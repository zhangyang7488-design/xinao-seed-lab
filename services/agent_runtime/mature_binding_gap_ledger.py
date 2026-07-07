from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import task_package_resolver


SCHEMA_VERSION = "xinao.codex_s.mature_binding_gap_ledger.v1"
SENTINEL = "SENTINEL:XINAO_MATURE_BINDING_GAP_LEDGER_READY"
TASK_ID = "p0_005_mature_binding_gap_ledger"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_PACKAGE_ROOT = Path(
    os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
)
CATEGORIES = ("bound", "installed_not_bound", "not_applicable", "P1_deferred")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    return cleaned.strip("-")[:140] or "mature-binding-gap-ledger"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def output_paths(runtime: Path, *, record_id: str = TASK_ID) -> dict[str, Path]:
    state = runtime / "state" / "mature_binding_gap_ledger"
    return {
        "state_dir": state,
        "latest": state / "latest.json",
        "record": state / "records" / f"{safe_stem(record_id)}.json",
        "readback": runtime / "readback" / "zh" / "mature_binding_gap_ledger_20260707.md",
        "capability_manifest": runtime
        / "capabilities"
        / "codex_s.mature_binding_gap_ledger"
        / "manifest.json",
    }


def _state_dirs(runtime: Path) -> list[Path]:
    state = runtime / "state"
    try:
        return sorted([path for path in state.iterdir() if path.is_dir()], key=lambda item: item.name.lower())
    except OSError:
        return []


