"""Thin native MLflow, OpenLineage, and OpenTelemetry delivery adapters."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path

import requests
from mlflow.entities import Param, RunTag
from mlflow.tracking import MlflowClient
from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import (
    InputDataset,
    Job,
    OutputDataset,
    Run,
    RunEvent,
    RunState,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

from .models import EvidenceManifest, LineageIntent

PRODUCER = "https://xinao.local/spec/lineage-producer/v1"
NAMESPACE = "xinao"
JOB_NAME = "xinao-discovery.settlement-lineage"


def read_marquez_run(base_url: str, run_id: str) -> dict[str, object]:
    """Read back the exact OpenLineage run and require its terminal state."""
    endpoint = f"{base_url.rstrip('/')}/api/v1/jobs"
    response = requests.get(endpoint, timeout=20)
    response.raise_for_status()
    payload = response.json()
    for job in payload.get("jobs", []):
        identity = job.get("id", {})
        if identity.get("namespace") != NAMESPACE or identity.get("name") != JOB_NAME:
            continue
        latest = job.get("latestRun") or {}
        if latest.get("id") == run_id:
            if latest.get("state") != "COMPLETED":
                raise AssertionError(
                    f"Marquez run {run_id} is {latest.get('state')}, not COMPLETED"
                )
            return latest
    raise AssertionError(f"Marquez did not read back OpenLineage run {run_id}")


def create_mlflow_run(
    intent: LineageIntent,
    *,
    tracking_uri: str,
    experiment_name: str = "xinao-discovery",
) -> tuple[MlflowClient, str]:
    if intent.intent_hash is None:
        raise ValueError("lineage intent must be hash sealed")
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(experiment_name)
    experiment_id = (
        client.create_experiment(experiment_name)
        if experiment is None
        else experiment.experiment_id
    )
    existing = client.search_runs(
        [experiment_id],
        filter_string=f"tags.xinao.lineage_ref = '{intent.lineage_ref}'",
        max_results=2,
    )
    if len(existing) > 1:
        raise RuntimeError(f"multiple MLflow runs found for lineage {intent.lineage_ref}")
    if existing:
        return client, existing[0].info.run_id
    run = client.create_run(
        experiment_id,
        tags={
            "xinao.authority": "domain-event-ledger",
            "xinao.correlation_id": intent.correlation_id,
            "xinao.lineage_ref": intent.lineage_ref,
            "xinao.settlement_ref": intent.settlement_ref,
            "xinao.trace_id": intent.trace_id,
        },
    )
    client.log_batch(
        run.info.run_id,
        params=[
            Param("dataset_ref", intent.dataset_ref),
            Param("baseline_ref", intent.baseline_ref),
            Param("rule_version", intent.rule_version),
            Param("candidate_ref", intent.candidate_ref),
            Param("validation_ref", intent.validation_ref),
        ],
        tags=[RunTag("xinao.intent_hash", intent.intent_hash)],
    )
    return client, run.info.run_id


def complete_mlflow_run(
    client: MlflowClient,
    *,
    run_id: str,
    manifest: EvidenceManifest,
    manifest_path: Path,
) -> None:
    if manifest.manifest_hash is None:
        raise ValueError("evidence manifest must be hash sealed")
    client.set_tag(run_id, "xinao.manifest_hash", manifest.manifest_hash)
    client.set_tag(run_id, "xinao.result_status", manifest.result_status)
    client.log_artifact(run_id, str(manifest_path), artifact_path="evidence")
    # MLflow 2.22 prints an emoji URL hint before updating the run. Windows GBK
    # consoles cannot encode it, so isolate that incidental stdout without
    # changing process-wide encoding or suppressing the actual API operation.
    with redirect_stdout(StringIO()):
        client.set_terminated(run_id, status="FINISHED")


def emit_openlineage_run(
    intent: LineageIntent,
    *,
    url: str,
    event_time: str,
) -> str:
    client = OpenLineageClient(url=url)
    run = Run(runId=intent.openlineage_run_id)
    job = Job(namespace=NAMESPACE, name=JOB_NAME)
    inputs = [
        InputDataset(namespace=NAMESPACE, name=f"authority/{intent.authority_contract_id}"),
        InputDataset(namespace=NAMESPACE, name=f"dataset/{intent.dataset_ref}"),
        InputDataset(namespace=NAMESPACE, name=f"baseline/{intent.baseline_ref}"),
        InputDataset(namespace=NAMESPACE, name=f"rule/{intent.rule_version}"),
        InputDataset(namespace=NAMESPACE, name=f"candidate/{intent.candidate_ref}"),
        InputDataset(namespace=NAMESPACE, name=f"validation/{intent.validation_ref}"),
        InputDataset(namespace=NAMESPACE, name=f"freeze/{intent.frozen_decision_ref}"),
    ]
    outputs = [
        OutputDataset(namespace=NAMESPACE, name=f"settlement/{intent.settlement_ref}"),
    ]
    for state in (RunState.START, RunState.COMPLETE):
        client.emit(
            RunEvent(
                eventTime=event_time,
                producer=PRODUCER,
                eventType=state,
                run=run,
                job=job,
                inputs=inputs,
                outputs=outputs,
            )
        )
    return intent.openlineage_run_id


@contextmanager
def record_otel_delivery(intent: LineageIntent, *, attributes: Mapping[str, str] | None = None):
    trace_id = int(intent.trace_id, 16)
    parent_span_id = int(intent.intent_hash[-16:], 16) if intent.intent_hash else 1
    context = set_span_in_context(
        NonRecordingSpan(
            SpanContext(
                trace_id=trace_id,
                span_id=parent_span_id or 1,
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
        )
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("xinao.lineage", "1.0.0")
    with tracer.start_as_current_span("xinao.evidence.delivery", context=context) as span:
        span.set_attribute("xinao.correlation_id", intent.correlation_id)
        span.set_attribute("xinao.settlement_ref", intent.settlement_ref)
        span.set_attribute("xinao.intent_hash", intent.intent_hash or "")
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        yield span
    provider.shutdown()
    spans = exporter.get_finished_spans()
    if len(spans) != 1 or f"{spans[0].context.trace_id:032x}" != intent.trace_id:
        raise AssertionError("OpenTelemetry trace identity was not preserved")
