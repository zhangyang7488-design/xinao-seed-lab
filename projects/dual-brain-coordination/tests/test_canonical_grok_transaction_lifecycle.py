from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_canonical_grok_transaction.py"
SPEC = importlib.util.spec_from_file_location("xinao_canonical_grok_transaction", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _supervisor_routing(model: str) -> dict[str, object]:
    identity = {
        "provider_id": runner.CANONICAL_GROK_PROVIDER,
        "profile_ref": runner.CANONICAL_GROK_PROFILE,
        "model_id": model,
        "transport_id": runner.CANONICAL_GROK_TRANSPORT,
    }
    return {
        "task_separable": True,
        "context_inheritance_required": False,
        "benefit_close": False,
        "candidates": [
            {
                **identity,
                "declared_active": True,
                "healthy": True,
                "positive_benefit": True,
                "context_capable": False,
            }
        ],
        "supervisor_choice": identity,
    }


def _write_routing_policy(runtime_root: Path, *models: str) -> None:
    routes = [
        {
            "target": f"grok-{index}",
            "provider_id": runner.CANONICAL_GROK_PROVIDER,
            "profile_ref": runner.CANONICAL_GROK_PROFILE,
            "model_id": model,
            "transport_id": runner.CANONICAL_GROK_TRANSPORT,
        }
        for index, model in enumerate(models or ("grok-4.5",))
    ]
    path = runtime_root / "agent_runtime" / "routing_policy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "policy_version": "test-exact-routing-v1",
                "allowed_provider_ids": [runner.CANONICAL_GROK_PROVIDER],
                "routes": routes,
            }
        ),
        encoding="utf-8",
    )


def _identity(*, payload_sha256: str = "a" * 64) -> dict[str, object]:
    return {
        "schema_version": runner.TRANSACTION_IDENTITY_VERSION,
        "transaction_key_sha256": runner._sha256(b"logical-key"),
        "payload_sha256": payload_sha256,
        "task_queue": "queue-a",
        "worker_build_id": "build-a",
    }


@pytest.mark.parametrize(
    ("model", "is_escalated"),
    [
        ("grok-composer-2.5-fast", False),
        ("grok-4.5", True),
    ],
)
def test_canonical_selected_adapter_preserves_explicit_supervisor_model(
    tmp_path: Path,
    model: str,
    is_escalated: bool,
) -> None:
    _write_routing_policy(tmp_path, model)
    payload = runner._read_payload(
        json.dumps(
            {
                "grok_ready_frontier": [
                    {
                        "lane_id": "selected",
                        "prompt": "run the selected provider model",
                        "cwd": str(tmp_path),
                        "model": model,
                    }
                ],
                "grok_serial_reason": "one independently selected provider unit",
                "supervisor_routing": _supervisor_routing(model),
            }
        ).encode("utf-8"),
        runtime_root=tmp_path,
    )

    lane = payload["grok_ready_frontier"][0]
    assert lane["model"] == model
    assert lane["requested_model"] == model
    assert lane["is_escalated"] is is_escalated
    assert payload["supervisor_worker_decision"]["decision"] == "selected"
    assert payload["supervisor_worker_decision"]["selected_candidate"]["model_id"] == model
    assert len(payload["supervisor_worker_decision"]["decision_sha256"]) == 64
    assert "draft_model" not in runner.__dict__


def test_new_canonical_transaction_requires_supervisor_routing_before_effects(
    tmp_path: Path,
) -> None:
    _write_routing_policy(tmp_path, "grok-4.5")
    raw = json.dumps(
        {
            "grok_ready_frontier": [
                {
                    "lane_id": "missing-selection",
                    "prompt": "must be rejected before execution",
                    "cwd": str(tmp_path),
                    "model": "grok-4.5",
                }
            ],
            "grok_serial_reason": "one negative selection-admission unit",
        }
    ).encode("utf-8")

    with pytest.raises(ValueError, match="requires supervisor_routing"):
        runner._read_payload(raw, runtime_root=tmp_path)


