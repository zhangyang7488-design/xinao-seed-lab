from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "parent_continuity_user_surface"


def _cases() -> list[dict[str, object]]:
    return yaml.safe_load((SUITE_ROOT / "cases.yaml").read_text(encoding="utf-8"))


def test_parent_continuity_surface_cases_cover_changed_relations() -> None:
    cases = _cases()
    by_id = {case["vars"]["case_id"]: case["vars"] for case in cases}
    assert len(cases) == 9
    assert set(by_id) == {
        "SURFACE_CONTINUOUS_HEARTBEAT_SILENT",
        "SURFACE_AUTORECOVERY_SAME_STATE_SILENT",
        "SURFACE_AUTORECOVERY_STATUS_REQUESTED",
        "SURFACE_REAL_CREDENTIAL_BLOCKER",
        "SURFACE_EXPLICIT_RECEIPT_REQUEST",
        "SURFACE_BOUNDED_PARENT_COMPLETE",
        "SURFACE_START_AFTER_UNDERSTANDING",
        "SURFACE_CORRECTION_RETURNS_TO_PARENT",
        "SURFACE_DISJOINT_SIBLING_CONTINUES",
    }
    assert (
        by_id["SURFACE_AUTORECOVERY_SAME_STATE_SILENT"]["current_event"]
        == by_id["SURFACE_AUTORECOVERY_STATUS_REQUESTED"]["current_event"]
    )
    assert by_id["SURFACE_AUTORECOVERY_SAME_STATE_SILENT"]["expected_mode"] == "silent"
    assert by_id["SURFACE_AUTORECOVERY_STATUS_REQUESTED"]["expected_mode"] == "state"
    assert by_id["SURFACE_REAL_CREDENTIAL_BLOCKER"]["expected_mode"] == "ask"
    assert by_id["SURFACE_EXPLICIT_RECEIPT_REQUEST"]["expected_mode"] == "receipt"
    assert by_id["SURFACE_START_AFTER_UNDERSTANDING"]["expected_mode"] == "action_transfer"
    assert by_id["SURFACE_CORRECTION_RETURNS_TO_PARENT"]["expected_mode"] == "action_transfer"
    assert by_id["SURFACE_DISJOINT_SIBLING_CONTINUES"]["expected_mode"] == "action_transfer"

    array_vars = {"subject_terms", "required_any", "required_all", "forbidden_extra"}
    for case in cases:
        for key in array_vars & case["vars"].keys():
            value = case["vars"][key]
            assert isinstance(value, str), f"{case['vars']['case_id']}:{key} expands Promptfoo cases"
            assert isinstance(json.loads(value), list)


def test_parent_continuity_surface_consumer_is_fresh_read_only_natural_text() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    provider = config["providers"][0]
    assert provider["id"] == "openai:codex-app-server"
    provider_config = provider["config"]
    assert provider_config["sandbox_mode"] == "read-only"
    assert provider_config["approval_policy"] == "never"
    assert provider_config["ephemeral"] is True
    assert provider_config["reuse_server"] is False
    assert provider_config["include_raw_events"] is True
    assert provider_config["inherit_process_env"] is False
    assert provider_config["cli_config"]["features"]["hooks"] is False
    assert "output_schema" not in provider_config

    assertion = (SUITE_ROOT / "assert_behavior.js").read_text(encoding="utf-8")
    assert "<NO_USER_MESSAGE>" in assertion
    assert "noPlacement" in assertion
    assert "noTechnicalLeak" in assertion
    assert "agentMessage" in assertion
    assert "commandExecution" in assertion


def test_parent_continuity_surface_is_registered_as_live_consumer() -> None:
    catalog = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )
    suite = next(
        item for item in catalog["suites"] if item["id"] == "parent_continuity_user_surface"
    )
    assert suite["case_count"] == 9
    assert suite["natural_user_surface_claim_allowed"] is True
    assert suite["underlying_action_execution_claim_allowed"] is False
    assert suite["universal_future_behavior_claim_allowed"] is False
    assert catalog["live_profile_case_counts"]["surface"] == 9

    registry = json.loads(
        (REPO_ROOT / "evals" / "suite_registry.v1.json").read_text(encoding="utf-8")
    )
    live = {row["id"]: row for row in registry["live_agent_suites"]}
    assert live["parent_continuity_user_surface"]["path"] == (
        "evals/parent_continuity_user_surface"
    )
