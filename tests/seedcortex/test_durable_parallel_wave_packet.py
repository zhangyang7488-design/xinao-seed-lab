import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "durable_parallel_wave_packet.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_durable_parallel_wave_packet.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("durable_parallel_wave_packet", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime_refs(
    runtime: Path,
    *,
    source_continue: bool = True,
    live_poll: bool = False,
    include_all_refs: bool = True,
) -> None:
    refs = {
        "source_anchor_gap_continuation": {
            "schema_version": "xinao.codex_s.source_anchor_gap_continuation.v1",
            "status": "source_anchor_gap_continuation_ready",
            "continue_dispatch_expected": source_continue,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "codex_s_live_backend_watch": {
            "schema_version": "xinao.codex_s.live_backend_watch.v1",
            "status": "live_backend_watch_poll_required" if live_poll else "live_backend_watch_idle",
            "foreground_poll_required": live_poll,
            "validation": {"passed": True},
            "not_execution_controller": True,
            "not_completion_decision": True,
            "not_user_completion": True,
        },
        "default_hot_path_intake": {
            "schema_version": "xinao.codex_s.default_hot_path_intake.v1",
            "status": "default_hot_path_intake_ready",
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
                    "edge_kind": "write",
                    "selected": True,
                },
                {
                    "lane_id": "dp_eval",
                    "resource_lane": "dp_sidecar_execution",
                    "edge_kind": "verify",
                    "selected": True,
                },
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
        "fan_in_acceptance_queue": {
            "schema_version": "xinao.codex_s.fan_in_acceptance.v1",
            "status": "fan_in_acceptance_ready_for_plan_evidence",
            "object_type": "FanInAcceptanceQueue",
            "fan_in_is_default_heart": True,
            "not_new_bypass_queue": True,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "claim_card_staging_queue": {
            "schema_version": "xinao.codex_s.claim_card_staging_queue.v1",
            "status": "claim_card_staging_queue_ready",
            "claim_card_count": 2,
            "non_local_source_family_count": 2,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "source_frontier_fanin_acceptance": {
            "schema_version": "xinao.codex_s.source_frontier_fanin_acceptance.v1",
            "status": "source_frontier_fanin_acceptance_ready",
            "adoption_state": "default_hot_path_ready",
            "task_id": "wave3_20260702_absorption_slice_20260704",
            "parent_task_id": "xinao_seed_cortex_phase0_20260701",
            "routing": "continue_same_task",
            "runtime_enforced": False,
            "trigger_installed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "next_frontier_machine_actions": {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "next_frontier_machine_actions_ready",
            "should_continue_loop": True,
            "stop_allowed": False,
            "sleep_1800_main_loop_allowed": False,
            "source_frontier_gap": {"source_package_gap_open": True},
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "frontier_portfolio_snapshot": {
            "schema_version": "xinao.codex_s.frontier_portfolio_snapshot.v1",
            "status": "frontier_portfolio_snapshot_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "artifact_acceptance_queue": {
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "worker_dispatch_ledger": {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "status": "worker_dispatch_ledger_verifier_passed_not_hooked",
            "validation": {"passed": True},
            "runtime_enforced": True,
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_write_activity",
            "not_execution_controller": True,
        },
        "codex_s_main_execution_loop_tick": {
            "schema_version": "xinao.codex_s.main_execution_loop_tick.v1",
            "status": "main_execution_loop_tick_ready",
            "validation": {"passed": True},
            "runtime_entrypoint_invocation": {
                "runtime_enforced": True,
                "runtime_enforced_scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
            },
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
    }
    if not include_all_refs:
        refs.pop("parallel_fan_in_acceptance")
    for state_name, payload in refs.items():
        if state_name == "worker_dispatch_ledger":
            _write_json(runtime / "state" / state_name / "temporal_activity_latest.json", payload)
        elif state_name == "codex_s_main_execution_loop_tick":
            _write_json(runtime / "state" / state_name / "temporal_activity_latest.json", payload)
        elif state_name == "seed_lab_user_correction_runtime":
            _write_json(runtime / "state" / state_name / "service_entrypoint_latest.json", payload)
            _write_json(runtime / "state" / state_name / "latest.json", payload)
        else:
            _write_json(runtime / "state" / state_name / "latest.json", payload)
    _write_json(
        runtime / "state" / "scheduler_invocation_packet" / "latest.json",
        {
            "schema_version": "xinao.codex_s.scheduler_invocation_packet.v1",
            "status": "spawned_lane_refs_recorded",
            "validation": {"passed": True},
            "scheduler_invoked": True,
            "parent_dispatch_invoked": True,
            "default_runtime_scheduler_invoked": False,
            "runtime_enforced": False,
            "not_execution_controller": True,
        },
    )
    scheduler_lane_payload = {
        "schema_version": "xinao.codex_s.scheduler_spawned_lane_evidence.v1",
        "status": "scheduler_spawned_lane_evidence_ready",
        "validation": {"passed": True},
        "lane_evidence_state": "parent_scheduler_invoked_with_lane_refs_not_default_runtime",
        "scheduler_invoked": True,
        "parent_dispatch_invoked": True,
        "activity_scope_scheduler_invoked": False,
        "default_runtime_scheduler_invoked": False,
        "runtime_enforced": False,
        "scheduler_spawned_lane_count": 2,
        "not_execution_controller": True,
    }
    _write_json(
        runtime / "state" / "scheduler_spawned_lane_evidence" / "current_parent_latest.json",
        scheduler_lane_payload,
    )
    _write_json(
        runtime / "state" / "scheduler_spawned_lane_evidence" / "current_wave_latest.json",
        scheduler_lane_payload,
    )
    _write_json(
        runtime / "state" / "scheduler_spawned_lane_evidence" / "activity_scoped_latest.json",
        {
            **scheduler_lane_payload,
            "lane_evidence_state": "activity_scheduler_invoked_with_lane_refs_not_default_runtime",
            "parent_dispatch_invoked": False,
            "activity_scope_scheduler_invoked": True,
        },
    )
    dp_provider = {
        "schema_version": "xinao.seedcortex.dp_sidecar_execution_provider.v1",
        "kind": "dp_sidecar_execution_provider",
        "status": "provider_probe_ready",
        "port_id": "dp_sidecar_execution_port",
        "provider_id": "legacy.deepseek_dp_sidecar",
        "mode": "provider_probe",
        "available_modes": [
            "draft",
            "eval",
            "contradiction",
            "extraction",
            "audit",
            "search",
            "citation_verify",
            "provider_probe",
        ],
        "dp_search_is_mode_not_port_definition": True,
        "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
        "runtime_enforced": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    _write_json(runtime / "state" / "dp_sidecar_execution_provider" / "latest.json", dp_provider)
    _write_json(
        runtime / "state" / "dp_sidecar_execution_port" / "latest.json",
        {
            "schema_version": "xinao.codex_s.dp_sidecar_execution_port_runner.v1",
            "sentinel": "SENTINEL:XINAO_DP_SIDECAR_EXECUTION_PORT_RUNNER_READY",
            "status": "dp_sidecar_execution_port_runner_ready",
            "port_id": "dp_sidecar_execution_port",
            "provider_id": "legacy.deepseek_dp_sidecar",
            "mode": "provider_probe",
            "available_modes": dp_provider["available_modes"],
            "dp_search_is_mode_not_port_definition": True,
            "provider_payload": dp_provider,
            "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime
        / "capabilities"
        / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port"
        / "manifest.json",
        {
            "schema_version": "xinao.seedcortex.project_local_capability_manifest.v1",
            "capability_id": "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port",
            "capability_kind": "dp_sidecar_execution",
            "provider_id": "legacy.deepseek_dp_sidecar",
            "registered_scope": "dp_sidecar_execution_mode",
            "available_modes": dp_provider["available_modes"],
            "dp_search_is_mode_not_port_definition": True,
            "default_route_allowed_for_capability_kind": False,
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )


def _seed_worker_dispatch_ledger_entries(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "status": "worker_dispatch_ledger_verifier_passed_not_hooked",
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
        },
    )


def test_ready_packet_binds_dispatch_subagents_dp_fan_in_and_acceptance(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime_refs(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        codex_subagents=[
            "019f22a3-13b1-73d3-8f81-1b36cc635c23:worker_dispatch_ledger",
            "019f22a3-141d-7311-bf78-69a37f9db88e:hot_path_probe",
        ],
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.durable_parallel_wave_packet.v1"
    assert payload["status"] == "durable_parallel_wave_packet_ready"
    assert payload["adoption_state"] == "verifier_ready_but_not_hooked"
    assert payload["continue_dispatch_expected"] is True
    assert payload["stop_guard_layers_are_main_execution_loop"] is False
    assert payload["main_execution_loop"] == [
        "restore",
        "dispatch",
        "poll",
        "fan_in",
        "verify_evidence_readback",
        "recompute_capacity",
        "next_wave",
    ]
    assert payload["codex_subagent_dispatch"]["recorded_subagent_count"] == 2
    assert payload["codex_subagent_dispatch"]["spawned_by_this_runner"] is False
    assert payload["dp_sidecar_execution"]["default_lane_count"] == 20
    assert sum(payload["dp_sidecar_execution"]["mode_counts"].values()) == 20
    assert payload["dp_sidecar_execution"]["dp_search_is_mode_not_port_definition"] is True
    assert payload["dp_sidecar_execution"]["runner_latest_ref"]["exists"] is True
    assert payload["dp_sidecar_execution"]["provider_latest_ref"]["exists"] is True
    assert payload["dp_sidecar_execution"]["provider_manifest_ref"]["exists"] is True
    assert payload["dp_sidecar_execution"]["callable_entrypoint_bound"] is True
    assert payload["fan_in_policy"]["fan_in_required_before_fact_promotion"] is True
    assert payload["fan_in_policy"]["artifact_acceptance_queue_required"] is True
    assert payload["fan_in_policy"]["direct_fact_promotion_allowed"] is False
    assert payload["temporal_activity_refs"]["activity_refs_are_evidence_only"] is True
    assert payload["temporal_activity_refs"]["activity_refs_are_not_stop_guard_layers"] is True
    assert payload["temporal_activity_refs"]["activity_refs_are_not_completion_gates"] is True
    assert payload["temporal_activity_refs"]["activity_refs_are_not_execution_controllers"] is True
    assert payload["actual_dispatch_refs"]["codex_subagent_count"] == 2
    assert len(payload["actual_dispatch_refs"]["codex_subagents"]) == 2
    assert payload["actual_dispatch_refs"]["dp_sidecar_execution_port"] == "dp_sidecar_execution_port"
    assert payload["actual_dispatch_refs"]["spawned_by_this_runner"] is False
    assert payload["actual_dispatch_refs"]["refs_are_evidence_only"] is True
    assert payload["actual_dispatch_refs"]["refs_are_not_completion_gates"] is True
    assert payload["actual_dispatch_refs"]["refs_are_not_execution_controllers"] is True
    assert payload["actual_dispatch_refs"]["parallel_dispatch_plan_ref"]["exists"] is True
    assert payload["actual_dispatch_refs"]["worker_dispatch_ledger_activity_ref"]["exists"] is True
    assert payload["actual_dispatch_refs"]["main_execution_loop_tick_activity_ref"]["exists"] is True
    assert payload["poll_refs"]["live_backend_watch_ref"]["exists"] is True
    assert payload["poll_refs"]["poll_policy"] == "poll_live_backend_watch_first"
    assert payload["poll_refs"]["poll_blocks_dispatch"] is False
    assert payload["poll_refs"]["source_frontier_ready"] is True
    assert payload["poll_refs"]["worker_jsonl_non_terminal_blocks_stop"] is True
    assert payload["poll_refs"]["output_growth_blocks_stop"] is True
    assert payload["fan_in_refs"]["parallel_fan_in_acceptance_ref"]["exists"] is True
    assert payload["fan_in_refs"]["fan_in_acceptance_queue_ref"]["exists"] is True
    assert payload["fan_in_refs"]["source_frontier_fanin_acceptance_ref"]["exists"] is True
    assert payload["fan_in_refs"]["next_frontier_machine_actions_ref"]["exists"] is True
    assert payload["fan_in_refs"]["fan_in_acceptance_queue_default_heart"] is True
    assert payload["fan_in_refs"]["fan_in_acceptance_queue_not_bypass_island"] is True
    assert payload["fan_in_refs"]["artifact_acceptance_queue_ref"]["exists"] is True
    assert payload["fan_in_refs"]["direct_fact_promotion_allowed"] is False
    assert payload["user_correction_runtime_refs"]["service_entrypoint_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["service_entrypoint_ref"][
        "schema_version"
    ] == "xinao.codex_s.seed_lab_user_correction_runtime.v1"
    assert payload["user_correction_runtime_refs"]["correction_intake_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["experiment_review_view_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["replay_court_ref"]["exists"] is True
    assert payload["user_correction_runtime_refs"]["explicit_service_api_candidate"] is True
    assert payload["user_correction_runtime_refs"]["runtime_enforced"] is False
    assert payload["user_correction_runtime_refs"]["trigger_installed"] is False
    assert payload["user_correction_runtime_refs"]["memory_promotion_allowed"] is False
    assert payload["user_correction_runtime_refs"]["policy_promotion_allowed"] is False
    assert payload["user_correction_runtime_refs"]["completion_claim_allowed"] is False
    assert payload["user_correction_runtime_refs"]["refs_are_not_execution_controllers"] is True
    assert Path(payload["evidence_refs"]["runtime_latest"]).parts[-3:] == (
        "state",
        "durable_parallel_wave_packet",
        "latest.json",
    )
    assert payload["evidence_refs"]["verifier"].endswith("verify_durable_parallel_wave_packet.ps1")
    assert payload["evidence_refs"][
        "seed_lab_user_correction_runtime_service_latest"
    ].replace("\\", "/").endswith(
        "seed_lab_user_correction_runtime/service_entrypoint_latest.json"
    )
    assert payload["evidence_refs"]["seed_lab_replay_court_latest"].replace(
        "\\", "/"
    ).endswith("seed_lab_replay_court/latest.json")
    assert payload["readback_refs"]["runtime_readback_zh"].endswith(
        "durable_parallel_wave_packet_20260702.md"
    )
    assert payload["readback_refs"][
        "seed_lab_user_correction_runtime_service_readback"
    ].replace("\\", "/").endswith(
        "seed_lab_user_correction_runtime_service_entrypoint_20260702.md"
    )
    assert payload["readback_refs"]["human_visible_readback_required"] is True
    assert payload["service_entrypoint"]["caller"] == (
        "services.agent_runtime.durable_parallel_wave_packet.build"
    )
    assert payload["service_entrypoint"]["api_cli_adoption_state"] == (
        "api_cli_verifier_ready_not_hook_enforced"
    )
    assert payload["service_entrypoint"]["runtime_enforced"] is False
    assert payload["service_entrypoint"]["temporal_enforced"] is False
    assert payload["service_entrypoint"]["stop_hook_controller"] is False
    assert payload["service_entrypoint"]["main_execution_loop_packet_entrypoint"] is True
    assert payload["api_surface"]["fastapi_route"] == "POST /runtime/durable-parallel-wave-packet"
    assert payload["api_surface"]["cli_command"].endswith("durable-parallel-wave-packet")
    assert (
        payload["temporal_activity_refs"]["worker_dispatch_ledger_activity"]["runtime_enforced_scope"]
        == "seed_cortex_temporal_worker_dispatch_ledger_write_activity"
    )
    assert (
        payload["temporal_activity_refs"]["main_execution_loop_tick_activity"]["runtime_enforced_scope"]
        == "seed_cortex_temporal_main_execution_loop_tick_activity"
    )
    scheduler_refs = payload["scheduler_invocation_refs"]
    assert scheduler_refs["scheduler_invocation_packet_latest"]["exists"] is True
    assert scheduler_refs["scheduler_spawned_lane_evidence_current_parent"]["exists"] is True
    assert scheduler_refs["scheduler_invocation_status"] == "spawned_lane_refs_recorded"
    assert scheduler_refs["scheduler_invoked"] is True
    assert scheduler_refs["parent_dispatch_invoked"] is True
    assert scheduler_refs["current_parent_lane_evidence_state"] == (
        "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert scheduler_refs["current_parent_scheduler_spawned_lane_count"] == 2
    assert scheduler_refs["default_runtime_scheduler_invoked"] is False
    assert scheduler_refs["runtime_enforced"] is False
    assert scheduler_refs["refs_are_not_execution_controllers"] is True
    assert payload["actual_dispatch_refs"]["scheduler_invocation_packet_ref"]["exists"] is True
    assert (
        payload["actual_dispatch_refs"][
            "scheduler_spawned_lane_evidence_current_parent_ref"
        ]["exists"]
        is True
    )
    assert payload["actual_dispatch_refs"][
        "scheduler_current_parent_lane_evidence_state"
    ] == "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    assert payload["actual_dispatch_refs"]["scheduler_current_parent_spawned_lane_count"] == 2
    assert payload["actual_dispatch_refs"]["scheduler_current_parent_refs_bound"] is True
    assert payload["actual_dispatch_refs"]["dp_sidecar_execution_port_runner_ref"]["exists"] is True
    assert payload["actual_dispatch_refs"]["dp_sidecar_execution_provider_ref"]["exists"] is True
    assert payload["actual_dispatch_refs"]["dp_sidecar_execution_provider_manifest_ref"]["exists"] is True
    assert payload["actual_dispatch_refs"]["dp_sidecar_execution_callable_entrypoint_bound"] is True
    assert payload["legacy_5d33_transport_pattern"]["task_scoped_durable_owner_pattern_allowed"] is True
    assert payload["legacy_5d33_transport_pattern"]["old_5d33_owner_allowed"] is False
    assert payload["legacy_5d33_transport_pattern"]["old_pass_allowed"] is False
    assert payload["legacy_5d33_transport_pattern"]["old_latest_json_authority_allowed"] is False
    assert payload["legacy_5d33_transport_pattern"]["old_completion_gate_allowed"] is False
    assert payload["completion_claim_allowed"] is False
    assert payload["phase1_data_chain_allowed"] is False
    assert payload["positive_ev_claim_allowed"] is False
    assert payload["not_source_of_truth"] is True
    assert payload["not_user_completion"] is True
    assert payload["not_completion_decision"] is True
    assert payload["not_execution_controller"] is True
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["checks"]["actual_dispatch_refs_bound"] is True
    assert payload["validation"]["checks"]["actual_codex_subagent_or_worker_refs_present"] is True
    assert payload["validation"]["checks"]["poll_refs_bound"] is True
    assert payload["validation"]["checks"]["fan_in_refs_bound"] is True
    assert payload["validation"]["checks"]["source_frontier_fanin_refs_bound"] is True
    assert payload["validation"]["checks"]["user_correction_runtime_refs_bound"] is True
    assert payload["validation"]["checks"]["user_correction_runtime_not_enforced"] is True
    assert payload["validation"]["checks"]["scheduler_invocation_packet_ref_present"] is True
    assert (
        payload["validation"]["checks"][
            "scheduler_spawned_lane_current_parent_ref_present"
        ]
        is True
    )
    assert (
        payload["validation"]["checks"][
            "scheduler_current_parent_lane_refs_bound_no_overclaim"
        ]
        is True
    )
    assert payload["validation"]["checks"]["scheduler_refs_not_runtime_enforced"] is True
    assert payload["validation"]["checks"]["dp_sidecar_execution_callable_refs_bound"] is True
    assert payload["validation"]["checks"]["evidence_and_readback_refs_bound"] is True

    assert (runtime / "state" / "durable_parallel_wave_packet" / "latest.json").is_file()
    readback = runtime / "readback" / "zh" / "durable_parallel_wave_packet_20260702.md"
    assert readback.is_file()
    readback_text = readback.read_text(encoding="utf-8")
    assert "restore -> dispatch -> poll -> fan-in" in readback_text
    assert "user_correction_runtime_refs_bound: True" in readback_text
    assert "user_correction_runtime_enforced: False" in readback_text
    assert "scheduler_invocation_packet_ref_bound: True" in readback_text
    assert "scheduler_current_parent_lane_refs_bound: True" in readback_text
    assert "scheduler_refs_runtime_enforced: False" in readback_text
    assert "dp_sidecar_execution_callable_refs_bound: True" in readback_text


def test_ready_packet_derives_actual_worker_refs_from_dispatch_ledger_when_no_subagents(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime_refs(runtime)
    _seed_worker_dispatch_ledger_entries(runtime)

    payload = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=False)

    actual = payload["actual_dispatch_refs"]
    assert payload["status"] == "durable_parallel_wave_packet_ready"
    assert payload["codex_subagent_dispatch"]["recorded_subagent_count"] == 0
    assert actual["codex_subagent_count"] == 1
    assert actual["codex_subagents"][0]["agent_id"] == "codex_s_current_worker"
    assert actual["codex_subagents"][0]["source"] == "worker_dispatch_ledger"
    assert actual["explicit_codex_subagent_refs_provided"] is False
    assert actual["derived_codex_subagent_refs_from_worker_dispatch_ledger"] is True
    assert actual["worker_dispatch_ledger_actual_entry_ids"] == [
        "wave-1:local-worker-dispatch-ledger-writer"
    ]
    assert payload["validation"]["checks"]["actual_dispatch_refs_bound"] is True
    assert payload["validation"]["checks"]["actual_codex_subagent_or_worker_refs_present"] is True


def test_live_backend_poll_guard_only_does_not_block_source_frontier_dispatch(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime_refs(runtime, live_poll=True)

    payload = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=False)

    assert payload["status"] == "durable_parallel_wave_packet_ready"
    assert payload["continue_dispatch_expected"] is True
    assert payload["current_loop_step"] == "dispatch"
    assert payload["dispatch_blocker"] == ""
    assert payload["validation"]["checks"]["live_backend_does_not_require_poll"] is True
    assert payload["validation"]["checks"]["live_backend_poll_is_stop_guard_only"] is True
    assert (
        payload["validation"]["checks"]["live_backend_poll_does_not_block_source_frontier"]
        is True
    )
    assert payload["poll_refs"]["foreground_poll_required"] is True
    assert payload["poll_refs"]["poll_stop_guard_only"] is True
    assert payload["poll_refs"]["poll_blocks_dispatch"] is False
    assert payload["adoption_state"] == "verifier_ready_but_not_hooked"


def test_missing_runtime_ref_blocks_dispatch(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime_refs(runtime, include_all_refs=False)

    payload = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=False)

    assert payload["status"] == "durable_parallel_wave_packet_blocked"
    assert payload["continue_dispatch_expected"] is False
    assert payload["validation"]["checks"]["required_refs_present"] is False
    assert payload["runtime_refs"]["parallel_fan_in_acceptance"]["exists"] is False


def test_schema_contract_preserves_main_loop_and_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.durable_parallel_wave_packet.v1"
    )
    assert schema["properties"]["sentinel"]["const"] == (
        "SENTINEL:XINAO_DURABLE_PARALLEL_WAVE_PACKET_READY"
    )
    assert schema["properties"]["adoption_state"]["const"] == "verifier_ready_but_not_hooked"
    assert schema["properties"]["stop_guard_layers_are_main_execution_loop"]["const"] is False
    assert [item["const"] for item in schema["properties"]["main_execution_loop"]["prefixItems"]] == [
        "restore",
        "dispatch",
        "poll",
        "fan_in",
        "verify_evidence_readback",
        "recompute_capacity",
        "next_wave",
    ]
    assert schema["properties"]["codex_subagent_dispatch"]["properties"][
        "spawned_by_this_runner"
    ]["const"] is False
    assert schema["properties"]["dp_sidecar_execution"]["properties"]["default_lane_count"][
        "const"
    ] == 20
    assert schema["properties"]["dp_sidecar_execution"]["properties"][
        "callable_entrypoint_bound"
    ]["const"] is True
    assert schema["properties"]["temporal_activity_refs"]["properties"][
        "activity_refs_are_not_execution_controllers"
    ]["const"] is True
    assert "scheduler_invocation_refs" in schema["required"]
    scheduler_refs = schema["properties"]["scheduler_invocation_refs"]["properties"]
    assert scheduler_refs["scheduler_invocation_status"]["const"] == (
        "spawned_lane_refs_recorded"
    )
    assert scheduler_refs["current_parent_lane_evidence_state"]["const"] == (
        "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert scheduler_refs["default_runtime_scheduler_invoked"]["const"] is False
    assert scheduler_refs["runtime_enforced"]["const"] is False
    assert scheduler_refs["trigger_installed"]["const"] is False
    assert scheduler_refs["refs_are_not_execution_controllers"]["const"] is True
    assert schema["properties"]["actual_dispatch_refs"]["properties"]["dp_sidecar_execution_port"][
        "const"
    ] == "dp_sidecar_execution_port"
    assert schema["properties"]["actual_dispatch_refs"]["properties"][
        "dp_sidecar_execution_callable_entrypoint_bound"
    ]["const"] is True
    assert schema["properties"]["actual_dispatch_refs"]["properties"][
        "refs_are_not_execution_controllers"
    ]["const"] is True
    assert schema["properties"]["poll_refs"]["properties"]["poll_policy"]["const"] == (
        "poll_live_backend_watch_first"
    )
    assert schema["properties"]["fan_in_refs"]["properties"][
        "direct_fact_promotion_allowed"
    ]["const"] is False
    assert "user_correction_runtime_refs" in schema["required"]
    user_correction = schema["properties"]["user_correction_runtime_refs"]["properties"]
    assert user_correction["runtime_enforced"]["const"] is False
    assert user_correction["trigger_installed"]["const"] is False
    assert user_correction["memory_promotion_allowed"]["const"] is False
    assert user_correction["policy_promotion_allowed"]["const"] is False
    assert user_correction["completion_claim_allowed"]["const"] is False
    assert user_correction["refs_are_evidence_only"]["const"] is True
    assert user_correction["refs_are_not_completion_gates"]["const"] is True
    assert user_correction["refs_are_not_execution_controllers"]["const"] is True
    evidence_required = set(schema["properties"]["evidence_refs"]["required"])
    assert {
        "seed_lab_user_correction_runtime_service_latest",
        "seed_lab_correction_intake_latest",
        "seed_lab_experiment_review_view_latest",
        "seed_lab_replay_court_latest",
        "scheduler_invocation_packet_latest",
        "scheduler_spawned_lane_evidence_current_parent_latest",
        "scheduler_spawned_lane_evidence_current_wave_latest",
        "scheduler_spawned_lane_evidence_activity_scoped_latest",
        "dp_sidecar_execution_port_runner_latest",
        "dp_sidecar_execution_provider_latest",
        "dp_sidecar_execution_provider_manifest",
    } <= evidence_required
    assert "seed_lab_user_correction_runtime_service_readback" in set(
        schema["properties"]["readback_refs"]["required"]
    )
    assert schema["properties"]["readback_refs"]["properties"][
        "human_visible_readback_required"
    ]["const"] is True
    assert schema["properties"]["service_entrypoint"]["properties"][
        "api_cli_adoption_state"
    ]["const"] == "api_cli_verifier_ready_not_hook_enforced"
    assert schema["properties"]["service_entrypoint"]["properties"]["runtime_enforced"][
        "const"
    ] is False
    assert schema["properties"]["api_surface"]["properties"]["fastapi_route"]["const"] == (
        "POST /runtime/durable-parallel-wave-packet"
    )
    legacy = schema["properties"]["legacy_5d33_transport_pattern"]["properties"]
    assert legacy["old_5d33_owner_allowed"]["const"] is False
    assert legacy["old_pass_allowed"]["const"] is False
    assert legacy["old_latest_json_authority_allowed"]["const"] is False
    assert legacy["old_completion_gate_allowed"]["const"] is False
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
