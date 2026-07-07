"""Temporal workflow + activity for thin_glue_loop (independent task queue)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

TASK_QUEUE = "xinao-thin-glue-loop-v1"
WORKFLOW_NAME = "XinaoThinGlueLoopWorkflow"


@activity.defn(name="thin_glue_run_loop")
async def thin_glue_run_loop(payload: dict[str, Any]) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_loop import run_thin_glue_loop
    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

    input_raw = payload.get("input_path") or ""
    input_path = Path(input_raw) if input_raw else None
    materials_raw = payload.get("materials_dir") or ""
    materials_dir = Path(materials_raw) if materials_raw else None
    return run_thin_glue_loop(
        input_path,
        runtime_root=Path(payload.get("runtime_root") or DEFAULT_RUNTIME),
        repo_root=Path(payload.get("repo_root") or DEFAULT_REPO),
        materials_dir=materials_dir,
        prefer_docker=bool(payload.get("prefer_docker", True)),
        invoke_gateway_chat=bool(payload.get("invoke_gateway_chat", False)),
        write=bool(payload.get("write", True)),
    )


@workflow.defn(name=WORKFLOW_NAME)
class XinaoThinGlueLoopWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            thin_glue_run_loop,
            payload,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


def temporal_exports() -> tuple[list[type], list[Any]]:
    return [XinaoThinGlueLoopWorkflow], [thin_glue_run_loop]