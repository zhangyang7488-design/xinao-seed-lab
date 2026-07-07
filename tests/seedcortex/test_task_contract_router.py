from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime import task_contract_router


def test_task_contract_router_turns_p0_004_into_delivery_contract(tmp_path: Path, monkeypatch) -> None:
    canonical_repo = tmp_path / "logical-S"
    monkeypatch.setenv("XINAO_CANONICAL_REPO_ROOT", str(canonical_repo))
    payload = {
        "runtime_root": str(tmp_path),
        "task_id": "xinao_seed_cortex_phase0_20260701",
        "workflow_id": "codex-s-333-mainline-p0",
        "assignment_dag_node_id": "p0_004_litellm_default_binding_closure",
        "worker_kind": "implementation_worker",
        "phase_scope": "p0_004_litellm_default_binding_closure",
        "explicit_user_task_control": True,
        "work_package": {
            "objective": "Bind ProviderScheduler default route to LiteLLM Router",
            "next_ready_node_id": "p0_004_litellm_default_binding_closure",
        },
        "verification": ["python -m pytest tests/seedcortex/test_litellm_default_route.py"],
    }

    contract = task_contract_router.build_contract(payload, runtime_root=tmp_path, write=True)
    routed = task_contract_router.apply_contract_to_payload(payload, contract)

    assert contract["status"] == "execution_contract_ready"
    assert contract["delivery_contract"]["success_field"] == "routed_by=litellm"
    assert contract["delivery_contract"]["success_decision"] == "accepted_for_binding"
    assert contract["execution_policy"]["default_acceptance_decisions"] == [
        "accepted_for_binding",
        "accepted_for_delivery",
    ]
    assert contract["execution_policy"]["exception_acceptance_decision"] == "accepted_for_next_frontier"
    assert contract["execution_policy"]["next_frontier_default_outlet"] is False
    assert contract["execution_policy"]["retry_policy"]["policy_id"] == "bounded_delivery_retry"
    assert contract["execution_policy"]["retry_policy"]["max_attempts"] == 3
    assert contract["execution_policy"]["retry_policy"]["max_recursive_repairs"] == 2
    assert contract["execution_policy"]["retry_policy"]["next_frontier_on_failure"] is False
    assert contract["validation"]["checks"]["bounded_delivery_retry_ready"] is True
    assert contract["workflow_switches"]["disable_wave2_mainchain_hygiene"] is True
    assert contract["workflow_switches"]["disable_next_frontier_continuation_supervisor"] is True
    assert routed["execution_contract_ready"] is True
    assert routed["tool_bearing_patch_executor_enabled"] is True
    assert routed["disable_source_family_wave_scheduler"] is True
    assert routed["disable_default_dp_worker_pool_wave"] is True
    assert routed["repo_root"] == str(canonical_repo.absolute())
    assert routed["workspace_hint"] == str(canonical_repo.absolute())
    assert routed["phase_execution"]["repo_root"] == str(canonical_repo.absolute())
    assert Path(contract["record_path"]).is_file()


def test_task_contract_router_leaves_non_explicit_background_path_open(tmp_path: Path) -> None:
    payload = {
        "runtime_root": str(tmp_path),
        "task_id": "background",
        "user_goal": "ordinary background maintenance",
    }

    contract = task_contract_router.build_contract(payload, runtime_root=tmp_path, write=False)
    routed = task_contract_router.apply_contract_to_payload(payload, contract)

    assert contract["status"] == "no_explicit_execution_contract"
    assert contract["workflow_switches"]["frontier_auto_continue_allowed"] is True
    assert routed == payload


