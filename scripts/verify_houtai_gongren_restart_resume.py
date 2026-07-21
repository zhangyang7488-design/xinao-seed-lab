#!/usr/bin/env python3
"""One-shot durability canary for the canonical Docker LangGraph worker.

Starts one real ``XinaoIntegratedBusWorkflow``, waits until its Docker-native
Grok operation and session are both materialized, restarts the exact
pre-identified ``houtai-gongren`` container once, and proves that the same
Temporal workflow/run resumes and completes. No scheduler, Admin invocation,
or resident helper is created.
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

from temporalio.api.enums.v1 import EventType, TaskQueueType, TimeoutType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client, WorkflowExecutionStatus

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from services.agent_runtime.worker_repo_mount_identity import actual_mount_report  # noqa: E402

RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_RUN_DIR = (
    RUNTIME / "state" / "Codex_Situation_Island" / "runs" / "continuous-relay-20260712-019f5302"
)
DEFAULT_LATEST = RUNTIME / "state" / "integrated_bus_worker_restart" / "latest.json"
DAEMON_LATEST = RUNTIME / "state" / "integrated_bus_worker_daemon" / "latest.json"
CONTAINER_NAME = "houtai-gongren"
COMPOSER_MODEL = "grok-composer-2.5-fast"
WORKFLOW_TYPE = "XinaoIntegratedBusWorkflow"
WORKFLOW_QUEUE = "xinao-integrated-langgraph-plugin-queue"
ALL_QUEUES = (
    WORKFLOW_QUEUE,
    "xinao-integrated-bus-parent-queue",
    "xinao-integrated-bus-child-queue",
)
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
TERMINAL = {
    WorkflowExecutionStatus.COMPLETED,
    WorkflowExecutionStatus.FAILED,
    WorkflowExecutionStatus.CANCELED,
    WorkflowExecutionStatus.TERMINATED,
    WorkflowExecutionStatus.CONTINUED_AS_NEW,
    WorkflowExecutionStatus.TIMED_OUT,
}
_ACTIVE_WORKFLOW_ID = ""
_ACTIVE_WORKFLOW_RUN_ID = ""
_ACTIVE_CONTAINER_PRE: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=WINDOWLESS,
    )


def docker_identity(reference: str = CONTAINER_NAME) -> dict[str, Any]:
    # Select fields explicitly: never dump Config.Env, which may contain secrets.
    template = "\n".join(
        [
            "{{.Id}}",
            "{{.Created}}",
            "{{.State.Pid}}",
            "{{.State.StartedAt}}",
            "{{.State.Status}}",
            "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
            "{{.Image}}",
            "{{.Path}}",
            "{{json .Args}}",
            '{{index .Config.Labels "com.docker.compose.project"}}',
            '{{index .Config.Labels "com.docker.compose.service"}}',
            '{{index .Config.Labels "com.docker.compose.project.config_files"}}',
            '{{index .Config.Labels "com.docker.compose.config-hash"}}',
            "{{json .Mounts}}",
        ]
    )
    proc = _run(["docker", "inspect", "--format", template, reference])
    if proc.returncode != 0:
        raise RuntimeError(f"docker inspect failed: {proc.stderr[-500:]}")
    lines = proc.stdout.splitlines()
    if len(lines) < 14:
        raise RuntimeError(f"docker inspect shape mismatch: {len(lines)} lines")
    mounts_raw = json.loads(lines[13])
    mounts = sorted(
        (
            {
                "source": str(item.get("Source") or ""),
                "destination": str(item.get("Destination") or ""),
                "rw": bool(item.get("RW")),
            }
            for item in mounts_raw
            if isinstance(item, dict)
        ),
        key=lambda item: (item["destination"], item["source"]),
    )
    return {
        "id": lines[0],
        "created": lines[1],
        "pid": int(lines[2] or 0),
        "started_at": lines[3],
        "status": lines[4],
        "health": lines[5],
        "image_id": lines[6],
        "path": lines[7],
        "args": json.loads(lines[8]),
        "compose_project": lines[9],
        "compose_service": lines[10],
        "compose_file": lines[11],
        "config_hash": lines[12],
        "mounts": mounts,
    }


def _static_identity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "id",
            "created",
            "image_id",
            "path",
            "args",
            "compose_project",
            "compose_service",
            "compose_file",
            "config_hash",
            "mounts",
        )
    }


def _daemon_state() -> dict[str, Any]:
    if not DAEMON_LATEST.is_file():
        return {}
    try:
        value = json.loads(DAEMON_LATEST.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _timestamp_text(value: Any) -> str:
    try:
        return value.ToDatetime(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


async def queue_snapshot(client: Client) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for queue in ALL_QUEUES:
        per_type: dict[str, Any] = {}
        for label, queue_type in (
            ("workflow", TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
            ("activity", TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
        ):
            response = await client.workflow_service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace=client.namespace,
                    task_queue=TaskQueue(name=queue),
                    task_queue_type=queue_type,
                    report_stats=True,
                    report_pollers=True,
                )
            )
            per_type[label] = {
                "pollers": [
                    {
                        "identity": poller.identity,
                        "last_access_time": _timestamp_text(poller.last_access_time),
                    }
                    for poller in response.pollers
                ],
                "backlog": int(response.task_queue_status.backlog_count_hint or 0)
                if response.HasField("task_queue_status")
                else 0,
            }
        snapshot[queue] = per_type
    return snapshot


def _queues_ready(snapshot: dict[str, Any], *, after: datetime | None = None) -> bool:
    for queue in ALL_QUEUES:
        item = snapshot.get(queue)
        if not isinstance(item, dict):
            return False
        for label in ("workflow", "activity"):
            typed = item.get(label)
            pollers = typed.get("pollers") if isinstance(typed, dict) else None
            if not isinstance(pollers, list) or not pollers:
                return False
            if after is not None and not any(
                _parse_time(str(poller.get("last_access_time"))) > after
                for poller in pollers
                if isinstance(poller, dict) and poller.get("last_access_time")
            ):
                return False
    return True


def _event_rows(history: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in history.events:
        event_type = EventType.Name(int(event.event_type))
        identity = ""
        attempt = 0
        activity_type = ""
        scheduled_event_id = 0
        started_event_id = 0
        last_failure_message = ""
        last_failure_source = ""
        last_failure_timeout_type = ""
        if event_type == "EVENT_TYPE_WORKFLOW_TASK_STARTED":
            identity = event.workflow_task_started_event_attributes.identity
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            attrs = event.activity_task_started_event_attributes
            identity = attrs.identity
            attempt = int(attrs.attempt or 0)
            scheduled_event_id = int(attrs.scheduled_event_id or 0)
            if attrs.HasField("last_failure"):
                failure = attrs.last_failure
                last_failure_message = str(failure.message or "")
                last_failure_source = str(failure.source or "")
                if failure.HasField("timeout_failure_info"):
                    last_failure_timeout_type = TimeoutType.Name(
                        int(failure.timeout_failure_info.timeout_type)
                    )
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
            attrs = event.activity_task_scheduled_event_attributes
            activity_type = attrs.activity_type.name
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT":
            attrs = event.activity_task_timed_out_event_attributes
            scheduled_event_id = int(attrs.scheduled_event_id or 0)
            started_event_id = int(attrs.started_event_id or 0)
            if attrs.HasField("failure"):
                failure = attrs.failure
                last_failure_message = str(failure.message or "")
                last_failure_source = str(failure.source or "")
                if failure.HasField("timeout_failure_info"):
                    last_failure_timeout_type = TimeoutType.Name(
                        int(failure.timeout_failure_info.timeout_type)
                    )
        rows.append(
            {
                "id": int(event.event_id),
                "type": event_type,
                "time": _timestamp_text(event.event_time),
                "identity": identity,
                "attempt": attempt,
                "activity_type": activity_type,
                "scheduled_event_id": scheduled_event_id,
                "started_event_id": started_event_id,
                "last_failure_message": last_failure_message,
                "last_failure_source": last_failure_source,
                "last_failure_timeout_type": last_failure_timeout_type,
            }
        )
    return rows


def _attempt_two_restart_lineage(
    rows: list[dict[str, Any]],
    *,
    post_started: datetime,
    worker_identity_fragment: str,
) -> list[dict[str, Any]]:
    """Bind the post-restart attempt-2 start to its scheduled activity and worker-loss timeout."""
    scheduled = {
        int(row["id"]): row
        for row in rows
        if row.get("type") == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    }
    lineage: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            continue
        if int(row.get("attempt") or 0) != 2:
            continue
        identity = str(row.get("identity") or "")
        if not worker_identity_fragment or worker_identity_fragment not in identity:
            continue
        started_at = str(row.get("time") or "")
        if not started_at or _parse_time(started_at) <= post_started:
            continue
        if row.get("last_failure_timeout_type") not in {
            "TIMEOUT_TYPE_HEARTBEAT",
            "TIMEOUT_TYPE_START_TO_CLOSE",
        }:
            continue
        scheduled_event_id = int(row.get("scheduled_event_id") or 0)
        scheduled_row = scheduled.get(scheduled_event_id)
        if scheduled_row is None:
            continue
        lineage.append(
            {
                "started_event_id": int(row["id"]),
                "scheduled_event_id": scheduled_event_id,
                "activity_type": str(scheduled_row.get("activity_type") or ""),
                "attempt": 2,
                "worker_identity": identity,
                "started_at": started_at,
                "last_failure_timeout_type": str(row["last_failure_timeout_type"]),
                "last_failure_message": str(row.get("last_failure_message") or ""),
            }
        )
    return lineage


def _activity_timeout_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report explicit timeout events and retry-start lastFailure timeouts."""
    return [
        row
        for row in rows
        if row.get("type") == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT"
        or bool(row.get("last_failure_timeout_type"))
    ]


