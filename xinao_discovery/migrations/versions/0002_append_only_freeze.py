"""Add replay sequence keys, append-only gates, and atomic immutable freezes."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_append_only_freeze"
down_revision = "0001_event_ledger"
branch_labels = None
depends_on = None

APPEND_SIGNATURE = """
text,text,text,text,bigint,timestamptz,text,text,text,text,text,text,jsonb,bytea,text,
text,bytea,text,text,text,text,jsonb,text,text
"""

FREEZE_SIGNATURE = f"""
{APPEND_SIGNATURE},text,text,timestamptz,timestamptz,timestamptz,jsonb,text,
timestamptz,timestamptz,text,bytea,text
"""

FREEZE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION xinao_freeze_decision(
    p_event_id text, p_event_type text, p_aggregate_type text, p_aggregate_id text,
    p_aggregate_version bigint, p_occurred_at timestamptz, p_correlation_id text,
    p_causation_id text, p_actor text, p_command_id text, p_idempotency_key text,
    p_payload_schema_version text, p_payload jsonb, p_payload_canonical bytea,
    p_payload_hash text, p_prior_event_hash text, p_event_canonical bytea,
    p_event_hash text, p_trace_id text,
    p_workflow_id text, p_run_id text, p_artifact_refs jsonb, p_outbox_id text,
    p_topic text,
    p_decision_id text, p_decision_plan_id text, p_target_window_start timestamptz,
    p_target_window_end timestamptz, p_target_open_time timestamptz,
    p_candidate_refs jsonb, p_candidate_refs_hash text, p_freeze_deadline timestamptz,
    p_knowledge_cutoff timestamptz, p_decision_type text, p_decision_canonical bytea,
    p_decision_hash text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    appended_event_id text;
    existing_decision public.frozen_decision%ROWTYPE;
    decision_basis jsonb;
    readback_decision_hash text;
    readback_event_hash text;
BEGIN
    SELECT * INTO existing_decision
    FROM public.frozen_decision
    WHERE decision_id = p_decision_id
    FOR UPDATE;
    IF FOUND THEN
        IF existing_decision.decision_id = p_decision_id
            AND existing_decision.decision_hash = p_decision_hash
            AND existing_decision.decision_plan_id = p_decision_plan_id
            AND existing_decision.target_window_start = p_target_window_start
            AND existing_decision.target_window_end = p_target_window_end
            AND existing_decision.target_open_time = p_target_open_time
            AND existing_decision.candidate_refs = p_candidate_refs
            AND existing_decision.candidate_refs_hash = p_candidate_refs_hash
            AND existing_decision.freeze_deadline = p_freeze_deadline
            AND existing_decision.knowledge_cutoff = p_knowledge_cutoff
            AND existing_decision.decision_type = p_decision_type
        THEN
            RETURN existing_decision.decision_id;
        END IF;
        RAISE EXCEPTION 'freeze identity or content hash conflict';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.frozen_decision WHERE decision_hash = p_decision_hash
    ) THEN
        RAISE EXCEPTION 'freeze content hash already belongs to another decision';
    END IF;
    IF p_aggregate_type <> 'FrozenDecision'
        OR p_aggregate_id <> p_decision_id
        OR p_aggregate_version <> 1
    THEN
        RAISE EXCEPTION 'freeze event aggregate identity is invalid';
    END IF;
    IF (p_decision_type = 'ACTION' AND p_event_type <> 'ActionFrozen')
        OR (p_decision_type = 'NO_ACTION' AND p_event_type <> 'NoActionFrozen')
        OR p_decision_type NOT IN ('ACTION', 'NO_ACTION')
    THEN
        RAISE EXCEPTION 'freeze decision and event types disagree';
    END IF;
    IF p_target_window_start > p_target_window_end
        OR p_freeze_deadline >= p_target_open_time
        OR p_knowledge_cutoff >= p_target_open_time
        OR p_occurred_at > p_freeze_deadline
        OR clock_timestamp() > p_freeze_deadline
    THEN
        RAISE EXCEPTION 'freeze is late or has an invalid temporal boundary';
    END IF;
    IF jsonb_typeof(p_candidate_refs) <> 'array'
        OR p_candidate_refs_hash !~ '^[0-9a-f]{64}$'
        OR p_decision_hash !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'freeze candidates or hashes are invalid';
    END IF;
    IF p_payload->>'decision_id' IS DISTINCT FROM p_decision_id
        OR p_payload->>'decision_hash' IS DISTINCT FROM p_decision_hash
    THEN
        RAISE EXCEPTION 'freeze payload identity is invalid';
    END IF;
    decision_basis := pg_catalog.convert_from(p_decision_canonical, 'UTF8')::jsonb;
    IF encode(public.digest(p_decision_canonical, 'sha256'), 'hex') <> p_decision_hash
        OR decision_basis->>'decision_id' IS DISTINCT FROM p_decision_id
        OR decision_basis->>'decision_plan_id' IS DISTINCT FROM p_decision_plan_id
        OR decision_basis->>'candidate_refs_hash' IS DISTINCT FROM p_candidate_refs_hash
        OR decision_basis->>'decision_type' IS DISTINCT FROM p_decision_type
        OR decision_basis->'candidate_refs' IS DISTINCT FROM p_candidate_refs
        OR (decision_basis->>'target_window_start')::timestamptz
            IS DISTINCT FROM p_target_window_start
        OR (decision_basis->>'target_window_end')::timestamptz
            IS DISTINCT FROM p_target_window_end
        OR (decision_basis->>'target_open_time')::timestamptz
            IS DISTINCT FROM p_target_open_time
        OR (decision_basis->>'freeze_deadline')::timestamptz
            IS DISTINCT FROM p_freeze_deadline
        OR (decision_basis->>'knowledge_cutoff')::timestamptz
            IS DISTINCT FROM p_knowledge_cutoff
    THEN
        RAISE EXCEPTION 'decision canonical bytes, identity, or hash mismatch';
    END IF;

    appended_event_id := public.xinao_append_event(
        p_event_id,p_event_type,p_aggregate_type,p_aggregate_id,p_aggregate_version,
        p_occurred_at,p_correlation_id,p_causation_id,p_actor,p_command_id,
        p_idempotency_key,p_payload_schema_version,p_payload,p_payload_canonical,
        p_payload_hash,p_prior_event_hash,p_event_canonical,p_event_hash,p_trace_id,
        p_workflow_id,p_run_id,
        p_artifact_refs,p_outbox_id,p_topic
    );
    INSERT INTO public.frozen_decision(
        decision_id,decision_plan_id,target_window_start,target_window_end,
        target_open_time,candidate_refs,candidate_refs_hash,freeze_deadline,
        knowledge_cutoff,decision_type,decision_hash,payload,event_id
    ) VALUES (
        p_decision_id,p_decision_plan_id,p_target_window_start,p_target_window_end,
        p_target_open_time,p_candidate_refs,p_candidate_refs_hash,p_freeze_deadline,
        p_knowledge_cutoff,p_decision_type,p_decision_hash,p_payload,appended_event_id
    );
    SELECT decision_hash INTO STRICT readback_decision_hash
    FROM public.frozen_decision WHERE decision_id = p_decision_id;
    SELECT event_hash INTO STRICT readback_event_hash
    FROM public.domain_event WHERE event_id = appended_event_id;
    IF readback_decision_hash <> p_decision_hash
        OR readback_event_hash <> p_event_hash
    THEN
        RAISE EXCEPTION 'freeze database readback hash mismatch';
    END IF;
    RETURN p_decision_id;
EXCEPTION
    WHEN unique_violation THEN
        SELECT * INTO existing_decision
        FROM public.frozen_decision
        WHERE decision_id = p_decision_id;
        IF FOUND
            AND existing_decision.decision_id = p_decision_id
            AND existing_decision.decision_hash = p_decision_hash
            AND existing_decision.decision_plan_id = p_decision_plan_id
            AND existing_decision.target_window_start = p_target_window_start
            AND existing_decision.target_window_end = p_target_window_end
            AND existing_decision.target_open_time = p_target_open_time
            AND existing_decision.candidate_refs = p_candidate_refs
            AND existing_decision.candidate_refs_hash = p_candidate_refs_hash
            AND existing_decision.freeze_deadline = p_freeze_deadline
            AND existing_decision.knowledge_cutoff = p_knowledge_cutoff
            AND existing_decision.decision_type = p_decision_type
        THEN
            RETURN existing_decision.decision_id;
        END IF;
        RAISE;
END;
$$;
"""

