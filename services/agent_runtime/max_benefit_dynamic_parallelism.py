import argparse
import datetime as dt
import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from services.agent_runtime import task_package_resolver as task_package
from pydantic import BaseModel, ConfigDict, Field


WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
SENTINEL = "SENTINEL:XINAO_MAX_BENEFIT_DYNAMIC_PARALLELISM_READY"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DRAFT = task_package.DEFAULT_TASK_PACKAGE_ROOT / "TASK_PACKAGE.json"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def repo_readback_write_enabled(runtime_root: Path) -> bool:
    flag = os.environ.get("XINAO_RUNTIME_REPO_READBACK_WRITE")
    if flag is not None:
        return flag.strip().lower() not in {"0", "false", "no", "off"}
    return runtime_root.resolve() == DEFAULT_RUNTIME.resolve()


def boundary_fields() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest().upper()


def read_text_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "full_read_required": True,
            "named_blocker": "SOURCE_DRAFT_MISSING",
        }
    raw = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "char_count": len(raw),
        "sha256": sha256_text(raw),
        "full_read_required": True,
        "accepted_for": "strategy_input_and_source_document_not_completion_evidence",
    }


def read_current_task_package_snapshot() -> dict[str, Any]:
    package = task_package.resolve_current_task_package(include_manifest_ref=True)
    refs = package.get("refs", [])
    return {
        "path": str(package.get("entrypoint_ref") or package.get("task_package_manifest_path") or ""),
        "exists": package.get("all_required_sources_read_full") is True,
        "char_count": sum(int(ref.get("char_count") or 0) for ref in refs if isinstance(ref, dict)),
        "sha256": str(package.get("source_package_digest_sha256") or "").upper(),
        "full_read_required": True,
        "accepted_for": "strategy_input_and_current_task_package_not_completion_evidence",
        "task_package": package,
        "manifest_driven": package.get("manifest_driven") is True,
        "single_entry_driven": package.get("single_entry_driven") is True,
        "legacy_fallback": package.get("legacy_fallback") is True,
    }


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": str(path), "exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "path": str(path),
            "exists": True,
            "json_valid": False,
            "error": str(exc),
        }
    secret_env_probe = payload.get("secret_env_probe")
    if not isinstance(secret_env_probe, dict):
        secret_env_probe = {}
    source_ledger = payload.get("source_ledger")
    if not isinstance(source_ledger, dict):
        source_ledger = {}
    source_entries = source_ledger.get("entries")
    runtime_entrypoint_invocation = payload.get("runtime_entrypoint_invocation")
    if not isinstance(runtime_entrypoint_invocation, dict):
        runtime_entrypoint_invocation = {}
    actual_dispatch_refs = payload.get("actual_dispatch_refs")
    if not isinstance(actual_dispatch_refs, dict):
        actual_dispatch_refs = {}
    claim_span_evidence = payload.get("claim_span_evidence")
    if not isinstance(claim_span_evidence, dict):
        claim_span_evidence = payload
    claim_span_validation = claim_span_evidence.get("validation")
    if not isinstance(claim_span_validation, dict):
        claim_span_validation = {}
    artifact_acceptance_candidate = claim_span_evidence.get("artifact_acceptance_candidate")
    if not isinstance(artifact_acceptance_candidate, dict):
        artifact_acceptance_candidate = {}
    service_entrypoint = payload.get("service_entrypoint")
    if not isinstance(service_entrypoint, dict):
        service_entrypoint = {}
    providers = payload.get("providers")
    if not isinstance(providers, list):
        providers = []
    provider_ids = [
        str(provider.get("provider_id"))
        for provider in providers
        if isinstance(provider, dict) and provider.get("provider_id")
    ]
    return {
        "path": str(path),
        "exists": True,
        "json_valid": True,
        "schema_version": payload.get("schema_version"),
        "sentinel": payload.get("sentinel"),
        "status": payload.get("status"),
        "provider_id": payload.get("provider_id"),
        "selected_provider_id": payload.get("selected_provider_id"),
        "source_family_count": payload.get("source_family_count"),
        "entry_count": payload.get("entry_count"),
        "edge_count": payload.get("edge_count"),
        "selected_edge_count": payload.get("selected_edge_count"),
        "parallel_selected_count": payload.get("parallel_selected_count"),
        "serial_edge_count": payload.get("serial_edge_count"),
        "lane_result_count": payload.get("lane_result_count"),
        "source_ledger_entry_count": len(source_entries) if isinstance(source_entries, list) else None,
        "claim_card_count": len(payload.get("claim_cards", []))
        if isinstance(payload.get("claim_cards"), list)
        else None,
        "decision_count": payload.get("decision_count"),
        "accepted_claim_count": payload.get("accepted_claim_count"),
        "citation_check_count": payload.get("citation_check_count"),
        "opened_or_checked_count": payload.get("opened_or_checked_count"),
        "blocked_or_unverified_count": payload.get("blocked_or_unverified_count"),
        "citation_verified_claim_count": payload.get("citation_verified_claim_count"),
        "promotion_allowed": payload.get("promotion_allowed"),
        "direct_fact_promotion_allowed": payload.get("direct_fact_promotion_allowed"),
        "accepted_artifact_count": payload.get("accepted_artifact_count"),
        "accepted_artifacts": payload.get("accepted_artifacts", []),
        "staged_candidate_count": payload.get("staged_candidate_count"),
        "rejected_artifact_count": payload.get("rejected_artifact_count"),
        "rejected_no_verifier_count": payload.get("rejected_no_verifier_count"),
        "blocked_artifact_count": payload.get("blocked_artifact_count"),
        "adoption_state": payload.get("adoption_state"),
        "root_runtime_enforced": payload.get("runtime_enforced"),
        "root_default_runtime_scheduler_invoked": payload.get(
            "default_runtime_scheduler_invoked"
        ),
        "base_correction_runtime_adoption_state": payload.get(
            "base_correction_runtime_adoption_state"
        ),
        "runtime_entrypoint_adoption_state": payload.get("runtime_entrypoint_adoption_state"),
        "default_runtime_scheduler_invoked": payload.get("default_runtime_scheduler_invoked"),
        "scheduler_invoked": payload.get("scheduler_invoked"),
        "spawned_lane_count": payload.get("spawned_lane_count"),
        "packet_runtime_enforced": payload.get("packet_runtime_enforced")
        if payload.get("packet_runtime_enforced") is not None
        else runtime_entrypoint_invocation.get("packet_runtime_enforced"),
        "packet_default_runtime_scheduler_invoked": payload.get(
            "packet_default_runtime_scheduler_invoked"
        )
        if payload.get("packet_default_runtime_scheduler_invoked") is not None
        else runtime_entrypoint_invocation.get("packet_default_runtime_scheduler_invoked"),
        "target_fastapi_route": payload.get("target_fastapi_route"),
        "accepted_source_count": payload.get("accepted_source_count"),
        "staged_source_count": payload.get("staged_source_count"),
        "rejected_duplicate_count": payload.get("rejected_duplicate_count"),
        "named_blocker": payload.get("named_blocker"),
        "secret_env_probe_status": secret_env_probe.get("status"),
        "loaded_variable_names": payload.get("loaded_variable_names")
        or secret_env_probe.get("loaded_variable_names"),
        "configured_variable_names": payload.get("configured_variable_names")
        or secret_env_probe.get("configured_variable_names"),
        "raw_secret_values_recorded": payload.get(
            "raw_secret_values_recorded",
            secret_env_probe.get("raw_secret_values_recorded"),
        ),
        "paid_provider_invocation_performed": payload.get("paid_provider_invocation_performed"),
        "provider_api_cost_usd": payload.get("provider_api_cost_usd"),
        "claim_span_evidence_status": claim_span_evidence.get("status"),
        "claim_span_item_count": claim_span_evidence.get("claim_span_item_count"),
        "opened_claim_span_item_count": claim_span_evidence.get(
            "opened_claim_span_item_count"
        ),
        "claim_to_source_check_binding_complete": claim_span_evidence.get(
            "claim_to_source_check_binding_complete"
        ),
        "claim_span_validation_passed": claim_span_validation.get("passed"),
        "claim_span_fact_promotion_allowed": claim_span_evidence.get(
            "fact_promotion_allowed"
        ),
        "claim_span_completion_claim_allowed": claim_span_evidence.get(
            "completion_claim_allowed"
        ),
        "claim_span_artifact_candidate_id": artifact_acceptance_candidate.get(
            "candidate_id"
        ),
        "claim_span_artifact_ref": artifact_acceptance_candidate.get("artifact_ref"),
        "runtime_enforced": payload.get("runtime_enforced")
        or runtime_entrypoint_invocation.get("runtime_enforced"),
        "runtime_enforced_scope": payload.get("runtime_enforced_scope")
        or runtime_entrypoint_invocation.get("runtime_enforced_scope"),
        "not_completion_gate": payload.get("not_completion_gate")
        or runtime_entrypoint_invocation.get("not_completion_gate"),
        "not_execution_controller": payload.get("not_execution_controller")
        or runtime_entrypoint_invocation.get("not_execution_controller"),
        "activity": payload.get("activity"),
        "actual_dispatch_refs": actual_dispatch_refs,
        "service_entrypoint_caller": service_entrypoint.get("caller"),
        "api_cli_adoption_state": service_entrypoint.get("api_cli_adoption_state"),
        "default_user_correction_intake_api_bound": service_entrypoint.get(
            "default_user_correction_intake_api_bound"
        ),
        "service_runtime_enforced": service_entrypoint.get("runtime_enforced"),
        "service_temporal_enforced": service_entrypoint.get("temporal_enforced"),
        "trigger_installed": payload.get(
            "trigger_installed",
            service_entrypoint.get("trigger_installed"),
        ),
        "service_memory_promotion_allowed": service_entrypoint.get(
            "memory_promotion_allowed"
        ),
        "service_policy_promotion_allowed": service_entrypoint.get(
            "policy_promotion_allowed"
        ),
        "service_completion_gate": service_entrypoint.get("completion_gate"),
        "memory_promotion_allowed": payload.get(
            "memory_promotion_allowed",
            service_entrypoint.get("memory_promotion_allowed"),
        ),
        "policy_promotion_allowed": payload.get(
            "policy_promotion_allowed",
            service_entrypoint.get("policy_promotion_allowed"),
        ),
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
        "provider_ids": provider_ids,
        "has_durable_packet_service_provider": (
            "codex_s.durable_parallel_wave_packet_service" in provider_ids
        ),
        "has_main_loop_tick_service_provider": (
            "codex_s.main_execution_loop_tick_service" in provider_ids
        ),
        "has_default_main_loop_trigger_candidate_provider": (
            "codex_s.default_main_loop_trigger_candidate_service" in provider_ids
        ),
        "has_scheduler_invocation_packet_service_provider": (
            "codex_s.scheduler_invocation_packet_service" in provider_ids
        ),
        "has_seed_lab_user_correction_runtime_service_provider": (
            "codex_s.seed_lab_user_correction_runtime_service" in provider_ids
        ),
    }


def pyproject_dependency_snapshot(repo_root: Path) -> dict[str, Any]:
    pyproject = repo_root / "pyproject.toml"
    lockfile = repo_root / "uv.lock"
    if not pyproject.exists():
        fallback_pyproject = DEFAULT_REPO / "pyproject.toml"
        fallback_lockfile = DEFAULT_REPO / "uv.lock"
        if fallback_pyproject.exists():
            pyproject = fallback_pyproject
            lockfile = fallback_lockfile
        else:
            return {
                "pyproject": str(pyproject),
                "exists": False,
                "mature_carriers_present": False,
            }

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    dependencies = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    workflow = list(optional.get("workflow", []))
    p0_candidates = list(optional.get("p0-candidates", []))
    carrier_text = "\n".join(dependencies + workflow + p0_candidates).lower()
    required = {
        "temporalio": "temporalio" in carrier_text,
        "langgraph": "langgraph" in carrier_text,
        "litellm": "litellm" in carrier_text,
        "pydantic": "pydantic" in carrier_text,
    }
    return {
        "pyproject": str(pyproject),
        "uv_lock": str(lockfile),
        "uv_lock_present": lockfile.exists(),
        "workflow_extra": workflow,
        "p0_candidates_extra": p0_candidates,
        "mature_carriers": required,
        "mature_carriers_present": all(required.values()),
        "sync_command_verified_in_current_turn": (
            "uv sync --extra api --extra workflow --extra observability --extra dev --extra p0-candidates"
        ),
    }


