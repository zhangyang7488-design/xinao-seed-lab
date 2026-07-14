"""Promoted-task → Temporal workflow envelope validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

DEFAULT_LANGGRAPH_CHILD_QUEUE = "xinao-integrated-langgraph-plugin-queue"
DEFAULT_LANGGRAPH_CHILD_WORKFLOW = "XinaoIntegratedBusWorkflow"
DEFAULT_LANGGRAPH_INPUT_REF = "/app/materials/phase0_test_input.md"


@dataclass(frozen=True)
class PromotedTaskEnvelope:
    task_id: str
    workflow_id: str
    workflow_type: str
    task_queue: str
    generation: int
    immutable_intent_hash: str
    title: str
    goal: str
    source_thread_id: str | None
    owner: str
    decision_hash: str
    kernel_lease_token: str
    langgraph_child_enabled: bool
    langgraph_child_queue: str
    langgraph_child_workflow: str
    langgraph_input_ref: str
    grok_ready_frontier: list[dict[str, Any]]
    grok_serial_reason: str
    grok_full_frontier_acceptance_v1: bool
    correlation_id: str = ""
    parent_operation_id: str = ""

    def to_workflow_input(self) -> dict[str, object]:
        result: dict[str, object] = {
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "generation": self.generation,
            "immutable_intent_hash": self.immutable_intent_hash,
            "title": self.title,
            "goal": self.goal,
            "source_thread_id": self.source_thread_id,
            "owner": self.owner,
            "decision_hash": self.decision_hash,
            "kernel_lease_token": self.kernel_lease_token,
            "promoted_only": True,
            "langgraph_child": {
                "enabled": self.langgraph_child_enabled,
                "task_queue": self.langgraph_child_queue,
                "workflow_type": self.langgraph_child_workflow,
                "input_ref": self.langgraph_input_ref,
            },
            "grok_ready_frontier": [dict(item) for item in self.grok_ready_frontier],
            "grok_serial_reason": self.grok_serial_reason,
            "grok_full_frontier_acceptance_v1": self.grok_full_frontier_acceptance_v1,
        }
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.parent_operation_id:
            result["parent_operation_id"] = self.parent_operation_id
        return result


def immutable_intent_hash(task: dict[str, Any]) -> str:
    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    decision = str(meta.get("decision_hash") or "").strip()
    if decision:
        return decision
    title = str(task.get("title") or "")
    goal = str(task.get("goal") or "")
    digest = hashlib.sha256(f"{title}\n{goal}".encode()).hexdigest()
    return digest


def workflow_id_for(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id") or "").strip()
    generation = int(task.get("control_epoch") or 0)
    if not task_id:
        raise ValueError("task_id required for workflow_id")
    return f"xinao-task-{task_id}-g{generation}"


def validate_task_envelope(
    task: dict[str, Any],
    *,
    workflow_type: str,
    task_queue: str,
) -> PromotedTaskEnvelope:
    from ..errors import ValidationError

    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    if not meta.get("promoted"):
        raise ValidationError(
            "Temporal requires explicitly promoted task",
            details={"task_id": task.get("task_id"), "promoted": False},
        )
    if meta.get("discuss_only") or meta.get("chat_only"):
        raise ValidationError(
            "chat/discuss-shaped payload cannot enter Temporal",
            details={"task_id": task.get("task_id")},
        )
    intent = immutable_intent_hash(task)
    if not intent:
        raise ValidationError(
            "immutable_intent_hash / decision_hash required for Temporal envelope",
            details={"task_id": task.get("task_id")},
        )
    state = str(task.get("state") or "")
    expected_workflow_id = workflow_id_for(task)
    recorded_workflow_id = str(meta.get("temporal_workflow_id") or "")
    if state != "queued" and not (state == "running" and recorded_workflow_id == expected_workflow_id):
        raise ValidationError(
            "task state not eligible for Temporal start",
            details={"task_id": task.get("task_id"), "state": state},
        )
    task_id = str(task.get("task_id") or "")
    langgraph = meta.get("langgraph_child") if isinstance(meta.get("langgraph_child"), dict) else {}
    raw_grok_frontier = meta.get("grok_ready_frontier")
    grok_frontier = (
        [dict(item) for item in raw_grok_frontier if isinstance(item, dict)]
        if isinstance(raw_grok_frontier, list)
        else []
    )
    input_ref = str(
        langgraph.get("input_ref")
        or meta.get("langgraph_input_ref")
        or meta.get("candidate_spec_ref")
        or meta.get("data_snapshot_ref")
        or DEFAULT_LANGGRAPH_INPUT_REF
    )
    return PromotedTaskEnvelope(
        task_id=task_id,
        workflow_id=workflow_id_for(task),
        workflow_type=workflow_type,
        task_queue=task_queue,
        generation=int(task.get("control_epoch") or 0),
        immutable_intent_hash=intent,
        title=str(task.get("title") or ""),
        goal=str(task.get("goal") or ""),
        source_thread_id=str(task.get("source_thread_id") or "") or None,
        owner=str(meta.get("owner") or "admin"),
        decision_hash=str(meta.get("decision_hash") or intent),
        kernel_lease_token=str(
            meta.get("temporal_kernel_lease_token")
            or "temporal_lease_"
            + hashlib.sha256(f"{expected_workflow_id}\n{intent}".encode()).hexdigest()[:32]
        ),
        langgraph_child_enabled=bool(langgraph.get("enabled", True)),
        langgraph_child_queue=str(langgraph.get("task_queue") or DEFAULT_LANGGRAPH_CHILD_QUEUE),
        langgraph_child_workflow=str(langgraph.get("workflow_type") or DEFAULT_LANGGRAPH_CHILD_WORKFLOW),
        langgraph_input_ref=input_ref,
        grok_ready_frontier=grok_frontier,
        grok_serial_reason=str(meta.get("grok_serial_reason") or ""),
        grok_full_frontier_acceptance_v1=bool(meta.get("grok_full_frontier_acceptance_v1", True)),
        correlation_id=str(meta.get("correlation_id") or "").strip(),
        parent_operation_id=str(meta.get("parent_operation_id") or "").strip(),
    )


def envelope_from_kernel_task(
    task: dict[str, Any],
    *,
    workflow_type: str,
    task_queue: str,
) -> PromotedTaskEnvelope:
    return validate_task_envelope(task, workflow_type=workflow_type, task_queue=task_queue)
