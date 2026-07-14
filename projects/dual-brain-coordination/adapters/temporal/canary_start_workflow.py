"""One-shot canary: start XinaoPromotedTaskWorkflowV1 on promoted queue and query status."""

# ruff: noqa: E402 -- this standalone adapter bootstraps repo/src before imports.

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
for p in (str(SRC), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from adapters.temporal.names import (
    DEFAULT_TASK_QUEUE,
    QUERY_GET_STATUS,
    WORKFLOW_TYPE,
)
from xinao_coordination.database import default_db_path
from xinao_coordination.service import CoordinationService

DEFAULT_OUT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance"
    r"\night_run_20260712\saturation\G1_temporal_worker\workflow_canary.json"
)


def create_kernel_backed_canary_task(
    service: CoordinationService,
    payload: dict[str, object],
    *,
    seed: str,
) -> str:
    """Create an accepted kernel task while preserving the requested Grok frontier."""

    opened = service.open_thread(
        actor="grok_4_5",
        title=str(payload.get("title") or "Temporal canary"),
        body=str(payload.get("goal") or "Verify the canonical promoted route."),
        idempotency_key=f"canary-open-{seed}",
    )
    thread = opened["thread"]
    if not isinstance(thread, dict):
        raise TypeError("open_thread returned no thread")
    thread_id = str(thread["thread_id"])
    decision_hash = str(payload.get("decision_hash") or seed)
    for actor in ("grok_4_5", "codex"):
        service.close_thread(
            actor=actor,
            thread_id=thread_id,
            decision="accept",
            resolution_key=decision_hash,
            summary="bounded kernel-backed Temporal canary",
            idempotency_key=f"canary-close-{actor}-{seed}",
        )
    metadata = {
        "owner": str(payload.get("owner") or "codex"),
        "grok_ready_frontier": list(payload.get("grok_ready_frontier") or []),
        "grok_serial_reason": str(payload.get("grok_serial_reason") or ""),
        "langgraph_child": dict(payload.get("langgraph_child") or {}),
    }
    correlation_id = str(payload.get("correlation_id") or "").strip()
    parent_operation_id = str(payload.get("parent_operation_id") or payload.get("operation_id") or "").strip()
    if correlation_id:
        metadata["correlation_id"] = correlation_id
    if parent_operation_id:
        metadata["parent_operation_id"] = parent_operation_id
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=decision_hash,
        title=str(payload.get("title") or "Temporal canary"),
        goal=str(payload.get("goal") or "Verify the canonical promoted route."),
        metadata=metadata,
        idempotency_key=f"canary-promote-{seed}",
    )
    task = promoted["task"]
    if not isinstance(task, dict):
        raise TypeError("promote_to_task returned no task")
    return str(task["task_id"])


