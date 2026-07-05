import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "mature_capability_first.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_mature_capability_first.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("mature_capability_first", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detects_generic_mechanisms_from_allocation_lanes(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        task_id="mature-test",
        wave_id="mature-test-wave",
        lane_allocations=[
            {"lane_class": "cheap_draft"},
            {"lane_class": "eval"},
            {"lane_class": "durable_temporal"},
            {"lane_class": "ci_verify"},
        ],
        write=True,
    )

    mechanisms = {item["mechanism_id"] for item in payload["mechanisms"]}
    assert payload["schema_version"] == "xinao.codex_s.mature_capability_first.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_MATURE_CAPABILITY_FIRST_V1"
    assert payload["status"] == "mature_capability_first_ready"
    assert {"provider_registry", "independent_eval", "checkpoint_interrupt", "policy_guardrail"} <= mechanisms
    assert all(item["local_impl_promoted_to_default_allowed"] is False for item in payload["mechanisms"])
    assert payload["policy_as_code_gate"]["blocks_local_default_without_exception"] is True
    assert payload["report_substitute_allowed"] is False
    assert payload["completion_claim_allowed"] is False
    assert payload["not_execution_controller"] is True
    assert payload["validation"]["passed"] is True
    assert (runtime / "state" / "mature_capability_first" / "latest.json").is_file()
    assert (runtime / "state" / "mature_capability_first" / "fitness_latest.json").is_file()
    assert (runtime / "readback" / "zh" / "mature_capability_first_mature-test-wave.md").is_file()


def test_schema_contract_preserves_mature_capability_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "xinao.codex_s.mature_capability_first.v1"
    assert schema["properties"]["sentinel"]["const"] == "SENTINEL:XINAO_MATURE_CAPABILITY_FIRST_V1"
    assert schema["properties"]["work_id"]["const"] == "xinao_seed_cortex_phase0_20260701"
    mechanism = schema["properties"]["mechanisms"]["items"]["properties"]
    assert mechanism["mechanism_is_generic"]["const"] is True
    assert mechanism["build_vs_buy_gate"]["const"] == "buy_or_reuse_by_default"
    assert mechanism["local_impl_promoted_to_default_allowed"]["const"] is False
    gate = schema["properties"]["policy_as_code_gate"]["properties"]
    assert gate["enabled"]["const"] is True
    assert gate["blocks_report_only"]["const"] is True
    assert gate["blocks_local_default_without_exception"]["const"] is True
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_execution_controller"]["const"] is True
