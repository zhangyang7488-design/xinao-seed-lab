from __future__ import annotations

import asyncio
import uuid

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from xinao_coordination.temporal.workflow import (
    REQUIRED_LANGGRAPH_TRUE_CHECKS,
    XinaoPromotedTaskWorkflowV1,
)


@workflow.defn(name="XinaoIntegratedBusWorkflow")
class _StubChildWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> dict:
        result = {name: True for name in REQUIRED_LANGGRAPH_TRUE_CHECKS}
        result.update(
            {
                "content_md": "grok fanin",
                "parallel_succeeded": 3,
                "worker_lane_provider": "grok_acpx_headless",
                "worker_lane_model": "grok-4.5",
                "grok_only_mode": True,
                "grok_fanin_ok": True,
                "grok_fanin_manifest_ref": "/evidence/grok-manifest",
                "grok_fanin_lane_count": 3,
                "non_grok_model_invocations": 0,
                "fallback_model_invocation_performed": False,
                "memory_model_bind_frozen": True,
                "pro_review_provider": "grok_acpx_headless",
                "proof_path": "/evidence/proof",
                "promotion_evidence_ref": "/evidence/promotion",
                "pytest_slice_ref": "/evidence/pytest",
            }
        )
        return result


def test_promoted_workflow_runs_caller_frontier_concurrently_and_fans_in() -> None:
    asyncio.run(_run_promoted_frontier())


def test_promoted_workflow_rejects_partial_frontier() -> None:
    asyncio.run(_run_promoted_frontier(failing_lane="audit"))


async def _run_promoted_frontier(*, failing_lane: str = "") -> None:
    activity_state = {"active": 0, "max_active": 0}
    observed_lineage: dict[str, set[tuple[str, str]]] = {"lanes": set(), "fanin": set()}

    @activity.defn(name="xinao.promoted.validate_envelope")
    async def validate(payload: dict) -> dict:
        return {"ok": True, "phase": "validated"}

    @activity.defn(name="xinao.promoted.record_started")
    async def start(payload: dict) -> dict:
        return {
            "ok": True,
            "phase": "started",
            "intake": {
                "ok": True,
                "artifact_path": "D:/XINAO_RESEARCH_RUNTIME/fake/base.md",
                "container_path": "/evidence/fake/base.md",
            },
        }

    @activity.defn(name="xinao.grok.execute_acpx_lane")
    async def grok_lane(payload: dict) -> dict:
        observed_lineage["lanes"].add(
            (str(payload.get("correlation_id") or ""), str(payload.get("parent_operation_id") or ""))
        )
        activity_state["active"] += 1
        activity_state["max_active"] = max(activity_state["max_active"], activity_state["active"])
        await asyncio.sleep(0.05)
        activity_state["active"] -= 1
        failed = payload["lane_id"] == failing_lane
        return {
            "ok": not failed,
            "provider_id": "grok_acpx_headless",
            "lane_id": payload["lane_id"],
            "mode": payload["mode"],
            "model": "grok-4.5",
            "operation_id": f"op-{payload['lane_id']}",
            "correlation_id": payload.get("correlation_id"),
            "parent_operation_id": payload.get("parent_operation_id"),
            "operation_state": "failed" if failed else "completed",
            "result_text": "" if failed else f"result {payload['lane_id']}",
            "artifacts": [],
        }

    @activity.defn(name="xinao.grok.materialize_acpx_fanin")
    async def fanin(payload: dict) -> dict:
        observed_lineage["fanin"].add(
            (str(payload.get("correlation_id") or ""), str(payload.get("parent_operation_id") or ""))
        )
        return {
            "ok": True,
            "provider_id": "grok_acpx_headless",
            "model": "grok-4.5",
            "correlation_id": payload.get("correlation_id"),
            "parent_operation_id": payload.get("parent_operation_id"),
            "lane_count": len(payload["lane_results"]),
            "ready_width": len(payload["lane_results"]),
            "succeeded": len(payload["lane_results"]),
            "failed": 0,
            "intake": {
                "ok": True,
                "artifact_path": "D:/XINAO_RESEARCH_RUNTIME/fake/fanin.md",
                "container_path": "/evidence/fake/fanin.md",
            },
        }

    @activity.defn(name="xinao.promoted.execute_step")
    async def step(payload: dict) -> dict:
        return {
            "ok": True,
            "phase": "step_done",
            "operation_id": payload["operation_id"],
            "artifact": {"sha256": "step"},
            "langgraph_evidence": {"ok": True},
        }

    @activity.defn(name="xinao.promoted.finalize")
    async def finalize(payload: dict) -> dict:
        return {"ok": True, "phase": "finalized", "kernel": {"ok": True}}

    task_queue = f"grok-frontier-test-{uuid.uuid4().hex}"
    workflow_id = f"grok-frontier-wf-{uuid.uuid4().hex}"
    payload = {
        "task_id": "task-grok-frontier",
        "workflow_id": workflow_id,
        "generation": 0,
        "immutable_intent_hash": "intent",
        "decision_hash": "decision",
        "title": "dynamic frontier",
        "goal": "run independent Grok workers",
        "owner": "admin",
        "correlation_id": "corr-frontier",
        "parent_operation_id": "parent-op-frontier",
        "promoted_only": True,
        "langgraph_child": {
            "enabled": True,
            "task_queue": task_queue,
            "workflow_type": "XinaoIntegratedBusWorkflow",
        },
        "grok_ready_frontier": [
            {"lane_id": "research", "mode": "external_research", "prompt": "research"},
            {"lane_id": "implementation", "mode": "implementation", "prompt": "build"},
            {"lane_id": "audit", "mode": "audit", "prompt": "audit"},
        ],
    }
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue=task_queue,
            workflows=[XinaoPromotedTaskWorkflowV1, _StubChildWorkflow],
            activities=[validate, start, grok_lane, fanin, step, finalize],
        ),
    ):
        handle = await env.client.start_workflow(
            XinaoPromotedTaskWorkflowV1.run,
            payload,
            id=workflow_id,
            task_queue=task_queue,
        )
        if failing_lane:
            with pytest.raises(WorkflowFailureError):
                await handle.result()
            return
        result = await handle.result()

    assert result["ok"] is True
    assert result["grok_fanin"]["lane_count"] == 3
    assert [item["lane_id"] for item in result["grok_lanes"]] == [
        "research",
        "implementation",
        "audit",
    ]
    assert activity_state["max_active"] >= 2
    assert observed_lineage["lanes"] == {("corr-frontier", "parent-op-frontier")}
    assert observed_lineage["fanin"] == {("corr-frontier", "parent-op-frontier")}
    assert result["correlation_id"] == "corr-frontier"
    assert result["parent_operation_id"] == "parent-op-frontier"
    assert {item["operation_id"] for item in result["grok_lanes"]} == {
        "op-research",
        "op-implementation",
        "op-audit",
    }
    assert result["langgraph_children"][0]["worker_lane_provider"] == "grok_acpx_headless"
