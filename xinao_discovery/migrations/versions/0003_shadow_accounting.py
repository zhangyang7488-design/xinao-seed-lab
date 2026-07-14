"""Add append-only outcome, shadow journal, settlement, and weekly close records."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_shadow_accounting"
down_revision = "0002_append_only_freeze"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_portfolio",
        sa.Column("portfolio_id", sa.Text(), primary_key=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(20, 4), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "currency='normalized_shadow_unit'", name="ck_shadow_portfolio_currency"
        ),
        sa.CheckConstraint(
            "opening_balance=100000.0000", name="ck_shadow_portfolio_opening_balance"
        ),
        sa.CheckConstraint(
            "policy_hash ~ '^[0-9a-f]{64}$'", name="ck_shadow_portfolio_policy_hash"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
    )
    op.create_table(
        "outcome_observation",
        sa.Column("outcome_id", sa.Text(), primary_key=True),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("admission_status", sa.Text(), nullable=False),
        sa.Column("supersedes_outcome_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("result_hash ~ '^[0-9a-f]{64}$'", name="ck_outcome_result_hash"),
        sa.CheckConstraint(
            "admission_status IN ('ACCEPTED','QUARANTINED','CONFLICTED')",
            name="ck_outcome_admission_status",
        ),
        sa.ForeignKeyConstraint(["supersedes_outcome_id"], ["outcome_observation.outcome_id"]),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
        sa.UniqueConstraint(
            "source_ref", "target_ref", "result_hash", name="uq_outcome_source_target_result"
        ),
    )
    op.create_table(
        "outcome_conflict",
        sa.Column("conflict_id", sa.Text(), primary_key=True),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("existing_outcome_id", sa.Text(), nullable=False),
        sa.Column("conflicting_outcome_id", sa.Text(), nullable=False, unique=True),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "existing_outcome_id <> conflicting_outcome_id", name="ck_outcome_conflict_distinct"
        ),
        sa.ForeignKeyConstraint(["existing_outcome_id"], ["outcome_observation.outcome_id"]),
        sa.ForeignKeyConstraint(["conflicting_outcome_id"], ["outcome_observation.outcome_id"]),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
    )
    op.create_table(
        "journal_group",
        sa.Column("journal_group_id", sa.Text(), primary_key=True),
        sa.Column("portfolio_id", sa.Text(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("reversal_of_group_id", sa.Text(), nullable=True),
        sa.Column("adjusts_period_id", sa.Text(), nullable=True),
        sa.Column("group_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "transaction_type IN ('OPENING','POSITION_FROZEN','SETTLEMENT_HIT',"
            "'SETTLEMENT_MISS','FEE','REVERSAL','PERIOD_ADJUSTMENT')",
            name="ck_journal_group_type",
        ),
        sa.CheckConstraint("group_hash ~ '^[0-9a-f]{64}$'", name="ck_journal_group_hash"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["shadow_portfolio.portfolio_id"]),
        sa.ForeignKeyConstraint(["reversal_of_group_id"], ["journal_group.journal_group_id"]),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
    )
    op.create_table(
        "journal_entry",
        sa.Column("journal_group_id", sa.Text(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("entry_hash", sa.String(64), nullable=False, unique=True),
        sa.CheckConstraint("line_no > 0", name="ck_journal_entry_line_no"),
        sa.CheckConstraint("amount > 0", name="ck_journal_entry_positive_amount"),
        sa.CheckConstraint("side IN ('DEBIT','CREDIT')", name="ck_journal_entry_side"),
        sa.CheckConstraint("currency='normalized_shadow_unit'", name="ck_journal_entry_currency"),
        sa.CheckConstraint(
            "account IN ('ShadowCash','OpenPositionAsset','OpeningCapitalEquity',"
            "'RealizedGainRevenue','RealizedLossExpense','FeeExpense','VoidAdjustment',"
            "'RoundingAdjustment')",
            name="ck_journal_entry_account",
        ),
        sa.CheckConstraint("entry_hash ~ '^[0-9a-f]{64}$'", name="ck_journal_entry_hash"),
        sa.ForeignKeyConstraint(["journal_group_id"], ["journal_group.journal_group_id"]),
        sa.PrimaryKeyConstraint("journal_group_id", "line_no"),
    )
    op.create_table(
        "settlement_record",
        sa.Column("settlement_id", sa.Text(), primary_key=True),
        sa.Column("frozen_decision_id", sa.Text(), nullable=False, unique=True),
        sa.Column("outcome_id", sa.Text(), nullable=False),
        sa.Column("rule_ref", sa.Text(), nullable=False),
        sa.Column("settlement_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("journal_group_id", sa.Text(), nullable=False, unique=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("settlement_hash ~ '^[0-9a-f]{64}$'", name="ck_settlement_hash"),
        sa.ForeignKeyConstraint(["frozen_decision_id"], ["frozen_decision.decision_id"]),
        sa.ForeignKeyConstraint(["outcome_id"], ["outcome_observation.outcome_id"]),
        sa.ForeignKeyConstraint(["journal_group_id"], ["journal_group.journal_group_id"]),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
    )
    op.create_table(
        "accounting_period",
        sa.Column("period_id", sa.Text(), primary_key=True),
        sa.Column("policy_ref", sa.Text(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("projection_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("projection", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("period_start < period_end", name="ck_accounting_period_window"),
        sa.CheckConstraint("closed_at >= period_end", name="ck_accounting_period_closed_after_end"),
        sa.CheckConstraint("status='CLOSED'", name="ck_accounting_period_closed_status"),
        sa.CheckConstraint(
            "projection_hash ~ '^[0-9a-f]{64}$'", name="ck_accounting_period_projection_hash"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["domain_event.event_id"]),
        sa.UniqueConstraint(
            "policy_ref", "period_start", "period_end", name="uq_accounting_period"
        ),
    )
    op.create_foreign_key(
        "fk_journal_group_adjusts_period",
        "journal_group",
        "accounting_period",
        ["adjusts_period_id"],
        ["period_id"],
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION xinao_check_journal_balance()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        DECLARE debit numeric(20,4); credit numeric(20,4);
        BEGIN
            SELECT COALESCE(sum(amount) FILTER (WHERE side='DEBIT'),0),
                   COALESCE(sum(amount) FILTER (WHERE side='CREDIT'),0)
            INTO debit,credit FROM public.journal_entry
            WHERE journal_group_id=NEW.journal_group_id;
            IF debit <> credit OR debit <= 0 THEN
                RAISE EXCEPTION 'journal group % is not balanced',NEW.journal_group_id;
            END IF;
            RETURN NULL;
        END;
        $$;
        CREATE CONSTRAINT TRIGGER tr_journal_group_balance
        AFTER INSERT ON journal_entry DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION xinao_check_journal_balance();

        CREATE TRIGGER tr_shadow_portfolio_append_only BEFORE UPDATE OR DELETE ON shadow_portfolio
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_shadow_portfolio_no_truncate BEFORE TRUNCATE ON shadow_portfolio
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_outcome_observation_append_only
        BEFORE UPDATE OR DELETE ON outcome_observation
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_outcome_observation_no_truncate BEFORE TRUNCATE ON outcome_observation
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_outcome_conflict_append_only BEFORE UPDATE OR DELETE ON outcome_conflict
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_outcome_conflict_no_truncate BEFORE TRUNCATE ON outcome_conflict
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_journal_group_append_only BEFORE UPDATE OR DELETE ON journal_group
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_journal_group_no_truncate BEFORE TRUNCATE ON journal_group
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_journal_entry_append_only BEFORE UPDATE OR DELETE ON journal_entry
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_journal_entry_no_truncate BEFORE TRUNCATE ON journal_entry
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_settlement_record_append_only BEFORE UPDATE OR DELETE ON settlement_record
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_settlement_record_no_truncate BEFORE TRUNCATE ON settlement_record
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_accounting_period_append_only BEFORE UPDATE OR DELETE ON accounting_period
        FOR EACH ROW EXECUTE FUNCTION xinao_reject_mutation();
        CREATE TRIGGER tr_accounting_period_no_truncate BEFORE TRUNCATE ON accounting_period
        FOR EACH STATEMENT EXECUTE FUNCTION xinao_reject_mutation();
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION xinao_create_shadow_portfolio(
            p_portfolio_id text,p_policy_hash text,p_event_id text
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE current_row public.shadow_portfolio%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(p_portfolio_id,0));
            SELECT * INTO current_row FROM public.shadow_portfolio
            WHERE portfolio_id=p_portfolio_id;
            IF FOUND THEN
                IF current_row.policy_hash=p_policy_hash THEN
                    RETURN current_row.portfolio_id;
                END IF;
                RAISE EXCEPTION 'portfolio identity conflict';
            END IF;
            INSERT INTO public.shadow_portfolio(
                portfolio_id,currency,opening_balance,policy_hash,event_id
            ) VALUES (p_portfolio_id,'normalized_shadow_unit',100000.0000,p_policy_hash,p_event_id);
            RETURN p_portfolio_id;
        END; $$;

        CREATE OR REPLACE FUNCTION xinao_observe_outcome(
            p_outcome_id text,p_source_ref text,p_target_ref text,p_result_hash text,
            p_observed_at timestamptz,p_verified boolean,p_supersedes_outcome_id text,
            p_payload jsonb,p_event_id text,p_conflict_id text,p_conflict_event_id text
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE same_result public.outcome_observation%ROWTYPE;
                prior_result public.outcome_observation%ROWTYPE;
                admission text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(p_source_ref||':'||p_target_ref,0));
            SELECT * INTO same_result FROM public.outcome_observation
            WHERE source_ref=p_source_ref AND target_ref=p_target_ref AND result_hash=p_result_hash;
            IF FOUND THEN RETURN 'DUPLICATE:'||same_result.outcome_id; END IF;
            SELECT * INTO prior_result FROM public.outcome_observation
            WHERE source_ref=p_source_ref AND target_ref=p_target_ref
            ORDER BY created_at,outcome_id LIMIT 1;
            admission := CASE
                WHEN NOT p_verified THEN 'QUARANTINED'
                WHEN FOUND THEN 'CONFLICTED'
                ELSE 'ACCEPTED' END;
            INSERT INTO public.outcome_observation(
                outcome_id,source_ref,target_ref,result_hash,observed_at,verified,
                admission_status,supersedes_outcome_id,payload,event_id
            ) VALUES (
                p_outcome_id,p_source_ref,p_target_ref,p_result_hash,p_observed_at,p_verified,
                admission,p_supersedes_outcome_id,p_payload,p_event_id
            );
            IF admission='CONFLICTED' THEN
                IF p_conflict_id IS NULL OR p_conflict_event_id IS NULL THEN
                    RAISE EXCEPTION 'conflicting outcome requires conflict identity and event';
                END IF;
                INSERT INTO public.outcome_conflict(
                    conflict_id,source_ref,target_ref,existing_outcome_id,
                    conflicting_outcome_id,event_id
                ) VALUES (
                    p_conflict_id,p_source_ref,p_target_ref,prior_result.outcome_id,
                    p_outcome_id,p_conflict_event_id
                );
            END IF;
            RETURN admission||':'||p_outcome_id;
        END; $$;

        CREATE OR REPLACE FUNCTION xinao_post_journal(
            p_journal_group_id text,p_portfolio_id text,p_transaction_type text,
            p_occurred_at timestamptz,p_source_ref text,p_reversal_of_group_id text,
            p_adjusts_period_id text,p_group_hash text,p_lines jsonb,p_event_id text
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE current_row public.journal_group%ROWTYPE; item jsonb;
                debit numeric(20,4):=0; credit numeric(20,4):=0; amount numeric(20,4);
                entry_hash text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(p_journal_group_id,0));
            SELECT * INTO current_row FROM public.journal_group
            WHERE journal_group_id=p_journal_group_id;
            IF FOUND THEN
                IF current_row.group_hash=p_group_hash THEN
                    RETURN current_row.journal_group_id;
                END IF;
                RAISE EXCEPTION 'journal group identity conflict';
            END IF;
            IF jsonb_typeof(p_lines)<>'array' OR jsonb_array_length(p_lines)<2 THEN
                RAISE EXCEPTION 'journal group requires at least two lines';
            END IF;
            IF p_transaction_type IN ('REVERSAL','PERIOD_ADJUSTMENT') THEN
                IF p_reversal_of_group_id IS NULL OR NOT EXISTS(
                    SELECT 1 FROM public.journal_group WHERE journal_group_id=p_reversal_of_group_id
                ) THEN RAISE EXCEPTION 'correction requires an existing reversal target'; END IF;
            ELSIF p_reversal_of_group_id IS NOT NULL THEN
                RAISE EXCEPTION 'ordinary journal cannot mutate or reverse prior history';
            END IF;
            IF p_transaction_type='PERIOD_ADJUSTMENT' THEN
                IF p_adjusts_period_id IS NULL OR NOT EXISTS(
                    SELECT 1 FROM public.accounting_period
                    WHERE period_id=p_adjusts_period_id AND status='CLOSED'
                        AND period_end<=p_occurred_at
                ) THEN
                    RAISE EXCEPTION 'period adjustment requires an already closed period';
                END IF;
            ELSIF p_adjusts_period_id IS NOT NULL THEN
                RAISE EXCEPTION 'only period adjustment may reference a closed period';
            END IF;
            INSERT INTO public.journal_group(
                journal_group_id,portfolio_id,transaction_type,occurred_at,source_ref,
                reversal_of_group_id,adjusts_period_id,group_hash,event_id
            ) VALUES (
                p_journal_group_id,p_portfolio_id,p_transaction_type,p_occurred_at,p_source_ref,
                p_reversal_of_group_id,p_adjusts_period_id,p_group_hash,p_event_id
            );
            FOR item IN SELECT value FROM jsonb_array_elements(p_lines) LOOP
                amount := (item->>'amount')::numeric(20,4);
                IF amount<=0 OR item->>'amount' !~ '^[0-9]+\.[0-9]{4}$' THEN
                    RAISE EXCEPTION
                        'journal amount must be positive fixed-scale accounting decimal';
                END IF;
                IF item->>'side'='DEBIT' THEN debit:=debit+amount;
                ELSIF item->>'side'='CREDIT' THEN credit:=credit+amount;
                ELSE RAISE EXCEPTION 'journal side is invalid'; END IF;
                entry_hash:=encode(public.digest(convert_to(
                    jsonb_build_object(
                        'journal_group_id',p_journal_group_id,'line_no',(item->>'line_no')::int,
                        'account',item->>'account','side',item->>'side','amount',item->>'amount',
                        'currency',item->>'currency'
                    )::text,'UTF8'),'sha256'),'hex');
                INSERT INTO public.journal_entry(
                    journal_group_id,line_no,account,side,amount,currency,entry_hash
                ) VALUES (
                    p_journal_group_id,(item->>'line_no')::int,item->>'account',item->>'side',
                    amount,item->>'currency',entry_hash
                );
            END LOOP;
            IF debit<>credit OR debit<=0 THEN
                RAISE EXCEPTION 'journal group is not balanced';
            END IF;
            RETURN p_journal_group_id;
        END; $$;

        CREATE OR REPLACE FUNCTION xinao_record_settlement(
            p_settlement_id text,p_frozen_decision_id text,p_outcome_id text,p_rule_ref text,
            p_settlement_hash text,p_journal_group_id text,p_payload jsonb,p_event_id text
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE current_row public.settlement_record%ROWTYPE;
                frozen_target text; outcome_target text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(p_frozen_decision_id,0));
            SELECT * INTO current_row FROM public.settlement_record
            WHERE frozen_decision_id=p_frozen_decision_id;
            IF FOUND THEN
                IF current_row.settlement_hash=p_settlement_hash THEN
                    RETURN current_row.settlement_id;
                END IF;
                RAISE EXCEPTION 'settlement conflict must pause automatic posting';
            END IF;
            SELECT payload->>'target_ref' INTO frozen_target FROM public.frozen_decision
            WHERE decision_id=p_frozen_decision_id AND decision_type='ACTION';
            IF NOT FOUND THEN RAISE EXCEPTION 'settlement requires a frozen ACTION'; END IF;
            SELECT target_ref INTO outcome_target FROM public.outcome_observation
            WHERE outcome_id=p_outcome_id AND verified AND admission_status='ACCEPTED';
            IF NOT FOUND OR outcome_target IS DISTINCT FROM frozen_target THEN
                RAISE EXCEPTION 'settlement requires an accepted matching outcome';
            END IF;
            IF EXISTS(SELECT 1 FROM public.outcome_conflict WHERE target_ref=outcome_target) THEN
                RAISE EXCEPTION 'outcome conflict pauses settlement';
            END IF;
            IF NOT EXISTS(
                SELECT 1 FROM public.journal_group
                WHERE journal_group_id=p_journal_group_id
            )
            THEN RAISE EXCEPTION 'settlement journal does not exist'; END IF;
            INSERT INTO public.settlement_record(
                settlement_id,frozen_decision_id,outcome_id,rule_ref,settlement_hash,
                journal_group_id,payload,event_id
            ) VALUES (
                p_settlement_id,p_frozen_decision_id,p_outcome_id,p_rule_ref,p_settlement_hash,
                p_journal_group_id,p_payload,p_event_id
            );
            RETURN p_settlement_id;
        END; $$;

        CREATE OR REPLACE FUNCTION xinao_close_accounting_period(
            p_period_id text,p_policy_ref text,p_period_start timestamptz,p_period_end timestamptz,
            p_closed_at timestamptz,p_projection_hash text,p_projection jsonb,p_event_id text
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE current_row public.accounting_period%ROWTYPE;
                computed_balances jsonb; expected_group_count bigint;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(p_period_id,0));
            SELECT * INTO current_row FROM public.accounting_period WHERE period_id=p_period_id;
            IF FOUND THEN
                IF current_row.projection_hash=p_projection_hash THEN
                    RETURN current_row.period_id;
                END IF;
                RAISE EXCEPTION 'closed period identity conflict';
            END IF;
            IF p_period_start>=p_period_end OR p_closed_at<p_period_end
                OR clock_timestamp()<p_period_end
            THEN
                RAISE EXCEPTION 'period boundary or close time is invalid';
            END IF;
            IF p_projection->>'status' IS DISTINCT FROM 'RECONCILED'
                OR jsonb_typeof(p_projection->'unresolved_decision_refs')<>'array'
                OR jsonb_array_length(p_projection->'unresolved_decision_refs')<>0
                OR jsonb_typeof(p_projection->'conflicted_target_refs')<>'array'
                OR jsonb_array_length(p_projection->'conflicted_target_refs')<>0
            THEN RAISE EXCEPTION 'missing or conflicting facts block period close'; END IF;
            IF jsonb_typeof(p_projection->'journal_group_refs')<>'array' THEN
                RAISE EXCEPTION 'period projection journal group refs are required';
            END IF;
            SELECT count(*) INTO expected_group_count FROM public.journal_group
            WHERE occurred_at>=p_period_start AND occurred_at<p_period_end;
            IF jsonb_array_length(p_projection->'journal_group_refs')<>expected_group_count
                OR EXISTS(
                    SELECT 1 FROM public.journal_group
                    WHERE occurred_at>=p_period_start AND occurred_at<p_period_end
                      AND NOT (p_projection->'journal_group_refs' ? journal_group_id)
                )
            THEN RAISE EXCEPTION 'period projection omits or adds journal groups'; END IF;
            WITH accounts(account) AS (
                VALUES ('ShadowCash'),('OpenPositionAsset'),('OpeningCapitalEquity'),
                    ('RealizedGainRevenue'),('RealizedLossExpense'),('FeeExpense'),
                    ('VoidAdjustment'),('RoundingAdjustment')
            ), balances AS (
                SELECT a.account,
                    COALESCE(sum(
                        CASE
                            WHEN g.journal_group_id IS NULL THEN 0
                            WHEN e.side='DEBIT' THEN e.amount
                            ELSE -e.amount
                        END
                    ),0)::numeric(20,4) AS amount
                FROM accounts a
                LEFT JOIN public.journal_entry e ON e.account=a.account
                LEFT JOIN public.journal_group g ON g.journal_group_id=e.journal_group_id
                    AND g.occurred_at>=p_period_start AND g.occurred_at<p_period_end
                GROUP BY a.account
            )
            SELECT jsonb_object_agg(
                account,to_char(amount,'FM9999999999999990.0000') ORDER BY account
            ) INTO computed_balances FROM balances;
            IF p_projection->'balances' IS DISTINCT FROM computed_balances THEN
                RAISE EXCEPTION 'period projection balances do not replay from journal';
            END IF;
            INSERT INTO public.accounting_period(
                period_id,policy_ref,period_start,period_end,closed_at,status,
                projection_hash,projection,event_id
            ) VALUES (
                p_period_id,p_policy_ref,p_period_start,p_period_end,p_closed_at,'CLOSED',
                p_projection_hash,p_projection,p_event_id
            );
            RETURN p_period_id;
        END; $$;
        """
    )
    op.execute(
        r"""
        DO $$ BEGIN
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='xinao_discovery_settlement_writer')
            THEN CREATE ROLE xinao_discovery_settlement_writer NOLOGIN; END IF;
        END $$;
        REVOKE ALL ON shadow_portfolio,outcome_observation,outcome_conflict,journal_group,
            journal_entry,settlement_record,accounting_period FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_create_shadow_portfolio(text,text,text) FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_observe_outcome(
            text,text,text,text,timestamptz,boolean,text,jsonb,text,text,text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_post_journal(
            text,text,text,timestamptz,text,text,text,text,jsonb,text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_record_settlement(
            text,text,text,text,text,text,jsonb,text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_close_accounting_period(
            text,text,timestamptz,timestamptz,timestamptz,text,jsonb,text
        ) FROM PUBLIC;
        GRANT SELECT ON shadow_portfolio,outcome_observation,outcome_conflict,journal_group,
            journal_entry,settlement_record,accounting_period TO xinao_discovery_settlement_writer;
        GRANT EXECUTE ON FUNCTION xinao_create_shadow_portfolio(text,text,text)
            TO xinao_discovery_settlement_writer;
        GRANT EXECUTE ON FUNCTION xinao_observe_outcome(
            text,text,text,text,timestamptz,boolean,text,jsonb,text,text,text
        ) TO xinao_discovery_settlement_writer;
        GRANT EXECUTE ON FUNCTION xinao_post_journal(
            text,text,text,timestamptz,text,text,text,text,jsonb,text
        ) TO xinao_discovery_settlement_writer;
        GRANT EXECUTE ON FUNCTION xinao_record_settlement(
            text,text,text,text,text,text,jsonb,text
        ) TO xinao_discovery_settlement_writer;
        GRANT EXECUTE ON FUNCTION xinao_close_accounting_period(
            text,text,timestamptz,timestamptz,timestamptz,text,jsonb,text
        ) TO xinao_discovery_settlement_writer;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM shadow_portfolio)+"
            "(SELECT count(*) FROM outcome_observation)+"
            "(SELECT count(*) FROM journal_group)+"
            "(SELECT count(*) FROM settlement_record)+"
            "(SELECT count(*) FROM accounting_period)"
        )
    ).scalar_one()
    if count and os.environ.get("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE") != "isolated-canary-reset":
        raise RuntimeError("shadow accounting history exists; restore an isolated database instead")
    op.execute(
        r"""
        DROP FUNCTION IF EXISTS xinao_close_accounting_period(
            text,text,timestamptz,timestamptz,timestamptz,text,jsonb,text
        );
        DROP FUNCTION IF EXISTS xinao_record_settlement(text,text,text,text,text,text,jsonb,text);
        DROP FUNCTION IF EXISTS xinao_post_journal(
            text,text,text,timestamptz,text,text,text,text,jsonb,text
        );
        DROP FUNCTION IF EXISTS xinao_observe_outcome(
            text,text,text,text,timestamptz,boolean,text,jsonb,text,text,text
        );
        DROP FUNCTION IF EXISTS xinao_create_shadow_portfolio(text,text,text);
        DROP TRIGGER IF EXISTS tr_journal_group_balance ON journal_entry;
        DROP FUNCTION IF EXISTS xinao_check_journal_balance();
        """
    )
    op.drop_constraint("fk_journal_group_adjusts_period", "journal_group", type_="foreignkey")
    for table in (
        "accounting_period",
        "settlement_record",
        "journal_entry",
        "journal_group",
        "outcome_conflict",
        "outcome_observation",
        "shadow_portfolio",
    ):
        op.drop_table(table)
    op.execute("DROP ROLE IF EXISTS xinao_discovery_settlement_writer")
