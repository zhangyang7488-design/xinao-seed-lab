#!/usr/bin/env python3
"""Run one bounded Temporal -> Docker -> LangGraph kernel canary.

This deliberately does not invoke Grok.  It proves only the durable Temporal
dispatch, canonical Docker worker, LangGraph execution, checkpoint, and D-drive
proof path.  The separate canonical Grok transaction is the acceptance surface
for the full provider route.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client, WorkflowExecutionStatus

DEFAULT_RUN_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\temporal_kernel_convergence")
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
WORKFLOW_TYPE = "XinaoIntegratedBusWorkflow"
TASK_QUEUE = "xinao-integrated-langgraph-plugin-queue"


def _host_path(runtime_root: Path, raw: object) -> Path:
    value = str(raw or "").replace("\\", "/")
    if value.startswith("/evidence/"):
        return runtime_root / value[len("/evidence/") :]
    return Path(value)


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


async def run(run_root: Path, runtime_root: Path, timeout_seconds: float) -> dict[str, Any]:
    suffix = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = run_root.resolve() / f"kernel-convergence-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    workflow_id = f"xinao-kernel-convergence-{suffix}"
    workflow_input = {
        "input_path": "/app/materials/phase0_test_input.md",
        "params_path": "/app/materials/authority_glue/seams/integrated_bus_params.v1.json",
        "repo_root": "/app",
        "runtime_root": "/evidence",
        "workflow_id": workflow_id,
        "episode_phase": 3,
        "episode_max_phase": 3,
        "react_loop_count": 0,
        "heal_retry_count": 0,
        "heal_failed_checks": [],
    }
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    handle = await client.start_workflow(
        WORKFLOW_TYPE,
        workflow_input,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    async with asyncio.timeout(timeout_seconds):
        result = await handle.result()
    description = await handle.describe()
    if not isinstance(result, dict):
        raise TypeError("LangGraph workflow result must be an object")
    proof_path = _host_path(runtime_root, result.get("proof_path"))
    checks = {
        "workflow_completed": description.status is WorkflowExecutionStatus.COMPLETED,
        "planner_ok": result.get("planner_ok") is True,
        "fanin_ok": result.get("fanin_ok") is True,
        "checkpoint_ok": result.get("checkpoint_ok") is True,
        "promotion_gate_passed": result.get("promotion_gate_passed") is True,
        "proof_path_exists": proof_path.is_file(),
        "grok_not_invoked": result.get("worker_lane_ok") is not True
        and str(result.get("worker_lane_named_blocker") or "") == "GROK_FANIN_REQUIRED",
    }
    output = {
        "ok": all(checks.values()),
        "workflow_id": workflow_id,
        "run_id": description.run_id,
        "task_queue": TASK_QUEUE,
        "workflow_status": description.status.name.lower(),
        "history_length": description.history_length,
        "checks": checks,
        "proof_path": str(proof_path),
        "run_dir": str(run_dir),
        "full_provider_route_not_claimed": True,
        "grok_invocations": 0,
    }
    _write_json_atomic(run_dir / "result.json", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    args = parser.parse_args()
    output = asyncio.run(run(args.run_root, args.runtime_root, args.timeout_seconds))
    print(
        json.dumps(
            {key: output[key] for key in ("ok", "workflow_id", "run_id", "run_dir")},
            ensure_ascii=False,
        )
    )
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
