import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "pre_pass_audit_loop.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_pre_pass_audit_loop.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("pre_pass_audit_loop", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "codex_s_main_execution_loop_tick" / "latest.json",
        {
            "schema_version": "xinao.codex_s.main_execution_loop_tick.v1",
            "status": "main_execution_loop_tick_ready",
            "validation": {"passed": True},
            "not_execution_controller": True,
            "completion_claim_allowed": False,
        },
    )
    _write_json(
        runtime / "state" / "loop_runtime_state" / "latest.json",
        {
            "schema_version": "xinao.codex_s.temporal_activity_no_window_dp_worker_pool_phase3.v1",
            "status": "phase3_temporal_activity_event_queue_wave_ready",
            "active_workers": [{"worker_id": "temporal-worker"}],
            "task_backlog": [{"task_item_id": "next"}],
            "ready_frontier": [{"frontier_id": "next"}],
            "source_gaps": [],
            "next_frontier": [{"frontier_id": "next"}],
            "stop": {
                "stop_allowed": False,
                "derived": True,
                "stop_reason": "continue_required:active_worker_or_valid_lease",
            },
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "schema_version": "xinao.codex_s.codex_native_provider_scheduler_phase4.v1",
            "status": "codex_native_provider_scheduler_ready",
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
            "qwen_first_applies_only_to": "cheap_worker_lane",
            "external_cheap_draft_count": 8,
            "qwen_prepaid_draft_count": 8,
            "staged_count": 8,
            "merged_count": 1,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "modular_dynamic_worker_pool_phase1" / "draft_staging_queue" / "latest.json",
        {"staged_count": 8, "merged_count": 1, "validation": {"passed": True}},
    )
    _write_json(
        runtime / "state" / "modular_dynamic_worker_pool_phase1" / "merge_consumer" / "latest.json",
        {"staged_count": 8, "merged_count": 1, "validation": {"passed": True}},
    )
    _write_json(
        runtime / "state" / "source_frontier_durable_consumer" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_frontier_durable_consumer.v1",
            "status": "source_frontier_module_consumed",
            "source_gap_open": False,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    readback = runtime / "readback" / "zh" / "temporal_activity_no_window_dp_worker_pool_phase3_20260704.md"
    readback.parent.mkdir(parents=True, exist_ok=True)
    readback.write_text("stop_allowed=false; next_machine_action=continue\n", encoding="utf-8")


def test_pre_pass_generates_candidate_lanes_and_repair_plan(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path,
        task_id="pre_pass_audit_loop_20260704",
        wave_id="pre-pass-test-wave",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.pre_pass_audit_loop.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1"
    assert payload["status"] == "pre_pass_audit_loop_ready"
    assert payload["candidate_snapshot"]["candidate_kind"] == "before_final_or_pass"
    assert payload["audit_lane_registry"]["lane_count"] == 8
    assert [lane["lane_id"] for lane in payload["audit_lane_registry"]["lanes"]] == [
        "hotpath_lane",
        "runtime_lane",
        "provider_lane",
        "source_gap_lane",
        "fanin_lane",
        "completion_boundary_lane",
        "readback_lane",
        "history_lane",
    ]
    assert payload["audit_fan_in"]["decision"] == "repair_required"
    assert payload["audit_fan_in"]["final_allowed"] is False
    assert payload["pre_pass_payload"]["decision"] == "dispatch_repair_plan"
    assert payload["pre_pass_payload"]["continue_main_loop"] is True
    assert payload["repair_plan"]["dispatch_to"] == "root_intent_loop_driver"
    assert payload["repair_plan"]["completion_claim_allowed"] is False
    assert payload["completion_claim_allowed"] is False
    assert payload["not_old_segment_audit"] is True
    assert payload["not_completion_gate"] is True
    assert payload["not_execution_controller"] is True
    assert payload["validation"]["passed"] is True
    assert (runtime / "state" / "pre_pass_audit_loop" / "latest.json").is_file()
    assert (runtime / "state" / "pre_pass_audit_loop" / "repair_plan_latest.json").is_file()
    assert (runtime / "readback" / "zh" / "pre_pass_audit_loop_pre-pass-test-wave.md").is_file()


def test_pre_pass_blocks_completion_overclaim(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    candidate = tmp_path / "candidate.json"
    _write_json(candidate, {"candidate_kind": "before_final_or_pass", "completion_claim_allowed": True})

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path,
        task_id="pre_pass_audit_loop_20260704",
        wave_id="pre-pass-overclaim-wave",
        candidate_json=candidate,
        write=False,
    )

    completion_lane = [
        lane
        for lane in payload["audit_lane_registry"]["lanes"]
        if lane["lane_id"] == "completion_boundary_lane"
    ][0]
    assert completion_lane["status"] == "HARD_RISK"
    assert payload["audit_fan_in"]["decision"] == "hard_risk_stop_for_user"
    assert payload["final_allowed"] is False
    assert payload["completion_claim_allowed"] is False


def test_pre_pass_repeated_fixable_without_artifact_delta_becomes_named_blocker(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    first = module.build(
        runtime_root=runtime,
        repo_root=tmp_path,
        task_id="pre_pass_audit_loop_20260704",
        wave_id="pre-pass-repeat-wave-1",
        write=True,
    )
    second = module.build(
        runtime_root=runtime,
        repo_root=tmp_path,
        task_id="pre_pass_audit_loop_20260704",
        wave_id="pre-pass-repeat-wave-2",
        write=True,
    )

    assert first["pre_pass_payload"]["continue_main_loop"] is True
    assert second["anti_audit_marathon_gate"]["triggered"] is True
    assert second["pre_pass_payload"]["decision"] == "named_blocker"
    assert second["pre_pass_payload"]["continue_main_loop"] is False
    assert "REPEATED_FIXABLE_WITHOUT_ARTIFACT_DELTA" in second["named_blocker"]
    assert second["progress_self_evolution"]["strategy_mutation"]["scheduler_consumption_required"] is True


def test_schema_contract_preserves_pre_pass_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.pre_pass_audit_loop.v1"
    )
    assert schema["properties"]["sentinel"]["const"] == (
        "SENTINEL:XINAO_CODEX_S_PRE_PASS_AUDIT_LOOP_V1"
    )
    assert schema["properties"]["work_id"]["const"] == "xinao_seed_cortex_phase0_20260701"
    assert schema["properties"]["repair_plan"]["properties"]["dispatch_to"]["const"] == (
        "root_intent_loop_driver"
    )
    assert schema["properties"]["repair_plan"]["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_old_segment_audit"]["const"] is True
    assert schema["properties"]["not_completion_gate"]["const"] is True
    assert schema["properties"]["not_execution_controller"]["const"] is True