def test_task_contract_router_consumes_mature_bind_queue_task(tmp_path: Path, monkeypatch) -> None:
    canonical_repo = tmp_path / "logical-S"
    monkeypatch.setenv("XINAO_CANONICAL_REPO_ROOT", str(canonical_repo))
    mature_bind_task = {
        "task_id": "p0_004a_provider_lane_index",
        "status": "ready",
        "deliverable": "Provider lane index proves LiteLLM-routed worker lanes",
        "replace_target": "opaque direct model calls",
        "mature_carrier": "LiteLLM Router",
        "thin_adapter": "ProviderScheduler policy wrapper",
        "default_mainline_binding": "TaskContractRouter -> ProviderScheduler -> FanIn/AAQ",
        "runtime_evidence": ["D:/runtime/state/provider_lane_index/latest.json"],
        "verification": ["pytest tests/seedcortex/test_codex_native_provider_scheduler_phase4.py"],
        "acceptance": {
            "success_decision": "accepted_for_binding",
            "success_field": "provider_lane_index_ready",
        },
        "fallback_or_blocker": "PROVIDER_LANE_INDEX_NOT_BOUND",
    }
    payload = {
        "runtime_root": str(tmp_path),
        "task_id": "xinao_seed_cortex_phase0_20260701",
        "workflow_id": "codex-s-333-mainline-p0",
        "worker_kind": "implementation_worker",
        "phase_scope": "p0_004a_provider_lane_index",
        "mature_bind_task": mature_bind_task,
        "verification": mature_bind_task["verification"],
    }

    contract = task_contract_router.build_contract(payload, runtime_root=tmp_path, write=True)
    routed = task_contract_router.apply_contract_to_payload(payload, contract)

    assert contract["status"] == "execution_contract_ready"
    assert contract["execution_policy"]["mature_bind_queue_consumed"] is True
    assert contract["execution_policy"]["task_shape"] == "one_deliverable_one_binding_one_verifier"
    assert contract["delivery_contract"]["delivery_id"] == "p0_004a_provider_lane_index"
    assert contract["delivery_contract"]["success_field"] == "provider_lane_index_ready"
    assert contract["delivery_contract"]["success_decision"] == "accepted_for_binding"
    assert contract["delivery_contract"]["replace_target"] == "opaque direct model calls"
    assert contract["delivery_contract"]["replacement"] == "LiteLLM Router"
    assert contract["validation"]["checks"]["mature_bind_task_has_verifier"] is True
    assert routed["execution_contract_ready"] is True
    assert routed["forbid_background_self_proof_without_deliverable"] is True
    assert routed["mature_bind_task"]["task_id"] == "p0_004a_provider_lane_index"


def test_task_contract_router_forces_main_loop_tick_for_p0_007(tmp_path: Path, monkeypatch) -> None:
    canonical_repo = tmp_path / "logical-S"
    monkeypatch.setenv("XINAO_CANONICAL_REPO_ROOT", str(canonical_repo))
    mature_bind_task = {
        "task_id": "p0_007_default_main_loop_trigger_bind",
        "deliverable": "Live r9 consumes current WorkerBrief queue through the Temporal main tick",
        "replace_target": "explicit contracts that stop before main_execution_loop_tick",
        "mature_carrier": "Temporal workflow activity history",
        "thin_adapter": "TaskContractRouter force_default_main_loop_tick payload flag",
        "default_mainline_binding": "task_control -> main_execution_loop_tick -> default_main_loop_trigger_candidate",
        "verification": ["scripts/verify_current_worker_brief_default_trigger.ps1"],
        "acceptance": {
            "success_decision": "accepted_for_binding",
            "success_field": "default_main_loop_trigger_runtime_enforced",
        },
    }
    payload = {
        "runtime_root": str(tmp_path),
        "task_id": "xinao_seed_cortex_phase0_20260701",
        "workflow_id": "codex-s-333-mainline-p0-current",
        "worker_kind": "implementation_worker",
        "phase_scope": "p0_007_default_main_loop_trigger_bind",
        "mature_bind_task": mature_bind_task,
        "verification": mature_bind_task["verification"],
    }

    contract = task_contract_router.build_contract(payload, runtime_root=tmp_path, write=True)
    routed = task_contract_router.apply_contract_to_payload(payload, contract)

    assert contract["status"] == "execution_contract_ready"
    assert contract["contract_id"] == "p0_007_default_main_loop_trigger_bind"
    assert contract["delivery_contract"]["delivery_id"] == "p0_007_default_main_loop_trigger_bind"
    assert contract["delivery_contract"]["success_field"] == "default_main_loop_trigger_runtime_enforced"
    assert routed["execution_contract_ready"] is True
    assert routed["force_default_main_loop_tick"] is True
    assert routed["default_main_loop_trigger_bind_required"] is True
    assert routed["current_worker_brief_queue_required"] is True
    assert routed["bind_provider_worker_pool"] is True
    assert routed["phase1_target_width"] == 3
    assert routed["phase1_max_parallel_workers"] == 3
    assert routed["current_worker_brief_queue_ref"] == str(
        tmp_path / "state" / "worker_brief_queue" / "latest.json"
    )


