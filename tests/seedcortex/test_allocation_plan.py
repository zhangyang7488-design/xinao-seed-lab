import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "allocation_plan.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_allocation_plan.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("allocation_plan", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path, *, qwen_ready: bool = True) -> None:
    _write_json(
        runtime / "state" / "loop_runtime_state" / "latest.json",
        {
            "schema_version": "xinao.codex_s.temporal_activity_no_window_dp_worker_pool_phase3.v1",
            "status": "phase3_temporal_activity_event_queue_wave_ready",
            "active_workers": [{"worker_id": "temporal-worker", "valid_lease": True}],
            "task_backlog": [{"task_item_id": "item-1"}],
            "ready_frontier": [{"frontier_id": "frontier-1"}],
            "draft_staging": {"staged_count": 6, "merged_count": 1, "unmerged_count": 2},
            "merge_backlog": [],
            "fan_in_backlog": [],
            "source_gaps": [{"gap_id": "source-gap-1"}],
            "blockers": [],
            "next_frontier": [{"frontier_id": "next-1"}],
            "capacity_by_lane_class": {
                "dynamic_width_record": {
                    "width_candidates": {
                        "provider_available_slots": 12,
                        "executor_available_slots": 10,
                        "independent_task_count": 18,
                        "useful_frontier_count": 18,
                    },
                    "rate_limit_error": "",
                    "retry_after": "",
                }
            },
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    providers = [
        {"provider_id": "codex_exec", "status": "ready"},
        {"provider_id": "codex_sdk", "status": "ready"},
        {"provider_id": "deepseek_dp", "status": "ready"},
        {"provider_id": "search", "status": "foreground_tool_ready"},
        {"provider_id": "temporal_activity", "status": "ready"},
    ]
    if qwen_ready:
        providers.append({"provider_id": "qwen_prepaid_cheap_worker", "status": "ready"})
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "schema_version": "xinao.codex_s.codex_native_provider_scheduler_phase4.v1",
            "status": "codex_native_provider_scheduler_ready",
            "provider_registry": {"providers": providers},
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json",
        {
            "schema_version": "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1",
            "status": "modular_dynamic_worker_pool_phase1_wave_merged",
            "actual_dispatched_width": 12,
            "actual_completed_width": 10,
            "staged_count": 6,
            "merged_count": 1,
            "width_candidates": {"provider_available_slots": 12, "independent_task_count": 18},
            "token_cost_spend": {"total_tokens": 1200, "cost_usd": 0.0},
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "source_frontier_durable_consumer" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_frontier_durable_consumer.v1",
            "status": "source_frontier_gap_open",
            "remaining_batch_ids": ["batch-1", "batch-2"],
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "source_family_wave_scheduler" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_wave_scheduler.v1",
            "status": "source_family_wave_scheduler_ready",
            "frontier_lanes": [{"lane": "official"}, {"lane": "github"}],
            "dynamic_width": {"actual_dispatched_width": 5, "independent_task_count": 8},
            "validation": {"passed": True},
        },
    )
    _write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_ready",
            "staged_candidate_count": 4,
            "accepted_artifact_count": 2,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
        },
    )
    _write_json(
        runtime / "state" / "worker_dispatch_ledger" / "latest.json",
        {
            "schema_version": "xinao.codex_s.worker_dispatch_ledger.v1",
            "status": "worker_dispatch_ledger_ready",
            "poll_result_summary": {"failed_count": 0, "blocked_count": 0},
            "validation": {"passed": True},
        },
    )


