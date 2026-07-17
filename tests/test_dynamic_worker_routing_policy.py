from __future__ import annotations

import json
from pathlib import Path

import pytest
from services.agent_runtime.routing_policy_reader import (
    CODEX_SUBAGENT_PROVIDER_ID,
    DEFAULT_DRAFT_WORKER,
    GROK_PROVIDER_ID,
    draft_model,
    draft_worker_target,
    load_routing_policy,
    resolve_supervisor_worker_decision,
)


def _dynamic_policy(*, frozen_workers: list[str] | None = None) -> dict[str, object]:
    return {
        "policy_version": "xinao.routing-policy.v4-positive-benefit-dynamic",
        "default_strategy": "benefit_driven_provider_and_transport_resolution",
        "model_worker_policy": "positive_benefit_dynamic",
        "default_draft_worker": "caller_resolved",
        "stable_preferred_provider_id": GROK_PROVIDER_ID,
        "provider_preference_scope": "all_positive_benefit_separable_work",
        "worker_output_authority": "non_authoritative_candidate",
        "quota_capacity_bindings": {
            GROK_PROVIDER_ID: {"source_key": "grok"},
            CODEX_SUBAGENT_PROVIDER_ID: {
                "source_key": "codex",
                "bucket_id": "codex",
            },
        },
        "allowed_provider_ids": [GROK_PROVIDER_ID, CODEX_SUBAGENT_PROVIDER_ID],
        "frozen_workers": list(frozen_workers or []),
        "routes": [
            {
                "target": "grok",
                "provider_id": GROK_PROVIDER_ID,
                "worker_id": "grok_dynamic_worker",
                "route_role": "worker_candidate",
                "profile_ref": "grok.com.cached_profile",
                "model_id": "grok-composer-2.5-fast",
                "transport_id": "temporal-docker-langgraph",
                "preferred_model": "grok-composer-2.5-fast",
            },
            {
                "target": "codex_subagent",
                "provider_id": CODEX_SUBAGENT_PROVIDER_ID,
                "worker_id": "codex_contextual_subagent",
                "route_role": "contextual_codex_subagent",
                "profile_ref": "current_codex_session",
                "model_id": "current_codex_session",
                "transport_id": "in-turn-agent",
                "preferred_model": "current_codex_session",
            },
            {
                "target": "grok_45",
                "provider_id": GROK_PROVIDER_ID,
                "worker_id": "grok_45_worker",
                "route_role": "worker_candidate",
                "profile_ref": "grok.com.cached_profile",
                "model_id": "grok-4.5",
                "transport_id": "temporal-docker-langgraph",
                "preferred_model": "grok-4.5",
            },
        ],
    }


def _write_policy(runtime: Path, payload: dict[str, object]) -> None:
    path = runtime / "agent_runtime" / "routing_policy.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_reader_preserves_all_active_dynamic_provider_candidates(tmp_path: Path) -> None:
    _write_policy(tmp_path, _dynamic_policy())

    policy = load_routing_policy(runtime_root=tmp_path)

    assert policy["model_worker_policy"] == "positive_benefit_dynamic"
    assert policy["stable_preferred_provider_id"] == GROK_PROVIDER_ID
    assert policy["provider_preference_scope"] == "all_positive_benefit_separable_work"
    assert policy["worker_output_authority"] == "non_authoritative_candidate"
    assert policy["quota_capacity_bindings"][GROK_PROVIDER_ID] == {"source_key": "grok"}
    assert policy["allowed_provider_ids"] == [GROK_PROVIDER_ID, CODEX_SUBAGENT_PROVIDER_ID]
    assert {route["provider_id"] for route in policy["routes"]} == {
        GROK_PROVIDER_ID,
        CODEX_SUBAGENT_PROVIDER_ID,
    }
    assert policy["inactive_routes"] == []
    assert policy["route_by_target"]["codex_subagent"]["worker_id"] == (
        "codex_contextual_subagent"
    )
    assert "frozen_non_grok_routes" not in policy


def test_one_frozen_candidate_does_not_freeze_the_other_provider(tmp_path: Path) -> None:
    _write_policy(tmp_path, _dynamic_policy(frozen_workers=["grok_dynamic_worker"]))

    policy = load_routing_policy(runtime_root=tmp_path)

    assert [route["provider_id"] for route in policy["routes"]] == [
        CODEX_SUBAGENT_PROVIDER_ID,
        GROK_PROVIDER_ID,
    ]
    assert [route["target"] for route in policy["routes"]] == [
        "codex_subagent",
        "grok_45",
    ]
    assert [route["provider_id"] for route in policy["inactive_routes"]] == [
        GROK_PROVIDER_ID,
    ]
    assert policy["model_worker_policy"] == "positive_benefit_dynamic"
    assert draft_worker_target(runtime_root=tmp_path) == DEFAULT_DRAFT_WORKER
    with pytest.raises(ValueError, match="explicitly selected active Grok model"):
        draft_model(runtime_root=tmp_path, candidate="grok-composer-2.5-fast")


