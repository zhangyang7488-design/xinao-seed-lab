"""Temporal parent + child workflows for parallel thin-glue worker lanes."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

TASK_QUEUE = "xinao-thin-glue-worker-pool-v1"
LANE_WORKFLOW = "XinaoThinGlueLaneWorkflow"
POOL_WORKFLOW = "XinaoThinGlueWorkerPoolWorkflow"


@activity.defn(name="thin_glue_lane_activity")
async def thin_glue_lane_activity(payload: dict[str, Any]) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_lane_worker import run_thin_glue_lane
    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

    return run_thin_glue_lane(
        lane_id=str(payload.get("lane_id") or "lane-001"),
        mode=str(payload.get("mode") or "draft"),
        query=str(payload.get("query") or "thin_glue"),
        wave_id=str(payload.get("wave_id") or "thin-glue-pool"),
        runtime_root=Path(payload.get("runtime_root") or DEFAULT_RUNTIME),
        repo_root=Path(payload.get("repo_root") or DEFAULT_REPO),
        lane_number=int(payload.get("lane_number") or 1),
        write=bool(payload.get("write", True)),
    )


@workflow.defn(name=LANE_WORKFLOW)
class XinaoThinGlueLaneWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            thin_glue_lane_activity,
            payload,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name=POOL_WORKFLOW)
class XinaoThinGlueWorkerPoolWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        lanes: list[dict[str, Any]] = list(payload.get("lanes") or [])
        wave_id = str(payload.get("wave_id") or "thin-glue-pool")
        results = await asyncio.gather(
            *[
                workflow.execute_child_workflow(
                    XinaoThinGlueLaneWorkflow.run,
                    lane,
                    id=f"{wave_id}-{lane.get('lane_id', 'lane')}",
                    task_queue=TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.TERMINATE,
                )
                for lane in lanes
            ]
        )
        succeeded = [item for item in results if item.get("status") == "succeeded"]
        return {
            "wave_id": payload.get("wave_id"),
            "lane_results": results,
            "succeeded_count": len(succeeded),
            "draft_count": len([r for r in results if r.get("mode") == "draft"]),
            "temporal_child_workflows": True,
            "hand_rolled_thread_pool_bypassed": True,
            "thin_glue": True,
            "validation": {"passed": len(succeeded) > 0},
        }


def temporal_exports() -> tuple[list[type], list[Any]]:
    return [XinaoThinGlueLaneWorkflow, XinaoThinGlueWorkerPoolWorkflow], [thin_glue_lane_activity]
