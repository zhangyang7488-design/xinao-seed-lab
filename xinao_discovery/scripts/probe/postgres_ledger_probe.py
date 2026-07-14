"""Exercise domain-ledger and confirmation-vault migrations against live PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from xinao.canonical.hashing import canonical_sha256
from xinao.canonical.identifiers import generate_uuid7
from xinao.canonical.jcs import canonical_dumps
from xinao.canonical.time_profile import format_utc
from xinao.ledger import EventRecord, create_event, replay_stream, verify_event

APPEND_SQL = "SELECT xinao_append_event(" + ",".join(["%s"] * 24) + ")"
FREEZE_SQL = "SELECT xinao_freeze_decision(" + ",".join(["%s"] * 36) + ")"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain-db", required=True)
    parser.add_argument("--confirmation-db", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


@contextmanager
def connection(database: str, *, autocommit: bool = False):
    with psycopg.connect(
        host=os.environ.get("XINAO_DB_HOST", "shiwu-ku"),
        port=os.environ.get("XINAO_DB_PORT", "5432"),
        dbname=database,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=autocommit,
    ) as conn:
        yield conn


def alembic(config: str, database: str, *arguments: str, allow_destructive: bool = False) -> None:
    env = os.environ.copy()
    env["POSTGRES_DB"] = database
    if allow_destructive:
        env["XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE"] = "isolated-canary-reset"
    else:
        env.pop("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE", None)
    subprocess.run(
        ["alembic", "-c", config, *arguments],
        check=True,
        env=env,
        text=True,
    )


def json_arguments(arguments: tuple[Any, ...]) -> tuple[Any, ...]:
    values = list(arguments)
    values[12] = Jsonb(values[12])
    values[21] = Jsonb(values[21])
    return tuple(values)


def append(conn: psycopg.Connection, event: EventRecord, *, outbox_id: str) -> str:
    arguments = event.append_arguments(outbox_id=outbox_id, topic="xinao.domain-events.v1")
    return conn.execute(APPEND_SQL, json_arguments(arguments)).fetchone()[0]


def expect_database_error(
    conn: psycopg.Connection, statement: str | sql.Composed, parameters: Any = None
) -> str:
    try:
        with conn.transaction():
            conn.execute(statement, parameters)
    except psycopg.Error as exc:
        return exc.sqlstate or exc.__class__.__name__
    raise AssertionError("expected PostgreSQL to reject the operation")


def expect_alembic_guard(config: str, database: str) -> str:
    try:
        alembic(config, database, "downgrade", "base")
    except subprocess.CalledProcessError as exc:
        return f"rejected:{exc.returncode}"
    raise AssertionError("destructive downgrade was not guarded")


def event_from_row(row: tuple[Any, ...]) -> EventRecord:
    return EventRecord(
        event_id=row[0],
        event_type=row[1],
        aggregate_type=row[2],
        aggregate_id=row[3],
        aggregate_version=row[4],
        occurred_at=row[5],
        correlation_id=row[6],
        causation_id=row[7],
        actor=row[8],
        command_id=row[9],
        idempotency_key=row[10],
        payload_schema_version=row[11],
        payload=row[12],
        payload_hash=row[13],
        prior_event_hash=row[14],
        event_hash=row[15],
        trace_id=row[16],
        workflow_id=row[17],
        run_id=row[18],
        artifact_refs=tuple(row[19]),
    )


def make_event(
    *,
    aggregate_id: str,
    version: int,
    prior_hash: str | None,
    idempotency_key: str,
    payload: dict[str, Any],
    event_type: str = "CanaryRecorded",
    aggregate_type: str = "CanaryAggregate",
    occurred_at: datetime | None = None,
) -> EventRecord:
    return create_event(
        event_id=generate_uuid7(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        occurred_at=occurred_at or datetime(2026, 7, 14, 4, version, tzinfo=UTC),
        correlation_id=generate_uuid7(),
        causation_id=None,
        actor="Codex-P2-canary",
        command_id=generate_uuid7(),
        idempotency_key=idempotency_key,
        payload_schema_version="canary-event.v1",
        payload=payload,
        prior_event_hash=prior_hash,
        trace_id=generate_uuid7(),
        workflow_id="xinao-p2-postgres-canary",
        run_id="run-live-1",
    )


def exercise_domain(database: str) -> dict[str, Any]:
    report: dict[str, Any] = {"database": database, "checks": {}}
    alembic("migrations/alembic.ini", database, "downgrade", "base")
    alembic("migrations/alembic.ini", database, "upgrade", "0001_event_ledger")
    first = make_event(
        aggregate_id="aggregate-1",
        version=1,
        prior_hash=None,
        idempotency_key="domain-canary-1",
        payload={"value": 1},
    )
    first_outbox = generate_uuid7()
    with connection(database) as conn:
        appended_event_id = append(conn, first, outbox_id=first_outbox)
        assert appended_event_id == first.event_id
        conn.commit()
    alembic("migrations/alembic.ini", database, "upgrade", "head")
    report["checks"]["event_only_downgrade_guard"] = expect_alembic_guard(
        "migrations/alembic.ini", database
    )

    with connection(database, autocommit=True) as conn:
        sequence_key = conn.execute(
            "SELECT event_sequence_key FROM domain_event WHERE event_id=%s",
            (first.event_id,),
        ).fetchone()[0]
        assert sequence_key == first.sequence_key
        report["checks"]["data_migration_sequence_backfill"] = sequence_key

        before = conn.execute(
            "SELECT (SELECT count(*) FROM domain_event),"
            "(SELECT count(*) FROM command_dedup),"
            "(SELECT count(*) FROM transactional_outbox)"
        ).fetchone()
        replayed_event_id = append(conn, first, outbox_id=first_outbox)
        assert replayed_event_id == first.event_id
        after = conn.execute(
            "SELECT (SELECT count(*) FROM domain_event),"
            "(SELECT count(*) FROM command_dedup),"
            "(SELECT count(*) FROM transactional_outbox)"
        ).fetchone()
        assert before == after == (1, 1, 1)
        report["checks"]["idempotent_event_replay"] = list(after)

        conflict = make_event(
            aggregate_id="aggregate-1",
            version=2,
            prior_hash=first.event_hash,
            idempotency_key=first.idempotency_key,
            payload={"value": "conflict"},
        )
        report["checks"]["idempotency_conflict_sqlstate"] = expect_database_error(
            conn,
            APPEND_SQL,
            json_arguments(
                conflict.append_arguments(
                    outbox_id=generate_uuid7(), topic="xinao.domain-events.v1"
                )
            ),
        )
        late = make_event(
            aggregate_id="aggregate-1",
            version=3,
            prior_hash=first.event_hash,
            idempotency_key="domain-canary-late",
            payload={"value": 3},
        )
        report["checks"]["late_version_sqlstate"] = expect_database_error(
            conn,
            APPEND_SQL,
            json_arguments(
                late.append_arguments(outbox_id=generate_uuid7(), topic="xinao.domain-events.v1")
            ),
        )
        hash_check_event = make_event(
            aggregate_id="aggregate-1",
            version=2,
            prior_hash=first.event_hash,
            idempotency_key="domain-canary-hash-check",
            payload={"value": "hash-check"},
        )
        hash_arguments = list(
            json_arguments(
                hash_check_event.append_arguments(
                    outbox_id=generate_uuid7(), topic="xinao.domain-events.v1"
                )
            )
        )
        hash_arguments[13] = b"{}"
        report["checks"]["payload_canonical_mismatch_sqlstate"] = expect_database_error(
            conn, APPEND_SQL, tuple(hash_arguments)
        )
        hash_arguments = list(
            json_arguments(
                hash_check_event.append_arguments(
                    outbox_id=generate_uuid7(), topic="xinao.domain-events.v1"
                )
            )
        )
        hash_arguments[16] = b"{}"
        report["checks"]["event_canonical_mismatch_sqlstate"] = expect_database_error(
            conn, APPEND_SQL, tuple(hash_arguments)
        )
        hash_arguments = list(
            json_arguments(
                hash_check_event.append_arguments(
                    outbox_id=generate_uuid7(), topic="xinao.domain-events.v1"
                )
            )
        )
        hash_arguments[8] = "canonical-parameter-drift"
        report["checks"]["event_parameter_drift_sqlstate"] = expect_database_error(
            conn, APPEND_SQL, tuple(hash_arguments)
        )
        second = make_event(
            aggregate_id="aggregate-1",
            version=2,
            prior_hash=first.event_hash,
            idempotency_key="domain-canary-2",
            payload={"value": 2},
        )
        append(conn, second, outbox_id=generate_uuid7())
        rows = conn.execute(
            """
            SELECT event_id,event_type,aggregate_type,aggregate_id,aggregate_version,
                   occurred_at,correlation_id,causation_id,actor,command_id,
                   idempotency_key,payload_schema_version,payload,payload_hash,
                   prior_event_hash,event_hash,trace_id,workflow_id,run_id,artifact_refs
            FROM domain_event
            WHERE aggregate_type='CanaryAggregate' AND aggregate_id='aggregate-1'
            ORDER BY aggregate_version
            """
        ).fetchall()
        replay = replay_stream(event_from_row(row) for row in rows)
        assert replay.last_event_hash == second.event_hash
        report["checks"]["event_replay"] = asdict(replay)
        report["checks"]["event_update_sqlstate"] = expect_database_error(
            conn, "UPDATE domain_event SET actor='tampered' WHERE event_id=%s", (first.event_id,)
        )
        report["checks"]["event_delete_sqlstate"] = expect_database_error(
            conn, "DELETE FROM domain_event WHERE event_id=%s", (first.event_id,)
        )
        report["checks"]["event_truncate_sqlstate"] = expect_database_error(
            conn, "TRUNCATE domain_event CASCADE"
        )
        report["checks"]["head_delete_sqlstate"] = expect_database_error(
            conn,
            "DELETE FROM aggregate_head WHERE aggregate_type='CanaryAggregate' "
            "AND aggregate_id='aggregate-1'",
        )
        report["checks"]["head_invalid_update_sqlstate"] = expect_database_error(
            conn,
            "UPDATE aggregate_head SET version=version+2 "
            "WHERE aggregate_type='CanaryAggregate' AND aggregate_id='aggregate-1'",
        )
        report["checks"]["head_truncate_sqlstate"] = expect_database_error(
            conn, "TRUNCATE aggregate_head CASCADE"
        )
        report["checks"]["outbox_delete_sqlstate"] = expect_database_error(
            conn, "DELETE FROM transactional_outbox WHERE event_id=%s", (first.event_id,)
        )
        report["checks"]["outbox_payload_update_sqlstate"] = expect_database_error(
            conn,
            "UPDATE transactional_outbox SET payload='{}' WHERE event_id=%s",
            (first.event_id,),
        )
        report["checks"]["outbox_truncate_sqlstate"] = expect_database_error(
            conn, "TRUNCATE transactional_outbox"
        )
        report["checks"]["dedup_truncate_sqlstate"] = expect_database_error(
            conn, "TRUNCATE command_dedup CASCADE"
        )
        conn.execute("SET ROLE xinao_discovery_outbox_publisher")
        advanced = conn.execute("SELECT xinao_advance_outbox(%s,true)", (first_outbox,)).fetchone()[
            0
        ]
        assert advanced == 1
        report["checks"]["outbox_repeat_publish_sqlstate"] = expect_database_error(
            conn, "SELECT xinao_advance_outbox(%s,true)", (first_outbox,)
        )
        report["checks"]["publisher_direct_payload_update_sqlstate"] = expect_database_error(
            conn,
            "UPDATE transactional_outbox SET payload='{}' WHERE outbox_id=%s",
            (first_outbox,),
        )
        conn.execute("RESET ROLE")
        delivery_state = conn.execute(
            "SELECT attempt_count,published_at IS NOT NULL FROM transactional_outbox "
            "WHERE outbox_id=%s",
            (first_outbox,),
        ).fetchone()
        assert delivery_state == (1, True)
        report["checks"]["outbox_publisher_role_advance"] = list(delivery_state)

        conn.execute("SET ROLE xinao_discovery_projection_reader")
        assert conn.execute("SELECT count(*) FROM domain_event").fetchone()[0] == 2
        report["checks"]["projection_write_denied_sqlstate"] = expect_database_error(
            conn,
            "DELETE FROM domain_event WHERE event_id=%s",
            (first.event_id,),
        )
        conn.execute("RESET ROLE")

        writer_event = make_event(
            aggregate_id="writer-aggregate",
            version=1,
            prior_hash=None,
            idempotency_key="domain-writer-role",
            payload={"writer": True},
        )
        conn.execute("SET ROLE xinao_discovery_event_writer")
        writer_event_id = append(conn, writer_event, outbox_id=generate_uuid7())
        assert writer_event_id == writer_event.event_id
        report["checks"]["writer_direct_insert_denied_sqlstate"] = expect_database_error(
            conn,
            "INSERT INTO domain_event(event_id) VALUES ('forbidden')",
        )
        conn.execute("RESET ROLE")

        decision_id = generate_uuid7()
        decision_plan_id = generate_uuid7()
        candidates = ["candidate:special-number-settlement.v0"]
        candidate_hash = canonical_sha256(candidates)
        target_start = datetime(2099, 1, 1, tzinfo=UTC)
        target_end = datetime(2099, 1, 7, tzinfo=UTC)
        target_open = datetime(2100, 1, 1, tzinfo=UTC)
        freeze_deadline = datetime(2099, 12, 31, tzinfo=UTC)
        knowledge_cutoff = datetime(2026, 7, 14, tzinfo=UTC)
        decision_basis = {
            "decision_id": decision_id,
            "decision_plan_id": decision_plan_id,
            "target_window_start": format_utc(target_start),
            "target_window_end": format_utc(target_end),
            "target_open_time": format_utc(target_open),
            "candidate_refs": candidates,
            "candidate_refs_hash": candidate_hash,
            "freeze_deadline": format_utc(freeze_deadline),
            "knowledge_cutoff": format_utc(knowledge_cutoff),
            "decision_type": "NO_ACTION",
        }
        decision_hash = canonical_sha256(decision_basis)
        freeze_payload = {
            "decision_id": decision_id,
            "decision_hash": decision_hash,
            "decision_plan_id": decision_plan_id,
        }
        freeze_event = make_event(
            aggregate_id=decision_id,
            version=1,
            prior_hash=None,
            idempotency_key="freeze-canary-1",
            payload=freeze_payload,
            event_type="NoActionFrozen",
            aggregate_type="FrozenDecision",
        )
        freeze_args = (
            *json_arguments(
                freeze_event.append_arguments(
                    outbox_id=generate_uuid7(), topic="xinao.decision-frozen.v1"
                )
            ),
            decision_id,
            decision_plan_id,
            target_start,
            target_end,
            target_open,
            Jsonb(candidates),
            candidate_hash,
            freeze_deadline,
            knowledge_cutoff,
            "NO_ACTION",
            canonical_dumps(decision_basis),
            decision_hash,
        )
        conn.execute("SET ROLE xinao_discovery_freeze_writer")
        assert conn.execute(FREEZE_SQL, freeze_args).fetchone()[0] == decision_id
        conn.execute("RESET ROLE")
        frozen_counts = conn.execute(
            "SELECT (SELECT count(*) FROM frozen_decision),"
            "(SELECT count(*) FROM domain_event WHERE aggregate_type='FrozenDecision'),"
            "(SELECT count(*) FROM transactional_outbox o JOIN domain_event e "
            " ON e.event_id=o.event_id WHERE e.aggregate_type='FrozenDecision')"
        ).fetchone()
        assert frozen_counts == (1, 1, 1)
        conn.execute("SET ROLE xinao_discovery_freeze_writer")
        assert conn.execute(FREEZE_SQL, freeze_args).fetchone()[0] == decision_id
        conn.execute("RESET ROLE")
        assert conn.execute("SELECT count(*) FROM frozen_decision").fetchone()[0] == 1
        report["checks"]["atomic_idempotent_freeze"] = list(frozen_counts)
        readback_decision = conn.execute(
            "SELECT decision_hash,payload,event_id FROM frozen_decision WHERE decision_id=%s",
            (decision_id,),
        ).fetchone()
        assert readback_decision[0] == canonical_sha256(decision_basis)
        freeze_row = conn.execute(
            """
            SELECT event_id,event_type,aggregate_type,aggregate_id,aggregate_version,
                   occurred_at,correlation_id,causation_id,actor,command_id,
                   idempotency_key,payload_schema_version,payload,payload_hash,
                   prior_event_hash,event_hash,trace_id,workflow_id,run_id,artifact_refs
            FROM domain_event WHERE event_id=%s
            """,
            (readback_decision[2],),
        ).fetchone()
        verify_event(event_from_row(freeze_row))
        assert freeze_row[15] == freeze_event.event_hash
        report["checks"]["freeze_hash_readback"] = {
            "decision_hash": readback_decision[0],
            "event_hash": freeze_row[15],
        }
        report["checks"]["freeze_update_sqlstate"] = expect_database_error(
            conn,
            "UPDATE frozen_decision SET decision_type='ACTION' WHERE decision_id=%s",
            (decision_id,),
        )
        report["checks"]["freeze_delete_sqlstate"] = expect_database_error(
            conn, "DELETE FROM frozen_decision WHERE decision_id=%s", (decision_id,)
        )
        report["checks"]["freeze_truncate_sqlstate"] = expect_database_error(
            conn, "TRUNCATE frozen_decision"
        )

        late_decision_id = generate_uuid7()
        late_plan_id = generate_uuid7()
        late_start = datetime(2020, 1, 1, tzinfo=UTC)
        late_end = datetime(2020, 1, 2, tzinfo=UTC)
        late_open = datetime(2020, 1, 3, tzinfo=UTC)
        late_deadline = datetime(2020, 1, 2, tzinfo=UTC)
        late_cutoff = datetime(2020, 1, 1, tzinfo=UTC)
        late_basis = {
            "decision_id": late_decision_id,
            "decision_plan_id": late_plan_id,
            "target_window_start": format_utc(late_start),
            "target_window_end": format_utc(late_end),
            "target_open_time": format_utc(late_open),
            "candidate_refs": candidates,
            "candidate_refs_hash": candidate_hash,
            "freeze_deadline": format_utc(late_deadline),
            "knowledge_cutoff": format_utc(late_cutoff),
            "decision_type": "NO_ACTION",
        }
        late_hash = canonical_sha256(late_basis)
        late_payload = {"decision_id": late_decision_id, "decision_hash": late_hash}
        late_event = make_event(
            aggregate_id=late_decision_id,
            version=1,
            prior_hash=None,
            idempotency_key="freeze-late-1",
            payload=late_payload,
            event_type="NoActionFrozen",
            aggregate_type="FrozenDecision",
            occurred_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        late_args = (
            *json_arguments(
                late_event.append_arguments(
                    outbox_id=generate_uuid7(), topic="xinao.decision-frozen.v1"
                )
            ),
            late_decision_id,
            late_plan_id,
            late_start,
            late_end,
            late_open,
            Jsonb(candidates),
            candidate_hash,
            late_deadline,
            late_cutoff,
            "NO_ACTION",
            canonical_dumps(late_basis),
            late_hash,
        )
        before_late = conn.execute(
            "SELECT count(*) FROM domain_event WHERE aggregate_type='FrozenDecision'"
        ).fetchone()[0]
        conn.execute("SET ROLE xinao_discovery_freeze_writer")
        report["checks"]["late_freeze_sqlstate"] = expect_database_error(
            conn, FREEZE_SQL, late_args
        )
        conn.execute("RESET ROLE")
        after_late = conn.execute(
            "SELECT count(*) FROM domain_event WHERE aggregate_type='FrozenDecision'"
        ).fetchone()[0]
        assert before_late == after_late == 1
        report["checks"]["late_freeze_atomic_no_event"] = after_late

    report["checks"]["destructive_downgrade_guard"] = expect_alembic_guard(
        "migrations/alembic.ini", database
    )
    alembic(
        "migrations/alembic.ini",
        database,
        "downgrade",
        "base",
        allow_destructive=True,
    )
    alembic("migrations/alembic.ini", database, "upgrade", "head")
    with connection(database, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM domain_event").fetchone()[0] == 0
        report["checks"]["fresh_up_down_up"] = "PASS"
    return report


def exercise_confirmation(database: str) -> dict[str, Any]:
    report: dict[str, Any] = {"database": database, "checks": {}}
    config = "migrations/confirmation/alembic.ini"
    alembic(config, database, "downgrade", "base")
    alembic(config, database, "upgrade", "head")
    with connection(database, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO confirmation_private.vault_observation(
                observation_id,candidate_ref,partition_name,metric_value,raw_payload
            ) VALUES
                ('obs-1','candidate-v1','CONFIRMATION',0.25,'{"row":"secret-1"}'),
                ('obs-2','candidate-v1','CONFIRMATION',-0.05,'{"row":"secret-2"}'),
                ('obs-3','candidate-v1','FINAL_HOLDOUT',0.20,'{"row":"secret-3"}')
            """
        )
        conn.execute(
            """
            INSERT INTO confirmation_private.research_error_budget_ledger(
                budget_id,hypothesis_family,total_queries,remaining_queries
            ) VALUES ('budget-aggregate','family-aggregate',2,2),
                     ('budget-final','family-final',2,2)
            """
        )
        research_connect = conn.execute(
            "SELECT has_database_privilege("
            "'xinao_discovery_research_worker',current_database(),'CONNECT')"
        ).fetchone()[0]
        service_raw_read = conn.execute(
            "SELECT has_table_privilege("
            "'xinao_discovery_confirmation_service',"
            "'confirmation_private.vault_observation','SELECT')"
        ).fetchone()[0]
        service_api = conn.execute(
            "SELECT has_function_privilege("
            "'xinao_discovery_confirmation_service',"
            "'confirmation_api.query_candidate(text,text,text,text,text)','EXECUTE')"
        ).fetchone()[0]
        assert research_connect is False
        assert service_raw_read is False
        assert service_api is True
        report["checks"]["role_boundary"] = {
            "research_connect": research_connect,
            "service_raw_read": service_raw_read,
            "service_api_execute": service_api,
        }

        conn.execute("SET ROLE xinao_discovery_research_worker")
        report["checks"]["research_raw_read_denied_sqlstate"] = expect_database_error(
            conn, "SELECT * FROM confirmation_private.vault_observation"
        )
        conn.execute("RESET ROLE")
        conn.execute("SET ROLE xinao_discovery_confirmation_service")
        report["checks"]["service_raw_read_denied_sqlstate"] = expect_database_error(
            conn, "SELECT * FROM confirmation_private.vault_observation"
        )
        query_sql = "SELECT confirmation_api.query_candidate(%s,%s,%s,%s,%s)"
        first = conn.execute(
            query_sql,
            ("query-1", "budget-aggregate", "candidate-v1", "AGGREGATE_EFFECT", "idem-1"),
        ).fetchone()[0]
        assert first["status"] == "EXECUTED"
        assert first["remaining_queries"] == 1
        assert first["disclosure"]["sample_size"] == 2
        assert set(first["disclosure"]) == {
            "verdict",
            "effect_mean",
            "effect_interval_90",
            "sample_size",
            "reason_code",
        }
        interval = first["disclosure"]["effect_interval_90"]
        assert interval["lower"] < first["disclosure"]["effect_mean"] < interval["upper"]
        assert interval["method"] == "normal_approximation_two_sided_90"
        replay = conn.execute(
            query_sql,
            ("ignored", "budget-aggregate", "candidate-v1", "AGGREGATE_EFFECT", "idem-1"),
        ).fetchone()[0]
        assert replay["status"] == "IDEMPOTENT_REPLAY"
        assert replay["remaining_queries"] == 1
        conn.execute(
            query_sql,
            ("query-2", "budget-aggregate", "candidate-v1", "AGGREGATE_EFFECT", "idem-2"),
        )
        report["checks"]["budget_exhausted_sqlstate"] = expect_database_error(
            conn,
            query_sql,
            ("query-3", "budget-aggregate", "candidate-v1", "AGGREGATE_EFFECT", "idem-3"),
        )
        conn.execute("RESET ROLE")
        aggregate_state = conn.execute(
            "SELECT remaining_queries,(SELECT count(*) FROM "
            " confirmation_private.confirmation_query_ledger WHERE budget_id='budget-aggregate')"
            " FROM confirmation_private.research_error_budget_ledger"
            " WHERE budget_id='budget-aggregate'"
        ).fetchone()
        assert aggregate_state == (0, 2)
        report["checks"]["atomic_budget_and_idempotency"] = list(aggregate_state)

        conn.execute("SET ROLE xinao_discovery_confirmation_service")
        final = conn.execute(
            query_sql,
            ("final-1", "budget-final", "candidate-v1", "FINAL_GATE", "final-idem-1"),
        ).fetchone()[0]
        assert final["disclosure"]["sample_size"] == 1
        report["checks"]["duplicate_final_gate_sqlstate"] = expect_database_error(
            conn,
            query_sql,
            ("final-2", "budget-final", "candidate-v1", "FINAL_GATE", "final-idem-2"),
        )
        conn.execute("RESET ROLE")
        final_remaining = conn.execute(
            "SELECT remaining_queries FROM confirmation_private.research_error_budget_ledger "
            "WHERE budget_id='budget-final'"
        ).fetchone()[0]
        assert final_remaining == 1
        report["checks"]["final_gate_conflict_rolls_back_budget"] = final_remaining
        report["checks"]["query_update_sqlstate"] = expect_database_error(
            conn,
            "UPDATE confirmation_private.confirmation_query_ledger "
            "SET disclosure='{}' WHERE query_id='query-1'",
        )
        report["checks"]["query_delete_sqlstate"] = expect_database_error(
            conn,
            "DELETE FROM confirmation_private.confirmation_query_ledger WHERE query_id='query-1'",
        )

    report["checks"]["destructive_downgrade_guard"] = expect_alembic_guard(config, database)
    alembic(config, database, "downgrade", "base", allow_destructive=True)
    alembic(config, database, "upgrade", "head")
    with connection(database, autocommit=True) as conn:
        count = conn.execute(
            "SELECT count(*) FROM confirmation_private.confirmation_query_ledger"
        ).fetchone()[0]
        assert count == 0
        report["checks"]["fresh_up_down_up"] = "PASS"
    return report


def main() -> int:
    args = parse_args()
    report = {
        "schema_version": "xinao-postgres-p2-probe.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "domain": exercise_domain(args.domain_db),
        "confirmation": exercise_confirmation(args.confirmation_db),
        "status": "verified",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
