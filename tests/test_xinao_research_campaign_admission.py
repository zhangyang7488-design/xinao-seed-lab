from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from services.agent_runtime import xinao_mainline_canary as subject
from services.agent_runtime import xinao_science_episode_workflow as science_subject
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
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
        if "science_episode_admission" in state:
            assert state["science_episode_admission"]["protocol_pin_id"] == "pin-1"
            assert state["science_instrument_mode"] == "RESEARCH"
            assert state["runtime_root"].endswith("/research_worker_runtime")
        return {
            **_bus_result(),
            "science_instrument_admission_consumed": ("science_episode_admission" in state),
            "science_trial_appends": 0,
            "research_progress_claim_allowed": False,
            "completion_claim_allowed": False,
            "evaluation_outcome_access": False,
            "legacy_parent_scope_consumed": False,
        }


@activity.defn(name=science_subject.SCIENCE_STARTUP_INSTRUMENT_ACTIVITY_NAME)
async def _fake_science_instrument_activity(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.science_instrument_validation.v1",
        "episode_id": payload["episode_id"],
        "ok": True,
        "checks": {"fixture": True},
        "science_trial_appends": 0,
        "outcome_accessed": False,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
        "output_root": "evidence/science-episode-1/canonical-pin",
        "frozen_inputs": {
            "protocol_pin": {
                "ref": "protocol_pin.json",
                "sha256": "c" * 64,
            }
        },
        "receipt_ref": "fixture-science-instrument.json",
        "receipt_sha256": "f" * 64,
    }


@activity.defn(name=science_subject.SCIENCE_STARTUP_WORKER_ACTIVITY_NAME)
async def _fake_science_startup_worker_activity(
    _payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.science_startup_worker_receipt.v1",
        "ok": True,
        "status": "WORKER_TERMINAL_ACCEPTED",
        "model_identity_ok": True,
        "usage": {
            "invocation_count": 1,
            "total_tokens": 120,
            "accepted_tokens": 120,
            "cancelled_tokens": 0,
            "failed_tokens": 0,
        },
        "terminal_state": "completed",
        "stop_reason": "endturn",
        "receipt_ref": "fixture-science-worker.json",
        "receipt_sha256": "1" * 64,
        "checkpoint_ref": "fixture-science-worker-checkpoint.json",
        "checkpoint_sha256": "2" * 64,
        "science_trial_appends": 0,
        "outcome_accessed": False,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
        "legacy_parent_scope_consumed": False,
    }


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


