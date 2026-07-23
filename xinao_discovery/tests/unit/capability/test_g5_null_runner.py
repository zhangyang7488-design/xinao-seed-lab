from __future__ import annotations

import pytest

from xinao.canonical import canonical_sha256
from xinao.capability.g5_statistical_validity.null_runner import (
    NullRunnerError,
    build_full_pipeline_null_report_for_test,
    run_public_null_smoke,
    validate_full_pipeline_null_report,
)


def test_public_smoke_calls_pipeline_but_never_becomes_g5_evidence() -> None:
    seen: list[str] = []

    def pipeline(case):
        seen.append(case["trial_id"])
        return {"action": "NO_ACTION", "claimed_discovery": False, "promoted": False}

    report = run_public_null_smoke(pipeline, trial_count=5)
    assert len(seen) == 5
    assert report["passed"] is True
    assert report["g5_evidence_eligible"] is False
    with pytest.raises(NullRunnerError, match="not G5-eligible"):
        validate_full_pipeline_null_report(report)


def test_public_smoke_detects_noise_promotion() -> None:
    report = run_public_null_smoke(
        lambda _case: {"action": "PROMOTE", "claimed_discovery": True, "promoted": True},
        trial_count=4,
    )
    assert report["passed"] is False
    assert any(item.startswith("promoted_noise") for item in report["violations"])


def test_real_full_pipeline_report_has_typed_error_and_holdout_bindings() -> None:
    report = build_full_pipeline_null_report_for_test(
        trial_count=4,
        model_identities=["model-observed"],
        hashes={
            "input": "a" * 64,
            "source": "b" * 64,
            "error_control": "c" * 64,
            "holdout": "d" * 64,
        },
    )
    assert validate_full_pipeline_null_report(report)["passed"] is True
    bad = dict(report)
    bad["disclosure"] = {**bad["disclosure"], "alpha_or_evalue_budget": 0.05}
    bad["content_hash"] = canonical_sha256(
        {key: value for key, value in bad.items() if key != "content_hash"}
    )
    with pytest.raises(NullRunnerError, match="generic alpha-or-e"):
        validate_full_pipeline_null_report(bad)


def test_real_full_pipeline_report_rejects_unobserved_model_identity() -> None:
    report = build_full_pipeline_null_report_for_test(
        trial_count=4,
        model_identities=["unknown"],
        hashes={
            "input": "a" * 64,
            "source": "b" * 64,
            "error_control": "c" * 64,
            "holdout": "d" * 64,
        },
    )
    with pytest.raises(NullRunnerError, match="observed identities"):
        validate_full_pipeline_null_report(report)
