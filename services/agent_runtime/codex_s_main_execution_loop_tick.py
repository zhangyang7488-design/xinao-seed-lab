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
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
SRC_ROOT = DEFAULT_REPO / "src"
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
    path = Path(__file__).resolve().parent / f"{module_name}.py"
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


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json"),
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
    durable_payload: dict[str, Any],
    worker_ledger_ref: dict[str, Any],
) -> dict[str, Any]:
    if live_payload.get("foreground_poll_required") is True:
        return {
            "decision": "poll_live_backend_watch",
            "named_blocker": "LIVE_BACKEND_POLL_REQUIRED",
            "continue_main_loop": True,
        }
    if source_payload.get("continue_dispatch_expected") is not True:
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
    service_ref = json_ref(state / "seed_lab_user_correction_runtime" / "service_entrypoint_latest.json")
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
        runtime_root
        / "state"
        / "scheduler_spawned_lane_evidence"
        / "current_parent_latest.json"
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
        "scheduler_spawned_lane_evidence_current_parent_ref": json_ref(
            current_parent_latest
        ),
        "scheduler_invocation_status": scheduler_payload.get("status"),
        "scheduler_invoked": scheduler_payload.get("scheduler_invoked") is True,
        "parent_dispatch_invoked": scheduler_payload.get("parent_dispatch_invoked") is True,
        "scheduler_spawned_lane_count": int(
            scheduler_payload.get("spawned_lane_count") or 0
        ),
        "current_parent_lane_evidence_state": lane_payload.get("lane_evidence_state"),
        "current_parent_lane_evidence_validation_passed": lane_validation.get("passed")
        is True,
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
    wave_id: str = "codex-s-main-execution-wave-20260702",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    live_module = load_sibling_module("codex_s_live_backend_watch")
    source_module = load_sibling_module("source_anchor_gap_continuation")
    durable_module = load_sibling_module("durable_parallel_wave_packet")
    worker_ledger_module = load_sibling_module("worker_dispatch_ledger")

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
    worker_ledger_payload = worker_ledger_module.build_worker_dispatch_ledger(
        repo_root=repo,
        runtime_root=runtime,
        wave_id=wave_id,
        task_id=WORK_ID,
        codex_subagents=codex_subagents or [],
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
        durable_payload=durable_payload,
        worker_ledger_ref=worker_ledger_ref,
    )
    output = output_paths(repo, runtime)
    checks = {
        "invoked_live_backend_watch": live_payload.get("schema_version")
        == "xinao.codex_s.live_backend_watch.v1",
        "invoked_source_anchor_gap_continuation": source_payload.get("schema_version")
        == "xinao.codex_s.source_anchor_gap_continuation.v1",
        "invoked_durable_parallel_wave_packet": durable_payload.get("schema_version")
        == "xinao.codex_s.durable_parallel_wave_packet.v1",
        "stop_guard_layers_are_not_main_loop": True,
        "main_loop_shape_preserved": MAIN_EXECUTION_LOOP == durable_payload.get("main_execution_loop"),
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
        "scheduler_current_parent_surface_prepared": (
            scheduler_surface.get("refs_ready_for_durable_packet") is True
            and scheduler_surface.get("scheduler_invoked") is True
            and scheduler_surface.get("parent_dispatch_invoked") is True
            and int(scheduler_surface.get("scheduler_spawned_lane_count") or 0) > 0
            and scheduler_surface.get("runtime_enforced") is False
            and scheduler_surface.get("default_runtime_scheduler_invoked") is False
            and scheduler_surface.get("not_execution_controller") is True
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
        "status": "main_execution_loop_tick_ready" if all(checks.values()) else "main_execution_loop_tick_blocked",
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
            "seed_lab_user_correction_runtime_surface": user_correction_surface,
            "scheduler_current_parent_surface": scheduler_surface,
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
            "worker_dispatch_ledger_activity_ref": dict(
                worker_dispatch_ledger_activity_ref or {}
            ),
            "worker_dispatch_ledger_entries": worker_ledger_payload.get("dispatch_entries", []),
        },
        "poll_refs": [str(state / "codex_s_live_backend_watch" / "latest.json")],
        "fan_in_refs": [
            durable_payload.get("fan_in_acceptance_ref"),
            durable_payload.get("artifact_acceptance_queue_ref"),
        ],
        "evidence_refs": [
            str(state / "codex_s_main_execution_loop_tick" / "latest.json"),
            output["runtime_readback_zh"],
            str(state / "durable_parallel_wave_packet" / "latest.json"),
            str(state / "source_anchor_gap_continuation" / "latest.json"),
            str(state / "codex_s_live_backend_watch" / "latest.json"),
            str(
                (worker_dispatch_ledger_activity_ref or {}).get(
                    "ledger_temporal_activity_latest_ref", ""
                )
            ),
        ],
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
        "- actual dispatch refs include Codex subagents, DP sidecar modes, lane assignments, worker dispatch ledger ref.",
        "- This tick is a callable S machine entrypoint, not completion evidence and not the durable owner.",
        "- temporal_activity_scope_ref: `seed_cortex_temporal_main_execution_loop_tick_activity`；只有 temporal_activity_latest.json 里 runtime_entrypoint_invocation.runtime_enforced=true 时才代表该 scope 生效。",
    ]
    invocation = payload.get("runtime_entrypoint_invocation")
    if isinstance(invocation, dict) and invocation.get("runtime_enforced") is True:
        activity_ref = (
            payload.get("actual_dispatch_refs", {})
            .get("worker_dispatch_ledger_activity_ref", {})
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
