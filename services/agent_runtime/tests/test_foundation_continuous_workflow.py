from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from services.agent_runtime.foundation_continuous_workflow import (
    FoundationContinuousWorkflowV1,
    FoundationWaveChildWorkflowV1,
    _accept_external_signal,
    _apply_control,
    _continuation_input,
    _continue_as_new_due,
    _initial_child_state,
    _initial_parent_state,
    persist_foundation_state,
    reconcile_foundation_frontier,
    verify_external_wave_result,
)
from temporalio import workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


@workflow.defn(name="FoundationContinuousFakeExternalWorkflow")
class _FakeExternalWorkflow:
    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: False)
        return "unreachable"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _parent_initial(runtime: Path, frontier: Path, **extra: object) -> dict[str, object]:
    return {
        "operation_id": "foundation-op",
        "runtime_root": str(runtime),
        "frontier_ref": str(frontier),
        "default_wait_seconds": 3_600,
        **extra,
    }


def _result_payload(
    *,
    payload_path: Path,
    payload_sha256: str,
    model: str = "grok-4.5",
) -> dict[str, object]:
    return {
        "ok": True,
        "workflow_status": "completed",
        "workflow_id": "external-grok-wave-d",
        "run_id": "external-run-d",
        "task_queue": "xinao-canonical-grok-host-v1",
        "payload_path": str(payload_path),
        "payload_sha256": payload_sha256,
        "result": {
            "grok_fanin": {
                "ok": True,
                "correlation_id": "foundation-op:wave-d",
                "parent_operation_id": "foundation-op",
                "lane_count": 1,
                "succeeded": 1,
                "failed": 0,
                "provider_id": "grok_acpx_headless",
                "model": model,
            }
        },
    }


def test_control_is_idempotent_and_identity_bound(tmp_path: Path) -> None:
    state = _initial_parent_state(_parent_initial(tmp_path, tmp_path / "frontier.json"))
    pause = {
        "operation_id": "control-1",
        "action": "PAUSE",
        "reason": "operator pause",
    }
    first = _apply_control(state, pause)
    second = _apply_control(state, pause)
    assert first == second
    assert state["paused"] is True
    assert len(state["control_audit"]) == 1

    no_op = _apply_control(
        state,
        {
            "operation_id": "control-2",
            "action": "PAUSE",
            "reason": "repeat with a new operation",
        },
    )
    assert no_op["no_op"] is True
    with pytest.raises(ValueError, match="identity conflict"):
        _apply_control(state, {**pause, "action": "STOP"})

    _apply_control(
        state,
        {
            "operation_id": "control-3",
            "action": "RESUME",
            "reason": "continue",
        },
    )
    stopped = _apply_control(
        state,
        {
            "operation_id": "control-4",
            "action": "STOP",
            "reason": "operator stop",
        },
    )
    assert state["paused"] is False
    assert state["stop_requested"] is True
    assert stopped["no_op"] is False


def test_external_callbacks_are_idempotent_and_reject_run_drift() -> None:
    state = _initial_child_state(
        {
            "operation_id": "foundation-op",
            "wave_id": "wave-d",
            "correlation_id": "foundation-op:wave-d",
        }
    )
    started = {
        "signal_id": "started-1",
        "wave_id": "wave-d",
        "workflow_id": "external-grok-wave-d",
        "run_id": "external-run-d",
        "task_queue": "xinao-canonical-grok-host-v1",
    }
    _accept_external_signal(state, "started", started)
    _accept_external_signal(state, "started", started)
    assert state["status"] == "EXTERNAL_RUNNING"
    assert state["duplicate_signals"] == 1

    _accept_external_signal(
        state,
        "completed",
        {
            "signal_id": "completed-1",
            "wave_id": "wave-d",
            "workflow_id": "external-grok-wave-d",
            "run_id": "wrong-run",
            "result_ref": "result.json",
            "result_sha256": "a" * 64,
        },
    )
    assert state["status"] == "EXTERNAL_FAILED"
    assert state["external_failed"]["error_type"] == "EXTERNAL_RUN_IDENTITY_CONFLICT"


