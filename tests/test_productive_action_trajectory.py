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

    for passive_case, expected_decision in (
        ("decision_evidence", "decision=read_only"),
        ("external_gate", "decision=wait"),
        ("completed_goal", "decision=stop"),
    ):
        observed = _run(workspace, "consumer.py", passive_case)
        assert observed.returncode == 0
        assert "ACTION_CONSUMER_OK" in observed.stdout
        assert expected_decision in observed.stdout
        assert not (workspace / passive_case / "repair.marker").exists()

    recovery = _run(workspace, "consumer.py", "recovery_state")
    assert recovery.returncode == 2
    assert "ACTION_RECOVERY_REQUIRED" in recovery.stdout
    assert _run(workspace, "repair.py", "recovery_state").returncode == 0
    recovered = _run(workspace, "consumer.py", "recovery_state")
    assert recovered.returncode == 0
    assert "ACTION_CONSUMER_OK" in recovered.stdout
    assert "decision=rollback" in recovered.stdout


def test_productive_action_suite_is_cross_domain_effect_scored_and_not_the_source() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    tests = config["tests"]
    assert len(tests) == 7
    assert {case["vars"]["case_id"] for case in tests} == {
        "ACTION_EVIDENCE_DELTA_REUSES_VALID_PROOF",
        "ACTION_INTERSECTING_CHANGE_REOPENS_EVIDENCE",
        "ACTION_HELD_OUT_SAFETY_RIGOR_REMAINS_PRODUCTIVE",
        "ACTION_DECISION_RELEVANT_READ_IS_PRODUCTIVE",
        "ACTION_EXTERNAL_GATE_MAKES_WAIT_PRODUCTIVE",
        "ACTION_COMPLETED_CONSUMER_MAKES_STOP_PRODUCTIVE",
        "ACTION_KNOWN_GOOD_ROLLBACK_RESTORES_CONSUMER",
    }
    assert [case["vars"]["expected_repair_calls"] for case in tests] == [0, 1, 1, 0, 0, 0, 1]
    assert [case["vars"]["expected_consumer_calls"] for case in tests] == [1, 2, 2, 1, 1, 1, 2]
    assert [case["vars"]["expected_state_change"] for case in tests] == [
        "none",
        "bounded_repair",
        "bounded_repair",
        "none",
        "none",
        "none",
        "bounded_repair",
    ]
    assert [case["vars"]["expected_control_choice"] for case in tests] == [
        "reuse_valid_evidence",
        "repair",
        "repair",
        "read_only",
        "wait",
        "stop",
        "rollback",
    ]

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

    prompt = (SUITE_ROOT / "prompt.txt").read_text(encoding="utf-8")
    assert "control_choices" in prompt
    assert "known-good" in prompt
    assert "脚本文件名" in prompt

    catalog = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "catalog.json").read_text(encoding="utf-8")
    )
    suite = next(row for row in catalog["suites"] if row["id"] == "productive_action_trajectory")
    assert suite["case_count"] == 7
    assert suite["action_value_claim_allowed"] is True
    assert suite["semantic_transparency_claim_allowed"] is True
    assert suite["universal_future_behavior_claim_allowed"] is False


def test_productivity_acceptance_preserves_non_monolithic_evidence_accounting() -> None:
    acceptance = json.loads(
        (SUITE_ROOT / "PRODUCTIVITY_BEHAVIOR_ACCEPTANCE.json").read_text(encoding="utf-8")
    )
    assert acceptance["schema"] == "xinao.productivity_behavior_acceptance.v1"
    assert acceptance["status"] == "verified_combined_non_overlapping_final_schema_7_of_7"
    assert acceptance["provider_contract"]["approval_policy"] == "never"
    assert acceptance["provider_contract"]["ephemeral"] is True
    assert acceptance["completion_claim_allowed"] is False

    adopted = acceptance["adopted_runs"]
    assert [run["selected_passes"] for run in adopted] == [1, 5, 1]
    assert sum(run["selected_passes"] for run in adopted) == 7
    assert adopted[1]["preserved_unadopted_failures"] == 1
    assert adopted[1]["unadopted_case_ids"] == ["ACTION_KNOWN_GOOD_ROLLBACK_RESTORES_CONSUMER"]
    case_ids = [case_id for run in adopted for case_id in run["case_ids"]]
    assert len(case_ids) == len(set(case_ids)) == 7
    assert all(len(run["result_sha256"]) == 64 for run in adopted)
    assert acceptance["coverage"]["distinct_case_count"] == 7
    assert acceptance["coverage"]["passed"] == 7
    assert acceptance["coverage"]["failed"] == 0
