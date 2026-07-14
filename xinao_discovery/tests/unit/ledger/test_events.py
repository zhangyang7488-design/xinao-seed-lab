from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from xinao.ledger import create_event, replay_stream, verify_event

IDS = (
    "0190f9c0-6f4c-7a01-8b22-334455667788",
    "0190f9c0-6f4c-7a02-8b22-334455667788",
    "0190f9c0-6f4c-7a03-8b22-334455667788",
    "0190f9c0-6f4c-7a04-8b22-334455667788",
    "0190f9c0-6f4c-7a05-8b22-334455667788",
    "0190f9c0-6f4c-7a06-8b22-334455667788",
)


def event(version: int, prior_hash: str | None = None):
    offset = 0 if version == 1 else 3
    return create_event(
        event_id=IDS[offset],
        event_type="DatasetRegistered" if version == 1 else "DatasetSuperseded",
        aggregate_type="DatasetSnapshot",
        aggregate_id="verified-913",
        aggregate_version=version,
        occurred_at=datetime(2026, 7, 14, 2, version, tzinfo=UTC),
        correlation_id=IDS[1],
        causation_id=None if version == 1 else IDS[0],
        actor="Codex",
        command_id=IDS[offset + 2],
        idempotency_key=f"dataset-{version}",
        payload_schema_version="dataset-snapshot.v1",
        payload={"dataset_ref": "verified-913", "version": version},
        prior_event_hash=prior_hash,
        trace_id=IDS[2],
        workflow_id="xinao-canary",
        run_id="run-1",
    )


def test_event_creation_and_replay_are_deterministic() -> None:
    first = event(1)
    second = event(2, first.event_hash)
    verify_event(first)
    state = replay_stream([first, second])
    assert state.version == 2
    assert state.last_event_hash == second.event_hash
    assert first.sequence_key.endswith("00000000000000000001")
    assert (
        create_event(
            **{
                field: getattr(first, field)
                for field in (
                    "event_id",
                    "event_type",
                    "aggregate_type",
                    "aggregate_id",
                    "aggregate_version",
                    "occurred_at",
                    "correlation_id",
                    "causation_id",
                    "actor",
                    "command_id",
                    "idempotency_key",
                    "payload_schema_version",
                    "payload",
                    "prior_event_hash",
                    "trace_id",
                    "workflow_id",
                    "run_id",
                    "artifact_refs",
                )
            }
        ).event_hash
        == first.event_hash
    )


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda item: replace(item, payload={"tampered": True}), "payload hash mismatch"),
        (lambda item: replace(item, event_hash="f" * 64), "event hash mismatch"),
    ],
)
def test_event_tampering_is_rejected(mutation, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        verify_event(mutation(event(1)))


def test_replay_rejects_out_of_order_or_broken_chain() -> None:
    first = event(1)
    second = event(2, first.event_hash)
    with pytest.raises(ValueError, match="versions"):
        replay_stream([second, first])
    wrong_chain = event(2, "f" * 64)
    with pytest.raises(ValueError, match="hash chain"):
        replay_stream([first, wrong_chain])
