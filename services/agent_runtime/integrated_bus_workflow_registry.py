"""Single daemon registry — all Temporal workflows/activities bound to integrated bus ops."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.agent_runtime.integrated_bus_graph import GRAPH_ID, XinaoIntegratedBusWorkflow, make_integrated_graph


@dataclass
class WorkerBinding:
    task_queue: str
    workflows: list[type] = field(default_factory=list)
    activities: list[Any] = field(default_factory=list)
    graph_id: str | None = None
    langgraph_plugin: bool = False


def collect_worker_bindings() -> list[WorkerBinding]:
    bindings: list[WorkerBinding] = []
    integrated_queue = "xinao-integrated-langgraph-plugin-queue"
    try:
        from services.agent_runtime.integrated_bus_graph import DEFAULT_PARAMS
        import json
        from pathlib import Path

        if DEFAULT_PARAMS.is_file():
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

    _extend(binding_module="services.agent_runtime.thin_glue_temporal", bindings=bindings)
    _extend(binding_module="services.agent_runtime.thin_glue_root_intent_temporal", bindings=bindings)
    _extend(binding_module="services.agent_runtime.thin_glue_worker_pool_temporal", bindings=bindings)

    return bindings


def _extend(*, binding_module: str, bindings: list[WorkerBinding]) -> None:
    try:
        import importlib

        mod = importlib.import_module(binding_module)
        task_queue = str(getattr(mod, "TASK_QUEUE", "") or "")
        temporal_exports = getattr(mod, "temporal_exports", None)
        if not task_queue or not callable(temporal_exports):
            return
        workflows, activities = temporal_exports()
        for binding in bindings:
            if binding.task_queue == task_queue:
                binding.workflows.extend([w for w in workflows if w not in binding.workflows])
                binding.activities.extend([a for a in activities if a not in binding.activities])
                return
        bindings.append(
            WorkerBinding(
                task_queue=task_queue,
                workflows=list(workflows),
                activities=list(activities),
            )
        )
    except Exception:
        return


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