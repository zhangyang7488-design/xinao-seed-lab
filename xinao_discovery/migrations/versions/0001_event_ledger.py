"""Create the formal event ledger, idempotency gate, outbox, and checkpoints."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_event_ledger"
down_revision = None
branch_labels = None
depends_on = None


APPEND_FUNCTION = r"""
CREATE OR REPLACE FUNCTION xinao_append_event(
    p_event_id text, p_event_type text, p_aggregate_type text, p_aggregate_id text,
    p_aggregate_version bigint, p_occurred_at timestamptz, p_correlation_id text,
    p_causation_id text, p_actor text, p_command_id text, p_idempotency_key text,
    p_payload_schema_version text, p_payload jsonb, p_payload_canonical bytea,
    p_payload_hash text, p_prior_event_hash text, p_event_canonical bytea,
    p_event_hash text, p_trace_id text,
    p_workflow_id text, p_run_id text, p_artifact_refs jsonb, p_outbox_id text,
    p_topic text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    current_head public.aggregate_head%ROWTYPE;
    existing_dedup public.command_dedup%ROWTYPE;
    event_basis jsonb;
BEGIN
    SELECT * INTO existing_dedup
    FROM public.command_dedup
    WHERE idempotency_key = p_idempotency_key
    FOR UPDATE;
    IF FOUND THEN
        IF existing_dedup.command_id = p_command_id
            AND existing_dedup.event_type = p_event_type
            AND existing_dedup.aggregate_type = p_aggregate_type
            AND existing_dedup.aggregate_id = p_aggregate_id
            AND existing_dedup.aggregate_version = p_aggregate_version
            AND existing_dedup.payload_hash = p_payload_hash
            AND existing_dedup.prior_event_hash IS NOT DISTINCT FROM p_prior_event_hash
            AND existing_dedup.event_hash = p_event_hash
        THEN
            RETURN existing_dedup.event_id;
        END IF;
        RAISE EXCEPTION 'idempotency key reused with different command or payload';
    END IF;

    IF pg_catalog.convert_from(p_payload_canonical, 'UTF8')::jsonb IS DISTINCT FROM p_payload
        OR encode(public.digest(p_payload_canonical, 'sha256'), 'hex') <> p_payload_hash
    THEN
        RAISE EXCEPTION 'payload canonical bytes or hash mismatch';
    END IF;
    event_basis := pg_catalog.convert_from(p_event_canonical, 'UTF8')::jsonb;
    IF encode(public.digest(p_event_canonical, 'sha256'), 'hex') <> p_event_hash
        OR event_basis->>'event_id' IS DISTINCT FROM p_event_id
        OR event_basis->>'event_type' IS DISTINCT FROM p_event_type
        OR event_basis->>'aggregate_type' IS DISTINCT FROM p_aggregate_type
        OR event_basis->>'aggregate_id' IS DISTINCT FROM p_aggregate_id
        OR event_basis->>'aggregate_version' IS DISTINCT FROM p_aggregate_version::text
        OR (event_basis->>'occurred_at')::timestamptz IS DISTINCT FROM p_occurred_at
        OR event_basis->>'correlation_id' IS DISTINCT FROM p_correlation_id
        OR event_basis->>'causation_id' IS DISTINCT FROM p_causation_id
        OR event_basis->>'actor' IS DISTINCT FROM p_actor
        OR event_basis->>'command_id' IS DISTINCT FROM p_command_id
        OR event_basis->>'idempotency_key' IS DISTINCT FROM p_idempotency_key
        OR event_basis->>'payload_schema_version' IS DISTINCT FROM p_payload_schema_version
        OR event_basis->>'payload_hash' IS DISTINCT FROM p_payload_hash
        OR event_basis->>'prior_event_hash' IS DISTINCT FROM p_prior_event_hash
        OR event_basis->>'trace_id' IS DISTINCT FROM p_trace_id
        OR event_basis->>'workflow_id' IS DISTINCT FROM p_workflow_id
        OR event_basis->>'run_id' IS DISTINCT FROM p_run_id
        OR event_basis->'payload' IS DISTINCT FROM p_payload
        OR event_basis->'artifact_refs' IS DISTINCT FROM p_artifact_refs
    THEN
        RAISE EXCEPTION 'event canonical bytes, identity, or hash mismatch';
    END IF;

    SELECT * INTO current_head
    FROM public.aggregate_head
    WHERE aggregate_type = p_aggregate_type AND aggregate_id = p_aggregate_id
    FOR UPDATE;
    IF NOT FOUND THEN
        IF p_aggregate_version <> 1 OR p_prior_event_hash IS NOT NULL THEN
            RAISE EXCEPTION 'first event must be version 1 with no prior hash';
        END IF;
    ELSIF p_aggregate_version <> current_head.version + 1
        OR p_prior_event_hash IS DISTINCT FROM current_head.last_event_hash
    THEN
        RAISE EXCEPTION 'aggregate version or prior hash mismatch';
    END IF;

    INSERT INTO public.domain_event(
        event_id,event_type,aggregate_type,aggregate_id,aggregate_version,occurred_at,
        correlation_id,causation_id,actor,command_id,idempotency_key,
        payload_schema_version,payload,payload_hash,prior_event_hash,event_hash,trace_id,
        workflow_id,run_id,artifact_refs
    ) VALUES (
        p_event_id,p_event_type,p_aggregate_type,p_aggregate_id,p_aggregate_version,
        p_occurred_at,p_correlation_id,p_causation_id,p_actor,p_command_id,
        p_idempotency_key,p_payload_schema_version,p_payload,p_payload_hash,
        p_prior_event_hash,p_event_hash,p_trace_id,p_workflow_id,p_run_id,p_artifact_refs
    );
    INSERT INTO public.command_dedup(
        idempotency_key,command_id,event_type,aggregate_type,aggregate_id,
        aggregate_version,payload_hash,prior_event_hash,event_hash,event_id
    ) VALUES (
        p_idempotency_key,p_command_id,p_event_type,p_aggregate_type,p_aggregate_id,
        p_aggregate_version,p_payload_hash,p_prior_event_hash,p_event_hash,p_event_id
    );
    INSERT INTO public.aggregate_head(
        aggregate_type,aggregate_id,version,last_event_id,last_event_hash
    ) VALUES (
        p_aggregate_type,p_aggregate_id,p_aggregate_version,p_event_id,p_event_hash
    ) ON CONFLICT (aggregate_type,aggregate_id) DO UPDATE SET
        version=EXCLUDED.version,
        last_event_id=EXCLUDED.last_event_id,
        last_event_hash=EXCLUDED.last_event_hash,
        updated_at=now();
    INSERT INTO public.transactional_outbox(outbox_id,event_id,topic,payload)
    VALUES (p_outbox_id,p_event_id,p_topic,jsonb_build_object(
        'event_id',p_event_id,'event_type',p_event_type,
        'aggregate_type',p_aggregate_type,'aggregate_id',p_aggregate_id,
        'aggregate_version',p_aggregate_version,'event_hash',p_event_hash
    ));
    RETURN p_event_id;
EXCEPTION
    WHEN unique_violation THEN
        SELECT * INTO existing_dedup
        FROM public.command_dedup
        WHERE idempotency_key = p_idempotency_key;
        IF FOUND
            AND existing_dedup.command_id = p_command_id
            AND existing_dedup.event_type = p_event_type
            AND existing_dedup.aggregate_type = p_aggregate_type
            AND existing_dedup.aggregate_id = p_aggregate_id
            AND existing_dedup.aggregate_version = p_aggregate_version
            AND existing_dedup.payload_hash = p_payload_hash
            AND existing_dedup.prior_event_hash IS NOT DISTINCT FROM p_prior_event_hash
            AND existing_dedup.event_hash = p_event_hash
        THEN
            RETURN existing_dedup.event_id;
        END IF;
        RAISE;
END;
$$;
"""

APPEND_SIGNATURE = """
text,text,text,text,bigint,timestamptz,text,text,text,text,text,text,jsonb,bytea,text,
text,bytea,text,text,text,text,jsonb,text,text
"""


def _utc_timestamp(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "domain_event",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _utc_timestamp("recorded_at"),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("causation_id", sa.Text()),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("command_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload_schema_version", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("prior_event_hash", sa.String(64)),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text()),
        sa.Column("run_id", sa.Text()),
        sa.Column("mlflow_run_id", sa.Text()),
        sa.Column("openlineage_run_id", sa.Text()),
        sa.Column(
            "artifact_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.CheckConstraint("aggregate_version > 0", name="ck_domain_event_positive_version"),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'", name="ck_domain_event_payload_hash_hex"
        ),
        sa.CheckConstraint("event_hash ~ '^[0-9a-f]{64}$'", name="ck_domain_event_event_hash_hex"),
        sa.UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            name="uq_domain_event_aggregate_version",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_domain_event_idempotency"),
        sa.UniqueConstraint("event_hash", name="uq_domain_event_hash"),
    )
    op.create_index(
        "ix_domain_event_correlation_recorded",
        "domain_event",
        ["correlation_id", "recorded_at"],
    )
    op.create_table(
        "command_dedup",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("command_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("prior_event_hash", sa.String(64)),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        _utc_timestamp("recorded_at"),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
    )
    op.create_table(
        "aggregate_head",
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("last_event_id", sa.Text(), nullable=False),
        sa.Column("last_event_hash", sa.String(64), nullable=False),
        _utc_timestamp("updated_at"),
        sa.PrimaryKeyConstraint("aggregate_type", "aggregate_id"),
        sa.ForeignKeyConstraint(["last_event_id"], ["domain_event.event_id"]),
    )
    op.create_table(
        "transactional_outbox",
        sa.Column("outbox_id", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _utc_timestamp("created_at"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
        sa.UniqueConstraint("event_id", "topic", name="uq_outbox_event_topic"),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "transactional_outbox",
        ["published_at", "created_at"],
    )
    op.create_table(
        "projection_checkpoint",
        sa.Column("projection_name", sa.Text(), primary_key=True),
        sa.Column("last_event_id", sa.Text()),
        sa.Column("last_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        _utc_timestamp("updated_at"),
    )
    op.execute(APPEND_FUNCTION)
    op.execute(
        f"""
        REVOKE ALL ON FUNCTION xinao_append_event({APPEND_SIGNATURE}) FROM PUBLIC;
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname='xinao_discovery_event_writer'
            ) THEN
                CREATE ROLE xinao_discovery_event_writer NOLOGIN;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname='xinao_discovery_projection_reader'
            ) THEN
                CREATE ROLE xinao_discovery_projection_reader NOLOGIN;
            END IF;
        END $$;
        GRANT SELECT ON domain_event, aggregate_head, transactional_outbox
            TO xinao_discovery_projection_reader;
        GRANT EXECUTE ON FUNCTION xinao_append_event({APPEND_SIGNATURE})
            TO xinao_discovery_event_writer;
        """
    )


def downgrade() -> None:
    event_count = op.get_bind().execute(sa.text("SELECT count(*) FROM domain_event")).scalar_one()
    if event_count and os.environ.get("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE") != (
        "isolated-canary-reset"
    ):
        raise RuntimeError(
            "domain ledger contains history; restore an isolated database instead of downgrading"
        )
    op.execute(
        f"""
        REVOKE ALL ON domain_event, aggregate_head, transactional_outbox
            FROM xinao_discovery_projection_reader;
        REVOKE ALL ON FUNCTION xinao_append_event({APPEND_SIGNATURE})
            FROM xinao_discovery_event_writer;
        DROP FUNCTION IF EXISTS xinao_append_event({APPEND_SIGNATURE});
        """
    )
    op.drop_table("projection_checkpoint")
    op.drop_index("ix_outbox_unpublished", table_name="transactional_outbox")
    op.drop_table("transactional_outbox")
    op.drop_table("aggregate_head")
    op.drop_table("command_dedup")
    op.drop_index("ix_domain_event_correlation_recorded", table_name="domain_event")
    op.drop_table("domain_event")
    op.execute(
        """
        DO $$ BEGIN
            DROP ROLE IF EXISTS xinao_discovery_event_writer;
            DROP ROLE IF EXISTS xinao_discovery_projection_reader;
        END $$;
        """
    )
