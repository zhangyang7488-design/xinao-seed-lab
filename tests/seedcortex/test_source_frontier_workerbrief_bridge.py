import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_frontier_workerbrief_bridge.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_source_frontier_workerbrief_bridge.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_frontier_workerbrief_bridge", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path, *, source_frontier_empty: bool = True) -> None:
    _write_json(
        runtime / "state" / "source_frontier_durable_consumer" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_frontier_durable_consumer.v1",
            "status": "source_frontier_module_consumed" if source_frontier_empty else "source_frontier_module_backlog_remaining",
            "consumed_batch_ids": ["already-consumed"],
            "remaining_batch_ids": [] if source_frontier_empty else ["source-batch-1"],
            "wave_payload_refs": []
            if source_frontier_empty
            else [
                {
                    "batch_id": "source-batch-1",
                    "latest_ref": str(runtime / "state" / "source_frontier_fanin_acceptance" / "latest.json"),
                    "fan_in_ref": str(runtime / "state" / "fan_in_acceptance_queue" / "latest.json"),
                    "aaq_ref": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
                }
            ],
            "source_gap_open": not source_frontier_empty,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "claim_card_staging_queue" / "latest.json",
        {
            "schema_version": "xinao.codex_s.claim_card_staging_queue.v1",
            "status": "claim_card_staging_queue_ready",
            "claim_card_count": 1,
            "claim_cards": [
                {
                    "candidate_id": "claim-test-source",
                    "source_url": "local:test-source",
                    "source_family": "local_test",
                    "accepted_for": "source_frontier_workerbrief_bridge",
                }
            ],
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "source_frontier_fanin_acceptance" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_frontier_fanin_acceptance.v1",
            "status": "source_frontier_fanin_acceptance_ready",
            "source_package": {
                "source_package_digest_sha256": "abc123",
                "root": "local",
                "read_full_count": 1,
            },
            "validation": {"passed": True},
        },
    )
    for state_name, status in {
        "fan_in_acceptance_queue": "fan_in_acceptance_queue_ready",
        "artifact_acceptance_queue": "artifact_acceptance_queue_ready",
        "source_ledger": "source_ledger_ready",
        "next_frontier_machine_actions": "next_frontier_machine_actions_ready",
    }.items():
        _write_json(
            runtime / "state" / state_name / "latest.json",
            {
                "schema_version": f"xinao.test.{state_name}.v1",
                "status": status,
                "next_frontier": [{"action": "continue_test_frontier"}],
                "accepted_artifact_count": 1,
                "validation": {"passed": True},
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )
    _write_json(
        runtime / "state" / "loop_runtime_state" / "latest.json",
        {
            "schema_version": "xinao.codex_s.loop_runtime_state.v1",
            "status": "loop_runtime_state_ready",
            "next_frontier": [{"frontier_id": "nf-1", "action": "continue_test_frontier"}],
            "validation": {"passed": True},
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
            "brief_count": 2,
            "briefs": [
                {
                    "brief_id": "allocation:test:cheap",
                    "lane_class": "cheap_draft",
                    "objective": "Draft from source frontier.",
                    "expected_artifact": "draft_ref",
                    "provider_candidates": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
                    "worker_output_must_enter_staging": True,
                    "completion_claim_allowed": False,
                },
                {
                    "brief_id": "allocation:test:merge",
                    "lane_class": "merge_accept",
                    "objective": "Merge accepted source result.",
                    "expected_artifact": "merge_ref",
                    "provider_candidates": ["codex_exec"],
                    "worker_output_must_enter_staging": True,
                    "completion_claim_allowed": False,
                },
            ],
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "worker_brief" / "latest.json",
        {
            "schema_version": "xinao.codex_s.worker_brief_queue.v1",
            "status": "worker_brief_queue_ready",
            "brief_count": 1,
            "briefs": [],
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "schema_version": "xinao.codex_s.codex_native_provider_scheduler_phase4.v1",
            "status": "codex_native_provider_scheduler_ready",
            "qwen_prepaid_cheap_worker_default_first": True,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    worker_root = runtime / "state" / "modular_dynamic_worker_pool_phase1"
    _write_json(
        worker_root / "latest.json",
        {
            "schema_version": "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1",
            "status": "modular_dynamic_worker_pool_phase1_wave_merged",
            "runtime_enforced": True,
            "adoption_state": "runtime_enforced_global_default",
            "staged_count": 2,
            "merged_count": 1,
            "validation": {"passed": True},
        },
    )
    _write_json(
        worker_root / "default_route_binding" / "latest.json",
        {
            "schema_version": "xinao.codex_s.modular_dynamic_worker_pool_phase1.default_route_binding.v1",
            "status": "global_default_runtime_enforced",
            "qwen_prepaid_cheap_worker_default_first": True,
            "validation": {"passed": True},
        },
    )
    for child in ("draft_staging_queue", "merge_consumer", "spend_ledger"):
        _write_json(worker_root / child / "latest.json", {"status": f"{child}_ready", "validation": {"passed": True}})
    _write_json(runtime / "state" / "scheduler_invocation_packet" / "latest.json", {"status": "ready"})


def test_bridge_generates_bounded_source_item_when_frontier_empty(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime, source_frontier_empty=True)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id="bridge-test-wave",
        workflow_id="bridge-test-workflow",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_frontier_workerbrief_bridge.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_V1"
    assert payload["status"] == "source_frontier_workerbrief_bridge_ready"
    assert payload["source_frontier_delta"]["generated_bounded_item"] is True
    assert payload["source_frontier_items"][0]["bounded_current_source_frontier_item"] is True
    assert payload["worker_brief_binding_count"] == 2
    for binding in payload["worker_brief_bindings"]:
        assert binding["source_batch_id"].startswith("bounded-current-source-delta-")
        assert binding["frontier_batch_id"] == binding["source_batch_id"]
        assert binding["claim_card_id"] == "claim-test-source"
        assert binding["claim_card_ref"] == "local:test-source"
        assert binding["mapping_key"]
        assert binding["provider_policy"]["provider_scheduler_ref"]
        assert binding["fan_in_target"]["worker_output_must_enter_staging"] is True
        assert binding["aaq_target"]["claim_card_requires_source_ledger"] is True
        assert binding["next_frontier_policy"]["completion_claim_allowed"] is False
        assert binding["completion_claim_allowed"] is False
        assert binding["not_execution_controller"] is True
    assert payload["latest_alias_is_not_proof"] is True
    assert payload["validation"]["passed"] is True
    assert Path(payload["output_paths"]["wave"]).is_file()
    assert Path(payload["output_paths"]["worker_dispatch_ledger_wave"]).is_file()
    assert Path(payload["output_paths"]["worker_dispatch_ledger_activity"]).is_file()
    assert Path(payload["output_paths"]["readback_zh"]).is_file()


def test_bridge_maps_existing_source_batch_refs(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime, source_frontier_empty=False)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id="bridge-existing-source-wave",
        workflow_id="bridge-test-workflow",
        write=False,
    )

    assert payload["source_frontier_delta"]["generated_bounded_item"] is False
    assert payload["source_frontier_items"][0]["source_batch_id"] == "source-batch-1"
    assert payload["worker_brief_queue_summary"]["canonical_worker_brief_queue_source"] == "allocation_plan.worker_brief_queue"
    assert payload["worker_pool_existing_real_wave_evidence_reused"] is True
    assert payload["worker_pool_reinvoke_performed_by_bridge"] is False
    assert payload["validation"]["passed"] is True


def test_schema_contract_preserves_bridge_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "xinao.codex_s.source_frontier_workerbrief_bridge.v1"
    assert schema["properties"]["sentinel"]["const"] == "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_V1"
    assert schema["properties"]["source_frontier_to_workerbrief_binding"]["const"] is True
    assert schema["properties"]["thin_binding_only"]["const"] is True
    assert schema["properties"]["not_new_control_plane"]["const"] is True
    assert schema["properties"]["latest_alias_is_not_proof"]["const"] is True
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
