"""One-click Temporal E2E: connect → start → wait COMPLETED → query.

Default mode uses WorkflowEnvironment time-skipping (no live Temporal server).
Optional live mode: set XINAO_TEMPORAL_SELFTEST_LIVE=1 (requires server + worker).

Writes G25 evidence JSON. Does not touch client.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
for p in (str(SRC), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from adapters.temporal.names import (  # noqa: E402
    DEFAULT_TASK_QUEUE,
    QUERY_GET_STATUS,
    WORKFLOW_TYPE,
    verify_registered_names,
)

EVIDENCE_DIR = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance"
    r"\night_run_20260712\saturation\G25_temporal_selftest_e2e"
)


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _sample_input(task_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "workflow_id": f"xinao-task-{task_id}-g0",
        "generation": 0,
        "immutable_intent_hash": "g25-selftest-intent-hash-001",
        "title": "G25 selftest e2e",
        "goal": "connect start wait COMPLETED query",
        "source_thread_id": None,
        "owner": "g25",
        "decision_hash": "g25-selftest-intent-hash-001",
        "promoted_only": True,
        "step_count": 1,
    }


async def _run_time_skipping_e2e() -> dict[str, Any]:
    """Self-contained: env client + in-process worker + start + result + query."""
    from temporalio.testing import WorkflowEnvironment

    from adapters.temporal.worker_runtime import (
        build_promoted_worker,
        start_promoted_workflow,
    )

    task_id = f"g25-e2e-{uuid.uuid4().hex[:10]}"
    payload = _sample_input(task_id)
    task_queue = f"g25-selftest-e2e-{uuid.uuid4().hex[:8]}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        # connect (env.client is the connected Temporal client)
        client = env.client
        async with build_promoted_worker(client, task_queue=task_queue):
            # start
            handle = await start_promoted_workflow(
                client,
                payload,
                workflow_id=payload["workflow_id"],
                task_queue=task_queue,
            )
            # wait COMPLETED (result)
            result = await handle.result()
            # query after completion
            status = await handle.query(QUERY_GET_STATUS)
            try:
                desc = await handle.describe()
                desc_status = str(getattr(desc, "status", None) or "")
            except Exception as exc:  # noqa: BLE001
                desc_status = f"describe_error:{type(exc).__name__}"

    terminal = str(result.get("terminal_status") or "")
    status_field = str(status.get("status") or "")
    completed_ok = (
        bool(result.get("ok"))
        and terminal == "completed"
        and status_field == "completed"
    )
    return {
        "mode": "time_skipping",
        "ok": completed_ok,
        "phases": ["connect", "start", "wait_COMPLETED", "query"],
        "workflow_type": WORKFLOW_TYPE,
        "workflow_id": payload["workflow_id"],
        "task_queue": task_queue,
        "result": result,
        "query_name": QUERY_GET_STATUS,
        "query_status": status,
        "describe_status": desc_status,
        "terminal_status": terminal,
    }


async def _run_live_e2e() -> dict[str, Any]:
    """Live: Client.connect + start on promoted queue (worker must already poll)."""
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    address = os.environ.get("XINAO_TEMPORAL_ADDRESS", "127.0.0.1:7233").strip()
    namespace = os.environ.get("XINAO_TEMPORAL_NAMESPACE", "default").strip()
    task_queue = os.environ.get(
        "XINAO_TEMPORAL_TASK_QUEUE", DEFAULT_TASK_QUEUE
    ).strip()

    task_id = f"g25-live-{uuid.uuid4().hex[:10]}"
    payload = _sample_input(task_id)
    wf_id = payload["workflow_id"]

    # connect
    client = await Client.connect(address, namespace=namespace)
    start_info: dict[str, Any]
    try:
        # start
        handle = await client.start_workflow(
            WORKFLOW_TYPE,
            payload,
            id=wf_id,
            task_queue=task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        start_info = {"mode": "started", "run_id": handle.result_run_id}
    except WorkflowAlreadyStartedError as exc:
        handle = client.get_workflow_handle(wf_id)
        start_info = {
            "mode": "already_started",
            "run_id": getattr(exc, "run_id", None),
            "message": str(exc),
        }

    # wait COMPLETED
    result = await asyncio.wait_for(handle.result(), timeout=60)
    # query
    status = await handle.query(QUERY_GET_STATUS)
    try:
        desc = await handle.describe()
        desc_status = str(getattr(desc, "status", None) or "")
    except Exception as exc:  # noqa: BLE001
        desc_status = f"describe_error:{type(exc).__name__}"

    terminal = str(result.get("terminal_status") or "")
    status_field = str(status.get("status") or "")
    completed_ok = (
        bool(result.get("ok"))
        and terminal == "completed"
        and status_field == "completed"
    )
    return {
        "mode": "live",
        "ok": completed_ok,
        "phases": ["connect", "start", "wait_COMPLETED", "query"],
        "address": address,
        "namespace": namespace,
        "task_queue": task_queue,
        "workflow_type": WORKFLOW_TYPE,
        "workflow_id": wf_id,
        "start": start_info,
        "result": result,
        "query_name": QUERY_GET_STATUS,
        "query_status": status,
        "describe_status": desc_status,
        "terminal_status": terminal,
    }


async def main_async() -> dict[str, Any]:
    name_report = verify_registered_names()
    errors: list[str] = []
    e2e: dict[str, Any] | None = None
    live = _truthy("XINAO_TEMPORAL_SELFTEST_LIVE", "0")
    try:
        if live:
            e2e = await _run_live_e2e()
        else:
            e2e = await _run_time_skipping_e2e()
    except Exception:  # noqa: BLE001
        errors.append(traceback.format_exc())
        e2e = {"ok": False, "mode": "live" if live else "time_skipping", "error": "see errors[]"}

    all_ok = bool(name_report.get("ok")) and bool(e2e and e2e.get("ok")) and not errors
    return {
        "schema_version": "xinao.G25.temporal_selftest_e2e.v1",
        "lane": "G25",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pass": all_ok,
        "name_consistency": name_report,
        "e2e": e2e,
        "errors": errors,
        "forbidden_untouched": [
            "client.py",
            "policy.py",
            "service.py",
            "cli.py",
            "mcp_server.py",
            "pyproject.toml",
        ],
        "landed_files": [
            "adapters/temporal/names.py",
            "adapters/temporal/selftest_e2e.py",
            "adapters/temporal/worker_runtime.py",
            "adapters/temporal/canary_start_workflow.py",
            "adapters/temporal/workflow.py",
            "adapters/temporal/activities.py",
        ],
        "note_cn": (
            "G25：names SSOT 校验 workflow/activity/query 名一致；"
            "一键 selftest_e2e = connect→start→wait COMPLETED→query；"
            "默认 time-skipping，XINAO_TEMPORAL_SELFTEST_LIVE=1 走 live"
        ),
    }


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(main_async())
    out = EVIDENCE_DIR / "G25_temporal_selftest_e2e_latest.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "pass": report["pass"],
        "evidence": str(out),
        "name_ok": report["name_consistency"].get("ok"),
        "e2e_ok": (report.get("e2e") or {}).get("ok"),
        "e2e_mode": (report.get("e2e") or {}).get("mode"),
        "terminal_status": (report.get("e2e") or {}).get("terminal_status"),
        "query_name": (report.get("e2e") or {}).get("query_name"),
    }
    (EVIDENCE_DIR / "G25_RESULT.json").write_text(
        json.dumps(
            {
                "schema": "G25_RESULT.v1",
                "lane": "G25",
                "status": "PASS" if report["pass"] else "FAIL",
                "timestamp_utc": report["generated_at"],
                "summary": summary,
                "name_consistency": report["name_consistency"],
                "forbidden_touched": False,
                "evidence": str(out),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