OUTBOX_ADVANCE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION xinao_advance_outbox(
    p_outbox_id text, p_mark_published boolean
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    current_outbox public.transactional_outbox%ROWTYPE;
    new_attempt_count integer;
BEGIN
    SELECT * INTO current_outbox
    FROM public.transactional_outbox
    WHERE outbox_id = p_outbox_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'outbox item does not exist';
    END IF;
    IF current_outbox.published_at IS NOT NULL THEN
        RAISE EXCEPTION 'outbox item is already published';
    END IF;
    UPDATE public.transactional_outbox
    SET attempt_count = attempt_count + 1,
        published_at = CASE WHEN p_mark_published THEN clock_timestamp() ELSE NULL END
    WHERE outbox_id = p_outbox_id
    RETURNING attempt_count INTO new_attempt_count;
    RETURN new_attempt_count;
END;
$$;
"""


def upgrade() -> None:
    op.add_column("domain_event", sa.Column("event_sequence_key", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE domain_event
        SET event_sequence_key = aggregate_type || ':' || aggregate_id || ':' ||
            lpad(aggregate_version::text, 20, '0')
        WHERE event_sequence_key IS NULL
        """
    )
    op.alter_column("domain_event", "event_sequence_key", nullable=False)
    op.create_unique_constraint(
        "uq_domain_event_sequence_key", "domain_event", ["event_sequence_key"]
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION xinao_set_event_sequence_key()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.event_sequence_key := NEW.aggregate_type || ':' || NEW.aggregate_id || ':' ||
                lpad(NEW.aggregate_version::text, 20, '0');
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_domain_event_sequence_key
        BEFORE INSERT ON domain_event
        FOR EACH ROW EXECUTE FUNCTION xinao_set_event_sequence_key();

        CREATE OR REPLACE FUNCTION xinao_reject_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP;
        END;
        $$;
        CREATE TRIGGER tr_domain_event_append_only
        BEFORE UPDATE OR DELETE ON domain_event
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_domain_event_no_truncate
        BEFORE TRUNCATE ON domain_event
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_command_dedup_append_only
        BEFORE UPDATE OR DELETE ON command_dedup
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_command_dedup_no_truncate
        BEFORE TRUNCATE ON command_dedup
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();

        CREATE OR REPLACE FUNCTION xinao_guard_aggregate_head()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'aggregate_head % is forbidden', TG_OP;
            END IF;
            IF NEW.version <> OLD.version + 1 OR NOT EXISTS (
                SELECT 1 FROM domain_event
                WHERE event_id=NEW.last_event_id
                  AND aggregate_type=NEW.aggregate_type
                  AND aggregate_id=NEW.aggregate_id
                  AND aggregate_version=NEW.version
                  AND event_hash=NEW.last_event_hash
            ) THEN
                RAISE EXCEPTION 'aggregate head update is not a valid next event';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_aggregate_head_guard
        BEFORE UPDATE OR DELETE ON aggregate_head
        FOR EACH ROW EXECUTE FUNCTION xinao_guard_aggregate_head();
        CREATE TRIGGER tr_aggregate_head_no_truncate
        BEFORE TRUNCATE ON aggregate_head
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_guard_aggregate_head();

        CREATE OR REPLACE FUNCTION xinao_guard_outbox()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'transactional_outbox % is forbidden', TG_OP;
            END IF;
            IF NEW.outbox_id IS DISTINCT FROM OLD.outbox_id
                OR NEW.event_id IS DISTINCT FROM OLD.event_id
                OR NEW.topic IS DISTINCT FROM OLD.topic
                OR NEW.payload IS DISTINCT FROM OLD.payload
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.attempt_count < OLD.attempt_count
                OR (
                    OLD.published_at IS NOT NULL
                    AND NEW.published_at IS DISTINCT FROM OLD.published_at
                )
            THEN
                RAISE EXCEPTION 'outbox immutable fields or delivery state cannot move backward';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER tr_outbox_guard
        BEFORE UPDATE OR DELETE ON transactional_outbox
        FOR EACH ROW EXECUTE FUNCTION xinao_guard_outbox();
        CREATE TRIGGER tr_outbox_no_truncate
        BEFORE TRUNCATE ON transactional_outbox
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_guard_outbox();
        """
    )
    op.create_table(
        "frozen_decision",
        sa.Column("decision_id", sa.Text(), primary_key=True),
        sa.Column("decision_plan_id", sa.Text(), nullable=False),
        sa.Column("target_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidate_refs_hash", sa.String(64), nullable=False),
        sa.Column("freeze_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("knowledge_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_type", sa.Text(), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.CheckConstraint(
            "decision_type IN ('ACTION','NO_ACTION')", name="ck_frozen_decision_type"
        ),
        sa.CheckConstraint("decision_hash ~ '^[0-9a-f]{64}$'", name="ck_frozen_decision_hash_hex"),
        sa.CheckConstraint(
            "candidate_refs_hash ~ '^[0-9a-f]{64}$'",
            name="ck_frozen_candidate_refs_hash_hex",
        ),
        sa.CheckConstraint(
            "freeze_deadline < target_open_time", name="ck_frozen_deadline_before_open"
        ),
        sa.CheckConstraint(
            "knowledge_cutoff < target_open_time", name="ck_frozen_knowledge_before_open"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
        sa.UniqueConstraint("decision_hash", name="uq_frozen_decision_hash"),
        sa.UniqueConstraint(
            "decision_plan_id",
            "target_window_start",
            "target_window_end",
            "candidate_refs_hash",
            "freeze_deadline",
            name="uq_frozen_plan_target_candidates",
        ),
    )
    op.execute(
        """
        CREATE TRIGGER tr_frozen_decision_append_only
        BEFORE UPDATE OR DELETE ON frozen_decision
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_frozen_decision_no_truncate
        BEFORE TRUNCATE ON frozen_decision
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        """
    )
    op.execute(FREEZE_FUNCTION)
    op.execute(OUTBOX_ADVANCE_FUNCTION)
    op.execute(
        f"""
        REVOKE ALL ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE}) FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_advance_outbox(text,boolean) FROM PUBLIC;
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname='xinao_discovery_freeze_writer'
            ) THEN
                CREATE ROLE xinao_discovery_freeze_writer NOLOGIN;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname='xinao_discovery_outbox_publisher'
            ) THEN
                CREATE ROLE xinao_discovery_outbox_publisher NOLOGIN;
            END IF;
        END $$;
        GRANT SELECT ON frozen_decision TO xinao_discovery_freeze_writer;
        GRANT EXECUTE ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE})
            TO xinao_discovery_freeze_writer;
        GRANT EXECUTE ON FUNCTION xinao_advance_outbox(text,boolean)
            TO xinao_discovery_outbox_publisher;
        """
    )


def downgrade() -> None:
    history_count = op.get_bind().execute(sa.text("SELECT count(*) FROM domain_event")).scalar_one()
    if history_count and os.environ.get("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE") != (
        "isolated-canary-reset"
    ):
        raise RuntimeError(
            "domain history exists; restore an isolated database instead of downgrading"
        )
    op.execute(
        f"""
        REVOKE ALL ON frozen_decision FROM xinao_discovery_freeze_writer;
        REVOKE ALL ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE})
            FROM xinao_discovery_freeze_writer;
        REVOKE ALL ON FUNCTION xinao_advance_outbox(text,boolean)
            FROM xinao_discovery_outbox_publisher;
        DROP FUNCTION IF EXISTS xinao_freeze_decision({FREEZE_SIGNATURE});
        DROP FUNCTION IF EXISTS xinao_advance_outbox(text,boolean);
        DROP TRIGGER IF EXISTS tr_frozen_decision_append_only ON frozen_decision;
        DROP TRIGGER IF EXISTS tr_frozen_decision_no_truncate ON frozen_decision;
        """
    )
    op.drop_table("frozen_decision")
    op.execute(
        """
        DROP TRIGGER IF EXISTS tr_command_dedup_append_only ON command_dedup;
        DROP TRIGGER IF EXISTS tr_command_dedup_no_truncate ON command_dedup;
        DROP TRIGGER IF EXISTS tr_domain_event_append_only ON domain_event;
        DROP TRIGGER IF EXISTS tr_domain_event_no_truncate ON domain_event;
        DROP FUNCTION IF EXISTS xinao_reject_mutation();
        DROP TRIGGER IF EXISTS tr_aggregate_head_guard ON aggregate_head;
        DROP TRIGGER IF EXISTS tr_aggregate_head_no_truncate ON aggregate_head;
        DROP FUNCTION IF EXISTS xinao_guard_aggregate_head();
        DROP TRIGGER IF EXISTS tr_outbox_guard ON transactional_outbox;
        DROP TRIGGER IF EXISTS tr_outbox_no_truncate ON transactional_outbox;
        DROP FUNCTION IF EXISTS xinao_guard_outbox();
        DROP TRIGGER IF EXISTS tr_domain_event_sequence_key ON domain_event;
        DROP FUNCTION IF EXISTS xinao_set_event_sequence_key();
        DO $$ BEGIN
            DROP ROLE IF EXISTS xinao_discovery_freeze_writer;
            DROP ROLE IF EXISTS xinao_discovery_outbox_publisher;
        END $$;
        """
    )
    op.drop_constraint("uq_domain_event_sequence_key", "domain_event", type_="unique")
    op.drop_column("domain_event", "event_sequence_key")