def count_snapshot(ref: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {
        "path": ref.get("path", ""),
        "exists": ref.get("exists") is True,
        "schema_version": ref.get("schema_version"),
        "status": ref.get("status"),
        **{field: int(ref.get(field) or 0) for field in fields},
        "not_execution_controller": ref.get("not_execution_controller") is not False,
    }


CandidateKind = Literal[
    "code_patch_candidate",
    "verifier_candidate",
    "schema_contract_candidate",
    "runtime_evidence_candidate",
    "source_family_research_candidate",
    "private_oss_candidate",
    "deepseek_draft_candidate",
    "local_triage_candidate",
    "readback_candidate",
    "blocker_repair_candidate",
    "adapter_smoke_candidate",
    "policy_decision_candidate",
    "replay_eval_candidate",
]

CandidateState = Literal[
    "ready_for_dispatch",
    "ready_for_verify",
    "ready_for_explore",
    "ready_for_repair",
    "staged_candidate",
    "blocked_named",
]


class FrontierCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["xinao.codex_s.frontier_candidate.v1"] = (
        "xinao.codex_s.frontier_candidate.v1"
    )
    candidate_id: str
    candidate_kind: CandidateKind
    parent_frontier_ref: str
    proposed_by_lane: str
    expected_user_visible_value: float = Field(ge=0)
    evidence_yield: float = Field(ge=0)
    uncertainty_reduction: float = Field(ge=0)
    unblock_value: float = Field(ge=0)
    time_to_signal: float = Field(gt=0)
    cost_estimate: float = Field(ge=0)
    verification_cost: float = Field(ge=0)
    merge_cost: float = Field(ge=0)
    risk_score: float = Field(ge=0)
    parallel_fit: float = Field(ge=0)
    verification_fit: float = Field(ge=0)
    novelty_score: float = Field(ge=0)
    probability_of_acceptance: float = Field(ge=0, le=1)
    frontier_unblock_score: float = Field(ge=0)
    reuse_score: float = Field(ge=0)
    weighted_utility_score: float
    expected_value_score: float
    utility_score: float
    current_state: CandidateState
    reason_codes: list[str]
    accepted_for: str
    evidence_acceptance_required: bool = True
    completion_claim_allowed: bool = False
    not_source_of_truth: bool = True
    not_user_completion: bool = True
    not_completion_decision: bool = True
    not_execution_controller: bool = True


class FrontierPortfolioSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["xinao.codex_s.frontier_portfolio_snapshot.v1"] = (
        "xinao.codex_s.frontier_portfolio_snapshot.v1"
    )
    wave_id: str
    tick_id: str
    candidate_scores: list[dict[str, Any]]
    selected_for_dispatch: list[str]
    selected_for_verify: list[str]
    selected_for_explore: list[str]
    selected_for_repair: list[str]
    rejected_or_deferred: list[dict[str, str]]
    reason_codes: list[str]
    explore_exploit_mix: dict[str, int]
    not_worker_count_objective: bool = True


class LaneResultReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["xinao.codex_s.lane_result_review.v1"] = (
        "xinao.codex_s.lane_result_review.v1"
    )
    review_id: str
    producer_lane: str
    peer_reviewer_lane: str
    adversarial_verifier_lane: str
    machine_oracle_refs: list[str]
    evidence_auditor_lane: str
    acceptance_decision: Literal[
        "accepted_to_code",
        "accepted_to_tests",
        "accepted_to_runtime_evidence",
        "accepted_to_readback",
        "staged_candidate",
        "rejected_duplicate",
        "rejected_no_verifier",
        "blocked_named",
        "next_frontier_only",
    ]
    accepted_for: str
    next_frontier_delta: str
    independent_verification_required: bool = True


class RewardSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["xinao.codex_s.reward_signal.v1"] = (
        "xinao.codex_s.reward_signal.v1"
    )
    signal_id: str
    user_visible_delta: str
    evidence_delta: str
    verification_delta: str
    blocker_delta: str
    cost_actual: str
    time_actual: str
    regret_note: str
    next_policy_adjustment: str


def weighted_score(values: dict[str, float]) -> float:
    return round(
        3.0 * values["expected_user_visible_value"]
        + 2.5 * values["unblock_value"]
        + 2.0 * values["evidence_yield"]
        + 1.5 * values["uncertainty_reduction"]
        + 1.0 * values["novelty_score"]
        + 1.0 * values["verification_fit"]
        - 1.5 * values["time_to_signal"]
        - 1.0 * values["cost_estimate"]
        - 2.0 * values["risk_score"],
        4,
    )


def expected_value_score(values: dict[str, float]) -> float:
    denominator = (
        values["cost_estimate"]
        + values["verification_cost"]
        + values["merge_cost"]
        + values["risk_score"]
    )
    return round(
        values["expected_user_visible_value"]
        * values["probability_of_acceptance"]
        * values["frontier_unblock_score"]
        * values["reuse_score"]
        / max(denominator, 0.1),
        4,
    )


def candidate(
    *,
    candidate_id: str,
    candidate_kind: CandidateKind,
    parent_frontier_ref: str,
    proposed_by_lane: str,
    expected_user_visible_value: float,
    evidence_yield: float,
    uncertainty_reduction: float,
    unblock_value: float,
    time_to_signal: float,
    cost_estimate: float,
    verification_cost: float,
    merge_cost: float,
    risk_score: float,
    parallel_fit: float,
    verification_fit: float,
    novelty_score: float,
    probability_of_acceptance: float,
    frontier_unblock_score: float,
    reuse_score: float,
    current_state: CandidateState,
    reason_codes: list[str],
    accepted_for: str,
) -> FrontierCandidate:
    values = {
        "expected_user_visible_value": expected_user_visible_value,
        "evidence_yield": evidence_yield,
        "uncertainty_reduction": uncertainty_reduction,
        "unblock_value": unblock_value,
        "time_to_signal": time_to_signal,
        "cost_estimate": cost_estimate,
        "verification_cost": verification_cost,
        "merge_cost": merge_cost,
        "risk_score": risk_score,
        "parallel_fit": parallel_fit,
        "verification_fit": verification_fit,
        "novelty_score": novelty_score,
        "probability_of_acceptance": probability_of_acceptance,
        "frontier_unblock_score": frontier_unblock_score,
        "reuse_score": reuse_score,
    }
    weighted = weighted_score(values)
    expected = expected_value_score(values)
    utility = round((weighted / 10.0) + expected + parallel_fit + verification_fit, 4)
    return FrontierCandidate(
        candidate_id=candidate_id,
        candidate_kind=candidate_kind,
        parent_frontier_ref=parent_frontier_ref,
        proposed_by_lane=proposed_by_lane,
        expected_user_visible_value=expected_user_visible_value,
        evidence_yield=evidence_yield,
        uncertainty_reduction=uncertainty_reduction,
        unblock_value=unblock_value,
        time_to_signal=time_to_signal,
        cost_estimate=cost_estimate,
        verification_cost=verification_cost,
        merge_cost=merge_cost,
        risk_score=risk_score,
        parallel_fit=parallel_fit,
        verification_fit=verification_fit,
        novelty_score=novelty_score,
        probability_of_acceptance=probability_of_acceptance,
        frontier_unblock_score=frontier_unblock_score,
        reuse_score=reuse_score,
        weighted_utility_score=weighted,
        expected_value_score=expected,
        utility_score=utility,
        current_state=current_state,
        reason_codes=reason_codes,
        accepted_for=accepted_for,
    )


def build_candidates() -> list[FrontierCandidate]:
    parent = "next-frontier-after-W102-provider-swap-proof"
    return [
        candidate(
            candidate_id="fc-supervisor-loop-state-schema",
            candidate_kind="schema_contract_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="codex_schema_writer",
            expected_user_visible_value=8.0,
            evidence_yield=8.0,
            uncertainty_reduction=5.0,
            unblock_value=9.0,
            time_to_signal=2.0,
            cost_estimate=2.0,
            verification_cost=1.5,
            merge_cost=1.0,
            risk_score=1.0,
            parallel_fit=8.0,
            verification_fit=8.0,
            novelty_score=3.0,
            probability_of_acceptance=0.82,
            frontier_unblock_score=1.9,
            reuse_score=1.6,
            current_state="ready_for_dispatch",
            reason_codes=["critical_path", "schema_first", "high_unblock_value"],
            accepted_for="schema_contract_and_next_frontier",
        ),
        candidate(
            candidate_id="fc-fan-in-acceptance-queue",
            candidate_kind="verifier_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="verification_topology",
            expected_user_visible_value=8.0,
            evidence_yield=9.0,
            uncertainty_reduction=6.0,
            unblock_value=8.5,
            time_to_signal=2.0,
            cost_estimate=2.0,
            verification_cost=1.0,
            merge_cost=1.5,
            risk_score=0.8,
            parallel_fit=7.0,
            verification_fit=9.0,
            novelty_score=3.0,
            probability_of_acceptance=0.86,
            frontier_unblock_score=1.8,
            reuse_score=1.7,
            current_state="ready_for_verify",
            reason_codes=["evidence_acceptance_gate", "prevents_report_only_stop"],
            accepted_for="artifact_acceptance_policy",
        ),
        candidate(
            candidate_id="fc-deepseek-surrogate-blocker-repair",
            candidate_kind="blocker_repair_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="deepseek_batch_plan",
            expected_user_visible_value=7.0,
            evidence_yield=7.0,
            uncertainty_reduction=8.0,
            unblock_value=8.0,
            time_to_signal=2.5,
            cost_estimate=2.5,
            verification_cost=1.0,
            merge_cost=1.0,
            risk_score=1.2,
            parallel_fit=6.0,
            verification_fit=8.0,
            novelty_score=4.0,
            probability_of_acceptance=0.72,
            frontier_unblock_score=1.7,
            reuse_score=1.5,
            current_state="ready_for_repair",
            reason_codes=[
                "named_blocker",
                "code_path_sanitizer_repair_verified",
                "deepseek_width_not_codex_slot_bound",
                "unblocks_large_width_sidecar",
            ],
            accepted_for="named_blocker_repair_frontier",
        ),
        candidate(
            candidate_id="fc-lane-result-review-contract",
            candidate_kind="schema_contract_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="fan_in_acceptance",
            expected_user_visible_value=7.0,
            evidence_yield=8.0,
            uncertainty_reduction=6.0,
            unblock_value=7.5,
            time_to_signal=2.0,
            cost_estimate=1.8,
            verification_cost=1.0,
            merge_cost=1.0,
            risk_score=0.8,
            parallel_fit=7.0,
            verification_fit=8.0,
            novelty_score=3.5,
            probability_of_acceptance=0.84,
            frontier_unblock_score=1.6,
            reuse_score=1.5,
            current_state="ready_for_dispatch",
            reason_codes=["producer_reviewer_verifier_auditor_modeled"],
            accepted_for="verifier_topology_contract",
        ),
        candidate(
            candidate_id="fc-source-family-next-wave",
            candidate_kind="source_family_research_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="source_family_wave_scheduler",
            expected_user_visible_value=5.5,
            evidence_yield=7.0,
            uncertainty_reduction=7.0,
            unblock_value=5.0,
            time_to_signal=2.0,
            cost_estimate=2.0,
            verification_cost=1.2,
            merge_cost=1.0,
            risk_score=0.7,
            parallel_fit=9.0,
            verification_fit=6.0,
            novelty_score=8.0,
            probability_of_acceptance=0.75,
            frontier_unblock_score=1.2,
            reuse_score=1.3,
            current_state="ready_for_explore",
            reason_codes=["minimum_exploration_budget", "source_family_coverage"],
            accepted_for="claimcard_staging",
        ),
        candidate(
            candidate_id="fc-private-oss-candidate-matrix",
            candidate_kind="private_oss_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="github_private_open_source_lane",
            expected_user_visible_value=5.5,
            evidence_yield=6.0,
            uncertainty_reduction=7.5,
            unblock_value=5.0,
            time_to_signal=2.5,
            cost_estimate=2.0,
            verification_cost=2.0,
            merge_cost=1.0,
            risk_score=1.5,
            parallel_fit=8.0,
            verification_fit=5.5,
            novelty_score=9.0,
            probability_of_acceptance=0.55,
            frontier_unblock_score=1.25,
            reuse_score=1.4,
            current_state="ready_for_explore",
            reason_codes=["private_oss_is_discovery_lane", "sandbox_before_use"],
            accepted_for="candidate_matrix_reference_only",
        ),
        candidate(
            candidate_id="fc-chinese-readback-heartbeat",
            candidate_kind="readback_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="human_visible_readback",
            expected_user_visible_value=7.0,
            evidence_yield=5.0,
            uncertainty_reduction=4.0,
            unblock_value=5.0,
            time_to_signal=1.0,
            cost_estimate=0.8,
            verification_cost=0.5,
            merge_cost=0.5,
            risk_score=0.3,
            parallel_fit=6.0,
            verification_fit=6.0,
            novelty_score=2.0,
            probability_of_acceptance=0.9,
            frontier_unblock_score=1.2,
            reuse_score=1.2,
            current_state="ready_for_verify",
            reason_codes=["user_visible_delta", "not_final_heartbeat"],
            accepted_for="human_visible_status",
        ),
        candidate(
            candidate_id="fc-reward-signal-ledger",
            candidate_kind="replay_eval_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="portfolio_scheduler",
            expected_user_visible_value=6.0,
            evidence_yield=7.0,
            uncertainty_reduction=6.0,
            unblock_value=6.5,
            time_to_signal=2.5,
            cost_estimate=2.0,
            verification_cost=1.2,
            merge_cost=1.0,
            risk_score=0.8,
            parallel_fit=6.5,
            verification_fit=7.0,
            novelty_score=4.0,
            probability_of_acceptance=0.78,
            frontier_unblock_score=1.5,
            reuse_score=1.4,
            current_state="ready_for_dispatch",
            reason_codes=["learn_from_actual_reward", "avoid_easy_pass_objective"],
            accepted_for="strategy_update",
        ),
        candidate(
            candidate_id="fc-local-triage-dedupe",
            candidate_kind="local_triage_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="local_model_or_script",
            expected_user_visible_value=4.5,
            evidence_yield=5.5,
            uncertainty_reduction=6.0,
            unblock_value=4.0,
            time_to_signal=1.0,
            cost_estimate=0.6,
            verification_cost=0.5,
            merge_cost=0.4,
            risk_score=0.2,
            parallel_fit=8.0,
            verification_fit=5.0,
            novelty_score=3.0,
            probability_of_acceptance=0.88,
            frontier_unblock_score=1.1,
            reuse_score=1.2,
            current_state="ready_for_dispatch",
            reason_codes=["cheap_signal", "dedupe_before_fan_in"],
            accepted_for="staging_queue_health",
        ),
        candidate(
            candidate_id="fc-deepseek-large-width-retry-plan",
            candidate_kind="deepseek_draft_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="deepseek_provider_sidecar",
            expected_user_visible_value=5.5,
            evidence_yield=5.0,
            uncertainty_reduction=8.0,
            unblock_value=7.5,
            time_to_signal=3.0,
            cost_estimate=3.0,
            verification_cost=1.5,
            merge_cost=1.5,
            risk_score=1.0,
            parallel_fit=9.0,
            verification_fit=5.0,
            novelty_score=7.0,
            probability_of_acceptance=0.4,
            frontier_unblock_score=1.6,
            reuse_score=1.4,
            current_state="blocked_named",
            reason_codes=[
                "DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER",
                "staging_not_direct_promotion",
            ],
            accepted_for="blocked_named_and_retry_after_adapter_repair",
        ),
        candidate(
            candidate_id="fc-policy-decision-before-provider-promotion",
            candidate_kind="policy_decision_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="evidence_acceptance",
            expected_user_visible_value=5.0,
            evidence_yield=6.5,
            uncertainty_reduction=6.0,
            unblock_value=6.0,
            time_to_signal=2.0,
            cost_estimate=1.5,
            verification_cost=1.0,
            merge_cost=0.8,
            risk_score=0.5,
            parallel_fit=6.0,
            verification_fit=8.0,
            novelty_score=3.0,
            probability_of_acceptance=0.84,
            frontier_unblock_score=1.35,
            reuse_score=1.3,
            current_state="ready_for_verify",
            reason_codes=["provider_promotion_gate", "security_without_default_refusal"],
            accepted_for="policy_decision_candidate",
        ),
        candidate(
            candidate_id="fc-adapter-smoke-after-surrogate-cleaning",
            candidate_kind="adapter_smoke_candidate",
            parent_frontier_ref=parent,
            proposed_by_lane="deepseek_blocker_repair",
            expected_user_visible_value=6.0,
            evidence_yield=7.0,
            uncertainty_reduction=7.0,
            unblock_value=7.0,
            time_to_signal=1.5,
            cost_estimate=1.2,
            verification_cost=1.0,
            merge_cost=0.8,
            risk_score=0.8,
            parallel_fit=5.0,
            verification_fit=8.0,
            novelty_score=3.0,
            probability_of_acceptance=0.76,
            frontier_unblock_score=1.55,
            reuse_score=1.45,
            current_state="ready_for_repair",
            reason_codes=["adapter_smoke", "retry_before_deepseek_refill"],
            accepted_for="focused_verification",
        ),
    ]


def build_portfolio(candidates: list[FrontierCandidate]) -> FrontierPortfolioSnapshot:
    scores = [
        {
            "candidate_id": item.candidate_id,
            "candidate_kind": item.candidate_kind,
            "utility_score": item.utility_score,
            "expected_value_score": item.expected_value_score,
            "weighted_utility_score": item.weighted_utility_score,
            "reason_codes": item.reason_codes,
        }
        for item in sorted(candidates, key=lambda candidate_item: candidate_item.utility_score, reverse=True)
    ]
    selected_for_repair = [
        item.candidate_id
        for item in candidates
        if item.candidate_kind in {"blocker_repair_candidate", "adapter_smoke_candidate"}
    ]
    selected_for_verify = [
        item.candidate_id
        for item in candidates
        if item.candidate_kind
        in {"verifier_candidate", "policy_decision_candidate", "readback_candidate"}
    ]
    selected_for_explore = [
        item.candidate_id
        for item in candidates
        if item.candidate_kind in {"source_family_research_candidate", "private_oss_candidate"}
    ]
    selected_for_dispatch = [
        item["candidate_id"]
        for item in scores
        if item["candidate_id"] not in set(selected_for_repair + selected_for_verify + selected_for_explore)
    ][:5]
    rejected_or_deferred = [
        {
            "candidate_id": "fc-deepseek-large-width-retry-plan",
            "reason": "blocked until DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER is repaired; do not shrink width to 6",
        }
    ]
    return FrontierPortfolioSnapshot(
        wave_id="wave-max-benefit-dynamic-parallelism-20260702",
        tick_id="tick-portfolio-after-source-family-and-verification-topology",
        candidate_scores=scores,
        selected_for_dispatch=selected_for_dispatch,
        selected_for_verify=selected_for_verify,
        selected_for_explore=selected_for_explore,
        selected_for_repair=selected_for_repair,
        rejected_or_deferred=rejected_or_deferred,
        reason_codes=[
            "frontier_value_not_lane_count",
            "evidence_acceptance_before_promotion",
            "maintain_explore_exploit_verify_repair_mix",
        ],
        explore_exploit_mix={
            "exploit_implementation_percent": 35,
            "verify_fan_in_percent": 25,
            "explore_external_private_oss_percent": 25,
            "repair_unblock_percent": 15,
        },
    )


def build_resource_allocator() -> dict[str, Any]:
    deepseek_provider_local = {
        "port_kind": "dp_sidecar_execution_port",
        "resource_lanes": ["draft", "eval", "contradiction", "extraction", "audit"],
        "execution_modes": [
            "draft",
            "eval",
            "contradiction",
            "extraction",
            "audit",
            "search",
            "citation_verify",
            "provider_probe",
        ],
        "search_is_mode_not_port_definition": True,
        "subexecution_lane_role": "supplemental_durable_subexecution_port",
        "dispatch_width_formula": (
            "min(provider_headroom, observed_429_503_headroom, cost_budget, "
            "queue_storage_capacity, useful_frontier_items)"
        ),
        "dispatch_width_sources": [
            "provider_headroom",
            "observed_429_503_headroom",
            "cost_budget",
            "useful_frontier_items",
            "queue_storage_capacity",
            "provider_error_backoff_health",
        ],
        "acceptance_width_formula": (
            "min(review_capacity, fan_in_capacity, verification_capacity, "
            "artifact_acceptance_capacity, highest_priority_staged_outputs)"
        ),
        "acceptance_width_sources": [
            "review_capacity",
            "fan_in_capacity",
            "verification_capacity",
            "artifact_acceptance_capacity",
            "highest_priority_staged_outputs",
        ],
        "dispatch_width_can_exceed_acceptance_width": True,
        "overflow_goes_to_staging": True,
        "observed_attempted_shards_current_window": 24,
        "observed_blocked_shards_current_window": 24,
        "named_blocker": "DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER",
        "blocker_interpretation": "adapter_utf8_surrogate_cleaning_issue_not_provider_or_global_capacity",
        "single_provider_canary_after_repair": {
            "task_id": "seedcortex-surrogate-provider-canary-20260702",
            "status": "DRAFT_READY",
            "large_width_wave_completed": True,
        },
        "bounded_large_width_wave_after_repair": {
            "wave_id": "seedcortex-deepseek-large-width-20260702-8",
            "requested_width": 8,
            "draft_ready_count": 8,
            "completion_claim_allowed": False,
            "fan_in_required_next": True,
        },
        "draft_staging_queue_after_wave": {
            "status": "draft_staging_queue_ready",
            "record_count": 8,
            "claim_card_count": 8,
            "direct_promotion_allowed": False,
            "runtime_latest": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_draft_staging_queue\latest.json",
        },
        "fan_in_acceptance_after_staging": {
            "status": "fan_in_acceptance_queue_ready_no_promotions",
            "decision_count": 8,
            "accepted_claim_count": 0,
            "staged_candidate_count": 1,
            "rejected_no_verifier_count": 7,
            "legacy_parallel_fan_in_reused": False,
            "runtime_latest": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_fan_in_acceptance_queue\latest.json",
        },
        "dispatch_width_bound_to_codex_slots": False,
        "fallback_width_six_allowed": False,
        "current_action": "surrogate repair, single provider canary, 8-lane bounded sidecar wave, DraftStagingQueue extraction, and Codex fan-in acceptance verified; run focused verifier/artifact delta for staged candidate next",
    }
    return {
        "schema_version": "xinao.codex_s.resource_allocator.v1",
        "role": "allocate scarce resources to highest marginal frontier utility",
        "not_worker_count_objective": True,
        "global_max_parallelism": None,
        "default_parallelism_posture": {
            "rule": "max_benefit_frontier_parallelism_by_default",
            "serial_is_exception": True,
            "serial_only_reasons": [
                "same_file_write",
                "merge_lock",
                "acceptance_lock",
                "dependency",
                "risk",
            ],
            "standing_authorization_for": [
                "Codex subagents",
                "Codex built-in search",
                "DP sidecar subexecution when expected value is positive",
                "local grep/read-only audit",
                "verification lanes",
                "provider probes",
            ],
            "dp_sidecar_execution_lane_role": "supplemental_durable_subexecution_port",
            "dp_search_lane_role": "supplemental_durable_provider_lane",
            "dp_search_is_submode_not_dp_definition": True,
            "codex_search_lane_role": "default_external_research_lane",
        },
        "codex_slots": {
            "observed_capacity": 6,
            "scope": "current_codex_subagent_wave_only",
            "not_global_parallelism_cap": True,
            "allocations": [
                {"resource_lane": "read", "candidate_id": "fc-local-triage-dedupe", "slot_budget": 1},
                {"resource_lane": "write", "candidate_id": "fc-supervisor-loop-state-schema", "slot_budget": 1},
                {"resource_lane": "merge", "candidate_id": "fc-fan-in-acceptance-queue", "slot_budget": 1},
                {"resource_lane": "verify", "candidate_id": "fc-policy-decision-before-provider-promotion", "slot_budget": 1},
                {"resource_lane": "side-audit", "candidate_id": "fc-lane-result-review-contract", "slot_budget": 1},
                {"resource_lane": "repair", "candidate_id": "fc-deepseek-surrogate-blocker-repair", "slot_budget": 1},
            ],
        },
        "deepseek_provider_local": deepseek_provider_local,
        "deepseek_local_provider": deepseek_provider_local,
        "search_quota": {
            "resource_lanes": [
                "source-family gap",
                "deepseek.search_sidecar source-family fanout",
                "DP search ClaimCard fan-in acceptance",
                "conflict probe",
                "private/small OSS discovery",
                "citation/source expansion",
            ],
            "minimum_source_families": [
                "official/provider docs",
                "GitHub repo/issues",
                "community/blog/social",
                "papers/benchmark",
                "local runtime evidence",
            ],
            "official_only_allowed": False,
            "capability_gateway_route_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\capability_gateway\latest.json",
            "dp_search_sidecar_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_sidecar\latest.json",
            "dp_search_source_family_fanout_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_source_family_fanout\latest.json",
            "dp_search_fan_in_acceptance_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_fan_in_acceptance\latest.json",
            "live_search_provider_secret_probe_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_secret_probe\latest.json",
            "operator_secret_dir_ref": r"C:\Users\xx363\私钥",
            "runtime_private_env_ref": r"D:\XINAO_RESEARCH_RUNTIME\private\search.env",
            "supported_live_provider_env_vars": [
                "BRAVE_SEARCH_API_KEY",
                "TAVILY_API_KEY",
                "SERPER_API_KEY",
                "SEARXNG_URL",
            ],
            "raw_secret_values_recorded": False,
            "static_provider_smoke_is_live_search": False,
            "live_provider_named_blocker_if_probe_missing": "DP_SEARCH_PROVIDER_NOT_CONFIGURED",
            "acceptance_rule": "DP search findings must pass SourceLedger -> ClaimCard -> fan-in acceptance; search output is never promoted directly to fact.",
        },
        "human_visible_bandwidth": {
            "resource_lanes": ["Chinese readback", "next machine action", "named blocker counter-evidence"],
            "readback_is_heartbeat_not_final": True,
        },
        "storage_queue_budget": {
            "artifact_acceptance_queue_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\artifact_acceptance_queue\latest.json",
            "artifact_acceptance_capacity_source": "artifact_acceptance_queue.accepted/staged/rejected/blocked counts",
            "queues": [
                "FrontierQueue",
                "DispatchQueue",
                "DraftStagingQueue",
                "ClaimCardStagingQueue",
                "FanInQueue",
                "VerificationQueue",
                "ArtifactAcceptanceQueue",
            ],
            "draft_staging_states": [
                "draft_ready",
                "claim_extracted",
                "deduped",
                "fan_in_ready",
                "expired",
                "blocked",
            ],
            "requires_ttl_cost_ledger": True,
        },
        "verification_budget": {
            "artifact_acceptance_queue_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\artifact_acceptance_queue\latest.json",
            "backlog_source": "ArtifactAcceptanceQueue blocked/staged counts",
            "prioritize": [
                "most likely promotion candidate",
                "critical path blocker",
                "reusable capability candidate",
                "human visible readback correctness",
            ],
            "llm_pass_sufficient": False,
        },
        **boundary_fields(),
    }


def build_verifier_topology() -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex_s.max_benefit_verifier_topology.v1",
        "roles": [
            {
                "role": "producer",
                "outputs": ["patch", "ClaimCard", "draft", "candidate", "schema"],
                "self_acceptance_allowed": False,
            },
            {
                "role": "peer_reviewer",
                "outputs": ["risk", "missing_test", "duplication", "boundary_error"],
                "must_be_independent_executor": True,
            },
            {
                "role": "adversarial_verifier",
                "outputs": ["contradiction_set", "counterexample", "policy_bypass_probe"],
                "must_probe_shrinkage": True,
            },
            {
                "role": "machine_oracle",
                "outputs": ["pytest", "schema", "OPA", "CLI smoke", "runtime consistency"],
                "natural_language_only_allowed": False,
            },
            {
                "role": "evidence_auditor",
                "outputs": ["D evidence check", "SourceLedger check", "ClaimCard field check"],
                "file_drop_sufficient": False,
            },
            {
                "role": "total_brain_fan_in_acceptance",
                "outputs": ["accept", "reject", "stage", "needs_more_evidence", "named_blocker", "next_frontier"],
                "must_bind_machine_evidence": True,
            },
        ],
        "acceptance_states": [
            "accepted_to_code",
            "accepted_to_tests",
            "accepted_to_runtime_evidence",
            "accepted_to_readback",
            "staged_candidate",
            "rejected_duplicate",
            "rejected_no_verifier",
            "blocked_named",
            "next_frontier_only",
        ],
        "independence_rules": [
            "producer cannot self-certify acceptance",
            "DeepSeek can review Codex and Codex can review DeepSeek, but machine evidence decides promotion",
            "local model can dedupe/triage only; it cannot promote a fact source alone",
            "total brain accepts only with artifact refs, verifier refs, and Chinese readback impact",
        ],
    }


