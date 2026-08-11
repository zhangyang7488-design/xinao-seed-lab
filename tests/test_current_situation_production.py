from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from services.agent_runtime.current_situation import (
    CURRENT_SITUATION_VERSION,
    TRANSITION_VERSION,
    CurrentSituationConflict,
    CurrentSituationError,
    apply_transition,
    build_snapshot,
    initialize_store,
    load_current,
    render_hot_context,
    validate_current,
)


def _event(event_id: str, relation: str = "discussion") -> dict[str, str]:
    return {
        "event_id": event_id,
        "event_sha256": hashlib.sha256(event_id.encode()).hexdigest(),
        "relation": relation,
    }


def _current(*, statement: str = "We are discussing the continuity problem.", event_id: str = "event-0") -> dict[str, object]:
    return {
        "activity": {"mode": "discussion", "description": "Understand the whole continuity problem."},
        "human_relation": {
            "description": "The user is correcting the current Codex's understanding.",
            "user_need_not_repeat": "The whole continuity problem and why task-first routing is painful.",
        },
        "object": {"description": "The missing continuing knower relation, not a state-management product."},
        "open_relations": [
            {"id": "o1", "source_event_id": event_id, "statement": "A snapshot may be necessary but insufficient."}
        ],
        "retracted": [],
        "understandings": [
            {"id": "u1", "source_event_id": event_id, "statement": statement}
        ],
    }


def _snapshot() -> dict[str, object]:
    return build_snapshot(
        lineage_id="lab-lineage-1",
        generation=0,
        last_event_ref=_event("event-0"),
        current=_current(),
    )


def _correction_transition(snapshot: dict[str, object]) -> dict[str, object]:
    event = _event("event-1", "correction")
    next_current = _current(
        statement="We are testing a narrow continuity prosthesis, not manufacturing consciousness.",
        event_id="event-1",
    )
    next_current["activity"] = {
        "mode": "construction",
        "description": "Build and test the narrow continuity prosthesis without pre-claiming subjecthood.",
    }
    next_current["human_relation"] = {
        "description": "The user narrowed what success may legitimately mean.",
        "user_need_not_repeat": "The distinction between improved continuity phenotype and human-like subjecthood.",
    }
    next_current["object"] = {
        "description": "Whether missing external conditions cause most observed fragmentation."
    }
    return {
        "schema_version": TRANSITION_VERSION,
        "materiality": "MATERIAL_REVISION",
        "expected_generation": snapshot["generation"],
        "expected_projection_sha256": snapshot["projection_sha256"],
        "event_ref": event,
        "field_dispositions": [
            {"field": "activity", "disposition": "replace"},
            {"field": "human_relation", "disposition": "replace"},
            {"field": "object", "disposition": "replace"},
        ],
        "item_dispositions": [
            {"item_ref": "open_relations:o1", "disposition": "replace", "replacement_ref": "open_relations:o1-new"},
            {"item_ref": "understandings:u1", "disposition": "replace", "replacement_ref": "understandings:u2"},
        ],
        "next_current": {
            **next_current,
            "open_relations": [
                {"id": "o1-new", "source_event_id": "event-1", "statement": "Correct state may still feel like a new reader of a handoff."}
            ],
            "retracted": [
                {"id": "r1", "source_event_id": "event-1", "statement": "No longer held: the target is merely a state-management product."}
            ],
            "understandings": [
                {"id": "u2", "source_event_id": "event-1", "statement": "We are testing a narrow continuity prosthesis, not manufacturing consciousness."}
            ],
        },
    }


def test_initialize_and_load_round_trip(tmp_path: Path) -> None:
    snapshot = _snapshot()
    initialize_store(tmp_path, snapshot)

    loaded = load_current(tmp_path)

    assert loaded == snapshot
    assert loaded["schema_version"] == CURRENT_SITUATION_VERSION


