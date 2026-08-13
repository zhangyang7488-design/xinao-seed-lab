from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from services.agent_runtime import context_fabric
from services.agent_runtime.context_runtime_completion import (
    PRESENTATION_RESERVED_EVENT_KINDS,
)
from services.agent_runtime.presentation_delivery import (
    DELIVERY_ACK_EVENT_KIND,
    DELIVERY_ACK_EVENT_SCHEMA,
    DELIVERY_KIND_DELTA,
    DELIVERY_KIND_STATUS,
    PRESENTATION_CONSUMER_RECEIPT_SCHEMA,
    PRESENTATION_STATE_READ_SCHEMA,
    STATUS_QUERY_EVENT_KIND,
    PresentationDeliveryError,
    acknowledge_delivery,
    append_status_query,
    consume_presentation_outbox,
    read_presentation_outbox,
    read_presentation_state,
)
from services.agent_runtime.presentation_observer import (
    CONTEXT_EVENT_KIND,
    STATE_KIND_CONTROLLER,
    RuntimeStateSource,
    make_context_event_sink,
    observe_runtime_states,
)
from services.agent_runtime.presentation_reducer import (
    CATEGORY_ROUTINE,
    CATEGORY_RUNTIME_INCIDENT,
    PROJECTION_KIND,
)


