import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "progress_self_evolution.py"
ALLOCATION_PATH = REPO_ROOT / "services" / "agent_runtime" / "allocation_plan.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_allocation_runtime(runtime: Path) -> None:
    state = runtime / "state"
    _write_json(
        state / "loop_runtime_state" / "latest.json",
        {
            "status": "phase3_temporal_activity_event_queue_wave_ready",
            "task_backlog": [{"id": "task"}],
            "ready_frontier": [{"id": "frontier"}],
            "next_frontier": [{"id": "self-loop"}],
            "draft_staging": {"staged_count": 2, "unmerged_count": 2},
            "validation": {"passed": True},
        },
    )
    _write_json(
        state / "modular_dynamic_worker_pool_phase1" / "latest.json",
        {
            "status": "ready",
            "target_width": 12,
            "actual_dispatched_width": 12,
            "actual_completed_width": 12,
            "staged_count": 2,
            "merged_count": 0,
            "validation": {"passed": True},
        },
    )
    _write_json(
        state / "codex_native_provider_scheduler_phase4_20260704" / "latest.json",
        {
            "status": "ready",
            "providers": [
                {"provider_id": "qwen_prepaid_cheap_worker", "status": "ready"},
                {"provider_id": "deepseek_dp", "status": "ready"},
                {"provider_id": "codex_exec", "status": "ready"},
            ],
            "validation": {"passed": True},
        },
    )
    for name in [
        "source_frontier_durable_consumer",
        "source_family_wave_scheduler",
        "artifact_acceptance_queue",
        "worker_dispatch_ledger",
        "scheduler_invocation_packet",
    ]:
        _write_json(
            state / name / "latest.json", {"status": "ready", "validation": {"passed": True}}
        )


def test_progress_ledger_repeated_no_progress_emits_strategy_mutation(tmp_path: Path) -> None:
    module = _load_module(MODULE_PATH, "progress_self_evolution")
    runtime = tmp_path / "runtime"

    first = module.record_progress_bundle(
        runtime_root=runtime,
        wave_id="wave-001",
        source_digest="digest-1",
        source_theme_id="empty",
        artifact_delta_count=0,
        source_frontier_empty=True,
        synthetic_item_used=False,
        feedback_source_refs=[
            str(runtime / "state" / "source_frontier_durable_consumer" / "latest.json")
        ],
        write=True,
    )
    second = module.record_progress_bundle(
        runtime_root=runtime,
        wave_id="wave-002",
        source_digest="digest-1",
        source_theme_id="empty",
        artifact_delta_count=0,
        source_frontier_empty=True,
        synthetic_item_used=False,
        feedback_source_refs=[
            str(runtime / "state" / "source_frontier_durable_consumer" / "latest.json")
        ],
        write=True,
    )

    assert first["progress_ledger"]["no_progress_count"] == 1
    assert second["progress_ledger"]["no_progress_count"] == 2
    assert second["reflection_record"]["can_influence_scheduler"] is True
    assert second["strategy_mutation"]["active"] is True
    assert second["strategy_mutation"]["scheduler_consumption_required"] is True
    assert (runtime / "state" / "strategy_mutation" / "latest.json").is_file()


def test_allocation_plan_consumes_strategy_mutation_to_drain_only(tmp_path: Path) -> None:
    progress = _load_module(MODULE_PATH, "progress_self_evolution")
    allocation = _load_module(ALLOCATION_PATH, "allocation_plan")
    runtime = tmp_path / "runtime"
    _seed_allocation_runtime(runtime)
    progress.record_progress_bundle(
        runtime_root=runtime,
        wave_id="wave-001",
        source_digest="digest-2",
        artifact_delta_count=0,
        source_frontier_empty=True,
        feedback_source_refs=[str(runtime / "state" / "loop_runtime_state" / "latest.json")],
        write=True,
    )
    progress.record_progress_bundle(
        runtime_root=runtime,
        wave_id="wave-002",
        source_digest="digest-2",
        artifact_delta_count=0,
        source_frontier_empty=True,
        feedback_source_refs=[str(runtime / "state" / "loop_runtime_state" / "latest.json")],
        write=True,
    )

    payload = allocation.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id="allocation-consumes-mutation",
        write=False,
    )

    lane_classes = set(payload["lane_classes"])
    assert payload["strategy_mutation_consumption"]["strategy_mutation_consumed"] is True
    assert payload["strategy_mutation_consumption"]["drain_only"] is True
    assert "cheap_draft" not in lane_classes
    assert "eval" not in lane_classes
    assert "merge_accept" in lane_classes
    assert (
        payload["next_allocation_advice"]["decision"]
        == "drain_fan_in_or_replan_from_strategy_mutation"
    )
    assert payload["next_allocation_advice"]["strategy_mutation_consumed"] is True
    assert payload["validation"]["passed"] is True


def test_readback_delta_is_not_progress(tmp_path: Path) -> None:
    module = _load_module(MODULE_PATH, "progress_self_evolution")
    runtime = tmp_path / "runtime"

    first = module.record_progress_bundle(
        runtime_root=runtime,
        wave_id="wave-readback-only-001",
        source_digest="digest-readback-only",
        artifact_delta_count=0,
        readback_delta=3,
        aaq_accepted_delta=0,
        default_invoke_delta=0,
        source_frontier_empty=False,
        feedback_source_refs=[],
        write=True,
    )
    second = module.record_progress_bundle(
        runtime_root=runtime,
        wave_id="wave-readback-only-002",
        source_digest="digest-readback-only",
        artifact_delta_count=0,
        readback_delta=1,
        aaq_accepted_delta=0,
        default_invoke_delta=0,
        source_frontier_empty=False,
        feedback_source_refs=[],
        write=True,
    )

    assert first["progress_ledger"]["artifact_delta_count"] == 0
    assert first["progress_ledger"]["readback_delta"] == 3
    assert first["progress_ledger"]["progress_made"] is False
    assert first["progress_ledger"]["no_progress_count"] == 1
    assert second["progress_ledger"]["artifact_delta_count"] == 0
    assert second["progress_ledger"]["readback_delta"] == 1
    assert second["progress_ledger"]["no_progress_count"] == 2
