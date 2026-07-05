from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xinao.codex_s.default_main_loop_trigger_candidate.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
ADOPTION_STATE = "runtime_trigger_candidate_verifier_ready"
RUNTIME_ENFORCED_ADOPTION_STATE = "runtime_enforced"
TASK_SCOPED_TRIGGER_SCOPE = "default_main_loop_trigger_task_scoped_qwen_dp_worker_pool"
TASK_SCOPED_RUNTIME_SCOPE = "seed_cortex_default_main_loop_trigger_qwen_dp_worker_pool"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[2]
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")

MAIN_EXECUTION_LOOP = [
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave",
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


def repo_readback_write_enabled(runtime_root: Path) -> bool:
    flag = os.environ.get("XINAO_RUNTIME_REPO_READBACK_WRITE")
    if flag is not None:
        return flag.strip().lower() not in {"0", "false", "no", "off"}
    return runtime_root.resolve() == DEFAULT_RUNTIME.resolve()


def load_sibling_module(module_name: str):
    path = Path(__file__).resolve().parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_ref(path: Path) -> dict[str, Any]:
    ref: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ref.update({"json_valid": False, "json_error": str(exc)})
        return ref
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    service = (
        payload.get("service_entrypoint")
        if isinstance(payload.get("service_entrypoint"), dict)
        else {}
    )
    ref.update(
        {
            "json_valid": True,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "sentinel": payload.get("sentinel"),
            "validation_passed": validation.get("passed"),
            "adoption_state": payload.get("adoption_state"),
            "service_caller": service.get("caller"),
            "api_cli_adoption_state": service.get("api_cli_adoption_state"),
            "service_runtime_enforced": service.get("runtime_enforced"),
            "service_temporal_enforced": service.get("temporal_enforced"),
            "stop_hook_controller": service.get("stop_hook_controller"),
            "runtime_enforced": payload.get("runtime_enforced"),
            "trigger_installed": payload.get("trigger_installed"),
            "memory_promotion_allowed": payload.get("memory_promotion_allowed"),
            "policy_promotion_allowed": payload.get("policy_promotion_allowed"),
            "completion_claim_allowed": payload.get("completion_claim_allowed"),
            "not_execution_controller": payload.get("not_execution_controller"),
        }
    )
    return ref


def scheduler_lane_evidence_ref(path: Path) -> dict[str, Any]:
    ref = json_ref(path)
    if not ref.get("json_valid"):
        return ref
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ref
    actual_dispatch = (
        payload.get("actual_dispatch_refs")
        if isinstance(payload.get("actual_dispatch_refs"), dict)
        else {}
    )
    ref.update(
        {
            "lane_evidence_state": payload.get("lane_evidence_state"),
            "wave_id": payload.get("wave_id"),
            "scheduler_invoked": payload.get("scheduler_invoked"),
            "parent_dispatch_invoked": payload.get("parent_dispatch_invoked"),
            "activity_scope_scheduler_invoked": payload.get(
                "activity_scope_scheduler_invoked"
            ),
            "default_runtime_scheduler_invoked": payload.get(
                "default_runtime_scheduler_invoked"
            ),
            "runtime_enforced": payload.get("runtime_enforced"),
            "scheduler_spawned_lane_count": payload.get("scheduler_spawned_lane_count"),
            "dp_sidecar_execution_lanes_spawned": payload.get(
                "dp_sidecar_execution_lanes_spawned"
            ),
            "dp_sidecar_execution_modes_seen": payload.get(
                "dp_sidecar_execution_modes_seen"
            )
            if isinstance(payload.get("dp_sidecar_execution_modes_seen"), list)
            else [],
            "named_blocker": payload.get("named_blocker"),
            "refs_are_not_execution_controllers": actual_dispatch.get(
                "refs_are_not_execution_controllers"
            ),
        }
    )
    evidence_refs = (
        payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), dict) else {}
    )
    runtime_wave_record = str(evidence_refs.get("runtime_wave_record") or "")
    runtime_wave_digest = str(evidence_refs.get("runtime_wave_record_digest_sha256") or "")
    ref["runtime_wave_record"] = runtime_wave_record
    ref["runtime_wave_record_exists"] = (
        Path(runtime_wave_record).is_file() if runtime_wave_record else False
    )
    ref["runtime_wave_record_digest_sha256"] = runtime_wave_digest
    ref["runtime_wave_record_digest_bound"] = len(runtime_wave_digest) == 64
    lane_refs = (
        actual_dispatch.get("scheduler_spawned_lane_refs")
        if isinstance(actual_dispatch.get("scheduler_spawned_lane_refs"), list)
        else []
    )
    ref["current_parent_codex_lane_count"] = len(
        [
            lane
            for lane in lane_refs
            if isinstance(lane, dict)
            and lane.get("lane_kind") == "current_parent_codex_subagent"
        ]
    )
    ref["dp_sidecar_execution_lane_count"] = len(
        [
            lane
            for lane in lane_refs
            if isinstance(lane, dict)
            and lane.get("lane_kind") == "dp_sidecar_execution"
        ]
    )
    return ref


def gateway_scheduler_lane_providers(gateway: dict[str, Any] | Any) -> list[dict[str, Any]]:
    providers = gateway.get("providers", []) if isinstance(gateway, dict) else getattr(gateway, "providers", [])
    summaries: list[dict[str, Any]] = []
    wanted = {
        "activity_scoped_scheduler_lane_evidence",
        "actual_subagent_dispatch_evidence",
    }
    for provider in providers:
        if isinstance(provider, dict):
            kinds = [str(item) for item in provider.get("capability_kinds", [])]
            provider_id = str(provider.get("provider_id") or "")
            adoption_state = provider.get("adoption_state")
            runtime_enforced = provider.get("runtime_enforced")
            activity_scope_only = provider.get("activity_scope_only")
            default_runtime_scheduler_invoked = provider.get(
                "default_runtime_scheduler_invoked"
            )
            provider_invocation_performed = provider.get("provider_invocation_performed")
            runtime_enforced_scope = provider.get("runtime_enforced_scope")
            selected_provider_boundary = provider.get("selected_provider_boundary")
        else:
            kinds = [str(item) for item in getattr(provider, "capability_kinds", [])]
            provider_id = str(getattr(provider, "provider_id", "") or "")
            adoption_state = getattr(provider, "adoption_state", None)
            runtime_enforced = getattr(provider, "runtime_enforced", None)
            activity_scope_only = getattr(provider, "activity_scope_only", None)
            default_runtime_scheduler_invoked = getattr(
                provider, "default_runtime_scheduler_invoked", None
            )
            provider_invocation_performed = getattr(
                provider, "provider_invocation_performed", None
            )
            runtime_enforced_scope = getattr(provider, "runtime_enforced_scope", None)
            selected_provider_boundary = getattr(provider, "selected_provider_boundary", None)
        matched = sorted(wanted.intersection(kinds))
        if not matched:
            continue
        summaries.append(
            {
                "provider_id": provider_id,
                "matched_capability_kinds": matched,
                "adoption_state": adoption_state,
                "runtime_enforced": runtime_enforced,
                "runtime_enforced_scope": runtime_enforced_scope,
                "activity_scope_only": activity_scope_only,
                "default_runtime_scheduler_invoked": default_runtime_scheduler_invoked,
                "provider_invocation_performed": provider_invocation_performed,
                "selected_provider_boundary": selected_provider_boundary,
            }
        )
    return summaries


