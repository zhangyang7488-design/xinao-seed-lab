"""Fixed-role Temporal worker for the isolated OpenHands execution endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from services.agent_runtime.integrated_bus_workflow_registry import (
    collect_openhands_worker_binding,
)

SCHEMA_VERSION = "xinao.openhands_execution_worker.v1"
SENTINEL = "SENTINEL:XINAO_OPENHANDS_EXECUTION_BROKER_READY"


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(raw, encoding="utf-8")
    os.replace(temporary, path)


async def run_execution_worker(
    *,
    address: str,
    namespace: str,
    runtime_root: Path,
    identity: str,
) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    binding = collect_openhands_worker_binding()
    client = await Client.connect(address, namespace=namespace)
    state_path = runtime_root / "state" / "openhands_execution_worker" / "latest.json"
    with ThreadPoolExecutor(max_workers=4) as activity_executor:
        async with Worker(
            client,
            task_queue=binding.task_queue,
            workflows=binding.workflows,
            activities=binding.activities,
            activity_executor=activity_executor,
            identity=identity,
        ):
            _write_json_atomic(
                state_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "sentinel": SENTINEL,
                    "status": "polling",
                    "identity": identity,
                    "address": address,
                    "namespace": namespace,
                    "task_queue": binding.task_queue,
                    "workflow_count": len(binding.workflows),
                    "activity_count": len(binding.activities),
                    "docker_control_owner": True,
                    "model_worker": False,
                    "orchestrator": False,
                    "completion_claim_allowed": False,
                    "generated_at": datetime.now().astimezone().isoformat(),
                },
            )
            await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenHands endpoint execution broker")
    parser.add_argument(
        "--address",
        default=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"),
    )
    parser.add_argument(
        "--namespace",
        default=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    parser.add_argument(
        "--runtime-root",
        default=os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"),
    )
    parser.add_argument(
        "--identity",
        default=os.environ.get(
            "XINAO_OPENHANDS_WORKER_IDENTITY",
            "xinao-openhands-execution-broker-v1",
        ),
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(
            run_execution_worker(
                address=args.address,
                namespace=args.namespace,
                runtime_root=Path(args.runtime_root),
                identity=args.identity,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