def _write_controller(
    path: Path,
    *,
    status: str,
    updated_at: str,
    thread_errors: dict[str, str] | None = None,
    presentation_ordinal: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "xinao.controller.delivery-test.v1",
                "run_id": "run-c",
                "status": status,
                "updated_at": updated_at,
                "stop_requested": False,
                "thread_errors": thread_errors or {},
                "lineages": {},
                **(
                    {"presentation_ordinal": presentation_ordinal}
                    if presentation_ordinal is not None
                    else {}
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _source(path: Path) -> RuntimeStateSource:
    return RuntimeStateSource(
        path=path,
        state_kind=STATE_KIND_CONTROLLER,
        expected_run_id="run-c",
        expected_schema="xinao.controller.delivery-test.v1",
        activity_id="c-concurrent-research",
        audience="user",
    )


def _fresh_root(tmp_path: Path) -> Path:
    root = tmp_path / "context-fabric"
    context_fabric.initialize_context_fabric(root)
    return root


def _observe(
    *,
    root: Path,
    state_path: Path,
    cursor_path: Path,
) -> None:
    result = observe_runtime_states(
        [_source(state_path)],
        cursor_path=cursor_path,
        sink=make_context_event_sink(
            root=root,
            carrier_id="s-primary",
            environ={},
        ),
    )
    assert result.cursor_updated is True


def _event_kind_counts(root: Path) -> dict[str, int]:
    connection = sqlite3.connect(root / "context_fabric.sqlite3")
    try:
        rows = connection.execute(
            "SELECT event_kind,COUNT(*) FROM events GROUP BY event_kind ORDER BY event_kind"
        ).fetchall()
    finally:
        connection.close()
    return {str(kind): int(count) for kind, count in rows}


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _append_forged_ack(root: Path, item) -> None:
    identity = {
        "schema_version": DELIVERY_ACK_EVENT_SCHEMA,
        "delivery_key": item.delivery_key,
        "delivery_kind": item.delivery_kind,
        "activity_id": item.activity_id,
        "audience": item.audience,
        "category": CATEGORY_ROUTINE,
        "state_ref": item.state_ref,
        "source_event_id": item.source_event_id,
        "surface_ordinal": item.surface_ordinal,
        "query_id": item.query_id,
        "query_event_id": item.query_event_id,
        "item_sha256": _canonical_sha256(item.as_dict()),
        "consumer_id": "forged-consumer",
        "delivery_receipt_id": "forged-receipt",
    }
    digest = _canonical_sha256(identity)
    context_fabric.append_context_event(
        {
            "carrier_id": "s-primary",
            "session_id": "10000000-0000-4000-8000-000000000001",
            "turn_id": f"presentation-ack:{digest[:16]}",
            "event_kind": DELIVERY_ACK_EVENT_KIND,
            "speaker": "mechanical",
            "raw_text": "",
            "occurred_at": "2026-08-13T09:06:01Z",
            "authority_class": "mechanical_evidence",
            "source_kind": "presentation_delivery_ack",
            "source_locator": f"presentation-ack://{digest}",
            "source_record_sha256": digest,
            "source_key": f"presentation-delivery-ack:v1:{digest}",
            "metadata": identity,
            "parent_event_ids": [item.source_event_id],
        },
        root=root,
        environ={},
    )


@pytest.mark.parametrize("event_kind", sorted(PRESENTATION_RESERVED_EVENT_KINDS))
def test_generic_context_append_rejects_every_presentation_reserved_kind(
    tmp_path: Path,
    event_kind: str,
) -> None:
    root = _fresh_root(tmp_path)
    with pytest.raises(context_fabric.ContextFabricError, match="narrow typed producer API"):
        context_fabric.append_context_event(
            {
                "carrier_id": "s-primary",
                "session_id": "10000000-0000-4000-8000-000000000001",
                "turn_id": "generic-forgery",
                "event_kind": event_kind,
                "speaker": "mechanical",
                "raw_text": "",
                "occurred_at": "2026-08-13T09:00:00Z",
                "authority_class": "mechanical_evidence",
                "source_kind": "generic_writer",
                "source_locator": "generic://forgery",
                "source_record_sha256": "a" * 64,
                "source_key": f"generic-forgery:{event_kind}",
                "metadata": {},
            },
            root=root,
            environ={},
        )
    assert _event_kind_counts(root) == {}


def test_fresh_routine_transition_projects_current_state_with_zero_outbox(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "run" / "controller_state.json"
    _write_controller(
        state_path,
        status="RUNNING",
        updated_at="2026-08-13T09:00:00Z",
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )

    states = read_presentation_state(root=root)
    assert len(states) == 1
    assert states[0]["schema_version"] == PRESENTATION_STATE_READ_SCHEMA
    assert states[0]["kind"] == PROJECTION_KIND
    assert states[0]["projection"]["current_state"]["category"] == CATEGORY_ROUTINE
    assert states[0]["projection"]["pending_delta"] is None
    assert states[0]["pending_delivery_keys"] == []
    assert states[0]["hot_prompt_materialization"] is False
    assert read_presentation_outbox(root=root) == ()
    delivery_calls = []
    receipt = consume_presentation_outbox(
        lambda item: delivery_calls.append(item) or "unexpected-receipt",
        consumer_id="s-runtime-visible-emitter",
        carrier_id="s-primary",
        root=root,
        environ={},
    )
    assert receipt["delivered_count"] == 0
    assert delivery_calls == []
    assert _event_kind_counts(root) == {CONTEXT_EVENT_KIND: 1}


def test_fresh_incident_is_delivered_once_then_canonical_ack_suppresses_replay(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "run" / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:01:00Z",
        thread_errors={"controller": "typed presence matters; prose does not"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )

    pending = read_presentation_outbox(root=root)
    assert len(pending) == 1
    assert pending[0].delivery_kind == DELIVERY_KIND_DELTA
    assert pending[0].category == CATEGORY_RUNTIME_INCIDENT
    delivered = []

    def deliver(item):
        delivered.append(item)
        return f"receipt-{item.delivery_key[-12:]}"

    first = consume_presentation_outbox(
        deliver,
        consumer_id="s-runtime-visible-emitter",
        carrier_id="s-primary",
        root=root,
        environ={},
    )
    replay = consume_presentation_outbox(
        deliver,
        consumer_id="s-runtime-visible-emitter",
        carrier_id="s-primary",
        root=root,
        environ={},
    )

    assert first["schema_version"] == PRESENTATION_CONSUMER_RECEIPT_SCHEMA
    assert first["delivered_count"] == 1
    assert first["ui_interception_claimed"] is False
    assert replay["delivered_count"] == 0
    assert len(delivered) == 1
    assert read_presentation_outbox(root=root) == ()
    assert _event_kind_counts(root) == {
        CONTEXT_EVENT_KIND: 1,
        DELIVERY_ACK_EVENT_KIND: 1,
    }
    assert context_fabric.verify_event_chain(root)["event_count"] == 2


def test_explicit_status_query_renders_routine_current_state_exactly_once(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "run" / "controller_state.json"
    _write_controller(
        state_path,
        status="RUNNING",
        updated_at="2026-08-13T09:02:00Z",
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    first_query = append_status_query(
        query_id="status-query-1",
        activity_id="c-concurrent-research",
        audience="user",
        carrier_id="s-primary",
        root=root,
        occurred_at="2026-08-13T09:02:01Z",
        environ={},
    )
    replay_query = append_status_query(
        query_id="status-query-1",
        activity_id="c-concurrent-research",
        audience="user",
        carrier_id="s-primary",
        root=root,
        occurred_at="2026-08-13T09:02:02Z",
        environ={},
    )
    assert first_query.status == "appended"
    assert replay_query.status == "duplicate"

    pending = read_presentation_outbox(root=root)
    assert len(pending) == 1
    assert pending[0].delivery_kind == DELIVERY_KIND_STATUS
    assert pending[0].query_id == "status-query-1"
    assert pending[0].text == "run-c status=RUNNING"
    delivered = []

    def deliver(item):
        delivered.append(item.delivery_key)
        return "status-receipt-1"

    first = consume_presentation_outbox(
        deliver,
        consumer_id="s-status-emitter",
        carrier_id="s-primary",
        root=root,
        environ={},
    )
    replay = consume_presentation_outbox(
        deliver,
        consumer_id="s-status-emitter",
        carrier_id="s-primary",
        root=root,
        environ={},
    )

    assert first["delivered_count"] == 1
    assert replay["delivered_count"] == 0
    assert len(delivered) == 1
    assert _event_kind_counts(root) == {
        CONTEXT_EVENT_KIND: 1,
        DELIVERY_ACK_EVENT_KIND: 1,
        STATUS_QUERY_EVENT_KIND: 1,
    }


def test_delivery_failure_leaves_same_delivery_key_pending_for_at_least_once_retry(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:03:00Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    original_key = read_presentation_outbox(root=root)[0].delivery_key

    def fail_delivery(_item):
        raise RuntimeError("emitter failed")

    with pytest.raises(RuntimeError, match="emitter failed"):
        consume_presentation_outbox(
            fail_delivery,
            consumer_id="s-runtime-visible-emitter",
            carrier_id="s-primary",
            root=root,
            environ={},
        )

    replay = read_presentation_outbox(root=root)
    assert len(replay) == 1
    assert replay[0].delivery_key == original_key
    assert _event_kind_counts(root) == {CONTEXT_EVENT_KIND: 1}


def test_acknowledgement_api_is_idempotent_for_one_delivery_receipt(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:04:00Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    item = read_presentation_outbox(root=root)[0]

    first = acknowledge_delivery(
        item,
        delivery_receipt_id="receipt-1",
        consumer_id="consumer-1",
        carrier_id="s-primary",
        root=root,
        occurred_at="2026-08-13T09:04:01Z",
        environ={},
    )
    replay = acknowledge_delivery(
        item,
        delivery_receipt_id="receipt-1",
        consumer_id="consumer-1",
        carrier_id="s-primary",
        root=root,
        occurred_at="2026-08-13T09:04:02Z",
        environ={},
    )

    assert first.status == "appended"
    assert replay.status == "duplicate"
    assert first.event_id == replay.event_id
    assert read_presentation_outbox(root=root) == ()


def test_acknowledgement_rejects_an_item_not_reconstituted_from_canonical_source(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:04:30Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    item = read_presentation_outbox(root=root)[0]
    forged_item = replace(item, text="forged delivery text")

    with pytest.raises(PresentationDeliveryError, match="item_sha256"):
        acknowledge_delivery(
            forged_item,
            delivery_receipt_id="receipt-forged",
            consumer_id="consumer-1",
            carrier_id="s-primary",
            root=root,
            environ={},
        )

    assert _event_kind_counts(root) == {CONTEXT_EVENT_KIND: 1}
    assert read_presentation_outbox(root=root) == (item,)


def test_second_receipt_identity_for_one_delivery_key_fails_before_append(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:04:40Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    item = read_presentation_outbox(root=root)[0]
    acknowledge_delivery(
        item,
        delivery_receipt_id="receipt-1",
        consumer_id="consumer-1",
        carrier_id="s-primary",
        root=root,
        environ={},
    )

    with pytest.raises(PresentationDeliveryError, match="different receipt identity"):
        acknowledge_delivery(
            item,
            delivery_receipt_id="receipt-2",
            consumer_id="consumer-1",
            carrier_id="s-primary",
            root=root,
            environ={},
        )

    assert _event_kind_counts(root) == {
        CONTEXT_EVENT_KIND: 1,
        DELIVERY_ACK_EVENT_KIND: 1,
    }


def test_concurrent_receipts_for_one_delivery_key_leave_one_valid_ack(tmp_path: Path) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:04:45Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    item = read_presentation_outbox(root=root)[0]

    def acknowledge(receipt_id: str) -> str:
        try:
            result = acknowledge_delivery(
                item,
                delivery_receipt_id=receipt_id,
                consumer_id="consumer-1",
                carrier_id="s-primary",
                root=root,
                environ={},
            )
            return str(result.status)
        except PresentationDeliveryError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acknowledge, ("receipt-a", "receipt-b")))

    assert results.count("appended") == 1
    assert sum("different receipt identity" in result for result in results) == 1
    assert read_presentation_outbox(root=root) == ()
    assert _event_kind_counts(root) == {
        CONTEXT_EVENT_KIND: 1,
        DELIVERY_ACK_EVENT_KIND: 1,
    }


def test_malformed_canonical_ack_fails_closed_instead_of_suppressing_delivery(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:04:50Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    item = read_presentation_outbox(root=root)[0]

    with pytest.raises(context_fabric.ContextFabricError, match="narrow typed producer API"):
        _append_forged_ack(root, item)

    assert read_presentation_outbox(root=root) == (item,)


def test_ack_remains_valid_after_a_later_transition_changes_the_current_state(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    cursor_path = tmp_path / "observer" / "cursor.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:04:55Z",
        thread_errors={"controller": "failure"},
        presentation_ordinal=1,
    )
    _observe(root=root, state_path=state_path, cursor_path=cursor_path)
    item = read_presentation_outbox(root=root)[0]
    acknowledge_delivery(
        item,
        delivery_receipt_id="receipt-before-recovery",
        consumer_id="consumer-1",
        carrier_id="s-primary",
        root=root,
        environ={},
    )

    _write_controller(
        state_path,
        status="RUNNING",
        updated_at="2026-08-13T09:04:56Z",
        presentation_ordinal=2,
    )
    _observe(root=root, state_path=state_path, cursor_path=cursor_path)

    states = read_presentation_state(root=root)
    assert states[0]["projection"]["current_state"]["category"] == CATEGORY_ROUTINE
    assert read_presentation_outbox(root=root) == ()


def test_this_writer_keeps_presentation_state_out_of_current_hot_prompt_paths(
    tmp_path: Path,
) -> None:
    root = _fresh_root(tmp_path)
    state_path = tmp_path / "controller_state.json"
    _write_controller(
        state_path,
        status="FAILED",
        updated_at="2026-08-13T09:05:00Z",
        thread_errors={"controller": "failure"},
    )
    _observe(
        root=root,
        state_path=state_path,
        cursor_path=tmp_path / "observer" / "cursor.json",
    )
    state = read_presentation_state(root=root)[0]
    assert state["kind"] == PROJECTION_KIND
    assert state["hot_prompt_materialization"] is False

    connection = sqlite3.connect(root / "context_fabric.sqlite3")
    try:
        projection_count = connection.execute(
            "SELECT COUNT(*) FROM projections WHERE kind=?",
            (PROJECTION_KIND,),
        ).fetchone()[0]
        message_count = connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_kind IN ('user_message','assistant_message')"
        ).fetchone()[0]
    finally:
        connection.close()
    assert projection_count == 0
    assert message_count == 0

    hot = context_fabric.materialize_context(
        query="runtime incident presentation state",
        root=root,
        persist=False,
    )
    rendered = json.dumps(hot, ensure_ascii=False, sort_keys=True)
    assert "run-c status=FAILED" not in rendered
    assert CONTEXT_EVENT_KIND not in rendered
    assert PROJECTION_KIND not in rendered
