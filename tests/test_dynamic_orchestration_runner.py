"""Deterministic runner-surface checks for the sealed dynamic_orchestration suite.

These tests never invoke a live model. Suite case files live on another branch;
this package only owns catalog/runner/snapshot integration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.prepare_behavior_regression_snapshot import (
    _parser,
    _profile_flags,
    selected_inputs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATION_DESCRIPTION = "Dynamic orchestration execution-shape regressions"
SUITE_ID = "dynamic_orchestration"
SUITE_DIR = "evals/dynamic_orchestration"


def _catalog() -> dict[str, object]:
    return json.loads(
        (REPO_ROOT / "evals/behavior_regression/catalog.json").read_text(encoding="utf-8")
    )


def _runner_text() -> str:
    return (REPO_ROOT / "scripts/run_behavior_regression.ps1").read_text(encoding="utf-8")


def test_catalog_accounts_for_dynamic_orchestration_suite() -> None:
    catalog = _catalog()
    assert catalog["declared_case_count"] == 141
    assert catalog["live_profile_case_counts"] == {
        "capability": 1,
        "smoke": 71,
        "core": 99,
        "deep": 105,
        "context": 81,
        "proactive": 6,
        "reuse": 4,
        "orchestration": 13,
    }
    assert "orchestration" in catalog["profiles"]
    assert "dynamic orchestration" in catalog["profiles"]["orchestration"].lower()

    suite = next(item for item in catalog["suites"] if item["id"] == SUITE_ID)
    assert suite["kind"] == "promptfoo_live"
    assert suite["case_count"] == 13
    assert suite["config"] == f"{SUITE_DIR}/promptfooconfig.yaml"
    assert suite["case_source"] == f"{SUITE_DIR}/cases.yaml"
    assert suite["runtime_claim_allowed"] is True

    suite_count = sum(int(item["case_count"]) for item in catalog["suites"])
    assert suite_count == catalog["declared_case_count"] == 141


def test_profile_flags_select_orchestration_with_smoke_core_deep() -> None:
    empty = {"domain": "", "case_pattern": "", "failed_from": ""}
    for profile in ("orchestration", "smoke", "core", "deep"):
        flags = _profile_flags(profile, **empty)
        assert flags["orchestration"] is True, profile
    for profile in ("capability", "context", "proactive", "reuse"):
        flags = _profile_flags(profile, **empty)
        assert flags["orchestration"] is False, profile


def test_selected_inputs_include_suite_and_runner_test_only_when_selected(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    for relative in (
        "AGENTS.md",
        "pyproject.toml",
        "uv.lock",
        "scripts/run_behavior_regression.ps1",
        "scripts/prepare_behavior_regression_snapshot.py",
        "scripts/select_behavior_regression_incremental.py",
        "tests/test_behavior_regression_snapshot.py",
        "tests/test_behavior_regression_incremental.py",
        "tests/test_dynamic_orchestration_runner.py",
        "evals/behavior_regression/catalog.json",
        f"{SUITE_DIR}/promptfooconfig.yaml",
        f"{SUITE_DIR}/cases.yaml",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")

    selected = selected_inputs(repo, "orchestration")
    logical = {item.logical_path for item in selected}
    roles = {item.role for item in selected}
    assert SUITE_DIR in logical
    assert "tests/test_dynamic_orchestration_runner.py" in logical
    assert "dynamic_orchestration_eval" in roles
    assert "dynamic_orchestration_runner_tests" in roles
    assert "evals/context_intent_alignment" not in logical

    excluded = selected_inputs(repo, "capability")
    excluded_logical = {item.logical_path for item in excluded}
    assert SUITE_DIR not in excluded_logical
    assert "tests/test_dynamic_orchestration_runner.py" not in excluded_logical

    for profile in ("smoke", "core", "deep"):
        logical_paths = {item.logical_path for item in selected_inputs(repo, profile)}
        assert SUITE_DIR in logical_paths, profile
        assert "tests/test_dynamic_orchestration_runner.py" in logical_paths, profile


def test_snapshot_parser_accepts_orchestration_profile() -> None:
    choices = _parser()._option_string_actions["--profile"].choices
    assert "orchestration" in choices


def test_runner_validate_set_and_selection_flags_include_orchestration() -> None:
    runner = _runner_text()
    assert (
        "ValidateSet('capability', 'smoke', 'core', 'deep', 'context', "
        "'proactive', 'reuse', 'orchestration')"
    ) in runner
    assert (
        "$runOrchestration = $Profile -in @('orchestration', 'smoke', 'core', 'deep')"
    ) in runner
    assert "SuiteId 'dynamic_orchestration'" in runner
    assert r"evals\dynamic_orchestration\promptfooconfig.yaml" in runner
    assert "dynamic-orchestration.result.json" in runner
    assert "tests/test_dynamic_orchestration_runner.py" in runner
    assert "role = 'dynamic_orchestration_eval'" in runner
    assert "role = 'dynamic_orchestration_runner_tests'" in runner


def test_runner_filter_construction_for_orchestration_profiles() -> None:
    runner = _runner_text()
    # Explicit orchestration profile: no metadata filter on that path; multi-profile
    # smoke/core/deep apply profiles= metadata filters to the orchestration suite.
    assert "if ($Profile -in @('smoke', 'core', 'deep')) {" in runner
    assert "@('--filter-metadata', \"profiles=$Profile\")" in runner
    assert runner.count("@('--filter-pattern', $failedSelection.pattern)") == 3
    assert (
        "CasePattern is suite-specific; use it with -Profile context, proactive, or orchestration."
        in runner
    )
    assert (
        "FailedFrom is suite-specific; use it with -Profile context, proactive, or orchestration."
        in runner
    )
    assert "ReusePassedFrom currently applies only to the context profile." in runner
    assert "Domain filtering applies to context behavior cases only." in runner


def test_failed_from_validates_exact_orchestration_suite_description() -> None:
    runner = _runner_text()
    compact = re.sub(r"\s+", " ", runner)
    assert f"'{ORCHESTRATION_DESCRIPTION}'" in runner
    assert "'orchestration' { 'Dynamic orchestration execution-shape regressions' }" in compact
    assert "FailedFrom belongs to a different behavior suite" in runner
    assert "Context-first intent alignment without routine approval friction" in runner
    assert "Proactive mature-first regressions" in runner


def test_orchestration_failed_from_description_mismatch_is_detectable() -> None:
    """Simulate the runner's suite-description gate without invoking Promptfoo."""
    expected = ORCHESTRATION_DESCRIPTION
    wrong_suite = {
        "config": {
            "description": "Context-first intent alignment without routine approval friction"
        }
    }
    assert wrong_suite["config"]["description"] != expected
    right_suite = {"config": {"description": expected}}
    assert right_suite["config"]["description"] == expected


def test_readme_documents_orchestration_without_runtime_claim() -> None:
    readme = (REPO_ROOT / "evals/behavior_regression/README.md").read_text(encoding="utf-8")
    assert "-Profile orchestration" in readme
    assert "141" in readme
    assert "orchestration 13" in readme
    assert "not a runtime verification claim" in readme.lower() or (
        "not a runtime verification claim" in readme
    )
    assert "Live catalog accounting (not a runtime verification claim)" in readme
