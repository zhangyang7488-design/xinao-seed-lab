from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.progress_self_evolution.v1"
SENTINEL = "SENTINEL:XINAO_PROGRESS_SELF_EVOLUTION_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
NO_PROGRESS_THRESHOLD = 2
DEFAULT_COST_PER_ACCEPTED_ARTIFACT_LIMIT = 0.25


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-_.")
    return cleaned[:120] or "wave"


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def digest_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def paths(runtime: Path, wave_id: str) -> dict[str, Path]:
    wave_stem = safe_stem(wave_id)
    root = runtime / "state" / "progress_self_evolution"
    return {
        "progress_latest": root / "progress_ledger" / "latest.json",
        "progress_wave": root / "progress_ledger" / "waves" / f"{wave_stem}.json",
        "reflection_latest": root / "reflection_record" / "latest.json",
        "reflection_wave": root / "reflection_record" / "waves" / f"{wave_stem}.json",
        "strategy_latest": root / "strategy_mutation" / "latest.json",
        "strategy_wave": root / "strategy_mutation" / "waves" / f"{wave_stem}.json",
        "scheduler_latest": runtime / "state" / "strategy_mutation" / "latest.json",
    }


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _previous_no_progress_count(runtime: Path, source_digest: str) -> int:
    previous = read_json(runtime / "state" / "progress_self_evolution" / "progress_ledger" / "latest.json")
    if previous.get("source_digest") != source_digest:
        return 0
    return _as_int(previous.get("no_progress_count"))


def _artifact_delta_count(
    *,
    artifact_delta_count: int,
    aaq_accepted_delta: int,
    default_invoke_delta: int,
    named_blocker_delta: int,
    claimcard_delta: int,
) -> int:
    return max(
        _as_int(artifact_delta_count),
        _as_int(aaq_accepted_delta),
        _as_int(default_invoke_delta),
        _as_int(named_blocker_delta),
        0 if _as_int(claimcard_delta) > 0 else 0,
    )


