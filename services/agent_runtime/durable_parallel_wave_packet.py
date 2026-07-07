from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.durable_parallel_wave_packet.v1"
SENTINEL = "SENTINEL:XINAO_DURABLE_PARALLEL_WAVE_PACKET_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]

MAIN_EXECUTION_LOOP = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
]

DP_MODE_COUNTS = {
    "draft": 0,
    "eval": 4,
    "contradiction": 4,
    "extraction": 4,
    "audit": 2,
    "search": 4,
    "citation_verify": 0,
    "provider_probe": 2,
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
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


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
            "continue_dispatch_expected": payload.get("continue_dispatch_expected"),
            "foreground_poll_required": payload.get("foreground_poll_required"),
            "runtime_enforced": payload.get("runtime_enforced")
            or runtime_invocation.get("runtime_enforced"),
            "runtime_enforced_scope": payload.get("runtime_enforced_scope")
            or runtime_invocation.get("runtime_enforced_scope"),
            "not_execution_controller": payload.get("not_execution_controller"),
            "not_completion_decision": payload.get("not_completion_decision"),
            "not_user_completion": payload.get("not_user_completion"),
        }
    )
    return ref


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(runtime / "state" / "durable_parallel_wave_packet" / "latest.json"),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "durable_parallel_wave_packet_20260702.md"
        ),
        "schema": str(
            repo / "contracts" / "schemas" / "codex_s_durable_parallel_wave_packet.v1.json"
        ),
        "writer": str(repo / "services" / "agent_runtime" / "durable_parallel_wave_packet.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_durable_parallel_wave_packet.py"),
        "verifier": str(repo / "scripts" / "verify_durable_parallel_wave_packet.ps1"),
    }


def runtime_refs(runtime: Path) -> dict[str, dict[str, Any]]:
    state = runtime / "state"
    return {
        "source_anchor_gap_continuation": json_ref(
            state / "source_anchor_gap_continuation" / "latest.json"
        ),
        "codex_s_live_backend_watch": json_ref(
            state / "codex_s_live_backend_watch" / "latest.json"
        ),
        "default_hot_path_intake": json_ref(state / "default_hot_path_intake" / "latest.json"),
        "parallel_dispatch_plan": json_ref(state / "parallel_dispatch_plan" / "latest.json"),
        "parallel_fan_in_acceptance": json_ref(
            state / "parallel_fan_in_acceptance" / "latest.json"
        ),
        "fan_in_acceptance_queue": json_ref(state / "fan_in_acceptance_queue" / "latest.json"),
        "claim_card_staging_queue": json_ref(state / "claim_card_staging_queue" / "latest.json"),
        "source_frontier_fanin_acceptance": json_ref(
            state / "source_frontier_fanin_acceptance" / "latest.json"
        ),
        "next_frontier_machine_actions": json_ref(
            state / "next_frontier_machine_actions" / "latest.json"
        ),
        "frontier_portfolio_snapshot": json_ref(
            state / "frontier_portfolio_snapshot" / "latest.json"
        ),
        "artifact_acceptance_queue": json_ref(state / "artifact_acceptance_queue" / "latest.json"),
        "temporal_worker_dispatch_ledger_activity": json_ref(
            state / "worker_dispatch_ledger" / "temporal_activity_latest.json"
        ),
        "temporal_main_execution_loop_tick_activity": json_ref(
            state / "codex_s_main_execution_loop_tick" / "temporal_activity_latest.json"
        ),
        "seed_lab_user_correction_runtime_service": json_ref(
            state / "seed_lab_user_correction_runtime" / "service_entrypoint_latest.json"
        ),
        "seed_lab_correction_intake": json_ref(
            state / "seed_lab_correction_intake" / "latest.json"
        ),
        "seed_lab_experiment_review_view": json_ref(
            state / "seed_lab_experiment_review_view" / "latest.json"
        ),
        "seed_lab_replay_court": json_ref(state / "seed_lab_replay_court" / "latest.json"),
        "scheduler_invocation_packet": json_ref(
            state / "scheduler_invocation_packet" / "latest.json"
        ),
        "scheduler_spawned_lane_evidence_current_parent": json_ref(
            state / "scheduler_spawned_lane_evidence" / "current_parent_latest.json"
        ),
        "scheduler_spawned_lane_evidence_current_wave": json_ref(
            state / "scheduler_spawned_lane_evidence" / "current_wave_latest.json"
        ),
        "scheduler_spawned_lane_evidence_activity_scoped": json_ref(
            state / "scheduler_spawned_lane_evidence" / "activity_scoped_latest.json"
        ),
        "dp_sidecar_execution_port_runner": json_ref(
            state / "dp_sidecar_execution_port" / "latest.json"
        ),
        "dp_sidecar_execution_provider": json_ref(
            state / "dp_sidecar_execution_provider" / "latest.json"
        ),
        "dp_sidecar_execution_provider_manifest": json_ref(
            runtime
            / "capabilities"
            / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port"
            / "manifest.json"
        ),
    }


