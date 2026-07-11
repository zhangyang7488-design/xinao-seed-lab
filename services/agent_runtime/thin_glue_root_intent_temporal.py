"""L2 thin root intent — Temporal parent workflow tick (not 14k body)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

TASK_QUEUE = "xinao-thin-glue-root-intent-v1"
WORKFLOW_NAME = "XinaoThinGlueRootIntentTickWorkflow"


@activity.defn(name="thin_glue_root_intent_tick_activity")
async def thin_glue_root_intent_tick_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    from services.agent_runtime.thin_glue_l2_root_intent import run_thin_glue_root_intent_tick
    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

    return run_thin_glue_root_intent_tick(
        runtime_root=Path(payload.get("runtime_root") or DEFAULT_RUNTIME),
        repo_root=Path(payload.get("repo_root") or DEFAULT_REPO),
        wave_id=str(payload.get("wave_id") or "thin-glue-root-intent-tick"),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_run_id=str(payload.get("workflow_run_id") or ""),
        write=bool(payload.get("write", True)),
        temporal_activity=True,
    )


@workflow.defn(name=WORKFLOW_NAME)
class XinaoThinGlueRootIntentTickWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            thin_glue_root_intent_tick_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


def temporal_exports() -> tuple[list[type], list[Any]]:
    return [XinaoThinGlueRootIntentTickWorkflow], [thin_glue_root_intent_tick_activity]
