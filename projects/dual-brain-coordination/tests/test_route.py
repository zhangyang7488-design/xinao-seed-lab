from __future__ import annotations

import pytest
from pydantic import ValidationError

from xinao_coordination.models import RouteSignals, assess_route


def test_zero_signals_choose_direct() -> None:
    result = assess_route(RouteSignals())
    assert result.recommendation == "direct"
    assert result.advisory_only is True
    assert "idempotency_and_fencing" in result.hard_invariants


def test_complementary_uncertain_work_chooses_discussion() -> None:
    result = assess_route(RouteSignals(uncertainty=1, complementarity=1, disagreement=0.8, latency_cost=0.1))
    assert result.recommendation == "discuss"
    assert result.net_benefit > 0.15


def test_artifact_changes_terminal_shape_not_cognitive_gate() -> None:
    result = assess_route(RouteSignals(needs_artifact=True, coordination_cost=0.8))
    assert result.recommendation == "task"
    assert result.advisory_only is True


def test_current_request_overrides_formula() -> None:
    result = assess_route(
        RouteSignals(
            uncertainty=1,
            disagreement=1,
            complementarity=1,
            requested_mode="direct",
        )
    )
    assert result.recommendation == "direct"
    assert result.overridden_by_request is True
    assert "explicit_current_request" in result.reasons


def test_signals_are_bounded() -> None:
    with pytest.raises(ValidationError):
        RouteSignals(uncertainty=1.1)


@pytest.mark.parametrize(
    "signals",
    [
        {"uncertainty": float("nan")},
        {"benefit_weights": {"uncertainty": float("nan")}},
        {"cost_weights": {"latency": float("inf")}},
    ],
)
def test_route_rejects_non_finite_numbers(signals: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RouteSignals.model_validate(signals)


def test_context_can_replace_equal_weight_prior_without_becoming_a_gate() -> None:
    result = assess_route(
        RouteSignals(
            impact=1,
            latency_cost=0.8,
            benefit_weights={"impact": 10},
            cost_weights={"latency": 1},
            discussion_margin=0.1,
        )
    )
    assert result.recommendation == "discuss"
    assert result.policy_id == "replaceable_contextual_net_benefit_v1"
    assert result.score_controls_execution is False
    assert "contextual_weights" in result.reasons
