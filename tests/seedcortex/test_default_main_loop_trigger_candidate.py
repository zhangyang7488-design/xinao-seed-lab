import importlib.util
import json
from pathlib import Path

from xinao_seedlab.application.seed_cortex import build_default_service
from xinao_seedlab.cli.__main__ import main as cli_main


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "default_main_loop_trigger_candidate.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "codex_s_default_main_loop_trigger_candidate.v1.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("default_main_loop_trigger_candidate", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_anchors(anchor_root: Path) -> None:
    names = [
        "新系统独立并行_自由发散外部研究总稿_20260701.txt",
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
        "新系统步骤程序_大骨架_并行研究收口_20260702.txt",
        "新系统前置材料_收口合并_20260702.txt",
    ]
    anchor_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (anchor_root / name).write_text(f"{name}\n", encoding="utf-8")


def _seed_runtime_refs(runtime: Path) -> None:
    refs = {
        "default_hot_path_intake": {
            "schema_version": "xinao.codex_s.default_hot_path_intake.v1",
            "status": "default_hot_path_intake_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "artifact_acceptance_queue": {
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_ready",
            "accepted_artifact_count": 1,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "parallel_dispatch_plan": {
            "schema_version": "xinao.codex_s.parallel_dispatch_plan.v1",
            "status": "parallel_dispatch_plan_ready",
            "lane_assignments": [
                {
                    "lane_id": "codex_hot_path",
                    "resource_lane": "codex_subagent",
                    "edge_kind": "audit",
                    "selected": True,
                }
            ],
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "parallel_fan_in_acceptance": {
            "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
            "status": "fan_in_acceptance_ready_for_plan_evidence",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "worker_dispatch_ledger": {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "status": "worker_dispatch_ledger_ready",
            "continue_dispatch_expected": True,
            "foreground_poll_required": False,
            "runtime_enforced": True,
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_activity",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "codex_s_main_execution_loop_tick": {
            "schema_version": "xinao.codex_s.main_execution_loop_tick.v1",
            "status": "main_execution_loop_tick_ready",
            "continue_dispatch_expected": True,
            "foreground_poll_required": False,
            "runtime_entrypoint_invocation": {
                "runtime_enforced": True,
                "runtime_enforced_scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
                "not_execution_controller": True,
                "not_completion_gate": True,
            },
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "seed_lab_total_execution_kernel": {
            "schema_version": "xinao.seed_lab.total_execution_kernel.v1",
            "status": "seed_lab_total_execution_kernel_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "seed_lab_correction_intake": {
            "schema_version": "xinao.seed_lab.correction_intake.v1",
            "status": "seed_lab_correction_intake_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "seed_lab_experiment_review_view": {
            "schema_version": "xinao.seed_lab.experiment_review_view.v1",
            "status": "seed_lab_experiment_review_view_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "seed_lab_replay_court": {
            "schema_version": "xinao.seed_lab.replay_court.v1",
            "status": "seed_lab_replay_court_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "seed_lab_user_correction_runtime": {
            "schema_version": "xinao.codex_s.seed_lab_user_correction_runtime.v1",
            "status": "seed_lab_user_correction_runtime_candidate_ready",
            "sentinel": "SENTINEL:XINAO_SEED_LAB_USER_CORRECTION_RUNTIME_SERVICE_API_CANDIDATE",
            "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "trigger_installed": False,
            "memory_promotion_allowed": False,
            "policy_promotion_allowed": False,
            "completion_claim_allowed": False,
            "validation": {"passed": True},
            "service_entrypoint": {
                "caller": "SeedCortexService.seed_lab_user_correction_runtime",
                "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
            },
            "not_execution_controller": True,
        },
        "scheduler_invocation_packet": {
            "schema_version": "xinao.codex_s.scheduler_invocation_packet.v1",
            "status": "spawned_lane_refs_recorded",
            "sentinel": "SENTINEL:XINAO_CODEX_S_SCHEDULER_INVOCATION_PACKET_READY",
            "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "scheduler_invoked": True,
            "parent_dispatch_invoked": True,
            "runtime_enforced": False,
            "default_runtime_scheduler_invoked": False,
            "completion_claim_allowed": False,
            "validation": {"passed": True},
            "service_entrypoint": {
                "caller": "SeedCortexService.scheduler_invocation_packet",
                "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
                "runtime_enforced": False,
                "default_runtime_scheduler_invoked": False,
            },
            "not_execution_controller": True,
        },
        "scheduler_spawned_lane_evidence": {
            "schema_version": "xinao.codex_s.scheduler_spawned_lane_evidence.v1",
            "status": "scheduler_spawned_lane_evidence_ready",
            "sentinel": "SENTINEL:XINAO_CODEX_S_SCHEDULER_SPAWNED_LANE_EVIDENCE_READY",
            "lane_evidence_state": "parent_scheduler_invoked_with_lane_refs_not_default_runtime",
            "scheduler_invoked": True,
            "parent_dispatch_invoked": True,
            "activity_scope_scheduler_invoked": False,
            "default_runtime_scheduler_invoked": False,
            "runtime_enforced": False,
            "scheduler_spawned_lane_count": 2,
            "dp_sidecar_execution_lanes_spawned": True,
            "dp_sidecar_execution_modes_seen": ["search", "draft"],
            "named_blocker": "DEFAULT_RUNTIME_SCHEDULER_NOT_HOOKED_PARENT_DISPATCH_ONLY",
            "actual_dispatch_refs": {
                "refs_are_not_execution_controllers": True,
                "scheduler_spawned_lane_count": 2,
            },
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "dp_sidecar_execution_port": {
            "schema_version": "xinao.codex_s.dp_sidecar_execution_port.v1",
            "status": "dp_sidecar_execution_port_runner_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "dp_sidecar_execution_provider": {
            "schema_version": "xinao.seedcortex.dp_sidecar_execution_provider.v1",
            "status": "dp_sidecar_execution_provider_ready",
            "validation": {"passed": True},
            "runtime_enforced": False,
            "trigger_installed": False,
            "not_execution_controller": True,
        },
        "current_333_run_index": {
            "schema_version": "xinao.codex_s.333_sleep_watch_p0_landing.v1.current_run_index.v1",
            "status": "current_333_run_index_ready",
            "workflow_id": "333-sleep-watch-source-package-20260705-r1",
            "workflow_run_id": "run-default-trigger-unit",
            "current_state": "running_with_pending_activity",
            "latest_completed_wave_id": "unit-wave-01",
            "reconciliation": {"reconciled": True, "named_blocker": ""},
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
            "validation": {"passed": True},
        },
    }
    for state_name, payload in refs.items():
        _write_json(runtime / "state" / state_name / "latest.json", payload)
        if state_name in {"worker_dispatch_ledger", "codex_s_main_execution_loop_tick"}:
            _write_json(runtime / "state" / state_name / "temporal_activity_latest.json", payload)
        if state_name == "seed_lab_user_correction_runtime":
            _write_json(runtime / "state" / state_name / "service_entrypoint_latest.json", payload)
        if state_name == "scheduler_invocation_packet":
            _write_json(runtime / "state" / state_name / "service_entrypoint_latest.json", payload)
        if state_name == "scheduler_spawned_lane_evidence":
            _write_json(runtime / "state" / state_name / "current_wave_latest.json", payload)
            activity_payload = {
                **payload,
                "lane_evidence_state": "activity_scheduler_invoked_with_lane_refs_not_default_runtime",
                "parent_dispatch_invoked": False,
                "activity_scope_scheduler_invoked": True,
                "named_blocker": "DEFAULT_RUNTIME_SCHEDULER_NOT_HOOKED_ACTIVITY_SCOPE_ONLY",
            }
            _write_json(
                runtime / "state" / state_name / "activity_scoped_latest.json",
                activity_payload,
            )
    _write_json(
        runtime
        / "capabilities"
        / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port"
        / "manifest.json",
        {
            "provider_id": "legacy.deepseek_dp_sidecar",
            "port_id": "dp_sidecar_execution_port",
            "capability_kinds": ["dp_sidecar_execution"],
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json",
        {
            "schema_version": "xinao.codex_s.333_sleep_watch_p0_landing.v1.tool_registry.v1",
            "status": "tool_registry_ready",
            "provider_ids": [
                "codex_s.333_stateful_continuity_router",
                "codex_s.333_host_dialogue_gate_trace",
                "codex_s.333_task_transaction_control",
                "codex_s.direct_worker_lane",
                "qwen_prepaid_cheap_worker",
                "legacy.deepseek_dp_sidecar",
                "codex_s.capability_gateway",
                "mcp.xinao_runtime.tools",
                "d_runtime.capability_manifests",
            ],
            "ucp_dispatch_exposed": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
            "validation": {"passed": True},
        },
    )


def _seed_worker_dispatch_ledger_entries(runtime: Path) -> None:
    payload = {
        "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
        "status": "worker_dispatch_ledger_ready",
        "continue_dispatch_expected": True,
        "foreground_poll_required": False,
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_activity",
        "validation": {"passed": True},
        "not_execution_controller": True,
        "dispatch_entries": [
            {
                "entry_id": "wave-1:local-worker-dispatch-ledger-writer",
                "agent_id": "codex_s_current_worker",
                "provider": "codex.local",
                "mode": "worker",
                "poll_status": "succeeded",
            },
            {
                "entry_id": "wave-1:codex-subagent-dispatch-record",
                "agent_id": "codex_s_subagent_lane",
                "provider": "codex.subagent",
                "mode": "subagent",
                "poll_status": "planned_not_spawned",
            },
        ],
    }
    _write_json(runtime / "state" / "worker_dispatch_ledger" / "latest.json", payload)
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json",
        payload,
    )


def _fake_phase1_truth_chain_payload(runtime: Path, wave_id: str) -> dict:
    return {
        "schema_version": "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1",
        "status": "modular_dynamic_worker_pool_phase1_wave_merged",
        "wave_id": wave_id,
        "validation": {"passed": True, "checks": {"runtime_enforced_write_gate_passed": True}},
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_global_default_modular_dynamic_worker_pool_phase1",
        "runtime_enforcement_truth_chain": {"ready": True, "checks": {}},
        "default_route_binding": {
            "provider_scheduler_default_layer": {"status": "ready"},
        },
        "actual_dispatched_width": 4,
        "actual_completed_width": 4,
        "worker_dispatch_ledger_succeeded_count": 4,
        "worker_dispatch_ledger_succeeded_matches_completed": True,
        "artifact_acceptance_queue": {
            "accepted_candidate_count": 1,
            "accepted_artifact_count": 1,
            "unique_accepted_artifact_count": 1,
            "duplicate_accepted_candidate_count": 0,
        },
        "qwen_prepaid_first_required_count": 2,
        "qwen_prepaid_first_succeeded_count": 2,
        "provider_tier_usage": {
            "qwen_prepaid_cheap_worker": 2,
            "deepseek_dp_external_model": 2,
        },
        "lane_results": [
            {
                "lane_id": "draft-01",
                "status": "succeeded",
                "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
            },
            {
                "lane_id": "draft-02",
                "status": "succeeded",
                "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
            },
            {
                "lane_id": "audit-01",
                "status": "succeeded",
                "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
            },
            {
                "lane_id": "citation-01",
                "status": "succeeded",
                "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
            },
        ],
        "python_carrier": {"using_expected_python": True},
        "can_invoke_now": {
            "direct_module": "E:\\XINAO_RESEARCH_WORKSPACES\\S\\.venv\\Scripts\\python.exe -m services.agent_runtime.modular_dynamic_worker_pool_phase1",
        },
        "merge_artifact": str(
            runtime / "state" / "modular_dynamic_worker_pool_phase1" / "merge.md"
        ),
        "evidence_refs": {
            "runtime_latest": str(
                runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
            ),
            "worker_dispatch_ledger_latest": str(
                runtime / "state" / "worker_dispatch_ledger" / "latest.json"
            ),
            "artifact_acceptance_queue_latest": str(
                runtime / "state" / "artifact_acceptance_queue" / "latest.json"
            ),
        },
    }


def test_trigger_truth_chain_accepts_dp_only_token_saving_route(tmp_path: Path) -> None:
    module = _load_module()
    wave_id = "unit-dp-only-token-saving"
    payload = _fake_phase1_truth_chain_payload(tmp_path / "runtime", wave_id)
    payload["qwen_prepaid_first_required_count"] = 0
    payload["qwen_prepaid_first_succeeded_count"] = 0
    payload["provider_tier_usage"] = {"deepseek_dp_external_model": 4}
    for lane in payload["lane_results"]:
        lane["selected_carrier_provider_id"] = "legacy.deepseek_dp_sidecar"
    payload["default_route_binding"] = {
        "status": "global_default_runtime_enforced",
        "runtime_enforced": True,
        "provider_scheduler_default_layer": {
            "provider_id": "codex_s.provider_scheduler",
            "status": "blocked_or_not_refreshed",
        },
    }

    truth = module.build_trigger_truth_chain(
        requested=True,
        phase1_payload=payload,
        wave_id=wave_id,
    )

    assert truth["ready"] is True
    assert truth["qwen_prepaid_first_required_count"] == 0
    assert truth["dp_default_route_succeeded"] is True
    assert truth["qwen_or_dp_default_worker_route_succeeded"] is True
    assert truth["checks"]["qwen_cheap_first_required_attempts_succeeded"] is True
    assert truth["checks"]["provider_scheduler_default_layer_ready"] is True


def test_trigger_truth_chain_accepts_allowed_dp_fallback_after_qwen_attempt(
    tmp_path: Path,
) -> None:
    module = _load_module()
    wave_id = "unit-qwen-fallback-allowed"
    payload = _fake_phase1_truth_chain_payload(tmp_path / "runtime", wave_id)
    payload["qwen_prepaid_first_required_count"] = 3
    payload["qwen_prepaid_first_attempted_count"] = 3
    payload["qwen_prepaid_first_succeeded_count"] = 0
    payload["qwen_fallback_allowed_count"] = 3
    payload["provider_tier_usage"] = {"deepseek_dp_external_model": 5}

    truth = module.build_trigger_truth_chain(
        requested=True,
        phase1_payload=payload,
        wave_id=wave_id,
    )

    assert truth["ready"] is True
    assert truth["qwen_prepaid_first_required_count"] == 3
    assert truth["qwen_prepaid_first_attempted_count"] == 3
    assert truth["qwen_fallback_allowed_count"] == 3
    assert truth["qwen_required_attempts_succeeded"] is False
    assert truth["qwen_required_attempts_succeeded_or_allowed_fallback"] is True
    assert truth["checks"]["qwen_cheap_first_succeeded_or_allowed_fallback"] is True


def test_default_main_loop_trigger_candidate_binds_service_refs(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        codex_subagents=[
            "019f22a3-13b1-73d3-8f81-1b36cc635c23:worker_dispatch_ledger",
            "019f22a3-141d-7311-bf78-69a37f9db88e:hot_path_probe",
        ],
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.default_main_loop_trigger_candidate.v1"
    assert payload["sentinel"] == (
        "SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY"
    )
    assert payload["status"] == "default_main_loop_trigger_candidate_verifier_ready"
    assert payload["adoption_state"] == "runtime_trigger_candidate_verifier_ready"
    assert payload["adoption_state_boundary"]["adoption_state"] == (
        "runtime_trigger_candidate_verifier_ready"
    )
    assert payload["adoption_state_boundary"]["scope"] == (
        "default_main_loop_trigger_candidate_only"
    )
    assert payload["adoption_state_boundary"]["state_is_scoped_candidate"] is True
    assert payload["adoption_state_boundary"]["not_global_runtime_enforcement"] is True
    assert payload["adoption_state_boundary"]["not_global_default_trigger"] is True
    assert payload["adoption_state_boundary"]["runtime_enforced"] is False
    assert payload["adoption_state_boundary"]["runtime_enforced_scope"] == ""
    assert payload["runtime_enforced"] is False
    assert payload["runtime_enforced_scope"] == ""
    assert payload["temporal_enforced"] is False
    assert payload["trigger_installed"] is False
    assert payload["trigger_truth_chain"]["requested"] is False
    assert payload["provider_worker_pool_invocation"]["requested"] is False
    assert payload["stop_hook_controller"] is False
    assert payload["candidate_for"] == "main_execution_loop_default_trigger"
    assert payload["target_service_method"] == "SeedCortexService.main_execution_loop_tick"
    assert payload["target_user_correction_runtime_service_method"] == (
        "SeedCortexService.seed_lab_user_correction_runtime"
    )
    assert payload["target_user_correction_runtime_fastapi_route"] == (
        "POST /runtime/seed-lab-user-correction-runtime"
    )
    assert payload["base_tick_adoption_state"] == "verifier_ready_but_not_hooked"
    assert payload["api_cli_adoption_state"] == "api_cli_verifier_ready_not_hook_enforced"
    assert payload["user_correction_runtime_api_cli_adoption_state"] == (
        "api_cli_verifier_ready_not_hook_enforced"
    )
    assert payload["stop_guard_layers_are_main_execution_loop"] is False
    assert payload["is_stop_guard_layer"] is False
    assert payload["is_completion_gate"] is False
    assert payload["not_execution_controller"] is True
    assert payload["validation"]["passed"] is True

    checks = payload["validation"]["checks"]
    assert checks["metaminute_before_new_parallel_wave_invoked"] is True
    assert checks["main_loop_service_invoked"] is True
    assert checks["durable_packet_service_invoked"] is True
    assert checks["modular_dynamic_worker_pool_phase1_provider_visible"] is True
    assert checks["user_correction_runtime_refs_bound"] is True
    assert checks["user_correction_runtime_not_enforced"] is True
    assert checks["scheduler_gateway_capabilities_visible"] is True
    assert checks["scheduler_current_wave_evidence_bound"] is True
    assert checks["scheduler_activity_scoped_evidence_bound"] is True
    assert checks["scheduler_lane_refs_non_overclaiming"] is True
    assert checks["actual_dispatch_refs_bound"] is True
    assert checks["poll_refs_bound"] is True
    assert checks["fan_in_refs_bound"] is True
    assert checks["evidence_and_readback_refs_bound"] is True
    assert checks["provider_worker_pool_invocation_bound"] is True
    assert checks["provider_worker_pool_truth_chain_ready"] is True
    assert checks["qwen_cheap_first_bound_to_trigger_wave"] is True
    assert checks["deepseek_dp_bound_to_trigger_wave"] is True
    assert checks["ledger_and_aaq_truth_chain_bound"] is True
    assert checks["current_333_run_index_consumed_by_default_trigger"] is True
    assert checks["tool_registry_consumed_by_default_trigger"] is True
    assert checks["no_stop_wave_consumption_refs_bound"] is True
    assert checks["stop_guards_not_main_loop"] is True
    assert checks["adoption_state_boundary_scoped_candidate"] is True

    refs = payload["actual_service_invocations"]
    main_service_path = refs["main_execution_loop_tick_service"]["path"].replace("\\", "/")
    durable_service_path = refs["durable_parallel_wave_packet_service"]["path"].replace("\\", "/")
    assert main_service_path.endswith(
        "codex_s_main_execution_loop_tick/service_entrypoint_latest.json"
    )
    assert durable_service_path.endswith(
        "durable_parallel_wave_packet/service_entrypoint_latest.json"
    )
    assert payload["user_correction_runtime_refs"]["service_entrypoint_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["correction_intake_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["experiment_review_view_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["replay_court_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["explicit_service_api_candidate"] is True
    assert payload["user_correction_runtime_refs"]["invoked_by_default_trigger"] is False
    assert payload["user_correction_runtime_refs"]["runtime_enforced"] is False
    assert payload["user_correction_runtime_refs"]["trigger_installed"] is False
    assert payload["user_correction_runtime_refs"]["memory_promotion_allowed"] is False
    assert payload["user_correction_runtime_refs"]["policy_promotion_allowed"] is False
    assert payload["user_correction_runtime_refs"]["completion_claim_allowed"] is False
    assert payload["user_correction_runtime_refs"]["refs_are_not_execution_controllers"] is True
    no_stop_refs = payload["no_stop_wave_consumption_refs"]
    assert no_stop_refs["ready"] is True
    assert no_stop_refs["current_333_run_index_ref"]["reconciled"] is True
    assert no_stop_refs["tool_registry_ref"]["required_provider_ids_present"] is True
    assert no_stop_refs["refs_are_not_execution_controllers"] is True
    assert payload["actual_dispatch_refs"]["codex_subagent_count"] == 2
    assert payload["actual_dispatch_refs"]["refs_are_not_execution_controllers"] is True
    phase1_binding = payload["modular_dynamic_worker_pool_phase1_trigger_binding"]
    assert phase1_binding["gateway_provider_id"] == (
        "codex_s.modular_dynamic_worker_pool_phase1"
    )
    assert phase1_binding["gateway_provider_visible"] is True
    assert phase1_binding["hot_path_shape"] == "parallel_draft->merge->writer"
    assert phase1_binding["dp_worker_role"] == "draft_main_worker_pool"
    assert phase1_binding["runtime_enforced"] is False
    assert phase1_binding["trigger_installed"] is False
    assert (
        payload["actual_dispatch_refs"]["dp_sidecar_execution_port_runner_ref"]["exists"]
        is True
    )
    assert (
        payload["actual_dispatch_refs"]["dp_sidecar_execution_provider_ref"]["exists"]
        is True
    )
    assert (
        payload["actual_dispatch_refs"]["dp_sidecar_execution_provider_manifest_ref"][
            "exists"
        ]
        is True
    )
    assert (
        payload["actual_dispatch_refs"]["dp_sidecar_execution_callable_entrypoint_bound"]
        is True
    )
    scheduler_refs = payload["scheduler_lane_evidence_refs"]
    assert scheduler_refs["bound_for_discovery_only"] is True
    assert scheduler_refs["runtime_enforced"] is False
    assert scheduler_refs["default_runtime_scheduler_invoked"] is False
    assert scheduler_refs["scheduler_spawned_lane_evidence_current_wave"][
        "scheduler_spawned_lane_count"
    ] >= 3
    assert scheduler_refs["scheduler_spawned_lane_evidence_current_wave"][
        "dp_sidecar_execution_lanes_spawned"
    ] is True
    assert scheduler_refs["scheduler_spawned_lane_evidence_activity_scoped"][
        "activity_scope_scheduler_invoked"
    ] is True
    assert any(
        "actual_subagent_dispatch_evidence" in provider["matched_capability_kinds"]
        for provider in scheduler_refs["capability_gateway_scheduler_lane_providers"]
    )
    spawned_refs = payload["scheduler_spawned_lane_evidence_refs"]
    assert spawned_refs["current_wave_latest_ref"]["exists"] is True
    assert spawned_refs["activity_scoped_latest_ref"]["exists"] is True
    assert spawned_refs["candidate_discovery_scope"] == (
        "default_main_loop_trigger_candidate_ref_discovery_only"
    )
    assert spawned_refs["current_wave_lane_evidence_state"] == (
        "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert spawned_refs["activity_scoped_lane_evidence_state"] == (
        "activity_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert spawned_refs["codex_lane_evidence_discovered"] is True
    assert spawned_refs["dp_sidecar_execution_modes_discovered"] is True
    assert spawned_refs["current_wave_dp_sidecar_execution_lanes_present"] is True
    assert spawned_refs["current_wave_immutable_ref_exists"] is True
    assert spawned_refs["current_wave_immutable_digest_bound"] is True
    assert spawned_refs["current_wave_runtime_wave_record"]
    assert len(spawned_refs["current_wave_runtime_wave_record_digest_sha256"]) == 64
    assert spawned_refs["current_wave_selected_runtime_latest"].replace("\\", "/").endswith(
        "scheduler_spawned_lane_evidence/current_wave_latest.json"
    )
    assert spawned_refs["dp_sidecar_execution_lanes_spawned"] is False
    assert spawned_refs["default_runtime_scheduler_invoked"] is False
    assert spawned_refs["runtime_enforced"] is False
    assert spawned_refs["trigger_installed"] is False
    assert spawned_refs["refs_are_not_execution_controllers"] is True
    assert payload["fan_in_refs"]["artifact_acceptance_queue_required"] is True

    latest = runtime / "state" / "default_main_loop_trigger_candidate" / "latest.json"
    readback = (
        runtime / "readback" / "zh" / "default_main_loop_trigger_candidate_20260702.md"
    )
    assert latest.is_file()
    assert readback.is_file()
    readback_text = readback.read_text(encoding="utf-8")
    assert "runtime_enforced: False" in readback_text
    assert "scoped candidate" in readback_text
    assert "not_global_runtime_enforcement: True" in readback_text
    assert "user_correction_runtime_refs_bound: True" in readback_text
    assert "user_correction_runtime_not_enforced: True" in readback_text
    assert "modular_dynamic_worker_pool_phase1_provider_visible: True" in readback_text
    assert "scheduler_current_wave_evidence_bound: True" in readback_text
    assert "scheduler_spawned_lane_evidence_refs_bound: True" in readback_text
    assert "scheduler_current_wave_immutable_ref_bound: True" in readback_text
    assert "dp_sidecar_execution_callable_refs_bound: True" in readback_text
    assert "provider_worker_pool_truth_chain_ready: True" in readback_text
    assert "current_333_run_index_consumed_by_default_trigger: True" in readback_text
    assert "tool_registry_consumed_by_default_trigger: True" in readback_text


def test_default_main_loop_trigger_accepts_ledger_derived_dispatch_refs(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)
    _seed_worker_dispatch_ledger_entries(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        codex_subagents=[],
        write=True,
    )

    actual = payload["actual_dispatch_refs"]
    assert payload["validation"]["checks"]["actual_dispatch_refs_bound"] is True
    assert actual["codex_subagent_count"] == 1
    assert actual["codex_subagents"][0]["agent_id"] == "codex_s_current_worker"
    assert actual["codex_subagents"][0]["source"] == "worker_dispatch_ledger"
    assert actual["explicit_codex_subagent_refs_provided"] is False
    assert actual["derived_codex_subagent_refs_from_worker_dispatch_ledger"] is True


def test_seed_cortex_service_invokes_default_main_loop_trigger_candidate(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)
    service = build_default_service(runtime)

    payload = service.default_main_loop_trigger_candidate(
        anchor_package_root=str(anchor),
        codex_subagents=["agent-1:worker_dispatch_ledger"],
        write_runtime=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.default_main_loop_trigger_candidate.v1"
    assert payload["adoption_state"] == "runtime_trigger_candidate_verifier_ready"
    assert payload["adoption_state_boundary"]["state_is_scoped_candidate"] is True
    assert payload["adoption_state_boundary"]["not_global_runtime_enforcement"] is True
    assert payload["service_entrypoint"]["caller"] == (
        "SeedCortexService.default_main_loop_trigger_candidate"
    )
    assert payload["service_entrypoint"]["api_cli_adoption_state"] == (
        "api_cli_verifier_ready_not_hook_enforced"
    )
    assert payload["service_entrypoint"]["runtime_enforced"] is False
    assert payload["service_entrypoint"]["trigger_installed"] is False
    assert payload["service_entrypoint"]["shared_latest_ref_is_base_runner_view"] is True
    assert payload["not_execution_controller"] is True

    service_latest = (
        runtime / "state" / "default_main_loop_trigger_candidate" / "service_entrypoint_latest.json"
    )
    service_readback = (
        runtime
        / "readback"
        / "zh"
        / "default_main_loop_trigger_candidate_service_entrypoint_20260702.md"
    )
    assert service_latest.is_file()
    assert service_readback.is_file()
    service_payload = json.loads(service_latest.read_text(encoding="utf-8"))
    assert service_payload["service_entrypoint"]["api_cli_adoption_state"] == (
        "api_cli_verifier_ready_not_hook_enforced"
    )
    service_text = service_readback.read_text(encoding="utf-8")
    assert "不是 Stop guard" in service_text
    assert "scheduler_current_wave_evidence_bound: True" in service_text
    assert "default_runtime_scheduler_invoked: False" in service_text


def test_cli_invokes_default_main_loop_trigger_candidate(tmp_path: Path, capsys) -> None:
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)

    exit_code = cli_main(
        [
            "default-main-loop-trigger-candidate",
            "--runtime-root",
            str(runtime),
            "--anchor-package-root",
            str(anchor),
            "--codex-subagent",
            "agent-1:worker_dispatch_ledger",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "xinao.codex_s.default_main_loop_trigger_candidate.v1"
    assert output["adoption_state"] == "runtime_trigger_candidate_verifier_ready"
    assert output["adoption_state_boundary"]["scope"] == (
        "default_main_loop_trigger_candidate_only"
    )
    assert output["adoption_state_boundary"]["not_global_runtime_enforcement"] is True
    assert output["service_entrypoint"]["api_cli_adoption_state"] == (
        "api_cli_verifier_ready_not_hook_enforced"
    )
    assert output["trigger_installed"] is False
    assert output["runtime_enforced"] is False


def test_default_main_loop_trigger_installs_task_scoped_provider_worker_pool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)

    captured: dict = {}

    def fake_provider_worker_pool(**kwargs):
        captured.update(kwargs)
        return _fake_phase1_truth_chain_payload(runtime, kwargs["wave_id"])

    monkeypatch.setattr(
        module,
        "invoke_provider_worker_pool_from_trigger",
        fake_provider_worker_pool,
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        wave_id="qwen-dp-default-trigger-test-wave",
        codex_subagents=["agent-1:worker_dispatch_ledger"],
        bind_provider_worker_pool=True,
        phase1_target_width=4,
        phase1_max_parallel_workers=2,
        write=True,
    )

    assert payload["status"] == "default_main_loop_trigger_task_scoped_runtime_enforced"
    assert payload["adoption_state"] == "runtime_enforced"
    assert payload["runtime_enforced"] is True
    assert payload["runtime_enforced_scope"] == (
        "seed_cortex_default_main_loop_trigger_qwen_dp_worker_pool"
    )
    assert payload["trigger_installed"] is True
    assert payload["adoption_state_boundary"]["scope"] == (
        "default_main_loop_trigger_task_scoped_qwen_dp_worker_pool"
    )
    assert payload["adoption_state_boundary"]["root_loop_every_wave_enforced"] is False
    assert payload["trigger_truth_chain"]["ready"] is True
    assert payload["trigger_truth_chain"]["phase1_wave_id"] == (
        "qwen-dp-default-trigger-test-wave"
    )
    assert payload["trigger_truth_chain"]["provider_lane_counts"] == {
        "qwen_prepaid_cheap_worker": 2,
        "legacy.deepseek_dp_sidecar": 2,
    }
    assert payload["trigger_truth_chain"]["worker_dispatch_ledger_succeeded_count"] == 4
    assert payload["trigger_truth_chain"]["unique_accepted_artifact_count"] == 1
    assert payload["provider_worker_pool_invocation"]["requested"] is True
    assert payload["provider_worker_pool_invocation"]["invoked"] is True
    decision = captured["dynamic_width_decision"]
    assert decision["target_width_source"].startswith("dynamic_width_scheduler")
    assert decision["recomputed_each_wave"] is True
    assert decision["fixed_20_or_50_used"] is False
    assert decision["width_decision_inputs"]
    assert payload["provider_worker_pool_invocation"]["target_width_source"].startswith(
        "dynamic_width_scheduler"
    )
    assert payload["provider_worker_pool_invocation"]["recomputed_each_wave"] is True
    assert payload["provider_worker_pool_invocation"]["resolved_target_width"] > 0
    assert payload["validation"]["checks"]["provider_worker_pool_truth_chain_ready"] is True
    assert payload["validation"]["checks"]["qwen_cheap_first_bound_to_trigger_wave"] is True
    assert payload["validation"]["checks"]["deepseek_dp_bound_to_trigger_wave"] is True
    assert payload["validation"]["checks"]["ledger_and_aaq_truth_chain_bound"] is True


def test_schema_preserves_non_overclaiming_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.default_main_loop_trigger_candidate.v1"
    )
    assert schema["properties"]["sentinel"]["const"] == (
        "SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY"
    )
    assert "runtime_trigger_candidate_verifier_ready" in schema["properties"][
        "adoption_state"
    ]["enum"]
    assert "runtime_enforced" in schema["properties"]["adoption_state"]["enum"]
    boundary = schema["properties"]["adoption_state_boundary"]
    assert "adoption_state_boundary" in schema["required"]
    assert "runtime_trigger_candidate_verifier_ready" in boundary["properties"][
        "adoption_state"
    ]["enum"]
    assert "runtime_enforced" in boundary["properties"]["adoption_state"]["enum"]
    assert "default_main_loop_trigger_candidate_only" in boundary["properties"][
        "scope"
    ]["enum"]
    assert (
        "default_main_loop_trigger_task_scoped_qwen_dp_worker_pool"
        in boundary["properties"]["scope"]["enum"]
    )
    assert boundary["properties"]["not_global_default_trigger"]["const"] is True
    assert boundary["properties"]["root_loop_every_wave_enforced"]["const"] is False
    assert "runtime_enforced_scope" in boundary["required"]
    assert schema["properties"]["target_user_correction_runtime_service_method"][
        "const"
    ] == "SeedCortexService.seed_lab_user_correction_runtime"
    assert schema["properties"]["target_user_correction_runtime_fastapi_route"][
        "const"
    ] == "POST /runtime/seed-lab-user-correction-runtime"
    assert schema["properties"]["target_user_correction_runtime_cli_command"][
        "const"
    ].endswith("seed-lab-user-correction-runtime")
    assert schema["properties"]["user_correction_runtime_api_cli_adoption_state"][
        "const"
    ] == "api_cli_verifier_ready_not_hook_enforced"
    assert "user_correction_runtime_refs" in schema["required"]
    assert "scheduler_lane_evidence_refs" in schema["required"]
    assert "scheduler_spawned_lane_evidence_refs" in schema["required"]
    assert "trigger_truth_chain" in schema["required"]
    assert "provider_worker_pool_invocation" in schema["required"]
    assert "evidence_refs" in schema["required"]
    user_correction = schema["properties"]["user_correction_runtime_refs"]["properties"]
    assert user_correction["explicit_service_api_candidate"]["const"] is True
    assert user_correction["invoked_by_default_trigger"]["const"] is False
    assert user_correction["runtime_enforced"]["const"] is False
    assert user_correction["trigger_installed"]["const"] is False
    assert user_correction["memory_promotion_allowed"]["const"] is False
    assert user_correction["policy_promotion_allowed"]["const"] is False
    assert user_correction["completion_claim_allowed"]["const"] is False
    assert user_correction["refs_are_evidence_only"]["const"] is True
    assert user_correction["refs_are_not_completion_gates"]["const"] is True
    assert user_correction["refs_are_not_execution_controllers"]["const"] is True
    scheduler_refs = schema["properties"]["scheduler_lane_evidence_refs"]["properties"]
    assert scheduler_refs["bound_for_discovery_only"]["const"] is True
    assert scheduler_refs["runtime_enforced"]["const"] is False
    assert scheduler_refs["default_runtime_scheduler_invoked"]["const"] is False
    assert scheduler_refs["refs_are_not_execution_controllers"]["const"] is True
    actual_dispatch = schema["properties"]["actual_dispatch_refs"]
    for field in (
        "dp_sidecar_execution_port_runner_ref",
        "dp_sidecar_execution_provider_ref",
        "dp_sidecar_execution_provider_manifest_ref",
        "dp_sidecar_execution_callable_entrypoint_bound",
    ):
        assert field in actual_dispatch["required"]
    assert (
        actual_dispatch["properties"]["dp_sidecar_execution_callable_entrypoint_bound"][
            "const"
        ]
        is True
    )
    spawned_refs = schema["properties"]["scheduler_spawned_lane_evidence_refs"][
        "properties"
    ]
    spawned_required = schema["properties"]["scheduler_spawned_lane_evidence_refs"][
        "required"
    ]
    assert spawned_refs["candidate_discovery_scope"]["const"] == (
        "default_main_loop_trigger_candidate_ref_discovery_only"
    )
    assert spawned_refs["current_wave_lane_evidence_state"]["const"] == (
        "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert spawned_refs["activity_scoped_lane_evidence_state"]["const"] == (
        "activity_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert spawned_refs["codex_lane_evidence_discovered"]["const"] is True
    assert spawned_refs["dp_sidecar_execution_modes_discovered"]["const"] is True
    assert spawned_refs["current_wave_immutable_ref_exists"]["const"] is True
    assert spawned_refs["current_wave_immutable_digest_bound"]["const"] is True
    for field in (
        "current_wave_runtime_wave_record",
        "current_wave_runtime_wave_record_digest_sha256",
        "current_wave_selected_runtime_latest",
    ):
        assert field in spawned_required
    assert spawned_refs["dp_sidecar_execution_lanes_spawned"]["const"] is False
    assert spawned_refs["runtime_enforced"]["const"] is False
    assert spawned_refs["default_runtime_scheduler_invoked"]["const"] is False
    assert spawned_refs["refs_are_not_execution_controllers"]["const"] is True
    assert schema["properties"]["runtime_enforced"]["type"] == "boolean"
    assert schema["properties"]["runtime_enforced_scope"]["type"] == "string"
    assert schema["properties"]["trigger_installed"]["type"] == "boolean"
    assert schema["properties"]["stop_guard_layers_are_main_execution_loop"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
    truth_chain = schema["properties"]["trigger_truth_chain"]
    assert truth_chain["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.default_trigger_qwen_dp_truth_chain.v1"
    )
    assert "qwen_prepaid_cheap_worker" in truth_chain["properties"][
        "provider_lane_counts"
    ]["required"]
    assert "legacy.deepseek_dp_sidecar" in truth_chain["properties"][
        "provider_lane_counts"
    ]["required"]
    evidence_required = schema["properties"]["evidence_refs"]["required"]
    for field in (
        "scheduler_spawned_lane_evidence_current_wave_immutable",
        "scheduler_spawned_lane_evidence_current_wave_immutable_digest_sha256",
        "dp_sidecar_execution_port_runner_latest",
        "dp_sidecar_execution_provider_latest",
        "dp_sidecar_execution_provider_manifest",
    ):
        assert field in evidence_required


def test_default_trigger_does_not_default_to_static_width_24() -> None:
    module = _load_module()
    assert module.build.__kwdefaults__["phase1_target_width"] == 0

    script_text = (
        REPO_ROOT / "scripts" / "verify_default_main_loop_trigger_candidate.ps1"
    ).read_text(encoding="utf-8")
    assert "--phase1-target-width 24" not in script_text

    workflow_text = (
        REPO_ROOT / "services" / "agent_runtime" / "temporal_codex_task_workflow.py"
    ).read_text(encoding="utf-8")
    assert (
        'phase1_target_width=int(input_payload.get("phase1_target_width") or 24)'
        not in workflow_text
    )
    assert (
        'parser.add_argument("--phase1-target-width", type=int, default=24)'
        not in workflow_text
    )

    service_text = (
        REPO_ROOT / "src" / "xinao_seedlab" / "application" / "seed_cortex.py"
    ).read_text(encoding="utf-8")
    assert "phase1_target_width: int = 24" not in service_text

    cli_text = (
        REPO_ROOT / "src" / "xinao_seedlab" / "cli" / "__main__.py"
    ).read_text(encoding="utf-8")
    assert 'add_argument("--phase1-target-width", type=int, default=24)' not in cli_text

    root_driver_text = (
        REPO_ROOT / "services" / "agent_runtime" / "root_intent_loop_driver.py"
    ).read_text(encoding="utf-8")
    assert "phase1_target_width: int = 24" not in root_driver_text
    assert 'add_argument("--phase1-target-width", type=int, default=24)' not in root_driver_text
