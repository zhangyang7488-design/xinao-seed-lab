"""Default thin-glue Temporal path — LangGraphPlugin integrated bus (replaces hand-roll loop workflow)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_runner import (
    integrated_bus_default_enabled,
    run_integrated_bus,
    run_integrated_bus_temporal,
)
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME


async def start_thin_glue_workflow(
    input_path: Path | None = None,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    materials_dir: Path | None = None,
    prefer_docker: bool = True,
    invoke_gateway_chat: bool = False,
    address: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    del materials_dir, prefer_docker, invoke_gateway_chat
    if not integrated_bus_default_enabled():
        from services.agent_runtime.thin_glue_temporal import (
            TASK_QUEUE,
            XinaoThinGlueLoopWorkflow,
            temporal_exports,
        )
        from temporalio.client import Client
        from temporalio.worker import Worker
        from datetime import datetime

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        wf_id = f"thin-glue-loop-{run_id}"
        payload = {
            "input_path": str(input_path) if input_path else "",
            "runtime_root": str(runtime_root),
            "repo_root": str(repo_root),
            "prefer_docker": True,
            "write": True,
            "workflow_id": wf_id,
        }
        workflows, activities = temporal_exports()
        client = await Client.connect(address)
        async with Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities):
            handle = await client.start_workflow(
                XinaoThinGlueLoopWorkflow.run,
                payload,
                id=wf_id,
                task_queue=TASK_QUEUE,
            )
            result = await handle.result()
            result["temporal"] = {"workflow_id": wf_id, "task_queue": TASK_QUEUE, "address": address}
            return result

    trigger = input_path
    if trigger is None or not trigger.is_file():
        for candidate in (
            repo_root / "materials" / "phase0_test_input.md",
            repo_root / "materials" / "thin_bootstrap_input.md",
        ):
            if candidate.is_file():
                trigger = candidate
                break
    if trigger is None or not trigger.is_file():
        from services.agent_runtime.integrated_bus_runner import resolve_input

        trigger = resolve_input(None, repo_root=repo_root)

    effective_repo = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", str(DEFAULT_REPO)))
    if not (effective_repo / "services" / "agent_runtime" / "integrated_bus_graph.py").is_file():
        effective_repo = DEFAULT_REPO
    result = await run_integrated_bus_temporal(
        trigger,
        runtime_root=runtime_root,
        repo_root=effective_repo,
        address=address,
        mainline_default=True,
    )
    result["temporal"] = {
        "workflow_id": result.get("workflow_id"),
        "task_queue": "xinao-integrated-langgraph-plugin-queue",
        "address": address,
        "integration_pattern": "LangGraphPlugin",
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="thin-glue default = integrated LangGraphPlugin bus")
    parser.add_argument("--input", default="")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    try:
        if args.local:
            payload = run_integrated_bus(input_path, temporal=False, mainline_default=True)
        else:
            payload = asyncio.run(
                start_thin_glue_workflow(input_path, address=args.address)
            )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())