def output_paths(repo: Path, runtime: Path) -> dict[str, str]:
    return {
        "runtime_latest": str(runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "default_main_loop_trigger_candidate_20260702.md"
        ),
        "repo_readback": str(
            repo / "docs" / "current" / "CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_2026-07-02.md"
        ),
        "schema": str(
            repo / "contracts" / "schemas" / "codex_s_default_main_loop_trigger_candidate.v1.json"
        ),
        "writer": str(repo / "services" / "agent_runtime" / "default_main_loop_trigger_candidate.py"),
        "tests": str(repo / "tests" / "seedcortex" / "test_default_main_loop_trigger_candidate.py"),
        "verifier": str(repo / "scripts" / "verify_default_main_loop_trigger_candidate.ps1"),
    }


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _provider_lane_counts(phase1_payload: dict[str, Any]) -> dict[str, int]:
    counts = {
        "qwen_prepaid_cheap_worker": 0,
        "legacy.deepseek_dp_sidecar": 0,
    }
    lane_results = (
        phase1_payload.get("lane_results")
        if isinstance(phase1_payload.get("lane_results"), list)
        else []
    )
    for lane in lane_results:
        if not isinstance(lane, dict):
            continue
        provider = str(
            lane.get("selected_carrier_provider_id")
            or lane.get("provider")
            or ""
        )
        if provider == "qwen_prepaid_cheap_worker":
            counts["qwen_prepaid_cheap_worker"] += 1
        if provider == "legacy.deepseek_dp_sidecar":
            counts["legacy.deepseek_dp_sidecar"] += 1
    tier_usage = (
        phase1_payload.get("provider_tier_usage")
        if isinstance(phase1_payload.get("provider_tier_usage"), dict)
        else {}
    )
    counts["qwen_prepaid_cheap_worker"] = max(
        counts["qwen_prepaid_cheap_worker"],
        _as_int(tier_usage.get("qwen_prepaid_cheap_worker")),
    )
    counts["legacy.deepseek_dp_sidecar"] = max(
        counts["legacy.deepseek_dp_sidecar"],
        _as_int(tier_usage.get("deepseek_dp_external_model")),
        _as_int(tier_usage.get("legacy.deepseek_dp_sidecar")),
    )
    return counts


def invoke_provider_worker_pool_from_trigger(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    target_width: int,
    dynamic_width_decision: dict[str, Any] | None,
    max_parallel_workers: int | None,
    require_external_draft: bool,
    workflow_id: str,
    workflow_run_id: str,
    work_package: dict[str, Any] | None,
    write: bool,
) -> dict[str, Any]:
    module = load_sibling_module("modular_dynamic_worker_pool_phase1")
    package = work_package if isinstance(work_package, dict) else {}
    assignment_node_id = (
        module.assignment_dag_node_id_from_work_package(package)
        if package
        else module.ASSIGNMENT_DAG_NODE_ID
    )
    return module.run_wave(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        target_width=target_width,
        dynamic_width_decision=dynamic_width_decision,
        write=write,
        record_meta_rsi=False,
        force_local_dp_draft=False,
        require_external_draft=require_external_draft,
        max_parallel_workers=max_parallel_workers,
        runtime_enforced=True,
        runtime_enforced_scope=module.GLOBAL_DEFAULT_ENFORCED_SCOPE,
        while_chain_id=f"{wave_id}-default-main-loop-trigger",
        while_wave_index=1,
        while_wave_count=1,
        assignment_dag_node_id=assignment_node_id or module.ASSIGNMENT_DAG_NODE_ID,
        workflow_id=workflow_id or "default-main-loop-trigger-candidate",
        workflow_run_id=workflow_run_id or wave_id,
        work_package=package,
    )


def build_trigger_dynamic_width_decision(
    *,
    runtime: Path,
    wave_id: str,
    requested_target_width: int,
    max_parallel_workers: int | None,
    allocation_plan_activity: dict[str, Any] | None,
    write: bool,
) -> dict[str, Any]:
    phase1_module = load_sibling_module("modular_dynamic_worker_pool_phase1")
    phase3_module = load_sibling_module("temporal_activity_no_window_dp_worker_pool_phase3")
    paths = phase3_module.output_paths(runtime)
    queue = phase3_module.read_json(paths["event_queue_latest"])
    if not queue:
        queue = {"schema_version": "xinao.phase3.event_queue.empty.v1", "items": []}
    decision = phase3_module.compute_dynamic_width_decision(
        runtime=runtime,
        queue=queue,
        source_entry=phase1_module.scan_source_entry(),
        requested_target_width=int(requested_target_width or 0),
        max_parallel_workers=int(max_parallel_workers or 12),
    )
    allocation = (
        allocation_plan_activity
        if isinstance(allocation_plan_activity, dict)
        else {}
    )
    allocation_outputs = (
        allocation.get("output_paths")
        if isinstance(allocation.get("output_paths"), dict)
        else {}
    )
    allocation_validation = (
        allocation.get("validation")
        if isinstance(allocation.get("validation"), dict)
        else {}
    )
    allocation_inputs = {
        "allocation_plan_ref": str(
            allocation.get("allocation_plan_temporal_activity_latest_ref")
            or allocation.get("allocation_plan_latest_ref")
            or allocation_outputs.get("temporal_activity_latest")
            or allocation_outputs.get("latest")
            or ""
        ),
        "allocation_plan_target_width_source": str(
            allocation.get("target_width_source") or ""
        ),
        "allocation_plan_total_requested_width": int(
            allocation.get("total_requested_width") or 0
        ),
        "allocation_plan_validation_passed": (
            allocation.get("allocation_plan_validation_passed") is True
            or allocation_validation.get("passed") is True
        ),
        "allocation_plan_not_execution_controller": True,
    }
    width_inputs = (
        decision.get("width_decision_inputs")
        if isinstance(decision.get("width_decision_inputs"), dict)
        else {}
    )
    width_inputs["allocation_plan"] = allocation_inputs
    width_inputs["trigger_requested_target_width_cap"] = int(requested_target_width or 0)
    decision.update(
        {
            "wave_id": wave_id,
            "invoked_by": "default_main_loop_trigger_candidate",
            "allocation_plan_binding": allocation_inputs,
            "width_decision_inputs": width_inputs,
        }
    )
    phase3_module.write_dynamic_width_decision(
        runtime=runtime,
        wave_id=wave_id,
        decision=decision,
        write=write,
    )
    return decision