def test_correction_replaces_hot_world_and_keeps_preimage_only_cold(tmp_path: Path) -> None:
    before = _snapshot()
    initialize_store(tmp_path, before)

    result = apply_transition(tmp_path, _correction_transition(before))
    after = load_current(tmp_path)
    hot = render_hot_context(after)
    cold = json.loads(Path(result["cold_revision_receipt"]).read_text(encoding="utf-8"))

    assert result["persisted"] is True
    assert after["generation"] == 1
    assert after["provisional"] is True
    assert "manufacturing consciousness" in hot
    assert "We are discussing the continuity problem" not in hot
    assert after["current"]["understandings"][0]["id"] == "u2"
    assert after["current"]["retracted"][0]["id"] == "r1"
    assert cold["before_projection"] == before
    assert cold["after_projection"] == after
    assert "cold_revisions" not in hot
    assert "before_projection" not in hot


def test_no_material_change_does_not_persist_or_create_cold_history(tmp_path: Path) -> None:
    snapshot = _snapshot()
    current_path = initialize_store(tmp_path, snapshot)
    before_bytes = current_path.read_bytes()
    lock_path = tmp_path / ".current.lock"
    before_lock_mtime = lock_path.stat().st_mtime_ns
    transition = {
        "schema_version": TRANSITION_VERSION,
        "materiality": "NO_MATERIAL_CHANGE",
        "expected_generation": 0,
        "expected_projection_sha256": snapshot["projection_sha256"],
        "event_ref": _event("event-small", "enrichment"),
        "field_dispositions": [],
        "item_dispositions": [],
    }

    result = apply_transition(tmp_path, transition)

    assert result["persisted"] is False
    assert current_path.read_bytes() == before_bytes
    assert lock_path.stat().st_mtime_ns == before_lock_mtime
    assert not (tmp_path / "cold_revisions").exists()


def test_stale_transition_is_rejected_by_generation_and_hash(tmp_path: Path) -> None:
    snapshot = _snapshot()
    initialize_store(tmp_path, snapshot)
    transition = _correction_transition(snapshot)
    apply_transition(tmp_path, transition)

    with pytest.raises(CurrentSituationConflict, match="stale"):
        apply_transition(tmp_path, transition)


def test_concurrent_material_revisions_have_one_winner(tmp_path: Path) -> None:
    snapshot = _snapshot()
    initialize_store(tmp_path, snapshot)
    transition = _correction_transition(snapshot)

    def attempt() -> str:
        try:
            apply_transition(tmp_path, transition)
        except CurrentSituationConflict:
            return "conflict"
        return "persisted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(lambda _: attempt(), range(2)))

    assert results == ["conflict", "persisted"]
    assert load_current(tmp_path)["generation"] == 1
    assert len(list((tmp_path / "cold_revisions").glob("*.json"))) == 1


def test_material_revision_cannot_silently_drop_prior_current_item(tmp_path: Path) -> None:
    snapshot = _snapshot()
    transition = _correction_transition(snapshot)
    transition["item_dispositions"] = transition["item_dispositions"][1:]

    initialize_store(tmp_path, snapshot)
    with pytest.raises(CurrentSituationError, match="every prior current item"):
        apply_transition(tmp_path, transition)


def test_strict_projection_schema_rejects_task_controller_fields() -> None:
    current = _current()
    current["next_action"] = "Implement the system."

    with pytest.raises(CurrentSituationError, match="extra=.*next_action"):
        validate_current(current)


def test_current_collections_are_bounded() -> None:
    current = _current()
    current["understandings"] = [
        {
            "id": f"u{index:02d}",
            "source_event_id": "event-0",
            "statement": "bounded",
        }
        for index in range(33)
    ]

    with pytest.raises(CurrentSituationError, match="exceeds 32 items"):
        validate_current(current)


def test_hot_renderer_has_no_task_plan_authority_worker_or_completion_state() -> None:
    rendered = render_hot_context(_snapshot())
    parsed = json.loads(rendered)

    assert set(parsed["current"]) == {
        "activity",
        "human_relation",
        "object",
        "open_relations",
        "retracted",
        "understandings",
    }
    forbidden = {"next_task", "next_action", "goal", "plan", "authority", "worker", "completion"}
    assert forbidden.isdisjoint(rendered.lower())