def test_canonical_rejects_selected_model_that_differs_from_frontier(tmp_path: Path) -> None:
    _write_routing_policy(tmp_path, "grok-4.5", "grok-composer-2.5-fast")
    raw = json.dumps(
        {
            "grok_ready_frontier": [
                {
                    "lane_id": "model-mismatch",
                    "prompt": "must be rejected before execution",
                    "cwd": str(tmp_path),
                    "model": "grok-4.5",
                }
            ],
            "grok_serial_reason": "one negative model-binding unit",
            "supervisor_routing": _supervisor_routing("grok-composer-2.5-fast"),
        }
    ).encode("utf-8")

    with pytest.raises(ValueError, match="does not match canonical Grok frontier"):
        runner._read_payload(raw, runtime_root=tmp_path)


def test_canonical_missing_model_rejects_before_runtime_or_provider_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def forbidden_sync(label: str):
        def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            calls.append(label)
            raise AssertionError(f"{label} ran before explicit model admission")

        return fail

    def forbidden_async(label: str):
        async def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            calls.append(label)
            raise AssertionError(f"{label} ran before explicit model admission")

        return fail

    monkeypatch.setattr(runner, "_load_verified_deployment", forbidden_sync("deployment"))
    monkeypatch.setattr(runner, "_transaction_attempt", forbidden_sync("transaction"))
    monkeypatch.setattr(runner, "actual_mount_report", forbidden_sync("mount"))
    monkeypatch.setattr(runner, "CoordinationService", forbidden_sync("coordination"))
    monkeypatch.setattr(runner, "build_promoted_worker", forbidden_sync("worker"))
    monkeypatch.setattr(
        runner,
        "ensure_deployment_current",
        forbidden_async("deployment_update"),
    )
    monkeypatch.setattr(
        runner,
        "Client",
        SimpleNamespace(connect=forbidden_async("temporal_connect")),
    )

    payload_path = tmp_path / "missing-model.json"
    payload_path.write_text(
        json.dumps(
            {
                "grok_ready_frontier": [
                    {
                        "lane_id": "missing-model",
                        "prompt": "must fail before provider selection has an effect",
                        "cwd": str(tmp_path),
                    }
                ],
                "grok_serial_reason": "one negative model-admission unit",
            }
        ),
        encoding="utf-8",
    )
    run_root = tmp_path / "runs"

    with pytest.raises(ValueError, match="explicit supervisor-selected model"):
        asyncio.run(
            runner.run(
                payload_path=payload_path,
                db=tmp_path / "coordination.sqlite3",
                run_root=run_root,
                timeout_seconds=5.0,
                runtime_root=tmp_path,
            )
        )

    assert calls == []
    assert not run_root.exists()


def test_stable_transaction_retries_use_distinct_attempts_without_overwrite(
    tmp_path: Path,
) -> None:
    with runner._transaction_attempt(
        run_root=tmp_path,
        suffix="unused",
        transaction_key="logical-key",
        identity=_identity(),
    ) as first:
        first_result = first.run_dir / "result.json"
        first_result.write_text('{"attempt":1}\n', encoding="utf-8")
        first_bytes = first_result.read_bytes()

    with runner._transaction_attempt(
        run_root=tmp_path,
        suffix="unused",
        transaction_key="logical-key",
        identity=_identity(),
    ) as second:
        assert second.transaction_dir == first.transaction_dir
        assert second.run_dir != first.run_dir
        assert second.attempt_id == "attempt-0002"
        assert first_result.read_bytes() == first_bytes
        assert not (second.run_dir / "result.json").exists()


def test_stable_transaction_rejects_different_identity_before_new_attempt(
    tmp_path: Path,
) -> None:
    with runner._transaction_attempt(
        run_root=tmp_path,
        suffix="unused",
        transaction_key="logical-key",
        identity=_identity(),
    ) as first:
        transaction_dir = first.transaction_dir

    with (
        pytest.raises(runner.TransactionIdentityConflict, match="conflicts"),
        runner._transaction_attempt(
            run_root=tmp_path,
            suffix="unused",
            transaction_key="logical-key",
            identity=_identity(payload_sha256="c" * 64),
        ),
    ):
        pytest.fail("conflicting transaction reached its execution body")

    attempts = sorted((transaction_dir / "attempts").iterdir())
    assert [path.name for path in attempts] == ["attempt-0001"]


