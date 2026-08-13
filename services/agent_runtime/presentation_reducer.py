"""Pure presentation reduction for already-typed runtime transitions.

The reducer is deliberately separate from Context Runtime's hot materializer
and from every user-interface emitter.  It receives transitions whose
presentation category has already been assigned by the owning runtime,
coalesces them by ``activity_id`` and ``audience``, and returns deterministic
projection payloads.  It never classifies prose or performs I/O.

Chronology comes from the source rollout ordinal plus its surfaced phase.
``database_seq`` is retained only as provenance and is never an ordering key;
this matters when a Stop hook records a final answer before a later rollout
import backfills earlier commentary.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PROJECTION_SCHEMA_VERSION = "s.presentation_projection.v1"
PROJECTION_KIND = "presentation_state"

CATEGORY_ROUTINE = "routine"
CATEGORY_MATERIAL = "material"
CATEGORY_BLOCKED = "blocked"
CATEGORY_NEEDS_USER = "needs_user"
CATEGORY_STOP_PAUSE = "stop_pause"
CATEGORY_MAJOR_RESULT = "major_result"
CATEGORY_RUNTIME_INCIDENT = "runtime_incident"

TRANSITION_CATEGORIES = frozenset(
    {
        CATEGORY_ROUTINE,
        CATEGORY_MATERIAL,
        CATEGORY_BLOCKED,
        CATEGORY_NEEDS_USER,
        CATEGORY_STOP_PAUSE,
        CATEGORY_MAJOR_RESULT,
        CATEGORY_RUNTIME_INCIDENT,
    }
)
VISIBLE_CATEGORIES = TRANSITION_CATEGORIES - {CATEGORY_ROUTINE}

_PHASE_ORDER = {
    "analysis": 0,
    "tool_call": 1,
    "tool_result": 2,
    "commentary": 3,
    "final_answer": 4,
    "runtime_transition": 5,
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, *, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string or null")
    return value.strip()


def _sha256(value: object, *, field: str) -> str:
    normalized = _required_text(value, field=field).lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return normalized


def _non_negative_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class PresentationSourceRef:
    """Exact source identity and surface chronology for one transition.

    ``database_seq`` may be supplied for a receipt, but it is intentionally
    absent from :attr:`chronology_key`.
    """

    event_id: str
    event_hash: str
    source_kind: str
    source_locator: str
    source_record_sha256: str
    rollout_ordinal: int
    phase: str
    database_seq: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _required_text(self.event_id, field="event_id"))
        object.__setattr__(self, "event_hash", _sha256(self.event_hash, field="event_hash"))
        object.__setattr__(
            self,
            "source_kind",
            _required_text(self.source_kind, field="source_kind"),
        )
        object.__setattr__(
            self,
            "source_locator",
            _required_text(self.source_locator, field="source_locator"),
        )
        object.__setattr__(
            self,
            "source_record_sha256",
            _sha256(self.source_record_sha256, field="source_record_sha256"),
        )
        object.__setattr__(
            self,
            "rollout_ordinal",
            _non_negative_integer(self.rollout_ordinal, field="rollout_ordinal"),
        )
        phase = _required_text(self.phase, field="phase")
        if phase not in _PHASE_ORDER:
            allowed = ", ".join(sorted(_PHASE_ORDER))
            raise ValueError(f"phase must be one of: {allowed}")
        object.__setattr__(self, "phase", phase)
        if self.database_seq is not None:
            database_seq = _non_negative_integer(self.database_seq, field="database_seq")
            object.__setattr__(self, "database_seq", database_seq)

    @classmethod
    def from_value(
        cls,
        value: PresentationSourceRef | Mapping[str, Any],
    ) -> PresentationSourceRef:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("source must be PresentationSourceRef or a mapping")
        return cls(
            event_id=value.get("event_id"),
            event_hash=value.get("event_hash"),
            source_kind=value.get("source_kind"),
            source_locator=value.get("source_locator"),
            source_record_sha256=value.get("source_record_sha256"),
            rollout_ordinal=value.get("rollout_ordinal"),
            phase=value.get("phase"),
            database_seq=value.get("database_seq"),
        )

    @property
    def chronology_key(self) -> tuple[int, int, str]:
        """Return display chronology without consulting capture/DB order."""

        return (self.rollout_ordinal, _PHASE_ORDER[self.phase], self.event_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_hash": self.event_hash,
            "source_kind": self.source_kind,
            "source_locator": self.source_locator,
            "source_record_sha256": self.source_record_sha256,
            "rollout_ordinal": self.rollout_ordinal,
            "phase": self.phase,
            "database_seq": self.database_seq,
        }


@dataclass(frozen=True, slots=True)
class RuntimeTransition:
    """One runtime-owned typed transition supplied to the reducer."""

    activity_id: str
    audience: str
    category: str
    state_ref: str
    status_text: str
    source: PresentationSourceRef
    delta_text: str = ""
    recovered_to_same_state: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "activity_id",
            _required_text(self.activity_id, field="activity_id"),
        )
        object.__setattr__(self, "audience", _required_text(self.audience, field="audience"))
        category = _required_text(self.category, field="category")
        if category not in TRANSITION_CATEGORIES:
            allowed = ", ".join(sorted(TRANSITION_CATEGORIES))
            raise ValueError(f"category must be one of: {allowed}")
        object.__setattr__(self, "category", category)
        object.__setattr__(
            self,
            "state_ref",
            _required_text(self.state_ref, field="state_ref"),
        )
        object.__setattr__(
            self,
            "status_text",
            _required_text(self.status_text, field="status_text"),
        )
        object.__setattr__(
            self,
            "delta_text",
            _optional_text(self.delta_text, field="delta_text"),
        )
        if not isinstance(self.source, PresentationSourceRef):
            raise TypeError("source must be PresentationSourceRef")
        if not isinstance(self.recovered_to_same_state, bool):
            raise TypeError("recovered_to_same_state must be a bool")
        if category in VISIBLE_CATEGORIES and not self.delta_text:
            raise ValueError("visible transitions require delta_text")

    @classmethod
    def from_value(
        cls,
        value: RuntimeTransition | Mapping[str, Any],
    ) -> RuntimeTransition:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("transition must be RuntimeTransition or a mapping")
        return cls(
            activity_id=value.get("activity_id"),
            audience=value.get("audience"),
            category=value.get("category"),
            state_ref=value.get("state_ref"),
            status_text=value.get("status_text"),
            source=PresentationSourceRef.from_value(value.get("source")),
            delta_text=value.get("delta_text", ""),
            recovered_to_same_state=value.get("recovered_to_same_state", False),
        )

    @property
    def scope(self) -> tuple[str, str]:
        return (self.activity_id, self.audience)

    @property
    def emits_delta(self) -> bool:
        return self.category in VISIBLE_CATEGORIES and not self.recovered_to_same_state

    def as_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "audience": self.audience,
            "category": self.category,
            "state_ref": self.state_ref,
            "status_text": self.status_text,
            "delta_text": self.delta_text,
            "recovered_to_same_state": self.recovered_to_same_state,
            "source": self.source.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class StatusQuery:
    """An idempotent request to render one scope's latest known state."""

    query_id: str
    activity_id: str
    audience: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _required_text(self.query_id, field="query_id"))
        object.__setattr__(
            self,
            "activity_id",
            _required_text(self.activity_id, field="activity_id"),
        )
        object.__setattr__(self, "audience", _required_text(self.audience, field="audience"))

    @classmethod
    def from_value(cls, value: StatusQuery | Mapping[str, Any]) -> StatusQuery:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("status query must be StatusQuery or a mapping")
        return cls(
            query_id=value.get("query_id"),
            activity_id=value.get("activity_id"),
            audience=value.get("audience"),
        )

    @property
    def scope(self) -> tuple[str, str]:
        return (self.activity_id, self.audience)


