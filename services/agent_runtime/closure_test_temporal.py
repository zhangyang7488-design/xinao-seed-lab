"""Temporal workflow + activity for closure_test_v1 (independent task queue)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

TASK_QUEUE = "xinao-closure-test-v1"
WORKFLOW_NAME = "XinaoClosureTestWorkflow"


@activity.defn(name="closure_test_run_pipeline")
async def closure_test_run_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    from services.agent_runtime.closure_test_activities import run_closure_test_pipeline
    from services.agent_runtime.thin_evidence_writer import DEFAULT_RUNTIME

    default_repo = payload.get("repo_root") or r"E:\XINAO_RESEARCH_WORKSPACES\S"
    return run_closure_test_pipeline(
        Path(payload["input_path"]),
        runtime_root=Path(payload.get("runtime_root") or DEFAULT_RUNTIME),
        repo_root=Path(payload.get("repo_root") or default_repo),
        prefer_docker=bool(payload.get("prefer_docker", True)),
        workflow_id=str(payload.get("workflow_id") or WORKFLOW_NAME),
    )


@workflow.defn(name=WORKFLOW_NAME)
class XinaoClosureTestWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            closure_test_run_pipeline,
            payload,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


def temporal_exports() -> tuple[list[type], list[Any]]:
    return [XinaoClosureTestWorkflow], [closure_test_run_pipeline]