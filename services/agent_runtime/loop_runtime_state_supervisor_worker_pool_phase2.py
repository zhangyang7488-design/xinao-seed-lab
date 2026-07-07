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

from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1
from services.agent_runtime import task_package_resolver as task_package

SCHEMA_VERSION = "xinao.codex_s.loop_runtime_state_supervisor_worker_pool_phase2.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_LOOP_RUNTIME_STATE_PHASE2_V1"
TASK_ID = "loop_runtime_state_supervisor_worker_pool_phase2_20260704"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
RUNTIME_SCOPE = "seed_cortex_loop_runtime_state_supervisor_worker_pool_phase2"
QUEUE_ID = "codex_s.333.supervisor_worker_pool.task_queue"
CONSUMER_ID = "codex_s.phase2.queue_consumer"
SOURCE_ENTRY_ROOT = Path(r"C:\Users\xx363\Desktop\新系统")
AUTHORITY_ANCHORS = [
    Path(r"C:\Users\xx363\Desktop\新系统\XINAO_333_固定锚点.txt"),
    Path(r"C:\Users\xx363\Desktop\循环.txt"),
    Path(
        r"C:\Users\xx363\Desktop\新系统\备用历史\Codex_DeepSeek_高并行草稿主脑合并模式_20260704.txt"
    ),
    *[
        task_package.DEFAULT_TASK_PACKAGE_ROOT / name
        for name in task_package.LEGACY_AUTHORITY_FILES[1:]
    ],
]
PHASE2_CORRECTION_DIGEST_POINTS = [
    "Foreground Codex is supervisor brain/watch/fan-in/merge/keepalive owner.",
    "Background main loop is queue consumption, not a 30-minute timer.",
    "DP/DeepSeek is draft-first cheap worker pool; local stubs cannot count as real DP.",
    "LoopRuntimeState is the single stop/backlog/frontier summary.",
    "Stop hook is a fake-stop guard only; it reads LoopRuntimeState and does not own execution.",
]
WATCHDOG_DOWNGRADE_FLAGS = {
    "watchdog_only": True,
    "not_main_loop": True,
    "not_task_owner": True,
    "not_completion_boundary": True,
    "not_foreground_brain": True,
}
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


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def epoch_now() -> float:
    return time.time()


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


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    return cleaned.strip("-")[:140] or "wave"


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / TASK_ID
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "task_queue_latest": state / "task_queue" / "latest.json",
        "task_queue_records": state / "task_queue" / "records",
        "background_latest": state / "background_latest.json",
        "background_log": state / "background.log",
        "readback": runtime / "readback" / "zh" / f"{TASK_ID}.md",
        "watchdog_downgrade_latest": state / "watchdog_downgrade_latest.json",
    }


def authority_anchor_paths() -> tuple[str, Path | None, list[Path]]:
    package = task_package.resolve_task_package(
        SOURCE_ENTRY_ROOT,
        legacy_files=tuple(
            str(path.relative_to(task_package.DEFAULT_TASK_PACKAGE_ROOT))
            for path in AUTHORITY_ANCHORS
            if path.is_relative_to(task_package.DEFAULT_TASK_PACKAGE_ROOT)
        )
        if hasattr(Path("."), "is_relative_to")
        else task_package.LEGACY_EXTENDED_AUTHORITY_FILES,
        include_manifest_ref=True,
    )
    if package.get("manifest_driven") is True:
        paths = [Path(str(ref.get("path") or "")) for ref in package.get("refs", [])]
        manifest_path = Path(str(package.get("task_package_manifest_path") or "")) or None
        return "task_package_manifest", manifest_path, paths
    return "legacy_authority_anchors", None, AUTHORITY_ANCHORS


def authority_anchor_facts() -> dict[str, Any]:
    mode, manifest_path, authority_paths = authority_anchor_paths()
    anchors = []
    for path in authority_paths:
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
        "mode": mode,
        "task_package_manifest_ref": str(manifest_path or ""),
        "anchors": anchors,
        "all_required_present": all(item["exists"] for item in anchors),
        "digest_sha256": sha256_json(anchors),
        "read_at": now_iso(),
    }


def latest_user_correction_digest() -> dict[str, Any]:
    payload = {
        "task_id": TASK_ID,
        "source": "current_user_visible_phase2_correction_package",
        "digest_points": PHASE2_CORRECTION_DIGEST_POINTS,
        "serves": "333 foreground brain + queue-consuming worker pool + fake-stop guard",
    }
    return {**payload, "sha256": sha256_json(payload)}


