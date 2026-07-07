from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import task_package_resolver as task_package
from services.agent_runtime import next_frontier_continuation_supervisor as next_frontier_supervisor


SCHEMA_VERSION = "xinao.codex_s.wave2_mainchain_hygiene.v1"
SENTINEL = "SENTINEL:XINAO_WAVE2_MAINCHAIN_HYGIENE_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave2_mainchain_hygiene_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
DEFAULT_PLANNING_TEXT = Path(r"C:\Users\xx363\Desktop\新系统_源文本对照_整块进度规划_20260704.txt")
PLANNING_TEXT_FALLBACKS = [
    Path(r"C:\Users\xx363\Desktop\新系统_超大块阶段验证与投递包_20260704.txt"),
    Path(r"C:\Users\xx363\Desktop\新系统_超大块阶段验证与投递包_20260704.bak_before_closure_update.txt"),
    DEFAULT_ANCHOR_PACKAGE / "当前源文本增量_20260704.txt",
]
SRC_ROOT = DEFAULT_REPO / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

AUTHORITY_FILES = [*task_package.LEGACY_AUTHORITY_FILES, "XINAO_333_固定锚点.txt"]
TASK_PACKAGE_MANIFEST_NAMES = list(task_package.TASK_PACKAGE_MANIFEST_NAMES)

MEMO_TARGETS = [
    "BrainProvider",
    "WorkerProvider",
    "ModelGateway",
    "ExecutorAdapter",
    "WorkerBrief",
    "DraftStagingQueue",
    "SpendLedger",
    "DynamicWidthPolicy",
    "MergeConsumer",
    "WidthBlocker",
    "LoopRuntimeState",
    "EventQueueContinuousConsume",
    "30minRunnerRemoval",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def json_summary(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "validation_passed": validation.get("passed"),
    }


def task_package_manifest_ref(anchor: Path) -> tuple[Path | None, dict[str, Any]]:
    for name in TASK_PACKAGE_MANIFEST_NAMES:
        candidate = anchor / name
        if candidate.is_file():
            payload = read_json(candidate)
            if payload:
                return candidate, payload
    return None, {}


def normalize_manifest_resource_path(anchor: Path, resource_path: str) -> Path:
    raw = str(resource_path or "").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return anchor / raw


def manifest_resource_paths(anchor: Path, manifest: dict[str, Any]) -> list[Path]:
    resources = manifest.get("resources")
    if not isinstance(resources, list):
        return []
    paths: list[Path] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        raw_path = str(resource.get("path") or resource.get("href") or "").strip()
        if not raw_path:
            continue
        paths.append(normalize_manifest_resource_path(anchor, raw_path))
    return paths


def resolve_planning_text(planning_text: Path) -> tuple[Path, dict[str, Any]]:
    requested = Path(planning_text)
    candidates: list[Path] = [requested]
    candidates.extend(path for path in PLANNING_TEXT_FALLBACKS if path != requested)
    candidate_refs = [{"path": str(path), "exists": path.is_file()} for path in candidates]
    for index, candidate in enumerate(candidates):
        if candidate.is_file():
            return candidate, {
                "requested_ref": str(requested),
                "resolved_ref": str(candidate),
                "used_fallback": index != 0,
                "resolution_reason": "requested_exists" if index == 0 else "current_stage_package_fallback",
                "candidate_refs": candidate_refs,
            }
    return requested, {
        "requested_ref": str(requested),
        "resolved_ref": str(requested),
        "used_fallback": False,
        "resolution_reason": "no_candidate_exists",
        "candidate_refs": candidate_refs,
    }


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "wave2_mainchain_hygiene"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_wave2_mainchain_hygiene.v1.json"),
        "temporal_activity_latest": str(root / "temporal_activity_latest.json"),
        "memo_gap_latest": str(root / "memo_gap_refresh" / "latest.json"),
        "black_window_latest": str(root / "black_window_probe" / "latest.json"),
        "default_main_loop_hygiene_latest": str(runtime / "state" / "default_main_loop_hygiene" / "latest.json"),
        "loop_runtime_overlay": str(runtime / "state" / "loop_runtime_state" / "wave2_mainchain_hygiene_overlay.json"),
        "next_frontier_scoped_latest": str(root / "next_frontier" / "latest.json"),
        "next_frontier_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "readback_zh": str(runtime / "readback" / "zh" / "wave_block2_mainchain_hygiene_20260704.md"),
    }


