"""Create the isolated confirmation vault, finite query API, and budget ledger."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_confirmation_vault"
down_revision = None
branch_labels = None
depends_on = None

QUERY_SIGNATURE = "text,text,text,text,text"

QUERY_FUNCTION = r"""
CREATE OR REPLACE FUNCTION confirmation_api.query_candidate(
    p_query_id text,
    p_budget_id text,
    p_candidate_ref text,
    p_query_kind text,
    p_idempotency_key text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, confirmation_private
AS $$
DECLARE
    existing_query confirmation_private.confirmation_query_ledger%ROWTYPE;
    new_remaining integer;
    query_cost integer;
    sample_size bigint;
    effect_mean numeric;
    effect_stddev numeric;
    interval_margin numeric;
    disclosure jsonb;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_idempotency_key, 0)
    );
    SELECT * INTO existing_query
    FROM confirmation_private.confirmation_query_ledger
    WHERE idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF existing_query.budget_id = p_budget_id
            AND existing_query.candidate_ref = p_candidate_ref
            AND existing_query.query_kind = p_query_kind
        THEN
            RETURN pg_catalog.jsonb_build_object(
                'query_id', existing_query.query_id,
                'status', 'IDEMPOTENT_REPLAY',
                'remaining_queries', existing_query.remaining_after,
                'disclosure', existing_query.disclosure
            );
        END IF;
        RAISE EXCEPTION 'idempotency key reused for a different confirmation query';
    END IF;

    query_cost := CASE p_query_kind
        WHEN 'AGGREGATE_EFFECT' THEN 1
        WHEN 'FINAL_GATE' THEN 1
        ELSE NULL
    END;
    IF query_cost IS NULL THEN
        RAISE EXCEPTION 'query kind is not admitted';
    END IF;

    UPDATE confirmation_private.research_error_budget_ledger
    SET remaining_queries = remaining_queries - query_cost,
        version = version + 1,
        updated_at = clock_timestamp()
    WHERE budget_id = p_budget_id AND remaining_queries >= query_cost
    RETURNING remaining_queries INTO new_remaining;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'confirmation budget missing or exhausted';
    END IF;

    SELECT count(*), avg(metric_value), stddev_samp(metric_value)
    INTO sample_size, effect_mean, effect_stddev
    FROM confirmation_private.vault_observation
    WHERE candidate_ref = p_candidate_ref
      AND partition_name = CASE p_query_kind
          WHEN 'AGGREGATE_EFFECT' THEN 'CONFIRMATION'
          WHEN 'FINAL_GATE' THEN 'FINAL_HOLDOUT'
      END;

    interval_margin := CASE
        WHEN sample_size >= 2
        THEN 1.6448536269514722 * effect_stddev / sqrt(sample_size::numeric)
        ELSE NULL
    END;
    disclosure := pg_catalog.jsonb_build_object(
        'verdict', CASE
            WHEN sample_size = 0 THEN 'INSUFFICIENT_DATA'
            WHEN effect_mean > 0 THEN 'PASS'
            ELSE 'FAIL'
        END,
        'effect_mean', effect_mean,
        'effect_interval_90', pg_catalog.jsonb_build_object(
            'lower', effect_mean - interval_margin,
            'upper', effect_mean + interval_margin,
            'method', 'normal_approximation_two_sided_90'
        ),
        'sample_size', sample_size,
        'reason_code', CASE
            WHEN sample_size = 0 THEN 'NO_ADMITTED_OBSERVATIONS'
            WHEN effect_mean > 0 THEN 'POSITIVE_AGGREGATE_EFFECT'
            ELSE 'NON_POSITIVE_AGGREGATE_EFFECT'
        END
    );
    INSERT INTO confirmation_private.confirmation_query_ledger(
        query_id,budget_id,candidate_ref,query_kind,query_cost,idempotency_key,
        disclosure,remaining_after
    ) VALUES (
        p_query_id,p_budget_id,p_candidate_ref,p_query_kind,query_cost,p_idempotency_key,
        disclosure,new_remaining
    );
    RETURN pg_catalog.jsonb_build_object(
        'query_id', p_query_id,
        'status', 'EXECUTED',
        'remaining_queries', new_remaining,
        'disclosure', disclosure
    );
