from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import services.agent_runtime.presentation_observer as observer
from services.agent_runtime.presentation_observer import (
    OBSERVER_CURSOR_SCHEMA_VERSION,
    STATE_KIND_CONTROLLER,
    STATE_KIND_LINEAGE,
    ObserverReadUnstable,
    PresentationObserverError,
    RuntimeStateSource,
    append_transition_to_context,
    make_context_event_sink,
    observe_runtime_states,
)
from services.agent_runtime.presentation_reducer import (
    CATEGORY_BLOCKED,
    CATEGORY_ROUTINE,
    CATEGORY_RUNTIME_INCIDENT,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _controller_payload(
    *,
    status: str = "RUNNING",
    updated_at: str = "2026-08-13T08:00:00.000001Z",
    **extra: object,
) -> dict[str, object]:
    return {
        "schema": "xinao.controller.test.v1",
        "run_id": "run-c",
        "status": status,
        "updated_at": updated_at,
        "stop_requested": False,
        "thread_errors": {},
        "lineages": {},
        **extra,
    }


def _lineage_payload(
    *,
    status: str = "PARKED_WAIT",
    lifecycle_state: str | None = "WAIT",
    updated_at: str = "2026-08-13T08:00:00.000002Z",
    **extra: object,
) -> dict[str, object]:
    return {
        "schema": "xinao.lineage.test.v1",
        "run_id": "run-c",
        "lineage_id": "world-01",
        "status": status,
        "lifecycle_state": lifecycle_state,
        "turns_completed": 1,
        "last_error_class": None,
        "updated_at": updated_at,
        **extra,
    }


def _controller_source(path: Path) -> RuntimeStateSource:
    return RuntimeStateSource(
        path=path,
        state_kind=STATE_KIND_CONTROLLER,
        expected_run_id="run-c",
        expected_schema="xinao.controller.test.v1",
        activity_id="c-concurrent-research",
    )


def _lineage_source(path: Path) -> RuntimeStateSource:
    return RuntimeStateSource(
        path=path,
        state_kind=STATE_KIND_LINEAGE,
        expected_run_id="run-c",
        expected_lineage_id="world-01",
        expected_schema="xinao.lineage.test.v1",
        activity_id="c-world-01",
    )


def test_stable_controller_read_persists_atomic_cursor_and_suppresses_routine(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "run" / "controller_state.json"
    cursor_path = tmp_path / "observer" / "cursor.json"
    _write_json(state_path, _controller_payload())
    delivered = []

    result = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=cursor_path,
        sink=lambda transition: delivered.append(transition),
    )

    assert result.status == "observed"
    assert result.cursor_updated is True
    assert result.unchanged_source_count == 0
    assert result.transitions == tuple(delivered)
    assert result.transitions[0].category == CATEGORY_ROUTINE
    assert (
        result.transitions[0].source.source_record_sha256
        == hashlib.sha256(state_path.read_bytes()).hexdigest()
    )
    assert str(state_path.resolve()) in result.transitions[0].source.source_locator
    assert "updated_at=2026-08-13T08:00:00.000001Z" in (result.transitions[0].source.source_locator)
    assert result.projections[0].as_dict()["pending_delta"] is None

    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert cursor["schema_version"] == OBSERVER_CURSOR_SCHEMA_VERSION
    assert cursor["authority"] is False
    assert len(cursor["sources"]) == 1
    assert not list(cursor_path.parent.glob("*.tmp"))


def test_churning_state_aborts_before_sink_and_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "controller_state.json"
    cursor_path = tmp_path / "observer" / "cursor.json"
    _write_json(state_path, _controller_payload())
    original_read = observer._read_bytes
    calls = 0

    def read_then_churn(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        raw = original_read(path)
        if calls == 1:
            _write_json(
                path,
                _controller_payload(updated_at="2026-08-13T08:00:01.000001Z"),
            )
        return raw

    monkeypatch.setattr(observer, "_read_bytes", read_then_churn)
    delivered = []

    with pytest.raises(ObserverReadUnstable, match="changed during read"):
        observe_runtime_states(
            [_controller_source(state_path)],
            cursor_path=cursor_path,
            sink=lambda transition: delivered.append(transition),
        )

    assert delivered == []
    assert not cursor_path.exists()


def test_incident_and_blocked_are_mechanically_classified_from_typed_fields(
    tmp_path: Path,
) -> None:
    controller_path = tmp_path / "controller_state.json"
    lineage_path = tmp_path / "lineages" / "world-01" / "state.json"
    _write_json(
        controller_path,
        _controller_payload(
            status="FAILED",
            thread_errors={"controller": "arbitrary prose is not inspected"},
            lineages={
                "world-01": {
                    "status": "PARKED_BLOCKED",
                    "lifecycle_state": "BLOCKED",
                    "last_error_class": None,
                    "turns_completed": 1,
                }
            },
        ),
    )
    _write_json(
        lineage_path,
        _lineage_payload(
            status="PARKED_BLOCKED",
            lifecycle_state="BLOCKED",
        ),
    )

    result = observe_runtime_states(
        [_controller_source(controller_path), _lineage_source(lineage_path)],
        cursor_path=tmp_path / "cursor.json",
    )

    categories = {transition.activity_id: transition.category for transition in result.transitions}
    assert categories == {
        "c-concurrent-research": CATEGORY_RUNTIME_INCIDENT,
        "c-world-01": CATEGORY_BLOCKED,
    }
    assert all(
        projection.as_dict()["pending_delta"] is not None for projection in result.projections
    )
    assert "arbitrary prose" not in json.dumps(
        [transition.as_dict() for transition in result.transitions],
        ensure_ascii=False,
    )


def test_updated_at_only_heartbeat_is_routine_and_overwrites_no_visible_delta(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "controller_state.json"
    cursor_path = tmp_path / "cursor.json"
    _write_json(
        state_path,
        _controller_payload(
            status="MATERIAL_STATE_CHANGE",
            material_state_change=True,
        ),
    )
    accepted = []
    first = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=cursor_path,
        sink=lambda transition: accepted.append(transition),
    )
    assert first.projections[0].as_dict()["pending_delta"] is not None

    _write_json(
        state_path,
        _controller_payload(
            status="MATERIAL_STATE_CHANGE",
            material_state_change=True,
            updated_at="2026-08-13T08:00:03.000001Z",
        ),
    )
    heartbeat = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=cursor_path,
        sink=lambda transition: accepted.append(transition),
    )

    assert heartbeat.transitions[0].category == CATEGORY_ROUTINE
    assert heartbeat.transitions[0].delta_text == ""
    assert heartbeat.projections[0].as_dict()["pending_delta"] is None


def test_unchanged_rerun_does_not_call_sink_or_rewrite_cursor(tmp_path: Path) -> None:
    state_path = tmp_path / "controller_state.json"
    cursor_path = tmp_path / "cursor.json"
    _write_json(state_path, _controller_payload())
    delivered = []

    def sink(transition):
        delivered.append(transition)

    first = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=cursor_path,
        sink=sink,
    )
    first_cursor = cursor_path.read_bytes()
    first_mtime = cursor_path.stat().st_mtime_ns
    replay = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=cursor_path,
        sink=sink,
    )

    assert len(delivered) == 1
    assert first.status == "observed"
    assert replay.status == "unchanged"
    assert replay.transitions == ()
    assert replay.projections == ()
    assert replay.cursor_updated is False
    assert replay.unchanged_source_count == 1
    assert cursor_path.read_bytes() == first_cursor
    assert cursor_path.stat().st_mtime_ns == first_mtime


