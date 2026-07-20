from __future__ import annotations

import asyncio
import hashlib
import uuid

import pytest
from temporalio import activity
from temporalio.common import VersioningBehavior
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.workflow import _Definition as WorkflowDefinition

from services.agent_runtime import foundation_continuous_workflow_v3 as subject


def _sha(character: str) -> str:
    return character * 64


def _proof_binding() -> dict[str, str]:
    return {
        "proof_ref": "proof.json",
        "proof_sha256": _sha("1"),
        "content_sha256": _sha("2"),
        "closure_pack_ref": "foundation_closure_pack.json",
        "closure_pack_file_sha256": _sha("3"),
        "closure_pack_content_sha256": _sha("4"),
    }


def _fresh_parent_state() -> dict[str, object]:
    state = subject._initial_state_v3(
        {
            "operation_id": "v3-temporal-test",
            "runtime_root": "runtime",
            "frontier_ref": "frontier.json",
            "frontier_sha256": _sha("5"),
            "roll_forward_manifest_ref": "roll-forward.json",
            "roll_forward_manifest_sha256": _sha("6"),
            "owner_generation": 1,
            "max_cycles_per_run": 1_000,
            "default_wait_seconds": 86_400,
        }
    )
    state["roll_forward_verification"] = {"ok": True}
    return state


def test_v3_parent_and_child_are_independent_pinned_workflow_types() -> None:
    parent = WorkflowDefinition.from_class(subject.FoundationContinuousWorkflowV3)
    child = WorkflowDefinition.from_class(subject.FoundationWaveChildWorkflowV3)
    assert parent.name == subject.PARENT_WORKFLOW_NAME_V3
    assert child.name == subject.CHILD_WORKFLOW_NAME_V3
    assert parent.versioning_behavior is VersioningBehavior.PINNED
    assert child.versioning_behavior is VersioningBehavior.PINNED
    assert subject.FoundationContinuousWorkflowV3.__mro__[1] is object
    assert subject.FoundationWaveChildWorkflowV3.__mro__[1] is object


def test_child_requires_autonomous_phase_frontier_and_closure_proof() -> None:
    base = {
        "operation_id": "child-test",
        "wave_id": "wave-1",
        "correlation_id": "correlation-1",
        "frontier_ref": "frontier.json",
        "frontier_sha256": _sha("5"),
        "foundation_closure_gate_proof": _proof_binding(),
    }
    with pytest.raises(ValueError, match="AUTONOMOUS_RESEARCH"):
        subject._initial_child_state_v3(
            {**base, "execution_phase": subject.FOUNDATION_CONSTRUCTION}
        )
    with pytest.raises(ValueError, match="proof binding"):
        subject._initial_child_state_v3(
            {**base, "execution_phase": subject.AUTONOMOUS_RESEARCH, "foundation_closure_gate_proof": {}}
        )
    state = subject._initial_child_state_v3(
        {**base, "execution_phase": subject.AUTONOMOUS_RESEARCH}
    )
    assert state["execution_phase"] == subject.AUTONOMOUS_RESEARCH
    assert state["foundation_closure_gate_proof"] == _proof_binding()


def test_continue_as_new_preserves_and_validates_phase_gate_identity() -> None:
    state = _fresh_parent_state()
    proof = _proof_binding()
    state.update(
        {
            "foundation_closed": True,
            "foundation_closure_gate_proof": proof,
            "foundation_closure": {
                "foundation_closure_proof_content_sha256": proof["content_sha256"]
            },
            "gate_state": subject.AUTONOMOUS_RESEARCH,
            "execution_phase": subject.AUTONOMOUS_RESEARCH,
            "milestone_recorded_revision": 10,
            "formal_gate_opened_revision": 12,
        }
    )
    continued = subject._continuation_input_v3(state)["resume_state"]
    assert continued["foundation_closure_gate_proof"] == proof
    assert continued["gate_state"] == subject.AUTONOMOUS_RESEARCH
    assert set(continued["closed_work_keys_by_phase"]) == {
        subject.FOUNDATION_CONSTRUCTION,
        subject.AUTONOMOUS_RESEARCH,
    }

    tampered = dict(state)
    tampered["foundation_closure_gate_proof"] = {}
    with pytest.raises(ValueError, match="lacks its proof milestone"):
        subject._continuation_input_v3(tampered)


