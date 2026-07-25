from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xinao.decision import (
    DecisionGateInput,
    DecisionKind,
    compile_decision_plan,
    freeze_decision,
)
from xinao.settlement import (
    OutcomeObservation,
    admit_outcome,
    admit_settlement,
    settle_frozen_decision,
)

OPEN = datetime(2026, 7, 20, 8, tzinfo=UTC)


def frozen_shadow(
    *,
    decision_kind: str = "FROZEN_EXPERIMENTAL_SHADOW",
    qualification: str | None = "SHADOW_EXPERIMENTAL",
):
    plan = compile_decision_plan(
        DecisionGateInput(
            candidate_ref="candidate.signal.v1",
            requested_decision_kind=decision_kind,
            candidate_qualification=qualification,
            adjudicated_decision_kinds=(
                "FROZEN_EXPERIMENTAL_SHADOW",
                "FROZEN_ELIGIBLE_ACTION",
                "NO_ACTION",
            ),
            court_verdict_bundle_ref="courts.signal.v1",
            court_verdict_bundle_content_hash="b" * 64,
            protocol_pin_ref="protocol.signal.v1",
            protocol_pin_sha256="c" * 64,
            information_set_ref="features.signal.v1",
            information_set_hash="d" * 64,
            validation_report_ref="validation.signal.v1",
            validation_output_hash="a" * 64,
            validation_verdict="ACTION",
            baseline_ref="baseline-odds-water.v1",
            baseline_active=True,
            rule_ref="special-number-rule.v1",
            rule_active=True,
            odds_version_ref="odds.signal.v1",
            cost_version_ref="cost.signal.v1",
            friction_version_ref="friction.signal.v1",
            exposure_policy_ref="shadow-exposure.minimal.v1",
            target_ref="draw.20260720-001",
            target_window_start=OPEN,
            target_window_end=OPEN,
            target_open_time=OPEN,
            freeze_deadline=OPEN - timedelta(minutes=5),
            knowledge_cutoff=OPEN - timedelta(minutes=10),
            compiled_at=OPEN - timedelta(minutes=20),
            panel="B",
            selected_number=1,
            stake="1.0000",
            lower_expected_net="0.2000",
            estimated_cost="0.0100",
            risk_limit="1.0000",
        ),
        plan_ref=f"decision-plan.{decision_kind.lower()}.v1",
    )
    return freeze_decision(
        plan,
        decision_ref=f"frozen-decision.{decision_kind.lower()}.v1",
        frozen_at=OPEN - timedelta(minutes=6),
    )


def outcome(*, ref: str = "outcome.1", special_number: int = 1, verified: bool = True):
    return OutcomeObservation(
        outcome_ref=ref,
        source_ref="macaujc2",
        target_ref="draw.20260720-001",
        actual_special_number=special_number,
        observed_at=OPEN + timedelta(hours=1),
        verified=verified,
    ).with_hash()


def test_duplicate_outcome_and_conflicting_outcome_are_distinct_states() -> None:
    first = outcome()
    duplicate = first.model_copy(update={"outcome_ref": "outcome.duplicate"}).with_hash()
    same = first.model_copy()
    conflict = outcome(ref="outcome.conflict", special_number=2)

    assert admit_outcome((first,), same).status == "DUPLICATE"
    assert admit_outcome((first,), duplicate).status == "DUPLICATE"
    assert admit_outcome((first,), conflict).status == "CONFLICT"
    assert admit_outcome((), outcome(ref="outcome.raw", verified=False)).status == "QUARANTINED"


def test_same_frozen_input_has_same_settlement_hash_and_duplicate_admission() -> None:
    kwargs = {
        "frozen": frozen_shadow(),
        "outcome": outcome(),
        "settlement_ref": "settlement.1",
        "journal_group_ref": "journal.settlement.1",
        "portfolio_ref": "shadow.v1",
        "occurred_at": OPEN + timedelta(hours=2),
    }
    first = settle_frozen_decision(**kwargs)
    second = settle_frozen_decision(**kwargs)

    assert first == second
    assert first.record.settlement_hash is not None
    assert admit_settlement((first.record,), second.record) == "DUPLICATE"


def test_changed_result_for_same_freeze_pauses_settlement() -> None:
    first = settle_frozen_decision(
        frozen=frozen_shadow(),
        outcome=outcome(),
        settlement_ref="settlement.1",
        journal_group_ref="journal.settlement.1",
        portfolio_ref="shadow.v1",
        occurred_at=OPEN + timedelta(hours=2),
    )
    conflict = settle_frozen_decision(
        frozen=frozen_shadow(),
        outcome=outcome(ref="outcome.2", special_number=2),
        settlement_ref="settlement.2",
        journal_group_ref="journal.settlement.2",
        portfolio_ref="shadow.v1",
        occurred_at=OPEN + timedelta(hours=2),
    )

    with pytest.raises(ValueError, match="pause"):
        admit_settlement((first.record,), conflict.record)


def test_claim_eligible_shadow_also_settles_without_promoting_experimental() -> None:
    experimental = frozen_shadow()
    eligible = frozen_shadow(
        decision_kind="FROZEN_ELIGIBLE_ACTION",
        qualification="SHADOW_CLAIM_ELIGIBLE",
    )

    assert experimental.decision_kind == DecisionKind.FROZEN_EXPERIMENTAL_SHADOW
    assert eligible.decision_kind == DecisionKind.FROZEN_ELIGIBLE_ACTION
    bundle = settle_frozen_decision(
        frozen=eligible,
        outcome=outcome(),
        settlement_ref="settlement.eligible",
        journal_group_ref="journal.settlement.eligible",
        portfolio_ref="shadow.v1",
        occurred_at=OPEN + timedelta(hours=2),
    )
    assert bundle.record.frozen_decision_hash == eligible.content_hash


def test_no_action_and_legacy_action_without_kind_cannot_settle() -> None:
    no_action = frozen_shadow(decision_kind="NO_ACTION", qualification=None)
    with pytest.raises(ValueError, match="exact frozen shadow"):
        settle_frozen_decision(
            frozen=no_action,
            outcome=outcome(),
            settlement_ref="settlement.no-action",
            journal_group_ref="journal.settlement.no-action",
            portfolio_ref="shadow.v1",
            occurred_at=OPEN + timedelta(hours=2),
        )

    experimental = frozen_shadow()
    legacy = type(experimental).model_construct(
        **experimental.model_dump(mode="python", exclude={"decision_kind"})
    )
    with pytest.raises(ValueError, match="exact frozen shadow"):
        settle_frozen_decision(
            frozen=legacy,
            outcome=outcome(),
            settlement_ref="settlement.legacy-action",
            journal_group_ref="journal.settlement.legacy-action",
            portfolio_ref="shadow.v1",
            occurred_at=OPEN + timedelta(hours=2),
        )


def test_constructed_frozen_decision_with_disagreeing_axes_cannot_settle() -> None:
    experimental = frozen_shadow()
    tampered = type(experimental).model_construct(
        **{
            **experimental.model_dump(mode="python"),
            "claim_scope": "CLAIM_ELIGIBLE",
        }
    )

    with pytest.raises(ValueError, match="claim scope"):
        settle_frozen_decision(
            frozen=tampered,
            outcome=outcome(),
            settlement_ref="settlement.invalid-axes",
            journal_group_ref="journal.settlement.invalid-axes",
            portfolio_ref="shadow.v1",
            occurred_at=OPEN + timedelta(hours=2),
        )
