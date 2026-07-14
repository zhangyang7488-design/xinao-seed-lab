"""Regression checks for deterministic formal-vertical event identifiers and timestamps."""

from datetime import UTC, datetime

from xinao.ledger import create_event


def test_all_registration_timestamps_fit_the_same_second() -> None:
    timestamps = [
        datetime(2026, 7, 14, 4, 5, 0, index * 1000, tzinfo=UTC) for index in range(1, 12)
    ]

    assert len(set(timestamps)) == 11
    assert all(value.second == 0 for value in timestamps)


def test_event_creation_accepts_the_registration_time_profile() -> None:
    event = create_event(
        event_id="0190f9c0-6f4c-7f01-8b22-334455667788",
        event_type="AuthorityContractActivated",
        aggregate_type="AuthorityContract",
        aggregate_id="authority-contract-v1",
        aggregate_version=1,
        occurred_at=datetime(2026, 7, 14, 4, 5, 0, 1000, tzinfo=UTC),
        correlation_id="0190f9c0-6f4c-7c00-8b22-334455667788",
        causation_id=None,
        actor="Codex-single-writer",
        command_id="0190f9c0-6f4c-7d01-8b22-334455667788",
        idempotency_key="authority-contract-v1",
        payload_schema_version="AuthorityContract.v1",
        payload={"content_hash": "fixture"},
        prior_event_hash=None,
        trace_id="0190f9c0-6f4c-7e00-8b22-334455667788",
        workflow_id="xinao-mainline-registration-p3-p5",
        run_id="xinao-mainline-20260714T014700",
    )

    assert event.occurred_at == datetime(2026, 7, 14, 4, 5, 0, 1000, tzinfo=UTC)
