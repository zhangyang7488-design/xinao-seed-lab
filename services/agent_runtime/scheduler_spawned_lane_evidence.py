from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
SCHEMA_VERSION = "xinao.codex_s.scheduler_spawned_lane_evidence.v1"
SENTINEL = "SENTINEL:XINAO_SCHEDULER_SPAWNED_LANE_EVIDENCE_READY"
ADOPTION_STATE = "verifier_ready_but_not_hooked"
PLANNED_ONLY_BLOCKER = "SCHEDULER_SPAWNED_LANES_NOT_RUNTIME_INVOKED"
PARENT_DISPATCH_ONLY_BLOCKER = "DEFAULT_RUNTIME_SCHEDULER_NOT_HOOKED_PARENT_DISPATCH_ONLY"
ACTIVITY_SCOPE_ONLY_BLOCKER = "DEFAULT_RUNTIME_SCHEDULER_NOT_HOOKED_ACTIVITY_SCOPE_ONLY"
INVOKED_NO_SPAWN_BLOCKER = "SCHEDULER_INVOKED_NO_LANE_SPAWN_EVIDENCE"

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_WAVE_ID = "codex-s-main-execution-wave-20260702"
READBACK_NAME = "scheduler_spawned_lane_evidence_20260703.md"

DP_MODE_IDS = (
    "draft",
    "eval",
    "contradiction",
    "extraction",
    "audit",
    "search",
    "citation_verify",
    "provider_probe",
)

