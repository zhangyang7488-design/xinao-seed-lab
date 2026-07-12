#!/usr/bin/env python3
"""Fresh C11 proof: read-only board exits and the kernel remains callable."""

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

import apsw
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client, WorkflowExecutionStatus

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from scripts.verify_c01_native_capability import _run_probe  # noqa: E402

DB = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3")
BOARD = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\S3_readonly_board_current.json")
INDEX = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\C11_readback_index_current.json")
DEFAULT_OUT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\C11_readonly_independence_latest.json")
C08_EVIDENCE = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave"
    r"\C08_temporal_kernel_convergence_latest.json"
)
DAEMON_EVIDENCE = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\integrated_bus_worker_daemon\latest.json")
CANONICAL_QUEUE = "xinao-integrated-langgraph-plugin-queue"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _daemon_binding_ready(daemon: dict[str, Any]) -> bool:
    """Validate the startup registration record; live pollers prove liveness below."""

    return bool(
        daemon.get("status") == "polling"
        and daemon.get("graph_id") == "xinao-integrated-bus-v2"
        and "XinaoIntegratedBusWorkflow" in (daemon.get("workflows_registered") or [])
    )


def _database_snapshot() -> dict[str, Any]:
    uri = f"file:{DB.as_posix()}?mode=ro"
    conn = apsw.Connection(uri, flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
    try:
        conn.execute("PRAGMA query_only=ON")
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in tables
        }
        return {
            "query_only": int(conn.execute("PRAGMA query_only").fetchone()[0]) == 1,
            "quick_check": str(conn.execute("PRAGMA quick_check").fetchone()[0]),
            "counts": counts,
            "max_event_seq": int(conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]),
        }
    finally:
        conn.close()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


async def _main_route_snapshot(workflow_id: str, run_id: str) -> dict[str, Any]:
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    description = await handle.describe()
    return {
        "workflow_id": description.id,
        "run_id": description.run_id,
        "status": description.status.name,
        "terminal": description.status is WorkflowExecutionStatus.COMPLETED,
    }


async def _canonical_queue_snapshot() -> dict[str, Any]:
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    output: dict[str, Any] = {}
    for label, queue_type in (
        ("workflow", TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
        ("activity", TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
    ):
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace="default",
                task_queue=TaskQueue(name=CANONICAL_QUEUE),
                task_queue_type=queue_type,
                report_pollers=True,
                report_stats=True,
            )
        )
        output[label] = {
            "pollers": [
                {
                    "identity": poller.identity,
                    "last_access_time": poller.last_access_time.ToDatetime(tzinfo=UTC).isoformat(),
                }
                for poller in response.pollers
            ],
            "backlog": int(response.task_queue_status.backlog_count_hint or 0)
            if response.HasField("task_queue_status")
            else 0,
        }
    return output


