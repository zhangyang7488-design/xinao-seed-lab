"""Bind exact scientific decision identity into freeze and settlement."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "0005_science_decision_kind"
down_revision = "0004_closed_period_journal_guard"
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

SCIENTIFIC_FREEZE_FUNCTION = r"""
CREATE FUNCTION xinao_freeze_decision(
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
    exact_decision_kind text;
    exact_candidate_qualification text;
    exact_claim_scope text;
    computed_candidate_refs_hash text;
    readback_content_hash text;
    readback_event_hash text;
BEGIN
    decision_basis := pg_catalog.convert_from(p_decision_canonical, 'UTF8')::jsonb;
    exact_decision_kind := decision_basis->>'decision_kind';
    exact_candidate_qualification := decision_basis->>'candidate_qualification';
    exact_claim_scope := decision_basis->>'claim_scope';

    IF encode(public.digest(p_decision_canonical, 'sha256'), 'hex') <> p_decision_hash
        OR decision_basis->>'decision_ref' IS DISTINCT FROM p_decision_id
        OR decision_basis->>'decision_plan_ref' IS DISTINCT FROM p_decision_plan_id
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
        OR (decision_basis->>'frozen_at')::timestamptz IS DISTINCT FROM p_occurred_at
        OR p_payload - 'content_hash' IS DISTINCT FROM decision_basis
        OR p_payload->>'content_hash' IS DISTINCT FROM p_decision_hash
    THEN
        RAISE EXCEPTION 'decision canonical bytes, payload, identity, or hash mismatch';
    END IF;

    IF p_aggregate_type <> 'FrozenDecision'
        OR p_aggregate_id <> p_decision_id
        OR p_aggregate_version <> 1
    THEN
        RAISE EXCEPTION 'freeze event aggregate identity is invalid';
    END IF;
    IF p_target_window_start > p_target_window_end
        OR p_freeze_deadline >= p_target_open_time
        OR p_knowledge_cutoff >= p_target_open_time
        OR p_occurred_at > p_freeze_deadline
        OR clock_timestamp() > p_freeze_deadline
    THEN
        RAISE EXCEPTION 'freeze is late or has an invalid temporal boundary';
    END IF;
    IF jsonb_typeof(p_candidate_refs) IS DISTINCT FROM 'array'
        OR jsonb_array_length(p_candidate_refs) = 0
        OR COALESCE(p_candidate_refs_hash, '') !~ '^[0-9a-f]{64}$'
        OR COALESCE(p_decision_hash, '') !~ '^[0-9a-f]{64}$'
        OR COALESCE(decision_basis->>'decision_plan_hash', '') !~ '^[0-9a-f]{64}$'
        OR COALESCE(decision_basis->>'court_verdict_bundle_content_hash', '')
            !~ '^[0-9a-f]{64}$'
        OR COALESCE(decision_basis->>'protocol_pin_sha256', '') !~ '^[0-9a-f]{64}$'
        OR COALESCE(decision_basis->>'information_set_hash', '') !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION 'freeze candidates or scientific hashes are invalid';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_candidate_refs) AS candidate(value)
        WHERE jsonb_typeof(candidate.value) <> 'string'
    ) THEN
        RAISE EXCEPTION 'freeze candidate references must be text';
    END IF;
    SELECT encode(
        public.digest(
            pg_catalog.convert_to(
                '[' || string_agg(candidate.value::text, ',' ORDER BY candidate.ordinality) || ']',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
    INTO computed_candidate_refs_hash
    FROM jsonb_array_elements(p_candidate_refs)
        WITH ORDINALITY AS candidate(value, ordinality);
    IF computed_candidate_refs_hash IS DISTINCT FROM p_candidate_refs_hash THEN
        RAISE EXCEPTION 'candidate_refs_hash does not bind candidate_refs';
    END IF;
    IF jsonb_typeof(decision_basis->'adjudicated_decision_kinds')
            IS DISTINCT FROM 'array'
        OR NOT (decision_basis->'adjudicated_decision_kinds' ? exact_decision_kind)
        OR jsonb_typeof(decision_basis->'no_action_reasons') IS DISTINCT FROM 'array'
    THEN
        RAISE EXCEPTION 'freeze kind is not admitted by the court bundle';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(
            decision_basis->'adjudicated_decision_kinds'
        ) AS admitted(kind)
        WHERE admitted.kind NOT IN (
            'FROZEN_EXPERIMENTAL_SHADOW',
            'FROZEN_ELIGIBLE_ACTION',
            'NO_ACTION'
        )
    ) OR (
        SELECT count(*) <> count(DISTINCT admitted.kind)
        FROM jsonb_array_elements_text(
            decision_basis->'adjudicated_decision_kinds'
        ) AS admitted(kind)
    ) THEN
        RAISE EXCEPTION 'adjudicated decision kinds are duplicated or unrecognized';
    END IF;
    IF COALESCE(decision_basis->>'court_verdict_bundle_ref', '') = ''
        OR COALESCE(decision_basis->>'protocol_pin_ref', '') = ''
        OR COALESCE(decision_basis->>'information_set_ref', '') = ''
        OR COALESCE(decision_basis->>'odds_version_ref', '') = ''
        OR COALESCE(decision_basis->>'cost_version_ref', '') = ''
        OR COALESCE(decision_basis->>'friction_version_ref', '') = ''
        OR COALESCE(decision_basis->>'exposure_policy_ref', '') = ''
        OR COALESCE(decision_basis->>'target_ref', '') = ''
    THEN
        RAISE EXCEPTION 'freeze scientific identity references are incomplete';
    END IF;

    IF exact_decision_kind = 'FROZEN_EXPERIMENTAL_SHADOW' THEN
        IF exact_candidate_qualification IS DISTINCT FROM 'SHADOW_EXPERIMENTAL'
            OR p_decision_type <> 'ACTION'
            OR exact_claim_scope IS DISTINCT FROM 'EXPERIMENTAL_ONLY'
            OR p_event_type <> 'ActionFrozen'
            OR jsonb_array_length(decision_basis->'no_action_reasons') <> 0
        THEN
            RAISE EXCEPTION 'experimental shadow scientific axes disagree';
        END IF;
    ELSIF exact_decision_kind = 'FROZEN_ELIGIBLE_ACTION' THEN
        IF exact_candidate_qualification IS DISTINCT FROM 'SHADOW_CLAIM_ELIGIBLE'
            OR p_decision_type <> 'ACTION'
            OR exact_claim_scope IS DISTINCT FROM 'CLAIM_ELIGIBLE'
            OR p_event_type <> 'ActionFrozen'
            OR jsonb_array_length(decision_basis->'no_action_reasons') <> 0
        THEN
            RAISE EXCEPTION 'claim-eligible shadow scientific axes disagree';
        END IF;
    ELSIF exact_decision_kind = 'NO_ACTION' THEN
        IF exact_candidate_qualification IS NOT NULL
            OR p_decision_type <> 'NO_ACTION'
            OR exact_claim_scope IS DISTINCT FROM 'NO_ACTION'
            OR p_event_type <> 'NoActionFrozen'
            OR jsonb_array_length(decision_basis->'no_action_reasons') = 0
        THEN
            RAISE EXCEPTION 'NO_ACTION scientific axes disagree';
        END IF;
    ELSE
        RAISE EXCEPTION 'freeze decision kind is not recognized';
    END IF;

    SELECT * INTO existing_decision
    FROM public.frozen_decision
    WHERE decision_id = p_decision_id
    FOR UPDATE;
    IF FOUND THEN
        IF existing_decision.decision_id = p_decision_id
            AND existing_decision.decision_hash = p_decision_hash
            AND existing_decision.content_hash = p_decision_hash
            AND existing_decision.decision_plan_id = p_decision_plan_id
            AND existing_decision.target_window_start = p_target_window_start
            AND existing_decision.target_window_end = p_target_window_end
            AND existing_decision.target_open_time = p_target_open_time
            AND existing_decision.candidate_refs = p_candidate_refs
            AND existing_decision.candidate_refs_hash = p_candidate_refs_hash
            AND existing_decision.freeze_deadline = p_freeze_deadline
            AND existing_decision.knowledge_cutoff = p_knowledge_cutoff
            AND existing_decision.decision_type = p_decision_type
            AND existing_decision.decision_kind = exact_decision_kind
            AND existing_decision.candidate_qualification
                IS NOT DISTINCT FROM exact_candidate_qualification
            AND existing_decision.payload = p_payload
        THEN
            RETURN existing_decision.decision_id;
        END IF;
        RAISE EXCEPTION 'freeze identity or content hash conflict';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.frozen_decision
        WHERE decision_hash = p_decision_hash OR content_hash = p_decision_hash
    ) THEN
        RAISE EXCEPTION 'freeze content hash already belongs to another decision';
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
        knowledge_cutoff,decision_type,decision_hash,payload,event_id,
        decision_kind,candidate_qualification,content_hash
    ) VALUES (
        p_decision_id,p_decision_plan_id,p_target_window_start,p_target_window_end,
        p_target_open_time,p_candidate_refs,p_candidate_refs_hash,p_freeze_deadline,
        p_knowledge_cutoff,p_decision_type,p_decision_hash,p_payload,appended_event_id,
        exact_decision_kind,exact_candidate_qualification,p_decision_hash
    );
    SELECT content_hash INTO STRICT readback_content_hash
    FROM public.frozen_decision WHERE decision_id = p_decision_id;
    SELECT event_hash INTO STRICT readback_event_hash
    FROM public.domain_event WHERE event_id = appended_event_id;
    IF readback_content_hash <> p_decision_hash
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
            AND existing_decision.content_hash = p_decision_hash
            AND existing_decision.decision_plan_id = p_decision_plan_id
            AND existing_decision.target_window_start = p_target_window_start
            AND existing_decision.target_window_end = p_target_window_end
            AND existing_decision.target_open_time = p_target_open_time
            AND existing_decision.candidate_refs = p_candidate_refs
            AND existing_decision.candidate_refs_hash = p_candidate_refs_hash
            AND existing_decision.freeze_deadline = p_freeze_deadline
            AND existing_decision.knowledge_cutoff = p_knowledge_cutoff
            AND existing_decision.decision_type = p_decision_type
            AND existing_decision.decision_kind = exact_decision_kind
            AND existing_decision.candidate_qualification
                IS NOT DISTINCT FROM exact_candidate_qualification
            AND existing_decision.payload = p_payload
        THEN
            RETURN existing_decision.decision_id;
        END IF;
        RAISE;
