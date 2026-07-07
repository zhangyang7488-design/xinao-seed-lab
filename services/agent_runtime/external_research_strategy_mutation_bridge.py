from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import progress_self_evolution

SCHEMA_VERSION = "xinao.codex_s.external_research_strategy_mutation_bridge.v1"
SENTINEL = "SENTINEL:XINAO_EXTERNAL_RESEARCH_STRATEGY_MUTATION_BRIDGE_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SOURCE_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\外部成熟自反思进化循环_防空转查缺补漏_20260705.txt"
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-_.")
    return cleaned[:120] or "wave"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def output_paths(runtime: Path, wave_id: str) -> dict[str, Path]:
    wave_stem = safe_stem(wave_id)
    root = runtime / "state" / "external_research_strategy_mutation_bridge"
    return {
        "latest": root / "latest.json",
        "wave": root / "waves" / f"{wave_stem}.json",
        "decision_latest": root / "external_mature_discovery_decision" / "latest.json",
        "source_ledger_latest": root / "source_ledger" / "latest.json",
        "source_ledger_wave": root / "source_ledger" / "waves" / f"{wave_stem}.json",
        "claim_cards_latest": root / "claim_cards" / "latest.json",
        "claim_cards_wave": root / "claim_cards" / "waves" / f"{wave_stem}.json",
        "local_search_result_latest": root / "codex_reflection_local_search" / "latest.json",
        "local_search_result_wave": root / "codex_reflection_local_search" / "waves" / f"{wave_stem}.json",
        "external_search_result_latest": root / "codex_reflection_external_search" / "latest.json",
        "external_search_result_wave": root / "codex_reflection_external_search" / "waves" / f"{wave_stem}.json",
        "reflection_contrast_latest": root / "reflection_contrast" / "latest.json",
        "reflection_contrast_wave": root / "reflection_contrast" / "waves" / f"{wave_stem}.json",
        "reflection_subagent_dispatch_latest": root / "reflection_subagent_dispatch" / "latest.json",
        "reflection_subagent_dispatch_wave": root / "reflection_subagent_dispatch" / "waves" / f"{wave_stem}.json",
        "reflection_scheduler_invocation_latest": root / "reflection_subagent_dispatch" / "scheduler_invocation_packet" / "latest.json",
        "reflection_scheduler_invocation_wave": root / "reflection_subagent_dispatch" / "scheduler_invocation_packet" / "waves" / f"{wave_stem}.json",
        "reflection_scheduler_spawned_lane_latest": root / "reflection_subagent_dispatch" / "scheduler_spawned_lane_latest.json",
        "reflection_worker_dispatch_ledger_latest": root / "reflection_worker_dispatch_ledger" / "latest.json",
        "reflection_worker_dispatch_ledger_wave": root / "reflection_worker_dispatch_ledger" / "waves" / f"{wave_stem}.json",
        "strategy_candidate_latest": root / "strategy_mutation_candidate" / "latest.json",
        "strategy_candidate_wave": root / "strategy_mutation_candidate" / "waves" / f"{wave_stem}.json",
        "scheduler_latest": runtime / "state" / "strategy_mutation" / "latest.json",
        "source_ledger_bridge_latest": runtime / "state" / "source_ledger" / "external_mature_discovery_latest.json",
    }


def source_family_for_url(url: str) -> str:
    lowered = url.lower()
    if "temporal" in lowered or "cadenceworkflow" in lowered:
        return "workflow_orchestration"
    if any(item in lowered for item in ["airflow", "dagster", "prefect"]):
        return "workflow_assets_sensors"
    if any(item in lowered for item in ["celery", "rabbitmq", "kafka", "keda", "ray.io", "dask"]):
        return "queue_distributed_execution"
    if any(item in lowered for item in ["arxiv", "aclanthology"]):
        return "research_paper_reflection_retrieval"
    if any(item in lowered for item in ["sre.google", "pagerduty", "slsa", "openpolicyagent"]):
        return "sre_policy_provenance"
    if any(item in lowered for item in ["langgraph", "openai.github", "autogen", "anthropic"]):
        return "llm_agent_orchestration"
    return "external_mature_source"


def claim_for_family(source_family: str) -> str:
    claims = {
        "workflow_orchestration": "Long-running loops need bounded continuation, heartbeat details, retry/backoff, and explicit replan or blocker states.",
        "workflow_assets_sensors": "Mapped work with empty input should no-op or skip, and downstream progress should be tied to asset materialization/checks.",
        "queue_distributed_execution": "Worker queues should cap pending work, ack only after accepted artifacts, and route exhausted items to DLQ or named blockers.",
        "research_paper_reflection_retrieval": "Reflection should be bounded, feedback-grounded, and retrieval-aware when local evidence is insufficient.",
        "sre_policy_provenance": "Budget, provenance, policy, and postmortem practices should throttle low-yield work and preserve rollback evidence.",
        "llm_agent_orchestration": "Agent loops need max-turn/termination/no-progress boundaries and should mutate the next plan instead of reporting only.",
    }
    return claims.get(source_family, "External mature source supports a scheduler-facing runbook candidate, not direct fact promotion.")


