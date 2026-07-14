from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xinao.decision import DecisionGateInput, compile_decision_plan, freeze_decision
from xinao.settlement import (
    OutcomeObservation,
    admit_outcome,
    admit_settlement,
    settle_frozen_decision,
)

OPEN = datetime(2026, 7, 20, 8, tzinfo=UTC)


def frozen_action():
    plan = compile_decision_plan(
        DecisionGateInput(
            candidate_ref="candidate.signal.v1",
            validation_report_ref="validation.signal.v1",
            validation_output_hash="a" * 64,
            validation_verdict="ACTION",
            baseline_ref="baseline-odds-water.v1",
            baseline_active=True,
            rule_ref="special-number-settlement.v0",
            rule_active=True,
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
        plan_ref="decision-plan.action.v1",
    )
    return freeze_decision(
        plan,
        decision_ref="frozen-decision.action.v1",
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
        "frozen": frozen_action(),
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
        frozen=frozen_action(),
        outcome=outcome(),
        settlement_ref="settlement.1",
        journal_group_ref="journal.settlement.1",
        portfolio_ref="shadow.v1",
        occurred_at=OPEN + timedelta(hours=2),
    )
    conflict = settle_frozen_decision(
        frozen=frozen_action(),
        outcome=outcome(ref="outcome.2", special_number=2),
        settlement_ref="settlement.2",
        journal_group_ref="journal.settlement.2",
        portfolio_ref="shadow.v1",
        occurred_at=OPEN + timedelta(hours=2),
    )

    with pytest.raises(ValueError, match="pause"):
        admit_settlement((first.record,), conflict.record)