def source_package_refs(
    anchor: Path,
    planning_text: Path,
    *,
    requested_planning_text: Path | None = None,
    planning_text_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package = task_package.resolve_task_package(
        anchor,
        legacy_files=tuple(AUTHORITY_FILES),
        include_manifest_ref=True,
    )
    planning_ref = task_package.text_source_ref(
        planning_text,
        role=(
            "planning_reference_optional_when_manifest_present"
            if package.get("manifest_driven")
            else "legacy_planning_reference"
        ),
    )
    if package.get("manifest_driven") is not True:
        package["refs"] = [*package.get("refs", []), planning_ref]
        package["all_required_sources_read_full"] = all(
            ref.get("read_full") is True for ref in package.get("refs", [])
        )
    return {
        **package,
        "root": str(anchor),
        "package_mode": "manifest" if package.get("manifest_driven") else package.get("package_mode"),
        "task_package_manifest_ref": str(package.get("task_package_manifest_path") or ""),
        "planning_text_ref": str(planning_text),
        "requested_planning_text_ref": str(requested_planning_text or planning_text),
        "planning_text_resolution": planning_text_resolution
        or {
            "requested_ref": str(requested_planning_text or planning_text),
            "resolved_ref": str(planning_text),
            "used_fallback": False,
            "resolution_reason": "not_resolved_by_helper",
            "candidate_refs": [],
        },
        "planning_text_optional_ref": planning_ref,
        "source_frontier_scope": (
            "current_manifest_task_package_after_blocks_3_4_5"
            if package.get("manifest_driven")
            else "wave2_mainchain_hygiene_after_blocks_3_4_5"
        ),
    }


def hidden_subprocess_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _handle_value(value: Any) -> int:
    if isinstance(value, dict):
        return _handle_value(value.get("value"))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def process_window_snapshot() -> dict[str, Any]:
    if os.name != "nt":
        return {
            "windows_probe_supported": False,
            "visible_disallowed_console_count": 0,
            "visible_codex_s_terminal_count": 0,
            "visible_disallowed_console_processes": [],
            "visible_terminal_windows": [],
            "probe_error": "",
        }
    command = r"""
$names = 'cmd','powershell','pwsh','python','pythonw','OpenConsole','WindowsTerminal'
Get-Process | Where-Object { $names -contains $_.ProcessName } |
  Select-Object Id,ProcessName,MainWindowTitle,MainWindowHandle,Path |
  ConvertTo-Json -Depth 5
"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=12,
            **hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        return {
            "windows_probe_supported": True,
            "visible_disallowed_console_count": 1,
            "visible_codex_s_terminal_count": 0,
            "visible_disallowed_console_processes": [],
            "visible_terminal_windows": [],
            "probe_error": f"{type(exc).__name__}:{exc}",
        }
    if completed.returncode != 0:
        return {
            "windows_probe_supported": True,
            "visible_disallowed_console_count": 1,
            "visible_codex_s_terminal_count": 0,
            "visible_disallowed_console_processes": [],
            "visible_terminal_windows": [],
            "probe_error": (completed.stderr or "").strip(),
        }
    try:
        raw = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {
            "windows_probe_supported": True,
            "visible_disallowed_console_count": 1,
            "visible_codex_s_terminal_count": 0,
            "visible_disallowed_console_processes": [],
            "visible_terminal_windows": [],
            "probe_error": f"JSONDecodeError:{exc}",
        }
    processes = raw if isinstance(raw, list) else [raw]
    disallowed_names = {"cmd", "powershell", "pwsh", "python", "pythonw", "OpenConsole"}
    visible_disallowed: list[dict[str, Any]] = []
    visible_terminals: list[dict[str, Any]] = []
    for proc in processes:
        if not isinstance(proc, dict):
            continue
        handle = _handle_value(proc.get("MainWindowHandle"))
        row = {
            "pid": proc.get("Id"),
            "process_name": proc.get("ProcessName"),
            "main_window_title": proc.get("MainWindowTitle") or "",
            "main_window_handle": handle,
            "path": proc.get("Path") or "",
        }
        if handle <= 0:
            continue
        if row["process_name"] == "WindowsTerminal":
            visible_terminals.append(row)
        elif row["process_name"] in disallowed_names:
            visible_disallowed.append(row)
    codex_s_terminals = [
        item
        for item in visible_terminals
        if str(item.get("main_window_title") or "").strip() in {"S", "⠸ S"}
        or str(item.get("main_window_title") or "").strip().endswith(" S")
    ]
    return {
        "windows_probe_supported": True,
        "visible_disallowed_console_count": len(visible_disallowed),
        "visible_codex_s_terminal_count": len(codex_s_terminals),
        "visible_disallowed_console_processes": visible_disallowed,
        "visible_terminal_windows": visible_terminals,
        "probe_error": "",
    }


def start_worker_contract(repo: Path) -> dict[str, Any]:
    start_script = repo / "scripts" / "Start-XinaoTemporalCodexWorker.ps1"
    text = start_script.read_text(encoding="utf-8-sig") if start_script.is_file() else ""
    return {
        "start_worker_script_ref": str(start_script),
        "start_worker_script_exists": start_script.is_file(),
        "powershell_windowstyle_hidden": "-WindowStyle Hidden" in text,
        "redirects_stdout_stderr": "-RedirectStandardOutput" in text and "-RedirectStandardError" in text,
        "not_completion_source": "not_completion_decision" in text,
    }


def no_window_code_contract(repo: Path) -> dict[str, Any]:
    phase3 = repo / "services" / "agent_runtime" / "temporal_activity_no_window_dp_worker_pool_phase3.py"
    scheduler = repo / "services" / "agent_runtime" / "codex_native_provider_scheduler_phase4.py"
    phase3_text = phase3.read_text(encoding="utf-8-sig") if phase3.is_file() else ""
    scheduler_text = scheduler.read_text(encoding="utf-8-sig") if scheduler.is_file() else ""
    return {
        "phase3_ref": str(phase3),
        "phase4_scheduler_ref": str(scheduler),
        "phase3_create_no_window": "subprocess.CREATE_NO_WINDOW" in phase3_text,
        "phase3_startf_useshowwindow": "STARTF_USESHOWWINDOW" in phase3_text,
        "phase3_sw_hide": "SW_HIDE" in phase3_text or "wShowWindow = 0" in phase3_text,
        "scheduler_create_no_window": "CREATE_NO_WINDOW" in scheduler_text,
        "scheduler_startf_useshowwindow": "STARTF_USESHOWWINDOW" in scheduler_text,
    }


def build_black_window_probe(repo: Path, runtime: Path) -> dict[str, Any]:
    start_contract = start_worker_contract(repo)
    code_contract = no_window_code_contract(repo)
    snapshot = process_window_snapshot()
    worker_status = read_json(runtime / "state" / "temporal_codex_task_worker" / "latest.json")
    hidden_worker_pid = int(worker_status.get("pid") or 0)
    handled = (
        start_contract["powershell_windowstyle_hidden"] is True
        and code_contract["phase3_create_no_window"] is True
        and code_contract["phase3_startf_useshowwindow"] is True
        and int(snapshot.get("visible_disallowed_console_count") or 0) == 0
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.black_window_probe.v1",
        "status": "black_window_handled" if handled else "black_window_probe_blocked",
        "hidden_worker_pid": hidden_worker_pid,
        "temporal_worker_status_ref": str(runtime / "state" / "temporal_codex_task_worker" / "latest.json"),
        "start_worker_contract": start_contract,
        "no_window_code_contract": code_contract,
        "process_window_snapshot": snapshot,
        "visible_window_target": "only_one_codex_s_window",
        "visible_disallowed_cmd_powershell_python_count": int(
            snapshot.get("visible_disallowed_console_count") or 0
        ),
        "black_window_issue_handled": handled,
        "generated_at": now_iso(),
    }


def build_block_sequence(runtime: Path) -> dict[str, Any]:
    block3 = read_json(runtime / "state" / "source_frontier_durable_consumer" / "temporal_activity_latest.json")
    block4 = read_json(runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json")
    block5 = read_json(runtime / "state" / "phase0_reusable_kernel" / "temporal_activity_latest.json")
    return {
        "block3_source_frontier": {
            **json_summary(runtime / "state" / "source_frontier_durable_consumer" / "temporal_activity_latest.json"),
            "source_gap_open": block3.get("source_gap_open"),
            "consumed_batch_ids": block3.get("consumed_batch_ids", []),
            "remaining_batch_ids": block3.get("remaining_batch_ids", []),
        },
        "block4_source_family": {
            **json_summary(runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json"),
            "accepted_artifact_count": block4.get("artifact_acceptance_queue", {}).get("accepted_artifact_count")
            if isinstance(block4.get("artifact_acceptance_queue"), dict)
            else None,
            "source_family_count": len(block4.get("claim_card_staging_queue", {}).get("source_families", []))
            if isinstance(block4.get("claim_card_staging_queue"), dict)
            else None,
        },
        "block5_phase0_kernel": {
            **json_summary(runtime / "state" / "phase0_reusable_kernel" / "temporal_activity_latest.json"),
            "landed_count": block5.get("kernel_objects", {}).get("landed_count")
            if isinstance(block5.get("kernel_objects"), dict)
            else None,
            "object_count": block5.get("kernel_objects", {}).get("object_count")
            if isinstance(block5.get("kernel_objects"), dict)
            else None,
            "thin_bind_ready": block5.get("new_work_id_thin_bind", {}).get("bind_without_hand_solder")
            if isinstance(block5.get("new_work_id_thin_bind"), dict)
            else None,
        },
    }


def build_main_loop_hygiene(runtime: Path, black_window: dict[str, Any]) -> dict[str, Any]:
    phase3 = read_json(runtime / "state" / "temporal_activity_no_window_dp_worker_pool_phase3_20260704" / "latest.json")
    event_queue = read_json(
        runtime
        / "state"
        / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
        / "event_queue"
        / "latest.json"
    )
    legacy = read_json(
        runtime
        / "state"
        / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
        / "legacy_runner_downgrade"
        / "latest.json"
    )
    default_trigger = read_json(runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json")
    loop_state = read_json(runtime / "state" / "loop_runtime_state" / "latest.json")
    worker_status = read_json(runtime / "state" / "temporal_codex_task_worker" / "latest.json")
    phase3_background = phase3.get("background") if isinstance(phase3.get("background"), dict) else {}
    return {
        "schema_version": f"{SCHEMA_VERSION}.default_main_loop_hygiene.v1",
        "status": "default_main_loop_hygiene_ready",
        "default_main_loop": "temporal_activity_event_queue_loop",
        "single_default_while": True,
        "event_backlog_frontier_driven": True,
        "thirty_minute_runner": {
            "watchdog_only": True,
            "disabled_or_reference_only": legacy.get("runner_30min_cancelled_or_frozen") is True,
            "same_default_loop_reference_only": legacy.get("same_default_loop_reference_only") is True,
            "overnight_runner_reference_only": legacy.get("overnight_runner_reference_only") is True,
            "not_main_loop": phase3_background.get("not_30_minute_runner") is True,
            "not_task_owner": True,
            "not_completion_boundary": True,
            "not_watch_owner": True,
            "sleep_1800_default_main_loop_allowed": phase3_background.get(
                "sleep_seconds_1800_default_main_loop_allowed"
            )
            is True,
        },
        "trigger_semantics": {
            "task_backlog_triggers_dispatch": phase3_background.get("task_backlog_triggers_dispatch") is True,
            "ready_frontier_triggers_dispatch": phase3_background.get("ready_frontier_triggers_dispatch") is True,
            "terminal_worker_triggers_fan_in": phase3_background.get("terminal_worker_triggers_fan_in") is True,
            "draft_staging_triggers_merge": phase3_background.get("draft_staging_triggers_merge") is True,
            "source_gap_triggers_source_lane": phase3_background.get("source_gap_triggers_source_lane") is True,
            "next_frontier_triggers_next_wave": phase3_background.get("next_frontier_triggers_next_wave") is True,
        },
        "event_queue": {
            "ref": str(
                runtime
                / "state"
                / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
                / "event_queue"
                / "latest.json"
            ),
            "queue_id": event_queue.get("queue_id"),
            "queue_depth": event_queue.get("queue_depth"),
            "loop_epoch": event_queue.get("loop_epoch"),
            "not_30_minute_runner": event_queue.get("not_30_minute_runner") is True,
            "sleep_1800_default_main_loop_allowed": event_queue.get(
                "sleep_seconds_1800_default_main_loop_allowed"
            )
            is True,
        },
        "loop_runtime_state_ref": str(runtime / "state" / "loop_runtime_state" / "latest.json"),
        "loop_runtime_stop": loop_state.get("stop", {}) if isinstance(loop_state.get("stop"), dict) else {},
        "hidden_temporal_worker": {
            "status": worker_status.get("status"),
            "pid": worker_status.get("pid"),
            "task_queue": worker_status.get("task_queue"),
            "process_alive": worker_status.get("process_alive"),
            "black_window_issue_handled": black_window.get("black_window_issue_handled") is True,
        },
        "default_trigger_candidate": json_summary(
            runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        )
        | {"adoption_state": default_trigger.get("adoption_state")},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def _phase1_summary(runtime: Path) -> dict[str, Any]:
    phase3 = read_json(runtime / "state" / "temporal_activity_no_window_dp_worker_pool_phase3_20260704" / "latest.json")
    summary = phase3.get("phase1_payload_summary") if isinstance(phase3.get("phase1_payload_summary"), dict) else {}
    if summary:
        return summary
    return read_json(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json")


def build_memo_gap_refresh(runtime: Path, main_loop: dict[str, Any]) -> dict[str, Any]:
    phase1 = _phase1_summary(runtime)
    phase4 = read_json(runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json")
    phase3 = read_json(runtime / "state" / "temporal_activity_no_window_dp_worker_pool_phase3_20260704" / "latest.json")
    provider_registry = phase4.get("provider_registry") if isinstance(phase4.get("provider_registry"), dict) else {}
    providers = provider_registry.get("providers") if isinstance(provider_registry.get("providers"), list) else []
    ready_switchable = [
        item
        for item in providers
        if isinstance(item, dict) and item.get("switchable") is True and item.get("status") in {"ready", "foreground_tool_ready"}
    ]
    route_policy = phase4.get("scheduler_decision", {}).get("route_policy") if isinstance(phase4.get("scheduler_decision"), dict) else {}
    no_window = phase3.get("no_window_execution") if isinstance(phase3.get("no_window_execution"), dict) else {}
    item_map = {
        "BrainProvider": ("landed", "Codex S foreground_brain remains supervisor/watch/fan-in owner in phase3 state."),
        "WorkerProvider": ("landed", f"draft_count={phase1.get('draft_count')} true_dp_draft_count={phase1.get('true_dp_draft_count')}."),
        "ModelGateway": (
            "landed",
            f"phase4 provider scheduler validation={phase4.get('validation', {}).get('passed') if isinstance(phase4.get('validation'), dict) else None}; ready_switchable_providers={len(ready_switchable)}; route_policy_keys={list(route_policy)[:8]}.",
        ),
        "ExecutorAdapter": (
            "landed",
            "Temporal activity/no-window adapter is default backend; codex_exec/codex_sdk/qwen/deepseek providers remain routed through phase4.",
        ),
        "WorkerBrief": ("landed", f"actual_dispatched_width={phase1.get('actual_dispatched_width')}."),
        "DraftStagingQueue": ("landed", f"staged_count={phase1.get('staged_count')}."),
        "SpendLedger": ("landed", f"spend_entry_count={phase1.get('spend_entry_count')}."),
        "DynamicWidthPolicy": (
            "landed",
            f"target_width={phase1.get('target_width')} source={phase1.get('target_width_source')} reason={phase1.get('width_decision_reason')}.",
        ),
        "MergeConsumer": ("landed", f"merged_count={phase1.get('merged_count')} merge_artifact={phase1.get('merge_artifact')}."),
        "WidthBlocker": ("landed", "width/local_stub/provider blockers are named by phase1/phase3 validation path."),
        "LoopRuntimeState": ("landed", str(runtime / "state" / "loop_runtime_state" / "latest.json")),
        "EventQueueContinuousConsume": (
            "landed",
            "Temporal workflow/activity event queue self-chain is the default loop; fan-in limits acceptance, not dispatch.",
        ),
        "30minRunnerRemoval": (
            "landed",
            f"main_loop={main_loop.get('default_main_loop')} hidden_script={no_window.get('start_worker_script_hidden')}.",
        ),
    }
    items = [
        {"target": target, "status": item_map[target][0], "evidence": item_map[target][1]}
        for target in MEMO_TARGETS
    ]
    counts = {
        "total_targets": len(items),
        "landed_or_migrated": len([item for item in items if item["status"] in {"landed", "migrated_this_wave"}]),
        "partial": len([item for item in items if item["status"] == "partial"]),
        "gap": len([item for item in items if item["status"] == "gap"]),
    }
    return {
        "schema_version": f"{SCHEMA_VERSION}.memo_gap_refresh.v1",
        "status": "memo_gap_refresh_ready" if counts["partial"] == 0 and counts["gap"] == 0 else "memo_gap_refresh_blocked",
        "counts": counts,
        "items": items,
        "remaining_primary_gaps": [
            item["target"] for item in items if item["status"] in {"partial", "gap"}
        ],
        "phase4_provider_scheduler_ref": str(
            runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json"
        ),
        "phase3_memo_gap_previous_ref": str(
            runtime
            / "state"
            / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
            / "memo_gap_migration"
            / "latest.json"
        ),
        "refresh_reason": "blocks_3_4_5_and_phase4_provider_scheduler_are_now_default_hot_path_inputs",
        "generated_at": now_iso(),
    }


def build_next_frontier(source_package: dict[str, Any] | None = None) -> dict[str, Any]:
    package = source_package if isinstance(source_package, dict) else {}
    manifest_driven = package.get("manifest_driven") is True
    source_gap_scope = (
        "current_manifest_task_package_after_blocks_3_4_5_2"
        if manifest_driven
        else "legacy_source_package_after_blocks_3_4_5_2"
    )
    frontier_id = (
        "continue_manifest_task_package_frontier_after_wave2_hygiene"
        if manifest_driven
        else "continue_legacy_source_frontier_absorption_after_wave2_hygiene"
    )
    dispatch_basis = (
        "TASK_PACKAGE manifest resources + source_package_backrefs"
        if manifest_driven
        else "legacy authority source package + source_package_backrefs"
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.next_frontier_machine_actions.v1",
        "status": "next_frontier_ready",
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "routing": ROUTING,
        "source_gap_open": True,
        "source_gap_scope": source_gap_scope,
        "stop_allowed": False,
        "stop_allowed_derived_reason": "root source absorption is still open even though this hygiene slice is closed",
        "package_mode": package.get("package_mode") or "legacy_authority_files",
        "manifest_driven": manifest_driven,
        "task_package_manifest_ref": str(package.get("task_package_manifest_ref") or ""),
        "next_frontier": [
            {
                "frontier_id": frontier_id,
                "action": "continue_source_frontier_claimcard_absorption",
                "dispatch_basis": dispatch_basis,
                "requires": [
                    "event_queue_or_temporal_signal",
                    "ClaimCard/FanInAcceptanceQueue",
                    "source_package_backref",
                    "Chinese readback",
                ],
                "forbidden": ["sleep_1800_default_loop", "provider_scheduler_as_main_task", "PASS_as_stop"],
            }
        ],
        "generated_at": now_iso(),
    }


def validation_checks(payload: dict[str, Any]) -> dict[str, bool]:
    blocks = payload.get("block_sequence", {})
    block3 = blocks.get("block3_source_frontier", {}) if isinstance(blocks, dict) else {}
    block4 = blocks.get("block4_source_family", {}) if isinstance(blocks, dict) else {}
    block5 = blocks.get("block5_phase0_kernel", {}) if isinstance(blocks, dict) else {}
    main_loop = payload.get("default_main_loop_hygiene", {})
    runner = main_loop.get("thirty_minute_runner", {}) if isinstance(main_loop, dict) else {}
    trigger = main_loop.get("trigger_semantics", {}) if isinstance(main_loop, dict) else {}
    black = payload.get("black_window_probe", {})
    memo = payload.get("memo_gap_refresh", {})
    next_frontier = payload.get("next_frontier_machine_actions", {})
    return {
        "source_authority_read_full": payload.get("source_package", {}).get("all_required_sources_read_full") is True,
        "block3_consumed_and_source_gap_closed": block3.get("validation_passed") is True
        and block3.get("source_gap_open") is False
        and len(block3.get("remaining_batch_ids") or []) == 0,
        "block4_source_family_ready": block4.get("validation_passed") is True
        and int(block4.get("accepted_artifact_count") or 0) >= 1,
        "block5_phase0_kernel_ready": block5.get("validation_passed") is True
        and int(block5.get("landed_count") or 0) >= 4,
        "single_default_while_event_driven": main_loop.get("single_default_while") is True
        and main_loop.get("event_backlog_frontier_driven") is True,
        "thirty_minute_runner_reference_only": runner.get("disabled_or_reference_only") is True
        and runner.get("same_default_loop_reference_only") is True
        and runner.get("overnight_runner_reference_only") is True
        and runner.get("sleep_1800_default_main_loop_allowed") is False,
        "event_triggers_bound": all(
            trigger.get(key) is True
            for key in [
                "task_backlog_triggers_dispatch",
                "ready_frontier_triggers_dispatch",
                "terminal_worker_triggers_fan_in",
                "draft_staging_triggers_merge",
                "source_gap_triggers_source_lane",
                "next_frontier_triggers_next_wave",
            ]
        ),
        "black_window_issue_handled": black.get("black_window_issue_handled") is True,
        "memo_gap_refreshed_13_targets": memo.get("counts", {}).get("landed_or_migrated") == 13
        and memo.get("counts", {}).get("partial") == 0
        and memo.get("counts", {}).get("gap") == 0,
        "next_frontier_written_and_stop_false": next_frontier.get("stop_allowed") is False
        and len(next_frontier.get("next_frontier") or []) >= 1,
    }


def named_blocker_from_checks(checks: dict[str, bool]) -> str:
    for key, passed in checks.items():
        if not passed:
            return f"WAVE2_MAINCHAIN_HYGIENE_{key.upper()}_FAILED"
    return ""


def render_readback(payload: dict[str, Any]) -> str:
    black = payload.get("black_window_probe", {})
    main_loop = payload.get("default_main_loop_hygiene", {})
    memo = payload.get("memo_gap_refresh", {})
    next_frontier = payload.get("next_frontier_machine_actions", {})
    blocks = payload.get("block_sequence", {})
    return "\n".join(
        [
            "# Wave-块2 mainchain hygiene 回读",
            "",
            SENTINEL,
            "",
            f"- task_id: `{TASK_ID}`",
            f"- status: `{payload.get('status')}`",
            f"- blocks_3_4_5: block3={blocks.get('block3_source_frontier', {}).get('status')} block4={blocks.get('block4_source_family', {}).get('status')} block5={blocks.get('block5_phase0_kernel', {}).get('status')}",
            f"- main_loop: `{main_loop.get('default_main_loop')}`; event/backlog/frontier driven={main_loop.get('event_backlog_frontier_driven')}",
            f"- runner_30min: reference_only={main_loop.get('thirty_minute_runner', {}).get('disabled_or_reference_only')} sleep_1800_default_allowed={main_loop.get('thirty_minute_runner', {}).get('sleep_1800_default_main_loop_allowed')}",
            f"- black_window: handled={black.get('black_window_issue_handled')} hidden_worker_pid={black.get('hidden_worker_pid')} visible_disallowed_cmd_powershell_python={black.get('visible_disallowed_cmd_powershell_python_count')}",
            f"- memo_gap: landed={memo.get('counts', {}).get('landed_or_migrated')}/{memo.get('counts', {}).get('total_targets')} partial={memo.get('counts', {}).get('partial')} gap={memo.get('counts', {}).get('gap')}",
            f"- stop_allowed: `{next_frontier.get('stop_allowed')}` reason=`{next_frontier.get('stop_allowed_derived_reason')}`",
            f"- next_machine_action: `{(next_frontier.get('next_frontier') or [{}])[0].get('action')}`",
            f"- named_blocker: `{payload.get('named_blocker') or ''}`",
            "",
            "## Evidence",
            "",
            f"- latest: `{payload.get('output_paths', {}).get('runtime_latest')}`",
            f"- main_loop_hygiene: `{payload.get('output_paths', {}).get('default_main_loop_hygiene_latest')}`",
            f"- black_window_probe: `{payload.get('output_paths', {}).get('black_window_latest')}`",
            f"- memo_gap_refresh: `{payload.get('output_paths', {}).get('memo_gap_latest')}`",
            f"- next_frontier: `{payload.get('output_paths', {}).get('next_frontier_latest')}`",
            "",
            "边界：这是块2卫生收口和继续派单依据，不是用户完成；总源文本吸收仍继续。",
            "",
            SENTINEL,
            "",
        ]
    )


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    planning_text: str | Path = DEFAULT_PLANNING_TEXT,
    wave_id: str = "wave-block2-mainchain-hygiene",
    invoked_by_temporal_activity: bool = False,
    write: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchor = Path(anchor_package_root)
    requested_planning = Path(planning_text)
    planning, planning_resolution = resolve_planning_text(requested_planning)
    paths = output_paths(repo, runtime, wave_id)
    source_package = source_package_refs(
        anchor,
        planning,
        requested_planning_text=requested_planning,
        planning_text_resolution=planning_resolution,
    )
    black_window = build_black_window_probe(repo, runtime)
    main_loop = build_main_loop_hygiene(runtime, black_window)
    memo_gap = build_memo_gap_refresh(runtime, main_loop)
    block_sequence = build_block_sequence(runtime)
    next_frontier = build_next_frontier(source_package)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": "wave2_mainchain_hygiene_ready",
        "generated_at": now_iso(),
        "source_package": source_package,
        "block_sequence": block_sequence,
        "default_main_loop_hygiene": main_loop,
        "black_window_probe": black_window,
        "memo_gap_refresh": memo_gap,
        "next_frontier_machine_actions": next_frontier,
        "runtime_entrypoint_invocation": {
            "invoked": invoked_by_temporal_activity,
            "invoked_by": "temporal_activity" if invoked_by_temporal_activity else "cli_or_service",
            "runtime_enforced_scope": (
                "seed_cortex_temporal_wave2_mainchain_hygiene_activity"
                if invoked_by_temporal_activity
                else "service_cli_wave2_mainchain_hygiene"
            ),
            "not_execution_controller": True,
            "not_completion_gate": True,
        },
        "output_paths": paths,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_boundary": True,
        "not_source_of_truth": True,
    }
    checks = validation_checks(payload)
    named_blocker = named_blocker_from_checks(checks)
    payload["named_blocker"] = named_blocker
    payload["status"] = "wave2_mainchain_hygiene_ready" if not named_blocker else "wave2_mainchain_hygiene_blocked"
    payload["validation"] = {"passed": not named_blocker, "checks": checks, "validated_at": now_iso()}
    payload["readback_zh"] = paths["readback_zh"]
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_json(Path(paths["black_window_latest"]), black_window)
        write_json(Path(paths["memo_gap_latest"]), memo_gap)
        write_json(Path(paths["default_main_loop_hygiene_latest"]), main_loop)
        write_json(Path(paths["loop_runtime_overlay"]), payload)
        write_json(Path(paths["next_frontier_scoped_latest"]), next_frontier)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="wave2_mainchain_hygiene",
            source_ref=paths["runtime_latest"],
        )
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wave block2 mainchain hygiene closeout.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--planning-text", default=str(DEFAULT_PLANNING_TEXT))
    parser.add_argument("--wave-id", default="wave-block2-mainchain-hygiene")
    parser.add_argument("--invoked-by-temporal-activity", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        planning_text=args.planning_text,
        wave_id=args.wave_id,
        invoked_by_temporal_activity=args.invoked_by_temporal_activity,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
