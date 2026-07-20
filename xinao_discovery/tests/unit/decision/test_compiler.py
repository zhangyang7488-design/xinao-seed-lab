from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xinao.decision import DecisionGateInput, compile_decision_plan, freeze_decision

HASH = "a" * 64
OPEN = datetime(2026, 7, 20, 8, tzinfo=UTC)


def gate(**updates: object) -> DecisionGateInput:
    values: dict[str, object] = {
        "candidate_ref": "candidate.signal.v1",
        "validation_report_ref": "validation.signal.v1",
        "validation_output_hash": HASH,
        "validation_verdict": "ACTION",
        "baseline_ref": "baseline-odds-water.v1",
        "baseline_active": True,
        "rule_ref": "special-number-rule.v1",
        "rule_active": True,
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


def test_all_mechanical_gates_pass_to_action_and_freeze() -> None:
    plan = compile_decision_plan(gate(), plan_ref="decision-plan.action.v1")
    frozen = freeze_decision(
        plan,
        decision_ref="frozen-decision.action.v1",
        frozen_at=OPEN - timedelta(minutes=6),
    )

    assert plan.decision_type == "ACTION"
    assert plan.no_action_reasons == ()
    assert plan.plan_hash is not None
    assert frozen.decision_type == "ACTION"
    assert frozen.decision_hash is not None


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

    assert plan.decision_type == "NO_ACTION"
    assert plan.stake == "0.0000"
    assert reason in plan.no_action_reasons


def test_late_freeze_and_unsealed_plan_fail_closed() -> None:
    plan = compile_decision_plan(gate(), plan_ref="decision-plan.action.v1")
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