@dataclass(frozen=True, slots=True)
class PresentationProjection:
    """Standalone projection content; persistence and delivery stay external."""

    activity_id: str
    audience: str
    source_refs: tuple[PresentationSourceRef, ...]
    current_transition: RuntimeTransition
    pending_delta: RuntimeTransition | None
    status_query_ids: tuple[str, ...]

    @property
    def scope_key(self) -> str:
        return f"{self.activity_id}\u001f{self.audience}"

    def as_dict(self) -> dict[str, Any]:
        current = self.current_transition
        return {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "kind": PROJECTION_KIND,
            "scope_key": self.scope_key,
            "activity_id": self.activity_id,
            "audience": self.audience,
            "source_refs": [source.as_dict() for source in self.source_refs],
            "source_event_ids": [source.event_id for source in self.source_refs],
            "input_tip": current.source.as_dict(),
            "current_state": {
                "state_ref": current.state_ref,
                "status_text": current.status_text,
                "category": current.category,
                "recovered_to_same_state": current.recovered_to_same_state,
            },
            "pending_delta": (
                {
                    "category": self.pending_delta.category,
                    "state_ref": self.pending_delta.state_ref,
                    "text": self.pending_delta.delta_text,
                    "source": self.pending_delta.source.as_dict(),
                }
                if self.pending_delta is not None
                else None
            ),
            "status_renders": [
                {
                    "query_id": query_id,
                    "state_ref": current.state_ref,
                    "text": current.status_text,
                    "source": current.source.as_dict(),
                }
                for query_id in self.status_query_ids
            ],
            "coalesced_transition_count": len(self.source_refs),
        }


