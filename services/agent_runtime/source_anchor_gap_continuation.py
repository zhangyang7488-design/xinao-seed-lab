from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.source_anchor_gap_continuation.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_GAP_CONTINUATION_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
NODE_ID = "source_anchor_gap_continuation"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")

RUNTIME_REF_PATHS = {
    "live_backend_watch": r"state\codex_s_live_backend_watch\latest.json",
    "default_hot_path_intake": r"state\default_hot_path_intake\latest.json",
    "artifact_acceptance_queue": r"state\artifact_acceptance_queue\latest.json",
    "metaminute_preflight_reflection": r"state\metaminute_preflight_reflection\latest.json",
    "default_parallelism_policy": r"state\default_parallelism_policy\latest.json",
    "parallel_dispatch_plan": r"state\parallel_dispatch_plan\latest.json",
    "parallel_fan_in_acceptance": r"state\parallel_fan_in_acceptance\latest.json",
    "seed_lab_total_execution_kernel": r"state\seed_lab_total_execution_kernel\latest.json",
    "seed_lab_correction_intake": r"state\seed_lab_correction_intake\latest.json",
}

MAIN_EXECUTION_LOOP = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
]

OBLIGATION_MARKERS = (
    "必做",
    "验收",
    "禁止",
    "下一步",
    "下一拍",
    "任务",
    "派单",
    "切割",
    "继续",
    "续跑",
    "门禁",
    "完成",
    "外部搜索",
    "source",
    "SourceLedger",
    "AAQ",
    "ClaimCard",
    "TaskCard",
    "Temporal",
    "worker",
    "dispatch",
    "poll",
    "fan-in",
    "Stop",
    "stop",
    "hook",
)
OBLIGATION_LIMIT_PER_ANCHOR = 120
TASK_SLICE_LIMIT = 24
SOURCE_TASK_SLICING_DEFAULT_ENABLED = False
SOURCE_TASK_SLICING_FREEZE_REASON = (
    "user_permanently_froze_auto_source_text_slicing; main brain reads anchor entry root itself"
)


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


def file_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    ref.update(
        {
            "byte_count": len(data),
            "line_count": len(text.splitlines()),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
            "last_write_time": dt.datetime.fromtimestamp(
                path.stat().st_mtime, tz=dt.datetime.now().astimezone().tzinfo
            ).isoformat(timespec="seconds"),
        }
    )
    return ref


