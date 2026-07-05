import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "modular_dynamic_worker_pool_phase1.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "codex_s_modular_dynamic_worker_pool_phase1.v1.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "modular_dynamic_worker_pool_phase1", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_dp_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    mode = str(kwargs["mode"])
    invocation_id = str(kwargs["invocation_id"])
    result_path = runtime / "fake_dp_results" / f"{invocation_id}.{mode}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "draft_ready" if mode == "draft" else "model_ready",
                "mode": mode,
                "invocation_id": invocation_id,
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    provider_payload = {
        "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
        "selected_carrier_provider_id": (
            "seed_cortex.local_draft_artifact_provider"
            if mode == "draft"
            else "seed_cortex.local_eval_artifact_provider"
        ),
        "provider_invocation_performed": True,
        "model_invocation_performed": mode != "draft",
        "tool_invocation_performed": mode == "draft",
        "result_path": str(result_path),
        "raw_response_ref": str(result_path),
        "provider_invocation_ref": str(
            runtime / "fake_dp_results" / f"{invocation_id}.provider.json"
        ),
        "evidence_refs": {
            "latest": str(runtime / "fake_dp_results" / "latest.json"),
            "result_path": str(result_path),
        },
        "named_blocker": "",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(result_path),
            "provider_invocation_ref": provider_payload["provider_invocation_ref"],
            "provider_latest_ref": provider_payload["evidence_refs"]["latest"],
        },
    }


