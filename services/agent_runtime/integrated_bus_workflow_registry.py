"""Single daemon registry — all Temporal workflows/activities bound to integrated bus ops."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from services.agent_runtime.integrated_bus_graph import (
    GRAPH_ID,
    XinaoIntegratedBusWorkflow,
)
from services.agent_runtime.integrated_bus_parent_workflow import (
    CHILD_TASK_QUEUE,
    PARENT_TASK_QUEUE,
    XinaoIntegratedBusChildWorkflow,
    XinaoIntegratedBusParentWorkflow,
    integrated_bus_child_slice,
    scan_watchdog_signal_feed,
)
from services.agent_runtime.openhands_execution_activity import (
    execute_openhands_command_activity,
)
from services.agent_runtime.openhands_execution_contract import (
    TASK_QUEUE as OPENHANDS_TASK_QUEUE,
)
from services.agent_runtime.openhands_execution_contract import (
    XinaoOpenHandsExecuteWorkflowV1,
)
from services.agent_runtime.xinao_mainline_canary import (
    TASK_QUEUE as MAINLINE_CANARY_TASK_QUEUE,
)
from services.agent_runtime.xinao_mainline_canary import temporal_exports as mainline_exports


@dataclass
class WorkerBinding:
    task_queue: str
    workflows: list[type] = field(default_factory=list)
    activities: list[Any] = field(default_factory=list)
    graph_id: str | None = None
    langgraph_plugin: bool = False


def collect_openhands_worker_binding() -> WorkerBinding:
    """Return the fixed-role endpoint binding owned by the execution broker."""

    return WorkerBinding(
        task_queue=OPENHANDS_TASK_QUEUE,
        workflows=[XinaoOpenHandsExecuteWorkflowV1],
        activities=[execute_openhands_command_activity],
    )


def collect_worker_bindings() -> list[WorkerBinding]:
    """Return only orchestration/LangGraph bindings for houtai-gongren."""

    bindings: list[WorkerBinding] = []
    integrated_queue = str(
        os.environ.get("XINAO_INTEGRATED_LANGGRAPH_TASK_QUEUE")
        or "xinao-integrated-langgraph-plugin-queue"
    ).strip()
    try:
        import json

        from services.agent_runtime.integrated_bus_graph import DEFAULT_PARAMS

        if DEFAULT_PARAMS.is_file() and not os.environ.get(
            "XINAO_INTEGRATED_LANGGRAPH_TASK_QUEUE"
        ):
            params = json.loads(DEFAULT_PARAMS.read_text(encoding="utf-8"))
            integrated_queue = str(params.get("task_queue") or integrated_queue)
    except Exception:
        pass

    bindings.append(
        WorkerBinding(
            task_queue=integrated_queue,
            workflows=[XinaoIntegratedBusWorkflow],
            activities=[],
            graph_id=GRAPH_ID,
            langgraph_plugin=True,
        )
    )

    bindings.extend(
        [
            WorkerBinding(
                task_queue=PARENT_TASK_QUEUE,
                workflows=[XinaoIntegratedBusParentWorkflow],
                activities=[scan_watchdog_signal_feed],
            ),
            WorkerBinding(
                task_queue=CHILD_TASK_QUEUE,
                workflows=[XinaoIntegratedBusChildWorkflow],
                activities=[integrated_bus_child_slice],
            ),
        ]
    )

    mainline_workflows, mainline_activities = mainline_exports()
    bindings.append(
        WorkerBinding(
            task_queue=MAINLINE_CANARY_TASK_QUEUE,
            workflows=mainline_workflows,
            activities=mainline_activities,
        )
    )

    return bindings


def registry_summary() -> dict[str, Any]:
    bindings = collect_worker_bindings()
    return {
        "binding_count": len(bindings),
        "task_queues": [b.task_queue for b in bindings],
        "workflows_registered": [
            getattr(w, "__name__", str(w)) for b in bindings for w in b.workflows
        ],
        "activity_count": sum(len(b.activities) for b in bindings),
        "graph_ids": [b.graph_id for b in bindings if b.graph_id],
        "langgraph_plugin_queues": [b.task_queue for b in bindings if b.langgraph_plugin],
    }


__all__ = [
    "WorkerBinding",
    "collect_openhands_worker_binding",
    "collect_worker_bindings",
    "registry_summary",
]