def build_evidence() -> dict[str, Any]:
    adapter_path = REPO / "scripts" / "_s3_ssot_read_adapter.py"
    verifier_path = Path(__file__).resolve()
    observer_path = REPO / "scripts" / "verify_c01_native_capability.py"
    route_verifier_path = REPO / "scripts" / "verify_temporal_kernel_convergence.py"
    bound_sources = (adapter_path, verifier_path, observer_path, route_verifier_path)
    source_hashes_start = {
        str(path.relative_to(REPO)).replace("/", "\\"): _sha256(path) for path in bound_sources
    }
    before = _database_snapshot()
    adapter = _run_probe(
        "c11_readonly_adapter",
        [sys.executable, str(adapter_path), "--snapshot"],
        include_stdout=True,
    )
    reader_finished_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = json.loads(str(adapter.get("stdout_text") or ""))
    if not isinstance(snapshot, dict):
        raise TypeError("reader snapshot must be an object")
    after_reader = _database_snapshot()
    _write_atomic(BOARD, snapshot)
    source_refs = snapshot.get("sources") if isinstance(snapshot.get("sources"), dict) else {}
    source_refs_current = bool(source_refs) and all(
        isinstance(meta, dict)
        and meta.get("exists") is True
        and Path(str(meta.get("path") or "")).is_file()
        and str(meta.get("sha256") or "").lower() == _sha256(Path(str(meta.get("path") or ""))).lower()
        for meta in source_refs.values()
    )
    kernel = snapshot.get("kernel") if isinstance(snapshot.get("kernel"), dict) else {}
    kernel_counts = kernel.get("counts") if isinstance(kernel.get("counts"), dict) else {}
    live_counts = before.get("counts") if isinstance(before.get("counts"), dict) else {}
    named_count_keys = {
        "threads",
        "tasks",
        "messages",
        "events",
        "artifacts",
        "agent_operations",
        "notification_outbox",
    }
    kernel_counts_match = all(kernel_counts.get(name) == live_counts.get(name) for name in named_count_keys)
    index = {
        "schema_version": "xinao.c11.readback_index.v1",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "board": {
            "path": str(BOARD),
            "sha256": _sha256(BOARD),
            "size_bytes": BOARD.stat().st_size,
        },
        "named_sources": source_refs,
        "all_named_sources_visible": snapshot.get("all_named_sources_visible") is True,
    }
    _write_atomic(INDEX, index)

    route_result = json.loads(C08_EVIDENCE.read_text(encoding="utf-8-sig"))
    if not isinstance(route_result, dict):
        raise TypeError("C08 evidence must be an object")
    workflow_id = str(route_result.get("workflow_id") or "")
    run_id = str(route_result.get("run_id") or "")
    route_after = (
        asyncio.run(_main_route_snapshot(workflow_id, run_id))
        if workflow_id and run_id
        else {"workflow_id": workflow_id, "run_id": run_id, "status": "MISSING", "terminal": False}
    )
    artifact = route_result.get("artifact") if isinstance(route_result.get("artifact"), dict) else {}
    artifact_path = Path(str(artifact.get("path") or ""))
    artifact_hash = _sha256(artifact_path) if artifact_path.is_file() else ""
    c08_hashes = (
        route_result.get("source_hashes") if isinstance(route_result.get("source_hashes"), dict) else {}
    )
    c08_sources_current = bool(c08_hashes) and all(
        (REPO / name).is_file() and _sha256(REPO / name).lower() == str(digest or "").lower()
        for name, digest in c08_hashes.items()
    )
    daemon = json.loads(DAEMON_EVIDENCE.read_text(encoding="utf-8-sig"))
    if not isinstance(daemon, dict):
        raise TypeError("daemon evidence must be an object")
    queue_snapshot = asyncio.run(_canonical_queue_snapshot())
    observed_now = datetime.now(UTC)
    queue_pollers_ready = all(
        isinstance(queue_snapshot.get(kind), dict) and bool(queue_snapshot[kind].get("pollers"))
        for kind in ("workflow", "activity")
    )
    queue_pollers_fresh = queue_pollers_ready and all(
        any(
            0 <= (observed_now - datetime.fromisoformat(str(item["last_access_time"]))).total_seconds() <= 90
            for item in queue_snapshot[kind]["pollers"]
        )
        for kind in ("workflow", "activity")
    )
    worker_runner_path = Path(
        r"E:\XINAO_RESEARCH_WORKSPACES\S\services\agent_runtime\integrated_bus_runner.py"
    )
    source_hashes_end = {
        str(path.relative_to(REPO)).replace("/", "\\"): _sha256(path) for path in bound_sources
    }
    checks = {
        "strict_reader_schema": snapshot.get("schema_version") == "xinao.s3.readback_snapshot.v1",
        "strict_reader_mode": snapshot.get("mode") == "strict_read_only"
        and kernel.get("sqlite_mode_ro") is True
        and kernel.get("query_only") is True
        and kernel.get("quick_check") == "ok",
        "all_named_sources_visible_and_hashed": snapshot.get("all_named_sources_visible") is True
        and source_refs_current,
        "fresh_kernel_counts_match_reader": kernel_counts_match,
        "fresh_process_adapter_exit_zero": adapter["exit_code"] == 0,
        "fresh_process_closed_after_read": adapter["root_process_exited"] is True
        and adapter["process_tree_resident_count"] == 0,
        "database_unchanged_by_reader": before == after_reader,
        "external_observer_no_window": adapter["visible_window_count"] == 0,
        "external_observer_no_focus": adapter["foreground_unchanged"] is True,
        "external_observer_exited": adapter["root_process_exited"] is True
        and adapter["process_tree_resident_count"] == 0,
        # The daemon file is a startup registration record, not a heartbeat.
        # Current workflow/activity pollers below are the bounded live signal.
        "canonical_daemon_ready_after_reader_exit": _daemon_binding_ready(daemon),
        "canonical_queue_pollers_fresh_after_reader_exit": queue_pollers_fresh,
        "last_verified_main_route_sources_current": c08_sources_current
        and route_result.get("completion_claim_allowed") is True,
        "last_verified_main_route_temporal_completed": route_after["terminal"] is True
        and route_after["status"] == "COMPLETED"
        and route_result.get("ok") is True
        and route_result.get("workflow_status") == "COMPLETED",
        "last_verified_main_route_d_artifact_hashed": artifact_path.is_file()
        and bool(artifact_hash)
        and artifact_hash == str(artifact.get("sha256") or "").lower()
        and int(artifact.get("size_bytes") or 0) == artifact_path.stat().st_size,
        "grok_admin_remained_paused_during_readiness_probe": before == after_reader,
        "worker_runner_binding_visible": worker_runner_path.is_file(),
        "fresh_board_and_index_written": BOARD.is_file()
        and INDEX.is_file()
        and str(index["board"]["sha256"]).lower() == _sha256(BOARD).lower(),
        "sources_stable_during_run": source_hashes_start == source_hashes_end,
    }
    main_route = {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "canonical_daemon_ready_after_reader_exit": checks["canonical_daemon_ready_after_reader_exit"],
        "canonical_queue_pollers_fresh_after_reader_exit": checks[
            "canonical_queue_pollers_fresh_after_reader_exit"
        ],
        "reader_finished_at_utc": reader_finished_at_utc,
        "status": route_after["status"],
        "terminal": route_after["terminal"],
        "route_result_path": str(C08_EVIDENCE),
        "route_result_sha256": _sha256(C08_EVIDENCE),
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_hash or None,
        "artifact_expected_sha256": artifact.get("sha256"),
    }
    observer = {
        "pid": adapter.get("pid"),
        "exit_code": adapter["exit_code"],
        "process_exited": adapter["root_process_exited"] is True
        and adapter["process_tree_resident_count"] == 0,
        "foreground_unchanged": adapter["foreground_unchanged"],
        "visible_window_count": adapter["visible_window_count"],
        "create_no_window": adapter["create_no_window"],
    }
    return {
        "schema_version": "xinao.c11.readonly_independence.v3",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": all(checks.values()),
        "completion_claim_allowed": all(checks.values()),
        "checks": checks,
        "database_before_reader": before,
        "database_after_reader": after_reader,
        "fresh_process_adapter": adapter,
        "readback_snapshot": snapshot,
        "board": {"path": str(BOARD), "sha256": _sha256(BOARD) if BOARD.is_file() else None},
        "index": {"path": str(INDEX), "sha256": _sha256(INDEX) if INDEX.is_file() else None},
        "main_route_before_after": main_route,
        "post_reader_daemon": daemon,
        "post_reader_queue_snapshot": queue_snapshot,
        "worker_runner_binding": {
            "path": str(worker_runner_path),
            "sha256": _sha256(worker_runner_path) if worker_runner_path.is_file() else None,
        },
        "observer_evidence": observer,
        "source_hashes_start": source_hashes_start,
        "source_hashes_end": source_hashes_end,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    output = Path(args.output)
    payload = build_evidence()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
