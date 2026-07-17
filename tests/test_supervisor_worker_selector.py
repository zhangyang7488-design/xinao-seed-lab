from __future__ import annotations

import pytest
from services.agent_runtime.supervisor_worker_selector import (
    CandidateIdentity,
    WorkerCandidate,
    select_supervisor_worker,
)


def candidate(
    provider_id: str,
    model_id: str,
    *,
    profile_ref: str | None = None,
    transport_id: str = "temporal-docker-langgraph",
    declared_active: bool = True,
    healthy: bool = True,
    positive_benefit: bool = True,
    context_capable: bool = False,
) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "profile_ref": profile_ref or f"profile:{provider_id}",
        "model_id": model_id,
        "transport_id": transport_id,
        "declared_active": declared_active,
        "healthy": healthy,
        "positive_benefit": positive_benefit,
        "context_capable": context_capable,
    }


def identity(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(item["provider_id"]),
        str(item["profile_ref"]),
        str(item["model_id"]),
        str(item["transport_id"]),
    )


def test_input_order_does_not_change_result() -> None:
    candidates = [
        candidate("grok", "grok-4.5"),
        candidate("codex", "codex", context_capable=True),
        candidate("grok", "grok-composer-2.5-fast", healthy=False),
    ]

    forward = select_supervisor_worker(candidates, task_separable=True)
    reverse = select_supervisor_worker(reversed(candidates), task_separable=True)

    assert forward == reverse
    assert forward["decision"] == "decision_required"
    assert [identity(item) for item in forward["eligible_candidates"]] == sorted(
        identity(item) for item in forward["eligible_candidates"]
    )


def test_exact_supervisor_choice_uses_all_four_identity_fields() -> None:
    first = candidate("grok", "grok-4.5", profile_ref="profile:a", transport_id="direct")
    second = candidate("grok", "grok-4.5", profile_ref="profile:b", transport_id="temporal")

    result = select_supervisor_worker(
        [first, second],
        task_separable=True,
        supervisor_choice=CandidateIdentity(
            provider_id="grok",
            profile_ref="profile:b",
            model_id="grok-4.5",
            transport_id="temporal",
        ),
    )

    assert result["decision"] == "selected"
    assert result["decision_reason"] == "explicit_supervisor_choice"
    assert identity(result["selected_candidate"]) == identity(second)


def test_all_admission_facts_are_filtered_with_explicit_reasons() -> None:
    candidates = [
        candidate("inactive", "model", declared_active=False),
        candidate("unhealthy", "model", healthy=False),
        candidate("zero-benefit", "model", positive_benefit=False),
        candidate("no-context", "model", context_capable=False),
        candidate("eligible", "model", context_capable=True),
    ]

    result = select_supervisor_worker(
        candidates,
        task_separable=True,
        context_inheritance_required=True,
    )

    assert result["decision"] == "selected"
    assert result["selected_candidate"]["provider_id"] == "eligible"
    reasons = {
        entry["candidate"]["provider_id"]: entry["reasons"] for entry in result["excluded_reasons"]
    }
    assert reasons == {
        "inactive": ["not_declared_active", "context_inheritance_unsupported"],
        "no-context": ["context_inheritance_unsupported"],
        "unhealthy": ["unhealthy", "context_inheritance_unsupported"],
        "zero-benefit": ["no_positive_benefit", "context_inheritance_unsupported"],
    }


def test_inseparable_task_returns_no_action_without_hiding_eligible_candidates() -> None:
    result = select_supervisor_worker(
        [candidate("grok", "grok-4.5")],
        task_separable=False,
    )

    assert result["decision"] == "no_action"
    assert result["decision_reason"] == "task_not_separable"
    assert result["selected_candidate"] is None
    assert len(result["eligible_candidates"]) == 1


def test_no_positive_benefit_returns_no_action() -> None:
    result = select_supervisor_worker(
        [
            candidate("grok", "grok-4.5", positive_benefit=False),
            candidate("codex", "codex", positive_benefit=False),
        ],
        task_separable=True,
    )

    assert result["decision"] == "no_action"
    assert result["decision_reason"] == "no_positive_benefit_candidate"
    assert result["eligible_candidates"] == []


def test_context_requirement_keeps_only_context_capable_candidate() -> None:
    result = select_supervisor_worker(
        [
            candidate("grok", "grok-4.5", context_capable=False),
            candidate("codex", "codex", context_capable=True),
        ],
        task_separable=True,
        context_inheritance_required=True,
    )

    assert result["decision"] == "selected"
    assert result["selected_candidate"]["provider_id"] == "codex"
    assert result["decision_reason"] == "sole_eligible_candidate"


