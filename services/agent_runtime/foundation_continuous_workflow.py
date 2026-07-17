"""Durable foundation-control state machines without a second daemon.

The parent workflow owns reconciliation and bounded wave children.  A child
does not launch a Windows Grok process: it exposes a durable callback surface
for one externally submitted, canonical Grok transaction.  Temporal history,
signals, updates, timers, and Continue-As-New provide lifecycle durability.
All filesystem I/O stays in activities.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    ChildWorkflowError,
    TemporalError,
)

PARENT_WORKFLOW_NAME = "FoundationContinuousWorkflowV1"
CHILD_WORKFLOW_NAME = "FoundationWaveChildWorkflowV1"
CONTROL_ACTIONS = {"PAUSE", "RESUME", "STOP"}
EXTERNAL_SIGNAL_KINDS = {"started", "completed", "failed"}
DEFAULT_RUNTIME_ROOT = r"D:\XINAO_RESEARCH_RUNTIME"
DEFAULT_EXTERNAL_TASK_QUEUE = "xinao-canonical-grok-host-v1"
DEFAULT_EXTERNAL_PROVIDER_ID = "grok_acpx_headless"
DEFAULT_EXTERNAL_MODEL = "grok-4.5"
MIN_WAIT_SECONDS = 5
MAX_WAIT_SECONDS = 86_400


def _canonical_hash(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_part(value: object, *, fallback: str = "unknown") -> str:
    raw = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)
    return (safe or fallback)[:120]


def _bounded_seconds(value: object, *, default: int) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = default
    return max(MIN_WAIT_SECONDS, min(seconds, MAX_WAIT_SECONDS))


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_json_once(path: Path, value: object) -> None:
    if path.is_file():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise RuntimeError(f"immutable artifact identity conflict: {path}")
        return
    if os.environ.get("XINAO_F4_SNAPSHOT_MANIFEST", "").strip():
        raise RuntimeError(f"snapshot replay cannot create an input artifact: {path}")
    _write_json_atomic(path, value)


def _resolve_runtime_ref(runtime_root: Path, value: object) -> Path:
    """Resolve host-D, container-/evidence, absolute, or relative runtime refs."""

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("runtime artifact ref is required")
    if os.environ.get("XINAO_F4_SNAPSHOT_MANIFEST", "").strip():
        from xinao.foundation.f4_snapshot_runtime import (
            input_path,
            inside,
        )

        resolved = input_path(raw, expect="file")
        if not inside(resolved, runtime_root):
            raise ValueError(f"artifact ref escapes runtime root: {raw}")
        return resolved
    normalized = raw.replace("\\", "/")
    lowered = normalized.casefold()
    d_prefix = "d:/xinao_research_runtime"
    raw_path = Path(raw)
    if raw_path.is_absolute():
        candidate = raw_path
    elif lowered == d_prefix:
        candidate = runtime_root
    elif lowered.startswith(d_prefix + "/"):
        candidate = runtime_root / normalized[len(d_prefix) + 1 :]
    elif normalized == "/evidence":
        candidate = runtime_root
    elif normalized.startswith("/evidence/"):
        candidate = runtime_root / normalized[len("/evidence/") :]
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = runtime_root / candidate
    root = runtime_root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact ref escapes runtime root: {raw}") from exc
    return resolved


def _activity_options(*, timeout_seconds: int = 30) -> dict[str, Any]:
    return {
        "start_to_close_timeout": timedelta(seconds=timeout_seconds),
        "retry_policy": RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=10),
            maximum_attempts=3,
            non_retryable_error_types=["ValueError", "TypeError", "RuntimeError"],
        ),
    }


@activity.defn(name="xinao.foundation.reconcile")
def reconcile_foundation_frontier(payload: dict[str, Any]) -> dict[str, Any]:
    """Read one compact D-disk frontier and choose the next observable action."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    frontier_ref = str(payload.get("frontier_ref") or "").strip()
    if not frontier_ref:
        return {
            "action": "WAIT",
            "reason": "frontier_ref_missing",
            "wait_seconds": _bounded_seconds(payload.get("default_wait_seconds"), default=300),
            "frontier_ref": "",
            "frontier_sha256": "",
        }
    path = _resolve_runtime_ref(runtime_root, frontier_ref)
    if not path.is_file():
        return {
            "action": "WAIT",
            "reason": "frontier_artifact_missing",
            "wait_seconds": _bounded_seconds(payload.get("default_wait_seconds"), default=300),
            "frontier_ref": str(path),
            "frontier_sha256": "",
        }
    raw = path.read_bytes()
    frontier = json.loads(raw.decode("utf-8"))
    if not isinstance(frontier, dict):
        raise TypeError("foundation frontier must be a JSON object")
    frontier_sha256 = hashlib.sha256(raw).hexdigest()
    completed = {str(item) for item in payload.get("completed_wave_ids", [])}
    ready = frontier.get("ready_frontier") or []
    if not isinstance(ready, list):
        raise TypeError("ready_frontier must be a list")
    for raw_wave in ready:
        if not isinstance(raw_wave, dict):
            raise TypeError("ready_frontier entries must be objects")
        wave_id = str(raw_wave.get("wave_id") or "").strip()
        if not wave_id or wave_id in completed:
            continue
        payload_ref = str(raw_wave.get("payload_ref") or "").strip()
        if not payload_ref:
            return {
                "action": "WAIT",
                "reason": f"wave_payload_ref_missing:{wave_id}",
                "wait_seconds": _bounded_seconds(frontier.get("wait_seconds"), default=300),
                "frontier_ref": str(path),
                "frontier_sha256": frontier_sha256,
            }
        payload_path = _resolve_runtime_ref(runtime_root, payload_ref)
        if not payload_path.is_file():
            return {
                "action": "WAIT",
                "reason": f"wave_payload_missing:{wave_id}",
                "wait_seconds": _bounded_seconds(frontier.get("wait_seconds"), default=300),
                "frontier_ref": str(path),
                "frontier_sha256": frontier_sha256,
            }
        return {
            "action": "DISPATCH_EXTERNAL",
            "reason": "positive_ready_frontier",
            "frontier_ref": str(path),
            "frontier_sha256": frontier_sha256,
            "wave": {
                "wave_id": wave_id,
                "payload_ref": str(payload_path),
                "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
                "correlation_id": str(
                    raw_wave.get("correlation_id") or f"{payload.get('operation_id')}:{wave_id}"
                ),
                "submission_timeout_seconds": _bounded_seconds(
                    raw_wave.get("submission_timeout_seconds"), default=3_600
                ),
                "external_task_queue": str(
                    raw_wave.get("external_task_queue") or DEFAULT_EXTERNAL_TASK_QUEUE
                ),
                "external_provider_id": str(
                    raw_wave.get("external_provider_id") or DEFAULT_EXTERNAL_PROVIDER_ID
                ),
                "external_model": str(raw_wave.get("external_model") or DEFAULT_EXTERNAL_MODEL),
                "metadata_ref": str(raw_wave.get("metadata_ref") or ""),
            },
        }
    if frontier.get("foundation_closed") is True and not payload.get("foundation_closed"):
        return {
            "action": "MILESTONE",
            "reason": "all_foundation_gates_verified",
            "frontier_ref": str(path),
            "frontier_sha256": frontier_sha256,
            "wait_seconds": _bounded_seconds(frontier.get("wait_seconds"), default=900),
        }
    return {
        "action": "WAIT",
        "reason": (
            "foundation_milestone_already_recorded"
            if payload.get("foundation_closed")
            else "no_positive_ready_frontier"
        ),
        "wait_seconds": _bounded_seconds(frontier.get("wait_seconds"), default=300),
        "frontier_ref": str(path),
        "frontier_sha256": frontier_sha256,
    }