def test_stable_transaction_has_one_live_owner(tmp_path: Path) -> None:
    with (
        runner._transaction_attempt(
            run_root=tmp_path,
            suffix="unused",
            transaction_key="logical-key",
            identity=_identity(),
        ),
        pytest.raises(runner.TransactionBusyError, match="already active"),
        runner._transaction_attempt(
            run_root=tmp_path,
            suffix="unused",
            transaction_key="logical-key",
            identity=_identity(),
        ),
    ):
        pytest.fail("a second owner acquired the same transaction")


class _FakeHandle:
    def __init__(
        self,
        *,
        wait_forever: bool = False,
        status: str = "RUNNING",
        cancel_hangs: bool = False,
        cancel_changes_status: bool = True,
        first_run_id: str = "run-a",
    ) -> None:
        self.cancel_calls = 0
        self.wait_forever = wait_forever
        self.status = status
        self.cancel_hangs = cancel_hangs
        self.cancel_changes_status = cancel_changes_status
        self.first_run_id = first_run_id
        self.result_entered: asyncio.Event | None = None

    async def result(self) -> dict[str, object]:
        if not self.wait_forever:
            self.status = "COMPLETED"
            return {"ok": True}
        self.result_entered = asyncio.Event()
        self.result_entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def describe(self, *, rpc_timeout: object = None) -> object:
        del rpc_timeout
        return SimpleNamespace(
            status=SimpleNamespace(name=self.status),
            raw_info=SimpleNamespace(first_run_id=self.first_run_id),
        )

    async def cancel(
        self,
        *,
        reason: str = "",
        rpc_timeout: object = None,
    ) -> None:
        del reason, rpc_timeout
        self.cancel_calls += 1
        if self.cancel_hangs:
            await asyncio.Event().wait()
        if self.cancel_changes_status:
            self.status = "CANCELED"


class _FakeClient:
    def __init__(self, handle: _FakeHandle) -> None:
        self.handle = handle
        self.requests: list[tuple[str, str | None, str | None]] = []

    def get_workflow_handle(
        self,
        workflow_id: str,
        *,
        run_id: str | None = None,
        first_execution_run_id: str | None = None,
    ) -> _FakeHandle:
        self.requests.append((workflow_id, run_id, first_execution_run_id))
        return self.handle


def _started_record(run_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "xinao.canonical_grok_transaction.started.v1",
        "task_id": "task-a",
        "workflow_id": "workflow-a",
        "run_id": "run-a",
        "first_execution_run_id": "run-a",
        "task_queue": "queue-a",
        "attempt_id": "attempt-0001",
        "run_dir": str(run_dir),
    }


def test_on_started_failure_cancels_exact_workflow_and_records_abort(tmp_path: Path) -> None:
    handle = _FakeHandle()
    client = _FakeClient(handle)

    async def fail_after_start(_: dict[str, Any]) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        asyncio.run(
            runner._observe_started_workflow(
                client=client,
                started_record=_started_record(tmp_path),
                run_dir=tmp_path,
                timeout_seconds=30,
                handshake_path=None,
                on_started=fail_after_start,
            )
        )

    assert client.requests == [
        ("workflow-a", "run-a", None),
        ("workflow-a", "run-a", "run-a"),
        ("workflow-a", None, "run-a"),
    ]
    assert handle.cancel_calls == 1
    aborted = json.loads((tmp_path / "aborted.json").read_text(encoding="utf-8"))
    assert aborted["reason"] == "RuntimeError"
    assert aborted["workflow_cancel_requested"] is True
    assert aborted["workflow_terminal_confirmed"] is True
    assert aborted["workflow_cancel_confirmed"] is True


