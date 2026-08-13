"""Canonical-stream presentation projection and delivery outbox.

This consumer derives ``presentation_state`` directly from Context Runtime's
append-only events.  Status queries and delivery acknowledgements are events
in that same stream; there is no second event store, mutable outbox database,
or orchestration runtime.

This module deliberately never persists ``presentation_state`` into Context's
generic ``projections`` table.  Its source events are also non-message kinds,
so the current prompt materializer cannot retrieve them as recent or relevant
conversation.  Only the explicit public readers in this module consume this
surface.  This is a property of this writer and the current materializer paths,
not a claim that Context has a global reserved-kind access-control gate.

Context's generic append API rejects all presentation-reserved event kinds.
The observer and this delivery consumer use narrow typed writer functions that
construct event identity centrally; callers do not supply low-level event kind,
source key, locator, metadata, or parent bindings.

While an item remains the reducer's current coalesced item, delivery is
at-least-once across a process crash.  A newer transition may intentionally
coalesce an unacknowledged older delta; this surface is latest-state reporting,
not a per-transition notification log.  Emitters must use the stable
``delivery_key`` as their idempotency key; an acknowledgement is appended only
after the emitter returns a durable receipt identity.  Nothing here claims to
intercept arbitrary Codex commentary or to provide a product UI hook.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.agent_runtime import context_fabric
from services.agent_runtime.context_runtime_completion import (
    PRESENTATION_DELIVERY_ACK_EVENT_KIND,
    PRESENTATION_DELIVERY_ACK_EVENT_SCHEMA,
    PRESENTATION_STATUS_QUERY_EVENT_KIND,
    PRESENTATION_STATUS_QUERY_EVENT_SCHEMA,
    append_presentation_delivery_ack,
    append_presentation_status_query,
)
from services.agent_runtime.presentation_lock import (
    PresentationLockBusy,
    exclusive_presentation_lock,
)
from services.agent_runtime.presentation_observer import (
    CONTEXT_EVENT_KIND,
    OBSERVER_CURSOR_SCHEMA_VERSION,
)
from services.agent_runtime.presentation_reducer import (
    PROJECTION_KIND,
    PROJECTION_SCHEMA_VERSION,
    PresentationProjection,
    PresentationSourceRef,
    RuntimeTransition,
    StatusQuery,
    reduce_presentation,
)

PRESENTATION_STATE_READ_SCHEMA = "s.presentation_state.read.v1"
PRESENTATION_OUTBOX_ITEM_SCHEMA = "s.presentation_outbox.item.v1"
PRESENTATION_CONSUMER_RECEIPT_SCHEMA = "s.presentation_outbox.consume_receipt.v1"
STATUS_QUERY_EVENT_SCHEMA = PRESENTATION_STATUS_QUERY_EVENT_SCHEMA
DELIVERY_ACK_EVENT_SCHEMA = PRESENTATION_DELIVERY_ACK_EVENT_SCHEMA

STATUS_QUERY_EVENT_KIND = PRESENTATION_STATUS_QUERY_EVENT_KIND
DELIVERY_ACK_EVENT_KIND = PRESENTATION_DELIVERY_ACK_EVENT_KIND

DELIVERY_KIND_DELTA = "delta"
DELIVERY_KIND_STATUS = "status"
DELIVERY_KINDS = frozenset({DELIVERY_KIND_DELTA, DELIVERY_KIND_STATUS})

_PRESENTATION_EVENT_KINDS = (
    CONTEXT_EVENT_KIND,
    STATUS_QUERY_EVENT_KIND,
    DELIVERY_ACK_EVENT_KIND,
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BOUNDED_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}")
_DELIVERY_LOCK_TOKEN = object()


class PresentationDeliveryError(RuntimeError):
    """The canonical presentation stream or delivery contract is invalid."""


def _required_text(value: object, *, field: str, max_length: int = 192) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PresentationDeliveryError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text) > max_length:
        raise PresentationDeliveryError(f"{field} exceeds its bounded length")
    return text


def _bounded_id(value: object, *, field: str) -> str:
    text = _required_text(value, field=field)
    if _BOUNDED_ID_RE.fullmatch(text) is None:
        raise PresentationDeliveryError(f"{field} is not a supported identifier")
    return text


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _delivery_key(identity: Mapping[str, object]) -> str:
    return "delivery_" + _sha256_value(
        {
            "schema": PRESENTATION_OUTBOX_ITEM_SCHEMA,
            **dict(identity),
        }
    )


@dataclass(frozen=True, slots=True)
class PresentationDeliveryItem:
    """One coalesced user-facing delta or explicit status response."""

    delivery_key: str
    delivery_kind: str
    activity_id: str
    audience: str
    category: str
    state_ref: str
    text: str
    source_event_id: str
    surface_ordinal: int
    query_id: str = ""
    query_event_id: str = ""

    def __post_init__(self) -> None:
        if (
            not self.delivery_key.startswith("delivery_")
            or _SHA256_RE.fullmatch(self.delivery_key.removeprefix("delivery_")) is None
        ):
            raise PresentationDeliveryError("delivery_key is invalid")
        if self.delivery_kind not in DELIVERY_KINDS:
            raise PresentationDeliveryError("delivery_kind is unsupported")
        for field in ("activity_id", "audience", "category", "state_ref", "source_event_id"):
            _required_text(getattr(self, field), field=field, max_length=256)
        _required_text(self.text, field="delivery text", max_length=8_192)
        if isinstance(self.surface_ordinal, bool) or not isinstance(self.surface_ordinal, int):
            raise PresentationDeliveryError("surface_ordinal must be an integer")
        if self.surface_ordinal < 0:
            raise PresentationDeliveryError("surface_ordinal must be non-negative")
        if self.delivery_kind == DELIVERY_KIND_STATUS:
            _required_text(self.query_id, field="query_id")
            _required_text(self.query_event_id, field="query_event_id", max_length=256)
        elif self.query_id or self.query_event_id:
            raise PresentationDeliveryError("delta delivery cannot carry a status query identity")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PRESENTATION_OUTBOX_ITEM_SCHEMA,
            "delivery_key": self.delivery_key,
            "delivery_kind": self.delivery_kind,
            "activity_id": self.activity_id,
            "audience": self.audience,
            "category": self.category,
            "state_ref": self.state_ref,
            "text": self.text,
            "source_event_id": self.source_event_id,
            "surface_ordinal": self.surface_ordinal,
            "query_id": self.query_id or None,
            "query_event_id": self.query_event_id or None,
            "authority": False,
        }


@dataclass(frozen=True, slots=True)
class _CanonicalPresentation:
    transitions: tuple[RuntimeTransition, ...]
    status_queries: tuple[StatusQuery, ...]
    query_event_ids: Mapping[str, str]
    acked_delivery_keys: frozenset[str]
    delivery_acks: Mapping[str, _DeliveryAck]
    served_status_query_ids: frozenset[str]
    source_event_count: int
    presentation_tip_seq: int
    presentation_tip_event_hash: str


@dataclass(frozen=True, slots=True)
class _DeliveryAck:
    delivery_key: str
    delivery_kind: str
    activity_id: str
    audience: str
    category: str
    state_ref: str
    source_event_id: str
    surface_ordinal: int
    query_id: str
    query_event_id: str
    item_sha256: str
    consumer_id: str
    delivery_receipt_id: str
    event_id: str
    parent_event_ids: tuple[str, ...]


def _database_path(root: Path) -> Path:
    candidate = Path(root)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PresentationDeliveryError("context fabric root is unavailable") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise PresentationDeliveryError("context fabric root must be a regular directory")
    database = resolved / "context_fabric.sqlite3"
    if not database.is_file() or database.is_symlink():
        raise PresentationDeliveryError("context fabric database is unavailable")
    return database


def _event_ids(root: Path) -> list[str]:
    database = _database_path(root)
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=1.2)
    try:
        placeholders = ",".join("?" for _ in _PRESENTATION_EVENT_KINDS)
        rows = connection.execute(
            f"SELECT event_id FROM events WHERE event_kind IN ({placeholders}) ORDER BY seq",
            _PRESENTATION_EVENT_KINDS,
        ).fetchall()
    except sqlite3.Error as exc:
        raise PresentationDeliveryError("canonical presentation events are unreadable") from exc
    finally:
        connection.close()
    return [str(row[0]) for row in rows]


def _metadata(event: Mapping[str, object]) -> dict[str, object]:
    value = event.get("metadata")
    if not isinstance(value, dict):
        raise PresentationDeliveryError("canonical event metadata is not an object")
    if value.get("parent_event_ids") is None or value.get("artifact_ids") is None:
        raise PresentationDeliveryError("canonical event relationship metadata is incomplete")
    return value


def _transition_from_event(event: Mapping[str, object]) -> RuntimeTransition:
    metadata = _metadata(event)
    if metadata.get("projection_kind") != PROJECTION_KIND:
        raise PresentationDeliveryError("presentation transition projection kind changed")
    if metadata.get("projection_schema_version") != PROJECTION_SCHEMA_VERSION:
        raise PresentationDeliveryError("presentation transition schema changed")
    source_record_sha256 = str(event.get("source_record_sha256") or "")
    event_hash = str(event.get("event_hash") or "")
    if (
        _SHA256_RE.fullmatch(source_record_sha256) is None
        or _SHA256_RE.fullmatch(event_hash) is None
    ):
        raise PresentationDeliveryError("presentation transition provenance digest is invalid")
    try:
        database_seq = int(event["seq"])
        surface_ordinal = int(metadata["surface_ordinal"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PresentationDeliveryError("presentation transition ordinal is invalid") from exc
    if database_seq < 0 or surface_ordinal < 0:
        raise PresentationDeliveryError("presentation transition ordinal cannot be negative")
    transition = RuntimeTransition(
        activity_id=metadata.get("activity_id"),
        audience=metadata.get("audience"),
        category=metadata.get("category"),
        state_ref=metadata.get("state_ref"),
        status_text=metadata.get("status_text"),
        delta_text=metadata.get("delta_text", ""),
        recovered_to_same_state=metadata.get("recovered_to_same_state", False),
        source=PresentationSourceRef(
            event_id=str(event.get("event_id") or ""),
            event_hash=event_hash,
            source_kind=str(event.get("source_kind") or ""),
            source_locator=str(event.get("source_locator") or ""),
            source_record_sha256=source_record_sha256,
            rollout_ordinal=surface_ordinal,
            phase=metadata.get("phase"),
            database_seq=database_seq,
        ),
    )
    identity = {
        "schema": OBSERVER_CURSOR_SCHEMA_VERSION,
        "activity_id": transition.activity_id,
        "audience": transition.audience,
        "category": transition.category,
        "state_ref": transition.state_ref,
        "source_kind": transition.source.source_kind,
        "source_locator": transition.source.source_locator,
        "source_record_sha256": transition.source.source_record_sha256,
    }
    source_key = f"presentation-observer:v1:{_sha256_value(identity)}"
    expected_event_id = f"evt_{hashlib.sha256(source_key.encode('utf-8')).hexdigest()}"
    expected_metadata = {
        "projection_kind": PROJECTION_KIND,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "activity_id": transition.activity_id,
        "audience": transition.audience,
        "category": transition.category,
        "state_ref": transition.state_ref,
        "status_text": transition.status_text,
        "delta_text": transition.delta_text,
        "recovered_to_same_state": transition.recovered_to_same_state,
        "surface_ordinal": transition.source.rollout_ordinal,
        "phase": transition.source.phase,
        "parent_event_ids": [],
        "artifact_ids": [],
    }
    if (
        event.get("event_id") != expected_event_id
        or event.get("source_key") != source_key
        or event.get("speaker") != "mechanical"
        or event.get("authority_class") != "mechanical_evidence"
        or event.get("raw_text") != ""
        or metadata != expected_metadata
    ):
        raise PresentationDeliveryError("presentation transition identity is invalid")
    return transition


def _status_query_from_event(event: Mapping[str, object]) -> tuple[StatusQuery, str]:
    metadata = _metadata(event)
    if metadata.get("schema_version") != STATUS_QUERY_EVENT_SCHEMA:
        raise PresentationDeliveryError("presentation status query schema changed")
    query = StatusQuery(
        query_id=metadata.get("query_id"),
        activity_id=metadata.get("activity_id"),
        audience=metadata.get("audience"),
    )
    event_id = _required_text(event.get("event_id"), field="status query event_id")
    identity = {
        "schema_version": STATUS_QUERY_EVENT_SCHEMA,
        "query_id": query.query_id,
        "activity_id": query.activity_id,
        "audience": query.audience,
    }
    digest = _sha256_value(identity)
    if (
        event.get("source_kind") != "presentation_status_query"
        or event.get("source_locator") != f"presentation-query://{digest}"
        or event.get("source_record_sha256") != digest
        or event.get("source_key") != f"presentation-status-query:v1:{digest}"
        or event.get("speaker") != "mechanical"
        or event.get("authority_class") != "mechanical_evidence"
        or event.get("raw_text") != ""
        or metadata != {**identity, "parent_event_ids": [], "artifact_ids": []}
    ):
        raise PresentationDeliveryError("presentation status query identity is invalid")
    return query, event_id


def _ack_from_event(event: Mapping[str, object]) -> _DeliveryAck:
    metadata = _metadata(event)
    if metadata.get("schema_version") != DELIVERY_ACK_EVENT_SCHEMA:
        raise PresentationDeliveryError("presentation delivery acknowledgement schema changed")
    delivery_key = _required_text(
        metadata.get("delivery_key"),
        field="ack delivery_key",
        max_length=80,
    )
    if (
        not delivery_key.startswith("delivery_")
        or _SHA256_RE.fullmatch(delivery_key.removeprefix("delivery_")) is None
    ):
        raise PresentationDeliveryError("ack delivery_key is invalid")
    delivery_kind = _required_text(metadata.get("delivery_kind"), field="ack delivery_kind")
    if delivery_kind not in DELIVERY_KINDS:
        raise PresentationDeliveryError("ack delivery_kind is unsupported")
    activity_id = _required_text(metadata.get("activity_id"), field="ack activity_id")
    audience = _required_text(metadata.get("audience"), field="ack audience")
    category = _required_text(metadata.get("category"), field="ack category")
    state_ref = _required_text(metadata.get("state_ref"), field="ack state_ref", max_length=256)
    source_event_id = _required_text(
        metadata.get("source_event_id"), field="ack source_event_id", max_length=256
    )
    try:
        surface_ordinal = int(metadata["surface_ordinal"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PresentationDeliveryError("ack surface_ordinal is invalid") from exc
    if surface_ordinal < 0:
        raise PresentationDeliveryError("ack surface_ordinal cannot be negative")
    query_id = str(metadata.get("query_id") or "")
    query_event_id = str(metadata.get("query_event_id") or "")
    if delivery_kind == DELIVERY_KIND_STATUS and not query_id:
        raise PresentationDeliveryError("status acknowledgement lacks query_id")
    if delivery_kind == DELIVERY_KIND_STATUS and not query_event_id:
        raise PresentationDeliveryError("status acknowledgement lacks query_event_id")
    if delivery_kind == DELIVERY_KIND_DELTA and (query_id or query_event_id):
        raise PresentationDeliveryError("delta acknowledgement cannot serve a query")
    item_sha256 = _required_text(metadata.get("item_sha256"), field="ack item_sha256")
    if _SHA256_RE.fullmatch(item_sha256) is None:
        raise PresentationDeliveryError("ack item_sha256 is invalid")
    consumer_id = _bounded_id(metadata.get("consumer_id"), field="ack consumer_id")
    delivery_receipt_id = _bounded_id(
        metadata.get("delivery_receipt_id"), field="ack delivery_receipt_id"
    )
    event_id = _required_text(event.get("event_id"), field="ack event_id", max_length=256)
    parents = event.get("parent_event_ids")
    if not isinstance(parents, list) or not all(isinstance(item, str) for item in parents):
        raise PresentationDeliveryError("ack parent_event_ids are invalid")
    ack = _DeliveryAck(
        delivery_key=delivery_key,
        delivery_kind=delivery_kind,
        activity_id=activity_id,
        audience=audience,
        category=category,
        state_ref=state_ref,
        source_event_id=source_event_id,
        surface_ordinal=surface_ordinal,
        query_id=query_id,
        query_event_id=query_event_id,
        item_sha256=item_sha256,
        consumer_id=consumer_id,
        delivery_receipt_id=delivery_receipt_id,
        event_id=event_id,
        parent_event_ids=tuple(parents),
    )
    identity = {
        "schema_version": DELIVERY_ACK_EVENT_SCHEMA,
        "delivery_key": ack.delivery_key,
        "delivery_kind": ack.delivery_kind,
        "activity_id": ack.activity_id,
        "audience": ack.audience,
        "category": ack.category,
        "state_ref": ack.state_ref,
        "source_event_id": ack.source_event_id,
        "surface_ordinal": ack.surface_ordinal,
        "query_id": ack.query_id,
        "query_event_id": ack.query_event_id,
        "item_sha256": ack.item_sha256,
        "consumer_id": ack.consumer_id,
        "delivery_receipt_id": ack.delivery_receipt_id,
    }
    digest = _sha256_value(identity)
    expected_parents = sorted(
        [ack.source_event_id, *([ack.query_event_id] if ack.query_event_id else [])]
    )
    if (
        event.get("source_kind") != "presentation_delivery_ack"
        or event.get("source_locator") != f"presentation-ack://{digest}"
        or event.get("source_record_sha256") != digest
        or event.get("source_key") != f"presentation-delivery-ack:v1:{digest}"
        or event.get("speaker") != "mechanical"
        or event.get("authority_class") != "mechanical_evidence"
        or event.get("raw_text") != ""
        or list(ack.parent_event_ids) != expected_parents
        or metadata
        != {
            **identity,
            "parent_event_ids": expected_parents,
            "artifact_ids": [],
        }
    ):
        raise PresentationDeliveryError("presentation delivery acknowledgement identity is invalid")
    return ack


def _validate_ack_binding(
    ack: _DeliveryAck,
    *,
    transitions_by_event_id: Mapping[str, RuntimeTransition],
    queries_by_id: Mapping[str, StatusQuery],
    query_event_ids: Mapping[str, str],
) -> None:
    transition = transitions_by_event_id.get(ack.source_event_id)
    if transition is None:
        raise PresentationDeliveryError("ack source_event_id is not a presentation transition")
    if (
        transition.activity_id != ack.activity_id
        or transition.audience != ack.audience
        or transition.category != ack.category
        or transition.state_ref != ack.state_ref
        or transition.source.rollout_ordinal != ack.surface_ordinal
    ):
        raise PresentationDeliveryError(
            "ack transition binding does not match its canonical source"
        )

    if ack.delivery_kind == DELIVERY_KIND_DELTA:
        if not transition.emits_delta:
            raise PresentationDeliveryError("ack cannot bind a transition that emits no delta")
        expected_item = PresentationDeliveryItem(
            delivery_key=_delivery_key(
                {
                    "delivery_kind": DELIVERY_KIND_DELTA,
                    "activity_id": ack.activity_id,
                    "audience": ack.audience,
                    "category": ack.category,
                    "state_ref": ack.state_ref,
                    "source_event_id": ack.source_event_id,
                }
            ),
            delivery_kind=DELIVERY_KIND_DELTA,
            activity_id=ack.activity_id,
            audience=ack.audience,
            category=ack.category,
            state_ref=ack.state_ref,
            text=transition.delta_text,
            source_event_id=ack.source_event_id,
            surface_ordinal=ack.surface_ordinal,
        )
    else:
        query = queries_by_id.get(ack.query_id)
        if query is None or query_event_ids.get(ack.query_id) != ack.query_event_id:
            raise PresentationDeliveryError(
                "ack query binding does not match a canonical status query"
            )
        if query.scope != transition.scope:
            raise PresentationDeliveryError("ack status query and transition scopes differ")
        expected_item = PresentationDeliveryItem(
            delivery_key=_delivery_key(
                {
                    "delivery_kind": DELIVERY_KIND_STATUS,
                    "activity_id": ack.activity_id,
                    "audience": ack.audience,
                    "state_ref": ack.state_ref,
                    "source_event_id": ack.source_event_id,
                    "query_id": ack.query_id,
                    "query_event_id": ack.query_event_id,
                }
            ),
            delivery_kind=DELIVERY_KIND_STATUS,
            activity_id=ack.activity_id,
            audience=ack.audience,
            category=ack.category,
            state_ref=ack.state_ref,
            text=transition.status_text,
            source_event_id=ack.source_event_id,
            surface_ordinal=ack.surface_ordinal,
            query_id=ack.query_id,
            query_event_id=ack.query_event_id,
        )

    if ack.delivery_key != expected_item.delivery_key:
        raise PresentationDeliveryError("ack delivery_key does not match its canonical item")
    if ack.item_sha256 != _sha256_value(expected_item.as_dict()):
        raise PresentationDeliveryError("ack item_sha256 does not match its canonical item")


def _current_unacked_items(
    *,
    transitions: list[RuntimeTransition],
    queries: list[StatusQuery],
    query_event_ids: Mapping[str, str],
    acks: list[_DeliveryAck],
) -> tuple[PresentationDeliveryItem, ...]:
    acked_keys = frozenset(ack.delivery_key for ack in acks)
    served_queries = frozenset(ack.query_id for ack in acks if ack.query_id)
    canonical = _CanonicalPresentation(
        transitions=tuple(transitions),
        status_queries=tuple(queries),
        query_event_ids=query_event_ids,
        acked_delivery_keys=acked_keys,
        delivery_acks={ack.delivery_key: ack for ack in acks},
        served_status_query_ids=served_queries,
        source_event_count=0,
        presentation_tip_seq=0,
        presentation_tip_event_hash="0" * 64,
    )
    items: list[PresentationDeliveryItem] = []
    for projection in reduce_presentation(
        transitions,
        status_queries=queries,
        served_status_query_ids=served_queries,
    ):
        items.extend(_items_for_projection(projection, canonical))
    return tuple(items)


def _read_canonical(root: Path) -> _CanonicalPresentation:
    transitions: list[RuntimeTransition] = []
    queries: list[StatusQuery] = []
    query_event_ids: dict[str, str] = {}
    acks: list[_DeliveryAck] = []
    acked_keys: set[str] = set()
    delivery_acks: dict[str, _DeliveryAck] = {}
    served_queries: set[str] = set()
    tip_seq = 0
    tip_hash = "0" * 64

    event_ids = _event_ids(root)
    for event_id in event_ids:
        event = context_fabric.read_event(event_id, root=Path(root))
        tip_seq = max(tip_seq, int(event["seq"]))
        tip_hash = str(event["event_hash"])
        kind = event.get("event_kind")
        if kind == CONTEXT_EVENT_KIND:
            transitions.append(_transition_from_event(event))
        elif kind == STATUS_QUERY_EVENT_KIND:
            query, query_event_id = _status_query_from_event(event)
            prior = query_event_ids.get(query.query_id)
            if prior is not None and prior != query_event_id:
                raise PresentationDeliveryError("query_id is bound to multiple canonical events")
            query_event_ids[query.query_id] = query_event_id
            queries.append(query)
        elif kind == DELIVERY_ACK_EVENT_KIND:
            ack = _ack_from_event(event)
            _validate_ack_binding(
                ack,
                transitions_by_event_id={
                    transition.source.event_id: transition for transition in transitions
                },
                queries_by_id={query.query_id: query for query in queries},
                query_event_ids=query_event_ids,
            )
            current_items = {
                item.delivery_key: item
                for item in _current_unacked_items(
                    transitions=transitions,
                    queries=queries,
                    query_event_ids=query_event_ids,
                    acks=acks,
                )
            }
            current_item = current_items.get(ack.delivery_key)
            if current_item is None or ack.item_sha256 != _sha256_value(current_item.as_dict()):
                raise PresentationDeliveryError("ack does not bind a current canonical outbox item")
            if ack.delivery_key in acked_keys:
                raise PresentationDeliveryError(
                    "one delivery_key is bound to multiple canonical acknowledgements"
                )
            acks.append(ack)
            acked_keys.add(ack.delivery_key)
            delivery_acks[ack.delivery_key] = ack
            if ack.query_id:
                served_queries.add(ack.query_id)
        else:  # pragma: no cover - SQL kind filter keeps this defensive only.
            raise PresentationDeliveryError("unexpected canonical presentation event kind")

    # The reducer performs duplicate/conflicting source validation and stable
    # chronology checks before any state is exposed.  ACKs are not accepted by
    # kind/name alone: each one must mechanically reconstitute one exact item
    # from its canonical transition/query parents.
    reduce_presentation(
        transitions,
        status_queries=queries,
    )
    return _CanonicalPresentation(
        transitions=tuple(transitions),
        status_queries=tuple(queries),
        query_event_ids=query_event_ids,
        acked_delivery_keys=frozenset(acked_keys),
        delivery_acks=delivery_acks,
        served_status_query_ids=frozenset(served_queries),
        source_event_count=len(event_ids),
        presentation_tip_seq=tip_seq,
        presentation_tip_event_hash=tip_hash,
    )


def _matches_scope(
    activity: str,
    audience_value: str,
    *,
    activity_id: str,
    audience: str,
) -> bool:
    return (not activity_id or activity == activity_id) and (
        not audience or audience_value == audience
    )


def _projections(
    canonical: _CanonicalPresentation,
    *,
    activity_id: str,
    audience: str,
) -> tuple[PresentationProjection, ...]:
    transitions = [
        transition
        for transition in canonical.transitions
        if _matches_scope(
            transition.activity_id,
            transition.audience,
            activity_id=activity_id,
            audience=audience,
        )
    ]
    queries = [
        query
        for query in canonical.status_queries
        if _matches_scope(
            query.activity_id,
            query.audience,
            activity_id=activity_id,
            audience=audience,
        )
    ]
    return reduce_presentation(
        transitions,
        status_queries=queries,
        served_status_query_ids=canonical.served_status_query_ids,
    )


def _items_for_projection(
    projection: PresentationProjection,
    canonical: _CanonicalPresentation,
) -> list[PresentationDeliveryItem]:
    result: list[PresentationDeliveryItem] = []
    pending = projection.pending_delta
    if pending is not None:
        key = _delivery_key(
            {
                "delivery_kind": DELIVERY_KIND_DELTA,
                "activity_id": projection.activity_id,
                "audience": projection.audience,
                "category": pending.category,
                "state_ref": pending.state_ref,
                "source_event_id": pending.source.event_id,
            }
        )
        if key not in canonical.acked_delivery_keys:
            result.append(
                PresentationDeliveryItem(
                    delivery_key=key,
                    delivery_kind=DELIVERY_KIND_DELTA,
                    activity_id=projection.activity_id,
                    audience=projection.audience,
                    category=pending.category,
                    state_ref=pending.state_ref,
                    text=pending.delta_text,
                    source_event_id=pending.source.event_id,
                    surface_ordinal=pending.source.rollout_ordinal,
                )
            )

    current = projection.current_transition
    for query_id in projection.status_query_ids:
        query_event_id = canonical.query_event_ids.get(query_id)
        if not query_event_id:
            raise PresentationDeliveryError("status query lacks a canonical source event")
        key = _delivery_key(
            {
                "delivery_kind": DELIVERY_KIND_STATUS,
                "activity_id": projection.activity_id,
                "audience": projection.audience,
                "state_ref": current.state_ref,
                "source_event_id": current.source.event_id,
                "query_id": query_id,
                "query_event_id": query_event_id,
            }
        )
        if key not in canonical.acked_delivery_keys:
            result.append(
                PresentationDeliveryItem(
                    delivery_key=key,
                    delivery_kind=DELIVERY_KIND_STATUS,
                    activity_id=projection.activity_id,
                    audience=projection.audience,
                    category=current.category,
                    state_ref=current.state_ref,
                    text=current.status_text,
                    source_event_id=current.source.event_id,
                    surface_ordinal=current.source.rollout_ordinal,
                    query_id=query_id,
                    query_event_id=query_event_id,
                )
            )
    return result


def _state_and_items(
    *,
    root: Path,
    activity_id: str = "",
    audience: str = "",
) -> tuple[tuple[dict[str, Any], ...], tuple[PresentationDeliveryItem, ...]]:
    if activity_id:
        activity_id = _required_text(activity_id, field="activity_id")
    if audience:
        audience = _required_text(audience, field="audience")
    canonical = _read_canonical(Path(root))
    projections = _projections(
        canonical,
        activity_id=activity_id,
        audience=audience,
    )
    items: list[PresentationDeliveryItem] = []
    states: list[dict[str, Any]] = []
    for projection in projections:
        projection_items = _items_for_projection(projection, canonical)
        items.extend(projection_items)
        states.append(
            {
                "schema_version": PRESENTATION_STATE_READ_SCHEMA,
                "kind": PROJECTION_KIND,
                "activity_id": projection.activity_id,
                "audience": projection.audience,
                "scope_key": projection.scope_key,
                "projection": projection.as_dict(),
                "pending_delivery_keys": [item.delivery_key for item in projection_items],
                "canonical_source_event_count": canonical.source_event_count,
                # This is the tip of the presentation subset, not a claim
                # about the current tip of the whole concurrently-appended
                # Context event chain.
                "presentation_tip_seq": canonical.presentation_tip_seq,
                "presentation_tip_event_hash": canonical.presentation_tip_event_hash,
                "hot_prompt_materialization": False,
                "authority": False,
            }
        )
    items.sort(
        key=lambda item: (
            item.surface_ordinal,
            0 if item.delivery_kind == DELIVERY_KIND_DELTA else 1,
            item.delivery_key,
        )
    )
    return tuple(states), tuple(items)


def read_presentation_state(
    *,
    root: Path = context_fabric.DEFAULT_CONTEXT_FABRIC_ROOT,
    activity_id: str = "",
    audience: str = "",
) -> tuple[dict[str, Any], ...]:
    """Read the independent, non-hot projection from canonical events."""

    states, _items = _state_and_items(
        root=Path(root),
        activity_id=activity_id,
        audience=audience,
    )
    return states


def read_presentation_outbox(
    *,
    root: Path = context_fabric.DEFAULT_CONTEXT_FABRIC_ROOT,
    activity_id: str = "",
    audience: str = "",
) -> tuple[PresentationDeliveryItem, ...]:
    """Read coalesced, unacknowledged delivery items from the same event stream."""

    _states, items = _state_and_items(
        root=Path(root),
        activity_id=activity_id,
        audience=audience,
    )
    return items


def append_status_query(
    *,
    query_id: str,
    activity_id: str,
    audience: str,
    carrier_id: str,
    root: Path = context_fabric.DEFAULT_CONTEXT_FABRIC_ROOT,
    occurred_at: str = "",
    environ: Mapping[str, str] | None = None,
) -> object:
    """Append an idempotent explicit request to render current state once."""

    return append_presentation_status_query(
        query_id=query_id,
        activity_id=activity_id,
        audience=audience,
        carrier_id=_bounded_id(carrier_id, field="carrier_id"),
        root=Path(root),
        occurred_at=occurred_at,
        environ=environ,
    )


def acknowledge_delivery(
    item: PresentationDeliveryItem,
    *,
    delivery_receipt_id: str,
    consumer_id: str,
    carrier_id: str,
    root: Path = context_fabric.DEFAULT_CONTEXT_FABRIC_ROOT,
    occurred_at: str = "",
    environ: Mapping[str, str] | None = None,
    _lock_token: object | None = None,
) -> object:
    """Append an idempotent acknowledgement after durable emitter success."""

    root = Path(root)
    if _lock_token is not _DELIVERY_LOCK_TOKEN:
        lock_path = _database_path(root).with_name("presentation_delivery.lock")
        try:
            with exclusive_presentation_lock(lock_path):
                return acknowledge_delivery(
                    item,
                    delivery_receipt_id=delivery_receipt_id,
                    consumer_id=consumer_id,
                    carrier_id=carrier_id,
                    root=root,
                    occurred_at=occurred_at,
                    environ=environ,
                    _lock_token=_DELIVERY_LOCK_TOKEN,
                )
        except PresentationLockBusy as exc:
            raise PresentationDeliveryError("presentation delivery consumer is busy") from exc

    if not isinstance(item, PresentationDeliveryItem):
        raise TypeError("item must be PresentationDeliveryItem")
    receipt_id = _bounded_id(delivery_receipt_id, field="delivery_receipt_id")
    consumer = _bounded_id(consumer_id, field="consumer_id")
    canonical = _read_canonical(root)
    item_sha256 = _sha256_value(item.as_dict())
    existing_ack = canonical.delivery_acks.get(item.delivery_key)
    if existing_ack is not None:
        if (
            existing_ack.consumer_id != consumer
            or existing_ack.delivery_receipt_id != receipt_id
            or existing_ack.item_sha256 != item_sha256
        ):
            raise PresentationDeliveryError(
                "delivery_key is already acknowledged by a different receipt identity"
            )
        # Exact replay is delegated to Context's source-key idempotency after
        # reconstructing the same ACK identity below.
    current_items: dict[str, PresentationDeliveryItem] = {}
    for projection in _projections(
        canonical,
        activity_id=item.activity_id,
        audience=item.audience,
    ):
        for pending in _items_for_projection(projection, canonical):
            current_items[pending.delivery_key] = pending
    current_item = current_items.get(item.delivery_key)
    if existing_ack is None and (current_item is None or current_item != item):
        raise PresentationDeliveryError(
            "item_sha256 does not identify a current canonical outbox item"
        )
    probe = _DeliveryAck(
        delivery_key=item.delivery_key,
        delivery_kind=item.delivery_kind,
        activity_id=item.activity_id,
        audience=item.audience,
        category=item.category,
        state_ref=item.state_ref,
        source_event_id=item.source_event_id,
        surface_ordinal=item.surface_ordinal,
        query_id=item.query_id,
        query_event_id=item.query_event_id,
        item_sha256=item_sha256,
        consumer_id=consumer,
        delivery_receipt_id=receipt_id,
        event_id="preappend-validation",
        parent_event_ids=tuple(
            sorted([item.source_event_id, *([item.query_event_id] if item.query_event_id else [])])
        ),
    )
    _validate_ack_binding(
        probe,
        transitions_by_event_id={
            transition.source.event_id: transition for transition in canonical.transitions
        },
        queries_by_id={query.query_id: query for query in canonical.status_queries},
        query_event_ids=canonical.query_event_ids,
    )
    return append_presentation_delivery_ack(
        item,
        delivery_receipt_id=receipt_id,
        consumer_id=consumer,
        carrier_id=_bounded_id(carrier_id, field="carrier_id"),
        root=root,
        occurred_at=occurred_at,
        environ=environ,
    )


def consume_presentation_outbox(
    deliver: Callable[[PresentationDeliveryItem], str],
    *,
    consumer_id: str,
    carrier_id: str,
    root: Path = context_fabric.DEFAULT_CONTEXT_FABRIC_ROOT,
    activity_id: str = "",
    audience: str = "",
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Deliver each current item and append its canonical acknowledgement.

    The callback is the only emitter seam.  It must durably deduplicate by the
    supplied delivery key and return a stable receipt identifier.  This
    consumer does not itself select a UI, notification service, or chat route.
    """

    if not callable(deliver):
        raise TypeError("deliver must be callable")
    consumer = _bounded_id(consumer_id, field="consumer_id")
    carrier = _bounded_id(carrier_id, field="carrier_id")
    root = Path(root)
    lock_path = _database_path(root).with_name("presentation_delivery.lock")
    try:
        with exclusive_presentation_lock(lock_path):
            items = read_presentation_outbox(
                root=root,
                activity_id=activity_id,
                audience=audience,
            )
            ack_event_ids: list[str] = []
            delivered_keys: list[str] = []
            for item in items:
                receipt_id = _bounded_id(deliver(item), field="delivery_receipt_id")
                result = acknowledge_delivery(
                    item,
                    delivery_receipt_id=receipt_id,
                    consumer_id=consumer,
                    carrier_id=carrier,
                    root=root,
                    environ=environ,
                    _lock_token=_DELIVERY_LOCK_TOKEN,
                )
                ack_event_id = getattr(result, "event_id", None)
                if not isinstance(ack_event_id, str) or not ack_event_id:
                    raise PresentationDeliveryError(
                        "canonical acknowledgement did not return its event identity"
                    )
                ack_event_ids.append(ack_event_id)
                delivered_keys.append(item.delivery_key)
    except PresentationLockBusy as exc:
        raise PresentationDeliveryError("presentation delivery consumer is busy") from exc

    return {
        "schema_version": PRESENTATION_CONSUMER_RECEIPT_SCHEMA,
        "consumer_id": consumer,
        "delivered_count": len(delivered_keys),
        "delivery_keys": delivered_keys,
        "ack_event_ids": ack_event_ids,
        "authority": False,
        "ui_interception_claimed": False,
    }


__all__ = [
    "DELIVERY_ACK_EVENT_KIND",
    "DELIVERY_ACK_EVENT_SCHEMA",
    "DELIVERY_KIND_DELTA",
    "DELIVERY_KIND_STATUS",
    "PRESENTATION_CONSUMER_RECEIPT_SCHEMA",
    "PRESENTATION_OUTBOX_ITEM_SCHEMA",
    "PRESENTATION_STATE_READ_SCHEMA",
    "STATUS_QUERY_EVENT_KIND",
    "STATUS_QUERY_EVENT_SCHEMA",
    "PresentationDeliveryError",
    "PresentationDeliveryItem",
    "acknowledge_delivery",
    "append_status_query",
    "consume_presentation_outbox",
    "read_presentation_outbox",
    "read_presentation_state",
]
