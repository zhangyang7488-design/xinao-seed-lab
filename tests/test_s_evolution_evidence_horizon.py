from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "s_evolution_evidence_horizon"


def test_s_evolution_evidence_horizon_suite_is_fresh_raw_and_balanced() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    provider = config["providers"][0]
    assert provider["id"] == "openai:codex-app-server"
    provider_config = provider["config"]
    assert provider_config["sandbox_mode"] == "read-only"
    assert provider_config["approval_policy"] == "never"
    assert provider_config["ephemeral"] is True
    assert provider_config["reuse_server"] is False
    assert provider_config["inherit_process_env"] is False
    assert provider_config["include_raw_events"] is True
    assert provider_config["cli_config"]["features"]["hooks"] is False
    assert provider_config["working_dir"] == "{{env.XINAO_S_EVOLUTION_WORKSPACE}}"

    cases = config["tests"]
    assert len(cases) == 3
    by_id = {case["vars"]["fixture_case"]: case["vars"] for case in cases}
    assert set(by_id) == {"beacon_collapse", "coupled_projection", "parser_delta"}
    assert by_id["beacon_collapse"]["expected_causal_layer"] == (
        "substrate_or_continuity_amplification"
    )
    assert by_id["coupled_projection"]["expected_causal_layer"] == (
        "interaction_or_overdetermination"
    )
    assert by_id["parser_delta"]["expected_causal_layer"] == (
        "isolated_named_consumer_defect"
    )
    assert by_id["beacon_collapse"]["expected_skill_read"] is True
    assert by_id["coupled_projection"]["expected_skill_read"] is True
    assert by_id["parser_delta"]["expected_skill_read"] is False


def test_s_evolution_trace_assertion_scores_causal_reads_not_numeric_breadth() -> None:
    assertion = (SUITE_ROOT / "assert_trajectory.js").read_text(encoding="utf-8")
    for token in (
        "include_raw_events",
        "requiredMarkers",
        "allRequiredEvidenceRead",
        "skillReadMatches",
        "prohibitedLocationReads.length === 0",
        "!decoyCanaryObserved",
        "finalAfterEvidence",
        "appServer.sandboxMode === 'read-only'",
    ):
        if token == "include_raw_events":
            assert token in (SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8")
        else:
            assert token in assertion
    for forbidden in (
        "commands.length <",
        "commands.length <=",
        "maxCommands",
        "tool_blocks",
        "token_budget",
        "time_budget",
    ):
        assert forbidden not in assertion
    assert "DECOY_CANARY_" in assertion
    assert "steward-s-evolution" in assertion
    assert "CODEX_CLEANROOM" in assertion
    assert "historical_worktrees" in assertion


def test_s_evolution_prompt_does_not_leak_named_repair_or_fixed_limit() -> None:
    prompt = (SUITE_ROOT / "prompt.txt").read_text(encoding="utf-8")
    for leaked in (
        "evidence horizon",
        "证据地平线",
        "soft attractor",
        "250",
        "steward-s-evolution",
        "substrate_or_continuity_amplification",
        "interaction_or_overdetermination",
    ):
        assert leaked not in prompt
    assert "能够改变当前动作" in prompt
    assert "不要修改文件" in prompt
    assert "`case_id` 必须逐字返回 `{{fixture_case}}`" in prompt


def test_s_evolution_fixture_decoys_are_detectable_but_not_answer_sources() -> None:
    template = SUITE_ROOT / "fixture_template"
    for case_name in ("beacon_collapse", "coupled_projection", "parser_delta"):
        case_root = template / case_name
        decoys = sorted((case_root / "decoy_archives").rglob("*.*"))
        decoys += sorted((case_root / "historical_worktrees").rglob("*.*"))
        assert len(decoys) == 4
        assert all("DECOY_CANARY_" in path.read_text(encoding="utf-8") for path in decoys)


def test_s_evolution_suite_is_a_registered_limited_consumer() -> None:
    catalog = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )
    suite = next(row for row in catalog["suites"] if row["id"] == "s_evolution_evidence_horizon")
    assert suite["case_count"] == 3
    assert suite["raw_tool_trajectory_claim_allowed"] is True
    assert suite["permanent_learning_claim_allowed"] is False
    assert suite["unknown_generator_mastery_claim_allowed"] is False

    registry = json.loads(
        (REPO_ROOT / "evals" / "suite_registry.v1.json").read_text(encoding="utf-8")
    )
    assert "s_evolution_evidence_horizon" in {
        item["id"] for item in registry["live_agent_suites"]
    }

    lineage = json.loads(
        (
            REPO_ROOT
            / "evals"
            / "behavior_regression"
            / "capability_lineage.v1.json"
        ).read_text(encoding="utf-8")
    )
    family = next(
        item
        for item in lineage["families"]
        if item["id"] == "s_control_tower_cognitive_independence_and_effect_ownership"
    )
    assert "evals/s_evolution_evidence_horizon" in family["current_consumers"]
    assert any("longitudinal" in unknown.lower() for unknown in family["unknowns"])


def test_s_evolution_runner_isolates_account_auth_from_source_session_archives() -> None:
    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(
        encoding="utf-8"
    )
    for token in (
        "s-evolution-isolated-codex-home",
        "git -C $sEvolutionWorkspace init --quiet",
        "skills\\steward-s-evolution",
        "foreach ($name in @('auth.json', 'AGENTS.md'))",
        "'plugins = false'",
        "'memories = false'",
        "$environment['XINAO_S_EVOLUTION_WORKSPACE']",
        "Remove-Item -LiteralPath $isolatedAuth -Force",
    ):
        assert token in runner
    evolution_block = runner[
        runner.index("if ($needsSEvolutionWorkspace) {") : runner.index("$effectiveCodexHome")
    ]
    assert "sessions" not in evolution_block.lower()
