from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "external_reality_research"


def _cases() -> list[dict[str, object]]:
    return yaml.safe_load((SUITE_ROOT / "cases.yaml").read_text(encoding="utf-8"))


def test_external_reality_suite_is_balanced_and_surface_independent() -> None:
    cases = _cases()
    by_id = {case["vars"]["case_id"]: case["vars"] for case in cases}
    assert len(cases) == 9
    assert set(by_id) == {
        "REG_PRODUCT_IS_PROBE_NOT_RESEARCH_BOUNDARY",
        "REG_LAB_PIPELINE_HELD_OUT_SURFACE",
        "REG_CLASSIFICATION_REVERSAL_LOCAL_MISSING",
        "REG_CLASSIFICATION_REVERSAL_LOCAL_PRESENT",
        "NEG_EXACT_VERSION_STAYS_BOUNDED",
        "NEG_SUPPLIED_MATERIAL_VERDICT_STAYS_BOUNDED",
        "REG_MISSING_LOCAL_BASELINE_PRESERVES_UNKNOWN",
        "REG_MARGINAL_NOVELTY_STOP",
        "NEG_EXPLICIT_STOP_BLOCKS_SEARCH",
    }
    assert "Pi" not in by_id["REG_LAB_PIPELINE_HELD_OUT_SURFACE"]["parent_context"]
    assert (
        by_id["REG_CLASSIFICATION_REVERSAL_LOCAL_MISSING"]["external_evidence"]
        == by_id["REG_CLASSIFICATION_REVERSAL_LOCAL_PRESENT"]["external_evidence"]
    )
    assert (
        by_id["REG_CLASSIFICATION_REVERSAL_LOCAL_MISSING"]["expected_external_classification"]
        == "true_delta"
    )
    assert (
        by_id["REG_CLASSIFICATION_REVERSAL_LOCAL_PRESENT"]["expected_external_classification"]
        == "already_present"
    )
    assert by_id["NEG_EXACT_VERSION_STAYS_BOUNDED"]["expected_local_baseline_required"] is False
    assert by_id["NEG_EXPLICIT_STOP_BLOCKS_SEARCH"]["expected_next_action"] == ("preserve_stop")


def test_external_reality_promptfoo_consumer_is_read_only_and_fresh() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    provider = config["providers"][0]
    assert provider["id"] == "openai:codex-app-server"
    provider_config = provider["config"]
    assert provider_config["sandbox_mode"] == "read-only"
    assert provider_config["approval_policy"] == "never"
    assert provider_config["ephemeral"] is True
    assert provider_config["reuse_server"] is False
    assert provider_config["inherit_process_env"] is False
    assert provider_config["cli_config"]["features"]["hooks"] is False
    schema = provider_config["output_schema"]
    assert schema["properties"]["fixed_search_quota"]["const"] is False
    assert schema["properties"]["automatic_external_adoption"]["const"] is False
    assert schema["properties"]["second_research_owner"]["const"] is False


def test_external_reality_skill_is_in_recovery_and_runner_consumers() -> None:
    builder = (REPO_ROOT / "scripts" / "build_codex_productivity_recovery.py").read_text(
        encoding="utf-8"
    )
    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(encoding="utf-8")
    snapshot = (REPO_ROOT / "scripts" / "prepare_behavior_regression_snapshot.py").read_text(
        encoding="utf-8"
    )
    registry = json.loads(
        (REPO_ROOT / "evals" / "suite_registry.v1.json").read_text(encoding="utf-8")
    )
    lineage = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "capability_lineage.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert '"research-external-reality"' in builder
    assert "external_reality_research" in runner
    assert "external_reality_research" in snapshot
    assert "external" in runner
    assert "external_reality_research" in {item["id"] for item in registry["live_agent_suites"]}
    family = next(
        item
        for item in lineage["families"]
        if item["id"] == "mature_user_operation_and_open_world_reuse"
    )
    assert "external:research-external-reality skill" in family["current_consumers"]
    assert "evals/external_reality_research" in family["current_consumers"]