@activity.defn(name="xinao.foundation.persist_state")
def persist_foundation_state(payload: dict[str, Any]) -> dict[str, str]:
    """Write immutable state plus a replaceable pointer under the runtime root."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    operation_id = _safe_part(payload.get("operation_id"), fallback="operation")
    entity_kind = _safe_part(payload.get("entity_kind"), fallback="entity")
    entity_id = _safe_part(payload.get("entity_id"), fallback="unknown")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be an object")
    snapshot_hash = _canonical_hash(snapshot)
    operation_root = runtime_root / "state" / "foundation_continuous" / operation_id
    entity_root = operation_root / entity_kind / entity_id
    artifact = entity_root / "snapshots" / f"{snapshot_hash}.json"
    _write_json_once(artifact, snapshot)
    pointer = {
        "schema_version": "xinao.foundation_continuous_latest.v1",
        "operation_id": str(payload.get("operation_id") or ""),
        "entity_kind": str(payload.get("entity_kind") or ""),
        "entity_id": str(payload.get("entity_id") or ""),
        "snapshot_hash": snapshot_hash,
        "artifact_ref": str(artifact),
    }
    latest = entity_root / "latest.json"
    _write_json_atomic(latest, pointer)
    request_ref = ""
    current_wave = snapshot.get("current_wave")
    if isinstance(current_wave, dict) and snapshot.get("status") == "WAITING_EXTERNAL":
        request = {
            "schema_version": "xinao.foundation_external_wave_request.v1",
            "operation_id": snapshot.get("operation_id"),
            "wave_id": current_wave.get("wave_id"),
            "wave_sequence": current_wave.get("wave_sequence"),
            "correlation_id": current_wave.get("correlation_id"),
            "payload_ref": current_wave.get("payload_ref"),
            "payload_sha256": current_wave.get("payload_sha256"),
            "expected_external_task_queue": current_wave.get("external_task_queue")
            or DEFAULT_EXTERNAL_TASK_QUEUE,
            "expected_external_provider_id": current_wave.get("external_provider_id")
            or DEFAULT_EXTERNAL_PROVIDER_ID,
            "expected_external_model": current_wave.get("external_model") or DEFAULT_EXTERNAL_MODEL,
            "callback_workflow_id": current_wave.get("child_workflow_id"),
            "callback_run_id": current_wave.get("child_run_id"),
            "callback_signals": {
                "started": "external_started",
                "completed": "external_completed",
                "failed": "external_failed",
            },
        }
        request["request_hash"] = _canonical_hash(request)
        request_name = (
            f"{int(current_wave.get('wave_sequence') or 0):06d}-"
            f"{_safe_part(current_wave.get('wave_id'), fallback='wave')}.json"
        )
        request_path = operation_root / "requests" / request_name
        _write_json_once(request_path, request)
        request_ref = str(request_path)
    return {
        "snapshot_hash": snapshot_hash,
        "artifact_ref": str(artifact),
        "latest_ref": str(latest),
        "request_ref": request_ref,
    }


@activity.defn(name="xinao.foundation.verify_wave_result")
def verify_external_wave_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify an externally completed one-shot by reference, hash, and identity."""

    runtime_root = Path(str(payload.get("runtime_root") or DEFAULT_RUNTIME_ROOT))
    result_path = _resolve_runtime_ref(runtime_root, payload.get("result_ref"))
    if not result_path.is_file():
        raise ValueError(f"external result does not exist: {result_path}")
    raw = result_path.read_bytes()
    result_sha256 = hashlib.sha256(raw).hexdigest()
    expected_hash = str(payload.get("result_sha256") or "").strip()
    if expected_hash and result_sha256 != expected_hash:
        raise ValueError("external result sha256 mismatch")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError("external result must be a JSON object")
    result = value.get("result") or {}
    if not isinstance(result, dict):
        raise TypeError("external result.result must be a JSON object")
    fanin = result.get("grok_fanin") or {}
    if not isinstance(fanin, dict):
        raise TypeError("external result.result.grok_fanin must be a JSON object")
    correlation_id = str(fanin.get("correlation_id") or value.get("correlation_id") or "")
    parent_operation_id = str(
        fanin.get("parent_operation_id") or value.get("parent_operation_id") or ""
    )
    lane_count = int(fanin.get("lane_count") or 0)
    succeeded = int(fanin.get("succeeded") or 0)
    failed = int(fanin.get("failed") or 0)
    expected_payload_hash = str(payload.get("payload_sha256") or "").strip()
    expected_task_queue = str(payload.get("external_task_queue") or "").strip()
    expected_provider = str(payload.get("external_provider_id") or "").strip()
    expected_model = str(payload.get("external_model") or "").strip()
    expected_payload_path = _resolve_runtime_ref(runtime_root, payload.get("payload_ref"))
    actual_payload_path = _resolve_runtime_ref(runtime_root, value.get("payload_path"))
    checks = {
        "ok": value.get("ok") is True,
        "workflow_completed": str(value.get("workflow_status") or "").lower() == "completed",
        "correlation_matches": correlation_id == str(payload.get("correlation_id") or ""),
        "parent_operation_matches": parent_operation_id == str(payload.get("operation_id") or ""),
        "workflow_id_present": bool(str(value.get("workflow_id") or "").strip()),
        "run_id_present": bool(str(value.get("run_id") or "").strip()),
        "payload_ref_matches": actual_payload_path == expected_payload_path,
        "payload_sha256_matches": bool(expected_payload_hash)
        and str(value.get("payload_sha256") or "") == expected_payload_hash,
        "task_queue_matches": bool(expected_task_queue)
        and str(value.get("task_queue") or "") == expected_task_queue,
        "fanin_ok": fanin.get("ok") is True,
        "fanin_complete": lane_count > 0 and succeeded == lane_count and failed == 0,
        "provider_matches": bool(expected_provider)
        and str(fanin.get("provider_id") or "") == expected_provider,
        "model_matches": bool(expected_model) and str(fanin.get("model") or "") == expected_model,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, passed in checks.items() if not passed)
        raise ValueError(f"external result identity gate failed: {failed}")
    expected_workflow_id = str(payload.get("external_workflow_id") or "").strip()
    expected_run_id = str(payload.get("external_run_id") or "").strip()
    if expected_workflow_id and value.get("workflow_id") != expected_workflow_id:
        raise ValueError("external workflow id mismatch")
    if expected_run_id and value.get("run_id") != expected_run_id:
        raise ValueError("external run id mismatch")
    return {
        "ok": True,
        "wave_id": str(payload.get("wave_id") or ""),
        "result_ref": str(result_path),
        "result_sha256": result_sha256,
        "external_workflow_id": str(value["workflow_id"]),
        "external_run_id": str(value["run_id"]),
        "external_task_queue": str(value["task_queue"]),
        "external_provider_id": str(fanin["provider_id"]),
        "external_model": str(fanin["model"]),
        "checks": checks,
    }


