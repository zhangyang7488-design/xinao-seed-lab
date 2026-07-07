import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRESS_PATH = REPO_ROOT / "services" / "agent_runtime" / "progress_self_evolution.py"
BRIDGE_PATH = REPO_ROOT / "services" / "agent_runtime" / "external_research_strategy_mutation_bridge.py"
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
            "provider_registry": {
                "providers": [
                    {"provider_id": "qwen_prepaid_cheap_worker", "status": "ready"},
                    {"provider_id": "deepseek_dp", "status": "ready"},
                    {"provider_id": "codex_exec", "status": "ready"},
                    {"provider_id": "temporal_activity", "status": "ready"},
                ]
            },
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
        _write_json(state / name / "latest.json", {"status": "ready", "validation": {"passed": True}})


def test_external_mature_bridge_emits_scheduler_consumable_mutation(tmp_path: Path) -> None:
    progress = _load_module(PROGRESS_PATH, "progress_self_evolution_bridge_test")
    bridge = _load_module(BRIDGE_PATH, "external_bridge_test")
    allocation = _load_module(ALLOCATION_PATH, "allocation_bridge_test")
    runtime = tmp_path / "runtime"
    source_package = tmp_path / "external_mature_package.txt"
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
    feedback_ref = str(runtime / "state" / "loop_runtime_state" / "latest.json")
    progress.record_progress_bundle(
        runtime_root=runtime,
        wave_id="bridge-progress-001",
        source_digest="same-digest",
        artifact_delta_count=0,
        feedback_source_refs=[feedback_ref],
        no_progress_reason="no_artifact_or_accepted_delta",
        write=True,
    )
    progress.record_progress_bundle(
        runtime_root=runtime,
        wave_id="bridge-progress-002",
        source_digest="same-digest",
        artifact_delta_count=0,
        feedback_source_refs=[feedback_ref],
        no_progress_reason="no_artifact_or_accepted_delta",
        write=True,
    )

    payload = bridge.run_bridge(
        runtime_root=runtime,
        source_package=source_package,
        wave_id="external-bridge-wave",
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["external_mature_discovery_decision"]["external_mature_discovery_required"] is True
    assert payload["external_mature_discovery_decision"]["codex_reflection_subagent_dispatch_required"] is True
    assert payload["external_mature_discovery_decision"]["required_codex_subagent_count"] == 2
    assert payload["source_ledger"]["entry_count"] == 4
    assert payload["claim_cards"]["claim_card_count"] == 4
    assert payload["reflection_subagent_dispatch"]["dispatched_subagent_count"] == 2
    assert payload["reflection_subagent_dispatch"]["scheduler_spawned_lane_count"] == 2
    assert payload["reflection_subagent_dispatch"]["validation"]["passed"] is True
    assert payload["reflection_worker_dispatch_ledger"]["summary"]["subagent_entry_count"] == 2
    assert {
        entry["agent_id"]
        for entry in payload["reflection_worker_dispatch_ledger"]["dispatch_entries"]
    } == {"codex_reflection_local_search", "codex_reflection_external_search"}
    assert all(
        entry["provider"] == "codex.subagent" and entry["mode"] == "subagent"
        for entry in payload["reflection_worker_dispatch_ledger"]["dispatch_entries"]
    )
    assert payload["strategy_mutation_candidate"]["reflection_contrast_refs"]
    assert payload["strategy_mutation_candidate"]["worker_dispatch_ledger_refs"]
    assert payload["strategy_mutation_candidate"]["status"] == "strategy_mutation_candidate_ready"
    assert payload["strategy_mutation"]["active"] is True
    assert payload["strategy_mutation"]["external_mature_discovery"]["codex_reflection_subagent_refs"] == [
        "codex_reflection_local_search",
        "codex_reflection_external_search",
    ]
    assert payload["strategy_mutation"]["external_mature_discovery"]["worker_dispatch_ledger_refs"]
    assert (runtime / "state" / "strategy_mutation" / "latest.json").is_file()

    _seed_allocation_runtime(runtime)
    allocation_payload = allocation.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        wave_id="allocation-after-external-bridge",
        write=False,
    )
    assert allocation_payload["strategy_mutation_consumption"]["strategy_mutation_consumed"] is True
    assert allocation_payload["strategy_mutation_consumption"]["external_mature_source_refs"]
    assert all(
        brief["strategy_mutation_applied"] is True
        for brief in allocation_payload["worker_brief_queue"]["briefs"]
    )
    assert allocation_payload["validation"]["passed"] is True
