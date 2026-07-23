"""Public-only C0 algorithm subject for the G4 bootstrap vertical slice.

The adapter is copied into the existing digest-pinned, network-disabled Promptfoo
container.  It consumes one JSON prompt containing public observations only and
returns an unscored analysis envelope.  It never reads files, calls a provider,
opens a network connection, or receives evaluator/vault state.
"""

from __future__ import annotations

import json
import math
import os
from itertools import combinations
from statistics import NormalDist
from typing import Any


FORBIDDEN_ENV_TOKENS = ("VAULT", "TRUTH", "SCORER", "HIDDEN", "SECRET", "API_KEY")
H01_FAMILY_ALPHA = 0.05


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _accuracy(labels: list[int], predictions: list[int]) -> float:
    if not labels or len(labels) != len(predictions):
        return 0.0
    return sum(int(a == b) for a, b in zip(labels, predictions, strict=True)) / len(labels)


def _majority_mapping(
    values: list[tuple[Any, ...]], labels: list[int]
) -> dict[tuple[Any, ...], int]:
    counts: dict[tuple[Any, ...], list[int]] = {}
    for value, label in zip(values, labels, strict=True):
        bucket = counts.setdefault(value, [0, 0])
        bucket[int(label)] += 1
    return {value: int(bucket[1] >= bucket[0]) for value, bucket in counts.items()}


def _analyze_table(task: dict[str, Any]) -> dict[str, Any]:
    rows = task.get("table")
    labels = task.get("labels")
    if not isinstance(rows, list) or not rows or not isinstance(labels, list):
        return {"decision": "INVALID_INPUT", "reason": "table_or_labels_missing"}
    if len(rows) != len(labels) or not all(isinstance(row, dict) for row in rows):
        return {"decision": "INVALID_INPUT", "reason": "table_label_shape_mismatch"}
    columns = sorted(set.intersection(*(set(row) for row in rows)))
    y = [int(value) for value in labels]

    best_single = {"accuracy": -1.0, "columns": []}
    for column in columns:
        values = [(row[column],) for row in rows]
        mapping = _majority_mapping(values, y)
        predictions = [mapping[value] for value in values]
        accuracy = _accuracy(y, predictions)
        if accuracy > float(best_single["accuracy"]):
            best_single = {"accuracy": accuracy, "columns": [column]}

    best_pair: dict[str, Any] = {"accuracy": -1.0, "columns": [], "mapping": {}}
    for left, right in combinations(columns, 2):
        values = [(row[left], row[right]) for row in rows]
        mapping = _majority_mapping(values, y)
        predictions = [mapping[value] for value in values]
        accuracy = _accuracy(y, predictions)
        if accuracy > float(best_pair["accuracy"]):
            best_pair = {
                "accuracy": accuracy,
                "columns": [left, right],
                "mapping": mapping,
                "predictions": predictions,
            }

    pair_accuracy = float(best_pair["accuracy"])
    single_accuracy = float(best_single["accuracy"])
    if pair_accuracy < 0.95 or pair_accuracy <= single_accuracy + 0.15:
        return {
            "analysis_kind": "tabular_rule_search",
            "decision": "NO_ACTION",
            "attempts": len(columns) + math.comb(len(columns), 2),
            "best_single_accuracy": round(single_accuracy, 8),
            "best_pair_accuracy": round(pair_accuracy, 8),
            "promoted": False,
        }

    mapping_public = {
        json.dumps(list(key), separators=(",", ":")): value
        for key, value in sorted(best_pair["mapping"].items())
    }
    return {
        "analysis_kind": "tabular_rule_search",
        "decision": "STRUCTURE",
        "active_columns": list(best_pair["columns"]),
        "rule_table": mapping_public,
        "predictions": list(best_pair["predictions"]),
        "training_accuracy": round(pair_accuracy, 8),
        "best_single_accuracy": round(single_accuracy, 8),
        "interaction_gain": round(pair_accuracy - single_accuracy, 8),
        "attempts": len(columns) + math.comb(len(columns), 2),
        "promoted": False,
    }


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    n = len(vector)
    augmented = [list(row) + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * base
                for value, base in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(n)]


def _fit(columns: list[list[float]], target: list[float]) -> tuple[list[float], list[float]] | None:
    design = [[1.0, *(column[index] for column in columns)] for index in range(len(target))]
    width = len(design[0])
    gram = [[sum(row[i] * row[j] for row in design) for j in range(width)] for i in range(width)]
    rhs = [
        sum(row[i] * value for row, value in zip(design, target, strict=True)) for i in range(width)
    ]
    coefficients = _solve(gram, rhs)
    if coefficients is None:
        return None
    predictions = [sum(c * x for c, x in zip(coefficients, row, strict=True)) for row in design]
    return coefficients, predictions


def _rmse(actual: list[float], predicted: list[float]) -> float:
    if not actual or len(actual) != len(predicted):
        return float("inf")
    return math.sqrt(_mean([(a - b) ** 2 for a, b in zip(actual, predicted, strict=True)]))


