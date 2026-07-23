"""Regression checks for deterministic formal-vertical event identifiers and timestamps."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xinao.ledger import create_event


def _registration_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "register" / "formal_vertical.py"
    spec = importlib.util.spec_from_file_location("xinao_formal_vertical_registration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_formal_registration_fails_before_database_when_admission_is_missing(
    tmp_path: Path,
) -> None:
    module = _registration_module()
    with pytest.raises(SystemExit, match="formal vertical registration denied"):
        module.require_domain_research_admission(
            tmp_path / "missing-admission.json",
            report_sha256="a" * 64,
            scope="xinao-domain-mainline",
            realm="DOMAIN_FIXED_AXIOM",
            as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
        )