def test_stable_preference_applies_to_any_positive_separable_work() -> None:
    candidates = [
        candidate("grok", "grok-4.5"),
        candidate("codex", "codex"),
    ]

    result = select_supervisor_worker(
        candidates,
        task_separable=True,
        stable_preferred_provider_id="grok",
    )

    assert result["decision"] == "selected"
    assert result["selected_candidate"]["provider_id"] == "grok"
    assert result["decision_reason"] == "stable_provider_preference"


def test_capacity_preference_uses_current_remaining_quota_without_reset_math() -> None:
    result = select_supervisor_worker(
        [candidate("grok", "grok-4.5"), candidate("codex", "codex")],
        task_separable=True,
        capacity_by_provider={
            "grok": {"remaining_percent": 96},
            "codex": {"remaining_percent": 21},
        },
    )

    assert result["decision"] == "selected"
    assert result["selected_candidate"]["provider_id"] == "grok"
    assert result["decision_reason"] == "capacity_provider_preference"


def test_provider_preference_does_not_choose_model_or_transport() -> None:
    result = select_supervisor_worker(
        [
            candidate("grok", "grok-4.5"),
            candidate("grok", "grok-4", profile_ref="profile:other"),
            candidate("codex", "codex"),
        ],
        task_separable=True,
        stable_preferred_provider_id="grok",
    )

    assert result["decision"] == "decision_required"
    assert result["decision_reason"] == "preferred_provider_requires_exact_candidate_choice"
    assert result["provider_preference"]["preferred_provider_id"] == "grok"


def test_unavailable_explicit_choice_does_not_create_a_fallback_chain() -> None:
    result = select_supervisor_worker(
        [
            candidate("grok", "grok-composer-2.5-fast", healthy=False),
            candidate("grok", "grok-4.5"),
            candidate("codex", "codex"),
        ],
        task_separable=True,
        supervisor_choice={
            "provider_id": "grok",
            "profile_ref": "profile:grok",
            "model_id": "grok-composer-2.5-fast",
            "transport_id": "temporal-docker-langgraph",
        },
    )

    assert result["decision"] == "decision_required"
    assert result["selected_candidate"] is None
    assert result["decision_reason"] == "explicit_supervisor_choice_not_eligible"


def test_unavailable_explicit_choice_does_not_fall_through_to_sole_candidate() -> None:
    result = select_supervisor_worker(
        [
            candidate("grok", "grok-composer-2.5-fast", healthy=False),
            candidate("grok", "grok-4.5"),
        ],
        task_separable=True,
        supervisor_choice={
            "provider_id": "grok",
            "profile_ref": "profile:grok",
            "model_id": "grok-composer-2.5-fast",
            "transport_id": "temporal-docker-langgraph",
        },
    )

    assert result["decision"] == "decision_required"
    assert result["selected_candidate"] is None
    assert result["decision_reason"] == "explicit_supervisor_choice_not_eligible"


def test_composer_failure_only_removes_composer_candidate() -> None:
    result = select_supervisor_worker(
        [
            candidate("grok", "grok-composer-2.5-fast", healthy=False),
            candidate("grok", "grok-4.5"),
            candidate("codex", "codex", context_capable=True),
        ],
        task_separable=True,
    )

    assert result["decision"] == "decision_required"
    assert {item["model_id"] for item in result["eligible_candidates"]} == {
        "grok-4.5",
        "codex",
    }
    assert result["excluded_reasons"][0]["candidate"]["model_id"] == ("grok-composer-2.5-fast")
    assert result["excluded_reasons"][0]["reasons"] == ["unhealthy"]


@pytest.mark.parametrize(
    ("unhealthy_provider", "remaining_provider"),
    [("codex", "grok"), ("grok", "codex")],
)
def test_one_provider_failure_does_not_freeze_the_other(
    unhealthy_provider: str,
    remaining_provider: str,
) -> None:
    model_by_provider = {"grok": "grok-4.5", "codex": "codex"}
    result = select_supervisor_worker(
        [
            candidate(
                provider,
                model,
                healthy=provider != unhealthy_provider,
            )
            for provider, model in model_by_provider.items()
        ],
        task_separable=True,
    )

    assert result["decision"] == "selected"
    assert result["selected_candidate"]["provider_id"] == remaining_provider


def test_duplicate_exact_identity_is_rejected_instead_of_order_dependent_merging() -> None:
    item = candidate("grok", "grok-4.5")

    with pytest.raises(ValueError, match="identities must be unique"):
        select_supervisor_worker([item, dict(item)], task_separable=True)


def test_dataclass_inputs_reject_incomplete_identity_and_non_boolean_facts() -> None:
    with pytest.raises(ValueError, match="model_id"):
        CandidateIdentity("grok", "profile:grok", "", "direct")

    with pytest.raises(TypeError, match="healthy"):
        WorkerCandidate(
            identity=CandidateIdentity("grok", "profile:grok", "grok-4.5", "direct"),
            declared_active=True,
            healthy=1,  # type: ignore[arg-type]
            positive_benefit=True,
        )