def test_stale_handshake_is_never_reused_and_cancels_started_workflow(
    tmp_path: Path,
) -> None:
    handle = _FakeHandle()
    client = _FakeClient(handle)
    handshake = tmp_path / "caller-handshake.json"
    handshake.write_text('{"stale":true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        asyncio.run(
            runner._observe_started_workflow(
                client=client,
                started_record=_started_record(tmp_path / "attempt"),
                run_dir=tmp_path / "attempt",
                timeout_seconds=30,
                handshake_path=handshake,
                on_started=None,
            )
        )

    assert handle.cancel_calls == 1
    assert handshake.read_text(encoding="utf-8") == '{"stale":true}\n'


def test_task_cancellation_cancels_exact_started_workflow(tmp_path: Path) -> None:
    async def exercise() -> _FakeHandle:
        handle = _FakeHandle(wait_forever=True)
        task = asyncio.create_task(
            runner._observe_started_workflow(
                client=_FakeClient(handle),
                started_record=_started_record(tmp_path),
                run_dir=tmp_path,
                timeout_seconds=30,
                handshake_path=None,
                on_started=None,
            )
        )
        while handle.result_entered is None:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return handle

    handle = asyncio.run(exercise())
    assert handle.cancel_calls == 1
    aborted = json.loads((tmp_path / "aborted.json").read_text(encoding="utf-8"))
    assert aborted["reason"] == "CancelledError"
    assert aborted["workflow_cancel_requested"] is True


def test_started_persistence_failure_still_cancels_exact_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle()

    def fail_write(_: Path, __: object) -> str:
        raise OSError("evidence volume unavailable")

    monkeypatch.setattr(runner, "_write_json_atomic", fail_write)
    with pytest.raises(OSError, match="evidence volume"):
        asyncio.run(
            runner._observe_started_workflow(
                client=_FakeClient(handle),
                started_record=_started_record(tmp_path),
                run_dir=tmp_path,
                timeout_seconds=30,
                handshake_path=None,
                on_started=None,
            )
        )
    assert handle.cancel_calls == 1


def test_hung_cancel_obeys_bounded_deadline() -> None:
    handle = _FakeHandle(cancel_hangs=True)
    started_at = time.monotonic()
    outcome = asyncio.run(
        runner._cancel_exact_workflow(
            handle,
            expected_first_execution_run_id="run-a",
            timeout_seconds=0.05,
        )
    )
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert outcome["workflow_cancel_requested"] is False
    assert outcome["workflow_terminal_confirmed"] is False
    assert outcome["workflow_cancel_confirmed"] is False
    assert outcome["workflow_cancel_error_type"] == "TimeoutError"


def test_completed_terminal_is_not_reported_as_cancel_confirmed() -> None:
    handle = _FakeHandle(status="COMPLETED", cancel_changes_status=False)
    outcome = asyncio.run(
        runner._cancel_exact_workflow(
            handle,
            expected_first_execution_run_id="run-a",
            timeout_seconds=0.5,
        )
    )

    assert outcome["workflow_cancel_requested"] is True
    assert outcome["workflow_terminal_confirmed"] is True
    assert outcome["workflow_cancel_confirmed"] is False
    assert outcome["workflow_cancel_terminal_status"] == "COMPLETED"


@pytest.mark.parametrize("observed_first_run_id", ["", "wrong-run"])
def test_cancel_confirmation_fails_closed_without_exact_chain_identity(
    observed_first_run_id: str,
) -> None:
    handle = _FakeHandle(status="CANCELED", first_run_id=observed_first_run_id)
    outcome = asyncio.run(
        runner._cancel_exact_workflow(
            handle,
            expected_first_execution_run_id="run-a",
            timeout_seconds=0.5,
        )
    )

    assert outcome["workflow_cancel_chain_identity_ok"] is False
    assert outcome["workflow_terminal_confirmed"] is False
    assert outcome["workflow_cancel_confirmed"] is False
    assert outcome["workflow_cancel_error_type"] == "WorkflowChainIdentityMismatch"