END;
$$;
"""

SETTLEMENT_DECISION_KIND_GUARD = r"""
CREATE OR REPLACE FUNCTION xinao_guard_settlement_decision_kind()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    exact_kind text;
    exact_content_hash text;
BEGIN
    SELECT decision_kind, content_hash INTO exact_kind, exact_content_hash
    FROM public.frozen_decision
    WHERE decision_id = NEW.frozen_decision_id;
    IF NOT FOUND
        OR exact_kind NOT IN ('FROZEN_EXPERIMENTAL_SHADOW', 'FROZEN_ELIGIBLE_ACTION')
        OR exact_content_hash IS NULL
    THEN
        RAISE EXCEPTION 'settlement requires an exact frozen shadow decision kind';
    END IF;
    IF NEW.payload->>'settlement_ref' IS DISTINCT FROM NEW.settlement_id
        OR NEW.payload->>'frozen_decision_ref' IS DISTINCT FROM NEW.frozen_decision_id
        OR NEW.payload->>'frozen_decision_hash' IS DISTINCT FROM exact_content_hash
        OR NEW.payload->>'outcome_ref' IS DISTINCT FROM NEW.outcome_id
        OR NEW.payload->>'rule_ref' IS DISTINCT FROM NEW.rule_ref
        OR NEW.payload->>'journal_group_ref' IS DISTINCT FROM NEW.journal_group_id
        OR NEW.payload->>'settlement_hash' IS DISTINCT FROM NEW.settlement_hash
    THEN
        RAISE EXCEPTION 'settlement payload does not bind the exact frozen decision';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tr_settlement_decision_kind_guard
