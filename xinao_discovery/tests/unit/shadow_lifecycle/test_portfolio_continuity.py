"""Same-seat prospective continuity through the real file-backed consumer."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.shadow_lifecycle import (
    AccountingBasis,
    FeedbackKind,
    ScienceDecisionIdentity,
    build_account_no_action,
    build_science_decision,
    feedback_portfolio_period,
    freeze_episode,
    freeze_portfolio_period,
    freeze_shadow_episode,
    init_episode,
    init_portfolio,
    inspect_episode,
    inspect_portfolio,
    replay_portfolio_period,
    settle_portfolio_period,
)
from xinao.shadow_lifecycle.store import (
    FEEDBACK_NAME,
    StoreError,
    load_frozen,
    load_seat,
    load_settled,
    period_directory,
    prepare_next_period_root,
)

OPEN_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
OPEN_2 = OPEN_1 + timedelta(days=1)


def _fixture_freeze_portfolio_period(**kwargs):
    """Shadow lifecycle unit fixtures only — not production authority."""
    from .fixture_portfolio_freeze import freeze_portfolio_period_for_fixture

    return freeze_portfolio_period_for_fixture(**kwargs)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _times(open_at: datetime) -> tuple[datetime, datetime, datetime]:
    return (
        open_at - timedelta(minutes=10),
        open_at - timedelta(minutes=6),
        open_at - timedelta(minutes=5),
    )


def _ticket_action_request(path: Path, *, open_at: datetime, period: int) -> Path:
    cutoff, frozen_at, deadline = _times(open_at)
    target_ref = f"draw.2026080{period}-001"
    body = {
        "episode_ref": f"episode.portfolio.p{period}",
        "science_decision": {
            "science_decision_ref": f"science.policy.p{period}",
            "identity": "POLICY_NO_ACTION",
            "knowledge_cutoff": cutoff.isoformat(),
            "rationale_ref": "science-not-an-account-admission-gate",
        },
        "account_decision": {
            "account_decision_ref": f"account.action.p{period}",
            "identity": "ACTION",
        },
        "bound_account_ticket": {
            "ticket_ref": f"account-ticket.p{period}",
            "target_ref": target_ref,
            "target_open_time": open_at.isoformat(),
            "freeze_deadline": deadline.isoformat(),
            "knowledge_cutoff": cutoff.isoformat(),
            "frozen_at": frozen_at.isoformat(),
            "panel": "B",
            "selected_number": 1,
            "stake": "1.0000",
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.special-number.20260731.v1",
            "baseline_ref": "BO0013",
            "risk_policy_ref": "shadow-risk.max-one-unit.v1",
            "information_set_ref": f"information.p{period}.v1",
            "information_set_hash": "a" * 64,
        },
        "target_ref": target_ref,
        "target_open_time": open_at.isoformat(),
        "freeze_deadline": deadline.isoformat(),
        "frozen_at": frozen_at.isoformat(),
        "position_journal_group_ref": f"journal.position.p{period}",
    }
    return _write_json(path, body)


def _no_action_request(path: Path, *, open_at: datetime, period: int) -> Path:
    cutoff, frozen_at, deadline = _times(open_at)
    target_ref = f"draw.2026080{period}-001"
    return _write_json(
        path,
        {
            "episode_ref": f"episode.portfolio.p{period}",
            "science_decision": {
                "science_decision_ref": f"science.candidate.p{period}",
                "identity": "SCIENCE_CANDIDATE",
                "candidate_ref": "candidate.wild-overfit-is-still-testable",
                "knowledge_cutoff": cutoff.isoformat(),
                "rationale_ref": "account-no-action-does-not-green-or-kill-science",
            },
            "account_decision": {
                "account_decision_ref": f"account.no-action.p{period}",
                "identity": "RESEARCHER_ACCOUNT_NO_ACTION",
                "rule_ref": "special-number-rule.v1",
                "odds_version_ref": "odds.special-number.20260731.v1",
            },
            "target_ref": target_ref,
            "target_open_time": open_at.isoformat(),
            "freeze_deadline": deadline.isoformat(),
            "frozen_at": frozen_at.isoformat(),
        },
    )


def _outcome(path: Path, *, open_at: datetime, period: int, number: int) -> Path:
    return _write_json(
        path,
        {
            "outcome_ref": f"outcome.portfolio.p{period}",
            "source_ref": "synthetic-test-fixture-only",
            "target_ref": f"draw.2026080{period}-001",
            "actual_special_number": number,
            "observed_at": (open_at + timedelta(hours=1)).isoformat(),
            "verified": True,
        },
    )


def test_two_period_ticket_action_then_no_action_same_seat(tmp_path: Path) -> None:
    root = tmp_path / "portfolio"
    initialized = init_portfolio(
        root=root,
        seat_id="seat.continuity.alpha",
        portfolio_ref="portfolio.continuity.alpha",
    )
    genesis_seat = load_seat(root)
    assert initialized["opening_balance"] == "10000.0000"

    frozen_1 = _fixture_freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(tmp_path / "p1-freeze.json", open_at=OPEN_1, period=1),
    )
    assert frozen_1["period_index"] == 1
    episode_1 = load_frozen(period_directory(root, 1))
    assert episode_1.accounting_basis == AccountingBasis.CARRIED_BALANCE_SNAPSHOT
    assert episode_1.bound_account_ticket is not None
    assert episode_1.bound_frozen_decision is None
    assert episode_1.opening_journal_group is None
    assert episode_1.prior_close_binding is None

    with pytest.raises(StoreError, match="cannot open a new period"):
        _fixture_freeze_portfolio_period(
            root=root,
            request_path=_no_action_request(tmp_path / "early-p2.json", open_at=OPEN_2, period=2),
        )

    settled_1 = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "p1-outcome.json", open_at=OPEN_1, period=1, number=1),
    )
    assert settled_1["statement_result"] == "HIT"
    assert settled_1["pnl"] == "41.3850"
    assert settled_1["closing_balance"] == "10041.3850"
    feedback_1 = feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="CONTINUE_TO_NEXT_PROSPECTIVE_PERIOD",
    )
    assert feedback_1["scientific_promotion"] is False

    frozen_2 = _fixture_freeze_portfolio_period(
        root=root,
        request_path=_no_action_request(tmp_path / "p2-freeze.json", open_at=OPEN_2, period=2),
    )
    assert frozen_2["period_index"] == 2
    episode_2 = load_frozen(period_directory(root, 2))
    assert episode_2.pre_freeze_balance == "10041.3850"
    assert episode_2.opening_balance == "10000.0000"
    assert episode_2.prior_close_binding is not None
    assert episode_2.prior_close_binding.prior_closing_balance == "10041.3850"
    assert episode_2.opening_journal_group is None
    assert episode_2.position_journal_group is None

    settled_2 = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "p2-outcome.json", open_at=OPEN_2, period=2, number=49),
    )
    assert settled_2["statement_result"] == "NO_EXPOSURE"
    assert settled_2["pnl"] == "0.0000"
    assert settled_2["closing_balance"] == "10041.3850"
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.TYPED_FEEDBACK,
        notes="no exposure; preserve carried balance",
    )

    assert replay_portfolio_period(root=root, period_index=1)["replay_match"] is True
    assert replay_portfolio_period(root=root, period_index=2)["replay_match"] is True
    final = inspect_portfolio(root=root)
    assert final["head_period_index"] == 2
    assert final["phase"] == "FEEDBACK_SEALED"
    assert final["closing_balance"] == "10041.3850"
    assert final["scientific_promotion"] is False
    assert load_seat(root) == genesis_seat


def test_account_ticket_rejects_scientific_gate_fields(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-extra"
    init_portfolio(root=root, seat_id="seat.extra", portfolio_ref="portfolio.extra")
    request = _ticket_action_request(tmp_path / "extra.json", open_at=OPEN_1, period=1)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["bound_account_ticket"]["court_verdict_bundle_ref"] = "must-not-enter-account-gate"
    _write_json(request, payload)
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _fixture_freeze_portfolio_period(root=root, request_path=request)


def test_feedback_is_exclusive_and_second_genesis_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-exclusive"
    init_portfolio(root=root, seat_id="seat.exclusive", portfolio_ref="portfolio.exclusive")
    _fixture_freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(tmp_path / "freeze.json", open_at=OPEN_1, period=1),
    )
    settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "outcome.json", open_at=OPEN_1, period=1, number=1),
    )
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="SEALED_ONCE",
    )
    assert (period_directory(root, 1) / FEEDBACK_NAME).is_file()
    with pytest.raises(StoreError, match="requires a settled head without feedback"):
        feedback_portfolio_period(
            root=root,
            kind=FeedbackKind.NO_CHANGE_WITH_REASON,
            reason_code="REWRITE",
        )
    with pytest.raises(StoreError, match="empty root"):
        init_portfolio(root=root, seat_id="seat.second", portfolio_ref="portfolio.second")


def test_flat_verbs_cannot_poison_portfolio_or_period_root(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-layout"
    init_portfolio(root=root, seat_id="seat.layout", portfolio_ref="portfolio.layout")
    request = _ticket_action_request(tmp_path / "layout.json", open_at=OPEN_1, period=1)
    with pytest.raises(StoreError, match="legacy flat verb"):
        inspect_episode(root=root)
    with pytest.raises(StoreError, match="legacy flat verb"):
        freeze_episode(root=root, request_path=request)
    assert not (root / "frozen_episode.v1.json").exists()

    period_root, period_index, prior = prepare_next_period_root(root)
    assert period_index == 1 and prior is None
    with pytest.raises(StoreError, match="legacy flat verb"):
        freeze_episode(root=period_root, request_path=request)
    assert not (period_root / "frozen_episode.v1.json").exists()


def test_flat_init_cannot_poison_portfolio_or_period_root(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-init-layout"
    init_portfolio(root=root, seat_id="seat.init-layout", portfolio_ref="portfolio.init-layout")

    with pytest.raises(StoreError, match="legacy flat verb"):
        init_episode(
            root=root,
            seat_id="seat.foreign-root",
            portfolio_ref="portfolio.foreign-root",
        )

    period_root, period_index, prior = prepare_next_period_root(root)
    assert period_index == 1 and prior is None
    before = {path.name: path.read_bytes() for path in period_root.iterdir() if path.is_file()}
    with pytest.raises(StoreError, match="legacy flat verb"):
        init_episode(
            root=period_root,
            seat_id="seat.foreign-period",
            portfolio_ref="portfolio.foreign-period",
        )
    after = {path.name: path.read_bytes() for path in period_root.iterdir() if path.is_file()}
    assert after == before


def test_internal_continuity_freeze_rejects_legacy_accounting_before_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "portfolio-accounting-layout"
    init_portfolio(
        root=root,
        seat_id="seat.accounting-layout",
        portfolio_ref="portfolio.accounting-layout",
    )
    period_root, period_index, prior = prepare_next_period_root(root)
    assert period_index == 1 and prior is None

    with pytest.raises(StoreError, match="CARRIED_BALANCE_SNAPSHOT"):
        freeze_episode(
            root=period_root,
            request_path=_ticket_action_request(
                tmp_path / "legacy-accounting.json", open_at=OPEN_1, period=1
            ),
            _continuity_internal=True,
        )
    assert not (period_root / "frozen_episode.v1.json").exists()


def test_account_ticket_wrong_panel_baseline_fails_before_freeze(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-baseline"
    init_portfolio(root=root, seat_id="seat.baseline", portfolio_ref="portfolio.baseline")
    request = _ticket_action_request(tmp_path / "baseline.json", open_at=OPEN_1, period=1)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["bound_account_ticket"]["baseline_ref"] = "BO0001"
    _write_json(request, payload)
    with pytest.raises(ValueError, match="ACCOUNT_TICKET_BASELINE_INVALID"):
        _fixture_freeze_portfolio_period(root=root, request_path=request)
    assert not (period_directory(root, 1) / "frozen_episode.v1.json").exists()


def test_pure_period_three_rejects_period_one_as_direct_predecessor(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-prior-generation"
    init_portfolio(root=root, seat_id="seat.prior", portfolio_ref="portfolio.prior")
    _fixture_freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(
            tmp_path / "prior-freeze.json", open_at=OPEN_1, period=1
        ),
    )
    settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "prior-outcome.json", open_at=OPEN_1, period=1, number=1),
    )
    settled_1 = load_settled(period_directory(root, 1))
    cutoff, frozen_at, deadline = _times(OPEN_2 + timedelta(days=1))
    science = build_science_decision(
        science_decision_ref="science.period3",
        identity=ScienceDecisionIdentity.POLICY_NO_ACTION,
        knowledge_cutoff=cutoff,
        rationale_ref="wrong-generation-negative",
    )
    account = build_account_no_action(
        account_decision_ref="account.period3.no-action",
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.special-number.20260731.v1",
    )
    with pytest.raises(ValueError, match="HISTORY_GAP"):
        freeze_shadow_episode(
            episode_ref="episode.period3.invalid-prior",
            seat=load_seat(root),
            science_decision=science,
            account_decision=account,
            target_ref="draw.20260803-001",
            target_open_time=OPEN_2 + timedelta(days=1),
            freeze_deadline=deadline,
            frozen_at=frozen_at,
            period_index=3,
            prior_settled=settled_1,
            accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
        )
