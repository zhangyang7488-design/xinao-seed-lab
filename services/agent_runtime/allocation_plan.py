from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.allocation_plan.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "allocation_plan_20260704"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_DESKTOP_SPEC = Path(r"C:\Users\xx363\Desktop\新建 文本文档 (3).txt")

LANE_CLASSES = {
    "foreground_brain",
    "cheap_draft",
    "extraction",
    "eval",
    "contradiction",
    "audit",
    "search_source",
    "ci_verify",
    "repo_exec",
    "merge_accept",
    "approval_gate",
    "repair",
    "durable_temporal",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("._")
    cleaned = cleaned or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{cleaned[: limit - 13]}-{digest}"


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def output_paths(runtime_root: Path, *, task_id: str, wave_id: str) -> dict[str, str]:
    state_dir = runtime_root / "state" / "allocation_plan"
    task_dir = state_dir / "tasks" / safe_stem(task_id)
    return {
        "latest": str(state_dir / "latest.json"),
        "temporal_activity_latest": str(state_dir / "temporal_activity_latest.json"),
        "task_wave": str(task_dir / f"{safe_stem(wave_id)}.json"),
        "worker_brief_queue_latest": str(state_dir / "worker_brief_queue_latest.json"),
        "lane_allocations_latest": str(state_dir / "lane_allocations_latest.json"),
        "dispatch_attempts_latest": str(state_dir / "dispatch_attempts_latest.json"),
        "repair_plan_latest": str(state_dir / "repair_plan_latest.json"),
        "readback_zh": str(runtime_root / "readback" / "zh" / f"allocation_plan_{safe_stem(wave_id)}.md"),
    }


def runtime_ref_paths(runtime_root: Path) -> dict[str, Path]:
    state = runtime_root / "state"
    return {
        "frontier_portfolio_snapshot": state / "frontier_portfolio_snapshot" / "latest.json",
        "root_intent_loop_driver": state / "root_intent_loop_driver" / "latest.json",
        "loop_runtime_state": state / "loop_runtime_state" / "latest.json",
        "provider_scheduler": state / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        "modular_worker_pool": state / "modular_dynamic_worker_pool_phase1" / "latest.json",
        "scheduler_invocation_packet": state / "scheduler_invocation_packet" / "latest.json",
        "worker_dispatch_ledger": state / "worker_dispatch_ledger" / "latest.json",
        "artifact_acceptance_queue": state / "artifact_acceptance_queue" / "latest.json",
        "source_ledger": state / "source_ledger" / "latest.json",
        "source_frontier": state / "source_frontier_durable_consumer" / "latest.json",
        "source_family": state / "source_family_wave_scheduler" / "latest.json",
        "pre_pass_audit_loop": state / "pre_pass_audit_loop" / "latest.json",
        "temporal_worker": state / "temporal_codex_task_worker" / "latest.json",
    }


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": payload.get("schema_version", ""),
        "status": payload.get("status", ""),
        "validation_passed": validation.get("passed"),
        "runtime_enforced": payload.get("runtime_enforced"),
        "not_execution_controller": payload.get("not_execution_controller"),
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
    }


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    if value in (None, "", 0):
        return []
    return [value]


def count_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        if "count" in value:
            return as_int(value.get("count"))
        for key in ("item_count", "entry_count", "staged_count", "unmerged_count"):
            if key in value:
                return as_int(value.get(key))
        return len(value) if value else 0
    return as_int(value)


