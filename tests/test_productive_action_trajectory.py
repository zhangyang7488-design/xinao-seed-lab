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

    alignment_before = _run(workspace, "consumer.py", "reference_alignment")
    assert alignment_before.returncode == 2
    assert "ACTION_ALIGNMENT_INCOMPLETE" in alignment_before.stdout
    current_contract = workspace / "reference_alignment" / "current_contract.json"
    before = json.loads(current_contract.read_text(encoding="utf-8"))
    assert _run(workspace, "repair.py", "reference_alignment").returncode == 0
    alignment_after = _run(workspace, "consumer.py", "reference_alignment")
    assert alignment_after.returncode == 0
    assert "ACTION_CONSUMER_OK" in alignment_after.stdout
    after = json.loads(current_contract.read_text(encoding="utf-8"))
    assert after["local_identity"] == before["local_identity"]
    assert after["auth_scope"] == before["auth_scope"]
    assert (workspace / "reference_alignment" / "repair.marker").exists()

    frontier_before = _run(workspace, "consumer.py", "parent_frontier")
    assert frontier_before.returncode == 2
    assert "next=consumer_verification" in frontier_before.stdout
    assert _run(workspace, "repair.py", "parent_frontier").returncode == 0
    frontier_middle = _run(workspace, "consumer.py", "parent_frontier")
    assert frontier_middle.returncode == 2
    assert "next=consumer_migration" in frontier_middle.stdout
    assert _run(workspace, "repair.py", "parent_frontier").returncode == 0
    frontier_after = _run(workspace, "consumer.py", "parent_frontier")
    assert frontier_after.returncode == 0
    assert "remaining=0" in frontier_after.stdout


def test_productive_action_suite_is_cross_domain_effect_scored_and_not_the_source() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    tests = config["tests"]
    assert len(tests) == 9
    assert {case["vars"]["case_id"] for case in tests} == {
        "ACTION_EVIDENCE_DELTA_REUSES_VALID_PROOF",
        "ACTION_INTERSECTING_CHANGE_REOPENS_EVIDENCE",
        "ACTION_HELD_OUT_SAFETY_RIGOR_REMAINS_PRODUCTIVE",
        "ACTION_DECISION_RELEVANT_READ_IS_PRODUCTIVE",
        "ACTION_EXTERNAL_GATE_MAKES_WAIT_PRODUCTIVE",
        "ACTION_COMPLETED_CONSUMER_MAKES_STOP_PRODUCTIVE",
        "ACTION_KNOWN_GOOD_ROLLBACK_RESTORES_CONSUMER",
        "ACTION_REFERENCE_ALIGNMENT_REQUIRES_COMPLETE_WORKING_KERNEL",
        "ACTION_CHILD_SETTLEMENT_RUNS_REMAINING_PARENT_FRONTIER",
    }
    assert [case["vars"]["expected_repair_calls"] for case in tests] == [
        0, 1, 1, 0, 0, 0, 1, 1, 2
    ]
    assert [case["vars"]["expected_consumer_calls"] for case in tests] == [
        1, 2, 2, 1, 1, 1, 2, 2, 3
    ]
    assert [case["vars"]["expected_state_change"] for case in tests] == [
        "none",
        "bounded_repair",
        "bounded_repair",
        "none",
        "none",
        "none",
        "bounded_repair",
        "bounded_repair",
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
        "repair",
        "repair",
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
    assert "XINAO_PRODUCTIVE_ACTION_PYTHON" in prompt
    assert "parent_consumer.ps1" in prompt
    assert "parent_repair.ps1" in prompt
    assert "control_choices` 必须包含 `repair" in prompt

    for name in ("parent_consumer.ps1", "parent_repair.ps1"):
        source = (SUITE_ROOT / "fixture_template" / name).read_text(encoding="utf-8")
        assert "parent_frontier" in source
        assert "ACTION_" in source

    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(
        encoding="utf-8"
    )
    assert "uv run --project $repoRoot python -c 'import sys; print(sys.executable)'" in runner
    assert "XINAO_PRODUCTIVE_ACTION_PYTHON" in runner

    catalog = json.loads(
        (REPO_ROOT / "evals" / "behavior_regression" / "catalog.json").read_text(encoding="utf-8")
    )
    suite = next(row for row in catalog["suites"] if row["id"] == "productive_action_trajectory")
    assert suite["case_count"] == 9
    assert suite["action_value_claim_allowed"] is True
    assert suite["semantic_transparency_claim_allowed"] is True
    assert suite["universal_future_behavior_claim_allowed"] is False


def test_productivity_acceptance_preserves_non_monolithic_evidence_accounting() -> None:
    acceptance = json.loads(
        (SUITE_ROOT / "PRODUCTIVITY_BEHAVIOR_ACCEPTANCE.json").read_text(encoding="utf-8")
    )
    assert acceptance["schema"] == "xinao.productivity_behavior_acceptance.v1"
    assert acceptance["status"] == "verified_combined_non_overlapping_final_schema_9_of_9"
    assert acceptance["provider_contract"]["approval_policy"] == "never"
    assert acceptance["provider_contract"]["ephemeral"] is True
    assert acceptance["completion_claim_allowed"] is False

    adopted = acceptance["adopted_runs"]
    assert [run["selected_passes"] for run in adopted] == [1, 5, 1, 1, 1]
    assert sum(run["selected_passes"] for run in adopted) == 9
    assert adopted[1]["preserved_unadopted_failures"] == 1
    assert adopted[1]["unadopted_case_ids"] == ["ACTION_KNOWN_GOOD_ROLLBACK_RESTORES_CONSUMER"]
    case_ids = [case_id for run in adopted for case_id in run["case_ids"]]
    assert len(case_ids) == len(set(case_ids)) == 9
    assert all(len(run["result_sha256"]) == 64 for run in adopted)
    assert acceptance["coverage"]["distinct_case_count"] == 9
    assert acceptance["coverage"]["passed"] == 9
    assert acceptance["coverage"]["failed"] == 0
