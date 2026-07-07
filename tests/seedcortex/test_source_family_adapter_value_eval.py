import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_family_adapter_value_eval.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_family_adapter_value_eval", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _binding(index: int, binding_id: str, source_url: str) -> dict:
    return {
        "schema_version": "xinao.seedcortex.source_candidate_binding.v1",
        "status": "source_candidate_binding_ready",
        "binding": {
            "binding_id": binding_id,
            "source_url": source_url,
            "source_claim_card_id": f"claim-{binding_id}",
            "mature_carrier": "candidate carrier",
            "first_ref_sha": f"{index}" * 40,
            "adapter_kind": "source_family_smoked_candidate_reference",
            "thin_bind_adapter": "xinao_seedlab.adapters.source_candidate.SourceCandidateAdapter",
            "promotion_allowed": False,
            "promotion_gate": "adapter_value_eval_before_default_capability",
            "not_execution_controller": True,
        },
        "validation": {"passed": True},
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def _seed_runtime(runtime: Path) -> None:
    thin_wave = "unit-thin-bind"
    bindings = [
        _binding(1, "mcp_reference_servers_candidate", "https://github.com/modelcontextprotocol/servers"),
        _binding(2, "contextforge_gateway_candidate", "https://github.com/IBM/mcp-context-forge"),
    ]
    _write_json(
        runtime / "state" / "source_family_smoked_candidate_thin_bind" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_smoked_candidate_thin_bind.v1",
            "status": "source_family_smoked_candidate_thin_bind_ready",
            "wave_id": thin_wave,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "source_family_smoked_candidate_thin_bind" / "bindings" / "latest.json",
        {
            "schema_version": "xinao.codex_s.source_family_smoked_candidate_thin_bind.v1.bindings.v1",
            "status": "smoked_candidate_thin_bindings_ready",
            "wave_id": thin_wave,
            "binding_count": len(bindings),
            "ready_binding_count": len(bindings),
            "bindings": bindings,
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        },
    )
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "smoked_candidate_thin_bind_next_frontier_ready",
            "wave_id": thin_wave,
            "parent_wave_id": "unit-adapter-smoke",
            "next_frontier": [
                {"action": "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"}
            ],
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


def test_source_family_adapter_value_eval_consumes_thin_bind(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-value-eval",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.source_family_adapter_value_eval.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_READY"
    assert payload["status"] == "source_family_adapter_value_eval_ready"
    assert payload["consumed_next_frontier_action"] == (
        "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"
    )
    assert payload["decision_count"] == 2
    assert payload["gateway_candidate_count"] == 2
    assert payload["capability_gateway_candidates"]["provider"]["provider_invocation_performed"] is False
    assert payload["capability_gateway_candidates"]["provider"]["default_capability_promotion_allowed"] is False
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "refresh_capability_gateway_snapshot_with_evaluated_source_candidates"
    )
    assert payload["validation"]["passed"] is True

    for path in [
        runtime / "state" / "source_family_adapter_value_eval" / "latest.json",
        runtime / "state" / "source_family_adapter_value_eval" / "decisions" / "latest.json",
        runtime / "state" / "source_family_adapter_value_eval" / "capability_gateway_candidates" / "latest.json",
        runtime / "capabilities" / "codex_s.source_family_adapter_value_eval" / "manifest.json",
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        runtime / "readback" / "zh" / "source_family_adapter_value_eval_20260704.md",
    ]:
        assert path.is_file(), path


def test_value_eval_service_refreshes_capability_gateway_candidate_provider(tmp_path: Path) -> None:
    from xinao_seedlab.application.seed_cortex import build_default_service

    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    service = build_default_service(runtime, repo_root=REPO_ROOT)

    payload = service.source_family_adapter_value_eval(
        wave_id="unit-value-eval-service",
        write_runtime=True,
    )
    gateway = json.loads(
        (runtime / "state" / "capability_gateway" / "latest.json").read_text(encoding="utf-8")
    )

    assert payload["validation"]["passed"] is True
    assert payload["capability_gateway_snapshot"]["source_family_adapter_candidate_provider_visible"] is True
    assert payload["gateway_refresh"]["validation"]["passed"] is True
    assert payload["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "monitor_temporal_source_family_adapter_value_eval_activity"
    )
    assert "codex_s.source_family_smoked_candidate_adapter_candidates" in gateway["provider_ids"]
    assert (
        runtime / "state" / "source_family_adapter_value_eval" / "gateway_refresh" / "latest.json"
    ).is_file()
    provider = next(
        item
        for item in gateway["providers"]
        if item["provider_id"] == "codex_s.source_family_smoked_candidate_adapter_candidates"
    )
    assert provider["candidate_count"] == 2
    assert provider["default_capability_promotion_allowed"] is False


def test_value_eval_temporal_monitor_consumes_wave_specific_activity(tmp_path: Path) -> None:
    from xinao_seedlab.application.seed_cortex import build_default_service

    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    service = build_default_service(runtime, repo_root=REPO_ROOT)
    activity_payload = service.source_family_adapter_value_eval(
        wave_id="unit-value-eval-temporal-activity",
        write_runtime=True,
    )
    activity_payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_family_adapter_value_eval_activity",
        "invoked": True,
        "not_execution_controller": True,
    }
    activity_latest = runtime / "state" / "source_family_adapter_value_eval" / "temporal_activity_latest.json"
    activity_wave = (
        runtime
        / "state"
        / "source_family_adapter_value_eval"
        / "temporal_activity"
        / "waves"
        / f"{activity_payload['wave_id']}.json"
    )
    _write_json(activity_latest, activity_payload)
    _write_json(activity_wave, activity_payload)

    monitor = service.source_family_adapter_value_eval_temporal_monitor(
        wave_id="unit-value-eval-temporal-monitor",
        write_runtime=True,
    )

    assert monitor["status"] == "source_family_adapter_value_eval_temporal_monitor_ready"
    assert monitor["consumed_next_frontier_action"] == (
        "monitor_temporal_source_family_adapter_value_eval_activity"
    )
    assert monitor["validation"]["passed"] is True
    assert monitor["input_refs"]["temporal_activity_wave"]["exists"] is True
    assert monitor["input_refs"]["gateway_refresh_wave"]["exists"] is True
    assert monitor["next_frontier_machine_actions"]["next_frontier"][0]["action"] == (
        "continue_default_temporal_chain_after_source_family_adapter_value_eval_monitor"
    )


def test_value_eval_uses_thin_bind_wave_next_frontier_when_latest_overwritten(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_runtime(runtime)
    thin_bind_path = runtime / "state" / "source_family_smoked_candidate_thin_bind" / "latest.json"
    thin_bind = json.loads(thin_bind_path.read_text(encoding="utf-8"))
    thin_bind["next_frontier_machine_actions"] = {
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
    }
    _write_json(thin_bind_path, thin_bind)
    _write_json(
        runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        {
            "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
            "status": "next_frontier_machine_actions_ready",
            "wave_id": "unrelated-source-family",
            "next_frontier": [{"action": "enter_phase5_mature_thin_bind_sunset"}],
            "stop_allowed": False,
            "validation": {"passed": True},
            "not_execution_controller": True,
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="unit-value-eval-overwritten-latest",
        write=True,
    )

    assert payload["status"] == "source_family_adapter_value_eval_ready"
    assert payload["parent_wave_id"] == "unit-thin-bind"
    assert payload["consumed_next_frontier_action"] == (
        "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"
    )
    assert payload["input_refs"]["thin_bind_wave_specific_next_frontier_used"] is True
    assert payload["validation"]["passed"] is True