def test_allocation_plan_generates_dynamic_multilane_plan(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        task_id="allocation_plan_20260704",
        wave_id="allocation-plan-test-wave",
        write=True,
    )

    lane_classes = {lane["lane_class"] for lane in payload["lane_allocations"]}
    cheap_lane = [lane for lane in payload["lane_allocations"] if lane["lane_class"] == "cheap_draft"][0]
    assert payload["schema_version"] == "xinao.codex_s.allocation_plan.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1"
    assert payload["status"] == "allocation_plan_ready"
    assert payload["not_task_route_decision_enum"] is True
    assert payload["same_task_multi_lane_allocation"] is True
    assert "cheap_draft" in lane_classes
    assert "eval" in lane_classes
    assert {"merge_accept", "ci_verify"} & lane_classes
    assert "search_source" in lane_classes
    assert cheap_lane["requested_width"] > 0
    assert cheap_lane["provider_candidates"][0] == "qwen_prepaid_cheap_worker"
    assert payload["target_width_source"] == "derived_from_runtime_feedback_inputs"
    assert payload["fixed_target_width_used"] is False
    assert payload["fixed_20_or_50_used"] is False
    assert payload["worker_brief_queue"]["brief_count"] == len(payload["lane_allocations"])
    assert payload["dispatch_attempts"]["dispatch_attempt_count"] == len(payload["lane_allocations"])
    assert payload["dispatch_attempts"]["report_substitute_allowed"] is False
    assert payload["mature_capability_first"]["schema_version"] == "xinao.codex_s.mature_capability_first.v1"
    assert payload["mature_capability_first"]["validation"]["passed"] is True
    assert payload["mature_capability_first"]["not_execution_controller"] is True
    assert payload["stop_allowed"]["derived_only"] is True
    assert payload["stop_allowed"]["value"] is False
    assert payload["next_allocation_advice"]["decision"] == "dispatch_ready_frontier_now"
    assert payload["completion_claim_allowed"] is False
    assert payload["not_execution_controller"] is True
    assert payload["validation"]["passed"] is True
    assert (runtime / "state" / "allocation_plan" / "latest.json").is_file()
    assert (runtime / "state" / "mature_capability_first" / "latest.json").is_file()
    assert (runtime / "state" / "allocation_plan" / "worker_brief_queue_latest.json").is_file()
    assert (runtime / "readback" / "zh" / "allocation_plan_allocation-plan-test-wave.md").is_file()


@pytest.mark.parametrize("provider_mode", ["qwen_dp_first", "codex_brain_only"])
def test_allocation_plan_does_not_apply_legacy_width_cap_to_token_saving_default(
    tmp_path: Path,
    provider_mode: str,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    _write_json(
        runtime / "state" / "provider_cost_routing_policy" / "latest.json",
        {
            "status": "provider_cost_routing_policy_ready",
            "effective_mode": provider_mode,
            "qwen_dp_first_global_default": True,
            "codex_brain_only_global_default": provider_mode == "codex_brain_only",
        },
    )
    _write_json(
        runtime / "state" / "strategy_mutation" / "latest.json",
        {
            "status": "strategy_mutation_active",
            "active": True,
            "next_mode": "legacy-max-width-cap-residue",
            "max_width_cap": 3,
            "drain_only": False,
            "lane_class_pause": [],
            "provider_route_hints": {},
            "preferred_provider_order": [],
            "provider_policy_override": {"max_width_cap": 3},
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        task_id="allocation_plan_20260704",
        wave_id="allocation-plan-qwen-dp-no-cap-wave",
        write=False,
    )

    cheap_lane = [
        lane for lane in payload["lane_allocations"] if lane["lane_class"] == "cheap_draft"
    ][0]
    assert payload["strategy_mutation_consumption"]["strategy_mutation_consumed"] is True
    assert payload["codex_token_saving_width_policy"][
        "qwen_dp_dynamic_width_unlimited_by_codex_budget"
    ] is True
    assert payload["codex_token_saving_width_policy"][
        "legacy_max_width_cap_applies_to_qwen_dp"
    ] is False
    assert cheap_lane["requested_width"] == 11
    assert payload["total_requested_width"] > 3
    assert payload["validation"]["passed"] is True


def test_allocation_plan_records_repair_when_qwen_first_unavailable(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime, qwen_ready=False)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        task_id="allocation_plan_20260704",
        wave_id="allocation-plan-qwen-blocker-wave",
        write=False,
    )

    assert payload["repair_required"] is True
    assert payload["repair_plan"]["dispatch_to"] == "root_intent_loop_driver"
    assert payload["repair_plan"]["temporal_consumable"] is True
    assert payload["repair_plan"]["report_substitute_allowed"] is False
    blockers = {item["blocker_name"] for item in payload["repair_plan"]["repair_items"]}
    assert "QWEN_PREPAID_FIRST_NOT_ATTEMPTED" in blockers
    assert payload["next_allocation_advice"]["decision"] == "dispatch_repair_plan"
    assert payload["validation"]["passed"] is True


def test_schema_contract_preserves_allocation_plan_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "xinao.codex_s.allocation_plan.v1"
    assert schema["properties"]["sentinel"]["const"] == "SENTINEL:XINAO_CODEX_S_ALLOCATION_PLAN_V1"
    assert schema["properties"]["not_task_route_decision_enum"]["const"] is True
    assert schema["properties"]["target_width_source"]["const"] == "derived_from_runtime_feedback_inputs"
    assert schema["properties"]["fixed_20_or_50_used"]["const"] is False
    assert schema["properties"]["repair_plan"]["properties"]["dispatch_to"]["const"] == "root_intent_loop_driver"
    assert schema["properties"]["dispatch_attempts"]["properties"]["report_substitute_allowed"]["const"] is False
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
