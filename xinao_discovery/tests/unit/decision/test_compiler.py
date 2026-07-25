from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from xinao.decision import (
    CandidateQualification,
    DecisionGateInput,
    DecisionKind,
    compile_decision_plan,
    freeze_decision,
)

HASH = "a" * 64
OPEN = datetime(2026, 7, 20, 8, tzinfo=UTC)


def gate(**updates: object) -> DecisionGateInput:
    values: dict[str, object] = {
        "candidate_ref": "candidate.signal.v1",
        "requested_decision_kind": "FROZEN_EXPERIMENTAL_SHADOW",
        "candidate_qualification": "SHADOW_EXPERIMENTAL",
        "adjudicated_decision_kinds": (
            "FROZEN_EXPERIMENTAL_SHADOW",
            "NO_ACTION",
        ),
        "court_verdict_bundle_ref": "courts.signal.v1",
        "court_verdict_bundle_content_hash": "b" * 64,
        "protocol_pin_ref": "protocol.signal.v1",
        "protocol_pin_sha256": "c" * 64,
        "information_set_ref": "features.signal.v1",
        "information_set_hash": "d" * 64,
        "validation_report_ref": "validation.signal.v1",
        "validation_output_hash": HASH,
        "validation_verdict": "ACTION",
        "baseline_ref": "baseline-odds-water.v1",
        "baseline_active": True,
        "rule_ref": "special-number-rule.v1",
        "rule_active": True,
        "odds_version_ref": "odds.signal.v1",
        "cost_version_ref": "cost.signal.v1",
        "friction_version_ref": "friction.signal.v1",
        "exposure_policy_ref": "shadow-exposure.minimal.v1",
        "target_ref": "draw.20260720-001",
        "target_window_start": OPEN,
        "target_window_end": OPEN,
        "target_open_time": OPEN,
        "freeze_deadline": OPEN - timedelta(minutes=5),
        "knowledge_cutoff": OPEN - timedelta(minutes=10),
        "compiled_at": OPEN - timedelta(minutes=20),
        "panel": "B",
        "selected_number": 1,
        "stake": "1.0000",
        "lower_expected_net": "0.2000",
        "estimated_cost": "0.0100",
        "risk_limit": "1.0000",
    }
    values.update(updates)
    return DecisionGateInput.model_validate(values)


def test_all_mechanical_gates_pass_to_experimental_shadow_and_freeze() -> None:
    plan = compile_decision_plan(gate(), plan_ref="decision-plan.experimental.v1")
    frozen = freeze_decision(
        plan,
        decision_ref="frozen-decision.experimental.v1",
        frozen_at=OPEN - timedelta(minutes=6),
    )

    assert plan.decision_kind == DecisionKind.FROZEN_EXPERIMENTAL_SHADOW
    assert plan.candidate_qualification == CandidateQualification.SHADOW_EXPERIMENTAL
    assert plan.decision_type == "ACTION"
    assert plan.claim_scope == "EXPERIMENTAL_ONLY"
    assert plan.no_action_reasons == ()
    assert plan.plan_hash is not None
    assert frozen.decision_kind == DecisionKind.FROZEN_EXPERIMENTAL_SHADOW
    assert frozen.candidate_qualification == CandidateQualification.SHADOW_EXPERIMENTAL
    assert frozen.decision_type == "ACTION"
    assert frozen.content_hash == frozen.compute_content_hash()


