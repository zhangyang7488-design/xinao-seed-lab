from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from xinao.canonical.identifiers import generate_uuid7
from xinao.ledger import create_event, replay_stream

SAFE_INTEGER = st.integers(min_value=-(2**53) + 1, max_value=(2**53) - 1)
SAFE_KEY = st.text(alphabet=st.characters(exclude_categories=("Cs",)), min_size=1, max_size=30)


@given(
    st.lists(
        st.dictionaries(SAFE_KEY, SAFE_INTEGER, max_size=10),
        min_size=1,
        max_size=20,
    )
)
def test_any_canonical_payload_chain_replays(payloads: list[dict[str, int]]) -> None:
    correlation_id = generate_uuid7()
    trace_id = generate_uuid7()
    prior = None
    events = []
    for version, payload in enumerate(payloads, start=1):
        record = create_event(
            event_id=generate_uuid7(),
            event_type="PropertyEvent",
            aggregate_type="PropertyAggregate",
            aggregate_id="property-1",
            aggregate_version=version,
            occurred_at=datetime(2026, 7, 14, 3, 0, tzinfo=UTC),
            correlation_id=correlation_id,
            causation_id=None if version == 1 else events[-1].event_id,
            actor="property-test",
            command_id=generate_uuid7(),
            idempotency_key=f"property-{version}",
            payload_schema_version="property.v1",
            payload=payload,
            prior_event_hash=prior,
            trace_id=trace_id,
        )
        events.append(record)
        prior = record.event_hash
    assert replay_stream(events).event_count == len(payloads)
