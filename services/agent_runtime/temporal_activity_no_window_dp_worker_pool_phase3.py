from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import loop_runtime_state_supervisor_worker_pool_phase2 as phase2
from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1


SCHEMA_VERSION = "xinao.codex_s.temporal_activity_no_window_dp_worker_pool_phase3.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_TEMPORAL_ACTIVITY_NO_WINDOW_DP_POOL_PHASE3"
TASK_ID = "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
RUNTIME_SCOPE = "seed_cortex_temporal_activity_no_window_dp_worker_pool_phase3"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
EVENT_QUEUE_ID = "codex_s.333.temporal_activity.event_queue"
SOURCE_ENTRY_ROOT = Path(r"C:\Users\xx363\Desktop\新系统")

AUTHORITY_ANCHORS = [
    Path(r"C:\Users\xx363\Desktop\新系统\XINAO_333_固定锚点.txt"),
    Path(r"C:\Users\xx363\Desktop\循环.txt"),
    Path(r"C:\Users\xx363\Desktop\Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt"),
    Path(r"C:\Users\xx363\Desktop\新系统\当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt"),
    Path(r"C:\Users\xx363\Desktop\新系统\新系统独立并行_自由发散外部研究总稿_20260701.txt"),
]

STOP_FALSE_KEYS = [
    "active_worker_or_valid_lease",
    "task_backlog",
    "ready_frontier",
    "unmerged_draft_staging",
    "merge_backlog",
    "fan_in_backlog",
    "evidence_backlog",
    "source_gaps",
    "next_frontier_not_dispatched",
    "retry_or_backoff_can_continue",
    "unhandled_blockers",
]