def test_task_contract_router_forces_real_receipts_for_p0_008(tmp_path: Path, monkeypatch) -> None:
    canonical_repo = tmp_path / "logical-S"
    monkeypatch.setenv("XINAO_CANONICAL_REPO_ROOT", str(canonical_repo))
    mature_bind_task = {
        "task_id": "p0_008_worker_dispatch_real_receipt",
        "deliverable": "Worker dispatch ledger succeeds only from real WorkerBrief provider receipts",
        "replace_target": "worker_dispatch_ledger self-written or phase1 succeeded counts",
        "mature_carrier": "Temporal worker task result receipt",
        "thin_adapter": "WorkerBriefQueue -> ProviderScheduler -> execute_worker_turn",
        "default_mainline_binding": "r9 main tick -> WorkerBrief provider lane -> worker_dispatch_ledger",
        "verification": ["scripts/verify_worker_dispatch_ledger.ps1"],
        "acceptance": {
            "success_decision": "accepted_for_binding",
            "success_field": "worker_dispatch_real_receipt_ready",
        },
    }
    payload = {
        "runtime_root": str(tmp_path),
        "task_id": "xinao_seed_cortex_phase0_20260701",
        "workflow_id": "codex-s-333-mainline-p0-current",
        "workflow_run_id": "run-r9",
        "worker_kind": "implementation_worker",
        "phase_scope": "p0_008_worker_dispatch_real_receipt",
        "mature_bind_task": mature_bind_task,
        "verification": mature_bind_task["verification"],
    }

    contract = task_contract_router.build_contract(payload, runtime_root=tmp_path, write=True)
    routed = task_contract_router.apply_contract_to_payload(payload, contract)

    assert contract["status"] == "execution_contract_ready"
    assert contract["contract_id"] == "p0_008_worker_dispatch_real_receipt"
    assert contract["delivery_contract"]["success_field"] == "worker_dispatch_real_receipt_ready"
    assert contract["delivery_contract"]["success_decision"] == "accepted_for_binding"
    assert routed["execute_worker_turn"] is True
    assert routed["execute_codex_worker"] is False
    assert routed["worker_dispatch_real_receipt_required"] is True
    assert routed["worker_brief_real_receipt_required"] is True
    assert routed["current_worker_brief_queue_required"] is True
    assert routed["force_default_main_loop_tick"] is True
    assert routed["bind_provider_worker_pool"] is False
    assert routed["phase1_target_width"] == 0
    assert routed["phase1_max_parallel_workers"] == 0
    assert routed["disable_default_trigger_provider_worker_pool"] is True
    assert routed["worker_brief_dispatch_limit"] == 3
    assert routed["require_dp_receipt"] is True
    assert routed["worker_dispatch_ledger_real_receipt_ref"] == str(
        tmp_path / "state" / "worker_dispatch_ledger" / "latest.json"
    )


def test_task_contract_router_binds_current_333_run_index_for_current_alias(tmp_path: Path, monkeypatch) -> None:
    canonical_repo = tmp_path / "logical-S"
    monkeypatch.setenv("XINAO_CANONICAL_REPO_ROOT", str(canonical_repo))
    current_index = tmp_path / "state" / "current_333_run_index" / "latest.json"
    current_index.parent.mkdir(parents=True)
    current_index.write_text(
        json.dumps(
            {
                "status": "current_333_run_index_ready",
                "workflow_id": "codex-s-333-mainline-p0-r9",
                "workflow_run_id": "run-r9",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    mature_bind_task = {
        "task_id": "p0_004a_provider_lane_index",
        "status": "ready",
        "deliverable": "Provider lane index proves LiteLLM-routed worker lanes",
        "verification": ["pytest tests/seedcortex/test_codex_native_provider_scheduler_phase4.py"],
        "acceptance": {
            "success_decision": "accepted_for_binding",
            "success_field": "provider_lane_index_ready",
        },
    }
    payload = {
        "runtime_root": str(tmp_path),
        "task_id": "xinao_seed_cortex_phase0_20260701",
        "workflow_id": "codex-s-333-mainline-p0-current",
        "workflow_run_id": "",
        "worker_kind": "implementation_worker",
        "phase_scope": "p0_004a_provider_lane_index",
        "mature_bind_task": mature_bind_task,
        "verification": mature_bind_task["verification"],
    }

    contract = task_contract_router.build_contract(payload, runtime_root=tmp_path, write=True)

    assert contract["status"] == "execution_contract_ready"
    assert contract["workflow_id"] == "codex-s-333-mainline-p0-r9"
    assert contract["workflow_run_id"] == "run-r9"
    assert contract["workflow_binding"]["source"] == "current_333_run_index"
    assert contract["workflow_binding"]["input_workflow_id"] == "codex-s-333-mainline-p0-current"
