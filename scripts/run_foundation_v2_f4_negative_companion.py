#!/usr/bin/env python3
"""Run isolated, zero-model negative companion proofs for the F4 V2 controller.

The companion uses Temporal's ephemeral time-skipping test server.  It does not
connect to the live namespace, launch the canonical Grok runner, or mutate the
canonical V1 workflow.  Three finite cases prove capacity backpressure, exact
external failure/downshift recovery, and exact external cancellation followed
by a fresh recovery dispatch.
"""

from __future__ import annotations

# ruff: noqa: E402,I001 -- standalone entrypoint exposes repository packages first.

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_BOOT_REPO = Path(__file__).resolve().parents[1]
for _candidate in (_BOOT_REPO, _BOOT_REPO / "xinao_discovery" / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from scripts.run_foundation_v2_f4_live_canary import (
    RUNTIME,
    file_sha256,
    prepare_inputs,
    write_json,
)
from services.agent_runtime.foundation_continuous_workflow import (
    FoundationContinuousWorkflowV1,
    FoundationWaveChildWorkflowV1,
    persist_foundation_state,
    verify_external_wave_result,
)
from services.agent_runtime.foundation_continuous_workflow_v2 import (
    FoundationContinuousWorkflowV2,
    _initial_state_v2,
    finalize_research_fan_in_v2,
    inspect_external_wave_result_v2,
    reconcile_foundation_frontier_v2,
    verify_roll_forward_manifest_v2,
)
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle, WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

EVIDENCE_PARENT = RUNTIME / "projects" / "xinao_discovery" / "evidence"
COMPANION_PREFIX = "xinao-f4-negative-companion"
WORKFLOW_TYPES = [FoundationContinuousWorkflowV2, FoundationWaveChildWorkflowV1]
SOURCE_INDEX_RELATIVE = "source_cas/index.json"
SOURCE_ROLE_PATHS = {
    "input_helper": (
        "scripts/run_foundation_v2_f4_live_canary.py",
        _BOOT_REPO / "scripts" / "run_foundation_v2_f4_live_canary.py",
    ),
    "runner": (
        "scripts/run_foundation_v2_f4_negative_companion.py",
        Path(__file__).resolve(),
    ),
    "v1_workflow": (
        "services/agent_runtime/foundation_continuous_workflow.py",
        _BOOT_REPO / "services" / "agent_runtime" / "foundation_continuous_workflow.py",
    ),
    "v2_workflow": (
        "services/agent_runtime/foundation_continuous_workflow_v2.py",
        _BOOT_REPO / "services" / "agent_runtime" / "foundation_continuous_workflow_v2.py",
    ),
}


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def stable_id(*parts: str, length: int = 20) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:length]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def patch_capacity(
    inputs: Mapping[str, str],
    *,
    available_slots: int,
    queue_depth: int = 3,
) -> dict[str, str]:
    """Rewrite a not-yet-consumed input pair and return its new bound hash."""

    frontier_path = Path(inputs["frontier_ref"])
    frontier = read_json(frontier_path)
    observation_path = Path(str(frontier["capacity_observation_ref"]))
    observation = read_json(observation_path)
    observation.update(
        {
            "host_state": "available",
            "available_slots": available_slots,
            "queue_depth": queue_depth,
            "verified_canary": True,
        }
    )
    _, observation_hash = write_json(observation_path, observation)
    frontier["capacity_observation_sha256"] = observation_hash
    _, frontier_hash = write_json(frontier_path, frontier)
    return {**dict(inputs), "frontier_sha256": frontier_hash}


def resolve_runtime_ref(value: str) -> Path:
    normalized = value.replace("\\", "/")
    if normalized == "/evidence":
        return RUNTIME
    if normalized.startswith("/evidence/"):
        return RUNTIME / normalized[len("/evidence/") :]
    lowered = normalized.casefold()
    runtime_prefix = "d:/xinao_research_runtime"
    if lowered == runtime_prefix:
        return RUNTIME
    if lowered.startswith(runtime_prefix + "/"):
        return RUNTIME / normalized[len(runtime_prefix) + 1 :]
    return Path(value)