def test_claim_eligible_kind_requires_matching_court_and_qualification() -> None:
    plan = compile_decision_plan(
        gate(
            requested_decision_kind="FROZEN_ELIGIBLE_ACTION",
            candidate_qualification="SHADOW_CLAIM_ELIGIBLE",
            adjudicated_decision_kinds=(
                "FROZEN_EXPERIMENTAL_SHADOW",
                "FROZEN_ELIGIBLE_ACTION",
                "NO_ACTION",
            ),
        ),
        plan_ref="decision-plan.eligible.v1",
    )

    assert plan.decision_kind == DecisionKind.FROZEN_ELIGIBLE_ACTION
    assert plan.candidate_qualification == CandidateQualification.SHADOW_CLAIM_ELIGIBLE
    assert plan.claim_scope == "CLAIM_ELIGIBLE"


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"validation_verdict": "NO_ACTION"}, "VALIDATION_REJECTED"),
        ({"baseline_active": False}, "BASELINE_INACTIVE"),
        ({"rule_active": False}, "RULE_INACTIVE"),
        (
            {"lower_expected_net": "0.0100", "estimated_cost": "0.0100"},
            "UNCERTAINTY_NOT_POSITIVE_AFTER_COST",
        ),
        ({"stake": "1.0001"}, "RISK_LIMIT_EXCEEDED"),
        ({"freeze_deadline": OPEN}, "INVALID_TEMPORAL_BOUNDARY"),
        ({"compiled_at": OPEN - timedelta(minutes=4)}, "FREEZE_DEADLINE_MISSED"),
    ],
)
def test_any_gate_failure_compiles_to_zero_exposure_no_action(
    updates: dict[str, object], reason: str
) -> None:
    plan = compile_decision_plan(gate(**updates), plan_ref=f"decision-plan.{reason}.v1")

    assert plan.decision_kind == DecisionKind.NO_ACTION
    assert plan.candidate_qualification is None
    assert plan.decision_type == "NO_ACTION"
    assert plan.claim_scope == "NO_ACTION"
    assert plan.stake == "0.0000"
    assert reason in plan.no_action_reasons


def test_explicit_no_action_is_hash_sealed_and_has_no_candidate_qualification() -> None:
    plan = compile_decision_plan(
        gate(
            requested_decision_kind="NO_ACTION",
            candidate_qualification=None,
        ),
        plan_ref="decision-plan.no-action.v1",
    )
    frozen = freeze_decision(
        plan,
        decision_ref="frozen-decision.no-action.v1",
        frozen_at=OPEN - timedelta(minutes=6),
    )

    assert plan.decision_kind == DecisionKind.NO_ACTION
    assert "NO_ACTION_SELECTED" in plan.no_action_reasons
    assert frozen.candidate_qualification is None
    assert frozen.stake == "0.0000"
    assert frozen.content_hash == frozen.compute_content_hash()


def test_alias_qualification_and_court_ineligible_kind_fail_closed() -> None:
    with pytest.raises(ValidationError, match="FROZEN_EXPERIMENTAL_SHADOW"):
        gate(requested_decision_kind="ACTION")
    with pytest.raises(ValidationError, match="candidate qualification"):
        gate(candidate_qualification="SHADOW_CLAIM_ELIGIBLE")
    with pytest.raises(ValidationError, match="not permitted"):
        gate(
            requested_decision_kind="FROZEN_ELIGIBLE_ACTION",
            candidate_qualification="SHADOW_CLAIM_ELIGIBLE",
        )


def test_late_freeze_and_unsealed_plan_fail_closed() -> None:
    plan = compile_decision_plan(gate(), plan_ref="decision-plan.experimental.v1")
    with pytest.raises(ValueError, match="late"):
        freeze_decision(
            plan,
            decision_ref="frozen-decision.late.v1",
            frozen_at=OPEN - timedelta(minutes=4),
        )
    with pytest.raises(ValueError, match="hash sealed"):
        freeze_decision(
            plan.model_copy(update={"plan_hash": None}),
            decision_ref="frozen-decision.unsealed.v1",
            frozen_at=OPEN - timedelta(minutes=6),
        )


def test_tampered_axes_and_content_hash_fail_closed() -> None:
    plan = compile_decision_plan(gate(), plan_ref="decision-plan.experimental.v1")
    with pytest.raises(ValueError, match="qualification"):
        freeze_decision(
            plan.model_copy(
                update={"candidate_qualification": CandidateQualification.SHADOW_CLAIM_ELIGIBLE}
            ),
            decision_ref="frozen-decision.invalid-qualification.v1",
            frozen_at=OPEN - timedelta(minutes=6),
        )

    frozen = freeze_decision(
        plan,
        decision_ref="frozen-decision.experimental.v1",
        frozen_at=OPEN - timedelta(minutes=6),
    )
    with pytest.raises(ValidationError, match="content_hash"):
        type(frozen).model_validate({**frozen.model_dump(mode="json"), "content_hash": "f" * 64})
    with pytest.raises(ValidationError, match="candidate_refs_hash"):
        type(frozen).model_validate(
            {
                **frozen.model_dump(mode="json"),
                "candidate_refs_hash": "f" * 64,
                "content_hash": None,
            }
        )
