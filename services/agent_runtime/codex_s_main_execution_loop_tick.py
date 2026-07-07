from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.main_execution_loop_tick.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_MAIN_EXECUTION_LOOP_TICK_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
SRC_ROOT = DEFAULT_REPO / "src"
if str(DEFAULT_REPO) not in sys.path:
    sys.path.insert(0, str(DEFAULT_REPO))
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

MAIN_EXECUTION_LOOP = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
]


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
    if path.name == "latest.json" and path.parent.name == "codex_s_main_execution_loop_tick":
        existing = read_json_payload(path)
        existing_invocation = (
            existing.get("runtime_entrypoint_invocation")
            if isinstance(existing.get("runtime_entrypoint_invocation"), dict)
            else {}
        )
        incoming_invocation = (
            payload.get("runtime_entrypoint_invocation")
            if isinstance(payload.get("runtime_entrypoint_invocation"), dict)
            else {}
        )
        existing_p0_007 = (
            existing.get("p0_007_default_main_loop_trigger_bind")
            if isinstance(existing.get("p0_007_default_main_loop_trigger_bind"), dict)
            else {}
        )
        incoming_p0_007 = (
            payload.get("p0_007_default_main_loop_trigger_bind")
            if isinstance(payload.get("p0_007_default_main_loop_trigger_bind"), dict)
            else {}
        )
        incoming_status = str(payload.get("status") or "")
        incoming_has_blocker = bool(str(payload.get("named_blocker") or "").strip())
        incoming_is_blocked = "blocked" in incoming_status.lower()
        existing_enforced = (
            existing_invocation.get("runtime_enforced") is True
            or existing_p0_007.get("default_main_loop_trigger_runtime_enforced") is True
        )
        existing_p0_007_enforced = (
            existing_p0_007.get("default_main_loop_trigger_runtime_enforced") is True
            or existing_p0_007.get("current_worker_brief_queue_consumed_by_temporal_main_tick")
            is True
        )
        incoming_enforced = (
            incoming_invocation.get("runtime_enforced") is True
            or incoming_p0_007.get("default_main_loop_trigger_runtime_enforced") is True
        )
        incoming_p0_007_enforced = (
            incoming_p0_007.get("default_main_loop_trigger_runtime_enforced") is True
            or incoming_p0_007.get("current_worker_brief_queue_consumed_by_temporal_main_tick")
            is True
        )
        if (
            (
                (existing_enforced and not incoming_enforced)
                or (existing_p0_007_enforced and not incoming_p0_007_enforced)
            )
            and not incoming_has_blocker
            and not incoming_is_blocked
        ):
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def load_sibling_module(module_name: str):
    path = Path(__file__).parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ref.update({"json_valid": False, "json_error": str(exc)})
        return ref
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed"),
            "adoption_state": payload.get("adoption_state"),
            "continue_dispatch_expected": payload.get("continue_dispatch_expected"),
            "foreground_poll_required": payload.get("foreground_poll_required"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def read_json_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(
            runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json"
        ),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "codex_s_main_execution_loop_tick_20260702.md"
        ),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_main_execution_loop_tick.v1.json"),
        "writer": str(repo / "services" / "agent_runtime" / "codex_s_main_execution_loop_tick.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_codex_s_main_execution_loop_tick.py"),
        "verifier": str(repo / "scripts" / "verify_codex_s_main_execution_loop_tick.ps1"),
    }