def _latest(runtime: Path, state_id: str) -> tuple[Path, dict[str, Any]]:
    path = runtime / "state" / state_id / "latest.json"
    return path, read_json(path)


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _category_record(
    state_id: str,
    *,
    category: str,
    reason: str,
    latest_path: Path,
    status: str = "",
    exists: bool | None = None,
    task_id: str = "",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "state_id": state_id,
        "category": category,
        "reason": reason,
        "latest_path": str(latest_path),
        "exists": latest_path.is_file() if exists is None else exists,
        "status": status,
        "task_id": task_id,
        "evidence": evidence or {},
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def _current_workflow(runtime: Path) -> dict[str, str]:
    _, current = _latest(runtime, "current_333_run_index")
    return {
        "workflow_id": str(current.get("workflow_id") or ""),
        "workflow_run_id": str(current.get("workflow_run_id") or ""),
        "status": str(current.get("status") or ""),
        "mainline_candidate_count": str(_nested(current, "temporal", "mainline_candidate_count") or ""),
        "running_workflow_count": str(_nested(current, "temporal", "running_workflow_count") or ""),
    }


def provider_lane_index_status(runtime: Path) -> tuple[Path, dict[str, Any]]:
    path = (
        runtime
        / "state"
        / "codex_native_provider_scheduler_phase4_20260704"
        / "provider_lane_index"
        / "latest.json"
    )
    return path, read_json(path)


def classify_known_state(runtime: Path, state_id: str) -> dict[str, Any] | None:
    latest_path, payload = _latest(runtime, state_id)
    status = str(payload.get("status") or "")
    current = _current_workflow(runtime)

    if state_id == "mature_binding_gap_ledger":
        return _category_record(
            state_id,
            category="bound",
            reason="this task-scoped ledger is the p0_005 deliverable and verifier target",
            latest_path=latest_path,
            status=status or "mature_binding_gap_ledger_ready",
            task_id=TASK_ID,
        )

    if state_id == "current_333_run_index":
        mainline_count = int(_nested(payload, "temporal", "mainline_candidate_count") or 0)
        worker_status = str(_nested(payload, "worker_status", "status") or "")
        bound = status == "current_333_run_index_ready" and mainline_count == 1 and worker_status == "polling"
        return _category_record(
            state_id,
            category="bound" if bound else "installed_not_bound",
            reason="exactly one running 333 mainline with polling worker"
            if bound
            else "current 333 index is missing a single polling mainline",
            latest_path=latest_path,
            status=status,
            evidence={
                "workflow_id": str(payload.get("workflow_id") or ""),
                "workflow_run_id": str(payload.get("workflow_run_id") or ""),
                "mainline_candidate_count": mainline_count,
                "worker_status": worker_status,
            },
        )

    if state_id == "artifact_acceptance_queue":
        binding_or_delivery = int(payload.get("accepted_for_binding_count") or 0) + int(
            payload.get("accepted_for_delivery_count") or 0
        )
        return _category_record(
            state_id,
            category="bound" if binding_or_delivery else "installed_not_bound",
            reason="AAQ accepts binding/delivery decisions and is not next_frontier-only"
            if binding_or_delivery
            else "AAQ has no binding/delivery acceptance in latest snapshot",
            latest_path=latest_path,
            status=status,
            evidence={
                "accepted_for_binding_count": int(payload.get("accepted_for_binding_count") or 0),
                "accepted_for_delivery_count": int(payload.get("accepted_for_delivery_count") or 0),
                "accepted_for_next_frontier_only": payload.get("accepted_for_next_frontier_only"),
            },
        )

    if state_id == "task_contract_router":
        contract_id = str(payload.get("contract_id") or "")
        ready = (
            status == "execution_contract_ready"
            and contract_id == TASK_ID
            and str(payload.get("workflow_run_id") or "")
            and payload.get("validation", {}).get("passed") is True
        )
        return _category_record(
            state_id,
            category="bound" if ready else "installed_not_bound",
            reason="TaskContractRouter consumed mature_bind_queue[1] and emitted p0_005 contract"
            if ready
            else "TaskContractRouter latest is not the p0_005 contract or is not workflow-bound",
            latest_path=latest_path,
            status=status,
            evidence={
                "contract_id": contract_id,
                "workflow_id": str(payload.get("workflow_id") or ""),
                "workflow_run_id": str(payload.get("workflow_run_id") or ""),
                "validation_passed": payload.get("validation", {}).get("passed"),
            },
        )

    if state_id == "default_main_loop_trigger_candidate":
        runtime_enforced = payload.get("runtime_enforced") is True
        trigger_installed = payload.get("trigger_installed") is True
        return _category_record(
            state_id,
            category="bound" if runtime_enforced and trigger_installed else "installed_not_bound",
            reason="default main loop trigger is runtime enforced"
            if runtime_enforced and trigger_installed
            else "default main loop trigger is present but not runtime_enforced/installed",
            latest_path=latest_path,
            status=status,
            evidence={
                "runtime_enforced": payload.get("runtime_enforced"),
                "trigger_installed": payload.get("trigger_installed"),
                "root_loop_every_wave_enforced": payload.get("root_loop_every_wave_enforced"),
                "base_tick_adoption_state": payload.get("base_tick_adoption_state"),
            },
        )

    if state_id == "codex_s_main_execution_loop_tick":
        adoption = str(payload.get("adoption_state") or "")
        bound = adoption == "runtime_enforced_hot_path_hooked"
        return _category_record(
            state_id,
            category="bound" if bound else "installed_not_bound",
            reason="main execution loop tick is runtime-enforced"
            if bound
            else "main execution loop tick is still verifier_ready_but_not_hooked",
            latest_path=latest_path,
            status=status,
            evidence={
                "adoption_state": adoption,
                "invoked_worker_dispatch_ledger_status": str(
                    _nested(payload, "invoked_worker_dispatch_ledger", "status") or ""
                ),
            },
        )

    if state_id == "worker_dispatch_ledger":
        adoption = str(payload.get("adoption_state") or "")
        entry_adoptions = sorted(
            {
                str(entry.get("adoption_state") or "")
                for entry in payload.get("dispatch_entries", [])
                if isinstance(entry, dict)
            }
        )
        spawned = int(_nested(payload, "summary", "spawned_external_agent_count") or 0)
        contradiction = (
            adoption == "runtime_enforced_hot_path_hooked"
            and "verifier_ready_but_not_hooked" in entry_adoptions
        )
        return _category_record(
            state_id,
            category="installed_not_bound" if contradiction or spawned == 0 else "bound",
            reason="top-level claims runtime_enforced_hot_path_hooked while entries remain verifier_ready_but_not_hooked"
            if contradiction
            else "worker dispatch ledger has spawned worker evidence",
            latest_path=latest_path,
            status=status,
            evidence={
                "adoption_state": adoption,
                "entry_adoption_states": entry_adoptions,
                "spawned_external_agent_count": spawned,
                "succeeded_count": int(payload.get("succeeded_count") or 0),
            },
        )

    if state_id == "root_intent_loop_driver":
        workflow_id = str(payload.get("workflow_id") or _nested(payload, "temporal", "workflow_id") or "")
        workflow_run_id = str(payload.get("workflow_run_id") or _nested(payload, "temporal", "workflow_run_id") or "")
        drift = bool(
            workflow_id
            and current["workflow_id"]
            and (workflow_id != current["workflow_id"] or workflow_run_id != current["workflow_run_id"])
        )
        return _category_record(
            state_id,
            category="installed_not_bound" if drift or not workflow_run_id else "bound",
            reason="driver latest is bound to an old or empty workflow/run instead of the live r9 current index"
            if drift or not workflow_run_id
            else "driver latest is bound to the current workflow/run",
            latest_path=latest_path,
            status=status,
            evidence={
                "driver_workflow_id": workflow_id,
                "driver_workflow_run_id": workflow_run_id,
                "current_workflow_id": current["workflow_id"],
                "current_workflow_run_id": current["workflow_run_id"],
            },
        )

    if state_id == "codex_333_stateful_continuity_router":
        text = json.dumps(payload, ensure_ascii=False)
        stale_worker_blocker = (
            "TEMPORAL_WORKER_NOT_POLLING" in text
            and read_json(runtime / "state" / "current_333_run_index" / "latest.json")
            .get("worker_status", {})
            .get("status")
            == "polling"
        )
        source_package_id = str(payload.get("source_package_id") or "")
        return _category_record(
            state_id,
            category="installed_not_bound" if stale_worker_blocker else "bound",
            reason="continuity router read current three-text package but still carries stale TEMPORAL_WORKER_NOT_POLLING blocker"
            if stale_worker_blocker
            else "continuity router has no stale worker blocker in latest",
            latest_path=latest_path,
            status=status,
            evidence={
                "source_package_id": source_package_id,
                "stale_temporal_worker_not_polling": stale_worker_blocker,
            },
        )

    if state_id == "source_ledger":
        text = json.dumps(payload, ensure_ascii=False)
        has_current_three_text = "current_p0_three_text_20260707" in text or "02_P0_底座全自动任务落地_20260707" in text
        return _category_record(
            state_id,
            category="bound" if has_current_three_text else "installed_not_bound",
            reason="SourceLedger contains current three-text package entries"
            if has_current_three_text
            else "SourceLedger latest does not contain the current three-text intake package",
            latest_path=latest_path,
            status=status,
            evidence={
                "entry_count": int(payload.get("entry_count") or 0),
                "has_current_three_text": has_current_three_text,
            },
        )

    if state_id == "codex_333_control_vs_evidence_boundary_contract":
        text = json.dumps(payload, ensure_ascii=False)
        old_source = "20260705" in text or "新建文件夹" in text
        return _category_record(
            state_id,
            category="not_applicable",
            reason="boundary contract is a read-model guard; stale embedded snapshots are evidence-plane warnings, not hot-path authority",
            latest_path=latest_path,
            status=status,
            evidence={"contains_old_source_snapshot": old_source},
        )

    return None


def default_category(state_id: str, latest_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    lowered = state_id.lower()
    status = str(payload.get("status") or "")
    if "frontier" in lowered or "research" in lowered:
        return _category_record(
            state_id,
            category="P1_deferred",
            reason="research/frontier state is not a P0 mature binding target unless explicitly selected",
            latest_path=latest_path,
            status=status,
        )
    if "legacy" in lowered or "sleep_watch" in lowered or "audit" in lowered or "hygiene" in lowered:
        return _category_record(
            state_id,
            category="not_applicable",
            reason="legacy/audit/hygiene evidence surface is reference-only for this p0_005 binding ledger",
            latest_path=latest_path,
            status=status,
        )
    return _category_record(
        state_id,
        category="not_applicable",
        reason="state layer is not a current mature carrier binding target for p0_005",
        latest_path=latest_path,
        status=status,
    )


def classify_state_directories(runtime: Path) -> tuple[int, list[dict[str, Any]]]:
    preexisting = len(_state_dirs(runtime))
    output_paths(runtime)["state_dir"].mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for state_dir in _state_dirs(runtime):
        latest_path = state_dir / "latest.json"
        payload = read_json(latest_path)
        known = classify_known_state(runtime, state_dir.name)
        records.append(known or default_category(state_dir.name, latest_path, payload))
    records.sort(key=lambda item: (str(item["category"]), str(item["state_id"])))
    return preexisting, records


def missing_expected_targets(runtime: Path) -> list[dict[str, Any]]:
    target_categories = {
        "worker_brief_queue": "installed_not_bound",
        "bounded_result_wait": "installed_not_bound",
        "otel_collector": "P1_deferred",
        "otel_unified_trace_canary": "P1_deferred",
        "langfuse": "P1_deferred",
        "langfuse_live_trace_canary": "P1_deferred",
        "backstage_catalog": "P1_deferred",
    }
    missing: list[dict[str, Any]] = []
    for state_id, category in target_categories.items():
        latest_path = runtime / "state" / state_id / "latest.json"
        if latest_path.is_file():
            continue
        missing.append(
            _category_record(
                state_id,
                category=category,
                reason="expected carrier/default-route evidence is missing on disk",
                latest_path=latest_path,
                exists=False,
            )
        )
    return missing


def lying_layers(runtime: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item["state_id"]): item for item in records}
    current = _current_workflow(runtime)
    output: list[dict[str, Any]] = []

    worker = by_id.get("worker_dispatch_ledger")
    if worker and worker.get("category") == "installed_not_bound":
        output.append(
            {
                "state_id": "worker_dispatch_ledger",
                "claim": "top-level adoption_state says runtime_enforced_hot_path_hooked",
                "counter_evidence": "dispatch entries remain verifier_ready_but_not_hooked and spawned_external_agent_count is 0",
                "fix_shape": "bind real default worker result poll into every-wave dispatch before calling it hot path",
            }
        )

    driver = by_id.get("root_intent_loop_driver")
    if driver and driver.get("category") == "installed_not_bound":
        output.append(
            {
                "state_id": "root_intent_loop_driver",
                "claim": "driver latest looks like the active loop pointer",
                "counter_evidence": f"live current_333_run_index is {current['workflow_id']} / {current['workflow_run_id']}",
                "fix_shape": "make driver bind through current_333_run_index or stop exposing old workflow ids as active",
            }
        )

    continuity = by_id.get("codex_333_stateful_continuity_router")
    if continuity and continuity.get("category") == "installed_not_bound":
        output.append(
            {
                "state_id": "codex_333_stateful_continuity_router",
                "claim": "continuity router latest contains active blocker TEMPORAL_WORKER_NOT_POLLING",
                "counter_evidence": "current_333_run_index worker_status is polling with pollers_seen",
                "fix_shape": "clear stale blocker or regenerate continuity router from current 333 index",
            }
        )

    source = by_id.get("source_ledger")
    if source and source.get("category") == "installed_not_bound":
        output.append(
            {
                "state_id": "source_ledger",
                "claim": "current task package has been read",
                "counter_evidence": "SourceLedger latest lacks current_p0_three_text_20260707 entries",
                "fix_shape": "write three-text intake entries before WorkerBrief generation",
            }
        )

    boundary = by_id.get("codex_333_control_vs_evidence_boundary_contract")
    if boundary and boundary.get("evidence", {}).get("contains_old_source_snapshot") is True:
        output.append(
            {
                "state_id": "codex_333_control_vs_evidence_boundary_contract",
                "claim": "boundary contract reflects current control/evidence map",
                "counter_evidence": "embedded snapshot still references old 20260705/new-folder source package",
                "fix_shape": "regenerate the boundary read model after current source package intake",
            }
        )

    return output


def contract_and_package(runtime: Path, task_package_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    package = task_package_resolver.resolve_task_package(
        task_package_root,
        include_manifest_ref=True,
        runtime_root=runtime,
    )
    _, contract = _latest(runtime, "task_contract_router")
    return package, contract


def build_capability_manifest(runtime: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.capability_manifest.v1",
        "provider_id": "codex_s.mature_binding_gap_ledger",
        "status": "registered",
        "capability_kinds": [
            "mature_binding_gap_ledger",
            "runtime_state_classification",
            "truth_surface_contradiction_readback",
        ],
        "task_id": TASK_ID,
        "runtime_latest": payload.get("output_paths", {}).get("latest", ""),
        "readback": payload.get("output_paths", {}).get("readback", ""),
        "schema_ref": "contracts/schemas/codex_s_mature_binding_gap_ledger.v1.json",
        "verifier": "scripts/verify_mature_binding_gap_ledger.ps1",
        "default_role": "delivery_evidence_read_model_not_controller",
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def build_mature_binding_gap_ledger(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_package_root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    task_root = Path(task_package_root)
    paths = output_paths(runtime)
    preexisting_count, state_records = classify_state_directories(runtime)
    expected_missing = missing_expected_targets(runtime)
    category_counts = {category: 0 for category in CATEGORIES}
    for record in state_records:
        category_counts[str(record.get("category") or "")] = category_counts.get(str(record.get("category") or ""), 0) + 1
    accepted_tasks = task_package_resolver.runtime_accepted_task_decisions(runtime)
    package, contract = contract_and_package(runtime, task_root)
    provider_path, provider_lane = provider_lane_index_status(runtime)
    p0_004a_bound = (
        provider_lane.get("status") == "provider_lane_index_ready"
        and provider_lane.get("accepted_for") == "accepted_for_binding"
        and "p0_004a_provider_lane_index" in accepted_tasks
    )
    p0_005_contract_ready = (
        contract.get("status") == "execution_contract_ready"
        and contract.get("contract_id") == TASK_ID
        and bool(contract.get("workflow_run_id"))
        and contract.get("validation", {}).get("passed") is True
    )
    p0_005_selected_or_accepted = (
        package.get("next_mature_bind_task_id") == TASK_ID or TASK_ID in accepted_tasks
    )
    contradictions = lying_layers(runtime, state_records)
    critical_gaps = [
        record
        for record in [*state_records, *expected_missing]
        if record.get("state_id")
        in {
            "default_main_loop_trigger_candidate",
            "codex_s_main_execution_loop_tick",
            "worker_dispatch_ledger",
            "root_intent_loop_driver",
            "codex_333_stateful_continuity_router",
            "source_ledger",
            "worker_brief_queue",
            "bounded_result_wait",
            "otel_collector",
            "otel_unified_trace_canary",
            "langfuse",
            "langfuse_live_trace_canary",
            "backstage_catalog",
        }
        and record.get("category") in {"installed_not_bound", "P1_deferred"}
    ]
    validation_checks = {
        "all_existing_state_dirs_classified": len(state_records) == len(_state_dirs(runtime)),
        "required_categories_present": all(category in category_counts for category in CATEGORIES),
        "critical_gaps_identified": len(critical_gaps) >= 4,
        "lying_layers_identified": len(contradictions) >= 4,
        "p0_004a_provider_lane_index_bound": p0_004a_bound,
        "p0_005_contract_ready": p0_005_contract_ready,
        "task_package_router_selected_p0_005": p0_005_selected_or_accepted,
        "completion_claim_blocked": True,
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "mature_binding_gap_ledger_ready"
        if all(validation_checks.values())
        else "mature_binding_gap_ledger_blocked",
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "task_package_root": str(task_root),
        "preexisting_state_directory_count": preexisting_count,
        "state_directory_count": len(state_records),
        "classified_state_count": len(state_records),
        "category_counts": category_counts,
        "classification_categories": list(CATEGORIES),
        "classifications": state_records,
        "expected_missing_targets": expected_missing,
        "critical_gaps": critical_gaps,
        "lying_layers": contradictions,
        "current_workflow": _current_workflow(runtime),
        "task_contract_router": {
            "contract_id": str(contract.get("contract_id") or ""),
            "status": str(contract.get("status") or ""),
            "workflow_id": str(contract.get("workflow_id") or ""),
            "workflow_run_id": str(contract.get("workflow_run_id") or ""),
            "validation_passed": contract.get("validation", {}).get("passed") is True,
        },
        "task_package": {
            "next_mature_bind_task_id": str(package.get("next_mature_bind_task_id") or ""),
            "runtime_acceptance_overlay_enabled": package.get("runtime_acceptance_overlay_enabled") is True,
            "runtime_accepted_task_ids": package.get("runtime_accepted_task_ids") or [],
        },
        "p0_004a_provider_lane_index": {
            "bound": p0_004a_bound,
            "latest_path": str(provider_path),
            "status": str(provider_lane.get("status") or ""),
            "accepted_for": str(provider_lane.get("accepted_for") or ""),
            "route_count": provider_lane.get("route_count"),
            "model_lane_count": provider_lane.get("model_lane_count"),
        },
        "p0_005": {
            "mature_binding_gap_ledger_ready": all(validation_checks.values()),
            "success_field": "mature_binding_gap_ledger_ready",
            "success_decision": "accepted_for_delivery",
            "deliverable": "runtime state binding gap ledger plus Chinese readback",
        },
        "next_machine_actions": [
            {
                "order": 1,
                "task_id": "p0_006_three_text_source_ledger_intake",
                "action": "write current three-text package into SourceLedger and WorkerBrief queue",
                "blocker_if_failed": "CURRENT_THREE_TEXT_NOT_IN_SOURCE_LEDGER",
            },
            {
                "order": 2,
                "task_id": "p0_007_default_main_loop_trigger_bind",
                "action": "bind default_main_loop_trigger_candidate into r9 every-wave Temporal path",
                "blocker_if_failed": "DEFAULT_MAIN_LOOP_TRIGGER_NOT_RUNTIME_ENFORCED",
            },
            {
                "order": 3,
                "task_id": "p0_008_worker_dispatch_real_receipt",
                "action": "replace ledger self-written succeeded counts with real WorkerBrief -> ProviderScheduler -> worker receipt",
                "blocker_if_failed": "WORKER_DISPATCH_LEDGER_HAS_NO_EXTERNAL_RECEIPT",
            },
        ],
        "acceptance": {
            "artifact_kind": "mature_binding_gap_ledger",
            "accepted_for": "accepted_for_delivery",
            "artifact_acceptance_decision": "accepted_for_delivery",
            "accepted_by_aaq_required": True,
        },
        "output_paths": {
            "latest": str(paths["latest"]),
            "record": str(paths["record"]),
            "readback": str(paths["readback"]),
            "capability_manifest": str(paths["capability_manifest"]),
        },
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }
    payload["payload_sha256"] = sha256_json({key: value for key, value in payload.items() if key != "payload_sha256"})
    payload["validation"] = {
        "passed": all(validation_checks.values()),
        "checks": validation_checks,
        "validated_at": now_iso(),
    }
    manifest = build_capability_manifest(runtime, payload)
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
        write_json(paths["capability_manifest"], manifest)
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    lines = [
        "# Mature Binding Gap Ledger",
        "",
        SENTINEL,
        "",
        "## 结论",
        "",
        f"- status: `{payload.get('status')}`",
        f"- mature_binding_gap_ledger_ready: `{payload.get('p0_005', {}).get('mature_binding_gap_ledger_ready')}`",
        f"- preexisting_state_directory_count: `{payload.get('preexisting_state_directory_count')}`",
        f"- scanned_state_directory_count: `{payload.get('state_directory_count')}`",
        f"- next_mature_bind_task_id: `{payload.get('task_package', {}).get('next_mature_bind_task_id')}`",
        f"- p0_005_contract_ready: `{payload.get('validation', {}).get('checks', {}).get('p0_005_contract_ready')}`",
        "",
        "## 哪层在撒谎",
        "",
    ]
    for item in payload.get("lying_layers", []):
        lines.extend(
            [
                f"- `{item.get('state_id')}`",
                f"  - claim: {item.get('claim')}",
                f"  - counter_evidence: {item.get('counter_evidence')}",
                f"  - fix_shape: {item.get('fix_shape')}",
            ]
        )
    lines.extend(
        [
            "",
            "## 分类计数",
            "",
        ]
    )
    for category, count in payload.get("category_counts", {}).items():
        lines.append(f"- {category}: {count}")
    lines.extend(
        [
            "",
            "## 关键缺口",
            "",
        ]
    )
    for item in payload.get("critical_gaps", [])[:20]:
        lines.append(f"- `{item.get('state_id')}` -> {item.get('category')}: {item.get('reason')}")
    lines.extend(
        [
            "",
            "## 下一机器动作",
            "",
        ]
    )
    for item in payload.get("next_machine_actions", []):
        lines.append(f"- {item.get('order')}. `{item.get('task_id')}`: {item.get('action')}")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 这份账本是 p0_005 交付物和读模型，不是控制面，不允许 completion claim。",
            "- 它把“已安装但未绑定”和“旧 evidence 误导”摊开，下一刀仍必须按队列显式绑定。",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mature-binding-gap-ledger")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-package-root", default=str(DEFAULT_TASK_PACKAGE_ROOT))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build_mature_binding_gap_ledger(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_package_root=args.task_package_root,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "state_directory_count": payload["state_directory_count"],
                "category_counts": payload["category_counts"],
                "lying_layer_count": len(payload["lying_layers"]),
                "critical_gap_count": len(payload["critical_gaps"]),
                "validation": payload["validation"],
                "latest": payload["output_paths"]["latest"],
                "readback": payload["output_paths"]["readback"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
