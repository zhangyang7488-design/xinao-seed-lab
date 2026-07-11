"""Parent Temporal WF — new_material / watchdog signals + Child WF escalation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

PARENT_WORKFLOW_NAME = "XinaoIntegratedBusParentWorkflow"
CHILD_WORKFLOW_NAME = "XinaoIntegratedBusChildWorkflow"
PARENT_TASK_QUEUE = "xinao-integrated-bus-parent-queue"
CHILD_TASK_QUEUE = "xinao-integrated-bus-child-queue"
TASK_QUEUE = PARENT_TASK_QUEUE


@activity.defn(name="integrated_bus_scan_watchdog_signal_feed")
async def scan_watchdog_signal_feed(payload: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    from services.agent_runtime.integrated_bus_bus_nodes import run_signal_feed_bus

    runtime = Path(str(payload.get("runtime_root") or r"D:\XINAO_RESEARCH_RUNTIME"))
    return run_signal_feed_bus(runtime_root=runtime)


@activity.defn(name="integrated_bus_child_slice")
async def integrated_bus_child_slice(payload: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    from services.agent_runtime.integrated_bus_runner import run_integrated_bus

    input_raw = str(payload.get("input_path") or "")
    if not input_raw:
        feed = payload.get("signal_feed") or {}
        paths = feed.get("material_paths") or []
        input_raw = str(paths[0]) if paths else ""
    result = run_integrated_bus(
        Path(input_raw) if input_raw else None,
        temporal=False,
        mainline_default=False,
    )
    return {
        "child_slice_ok": result.get("validation", {}).get("passed") is True,
        "child_evidence_ref": result.get("evidence_path"),
        "invoke_mode": "child_workflow_local_slice",
        "result_summary": result.get("acceptance_now_can_invoke_cn"),
    }


@workflow.defn(name=CHILD_WORKFLOW_NAME)
class XinaoIntegratedBusChildWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            integrated_bus_child_slice,
            payload,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name=PARENT_WORKFLOW_NAME)
class XinaoIntegratedBusParentWorkflow:
    def __init__(self) -> None:
        self._pending_materials: list[dict[str, Any]] = []
        self._watchdog_events: list[dict[str, Any]] = []
        self._child_results: list[dict[str, Any]] = []

    @workflow.signal
    async def new_material(self, payload: dict[str, Any]) -> None:
        self._pending_materials.append(dict(payload))

    @workflow.signal
    async def watchdog(self, payload: dict[str, Any]) -> None:
        self._watchdog_events.append(dict(payload))

    @workflow.run
    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        feed = await workflow.execute_activity(
            scan_watchdog_signal_feed,
            initial,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        material_paths = list(feed.get("material_paths") or [])
        for item in self._pending_materials:
            path = str(item.get("input_path") or item.get("path") or "")
            if path:
                material_paths.append(path)
        material_paths = list(dict.fromkeys(material_paths))
        child_payload = {
            **initial,
            "signal_feed": feed,
            "input_path": material_paths[0] if material_paths else initial.get("input_path"),
            "watchdog_signal_count": len(self._watchdog_events),
            "new_material_signal_count": len(self._pending_materials),
        }
        child_result = await workflow.execute_child_workflow(
            XinaoIntegratedBusChildWorkflow.run,
            child_payload,
            id=f"{workflow.info().workflow_id}-child",
            task_queue=CHILD_TASK_QUEUE,
        )
        self._child_results.append(child_result)
        return {
            "parent_workflow_id": workflow.info().workflow_id,
            "signal_feed_ok": feed.get("signal_feed_ok") is True,
            "watchdog_auto_feed_count": int(feed.get("auto_feed_count") or 0),
            "material_paths": material_paths,
            "child_workflow_invoked": True,
            "child_result": child_result,
            "watchdog_events": len(self._watchdog_events),
            "new_material_signals": len(self._pending_materials),
        }


def temporal_exports() -> tuple[list[type], list[Any]]:
    return (
        [XinaoIntegratedBusParentWorkflow, XinaoIntegratedBusChildWorkflow],
        [scan_watchdog_signal_feed, integrated_bus_child_slice],
    )
