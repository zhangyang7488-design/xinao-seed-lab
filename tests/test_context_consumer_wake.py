from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import scripts.codex_situation_context_hook as hook_adapter
import scripts.context_rollout_consumer as rollout_consumer
import services.xinao_perpetual_world_compute.controller as controller_module

BASE_NOW = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)


def _fake_windows_root(tmp_path: Path) -> Path:
    root = tmp_path / "Windows"
    executable = root / "System32" / "schtasks.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test-schtasks")
    return root


def test_hook_lifecycle_wake_is_mounted_hidden_and_nonblocking(
    tmp_path: Path, monkeypatch
) -> None:
    root = _fake_windows_root(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_runner(command: list[str], **kwargs: object) -> object:
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr(
        hook_adapter,
        "evaluate_mount",
        lambda _event: SimpleNamespace(mounted=True),
    )
    event = {"hook_event_name": "Stop"}
    assert hook_adapter.request_context_consumer_wake(
        event,
        runner=fake_runner,
        system_root=str(root),
    )
    assert calls[0][0] == [
        str(root / "System32" / "schtasks.exe"),
        "/Run",
        "/TN",
        r"\XINAO-S-Context-Rollout-Consumer-v1",
    ]
    assert calls[0][1]["close_fds"] is True
    assert calls[0][1]["creationflags"] == getattr(
        hook_adapter.subprocess, "CREATE_NO_WINDOW", 0
    )


def test_hook_wake_skips_hot_prompt_and_unmounted_body(tmp_path: Path, monkeypatch) -> None:
    root = _fake_windows_root(tmp_path)
    calls: list[object] = []

    def fake_runner(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(
        hook_adapter,
        "evaluate_mount",
        lambda _event: SimpleNamespace(mounted=True),
    )
    assert not hook_adapter.request_context_consumer_wake(
        {"hook_event_name": "UserPromptSubmit"},
        runner=fake_runner,
        system_root=str(root),
    )
    monkeypatch.setattr(
        hook_adapter,
        "evaluate_mount",
        lambda _event: SimpleNamespace(mounted=False),
    )
    assert not hook_adapter.request_context_consumer_wake(
        {"hook_event_name": "SessionEnd"},
        runner=fake_runner,
        system_root=str(root),
    )
    assert calls == []


def test_hook_wake_failure_is_fail_open(tmp_path: Path, monkeypatch) -> None:
    root = _fake_windows_root(tmp_path)
    monkeypatch.setattr(
        hook_adapter,
        "evaluate_mount",
        lambda _event: SimpleNamespace(mounted=True),
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("task scheduler unavailable")

    assert not hook_adapter.request_context_consumer_wake(
        {"hook_event_name": "PostCompact"},
        runner=fail,
        system_root=str(root),
    )


def test_hook_adapter_still_requests_recovery_wake_when_capture_fails(
    monkeypatch,
) -> None:
    event = {"hook_event_name": "SessionEnd", "cwd": str(hook_adapter.REPO_ROOT)}
    observed: list[dict[str, object]] = []
    output = io.StringIO()

    monkeypatch.setattr(hook_adapter.sys, "stdin", io.StringIO(json.dumps(event)))
    monkeypatch.setattr(hook_adapter.sys, "stdout", output)
    monkeypatch.setattr(
        hook_adapter,
        "handle_hook_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("capture failed")),
    )
    monkeypatch.setattr(
        hook_adapter,
        "request_context_consumer_wake",
        lambda value: observed.append(dict(value)) or True,
    )

    assert hook_adapter.main() == 0
    assert observed[0]["hook_event_name"] == "SessionEnd"
    assert json.loads(output.getvalue()) == {"continue": True}


def test_controller_wake_is_limited_to_named_runtime_state(
    tmp_path: Path,
) -> None:
    windows_root = _fake_windows_root(tmp_path)
    runtime_root = tmp_path / "runtime"
    state_path = runtime_root / "runs" / "run-1" / "controller_state.json"
    state_path.parent.mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_runner(command: list[str], **_kwargs: object) -> object:
        calls.append(command)
        return object()

    assert controller_module.request_context_consumer_wake(
        controller_state_path=state_path,
        allowed_runtime_roots=[runtime_root],
        runner=fake_runner,
        system_root=str(windows_root),
    )
    assert calls == [
        [
            str(windows_root / "System32" / "schtasks.exe"),
            "/Run",
            "/TN",
            r"\XINAO-S-Context-Rollout-Consumer-v1",
        ]
    ]
    assert not controller_module.request_context_consumer_wake(
        controller_state_path=tmp_path / "outside" / "controller_state.json",
        allowed_runtime_roots=[runtime_root],
        runner=fake_runner,
        system_root=str(windows_root),
    )


def test_controller_publish_wakes_only_after_state_commit(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "controller_state.json"
    wake_observations: list[bool] = []

    def observe_committed_state(*, controller_state_path: Path) -> bool:
        wake_observations.append(controller_state_path.is_file())
        return True

    monkeypatch.setattr(
        controller_module,
        "request_context_consumer_wake",
        observe_committed_state,
    )
    fake = SimpleNamespace(
        _state_lock=threading.RLock(),
        _lineage_states={},
        config={"run_id": "run-1"},
        schemas={"controller": controller_module.CONTROLLER_SCHEMA},
        _started_at="2026-08-13T10:00:00+00:00",
        stop_path=tmp_path / "stop.json",
        _quiescing=threading.Event(),
        _active_processes={},
        _thread_errors={},
        controller_state_path=state_path,
    )
    controller_module.PerpetualController.publish_controller_state(fake, "RUNNING")
    assert wake_observations == [True]


def test_event_wake_retries_stable_observation_in_one_task_invocation(
    monkeypatch,
) -> None:
    receipts = [
        {"status": "completed", "counts": {"awaiting_stable": 1}},
        {"status": "completed", "counts": {"imported": 1}},
    ]
    observed_now: list[datetime | None] = []
    delays: list[float] = []

    def fake_run_consumer(**kwargs: object) -> dict[str, object]:
        observed_now.append(kwargs.get("now"))  # type: ignore[arg-type]
        return receipts.pop(0)

    monkeypatch.setattr(rollout_consumer, "run_consumer", fake_run_consumer)
    result = rollout_consumer.run_consumer_to_quiescence(
        now=BASE_NOW,
        sleeper=lambda value: delays.append(value),
    )
    assert result["counts"] == {"imported": 1}
    assert delays == [rollout_consumer.QUIESCENCE_RETRY_DELAYS_SECONDS[0]]
    assert observed_now == [
        BASE_NOW,
        BASE_NOW
        + rollout_consumer.timedelta(
            seconds=rollout_consumer.QUIESCENCE_RETRY_DELAYS_SECONDS[0]
        ),
    ]


def test_event_wake_retry_is_strictly_bounded(monkeypatch) -> None:
    call_count = 0
    delays: list[float] = []

    def always_growing(**_kwargs: object) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {"status": "completed", "counts": {"awaiting_stable": 1}}

    monkeypatch.setattr(rollout_consumer, "run_consumer", always_growing)
    result = rollout_consumer.run_consumer_to_quiescence(
        now=BASE_NOW,
        sleeper=lambda value: delays.append(value),
    )
    assert result["counts"] == {"awaiting_stable": 1}
    assert call_count == 1 + len(rollout_consumer.QUIESCENCE_RETRY_DELAYS_SECONDS)
    assert delays == list(rollout_consumer.QUIESCENCE_RETRY_DELAYS_SECONDS)


def test_event_wake_retry_still_drains_other_files_when_one_file_is_degraded(
    monkeypatch,
) -> None:
    receipts = [
        {
            "status": "completed_with_errors",
            "counts": {"awaiting_stable": 1, "file_error": 1},
        },
        {
            "status": "completed_with_errors",
            "counts": {"imported": 1, "file_error": 1},
        },
    ]
    delays: list[float] = []

    monkeypatch.setattr(
        rollout_consumer,
        "run_consumer",
        lambda **_kwargs: receipts.pop(0),
    )
    result = rollout_consumer.run_consumer_to_quiescence(
        now=BASE_NOW,
        sleeper=lambda value: delays.append(value),
    )
    assert result["counts"] == {"imported": 1, "file_error": 1}
    assert delays == [rollout_consumer.QUIESCENCE_RETRY_DELAYS_SECONDS[0]]