def json_ref(path: Path) -> dict[str, Any]:
    ref = file_ref(path)
    if not path.is_file():
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ref.update({"json_valid": False, "json_error": str(exc)})
        return ref
    validation = payload.get("validation") if isinstance(payload, dict) else None
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed")
            if isinstance(validation, dict)
            else None,
            "foreground_poll_required": payload.get("foreground_poll_required"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def classify_obligation(line: str) -> str:
    lowered = line.lower()
    if "禁止" in line or "禁" in line or "must not" in lowered or "forbid" in lowered:
        return "boundary"
    if "验收" in line or "acceptance" in lowered or "claimcard" in lowered:
        return "acceptance"
    if "必做" in line or "must" in lowered or "dispatch" in lowered or "派单" in line:
        return "must_do"
    if "stop" in lowered or "hook" in lowered or "门禁" in line:
        return "stop_gate"
    return "source_debt"


def obligation_line_candidates(anchor_key: str, path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    obligations: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        lower_line = line.lower()
        marker_hit = any(marker.lower() in lower_line for marker in OBLIGATION_MARKERS)
        list_hit = line.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5."))
        if not marker_hit and not list_hit:
            continue
        fingerprint = hashlib.sha256(
            f"{anchor_key}:{line_no}:{line}".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        obligations.append(
            {
                "obligation_id": f"{anchor_key}:{line_no}:{fingerprint}",
                "anchor_key": anchor_key,
                "line_no": line_no,
                "task_kind": classify_obligation(line),
                "source_excerpt": line[:360],
                "fingerprint": fingerprint,
            }
        )
        if len(obligations) >= OBLIGATION_LIMIT_PER_ANCHOR:
            break
    return obligations


def source_anchor_sha256s(anchors: dict[str, Any]) -> dict[str, str]:
    shas: dict[str, str] = {}
    text_refs = anchors.get("text_refs", {})
    if not isinstance(text_refs, dict):
        return shas
    for key, ref in text_refs.items():
        if isinstance(ref, dict) and ref.get("exists") and ref.get("sha256"):
            shas[str(key)] = str(ref["sha256"])
    return shas


def existing_coverage_refs(runtime: Path, anchor_shas: dict[str, str]) -> dict[str, Any]:
    state = runtime / "state"
    coverage_latest_path = state / "source_anchor_coverage" / "latest.json"
    coverage_latest = read_json_file(coverage_latest_path)
    recorded_shas = coverage_latest.get("source_anchor_sha256s")
    if not isinstance(recorded_shas, dict):
        recorded_shas = {}
    matched_sha_count = sum(
        1
        for key, sha in anchor_shas.items()
        if str(recorded_shas.get(key, "")).upper() == str(sha).upper()
    )
    coverage_complete = bool(coverage_latest.get("coverage_complete")) and (
        matched_sha_count == len(anchor_shas)
    )

    def ref_count(relative: str) -> int:
        root = state / relative
        if not root.is_dir():
            return 0
        return len([path for path in root.glob("*.json") if path.is_file()])

    return {
        "coverage_latest_ref": json_ref(coverage_latest_path),
        "coverage_latest_claims_complete": bool(coverage_latest.get("coverage_complete")),
        "coverage_latest_sha_match_count": matched_sha_count,
        "coverage_complete": coverage_complete,
        "task_card_json_count": ref_count("task_card"),
        "worker_assignment_json_count": ref_count("worker_assignment"),
        "source_ledger_latest_ref": json_ref(state / "source_ledger" / "latest.json"),
        "artifact_acceptance_queue_latest_ref": json_ref(
            state / "artifact_acceptance_queue" / "latest.json"
        ),
    }


def source_anchors(anchor_root: Path) -> dict[str, Any]:
    root_ref = {
        "path": str(anchor_root),
        "exists": anchor_root.is_dir(),
        "anchor_key": "source_anchor_entry_root",
        "role": "entry_root_only",
    }
    if anchor_root.is_dir():
        item = anchor_root.stat()
        root_ref.update(
            {
                "last_write_time": dt.datetime.fromtimestamp(
                    item.st_mtime, tz=dt.datetime.now().astimezone().tzinfo
                ).isoformat(timespec="seconds"),
            }
        )
    return {
        "anchor_package_root": str(anchor_root),
        "source_anchor_role": "desktop current human intent package entry root only",
        "discovery_policy": "entry_root_only_no_text_file_binding",
        "source_text_files_required_by_name": False,
        "text_file_scan_enabled": False,
        "source_text_auto_slicing_permanently_frozen": True,
        "root_ref": root_ref,
        "text_refs": {},
        "required_text_refs": ["source_anchor_entry_root"],
        "optional_text_refs": [],
        "source_anchor_complete": anchor_root.is_dir(),
    }


def build_source_anchor_coverage(
    *,
    anchors: dict[str, Any],
    anchor_root: Path,
    runtime: Path,
    paths: dict[str, str],
    task_slicing_enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    task_slicing_enabled = False
    obligations: list[dict[str, Any]] = []

    anchor_shas = source_anchor_sha256s(anchors)
    coverage_refs = existing_coverage_refs(runtime, anchor_shas)
    coverage_complete = bool(anchors.get("source_anchor_complete"))
    source_text_debt_open = False
    selected = obligations[:TASK_SLICE_LIMIT] if source_text_debt_open else []
    task_slices = []
    for index, obligation in enumerate(selected, start=1):
        task_slices.append(
            {
                "slice_id": f"source_anchor_slice_{index:02d}_{obligation['fingerprint']}",
                "source_obligation_id": obligation["obligation_id"],
                "anchor_key": obligation["anchor_key"],
                "line_no": obligation["line_no"],
                "task_kind": obligation["task_kind"],
                "objective_cn": "锚定源文本义务，切成可派发任务，进入既有 S lane/TaskCard/AAQ 证据链。",
                "source_excerpt": obligation["source_excerpt"],
                "target_lane": "existing_seed_cortex_lane",
                "acceptance": "TaskCard 或 named blocker 写入 D-runtime；ClaimCard/SourceLedger/AAQ 能追到源文本 obligation_id。",
            }
        )

    task_slice_payload = {
        "schema_version": "xinao.codex_s.source_anchor_task_slices.v1",
        "status": (
            "source_anchor_task_slices_ready"
            if task_slices
            else (
                "source_anchor_task_slicing_permanently_frozen"
                if not task_slicing_enabled
                else "source_anchor_task_slices_not_required"
            )
        ),
        "generated_at": now_iso(),
        "work_id": WORK_ID,
        "auto_task_slicing_enabled": task_slicing_enabled,
        "frozen_by_user": not task_slicing_enabled,
        "freeze_reason": SOURCE_TASK_SLICING_FREEZE_REASON
        if not task_slicing_enabled
        else "",
        "source_anchor_sha256s": anchor_shas,
        "anchor_entry_root": anchors.get("anchor_package_root", ""),
        "next_ready": bool(task_slices),
        "slice_count": len(task_slices),
        "task_slices": task_slices,
        "dispatch_policy": (
            "auto source obligation slicing is frozen; main brain reads anchor entry root directly"
            if not task_slicing_enabled
            else "compose source obligation -> TaskCard -> existing lane; no Grok/default side island"
        ),
        "sentinel": "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_TASK_SLICES_READY",
    }

    next_task_card = {
        "schema_version": "xinao.codex_s.task_card.v1",
        "task_id": "source_anchor_coverage_next_ready",
        "status": "frozen_tombstone_not_taskcard"
        if not task_slicing_enabled
        else ("next_ready" if task_slices else "not_required"),
        "generated_at": now_iso(),
        "work_id": WORK_ID,
        "intent": (
            "source_anchor_auto_task_slicing_frozen"
            if not task_slicing_enabled
            else "source_anchor_text_debt_thin_bind"
        ),
        "objective_cn": (
            "源文本自动切割/自动派单已按用户要求永久冻结；主大脑应直接读取入口目录材料，不抢占现有优先级。"
            if not task_slicing_enabled
            else "把未覆盖的源文本义务切割成 TaskCard，并派到既有 Seed Cortex lane 产出 ClaimCard 或 named blocker。"
        ),
        "source_anchor_sha256s": anchor_shas,
        "anchor_entry_root": anchors.get("anchor_package_root", ""),
        "source_task_slice_ref": paths["source_anchor_task_slices_latest"],
        "next_slice_count": len(task_slices),
        "auto_task_slicing_enabled": task_slicing_enabled,
        "frozen_by_user": not task_slicing_enabled,
        "freeze_reason": SOURCE_TASK_SLICING_FREEZE_REASON
        if not task_slicing_enabled
        else "",
        "routing": {
            "preferred_lane": "none_auto_task_slicing_frozen"
            if not task_slicing_enabled
            else "existing_seed_cortex_lane",
            "forbidden": [
                "do_not_default_to_grok",
                "do_not_treat_report_or_PASS_as_stop",
                "do_not_bypass_SourceLedger_or_AAQ",
                "do_not_consume_frozen_source_anchor_task_card",
            ],
        },
        "acceptance": {
            "task_card_enters_existing_lane": task_slicing_enabled,
            "claimcard_or_named_blocker_required": task_slicing_enabled,
            "source_obligation_id_required": task_slicing_enabled,
        },
        "sentinel": "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_TASK_CARD_READY",
    }

    coverage = {
        "schema_version": "xinao.codex_s.source_anchor_coverage.v1",
        "status": (
            "source_anchor_coverage_debt_open"
            if source_text_debt_open
            else (
                "source_anchor_entry_root_ready_auto_task_slicing_frozen"
                if not task_slicing_enabled
                else "source_anchor_coverage_complete_or_not_applicable"
            )
        ),
        "generated_at": now_iso(),
        "auto_task_slicing_enabled": task_slicing_enabled,
        "frozen_by_user": not task_slicing_enabled,
        "freeze_reason": SOURCE_TASK_SLICING_FREEZE_REASON
        if not task_slicing_enabled
        else "",
        "coverage_complete": coverage_complete,
        "source_text_debt_open": source_text_debt_open,
        "source_anchor_sha256s": anchor_shas,
        "source_text_obligation_scan_enabled": task_slicing_enabled,
        "source_text_obligation_count": len(obligations),
        "sampled_obligation_count": len(task_slices),
        "task_slices_ref": paths["source_anchor_task_slices_latest"],
        "next_task_card_ref": paths["source_anchor_next_task_card"],
        "existing_coverage_refs": coverage_refs,
        "next_machine_action": (
            "slice_source_text_to_taskcards_and_dispatch_next_assignment"
            if source_text_debt_open
            else (
                "source_anchor_entry_root_checked_no_taskcard_dispatch_main_brain_reads_directly"
                if not task_slicing_enabled
                else "no_source_text_debt_detected"
            )
        ),
        "sentinel": "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_COVERAGE_READY",
    }
    return coverage, task_slice_payload, next_task_card


def runtime_refs(runtime: Path) -> dict[str, dict[str, Any]]:
    return {key: json_ref(runtime / relative) for key, relative in RUNTIME_REF_PATHS.items()}


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(
            runtime / "state" / "source_anchor_gap_continuation" / "latest.json"
        ),
        "source_anchor_coverage_latest": str(
            runtime / "state" / "source_anchor_coverage" / "latest.json"
        ),
        "source_anchor_task_slices_latest": str(
            runtime / "state" / "source_anchor_task_slices" / "latest.json"
        ),
        "source_anchor_next_task_card": str(
            runtime / "state" / "task_card" / "source_anchor_coverage_next_ready.json"
        ),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "source_anchor_gap_continuation_20260702.md"
        ),
        "schema": str(
            repo / "contracts" / "schemas" / "codex_s_source_anchor_gap_continuation.v1.json"
        ),
        "writer": str(repo / "services" / "agent_runtime" / "source_anchor_gap_continuation.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_source_anchor_gap_continuation.py"),
        "verifier": str(repo / "scripts" / "verify_source_anchor_gap_continuation.ps1"),
    }


def decide_next_loop_packet(
    *,
    live_backend_foreground_poll_required: bool,
    explicit_user_stop_requested: bool,
    continuation_mode_active: bool,
    source_anchor_complete: bool,
    runtime_ref_complete: bool,
    source_text_debt_open: bool,
    source_task_slice_count: int,
    task_slicing_enabled: bool,
) -> dict[str, Any]:
    if live_backend_foreground_poll_required:
        return {
            "should_continue_loop": False,
            "front_gate": "live_backend_watch_front_gate",
            "continue_dispatch_expected": False,
            "inactive_reason": "live_backend_watch_requires_foreground_poll_first",
            "action": "poll live backend until terminal or no-growth, then run source-anchor gap continuation",
            "named_blocker": "",
        }
    if explicit_user_stop_requested:
        return {
            "should_continue_loop": False,
            "front_gate": "explicit_user_stop_override",
            "continue_dispatch_expected": False,
            "inactive_reason": "explicit_user_stop",
            "action": "do not continue until user resumes",
            "named_blocker": "",
        }
    if not continuation_mode_active:
        return {
            "should_continue_loop": False,
            "front_gate": "ordinary_checkpoint_stop_allowed",
            "continue_dispatch_expected": False,
            "inactive_reason": "ordinary_discussion_without_no_stop_intent",
            "action": "ordinary discussion can stop; do not manufacture worker evidence",
            "named_blocker": "",
        }
    if not source_anchor_complete:
        return {
            "should_continue_loop": False,
            "front_gate": "source_anchor_gap_continuation",
            "continue_dispatch_expected": False,
            "inactive_reason": "source_anchor_missing",
            "action": "restore or name missing desktop anchor package before dispatch",
            "named_blocker": "CODEX_S_SOURCE_ANCHOR_MISSING",
        }
    if not runtime_ref_complete:
        return {
            "should_continue_loop": False,
            "front_gate": "source_anchor_gap_continuation",
            "continue_dispatch_expected": False,
            "inactive_reason": "runtime_ref_missing_or_invalid",
            "action": "repair focused runtime evidence refs before dispatch",
            "named_blocker": "CODEX_S_RUNTIME_REF_GAP",
        }
    if not task_slicing_enabled:
        return {
            "should_continue_loop": False,
            "front_gate": "source_anchor_task_slicing_frozen",
            "continue_dispatch_expected": False,
            "inactive_reason": "source_anchor_auto_task_slicing_frozen_by_user",
            "action": "do not dispatch source-anchor TaskCard; main brain reads anchor entry root directly",
            "next_task_slice_count": 0,
            "named_blocker": "",
        }
    if source_text_debt_open:
        return {
            "should_continue_loop": True,
            "front_gate": "source_anchor_gap_continuation",
            "continue_dispatch_expected": True,
            "inactive_reason": "",
            "action": "slice_source_text_to_taskcards_and_dispatch_next_assignment",
            "next_task_slice_count": source_task_slice_count,
            "named_blocker": "",
        }
    return {
        "should_continue_loop": True,
        "front_gate": "source_anchor_gap_continuation",
        "continue_dispatch_expected": True,
        "inactive_reason": "",
        "action": (
            "restore -> recompute max-benefit frontier -> dispatch useful independent lanes "
            "-> poll -> fan-in -> verify/evidence/readback -> recompute -> next wave"
        ),
        "named_blocker": "",
    }


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    continuation_mode_active: bool = False,
    explicit_user_stop_requested: bool = False,
    source_task_slicing_enabled: bool = SOURCE_TASK_SLICING_DEFAULT_ENABLED,
    write: bool = True,
) -> dict[str, Any]:
    source_task_slicing_enabled = False
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    anchor_root = Path(anchor_package_root)
    anchors = source_anchors(anchor_root)
    refs = runtime_refs(runtime)
    paths = output_paths(repo, runtime)
    source_coverage, task_slice_payload, next_task_card = build_source_anchor_coverage(
        anchors=anchors,
        anchor_root=anchor_root,
        runtime=runtime,
        paths=paths,
        task_slicing_enabled=source_task_slicing_enabled,
    )
    live_backend_foreground_poll_required = (
        refs["live_backend_watch"].get("foreground_poll_required") is True
    )
    required_ref_names = [
        "live_backend_watch",
        "default_hot_path_intake",
        "artifact_acceptance_queue",
        "metaminute_preflight_reflection",
        "default_parallelism_policy",
        "parallel_dispatch_plan",
        "parallel_fan_in_acceptance",
    ]
    runtime_ref_complete = all(
        refs[name].get("exists") is True and refs[name].get("json_valid") is True
        for name in required_ref_names
    )
    next_packet = decide_next_loop_packet(
        live_backend_foreground_poll_required=live_backend_foreground_poll_required,
        explicit_user_stop_requested=explicit_user_stop_requested,
        continuation_mode_active=continuation_mode_active,
        source_anchor_complete=anchors["source_anchor_complete"],
        runtime_ref_complete=runtime_ref_complete,
        source_text_debt_open=bool(source_coverage["source_text_debt_open"]),
        source_task_slice_count=int(source_coverage["sampled_obligation_count"]),
        task_slicing_enabled=source_task_slicing_enabled,
    )
    coverage_gate_decision = {
        "schema_version": "xinao.codex_s.report_then_continue_source_gate.v1",
        "report_allowed": True,
        "stop_allowed": (
            explicit_user_stop_requested
            or (not source_task_slicing_enabled and not live_backend_foreground_poll_required)
            or (not continuation_mode_active and not live_backend_foreground_poll_required)
            or (
                continuation_mode_active
                and not live_backend_foreground_poll_required
                and not bool(source_coverage["source_text_debt_open"])
                and runtime_ref_complete
                and anchors["source_anchor_complete"]
            )
        ),
        "continuation_required": (
            not explicit_user_stop_requested
            and source_task_slicing_enabled
            and continuation_mode_active
            and (
                bool(source_coverage["source_text_debt_open"])
                or next_packet["continue_dispatch_expected"]
                or not runtime_ref_complete
                or not anchors["source_anchor_complete"]
            )
        ),
        "source_text_debt_open": bool(source_coverage["source_text_debt_open"]),
        "auto_task_slicing_enabled": source_task_slicing_enabled,
        "source_anchor_task_slicing_frozen": not source_task_slicing_enabled,
        "source_anchor_coverage_complete": bool(source_coverage["coverage_complete"]),
        "next_machine_action": (
            source_coverage["next_machine_action"]
            if bool(source_coverage["source_text_debt_open"])
            else (
                "source_anchor_auto_task_slicing_frozen_no_taskcard_dispatch"
                if not source_task_slicing_enabled
                else next_packet["action"]
            )
        ),
        "source_task_slice_count": int(source_coverage["sampled_obligation_count"]),
        "source_anchor_coverage_ref": paths["source_anchor_coverage_latest"],
        "source_anchor_task_slices_ref": paths["source_anchor_task_slices_latest"],
        "source_anchor_next_task_card_ref": paths["source_anchor_next_task_card"],
    }
    checks = {
        "live_backend_watch_read": refs["live_backend_watch"].get("exists") is True
        and refs["live_backend_watch"].get("json_valid") is True,
        "source_anchor_complete": anchors["source_anchor_complete"],
        "runtime_ref_complete": runtime_ref_complete,
        "source_text_debt_accounted_for": (
            not bool(source_coverage["source_text_debt_open"])
            or int(source_coverage["sampled_obligation_count"]) > 0
        ),
        "source_anchor_task_slicing_frozen_by_default": (
            source_task_slicing_enabled or source_coverage["frozen_by_user"] is True
        ),
        "report_allowed_even_when_continuing": coverage_gate_decision["report_allowed"],
        "ordinary_discussion_can_stop": True,
        "current_no_stop_task_requires_continuation_mode": continuation_mode_active,
        "explicit_stop_overrides": (
            next_packet["front_gate"] == "explicit_user_stop_override"
            if explicit_user_stop_requested
            else True
        ),
        "continue_dispatch_requires_no_live_backend": (
            not next_packet["continue_dispatch_expected"]
            or live_backend_foreground_poll_required is False
        ),
        "stop_guard_not_execution_controller": True,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "node_id": NODE_ID,
        "status": "source_anchor_gap_continuation_ready",
        "generated_at": now_iso(),
        "adoption_state": "verifier_ready_but_not_hooked",
        "source_anchors": anchors,
        "runtime_refs": refs,
        "source_anchor_complete": anchors["source_anchor_complete"],
        "runtime_ref_complete": runtime_ref_complete,
        "continuation_mode_active": continuation_mode_active,
        "explicit_user_stop_requested": explicit_user_stop_requested,
        "live_backend_foreground_poll_required": live_backend_foreground_poll_required,
        "ordinary_discussion_can_stop": True,
        "no_stop_intent_required_for_dynamic_loop": True,
        "source_anchor_coverage": source_coverage,
        "source_anchor_coverage_complete": bool(source_coverage["coverage_complete"]),
        "source_text_debt_open": bool(source_coverage["source_text_debt_open"]),
        "auto_task_slicing_enabled": source_task_slicing_enabled,
        "source_anchor_task_slicing_frozen": not source_task_slicing_enabled,
        "freeze_reason": SOURCE_TASK_SLICING_FREEZE_REASON
        if not source_task_slicing_enabled
        else "",
        "coverage_gate_decision": coverage_gate_decision,
        "continue_dispatch_expected": next_packet["continue_dispatch_expected"],
        "next_loop_packet": next_packet,
        "stop_guard_layer": "source_anchor_gap_continuation",
        "stop_guard_layer_not_execution_controller": True,
        "stop_hook_may_use_as_decision_input": True,
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "legacy_5d33_transport_pattern_allowed": True,
        "legacy_5d33_authority_allowed": False,
        "output_paths": paths,
        "validation": {"passed": all(checks.values()), "checks": checks},
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(paths["source_anchor_coverage_latest"]), source_coverage)
        write_json(Path(paths["source_anchor_task_slices_latest"]), task_slice_payload)
        write_json(Path(paths["source_anchor_next_task_card"]), next_task_card)
        write_json(Path(payload["output_paths"]["runtime_latest"]), payload)
        write_text(Path(payload["output_paths"]["runtime_readback_zh"]), render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Codex S Source Anchor Gap Continuation readback",
            "",
            SENTINEL,
            "",
            f"- status: `{payload['status']}`",
            f"- adoption_state: `{payload['adoption_state']}`",
            f"- source_anchor_complete: {payload['source_anchor_complete']}",
            f"- runtime_ref_complete: {payload['runtime_ref_complete']}",
            f"- continuation_mode_active: {payload['continuation_mode_active']}",
            f"- auto_task_slicing_enabled: {payload['auto_task_slicing_enabled']}",
            f"- source_anchor_task_slicing_frozen: {payload['source_anchor_task_slicing_frozen']}",
            f"- source_text_debt_open: {payload['source_text_debt_open']}",
            f"- source_task_slice_count: {payload['source_anchor_coverage']['sampled_obligation_count']}",
            f"- report_allowed: {payload['coverage_gate_decision']['report_allowed']}",
            f"- stop_allowed: {payload['coverage_gate_decision']['stop_allowed']}",
            f"- continuation_required: {payload['coverage_gate_decision']['continuation_required']}",
            f"- continue_dispatch_expected: {payload['continue_dispatch_expected']}",
            "",
            "这是一层 Stop 后门守护，不是主执行流程、不是事实源、不是完成判断、不是执行控制器。",
            "源文本自动切割/自动 TaskCard 派单永久冻结；这层只检查入口目录存在，主大脑直接读入口材料。",
            "live watch / source-anchor gap 只是防停证据层；真正主流程仍是 restore -> dispatch -> poll -> fan-in -> verify/evidence/readback -> recompute -> next_wave。",
            "5d33 的耐久事务/worker/result-wait 只能作为 transport pattern 参考，不能复用旧 owner/PASS/completion gate/latest 权威。",
            "",
            "## next_loop_packet",
            "",
            f"- front_gate: `{payload['next_loop_packet']['front_gate']}`",
            f"- action: {payload['next_loop_packet']['action']}",
            f"- named_blocker: `{payload['next_loop_packet']['named_blocker']}`",
            "",
            SENTINEL,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--continuation-mode-active", action="store_true")
    parser.add_argument("--explicit-user-stop", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        continuation_mode_active=args.continuation_mode_active,
        explicit_user_stop_requested=args.explicit_user_stop,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "continue_dispatch_expected": payload["continue_dispatch_expected"],
                "auto_task_slicing_enabled": payload["auto_task_slicing_enabled"],
                "source_anchor_task_slicing_frozen": payload[
                    "source_anchor_task_slicing_frozen"
                ],
                "source_text_debt_open": payload["source_text_debt_open"],
                "source_task_slice_count": payload["source_anchor_coverage"][
                    "sampled_obligation_count"
                ],
                "continuation_required": payload["coverage_gate_decision"][
                    "continuation_required"
                ],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
