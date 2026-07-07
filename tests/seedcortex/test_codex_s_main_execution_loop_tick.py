import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_s_main_execution_loop_tick.py"
PROGRESS_PATH = REPO_ROOT / "services" / "agent_runtime" / "progress_self_evolution.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_main_execution_loop_tick.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_s_main_execution_loop_tick", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_progress_module():
    spec = importlib.util.spec_from_file_location("progress_self_evolution_tick_test", PROGRESS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_anchors(anchor_root: Path) -> None:
    resources = {
        "01_总说明_本项目是什么_20260707.txt": "当前 P0 项目边界\nRootIntentLoop 默认内核\n",
        "02_P0_底座全自动任务落地_20260707.txt": "\n".join(
            [
                "P0 当前任务入口",
                "1. RootIntentLoop 默认内核",
                "2. 外部研究发现：能力获取与 Agent OS",
                "2.1 MCP Registry",
                "3. 高噪声正期望搜索引擎",
                "3.1 防过拟合 / lockbox",
                "4. 源文本主题 A",
                "4.1 源文本主题 B",
                "4.2 源文本主题 C",
                "4.3 源文本主题 D",
                "4.4 源文本主题 E",
                "4.5 源文本主题 F",
                "4.6 源文本主题 G",
                "4.7 源文本主题 H",
                "4.8 源文本主题 I",
                "4.9 源文本主题 J",
            ]
        ),
        "03_P1_任务落地_20260707.txt": "P1 当前任务门禁上下文\n",
    }
    anchor_root.mkdir(parents=True, exist_ok=True)
    for name, body in resources.items():
        (anchor_root / name).write_text(body + "\n", encoding="utf-8")
    (anchor_root / "TASK_PACKAGE.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.task_package_manifest.v1",
                "package_mode": "current_system_p0",
                "entrypoint": "02_P0_底座全自动任务落地_20260707.txt",
                "resources": [
                    {"path": name, "role": "current_task_source", "read": "full"}
                    for name in resources
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_runtime_refs(runtime: Path, *, include_worker_ledger: bool = False) -> None:
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
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "metaminute_preflight_reflection": {
            "schema_version": "xinao.codex_s.metaminute_preflight_reflection.v1",
            "status": "metaminute_preflight_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "default_parallelism_policy": {
            "schema_version": "xinao.codex_s.default_parallelism_policy.v1",
            "status": "default_parallelism_policy_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
        "parallel_dispatch_plan": {
            "schema_version": "xinao.codex_s.parallel_dispatch_plan.v1",
            "sentinel": "SENTINEL:XINAO_PARALLEL_DISPATCH_PLAN_READY",
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
        "codex_s_live_backend_watch": {
            "schema_version": "xinao.codex_s.live_backend_watch.v1",
            "status": "live_backend_watch_idle_or_unavailable",
            "foreground_poll_required": False,
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
    }
    for state_name, payload in refs.items():
        _write_json(runtime / "state" / state_name / "latest.json", payload)
    _write_json(
        runtime / "state" / "dp_sidecar_execution_port" / "latest.json",
        {
            "schema_version": "xinao.codex_s.dp_sidecar_execution_port.v1",
            "status": "dp_sidecar_execution_port_runner_ready",
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "dp_sidecar_execution_provider" / "latest.json",
        {
            "schema_version": "xinao.seedcortex.dp_sidecar_execution_provider.v1",
            "status": "dp_sidecar_execution_provider_ready",
            "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": False,
            "trigger_installed": False,
            "validation": {"passed": True},
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
            "provider_id": "legacy.deepseek_dp_sidecar",
            "port_id": "dp_sidecar_execution_port",
            "capability_kinds": ["dp_sidecar_execution"],
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "status": "worker_dispatch_ledger_verifier_passed_not_hooked",
            "runtime_enforced": True,
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_write_activity",
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "codex_s_main_execution_loop_tick" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.codex_s.main_execution_loop_tick.v1",
            "status": "main_execution_loop_tick_ready",
            "runtime_entrypoint_invocation": {
                "runtime_enforced": True,
                "runtime_enforced_scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
                "not_execution_controller": True,
                "not_completion_gate": True,
            },
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    if include_worker_ledger:
        _write_json(
            runtime / "state" / "worker_dispatch_ledger" / "latest.json",
            {
                "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
                "status": "worker_dispatch_ledger_ready",
                "validation": {"passed": True},
                "not_execution_controller": True,
            },
        )


def test_tick_invokes_guard_source_durable_packet_and_worker_ledger(
    tmp_path: Path,
) -> None:
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

    assert payload["schema_version"] == "xinao.codex_s.main_execution_loop_tick.v1"
    assert payload["status"] == "main_execution_loop_tick_ready"
    assert payload["adoption_state"] == "verifier_ready_but_not_hooked"
    assert payload["ordinary_discussion_can_stop"] is True
    assert payload["current_four_text_same_source_task_no_stop"] is True
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
    assert payload["invoked_runners"]["live_backend_watch"]["foreground_poll_required"] is False
    assert payload["invoked_runners"]["source_anchor_gap_continuation"][
        "continue_dispatch_expected"
    ] is False
    assert payload["invoked_runners"]["durable_parallel_wave_packet"][
        "continue_dispatch_expected"
    ] is True
    preflight = payload["runtime_preflight_refs"]
    source_surface = preflight["source_frontier_fanin_acceptance_surface"]
    correction_surface = preflight["seed_lab_user_correction_runtime_surface"]
    allocation_surface = preflight["allocation_plan"]
    pre_pass_surface = preflight["pre_pass_audit_loop"]
    assert preflight["preflight_refs_are_evidence_only"] is True
    assert preflight["preflight_refs_are_not_stop_guard_layers"] is True
    assert preflight["preflight_refs_are_not_completion_gates"] is True
    assert preflight["preflight_refs_are_not_execution_controllers"] is True
    assert source_surface["task_id"] == "wave3_20260702_absorption_slice_20260704"
    assert source_surface["parent_task_id"] == "xinao_seed_cortex_phase0_20260701"
    assert source_surface["routing"] == "continue_same_task"
    assert source_surface["fan_in_acceptance_queue_default_heart"] is True
    assert source_surface["provider_scheduler_main_task"] is False
    assert source_surface["source_package_gap_open"] is True
    assert source_surface["runtime_enforced"] is False
    assert source_surface["trigger_installed"] is False
    assert source_surface["validation_passed"] is True
    assert source_surface["not_execution_controller"] is True
    assert correction_surface["invoked_by_main_execution_loop_tick"] is True
    assert correction_surface["refs_ready_for_durable_packet"] is True
    assert correction_surface["runtime_enforced"] is False
    assert correction_surface["trigger_installed"] is False
    assert correction_surface["memory_promotion_allowed"] is False
    assert correction_surface["policy_promotion_allowed"] is False
    assert correction_surface["completion_claim_allowed"] is False
    assert correction_surface["not_execution_controller"] is True
    scheduler_surface = preflight["scheduler_current_parent_surface"]
    assert scheduler_surface["invoked_by_main_execution_loop_tick"] is True
    assert scheduler_surface["refs_ready_for_durable_packet"] is True
    assert scheduler_surface["scheduler_invocation_status"] == "spawned_lane_refs_recorded"
    assert scheduler_surface["scheduler_invoked"] is True
    assert scheduler_surface["parent_dispatch_invoked"] is True
    assert scheduler_surface["scheduler_spawned_lane_count"] == 2
    assert scheduler_surface["current_parent_lane_evidence_state"] == (
        "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert scheduler_surface["default_runtime_scheduler_invoked"] is False
    assert scheduler_surface["runtime_enforced"] is False
    assert scheduler_surface["trigger_installed"] is False
    assert scheduler_surface["completion_claim_allowed"] is False
    assert scheduler_surface["not_execution_controller"] is True
    external_bridge_surface = preflight["external_mature_strategy_mutation_bridge"]
    assert external_bridge_surface["validation_passed"] is True
    assert external_bridge_surface["completion_claim_allowed"] is False
    assert external_bridge_surface["not_execution_controller"] is True
    assert external_bridge_surface["strategy_mutation_candidate_ref"]
    assert allocation_surface["invoked_by_main_execution_loop_tick"] is True
    assert allocation_surface["target_width_source"] == "derived_from_runtime_feedback_inputs"
    assert allocation_surface["fixed_20_or_50_used"] is False
    assert allocation_surface["completion_claim_allowed"] is False
    assert allocation_surface["not_execution_controller"] is True
    assert allocation_surface["validation_passed"] is True
    allocation_lane_classes = {
        lane["lane_class"]
        for lane in payload["allocation_plan"]["lane_allocations"]
    }
    assert "cheap_draft" in allocation_lane_classes
    assert {"eval", "audit"} & allocation_lane_classes
    assert {"merge_accept", "ci_verify"} & allocation_lane_classes
    assert payload["actual_dispatch_refs"]["allocation_plan"]["target_width_source"] == (
        "derived_from_runtime_feedback_inputs"
    )
    assert payload["actual_dispatch_refs"]["allocation_plan"]["fixed_20_or_50_used"] is False
    assert pre_pass_surface["invoked_by_main_execution_loop_tick"] is True
    assert pre_pass_surface["completion_claim_allowed"] is False
    assert pre_pass_surface["not_execution_controller"] is True
    assert pre_pass_surface["validation_passed"] is True
    assert len(payload["actual_dispatch_refs"]["codex_subagents"]) == 2
    assert payload["actual_dispatch_refs"]["dp_sidecar_execution"]["default_lane_count"] == 20
    assert payload["invoked_runners"]["worker_dispatch_ledger"]["validation_passed"] is True
    assert payload["actual_dispatch_refs"]["worker_dispatch_ledger_ref"]["exists"] is True
    assert len(payload["actual_dispatch_refs"]["worker_dispatch_ledger_entries"]) >= 4
    ledger_agent_ids = {
        entry["agent_id"]
        for entry in payload["actual_dispatch_refs"]["worker_dispatch_ledger_entries"]
    }
    assert "019f22a3-13b1-73d3-8f81-1b36cc635c23" in ledger_agent_ids
    assert "019f22a3-141d-7311-bf78-69a37f9db88e" in ledger_agent_ids
    assert payload["next_wave_decision"]["decision"] == "dispatch_repair_plan"
    assert payload["next_wave_decision"]["named_blocker"] == ""
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["checks"][
        "seed_lab_user_correction_runtime_surface_prepared"
    ] is True
    assert payload["validation"]["checks"][
        "source_frontier_fanin_acceptance_surface_prepared"
    ] is True
    assert payload["validation"]["checks"]["scheduler_current_parent_surface_prepared"] is True
    assert payload["validation"]["checks"]["external_mature_bridge_surface_prepared"] is True
    assert payload["validation"]["checks"]["allocation_plan_prepared"] is True
    assert payload["validation"]["checks"]["pre_pass_audit_loop_prepared"] is True
    assert payload["completion_claim_allowed"] is False
    assert payload["phase1_data_chain_allowed"] is False
    assert payload["positive_ev_claim_allowed"] is False
    assert (
        payload["invoked_runners"]["durable_parallel_wave_packet"]["poll_refs"][
            "poll_blocks_dispatch"
        ]
        is False
    )
    assert (
        payload["invoked_runners"]["durable_parallel_wave_packet"]["poll_refs"][
            "source_frontier_ready"
        ]
        is True
    )
    assert payload["not_execution_controller"] is True
    assert (runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json").is_file()
    assert (
        runtime / "readback" / "zh" / "codex_s_main_execution_loop_tick_20260702.md"
    ).is_file()


def test_tick_uses_worker_dispatch_ledger_when_available(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime, include_worker_ledger=True)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        codex_subagents=["agent-1:worker_dispatch_ledger"],
        write=True,
    )

    assert payload["actual_dispatch_refs"]["worker_dispatch_ledger_ref"]["exists"] is True
    assert payload["actual_dispatch_refs"]["worker_dispatch_ledger_ref"]["validation_passed"] is True
    assert payload["next_wave_decision"]["decision"] == "dispatch_repair_plan"
    assert payload["next_wave_decision"]["named_blocker"] == ""


def test_tick_accepts_consumed_source_frontier_surface(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime, include_worker_ledger=True)
    _write_json(
        runtime / "state" / "source_frontier_durable_consumer" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_frontier_durable_consumer.v1",
            "status": "source_frontier_module_consumed",
            "task_id": "wave3_20260702_absorption_slice_20260704",
            "parent_task_id": "xinao_seed_cortex_phase0_20260701",
            "routing": "continue_same_task",
            "consumed_batch_ids": [
                "source_family_fanout_claimcards",
                "frontier_portfolio_four_objects",
                "private_open_source_reference_lane",
                "post_hygiene_total_source_frontier_claimcards",
                "default_loop_split_brain_unification",
                "clean_ingress_s_native_boundary",
            ],
            "remaining_batch_ids": [],
            "source_gap_open": False,
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "temporal_codex_task_worker" / "latest.json",
        {"status": "started", "pid": 9416},
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        codex_subagents=["agent-1:worker_dispatch_ledger"],
        write=True,
    )

    source_surface = payload["runtime_preflight_refs"][
        "source_frontier_fanin_acceptance_surface"
    ]
    assert payload["status"] == "main_execution_loop_tick_ready"
    assert payload["validation"]["checks"][
        "source_frontier_fanin_acceptance_surface_prepared"
    ] is True
    assert source_surface["source_package_gap_open"] is False
    assert payload["runtime_preflight_refs"]["source_family_wave_scheduler_surface"][
        "validation_passed"
    ] is True
    assert payload["runtime_preflight_refs"]["source_family_wave_scheduler_surface"][
        "source_family_count"
    ] >= 5
    assert payload["runtime_preflight_refs"]["source_family_wave_scheduler_surface"][
        "remaining_topic_family_count"
    ] >= 0
    assert payload["runtime_preflight_refs"]["source_family_wave_scheduler_surface"][
        "next_frontier_action"
    ] == "continue_phase4_total_source_frontier_absorption"
    assert payload["next_wave_decision"]["decision"] == "dispatch_repair_plan"
    assert payload["next_wave_decision"]["pre_pass_repair_plan_ref"]
    assert payload["completion_claim_allowed"] is False
    assert payload["not_user_completion"] is True


def test_tick_external_mature_bridge_mutation_is_consumed_by_allocation(
    tmp_path: Path,
) -> None:
    module = _load_module()
    progress = _load_progress_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    source_package = tmp_path / "external_mature_package.txt"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)
    source_package.write_text(
        "\n".join(
            [
                "Temporal https://docs.temporal.io/workflow-execution/continue-as-new",
                "LangGraph https://docs.langchain.com/oss/python/langgraph/persistence",
                "RabbitMQ https://www.rabbitmq.com/docs/dlx",
                "SRE https://sre.google/workbook/error-budget-policy/",
            ]
        ),
        encoding="utf-8",
    )
    feedback_ref = str(runtime / "state" / "worker_dispatch_ledger" / "latest.json")
    for index in range(2):
        progress.record_progress_bundle(
            runtime_root=runtime,
            wave_id=f"main-tick-no-progress-{index}",
            source_digest="main-tick-same-digest",
            artifact_delta_count=0,
            feedback_source_refs=[feedback_ref],
            no_progress_reason="no_artifact_or_accepted_delta",
            write=True,
        )

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        anchor_package_root=anchor,
        codex_subagents=["agent-1:worker_dispatch_ledger"],
        external_mature_source_package=source_package,
        write=True,
    )

    bridge = payload["external_mature_strategy_mutation_bridge"]
    allocation = payload["allocation_plan"]
    assert bridge["external_mature_discovery_decision"]["external_mature_discovery_required"] is True
    assert bridge["reflection_subagent_dispatch"]["dispatched_subagent_count"] == 2
    assert bridge["reflection_worker_dispatch_ledger"]["summary"]["subagent_entry_count"] == 2
    assert bridge["strategy_mutation"]["active"] is True
    assert allocation["strategy_mutation_consumption"]["strategy_mutation_consumed"] is True
    assert allocation["strategy_mutation_consumption"]["external_mature_source_refs"]
    assert payload["validation"]["checks"]["external_mature_bridge_surface_prepared"] is True
    assert payload["status"] == "main_execution_loop_tick_ready"


def test_tick_binds_current_wave_worker_ledger_when_no_subagents_are_explicit(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        codex_subagents=[],
        write=True,
    )

    durable = payload["invoked_runners"]["durable_parallel_wave_packet"]
    actual = payload["actual_dispatch_refs"]
    assert payload["status"] == "main_execution_loop_tick_ready"
    assert durable["continue_dispatch_expected"] is True
    assert len(actual["codex_subagents"]) >= 1
    assert actual["codex_subagents"][0]["source"] == "worker_dispatch_ledger"
    assert actual["worker_dispatch_ledger_entries"][0]["agent_id"] == "codex_s_current_worker"
    assert payload["next_wave_decision"]["decision"] == "dispatch_repair_plan"
    durable_latest = json.loads(
        (runtime / "state" / "durable_parallel_wave_packet" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert durable_latest["validation"]["checks"]["actual_dispatch_refs_bound"] is True
    assert durable_latest["actual_dispatch_refs"][
        "derived_codex_subagent_refs_from_worker_dispatch_ledger"
    ] is True
    assert durable_latest["validation"]["checks"][
        "scheduler_current_parent_lane_refs_bound_no_overclaim"
    ] is True


def test_tick_can_bind_temporal_worker_dispatch_ledger_activity_ref(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    anchor = tmp_path / "Desktop" / "新系统"
    _seed_anchors(anchor)
    _seed_runtime_refs(runtime)
    activity_ref = {
        "activity": "worker_dispatch_ledger",
        "status": "activity_gate_checked",
        "runtime_enforced": True,
        "ledger_succeeded_count": 1,
        "ledger_temporal_activity_latest_ref": str(
            runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json"
        ),
        "not_execution_controller": True,
    }

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        anchor_package_root=anchor,
        worker_dispatch_ledger_activity_ref=activity_ref,
        write=False,
    )

    assert payload["actual_dispatch_refs"]["worker_dispatch_ledger_activity_ref"] == activity_ref
    assert activity_ref["ledger_temporal_activity_latest_ref"] in payload["evidence_refs"]
    assert "" not in payload["evidence_refs"]


def test_next_wave_ready_requires_runtime_enforced_ledger_succeeded() -> None:
    module = _load_module()

    decision = module.decide_next_wave(
        live_payload={"foreground_poll_required": False},
        source_payload={"continue_dispatch_expected": True},
        durable_payload={"continue_dispatch_expected": True},
        worker_ledger_ref={"exists": True, "validation_passed": True},
        worker_ledger_payload={
            "succeeded_count": 1,
            "poll_result_summary": {"succeeded_count": 1},
        },
        worker_dispatch_ledger_activity_ref={
            "runtime_enforced": True,
            "ledger_succeeded_count": 1,
        },
    )

    assert decision["decision"] == "fan_in_or_next_wave_ready"
    assert decision["named_blocker"] == ""


def test_source_frontier_next_wave_takes_priority_over_live_poll_guard() -> None:
    module = _load_module()

    decision = module.decide_next_wave(
        live_payload={"foreground_poll_required": True},
        source_payload={"continue_dispatch_expected": False},
        source_frontier_payload={
            "task_id": "wave3_20260702_absorption_slice_20260704",
            "parent_task_id": "xinao_seed_cortex_phase0_20260701",
            "routing": "continue_same_task",
            "next_frontier_machine_actions": {"should_continue_loop": True},
            "validation": {"passed": True},
        },
        durable_payload={"continue_dispatch_expected": True},
        worker_ledger_ref={"exists": True, "validation_passed": True},
        worker_ledger_payload={"succeeded_count": 1},
        worker_dispatch_ledger_activity_ref={
            "runtime_enforced": True,
            "ledger_succeeded_count": 1,
        },
    )

    assert decision["decision"] == "fan_in_or_next_wave_ready"
    assert decision["named_blocker"] == ""


def test_schema_contract_preserves_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.main_execution_loop_tick.v1"
    )
    assert schema["properties"]["sentinel"]["const"] == (
        "SENTINEL:XINAO_CODEX_S_MAIN_EXECUTION_LOOP_TICK_READY"
    )
    assert schema["properties"]["adoption_state"]["const"] == "verifier_ready_but_not_hooked"
    assert schema["properties"]["ordinary_discussion_can_stop"]["const"] is True
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
    assert schema["properties"]["next_wave_decision"]["properties"]["continue_main_loop"][
        "const"
    ] is True
    surface_schema = schema["properties"]["runtime_preflight_refs"]["properties"][
        "seed_lab_user_correction_runtime_surface"
    ]["properties"]
    assert surface_schema["invoked_by_main_execution_loop_tick"]["const"] is True
    assert surface_schema["refs_ready_for_durable_packet"]["const"] is True
    assert surface_schema["runtime_enforced"]["const"] is False
    assert surface_schema["trigger_installed"]["const"] is False
    assert surface_schema["memory_promotion_allowed"]["const"] is False
    assert surface_schema["policy_promotion_allowed"]["const"] is False
    assert surface_schema["completion_claim_allowed"]["const"] is False
    assert surface_schema["not_execution_controller"]["const"] is True
    source_surface_schema = schema["properties"]["runtime_preflight_refs"]["properties"][
        "source_frontier_fanin_acceptance_surface"
    ]["properties"]
    assert source_surface_schema["task_id"]["const"] == (
        "wave3_20260702_absorption_slice_20260704"
    )
    assert source_surface_schema["parent_task_id"]["const"] == (
        "xinao_seed_cortex_phase0_20260701"
    )
    assert source_surface_schema["routing"]["const"] == "continue_same_task"
    assert source_surface_schema["fan_in_acceptance_queue_default_heart"]["const"] is True
    assert source_surface_schema["provider_scheduler_main_task"]["const"] is False
    assert source_surface_schema["source_package_gap_open"]["type"] == "boolean"
    assert source_surface_schema["runtime_enforced"]["const"] is False
    assert source_surface_schema["trigger_installed"]["const"] is False
    assert source_surface_schema["validation_passed"]["const"] is True
    assert source_surface_schema["not_execution_controller"]["const"] is True
    source_family_schema = schema["properties"]["runtime_preflight_refs"]["properties"][
        "source_family_wave_scheduler_surface"
    ]["properties"]
    assert source_family_schema["task_id"]["const"] == (
        "wave4_20260701_frontier_source_family_20260704"
    )
    assert source_family_schema["remaining_topic_family_count"]["type"] == [
        "integer",
        "null",
    ]
    assert source_family_schema["next_frontier_action"]["type"] == "string"
    assert source_family_schema["total_source_frontier_coverage_ref"]["type"] == "string"
    assert source_family_schema["validation_passed"]["const"] is True
    assert source_family_schema["not_execution_controller"]["const"] is True
    scheduler_surface_schema = schema["properties"]["runtime_preflight_refs"]["properties"][
        "scheduler_current_parent_surface"
    ]["properties"]
    assert scheduler_surface_schema["invoked_by_main_execution_loop_tick"]["const"] is True
    assert scheduler_surface_schema["refs_ready_for_durable_packet"]["const"] is True
    assert scheduler_surface_schema["scheduler_invocation_status"]["const"] == (
        "spawned_lane_refs_recorded"
    )
    assert scheduler_surface_schema["scheduler_invoked"]["const"] is True
    assert scheduler_surface_schema["parent_dispatch_invoked"]["const"] is True
    assert scheduler_surface_schema["current_parent_lane_evidence_state"]["const"] == (
        "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
    )
    assert scheduler_surface_schema["default_runtime_scheduler_invoked"]["const"] is False
    assert scheduler_surface_schema["runtime_enforced"]["const"] is False
    assert scheduler_surface_schema["trigger_installed"]["const"] is False
    assert scheduler_surface_schema["completion_claim_allowed"]["const"] is False
    assert scheduler_surface_schema["not_execution_controller"]["const"] is True
    pre_pass_schema = schema["properties"]["runtime_preflight_refs"]["properties"][
        "pre_pass_audit_loop"
    ]["properties"]
    assert pre_pass_schema["invoked_by_main_execution_loop_tick"]["const"] is True
    assert pre_pass_schema["completion_claim_allowed"]["const"] is False
    assert pre_pass_schema["not_execution_controller"]["const"] is True
    assert pre_pass_schema["validation_passed"]["const"] is True
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
