import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT
    / "services"
    / "agent_runtime"
    / "codex_native_provider_scheduler_phase4.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("phase4", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_turn_provider_routes_structural_blocker_repair_to_v4pro(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "local_ollama_pool_status",
        lambda timeout_seconds=2: {"ready": False, "ready_provider_ids": []},
    )

    decision = module.worker_turn_provider_decision(
        {
            "provider_route_key": "structural_blocker_repair",
            "structural_blocker_repair": True,
            "worker_kind": "control_plane_repair_worker",
        }
    )

    assert decision["provider_id"] == "deepseek_v4_pro"
    assert decision["mode"] == "audit"
    assert decision["route_reason"] == "structural_blocker_repair_v4pro"


def test_provider_scheduler_registers_codex_native_default_and_dp_aux(tmp_path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    phase3_latest = runtime / "state" / module.PHASE3_TASK_ID / "latest.json"
    phase3_latest.parent.mkdir(parents=True, exist_ok=True)
    phase3_latest.write_text(
        json.dumps(
            {
                "phase1_payload_summary": {
                    "draft_count": 5,
                    "staged_count": 5,
                    "merged_count": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    cached_codex = runtime / "state" / module.TASK_ID / "logs" / "codex_exec_canary.last_message.json"
    cached_codex.parent.mkdir(parents=True, exist_ok=True)
    cached_codex.write_text(
        json.dumps(
            {
                "provider_id": "codex_exec",
                "status": "ready",
                "capability": "non_interactive_engineering_worker",
                "no_file_edits": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "codex_version",
        lambda runtime_root, cwd: {
            "installed": True,
            "path": "codex",
            "version": "codex-cli 0.142.3",
        },
    )
    monkeypatch.setattr(
        module,
        "module_available",
        lambda name: name in {"openai_codex", "agents", "litellm", "temporalio", "openai"},
    )
    monkeypatch.setattr(
        module,
        "qwen_secret_status",
        lambda runtime_root: {
            "api_key_available": True,
            "api_key_source_label": "runtime_private_config:qwen_key_txt_path",
            "named_blocker": "",
            "env_vars": ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"],
        },
    )
    monkeypatch.setattr(
        module,
        "local_ollama_status",
        lambda timeout_seconds=5: {
            "ready": True,
            "status": "local_ollama_qwen_ready",
            "selected_model": "qwen3:8b",
            "executable": "ollama",
            "models": ["qwen3:8b"],
            "named_blocker": "",
        },
    )

    payload = module.run_provider_scheduler(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase4-test-wave-001",
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )

    providers = {
        item["provider_id"]: item for item in payload["provider_registry"]["providers"]
    }
    assert payload["validation"]["passed"] is True
    assert payload["codex_native_default_primary"] is False
    assert payload["codex_brain_only_default"] is True
    assert payload["codex_bulk_worker_default_paused"] is True
    assert payload["default_token_saving_worker_route"] is True
    assert providers["codex_exec"]["default"] == "on_for_brain_acceptance"
    assert providers["codex_exec"]["role"] == "brain_route_high_risk_final_acceptance_executor"
    assert providers["codex_exec"]["status"] == "ready"
    assert providers["codex_sdk"]["status"] == "ready"
    assert providers["codex_mcp_agents"]["status"] == "ready"
    assert providers["qwen_dashscope"]["status"] == "ready"
    assert providers["local_ollama_qwen"]["status"] == "ready"
    assert providers["local_ollama_qwen"]["outputs_to_staging_only"] is True
    assert providers["local_ollama_qwen"]["direct_repo_write_allowed"] is False
    assert providers["local_ollama_qwen"]["not_search_provider"] is True
    assert providers["local_ollama_qwen"]["local_first_mandatory"] is False
    assert providers["local_ollama_qwen3"]["status"] == "ready"
    assert providers["local_ollama_qwen3"]["dynamic_router_candidate"] is True
    assert providers["local_ollama_qwen3"]["local_first_mandatory"] is False
    assert providers["qwen_prepaid_cheap_worker"]["default"] == "on_first_for_cheap_work"
    assert providers["qwen_prepaid_cheap_worker"]["outputs_to_staging_only"] is True
    assert providers["deepseek_dp"]["primary_bulk_staging_worker"] is True
    assert providers["deepseek_dp"]["outputs_to_staging_only"] is True
    assert providers["deepseek_v4_pro"]["primary_hard_staging_worker"] is True
    assert providers["deepseek_v4_pro"]["deepseek_v4_pro_main_worker_eligible"] is True
    assert payload["scheduler_decision"]["active_primary_executor_pool"] == []
    assert payload["scheduler_decision"]["active_codex_brain_pool"] == [
        "codex_exec",
        "codex_sdk",
    ]
    assert payload["scheduler_decision"]["active_local_model_pool"] == ["local_ollama_qwen3"]
    assert payload["scheduler_decision"]["active_prepaid_cheap_pool"] == ["qwen_prepaid_cheap_worker"]
    assert payload["scheduler_decision"]["active_aux_draft_pool"] == [
        "local_ollama_qwen3",
        "qwen_prepaid_cheap_worker",
        "deepseek_dp",
    ]
    assert payload["scheduler_decision"]["route_policy"]["draft_extraction_classify_eval"][:2] == [
        "qwen_prepaid_cheap_worker",
        "local_ollama_qwen3",
    ]
    assert payload["scheduler_decision"]["route_policy"]["cheap_parallel_draft"][:2] == [
        "qwen_prepaid_cheap_worker",
        "local_ollama_qwen3",
    ]
    assert payload["scheduler_decision"]["local_model_candidate_when_scored"] is True
    assert payload["scheduler_decision"]["local_first_mandatory"] is False
    assert payload["scheduler_decision"]["route_policy"]["engineering_patch_or_test"][0] == "qwen_code_diversity_worker"
    assert payload["scheduler_decision"]["route_policy"]["complex_audit_contradiction_key_plan_review"][:2] == [
        "deepseek_v4_pro",
        "deepseek_dp",
    ]
    assert "codex_exec" not in payload["scheduler_decision"]["route_policy"]["draft_extraction_classify_eval"]
    assert "codex_exec" in payload["scheduler_decision"]["route_policy"]["codex_brain_decision"]
    assert "codex_exec" in payload["scheduler_decision"]["route_policy"]["final_merge_artifact_acceptance"]
    assert payload["scheduler_decision"]["codex_brain_only_budget"]["target_codex_share_min"] == 0.10
    assert payload["scheduler_decision"]["codex_brain_only_budget"]["target_codex_share_max"] == 0.20
    assert payload["executor_adapter"]["default_primary_executor_pool"] == []
    assert payload["executor_adapter"]["codex_brain_pool"] == ["codex_exec", "codex_sdk"]
    assert payload["executor_adapter"]["default_staging_executor_pool"] == [
        "local_ollama_qwen3",
        "qwen_prepaid_cheap_worker",
        "deepseek_dp",
        "deepseek_v4_pro",
    ]
    assert payload["qwen_prepaid_policy"]["codex_final_patch_acceptance_only_when_token_saving"] is True
    assert payload["model_gateway"]["status"] == "model_gateway_ready"
    assert payload["model_gateway"]["binding_id"] == "p0_004_litellm_default_binding"
    assert payload["model_gateway"]["routed_by"] == "litellm"
    assert payload["model_gateway"]["router_provider_id"] == "litellm_router"
    assert payload["model_gateway"]["default_hot_path"] is True
    assert payload["model_gateway"]["hand_rolled_gateway_default"] is False
    assert payload["model_gateway"]["default_route_binding"]["status"] == "default_route_bound"
    assert payload["model_gateway"]["default_route_binding"]["success_field"] == "routed_by=litellm"
    retry_policy = payload["model_gateway"]["default_route_binding"]["retry_policy"]
    assert retry_policy["policy_id"] == "bounded_delivery_retry"
    assert retry_policy["scope"] == "same_deliverable_binding_only"
    assert retry_policy["max_attempts"] == 3
    assert retry_policy["max_recursive_repairs"] == 2
    assert retry_policy["retry_same_deliverable_on_failure"] is True
    assert retry_policy["continue_to_next_task_only_after"] == "accepted_for_binding"
    assert retry_policy["failure_terminal_blocker"] == "LITELLM_BINDING_RETRY_BUDGET_EXHAUSTED"
    assert retry_policy["next_frontier_on_failure"] is False
    assert retry_policy["empty_retry_forbidden"] is True
    assert payload["scheduler_decision"]["model_gateway_binding"]["success_decision"] == "accepted_for_binding"
    assert payload["scheduler_decision"]["p0_004_litellm_default_binding"] is True
    assert payload["binding_acceptance"]["artifact_acceptance_decision"] == "accepted_for_binding"
    assert payload["binding_acceptance"]["next_frontier_default_exit"] is False
    assert payload["artifact_acceptance_decision"] == "accepted_for_binding"
    assert payload["accepted_for"] == "accepted_for_binding"
    assert payload["next_frontier_default_exit"] is False
    assert payload["validation"]["checks"]["p0_004_litellm_default_binding_bound"] is True
    assert payload["validation"]["checks"]["p0_004_bounded_retry_policy_ready"] is True
    assert payload["validation"]["checks"]["model_gateway_routes_routed_by_litellm"] is True
    gateway_routes = {
        item["route_id"]: item for item in payload["model_gateway"]["routes"]
    }
    assert gateway_routes["codex-brain-acceptance"]["providers"] == ["codex_exec", "codex_sdk"]
    assert gateway_routes["cheap-draft-augmentation"]["providers"][:2] == [
        "qwen_prepaid_cheap_worker",
        "local_ollama_qwen3",
    ]
    assert gateway_routes["source-family-research"]["providers"][:2] == ["search", "local_ollama_qwen3"]
    for route_id, route in gateway_routes.items():
        assert route["routed_by"] == "litellm"
        assert route["router_provider_id"] == "litellm_router"
        if route_id != "codex-brain-acceptance":
            assert "codex_exec" not in route["providers"]
            assert "codex_sdk" not in route["providers"]
    model_gateway_stage = next(
        item for item in payload["draft_staging"]["items"] if item["artifact_id"] == "model_gateway"
    )
    assert model_gateway_stage["accepted_for"] == "accepted_for_binding"
    assert model_gateway_stage["success_decision"] == "accepted_for_binding"
    assert model_gateway_stage["retry_policy"]["policy_id"] == "bounded_delivery_retry"
    assert payload["provider_invocation"]["codex_exec"]["status"] == (
        "codex_exec_cached_canary_ready"
    )
    assert payload["provider_invocation"]["codex_exec"]["invoke_performed"] is False
    assert payload["provider_invocation"]["codex_exec"]["last_message_ref"]
    assert payload["draft_staging"]["staged_count"] >= 5
    assert payload["merge_consumer"]["merged_count"] == 1

    latest = runtime / "state" / module.TASK_ID / "latest.json"
    manifest = runtime / "capabilities" / "codex_s.provider_scheduler" / "manifest.json"
    readback = runtime / "readback" / "zh" / f"{module.TASK_ID}.md"
    assert latest.is_file()
    assert manifest.is_file()
    assert "现在能 invoke 什么" in readback.read_text(encoding="utf-8")


def test_missing_dp_remains_named_blocker_not_fake_success(tmp_path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    monkeypatch.setattr(
        module,
        "codex_version",
        lambda runtime_root, cwd: {
            "installed": True,
            "path": "codex",
            "version": "codex-cli 0.142.3",
        },
    )
    monkeypatch.setattr(
        module,
        "module_available",
        lambda name: name in {"openai_codex", "agents", "litellm", "temporalio", "openai"},
    )
    monkeypatch.setattr(
        module,
        "qwen_secret_status",
        lambda runtime_root: {
            "api_key_available": True,
            "api_key_source_label": "runtime_private_config:qwen_key_txt_path",
            "named_blocker": "",
            "env_vars": ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"],
        },
    )

    payload = module.run_provider_scheduler(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase4-dp-blocked-wave-001",
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )

    providers = {
        item["provider_id"]: item for item in payload["provider_registry"]["providers"]
    }
    assert providers["deepseek_dp"]["status"] == "blocked"
    assert providers["deepseek_dp"]["named_blocker"] == "DP_DRAFT_POOL_NOT_RUNNING"
    assert "DP_DRAFT_POOL_NOT_RUNNING" in payload["named_blockers"]
    assert payload["validation"]["checks"]["dp_legacy_aux_flag_compat_only"] is True
    assert payload["validation"]["checks"]["deepseek_dynamic_escalation_before_codex_without_fixed_share"] is True
    assert payload["validation"]["checks"]["qwen_prepaid_first_for_cheap_extract_scope"] is True
    assert payload["status"] == "codex_native_provider_scheduler_ready_with_named_blockers"


def test_provider_cost_routing_switch_defaults_codex_brain_only_and_can_restore_codex_primary(tmp_path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    registry = {
        "providers": [
            {"provider_id": "codex_exec", "status": "ready"},
            {"provider_id": "codex_sdk", "status": "ready"},
            {"provider_id": "local_ollama_qwen", "status": "ready"},
            {"provider_id": "local_ollama_qwen3", "status": "ready"},
            {"provider_id": "qwen_prepaid_cheap_worker", "status": "ready"},
            {"provider_id": "deepseek_dp", "status": "ready"},
            {"provider_id": "deepseek_v4_pro", "status": "ready"},
            {"provider_id": "qwen_quality_aux_worker", "status": "ready"},
        ]
    }

    default_policy = module.load_provider_cost_routing_policy(runtime)
    default_decision = module.build_scheduler_decision(
        registry,
        provider_cost_routing_policy=default_policy,
        budget_gate={"active": True, "scheduler_action": "route_qwen_dp_first_codex_final_only"},
    )

    assert default_policy["effective_mode"] == "codex_brain_only"
    assert default_policy["codex_brain_only_global_default"] is True
    assert default_decision["default_route_binding"]["routed_by"] == ""
    assert default_decision["default_route_binding"]["failure_blocker"] == "LITELLM_NOT_ON_DEFAULT_PATH"
    assert default_decision["default_route_binding"]["retry_policy"]["max_attempts"] == 3
    assert default_decision["default_route_binding"]["retry_policy"]["next_frontier_on_failure"] is False
    assert default_decision["model_gateway_binding"]["success_decision"] == "accepted_for_binding"
    assert default_decision["p0_004_litellm_default_binding"] is False
    assert default_decision["default_route"][:2] == ["qwen_prepaid_cheap_worker", "local_ollama_qwen3"]
    assert default_decision["codex_brain_only_default"] is True
    assert default_decision["route_policy"]["engineering_patch_or_test"][0] == "qwen_code_diversity_worker"
    assert default_decision["route_policy"]["draft_extraction_classify_eval"][:2] == [
        "qwen_prepaid_cheap_worker",
        "local_ollama_qwen3",
    ]
    assert default_decision["route_policy"]["cheap_parallel_draft"][:2] == [
        "qwen_prepaid_cheap_worker",
        "local_ollama_qwen3",
    ]
    assert default_decision["route_policy"]["source_family_research"][:2] == ["search", "local_ollama_qwen3"]
    assert default_decision["local_first_mandatory"] is False
    assert default_decision["route_policy"]["final_merge_artifact_acceptance"][0] == "codex_exec"
    assert default_decision["codex_brain_only_budget"]["fixed_deepseek_share_target_used"] is False
    assert default_decision["codex_brain_only_budget"]["deepseek_worker_share_strategy"] == (
        "dynamic_escalation_after_qwen_when_suitable"
    )
    assert default_decision["fixed_deepseek_share_target_used"] is False
    assert default_decision["deepseek_worker_share_strategy"] == (
        "dynamic_escalation_after_qwen_when_suitable"
    )
    assert default_decision["codex_brain_only_budget"]["qwen_default_scope"] == "cheap_extract_classify_compress_only"
    assert default_decision["codex_brain_only_budget"]["cheap_local_provider"] == "local_ollama_qwen3"
    assert default_decision["active_primary_executor_pool"] == []
    assert default_decision["active_codex_brain_pool"] == ["codex_exec", "codex_sdk"]
    assert default_decision["active_local_model_pool"] == ["local_ollama_qwen3"]
    assert default_decision["codex_bulk_worker_default_paused"] is True
    assert default_decision["codex_native_execution_default_primary"] is False
    assert "deepseek_v4_pro" in default_decision["route_policy"][
        "complex_audit_contradiction_key_plan_review"
    ]

    policy_path = runtime / "state" / "provider_cost_routing_policy" / "latest.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps({"mode": "codex_primary"}), encoding="utf-8")
    codex_policy = module.load_provider_cost_routing_policy(runtime)
    codex_decision = module.build_scheduler_decision(
        registry,
        provider_cost_routing_policy=codex_policy,
        budget_gate={"active": True, "scheduler_action": "continue_codex_primary_with_cost_metering"},
    )

    assert codex_policy["effective_mode"] == "codex_primary"
    assert codex_decision["default_route"][0] == "codex_exec"
    assert codex_decision["active_primary_executor_pool"] == ["codex_exec", "codex_sdk"]
    assert codex_decision["codex_bulk_worker_default_paused"] is False
    assert codex_decision["codex_native_execution_default_primary"] is True


def test_provider_scheduler_consumes_strategy_mutation_and_budget_gate(tmp_path, monkeypatch) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    strategy_latest = runtime / "state" / "strategy_mutation" / "latest.json"
    strategy_latest.parent.mkdir(parents=True, exist_ok=True)
    strategy_latest.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.progress_self_evolution.v1.strategy_mutation.v1",
                "status": "strategy_mutation_active",
                "active": True,
                "wave_id": "strategy-wave",
                "next_mode": "external_mature_reduce_width_drain_then_replan",
                "mutation_type": "external_mature_discovery_reduce_width_drain",
                "max_width_cap": 3,
                "drain_only": True,
                "replan_frontier": True,
                "provider_route_hints": {
                    "complex_audit_contradiction_key_plan_review": [
                        "codex_exec",
                        "deepseek_dp",
                        "qwen_quality_aux_worker",
                    ]
                },
                "preferred_provider_order": ["codex_exec", "qwen_prepaid_cheap_worker", "deepseek_dp"],
                "provider_policy_override": {"max_width_cap": 3},
                "external_mature_source_refs": ["source-ledger-ref", "claim-card-ref"],
                "progress_ledger_ref": "progress-ref",
            }
        ),
        encoding="utf-8",
    )
    spend_latest = runtime / "state" / "modular_dynamic_worker_pool_phase1" / "spend_ledger" / "latest.json"
    spend_latest.parent.mkdir(parents=True, exist_ok=True)
    spend_latest.write_text(
        json.dumps({"cost_usd": 2.0, "accepted_artifact_count": 0}),
        encoding="utf-8",
    )
    phase3_latest = runtime / "state" / module.PHASE3_TASK_ID / "latest.json"
    phase3_latest.parent.mkdir(parents=True, exist_ok=True)
    phase3_latest.write_text(
        json.dumps({"phase1_payload_summary": {"draft_count": 5, "staged_count": 5, "merged_count": 0}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "codex_version",
        lambda runtime_root, cwd: {
            "installed": True,
            "path": "codex",
            "version": "codex-cli 0.142.3",
        },
    )
    monkeypatch.setattr(
        module,
        "module_available",
        lambda name: name in {"openai_codex", "agents", "litellm", "temporalio", "openai"},
    )
    monkeypatch.setattr(
        module,
        "qwen_secret_status",
        lambda runtime_root: {
            "api_key_available": True,
            "api_key_source_label": "runtime_private_config:qwen_key_txt_path",
            "named_blocker": "",
            "env_vars": ["DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL"],
        },
    )

    payload = module.run_provider_scheduler(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase4-strategy-mutation-wave",
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )

    decision = payload["scheduler_decision"]
    assert payload["strategy_mutation_consumption"]["strategy_mutation_consumed"] is True
    assert decision["provider_route_hints_consumed"] is True
    assert decision["route_policy"]["complex_audit_contradiction_key_plan_review"][0] == "deepseek_v4_pro"
    assert decision["route_policy"]["engineering_patch_or_test"][0] == "qwen_code_diversity_worker"
    assert decision["active_primary_executor_pool"] == []
    assert decision["active_codex_brain_pool"] == ["codex_exec", "codex_sdk"]
    assert decision["codex_bulk_worker_default_paused"] is True
    assert payload["budget_gate"]["active"] is True
    assert decision["budget_gate_consumed"] is True
    assert decision["budget_gate"]["scheduler_action"] == (
        "limit_codex_only_keep_qwen_dp_dynamic_width"
    )
    assert decision["budget_gate"]["width_cap_scope"] == "codex_only"
    assert decision["budget_gate"]["max_width_cap"] == 0
    assert decision["budget_gate"]["max_codex_width_cap"] == 1
    assert decision["budget_gate"]["max_qwen_dp_width_cap"] == 0
    assert decision["budget_gate"]["qwen_dp_dynamic_width_unlimited"] is True
    assert payload["validation"]["checks"]["strategy_mutation_consumed_when_active"] is True
    assert payload["validation"]["checks"]["budget_gate_has_scheduler_action"] is True
