from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from xinao.lineage import (
    EvidenceManifest,
    build_lineage_intent,
    create_mlflow_run,
    emit_openlineage_run,
    record_otel_delivery,
)


def intent(**updates: object):
    values: dict[str, object] = {
        "lineage_ref": "lineage.settlement.1",
        "correlation_id": "0190fa00-1111-7000-8222-334455667788",
        "session_id": "xinao-mainline-20260714T014700",
        "workflow_id": "xinao-mainline-p6-canary",
        "run_id": "xinao-mainline-20260714T014700",
        "code_git_sha": "a" * 40,
        "code_dirty": True,
        "config_hash": "b" * 64,
        "dvc_lock_hash": "c" * 64,
        "authority_contract_id": "macaujc-source-authority-contract.v1",
        "source_ref": "macaujc2",
        "dataset_ref": "dataset.v1",
        "dataset_hash": "d" * 64,
        "baseline_ref": "baseline.v1",
        "baseline_hash": "e" * 64,
        "rule_version": "rule.v1",
        "experiment_ref": "experiment.v1",
        "candidate_ref": "candidate.v1",
        "validation_ref": "validation.v1",
        "validation_hash": "f" * 64,
        "frozen_decision_ref": "freeze.v1",
        "frozen_decision_hash": "1" * 64,
        "outcome_ref": "outcome.v1",
        "settlement_ref": "settlement.v1",
        "settlement_hash": "2" * 64,
        "input_snapshot_hashes": ("3" * 64, "4" * 64),
        "output_hashes": ("5" * 64,),
        "openlineage_run_id": "0190fa00-1111-7000-8222-334455667788",
        "trace_id": "6" * 32,
    }
    values.update(updates)
    return build_lineage_intent(**values)


def test_intent_and_manifest_are_deterministic_complete_reverse_links() -> None:
    first = intent()
    second = intent()
    manifest = EvidenceManifest(
        intent=first,
        mlflow_run_id="mlflow-run-1",
        openlineage_run_id=first.openlineage_run_id,
        trace_id=first.trace_id,
        result_status="VERIFIED",
        verifier="Independent Verifier",
        created_at=datetime(2026, 7, 14, 8, tzinfo=UTC),
        delivery_status="DELIVERED",
    ).with_hash()

    assert first == second
    assert first.intent_hash is not None
    assert manifest.manifest_hash is not None
    assert manifest.intent.settlement_ref == "settlement.v1"
    assert manifest.intent.frozen_decision_ref == "freeze.v1"
    assert manifest.intent.validation_ref == "validation.v1"
    assert manifest.intent.dataset_ref == "dataset.v1"
    assert manifest.intent.authority_contract_id == "macaujc-source-authority-contract.v1"


def test_identity_drift_and_duplicate_hashes_fail_closed() -> None:
    with pytest.raises(ValueError, match="unique"):
        intent(input_snapshot_hashes=("3" * 64, "3" * 64))
    with pytest.raises(ValueError, match="trace identity"):
        EvidenceManifest(
            intent=intent(),
            mlflow_run_id="mlflow-run-1",
            openlineage_run_id="0190fa00-1111-7000-8222-334455667788",
            trace_id="7" * 32,
            result_status="VERIFIED",
            verifier="Independent Verifier",
            created_at=datetime(2026, 7, 14, 8, tzinfo=UTC),
            delivery_status="DELIVERED",
        ).with_hash()


def test_otel_span_preserves_formal_trace_identity() -> None:
    with record_otel_delivery(intent(), attributes={"xinao.test": "true"}) as span:
        assert f"{span.get_span_context().trace_id:032x}" == "6" * 32


def test_native_mlflow_adapter_logs_only_run_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def __init__(self, *, tracking_uri: str):
            calls.append(("tracking_uri", tracking_uri))

        def get_experiment_by_name(self, name: str):
            calls.append(("experiment_lookup", name))
            return None

        def create_experiment(self, name: str):
            calls.append(("experiment_create", name))
            return "experiment-1"

        def search_runs(self, experiment_ids, *, filter_string: str, max_results: int):
            calls.append(("search_runs", (experiment_ids, filter_string, max_results)))
            return []

        def create_run(self, experiment_id: str, *, tags: dict[str, str]):
            calls.append(("create_run", (experiment_id, tags)))
            return SimpleNamespace(info=SimpleNamespace(run_id="run-1"))

        def log_batch(self, run_id: str, *, params, tags):
            calls.append(("log_batch", (run_id, params, tags)))

    monkeypatch.setattr("xinao.lineage.adapters.MlflowClient", FakeClient)
    _, run_id = create_mlflow_run(intent(), tracking_uri="http://mlflow.test")

    assert run_id == "run-1"
    assert [name for name, _ in calls] == [
        "tracking_uri",
        "experiment_lookup",
        "experiment_create",
        "search_runs",
        "create_run",
        "log_batch",
    ]


def test_openlineage_adapter_emits_start_and_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted = []

    class FakeClient:
        def __init__(self, *, url: str):
            assert url == "http://lineage.test"

        def emit(self, value):
            emitted.append(value)

    monkeypatch.setattr("xinao.lineage.adapters.OpenLineageClient", FakeClient)
    run_id = emit_openlineage_run(
        intent(), url="http://lineage.test", event_time="2026-07-14T08:00:00.000Z"
    )

    assert run_id == "0190fa00-1111-7000-8222-334455667788"
    assert [event.eventType.value for event in emitted] == ["START", "COMPLETE"]
    assert all(len(event.inputs) == 7 for event in emitted)
    assert all(len(event.outputs) == 1 for event in emitted)