END;
$$;
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA confirmation_private")
    op.execute("CREATE SCHEMA confirmation_api")
    op.create_table(
        "vault_observation",
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("candidate_ref", sa.Text(), nullable=False),
        sa.Column("partition_name", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Numeric(30, 12), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "partition_name IN ('CONFIRMATION','FINAL_HOLDOUT')",
            name="ck_vault_observation_partition",
        ),
        schema="confirmation_private",
    )
    op.create_index(
        "ix_vault_observation_candidate_partition",
        "vault_observation",
        ["candidate_ref", "partition_name"],
        schema="confirmation_private",
    )
    op.create_table(
        "research_error_budget_ledger",
        sa.Column("budget_id", sa.Text(), primary_key=True),
        sa.Column("hypothesis_family", sa.Text(), nullable=False, unique=True),
        sa.Column("total_queries", sa.Integer(), nullable=False),
        sa.Column("remaining_queries", sa.Integer(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("total_queries >= 0", name="ck_budget_total_nonnegative"),
        sa.CheckConstraint("remaining_queries >= 0", name="ck_budget_remaining_nonnegative"),
        sa.CheckConstraint(
            "remaining_queries <= total_queries", name="ck_budget_remaining_within_total"
        ),
        schema="confirmation_private",
    )
    op.create_table(
        "confirmation_query_ledger",
        sa.Column("query_id", sa.Text(), primary_key=True),
        sa.Column("budget_id", sa.Text(), nullable=False),
        sa.Column("candidate_ref", sa.Text(), nullable=False),
        sa.Column("query_kind", sa.Text(), nullable=False),
        sa.Column("query_cost", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("disclosure", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("remaining_after", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "query_kind IN ('AGGREGATE_EFFECT','FINAL_GATE')",
            name="ck_confirmation_query_kind",
        ),
        sa.CheckConstraint("query_cost > 0", name="ck_confirmation_query_positive_cost"),
        sa.ForeignKeyConstraint(
            ["budget_id"],
            ["confirmation_private.research_error_budget_ledger.budget_id"],
        ),
        schema="confirmation_private",
    )
    op.create_index(
        "uq_confirmation_final_gate_once",
        "confirmation_query_ledger",
        ["candidate_ref"],
        unique=True,
        postgresql_where=sa.text("query_kind = 'FINAL_GATE'"),
        schema="confirmation_private",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION confirmation_private.reject_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP;
        END;
        $$;
        CREATE TRIGGER tr_confirmation_query_append_only
        BEFORE UPDATE OR DELETE ON confirmation_private.confirmation_query_ledger
        FOR EACH ROW EXECUTE FUNCTION confirmation_private.reject_mutation();
        """
    )
    op.execute(QUERY_FUNCTION)
    op.execute(
        f"""
        REVOKE ALL ON SCHEMA confirmation_private FROM PUBLIC;
        REVOKE ALL ON SCHEMA confirmation_api FROM PUBLIC;
        REVOKE ALL ON FUNCTION confirmation_api.query_candidate({QUERY_SIGNATURE}) FROM PUBLIC;
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname='xinao_discovery_confirmation_service'
            ) THEN
                CREATE ROLE xinao_discovery_confirmation_service NOLOGIN;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname='xinao_discovery_research_worker'
            ) THEN
                CREATE ROLE xinao_discovery_research_worker NOLOGIN;
            END IF;
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database());
            EXECUTE format(
                'GRANT CONNECT ON DATABASE %I TO xinao_discovery_confirmation_service',
                current_database()
            );
        END $$;
        GRANT USAGE ON SCHEMA confirmation_api
            TO xinao_discovery_confirmation_service;
        GRANT EXECUTE ON FUNCTION confirmation_api.query_candidate({QUERY_SIGNATURE})
            TO xinao_discovery_confirmation_service;
        """
    )


def downgrade() -> None:
    private_rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT (SELECT count(*) FROM confirmation_private.vault_observation) + "
                "(SELECT count(*) FROM confirmation_private.research_error_budget_ledger) + "
                "(SELECT count(*) FROM confirmation_private.confirmation_query_ledger)"
            )
        )
        .scalar_one()
    )
    if private_rows and os.environ.get("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE") != (
        "isolated-canary-reset"
    ):
        raise RuntimeError(
            "confirmation vault contains history; restore an isolated database instead"
        )
    op.execute(
        f"""
        REVOKE ALL ON FUNCTION confirmation_api.query_candidate({QUERY_SIGNATURE})
            FROM xinao_discovery_confirmation_service;
        REVOKE ALL ON SCHEMA confirmation_api
            FROM xinao_discovery_confirmation_service;
        DROP FUNCTION IF EXISTS confirmation_api.query_candidate({QUERY_SIGNATURE});
        DROP TRIGGER IF EXISTS tr_confirmation_query_append_only
            ON confirmation_private.confirmation_query_ledger;
        DROP FUNCTION IF EXISTS confirmation_private.reject_mutation();
        DO $$ BEGIN
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM xinao_discovery_confirmation_service',
                current_database()
            );
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO PUBLIC', current_database());
        END $$;
        """
    )
    op.drop_index(
        "uq_confirmation_final_gate_once",
        table_name="confirmation_query_ledger",
        schema="confirmation_private",
    )
    op.drop_table("confirmation_query_ledger", schema="confirmation_private")
    op.drop_table("research_error_budget_ledger", schema="confirmation_private")
    op.drop_index(
        "ix_vault_observation_candidate_partition",
        table_name="vault_observation",
        schema="confirmation_private",
    )
    op.drop_table("vault_observation", schema="confirmation_private")
    op.execute("DROP SCHEMA confirmation_api")
    op.execute("DROP SCHEMA confirmation_private")
    op.execute(
        """
        DO $$ BEGIN
            DROP ROLE IF EXISTS xinao_discovery_confirmation_service;
            DROP ROLE IF EXISTS xinao_discovery_research_worker;
        END $$;
        """
    )
