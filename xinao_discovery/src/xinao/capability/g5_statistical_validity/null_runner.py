"""Public null smoke and real full-pipeline null-report validation."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from xinao.canonical import canonical_sha256

PUBLIC_NULL_SMOKE = "PUBLIC_NULL_SMOKE"
REAL_PIPELINE_NULL = "REAL_FULL_PIPELINE_NULL"


class NullRunnerError(ValueError):
    """Invalid public-null result or G5-ineligible full-pipeline report."""


def _sha256(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NullRunnerError(f"{name} must be 64 lowercase hex")
    return value


def _verify_hash(payload: Mapping[str, Any]) -> None:
    expected = canonical_sha256(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    if _sha256("content_hash", payload.get("content_hash")) != expected:
        raise NullRunnerError("content_hash mismatch")


def _public_null_cases(*, seed: int, trial_count: int) -> list[dict[str, Any]]:
    if isinstance(trial_count, bool) or not isinstance(trial_count, int) or trial_count < 4:
        raise NullRunnerError("trial_count must be an integer >= 4")
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    for index in range(trial_count):
        observations = [rng.uniform(-1.0, 1.0) for _ in range(16)]
        cases.append(
            {
                "trial_id": f"public-null-{index:04d}",
                "kind": "PUBLIC_PURE_NOISE",
                "observations": observations,
                "is_g4_proof": False,
                "heldout": False,
            }
        )
    return cases


def run_public_null_smoke(
    pipeline: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    *,
    seed: int = 20260723,
    trial_count: int = 8,
) -> dict[str, Any]:
    """Exercise a callable on public pure noise without creating G5 evidence."""

    cases = _public_null_cases(seed=seed, trial_count=trial_count)
    traces: list[dict[str, Any]] = []
    violations: list[str] = []
    for case in cases:
        raw = pipeline(case)
        if not isinstance(raw, Mapping):
            raise NullRunnerError("pipeline result must be a mapping")
        result = dict(raw)
        action = result.get("action")
        claimed = result.get("claimed_discovery") is True
        promoted = result.get("promoted") is True
        if action not in {"NO_ACTION", "CORRECT_REJECTION"}:
            violations.append(f"invalid_action:{case['trial_id']}")
        if claimed:
            violations.append(f"claimed_discovery:{case['trial_id']}")
        if promoted:
            violations.append(f"promoted_noise:{case['trial_id']}")
        traces.append(
            {
                "trial_id": case["trial_id"],
                "action": action,
                "claimed_discovery": claimed,
                "promoted": promoted,
                "result_sha256": canonical_sha256(result),
            }
        )
    body: dict[str, Any] = {
        "schema_version": "xinao.g5.public_null_smoke.v1",
        "runner_kind": PUBLIC_NULL_SMOKE,
        "seed": seed,
        "trial_count": trial_count,
        "public_input_sha256": canonical_sha256(cases),
        "traces": traces,
        "violations": violations,
        "passed": not violations,
        "executes_real_full_pipeline": False,
        "g5_evidence_eligible": False,
        "g4_full": False,
        "g5_closed": False,
        "authority": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def validate_full_pipeline_null_report(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an immutable report produced by the actual research pipeline.

    The validator deliberately rejects PUBLIC_NULL_SMOKE.  A real report must
    bind its executable entrypoint, actual model identities, input snapshot,
    error-control receipt, holdout ledger, and source evidence.
    """

    data = dict(raw)
    _verify_hash(data)
    if data.get("runner_kind") != REAL_PIPELINE_NULL:
        raise NullRunnerError("PUBLIC_NULL_SMOKE is not G5-eligible full-pipeline evidence")
    if data.get("schema_version") != "xinao.g5.full_pipeline_null_report.v1":
        raise NullRunnerError("unexpected full-pipeline null schema_version")
    entrypoint = data.get("actual_pipeline_entrypoint")
    identities = data.get("actual_model_identities")
    if not isinstance(entrypoint, str) or not entrypoint:
        raise NullRunnerError("actual_pipeline_entrypoint required")
    if (
        not isinstance(identities, list)
        or not identities
        or any(not isinstance(item, str) or not item for item in identities)
    ):
        raise NullRunnerError("actual_model_identities must be a non-empty list")
    if any(
        item.strip().lower() in {"unknown", "unobserved", "requested-only"} for item in identities
    ):
        raise NullRunnerError("actual_model_identities must contain observed identities")
    _sha256("input_snapshot_sha256", data.get("input_snapshot_sha256"))
    _sha256("source_evidence_sha256", data.get("source_evidence_sha256"))
    trial_count = data.get("trial_count")
    correct_rejections = data.get("correct_rejections")
    false_promotions = data.get("false_promotions")
    if isinstance(trial_count, bool) or not isinstance(trial_count, int) or trial_count < 1:
        raise NullRunnerError("trial_count must be an integer >= 1")
    if correct_rejections != trial_count:
        raise NullRunnerError("every public-null trial must be correctly rejected")
    if false_promotions != 0:
        raise NullRunnerError("public-null pipeline produced a false promotion")
    disclosure = data.get("disclosure")
    if not isinstance(disclosure, Mapping):
        raise NullRunnerError("disclosure required")
    required_disclosure = {
        "total_trials",
        "valid_equivalence_clusters",
        "discarded_paths",
        "selection_criteria",
        "confirmation_accesses",
        "effective_degrees_of_freedom",
        "compute_budget",
        "error_control_receipt_sha256",
        "holdout_ledger_sha256",
    }
    missing = sorted(required_disclosure - set(disclosure))
    if missing:
        raise NullRunnerError(f"null disclosure missing {missing}")
    if {"alpha_or_evalue_budget", "alpha_or_e_budget"}.intersection(disclosure):
        raise NullRunnerError("generic alpha-or-e disclosure is forbidden")
    if disclosure.get("total_trials") != trial_count:
        raise NullRunnerError("disclosure total_trials mismatch")
    for field in (
        "valid_equivalence_clusters",
        "confirmation_accesses",
        "effective_degrees_of_freedom",
        "compute_budget",
    ):
        value = disclosure.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise NullRunnerError(f"disclosure {field} must be a non-negative number")
    if not isinstance(disclosure.get("discarded_paths"), list):
        raise NullRunnerError("disclosure discarded_paths must be a list")
    if not isinstance(disclosure.get("selection_criteria"), str) or not disclosure.get(
        "selection_criteria"
    ):
        raise NullRunnerError("disclosure selection_criteria required")
    _sha256("error_control_receipt_sha256", disclosure.get("error_control_receipt_sha256"))
    _sha256("holdout_ledger_sha256", disclosure.get("holdout_ledger_sha256"))
    if data.get("passed") is not True:
        raise NullRunnerError("full-pipeline null report did not pass")
    if data.get("g5_evidence_eligible") is not True:
        raise NullRunnerError("full-pipeline report is not marked G5 evidence eligible")
    return data