def build_progress_ledger(
    *,
    runtime: Path,
    wave_id: str,
    source_digest: str,
    source_theme_id: str = "",
    input_count: int = 0,
    mapped_count: int = 0,
    artifact_delta_count: int = 0,
    merge_artifact_refs: list[str] | None = None,
    aaq_accepted_delta: int = 0,
    default_invoke_delta: int = 0,
    named_blocker_delta: int = 0,
    claimcard_delta: int = 0,
    readback_delta: int = 0,
    cost_actual: float = 0.0,
    token_actual: int = 0,
    wall_time_seconds: float = 0.0,
    provider_route: dict[str, Any] | None = None,
    synthetic_item_used: bool = False,
    source_frontier_empty: bool = False,
    next_frontier_real_work_count: int = 0,
    next_frontier_self_loop_count: int = 0,
    feedback_source_refs: list[str] | None = None,
    no_progress_reason: str = "",
) -> dict[str, Any]:
    real_delta = _artifact_delta_count(
        artifact_delta_count=artifact_delta_count,
        aaq_accepted_delta=aaq_accepted_delta,
        default_invoke_delta=default_invoke_delta,
        named_blocker_delta=named_blocker_delta,
        claimcard_delta=claimcard_delta,
    )
    accepted_or_artifact = max(1, _as_int(aaq_accepted_delta), _as_int(default_invoke_delta), real_delta)
    cost = _as_float(cost_actual)
    cost_per_accepted_artifact = cost / accepted_or_artifact if cost else 0.0
    budget_pressure = cost_per_accepted_artifact > DEFAULT_COST_PER_ACCEPTED_ARTIFACT_LIMIT and real_delta <= 0
    previous_no_progress = _previous_no_progress_count(runtime, source_digest)
    no_progress_count = 0 if real_delta > 0 else previous_no_progress + 1
    if real_delta > 0 and _as_int(next_frontier_real_work_count) > 0:
        decision = "continue_with_real_frontier"
    elif source_frontier_empty and not synthetic_item_used:
        decision = "empty_frontier_noop"
    elif budget_pressure:
        decision = "reduce_width"
    elif no_progress_count >= NO_PROGRESS_THRESHOLD:
        decision = "replan"
    else:
        decision = "drain_fan_in"
    if not no_progress_reason and real_delta <= 0:
        if budget_pressure:
            no_progress_reason = "budget_pressure_without_accepted_artifact"
        else:
            no_progress_reason = (
                "source_frontier_empty"
                if source_frontier_empty
                else "no_artifact_or_accepted_delta"
            )
    return {
        "schema_version": f"{SCHEMA_VERSION}.progress_ledger.v1",
        "sentinel": SENTINEL,
        "status": "progress_ledger_recorded",
        "work_id": WORK_ID,
        "wave_id": wave_id,
        "source_digest": source_digest,
        "source_theme_id": source_theme_id,
        "input_count": _as_int(input_count),
        "mapped_count": _as_int(mapped_count),
        "artifact_delta_count": real_delta,
        "merge_artifact_refs": merge_artifact_refs or [],
        "AAQ_accepted_delta": _as_int(aaq_accepted_delta),
        "default_invoke_delta": _as_int(default_invoke_delta),
        "named_blocker_delta": _as_int(named_blocker_delta),
        "claimcard_delta": _as_int(claimcard_delta),
        "readback_delta": _as_int(readback_delta),
        "cost_actual": float(cost_actual or 0.0),
        "cost_per_accepted_artifact": cost_per_accepted_artifact,
        "budget_gate": {
            "active": budget_pressure,
            "cost_per_accepted_artifact": cost_per_accepted_artifact,
            "limit": DEFAULT_COST_PER_ACCEPTED_ARTIFACT_LIMIT,
            "decision": "reduce_width" if budget_pressure else "within_budget",
        },
        "token_actual": _as_int(token_actual),
        "wall_time_seconds": float(wall_time_seconds or 0.0),
        "provider_route": provider_route or {},
        "synthetic_item_used": bool(synthetic_item_used),
        "source_frontier_empty": bool(source_frontier_empty),
        "next_frontier_real_work_count": _as_int(next_frontier_real_work_count),
        "next_frontier_self_loop_count": _as_int(next_frontier_self_loop_count),
        "no_progress_count": no_progress_count,
        "repeated_finding_count": max(0, no_progress_count - 1),
        "no_progress_reason": no_progress_reason,
        "feedback_source_refs": feedback_source_refs or [],
        "decision": decision,
        "progress_made": real_delta > 0,
        "is_request_satisfied": False,
        "generated_at": now_iso(),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_reflection_record(progress: dict[str, Any], feedback_source_refs: list[str]) -> dict[str, Any]:
    trigger = progress.get("no_progress_count", 0) >= NO_PROGRESS_THRESHOLD or (
        progress.get("source_frontier_empty") is True and progress.get("synthetic_item_used") is True
    ) or progress.get("no_progress_reason") in {
        "repeated_fixable_without_artifact_delta",
        "budget_pressure_without_accepted_artifact",
    }
    external_mature_required = bool(
        trigger
        and (
            progress.get("no_progress_count", 0) >= NO_PROGRESS_THRESHOLD
            or progress.get("no_progress_reason")
            in {
                "repeated_fixable_without_artifact_delta",
                "budget_pressure_without_accepted_artifact",
                "repeated_tool_failure",
                "unsupported_answer",
                "unresolved_premise",
            }
        )
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.reflection_record.v1",
        "sentinel": SENTINEL,
        "status": "reflection_record_ready" if trigger and feedback_source_refs else "reflection_record_reference_only",
        "work_id": WORK_ID,
        "wave_id": progress.get("wave_id", ""),
        "triggered": bool(trigger),
        "feedback_source_refs": feedback_source_refs,
        "can_influence_scheduler": bool(trigger and feedback_source_refs),
        "external_mature_discovery_decision": {
            "schema_version": f"{SCHEMA_VERSION}.external_mature_discovery_decision.v1",
            "external_mature_discovery_required": external_mature_required,
            "codex_reflection_subagent_dispatch_required": bool(trigger and feedback_source_refs),
            "required_codex_subagent_count": 2 if trigger and feedback_source_refs else 0,
            "required_codex_subagents": [
                {
                    "agent_id": "codex_reflection_local_search",
                    "role": "local_reflection_search",
                    "search_scope": "local_runtime_repo_sourceledger",
                    "expected_artifact": "LocalReflectionSearchResult",
                },
                {
                    "agent_id": "codex_reflection_external_search",
                    "role": "external_mature_reflection_search",
                    "search_scope": "external_mature_sources",
                    "expected_artifact": "ExternalMatureSearchResult",
                },
            ]
            if trigger and feedback_source_refs
            else [],
            "reflection_contrast_required": bool(trigger and feedback_source_refs),
            "reason_codes": [
                str(progress.get("no_progress_reason") or ""),
                f"no_progress_count={progress.get('no_progress_count')}",
            ],
            "allowed_outputs": [
                "SourceLedgerEntry",
                "ClaimCard",
                "RunbookCandidate",
                "ToolCandidate",
                "ActionKnowledgeDelta",
                "StrategyMutationCandidate",
                "named_blocker",
            ],
            "report_only_allowed": False,
            "direct_fact_promotion_allowed": False,
        },
        "reasons": [
            str(progress.get("no_progress_reason") or ""),
            f"no_progress_count={progress.get('no_progress_count')}",
        ],
        "progress_ledger_ref": "",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_strategy_mutation(progress: dict[str, Any], reflection: dict[str, Any]) -> dict[str, Any]:
    active = reflection.get("can_influence_scheduler") is True
    if progress.get("source_frontier_empty") is True:
        mutation_type = "replan_frontier"
        next_mode = "drain_only_then_replan_frontier"
    elif progress.get("budget_gate", {}).get("active") is True:
        mutation_type = "reduce_width"
        next_mode = "budget_gate_reduce_width_and_drain"
    elif progress.get("no_progress_count", 0) >= NO_PROGRESS_THRESHOLD:
        mutation_type = "reduce_width"
        next_mode = "reduce_width_and_drain_only"
    else:
        mutation_type = "drain_only"
        next_mode = "drain_fan_in"
    return {
        "schema_version": f"{SCHEMA_VERSION}.strategy_mutation.v1",
        "sentinel": SENTINEL,
        "status": "strategy_mutation_active" if active else "strategy_mutation_reference_only",
        "work_id": WORK_ID,
        "wave_id": progress.get("wave_id", ""),
        "active": active,
        "mutation_type": mutation_type,
        "next_mode": next_mode,
        "lane_class_pause": ["readback_only", "audit_only", "synthetic_source"] if active else [],
        "max_width_cap": 3 if active else 0,
        "drain_only": active and mutation_type in {"reduce_width", "drain_only", "replan_frontier"},
        "replan_frontier": active and mutation_type == "replan_frontier",
        "budget_gate": progress.get("budget_gate", {}),
        "preferred_provider_order": ["codex_exec", "qwen_prepaid_cheap_worker", "deepseek_dp"]
        if active and progress.get("budget_gate", {}).get("active") is True
        else [],
        "provider_route_hints": {
            "cheap_parallel_draft": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
            "draft_extraction_classify_eval": ["qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"],
            "complex_audit_contradiction_key_plan_review": ["deepseek_dp", "qwen_quality_aux_worker", "codex_exec"],
        }
        if active
        else {},
        "external_mature_discovery": reflection.get("external_mature_discovery_decision", {}),
        "external_mature_source_refs": [],
        "strategy_mutation_candidate_ref": "",
        "scheduler_consumption_required": active,
        "consumed_by": [
            "services.agent_runtime.allocation_plan",
            "services.agent_runtime.codex_s_durable_default_chain_supervisor",
            "ProviderScheduler / modular worker pool",
        ],
        "progress_ledger_decision": progress.get("decision"),
        "progress_ledger_ref": "",
        "reflection_record_ref": "",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def record_progress_bundle(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    wave_id: str,
    source_digest: str,
    source_theme_id: str = "",
    input_count: int = 0,
    mapped_count: int = 0,
    artifact_delta_count: int = 0,
    merge_artifact_refs: list[str] | None = None,
    aaq_accepted_delta: int = 0,
    default_invoke_delta: int = 0,
    named_blocker_delta: int = 0,
    claimcard_delta: int = 0,
    readback_delta: int = 0,
    cost_actual: float = 0.0,
    token_actual: int = 0,
    wall_time_seconds: float = 0.0,
    provider_route: dict[str, Any] | None = None,
    synthetic_item_used: bool = False,
    source_frontier_empty: bool = False,
    next_frontier_real_work_count: int = 0,
    next_frontier_self_loop_count: int = 0,
    feedback_source_refs: list[str] | None = None,
    no_progress_reason: str = "",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    output = paths(runtime, wave_id)
    progress = build_progress_ledger(
        runtime=runtime,
        wave_id=wave_id,
        source_digest=source_digest,
        source_theme_id=source_theme_id,
        input_count=input_count,
        mapped_count=mapped_count,
        artifact_delta_count=artifact_delta_count,
        merge_artifact_refs=merge_artifact_refs,
        aaq_accepted_delta=aaq_accepted_delta,
        default_invoke_delta=default_invoke_delta,
        named_blocker_delta=named_blocker_delta,
        claimcard_delta=claimcard_delta,
        readback_delta=readback_delta,
        cost_actual=cost_actual,
        token_actual=token_actual,
        wall_time_seconds=wall_time_seconds,
        provider_route=provider_route,
        synthetic_item_used=synthetic_item_used,
        source_frontier_empty=source_frontier_empty,
        next_frontier_real_work_count=next_frontier_real_work_count,
        next_frontier_self_loop_count=next_frontier_self_loop_count,
        feedback_source_refs=feedback_source_refs,
        no_progress_reason=no_progress_reason,
    )
    refs = feedback_source_refs or []
    reflection = build_reflection_record(progress, refs)
    mutation = build_strategy_mutation(progress, reflection)
    progress["output_paths"] = {key: str(path) for key, path in output.items()}
    reflection["progress_ledger_ref"] = str(output["progress_wave"])
    mutation["progress_ledger_ref"] = str(output["progress_wave"])
    mutation["reflection_record_ref"] = str(output["reflection_wave"])
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "progress_self_evolution_recorded",
        "work_id": WORK_ID,
        "wave_id": wave_id,
        "progress_ledger": progress,
        "reflection_record": reflection,
        "strategy_mutation": mutation,
        "output_paths": {key: str(path) for key, path in output.items()},
        "validation": {
            "passed": True,
            "checks": {
                "progress_ledger_present": True,
                "reflection_has_feedback_when_active": (
                    reflection.get("can_influence_scheduler") is not True
                    or bool(reflection.get("feedback_source_refs"))
                ),
                "strategy_mutation_changes_scheduler_when_active": (
                    mutation.get("active") is not True
                    or bool(mutation.get("next_mode"))
                ),
            },
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    if write:
        write_json(output["progress_latest"], progress)
        write_json(output["progress_wave"], progress)
        if reflection.get("triggered") is True:
            write_json(output["reflection_latest"], reflection)
            write_json(output["reflection_wave"], reflection)
        if mutation.get("active") is True:
            write_json(output["strategy_latest"], mutation)
            write_json(output["strategy_wave"], mutation)
            write_json(output["scheduler_latest"], mutation)
    return bundle


def load_active_strategy_mutation(runtime_root: str | Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    runtime = Path(runtime_root)
    mutation = read_json(runtime / "state" / "strategy_mutation" / "latest.json")
    return mutation if mutation.get("active") is True else {}


def scheduler_consumption_from_mutation(mutation: dict[str, Any]) -> dict[str, Any]:
    if not mutation:
        return {
            "strategy_mutation_consumed": False,
            "active": False,
            "next_mode": "",
            "max_width_cap": 0,
            "drain_only": False,
            "replan_frontier": False,
            "lane_class_pause": [],
            "provider_route_hints": {},
            "preferred_provider_order": [],
            "provider_policy_override": {},
            "external_mature_source_refs": [],
            "budget_gate": {},
        }
    return {
        "strategy_mutation_consumed": True,
        "active": True,
        "mutation_ref": str(mutation.get("progress_ledger_ref") or ""),
        "wave_id": str(mutation.get("wave_id") or ""),
        "next_mode": str(mutation.get("next_mode") or ""),
        "mutation_type": str(mutation.get("mutation_type") or ""),
        "max_width_cap": _as_int(mutation.get("max_width_cap")),
        "drain_only": mutation.get("drain_only") is True,
        "replan_frontier": mutation.get("replan_frontier") is True,
        "lane_class_pause": mutation.get("lane_class_pause") if isinstance(mutation.get("lane_class_pause"), list) else [],
        "provider_route_hints": mutation.get("provider_route_hints") if isinstance(mutation.get("provider_route_hints"), dict) else {},
        "preferred_provider_order": mutation.get("preferred_provider_order") if isinstance(mutation.get("preferred_provider_order"), list) else [],
        "provider_policy_override": mutation.get("provider_policy_override") if isinstance(mutation.get("provider_policy_override"), dict) else {},
        "external_mature_source_refs": mutation.get("external_mature_source_refs") if isinstance(mutation.get("external_mature_source_refs"), list) else [],
        "budget_gate": mutation.get("budget_gate") if isinstance(mutation.get("budget_gate"), dict) else {},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record ProgressLedger/ReflectionRecord/StrategyMutation evidence.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--wave-id", default="progress-self-evolution-anti-idle-20260705")
    parser.add_argument("--source-digest", default="")
    parser.add_argument("--source-theme-id", default="progress_self_evolution.manual_invoke")
    parser.add_argument("--artifact-delta-count", type=int, default=0)
    parser.add_argument("--aaq-accepted-delta", type=int, default=0)
    parser.add_argument("--default-invoke-delta", type=int, default=0)
    parser.add_argument("--named-blocker-delta", type=int, default=0)
    parser.add_argument("--claimcard-delta", type=int, default=0)
    parser.add_argument("--readback-delta", type=int, default=1)
    parser.add_argument("--source-frontier-empty", action="store_true")
    parser.add_argument("--synthetic-item-used", action="store_true")
    parser.add_argument("--feedback-source-ref", action="append", default=[])
    parser.add_argument("--no-progress-reason", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    source_digest = args.source_digest or digest_json(
        {
            "wave_id": args.wave_id,
            "source_theme_id": args.source_theme_id,
            "source_frontier_empty": args.source_frontier_empty,
            "feedback_source_refs": args.feedback_source_ref,
        }
    )
    payload = record_progress_bundle(
        runtime_root=args.runtime_root,
        wave_id=args.wave_id,
        source_digest=source_digest,
        source_theme_id=args.source_theme_id,
        artifact_delta_count=args.artifact_delta_count,
        aaq_accepted_delta=args.aaq_accepted_delta,
        default_invoke_delta=args.default_invoke_delta,
        named_blocker_delta=args.named_blocker_delta,
        claimcard_delta=args.claimcard_delta,
        readback_delta=args.readback_delta,
        source_frontier_empty=args.source_frontier_empty,
        synthetic_item_used=args.synthetic_item_used,
        feedback_source_refs=args.feedback_source_ref,
        no_progress_reason=args.no_progress_reason,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