async def main() -> int:
    address = os.environ.get("XINAO_TEMPORAL_ADDRESS", "127.0.0.1:7233").strip()
    namespace = os.environ.get("XINAO_TEMPORAL_NAMESPACE", "default").strip()
    task_queue = os.environ.get("XINAO_TEMPORAL_TASK_QUEUE", DEFAULT_TASK_QUEUE).strip()
    out_path = Path(os.environ.get("XINAO_TEMPORAL_CANARY_OUT", str(DEFAULT_OUT)))
    payload_path = os.environ.get("XINAO_TEMPORAL_CANARY_PAYLOAD", "").strip()

    wf_id = os.environ.get("XINAO_TEMPORAL_CANARY_WF_ID", "xinao-task-g1-canary-e2e-g0")
    timeout_seconds = float(os.environ.get("XINAO_TEMPORAL_CANARY_TIMEOUT", "900"))
    payload = {
        "task_id": "g1-canary-e2e",
        "workflow_id": wf_id,
        "generation": 0,
        "immutable_intent_hash": "g1-canary-intent",
        "title": "G1 canary",
        "goal": "prove worker executes workflow",
        "source_thread_id": None,
        "owner": "codex",
        "decision_hash": "g1-canary-intent",
        "promoted_only": True,
        "langgraph_child": {
            "enabled": True,
            "task_queue": "xinao-integrated-langgraph-plugin-queue",
            "workflow_type": "XinaoIntegratedBusWorkflow",
            "input_ref": "/app/materials/phase0_test_input.md",
        },
    }
    if payload_path:
        loaded = json.loads(Path(payload_path).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("XINAO_TEMPORAL_CANARY_PAYLOAD must contain a JSON object")
        payload = loaded

    client = await Client.connect(address, namespace=namespace)
    direct_mode = os.environ.get("XINAO_TEMPORAL_CANARY_DIRECT", "").strip() == "1"
    task_id = ""
    if not direct_mode:
        os.environ.update(
            {
                "XINAO_TEMPORAL_ENABLED": "1",
                "XINAO_TEMPORAL_MOCK": "0",
                "XINAO_TEMPORAL_LIVE": "1",
                "XINAO_TEMPORAL_ADDRESS": address,
                "XINAO_TEMPORAL_NAMESPACE": namespace,
                "XINAO_TEMPORAL_TASK_QUEUE": task_queue,
            }
        )
        service = CoordinationService(Path(os.environ.get("XINAO_COORD_DB", str(default_db_path()))))
        seed = "".join(ch if ch.isalnum() else "-" for ch in wf_id).strip("-")[:100]
        task_id = create_kernel_backed_canary_task(service, payload, seed=seed)
        started = await asyncio.to_thread(
            service.temporal_start_promoted,
            actor="codex",
            task_id=task_id,
            idempotency_key=f"canary-live-start-{seed}",
        )
        wf_id = str(started["workflow_id"])
        handle = client.get_workflow_handle(
            wf_id,
            run_id=str(started.get("run_id") or "") or None,
        )
        start_info = {
            "mode": str(started.get("mode") or "started"),
            "run_id": started.get("run_id"),
            "kernel_backed": True,
            "task_id": task_id,
        }
    else:
        if not str(payload.get("kernel_lease_token") or ""):
            raise ValueError(
                "direct canary requires an explicit kernel_lease_token; use the default kernel-backed route"
            )
        try:
            handle = await client.start_workflow(
                WORKFLOW_TYPE,
                payload,
                id=wf_id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
            start_info = {
                "mode": "started",
                "run_id": handle.result_run_id,
                "kernel_backed": False,
            }
        except WorkflowAlreadyStartedError as exc:
            handle = client.get_workflow_handle(wf_id)
            start_info = {
                "mode": "already_started",
                "run_id": getattr(exc, "run_id", None),
                "message": str(exc),
                "kernel_backed": False,
            }

    pause_for_grok = os.environ.get("XINAO_TEMPORAL_CANARY_PAUSE_FOR_GROK", "").strip() == "1"
    if pause_for_grok and start_info["mode"] == "started":
        await handle.signal("pause")
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            description = await handle.describe()
            if description.status is not WorkflowExecutionStatus.RUNNING:
                raise RuntimeError(
                    f"Grok canary workflow closed before fan-in: {description.status.name.lower()}"
                )
            status_before_cancel = await handle.query(QUERY_GET_STATUS)
            if status_before_cancel.get("grok_fanin"):
                await handle.signal("request_cancel", "canary_stop_after_grok_fanin")
                await handle.signal("resume")
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Grok fan-in did not appear before canary deadline")
            await asyncio.sleep(0.5)

    result = await asyncio.wait_for(handle.result(), timeout=timeout_seconds)
    # Query name from names SSOT (not bare "status" — that mismatch failed early canaries).
    status = await handle.query(QUERY_GET_STATUS)
    out = {
        "ok": True,
        "address": address,
        "namespace": namespace,
        "task_queue": task_queue,
        "workflow_type": WORKFLOW_TYPE,
        "workflow_id": wf_id,
        "task_id": task_id or None,
        "start": start_info,
        "result": result,
        "query_status": status,
        "query_name": QUERY_GET_STATUS,
        "timeout_seconds": timeout_seconds,
        "sandbox_import_error": False,
        "pause_for_grok": pause_for_grok,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path),
                "phase": status.get("last_phase"),
            },
            ensure_ascii=False,
        )
    )
    expected_terminal = os.environ.get("XINAO_TEMPORAL_CANARY_EXPECT_TERMINAL", "").strip()
    if expected_terminal:
        return 0 if result.get("terminal_status") == expected_terminal else 1
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
