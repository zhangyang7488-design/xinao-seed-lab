"""Independent offline scoring for the H03/H04/H10 G4 bootstrap slice."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from statistics import NormalDist
from typing import Any

from xinao.canonical import canonical_sha256

from .g4_hidden_benchmark.constants import HASH_PROFILE

BOOTSTRAP_FAMILIES = ("H03", "H04", "H10")
FORMAL_CASE_FAMILIES = ("H01", "H03", "H04", "H10")
TERMINAL_PASS = "G4_BOOTSTRAP_EXECUTION_VERIFIED_HOLD"
TERMINAL_FAIL = "G4_BOOTSTRAP_EXECUTION_FAIL_CLOSED_HOLD"
FORMAL_CASE_PASS = "G4_FORMAL_CASE_PASS_HOLD"
FORMAL_CASE_FAIL = "G4_FORMAL_CASE_FAIL_HOLD"
H01_FAMILY_ALPHA = 0.05
FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "authority",
        "authority_applied",
        "evaluator_truth",
        "g4_closed",
        "hidden_parameters",
        "parent_complete",
        "scoring_policy_id",
        "truth",
        "vault_locator",
        "vault_path",
    }
)


def _forbidden_output_paths(value: Any, *, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_OUTPUT_KEYS:
                hits.append(child_path)
            hits.extend(_forbidden_output_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_forbidden_output_paths(child, path=f"{path}[{index}]"))
    return hits


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _rows(payload: Any) -> list[Any]:
    results = payload.get("results") if isinstance(payload, Mapping) else payload
    if isinstance(results, Mapping):
        nested = results.get("results")
        if isinstance(nested, list):
            return nested
        table = results.get("table")
        return table if isinstance(table, list) else []
    return results if isinstance(results, list) else []


def _row_case_id(row: Mapping[str, Any]) -> str | None:
    vars_obj = row.get("vars") if isinstance(row.get("vars"), Mapping) else {}
    case_id = vars_obj.get("public_case_id") or row.get("public_case_id")
    test_case = row.get("testCase")
    if not case_id and isinstance(test_case, Mapping):
        test_vars = test_case.get("vars")
        if isinstance(test_vars, Mapping):
            case_id = test_vars.get("public_case_id")
    metadata = row.get("metadata")
    if not case_id and isinstance(metadata, Mapping):
        case_id = metadata.get("public_case_id")
    return str(case_id) if case_id else None


def _response_text(row: Mapping[str, Any]) -> str | None:
    response = row.get("response")
    if isinstance(response, Mapping):
        for key in ("output", "text", "content"):
            value = response.get(key)
            if isinstance(value, str):
                return value
    elif isinstance(response, str):
        return response
    for key in ("output", "text"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return None


def extract_subject_outputs(promptfoo_result: Any) -> dict[str, Any]:
    """Parse exact unique subject envelopes without reading evaluator truth."""
    observed: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for index, row in enumerate(_rows(promptfoo_result)):
        if not isinstance(row, Mapping):
            problems.append(f"malformed_row:{index}")
            continue
        case_id = _row_case_id(row)
        if not case_id:
            problems.append(f"missing_case_id:{index}")
            continue
        if case_id in observed:
            problems.append(f"duplicate_case_id:{case_id}")
            continue
        if row.get("cached") is True or row.get("fromCache") is True:
            problems.append(f"cached_row:{case_id}")
        response = row.get("response")
        if isinstance(response, Mapping) and response.get("cached") is True:
            problems.append(f"cached_row:{case_id}")
        text = _response_text(row)
        if text is None:
            problems.append(f"missing_response_output:{case_id}")
            continue
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"response_not_json:{case_id}")
            continue
        if not isinstance(envelope, dict):
            problems.append(f"response_not_mapping:{case_id}")
            continue
        if envelope.get("public_case_id") != case_id:
            problems.append(f"response_case_id_mismatch:{case_id}")
        if envelope.get("schema_version") != "xinao.g4.bootstrap.c0_subject_output.v1":
            problems.append(f"response_schema_mismatch:{case_id}")
        if envelope.get("subject_configuration") != "C0-ALGO":
            problems.append(f"subject_configuration_mismatch:{case_id}")
        hits = sorted(_forbidden_output_paths(envelope))
        if hits:
            problems.append(f"authority_or_private_output_fields:{case_id}:{','.join(hits)}")
        observed[case_id] = envelope
    return {
        "ok": not problems and bool(observed),
        "problems": problems,
        "outputs": observed,
        "output_count": len(observed),
    }


def recompute_private_record_commitment(record: Mapping[str, Any]) -> str:
    material = {
        "public_case_id": record["public_case_id"],
        "public_instructions": record["public_instructions"],
        "task_input": record["task_input"],
        "family_id": record["family_id"],
        "split": record["split"],
        "case_index": record["case_index"],
        "hidden_parameters": record["hidden_parameters"],
        "truth": record["truth"],
        "expected_disposition": record["expected_disposition"],
        "scoring_policy_id": record["scoring_policy_id"],
        "hash_profile": HASH_PROFILE,
    }
    return canonical_sha256(material)


def _correlation(values: list[float], labels: list[float]) -> float:
    if not values or len(values) != len(labels):
        return 0.0
    mean_x = sum(values) / len(values)
    mean_y = sum(labels) / len(labels)
    centered_x = [value - mean_x for value in values]
    centered_y = [value - mean_y for value in labels]
    denominator = math.sqrt(
        sum(value * value for value in centered_x) * sum(value * value for value in centered_y)
    )
    if denominator <= 1e-12:
        return 0.0
    return (
        sum(left * right for left, right in zip(centered_x, centered_y, strict=True)) / denominator
    )


def _score_h01(record: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    analysis = envelope.get("analysis") if isinstance(envelope.get("analysis"), Mapping) else {}
    task = record.get("task_input") if isinstance(record.get("task_input"), Mapping) else {}
    truth = record.get("truth") if isinstance(record.get("truth"), Mapping) else {}
    observations = task.get("observations") if isinstance(task.get("observations"), list) else []
    targets = task.get("targets") if isinstance(task.get("targets"), list) else []
    rows_valid = (
        len(observations) > 3
        and len(observations) == len(targets)
        and all(isinstance(row, Mapping) for row in observations)
    )
    columns = sorted(set.intersection(*(set(row) for row in observations))) if rows_valid else []
    try:
        labels = [float(value) for value in targets]
        correlations = {
            column: _correlation(
                [float(row[column]) for row in observations],
                labels,
            )
            for column in columns
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        correlations = {}
    selected_feature = (
        max(columns, key=lambda column: abs(correlations[column]))
        if columns and len(correlations) == len(columns)
        else ""
    )
    selected_correlation = correlations.get(selected_feature)
    alpha_eff = H01_FAMILY_ALPHA / len(columns) if columns else None
    p_value: float | None = None
    if selected_correlation is not None and len(observations) > 3:
        clipped = max(-1.0 + 1e-15, min(1.0 - 1e-15, selected_correlation))
        fisher_z = math.atanh(clipped) * math.sqrt(len(observations) - 3)
        p_value = 2.0 * (1.0 - NormalDist().cdf(abs(fisher_z)))
    expected_decision = (
        "STRUCTURE"
        if p_value is not None and alpha_eff is not None and p_value <= alpha_eff
        else "NO_ACTION"
    )
    observed_correlation = _finite_float(analysis.get("selected_correlation"))
    observed_p = _finite_float(analysis.get("p_value"))
    observed_alpha_eff = _finite_float(analysis.get("alpha_eff"))
    attempts = _safe_int(analysis.get("attempts"))
    expected_feature = str(truth.get("active_feature") or "")
    statistical_checks = {
        "public_shape_valid": bool(columns) and len(correlations) == len(columns),
        "selected_feature_recomputed": analysis.get("selected_feature") == selected_feature,
        "correlation_recomputed": selected_correlation is not None
        and observed_correlation is not None
        and math.isclose(observed_correlation, selected_correlation, abs_tol=1e-7),
        "p_value_recomputed": p_value is not None
        and observed_p is not None
        and math.isclose(observed_p, p_value, abs_tol=1e-10),
        "alpha_eff_recomputed": alpha_eff is not None
        and observed_alpha_eff is not None
        and math.isclose(observed_alpha_eff, alpha_eff, abs_tol=1e-10),
        "multiplicity_declared": analysis.get("multiplicity") == "BONFERRONI_FEATURE_SCREEN",
        "decision_calibrated": analysis.get("decision") == expected_decision,
        "attempts_complete": attempts == len(columns) and len(columns) > 0,
        "not_promoted": analysis.get("promoted") is False,
    }
    detection_checks = {
        "decision_structure": expected_decision == "STRUCTURE",
        "active_feature_exact": analysis.get("active_feature") == expected_feature,
        "direction_positive": observed_correlation is not None and observed_correlation > 0,
    }
    statistically_valid = all(statistical_checks.values())
    return {
        "family_id": "H01",
        "passed": statistically_valid and all(detection_checks.values()),
        "statistically_valid": statistically_valid,
        "checks": {**statistical_checks, **detection_checks},
        "metrics": {
            "selected_correlation": observed_correlation,
            "p_value": observed_p,
            "alpha_eff": observed_alpha_eff,
            "power_band": truth.get("power_band"),
        },
    }


def _score_h03(record: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    analysis = envelope.get("analysis") if isinstance(envelope.get("analysis"), Mapping) else {}
    task = record.get("task_input") if isinstance(record.get("task_input"), Mapping) else {}
    truth = record.get("truth") if isinstance(record.get("truth"), Mapping) else {}
    labels = task.get("labels") if isinstance(task.get("labels"), list) else []
    predictions = (
        analysis.get("predictions") if isinstance(analysis.get("predictions"), list) else []
    )
    parsed_labels = [_safe_int(value) for value in labels]
    parsed_predictions = [_safe_int(value) for value in predictions]
    accuracy = 0.0
    if (
        labels
        and len(labels) == len(predictions)
        and None not in parsed_labels
        and None not in parsed_predictions
    ):
        accuracy = sum(
            int(a == b) for a, b in zip(parsed_labels, parsed_predictions, strict=True)
        ) / len(labels)
    expected_columns = sorted(str(value) for value in truth.get("active_columns", []))
    observed_columns = sorted(str(value) for value in analysis.get("active_columns", []))
    interaction_gain = _finite_float(analysis.get("interaction_gain"))
    attempts = _safe_int(analysis.get("attempts"))
    checks = {
        "decision_structure": analysis.get("decision") == "STRUCTURE",
        "active_columns_exact": observed_columns == expected_columns,
        "functional_accuracy": accuracy == 1.0,
        "beats_single_baseline": interaction_gain is not None and interaction_gain >= 0.15,
        "attempts_disclosed": attempts is not None and attempts >= 3,
        "not_promoted": analysis.get("promoted") is False,
    }
    return {
        "family_id": "H03",
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": {"functional_accuracy": round(accuracy, 8)},
    }


def _score_h04(record: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    analysis = envelope.get("analysis") if isinstance(envelope.get("analysis"), Mapping) else {}
    truth = record.get("truth") if isinstance(record.get("truth"), Mapping) else {}
    expected_components = (
        truth.get("components") if isinstance(truth.get("components"), list) else []
    )
    observed_components = (
        analysis.get("components") if isinstance(analysis.get("components"), list) else []
    )
    expected_periods = sorted(
        parsed
        for item in expected_components
        if (parsed := _safe_int(item.get("period") if isinstance(item, Mapping) else None))
        is not None
    )
    observed_periods = sorted(
        parsed
        for item in observed_components
        if isinstance(item, Mapping) and (parsed := _safe_int(item.get("period"))) is not None
    )
    joint_oos = _finite_float(analysis.get("joint_oos_rmse"))
    single_oos = _finite_float(analysis.get("best_single_oos_rmse"))
    surrogate = _finite_float(analysis.get("surrogate_rmse"))
    attempts = _safe_int(analysis.get("attempts"))
    checks = {
        "decision_structure": analysis.get("decision") == "STRUCTURE",
        "component_periods_exact": len(observed_periods) == len(observed_components)
        and observed_periods == expected_periods,
        "joint_beats_single": joint_oos is not None
        and single_oos is not None
        and joint_oos < single_oos * 0.8,
        "joint_beats_surrogate": joint_oos is not None
        and surrogate is not None
        and joint_oos < surrogate,
        "stable_oos": analysis.get("stable_oos") is True,
        "attempts_disclosed": attempts is not None and attempts > 0,
        "not_promoted": analysis.get("promoted") is False,
    }
    return {
        "family_id": "H04",
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": {
            "joint_oos_rmse": round(joint_oos, 8) if joint_oos is not None else None,
            "best_single_oos_rmse": round(single_oos, 8) if single_oos is not None else None,
            "surrogate_rmse": round(surrogate, 8) if surrogate is not None else None,
        },
    }


def _score_h10(record: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    analysis = envelope.get("analysis") if isinstance(envelope.get("analysis"), Mapping) else {}
    certificate = (
        analysis.get("stopping_certificate")
        if isinstance(analysis.get("stopping_certificate"), Mapping)
        else {}
    )
    task = record.get("task_input") if isinstance(record.get("task_input"), Mapping) else {}
    features = task.get("features") if isinstance(task.get("features"), list) else []
    feature_count = len(features[0]) if features and isinstance(features[0], Mapping) else 0
    attempts = _safe_int(certificate.get("attempts_disclosed"))
    max_abs = _finite_float(certificate.get("max_abs_correlation"))
    checks = {
        "decision_no_action": analysis.get("decision") == "NO_ACTION",
        "certificate_present": bool(certificate),
        "attempts_complete": attempts is not None and attempts >= feature_count > 0,
        "no_candidate_promoted": certificate.get("no_candidate_promoted") is True,
        "not_promoted": analysis.get("promoted") is False,
    }
    return {
        "family_id": "H10",
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": {
            "max_abs_correlation": max_abs,
            "attempts_disclosed": attempts,
        },
    }


FORMAL_CASE_SCORERS = {
    "H01": _score_h01,
    "H03": _score_h03,
    "H04": _score_h04,
    "H10": _score_h10,
}


def score_formal_case(
    *,
    evaluator_record: Mapping[str, Any],
    promptfoo_result: Any,
    suite_identity_sha256: str,
    generator_artifact_sha256: str,
) -> dict[str, Any]:
    """Score one preregistered formal case without aggregating a family outcome."""
    extraction = extract_subject_outputs(promptfoo_result)
    problems = list(extraction["problems"])
    family = str(evaluator_record.get("family_id") or "")
    case_id = str(evaluator_record.get("public_case_id") or "")
    if family not in FORMAL_CASE_FAMILIES:
        problems.append(f"unsupported_private_family:{family}")
    if set(extraction["outputs"]) != {case_id}:
        problems.append("public_private_case_set_mismatch")
    recomputed = recompute_private_record_commitment(evaluator_record)
    expected = str(evaluator_record.get("commitment_sha256") or "")
    output = extraction["outputs"].get(case_id)
    observed = str(output.get("commitment_sha256") or "") if isinstance(output, Mapping) else ""
    commitment_verified = recomputed == expected == observed
    if not commitment_verified:
        problems.append(f"commitment_mismatch:{case_id}")

    family_result: dict[str, Any] = {}
    if not problems:
        family_result = FORMAL_CASE_SCORERS[family](evaluator_record, output)
    pipeline_verified = not problems and commitment_verified
    capability_case_pass = pipeline_verified and family_result.get("passed") is True
    report: dict[str, Any] = {
        "schema_version": "xinao.g4.formal_case.offline_score_report.v1",
        "terminal": FORMAL_CASE_PASS if capability_case_pass else FORMAL_CASE_FAIL,
        "pipeline_verified": pipeline_verified,
        "capability_case_pass": capability_case_pass,
        "suite_identity_sha256": suite_identity_sha256,
        "generator_artifact_sha256": generator_artifact_sha256,
        "subject_configuration": "C0-ALGO",
        "family_id": family,
        "public_case_id": case_id,
        "family_result": family_result,
        "commitment_verified": commitment_verified,
        "subject_outputs_sha256": canonical_sha256(extraction["outputs"]),
        "problems": problems,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "admission_closed": False,
        "parent_complete": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report


def score_bootstrap(
    *,
    evaluator_records: Sequence[Mapping[str, Any]],
    promptfoo_result: Any,
    suite_identity_sha256: str,
    generator_artifact_sha256: str,
) -> dict[str, Any]:
    """Score one complete public-output envelope against private custodian records."""
    extraction = extract_subject_outputs(promptfoo_result)
    family_records: dict[str, Mapping[str, Any]] = {}
    problems = list(extraction["problems"])
    commitment_checks: dict[str, bool] = {}
    for record in evaluator_records:
        family = str(record.get("family_id") or "")
        case_id = str(record.get("public_case_id") or "")
        if family not in BOOTSTRAP_FAMILIES:
            problems.append(f"unexpected_private_family:{family}")
            continue
        if family in family_records:
            problems.append(f"duplicate_private_family:{family}")
            continue
        family_records[family] = record
        recomputed = recompute_private_record_commitment(record)
        expected = str(record.get("commitment_sha256") or "")
        output = extraction["outputs"].get(case_id)
        observed = str(output.get("commitment_sha256") or "") if isinstance(output, Mapping) else ""
        commitment_checks[case_id] = recomputed == expected == observed
        if not commitment_checks[case_id]:
            problems.append(f"commitment_mismatch:{case_id}")
    if set(family_records) != set(BOOTSTRAP_FAMILIES):
        problems.append("mandatory_family_set_mismatch")
    expected_ids = {str(record.get("public_case_id") or "") for record in family_records.values()}
    observed_ids = set(extraction["outputs"])
    if observed_ids != expected_ids:
        problems.append("public_private_case_set_mismatch")

    family_results: dict[str, dict[str, Any]] = {}
    if not problems:
        for family in BOOTSTRAP_FAMILIES:
            record = family_records[family]
            case_id = str(record["public_case_id"])
            family_results[family] = FORMAL_CASE_SCORERS[family](
                record, extraction["outputs"][case_id]
            )

    pipeline_verified = not problems and all(commitment_checks.values())
    capability_bootstrap_pass = pipeline_verified and all(
        result.get("passed") is True for result in family_results.values()
    )
    terminal = TERMINAL_PASS if capability_bootstrap_pass else TERMINAL_FAIL
    report: dict[str, Any] = {
        "schema_version": "xinao.g4.bootstrap.offline_score_report.v1",
        "terminal": terminal,
        "pipeline_verified": pipeline_verified,
        "capability_bootstrap_pass": capability_bootstrap_pass,
        "suite_identity_sha256": suite_identity_sha256,
        "generator_artifact_sha256": generator_artifact_sha256,
        "subject_configuration": "C0-ALGO",
        "mandatory_family_results": family_results,
        "commitment_checks": commitment_checks,
        "subject_outputs_sha256": canonical_sha256(extraction["outputs"]),
        "problems": problems,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "admission_closed": False,
        "parent_complete": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report