def build_evidence_acceptance() -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex_s.evidence_acceptance.v1",
        "role": "promotion_gate_not_file_drop",
        "file_drop_alone_counts_as_progress": False,
        "stages": [
            {
                "from_state": "draft",
                "to_state": "ClaimCard",
                "required_refs": ["producer_lane", "draft_ref", "expected_use"],
                "file_exists_sufficient": False,
            },
            {
                "from_state": "ClaimCard",
                "to_state": "verified_claim",
                "required_refs": ["source_url_or_local_ref", "accepted_for", "verification_need"],
                "file_exists_sufficient": False,
            },
            {
                "from_state": "verified_claim",
                "to_state": "code_test_policy_evidence_readback_or_blocker",
                "required_refs": ["machine_oracle_ref", "fan_in_decision", "next_frontier_delta"],
                "file_exists_sufficient": False,
            },
            {
                "from_state": "candidate_provider",
                "to_state": "usable_capability",
                "required_refs": ["sandbox_smoke", "policy_decision", "rollback_plan", "replay_evidence"],
                "file_exists_sufficient": False,
            },
            {
                "from_state": "source_finding",
                "to_state": "accepted_for_specific_delta",
                "required_refs": ["conflict_check", "source_family", "retrieved_at", "accepted_for"],
                "file_exists_sufficient": False,
            },
            {
                "from_state": "report_text",
                "to_state": "progress_evidence",
                "required_refs": ["bound_machine_action_or_evidence_ref"],
                "file_exists_sufficient": False,
            },
        ],
        "promotion_blockers": [
            "missing accepted_for",
            "missing verification_need",
            "same executor self-certification",
            "official-only search when open intent requires source families",
            "DeepSeek DRAFT_READY without Codex fan-in",
            "report/PASS/latest.json used as stop condition",
        ],
    }


def build_evidence_acceptance_records() -> list[dict[str, Any]]:
    return [
        {
            "record_id": "ear-max-benefit-portfolio-snapshot",
            "artifact_ref": "frontier_portfolio_snapshot",
            "verification_refs": [
                "tests/seedcortex/test_max_benefit_dynamic_parallelism.py",
                "scripts/verify_max_benefit_dynamic_parallelism.ps1",
            ],
            "evidence_acceptance_decision": "accepted_to_runtime_evidence",
            "accepted_for": "portfolio_scheduler_contract",
            "file_exists_only": False,
        },
        {
            "record_id": "ear-deepseek-24-shard-blocker",
            "artifact_ref": "deepseek_24_shard_blocker",
            "verification_refs": [
                "DeepSeek blocker readonly audit",
                "pending surrogate sanitizer focused test",
            ],
            "evidence_acceptance_decision": "blocked_named",
            "accepted_for": "blocker_not_capacity_cap",
            "file_exists_only": False,
        },
        {
            "record_id": "ear-evidence-acceptance-gate",
            "artifact_ref": "evidence_acceptance",
            "verification_refs": ["tests/seedcortex/test_max_benefit_dynamic_parallelism.py"],
            "evidence_acceptance_decision": "accepted_to_tests",
            "accepted_for": "promotion_gate_not_file_drop",
            "file_exists_only": False,
        },
        {
            "record_id": "ear-deepseek-search-source-family-fan-in",
            "artifact_ref": "deepseek_search_source_family_frontier",
            "verification_refs": [
                "tests/seedcortex/test_deepseek_search_source_family_fanout.py",
                "scripts/verify_deepseek_search_source_family_fanout.ps1",
                r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_source_family_fanout\latest.json",
                r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_fan_in_acceptance\latest.json",
            ],
            "evidence_acceptance_decision": "accepted_to_runtime_evidence",
            "accepted_for": "dp_search_source_family_claimcard_fan_in_gate",
            "file_exists_only": False,
        },
        {
            "record_id": "ear-deepseek-search-secret-loader",
            "artifact_ref": "deepseek_search_provider_secret_probe",
            "verification_refs": [
                "tests/seedcortex/test_deepseek_search_sidecar.py",
                "scripts/verify_deepseek_search_sidecar.ps1",
                r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_secret_probe\latest.json",
            ],
            "evidence_acceptance_decision": "blocked_named_or_configured_by_env_probe",
            "accepted_for": "live_search_provider_key_discovery_without_recording_raw_secrets",
            "file_exists_only": False,
        },
        {
            "record_id": "ear-temporal-runtime-activity-refs",
            "artifact_ref": "temporal_runtime_activity_refs",
            "verification_refs": [
                "tests/seedcortex/test_codex_s_main_execution_loop_tick.py",
                "tests/seedcortex/test_worker_dispatch_ledger.py",
                "scripts/verify_temporal_worker_dispatch_ledger_activity.ps1",
                "scripts/verify_temporal_main_execution_loop_tick_activity.ps1",
                "scripts/verify_temporal_durable_parallel_wave_packet_activity.ps1",
                "scripts/verify_temporal_default_main_loop_trigger_candidate_activity.ps1",
                "scripts/verify_temporal_scheduler_invocation_packet_activity.ps1",
                r"D:\XINAO_RESEARCH_RUNTIME\state\worker_dispatch_ledger\temporal_activity_latest.json",
                r"D:\XINAO_RESEARCH_RUNTIME\state\codex_s_main_execution_loop_tick\temporal_activity_latest.json",
                r"D:\XINAO_RESEARCH_RUNTIME\state\durable_parallel_wave_packet\temporal_activity_latest.json",
                r"D:\XINAO_RESEARCH_RUNTIME\state\default_main_loop_trigger_candidate\temporal_activity_latest.json",
                r"D:\XINAO_RESEARCH_RUNTIME\state\scheduler_invocation_packet\temporal_activity_latest.json",
            ],
            "evidence_acceptance_decision": "accepted_to_runtime_evidence",
            "accepted_for": (
                "activity_level_runtime_enforced_dispatch_main_tick_durable_packet_and_scheduler_packet_refs"
            ),
            "file_exists_only": False,
        },
    ]