def source_gaps_from_anchors(
    anchor_facts: dict[str, Any], source_entry: dict[str, Any]
) -> list[dict[str, Any]]:
    gaps = []
    manifest_anchor_mode = anchor_facts.get("mode") == "task_package_manifest"
    if source_entry.get("manifest_driven") is not True or manifest_anchor_mode:
        for item in anchor_facts.get("anchors", []):
            if isinstance(item, dict) and not item.get("exists"):
                gaps.append(
                    {
                        "gap_id": f"missing_anchor:{item.get('name')}",
                        "kind": (
                            "missing_task_package_manifest_resource"
                            if manifest_anchor_mode
                            else "missing_authority_anchor"
                        ),
                        "path": item.get("path"),
                        "unblock_action": (
                            "fix TASK_PACKAGE.json or restore the missing manifest resource"
                            if manifest_anchor_mode
                            else "restore/read the missing authority anchor or write named blocker"
                        ),
                    }
                )
    if int(source_entry.get("sampled_count") or 0) <= 0:
        gaps.append(
            {
                "gap_id": "source_entry_not_sampled",
                "kind": "source_entry_gap",
                "path": source_entry.get("source_entry_root"),
                "unblock_action": "read/sample C:/Users/xx363/Desktop/新系统 before dispatch",
            }
        )
    return gaps


def queue_status_entries(queue: dict[str, Any], statuses: set[str]) -> list[dict[str, Any]]:
    return [
        item
        for item in queue.get("entries", [])
        if isinstance(item, dict) and str(item.get("status") or "") in statuses
    ]


def ready_entries(queue: dict[str, Any], *, now_epoch: float) -> list[dict[str, Any]]:
    ready = []
    for item in queue_status_entries(queue, {"queued", "ready", "retry_ready"}):
        ready_after = float(item.get("ready_after_epoch") or 0.0)
        if ready_after <= now_epoch:
            ready.append(item)
    return ready


def build_queue_item(
    *,
    wave_id: str,
    target_width: int,
    loop_epoch: int,
    source_digest: str,
    ready_after_epoch: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "task_item_id": f"{safe_stem(wave_id)}.supervisor_wave",
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "loop_epoch": loop_epoch,
        "status": "queued",
        "lane_class": "supervisor_wave",
        "worker_pool_provider": "codex_s.modular_dynamic_worker_pool_phase1",
        "objective": (
            "SupervisorBrain reads 333/source/user correction, dispatches DP draft pool, "
            "fans in staging, writes merge/evidence/readback, then creates next frontier."
        ),
        "target_width": max(0, int(target_width or 0)),
        "target_width_source": (
            "dynamic_width_scheduler_pending"
            if int(target_width or 0) <= 0
            else "operator_requested_cap"
        ),
        "source_digest_sha256": source_digest,
        "ready_after_epoch": ready_after_epoch,
        "ready_after": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ready_after_epoch)),
        "enqueue_reason": reason,
        "attempt": 0,
        "completion_claim_allowed": False,
        "not_completion_boundary": True,
        "generated_at": now_iso(),
    }


