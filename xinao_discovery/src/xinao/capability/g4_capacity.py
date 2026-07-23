"""Fail-closed G4 route calibration for one bounded batch.

Calibration is deliberately performed on public training cases.  It may measure a
provider route, actual model identity, usage, and wall time, but it never scores a
held-out outcome and can never close G4 by itself. Provider capacity is scoped to
the current batch and never becomes a whole-campaign prerequisite or provider lock.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.capability.phase_conditions import (
    build_phase_control_state,
    execution_directives,
    human_summary_cn,
    legacy_claim_projection,
)

PUBLIC_CASE_KEYS = frozenset(
    {"public_case_id", "public_instructions", "task_input", "commitment_sha256"}
)
FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "answer",
        "answer_key",
        "evaluator_token",
        "family_id",
        "ground_truth",
        "heldout_truth",
        "hidden_parameters",
        "parameters",
        "rejection_label",
        "scorer_credentials",
        "scorer_features",
        "scoring_policy_id",
        "scoring_rule",
        "sealed_answer",
        "seed",
        "split",
        "truth",
        "vault_locator",
        "vault_path",
    }
)
TERMINAL_ROUTE_HOLD = "G4_BOUNDED_FAMILY_ROUTE_HOLD_NO_OUTCOME_ACCESS"
TERMINAL_ROUTE_READY = "G4_BOUNDED_FAMILY_ROUTE_READY_NO_OUTCOME_ACCESS"
# Backward-compatible imports; the old campaign-wide semantics and terminal strings are retired.
TERMINAL_HOLD = TERMINAL_ROUTE_HOLD
TERMINAL_FEASIBLE = TERMINAL_ROUTE_READY


def _canonical_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def raw_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _find_forbidden(value: Any, *, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if normalized in FORBIDDEN_PUBLIC_KEYS:
                findings.append(child_path)
            findings.extend(_find_forbidden(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_forbidden(child, path=f"{path}[{index}]"))
    return findings


def validate_public_case(case: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(case)
    problems: list[str] = []
    if keys != set(PUBLIC_CASE_KEYS):
        problems.append(f"public_case_keys:{sorted(keys)}")
    case_id = case.get("public_case_id")
    commitment = case.get("commitment_sha256")
    if not isinstance(case_id, str) or not case_id:
        problems.append("public_case_id_invalid")
    if (
        not isinstance(commitment, str)
        or len(commitment) != 64
        or any(char not in "0123456789abcdef" for char in commitment)
    ):
        problems.append("commitment_sha256_invalid")
    if not isinstance(case.get("public_instructions"), str):
        problems.append("public_instructions_invalid")
    if not isinstance(case.get("task_input"), Mapping):
        problems.append("task_input_invalid")
    problems.extend(f"forbidden:{path}" for path in _find_forbidden(case))
    return {"ok": not problems, "problems": problems}


def select_size_stratified_cases(
    cases: Sequence[Mapping[str, Any]], *, sample_count: int = 3
) -> list[dict[str, Any]]:
    """Select deterministic low/median/high public payload sizes."""
    if sample_count != 3:
        raise ValueError("capacity calibration requires exactly three size strata")
    prepared: list[tuple[int, str, dict[str, Any]]] = []
    for raw_case in cases:
        case = dict(raw_case)
        validation = validate_public_case(case)
        if validation["ok"] is not True:
            raise ValueError(f"unsafe public case: {validation['problems']}")
        text = _canonical_text(case)
        prepared.append((len(text.encode("utf-8")), str(case["public_case_id"]), case))
    if len(prepared) < sample_count:
        raise ValueError("at least three public cases are required")
    prepared.sort(key=lambda row: (row[0], row[1]))
    indexes = (0, (len(prepared) - 1) // 2, len(prepared) - 1)
    if len(set(indexes)) != sample_count:
        raise ValueError("size strata are not distinct")
    labels = ("low", "median", "high")
    selected: list[dict[str, Any]] = []
    for label, index in zip(labels, indexes, strict=True):
        size, _case_id, case = prepared[index]
        selected.append({"stratum": label, "public_bytes": size, "case": case})
    return selected


def build_subject_prompt(case: Mapping[str, Any], *, subject_configuration: str) -> str:
    validation = validate_public_case(case)
    if validation["ok"] is not True:
        raise ValueError(f"unsafe public case: {validation['problems']}")
    instruction = {
        "role": "public_only_g4_capacity_calibration_subject",
        "subject_configuration": subject_configuration,
        "rules": [
            "Use only the embedded public_case.",
            "Do not claim filesystem, network-tool, evaluator, vault, truth, or score access.",
            "Return exactly one JSON object and no markdown.",
            "Do not self-grade and do not claim G4, admission, or completion.",
        ],
        "required_output": {
            "schema_version": "xinao.g4.capacity.public_subject_output.v1",
            "public_case_id": case["public_case_id"],
            "commitment_sha256": case["commitment_sha256"],
            "subject_configuration": subject_configuration,
            "analysis": "object",
            "self_grade": False,
            "authority": False,
            "completion_claim_allowed": False,
        },
        "public_case": dict(case),
    }
    return _canonical_text(instruction)


def normalize_relay_measurement(
    dispatch: Mapping[str, Any],
    meta: Mapping[str, Any],
    *,
    expected_prompt_sha256: str,
    stratum: str,
    prompt_bytes: int,
    result_hash_readback: bool,
    raw_hash_readback: bool,
) -> dict[str, Any]:
    problems: list[str] = []
    workers = dispatch.get("workers")
    worker = workers[0] if isinstance(workers, list) and len(workers) == 1 else {}
    usage = meta.get("usage") if isinstance(meta.get("usage"), Mapping) else {}
    total_tokens = usage.get("total_tokens")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    observed_prompt_sha256 = meta.get("prompt_sha256")
    provider_contract_sha256 = meta.get("provider_contract_sha256")
    prompt_hash_recorded = (
        isinstance(observed_prompt_sha256, str)
        and len(observed_prompt_sha256) == 64
        and all(char in "0123456789abcdef" for char in observed_prompt_sha256)
    )
    route_contract_pinned = (
        isinstance(provider_contract_sha256, str)
        and len(provider_contract_sha256) == 64
        and all(char in "0123456789abcdef" for char in provider_contract_sha256)
    )
    checks = {
        "dispatch_ok": dispatch.get("status") == "ok",
        "one_worker": isinstance(worker, Mapping) and bool(worker),
        "meta_ok": meta.get("status") == "ok" and meta.get("http_status") == 200,
        "model_observed": meta.get("model_invocation_observed") is True,
        "model_exact": meta.get("selected_equals_observed") is True,
        "model_accepted": meta.get("model_identity_accepted") is True,
        "positive_usage": isinstance(total_tokens, int) and total_tokens > 0,
        "prompt_hash_recorded": prompt_hash_recorded,
        "prompt_hash_exact": prompt_hash_recorded
        and observed_prompt_sha256 == expected_prompt_sha256,
        "route_contract_pinned": route_contract_pinned,
        "secret_not_recorded": meta.get("secret_material_recorded") is False,
        "filesystem_boundary_recorded": meta.get("cannot_access_filesystem") is True,
        "result_hash_readback": result_hash_readback,
        "raw_hash_readback": raw_hash_readback,
        "terminal_completed": meta.get("terminal_state") == "completed",
    }
    problems.extend(name for name, passed in checks.items() if not passed)
    duration_ms = meta.get("duration_ms")
    if not isinstance(duration_ms, int) or duration_ms <= 0:
        problems.append("duration_ms_invalid")
    return {
        "ok": not problems,
        "stratum": stratum,
        "prompt_bytes": prompt_bytes,
        "prompt_sha256": expected_prompt_sha256,
        "provider_id": meta.get("provider_id"),
        "transport_id": meta.get("transport_id"),
        "selected_model": meta.get("selected_model"),
        "observed_model": meta.get("observed_model"),
        "api_style": meta.get("api_style"),
        "provider_contract_sha256": provider_contract_sha256,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
        "result_sha256": meta.get("result_sha256"),
        "raw_response_sha256": meta.get("raw_response_sha256"),
        "checks": checks,
        "problems": problems,
    }


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def adjudicate_capacity(
    *,
    measurements: Sequence[Mapping[str, Any]],
    quota_snapshot: Mapping[str, Any],
    planned_batch_cells: int,
    hard_bounds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adjudicate route readiness and capacity for the current bounded batch.

    G4 execution is partitioned into pre-registered batches. Each batch
    still requires its own PowerPlan, budget, and stopping conditions; G4_FULL
    remains false until every required family/configuration result is complete.
    Percentage-only quota telemetry cannot block a batch. A known insufficient
    hard bound holds only this batch so the worker bus can resize or re-route it.
    """
    reasons: list[str] = []
    advisories: list[str] = []
    failed_check_reasons = {
        "prompt_hash_recorded": "ROUTE_MEASUREMENT_PROMPT_HASH_NOT_RECORDED",
        "prompt_hash_exact": "ROUTE_MEASUREMENT_PROMPT_HASH_NOT_EXACT",
        "route_contract_pinned": "ROUTE_MEASUREMENT_ROUTE_CONTRACT_NOT_PINNED",
        "filesystem_boundary_recorded": ("ROUTE_MEASUREMENT_FILESYSTEM_BOUNDARY_NOT_RECORDED"),
    }
    if planned_batch_cells <= 0:
        raise ValueError("planned_batch_cells must be positive")
    rows = [dict(row) for row in measurements]
    if len(rows) != 3 or {row.get("stratum") for row in rows} != {
        "low",
        "median",
        "high",
    }:
        reasons.append("THREE_SIZE_STRATA_NOT_MEASURED")
    if any(row.get("ok") is not True for row in rows):
        reasons.append("ROUTE_MEASUREMENT_INVALID")
    for row in rows:
        for problem in row.get("problems") or []:
            problem_name = str(problem)
            reasons.append(
                failed_check_reasons.get(
                    problem_name,
                    f"ROUTE_MEASUREMENT_{problem_name.upper().replace('-', '_')}_FAILED",
                )
            )
    route_identities = {
        (
            row.get("provider_id"),
            row.get("transport_id"),
            row.get("selected_model"),
            row.get("observed_model"),
            row.get("provider_contract_sha256"),
        )
        for row in rows
        if row.get("ok") is True
    }
    if len(route_identities) != 1:
        reasons.append("ROUTE_IDENTITY_NOT_SINGLE_EXACT")

    total_tokens = [_positive_int(row.get("total_tokens")) for row in rows]
    durations = [_positive_int(row.get("duration_ms")) for row in rows]
    if any(value is None for value in total_tokens):
        reasons.append("POSITIVE_TOKEN_MEASUREMENT_MISSING")
    if any(value is None for value in durations):
        reasons.append("POSITIVE_DURATION_MEASUREMENT_MISSING")

    bound = dict(hard_bounds or {})
    hard_available_tokens = _positive_int(bound.get("available_tokens"))
    hard_max_calls = _positive_int(bound.get("max_calls"))
    hard_wall_clock_ms = _positive_int(bound.get("wall_clock_ms"))
    hard_source = bound.get("source")
    absolute_capacity_available = (
        all(
            value is not None
            for value in (hard_available_tokens, hard_max_calls, hard_wall_clock_ms)
        )
        and isinstance(hard_source, str)
        and bool(hard_source)
    )
    if hard_available_tokens is None:
        advisories.append("ABSOLUTE_TOKEN_CAPACITY_NOT_AVAILABLE_ADVISORY")
    if hard_max_calls is None:
        advisories.append("ABSOLUTE_CALL_CAPACITY_NOT_AVAILABLE_ADVISORY")
    if hard_wall_clock_ms is None:
        advisories.append("ABSOLUTE_WALL_CLOCK_CAPACITY_NOT_AVAILABLE_ADVISORY")
    if not isinstance(hard_source, str) or not hard_source:
        advisories.append("ABSOLUTE_CAPACITY_SOURCE_NOT_AVAILABLE_ADVISORY")

    quota_is_percentage_only = not any(
        _positive_int(quota_snapshot.get(key)) is not None
        for key in ("hard_available_tokens", "hard_max_calls", "hard_wall_clock_ms")
    )
    if quota_is_percentage_only:
        advisories.append("QUOTA_TELEMETRY_PERCENTAGE_ONLY_ADVISORY")

    max_tokens = max((value or 0 for value in total_tokens), default=0)
    max_duration = max((value or 0 for value in durations), default=0)
    estimated_token_ceiling = math.ceil(max_tokens * planned_batch_cells * 1.25)
    estimated_serial_wall_ms = math.ceil(max_duration * planned_batch_cells * 1.25)
    batch_scheduling_holds: list[str] = []
    if hard_available_tokens is not None and hard_available_tokens < estimated_token_ceiling:
        batch_scheduling_holds.append("OBSERVED_TOKEN_CAPACITY_BELOW_CURRENT_BATCH_ESTIMATE")
    if hard_max_calls is not None and hard_max_calls < planned_batch_cells:
        batch_scheduling_holds.append("OBSERVED_CALL_CAPACITY_BELOW_CURRENT_BATCH_ESTIMATE")
    if hard_wall_clock_ms is not None and hard_wall_clock_ms < estimated_serial_wall_ms:
        batch_scheduling_holds.append("OBSERVED_WALL_BOUND_BELOW_CURRENT_BATCH_ESTIMATE")

    route_evidence_ready = not reasons
    current_batch_capacity_observed_sufficient = bool(
        absolute_capacity_available
        and hard_available_tokens is not None
        and hard_available_tokens >= estimated_token_ceiling
        and hard_max_calls is not None
        and hard_max_calls >= planned_batch_cells
        and hard_wall_clock_ms is not None
        and hard_wall_clock_ms >= estimated_serial_wall_ms
    )
    batch_execution_ready = route_evidence_ready and not batch_scheduling_holds
    phase_control = build_phase_control_state(
        observed_generation=canonical_sha256(
            {
                "schema_version": "xinao.g4.capacity.phase_generation.v1",
                "measurements": rows,
                "quota_snapshot": dict(quota_snapshot),
                "planned_batch_cells": planned_batch_cells,
                "hard_bounds": bound,
            }
        ),
        g4_engineering_allowed=True,
        g4_batch_execution_allowed=batch_execution_ready,
        g4_full_evidence_complete=False,
        g5_design_allowed=True,
        g5_preregistration_allowed=True,
        g5_final_adjudication_complete=False,
        g6_formal_research_allowed=False,
    )
    phase_directives = execution_directives(phase_control)
    legacy_claims = legacy_claim_projection(phase_control)
    report: dict[str, Any] = {
        "schema_version": "xinao.g4.bounded_batch_route_advisory.v3",
        "terminal": (TERMINAL_ROUTE_READY if batch_execution_ready else TERMINAL_ROUTE_HOLD),
        "route_evidence_ready_for_current_batch": route_evidence_ready,
        "current_batch_execution_ready": batch_execution_ready,
        "execution_mode": "pre_registered_bounded_family_batches",
        "family_power_plan_required": True,
        "single_shot_capacity_required": False,
        "full_report_requires_complete_campaign": True,
        "capacity_scope": "current_batch_only",
        "campaign_provider_locked": False,
        "api_quota_is_campaign_gate": False,
        "planned_batch_cells": planned_batch_cells,
        "calibration_measurements": rows,
        "route_identity_count": len(route_identities),
        "measured_max_tokens_per_call": max_tokens or None,
        "measured_max_duration_ms_per_call": max_duration or None,
        "estimated_batch_token_ceiling_with_25pct_contingency": (estimated_token_ceiling or None),
        "estimated_batch_serial_wall_ms_with_25pct_contingency": (estimated_serial_wall_ms or None),
        "hard_bounds": bound,
        "absolute_capacity_available": absolute_capacity_available,
        "current_batch_capacity_observed_sufficient": (current_batch_capacity_observed_sufficient),
        "quota_snapshot_sha256": canonical_sha256(dict(quota_snapshot)),
        "quota_percentage_only_advisory": quota_is_percentage_only,
        "reasons": sorted(set(reasons)),
        "batch_scheduling_holds": sorted(set(batch_scheduling_holds)),
        "advisories": sorted(set(advisories)),
        "hidden_outcome_access": False,
        "scoring_executed": False,
        "authority_freeze_allowed": False,
        "phase_control_state": phase_control,
        "execution_directives": phase_directives,
        "human_status_cn": human_summary_cn(phase_control),
        "global_wait_allowed": phase_directives["parent_global_wait_allowed"],
        "g4_full": legacy_claims["g4_full"],
        "g4_closed": legacy_claims["g4_closed"],
        "g5_closed": legacy_claims["g5_closed"],
        "admission_closed": False,
        "foundation_closed": False,
        "parent_complete": False,
        "authority": False,
        "completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report
