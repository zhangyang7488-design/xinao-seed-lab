from __future__ import annotations

from copy import deepcopy

import pytest
from services.agent_runtime.integrated_bus_workflow_registry import registry_summary
from services.agent_runtime.xinao_mainline_canary import (
    _accept_fact,
    _initial_state,
    _snapshot,
)


def fact(fact_id: str = "settlement", fact_hash: str = "a" * 64) -> dict[str, str]:
    return {
        "fact_id": fact_id,
        "kind": "SettlementRecord",
        "ref": f"evidence://{fact_id}",
        "fact_hash": fact_hash,
    }


def test_mainline_fact_signal_is_idempotent_and_conflict_stops() -> None:
    state = _initial_state(
        {
            "operation_id": "p8-unit",
            "expected_fact_ids": ["settlement", "lineage"],
            "seed_facts": [fact()],
        }
    )
    _accept_fact(state, fact())
    assert _snapshot(state)["fact_count"] == 1
    assert state["duplicate_signals"] == 1

    _accept_fact(state, fact(fact_hash="b" * 64))
    assert state["stop_requested"] is True
    assert _snapshot(state)["status"] == "CONFLICTED"


def test_snapshot_query_shape_is_pure_and_hash_stable() -> None:
    state = _initial_state(
        {
            "operation_id": "p8-unit",
            "expected_fact_ids": ["settlement"],
            "seed_facts": [fact()],
        }
    )
    before = deepcopy(state)
    first = _snapshot(state)
    second = _snapshot(state)

    assert state == before
    assert first == second
    assert first["complete"] is True
    assert first["status"] == "COMPLETED"


def test_invalid_fact_and_seed_identity_conflict_fail_closed() -> None:
    with pytest.raises(ValueError, match="sha256"):
        _accept_fact(
            _initial_state({"operation_id": "p8-unit"}),
            fact(fact_hash="bad"),
        )
    with pytest.raises(ValueError, match="identity conflict"):
        _initial_state(
            {
                "operation_id": "p8-unit",
                "seed_facts": [fact(), fact(fact_hash="b" * 64)],
            }
        )


def test_canonical_worker_registry_contains_p8_workflows() -> None:
    summary = registry_summary()
    assert "xinao-mainline-canary-queue" in summary["task_queues"]
    assert "XinaoMainlineCanaryWorkflow" in summary["workflows_registered"]
    assert "XinaoResearchCampaignWorkflow" in summary["workflows_registered"]
