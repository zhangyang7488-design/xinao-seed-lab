"""Serialize period close with journal posting and reject closed-period rewrites."""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "0004_closed_period_journal_guard"
down_revision = "0003_shadow_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION xinao_guard_closed_period_journal()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
        DECLARE original_occurred_at timestamptz;
                adjusted_period public.accounting_period%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('xinao:closed-period-journal-boundary',0)
            );
            IF EXISTS(
                SELECT 1 FROM public.accounting_period
                WHERE status='CLOSED'
                  AND period_start<=NEW.occurred_at AND NEW.occurred_at<period_end
            ) THEN
                RAISE EXCEPTION 'journal timestamp belongs to a closed accounting period';
            END IF;
            IF NEW.transaction_type IN ('REVERSAL','PERIOD_ADJUSTMENT') THEN
                SELECT occurred_at INTO original_occurred_at
                FROM public.journal_group
                WHERE journal_group_id=NEW.reversal_of_group_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'correction requires an existing reversal target';
                END IF;
            END IF;
            IF NEW.transaction_type='REVERSAL' AND EXISTS(
                SELECT 1 FROM public.accounting_period
                WHERE status='CLOSED'
                  AND period_start<=original_occurred_at
                  AND original_occurred_at<period_end
            ) THEN
                RAISE EXCEPTION 'closed-period correction must use a PeriodAdjustment';
            END IF;
            IF NEW.transaction_type='PERIOD_ADJUSTMENT' THEN
                SELECT * INTO adjusted_period FROM public.accounting_period
                WHERE period_id=NEW.adjusts_period_id AND status='CLOSED';
                IF NOT FOUND
                   OR original_occurred_at<adjusted_period.period_start
                   OR original_occurred_at>=adjusted_period.period_end
                   OR NEW.occurred_at<adjusted_period.period_end
                THEN
                    RAISE EXCEPTION
                        'period adjustment target must belong to the referenced closed period';
                END IF;
            END IF;
            RETURN NEW;
        END; $$;

        CREATE OR REPLACE FUNCTION xinao_revalidate_period_close()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
        DECLARE expected_group_count bigint;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('xinao:closed-period-journal-boundary',0)
            );
            SELECT count(*) INTO expected_group_count FROM public.journal_group
            WHERE occurred_at>=NEW.period_start AND occurred_at<NEW.period_end;
            IF jsonb_typeof(NEW.projection->'journal_group_refs')<>'array'
               OR jsonb_array_length(NEW.projection->'journal_group_refs')<>expected_group_count
               OR EXISTS(
                    SELECT 1 FROM public.journal_group
                    WHERE occurred_at>=NEW.period_start AND occurred_at<NEW.period_end
                      AND NOT (NEW.projection->'journal_group_refs' ? journal_group_id)
               )
            THEN
                RAISE EXCEPTION 'period projection changed during close';
            END IF;
            RETURN NEW;
        END; $$;

        CREATE TRIGGER tr_journal_group_closed_period_guard
        BEFORE INSERT ON journal_group
        FOR EACH ROW EXECUTE FUNCTION xinao_guard_closed_period_journal();
        CREATE TRIGGER tr_accounting_period_close_revalidation
        BEFORE INSERT ON accounting_period
        FOR EACH ROW EXECUTE FUNCTION xinao_revalidate_period_close();

        REVOKE ALL ON FUNCTION xinao_guard_closed_period_journal() FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_revalidate_period_close() FROM PUBLIC;
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    history_count = connection.execute(
        text(
            "SELECT (SELECT count(*) FROM journal_group) + (SELECT count(*) FROM accounting_period)"
        )
    ).scalar_one()
    if history_count and os.environ.get("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE") != (
        "isolated-canary-reset"
    ):
        raise RuntimeError(
            "shadow accounting history exists; refusing to remove closed-period journal guard"
        )
    op.execute(
        r"""
        DROP TRIGGER IF EXISTS tr_accounting_period_close_revalidation ON accounting_period;
        DROP TRIGGER IF EXISTS tr_journal_group_closed_period_guard ON journal_group;
        DROP FUNCTION IF EXISTS xinao_revalidate_period_close();
        DROP FUNCTION IF EXISTS xinao_guard_closed_period_journal();
        """
    )
