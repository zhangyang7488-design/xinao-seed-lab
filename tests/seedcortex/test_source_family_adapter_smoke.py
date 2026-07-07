import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_family_adapter_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_family_adapter_smoke", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_runtime(runtime: Path) -> None:
    phase5_wave = "unit-phase5-sunset"
    _write_json(
        runtime / "state" / "source_family_mature_thin_bind_sunset" / "candidate_adapter_smoke_queue" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_phase5_candidate_adapter_smoke_queue.v1",
            "status": "candidate_adapter_smoke_queue_ready",
            "wave_id": phase5_wave,
            "candidate_count": 2,
            "candidates": [
                {
                    "queue_id": "phase5-adapter-smoke-01-mcp_reference_servers_candidate",
                    "binding_id": "mcp_reference_servers_candidate",
                    "mature_carrier": "Model Context Protocol reference/community servers",
                    "handrolled_surface": "hand-written tool adapter catalog",
                    "source_claim_card_id": "claim-mcp-reference-servers-and-registry",
                    "source_url": "https://github.com/modelcontextprotocol/servers",
                    "promotion_gate": "adapter_smoke_before_default_capability",
                    "status": "adapter_smoke_required_before_promotion",
                    "thin_bind_landed": False,
                },
                {
                    "queue_id": "phase5-adapter-smoke-02-contextforge_gateway_candidate",
                    "binding_id": "contextforge_gateway_candidate",
                    "mature_carrier": "IBM ContextForge MCP Gateway",
                    "handrolled_surface": "custom MCP/REST/gRPC registry glue",
                    "source_claim_card_id": "claim-mcp-contextforge-gateway-candidate",
                    "source_url": "https://github.com/IBM/mcp-context-forge",
                    "promotion_gate": "adapter_smoke_before_default_capability",
                    "status": "adapter_smoke_required_before_promotion",
                    "thin_bind_landed": False,
                },
            ],
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "source_family_mature_thin_bind_sunset" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_mature_thin_bind_sunset.v1",
            "status": "source_family_mature_thin_bind_sunset_ready",
            "wave_id": phase5_wave,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "phase5_next_frontier_ready",
            "wave_id": phase5_wave,
            "parent_wave_id": "unit-source-family-wave",
            "next_frontier": [{"action": "smoke_mature_carrier_adapter_candidates"}],
            "stop_allowed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {"accepted_artifact_count": 3, "validation": {"passed": True}, "not_execution_controller": True},
    )
    _write_json(
        runtime / "state" / "source_ledger" / "latest.json",
        {"entry_count": 3, "validation": {"passed": True}, "not_execution_controller": True},
    )


def test_source_family_adapter_smoke_consumes_candidate_queue(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-adapter-smoke",
        probe_mode="synthetic",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_family_adapter_smoke.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_SMOKE_READY"
    assert payload["status"] == "source_family_adapter_smoke_ready"
    assert payload["task_id"] == "wave6_source_family_adapter_smoke_20260704"
    assert payload["routing"] == "continue_same_task"
    assert payload["parent_wave_id"] == "unit-phase5-sunset"
    assert payload["consumed_next_frontier_action"] == "smoke_mature_carrier_adapter_candidates"
    assert payload["candidate_count"] == 2
    assert payload["passed_candidate_count"] == 2
    assert payload["candidate_results"]["validation"]["passed"] is True
    assert payload["candidate_results"]["results"][0]["probe"]["probe_mode"] == "synthetic"
    assert payload["candidate_results"]["results"][0]["proposed_adapter_scope"]["promotion_allowed"] is False
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "implement_thin_bind_adapter_for_smoked_candidates"
    )
    assert payload["completion_claim_allowed"] is False
    assert payload["validation"]["passed"] is True

    for path in [
        runtime / "state" / "source_family_adapter_smoke" / "latest.json",
        runtime / "state" / "source_family_adapter_smoke" / "candidate_results" / "latest.json",
        runtime / "capabilities" / "codex_s.source_family_adapter_smoke" / "manifest.json",
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        runtime / "readback" / "zh" / "source_family_adapter_smoke_20260704.md",
    ]:
        assert path.is_file(), path


def test_source_family_adapter_smoke_is_idempotent_after_next_action(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "adapter_smoke_next_frontier_ready",
            "wave_id": "unit-adapter-smoke-previous",
            "parent_wave_id": "unit-phase5-sunset",
            "next_frontier": [{"action": "implement_thin_bind_adapter_for_smoked_candidates"}],
            "stop_allowed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-adapter-smoke-idempotent",
        probe_mode="synthetic",
        write=True,
    )

    assert payload["status"] == "source_family_adapter_smoke_ready"
    assert payload["consumed_next_frontier_action"] == "smoke_mature_carrier_adapter_candidates"
    assert payload["parent_wave_id"] == "unit-phase5-sunset"
    assert payload["validation"]["passed"] is True


def test_source_family_adapter_smoke_replays_after_thin_bind_eval_action(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "smoked_candidate_thin_bind_next_frontier_ready",
            "wave_id": "unit-thin-bind",
            "parent_wave_id": "unit-adapter-smoke",
            "next_frontier": [
                {"action": "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"}
            ],
            "stop_allowed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-adapter-smoke-replay-after-eval",
        probe_mode="synthetic",
        write=True,
    )

    assert payload["status"] == "source_family_adapter_smoke_ready"
    assert payload["consumed_next_frontier_action"] == "smoke_mature_carrier_adapter_candidates"
    assert payload["parent_wave_id"] == "unit-adapter-smoke"
    assert payload["validation"]["passed"] is True


def test_source_family_adapter_smoke_uses_phase5_wave_next_frontier_when_latest_overwritten(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    phase5 = json.loads(
        (
            runtime / "state" / "source_family_mature_thin_bind_sunset" / "latest.json"
        ).read_text(encoding="utf-8")
    )
    phase5["next_frontier_machine_actions"] = {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "phase5_next_frontier_ready",
        "wave_id": "unit-phase5-sunset",
        "parent_wave_id": "unit-source-family-wave",
        "next_frontier": [{"action": "smoke_mature_carrier_adapter_candidates"}],
        "stop_allowed": False,
        "validation": {"passed": True},
        "not_execution_controller": True,
    }
    _write_json(runtime / "state" / "source_family_mature_thin_bind_sunset" / "latest.json", phase5)
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.wave2_mainchain_hygiene.v1.next_frontier_machine_actions.v1",
            "status": "next_frontier_ready",
            "wave_id": "unrelated-wave2-hygiene",
            "next_frontier": [{"action": "continue_source_frontier_claimcard_absorption"}],
            "stop_allowed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-adapter-smoke-overwritten-latest",
        probe_mode="synthetic",
        write=True,
    )

    assert payload["status"] == "source_family_adapter_smoke_ready"
    assert payload["parent_wave_id"] == "unit-phase5-sunset"
    assert payload["consumed_next_frontier_action"] == "smoke_mature_carrier_adapter_candidates"
    assert payload["input_refs"]["phase5_wave_specific_next_frontier_used"] is True
    assert payload["validation"]["passed"] is True