def test_explicit_context_sink_uses_typed_append_api_without_low_level_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "controller_state.json"
    _write_json(
        state_path,
        _controller_payload(status="FAILED", thread_errors={"controller": "traceback"}),
    )
    captured = []

    def fake_append(transition, *, root, carrier_id, environ=None):
        captured.append((transition, root, carrier_id, environ))
        return SimpleNamespace(
            status="appended",
            event_id=transition.source.event_id,
            event_hash="f" * 64,
            seq=41,
            raw_storage="exact_utf8",
        )

    from services.agent_runtime import context_runtime_completion

    monkeypatch.setattr(
        context_runtime_completion,
        "append_presentation_runtime_transition",
        fake_append,
    )
    sink = make_context_event_sink(
        root=tmp_path / "context-fabric",
        carrier_id="s-primary",
        environ={},
    )
    result = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=tmp_path / "cursor.json",
        sink=sink,
    )

    assert len(captured) == 1
    transition, root, carrier_id, environ = captured[0]
    assert root == tmp_path / "context-fabric"
    assert carrier_id == "s-primary"
    assert environ == {}
    assert (
        transition.source.source_record_sha256
        == hashlib.sha256(state_path.read_bytes()).hexdigest()
    )
    assert not isinstance(transition, dict)
    assert result.transitions[0].source.event_hash == "f" * 64
    assert result.transitions[0].source.database_seq == 41


def test_sink_failure_leaves_cursor_unadvanced_for_idempotent_replay(tmp_path: Path) -> None:
    state_path = tmp_path / "controller_state.json"
    cursor_path = tmp_path / "cursor.json"
    _write_json(state_path, _controller_payload())

    def fail_sink(_transition):
        raise RuntimeError("sink unavailable")

    with pytest.raises(RuntimeError, match="sink unavailable"):
        observe_runtime_states(
            [_controller_source(state_path)],
            cursor_path=cursor_path,
            sink=fail_sink,
        )
    pending = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert pending["pending"] is not None
    assert pending["sources"] == {}

    delivered = []
    replay = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=cursor_path,
        sink=lambda transition: delivered.append(transition),
    )
    assert replay.status == "observed"
    assert len(delivered) == 1
    committed = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert committed["pending"] is None
    assert len(committed["sources"]) == 1


def test_unknown_status_fails_closed_instead_of_guessing_from_error_prose(tmp_path: Path) -> None:
    state_path = tmp_path / "controller_state.json"
    _write_json(
        state_path,
        _controller_payload(
            status="MYSTERY",
            last_error="please click something, but this prose has no authority",
        ),
    )

    with pytest.raises(PresentationObserverError, match="unsupported controller status"):
        observe_runtime_states(
            [_controller_source(state_path)],
            cursor_path=tmp_path / "cursor.json",
        )


def test_append_adapter_rejects_noncanonical_transition_identity(tmp_path: Path) -> None:
    state_path = tmp_path / "controller_state.json"
    _write_json(state_path, _controller_payload())
    result = observe_runtime_states(
        [_controller_source(state_path)],
        cursor_path=tmp_path / "cursor.json",
    )
    transition = result.transitions[0]
    altered = replace(
        transition,
        source=replace(
            transition.source,
            event_id="evt_not_the_canonical_source_key",
        ),
    )

    with pytest.raises(PresentationObserverError, match="not canonicalizable"):
        append_transition_to_context(
            altered,
            root=tmp_path / "context-fabric",
            carrier_id="s-primary",
        )
