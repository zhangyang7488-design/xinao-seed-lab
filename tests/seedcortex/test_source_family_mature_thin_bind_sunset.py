import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_family_mature_thin_bind_sunset.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_family_mature_thin_bind_sunset", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path) -> None:
    source_family_wave = "unit-source-family-wave"
    _write_json(
        runtime / "state" / "source_family_wave_scheduler" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_wave_scheduler.v1",
            "status": "source_family_wave_scheduler_ready",
            "task_id": "wave4_20260701_frontier_source_family_20260704",
            "wave_id": source_family_wave,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "source_family_wave_scheduler" / "temporal_activity_latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_wave_scheduler.v1",
            "status": "source_family_wave_scheduler_ready",
            "wave_id": source_family_wave,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime
        / "state"
        / "source_family_wave_scheduler"
        / "total_source_frontier_coverage"
        / "latest.json",
        {
            "schema_version": "xinao.codex_s.total_source_frontier_coverage.v1",
            "status": "total_source_frontier_coverage_ready",
            "wave_id": source_family_wave,
            "topic_family_count": 407,
            "covered_topic_family_count": 407,
            "remaining_topic_family_count": 0,
            "source_gap_open": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "source_family_wave_scheduler" / "source_topic_claimcards" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_topic_claimcards.v1",
            "status": "source_topic_claimcards_ready",
            "claim_card_count": 186,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "mature_carrier_replacement_bindings" / "latest.json",
        {
            "schema_version": "xinao.codex_s.mature_carrier_replacement_bindings.v1",
            "status": "mature_carrier_thin_bind_ready",
            "wave_id": source_family_wave,
            "thin_bind_landed": True,
            "thin_bind_landed_count": 2,
            "policy_only": False,
            "landed_bindings": [
                {
                    "binding_id": "temporal_task_queue_activity_thin_bind",
                    "handrolled_surface": "30min runner",
                    "mature_carrier": "Temporal Task Queue + Temporal Activity",
                    "source_claim_card_id": "claim-temporal-task-queue-worker-polling",
                    "source_url": "https://docs.temporal.io/task-queue",
                    "thin_bind_adapter": "services.agent_runtime.temporal_codex_task_workflow.source_family_wave_scheduler_activity",
                    "invoke": {"temporal_activity": "source_family_wave_scheduler_activity"},
                    "sunset_scope": ["sleep_1800_main_loop"],
                    "thin_bind_landed": True,
                    "policy_only": False,
                },
                {
                    "binding_id": "claimcard_sourceledger_fanin_aaq_thin_bind",
                    "handrolled_surface": "report-only search",
                    "mature_carrier": "ClaimCard -> SourceLedger -> FanInAcceptanceQueue -> ArtifactAcceptanceQueue",
                    "source_claim_card_id": "claim-local-wave3-consumed-evidence",
                    "source_url": "D:/XINAO_RESEARCH_RUNTIME/state/source_frontier_durable_consumer/latest.json",
                    "thin_bind_adapter": "SeedCortexService.artifact_acceptance_queue",
                    "invoke": {"cli": "python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler"},
                    "sunset_scope": ["PASS_as_source_acceptance"],
                    "thin_bind_landed": True,
                    "policy_only": False,
                },
            ],
            "candidate_replacement_queue": [
                {
                    "binding_id": "mcp_reference_servers_candidate",
                    "handrolled_surface": "adapter catalog",
                    "mature_carrier": "Model Context Protocol reference/community servers",
                    "source_claim_card_id": "claim-mcp-reference-servers-and-registry",
                    "source_url": "https://github.com/modelcontextprotocol/servers",
                    "promotion_gate": "adapter_smoke_before_default_capability",
                }
            ],
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "capabilities" / "codex_s.source_family_mature_carrier_thin_bind" / "manifest.json",
        {
            "schema_version": "xinao.capability_manifest.v1",
            "capability_id": "codex_s.source_family_mature_carrier_thin_bind",
            "status": "ready",
            "invoke": {
                "cli": "python -m xinao_seedlab.cli.__main__ source-family-wave-scheduler --wave-id <wave>",
                "temporal_activity": "source_family_wave_scheduler_activity",
            },
            "not_completion_boundary": True,
        },
    )
    _write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {"accepted_artifact_count": 193, "validation": {"passed": True}, "not_execution_controller": True},
    )
    _write_json(
        runtime / "state" / "source_ledger" / "latest.json",
        {"entry_count": 193, "validation": {"passed": True}, "not_execution_controller": True},
    )
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "next_frontier_machine_actions_ready",
            "wave_id": source_family_wave,
            "next_frontier": [{"action": "enter_phase5_mature_thin_bind_sunset"}],
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )


def test_source_family_mature_thin_bind_sunset_consumes_phase5_action(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-phase5-sunset",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_family_mature_thin_bind_sunset.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET_READY"
    assert payload["status"] == "source_family_mature_thin_bind_sunset_ready"
    assert payload["task_id"] == "wave5_source_family_mature_thin_bind_sunset_20260704"
    assert payload["routing"] == "continue_same_task"
    assert payload["parent_wave_id"] == "unit-source-family-wave"
    assert payload["consumed_next_frontier_action"] == "enter_phase5_mature_thin_bind_sunset"
    assert payload["source_frontier_remaining_topic_family_count"] == 0
    assert payload["sunset_edges"]["edge_count"] == 2
    assert payload["candidate_adapter_smoke_queue"]["candidate_count"] == 1
    assert payload["next_frontier_machine_actions"]["should_continue_loop"] is True
    assert payload["next_frontier_machine_actions"]["stop_allowed"] is False
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "smoke_mature_carrier_adapter_candidates"
    )
    assert payload["repair_plan"]["status"] == "repair_not_required"
    assert payload["completion_claim_allowed"] is False
    assert payload["validation"]["passed"] is True

    for path in [
        runtime / "state" / "source_family_mature_thin_bind_sunset" / "latest.json",
        runtime / "state" / "source_family_mature_thin_bind_sunset" / "sunset_edges" / "latest.json",
        runtime
        / "state"
        / "source_family_mature_thin_bind_sunset"
        / "candidate_adapter_smoke_queue"
        / "latest.json",
        runtime / "capabilities" / "codex_s.source_family_mature_thin_bind_sunset" / "manifest.json",
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        runtime / "readback" / "zh" / "wave_block5_mature_thin_bind_sunset_20260704.md",
    ]:
        assert path.is_file(), path


def test_source_family_mature_thin_bind_sunset_does_not_consume_foreign_action(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    next_frontier_path = runtime / "state" / "next_frontier_machine_actions" / "latest.json"
    foreign_next_frontier = {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "xinao_surface_priority_preempt_next_frontier_ready",
        "wave_id": "unit-foreign-wave",
        "next_frontier": [{"action": "xinao_surface_build_deploy_verify_shortcut"}],
        "validation": {"passed": True},
        "not_execution_controller": True,
    }
    _write_json(next_frontier_path, foreign_next_frontier)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-phase5-foreign-action",
        write=True,
    )

    assert payload["status"] == "source_family_mature_thin_bind_sunset_blocked"
    assert payload["consumed_next_frontier_action"] == ""
    assert payload["foreign_next_frontier_action_deferred"] == (
        "xinao_surface_build_deploy_verify_shortcut"
    )
    assert payload["next_frontier_write_skipped"] is True
    assert payload["validation"]["passed"] is False
    assert json.loads(next_frontier_path.read_text(encoding="utf-8")) == foreign_next_frontier