def test_success_describes_latest_bound_continue_as_new_chain(tmp_path: Path) -> None:
    original = _FakeHandle(status="CONTINUED_AS_NEW", cancel_changes_status=False)
    latest = _FakeHandle(status="COMPLETED", cancel_changes_status=False)

    async def result() -> dict[str, object]:
        return {"ok": True}

    original.result = result  # type: ignore[method-assign]

    class ChainClient:
        def get_workflow_handle(
            self,
            _: str,
            *,
            run_id: str | None = None,
            first_execution_run_id: str | None = None,
        ) -> _FakeHandle:
            assert first_execution_run_id in (None, "run-a")
            return original if run_id == "run-a" else latest

    _, description = asyncio.run(
        runner._observe_started_workflow(
            client=ChainClient(),
            started_record=_started_record(tmp_path),
            run_dir=tmp_path,
            timeout_seconds=1,
            handshake_path=None,
            on_started=None,
        )
    )

    assert description.status.name == "COMPLETED"
    assert description.raw_info.first_run_id == "run-a"


def test_fresh_start_resolves_temporal_chain_root_before_binding(tmp_path: Path) -> None:
    handle = _FakeHandle(first_run_id="root-run-a")
    client = _FakeClient(handle)
    started = _started_record(tmp_path)
    started["run_id"] = "continued-run-b"
    started["first_execution_run_id"] = "continued-run-b"
    binding = {"first_execution_run_id": "continued-run-b"}
    observed: dict[str, object] = {}

    async def capture_then_stop(value: dict[str, Any]) -> None:
        observed.update(value)
        raise RuntimeError("stop after binding")

    with pytest.raises(RuntimeError, match="stop after binding"):
        asyncio.run(
            runner._observe_started_workflow(
                client=client,
                started_record=started,
                run_dir=tmp_path,
                timeout_seconds=1,
                handshake_path=None,
                on_started=capture_then_stop,
                execution_binding=binding,
                resolve_first_execution_run_id=True,
            )
        )

    assert started["first_execution_run_id"] == "root-run-a"
    assert binding["first_execution_run_id"] == "root-run-a"
    assert observed["first_execution_run_id"] == "root-run-a"