def test_temporal_history_records_proof_then_milestone_then_formal_gate() -> None:
    gate_calls: list[int] = []
    proof_calls: list[int] = []

    async def run() -> tuple[dict[str, object], list[int], list[int]]:
        formal_wait_persisted = asyncio.Event()

        @activity.defn(name="xinao.foundation.persist_state")
        async def persist(payload: dict[str, object]) -> dict[str, str]:
            snapshot = payload["snapshot"]
            assert isinstance(snapshot, dict)
            decision = snapshot.get("last_decision")
            if (
                isinstance(decision, dict)
                and decision.get("reason") == "AUTONOMOUS_COMPILER_UNAVAILABLE"
            ):
                formal_wait_persisted.set()
            snapshot_hash = hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()
            return {
                "artifact_ref": f"state-{snapshot_hash}.json",
                "snapshot_hash": snapshot_hash,
            }

        @activity.defn(name="xinao.foundation.v3.inspect_phase_gate")
        async def inspect_gate(payload: dict[str, object]) -> dict[str, object]:
            gate_calls.append(len(gate_calls) + 1)
            call = gate_calls[-1]
            if call == 1:
                return {
                    "action": "VERIFY_CLOSURE_PROOF",
                    "formal_research_allowed": False,
                    "foundation_closure_pack_ref": "foundation_closure_pack.json",
                    "foundation_closure_pack_sha256": _sha("3"),
                }
            if call == 2:
                return {
                    "action": "MILESTONE",
                    "formal_research_allowed": False,
                    "foundation_closure_proof_content_sha256": _sha("2"),
                    "foundation_closure_pack_file_sha256": _sha("3"),
                    "foundation_closure_pack_content_sha256": _sha("4"),
                    "wait_seconds": 5,
                }
            return {
                "action": "ALLOW_AUTONOMOUS_RESEARCH",
                "formal_research_allowed": True,
                "foundation_closure_proof_content_sha256": _sha("2"),
                "wait_seconds": 86_400,
            }

        @activity.defn(name="xinao.foundation.v3.verify_closure_pack")
        async def verify_pack(payload: dict[str, object]) -> dict[str, object]:
            proof_calls.append(len(proof_calls) + 1)
            binding = _proof_binding()
            return {
                "ok": True,
                "proof_ref": binding["proof_ref"],
                "proof_sha256": binding["proof_sha256"],
                "proof": {
                    "content_sha256": binding["content_sha256"],
                    "closure_pack_ref": binding["closure_pack_ref"],
                    "closure_pack_file_sha256": binding["closure_pack_file_sha256"],
                    "closure_pack_content_sha256": binding[
                        "closure_pack_content_sha256"
                    ],
                },
            }

        task_queue = f"foundation-v3-test-{uuid.uuid4().hex}"
        workflow_id = f"foundation-v3-test-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[subject.FoundationContinuousWorkflowV3],
                activities=[persist, inspect_gate, verify_pack],
            ):
                handle = await environment.client.start_workflow(
                    subject.FoundationContinuousWorkflowV3.run,
                    {"resume_state": _fresh_parent_state()},
                    id=workflow_id,
                    task_queue=task_queue,
                )
                await asyncio.wait_for(formal_wait_persisted.wait(), timeout=10)
                await handle.execute_update(
                    subject.FoundationContinuousWorkflowV3.control,
                    {
                        "action": "STOP",
                        "operation_id": "temporal-test-stop",
                        "reason": "test observed the formal gate boundary",
                    },
                )
                result = await handle.result()
                return result, list(gate_calls), list(proof_calls)

    result, recorded_gate_calls, recorded_proof_calls = asyncio.run(run())
    assert recorded_gate_calls[:4] == [1, 2, 3, 4]
    assert recorded_proof_calls == [1]
    assert result["status"] == "STOPPED"
    assert result["gate_state"] == subject.AUTONOMOUS_RESEARCH
    assert result["execution_phase"] == subject.AUTONOMOUS_RESEARCH
    assert result["milestone_recorded_revision"] < result["formal_gate_opened_revision"]
    assert result["foundation_closure_gate_proof"] == _proof_binding()
    assert result["formal_route_counts"] == {
        "allocation": 0,
        "delegate": 0,
        "worker": 0,
    }
    assert result["current_wave"] is None


def test_v3_exports_are_self_contained_and_activity_names_are_unique() -> None:
    workflows, activities = subject.temporal_exports_v3()
    assert workflows == [
        subject.FoundationContinuousWorkflowV3,
        subject.FoundationWaveChildWorkflowV3,
    ]
    names = [activity._defn.name for activity in activities]
    assert len(names) == len(set(names))
    assert set(names) == {
        "xinao.foundation.persist_state",
        "xinao.foundation.v2.verify_roll_forward",
        "xinao.foundation.v3.inspect_phase_gate",
        "xinao.foundation.v3.verify_closure_pack",
        "xinao.foundation.v3.verify_wave_result",
    }
