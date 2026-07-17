from __future__ import annotations

import asyncio
import uuid

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from xinao_coordination.temporal import workflow as promoted_workflow
from xinao_coordination.temporal.workflow import (
    REQUIRED_LANGGRAPH_TRUE_CHECKS,
    XinaoPromotedTaskWorkflowV1,
    _is_accepted_grok_lane,
)

DEFAULT_MODEL = "grok-composer-2.5-fast"


@pytest.mark.parametrize(
    ("composer_patch_enabled", "expected_default"),
    [
        (False, promoted_workflow.GROK_LEGACY_DEFAULT_MODEL),
        (True, promoted_workflow.GROK_DEFAULT_MODEL),
    ],
)
def test_workflow_model_patch_preserves_pre_patch_replay_default(
    monkeypatch: pytest.MonkeyPatch,
    composer_patch_enabled: bool,
    expected_default: str,
) -> None:
    observed: dict[str, object] = {}

    def fake_patched(patch_id: str) -> bool:
        if patch_id == promoted_workflow.GROK_COMPOSER_DEFAULT_PATCH_ID:
            return composer_patch_enabled
        return False

    def capture_frontier(
        raw: object,
        *,
        serial_reason: str,
        default_model: str,
        require_explicit_model: bool,
        require_explicit_cwd: bool,
    ) -> list[dict]:
        observed.update(
            raw=raw,
            serial_reason=serial_reason,
            default_model=default_model,
            require_explicit_model=require_explicit_model,
            require_explicit_cwd=require_explicit_cwd,
        )
        return []

    monkeypatch.setattr(promoted_workflow.workflow, "patched", fake_patched)
    monkeypatch.setattr(promoted_workflow, "validate_ready_frontier", capture_frontier)
    instance = XinaoPromotedTaskWorkflowV1()
    started = {"phase": "started"}

    result = asyncio.run(
        instance._execute_grok_frontier(
            {
                "grok_ready_frontier": [{"lane_id": "history", "prompt": "replay"}],
                "grok_serial_reason": "one retained-history lane",
            },
            started,
        )
    )

    assert result == started
    assert observed["default_model"] == expected_default
    assert observed["serial_reason"] == "one retained-history lane"
    assert observed["require_explicit_model"] is False
    assert observed["require_explicit_cwd"] is False


def test_new_workflow_history_requires_explicit_supervisor_model_and_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_patched(patch_id: str) -> bool:
        return patch_id == promoted_workflow.GROK_EXPLICIT_SUPERVISOR_SELECTION_PATCH_ID

    monkeypatch.setattr(promoted_workflow.workflow, "patched", fake_patched)
    instance = XinaoPromotedTaskWorkflowV1()

    with pytest.raises(Exception, match="explicit supervisor-selected model"):
        asyncio.run(
            instance._execute_grok_frontier(
                {
                    "grok_ready_frontier": [
                        {"lane_id": "new", "prompt": "new execution"}
                    ],
                    "grok_serial_reason": "one selected lane",
                },
                {"phase": "started"},
            )
        )


def test_attested_lane_acceptance_has_an_independent_replay_boundary() -> None:
    legacy_composer_result = {
        "ok": True,
        "provider_id": "grok_acpx_headless",
        "model": DEFAULT_MODEL,
        "operation_id": "legacy-op",
        "operation_state": "completed",
        "result_text": "legacy Composer result without attestation fields",
    }

    assert _is_accepted_grok_lane(
        legacy_composer_result,
        attested_lane_acceptance=False,
    )
    assert not _is_accepted_grok_lane(
        legacy_composer_result,
        attested_lane_acceptance=True,
    )


