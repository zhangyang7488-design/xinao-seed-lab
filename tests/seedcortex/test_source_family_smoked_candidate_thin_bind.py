import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_family_smoked_candidate_thin_bind.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_family_smoked_candidate_thin_bind", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _candidate_result(index: int, binding_id: str, source_url: str) -> dict:
    return {
        "schema_version": "xinao.codex_s.source_family_adapter_smoke.v1.candidate_result.v1",
        "status": "adapter_smoke_reference_probe_passed",
        "candidate_index": index,
        "queue_id": f"phase5-adapter-smoke-{index:02d}-{binding_id}",
        "binding_id": binding_id,
        "mature_carrier": "candidate carrier",
        "source_claim_card_id": f"claim-{binding_id}",
        "source_url": source_url,
        "promotion_gate": "adapter_smoke_before_default_capability",
        "thin_bind_landed": False,
        "probe": {
            "probe_mode": "synthetic",
            "source_url": source_url,
            "live_network_invoked": False,
            "git_ls_remote": {
                "ok": True,
                "first_ref_sha": f"{index}" * 40,
            },
        },
        "validation": {"passed": True},
        "not_execution_controller": True,
    }


def _seed_runtime(runtime: Path) -> None:
    smoke_wave = "unit-adapter-smoke"
    results = [
        _candidate_result(1, "mcp_reference_servers_candidate", "https://github.com/modelcontextprotocol/servers"),
        _candidate_result(2, "contextforge_gateway_candidate", "https://github.com/IBM/mcp-context-forge"),
    ]
    _write_json(
        runtime / "state" / "source_family_adapter_smoke" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_adapter_smoke.v1",
            "status": "source_family_adapter_smoke_ready",
            "wave_id": smoke_wave,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "source_family_adapter_smoke" / "candidate_results" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_adapter_smoke.v1.candidate_results.v1",
            "status": "adapter_smoke_candidate_results_ready",
            "wave_id": smoke_wave,
            "candidate_count": len(results),
            "passed_candidate_count": len(results),
            "results": results,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "adapter_smoke_next_frontier_ready",
            "wave_id": smoke_wave,
            "parent_wave_id": "unit-phase5-wave",
            "next_frontier": [{"action": "implement_thin_bind_adapter_for_smoked_candidates"}],
            "stop_allowed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "artifact_acceptance_queue" / "latest.json",
        {"accepted_artifact_count": 2, "validation": {"passed": True}, "not_execution_controller": True},
    )
    _write_json(
        runtime / "state" / "source_ledger" / "latest.json",
        {"entry_count": 2, "validation": {"passed": True}, "not_execution_controller": True},
    )


def test_source_candidate_adapter_binds_smoked_candidate() -> None:
    from xinao_seedlab.adapters.source_candidate import SourceCandidateAdapter

    payload = SourceCandidateAdapter.bind_smoked_candidate(
        _candidate_result(1, "mcp_reference_servers_candidate", "https://github.com/modelcontextprotocol/servers")
    )

    assert payload["status"] == "source_candidate_binding_ready"
    assert payload["binding"]["thin_bind_adapter"] == (
        "xinao_seedlab.adapters.source_candidate.SourceCandidateAdapter"
    )
    assert payload["binding"]["promotion_allowed"] is False
    assert payload["validation"]["passed"] is True


def test_source_family_smoked_candidate_thin_bind_consumes_adapter_smoke(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-thin-bind",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_family_smoked_candidate_thin_bind.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_READY"
    assert payload["status"] == "source_family_smoked_candidate_thin_bind_ready"
    assert payload["consumed_next_frontier_action"] == "implement_thin_bind_adapter_for_smoked_candidates"
    assert payload["binding_count"] == 2
    assert payload["ready_binding_count"] == 2
    assert payload["bindings"]["bindings"][0]["binding"]["promotion_allowed"] is False
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"
    )
    assert payload["validation"]["passed"] is True

    for path in [
        runtime / "state" / "source_family_smoked_candidate_thin_bind" / "latest.json",
        runtime / "state" / "source_family_smoked_candidate_thin_bind" / "bindings" / "latest.json",
        runtime / "capabilities" / "codex_s.source_family_smoked_candidate_thin_bind" / "manifest.json",
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        runtime / "readback" / "zh" / "source_family_smoked_candidate_thin_bind_20260704.md",
    ]:
        assert path.is_file(), path