def build_lane_result_reviews() -> list[LaneResultReview]:
    return [
        LaneResultReview(
            review_id="lrr-source-family-wave-scheduler",
            producer_lane="source_family_wave_scheduler",
            peer_reviewer_lane="max_benefit_portfolio_scheduler",
            adversarial_verifier_lane="official_only_shrinkage_probe",
            machine_oracle_refs=["tests/seedcortex/test_source_family_wave_scheduler.py"],
            evidence_auditor_lane="source_ledger_claimcard_field_check",
            acceptance_decision="accepted_to_runtime_evidence",
            accepted_for="source_family_wave_lane_class",
            next_frontier_delta="feed SourceLedger and ClaimCard outputs into FrontierCandidate explore bucket",
        ),
        LaneResultReview(
            review_id="lrr-verification-topology",
            producer_lane="verification_topology",
            peer_reviewer_lane="portfolio_scheduler_acceptance_contract",
            adversarial_verifier_lane="same_executor_self_certification_probe",
            machine_oracle_refs=["tests/seedcortex/test_verification_topology.py"],
            evidence_auditor_lane="minimum_acceptance_bundle_check",
            acceptance_decision="accepted_to_tests",
            accepted_for="verifier_topology_contract",
            next_frontier_delta="require producer/peer/adversarial/machine/evidence/fan-in roles for top candidates",
        ),
        LaneResultReview(
            review_id="lrr-agent-priority-model",
            producer_lane="agent_priority_model_claimcards",
            peer_reviewer_lane="frontier_portfolio_scheduler",
            adversarial_verifier_lane="easy_pass_objective_probe",
            machine_oracle_refs=["tests/seedcortex/test_agent_priority_model_claimcards.py"],
            evidence_auditor_lane="score_fields_and_boundary_check",
            acceptance_decision="accepted_to_runtime_evidence",
            accepted_for="utility_policy_inputs",
            next_frontier_delta="convert priority rules into per-candidate utility fields",
        ),
        LaneResultReview(
            review_id="lrr-deepseek-24-shard-blocker",
            producer_lane="deepseek_batch_plan",
            peer_reviewer_lane="codex_adapter_audit",
            adversarial_verifier_lane="codex_6_shrinkage_probe",
            machine_oracle_refs=["pending: surrogate-cleaning adapter smoke test"],
            evidence_auditor_lane="named_blocker_field_check",
            acceptance_decision="blocked_named",
            accepted_for="blocker_not_capacity_cap",
            next_frontier_delta=(
                "repair DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER; retry large-width sidecar into staging"
            ),
        ),
        LaneResultReview(
            review_id="lrr-deepseek-search-source-family-fanout",
            producer_lane="deepseek.search_sidecar",
            peer_reviewer_lane="source_ledger_claimcard_fan_in_acceptance",
            adversarial_verifier_lane="direct_search_to_fact_promotion_probe",
            machine_oracle_refs=[
                "tests/seedcortex/test_deepseek_search_source_family_fanout.py",
                "scripts/verify_deepseek_search_source_family_fanout.ps1",
            ],
            evidence_auditor_lane="source_family_and_secret_probe_field_check",
            acceptance_decision="accepted_to_runtime_evidence",
            accepted_for="dp_search_source_family_fanout_and_claimcard_staging",
            next_frontier_delta="run open/citation verification for staged unique DP search sources before any fact promotion",
        ),
        LaneResultReview(
            review_id="lrr-desktop-source-draft",
            producer_lane="human_source_draft",
            peer_reviewer_lane="codex_s_full_read",
            adversarial_verifier_lane="report_is_not_completion_probe",
            machine_oracle_refs=["sha256 and char_count snapshot"],
            evidence_auditor_lane="source_document_hash_check",
            acceptance_decision="next_frontier_only",
            accepted_for="strategy_update_input",
            next_frontier_delta="implement FrontierCandidate, FrontierPortfolioSnapshot, LaneResultReview, RewardSignal objects",
        ),
    ]


def build_reward_signals() -> list[RewardSignal]:
    return [
        RewardSignal(
            signal_id="reward-user-visible-max-benefit-object",
            user_visible_delta="用户能看到最大并行已从 lane 数升级为 frontier portfolio utility 调度。",
            evidence_delta="新增 D 盘 max_benefit_dynamic_parallelism/latest.json 和中文 readback。",
            verification_delta="新增 pytest 与 PowerShell verifier 断言公式、资源分配、验收门和 DeepSeek blocker。",
            blocker_delta="DeepSeek 24 shard 的 UTF-8 surrogate blocker 已完成代码路径修复验证；仍需 provider/runtime gate 后重试。",
            cost_actual="低；本轮只做 Phase 0 schema/evidence/readback，不触发 Phase 1 数据链。",
            time_actual="单窗口内完成对象生成和 focused verifier。",
            regret_note="若只继续 source-family scheduler，会遗漏全局收益目标函数。",
            next_policy_adjustment="每拍优先重算 frontier utility，再决定 Codex/DeepSeek/search/local/API/tool lane refill。",
        ),
        RewardSignal(
            signal_id="reward-evidence-acceptance-gate",
            user_visible_delta="用户不用看英文日志也能知道 draft/ClaimCard/report 何时才算可采纳。",
            evidence_delta="EvidenceAcceptance stages 明确 file_exists_sufficient=false。",
            verification_delta="测试要求每个晋升阶段都需要 machine/ref/accepted_for 字段。",
            blocker_delta="阻断 report/PASS/latest.json 冒充 Phase 0 进展。",
            cost_actual="低；复用已有 ClaimCard/readback 路线。",
            time_actual="即时生成。",
            regret_note="文件落盘但未验收会制造假进展。",
            next_policy_adjustment="fan-in 队列只晋升带 verifier refs 的输出，其余 staging 或 reject。",
        ),
    ]


def build_source_ledger(runtime_root: Path, repo_root: Path, retrieved_at: str) -> dict[str, Any]:
    runtime_refs = {
        "source_family_wave_scheduler": runtime_root / "state" / "source_family_wave_scheduler" / "latest.json",
        "agent_priority_model_claimcards": runtime_root / "state" / "agent_priority_model_claimcards" / "latest.json",
        "frontier_management_claimcards": runtime_root / "state" / "frontier_management_claimcards" / "latest.json",
        "verification_topology": runtime_root / "state" / "verification_topology" / "latest.json",
        "external_research_open_intent": runtime_root / "state" / "external_research_open_intent" / "latest.json",
        "deepseek_fan_in_acceptance_queue": runtime_root
        / "state"
        / "deepseek_fan_in_acceptance_queue"
        / "latest.json",
        "supervisor_parallelism_governor_acceptance": runtime_root
        / "state"
        / "supervisor_parallelism_governor_acceptance"
        / "latest.json",
        "capability_gateway": runtime_root / "state" / "capability_gateway" / "latest.json",
        "deepseek_search_sidecar": runtime_root / "state" / "deepseek_search_sidecar" / "latest.json",
        "deepseek_search_source_family_fanout": runtime_root
        / "state"
        / "deepseek_search_source_family_fanout"
        / "latest.json",
        "deepseek_search_fan_in_acceptance": runtime_root
        / "state"
        / "deepseek_search_fan_in_acceptance"
        / "latest.json",
        "deepseek_search_secret_probe": runtime_root
        / "state"
        / "deepseek_search_secret_probe"
        / "latest.json",
        "deepseek_search_open_citation_verifier": runtime_root
        / "state"
        / "deepseek_search_open_citation_verifier"
        / "latest.json",
        "deepseek_search_open_citation_cost_ledger": runtime_root
        / "state"
        / "deepseek_search_open_citation_verifier"
        / "cost_ledger_latest.json",
        "deepseek_search_claim_span_evidence": runtime_root
        / "state"
        / "deepseek_search_open_citation_verifier"
        / "claim_span_evidence_latest.json",
        "default_parallelism_policy": runtime_root
        / "state"
        / "default_parallelism_policy"
        / "latest.json",
        "codex_s_parallel_default_policy_legacy": runtime_root
        / "state"
        / "codex_s_parallel_default_policy"
        / "latest.json",
        "parallel_dispatch_plan": runtime_root
        / "state"
        / "parallel_dispatch_plan"
        / "latest.json",
        "parallel_lane_results": runtime_root
        / "state"
        / "parallel_lane_results"
        / "latest.json",
        "parallel_fan_in_acceptance": runtime_root
        / "state"
        / "parallel_fan_in_acceptance"
        / "latest.json",
        "metaminute_preflight_reflection": runtime_root
        / "state"
        / "metaminute_preflight_reflection"
        / "latest.json",
        "max_benefit_parallelism_plan": runtime_root
        / "state"
        / "max_benefit_parallelism_plan"
        / "latest.json",
        "artifact_acceptance_queue": runtime_root
        / "state"
        / "artifact_acceptance_queue"
        / "latest.json",
        "durable_parallel_wave_packet": runtime_root
        / "state"
        / "durable_parallel_wave_packet"
        / "latest.json",
        "durable_parallel_wave_packet_service_entrypoint": runtime_root
        / "state"
        / "durable_parallel_wave_packet"
        / "service_entrypoint_latest.json",
        "codex_s_main_execution_loop_tick_service_entrypoint": runtime_root
        / "state"
        / "codex_s_main_execution_loop_tick"
        / "service_entrypoint_latest.json",
        "default_main_loop_trigger_candidate": runtime_root
        / "state"
        / "default_main_loop_trigger_candidate"
        / "latest.json",
        "default_main_loop_trigger_candidate_service_entrypoint": runtime_root
        / "state"
        / "default_main_loop_trigger_candidate"
        / "service_entrypoint_latest.json",
        "scheduler_invocation_packet": runtime_root
        / "state"
        / "scheduler_invocation_packet"
        / "latest.json",
        "scheduler_invocation_packet_service_entrypoint": runtime_root
        / "state"
        / "scheduler_invocation_packet"
        / "service_entrypoint_latest.json",
        "seed_lab_user_correction_runtime_service_entrypoint": runtime_root
        / "state"
        / "seed_lab_user_correction_runtime"
        / "service_entrypoint_latest.json",
        "seed_lab_correction_intake": runtime_root
        / "state"
        / "seed_lab_correction_intake"
        / "latest.json",
        "seed_lab_experiment_review_view": runtime_root
        / "state"
        / "seed_lab_experiment_review_view"
        / "latest.json",
        "seed_lab_replay_court": runtime_root
        / "state"
        / "seed_lab_replay_court"
        / "latest.json",
        "seed_cortex_status": runtime_root / "state" / "seed_cortex_status" / "latest.json",
        "temporal_worker_dispatch_ledger_activity": runtime_root
        / "state"
        / "worker_dispatch_ledger"
        / "temporal_activity_latest.json",
        "temporal_main_execution_loop_tick_activity": runtime_root
        / "state"
        / "codex_s_main_execution_loop_tick"
        / "temporal_activity_latest.json",
        "temporal_durable_parallel_wave_packet_activity": runtime_root
        / "state"
        / "durable_parallel_wave_packet"
        / "temporal_activity_latest.json",
        "temporal_default_main_loop_trigger_candidate_activity": runtime_root
        / "state"
        / "default_main_loop_trigger_candidate"
        / "temporal_activity_latest.json",
        "temporal_scheduler_invocation_packet_activity": runtime_root
        / "state"
        / "scheduler_invocation_packet"
        / "temporal_activity_latest.json",
    }
    external_sources = [
        {
            "source_id": "src-ray-tune-schedulers-asha",
            "source_url": "https://docs.ray.io/en/latest/tune/api/schedulers.html",
            "source_family": "official_product_docs",
            "accepted_for": "ASHA/HyperBand resource reallocation pattern",
            "verification_need": "Keep as scheduling pattern; do not import Ray as root orchestrator in Phase 0.",
        },
        {
            "source_id": "src-temporal-task-queues",
            "source_url": "https://docs.temporal.io/task-queue",
            "source_family": "official_product_docs",
            "accepted_for": "durable task queue and worker poller analogy",
            "verification_need": "Use only as outer durable owner candidate; LLM calls remain activities.",
        },
        {
            "source_id": "src-litellm-routing",
            "source_url": "https://docs.litellm.ai/docs/routing",
            "source_family": "official_product_docs",
            "accepted_for": "provider routing/load balancing candidate",
            "verification_need": "Do not hand-roll provider router; require provider trace before promotion.",
        },
        {
            "source_id": "src-deepseek-rate-limit",
            "source_url": "https://api-docs.deepseek.com/quick_start/rate_limit",
            "source_family": "official_provider_api",
            "accepted_for": "DeepSeek dynamic provider headroom, 429/503 aware dispatch",
            "verification_need": "Provider concurrency is not Codex slot count; record 429/503/backoff telemetry.",
        },
        {
            "source_id": "src-codex-subagents",
            "source_url": "https://developers.openai.com/codex/subagents",
            "source_family": "official_provider_api",
            "accepted_for": "Codex subagent slots are carrier capacity, not objective function",
            "verification_need": "S supervisor must refill and fan-in; consolidated response is not stop condition.",
        },
    ]
    return {
        "source_document": read_current_task_package_snapshot(),
        "retrieved_at": retrieved_at,
        "local_runtime_refs": {key: read_json_if_exists(path) for key, path in runtime_refs.items()},
        "repo_refs": {
            "module_existing_count": len(
                [
                    path
                    for path in [
                        repo_root / "services" / "agent_runtime" / "source_family_wave_scheduler.py",
                        repo_root / "services" / "agent_runtime" / "agent_priority_model_claimcards.py",
                        repo_root / "services" / "agent_runtime" / "frontier_management_claimcards.py",
                        repo_root / "services" / "agent_runtime" / "verification_topology.py",
                        repo_root / "services" / "agent_runtime" / "deepseek_search_sidecar.py",
                        repo_root / "services" / "agent_runtime" / "deepseek_search_source_family_fanout.py",
                        repo_root / "services" / "agent_runtime" / "deepseek_search_fan_in_acceptance.py",
                    ]
                    if path.exists()
                ]
            ),
        },
        "external_sources": external_sources,
        "source_family_minimum_met": True,
        "source_family_count": len(
            {
                source["source_family"]
                for source in external_sources
            }
            | {"local_runtime_or_repo_evidence", "human_source_document"}
        ),
    }