def _canonical_transition(transition: RuntimeTransition) -> str:
    return json.dumps(
        transition.as_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize_transitions(
    transitions: Iterable[RuntimeTransition | Mapping[str, Any]],
) -> list[RuntimeTransition]:
    by_event_id: dict[str, RuntimeTransition] = {}
    canonical_by_event_id: dict[str, str] = {}
    for raw in transitions:
        transition = RuntimeTransition.from_value(raw)
        event_id = transition.source.event_id
        canonical = _canonical_transition(transition)
        previous = canonical_by_event_id.get(event_id)
        if previous is not None and previous != canonical:
            raise ValueError(f"event_id {event_id!r} has conflicting transition payloads")
        canonical_by_event_id[event_id] = canonical
        by_event_id[event_id] = transition
    return list(by_event_id.values())


def _normalize_queries(
    queries: Iterable[StatusQuery | Mapping[str, Any]],
) -> list[StatusQuery]:
    by_query_id: dict[str, StatusQuery] = {}
    for raw in queries:
        query = StatusQuery.from_value(raw)
        previous = by_query_id.get(query.query_id)
        if previous is not None and previous != query:
            raise ValueError(f"query_id {query.query_id!r} refers to multiple scopes")
        by_query_id[query.query_id] = query
    return sorted(by_query_id.values(), key=lambda query: (query.scope, query.query_id))


def reduce_presentation(
    transitions: Iterable[RuntimeTransition | Mapping[str, Any]],
    *,
    status_queries: Iterable[StatusQuery | Mapping[str, Any]] = (),
    served_status_query_ids: Iterable[str] = (),
) -> tuple[PresentationProjection, ...]:
    """Reduce typed transitions into one deterministic projection per scope.

    The last surface transition wins.  A routine transition, or a transition
    explicitly marked as recovered to the same state, suppresses any earlier
    pending delta in the same batch.  Visible categories expose at most that
    one latest delta.  A unique, not-yet-served status query renders the latest
    state once even when the normal delta is suppressed.

    Callers persist projections and delivery acknowledgements themselves.  No
    Context Runtime table, hot prompt, hook, or UI is touched here.
    """

    normalized = _normalize_transitions(transitions)
    queries = _normalize_queries(status_queries)
    served = {
        _required_text(query_id, field="served_status_query_id")
        for query_id in served_status_query_ids
    }

    grouped: dict[tuple[str, str], list[RuntimeTransition]] = {}
    for transition in normalized:
        grouped.setdefault(transition.scope, []).append(transition)

    queries_by_scope: dict[tuple[str, str], list[str]] = {}
    for query in queries:
        if query.query_id not in served:
            queries_by_scope.setdefault(query.scope, []).append(query.query_id)

    projections: list[PresentationProjection] = []
    for scope in sorted(grouped):
        ordered = sorted(
            grouped[scope],
            key=lambda transition: transition.source.chronology_key,
        )
        occupied_positions: dict[tuple[int, int], str] = {}
        for transition in ordered:
            position = transition.source.chronology_key[:2]
            previous_event = occupied_positions.get(position)
            if previous_event is not None and previous_event != transition.source.event_id:
                raise ValueError(
                    "surface chronology is ambiguous: distinct events share "
                    f"rollout_ordinal/phase {position!r} in scope {scope!r}"
                )
            occupied_positions[position] = transition.source.event_id

        current = ordered[-1]
        projections.append(
            PresentationProjection(
                activity_id=scope[0],
                audience=scope[1],
                source_refs=tuple(transition.source for transition in ordered),
                current_transition=current,
                pending_delta=current if current.emits_delta else None,
                status_query_ids=tuple(sorted(queries_by_scope.get(scope, ()))),
            )
        )

    return tuple(projections)


__all__ = [
    "CATEGORY_BLOCKED",
    "CATEGORY_MAJOR_RESULT",
    "CATEGORY_MATERIAL",
    "CATEGORY_NEEDS_USER",
    "CATEGORY_ROUTINE",
    "CATEGORY_RUNTIME_INCIDENT",
    "CATEGORY_STOP_PAUSE",
    "PROJECTION_KIND",
    "PROJECTION_SCHEMA_VERSION",
    "PresentationProjection",
    "PresentationSourceRef",
    "RuntimeTransition",
    "StatusQuery",
    "TRANSITION_CATEGORIES",
    "VISIBLE_CATEGORIES",
    "reduce_presentation",
]
