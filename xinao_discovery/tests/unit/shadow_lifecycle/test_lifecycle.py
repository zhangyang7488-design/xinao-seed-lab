"""Focused unit coverage for the leg-A shadow lifecycle vertical."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from xinao.decision import DecisionGateInput, DecisionKind, compile_decision_plan, freeze_decision
from xinao.settlement import OutcomeObservation
from xinao.shadow_lifecycle import (
    DEFAULT_OPENING_BALANCE,
    AccountDecisionIdentity,
    EvidenceState,
    ScienceDecisionIdentity,
    StatementResultKind,
    admit_episode_outcome,
    assess_fixture_evidence,
    assess_real_evidence,
    build_account_action,
    build_account_no_action,
    build_science_decision,
    create_seat,
    freeze_shadow_episode,
    reject_conflicting_settlement,
    reject_policy_as_account_ticket,
    replay_settled_episode,
    settle_shadow_episode,
)

OPEN = datetime(2026, 7, 20, 8, tzinfo=UTC)
FREEZE_AT = OPEN - timedelta(minutes=6)
DEADLINE = OPEN - timedelta(minutes=5)
CUTOFF = OPEN - timedelta(minutes=10)


def _frozen_shadow(**updates: Any):
    values: dict[str, Any] = {
        "candidate_ref": "candidate.signal.v1",
        "requested_decision_kind": "FROZEN_EXPERIMENTAL_SHADOW",
        "candidate_qualification": "SHADOW_EXPERIMENTAL",
        "adjudicated_decision_kinds": (
            "FROZEN_EXPERIMENTAL_SHADOW",
            "FROZEN_ELIGIBLE_ACTION",
            "NO_ACTION",
        ),
        "court_verdict_bundle_ref": "courts.signal.v1",
        "court_verdict_bundle_content_hash": "b" * 64,
        "protocol_pin_ref": "protocol.signal.v1",
        "protocol_pin_sha256": "c" * 64,
        "information_set_ref": "features.signal.v1",
        "information_set_hash": "d" * 64,
        "validation_report_ref": "validation.signal.v1",
        "validation_output_hash": "a" * 64,
        "validation_verdict": "ACTION",
        "baseline_ref": "baseline-odds-water.v1",
        "baseline_active": True,
        "rule_ref": "special-number-rule.v1",
        "rule_active": True,
        "odds_version_ref": "odds.signal.v1",
        "cost_version_ref": "cost.signal.v1",
        "friction_version_ref": "friction.signal.v1",
        "exposure_policy_ref": "shadow-exposure.minimal.v1",
        "target_ref": "draw.20260720-001",
        "target_window_start": OPEN,
        "target_window_end": OPEN,
        "target_open_time": OPEN,
        "freeze_deadline": DEADLINE,
        "knowledge_cutoff": CUTOFF,
        "compiled_at": OPEN - timedelta(minutes=20),
        "panel": "B",
        "selected_number": 1,
        "stake": "1.0000",
        "lower_expected_net": "0.2000",
        "estimated_cost": "0.0100",
        "risk_limit": "1.0000",
    }
    values.update(updates)
    plan = compile_decision_plan(
        DecisionGateInput.model_validate(values), plan_ref="plan.shadow.v1"
    )
    return freeze_decision(plan, decision_ref="frozen.shadow.v1", frozen_at=FREEZE_AT)


def _seat():
    return create_seat(seat_id="seat.researcher.alpha", portfolio_ref="portfolio.shadow.alpha")


def _science_candidate():
    return build_science_decision(
        science_decision_ref="science.candidate.v1",
        identity=ScienceDecisionIdentity.SCIENCE_CANDIDATE,
        knowledge_cutoff=CUTOFF,
        rationale_ref="rationale.science.v1",
        candidate_ref="candidate.signal.v1",
    )


def _science_policy_no_action():
    return build_science_decision(
        science_decision_ref="science.policy-no-action.v1",
        identity=ScienceDecisionIdentity.POLICY_NO_ACTION,
        knowledge_cutoff=CUTOFF,
        rationale_ref="rationale.policy.v1",
    )


def _outcome(
    *,
    ref: str = "outcome.1",
    special_number: int = 1,
    target_ref: str = "draw.20260720-001",
    observed_at: datetime | None = None,
    verified: bool = True,
):
    return OutcomeObservation(
        outcome_ref=ref,
        source_ref="macaujc2",
        target_ref=target_ref,
        actual_special_number=special_number,
        observed_at=observed_at if observed_at is not None else OPEN + timedelta(hours=1),
        verified=verified,
    ).with_hash()


def _freeze_action(**kwargs: Any):
    seat = kwargs.pop("seat", _seat())
    frozen = kwargs.pop("frozen", _frozen_shadow())
    science = kwargs.pop("science", _science_candidate())
    account = kwargs.pop(
        "account",
        build_account_action(account_decision_ref="acct.action.v1", frozen_decision=frozen),
    )
    values: dict[str, Any] = {
        "episode_ref": "episode.action.v1",
        "seat": seat,
        "science_decision": science,
        "account_decision": account,
        "target_ref": frozen.target_ref,
        "target_open_time": frozen.target_open_time,
        "freeze_deadline": frozen.freeze_deadline,
        "frozen_at": FREEZE_AT,
        "bound_frozen_decision": frozen,
        "opening_journal_group_ref": "journal.opening.episode.action.v1",
        "position_journal_group_ref": "journal.position.episode.action.v1",
    }
    values.update(kwargs)
    return freeze_shadow_episode(**values)


def _freeze_no_action(**kwargs: Any):
    seat = kwargs.pop("seat", _seat())
    science = kwargs.pop("science", _science_candidate())
    account = kwargs.pop(
        "account",
        build_account_no_action(
            account_decision_ref="acct.no-action.v1",
            rule_ref="special-number-rule.v1",
            odds_version_ref="odds.signal.v1",
        ),
    )
    values: dict[str, Any] = {
        "episode_ref": "episode.no-action.v1",
        "seat": seat,
        "science_decision": science,
        "account_decision": account,
        "target_ref": "draw.20260720-001",
        "target_open_time": OPEN,
        "freeze_deadline": DEADLINE,
        "frozen_at": FREEZE_AT,
    }
    values.update(kwargs)
    return freeze_shadow_episode(**values)


def test_seat_default_opening_balance_and_distinct_ids() -> None:
    seat = _seat()
    assert seat.opening_balance == DEFAULT_OPENING_BALANCE == "10000.0000"
    assert seat.seat_id != seat.portfolio_ref
    assert seat.content_hash == seat.compute_content_hash()
    with pytest.raises(ValueError, match="distinct"):
        create_seat(seat_id="same", portfolio_ref="same")


def test_action_full_closed_loop_and_deterministic_fresh_replay() -> None:
    episode = _freeze_action()
    assert episode.account_decision.identity == AccountDecisionIdentity.ACTION
    assert episode.opening_journal_group is not None
    assert episode.position_journal_group is not None
    assert episode.content_hash is not None

    outcome = _outcome(special_number=1)
    settled = settle_shadow_episode(
        episode=episode,
        outcome=outcome,
        settlement_ref="settlement.action.v1",
        settlement_journal_group_ref="journal.settlement.action.v1",
        statement_ref="statement.action.v1",
    )

    assert settled.statement.account_decision == AccountDecisionIdentity.ACTION
    assert settled.statement.result == StatementResultKind.HIT
    assert settled.statement.risk_stake == "1.0000"
    assert settled.statement.opening_balance == "10000.0000"
    assert settled.statement.pnl == "41.3850"
    assert settled.statement.closing_balance == "10041.3850"
    assert settled.statement.anomaly_status.value == "NONE"
    assert settled.settlement_bundle is not None
    assert len(settled.journal_groups) == 3

    replayed = replay_settled_episode(
        episode=episode,
        outcome=outcome,
        settled=settled,
        seat=_seat(),
        portfolio_ref=episode.portfolio_ref,
    )
    assert replayed.content_hash == settled.content_hash
    assert replayed.statement.content_hash == settled.statement.content_hash
    assert replayed.statement.closing_balance == settled.statement.closing_balance


def test_researcher_account_no_action_pre_outcome_freeze_and_zero_risk_statement() -> None:
    episode = _freeze_no_action()
    assert episode.is_account_pre_outcome_freeze()
    assert episode.account_decision.identity == AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION
    assert episode.account_decision.stake == "0.0000"
    assert episode.bound_frozen_decision is None
    assert episode.opening_journal_group is None
    assert episode.position_journal_group is None

    outcome = _outcome(special_number=7)
    settled = settle_shadow_episode(
        episode=episode,
        outcome=outcome,
        statement_ref="statement.no-action.v1",
    )
    assert settled.settlement_bundle is None
    assert settled.journal_groups == ()
    assert settled.statement.result == StatementResultKind.NO_EXPOSURE
    assert settled.statement.pnl == "0.0000"
    assert settled.statement.closing_balance == episode.pre_freeze_balance
    assert settled.statement.risk_stake == "0.0000"

    replayed = replay_settled_episode(episode=episode, outcome=outcome, settled=settled)
    assert replayed.content_hash == settled.content_hash


def test_scientific_policy_no_action_cannot_substitute_for_account_ticket() -> None:
    science = _science_policy_no_action()
    with pytest.raises(ValueError, match="cannot substitute"):
        reject_policy_as_account_ticket(science)

    # Freezing still requires an explicit account branch ticket; science alone is not enough.
    account = build_account_no_action(
        account_decision_ref="acct.explicit.v1",
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.signal.v1",
    )
    episode = _freeze_no_action(science=science, account=account)
    assert episode.science_decision.identity == ScienceDecisionIdentity.POLICY_NO_ACTION
    assert episode.account_decision.identity == AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION
    assert science.identity != AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION


def test_late_or_backdated_freeze_rejected() -> None:
    frozen = _frozen_shadow()
    account = build_account_action(account_decision_ref="acct.late.v1", frozen_decision=frozen)
    with pytest.raises(ValueError, match="late or backdated freeze"):
        freeze_shadow_episode(
            episode_ref="episode.late",
            seat=_seat(),
            science_decision=_science_candidate(),
            account_decision=account,
            target_ref=frozen.target_ref,
            target_open_time=OPEN,
            freeze_deadline=DEADLINE,
            frozen_at=DEADLINE + timedelta(seconds=1),
            bound_frozen_decision=frozen,
            opening_journal_group_ref="j.open",
            position_journal_group_ref="j.pos",
        )
    with pytest.raises(ValueError, match="late or backdated freeze"):
        freeze_shadow_episode(
            episode_ref="episode.bad-deadline",
            seat=_seat(),
            science_decision=_science_candidate(),
            account_decision=account,
            target_ref=frozen.target_ref,
            target_open_time=OPEN,
            freeze_deadline=OPEN,
            frozen_at=FREEZE_AT,
            bound_frozen_decision=frozen,
            opening_journal_group_ref="j.open",
            position_journal_group_ref="j.pos",
        )


def test_outcome_before_freeze_or_pre_open_outcome_rejected() -> None:
    episode = _freeze_action()
    pre_open = _outcome(observed_at=OPEN - timedelta(minutes=1))
    with pytest.raises(ValueError, match="pre-open"):
        admit_episode_outcome(episode=episode, candidate=pre_open)

    mid = episode.frozen_at + timedelta(seconds=1)
    assert mid < episode.target_open_time
    with pytest.raises(ValueError, match="pre-open"):
        admit_episode_outcome(episode=episode, candidate=_outcome(observed_at=mid))

    # Defensive path: outcome observed after open but still before a backdated freeze stamp.
    # Valid freezes never produce this ordering; construct keeps nested models intact for admit.
    late_fields = {name: getattr(episode, name) for name in type(episode).model_fields}
    late_fields["frozen_at"] = OPEN + timedelta(hours=2)
    late_freeze = type(episode).model_construct(**late_fields)
    early_after_open = _outcome(observed_at=OPEN + timedelta(minutes=1))
    with pytest.raises(ValueError, match="outcome-before-freeze"):
        admit_episode_outcome(episode=late_freeze, candidate=early_after_open)


def test_target_seat_portfolio_mismatch_rejected() -> None:
    episode = _freeze_action()
    wrong_target = _outcome(target_ref="draw.other")
    with pytest.raises(ValueError, match="target"):
        admit_episode_outcome(episode=episode, candidate=wrong_target)

    settled = settle_shadow_episode(
        episode=episode,
        outcome=_outcome(),
        settlement_ref="settlement.1",
        settlement_journal_group_ref="journal.settlement.1",
        statement_ref="statement.1",
    )
    other_seat = create_seat(seat_id="seat.other", portfolio_ref="portfolio.other")
    with pytest.raises(ValueError, match="cross-seat"):
        replay_settled_episode(
            episode=episode,
            outcome=_outcome(),
            settled=settled,
            seat=other_seat,
        )
    with pytest.raises(ValueError, match="cross-portfolio"):
        replay_settled_episode(
            episode=episode,
            outcome=_outcome(),
            settled=settled,
            portfolio_ref="portfolio.other",
        )


def test_double_or_conflicting_settlement_rejected() -> None:
    episode = _freeze_action()
    first = settle_shadow_episode(
        episode=episode,
        outcome=_outcome(special_number=1),
        settlement_ref="settlement.1",
        settlement_journal_group_ref="journal.settlement.1",
        statement_ref="statement.1",
    )
    with pytest.raises(ValueError, match=r"double|conflicting"):
        reject_conflicting_settlement(existing=first, candidate=first)

    second = settle_shadow_episode(
        episode=episode,
        outcome=_outcome(ref="outcome.2", special_number=2),
        settlement_ref="settlement.2",
        settlement_journal_group_ref="journal.settlement.2",
        statement_ref="statement.2",
    )
    with pytest.raises(ValueError, match="conflicting"):
        reject_conflicting_settlement(existing=first, candidate=second)

    # Same freeze cannot accept a second settlement record with different hash.
    assert first.settlement_bundle is not None
    with pytest.raises(ValueError, match=r"double or conflicting settlement|pause"):
        settle_shadow_episode(
            episode=episode,
            outcome=_outcome(ref="outcome.3", special_number=2),
            settlement_ref="settlement.3",
            settlement_journal_group_ref="journal.settlement.3",
            statement_ref="statement.3",
            existing_settlements=(first.settlement_bundle.record,),
        )


def test_mutated_sealed_content_and_replay_rejected() -> None:
    episode = _freeze_action()
    outcome = _outcome()
    settled = settle_shadow_episode(
        episode=episode,
        outcome=outcome,
        settlement_ref="settlement.mut.v1",
        settlement_journal_group_ref="journal.settlement.mut.v1",
        statement_ref="statement.mut.v1",
    )

    mutated_episode_fields = {name: getattr(episode, name) for name in type(episode).model_fields}
    mutated_episode_fields["target_ref"] = "draw.mutated"
    mutated_episode = type(episode).model_construct(**mutated_episode_fields)
    with pytest.raises(ValueError, match="mutated sealed episode"):
        replay_settled_episode(episode=mutated_episode, outcome=outcome, settled=settled)

    mutated_statement_fields = {
        name: getattr(settled.statement, name) for name in type(settled.statement).model_fields
    }
    mutated_statement_fields["pnl"] = "999.0000"
    mutated_statement = type(settled.statement).model_construct(**mutated_statement_fields)
    mutated_settled_fields = {name: getattr(settled, name) for name in type(settled).model_fields}
    mutated_settled_fields["statement"] = mutated_statement
    mutated_settled = type(settled).model_construct(**mutated_settled_fields)
    with pytest.raises(ValueError, match="mutated sealed settlement"):
        replay_settled_episode(episode=episode, outcome=outcome, settled=mutated_settled)

    half = settled.model_copy(
        update={"journal_groups": settled.journal_groups[:2]}
    ).with_content_hash()
    with pytest.raises(ValueError, match="half transaction"):
        replay_settled_episode(episode=episode, outcome=outcome, settled=half)


def test_synthetic_fixtures_cannot_claim_first_episode() -> None:
    evidence = assess_fixture_evidence(implementation_ready=True, synthetic_or_historical=True)
    assert evidence.state == EvidenceState.IMPLEMENTATION_READY
    assert evidence.first_episode_verified is False
    assert "FIRST_EPISODE_VERIFIED" in evidence.notes

    policy_only = assess_fixture_evidence(
        implementation_ready=True,
        science_only_policy_no_action=True,
        account_ticket_frozen=False,
    )
    assert policy_only.state == EvidenceState.IMPLEMENTATION_READY
    assert policy_only.state != EvidenceState.SHADOW_PRACTICE_STARTED
    assert "POLICY_NO_ACTION" in policy_only.notes

    # Real attestation path is separate and fail-closed without both attestations.
    started = assess_real_evidence(
        prospective_account_freeze_attested=True,
        independent_outcome_attested=False,
        closed_loop_verified=False,
    )
    assert started.state == EvidenceState.SHADOW_PRACTICE_STARTED
    assert started.first_episode_verified is False

    verified = assess_real_evidence(
        prospective_account_freeze_attested=True,
        independent_outcome_attested=True,
        closed_loop_verified=True,
    )
    assert verified.state == EvidenceState.FIRST_EPISODE_VERIFIED
    assert verified.first_episode_verified is True


def test_decision_kind_no_action_semantics_unchanged_for_settlement_binding() -> None:
    """Existing DecisionKind.NO_ACTION still cannot become an ACTION account ticket."""
    no_action = _frozen_shadow(requested_decision_kind="NO_ACTION", candidate_qualification=None)
    assert no_action.decision_kind == DecisionKind.NO_ACTION
    with pytest.raises(ValueError, match="exact frozen shadow decision kind"):
        build_account_action(account_decision_ref="acct.bad", frozen_decision=no_action)