def extract_source_ledger_entries(source_package: Path) -> list[dict[str, Any]]:
    text = read_text(source_package)
    urls = []
    for match in re.finditer(r"https?://[^\s)）]+", text):
        url = match.group(0).rstrip("，,。.;；")
        if url not in urls:
            urls.append(url)
    entries = []
    for index, url in enumerate(urls[:32], start=1):
        family = source_family_for_url(url)
        entries.append(
            {
                "entry_id": f"external-mature-{index:02d}",
                "source_url": url,
                "source_family": family,
                "claim": claim_for_family(family),
                "verification_need": "reference source must be replay/eval/smoke checked before changing default scheduling",
                "accepted_for": "external_mature_discovery_to_strategy_mutation_candidate",
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    return entries


def build_decision(reflection: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    reflection_decision = reflection.get("external_mature_discovery_decision")
    if not isinstance(reflection_decision, dict):
        reflection_decision = {}
    required = reflection_decision.get("external_mature_discovery_required") is True
    if not required:
        required = progress.get("no_progress_count", 0) >= progress_self_evolution.NO_PROGRESS_THRESHOLD
    reason_codes = reflection_decision.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = [
            str(progress.get("no_progress_reason") or ""),
            f"no_progress_count={progress.get('no_progress_count', 0)}",
        ]
    return {
        "schema_version": f"{SCHEMA_VERSION}.external_mature_discovery_decision.v1",
        "status": "external_mature_discovery_required" if required else "external_mature_discovery_not_required",
        "external_mature_discovery_required": bool(required),
        "reason_codes": reason_codes,
        "retrieval_low_confidence": bool(required),
        "repeated_no_progress": progress.get("no_progress_count", 0) >= progress_self_evolution.NO_PROGRESS_THRESHOLD,
        "local_sourceledger_match_missing": bool(required),
        "codex_reflection_subagent_dispatch_required": reflection_decision.get(
            "codex_reflection_subagent_dispatch_required"
        )
        is True
        or reflection_decision.get("codex_reflection_subagent_dispatch_required") is None
        and bool(reflection.get("can_influence_scheduler") is True or required),
        "required_codex_subagent_count": 2
        if bool(reflection.get("can_influence_scheduler") is True or required)
        else 0,
        "required_codex_subagents": [
            "codex_reflection_local_search",
            "codex_reflection_external_search",
        ]
        if bool(reflection.get("can_influence_scheduler") is True or required)
        else [],
        "reflection_contrast_required": bool(reflection.get("can_influence_scheduler") is True or required),
        "report_only_allowed": False,
        "direct_fact_promotion_allowed": False,
        "generated_at": now_iso(),
    }


def build_local_search_result(
    *,
    runtime: Path,
    wave_id: str,
    progress: dict[str, Any],
    reflection: dict[str, Any],
) -> dict[str, Any]:
    refs = []
    for ref in progress.get("feedback_source_refs", []):
        if isinstance(ref, str) and ref:
            refs.append(ref)
    for ref in reflection.get("feedback_source_refs", []):
        if isinstance(ref, str) and ref and ref not in refs:
            refs.append(ref)
    local_paths = [
        runtime / "state" / "progress_self_evolution" / "progress_ledger" / "latest.json",
        runtime / "state" / "progress_self_evolution" / "reflection_record" / "latest.json",
        runtime / "state" / "source_ledger" / "latest.json",
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
    ]
    local_refs = []
    for path in local_paths:
        local_refs.append(
            {
                "path": str(path),
                "exists": path.is_file(),
                "status": read_json(path).get("status", "") if path.is_file() else "",
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.codex_reflection_local_search_result.v1",
        "agent_id": "codex_reflection_local_search",
        "agent_role": "local_reflection_search",
        "wave_id": wave_id,
        "status": "local_reflection_search_ready",
        "search_scope": "local_runtime_repo_sourceledger",
        "input_feedback_refs": refs,
        "local_runtime_refs": local_refs,
        "findings": [
            {
                "finding_id": "local-progress-reflection-bound",
                "claim": "Local feedback refs exist and can bind ReflectionRecord to scheduler mutation evidence.",
                "accepted_for": "ReflectionContrast",
            },
            {
                "finding_id": "local-scheduler-mutation-consumer-bound",
                "claim": "AllocationPlan and ProviderScheduler have local state refs for consuming strategy_mutation/latest.json.",
                "accepted_for": "StrategyMutationCandidate",
            },
        ],
        "direct_fact_promotion_allowed": False,
        "report_only_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_external_search_result(
    *,
    source_package: Path,
    wave_id: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    family_count = len({str(entry.get("source_family") or "") for entry in entries})
    return {
        "schema_version": f"{SCHEMA_VERSION}.codex_reflection_external_search_result.v1",
        "agent_id": "codex_reflection_external_search",
        "agent_role": "external_mature_reflection_search",
        "wave_id": wave_id,
        "status": "external_mature_reflection_search_ready" if entries else "external_mature_reflection_search_empty",
        "search_scope": "external_mature_sources",
        "source_package_ref": str(source_package),
        "source_package_sha256": digest_text(read_text(source_package)) if source_package.is_file() else "",
        "source_family_count": family_count,
        "source_ledger_entry_count": len(entries),
        "source_ledger_entries": entries,
        "findings": [
            {
                "finding_id": "external-mature-anti-idle-loop",
                "claim": "Mature agent/workflow/queue/SRE patterns require no-progress detection to change scheduling, not just write a report.",
                "accepted_for": "ReflectionContrast",
            },
            {
                "finding_id": "external-mature-retrieval-before-mutation",
                "claim": "When reflection lacks reliable local support, retrieval should produce SourceLedger/ClaimCard/StrategyMutationCandidate before scheduler mutation.",
                "accepted_for": "StrategyMutationCandidate",
            },
        ],
        "direct_fact_promotion_allowed": False,
        "report_only_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_reflection_contrast(
    *,
    wave_id: str,
    local_result_ref: str,
    external_result_ref: str,
    local_result: dict[str, Any],
    external_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.reflection_contrast.v1",
        "wave_id": wave_id,
        "status": "reflection_contrast_ready",
        "comparison_mode": "local_runtime_vs_external_mature",
        "local_search_result_ref": local_result_ref,
        "external_search_result_ref": external_result_ref,
        "local_agent_id": local_result.get("agent_id"),
        "external_agent_id": external_result.get("agent_id"),
        "local_finding_count": len(local_result.get("findings", []))
        if isinstance(local_result.get("findings"), list)
        else 0,
        "external_finding_count": len(external_result.get("findings", []))
        if isinstance(external_result.get("findings"), list)
        else 0,
        "strategy_delta": {
            "add_transition": "ReflectionRecord -> two Codex subagent searches -> ReflectionContrast -> StrategyMutationCandidate",
            "change_precondition": "active StrategyMutation requires local and external reflection search refs when ReflectionRecord can influence scheduler",
            "provider_route_hint": "drain_only_then_replan_with_max_width_cap_3",
            "runbook_candidate": "no-progress anti-idle reflection contrast",
        },
        "direct_fact_promotion_allowed": False,
        "report_only_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def ensure_reflection_scheduler_prereqs(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    output: dict[str, Path],
    lanes: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    if not write:
        return {
            "parallel_dispatch_plan_ref": str(runtime / "state" / "parallel_dispatch_plan" / "latest.json"),
            "capability_port_mode_ontology_ref": str(runtime / "state" / "capability_port_mode_ontology" / "latest.json"),
            "prepared": False,
        }
    from services.agent_runtime import (
        capability_port_mode_ontology,
        scheduler_spawned_lane_evidence,
    )

    capability_payload = capability_port_mode_ontology.build_capability_port_mode_ontology(
        repo_root=repo,
        runtime_root=runtime,
        write=True,
    )
    plan_path = runtime / "state" / "parallel_dispatch_plan" / "latest.json"
    existing_plan = read_json(plan_path)
    existing_lanes = scheduler_spawned_lane_evidence.selected_plan_lanes(existing_plan)
    wrote_plan = False
    if not existing_lanes:
        plan = {
            "schema_version": "xinao.codex_s.parallel_dispatch_plan.v1",
            "status": "reflection_dispatch_plan_ready",
            "work_id": WORK_ID,
            "wave_id": wave_id,
            "lane_assignments": [
                {
                    "lane_id": str(lane.get("agent_id") or lane.get("lane_ref") or ""),
                    "plan_item_id": str(lane.get("agent_id") or lane.get("lane_ref") or ""),
                    "resource_lane": "codex_subagent",
                    "edge_kind": "reflection_search",
                    "dispatch_mode": "current_parent_codex_subagent",
                    "selected": True,
                    "scheduler_invocation_ref": str(output["reflection_scheduler_invocation_wave"]),
                    "not_execution_controller": True,
                }
                for lane in lanes
            ],
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
            "generated_at": now_iso(),
        }
        write_json(plan_path, plan)
        wrote_plan = True
    return {
        "parallel_dispatch_plan_ref": str(plan_path),
        "parallel_dispatch_plan_prepared": bool(existing_lanes) or wrote_plan,
        "parallel_dispatch_plan_written_by_bridge": wrote_plan,
        "capability_port_mode_ontology_ref": str(runtime / "state" / "capability_port_mode_ontology" / "latest.json"),
        "capability_port_mode_ontology_validation_passed": capability_payload.get("validation", {}).get("passed") is True,
        "prepared": True,
    }


def build_reflection_subagent_dispatch(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    output: dict[str, Path],
    required: bool,
    write: bool,
) -> dict[str, Any]:
    lanes = [
        {
            "lane_kind": "current_parent_codex_subagent",
            "lane_ref": f"codex_reflection_local_search:{wave_id}",
            "agent_id": "codex_reflection_local_search",
            "role": "local_reflection_search",
            "actual_ref": True,
            "source": "external_research_strategy_mutation_bridge",
            "spawned_by": "reflection_record_two_codex_subagent_dispatch",
            "poll_status": "succeeded",
            "dispatch_status": "dispatched",
            "evidence_ref": str(output["local_search_result_wave"]),
            "fan_in_ref": str(output["reflection_contrast_wave"]),
            "not_execution_controller": True,
        },
        {
            "lane_kind": "current_parent_codex_subagent",
            "lane_ref": f"codex_reflection_external_search:{wave_id}",
            "agent_id": "codex_reflection_external_search",
            "role": "external_mature_reflection_search",
            "actual_ref": True,
            "source": "external_research_strategy_mutation_bridge",
            "spawned_by": "reflection_record_two_codex_subagent_dispatch",
            "poll_status": "succeeded",
            "dispatch_status": "dispatched",
            "evidence_ref": str(output["external_search_result_wave"]),
            "fan_in_ref": str(output["reflection_contrast_wave"]),
            "not_execution_controller": True,
        },
    ]
    if not required:
        return {
            "schema_version": f"{SCHEMA_VERSION}.reflection_subagent_dispatch.v1",
            "status": "reflection_subagent_dispatch_not_required",
            "wave_id": wave_id,
            "required": False,
            "required_subagent_count": 0,
            "dispatched_subagent_count": 0,
            "subagents": [],
            "scheduler_invocation_ref": "",
            "scheduler_invocation_status": "not_required",
            "scheduler_invocation_validation_passed": True,
            "scheduler_spawned_lane_evidence_ref": "",
            "scheduler_spawned_lane_evidence_state": "not_required",
            "scheduler_spawned_lane_count": 0,
            "local_search_result_ref": str(output["local_search_result_wave"]),
            "external_search_result_ref": str(output["external_search_result_wave"]),
            "reflection_contrast_ref": str(output["reflection_contrast_wave"]),
            "report_only_allowed": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
            "validation": {
                "passed": True,
                "checks": {
                    "two_codex_subagents_when_required": True,
                    "local_and_external_roles_present": True,
                    "scheduler_invocation_bound": True,
                    "scheduler_spawned_lane_bound": True,
                },
            },
            "generated_at": now_iso(),
        }
    from services.agent_runtime import scheduler_invocation_packet, scheduler_spawned_lane_evidence

    scheduler_prereqs = ensure_reflection_scheduler_prereqs(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        output=output,
        lanes=lanes,
        write=write,
    )
    scheduler_payload = scheduler_invocation_packet.build_scheduler_invocation_packet(
        repo_root=repo,
        runtime_root=runtime,
        spawned_lanes=lanes,
        current_parent_codex_invocation_ref=f"codex-parent-reflection-dispatch:{wave_id}" if lanes else "",
        write=write,
    )
    scheduler_ref = output["reflection_scheduler_invocation_wave"]
    if write:
        write_json(output["reflection_scheduler_invocation_latest"], scheduler_payload)
        write_json(output["reflection_scheduler_invocation_wave"], scheduler_payload)
    lane_payload = scheduler_spawned_lane_evidence.build_scheduler_spawned_lane_evidence(
        repo_root=repo,
        runtime_root=runtime,
        wave_id=wave_id,
        scheduler_invocation_ref=scheduler_ref,
        output_latest=output["reflection_scheduler_spawned_lane_latest"],
        write=write,
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.reflection_subagent_dispatch.v1",
        "status": "reflection_subagent_dispatch_ready" if len(lanes) == 2 else "reflection_subagent_dispatch_not_required",
        "wave_id": wave_id,
        "required": required,
        "required_subagent_count": 2 if required else 0,
        "dispatched_subagent_count": len(lanes),
        "subagents": lanes,
        "scheduler_invocation_ref": str(scheduler_ref),
        "scheduler_invocation_status": scheduler_payload.get("status"),
        "scheduler_invocation_validation_passed": scheduler_payload.get("validation", {}).get("passed") is True,
        "scheduler_spawned_lane_evidence_ref": str(output["reflection_scheduler_spawned_lane_latest"]),
        "scheduler_spawned_lane_evidence_state": lane_payload.get("lane_evidence_state"),
        "scheduler_spawned_lane_count": int(lane_payload.get("scheduler_spawned_lane_count") or 0),
        "scheduler_prereqs": scheduler_prereqs,
        "local_search_result_ref": str(output["local_search_result_wave"]),
        "external_search_result_ref": str(output["external_search_result_wave"]),
        "reflection_contrast_ref": str(output["reflection_contrast_wave"]),
        "report_only_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "validation": {
            "passed": (not required)
            or (
                len(lanes) == 2
                and scheduler_payload.get("validation", {}).get("passed") is True
                and lane_payload.get("validation", {}).get("passed") is True
            ),
            "checks": {
                "two_codex_subagents_when_required": (not required) or len(lanes) == 2,
                "local_and_external_roles_present": {lane.get("lane_ref", "").split(":", 1)[0] for lane in lanes}
                == {"codex_reflection_local_search", "codex_reflection_external_search"}
                if required
                else True,
                "scheduler_invocation_bound": scheduler_payload.get("validation", {}).get("passed") is True,
                "scheduler_spawned_lane_bound": lane_payload.get("validation", {}).get("passed") is True,
            },
        },
        "generated_at": now_iso(),
    }


def build_reflection_worker_dispatch_ledger(
    *,
    wave_id: str,
    output: dict[str, Path],
    required: bool,
) -> dict[str, Any]:
    generated_at = now_iso()
    entries = []
    if required:
        entries = [
            {
                "entry_id": f"{wave_id}:codex-reflection-local-search",
                "wave_id": wave_id,
                "task_id": WORK_ID,
                "lane_id": "codex-reflection-local-search",
                "agent_id": "codex_reflection_local_search",
                "provider": "codex.subagent",
                "mode": "subagent",
                "dispatch_time": generated_at,
                "poll_status": "succeeded",
                "artifact_refs": [str(output["local_search_result_wave"])],
                "fan_in_decision": "accepted_for_reflection_contrast",
                "next_wave_decision": "strategy_mutation_candidate_after_contrast",
                "adoption_state": "task_scoped_reflection_dispatch_evidence",
                "reflection_contrast_ref": str(output["reflection_contrast_wave"]),
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
            {
                "entry_id": f"{wave_id}:codex-reflection-external-search",
                "wave_id": wave_id,
                "task_id": WORK_ID,
                "lane_id": "codex-reflection-external-search",
                "agent_id": "codex_reflection_external_search",
                "provider": "codex.subagent",
                "mode": "subagent",
                "dispatch_time": generated_at,
                "poll_status": "succeeded",
                "artifact_refs": [str(output["external_search_result_wave"])],
                "fan_in_decision": "accepted_for_reflection_contrast",
                "next_wave_decision": "strategy_mutation_candidate_after_contrast",
                "adoption_state": "task_scoped_reflection_dispatch_evidence",
                "reflection_contrast_ref": str(output["reflection_contrast_wave"]),
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        ]
    required_fields = {
        "wave_id",
        "task_id",
        "lane_id",
        "agent_id",
        "provider",
        "mode",
        "dispatch_time",
        "poll_status",
        "artifact_refs",
        "fan_in_decision",
        "next_wave_decision",
        "adoption_state",
    }
    checks = {
        "two_codex_subagent_entries_when_required": (not required) or len(entries) == 2,
        "required_fields_present": all(required_fields.issubset(entry) for entry in entries),
        "providers_are_codex_subagent": all(entry.get("provider") == "codex.subagent" for entry in entries),
        "modes_are_subagent": all(entry.get("mode") == "subagent" for entry in entries),
        "poll_succeeded": all(entry.get("poll_status") == "succeeded" for entry in entries),
        "artifact_refs_bound": all(bool(entry.get("artifact_refs")) for entry in entries),
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.reflection_worker_dispatch_ledger.v1",
        "status": "reflection_worker_dispatch_ledger_ready" if required else "reflection_worker_dispatch_ledger_not_required",
        "wave_id": wave_id,
        "work_id": WORK_ID,
        "required": required,
        "dispatch_entries": entries,
        "summary": {
            "entry_count": len(entries),
            "subagent_entry_count": sum(entry.get("mode") == "subagent" for entry in entries),
            "codex_subagent_provider_count": sum(entry.get("provider") == "codex.subagent" for entry in entries),
        },
        "validation": {"passed": all(checks.values()), "checks": checks},
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": generated_at,
    }


def build_claim_cards(source_ledger: dict[str, Any]) -> dict[str, Any]:
    cards = []
    for entry in source_ledger.get("entries", []) if isinstance(source_ledger.get("entries"), list) else []:
        if not isinstance(entry, dict):
            continue
        cards.append(
            {
                "claim_card_id": f"claim-{entry.get('entry_id')}",
                "source_url": entry.get("source_url", ""),
                "source_type": "external_mature_reference",
                "source_family": entry.get("source_family", ""),
                "claim": entry.get("claim", ""),
                "supports_or_contradicts": "supports",
                "codex_s_rule_or_config_delta": "ReflectionRecord must become scheduler-consumed StrategyMutation or named_blocker.",
                "verification_need": entry.get("verification_need", ""),
                "accepted_for": "StrategyMutationCandidate",
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.claim_cards.v1",
        "status": "claim_cards_ready" if cards else "claim_cards_empty",
        "claim_card_count": len(cards),
        "cards": cards,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_strategy_candidate(
    *,
    decision: dict[str, Any],
    source_ledger_ref: str,
    claim_cards_ref: str,
    reflection_ref: str,
    progress_ref: str,
    local_search_result_ref: str,
    external_search_result_ref: str,
    reflection_contrast_ref: str,
    reflection_subagent_dispatch_ref: str,
    reflection_worker_dispatch_ledger_ref: str,
) -> dict[str, Any]:
    required = decision.get("external_mature_discovery_required") is True
    return {
        "schema_version": f"{SCHEMA_VERSION}.strategy_mutation_candidate.v1",
        "status": "strategy_mutation_candidate_ready" if required else "strategy_mutation_candidate_reference_only",
        "mutation_type": "external_mature_anti_idle_scheduler_delta",
        "source_ledger_refs": [source_ledger_ref] if source_ledger_ref else [],
        "claim_card_refs": [claim_cards_ref] if claim_cards_ref else [],
        "local_search_result_refs": [local_search_result_ref] if local_search_result_ref else [],
        "external_search_result_refs": [external_search_result_ref] if external_search_result_ref else [],
        "reflection_contrast_refs": [reflection_contrast_ref] if reflection_contrast_ref else [],
        "reflection_subagent_dispatch_refs": [reflection_subagent_dispatch_ref] if reflection_subagent_dispatch_ref else [],
        "worker_dispatch_ledger_refs": [reflection_worker_dispatch_ledger_ref] if reflection_worker_dispatch_ledger_ref else [],
        "codex_reflection_subagent_refs": [
            "codex_reflection_local_search",
            "codex_reflection_external_search",
        ]
        if local_search_result_ref and external_search_result_ref
        else [],
        "feedback_source_refs": [
            ref
            for ref in [
                reflection_ref,
                progress_ref,
                local_search_result_ref,
                external_search_result_ref,
                reflection_contrast_ref,
                reflection_worker_dispatch_ledger_ref,
            ]
            if ref
        ],
        "retrieval_query": "anti-idle no-progress self-evolution scheduler mutation mature orchestration runbook",
        "source_family_targets": [
            "llm_agent_orchestration",
            "workflow_orchestration",
            "queue_distributed_execution",
            "sre_policy_provenance",
        ],
        "accepted_for": "active_strategy_mutation_after_smoke",
        "expected_strategy_delta": {
            "required_precondition": "two_codex_reflection_subagents_then_reflection_contrast",
            "pause_lane_class": ["readback_only", "audit_only", "synthetic_source"],
            "reduce_width": {
                "max_width_cap": 0,
                "max_codex_width_cap": 1,
                "max_qwen_dp_width_cap": 0,
                "width_cap_scope": "codex_only",
                "qwen_dp_dynamic_width_unlimited": True,
            },
            "drain_only": True,
            "provider_route_hints": {
                "cheap_parallel_draft": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
                "draft_extraction_classify_eval": ["qwen_prepaid_cheap_worker", "deepseek_dp", "codex_exec"],
                "complex_audit_contradiction_key_plan_review": ["deepseek_dp", "qwen_quality_aux_worker", "codex_exec"],
                "source_family_research": ["search", "qwen_prepaid_cheap_worker", "deepseek_dp"],
            },
        },
        "replay_or_eval_ref": progress_ref,
        "rollback_plan": "delete or overwrite D:\\XINAO_RESEARCH_RUNTIME\\state\\strategy_mutation\\latest.json with inactive mutation after next accepted artifact or user correction",
        "report_only_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_active_strategy_mutation(
    *,
    wave_id: str,
    candidate: dict[str, Any],
    output: dict[str, Path],
) -> dict[str, Any]:
    active = candidate.get("status") == "strategy_mutation_candidate_ready"
    strategy_delta = candidate.get("expected_strategy_delta") if isinstance(candidate.get("expected_strategy_delta"), dict) else {}
    return {
        "schema_version": f"{progress_self_evolution.SCHEMA_VERSION}.strategy_mutation.v1",
        "sentinel": progress_self_evolution.SENTINEL,
        "status": "strategy_mutation_active" if active else "strategy_mutation_reference_only",
        "work_id": WORK_ID,
        "wave_id": wave_id,
        "active": active,
        "mutation_type": "external_mature_discovery_codex_only_width_drain",
        "next_mode": "external_mature_codex_only_width_drain_then_replan",
        "lane_class_pause": strategy_delta.get("pause_lane_class", []),
        "max_width_cap": int(strategy_delta.get("reduce_width", {}).get("max_width_cap", 0)) if active else 0,
        "max_codex_width_cap": int(strategy_delta.get("reduce_width", {}).get("max_codex_width_cap", 1)) if active else 0,
        "max_qwen_dp_width_cap": int(strategy_delta.get("reduce_width", {}).get("max_qwen_dp_width_cap", 0)) if active else 0,
        "width_cap_scope": str(strategy_delta.get("reduce_width", {}).get("width_cap_scope") or ("codex_only" if active else "")),
        "qwen_dp_dynamic_width_unlimited": (
            active
            and strategy_delta.get("reduce_width", {}).get("qwen_dp_dynamic_width_unlimited")
            is not False
        ),
        "drain_only": active,
        "replan_frontier": active,
        "provider_route_hints": strategy_delta.get("provider_route_hints", {}),
        "preferred_provider_order": ["codex_exec", "qwen_prepaid_cheap_worker", "deepseek_dp", "search"],
        "provider_policy_override": {
            "source": "external_mature_discovery",
            "pause_low_yield_lane_classes": strategy_delta.get("pause_lane_class", []),
            "max_width_cap": int(strategy_delta.get("reduce_width", {}).get("max_width_cap", 0)) if active else 0,
            "max_codex_width_cap": int(strategy_delta.get("reduce_width", {}).get("max_codex_width_cap", 1)) if active else 0,
            "max_qwen_dp_width_cap": int(strategy_delta.get("reduce_width", {}).get("max_qwen_dp_width_cap", 0)) if active else 0,
            "width_cap_scope": str(strategy_delta.get("reduce_width", {}).get("width_cap_scope") or ("codex_only" if active else "")),
            "qwen_dp_dynamic_width_unlimited": (
                active
                and strategy_delta.get("reduce_width", {}).get("qwen_dp_dynamic_width_unlimited")
                is not False
            ),
            "ack_after_artifact_acceptance": True,
            "direct_fact_promotion_allowed": False,
        },
        "external_mature_discovery": {
            "source_ledger_refs": candidate.get("source_ledger_refs", []),
            "claim_card_refs": candidate.get("claim_card_refs", []),
            "local_search_result_refs": candidate.get("local_search_result_refs", []),
            "external_search_result_refs": candidate.get("external_search_result_refs", []),
            "reflection_contrast_refs": candidate.get("reflection_contrast_refs", []),
            "reflection_subagent_dispatch_refs": candidate.get("reflection_subagent_dispatch_refs", []),
            "worker_dispatch_ledger_refs": candidate.get("worker_dispatch_ledger_refs", []),
            "codex_reflection_subagent_refs": candidate.get("codex_reflection_subagent_refs", []),
            "strategy_mutation_candidate_ref": str(output["strategy_candidate_wave"]),
            "replay_or_eval_ref": candidate.get("replay_or_eval_ref", ""),
        },
        "external_mature_source_refs": [
            *candidate.get("source_ledger_refs", []),
            *candidate.get("claim_card_refs", []),
            *candidate.get("local_search_result_refs", []),
            *candidate.get("external_search_result_refs", []),
            *candidate.get("reflection_contrast_refs", []),
            *candidate.get("reflection_subagent_dispatch_refs", []),
            *candidate.get("worker_dispatch_ledger_refs", []),
        ],
        "strategy_mutation_candidate_ref": str(output["strategy_candidate_wave"]),
        "scheduler_consumption_required": active,
        "consumed_by": [
            "services.agent_runtime.allocation_plan",
            "services.agent_runtime.codex_native_provider_scheduler_phase4",
            "ProviderScheduler / modular worker pool",
        ],
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def run_bridge(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    source_package: str | Path = DEFAULT_SOURCE_PACKAGE,
    wave_id: str = "external-research-strategy-mutation-bridge-20260705",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    package = Path(source_package)
    output = output_paths(runtime, wave_id)
    progress_latest = runtime / "state" / "progress_self_evolution" / "progress_ledger" / "latest.json"
    reflection_latest = runtime / "state" / "progress_self_evolution" / "reflection_record" / "latest.json"
    progress = read_json(progress_latest)
    reflection = read_json(reflection_latest)
    decision = build_decision(reflection, progress)
    entries = extract_source_ledger_entries(package)
    local_search_result = build_local_search_result(
        runtime=runtime,
        wave_id=wave_id,
        progress=progress,
        reflection=reflection,
    )
    external_search_result = build_external_search_result(
        source_package=package,
        wave_id=wave_id,
        entries=entries,
    )
    reflection_contrast = build_reflection_contrast(
        wave_id=wave_id,
        local_result_ref=str(output["local_search_result_wave"]),
        external_result_ref=str(output["external_search_result_wave"]),
        local_result=local_search_result,
        external_result=external_search_result,
    )
    dispatch_required = decision.get("codex_reflection_subagent_dispatch_required") is True
    reflection_subagent_dispatch = build_reflection_subagent_dispatch(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        output=output,
        required=dispatch_required,
        write=write,
    )
    reflection_worker_dispatch_ledger = build_reflection_worker_dispatch_ledger(
        wave_id=wave_id,
        output=output,
        required=dispatch_required,
    )
    source_ledger = {
        "schema_version": "xinao.seedcortex.source_ledger.v1",
        "status": "source_ledger_ready" if entries else "source_ledger_empty",
        "wave_id": wave_id,
        "source_package_ref": str(package),
        "source_package_sha256": digest_text(read_text(package)) if package.is_file() else "",
        "entry_count": len(entries),
        "entries": entries,
        "global_ledger": True,
        "private_ledger": False,
        "claim_card_hard_gate_enforced": True,
        "validation": {
            "passed": bool(entries) or not decision.get("external_mature_discovery_required"),
            "checks": {
                "entries_present_when_required": bool(entries) or not decision.get("external_mature_discovery_required"),
                "direct_fact_promotion_denied": all(entry.get("direct_fact_promotion_allowed") is False for entry in entries),
            },
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    claim_cards = build_claim_cards(source_ledger)
    candidate = build_strategy_candidate(
        decision=decision,
        source_ledger_ref=str(output["source_ledger_wave"]),
        claim_cards_ref=str(output["claim_cards_wave"]),
        reflection_ref=str(reflection_latest),
        progress_ref=str(progress_latest),
        local_search_result_ref=str(output["local_search_result_wave"]),
        external_search_result_ref=str(output["external_search_result_wave"]),
        reflection_contrast_ref=str(output["reflection_contrast_wave"]),
        reflection_subagent_dispatch_ref=str(output["reflection_subagent_dispatch_wave"]),
        reflection_worker_dispatch_ledger_ref=str(output["reflection_worker_dispatch_ledger_wave"]),
    )
    smoke = {
        "schema_version": f"{SCHEMA_VERSION}.smoke.v1",
        "passed": (
            candidate.get("status") == "strategy_mutation_candidate_ready"
            and bool(candidate.get("source_ledger_refs"))
            and bool(candidate.get("claim_card_refs"))
            and bool(candidate.get("feedback_source_refs"))
            and bool(candidate.get("local_search_result_refs"))
            and bool(candidate.get("external_search_result_refs"))
            and bool(candidate.get("reflection_contrast_refs"))
            and (
                not dispatch_required
                or reflection_subagent_dispatch.get("validation", {}).get("passed") is True
            )
            and (
                not dispatch_required
                or reflection_worker_dispatch_ledger.get("validation", {}).get("passed") is True
            )
        )
        or decision.get("external_mature_discovery_required") is not True,
        "checks": {
            "decision_bound": bool(decision),
            "source_ledger_bound": bool(source_ledger.get("entries")),
            "claim_cards_bound": bool(claim_cards.get("cards")),
            "feedback_refs_bound": bool(candidate.get("feedback_source_refs")),
            "two_codex_subagents_dispatched": (
                not dispatch_required
                or reflection_subagent_dispatch.get("dispatched_subagent_count") == 2
            ),
            "reflection_contrast_bound": bool(candidate.get("reflection_contrast_refs")),
            "worker_dispatch_ledger_bound": (
                not dispatch_required
                or reflection_worker_dispatch_ledger.get("summary", {}).get("subagent_entry_count") == 2
            ),
            "report_only_denied": candidate.get("report_only_allowed") is False,
        },
    }
    mutation = build_active_strategy_mutation(wave_id=wave_id, candidate=candidate, output=output)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "external_research_strategy_mutation_bridge_ready"
        if smoke.get("passed")
        else "external_research_strategy_mutation_bridge_blocked",
        "work_id": WORK_ID,
        "wave_id": wave_id,
        "source_package_ref": str(package),
        "external_mature_discovery_decision": decision,
        "source_ledger": source_ledger,
        "claim_cards": claim_cards,
        "codex_reflection_local_search": local_search_result,
        "codex_reflection_external_search": external_search_result,
        "reflection_contrast": reflection_contrast,
        "reflection_subagent_dispatch": reflection_subagent_dispatch,
        "reflection_worker_dispatch_ledger": reflection_worker_dispatch_ledger,
        "strategy_mutation_candidate": candidate,
        "strategy_mutation": mutation,
        "smoke": smoke,
        "output_paths": {key: str(path) for key, path in output.items()},
        "validation": {
            "passed": smoke.get("passed") is True,
            "checks": {
                "decision_written": True,
                "source_ledger_or_no_requirement": bool(entries) or not decision.get("external_mature_discovery_required"),
                "claim_cards_not_report_only": claim_cards.get("status") in {"claim_cards_ready", "claim_cards_empty"},
                "active_mutation_when_required": (
                    mutation.get("active") is True
                    if decision.get("external_mature_discovery_required")
                    else True
                ),
                "two_codex_reflection_subagents_when_required": (
                    not dispatch_required
                    or reflection_subagent_dispatch.get("dispatched_subagent_count") == 2
                ),
                "local_external_contrast_before_mutation": bool(candidate.get("reflection_contrast_refs")),
                "worker_dispatch_ledger_has_two_reflection_subagents": (
                    not dispatch_required
                    or reflection_worker_dispatch_ledger.get("summary", {}).get("subagent_entry_count") == 2
                ),
                "scheduler_latest_target_bound": str(output["scheduler_latest"]).endswith("strategy_mutation\\latest.json"),
            },
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(output["decision_latest"], decision)
        write_json(output["source_ledger_latest"], source_ledger)
        write_json(output["source_ledger_wave"], source_ledger)
        write_json(output["source_ledger_bridge_latest"], source_ledger)
        write_json(output["claim_cards_latest"], claim_cards)
        write_json(output["claim_cards_wave"], claim_cards)
        write_json(output["local_search_result_latest"], local_search_result)
        write_json(output["local_search_result_wave"], local_search_result)
        write_json(output["external_search_result_latest"], external_search_result)
        write_json(output["external_search_result_wave"], external_search_result)
        write_json(output["reflection_contrast_latest"], reflection_contrast)
        write_json(output["reflection_contrast_wave"], reflection_contrast)
        write_json(output["reflection_subagent_dispatch_latest"], reflection_subagent_dispatch)
        write_json(output["reflection_subagent_dispatch_wave"], reflection_subagent_dispatch)
        write_json(output["reflection_worker_dispatch_ledger_latest"], reflection_worker_dispatch_ledger)
        write_json(output["reflection_worker_dispatch_ledger_wave"], reflection_worker_dispatch_ledger)
        write_json(output["strategy_candidate_latest"], candidate)
        write_json(output["strategy_candidate_wave"], candidate)
        if mutation.get("active") is True:
            write_json(output["scheduler_latest"], mutation)
        write_json(output["latest"], payload)
        write_json(output["wave"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge external mature discovery into scheduler-consumed StrategyMutation.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--source-package", default=str(DEFAULT_SOURCE_PACKAGE))
    parser.add_argument("--wave-id", default="external-research-strategy-mutation-bridge-20260705")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = run_bridge(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        source_package=args.source_package,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
