"""Exercise P6 decision, freeze, settlement, journal, and weekly close on PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from xinao.canonical import canonical_sha256
from xinao.canonical.identifiers import generate_uuid7
from xinao.canonical.jcs import canonical_dumps
from xinao.canonical.time_profile import format_utc
from xinao.catalog.compiler import write_atomic
from xinao.decision import DecisionGateInput, compile_decision_plan, freeze_decision
from xinao.ledger import (
    append_event,
    create_event,
    frozen_position_group,
    opening_group,
    period_adjustment_group,
    replay_balances,
    reversal_group,
)
from xinao.settlement import OutcomeObservation, settle_frozen_decision

FREEZE_SQL = "SELECT xinao_freeze_decision(" + ",".join(["%s"] * 36) + ")"


def now_utc() -> datetime:
    value = datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def event(*, event_type: str, aggregate_type: str, aggregate_id: str, payload: dict[str, Any]):
    return create_event(
        event_id=generate_uuid7(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=1,
        occurred_at=now_utc(),
        correlation_id="0190fa00-1111-7000-8222-334455667788",
        causation_id=None,
        actor="Codex-single-writer",
        command_id=generate_uuid7(),
        idempotency_key=f"p6:{aggregate_type}:{aggregate_id}",
        payload_schema_version=f"{aggregate_type}.v1",
        payload=payload,
        prior_event_hash=None,
        trace_id="0190fa00-2222-7000-8222-334455667788",
        workflow_id="xinao-mainline-p6-canary",
        run_id="xinao-mainline-20260714T014700",
    )


def append(conn: psycopg.Connection, record, *, topic: str = "xinao.domain-events.v1") -> str:
    conn.execute("SET ROLE xinao_discovery_event_writer")
    try:
        return append_event(conn, record, outbox_id=generate_uuid7(), topic=topic)
    finally:
        conn.execute("RESET ROLE")


def expect_error(conn: psycopg.Connection, statement: str, parameters: Any = None) -> str:
    try:
        with conn.transaction():
            conn.execute(statement, parameters)
    except psycopg.Error as exc:
        return exc.sqlstate or type(exc).__name__
    raise AssertionError("PostgreSQL accepted a prohibited operation")


def call_as_settlement(conn: psycopg.Connection, statement: str, parameters: tuple[Any, ...]):
    conn.execute("SET ROLE xinao_discovery_settlement_writer")
    try:
        return conn.execute(statement, parameters).fetchone()[0]
    finally:
        conn.execute("RESET ROLE")


def expect_settlement_error(
    conn: psycopg.Connection, statement: str, parameters: tuple[Any, ...]
) -> str:
    try:
        with conn.transaction():
            conn.execute("SET ROLE xinao_discovery_settlement_writer")
            conn.execute(statement, parameters)
    except psycopg.Error as exc:
        conn.execute("RESET ROLE")
        return f"{exc.sqlstate or type(exc).__name__}:{exc.diag.message_primary}"
    conn.execute("RESET ROLE")
    raise AssertionError("settlement writer accepted a prohibited operation")


def freeze_action(conn: psycopg.Connection, *, target_ref: str):
    now = now_utc()
    open_time = now + timedelta(hours=3)
    gate = DecisionGateInput(
        candidate_ref="candidate.signal.p6.v1",
        validation_report_ref="validation.signal.p6.v1",
        validation_output_hash="a" * 64,
        validation_verdict="ACTION",
        baseline_ref="baseline-odds-water.v1",
        baseline_active=True,
        rule_ref="special-number-settlement.v0",
        rule_active=True,
        target_ref=target_ref,
        target_window_start=open_time,
        target_window_end=open_time,
        target_open_time=open_time,
        freeze_deadline=now + timedelta(hours=2),
        knowledge_cutoff=now,
        compiled_at=now,
        panel="B",
        selected_number=1,
        stake="1.0000",
        lower_expected_net="0.2000",
        estimated_cost="0.0100",
        risk_limit="1.0000",
    )
    plan = compile_decision_plan(gate, plan_ref=generate_uuid7())
    frozen = freeze_decision(
        plan,
        decision_ref=generate_uuid7(),
        frozen_at=now + timedelta(seconds=1),
    )
    candidate_refs = list(frozen.candidate_refs)
    candidate_hash = canonical_sha256(candidate_refs)
    decision_basis = {
        "decision_id": frozen.decision_ref,
        "decision_plan_id": frozen.decision_plan_ref,
        "target_window_start": format_utc(frozen.target_window_start),
        "target_window_end": format_utc(frozen.target_window_end),
        "target_open_time": format_utc(frozen.target_open_time),
        "candidate_refs": candidate_refs,
        "candidate_refs_hash": candidate_hash,
        "freeze_deadline": format_utc(frozen.freeze_deadline),
        "knowledge_cutoff": format_utc(frozen.knowledge_cutoff),
        "decision_type": "ACTION",
    }
    database_hash = canonical_sha256(decision_basis)
    payload = {
        "decision_id": frozen.decision_ref,
        "decision_hash": database_hash,
        "decision_plan_id": frozen.decision_plan_ref,
        "target_ref": target_ref,
        "selection": {
            "panel": frozen.panel,
            "selected_number": frozen.selected_number,
            "stake": frozen.stake,
        },
        "domain_decision_hash": frozen.decision_hash,
    }
    record = event(
        event_type="ActionFrozen",
        aggregate_type="FrozenDecision",
        aggregate_id=frozen.decision_ref,
        payload=payload,
    )
    arguments = list(
        record.append_arguments(outbox_id=generate_uuid7(), topic="xinao.decision-frozen.v1")
    )
    arguments[12] = Jsonb(arguments[12])
    arguments[21] = Jsonb(arguments[21])
    freeze_args = (
        *arguments,
        frozen.decision_ref,
        frozen.decision_plan_ref,
        frozen.target_window_start,
        frozen.target_window_end,
        frozen.target_open_time,
        Jsonb(candidate_refs),
        candidate_hash,
        frozen.freeze_deadline,
        frozen.knowledge_cutoff,
        "ACTION",
        canonical_dumps(decision_basis),
        database_hash,
    )
    conn.execute("SET ROLE xinao_discovery_freeze_writer")
    try:
        result = conn.execute(FREEZE_SQL, freeze_args).fetchone()[0]
    finally:
        conn.execute("RESET ROLE")
    assert result == frozen.decision_ref
    return frozen


def post_group(conn: psycopg.Connection, group) -> str:
    record = event(
        event_type="JournalPosted",
        aggregate_type="JournalEntry",
        aggregate_id=group.group_ref,
        payload=group.model_dump(mode="json"),
    )
    append(conn, record, topic="xinao.journal.v1")
    return call_as_settlement(
        conn,
        "SELECT xinao_post_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            group.group_ref,
            group.portfolio_ref,
            group.transaction_type,
            group.occurred_at,
            group.source_ref,
            group.reversal_of_group_ref,
            group.adjusts_period_ref,
            group.group_hash,
            Jsonb([line.model_dump(mode="json") for line in group.lines]),
            record.event_id,
        ),
    )


def expect_post_group_error(conn: psycopg.Connection, group) -> str:
    record = event(
        event_type="JournalPosted",
        aggregate_type="JournalEntry",
        aggregate_id=group.group_ref,
        payload=group.model_dump(mode="json"),
    )
    try:
        with conn.transaction():
            append(conn, record, topic="xinao.journal.v1")
            conn.execute("SET ROLE xinao_discovery_settlement_writer")
            conn.execute(
                "SELECT xinao_post_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    group.group_ref,
                    group.portfolio_ref,
                    group.transaction_type,
                    group.occurred_at,
                    group.source_ref,
                    group.reversal_of_group_ref,
                    group.adjusts_period_ref,
                    group.group_hash,
                    Jsonb([line.model_dump(mode="json") for line in group.lines]),
                    record.event_id,
                ),
            )
    except psycopg.Error as exc:
        conn.execute("RESET ROLE")
        return f"{exc.sqlstate or type(exc).__name__}:{exc.diag.message_primary}"
    conn.execute("RESET ROLE")
    raise AssertionError("settlement writer posted a journal group across a closed-period guard")


def run(database: str) -> dict[str, Any]:
    report: dict[str, Any] = {"database": database, "checks": {}}
    with psycopg.connect(
        host=os.environ.get("XINAO_DB_HOST", "shiwu-ku"),
        port=os.environ.get("XINAO_DB_PORT", "5432"),
        dbname=database,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    ) as conn:
        portfolio_ref = "shadow-portfolio.canary.v1"
        portfolio_hash = canonical_sha256(
            {"opening_balance": "100000.0000", "currency": "normalized_shadow_unit"}
        )
        with conn.transaction():
            portfolio_event = event(
                event_type="JournalPosted",
                aggregate_type="ShadowPortfolio",
                aggregate_id=portfolio_ref,
                payload={"policy_hash": portfolio_hash},
            )
            append(conn, portfolio_event)
            assert (
                call_as_settlement(
                    conn,
                    "SELECT xinao_create_shadow_portfolio(%s,%s,%s)",
                    (portfolio_ref, portfolio_hash, portfolio_event.event_id),
                )
                == portfolio_ref
            )

        historical = now_utc() - timedelta(days=10)
        opening = opening_group(
            group_ref=generate_uuid7(),
            portfolio_ref=portfolio_ref,
            occurred_at=historical,
        )
        with conn.transaction():
            assert post_group(conn, opening) == opening.group_ref
        existing_event_id = conn.execute(
            "SELECT event_id FROM journal_group WHERE journal_group_id=%s", (opening.group_ref,)
        ).fetchone()[0]
        report["checks"]["unbalanced_journal_rejected"] = expect_settlement_error(
            conn,
            "SELECT xinao_post_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                generate_uuid7(),
                portfolio_ref,
                "FEE",
                now_utc(),
                "fee.invalid",
                None,
                None,
                "b" * 64,
                Jsonb(
                    [
                        {
                            "line_no": 1,
                            "account": "FeeExpense",
                            "side": "DEBIT",
                            "amount": "1.0000",
                            "currency": "normalized_shadow_unit",
                        },
                        {
                            "line_no": 2,
                            "account": "ShadowCash",
                            "side": "CREDIT",
                            "amount": "0.5000",
                            "currency": "normalized_shadow_unit",
                        },
                    ]
                ),
                portfolio_event.event_id,
            ),
        )
        report["checks"]["ordinary_mutation_style_correction_rejected"] = expect_settlement_error(
            conn,
            "SELECT xinao_post_journal(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                generate_uuid7(),
                portfolio_ref,
                "SETTLEMENT_MISS",
                now_utc(),
                "correction.invalid",
                opening.group_ref,
                None,
                "c" * 64,
                Jsonb([line.model_dump(mode="json") for line in opening.lines]),
                existing_event_id,
            ),
        )

        frozen = None
        with conn.transaction():
            frozen = freeze_action(conn, target_ref="draw.p6-canary.1")
            position = frozen_position_group(
                group_ref=generate_uuid7(),
                portfolio_ref=portfolio_ref,
                decision_ref=frozen.decision_ref,
                occurred_at=now_utc(),
                stake=frozen.stake,
            )
            assert post_group(conn, position) == position.group_ref
        assert frozen is not None

        observed = OutcomeObservation(
            outcome_ref=generate_uuid7(),
            source_ref="macaujc2",
            target_ref=frozen.target_ref,
            actual_special_number=1,
            observed_at=now_utc(),
            verified=True,
        ).with_hash()
        with conn.transaction():
            outcome_event = event(
                event_type="OutcomeObserved",
                aggregate_type="OutcomeObservation",
                aggregate_id=observed.outcome_ref,
                payload=observed.model_dump(mode="json"),
            )
            append(conn, outcome_event, topic="xinao.outcome.v1")
            admission = call_as_settlement(
                conn,
                "SELECT xinao_observe_outcome(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    observed.outcome_ref,
                    observed.source_ref,
                    observed.target_ref,
                    observed.result_hash,
                    observed.observed_at,
                    observed.verified,
                    None,
                    Jsonb(observed.model_dump(mode="json")),
                    outcome_event.event_id,
                    None,
                    None,
                ),
            )
            assert admission == f"ACCEPTED:{observed.outcome_ref}"
        before_duplicate = conn.execute("SELECT count(*) FROM outcome_observation").fetchone()[0]
        with conn.transaction():
            duplicate = call_as_settlement(
                conn,
                "SELECT xinao_observe_outcome(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    generate_uuid7(),
                    observed.source_ref,
                    observed.target_ref,
                    observed.result_hash,
                    observed.observed_at,
                    True,
                    None,
                    Jsonb({}),
                    "unused-event-id",
                    None,
                    None,
                ),
            )
        assert duplicate == f"DUPLICATE:{observed.outcome_ref}"
        assert (
            conn.execute("SELECT count(*) FROM outcome_observation").fetchone()[0]
            == before_duplicate
        )

        bundle = settle_frozen_decision(
            frozen=frozen,
            outcome=observed,
            settlement_ref=generate_uuid7(),
            journal_group_ref=generate_uuid7(),
            portfolio_ref=portfolio_ref,
            occurred_at=now_utc(),
        )
        with conn.transaction():
            assert post_group(conn, bundle.journal_group) == bundle.journal_group.group_ref
            settlement_event = event(
                event_type="SettlementRecorded",
                aggregate_type="SettlementRecord",
                aggregate_id=bundle.record.settlement_ref,
                payload=bundle.record.model_dump(mode="json"),
            )
            append(conn, settlement_event, topic="xinao.settlement.v1")
            assert (
                call_as_settlement(
                    conn,
                    "SELECT xinao_record_settlement(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        bundle.record.settlement_ref,
                        frozen.decision_ref,
                        observed.outcome_ref,
                        frozen.rule_ref,
                        bundle.record.settlement_hash,
                        bundle.journal_group.group_ref,
                        Jsonb(bundle.record.model_dump(mode="json")),
                        settlement_event.event_id,
                    ),
                )
                == bundle.record.settlement_ref
            )
        with conn.transaction():
            assert (
                call_as_settlement(
                    conn,
                    "SELECT xinao_record_settlement(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        generate_uuid7(),
                        frozen.decision_ref,
                        observed.outcome_ref,
                        frozen.rule_ref,
                        bundle.record.settlement_hash,
                        bundle.journal_group.group_ref,
                        Jsonb({}),
                        "unused-event-id",
                    ),
                )
                == bundle.record.settlement_ref
            )
        report["checks"]["deterministic_settlement_hash"] = bundle.record.settlement_hash
        report["checks"]["idempotent_outcome_and_settlement"] = True
        report["checks"]["replay_balances"] = replay_balances(
            (opening, position, bundle.journal_group)
        )

        conflict = OutcomeObservation(
            outcome_ref=generate_uuid7(),
            source_ref="macaujc2",
            target_ref=observed.target_ref,
            actual_special_number=2,
            observed_at=now_utc(),
            verified=True,
        ).with_hash()
        with conn.transaction():
            conflict_outcome_event = event(
                event_type="OutcomeObserved",
                aggregate_type="OutcomeObservation",
                aggregate_id=conflict.outcome_ref,
                payload=conflict.model_dump(mode="json"),
            )
            conflict_event = event(
                event_type="OutcomeConflictDetected",
                aggregate_type="OutcomeConflict",
                aggregate_id=generate_uuid7(),
                payload={
                    "target_ref": conflict.target_ref,
                    "existing_outcome_ref": observed.outcome_ref,
                    "conflicting_outcome_ref": conflict.outcome_ref,
                },
            )
            append(conn, conflict_outcome_event, topic="xinao.outcome.v1")
            append(conn, conflict_event, topic="xinao.outcome-conflict.v1")
            conflict_admission = call_as_settlement(
                conn,
                "SELECT xinao_observe_outcome(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    conflict.outcome_ref,
                    conflict.source_ref,
                    conflict.target_ref,
                    conflict.result_hash,
                    conflict.observed_at,
                    True,
                    None,
                    Jsonb(conflict.model_dump(mode="json")),
                    conflict_outcome_event.event_id,
                    conflict_event.aggregate_id,
                    conflict_event.event_id,
                ),
            )
            assert conflict_admission == f"CONFLICTED:{conflict.outcome_ref}"
        report["checks"]["outcome_conflict_persisted"] = True

        frozen_conflict = None
        with conn.transaction():
            frozen_conflict = freeze_action(conn, target_ref="draw.p6-canary.2")
        assert frozen_conflict is not None
        accepted_two = OutcomeObservation(
            outcome_ref=generate_uuid7(),
            source_ref="macaujc2",
            target_ref=frozen_conflict.target_ref,
            actual_special_number=1,
            observed_at=now_utc(),
            verified=True,
        ).with_hash()
        conflicting_two = OutcomeObservation(
            outcome_ref=generate_uuid7(),
            source_ref="macaujc2",
            target_ref=frozen_conflict.target_ref,
            actual_special_number=2,
            observed_at=now_utc(),
            verified=True,
        ).with_hash()
        with conn.transaction():
            for candidate, conflict_with in (
                (accepted_two, None),
                (conflicting_two, accepted_two),
            ):
                observed_event = event(
                    event_type="OutcomeObserved",
                    aggregate_type="OutcomeObservation",
                    aggregate_id=candidate.outcome_ref,
                    payload=candidate.model_dump(mode="json"),
                )
                append(conn, observed_event, topic="xinao.outcome.v1")
                detected_event = None
                if conflict_with is not None:
                    detected_event = event(
                        event_type="OutcomeConflictDetected",
                        aggregate_type="OutcomeConflict",
                        aggregate_id=generate_uuid7(),
                        payload={
                            "target_ref": candidate.target_ref,
                            "existing_outcome_ref": conflict_with.outcome_ref,
                            "conflicting_outcome_ref": candidate.outcome_ref,
                        },
                    )
                    append(conn, detected_event, topic="xinao.outcome-conflict.v1")
                call_as_settlement(
                    conn,
                    "SELECT xinao_observe_outcome(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        candidate.outcome_ref,
                        candidate.source_ref,
                        candidate.target_ref,
                        candidate.result_hash,
                        candidate.observed_at,
                        True,
                        None,
                        Jsonb(candidate.model_dump(mode="json")),
                        observed_event.event_id,
                        None if detected_event is None else detected_event.aggregate_id,
                        None if detected_event is None else detected_event.event_id,
                    ),
                )
        report["checks"]["conflict_pauses_new_settlement"] = expect_settlement_error(
            conn,
            "SELECT xinao_record_settlement(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                generate_uuid7(),
                frozen_conflict.decision_ref,
                accepted_two.outcome_ref,
                frozen_conflict.rule_ref,
                "d" * 64,
                "journal.does-not-exist",
                Jsonb({}),
                "event.does-not-exist",
            ),
        )

        period_start = historical - timedelta(days=historical.weekday())
        period_start = period_start.replace(hour=7, minute=0, second=0, microsecond=0)
        if opening.occurred_at < period_start:
            period_start -= timedelta(days=7)
        period_end = period_start + timedelta(days=7)
        projection = {
            "status": "RECONCILED",
            "unresolved_decision_refs": [],
            "conflicted_target_refs": [],
            "journal_group_refs": [opening.group_ref],
            "balances": replay_balances((opening,)),
        }
        projection_hash = canonical_sha256(projection)
        period_id = generate_uuid7()
        invalid_projection = {**projection, "balances": {"ShadowCash": "0.0000"}}
        report["checks"]["period_replay_mismatch_rejected"] = expect_settlement_error(
            conn,
            "SELECT xinao_close_accounting_period(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                generate_uuid7(),
                "weekly-close-policy.v0",
                period_start,
                period_end,
                now_utc(),
                canonical_sha256(invalid_projection),
                Jsonb(invalid_projection),
                "event.does-not-exist",
            ),
        )
        with conn.transaction():
            period_event = event(
                event_type="AccountingPeriodClosed",
                aggregate_type="AccountingPeriod",
                aggregate_id=period_id,
                payload={**projection, "projection_hash": projection_hash},
            )
            append(conn, period_event, topic="xinao.accounting-period.v1")
            assert (
                call_as_settlement(
                    conn,
                    "SELECT xinao_close_accounting_period(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        period_id,
                        "weekly-close-policy.v0",
                        period_start,
                        period_end,
                        now_utc(),
                        projection_hash,
                        Jsonb(projection),
                        period_event.event_id,
                    ),
                )
                == period_id
            )
        report["checks"]["closed_period_projection_hash"] = projection_hash

        backdated = opening_group(
            group_ref=generate_uuid7(),
            portfolio_ref=portfolio_ref,
            occurred_at=opening.occurred_at,
            amount="1.0000",
        )
        report["checks"]["closed_period_backdating_rejected"] = expect_post_group_error(
            conn, backdated
        )
        closed_reversal = reversal_group(
            group_ref=generate_uuid7(),
            original=opening,
            occurred_at=now_utc(),
        )
        report["checks"]["closed_period_reversal_rejected"] = expect_post_group_error(
            conn, closed_reversal
        )

        adjustment = period_adjustment_group(
            group_ref=generate_uuid7(),
            original=opening,
            closed_period_ref=period_id,
            occurred_at=now_utc(),
        )
        with conn.transaction():
            assert post_group(conn, adjustment) == adjustment.group_ref
        report["checks"]["period_adjustment_group"] = adjustment.group_hash

        conn.execute("SET ROLE xinao_discovery_settlement_writer")
        try:
            report["checks"]["direct_journal_update_denied_sqlstate"] = expect_error(
                conn,
                "UPDATE journal_entry SET amount=amount+1 WHERE journal_group_id=%s",
                (opening.group_ref,),
            )
            report["checks"]["direct_settlement_insert_denied_sqlstate"] = expect_error(
                conn,
                "INSERT INTO settlement_record(settlement_id) VALUES ('forbidden')",
            )
            report["checks"]["journal_truncate_denied_sqlstate"] = expect_error(
                conn, "TRUNCATE journal_entry"
            )
        finally:
            conn.execute("RESET ROLE")

        counts = conn.execute(
            "SELECT (SELECT count(*) FROM shadow_portfolio),"
            "(SELECT count(*) FROM outcome_observation),"
            "(SELECT count(*) FROM outcome_conflict),"
            "(SELECT count(*) FROM journal_group),"
            "(SELECT count(*) FROM settlement_record),"
            "(SELECT count(*) FROM accounting_period)"
        ).fetchone()
        report["checks"]["row_counts"] = list(counts)
        assert counts == (1, 4, 2, 4, 1, 1)
    report["status"] = "verified"
    return report


def main() -> int:
    args = parse_args()
    report = run(args.database)
    environment = os.environ.copy()
    environment["POSTGRES_DB"] = args.database
    downgrade = subprocess.run(
        ["alembic", "-c", "migrations/alembic.ini", "downgrade", "0002_append_only_freeze"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if downgrade.returncode == 0 or "shadow accounting history exists" not in (
        downgrade.stdout + downgrade.stderr
    ):
        raise AssertionError("P6 destructive downgrade guard did not reject history loss")
    report["checks"]["destructive_downgrade_guard"] = f"rejected:{downgrade.returncode}"
    restore = subprocess.run(
        ["alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if restore.returncode != 0:
        raise AssertionError(
            "P6 guard migration was not restored after downgrade rejection: "
            + (restore.stdout + restore.stderr)[-1000:]
        )
    report["checks"]["migration_head_restored"] = "0004_closed_period_journal_guard"
    write_atomic(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