def test_selected_grok_route_keeps_exact_model_semantics(tmp_path: Path) -> None:
    _write_policy(tmp_path, _dynamic_policy())

    assert draft_worker_target(runtime_root=tmp_path) == DEFAULT_DRAFT_WORKER
    assert (
        draft_model(runtime_root=tmp_path, candidate="grok-composer-2.5-fast")
        == "grok-composer-2.5-fast"
    )
    assert draft_model(runtime_root=tmp_path, candidate="grok-4.5") == "grok-4.5"


def test_declared_single_provider_policy_is_read_without_inventing_another(tmp_path: Path) -> None:
    payload = _dynamic_policy()
    payload["allowed_provider_ids"] = [CODEX_SUBAGENT_PROVIDER_ID]
    _write_policy(tmp_path, payload)

    policy = load_routing_policy(runtime_root=tmp_path)

    assert policy["allowed_provider_ids"] == [CODEX_SUBAGENT_PROVIDER_ID]
    assert [route["provider_id"] for route in policy["routes"]] == [
        CODEX_SUBAGENT_PROVIDER_ID
    ]
    assert [route["provider_id"] for route in policy["inactive_routes"]] == [
        GROK_PROVIDER_ID,
        GROK_PROVIDER_ID
    ]


def test_missing_policy_does_not_invent_provider_or_model(tmp_path: Path) -> None:
    policy = load_routing_policy(runtime_root=tmp_path)

    assert policy["policy_present"] is False
    assert policy["allowed_provider_ids"] == []
    assert policy["routes"] == []
    assert draft_worker_target(runtime_root=tmp_path) == DEFAULT_DRAFT_WORKER
    with pytest.raises(ValueError, match="not present|not active|explicitly selected"):
        draft_model(runtime_root=tmp_path, candidate="grok-4.5")


def test_production_bridge_binds_exact_policy_candidate_and_hash(tmp_path: Path) -> None:
    _write_policy(tmp_path, _dynamic_policy())
    identity = {
        "provider_id": GROK_PROVIDER_ID,
        "profile_ref": "grok.com.cached_profile",
        "model_id": "grok-composer-2.5-fast",
        "transport_id": "temporal-docker-langgraph",
    }

    decision = resolve_supervisor_worker_decision(
        {
            "task_separable": True,
            "candidates": [
                {
                    **identity,
                    "declared_active": True,
                    "healthy": True,
                    "positive_benefit": True,
                    "context_capable": False,
                }
            ],
            "supervisor_choice": identity,
        },
        runtime_root=tmp_path,
    )

    assert decision["decision"] == "selected"
    assert decision["selected_candidate"]["model_id"] == "grok-composer-2.5-fast"
    assert len(decision["policy_sha256"]) == 64
    assert len(decision["decision_sha256"]) == 64


def test_production_bridge_applies_replaceable_default_and_capacity_evidence(
    tmp_path: Path,
) -> None:
    _write_policy(tmp_path, _dynamic_policy())
    decision = resolve_supervisor_worker_decision(
        {
            "task_separable": True,
            "candidates": [
                {
                    "provider_id": GROK_PROVIDER_ID,
                    "profile_ref": "grok.com.cached_profile",
                    "model_id": "grok-4.5",
                    "transport_id": "temporal-docker-langgraph",
                    "declared_active": True,
                    "healthy": True,
                    "positive_benefit": True,
                },
                {
                    "provider_id": CODEX_SUBAGENT_PROVIDER_ID,
                    "profile_ref": "current_codex_session",
                    "model_id": "current_codex_session",
                    "transport_id": "in-turn-agent",
                    "declared_active": True,
                    "healthy": True,
                    "positive_benefit": True,
                },
            ],
            "quota_result": {
                "grok": {
                    "remainingPercent": 96,
                    "resetAt": "2026-07-19T02:52:23Z",
                },
                "codex": {
                    "buckets": [
                        {
                            "id": "codex",
                            "primary": {
                                "remainingPercent": 21,
                                "resetAt": "2026-07-23T09:14:29Z",
                            },
                        }
                    ]
                },
            },
        },
        runtime_root=tmp_path,
    )

    assert decision["decision"] == "selected"
    assert decision["selected_candidate"]["provider_id"] == GROK_PROVIDER_ID
    assert decision["decision_reason"] == "stable_provider_preference"
    assert decision["provider_preference"]["preference_basis"] == [
        "stable_default",
        "remaining_capacity_reinforces_default",
        "earlier_reset_reinforces_preference",
    ]


def test_production_bridge_rejects_caller_admission_drift(tmp_path: Path) -> None:
    _write_policy(tmp_path, _dynamic_policy())
    with pytest.raises(ValueError, match="declared_active disagrees"):
        resolve_supervisor_worker_decision(
            {
                "task_separable": True,
                "candidates": [
                    {
                        "provider_id": GROK_PROVIDER_ID,
                        "profile_ref": "grok.com.cached_profile",
                        "model_id": "grok-4",
                        "transport_id": "temporal-docker-langgraph",
                        "declared_active": True,
                        "healthy": True,
                        "positive_benefit": True,
                    }
                ],
            },
            runtime_root=tmp_path,
        )