async def refresh_roll_forward_binding(inputs: Mapping[str, str]) -> dict[str, str]:
    """Rebind the copied handoff proof to current replayable V1 code."""

    manifest_path = Path(inputs["roll_forward_manifest_ref"])
    manifest = read_json(manifest_path)
    history_path = resolve_runtime_ref(str(manifest["predecessor_history_ref"]))
    history_value = read_json(history_path)
    history = WorkflowHistory.from_json(
        str(manifest["predecessor_workflow_id"]),
        history_value,
    )
    replay = await Replayer(
        workflows=[FoundationContinuousWorkflowV1, FoundationWaveChildWorkflowV1]
    ).replay_workflow(history)
    if replay.replay_failure is not None:
        raise replay.replay_failure
    code_path = _BOOT_REPO / "services" / "agent_runtime" / ("foundation_continuous_workflow.py")
    code_hash = file_sha256(code_path)
    replay_proof = {
        "schema_version": "xinao.temporal_replay_proof.v1",
        "proof_type": "TEMPORAL_SDK_REPLAYER",
        "ok": True,
        "workflow_type": "FoundationContinuousWorkflowV1",
        "workflow_id": manifest["predecessor_workflow_id"],
        "run_id": manifest["predecessor_run_id"],
        "history_sha256": file_sha256(history_path),
        "workflow_code_sha256": code_hash,
        "event_count": len(history.events),
        "verified_at": datetime.now(UTC).isoformat(),
    }
    replay_ref, replay_hash = write_json(
        manifest_path.with_name("predecessor_replay_proof.current.json"),
        replay_proof,
    )
    manifest.update(
        {
            "predecessor_workflow_code_sha256": code_hash,
            "predecessor_replay_ref": replay_ref,
            "predecessor_replay_sha256": replay_hash,
        }
    )
    _, manifest_hash = write_json(manifest_path, manifest)
    return {
        **dict(inputs),
        "roll_forward_manifest_sha256": manifest_hash,
    }


def build_initial(
    inputs: Mapping[str, str],
    *,
    operation_id: str,
    previous_width: int | None = None,
) -> dict[str, Any]:
    initial: dict[str, Any] = {
        "operation_id": operation_id,
        "runtime_root": str(RUNTIME),
        "frontier_ref": inputs["frontier_ref"],
        "frontier_sha256": inputs["frontier_sha256"],
        "roll_forward_manifest_ref": inputs["roll_forward_manifest_ref"],
        "roll_forward_manifest_sha256": inputs["roll_forward_manifest_sha256"],
        "owner_generation": 1,
        "default_wait_seconds": 3_600,
        "max_waves_per_run": 50,
    }
    if previous_width is None:
        return initial
    state = _initial_state_v2(initial)
    state["previous_width"] = previous_width
    return {"resume_state": state}


def parent_worker(
    client: Any,
    *,
    queue: str,
    identity: str,
    executor: ThreadPoolExecutor,
) -> Worker:
    return Worker(
        client,
        task_queue=queue,
        workflows=WORKFLOW_TYPES,
        activities=[
            persist_foundation_state,
            verify_external_wave_result,
            verify_roll_forward_manifest_v2,
            reconcile_foundation_frontier_v2,
            inspect_external_wave_result_v2,
            finalize_research_fan_in_v2,
        ],
        activity_executor=executor,
        identity=identity,
        max_concurrent_workflow_tasks=8,
        max_concurrent_activities=8,
        graceful_shutdown_timeout=timedelta(seconds=15),
    )


def hold_worker(
    client: Any,
    *,
    queue: str,
    identity: str,
    executor: ThreadPoolExecutor,
) -> Worker:
    return Worker(
        client,
        task_queue=queue,
        workflows=[FoundationWaveChildWorkflowV1],
        activities=[persist_foundation_state],
        activity_executor=executor,
        identity=identity,
        graceful_shutdown_timeout=timedelta(seconds=15),
    )