def load_dispatch_assignments(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    assignments = payload.get("lane_assignments")
    return assignments if isinstance(assignments, list) else []


def load_worker_dispatch_entries(runtime: Path) -> list[dict[str, Any]]:
    for path in [
        runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json",
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
    ]:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        entries = payload.get("dispatch_entries")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def load_json_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_subagent(value: str) -> dict[str, str]:
    if ":" in value:
        agent_id, role = value.split(":", 1)
    else:
        agent_id, role = value, "codex_subagent"
    return {"agent_id": agent_id.strip(), "role": role.strip() or "codex_subagent"}


def derived_worker_dispatch_refs(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        mode = str(entry.get("mode") or "").strip()
        provider = str(entry.get("provider") or "").strip()
        poll_status = str(entry.get("poll_status") or "").strip()
        agent_id = str(entry.get("agent_id") or "").strip()
        entry_id = str(entry.get("entry_id") or "").strip()
        if mode not in {"worker", "subagent"}:
            continue
        if poll_status in {"planned_not_spawned", "not_applicable_not_spawned"}:
            continue
        if not agent_id:
            continue
        key = entry_id or f"{provider}:{agent_id}:{mode}"
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "agent_id": agent_id,
                "role": f"worker_dispatch_ledger_{mode}",
                "source": "worker_dispatch_ledger",
                "source_entry_id": entry_id,
                "provider": provider,
                "mode": mode,
                "poll_status": poll_status,
                "derived_from_worker_dispatch_ledger": True,
            }
        )
    return refs


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    codex_subagents: list[str] | None = None,
    wave_id: str = "codex-s-main-execution-wave-20260702",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    refs = runtime_refs(runtime)
    assignments = load_dispatch_assignments(
        runtime / "state" / "parallel_dispatch_plan" / "latest.json"
    )
    worker_dispatch_entries = load_worker_dispatch_entries(runtime)
    scheduler_invocation_payload = load_json_payload(
        runtime / "state" / "scheduler_invocation_packet" / "latest.json"
    )
    scheduler_current_parent_payload = load_json_payload(
        runtime / "state" / "scheduler_spawned_lane_evidence" / "current_parent_latest.json"
    )
    scheduler_current_wave_payload = load_json_payload(
        runtime / "state" / "scheduler_spawned_lane_evidence" / "current_wave_latest.json"
    )
    scheduler_activity_scoped_payload = load_json_payload(
        runtime / "state" / "scheduler_spawned_lane_evidence" / "activity_scoped_latest.json"
    )
    explicit_subagent_records = [
        {**parse_subagent(item), "source": "explicit_codex_subagent_arg"}
        for item in (codex_subagents or [])
        if item.strip()
    ]
    derived_worker_records = (
        [] if explicit_subagent_records else derived_worker_dispatch_refs(worker_dispatch_entries)
    )
    dispatch_ref_records = explicit_subagent_records or derived_worker_records
    explicit_subagent_refs_provided = bool(explicit_subagent_records)
    paths = output_paths(repo, runtime)
    source_frontier_ready = (
        refs["source_frontier_fanin_acceptance"].get("exists") is True
        and refs["source_frontier_fanin_acceptance"].get("json_valid") is True
        and refs["source_frontier_fanin_acceptance"].get("validation_passed") is True
    )
    source_continue = (
        refs["source_anchor_gap_continuation"].get("continue_dispatch_expected") is True
        or source_frontier_ready
    )
    live_poll = refs["codex_s_live_backend_watch"].get("foreground_poll_required") is True
    live_watch_stop_guard_only = (
        refs["codex_s_live_backend_watch"].get("not_execution_controller") is True
        and refs["codex_s_live_backend_watch"].get("not_completion_decision") is True
        and refs["codex_s_live_backend_watch"].get("not_user_completion") is True
    )
    live_poll_blocks_dispatch = live_poll and not (
        source_frontier_ready and live_watch_stop_guard_only
    )
    required_refs_present = all(
        refs[name].get("exists") is True and refs[name].get("json_valid") is True
        for name in [
            "source_anchor_gap_continuation",
            "codex_s_live_backend_watch",
            "default_hot_path_intake",
            "parallel_dispatch_plan",
            "parallel_fan_in_acceptance",
            "fan_in_acceptance_queue",
            "source_frontier_fanin_acceptance",
            "next_frontier_machine_actions",
            "artifact_acceptance_queue",
            "temporal_worker_dispatch_ledger_activity",
            "temporal_main_execution_loop_tick_activity",
            "seed_lab_user_correction_runtime_service",
            "seed_lab_correction_intake",
            "seed_lab_experiment_review_view",
            "seed_lab_replay_court",
            "scheduler_invocation_packet",
            "scheduler_spawned_lane_evidence_current_parent",
        ]
    )
    scheduler_current_parent_refs_bound = (
        refs["scheduler_invocation_packet"].get("exists") is True
        and refs["scheduler_invocation_packet"].get("json_valid") is True
        and scheduler_invocation_payload.get("status") == "spawned_lane_refs_recorded"
        and scheduler_invocation_payload.get("scheduler_invoked") is True
        and scheduler_invocation_payload.get("parent_dispatch_invoked") is True
        and scheduler_invocation_payload.get("default_runtime_scheduler_invoked") is False
        and scheduler_invocation_payload.get("runtime_enforced") is False
        and refs["scheduler_spawned_lane_evidence_current_parent"].get("exists") is True
        and refs["scheduler_spawned_lane_evidence_current_parent"].get("json_valid") is True
        and scheduler_current_parent_payload.get("lane_evidence_state")
        == "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
        and scheduler_current_parent_payload.get("scheduler_invoked") is True
        and scheduler_current_parent_payload.get("parent_dispatch_invoked") is True
        and scheduler_current_parent_payload.get("default_runtime_scheduler_invoked") is False
        and scheduler_current_parent_payload.get("runtime_enforced") is False
        and int(scheduler_current_parent_payload.get("scheduler_spawned_lane_count") or 0) > 0
    )
    dispatch_allowed = source_continue and not live_poll_blocks_dispatch and required_refs_present
    checks = {
        "source_anchor_allows_dispatch": source_continue,
        "live_backend_does_not_require_poll": not live_poll_blocks_dispatch,
        "live_backend_poll_is_stop_guard_only": (not live_poll) or live_watch_stop_guard_only,
        "live_backend_poll_does_not_block_source_frontier": not live_poll_blocks_dispatch,
        "required_refs_present": required_refs_present,
        "main_loop_is_not_stop_guard_layers": True,
        "legacy_5d33_transport_only": True,
        "old_authority_disallowed": True,
        "dp_mode_total_is_20": sum(DP_MODE_COUNTS.values()) == 20,
        "artifact_acceptance_ref_present": refs["artifact_acceptance_queue"].get("exists") is True,
        "temporal_worker_dispatch_ledger_activity_ref_present": refs[
            "temporal_worker_dispatch_ledger_activity"
        ].get("exists")
        is True,
        "temporal_main_execution_loop_tick_activity_ref_present": refs[
            "temporal_main_execution_loop_tick_activity"
        ].get("exists")
        is True,
        "temporal_activity_refs_are_not_execution_controllers": all(
            refs[name].get("not_execution_controller") is True
            for name in [
                "temporal_worker_dispatch_ledger_activity",
                "temporal_main_execution_loop_tick_activity",
            ]
        ),
        "user_correction_runtime_refs_bound": (
            refs["seed_lab_user_correction_runtime_service"].get("exists") is True
            and refs["seed_lab_user_correction_runtime_service"].get("json_valid") is True
            and refs["seed_lab_user_correction_runtime_service"].get("validation_passed") is True
            and refs["seed_lab_correction_intake"].get("exists") is True
            and refs["seed_lab_experiment_review_view"].get("exists") is True
            and refs["seed_lab_replay_court"].get("exists") is True
        ),
        "user_correction_runtime_not_enforced": (
            refs["seed_lab_user_correction_runtime_service"].get("runtime_enforced") is not True
            and refs["seed_lab_user_correction_runtime_service"].get("not_execution_controller")
            is True
        ),
        "scheduler_invocation_packet_ref_present": (
            refs["scheduler_invocation_packet"].get("exists") is True
            and refs["scheduler_invocation_packet"].get("json_valid") is True
        ),
        "scheduler_spawned_lane_current_parent_ref_present": (
            refs["scheduler_spawned_lane_evidence_current_parent"].get("exists") is True
            and refs["scheduler_spawned_lane_evidence_current_parent"].get("json_valid") is True
        ),
        "scheduler_current_parent_lane_refs_bound_no_overclaim": (
            scheduler_current_parent_refs_bound
        ),
        "scheduler_refs_not_runtime_enforced": (
            scheduler_invocation_payload.get("runtime_enforced") is False
            and scheduler_invocation_payload.get("default_runtime_scheduler_invoked") is False
            and scheduler_current_parent_payload.get("runtime_enforced") is False
            and scheduler_current_parent_payload.get("default_runtime_scheduler_invoked") is False
        ),
        "dp_sidecar_execution_callable_refs_bound": (
            refs["dp_sidecar_execution_port_runner"].get("exists") is True
            and refs["dp_sidecar_execution_port_runner"].get("json_valid") is True
            and refs["dp_sidecar_execution_port_runner"].get("not_execution_controller") is True
            and refs["dp_sidecar_execution_provider"].get("exists") is True
            and refs["dp_sidecar_execution_provider"].get("json_valid") is True
            and refs["dp_sidecar_execution_provider"].get("not_execution_controller") is True
            and refs["dp_sidecar_execution_provider_manifest"].get("exists") is True
            and refs["dp_sidecar_execution_provider_manifest"].get("json_valid") is True
            and refs["dp_sidecar_execution_provider_manifest"].get("not_execution_controller")
            is True
        ),
        "actual_dispatch_refs_bound": (
            refs["parallel_dispatch_plan"].get("exists") is True
            and refs["temporal_worker_dispatch_ledger_activity"].get("exists") is True
            and refs["temporal_main_execution_loop_tick_activity"].get("exists") is True
            and len(dispatch_ref_records) > 0
            and scheduler_current_parent_refs_bound
            and refs["dp_sidecar_execution_port_runner"].get("exists") is True
            and refs["dp_sidecar_execution_provider"].get("exists") is True
        ),
        "actual_codex_subagent_or_worker_refs_present": len(dispatch_ref_records) > 0,
        "poll_refs_bound": refs["codex_s_live_backend_watch"].get("exists") is True,
        "fan_in_refs_bound": (
            refs["parallel_fan_in_acceptance"].get("exists") is True
            and refs["fan_in_acceptance_queue"].get("exists") is True
            and refs["artifact_acceptance_queue"].get("exists") is True
        ),
        "source_frontier_fanin_refs_bound": (
            refs["source_frontier_fanin_acceptance"].get("exists") is True
            and refs["source_frontier_fanin_acceptance"].get("json_valid") is True
            and refs["source_frontier_fanin_acceptance"].get("validation_passed") is True
            and refs["fan_in_acceptance_queue"].get("exists") is True
            and refs["next_frontier_machine_actions"].get("exists") is True
        ),
        "evidence_and_readback_refs_bound": bool(paths["runtime_latest"])
        and bool(paths["runtime_readback_zh"]),
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "durable_parallel_wave_packet_ready"
        if dispatch_allowed
        else "durable_parallel_wave_packet_blocked",
        "generated_at": now_iso(),
        "adoption_state": "verifier_ready_but_not_hooked",
        "source_anchor_ref": refs["source_anchor_gap_continuation"]["path"],
        "live_backend_watch_ref": refs["codex_s_live_backend_watch"]["path"],
        "dispatch_plan_ref": refs["parallel_dispatch_plan"]["path"],
        "fan_in_acceptance_ref": refs["parallel_fan_in_acceptance"]["path"],
        "artifact_acceptance_queue_ref": refs["artifact_acceptance_queue"]["path"],
        "runtime_refs": refs,
        "temporal_activity_refs": {
            "worker_dispatch_ledger_activity": refs["temporal_worker_dispatch_ledger_activity"],
            "main_execution_loop_tick_activity": refs["temporal_main_execution_loop_tick_activity"],
            "activity_refs_are_evidence_only": True,
            "activity_refs_are_not_stop_guard_layers": True,
            "activity_refs_are_not_completion_gates": True,
            "activity_refs_are_not_execution_controllers": True,
        },
        "scheduler_invocation_refs": {
            "scheduler_invocation_packet_latest": refs["scheduler_invocation_packet"],
            "scheduler_spawned_lane_evidence_current_parent": refs[
                "scheduler_spawned_lane_evidence_current_parent"
            ],
            "scheduler_spawned_lane_evidence_current_wave": refs[
                "scheduler_spawned_lane_evidence_current_wave"
            ],
            "scheduler_spawned_lane_evidence_activity_scoped": refs[
                "scheduler_spawned_lane_evidence_activity_scoped"
            ],
            "scheduler_invocation_status": scheduler_invocation_payload.get("status"),
            "scheduler_invoked": scheduler_invocation_payload.get("scheduler_invoked"),
            "parent_dispatch_invoked": scheduler_invocation_payload.get("parent_dispatch_invoked"),
            "current_parent_lane_evidence_state": scheduler_current_parent_payload.get(
                "lane_evidence_state"
            ),
            "current_parent_scheduler_spawned_lane_count": int(
                scheduler_current_parent_payload.get("scheduler_spawned_lane_count") or 0
            ),
            "current_wave_lane_evidence_state": scheduler_current_wave_payload.get(
                "lane_evidence_state"
            ),
            "activity_scoped_lane_evidence_state": scheduler_activity_scoped_payload.get(
                "lane_evidence_state"
            ),
            "default_runtime_scheduler_invoked": False,
            "runtime_enforced": False,
            "trigger_installed": False,
            "refs_are_evidence_only": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
        },
        "actual_dispatch_refs": {
            "parallel_dispatch_plan_ref": refs["parallel_dispatch_plan"],
            "lane_assignments": assignments,
            "codex_subagents": dispatch_ref_records,
            "codex_subagent_count": len(dispatch_ref_records),
            "scheduler_invocation_packet_ref": refs["scheduler_invocation_packet"],
            "scheduler_spawned_lane_evidence_current_parent_ref": refs[
                "scheduler_spawned_lane_evidence_current_parent"
            ],
            "scheduler_current_parent_lane_evidence_state": scheduler_current_parent_payload.get(
                "lane_evidence_state"
            ),
            "scheduler_current_parent_spawned_lane_count": int(
                scheduler_current_parent_payload.get("scheduler_spawned_lane_count") or 0
            ),
            "scheduler_current_parent_refs_bound": scheduler_current_parent_refs_bound,
            "dp_sidecar_execution_port_runner_ref": refs["dp_sidecar_execution_port_runner"],
            "dp_sidecar_execution_provider_ref": refs["dp_sidecar_execution_provider"],
            "dp_sidecar_execution_provider_manifest_ref": refs[
                "dp_sidecar_execution_provider_manifest"
            ],
            "dp_sidecar_execution_callable_entrypoint_bound": (
                refs["dp_sidecar_execution_port_runner"].get("exists") is True
                and refs["dp_sidecar_execution_provider"].get("exists") is True
            ),
            "explicit_codex_subagent_refs_provided": explicit_subagent_refs_provided,
            "derived_codex_subagent_refs_from_worker_dispatch_ledger": bool(derived_worker_records),
            "worker_dispatch_ledger_actual_entry_ids": [
                str(record.get("source_entry_id") or "")
                for record in derived_worker_records
                if str(record.get("source_entry_id") or "").strip()
            ],
            "worker_dispatch_ledger_entries_seen": len(worker_dispatch_entries),
            "worker_dispatch_ledger_activity_ref": refs["temporal_worker_dispatch_ledger_activity"],
            "main_execution_loop_tick_activity_ref": refs[
                "temporal_main_execution_loop_tick_activity"
            ],
            "dp_sidecar_execution_port": "dp_sidecar_execution_port",
            "spawned_by_this_runner": False,
            "refs_are_evidence_only": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
        },
        "poll_refs": {
            "live_backend_watch_ref": refs["codex_s_live_backend_watch"],
            "poll_policy": "poll_live_backend_watch_first",
            "foreground_poll_required": live_poll,
            "poll_stop_guard_only": live_watch_stop_guard_only,
            "poll_blocks_dispatch": live_poll_blocks_dispatch,
            "source_frontier_ready": source_frontier_ready,
            "worker_jsonl_non_terminal_blocks_stop": True,
            "output_growth_blocks_stop": True,
        },
        "fan_in_refs": {
            "parallel_fan_in_acceptance_ref": refs["parallel_fan_in_acceptance"],
            "fan_in_acceptance_queue_ref": refs["fan_in_acceptance_queue"],
            "source_frontier_fanin_acceptance_ref": refs["source_frontier_fanin_acceptance"],
            "claim_card_staging_queue_ref": refs["claim_card_staging_queue"],
            "artifact_acceptance_queue_ref": refs["artifact_acceptance_queue"],
            "next_frontier_machine_actions_ref": refs["next_frontier_machine_actions"],
            "frontier_portfolio_snapshot_ref": refs["frontier_portfolio_snapshot"],
            "fan_in_required_before_fact_promotion": True,
            "artifact_acceptance_queue_required": True,
            "direct_fact_promotion_allowed": False,
            "fan_in_acceptance_queue_default_heart": True,
            "fan_in_acceptance_queue_not_bypass_island": True,
        },
        "user_correction_runtime_refs": {
            "service_entrypoint_ref": refs["seed_lab_user_correction_runtime_service"],
            "correction_intake_ref": refs["seed_lab_correction_intake"],
            "experiment_review_view_ref": refs["seed_lab_experiment_review_view"],
            "replay_court_ref": refs["seed_lab_replay_court"],
            "explicit_service_api_candidate": True,
            "runtime_enforced": False,
            "trigger_installed": False,
            "memory_promotion_allowed": False,
            "policy_promotion_allowed": False,
            "completion_claim_allowed": False,
            "refs_are_evidence_only": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
        },
        "evidence_refs": {
            "runtime_latest": paths["runtime_latest"],
            "schema": paths["schema"],
            "writer": paths["writer"],
            "tests": paths["tests"],
            "verifier": paths["verifier"],
            "worker_dispatch_ledger_activity_latest": refs[
                "temporal_worker_dispatch_ledger_activity"
            ]["path"],
            "main_execution_loop_tick_activity_latest": refs[
                "temporal_main_execution_loop_tick_activity"
            ]["path"],
            "seed_lab_user_correction_runtime_service_latest": refs[
                "seed_lab_user_correction_runtime_service"
            ]["path"],
            "seed_lab_correction_intake_latest": refs["seed_lab_correction_intake"]["path"],
            "seed_lab_experiment_review_view_latest": refs["seed_lab_experiment_review_view"][
                "path"
            ],
            "seed_lab_replay_court_latest": refs["seed_lab_replay_court"]["path"],
            "scheduler_invocation_packet_latest": refs["scheduler_invocation_packet"]["path"],
            "scheduler_spawned_lane_evidence_current_parent_latest": refs[
                "scheduler_spawned_lane_evidence_current_parent"
            ]["path"],
            "scheduler_spawned_lane_evidence_current_wave_latest": refs[
                "scheduler_spawned_lane_evidence_current_wave"
            ]["path"],
            "scheduler_spawned_lane_evidence_activity_scoped_latest": refs[
                "scheduler_spawned_lane_evidence_activity_scoped"
            ]["path"],
            "source_frontier_fanin_acceptance_latest": refs["source_frontier_fanin_acceptance"][
                "path"
            ],
            "fan_in_acceptance_queue_latest": refs["fan_in_acceptance_queue"]["path"],
            "next_frontier_machine_actions_latest": refs["next_frontier_machine_actions"]["path"],
            "dp_sidecar_execution_port_runner_latest": refs["dp_sidecar_execution_port_runner"][
                "path"
            ],
            "dp_sidecar_execution_provider_latest": refs["dp_sidecar_execution_provider"]["path"],
            "dp_sidecar_execution_provider_manifest": refs[
                "dp_sidecar_execution_provider_manifest"
            ]["path"],
        },
        "readback_refs": {
            "runtime_readback_zh": paths["runtime_readback_zh"],
            "seed_lab_user_correction_runtime_service_readback": str(
                runtime
                / "readback"
                / "zh"
                / "seed_lab_user_correction_runtime_service_entrypoint_20260702.md"
            ),
            "human_visible_readback_required": True,
        },
        "service_entrypoint": {
            "caller": "services.agent_runtime.durable_parallel_wave_packet.build",
            "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "temporal_enforced": False,
            "stop_hook_controller": False,
            "main_execution_loop_packet_entrypoint": True,
            "missing_to_runtime_enforced_cn": (
                "还需要默认主循环或 Temporal/LangGraph runtime 在每波 dispatch 前调用，"
                "并由 focused verifier 证明触发。"
            ),
        },
        "api_surface": {
            "fastapi_route": "POST /runtime/durable-parallel-wave-packet",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "cli_command": "python -m xinao_seedlab.cli.__main__ durable-parallel-wave-packet",
        },
        "stop_guard_layers": [
            "live_backend_watch_front_gate",
            "source_anchor_gap_continuation",
        ],
        "stop_guard_layers_are_main_execution_loop": False,
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "current_loop_step": "dispatch" if dispatch_allowed else "restore_or_poll",
        "continue_dispatch_expected": dispatch_allowed,
        "dispatch_blocker": ""
        if dispatch_allowed
        else "SOURCE_ANCHOR_OR_LIVE_BACKEND_OR_RUNTIME_REF_BLOCKED",
        "lane_assignments": assignments,
        "codex_subagent_dispatch": {
            "recorded_subagent_count": len(explicit_subagent_records),
            "subagents": explicit_subagent_records,
            "spawned_by_this_runner": False,
            "spawn_tool": "multi_agent_v1.spawn_agent",
            "worker_refs_may_bind_actual_dispatch_when_no_explicit_subagents": True,
        },
        "dp_sidecar_execution": {
            "port_id": "dp_sidecar_execution_port",
            "default_lane_count": 20,
            "mode_counts": DP_MODE_COUNTS,
            "dp_search_is_mode_not_port_definition": True,
            "runner_latest_ref": refs["dp_sidecar_execution_port_runner"],
            "provider_latest_ref": refs["dp_sidecar_execution_provider"],
            "provider_manifest_ref": refs["dp_sidecar_execution_provider_manifest"],
            "callable_entrypoint_bound": (
                refs["dp_sidecar_execution_port_runner"].get("exists") is True
                and refs["dp_sidecar_execution_provider"].get("exists") is True
            ),
            "outputs_require_fan_in_and_artifact_acceptance": True,
        },
        "poll_policy": {
            "poll_live_backend_watch_first": True,
            "worker_jsonl_non_terminal_blocks_stop": True,
            "output_growth_blocks_stop": True,
        },
        "fan_in_policy": {
            "fan_in_required_before_fact_promotion": True,
            "artifact_acceptance_queue_required": True,
            "direct_fact_promotion_allowed": False,
            "source_frontier_fanin_acceptance_required": True,
            "fan_in_acceptance_queue_is_default_heart": True,
            "fan_in_acceptance_queue_not_bypass_island": True,
        },
        "legacy_5d33_transport_pattern": {
            "task_scoped_durable_owner_pattern_allowed": True,
            "worker_jsonl_and_result_wait_pattern_allowed": True,
            "old_5d33_owner_allowed": False,
            "old_pass_allowed": False,
            "old_latest_json_authority_allowed": False,
            "old_completion_gate_allowed": False,
        },
        "output_paths": paths,
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "phase1_data_chain_allowed": False,
        "positive_ev_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(payload["output_paths"]["runtime_latest"]), payload)
        write_text(Path(payload["output_paths"]["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Codex S Durable Parallel Wave Packet readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload['status']}`",
            f"- adoption_state: `{payload['adoption_state']}`",
            f"- continue_dispatch_expected: {payload['continue_dispatch_expected']}",
            f"- codex_subagents_recorded: {payload['codex_subagent_dispatch']['recorded_subagent_count']}",
            f"- actual_dispatch_worker_or_subagent_refs: {payload['actual_dispatch_refs']['codex_subagent_count']}",
            f"- actual_refs_derived_from_worker_ledger: {payload['actual_dispatch_refs'].get('derived_codex_subagent_refs_from_worker_dispatch_ledger')}",
            f"- scheduler_invocation_packet_ref_bound: {payload['validation']['checks']['scheduler_invocation_packet_ref_present']}",
            f"- scheduler_current_parent_lane_refs_bound: {payload['validation']['checks']['scheduler_current_parent_lane_refs_bound_no_overclaim']}",
            f"- scheduler_current_parent_spawned_lane_count: {payload['scheduler_invocation_refs']['current_parent_scheduler_spawned_lane_count']}",
            f"- scheduler_refs_runtime_enforced: {payload['scheduler_invocation_refs']['runtime_enforced']}",
            f"- dp_sidecar_execution_callable_refs_bound: {payload['validation']['checks']['dp_sidecar_execution_callable_refs_bound']}",
            f"- temporal_activity_refs_bound: {payload['validation']['checks']['temporal_worker_dispatch_ledger_activity_ref_present'] and payload['validation']['checks']['temporal_main_execution_loop_tick_activity_ref_present']}",
            f"- actual_dispatch_refs_bound: {payload['validation']['checks']['actual_dispatch_refs_bound']}",
            f"- poll_refs_bound: {payload['validation']['checks']['poll_refs_bound']}",
            f"- foreground_poll_required: {payload['poll_refs']['foreground_poll_required']}",
            f"- poll_stop_guard_only: {payload['poll_refs']['poll_stop_guard_only']}",
            f"- poll_blocks_dispatch: {payload['poll_refs']['poll_blocks_dispatch']}",
            f"- fan_in_refs_bound: {payload['validation']['checks']['fan_in_refs_bound']}",
            f"- source_frontier_fanin_refs_bound: {payload['validation']['checks']['source_frontier_fanin_refs_bound']}",
            f"- user_correction_runtime_refs_bound: {payload['validation']['checks']['user_correction_runtime_refs_bound']}",
            f"- user_correction_runtime_enforced: {payload['user_correction_runtime_refs']['runtime_enforced']}",
            f"- evidence_and_readback_refs_bound: {payload['validation']['checks']['evidence_and_readback_refs_bound']}",
            f"- api_cli_adoption_state: {payload['service_entrypoint']['api_cli_adoption_state']}",
            "- 这是一拍 S 主执行循环事务包，不是 Stop guard，也不是完成声明。",
            "- 主循环：restore -> dispatch -> poll -> fan-in -> verify/evidence/readback -> recompute -> next_wave。",
            "- source_frontier_fanin_refs 绑定切片 task_id=wave3_20260702_absorption_slice_20260704，parent_task_id=xinao_seed_cortex_phase0_20260701，FanInAcceptanceQueue 是默认心脏。",
            "- actual_dispatch_refs / poll_refs / fan_in_refs / evidence_refs / readback_refs 是本 packet 的机器锚点。",
            "- scheduler_invocation_refs 只证明当前父窗口 actual lane refs 已被 durable packet 看见；不是默认 scheduler runtime 安装。",
            "- user_correction_runtime_refs 指向 CorrectionIntake / ExperimentReviewView / ReplayCourt 的 explicit service/API candidate；不是 runtime_enforced。",
            "- Temporal activity refs 只是 worker ledger/main tick 的 activity-level runtime evidence；不是 Stop hook、controller 或 completion gate。",
            "- 5d33 只能复用 durable transport pattern；旧 owner/PASS/latest/completion gate 禁止成为 S 权威。",
            "",
            SENTINEL,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        codex_subagents=args.codex_subagent,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "continue_dispatch_expected": payload["continue_dispatch_expected"],
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
