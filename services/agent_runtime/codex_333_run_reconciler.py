from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "xinao.codex_s.333_run_reconciler.v1"
CURRENT_INDEX_SCHEMA_VERSION = f"{SCHEMA_VERSION}.current_run_index.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_RUN_RECONCILER_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "codex_333_run_reconciler_20260706"
STATE_NAME = "codex_333_run_reconciler"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TEMPORAL_ADDRESS = "127.0.0.1:7233"
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
DEFAULT_WORKFLOW_TYPE = "TemporalCodexTaskWorkflow"

MAINLINE_PREFIXES = ("codex-s-333-", "codex-s-backend-control-plane-", "333-")
TEMPORARY_MARKERS = (
    "_temporal_tmp",
    "temporal_tmp",
    "tmp",
    "verify",
    "smoke",
    "probe",
    "test",
    "light-research",
)

CommandRunner = Callable[[list[str], int], dict[str, Any]]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return cleaned[:120] or "unbound"


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def replace_path_with_retry(tmp: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(25):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def output_paths(runtime: Path, *, record_id: str = "latest") -> dict[str, Path]:
    state = runtime / "state" / STATE_NAME
    current_index = runtime / "state" / "current_333_run_index"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{safe_stem(record_id)}.json",
        "readback": runtime / "readback" / "zh" / f"{STATE_NAME}.md",
        "current_index_latest": current_index / "latest.json",
        "current_index_record": current_index / "records" / f"{safe_stem(record_id)}.json",
        "tool_registry": runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.333_run_reconciler"
        / "manifest.json",
    }


def default_command_runner(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }


def tcp_port_open(address: str, timeout_seconds: float = 1.5) -> bool:
    host, _, port_text = address.partition(":")
    try:
        with socket.create_connection((host, int(port_text)), timeout=timeout_seconds):
            return True
    except (OSError, ValueError):
        return False


def find_temporal_worker_processes(task_queue: str) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    ps_script = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*temporal_codex_task_workflow*' "
        "-and $_.CommandLine -like '*--worker*' "
        f"-and $_.CommandLine -like '*{task_queue}*' }} | "
        "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Depth 4"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    processes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        command_line = str(item.get("CommandLine") or "")
        if "temporal_codex_task_workflow" not in command_line or task_queue not in command_line:
            continue
        processes.append(
            {
                "pid": item.get("ProcessId"),
                "parent_pid": item.get("ParentProcessId"),
                "executable_path": item.get("ExecutablePath"),
                "command_line": command_line,
                "launched_from_s_venv": str(DEFAULT_REPO / ".venv" / "Scripts" / "python.exe")
                in command_line,
            }
        )
    return processes


def normalize_workflow(raw: dict[str, Any]) -> dict[str, Any]:
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    root_execution = raw.get("rootExecution") if isinstance(raw.get("rootExecution"), dict) else {}
    workflow_type = raw.get("type") if isinstance(raw.get("type"), dict) else {}
    return {
        "workflow_id": str(
            execution.get("workflowId")
            or execution.get("workflow_id")
            or raw.get("workflow_id")
            or raw.get("workflowId")
            or ""
        ),
        "run_id": str(
            execution.get("runId")
            or execution.get("run_id")
            or raw.get("run_id")
            or raw.get("runId")
            or ""
        ),
        "root_workflow_id": str(root_execution.get("workflowId") or root_execution.get("workflow_id") or ""),
        "root_run_id": str(root_execution.get("runId") or root_execution.get("run_id") or ""),
        "workflow_type": str(workflow_type.get("name") or raw.get("workflow_type") or raw.get("type") or ""),
        "status": str(raw.get("status") or ""),
        "task_queue": str(raw.get("taskQueue") or raw.get("task_queue") or ""),
        "start_time": str(raw.get("startTime") or raw.get("start_time") or ""),
        "execution_time": str(raw.get("executionTime") or raw.get("execution_time") or ""),
    }