def test_cancel_cleanup_failure_does_not_mask_original_observe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def cleanup_failure(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        raise RuntimeError("cleanup failed")

    async def original_failure(_: dict[str, Any]) -> None:
        raise ValueError("original callback failed")

    monkeypatch.setattr(runner, "_cancel_exact_workflow", cleanup_failure)
    with pytest.raises(ValueError, match="original callback failed"):
        asyncio.run(
            runner._observe_started_workflow(
                client=_FakeClient(_FakeHandle()),
                started_record=_started_record(tmp_path),
                run_dir=tmp_path,
                timeout_seconds=1,
                handshake_path=None,
                on_started=original_failure,
            )
        )

    aborted = json.loads((tmp_path / "aborted.json").read_text(encoding="utf-8"))
    assert aborted["reason"] == "ValueError"
    assert aborted["workflow_cancel_attempted"] is True
    assert aborted["workflow_cancel_error_type"] == "RuntimeError"


def test_process_environment_guard_rejects_in_process_cross_talk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XINAO_COORD_DB", "before")
    monkeypatch.delenv("XINAO_TEMPORAL_TASK_QUEUE", raising=False)
    with runner._exclusive_process_environment(
        {"XINAO_COORD_DB": "db-a", "XINAO_TEMPORAL_TASK_QUEUE": "queue-a"}
    ):
        assert runner.os.environ["XINAO_COORD_DB"] == "db-a"
        with (
            pytest.raises(runner.TransactionBusyError, match="process-global"),
            runner._exclusive_process_environment(
                {"XINAO_COORD_DB": "db-b", "XINAO_TEMPORAL_TASK_QUEUE": "queue-b"}
            ),
        ):
            pytest.fail("a second in-process transaction changed global routing")

    assert runner.os.environ["XINAO_COORD_DB"] == "before"
    assert "XINAO_TEMPORAL_TASK_QUEUE" not in runner.os.environ


def test_execution_binding_reconnects_only_exact_stable_run(tmp_path: Path) -> None:
    path = tmp_path / "execution.json"
    binding = {
        "schema_version": runner.TRANSACTION_EXECUTION_VERSION,
        "transaction_key_semantics": runner.TRANSACTION_KEY_SEMANTICS,
        "transaction_identity_sha256": "b" * 64,
        "task_queue": "queue-a",
        "task_id": "task-a",
        "workflow_id": "workflow-a",
        "run_id": "run-a",
        "first_execution_run_id": "run-a",
    }
    runner._write_json_exclusive(path, binding)

    assert (
        runner._load_execution_binding(
            path,
            transaction_identity_sha256="b" * 64,
            task_queue="queue-a",
        )
        == binding
    )
    with pytest.raises(runner.TransactionIdentityConflict, match="conflicts"):
        runner._load_execution_binding(
            path,
            transaction_identity_sha256="c" * 64,
            task_queue="queue-a",
        )


def test_attempt_outcome_carries_chain_identity_verdict(tmp_path: Path) -> None:
    transaction = runner.TransactionAttempt(
        transaction_dir=tmp_path,
        run_dir=tmp_path / "attempt-0001",
        attempt_id="attempt-0001",
        transaction_key_sha256="a" * 64,
        transaction_identity_sha256="b" * 64,
    )
    outcome = runner._attempt_outcome(
        transaction=transaction,
        status="failed",
        phase="observing_workflow",
        cancellation={"workflow_cancel_chain_identity_ok": True},
    )
    assert outcome["workflow_cancel_chain_identity_ok"] is True


def test_mount_mismatch_rejects_before_temporal_worker_workflow_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {
        "coordination_service": 0,
        "client_connect": 0,
        "build_worker": 0,
        "ensure_deployment": 0,
        "create_kernel_task": 0,
        "observe_workflow": 0,
        "provider_activity": 0,
    }

    def forbidden_sync(label: str):
        def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            calls[label] += 1
            raise AssertionError(f"{label} ran after mount mismatch")

        return fail

    def forbidden_async(label: str):
        async def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            calls[label] += 1
            raise AssertionError(f"{label} ran after mount mismatch")

        return fail

    mount_report = {
        "schema_version": "xinao.worker_repo_mount_identity.v1",
        "ok": False,
        "named_blocker": "WORKER_REPO_MOUNT_MISMATCH",
        "provider_invocation_allowed": False,
        "expected_repo_root": str(runner.REPO_ROOT),
        "issues": [
            {
                "code": "SOURCE_MISMATCH",
                "destination": "/app/services",
                "expected_source": str(runner.REPO_ROOT / "services"),
                "observed_source": r"E:\XINAO_RESEARCH_WORKSPACES\S\services",
            }
        ],
    }
    inspected_roots: list[Path] = []

    def rejected_mount_report(repo_root: Path) -> dict[str, object]:
        inspected_roots.append(repo_root)
        return mount_report

    provider_activity = forbidden_async("provider_activity")
    monkeypatch.setattr(runner, "actual_mount_report", rejected_mount_report)
    monkeypatch.setattr(runner, "CoordinationService", forbidden_sync("coordination_service"))
    monkeypatch.setattr(
        runner,
        "Client",
        SimpleNamespace(connect=forbidden_async("client_connect")),
    )
    monkeypatch.setattr(runner, "build_promoted_worker", forbidden_sync("build_worker"))
    monkeypatch.setattr(
        runner,
        "ensure_deployment_current",
        forbidden_async("ensure_deployment"),
    )
    monkeypatch.setattr(
        runner,
        "create_kernel_backed_canary_task",
        forbidden_sync("create_kernel_task"),
    )
    monkeypatch.setattr(
        runner,
        "_observe_started_workflow",
        forbidden_async("observe_workflow"),
    )
    monkeypatch.setattr(runner, "PROMOTED_ACTIVITIES", (provider_activity,))
    monkeypatch.setattr(
        runner,
        "_load_verified_deployment",
        lambda: {"deployment_name": "deployment-a", "build_id": "build-a"},
    )
    monkeypatch.setattr(
        runner,
        "validate_ready_frontier",
        lambda value, **kwargs: list(value or []),
    )

    payload_path = tmp_path / "payload.json"
    _write_routing_policy(tmp_path, "grok-4.5")
    payload_path.write_text(
        json.dumps(
            {
                "grok_ready_frontier": [{"model": "grok-4.5"}],
                "supervisor_routing": _supervisor_routing("grok-4.5"),
            }
        ),
        encoding="utf-8",
    )
    output = asyncio.run(
        runner.run(
            payload_path=payload_path,
            db=tmp_path / "coordination.sqlite3",
            run_root=tmp_path / "runs",
            timeout_seconds=5.0,
            runtime_root=tmp_path,
            transaction_key="mount-mismatch-operation",
        )
    )

    assert inspected_roots == [runner.REPO_ROOT]
    assert calls == {key: 0 for key in calls}
    assert output["ok"] is False
    assert output["provider_invocation_allowed"] is False
    assert output["named_blocker"] == "WORKER_REPO_MOUNT_MISMATCH"
    assert output["workflow_status"] == "not_started"
    assert output["token_accounting"] == {
        "provider_attempt_count": 0,
        "total_tokens": 0,
    }

    run_dir = Path(output["run_dir"])
    persisted_mount = json.loads((run_dir / "mount_preflight.json").read_text(encoding="utf-8"))
    persisted_result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    persisted_outcome = json.loads((run_dir / "attempt_outcome.json").read_text(encoding="utf-8"))
    assert persisted_mount == mount_report
    assert persisted_result == output
    assert persisted_outcome["status"] == "rejected"
    assert persisted_outcome["phase"] == "worker_mount_rejected"
    assert not (run_dir / "started.json").exists()
    assert not (Path(output["transaction_dir"]) / "execution.json").exists()


def test_run_reconnects_same_key_without_starting_a_second_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters = {"create": 0, "start": 0, "connect": 0}

    class FakeService:
        def __init__(self, _: Path) -> None:
            pass

        def temporal_start_promoted(self, **_: object) -> dict[str, str]:
            counters["start"] += 1
            return {"workflow_id": "workflow-a", "run_id": "continued-run-b"}

    class FakeWorker:
        async def __aenter__(self) -> FakeWorker:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

    handle = _FakeHandle(first_run_id="root-run-a")
    client = _FakeClient(handle)

    async def connect(*_: object, **__: object) -> _FakeClient:
        counters["connect"] += 1
        return client

    async def ensure(*_: object, **__: object) -> None:
        return None

    def create(*_: object, **__: object) -> str:
        counters["create"] += 1
        return "task-a"

    async def successful_result() -> dict[str, object]:
        handle.status = "COMPLETED"
        return {
            "ok": True,
            "terminal_status": "completed",
            "grok_fanin": {"ok": True},
        }

    handle.result = successful_result  # type: ignore[method-assign]
    monkeypatch.setattr(runner, "CoordinationService", FakeService)
    monkeypatch.setattr(runner, "create_kernel_backed_canary_task", create)
    monkeypatch.setattr(runner, "build_promoted_worker", lambda *args, **kwargs: FakeWorker())
    monkeypatch.setattr(runner, "ensure_deployment_current", ensure)
    monkeypatch.setattr(runner, "Client", SimpleNamespace(connect=connect))
    monkeypatch.setattr(
        runner,
        "actual_mount_report",
        lambda _repo_root: {
            "schema_version": "xinao.worker_repo_mount_identity.v1",
            "ok": True,
            "named_blocker": None,
            "provider_invocation_allowed": True,
        },
    )
    monkeypatch.setattr(
        runner,
        "_load_verified_deployment",
        lambda: {"deployment_name": "deployment-a", "build_id": "build-a"},
    )
    monkeypatch.setattr(
        runner,
        "validate_ready_frontier",
        lambda value, **kwargs: list(value or []),
    )

    payload_path = tmp_path / "payload.json"
    _write_routing_policy(tmp_path, "grok-4.5")
    payload_path.write_text(
        json.dumps(
            {
                "grok_ready_frontier": [{"model": "grok-4.5"}],
                "supervisor_routing": _supervisor_routing("grok-4.5"),
            }
        ),
        encoding="utf-8",
    )
    arguments = {
        "payload_path": payload_path,
        "db": tmp_path / "coordination.sqlite3",
        "run_root": tmp_path / "runs",
        "timeout_seconds": 5.0,
        "runtime_root": tmp_path,
        "transaction_key": "same-logical-operation",
    }

    first = asyncio.run(runner.run(**arguments))
    second = asyncio.run(runner.run(**arguments))

    assert first["execution_reused"] is False
    assert second["execution_reused"] is True
    assert first["run_id"] == second["run_id"] == "continued-run-b"
    assert first["first_execution_run_id"] == "root-run-a"
    assert second["first_execution_run_id"] == "root-run-a"
    assert counters == {"create": 1, "start": 1, "connect": 2}
    transaction_dir = Path(first["transaction_dir"])
    execution = json.loads((transaction_dir / "execution.json").read_text(encoding="utf-8"))
    assert execution["run_id"] == "continued-run-b"
    assert execution["first_execution_run_id"] == "root-run-a"
    persisted_results = sorted(transaction_dir.glob("attempts/*/result.json"))
    assert len(persisted_results) == 2
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["first_execution_run_id"] == "root-run-a"
        for path in persisted_results
    )
    outcomes = sorted(transaction_dir.glob("attempts/*/attempt_outcome.json"))
    assert len(outcomes) == 2
    assert all(json.loads(path.read_text(encoding="utf-8"))["status"] == "accepted" for path in outcomes)

    async def fail_connect(*_: object, **__: object) -> object:
        raise ConnectionError("temporal unavailable")

    monkeypatch.setattr(runner, "Client", SimpleNamespace(connect=fail_connect))
    failed_arguments = dict(arguments)
    failed_arguments["transaction_key"] = "connect-failure-operation"
    with pytest.raises(ConnectionError, match="temporal unavailable"):
        asyncio.run(runner.run(**failed_arguments))
    failed_sha = runner._sha256(b"connect-failure-operation")
    failed_dir = arguments["run_root"] / f"canonical-grok-key-{failed_sha[:20]}"
    failure = json.loads(
        (failed_dir / "attempts" / "attempt-0001" / "attempt_outcome.json").read_text(encoding="utf-8")
    )
    assert failure["status"] == "failed"
    assert failure["phase"] == "connecting_temporal"
    assert failure["error_type"] == "ConnectionError"


