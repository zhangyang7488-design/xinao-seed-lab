#!/usr/bin/env python3
"""Run one bounded no-Grok parent -> Docker LangGraph completion canary."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from xinao_coordination.service import CoordinationService
from xinao_coordination.temporal.activities import PROMOTED_ACTIVITIES
from xinao_coordination.temporal.workflow import PROMOTED_WORKFLOWS

DEFAULT_DB = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3")
DEFAULT_RUN_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs"
    r"\continuous-relay-20260712-019f5302"
)


def _accepted_task(service: CoordinationService, suffix: str) -> str:
    opened = service.open_thread(
        actor="grok_4_5",
        title=f"C08 kernel convergence canary {suffix}",
        body="Logical fixture only; no Grok/Admin transport invocation.",
        idempotency_key=f"c08-open-{suffix}",
    )
    thread = opened["thread"]
    assert isinstance(thread, dict)
    thread_id = str(thread["thread_id"])
    for actor in ("grok_4_5", "codex"):
        service.close_thread(
            actor=actor,
            thread_id=thread_id,
            decision="accept",
            resolution_key=f"c08-resolution-{suffix}",
            summary="bounded kernel convergence canary",
            idempotency_key=f"c08-close-{actor}-{suffix}",
        )
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"c08-resolution-{suffix}",
        title="C08 real Temporal kernel convergence",
        goal="Complete one real Docker LangGraph child and converge SQLite plus D artifact.",
        metadata={
            "grok_ready_frontier": [],
            "grok_serial_reason": "not applicable: bounded convergence canary has no model work",
            "langgraph_child": {
                "enabled": True,
                "task_queue": "xinao-integrated-langgraph-plugin-queue",
                "workflow_type": "XinaoIntegratedBusWorkflow",
                "input_ref": "/app/materials/phase0_test_input.md",
            },
        },
        idempotency_key=f"c08-promote-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    return str(task["task_id"])


async def run(db: Path, run_root: Path) -> dict[str, Any]:
    suffix = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = run_root / f"c08-convergence-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    queue = f"xinao-c08-convergence-{uuid.uuid4().hex}"
    os.environ.update(
        {
            "XINAO_COORD_DB": str(db),
            "XINAO_TEMPORAL_ENABLED": "1",
            "XINAO_TEMPORAL_MOCK": "0",
            "XINAO_TEMPORAL_LIVE": "1",
            "XINAO_TEMPORAL_ADDRESS": "127.0.0.1:7233",
            "XINAO_TEMPORAL_NAMESPACE": "default",
            "XINAO_TEMPORAL_TASK_QUEUE": queue,
        }
    )
    service = CoordinationService(db)
    task_id = _accepted_task(service, suffix)
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    async with Worker(
        client,
        task_queue=queue,
        workflows=PROMOTED_WORKFLOWS,
        activities=PROMOTED_ACTIVITIES,
        identity=f"c08-one-shot@{suffix}",
    ):
        started = await asyncio.to_thread(
            service.temporal_start_promoted,
            actor="codex",
            task_id=task_id,
            idempotency_key=f"c08-live-start-{suffix}",
        )
        workflow_id = str(started["workflow_id"])
        run_id = str(started["run_id"])
        handle = client.get_workflow_handle(workflow_id, run_id=run_id)
        async with asyncio.timeout(180):
            result = await handle.result()
        if not isinstance(result, dict):
            raise TypeError("workflow result must be an object")
    output = {
        "ok": result.get("ok") is True and result.get("terminal_status") == "completed",
        "task_id": task_id,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "task_queue": queue,
        "worker_identity": f"c08-one-shot@{suffix}",
        "grok_admin_transport_invocations": 0,
        "run_dir": str(run_dir),
        "result": result,
    }
    result_path = run_dir / "result.json"
    temporary = result_path.with_name(f".{result_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, result_path)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    args = parser.parse_args()
    payload = asyncio.run(run(args.db, args.run_root))
    print(
        json.dumps(
            {key: payload[key] for key in ("ok", "task_id", "workflow_id", "run_id", "run_dir")},
            ensure_ascii=False,
        )
    )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