def test_external_callbacks_require_canonical_start_before_completion() -> None:
    state = _initial_child_state(
        {
            "operation_id": "foundation-op",
            "wave_id": "wave-d",
            "correlation_id": "foundation-op:wave-d",
        }
    )
    _accept_external_signal(
        state,
        "completed",
        {
            "signal_id": "completed-before-start",
            "wave_id": "wave-d",
            "workflow_id": "external-grok-wave-d",
            "run_id": "external-run-d",
            "result_ref": "result.json",
            "result_sha256": "a" * 64,
        },
    )
    assert state["external_failed"]["error_type"] == "START_CALLBACK_MISSING"

    wrong_queue = _initial_child_state(
        {
            "operation_id": "foundation-op",
            "wave_id": "wave-d",
            "correlation_id": "foundation-op:wave-d",
        }
    )
    _accept_external_signal(
        wrong_queue,
        "started",
        {
            "signal_id": "started-wrong-queue",
            "wave_id": "wave-d",
            "workflow_id": "external-grok-wave-d",
            "run_id": "external-run-d",
            "task_queue": "uncanonical-queue",
        },
    )
    assert wrong_queue["external_failed"]["error_type"] == "EXTERNAL_TASK_QUEUE_CONFLICT"


def test_reconcile_and_result_verification_use_only_runtime_refs(tmp_path: Path) -> None:
    payload = tmp_path / "state" / "payloads" / "wave-d.json"
    result = tmp_path / "state" / "results" / "wave-d.json"
    frontier = tmp_path / "state" / "frontier.json"
    _write(payload, {"ready_frontier": "wave-d"})
    payload_sha256 = hashlib.sha256(payload.read_bytes()).hexdigest()
    _write(
        result,
        _result_payload(
            payload_path=payload,
            payload_sha256=payload_sha256,
            model="grok-4.5",
        ),
    )
    _write(
        frontier,
        {
            "ready_frontier": [
                {
                    "wave_id": "wave-d",
                    "payload_ref": str(payload),
                    "correlation_id": "foundation-op:wave-d",
                }
            ],
            "wait_seconds": 600,
        },
    )
    decision = reconcile_foundation_frontier(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "foundation-op",
            "frontier_ref": str(frontier),
            "completed_wave_ids": [],
        }
    )
    assert decision["action"] == "DISPATCH_EXTERNAL"
    assert decision["wave"]["payload_sha256"] == hashlib.sha256(payload.read_bytes()).hexdigest()

    raw = result.read_bytes()
    verified = verify_external_wave_result(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "foundation-op",
            "wave_id": "wave-d",
            "correlation_id": "foundation-op:wave-d",
            "result_ref": str(result),
            "result_sha256": hashlib.sha256(raw).hexdigest(),
            "payload_ref": str(payload),
            "payload_sha256": payload_sha256,
            "external_task_queue": "xinao-canonical-grok-host-v1",
            "external_provider_id": "grok_acpx_headless",
            "external_model": "grok-4.5",
            "external_workflow_id": "external-grok-wave-d",
            "external_run_id": "external-run-d",
        }
    )
    assert verified["ok"] is True
    assert verified["result_ref"] == str(result)

    escaped = tmp_path.parent / "outside.json"
    _write(
        escaped,
        _result_payload(
            payload_path=payload,
            payload_sha256=payload_sha256,
            model="grok-4.5",
        ),
    )
    with pytest.raises(ValueError, match="escapes runtime root"):
        verify_external_wave_result(
            {
                "runtime_root": str(tmp_path),
                "operation_id": "foundation-op",
                "wave_id": "wave-d",
                "correlation_id": "foundation-op:wave-d",
                "result_ref": str(escaped),
            }
        )


def test_atomic_state_writer_emits_idempotent_snapshot_pointer_and_request(
    tmp_path: Path,
) -> None:
    snapshot = {
        "operation_id": "foundation-op",
        "status": "WAITING_EXTERNAL",
        "current_wave": {
            "wave_id": "wave-d",
            "wave_sequence": 1,
            "correlation_id": "foundation-op:wave-d",
            "payload_ref": str(tmp_path / "payload.json"),
            "payload_sha256": "b" * 64,
            "child_workflow_id": "foundation-parent-wave-000001",
            "child_run_id": "child-run-1",
        },
    }
    call = {
        "runtime_root": str(tmp_path),
        "operation_id": "foundation-op",
        "entity_kind": "parent",
        "entity_id": "foundation-parent",
        "snapshot": snapshot,
    }
    first = persist_foundation_state(call)
    second = persist_foundation_state(call)
    assert first == second
    assert Path(first["artifact_ref"]).is_file()
    assert Path(first["latest_ref"]).is_file()
    request = json.loads(Path(first["request_ref"]).read_text(encoding="utf-8"))
    assert request["callback_workflow_id"] == "foundation-parent-wave-000001"
    assert request["expected_external_task_queue"] == "xinao-canonical-grok-host-v1"
    assert request["expected_external_provider_id"] == "grok_acpx_headless"
    assert request["expected_external_model"] == "grok-4.5"
    assert request["callback_signals"] == {
        "started": "external_started",
        "completed": "external_completed",
        "failed": "external_failed",
    }


