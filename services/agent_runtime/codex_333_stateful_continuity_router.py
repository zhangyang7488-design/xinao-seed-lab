from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.333_stateful_continuity_router.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_STATEFUL_CONTINUITY_ROUTER_READY"
TASK_ID = "codex_333_stateful_continuity_router_20260706"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_SOURCE_ROOT = Path(r"C:\Users\xx363\Desktop\新建文件夹")
DEFAULT_SOURCE_FILES = [
    DEFAULT_SOURCE_ROOT / "333_DEFAULT_CHAIN_EVOLUTION_QWEN_DP_AUDIT_20260705.txt",
    DEFAULT_SOURCE_ROOT / "333_DEFAULT_CHAIN_GLOBAL_REPAIR_PACKAGE_20260705.txt",
    DEFAULT_SOURCE_ROOT / "333_GLOBAL_CAPABILITY_ISLAND_INVENTORY_QWEN_DP_20260705.txt",
    DEFAULT_SOURCE_ROOT / "333_S_HANDOFF_MERGED_LANDABLE_PACKAGE_QWEN_DP_20260705.txt",
    DEFAULT_SOURCE_ROOT / "GLOBAL_MAINCHAIN_CONFLICT_AUDIT_QWEN_DP_ONLY_20260705.txt",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value)).strip("._")
    cleaned = cleaned or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(str(value).encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{cleaned[: limit - 13]}-{digest}"


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


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "codex_333_stateful_continuity_router"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "codex_333_stateful_continuity_router.md",
    }


def source_file_record(path: Path) -> dict[str, Any]:
    raw = path.read_bytes() if path.is_file() else b""
    text = raw.decode("utf-8", errors="replace") if raw else ""
    lines = text.splitlines()
    headings = [
        line.strip()
        for line in lines
        if line.strip()
        and (
            line.strip().startswith("ClaimCard")
            or line.strip().startswith("P0")
            or line.strip().startswith("P1")
            or line.strip().startswith("阶段")
            or line.strip().startswith("一、")
            or line.strip().startswith("二、")
            or line.strip().startswith("三、")
            or line.strip().startswith("四、")
        )
    ][:40]
    landing_artifacts = []
    for index, line in enumerate(lines):
        if "应落地工件" in line or "输出文件建议" in line or "下一步应落" in line:
            landing_artifacts.append(
                {
                    "line_number": index + 1,
                    "line": line.strip(),
                    "next_lines": [item.strip() for item in lines[index + 1 : index + 5] if item.strip()],
                }
            )
    return {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": len(raw),
        "line_count": len(lines),
        "char_count": len(text),
        "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
        "first_nonempty": next((line.strip() for line in lines if line.strip()), ""),
        "read_full": path.is_file(),
        "heading_sample": headings,
        "landing_artifact_mentions": landing_artifacts[:30],
    }


def build_source_package(files: list[Path]) -> dict[str, Any]:
    records = [source_file_record(path) for path in files]
    return {
        "source_root": str(files[0].parent if files else DEFAULT_SOURCE_ROOT),
        "file_count": len(records),
        "all_files_exist": all(item["exists"] for item in records),
        "all_files_read_full": all(item["read_full"] for item in records),
        "total_bytes": sum(int(item["bytes"] or 0) for item in records),
        "total_lines": sum(int(item["line_count"] or 0) for item in records),
        "files": records,
    }


def runtime_refs(runtime: Path) -> dict[str, dict[str, Any]]:
    refs = {
        "current_333_run_index": runtime / "state" / "current_333_run_index" / "latest.json",
        "tool_registry": runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        "task_transaction_control": runtime / "state" / "codex_333_task_transaction_control" / "latest.json",
        "default_main_loop_trigger": runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json",
        "phase1": runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json",
        "dynamic_width_policy": runtime / "state" / "dynamic_width_policy" / "latest.json",
        "p0_landing": runtime / "state" / "333_sleep_watch_p0_landing" / "latest.json",
        "legacy_freeze_manifest": runtime / "state" / "codex_333_legacy_freeze_manifest" / "latest.json",
    }
    result = {}
    for name, path in refs.items():
        payload = read_json(path)
        validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
        result[name] = {
            "path": str(path),
            "exists": path.is_file(),
            "status": payload.get("status", ""),
            "validation_passed": validation.get("passed"),
            "completion_claim_allowed": payload.get("completion_claim_allowed"),
        }
    return result


