import importlib.util
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_max_capability_think_execute.py"
TASK_ID = "codexa_mature_intent_50d9a42afd8c42f18d33dfd794ac2844"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "codex_max_capability_think_execute", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "deepseek_dynamic_routing_policy" / "latest.json",
        {
            "schema_version": "xinao.codex_s.deepseek_dynamic_routing_policy.v1",
            "status": "deepseek_dynamic_routing_policy_custom_stopgap_only",
            "routing_policy": {
                "provider_backend": "custom_stopgap",
                "mature_router_bound": False,
                "adoption_state": "custom_stopgap_only",
                "default_intelligent_dispatch_allowed": False,
                "completion_gate_passed": False,
                "current_default_provider_width": 50,
                "named_blocker": "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND",
            },
            "model_policy": {
                "bulk_model_candidate": "deepseek-v4-flash",
                "quality_model_candidate": "deepseek-v4-pro",
            },
            "named_blocker": "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND",
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "deepseek_keypool_live_probe" / "latest.json",
        {
            "schema_version": "xinao.codex_s.deepseek_keypool_live_probe.v1",
            "status": "deepseek_keypool_live_probe_ready",
            "live_provider_invocation_performed": True,
            "certification": {
                "certified_provider_width": 50,
                "healthy_target_promoted": True,
                "high_target_promoted": True,
            },
            "observed": {
                "wave_count": 3,
                "total_attempted_request_count": 150,
                "total_successful_request_count": 150,
                "total_rate_limit_count": 0,
            },
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "deepseek_mature_router_binding" / "latest.json",
        {
            "schema_version": "xinao.codex_s.deepseek_mature_router_binding.v1",
            "status": "deepseek_mature_router_custom_stopgap_only",
            "route_policy": {
                "provider_backend": "custom_stopgap",
                "mature_router_bound": False,
                "adoption_state": "custom_stopgap_only",
                "default_intelligent_dispatch_allowed": False,
                "completion_gate_passed": False,
            },
            "named_blocker": "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND",
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "parallel_capacity" / "latest.json",
        {
            "schema_version": "xinao.parallel_capacity_snapshot.v1",
            "status": "fan_in_backlog_reduced_next_wave_allowed_scoped",
            "computed_fanout_ceiling": 6,
            "ceiling_scope": "current_codex_subagent_wave_only",
        },
    )
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "status": "worker_dispatch_ledger_verifier_passed_not_hooked",
            "adoption_state": "verifier_ready_but_not_hooked",
            "runtime_entrypoint_invocation": {
                "invoked_by": "temporal_codex_task_workflow.worker_dispatch_ledger_activity",
                "runtime_enforced": True,
                "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_write_activity",
                "not_execution_controller": True,
                "not_completion_gate": True,
            },
        },
    )


class _FakeDpPort:
    @staticmethod
    def invoke_dp_sidecar_execution_port(
        *,
        runtime_root: str | Path,
        task_id: str,
        request_id: str,
        invocation_id: str,
        episode_id: str,
        mode: str,
        objective: str,
        input_text: str,
        max_results: int = 5,
        write: bool = True,
    ) -> dict[str, Any]:
        runtime = Path(runtime_root)
        record = runtime / "state" / "dp_sidecar_execution_port" / "records" / f"{invocation_id}.json"
        provider = runtime / "state" / "dp_sidecar_execution_provider" / f"{invocation_id}.json"
        latest = runtime / "state" / "dp_sidecar_execution_provider" / "latest.json"
        raw = runtime / "state" / "dp_sidecar_execution_provider" / f"{invocation_id}.raw.json"
        if write:
            for path in (record, provider, latest, raw):
                _write_json(path, {"invocation_id": invocation_id, "mode": mode, "ok": True})
        if mode == "search":
            mode_status = "search_ready"
            selected_carrier = "deepseek.search_sidecar"
            model_invoked = False
            tool_invoked = True
        elif mode == "draft":
            mode_status = "draft_ready"
            selected_carrier = "legacy.deepseek_dp_sidecar"
            model_invoked = True
            tool_invoked = False
        elif mode == "eval":
            mode_status = "model_ready"
            selected_carrier = "litellm.model_gateway"
            model_invoked = True
            tool_invoked = False
        else:
            mode_status = "blocked"
            selected_carrier = "legacy.deepseek_dp_sidecar"
            model_invoked = False
            tool_invoked = False
        provider_payload = {
            "mode": mode,
            "mode_invocation_status": mode_status,
            "mode_dispatch_attempted": True,
            "provider_invocation_performed": mode_status != "blocked",
            "model_invocation_performed": model_invoked,
            "tool_invocation_performed": tool_invoked,
            "selected_carrier_provider_id": selected_carrier,
            "provider_invocation_ref": str(provider),
            "raw_response_ref": str(raw),
            "result_path": str(record),
        }
        return {
            "schema_version": "xinao.codex_s.dp_sidecar_execution_port_runner.v1",
            "status": "dp_sidecar_execution_port_runner_ready",
            "task_id": task_id,
            "request_id": request_id,
            "invocation_id": invocation_id,
            "episode_id": episode_id,
            "mode": mode,
            "provider_payload": provider_payload,
            "actual_dispatch_refs": {
                "provider_id": "legacy.deepseek_dp_sidecar",
                "selected_carrier_provider_id": selected_carrier,
                "mode": mode,
            },
            "evidence_refs": {
                "record_path": str(record),
                "latest": str(record),
                "provider_invocation_ref": str(provider),
                "provider_latest_ref": str(latest),
            },
            "created_at": "2026-07-03T00:00:00+00:00",
        }


