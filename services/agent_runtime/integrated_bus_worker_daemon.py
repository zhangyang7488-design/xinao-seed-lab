"""Long-lived Temporal worker daemon for the canonical integrated-bus queues."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_graph import (
    GRAPH_ID,
    integrated_temporal_graphs,
    make_integrated_graph,
)
from services.agent_runtime.integrated_bus_workflow_registry import (
    collect_worker_bindings,
    registry_summary,
)
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json
from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

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

    from services.agent_runtime.integrated_bus_runner import integrated_bus_workflow_runner

    bindings = collect_worker_bindings()
    client = await Client.connect(address)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    sunset = summarize_sunset_registry()
    reg = registry_summary()
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "polling",
        "run_id": run_id,
        "address": address,
        "graph_id": GRAPH_ID,
        "binding_count": len(bindings),
        "task_queues": reg.get("task_queues", []),
        "workflows_registered": reg.get("workflows_registered", []),
        "activity_count": reg.get("activity_count", 0),
        "handroll_intact": False,
        "facade_hard_redirect": True,
        "sunset_registry_handroll_intact": sunset.get("handroll_intact") is False,
        "not_333_mainline": False,
        "completion_claim_allowed": False,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    state_dir = runtime_root / "state" / "integrated_bus_worker_daemon"
    state_dir.mkdir(parents=True, exist_ok=True)
    write_json(state_dir / "latest.json", evidence)
    write_json(runtime_root / "readback" / f"integrated_bus_worker_daemon_{run_id}.json", evidence)

    async with AsyncExitStack() as stack:
        for binding in bindings:
            plugins = []
            if binding.langgraph_plugin and binding.graph_id:
                graphs = (
                    integrated_temporal_graphs()
                    if binding.graph_id == GRAPH_ID
                    else {binding.graph_id: make_integrated_graph()}
                )
                plugins.append(LangGraphPlugin(graphs=graphs))
            worker = Worker(
                client,
                task_queue=binding.task_queue,
                workflows=binding.workflows,
                activities=binding.activities,
                plugins=plugins,
                activity_executor=ThreadPoolExecutor(max(4, len(binding.activities) or 1)),
                workflow_runner=integrated_bus_workflow_runner(),
            )
            await stack.enter_async_context(worker)
        await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Integrated bus Temporal worker daemon (canonical queues only)"
    )
    # Prefer compose TEMPORAL_ADDRESS (pinyin stack: naijiu-shiwu:7233); host rescue falls back to localhost.
    default_address = (
        os.environ.get("TEMPORAL_ADDRESS") or os.environ.get("TEMPORAL_HOST") or "127.0.0.1:7233"
    )
    parser.add_argument("--address", default=default_address)
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