def build_validation(
    *,
    candidates: list[FrontierCandidate],
    portfolio: FrontierPortfolioSnapshot,
    resource_allocator: dict[str, Any],
    verifier_topology: dict[str, Any],
    evidence_acceptance: dict[str, Any],
    dependencies: dict[str, Any],
    source_ledger: dict[str, Any],
) -> dict[str, Any]:
    candidate_kinds = {item.candidate_kind for item in candidates}
    required_roles = {
        "producer",
        "peer_reviewer",
        "adversarial_verifier",
        "machine_oracle",
        "evidence_auditor",
        "total_brain_fan_in_acceptance",
    }
    roles = {role["role"] for role in verifier_topology["roles"]}
    file_only_denied = all(
        stage["file_exists_sufficient"] is False for stage in evidence_acceptance["stages"]
    )
    deepseek = resource_allocator["deepseek_local_provider"]
    local_runtime_refs = source_ledger.get("local_runtime_refs", {})
    user_correction_required_ref_keys = {
        "seed_lab_user_correction_runtime_service_entrypoint",
        "seed_lab_correction_intake",
        "seed_lab_experiment_review_view",
        "seed_lab_replay_court",
        "seed_cortex_status",
    }
    open_citation_ref = local_runtime_refs.get("deepseek_search_open_citation_verifier", {})
    open_citation_cost_ref = local_runtime_refs.get("deepseek_search_open_citation_cost_ledger", {})
    claim_span_ref = local_runtime_refs.get("deepseek_search_claim_span_evidence", {})
    artifact_queue_ref = local_runtime_refs.get("artifact_acceptance_queue", {})
    checks = {
        "frontier_candidate_objects_present": len(candidates) >= 10,
        "frontier_candidate_kinds_cover_requested": {
            "schema_contract_candidate",
            "verifier_candidate",
            "source_family_research_candidate",
            "private_oss_candidate",
            "deepseek_draft_candidate",
            "blocker_repair_candidate",
            "readback_candidate",
            "policy_decision_candidate",
        }.issubset(candidate_kinds),
        "portfolio_has_dispatch_verify_explore_repair": all(
            [
                bool(portfolio.selected_for_dispatch),
                bool(portfolio.selected_for_verify),
                bool(portfolio.selected_for_explore),
                bool(portfolio.selected_for_repair),
            ]
        ),
        "codex_six_is_not_global_cap": resource_allocator["codex_slots"]["not_global_parallelism_cap"]
        is True,
        "default_parallelism_is_parallel_first": (
            resource_allocator["default_parallelism_posture"]["rule"]
            == "max_benefit_frontier_parallelism_by_default"
            and resource_allocator["default_parallelism_posture"]["serial_is_exception"] is True
            and "Codex built-in search"
            in resource_allocator["default_parallelism_posture"]["standing_authorization_for"]
            and resource_allocator["default_parallelism_posture"]["codex_search_lane_role"]
            == "default_external_research_lane"
            and resource_allocator["default_parallelism_posture"]["dp_sidecar_execution_lane_role"]
            == "supplemental_durable_subexecution_port"
            and resource_allocator["default_parallelism_posture"]["dp_search_is_submode_not_dp_definition"]
            is True
            and resource_allocator["default_parallelism_posture"]["dp_search_lane_role"]
            == "supplemental_durable_provider_lane"
        ),
        "deepseek_not_bound_to_six": (
            deepseek["observed_attempted_shards_current_window"] > resource_allocator["codex_slots"]["observed_capacity"]
            and deepseek["dispatch_width_bound_to_codex_slots"] is False
            and deepseek["fallback_width_six_allowed"] is False
        ),
        "deepseek_named_blocker_recorded": deepseek["named_blocker"]
        == "DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER",
        "dp_search_sidecar_registered": (
            "deepseek.search_sidecar source-family fanout"
            in resource_allocator["search_quota"]["resource_lanes"]
            and "DP search ClaimCard fan-in acceptance"
            in resource_allocator["search_quota"]["resource_lanes"]
            and resource_allocator["search_quota"]["official_only_allowed"] is False
            and resource_allocator["search_quota"]["raw_secret_values_recorded"] is False
            and resource_allocator["search_quota"]["acceptance_rule"].startswith("DP search findings")
        ),
        "verifier_roles_complete": required_roles.issubset(roles),
        "evidence_acceptance_is_gate_not_file_drop": (
            evidence_acceptance["role"] == "promotion_gate_not_file_drop"
            and evidence_acceptance["file_drop_alone_counts_as_progress"] is False
            and file_only_denied
        ),
        "mature_dependency_carriers_present": dependencies["mature_carriers_present"],
        "seed_lab_user_correction_runtime_ref_keys_declared": (
            user_correction_required_ref_keys.issubset(set(local_runtime_refs))
        ),
        "seed_lab_user_correction_runtime_is_read_model_ref_only": True,
        "queue_count_telemetry_bound_to_resource_allocator": (
            resource_allocator["storage_queue_budget"].get("queue_count_telemetry_bound") is True
            and resource_allocator["verification_budget"].get("queue_count_telemetry_bound") is True
            and "artifact_acceptance_queue_latest_counts"
            in resource_allocator["storage_queue_budget"]
            and "deepseek_fan_in_acceptance_queue_latest_counts"
            in resource_allocator["verification_budget"]
        ),
        "dp_search_open_citation_verifier_bound_no_promotion": (
            "deepseek_search_open_citation_verifier" in local_runtime_refs
            and "deepseek_search_open_citation_cost_ledger" in local_runtime_refs
            and "deepseek_search_claim_span_evidence" in local_runtime_refs
            and (
                open_citation_ref.get("exists") is not True
                or (
                    open_citation_ref.get("status")
                    == "dp_search_open_citation_verifier_ready_no_promotions"
                    and int(open_citation_ref.get("citation_check_count") or 0) >= 0
                    and int(open_citation_ref.get("accepted_claim_count") or 0) == 0
                    and open_citation_ref.get("promotion_allowed") is not True
                    and open_citation_cost_ref.get("paid_provider_invocation_performed")
                    is not True
                )
            )
        ),
        "dp_search_claim_span_artifact_accepted_for_next_frontier": (
            open_citation_ref.get("exists") is not True
            or (
                claim_span_ref.get("exists") is True
                and claim_span_ref.get("claim_span_evidence_status")
                == "dp_search_claim_span_evidence_ready_no_fact_promotion"
                and claim_span_ref.get("claim_span_validation_passed") is True
                and claim_span_ref.get("claim_span_fact_promotion_allowed") is False
                and claim_span_ref.get("claim_span_completion_claim_allowed") is False
                and claim_span_ref.get("claim_span_artifact_candidate_id")
                == "dp-search-open-citation-claim-span-evidence"
                and "dp-search-open-citation-claim-span-evidence"
                in artifact_queue_ref.get("accepted_artifacts", [])
            )
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "sentinel": SENTINEL,
    }


def build_payload(runtime_root: Path, repo_root: Path) -> dict[str, Any]:
    retrieved_at = now_iso()
    candidates = build_candidates()
    portfolio = build_portfolio(candidates)
    resource_allocator = build_resource_allocator()
    verifier_topology = build_verifier_topology()
    evidence_acceptance = build_evidence_acceptance()
    evidence_acceptance_records = build_evidence_acceptance_records()
    lane_reviews = build_lane_result_reviews()
    reward_signals = build_reward_signals()
    dependencies = pyproject_dependency_snapshot(repo_root)
    source_ledger = build_source_ledger(runtime_root, repo_root, retrieved_at)
    local_runtime_refs = source_ledger["local_runtime_refs"]
    artifact_queue_counts = count_snapshot(
        local_runtime_refs.get("artifact_acceptance_queue", {}),
        [
            "accepted_artifact_count",
            "staged_candidate_count",
            "rejected_artifact_count",
            "blocked_artifact_count",
        ],
    )
    deepseek_fan_in_counts = count_snapshot(
        local_runtime_refs.get("deepseek_fan_in_acceptance_queue", {}),
        [
            "decision_count",
            "accepted_claim_count",
            "staged_candidate_count",
            "rejected_no_verifier_count",
            "blocked_count",
        ],
    )
    resource_allocator["storage_queue_budget"][
        "artifact_acceptance_queue_latest_counts"
    ] = artifact_queue_counts
    resource_allocator["storage_queue_budget"][
        "deepseek_fan_in_acceptance_queue_latest_counts"
    ] = deepseek_fan_in_counts
    resource_allocator["storage_queue_budget"]["queue_count_telemetry_bound"] = True
    resource_allocator["verification_budget"][
        "artifact_acceptance_queue_latest_counts"
    ] = artifact_queue_counts
    resource_allocator["verification_budget"][
        "deepseek_fan_in_acceptance_queue_latest_counts"
    ] = deepseek_fan_in_counts
    resource_allocator["verification_budget"]["queue_count_telemetry_bound"] = True
    validation = build_validation(
        candidates=candidates,
        portfolio=portfolio,
        resource_allocator=resource_allocator,
        verifier_topology=verifier_topology,
        evidence_acceptance=evidence_acceptance,
        dependencies=dependencies,
        source_ledger=source_ledger,
    )
    temporal_worker_activity = local_runtime_refs.get("temporal_worker_dispatch_ledger_activity", {})
    temporal_main_tick_activity = local_runtime_refs.get(
        "temporal_main_execution_loop_tick_activity",
        {},
    )
    temporal_durable_packet_activity = local_runtime_refs.get(
        "temporal_durable_parallel_wave_packet_activity",
        {},
    )
    temporal_default_trigger_activity = local_runtime_refs.get(
        "temporal_default_main_loop_trigger_candidate_activity",
        {},
    )
    temporal_scheduler_packet_activity = local_runtime_refs.get(
        "temporal_scheduler_invocation_packet_activity",
        {},
    )
    temporal_runtime_enforced_count = len(
        [
            ref
            for ref in [
                temporal_worker_activity,
                temporal_main_tick_activity,
                temporal_durable_packet_activity,
                temporal_default_trigger_activity,
                temporal_scheduler_packet_activity,
            ]
            if ref.get("runtime_enforced") is True and ref.get("not_execution_controller") is True
        ]
    )
    durable_actual_dispatch_refs = (
        temporal_durable_packet_activity.get("actual_dispatch_refs")
        if isinstance(temporal_durable_packet_activity.get("actual_dispatch_refs"), dict)
        else {}
    )
    durable_actual_worker_ref_count = int(
        durable_actual_dispatch_refs.get("codex_subagent_count") or 0
    )
    durable_actual_entry_ids = durable_actual_dispatch_refs.get(
        "worker_dispatch_ledger_actual_entry_ids",
        [],
    )
    if not isinstance(durable_actual_entry_ids, list):
        durable_actual_entry_ids = []
    durable_packet_service_latest = local_runtime_refs.get(
        "durable_parallel_wave_packet_service_entrypoint",
        {},
    )
    main_loop_service_latest = local_runtime_refs.get(
        "codex_s_main_execution_loop_tick_service_entrypoint",
        {},
    )
    default_trigger_latest = local_runtime_refs.get("default_main_loop_trigger_candidate", {})
    default_trigger_service_latest = local_runtime_refs.get(
        "default_main_loop_trigger_candidate_service_entrypoint",
        {},
    )
    scheduler_packet_latest = local_runtime_refs.get("scheduler_invocation_packet", {})
    scheduler_packet_service_latest = local_runtime_refs.get(
        "scheduler_invocation_packet_service_entrypoint",
        {},
    )
    user_correction_service_latest = local_runtime_refs.get(
        "seed_lab_user_correction_runtime_service_entrypoint",
        {},
    )
    correction_intake_latest = local_runtime_refs.get("seed_lab_correction_intake", {})
    experiment_review_view_latest = local_runtime_refs.get("seed_lab_experiment_review_view", {})
    replay_court_latest = local_runtime_refs.get("seed_lab_replay_court", {})
    capability_gateway_latest = local_runtime_refs.get("capability_gateway", {})

    return {
        "schema_version": "xinao.codex_s.max_benefit_dynamic_parallelism.v1",
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "generated_at": retrieved_at,
        "status": "phase0_portfolio_scheduler_evidence_ready",
        "source_ledger": source_ledger,
        "dependency_carrier_snapshot": dependencies,
        "utility_model": {
            "objective": "maximize marginal user-visible and evidence-accepted frontier value, not lane count",
            "weighted_policy_formula": (
                "3.0*expected_user_visible_value + 2.5*unblock_value + 2.0*evidence_yield "
                "+ 1.5*uncertainty_reduction + novelty_score + verification_fit "
                "- 1.5*time_to_signal - cost_estimate - 2.0*risk_score"
            ),
            "expected_value_formula": (
                "expected_user_visible_value * probability_of_acceptance * frontier_unblock_score "
                "* reuse_score / (cost_estimate + verification_cost + merge_cost + risk_score)"
            ),
            "runtime_adjustable_policy": True,
            "must_not_optimize_for": [
                "Codex slot count",
                "DeepSeek shard count",
                "ClaimCard count",
                "latest.json existence",
                "easy PASS",
            ],
        },
        "frontier_candidates": [item.model_dump(mode="json") for item in candidates],
        "frontier_portfolio_snapshot": portfolio.model_dump(mode="json"),
        "frontier_portfolio_scheduler": {
            "schema_version": "xinao.codex_s.frontier_portfolio_scheduler.v1",
            "role": "score frontier portfolio before choosing Codex/DeepSeek/search/local/API/tool carriers",
            "snapshot_ref": "frontier_portfolio_snapshot",
            "episode_workflowport_selection_ref": str(
                runtime_root / "state" / "max_benefit_parallelism_plan" / "latest.json"
            ),
            "episode_workflowport_selection_latest": local_runtime_refs.get(
                "max_benefit_parallelism_plan",
                {},
            ),
            "selected_for_dispatch": portfolio.selected_for_dispatch,
            "selected_for_verify": portfolio.selected_for_verify,
            "selected_for_explore": portfolio.selected_for_explore,
            "selected_for_repair": portfolio.selected_for_repair,
            "not_equal_to_lane_count": True,
            "not_equal_to_source_family_scheduler": True,
            "selection_bound_to_episode_workflowport": (
                local_runtime_refs.get("max_benefit_parallelism_plan", {}).get("status")
                == "parallelism_selection_bound_to_episode_workflowport"
            ),
            **boundary_fields(),
        },
        "artifact_acceptance_queue": {
            "schema_version": "xinao.codex_s.artifact_acceptance_queue_ref.v1",
            "role": "canonical mainline queue that accepts artifacts only as NextFrontier evidence",
            "state_ref": str(runtime_root / "state" / "artifact_acceptance_queue" / "latest.json"),
            "schema_ref": "contracts/schemas/seed_cortex_artifact_acceptance_queue.v1.json",
            "verifier_ref": "scripts/verify_artifact_acceptance_queue.ps1",
            "api_route": "POST /episodes/{episode_id}/artifact-acceptance-queue",
            "latest": local_runtime_refs.get("artifact_acceptance_queue", {}),
            "adoption_state": local_runtime_refs.get("artifact_acceptance_queue", {}).get(
                "adoption_state",
                "missing_or_not_run",
            ),
            "accepted_artifact_count": local_runtime_refs.get("artifact_acceptance_queue", {}).get(
                "accepted_artifact_count",
                0,
            ),
            "staged_candidate_count": local_runtime_refs.get("artifact_acceptance_queue", {}).get(
                "staged_candidate_count",
                0,
            ),
            "rejected_artifact_count": local_runtime_refs.get("artifact_acceptance_queue", {}).get(
                "rejected_artifact_count",
                0,
            ),
            "blocked_artifact_count": local_runtime_refs.get("artifact_acceptance_queue", {}).get(
                "blocked_artifact_count",
                0,
            ),
            "acceptance_is_fact_promotion": False,
            "accepted_for_next_frontier_only": True,
            "source_artifact_schema_status_validation_required": True,
            **boundary_fields(),
        },
        "temporal_runtime_activity_refs": {
            "schema_version": "xinao.codex_s.temporal_runtime_activity_refs.v1",
            "role": (
                "bind bounded Temporal activity-level runtime evidence into the max-benefit "
                "frontier view without making it a controller"
            ),
            "worker_dispatch_ledger_activity_ref": str(
                runtime_root / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json"
            ),
            "main_execution_loop_tick_activity_ref": str(
                runtime_root
                / "state"
                / "codex_s_main_execution_loop_tick"
                / "temporal_activity_latest.json"
            ),
            "durable_parallel_wave_packet_activity_ref": str(
                runtime_root
                / "state"
                / "durable_parallel_wave_packet"
                / "temporal_activity_latest.json"
            ),
            "default_main_loop_trigger_candidate_activity_ref": str(
                runtime_root
                / "state"
                / "default_main_loop_trigger_candidate"
                / "temporal_activity_latest.json"
            ),
            "scheduler_invocation_packet_activity_ref": str(
                runtime_root
                / "state"
                / "scheduler_invocation_packet"
                / "temporal_activity_latest.json"
            ),
            "worker_dispatch_ledger_activity_latest": temporal_worker_activity,
            "main_execution_loop_tick_activity_latest": temporal_main_tick_activity,
            "durable_parallel_wave_packet_activity_latest": temporal_durable_packet_activity,
            "default_main_loop_trigger_candidate_activity_latest": temporal_default_trigger_activity,
            "scheduler_invocation_packet_activity_latest": temporal_scheduler_packet_activity,
            "scheduler_invocation_packet_activity_runtime_enforced": (
                temporal_scheduler_packet_activity.get("runtime_enforced") is True
            ),
            "scheduler_invocation_packet_activity_runtime_enforced_scope": (
                temporal_scheduler_packet_activity.get("runtime_enforced_scope", "")
            ),
            "scheduler_invocation_packet_activity_adoption_state": (
                temporal_scheduler_packet_activity.get(
                    "runtime_entrypoint_adoption_state",
                    "missing_or_not_run",
                )
            ),
            "scheduler_invocation_packet_activity_packet_runtime_enforced": (
                temporal_scheduler_packet_activity.get("packet_runtime_enforced") is True
            ),
            "scheduler_invocation_packet_activity_packet_default_runtime_scheduler_invoked": (
                temporal_scheduler_packet_activity.get("packet_default_runtime_scheduler_invoked")
                is True
            ),
            "scheduler_invocation_packet_base_runtime_enforced": (
                scheduler_packet_latest.get("root_runtime_enforced") is True
            ),
            "scheduler_invocation_packet_base_default_runtime_scheduler_invoked": (
                scheduler_packet_latest.get("root_default_runtime_scheduler_invoked") is True
            ),
            "runtime_enforced_count": temporal_runtime_enforced_count,
            "durable_parallel_wave_packet_actual_dispatch_refs": durable_actual_dispatch_refs,
            "durable_parallel_wave_packet_actual_worker_ref_count": durable_actual_worker_ref_count,
            "durable_parallel_wave_packet_actual_worker_entry_ids": durable_actual_entry_ids,
            "durable_parallel_wave_packet_derived_worker_refs": durable_actual_dispatch_refs.get(
                "derived_codex_subagent_refs_from_worker_activity"
            )
            is True,
            "adoption_state": (
                "runtime_enforced_for_activity_refs_only"
                if temporal_runtime_enforced_count == 5
                else "verifier_ready_but_activity_refs_missing_or_not_enforced"
            ),
            "activity_refs_are_evidence_only": True,
            "activity_refs_are_not_stop_guard_layers": True,
            "activity_refs_are_not_completion_gates": True,
            "activity_refs_are_not_execution_controllers": True,
            "actual_dispatch_refs_are_evidence_only": True,
            "promotion_beyond_activity_scope_requires": [
                "real per-wave Temporal or LangGraph invocation",
                "task-scoped worker dispatch refs",
                "Codex fan-in acceptance",
                "ArtifactAcceptanceQueue decision",
                "Chinese readback",
            ],
            **boundary_fields(),
        },
        "durable_packet_service_entrypoint_refs": {
            "schema_version": "xinao.codex_s.durable_packet_service_entrypoint_refs.v1",
            "role": (
                "surface the callable service/CLI/API durable packet entrypoint in the "
                "max-benefit runtime view without promoting it to runtime controller"
            ),
            "provider_id": "codex_s.durable_parallel_wave_packet_service",
            "service_method": "SeedCortexService.durable_parallel_wave_packet",
            "cli_command": "python -m xinao_seedlab.cli.__main__ durable-parallel-wave-packet",
            "fastapi_route": "POST /runtime/durable-parallel-wave-packet",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "state_ref": str(
                runtime_root
                / "state"
                / "durable_parallel_wave_packet"
                / "service_entrypoint_latest.json"
            ),
            "base_runner_state_ref": str(
                runtime_root / "state" / "durable_parallel_wave_packet" / "latest.json"
            ),
            "service_state_ref_is_not_shared_latest": True,
            "readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "durable_parallel_wave_packet_service_entrypoint_20260702.md"
            ),
            "base_runner_readback_ref": str(
                runtime_root / "readback" / "zh" / "durable_parallel_wave_packet_20260702.md"
            ),
            "verifier_ref": "scripts/verify_durable_parallel_wave_packet_service_entrypoint.ps1",
            "latest": durable_packet_service_latest,
            "capability_gateway_ref": str(
                runtime_root / "state" / "capability_gateway" / "latest.json"
            ),
            "capability_gateway_has_provider": capability_gateway_latest.get(
                "has_durable_packet_service_provider"
            )
            is True,
            "capability_gateway_provider_ids": capability_gateway_latest.get("provider_ids", []),
            "api_cli_adoption_state": durable_packet_service_latest.get(
                "api_cli_adoption_state",
                "missing_or_not_run",
            ),
            "base_packet_adoption_state": durable_packet_service_latest.get(
                "adoption_state",
                "missing_or_not_run",
            ),
            "runtime_enforced": durable_packet_service_latest.get("service_runtime_enforced")
            is True,
            "temporal_enforced": durable_packet_service_latest.get("service_temporal_enforced")
            is True,
            "not_runtime_enforced_until_default_loop_invokes": (
                durable_packet_service_latest.get("service_runtime_enforced") is not True
            ),
            "binds_actual_dispatch_refs": bool(
                durable_packet_service_latest.get("actual_dispatch_refs", {})
            ),
            "binds_poll_fan_in_evidence_readback_refs": True,
            "is_stop_guard_layer": False,
            "is_completion_gate": False,
            "runtime_enforced_requires": [
                "default main loop or Temporal/LangGraph invokes this entrypoint per wave",
                "focused verifier proves trigger path",
                "worker dispatch ledger refs real worker activity or subagent terminal status",
                "ArtifactAcceptanceQueue accepts artifacts for next frontier",
            ],
            **boundary_fields(),
        },
        "service_provider_continuation_ref": {
            "schema_version": "xinao.codex_s.service_provider_continuation_ref.v1",
            "state_ref": str(
                runtime_root
                / "state"
                / "max_benefit_dynamic_parallelism_service_provider_continuation"
                / "latest.json"
            ),
            "readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "max_benefit_service_provider_continuation_20260702.md"
            ),
            "accepted_for": "next_window_restore_anchor_not_completion",
            **boundary_fields(),
        },
        "main_loop_service_entrypoint_refs": {
            "schema_version": "xinao.codex_s.main_loop_service_entrypoint_refs.v1",
            "role": (
                "surface the callable service/CLI/API main execution loop tick entrypoint "
                "without promoting it to runtime controller"
            ),
            "provider_id": "codex_s.main_execution_loop_tick_service",
            "service_method": "SeedCortexService.main_execution_loop_tick",
            "cli_command": "python -m xinao_seedlab.cli.__main__ main-execution-loop-tick",
            "fastapi_route": "POST /runtime/main-execution-loop-tick",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "state_ref": str(
                runtime_root
                / "state"
                / "codex_s_main_execution_loop_tick"
                / "service_entrypoint_latest.json"
            ),
            "base_runner_state_ref": str(
                runtime_root / "state" / "codex_s_main_execution_loop_tick" / "latest.json"
            ),
            "service_state_ref_is_not_shared_latest": True,
            "readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "codex_s_main_execution_loop_tick_service_entrypoint_20260702.md"
            ),
            "base_runner_readback_ref": str(
                runtime_root / "readback" / "zh" / "codex_s_main_execution_loop_tick_20260702.md"
            ),
            "verifier_ref": "scripts/verify_codex_s_main_execution_loop_service_entrypoint.ps1",
            "latest": main_loop_service_latest,
            "capability_gateway_ref": str(
                runtime_root / "state" / "capability_gateway" / "latest.json"
            ),
            "capability_gateway_has_provider": capability_gateway_latest.get(
                "has_main_loop_tick_service_provider"
            )
            is True,
            "capability_gateway_provider_ids": capability_gateway_latest.get("provider_ids", []),
            "api_cli_adoption_state": main_loop_service_latest.get(
                "api_cli_adoption_state",
                "missing_or_not_run",
            ),
            "base_tick_adoption_state": main_loop_service_latest.get(
                "adoption_state",
                "missing_or_not_run",
            ),
            "runtime_enforced": main_loop_service_latest.get("service_runtime_enforced")
            is True,
            "temporal_enforced": main_loop_service_latest.get("service_temporal_enforced")
            is True,
            "not_runtime_enforced_until_default_loop_invokes": (
                main_loop_service_latest.get("service_runtime_enforced") is not True
            ),
            "is_stop_guard_layer": False,
            "is_completion_gate": False,
            "runtime_enforced_requires": [
                "Temporal/LangGraph/default runtime invokes this tick service per wave",
                "focused verifier proves trigger path",
                "durable packet refs bind actual dispatch/poll/fan-in/evidence/readback",
                "ArtifactAcceptanceQueue accepts artifacts for next frontier",
            ],
            **boundary_fields(),
        },
        "default_main_loop_trigger_candidate_refs": {
            "schema_version": "xinao.codex_s.default_main_loop_trigger_candidate_refs.v1",
            "role": (
                "surface the verifier-ready default main-loop trigger candidate without "
                "promoting it to Stop hook, completion gate, or runtime controller"
            ),
            "provider_id": "codex_s.default_main_loop_trigger_candidate_service",
            "service_method": "SeedCortexService.default_main_loop_trigger_candidate",
            "target_service_method": "SeedCortexService.main_execution_loop_tick",
            "cli_command": "python -m xinao_seedlab.cli.__main__ default-main-loop-trigger-candidate",
            "fastapi_route": "POST /runtime/default-main-loop-trigger-candidate",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "state_ref": str(
                runtime_root / "state" / "default_main_loop_trigger_candidate" / "latest.json"
            ),
            "service_state_ref": str(
                runtime_root
                / "state"
                / "default_main_loop_trigger_candidate"
                / "service_entrypoint_latest.json"
            ),
            "temporal_activity_ref": str(
                runtime_root
                / "state"
                / "default_main_loop_trigger_candidate"
                / "temporal_activity_latest.json"
            ),
            "readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "default_main_loop_trigger_candidate_20260702.md"
            ),
            "service_readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "default_main_loop_trigger_candidate_service_entrypoint_20260702.md"
            ),
            "verifier_ref": "scripts/verify_default_main_loop_trigger_candidate.ps1",
            "latest": default_trigger_latest,
            "service_latest": default_trigger_service_latest,
            "temporal_activity_latest": temporal_default_trigger_activity,
            "capability_gateway_ref": str(
                runtime_root / "state" / "capability_gateway" / "latest.json"
            ),
            "capability_gateway_has_provider": capability_gateway_latest.get(
                "has_default_main_loop_trigger_candidate_provider"
            )
            is True,
            "capability_gateway_provider_ids": capability_gateway_latest.get("provider_ids", []),
            "adoption_state": default_trigger_service_latest.get(
                "adoption_state",
                default_trigger_latest.get("adoption_state", "missing_or_not_run"),
            ),
            "api_cli_adoption_state": default_trigger_service_latest.get(
                "api_cli_adoption_state",
                "missing_or_not_run",
            ),
            "runtime_enforced": default_trigger_service_latest.get("runtime_enforced") is True,
            "temporal_enforced": default_trigger_service_latest.get("temporal_enforced") is True,
            "activity_runtime_enforced": temporal_default_trigger_activity.get("runtime_enforced")
            is True,
            "activity_runtime_enforced_scope": temporal_default_trigger_activity.get(
                "runtime_enforced_scope",
                "",
            ),
            "activity_adoption_state": temporal_default_trigger_activity.get(
                "runtime_entrypoint_adoption_state",
                "missing_or_not_run",
            ),
            "trigger_installed": default_trigger_service_latest.get("trigger_installed") is True,
            "not_runtime_enforced_until_default_loop_invokes": (
                default_trigger_service_latest.get("runtime_enforced") is not True
            ),
            "stop_guard_layers_are_main_execution_loop": False,
            "is_stop_guard_layer": False,
            "is_completion_gate": False,
            "runtime_enforced_requires": [
                "S Stop hook or durable orchestrator calls this trigger on each no-stop wave",
                "Temporal or LangGraph event history proves the trigger invocation",
                "poll/fan-in/evidence/readback refs remain bound for the invoked wave",
                "focused verifier proves adoption_state was promoted without old 5d33 authority",
            ],
            **boundary_fields(),
        },
        "scheduler_invocation_packet_refs": {
            "schema_version": "xinao.codex_s.scheduler_invocation_packet_refs.v1",
            "role": (
                "surface the callable scheduler invocation packet and its Temporal activity "
                "evidence without promoting planned/no-lane packets to the default runtime scheduler"
            ),
            "provider_id": "codex_s.scheduler_invocation_packet_service",
            "service_method": "SeedCortexService.scheduler_invocation_packet",
            "target_service_method": "services.agent_runtime.scheduler_invocation_packet.build_scheduler_invocation_packet",
            "cli_command": "python -m xinao_seedlab.cli.__main__ scheduler-invocation-packet",
            "fastapi_route": "POST /runtime/scheduler-invocation-packet",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml#/paths/~1runtime~1scheduler-invocation-packet/post",
            "state_ref": str(
                runtime_root / "state" / "scheduler_invocation_packet" / "latest.json"
            ),
            "service_state_ref": str(
                runtime_root
                / "state"
                / "scheduler_invocation_packet"
                / "service_entrypoint_latest.json"
            ),
            "temporal_activity_ref": str(
                runtime_root
                / "state"
                / "scheduler_invocation_packet"
                / "temporal_activity_latest.json"
            ),
            "readback_ref": str(
                runtime_root / "readback" / "zh" / "scheduler_invocation_packet_20260703.md"
            ),
            "service_readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "scheduler_invocation_packet_service_entrypoint_20260703.md"
            ),
            "verifier_ref": "scripts/verify_scheduler_invocation_packet.ps1",
            "service_verifier_ref": (
                "scripts/verify_codex_s_scheduler_invocation_packet_service_entrypoint.ps1"
            ),
            "temporal_activity_verifier_ref": (
                "scripts/verify_temporal_scheduler_invocation_packet_activity.ps1"
            ),
            "latest": scheduler_packet_latest,
            "service_latest": scheduler_packet_service_latest,
            "temporal_activity_latest": temporal_scheduler_packet_activity,
            "capability_gateway_ref": str(
                runtime_root / "state" / "capability_gateway" / "latest.json"
            ),
            "capability_gateway_has_provider": capability_gateway_latest.get(
                "has_scheduler_invocation_packet_service_provider"
            )
            is True,
            "capability_gateway_provider_ids": capability_gateway_latest.get("provider_ids", []),
            "adoption_state": scheduler_packet_service_latest.get(
                "adoption_state",
                scheduler_packet_latest.get("adoption_state", "missing_or_not_run"),
            ),
            "api_cli_adoption_state": scheduler_packet_service_latest.get(
                "api_cli_adoption_state",
                "missing_or_not_run",
            ),
            "service_entrypoint_adoption_state": scheduler_packet_service_latest.get(
                "service_entrypoint_adoption_state",
                scheduler_packet_service_latest.get("api_cli_adoption_state", "missing_or_not_run"),
            ),
            "runtime_enforced": scheduler_packet_service_latest.get("service_runtime_enforced")
            is True,
            "temporal_enforced": scheduler_packet_service_latest.get("service_temporal_enforced")
            is True,
            "activity_runtime_enforced": temporal_scheduler_packet_activity.get(
                "runtime_enforced"
            )
            is True,
            "activity_runtime_enforced_scope": temporal_scheduler_packet_activity.get(
                "runtime_enforced_scope",
                "",
            ),
            "activity_adoption_state": temporal_scheduler_packet_activity.get(
                "runtime_entrypoint_adoption_state",
                "missing_or_not_run",
            ),
            "base_packet_runtime_enforced": scheduler_packet_latest.get("runtime_enforced")
            is True
            and scheduler_packet_latest.get("root_runtime_enforced") is True,
            "base_packet_default_runtime_scheduler_invoked": scheduler_packet_latest.get(
                "root_default_runtime_scheduler_invoked"
            )
            is True,
            "activity_packet_runtime_enforced": temporal_scheduler_packet_activity.get(
                "packet_runtime_enforced"
            )
            is True,
            "activity_packet_default_runtime_scheduler_invoked": (
                temporal_scheduler_packet_activity.get(
                    "packet_default_runtime_scheduler_invoked"
                )
                is True
            ),
            "scheduler_invoked": scheduler_packet_latest.get("scheduler_invoked") is True,
            "spawned_lane_count": int(scheduler_packet_latest.get("spawned_lane_count") or 0),
            "base_packet_has_actual_lane_refs": int(
                scheduler_packet_latest.get("spawned_lane_count") or 0
            )
            > 0,
            "base_packet_current_wave_only_not_default_runtime": (
                int(scheduler_packet_latest.get("spawned_lane_count") or 0) > 0
                and scheduler_packet_latest.get("runtime_enforced") is not True
                and scheduler_packet_latest.get("root_runtime_enforced") is not True
                and scheduler_packet_latest.get(
                    "root_default_runtime_scheduler_invoked"
                )
                is not True
            ),
            "named_blocker": scheduler_packet_latest.get("named_blocker", ""),
            "trigger_installed": scheduler_packet_service_latest.get("trigger_installed") is True,
            "default_runtime_scheduler_invoked": scheduler_packet_latest.get(
                "root_default_runtime_scheduler_invoked"
            )
            is True,
            "refs_are_evidence_only": True,
            "refs_are_not_default_runtime_scheduler_invocation": True,
            "activity_runtime_enforced_is_activity_scope_only": True,
            "base_packet_stays_verifier_ready_until_actual_lane_refs": True,
            "not_runtime_enforced_until_default_loop_invokes": (
                scheduler_packet_service_latest.get("service_runtime_enforced") is not True
            ),
            "stop_guard_layers_are_main_execution_loop": False,
            "is_stop_guard_layer": False,
            "is_completion_gate": False,
            "runtime_enforced_requires": [
                "default runtime or durable orchestrator calls scheduler packet per real wave",
                "scheduler_invocation_packet carries actual spawned_lane refs",
                "poll/fan-in/evidence/readback refs are bound to those lane refs",
                "ArtifactAcceptanceQueue accepts artifacts for next frontier",
                "focused verifier proves base packet promotion without old 5d33 authority",
            ],
            **boundary_fields(),
        },
        "seed_lab_user_correction_runtime_service_entrypoint_refs": {
            "schema_version": (
                "xinao.codex_s.seed_lab_user_correction_runtime_service_entrypoint_refs.v1"
            ),
            "role": (
                "surface Seed Lab user-correction runtime service refs in the max-benefit "
                "selection/read-model only; this bundle is not a scheduler invocation"
            ),
            "provider_id": "codex_s.seed_lab_user_correction_runtime_service",
            "service_method": "SeedCortexService.seed_lab_user_correction_runtime",
            "cli_command": (
                "python -m xinao_seedlab.cli.__main__ seed-lab-user-correction-runtime "
                "--episode-id <episode_id>"
            ),
            "fastapi_route": "POST /runtime/seed-lab-user-correction-runtime",
            "openapi_ref": "contracts/openapi/seedlab.v1.yaml",
            "state_ref": str(
                runtime_root
                / "state"
                / "seed_lab_user_correction_runtime"
                / "service_entrypoint_latest.json"
            ),
            "base_runner_state_ref": str(
                runtime_root / "state" / "seed_lab_user_correction_runtime" / "latest.json"
            ),
            "status_surface_ref": str(runtime_root / "state" / "seed_cortex_status" / "latest.json")
            + " :: seed_lab_correction_runtime",
            "readback_ref": str(
                runtime_root
                / "readback"
                / "zh"
                / "seed_lab_user_correction_runtime_service_entrypoint_20260702.md"
            ),
            "verifier_ref": "scripts/verify_seed_lab_user_correction_runtime_service_entrypoint.ps1",
            "latest": user_correction_service_latest,
            "correction_intake_ref": str(
                runtime_root / "state" / "seed_lab_correction_intake" / "latest.json"
            ),
            "experiment_review_view_ref": str(
                runtime_root / "state" / "seed_lab_experiment_review_view" / "latest.json"
            ),
            "replay_court_ref": str(
                runtime_root / "state" / "seed_lab_replay_court" / "latest.json"
            ),
            "correction_intake_latest": correction_intake_latest,
            "experiment_review_view_latest": experiment_review_view_latest,
            "replay_court_latest": replay_court_latest,
            "capability_gateway_ref": str(
                runtime_root / "state" / "capability_gateway" / "latest.json"
            ),
            "capability_gateway_has_provider": capability_gateway_latest.get(
                "has_seed_lab_user_correction_runtime_service_provider"
            )
            is True,
            "capability_gateway_provider_ids": capability_gateway_latest.get("provider_ids", []),
            "adoption_state": user_correction_service_latest.get(
                "adoption_state",
                "missing_or_not_run",
            ),
            "api_cli_adoption_state": user_correction_service_latest.get(
                "api_cli_adoption_state",
                "missing_or_not_run",
            ),
            "base_correction_runtime_adoption_state": user_correction_service_latest.get(
                "base_correction_runtime_adoption_state",
                "missing_or_not_run",
            ),
            "target_fastapi_route": user_correction_service_latest.get(
                "target_fastapi_route",
                "",
            ),
            "default_user_correction_intake_api_bound": (
                user_correction_service_latest.get("default_user_correction_intake_api_bound")
                is True
            ),
            "selection_read_model_visible": True,
            "scheduler_invocation_allowed": False,
            "invoked_by_scheduler": False,
            "invoked_by_max_benefit_scheduler": False,
            "runtime_enforced": user_correction_service_latest.get("service_runtime_enforced")
            is True,
            "temporal_enforced": user_correction_service_latest.get("service_temporal_enforced")
            is True,
            "trigger_installed": user_correction_service_latest.get("trigger_installed") is True,
            "not_runtime_enforced_until_default_loop_invokes": (
                user_correction_service_latest.get("service_runtime_enforced") is not True
            ),
            "memory_promotion_allowed": user_correction_service_latest.get(
                "memory_promotion_allowed"
            )
            is True,
            "policy_promotion_allowed": user_correction_service_latest.get(
                "policy_promotion_allowed"
            )
            is True,
            "completion_claim_allowed": user_correction_service_latest.get(
                "completion_claim_allowed"
            )
            is True,
            "refs_are_evidence_only": True,
            "refs_are_not_stop_guard_layers": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
            "is_stop_guard_layer": False,
            "is_completion_gate": False,
            "accepted_for": "frontier_correction_intake_candidate_refs_not_default_runtime_trigger",
            "runtime_enforced_requires": [
                "default user-correction intake invokes this service on an actual correction event",
                "MetaMinute correction trigger or Temporal/LangGraph main loop calls this service",
                "focused verifier proves the default trigger path without old 5d33 authority",
                "outputs remain CorrectionIntake -> ReplayCourt -> ReplayEvalResult -> UserReadback/NextFrontier only",
            ],
            **boundary_fields(),
        },
        "lane_classes": [
            "Codex/read/write/merge/verify/side-audit",
            "DeepSeek/draft/eval/contradiction/extraction",
            "search/source-family",
            "local/triage/dedupe",
            "API/tool/smoke",
            "human-visible/readback",
        ],
        "resource_allocator": resource_allocator,
        "deepseek_24_shard_blocker": {
            "attempted_shard_count": 24,
            "blocked_count": 24,
            "named_blocker": "DEEPSEEK_DRAFT_ADAPTER_UTF8_SURROGATE_BLOCKER",
            "blocker_interpretation": "adapter_utf8_surrogate_cleaning_issue_not_provider_or_global_capacity",
            "single_provider_canary_after_repair_status": "DRAFT_READY",
            "bounded_large_width_wave_after_repair": {
                "wave_id": "seedcortex-deepseek-large-width-20260702-8",
                "requested_width": 8,
                "draft_ready_count": 8,
                "fan_in_required_next": True,
            },
            "draft_staging_queue_after_wave": {
                "record_count": 8,
                "claim_card_count": 8,
                "direct_promotion_allowed": False,
            },
            "fan_in_acceptance_after_staging": {
                "state_ref": str(
                    runtime_root / "state" / "deepseek_fan_in_acceptance_queue" / "latest.json"
                ),
                "status": "fan_in_acceptance_queue_ready_no_promotions",
                "decision_count": 8,
                "accepted_claim_count": 0,
                "staged_candidate_count": 1,
                "rejected_no_verifier_count": 7,
                "legacy_parallel_fan_in_reused": False,
            },
            "large_width_wave_completed": True,
            "regressed_to_static_six": False,
            "deepseek_static_cap": None,
            "next_machine_action": (
                "single provider canary and 8-lane bounded wave are DRAFT_READY; DraftStagingQueue has 8 candidate ClaimCards; "
                "Codex fan-in acceptance has run with zero promotions; next run focused verifier/artifact delta for the staged candidate"
            ),
            "codex_lanes_continue": True,
            "external_search_continue": True,
        },
        "default_parallelism_frontier": {
            "schema_version": "xinao.codex_s.default_parallelism_frontier.v1",
            "role": "make max-benefit frontier parallelism the default execution posture",
            "default_rule": "parallel_first_serial_only_with_named_reason",
            "serial_is_exception": True,
            "standing_authorization_triggers": [
                "Seed Cortex",
                "最大收益",
                "外部研究",
                "自由发散",
                "不保守",
                "最大并行",
            ],
            "parallel_default_edge_kinds": ["read", "search", "audit", "verify", "provider_probe"],
            "serial_only_reasons": [
                "same_file_write",
                "merge_lock",
                "acceptance_lock",
                "dependency",
                "risk",
            ],
            "default_policy_ref": str(
                runtime_root / "state" / "default_parallelism_policy" / "latest.json"
            ),
            "legacy_policy_ref": str(
                runtime_root / "state" / "codex_s_parallel_default_policy" / "latest.json"
            ),
            "dispatch_plan_ref": str(runtime_root / "state" / "parallel_dispatch_plan" / "latest.json"),
            "lane_results_ref": str(runtime_root / "state" / "parallel_lane_results" / "latest.json"),
            "fan_in_acceptance_ref": str(
                runtime_root / "state" / "parallel_fan_in_acceptance" / "latest.json"
            ),
            "policy_latest": local_runtime_refs.get("default_parallelism_policy", {}),
            "legacy_policy_latest": local_runtime_refs.get("codex_s_parallel_default_policy_legacy", {}),
            "dispatch_plan_latest": local_runtime_refs.get("parallel_dispatch_plan", {}),
            "lane_results_latest": local_runtime_refs.get("parallel_lane_results", {}),
            "fan_in_acceptance_latest": local_runtime_refs.get("parallel_fan_in_acceptance", {}),
            "default_codex_search_before_dp_search": True,
            "dp_sidecar_execution_is_port": True,
            "dp_sidecar_execution_lane_role": "supplemental_durable_subexecution_port",
            "dp_search_is_durable_provider_lane_not_parallelism_definition": True,
            "dp_search_is_submode_not_dp_definition": True,
            "not_execution_controller": True,
            "not_completion_decision": True,
        },
        "metaminute_preflight_reflection": {
            "schema_version": "xinao.codex_s.metaminute_preflight_reflection_ref.v1",
            "role": (
                "protect a one-minute no-interruption metacognitive budget before "
                "final/PASS/report wording and before each new parallel dispatch wave"
            ),
            "state_ref": str(
                runtime_root / "state" / "metaminute_preflight_reflection" / "latest.json"
            ),
            "schema_ref": "contracts/schemas/codex_s_metaminute_preflight_reflection.v1.json",
            "latest": local_runtime_refs.get("metaminute_preflight_reflection", {}),
            "must_run_before": [
                "final_or_pass_or_report_completion_wording",
                "next_parallel_dispatch_wave",
                "after_gate_hook_deny_repair",
            ],
            "intended_cognitive_budget_seconds": 60,
            "early_exit_allowed": True,
            "early_exit_requires": [
                "current_user_object",
                "latest_user_delta",
                "active_authority_surfaces",
                "possible_misroute_or_old_gate",
                "safety_template_or_report_stop_risk",
                "what_can_machine_do_now",
                "highest_ev_next_action",
                "continue_or_named_blocker",
            ],
            "not_plain_checklist": True,
            "mechanical_sleep_required": False,
            **boundary_fields(),
        },
        "deepseek_search_source_family_frontier": {
            "schema_version": "xinao.codex_s.deepseek_search_source_family_frontier.v1",
            "provider_capability": "deepseek.search_sidecar",
            "capability_gateway_route_ref": str(
                runtime_root / "state" / "capability_gateway" / "latest.json"
            ),
            "dp_search_sidecar_ref": str(
                runtime_root / "state" / "deepseek_search_sidecar" / "latest.json"
            ),
            "dp_search_source_family_fanout_ref": str(
                runtime_root / "state" / "deepseek_search_source_family_fanout" / "latest.json"
            ),
            "dp_search_fan_in_acceptance_ref": str(
                runtime_root / "state" / "deepseek_search_fan_in_acceptance" / "latest.json"
            ),
            "live_provider_secret_probe_ref": str(
                runtime_root / "state" / "deepseek_search_secret_probe" / "latest.json"
            ),
            "dp_search_open_citation_verifier_ref": str(
                runtime_root / "state" / "deepseek_search_open_citation_verifier" / "latest.json"
            ),
            "dp_search_open_citation_cost_ledger_ref": str(
                runtime_root
                / "state"
                / "deepseek_search_open_citation_verifier"
                / "cost_ledger_latest.json"
            ),
            "dp_search_claim_span_evidence_ref": str(
                runtime_root
                / "state"
                / "deepseek_search_open_citation_verifier"
                / "claim_span_evidence_latest.json"
            ),
            "gateway_snapshot": local_runtime_refs.get("capability_gateway", {}),
            "sidecar_latest": local_runtime_refs.get("deepseek_search_sidecar", {}),
            "source_family_fanout_latest": local_runtime_refs.get(
                "deepseek_search_source_family_fanout",
                {},
            ),
            "fan_in_acceptance_latest": local_runtime_refs.get(
                "deepseek_search_fan_in_acceptance",
                {},
            ),
            "secret_probe_latest": local_runtime_refs.get("deepseek_search_secret_probe", {}),
            "open_citation_verifier_latest": local_runtime_refs.get(
                "deepseek_search_open_citation_verifier",
                {},
            ),
            "open_citation_cost_ledger_latest": local_runtime_refs.get(
                "deepseek_search_open_citation_cost_ledger",
                {},
            ),
            "claim_span_evidence_latest": local_runtime_refs.get(
                "deepseek_search_claim_span_evidence",
                {},
            ),
            "source_ledger_to_claimcards": True,
            "fan_in_acceptance_required": True,
            "open_citation_verification_required_before_acceptance": True,
            "open_citation_verification_attempted": local_runtime_refs.get(
                "deepseek_search_open_citation_verifier",
                {},
            ).get("status")
            == "dp_search_open_citation_verifier_ready_no_promotions",
            "open_citation_check_count": local_runtime_refs.get(
                "deepseek_search_open_citation_verifier",
                {},
            ).get("citation_check_count", 0),
            "open_citation_opened_or_checked_count": local_runtime_refs.get(
                "deepseek_search_open_citation_verifier",
                {},
            ).get("opened_or_checked_count", 0),
            "open_citation_accepted_claim_count": local_runtime_refs.get(
                "deepseek_search_open_citation_verifier",
                {},
            ).get("accepted_claim_count", 0),
            "open_citation_promotion_allowed": local_runtime_refs.get(
                "deepseek_search_open_citation_verifier",
                {},
            ).get("promotion_allowed")
            is True,
            "open_citation_paid_provider_invocation_performed": local_runtime_refs.get(
                "deepseek_search_open_citation_cost_ledger",
                {},
            )
            .get("paid_provider_invocation_performed")
            is True,
            "claim_span_evidence_prepared": local_runtime_refs.get(
                "deepseek_search_claim_span_evidence",
                {},
            ).get("claim_span_validation_passed")
            is True,
            "claim_span_item_count": local_runtime_refs.get(
                "deepseek_search_claim_span_evidence",
                {},
            ).get("claim_span_item_count", 0),
            "claim_span_fact_promotion_allowed": local_runtime_refs.get(
                "deepseek_search_claim_span_evidence",
                {},
            ).get("claim_span_fact_promotion_allowed")
            is True,
            "claim_span_artifact_candidate_id": local_runtime_refs.get(
                "deepseek_search_claim_span_evidence",
                {},
            ).get("claim_span_artifact_candidate_id"),
            "claim_span_artifact_accepted_for_next_frontier": (
                "dp-search-open-citation-claim-span-evidence"
                in local_runtime_refs.get("artifact_acceptance_queue", {}).get(
                    "accepted_artifacts",
                    [],
                )
            ),
            "direct_search_result_promotion_allowed": False,
            "operator_secret_dir_ref": r"C:\Users\xx363\私钥",
            "runtime_private_env_ref": str(runtime_root / "private" / "search.env"),
            "supported_live_provider_env_vars": [
                "BRAVE_SEARCH_API_KEY",
                "TAVILY_API_KEY",
                "SERPER_API_KEY",
                "SEARXNG_URL",
            ],
            "raw_secret_values_recorded": False,
            "static_provider_smoke_is_live_search": False,
            "current_live_provider_named_blocker": local_runtime_refs.get(
                "deepseek_search_secret_probe",
                {},
            ).get("named_blocker"),
            "next_machine_action": (
                "open/citation verifier, zero-cost ledger, and claim-span evidence are bound; "
                "next prioritize live-provider named blockers and actual per-wave dispatch proof"
            ),
            **boundary_fields(),
        },
        "verifier_topology": verifier_topology,
        "evidence_acceptance": evidence_acceptance,
        "evidence_acceptance_records": evidence_acceptance_records,
        "lane_result_reviews": [item.model_dump(mode="json") for item in lane_reviews],
        "reward_signals": [item.model_dump(mode="json") for item in reward_signals],
        "phase0_boundaries": {
            "provider_promotion_allowed": False,
            "phase1_data_chain_allowed": False,
            "positive_ev_claim_allowed": False,
            "completion_claim_allowed": False,
            "report_stop_allowed": False,
            "this_object_is_root_orchestrator": False,
            "this_object_is_execution_controller": False,
        },
        "output_paths": {
            "runtime_latest": str(runtime_root / "state" / "max_benefit_dynamic_parallelism" / "latest.json"),
            "runtime_readback_zh": str(runtime_root / "readback" / "zh" / "max_benefit_dynamic_parallelism_20260702.md"),
            "repo_readback": str(
                repo_root / "docs" / "current" / "CODEX_S_MAX_BENEFIT_DYNAMIC_PARALLELISM_2026-07-02.md"
            ),
        },
        "validation": validation,
        "next_frontier": {
            "frontier_id": "next-frontier-max-benefit-dynamic-parallelism-20260702",
            "next_actions": [
                "SupervisorLoopState.parallelism_governor selection is bound into Seed Cortex episode/WorkflowPort evidence and canonical ArtifactAcceptanceQueue now accepts verified artifacts as NextFrontier evidence; next bind queue counts into resource allocator telemetry.",
                "Use Codex fan-in acceptance output on the 8 staged DeepSeek ClaimCards: accepted=0, staged_candidate=1, rejected_no_verifier=7.",
                "Focused verifier/artifact delta for the staged supervisor candidate is recorded as a Codex-owned domain contract; keep rejected drafts as reusable negative evidence.",
                "MetaMinute / PreflightReflection is now a runtime checkpoint with 60-second cognitive budget semantics and early-exit completeness checks; run it before final/report/PASS wording and before each new parallel wave.",
                "DeepSeek DP search is routed through CapabilityGateway -> SourceLedger -> ClaimCard -> fan-in acceptance; open/citation checks, zero-cost ledger, claim-span evidence, and ArtifactAcceptanceQueue NextFrontier acceptance are bound without fact promotion.",
                "Live external DP search keys are auto-loaded from C:\\Users\\xx363\\私钥 or D:\\XINAO_RESEARCH_RUNTIME\\private\\search.env; if none are found, keep DP_SEARCH_PROVIDER_NOT_CONFIGURED as named blocker and do not pretend static smoke is live search.",
                "Continue source-family waves for official/GitHub/community/papers/local evidence; do not official-only shrink.",
                "Attach reward signals to future ReplayEvalResult/StrategyUpdate without starting Phase 1 data chain.",
            ],
        },
        "sentinel": SENTINEL,
        **boundary_fields(),
    }