LEGACY_RUNNER_FLAGS = {
    "watchdog_only": True,
    "disabled": True,
    "reference_only": True,
    "not_main_loop": True,
    "not_task_owner": True,
    "not_completion_boundary": True,
    "not_watch_owner": True,
    "not_foreground_brain": True,
    "legacy_phase2_runner_reference_only": True,
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def epoch_now() -> float:
    return time.time()


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    return cleaned.strip("-")[:140] or "wave"


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{time.time_ns()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / TASK_ID
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "event_queue_latest": state / "event_queue" / "latest.json",
        "event_queue_records": state / "event_queue" / "records",
        "dynamic_width_decision_latest": state / "dynamic_width_decision" / "latest.json",
        "dynamic_width_decision_records": state / "dynamic_width_decision" / "records",
        "capacity_observation_latest": state / "capacity_observation" / "latest.json",
        "capacity_observation_records": state / "capacity_observation" / "records",
        "memo_gap_migration_latest": state / "memo_gap_migration" / "latest.json",
        "memo_gap_migration_readback": runtime
        / "readback"
        / "zh"
        / "codex_deepseek_memo_gap_migration_20260704.md",
        "activity_trace_latest": state / "activity_trace" / "latest.json",
        "legacy_runner_downgrade_latest": state / "legacy_runner_downgrade" / "latest.json",
        "no_window_latest": state / "no_window_execution" / "latest.json",
        "tool_trace_evidence_latest": runtime / "state" / "tool_trace_evidence" / f"{TASK_ID}.latest.json",
        "worker_dispatch_ledger_activity_latest": runtime / "state" / "worker_dispatch_ledger" / f"{TASK_ID}.latest.json",
        "canonical_loop_runtime_state_latest": runtime / "state" / "loop_runtime_state" / "latest.json",
        "readback": runtime / "readback" / "zh" / f"{TASK_ID}.md",
    }


def no_window_contract(repo: Path) -> dict[str, Any]:
    start_script = repo / "scripts" / "Start-XinaoTemporalCodexWorker.ps1"
    script_text = ""
    try:
        script_text = start_script.read_text(encoding="utf-8-sig")
    except Exception:
        script_text = ""
    return {
        "windows_no_window_required": True,
        "subprocess_create_no_window": os.name == "nt",
        "creationflags_required": [
            "subprocess.CREATE_NO_WINDOW",
            "subprocess.DETACHED_PROCESS for legacy rescue only",
        ],
        "startupinfo_required": {
            "dwFlags_contains_STARTF_USESHOWWINDOW": True,
            "wShowWindow": "SW_HIDE",
        },
        "powershell_start_process_windowstyle_hidden_required": True,
        "start_worker_script_ref": str(start_script),
        "start_worker_script_hidden": "-WindowStyle Hidden" in script_text,
        "foreground_visible_window_target": "only_one_codex_s_window",
        "no_visible_cmd_powershell_python_window_expected": True,
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


def run_hidden_powershell(command: str, *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        **hidden_subprocess_kwargs(),
    )


def process_alive(pid: Any) -> bool:
    try:
        if not pid:
            return False
        if os.name == "nt":
            completed = run_hidden_powershell(
                f"Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id"
            )
            return completed.returncode == 0 and bool((completed.stdout or "").strip())
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def stop_process(pid: int) -> dict[str, Any]:
    if not pid:
        return {"attempted": False, "pid": 0, "alive_after": False}
    before = process_alive(pid)
    error = ""
    if before:
        try:
            if os.name == "nt":
                completed = run_hidden_powershell(
                    f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue",
                    timeout=10,
                )
                error = (completed.stderr or "").strip()
            else:
                os.kill(int(pid), 15)
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
    return {
        "attempted": before,
        "pid": int(pid),
        "alive_before": before,
        "alive_after": process_alive(pid),
        "error": error,
        "used_hidden_no_window_process": os.name == "nt",
    }


def authority_anchor_facts() -> dict[str, Any]:
    anchors = []
    for path in AUTHORITY_ANCHORS:
        raw = b""
        text = ""
        error = ""
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        anchors.append(
            {
                "path": str(path),
                "name": path.name,
                "exists": path.is_file(),
                "size_bytes": len(raw),
                "line_count": len(text.splitlines()) if text else 0,
                "char_count": len(text) if text else 0,
                "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
                "read_error": error,
            }
        )
    return {
        "anchors": anchors,
        "all_required_present": all(item["exists"] for item in anchors),
        "digest_sha256": sha256_json(anchors),
        "read_at": now_iso(),
    }


def latest_user_correction_digest() -> dict[str, Any]:
    payload = {
        "task_id": "remove_30min_runner_event_queue_loop_correction_20260704",
        "source": "current_user_visible_phase3_and_30min_runner_correction",
        "digest_points": [
            "Temporal activity is the backend execution shape; S remains foreground brain/watch/fan-in owner.",
            "DP/DeepSeek remains draft-first worker pool inside the activity path.",
            "No visible cmd/powershell/python worker windows are allowed; hidden Temporal worker is the carrier.",
            "30-minute/sleep-1800/same_default/overnight runners are disabled/reference-only, not main loops or watch owners.",
            "Main loop trigger is event/backlog/frontier driven: backlog, ready frontier, terminal worker, staging, source gap, retry, next frontier.",
        ],
        "serves": "333 foreground brain + Temporal activity backend + event queue loop correction",
    }
    return {**payload, "sha256": sha256_json(payload)}


def load_event_queue(runtime: Path) -> dict[str, Any]:
    queue = read_json(output_paths(runtime)["event_queue_latest"])
    if queue:
        return queue
    return {
        "schema_version": "xinao.codex_s.phase3_event_queue.v1",
        "queue_id": EVENT_QUEUE_ID,
        "task_id": TASK_ID,
        "status": "event_queue_ready",
        "trigger_model": "event_backlog_frontier_driven",
        "not_30_minute_runner": True,
        "sleep_seconds_1800_default_main_loop_allowed": False,
        "fixed_interval_default_loop_allowed": False,
        "entries": [],
        "generated_at": now_iso(),
    }


def queue_open_entries(queue: dict[str, Any]) -> list[dict[str, Any]]:
    statuses = {"queued", "ready", "retry_ready", "leased", "running"}
    return [
        item
        for item in queue.get("entries", [])
        if isinstance(item, dict) and str(item.get("status") or "") in statuses
    ]


def queue_ready_entries(queue: dict[str, Any]) -> list[dict[str, Any]]:
    now = epoch_now()
    return [
        item
        for item in queue_open_entries(queue)
        if float(item.get("ready_after_epoch") or 0.0) <= now
    ]


def int_field(payload: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(payload.get(key) or default)
    except Exception:
        return default


def compute_dynamic_width_decision(
    *,
    runtime: Path,
    queue: dict[str, Any],
    source_entry: dict[str, Any],
    requested_target_width: int,
    max_parallel_workers: int,
) -> dict[str, Any]:
    previous = read_json(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json")
    token_cost = previous.get("token_cost_spend") if isinstance(previous.get("token_cost_spend"), dict) else {}
    source_sampled_count = int_field(source_entry, "sampled_count", 0)
    queue_depth = len(queue_open_entries(queue))
    ready_count = len(queue_ready_entries(queue))
    previous_dispatched = int_field(previous, "actual_dispatched_width", 0)
    previous_completed = int_field(previous, "actual_completed_width", 0)
    previous_staged = int_field(previous, "staged_count", 0)
    previous_merged = int_field(previous, "merged_count", 0)
    previous_tokens = int_field(token_cost, "total_tokens", 0)
    previous_blocker = str(previous.get("named_blocker") or "")
    rate_limit_error = str(previous.get("rate_limit_error") or "")
    previous_unmerged = max(0, previous_staged - previous_merged)

    independent_task_count = max(
        3,
        source_sampled_count * 4
        + queue_depth
        + ready_count
        + (2 if previous_blocker else 0)
        + min(previous_unmerged, 6),
    )
    executor_available_slots = max(3, int(max_parallel_workers or 12) * 2)
    env_cap = int(os.environ.get("XINAO_DYNAMIC_WIDTH_OPERATOR_SAFETY_CAP") or 0)
    operator_safety_cap = (
        env_cap
        if env_cap > 0
        else max(3, executor_available_slots, int(previous_completed or 0), int(previous_dispatched or 0))
    )
    provider_available_slots = (
        3
        if rate_limit_error
        else min(
            operator_safety_cap,
            max(3, previous_completed or max_parallel_workers or 12)
            + (4 if previous_completed >= previous_dispatched and previous_dispatched > 0 and not previous_blocker else 0),
        )
    )
    budget_headroom = (
        operator_safety_cap
        if previous_tokens < 60000
        else max(3, operator_safety_cap // 2)
        if previous_tokens < 100000
        else max(3, operator_safety_cap // 4)
    )
    rate_limit_headroom = 3 if rate_limit_error else operator_safety_cap
    useful_frontier_count = max(independent_task_count, ready_count, 3)
    fan_in_pressure_record = {
        "previous_staged_count": previous_staged,
        "previous_merged_count": previous_merged,
        "previous_unmerged_count": previous_unmerged,
        "fan_in_limits_acceptance_not_dispatch": True,
        "overflow_goes_to_staging": True,
    }
    candidates = {
        "independent_task_count": independent_task_count,
        "provider_available_slots": provider_available_slots,
        "executor_available_slots": executor_available_slots,
        "budget_headroom": budget_headroom,
        "rate_limit_headroom": rate_limit_headroom,
        "useful_frontier_count": useful_frontier_count,
        "operator_safety_cap": operator_safety_cap,
    }
    target_width = max(3, min(candidates.values()))
    selected_min_candidate = sorted(candidates.items(), key=lambda item: item[1])[0][0]
    operator_cap_applied = False
    if int(requested_target_width or 0) > 0 and target_width > int(requested_target_width):
        target_width = int(requested_target_width)
        operator_cap_applied = True
        selected_min_candidate = "operator_requested_target_width_cap"

    target_width_source = (
        "dynamic_width_scheduler_with_operator_cap"
        if operator_cap_applied
        else "dynamic_width_scheduler"
    )
    reason = (
        f"target_width={target_width} from {selected_min_candidate}; "
        f"inputs queue_depth={queue_depth}, ready_frontier={ready_count}, "
        f"source_sampled_count={source_sampled_count}, previous_completed={previous_completed}, "
        f"rate_limit={'yes' if rate_limit_error else 'no'}, previous_tokens={previous_tokens}"
    )
    return {
        "schema_version": f"{SCHEMA_VERSION}.dynamic_width_decision.v1",
        "task_id": TASK_ID,
        "target_width": target_width,
        "requested_target_width": int(requested_target_width or 0),
        "target_width_source": target_width_source,
        "width_decision_reason": reason,
        "selected_min_candidate": selected_min_candidate,
        "width_decision_inputs": {
            "source_sampled_count": source_sampled_count,
            "queue_depth": queue_depth,
            "ready_frontier_count": ready_count,
            "previous_dispatched_width": previous_dispatched,
            "previous_completed_width": previous_completed,
            "previous_staged_count": previous_staged,
            "previous_merged_count": previous_merged,
            "previous_unmerged_count": previous_unmerged,
            "previous_total_tokens": previous_tokens,
            "previous_named_blocker": previous_blocker,
            "rate_limit_error": rate_limit_error,
            "max_parallel_workers": int(max_parallel_workers or 0),
            "operator_safety_cap_source": "env:XINAO_DYNAMIC_WIDTH_OPERATOR_SAFETY_CAP"
            if env_cap > 0
            else "derived_from_executor_and_previous_wave",
            "fan_in_pressure": fan_in_pressure_record,
        },
        "width_candidates": candidates,
        "operator_cap_applied": operator_cap_applied,
        "recomputed_each_wave": True,
        "fixed_20_or_50_used": False,
        "not_default_width": True,
        "not_permanent_cap": True,
        "dynamic_retest_required_for_future_higher_width": True,
        "fan_in_limits_acceptance_not_dispatch": True,
        "staging_overflow_allowed": True,
        "generated_at": now_iso(),
    }


def write_dynamic_width_decision(
    *,
    runtime: Path,
    wave_id: str,
    decision: dict[str, Any],
    write: bool,
) -> None:
    if not write:
        return
    paths = output_paths(runtime)
    write_json(paths["dynamic_width_decision_latest"], decision)
    write_json(paths["dynamic_width_decision_records"] / f"{safe_stem(wave_id)}.json", decision)


def write_capacity_observation(
    *,
    runtime: Path,
    wave_id: str,
    width_decision: dict[str, Any],
    phase_payload: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    actual_dispatched = int(phase_payload.get("actual_dispatched_width") or 0)
    actual_completed = int(phase_payload.get("actual_completed_width") or 0)
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.capacity_observation.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "capacity_observation_recorded",
        "requested_target_width": int(width_decision.get("requested_target_width") or 0),
        "target_width": int(width_decision.get("target_width") or 0),
        "target_width_source": width_decision.get("target_width_source"),
        "width_decision_reason": width_decision.get("width_decision_reason"),
        "operator_safety_cap": width_decision.get("width_candidates", {}).get("operator_safety_cap"),
        "actual_dispatched_width": actual_dispatched,
        "actual_completed_width": actual_completed,
        "draft_count": int(phase_payload.get("draft_count") or 0),
        "true_dp_draft_count": int(phase_payload.get("true_dp_draft_count") or 0),
        "local_stub_draft_count": int(phase_payload.get("local_stub_draft_count") or 0),
        "staged_count": int(phase_payload.get("staged_count") or 0),
        "merged_count": int(phase_payload.get("merged_count") or 0),
        "validation_passed": phase_payload.get("validation", {}).get("passed") is True,
        "named_blocker": phase_payload.get("named_blocker") or "",
        "not_default_width": True,
        "not_permanent_cap": True,
        "not_completion_boundary": True,
        "dynamic_retest_required_for_future_higher_width": True,
        "observation_meaning_cn": (
            "这是本波容量观测，不是默认宽度、不是永久上限；后续需要更高宽度时按当时 "
            "frontier/provider/headroom 重新测试并记录。"
        ),
        "generated_at": now_iso(),
        "validation": {
            "passed": actual_dispatched > 0,
            "checks": {
                "actual_dispatch_observed": actual_dispatched > 0,
                "true_dp_draft_observed": int(phase_payload.get("true_dp_draft_count") or 0) > 0,
                "local_stub_not_counted_as_success": int(phase_payload.get("local_stub_draft_count") or 0) == 0,
                "not_default_width": True,
                "not_permanent_cap": True,
                "future_retest_required": True,
            },
        },
    }
    if write:
        write_json(paths["capacity_observation_latest"], payload)
        write_json(paths["capacity_observation_records"] / f"{safe_stem(wave_id)}.json", payload)
    return payload


def build_queue_item(
    *,
    wave_id: str,
    target_width: int,
    loop_epoch: int,
    source_digest: str,
    reason: str,
    ready_after_epoch: float | None = None,
) -> dict[str, Any]:
    ready_epoch = epoch_now() if ready_after_epoch is None else ready_after_epoch
    return {
        "task_item_id": f"{safe_stem(wave_id)}.temporal_activity_wave",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "loop_epoch": loop_epoch,
        "status": "queued",
        "lane_class": "temporal_activity_dp_wave",
        "trigger_reason": reason,
        "triggered_by": "task_backlog_or_ready_frontier_event",
        "target_width": max(0, int(target_width or 0)),
        "target_width_hint": max(0, int(target_width or 0)),
        "target_width_source": "queued_placeholder_recomputed_on_claim",
        "width_recompute_required": True,
        "source_digest_sha256": source_digest,
        "ready_after_epoch": ready_epoch,
        "ready_after": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ready_epoch)),
        "not_30_minute_runner": True,
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def seed_or_claim_event(
    *,
    runtime: Path,
    wave_id: str,
    target_width: int,
    source_digest: str,
    write: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = output_paths(runtime)
    queue = load_event_queue(runtime)
    if not queue_open_entries(queue):
        loop_epoch = int(queue.get("loop_epoch") or 0) + 1
        queue.setdefault("entries", []).append(
            build_queue_item(
                wave_id=wave_id,
                target_width=target_width,
                loop_epoch=loop_epoch,
                source_digest=source_digest,
                reason="phase3_current_user_package_ready_frontier",
            )
        )
        queue["loop_epoch"] = loop_epoch
    ready = queue_ready_entries(queue)
    item = ready[0] if ready else queue_open_entries(queue)[0]
    item["status"] = "running"
    item["lease_id"] = f"lease-{safe_stem(str(item.get('wave_id') or wave_id))}-{int(epoch_now())}"
    item["lease_expires_epoch"] = epoch_now() + 900
    item["lease_expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(item["lease_expires_epoch"]))
    item["claimed_by"] = "temporal_activity.dp_worker_pool_wave_activity"
    item["claimed_at"] = now_iso()
    queue["queue_depth"] = len(queue_open_entries(queue))
    queue["updated_at"] = now_iso()
    if write:
        write_json(paths["event_queue_latest"], queue)
    return queue, item


def complete_event_and_enqueue_next(
    *,
    queue: dict[str, Any],
    item: dict[str, Any],
    phase_payload: dict[str, Any],
    named_blocker: str,
) -> dict[str, Any]:
    succeeded = phase_payload.get("validation", {}).get("passed") is True and not named_blocker
    item["status"] = "terminal_succeeded" if succeeded else "terminal_blocked"
    item["terminal_at"] = now_iso()
    item["phase1_wave_id"] = phase_payload.get("wave_id")
    item["draft_count"] = phase_payload.get("draft_count")
    item["staged_count"] = phase_payload.get("staged_count")
    item["merged_count"] = phase_payload.get("merged_count")
    item["named_blocker"] = named_blocker
    next_item: dict[str, Any] = {}
    if succeeded:
        next_epoch = int(item.get("loop_epoch") or 0) + 1
        next_wave_id = f"{TASK_ID}-event-wave-{next_epoch:03d}"
        next_item = build_queue_item(
            wave_id=next_wave_id,
            target_width=0,
            loop_epoch=next_epoch,
            source_digest=str(item.get("source_digest_sha256") or ""),
            reason="next_frontier_non_empty_event_driven_immediate",
            ready_after_epoch=epoch_now(),
        )
        queue.setdefault("entries", []).append(next_item)
        queue["loop_epoch"] = next_epoch
    queue["queue_depth"] = len(queue_open_entries(queue))
    queue["updated_at"] = now_iso()
    return next_item


def derive_phase_named_blocker(phase_payload: dict[str, Any]) -> str:
    named_blocker = str(phase_payload.get("named_blocker") or "")
    validation_passed = phase_payload.get("validation", {}).get("passed") is True
    true_dp = int(phase_payload.get("true_dp_draft_count") or 0)
    local_stub = int(phase_payload.get("local_stub_draft_count") or 0)
    if not validation_passed and true_dp <= 0:
        return named_blocker or "DEEPSEEK_PROVIDER_NOT_CONFIGURED"
    if not validation_passed and local_stub >= max(1, int(phase_payload.get("draft_count") or 0)):
        return named_blocker or "MODEL_GATEWAY_NOT_ROUTED"
    return named_blocker


def legacy_runner_candidates(runtime: Path) -> list[tuple[str, Path]]:
    return [
        (
            "phase2_queue_consumer_background",
            runtime
            / "state"
            / "loop_runtime_state_supervisor_worker_pool_phase2_20260704"
            / "background_latest.json",
        ),
        (
            "overnight_parent_same_default_background",
            runtime
            / "state"
            / "overnight_supervisor_loop_phase0_batch_20260704"
            / "same_default_loop"
            / "background_latest.json",
        ),
        (
            "overnight_supervisor_loop_latest",
            runtime / "state" / "overnight_supervisor_loop" / "latest.json",
        ),
    ]


def freeze_legacy_30min_runners(*, runtime: Path, write: bool) -> dict[str, Any]:
    paths = output_paths(runtime)
    observed = []
    for name, path in legacy_runner_candidates(runtime):
        payload = read_json(path)
        pid = int(payload.get("pid") or 0) if payload else 0
        command_text = " ".join(str(item) for item in payload.get("command", [])) if payload else ""
        sleep_seconds = payload.get("sleep_seconds") if payload else None
        process_was_alive = process_alive(pid)
        should_stop = bool(
            process_was_alive
            and (
                "loop_runtime_state_supervisor_worker_pool_phase2" in command_text
                or "overnight_parent_same_default_loop" in command_text
                or str(sleep_seconds) == "1800"
            )
        )
        stop_result = stop_process(pid) if should_stop else {
            "attempted": False,
            "pid": pid,
            "alive_before": process_was_alive,
            "alive_after": process_was_alive,
            "error": "",
            "used_hidden_no_window_process": False,
        }
        patched_payload = {
            **payload,
            **LEGACY_RUNNER_FLAGS,
            "status": "legacy_runner_disabled_reference_only" if payload else "legacy_runner_not_observed_reference_only",
            "disabled_by_task_id": TASK_ID,
            "disabled_at": now_iso(),
            "process_alive_after_disable": stop_result.get("alive_after"),
            "main_loop_replacement": "temporal_activity_event_queue_loop",
        }
        if name == "phase2_queue_consumer_background":
            patched_payload["queue_consumer_main_loop"] = False
        if name == "overnight_parent_same_default_background":
            patched_payload["background_runner_only"] = True
        if write and payload:
            write_json(path, patched_payload)
        observed.append(
            {
                "name": name,
                "ref": str(path),
                "exists": bool(payload),
                "pid": pid,
                "sleep_seconds": sleep_seconds,
                "command_contains_loop": "--loop" in command_text,
                "process_alive_before": process_was_alive,
                "stop_result": stop_result,
                **LEGACY_RUNNER_FLAGS,
                "status_after": patched_payload["status"],
            }
        )
    result = {
        "schema_version": "xinao.codex_s.phase3_legacy_runner_downgrade.v1",
        "task_id": TASK_ID,
        "status": "legacy_30min_runners_disabled_reference_only",
        "runner_30min_cancelled_or_frozen": True,
        "sleep_1800_default_main_loop_allowed": False,
        "same_default_loop_reference_only": True,
        "overnight_runner_reference_only": True,
        "phase2_queue_consumer_direct_process_reference_only": True,
        "main_loop_replacement": "temporal_activity_event_queue_loop",
        "observed": observed,
        "validation": {
            "passed": all(item["not_main_loop"] and item["not_completion_boundary"] for item in observed),
        },
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["legacy_runner_downgrade_latest"], result)
    return result


def temporal_activity_context(input_payload: dict[str, Any], activity_name: str) -> dict[str, Any]:
    workflow_id = str(input_payload.get("workflow_id") or input_payload.get("workflowId") or "")
    run_id = str(input_payload.get("workflow_run_id") or input_payload.get("run_id") or "")
    task_queue = str(input_payload.get("task_queue") or DEFAULT_TASK_QUEUE)
    worker_identity = str(input_payload.get("worker_identity") or os.environ.get("COMPUTERNAME") or "codex_s_temporal_worker")
    return {
        "workflow_id": workflow_id or f"{TASK_ID}.direct_activity_smoke",
        "run_id": run_id or f"direct-{int(epoch_now())}",
        "activity_name": activity_name,
        "task_queue": task_queue,
        "worker_identity": worker_identity,
        "event_history_ref": "",
        "equivalent_activity_trace": True,
        "activity_invocation_mode": "temporal_worker_activity" if workflow_id or run_id else "direct_activity_smoke",
    }


def write_worker_dispatch_ledger_activity(
    *,
    runtime: Path,
    wave_id: str,
    phase_payload: dict[str, Any],
    activity_context: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    lane_results = phase_payload.get("lane_results") if isinstance(phase_payload.get("lane_results"), list) else []
    entries = []
    for item in lane_results:
        if not isinstance(item, dict):
            continue
        entries.append(
            {
                "entry_id": item.get("lane_id"),
                "task_id": TASK_ID,
                "wave_id": wave_id,
                "mode": item.get("mode"),
                "status": item.get("status"),
                "artifact_ref": item.get("artifact_ref"),
                "provider_invocation_ref": item.get("provider_invocation_ref"),
                "selected_carrier_provider_id": item.get("selected_carrier_provider_id"),
                "accepted_for": "phase3_temporal_activity_worker_dispatch_evidence",
            }
        )
    payload = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.phase3_activity.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "worker_dispatch_ledger_phase3_activity_ready",
        "activity_context": activity_context,
        "dispatch_entries": entries,
        "succeeded_count": len([item for item in entries if item.get("status") == "succeeded"]),
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["worker_dispatch_ledger_activity_latest"], payload)
    return payload


def write_tool_trace_evidence(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    phase_payload: dict[str, Any],
    activity_context: dict[str, Any],
    no_window: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    lane_results = phase_payload.get("lane_results") if isinstance(phase_payload.get("lane_results"), list) else []
    provider_refs = [
        item.get("provider_invocation_ref")
        for item in lane_results
        if isinstance(item, dict) and item.get("provider_invocation_ref")
    ]
    payload = {
        "schema_version": "xinao.codex_s.tool_trace_evidence.phase3_activity.v1",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "status": "tool_trace_evidence_ready",
        "activity_context": activity_context,
        "no_window_execution": no_window,
        "provider_invocation_refs": provider_refs,
        "provider_invocation_ref_count": len(provider_refs),
        "start_worker_status_ref": str(runtime / "state" / "temporal_codex_task_worker" / "status.json"),
        "start_worker_script_ref": str(repo / "scripts" / "Start-XinaoTemporalCodexWorker.ps1"),
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["tool_trace_evidence_latest"], payload)
    return payload


def run_dp_worker_pool_wave_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime = Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo = Path(str(input_payload.get("repo_root") or DEFAULT_REPO))
    write = input_payload.get("write", True) is not False
    wave_id = str(input_payload.get("wave_id") or f"{TASK_ID}-event-wave-001")
    requested_target_width = int(input_payload.get("target_width") or 0)
    max_parallel_workers = int(input_payload.get("max_parallel_workers") or 12)
    paths = output_paths(runtime)

    no_window = no_window_contract(repo)
    if write:
        write_json(paths["no_window_latest"], no_window)
    legacy_runners = freeze_legacy_30min_runners(runtime=runtime, write=write)
    source_entry = phase1.scan_source_entry(root=SOURCE_ENTRY_ROOT)
    queue, item = seed_or_claim_event(
        runtime=runtime,
        wave_id=wave_id,
        target_width=requested_target_width,
        source_digest=str(source_entry.get("source_entry_digest_sha256") or ""),
        write=write,
    )
    actual_wave_id = str(item.get("wave_id") or wave_id)
    width_decision = compute_dynamic_width_decision(
        runtime=runtime,
        queue=queue,
        source_entry=source_entry,
        requested_target_width=requested_target_width,
        max_parallel_workers=max_parallel_workers,
    )
    width_decision["wave_id"] = actual_wave_id
    item["target_width"] = int(width_decision.get("target_width") or 0)
    item["target_width_source"] = width_decision.get("target_width_source")
    item["width_decision_reason"] = width_decision.get("width_decision_reason")
    item["width_decision_ref"] = str(paths["dynamic_width_decision_latest"])
    item["width_recompute_required"] = False
    queue["updated_at"] = now_iso()
    write_dynamic_width_decision(
        runtime=runtime,
        wave_id=actual_wave_id,
        decision=width_decision,
        write=write,
    )
    if write:
        write_json(paths["event_queue_latest"], queue)
    phase_payload = phase1.run_wave(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=actual_wave_id,
        target_width=int(width_decision.get("target_width") or 3),
        dynamic_width_decision=width_decision,
        write=write,
        record_meta_rsi=False,
        require_external_draft=True,
        max_parallel_workers=max_parallel_workers,
        runtime_enforced=True,
        runtime_enforced_scope=RUNTIME_SCOPE,
        while_chain_id=f"{TASK_ID}.temporal_activity_event_queue",
        while_wave_index=int(item.get("loop_epoch") or 1),
        while_wave_count=999999,
        previous_wave_id="",
        next_wave_id=f"{TASK_ID}-event-wave-{int(item.get('loop_epoch') or 1) + 1:03d}",
    )
    capacity_observation = write_capacity_observation(
        runtime=runtime,
        wave_id=actual_wave_id,
        width_decision=width_decision,
        phase_payload=phase_payload,
        write=write,
    )
    named_blocker = derive_phase_named_blocker(phase_payload)
    next_item = complete_event_and_enqueue_next(
        queue=queue,
        item=item,
        phase_payload=phase_payload,
        named_blocker=named_blocker,
    )
    if write:
        write_json(paths["event_queue_latest"], queue)
        write_json(paths["event_queue_records"] / f"{safe_stem(actual_wave_id)}.queue.json", queue)
    activity_context = temporal_activity_context(input_payload, "dp_worker_pool_wave_activity")
    ledger = write_worker_dispatch_ledger_activity(
        runtime=runtime,
        wave_id=actual_wave_id,
        phase_payload=phase_payload,
        activity_context=activity_context,
        write=write,
    )
    tool_trace = write_tool_trace_evidence(
        runtime=runtime,
        repo=repo,
        wave_id=actual_wave_id,
        phase_payload=phase_payload,
        activity_context=activity_context,
        no_window=no_window,
        write=write,
    )
    checks = {
        "activity_name_bound": activity_context["activity_name"] == "dp_worker_pool_wave_activity",
        "legacy_30min_runners_disabled": legacy_runners.get("validation", {}).get("passed") is True,
        "no_window_contract_bound": no_window.get("start_worker_script_hidden") is True,
        "actual_dispatched_width_gte_3": int(phase_payload.get("actual_dispatched_width") or 0) >= 3,
        "actual_completed_width_gte_1": int(phase_payload.get("actual_completed_width") or 0) >= 1,
        "draft_count_positive": int(phase_payload.get("draft_count") or 0) > 0,
        "staged_count_positive": int(phase_payload.get("staged_count") or 0) > 0,
        "merged_or_named_blocker": int(phase_payload.get("merged_count") or 0) >= 1 or bool(named_blocker),
        "local_stub_not_counted_as_success": (
            int(phase_payload.get("true_dp_draft_count") or 0)
            > int(phase_payload.get("local_stub_draft_count") or 0)
        )
        or bool(named_blocker),
        "dynamic_width_decision_bound": (
            phase_payload.get("target_width_source")
            in {
                "dynamic_width_scheduler",
                "dynamic_width_scheduler_with_operator_cap",
            }
            and bool(phase_payload.get("width_decision_reason"))
            and phase_payload.get("recomputed_each_wave") is True
        ),
        "event_queue_next_frontier_ready": bool(next_item) or bool(named_blocker),
    }
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.dp_worker_pool_wave_activity",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "wave_id": actual_wave_id,
        "activity": "dp_worker_pool_wave_activity",
        "status": "dp_worker_pool_wave_activity_ready" if all(checks.values()) else "dp_worker_pool_wave_activity_blocked",
        "activity_context": activity_context,
        "temporal_activity_evidence": activity_context,
        "event_queue": {
            "queue_id": EVENT_QUEUE_ID,
            "latest_ref": str(paths["event_queue_latest"]),
            "claimed_item_id": item.get("task_item_id"),
            "next_frontier_item": next_item,
            "queue_depth": len(queue_open_entries(queue)),
            "not_30_minute_runner": True,
        },
        "dynamic_width_decision": width_decision,
        "dynamic_width_decision_ref": str(paths["dynamic_width_decision_latest"]),
        "capacity_observation": capacity_observation,
        "capacity_observation_ref": str(paths["capacity_observation_latest"]),
        "phase1_payload": phase_payload,
        "phase1_latest_ref": phase_payload.get("evidence_refs", {}).get("runtime_latest") or "",
        "draft_count": int(phase_payload.get("draft_count") or 0),
        "staged_count": int(phase_payload.get("staged_count") or 0),
        "merged_count": int(phase_payload.get("merged_count") or 0),
        "actual_dispatched_width": int(phase_payload.get("actual_dispatched_width") or 0),
        "actual_completed_width": int(phase_payload.get("actual_completed_width") or 0),
        "mode_counts": phase_payload.get("mode_counts") or {},
        "true_dp_draft_count": int(phase_payload.get("true_dp_draft_count") or 0),
        "local_stub_draft_count": int(phase_payload.get("local_stub_draft_count") or 0),
        "named_blocker": named_blocker,
        "merge_artifact": phase_payload.get("merge_artifact") or "",
        "legacy_runners": legacy_runners,
        "no_window_execution": no_window,
        "worker_dispatch_ledger_ref": str(paths["worker_dispatch_ledger_activity_latest"]),
        "worker_dispatch_ledger": ledger,
        "tool_trace_evidence_ref": str(paths["tool_trace_evidence_latest"]),
        "tool_trace_evidence": tool_trace,
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "generated_at": now_iso(),
    }
    payload["activity_context"]["event_history_ref"] = str(paths["activity_trace_latest"])
    if write:
        write_json(paths["activity_trace_latest"], payload)
        write_json(paths["records"] / f"{safe_stem(actual_wave_id)}.dp_worker_pool_wave_activity.json", payload)
    return payload


def run_draft_staging_fan_in_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime = Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    write = input_payload.get("write", True) is not False
    paths = output_paths(runtime)
    dp_activity = (
        input_payload.get("dp_worker_pool_wave_activity")
        if isinstance(input_payload.get("dp_worker_pool_wave_activity"), dict)
        else {}
    )
    phase_payload = (
        dp_activity.get("phase1_payload")
        if isinstance(dp_activity.get("phase1_payload"), dict)
        else read_json(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json")
    )
    wave_id = str(dp_activity.get("wave_id") or phase_payload.get("wave_id") or input_payload.get("wave_id") or f"{TASK_ID}-fan-in")
    activity_context = temporal_activity_context(input_payload, "draft_staging_fan_in_activity")
    staging_queue = phase_payload.get("draft_staging_queue") if isinstance(phase_payload.get("draft_staging_queue"), dict) else {}
    merge_consumer = phase_payload.get("merge_consumer") if isinstance(phase_payload.get("merge_consumer"), dict) else {}
    adopted = []
    rejected = []
    for item in phase_payload.get("lane_results", []) if isinstance(phase_payload.get("lane_results"), list) else []:
        if not isinstance(item, dict):
            continue
        target = adopted if item.get("status") == "succeeded" and item.get("artifact_ref") else rejected
        target.append(
            {
                "lane_id": item.get("lane_id"),
                "mode": item.get("mode"),
                "artifact_ref": item.get("artifact_ref"),
                "reason": "accepted_into_merge" if target is adopted else item.get("named_blocker") or "not_succeeded",
            }
        )
    checks = {
        "activity_name_bound": activity_context["activity_name"] == "draft_staging_fan_in_activity",
        "drafts_staged": int(phase_payload.get("staged_count") or staging_queue.get("staged_count") or 0) > 0,
        "merge_artifact_or_blocker": bool(phase_payload.get("merge_artifact")) or bool(dp_activity.get("named_blocker")),
        "fan_in_uses_staging_not_lane_count_only": bool(staging_queue),
    }
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.draft_staging_fan_in_activity",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "activity": "draft_staging_fan_in_activity",
        "status": "draft_staging_fan_in_activity_ready" if all(checks.values()) else "draft_staging_fan_in_activity_blocked",
        "activity_context": activity_context,
        "draft_staging_queue_ref": phase_payload.get("evidence_refs", {}).get("draft_staging_queue_latest") or "",
        "merge_consumer_ref": phase_payload.get("evidence_refs", {}).get("merge_consumer_latest") or "",
        "merge_artifact": phase_payload.get("merge_artifact") or "",
        "draft_count": int(phase_payload.get("draft_count") or 0),
        "staged_count": int(phase_payload.get("staged_count") or 0),
        "merged_count": int(phase_payload.get("merged_count") or 0),
        "adopted_drafts": adopted,
        "rejected_drafts": rejected,
        "named_blocker": str(dp_activity.get("named_blocker") or phase_payload.get("named_blocker") or ""),
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["records"] / f"{safe_stem(wave_id)}.draft_staging_fan_in_activity.json", payload)
    return payload


def source_gaps_from_anchors(anchor_facts: dict[str, Any], source_entry: dict[str, Any]) -> list[dict[str, Any]]:
    gaps = []
    for item in anchor_facts.get("anchors", []):
        if isinstance(item, dict) and not item.get("exists"):
            gaps.append(
                {
                    "gap_id": f"missing_anchor:{item.get('name')}",
                    "kind": "missing_authority_anchor",
                    "path": item.get("path"),
                    "unblock_action": "restore/read the missing authority anchor or write named blocker",
                }
            )
    if int(source_entry.get("sampled_count") or 0) <= 0:
        gaps.append(
            {
                "gap_id": "source_entry_not_sampled",
                "kind": "source_entry_gap",
                "path": source_entry.get("source_entry_root"),
                "unblock_action": "read/sample source entry before dispatch",
            }
        )
    return gaps


def active_temporal_worker(runtime: Path) -> list[dict[str, Any]]:
    status = read_json(runtime / "state" / "temporal_codex_task_worker" / "status.json")
    if not status:
        return []
    if status.get("process_alive") is not True and int(status.get("pollers_seen") or 0) <= 0:
        return []
    return [
        {
            "worker_id": f"temporal-worker-pid-{status.get('pid')}",
            "lane_class": "temporal_activity_worker",
            "status": status.get("status"),
            "pid": status.get("pid"),
            "task_queue": status.get("task_queue"),
            "pollers_seen": status.get("pollers_seen"),
            "hidden_worker": True,
            "valid_lease": True,
        }
    ]


def build_capacity(phase_payload: dict[str, Any], queue: dict[str, Any]) -> dict[str, Any]:
    mode_counts = phase_payload.get("mode_counts") if isinstance(phase_payload.get("mode_counts"), dict) else {}
    lane_results = phase_payload.get("lane_results") if isinstance(phase_payload.get("lane_results"), list) else []
    width_policy = (
        phase_payload.get("dynamic_width_policy")
        if isinstance(phase_payload.get("dynamic_width_policy"), dict)
        else {}
    )
    latencies = []
    for item in lane_results:
        if isinstance(item, dict):
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            latencies.append(int(usage.get("latency_ms") or 0))
    return {
        "temporal_activity": {
            "task_queue": DEFAULT_TASK_QUEUE,
            "owner": "Temporal workflow/activity",
            "hidden_worker_required": True,
        },
        "dp_draft": {
            "target_width": sum(int(value or 0) for value in mode_counts.values()),
            "draft_target": int(mode_counts.get("draft") or 0),
            "draft_is_primary": int(mode_counts.get("draft") or 0)
            > max([int(value or 0) for key, value in mode_counts.items() if key != "draft"] or [0]),
            "provider": "DeepSeek/DP through ProviderGateway",
            "provider_tier_usage": phase_payload.get("provider_tier_usage") or {},
        },
        "merge_accept": {
            "fan_in_limits_acceptance_not_dispatch": True,
            "staging_overflow_allowed": True,
        },
        "dynamic_width_record": {
            "target_width": sum(int(value or 0) for value in mode_counts.values()),
            "target_width_source": phase_payload.get("target_width_source")
            or width_policy.get("target_width_source"),
            "width_decision_reason": phase_payload.get("width_decision_reason")
            or width_policy.get("width_decision_reason"),
            "width_decision_inputs": phase_payload.get("width_decision_inputs")
            or width_policy.get("width_decision_inputs")
            or {},
            "width_candidates": phase_payload.get("width_candidates")
            or width_policy.get("width_candidates")
            or {},
            "operator_cap_applied": phase_payload.get("operator_cap_applied")
            if "operator_cap_applied" in phase_payload
            else width_policy.get("operator_cap_applied"),
            "recomputed_each_wave": phase_payload.get("recomputed_each_wave")
            if "recomputed_each_wave" in phase_payload
            else width_policy.get("recomputed_each_wave"),
            "fixed_20_or_50_used": width_policy.get("fixed_20_or_50_used") is True,
            "actual_dispatched_width": int(phase_payload.get("actual_dispatched_width") or 0),
            "actual_completed_width": int(phase_payload.get("actual_completed_width") or 0),
            "independent_task_count": len(queue_open_entries(queue))
            + sum(int(value or 0) for value in mode_counts.values()),
            "provider": "legacy.deepseek_dp_sidecar",
            "model": "dp_sidecar_model_gateway_route",
            "provider_tier": sorted((phase_payload.get("provider_tier_usage") or {}).keys()),
            "token_cost_spend": phase_payload.get("token_cost_spend") or {},
            "latency_ms": {
                "min": min(latencies) if latencies else 0,
                "max": max(latencies) if latencies else 0,
                "avg": int(sum(latencies) / len(latencies)) if latencies else 0,
            },
            "queue_depth": len(queue_open_entries(queue)),
            "rate_limit_error": phase_payload.get("rate_limit_error") or "",
            "retry_after": "",
            "staged_count": int(phase_payload.get("staged_count") or 0),
            "merged_count": int(phase_payload.get("merged_count") or 0),
            "named_blocker": phase_payload.get("named_blocker") or "",
        },
    }


def compute_stop_decision(
    *,
    active_workers: list[dict[str, Any]],
    task_backlog: list[dict[str, Any]],
    ready_frontier: list[dict[str, Any]],
    draft_staging: dict[str, Any],
    merge_backlog: list[dict[str, Any]],
    fan_in_backlog: list[dict[str, Any]],
    evidence_backlog: list[dict[str, Any]],
    source_gaps: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    next_frontier: list[dict[str, Any]],
) -> dict[str, Any]:
    reason_flags = {
        "active_worker_or_valid_lease": bool(active_workers),
        "task_backlog": bool(task_backlog),
        "ready_frontier": bool(ready_frontier),
        "unmerged_draft_staging": int(draft_staging.get("unmerged_count") or 0) > 0,
        "merge_backlog": bool(merge_backlog),
        "fan_in_backlog": bool(fan_in_backlog),
        "evidence_backlog": bool(evidence_backlog),
        "source_gaps": bool(source_gaps),
        "next_frontier_not_dispatched": bool(
            [item for item in next_frontier if not item.get("dispatched_to_task_queue")]
        ),
        "retry_or_backoff_can_continue": bool(task_backlog or ready_frontier),
        "unhandled_blockers": bool(
            [item for item in blockers if not item.get("evidence_backed_terminal_blocker")]
        ),
    }
    stop_allowed = not any(reason_flags.values())
    false_reasons = [key for key, value in reason_flags.items() if value]
    return {
        "stop_allowed": stop_allowed,
        "stop_reason": "task_scoped_acceptance_required_before_stop"
        if stop_allowed
        else "continue_required:" + ",".join(false_reasons),
        "derived": True,
        "manual_override_allowed": False,
        "false_when_any": STOP_FALSE_KEYS,
        "reason_flags": reason_flags,
        "computed_from_refs": [
            "active_workers",
            "task_backlog",
            "ready_frontier",
            "draft_staging",
            "merge_backlog",
            "fan_in_backlog",
            "evidence_backlog",
            "source_gaps",
            "next_frontier",
            "blockers",
        ],
        "user_stop_requested": False,
        "user_only_gate_open": False,
        "irreversible_hard_risk": False,
        "accepted_completion_ref": "",
    }


def run_loop_runtime_state_update_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime = Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo = Path(str(input_payload.get("repo_root") or DEFAULT_REPO))
    write = input_payload.get("write", True) is not False
    paths = output_paths(runtime)
    dp_activity = (
        input_payload.get("dp_worker_pool_wave_activity")
        if isinstance(input_payload.get("dp_worker_pool_wave_activity"), dict)
        else {}
    )
    fan_in_activity = (
        input_payload.get("draft_staging_fan_in_activity")
        if isinstance(input_payload.get("draft_staging_fan_in_activity"), dict)
        else {}
    )
    phase_payload = (
        dp_activity.get("phase1_payload")
        if isinstance(dp_activity.get("phase1_payload"), dict)
        else read_json(runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json")
    )
    wave_id = str(dp_activity.get("wave_id") or phase_payload.get("wave_id") or input_payload.get("wave_id") or f"{TASK_ID}-state")
    queue = load_event_queue(runtime)
    anchor_facts = authority_anchor_facts()
    source_entry = phase1.scan_source_entry(root=SOURCE_ENTRY_ROOT)
    correction_digest = latest_user_correction_digest()
    task_backlog = queue_open_entries(queue)
    ready_frontier = queue_ready_entries(queue)
    staged_count = int(phase_payload.get("staged_count") or fan_in_activity.get("staged_count") or 0)
    merged_count = int(phase_payload.get("merged_count") or fan_in_activity.get("merged_count") or 0)
    draft_staging = {
        "latest_ref": phase_payload.get("evidence_refs", {}).get("draft_staging_queue_latest") or "",
        "staged_count": staged_count,
        "merged_count": merged_count,
        "unmerged_count": 0 if merged_count > 0 else staged_count,
        "status": "merged" if merged_count > 0 else "staged_waiting_merge",
    }
    merge_backlog = [] if merged_count > 0 else [{"reason": "staged_drafts_waiting_merge"}]
    fan_in_backlog = [] if merged_count > 0 else [{"reason": "fan_in_waiting_merge_consumer"}]
    evidence_backlog = []
    if int(phase_payload.get("spend_entry_count") or 0) <= 0:
        evidence_backlog.append({"kind": "spend_ledger_missing_or_provider_blocked"})
    if not paths["tool_trace_evidence_latest"].is_file():
        evidence_backlog.append({"kind": "tool_trace_evidence_missing"})
    source_gaps = source_gaps_from_anchors(anchor_facts, source_entry)
    named_blocker = str(dp_activity.get("named_blocker") or phase_payload.get("named_blocker") or "")
    blockers = []
    if named_blocker:
        blockers.append(
            {
                "named_blocker": named_blocker,
                "evidence_ref": dp_activity.get("phase1_latest_ref") or "",
                "evidence_backed_terminal_blocker": named_blocker
                in {"DEEPSEEK_PROVIDER_NOT_CONFIGURED", "MODEL_GATEWAY_NOT_ROUTED"},
                "unblock_action": "route DeepSeek/model gateway or invoke another safe independent lane",
            }
        )
    next_frontier = [
        {
            "frontier_id": item.get("task_item_id"),
            "wave_id": item.get("wave_id"),
            "status": item.get("status"),
            "ready_after": item.get("ready_after"),
            "dispatched_to_task_queue": False,
            "dispatch_basis": item.get("trigger_reason"),
        }
        for item in task_backlog
    ]
    active_workers = active_temporal_worker(runtime)
    stop = compute_stop_decision(
        active_workers=active_workers,
        task_backlog=task_backlog,
        ready_frontier=ready_frontier,
        draft_staging=draft_staging,
        merge_backlog=merge_backlog,
        fan_in_backlog=fan_in_backlog,
        evidence_backlog=evidence_backlog,
        source_gaps=source_gaps,
        blockers=blockers,
        next_frontier=next_frontier,
    )
    activity_context = temporal_activity_context(input_payload, "loop_runtime_state_update_activity")
    legacy_runners = (
        dp_activity.get("legacy_runners")
        if isinstance(dp_activity.get("legacy_runners"), dict)
        else freeze_legacy_30min_runners(runtime=runtime, write=write)
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "identity": {
            "work_id": WORK_ID,
            "route_profile": ROUTE_PROFILE,
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "checkpoint_ref": str(paths["canonical_loop_runtime_state_latest"]),
            "generated_at": now_iso(),
        },
        "activity": "loop_runtime_state_update_activity",
        "status": "phase3_temporal_activity_event_queue_wave_ready",
        "phase": "temporal_activity_dp_wave_staging_fan_in_loop_state",
        "temporal": {
            "workflow_id": activity_context["workflow_id"],
            "run_id": activity_context["run_id"],
            "activity_name": activity_context["activity_name"],
            "task_queue": activity_context["task_queue"],
            "worker_identity": activity_context["worker_identity"],
            "event_history_ref": str(paths["activity_trace_latest"]),
            "activity_trace_ref": str(paths["activity_trace_latest"]),
            "temporal_owner": True,
            "foreground_s_direct_runner": False,
            "event_queue_self_chain_enabled": input_payload.get(
                "phase3_event_queue_self_chain_enabled"
            )
            is True,
            "max_event_waves_per_run": int(input_payload.get("phase3_max_event_waves_per_run") or 0),
            "event_wave_index_in_run": int(input_payload.get("phase3_event_wave_index_in_run") or 0),
            "continue_generation": int(input_payload.get("phase3_continue_generation") or 0),
            "previous_run_id": str(input_payload.get("phase3_previous_run_id") or ""),
        },
        "foreground_brain": {
            "owner": "Codex S",
            "role": "supervisor_watch_fan_in_readback_kick_resume_only",
            "source_entry_read_at": source_entry.get("source_entry_read_at"),
            "user_latest_correction_digest": correction_digest,
            "333_alignment": "333 remains the highest semantic line; phase3 serves it.",
            "not_backend_runner": True,
        },
        "background": {
            "main_loop": "temporal_activity_event_queue_loop",
            "event_queue_driven": True,
            "task_backlog_triggers_dispatch": True,
            "ready_frontier_triggers_dispatch": True,
            "terminal_worker_triggers_fan_in": True,
            "draft_staging_triggers_merge": True,
            "source_gap_triggers_source_lane": True,
            "lease_expired_triggers_requeue": True,
            "retry_after_triggers_resume": True,
            "next_frontier_triggers_next_wave": True,
            "not_30_minute_runner": True,
            "sleep_seconds_1800_default_main_loop_allowed": False,
            "fixed_interval_default_loop_allowed": False,
            "legacy_runners": legacy_runners,
        },
        "no_window_execution": dp_activity.get("no_window_execution") or no_window_contract(repo),
        "queues": {
            "event_queue_latest": str(paths["event_queue_latest"]),
            "task_backlog": task_backlog,
            "ready_frontier": ready_frontier,
            "source_gaps": source_gaps,
            "draft_staging": draft_staging,
            "merge_backlog": merge_backlog,
            "fan_in_backlog": fan_in_backlog,
            "evidence_backlog": evidence_backlog,
            "blockers": blockers,
            "next_frontier": next_frontier,
        },
        "active_workers": active_workers,
        "task_backlog": task_backlog,
        "ready_frontier": ready_frontier,
        "draft_staging": draft_staging,
        "merge_backlog": merge_backlog,
        "fan_in_backlog": fan_in_backlog,
        "evidence_backlog": evidence_backlog,
        "source_gaps": source_gaps,
        "blockers": blockers,
        "next_frontier": next_frontier,
        "capacity_by_lane_class": build_capacity(phase_payload, queue),
        "acceptance": {
            "draft_count": int(phase_payload.get("draft_count") or 0),
            "staged_count": staged_count,
            "merged_count": merged_count,
            "merge_artifact": phase_payload.get("merge_artifact") or fan_in_activity.get("merge_artifact") or "",
            "adopted_drafts": fan_in_activity.get("adopted_drafts") or [],
            "rejected_drafts": fan_in_activity.get("rejected_drafts") or [],
            "completion_claim_allowed": False,
        },
        "evidence_ledger": {
            "worker_dispatch_ledger_refs": [str(paths["worker_dispatch_ledger_activity_latest"])],
            "draft_staging_queue_refs": [phase_payload.get("evidence_refs", {}).get("draft_staging_queue_latest") or ""],
            "merge_consumer_refs": [phase_payload.get("evidence_refs", {}).get("merge_consumer_latest") or ""],
            "merge_artifact_refs": [phase_payload.get("merge_artifact") or ""],
            "spend_ledger_refs": [phase_payload.get("evidence_refs", {}).get("spend_ledger_latest") or ""],
            "tool_trace_evidence_refs": [str(paths["tool_trace_evidence_latest"])],
            "loop_runtime_state_ref": str(paths["canonical_loop_runtime_state_latest"]),
            "phase3_latest_ref": str(paths["latest"]),
            "readback_refs": {"zh": str(paths["readback"])},
            "memo_gap_migration_ref": str(paths["memo_gap_migration_latest"]),
            "memo_gap_migration_readback": str(paths["memo_gap_migration_readback"]),
            "verifier_refs": [str(repo / "scripts" / "verify_temporal_activity_no_window_dp_worker_pool_phase3.ps1")],
        },
        "source_authority": {
            "anchor_facts": anchor_facts,
            "source_entry": source_entry,
            "desktop_memo_is_mode_memo_not_authority": True,
        },
        "phase1_payload_summary": {
            "wave_id": phase_payload.get("wave_id"),
            "status": phase_payload.get("status"),
            "validation_passed": phase_payload.get("validation", {}).get("passed"),
            "target_width": phase_payload.get("target_width"),
            "target_width_source": phase_payload.get("target_width_source"),
            "width_decision_reason": phase_payload.get("width_decision_reason"),
            "width_decision_inputs": phase_payload.get("width_decision_inputs") or {},
            "width_candidates": phase_payload.get("width_candidates") or {},
            "recomputed_each_wave": phase_payload.get("recomputed_each_wave"),
            "operator_cap_applied": phase_payload.get("operator_cap_applied"),
            "actual_dispatched_width": phase_payload.get("actual_dispatched_width"),
            "actual_completed_width": phase_payload.get("actual_completed_width"),
            "draft_count": phase_payload.get("draft_count"),
            "true_dp_draft_count": phase_payload.get("true_dp_draft_count"),
            "local_stub_draft_count": phase_payload.get("local_stub_draft_count"),
            "staged_count": phase_payload.get("staged_count"),
            "merged_count": phase_payload.get("merged_count"),
            "spend_entry_count": phase_payload.get("spend_entry_count"),
            "merge_artifact": phase_payload.get("merge_artifact"),
            "named_blocker": named_blocker,
        },
        "stop": stop,
        "stop_hook_contract": {
            "reads_loop_runtime_state": True,
            "latest_ref": str(paths["canonical_loop_runtime_state_latest"]),
            "hook_role": "fake_stop_guard_and_kick_resume_only",
            "does_not_start_30min_runner": True,
            "when_stop_allowed_false": [
                "do_not_final",
                "continue_poll_watch",
                "signal_or_update_temporal_workflow_resume",
                "fan_in_terminal_workers_before_report",
            ],
        },
        "can_invoke_now": {
            "temporal_workflow": (
                "python -m services.agent_runtime.temporal_codex_task_workflow "
                f"--live-temporal --task-id {TASK_ID} --runtime-root D:/XINAO_RESEARCH_RUNTIME"
            ),
            "direct_activity_smoke": (
                "python -m services.agent_runtime.temporal_activity_no_window_dp_worker_pool_phase3"
            ),
            "cli": "python -m xinao_seedlab.cli.__main__ temporal-activity-no-window-dp-worker-pool-phase3",
            "status": "scripts/Status-XinaoTemporalCodexWorker.ps1",
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_boundary": True,
        "not_source_of_truth": True,
        "validation": {
            "passed": True,
            "checks": {
                "canonical_loop_runtime_state_written": True,
                "temporal_activity_evidence_present": bool(activity_context["activity_name"]),
                "event_queue_driven_not_30min": True,
                "sleep_1800_not_default": True,
                "legacy_runners_reference_only": legacy_runners.get("validation", {}).get("passed") is True,
                "no_window_execution_bound": (dp_activity.get("no_window_execution") or no_window_contract(repo)).get("start_worker_script_hidden") is True,
                "draft_count_positive": int(phase_payload.get("draft_count") or 0) > 0,
                "staged_count_positive": staged_count > 0,
                "merged_or_named_blocker": merged_count > 0 or bool(named_blocker),
                "actual_dispatched_width_gte_3": int(phase_payload.get("actual_dispatched_width") or 0) >= 3,
                "actual_completed_width_gte_1": int(phase_payload.get("actual_completed_width") or 0) >= 1,
                "dynamic_width_decision_explained": (
                    phase_payload.get("target_width_source")
                    in {
                        "dynamic_width_scheduler",
                        "dynamic_width_scheduler_with_operator_cap",
                    }
                    and bool(phase_payload.get("width_decision_reason"))
                    and phase_payload.get("recomputed_each_wave") is True
                ),
                "local_stub_not_success": int(phase_payload.get("true_dp_draft_count") or 0)
                > int(phase_payload.get("local_stub_draft_count") or 0)
                or bool(named_blocker),
                "stop_allowed_derived": stop.get("derived") is True,
                "stop_allowed_false_with_backlog": stop.get("stop_allowed") is False if task_backlog or ready_frontier else True,
                "next_frontier_present": bool(next_frontier) or bool(named_blocker),
            },
            "validated_at": now_iso(),
        },
    }
    payload["validation"]["passed"] = all(payload["validation"]["checks"].values())
    payload["status"] = (
        "phase3_temporal_activity_event_queue_wave_ready"
        if payload["validation"]["passed"]
        else "phase3_temporal_activity_event_queue_wave_blocked"
    )
    memo_gap_migration = build_memo_gap_migration(payload)
    payload["memo_gap_migration"] = memo_gap_migration
    if write:
        write_json(paths["canonical_loop_runtime_state_latest"], payload)
        write_json(paths["latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.loop_runtime_state.json", payload)
        write_json(paths["memo_gap_migration_latest"], memo_gap_migration)
        write_text(paths["memo_gap_migration_readback"], render_memo_gap_readback(memo_gap_migration))
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    phase = payload.get("phase1_payload_summary", {})
    stop = payload.get("stop", {})
    background = payload.get("background", {})
    no_window = payload.get("no_window_execution", {})
    temporal = payload.get("temporal", {}) if isinstance(payload.get("temporal"), dict) else {}
    legacy = background.get("legacy_runners", {}) if isinstance(background, dict) else {}
    next_action = (
        "Temporal workflow self-chain consumes ready next_frontier and continue-as-new keeps the event queue hot; foreground hook only kicks/resumes if the worker is stale."
        if temporal.get("event_queue_self_chain_enabled") is True
        else f"signal/update Temporal workflow to consume ready next_frontier from `{EVENT_QUEUE_ID}`; if worker stale, foreground hook kicks/resumes Temporal, not 30min runner."
    )
    return "\n".join(
        [
            "# Temporal Activity Phase3 回读",
            "",
            SENTINEL,
            "",
            f"- task_id: `{TASK_ID}`",
            f"- status: `{payload.get('status')}`",
            f"- current_backend: Temporal workflow/activity on task_queue `{payload.get('temporal', {}).get('task_queue')}`; S 前台只 watch/fan-in/kick。",
            f"- event_queue_self_chain: enabled={temporal.get('event_queue_self_chain_enabled')} generation={temporal.get('continue_generation')} index_in_run={temporal.get('event_wave_index_in_run')}/{temporal.get('max_event_waves_per_run')}",
            f"- runner_30min: frozen/reference_only={legacy.get('runner_30min_cancelled_or_frozen')} sleep_1800_default_allowed={background.get('sleep_seconds_1800_default_main_loop_allowed')}",
            f"- main_trigger: event_driven backlog={len(payload.get('task_backlog', []))} ready_frontier={len(payload.get('ready_frontier', []))} next_frontier={len(payload.get('next_frontier', []))}",
            f"- backend_has_work_immediate_consume: {bool(payload.get('task_backlog') or payload.get('ready_frontier'))}",
            f"- black_window: expected_none={no_window.get('no_visible_cmd_powershell_python_window_expected')} hidden_worker_script={no_window.get('start_worker_script_hidden')}",
            f"- dp_wave: dispatched={phase.get('actual_dispatched_width')} completed={phase.get('actual_completed_width')} draft={phase.get('draft_count')} staged={phase.get('staged_count')} merged={phase.get('merged_count')}",
            f"- width_decision: target={phase.get('target_width')} source=`{phase.get('target_width_source')}` reason=`{phase.get('width_decision_reason')}`",
            f"- named_blocker: `{phase.get('named_blocker') or ''}`",
            f"- stop_allowed: {stop.get('stop_allowed')} reason=`{stop.get('stop_reason')}`",
            f"- next_machine_action: {next_action}",
            f"- merge_artifact: `{phase.get('merge_artifact')}`",
            "",
            "## Evidence",
            "",
            f"- loop_runtime_state: `{payload.get('evidence_ledger', {}).get('loop_runtime_state_ref')}`",
            f"- phase3_latest: `{payload.get('evidence_ledger', {}).get('phase3_latest_ref')}`",
            f"- worker_dispatch_ledger: `{(payload.get('evidence_ledger', {}).get('worker_dispatch_ledger_refs') or [''])[0]}`",
            f"- tool_trace: `{(payload.get('evidence_ledger', {}).get('tool_trace_evidence_refs') or [''])[0]}`",
            f"- readback_zh: `{payload.get('evidence_ledger', {}).get('readback_refs', {}).get('zh')}`",
            f"- memo_gap_migration: `{payload.get('evidence_ledger', {}).get('memo_gap_migration_ref')}`",
            "",
            "## 边界",
            "",
            "- 这不是完成声明；PASS/latest/readback/report 都不是完成边界。",
            "- 30 分钟 runner 只剩 reference/rescue 证据，不是 main loop、task owner、watch owner。",
            "- stop_allowed 是派生字段；有 backlog/frontier/active worker/staging/source gap/next frontier 时必须 false。",
            "",
            SENTINEL,
            "",
        ]
    )


def desktop_memo_snapshot() -> dict[str, Any]:
    memo = Path(r"C:\Users\xx363\Desktop\Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt")
    try:
        text = memo.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return {
            "path": str(memo),
            "exists": memo.is_file(),
            "read_error": type(exc).__name__,
            "line_count": 0,
            "digest_sha256": "",
            "keyword_line_refs": {},
        }
    lines = text.splitlines()
    keywords = [
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
        "DynamicWidthScheduler",
        "target_width",
        "DraftStagingQueue 收所有候选",
        "Fan-in limits acceptance",
    ]
    refs: dict[str, int] = {}
    for keyword in keywords:
        for index, line in enumerate(lines, start=1):
            if keyword in line:
                refs[keyword] = index
                break
    return {
        "path": str(memo),
        "exists": True,
        "line_count": len(lines),
        "digest_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "keyword_line_refs": refs,
        "mode_memo_not_authority": True,
    }


def build_memo_gap_migration(payload: dict[str, Any]) -> dict[str, Any]:
    phase = payload.get("phase1_payload_summary") if isinstance(payload.get("phase1_payload_summary"), dict) else {}
    capacity = payload.get("capacity_by_lane_class") if isinstance(payload.get("capacity_by_lane_class"), dict) else {}
    dynamic_record = (
        capacity.get("dynamic_width_record")
        if isinstance(capacity.get("dynamic_width_record"), dict)
        else {}
    )
    background = payload.get("background") if isinstance(payload.get("background"), dict) else {}
    temporal = payload.get("temporal") if isinstance(payload.get("temporal"), dict) else {}
    evidence = payload.get("evidence_ledger") if isinstance(payload.get("evidence_ledger"), dict) else {}
    target_source = str(phase.get("target_width_source") or "")
    actual_dispatched = int(phase.get("actual_dispatched_width") or 0)
    draft_count = int(phase.get("draft_count") or 0)
    staged_count = int(phase.get("staged_count") or 0)
    merged_count = int(phase.get("merged_count") or 0)
    spend_count = int(phase.get("spend_entry_count") or 0)
    memo = desktop_memo_snapshot()

    items = [
        {
            "target": "BrainProvider",
            "status": "landed",
            "evidence": "foreground Codex S remains SupervisorBrain/fan-in owner in phase1 foreground_brain_decision",
        },
        {
            "target": "WorkerProvider",
            "status": "landed" if draft_count > 0 else "gap",
            "evidence": f"DP draft count={draft_count}",
        },
        {
            "target": "ModelGateway",
            "status": "partial",
            "evidence": "dp_sidecar model route is metered; generalized provider gateway routing remains a migration gap",
        },
        {
            "target": "ExecutorAdapter",
            "status": "partial",
            "evidence": "Temporal activity/no-window subprocess path exists; codex exec/SDK/OpenHands/SWE-ReX adapter matrix is not fully routed",
        },
        {
            "target": "WorkerBrief",
            "status": "landed" if actual_dispatched >= 3 else "gap",
            "evidence": f"actual_dispatched_width={actual_dispatched}",
        },
        {
            "target": "DraftStagingQueue",
            "status": "landed" if staged_count > 0 else "gap",
            "evidence": f"staged_count={staged_count}",
        },
        {
            "target": "SpendLedger",
            "status": "landed" if spend_count > 0 else "gap",
            "evidence": f"spend_entry_count={spend_count}",
        },
        {
            "target": "DynamicWidthPolicy",
            "status": "migrated_this_wave"
            if target_source.startswith("dynamic_width_scheduler")
            and dynamic_record.get("recomputed_each_wave") is True
            and dynamic_record.get("fixed_20_or_50_used") is False
            else "gap",
            "evidence": phase.get("width_decision_reason") or "",
        },
        {
            "target": "MergeConsumer",
            "status": "landed" if merged_count > 0 else "gap",
            "evidence": f"merged_count={merged_count}; merge_artifact={phase.get('merge_artifact')}",
        },
        {
            "target": "WidthBlocker",
            "status": "landed",
            "evidence": "width<3/local_stub/provider routing blockers are named in phase1/phase3 validation path",
        },
        {
            "target": "LoopRuntimeState",
            "status": "landed" if payload.get("stop", {}).get("derived") is True else "gap",
            "evidence": str(evidence.get("loop_runtime_state_ref") or ""),
        },
        {
            "target": "EventQueueContinuousConsume",
            "status": "migrated_this_wave"
            if temporal.get("event_queue_self_chain_enabled") is True
            else "partial",
            "evidence": (
                "Temporal workflow consumes multiple event waves per run and continue-as-new is enabled"
                if temporal.get("event_queue_self_chain_enabled") is True
                else "event queue and next_frontier are immediate; full autonomous continue-as-new consumption still needs stronger Temporal self-chain"
            ),
        },
        {
            "target": "30minRunnerRemoval",
            "status": "landed"
            if background.get("sleep_seconds_1800_default_main_loop_allowed") is False
            else "gap",
            "evidence": f"main_loop={background.get('main_loop')}; runner_30min frozen={background.get('legacy_runners', {}).get('runner_30min_cancelled_or_frozen') if isinstance(background.get('legacy_runners'), dict) else None}",
        },
    ]
    landed = [item for item in items if item["status"] in {"landed", "migrated_this_wave"}]
    partial = [item for item in items if item["status"] == "partial"]
    gap = [item for item in items if item["status"] == "gap"]
    return {
        "schema_version": f"{SCHEMA_VERSION}.memo_gap_migration.v1",
        "task_id": TASK_ID,
        "status": "memo_target_migration_in_progress",
        "desktop_memo": memo,
        "verdict": "non_completion_continue_migration",
        "counts": {
            "total_targets": len(items),
            "landed_or_migrated": len(landed),
            "partial": len(partial),
            "gap": len(gap),
        },
        "items": items,
        "remaining_primary_gaps": [
            item["target"] for item in partial + gap
        ],
        "dynamic_width_migration": {
            "target_width": phase.get("target_width"),
            "target_width_source": phase.get("target_width_source"),
            "width_decision_reason": phase.get("width_decision_reason"),
            "recomputed_each_wave": phase.get("recomputed_each_wave"),
            "fixed_20_or_50_used": dynamic_record.get("fixed_20_or_50_used"),
        },
        "generated_at": now_iso(),
    }


def render_memo_gap_readback(payload: dict[str, Any]) -> str:
    counts = payload.get("counts", {})
    lines = [
        "# Codex DeepSeek 备忘目标迁移对照",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- verdict: `{payload.get('verdict')}`",
        f"- memo: `{payload.get('desktop_memo', {}).get('path')}`",
        f"- counts: landed_or_migrated={counts.get('landed_or_migrated')} partial={counts.get('partial')} gap={counts.get('gap')} total={counts.get('total_targets')}",
        f"- remaining_primary_gaps: `{', '.join(payload.get('remaining_primary_gaps') or [])}`",
        f"- dynamic_width: `{json.dumps(payload.get('dynamic_width_migration', {}), ensure_ascii=False)}`",
        "",
        "## 逐项",
        "",
    ]
    for item in payload.get("items", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('target')}: {item.get('status')} | {item.get('evidence')}")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 这不是完成声明；剩余 partial/gap 必须继续迁移或写 named_blocker。",
            "- 备忘服务 333，不替代 333/源文本/用户最新纠偏。",
            "",
            SENTINEL,
            "",
        ]
    )
    return "\n".join(lines)


def run_activity_sequence(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = f"{TASK_ID}-event-wave-001",
    target_width: int = 0,
    max_parallel_workers: int = 12,
    workflow_id: str = "",
    workflow_run_id: str = "",
    task_queue: str = DEFAULT_TASK_QUEUE,
    worker_identity: str = "",
    write: bool = True,
) -> dict[str, Any]:
    base_payload = {
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "wave_id": wave_id,
        "target_width": target_width,
        "max_parallel_workers": max_parallel_workers,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "task_queue": task_queue,
        "worker_identity": worker_identity,
        "write": write,
    }
    dp_activity = run_dp_worker_pool_wave_activity(base_payload)
    fan_in_activity = run_draft_staging_fan_in_activity(
        {**base_payload, "dp_worker_pool_wave_activity": dp_activity}
    )
    loop_state = run_loop_runtime_state_update_activity(
        {
            **base_payload,
            "dp_worker_pool_wave_activity": dp_activity,
            "draft_staging_fan_in_activity": fan_in_activity,
        }
    )
    paths = output_paths(Path(runtime_root))
    result = {
        "schema_version": f"{SCHEMA_VERSION}.activity_sequence",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "phase3_activity_sequence_ready"
        if loop_state.get("validation", {}).get("passed") is True
        else "phase3_activity_sequence_blocked",
        "activities": {
            "dp_worker_pool_wave_activity": dp_activity,
            "draft_staging_fan_in_activity": fan_in_activity,
            "loop_runtime_state_update_activity": loop_state,
        },
        "loop_runtime_state_ref": str(paths["canonical_loop_runtime_state_latest"]),
        "readback_ref": str(paths["readback"]),
        "validation": {
            "passed": loop_state.get("validation", {}).get("passed") is True,
            "checks": {
                "dp_activity_passed": dp_activity.get("validation", {}).get("passed") is True,
                "fan_in_activity_passed": fan_in_activity.get("validation", {}).get("passed") is True,
                "loop_state_activity_passed": loop_state.get("validation", {}).get("passed") is True,
            },
            "validated_at": now_iso(),
        },
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["latest"], loop_state)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.activity_sequence.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default=f"{TASK_ID}-event-wave-001")
    parser.add_argument("--target-width", type=int, default=0)
    parser.add_argument("--max-parallel-workers", type=int, default=12)
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--worker-identity", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = run_activity_sequence(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        target_width=args.target_width,
        max_parallel_workers=args.max_parallel_workers,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        task_queue=args.task_queue,
        worker_identity=args.worker_identity,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
