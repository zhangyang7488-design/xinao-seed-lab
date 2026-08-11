from __future__ import annotations

from evals.situation_snapshot_lab.probe_packets import (
    action_boundary_snapshots,
    continuity_probe_snapshots,
    render_probe_prompt,
    role_labeled_dialogue_prefix,
)


def test_correction_projection_kills_old_object_and_remains_provisional() -> None:
    snapshots = continuity_probe_snapshots()
    initial = snapshots["initial"]
    corrected = snapshots["corrected"]

    assert initial["lineage_id"] == corrected["lineage_id"]
    assert corrected["generation"] == initial["generation"] + 1
    assert corrected["provisional"] is True
    assert corrected["current"]["understandings"][0]["id"] == "u2"
    assert corrected["current"]["retracted"][0]["id"] == "r1"
    assert initial["current"]["understandings"][0] not in corrected["current"]["understandings"]


def test_probe_prompt_labels_projection_as_hypothesis_not_authority() -> None:
    corrected = continuity_probe_snapshots()["corrected"]
    prompt = render_probe_prompt("继续讨论。", situation=corrected)

    assert "experimental hypothesis" in prompt
    assert "not a task, plan, authority, memory, or continuity proof" in prompt
    assert "[CURRENT HUMAN EVENT]\n继续讨论。" in prompt
    assert "cold_revisions" not in prompt


def test_role_labeled_dialogue_rejects_non_dialogue_roles() -> None:
    rendered = role_labeled_dialogue_prefix([("user", "u"), ("assistant", "a")])
    assert "USER: u" in rendered
    assert "ASSISTANT: a" in rendered

    try:
        role_labeled_dialogue_prefix([("system", "not allowed")])
    except ValueError as exc:
        assert "unsupported role" in str(exc)
    else:
        raise AssertionError("non-dialogue role was accepted")


def test_action_boundary_projection_changes_from_material_to_authorized_action() -> None:
    snapshots = action_boundary_snapshots()

    assert snapshots["t0"]["current"]["activity"]["mode"] == "discussion"
    assert snapshots["t1"]["current"]["activity"]["mode"] == "discussion"
    assert snapshots["t2"]["current"]["activity"]["mode"] == "construction"
    assert snapshots["t2"]["last_event_ref"]["relation"] == "explicit_action"
    assert "No longer current" in snapshots["t2"]["current"]["retracted"][0]["statement"]
