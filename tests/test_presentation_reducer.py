from __future__ import annotations

import json

import pytest
from services.agent_runtime.presentation_reducer import (
    CATEGORY_BLOCKED,
    CATEGORY_MAJOR_RESULT,
    CATEGORY_MATERIAL,
    CATEGORY_NEEDS_USER,
    CATEGORY_ROUTINE,
    CATEGORY_RUNTIME_INCIDENT,
    PROJECTION_KIND,
    PROJECTION_SCHEMA_VERSION,
    PresentationSourceRef,
    RuntimeTransition,
    StatusQuery,
    reduce_presentation,
)


def _source(
    event_id: str,
    *,
    ordinal: int,
    phase: str = "runtime_transition",
    database_seq: int | None = None,
) -> PresentationSourceRef:
    digest_seed = sum(event_id.encode("utf-8"))
    return PresentationSourceRef(
        event_id=event_id,
        event_hash=f"{digest_seed:064x}",
        source_kind="rollout_jsonl",
        source_locator=f"rollout://session-a#{ordinal}",
        source_record_sha256=f"{ordinal + 1:064x}",
        rollout_ordinal=ordinal,
        phase=phase,
        database_seq=database_seq,
    )


def _transition(
    event_id: str,
    *,
    ordinal: int,
    category: str,
    state_ref: str,
    status_text: str,
    delta_text: str = "",
    phase: str = "runtime_transition",
    database_seq: int | None = None,
    recovered_to_same_state: bool = False,
    activity_id: str = "c-concurrent-research",
    audience: str = "user",
) -> RuntimeTransition:
    return RuntimeTransition(
        activity_id=activity_id,
        audience=audience,
        category=category,
        state_ref=state_ref,
        status_text=status_text,
        delta_text=delta_text,
        recovered_to_same_state=recovered_to_same_state,
        source=_source(
            event_id,
            ordinal=ordinal,
            phase=phase,
            database_seq=database_seq,
        ),
    )


def test_latest_visible_transition_is_the_only_pending_delta_per_scope() -> None:
    projections = reduce_presentation(
        [
            _transition(
                "evt_material",
                ordinal=10,
                category=CATEGORY_MATERIAL,
                state_ref="running-v2",
                status_text="C concurrent research is running on v2.",
                delta_text="C concurrent research moved to v2.",
            ),
            _transition(
                "evt_blocked",
                ordinal=11,
                category=CATEGORY_BLOCKED,
                state_ref="blocked-quota",
                status_text="C concurrent research is blocked by quota.",
                delta_text="C concurrent research is blocked by quota.",
            ),
            _transition(
                "evt_needs_user",
                ordinal=12,
                category=CATEGORY_NEEDS_USER,
                state_ref="awaiting-secret",
                status_text="A missing secret needs user input.",
                delta_text="A missing secret needs user input.",
            ),
        ]
    )

    assert len(projections) == 1
    payload = projections[0].as_dict()
    assert payload["kind"] == PROJECTION_KIND
    assert payload["schema_version"] == PROJECTION_SCHEMA_VERSION
    assert payload["coalesced_transition_count"] == 3
    assert payload["pending_delta"] == {
        "category": CATEGORY_NEEDS_USER,
        "state_ref": "awaiting-secret",
        "text": "A missing secret needs user input.",
        "source": _source("evt_needs_user", ordinal=12).as_dict(),
    }
    assert payload["source_event_ids"] == [
        "evt_material",
        "evt_blocked",
        "evt_needs_user",
    ]
    json.dumps(payload, ensure_ascii=False, sort_keys=True)


@pytest.mark.parametrize(
    ("latest_category", "recovered_to_same_state", "latest_delta"),
    [
        (CATEGORY_ROUTINE, False, ""),
        (CATEGORY_RUNTIME_INCIDENT, True, "recovered without a material state change"),
    ],
)
def test_routine_or_recovered_same_latest_state_suppresses_earlier_incident(
    latest_category: str,
    recovered_to_same_state: bool,
    latest_delta: str,
) -> None:
    projections = reduce_presentation(
        [
            _transition(
                "evt_incident",
                ordinal=20,
                category=CATEGORY_RUNTIME_INCIDENT,
                state_ref="controller-failed",
                status_text="The controller failed.",
                delta_text="The controller failed.",
            ),
            _transition(
                "evt_recovered",
                ordinal=21,
                category=latest_category,
                state_ref="running-original-state",
                status_text="C concurrent research is running.",
                delta_text=latest_delta,
                recovered_to_same_state=recovered_to_same_state,
            ),
        ]
    )

    payload = projections[0].as_dict()
    assert payload["pending_delta"] is None
    assert payload["current_state"] == {
        "state_ref": "running-original-state",
        "status_text": "C concurrent research is running.",
        "category": latest_category,
        "recovered_to_same_state": recovered_to_same_state,
    }


def test_status_query_renders_suppressed_current_state_once_and_is_acknowledgeable() -> None:
    transition = _transition(
        "evt_heartbeat",
        ordinal=30,
        category=CATEGORY_ROUTINE,
        state_ref="running-stable",
        status_text="C concurrent research is running.",
    )
    query = StatusQuery(
        query_id="status-query-1",
        activity_id="c-concurrent-research",
        audience="user",
    )

    first = reduce_presentation(
        [transition],
        status_queries=[query, query],
    )[0].as_dict()
    assert first["pending_delta"] is None
    assert first["status_renders"] == [
        {
            "query_id": "status-query-1",
            "state_ref": "running-stable",
            "text": "C concurrent research is running.",
            "source": transition.source.as_dict(),
        }
    ]

    replay = reduce_presentation(
        [transition],
        status_queries=[query],
        served_status_query_ids=["status-query-1"],
    )[0].as_dict()
    assert replay["status_renders"] == []