def build_trigger_truth_chain(
    *,
    requested: bool,
    phase1_payload: dict[str, Any],
    wave_id: str,
) -> dict[str, Any]:
    if not requested:
        return {
            "schema_version": "xinao.codex_s.default_trigger_qwen_dp_truth_chain.v1",
            "requested": False,
            "ready": False,
            "named_blocker": "PROVIDER_WORKER_POOL_NOT_REQUESTED_BY_TRIGGER",
            "checks": {},
            "provider_lane_counts": {
                "qwen_prepaid_cheap_worker": 0,
                "legacy.deepseek_dp_sidecar": 0,
            },
        }

    artifact_acceptance = (
        phase1_payload.get("artifact_acceptance_queue")
        if isinstance(phase1_payload.get("artifact_acceptance_queue"), dict)
        else {}
    )
    runtime_truth = (
        phase1_payload.get("runtime_enforcement_truth_chain")
        if isinstance(phase1_payload.get("runtime_enforcement_truth_chain"), dict)
        else {}
    )
    python_carrier = (
        phase1_payload.get("python_carrier")
        if isinstance(phase1_payload.get("python_carrier"), dict)
        else {}
    )
    provider_lane_counts = _provider_lane_counts(phase1_payload)
    required_qwen = _as_int(phase1_payload.get("qwen_prepaid_first_required_count"))
    succeeded_qwen = _as_int(phase1_payload.get("qwen_prepaid_first_succeeded_count"))
    accepted_count = _as_int(artifact_acceptance.get("accepted_artifact_count"))
    unique_accepted_count = _as_int(
        artifact_acceptance.get("unique_accepted_artifact_count")
    )
    completed_width = _as_int(phase1_payload.get("actual_completed_width"))
    ledger_succeeded = _as_int(
        phase1_payload.get("worker_dispatch_ledger_succeeded_count")
    )
    checks = {
        "provider_worker_pool_invoked_by_trigger": bool(phase1_payload),
        "same_wave_id": str(phase1_payload.get("wave_id") or "") == wave_id,
        "phase1_validation_passed": phase1_payload.get("validation", {}).get("passed")
        is True,
        "provider_scheduler_default_layer_ready": phase1_payload.get(
            "default_route_binding",
            {},
        )
        .get("provider_scheduler_default_layer", {})
        .get("status")
        == "ready",
        "qwen_cheap_first_required_attempts_succeeded": required_qwen > 0
        and succeeded_qwen == required_qwen,
        "deepseek_dp_lane_observed": provider_lane_counts[
            "legacy.deepseek_dp_sidecar"
        ]
        > 0,
        "worker_dispatch_ledger_succeeded_matches_completed": phase1_payload.get(
            "worker_dispatch_ledger_succeeded_matches_completed"
        )
        is True,
        "worker_dispatch_ledger_count_aligned": completed_width > 0
        and ledger_succeeded == completed_width,
        "artifact_acceptance_unique_count_positive": unique_accepted_count > 0,
        "artifact_acceptance_count_is_unique": accepted_count == unique_accepted_count,
        "runtime_enforced_write_gate_passed": runtime_truth.get("ready") is True
        and phase1_payload.get("runtime_enforced") is True,
        "s_venv_python_carrier_used": python_carrier.get("using_expected_python")
        is True,
    }
    ready = all(checks.values())
    return {
        "schema_version": "xinao.codex_s.default_trigger_qwen_dp_truth_chain.v1",
        "requested": True,
        "ready": ready,
        "named_blocker": "" if ready else "DEFAULT_TRIGGER_QWEN_DP_TRUTH_CHAIN_NOT_READY",
        "checks": checks,
        "phase1_wave_id": str(phase1_payload.get("wave_id") or ""),
        "phase1_status": str(phase1_payload.get("status") or ""),
        "phase1_runtime_enforced": phase1_payload.get("runtime_enforced") is True,
        "phase1_runtime_enforced_scope": str(
            phase1_payload.get("runtime_enforced_scope") or ""
        ),
        "actual_dispatched_width": _as_int(
            phase1_payload.get("actual_dispatched_width")
        ),
        "actual_completed_width": completed_width,
        "worker_dispatch_ledger_succeeded_count": ledger_succeeded,
        "unique_accepted_artifact_count": unique_accepted_count,
        "accepted_artifact_count": accepted_count,
        "qwen_prepaid_first_required_count": required_qwen,
        "qwen_prepaid_first_succeeded_count": succeeded_qwen,
        "provider_lane_counts": provider_lane_counts,
        "provider_tier_usage": phase1_payload.get("provider_tier_usage") or {},
        "can_invoke_now": phase1_payload.get("can_invoke_now") or {},
        "evidence_refs": {
            "phase1_latest": phase1_payload.get("evidence_refs", {}).get(
                "runtime_latest",
                "",
            ),
            "worker_dispatch_ledger_latest": phase1_payload.get(
                "evidence_refs",
                {},
            ).get("worker_dispatch_ledger_latest", ""),
            "artifact_acceptance_queue_latest": phase1_payload.get(
                "evidence_refs",
                {},
            ).get("artifact_acceptance_queue_latest", ""),
            "merge_artifact": phase1_payload.get("merge_artifact", ""),
        },
    }


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "codex-s-main-execution-wave-20260702",
    codex_subagents: list[str] | None = None,
    service: Any | None = None,
    bind_provider_worker_pool: bool = False,
    phase1_target_width: int = 24,
    phase1_max_parallel_workers: int | None = 12,
    phase1_require_external_draft: bool = True,
    allocation_plan_activity: dict[str, Any] | None = None,
    dynamic_width_decision: dict[str, Any] | None = None,
    work_package: dict[str, Any] | None = None,
    workflow_id: str = "",
    workflow_run_id: str = "",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(repo, runtime)
    subagents = [item for item in (codex_subagents or []) if item.strip()]

    metaminute_module = load_sibling_module("metaminute_preflight_reflection")
    max_benefit_module = load_sibling_module("max_benefit_dynamic_parallelism")
    metaminute = metaminute_module.build(
        trigger="before_new_parallel_wave",
        current_user_object="Seed Cortex S no-stop same-source implementation task",
        latest_user_delta=(
            "bind callable service tick and durable packet into a default main-loop "
            "trigger candidate without claiming runtime_enforced"
        ),
        repo_root=repo,
        runtime_root=runtime,
        write=write,
    )

    if service is None:
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime)
    tick = service.main_execution_loop_tick(
        anchor_package_root=str(anchor_package_root),
        wave_id=wave_id,
        codex_subagents=subagents,
        write_runtime=write,
    )
    state = runtime / "state"
    user_correction_service_latest = (
        state / "seed_lab_user_correction_runtime" / "service_entrypoint_latest.json"
    )
    user_correction_refs = {
        "service_entrypoint_ref": json_ref(user_correction_service_latest),
        "correction_intake_ref": json_ref(
            state / "seed_lab_correction_intake" / "latest.json"
        ),
        "experiment_review_view_ref": json_ref(
            state / "seed_lab_experiment_review_view" / "latest.json"
        ),
        "replay_court_ref": json_ref(state / "seed_lab_replay_court" / "latest.json"),
        "explicit_service_api_candidate": True,
        "invoked_by_default_trigger": False,
        "runtime_enforced": False,
        "trigger_installed": False,
        "memory_promotion_allowed": False,
        "policy_promotion_allowed": False,
        "completion_claim_allowed": False,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
    }
    packet = service.durable_parallel_wave_packet(
        wave_id=wave_id,
        codex_subagents=subagents,
        write_runtime=write,
    )
    provider_worker_pool_payload: dict[str, Any] = {}
    provider_worker_pool_dynamic_width_decision: dict[str, Any] = {}
    if bind_provider_worker_pool:
        provider_worker_pool_dynamic_width_decision = (
            dynamic_width_decision
            if isinstance(dynamic_width_decision, dict)
            and dynamic_width_decision.get("target_width")
            else build_trigger_dynamic_width_decision(
                runtime=runtime,
                wave_id=wave_id,
                requested_target_width=phase1_target_width,
                max_parallel_workers=phase1_max_parallel_workers,
                allocation_plan_activity=allocation_plan_activity,
                write=write,
            )
        )
        provider_worker_pool_payload = invoke_provider_worker_pool_from_trigger(
            runtime=runtime,
            repo=repo,
            wave_id=wave_id,
            target_width=phase1_target_width,
            dynamic_width_decision=provider_worker_pool_dynamic_width_decision,
            max_parallel_workers=phase1_max_parallel_workers,
            require_external_draft=phase1_require_external_draft,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            work_package=work_package,
            write=write,
        )
    gateway = service.capability_gateway_snapshot(write_runtime=write)
    max_benefit = max_benefit_module.build(repo_root=repo, runtime_root=runtime, write=write)

    main_service_latest = state / "codex_s_main_execution_loop_tick" / "service_entrypoint_latest.json"
    durable_service_latest = state / "durable_parallel_wave_packet" / "service_entrypoint_latest.json"
    main_base_latest = state / "codex_s_main_execution_loop_tick" / "latest.json"
    durable_base_latest = state / "durable_parallel_wave_packet" / "latest.json"
    gateway_latest = state / "capability_gateway" / "latest.json"
    max_benefit_latest = state / "max_benefit_dynamic_parallelism" / "latest.json"
    metaminute_latest = state / "metaminute_preflight_reflection" / "latest.json"
    scheduler_invocation_latest = state / "scheduler_invocation_packet" / "latest.json"
    scheduler_invocation_service_latest = (
        state / "scheduler_invocation_packet" / "service_entrypoint_latest.json"
    )
    scheduler_lane_current_wave_latest = (
        state / "scheduler_spawned_lane_evidence" / "current_wave_latest.json"
    )
    scheduler_lane_activity_scoped_latest = (
        state / "scheduler_spawned_lane_evidence" / "activity_scoped_latest.json"
    )
    modular_worker_pool_trigger_latest = (
        state / "modular_dynamic_worker_pool_phase1" / "trigger_binding" / "latest.json"
    )
    modular_worker_pool_latest = state / "modular_dynamic_worker_pool_phase1" / "latest.json"

    scheduler_packet_module = load_sibling_module("scheduler_invocation_packet")
    scheduler_lane_module = load_sibling_module("scheduler_spawned_lane_evidence")
    current_wave_lanes: list[str] = []
    for item in subagents:
        raw = item.strip()
        if not raw:
            continue
        agent_id = raw.split(":", 1)[0].strip()
        if agent_id:
            current_wave_lanes.append(f"current_parent_codex_subagent:{agent_id}")
    if not current_wave_lanes:
        current_wave_lanes.append("current_parent_codex_subagent:codex_s_current_worker")
    current_wave_lanes.append(
        f"dp_sidecar_execution:{wave_id}:dp_sidecar_execution_port"
    )
    scheduler_packet_module.build_scheduler_invocation_packet(
        runtime_root=runtime,
        repo_root=repo,
        spawned_lanes=current_wave_lanes,
        current_parent_codex_invocation_ref=f"current_parent_codex_dispatch:{wave_id}",
        dp_launcher_ref=f"deepseek-dp-launcher:{wave_id}",
        write=write,
    )
    scheduler_lane_module.build_scheduler_spawned_lane_evidence(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        scheduler_invocation_ref=scheduler_invocation_latest,
        output_latest=scheduler_lane_current_wave_latest,
        write=write,
    )

    packet_checks = packet.get("validation", {}).get("checks", {}) if isinstance(packet.get("validation"), dict) else {}
    tick_service = (
        tick.get("service_entrypoint")
        if isinstance(tick.get("service_entrypoint"), dict)
        else {}
    )
    packet_service = (
        packet.get("service_entrypoint")
        if isinstance(packet.get("service_entrypoint"), dict)
        else {}
    )
    gateway_providers = gateway.get("providers", []) if isinstance(gateway, dict) else getattr(gateway, "providers", [])
    provider_ids = []
    phase1_gateway_provider: dict[str, Any] = {}
    for provider in gateway_providers:
        if isinstance(provider, dict):
            provider_id = provider.get("provider_id")
        else:
            provider_id = getattr(provider, "provider_id", "")
        if provider_id:
            provider_ids.append(str(provider_id))
        if provider_id == "codex_s.modular_dynamic_worker_pool_phase1" and isinstance(provider, dict):
            phase1_gateway_provider = provider
    scheduler_gateway_providers = gateway_scheduler_lane_providers(gateway)
    scheduler_current_wave_ref = scheduler_lane_evidence_ref(
        scheduler_lane_current_wave_latest
    )
    scheduler_activity_scoped_ref = scheduler_lane_evidence_ref(
        scheduler_lane_activity_scoped_latest
    )
    scheduler_invocation_packet_ref = json_ref(scheduler_invocation_latest)
    scheduler_invocation_service_ref = json_ref(scheduler_invocation_service_latest)
    current_wave_dp_modes = [
        str(item)
        for item in scheduler_current_wave_ref.get("dp_sidecar_execution_modes_seen", [])
        if isinstance(item, str)
    ]
    activity_scoped_dp_modes = [
        str(item)
        for item in scheduler_activity_scoped_ref.get(
            "dp_sidecar_execution_modes_seen", []
        )
        if isinstance(item, str)
    ]
    scheduler_spawned_lane_evidence_refs = {
        "current_wave_latest_ref": scheduler_current_wave_ref,
        "activity_scoped_latest_ref": scheduler_activity_scoped_ref,
        "candidate_discovery_scope": (
            "default_main_loop_trigger_candidate_ref_discovery_only"
        ),
        "current_wave_lane_evidence_state": scheduler_current_wave_ref.get(
            "lane_evidence_state"
        ),
        "activity_scoped_lane_evidence_state": scheduler_activity_scoped_ref.get(
            "lane_evidence_state"
        ),
        "codex_lane_evidence_discovered": (
            int(scheduler_current_wave_ref.get("current_parent_codex_lane_count") or 0)
            > 0
            or (
                scheduler_current_wave_ref.get("parent_dispatch_invoked") is True
                and int(
                    scheduler_current_wave_ref.get("scheduler_spawned_lane_count") or 0
                )
                > 0
            )
        ),
        "dp_sidecar_execution_modes_discovered": bool(
            set(current_wave_dp_modes + activity_scoped_dp_modes)
        ),
        "current_wave_dp_sidecar_execution_lanes_present": (
            scheduler_current_wave_ref.get("dp_sidecar_execution_lanes_spawned") is True
            or int(scheduler_current_wave_ref.get("dp_sidecar_execution_lane_count") or 0)
            > 0
        ),
        "current_wave_immutable_ref": scheduler_current_wave_ref.get(
            "runtime_wave_record"
        ),
        "current_wave_runtime_wave_record": scheduler_current_wave_ref.get(
            "runtime_wave_record"
        ),
        "current_wave_immutable_ref_exists": scheduler_current_wave_ref.get(
            "runtime_wave_record_exists"
        )
        is True,
        "current_wave_immutable_digest_sha256": scheduler_current_wave_ref.get(
            "runtime_wave_record_digest_sha256"
        ),
        "current_wave_runtime_wave_record_digest_sha256": scheduler_current_wave_ref.get(
            "runtime_wave_record_digest_sha256"
        ),
        "current_wave_selected_runtime_latest": str(scheduler_lane_current_wave_latest),
        "current_wave_immutable_digest_bound": scheduler_current_wave_ref.get(
            "runtime_wave_record_digest_bound"
        )
        is True,
        "dp_sidecar_execution_lanes_spawned": False,
        "default_runtime_scheduler_invoked": False,
        "runtime_enforced": False,
        "trigger_installed": False,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
    }
    actual_packet_dispatch = (
        packet.get("actual_dispatch_refs")
        if isinstance(packet.get("actual_dispatch_refs"), dict)
        else {}
    )
    trigger_truth_chain = build_trigger_truth_chain(
        requested=bind_provider_worker_pool,
        phase1_payload=provider_worker_pool_payload,
        wave_id=wave_id,
    )
    provider_worker_pool_ready = (
        bind_provider_worker_pool and trigger_truth_chain.get("ready") is True
    )
    adoption_boundary = {
        "adoption_state": RUNTIME_ENFORCED_ADOPTION_STATE
        if provider_worker_pool_ready
        else ADOPTION_STATE,
        "scope": TASK_SCOPED_TRIGGER_SCOPE
        if provider_worker_pool_ready
        else "default_main_loop_trigger_candidate_only",
        "state_is_scoped_candidate": not provider_worker_pool_ready,
        "task_scoped_runtime_enforcement": provider_worker_pool_ready,
        "not_global_runtime_enforcement": not provider_worker_pool_ready,
        "not_global_default_trigger": True,
        "root_loop_every_wave_enforced": False,
        "runtime_enforced": provider_worker_pool_ready,
        "runtime_enforced_scope": TASK_SCOPED_RUNTIME_SCOPE
        if provider_worker_pool_ready
        else "",
        "trigger_installed": provider_worker_pool_ready,
        "meaning_cn": (
            "runtime_enforced 表示本次 default trigger 调用已经在同一个 wave 内"
            "调用 ProviderScheduler/Qwen/DeepSeek worker pool，并通过 ledger+唯一AAQ"
            "真相链；它仍不是 RootIntentLoop 全局每波不可绕过 controller。"
            if provider_worker_pool_ready
            else "runtime_trigger_candidate_verifier_ready 表示 focused default_main_loop "
            "trigger candidate 的 schema/test/verifier/latest/readback 已通过；它是 "
            "scoped candidate，不是全局 runtime enforcement。"
        ),
        "missing_to_runtime_enforced_cn": (
            "还缺 Temporal/LangGraph/RootIntentLoop event history 证明未来每个 no-stop wave"
            "都不可绕过该 trigger；当前只证明本 task-scoped wave 已触发 Qwen/DP worker pool。"
            if provider_worker_pool_ready
            else "还需要 S runtime、Temporal 或 LangGraph 在真实 no-stop wave 中按默认路径"
            "逐波调用，并由 focused verifier 证明触发路径和 fan-in/evidence/readback 绑定。"
        ),
    }
    checks = {
        "metaminute_before_new_parallel_wave_invoked": (
            metaminute.get("trigger") == "before_new_parallel_wave"
            and metaminute.get("validation", {}).get("passed") is True
            and metaminute.get("intended_cognitive_budget_seconds") == 60
        ),
        "main_loop_service_invoked": (
            tick.get("schema_version") == "xinao.codex_s.main_execution_loop_tick.v1"
            and tick_service.get("caller") == "SeedCortexService.main_execution_loop_tick"
            and tick_service.get("runtime_enforced") is False
        ),
        "durable_packet_service_invoked": (
            packet.get("schema_version") == "xinao.codex_s.durable_parallel_wave_packet.v1"
            and packet_service.get("caller") == "SeedCortexService.durable_parallel_wave_packet"
            and packet_service.get("runtime_enforced") is False
            and packet_service.get("temporal_enforced") is False
        ),
        "capability_gateway_providers_visible": (
            "codex_s.main_execution_loop_tick_service" in provider_ids
            and "codex_s.durable_parallel_wave_packet_service" in provider_ids
            and "codex_s.seed_lab_user_correction_runtime_service" in provider_ids
        ),
        "modular_dynamic_worker_pool_phase1_provider_visible": (
            "codex_s.modular_dynamic_worker_pool_phase1" in provider_ids
        ),
        "scheduler_gateway_capabilities_visible": (
            any(
                "activity_scoped_scheduler_lane_evidence"
                in provider["matched_capability_kinds"]
                for provider in scheduler_gateway_providers
            )
            and any(
                "actual_subagent_dispatch_evidence"
                in provider["matched_capability_kinds"]
                for provider in scheduler_gateway_providers
            )
        ),
        "user_correction_runtime_refs_bound": (
            user_correction_refs["service_entrypoint_ref"].get("exists") is True
            and user_correction_refs["service_entrypoint_ref"].get("json_valid") is True
            and user_correction_refs["service_entrypoint_ref"].get("schema_version")
            == "xinao.codex_s.seed_lab_user_correction_runtime.v1"
            and user_correction_refs["service_entrypoint_ref"].get("validation_passed") is True
            and user_correction_refs["correction_intake_ref"].get("exists") is True
            and user_correction_refs["experiment_review_view_ref"].get("exists") is True
            and user_correction_refs["replay_court_ref"].get("exists") is True
        ),
        "user_correction_runtime_not_enforced": (
            user_correction_refs["invoked_by_default_trigger"] is False
            and user_correction_refs["service_entrypoint_ref"].get("runtime_enforced") is not True
            and user_correction_refs["service_entrypoint_ref"].get("service_runtime_enforced") is not True
            and user_correction_refs["service_entrypoint_ref"].get("trigger_installed") is not True
            and user_correction_refs["runtime_enforced"] is False
            and user_correction_refs["trigger_installed"] is False
            and user_correction_refs["memory_promotion_allowed"] is False
            and user_correction_refs["policy_promotion_allowed"] is False
            and user_correction_refs["completion_claim_allowed"] is False
            and user_correction_refs["refs_are_not_execution_controllers"] is True
        ),
        "max_benefit_refs_visible": (
            max_benefit.get("main_loop_service_entrypoint_refs", {}).get("provider_id")
            == "codex_s.main_execution_loop_tick_service"
            and max_benefit.get("durable_packet_service_entrypoint_refs", {}).get("provider_id")
            == "codex_s.durable_parallel_wave_packet_service"
        ),
        "actual_dispatch_refs_bound": (
            actual_packet_dispatch.get("codex_subagent_count") == len(subagents)
            and len(subagents) > 0
            and actual_packet_dispatch.get(
                "dp_sidecar_execution_callable_entrypoint_bound"
            )
            is True
            and actual_packet_dispatch.get("dp_sidecar_execution_port_runner_ref", {}).get(
                "exists"
            )
            is True
            and actual_packet_dispatch.get("dp_sidecar_execution_provider_ref", {}).get(
                "exists"
            )
            is True
            and actual_packet_dispatch.get(
                "dp_sidecar_execution_provider_manifest_ref", {}
            ).get("exists")
            is True
            and actual_packet_dispatch.get("refs_are_not_execution_controllers") is True
        ),
        "dp_sidecar_execution_callable_refs_bound": (
            actual_packet_dispatch.get("dp_sidecar_execution_callable_entrypoint_bound")
            is True
            and actual_packet_dispatch.get("dp_sidecar_execution_port_runner_ref", {}).get(
                "exists"
            )
            is True
            and actual_packet_dispatch.get("dp_sidecar_execution_provider_ref", {}).get(
                "exists"
            )
            is True
            and actual_packet_dispatch.get(
                "dp_sidecar_execution_provider_manifest_ref", {}
            ).get("exists")
            is True
        ),
        "scheduler_current_wave_evidence_bound": (
            scheduler_current_wave_ref.get("json_valid") is True
            and scheduler_current_wave_ref.get("scheduler_invoked") is True
            and scheduler_current_wave_ref.get("parent_dispatch_invoked") is True
            and int(scheduler_current_wave_ref.get("scheduler_spawned_lane_count") or 0)
            > 0
            and scheduler_current_wave_ref.get("default_runtime_scheduler_invoked")
            is False
            and scheduler_current_wave_ref.get("runtime_enforced") is False
            and scheduler_current_wave_ref.get("refs_are_not_execution_controllers")
            is True
        ),
        "scheduler_activity_scoped_evidence_bound": (
            scheduler_activity_scoped_ref.get("json_valid") is True
            and scheduler_activity_scoped_ref.get("scheduler_invoked") is True
            and scheduler_activity_scoped_ref.get("activity_scope_scheduler_invoked")
            is True
            and scheduler_activity_scoped_ref.get("default_runtime_scheduler_invoked")
            is False
            and scheduler_activity_scoped_ref.get("runtime_enforced") is False
            and scheduler_activity_scoped_ref.get("refs_are_not_execution_controllers")
            is True
        ),
        "scheduler_lane_refs_non_overclaiming": (
            scheduler_invocation_packet_ref.get("runtime_enforced") is False
            and scheduler_invocation_packet_ref.get("completion_claim_allowed") is False
            and scheduler_invocation_service_ref.get("service_runtime_enforced") is False
            and all(
                provider["runtime_enforced"] is not True
                and provider["default_runtime_scheduler_invoked"] is not True
                and provider["provider_invocation_performed"] is not True
                for provider in scheduler_gateway_providers
            )
        ),
        "scheduler_spawned_lane_evidence_refs_bound": (
            scheduler_spawned_lane_evidence_refs["current_wave_latest_ref"].get(
                "json_valid"
            )
            is True
            and scheduler_spawned_lane_evidence_refs["activity_scoped_latest_ref"].get(
                "json_valid"
            )
            is True
        ),
        "scheduler_current_wave_immutable_ref_bound": (
            scheduler_current_wave_ref.get("runtime_wave_record_exists") is True
            and scheduler_current_wave_ref.get("runtime_wave_record_digest_bound")
            is True
            and scheduler_current_wave_ref.get("wave_id") == wave_id
        ),
        "scheduler_spawned_lane_current_wave_found": (
            scheduler_spawned_lane_evidence_refs["current_wave_lane_evidence_state"]
            == "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
        ),
        "scheduler_spawned_lane_activity_scoped_found": (
            scheduler_spawned_lane_evidence_refs["activity_scoped_lane_evidence_state"]
            == "activity_scheduler_invoked_with_lane_refs_not_default_runtime"
        ),
        "codex_lane_evidence_discovered_by_candidate": (
            scheduler_spawned_lane_evidence_refs["codex_lane_evidence_discovered"]
            is True
        ),
        "dp_sidecar_execution_modes_discovered_by_candidate": (
            scheduler_spawned_lane_evidence_refs[
                "dp_sidecar_execution_modes_discovered"
            ]
            is True
        ),
        "scheduler_spawned_lane_evidence_not_default_runtime": (
            scheduler_spawned_lane_evidence_refs["default_runtime_scheduler_invoked"]
            is False
            and scheduler_spawned_lane_evidence_refs["runtime_enforced"] is False
            and scheduler_spawned_lane_evidence_refs["trigger_installed"] is False
            and scheduler_current_wave_ref.get("default_runtime_scheduler_invoked")
            is False
            and scheduler_activity_scoped_ref.get("default_runtime_scheduler_invoked")
            is False
        ),
        "provider_worker_pool_invocation_bound": (
            (not bind_provider_worker_pool)
            or trigger_truth_chain.get("checks", {}).get(
                "provider_worker_pool_invoked_by_trigger"
            )
            is True
        ),
        "provider_worker_pool_truth_chain_ready": (
            (not bind_provider_worker_pool) or trigger_truth_chain.get("ready") is True
        ),
        "qwen_cheap_first_bound_to_trigger_wave": (
            (not bind_provider_worker_pool)
            or trigger_truth_chain.get("checks", {}).get(
                "qwen_cheap_first_required_attempts_succeeded"
            )
            is True
        ),
        "deepseek_dp_bound_to_trigger_wave": (
            (not bind_provider_worker_pool)
            or trigger_truth_chain.get("checks", {}).get("deepseek_dp_lane_observed")
            is True
        ),
        "ledger_and_aaq_truth_chain_bound": (
            (not bind_provider_worker_pool)
            or (
                trigger_truth_chain.get("checks", {}).get(
                    "worker_dispatch_ledger_count_aligned"
                )
                is True
                and trigger_truth_chain.get("checks", {}).get(
                    "artifact_acceptance_count_is_unique"
                )
                is True
            )
        ),
        "poll_refs_bound": packet_checks.get("poll_refs_bound") is True,
        "fan_in_refs_bound": packet_checks.get("fan_in_refs_bound") is True,
        "evidence_and_readback_refs_bound": packet_checks.get("evidence_and_readback_refs_bound") is True,
        "stop_guards_not_main_loop": (
            tick.get("stop_guard_layers_are_main_execution_loop") is False
            and packet.get("stop_guard_layers_are_main_execution_loop") is False
        ),
        "runtime_enforcement_not_overclaimed": True,
        "old_5d33_not_authority": (
            packet.get("legacy_5d33_transport_pattern", {}).get("old_5d33_owner_allowed") is False
            and packet.get("legacy_5d33_transport_pattern", {}).get("old_pass_allowed") is False
            and packet.get("legacy_5d33_transport_pattern", {}).get("old_latest_json_authority_allowed") is False
        ),
        "adoption_state_boundary_scoped_candidate": (
            (
                adoption_boundary["adoption_state"] == ADOPTION_STATE
                and adoption_boundary["scope"] == "default_main_loop_trigger_candidate_only"
                and adoption_boundary["state_is_scoped_candidate"] is True
                and adoption_boundary["not_global_runtime_enforcement"] is True
                and adoption_boundary["runtime_enforced"] is False
                and adoption_boundary["trigger_installed"] is False
            )
            or (
                adoption_boundary["adoption_state"] == RUNTIME_ENFORCED_ADOPTION_STATE
                and adoption_boundary["scope"] == TASK_SCOPED_TRIGGER_SCOPE
                and adoption_boundary["task_scoped_runtime_enforcement"] is True
                and adoption_boundary["root_loop_every_wave_enforced"] is False
                and adoption_boundary["runtime_enforced"] is True
                and adoption_boundary["trigger_installed"] is True
            )
        ),
    }
    validation_passed = all(checks.values())
    effective_runtime_enforced = provider_worker_pool_ready and validation_passed
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "status": (
            "default_main_loop_trigger_task_scoped_runtime_enforced"
            if effective_runtime_enforced
            else "default_main_loop_trigger_candidate_verifier_ready"
            if validation_passed
            else "default_main_loop_trigger_candidate_blocked"
        ),
        "generated_at": now_iso(),
        "adoption_state": RUNTIME_ENFORCED_ADOPTION_STATE
        if effective_runtime_enforced
        else ADOPTION_STATE,
        "adoption_state_boundary": adoption_boundary,
        "runtime_enforced": effective_runtime_enforced,
        "runtime_enforced_scope": TASK_SCOPED_RUNTIME_SCOPE
        if effective_runtime_enforced
        else "",
        "temporal_enforced": False,
        "trigger_installed": effective_runtime_enforced,
        "stop_hook_controller": False,
        "candidate_for": "main_execution_loop_default_trigger",
        "target_service_method": "SeedCortexService.main_execution_loop_tick",
        "target_durable_packet_service_method": "SeedCortexService.durable_parallel_wave_packet",
        "target_user_correction_runtime_service_method": (
            "SeedCortexService.seed_lab_user_correction_runtime"
        ),
        "target_fastapi_route": "POST /runtime/main-execution-loop-tick",
        "target_durable_packet_fastapi_route": "POST /runtime/durable-parallel-wave-packet",
        "target_user_correction_runtime_fastapi_route": (
            "POST /runtime/seed-lab-user-correction-runtime"
        ),
        "target_cli_command": "python -m xinao_seedlab.cli.__main__ main-execution-loop-tick",
        "target_durable_packet_cli_command": (
            "python -m xinao_seedlab.cli.__main__ durable-parallel-wave-packet"
        ),
        "target_user_correction_runtime_cli_command": (
            "python -m xinao_seedlab.cli.__main__ seed-lab-user-correction-runtime"
        ),
        "base_tick_adoption_state": tick.get("adoption_state"),
        "base_durable_packet_adoption_state": packet.get("adoption_state"),
        "api_cli_adoption_state": tick_service.get("api_cli_adoption_state"),
        "durable_packet_api_cli_adoption_state": packet_service.get("api_cli_adoption_state"),
        "user_correction_runtime_api_cli_adoption_state": user_correction_refs[
            "service_entrypoint_ref"
        ].get("api_cli_adoption_state"),
        "not_default_runtime_controller": True,
        "is_stop_guard_layer": False,
        "is_completion_gate": False,
        "stop_hook_dispatches_main_execution_loop": False,
        "ordinary_discussion_can_stop": True,
        "current_four_text_same_source_task_no_stop": True,
        "main_execution_loop": MAIN_EXECUTION_LOOP,
        "stop_guard_layers": [
            "live_backend_watch_front_gate",
            "source_anchor_gap_continuation",
        ],
        "stop_guard_layers_are_main_execution_loop": False,
        "default_trigger_candidate": {
            "trigger_scope": "candidate_default_hot_path_trigger_for_no_stop_seed_cortex_tasks",
            "candidate_invocation_shape": (
                "metaminute_before_new_parallel_wave -> SeedCortexService.main_execution_loop_tick "
                "-> SeedCortexService.durable_parallel_wave_packet -> capability_gateway_snapshot "
                "-> max_benefit_dynamic_parallelism -> optional ProviderScheduler/Qwen/DP worker pool"
            ),
            "runtime_enforced_requires": [
                "same-wave ProviderScheduler/Qwen/DP worker pool invocation",
                "worker_dispatch_ledger succeeded_count equals actual_completed_width",
                "ArtifactAcceptanceQueue unique accepted artifact count is positive and unique",
                "focused verifier proves no old 5d33 owner/PASS/latest authority",
            ],
            "adoption_state_meaning_cn": (
                "默认主执行循环触发候选可在显式绑定 provider worker pool 时进入"
                "task-scoped runtime_enforced；仍不是 Stop guard、completion gate 或全局 controller。"
            ),
        },
        "trigger_truth_chain": trigger_truth_chain,
        "provider_worker_pool_invocation": {
            "requested": bind_provider_worker_pool,
            "invoked": bool(provider_worker_pool_payload),
            "invoked_by": "services.agent_runtime.default_main_loop_trigger_candidate.build",
            "task_scoped_runtime_scope": TASK_SCOPED_RUNTIME_SCOPE
            if effective_runtime_enforced
            else "",
            "phase1_wave_id": str(provider_worker_pool_payload.get("wave_id") or ""),
            "phase1_status": str(provider_worker_pool_payload.get("status") or ""),
            "phase1_validation_passed": provider_worker_pool_payload.get(
                "validation",
                {},
            ).get("passed")
            is True,
            "evidence_refs": provider_worker_pool_payload.get("evidence_refs", {}),
            "dynamic_width_decision": provider_worker_pool_dynamic_width_decision,
            "dynamic_width_decision_ref": str(
                runtime
                / "state"
                / "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
                / "dynamic_width_decision"
                / "latest.json"
            )
            if provider_worker_pool_dynamic_width_decision
            else "",
            "target_width_source": str(
                provider_worker_pool_dynamic_width_decision.get(
                    "target_width_source"
                )
                or ""
            ),
            "resolved_target_width": int(
                provider_worker_pool_dynamic_width_decision.get("target_width") or 0
            )
            if provider_worker_pool_dynamic_width_decision
            else 0,
            "recomputed_each_wave": (
                provider_worker_pool_dynamic_width_decision.get(
                    "recomputed_each_wave"
                )
                is True
            )
            if provider_worker_pool_dynamic_width_decision
            else False,
        },
        "modular_dynamic_worker_pool_phase1_trigger_binding": {
            "task_id": "modular_dynamic_worker_pool_phase1_20260704",
            "hot_path_shape": "parallel_draft->merge->writer",
            "dp_worker_role": "draft_main_worker_pool",
            "gateway_provider_id": "codex_s.modular_dynamic_worker_pool_phase1",
            "gateway_provider_visible": (
                "codex_s.modular_dynamic_worker_pool_phase1" in provider_ids
            ),
            "gateway_provider_adoption_state": str(
                phase1_gateway_provider.get("adoption_state") or ""
            ),
            "gateway_provider_runtime_enforced": (
                phase1_gateway_provider.get("runtime_enforced") is True
            ),
            "gateway_provider_runtime_enforced_scope": str(
                phase1_gateway_provider.get("runtime_enforced_scope") or ""
            ),
            "trigger_binding_ref": json_ref(modular_worker_pool_trigger_latest),
            "latest_ref": json_ref(modular_worker_pool_latest),
            "search_is_main_task": False,
            "provider_probe_used_as_progress": False,
            "watchdog_role": "downgraded_side_evidence_not_mainline",
            "runtime_enforced": phase1_gateway_provider.get("runtime_enforced") is True,
            "trigger_installed": phase1_gateway_provider.get("trigger_installed") is True,
            "not_execution_controller": True,
        },
        "trigger_points_bound": {
            "before_new_parallel_wave": {
                "invoked": True,
                "metaminute_ref": str(metaminute_latest),
                "main_loop_service_ref": str(main_service_latest),
                "durable_packet_service_ref": str(durable_service_latest),
                "user_correction_runtime_service_ref": str(
                    user_correction_service_latest
                ),
                "scheduler_invocation_packet_ref": str(scheduler_invocation_latest),
                "scheduler_spawned_lane_evidence_current_wave_ref": str(
                    scheduler_lane_current_wave_latest
                ),
                "scheduler_spawned_lane_evidence_current_wave_immutable_ref": str(
                    scheduler_current_wave_ref.get("runtime_wave_record") or ""
                ),
                "scheduler_spawned_lane_evidence_current_wave_immutable_digest_sha256": str(
                    scheduler_current_wave_ref.get("runtime_wave_record_digest_sha256") or ""
                ),
                "scheduler_spawned_lane_evidence_activity_scoped_ref": str(
                    scheduler_lane_activity_scoped_latest
                ),
            },
            "after_user_correction_detected": {
                "machine_pointer_left": True,
                "service_ref": str(user_correction_service_latest),
                "runtime_enforced": False,
                "trigger_installed": False,
            },
            "window_start_first_hop": {
                "machine_pointer_left": True,
                "runtime_enforced": False,
            },
            "after_gate_hook_deny": {
                "machine_pointer_left": True,
                "runtime_enforced": False,
            },
            "before_final_pass_report": {
                "machine_pointer_left": True,
                "runtime_enforced": False,
            },
        },
        "actual_service_invocations": {
            "metaminute_preflight_reflection": json_ref(metaminute_latest),
            "main_execution_loop_tick_service": json_ref(main_service_latest),
            "main_execution_loop_tick_base": json_ref(main_base_latest),
            "durable_parallel_wave_packet_service": json_ref(durable_service_latest),
            "durable_parallel_wave_packet_base": json_ref(durable_base_latest),
            "capability_gateway": json_ref(gateway_latest),
            "max_benefit_dynamic_parallelism": json_ref(max_benefit_latest),
        },
        "user_correction_runtime_refs": user_correction_refs,
        "actual_dispatch_refs": {
            "codex_subagents": actual_packet_dispatch.get("codex_subagents", []),
            "codex_subagent_count": actual_packet_dispatch.get("codex_subagent_count", 0),
            "lane_assignments": actual_packet_dispatch.get("lane_assignments", []),
            "worker_dispatch_ledger_activity_ref": actual_packet_dispatch.get(
                "worker_dispatch_ledger_activity_ref", {}
            ),
            "main_execution_loop_tick_activity_ref": actual_packet_dispatch.get(
                "main_execution_loop_tick_activity_ref", {}
            ),
            "dp_sidecar_execution_port": actual_packet_dispatch.get("dp_sidecar_execution_port"),
            "dp_sidecar_execution_port_runner_ref": actual_packet_dispatch.get(
                "dp_sidecar_execution_port_runner_ref", {}
            ),
            "dp_sidecar_execution_provider_ref": actual_packet_dispatch.get(
                "dp_sidecar_execution_provider_ref", {}
            ),
            "dp_sidecar_execution_provider_manifest_ref": actual_packet_dispatch.get(
                "dp_sidecar_execution_provider_manifest_ref", {}
            ),
            "dp_sidecar_execution_callable_entrypoint_bound": actual_packet_dispatch.get(
                "dp_sidecar_execution_callable_entrypoint_bound"
            )
            is True,
            "dp_sidecar_execution_port_runner_latest": actual_packet_dispatch.get(
                "dp_sidecar_execution_port_runner_ref", {}
            ).get("path"),
            "dp_sidecar_execution_provider_latest": actual_packet_dispatch.get(
                "dp_sidecar_execution_provider_ref", {}
            ).get("path"),
            "dp_sidecar_execution_provider_manifest": actual_packet_dispatch.get(
                "dp_sidecar_execution_provider_manifest_ref", {}
            ).get("path"),
            "spawned_by_this_runner": False,
            "refs_are_evidence_only": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
        },
        "scheduler_lane_evidence_refs": {
            "scheduler_invocation_packet_latest": scheduler_invocation_packet_ref,
            "scheduler_invocation_packet_service_latest": scheduler_invocation_service_ref,
            "scheduler_spawned_lane_evidence_current_wave": scheduler_current_wave_ref,
            "scheduler_spawned_lane_evidence_activity_scoped": scheduler_activity_scoped_ref,
            "scheduler_spawned_lane_evidence_current_wave_immutable_ref": (
                scheduler_current_wave_ref.get("runtime_wave_record")
            ),
            "scheduler_spawned_lane_evidence_current_wave_immutable_digest_sha256": (
                scheduler_current_wave_ref.get("runtime_wave_record_digest_sha256")
            ),
            "scheduler_spawned_lane_evidence_current_wave_selected_runtime_latest": str(
                scheduler_lane_current_wave_latest
            ),
            "capability_gateway_scheduler_lane_providers": scheduler_gateway_providers,
            "bound_for_discovery_only": True,
            "spawned_by_this_runner": False,
            "default_runtime_scheduler_invoked": False,
            "runtime_enforced": False,
            "trigger_installed": False,
            "refs_are_evidence_only": True,
            "refs_are_not_completion_gates": True,
            "refs_are_not_execution_controllers": True,
        },
        "scheduler_spawned_lane_evidence_refs": scheduler_spawned_lane_evidence_refs,
        "poll_refs": packet.get("poll_refs", {}),
        "fan_in_refs": packet.get("fan_in_refs", {}),
        "evidence_refs": {
            "runtime_latest": paths["runtime_latest"],
            "schema": paths["schema"],
            "writer": paths["writer"],
            "tests": paths["tests"],
            "verifier": paths["verifier"],
            "metaminute_latest": str(metaminute_latest),
            "main_loop_service_latest": str(main_service_latest),
            "main_loop_base_latest": str(main_base_latest),
            "durable_packet_service_latest": str(durable_service_latest),
            "durable_packet_base_latest": str(durable_base_latest),
            "seed_lab_user_correction_runtime_service_latest": str(
                user_correction_service_latest
            ),
            "seed_lab_correction_intake_latest": str(
                state / "seed_lab_correction_intake" / "latest.json"
            ),
            "seed_lab_experiment_review_view_latest": str(
                state / "seed_lab_experiment_review_view" / "latest.json"
            ),
            "seed_lab_replay_court_latest": str(
                state / "seed_lab_replay_court" / "latest.json"
            ),
            "capability_gateway_latest": str(gateway_latest),
            "max_benefit_dynamic_parallelism_latest": str(max_benefit_latest),
            "scheduler_invocation_packet_latest": str(scheduler_invocation_latest),
            "scheduler_invocation_packet_service_latest": str(
                scheduler_invocation_service_latest
            ),
            "scheduler_spawned_lane_evidence_current_wave_latest": str(
                scheduler_lane_current_wave_latest
            ),
            "scheduler_spawned_lane_evidence_current_wave_immutable": str(
                scheduler_current_wave_ref.get("runtime_wave_record") or ""
            ),
            "scheduler_spawned_lane_evidence_current_wave_immutable_digest_sha256": str(
                scheduler_current_wave_ref.get("runtime_wave_record_digest_sha256") or ""
            ),
            "scheduler_spawned_lane_evidence_activity_scoped_latest": str(
                scheduler_lane_activity_scoped_latest
            ),
            "dp_sidecar_execution_port_runner_latest": str(
                actual_packet_dispatch.get("dp_sidecar_execution_port_runner_ref", {}).get(
                    "path"
                )
                or ""
            ),
            "dp_sidecar_execution_provider_latest": str(
                actual_packet_dispatch.get("dp_sidecar_execution_provider_ref", {}).get(
                    "path"
                )
                or ""
            ),
            "dp_sidecar_execution_provider_manifest": str(
                actual_packet_dispatch.get(
                    "dp_sidecar_execution_provider_manifest_ref", {}
                ).get("path")
                or ""
            ),
            "modular_dynamic_worker_pool_phase1_latest": str(modular_worker_pool_latest),
            "modular_dynamic_worker_pool_phase1_trigger_binding": str(
                modular_worker_pool_trigger_latest
            ),
            "default_trigger_qwen_dp_worker_pool_phase1_latest": str(
                trigger_truth_chain.get("evidence_refs", {}).get("phase1_latest") or ""
            ),
            "default_trigger_qwen_dp_worker_dispatch_ledger_latest": str(
                trigger_truth_chain.get("evidence_refs", {}).get(
                    "worker_dispatch_ledger_latest"
                )
                or ""
            ),
            "default_trigger_qwen_dp_aaq_latest": str(
                trigger_truth_chain.get("evidence_refs", {}).get(
                    "artifact_acceptance_queue_latest"
                )
                or ""
            ),
        },
        "readback_refs": {
            "runtime_readback_zh": paths["runtime_readback_zh"],
            "repo_readback": paths["repo_readback"],
            "main_loop_service_readback": str(
                runtime
                / "readback"
                / "zh"
                / "codex_s_main_execution_loop_tick_service_entrypoint_20260702.md"
            ),
            "durable_packet_service_readback": str(
                runtime / "readback" / "zh" / "durable_parallel_wave_packet_service_entrypoint_20260702.md"
            ),
            "seed_lab_user_correction_runtime_service_readback": str(
                runtime
                / "readback"
                / "zh"
                / "seed_lab_user_correction_runtime_service_entrypoint_20260702.md"
            ),
            "human_visible_readback_required": True,
        },
        "legacy_5d33_transport_pattern": packet.get("legacy_5d33_transport_pattern", {}),
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "phase1_data_chain_allowed": False,
        "positive_ev_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        write_json(Path(paths["runtime_latest"]), payload)
        readback = render_readback(payload)
        write_text(Path(paths["runtime_readback_zh"]), readback)
        if repo_readback_write_enabled(runtime):
            write_text(Path(paths["repo_readback"]), readback)
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    checks = payload["validation"]["checks"]
    adoption_boundary = payload["adoption_state_boundary"]
    truth_chain = payload.get("trigger_truth_chain", {})
    lines = [
        "# Codex S Default Main Loop Trigger Candidate readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload['status']}`",
        f"- adoption_state: `{payload['adoption_state']}`",
        f"- adoption_scope: `{adoption_boundary['scope']}`",
        f"- scoped_candidate: {adoption_boundary['state_is_scoped_candidate']}",
        f"- not_global_runtime_enforcement: {adoption_boundary['not_global_runtime_enforcement']}",
        f"- runtime_enforced: {payload['runtime_enforced']}",
        f"- runtime_enforced_scope: `{payload.get('runtime_enforced_scope', '')}`",
        f"- trigger_installed: {payload.get('trigger_installed')}",
        f"- temporal_enforced: {payload['temporal_enforced']}",
        f"- stop_hook_controller: {payload['stop_hook_controller']}",
        f"- trigger_truth_chain_ready: {truth_chain.get('ready')}",
        f"- qwen_prepaid_first_required_count: {truth_chain.get('qwen_prepaid_first_required_count')}",
        f"- qwen_prepaid_first_succeeded_count: {truth_chain.get('qwen_prepaid_first_succeeded_count')}",
        f"- dp_lane_count: {truth_chain.get('provider_lane_counts', {}).get('legacy.deepseek_dp_sidecar') if isinstance(truth_chain.get('provider_lane_counts'), dict) else None}",
        f"- ledger_succeeded_count: {truth_chain.get('worker_dispatch_ledger_succeeded_count')}",
        f"- unique_accepted_artifact_count: {truth_chain.get('unique_accepted_artifact_count')}",
        f"- actual_dispatch_refs_bound: {checks['actual_dispatch_refs_bound']}",
        f"- poll_refs_bound: {checks['poll_refs_bound']}",
        f"- fan_in_refs_bound: {checks['fan_in_refs_bound']}",
        f"- user_correction_runtime_refs_bound: {checks['user_correction_runtime_refs_bound']}",
        f"- user_correction_runtime_not_enforced: {checks['user_correction_runtime_not_enforced']}",
        f"- user_correction_runtime_enforced: {payload['user_correction_runtime_refs']['runtime_enforced']}",
        f"- scheduler_gateway_capabilities_visible: {checks['scheduler_gateway_capabilities_visible']}",
        f"- modular_dynamic_worker_pool_phase1_provider_visible: {checks['modular_dynamic_worker_pool_phase1_provider_visible']}",
        f"- scheduler_current_wave_evidence_bound: {checks['scheduler_current_wave_evidence_bound']}",
        f"- scheduler_activity_scoped_evidence_bound: {checks['scheduler_activity_scoped_evidence_bound']}",
        f"- scheduler_lane_refs_non_overclaiming: {checks['scheduler_lane_refs_non_overclaiming']}",
        f"- scheduler_spawned_lane_evidence_refs_bound: {checks['scheduler_spawned_lane_evidence_refs_bound']}",
        f"- codex_lane_evidence_discovered_by_candidate: {checks['codex_lane_evidence_discovered_by_candidate']}",
        f"- dp_sidecar_execution_modes_discovered_by_candidate: {checks['dp_sidecar_execution_modes_discovered_by_candidate']}",
        f"- scheduler_spawned_lane_evidence_not_default_runtime: {checks['scheduler_spawned_lane_evidence_not_default_runtime']}",
        f"- scheduler_lane_default_runtime_scheduler_invoked: {payload['scheduler_lane_evidence_refs']['default_runtime_scheduler_invoked']}",
        f"- scheduler_lane_runtime_enforced: {payload['scheduler_lane_evidence_refs']['runtime_enforced']}",
        f"- scheduler_current_wave_immutable_ref_bound: {checks['scheduler_current_wave_immutable_ref_bound']}",
        f"- dp_sidecar_execution_callable_refs_bound: {checks['dp_sidecar_execution_callable_refs_bound']}",
        f"- provider_worker_pool_truth_chain_ready: {checks['provider_worker_pool_truth_chain_ready']}",
        f"- qwen_cheap_first_bound_to_trigger_wave: {checks['qwen_cheap_first_bound_to_trigger_wave']}",
        f"- deepseek_dp_bound_to_trigger_wave: {checks['deepseek_dp_bound_to_trigger_wave']}",
        f"- ledger_and_aaq_truth_chain_bound: {checks['ledger_and_aaq_truth_chain_bound']}",
        f"- evidence_and_readback_refs_bound: {checks['evidence_and_readback_refs_bound']}",
        "- main_execution_loop: restore -> dispatch -> poll -> fan-in -> verify/evidence/readback -> recompute -> next_wave",
        "- modular_dynamic_worker_pool_phase1: parallel_draft->merge->writer binding ref 可见；DP=draft 主力，search/provider_probe 不是主任务。",
        "- stop_guard_layers 只防停，不是执行 controller。",
        f"- 能力采纳状态：{payload['adoption_state']}。",
        f"- 这代表：{adoption_boundary['meaning_cn']}",
        f"- 还缺什么才能进入下一状态：{adoption_boundary['missing_to_runtime_enforced_cn']}",
        "- 这个入口已经真实调用 service tick 和 durable packet；带 provider worker pool 绑定时还会同 wave 调用 Qwen/DP worker pool 并绑定 ledger/AAQ 真相链。",
        "",
        "## Evidence",
        "",
    ]
    for key, value in payload["evidence_refs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--bind-provider-worker-pool", action="store_true")
    parser.add_argument("--phase1-target-width", type=int, default=24)
    parser.add_argument("--phase1-max-parallel-workers", type=int, default=12)
    parser.add_argument("--allow-local-stub-acceptance", action="store_true")
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        codex_subagents=args.codex_subagent,
        bind_provider_worker_pool=args.bind_provider_worker_pool,
        phase1_target_width=args.phase1_target_width,
        phase1_max_parallel_workers=args.phase1_max_parallel_workers,
        phase1_require_external_draft=not args.allow_local_stub_acceptance,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "status": payload["status"],
                "adoption_state": payload["adoption_state"],
                "runtime_enforced": payload.get("runtime_enforced"),
                "trigger_installed": payload.get("trigger_installed"),
                "trigger_truth_chain_ready": payload.get("trigger_truth_chain", {}).get("ready"),
                "validation_passed": payload["validation"]["passed"],
                "runtime_latest": payload["evidence_refs"]["runtime_latest"],
                "runtime_readback_zh": payload["readback_refs"]["runtime_readback_zh"],
                "sentinel": payload["sentinel"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