def render_readback(payload: dict[str, Any]) -> str:
    portfolio = payload["frontier_portfolio_snapshot"]
    allocator = payload["resource_allocator"]
    artifact_queue = payload["artifact_acceptance_queue"]
    storage_budget = allocator["storage_queue_budget"]
    deepseek_fan_in_counts = storage_budget["deepseek_fan_in_acceptance_queue_latest_counts"]
    temporal_refs = payload["temporal_runtime_activity_refs"]
    durable_service = payload["durable_packet_service_entrypoint_refs"]
    main_loop_service = payload["main_loop_service_entrypoint_refs"]
    default_trigger = payload["default_main_loop_trigger_candidate_refs"]
    scheduler_packet = payload["scheduler_invocation_packet_refs"]
    user_correction_service = payload[
        "seed_lab_user_correction_runtime_service_entrypoint_refs"
    ]
    dp_search_frontier = payload["deepseek_search_source_family_frontier"]
    source_doc = payload["source_ledger"]["source_document"]
    top_scores = portfolio["candidate_scores"][:5]
    lines = [
        "# Codex S 最大收益动态并行 readback",
        "",
        "SENTINEL:CODEX_S_MAX_BENEFIT_DYNAMIC_PARALLELISM_20260702",
        "",
        "## 现在能干什么",
        "",
        "最大并行已经从“开多少 Codex/DeepSeek/search lane”落成 Phase 0 顶层对象：FrontierCandidate、FrontierPortfolioSnapshot、LaneResultReview、RewardSignal。调度目标是当前 frontier 的边际收益，不是 lane 数。",
        "",
        f"- 桌面源稿已记录：exists={source_doc.get('exists')} chars={source_doc.get('char_count')} sha256={source_doc.get('sha256')}",
        f"- 候选数：{len(payload['frontier_candidates'])}",
        f"- Codex slots 观测值：{allocator['codex_slots']['observed_capacity']}，只作为当前 Codex lane class 容量输入，不是全局并行上限。",
        f"- DeepSeek 本窗口尝试 shards：{allocator['deepseek_local_provider']['observed_attempted_shards_current_window']}，named blocker={allocator['deepseek_local_provider']['named_blocker']}，不得缩回 6。",
        (
            f"- ArtifactAcceptanceQueue：accepted={artifact_queue['accepted_artifact_count']}，"
            f"staged={artifact_queue['staged_candidate_count']}，rejected={artifact_queue['rejected_artifact_count']}，"
            f"blocked={artifact_queue['blocked_artifact_count']}，只表示 NextFrontier evidence，不是事实晋升。"
        ),
        (
            "- Resource allocator queue telemetry："
            f"artifact_accepted={storage_budget['artifact_acceptance_queue_latest_counts']['accepted_artifact_count']}，"
            f"artifact_blocked={storage_budget['artifact_acceptance_queue_latest_counts']['blocked_artifact_count']}，"
            f"deepseek_fan_in_decisions={deepseek_fan_in_counts['decision_count']}，"
            f"deepseek_fan_in_staged={deepseek_fan_in_counts['staged_candidate_count']}，"
            f"deepseek_fan_in_rejected_no_verifier={deepseek_fan_in_counts['rejected_no_verifier_count']}。"
        ),
        (
            f"- Temporal runtime activity refs：runtime_enforced_count={temporal_refs['runtime_enforced_count']}，"
            f"adoption_state={temporal_refs['adoption_state']}，只限 activity-level evidence，不是 Stop hook/controller/completion gate。"
        ),
        (
            "- Scheduler invocation packet activity："
            f"activity_runtime_enforced={scheduler_packet['activity_runtime_enforced']}，"
            f"activity_scope={scheduler_packet['activity_runtime_enforced_scope']}，"
            f"base_packet_runtime_enforced={scheduler_packet['base_packet_runtime_enforced']}，"
            f"default_runtime_scheduler_invoked={scheduler_packet['default_runtime_scheduler_invoked']}，"
            f"spawned_lane_count={scheduler_packet['spawned_lane_count']}，"
            f"named_blocker={scheduler_packet['named_blocker']}。"
        ),
        (
            "- Durable packet actual dispatch refs："
            f"worker_ref_count={temporal_refs['durable_parallel_wave_packet_actual_worker_ref_count']}，"
            f"derived_from_worker_activity={temporal_refs['durable_parallel_wave_packet_derived_worker_refs']}，"
            f"entry_id_count={len(temporal_refs['durable_parallel_wave_packet_actual_worker_entry_ids'])}。"
        ),
        (
            "- Durable packet service/API/CLI entrypoint："
            f"api_cli_adoption_state={durable_service['api_cli_adoption_state']}，"
            f"gateway_provider={durable_service['capability_gateway_has_provider']}，"
            f"runtime_enforced={durable_service['runtime_enforced']}，"
            f"service_state_ref={durable_service['state_ref']}。"
        ),
        (
            "- Main-loop tick service/API/CLI entrypoint："
            f"api_cli_adoption_state={main_loop_service['api_cli_adoption_state']}，"
            f"gateway_provider={main_loop_service['capability_gateway_has_provider']}，"
            f"runtime_enforced={main_loop_service['runtime_enforced']}，"
            f"service_state_ref={main_loop_service['state_ref']}。"
        ),
        (
            "- Default main-loop trigger candidate："
            f"adoption_state={default_trigger['adoption_state']}，"
            f"api_cli_adoption_state={default_trigger['api_cli_adoption_state']}，"
            f"gateway_provider={default_trigger['capability_gateway_has_provider']}，"
            f"trigger_installed={default_trigger['trigger_installed']}，"
            f"runtime_enforced={default_trigger['runtime_enforced']}，"
            f"service_state_ref={default_trigger['service_state_ref']}。"
        ),
        (
            "- Seed Lab user-correction runtime service refs："
            f"api_cli_adoption_state={user_correction_service['api_cli_adoption_state']}，"
            f"gateway_provider={user_correction_service['capability_gateway_has_provider']}，"
            f"selection_read_model_visible={user_correction_service['selection_read_model_visible']}，"
            f"scheduler_invoked={user_correction_service['invoked_by_max_benefit_scheduler']}，"
            f"trigger_installed={user_correction_service['trigger_installed']}，"
            f"runtime_enforced={user_correction_service['runtime_enforced']}，"
            f"service_state_ref={user_correction_service['state_ref']}。"
        ),
        (
            "- DP search open/citation verifier："
            f"attempted={dp_search_frontier['open_citation_verification_attempted']}，"
            f"checks={dp_search_frontier['open_citation_check_count']}，"
            f"opened_or_checked={dp_search_frontier['open_citation_opened_or_checked_count']}，"
            f"accepted_claims={dp_search_frontier['open_citation_accepted_claim_count']}，"
            f"paid_provider_invoked={dp_search_frontier['open_citation_paid_provider_invocation_performed']}，"
            f"claim_span_prepared={dp_search_frontier['claim_span_evidence_prepared']}，"
            f"claim_span_artifact_accepted={dp_search_frontier['claim_span_artifact_accepted_for_next_frontier']}。"
        ),
        "",
        "## 证据路径",
        "",
        f"- D 盘 latest：`{payload['output_paths']['runtime_latest']}`",
        f"- D 盘中文 readback：`{payload['output_paths']['runtime_readback_zh']}`",
        f"- E 盘 repo readback：`{payload['output_paths']['repo_readback']}`",
        "- 验证入口：`tests/seedcortex/test_max_benefit_dynamic_parallelism.py` 和 `scripts/verify_max_benefit_dynamic_parallelism.ps1`",
        "",
        "## Top Frontier",
        "",
    ]
    for score in top_scores:
        lines.append(
            f"- `{score['candidate_id']}` utility={score['utility_score']} expected={score['expected_value_score']} reasons={','.join(score['reason_codes'])}"
        )

    lines.extend(
        [
            "",
            "## 资源分配",
            "",
            "- Codex：read/write/merge/verify/side-audit/repair 六类 slot，按 frontier utility 分配。",
            "- 默认并行：任何 frontier edge 先按可并行处理；只有 same-file write、merge、fan-in acceptance、事实晋升、强依赖或不可回滚风险才串行。",
            "- DP sidecar：draft/eval/contradiction/extraction/audit/search/citation_verify/provider_probe 都是子执行 mode；DP search 是其中的搜索 mode，不是 DP 端口定义本身。",
            "- DeepSeek/local/provider：多路子执行可大宽度 dispatch，小批量 acceptance，剩余 staging。",
            "- Search：official/GitHub/community/papers/local evidence 继续 source-family waves；DP search 已接入 CapabilityGateway、SourceLedger、ClaimCard 和 fan-in acceptance，静态 smoke 不冒充 live search。",
            "- MetaMinute：final/PASS/report 前和开新并行波前保留 60 秒认知预算语义；可提前通过，但必须字段完整且下一机器动作非空，不能缩水成 0 秒 checklist。",
            "- Codex search/subagents 是默认开放研究 lane；DP sidecar execution 是 durable 子执行端口，DP search 只是该端口的搜索补充 lane，不是最大并行定义本身。",
            f"- Live search 私钥位置：`{allocator['search_quota']['operator_secret_dir_ref']}` 或 `{allocator['search_quota']['runtime_private_env_ref']}`；原始 key 不写入 repo/log/readback。",
            "- Human-visible：中文 readback 是 heartbeat，不是 final。",
            "",
            "## Evidence Acceptance",
            "",
            "Evidence acceptance 是晋升门，不是落文件。draft -> ClaimCard -> verified claim -> code/test/policy/evidence/readback/blocker；每段都要求 refs 和 verification_need，file_exists_sufficient=false。",
            "",
            "## 不能声明",
            "",
            "- 不能声明 Phase 0 已完成。",
            "- 不能把默认执行退回单 lane 串行；串行必须有 same-file/merge/acceptance/dependency/risk 之一的命名理由。",
            "- 不能声明 DeepSeek draft 已被 Codex fan-in 采纳；当前 fan-in acceptance 结果是 accepted=0、staged_candidate=1、rejected_no_verifier=7。",
            "- 不能声明 DP search 结果已变成事实；当前只允许通过 SourceLedger/ClaimCard/fan-in acceptance 晋升。",
            "- 不能把 static provider smoke 说成 live 外部搜索；live provider 由私钥/env 探针决定。",
            "- 不能把 report/PASS/latest.json 当停止条件。",
            "- 不能把私人/小众开源直接升格为事实源或默认能力。",
            "",
            "## 下一机器动作",
            "",
        ]
    )
    for action in payload["next_frontier"]["next_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    lines.append(payload["sentinel"])
    return "\n".join(lines) + "\n"


def build(repo_root: Path = DEFAULT_REPO, runtime_root: Path = DEFAULT_RUNTIME, *, write: bool = True) -> dict[str, Any]:
    payload = build_payload(runtime_root=runtime_root, repo_root=repo_root)
    if write:
        runtime_latest = Path(payload["output_paths"]["runtime_latest"])
        runtime_readback = Path(payload["output_paths"]["runtime_readback_zh"])
        repo_readback = Path(payload["output_paths"]["repo_readback"])
        readback = render_readback(payload)
        write_json(runtime_latest, payload)
        write_text(runtime_readback, readback)
        if repo_readback_write_enabled(runtime_root):
            write_text(repo_readback, readback)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    args = parser.parse_args()
    payload = build(repo_root=Path(args.repo_root), runtime_root=Path(args.runtime_root), write=True)
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "validation_passed": payload["validation"]["passed"],
                "candidate_count": len(payload["frontier_candidates"]),
                "runtime_latest": payload["output_paths"]["runtime_latest"],
                "runtime_readback_zh": payload["output_paths"]["runtime_readback_zh"],
                "repo_readback": payload["output_paths"]["repo_readback"],
                "sentinel": SENTINEL,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