@workflow.defn(name="XinaoIntegratedBusWorkflow")
class _StubChildWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> dict:
        frontier = [dict(item) for item in payload.get("grok_ready_frontier") or []]
        lanes = []
        for item in frontier:
            failed = item.get("test_fail") is True
            model = str(item.get("model") or DEFAULT_MODEL)
            lanes.append(
                {
                    "ok": not failed,
                    "provider_id": "grok_acpx_headless",
                    "lane_id": item["lane_id"],
                    "mode": item["mode"],
                    "model": model,
                    "requested_model": model,
                    "observed_model": "" if failed else model,
                    "model_identity_ok": not failed,
                    "agent_session_id": f"session-{item['lane_id']}",
                    "model_identity_ref": f"/evidence/identity-{item['lane_id']}.json",
                    "model_identity_sha256": "a" * 64,
                    "session_model_evidence_valid": not failed,
                    "prompt_sha256": "b" * 64,
                    "operation_id": f"op-{item['lane_id']}",
                    "correlation_id": payload.get("correlation_id"),
                    "parent_operation_id": payload.get("parent_operation_id"),
                    "operation_state": "failed" if failed else "completed",
                    "result_text": "" if failed else f"result {item['lane_id']}",
                    "artifacts": [],
                }
            )
        succeeded = sum(item["ok"] is True for item in lanes)
        fanin_ok = succeeded == len(lanes) and bool(lanes)
        fanin = {
            "ok": fanin_ok,
            "provider_id": "grok_acpx_headless",
            "model": DEFAULT_MODEL,
            "models": [DEFAULT_MODEL],
            "model_identity_ok": fanin_ok,
            "correlation_id": payload.get("correlation_id"),
            "parent_operation_id": payload.get("parent_operation_id"),
            "lane_count": len(lanes),
            "ready_width": len(lanes),
            "succeeded": succeeded,
            "failed": len(lanes) - succeeded,
            "execution_location": "docker:houtai-gongren",
            "supervisor_selection_required": payload.get(
                "supervisor_selection_required"
            ),
            "supervisor_worker_decision_sha256": (
                payload.get("supervisor_worker_decision") or {}
            ).get("decision_sha256"),
        }
        result = {name: True for name in REQUIRED_LANGGRAPH_TRUE_CHECKS}
        result.update(
            {
                "content_md": "grok fanin",
                "parallel_succeeded": 3,
                "worker_lane_provider": "grok_acpx_headless",
                "worker_lane_model": DEFAULT_MODEL,
                "grok_only_mode": False,
                "selected_provider_fail_closed": True,
                "provider_fanin_ok": True,
                "provider_validator_id": "xinao.grok.shared_execution_contract.v1",
                "provider_evidence_bound": True,
                "grok_fanin_ok": True,
                "grok_fanin_model_identity_ok": True,
                "grok_fanin_manifest_ref": "/evidence/grok-manifest",
                "grok_fanin_lane_count": 3,
                "grok_lanes": lanes,
                "grok_fanin": fanin,
                "grok_execution_location": "docker:houtai-gongren",
                "non_grok_model_invocations": 0,
                "fallback_model_invocation_performed": False,
                "memory_model_bind_frozen": True,
                "pro_review_ok": False,
                "pro_review_provider": "",
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
            "model": payload["model"],
            "requested_model": payload["model"],
            "observed_model": payload["model"],
            "model_identity_ok": not failed,
            "agent_session_id": f"session-{payload['lane_id']}",
            "model_identity_ref": f"D:/identity-{payload['lane_id']}.json",
            "model_identity_sha256": "a" * 64,
            "session_model_evidence_valid": not failed,
            "prompt_sha256": payload["prompt_sha256"],
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
            "model": payload["lane_results"][0]["model"],
            "models": [payload["lane_results"][0]["model"]],
            "model_identity_ok": True,
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
        "supervisor_worker_decision": {
            "decision": "selected",
            "decision_sha256": "d" * 64,
        },
        "langgraph_child": {
            "enabled": True,
            "task_queue": task_queue,
            "workflow_type": "XinaoIntegratedBusWorkflow",
        },
        "grok_ready_frontier": [
            {
                "lane_id": "research",
                "mode": "external_research",
                "prompt": "research",
                "test_fail": failing_lane == "research",
            },
            {
                "lane_id": "implementation",
                "mode": "implementation",
                "prompt": "build",
                "test_fail": failing_lane == "implementation",
            },
            {
                "lane_id": "audit",
                "mode": "audit",
                "prompt": "audit",
                "test_fail": failing_lane == "audit",
            },
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
    assert activity_state["max_active"] == 0
    assert observed_lineage["lanes"] == set()
    assert observed_lineage["fanin"] == set()
    assert result["correlation_id"] == "corr-frontier"
    assert result["parent_operation_id"] == "parent-op-frontier"
    assert {item["operation_id"] for item in result["grok_lanes"]} == {
        "op-research",
        "op-implementation",
        "op-audit",
    }
    assert result["langgraph_children"][0]["worker_lane_provider"] == "grok_acpx_headless"
    assert result["grok_fanin"]["model"] == DEFAULT_MODEL
    assert result["grok_fanin"]["execution_location"] == "docker:houtai-gongren"
    assert result["grok_fanin"]["supervisor_selection_required"] is True
    assert result["grok_fanin"]["supervisor_worker_decision_sha256"] == "d" * 64
    assert {item["observed_model"] for item in result["grok_lanes"]} == {DEFAULT_MODEL}
