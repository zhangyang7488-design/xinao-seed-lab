"""Long-lived Temporal worker — registers integrated bus + thin_glue workflows."""

from __future__ import annotations

import argparse
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_graph import (
    GRAPH_ID,
    XinaoIntegratedBusWorkflow,
    make_integrated_graph,
)
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

SCHEMA_VERSION = "xinao.integrated_bus_worker_daemon.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_WORKER_DAEMON_READY"


def _load_params() -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_graph import DEFAULT_PARAMS

    if not DEFAULT_PARAMS.is_file():
        return {}
    return json.loads(DEFAULT_PARAMS.read_text(encoding="utf-8"))


async def run_integrated_bus_worker_daemon(
    *,
    address: str = "127.0.0.1:7233",
    runtime_root: Path = DEFAULT_RUNTIME,
) -> None:
    from temporalio.client import Client
    from temporalio.contrib.langgraph import LangGraphPlugin
    from temporalio.worker import Worker

    params = _load_params()
    task_queue = str(params.get("task_queue") or "xinao-integrated-langgraph-plugin-queue")
    graph_id = str(params.get("graph_id") or GRAPH_ID)

    workflows: list[Any] = [XinaoIntegratedBusWorkflow]
    activities: list[Any] = []
    try:
        from services.agent_runtime.thin_glue_temporal import XinaoThinGlueLoopWorkflow, temporal_exports

        wfs, acts = temporal_exports()
        workflows.extend([w for w in wfs if w not in workflows])
        activities.extend(acts)
    except Exception:
        pass

    client = await Client.connect(address)
    plugin = LangGraphPlugin(graphs={graph_id: make_integrated_graph()})
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "polling",
        "run_id": run_id,
        "task_queue": task_queue,
        "graph_id": graph_id,
        "workflows_registered": [getattr(w, "__name__", str(w)) for w in workflows],
        "activity_count": len(activities),
        "address": address,
        "not_333_mainline": True,
        "completion_claim_allowed": False,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    state_dir = runtime_root / "state" / "integrated_bus_worker_daemon"
    state_dir.mkdir(parents=True, exist_ok=True)
    write_json(state_dir / "latest.json", evidence)

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        plugins=[plugin],
        activity_executor=ThreadPoolExecutor(4),
    ):
        await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Integrated bus Temporal worker daemon")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    args = parser.parse_args(argv)
    try:
        asyncio.run(
            run_integrated_bus_worker_daemon(
                address=args.address,
                runtime_root=Path(args.runtime_root),
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())