async def _active_canonical_workflows(client: Client) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    async for execution in client.list_workflows('ExecutionStatus = "Running"'):
        if execution.status != WorkflowExecutionStatus.RUNNING:
            continue
        if execution.task_queue not in ALL_QUEUES:
            continue
        active.append(
            {
                "workflow_id": execution.id,
                "run_id": execution.run_id,
                "workflow_type": execution.workflow_type,
                "task_queue": execution.task_queue,
                "status": execution.status.name,
                "start_time": execution.start_time.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
    return sorted(active, key=lambda item: (item["workflow_id"], item["run_id"]))


def _blast_radius_gate(
    active: list[dict[str, Any]],
    *,
    expected_workflow: tuple[str, str] | None,
) -> bool:
    actual = {
        (str(item.get("workflow_id") or ""), str(item.get("run_id") or ""))
        for item in active
        if item.get("status") == "RUNNING"
    }
    expected = {expected_workflow} if expected_workflow is not None else set()
    return actual == expected


def _grok_sessions_root(container: dict[str, Any]) -> Path:
    for mount in container.get("mounts") or []:
        if str(mount.get("destination") or "").rstrip("/") == "/grok-home/.grok":
            return Path(str(mount.get("source") or "")) / "sessions"
    raise RuntimeError("canonical Docker worker has no mounted Grok session root")


def _operation_session_gate(workflow_id: str, sessions_root: Path) -> dict[str, Any]:
    operation_root = RUNTIME / "state" / "grok_docker_native" / workflow_id / "operations"
    for manifest_path in sorted(operation_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("state") != "running":
            continue
        session_id = str(manifest.get("requested_session_id") or "").strip()
        operation_id = str(manifest.get("operation_id") or "").strip()
        if not session_id or not operation_id:
            continue
        session_dirs = [
            path for path in sessions_root.glob(f"*/{session_id}") if path.is_dir()
        ]
        for session_dir in session_dirs:
            materialized = [
                name
                for name in ("prompt_context.json", "events.jsonl", "summary.json.lock")
                if (session_dir / name).is_file()
            ]
            if len(materialized) < 2:
                continue
            return {
                "ok": True,
                "operation_id": operation_id,
                "manifest_path": str(manifest_path),
                "manifest_sha256": _sha256(manifest_path),
                "operation_attempt": int(manifest.get("attempt") or 0),
                "session_id": session_id,
                "session_path": str(session_dir),
                "materialized_files": materialized,
            }
    return {
        "ok": False,
        "operation_root": str(operation_root),
        "sessions_root": str(sessions_root),
    }


async def _wait_running_activity(
    handle: Any,
    *,
    workflow_id: str,
    sessions_root: Path,
    timeout: float = 90.0,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        desc = await handle.describe()
        history = await handle.fetch_history()
        rows = _event_rows(history)
        operation_session_gate = _operation_session_gate(workflow_id, sessions_root)
        if desc.status == WorkflowExecutionStatus.RUNNING and any(
            row["type"] == "EVENT_TYPE_ACTIVITY_TASK_STARTED" for row in rows
        ) and operation_session_gate["ok"]:
            return {
                "run_id": desc.run_id,
                "status": desc.status.name,
                "max_event_id": max(row["id"] for row in rows),
                "history_event_count": len(rows),
                "event_types": [row["type"] for row in rows],
                "operation_session_gate": operation_session_gate,
            }
        if desc.status in TERMINAL:
            raise RuntimeError(f"workflow reached {desc.status.name} before restart gate")
        await asyncio.sleep(0.05)
    raise TimeoutError(
        "workflow did not materialize a running Grok operation/session before restart gate"
    )


async def _wait_daemon_and_queues(
    client: Client,
    *,
    previous_run_id: str,
    started_after: datetime,
    timeout: float = 90.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = asyncio.get_running_loop().time() + timeout
    last_daemon: dict[str, Any] = {}
    last_queues: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        last_daemon = _daemon_state()
        last_queues = await queue_snapshot(client)
        generated = str(last_daemon.get("generated_at") or "")
        daemon_fresh = bool(
            last_daemon.get("run_id")
            and last_daemon.get("run_id") != previous_run_id
            and generated
            and _parse_time(generated) > started_after
        )
        if daemon_fresh and _queues_ready(last_queues, after=started_after):
            return last_daemon, last_queues
        await asyncio.sleep(0.5)
    raise TimeoutError(
        "restarted worker did not publish a fresh daemon generation and all queue pollers"
    )


def _docker_restart(container_id: str) -> dict[str, Any]:
    began = _now()
    proc = _run(["docker", "restart", "--time", "10", container_id], timeout=30)
    return {
        "began_at_utc": began,
        "ended_at_utc": _now(),
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr_tail": proc.stderr[-1000:],
        "create_no_window": bool(WINDOWLESS) if os.name == "nt" else True,
    }


def _rollback_start_if_exact_stopped(
    *, pre: dict[str, Any], current: dict[str, Any] | None
) -> dict[str, Any]:
    if current is None:
        return {"attempted": False, "reason": "identity unavailable; ambiguity is read-only"}
    if _static_identity(current) != _static_identity(pre):
        return {"attempted": False, "reason": "identity drift; ambiguity is read-only"}
    if current.get("status") == "running":
        return {"attempted": False, "reason": "exact container already running"}
    proc = _run(["docker", "container", "start", str(pre["id"])], timeout=30)
    return {
        "attempted": True,
        "exact_container_id": pre["id"],
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr_tail": proc.stderr[-1000:],
        "create_no_window": bool(WINDOWLESS) if os.name == "nt" else True,
    }


def _host_path(raw: str) -> Path:
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/evidence/"):
        return RUNTIME / normalized[len("/evidence/") :]
    return Path(raw)


def _grok_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    raw_lanes = result.get("grok_lanes")
    if isinstance(raw_lanes, dict):
        lanes = [raw_lanes]
    elif isinstance(raw_lanes, list):
        lanes = [item for item in raw_lanes if isinstance(item, dict)]
    else:
        lanes = []
    successful = [item for item in lanes if item.get("ok") is True]
    return {
        "execution_location": str(result.get("grok_execution_location") or ""),
        "worker_lane_adapter": str(result.get("worker_lane_adapter") or ""),
        "requested_models": sorted(
            {str(item.get("requested_model") or "") for item in lanes if item}
        ),
        "observed_models": sorted(
            {str(item.get("observed_model") or "") for item in successful if item}
        ),
        "lane_count": len(lanes),
        "successful_lanes": len(successful),
        "total_tokens": int(result.get("grok_total_tokens") or 0),
    }


def _real_result_accepted(result: dict[str, Any]) -> bool:
    base_ok = all(
        result.get(name) is True
        for name in (
            "validate_ok",
            "planner_ok",
            "fanin_ok",
            "checkpoint_ok",
            "promotion_gate_passed",
            "pytest_slice_ok",
        )
    )
    legacy_send_ok = result.get("langgraph_send_wired") is True
    grok = _grok_result_summary(result)
    docker_native_ok = bool(
        result.get("worker_lane_ok") is True
        and result.get("grok_fanin_ok") is True
        and grok["execution_location"] == "docker:houtai-gongren"
        and grok["worker_lane_adapter"] == "grok_build_cli_docker_native"
        and grok["requested_models"] == [COMPOSER_MODEL]
        and grok["observed_models"] == [COMPOSER_MODEL]
        and grok["lane_count"] > 0
        and grok["successful_lanes"] == grok["lane_count"]
        and grok["total_tokens"] > 0
    )
    return base_ok and (legacy_send_ok or docker_native_ok)


async def fresh_verify(preliminary: Path) -> dict[str, Any]:
    pre = json.loads(preliminary.read_text(encoding="utf-8"))
    workflow_id = str(pre["workflow_id"])
    expected_run_id = str(pre["run_id"])
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    handle = client.get_workflow_handle(workflow_id, run_id=expected_run_id)
    desc = await handle.describe()
    history = await handle.fetch_history()
    rows = _event_rows(history)
    result = await handle.result()
    result = result if isinstance(result, dict) else {}
    current_container = docker_identity(str(pre["container_pre"]["id"]))
    queues = await queue_snapshot(client)
    active_after = await _active_canonical_workflows(client)
    daemon = _daemon_state()
    post_started = _parse_time(str(pre["container_post"]["started_at"]))
    worker_identity_fragment = str(pre["container_post"]["id"][:12])
    post_worker_events = [
        row
        for row in rows
        if row["type"] in {"EVENT_TYPE_WORKFLOW_TASK_STARTED", "EVENT_TYPE_ACTIVITY_TASK_STARTED"}
        and row["time"]
        and _parse_time(row["time"]) > post_started
        and worker_identity_fragment in str(row["identity"])
    ]
    attempt_two_lineage = _attempt_two_restart_lineage(
        rows,
        post_started=post_started,
        worker_identity_fragment=worker_identity_fragment,
    )
    activity_timeouts = _activity_timeout_rows(rows)
    event_types = [row["type"] for row in rows]
    activity_types = [row["activity_type"] for row in rows if row["activity_type"]]
    proof_raw = str(result.get("proof_path") or "")
    proof_path = _host_path(proof_raw) if proof_raw else RUNTIME / "missing-proof"
    grok_summary = _grok_result_summary(result)
    checks = {
        "same_workflow_id": desc.id == workflow_id,
        "same_run_id": desc.run_id == expected_run_id,
        "completed": desc.status == WorkflowExecutionStatus.COMPLETED,
        "history_advanced_after_restart": max(row["id"] for row in rows)
        > int(pre["pre_history_max_event_id"]),
        "post_restart_worker_event_attributed": bool(post_worker_events),
        "attempt_2_restart_lineage": bool(attempt_two_lineage),
        "worker_loss_timeout_reported": any(
            row.get("last_failure_timeout_type")
            in {"TIMEOUT_TYPE_HEARTBEAT", "TIMEOUT_TYPE_START_TO_CLOSE"}
            for row in activity_timeouts
        ),
        "workflow_execution_completed_event": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"
        in event_types,
        "no_workflow_task_failed": "EVENT_TYPE_WORKFLOW_TASK_FAILED" not in event_types,
        "no_workflow_execution_failed": "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED" not in event_types,
        "container_static_identity_unchanged": _static_identity(current_container)
        == _static_identity(pre["container_pre"]),
        "container_generation_changed": (
            current_container["pid"] != pre["container_pre"]["pid"]
            and current_container["started_at"] != pre["container_pre"]["started_at"]
        ),
        "container_running_healthy": current_container["status"] == "running"
        and current_container["health"] == "healthy",
        "daemon_generation_fresh": daemon.get("run_id") == pre["daemon_post"].get("run_id")
        and _parse_time(str(daemon.get("generated_at"))) > post_started,
        "all_queue_pollers_fresh": _queues_ready(queues, after=post_started),
        "all_queue_backlogs_zero": all(
            int(queues[q][kind]["backlog"]) == 0
            for q in ALL_QUEUES
            for kind in ("workflow", "activity")
        ),
        "real_result_acceptance": _real_result_accepted(result),
        "d_disk_proof_exists": proof_path.is_file(),
        "no_host_grok_activity_scheduled": not any(
            name.startswith("xinao.grok.") for name in activity_types
        ),
        "blast_radius_baseline_clear": bool((pre.get("blast_radius_before") or {}).get("ok")),
        "blast_radius_restart_gate_exact": bool(
            (pre.get("blast_radius_restart_gate") or {}).get("ok")
        ),
        "canary_not_active_after_completion": not any(
            item["workflow_id"] == workflow_id and item["run_id"] == expected_run_id
            for item in active_after
        ),
    }
    history_path = preliminary.parent / "workflow_history.json"
    _write_json(history_path, history.to_json_dict())
    return {
        "schema_version": "xinao.houtai_restart_resume.fresh_verify.v1",
        "generated_at_utc": _now(),
        "ok": all(checks.values()),
        "checks": checks,
        "workflow": {
            "workflow_id": workflow_id,
            "run_id": desc.run_id,
            "status": desc.status.name,
            "history_event_count": len(rows),
            "max_event_id": max(row["id"] for row in rows),
            "post_restart_worker_events": post_worker_events,
            "attempt_2_restart_lineage": attempt_two_lineage,
            "activity_timeouts": activity_timeouts,
            "active_canonical_after": active_after,
        },
        "result_acceptance": {
            key: result.get(key)
            for key in (
                "validate_ok",
                "planner_ok",
                "fanin_ok",
                "checkpoint_ok",
                "langgraph_send_wired",
                "promotion_gate_passed",
                "pytest_slice_ok",
                "proof_path",
                "fanin_evidence_ref",
                "worker_lane_provider",
                "worker_lane_model",
            )
        },
        "grok": grok_summary,
        "history": {"path": str(history_path), "sha256": _sha256(history_path)},
        "proof": {
            "path": str(proof_path),
            "sha256": _sha256(proof_path) if proof_path.is_file() else None,
        },
        "container": current_container,
        "daemon": daemon,
        "queues": queues,
    }


def _spawn_fresh_verify(preliminary: Path) -> dict[str, Any]:
    proc = _run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--fresh-verify",
            str(preliminary),
        ],
        timeout=120,
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


async def run_canary(run_dir: Path) -> dict[str, Any]:
    global _ACTIVE_CONTAINER_PRE, _ACTIVE_WORKFLOW_ID, _ACTIVE_WORKFLOW_RUN_ID
    _ACTIVE_WORKFLOW_ID = ""
    _ACTIVE_WORKFLOW_RUN_ID = ""
    _ACTIVE_CONTAINER_PRE = None
    run_id = f"restart-resume-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    evidence_dir = run_dir / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    workflow_id = f"xinao-restart-canary-{uuid.uuid4().hex}"
    canary_input = evidence_dir / "canary_input.md"
    canary_input.write_text(
        "# Docker worker restart/recovery canary\n\n"
        "Audit this bounded local fixture and return one concise recovery finding.\n",
        encoding="utf-8",
    )
    container_pre = docker_identity()
    _ACTIVE_CONTAINER_PRE = container_pre
    mount_pre = await asyncio.to_thread(
        actual_mount_report,
        REPO,
        container=str(container_pre["id"]),
    )
    mount_pre_path = evidence_dir / "mount_preflight_before.json"
    _write_json(mount_pre_path, mount_pre)
    if mount_pre.get("ok") is not True:
        return {
            "schema_version": "xinao.houtai_restart_resume.v1",
            "generated_at_utc": _now(),
            "ok": False,
            "error_type": "WorkerRepoMountMismatch",
            "named_blocker": "WORKER_REPO_MOUNT_MISMATCH",
            "temporal_connected": False,
            "workflow_started": False,
            "restart_attempted": False,
            "mount_preflight": {
                "path": str(mount_pre_path),
                "sha256": _sha256(mount_pre_path),
                "report": mount_pre,
            },
        }
    canary_input_container = "/evidence/" + canary_input.relative_to(RUNTIME).as_posix()
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    daemon_pre = _daemon_state()
    queues_pre = await queue_snapshot(client)
    active_before = await _active_canonical_workflows(client)
    blast_radius_before = {
        "ok": _blast_radius_gate(active_before, expected_workflow=None),
        "expected": [],
        "active": active_before,
    }
    baseline_ok = bool(
        container_pre["status"] == "running"
        and container_pre["health"] == "healthy"
        and container_pre["compose_service"] == CONTAINER_NAME
        and Path(container_pre["compose_file"]).resolve() == (REPO / "docker-compose.yml").resolve()
        and mount_pre.get("ok") is True
        and _queues_ready(queues_pre)
        and daemon_pre.get("status") == "polling"
        and blast_radius_before["ok"]
    )
    plan = {
        "schema_version": "xinao.houtai_restart_resume.plan.v1",
        "created_at_utc": _now(),
        "baseline_ok": baseline_ok,
        "candidate": {
            "effect": "restart the exact canonical Docker worker once",
            "container": container_pre,
            "workflow_id": workflow_id,
            "workflow_type": WORKFLOW_TYPE,
            "task_queue": WORKFLOW_QUEUE,
            "input_path": str(canary_input),
            "input_sha256": _sha256(canary_input),
        },
        "control": {
            "container_running_healthy": True,
            "worker_repo_mount": mount_pre,
            "daemon": daemon_pre,
            "queues": queues_pre,
            "blast_radius": blast_radius_before,
        },
        "bounded_episode": {
            "max_seconds": 720,
            "max_workflows": 1,
            "max_restarts": 1,
            "max_rollback_starts": 1,
            "exit_condition": "same workflow/run completes with post-restart worker evidence",
        },
        "success_thresholds": [
            "same workflow_id and run_id",
            "no other active workflow on any canonical worker queue at baseline/restart gate",
            "post-restart attempt 2 links to the scheduled activity and worker-loss timeout",
            "Grok operation manifest and session files materialized before restart",
            "new container PID and StartedAt with unchanged static identity",
            "fresh daemon generation and all six workflow/activity poller surfaces",
            "Temporal completion, post-restart attributed event, D-disk proof hash",
        ],
        "abort_thresholds": [
            "any unrelated active workflow on a canonical worker queue",
            "identity drift before restart",
            "workflow no longer RUNNING before restart",
            "container missing or ambiguous",
            "observation window exceeded",
        ],
        "rollback": {
            "condition": "exact container stopped after failed restart",
            "action": "docker container start <captured full id> once",
            "forbidden": ["compose up/recreate", "second restart", "guess another object"],
        },
        "negative_checks": {
            "grok_admin_invocations_allowed": 0,
            "visible_window_focus_input_allowed": False,
            "scheduler_timer_daemon_created": False,
        },
    }
    plan_path = evidence_dir / "plan.json"
    _write_json(plan_path, plan)
    if not baseline_ok:
        return {
            "schema_version": "xinao.houtai_restart_resume.v1",
            "generated_at_utc": _now(),
            "ok": False,
            "error_type": "BaselineNotReady",
            "blast_radius": blast_radius_before,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
        }

    initial = {
        "input_path": canary_input_container,
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
    handle = await client.start_workflow(
        WORKFLOW_TYPE,
        initial,
        id=workflow_id,
        task_queue=WORKFLOW_QUEUE,
    )
    _ACTIVE_WORKFLOW_ID = workflow_id
    _ACTIVE_WORKFLOW_RUN_ID = str(handle.run_id or handle.result_run_id or "")
    pre_history = await _wait_running_activity(
        handle,
        workflow_id=workflow_id,
        sessions_root=_grok_sessions_root(container_pre),
    )
    _ACTIVE_WORKFLOW_RUN_ID = str(pre_history["run_id"])
    container_gate = docker_identity(container_pre["id"])
    mount_gate = await asyncio.to_thread(
        actual_mount_report,
        REPO,
        container=str(container_pre["id"]),
    )
    desc_gate = await handle.describe()
    active_at_restart_gate = await _active_canonical_workflows(client)
    blast_radius_restart_gate = {
        "ok": _blast_radius_gate(
            active_at_restart_gate,
            expected_workflow=(workflow_id, str(pre_history["run_id"])),
        ),
        "expected": [{"workflow_id": workflow_id, "run_id": str(pre_history["run_id"])}],
        "active": active_at_restart_gate,
    }
    gate_ok = bool(
        _static_identity(container_gate) == _static_identity(container_pre)
        and container_gate["pid"] == container_pre["pid"]
        and container_gate["started_at"] == container_pre["started_at"]
        and desc_gate.status == WorkflowExecutionStatus.RUNNING
        and desc_gate.run_id == pre_history["run_id"]
        and bool((pre_history.get("operation_session_gate") or {}).get("ok"))
        and blast_radius_restart_gate["ok"]
        and mount_gate.get("ok") is True
    )
    gate_path = evidence_dir / "restart_gate.json"
    _write_json(
        gate_path,
        {
            "generated_at_utc": _now(),
            "ok": gate_ok,
            "container": container_gate,
            "worker_repo_mount": mount_gate,
            "workflow": pre_history,
            "blast_radius": blast_radius_restart_gate,
        },
    )
    if not gate_ok:
        cleanup = await _cancel_handle_to_terminal(handle)
        _ACTIVE_WORKFLOW_ID = ""
        _ACTIVE_WORKFLOW_RUN_ID = ""
        return {
            "schema_version": "xinao.houtai_restart_resume.v1",
            "generated_at_utc": _now(),
            "ok": False,
            "error_type": "RestartGateRejected",
            "cleanup": cleanup,
            "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
            "gate": {"path": str(gate_path), "sha256": _sha256(gate_path)},
        }

    restart = await asyncio.to_thread(_docker_restart, str(container_pre["id"]))
    rollback: dict[str, Any] = {"attempted": False, "reason": "not needed"}
    container_post: dict[str, Any] | None = None
    try:
        container_post = docker_identity(str(container_pre["id"]))
    except Exception:
        container_post = None
    if restart["exit_code"] != 0 or not container_post or container_post["status"] != "running":
        rollback_outcome = _rollback_start_if_exact_stopped(
            pre=container_pre, current=container_post
        )
        raise RuntimeError(
            "exact Docker restart failed; bounded rollback evaluated: "
            + json.dumps(rollback_outcome, ensure_ascii=True, sort_keys=True)
        )
    post_started = _parse_time(str(container_post["started_at"]))
    mount_post = await asyncio.to_thread(
        actual_mount_report,
        REPO,
        container=str(container_pre["id"]),
    )
    if mount_post.get("ok") is not True:
        cleanup = await _cancel_handle_to_terminal(handle)
        _ACTIVE_WORKFLOW_ID = ""
        _ACTIVE_WORKFLOW_RUN_ID = ""
        return {
            "schema_version": "xinao.houtai_restart_resume.v1",
            "generated_at_utc": _now(),
            "ok": False,
            "error_type": "WorkerRepoMountMismatchAfterRestart",
            "named_blocker": "WORKER_REPO_MOUNT_MISMATCH",
            "restart_attempted": True,
            "cleanup": cleanup,
            "mount_preflight_before": mount_pre,
            "mount_preflight_restart_gate": mount_gate,
            "mount_preflight_after": mount_post,
        }
    daemon_post, queues_post = await _wait_daemon_and_queues(
        client,
        previous_run_id=str(daemon_pre.get("run_id") or ""),
        started_after=post_started,
    )
    workflow_result = await asyncio.wait_for(handle.result(), timeout=720)
    desc_post = await handle.describe()
    preliminary = {
        "schema_version": "xinao.houtai_restart_resume.preliminary.v1",
        "generated_at_utc": _now(),
        "workflow_id": workflow_id,
        "run_id": pre_history["run_id"],
        "pre_history_max_event_id": pre_history["max_event_id"],
        "container_pre": container_pre,
        "container_post": container_post,
        "daemon_pre": daemon_pre,
        "daemon_post": daemon_post,
        "queues_pre": queues_pre,
        "queues_post": queues_post,
        "blast_radius_before": blast_radius_before,
        "blast_radius_restart_gate": blast_radius_restart_gate,
        "restart": restart,
        "mount_preflight_before": mount_pre,
        "mount_preflight_restart_gate": mount_gate,
        "mount_preflight_after": mount_post,
        "rollback": rollback,
        "workflow_status_after": desc_post.status.name,
        "result_is_dict": isinstance(workflow_result, dict),
    }
    preliminary_path = evidence_dir / "preliminary.json"
    _write_json(preliminary_path, preliminary)
    fresh = _spawn_fresh_verify(preliminary_path)
    fresh_payload = fresh.get("payload") if isinstance(fresh.get("payload"), dict) else {}
    checks = {
        "restart_command_succeeded": restart["exit_code"] == 0,
        "static_identity_unchanged": _static_identity(container_post)
        == _static_identity(container_pre),
        "container_generation_changed": container_post["pid"] != container_pre["pid"]
        and container_post["started_at"] != container_pre["started_at"],
        "same_workflow_run_completed": desc_post.status == WorkflowExecutionStatus.COMPLETED
        and desc_post.run_id == pre_history["run_id"],
        "fresh_process_verified": fresh["exit_code"] == 0 and fresh_payload.get("ok") is True,
        "no_rollback_needed": rollback.get("attempted") is False,
        "blast_radius_baseline_clear": blast_radius_before["ok"] is True,
        "blast_radius_restart_gate_exact": blast_radius_restart_gate["ok"] is True,
        "worker_repo_mount_before_exact": mount_pre.get("ok") is True,
        "worker_repo_mount_restart_gate_exact": mount_gate.get("ok") is True,
        "worker_repo_mount_after_exact": mount_post.get("ok") is True,
    }
    payload = {
        "schema_version": "xinao.houtai_restart_resume.v1",
        "generated_at_utc": _now(),
        "ok": all(checks.values()),
        "checks": checks,
        "workflow": {
            "workflow_id": workflow_id,
            "run_id": pre_history["run_id"],
            "status_before": pre_history["status"],
            "status_after": desc_post.status.name,
            "pre_history_max_event_id": pre_history["max_event_id"],
        },
        "container_pre": container_pre,
        "container_post": container_post,
        "restart": restart,
        "mount_preflight_before": mount_pre,
        "mount_preflight_restart_gate": mount_gate,
        "mount_preflight_after": mount_post,
        "rollback": rollback,
        "daemon_pre": daemon_pre,
        "daemon_post": daemon_post,
        "fresh_process": fresh,
        "plan": {"path": str(plan_path), "sha256": _sha256(plan_path)},
        "gate": {"path": str(gate_path), "sha256": _sha256(gate_path)},
        "preliminary": {
            "path": str(preliminary_path),
            "sha256": _sha256(preliminary_path),
        },
        "side_effects": {
            "grok_invocations": int(
                ((fresh_payload.get("grok") or {}).get("successful_lanes") or 0)
            ),
            "grok_model": COMPOSER_MODEL,
            "grok_total_tokens": int(
                ((fresh_payload.get("grok") or {}).get("total_tokens") or 0)
            ),
            "admin_invocations": 0,
            "visible_window": False,
            "focus_or_input": False,
            "timer_scheduler_daemon_created": False,
            "persistent_helper_after_exit": False,
        },
    }
    _ACTIVE_WORKFLOW_ID = ""
    _ACTIVE_WORKFLOW_RUN_ID = ""
    return payload


async def _cancel_handle_to_terminal(handle: Any) -> dict[str, Any]:
    desc = await handle.describe()
    status_before = desc.status.name
    cancel_requested = False
    if desc.status == WorkflowExecutionStatus.RUNNING:
        await handle.cancel()
        cancel_requested = True
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            desc = await handle.describe()
            if desc.status in TERMINAL:
                break
            await asyncio.sleep(0.1)
    return {
        "status_before": status_before,
        "cancel_requested": cancel_requested,
        "status_after": desc.status.name,
        "terminal_confirmed": desc.status in TERMINAL,
    }


async def _cancel_exact_running(workflow_id: str, run_id: str) -> dict[str, Any]:
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    result = await _cancel_handle_to_terminal(handle)
    return {"workflow_id": workflow_id, "run_id": run_id, **result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--output", default=str(DEFAULT_LATEST))
    parser.add_argument("--fresh-verify")
    args = parser.parse_args()
    if args.fresh_verify:
        payload = asyncio.run(fresh_verify(Path(args.fresh_verify)))
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["ok"] else 1
    output = Path(args.output)
    try:
        payload = asyncio.run(run_canary(Path(args.run_dir)))
    except Exception as exc:
        cleanup: dict[str, Any] = {"attempted": False, "reason": "no active canary"}
        if _ACTIVE_WORKFLOW_ID:
            if not _ACTIVE_WORKFLOW_RUN_ID:
                cleanup = {
                    "attempted": False,
                    "workflow_id": _ACTIVE_WORKFLOW_ID,
                    "reason": "exact run id unavailable; ambiguous cleanup refused",
                }
            else:
                try:
                    cancellation = asyncio.run(
                        _cancel_exact_running(_ACTIVE_WORKFLOW_ID, _ACTIVE_WORKFLOW_RUN_ID)
                    )
                    cleanup = {"attempted": True, **cancellation}
                except Exception as cleanup_exc:
                    cleanup = {
                        "attempted": True,
                        "workflow_id": _ACTIVE_WORKFLOW_ID,
                        "run_id": _ACTIVE_WORKFLOW_RUN_ID,
                        "error_type": type(cleanup_exc).__name__,
                        "message": str(cleanup_exc)[:500],
                    }
        rollback: dict[str, Any] = {"attempted": False, "reason": "no captured container"}
        if _ACTIVE_CONTAINER_PRE is not None:
            current: dict[str, Any] | None
            try:
                current = docker_identity(str(_ACTIVE_CONTAINER_PRE["id"]))
            except Exception:
                current = None
            rollback = _rollback_start_if_exact_stopped(
                pre=_ACTIVE_CONTAINER_PRE,
                current=current,
            )
        payload = {
            "schema_version": "xinao.houtai_restart_resume.v1",
            "generated_at_utc": _now(),
            "ok": False,
            "error_type": type(exc).__name__,
            "message": str(exc)[:1000],
            "cleanup": cleanup,
            "rollback": rollback,
        }
    _write_json(output, payload)
    print(
        json.dumps(
            {
                "ok": payload.get("ok"),
                "output": str(output),
                "workflow": (payload.get("workflow") or {}).get("workflow_id"),
                "error_type": payload.get("error_type"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