def _validate_control(command: dict[str, Any]) -> tuple[str, str, str]:
    action = str(command.get("action") or "").upper()
    operation_id = str(command.get("operation_id") or "").strip()
    reason = str(command.get("reason") or "").strip()
    if action not in CONTROL_ACTIONS:
        raise ValueError("unsupported control action")
    if not operation_id:
        raise ValueError("control operation_id is required")
    if not reason:
        raise ValueError("control reason is required")
    return action, operation_id, reason


def _apply_control(state: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    action, operation_id, reason = _validate_control(command)
    prior = next(
        (item for item in state["control_audit"] if item["operation_id"] == operation_id),
        None,
    )
    if prior is not None:
        if prior["action"] != action or prior["reason"] != reason:
            raise ValueError("control operation identity conflict")
        return dict(prior)
    no_op = False
    if action == "PAUSE":
        no_op = state["paused"] is True
        state["paused"] = True
    elif action == "RESUME":
        no_op = state["paused"] is False
        state["paused"] = False
    else:
        no_op = state["stop_requested"] is True
        state["stop_requested"] = True
    state["revision"] += 1
    record = {
        "operation_id": operation_id,
        "action": action,
        "reason": reason,
        "revision": state["revision"],
        "no_op": no_op,
    }
    state["control_audit"].append(record)
    return dict(record)


def _initial_parent_state(initial: dict[str, Any]) -> dict[str, Any]:
    resume = initial.get("resume_state")
    if isinstance(resume, dict):
        state = json.loads(json.dumps(resume))
        state["generation"] = int(state.get("generation") or 0) + 1
        state["waves_since_continue_as_new"] = 0
        state["current_wave"] = None
        state["status"] = "RECONCILING"
        state["next_wake_at"] = ""
        state["revision"] = int(state.get("revision") or 0) + 1
        return state
    operation_id = str(initial.get("operation_id") or "").strip()
    if not operation_id:
        raise ValueError("operation_id is required")
    max_waves = max(1, min(int(initial.get("max_waves_per_run") or 20), 1_000))
    return {
        "schema_version": "xinao.foundation_continuous_state.v1",
        "operation_id": operation_id,
        "runtime_root": str(initial.get("runtime_root") or DEFAULT_RUNTIME_ROOT),
        "frontier_ref": str(initial.get("frontier_ref") or ""),
        "scope": "foundation",
        "status": "PENDING",
        "generation": 0,
        "wave_sequence": 0,
        "waves_since_continue_as_new": 0,
        "max_waves_per_run": max_waves,
        "waves_completed": 0,
        "waves_failed": 0,
        "completed_wave_ids": [],
        "failed_wave_ids": [],
        "current_wave": None,
        "last_wave_result": {},
        "last_decision": {},
        "last_state_ref": "",
        "last_state_hash": "",
        "paused": bool(initial.get("paused", False)),
        "stop_requested": False,
        "foundation_closed": False,
        "idle_cycles": 0,
        "default_wait_seconds": _bounded_seconds(initial.get("default_wait_seconds"), default=300),
        "next_wake_at": "",
        "wake_revision": 0,
        "material_signal_ids": [],
        "duplicate_material_signals": 0,
        "control_audit": [],
        "revision": 1,
    }


def _parent_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(state))


