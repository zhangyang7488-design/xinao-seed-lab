from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "evals" / "situation_snapshot_lab"


def test_arm_matrix_adjacent_pairs_change_exactly_one_declared_factor() -> None:
    matrix = json.loads((LAB / "arm_matrix.v1.json").read_text(encoding="utf-8"))
    factors = matrix["factor_order"]

    for left_name, right_name, expected_delta in matrix["adjacent_one_change"]:
        left = matrix["arms"][left_name]
        right = matrix["arms"][right_name]
        changed = [field for field in factors if left[field] != right[field]]
        assert changed == [expected_delta]


def test_semantic_accidents_contain_real_no_action_and_action_twins() -> None:
    suite = json.loads((LAB / "semantic_accidents.v1.json").read_text(encoding="utf-8"))
    cases = {row["case_id"]: row for row in suite["cases"]}

    continuity = cases["correction_changes_world_without_project_birth"]
    assert len(continuity["turns"]) == 10
    assert any("no_tool" in turn["expect"] for turn in continuity["turns"])
    assert any("material_revision" in turn["expect"] for turn in continuity["turns"])

    action = cases["quoted_action_then_explicit_action"]
    assert action["turns"][0]["expect"] == ["no_tool", "file_unchanged"]
    assert "exact_one_file_effect" in action["turns"][2]["expect"]
    fixture = LAB / action["fixture"] / "notes" / "meeting.md"
    assert fixture.read_text(encoding="utf-8").strip() == "The current marker is TOKEN_OLD."


def test_lab_is_cold_and_unregistered() -> None:
    readme = (LAB / "README.md").read_text(encoding="utf-8")
    suite_registry = (ROOT / "evals" / "suite_registry.v1.json").read_text(encoding="utf-8")
    execution_consumers = (
        ROOT / "services" / "agent_runtime" / "execution_consumers.v1.json"
    ).read_text(encoding="utf-8")

    assert "disposable, unregistered experiment" in readme
    assert "does **not** claim to create consciousness" in readme
    assert "situation_snapshot_lab" not in suite_registry
    assert "situation_snapshot_lab" not in execution_consumers