def test_hook_first_final_then_imported_earlier_commentary_uses_rollout_chronology() -> None:
    final_captured_by_stop_hook = _transition(
        "evt_final",
        ordinal=3265,
        phase="final_answer",
        database_seq=139,
        category=CATEGORY_MAJOR_RESULT,
        state_ref="final-result",
        status_text="The material result is available.",
        delta_text="The material result is available.",
    )
    commentary_imported_later = _transition(
        "evt_commentary",
        ordinal=3260,
        phase="commentary",
        database_seq=567,
        category=CATEGORY_MATERIAL,
        state_ref="working",
        status_text="Work was still in progress.",
        delta_text="Work was still in progress.",
    )

    # Iterable order mirrors event-store capture order: Stop/final first, then
    # the rollout importer backfills the earlier commentary.  database_seq is
    # deliberately the opposite of surfaced chronology.
    captured_order = reduce_presentation([final_captured_by_stop_hook, commentary_imported_later])[
        0
    ].as_dict()
    reverse_order = reduce_presentation([commentary_imported_later, final_captured_by_stop_hook])[
        0
    ].as_dict()

    assert captured_order == reverse_order
    assert captured_order["source_event_ids"] == ["evt_commentary", "evt_final"]
    assert captured_order["input_tip"]["event_id"] == "evt_final"
    assert captured_order["input_tip"]["database_seq"] == 139
    assert captured_order["pending_delta"]["text"] == "The material result is available."


def test_activity_and_audience_scopes_coalesce_independently_and_sort_stably() -> None:
    projections = reduce_presentation(
        [
            _transition(
                "evt_operator",
                ordinal=2,
                category=CATEGORY_BLOCKED,
                state_ref="operator-blocked",
                status_text="Operator action is blocked.",
                delta_text="Operator action is blocked.",
                audience="operator",
            ),
            _transition(
                "evt_user",
                ordinal=1,
                category=CATEGORY_MATERIAL,
                state_ref="user-running",
                status_text="User-visible research is running.",
                delta_text="User-visible research started.",
            ),
            _transition(
                "evt_other_activity",
                ordinal=3,
                category=CATEGORY_MAJOR_RESULT,
                state_ref="a-result",
                status_text="A result is ready.",
                delta_text="A result is ready.",
                activity_id="a-concurrent-research",
            ),
        ]
    )

    assert [(item.activity_id, item.audience) for item in projections] == [
        ("a-concurrent-research", "user"),
        ("c-concurrent-research", "operator"),
        ("c-concurrent-research", "user"),
    ]
    assert [item.as_dict()["pending_delta"]["category"] for item in projections] == [
        CATEGORY_MAJOR_RESULT,
        CATEGORY_BLOCKED,
        CATEGORY_MATERIAL,
    ]


def test_duplicate_event_is_idempotent_but_conflicting_payload_fails_closed() -> None:
    transition = _transition(
        "evt_duplicate",
        ordinal=40,
        category=CATEGORY_MATERIAL,
        state_ref="running",
        status_text="Running.",
        delta_text="Started.",
    )
    projection = reduce_presentation([transition, transition])[0].as_dict()
    assert projection["coalesced_transition_count"] == 1

    conflict = _transition(
        "evt_duplicate",
        ordinal=40,
        category=CATEGORY_BLOCKED,
        state_ref="blocked",
        status_text="Blocked.",
        delta_text="Blocked.",
    )
    with pytest.raises(ValueError, match="conflicting transition payloads"):
        reduce_presentation([transition, conflict])


def test_ambiguous_surface_position_fails_instead_of_falling_back_to_database_seq() -> None:
    first = _transition(
        "evt_first",
        ordinal=50,
        category=CATEGORY_MATERIAL,
        state_ref="first",
        status_text="First.",
        delta_text="First.",
        database_seq=100,
    )
    second = _transition(
        "evt_second",
        ordinal=50,
        category=CATEGORY_BLOCKED,
        state_ref="second",
        status_text="Second.",
        delta_text="Second.",
        database_seq=101,
    )

    with pytest.raises(ValueError, match="surface chronology is ambiguous"):
        reduce_presentation([first, second])


def test_visible_categories_require_an_explicit_runtime_owned_delta() -> None:
    with pytest.raises(ValueError, match="visible transitions require delta_text"):
        _transition(
            "evt_missing_delta",
            ordinal=60,
            category=CATEGORY_NEEDS_USER,
            state_ref="needs-user",
            status_text="User input is required.",
        )


def test_conflicting_status_query_identity_fails_closed() -> None:
    transition = _transition(
        "evt_status",
        ordinal=70,
        category=CATEGORY_ROUTINE,
        state_ref="running",
        status_text="Running.",
    )
    with pytest.raises(ValueError, match="refers to multiple scopes"):
        reduce_presentation(
            [transition],
            status_queries=[
                StatusQuery("q-1", "c-concurrent-research", "user"),
                StatusQuery("q-1", "other-activity", "user"),
            ],
        )