@workflow.defn(name=subject.RESEARCH_WORKFLOW_NAME)
class _PreRetirementResearchCampaignWorkflow:
    """Exact domain-admission version before fresh-start retirement."""

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        campaign_id = str(initial.get("campaign_id") or "").strip()
        bus_state = dict(initial.get("bus_state") or {})
        guarded = workflow.patched(subject.DOMAIN_ADMISSION_PATCH_ID)
        admission: dict[str, Any] = {}
        if guarded:
            admission = await workflow.execute_activity(
                "xinao_verify_domain_research_admission",
                {
                    "report_ref": str(initial.get("domain_admission_report_ref") or ""),
                    "report_sha256": str(initial.get("domain_admission_report_sha256") or ""),
                    "scope": str(initial.get("domain_scope") or ""),
                    "realm": str(initial.get("domain_realm") or ""),
                    "evidence_root": str(
                        initial.get("domain_admission_evidence_root") or "/evidence"
                    ),
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                result_type=dict[str, Any],
            )
            bus_state["domain_research_admission"] = {
                "report_ref": admission["report_ref"],
                "report_file_sha256": admission["report_file_sha256"],
                "report_content_hash": admission["content_hash"],
                "report_id": admission["report_id"],
                "scope": admission["scope"],
                "realm": admission["realm"],
                "expires_at": admission["expires_at"],
            }
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
        response = {
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
        if guarded:
            response["domain_research_admission"] = bus_state["domain_research_admission"]
        return response


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


def _science_initial(*, mode: str) -> dict[str, Any]:
    return {
        "episode_id": "science-episode-1",
        "protocol_pin_ref": "protocol_pin.json",
        "protocol_pin_sha256": "c" * 64,
        "mode": mode,
        "model": "grok-4.5",
        "code_git_sha": "e" * 40,
        "bus_state": {"input_path": "input.json"},
    }


def _science_admission() -> dict[str, Any]:
    return {
        "schema_version": "xinao.science_episode_admission.v1",
        "allowed": True,
        "episode_id": "science-episode-1",
        "protocol_pin_id": "pin-1",
        "protocol_pin_ref": "protocol_pin.json",
        "protocol_pin_sha256": "c" * 64,
        "active_parent_id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
        "active_parent_sha256": "d" * 64,
        "claim_intent": "STARTUP_VALIDATION",
        "exposure_status": "UNKNOWN",
        "evaluation_outcome_access": False,
        "old_g6_equivalent": False,
    }


def test_old_g6_allow_cannot_start_current_science_episode() -> None:
    calls: list[dict[str, Any]] = []

    @activity.defn(name=science_subject.SCIENCE_EPISODE_ACTIVITY_NAME)
    async def deny(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"allowed": False, "reasons": ["protocol_pin_missing"]}

    async def run() -> tuple[list[dict[str, Any]], list[str]]:
        task_queue = f"science-deny-{uuid.uuid4().hex}"
        initial = _initial()
        initial.update(
            {
                "episode_id": "science-episode-1",
                "mode": "SCIENCE_STARTUP_VALIDATION",
            }
        )
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[science_subject.XinaoScienceEpisodeWorkflowV1],
                activities=[deny],
            ):
                handle = await environment.client.start_workflow(
                    science_subject.XinaoScienceEpisodeWorkflowV1.run,
                    initial,
                    id=f"science-deny-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                with pytest.raises(WorkflowFailureError) as raised:
                    await handle.result()
                assert "science episode admission denied" in str(raised.value.cause)
                history = await handle.fetch_history()
                names = [EventType.Name(event.event_type) for event in history.events]
                return list(calls), names

    recorded_calls, event_names = asyncio.run(run())
    assert len(recorded_calls) == 1
    assert recorded_calls[0]["protocol_pin_ref"] == ""
    assert "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_names


def test_current_science_startup_validation_executes_instruments_without_research_claim() -> None:
    @activity.defn(name=science_subject.SCIENCE_EPISODE_ACTIVITY_NAME)
    async def allow(_payload: dict[str, Any]) -> dict[str, Any]:
        return _science_admission()

    async def run() -> tuple[dict[str, Any], list[str]]:
        task_queue = f"science-startup-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with (
                Worker(
                    environment.client,
                    task_queue=task_queue,
                    workflows=[science_subject.XinaoScienceEpisodeWorkflowV1],
                    activities=[
                        allow,
                        _fake_science_instrument_activity,
                        _fake_science_startup_worker_activity,
                    ],
                ),
            ):
                handle = await environment.client.start_workflow(
                    science_subject.XinaoScienceEpisodeWorkflowV1.run,
                    _science_initial(mode="SCIENCE_STARTUP_VALIDATION"),
                    id=f"science-startup-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                result = await handle.result()
                history = await handle.fetch_history()
                names = [EventType.Name(event.event_type) for event in history.events]
                return result, names

    result, event_names = asyncio.run(run())
    assert result["status"] == "STARTUP_VALIDATED"
    assert result["child_scheduled"] is False
    assert result["worker_activity_scheduled"] is True
    assert result["outcome_accessed"] is False
    assert result["science_trial_appends"] == 0
    assert result["research_progress_claim_allowed"] is False
    assert result["completion_claim_allowed"] is False
    assert result["science_instrument_validation"]["ok"] is True
    assert result["science_startup_worker_receipt"]["status"] == ("WORKER_TERMINAL_ACCEPTED")
    assert "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_names


def test_current_science_execution_binds_admission_into_instrument_child() -> None:
    @activity.defn(name=science_subject.SCIENCE_EPISODE_ACTIVITY_NAME)
    async def allow(_payload: dict[str, Any]) -> dict[str, Any]:
        admission = _science_admission()
        admission["claim_intent"] = "EXPLORATORY"
        return admission

    async def run() -> dict[str, Any]:
        task_queue = f"science-execute-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with (
                Worker(
                    environment.client,
                    task_queue=task_queue,
                    workflows=[science_subject.XinaoScienceEpisodeWorkflowV1],
                    activities=[allow, _fake_science_instrument_activity],
                ),
                Worker(
                    environment.client,
                    task_queue=subject.INTEGRATED_BUS_QUEUE,
                    workflows=[_FakeIntegratedBusWorkflow],
                ),
            ):
                return await environment.client.execute_workflow(
                    science_subject.XinaoScienceEpisodeWorkflowV1.run,
                    _science_initial(mode="RESEARCH"),
                    id=f"science-execute-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )

    result = asyncio.run(run())
    assert result["status"] == "INSTRUMENT_EXECUTED"
    assert result["child_scheduled"] is True
    assert result["science_episode_admission"]["old_g6_equivalent"] is False


def test_science_startup_pause_survives_worker_replacement_and_resumes() -> None:
    @activity.defn(name=science_subject.SCIENCE_EPISODE_ACTIVITY_NAME)
    async def allow(_payload: dict[str, Any]) -> dict[str, Any]:
        return _science_admission()

    async def run() -> dict[str, Any]:
        task_queue = f"science-resume-{uuid.uuid4().hex}"
        initial = _science_initial(mode="SCIENCE_STARTUP_VALIDATION")
        initial["start_paused"] = True
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[science_subject.XinaoScienceEpisodeWorkflowV1],
                activities=[
                    allow,
                    _fake_science_instrument_activity,
                    _fake_science_startup_worker_activity,
                ],
                max_cached_workflows=0,
            ):
                handle = await environment.client.start_workflow(
                    science_subject.XinaoScienceEpisodeWorkflowV1.run,
                    initial,
                    id=f"science-resume-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                for _ in range(100):
                    state = await handle.query(science_subject.XinaoScienceEpisodeWorkflowV1.state)
                    if state["phase"] == "PAUSED_AFTER_ADMISSION":
                        break
                    await asyncio.sleep(0.01)
                assert state["paused"] is True
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[science_subject.XinaoScienceEpisodeWorkflowV1],
                activities=[
                    allow,
                    _fake_science_instrument_activity,
                    _fake_science_startup_worker_activity,
                ],
                max_cached_workflows=0,
            ):
                await handle.signal(
                    science_subject.XinaoScienceEpisodeWorkflowV1.control,
                    "RESUME",
                )
                try:
                    return await asyncio.wait_for(handle.result(), timeout=10)
                except TimeoutError as exc:
                    history = await handle.fetch_history()
                    names = [EventType.Name(event.event_type) for event in history.events]
                    raise AssertionError(
                        f"replacement worker did not resume; history tail={names[-12:]}"
                    ) from exc

    result = asyncio.run(run())
    assert result["status"] == "STARTUP_VALIDATED"
    assert result["science_trial_appends"] == 0
    assert result["research_progress_claim_allowed"] is False


def test_science_startup_rejects_incomplete_worker_receipt_without_child() -> None:
    @activity.defn(name=science_subject.SCIENCE_EPISODE_ACTIVITY_NAME)
    async def allow(_payload: dict[str, Any]) -> dict[str, Any]:
        return _science_admission()

    @activity.defn(name=science_subject.SCIENCE_STARTUP_WORKER_ACTIVITY_NAME)
    async def incomplete(_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "WORKER_TERMINAL_ACCEPTED",
            "usage": {
                "invocation_count": 0,
                "total_tokens": 0,
                "accepted_tokens": 0,
                "cancelled_tokens": 0,
                "failed_tokens": 0,
            },
            "science_trial_appends": 0,
            "outcome_accessed": False,
            "research_progress_claim_allowed": False,
            "completion_claim_allowed": False,
            "legacy_parent_scope_consumed": False,
        }

    async def run() -> list[str]:
        task_queue = f"science-incomplete-worker-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[science_subject.XinaoScienceEpisodeWorkflowV1],
                activities=[allow, _fake_science_instrument_activity, incomplete],
            ):
                handle = await environment.client.start_workflow(
                    science_subject.XinaoScienceEpisodeWorkflowV1.run,
                    _science_initial(mode="SCIENCE_STARTUP_VALIDATION"),
                    id=f"science-incomplete-worker-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                with pytest.raises(WorkflowFailureError) as raised:
                    await handle.result()
                assert "complete accepted receipt" in str(raised.value.cause)
                history = await handle.fetch_history()
                return [EventType.Name(event.event_type) for event in history.events]

    event_names = asyncio.run(run())
    assert "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_names


def test_legacy_campaign_fresh_start_is_retired_before_activity_or_child() -> None:
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
                assert "retired for fresh starts" in str(raised.value.cause)
                history = await handle.fetch_history()
                names = [EventType.Name(event.event_type) for event in history.events]
                return list(calls), names

    recorded_calls, event_names = asyncio.run(run())
    assert recorded_calls == []
    assert "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_names


def test_pre_retirement_domain_admission_history_still_replays() -> None:
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

    async def run() -> None:
        task_queue = f"campaign-allow-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            async with (
                Worker(
                    environment.client,
                    task_queue=task_queue,
                    workflows=[_PreRetirementResearchCampaignWorkflow],
                    activities=[allow],
                ),
                Worker(
                    environment.client,
                    task_queue=subject.INTEGRATED_BUS_QUEUE,
                    workflows=[_FakeIntegratedBusWorkflow],
                ),
            ):
                handle = await environment.client.start_workflow(
                    _PreRetirementResearchCampaignWorkflow.run,
                    _initial(),
                    id=f"campaign-allow-{uuid.uuid4().hex}",
                    task_queue=task_queue,
                )
                result = await handle.result()
                assert result["domain_research_admission"]["report_id"] == "admission-1"
                history = await handle.fetch_history()
        await Replayer(workflows=[subject.XinaoResearchCampaignWorkflow]).replay_workflow(history)

    asyncio.run(run())


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
