#!/usr/bin/env python3
"""C13 live Stop proof against real Temporal and the Docker LangGraph child.

The parent worker is an in-process, one-shot canary on a unique queue.  It
registers the production workflow/activities but supplies no Grok frontier.
The canonical Docker ``houtai-gongren`` remains the child-workflow worker.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import Worker

from xinao_coordination.agent_operations import RECONCILABLE_STATES, AgentOperationStore
from xinao_coordination.errors import InvalidTransitionError, LeaseError
from xinao_coordination.service import CoordinationService
from xinao_coordination.temporal.activities import PROMOTED_ACTIVITIES
from xinao_coordination.temporal.workflow import PROMOTED_WORKFLOWS

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs"
    r"\continuous-relay-20260712-019f5302"
)
DEFAULT_LATEST = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance"
    r"\night_run_20260712\saturation\G11_stop_lease\C13_live_stop_current.json"
)
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
TERMINAL = {
    WorkflowExecutionStatus.COMPLETED,
    WorkflowExecutionStatus.FAILED,
    WorkflowExecutionStatus.CANCELED,
    WorkflowExecutionStatus.TERMINATED,
    WorkflowExecutionStatus.TIMED_OUT,
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status_name(value: object) -> str:
    return str(getattr(value, "name", value))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _accepted_task(service: CoordinationService, suffix: str) -> str:
    opened = service.open_thread(
        actor="grok_4_5",
        title=f"C13 live Stop canary {suffix}",
        body="Logical acceptance fixture only; no model or ACPX invocation.",
        idempotency_key=f"c13-open-{suffix}",
    )
    thread = opened["thread"]
    assert isinstance(thread, dict)
    thread_id = str(thread["thread_id"])
    service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"c13-resolution-{suffix}",
        summary="logical peer vote; no external invocation",
        idempotency_key=f"c13-close-peer-{suffix}",
    )
    service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"c13-resolution-{suffix}",
        summary="bounded live Stop canary",
        idempotency_key=f"c13-close-codex-{suffix}",
    )
    promoted = service.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"c13-resolution-{suffix}",
        title="C13 live parent-child cancellation",
        goal="Reach a real Docker LangGraph child, then prove Stop cancellation convergence.",
        metadata={
            "grok_ready_frontier": [],
            "grok_serial_reason": "not applicable: bounded Stop canary has no model work",
            "langgraph_child": {
                "enabled": True,
                "task_queue": "xinao-integrated-langgraph-plugin-queue",
                "workflow_type": "XinaoIntegratedBusWorkflow",
                "input_ref": "/app/materials/phase0_test_input.md",
            },
        },
        idempotency_key=f"c13-promote-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    return str(task["task_id"])


def _fresh_process_check(db: Path, task_id: str, old_lease: str) -> dict[str, Any]:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src"),
        "XINAO_C13_OLD_LEASE": old_lease,
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--fresh-check",
            "--db",
            str(db),
            "--task-id",
            task_id,
        ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        creationflags=WINDOWLESS,
    )
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {}
    return {
        "exit_code": proc.returncode,
        "payload": payload,
        "stderr_tail": proc.stderr[-1000:],
        "create_no_window": bool(WINDOWLESS) if os.name == "nt" else True,
    }


def fresh_check(db: Path, task_id: str) -> int:
    service = CoordinationService(db)
    old_lease = os.environ.get("XINAO_C13_OLD_LEASE", "")
    before_event_count = int(service.db.execute_read("SELECT count(*) AS n FROM events")[0]["n"])
    before_completed = int(
        service.db.execute_read("SELECT count(*) AS n FROM events WHERE event_type='TaskCompleted'")[0]["n"]
    )
    checks: dict[str, bool] = {
        "stop_active": service.stop_status().get("active") is True,
        "old_lease_present": bool(old_lease),
    }
    errors: dict[str, str] = {}
    try:
        service.dispatch_task(
            actor="codex",
            title="must remain blocked after Stop",
            goal="negative canary",
            explicit_non_consensus=True,
            idempotency_key="c13-fresh-dispatch-must-block",
        )
        checks["new_dispatch_rejected"] = False
    except InvalidTransitionError as exc:
        checks["new_dispatch_rejected"] = True
        errors["new_dispatch"] = type(exc).__name__
    try:
        service.temporal_start_promoted(
            actor="codex",
            task_id=task_id,
            idempotency_key="c13-fresh-temporal-must-block",
        )
        checks["temporal_restart_rejected"] = False
    except InvalidTransitionError as exc:
        checks["temporal_restart_rejected"] = True
        errors["temporal_restart"] = type(exc).__name__
    try:
        service.complete_task(
            actor="admin",
            task_id=task_id,
            lease_token=old_lease,
            result_summary="stale generation must not write",
            evidence=[{"kind": "c13", "result": "must_not_land"}],
            idempotency_key="c13-fresh-stale-write-must-block",
        )
        checks["stale_generation_write_rejected"] = False
    except LeaseError as exc:
        checks["stale_generation_write_rejected"] = True
        errors["stale_write"] = type(exc).__name__
    except Exception as exc:
        checks["stale_generation_write_rejected"] = False
        errors["stale_write"] = type(exc).__name__
    after_event_count = int(service.db.execute_read("SELECT count(*) AS n FROM events")[0]["n"])
    after_completed = int(
        service.db.execute_read("SELECT count(*) AS n FROM events WHERE event_type='TaskCompleted'")[0]["n"]
    )
    checks["rejected_calls_left_no_events"] = before_event_count == after_event_count
    checks["stale_write_left_no_completion"] = before_completed == after_completed
    payload = {
        "ok": all(checks.values()),
        "fresh_process": True,
        "checks": checks,
        "expected_rejections": errors,
        "event_counts": {
            "before": before_event_count,
            "after": after_event_count,
            "task_completed_before": before_completed,
            "task_completed_after": after_completed,
        },
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


async def _wait_query(handle: Any, *, timeout: float = 60.0) -> tuple[dict[str, Any], str]:
    deadline = asyncio.get_running_loop().time() + timeout
    last: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        try:
            value = await handle.query("get_status")
            if isinstance(value, dict):
                last = value
                child_id = str(value.get("current_child_workflow_id") or "")
                if child_id:
                    return value, child_id
        except Exception:
            pass
        desc = await handle.describe()
        if desc.status in TERMINAL:
            break
        await asyncio.sleep(0.1)
    raise TimeoutError(f"parent never exposed a running child; last_status={last}")


async def _wait_terminal(handle: Any, *, timeout: float = 45.0) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        desc = await handle.describe()
        if desc.status in TERMINAL:
            return _status_name(desc.status)
        await asyncio.sleep(0.1)
    return "UNCONFIRMED"


async def _count_exact(client: Client, workflow_id: str) -> int:
    count = 0
    async for _item in client.list_workflows(
        f'WorkflowId = "{workflow_id}"',
        limit=10,
    ):
        count += 1
    return count


async def cleanup_exact_workflow(queue: str, workflow_id: str) -> dict[str, Any]:
    """Bounded cleanup for a canary-owned parent whose one-shot worker exited."""
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    async with Worker(
        client,
        task_queue=queue,
        workflows=PROMOTED_WORKFLOWS,
        activities=PROMOTED_ACTIVITIES,
        identity=f"c13-exact-cleanup@{workflow_id[-24:]}",
    ):
        handle = client.get_workflow_handle(workflow_id)
        before = await handle.describe()
        if before.status not in TERMINAL:
            await handle.cancel()
        terminal = await _wait_terminal(handle)
    return {
        "ok": terminal == "CANCELED",
        "workflow_id": workflow_id,
        "task_queue": queue,
        "status_before": _status_name(before.status),
        "status_after": terminal,
        "bounded_one_shot_worker": True,
    }


async def run_canary(run_dir: Path) -> dict[str, Any]:
    run_id = f"c13-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    evidence_dir = run_dir / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    db = evidence_dir / "coordination.sqlite3"
    stop_dir = evidence_dir / "stop"
    parent_queue = f"xinao-c13-stop-{uuid.uuid4().hex}"
    os.environ.update(
        {
            "XINAO_COORD_DB": str(db),
            "XINAO_COORD_STOP_DIR": str(stop_dir),
            "XINAO_TEMPORAL_ENABLED": "1",
            "XINAO_TEMPORAL_MOCK": "0",
            "XINAO_TEMPORAL_LIVE": "1",
            "XINAO_TEMPORAL_ADDRESS": "127.0.0.1:7233",
            "XINAO_TEMPORAL_NAMESPACE": "default",
            "XINAO_TEMPORAL_TASK_QUEUE": parent_queue,
            "XINAO_MBG_ENABLED": "1",
            "XINAO_MBG_SCRATCH_ROOT": str(evidence_dir / "mbg_scratch"),
        }
    )
    plan = {
        "schema_version": "xinao.c13.live_stop.plan.v1",
        "created_at_utc": _now(),
        "bounded_episode": {
            "max_seconds": 420,
            "max_parent_workflows": 1,
            "max_child_workflows": 1,
            "exit_condition": "parent and child CANCELED plus fresh-process Stop fences",
        },
        "route": {
            "parent_queue": parent_queue,
            "child_queue": "xinao-integrated-langgraph-plugin-queue",
            "grok_ready_frontier": [],
            "grok_admin_invocations_allowed": 0,
        },
        "negative_checks": [
            "no visible window or focus/input action",
            "no OS scheduler, periodic timer, daemon, or persistence",
            "no fresh-process dispatch/restart/stale write after Stop",
        ],
    }
    plan_path = evidence_dir / "plan.json"
    _write_json(plan_path, plan)

    client = await Client.connect("127.0.0.1:7233", namespace="default")
    service = CoordinationService(db)
    task_id = _accepted_task(service, run_id)
    mbg_task_id = _accepted_task(service, f"{run_id}-mbg")
    mbg_dispatched = service.mbg_dispatch(
        actor="codex",
        task_id=mbg_task_id,
        idempotency_key=f"c13-mbg-{run_id}",
        start_transport=False,
    )
    mbg_operation = mbg_dispatched.get("operation")
    assert isinstance(mbg_operation, dict)
    mbg_operation_id = str(mbg_operation["operation_id"])
    parent_id = ""
    child_id = ""
    result: dict[str, Any]
    try:
        async with Worker(
            client,
            task_queue=parent_queue,
            workflows=PROMOTED_WORKFLOWS,
            activities=PROMOTED_ACTIVITIES,
            identity=f"c13-one-shot@{run_id}",
        ):
            started = await asyncio.to_thread(
                service.temporal_start_promoted,
                actor="codex",
                task_id=task_id,
                idempotency_key=f"c13-live-start-{run_id}",
            )
            parent_id = str(started["workflow_id"])
            parent_run_id = str(started.get("run_id") or "")
            if not parent_run_id:
                raise RuntimeError("live Temporal start did not return an exact parent run_id")
            parent = client.get_workflow_handle(parent_id, run_id=parent_run_id)
            await parent.signal("pause")
            async with asyncio.timeout(180):
                # Resume even if the pause signal arrived while start activities ran.
                await asyncio.sleep(0.2)
                await parent.signal("resume")
                query_before, child_id = await _wait_query(parent)
                child_unpinned = client.get_workflow_handle(child_id)
                child_before = await child_unpinned.describe()
                child_run_id = str(child_before.run_id or "")
                if not child_run_id:
                    raise RuntimeError("real LangGraph child did not expose an exact run_id")
                child = client.get_workflow_handle(child_id, run_id=child_run_id)
                task_before = service.get_task(task_id)["task"]
                assert isinstance(task_before, dict)
                old_lease = str((task_before.get("metadata") or {}).get("temporal_kernel_lease_token") or "")
                stopped = await asyncio.to_thread(
                    service.user_stop,
                    actor="user",
                    reason="C13 bounded live Stop canary",
                    scope="global",
                    idempotency_key=f"c13-live-stop-{run_id}",
                )
                parent_terminal = await _wait_terminal(parent)
                child_terminal = await _wait_terminal(child)
                parent_history = await parent.fetch_history()
                child_history = await child.fetch_history()
                parent_history_path = evidence_dir / "parent_history.json"
                child_history_path = evidence_dir / "child_history.json"
                _write_json(parent_history_path, parent_history.to_json_dict())
                _write_json(child_history_path, child_history.to_json_dict())
                fresh = _fresh_process_check(db, task_id, old_lease)
                parent_exact_count = await _count_exact(client, parent_id)
                child_exact_count = await _count_exact(client, child_id)
                task_after = service.get_task(task_id)["task"]
                assert isinstance(task_after, dict)
                task_view_after = service.get_task(task_id)
                attempts_after = task_view_after.get("attempts")
                assert isinstance(attempts_after, list)
                mbg_task_after = service.get_task(mbg_task_id)["task"]
                assert isinstance(mbg_task_after, dict)
                mbg_operation_after = AgentOperationStore(db).get(mbg_operation_id)["operation"]
                assert isinstance(mbg_operation_after, dict)
                active_operations = AgentOperationStore(db).list(limit=500).get("operations")
                assert isinstance(active_operations, list)
                active_operations = [
                    item for item in active_operations if str(item.get("state") or "") in RECONCILABLE_STATES
                ]
                temporal_worker_id = str(task_before.get("lease_owner") or "")
                worker_rows = service.db.execute_read(
                    "SELECT status,last_lease_token FROM workers WHERE worker_id=?",
                    (temporal_worker_id,),
                )
                worker_after = worker_rows[0] if worker_rows else {}
                cancel_requests = stopped.get("temporal_cancel_requests")
                request = cancel_requests[0] if isinstance(cancel_requests, list) and cancel_requests else {}
                parent_history_text = parent_history_path.read_text(encoding="utf-8")
                timer_started = parent_history_text.count("EVENT_TYPE_TIMER_STARTED")
                timer_canceled = parent_history_text.count("EVENT_TYPE_TIMER_CANCELED")
                checks = {
                    "parent_reached_real_child": bool(child_id),
                    "child_running_before_stop": _status_name(child_before.status) == "RUNNING",
                    "parent_temporal_canceled": parent_terminal == "CANCELED",
                    "child_temporal_canceled": child_terminal == "CANCELED",
                    "kernel_task_canceled": task_after.get("state") == "canceled",
                    "stop_epoch_active": service.stop_status().get("active") is True,
                    "service_cancel_all_confirmed": stopped.get("temporal_cancel_all_ok") is True,
                    "native_cancel_terminal_confirmed": isinstance(request, dict)
                    and request.get("terminal_confirmed") is True,
                    "native_cancel_exact_run_confirmed": isinstance(request, dict)
                    and request.get("workflow_id") == parent_id
                    and request.get("run_id") == parent_run_id,
                    "fresh_process_no_revival": fresh.get("exit_code") == 0
                    and (fresh.get("payload") or {}).get("ok") is True,
                    "fresh_process_old_lease_present": ((fresh.get("payload") or {}).get("checks") or {}).get(
                        "old_lease_present"
                    )
                    is True,
                    "fresh_process_exact_lease_fence": (
                        (fresh.get("payload") or {}).get("expected_rejections") or {}
                    ).get("stale_write")
                    == "LeaseError",
                    "fresh_process_rejections_left_no_events": (
                        (fresh.get("payload") or {}).get("checks") or {}
                    ).get("rejected_calls_left_no_events")
                    is True,
                    "single_parent_execution": parent_exact_count == 1,
                    "single_child_execution": child_exact_count == 1,
                    "no_grok_activity_scheduled": "xinao.grok.execute_acpx_lane" not in parent_history_text,
                    "task_attempts_canceled": bool(attempts_after)
                    and all(
                        item.get("state") == "canceled" and item.get("finished_at_ms") is not None
                        for item in attempts_after
                    ),
                    "worker_registry_fenced": worker_after.get("status") == "stale"
                    and worker_after.get("last_lease_token") is None,
                    "mbg_task_canceled": mbg_task_after.get("state") == "canceled",
                    "mbg_operation_canceled_before_transport": mbg_operation_after.get("state") == "canceled"
                    and mbg_operation_after.get("collector_pid") is None,
                    "agent_operation_cancel_confirmed": stopped.get("agent_cancel_all_ok") is True,
                    "no_active_agent_operations": not active_operations,
                    "global_scope_explicit": service.stop_status().get("scope") == "global",
                    "temporal_workflow_timer_not_resident": timer_started == 0
                    or timer_canceled >= timer_started,
                }
                result = {
                    "schema_version": "xinao.c13.live_stop.v1",
                    "generated_at_utc": _now(),
                    "ok": all(checks.values()),
                    "checks": checks,
                    "workflow": {
                        "parent_id": parent_id,
                        "parent_run_id": parent_run_id,
                        "parent_queue": parent_queue,
                        "parent_status": parent_terminal,
                        "child_id": child_id,
                        "child_run_id": child_run_id,
                        "child_queue": "xinao-integrated-langgraph-plugin-queue",
                        "child_status_before_stop": _status_name(child_before.status),
                        "child_status": child_terminal,
                        "query_before_stop": query_before,
                        "parent_exact_visibility_count": parent_exact_count,
                        "child_exact_visibility_count": child_exact_count,
                    },
                    "kernel": {
                        "db_path": str(db),
                        "task_id": task_id,
                        "state_after": task_after.get("state"),
                        "attempts_after": attempts_after,
                        "worker_id": temporal_worker_id,
                        "worker_after": worker_after,
                        "mbg_task_id": mbg_task_id,
                        "mbg_task_state_after": mbg_task_after.get("state"),
                        "mbg_operation_id": mbg_operation_id,
                        "mbg_operation_state_after": mbg_operation_after.get("state"),
                        "stop_status": service.stop_status(),
                    },
                    "stop_result": stopped,
                    "fresh_process": fresh,
                    "history": {
                        "parent": {
                            "path": str(parent_history_path),
                            "sha256": _sha256(parent_history_path),
                        },
                        "child": {
                            "path": str(child_history_path),
                            "sha256": _sha256(child_history_path),
                        },
                    },
                    "non_claims": {
                        "visible_window": "covered by C01/C11/C15, not self-reported here",
                        "focus_or_input": "covered by C01/C11/C15, not self-reported here",
                        "os_scheduler_or_daemon": "covered by C15, not self-reported here",
                    },
                    "temporal_timers": {
                        "started": timer_started,
                        "canceled": timer_canceled,
                        "resident_after_terminal": False,
                    },
                    "source_hashes": {
                        str(path.relative_to(REPO)).replace("/", "\\"): _sha256(path)
                        for path in (
                            REPO / "src" / "xinao_coordination" / "service.py",
                            REPO / "src" / "xinao_coordination" / "temporal" / "client.py",
                            REPO / "src" / "xinao_coordination" / "temporal" / "workflow.py",
                            REPO / "src" / "xinao_coordination" / "agent_operations.py",
                            REPO / "scripts" / "verify_c13_live_stop.py",
                        )
                    },
                    "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
                }
    except Exception as exc:
        cleanup_terminal = "NOT_NEEDED"
        if parent_id:
            try:
                async with Worker(
                    client,
                    task_queue=parent_queue,
                    workflows=PROMOTED_WORKFLOWS,
                    activities=PROMOTED_ACTIVITIES,
                    identity=f"c13-cleanup@{run_id}",
                ):
                    handle = client.get_workflow_handle(parent_id)
                    desc = await handle.describe()
                    if desc.status not in TERMINAL:
                        await handle.cancel()
                    cleanup_terminal = await _wait_terminal(handle)
            except Exception as cleanup_exc:
                cleanup_terminal = f"UNCONFIRMED:{type(cleanup_exc).__name__}"
        result = {
            "schema_version": "xinao.c13.live_stop.v1",
            "generated_at_utc": _now(),
            "ok": False,
            "error_type": type(exc).__name__,
            "message": str(exc)[:1000],
            "workflow": {"parent_id": parent_id, "child_id": child_id},
            "cleanup_terminal": cleanup_terminal,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
        }
    result_path = evidence_dir / "result.json"
    _write_json(result_path, result)
    result["evidence_path"] = str(result_path)
    result["evidence_sha256"] = _sha256(result_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--output", default=str(DEFAULT_LATEST))
    parser.add_argument("--fresh-check", action="store_true")
    parser.add_argument("--cleanup-workflow", action="store_true")
    parser.add_argument("--queue")
    parser.add_argument("--workflow-id")
    parser.add_argument("--db")
    parser.add_argument("--task-id")
    args = parser.parse_args()
    if args.fresh_check:
        if not args.db or not args.task_id:
            raise SystemExit("--fresh-check requires --db and --task-id")
        return fresh_check(Path(args.db), args.task_id)
    if args.cleanup_workflow:
        if not args.queue or not args.workflow_id:
            raise SystemExit("--cleanup-workflow requires --queue and --workflow-id")
        payload = asyncio.run(cleanup_exact_workflow(args.queue, args.workflow_id))
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["ok"] else 1
    payload = asyncio.run(run_canary(Path(args.run_dir)))
    _write_json(Path(args.output), payload)
    print(
        json.dumps(
            {
                "ok": payload.get("ok"),
                "output": str(Path(args.output)),
                "parent_id": (payload.get("workflow") or {}).get("parent_id"),
                "child_id": (payload.get("workflow") or {}).get("child_id"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