def _square_basis(length: int, period: int, offset: int) -> list[float]:
    return [1.0 if ((index + offset) % period) < (period // 2) else -1.0 for index in range(length)]


def _predict(coefficients: list[float], columns: list[list[float]]) -> list[float]:
    return [
        coefficients[0]
        + sum(
            coefficient * column[index]
            for coefficient, column in zip(coefficients[1:], columns, strict=True)
        )
        for index in range(len(columns[0]))
    ]


def _analyze_sequence(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("sequence")
    if not isinstance(raw, list) or len(raw) < 24:
        return {"decision": "INVALID_INPUT", "reason": "sequence_missing_or_short"}
    sequence = [float(value) for value in raw]
    split = max(16, len(sequence) * 3 // 4)
    train = sequence[:split]
    test = sequence[split:]
    candidates = [
        (period, offset, _square_basis(len(sequence), period, offset))
        for period in range(3, min(13, len(sequence) // 2 + 1))
        for offset in range(period)
    ]

    best_single: dict[str, Any] | None = None
    for period, offset, basis in candidates:
        fit = _fit([basis[:split]], train)
        if fit is None:
            continue
        coefficients, _ = fit
        train_rmse = _rmse(train, _predict(coefficients, [basis[:split]]))
        test_rmse = _rmse(test, _predict(coefficients, [basis[split:]]))
        row = {
            "period": period,
            "offset": offset,
            "coefficient": coefficients[1],
            "train_rmse": train_rmse,
            "test_rmse": test_rmse,
        }
        if best_single is None or train_rmse < float(best_single["train_rmse"]):
            best_single = row

    best_pair: dict[str, Any] | None = None
    for left_index, (left_period, left_offset, left_basis) in enumerate(candidates):
        for right_period, right_offset, right_basis in candidates[left_index + 1 :]:
            if left_period == right_period:
                continue
            fit = _fit([left_basis[:split], right_basis[:split]], train)
            if fit is None:
                continue
            coefficients, _ = fit
            train_rmse = _rmse(
                train,
                _predict(coefficients, [left_basis[:split], right_basis[:split]]),
            )
            if best_pair is not None and train_rmse >= float(best_pair["train_rmse"]):
                continue
            test_rmse = _rmse(
                test,
                _predict(coefficients, [left_basis[split:], right_basis[split:]]),
            )
            best_pair = {
                "components": [
                    {
                        "period": left_period,
                        "offset": left_offset,
                        "coefficient": coefficients[1],
                    },
                    {
                        "period": right_period,
                        "offset": right_offset,
                        "coefficient": coefficients[2],
                    },
                ],
                "intercept": coefficients[0],
                "train_rmse": train_rmse,
                "test_rmse": test_rmse,
            }

    if best_pair is None or best_single is None:
        return {"decision": "NO_ACTION", "reason": "no_stable_sequence_model", "promoted": False}
    rotated = sequence[7:] + sequence[:7]
    surrogate_rmse = _rmse(rotated, sequence)
    stable = (
        float(best_pair["test_rmse"]) < float(best_single["test_rmse"]) * 0.8
        and float(best_pair["test_rmse"]) < 0.2
    )
    return {
        "analysis_kind": "sequence_component_search",
        "decision": "STRUCTURE" if stable else "NO_ACTION",
        "components": best_pair["components"],
        "joint_train_rmse": round(float(best_pair["train_rmse"]), 8),
        "joint_oos_rmse": round(float(best_pair["test_rmse"]), 8),
        "best_single_oos_rmse": round(float(best_single["test_rmse"]), 8),
        "surrogate_rmse": round(surrogate_rmse, 8),
        "stable_oos": stable,
        "attempts": len(candidates) + math.comb(len(candidates), 2),
        "promoted": False,
    }


def _correlation(values: list[float], labels: list[float]) -> float:
    mx = _mean(values)
    my = _mean(labels)
    dx = [value - mx for value in values]
    dy = [value - my for value in labels]
    denominator = math.sqrt(sum(value * value for value in dx) * sum(value * value for value in dy))
    if denominator <= 1e-12:
        return 0.0
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denominator


def _analyze_weak_signal(task: dict[str, Any]) -> dict[str, Any]:
    observations = task.get("observations")
    targets = task.get("targets")
    if not isinstance(observations, list) or not observations or not isinstance(targets, list):
        return {"decision": "INVALID_INPUT", "reason": "observations_or_targets_missing"}
    if len(observations) != len(targets) or not all(isinstance(row, dict) for row in observations):
        return {"decision": "INVALID_INPUT", "reason": "observation_target_shape_mismatch"}
    if len(observations) <= 3:
        return {"decision": "INVALID_INPUT", "reason": "too_few_observations"}
    columns = sorted(set.intersection(*(set(row) for row in observations)))
    if not columns:
        return {"decision": "INVALID_INPUT", "reason": "no_common_features"}
    labels = [float(value) for value in targets]
    correlations = {
        column: _correlation([float(row[column]) for row in observations], labels)
        for column in columns
    }
    selected_feature = max(columns, key=lambda column: abs(correlations[column]))
    selected_correlation = correlations[selected_feature]
    clipped_correlation = max(-1.0 + 1e-15, min(1.0 - 1e-15, selected_correlation))
    fisher_z = math.atanh(clipped_correlation) * math.sqrt(len(observations) - 3)
    p_value = 2.0 * (1.0 - NormalDist().cdf(abs(fisher_z)))
    alpha_eff = H01_FAMILY_ALPHA / len(columns)
    decision = "STRUCTURE" if p_value <= alpha_eff else "NO_ACTION"
    return {
        "analysis_kind": "weak_signal_pearson_screen",
        "decision": decision,
        "correlations": {key: round(value, 8) for key, value in correlations.items()},
        "selected_feature": selected_feature,
        "active_feature": selected_feature if decision == "STRUCTURE" else None,
        "selected_correlation": round(selected_correlation, 8),
        "direction": (
            "positive"
            if selected_correlation > 0
            else "negative"
            if selected_correlation < 0
            else "zero"
        ),
        "p_value": round(p_value, 12),
        "alpha": H01_FAMILY_ALPHA,
        "alpha_eff": round(alpha_eff, 12),
        "multiplicity": "BONFERRONI_FEATURE_SCREEN",
        "attempts": len(columns),
        "promoted": False,
    }


def _analyze_feature_target(task: dict[str, Any]) -> dict[str, Any]:
    features = task.get("features")
    targets = task.get("targets")
    if not isinstance(features, list) or not features or not isinstance(targets, list):
        return {"decision": "INVALID_INPUT", "reason": "features_or_targets_missing"}
    if len(features) != len(targets) or not all(isinstance(row, dict) for row in features):
        return {"decision": "INVALID_INPUT", "reason": "feature_target_shape_mismatch"}
    columns = sorted(set.intersection(*(set(row) for row in features)))
    labels = [float(value) for value in targets]
    correlations = {
        column: _correlation([float(row[column]) for row in features], labels) for column in columns
    }
    max_abs = max((abs(value) for value in correlations.values()), default=0.0)
    threshold = 0.45
    decision = "NO_ACTION" if max_abs < threshold else "STRUCTURE"
    return {
        "analysis_kind": "bounded_null_search",
        "decision": decision,
        "correlations": {key: round(value, 8) for key, value in correlations.items()},
        "stopping_certificate": {
            "attempts_disclosed": len(columns),
            "max_abs_correlation": round(max_abs, 8),
            "predeclared_threshold": threshold,
            "no_candidate_promoted": decision == "NO_ACTION",
        },
        "promoted": False,
    }


def _analyze(task: dict[str, Any]) -> dict[str, Any]:
    if "table" in task and "labels" in task:
        return _analyze_table(task)
    if "sequence" in task:
        return _analyze_sequence(task)
    if "observations" in task and "targets" in task:
        return _analyze_weak_signal(task)
    if "features" in task and "targets" in task:
        return _analyze_feature_target(task)
    return {"decision": "UNSUPPORTED", "reason": "no_supported_public_shape", "promoted": False}


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Promptfoo Python-provider entrypoint."""
    del options
    forbidden_env = sorted(
        key for key in os.environ if any(token in key.upper() for token in FORBIDDEN_ENV_TOKENS)
    )
    if forbidden_env:
        return {"error": "subject_forbidden_environment"}
    vars_obj = context.get("vars") if isinstance(context, dict) else {}
    if not isinstance(vars_obj, dict):
        vars_obj = {}
    public_prompt = str(vars_obj.get("public_prompt") or prompt or "")
    try:
        public_case = json.loads(public_prompt)
    except json.JSONDecodeError:
        return {"error": "public_prompt_not_canonical_json"}
    if not isinstance(public_case, dict) or set(public_case) != {
        "commitment_sha256",
        "public_case_id",
        "public_instructions",
        "task_input",
    }:
        return {"error": "public_case_schema_mismatch"}
    case_id = str(public_case["public_case_id"])
    commitment = str(public_case["commitment_sha256"])
    if case_id != str(vars_obj.get("public_case_id") or ""):
        return {"error": "public_case_id_binding_mismatch"}
    if commitment != str(vars_obj.get("commitment_sha256") or ""):
        return {"error": "public_commitment_binding_mismatch"}
    task = public_case.get("task_input")
    if not isinstance(task, dict):
        return {"error": "task_input_not_mapping"}
    analysis = _analyze(task)
    envelope = {
        "schema_version": "xinao.g4.bootstrap.c0_subject_output.v1",
        "public_case_id": case_id,
        "commitment_sha256": commitment,
        "subject_configuration": "C0-ALGO",
        "analysis": analysis,
    }
    return {"output": json.dumps(envelope, sort_keys=True, separators=(",", ":"))}
