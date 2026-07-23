from __future__ import annotations

import pytest

from xinao.canonical import canonical_sha256
from xinao.capability.g5_statistical_validity.error_control import (
    ALPHA_SPENDING,
    ALPHA_SPENDING_PROCEDURE,
    LOND_PROCEDURE,
    ONLINE_FDR_LOND,
    ErrorControlError,
    evaluate_error_control,
)
from xinao.capability.g5_statistical_validity.holdout import (
    HoldoutExposureError,
    HoldoutExposureLedger,
)


def _sealed(value: dict) -> dict:
    result = dict(value)
    result["content_hash"] = canonical_sha256(result)
    return result


def test_sequential_alpha_spending_recomputes_every_decision() -> None:
    protocol = _sealed(
        {
            "regime": ALPHA_SPENDING,
            "procedure_id": ALPHA_SPENDING_PROCEDURE,
            "assumption_class": "ARBITRARY_DEPENDENCE",
            "family_alpha": 0.05,
            "preregistration_sha256": "a" * 64,
            "hypothesis_order": ["h1", "h2"],
            "allocation": [0.01, 0.04],
        }
    )
    receipt = evaluate_error_control(
        protocol,
        [
            {"hypothesis_id": "h1", "p_value": 0.005, "declared_threshold": 0.01, "rejected": True},
            {"hypothesis_id": "h2", "p_value": 0.2, "declared_threshold": 0.04, "rejected": False},
        ],
    )
    assert receipt["passed"] is True
    assert receipt["rejection_count"] == 1
    assert receipt["generic_alpha_or_e_balance"] is False


def test_lond_threshold_depends_on_prior_rejections() -> None:
    protocol = _sealed(
        {
            "regime": ONLINE_FDR_LOND,
            "procedure_id": LOND_PROCEDURE,
            "assumption_class": "INDEPENDENT_P_VALUES",
            "family_alpha": 0.05,
            "preregistration_sha256": "b" * 64,
            "hypothesis_order": ["h1", "h2"],
            "allocation": [0.01, 0.02],
        }
    )
    receipt = evaluate_error_control(
        protocol,
        [
            {"hypothesis_id": "h1", "p_value": 0.005, "declared_threshold": 0.01, "rejected": True},
            {"hypothesis_id": "h2", "p_value": 0.03, "declared_threshold": 0.04, "rejected": True},
        ],
    )
    assert receipt["verified_observations"][1]["rejections_before"] == 1
    assert receipt["verified_observations"][1]["threshold"] == 0.04


def test_generic_alpha_or_e_budget_and_disabled_mode_are_rejected() -> None:
    generic = _sealed(
        {
            "regime": ALPHA_SPENDING,
            "procedure_id": ALPHA_SPENDING_PROCEDURE,
            "assumption_class": "ARBITRARY_DEPENDENCE",
            "family_alpha": 0.05,
            "alpha_or_e_budget": 0.05,
            "preregistration_sha256": "a" * 64,
            "hypothesis_order": ["h1"],
            "allocation": [0.05],
        }
    )
    with pytest.raises(ErrorControlError, match="ambiguous budget"):
        evaluate_error_control(generic, [])

    disabled = _sealed(
        {
            "regime": "DISABLED_DECLARED",
            "procedure_id": "NONE",
            "assumption_class": "NONE",
            "family_alpha": 0.05,
            "preregistration_sha256": "a" * 64,
            "hypothesis_order": ["h1"],
            "allocation": [0.05],
        }
    )
    with pytest.raises(ErrorControlError, match="unsupported regime"):
        evaluate_error_control(disabled, [])


def test_wrong_threshold_or_family_order_fails_closed() -> None:
    protocol = _sealed(
        {
            "regime": ALPHA_SPENDING,
            "procedure_id": ALPHA_SPENDING_PROCEDURE,
            "assumption_class": "ARBITRARY_DEPENDENCE",
            "family_alpha": 0.05,
            "preregistration_sha256": "c" * 64,
            "hypothesis_order": ["h1"],
            "allocation": [0.05],
        }
    )
    with pytest.raises(ErrorControlError, match="threshold does not recompute"):
        evaluate_error_control(
            protocol,
            [
                {
                    "hypothesis_id": "h1",
                    "p_value": 0.1,
                    "declared_threshold": 0.04,
                    "rejected": False,
                }
            ],
        )


def test_every_holdout_outcome_access_consumes_budget_even_no_action() -> None:
    ledger = HoldoutExposureLedger(
        ledger_id="holdout-1",
        split_binding="split-frozen-v1",
        preregistration_sha256="d" * 64,
        max_accesses=1,
    )
    first = ledger.debit(
        access_id="access-1",
        query_sha256="e" * 64,
        outcome_artifact_sha256="f" * 64,
        purpose="confirmation",
        downstream_action="NO_ACTION",
    )
    assert first["access_id"] == "access-1"
    snapshot = ledger.snapshot()
    assert snapshot["accesses_used"] == 1
    assert snapshot["no_action_is_free_access"] is False
    with pytest.raises(HoldoutExposureError, match="budget exceeded"):
        ledger.debit(
            access_id="access-2",
            query_sha256="1" * 64,
            outcome_artifact_sha256="2" * 64,
            purpose="confirmation",
            downstream_action="NO_ACTION",
        )
    assert ledger.snapshot()["revoked"] is True


def test_holdout_exact_replay_is_idempotent_but_conflict_revokes() -> None:
    ledger = HoldoutExposureLedger(
        ledger_id="holdout-1",
        split_binding="split-frozen-v1",
        preregistration_sha256="d" * 64,
        max_accesses=2,
    )
    kwargs = {
        "access_id": "access-1",
        "query_sha256": "e" * 64,
        "outcome_artifact_sha256": "f" * 64,
        "purpose": "confirmation",
        "downstream_action": "NO_ACTION",
    }
    assert ledger.debit(**kwargs) == ledger.debit(**kwargs)
    assert ledger.snapshot()["accesses_used"] == 1
    with pytest.raises(HoldoutExposureError, match="conflicting replay"):
        ledger.debit(**{**kwargs, "outcome_artifact_sha256": "0" * 64})
    assert ledger.snapshot()["overexposed"] is True