def _continue_as_new_due(state: dict[str, Any], *, suggested: bool) -> bool:
    return bool(
        state.get("current_wave") is None
        and not state.get("stop_requested")
        and (
            suggested
            or int(state.get("waves_since_continue_as_new") or 0)
            >= int(state.get("max_waves_per_run") or 20)
        )
    )


def _continuation_input(state: dict[str, Any]) -> dict[str, Any]:
    compact = _parent_snapshot(state)
    compact["current_wave"] = None
    compact["last_decision"] = {
        key: value
        for key, value in dict(compact.get("last_decision") or {}).items()
        if key != "wave"
    }
    return {"resume_state": compact}


def _initial_child_state(initial: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(initial.get("operation_id") or "").strip()
    wave_id = str(initial.get("wave_id") or "").strip()
    correlation_id = str(initial.get("correlation_id") or "").strip()
    if not operation_id or not wave_id or not correlation_id:
        raise ValueError("operation_id, wave_id, and correlation_id are required")
    return {
        "schema_version": "xinao.foundation_wave_child_state.v1",
        "operation_id": operation_id,
        "runtime_root": str(initial.get("runtime_root") or DEFAULT_RUNTIME_ROOT),
        "wave_id": wave_id,
        "wave_sequence": int(initial.get("wave_sequence") or 0),
        "correlation_id": correlation_id,
        "payload_ref": str(initial.get("payload_ref") or ""),
        "payload_sha256": str(initial.get("payload_sha256") or ""),
        "external_task_queue": str(
            initial.get("external_task_queue") or DEFAULT_EXTERNAL_TASK_QUEUE
        ),
        "external_provider_id": str(
            initial.get("external_provider_id") or DEFAULT_EXTERNAL_PROVIDER_ID
        ),
        "external_model": str(initial.get("external_model") or DEFAULT_EXTERNAL_MODEL),
        "submission_timeout_seconds": _bounded_seconds(
            initial.get("submission_timeout_seconds"), default=3_600
        ),
        "status": "REQUESTED",
        "external_started": {},
        "external_completed": {},
        "external_failed": {},
        "verification": {},
        "signal_audit": {},
        "duplicate_signals": 0,
        "signal_conflicts": [],
        "cancel_requested": False,
        "last_state_ref": "",
        "last_state_hash": "",
        "revision": 1,
    }


def _accept_external_signal(state: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    if kind not in EXTERNAL_SIGNAL_KINDS:
        raise ValueError("unsupported external signal kind")
    signal_id = str(payload.get("signal_id") or "").strip() or _canonical_hash(payload)
    normalized = json.loads(json.dumps(payload))
    normalized["signal_id"] = signal_id
    prior = state["signal_audit"].get(signal_id)
    if prior is not None:
        if prior == {"kind": kind, "payload": normalized}:
            state["duplicate_signals"] += 1
            return
        state["signal_conflicts"].append(signal_id)
        state["external_failed"] = {
            "signal_id": signal_id,
            "error_type": "SIGNAL_IDENTITY_CONFLICT",
            "message": "same signal_id carried different content",
        }
        state["status"] = "EXTERNAL_FAILED"
        state["revision"] += 1
        return
    if str(normalized.get("wave_id") or "") != state["wave_id"]:
        state["external_failed"] = {
            "signal_id": signal_id,
            "error_type": "WAVE_IDENTITY_CONFLICT",
            "message": "external callback wave_id mismatch",
        }
        state["status"] = "EXTERNAL_FAILED"
    elif kind == "started":
        required = ("workflow_id", "run_id", "task_queue")
        if not all(str(normalized.get(key) or "").strip() for key in required):
            state["external_failed"] = {
                "signal_id": signal_id,
                "error_type": "START_IDENTITY_MISSING",
                "message": "workflow_id, run_id, and task_queue are required",
            }
            state["status"] = "EXTERNAL_FAILED"
        elif str(normalized.get("task_queue") or "") != state["external_task_queue"]:
            state["external_failed"] = {
                "signal_id": signal_id,
                "error_type": "EXTERNAL_TASK_QUEUE_CONFLICT",
                "message": "external callback task_queue does not match the canonical route",
            }
            state["status"] = "EXTERNAL_FAILED"
        else:
            state["external_started"] = normalized
            state["status"] = "EXTERNAL_RUNNING"
    elif kind == "completed":
        required = ("result_ref", "result_sha256", "workflow_id", "run_id")
        if not all(str(normalized.get(key) or "").strip() for key in required):
            state["external_failed"] = {
                "signal_id": signal_id,
                "error_type": "COMPLETION_IDENTITY_MISSING",
                "message": "result and workflow identities are required",
            }
            state["status"] = "EXTERNAL_FAILED"
        elif not state["external_started"]:
            state["external_failed"] = {
                "signal_id": signal_id,
                "error_type": "START_CALLBACK_MISSING",
                "message": "external completion arrived before its identity-bound start callback",
            }
            state["status"] = "EXTERNAL_FAILED"
        elif any(
            normalized.get(key) != state["external_started"].get(key)
            for key in ("workflow_id", "run_id")
        ):
            state["external_failed"] = {
                "signal_id": signal_id,
                "error_type": "EXTERNAL_RUN_IDENTITY_CONFLICT",
                "message": "completion does not match started workflow/run",
            }
            state["status"] = "EXTERNAL_FAILED"
        else:
            state["external_completed"] = normalized
            state["status"] = "VERIFYING"
    else:
        state["external_failed"] = normalized
        state["status"] = "EXTERNAL_FAILED"
    state["signal_audit"][signal_id] = {"kind": kind, "payload": normalized}
    state["revision"] += 1


def _child_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(state))


@workflow.defn(name=CHILD_WORKFLOW_NAME)
class FoundationWaveChildWorkflowV1:
    """One bounded wave waiting for an externally run canonical Grok transaction."""

    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._state = _initial_child_state(initial)

    @workflow.signal(name="external_started")
    def external_started(self, payload: dict[str, Any]) -> None:
        _accept_external_signal(self._state, "started", payload)

    @workflow.signal(name="external_completed")
    def external_completed(self, payload: dict[str, Any]) -> None:
        _accept_external_signal(self._state, "completed", payload)

    @workflow.signal(name="external_failed")
    def external_failed(self, payload: dict[str, Any]) -> None:
        _accept_external_signal(self._state, "failed", payload)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return _child_snapshot(self._state)

    async def _persist(self) -> None:
        receipt = await workflow.execute_activity(
            persist_foundation_state,
            {
                "runtime_root": self._state["runtime_root"],
                "operation_id": self._state["operation_id"],
                "entity_kind": "wave",
                "entity_id": self._state["wave_id"],
                "snapshot": _child_snapshot(self._state),
            },
            **_activity_options(),
        )
        self._state["last_state_ref"] = receipt["artifact_ref"]
        self._state["last_state_hash"] = receipt["snapshot_hash"]

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        del initial
        self._state["workflow_id"] = workflow.info().workflow_id
        self._state["run_id"] = workflow.info().run_id
        await self._persist()
        try:
            try:
                await workflow.wait_condition(
                    lambda: bool(
                        self._state["external_completed"] or self._state["external_failed"]
                    ),
                    timeout=timedelta(seconds=int(self._state["submission_timeout_seconds"])),
                )
            except asyncio.TimeoutError:
                self._state["external_failed"] = {
                    "error_type": "EXTERNAL_SUBMISSION_TIMEOUT",
                    "message": "no completed external one-shot arrived inside the wave window",
                }
                self._state["status"] = "EXTERNAL_TIMEOUT"
                self._state["revision"] += 1
            if self._state["external_failed"]:
                await self._persist()
                await workflow.wait_condition(workflow.all_handlers_finished)
                return _child_snapshot(self._state)
            completed = dict(self._state["external_completed"])
            try:
                verification = await workflow.execute_activity(
                    verify_external_wave_result,
                    {
                        "runtime_root": self._state["runtime_root"],
                        "operation_id": self._state["operation_id"],
                        "wave_id": self._state["wave_id"],
                        "correlation_id": self._state["correlation_id"],
                        "result_ref": completed["result_ref"],
                        "result_sha256": completed["result_sha256"],
                        "payload_ref": self._state["payload_ref"],
                        "payload_sha256": self._state["payload_sha256"],
                        "external_task_queue": self._state["external_task_queue"],
                        "external_provider_id": self._state["external_provider_id"],
                        "external_model": self._state["external_model"],
                        "external_workflow_id": completed["workflow_id"],
                        "external_run_id": completed["run_id"],
                    },
                    **_activity_options(),
                )
            except ActivityError as exc:
                self._state["external_failed"] = {
                    "error_type": "EXTERNAL_RESULT_VERIFICATION_FAILED",
                    "message": str(exc)[:400],
                }
                self._state["status"] = "VERIFY_FAILED"
            else:
                self._state["verification"] = verification
                self._state["status"] = "COMPLETED"
            self._state["revision"] += 1
            await self._persist()
            await workflow.wait_condition(workflow.all_handlers_finished)
            return _child_snapshot(self._state)
        except asyncio.CancelledError:
            self._state["cancel_requested"] = True
            self._state["status"] = "CANCELLING"
            self._state["revision"] += 1
            started = self._state.get("external_started") or {}
            external_workflow_id = str(started.get("workflow_id") or "")
            if external_workflow_id:
                external = workflow.get_external_workflow_handle(
                    external_workflow_id,
                    run_id=str(started.get("run_id") or "") or None,
                )
                with contextlib.suppress(TemporalError):
                    await external.cancel(reason="foundation parent stopped current wave")
            self._state["status"] = "CANCELED"
            with contextlib.suppress(TemporalError, asyncio.CancelledError):
                await asyncio.shield(self._persist())
            raise


@workflow.defn(name=PARENT_WORKFLOW_NAME)
class FoundationContinuousWorkflowV1:
    """Long-lived reconciliation loop; never launches a host process itself."""

    @workflow.init
    def __init__(self, initial: dict[str, Any]) -> None:
        self._state = _initial_parent_state(initial)

    @workflow.query(name="state")
    def state(self) -> dict[str, Any]:
        return _parent_snapshot(self._state)

    @workflow.signal(name="material_changed")
    def material_changed(self, payload: dict[str, Any]) -> None:
        signal_id = str(payload.get("signal_id") or "").strip() or _canonical_hash(payload)
        if signal_id in self._state["material_signal_ids"]:
            self._state["duplicate_material_signals"] += 1
            return
        self._state["material_signal_ids"].append(signal_id)
        self._state["wake_revision"] += 1
        self._state["revision"] += 1

    @workflow.update(name="control")
    def control(self, command: dict[str, Any]) -> dict[str, Any]:
        try:
            return _apply_control(self._state, command)
        except ValueError as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc

    @control.validator
    def validate_control(self, command: dict[str, Any]) -> None:
        _validate_control(command)

    async def _persist(self) -> dict[str, str]:
        receipt = await workflow.execute_activity(
            persist_foundation_state,
            {
                "runtime_root": self._state["runtime_root"],
                "operation_id": self._state["operation_id"],
                "entity_kind": "parent",
                "entity_id": workflow.info().workflow_id,
                "snapshot": _parent_snapshot(self._state),
            },
            **_activity_options(),
        )
        self._state["last_state_ref"] = receipt["artifact_ref"]
        self._state["last_state_hash"] = receipt["snapshot_hash"]
        current = self._state.get("current_wave")
        if isinstance(current, dict) and receipt.get("request_ref"):
            current["request_ref"] = receipt["request_ref"]
        return receipt

    async def _wait_for_change(self, seconds: int) -> None:
        before = int(self._state["wake_revision"])
        self._state["next_wake_at"] = (workflow.now() + timedelta(seconds=seconds)).isoformat()
        try:
            await workflow.wait_condition(
                lambda: bool(
                    self._state["stop_requested"]
                    or self._state["paused"]
                    or int(self._state["wake_revision"]) != before
                ),
                timeout=timedelta(seconds=seconds),
            )
        except asyncio.TimeoutError:
            self._state["idle_cycles"] += 1
        else:
            self._state["idle_cycles"] = 0
        self._state["next_wake_at"] = ""
        self._state["revision"] += 1

    async def _stop_with_child(self, child: Any) -> dict[str, Any]:
        child.cancel()
        with contextlib.suppress(
            asyncio.CancelledError,
            ChildWorkflowError,
            TemporalError,
        ):
            await child
        self._state["current_wave"] = None
        self._state["status"] = "STOPPED"
        self._state["revision"] += 1
        await self._persist()
        await workflow.wait_condition(workflow.all_handlers_finished)
        return _parent_snapshot(self._state)

    async def _run_wave(self, wave: dict[str, Any]) -> dict[str, Any] | None:
        sequence = int(self._state["wave_sequence"]) + 1
        child_id = f"{workflow.info().workflow_id}-wave-{sequence:06d}"
        child_input = {
            "operation_id": self._state["operation_id"],
            "runtime_root": self._state["runtime_root"],
            "wave_id": wave["wave_id"],
            "wave_sequence": sequence,
            "correlation_id": wave["correlation_id"],
            "payload_ref": wave["payload_ref"],
            "payload_sha256": wave["payload_sha256"],
            "external_task_queue": wave["external_task_queue"],
            "external_provider_id": wave["external_provider_id"],
            "external_model": wave["external_model"],
            "submission_timeout_seconds": wave["submission_timeout_seconds"],
        }
        child = await workflow.start_child_workflow(
            FoundationWaveChildWorkflowV1.run,
            child_input,
            id=child_id,
            task_queue=workflow.info().task_queue,
            result_type=dict,
            cancellation_type=(workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED),
            parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
        )
        self._state["wave_sequence"] = sequence
        self._state["current_wave"] = {
            **wave,
            "wave_sequence": sequence,
            "child_workflow_id": child.id,
            "child_run_id": child.first_execution_run_id or "",
        }
        self._state["status"] = "WAITING_EXTERNAL"
        self._state["revision"] += 1
        await self._persist()
        stop_wait = asyncio.create_task(
            workflow.wait_condition(lambda: bool(self._state["stop_requested"]))
        )
        try:
            done, _ = await workflow.wait(
                [child, stop_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_wait in done and self._state["stop_requested"]:
                return await self._stop_with_child(child)
            try:
                child_result = await child
            except (ChildWorkflowError, TemporalError) as exc:
                child_result = {
                    "wave_id": wave["wave_id"],
                    "status": "CHILD_FAILED",
                    "external_failed": {
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:400],
                    },
                    "verification": {},
                }
        finally:
            if not stop_wait.done():
                stop_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_wait
        compact_result = {
            "wave_id": str(child_result.get("wave_id") or wave["wave_id"]),
            "status": str(child_result.get("status") or "UNKNOWN"),
            "verification": dict(child_result.get("verification") or {}),
            "external_failed": dict(child_result.get("external_failed") or {}),
        }
        self._state["last_wave_result"] = compact_result
        if (
            compact_result["status"] == "COMPLETED"
            and compact_result["verification"].get("ok") is True
        ):
            if wave["wave_id"] not in self._state["completed_wave_ids"]:
                self._state["completed_wave_ids"].append(wave["wave_id"])
            self._state["waves_completed"] += 1
        else:
            if wave["wave_id"] not in self._state["failed_wave_ids"]:
                self._state["failed_wave_ids"].append(wave["wave_id"])
            self._state["waves_failed"] += 1
        self._state["waves_since_continue_as_new"] += 1
        self._state["current_wave"] = None
        self._state["status"] = "RECONCILING"
        self._state["revision"] += 1
        await self._persist()
        return None

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        del initial
        self._state["workflow_id"] = workflow.info().workflow_id
        self._state["run_id"] = workflow.info().run_id
        await self._persist()
        try:
            while True:
                if self._state["stop_requested"]:
                    self._state["status"] = "STOPPED"
                    self._state["revision"] += 1
                    await self._persist()
                    await workflow.wait_condition(workflow.all_handlers_finished)
                    return _parent_snapshot(self._state)
                if _continue_as_new_due(
                    self._state,
                    suggested=workflow.info().is_continue_as_new_suggested(),
                ):
                    await workflow.wait_condition(workflow.all_handlers_finished)
                    workflow.continue_as_new(_continuation_input(self._state))
                if self._state["paused"]:
                    self._state["status"] = "PAUSED"
                    self._state["revision"] += 1
                    await self._persist()
                    await workflow.wait_condition(
                        lambda: bool(not self._state["paused"] or self._state["stop_requested"])
                    )
                    continue
                self._state["status"] = "RECONCILING"
                decision = await workflow.execute_activity(
                    reconcile_foundation_frontier,
                    {
                        "runtime_root": self._state["runtime_root"],
                        "operation_id": self._state["operation_id"],
                        "frontier_ref": self._state["frontier_ref"],
                        "completed_wave_ids": list(self._state["completed_wave_ids"]),
                        "foundation_closed": self._state["foundation_closed"],
                        "default_wait_seconds": self._state["default_wait_seconds"],
                    },
                    **_activity_options(),
                )
                self._state["last_decision"] = dict(decision)
                self._state["revision"] += 1
                action = str(decision.get("action") or "WAIT")
                if action == "DISPATCH_EXTERNAL":
                    stopped = await self._run_wave(dict(decision["wave"]))
                    if stopped is not None:
                        return stopped
                    continue
                if action == "MILESTONE":
                    self._state["foundation_closed"] = True
                    self._state["scope"] = "mainline-global"
                    self._state["status"] = "MILESTONE_RECORDED"
                    self._state["revision"] += 1
                    await self._persist()
                else:
                    self._state["status"] = "WAITING"
                    await self._persist()
                wait_seconds = _bounded_seconds(
                    decision.get("wait_seconds"),
                    default=int(self._state["default_wait_seconds"]),
                )
                await self._wait_for_change(wait_seconds)
        except asyncio.CancelledError:
            self._state["stop_requested"] = True
            self._state["status"] = "CANCELED"
            self._state["revision"] += 1
            with contextlib.suppress(TemporalError, asyncio.CancelledError):
                await asyncio.shield(self._persist())
            raise


def temporal_exports() -> tuple[list[type], list[Any]]:
    """Explicit opt-in registry export; this module does not register itself."""

    return (
        [FoundationContinuousWorkflowV1, FoundationWaveChildWorkflowV1],
        [
            reconcile_foundation_frontier,
            persist_foundation_state,
            verify_external_wave_result,
        ],
    )


__all__ = [
    "CHILD_WORKFLOW_NAME",
    "FoundationContinuousWorkflowV1",
    "FoundationWaveChildWorkflowV1",
    "PARENT_WORKFLOW_NAME",
    "persist_foundation_state",
    "reconcile_foundation_frontier",
    "temporal_exports",
    "verify_external_wave_result",
]
