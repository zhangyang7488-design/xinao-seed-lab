#!/usr/bin/env python3
"""Run one bounded Grok -> Temporal -> Docker LangGraph transaction.

The Windows host worker owns only the Grok-facing Temporal workflow and
activities for this transaction.  The promoted workflow delegates its
LangGraph child to the canonical Docker ``houtai-gongren`` task queue, then
this process exits.  No resident scheduler or second control plane is added.
"""

# ruff: noqa: E402 -- this standalone entrypoint bootstraps project src before imports.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
SRC = PROJECT_ROOT / "src"
for candidate in (str(SRC), str(PROJECT_ROOT), str(REPO_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from services.agent_runtime.routing_policy_reader import draft_model
from temporalio.client import Client

from adapters.temporal.canary_start_workflow import create_kernel_backed_canary_task
from adapters.temporal.deployment_management import (
    ensure_deployment_current,
    load_verified_deployment,
)
from adapters.temporal.worker_runtime import build_promoted_worker
from xinao_coordination.service import CoordinationService
from xinao_coordination.temporal.activities import PROMOTED_ACTIVITIES
from xinao_coordination.temporal.grok_parallel import validate_ready_frontier
from xinao_coordination.temporal.workflow import PROMOTED_WORKFLOWS

DEFAULT_DB = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3")
DEFAULT_RUN_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\canonical_grok_transactions")
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
CANONICAL_LANGGRAPH_QUEUE = "xinao-integrated-langgraph-plugin-queue"
CANONICAL_HOST_QUEUE = "xinao-canonical-grok-host-v1"
DEPLOYMENT_MANIFEST = PROJECT_ROOT / "adapters" / "temporal" / "canonical_grok_host_deployment.v1.json"


def _read_payload(
    path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    langgraph_task_queue: str = CANONICAL_LANGGRAPH_QUEUE,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("payload must be a JSON object")
    frontier = validate_ready_frontier(
        payload.get("grok_ready_frontier"),
        serial_reason=str(payload.get("grok_serial_reason") or ""),
        default_model=draft_model(runtime_root=runtime_root),
    )
    if not frontier:
        raise ValueError("canonical Grok transaction requires a non-empty ready frontier")
    payload["grok_ready_frontier"] = frontier
    child = dict(payload.get("langgraph_child") or {})
    child.setdefault("enabled", True)
    child.setdefault("task_queue", langgraph_task_queue)
    child.setdefault("workflow_type", "XinaoIntegratedBusWorkflow")
    payload["langgraph_child"] = child
    return payload


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_verified_deployment() -> dict[str, Any]:
    return load_verified_deployment(PROJECT_ROOT, DEPLOYMENT_MANIFEST)


async def run(
    *,
    payload_path: Path,
    db: Path,
    run_root: Path,
    timeout_seconds: float,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    host_task_queue: str = CANONICAL_HOST_QUEUE,
    langgraph_task_queue: str = CANONICAL_LANGGRAPH_QUEUE,
    worker_deployment_name: str = "",
    resume_workflow_id: str = "",
    resume_run_id: str = "",
    resume_task_queue: str = "",
    resume_task_id: str = "",
) -> dict[str, Any]:
    payload_path = payload_path.resolve()
    payload = _read_payload(
        payload_path,
        runtime_root=runtime_root,
        langgraph_task_queue=langgraph_task_queue,
    )
    suffix = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = run_root.resolve() / f"canonical-grok-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    queue = resume_task_queue.strip() or host_task_queue
    workflow_id = str(payload.get("workflow_id") or f"xinao-canonical-grok-{suffix}")
    payload["workflow_id"] = workflow_id
    payload.setdefault("task_id", f"canonical-grok-{suffix}")
    payload.setdefault("generation", 0)
    payload.setdefault("immutable_intent_hash", hashlib.sha256(payload_path.read_bytes()).hexdigest())
    payload.setdefault("owner", "codex")
    payload.setdefault("decision_hash", str(payload["immutable_intent_hash"]))
    payload.setdefault("promoted_only", True)
    correlation_id = str(payload.get("correlation_id") or "").strip()
    parent_operation_id = str(payload.get("parent_operation_id") or payload.get("operation_id") or "").strip()

    deployment = _load_verified_deployment()
    deployment_name = worker_deployment_name.strip() or str(deployment["deployment_name"])
    os.environ.update(
        {
            "XINAO_COORD_DB": str(db.resolve()),
            "XINAO_TEMPORAL_ENABLED": "1",
            "XINAO_TEMPORAL_MOCK": "0",
            "XINAO_TEMPORAL_LIVE": "1",
            "XINAO_TEMPORAL_ADDRESS": "127.0.0.1:7233",
            "XINAO_TEMPORAL_NAMESPACE": "default",
            "XINAO_TEMPORAL_TASK_QUEUE": queue,
            "XINAO_TEMPORAL_WORKER_VERSIONING": "1",
            "XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME": deployment_name,
            "XINAO_TEMPORAL_WORKER_BUILD_ID": str(deployment["build_id"]),
        }
    )
    service = CoordinationService(db.resolve())
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    identity = f"canonical-grok-one-shot@{suffix}"
    worker = build_promoted_worker(
        client,
        task_queue=queue,
        workflows=PROMOTED_WORKFLOWS,
        activities=PROMOTED_ACTIVITIES,
        identity=identity,
    )

    async with worker:
        await ensure_deployment_current(
            "127.0.0.1:7233",
            deployment_name,
            str(deployment["build_id"]),
        )
        if resume_workflow_id.strip():
            if not resume_run_id.strip() or not resume_task_queue.strip():
                raise ValueError("resume requires workflow id, run id, and task queue")
            task_id = resume_task_id.strip()
            actual_workflow_id = resume_workflow_id.strip()
            run_id = resume_run_id.strip()
        else:
            task_id = create_kernel_backed_canary_task(service, payload, seed=suffix)
            started = await asyncio.to_thread(
                service.temporal_start_promoted,
                actor="codex",
                task_id=task_id,
                idempotency_key=f"canonical-grok-live-start-{suffix}",
            )
            actual_workflow_id = str(started["workflow_id"])
            run_id = str(started["run_id"])
        handle = client.get_workflow_handle(actual_workflow_id, run_id=run_id)
        started_record = {
            "schema_version": "xinao.canonical_grok_transaction.started.v1",
            "started_at": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "workflow_id": actual_workflow_id,
            "run_id": run_id,
            "task_queue": queue,
            "worker_identity": identity,
        }
        if correlation_id:
            started_record["correlation_id"] = correlation_id
        if parent_operation_id:
            started_record["parent_operation_id"] = parent_operation_id
        _write_json_atomic(run_dir / "started.json", started_record)
        try:
            async with asyncio.timeout(timeout_seconds):
                result = await handle.result()
        except (TimeoutError, asyncio.CancelledError) as exc:
            await handle.cancel()
            _write_json_atomic(
                run_dir / "aborted.json",
                {
                    "schema_version": "xinao.canonical_grok_transaction.aborted.v1",
                    "aborted_at": datetime.now(UTC).isoformat(),
                    "reason": type(exc).__name__,
                    "task_id": task_id,
                    "workflow_id": actual_workflow_id,
                    "run_id": run_id,
                    "task_queue": queue,
                    "workflow_cancel_requested": True,
                },
            )
            raise
        description = await handle.describe()

    if not isinstance(result, dict):
        raise TypeError("workflow result must be an object")
    grok_fanin = result.get("grok_fanin")
    output = {
        "ok": (
            result.get("ok") is True
            and result.get("terminal_status") == "completed"
            and isinstance(grok_fanin, dict)
            and grok_fanin.get("ok") is True
        ),
        "task_id": task_id,
        "workflow_id": actual_workflow_id,
        "run_id": run_id,
        "task_queue": queue,
        "worker_identity": identity,
        "worker_deployment_name": deployment_name,
        "worker_build_id": str(deployment["build_id"]),
        "langgraph_task_queue": langgraph_task_queue,
        "runtime_root": str(runtime_root.resolve()),
        "requested_models": sorted(
            {str(item.get("model") or "") for item in payload["grok_ready_frontier"]}
        ),
        "payload_path": str(payload_path),
        "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
        "workflow_status": description.status.name.lower(),
        "run_dir": str(run_dir),
        "result": result,
    }
    if correlation_id:
        output["correlation_id"] = correlation_id
    if parent_operation_id:
        output["parent_operation_id"] = parent_operation_id
    _write_json_atomic(run_dir / "result.json", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--timeout-seconds", type=float, default=1_800)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--host-task-queue", default=CANONICAL_HOST_QUEUE)
    parser.add_argument("--langgraph-task-queue", default=CANONICAL_LANGGRAPH_QUEUE)
    parser.add_argument("--worker-deployment-name", default="")
    parser.add_argument("--resume-workflow-id", default="")
    parser.add_argument("--resume-run-id", default="")
    parser.add_argument("--resume-task-queue", default="")
    parser.add_argument("--resume-task-id", default="")
    args = parser.parse_args()
    output = asyncio.run(
        run(
            payload_path=args.payload,
            db=args.db,
            run_root=args.run_root,
            timeout_seconds=args.timeout_seconds,
            runtime_root=args.runtime_root,
            host_task_queue=args.host_task_queue,
            langgraph_task_queue=args.langgraph_task_queue,
            worker_deployment_name=args.worker_deployment_name,
            resume_workflow_id=args.resume_workflow_id,
            resume_run_id=args.resume_run_id,
            resume_task_queue=args.resume_task_queue,
            resume_task_id=args.resume_task_id,
        )
    )
    print(
        json.dumps(
            {key: output[key] for key in ("ok", "task_id", "workflow_id", "run_id", "run_dir")},
            ensure_ascii=False,
        )
    )
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
