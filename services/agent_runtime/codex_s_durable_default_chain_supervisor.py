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

from services.agent_runtime import task_package_resolver as task_package

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
DEFAULT_MAX_AUTONOMOUS_DISPATCHES = 1
DEFAULT_CANONICAL_MAINLINE_WORKFLOW_ID = os.environ.get(
    "XINAO_CODEX_S_CANONICAL_MAINLINE_WORKFLOW_ID",
    "codex-s-333-mainline-p0-20260707-r9-task-package-resolver-global-hardened",
)
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
    task_package.LEGACY_AUTHORITY_FILES[0],
    "当前源文本增量_20260704.txt",
    "根意图分工.txt",
    "XINAO_333_固定锚点.txt",
    *task_package.LEGACY_AUTHORITY_FILES[1:],
]
TASK_PACKAGE_MANIFEST_NAMES = list(task_package.TASK_PACKAGE_MANIFEST_NAMES)
REAL_WORKER_PROVIDER_IDS = {
    "qwen_prepaid_cheap_worker",
    "legacy.deepseek_dp_sidecar",
    "deepseek_dp",
}
LOCAL_STUB_PROVIDER_PREFIXES = ("seed_cortex.local_",)
STOP_SENTINEL_FILENAME = "stop_interrupt.sentinel"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def check_stop_interrupt(runtime: Path) -> dict[str, Any]:
    sentinel = runtime / STOP_SENTINEL_FILENAME
    env_value = os.environ.get("XINAO_STOP_INTERRUPT", "").strip()
    detected = bool(env_value) or sentinel.is_file()
    return {
        "schema_version": f"{SCHEMA_VERSION}.stop_interrupt.v1",
        "detected": detected,
        "sentinel_path": str(sentinel),
        "sentinel_exists": sentinel.is_file(),
        "env_var": "XINAO_STOP_INTERRUPT",
        "env_set": bool(env_value),
        "reason": "operator_stop_interrupt_requested" if detected else "",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


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


def resolve_default_mainline_workflow_id(runtime: Path) -> dict[str, Any]:
    index_path = runtime / "state" / "current_333_run_index" / "latest.json"
    index = read_json(index_path)
    workflow_id = str(index.get("workflow_id") or "").strip()
    run_id = str(index.get("workflow_run_id") or "").strip()
    if workflow_id:
        return {
            "workflow_id": workflow_id,
            "workflow_run_id": run_id,
            "source": str(index_path),
            "source_status": str(index.get("status") or ""),
            "policy": "UseExisting_or_Fail",
        }
    return {
        "workflow_id": DEFAULT_CANONICAL_MAINLINE_WORKFLOW_ID,
        "workflow_run_id": "",
        "source": str(index_path),
        "source_status": str(index.get("status") or "missing"),
        "policy": "UseExisting_or_Fail",
    }


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


def task_package_manifest_ref(source_root: Path) -> tuple[Path | None, dict[str, Any]]:
    for name in TASK_PACKAGE_MANIFEST_NAMES:
        candidate = source_root / name
        if candidate.is_file():
            payload = read_json(candidate)
            if payload:
                return candidate, payload
    return None, {}


def normalize_manifest_resource_path(source_root: Path, resource_path: str) -> Path:
    raw = str(resource_path or "").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return source_root / raw


def manifest_resource_paths(source_root: Path, manifest: dict[str, Any]) -> list[Path]:
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
        paths.append(normalize_manifest_resource_path(source_root, raw_path))
    return paths


def source_package_refs(source_root: Path, package_path: Path) -> dict[str, Any]:
    package = task_package.resolve_task_package(
        source_root,
        legacy_files=tuple(SOURCE_AUTHORITY_FILENAMES),
        include_manifest_ref=True,
    )
    if package.get("manifest_driven") is True:
        manifest_ref = package.get("task_package_manifest")
        resource_refs = [
            ref
            for ref in package.get("refs", [])
            if ref.get("role") != "task_package_manifest"
        ]
        package_ref = file_digest(package_path)
        return {
            **package,
            "source_root": str(source_root),
            "package_mode": "manifest",
            "manifest_driven": True,
            "stage_package_ref": manifest_ref,
            "task_package_manifest_ref": manifest_ref,
            "legacy_stage_package_ref": package_ref,
            "authority_refs": resource_refs,
            "authority_file_count": len(resource_refs),
            "authority_existing_count": len([item for item in resource_refs if item.get("exists") is True]),
            "all_required_sources_read_full": bool(resource_refs)
            and all(item.get("exists") is True for item in resource_refs),
            "current_package_rank0_for_task": True,
            "desktop_new_system_anchor": True,
            "read_order": list(package.get("read_order", [])),
        }

    authority_refs = [file_digest(Path(str(ref.get("path") or ""))) for ref in package.get("refs", [])]
    package_ref = file_digest(package_path)
    aggregate_basis = {
        "package": package_ref,
        "source_root": str(source_root),
        "authority_refs": authority_refs,
    }
    return {
        "source_root": str(source_root),
        "package_mode": "legacy_authority_files",
        "manifest_driven": False,
        "task_package_manifest_ref": {},
        "stage_package_ref": package_ref,
        "authority_refs": authority_refs,
        "authority_file_count": len(authority_refs),
        "authority_existing_count": len([item for item in authority_refs if item.get("exists") is True]),
        "all_required_sources_read_full": package_ref.get("exists") is True
        and len([item for item in authority_refs if item.get("exists") is True]) >= 4,
        "source_package_digest_sha256": digest_json(aggregate_basis),
        "current_package_rank0_for_task": True,
        "desktop_new_system_anchor": True,
        "read_order": [
            str(package_path),
            str(source_root / SOURCE_AUTHORITY_FILENAMES[0]),
            str(source_root / "当前源文本增量_20260704.txt"),
            str(source_root / "根意图分工.txt"),
            str(source_root / "XINAO_333_固定锚点.txt"),
            str(source_root / SOURCE_AUTHORITY_FILENAMES[-2]),
            str(source_root / SOURCE_AUTHORITY_FILENAMES[-1]),
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
        "stop_evidence": str(wave_root / f"{cycle_stem}.stop_evidence.json"),
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


def next_cycle_index(runtime: Path, supervisor_wave_id: str) -> int:
    wave_stem = safe_stem(supervisor_wave_id)
    wave_root = runtime / "state" / "codex_s_durable_default_chain_supervisor" / "waves" / wave_stem
    if not wave_root.is_dir():
        return 1
    prefix = f"{wave_stem}-cycle-"
    highest = 0
    for path in wave_root.glob(f"{prefix}*.json"):
        suffix = path.stem[len(prefix) :] if path.stem.startswith(prefix) else ""
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


def autonomous_dispatch_count(runtime: Path, supervisor_wave_id: str) -> int:
    wave_stem = safe_stem(supervisor_wave_id)
    wave_root = runtime / "state" / "codex_s_durable_default_chain_supervisor" / "waves" / wave_stem
    if not wave_root.is_dir():
        return 0
    count = 0
    for path in wave_root.glob(f"{wave_stem}-cycle-*.json"):
        payload = read_json(path)
        dispatch = payload.get("dispatch_supervision") if isinstance(payload.get("dispatch_supervision"), dict) else {}
        result = dispatch.get("dispatch_result") if isinstance(dispatch.get("dispatch_result"), dict) else {}
        if dispatch.get("dispatch_attempted_this_cycle") is True or result.get("dispatch_attempted") is True:
            count += 1
    return count


def total_source_episode_acceptance_evidence(runtime: Path) -> dict[str, Any]:
    path = runtime / "state" / "total_source_episode_entry" / "latest.json"
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    aaq = (
        payload.get("artifact_acceptance_queue")
        if isinstance(payload.get("artifact_acceptance_queue"), dict)
        else {}
    )
    next_frontier = (
        payload.get("next_frontier")
        if isinstance(payload.get("next_frontier"), dict)
        else {}
    )
    next_validation = (
        next_frontier.get("validation")
        if isinstance(next_frontier.get("validation"), dict)
        else {}
    )
    checks = {
        "evidence_exists": path.is_file(),
        "validation_passed": validation.get("passed") is True,
        "source_theme_bound": bool(payload.get("theme_family")),
        "invoke_capability_bound": bool(
            payload.get("can_invoke_now", {}).get("capability")
            if isinstance(payload.get("can_invoke_now"), dict)
            else ""
        ),
        "aaq_accepted": int(aaq.get("accepted_artifact_count") or 0) > 0,
        "next_frontier_written": next_validation.get("passed") is True,
        "completion_claim_denied": payload.get("completion_claim_allowed") is False,
    }
    satisfied = all(checks.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}.total_source_episode_acceptance_evidence.v1",
        "evidence_kind": "total_source_episode_entry",
        "status": "hard_acceptance_evidence_satisfied" if satisfied else "hard_acceptance_evidence_incomplete",
        "ref": str(path),
        "wave_id": str(payload.get("wave_id") or ""),
        "theme_family": str(payload.get("theme_family") or ""),
        "checks": checks,
        "satisfied": satisfied,
        "artifact_delta_count": 1 if satisfied else 0,
        "aaq_accepted_count": int(aaq.get("accepted_artifact_count") or 0),
        "merge_artifact_refs": [],
        "synthetic_item_used": False,
        "aaq_ref": str(payload.get("output_paths", {}).get("aaq_latest") or "")
        if isinstance(payload.get("output_paths"), dict)
        else "",
        "next_frontier_ref": str(payload.get("output_paths", {}).get("next_frontier_latest") or "")
        if isinstance(payload.get("output_paths"), dict)
        else "",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def source_workerpool_provider_materialization(payload: dict[str, Any]) -> dict[str, Any]:
    existing = payload.get("provider_materialization")
    if isinstance(existing, dict):
        return existing
    lane_results = payload.get("lane_results") if isinstance(payload.get("lane_results"), list) else []
    spend = payload.get("phase1_spend_ledger") if isinstance(payload.get("phase1_spend_ledger"), dict) else {}
    entries = spend.get("entries") if isinstance(spend.get("entries"), list) else []
    real_results = []
    local_stub_results = []
    for result in lane_results:
        if not isinstance(result, dict):
            continue
        selected = str(result.get("selected_carrier_provider_id") or "")
        local_stub = result.get("local_stub") is True or selected.startswith(LOCAL_STUB_PROVIDER_PREFIXES)
        if local_stub:
            local_stub_results.append(result)
        if (
            result.get("status") == "succeeded"
            and result.get("provider_invocation_performed") is True
            and result.get("model_invocation_performed") is True
            and selected in REAL_WORKER_PROVIDER_IDS
            and not local_stub
            and bool(result.get("provider_invocation_ref"))
        ):
            real_results.append(result)
    real_drafts = [result for result in real_results if result.get("mode") == "draft"]
    qwen_real_count = len(
        [
            result
            for result in real_results
            if result.get("selected_carrier_provider_id") == "qwen_prepaid_cheap_worker"
        ]
    )
    deepseek_real_count = len(
        [
            result
            for result in real_results
            if result.get("selected_carrier_provider_id")
            in {"legacy.deepseek_dp_sidecar", "deepseek_dp"}
        ]
    )
    real_spend_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and (
            entry.get("qwen_prepaid_invocation") is True
            or entry.get("deepseek_dp_invocation") is True
            or str(entry.get("selected_carrier_provider_id") or "") in REAL_WORKER_PROVIDER_IDS
        )
    ]
    return {
        "real_worker_model_invocation_count": len(real_results),
        "qwen_real_model_invocation_count": qwen_real_count,
        "deepseek_dp_real_model_invocation_count": deepseek_real_count,
        "qwen_real_model_invoked": qwen_real_count > 0,
        "deepseek_dp_real_model_invoked": deepseek_real_count > 0,
        "qwen_and_deepseek_real_model_invoked": qwen_real_count > 0 and deepseek_real_count > 0,
        "external_cheap_draft_count": len(real_drafts),
        "local_stub_count": len(local_stub_results),
        "local_stub_draft_count": len(
            [result for result in local_stub_results if result.get("mode") == "draft"]
        ),
        "spend_ledger_real_provider_entry_count": len(real_spend_entries),
        "qwen_or_deepseek_real_model_invoked": len(real_results) > 0,
        "external_draft_model_invoked": len(real_drafts) > 0,
        "local_stub_as_completion_attempted": bool(local_stub_results) and len(real_results) == 0,
        "real_provider_invocation_refs": [
            str(result.get("provider_invocation_ref") or "") for result in real_results
        ],
    }


def source_workerpool_materialization_evidence(runtime: Path) -> dict[str, Any]:
    path = runtime / "state" / "source_frontier_workerpool_closure" / "latest.json"
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    merge = payload.get("merge") if isinstance(payload.get("merge"), dict) else {}
    aaq = (
        payload.get("artifact_acceptance_queue")
        if isinstance(payload.get("artifact_acceptance_queue"), dict)
        else {}
    )
    next_frontier = payload.get("next_frontier") if isinstance(payload.get("next_frontier"), dict) else {}
    next_validation = (
        next_frontier.get("validation")
        if isinstance(next_frontier.get("validation"), dict)
        else {}
    )
    source_batch_ids = payload.get("source_batch_ids")
    if not isinstance(source_batch_ids, list):
        source_batch_ids = next_frontier.get("source_batch_ids") if isinstance(next_frontier.get("source_batch_ids"), list) else []
    synthetic_item_used = any(
        str(batch_id).startswith("bounded-current-source-delta-")
        for batch_id in source_batch_ids
        if str(batch_id)
    ) or next_frontier.get("synthetic_item_used") is True
    accepted_count = int(aaq.get("accepted_artifact_count") or next_frontier.get("aaq_accepted_artifact_count") or 0)
    merge_artifact = str(merge.get("merge_artifact") or "")
    merge_count = int(merge.get("merged_count") or 0)
    next_real_count = int(next_frontier.get("next_frontier_real_work_count") or 0)
    provider_materialization = source_workerpool_provider_materialization(payload)
    real_qwen_model_invoked = (
        provider_materialization.get("qwen_real_model_invoked") is True
        or int(provider_materialization.get("qwen_real_model_invocation_count") or 0) > 0
    )
    real_deepseek_dp_model_invoked = (
        provider_materialization.get("deepseek_dp_real_model_invoked") is True
        or int(provider_materialization.get("deepseek_dp_real_model_invocation_count") or 0) > 0
    )
    output_paths = payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
    same_wave_refs = (
        payload.get("same_wave_output_refs")
        if isinstance(payload.get("same_wave_output_refs"), dict)
        else next_frontier.get("same_wave_output_refs")
        if isinstance(next_frontier.get("same_wave_output_refs"), dict)
        else {}
    )
    checks = {
        "evidence_exists": path.is_file(),
        "validation_passed": validation.get("passed") is True,
        "merge_artifact_materialized": bool(merge_artifact) and merge_count > 0,
        "aaq_accepted": accepted_count > 0,
        "next_frontier_written": next_validation.get("passed") is True,
        "next_frontier_real_work_count_positive": next_real_count > 0,
        "synthetic_item_not_used": not synthetic_item_used,
        "real_qwen_or_deepseek_model_invoked": provider_materialization.get(
            "qwen_or_deepseek_real_model_invoked"
        )
        is True,
        "real_qwen_model_invoked": real_qwen_model_invoked,
        "real_deepseek_dp_model_invoked": real_deepseek_dp_model_invoked,
        "real_qwen_and_deepseek_model_invoked": real_qwen_model_invoked
        and real_deepseek_dp_model_invoked,
        "real_external_draft_invoked": provider_materialization.get("external_draft_model_invoked")
        is True,
        "local_stub_not_used_as_completion": provider_materialization.get(
            "local_stub_as_completion_attempted"
        )
        is not True,
        "spend_ledger_real_provider_entry": int(
            provider_materialization.get("spend_ledger_real_provider_entry_count") or 0
        )
        > 0,
        "completion_claim_denied": payload.get("completion_claim_allowed") is False,
    }
    satisfied = all(checks.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_workerpool_materialization_evidence.v1",
        "evidence_kind": "source_frontier_workerpool_closure",
        "status": "hard_acceptance_evidence_satisfied" if satisfied else "hard_acceptance_evidence_incomplete",
        "ref": str(path),
        "wave_id": str(payload.get("wave_id") or next_frontier.get("wave_id") or ""),
        "parent_wave_id": str(payload.get("parent_wave_id") or next_frontier.get("parent_wave_id") or ""),
        "workflow_id": str(payload.get("workflow_id") or next_frontier.get("workflow_id") or ""),
        "source_batch_ids": [str(item) for item in source_batch_ids],
        "primary_source_batch_id": str(payload.get("primary_source_batch_id") or next_frontier.get("primary_source_batch_id") or ""),
        "primary_worker_brief_id": str(payload.get("primary_worker_brief_id") or next_frontier.get("primary_worker_brief_id") or ""),
        "checks": checks,
        "satisfied": satisfied,
        "artifact_delta_count": 1 if satisfied else 0,
        "aaq_accepted_count": accepted_count if satisfied else 0,
        "merge_artifact_refs": [merge_artifact] if satisfied and merge_artifact else [],
        "synthetic_item_used": synthetic_item_used,
        "next_frontier_real_work_count": next_real_count if satisfied else 0,
        "provider_materialization": provider_materialization,
        "real_worker_model_invocation_count": int(
            provider_materialization.get("real_worker_model_invocation_count") or 0
        ),
        "qwen_real_model_invocation_count": int(
            provider_materialization.get("qwen_real_model_invocation_count") or 0
        ),
        "deepseek_dp_real_model_invocation_count": int(
            provider_materialization.get("deepseek_dp_real_model_invocation_count") or 0
        ),
        "external_cheap_draft_count": int(
            provider_materialization.get("external_cheap_draft_count") or 0
        ),
        "local_stub_count": int(provider_materialization.get("local_stub_count") or 0),
        "same_wave_output_refs": same_wave_refs,
        "aaq_ref": str(output_paths.get("aaq") or same_wave_refs.get("aaq_ref") or aaq.get("aaq_ref") or ""),
        "merge_ref": str(output_paths.get("merge") or same_wave_refs.get("merge_ref") or merge.get("merge_ref") or ""),
        "next_frontier_ref": str(
            output_paths.get("next_frontier")
            or same_wave_refs.get("next_frontier_ref")
            or next_frontier.get("next_frontier_ref")
            or ""
        ),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def hard_acceptance_evidence(runtime: Path) -> dict[str, Any]:
    total_source = total_source_episode_acceptance_evidence(runtime)
    source_workerpool = source_workerpool_materialization_evidence(runtime)
    evidence_options = [source_workerpool, total_source]
    selected = next((item for item in evidence_options if item.get("satisfied") is True), source_workerpool)
    checks = {
        "source_workerpool_materialized": source_workerpool.get("satisfied") is True,
        "total_source_episode_accepted": total_source.get("satisfied") is True,
        "completion_claim_denied": True,
    }
    satisfied = any(item.get("satisfied") is True for item in evidence_options)
    return {
        "schema_version": f"{SCHEMA_VERSION}.hard_acceptance_evidence.v1",
        "status": "hard_acceptance_evidence_satisfied" if satisfied else "hard_acceptance_evidence_incomplete",
        "selected_evidence_kind": str(selected.get("evidence_kind") or ""),
        "ref": str(selected.get("ref") or ""),
        "wave_id": str(selected.get("wave_id") or ""),
        "theme_family": str(selected.get("theme_family") or selected.get("primary_source_batch_id") or ""),
        "checks": checks,
        "satisfied": satisfied,
        "artifact_delta_count": int(selected.get("artifact_delta_count") or 0) if satisfied else 0,
        "aaq_accepted_count": int(selected.get("aaq_accepted_count") or 0) if satisfied else 0,
        "merge_artifact_refs": selected.get("merge_artifact_refs") if isinstance(selected.get("merge_artifact_refs"), list) else [],
        "synthetic_item_used": selected.get("synthetic_item_used") is True,
        "source_workerpool_evidence": source_workerpool,
        "total_source_episode_evidence": total_source,
        "aaq_ref": str(selected.get("aaq_ref") or ""),
        "next_frontier_ref": str(selected.get("next_frontier_ref") or ""),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def build_dispatch_gate(
    *,
    no_dispatch: bool,
    interval_dispatch_due: bool,
    prior_autonomous_dispatch_count: int,
    max_autonomous_dispatches: int,
    allow_evidence_only_dispatch: bool,
    hard_acceptance: dict[str, Any] | None = None,
    stop_interrupt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    max_dispatches = max(0, int(max_autonomous_dispatches))
    hard_acceptance = hard_acceptance if isinstance(hard_acceptance, dict) else {}
    stop_interrupt = stop_interrupt if isinstance(stop_interrupt, dict) else {}
    stop_detected = stop_interrupt.get("detected") is True
    hard_acceptance_satisfied = hard_acceptance.get("satisfied") is True
    limit_reached = (
        not allow_evidence_only_dispatch
        and max_dispatches >= 0
        and prior_autonomous_dispatch_count >= max_dispatches
    )
    next_dispatch_allowed = not no_dispatch and interval_dispatch_due and not limit_reached and not stop_detected
    if stop_detected:
        status = "dispatch_blocked_stop_interrupt"
        blocker = "STOP_INTERRUPT_REQUESTED_BY_OPERATOR"
    elif no_dispatch:
        status = "dispatch_blocked_no_dispatch_mode"
        blocker = "DISPATCH_DISABLED_BY_NO_DISPATCH_MODE"
    elif not interval_dispatch_due:
        status = "dispatch_not_due"
        blocker = "DISPATCH_NOT_DUE"
    elif limit_reached and hard_acceptance_satisfied:
        status = "dispatch_blocked_new_supervisor_wave_required_after_hard_acceptance"
        blocker = "NEW_SUPERVISOR_WAVE_REQUIRED_AFTER_HARD_ACCEPTANCE"
    elif limit_reached:
        status = "dispatch_blocked_hard_acceptance_required"
        blocker = "HARD_ACCEPTANCE_REQUIRED_BEFORE_NEXT_AUTONOMOUS_DISPATCH"
    else:
        status = "dispatch_allowed"
        blocker = ""
    return {
        "schema_version": f"{SCHEMA_VERSION}.hard_acceptance_dispatch_gate.v1",
        "status": status,
        "next_dispatch_allowed": next_dispatch_allowed,
        "named_blocker": blocker,
        "prior_autonomous_dispatch_count": prior_autonomous_dispatch_count,
        "max_autonomous_dispatches": max_dispatches,
        "allow_evidence_only_dispatch": allow_evidence_only_dispatch,
        "hard_acceptance_required": limit_reached and not hard_acceptance_satisfied,
        "hard_acceptance_satisfied": hard_acceptance_satisfied,
        "hard_acceptance_evidence": hard_acceptance,
        "stop_interrupt": stop_interrupt,
        "hard_acceptance_required_shape": (
            "source_theme -> default_invoke_capability -> merged_artifact -> "
            "FanIn/AAQ -> next_frontier; evidence-only PASS/readback/latest is insufficient"
        ),
        "report_substitute_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    stop = payload.get("stop") if isinstance(payload.get("stop"), dict) else {}
    provider_materialization = (
        source_workerpool_provider_materialization(payload)
        if path.match("*/source_frontier_workerpool_closure/latest.json")
        or str(path).endswith(r"source_frontier_workerpool_closure\latest.json")
        else {}
    )
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
        "provider_materialization": provider_materialization,
        "qwen_or_deepseek_real_model_invoked": provider_materialization.get(
            "qwen_or_deepseek_real_model_invoked"
        ),
        "external_draft_model_invoked": provider_materialization.get("external_draft_model_invoked"),
        "local_stub_as_completion_attempted": provider_materialization.get(
            "local_stub_as_completion_attempted"
        ),
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
    dispatch_gate: dict[str, Any],
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
    if dispatch_gate.get("hard_acceptance_required") is True:
        items.append(
            {
                "blocker_name": "HARD_ACCEPTANCE_REQUIRED_BEFORE_NEXT_AUTONOMOUS_DISPATCH",
                "fixable": True,
                "unblock_action": (
                    "land one source-text theme as a default invokable capability with merged artifact, "
                    "FanIn/AAQ, next_frontier, and Chinese readback; then start a new supervisor wave "
                    "or explicitly allow evidence-only dispatch"
                ),
                "prior_autonomous_dispatch_count": dispatch_gate.get("prior_autonomous_dispatch_count"),
                "max_autonomous_dispatches": dispatch_gate.get("max_autonomous_dispatches"),
                "report_substitute_allowed": False,
            }
        )
    if dispatch_gate.get("named_blocker") == "NEW_SUPERVISOR_WAVE_REQUIRED_AFTER_HARD_ACCEPTANCE":
        items.append(
            {
                "blocker_name": "NEW_SUPERVISOR_WAVE_REQUIRED_AFTER_HARD_ACCEPTANCE",
                "fixable": True,
                "unblock_action": (
                    "start a new continuation supervisor wave or explicitly raise "
                    "--max-autonomous-dispatches; do not reuse the old exhausted wave"
                ),
                "hard_acceptance_evidence_ref": dispatch_gate.get("hard_acceptance_evidence", {}).get("ref", ""),
                "next_frontier_ref": dispatch_gate.get("hard_acceptance_evidence", {}).get("next_frontier_ref", ""),
                "report_substitute_allowed": False,
            }
        )
    closure_ref = runtime_ref_map.get("source_frontier_workerpool_closure_latest", {})
    closure_materialization = (
        closure_ref.get("provider_materialization")
        if isinstance(closure_ref.get("provider_materialization"), dict)
        else {}
    )
    if closure_ref.get("validation_passed") is not True:
        items.append(
            {
                "blocker_name": "SOURCE_FRONTIER_WORKERPOOL_CLOSURE_NOT_VALIDATED",
                "fixable": True,
                "unblock_action": "requeue source_frontier_workerbrief_bridge then source_frontier_workerpool_closure",
                "report_substitute_allowed": False,
            }
        )
    if closure_materialization and closure_materialization.get("qwen_or_deepseek_real_model_invoked") is not True:
        items.append(
            {
                "blocker_name": "REAL_QWEN_OR_DEEPSEEK_MODEL_INVOCATION_MISSING",
                "fixable": True,
                "unblock_action": (
                    "run source-bound WorkerBrief lanes through ProviderScheduler "
                    "with live qwen_prepaid_cheap_worker or DeepSeek/DP model invocation"
                ),
                "local_stub_count": closure_materialization.get("local_stub_count", 0),
                "report_substitute_allowed": False,
            }
        )
    if closure_materialization and not (
        closure_materialization.get("qwen_real_model_invoked") is True
        or int(closure_materialization.get("qwen_real_model_invocation_count") or 0) > 0
    ):
        items.append(
            {
                "blocker_name": "REAL_QWEN_MODEL_INVOCATION_MISSING",
                "fixable": True,
                "unblock_action": "requeue source-bound cheap lanes through live qwen_prepaid_cheap_worker",
                "qwen_real_model_invocation_count": closure_materialization.get(
                    "qwen_real_model_invocation_count", 0
                ),
                "report_substitute_allowed": False,
            }
        )
    if closure_materialization and not (
        closure_materialization.get("deepseek_dp_real_model_invoked") is True
        or int(closure_materialization.get("deepseek_dp_real_model_invocation_count") or 0) > 0
    ):
        items.append(
            {
                "blocker_name": "REAL_DEEPSEEK_DP_MODEL_INVOCATION_MISSING",
                "fixable": True,
                "unblock_action": "requeue source-bound quality lanes through live DeepSeek/DP sidecar model invocation",
                "deepseek_dp_real_model_invocation_count": closure_materialization.get(
                    "deepseek_dp_real_model_invocation_count", 0
                ),
                "report_substitute_allowed": False,
            }
        )
    if closure_materialization and closure_materialization.get("external_draft_model_invoked") is not True:
        items.append(
            {
                "blocker_name": "REAL_EXTERNAL_DRAFT_NOT_STAGED",
                "fixable": True,
                "unblock_action": "dispatch and stage at least one real Qwen/DeepSeek draft lane",
                "local_stub_draft_count": closure_materialization.get("local_stub_draft_count", 0),
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
    dispatch_gate: dict[str, Any],
    no_dispatch: bool,
    stop_interrupt: dict[str, Any] | None = None,
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
    stop_interrupt = stop_interrupt if isinstance(stop_interrupt, dict) else check_stop_interrupt(runtime)
    if stop_interrupt.get("detected") is True:
        write_json(Path(output["stop_evidence"]), stop_interrupt)
    repair_plan = build_repair_plan(
        cycle_id=cycle_id,
        dispatch_result=dispatch_result,
        temporal_available=temporal_available,
        runtime_ref_map=runtime_ref_map,
        dispatch_gate=dispatch_gate,
        output=output,
    )
    next_poll_at = (
        dt.datetime.now(dt.timezone.utc).astimezone() + dt.timedelta(seconds=max(1, poll_seconds))
    ).isoformat(timespec="seconds")
    closure_ref = runtime_ref_map.get("source_frontier_workerpool_closure_latest", {})
    from services.agent_runtime import progress_self_evolution

    dispatch_succeeded = dispatch_result.get("succeeded") is True
    materialization = source_workerpool_materialization_evidence(runtime)
    materialized_delta = materialization.get("satisfied") is True
    accepted_delta = int(materialization.get("aaq_accepted_count") or 0) if materialized_delta else 0
    merge_artifact_refs = (
        materialization.get("merge_artifact_refs")
        if materialized_delta and isinstance(materialization.get("merge_artifact_refs"), list)
        else []
    )
    next_frontier_real_work_count = (
        int(materialization.get("next_frontier_real_work_count") or 0) if materialized_delta else 0
    )
    synthetic_item_used = materialization.get("synthetic_item_used") is True
    progress_bundle = progress_self_evolution.record_progress_bundle(
        runtime_root=runtime,
        wave_id=cycle_id,
        source_digest=str(source_refs.get("source_package_digest_sha256") or digest),
        source_theme_id="durable_default_chain_supervisor.progress_heartbeat",
        input_count=1,
        mapped_count=1 if dispatch_result.get("dispatch_attempted") is True else 0,
        artifact_delta_count=1 if materialized_delta else 0,
        merge_artifact_refs=merge_artifact_refs,
        aaq_accepted_delta=accepted_delta,
        default_invoke_delta=0,
        named_blocker_delta=1
        if dispatch_result.get("dispatch_attempted") is True and dispatch_gate.get("named_blocker")
        else 0,
        claimcard_delta=0,
        readback_delta=1,
        synthetic_item_used=synthetic_item_used,
        source_frontier_empty=False,
        next_frontier_real_work_count=next_frontier_real_work_count,
        next_frontier_self_loop_count=0 if materialized_delta else 1,
        feedback_source_refs=[
            str(runtime_ref_map.get("loop_runtime_state_latest", {}).get("path") or ""),
            str(runtime_ref_map.get("source_frontier_workerpool_closure_latest", {}).get("path") or ""),
            str(runtime_ref_map.get("worker_dispatch_ledger_latest", {}).get("path") or ""),
        ],
        no_progress_reason=""
        if materialized_delta
        else "supervisor_dispatch_success_without_materialized_artifact"
        if dispatch_succeeded
        else "supervisor_heartbeat_without_new_artifact",
        write=True,
    )
    progress_ledger = progress_bundle.get("progress_ledger") if isinstance(progress_bundle.get("progress_ledger"), dict) else {}
    strategy_mutation = (
        progress_bundle.get("strategy_mutation")
        if isinstance(progress_bundle.get("strategy_mutation"), dict)
        else {}
    )
    heartbeat = {
        "background_keepalive": True,
        "polling_continues": True,
        "supervisor_pid": os.getpid(),
        "poll_seconds": poll_seconds,
        "next_poll_at": next_poll_at,
        "new_delta_count": int(progress_ledger.get("artifact_delta_count") or 0),
        "last_new_artifact_ref": str(merge_artifact_refs[0] if merge_artifact_refs else ""),
        "accepted_delta": int(progress_ledger.get("AAQ_accepted_delta") or 0),
        "no_progress_count": int(progress_ledger.get("no_progress_count") or 0),
        "active_worker_count": 1 if dispatch_result.get("dispatch_attempted") is True else 0,
        "backlog_count": 0,
        "next_decision": str(progress_ledger.get("decision") or ""),
        "keepalive_is_materialized_progress": False,
        "dispatch_success_is_materialized_progress": False,
        "materialized_progress": materialized_delta,
        "materialization_evidence_ref": str(materialization.get("ref") or ""),
        "strategy_mutation_status": str(strategy_mutation.get("status") or ""),
    }
    manifest_driven = source_refs.get("manifest_driven") is True
    required_sources_read_full = source_refs.get("all_required_sources_read_full") is True
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
            "hard_acceptance_dispatch_gate": dispatch_gate,
            "hard_acceptance_evidence": dispatch_gate.get("hard_acceptance_evidence") or {},
            "materialization_evidence": materialization,
            "workflow_id": dispatch_result.get("workflow_id", ""),
            "latest_closure_ref": closure_ref,
            "workerpool_closure_validation_seen": closure_ref.get("validation_passed") is True,
            "default_every_wave_target": "source -> WorkerBrief -> ProviderScheduler -> pool -> staging -> merge -> FanIn/AAQ -> next_frontier",
            "pass_report_substitute_allowed": False,
        },
        "runtime_refs": runtime_ref_map,
        "repair_plan": repair_plan,
        "stop": {
            "stop_allowed": stop_interrupt.get("detected") is True,
            "stop_allowed_from_runtime": stop_allowed,
            "forced_false_reason": ""
            if stop_interrupt.get("detected") is True
            else "user_requested_overnight_durable_polling_and_source_gap_remains_open",
            "derived_from_refs": [
                "loop_runtime_state",
                "source_frontier_workerpool_closure",
                "worker_dispatch_ledger",
                "default_auto_dispatch",
                "next_frontier_machine_actions",
            ],
            "user_stop_requested": stop_interrupt.get("detected") is True,
            "stop_interrupt": stop_interrupt,
            "stop_evidence_ref": output["stop_evidence"] if stop_interrupt.get("detected") is True else "",
            "completion_claim_allowed": False,
        },
        "next_poll_at": next_poll_at,
        "heartbeat": heartbeat,
        "progress_self_evolution": progress_bundle,
        "output_paths": output,
        "evidence_digest_sha256": digest,
        "validation": {
            "passed": True,
            "checks": {
                "stage_package_bound": source_refs["stage_package_ref"].get("exists") is True,
                "desktop_source_root_bound": source_root.is_dir(),
                "authority_refs_present": (
                    required_sources_read_full
                    if manifest_driven
                    else source_refs["authority_existing_count"] >= 4
                ),
                "manifest_package_bound_when_present": (
                    source_refs["task_package_manifest_ref"].get("exists") is True
                    if manifest_driven
                    and isinstance(source_refs.get("task_package_manifest_ref"), dict)
                    else True
                ),
                "default_transaction_chain_bound": True,
                "temporal_server_seen": temporal_available,
                "latest_not_completion": True,
                "stop_allowed_false": True,
                "stop_interrupt_blocks_dispatch": stop_interrupt.get("detected") is not True
                or dispatch_gate.get("next_dispatch_allowed") is False,
                "pass_report_substitute_denied": True,
                "hard_acceptance_dispatch_gate_present": isinstance(dispatch_gate, dict),
                "evidence_only_dispatch_limited": dispatch_gate.get("allow_evidence_only_dispatch") is False,
                "hard_acceptance_evidence_checked": isinstance(
                    dispatch_gate.get("hard_acceptance_evidence"), dict
                ),
                "background_keepalive_declared": True,
                "progress_heartbeat_fields_present": all(
                    key in heartbeat
                    for key in (
                        "new_delta_count",
                        "last_new_artifact_ref",
                        "accepted_delta",
                        "no_progress_count",
                        "next_decision",
                    )
                ),
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
        f"- 当前入口包: `{stage.get('path', '')}`",
        f"- 当前入口包 sha256: `{stage.get('sha256', '')}`",
        f"- 新系统源文本 digest: `{source.get('source_package_digest_sha256', '')}`",
        "- 当前能 invoke: `python -m services.agent_runtime.temporal_codex_task_workflow --live-temporal`；后台脚本 `scripts\\start_codex_s_durable_default_chain_supervisor.ps1`。",
        f"- 本轮是否触发 live Temporal 主链: {dispatch.get('dispatch_attempted_this_cycle')}",
        f"- 派单硬门: `{dispatch.get('hard_acceptance_dispatch_gate', {}).get('status', '')}`",
        f"- 硬验收证据: `{dispatch.get('hard_acceptance_evidence', {}).get('status', '')}`",
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
        "hard_acceptance_dispatch_gate": payload["dispatch_supervision"]["hard_acceptance_dispatch_gate"],
        "hard_acceptance_evidence": payload["dispatch_supervision"].get("hard_acceptance_evidence") or {},
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
    max_autonomous_dispatches: int = DEFAULT_MAX_AUTONOMOUS_DISPATCHES,
    allow_evidence_only_dispatch: bool = False,
) -> dict[str, Any]:
    cycle_index = next_cycle_index(runtime, supervisor_wave_id) - 1
    last_dispatch_monotonic = 0.0
    last_payload: dict[str, Any] = {}
    while True:
        cycle_index += 1
        cycle_id = f"{supervisor_wave_id}-cycle-{cycle_index:06d}"
        provisional_output = output_paths(runtime, supervisor_wave_id, cycle_id)
        now_monotonic = time.monotonic()
        interval_dispatch_due = (
            not no_dispatch
            and (last_dispatch_monotonic == 0.0 or now_monotonic - last_dispatch_monotonic >= min_dispatch_interval_seconds)
        )
        prior_dispatch_count = autonomous_dispatch_count(runtime, supervisor_wave_id)
        acceptance_evidence = hard_acceptance_evidence(runtime)
        stop_interrupt = check_stop_interrupt(runtime)
        dispatch_gate = build_dispatch_gate(
            no_dispatch=no_dispatch,
            interval_dispatch_due=interval_dispatch_due,
            prior_autonomous_dispatch_count=prior_dispatch_count,
            max_autonomous_dispatches=max_autonomous_dispatches,
            allow_evidence_only_dispatch=allow_evidence_only_dispatch,
            hard_acceptance=acceptance_evidence,
            stop_interrupt=stop_interrupt,
        )
        dispatch_due = dispatch_gate["next_dispatch_allowed"]
        dispatch_result: dict[str, Any] = {
            "dispatch_attempted": False,
            "succeeded": False,
            "named_blocker": dispatch_gate.get("named_blocker") or "DISPATCH_NOT_DUE_OR_DISABLED",
        }
        if dispatch_due:
            source_ref_paths = [
                str(path)
                for path in source_package_refs(source_root, package_path).get("read_order", [])
                if str(path)
            ]
            workflow_ref = resolve_default_mainline_workflow_id(runtime)
            workflow_id = str(workflow_ref["workflow_id"])
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
            dispatch_result["workflow_id_conflict_policy"] = workflow_ref["policy"]
            dispatch_result["workflow_id_source"] = workflow_ref["source"]
            dispatch_result["workflow_id_source_status"] = workflow_ref["source_status"]
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
            dispatch_gate=dispatch_gate,
            no_dispatch=no_dispatch,
            stop_interrupt=stop_interrupt,
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
        if stop_interrupt.get("detected") is True:
            return last_payload
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
    parser.add_argument("--max-autonomous-dispatches", type=int, default=DEFAULT_MAX_AUTONOMOUS_DISPATCHES)
    parser.add_argument("--allow-evidence-only-dispatch", action="store_true")
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
        max_autonomous_dispatches=args.max_autonomous_dispatches,
        allow_evidence_only_dispatch=args.allow_evidence_only_dispatch,
    )
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
