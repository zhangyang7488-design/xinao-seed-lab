import importlib.util
import hashlib
import json
import re
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


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip(".-")
    if len(cleaned) <= 120:
        return cleaned or "wave"
    digest = hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{cleaned[:103].strip('.-') or 'wave'}-{digest}"


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
    bridge_wave_payload = {
        "schema_version": "xinao.codex_s.source_frontier_workerbrief_bridge.v1",
        "status": "source_frontier_workerbrief_bridge_ready",
        "wave_id": wave_id,
        "source_item_count": 1,
        "worker_brief_binding_count": len(briefs),
        "worker_brief_bindings": briefs,
        "validation": {"passed": True},
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }
    _write_json(bridge_root / "waves" / f"{wave_id}.json", bridge_wave_payload)
    if _safe_stem(wave_id) != wave_id:
        _write_json(bridge_root / "waves" / f"{_safe_stem(wave_id)}.json", bridge_wave_payload)
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


def _local_stub_provider(provider_id: str = "seed_cortex.local_draft_artifact_provider"):
    def invoke(*, runtime_root, invocation_id, mode, input_text="", write=True, **kwargs):
        runtime = Path(runtime_root)
        root = runtime / "state" / "fake_local_stub" / provider_id
        artifact = root / "artifacts" / f"{invocation_id}.{mode}.json"
        record = root / "records" / f"{invocation_id}.json"
        if write:
            _write_json(artifact, {"provider_id": provider_id, "mode": mode, "content": input_text[:200]})
        payload = {
            "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
            "selected_carrier_provider_id": provider_id,
            "provider_invocation_performed": True,
            "model_invocation_performed": False,
            "tool_invocation_performed": True,
            "result_path": str(artifact),
            "raw_response_ref": "",
            "provider_invocation_ref": str(record),
            "evidence_refs": {"latest": str(root / "latest.json"), "record_path": str(record)},
            "named_blocker": "",
        }
        runner = {
            "provider_payload": payload,
            "actual_dispatch_refs": {"result_path": str(artifact), "provider_invocation_ref": str(record)},
        }
        if write:
            _write_json(record, runner)
            _write_json(root / "latest.json", runner)
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
        workflow_run_id="closure-test-run",
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
    assert payload["provider_materialization"]["qwen_or_deepseek_real_model_invoked"] is True
    assert payload["provider_materialization"]["qwen_real_model_invoked"] is True
    assert payload["provider_materialization"]["deepseek_dp_real_model_invoked"] is True
    assert payload["provider_materialization"]["qwen_and_deepseek_real_model_invoked"] is True
    assert payload["provider_materialization"]["external_draft_model_invoked"] is True
    assert payload["provider_materialization"]["tool_diagnostic_count"] == 0
    assert payload["independent_eval_payload"]["status"] == "independent_eval_passed"
    assert payload["independent_eval_payload"]["eval_is_health_signal_only"] is True
    assert payload["independent_eval_payload"]["does_not_zero_artifact_delta"] is True
    assert payload["validation"]["checks"]["real_qwen_or_deepseek_model_invoked"] is True
    assert payload["validation"]["checks"]["real_qwen_model_invoked"] is True
    assert payload["validation"]["checks"]["real_deepseek_dp_model_invoked"] is True
    assert payload["validation"]["checks"]["real_qwen_and_deepseek_model_invoked"] is True
    assert payload["validation"]["checks"]["independent_eval_payload_present"] is True
    assert payload["validation"]["checks"]["independent_eval_is_health_signal_only"] is True
    assert payload["repair_plan"]["repair_required"] is False
    assert payload["validation"]["passed"] is True
    assert payload["workflow_run_id"] == "closure-test-run"
    assert payload["primary_source_batch_id"] == "source-batch-1"
    assert payload["source_batch_ids"] == ["source-batch-1"]
    assert payload["source_bound_worker_brief_queue_ref"].endswith(f"{wave_id}.json")
    assert payload["source_bound_worker_brief_queue_wave_id"] == wave_id
    assert payload["source_bound_worker_brief_queue_latest_fallback_used"] is False
    assert payload["worker_brief_ids"]
    assert payload["same_wave_output_refs"]["staging_ref"] == payload["output_paths"]["staging"]
    assert payload["same_wave_output_refs"]["allocation_plan_ref"] == payload["output_paths"]["allocation_plan_snapshot"]
    assert payload["same_wave_output_refs"]["provider_scheduler_ref"] == payload["output_paths"]["provider_scheduler_snapshot"]
    chain = payload["acceptance_chains"][0]
    for field in (
        "wave_id",
        "workflow_id",
        "workflow_run_id",
        "evidence_digest_sha256",
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
    assert chain["workflow_id"] == "closure-test-workflow"
    assert chain["workflow_run_id"] == "closure-test-run"
    assert chain["evidence_digest_sha256"] == payload["evidence_digest_sha256"]
    assert chain["allocation_plan_ref"] == payload["output_paths"]["allocation_plan_snapshot"]
    assert chain["provider_scheduler_ref"] == payload["output_paths"]["provider_scheduler_snapshot"]
    assert Path(chain["allocation_plan_ref"]).is_file()
    assert Path(chain["provider_scheduler_ref"]).is_file()

    allocation_snapshot = json.loads(Path(chain["allocation_plan_ref"]).read_text(encoding="utf-8"))
    provider_snapshot = json.loads(Path(chain["provider_scheduler_ref"]).read_text(encoding="utf-8"))
    for snapshot in (allocation_snapshot, provider_snapshot):
        assert snapshot["wave_id"] == wave_id
        assert snapshot["parent_wave_id"] == wave_id
        assert snapshot["workflow_id"] == "closure-test-workflow"
        assert snapshot["workflow_run_id"] == "closure-test-run"
        assert snapshot["evidence_digest_sha256"] == payload["evidence_digest_sha256"]
        assert snapshot["snapshot_ref"]
        assert snapshot["source_ref"].endswith("latest.json")
        assert snapshot["source_digest_sha256"]
        assert snapshot["latest_alias_is_not_proof"] is True

    wave_specific_outputs = {
        "staging": "staging",
        "merge": "merge",
        "fan_in": "fan_in",
        "artifact_acceptance_queue": "aaq",
        "next_frontier": "next_frontier",
    }
    for payload_key, output_key in wave_specific_outputs.items():
        artifact = payload[payload_key]
        written = json.loads(Path(payload["output_paths"][output_key]).read_text(encoding="utf-8"))
        for candidate in (artifact, written):
            assert candidate["workflow_id"] == "closure-test-workflow"
            assert candidate["workflow_run_id"] == "closure-test-run"
            assert candidate["wave_id"] == wave_id
            assert candidate["parent_wave_id"] == wave_id
            assert candidate["primary_source_batch_id"] == "source-batch-1"
            assert candidate["source_batch_ids"] == ["source-batch-1"]
            assert candidate["primary_worker_brief_id"]
            assert candidate["worker_brief_ids"]
            assert candidate["evidence_digest_sha256"] == payload["evidence_digest_sha256"]
            assert candidate["same_wave_output_refs"]["staging_ref"] == payload["output_paths"]["staging"]
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


def test_closure_validates_same_wave_refs_for_truncated_long_wave_id(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    wave_id = (
        "codex-s-durable-default-chain-supervisor-20260704-night-sroute-fixed-live-000144-"
        "wave-01-ingress-source-frontier-workerpool-closure-repair-50fdfb8"
    )
    parent_wave_id = (
        "codex-s-durable-default-chain-supervisor-20260704-night-sroute-fixed-live-000144-"
        "wave-01-ingress-source-frontier-workerbrief-bridge"
    )
    _seed_runtime(runtime, wave_id=parent_wave_id)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        workflow_id="closure-long-workflow",
        workflow_run_id="closure-long-run",
        qwen_invoker=_fake_provider("qwen_prepaid_cheap_worker", "model_ready"),
        dp_invoker=_fake_provider("legacy.deepseek_dp_sidecar", "model_ready"),
        write=True,
    )

    assert payload["validation"]["checks"]["same_wave_refs"] is True
    assert payload["validation"]["checks"]["wave_specific_products_bound"] is True
    assert payload["validation"]["passed"] is True


def test_closure_uses_parent_bridge_wave_when_latest_queue_is_stale(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    parent_wave_id = "closure-parent-bridge-wave"
    _seed_runtime(runtime, wave_id=parent_wave_id)
    stale_queue = runtime / "state" / "source_frontier_workerbrief_bridge" / "worker_brief_queue_latest.json"
    stale_payload = json.loads(stale_queue.read_text(encoding="utf-8"))
    stale_payload["wave_id"] = "stale-latest-wave"
    for brief in stale_payload["briefs"]:
        brief["source_batch_id"] = "stale-source-batch"
        brief["worker_brief_id"] = f"stale-latest-wave:{brief['mapping_key']}"
    _write_json(stale_queue, stale_payload)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id="closure-child-wave",
        parent_wave_id=parent_wave_id,
        workflow_id="closure-test-workflow",
        qwen_invoker=_fake_provider("qwen_prepaid_cheap_worker", "model_ready"),
        dp_invoker=_fake_provider("legacy.deepseek_dp_sidecar", "model_ready"),
        write=False,
    )

    assert payload["validation"]["checks"]["source_bound_queue_parent_wave_bound"] is True
    assert payload["validation"]["checks"]["source_bound_queue_no_latest_fallback"] is True
    assert payload["source_batch_ids"] == ["source-batch-1"]
    assert all(
        result["worker_brief_id"].startswith(parent_wave_id)
        for result in payload["lane_results"]
    )
    assert "stale-source-batch" not in payload["source_batch_ids"]


def test_validation_accepts_role_suffix_wave_with_base_wave_refs(tmp_path: Path) -> None:
    module = _load_module()
    base_wave = "temporal-wave-01-ingress"
    role_wave = f"{base_wave}-source-frontier-workerpool-closure"
    ref = f"D:\\XINAO_RESEARCH_RUNTIME\\state\\source_frontier_workerpool_closure\\waves\\{base_wave}-abc123\\staging.json"
    allocation_ref = ref.replace("staging", "allocation_plan_snapshot")
    provider_scheduler_ref = ref.replace("staging", "provider_scheduler_snapshot")
    product_context = {
        "wave_id": role_wave,
        "workflow_id": "temporal-workflow",
        "workflow_run_id": "temporal-run",
        "evidence_digest_sha256": "digest-123",
        "source_batch_ids": ["source-batch"],
        "worker_brief_ids": ["worker-brief"],
        "primary_source_batch_id": "source-batch",
        "primary_worker_brief_id": "worker-brief",
    }
    payload = {
        "wave_id": role_wave,
        "parent_wave_id": base_wave,
        "workflow_id": "temporal-workflow",
        "workflow_run_id": "temporal-run",
        "evidence_digest_sha256": "digest-123",
        "source_batch_ids": ["source-batch"],
        "source_bound_worker_brief_queue_wave_id": base_wave,
        "source_bound_worker_brief_queue_latest_fallback_used": False,
        "source_bound_worker_brief_queue_source_batch_ids": ["source-batch"],
        "source_bound_worker_brief_count": 2,
        "lane_results": [
            {
                "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
                "status": "succeeded",
                "mode": "draft",
                "provider_invocation_performed": True,
                "model_invocation_performed": True,
                "provider_invocation_ref": "qwen-provider-invocation",
                "qwen_prepaid_invocation": True,
                "provider_route": {"preferred_provider_id": "qwen_prepaid_cheap_worker"},
            },
            {
                "selected_carrier_provider_id": "legacy.deepseek_dp_sidecar",
                "status": "succeeded",
                "mode": "contradiction",
                "provider_invocation_performed": True,
                "model_invocation_performed": True,
                "provider_invocation_ref": "dp-provider-invocation",
                "deepseek_dp_invocation": True,
                "provider_route": {"preferred_provider_id": "legacy.deepseek_dp_sidecar"},
            },
        ],
        "phase1_spend_ledger": {
            "entries": [
                {
                    "selected_carrier_provider_id": "qwen_prepaid_cheap_worker",
                    "qwen_prepaid_invocation": True,
                }
            ],
            "token_cost_spend": {"provider_usage_entry_count": 1},
        },
        "input_refs": {"provider_scheduler": "provider-scheduler"},
        "input_snapshots": {
            "allocation_plan": {
                "wave_id": role_wave,
                "workflow_id": "temporal-workflow",
                "evidence_digest_sha256": "digest-123",
                "source_ref": "allocation-latest",
                "snapshot_ref": allocation_ref,
                "source_digest_sha256": "allocation-digest",
                "latest_alias_is_not_proof": True,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
            "provider_scheduler": {
                "wave_id": role_wave,
                "workflow_id": "temporal-workflow",
                "evidence_digest_sha256": "digest-123",
                "source_ref": "provider-scheduler-latest",
                "snapshot_ref": provider_scheduler_ref,
                "source_digest_sha256": "provider-scheduler-digest",
                "latest_alias_is_not_proof": True,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        },
        "output_paths": {
            "allocation_plan_snapshot": allocation_ref,
            "provider_scheduler_snapshot": provider_scheduler_ref,
            "staging": ref,
            "merge": ref.replace("staging", "merge"),
            "fan_in": ref.replace("staging", "fan_in"),
            "aaq": ref.replace("staging", "aaq"),
            "next_frontier": ref.replace("staging", "next_frontier"),
        },
        "staging": {**product_context, "status": "source_bound_staging_ready", "real_external_staged_count": 2},
        "merge": {**product_context, "status": "source_bound_merge_ready"},
        "fan_in": {**product_context, "validation": {"passed": True}},
        "artifact_acceptance_queue": {**product_context, "accepted_artifact_count": 2},
        "next_frontier": {**product_context, "validation": {"passed": True}},
        "acceptance_chains": [
            {
                "wave_id": role_wave,
                "workflow_id": "temporal-workflow",
                "workflow_run_id": "temporal-run",
                "evidence_digest_sha256": "digest-123",
                "source_batch_id": "source-batch",
                "worker_brief_id": "worker-brief",
                "allocation_plan_ref": allocation_ref,
                "provider_scheduler_ref": provider_scheduler_ref,
                "provider_invocation_ref": "provider-invocation",
                "staging_ref": ref,
                "merge_ref": ref.replace("staging", "merge"),
                "fan_in_ref": ref.replace("staging", "fan_in"),
                "aaq_ref": ref.replace("staging", "aaq"),
                "next_frontier_ref": ref.replace("staging", "next_frontier"),
            }
        ],
        "repair_plan": {"repair_required": False},
        "independent_eval_payload": {
            **product_context,
            "schema_version": "xinao.codex_s.source_frontier_workerpool_closure.independent_eval.v1",
            "status": "independent_eval_passed",
            "passed": True,
            "eval_is_health_signal_only": True,
            "does_not_zero_artifact_delta": True,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
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


def test_closure_rejects_local_stub_as_workerpool_completion(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    wave_id = "closure-local-stub-wave"
    _seed_runtime(runtime, wave_id=wave_id)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id=wave_id,
        parent_wave_id=wave_id,
        workflow_id="closure-test-workflow",
        qwen_invoker=_local_stub_provider(),
        dp_invoker=_local_stub_provider("seed_cortex.local_eval_artifact_provider"),
        write=True,
    )

    assert payload["status"] == "source_frontier_workerpool_closure_repair_required"
    assert payload["provider_materialization"]["qwen_or_deepseek_real_model_invoked"] is False
    assert payload["provider_materialization"]["local_stub_as_completion_attempted"] is True
    assert payload["fan_in"]["accepted_edge_count"] == 0
    assert payload["artifact_acceptance_queue"]["accepted_artifact_count"] == 0
    assert payload["next_frontier"]["should_continue_loop"] is False
    assert payload["validation"]["checks"]["real_qwen_or_deepseek_model_invoked"] is False
    assert payload["validation"]["checks"]["real_qwen_model_invoked"] is False
    assert payload["validation"]["checks"]["real_deepseek_dp_model_invoked"] is False
    assert payload["validation"]["passed"] is False
    assert any(
        item["blocker_name"] == "REAL_QWEN_OR_DEEPSEEK_MODEL_INVOCATION_MISSING"
        for item in payload["repair_plan"]["repair_items"]
    )
    assert any(
        item["blocker_name"] == "REAL_DEEPSEEK_DP_MODEL_INVOCATION_MISSING"
        for item in payload["repair_plan"]["repair_items"]
    )


def test_closure_rejects_qwen_only_without_real_deepseek_dp(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    wave_id = "closure-qwen-only-wave"
    _seed_runtime(runtime, wave_id=wave_id)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id=wave_id,
        parent_wave_id=wave_id,
        workflow_id="closure-test-workflow",
        qwen_invoker=_fake_provider("qwen_prepaid_cheap_worker", "model_ready"),
        dp_invoker=_local_stub_provider("seed_cortex.local_eval_artifact_provider"),
        write=True,
    )

    assert payload["status"] == "source_frontier_workerpool_closure_repair_required"
    assert payload["provider_materialization"]["qwen_real_model_invocation_count"] == 1
    assert payload["provider_materialization"]["deepseek_dp_real_model_invocation_count"] == 0
    assert payload["provider_materialization"]["qwen_and_deepseek_real_model_invoked"] is False
    assert payload["validation"]["checks"]["real_qwen_model_invoked"] is True
    assert payload["validation"]["checks"]["real_deepseek_dp_model_invoked"] is False
    assert payload["validation"]["checks"]["real_qwen_and_deepseek_model_invoked"] is False
    assert payload["next_frontier"]["should_continue_loop"] is False
    assert payload["validation"]["passed"] is False
    assert any(
        item["blocker_name"] == "REAL_DEEPSEEK_DP_MODEL_INVOCATION_MISSING"
        for item in payload["repair_plan"]["repair_items"]
    )


def test_next_frontier_requires_real_artifact_delta_before_continue(tmp_path: Path) -> None:
    module = _load_module()
    output = {"next_frontier": str(tmp_path / "next_frontier.json")}

    payload = module.build_next_frontier(
        wave_id="closure-gate-wave",
        parent_wave_id="parent-wave",
        aaq={"accepted_artifact_count": 1},
        merge={"status": "source_bound_merge_blocked", "merged_count": 0, "merge_artifact": ""},
        staging={"staged_count": 1},
        output=output,
        evidence_context={"source_batch_ids": ["source-batch-1"]},
    )

    assert payload["aaq_accepted_artifact_count"] == 1
    assert payload["artifact_delta_count"] == 0
    assert payload["should_continue_loop"] is False
    assert payload["next_decision"] == "drain_fan_in_or_replan"
    assert payload["continue_gate"]["artifact_delta_count_positive"] is False
    assert payload["validation"]["passed"] is True


def test_independent_eval_rejects_tool_diagnostic_only(tmp_path: Path) -> None:
    module = _load_module()
    payload = module.build_independent_eval_payload(
        wave_id="independent-eval-tool-only",
        provider_materialization={
            "qwen_real_model_invocation_count": 0,
            "deepseek_dp_real_model_invocation_count": 0,
            "external_draft_model_invoked": False,
            "local_stub_only": False,
            "tool_diagnostic_only": True,
        },
        merge={"merged_count": 1, "merge_artifact": str(tmp_path / "merge.md")},
        staging={"staged_count": 1},
        lane_results=[{"mode": "provider_probe", "tool_invocation_performed": True}],
        output={"independent_eval": str(tmp_path / "independent_eval.json")},
    )

    assert payload["passed"] is False
    assert payload["status"] == "independent_eval_needs_repair"
    assert payload["tool_diagnostic_only"] is True
    assert payload["eval_is_health_signal_only"] is True
    assert payload["does_not_zero_artifact_delta"] is True


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
