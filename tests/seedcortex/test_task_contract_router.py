from __future__ import annotations

from pathlib import Path

from services.agent_runtime import task_contract_router


def test_task_contract_router_turns_p0_004_into_delivery_contract(tmp_path: Path) -> None:
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
    assert contract["workflow_switches"]["disable_wave2_mainchain_hygiene"] is True
    assert contract["workflow_switches"]["disable_next_frontier_continuation_supervisor"] is True
    assert routed["execution_contract_ready"] is True
    assert routed["tool_bearing_patch_executor_enabled"] is True
    assert routed["disable_source_family_wave_scheduler"] is True
    assert routed["disable_default_dp_worker_pool_wave"] is True
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