def accepted_claims(runtime: Path, refs: dict[str, dict[str, Any]]) -> list[str]:
    accepted: list[str] = []
    index = read_json(Path(refs["current_333_run_index"]["path"]))
    registry = read_json(Path(refs["tool_registry"]["path"]))
    task_control = read_json(Path(refs["task_transaction_control"]["path"]))
    host_trace = read_json(runtime / "state" / "codex_333_host_dialogue_gate_trace" / "latest.json")
    p0 = read_json(Path(refs["p0_landing"]["path"]))
    default_trigger = read_json(Path(refs["default_main_loop_trigger"]["path"]))
    phase1 = read_json(Path(refs["phase1"]["path"]))
    width_policy = read_json(Path(refs["dynamic_width_policy"]["path"]))
    legacy_freeze = read_json(Path(refs["legacy_freeze_manifest"]["path"]))
    if (
        index.get("status") == "current_333_run_index_ready"
        and index.get("reconciliation", {}).get("reconciled") is True
    ):
        accepted.append("P0-1.current_333_run_index")
    provider_ids = registry.get("provider_ids") if isinstance(registry.get("provider_ids"), list) else []
    if {
        "codex_s.333_task_transaction_control",
        "qwen_prepaid_cheap_worker",
        "legacy.deepseek_dp_sidecar",
    } <= set(provider_ids):
        accepted.append("P0-2.tool_registry_and_task_control")
    p0_checks = p0.get("validation", {}).get("checks", {}) if isinstance(p0.get("validation"), dict) else {}
    if p0_checks.get("provider_realness_gate_rejects_fake") is True:
        accepted.append("P0-3.provider_realness_gate")
    phase1_dynamic_width = (
        phase1.get("target_width_source")
        in {"dynamic_width_scheduler", "explicit_assignment_dag_work_package"}
        and int(phase1.get("actual_dispatched_width") or 0) > 0
    )
    policy_dynamic_width = (
        width_policy.get("status") == "dynamic_width_policy_ready"
        and int(width_policy.get("actual_dispatched_width") or 0) > 0
        and width_policy.get("fixed_width_literal_used") is False
        and width_policy.get("recomputed_each_wave") is True
    )
    if phase1_dynamic_width or policy_dynamic_width:
        accepted.append("P0-5.dynamic_width_evidence")
    if default_trigger.get("trigger_truth_chain", {}).get("ready") is True:
        accepted.append("P0.default_main_loop_trigger_truth_chain")
    if task_control.get("status") == "codex_333_task_transaction_control_ready":
        accepted.append("P0.task_transaction_control")
    if (
        host_trace.get("status") == "host_dialogue_gate_trace_ready"
        and host_trace.get("validation", {}).get("passed") is True
    ):
        accepted.append("P0.host_dialogue_gate_trace")
    if (
        legacy_freeze.get("status") == "legacy_freeze_manifest_ready"
        and legacy_freeze.get("validation", {}).get("passed") is True
    ):
        accepted.append("P0.legacy_freeze_manifest")
        accepted.append("P0.legacy_reference_only_runtime_guard")
    return accepted