async def wait_for_state(
    handle: WorkflowHandle,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    async with asyncio.timeout(timeout_seconds):
        while True:
            state = await handle.query("state")
            if predicate(state):
                return state
            await asyncio.sleep(0.05)


async def wait_for_status(
    handle: WorkflowHandle,
    expected: WorkflowExecutionStatus,
    *,
    timeout_seconds: float = 30,
) -> Any:
    async with asyncio.timeout(timeout_seconds):
        while True:
            description = await handle.describe()
            if description.status == expected:
                return description
            await asyncio.sleep(0.05)


async def stop_parent(
    handle: WorkflowHandle,
    *,
    operation_id: str,
    reason: str,
) -> dict[str, Any]:
    await handle.execute_update(
        "control",
        {
            "operation_id": operation_id,
            "action": "STOP",
            "reason": reason,
        },
    )
    terminal = await handle.result()
    if terminal.get("status") != "STOPPED":
        raise AssertionError(f"parent did not stop cleanly: {terminal.get('status')}")
    return terminal


def event_types(history_value: Mapping[str, Any]) -> list[str]:
    return [str(event.get("eventType") or "") for event in history_value["events"]]


async def capture_history(
    pack: Path,
    *,
    name: str,
    handle: WorkflowHandle,
) -> dict[str, Any]:
    history = await handle.fetch_history()
    replay = await Replayer(workflows=WORKFLOW_TYPES).replay_workflow(history)
    if replay.replay_failure is not None:
        raise replay.replay_failure
    value = history.to_json_dict()
    history_ref, history_hash = write_json(pack / "histories" / f"{name}.json", value)
    description = await handle.describe()
    return {
        "workflow_id": description.id,
        "run_id": description.run_id,
        "workflow_type": description.workflow_type,
        "task_queue": description.task_queue,
        "status": description.status.name if description.status else "UNKNOWN",
        "history_ref": history_ref,
        "history_sha256": history_hash,
        "history_event_count": len(value["events"]),
        "event_types": sorted(set(event_types(value))),
        "replay_ok": True,
    }


def request_files(operation_id: str) -> list[Path]:
    root = RUNTIME / "state" / "foundation_continuous" / operation_id / "requests"
    return sorted(root.glob("*.json")) if root.is_dir() else []


async def run_backpressure_case(
    client: Any,
    *,
    pack: Path,
    token: str,
) -> dict[str, Any]:
    operation_id = f"{COMPANION_PREFIX}-backpressure-{token}"
    queue = f"{COMPANION_PREFIX}-backpressure-q-{token}"
    workflow_id = f"{COMPANION_PREFIX}-backpressure-wf-{token}"
    inputs = prepare_inputs(
        pack / "cases" / "backpressure",
        operation_id=operation_id,
        external_queue=f"{COMPANION_PREFIX}-unused-{token}",
    )
    inputs = await refresh_roll_forward_binding(inputs)
    inputs = patch_capacity(inputs, available_slots=0)
    with ThreadPoolExecutor(max_workers=8) as executor:
        async with parent_worker(
            client,
            queue=queue,
            identity=f"{COMPANION_PREFIX}-worker-{token}",
            executor=executor,
        ):
            handle = await client.start_workflow(
                FoundationContinuousWorkflowV2.run,
                build_initial(inputs, operation_id=operation_id),
                id=workflow_id,
                task_queue=queue,
            )
            observed = await wait_for_state(
                handle,
                lambda state: (
                    state.get("status") == "WAITING"
                    and (state.get("last_decision") or {}).get("reason") == "CAPACITY_BACKPRESSURE"
                ),
            )
            capacity = dict(observed["last_decision"]["capacity_decision"])
            checks = {
                "available_slots_zero": (capacity["observation"]["available_slots"] == 0),
                "dispatch_width_zero": capacity["dispatch_width"] == 0,
                "capacity_reason_host_not_ready": capacity["reason"] == "HOST_NOT_READY",
                "backpressure_true": capacity["backpressure"] is True,
                "parent_wait_reason": observed["last_decision"]["reason"]
                == "CAPACITY_BACKPRESSURE",
                "no_current_wave": observed.get("current_wave") is None,
                "no_external_request": not request_files(operation_id),
            }
            if not all(checks.values()):
                raise AssertionError(f"backpressure checks failed: {checks}")
            terminal = await stop_parent(
                handle,
                operation_id=f"stop-backpressure-{token}",
                reason="negative companion backpressure proof complete",
            )
            checks["parent_stopped"] = terminal["status"] == "STOPPED"
            history = await capture_history(
                pack,
                name="backpressure-parent",
                handle=handle,
            )
    return {
        "case": "AVAILABLE_SLOTS_ZERO_BACKPRESSURE",
        "operation_id": operation_id,
        "task_queue": queue,
        "checks": checks,
        "capacity_decision": capacity,
        "observed_state": {
            "status": observed["status"],
            "last_decision": observed["last_decision"],
        },
        "terminal_status": terminal["status"],
        "histories": [history],
    }


async def run_partial_case(
    client: Any,
    *,
    pack: Path,
    token: str,
) -> dict[str, Any]:
    operation_id = f"{COMPANION_PREFIX}-partial-{token}"
    queue = f"{COMPANION_PREFIX}-partial-q-{token}"
    workflow_id = f"{COMPANION_PREFIX}-partial-wf-{token}"
    inputs = prepare_inputs(
        pack / "cases" / "partial",
        operation_id=operation_id,
        external_queue=f"{COMPANION_PREFIX}-unused-{token}",
    )
    inputs = await refresh_roll_forward_binding(inputs)
    initial = build_initial(inputs, operation_id=operation_id, previous_width=2)
    with ThreadPoolExecutor(max_workers=8) as executor:
        async with parent_worker(
            client,
            queue=queue,
            identity=f"{COMPANION_PREFIX}-worker-{token}",
            executor=executor,
        ):
            handle = await client.start_workflow(
                FoundationContinuousWorkflowV2.run,
                initial,
                id=workflow_id,
                task_queue=queue,
            )
            first = await wait_for_state(
                handle,
                lambda state: (
                    isinstance(state.get("current_wave"), dict)
                    and state["current_wave"].get("wave_sequence") == 1
                ),
            )
            first_wave = dict(first["current_wave"])
            failed_child = client.get_workflow_handle(
                str(first_wave["child_workflow_id"]),
                run_id=str(first_wave["child_run_id"]) or None,
            )
            failed_child_description = await failed_child.describe()
            failure_signal = {
                "signal_id": stable_id(operation_id, "external-failed"),
                "wave_id": first_wave["wave_id"],
                "error_type": "INJECTED_ZERO_MODEL_FAILURE",
                "message": "bounded negative companion failure injection",
            }
            await failed_child.signal("external_failed", failure_signal)
            recovered = await wait_for_state(
                handle,
                lambda state: (
                    state.get("waves_failed", 0) >= 1
                    and isinstance(state.get("current_wave"), dict)
                    and state["current_wave"].get("wave_sequence") == 2
                ),
            )
            recovery_wave = dict(recovered["current_wave"])
            recovery_child = client.get_workflow_handle(
                str(recovery_wave["child_workflow_id"]),
                run_id=str(recovery_wave["child_run_id"]) or None,
            )
            checks = {
                "first_dispatch_width_two": first_wave["capacity_decision"]["dispatch_width"] == 2,
                "first_capacity_tier_two": first_wave["capacity_decision"]["capacity_tier"] == 2,
                "failed_child_identity_exact": (
                    first_wave["child_workflow_id"] == failed_child_description.id
                    and first_wave["child_run_id"] == failed_child_description.run_id
                ),
                "failure_type_exact": recovered["last_wave_result"]["external_failed"]["error_type"]
                == "INJECTED_ZERO_MODEL_FAILURE",
                "partial_recorded": recovered["previous_partial"] is True,
                "failed_count_two": recovered["previous_failed"] == 2,
                "recovery_dispatch_exists": recovery_wave["wave_sequence"] == 2,
                "recovery_width_one": recovery_wave["capacity_decision"]["dispatch_width"] == 1,
                "recovery_reason_downshift": recovery_wave["capacity_decision"]["reason"]
                == "DOWNSHIFT_AFTER_PARTIAL_OR_FAILURE",
            }
            if not all(checks.values()):
                raise AssertionError(f"partial/downshift checks failed: {checks}")
            terminal = await stop_parent(
                handle,
                operation_id=f"stop-partial-{token}",
                reason="negative companion downshift proof complete",
            )
            await wait_for_status(recovery_child, WorkflowExecutionStatus.CANCELED)
            checks["parent_stopped"] = terminal["status"] == "STOPPED"
            checks["recovery_child_canceled_on_stop"] = True
            histories = [
                await capture_history(
                    pack,
                    name="partial-parent",
                    handle=handle,
                ),
                await capture_history(
                    pack,
                    name="partial-failed-child",
                    handle=failed_child,
                ),
                await capture_history(
                    pack,
                    name="partial-recovery-child",
                    handle=recovery_child,
                ),
            ]
    return {
        "case": "EXACT_EXTERNAL_FAILURE_DOWNSHIFT_RECOVERY",
        "operation_id": operation_id,
        "task_queue": queue,
        "failure_signal": failure_signal,
        "failed_child": {
            "workflow_id": failed_child_description.id,
            "run_id": failed_child_description.run_id,
        },
        "first_capacity_decision": first_wave["capacity_decision"],
        "recovery_capacity_decision": recovery_wave["capacity_decision"],
        "checks": checks,
        "terminal_status": terminal["status"],
        "histories": histories,
    }


async def run_cancel_case(
    client: Any,
    *,
    pack: Path,
    token: str,
) -> dict[str, Any]:
    operation_id = f"{COMPANION_PREFIX}-cancel-{token}"
    queue = f"{COMPANION_PREFIX}-cancel-q-{token}"
    hold_queue = f"{COMPANION_PREFIX}-hold-q-{token}"
    workflow_id = f"{COMPANION_PREFIX}-cancel-wf-{token}"
    hold_workflow_id = f"{COMPANION_PREFIX}-hold-wf-{token}"
    inputs = prepare_inputs(
        pack / "cases" / "cancel",
        operation_id=operation_id,
        external_queue=hold_queue,
    )
    inputs = await refresh_roll_forward_binding(inputs)
    recovery_operation_id = f"{COMPANION_PREFIX}-cancel-recovery-{token}"
    recovery_inputs = prepare_inputs(
        pack / "cases" / "cancel-recovery",
        operation_id=recovery_operation_id,
        external_queue=f"{COMPANION_PREFIX}-recovery-unused-{token}",
    )
    recovery_inputs = await refresh_roll_forward_binding(recovery_inputs)
    with ThreadPoolExecutor(max_workers=10) as executor:
        async with (
            parent_worker(
                client,
                queue=queue,
                identity=f"{COMPANION_PREFIX}-parent-worker-{token}",
                executor=executor,
            ),
            hold_worker(
                client,
                queue=hold_queue,
                identity=f"{COMPANION_PREFIX}-hold-worker-{token}",
                executor=executor,
            ),
        ):
            hold = await client.start_workflow(
                FoundationWaveChildWorkflowV1.run,
                {
                    "operation_id": f"{operation_id}-hold",
                    "runtime_root": str(RUNTIME),
                    "wave_id": f"hold-wave-{token}",
                    "wave_sequence": 1,
                    "correlation_id": f"hold-correlation-{token}",
                    "payload_ref": str(pack / "cases" / "cancel" / "unused.json"),
                    "payload_sha256": "0" * 64,
                    "external_task_queue": hold_queue,
                    "external_provider_id": "zero-model-hold",
                    "external_model": "none",
                    "submission_timeout_seconds": 86_400,
                },
                id=hold_workflow_id,
                task_queue=hold_queue,
            )
            hold_description = await hold.describe()
            parent = await client.start_workflow(
                FoundationContinuousWorkflowV2.run,
                build_initial(inputs, operation_id=operation_id),
                id=workflow_id,
                task_queue=queue,
            )
            parent_active = await wait_for_state(
                parent,
                lambda state: isinstance(state.get("current_wave"), dict),
            )
            wave = dict(parent_active["current_wave"])
            child = client.get_workflow_handle(
                str(wave["child_workflow_id"]),
                run_id=str(wave["child_run_id"]) or None,
            )
            child_description = await child.describe()
            started_signal = {
                "signal_id": stable_id(operation_id, "external-started"),
                "wave_id": wave["wave_id"],
                "workflow_id": hold_description.id,
                "run_id": hold_description.run_id,
                "task_queue": hold_queue,
            }
            await child.signal("external_started", started_signal)
            child_running = await wait_for_state(
                child,
                lambda state: state.get("status") == "EXTERNAL_RUNNING",
            )
            terminal = await stop_parent(
                parent,
                operation_id=f"stop-cancel-{token}",
                reason="negative companion exact cancel proof",
            )
            child_canceled = await wait_for_status(
                child,
                WorkflowExecutionStatus.CANCELED,
            )
            hold_canceled = await wait_for_status(
                hold,
                WorkflowExecutionStatus.CANCELED,
            )

            recovery_workflow_id = f"{COMPANION_PREFIX}-recovery-wf-{token}"
            recovery = await client.start_workflow(
                FoundationContinuousWorkflowV2.run,
                build_initial(
                    recovery_inputs,
                    operation_id=recovery_operation_id,
                ),
                id=recovery_workflow_id,
                task_queue=queue,
            )
            recovery_active = await wait_for_state(
                recovery,
                lambda state: isinstance(state.get("current_wave"), dict),
            )
            recovery_wave = dict(recovery_active["current_wave"])
            recovery_child = client.get_workflow_handle(
                str(recovery_wave["child_workflow_id"]),
                run_id=str(recovery_wave["child_run_id"]) or None,
            )
            recovery_terminal = await stop_parent(
                recovery,
                operation_id=f"stop-cancel-recovery-{token}",
                reason="negative companion fresh recovery dispatch observed",
            )
            await wait_for_status(recovery_child, WorkflowExecutionStatus.CANCELED)

            checks = {
                "started_signal_matches_child_state": child_running["external_started"]
                == started_signal,
                "started_identity_matches_exact_hold": (
                    child_running["external_started"]["workflow_id"] == hold_description.id
                    and child_running["external_started"]["run_id"] == hold_description.run_id
                    and child_running["external_started"]["task_queue"] == hold_queue
                ),
                "parent_stopped": terminal["status"] == "STOPPED",
                "callback_child_canceled": child_canceled.status
                == WorkflowExecutionStatus.CANCELED,
                "exact_hold_canceled": hold_canceled.status == WorkflowExecutionStatus.CANCELED,
                "fresh_recovery_dispatched": recovery_wave["wave_sequence"] == 1,
                "fresh_recovery_parent_stopped": recovery_terminal["status"] == "STOPPED",
                "workflow_ids_are_isolated": all(
                    value.startswith(COMPANION_PREFIX)
                    for value in (
                        workflow_id,
                        child_description.id,
                        hold_description.id,
                        recovery_workflow_id,
                        recovery_wave["child_workflow_id"],
                    )
                ),
            }
            if not all(checks.values()):
                raise AssertionError(f"exact cancel checks failed: {checks}")
            histories = [
                await capture_history(
                    pack,
                    name="cancel-parent",
                    handle=parent,
                ),
                await capture_history(
                    pack,
                    name="cancel-callback-child",
                    handle=child,
                ),
                await capture_history(
                    pack,
                    name="cancel-exact-hold",
                    handle=hold,
                ),
                await capture_history(
                    pack,
                    name="cancel-recovery-parent",
                    handle=recovery,
                ),
                await capture_history(
                    pack,
                    name="cancel-recovery-child",
                    handle=recovery_child,
                ),
            ]
    return {
        "case": "EXACT_CHILD_EXTERNAL_CANCEL_AND_FRESH_RECOVERY",
        "operation_id": operation_id,
        "task_queue": queue,
        "hold_task_queue": hold_queue,
        "started_signal": started_signal,
        "callback_child": {
            "workflow_id": child_description.id,
            "run_id": child_description.run_id,
        },
        "exact_hold": {
            "workflow_id": hold_description.id,
            "run_id": hold_description.run_id,
            "status": hold_canceled.status.name,
        },
        "fresh_recovery": {
            "operation_id": recovery_operation_id,
            "workflow_id": recovery_workflow_id,
            "wave": recovery_wave,
            "terminal_status": recovery_terminal["status"],
        },
        "checks": checks,
        "terminal_status": terminal["status"],
        "histories": histories,
    }


def validate_report(report: Mapping[str, Any]) -> None:
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != 3:
        raise ValueError("exactly three negative companion cases are required")
    if report.get("execution_surface") != "TEMPORAL_EPHEMERAL_TEST_SERVER":
        raise ValueError("negative companion must use the ephemeral test server")
    if report.get("model_invocations") != 0:
        raise ValueError("negative companion must remain zero-model")
    if report.get("canonical_v1_live_mutations") != 0:
        raise ValueError("canonical V1 live mutation count must remain zero")
    for case in cases:
        checks = case.get("checks")
        histories = case.get("histories")
        if not isinstance(checks, dict) or not checks or not all(checks.values()):
            raise ValueError(f"case checks are incomplete: {case.get('case')}")
        if not isinstance(histories, list) or not histories:
            raise ValueError(f"case histories are missing: {case.get('case')}")
        if not all(item.get("replay_ok") is True for item in histories):
            raise ValueError(f"case replay failed: {case.get('case')}")
        if not all(
            str(item.get("workflow_id") or "").startswith(COMPANION_PREFIX) for item in histories
        ):
            raise ValueError(f"non-isolated workflow identity: {case.get('case')}")


def artifact_manifest(pack: Path, report_ref: str, report_hash: str) -> dict[str, Any]:
    entries = []
    for path in sorted(pack.rglob("*")):
        if path.is_file() and path.name != "artifact_manifest.json":
            entries.append(
                {
                    "relative_path": path.relative_to(pack).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    return {
        "schema_version": "xinao.f4_negative_companion_artifact_manifest.v1",
        "pack_ref": str(pack),
        "report_ref": report_ref,
        "report_sha256": report_hash,
        "artifact_count": len(entries),
        "artifacts": entries,
    }


def seal_source_cas(pack: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copy the exact runner/workflow bytes into a pack-local source CAS."""

    bindings: dict[str, dict[str, Any]] = {}
    cas_refs: set[str] = set()
    for role, (logical_path, source_path) in sorted(SOURCE_ROLE_PATHS.items()):
        raw = source_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        relative = f"source_cas/sha256/{digest[:2]}/{digest}.py"
        target = pack / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            if target.read_bytes() != raw:
                raise RuntimeError(f"source CAS identity conflict: {target}")
        else:
            target.write_bytes(raw)
        bindings[role] = {
            "logical_path": logical_path,
            "cas_ref": relative,
            "sha256": digest,
            "size_bytes": len(raw),
        }
        cas_refs.add(relative)

    index_core: dict[str, Any] = {
        "schema_version": "xinao.f4_negative_source_cas.v1",
        "source_count": len(bindings),
        "cas_object_count": len(cas_refs),
        "sources": bindings,
    }
    index = {
        **index_core,
        "content_sha256": hashlib.sha256(
            json.dumps(
                index_core,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    index_ref, index_hash = write_json(pack / SOURCE_INDEX_RELATIVE, index)
    index_path = Path(index_ref)
    return bindings, {
        "ref": SOURCE_INDEX_RELATIVE,
        "sha256": index_hash,
        "size_bytes": index_path.stat().st_size,
    }


async def run(pack: Path) -> dict[str, Any]:
    pack.mkdir(parents=True, exist_ok=False)
    source_bindings, source_index = seal_source_cas(pack)
    token = stable_id(pack.name, utc_stamp(), str(os.getpid()), length=12)
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        backpressure = await run_backpressure_case(
            environment.client,
            pack=pack,
            token=f"bp-{token}",
        )
        partial = await run_partial_case(
            environment.client,
            pack=pack,
            token=f"pt-{token}",
        )
        cancel = await run_cancel_case(
            environment.client,
            pack=pack,
            token=f"cx-{token}",
        )
    report: dict[str, Any] = {
        "schema_version": "xinao.f4_negative_companion_report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "F4_ZERO_MODEL_NEGATIVE_COMPANION",
        "execution_surface": "TEMPORAL_EPHEMERAL_TEST_SERVER",
        "live_namespace_connections": 0,
        "model_invocations": 0,
        "canonical_grok_runner_processes_started": 0,
        "canonical_v1_live_mutations": 0,
        "positive_nine_lane_pack_reruns": 0,
        "workflow_identity_prefix": COMPANION_PREFIX,
        "source_index": source_index,
        "source_bindings": source_bindings,
        "cases": [backpressure, partial, cancel],
    }
    validate_report(report)
    report_ref, report_hash = write_json(pack / "negative_companion_report.json", report)
    manifest = artifact_manifest(pack, report_ref, report_hash)
    manifest_ref, manifest_hash = write_json(pack / "artifact_manifest.json", manifest)
    return {
        "ok": True,
        "pack_ref": str(pack),
        "report_ref": report_ref,
        "report_sha256": report_hash,
        "artifact_manifest_ref": manifest_ref,
        "artifact_manifest_sha256": manifest_hash,
        "case_count": len(report["cases"]),
        "history_count": sum(len(case["histories"]) for case in report["cases"]),
        "model_invocations": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        type=Path,
        default=None,
        help="new evidence directory; defaults under D:/XINAO_RESEARCH_RUNTIME",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pack = args.pack or EVIDENCE_PARENT / f"{COMPANION_PREFIX}-{utc_stamp()}"
    result = asyncio.run(run(pack))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
