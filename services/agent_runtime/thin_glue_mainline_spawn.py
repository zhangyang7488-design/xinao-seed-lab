"""Spawn thin_glue_loop child workflow — 主链薄接缝（不碰 14k workflow 正文）."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME

SCHEMA_VERSION = "xinao.codex_s.thin_glue_mainline_spawn.v1"
TASK_QUEUE = "xinao-thin-glue-loop-v1"
WORKFLOW_NAME = "XinaoThinGlueLoopWorkflow"


def thin_glue_mainline_spawn_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_MAINLINE_SPAWN", "0")
    return flag.strip().lower() in {"1", "true", "yes", "on"}


async def spawn_thin_glue_child_workflow(
    *,
    input_path: Path | None = None,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    prefer_docker: bool = True,
    address: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    from temporalio.client import Client

    from services.agent_runtime.thin_glue_temporal import XinaoThinGlueLoopWorkflow

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"thin-glue-mainline-spawn-{run_id}"
    payload = {
        "input_path": str(input_path) if input_path else "",
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "prefer_docker": prefer_docker,
        "invoke_gateway_chat": False,
        "write": True,
        "workflow_id": wf_id,
        "spawned_from": "thin_glue_mainline_spawn",
    }
    client = await Client.connect(address)
    handle = await client.start_workflow(
        XinaoThinGlueLoopWorkflow.run,
        payload,
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    result = await handle.result()
    return {
        "schema_version": SCHEMA_VERSION,
        "spawned": True,
        "child_workflow_id": wf_id,
        "child_task_queue": TASK_QUEUE,
        "child_result": result,
        "validation": {
            "passed": result.get("validation", {}).get("passed") is True,
        },
        "not_333_mainline": True,
        "thin_glue_mainline_spawn": True,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Spawn thin_glue_loop child on mainline seam")
    parser.add_argument("--input", default="")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-docker", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    out = asyncio.run(
        spawn_thin_glue_child_workflow(
            input_path=input_path,
            prefer_docker=not args.no_docker,
            address=args.address,
        )
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())