def test_handshake_requires_unique_caller_nonce_before_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "validate_ready_frontier",
        lambda value, **kwargs: list(value or []),
    )
    payload_path = tmp_path / "payload.json"
    _write_routing_policy(tmp_path, "grok-4.5")
    payload_path.write_text(
        json.dumps(
            {
                "grok_ready_frontier": [{"model": "grok-4.5"}],
                "supervisor_routing": _supervisor_routing("grok-4.5"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="caller-generated nonce"):
        asyncio.run(
            runner.run(
                payload_path=payload_path,
                db=tmp_path / "coordination.sqlite3",
                run_root=tmp_path / "runs",
                timeout_seconds=5.0,
                runtime_root=tmp_path,
                transaction_key="handshake-test",
                handshake_path=tmp_path / "handshake.json",
            )
        )

    with pytest.raises(ValueError, match="first execution run id"):
        asyncio.run(
            runner.run(
                payload_path=payload_path,
                db=tmp_path / "coordination.sqlite3",
                run_root=tmp_path / "runs",
                timeout_seconds=5.0,
                runtime_root=tmp_path,
                transaction_key="resume-chain-test",
                resume_workflow_id="workflow-a",
                resume_run_id="continued-run-b",
                resume_task_queue="queue-a",
                resume_task_id="task-a",
            )
        )