def parse_temporal_workflow_list_json(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        for key in ("executions", "workflowExecutions", "items"):
            items = payload.get(key)
            if isinstance(items, list):
                return [normalize_workflow(item) for item in items if isinstance(item, dict)]
        return [normalize_workflow(payload)]
    if isinstance(payload, list):
        return [normalize_workflow(item) for item in payload if isinstance(item, dict)]
    return []


def list_running_workflows(
    *,
    temporal_address: str,
    command_runner: CommandRunner | None = None,
    override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if override is not None:
        return {
            "status": "workflow_list_ready",
            "source": "override",
            "returncode": 0,
            "workflows": [normalize_workflow(item) for item in override],
            "error": "",
            "command": [],
        }
    runner = command_runner or default_command_runner
    command = [
        "temporal",
        "workflow",
        "list",
        "--address",
        temporal_address,
        "--query",
        "ExecutionStatus='Running'",
        "--output",
        "json",
    ]
    result = runner(command, 20)
    workflows: list[dict[str, Any]] = []
    error = str(result.get("stderr") or "")
    if int(result.get("returncode") or 0) == 0:
        try:
            workflows = parse_temporal_workflow_list_json(str(result.get("stdout") or ""))
        except (json.JSONDecodeError, TypeError) as exc:
            error = str(exc)
    return {
        "status": "workflow_list_ready" if workflows else "workflow_list_empty_or_unavailable",
        "source": "temporal_cli",
        "returncode": int(result.get("returncode") or 0),
        "workflows": workflows,
        "error": error,
        "command": command,
        "timed_out": result.get("timed_out") is True,
    }


def workflow_role(
    workflow: dict[str, Any],
    *,
    task_queue: str,
    workflow_type: str,
    mainline_prefixes: tuple[str, ...] = MAINLINE_PREFIXES,
) -> dict[str, Any]:
    workflow_id = str(workflow.get("workflow_id") or "")
    workflow_id_lower = workflow_id.lower()
    status = str(workflow.get("status") or "")
    same_queue = str(workflow.get("task_queue") or "") == task_queue
    same_type = str(workflow.get("workflow_type") or "") == workflow_type
    running = "RUNNING" in status.upper() or status.lower() == "running"
    temporary = any(marker in workflow_id_lower for marker in TEMPORARY_MARKERS)
    stable_mainline_prefix = any(workflow_id.startswith(prefix) for prefix in mainline_prefixes)
    if not running:
        role = "closed_or_unknown"
        eligible = False
    elif not same_queue or not same_type:
        role = "foreign_running_workflow"
        eligible = False
    elif temporary:
        role = "temporary_probe_or_ad_hoc"
        eligible = False
    elif stable_mainline_prefix:
        role = "mainline_candidate"
        eligible = True
    else:
        role = "unclassified_running_workflow"
        eligible = False
    return {
        **workflow,
        "role": role,
        "eligible_mainline": eligible,
        "same_task_queue": same_queue,
        "same_workflow_type": same_type,
        "temporary_or_probe": temporary,
        "stable_mainline_prefix": stable_mainline_prefix,
    }


def read_worker_status(runtime: Path, *, temporal_address: str, task_queue: str) -> dict[str, Any]:
    status_path = runtime / "state" / "temporal_codex_task_worker" / "status.json"
    latest_path = runtime / "state" / "temporal_codex_task_worker" / "latest.json"
    status = read_json(status_path)
    latest = read_json(latest_path)
    source = status if status else latest
    live_processes = find_temporal_worker_processes(task_queue)
    live_pids = {int(proc["pid"]) for proc in live_processes if str(proc.get("pid") or "").isdigit()}
    process_alive = source.get("process_alive")
    if process_alive is None:
        process_alive = bool(source.get("pid"))
    pid = source.get("pid")
    if live_processes:
        process_alive = True
        if not str(pid or "").isdigit() or int(pid) not in live_pids:
            selected = next(
                (
                    proc
                    for proc in live_processes
                    if proc.get("launched_from_s_venv") is True
                ),
                live_processes[0],
            )
            pid = selected.get("pid")
    return {
        "status_path": str(status_path),
        "latest_path": str(latest_path),
        "status_exists": status_path.is_file(),
        "latest_exists": latest_path.is_file(),
        "status": str(source.get("status") or ""),
        "pid": pid,
        "process_alive": bool(process_alive),
        "task_queue": str(source.get("task_queue") or ""),
        "temporal_address": str(source.get("temporal_address") or temporal_address),
        "pollers_seen": source.get("pollers_seen"),
        "detected_worker_process_count": len(live_processes),
        "detected_worker_pids": sorted(live_pids),
        "detected_worker_processes": live_processes,
        "matches_task_queue": str(source.get("task_queue") or "") in {"", task_queue},
    }


def build_control_plane_liveness(
    *,
    port_open: bool,
    worker_status: dict[str, Any],
    list_status: dict[str, Any],
    classified_workflows: list[dict[str, Any]],
    mainline_candidates: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    blocker: str,
) -> dict[str, Any]:
    workflow_list_readable = (
        int(list_status.get("returncode") or 0) == 0
        or list_status.get("source") == "override"
    )
    worker_polling = (
        worker_status.get("status") == "polling"
        or int(worker_status.get("pollers_seen") or 0) > 0
    )
    process_alive = worker_status.get("process_alive") is True
    selected_bound = bool(selected and selected.get("workflow_id") and selected.get("run_id"))
    status = (
        "control_plane_liveness_ready"
        if port_open and workflow_list_readable and (worker_polling or process_alive)
        else "control_plane_liveness_degraded"
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.control_plane_liveness.v1",
        "status": status,
        "mode": "pure_liveness_read_model",
        "role": "heartbeat_liveness_only_not_brain_not_worker_dispatch",
        "temporal_server_port_open": port_open,
        "workflow_list_readable": workflow_list_readable,
        "running_workflow_count": len(classified_workflows),
        "mainline_candidate_count": len(mainline_candidates),
        "selected_workflow_bound": selected_bound,
        "named_blocker": blocker,
        "worker_status": {
            "status": worker_status.get("status", ""),
            "pid": worker_status.get("pid"),
            "process_alive": process_alive,
            "pollers_seen": worker_status.get("pollers_seen"),
            "matches_task_queue": worker_status.get("matches_task_queue") is True,
        },
        "no_model_invocation": True,
        "model_invocation_performed": False,
        "no_provider_worker_dispatch": True,
        "no_codex_or_v4pro_supervisor_call": True,
        "no_temporal_write_performed": True,
        "no_signal_sent": True,
        "no_worker_started_or_stopped": True,
        "result_wait_readback_role": "foreground_watch_may_read_this_snapshot_but_it_is_not_completion",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": status == "control_plane_liveness_ready",
            "checks": {
                "temporal_server_port_open": port_open,
                "workflow_list_readable": workflow_list_readable,
                "worker_seen_alive_or_polling": worker_polling or process_alive,
                "model_invocation_not_performed": True,
                "worker_dispatch_not_performed": True,
                "signal_not_sent": True,
                "completion_claim_blocked": True,
            },
        },
        "generated_at": now_iso(),
    }


def build_current_index(
    *,
    selected: dict[str, Any] | None,
    blocker: str,
    candidates: list[dict[str, Any]],
    all_running: list[dict[str, Any]],
    temporal_address: str,
    task_queue: str,
    worker_status: dict[str, Any],
    previous_index: dict[str, Any],
    control_plane_liveness: dict[str, Any],
) -> dict[str, Any]:
    selected = selected or {}
    workflow_id = str(selected.get("workflow_id") or "")
    run_id = str(selected.get("run_id") or "")
    reconciled = bool(workflow_id and run_id and not blocker)
    return {
        "schema_version": CURRENT_INDEX_SCHEMA_VERSION,
        "reconciler_schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": WORK_ID,
        "status": "current_333_run_index_ready" if reconciled else "current_333_run_index_blocked",
        "selection_source": "codex_s.333_run_reconciler",
        "workflow_id": workflow_id,
        "workflow_run_id": run_id,
        "current_state": "running" if reconciled else "blocked",
        "temporal": {
            "address": temporal_address,
            "task_queue": task_queue,
            "workflow_type": DEFAULT_WORKFLOW_TYPE,
            "server_bound_visibility_list": True,
            "selected_workflow": selected,
            "running_workflow_count": len(all_running),
            "mainline_candidate_count": len(candidates),
        },
        "worker_status": worker_status,
        "control_plane_liveness": control_plane_liveness,
        "running_workflows": all_running,
        "mainline_candidates": candidates,
        "previous_current_index": {
            "status": previous_index.get("status", ""),
            "workflow_id": previous_index.get("workflow_id", ""),
            "workflow_run_id": previous_index.get("workflow_run_id", ""),
            "schema_version": previous_index.get("schema_version", ""),
        },
        "latest_completed_wave_id": "",
        "next_wave_id": "",
        "reconciliation": {
            "reconciled": reconciled,
            "named_blocker": blocker,
            "selection_policy": "exactly_one_running_mainline_candidate_else_named_blocker",
            "ambiguous_candidates_require_user_or_controller_decision": blocker
            == "AMBIGUOUS_ACTIVE_333_MAINLINE",
            "no_temporal_write_performed": True,
            "no_signal_sent": True,
            "no_worker_started_or_stopped": True,
        },
        "admission_policy": {
            "stable_mainline_workflow_id_required": True,
            "workflow_id_conflict_policy_recommendation": "UseExisting_or_Fail_for_default_mainline",
            "terminate_existing_allowed_only_for_explicit_replace": True,
            "temporary_workflows_not_current_mainline": True,
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def choose_current_mainline(
    classified: list[dict[str, Any]],
    *,
    port_open: bool,
    worker_status: dict[str, Any],
    list_status: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    if not port_open:
        return None, "TEMPORAL_SERVER_NOT_RUNNING"
    if int(list_status.get("returncode") or 0) != 0 and list_status.get("source") != "override":
        return None, "TEMPORAL_WORKFLOW_LIST_UNAVAILABLE"
    worker_alive_or_polling = (
        worker_status.get("process_alive") is True
        or int(worker_status.get("pollers_seen") or 0) > 0
        or worker_status.get("status") == "polling"
    )
    if not worker_alive_or_polling:
        return None, "TEMPORAL_WORKER_NOT_POLLING"
    candidates = [item for item in classified if item.get("eligible_mainline") is True]
    if len(candidates) == 1:
        return candidates[0], ""
    if not candidates:
        return None, "NO_ACTIVE_333_MAINLINE"
    return None, "AMBIGUOUS_ACTIVE_333_MAINLINE"


def capability_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
        "provider_id": "codex_s.333_run_reconciler",
        "capability_kinds": [
            "temporal_run_visibility_reconcile",
            "current_333_run_index_writer",
            "mainline_ambiguity_blocker",
            "admission_policy_read_model",
            "pure_liveness_heartbeat",
            "result_wait_readback_status_snapshot",
        ],
        "adoption_state": "default_hot_path_ready",
        "runtime_enforced": False,
        "default_runtime_scheduler_invoked": False,
        "provider_invocation_performed": payload.get("provider_invocation_performed") is True,
        "runtime_latest": payload.get("output_paths", {}).get("latest", ""),
        "current_index_latest": payload.get("output_paths", {}).get("current_index_latest", ""),
        "cli_command": "python -m xinao_seedlab.cli.__main__ 333-run-reconciler",
        "powershell_command": "scripts/hardmode/Invoke-CodexS333RunReconciler.ps1",
        "not_execution_controller": True,
        "completion_claim_allowed": False,
        "model_invocation_performed": False,
        "generated_at": now_iso(),
    }


def tool_registry_provider(payload: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": "codex_s.333_run_reconciler",
        "capability_kinds": manifest["capability_kinds"],
        "exists_code": True,
        "callable_now": True,
        "exposed_to_current_codex": True,
        "entrypoint": "scripts/hardmode/Invoke-CodexS333RunReconciler.ps1",
        "adoption_state": "default_hot_path_ready",
        "runtime_enforced": False,
        "provider_invocation_performed": payload.get("provider_invocation_performed") is True,
        "five_layer_status": {
            "connected_to_333": "current_333_run_index_reconcile_before_foreground_watch",
            "aaq_state": "not_artifact_acceptance_surface",
        },
        "evidence_refs": {
            "latest": payload.get("output_paths", {}).get("latest", ""),
            "current_index": payload.get("output_paths", {}).get("current_index_latest", ""),
            "manifest": payload.get("output_paths", {}).get("capability_manifest", ""),
        },
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "notes": (
            "Read-only Temporal visibility reconciler. It selects exactly one running "
            "333 mainline or writes a NO_ACTIVE/AMBIGUOUS blocker. Its control-plane "
            "liveness snapshot is heartbeat/readback only and does not call Codex/V4Pro."
        ),
    }


def upsert_tool_registry(path: Path, provider: dict[str, Any]) -> dict[str, Any]:
    registry = read_json(path)
    if not registry:
        registry = {
            "schema_version": f"{SCHEMA_VERSION}.tool_registry_patch.v1",
            "status": "s_tool_registry_ready",
            "providers": [],
            "provider_ids": [],
            "not_execution_controller": True,
        }
    providers = registry.get("providers") if isinstance(registry.get("providers"), list) else []
    providers = [
        item
        for item in providers
        if isinstance(item, dict) and item.get("provider_id") != provider["provider_id"]
    ]
    providers.append(provider)
    registry["providers"] = providers
    registry["provider_ids"] = [
        str(item.get("provider_id"))
        for item in providers
        if isinstance(item, dict) and str(item.get("provider_id") or "").strip()
    ]
    registry["not_execution_controller"] = True
    registry["completion_claim_allowed"] = False
    registry["updated_by"] = "codex_s.333_run_reconciler"
    registry["updated_at"] = now_iso()
    write_json(path, registry)
    return registry


def render_readback(payload: dict[str, Any]) -> str:
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    selected = decision.get("selected_workflow") if isinstance(decision.get("selected_workflow"), dict) else {}
    blocker = str(decision.get("named_blocker") or "")
    lines = [
        "# 333 run reconciler",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- running_workflow_count: `{payload.get('running_workflow_count')}`",
        f"- mainline_candidate_count: `{payload.get('mainline_candidate_count')}`",
        f"- selected_workflow_id: `{selected.get('workflow_id', '')}`",
        f"- selected_run_id: `{selected.get('run_id', '')}`",
        f"- named_blocker: `{blocker}`",
        f"- liveness_status: `{payload.get('control_plane_liveness', {}).get('status', '')}`",
        "- heartbeat_role: `pure_liveness_read_model; no model call, no worker dispatch, no signal`",
        "- boundary: Temporal visibility read model + current index rewrite; no signal, no cancel, no worker start/stop.",
        "",
        "人话：它只负责把 Temporal 里正在跑的 workflow 对账成一个当前 333 指针；如果多条都像主线，就写 AMBIGUOUS_ACTIVE_333_MAINLINE，禁止前台盲接旧指针。",
        "",
    ]
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    temporal_address: str = DEFAULT_TEMPORAL_ADDRESS,
    task_queue: str = DEFAULT_TASK_QUEUE,
    workflow_type: str = DEFAULT_WORKFLOW_TYPE,
    running_workflows_override: list[dict[str, Any]] | None = None,
    port_open_override: bool | None = None,
    worker_status_override: dict[str, Any] | None = None,
    command_runner: CommandRunner | None = None,
    write: bool = True,
    write_current_index: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    previous_index = read_json(runtime / "state" / "current_333_run_index" / "latest.json")
    port_open = tcp_port_open(temporal_address) if port_open_override is None else port_open_override
    worker = (
        read_worker_status(runtime, temporal_address=temporal_address, task_queue=task_queue)
        if worker_status_override is None
        else dict(worker_status_override)
    )
    list_status = list_running_workflows(
        temporal_address=temporal_address,
        command_runner=command_runner,
        override=running_workflows_override,
    )
    classified = [
        workflow_role(item, task_queue=task_queue, workflow_type=workflow_type)
        for item in list_status.get("workflows", [])
        if isinstance(item, dict)
    ]
    classified.sort(key=lambda item: str(item.get("start_time") or ""), reverse=True)
    candidates = [item for item in classified if item.get("eligible_mainline") is True]
    selected, blocker = choose_current_mainline(
        classified,
        port_open=port_open,
        worker_status=worker,
        list_status=list_status,
    )
    control_plane_liveness = build_control_plane_liveness(
        port_open=port_open,
        worker_status=worker,
        list_status=list_status,
        classified_workflows=classified,
        mainline_candidates=candidates,
        selected=selected,
        blocker=blocker,
    )
    current_index = build_current_index(
        selected=selected,
        blocker=blocker,
        candidates=candidates,
        all_running=classified,
        temporal_address=temporal_address,
        task_queue=task_queue,
        worker_status=worker,
        previous_index=previous_index,
        control_plane_liveness=control_plane_liveness,
    )
    record_id = str((selected or {}).get("workflow_id") or blocker or "latest")
    paths = output_paths(runtime, record_id=record_id)
    selected_ok = selected is not None and not blocker
    named_blocker_ok = bool(blocker)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "status": "codex_333_run_reconciler_ready"
        if selected_ok
        else "codex_333_run_reconciler_named_blocker",
        "runtime_root": str(runtime),
        "repo_root": str(repo),
        "temporal_address": temporal_address,
        "task_queue": task_queue,
        "workflow_type": workflow_type,
        "port_open": port_open,
        "worker_status": worker,
        "control_plane_liveness": control_plane_liveness,
        "workflow_list": {
            key: value
            for key, value in list_status.items()
            if key not in {"workflows"}
        },
        "running_workflow_count": len(classified),
        "mainline_candidate_count": len(candidates),
        "classified_workflows": classified,
        "decision": {
            "selected": selected_ok,
            "selected_workflow": selected or {},
            "named_blocker": blocker,
            "selection_policy": "exactly_one_running_mainline_candidate_else_named_blocker",
            "temporary_workflows_ignored": len(
                [item for item in classified if item.get("role") == "temporary_probe_or_ad_hoc"]
            ),
        },
        "current_333_run_index": current_index,
        "adoption_state": "default_hot_path_ready",
        "default_mainline_hardened": True,
        "default_consumer": "current_333_run_index / default_main_loop_trigger_candidate / foreground mirror watch",
        "workspace_only": False,
        "provider_invocation_performed": True,
        "model_invocation_performed": False,
        "control_plane_liveness_only": True,
        "no_temporal_write_performed": True,
        "no_signal_sent": True,
        "no_worker_started_or_stopped": True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "generated_at": now_iso(),
    }
    payload["validation"] = {
        "passed": (
            (selected_ok or named_blocker_ok)
            and current_index.get("completion_claim_allowed") is False
            and current_index.get("not_execution_controller") is True
            and control_plane_liveness.get("model_invocation_performed") is False
            and control_plane_liveness.get("no_provider_worker_dispatch") is True
        ),
        "checks": {
            "selected_or_named_blocker": selected_ok or named_blocker_ok,
            "current_index_payload_ready": bool(current_index),
            "current_index_completion_claim_blocked": current_index.get("completion_claim_allowed")
            is False,
            "control_plane_liveness_snapshot_ready": bool(control_plane_liveness),
            "control_plane_liveness_no_model_invocation": (
                control_plane_liveness.get("model_invocation_performed") is False
            ),
            "control_plane_liveness_no_worker_dispatch": (
                control_plane_liveness.get("no_provider_worker_dispatch") is True
            ),
            "temporal_write_not_performed": payload["no_temporal_write_performed"] is True,
            "signal_not_sent": payload["no_signal_sent"] is True,
            "worker_not_started_or_stopped": payload["no_worker_started_or_stopped"] is True,
        },
        "validated_at": now_iso(),
    }
    manifest = capability_manifest(payload)
    if write:
        registry_provider = tool_registry_provider(payload, manifest)
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        write_json(paths["capability_manifest"], manifest)
        upsert_tool_registry(paths["tool_registry"], registry_provider)
        if write_current_index:
            write_json(paths["current_index_latest"], current_index)
            write_json(paths["current_index_record"], current_index)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-333-run-reconciler")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--temporal-address", default=DEFAULT_TEMPORAL_ADDRESS)
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--workflow-type", default=DEFAULT_WORKFLOW_TYPE)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--no-current-index-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        temporal_address=args.temporal_address,
        task_queue=args.task_queue,
        workflow_type=args.workflow_type,
        write=not args.no_write,
        write_current_index=not args.no_current_index_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "running_workflow_count": payload["running_workflow_count"],
                "mainline_candidate_count": payload["mainline_candidate_count"],
                "decision": payload["decision"],
                "control_plane_liveness": payload["control_plane_liveness"],
                "current_index_ref": payload["output_paths"]["current_index_latest"],
                "latest_ref": payload["output_paths"]["latest"],
                "validation": payload["validation"],
                "completion_claim_allowed": payload["completion_claim_allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