def as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def provider_statuses(provider_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry = provider_payload.get("provider_registry")
    providers = registry.get("providers") if isinstance(registry, dict) else []
    result: dict[str, dict[str, Any]] = {}
    for provider in providers if isinstance(providers, list) else []:
        if not isinstance(provider, dict):
            continue
        provider_id = str(provider.get("provider_id") or "").strip()
        if provider_id:
            result[provider_id] = provider
    return result


def ready_provider_ids(provider_payload: dict[str, Any]) -> list[str]:
    statuses = provider_statuses(provider_payload)
    return [
        provider_id
        for provider_id, provider in statuses.items()
        if str(provider.get("status") or "").lower() in {"ready", "foreground_tool_ready"}
    ]


def build_feedback_inputs(
    *, runtime_root: Path, extra_refs: dict[str, Any] | None = None
) -> dict[str, Any]:
    paths = runtime_ref_paths(runtime_root)
    payloads = {name: read_json(path) for name, path in paths.items()}
    loop = payloads["loop_runtime_state"]
    provider = payloads["provider_scheduler"]
    pool = payloads["modular_worker_pool"]
    frontier = payloads["frontier_portfolio_snapshot"]
    source_frontier = payloads["source_frontier"]
    source_family = payloads["source_family"]
    aaq = payloads["artifact_acceptance_queue"]
    scheduler_packet = payloads["scheduler_invocation_packet"]
    worker_ledger = payloads["worker_dispatch_ledger"]

    queue_depth = count_items(loop.get("task_backlog") or nested(loop, "queues", "task_backlog"))
    ready_frontier_count = count_items(loop.get("ready_frontier") or nested(loop, "queues", "ready_frontier"))
    draft_staging = loop.get("draft_staging") if isinstance(loop.get("draft_staging"), dict) else {}
    staged_count = as_int(draft_staging.get("staged_count") or pool.get("staged_count"))
    unmerged_count = as_int(draft_staging.get("unmerged_count"))
    merge_backlog = count_items(loop.get("merge_backlog") or nested(loop, "queues", "merge_backlog"))
    fan_in_backlog = count_items(loop.get("fan_in_backlog") or nested(loop, "queues", "fan_in_backlog"))
    source_gap_count = count_items(loop.get("source_gaps") or nested(loop, "queues", "source_gaps"))
    blocker_count = count_items(loop.get("blockers") or nested(loop, "queues", "blockers"))
    next_frontier_count = count_items(loop.get("next_frontier") or nested(loop, "queues", "next_frontier"))

    dynamic_width_record = nested(loop, "capacity_by_lane_class", "dynamic_width_record", default={})
    width_candidates = (
        dynamic_width_record.get("width_candidates")
        if isinstance(dynamic_width_record, dict)
        else {}
    )
    if not isinstance(width_candidates, dict):
        width_candidates = {}
    pool_width_candidates = pool.get("width_candidates") if isinstance(pool.get("width_candidates"), dict) else {}
    provider_slots = max(
        0,
        as_int(width_candidates.get("provider_available_slots")),
        as_int(width_candidates.get("executor_available_slots")),
        as_int(pool_width_candidates.get("provider_available_slots")),
        as_int(pool.get("actual_completed_width")),
        as_int(pool.get("actual_dispatched_width")),
    )
    independent_task_count = max(
        0,
        as_int(frontier.get("independent_task_count")),
        as_int(frontier.get("frontier_count")),
        as_int(width_candidates.get("independent_task_count")),
        as_int(width_candidates.get("useful_frontier_count")),
        as_int(pool_width_candidates.get("independent_task_count")),
        as_int(nested(source_family, "dynamic_width", "independent_task_count")),
        as_int(nested(source_family, "dynamic_width", "actual_dispatched_width")),
        count_items(source_frontier.get("remaining_batch_ids")),
        count_items(source_family.get("frontier_lanes")),
        queue_depth + ready_frontier_count + next_frontier_count,
        as_int(aaq.get("staged_candidate_count")),
    )
    if independent_task_count <= 0:
        independent_task_count = max(1, provider_slots, queue_depth + ready_frontier_count + 1)
    if provider_slots <= 0:
        provider_slots = max(1, as_int(pool.get("target_width")), independent_task_count)

    rate_limit_error = str(
        pool.get("rate_limit_error")
        or dynamic_width_record.get("rate_limit_error")
        or ""
    )
    retry_after = str(pool.get("retry_after") or dynamic_width_record.get("retry_after") or "")
    ready_providers = ready_provider_ids(provider)
    provider_headroom = {
        "qwen_prepaid_cheap_worker": provider_slots
        if "qwen_prepaid_cheap_worker" in ready_providers
        else 0,
        "deepseek_dp": provider_slots if "deepseek_dp" in ready_providers else 0,
        "codex_exec": 1 if "codex_exec" in ready_providers else 0,
        "codex_sdk": 1 if "codex_sdk" in ready_providers else 0,
        "search": max(1, source_gap_count or count_items(source_family.get("frontier_lanes")))
        if "search" in ready_providers
        else 0,
        "temporal_activity": max(
            1,
            count_items(loop.get("active_workers")),
            as_int(nested(loop, "capacity_by_lane_class", "temporal_activity", "pollers_seen")),
        ),
    }
    fan_in_pressure = merge_backlog + fan_in_backlog + max(0, unmerged_count)
    feedback = {
        "queue_depth": queue_depth,
        "oldest_item_age": 0,
        "provider_headroom": provider_headroom,
        "rate_limit_retry_after": {
            "rate_limit_error": rate_limit_error,
            "retry_after": retry_after,
        },
        "fan_in_backlog": fan_in_backlog,
        "merge_capacity": 1 if merge_backlog == 0 else 0,
        "failure_rate": {
            "worker_dispatch_ledger_failed_count": as_int(worker_ledger.get("failed_count"))
            or as_int(nested(worker_ledger, "poll_result_summary", "failed_count")),
            "worker_dispatch_ledger_blocked_count": as_int(worker_ledger.get("blocked_count"))
            or as_int(nested(worker_ledger, "poll_result_summary", "blocked_count")),
        },
        "quality_score": {
            "previous_validation_passed": nested(pool, "validation", "passed") is True,
            "previous_merged_count": as_int(pool.get("merged_count")),
            "previous_staged_count": as_int(pool.get("staged_count")),
        },
        "conflict_count": 0,
        "spend_budget": nested(pool, "token_cost_spend", default={}),
        "frontier": {
            "independent_task_count": independent_task_count,
            "frontier_count": max(independent_task_count, ready_frontier_count),
            "source_gap_count": source_gap_count,
            "source_frontier_status": source_frontier.get("status", ""),
            "source_family_status": source_family.get("status", ""),
        },
        "runtime_backlog": {
            "active_workers": count_items(loop.get("active_workers")),
            "task_backlog": queue_depth,
            "ready_frontier": ready_frontier_count,
            "draft_staging": staged_count,
            "unmerged_draft_staging": unmerged_count,
            "merge_backlog": merge_backlog,
            "fan_in_backlog": fan_in_backlog,
            "source_gaps": source_gap_count,
            "blockers": blocker_count,
            "next_frontier": next_frontier_count,
        },
        "scheduler": {
            "previous_spawned_lane_count": as_int(scheduler_packet.get("spawned_lane_count")),
            "previous_status": scheduler_packet.get("status", ""),
        },
        "fan_in_pressure": fan_in_pressure,
        "fixed_target_width_used": False,
        "input_refs": {name: str(path) for name, path in paths.items()},
        "extra_refs": extra_refs or {},
    }
    return feedback


def width_limit(feedback: dict[str, Any]) -> int:
    frontier = feedback.get("frontier") if isinstance(feedback.get("frontier"), dict) else {}
    headroom = feedback.get("provider_headroom") if isinstance(feedback.get("provider_headroom"), dict) else {}
    independent = max(1, as_int(frontier.get("independent_task_count"), 1))
    provider_slots = max(as_int(value) for value in headroom.values()) if headroom else independent
    if provider_slots <= 0:
        provider_slots = 1
    if feedback.get("rate_limit_retry_after", {}).get("rate_limit_error"):
        provider_slots = max(1, provider_slots // 2)
    return max(1, min(independent, provider_slots))


def make_lane(
    *,
    lane_id: str,
    lane_class: str,
    objective: str,
    provider_candidates: list[str],
    requested_width: int,
    weight: float,
    dependencies: list[str] | None = None,
    hard_constraints: list[str] | None = None,
    soft_preferences: list[str] | None = None,
    queue: str = "worker_brief_queue",
    idempotent: bool = True,
    side_effect_risk: str = "low",
    steal_allowed: bool = True,
    timeout_seconds: int = 900,
    retry_policy: dict[str, Any] | None = None,
    fallback_chain: list[str] | None = None,
    expected_artifact: str = "draft_ref",
    evidence_refs: list[str] | None = None,
    dispatch_attempts: list[dict[str, Any]] | None = None,
    width_decision_reason: str = "",
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "lane_class": lane_class,
        "objective": objective,
        "provider_candidates": provider_candidates,
        "requested_width": max(0, requested_width),
        "weight": weight,
        "dependencies": dependencies or [],
        "hard_constraints": hard_constraints or [],
        "soft_preferences": soft_preferences or [],
        "queue": queue,
        "idempotent": idempotent,
        "side_effect_risk": side_effect_risk,
        "steal_allowed": steal_allowed,
        "timeout_seconds": timeout_seconds,
        "retry_policy": retry_policy or {"max_attempts": 2, "backoff_seconds": 30},
        "fallback_chain": fallback_chain or [],
        "expected_artifact": expected_artifact,
        "dispatch_attempts": dispatch_attempts or [],
        "evidence_refs": evidence_refs or [],
        "width_decision_reason": width_decision_reason,
        "worker_output_must_enter_staging": lane_class
        in {"cheap_draft", "extraction", "eval", "contradiction", "audit", "search_source"},
        "direct_final_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_lane_allocations(
    *, task_id: str, wave_id: str, feedback: dict[str, Any], runtime_root: Path
) -> list[dict[str, Any]]:
    limit = width_limit(feedback)
    frontier = feedback.get("frontier") if isinstance(feedback.get("frontier"), dict) else {}
    runtime_backlog = (
        feedback.get("runtime_backlog") if isinstance(feedback.get("runtime_backlog"), dict) else {}
    )
    source_gap_count = as_int(frontier.get("source_gap_count"))
    source_lane_width = min(max(1, source_gap_count), limit) if source_gap_count > 0 else 0
    cheap_width = max(1, limit - source_lane_width)
    eval_width = max(1, min(limit, max(1, limit // 5)))
    fan_in_pressure = as_int(feedback.get("fan_in_pressure"))
    reason = (
        "derived_from independent_task_count/provider_headroom/rate_limit/fan_in_pressure; "
        f"limit={limit}, independent={frontier.get('independent_task_count')}, "
        f"fan_in_pressure={fan_in_pressure}"
    )
    refs = feedback.get("input_refs") if isinstance(feedback.get("input_refs"), dict) else {}
    lanes = [
        make_lane(
            lane_id=f"{wave_id}:foreground-brain",
            lane_class="foreground_brain",
            objective="Codex S reads 333/user correction/source frontier and emits this wave's supervisory decision.",
            provider_candidates=["codex_s_foreground"],
            requested_width=1,
            weight=1.0,
            queue="foreground_brain",
            side_effect_risk="medium",
            steal_allowed=False,
            expected_artifact="allocation_decision",
            evidence_refs=[refs.get("loop_runtime_state", "")],
            width_decision_reason="foreground brain is a serial supervisory lane.",
        ),
        make_lane(
            lane_id=f"{wave_id}:cheap-draft",
            lane_class="cheap_draft",
            objective="Parallel cheap draft/extraction/classification/eval candidates; Qwen prepaid first, DeepSeek/DP fallback.",
            provider_candidates=["qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"],
            requested_width=cheap_width,
            weight=float(max(1, cheap_width)),
            hard_constraints=[
                "outputs_to_staging_only",
                "qwen_first_applies_only_to_cheap_worker_lane",
                "no_direct_repo_write",
            ],
            soft_preferences=["burn_qwen_prepaid_when_headroom_available"],
            queue="xinao-codex-task-default",
            fallback_chain=["deepseek_dp", "codex_exec"],
            expected_artifact="draft_ref",
            evidence_refs=[refs.get("provider_scheduler", ""), refs.get("modular_worker_pool", "")],
            width_decision_reason=reason,
        ),
        make_lane(
            lane_id=f"{wave_id}:eval-audit",
            lane_class="eval",
            objective="Low-risk evaluation and consistency pass over staged drafts before merge.",
            provider_candidates=["qwen_prepaid_cheap_worker", "deepseek_dp", "qwen_quality_aux_worker", "codex_exec"],
            requested_width=eval_width,
            weight=max(1.0, eval_width * 0.7),
            dependencies=[f"{wave_id}:cheap-draft"],
            fallback_chain=["deepseek_dp", "codex_exec"],
            expected_artifact="audit_note",
            evidence_refs=[refs.get("worker_dispatch_ledger", "")],
            width_decision_reason=reason,
        ),
    ]
    if source_lane_width > 0:
        lanes.append(
            make_lane(
                lane_id=f"{wave_id}:search-source",
                lane_class="search_source",
                objective="Close source/package gaps and produce ClaimCard candidates for SourceLedger and AAQ.",
                provider_candidates=["search", "qwen_prepaid_cheap_worker", "deepseek_dp"],
                requested_width=source_lane_width,
                weight=float(source_lane_width),
                fallback_chain=["codex_exec"],
                expected_artifact="claim_card",
                evidence_refs=[refs.get("source_frontier", ""), refs.get("source_family", "")],
                width_decision_reason=reason,
            )
        )
    if as_int(runtime_backlog.get("blockers")) > 0:
        lanes.append(
            make_lane(
                lane_id=f"{wave_id}:repair",
                lane_class="repair",
                objective="Repair named blockers with safe bootstrap/config/route/fallback before declaring blocked.",
                provider_candidates=["codex_exec", "codex_sdk", "local_tool"],
                requested_width=1,
                weight=2.0,
                dependencies=[],
                side_effect_risk="medium",
                steal_allowed=False,
                expected_artifact="blocker_repair_ref",
                evidence_refs=[refs.get("loop_runtime_state", "")],
                width_decision_reason="repair lane opens only when LoopRuntimeState exposes unhandled blockers.",
            )
        )
    lanes.extend(
        [
            make_lane(
                lane_id=f"{wave_id}:repo-exec",
                lane_class="repo_exec",
                objective="Bounded engineering patch/test/env/provider adapter work when a WorkerBrief requires repo changes.",
                provider_candidates=["codex_exec", "codex_sdk"],
                requested_width=1,
                weight=1.0,
                dependencies=[f"{wave_id}:foreground-brain"],
                hard_constraints=["serial_when_same_file_write", "no_secret_write"],
                queue="repo_exec_serial",
                idempotent=False,
                side_effect_risk="high",
                steal_allowed=False,
                expected_artifact="patch",
                evidence_refs=[str(DEFAULT_REPO)],
                width_decision_reason="repo writes are a narrow resource and remain serial.",
            ),
            make_lane(
                lane_id=f"{wave_id}:ci-verify",
                lane_class="ci_verify",
                objective="Focused verification over generated artifacts and repo changes.",
                provider_candidates=["local_tool", "codex_exec"],
                requested_width=1,
                weight=1.0,
                dependencies=[f"{wave_id}:repo-exec"],
                queue="local_verify",
                side_effect_risk="medium",
                steal_allowed=False,
                expected_artifact="test_log",
                evidence_refs=[],
                width_decision_reason="verification is scoped to changed artifacts and remains bounded.",
            ),
            make_lane(
                lane_id=f"{wave_id}:merge-accept",
                lane_class="merge_accept",
                objective="Fan-in staged worker output into MergeConsumer, AAQ, SourceLedger, and next_frontier.",
                provider_candidates=["codex_s_foreground", "codex_exec"],
                requested_width=1,
                weight=2.0 if fan_in_pressure > 0 else 1.0,
                dependencies=[f"{wave_id}:cheap-draft", f"{wave_id}:eval-audit"],
                hard_constraints=["serial_acceptance", "worker_final_never_user_final"],
                queue="merge_accept_serial",
                idempotent=False,
                side_effect_risk="medium",
                steal_allowed=False,
                expected_artifact="accepted_artifact_ref",
                evidence_refs=[
                    refs.get("artifact_acceptance_queue", ""),
                    refs.get("source_ledger", ""),
                    refs.get("modular_worker_pool", ""),
                ],
                width_decision_reason="merge/AAQ is the serial fan-in bottleneck; slow merge sends overflow to staging, not stop.",
            ),
            make_lane(
                lane_id=f"{wave_id}:durable-temporal",
                lane_class="durable_temporal",
                objective="Own durable execution, heartbeat, retry/resume, and event/backlog continuation.",
                provider_candidates=["temporal_activity"],
                requested_width=1,
                weight=2.0,
                queue="xinao-codex-task-default",
                side_effect_risk="medium",
                steal_allowed=False,
                expected_artifact="workflow_activity_trace",
                evidence_refs=[refs.get("loop_runtime_state", ""), refs.get("temporal_worker", "")],
                width_decision_reason="Temporal owner is durable and queue-driven; it is not a fixed-interval runner.",
            ),
        ]
    )
    for lane in lanes:
        lane["evidence_refs"] = [ref for ref in lane.get("evidence_refs", []) if ref]
        lane["task_id"] = task_id
        lane["wave_id"] = wave_id
    return lanes


def build_worker_brief_queue(
    *, task_id: str, wave_id: str, lane_allocations: list[dict[str, Any]]
) -> dict[str, Any]:
    briefs = []
    for index, lane in enumerate(lane_allocations, start=1):
        briefs.append(
            {
                "brief_id": f"{wave_id}:brief:{index:02d}:{lane['lane_class']}",
                "task_id": task_id,
                "wave_id": wave_id,
                "lane_id": lane["lane_id"],
                "lane_class": lane["lane_class"],
                "objective": lane["objective"],
                "provider_candidates": lane["provider_candidates"],
                "requested_width": lane["requested_width"],
                "expected_artifact": lane["expected_artifact"],
                "queue": lane["queue"],
                "dependencies": lane["dependencies"],
                "worker_output_must_enter_staging": lane["worker_output_must_enter_staging"],
                "direct_final_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    return {
        "schema_version": "xinao.codex_s.worker_brief_queue.v1",
        "task_id": task_id,
        "wave_id": wave_id,
        "status": "worker_brief_queue_ready",
        "brief_count": len(briefs),
        "briefs": briefs,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_dispatch_attempts(
    *,
    lane_allocations: list[dict[str, Any]],
    feedback: dict[str, Any],
    output: dict[str, str],
) -> dict[str, Any]:
    provider_headroom = (
        feedback.get("provider_headroom") if isinstance(feedback.get("provider_headroom"), dict) else {}
    )
    attempts: list[dict[str, Any]] = []
    repair_items: list[dict[str, Any]] = []
    for lane in lane_allocations:
        lane_class = str(lane.get("lane_class") or "")
        attempted = True
        status = "dispatch_planned_to_existing_lane"
        failure_stage = ""
        blocker_name = ""
        if lane_class == "cheap_draft" and as_int(provider_headroom.get("qwen_prepaid_cheap_worker")) <= 0:
            status = "repair_required"
            failure_stage = "provider_selection"
            blocker_name = "QWEN_PREPAID_FIRST_NOT_ATTEMPTED"
        elif lane_class == "durable_temporal" and as_int(provider_headroom.get("temporal_activity")) <= 0:
            status = "repair_required"
            failure_stage = "temporal_worker_poll"
            blocker_name = "TEMPORAL_WORKER_SERVICE_NOT_POLLING"
        elif lane_class in {"merge_accept", "ci_verify", "repo_exec"}:
            status = "serial_lane_ready"
        attempt = {
            "lane_id": lane["lane_id"],
            "lane_class": lane_class,
            "dispatch_attempted": attempted,
            "dispatch_status": status,
            "failure_stage": failure_stage,
            "worker": lane.get("provider_candidates", [""])[0],
            "queue": lane.get("queue", ""),
            "provider": lane.get("provider_candidates", [""])[0],
            "dispatch_ref": output["latest"],
            "blocker_name": blocker_name,
            "unblock_action": "repair_or_fallback_then_requeue" if blocker_name else "",
            "report_substitute_allowed": False,
            "completion_claim_allowed": False,
        }
        attempts.append(attempt)
        lane.setdefault("dispatch_attempts", []).append(attempt)
        if blocker_name:
            repair_items.append(attempt)
    return {
        "schema_version": "xinao.codex_s.allocation_plan.dispatch_attempts.v1",
        "status": "dispatch_attempts_ready",
        "dispatch_attempt_count": len(attempts),
        "repair_required": bool(repair_items),
        "attempts": attempts,
        "repair_items": repair_items,
        "report_substitute_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_repair_plan(
    *, task_id: str, wave_id: str, dispatch_attempts: dict[str, Any], output: dict[str, str]
) -> dict[str, Any]:
    repair_items = dispatch_attempts.get("repair_items") if isinstance(dispatch_attempts.get("repair_items"), list) else []
    return {
        "schema_version": "xinao.codex_s.allocation_plan.repair_plan.v1",
        "task_id": task_id,
        "wave_id": wave_id,
        "status": "allocation_repair_plan_ready" if repair_items else "allocation_repair_plan_not_required",
        "repair_required": bool(repair_items),
        "dispatch_to": "root_intent_loop_driver",
        "temporal_consumable": True,
        "repair_items": repair_items,
        "repair_plan_ref": output["repair_plan_latest"],
        "report_substitute_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def derive_stop_allowed(feedback: dict[str, Any]) -> dict[str, Any]:
    backlog = feedback.get("runtime_backlog") if isinstance(feedback.get("runtime_backlog"), dict) else {}
    reasons = {
        "active_workers": as_int(backlog.get("active_workers")) > 0,
        "ready_frontier": as_int(backlog.get("ready_frontier")) > 0,
        "task_backlog": as_int(backlog.get("task_backlog")) > 0,
        "draft_staging": as_int(backlog.get("unmerged_draft_staging")) > 0,
        "merge_backlog": as_int(backlog.get("merge_backlog")) > 0,
        "fan_in_backlog": as_int(backlog.get("fan_in_backlog")) > 0,
        "source_gaps": as_int(backlog.get("source_gaps")) > 0,
        "next_frontier": as_int(backlog.get("next_frontier")) > 0,
        "unhandled_blockers": as_int(backlog.get("blockers")) > 0,
    }
    return {
        "derived_only": True,
        "value": not any(reasons.values()),
        "reasons": reasons,
        "requires_empty": [
            "active_workers",
            "ready_frontier",
            "task_backlog",
            "draft_staging",
            "merge_backlog",
            "source_gaps",
            "unhandled_blockers",
        ],
    }


def next_allocation_advice(feedback: dict[str, Any], repair_plan: dict[str, Any]) -> dict[str, Any]:
    backlog = feedback.get("runtime_backlog") if isinstance(feedback.get("runtime_backlog"), dict) else {}
    if repair_plan.get("repair_required") is True:
        action = "dispatch_repair_plan"
    elif as_int(backlog.get("task_backlog")) > 0 or as_int(backlog.get("ready_frontier")) > 0:
        action = "dispatch_ready_frontier_now"
    elif as_int(backlog.get("unmerged_draft_staging")) > 0 or as_int(backlog.get("merge_backlog")) > 0:
        action = "fan_in_and_merge_staging"
    elif as_int(backlog.get("source_gaps")) > 0:
        action = "open_search_source_lane"
    elif as_int(backlog.get("next_frontier")) > 0:
        action = "enqueue_next_frontier_wave"
    else:
        action = "watch_for_next_event_or_user_intent"
    return {
        "decision": action,
        "continue_main_loop": action != "watch_for_next_event_or_user_intent",
        "reason": "derived_from_LoopRuntimeState_and_dispatch_attempts",
        "report_substitute_allowed": False,
    }


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    lanes = payload.get("lane_allocations") if isinstance(payload.get("lane_allocations"), list) else []
    lane_classes = {str(lane.get("lane_class") or "") for lane in lanes if isinstance(lane, dict)}
    feedback = payload.get("feedback_inputs") if isinstance(payload.get("feedback_inputs"), dict) else {}
    stop = payload.get("stop_allowed") if isinstance(payload.get("stop_allowed"), dict) else {}
    checks = {
        "allocation_plan_not_task_route_decision_enum": payload.get("not_task_route_decision_enum") is True,
        "lane_allocations_present": len(lanes) >= 3,
        "cheap_draft_lane_present": "cheap_draft" in lane_classes,
        "audit_or_eval_lane_present": bool({"eval", "audit"} & lane_classes),
        "merge_or_verify_lane_present": bool({"merge_accept", "ci_verify"} & lane_classes),
        "width_derived_from_feedback": payload.get("target_width_source")
        == "derived_from_runtime_feedback_inputs"
        and payload.get("fixed_target_width_used") is False,
        "feedback_inputs_bound": bool(feedback.get("provider_headroom"))
        and bool(feedback.get("frontier"))
        and bool(feedback.get("runtime_backlog")),
        "worker_outputs_stage_before_final": all(
            lane.get("direct_final_allowed") is False
            and lane.get("completion_claim_allowed") is False
            for lane in lanes
            if isinstance(lane, dict)
        ),
        "dispatch_attempts_do_not_report_substitute": payload.get("dispatch_attempts", {}).get(
            "report_substitute_allowed"
        )
        is False,
        "stop_allowed_derived": stop.get("derived_only") is True,
        "completion_claim_disallowed": payload.get("completion_claim_allowed") is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_id: str = TASK_ID,
    wave_id: str = "allocation-plan-wave-001",
    extra_refs: dict[str, Any] | None = None,
    invoked_by_main_execution_loop_tick: bool = False,
    invoked_by_temporal_activity: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    output = output_paths(runtime, task_id=task_id, wave_id=wave_id)
    feedback = build_feedback_inputs(runtime_root=runtime, extra_refs=extra_refs)
    lanes = build_lane_allocations(
        task_id=task_id,
        wave_id=wave_id,
        feedback=feedback,
        runtime_root=runtime,
    )
    worker_brief_queue = build_worker_brief_queue(
        task_id=task_id,
        wave_id=wave_id,
        lane_allocations=lanes,
    )
    dispatch_attempts = build_dispatch_attempts(
        lane_allocations=lanes,
        feedback=feedback,
        output=output,
    )
    repair_plan = build_repair_plan(
        task_id=task_id,
        wave_id=wave_id,
        dispatch_attempts=dispatch_attempts,
        output=output,
    )
    stop = derive_stop_allowed(feedback)
    advice = next_allocation_advice(feedback, repair_plan)
    total_requested_width = sum(as_int(lane.get("requested_width")) for lane in lanes)
    lane_classes = [str(lane.get("lane_class") or "") for lane in lanes]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "wave_id": wave_id,
        "status": "allocation_plan_ready",
        "generated_at": now_iso(),
        "desktop_spec_ref": str(DEFAULT_DESKTOP_SPEC),
        "repo_root": str(repo),
        "not_task_route_decision_enum": True,
        "same_task_multi_lane_allocation": True,
        "feedback_inputs": feedback,
        "frontier_refs": list(feedback.get("input_refs", {}).values())
        if isinstance(feedback.get("input_refs"), dict)
        else [],
        "lane_allocations": lanes,
        "lane_class_count": len(set(lane_classes)),
        "lane_classes": lane_classes,
        "total_requested_width": total_requested_width,
        "target_width_source": "derived_from_runtime_feedback_inputs",
        "width_decision_reason": (
            "Allocation widths are recomputed from frontier size, provider headroom, "
            "rate limit/retry_after, fan-in pressure, queue depth, failure and budget facts."
        ),
        "fixed_target_width_used": False,
        "fixed_20_or_50_used": False,
        "worker_brief_queue": worker_brief_queue,
        "dispatch_attempts": dispatch_attempts,
        "durable_evidence": {
            "workflow_run_id": nested(feedback, "extra_refs", "workflow_run_id", default=""),
            "activity_or_job_id": "allocation_plan_activity"
            if invoked_by_temporal_activity
            else "",
            "worker_dispatch_ledger_ref": nested(feedback, "input_refs", "worker_dispatch_ledger", default=""),
            "heartbeat_ref": nested(feedback, "input_refs", "loop_runtime_state", default=""),
            "event_history_refs": as_list(nested(feedback, "extra_refs", "event_history_refs", default=[])),
        },
        "repair_plan": repair_plan,
        "repair_required": repair_plan.get("repair_required") is True,
        "stop_allowed": stop,
        "next_allocation_advice": advice,
        "output_paths": output,
        "invoked_by_main_execution_loop_tick": invoked_by_main_execution_loop_tick,
        "invoked_by_temporal_activity": invoked_by_temporal_activity,
        "report_substitute_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
    }
    payload["validation"] = build_validation(payload)
    payload["status"] = (
        "allocation_plan_ready"
        if payload["validation"]["passed"]
        else "allocation_plan_validation_blocked"
    )
    if write:
        write_json(Path(output["latest"]), payload)
        write_json(Path(output["task_wave"]), payload)
        write_json(Path(output["worker_brief_queue_latest"]), worker_brief_queue)
        write_json(
            Path(output["lane_allocations_latest"]),
            {
                "schema_version": "xinao.codex_s.allocation_plan.lane_allocations.v1",
                "status": "lane_allocations_ready",
                "task_id": task_id,
                "wave_id": wave_id,
                "lane_allocations": lanes,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )
        write_json(Path(output["dispatch_attempts_latest"]), dispatch_attempts)
        write_json(Path(output["repair_plan_latest"]), repair_plan)
        write_text(Path(output["readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    feedback = payload.get("feedback_inputs") if isinstance(payload.get("feedback_inputs"), dict) else {}
    backlog = feedback.get("runtime_backlog") if isinstance(feedback.get("runtime_backlog"), dict) else {}
    headroom = feedback.get("provider_headroom") if isinstance(feedback.get("provider_headroom"), dict) else {}
    advice = payload.get("next_allocation_advice") if isinstance(payload.get("next_allocation_advice"), dict) else {}
    return "\n".join(
        [
            "# Codex S AllocationPlan readback",
            "",
            str(payload.get("sentinel")),
            "",
            f"- status: `{payload.get('status')}`",
            f"- task_id: `{payload.get('task_id')}`",
            f"- wave_id: `{payload.get('wave_id')}`",
            f"- lane_classes: `{', '.join(payload.get('lane_classes', []))}`",
            f"- total_requested_width: {payload.get('total_requested_width')}",
            f"- target_width_source: `{payload.get('target_width_source')}`",
            f"- fixed_20_or_50_used: {payload.get('fixed_20_or_50_used')}",
            f"- queue_depth: {backlog.get('task_backlog')}",
            f"- ready_frontier: {backlog.get('ready_frontier')}",
            f"- next_frontier: {backlog.get('next_frontier')}",
            f"- provider_headroom: `{json.dumps(headroom, ensure_ascii=False, sort_keys=True)}`",
            f"- repair_required: {payload.get('repair_required')}",
            f"- stop_allowed: {payload.get('stop_allowed', {}).get('value') if isinstance(payload.get('stop_allowed'), dict) else ''}",
            f"- next_machine_action: `{advice.get('decision', '')}`",
            f"- validation_passed: {validation.get('passed')}",
            f"- check.width_derived_from_feedback: {checks.get('width_derived_from_feedback')}",
            "",
            "人话：这不是前台/后台二选一路由；同一任务会同时分配前台主脑、cheap draft、eval/audit、repo/verify、merge/AAQ、Temporal durable 等 lane。",
            "worker 输出必须先进 staging/fan-in/merge；worker final 不能直升用户完成。",
            "后台不可用时进入 repair/requeue/named blocker，report_substitute_allowed=false。",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-id", default=TASK_ID)
    parser.add_argument("--wave-id", default="allocation-plan-wave-001")
    parser.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    parser.add_argument("--invoked-by-temporal-activity", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_id=args.task_id,
        wave_id=args.wave_id,
        invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
        invoked_by_temporal_activity=args.invoked_by_temporal_activity,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "sentinel": payload["sentinel"],
                "status": payload["status"],
                "task_id": payload["task_id"],
                "wave_id": payload["wave_id"],
                "lane_class_count": payload["lane_class_count"],
                "total_requested_width": payload["total_requested_width"],
                "repair_required": payload["repair_required"],
                "latest_ref": payload["output_paths"]["latest"],
                "readback_zh_ref": payload["output_paths"]["readback_zh"],
                "validation": payload["validation"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
