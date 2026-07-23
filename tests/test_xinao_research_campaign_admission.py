from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from services.agent_runtime import xinao_mainline_canary as subject
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker


def _bus_result() -> dict[str, Any]:
    return {
        "worker_lane_provider": "grok_acpx_headless",
        "worker_lane_model": "grok-4.5",
        "grok_fanin_model_identity_ok": True,
        "grok_fanin_ok": True,
        "grok_fanin_lane_count": 1,
        "checkpoint_ok": True,
        "checkpoint_invoked": True,
        "critic_edge_wired": True,
        "instructor_ok": True,
        "pro_review_ok": True,
        "promotion_gate_passed": True,
        "grok_fanin_manifest_ref": "fanin.json",
        "checkpoint_evidence_ref": "checkpoint.json",
        "promotion_evidence_ref": "promotion.json",
        "proof_path": "proof.json",
    }


@workflow.defn(name="XinaoIntegratedBusWorkflow")
class _FakeIntegratedBusWorkflow:
    @workflow.run
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        if "domain_research_admission" in state:
            assert state["domain_research_admission"]["report_id"] == "admission-1"
        return _bus_result()


@workflow.defn(name=subject.RESEARCH_WORKFLOW_NAME)
class _LegacyResearchCampaignWorkflow:
    """Exact pre-event427 command path used only to create replay history."""

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        campaign_id = str(initial.get("campaign_id") or "").strip()
        bus_state = dict(initial.get("bus_state") or {})
        result = await workflow.execute_child_workflow(
            "XinaoIntegratedBusWorkflow",
            bus_state,
            id=f"{workflow.info().workflow_id}-langgraph",
            task_queue=subject.INTEGRATED_BUS_QUEUE,
        )
        checks = {
            "real_grok_provider": result.get("worker_lane_provider") == "grok_acpx_headless",
            "real_grok_model": result.get("worker_lane_model") in subject.GROK_PROVIDER_MODELS
            and result.get("grok_fanin_model_identity_ok") is True,
            "typed_fanin": result.get("grok_fanin_ok") is True
            and int(result.get("grok_fanin_lane_count") or 0) >= 1,
            "checkpoint": result.get("checkpoint_ok") is True
            and result.get("checkpoint_invoked") is True,
            "critic_gate": result.get("critic_edge_wired") is True,
            "schema_gate": result.get("instructor_ok") is True,
            "verifier_gate": result.get("pro_review_ok") is True
            and result.get("promotion_gate_passed") is True,
        }
        return {
            "schema_version": "xinao.research_campaign_result.v1",
            "campaign_id": campaign_id,
            "workflow_id": workflow.info().workflow_id,
            "langgraph_child_workflow_id": f"{workflow.info().workflow_id}-langgraph",
            "checks": checks,
            "model": result.get("worker_lane_model"),
            "provider": result.get("worker_lane_provider"),
            "fanin_manifest_ref": result.get("grok_fanin_manifest_ref"),
            "checkpoint_evidence_ref": result.get("checkpoint_evidence_ref"),
            "promotion_evidence_ref": result.get("promotion_evidence_ref"),
            "proof_path": result.get("proof_path"),
        }


def _initial() -> dict[str, Any]:
    return {
        "campaign_id": "campaign-1",
        "bus_state": {"input_path": "input.json"},
        "domain_admission_report_ref": "admission.json",
        "domain_admission_report_sha256": "a" * 64,
        "domain_admission_evidence_root": "evidence",
        "domain_scope": "xinao-domain-mainline",
        "domain_realm": "DOMAIN_FIXED_AXIOM",
    }


def test_new_campaign_denies_before_scheduling_research_child() -> None:
    calls: list[dict[str, Any]] = []

    @activity.defn(name="xinao_verify_domain_research_admission")
    async def deny(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"ok": True, "allowed": False, "reasons": ["report_decision_deny"]}

    async def run() -> tuple[list[dict[str, Any]], list[str]]:
        task_queue = f"campaign-deny-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[subject.XinaoResearchCampaignWorkflow],
                activities=[deny],
            ):
                handle = await environment.client.start_workflow(
                    subject.XinaoResearchCampaignWorkflow.run,
                    _initial(),
                    id=f"campaign-deny-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                with pytest.raises(WorkflowFailureError) as raised:
                    await handle.result()
                assert "domain research admission denied" in str(raised.value.cause)
                history = await handle.fetch_history()
                names = [EventType.Name(event.event_type) for event in history.events]
                return list(calls), names

    recorded_calls, event_names = asyncio.run(run())
    assert len(recorded_calls) == 1
    assert "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_names


def test_new_campaign_binds_allowed_admission_into_child_and_result() -> None:
    @activity.defn(name="xinao_verify_domain_research_admission")
    async def allow(_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "allowed": True,
            "reasons": [],
            "report_ref": "admission.json",
            "report_file_sha256": "a" * 64,
            "content_hash": "b" * 64,
            "report_id": "admission-1",
            "scope": "xinao-domain-mainline",
            "realm": "DOMAIN_FIXED_AXIOM",
            "expires_at": "2026-07-24T00:00:00Z",
        }

    async def run() -> dict[str, Any]:
        task_queue = f"campaign-allow-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with (
                Worker(
                    environment.client,
                    task_queue=task_queue,
                    workflows=[subject.XinaoResearchCampaignWorkflow],
                    activities=[allow],
                ),
                Worker(
                    environment.client,
                    task_queue=subject.INTEGRATED_BUS_QUEUE,
                    workflows=[_FakeIntegratedBusWorkflow],
                ),
            ):
                return await environment.client.execute_workflow(
                    subject.XinaoResearchCampaignWorkflow.run,
                    _initial(),
                    id=f"campaign-allow-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )

    result = asyncio.run(run())
    assert result["domain_research_admission"] == {
        "report_ref": "admission.json",
        "report_file_sha256": "a" * 64,
        "report_content_hash": "b" * 64,
        "report_id": "admission-1",
        "scope": "xinao-domain-mainline",
        "realm": "DOMAIN_FIXED_AXIOM",
        "expires_at": "2026-07-24T00:00:00Z",
    }


def test_pre_cutover_history_replays_without_admission_activity() -> None:
    async def run() -> None:
        task_queue = f"campaign-legacy-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with (
                Worker(
                    environment.client,
                    task_queue=task_queue,
                    workflows=[_LegacyResearchCampaignWorkflow],
                ),
                Worker(
                    environment.client,
                    task_queue=subject.INTEGRATED_BUS_QUEUE,
                    workflows=[_FakeIntegratedBusWorkflow],
                ),
            ):
                handle = await environment.client.start_workflow(
                    _LegacyResearchCampaignWorkflow.run,
                    {"campaign_id": "legacy", "bus_state": {"input_path": "old.json"}},
                    id=f"campaign-legacy-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                await handle.result()
                history = await handle.fetch_history()
        await Replayer(workflows=[subject.XinaoResearchCampaignWorkflow]).replay_workflow(history)

    asyncio.run(run())