BEFORE INSERT ON settlement_record
FOR EACH ROW EXECUTE FUNCTION xinao_guard_settlement_decision_kind();
"""


def upgrade() -> None:
    op.add_column("frozen_decision", sa.Column("decision_kind", sa.Text(), nullable=True))
    op.add_column(
        "frozen_decision",
        sa.Column("candidate_qualification", sa.Text(), nullable=True),
    )
    op.add_column(
        "frozen_decision",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_frozen_decision_science_axes",
        "frozen_decision",
        """
        (
            decision_kind IS NULL
            AND candidate_qualification IS NULL
            AND content_hash IS NULL
        ) OR (
            content_hash = decision_hash
            AND (
                (
                    decision_kind = 'FROZEN_EXPERIMENTAL_SHADOW'
                    AND candidate_qualification = 'SHADOW_EXPERIMENTAL'
                    AND decision_type = 'ACTION'
                ) OR (
                    decision_kind = 'FROZEN_ELIGIBLE_ACTION'
                    AND candidate_qualification = 'SHADOW_CLAIM_ELIGIBLE'
                    AND decision_type = 'ACTION'
                ) OR (
                    decision_kind = 'NO_ACTION'
                    AND candidate_qualification IS NULL
                    AND decision_type = 'NO_ACTION'
                )
            )
        )
        """,
    )
    op.create_check_constraint(
        "ck_frozen_content_hash_hex",
        "frozen_decision",
        "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_unique_constraint(
        "uq_frozen_decision_content_hash",
        "frozen_decision",
        ["content_hash"],
    )
    op.execute(
        f"""
        ALTER FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE})
            RENAME TO xinao_freeze_decision_rollback_0002;
        REVOKE ALL ON FUNCTION xinao_freeze_decision_rollback_0002({FREEZE_SIGNATURE})
            FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_freeze_decision_rollback_0002({FREEZE_SIGNATURE})
            FROM xinao_discovery_freeze_writer;
        """
    )
    op.execute(SCIENTIFIC_FREEZE_FUNCTION)
    op.execute(SETTLEMENT_DECISION_KIND_GUARD)
    op.execute(
        f"""
        REVOKE ALL ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE}) FROM PUBLIC;
        REVOKE ALL ON FUNCTION xinao_guard_settlement_decision_kind() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE})
            TO xinao_discovery_freeze_writer;
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    exact_row_count = connection.execute(
        sa.text("SELECT count(*) FROM frozen_decision WHERE decision_kind IS NOT NULL")
    ).scalar_one()
    if exact_row_count and os.environ.get("XINAO_ALLOW_DESTRUCTIVE_DOWNGRADE") != (
        "isolated-canary-reset"
    ):
        raise RuntimeError(
            "scientific frozen decisions exist; restore an isolated database instead"
        )
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS tr_settlement_decision_kind_guard ON settlement_record;
        DROP FUNCTION IF EXISTS xinao_guard_settlement_decision_kind();
        REVOKE ALL ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE})
            FROM xinao_discovery_freeze_writer;
        DROP FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE});
        ALTER FUNCTION xinao_freeze_decision_rollback_0002({FREEZE_SIGNATURE})
            RENAME TO xinao_freeze_decision;
        GRANT EXECUTE ON FUNCTION xinao_freeze_decision({FREEZE_SIGNATURE})
            TO xinao_discovery_freeze_writer;
        """
    )
    op.drop_constraint(
        "uq_frozen_decision_content_hash",
        "frozen_decision",
        type_="unique",
    )
    op.drop_constraint(
        "ck_frozen_content_hash_hex",
        "frozen_decision",
        type_="check",
    )
    op.drop_constraint(
        "ck_frozen_decision_science_axes",
        "frozen_decision",
        type_="check",
    )
    op.drop_column("frozen_decision", "content_hash")
    op.drop_column("frozen_decision", "candidate_qualification")
    op.drop_column("frozen_decision", "decision_kind")
