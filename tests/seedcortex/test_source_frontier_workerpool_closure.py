import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_frontier_workerpool_closure.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_source_frontier_workerpool_closure.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_frontier_workerpool_closure", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path, *, wave_id: str = "closure-test-wave") -> None:
    bridge_root = runtime / "state" / "source_frontier_workerbrief_bridge"
    briefs = [
        {
            "worker_brief_id": f"{wave_id}:source-bound:01:01",
            "original_worker_brief_id": f"{wave_id}:brief:01:cheap_draft",
            "source_batch_id": "source-batch-1",
            "frontier_batch_id": "source-batch-1",
            "claim_card_id": "claim-source-1",
            "claim_card_ref": "local:claim-source-1",
            "source_package_ref": {"source_package_digest_sha256": "abc123"},
            "mapping_key": "mapping-1",
            "objective": "Draft source-bound worker output.",
            "expected_artifact": "draft_ref",
            "provider_policy": {"provider_scheduler_ref": "provider-scheduler"},
            "fan_in_target": {"worker_output_must_enter_staging": True},
            "aaq_target": {"claim_card_requires_source_ledger": True},
            "next_frontier_policy": {"completion_claim_allowed": False},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
        {
            "worker_brief_id": f"{wave_id}:source-bound:01:02",
            "original_worker_brief_id": f"{wave_id}:brief:02:merge_accept",
            "source_batch_id": "source-batch-1",
            "frontier_batch_id": "source-batch-1",
            "claim_card_id": "claim-source-1",
            "claim_card_ref": "local:claim-source-1",
            "source_package_ref": {"source_package_digest_sha256": "abc123"},
            "mapping_key": "mapping-2",
            "objective": "Cross-check source-bound worker output.",
            "expected_artifact": "merge_ref",
            "provider_policy": {"provider_scheduler_ref": "provider-scheduler"},
            "fan_in_target": {"worker_output_must_enter_staging": True},
            "aaq_target": {"claim_card_requires_source_ledger": True},
            "next_frontier_policy": {"completion_claim_allowed": False},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    ]
    _write_json(
        bridge_root / "worker_brief_queue_latest.json",
        {
            "schema_version": "xinao.codex_s.worker_brief_queue.source_bound.v1",
            "status": "source_bound_worker_brief_queue_ready",
            "wave_id": wave_id,
            "canonical_worker_brief_queue_ref": str(runtime / "state" / "allocation_plan" / "worker_brief_queue_latest.json"),
            "brief_count": len(briefs),
            "briefs": briefs,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        bridge_root / "waves" / f"{wave_id}.json",
        {
            "schema_version": "xinao.codex_s.source_frontier_workerbrief_bridge.v1",
            "status": "source_frontier_workerbrief_bridge_ready",
            "wave_id": wave_id,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "allocation_plan" / "latest.json",
        {
            "schema_version": "xinao.codex_s.allocation_plan.v1",
            "status": "allocation_plan_ready",
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "allocation_plan" / "worker_brief_queue_latest.json",
        {
            "schema_version": "xinao.codex_s.worker_brief_queue.v1",
            "status": "worker_brief_queue_ready",
            "brief_count": len(briefs),
            "briefs": briefs,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    provider_root = runtime / "state" / "codex_native_provider_scheduler_phase4_20260704"
    _write_json(
        provider_root / "latest.json",
        {
            "schema_version": "xinao.codex_s.codex_native_provider_scheduler_phase4.v1",
            "status": "codex_native_provider_scheduler_ready",
            "qwen_prepaid_cheap_worker_default_first": True,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        provider_root / "qwen_prepaid_policy" / "latest.json",
        {
            "status": "qwen_prepaid_policy_ready",
            "models": {"cheap_default_candidates": ["qwen3.6-flash"]},
            "outputs_to_staging_only": True,
        },
    )
    _write_json(
        provider_root / "qwen_invocation" / "latest.json",
        {"status": "qwen_dashscope_canary_ready", "succeeded": True, "selected_model": "qwen3.6-flash"},
    )


def _fake_provider(provider_id: str, status: str):
    def invoke(*, runtime_root, invocation_id, mode, objective, input_text, write=True, **kwargs):
        runtime = Path(runtime_root)
        root = runtime / "state" / "fake_provider" / provider_id
        artifact = root / "artifacts" / f"{invocation_id}.{mode}.json"
        record = root / "records" / f"{invocation_id}.json"
        raw = root / "raw" / f"{invocation_id}.json"
        if write:
            _write_json(artifact, {"provider_id": provider_id, "mode": mode, "content": input_text[:200]})
            _write_json(raw, {"usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}})
        payload = {
            "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
            "selected_carrier_provider_id": provider_id,
            "provider_invocation_performed": True,
            "model_invocation_performed": True,
            "tool_invocation_performed": False,
            "result_path": str(artifact),
            "raw_response_ref": str(raw),
            "provider_invocation_ref": str(record),
            "evidence_refs": {"latest": str(root / "latest.json"), "record_path": str(record)},
            "named_blocker": "",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        runner = {"provider_payload": payload, "actual_dispatch_refs": {"result_path": str(artifact), "provider_invocation_ref": str(record)}}
        if write:
            _write_json(record, runner)
            _write_json(root / "latest.json", runner)
        return runner
    return invoke


def _blocked_provider(blocker: str):
    def invoke(*, runtime_root, invocation_id, mode, write=True, **kwargs):
        runtime = Path(runtime_root)
        record = runtime / "state" / "fake_provider_blocked" / "records" / f"{invocation_id}.json"
        payload = {
            "mode_invocation_status": "blocked",
            "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "tool_invocation_performed": False,
            "result_path": "",
            "raw_response_ref": "",
            "provider_invocation_ref": str(record),
            "evidence_refs": {"record_path": str(record)},
            "named_blocker": blocker,
        }
        runner = {"provider_payload": payload, "actual_dispatch_refs": {"provider_invocation_ref": str(record)}}
        if write:
            _write_json(record, runner)
        return runner
    return invoke


def test_closure_executes_source_bound_workerbriefs_through_worker_pool(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    wave_id = "closure-test-wave"
    _seed_runtime(runtime, wave_id=wave_id)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id=wave_id,
        parent_wave_id=wave_id,
        workflow_id="closure-test-workflow",
        qwen_invoker=_fake_provider("qwen_prepaid_cheap_worker", "model_ready"),
        dp_invoker=_fake_provider("legacy.deepseek_dp_sidecar", "model_ready"),
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_frontier_workerpool_closure.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1"
    assert payload["status"] == "source_frontier_workerpool_closure_ready"
    assert payload["source_bound_worker_brief_count"] == 2
    assert len(payload["lane_results"]) == 2
    providers = {item["selected_carrier_provider_id"] for item in payload["lane_results"]}
    assert "qwen_prepaid_cheap_worker" in providers
    assert "legacy.deepseek_dp_sidecar" in providers
    assert payload["staging"]["staged_count"] == 2
    assert payload["merge"]["status"] == "source_bound_merge_ready"
    assert payload["fan_in"]["validation"]["passed"] is True
    assert payload["artifact_acceptance_queue"]["accepted_artifact_count"] > 0
    assert payload["next_frontier"]["validation"]["passed"] is True
    assert payload["repair_plan"]["repair_required"] is False
    assert payload["validation"]["passed"] is True
    chain = payload["acceptance_chains"][0]
    for field in (
        "source_batch_id",
        "worker_brief_id",
        "allocation_plan_ref",
        "provider_scheduler_ref",
        "provider_invocation_ref",
        "staging_ref",
        "merge_ref",
        "fan_in_ref",
        "aaq_ref",
        "next_frontier_ref",
    ):
        assert chain[field]
    assert Path(payload["output_paths"]["worker_dispatch_ledger_wave"]).is_file()
    assert Path(payload["output_paths"]["worker_dispatch_ledger_activity"]).is_file()


def test_closure_lane_ids_stay_short_for_long_temporal_wave_ids(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    wave_id = "codex-s-durable-default-chain-supervisor-workerfix-sroute-smoke-r2-20260704-live-000001-wave-01-ingress"
    _seed_runtime(runtime, wave_id=wave_id)
    refs = module.runtime_refs(runtime, parent_wave_id=wave_id)
    source_queue = json.loads(
        (runtime / "state" / "source_frontier_workerbrief_bridge" / "worker_brief_queue_latest.json").read_text(
            encoding="utf-8"
        )
    )

    briefs, _ = module.executable_worker_briefs(
        runtime=runtime,
        repo=tmp_path / "repo",
        wave_id=wave_id,
        parent_wave_id=wave_id,
        source_bound_queue=source_queue,
        refs=refs,
    )

    assert briefs
    assert all(brief["lane_id"].startswith("sfwc-") for brief in briefs)
    assert all(len(brief["lane_id"]) <= 24 for brief in briefs)


def test_validation_accepts_role_suffix_wave_with_base_wave_refs(tmp_path: Path) -> None:
    module = _load_module()
    base_wave = "temporal-wave-01-ingress"
    role_wave = f"{base_wave}-source-frontier-workerpool-closure"
    ref = f"D:\\XINAO_RESEARCH_RUNTIME\\state\\source_frontier_workerpool_closure\\waves\\{base_wave}-abc123\\staging.json"
    payload = {
        "wave_id": role_wave,
        "source_bound_worker_brief_count": 2,
        "lane_results": [
            {
                "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
                "provider_route": {"preferred_provider_id": "qwen_prepaid_cheap_worker"},
            },
            {
                "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
                "provider_route": {"preferred_provider_id": "legacy.deepseek_dp_sidecar"},
            },
        ],
        "input_refs": {"provider_scheduler": "provider-scheduler"},
        "staging": {"status": "source_bound_staging_ready"},
        "merge": {"status": "source_bound_merge_ready"},
        "fan_in": {"validation": {"passed": True}},
        "artifact_acceptance_queue": {"accepted_artifact_count": 2},
        "next_frontier": {"validation": {"passed": True}},
        "acceptance_chains": [
            {
                "source_batch_id": "source-batch",
                "worker_brief_id": "worker-brief",
                "allocation_plan_ref": "allocation",
                "provider_scheduler_ref": "provider-scheduler",
                "provider_invocation_ref": "provider-invocation",
                "staging_ref": ref,
                "merge_ref": ref.replace("staging", "merge"),
                "fan_in_ref": ref.replace("staging", "fan_in"),
                "aaq_ref": ref.replace("staging", "aaq"),
                "next_frontier_ref": ref.replace("staging", "next_frontier"),
            }
        ],
        "repair_plan": {"repair_required": False},
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }

    validation = module.build_validation(payload)

    assert validation["checks"]["same_wave_refs"] is True
    assert validation["passed"] is True


def test_closure_generates_repair_plan_for_fixable_provider_failure(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    wave_id = "closure-repair-wave"
    _seed_runtime(runtime, wave_id=wave_id)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id=wave_id,
        parent_wave_id=wave_id,
        workflow_id="closure-test-workflow",
        qwen_invoker=_blocked_provider("QWEN_AUTH_FAILED"),
        dp_invoker=_blocked_provider("DP_PROVIDER_NOT_READY"),
        write=False,
    )

    assert payload["status"] == "source_frontier_workerpool_closure_repair_required"
    assert payload["repair_plan"]["repair_required"] is True
    assert payload["repair_plan"]["fixable_repair_count"] > 0
    assert payload["repair_plan"]["dispatch_to"] == "RootIntentLoop / S Default Dynamic Loop"
    assert payload["repair_plan"]["continue_main_loop"] is True
    assert payload["validation"]["passed"] is False
    assert payload["completion_claim_allowed"] is False


def test_schema_contract_preserves_closure_chain_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "xinao.codex_s.source_frontier_workerpool_closure.v1"
    assert schema["properties"]["sentinel"]["const"] == "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1"
    required_chain = schema["properties"]["acceptance_chains"]["items"]["required"]
    assert "source_batch_id" in required_chain
    assert "worker_brief_id" in required_chain
    assert "provider_invocation_ref" in required_chain
    assert "next_frontier_ref" in required_chain
    assert schema["properties"]["latest_alias_is_not_proof"]["const"] is True
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