def _write_qwen_ready_state(runtime: Path) -> None:
    state = runtime / "state" / "codex_native_provider_scheduler_phase4_20260704"
    (state / "qwen_prepaid_policy").mkdir(parents=True, exist_ok=True)
    (state / "qwen_invocation").mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    (state / "latest.json").write_text(
        json.dumps(
            {
                "status": "codex_native_provider_scheduler_ready",
                "qwen_prepaid_cheap_worker_default_first": True,
                "codex_native_default_primary": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (state / "qwen_prepaid_policy" / "latest.json").write_text(
        json.dumps(
            {
                "status": "qwen_prepaid_policy_ready",
                "models": {"cheap_default_candidates": ["qwen3.6-flash"]},
                "secret_status": {"api_key_source_label": "test:redacted"},
                "outputs_to_staging_only": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (state / "qwen_invocation" / "latest.json").write_text(
        json.dumps(
            {
                "status": "qwen_dashscope_canary_ready",
                "succeeded": True,
                "selected_model": "qwen3.6-flash",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _fake_qwen_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    mode = str(kwargs["mode"])
    invocation_id = str(kwargs["invocation_id"])
    result_path = runtime / "fake_qwen_results" / f"{invocation_id}.{mode}.json"
    raw_path = runtime / "fake_qwen_results" / f"{invocation_id}.{mode}.raw.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "draft_ready" if mode == "draft" else "model_ready",
                "mode": mode,
                "provider_id": "qwen_prepaid_cheap_worker",
                "content": "qwen cheap worker artifact",
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    raw_path.write_text(
        json.dumps(
            {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                    "total_tokens": 18,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    provider_payload = {
        "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
        "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "tool_invocation_performed": False,
        "qwen_prepaid_first_required": True,
        "qwen_prepaid_first_attempted": True,
        "result_path": str(result_path),
        "raw_response_ref": str(raw_path),
        "provider_invocation_ref": str(
            runtime / "fake_qwen_results" / f"{invocation_id}.provider.json"
        ),
        "selected_model": "qwen3.6-flash",
        "evidence_refs": {"latest": str(runtime / "fake_qwen_results" / "latest.json")},
        "named_blocker": "",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(result_path),
            "provider_invocation_ref": provider_payload["provider_invocation_ref"],
            "provider_latest_ref": provider_payload["evidence_refs"]["latest"],
        },
    }


def _fake_qwen_timeout_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    invocation_id = str(kwargs["invocation_id"])
    record_path = runtime / "fake_qwen_results" / f"{invocation_id}.provider.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    provider_payload = {
        "mode_invocation_status": "blocked",
        "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
        "provider_invocation_performed": False,
        "model_invocation_performed": False,
        "tool_invocation_performed": False,
        "qwen_prepaid_first_required": True,
        "qwen_prepaid_first_attempted": True,
        "result_path": "",
        "raw_response_ref": "",
        "provider_invocation_ref": str(record_path),
        "selected_model": "qwen3.6-flash",
        "evidence_refs": {"latest": str(runtime / "fake_qwen_results" / "latest.json")},
        "named_blocker": "Request timed out.",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {},
    }


def _fake_external_dp_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    mode = str(kwargs["mode"])
    invocation_id = str(kwargs["invocation_id"])
    result_path = runtime / "fake_external_dp_results" / f"{invocation_id}.{mode}.json"
    raw_path = runtime / "fake_external_dp_results" / f"{invocation_id}.{mode}.raw.json"
    provider_ref = runtime / "fake_external_dp_results" / f"{invocation_id}.provider.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "draft_ready" if mode == "draft" else "model_ready",
                "mode": mode,
                "provider_id": "legacy.deepseek_dp_sidecar",
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    raw_path.write_text(json.dumps({"usage": {"total_tokens": 21}}, ensure_ascii=False), encoding="utf-8")
    provider_payload = {
        "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
        "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
        "provider_invocation_performed": True,
        "model_invocation_performed": True,
        "tool_invocation_performed": False,
        "result_path": str(result_path),
        "raw_response_ref": str(raw_path),
        "provider_invocation_ref": str(provider_ref),
        "evidence_refs": {"latest": str(runtime / "fake_external_dp_results" / "latest.json")},
        "named_blocker": "",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(result_path),
            "provider_invocation_ref": str(provider_ref),
            "provider_latest_ref": provider_payload["evidence_refs"]["latest"],
        },
    }


def test_schema_locks_phase1_draft_main_boundary() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1"
    )
    assert schema["properties"]["task_id"]["const"] == (
        "modular_dynamic_worker_pool_phase1_20260704"
    )
    assert schema["properties"]["mode_counts"]["properties"]["search"]["const"] == 0
    assert schema["properties"]["mode_counts"]["properties"]["provider_probe"]["const"] == 0
    assert schema["properties"]["trigger_binding"]["properties"]["hot_path"]["const"] == (
        "parallel_draft->merge->writer"
    )
    assert "must_do_10" in schema["required"]
    assert "wave_steps_8" in schema["required"]
    assert "spend_entry_count" in schema["required"]


def test_run_wave_stages_drafts_merges_and_records_spend(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.run_wave(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id=(
            "phase1-focused-test-wave-with-source-frontier-workerpool-global-"
            "closure-20260704-verify-wave-02-parallel_draft_batch_bind"
        ),
        target_width=8,
        write=True,
        dp_invoker=_fake_dp_invoker,
        record_meta_rsi=False,
        require_external_draft=False,
        assignment_dag_node_id="parallel_draft_batch_bind",
        workflow_id="phase1-focused-workflow",
        workflow_run_id="phase1-focused-run",
        next_wave_id="phase1-focused-next-wave",
    )

    assert payload["validation"]["passed"] is True, (
        [key for key, value in payload["validation"]["checks"].items() if not value],
        payload.get("artifact_acceptance_queue"),
    )
    assert payload["target_width"] == 8
    assert payload["actual_dispatched_width"] == 8
    assert all(
        brief["lane_id"].startswith("mdwp-") and len(brief["lane_id"]) < 40
        for brief in payload["worker_briefs"]
    )
    assert all(
        brief["source_wave_id"] == payload["wave_id"]
        for brief in payload["worker_briefs"]
    )
    assert payload["mode_counts"]["draft"] == 5
    assert payload["mode_counts"]["search"] == 0
    assert payload["mode_counts"]["provider_probe"] == 0
    assert payload["draft_count"] == 5
    assert payload["staged_count"] == 5
    assert payload["merged_count"] == 1
    assert payload["spend_entry_count"] == 8
    assert payload["eval_count"] == 1
    assert payload["audit_count"] == 1
    assert payload["provider_tier_usage"]
    assert payload["token_cost_spend"]["total_tokens"] > 0
    assert payload["token_cost_spend"]["metered_usage_entry_count"] == 8
    assert payload["token_cost_spend"]["estimated_usage_entry_count"] == 0
    assert payload["metered"] is True
    assert payload["source_entry"]["source_entry_root"].endswith("新系统")
    assert payload["source_entry"]["sampled_count"] > 0
    assert payload["user_latest_correction_digest"]["task_id"] == (
        "foreground_brain_dp_worker_pool_correction_20260704"
    )
    assert payload["foreground_brain_decision"]["owner"] == "foreground_codex_brain"
    assert payload["foreground_brain_decision"]["required_fields_present"] is True
    assert payload["foreground_brain_decision"]["333_alignment"][
        "333_is_owner_semantic_line"
    ] is True
    assert payload["foreground_brain_decision"]["worker_briefs_generated"][
        "draft_brief_count"
    ] > 0
    assert payload["foreground_brain_decision"]["draft_artifacts_consumed"]
    assert payload["foreground_brain_decision"]["merge_decision"]["adopted_draft_count"] > 0
    assert payload["foreground_brain_decision"]["next_wave_decision"]["should_continue"] is True
    assert payload["validation"]["checks"]["foreground_brain_decision_has_required_fields"] is True
    assert payload["validation"]["checks"]["source_entry_dynamic_read"] is True
    assert payload["validation"]["checks"]["assignment_dag_node_evidence_written"] is True
    assert payload["trigger_binding"]["status"] == "parallel_draft_to_merge_hot_path_bound"
    assert payload["watchdog_downgrade"]["status"] == "watchdog_downgraded_for_phase1_fast_path"
    assert payload["can_invoke_now"]["search_is_main_task"] is False
    assert payload["can_invoke_now"]["provider_probe_used_as_progress"] is False
    assert Path(payload["merge_artifact"]).is_file()
    merge_text = Path(payload["merge_artifact"]).read_text(encoding="utf-8")
    assert "这波推进了什么" in merge_text
    assert "采用的草稿" in merge_text
    assert "否决或暂缓的草稿" in merge_text
    assert "当前还差什么" in merge_text
    assert "下一波怎么派" in merge_text

    latest = runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
    readback = runtime / "readback" / "zh" / "modular_dynamic_worker_pool_phase1_20260704.md"
    trigger = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "trigger_binding"
        / "latest.json"
    )
    assert latest.is_file()
    assert trigger.is_file()
    assert Path(payload["evidence_refs"]["brain_provider_latest"]).is_file()
    assert Path(payload["evidence_refs"]["worker_provider_latest"]).is_file()
    assert Path(payload["evidence_refs"]["model_gateway_route_latest"]).is_file()
    assert Path(payload["evidence_refs"]["executor_adapter_latest"]).is_file()
    assert Path(payload["evidence_refs"]["worker_brief_latest"]).is_file()
    assert Path(payload["evidence_refs"]["dynamic_width_policy_latest"]).is_file()
    assert Path(payload["evidence_refs"]["width_blocker_latest"]).is_file()
    assert Path(payload["evidence_refs"]["parallel_draft_batch"]).is_file()
    assert Path(payload["evidence_refs"]["parallel_cost_ledger"]).is_file()
    assert Path(payload["evidence_refs"]["parallel_merge_review"]).is_file()
    assert Path(payload["evidence_refs"]["assignment_dag_node_evidence_latest"]).is_file()
    assert Path(payload["evidence_refs"]["assignment_dag_node_evidence_jsonl"]).is_file()
    assert payload["evidence_refs"]["runner"] == str(
        REPO_ROOT / "services" / "agent_runtime" / "modular_dynamic_worker_pool_phase1.py"
    )
    assert Path(payload["evidence_refs"]["worker_assignment"]).is_file()
    assert Path(payload["evidence_refs"]["foreground_brain_decision_latest"]).is_file()
    assert Path(payload["evidence_refs"]["cheap_worker_pool_capability_manifest"]).is_file()
    dag_evidence = payload["assignment_dag_node_evidence"]
    assert dag_evidence["status"] == "assignment_dag_node_evidence_written"
    assert dag_evidence["workflow_id"] == "phase1-focused-workflow"
    assert dag_evidence["workflow_run_id"] == "phase1-focused-run"
    assert dag_evidence["workflow_id_present"] is True
    assert dag_evidence["workflow_run_id_present"] is True
    assert dag_evidence["assignment_dag_node_id"] == "parallel_draft_batch_bind"
    assert dag_evidence["assignment_dag_node_found"] is True
    assert dag_evidence["current_active_node_id"] == "parallel_draft_batch_bind"
    assert dag_evidence["next_ready_node_id"] == "parallel_draft_batch_bind"
    assert dag_evidence["lane_count"] == payload["actual_completed_width"]
    assert dag_evidence["staged_count"] == payload["staged_count"]
    assert dag_evidence["merged_count"] == payload["merged_count"]
    assert dag_evidence["completion_claim_allowed"] is False
    assert dag_evidence["not_execution_controller"] is True
    assert dag_evidence["validation"]["checks"]["workflow_id_present"] is True
    assert dag_evidence["validation"]["checks"]["workflow_run_id_present"] is True
    assert all(
        lane["direct_repo_write_allowed"] is False
        for lane in dag_evidence["lane_bindings"]
    )
    assert all(
        lane["source_wave_id"] == payload["wave_id"]
        for lane in dag_evidence["lane_bindings"]
    )
    jsonl_path = Path(dag_evidence["jsonl_ref"])
    jsonl_event = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[-1])
    latest_event = json.loads(Path(dag_evidence["latest_ref"]).read_text(encoding="utf-8"))
    assert latest_event["jsonl_ref"] == dag_evidence["jsonl_ref"]
    assert latest_event["latest_ref"] == dag_evidence["latest_ref"]
    assert latest_event["node_latest_ref"] == dag_evidence["node_latest_ref"]
    assert jsonl_event["event_id"] == dag_evidence["event_id"]
    assert jsonl_event["record_digest_sha256"] == dag_evidence["record_digest_sha256"]
    assert jsonl_event["workflow_id"] == "phase1-focused-workflow"
    assert jsonl_event["assignment_dag_node_id"] == "parallel_draft_batch_bind"
    assert jsonl_event["completion_claim_allowed"] is False
    phase_boundary = payload["phase_boundary_named_blocker"]
    assert phase_boundary["named_blocker"] == "PHASE_BOUNDARY_NOT_READY_CONTINUE_REQUIRED"
    assert phase_boundary["workflow_id"] == "phase1-focused-workflow"
    assert phase_boundary["workflow_run_id"] == "phase1-focused-run"
    assert phase_boundary["phase_boundary_ready"] is False
    assert phase_boundary["next_wave_id"] == "phase1-focused-next-wave"
    assert phase_boundary["next_machine_action"] == (
        "consume queued phase1-focused-next-wave through existing Temporal workflow; "
        "then fan_in_staging_merge_spend"
    )
    assert phase_boundary["completion_claim_allowed"] is False
    assert Path(phase_boundary["latest_ref"]).is_file()
    assert Path(phase_boundary["jsonl_ref"]).is_file()
    assert payload["validation"]["checks"]["phase_boundary_named_blocker_written"] is True
    readback_text = readback.read_text(encoding="utf-8")
    assert "现在能 invoke 什么" in readback_text
    assert "Qwen/DP 都不是第二主脑" in readback_text
    assert "foreground_brain_decision" in readback_text


def test_assignment_dag_node_evidence_requires_temporal_workflow_binding(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.run_wave(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase1-missing-temporal-binding-test-wave",
        target_width=8,
        write=True,
        dp_invoker=_fake_dp_invoker,
        record_meta_rsi=False,
        require_external_draft=False,
        assignment_dag_node_id="parallel_draft_batch_bind",
    )

    dag_evidence = payload["assignment_dag_node_evidence"]
    assert dag_evidence["status"] == "assignment_dag_node_evidence_blocked"
    assert dag_evidence["named_blocker"] == (
        "ASSIGNMENT_DAG_NODE_TEMPORAL_EVIDENCE_NOT_READY"
    )
    assert "workflow_id_present" in dag_evidence["blocker_reasons"]
    assert "workflow_run_id_present" in dag_evidence["blocker_reasons"]
    assert dag_evidence["validation"]["checks"]["workflow_id_present"] is False
    assert dag_evidence["validation"]["checks"]["workflow_run_id_present"] is False
    assert payload["validation"]["checks"]["assignment_dag_node_evidence_written"] is False
    assert payload["validation"]["passed"] is False


def test_qwen_ready_routes_cheap_worker_lanes_first(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _write_qwen_ready_state(runtime)

    payload = module.run_wave(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase1-qwen-first-test-wave",
        target_width=8,
        write=True,
        dp_invoker=_fake_dp_invoker,
        qwen_invoker=_fake_qwen_invoker,
        record_meta_rsi=False,
        require_external_draft=True,
        workflow_id="phase1-qwen-first-workflow",
        workflow_run_id="phase1-qwen-first-run",
    )

    assert payload["validation"]["passed"] is True, [
        key for key, value in payload["validation"]["checks"].items() if not value
    ]
    assert payload["qwen_prepaid_cheap_worker_ready"] is True
    assert payload["qwen_prepaid_first_required_count"] == 6
    assert payload["qwen_prepaid_first_attempted_count"] == 6
    assert payload["qwen_prepaid_first_succeeded_count"] == 6
    assert payload["qwen_prepaid_draft_count"] == 5
    assert payload["true_dp_draft_count"] == 0
    assert payload["external_cheap_draft_count"] == 5
    assert payload["validation"]["checks"]["external_cheap_draft_observed"] is True
    assert payload["validation"]["checks"]["qwen_prepaid_first_attempted_when_required"] is True
    assert payload["validation"]["checks"]["qwen_prepaid_first_succeeded_or_allowed_fallback"] is True
    assert payload["qwen_first_applies_only_to"] == "cheap_worker_lane"
    assert "engineering_executor_lane" in payload["qwen_first_must_not_override"]
    draft_routes = [
        brief["provider_route"]["preferred_provider_id"]
        for brief in payload["worker_briefs"]
        if brief["mode"] == "draft"
    ]
    assert draft_routes == ["qwen_prepaid_cheap_worker"] * 5
    audit_routes = [
        brief["provider_route"]["preferred_provider_id"]
        for brief in payload["worker_briefs"]
        if brief["mode"] == "audit"
    ]
    assert audit_routes == ["legacy.deepseek_dp_sidecar"]


def test_qwen_transient_failure_falls_back_to_dp_same_wave(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _write_qwen_ready_state(runtime)

    payload = module.run_wave(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase1-qwen-timeout-fallback-test-wave",
        target_width=8,
        write=True,
        dp_invoker=_fake_external_dp_invoker,
        qwen_invoker=_fake_qwen_timeout_invoker,
        record_meta_rsi=False,
        require_external_draft=True,
        workflow_id="phase1-qwen-fallback-workflow",
        workflow_run_id="phase1-qwen-fallback-run",
    )

    assert module.classify_qwen_blocker("Request timed out.") == "QWEN_TRANSIENT_OR_ENDPOINT_FAILED"
    assert payload["validation"]["passed"] is True, [
        key for key, value in payload["validation"]["checks"].items() if not value
    ]
    assert payload["qwen_prepaid_first_required_count"] == 6
    assert payload["qwen_prepaid_first_attempted_count"] == 6
    assert payload["qwen_prepaid_first_succeeded_count"] == 0
    assert payload["qwen_fallback_allowed_count"] == 6
    assert payload["true_dp_draft_count"] == 5
    assert payload["external_cheap_draft_count"] == 5
    fallback_lanes = [
        lane for lane in payload["lane_results"] if lane.get("fallback_from_provider_id") == "qwen_prepaid_cheap_worker"
    ]
    assert len(fallback_lanes) == 6
    assert all(lane["fallback_reason"] == "QWEN_TRANSIENT_OR_ENDPOINT_FAILED" for lane in fallback_lanes)
    assert all(lane["qwen_attempt_ref"] for lane in fallback_lanes)


def test_run_enforced_while_freezes_global_default_for_three_metered_waves(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.run_enforced_while(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        chain_id="phase1-enforced-test-chain",
        base_wave_id="phase1-enforced-test",
        wave_count=3,
        target_width=8,
        write=True,
        dp_invoker=_fake_dp_invoker,
        require_external_draft=False,
        max_parallel_workers=3,
        assignment_dag_node_id="parallel_draft_batch_bind",
        workflow_id="phase1-enforced-workflow",
        workflow_run_id="phase1-enforced-run",
    )

    assert payload["validation"]["passed"] is True, [
        key for key, value in payload["validation"]["checks"].items() if not value
    ]
    assert payload["status"] == "global_default_runtime_enforced_while_self_chain_pop_ready"
    assert payload["runtime_enforced"] is True
    assert payload["runtime_enforced_scope"] == (
        "seed_cortex_global_default_modular_dynamic_worker_pool_phase1"
    )
    assert payload["enforced_wave_count"] == 3
    assert payload["metered_wave_count"] == 3
    assert payload["self_chain_wave_count"] == 3
    assert payload["while_pop"]["pop_ready"] is True
    assert payload["validation"]["checks"]["capability_gateway_phase1_runtime_enforced"] is True
    assert all(wave["runtime_enforced"] for wave in payload["waves"])
    assert all(wave["metered"] for wave in payload["waves"])
    phase1_latest = json.loads(
        (
            runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
        ).read_text(encoding="utf-8")
    )
    dag_evidence = phase1_latest["assignment_dag_node_evidence"]
    assert dag_evidence["workflow_id"] == "phase1-enforced-workflow"
    assert dag_evidence["workflow_run_id"] == "phase1-enforced-run"
    assert dag_evidence["assignment_dag_node_id"] == "parallel_draft_batch_bind"
    assert dag_evidence["validation"]["checks"]["workflow_id_present"] is True

    global_latest = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "global_default"
        / "latest.json"
    )
    while_latest = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "while_chain"
        / "latest.json"
    )
    gateway_latest = runtime / "state" / "capability_gateway" / "latest.json"
    readback = (
        runtime
        / "readback"
        / "zh"
        / "modular_dynamic_worker_pool_phase1_global_default_20260704.md"
    )
    assert global_latest.is_file()
    assert while_latest.is_file()
    assert gateway_latest.is_file()
    assert readback.is_file()
    readback_text = readback.read_text(encoding="utf-8")
    assert "three_waves_enforced: True" in readback_text
    assert "three_waves_metered: True" in readback_text
    assert "three_waves_self_chained: True" in readback_text


def test_service_workflow_bound_assignment_forces_enforced_single_wave(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1_module
    from xinao_seedlab.application.seed_cortex import build_default_service

    calls: dict[str, dict[str, Any]] = {}

    def fake_run_wave(**kwargs: Any) -> dict[str, Any]:
        calls["run_wave"] = kwargs
        return {
            "validation": {"passed": True},
            "runtime_enforced": kwargs.get("runtime_enforced"),
            "runtime_enforced_scope": kwargs.get("runtime_enforced_scope"),
        }

    def fake_run_enforced_while(**kwargs: Any) -> dict[str, Any]:
        calls["run_enforced_while"] = kwargs
        raise AssertionError("workflow-bound assignment must not take non-requested while chain")

    monkeypatch.setattr(phase1_module, "run_wave", fake_run_wave)
    monkeypatch.setattr(phase1_module, "run_enforced_while", fake_run_enforced_while)

    service = build_default_service(tmp_path / "runtime", repo_root=REPO_ROOT)
    payload = service.modular_dynamic_worker_pool_phase1(
        wave_id="wf-bound-phase1-wave",
        target_width=8,
        assignment_dag_node_id="parallel_draft_batch_bind",
        workflow_id="wf-bound-assignment",
        workflow_run_id="run-bound-assignment",
    )

    assert payload["runtime_enforced"] is True
    assert "run_enforced_while" not in calls
    run_wave_call = calls["run_wave"]
    assert run_wave_call["runtime_enforced"] is True
    assert run_wave_call["runtime_enforced_scope"] == phase1_module.GLOBAL_DEFAULT_ENFORCED_SCOPE
    assert run_wave_call["while_chain_id"] == "modular-dynamic-worker-pool-phase1-global-default"
    assert run_wave_call["while_wave_index"] == 1
    assert run_wave_call["while_wave_count"] == 1
    assert run_wave_call["workflow_id"] == "wf-bound-assignment"
    assert run_wave_call["workflow_run_id"] == "run-bound-assignment"


def test_module_cli_workflow_bound_assignment_forces_enforced_single_wave(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    calls: dict[str, dict[str, Any]] = {}

    def fake_run_wave(**kwargs: Any) -> dict[str, Any]:
        calls["run_wave"] = kwargs
        return {
            "validation": {"passed": True},
            "runtime_enforced": kwargs.get("runtime_enforced"),
            "runtime_enforced_scope": kwargs.get("runtime_enforced_scope"),
        }

    def fake_run_enforced_while(**kwargs: Any) -> dict[str, Any]:
        calls["run_enforced_while"] = kwargs
        raise AssertionError("workflow-bound CLI assignment must stay one-wave enforced")

    monkeypatch.setattr(module, "run_wave", fake_run_wave)
    monkeypatch.setattr(module, "run_enforced_while", fake_run_enforced_while)

    exit_code = module.main(
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--repo-root",
            str(REPO_ROOT),
            "--wave-id",
            "wf-bound-cli-wave",
            "--target-width",
            "8",
            "--assignment-dag-node-id",
            "parallel_draft_batch_bind",
            "--workflow-id",
            "wf-bound-cli-assignment",
            "--workflow-run-id",
            "run-bound-cli-assignment",
        ]
    )

    assert exit_code == 0
    assert "run_enforced_while" not in calls
    run_wave_call = calls["run_wave"]
    assert run_wave_call["runtime_enforced"] is True
    assert run_wave_call["runtime_enforced_scope"] == module.GLOBAL_DEFAULT_ENFORCED_SCOPE
    assert run_wave_call["while_chain_id"] == "modular-dynamic-worker-pool-phase1-global-default"
    assert run_wave_call["while_wave_index"] == 1
    assert run_wave_call["while_wave_count"] == 1
    assert run_wave_call["workflow_id"] == "wf-bound-cli-assignment"
    assert run_wave_call["workflow_run_id"] == "run-bound-cli-assignment"