def test_continue_as_new_payload_is_compact_and_preserves_global_progress(
    tmp_path: Path,
) -> None:
    state = _initial_parent_state(
        _parent_initial(tmp_path, tmp_path / "frontier.json", max_waves_per_run=1)
    )
    state["waves_since_continue_as_new"] = 1
    state["waves_completed"] = 3
    state["completed_wave_ids"] = ["wave-a", "wave-b", "wave-c"]
    state["current_wave"] = None
    state["last_decision"] = {
        "action": "DISPATCH_EXTERNAL",
        "wave": {"large": "not-carried"},
        "frontier_sha256": "c" * 64,
    }
    assert _continue_as_new_due(state, suggested=False) is True
    continuation = _continuation_input(state)
    resumed = _initial_parent_state(continuation)
    assert resumed["generation"] == 1
    assert resumed["waves_since_continue_as_new"] == 0
    assert resumed["waves_completed"] == 3
    assert resumed["completed_wave_ids"] == ["wave-a", "wave-b", "wave-c"]
    assert "wave" not in resumed["last_decision"]


async def _query_until(handle, predicate, *, attempts: int = 200) -> dict[str, object]:
    last: dict[str, object] = {}
    for _ in range(attempts):
        last = await handle.query("state")
        if predicate(last):
            return last
        await asyncio.sleep(0.01)
    raise AssertionError(f"workflow query did not reach expected state: {last}")


def test_time_skipping_parent_reconciles_again_after_external_wave(tmp_path: Path) -> None:
    payload = tmp_path / "state" / "payloads" / "wave-d.json"
    result_path = tmp_path / "state" / "results" / "wave-d.json"
    frontier = tmp_path / "state" / "frontier.json"
    _write(payload, {"goal": "bounded external Grok wave"})
    payload_sha256 = hashlib.sha256(payload.read_bytes()).hexdigest()
    result_value = _result_payload(payload_path=payload, payload_sha256=payload_sha256)
    _write(result_path, result_value)
    _write(
        frontier,
        {
            "ready_frontier": [
                {
                    "wave_id": "wave-d",
                    "payload_ref": str(payload),
                    "correlation_id": "foundation-op:wave-d",
                    "submission_timeout_seconds": 3_600,
                }
            ],
            "wait_seconds": 3_600,
        },
    )

    async def exercise() -> tuple[dict[str, object], dict[str, object]]:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    env.client,
                    task_queue="foundation-continuous-test",
                    workflows=[
                        FoundationContinuousWorkflowV1,
                        FoundationWaveChildWorkflowV1,
                    ],
                    activities=[
                        reconcile_foundation_frontier,
                        persist_foundation_state,
                        verify_external_wave_result,
                    ],
                    activity_executor=executor,
                ):
                    parent = await env.client.start_workflow(
                        FoundationContinuousWorkflowV1.run,
                        _parent_initial(tmp_path, frontier),
                        id="foundation-continuous-parent-test",
                        task_queue="foundation-continuous-test",
                    )
                    waiting = await _query_until(
                        parent,
                        lambda value: bool(value.get("current_wave")),
                    )
                    current = waiting["current_wave"]
                    assert isinstance(current, dict)
                    child = env.client.get_workflow_handle(str(current["child_workflow_id"]))
                    await child.signal(
                        "external_started",
                        {
                            "signal_id": "started-1",
                            "wave_id": "wave-d",
                            "workflow_id": "external-grok-wave-d",
                            "run_id": "external-run-d",
                            "task_queue": "xinao-canonical-grok-host-v1",
                        },
                    )
                    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
                    await child.signal(
                        "external_completed",
                        {
                            "signal_id": "completed-1",
                            "wave_id": "wave-d",
                            "workflow_id": "external-grok-wave-d",
                            "run_id": "external-run-d",
                            "result_ref": str(result_path),
                            "result_sha256": result_sha256,
                        },
                    )
                    reconciled = await _query_until(
                        parent,
                        lambda value: (
                            value.get("waves_completed") == 1
                            and isinstance(value.get("last_decision"), dict)
                            and value["last_decision"].get("action") == "WAIT"
                        ),
                    )
                    await parent.execute_update(
                        "control",
                        {
                            "operation_id": "stop-test",
                            "action": "STOP",
                            "reason": "test completed",
                        },
                    )
                    terminal = await parent.result()
                    return reconciled, terminal

    reconciled, terminal = asyncio.run(exercise())
    assert reconciled["completed_wave_ids"] == ["wave-d"]
    assert reconciled["last_wave_result"]["verification"]["ok"] is True
    assert terminal["status"] == "STOPPED"
    requests = list(
        (tmp_path / "state" / "foundation_continuous" / "foundation-op" / "requests").glob("*.json")
    )
    assert len(requests) == 1
    request = json.loads(requests[0].read_text(encoding="utf-8"))
    assert request["payload_ref"] == str(payload)
    assert request["callback_workflow_id"].endswith("-wave-000001")


