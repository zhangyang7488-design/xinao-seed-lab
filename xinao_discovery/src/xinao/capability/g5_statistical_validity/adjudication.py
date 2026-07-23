"""Power, replication, and whole-G5 deterministic adjudication."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import NormalDist
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.single_home.ess_report import validate_ess_report
from xinao.single_home.global_trial_ledger import GlobalTrialLedger
from xinao.single_home.power_plan import validate_power_plan

from .null_runner import NullRunnerError, validate_full_pipeline_null_report

TERMINAL_HOLD = "G5_STATISTICAL_VALIDITY_HOLD"
TERMINAL_READY = "G5_STATISTICAL_VALIDITY_READY"
POWER_METHOD = "STANDARDIZED_NORMAL_MEAN_Z_APPROXIMATION_V1"


class G5AdjudicationError(ValueError):
    """Malformed G5 evidence that cannot be adjudicated safely."""


def _sha256(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise G5AdjudicationError(f"{name} must be 64 lowercase hex")
    return value


def _verify_hash(payload: Mapping[str, Any]) -> None:
    expected = canonical_sha256(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    if _sha256("content_hash", payload.get("content_hash")) != expected:
        raise G5AdjudicationError("content_hash mismatch")


def _probability(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise G5AdjudicationError(f"{name} must be a finite probability")
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 < parsed < 1:
        raise G5AdjudicationError(f"{name} must be in (0,1)")
    return parsed


def required_effective_n(
    *,
    standardized_mde: float,
    alpha: float,
    target_power: float,
    sidedness: str,
) -> int:
    """Recompute the pinned standardized normal-mean approximation."""

    if isinstance(standardized_mde, bool) or not isinstance(standardized_mde, (int, float)):
        raise G5AdjudicationError("standardized_mde must be a positive finite number")
    effect = float(standardized_mde)
    if not math.isfinite(effect) or effect <= 0:
        raise G5AdjudicationError("standardized_mde must be a positive finite number")
    parsed_alpha = _probability("alpha", alpha)
    parsed_power = _probability("target_power", target_power)
    if sidedness == "TWO_SIDED":
        critical_probability = 1 - parsed_alpha / 2
    elif sidedness == "ONE_SIDED":
        critical_probability = 1 - parsed_alpha
    else:
        raise G5AdjudicationError("sidedness must be ONE_SIDED or TWO_SIDED")
    z_alpha = NormalDist().inv_cdf(critical_probability)
    z_power = NormalDist().inv_cdf(parsed_power)
    return max(1, math.ceil(((z_alpha + z_power) / effect) ** 2))


def _achieved_power(
    *,
    standardized_mde: float,
    effective_n: float,
    alpha: float,
    sidedness: str,
) -> float:
    shift = math.sqrt(effective_n) * standardized_mde
    normal = NormalDist()
    if sidedness == "TWO_SIDED":
        critical = normal.inv_cdf(1 - alpha / 2)
        return 1 - normal.cdf(critical - shift) + normal.cdf(-critical - shift)
    if sidedness == "ONE_SIDED":
        critical = normal.inv_cdf(1 - alpha)
        return 1 - normal.cdf(critical - shift)
    raise G5AdjudicationError("sidedness must be ONE_SIDED or TWO_SIDED")


def build_power_evidence(
    *,
    power_plan: Mapping[str, Any],
    ess_report: Mapping[str, Any],
    alpha: float,
    sidedness: str,
) -> dict[str, Any]:
    """Build the recomputable receipt consumed by ``evaluate_power_and_ess``."""

    plan = validate_power_plan(power_plan)
    ess = validate_ess_report(ess_report, power_plan=plan)
    parsed_alpha = _probability("alpha", alpha)
    required_n = required_effective_n(
        standardized_mde=float(plan["mde"]),
        alpha=parsed_alpha,
        target_power=float(plan["target_power"]),
        sidedness=sidedness,
    )
    achieved_power = _achieved_power(
        standardized_mde=float(plan["mde"]),
        effective_n=float(ess["effective_n"]),
        alpha=parsed_alpha,
        sidedness=sidedness,
    )
    body: dict[str, Any] = {
        "schema_version": "xinao.g5.power_evidence.v1",
        "method_id": POWER_METHOD,
        "power_plan_content_hash": plan["content_hash"],
        "alpha": parsed_alpha,
        "sidedness": sidedness,
        "required_effective_n": required_n,
        "achieved_power": achieved_power,
        "authority": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def build_family_definition(
    *,
    family_id: str,
    hypothesis_order: Sequence[str],
    definition: Mapping[str, Any],
    selection_rule: str,
) -> dict[str, Any]:
    if not family_id or not selection_rule:
        raise G5AdjudicationError("family_id and selection_rule are required")
    order = list(hypothesis_order)
    if not order or any(not item for item in order) or len(order) != len(set(order)):
        raise G5AdjudicationError("hypothesis_order must be non-empty and unique")
    body: dict[str, Any] = {
        "schema_version": "xinao.g5.family_definition.v1",
        "family_id": family_id,
        "hypothesis_order": order,
        "definition_sha256": canonical_sha256(dict(definition)),
        "selection_rule": selection_rule,
        "frozen_before_outcome_access": True,
        "authority": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def build_trial_ledger_evidence(
    ledger: GlobalTrialLedger,
    *,
    observed_work_keys: Sequence[str],
) -> dict[str, Any]:
    """Recompute complete-path evidence from the single GlobalTrialLedger home."""

    ledger.assert_no_silent_path(list(observed_work_keys))
    entries = ledger.entries()
    export = ledger.export_disclosure()
    work_keys = set(export["work_keys"])
    terminal_statuses = {"SUCCEEDED", "FAILED", "TIMEOUT", "DISCARDED", "NO_ACTION"}
    terminal_keys = {
        str(entry["work_key"]) for entry in entries if entry.get("status") in terminal_statuses
    }
    terminal_counts = {
        work_key: sum(
            1
            for entry in entries
            if entry.get("work_key") == work_key and entry.get("status") in terminal_statuses
        )
        for work_key in work_keys
    }
    observed_keys_exact = set(observed_work_keys) == work_keys
    exactly_one_terminal_per_trial = all(count == 1 for count in terminal_counts.values())
    body: dict[str, Any] = {
        "schema_version": "xinao.g5.trial_ledger_evidence.v1",
        "logical_object_id": export["logical_object_id"],
        "source_schema_version": export["schema_version"],
        "source_schema_final": "provisional" not in str(export["schema_version"]).lower(),
        "source_export_sha256": canonical_sha256(export),
        "entry_stream_sha256": canonical_sha256(entries),
        "total_trials": export["total_trials"],
        "valid_equivalence_clusters": export["valid_equivalence_clusters"],
        "discarded_paths": export["discarded_paths"],
        "failed_or_timeout_paths": export["failed_or_timeout_paths"],
        "statuses_observed": export["statuses_observed"],
        "work_keys": sorted(work_keys),
        "terminal_work_keys": sorted(terminal_keys),
        "terminal_counts": terminal_counts,
        "observed_work_keys_exact": observed_keys_exact,
        "exactly_one_terminal_per_trial": exactly_one_terminal_per_trial,
        "all_registered_trials_terminal": work_keys == terminal_keys
        and exactly_one_terminal_per_trial,
        "silent_unregistered_trials": 0
        if observed_keys_exact
        else len(work_keys - set(observed_work_keys)),
        "authoritative": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def evaluate_power_and_ess(
    *,
    power_plan: Mapping[str, Any],
    ess_report: Mapping[str, Any],
    power_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind provisional single-home objects to a recomputed power requirement."""

    plan = validate_power_plan(power_plan)
    ess = validate_ess_report(ess_report, power_plan=plan)
    evidence = dict(power_evidence)
    _verify_hash(evidence)
    if evidence.get("schema_version") != "xinao.g5.power_evidence.v1":
        raise G5AdjudicationError("unexpected power evidence schema_version")
    if evidence.get("method_id") != POWER_METHOD:
        raise G5AdjudicationError("unsupported power method")
    if evidence.get("power_plan_content_hash") != plan["content_hash"]:
        raise G5AdjudicationError("power evidence is not bound to the exact power plan")
    alpha = _probability("power_evidence.alpha", evidence.get("alpha"))
    sidedness = evidence.get("sidedness")
    required_n = required_effective_n(
        standardized_mde=float(plan["mde"]),
        alpha=alpha,
        target_power=float(plan["target_power"]),
        sidedness=str(sidedness),
    )
    if evidence.get("required_effective_n") != required_n:
        raise G5AdjudicationError("required_effective_n does not recompute")
    achieved_power = _probability("achieved_power", evidence.get("achieved_power"))
    expected_achieved = _achieved_power(
        standardized_mde=float(plan["mde"]),
        effective_n=float(ess["effective_n"]),
        alpha=alpha,
        sidedness=str(sidedness),
    )
    if not math.isclose(achieved_power, expected_achieved, rel_tol=0.0, abs_tol=1e-12):
        raise G5AdjudicationError("achieved_power does not recompute")
    budget_ok = int(plan["max_budget_trials"]) >= required_n
    ess_ok = float(ess["effective_n"]) >= required_n
    nominal_within_budget = float(ess["nominal_n"]) <= int(plan["max_budget_trials"])
    plan_status_ok = plan["status"] == ("ADEQUATE" if budget_ok else "UNDERPOWERED")
    passed = budget_ok and ess_ok and nominal_within_budget and plan_status_ok
    report: dict[str, Any] = {
        "schema_version": "xinao.g5.power_ess_verification.v1",
        "power_plan_content_hash": plan["content_hash"],
        "ess_report_content_hash": ess["content_hash"],
        "method_id": POWER_METHOD,
        "alpha": alpha,
        "sidedness": sidedness,
        "required_effective_n": required_n,
        "observed_effective_n": ess["effective_n"],
        "observed_nominal_n": ess["nominal_n"],
        "achieved_power": achieved_power,
        "target_power": plan["target_power"],
        "budget_ok": budget_ok,
        "ess_ok": ess_ok,
        "nominal_within_budget": nominal_within_budget,
        "plan_status_ok": plan_status_ok,
        "passed": passed,
        "input_schemas_final": "provisional" not in str(plan["schema_version"]).lower()
        and "provisional" not in str(ess["schema_version"]).lower(),
        "authority": False,
        "completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report


def evaluate_operational_replications(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Measure operational identity diversity without calling it independence."""

    required = (
        "replication_id",
        "dataset_snapshot_sha256",
        "split_sha256",
        "seed_sha256",
        "model_identity",
        "verifier_id",
        "evidence_sha256",
    )
    if not rows:
        raise G5AdjudicationError("at least one replication row is required")
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[Any, ...]] = set()
    for index, raw in enumerate(rows):
        row = dict(raw)
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise G5AdjudicationError(f"replication {index} missing {missing}")
        for field in ("dataset_snapshot_sha256", "split_sha256", "seed_sha256", "evidence_sha256"):
            _sha256(f"replication[{index}].{field}", row[field])
        identity = tuple(row[field] for field in required)
        identities.add(identity)
        normalized.append({field: row[field] for field in required})
    report: dict[str, Any] = {
        "schema_version": "xinao.g5.operational_replication_identity.v1",
        "replication_count": len(normalized),
        "distinct_operational_identity_count": len(identities),
        "rows_sha256": canonical_sha256(normalized),
        "operational_diversity_sufficient": len(identities) >= 2,
        "statistical_independence_proved": False,
        "requires_separate_statistical_independence_evidence": True,
        "authority": False,
        "completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report


def validate_statistical_independence_evidence(raw: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    _verify_hash(data)
    if data.get("schema_version") != "xinao.g5.statistical_independence_evidence.v1":
        raise G5AdjudicationError("unexpected statistical independence schema_version")
    for field in ("design_id", "independence_unit", "verifier_id"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise G5AdjudicationError(f"{field} required")
    for field in (
        "sampling_frame_sha256",
        "assignment_protocol_sha256",
        "source_artifact_sha256",
        "verifier_evidence_sha256",
    ):
        _sha256(field, data.get(field))
    if data.get("statistical_independence_supported") is not True:
        raise G5AdjudicationError("statistical independence is not supported by the evidence")
    if data.get("verification_result") != "PASS":
        raise G5AdjudicationError("independence verification_result must be PASS")
    if data.get("fixture_only") is True:
        raise G5AdjudicationError("fixture-only independence evidence is not admissible")
    return data


def _validate_family_definition(raw: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    _verify_hash(data)
    if data.get("schema_version") != "xinao.g5.family_definition.v1":
        raise G5AdjudicationError("unexpected family definition schema_version")
    if not isinstance(data.get("family_id"), str) or not data["family_id"]:
        raise G5AdjudicationError("family_id required")
    order = data.get("hypothesis_order")
    if not isinstance(order, list) or not order or len(order) != len(set(order)):
        raise G5AdjudicationError("hypothesis_order must be non-empty and unique")
    if data.get("frozen_before_outcome_access") is not True:
        raise G5AdjudicationError("family definition was not frozen before outcome access")
    _sha256("definition_sha256", data.get("definition_sha256"))
    return data


def _validate_hashed_mapping(
    raw: Mapping[str, Any] | None,
    *,
    schema: str | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise G5AdjudicationError("required evidence mapping missing")
    data = dict(raw)
    _verify_hash(data)
    if schema is not None and data.get("schema_version") != schema:
        raise G5AdjudicationError(f"unexpected schema_version for {schema}")
    return data


def adjudicate_g5(
    *,
    g4_report: Mapping[str, Any],
    power_plan: Mapping[str, Any] | None = None,
    ess_report: Mapping[str, Any] | None = None,
    power_evidence: Mapping[str, Any] | None = None,
    trial_ledger_disclosure: Mapping[str, Any] | None = None,
    family_definition: Mapping[str, Any] | None = None,
    error_control_receipt: Mapping[str, Any] | None = None,
    holdout_snapshot: Mapping[str, Any] | None = None,
    full_pipeline_null_report: Mapping[str, Any] | None = None,
    operational_replication_report: Mapping[str, Any] | None = None,
    statistical_independence_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Adjudicate the whole G5 predicate while preserving upstream boundaries."""

    g4 = _validate_hashed_mapping(g4_report)
    checks: dict[str, bool] = {
        "g4_full_closed": g4.get("g4_full") is True and g4.get("g4_closed") is True,
        "g4_not_fixture": g4.get("fixture_only") is not True,
    }
    evidence_hashes: dict[str, str | None] = {"g4_report": g4.get("content_hash")}
    reasons: list[str] = []

    power_result: dict[str, Any] | None = None
    try:
        if not all(isinstance(item, Mapping) for item in (power_plan, ess_report, power_evidence)):
            raise G5AdjudicationError("power plan, ESS report, or power evidence missing")
        power_result = evaluate_power_and_ess(
            power_plan=power_plan,
            ess_report=ess_report,
            power_evidence=power_evidence,
        )
        checks["power_ess_passed"] = power_result["passed"] is True
        checks["power_ess_schemas_final"] = power_result["input_schemas_final"] is True
        evidence_hashes["power_ess"] = power_result["content_hash"]
    except (G5AdjudicationError, ValueError) as exc:
        checks["power_ess_passed"] = False
        checks["power_ess_schemas_final"] = False
        reasons.append(f"POWER_ESS_INVALID:{exc}")

    ledger: dict[str, Any] | None = None
    try:
        ledger = _validate_hashed_mapping(
            trial_ledger_disclosure,
            schema="xinao.g5.trial_ledger_evidence.v1",
        )
        checks["trial_ledger_complete"] = (
            isinstance(ledger.get("total_trials"), int)
            and ledger["total_trials"] > 0
            and ledger.get("all_registered_trials_terminal") is True
            and ledger.get("observed_work_keys_exact") is True
            and ledger.get("exactly_one_terminal_per_trial") is True
            and ledger.get("silent_unregistered_trials") == 0
        )
        checks["trial_ledger_schema_final"] = ledger.get("source_schema_final") is True
        evidence_hashes["trial_ledger"] = ledger.get("content_hash")
    except G5AdjudicationError as exc:
        checks["trial_ledger_complete"] = False
        checks["trial_ledger_schema_final"] = False
        reasons.append(f"TRIAL_LEDGER_INVALID:{exc}")

    family: dict[str, Any] | None = None
    try:
        if not isinstance(family_definition, Mapping):
            raise G5AdjudicationError("family definition missing")
        family = _validate_family_definition(family_definition)
        checks["family_frozen"] = True
        evidence_hashes["family_definition"] = family["content_hash"]
    except G5AdjudicationError as exc:
        checks["family_frozen"] = False
        reasons.append(f"FAMILY_INVALID:{exc}")

    error_receipt: dict[str, Any] | None = None
    try:
        error_receipt = _validate_hashed_mapping(
            error_control_receipt,
            schema="xinao.g5.error_control_receipt.v1",
        )
        checks["error_control_passed"] = (
            error_receipt.get("passed") is True
            and error_receipt.get("generic_alpha_or_e_balance") is False
            and error_receipt.get("regime") in {"SEQUENTIAL_FWER_ALPHA_SPENDING", "ONLINE_FDR_LOND"}
        )
        _probability("error_control_receipt.family_alpha", error_receipt.get("family_alpha"))
        hypothesis_count = error_receipt.get("hypothesis_count")
        if (
            isinstance(hypothesis_count, bool)
            or not isinstance(hypothesis_count, int)
            or hypothesis_count < 1
        ):
            raise G5AdjudicationError("error-control hypothesis_count must be an integer >= 1")
        evidence_hashes["error_control"] = error_receipt["content_hash"]
    except G5AdjudicationError as exc:
        checks["error_control_passed"] = False
        reasons.append(f"ERROR_CONTROL_INVALID:{exc}")

    holdout: dict[str, Any] | None = None
    try:
        holdout = _validate_hashed_mapping(
            holdout_snapshot,
            schema="xinao.g5.holdout_exposure_ledger.v1",
        )
        checks["holdout_budget_respected"] = (
            holdout.get("revoked") is False
            and holdout.get("overexposed") is False
            and holdout.get("all_outcome_accesses_debited") is True
            and holdout.get("no_action_is_free_access") is False
        )
        evidence_hashes["holdout"] = holdout["content_hash"]
    except G5AdjudicationError as exc:
        checks["holdout_budget_respected"] = False
        reasons.append(f"HOLDOUT_INVALID:{exc}")

    null_report: dict[str, Any] | None = None
    try:
        if not isinstance(full_pipeline_null_report, Mapping):
            raise NullRunnerError("full-pipeline null report missing")
        null_report = validate_full_pipeline_null_report(full_pipeline_null_report)
        checks["full_pipeline_null_passed"] = null_report.get("fixture_only") is not True
        evidence_hashes["full_pipeline_null"] = null_report["content_hash"]
    except (NullRunnerError, ValueError) as exc:
        checks["full_pipeline_null_passed"] = False
        reasons.append(f"FULL_PIPELINE_NULL_INVALID:{exc}")

    replication: dict[str, Any] | None = None
    try:
        replication = _validate_hashed_mapping(
            operational_replication_report,
            schema="xinao.g5.operational_replication_identity.v1",
        )
        checks["operational_replication_diverse"] = (
            replication.get("operational_diversity_sufficient") is True
            and replication.get("statistical_independence_proved") is False
        )
        evidence_hashes["operational_replication"] = replication["content_hash"]
    except G5AdjudicationError as exc:
        checks["operational_replication_diverse"] = False
        reasons.append(f"OPERATIONAL_REPLICATION_INVALID:{exc}")

    independence: dict[str, Any] | None = None
    try:
        if not isinstance(statistical_independence_evidence, Mapping):
            raise G5AdjudicationError("statistical independence evidence missing")
        independence = validate_statistical_independence_evidence(statistical_independence_evidence)
        checks["statistical_independence_supported"] = True
        evidence_hashes["statistical_independence"] = independence["content_hash"]
    except G5AdjudicationError as exc:
        checks["statistical_independence_supported"] = False
        reasons.append(f"STATISTICAL_INDEPENDENCE_INVALID:{exc}")

    checks["cross_bindings_exact"] = False
    if all(
        item is not None
        for item in (power_result, ledger, family, error_receipt, holdout, null_report)
    ):
        disclosure = null_report.get("disclosure")
        hypothesis_order = family.get("hypothesis_order")
        try:
            checks["cross_bindings_exact"] = (
                error_receipt.get("hypothesis_count") == len(hypothesis_order)
                and math.isclose(
                    float(power_result.get("alpha")),
                    float(error_receipt.get("family_alpha")),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                and holdout.get("split_binding") == power_plan.get("holdout_split_binding")
                and isinstance(disclosure, Mapping)
                and disclosure.get("total_trials") == ledger.get("total_trials")
                and disclosure.get("error_control_receipt_sha256")
                == error_receipt.get("content_hash")
                and disclosure.get("holdout_ledger_sha256") == holdout.get("content_hash")
            )
        except (TypeError, ValueError):
            checks["cross_bindings_exact"] = False
            reasons.append("CROSS_BINDING_VALUE_INVALID")

    for name, passed in checks.items():
        if not passed:
            reasons.append(name.upper())
    ready = all(checks.values())
    report: dict[str, Any] = {
        "schema_version": "xinao.g5.statistical_validity_adjudication.v1",
        "terminal": TERMINAL_READY if ready else TERMINAL_HOLD,
        "g5_statistical_validity_ready": ready,
        "checks": checks,
        "evidence_content_hashes": evidence_hashes,
        "reasons": sorted(set(reasons)),
        "mature_protocol_boundaries": {
            "generic_alpha_or_e_balance_allowed": False,
            "disabled_error_control_can_pass": False,
            "every_holdout_outcome_access_is_debited": True,
            "public_null_smoke_is_g5_evidence": False,
            "operational_identity_is_statistical_independence": False,
        },
        "g4_full": g4.get("g4_full") is True,
        "g4_closed": g4.get("g4_closed") is True,
        "g5_closed": ready,
        "foundation_closed": False,
        "formal_admission": False,
        "g6_closed": False,
        "g7_closed": False,
        "g8_closed": False,
        "parent_complete": False,
        "authority": False,
        "completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report
