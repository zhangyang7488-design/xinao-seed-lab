from __future__ import annotations

from pathlib import Path

import pytest

from xinao_coordination.agent_controller import AgentOperationController


def test_transport_provisioning_captures_binary_output_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> None:
        observed["command"] = command
        observed.update(kwargs)

    monkeypatch.setattr("xinao_coordination.agent_controller.subprocess.run", fake_run)

    AgentOperationController.ensure_transport(timeout_seconds=17)

    assert observed["capture_output"] is True
    assert observed["text"] is False
    assert "encoding" not in observed
    assert observed["timeout"] == 17


def test_submit_returns_after_durable_enqueue_without_transport_provisioning(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = AgentOperationController(db_path)

    def forbidden_ensure() -> None:
        raise AssertionError("foreground submit must not provision the transport")

    class FakeLauncher:
        pid = 12345
        _handle = 99

    monkeypatch.setattr(controller, "ensure_transport", forbidden_ensure)
    monkeypatch.setattr(
        "xinao_coordination.agent_controller.subprocess.Popen",
        lambda *args, **kwargs: FakeLauncher(),
    )
    monkeypatch.setattr("xinao_coordination.agent_controller.process_start_time_ms", lambda handle: 67890)

    result = controller.submit_and_start(
        actor="codex",
        prompt="asynchronous enqueue",
        session_name="async",
        cwd=tmp_path,
        deadline_seconds=60,
        max_attempts=1,
        replay_safe=False,
        idempotency_key="async-enqueue",
        metadata={},
    )

    assert result["operation"]["state"] == "queued"
    assert result["spawned"] is True
    assert result["start_pending"] is True
    assert result["bootstrap_pid"] == 12345
    assert result["worker_pid"] is None


def test_reconcile_is_explicitly_bounded(db_path: Path) -> None:
    result = AgentOperationController(db_path).reconcile(limit=5, max_runtime_seconds=1)
    assert result["bounded"] is True
    assert result["max_runtime_seconds"] == 1
    assert result["results"] == []


def test_submit_launcher_failure_gets_one_bounded_foreground_reconcile(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = AgentOperationController(db_path)
    monkeypatch.setattr(
        controller,
        "enqueue_start",
        lambda operation_id: {
            "operation": controller.store.get(operation_id)["operation"],
            "spawned": False,
            "reason": "launcher_spawn_failed_reconcile_will_retry",
        },
    )
    observed: dict[str, object] = {}

    def fake_reconcile(
        operation_id: str | None = None, *, limit: int, max_runtime_seconds: int
    ) -> dict[str, object]:
        observed.update(
            operation_id=operation_id,
            limit=limit,
            max_runtime_seconds=max_runtime_seconds,
        )
        operation = controller.store.get(str(operation_id))["operation"]
        return {
            "ok": True,
            "bounded": True,
            "results": [{"operation": operation, "spawned": True, "bootstrap_pid": 7}],
        }

    monkeypatch.setattr(controller, "reconcile", fake_reconcile)
    result = controller.submit_and_start(
        actor="codex",
        prompt="recover once",
        session_name="fallback",
        cwd=tmp_path,
        deadline_seconds=60,
        max_attempts=1,
        replay_safe=False,
        idempotency_key="fallback-once",
        metadata={},
    )

    assert observed["limit"] == 1
    assert observed["max_runtime_seconds"] == 90
    assert result["spawned"] is True
    assert result["start_reason"] == "foreground_bounded_reconcile"
    assert result["foreground_reconcile"]["bounded"] is True