def test_stop_cancels_active_child_and_known_external_workflow(tmp_path: Path) -> None:
    payload = tmp_path / "state" / "payloads" / "wave-stop.json"
    frontier = tmp_path / "state" / "frontier.json"
    _write(payload, {"goal": "wait until explicit stop"})
    _write(
        frontier,
        {
            "ready_frontier": [
                {
                    "wave_id": "wave-stop",
                    "payload_ref": str(payload),
                    "correlation_id": "foundation-op:wave-stop",
                    "submission_timeout_seconds": 3_600,
                    "external_task_queue": "foundation-continuous-cancel-test",
                }
            ]
        },
    )

    async def exercise() -> tuple[dict[str, object], WorkflowExecutionStatus]:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    env.client,
                    task_queue="foundation-continuous-cancel-test",
                    workflows=[
                        FoundationContinuousWorkflowV1,
                        FoundationWaveChildWorkflowV1,
                        _FakeExternalWorkflow,
                    ],
                    activities=[
                        reconcile_foundation_frontier,
                        persist_foundation_state,
                        verify_external_wave_result,
                    ],
                    activity_executor=executor,
                ):
                    external = await env.client.start_workflow(
                        _FakeExternalWorkflow.run,
                        id="foundation-fake-external",
                        task_queue="foundation-continuous-cancel-test",
                    )
                    external_description = await external.describe()
                    parent = await env.client.start_workflow(
                        FoundationContinuousWorkflowV1.run,
                        _parent_initial(tmp_path, frontier),
                        id="foundation-continuous-cancel-parent",
                        task_queue="foundation-continuous-cancel-test",
                    )
                    waiting = await _query_until(
                        parent,
                        lambda value: bool(value.get("current_wave")),
                    )
                    current = waiting["current_wave"]
                    assert isinstance(current, dict)
                    child = env.client.get_workflow_handle(str(current["child_workflow_id"]))
                    await child.signal(
                        "external_started",
                        {
                            "signal_id": "started-stop",
                            "wave_id": "wave-stop",
                            "workflow_id": "foundation-fake-external",
                            "run_id": external_description.run_id,
                            "task_queue": "foundation-continuous-cancel-test",
                        },
                    )
                    await _query_until(
                        child,
                        lambda value: value.get("status") == "EXTERNAL_RUNNING",
                    )
                    await parent.execute_update(
                        "control",
                        {
                            "operation_id": "stop-active-wave",
                            "action": "STOP",
                            "reason": "verify cancellation propagation",
                        },
                    )
                    terminal = await parent.result()
                    for _ in range(100):
                        external_status = (await external.describe()).status
                        if external_status == WorkflowExecutionStatus.CANCELED:
                            break
                        await asyncio.sleep(0.01)
                    return terminal, external_status

    terminal, external_status = asyncio.run(exercise())
    assert terminal["status"] == "STOPPED"
    assert terminal["current_wave"] is None
    assert external_status == WorkflowExecutionStatus.CANCELED