def build_full_pipeline_null_report_for_test(
    *,
    trial_count: int,
    model_identities: Sequence[str],
    hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Build a structurally valid report for unit tests only.

    Production callers must use the actual pipeline producer.  The name keeps
    this helper out of the public package exports and prevents fixture evidence
    from being mistaken for current runtime truth.
    """

    body: dict[str, Any] = {
        "schema_version": "xinao.g5.full_pipeline_null_report.v1",
        "runner_kind": REAL_PIPELINE_NULL,
        "actual_pipeline_entrypoint": "unit_test_fixture_only",
        "actual_model_identities": list(model_identities),
        "input_snapshot_sha256": hashes["input"],
        "source_evidence_sha256": hashes["source"],
        "trial_count": trial_count,
        "correct_rejections": trial_count,
        "false_promotions": 0,
        "disclosure": {
            "total_trials": trial_count,
            "valid_equivalence_clusters": trial_count,
            "discarded_paths": [],
            "selection_criteria": "unit_test_fixture_only",
            "confirmation_accesses": 0,
            "effective_degrees_of_freedom": float(trial_count),
            "compute_budget": trial_count,
            "error_control_receipt_sha256": hashes["error_control"],
            "holdout_ledger_sha256": hashes["holdout"],
        },
        "passed": True,
        "g5_evidence_eligible": True,
        "fixture_only": True,
        "authority": False,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body
