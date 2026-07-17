from __future__ import annotations

import pytest
from services.agent_runtime.provider_routing_preference import (
    ProviderCapacitySignal,
    resolve_provider_preference,
)


def test_current_remaining_capacity_is_sufficient_without_burn_forecast() -> None:
    result = resolve_provider_preference(
        ["codex", "grok"],
        capacity_by_provider={
            "codex": {"remaining_percent": 21},
            "grok": {"remaining_percent": 96},
        },
    )

    assert result["preferred_provider_id"] == "grok"
    assert result["preference_basis"] == ["remaining_capacity"]


def test_reset_horizon_is_optional_independent_evidence() -> None:
    result = resolve_provider_preference(
        ["codex", "grok"],
        stable_preferred_provider_id="grok",
        capacity_by_provider={
            "codex": {
                "remainingPercent": 21,
                "resetAt": "2026-07-23T09:14:29Z",
            },
            "grok": {
                "remainingPercent": 96,
                "resetAt": "2026-07-19T02:52:23Z",
            },
        },
    )

    assert result["preferred_provider_id"] == "grok"
    assert result["preference_basis"] == [
        "stable_default",
        "remaining_capacity_reinforces_default",
        "earlier_reset_reinforces_preference",
    ]


def test_default_worker_can_change_by_policy_without_provider_code() -> None:
    result = resolve_provider_preference(
        ["future_worker", "grok"],
        stable_preferred_provider_id="future_worker",
    )

    assert result["preferred_provider_id"] == "future_worker"
    assert result["preference_basis"] == ["stable_default"]


def test_capacity_conflict_returns_control_to_supervisor_instead_of_locking_provider() -> None:
    result = resolve_provider_preference(
        ["future_worker", "grok"],
        stable_preferred_provider_id="grok",
        capacity_by_provider={
            "future_worker": {"remaining_percent": 99},
            "grok": {"remaining_percent": 10},
        },
    )

    assert result["preferred_provider_id"] is None
    assert result["preference_basis"] == [
        "stable_default",
        "remaining_capacity_conflicts_with_default",
    ]


def test_capacity_signal_validation_is_provider_agnostic_and_fail_closed() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        ProviderCapacitySignal("worker-a", remaining_percent=101)
    with pytest.raises(ValueError, match="timezone"):
        ProviderCapacitySignal("worker-a", reset_at="2026-07-19T02:52:23")