def test_codex_max_capability_writes_task_assignment_and_nonprobe_poll_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts" / "hardmode").mkdir(parents=True)
    spec_name = "max_benefit_dynamic_loop_authority_20260702.v1.md"
    (repo / "CODEX_S_L0.md").write_text(spec_name + "\n", encoding="utf-8")
    (repo / "SEED_CORTEX_MUST_READ_FIRST.md").write_text(spec_name + "\n", encoding="utf-8")
    (repo / "scripts" / "hardmode" / "Invoke-CodexSSideAuditHook.ps1").write_text(
        spec_name + "\n",
        encoding="utf-8",
    )
    total_draft = tmp_path / "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt"
    total_draft.write_text(
        "\n".join(
            [
                "Serial is the exception; max-benefit frontier parallelism is the default.",
                "4. 当前工程的动态轮回循环定义",
                "SupervisorLoopWorkflow",
                "11. 关键反事故句",
                "report、PASS、draft、window end、consolidated response 都不是停止条件。",
                "readback 是 heartbeat，不是 final。",
                "13. 中文 readback",
                "14. 最终反保守修正版",
            ]
        ),
        encoding="utf-8",
    )
    intent_package = tmp_path / "intent.json"
    _write_json(
        intent_package,
        {
            "task_id": TASK_ID,
            "mission": "think execute",
            "primary_authority_path": str(total_draft),
            "primary_authority": {
                "path": str(total_draft),
                "parent_anchor": str(tmp_path / "root_total_draft_20260701.txt"),
            },
            "semantic_object": {
                "total_draft_anti_accident_quotes_cn": [
                    "不要把并行理解成一次性开工批次",
                    "report、PASS、draft、window end 都不是停止条件",
                ]
            },
        },
    )
    _seed_runtime(runtime)

    real_loader = module.load_sibling_module

    def fake_loader(name: str):
        if name == "dp_sidecar_execution_port":
            return _FakeDpPort
        return real_loader(name)

    monkeypatch.setattr(module, "load_sibling_module", fake_loader)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        task_id=TASK_ID,
        intent_package=intent_package,
        wave_id="codex-max-capability-test-wave",
        codex_subagents=[
            "019f25b6-d322-7381-a41b-91bfdfe31396:dp_router_audit:succeeded",
            "019f25b6-e66c-7912-ad27-84599487252b:worker_assignment_audit:succeeded",
        ],
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.max_capability_think_execute.v1"
    assert payload["validation"]["passed"] is True
    assignment = payload["WORKER_ASSIGNMENT"]
    assert assignment["schema_version"] == "xinao.worker_assignment.v2.dag"
    assert assignment["scope_level_target"] == "L3"
    assert assignment["primary_authority_rank"] == 0
    assert assignment["current_grok_package_authority_proxy"] is True
    assert assignment["primary_authority_path"] == str(total_draft)
    assert assignment["total_draft_section_refs"] == ["§4", "§11", "§13", "§14"]
    assert len(assignment["think_lanes"]) >= 3
    assert len(assignment["execute_lanes"]) == 2
    execute_modes = {
        lane["evidence_refs"]["requested_mode"]
        for lane in assignment["execute_lanes"]
        if lane["phase"] == "execute"
    }
    assert execute_modes == {"draft", "eval"}
    assert assignment["dependencies"]
    assert {
        (dependency["from"], dependency["to"], dependency["dependency_kind"])
        for dependency in assignment["dependencies"]
    } >= {
        (
            "codex-max-think-dp-search-01",
            "codex-max-execute-dp-draft-01",
            "think_context_before_execute",
        ),
        (
            "codex-max-execute-dp-draft-01",
            "codex-max-execute-dp-eval-01",
            "draft_before_eval",
        ),
    }
    assert Path(payload["output_paths"]["worker_assignment"]).is_file()
    assert Path(payload["output_paths"]["total_draft_spec"]).is_file()
    assert payload["total_draft_boot_spec"]["validation"]["passed"] is True
    assert payload["hook_binding"]["side_audit_hook_reads_total_draft_spec"] is True

    width = payload["width_decision"]
    assert width["width_source"] == (
        "deepseek_dynamic_routing_policy.routing_policy.current_default_provider_width"
    )
    assert width["observed_provider_width"] == 50
    assert width["parallel_capacity_ceiling"] == 6
    assert width["effective_execute_lane_count"] == 1
    assert width["hardcoded_fixed_width_used"] is False
    assert width["serial_exception"] is True

    assert payload["width_decision"]["default_nonprobe_mode"] == "draft"
    assert payload["summary"]["dp_nonprobe_succeeded_count"] == 3
    assert payload["summary"]["dp_nonprobe_attempted_count"] == 3
    assert payload["summary"]["dp_execute_draft_eval_succeeded_count"] == 2
    assert payload["summary"]["execute_search_invocation_count"] == 0
    assert payload["summary"]["execute_modes_observed"] == ["draft", "eval"]
    assert payload["summary"]["provider_probe_invocation_count"] == 0
    assert payload["summary"]["synthetic_succeeded_count"] == 0
    assert payload["summary"]["named_serial_exception_present"] is True
    wave_scope_id = hashlib.sha256("codex-max-capability-test-wave".encode("utf-8")).hexdigest()[:16]
    for invocation in payload["dp_invocations"]:
        assert "codex-max-capability-test-wave" in invocation["invocation_id"]
        assert wave_scope_id in invocation["provider_task_id"]
        assert len(invocation["provider_task_id"]) <= 128
        assert invocation["wave_scoped_provider_task_id"] is True
        assert invocation["wave_scope_id"] == wave_scope_id
    for lane in assignment["execute_lanes"]:
        assert lane["evidence_refs"]["wave_scoped_provider_task_id"] is True
        assert wave_scope_id in lane["evidence_refs"]["provider_task_id"]
        assert len(lane["evidence_refs"]["provider_task_id"]) <= 128
        assert lane["evidence_refs"]["wave_scope_id"] == wave_scope_id
    assert payload["hook_binding"]["adoption_state"] == "hooked_runtime_entrypoint"
    assert payload["worker_dispatch_ledger"]["source_kind"] == "worker_dispatch_ledger_poll"
    assert payload["fan_in"]["lane_results"]["source_kind"] == "worker_dispatch_ledger_poll"
    assert payload["fan_in"]["lane_results"]["fan_in_consumed_real_lane_results"] is True
    assert payload["artifact_acceptance"]["accepted_artifact_count"] == 1
    assert payload["continuity_envelope"]["accepted_artifact_count"] == 1
    assert payload["continuity_envelope"]["should_continue_loop"] is True
    assert payload["phase0_closure_dag"]["status"] == "ready"
    assert payload["phase0_closure_dag"]["ledger_adoption_state"] == "hooked_runtime_entrypoint"
    assert payload["phase0_closure_dag"]["should_continue_loop"] is True
    assert [node["id"] for node in payload["phase0_closure_dag"]["nodes"]] == [
        "WP_HOOK",
        "WP_THINK",
        "WP_EXECUTE",
        "WP_READBACK",
        "WP_BOOT_STABLE",
        "WP_VERIFY",
    ]

    readback = Path(payload["output_paths"]["runtime_readback_zh"]).read_text(encoding="utf-8")
    assert "思考派了什么" in readback
    assert "L 层与总稿" in readback
    assert "执行几路" in readback
    assert "WP_HOOK -> THINK -> EXECUTE -> READBACK -> VERIFY" in readback
    assert "现在能干什么" in readback
    assert "写了什么" in readback
    assert "execute 是 draft/eval" in readback
    assert "search 只在 think" in readback
    assert "provider_probe invoked：0" in readback
    assert "execute search invoked：0" in readback
    assert "should_continue_loop：True" in readback
