"""Deliver one formal settlement lineage intent through MLflow, Marquez, OTel, and outbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from xinao.canonical import canonical_sha256
from xinao.canonical.identifiers import generate_uuid7
from xinao.catalog.compiler import write_atomic
from xinao.ledger import append_event, create_event
from xinao.lineage import (
    EvidenceManifest,
    LineageIntent,
    build_lineage_intent,
    complete_mlflow_run,
    create_mlflow_run,
    emit_openlineage_run,
    read_marquez_run,
    record_otel_delivery,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dvc-lock", type=Path, default=Path("dvc.lock"))
    parser.add_argument("--tracking-uri", default="http://shiyan-zhuiji:5000")
    parser.add_argument("--lineage-url", default="http://xueyuan-zhuiji:5001")
    parser.add_argument("--lineage-read-url", default="http://xueyuan-zhuiji:5001")
    return parser.parse_args()


def now_utc() -> datetime:
    value = datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(repo: Path) -> tuple[str, bool]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "xinao_discovery"],
        cwd=repo.parent,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sha, bool(status.strip())


def event(
    *,
    event_type: str,
    aggregate_id: str,
    version: int,
    payload: dict[str, Any],
    correlation_id: str,
    prior_event_hash: str | None,
    trace_id: str,
):
    return create_event(
        event_id=generate_uuid7(),
        event_type=event_type,
        aggregate_type="EvidenceBundle",
        aggregate_id=aggregate_id,
        aggregate_version=version,
        occurred_at=now_utc(),
        correlation_id=correlation_id,
        causation_id=None,
        actor="Codex-single-writer",
        command_id=generate_uuid7(),
        idempotency_key=f"p7:{event_type}:{aggregate_id}",
        payload_schema_version=f"{event_type}.v1",
        payload=payload,
        prior_event_hash=prior_event_hash,
        trace_id=trace_id,
        workflow_id="xinao-mainline-p7-lineage-canary",
        run_id="xinao-mainline-20260714T014700",
        artifact_refs=("dvc://lineage-seed",),
    )


def append(conn: psycopg.Connection, record, *, outbox_id: str) -> str:
    conn.execute("SET ROLE xinao_discovery_event_writer")
    try:
        return append_event(
            conn,
            record,
            outbox_id=outbox_id,
            topic="xinao.evidence-lineage.v1",
        )
    finally:
        conn.execute("RESET ROLE")


def read_settlement(conn: psycopg.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT s.settlement_id,s.settlement_hash,s.rule_ref,s.journal_group_id,
               s.frozen_decision_id,s.outcome_id,f.decision_hash,f.candidate_refs,
               f.payload,o.result_hash,e.workflow_id,e.run_id,j.group_hash
        FROM settlement_record s
        JOIN frozen_decision f ON f.decision_id=s.frozen_decision_id
        JOIN outcome_observation o ON o.outcome_id=s.outcome_id
        JOIN domain_event e ON e.event_id=s.event_id
        JOIN journal_group j ON j.journal_group_id=s.journal_group_id
        ORDER BY s.created_at DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("P7 probe requires the verified P6 canary settlement")
    return {
        "settlement_ref": row[0],
        "settlement_hash": row[1],
        "rule_ref": row[2],
        "journal_group_ref": row[3],
        "frozen_decision_ref": row[4],
        "outcome_ref": row[5],
        "frozen_decision_hash": row[6],
        "candidate_ref": row[7][0],
        "frozen_payload": row[8],
        "outcome_hash": row[9],
        "workflow_id": row[10],
        "run_id": row[11],
        "journal_group_hash": row[12],
    }


def read_pending_intent(conn: psycopg.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT e.payload,e.event_hash,e.correlation_id,e.trace_id,o.outbox_id
        FROM domain_event e
        JOIN transactional_outbox o ON o.event_id=e.event_id
        WHERE e.aggregate_type='EvidenceBundle'
          AND e.event_type='LineageIntentRecorded'
          AND o.published_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM domain_event delivered
              WHERE delivered.aggregate_type=e.aggregate_type
                AND delivered.aggregate_id=e.aggregate_id
                AND delivered.aggregate_version=2
          )
        ORDER BY e.recorded_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "intent": LineageIntent.model_validate(row[0]),
        "event_hash": row[1],
        "correlation_id": row[2],
        "event_trace_id": row[3],
        "outbox_id": row[4],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[2]
    code_sha, code_dirty = git_state(repo)
    dvc_lock_hash = sha256_file(args.dvc_lock)
    dvc_artifact_hash = sha256_file(repo / "artifacts" / "p7" / "lineage_seed.json")
    config_hash = canonical_sha256(
        {
            "tracking_uri": args.tracking_uri,
            "lineage_url": args.lineage_url,
            "dvc_lock_hash": dvc_lock_hash,
        }
    )
    with psycopg.connect(
        host=os.environ.get("XINAO_DB_HOST", "shiwu-ku"),
        port=os.environ.get("XINAO_DB_PORT", "5432"),
        dbname=args.database,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    ) as conn:
        settlement = read_settlement(conn)
        pending = read_pending_intent(conn)
        if pending is None:
            correlation_id = generate_uuid7()
            trace_id = hashlib.sha256(correlation_id.encode()).hexdigest()[:32]
            lineage_ref = generate_uuid7()
            intent = build_lineage_intent(
                lineage_ref=lineage_ref,
                correlation_id=correlation_id,
                session_id="xinao-mainline-20260714T014700",
                workflow_id=settlement["workflow_id"],
                run_id=settlement["run_id"],
                code_git_sha=code_sha,
                code_dirty=code_dirty,
                config_hash=config_hash,
                dvc_lock_hash=dvc_lock_hash,
                authority_contract_id="macaujc-source-authority-contract.v1",
                source_ref="macaujc2",
                dataset_ref="macaujc2-authority-dataset-2024-01-01--2026-07-01",
                dataset_hash="57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6",
                baseline_ref="baseline-odds-water.v1",
                baseline_hash="634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1",
                rule_version=settlement["rule_ref"],
                experiment_ref="p6-canary.synthetic-positive.v1",
                candidate_ref=settlement["candidate_ref"],
                validation_ref="validation.signal.p6.v1",
                validation_hash="a" * 64,
                frozen_decision_ref=settlement["frozen_decision_ref"],
                frozen_decision_hash=settlement["frozen_decision_hash"],
                outcome_ref=settlement["outcome_ref"],
                settlement_ref=settlement["settlement_ref"],
                settlement_hash=settlement["settlement_hash"],
                input_snapshot_hashes=(
                    settlement["frozen_decision_hash"],
                    settlement["outcome_hash"],
                ),
                output_hashes=(
                    settlement["settlement_hash"],
                    settlement["journal_group_hash"],
                ),
                openlineage_run_id=correlation_id,
                trace_id=trace_id,
            )
            intent_event = event(
                event_type="LineageIntentRecorded",
                aggregate_id=lineage_ref,
                version=1,
                payload=intent.model_dump(mode="json"),
                correlation_id=correlation_id,
                prior_event_hash=None,
                trace_id=correlation_id,
            )
            intent_event_hash = intent_event.event_hash
            intent_outbox_id = generate_uuid7()
            with conn.transaction():
                append(conn, intent_event, outbox_id=intent_outbox_id)

            failed_delivery = ""
            try:
                emit_openlineage_run(
                    intent,
                    url="http://127.0.0.1:9",
                    event_time=now_utc().isoformat().replace("+00:00", "Z"),
                )
            except Exception as exc:
                failed_delivery = type(exc).__name__
            if not failed_delivery:
                raise AssertionError("unreachable OpenLineage endpoint unexpectedly succeeded")
        else:
            intent = pending["intent"]
            lineage_ref = intent.lineage_ref
            correlation_id = pending["correlation_id"]
            trace_id = intent.trace_id
            intent_event_hash = pending["event_hash"]
            intent_outbox_id = pending["outbox_id"]
            failed_delivery = "recovered_pending_intent"
        pending_before_retry = conn.execute(
            "SELECT published_at IS NULL FROM transactional_outbox WHERE outbox_id=%s",
            (intent_outbox_id,),
        ).fetchone()[0]
        if not pending_before_retry:
            raise AssertionError("observability failure lost the retryable outbox item")

        with record_otel_delivery(
            intent,
            attributes={
                "xinao.mlflow.uri": args.tracking_uri,
                "xinao.openlineage.url": args.lineage_url,
            },
        ):
            mlflow_client, mlflow_run_id = create_mlflow_run(intent, tracking_uri=args.tracking_uri)
            openlineage_run_id = emit_openlineage_run(
                intent,
                url=args.lineage_url,
                event_time=now_utc().isoformat().replace("+00:00", "Z"),
            )
        manifest = EvidenceManifest(
            intent=intent,
            mlflow_run_id=mlflow_run_id,
            openlineage_run_id=openlineage_run_id,
            trace_id=trace_id,
            result_status="VERIFIED",
            verifier="Codex + live service readback",
            created_at=now_utc(),
            delivery_status="DELIVERED",
        ).with_hash()
        manifest_path = args.output.with_name("evidence_manifest.json")
        write_atomic(manifest_path, manifest.model_dump(mode="json"))
        complete_mlflow_run(
            mlflow_client,
            run_id=mlflow_run_id,
            manifest=manifest,
            manifest_path=manifest_path,
        )
        mlflow_run = mlflow_client.get_run(mlflow_run_id)
        if mlflow_run.data.tags.get("xinao.manifest_hash") != manifest.manifest_hash:
            raise AssertionError("MLflow manifest hash readback failed")
        marquez_run = read_marquez_run(args.lineage_read_url, openlineage_run_id)

        receipt_event = event(
            event_type="LineageDelivered",
            aggregate_id=lineage_ref,
            version=2,
            payload=manifest.model_dump(mode="json"),
            correlation_id=correlation_id,
            prior_event_hash=intent_event_hash,
            trace_id=correlation_id,
        )
        receipt_outbox_id = generate_uuid7()
        with conn.transaction():
            append(conn, receipt_event, outbox_id=receipt_outbox_id)
            conn.execute("SET ROLE xinao_discovery_outbox_publisher")
            try:
                assert (
                    conn.execute(
                        "SELECT xinao_advance_outbox(%s,true)", (intent_outbox_id,)
                    ).fetchone()[0]
                    == 1
                )
                assert (
                    conn.execute(
                        "SELECT xinao_advance_outbox(%s,true)", (receipt_outbox_id,)
                    ).fetchone()[0]
                    == 1
                )
            finally:
                conn.execute("RESET ROLE")
        outbox_readback = conn.execute(
            "SELECT count(*),count(*) FILTER (WHERE published_at IS NOT NULL) "
            "FROM transactional_outbox WHERE outbox_id IN (%s,%s)",
            (intent_outbox_id, receipt_outbox_id),
        ).fetchone()
        assert outbox_readback == (2, 2)
        stream = conn.execute(
            "SELECT event_type,aggregate_version,event_hash FROM domain_event "
            "WHERE aggregate_type='EvidenceBundle' AND aggregate_id=%s ORDER BY aggregate_version",
            (lineage_ref,),
        ).fetchall()
        assert [row[0] for row in stream] == ["LineageIntentRecorded", "LineageDelivered"]

    return {
        "schema_version": "xinao.lineage_delivery_probe.v1",
        "status": "verified",
        "database": args.database,
        "lineage_ref": lineage_ref,
        "correlation_id": correlation_id,
        "intent_hash": intent.intent_hash,
        "manifest_hash": manifest.manifest_hash,
        "mlflow_run_id": mlflow_run_id,
        "mlflow_status": mlflow_run.info.status,
        "openlineage_run_id": openlineage_run_id,
        "marquez_run_id": marquez_run.get("id"),
        "marquez_state": marquez_run.get("state"),
        "trace_id": trace_id,
        "failed_delivery_class": failed_delivery,
        "pending_before_retry": pending_before_retry,
        "outbox_after_delivery": list(outbox_readback),
        "domain_event_stream": [list(row) for row in stream],
        "reverse_links": {
            key: intent.model_dump(mode="json")[key]
            for key in (
                "authority_contract_id",
                "source_ref",
                "dataset_ref",
                "baseline_ref",
                "rule_version",
                "experiment_ref",
                "candidate_ref",
                "validation_ref",
                "frozen_decision_ref",
                "outcome_ref",
                "settlement_ref",
                "workflow_id",
                "run_id",
            )
        },
        "dvc_lock_hash": dvc_lock_hash,
        "dvc_artifact_hash": dvc_artifact_hash,
        "dvc_cache_dir": "D:/XINAO_RESEARCH_RUNTIME/projects/xinao_discovery/cache/dvc",
        "dvc_remote_dir": "E:/XINAO_RESEARCH_DATA/xinao_discovery/dvc-remote",
        "code_git_sha": code_sha,
        "code_dirty": code_dirty,
    }


def main() -> int:
    args = parse_args()
    report = run(args)
    write_atomic(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
