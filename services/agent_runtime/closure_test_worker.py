"""Run closure_test_v1 Temporal worker (standalone queue)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from services.agent_runtime.closure_test_temporal import (
    TASK_QUEUE,
    XinaoClosureTestWorkflow,
    closure_test_run_pipeline,
    temporal_exports,
)
from services.agent_runtime.thin_evidence_writer import DEFAULT_RUNTIME

DEFAULT_REPO = Path(__file__).resolve().parents[2]


async def start_closure_test_workflow(
    input_path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    prefer_docker: bool = True,
    address: str = "127.0.0.1:7233",
) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"closure-test-{run_id}"
    payload = {
        "input_path": str(input_path),
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "prefer_docker": prefer_docker,
        "workflow_id": wf_id,
    }
    workflows, activities = temporal_exports()
    client = await Client.connect(address)
    async with Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities):
        handle = await client.start_workflow(
            XinaoClosureTestWorkflow.run,
            payload,
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        result = await handle.result()
        result["temporal"] = {
            "workflow_id": wf_id,
            "task_queue": TASK_QUEUE,
            "address": address,
        }
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="closure_test_v1 Temporal worker+client")
    parser.add_argument("--input", default=str(DEFAULT_REPO / "materials" / "closure_test_input.md"))
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-docker", action="store_true")
    parser.add_argument("--worker-only", action="store_true")
    args = parser.parse_args(argv)

    if args.worker_only:
        async def _worker() -> None:
            workflows, activities = temporal_exports()
            client = await Client.connect(args.address)
            worker = Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities)
            print(json.dumps({"task_queue": TASK_QUEUE, "status": "worker_polling"}))
            await worker.run()

        asyncio.run(_worker())
        return 0

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"input missing: {input_path}", file=sys.stderr)
        return 2
    payload = asyncio.run(
        start_closure_test_workflow(
            input_path,
            prefer_docker=not args.no_docker,
            address=args.address,
        )
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())