def stale_claims(source_package: dict[str, Any], refs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    current = read_json(Path(refs["current_333_run_index"]["path"]))
    temporal = current.get("temporal") if isinstance(current.get("temporal"), dict) else {}
    all_text = "\n".join(
        Path(item["path"]).read_text(encoding="utf-8", errors="replace")
        for item in source_package.get("files", [])
        if item.get("exists")
    )
    claims: list[dict[str, str]] = []
    if "TEMPORAL_SERVER_NOT_RUNNING" in all_text and temporal.get("port_open") is True:
        claims.append(
            {
                "claim_id": "stale.TEMPORAL_SERVER_NOT_RUNNING",
                "source": "desktop_source_package",
                "current_truth": "Temporal server port is open in current_333_run_index",
            }
        )
    if "r7 已完成" in all_text and str(temporal.get("status") or "").lower() == "running":
        claims.append(
            {
                "claim_id": "stale.r7_completed_as_current",
                "source": "333_S_HANDOFF_MERGED_LANDABLE_PACKAGE_QWEN_DP_20260705",
                "current_truth": "current workflow is running and has a later pending activity",
            }
        )
    return claims


def active_blockers(refs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    current = read_json(Path(refs["current_333_run_index"]["path"]))
    temporal = current.get("temporal") if isinstance(current.get("temporal"), dict) else {}
    blockers: list[dict[str, str]] = []
    if not current:
        blockers.append({"blocker_name": "CURRENT_333_RUN_INDEX_MISSING", "next_action": "run P0 landing"})
    if temporal and temporal.get("port_open") is not True:
        blockers.append({"blocker_name": "TEMPORAL_SERVER_NOT_RUNNING", "next_action": "start/repair Temporal carrier"})
    if temporal and str(temporal.get("status") or "").lower() == "running" and int(temporal.get("pending_activity_count") or 0) > 0:
        blockers.append(
            {
                "blocker_name": "BACKGROUND_ACTIVITY_RUNNING",
                "next_action": "mirror poll; do not duplicate dispatch unless user explicitly inserts a task",
            }
        )
    return blockers


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    source_files: list[Path] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    files = source_files or list(DEFAULT_SOURCE_FILES)
    paths = output_paths(runtime)
    source_package = build_source_package(files)
    refs = runtime_refs(runtime)
    accepted = accepted_claims(runtime, refs)
    stale = stale_claims(source_package, refs)
    blockers = active_blockers(refs)
    forbidden_narrowing = [
        "Do not narrow the user request to Qwen/DP integration only.",
        "Do not treat reports, PASS, latest.json, readback, planned lanes, or verifier-only output as completion.",
        "Do not use D:\\XINAO_CLEAN_RUNTIME/current_task_owner/old completion gates as S hot-path authority.",
        "Do not call Qwen/DP the durable 333 mainline; they are provider lanes.",
        "Do not cap Qwen/DP width because Codex quota is constrained.",
    ]
    if "P0.host_dialogue_gate_trace" not in accepted:
        next_required_artifact = "host_dialogue_gate_trace.v1"
    elif "P0.legacy_freeze_manifest" not in accepted:
        next_required_artifact = "legacy_freeze_manifest.v1"
    else:
        next_required_artifact = "control_vs_evidence_boundary_contract.v1"
    required_runtime_ref_names = [
        "current_333_run_index",
        "tool_registry",
        "task_transaction_control",
        "default_main_loop_trigger",
        "phase1",
        "dynamic_width_policy",
        "p0_landing",
    ]
    if "P0.host_dialogue_gate_trace" in accepted:
        required_runtime_ref_names.append("legacy_freeze_manifest")
    checks = {
        "all_source_files_exist": source_package["all_files_exist"],
        "all_source_files_read_full": source_package["all_files_read_full"],
        "current_user_intent_object_present": True,
        "forbidden_narrowing_present": bool(forbidden_narrowing),
        "accepted_or_stale_claims_present": bool(accepted or stale),
        "next_required_artifact_present": bool(next_required_artifact),
        "runtime_refs_bound": all(refs[name]["exists"] for name in required_runtime_ref_names),
        "completion_claim_disallowed": True,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "status": "stateful_continuity_router_ready" if all(checks.values()) else "stateful_continuity_router_blocked",
        "repo_root": str(repo),
        "source_package": source_package,
        "current_user_intent_object": {
            "intent_id": "continue_333_source_package_main_task",
            "plain_zh": "继续读取桌面五文本源包，把主任务落到 333 默认后台事务，而不是报告或审计扩写。",
            "default_mainline": "RootIntentLoop / S Default Dynamic Loop",
            "backend_transaction_required": True,
            "codex_role": "foreground brain / final merge / AAQ owner",
            "qwen_dp_role": "dynamic-width provider worker lanes",
        },
        "forbidden_narrowing": forbidden_narrowing,
        "accepted_claim_ids": accepted,
        "stale_claims": stale,
        "active_blockers": blockers,
        "next_required_artifact": next_required_artifact,
        "source_refs": [item["path"] for item in source_package["files"]],
        "runtime_refs": refs,
        "required_runtime_ref_names": required_runtime_ref_names,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return "\n".join(
        [
            "# 333 stateful continuity router",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- source_file_count: {payload.get('source_package', {}).get('file_count')}",
            f"- accepted_claim_ids: `{', '.join(payload.get('accepted_claim_ids', []))}`",
            f"- stale_claim_count: {len(payload.get('stale_claims', []))}",
            f"- next_required_artifact: `{payload.get('next_required_artifact')}`",
            f"- validation_passed: {validation.get('passed')}",
            "- boundary: this is continuity routing evidence, not user completion.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        source_files=[Path(item) for item in args.source_file] if args.source_file else None,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
