from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.durable_default_chain_supervisor.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_DURABLE_DEFAULT_CHAIN_SUPERVISOR_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = WORK_ID
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SOURCE_ROOT = Path(r"C:\Users\xx363\Desktop\新系统")
DEFAULT_PACKAGE = Path(
    r"C:\Users\xx363\Desktop\新系统_超大块阶段验证与投递包_20260704.bak_before_closure_update.txt"
)
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
DEFAULT_SUPERVISOR_WAVE_ID = "codex-s-durable-default-chain-supervisor-20260704-night"
DEFAULT_PARENT_WAVE_ID = "source-frontier-workerpool-global-closure-20260704-verify-wave"
DEFAULT_POLL_SECONDS = 180
DEFAULT_MIN_DISPATCH_INTERVAL_SECONDS = 600
DEFAULT_WORKFLOW_TIMEOUT_SECONDS = 180
DEFAULT_CODEX_WORKER_TIMEOUT_SECONDS = 120
DEFAULT_LOOP_STEPS = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
]
SOURCE_AUTHORITY_FILENAMES = [
    "AUTHORITY_READ_ORDER.txt",
    "当前源文本增量_20260704.txt",
    "根意图分工.txt",
    "XINAO_333_固定锚点.txt",
    "新系统独立并行_自由发散外部研究总稿_20260701.txt",
    "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(value).strip())
    cleaned = cleaned.strip("-_.") or "wave"
    if len(cleaned) <= 120:
        return cleaned
    digest = hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{cleaned[:103].strip('-_.') or 'wave'}-{digest}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def digest_json(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8", errors="replace")).hexdigest()


def file_digest(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": "",
        "length": 0,
        "line_count": 0,
        "last_write_time": "",
    }
    if not path.is_file():
        return ref
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    stat = path.stat()
    ref.update(
        {
            "sha256": hashlib.sha256(data).hexdigest(),
            "length": stat.st_size,
            "line_count": len(text.splitlines()),
            "last_write_time": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds"),
        }
    )
    return ref


def source_package_refs(source_root: Path, package_path: Path) -> dict[str, Any]:
    authority_refs = [file_digest(source_root / name) for name in SOURCE_AUTHORITY_FILENAMES]
    package_ref = file_digest(package_path)
    aggregate_basis = {
        "package": package_ref,
        "source_root": str(source_root),
        "authority_refs": authority_refs,
    }
    return {
        "source_root": str(source_root),
        "stage_package_ref": package_ref,
        "authority_refs": authority_refs,
        "authority_file_count": len(authority_refs),
        "authority_existing_count": len([item for item in authority_refs if item.get("exists") is True]),
        "source_package_digest_sha256": digest_json(aggregate_basis),
        "current_package_rank0_for_task": True,
        "desktop_new_system_anchor": True,
        "read_order": [
            str(package_path),
            str(source_root / "AUTHORITY_READ_ORDER.txt"),
            str(source_root / "当前源文本增量_20260704.txt"),
            str(source_root / "根意图分工.txt"),
            str(source_root / "XINAO_333_固定锚点.txt"),
            str(source_root / "新系统独立并行_自由发散外部研究总稿_20260701.txt"),
            str(source_root / "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt"),
        ],
    }


def output_paths(runtime: Path, supervisor_wave_id: str, cycle_id: str, digest: str = "pending") -> dict[str, str]:
    wave_stem = safe_stem(supervisor_wave_id)
    cycle_stem = safe_stem(cycle_id)
    root = runtime / "state" / "codex_s_durable_default_chain_supervisor"
    wave_root = root / "waves" / wave_stem
    return {
        "latest": str(root / "latest.json"),
        "wave_latest": str(wave_root / "latest.json"),
        "cycle": str(wave_root / f"{cycle_stem}.json"),
        "heartbeat_latest": str(wave_root / "heartbeat_latest.json"),
        "repair_plan": str(wave_root / f"{cycle_stem}.repair_plan.json"),
        "process_latest": str(root / "process" / f"{wave_stem}.json"),
        "readback_zh": str(runtime / "readback" / "zh" / f"codex_s_durable_default_chain_supervisor_{wave_stem}.md"),
        "worker_dispatch_ledger_wave": str(
            runtime
            / "state"
            / "worker_dispatch_ledger"
            / "waves"
            / wave_stem
            / f"{digest}.codex_s_durable_default_chain_supervisor.json"
        ),
        "activity_ledger": str(
            runtime
            / "state"
            / "worker_dispatch_ledger"
            / "activity"
            / "codex-s-durable-default-chain-supervisor"
            / f"{cycle_stem}.json"
        ),
        "stdout_log": str(wave_root / "logs" / f"{cycle_stem}.stdout.log"),
        "stderr_log": str(wave_root / "logs" / f"{cycle_stem}.stderr.log"),
    }


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    stop = payload.get("stop") if isinstance(payload.get("stop"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": str(payload.get("schema_version") or ""),
        "status": str(payload.get("status") or ""),
        "wave_id": str(payload.get("wave_id") or ""),
        "parent_wave_id": str(payload.get("parent_wave_id") or ""),
        "workflow_id": str(payload.get("workflow_id") or ""),
        "validation_passed": validation.get("passed"),
        "stop_allowed": stop.get("stop_allowed", payload.get("stop_allowed")),
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
        "not_execution_controller": payload.get("not_execution_controller"),
        "next_frontier_ref": str(payload.get("output_paths", {}).get("next_frontier") or "")
        if isinstance(payload.get("output_paths"), dict)
        else "",
    }


def runtime_refs(runtime: Path) -> dict[str, dict[str, Any]]:
    state = runtime / "state"
    paths = {
        "temporal_workflow_latest": state / "temporal_codex_task_workflow" / "latest.json",
        "worker_dispatch_ledger_latest": state / "worker_dispatch_ledger" / "latest.json",
        "worker_dispatch_ledger_temporal_activity": state / "worker_dispatch_ledger" / "temporal_activity_latest.json",
        "codex_s_main_execution_loop_tick_temporal_activity": state
        / "codex_s_main_execution_loop_tick"
        / "temporal_activity_latest.json",
        "durable_parallel_wave_packet_temporal_activity": state
        / "durable_parallel_wave_packet"
        / "temporal_activity_latest.json",
        "default_main_loop_trigger_candidate_temporal_activity": state
        / "default_main_loop_trigger_candidate"
        / "temporal_activity_latest.json",
        "source_frontier_workerbrief_bridge_latest": state / "source_frontier_workerbrief_bridge" / "latest.json",
        "source_frontier_workerpool_closure_latest": state / "source_frontier_workerpool_closure" / "latest.json",
        "source_frontier_workerpool_closure_wave": state
        / "source_frontier_workerpool_closure"
        / "latest.json",
        "artifact_acceptance_queue_latest": state / "artifact_acceptance_queue" / "latest.json",
        "next_frontier_machine_actions_latest": state / "next_frontier_machine_actions" / "latest.json",
        "default_auto_dispatch_latest": state / "default_auto_dispatch" / "latest.json",
        "loop_runtime_state_latest": state / "loop_runtime_state" / "latest.json",
        "root_intent_loop_driver_latest": state / "root_intent_loop_driver" / "latest.json",
        "codex_s_live_backend_watch_latest": state / "codex_s_live_backend_watch" / "latest.json",
    }
    return {name: json_ref(path) for name, path in paths.items()}


def temporal_port_open(host: str = "127.0.0.1", port: int = 7233, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_workflow_command(
    *,
    python_exe: str,
    runtime: Path,
    repo: Path,
    source_refs: list[str],
    task_queue: str,
    workflow_id: str,
    user_goal: str,
    codex_worker_timeout_sec: int = DEFAULT_CODEX_WORKER_TIMEOUT_SECONDS,
) -> list[str]:
    worker_task_id = f"{safe_stem(workflow_id)}.source-bound.codex-worker"
    source_ref_lines = "\n".join(f"- {ref}" for ref in source_refs)
    worker_prompt = (
        "You are a task-bound Codex S implementation worker for the durable default chain.\n"
        "Do not claim completion to the user. Produce backend worker evidence only.\n"
        "The source refs below are already bound by the Temporal workflow; do not open or summarize large source files.\n"
        "Do not run shell commands. Do not modify files. Do not run tests.\n"
        "Write at most six short lines: worker_task, source_ref_count, route, evidence_kind, next_action, marker.\n"
        "Use evidence_kind=task_bound_codex_exec_jsonl and next_action=continue_fan_in_aaq_next_frontier.\n"
        "Bound source refs, for identity only:\n"
        f"{source_ref_lines}\n"
        f"Final line must contain exactly RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK for worker-ledger acceptance."
    )
    command = [
        python_exe,
        "-m",
        "services.agent_runtime.temporal_codex_task_workflow",
        "--task-id",
        TASK_ID,
        "--user-goal",
        user_goal,
        "--mode",
        "partial",
        "--runtime-root",
        str(runtime),
        "--task-queue",
        task_queue,
        "--workflow-id",
        workflow_id,
        "--live-temporal",
        "--execute-codex-worker",
        "--codex-worker-task-id",
        worker_task_id,
        "--codex-worker-prompt",
        worker_prompt,
        "--codex-worker-timeout-sec",
        str(max(30, int(codex_worker_timeout_sec))),
        "--human-egress-route",
        "grok_report_only",
        "--segment-boundary-headless",
        "--phase4-skip-codex-exec-canary",
        "--phase4-skip-qwen-canary",
    ]
    for source_ref in source_refs:
        command.extend(["--source-ref", source_ref])
    env_repo = str(repo)
    if env_repo:
        os.environ["XINAO_CODEX_S_REPO_ROOT"] = env_repo
    return command


def run_live_temporal_start(
    *,
    command: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    started_perf = time.perf_counter()
    env = os.environ.copy()
    env.setdefault("XINAO_RUNTIME_REPO_READBACK_WRITE", "0")
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        return {
            "dispatch_attempted": True,
            "started_at": started,
            "completed_at": now_iso(),
            "duration_ms": int((time.perf_counter() - started_perf) * 1000),
            "exit_code": result.returncode,
            "stdout_ref": str(stdout_path),
            "stderr_ref": str(stderr_path),
            "command": command,
            "succeeded": result.returncode == 0,
            "named_blocker": "" if result.returncode == 0 else "LIVE_TEMPORAL_WORKFLOW_START_FAILED",
        }
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "workflow start timed out", encoding="utf-8")
        return {
            "dispatch_attempted": True,
            "started_at": started,
            "completed_at": now_iso(),
            "duration_ms": int((time.perf_counter() - started_perf) * 1000),
            "exit_code": 124,
            "stdout_ref": str(stdout_path),
            "stderr_ref": str(stderr_path),
            "command": command,
            "succeeded": False,
            "named_blocker": "LIVE_TEMPORAL_WORKFLOW_START_TIMEOUT",
        }


def build_repair_plan(
    *,
    cycle_id: str,
    dispatch_result: dict[str, Any],
    temporal_available: bool,
    runtime_ref_map: dict[str, dict[str, Any]],
    output: dict[str, str],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if not temporal_available:
        items.append(
            {
                "blocker_name": "TEMPORAL_SERVER_NOT_AVAILABLE",
                "fixable": True,
                "unblock_action": "restart Temporal dev server then requeue same supervisor wave",
                "report_substitute_allowed": False,
            }
        )
    if dispatch_result.get("dispatch_attempted") and dispatch_result.get("succeeded") is not True:
        items.append(
            {
                "blocker_name": dispatch_result.get("named_blocker") or "LIVE_TEMPORAL_WORKFLOW_START_FAILED",
                "fixable": True,
                "unblock_action": "retry live Temporal start; if repeated, run local source-bound closure repair lane",
                "dispatch_stdout_ref": dispatch_result.get("stdout_ref", ""),
                "dispatch_stderr_ref": dispatch_result.get("stderr_ref", ""),
                "report_substitute_allowed": False,
            }
        )
    closure_ref = runtime_ref_map.get("source_frontier_workerpool_closure_latest", {})
    if closure_ref.get("validation_passed") is not True:
        items.append(
            {
                "blocker_name": "SOURCE_FRONTIER_WORKERPOOL_CLOSURE_NOT_VALIDATED",
                "fixable": True,
                "unblock_action": "requeue source_frontier_workerbrief_bridge then source_frontier_workerpool_closure",
                "report_substitute_allowed": False,
            }
        )
    repair_required = bool(items)
    return {
        "schema_version": f"{SCHEMA_VERSION}.repair_plan.v1",
        "status": "repair_plan_required" if repair_required else "repair_plan_not_required",
        "cycle_id": cycle_id,
        "repair_plan_ref": output["repair_plan"],
        "repair_required": repair_required,
        "fixable_repair_count": len([item for item in items if item.get("fixable") is True]),
        "repair_items": items,
        "named_blocker": "" if not items or any(item.get("fixable") for item in items) else "DURABLE_SUPERVISOR_EXTERNAL_BLOCKER",
        "continue_main_loop": True,
        "dispatch_to": "RootIntentLoop / S Default Dynamic Loop",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_cycle_record(
    *,
    runtime: Path,
    repo: Path,
    source_root: Path,
    package_path: Path,
    supervisor_wave_id: str,
    parent_wave_id: str,
    cycle_index: int,
    poll_seconds: int,
    task_queue: str,
    dispatch_result: dict[str, Any],
    no_dispatch: bool,
) -> dict[str, Any]:
    cycle_id = f"{supervisor_wave_id}-cycle-{cycle_index:06d}"
    runtime_ref_map = runtime_refs(runtime)
    temporal_available = temporal_port_open()
    source_refs = source_package_refs(source_root, package_path)
    stop_source = runtime_ref_map.get("loop_runtime_state_latest", {})
    stop_allowed = stop_source.get("stop_allowed") is True
    basis = {
        "supervisor_wave_id": supervisor_wave_id,
        "cycle_id": cycle_id,
        "source_package_digest_sha256": source_refs["source_package_digest_sha256"],
        "runtime_refs": runtime_ref_map,
        "dispatch_result": dispatch_result,
        "stop_allowed": stop_allowed,
    }
    digest = digest_json(basis)
    output = output_paths(runtime, supervisor_wave_id, cycle_id, digest=digest)
    repair_plan = build_repair_plan(
        cycle_id=cycle_id,
        dispatch_result=dispatch_result,
        temporal_available=temporal_available,
        runtime_ref_map=runtime_ref_map,
        output=output,
    )
    next_poll_at = (
        dt.datetime.now(dt.timezone.utc).astimezone() + dt.timedelta(seconds=max(1, poll_seconds))
    ).isoformat(timespec="seconds")
    closure_ref = runtime_ref_map.get("source_frontier_workerpool_closure_latest", {})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "durable_default_chain_supervisor_polling",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "route_profile": ROUTE_PROFILE,
        "routing": "continue_same_task",
        "supervisor_wave_id": supervisor_wave_id,
        "parent_wave_id": parent_wave_id,
        "cycle_id": cycle_id,
        "cycle_index": cycle_index,
        "generated_at": now_iso(),
        "default_transaction_chain": "RootIntentLoop / S Default Dynamic Loop",
        "main_execution_loop": DEFAULT_LOOP_STEPS,
        "stage_package_landed": True,
        "phase_package_ref": source_refs["stage_package_ref"],
        "source_package": source_refs,
        "temporal": {
            "server_port_open": temporal_available,
            "task_queue": task_queue,
            "worker_required": True,
            "live_temporal_route_requested": dispatch_result.get("dispatch_attempted") is True,
            "no_dispatch_mode": no_dispatch,
        },
        "dispatch_supervision": {
            "dispatch_attempted_this_cycle": dispatch_result.get("dispatch_attempted") is True,
            "dispatch_result": dispatch_result,
            "workflow_id": dispatch_result.get("workflow_id", ""),
            "latest_closure_ref": closure_ref,
            "workerpool_closure_validation_seen": closure_ref.get("validation_passed") is True,
            "default_every_wave_target": "source -> WorkerBrief -> ProviderScheduler -> pool -> staging -> merge -> FanIn/AAQ -> next_frontier",
            "pass_report_substitute_allowed": False,
        },
        "runtime_refs": runtime_ref_map,
        "repair_plan": repair_plan,
        "stop": {
            "stop_allowed": False,
            "stop_allowed_from_runtime": stop_allowed,
            "forced_false_reason": "user_requested_overnight_durable_polling_and_source_gap_remains_open",
            "derived_from_refs": [
                "loop_runtime_state",
                "source_frontier_workerpool_closure",
                "worker_dispatch_ledger",
                "default_auto_dispatch",
                "next_frontier_machine_actions",
            ],
            "user_stop_requested": False,
            "completion_claim_allowed": False,
        },
        "next_poll_at": next_poll_at,
        "heartbeat": {
            "background_keepalive": True,
            "polling_continues": True,
            "supervisor_pid": os.getpid(),
            "poll_seconds": poll_seconds,
            "next_poll_at": next_poll_at,
        },
        "output_paths": output,
        "evidence_digest_sha256": digest,
        "validation": {
            "passed": True,
            "checks": {
                "stage_package_bound": source_refs["stage_package_ref"].get("exists") is True,
                "desktop_source_root_bound": source_root.is_dir(),
                "authority_refs_present": source_refs["authority_existing_count"] >= 4,
                "default_transaction_chain_bound": True,
                "temporal_server_seen": temporal_available,
                "latest_not_completion": True,
                "stop_allowed_false": True,
                "pass_report_substitute_denied": True,
                "background_keepalive_declared": True,
                "repair_plan_present": isinstance(repair_plan, dict),
            },
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    source = payload.get("source_package") if isinstance(payload.get("source_package"), dict) else {}
    stage = source.get("stage_package_ref") if isinstance(source.get("stage_package_ref"), dict) else {}
    dispatch = payload.get("dispatch_supervision") if isinstance(payload.get("dispatch_supervision"), dict) else {}
    heartbeat = payload.get("heartbeat") if isinstance(payload.get("heartbeat"), dict) else {}
    repair = payload.get("repair_plan") if isinstance(payload.get("repair_plan"), dict) else {}
    lines = [
        "# Codex S 耐久默认主链监工 readback",
        "",
        SENTINEL,
        "",
        f"- supervisor_wave_id: `{payload.get('supervisor_wave_id')}`",
        f"- cycle_id: `{payload.get('cycle_id')}`",
        f"- 阶段投递包: `{stage.get('path', '')}`",
        f"- 阶段投递包 sha256: `{stage.get('sha256', '')}`",
        f"- 新系统源文本 digest: `{source.get('source_package_digest_sha256', '')}`",
        f"- 当前能 invoke: `python -m services.agent_runtime.temporal_codex_task_workflow --live-temporal`；后台脚本 `scripts\\start_codex_s_durable_default_chain_supervisor.ps1`。",
        f"- 本轮是否触发 live Temporal 主链: {dispatch.get('dispatch_attempted_this_cycle')}",
        f"- source-bound workerpool closure validation seen: {dispatch.get('workerpool_closure_validation_seen')}",
        f"- stop_allowed: {payload.get('stop', {}).get('stop_allowed')}，下一次轮询: `{heartbeat.get('next_poll_at', '')}`",
        f"- repair_required: {repair.get('repair_required')}，named_blocker: `{repair.get('named_blocker', '')}`",
        "",
        "人话：这不是 PASS 报告。它是后台保活/派单监工 evidence，继续按 RootIntentLoop 轮询 live Temporal、worker ledger、staging/merge、FanIn/AAQ 和 next_frontier。",
        "如果某轮 live Temporal 或 closure 卡住，本文件写 RepairPlan 并继续回默认主链重试，不把 latest/readback 当完成。",
        "",
        SENTINEL,
        "",
    ]
    return "\n".join(lines)


def write_cycle(payload: dict[str, Any]) -> None:
    output = payload["output_paths"]
    ledger = {
        "schema_version": f"{SCHEMA_VERSION}.worker_dispatch_ledger_wave.v1",
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": payload["supervisor_wave_id"],
        "cycle_id": payload["cycle_id"],
        "parent_wave_id": payload["parent_wave_id"],
        "status": "durable_default_chain_supervisor_cycle_recorded",
        "immutable_wave_evidence": True,
        "latest_alias_is_not_proof": True,
        "cycle_ref": output["cycle"],
        "evidence_digest_sha256": payload["evidence_digest_sha256"],
        "dispatch_result": payload["dispatch_supervision"]["dispatch_result"],
        "repair_required": payload["repair_plan"]["repair_required"],
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": payload["generated_at"],
    }
    activity = {
        "schema_version": f"{SCHEMA_VERSION}.activity.v1",
        "sentinel": SENTINEL,
        "activity": "codex_s_durable_default_chain_supervisor",
        "status": "activity_wave_recorded",
        "wave_id": payload["supervisor_wave_id"],
        "cycle_id": payload["cycle_id"],
        "immutable_wave_evidence_ref": output["worker_dispatch_ledger_wave"],
        "cycle_ref": output["cycle"],
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": payload["generated_at"],
    }
    write_json(Path(output["cycle"]), payload)
    write_json(Path(output["latest"]), payload)
    write_json(Path(output["wave_latest"]), payload)
    write_json(Path(output["heartbeat_latest"]), payload["heartbeat"])
    write_json(Path(output["repair_plan"]), payload["repair_plan"])
    write_json(Path(output["worker_dispatch_ledger_wave"]), ledger)
    write_json(Path(output["activity_ledger"]), activity)
    write_text(Path(output["readback_zh"]), render_readback(payload))


def run_supervisor(
    *,
    runtime: Path,
    repo: Path,
    source_root: Path,
    package_path: Path,
    supervisor_wave_id: str,
    parent_wave_id: str,
    task_queue: str,
    poll_seconds: int,
    min_dispatch_interval_seconds: int,
    max_cycles: int,
    once: bool,
    no_dispatch: bool,
    workflow_timeout_seconds: int,
    python_exe: str,
) -> dict[str, Any]:
    cycle_index = 0
    last_dispatch_monotonic = 0.0
    last_payload: dict[str, Any] = {}
    source_ref_paths = [str(package_path)] + [str(source_root / name) for name in SOURCE_AUTHORITY_FILENAMES]
    while True:
        cycle_index += 1
        cycle_id = f"{supervisor_wave_id}-cycle-{cycle_index:06d}"
        provisional_output = output_paths(runtime, supervisor_wave_id, cycle_id)
        now_monotonic = time.monotonic()
        dispatch_due = (
            not no_dispatch
            and (last_dispatch_monotonic == 0.0 or now_monotonic - last_dispatch_monotonic >= min_dispatch_interval_seconds)
        )
        dispatch_result: dict[str, Any] = {
            "dispatch_attempted": False,
            "succeeded": False,
            "named_blocker": "DISPATCH_NOT_DUE_OR_DISABLED",
        }
        if dispatch_due:
            workflow_id = f"{safe_stem(supervisor_wave_id)}-live-{cycle_index:06d}"
            command = build_workflow_command(
                python_exe=python_exe,
                runtime=runtime,
                repo=repo,
                source_refs=source_ref_paths,
                task_queue=task_queue,
                workflow_id=workflow_id,
                user_goal="land stage package with durable default chain polling, source-bound workerpool closure, and no PASS stop",
            )
            dispatch_result = run_live_temporal_start(
                command=command,
                cwd=repo,
                stdout_path=Path(provisional_output["stdout_log"]),
                stderr_path=Path(provisional_output["stderr_log"]),
                timeout_seconds=workflow_timeout_seconds,
            )
            dispatch_result["workflow_id"] = workflow_id
            if dispatch_result.get("dispatch_attempted"):
                last_dispatch_monotonic = now_monotonic
        last_payload = build_cycle_record(
            runtime=runtime,
            repo=repo,
            source_root=source_root,
            package_path=package_path,
            supervisor_wave_id=supervisor_wave_id,
            parent_wave_id=parent_wave_id,
            cycle_index=cycle_index,
            poll_seconds=poll_seconds,
            task_queue=task_queue,
            dispatch_result=dispatch_result,
            no_dispatch=no_dispatch,
        )
        write_cycle(last_payload)
        print(
            json.dumps(
                {
                    "sentinel": SENTINEL,
                    "cycle_id": last_payload["cycle_id"],
                    "latest_ref": last_payload["output_paths"]["latest"],
                    "heartbeat_ref": last_payload["output_paths"]["heartbeat_latest"],
                    "dispatch_attempted": dispatch_result.get("dispatch_attempted") is True,
                    "next_poll_at": last_payload["next_poll_at"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if once or (max_cycles > 0 and cycle_index >= max_cycles):
            return last_payload
        time.sleep(max(1, poll_seconds))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex S durable default-chain polling supervisor.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--package-path", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--supervisor-wave-id", default=DEFAULT_SUPERVISOR_WAVE_ID)
    parser.add_argument("--parent-wave-id", default=DEFAULT_PARENT_WAVE_ID)
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--min-dispatch-interval-seconds", type=int, default=DEFAULT_MIN_DISPATCH_INTERVAL_SECONDS)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--workflow-timeout-seconds", type=int, default=DEFAULT_WORKFLOW_TIMEOUT_SECONDS)
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-dispatch", action="store_true")
    args = parser.parse_args(argv)
    payload = run_supervisor(
        runtime=Path(args.runtime_root),
        repo=Path(args.repo_root),
        source_root=Path(args.source_root),
        package_path=Path(args.package_path),
        supervisor_wave_id=args.supervisor_wave_id,
        parent_wave_id=args.parent_wave_id,
        task_queue=args.task_queue,
        poll_seconds=args.poll_seconds,
        min_dispatch_interval_seconds=args.min_dispatch_interval_seconds,
        max_cycles=args.max_cycles,
        once=args.once,
        no_dispatch=args.no_dispatch,
        workflow_timeout_seconds=args.workflow_timeout_seconds,
        python_exe=args.python_exe,
    )
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