NON_SPAWN_POLL_STATUSES = {
    "",
    "planned_not_spawned",
    "not_applicable_not_spawned",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def replace_path_with_retry(tmp: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(25):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def sha256_payload_without_digest(payload: dict[str, Any]) -> str:
    payload_for_digest = json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    evidence_refs = payload_for_digest.get("evidence_refs")
    if isinstance(evidence_refs, dict):
        evidence_refs.pop("runtime_wave_record_digest_sha256", None)
    return hashlib.sha256(
        json.dumps(payload_for_digest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def json_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        ref.update({"json_valid": False, "json_error": str(exc)})
        return ref
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    runtime_invocation = (
        payload.get("runtime_entrypoint_invocation")
        if isinstance(payload.get("runtime_entrypoint_invocation"), dict)
        else {}
    )
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed"),
            "adoption_state": payload.get("adoption_state"),
            "runtime_enforced": payload.get("runtime_enforced")
            or runtime_invocation.get("runtime_enforced"),
            "runtime_enforced_scope": payload.get("runtime_enforced_scope")
            or runtime_invocation.get("runtime_enforced_scope"),
            "invoked_by": runtime_invocation.get("invoked_by"),
            "not_execution_controller": payload.get("not_execution_controller"),
            "completion_claim_allowed": payload.get("completion_claim_allowed"),
        }
    )
    return ref


def safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value)


def output_paths(repo_root: Path, runtime_root: Path, wave_id: str = DEFAULT_WAVE_ID) -> dict[str, str]:
    wave_part = safe_path_part(wave_id or DEFAULT_WAVE_ID)
    immutable_name = f"{int(time.time() * 1000)}_{os.getpid()}.json"
    return {
        "runtime_latest": str(
            runtime_root / "state" / "scheduler_spawned_lane_evidence" / "latest.json"
        ),
        "runtime_activity_scoped_latest": str(
            runtime_root
            / "state"
            / "scheduler_spawned_lane_evidence"
            / "activity_scoped_latest.json"
        ),
        "runtime_wave_record": str(
            runtime_root
            / "state"
            / "scheduler_spawned_lane_evidence"
            / "waves"
            / wave_part
            / immutable_name
        ),
        "runtime_readback_zh": str(runtime_root / "readback" / "zh" / READBACK_NAME),
        "schema": str(
            repo_root
            / "contracts"
            / "schemas"
            / "codex_s_scheduler_spawned_lane_evidence.v1.json"
        ),
        "writer": str(repo_root / "services" / "agent_runtime" / "scheduler_spawned_lane_evidence.py"),
        "tests": str(
            repo_root / "tests" / "seedcortex" / "test_scheduler_spawned_lane_evidence.py"
        ),
        "verifier": str(repo_root / "scripts" / "verify_scheduler_spawned_lane_evidence.ps1"),
    }


def runtime_ref_paths(runtime_root: Path, scheduler_invocation_ref: Path | None) -> dict[str, Path]:
    state = runtime_root / "state"
    refs = {
        "parallel_dispatch_plan": state / "parallel_dispatch_plan" / "latest.json",
        "durable_parallel_wave_packet": state / "durable_parallel_wave_packet" / "latest.json",
        "durable_parallel_wave_packet_temporal_activity": (
            state / "durable_parallel_wave_packet" / "temporal_activity_latest.json"
        ),
        "worker_dispatch_ledger": state / "worker_dispatch_ledger" / "latest.json",
        "worker_dispatch_ledger_temporal_activity": (
            state / "worker_dispatch_ledger" / "temporal_activity_latest.json"
        ),
        "default_main_loop_trigger_candidate": (
            state / "default_main_loop_trigger_candidate" / "latest.json"
        ),
        "default_main_loop_trigger_candidate_temporal_activity": (
            state / "default_main_loop_trigger_candidate" / "temporal_activity_latest.json"
        ),
        "capability_port_mode_ontology": (
            state / "capability_port_mode_ontology" / "latest.json"
        ),
        "codex_s_live_backend_watch": state / "codex_s_live_backend_watch" / "latest.json",
        "parallel_fan_in_acceptance": (
            state / "parallel_fan_in_acceptance" / "latest.json"
        ),
        "artifact_acceptance_queue": state / "artifact_acceptance_queue" / "latest.json",
    }
    if scheduler_invocation_ref is not None:
        refs["scheduler_invocation"] = scheduler_invocation_ref
    return refs


def _list_from(payload: dict[str, Any], *path: str) -> list[Any]:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return current if isinstance(current, list) else []


def _dict_from(payload: dict[str, Any], *path: str) -> dict[str, Any]:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def lane_key(lane: dict[str, Any]) -> str:
    for key in ("plan_item_id", "edge_id", "lane_id", "lane"):
        value = str(lane.get(key) or "").strip()
        if value:
            return value
    return "unknown_lane"


def selected_plan_lanes(plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = _list_from(plan_payload, "lane_assignments")
    if lanes:
        return [lane for lane in lanes if isinstance(lane, dict)]
    selected = _list_from(plan_payload, "selected_edges")
    return [lane for lane in selected if isinstance(lane, dict)]


def actual_dispatch_summary(label: str, payload: dict[str, Any]) -> dict[str, Any]:
    actual = _dict_from(payload, "actual_dispatch_refs")
    if not actual:
        actual = payload
    lanes = actual.get("lane_assignments")
    codex_subagents = actual.get("codex_subagents")
    worker_ids = actual.get("worker_dispatch_ledger_actual_entry_ids")
    return {
        "source": label,
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "runtime_enforced": bool(
            payload.get("runtime_enforced")
            or _dict_from(payload, "runtime_entrypoint_invocation").get("runtime_enforced")
        ),
        "runtime_enforced_scope": payload.get("runtime_enforced_scope")
        or _dict_from(payload, "runtime_entrypoint_invocation").get("runtime_enforced_scope"),
        "codex_subagent_count": int(actual.get("codex_subagent_count") or 0),
        "lane_assignment_count": len(lanes) if isinstance(lanes, list) else 0,
        "worker_dispatch_ledger_actual_entry_ids": (
            [str(item) for item in worker_ids] if isinstance(worker_ids, list) else []
        ),
        "spawned_by_this_runner": actual.get("spawned_by_this_runner") is True,
        "refs_are_evidence_only": actual.get("refs_are_evidence_only") is True,
        "refs_are_not_completion_gates": actual.get("refs_are_not_completion_gates") is True,
        "refs_are_not_execution_controllers": actual.get("refs_are_not_execution_controllers")
        is True,
        "not_execution_controller": payload.get("not_execution_controller") is True,
        "counted_as_scheduler_spawned": False,
    }


def worker_dispatch_entry_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _list_from(payload, "dispatch_entries")
    summaries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        summaries.append(
            {
                "entry_id": str(entry.get("entry_id") or ""),
                "lane_id": str(entry.get("lane_id") or ""),
                "provider": str(entry.get("provider") or ""),
                "mode": str(entry.get("mode") or ""),
                "poll_status": str(entry.get("poll_status") or ""),
                "fan_in_decision": str(entry.get("fan_in_decision") or ""),
                "not_execution_controller": entry.get("not_execution_controller") is True,
                "counted_as_scheduler_spawned": False,
            }
        )
    return summaries


def add_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def dp_modes_seen(*payloads: dict[str, Any]) -> list[str]:
    modes: list[str] = []
    for payload in payloads:
        for port in _list_from(payload, "ports"):
            if not isinstance(port, dict):
                continue
            if port.get("port_id") != "dp_sidecar_execution_port":
                continue
            for mode_id in port.get("mode_ids") or []:
                add_unique(modes, str(mode_id))
            for mode in port.get("modes") or []:
                if isinstance(mode, dict):
                    add_unique(modes, str(mode.get("mode_id") or ""))
        for mode_id in _dict_from(payload, "dp_sidecar_execution", "mode_counts").keys():
            add_unique(modes, str(mode_id))
        for mode_id in _dict_from(
            payload, "actual_dispatch_refs", "dp_sidecar_execution", "mode_counts"
        ).keys():
            add_unique(modes, str(mode_id))
        for mode_id in _dict_from(
            payload, "actual_activity_refs", "durable_parallel_wave_packet_activity_ref",
            "dp_sidecar_execution", "mode_counts"
        ).keys():
            add_unique(modes, str(mode_id))
    return modes


def scheduler_invocation_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return load_json(path)


def scheduler_invocation_summary(path: Path | None, payload: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "ref": None,
            "scheduler_invoked": False,
            "runtime_enforced": False,
            "default_runtime_scheduler_invoked": False,
            "parent_dispatch_invoked": False,
            "dp_sidecar_execution_lanes_spawned": False,
            "adoption_state": "",
            "invocation_scope": "",
            "spawned_lane_refs": [],
        }
    runtime_invocation = _dict_from(payload, "runtime_entrypoint_invocation")
    invocation_scope = str(
        payload.get("invocation_scope")
        or payload.get("scheduler_invocation_scope")
        or runtime_invocation.get("invocation_scope")
        or ""
    )
    invoked_by = str(
        payload.get("scheduler_invoked_by")
        or payload.get("invoked_by")
        or runtime_invocation.get("invoked_by")
        or ""
    )
    scheduler_invoked = (
        payload.get("scheduler_invoked") is True
        or (payload.get("invoked") is True and "scheduler" in invoked_by.lower())
        or "scheduler" in invoked_by.lower()
    )
    runtime_enforced = payload.get("runtime_enforced") is True or runtime_invocation.get(
        "runtime_enforced"
    ) is True
    runtime_enforced_scope = str(
        payload.get("runtime_enforced_scope")
        or runtime_invocation.get("runtime_enforced_scope")
        or ""
    )
    default_runtime_scheduler_invoked_raw = (
        payload.get("default_runtime_scheduler_invoked")
        if "default_runtime_scheduler_invoked" in payload
        else runtime_invocation.get("default_runtime_scheduler_invoked")
    )
    default_runtime_scheduler_invoked = (
        default_runtime_scheduler_invoked_raw is True
        or (
            default_runtime_scheduler_invoked_raw is None
            and runtime_enforced
            and "seed_cortex.scheduler.runtime" in invoked_by.lower()
        )
    )
    parent_dispatch_invoked = (
        payload.get("manual_parent_dispatch") is True
        or payload.get("parent_dispatch_invoked") is True
        or "parent" in invocation_scope.lower()
        or "parent" in invoked_by.lower()
    )
    activity_scope_scheduler_invoked = (
        runtime_enforced_scope == "seed_cortex_temporal_scheduler_invocation_packet_activity"
        or "scheduler_invocation_packet_activity" in invoked_by
    )
    dp_sidecar_execution_lanes_spawned = (
        payload.get("dp_sidecar_execution_lanes_spawned") is True
        or payload.get("dp_execution_lanes_spawned") is True
    )
    raw_lanes: Any = (
        payload.get("scheduler_spawned_lane_refs")
        or payload.get("scheduler_spawned_lanes")
        or payload.get("actual_spawned_lane_refs")
        or payload.get("spawned_lane_refs")
        or payload.get("spawned_lanes")
        or _dict_from(payload, "actual_dispatch_refs").get("scheduler_spawned_lane_refs")
        or []
    )
    lane_refs = [lane for lane in raw_lanes if isinstance(lane, dict)] if isinstance(raw_lanes, list) else []
    spawned_lanes = [
        lane
        for lane in lane_refs
        if str(lane.get("poll_status") or lane.get("dispatch_status") or "dispatched")
        not in NON_SPAWN_POLL_STATUSES
    ]
    return {
        "provided": True,
        "ref": json_ref(path),
        "scheduler_invoked": scheduler_invoked,
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": runtime_enforced_scope,
        "default_runtime_scheduler_invoked": default_runtime_scheduler_invoked,
        "parent_dispatch_invoked": parent_dispatch_invoked,
        "activity_scope_scheduler_invoked": activity_scope_scheduler_invoked,
        "dp_sidecar_execution_lanes_spawned": dp_sidecar_execution_lanes_spawned,
        "adoption_state": str(payload.get("adoption_state") or ""),
        "invocation_scope": invocation_scope,
        "invoked_by": invoked_by,
        "spawned_lane_refs": spawned_lanes,
    }


def lane_evidence_state(
    *,
    scheduler_invoked: bool,
    scheduler_spawned_lane_count: int,
    planned_lane_count: int,
    default_runtime_scheduler_invoked: bool = False,
    parent_dispatch_invoked: bool = False,
    activity_scope_scheduler_invoked: bool = False,
) -> str:
    if scheduler_invoked and scheduler_spawned_lane_count > 0:
        if not default_runtime_scheduler_invoked:
            if activity_scope_scheduler_invoked and not parent_dispatch_invoked:
                return "activity_scheduler_invoked_with_lane_refs_not_default_runtime"
            return "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
        return "scheduler_spawned_lanes_observed"
    if scheduler_invoked:
        return "scheduler_invoked_no_lane_spawn_evidence"
    if planned_lane_count > 0:
        return "planned_only_no_scheduler_spawn"
    return "no_lane_plan_available"


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("lane_evidence_state")
    scheduler_invoked = payload.get("scheduler_invoked") is True
    scheduler_ref = _dict_from(payload, "actual_dispatch_refs", "scheduler_invocation_ref")
    scheduler_ref_exists = scheduler_ref.get("exists") is True and scheduler_ref.get("json_valid") is True
    modes = [
        str(item)
        for item in payload.get("dp_sidecar_execution_modes_seen", [])
        if isinstance(item, str)
    ]
    actual_refs = _dict_from(payload, "actual_dispatch_refs")
    summaries = actual_refs.get("worker_and_activity_evidence_summaries")
    summaries = summaries if isinstance(summaries, list) else []
    activity_evidence_count = int(
        _dict_from(payload, "actual_dispatch_refs", "worker_and_activity_evidence_counts").get(
            "total_evidence_ref_count"
        )
        or 0
    )
    default_runtime_scheduler_invoked = (
        payload.get("default_runtime_scheduler_invoked") is True
    )
    parent_dispatch_invoked = payload.get("parent_dispatch_invoked") is True
    activity_scope_scheduler_invoked = payload.get("activity_scope_scheduler_invoked") is True
    checks = {
        "schema_version_locked": payload.get("schema_version") == SCHEMA_VERSION,
        "work_id_locked": payload.get("work_id") == WORK_ID,
        "route_profile_locked": payload.get("route_profile") == ROUTE_PROFILE,
        "adoption_state_not_promoted": payload.get("adoption_state") == ADOPTION_STATE,
        "completion_claim_blocked": payload.get("completion_claim_allowed") is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
        "spawned_by_this_runner_false": payload.get("spawned_by_this_runner") is False,
        "dp_search_is_mode_not_port_definition": payload.get(
            "dp_search_is_mode_not_port_definition"
        )
        is True,
        "dp_sidecar_execution_not_search_only": "search" in modes
        and any(mode != "search" for mode in modes),
        "planned_lane_count_present": int(payload.get("planned_lane_count") or 0) > 0,
        "planned_only_no_scheduler_spawn_boundary": (
            state != "planned_only_no_scheduler_spawn"
            or (
                scheduler_invoked is False
                and payload.get("scheduler_spawned_lane_count") == 0
                and payload.get("named_blocker") == PLANNED_ONLY_BLOCKER
                and payload.get("runtime_enforced") is False
            )
        ),
        "parent_dispatch_lanes_keep_default_runtime_blocker": (
            state != "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
            or (
                scheduler_invoked is True
                and parent_dispatch_invoked is True
                and default_runtime_scheduler_invoked is False
                and int(payload.get("scheduler_spawned_lane_count") or 0) > 0
                and payload.get("named_blocker") == PARENT_DISPATCH_ONLY_BLOCKER
                and payload.get("runtime_enforced") is False
            )
        ),
        "activity_scope_lanes_keep_default_runtime_blocker": (
            state != "activity_scheduler_invoked_with_lane_refs_not_default_runtime"
            or (
                scheduler_invoked is True
                and activity_scope_scheduler_invoked is True
                and default_runtime_scheduler_invoked is False
                and int(payload.get("scheduler_spawned_lane_count") or 0) > 0
                and payload.get("named_blocker") == ACTIVITY_SCOPE_ONLY_BLOCKER
                and payload.get("runtime_enforced") is False
            )
        ),
        "scheduler_invoked_without_spawn_has_named_blocker": (
            state != "scheduler_invoked_no_lane_spawn_evidence"
            or (
                scheduler_invoked is True
                and int(payload.get("scheduler_spawned_lane_count") or 0) == 0
                and payload.get("named_blocker") == INVOKED_NO_SPAWN_BLOCKER
            )
        ),
        "scheduler_spawned_count_requires_scheduler_invocation_ref": (
            int(payload.get("scheduler_spawned_lane_count") or 0) == 0
            or (scheduler_invoked and scheduler_ref_exists)
        ),
        "runtime_enforced_requires_scheduler_invocation_ref": (
            payload.get("runtime_enforced") is not True
            or (scheduler_invoked and scheduler_ref_exists)
        ),
        "runtime_enforced_requires_default_runtime_scheduler_invoked": (
            payload.get("runtime_enforced") is not True
            or default_runtime_scheduler_invoked is True
        ),
        "default_runtime_scheduler_invoked_requires_scheduler_ref": (
            default_runtime_scheduler_invoked is not True
            or (scheduler_invoked and scheduler_ref_exists)
        ),
        "worker_activity_evidence_not_counted_as_scheduler_spawned": (
            scheduler_invoked
            or int(payload.get("scheduler_spawned_lane_count") or 0) == 0
        )
        and activity_evidence_count >= 0,
        "activity_evidence_refs_remain_evidence_only": all(
            isinstance(item, dict)
            and item.get("counted_as_scheduler_spawned") is False
            and (
                not item.get("schema_version")
                or item.get("refs_are_not_execution_controllers") is True
            )
            for item in summaries
        ),
        "actual_dispatch_refs_bound": isinstance(actual_refs.get("parallel_dispatch_plan_ref"), dict)
        and isinstance(actual_refs.get("durable_parallel_wave_packet_ref"), dict)
        and isinstance(actual_refs.get("worker_dispatch_ledger_ref"), dict),
        "poll_refs_bound": isinstance(payload.get("poll_refs"), dict)
        and bool(_dict_from(payload, "poll_refs", "live_backend_watch_ref").get("path")),
        "fan_in_refs_bound": isinstance(payload.get("fan_in_refs"), dict)
        and bool(_dict_from(payload, "fan_in_refs", "parallel_fan_in_acceptance_ref").get("path"))
        and bool(_dict_from(payload, "fan_in_refs", "artifact_acceptance_queue_ref").get("path")),
        "evidence_refs_bound": isinstance(payload.get("evidence_refs"), dict)
        and bool(payload["evidence_refs"].get("runtime_latest"))
        and bool(payload["evidence_refs"].get("runtime_readback_zh")),
    }
    return {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}


def build_scheduler_spawned_lane_evidence(
    *,
    repo_root: str | Path = DEFAULT_REPO_ROOT,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    wave_id: str = DEFAULT_WAVE_ID,
    scheduler_invocation_ref: str | Path | None = None,
    output_latest: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_root)
    runtime = Path(runtime_root)
    scheduler_ref_path = Path(scheduler_invocation_ref) if scheduler_invocation_ref else None
    ref_paths = runtime_ref_paths(runtime, scheduler_ref_path)
    refs = {name: json_ref(path) for name, path in ref_paths.items()}
    payloads = {name: load_json(path) for name, path in ref_paths.items()}

    plan_lanes = selected_plan_lanes(payloads["parallel_dispatch_plan"])
    planned_lane_count = len(plan_lanes)
    planned_only_lanes = [
        lane for lane in plan_lanes if str(lane.get("dispatch_mode") or "") == "planned_only"
    ]
    planned_only_lane_ids = [lane_key(lane) for lane in planned_only_lanes]

    scheduler_summary = scheduler_invocation_summary(
        scheduler_ref_path, scheduler_invocation_payload(scheduler_ref_path)
    )
    scheduler_invoked = scheduler_summary["scheduler_invoked"] is True
    default_runtime_scheduler_invoked = (
        scheduler_summary["default_runtime_scheduler_invoked"] is True
    )
    parent_dispatch_invoked = scheduler_summary["parent_dispatch_invoked"] is True
    activity_scope_scheduler_invoked = (
        scheduler_summary.get("activity_scope_scheduler_invoked") is True
    )
    dp_sidecar_execution_lanes_spawned = (
        scheduler_summary["dp_sidecar_execution_lanes_spawned"] is True
    )
    scheduler_spawned_lane_refs = scheduler_summary["spawned_lane_refs"]
    scheduler_spawned_lane_count = len(scheduler_spawned_lane_refs) if scheduler_invoked else 0
    state = lane_evidence_state(
        scheduler_invoked=scheduler_invoked,
        scheduler_spawned_lane_count=scheduler_spawned_lane_count,
        planned_lane_count=planned_lane_count,
        default_runtime_scheduler_invoked=default_runtime_scheduler_invoked,
        parent_dispatch_invoked=parent_dispatch_invoked,
        activity_scope_scheduler_invoked=activity_scope_scheduler_invoked,
    )
    if not scheduler_invoked and planned_lane_count:
        named_blocker = PLANNED_ONLY_BLOCKER
    elif scheduler_invoked and scheduler_spawned_lane_count == 0:
        named_blocker = INVOKED_NO_SPAWN_BLOCKER
    elif scheduler_invoked and not default_runtime_scheduler_invoked:
        named_blocker = (
            ACTIVITY_SCOPE_ONLY_BLOCKER
            if activity_scope_scheduler_invoked and not parent_dispatch_invoked
            else PARENT_DISPATCH_ONLY_BLOCKER
        )
    else:
        named_blocker = ""
    effective_wave_id = wave_id or DEFAULT_WAVE_ID
    paths = output_paths(repo, runtime, effective_wave_id)

    durable_base_summary = actual_dispatch_summary(
        "durable_parallel_wave_packet_latest", payloads["durable_parallel_wave_packet"]
    )
    durable_temporal_summary = actual_dispatch_summary(
        "durable_parallel_wave_packet_temporal_activity_latest",
        payloads["durable_parallel_wave_packet_temporal_activity"],
    )
    default_trigger_summary = actual_dispatch_summary(
        "default_main_loop_trigger_candidate_latest",
        payloads["default_main_loop_trigger_candidate"],
    )
    default_trigger_temporal_summary = actual_dispatch_summary(
        "default_main_loop_trigger_candidate_temporal_activity_latest",
        payloads["default_main_loop_trigger_candidate_temporal_activity"],
    )
    worker_latest_entries = worker_dispatch_entry_summaries(payloads["worker_dispatch_ledger"])
    worker_temporal_entries = worker_dispatch_entry_summaries(
        payloads["worker_dispatch_ledger_temporal_activity"]
    )
    worker_activity_summaries = [
        durable_base_summary,
        durable_temporal_summary,
        default_trigger_summary,
        default_trigger_temporal_summary,
    ]
    mode_seen = dp_modes_seen(
        payloads["capability_port_mode_ontology"],
        payloads["durable_parallel_wave_packet"],
        payloads["durable_parallel_wave_packet_temporal_activity"],
    )

    runtime_enforced = (
        scheduler_invoked
        and default_runtime_scheduler_invoked
        and scheduler_summary.get("runtime_enforced") is True
        and scheduler_summary.get("provided") is True
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": effective_wave_id,
        "generated_at": now_iso(),
        "status": "scheduler_spawned_lane_evidence_ready",
        "lane_evidence_state": state,
        "named_blocker": named_blocker,
        "scheduler_invoked": scheduler_invoked,
        "default_runtime_scheduler_invoked": default_runtime_scheduler_invoked,
        "parent_dispatch_invoked": parent_dispatch_invoked,
        "activity_scope_scheduler_invoked": activity_scope_scheduler_invoked,
        "dp_sidecar_execution_lanes_spawned": dp_sidecar_execution_lanes_spawned,
        "scheduler_invocation_adoption_state": scheduler_summary.get("adoption_state") or "",
        "scheduler_invocation_scope": scheduler_summary.get("invocation_scope") or "",
        "spawned_by_this_runner": False,
        "planned_lane_count": planned_lane_count,
        "planned_only_lane_count": len(planned_only_lanes),
        "scheduler_spawned_lane_count": scheduler_spawned_lane_count,
        "dp_sidecar_execution_modes_seen": mode_seen,
        "dp_search_is_mode_not_port_definition": True,
        "actual_dispatch_refs": {
            "parallel_dispatch_plan_ref": refs["parallel_dispatch_plan"],
            "durable_parallel_wave_packet_ref": refs["durable_parallel_wave_packet"],
            "durable_parallel_wave_packet_temporal_activity_ref": refs[
                "durable_parallel_wave_packet_temporal_activity"
            ],
            "worker_dispatch_ledger_ref": refs["worker_dispatch_ledger"],
            "worker_dispatch_ledger_temporal_activity_ref": refs[
                "worker_dispatch_ledger_temporal_activity"
            ],
            "default_main_loop_trigger_candidate_ref": refs[
                "default_main_loop_trigger_candidate"
            ],
            "default_main_loop_trigger_candidate_temporal_activity_ref": refs[
                "default_main_loop_trigger_candidate_temporal_activity"
            ],
            "scheduler_invocation_ref": scheduler_summary.get("ref") or {"exists": False},
            "scheduler_invocation_summary": {
                "provided": scheduler_summary.get("provided") is True,
                "scheduler_invoked": scheduler_invoked,
                "default_runtime_scheduler_invoked": default_runtime_scheduler_invoked,
                "parent_dispatch_invoked": parent_dispatch_invoked,
                "activity_scope_scheduler_invoked": activity_scope_scheduler_invoked,
                "dp_sidecar_execution_lanes_spawned": dp_sidecar_execution_lanes_spawned,
                "adoption_state": scheduler_summary.get("adoption_state") or "",
                "invocation_scope": scheduler_summary.get("invocation_scope") or "",
                "invoked_by": scheduler_summary.get("invoked_by") or "",
                "runtime_enforced_scope": scheduler_summary.get("runtime_enforced_scope") or "",
            },
            "planned_lane_assignments": plan_lanes,
            "planned_only_lane_ids": planned_only_lane_ids,
            "planned_only_lane_count": len(planned_only_lanes),
            "scheduler_spawned_lane_refs": scheduler_spawned_lane_refs
            if scheduler_invoked
            else [],
            "scheduler_spawned_lane_count": scheduler_spawned_lane_count,
            "worker_and_activity_evidence_summaries": worker_activity_summaries,
            "worker_dispatch_ledger_entry_summaries": worker_latest_entries,
            "worker_dispatch_ledger_temporal_entry_summaries": worker_temporal_entries,
            "worker_and_activity_evidence_counts": {
                "durable_base_codex_subagent_count": durable_base_summary[
                    "codex_subagent_count"
                ],
                "durable_temporal_codex_subagent_count": durable_temporal_summary[
                    "codex_subagent_count"
                ],
                "default_trigger_base_codex_subagent_count": default_trigger_summary[
                    "codex_subagent_count"
                ],
                "default_trigger_temporal_codex_subagent_count": default_trigger_temporal_summary[
                    "codex_subagent_count"
                ],
                "worker_dispatch_ledger_entry_count": len(worker_latest_entries),
                "worker_dispatch_ledger_temporal_entry_count": len(worker_temporal_entries),
                "total_evidence_ref_count": len(worker_activity_summaries)
                + len(worker_latest_entries)
                + len(worker_temporal_entries),
            },
            "worker_or_activity_evidence_refs_not_counted_as_scheduler_spawned": True,
            "refs_are_evidence_only": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
        },
        "poll_refs": {
            "live_backend_watch_ref": refs["codex_s_live_backend_watch"],
            "durable_packet_poll_refs": _dict_from(
                payloads["durable_parallel_wave_packet"], "poll_refs"
            ),
            "default_trigger_poll_refs": _dict_from(
                payloads["default_main_loop_trigger_candidate"], "poll_refs"
            ),
            "poll_policy": "poll_live_backend_watch_first",
        },
        "fan_in_refs": {
            "parallel_fan_in_acceptance_ref": refs["parallel_fan_in_acceptance"],
            "artifact_acceptance_queue_ref": refs["artifact_acceptance_queue"],
            "durable_packet_fan_in_refs": _dict_from(
                payloads["durable_parallel_wave_packet"], "fan_in_refs"
            ),
            "default_trigger_fan_in_refs": _dict_from(
                payloads["default_main_loop_trigger_candidate"], "fan_in_refs"
            ),
            "fan_in_required_before_fact_promotion": True,
            "artifact_acceptance_queue_required": True,
            "direct_fact_promotion_allowed": False,
        },
        "evidence_refs": {
            **paths,
            "runtime_wave_record_digest_sha256": "",
            "parallel_dispatch_plan_latest": str(ref_paths["parallel_dispatch_plan"]),
            "durable_parallel_wave_packet_latest": str(ref_paths["durable_parallel_wave_packet"]),
            "durable_parallel_wave_packet_temporal_activity_latest": str(
                ref_paths["durable_parallel_wave_packet_temporal_activity"]
            ),
            "worker_dispatch_ledger_latest": str(ref_paths["worker_dispatch_ledger"]),
            "worker_dispatch_ledger_temporal_activity_latest": str(
                ref_paths["worker_dispatch_ledger_temporal_activity"]
            ),
            "default_main_loop_trigger_candidate_latest": str(
                ref_paths["default_main_loop_trigger_candidate"]
            ),
            "default_main_loop_trigger_candidate_temporal_activity_latest": str(
                ref_paths["default_main_loop_trigger_candidate_temporal_activity"]
            ),
            "capability_port_mode_ontology_latest": str(
                ref_paths["capability_port_mode_ontology"]
            ),
        },
        "readback_refs": {
            "runtime_readback_zh": paths["runtime_readback_zh"],
            "human_visible_readback_required": True,
        },
        "adoption_state": ADOPTION_STATE,
        "adoption_boundary": {
            "adoption_state": ADOPTION_STATE,
            "state_meaning_cn": (
                "已有 writer/schema/test/verifier/latest/readback，可以诚实区分 planned_only、"
                "worker/activity evidence 和 scheduler-spawned lane；但还没有被默认 scheduler "
                "runtime 强制调用。"
            ),
            "missing_to_next_state_cn": (
                "需要真实 scheduler invocation ref 指向已经运行的调度器调用，并由 focused "
                "verifier 证明 lane spawn、poll、fan-in、evidence/readback 绑定。"
            ),
        },
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": (
            "scheduler_invocation_ref_only" if runtime_enforced else ""
        ),
        "completion_claim_allowed": False,
        "phase0_completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload["validation"] = build_validation(payload)
    if not payload["validation"]["passed"]:
        payload["status"] = "scheduler_spawned_lane_evidence_validation_blocked"
    payload["evidence_refs"]["runtime_wave_record_digest_sha256"] = sha256_payload_without_digest(payload)
    if write:
        latest_path = Path(output_latest) if output_latest else Path(paths["runtime_latest"])
        payload["evidence_refs"]["selected_runtime_latest"] = str(latest_path)
        payload["evidence_refs"]["runtime_wave_record_digest_sha256"] = sha256_payload_without_digest(payload)
        write_json(Path(paths["runtime_wave_record"]), payload)
        write_json(latest_path, payload)
        write_text(Path(paths["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Scheduler Spawned Lane Evidence readback",
            "",
            SENTINEL,
            "",
            f"- lane_evidence_state: `{payload['lane_evidence_state']}`",
            f"- wave_id: `{payload['wave_id']}`",
            f"- named_blocker: `{payload['named_blocker']}`",
            f"- scheduler_invoked: {payload['scheduler_invoked']}",
            f"- default_runtime_scheduler_invoked: {payload['default_runtime_scheduler_invoked']}",
            f"- parent_dispatch_invoked: {payload['parent_dispatch_invoked']}",
            f"- activity_scope_scheduler_invoked: {payload['activity_scope_scheduler_invoked']}",
            f"- dp_sidecar_execution_lanes_spawned: {payload['dp_sidecar_execution_lanes_spawned']}",
            f"- spawned_by_this_runner: {payload['spawned_by_this_runner']}",
            f"- planned_lane_count: {payload['planned_lane_count']}",
            f"- scheduler_spawned_lane_count: {payload['scheduler_spawned_lane_count']}",
            f"- runtime_enforced: {payload['runtime_enforced']}",
            f"- completion_claim_allowed: {payload['completion_claim_allowed']}",
            f"- dp_sidecar_execution_modes_seen: {', '.join(payload['dp_sidecar_execution_modes_seen'])}",
            "- DP 是 `dp_sidecar_execution_port`，不是 search-only；`dp_search` 只是 search mode。",
            "- durable/base/temporal/default-trigger/worker ledger 中的 codex_subagent_count 和 activity refs 在没有 scheduler invocation ref 时只算 worker/activity evidence。",
            "- parent scheduler invocation refs 可以证明当前父窗口实际派过 lane，但在 `default_runtime_scheduler_invoked=false` 时仍不是默认热路径。",
            "- planned_only lane assignment 不能升级成 scheduler-spawned lane。",
            "",
            f"- 能力采纳状态：{payload['adoption_state']}。",
            f"- 这代表：{payload['adoption_boundary']['state_meaning_cn']}",
            f"- 还缺什么才能进入下一状态：{payload['adoption_boundary']['missing_to_next_state_cn']}",
            "",
            f"- latest: `{payload['evidence_refs']['runtime_latest']}`",
            f"- immutable wave record: `{payload['evidence_refs']['runtime_wave_record']}`",
            f"- immutable wave digest: `{payload['evidence_refs']['runtime_wave_record_digest_sha256']}`",
            f"- verifier: `{payload['evidence_refs']['verifier']}`",
            "",
            SENTINEL,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--wave-id", default=DEFAULT_WAVE_ID)
    parser.add_argument("--scheduler-invocation-ref", default="")
    parser.add_argument("--output-latest", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build_scheduler_spawned_lane_evidence(
        repo_root=args.repo_root,
        runtime_root=args.runtime_root,
        wave_id=args.wave_id,
        scheduler_invocation_ref=args.scheduler_invocation_ref or None,
        output_latest=args.output_latest or None,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "lane_evidence_state": payload["lane_evidence_state"],
                "scheduler_invoked": payload["scheduler_invoked"],
                "scheduler_spawned_lane_count": payload["scheduler_spawned_lane_count"],
                "named_blocker": payload["named_blocker"],
                "runtime_latest": payload["evidence_refs"]["runtime_latest"],
                "runtime_readback_zh": payload["evidence_refs"]["runtime_readback_zh"],
                "validation_passed": payload["validation"]["passed"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
