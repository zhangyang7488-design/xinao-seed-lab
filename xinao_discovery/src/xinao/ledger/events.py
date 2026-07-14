"""Pure event construction and replay used on both sides of the PostgreSQL ledger."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from xinao.canonical.hashing import canonical_sha256
from xinao.canonical.identifiers import require_uuid7
from xinao.canonical.jcs import canonical_dumps, to_json_value
from xinao.canonical.time_profile import format_utc


def _require_text(name: str, value: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{name} must be non-empty text without surrounding whitespace")
    return value


@dataclass(frozen=True, slots=True)
class EventRecord:
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None
    actor: str
    command_id: str
    idempotency_key: str
    payload_schema_version: str
    payload: Mapping[str, Any]
    payload_hash: str
    prior_event_hash: str | None
    event_hash: str
    trace_id: str
    workflow_id: str | None
    run_id: str | None
    artifact_refs: tuple[str, ...]

    @property
    def sequence_key(self) -> str:
        return f"{self.aggregate_type}:{self.aggregate_id}:{self.aggregate_version:020d}"

    def hash_basis(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "occurred_at": format_utc(self.occurred_at),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "actor": self.actor,
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "payload_schema_version": self.payload_schema_version,
            "payload": to_json_value(self.payload),
            "payload_hash": self.payload_hash,
            "prior_event_hash": self.prior_event_hash,
            "trace_id": self.trace_id,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "artifact_refs": list(self.artifact_refs),
        }

    def append_arguments(self, *, outbox_id: str, topic: str) -> tuple[Any, ...]:
        return (
            self.event_id,
            self.event_type,
            self.aggregate_type,
            self.aggregate_id,
            self.aggregate_version,
            self.occurred_at,
            self.correlation_id,
            self.causation_id,
            self.actor,
            self.command_id,
            self.idempotency_key,
            self.payload_schema_version,
            to_json_value(self.payload),
            canonical_dumps(self.payload),
            self.payload_hash,
            self.prior_event_hash,
            canonical_dumps(self.hash_basis()),
            self.event_hash,
            self.trace_id,
            self.workflow_id,
            self.run_id,
            list(self.artifact_refs),
            require_uuid7(outbox_id),
            _require_text("topic", topic),
        )


@dataclass(frozen=True, slots=True)
class ReplayState:
    aggregate_type: str
    aggregate_id: str
    version: int
    last_event_id: str
    last_event_hash: str
    event_count: int
    stream_hash: str


def create_event(
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    occurred_at: datetime,
    correlation_id: str,
    causation_id: str | None,
    actor: str,
    command_id: str,
    idempotency_key: str,
    payload_schema_version: str,
    payload: Mapping[str, Any],
    prior_event_hash: str | None,
    trace_id: str,
    workflow_id: str | None = None,
    run_id: str | None = None,
    artifact_refs: Iterable[str] = (),
) -> EventRecord:
    require_uuid7(event_id)
    require_uuid7(correlation_id)
    require_uuid7(command_id)
    require_uuid7(trace_id)
    if causation_id is not None:
        require_uuid7(causation_id)
    if aggregate_version <= 0:
        raise ValueError("aggregate_version must be positive")
    if aggregate_version == 1 and prior_event_hash is not None:
        raise ValueError("the first aggregate event cannot have a prior hash")
    if aggregate_version > 1 and prior_event_hash is None:
        raise ValueError("a non-first aggregate event requires a prior hash")
    format_utc(occurred_at)
    normalized_payload = to_json_value(payload)
    payload_hash = canonical_sha256(normalized_payload)
    draft = EventRecord(
        event_id=event_id,
        event_type=_require_text("event_type", event_type),
        aggregate_type=_require_text("aggregate_type", aggregate_type),
        aggregate_id=_require_text("aggregate_id", aggregate_id),
        aggregate_version=aggregate_version,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        causation_id=causation_id,
        actor=_require_text("actor", actor),
        command_id=command_id,
        idempotency_key=_require_text("idempotency_key", idempotency_key),
        payload_schema_version=_require_text("payload_schema_version", payload_schema_version),
        payload=normalized_payload,
        payload_hash=payload_hash,
        prior_event_hash=prior_event_hash,
        event_hash="",
        trace_id=trace_id,
        workflow_id=workflow_id,
        run_id=run_id,
        artifact_refs=tuple(artifact_refs),
    )
    return replace(draft, event_hash=canonical_sha256(draft.hash_basis()))


def verify_event(event: EventRecord) -> None:
    if canonical_sha256(event.payload) != event.payload_hash:
        raise ValueError(f"payload hash mismatch for event {event.event_id}")
    if canonical_sha256(event.hash_basis()) != event.event_hash:
        raise ValueError(f"event hash mismatch for event {event.event_id}")


def replay_stream(events: Iterable[EventRecord]) -> ReplayState:
    materialized = tuple(events)
    if not materialized:
        raise ValueError("cannot replay an empty event stream")
    first = materialized[0]
    expected_prior: str | None = None
    seen_events: set[str] = set()
    seen_idempotency: set[str] = set()
    for expected_version, event in enumerate(materialized, start=1):
        verify_event(event)
        if (event.aggregate_type, event.aggregate_id) != (
            first.aggregate_type,
            first.aggregate_id,
        ):
            raise ValueError("event stream contains multiple aggregates")
        if event.aggregate_version != expected_version:
            raise ValueError("aggregate versions are not contiguous and ordered")
        if event.prior_event_hash != expected_prior:
            raise ValueError("event hash chain is broken")
        if event.event_id in seen_events or event.idempotency_key in seen_idempotency:
            raise ValueError("event stream contains a duplicate identity")
        seen_events.add(event.event_id)
        seen_idempotency.add(event.idempotency_key)
        expected_prior = event.event_hash
    last = materialized[-1]
    return ReplayState(
        aggregate_type=first.aggregate_type,
        aggregate_id=first.aggregate_id,
        version=last.aggregate_version,
        last_event_id=last.event_id,
        last_event_hash=last.event_hash,
        event_count=len(materialized),
        stream_hash=canonical_sha256([event.event_hash for event in materialized]),
    )
