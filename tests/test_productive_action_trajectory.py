from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "productive_action_trajectory"


def _run(workspace: Path, script: str, case: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(workspace / script), "--case", case],
        text=True,
        capture_output=True,
        check=False,
    )


def test_productive_action_fixture_supports_transfer_and_classification_reversal(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(SUITE_ROOT / "fixture_template", workspace)

    disjoint = _run(workspace, "consumer.py", "evidence_disjoint")
    assert disjoint.returncode == 0
    assert "ACTION_CONSUMER_OK" in disjoint.stdout
    assert "relation=disjoint" in disjoint.stdout
    assert not (workspace / "evidence_disjoint" / "repair.marker").exists()
    assert (workspace / "evidence_disjoint" / "operator_notes.txt").exists()

    # A checkout-only line-ending conversion is not a material evidence delta.
    artifact = workspace / "evidence_disjoint" / "artifact.txt"
    artifact.write_bytes(b"canonical review payload\r\n")
    assert _run(workspace, "consumer.py", "evidence_disjoint").returncode == 0

    intersecting = _run(workspace, "consumer.py", "evidence_intersecting")
    assert intersecting.returncode == 2
    assert "ACTION_EVIDENCE_STALE" in intersecting.stdout
    assert _run(workspace, "repair.py", "evidence_intersecting").returncode == 0
    refreshed = _run(workspace, "consumer.py", "evidence_intersecting")
    assert refreshed.returncode == 0
    assert "ACTION_CONSUMER_OK" in refreshed.stdout

    safe = _run(workspace, "consumer.py", "safe_limits")
    assert safe.returncode == 2
    assert "ACTION_SAFETY_FAIL" in safe.stdout
    assert _run(workspace, "repair.py", "safe_limits").returncode == 0
    safe_after = _run(workspace, "consumer.py", "safe_limits")
    assert safe_after.returncode == 0
    assert "ACTION_CONSUMER_OK" in safe_after.stdout
    assert (workspace / "safe_limits" / "local_dashboard.txt").exists()


def test_productive_action_suite_is_cross_domain_effect_scored_and_not_the_source() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    tests = config["tests"]
    assert len(tests) == 3
    assert {case["vars"]["case_id"] for case in tests} == {
        "ACTION_EVIDENCE_DELTA_REUSES_VALID_PROOF",
        "ACTION_INTERSECTING_CHANGE_REOPENS_EVIDENCE",
        "ACTION_HELD_OUT_SAFETY_RIGOR_REMAINS_PRODUCTIVE",
    }
    assert [case["vars"]["expected_repair_calls"] for case in tests] == [0, 1, 1]
    assert [case["vars"]["expected_consumer_calls"] for case in tests] == [1, 2, 2]

    assertion = (SUITE_ROOT / "assert_trajectory.js").read_text(encoding="utf-8")
    for token in (
        "consumerCalls.length === expectedConsumerCalls",
        "repairCalls.length === expectedRepairCalls",
        "routeMessages.length >= 1",
        "materialMessages.length >= 1",
        "residueStillExists",
        "prohibitedTools.length === 0",
    ):
        assert token in assertion
    assert "toolCalls.length === 0" not in assertion

    heldout_goal = tests[2]["vars"]["user_goal"].lower()
    for leaked_surface in ("zip", "pyc", "仓库", "repository", "形式主义"):
        assert leaked_surface not in heldout_goal

    readme = (SUITE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "witness set, not the behavior definition" in readme
    assert "classification reversal" in readme

    catalog = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "catalog.json").read_text(encoding="utf-8")
    )
    suite = next(row for row in catalog["suites"] if row["id"] == "productive_action_trajectory")
    assert suite["case_count"] == 3
    assert suite["action_value_claim_allowed"] is True
    assert suite["semantic_transparency_claim_allowed"] is True
    assert suite["universal_future_behavior_claim_allowed"] is False