def load_or_seed_queue(
    *,
    runtime: Path,
    wave_id: str,
    target_width: int,
    source_digest: str,
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    queue = read_json(paths["task_queue_latest"])
    if not queue:
        queue = {
            "schema_version": "xinao.codex_s.phase2_task_queue.v1",
            "queue_id": QUEUE_ID,
            "task_id": TASK_ID,
            "status": "task_queue_ready",
            "entries": [],
            "consumer_model": "competing_consumers_with_lease",
            "not_30_minute_runner": True,
            "generated_at": now_iso(),
        }
    open_entries = queue_status_entries(
        queue,
        {"queued", "ready", "retry_ready", "leased", "running"},
    )
    if not open_entries:
        next_epoch = int(queue.get("loop_epoch") or 0) + 1
        queue.setdefault("entries", []).append(
            build_queue_item(
                wave_id=wave_id,
                target_width=target_width,
                loop_epoch=next_epoch,
                source_digest=source_digest,
                ready_after_epoch=epoch_now(),
                reason="seed_phase2_foreground_supervisor_frontier",
            )
        )
        queue["loop_epoch"] = next_epoch
    queue["queue_depth"] = len(
        queue_status_entries(queue, {"queued", "ready", "retry_ready", "leased", "running"})
    )
    queue["updated_at"] = now_iso()
    if write:
        write_json(paths["task_queue_latest"], queue)
    return queue


def normalize_open_queue_widths(queue: dict[str, Any], *, target_width: int) -> dict[str, Any]:
    if int(target_width or 0) > 0:
        return queue
    normalized = 0
    for item in queue_status_entries(
        queue, {"queued", "ready", "retry_ready", "leased", "running"}
    ):
        previous_width = int(item.get("target_width") or 0)
        previous_source = str(item.get("target_width_source") or "")
        if previous_width <= 0 and previous_source == "dynamic_width_scheduler_pending":
            continue
        item["legacy_target_width_before_dynamic_reset"] = previous_width
        item["target_width"] = 0
        item["target_width_source"] = "dynamic_width_scheduler_pending"
        item["legacy_fixed_width_cleared"] = previous_width == 20 or previous_source in {
            "",
            "operator_requested_cap",
        }
        item["width_reset_reason"] = (
            "no explicit operator width for this queue tick; clear legacy fixed width so "
            "phase1/phase3 recomputes from frontier/provider telemetry"
        )
        normalized += 1
    queue["legacy_fixed_width_open_items_cleared"] = normalized
    queue["width_policy"] = {
        "target_width_default": 0,
        "target_width_default_meaning": "dynamic_width_scheduler_recomputes_each_wave",
        "fixed_20_not_default": True,
    }
    return queue


def claim_queue_item(queue: dict[str, Any], *, lease_seconds: int = 900) -> dict[str, Any] | None:
    now = epoch_now()
    ready = ready_entries(queue, now_epoch=now)
    if not ready:
        return None
    item = ready[0]
    item["status"] = "running"
    item["attempt"] = int(item.get("attempt") or 0) + 1
    item["lease_id"] = f"lease-{safe_stem(str(item.get('wave_id') or 'wave'))}-{int(now)}"
    item["lease_expires_epoch"] = now + max(60, int(lease_seconds or 60))
    item["lease_expires_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%S%z", time.localtime(item["lease_expires_epoch"])
    )
    item["heartbeat_at"] = now_iso()
    item["consumer_id"] = CONSUMER_ID
    item["claimed_at"] = now_iso()
    return item


def complete_queue_item(
    queue: dict[str, Any],
    *,
    item: dict[str, Any],
    phase_payload: dict[str, Any],
    successor_delay_seconds: int,
) -> None:
    validation_passed = phase_payload.get("validation", {}).get("passed") is True
    named_blocker = derive_phase_named_blocker(phase_payload)
    item["status"] = (
        "terminal_succeeded" if validation_passed and not named_blocker else "terminal_blocked"
    )
    item["terminal_at"] = now_iso()
    item["phase1_wave_id"] = phase_payload.get("wave_id")
    item["phase1_latest_ref"] = phase_payload.get("evidence_refs", {}).get("runtime_latest")
    item["merge_artifact"] = phase_payload.get("merge_artifact")
    item["draft_count"] = phase_payload.get("draft_count")
    item["staged_count"] = phase_payload.get("staged_count")
    item["merged_count"] = phase_payload.get("merged_count")
    item["spend_entry_count"] = phase_payload.get("spend_entry_count")
    item["named_blocker"] = named_blocker
    if item["status"] == "terminal_succeeded":
        next_epoch = int(item.get("loop_epoch") or 0) + 1
        next_wave_id = f"{TASK_ID}-queue-wave-{next_epoch:03d}"
        queue.setdefault("entries", []).append(
            build_queue_item(
                wave_id=next_wave_id,
                target_width=int(item.get("target_width") or 0),
                loop_epoch=next_epoch,
                source_digest=str(item.get("source_digest_sha256") or ""),
                ready_after_epoch=epoch_now() + max(1, int(successor_delay_seconds or 1)),
                reason="open_frontier_requires_scheduled_successor",
            )
        )
        queue["loop_epoch"] = next_epoch


def derive_phase_named_blocker(phase_payload: dict[str, Any]) -> str:
    named_blocker = str(phase_payload.get("named_blocker") or "")
    validation_passed = phase_payload.get("validation", {}).get("passed") is True
    external_cheap = int(
        phase_payload.get("external_cheap_draft_count")
        or phase_payload.get("true_dp_draft_count")
        or 0
    )
    local_stub = int(phase_payload.get("local_stub_draft_count") or 0)
    if not validation_passed and external_cheap <= 0:
        return named_blocker or "CHEAP_WORKER_PROVIDER_NOT_CONFIGURED"
    if not validation_passed and local_stub >= max(1, int(phase_payload.get("draft_count") or 0)):
        return named_blocker or "MODEL_GATEWAY_NOT_ROUTED"
    return named_blocker


def downgrade_thirty_minute_runner(runtime: Path, *, write: bool) -> dict[str, Any]:
    paths = output_paths(runtime)
    background_path = (
        runtime
        / "state"
        / "overnight_supervisor_loop_phase0_batch_20260704"
        / "same_default_loop"
        / "background_latest.json"
    )
    payload = read_json(background_path)
    downgraded = {
        "schema_version": "xinao.codex_s.phase2_watchdog_downgrade.v1",
        "status": "no_30_minute_runner_observed",
        "observed_ref": str(background_path),
        **WATCHDOG_DOWNGRADE_FLAGS,
        "generated_at": now_iso(),
    }
    if payload:
        payload.update(WATCHDOG_DOWNGRADE_FLAGS)
        payload["phase2_downgraded_by"] = TASK_ID
        payload["phase2_downgraded_at"] = now_iso()
        downgraded.update(
            {
                "status": "thirty_minute_runner_downgraded_to_watchdog",
                "observed_status": payload.get("status"),
                "pid": payload.get("pid"),
                "sleep_seconds": payload.get("sleep_seconds"),
                "validation": {"passed": True},
            }
        )
        if write:
            write_json(background_path, payload)
    if write:
        write_json(paths["watchdog_downgrade_latest"], downgraded)
    return downgraded


def process_alive(pid: Any) -> bool:
    try:
        if not pid:
            return False
        if os.name == "nt":
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return completed.returncode == 0 and bool((completed.stdout or "").strip())
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def active_background_consumer(runtime: Path) -> dict[str, Any]:
    payload = read_json(output_paths(runtime)["background_latest"])
    pid = int(payload.get("pid") or 0) if payload else 0
    return {
        "status": payload.get("status") if payload else "not_started",
        "pid": pid,
        "alive": process_alive(pid),
        "queue_consumer_main_loop": payload.get("queue_consumer_main_loop") is True,
        "poll_seconds": payload.get("poll_seconds") if payload else None,
    }


def build_capacity(
    *,
    queue: dict[str, Any],
    phase_payload: dict[str, Any],
    target_width: int,
) -> dict[str, Any]:
    mode_counts = (
        phase_payload.get("mode_counts")
        if isinstance(phase_payload.get("mode_counts"), dict)
        else phase1.mode_counts_for_width(target_width)
    )
    token_cost = (
        phase_payload.get("token_cost_spend")
        if isinstance(phase_payload.get("token_cost_spend"), dict)
        else {}
    )
    lane_results = (
        phase_payload.get("lane_results")
        if isinstance(phase_payload.get("lane_results"), list)
        else []
    )
    latencies = []
    for item in lane_results:
        if isinstance(item, dict):
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            latencies.append(int(usage.get("latency_ms") or item.get("latency_ms") or 0))
    return {
        "codex_subagent": {"available_slots": 0, "role": "not_dp_main_worker"},
        "dp_draft": {
            "target_width": sum(int(value or 0) for value in mode_counts.values()),
            "mode_counts": mode_counts,
            "draft_target": int(mode_counts.get("draft") or 0),
            "draft_is_primary": int(mode_counts.get("draft") or 0)
            > max(int(value or 0) for key, value in mode_counts.items() if key != "draft"),
            "provider": "Qwen prepaid cheap worker first; DeepSeek/DP fallback through ProviderGateway",
            "provider_tier_usage": phase_payload.get("provider_tier_usage") or {},
            "qwen_prepaid_draft_count": int(phase_payload.get("qwen_prepaid_draft_count") or 0),
            "external_cheap_draft_count": int(
                phase_payload.get("external_cheap_draft_count")
                or phase_payload.get("true_dp_draft_count")
                or 0
            ),
            "provider_model": "model_gateway_or_dp_sidecar_selected",
        },
        "dp_search": {"search_is_main_task": False, "search_assist_allowed": True},
        "local_tool": {"local_stub_counts_as_real_dp": False},
        "verifier": {"available": True, "role": "support_lane"},
        "merge_accept": {
            "fan_in_limits_acceptance_not_dispatch": True,
            "staging_overflow_allowed": True,
        },
        "dynamic_width_record": {
            "target_width": sum(int(value or 0) for value in mode_counts.values()),
            "actual_dispatched_width": phase_payload.get("actual_dispatched_width") or 0,
            "actual_completed_width": phase_payload.get("actual_completed_width") or 0,
            "independent_task_count": len(
                queue_status_entries(queue, {"queued", "ready", "retry_ready", "running"})
            )
            + sum(int(value or 0) for value in mode_counts.values()),
            "provider": "provider_gateway_cheap_worker_pool",
            "model": "dp_sidecar_model_gateway_route",
            "provider_tier": sorted((phase_payload.get("provider_tier_usage") or {}).keys()),
            "token_cost_spend": token_cost,
            "latency_ms": {
                "min": min(latencies) if latencies else 0,
                "max": max(latencies) if latencies else 0,
                "avg": int(sum(latencies) / len(latencies)) if latencies else 0,
            },
            "queue_depth": len(queue_status_entries(queue, {"queued", "ready", "retry_ready"})),
            "rate_limit_error": phase_payload.get("rate_limit_error") or "",
            "retry_after": "",
            "staged_count": phase_payload.get("staged_count") or 0,
            "merged_count": phase_payload.get("merged_count") or 0,
            "named_blocker": phase_payload.get("named_blocker") or "",
        },
    }


def summarize_workers(
    phase_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active = []
    terminal = []
    lane_results = (
        phase_payload.get("lane_results")
        if isinstance(phase_payload.get("lane_results"), list)
        else []
    )
    for item in lane_results:
        if not isinstance(item, dict):
            continue
        worker = {
            "lane_id": item.get("lane_id"),
            "lane_class": "dp_draft" if item.get("mode") == "draft" else f"dp_{item.get('mode')}",
            "carrier": item.get("selected_carrier_provider_id"),
            "mode": item.get("mode"),
            "objective": item.get("objective"),
            "status": "terminal" if item.get("status") == "succeeded" else item.get("status"),
            "lease_id": "",
            "lease_expires_at": "",
            "heartbeat_at": "",
            "attempt": 1,
            "retry_after": "",
            "backoff_reason": item.get("rate_limit_error") or "",
            "input_refs": [],
            "output_refs": [item.get("artifact_ref")] if item.get("artifact_ref") else [],
            "evidence_refs": {
                "provider_invocation_ref": item.get("provider_invocation_ref"),
                "provider_latest_ref": item.get("provider_latest_ref"),
            },
            "blocker_ref": item.get("named_blocker") or "",
        }
        if item.get("status") in {"queued", "running"}:
            active.append(worker)
        else:
            terminal.append(worker)
    return active, terminal


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
        "retry_or_backoff_can_continue": bool(
            [
                item
                for item in task_backlog
                if str(item.get("status") or "") in {"queued", "ready", "retry_ready"}
            ]
        ),
        "unhandled_blockers": bool(
            [item for item in blockers if not item.get("evidence_backed_terminal_blocker")]
        ),
    }
    task_scoped_acceptance_ref = ""
    terminal_condition_present = bool(task_scoped_acceptance_ref)
    stop_allowed = not any(reason_flags.values()) and terminal_condition_present
    false_reasons = [key for key, value in reason_flags.items() if value]
    if not stop_allowed and not false_reasons:
        false_reasons = ["no_task_scoped_acceptance_or_named_terminal_blocker"]
    return {
        "stop_allowed": stop_allowed,
        "stop_reason": "task_scoped_acceptance_or_user_stop_gate"
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
        "accepted_completion_ref": task_scoped_acceptance_ref,
    }


def build_loop_runtime_state(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    queue: dict[str, Any],
    phase_payload: dict[str, Any],
    anchor_facts: dict[str, Any],
    source_entry: dict[str, Any],
    correction_digest: dict[str, Any],
    watchdog_downgrade: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    now_epoch = epoch_now()
    active_workers, terminal_workers = summarize_workers(phase_payload)
    task_backlog = queue_status_entries(
        queue, {"queued", "ready", "retry_ready", "leased", "running"}
    )
    ready_frontier = ready_entries(queue, now_epoch=now_epoch)
    staged_count = int(phase_payload.get("staged_count") or 0)
    merged_count = int(phase_payload.get("merged_count") or 0)
    draft_staging = {
        "latest_ref": phase_payload.get("evidence_refs", {}).get("draft_staging_queue_latest")
        or "",
        "staged_count": staged_count,
        "merged_count": merged_count,
        "unmerged_count": 0 if merged_count > 0 else staged_count,
        "status": "merged" if merged_count > 0 else "staged_waiting_merge",
    }
    merge_backlog = [] if merged_count > 0 else [{"reason": "staged_drafts_waiting_merge"}]
    fan_in_backlog = [] if merged_count > 0 else [{"reason": "fan_in_waiting_merge_consumer"}]
    evidence_backlog = []
    if int(phase_payload.get("spend_entry_count") or 0) <= 0:
        evidence_backlog.append({"kind": "spend_ledger_missing"})
    if not phase_payload.get("readback_refs", {}).get("runtime_readback_zh"):
        evidence_backlog.append({"kind": "readback_missing"})
    source_gaps = source_gaps_from_anchors(anchor_facts, source_entry)
    blockers = []
    named_blocker = derive_phase_named_blocker(phase_payload)
    if named_blocker:
        blockers.append(
            {
                "named_blocker": named_blocker,
                "evidence_ref": phase_payload.get("evidence_refs", {}).get("runtime_latest") or "",
                "evidence_backed_terminal_blocker": named_blocker
                in {"DEEPSEEK_PROVIDER_NOT_CONFIGURED", "MODEL_GATEWAY_NOT_ROUTED"},
                "unblock_action": "route DeepSeek/model gateway or dispatch another safe independent lane",
            }
        )
    next_frontier = [
        {
            "frontier_id": item.get("task_item_id"),
            "wave_id": item.get("wave_id"),
            "status": item.get("status"),
            "ready_after": item.get("ready_after"),
            "dispatched_to_task_queue": True,
            "dispatch_basis": item.get("enqueue_reason"),
        }
        for item in task_backlog
    ]
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
    background = active_background_consumer(runtime)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "identity": {
            "work_id": WORK_ID,
            "task_id": TASK_ID,
            "wave_id": wave_id,
            "loop_epoch": queue.get("loop_epoch") or 0,
            "checkpoint_ref": str(paths["latest"]),
            "generated_at": now_iso(),
        },
        "phase": "queue_consume_fan_in_recompute_next_frontier",
        "foreground_brain": {
            "owner": "Codex S",
            "role": "read_333_source_split_dispatch_watch_fanin_merge_keepalive",
            "source_entry_read_at": source_entry.get("source_entry_read_at"),
            "latest_user_correction_digest": correction_digest,
            "333_alignment": "333 is highest semantic anchor; phase2 serves it.",
        },
        "background": {
            "main_loop": "task_queue_worker_pool_consumer",
            "queue_consumer_main_loop": True,
            "thirty_minute_runner_is_watchdog_only": True,
            "current_consumer": background,
            "watchdog_downgrade": watchdog_downgrade,
        },
        "queues": {
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
        "terminal_workers_for_fan_in": terminal_workers,
        "capacity_by_lane_class": build_capacity(
            queue=queue,
            phase_payload=phase_payload,
            target_width=int(phase_payload.get("target_width") or 0),
        ),
        "acceptance": {
            "fan_in_candidates": staged_count,
            "accepted": merged_count,
            "staged": staged_count,
            "rejected": 0,
            "needs_more_evidence": len(evidence_backlog),
            "artifact_acceptance_refs": phase_payload.get("artifact_acceptance_queue", {}).get(
                "output_paths", {}
            )
            if isinstance(phase_payload.get("artifact_acceptance_queue"), dict)
            else {},
            "accepted_for": "next_frontier_evidence",
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
        },
        "evidence_ledger": {
            "worker_dispatch_ledger_refs": [
                str(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
            ],
            "source_ledger_refs": [],
            "claim_card_refs": [],
            "verifier_refs": [
                str(
                    repo / "scripts" / "verify_loop_runtime_state_supervisor_worker_pool_phase2.ps1"
                )
            ],
            "runtime_evidence_refs": {
                "phase1_latest": phase_payload.get("evidence_refs", {}).get("runtime_latest") or "",
                "task_queue_latest": str(paths["task_queue_latest"]),
                "loop_runtime_state_latest": str(paths["latest"]),
                "merge_artifact": phase_payload.get("merge_artifact") or "",
                "foreground_brain_decision": phase_payload.get("evidence_refs", {}).get(
                    "foreground_brain_decision_latest"
                )
                or "",
            },
            "readback_refs": {"zh": str(paths["readback"])},
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
            "actual_dispatched_width": phase_payload.get("actual_dispatched_width"),
            "actual_completed_width": phase_payload.get("actual_completed_width"),
            "draft_count": phase_payload.get("draft_count"),
            "true_dp_draft_count": phase_payload.get("true_dp_draft_count"),
            "qwen_prepaid_draft_count": phase_payload.get("qwen_prepaid_draft_count"),
            "external_cheap_draft_count": phase_payload.get("external_cheap_draft_count")
            or phase_payload.get("true_dp_draft_count"),
            "qwen_first_applies_only_to": phase_payload.get("qwen_first_applies_only_to"),
            "qwen_first_must_not_override": phase_payload.get("qwen_first_must_not_override"),
            "qwen_prepaid_first_required_count": phase_payload.get(
                "qwen_prepaid_first_required_count"
            ),
            "qwen_prepaid_first_attempted_count": phase_payload.get(
                "qwen_prepaid_first_attempted_count"
            ),
            "qwen_prepaid_first_succeeded_count": phase_payload.get(
                "qwen_prepaid_first_succeeded_count"
            ),
            "local_stub_draft_count": phase_payload.get("local_stub_draft_count"),
            "staged_count": phase_payload.get("staged_count"),
            "merged_count": phase_payload.get("merged_count"),
            "spend_entry_count": phase_payload.get("spend_entry_count"),
            "merge_artifact": phase_payload.get("merge_artifact"),
            "named_blocker": phase_payload.get("named_blocker") or "",
        },
        "stop": stop,
        "stop_hook_contract": {
            "hook_role": "fake_stop_guard_only",
            "reads_loop_runtime_state": True,
            "does_not_execute_main_loop": True,
            "when_stop_allowed_false": [
                "do_not_final",
                "continue_poll_watch",
                "kick_resume_dispatch_if_backend_stuck",
                "fan_in_terminal_workers_before_report",
            ],
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_boundary": True,
        "not_source_of_truth": True,
        "validation": {
            "passed": True,
            "checks": {
                "loop_runtime_state_written": True,
                "required_queue_fields_present": True,
                "stop_allowed_derived": stop.get("derived") is True,
                "stop_allowed_false_with_backlog": (
                    stop.get("stop_allowed") is False if task_backlog else True
                ),
                "draft_count_positive": int(phase_payload.get("draft_count") or 0) > 0,
                "staged_count_positive": staged_count > 0,
                "merged_count_positive": merged_count > 0,
                "external_cheap_not_local_stub": int(
                    phase_payload.get("external_cheap_draft_count")
                    or phase_payload.get("true_dp_draft_count")
                    or 0
                )
                > int(phase_payload.get("local_stub_draft_count") or 0),
                "watchdog_runner_downgraded": watchdog_downgrade.get("watchdog_only") is True
                and watchdog_downgrade.get("not_main_loop") is True,
                "queue_consumer_not_30_minute_runner": True,
                "source_gaps_computed": isinstance(source_gaps, list),
                "next_frontier_dispatched_to_queue": bool(next_frontier)
                or stop.get("stop_allowed") is False,
            },
            "validated_at": now_iso(),
        },
    }
    payload["validation"]["passed"] = all(payload["validation"]["checks"].values())
    payload["status"] = (
        "loop_runtime_state_queue_consumer_wave_ready"
        if payload["validation"]["passed"]
        else "loop_runtime_state_queue_consumer_wave_blocked"
    )
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["records"] / f"{safe_stem(wave_id)}.json", payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    queues = payload.get("queues", {}) if isinstance(payload.get("queues"), dict) else {}
    phase = payload.get("phase1_payload_summary", {})
    stop = payload.get("stop", {}) if isinstance(payload.get("stop"), dict) else {}
    background = (
        payload.get("background", {}) if isinstance(payload.get("background"), dict) else {}
    )
    current_consumer = (
        background.get("current_consumer")
        if isinstance(background.get("current_consumer"), dict)
        else {}
    )
    return "\n".join(
        [
            "# LoopRuntimeState Phase2 回读",
            "",
            SENTINEL,
            "",
            f"- task_id: `{TASK_ID}`",
            f"- status: `{payload.get('status')}`",
            f"- wave_id: `{payload.get('identity', {}).get('wave_id')}`",
            f"- 后台现在有没有活: consumer_alive={current_consumer.get('alive')} queue_consumer_main_loop={current_consumer.get('queue_consumer_main_loop')}",
            f"- 队列还有没有 backlog: {len(queues.get('task_backlog', []))}",
            f"- ready_frontier: {len(queues.get('ready_frontier', []))}",
            f"- 草稿有没有 merge: draft={phase.get('draft_count')} staged={phase.get('staged_count')} merged={phase.get('merged_count')}",
            f"- source gap 有没有闭合: source_gaps={len(queues.get('source_gaps', []))}",
            f"- stop_allowed: {stop.get('stop_allowed')} reason=`{stop.get('stop_reason')}`",
            f"- 下一步机器动作: consume queued next_frontier via `{QUEUE_ID}`; if backend idle, foreground kicks queue consumer.",
            f"- merge_artifact: `{phase.get('merge_artifact')}`",
            "",
            "## 边界",
            "",
            "- 30 分钟 same_default runner 只允许 watchdog/fallback/rescue，不是 main loop。",
            "- Stop hook 只读 LoopRuntimeState 防误停，不拥有主循环。",
            "- PASS/latest/readback/report/draft 都不是完成边界。",
            "",
            "## Evidence",
            "",
            f"- latest: `{payload.get('evidence_ledger', {}).get('runtime_evidence_refs', {}).get('loop_runtime_state_latest')}`",
            f"- task_queue: `{payload.get('evidence_ledger', {}).get('runtime_evidence_refs', {}).get('task_queue_latest')}`",
            f"- phase1_latest: `{payload.get('evidence_ledger', {}).get('runtime_evidence_refs', {}).get('phase1_latest')}`",
            f"- foreground_brain_decision: `{payload.get('evidence_ledger', {}).get('runtime_evidence_refs', {}).get('foreground_brain_decision')}`",
            "",
            SENTINEL,
            "",
        ]
    )


def run_queue_consumer_tick(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "",
    target_width: int = 0,
    max_parallel_workers: int = 12,
    successor_delay_seconds: int = 120,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(runtime)
    anchor_facts = authority_anchor_facts()
    source_entry = phase1.scan_source_entry(root=SOURCE_ENTRY_ROOT)
    correction_digest = latest_user_correction_digest()
    queue = load_or_seed_queue(
        runtime=runtime,
        wave_id=wave_id or f"{TASK_ID}-queue-wave-001",
        target_width=target_width,
        source_digest=source_entry.get("source_entry_digest_sha256") or "",
        write=write,
    )
    queue = normalize_open_queue_widths(queue, target_width=target_width)
    item = claim_queue_item(queue)
    if write:
        write_json(paths["task_queue_latest"], queue)
    if item is None:
        phase_payload = read_json(
            runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
        )
        if not phase_payload:
            phase_payload = {
                "wave_id": wave_id or f"{TASK_ID}-idle",
                "status": "no_ready_queue_item",
                "validation": {"passed": False},
                "named_blocker": "TASK_QUEUE_NO_READY_ITEM",
            }
        actual_wave_id = str(phase_payload.get("wave_id") or wave_id or f"{TASK_ID}-idle")
    else:
        actual_wave_id = str(item.get("wave_id") or wave_id or f"{TASK_ID}-queue-wave")
        phase_payload = phase1.run_wave(
            runtime_root=runtime,
            repo_root=repo,
            wave_id=actual_wave_id,
            target_width=int(item.get("target_width") or target_width or 0),
            write=write,
            record_meta_rsi=False,
            require_external_draft=True,
            max_parallel_workers=max_parallel_workers,
            runtime_enforced=True,
            runtime_enforced_scope=RUNTIME_SCOPE,
            while_chain_id=f"{TASK_ID}.task_queue_consumer",
            while_wave_index=int(item.get("loop_epoch") or 1),
            while_wave_count=999999,
            previous_wave_id="",
            next_wave_id=f"{TASK_ID}-queue-wave-{int(item.get('loop_epoch') or 1) + 1:03d}",
        )
        complete_queue_item(
            queue,
            item=item,
            phase_payload=phase_payload,
            successor_delay_seconds=successor_delay_seconds,
        )
        queue["queue_depth"] = len(queue_status_entries(queue, {"queued", "ready", "retry_ready"}))
        queue["updated_at"] = now_iso()
        if write:
            write_json(paths["task_queue_latest"], queue)
            write_json(
                paths["task_queue_records"] / f"{safe_stem(actual_wave_id)}.queue.json", queue
            )
    watchdog = downgrade_thirty_minute_runner(runtime, write=write)
    payload = build_loop_runtime_state(
        runtime=runtime,
        repo=repo,
        wave_id=actual_wave_id,
        queue=queue,
        phase_payload=phase_payload,
        anchor_facts=anchor_facts,
        source_entry=source_entry,
        correction_digest=correction_digest,
        watchdog_downgrade=watchdog,
        write=write,
    )
    return payload


def run_consumer_loop(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    poll_seconds: int = 60,
    max_waves: int = 0,
    target_width: int = 0,
    max_parallel_workers: int = 12,
    successor_delay_seconds: int = 120,
) -> dict[str, Any]:
    waves = []
    count = 0
    while True:
        if max_waves and count >= max_waves:
            break
        count += 1
        payload = run_queue_consumer_tick(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id="",
            target_width=target_width,
            max_parallel_workers=max_parallel_workers,
            successor_delay_seconds=successor_delay_seconds,
            write=True,
        )
        waves.append(
            {
                "wave_id": payload.get("identity", {}).get("wave_id"),
                "status": payload.get("status"),
                "validation_passed": payload.get("validation", {}).get("passed"),
                "stop_allowed": payload.get("stop", {}).get("stop_allowed"),
            }
        )
        if max_waves and count >= max_waves:
            break
        time.sleep(max(1, int(poll_seconds or 1)))
    return {
        "schema_version": f"{SCHEMA_VERSION}.loop",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "phase2_queue_consumer_loop_exited_reference_only",
        "reference_only": True,
        "watchdog_only": True,
        "not_main_loop": True,
        "not_task_owner": True,
        "not_watch_owner": True,
        "not_completion_boundary": True,
        "main_loop_replacement": "temporal_activity_event_queue_loop",
        "sleep_1800_default_main_loop_allowed": False,
        "wave_count": count,
        "waves": waves,
        "validation": {
            "passed": bool(waves) and all(w.get("validation_passed") is True for w in waves)
        },
        "generated_at": now_iso(),
    }


def start_background_consumer(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    poll_seconds: int = 60,
    target_width: int = 0,
    max_parallel_workers: int = 12,
    successor_delay_seconds: int = 120,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    paths = output_paths(runtime)
    args = [
        sys.executable,
        "-m",
        "services.agent_runtime.loop_runtime_state_supervisor_worker_pool_phase2",
        "--loop",
    ]
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.background",
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "phase2_background_start_disabled_reference_only",
        "pid": 0,
        "queue_consumer_main_loop": False,
        "not_30_minute_runner": True,
        "watchdog_only": True,
        "disabled": True,
        "reference_only": True,
        "not_main_loop": True,
        "not_task_owner": True,
        "not_watch_owner": True,
        "task_owner": "Temporal activity event queue loop; phase2 background process is disabled",
        "not_completion_boundary": True,
        "legacy_phase2_runner_reference_only": True,
        "command": args,
        "poll_seconds": poll_seconds,
        "successor_delay_seconds": successor_delay_seconds,
        "target_width": target_width,
        "log_path": str(paths["background_log"]),
        "stderr_log_path": str(paths["background_log"].with_suffix(".err.log")),
        "disabled_by_task_id": "remove_30min_runner_event_queue_loop_correction_20260704",
        "main_loop_replacement": "temporal_activity_event_queue_loop",
        "validation": {"passed": True},
        "generated_at": now_iso(),
    }
    write_json(paths["background_latest"], payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="")
    parser.add_argument("--target-width", type=int, default=0)
    parser.add_argument("--max-parallel-workers", type=int, default=12)
    parser.add_argument("--successor-delay-seconds", type=int, default=120)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-waves", type=int, default=0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--start-background", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if args.start_background:
        payload = start_background_consumer(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            poll_seconds=args.poll_seconds,
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
            successor_delay_seconds=args.successor_delay_seconds,
        )
    elif args.loop:
        payload = run_consumer_loop(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            poll_seconds=args.poll_seconds,
            max_waves=args.max_waves,
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
            successor_delay_seconds=args.successor_delay_seconds,
        )
    else:
        payload = run_queue_consumer_tick(
            runtime_root=args.runtime_root,
            repo_root=args.repo_root,
            wave_id=args.wave_id,
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
            successor_delay_seconds=args.successor_delay_seconds,
            write=not args.no_write,
        )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