def decide_next_wave(
    *,
    live_payload: dict[str, Any],
    source_payload: dict[str, Any],
    source_frontier_payload: dict[str, Any] | None = None,
    source_family_payload: dict[str, Any] | None = None,
    durable_payload: dict[str, Any],
    worker_ledger_ref: dict[str, Any],
    worker_ledger_payload: dict[str, Any] | None = None,
    worker_dispatch_ledger_activity_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_frontier_next_actions = (
        source_frontier_payload.get("next_frontier_machine_actions", {})
        if isinstance(source_frontier_payload, dict)
        else {}
    )
    source_frontier_ready = (
        isinstance(source_frontier_payload, dict)
        and source_frontier_payload.get("validation", {}).get("passed") is True
        and source_frontier_payload.get("task_id") == "wave3_20260702_absorption_slice_20260704"
        and source_frontier_payload.get("parent_task_id") == WORK_ID
        and source_frontier_payload.get("routing") == "continue_same_task"
        and source_frontier_next_actions.get("should_continue_loop") is True
    )
    source_frontier_module_consumed = (
        isinstance(source_frontier_payload, dict)
        and source_frontier_payload.get("validation", {}).get("passed") is True
        and source_frontier_payload.get("task_id") == "wave3_20260702_absorption_slice_20260704"
        and source_frontier_payload.get("parent_task_id") == WORK_ID
        and source_frontier_payload.get("routing") == "continue_same_task"
        and source_frontier_next_actions.get("should_continue_loop") is False
        and source_frontier_next_actions.get("source_frontier_gap", {}).get(
            "source_package_gap_open"
        )
        is False
    )
    source_family_ready = (
        isinstance(source_family_payload, dict)
        and source_family_payload.get("validation", {}).get("passed") is True
        and source_family_payload.get("task_id") == "wave4_20260701_frontier_source_family_20260704"
        and source_family_payload.get("parent_task_id") == WORK_ID
        and source_family_payload.get("routing") == "continue_same_task"
        and source_family_payload.get("next_frontier_machine_actions", {}).get(
            "should_continue_loop"
        )
        is True
    )
    source_family_next_actions = (
        source_family_payload.get("next_frontier_machine_actions", {})
        if isinstance(source_family_payload, dict)
        else {}
    )
    source_family_gap = (
        source_family_next_actions.get("source_frontier_gap", {})
        if isinstance(source_family_next_actions, dict)
        else {}
    )
    source_frontier_active_or_consumed = source_frontier_ready or source_frontier_module_consumed
    if (
        live_payload.get("foreground_poll_required") is True
        and not source_frontier_active_or_consumed
    ):
        return {
            "decision": "poll_live_backend_watch",
            "named_blocker": "LIVE_BACKEND_POLL_REQUIRED",
            "continue_main_loop": True,
        }
    if (
        source_payload.get("continue_dispatch_expected") is not True
        and not source_frontier_active_or_consumed
    ):
        return {
            "decision": "restore_or_source_anchor_gap",
            "named_blocker": "SOURCE_ANCHOR_CONTINUATION_NOT_READY",
            "continue_main_loop": True,
        }
    if durable_payload.get("continue_dispatch_expected") is not True:
        return {
            "decision": "repair_durable_parallel_wave_packet_refs",
            "named_blocker": "DURABLE_WAVE_PACKET_NOT_READY",
            "continue_main_loop": True,
        }
    if worker_ledger_ref.get("exists") is not True:
        return {
            "decision": "dispatch_worker_dispatch_ledger_next",
            "named_blocker": "WORKER_DISPATCH_LEDGER_NOT_READY",
            "continue_main_loop": True,
        }
    if worker_ledger_ref.get("validation_passed") is not True:
        return {
            "decision": "repair_worker_dispatch_ledger_validation",
            "named_blocker": "WORKER_DISPATCH_LEDGER_VALIDATION_FAILED",
            "continue_main_loop": True,
        }
    activity_ref = (
        worker_dispatch_ledger_activity_ref
        if isinstance(worker_dispatch_ledger_activity_ref, dict)
        else {}
    )
    ledger_payload = worker_ledger_payload if isinstance(worker_ledger_payload, dict) else {}
    if activity_ref:
        if activity_ref.get("runtime_enforced") is not True:
            return {
                "decision": "repair_worker_dispatch_ledger_activity_ref",
                "named_blocker": "WORKER_DISPATCH_LEDGER_ACTIVITY_NOT_RUNTIME_ENFORCED",
                "continue_main_loop": True,
            }
        succeeded_count = int(
            activity_ref.get("ledger_succeeded_count")
            or ledger_payload.get("succeeded_count")
            or ledger_payload.get("poll_result_summary", {}).get("succeeded_count")
            or 0
        )
        if succeeded_count <= 0:
            return {
                "decision": "dispatch_worker_dispatch_ledger_next",
                "named_blocker": "WORKER_DISPATCH_LEDGER_NO_SUCCEEDED_POLL",
                "continue_main_loop": True,
            }
    if source_frontier_module_consumed and not source_family_ready:
        return {
            "decision": "dispatch_source_family_wave_scheduler",
            "named_blocker": "SOURCE_FAMILY_WAVE_SCHEDULER_NOT_READY",
            "continue_main_loop": True,
            "next_frontier_scope": "20260701_total_source_frontier",
        }
    if source_frontier_module_consumed and source_family_ready:
        next_action = str(
            source_family_gap.get("next_gap_action")
            or (
                source_family_next_actions.get("next_frontier", [{}])[0].get("action")
                if isinstance(source_family_next_actions.get("next_frontier"), list)
                and source_family_next_actions.get("next_frontier")
                and isinstance(source_family_next_actions.get("next_frontier")[0], dict)
                else ""
            )
            or "continue_phase4_total_source_frontier_absorption"
        )
        remaining_count = int(source_family_gap.get("remaining_topic_family_count") or 0)
        decision = (
            "source_family_wave_ready_continue_phase4_total_source_frontier"
            if next_action == "continue_phase4_total_source_frontier_absorption"
            or remaining_count > 0
            else "source_family_wave_ready_continue_next_phase"
        )
        return {
            "decision": decision,
            "named_blocker": "",
            "continue_main_loop": True,
            "next_frontier_scope": str(
                source_family_gap.get("gap_scope") or "20260701_total_source_frontier"
            ),
            "next_frontier_action": next_action,
            "remaining_topic_family_count": remaining_count,
        }
    return {
        "decision": "fan_in_or_next_wave_ready",
        "named_blocker": "",
        "continue_main_loop": True,
    }


def ensure_seed_lab_user_correction_runtime_surface(
    *,
    runtime_root: Path,
    service: Any | None,
    write_runtime: bool,
) -> dict[str, Any]:
    if service is None:
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime_root)
        service_source = "build_default_service"
    else:
        service_source = "injected_seed_cortex_service"

    payload = service.seed_lab_user_correction_runtime(
        episode_id="seedcortex-main-loop-user-correction-runtime-20260702",
        request_id=f"{WORK_ID}-main-loop-user-correction-runtime",
        correction_event_id=f"{WORK_ID}-main-loop-user-correction-event",
        user_correction_zh=(
            "主执行循环 tick 在 durable packet 前刷新 CorrectionIntake、"
            "ExperimentReviewView、ReplayCourt candidate runtime refs；"
            "不晋升 memory/policy，不声明 runtime_enforced。"
        ),
        write_runtime=write_runtime,
    )

    state = runtime_root / "state"
    service_ref = json_ref(
        state / "seed_lab_user_correction_runtime" / "service_entrypoint_latest.json"
    )
    correction_ref = json_ref(state / "seed_lab_correction_intake" / "latest.json")
    review_ref = json_ref(state / "seed_lab_experiment_review_view" / "latest.json")
    replay_ref = json_ref(state / "seed_lab_replay_court" / "latest.json")
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    refs_ready_for_durable = all(
        ref.get("exists") is True
        and ref.get("json_valid") is True
        and ref.get("validation_passed") is True
        for ref in (service_ref, correction_ref, review_ref, replay_ref)
    )
    return {
        "schema_version": "xinao.codex_s.main_loop_tick_runtime_preflight_surface.v1",
        "surface_id": "seed_lab_user_correction_runtime_surface",
        "invoked_by_main_execution_loop_tick": True,
        "service_source": service_source,
        "status": payload.get("status"),
        "adoption_state": payload.get("adoption_state"),
        "validation_passed": validation.get("passed") is True,
        "checks": checks,
        "refs_ready_for_durable_packet": refs_ready_for_durable,
        "service_entrypoint_ref": service_ref,
        "correction_intake_ref": correction_ref,
        "experiment_review_view_ref": review_ref,
        "replay_court_ref": replay_ref,
        "runtime_enforced": payload.get("runtime_enforced") is True,
        "trigger_installed": payload.get("trigger_installed") is True,
        "memory_promotion_allowed": payload.get("memory_promotion_allowed") is True,
        "policy_promotion_allowed": payload.get("policy_promotion_allowed") is True,
        "completion_claim_allowed": payload.get("completion_claim_allowed") is True,
        "not_execution_controller": payload.get("not_execution_controller") is True,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
    }


def current_parent_scheduler_lanes(
    *,
    codex_subagents: list[str] | None,
    worker_ledger_payload: dict[str, Any],
) -> list[str]:
    lanes: list[str] = []
    for item in codex_subagents or []:
        raw = item.strip()
        if not raw:
            continue
        agent_id = raw.split(":", 1)[0].strip()
        if agent_id:
            lanes.append(f"current_parent_codex_subagent:{agent_id}")
    if lanes:
        return lanes
    entries = worker_ledger_payload.get("dispatch_entries")
    if not isinstance(entries, list):
        return ["current_parent_codex_subagent:codex_s_current_worker"]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mode = str(entry.get("mode") or "")
        poll_status = str(entry.get("poll_status") or "")
        agent_id = str(entry.get("agent_id") or "").strip()
        if mode not in {"worker", "subagent"}:
            continue
        if poll_status in {"planned_not_spawned", "not_applicable_not_spawned"}:
            continue
        if agent_id:
            lanes.append(f"current_parent_codex_subagent:{agent_id}")
    return lanes or ["current_parent_codex_subagent:codex_s_current_worker"]


def ensure_scheduler_current_parent_surface(
    *,
    runtime_root: Path,
    repo_root: Path,
    wave_id: str,
    codex_subagents: list[str] | None,
    worker_ledger_payload: dict[str, Any],
    write_runtime: bool,
) -> dict[str, Any]:
    capability_module = load_sibling_module("capability_port_mode_ontology")
    scheduler_packet_module = load_sibling_module("scheduler_invocation_packet")
    scheduler_lane_module = load_sibling_module("scheduler_spawned_lane_evidence")
    capability_payload = capability_module.build_capability_port_mode_ontology(
        runtime_root=runtime_root,
        repo_root=repo_root,
        write=write_runtime,
    )
    lanes = current_parent_scheduler_lanes(
        codex_subagents=codex_subagents,
        worker_ledger_payload=worker_ledger_payload,
    )
    scheduler_payload = scheduler_packet_module.build_scheduler_invocation_packet(
        runtime_root=runtime_root,
        repo_root=repo_root,
        spawned_lanes=lanes,
        current_parent_codex_invocation_ref=f"codex-parent-invocation:{wave_id}",
        write=write_runtime,
    )
    scheduler_latest = runtime_root / "state" / "scheduler_invocation_packet" / "latest.json"
    current_parent_latest = (
        runtime_root / "state" / "scheduler_spawned_lane_evidence" / "current_parent_latest.json"
    )
    lane_payload: dict[str, Any] = {}
    if write_runtime:
        lane_payload = scheduler_lane_module.build_scheduler_spawned_lane_evidence(
            runtime_root=runtime_root,
            repo_root=repo_root,
            scheduler_invocation_ref=scheduler_latest,
            output_latest=current_parent_latest,
            write=True,
        )
    validation = scheduler_payload.get("validation")
    if not isinstance(validation, dict):
        validation = {}
    lane_validation = lane_payload.get("validation")
    if not isinstance(lane_validation, dict):
        lane_validation = {}
    return {
        "schema_version": "xinao.codex_s.main_loop_tick_scheduler_current_parent_surface.v1",
        "invoked_by_main_execution_loop_tick": True,
        "capability_port_mode_ontology_ref": json_ref(
            runtime_root / "state" / "capability_port_mode_ontology" / "latest.json"
        ),
        "capability_port_mode_ontology_validation_passed": (
            capability_payload.get("validation", {}).get("passed") is True
        ),
        "scheduler_invocation_packet_ref": json_ref(scheduler_latest),
        "scheduler_spawned_lane_evidence_current_parent_ref": json_ref(current_parent_latest),
        "scheduler_invocation_status": scheduler_payload.get("status"),
        "scheduler_invoked": scheduler_payload.get("scheduler_invoked") is True,
        "parent_dispatch_invoked": scheduler_payload.get("parent_dispatch_invoked") is True,
        "scheduler_spawned_lane_count": int(scheduler_payload.get("spawned_lane_count") or 0),
        "current_parent_lane_evidence_state": lane_payload.get("lane_evidence_state"),
        "current_parent_lane_evidence_validation_passed": lane_validation.get("passed") is True,
        "default_runtime_scheduler_invoked": False,
        "runtime_enforced": False,
        "trigger_installed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
        "refs_ready_for_durable_packet": (
            write_runtime
            and validation.get("passed") is True
            and scheduler_payload.get("status") == "spawned_lane_refs_recorded"
            and scheduler_payload.get("runtime_enforced") is False
            and scheduler_payload.get("default_runtime_scheduler_invoked") is False
            and lane_payload.get("lane_evidence_state")
            == "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
            and lane_payload.get("runtime_enforced") is False
            and lane_payload.get("default_runtime_scheduler_invoked") is False
        ),
    }


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    continuation_mode_active: bool = True,
    explicit_user_stop: bool = False,
    codex_subagents: list[str] | None = None,
    worker_dispatch_ledger_activity_ref: dict[str, Any] | None = None,
    service: Any | None = None,
    external_mature_source_package: str | Path | None = None,
    wave_id: str = "codex-s-main-execution-wave-20260702",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    live_module = load_sibling_module("codex_s_live_backend_watch")
    source_module = load_sibling_module("source_anchor_gap_continuation")
    source_frontier_module = load_sibling_module("source_frontier_fanin_acceptance")
    source_frontier_workerbrief_bridge_module = load_sibling_module(
        "source_frontier_workerbrief_bridge"
    )
    source_family_module = load_sibling_module("source_family_wave_scheduler")
    durable_module = load_sibling_module("durable_parallel_wave_packet")
    allocation_module = load_sibling_module("allocation_plan")
    pre_pass_module = load_sibling_module("pre_pass_audit_loop")
    worker_ledger_module = load_sibling_module("worker_dispatch_ledger")
    external_mature_bridge_module = load_sibling_module(
        "external_research_strategy_mutation_bridge"
    )

    live_payload = live_module.build(
        runtime_root=runtime,
        repo_root=repo,
        explicit_user_stop=explicit_user_stop,
        write=write,
    )
    source_payload = source_module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor_package_root,
        continuation_mode_active=continuation_mode_active,
        explicit_user_stop_requested=explicit_user_stop,
        write=write,
    )
    activity_ref = (
        worker_dispatch_ledger_activity_ref
        if isinstance(worker_dispatch_ledger_activity_ref, dict)
        else {}
    )
    activity_ledger_path = Path(
        str(
            activity_ref.get("ledger_latest_ref")
            or activity_ref.get("ledger_temporal_activity_latest_ref")
            or ""
        )
    )
    worker_ledger_payload = {}
    if activity_ref.get("runtime_enforced") is True and activity_ledger_path.is_file():
        worker_ledger_payload = read_json_payload(activity_ledger_path)
    if not worker_ledger_payload:
        worker_ledger_payload = worker_ledger_module.build_worker_dispatch_ledger(
            repo_root=repo,
            runtime_root=runtime,
            wave_id=wave_id,
            task_id=WORK_ID,
            codex_subagents=codex_subagents or [],
            write=write,
        )
    source_frontier_surface = source_frontier_module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor_package_root,
        wave_id=f"{wave_id}-source-frontier-fanin",
        invoked_by_main_execution_loop_tick=True,
        write=write,
    )
    source_frontier_gap_open_for_block4 = (
        source_frontier_surface.get("next_frontier_machine_actions", {})
        .get("source_frontier_gap", {})
        .get("source_package_gap_open")
    )
    source_family_surface: dict[str, Any] = {
        "status": "source_family_wave_scheduler_waiting_for_wave3_consumed",
        "task_id": "wave4_20260701_frontier_source_family_20260704",
        "parent_task_id": WORK_ID,
        "routing": "continue_same_task",
        "validation": {"passed": True},
        "not_execution_controller": True,
        "completion_claim_allowed": False,
    }
    if source_frontier_gap_open_for_block4 is False:
        source_family_surface = source_family_module.build(
            runtime_root=runtime,
            repo_root=repo,
            anchor_package_root=anchor_package_root,
            wave_id=f"{wave_id}-source-family",
            invoked_by_main_execution_loop_tick=True,
            write=write,
        )
    user_correction_surface = ensure_seed_lab_user_correction_runtime_surface(
        runtime_root=runtime,
        service=service,
        write_runtime=write,
    )
    scheduler_surface = ensure_scheduler_current_parent_surface(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        codex_subagents=codex_subagents or [],
        worker_ledger_payload=worker_ledger_payload,
        write_runtime=write,
    )
    durable_payload = durable_module.build(
        runtime_root=runtime,
        repo_root=repo,
        codex_subagents=codex_subagents or [],
        wave_id=wave_id,
        write=write,
    )
    scheduler_surface = ensure_scheduler_current_parent_surface(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        codex_subagents=codex_subagents or [],
        worker_ledger_payload=worker_ledger_payload,
        write_runtime=write,
    )
    external_mature_bridge_payload = external_mature_bridge_module.run_bridge(
        runtime_root=runtime,
        repo_root=repo,
        source_package=external_mature_source_package
        or external_mature_bridge_module.DEFAULT_SOURCE_PACKAGE,
        wave_id=f"{wave_id}-external-mature-strategy-bridge",
        write=write,
    )
    state = runtime / "state"
    worker_ledger_ref = json_ref(state / "worker_dispatch_ledger" / "latest.json")
    if not write:
        worker_ledger_ref = {
            "path": str(state / "worker_dispatch_ledger" / "latest.json"),
            "exists": False,
            "json_valid": True,
            "schema_version": worker_ledger_payload.get("schema_version"),
            "status": worker_ledger_payload.get("status"),
            "sentinel": worker_ledger_payload.get("sentinel"),
            "validation_passed": worker_ledger_payload.get("validation", {}).get("passed"),
            "adoption_state": worker_ledger_payload.get("adoption_state"),
            "not_execution_controller": worker_ledger_payload.get("not_execution_controller"),
            "in_memory_build_only": True,
        }
    next_wave_decision = decide_next_wave(
        live_payload=live_payload,
        source_payload=source_payload,
        source_frontier_payload=source_frontier_surface,
        source_family_payload=source_family_surface,
        durable_payload=durable_payload,
        worker_ledger_ref=worker_ledger_ref,
        worker_ledger_payload=worker_ledger_payload,
        worker_dispatch_ledger_activity_ref=activity_ref,
    )
    output = output_paths(repo, runtime)
    allocation_payload = allocation_module.build(
        runtime_root=runtime,
        repo_root=repo,
        task_id=WORK_ID,
        wave_id=f"{wave_id}-allocation-plan",
        extra_refs={
            "workflow_refs": [
                str(state / "codex_s_main_execution_loop_tick" / "latest.json"),
                str(state / "durable_parallel_wave_packet" / "latest.json"),
            ],
            "worker_ledger_refs": [
                str(state / "worker_dispatch_ledger" / "latest.json"),
                str(activity_ref.get("ledger_temporal_activity_latest_ref", "")),
            ],
            "source_frontier_refs": [
                source_frontier_surface.get("output_paths", {}).get("runtime_latest", ""),
                source_family_surface.get("output_paths", {}).get("runtime_latest", "")
                if isinstance(source_family_surface.get("output_paths"), dict)
                else "",
            ],
            "fan_in_refs": [
                durable_payload.get("fan_in_acceptance_ref", ""),
                durable_payload.get("artifact_acceptance_queue_ref", ""),
            ],
            "event_history_refs": [
                str(
                    (worker_dispatch_ledger_activity_ref or {}).get(
                        "ledger_temporal_activity_latest_ref", ""
                    )
                )
            ],
        },
        invoked_by_main_execution_loop_tick=True,
        write=write,
    )
    source_frontier_workerbrief_bridge_payload = source_frontier_workerbrief_bridge_module.build(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=f"{wave_id}-source-frontier-workerbrief-bridge",
        workflow_id=f"{wave_id}-main-execution-loop-tick",
        activity_context={
            "invoked_by": "codex_s_main_execution_loop_tick.build",
            "source_frontier_surface_ref": source_frontier_surface.get("output_paths", {}).get(
                "runtime_latest", ""
            ),
            "source_family_surface_ref": source_family_surface.get("output_paths", {}).get(
                "runtime_latest", ""
            )
            if isinstance(source_family_surface.get("output_paths"), dict)
            else "",
            "allocation_plan_ref": allocation_payload.get("output_paths", {}).get("latest", ""),
            "allocation_worker_brief_queue_ref": allocation_payload.get("output_paths", {}).get(
                "worker_brief_queue_latest", ""
            ),
        },
        write=write,
    )
    pre_pass_payload = pre_pass_module.build(
        runtime_root=runtime,
        repo_root=repo,
        task_id=WORK_ID,
        wave_id=f"{wave_id}-pre-pass",
        extra_refs={
            "workflow_refs": [
                str(state / "codex_s_main_execution_loop_tick" / "latest.json"),
                str(state / "durable_parallel_wave_packet" / "latest.json"),
            ],
            "worker_ledger_refs": [
                str(state / "worker_dispatch_ledger" / "latest.json"),
                str(activity_ref.get("ledger_temporal_activity_latest_ref", "")),
            ],
            "source_frontier_refs": [
                source_frontier_surface.get("output_paths", {}).get("runtime_latest", ""),
                source_family_surface.get("output_paths", {}).get("runtime_latest", "")
                if isinstance(source_family_surface.get("output_paths"), dict)
                else "",
            ],
            "fan_in_refs": [
                durable_payload.get("fan_in_acceptance_ref", ""),
                durable_payload.get("artifact_acceptance_queue_ref", ""),
                allocation_payload.get("output_paths", {}).get("latest", ""),
                source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get("wave", ""),
            ],
            "readback_refs": [
                output["runtime_readback_zh"],
                source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                    "readback_zh", ""
                ),
            ],
        },
        invoked_by_main_execution_loop_tick=True,
        write=write,
    )
    if pre_pass_payload.get("pre_pass_payload", {}).get("repair_required") is True:
        next_wave_decision = {
            **next_wave_decision,
            "decision": "dispatch_repair_plan",
            "named_blocker": "",
            "continue_main_loop": True,
            "pre_pass_repair_plan_ref": pre_pass_payload.get("repair_plan_ref", ""),
        }
    elif pre_pass_payload.get("named_blocker"):
        next_wave_decision = {
            **next_wave_decision,
            "decision": "pre_pass_named_blocker_recorded",
            "named_blocker": pre_pass_payload.get("named_blocker", ""),
            "continue_main_loop": True,
            "pre_pass_latest_ref": pre_pass_payload.get("output_paths", {}).get("latest", ""),
        }
    source_frontier_next_actions = source_frontier_surface.get("next_frontier_machine_actions", {})
    source_frontier_gap_open = source_frontier_next_actions.get("source_frontier_gap", {}).get(
        "source_package_gap_open"
    )
    source_frontier_continues_or_consumed = (
        source_frontier_next_actions.get("should_continue_loop") is True
        or source_frontier_gap_open is False
    )
    bridge_source_delta = (
        source_frontier_workerbrief_bridge_payload.get("source_frontier_delta")
        if isinstance(source_frontier_workerbrief_bridge_payload.get("source_frontier_delta"), dict)
        else {}
    )
    bridge_has_workerbrief_bindings = (
        int(source_frontier_workerbrief_bridge_payload.get("worker_brief_binding_count") or 0) > 0
    )
    bridge_empty_frontier_noop = (
        bridge_source_delta.get("status") == "empty_frontier_noop"
        and bridge_source_delta.get("generated_bounded_item") is False
        and int(bridge_source_delta.get("worker_brief_binding_count") or 0) == 0
    )
    checks = {
        "invoked_live_backend_watch": live_payload.get("schema_version")
        == "xinao.codex_s.live_backend_watch.v1",
        "invoked_source_anchor_gap_continuation": source_payload.get("schema_version")
        == "xinao.codex_s.source_anchor_gap_continuation.v1",
        "invoked_durable_parallel_wave_packet": durable_payload.get("schema_version")
        == "xinao.codex_s.durable_parallel_wave_packet.v1",
        "stop_guard_layers_are_not_main_loop": True,
        "main_loop_shape_preserved": MAIN_EXECUTION_LOOP
        == durable_payload.get("main_execution_loop"),
        "durable_packet_ready": durable_payload.get("continue_dispatch_expected") is True,
        "subagent_refs_recorded": durable_payload.get("codex_subagent_dispatch", {}).get(
            "recorded_subagent_count"
        )
        == len([item for item in (codex_subagents or []) if item.strip()]),
        "worker_dispatch_ledger_invoked": worker_ledger_payload.get("schema_version")
        == "xinao.codex_s.worker_dispatch_ledger.v1",
        "worker_dispatch_ledger_validation_passed": worker_ledger_payload.get("validation", {}).get(
            "passed"
        )
        is True,
        "seed_lab_user_correction_runtime_surface_prepared": (
            user_correction_surface.get("validation_passed") is True
            and user_correction_surface.get("refs_ready_for_durable_packet") is True
            and user_correction_surface.get("runtime_enforced") is False
            and user_correction_surface.get("trigger_installed") is False
            and user_correction_surface.get("memory_promotion_allowed") is False
            and user_correction_surface.get("policy_promotion_allowed") is False
            and user_correction_surface.get("completion_claim_allowed") is False
            and user_correction_surface.get("not_execution_controller") is True
        ),
        "source_frontier_fanin_acceptance_surface_prepared": (
            source_frontier_surface.get("validation", {}).get("passed") is True
            and source_frontier_surface.get("task_id") == "wave3_20260702_absorption_slice_20260704"
            and source_frontier_surface.get("parent_task_id") == WORK_ID
            and source_frontier_surface.get("routing") == "continue_same_task"
            and source_frontier_surface.get("default_hot_path_binding", {}).get(
                "fan_in_acceptance_queue_default_heart"
            )
            is True
            and source_frontier_surface.get("default_hot_path_binding", {}).get(
                "provider_scheduler_main_task"
            )
            is False
            and source_frontier_continues_or_consumed
            and source_frontier_next_actions.get("sleep_1800_main_loop_allowed") is False
        ),
        "source_family_wave_scheduler_surface_prepared": (
            source_frontier_gap_open is not False
            or (
                source_family_surface.get("validation", {}).get("passed") is True
                and source_family_surface.get("task_id")
                == "wave4_20260701_frontier_source_family_20260704"
                and source_family_surface.get("parent_task_id") == WORK_ID
                and source_family_surface.get("routing") == "continue_same_task"
                and source_family_surface.get("completion_claim_allowed") is False
                and source_family_surface.get("not_execution_controller") is True
            )
        ),
        "scheduler_current_parent_surface_prepared": (
            scheduler_surface.get("refs_ready_for_durable_packet") is True
            and scheduler_surface.get("scheduler_invoked") is True
            and scheduler_surface.get("parent_dispatch_invoked") is True
            and int(scheduler_surface.get("scheduler_spawned_lane_count") or 0) > 0
            and scheduler_surface.get("runtime_enforced") is False
            and scheduler_surface.get("default_runtime_scheduler_invoked") is False
            and scheduler_surface.get("not_execution_controller") is True
        ),
        "pre_pass_audit_loop_prepared": (
            pre_pass_payload.get("schema_version") == "xinao.codex_s.pre_pass_audit_loop.v1"
            and pre_pass_payload.get("validation", {}).get("passed") is True
            and pre_pass_payload.get("completion_claim_allowed") is False
            and pre_pass_payload.get("not_execution_controller") is True
        ),
        "allocation_plan_prepared": (
            allocation_payload.get("schema_version") == "xinao.codex_s.allocation_plan.v1"
            and allocation_payload.get("validation", {}).get("passed") is True
            and allocation_payload.get("not_task_route_decision_enum") is True
            and allocation_payload.get("target_width_source")
            == "derived_from_runtime_feedback_inputs"
            and allocation_payload.get("fixed_20_or_50_used") is False
            and allocation_payload.get("completion_claim_allowed") is False
            and allocation_payload.get("not_execution_controller") is True
        ),
        "external_mature_bridge_surface_prepared": (
            external_mature_bridge_payload.get("schema_version")
            == "xinao.codex_s.external_research_strategy_mutation_bridge.v1"
            and external_mature_bridge_payload.get("validation", {}).get("passed") is True
            and external_mature_bridge_payload.get("completion_claim_allowed") is False
            and external_mature_bridge_payload.get("not_execution_controller") is True
        ),
        "source_frontier_workerbrief_bridge_prepared": (
            source_frontier_workerbrief_bridge_payload.get("schema_version")
            == "xinao.codex_s.source_frontier_workerbrief_bridge.v1"
            and source_frontier_workerbrief_bridge_payload.get(
                "source_frontier_to_workerbrief_binding"
            )
            is True
            and source_frontier_workerbrief_bridge_payload.get("thin_binding_only") is True
            and source_frontier_workerbrief_bridge_payload.get("not_new_control_plane") is True
            and source_frontier_workerbrief_bridge_payload.get("latest_alias_is_not_proof") is True
            and (bridge_has_workerbrief_bindings or bridge_empty_frontier_noop)
            and source_frontier_workerbrief_bridge_payload.get("validation", {}).get("passed")
            is True
            and source_frontier_workerbrief_bridge_payload.get("completion_claim_allowed") is False
            and source_frontier_workerbrief_bridge_payload.get("not_execution_controller") is True
        ),
        "fan_in_bound": durable_payload.get("fan_in_policy", {}).get(
            "fan_in_required_before_fact_promotion"
        )
        is True,
        "artifact_acceptance_bound": durable_payload.get("fan_in_policy", {}).get(
            "artifact_acceptance_queue_required"
        )
        is True,
        "old_5d33_authority_disallowed": durable_payload.get(
            "legacy_5d33_transport_pattern", {}
        ).get("old_5d33_owner_allowed")
        is False,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "main_execution_loop_tick_ready"
        if all(checks.values())
        else "main_execution_loop_tick_blocked",
        "generated_at": now_iso(),
        "adoption_state": "verifier_ready_but_not_hooked",
        "ordinary_discussion_can_stop": True,
        "current_four_text_same_source_task_no_stop": continuation_mode_active
        and not explicit_user_stop,
        "explicit_user_stop_requested": explicit_user_stop,
        "stop_guard_layers": [
            "live_backend_watch_front_gate",
            "source_anchor_gap_continuation",
        ],
        "stop_guard_layers_are_main_execution_loop": False,
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "invoked_runners": {
            "live_backend_watch": {
                "state": str(state / "codex_s_live_backend_watch" / "latest.json"),
                "status": live_payload.get("status"),
                "foreground_poll_required": live_payload.get("foreground_poll_required"),
                "adoption_state": live_payload.get("adoption_state"),
                "not_execution_controller": live_payload.get("not_execution_controller"),
                "not_completion_decision": live_payload.get("not_completion_decision"),
                "not_user_completion": live_payload.get("not_user_completion"),
            },
            "source_anchor_gap_continuation": {
                "state": str(state / "source_anchor_gap_continuation" / "latest.json"),
                "status": source_payload.get("status"),
                "continue_dispatch_expected": source_payload.get("continue_dispatch_expected"),
                "adoption_state": source_payload.get("adoption_state"),
                "not_execution_controller": source_payload.get("not_execution_controller"),
            },
            "durable_parallel_wave_packet": {
                "state": str(state / "durable_parallel_wave_packet" / "latest.json"),
                "status": durable_payload.get("status"),
                "continue_dispatch_expected": durable_payload.get("continue_dispatch_expected"),
                "adoption_state": durable_payload.get("adoption_state"),
                "poll_refs": {
                    "foreground_poll_required": durable_payload.get("poll_refs", {}).get(
                        "foreground_poll_required"
                    ),
                    "poll_stop_guard_only": durable_payload.get("poll_refs", {}).get(
                        "poll_stop_guard_only"
                    ),
                    "poll_blocks_dispatch": durable_payload.get("poll_refs", {}).get(
                        "poll_blocks_dispatch"
                    ),
                    "source_frontier_ready": durable_payload.get("poll_refs", {}).get(
                        "source_frontier_ready"
                    ),
                },
                "not_execution_controller": durable_payload.get("not_execution_controller"),
            },
            "worker_dispatch_ledger": {
                "state": str(state / "worker_dispatch_ledger" / "latest.json"),
                "status": worker_ledger_payload.get("status"),
                "validation_passed": worker_ledger_payload.get("validation", {}).get("passed"),
                "adoption_state": worker_ledger_payload.get("adoption_state"),
                "not_execution_controller": worker_ledger_payload.get("not_execution_controller"),
            },
        },
        "runtime_preflight_refs": {
            "source_frontier_fanin_acceptance_surface": {
                "status": source_frontier_surface.get("status"),
                "adoption_state": source_frontier_surface.get("adoption_state"),
                "task_id": source_frontier_surface.get("task_id"),
                "parent_task_id": source_frontier_surface.get("parent_task_id"),
                "routing": source_frontier_surface.get("routing"),
                "runtime_enforced": source_frontier_surface.get("runtime_enforced"),
                "trigger_installed": source_frontier_surface.get("trigger_installed"),
                "source_package_gap_open": source_frontier_surface.get(
                    "next_frontier_machine_actions", {}
                )
                .get("source_frontier_gap", {})
                .get("source_package_gap_open"),
                "fan_in_acceptance_queue_default_heart": source_frontier_surface.get(
                    "default_hot_path_binding", {}
                ).get("fan_in_acceptance_queue_default_heart"),
                "provider_scheduler_main_task": source_frontier_surface.get(
                    "default_hot_path_binding", {}
                ).get("provider_scheduler_main_task"),
                "output_paths": source_frontier_surface.get("output_paths", {}),
                "validation_passed": source_frontier_surface.get("validation", {}).get("passed"),
                "not_execution_controller": source_frontier_surface.get("not_execution_controller"),
            },
            "source_family_wave_scheduler_surface": {
                "status": source_family_surface.get("status"),
                "adoption_state": source_family_surface.get("adoption_state"),
                "task_id": source_family_surface.get("task_id"),
                "parent_task_id": source_family_surface.get("parent_task_id"),
                "routing": source_family_surface.get("routing"),
                "source_family_count": len(
                    source_family_surface.get("claim_card_staging_queue", {}).get(
                        "source_families", []
                    )
                )
                if isinstance(source_family_surface.get("claim_card_staging_queue"), dict)
                else 0,
                "actual_dispatched_width": source_family_surface.get("dynamic_width", {}).get(
                    "actual_dispatched_width"
                )
                if isinstance(source_family_surface.get("dynamic_width"), dict)
                else 0,
                "target_width": source_family_surface.get("dynamic_width", {}).get("target_width")
                if isinstance(source_family_surface.get("dynamic_width"), dict)
                else 0,
                "artifact_acceptance_count": source_family_surface.get(
                    "artifact_acceptance_queue", {}
                ).get("accepted_artifact_count")
                if isinstance(source_family_surface.get("artifact_acceptance_queue"), dict)
                else 0,
                "next_frontier_scope": source_family_surface.get(
                    "next_frontier_machine_actions", {}
                )
                .get("source_frontier_gap", {})
                .get("gap_scope")
                if isinstance(source_family_surface.get("next_frontier_machine_actions"), dict)
                else "",
                "remaining_topic_family_count": source_family_surface.get(
                    "next_frontier_machine_actions", {}
                )
                .get("source_frontier_gap", {})
                .get("remaining_topic_family_count")
                if isinstance(source_family_surface.get("next_frontier_machine_actions"), dict)
                else None,
                "next_frontier_action": source_family_surface.get(
                    "next_frontier_machine_actions", {}
                )
                .get("source_frontier_gap", {})
                .get("next_gap_action")
                if isinstance(source_family_surface.get("next_frontier_machine_actions"), dict)
                else "",
                "total_source_frontier_coverage_ref": source_family_surface.get(
                    "next_frontier_machine_actions", {}
                )
                .get("source_frontier_gap", {})
                .get("coverage_ref")
                if isinstance(source_family_surface.get("next_frontier_machine_actions"), dict)
                else "",
                "runtime_enforced": source_family_surface.get("runtime_enforced") is True,
                "trigger_installed": source_family_surface.get("trigger_installed") is True,
                "validation_passed": source_family_surface.get("validation", {}).get("passed"),
                "not_execution_controller": source_family_surface.get("not_execution_controller"),
            },
            "seed_lab_user_correction_runtime_surface": user_correction_surface,
            "scheduler_current_parent_surface": scheduler_surface,
            "external_mature_strategy_mutation_bridge": {
                "status": external_mature_bridge_payload.get("status"),
                "latest_ref": external_mature_bridge_payload.get("output_paths", {}).get("latest"),
                "wave_ref": external_mature_bridge_payload.get("output_paths", {}).get("wave"),
                "external_mature_discovery_required": external_mature_bridge_payload.get(
                    "external_mature_discovery_decision", {}
                ).get("external_mature_discovery_required"),
                "codex_reflection_subagent_dispatch_required": external_mature_bridge_payload.get(
                    "external_mature_discovery_decision", {}
                ).get("codex_reflection_subagent_dispatch_required"),
                "reflection_subagent_dispatch_ref": external_mature_bridge_payload.get(
                    "output_paths", {}
                ).get("reflection_subagent_dispatch_wave"),
                "reflection_worker_dispatch_ledger_ref": external_mature_bridge_payload.get(
                    "output_paths", {}
                ).get("reflection_worker_dispatch_ledger_wave"),
                "strategy_mutation_candidate_ref": external_mature_bridge_payload.get(
                    "output_paths", {}
                ).get("strategy_candidate_wave"),
                "active_strategy_mutation": external_mature_bridge_payload.get(
                    "strategy_mutation", {}
                ).get("active"),
                "validation_passed": external_mature_bridge_payload.get("validation", {}).get(
                    "passed"
                ),
                "completion_claim_allowed": external_mature_bridge_payload.get(
                    "completion_claim_allowed"
                ),
                "not_execution_controller": external_mature_bridge_payload.get(
                    "not_execution_controller"
                ),
            },
            "allocation_plan": {
                "status": allocation_payload.get("status"),
                "latest_ref": allocation_payload.get("output_paths", {}).get("latest"),
                "worker_brief_queue_ref": allocation_payload.get("output_paths", {}).get(
                    "worker_brief_queue_latest"
                ),
                "lane_allocations_ref": allocation_payload.get("output_paths", {}).get(
                    "lane_allocations_latest"
                ),
                "dispatch_attempts_ref": allocation_payload.get("output_paths", {}).get(
                    "dispatch_attempts_latest"
                ),
                "repair_plan_ref": allocation_payload.get("output_paths", {}).get(
                    "repair_plan_latest"
                ),
                "readback_zh_ref": allocation_payload.get("output_paths", {}).get("readback_zh"),
                "lane_class_count": allocation_payload.get("lane_class_count"),
                "total_requested_width": allocation_payload.get("total_requested_width"),
                "target_width_source": allocation_payload.get("target_width_source"),
                "fixed_20_or_50_used": allocation_payload.get("fixed_20_or_50_used"),
                "invoked_by_main_execution_loop_tick": allocation_payload.get(
                    "invoked_by_main_execution_loop_tick"
                ),
                "completion_claim_allowed": allocation_payload.get("completion_claim_allowed"),
                "not_execution_controller": allocation_payload.get("not_execution_controller"),
                "validation_passed": allocation_payload.get("validation", {}).get("passed"),
            },
            "source_frontier_workerbrief_bridge": {
                "status": source_frontier_workerbrief_bridge_payload.get("status"),
                "latest_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("latest"),
                "wave_ref": source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                    "wave"
                ),
                "source_bound_worker_brief_queue_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("worker_brief_queue_latest"),
                "mapping_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("mapping_latest"),
                "worker_dispatch_ledger_wave_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("worker_dispatch_ledger_wave"),
                "worker_dispatch_ledger_activity_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("worker_dispatch_ledger_activity"),
                "readback_zh_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("readback_zh"),
                "source_item_count": source_frontier_workerbrief_bridge_payload.get(
                    "source_item_count"
                ),
                "worker_brief_binding_count": source_frontier_workerbrief_bridge_payload.get(
                    "worker_brief_binding_count"
                ),
                "generated_bounded_item": source_frontier_workerbrief_bridge_payload.get(
                    "source_frontier_delta", {}
                ).get("generated_bounded_item")
                if isinstance(
                    source_frontier_workerbrief_bridge_payload.get("source_frontier_delta"),
                    dict,
                )
                else None,
                "latest_alias_is_not_proof": source_frontier_workerbrief_bridge_payload.get(
                    "latest_alias_is_not_proof"
                ),
                "completion_claim_allowed": source_frontier_workerbrief_bridge_payload.get(
                    "completion_claim_allowed"
                ),
                "not_execution_controller": source_frontier_workerbrief_bridge_payload.get(
                    "not_execution_controller"
                ),
                "validation_passed": source_frontier_workerbrief_bridge_payload.get(
                    "validation", {}
                ).get("passed"),
            },
            "pre_pass_audit_loop": {
                "status": pre_pass_payload.get("status"),
                "fan_in_decision": pre_pass_payload.get("audit_fan_in", {}).get("decision"),
                "final_allowed": pre_pass_payload.get("final_allowed"),
                "repair_plan_ref": pre_pass_payload.get("repair_plan_ref"),
                "latest_ref": pre_pass_payload.get("output_paths", {}).get("latest"),
                "readback_zh_ref": pre_pass_payload.get("output_paths", {}).get("readback_zh"),
                "invoked_by_main_execution_loop_tick": pre_pass_payload.get(
                    "invoked_by_main_execution_loop_tick"
                ),
                "completion_claim_allowed": pre_pass_payload.get("completion_claim_allowed"),
                "not_execution_controller": pre_pass_payload.get("not_execution_controller"),
                "validation_passed": pre_pass_payload.get("validation", {}).get("passed"),
            },
            "preflight_refs_are_evidence_only": True,
            "preflight_refs_are_not_stop_guard_layers": True,
            "preflight_refs_are_not_completion_gates": True,
            "preflight_refs_are_not_execution_controllers": True,
        },
        "actual_dispatch_refs": {
            "codex_subagents": durable_payload.get("actual_dispatch_refs", {}).get(
                "codex_subagents", []
            ),
            "dp_sidecar_execution": durable_payload.get("dp_sidecar_execution"),
            "lane_assignments": durable_payload.get("lane_assignments", []),
            "worker_dispatch_ledger_ref": worker_ledger_ref,
            "worker_dispatch_ledger_activity_ref": dict(worker_dispatch_ledger_activity_ref or {}),
            "worker_dispatch_ledger_entries": worker_ledger_payload.get("dispatch_entries", []),
            "allocation_plan": {
                "latest_ref": allocation_payload.get("output_paths", {}).get("latest", ""),
                "worker_brief_queue_ref": allocation_payload.get("output_paths", {}).get(
                    "worker_brief_queue_latest", ""
                ),
                "lane_allocations_ref": allocation_payload.get("output_paths", {}).get(
                    "lane_allocations_latest", ""
                ),
                "lane_allocations": allocation_payload.get("lane_allocations", []),
                "dispatch_attempts_ref": allocation_payload.get("output_paths", {}).get(
                    "dispatch_attempts_latest", ""
                ),
                "target_width_source": allocation_payload.get("target_width_source", ""),
                "fixed_20_or_50_used": allocation_payload.get("fixed_20_or_50_used"),
            },
            "external_mature_strategy_mutation_bridge": {
                "wave_ref": external_mature_bridge_payload.get("output_paths", {}).get("wave", ""),
                "source_ledger_ref": external_mature_bridge_payload.get("output_paths", {}).get(
                    "source_ledger_wave", ""
                ),
                "claim_cards_ref": external_mature_bridge_payload.get("output_paths", {}).get(
                    "claim_cards_wave", ""
                ),
                "reflection_subagent_dispatch_ref": external_mature_bridge_payload.get(
                    "output_paths", {}
                ).get("reflection_subagent_dispatch_wave", ""),
                "reflection_worker_dispatch_ledger_ref": external_mature_bridge_payload.get(
                    "output_paths", {}
                ).get("reflection_worker_dispatch_ledger_wave", ""),
                "strategy_mutation_candidate_ref": external_mature_bridge_payload.get(
                    "output_paths", {}
                ).get("strategy_candidate_wave", ""),
                "active_strategy_mutation": external_mature_bridge_payload.get(
                    "strategy_mutation", {}
                ).get("active"),
            },
            "source_frontier_workerbrief_bridge": {
                "wave_ref": source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                    "wave", ""
                ),
                "source_bound_worker_brief_queue_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("worker_brief_queue_latest", ""),
                "worker_dispatch_ledger_wave_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("worker_dispatch_ledger_wave", ""),
                "worker_dispatch_ledger_activity_ref": source_frontier_workerbrief_bridge_payload.get(
                    "output_paths", {}
                ).get("worker_dispatch_ledger_activity", ""),
            },
        },
        "poll_refs": [str(state / "codex_s_live_backend_watch" / "latest.json")],
        "fan_in_refs": [
            durable_payload.get("fan_in_acceptance_ref"),
            durable_payload.get("artifact_acceptance_queue_ref"),
            allocation_payload.get("output_paths", {}).get("worker_brief_queue_latest", ""),
            source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                "worker_brief_queue_latest", ""
            ),
            pre_pass_payload.get("output_paths", {}).get("audit_fan_in_latest", ""),
        ],
        "evidence_refs": [
            str(state / "codex_s_main_execution_loop_tick" / "latest.json"),
            output["runtime_readback_zh"],
            allocation_payload.get("output_paths", {}).get("latest", ""),
            allocation_payload.get("output_paths", {}).get("readback_zh", ""),
            source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get("wave", ""),
            source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                "worker_dispatch_ledger_wave", ""
            ),
            source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                "worker_dispatch_ledger_activity", ""
            ),
            source_frontier_workerbrief_bridge_payload.get("output_paths", {}).get(
                "readback_zh", ""
            ),
            pre_pass_payload.get("output_paths", {}).get("latest", ""),
            pre_pass_payload.get("output_paths", {}).get("readback_zh", ""),
            str(state / "durable_parallel_wave_packet" / "latest.json"),
            str(state / "source_anchor_gap_continuation" / "latest.json"),
            str(state / "codex_s_live_backend_watch" / "latest.json"),
            str(
                (worker_dispatch_ledger_activity_ref or {}).get(
                    "ledger_temporal_activity_latest_ref", ""
                )
            ),
            source_frontier_surface.get("output_paths", {}).get("runtime_latest", ""),
            source_frontier_surface.get("output_paths", {}).get(
                "fan_in_acceptance_queue_latest", ""
            ),
            source_frontier_surface.get("output_paths", {}).get(
                "artifact_acceptance_queue_latest", ""
            ),
            source_frontier_surface.get("output_paths", {}).get(
                "next_frontier_machine_actions_latest", ""
            ),
            source_family_surface.get("output_paths", {}).get("runtime_latest", "")
            if isinstance(source_family_surface.get("output_paths"), dict)
            else "",
            source_family_surface.get("output_paths", {}).get("readback_zh", "")
            if isinstance(source_family_surface.get("output_paths"), dict)
            else "",
            external_mature_bridge_payload.get("output_paths", {}).get("wave", ""),
            external_mature_bridge_payload.get("output_paths", {}).get("source_ledger_wave", ""),
            external_mature_bridge_payload.get("output_paths", {}).get("claim_cards_wave", ""),
            external_mature_bridge_payload.get("output_paths", {}).get(
                "reflection_subagent_dispatch_wave", ""
            ),
            external_mature_bridge_payload.get("output_paths", {}).get(
                "reflection_worker_dispatch_ledger_wave", ""
            ),
            external_mature_bridge_payload.get("output_paths", {}).get(
                "strategy_candidate_wave", ""
            ),
        ],
        "allocation_plan": allocation_payload,
        "external_mature_strategy_mutation_bridge": external_mature_bridge_payload,
        "source_frontier_workerbrief_bridge": source_frontier_workerbrief_bridge_payload,
        "pre_pass_audit_loop": pre_pass_payload,
        "next_wave_decision": next_wave_decision,
        "legacy_5d33_transport_pattern": durable_payload.get("legacy_5d33_transport_pattern"),
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "phase1_data_chain_allowed": False,
        "positive_ev_claim_allowed": False,
        "output_paths": output,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    payload["evidence_refs"] = [ref for ref in payload["evidence_refs"] if ref]
    from services.agent_runtime.thin_glue_mainline_bridge import attach_thin_glue_bridge_evidence

    payload["thin_glue_mainline_bridge"] = attach_thin_glue_bridge_evidence(runtime)
    if write:
        write_json(Path(output["runtime_latest"]), payload)
        write_text(Path(output["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    lines = [
        "# Codex S Main Execution Loop Tick readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload['status']}`",
        f"- adoption_state: `{payload['adoption_state']}`",
        f"- next_wave_decision: `{payload['next_wave_decision']['decision']}`",
        f"- named_blocker: `{payload['next_wave_decision']['named_blocker']}`",
        "- stop_guard_layers: live_backend_watch_front_gate, source_anchor_gap_continuation",
        "- main_execution_loop: restore -> dispatch -> poll -> fan-in -> verify/evidence/readback -> recompute -> next_wave",
        f"- seed_lab_user_correction_surface_prepared: {payload['validation']['checks'].get('seed_lab_user_correction_runtime_surface_prepared')}",
        f"- source_frontier_fanin_acceptance_surface_prepared: {payload['validation']['checks'].get('source_frontier_fanin_acceptance_surface_prepared')}",
        f"- allocation_plan_prepared: {payload['validation']['checks'].get('allocation_plan_prepared')}",
        f"- allocation_plan_lane_classes: `{', '.join(payload.get('allocation_plan', {}).get('lane_classes', []) if isinstance(payload.get('allocation_plan'), dict) else [])}`",
        f"- allocation_plan_total_requested_width: `{payload.get('allocation_plan', {}).get('total_requested_width', '') if isinstance(payload.get('allocation_plan'), dict) else ''}`",
        f"- allocation_plan_fixed_20_or_50_used: `{payload.get('allocation_plan', {}).get('fixed_20_or_50_used', '') if isinstance(payload.get('allocation_plan'), dict) else ''}`",
        f"- source_frontier_workerbrief_bridge_prepared: {payload['validation']['checks'].get('source_frontier_workerbrief_bridge_prepared')}",
        f"- source_frontier_workerbrief_bridge_status: `{payload.get('source_frontier_workerbrief_bridge', {}).get('status', '') if isinstance(payload.get('source_frontier_workerbrief_bridge'), dict) else ''}`",
        f"- source_frontier_workerbrief_bridge_bindings: `{payload.get('source_frontier_workerbrief_bridge', {}).get('worker_brief_binding_count', '') if isinstance(payload.get('source_frontier_workerbrief_bridge'), dict) else ''}`",
        f"- pre_pass_audit_loop_prepared: {payload['validation']['checks'].get('pre_pass_audit_loop_prepared')}",
        f"- pre_pass_decision: `{payload.get('pre_pass_audit_loop', {}).get('audit_fan_in', {}).get('decision', '') if isinstance(payload.get('pre_pass_audit_loop'), dict) else ''}`",
        f"- pre_pass_repair_plan: `{payload.get('pre_pass_audit_loop', {}).get('repair_plan_ref', '') if isinstance(payload.get('pre_pass_audit_loop'), dict) else ''}`",
        "- source_frontier_fanin task: `wave3_20260702_absorption_slice_20260704` under parent `xinao_seed_cortex_phase0_20260701`; routing=`continue_same_task`.",
        "- actual dispatch refs include Codex subagents, DP sidecar modes, lane assignments, worker dispatch ledger ref.",
        "- This tick is a callable S machine entrypoint, not completion evidence and not the durable owner.",
        "- temporal_activity_scope_ref: `seed_cortex_temporal_main_execution_loop_tick_activity`；只有 temporal_activity_latest.json 里 runtime_entrypoint_invocation.runtime_enforced=true 时才代表该 scope 生效。",
    ]
    invocation = payload.get("runtime_entrypoint_invocation")
    if isinstance(invocation, dict) and invocation.get("runtime_enforced") is True:
        activity_ref = (
            payload.get("actual_dispatch_refs", {}).get("worker_dispatch_ledger_activity_ref", {})
            if isinstance(payload.get("actual_dispatch_refs"), dict)
            else {}
        )
        lines.extend(
            [
                f"- runtime_enforced_scope: `{invocation.get('runtime_enforced_scope')}`",
                "- runtime_enforced means this Temporal activity path invoked the tick; it is still not a controller or completion gate.",
                f"- worker_dispatch_ledger_activity_ref: `{activity_ref.get('ledger_temporal_activity_latest_ref', '')}`",
            ]
        )
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--ordinary-discussion", action="store_true")
    parser.add_argument("--explicit-user-stop", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        continuation_mode_active=not args.ordinary_discussion,
        explicit_user_stop=args.explicit_user_stop,
        codex_subagents=args.codex_subagent,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "next_wave_decision": payload["next_wave_decision"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
