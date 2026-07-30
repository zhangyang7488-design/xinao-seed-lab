"""Fraud and continuity oracles for same-seat multi-period shadow portfolio.

Tests exercise public consumer/lifecycle/store APIs against the portfolio
continuity implementation. Prefer exclusive-write failures and typed errors over
private-field surgery. Synthetic fixtures only; never claims real-money authority.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.shadow_lifecycle import (
    AccountingBasis,
    FeedbackKind,
    ScienceDecisionIdentity,
    build_account_action_from_ticket,
    build_account_no_action,
    build_science_decision,
    create_seat,
    feedback_portfolio_period,
    freeze_episode,
    freeze_portfolio_period,
    freeze_shadow_episode,
    init_portfolio,
    inspect_episode,
    inspect_portfolio,
    replay_portfolio_period,
    seal_account_feedback,
    settle_portfolio_period,
)
from xinao.shadow_lifecycle.lifecycle import AccountRiskTicket, SettledShadowEpisode
from xinao.shadow_lifecycle.store import (
    FEEDBACK_NAME,
    FROZEN_NAME,
    OUTCOME_NAME,
    SETTLED_NAME,
    StoreError,
    derive_portfolio_head,
    load_frozen,
    load_outcome,
    load_seat,
    load_settled,
    period_directory,
    prepare_next_period_root,
    write_feedback_exclusive,
    write_new_json,
)

OPEN_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
OPEN_2 = OPEN_1 + timedelta(days=1)
OPEN_3 = OPEN_1 + timedelta(days=2)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _ticket_action_request(
    path: Path,
    *,
    open_at: datetime,
    period: int,
    number: int = 1,
    panel: str = "B",
    baseline_ref: str | None = None,
    stake: str = "1.0000",
) -> Path:
    cutoff, frozen_at, deadline = _times(open_at)
    target_ref = f"draw.2026080{period}-001"
    body = {
        "episode_ref": f"episode.fraud.p{period}",
        "science_decision": {
            "science_decision_ref": f"science.policy.p{period}",
            "identity": "POLICY_NO_ACTION",
            "knowledge_cutoff": cutoff.isoformat(),
            "rationale_ref": "science-not-account-gate",
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
            "panel": panel,
            "selected_number": number,
            "stake": stake,
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.special-number.20260731.v1",
            "baseline_ref": baseline_ref
            if baseline_ref is not None
            else ("BO0013" if panel == "B" else "BO0001"),
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
            "episode_ref": f"episode.fraud.p{period}",
            "science_decision": {
                "science_decision_ref": f"science.candidate.p{period}",
                "identity": "SCIENCE_CANDIDATE",
                "candidate_ref": "candidate.wild-overfit-is-still-testable",
                "knowledge_cutoff": cutoff.isoformat(),
                "rationale_ref": "account-no-action-does-not-green-science",
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
            "outcome_ref": f"outcome.fraud.p{period}",
            "source_ref": "synthetic-test-fixture-only",
            "target_ref": f"draw.2026080{period}-001",
            "actual_special_number": number,
            "observed_at": (open_at + timedelta(hours=1)).isoformat(),
            "verified": True,
        },
    )


def _init(root: Path, *, suffix: str = "alpha") -> dict[str, Any]:
    return init_portfolio(
        root=root,
        seat_id=f"seat.fraud.{suffix}",
        portfolio_ref=f"portfolio.fraud.{suffix}",
    )


def _p1_action_hit_and_feedback(tmp_path: Path, root: Path) -> dict[str, Any]:
    frozen = freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(tmp_path / "p1.json", open_at=OPEN_1, period=1),
    )
    settled = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "p1-out.json", open_at=OPEN_1, period=1, number=1),
    )
    feedback = feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="CONTINUE",
    )
    return {"frozen": frozen, "settled": settled, "feedback": feedback}


def test_positive_two_period_ticket_hit_then_no_action_replay(tmp_path: Path) -> None:
    """P1 ticket ACTION panel B #1 stake 1 hit → pnl 41.3850 / close 10041.3850;
    P2 explicit account NO_ACTION → NO_EXPOSURE, unchanged close; replay both.
    """
    root = tmp_path / "portfolio-positive"
    initialized = _init(root, suffix="positive")
    assert initialized["opening_balance"] == "10000.0000"
    genesis_seat = load_seat(root)

    freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(
            tmp_path / "pos-p1.json", open_at=OPEN_1, period=1, number=1, panel="B"
        ),
    )
    settled_1 = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "pos-p1-out.json", open_at=OPEN_1, period=1, number=1),
    )
    assert settled_1["statement_result"] == "HIT"
    assert settled_1["pnl"] == "41.3850"
    assert settled_1["closing_balance"] == "10041.3850"
    assert settled_1["scientific_promotion"] is False
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="CONTINUE_TO_NEXT_PROSPECTIVE_PERIOD",
    )

    freeze_portfolio_period(
        root=root,
        request_path=_no_action_request(tmp_path / "pos-p2.json", open_at=OPEN_2, period=2),
    )
    episode_2 = load_frozen(period_directory(root, 2))
    assert episode_2.pre_freeze_balance == "10041.3850"
    assert episode_2.prior_close_binding is not None
    assert episode_2.prior_close_binding.prior_closing_balance == "10041.3850"
    assert episode_2.opening_journal_group is None
    assert episode_2.accounting_basis == AccountingBasis.CARRIED_BALANCE_SNAPSHOT

    settled_2 = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "pos-p2-out.json", open_at=OPEN_2, period=2, number=49),
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
    assert final["completion_claim_allowed"] is False
    assert load_seat(root) == genesis_seat


def test_outcome_unavailable_and_peek_before_freeze_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-peek"
    _init(root, suffix="peek")

    with pytest.raises(StoreError, match=r"FROZEN|portfolio-settle"):
        settle_portfolio_period(
            root=root,
            outcome_path=_outcome(tmp_path / "early-out.json", open_at=OPEN_1, period=1, number=1),
        )

    request = _ticket_action_request(tmp_path / "peek-req.json", open_at=OPEN_1, period=1)
    body = json.loads(request.read_text(encoding="utf-8"))
    body["outcome"] = {"actual_special_number": 1}
    body["actual_special_number"] = 1
    _write_json(request, body)
    with pytest.raises(StoreError, match="no-peek"):
        freeze_portfolio_period(root=root, request_path=request)
    assert not (period_directory(root, 1) / FROZEN_NAME).exists()


def test_wrong_prior_close_balance_and_stale_hash_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-prior"
    _init(root, suffix="prior")
    _p1_action_hit_and_feedback(tmp_path, root)
    prior = load_settled(period_directory(root, 1))
    seat = load_seat(root)
    cutoff, frozen_at, deadline = _times(OPEN_2)
    science = build_science_decision(
        science_decision_ref="science.wrong-prior",
        identity=ScienceDecisionIdentity.POLICY_NO_ACTION,
        knowledge_cutoff=cutoff,
        rationale_ref="wrong-prior",
    )
    account = build_account_no_action(
        account_decision_ref="account.wrong-prior",
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.special-number.20260731.v1",
    )

    with pytest.raises(ValueError, match="PRIOR_CLOSE_MISMATCH"):
        freeze_shadow_episode(
            episode_ref="episode.wrong-balance",
            seat=seat,
            science_decision=science,
            account_decision=account,
            target_ref="draw.20260802-001",
            target_open_time=OPEN_2,
            freeze_deadline=deadline,
            frozen_at=frozen_at,
            period_index=2,
            prior_settled=prior,
            pre_freeze_balance="99999.0000",
            accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
        )

    stale = SettledShadowEpisode.model_construct(
        **{
            **{name: getattr(prior, name) for name in type(prior).model_fields},
            "content_hash": "f" * 64,
        }
    )
    with pytest.raises(ValueError, match=r"mutated sealed|content seal|hash"):
        freeze_shadow_episode(
            episode_ref="episode.stale-hash",
            seat=seat,
            science_decision=science,
            account_decision=account,
            target_ref="draw.20260802-001",
            target_open_time=OPEN_2,
            freeze_deadline=deadline,
            frozen_at=frozen_at,
            period_index=2,
            prior_settled=stale,
            accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
        )


def test_skipped_and_hollow_period_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-gap"
    _init(root, suffix="gap")
    _p1_action_hit_and_feedback(tmp_path, root)

    hollow = period_directory(root, 2)
    hollow.mkdir(parents=True, exist_ok=True)
    (hollow / "not_an_allowed_artifact.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StoreError, match=r"FOREIGN_PERIOD|HISTORY_GAP|FOREIGN"):
        inspect_portfolio(root=root)

    for child in hollow.iterdir():
        child.unlink()
    hollow.rmdir()
    skipped = period_directory(root, 3)
    skipped.mkdir(parents=True, exist_ok=True)
    write_new_json(skipped / "seat.v1.json", load_seat(root).model_dump(mode="json"))
    with pytest.raises(StoreError, match=r"HISTORY_GAP"):
        derive_portfolio_head(root)


def test_concurrent_double_freeze_exactly_one_wins(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-race-freeze"
    _init(root, suffix="race-freeze")
    request_a = _ticket_action_request(tmp_path / "race-a.json", open_at=OPEN_1, period=1)
    request_b = _ticket_action_request(tmp_path / "race-b.json", open_at=OPEN_1, period=1)
    body_b = json.loads(request_b.read_text(encoding="utf-8"))
    body_b["episode_ref"] = "episode.fraud.p1.alt"
    body_b["bound_account_ticket"]["ticket_ref"] = "account-ticket.p1.alt"
    body_b["account_decision"]["account_decision_ref"] = "account.action.p1.alt"
    _write_json(request_b, body_b)

    barrier = threading.Barrier(2)
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(path: Path) -> None:
        barrier.wait(timeout=5)
        try:
            result = freeze_portfolio_period(root=root, request_path=path)
            with lock:
                results.append(result)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(request_a,)),
        threading.Thread(target=worker, args=(request_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) + len(errors) == 2
    assert len(results) == 1, (
        f"expected exactly one freeze win, got {len(results)} wins / {len(errors)} errors: "
        f"{results!r} {[type(e).__name__ + ':' + str(e) for e in errors]!r}"
    )
    assert results[0]["ok"] is True
    assert results[0]["phase"] == "FROZEN"
    assert results[0]["period_index"] == 1
    assert any(isinstance(exc, (StoreError, ValueError)) for exc in errors)
    assert (period_directory(root, 1) / FROZEN_NAME).is_file()
    assert not period_directory(root, 2).exists() or not (
        period_directory(root, 2) / FROZEN_NAME
    ).exists()


def test_double_settle_portfolio_period_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-double-settle"
    _init(root, suffix="double-settle")
    freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(tmp_path / "ds-req.json", open_at=OPEN_1, period=1),
    )
    first = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "ds-out1.json", open_at=OPEN_1, period=1, number=1),
    )
    assert first["statement_result"] == "HIT"
    # Portfolio head is SETTLED: consumer rejects before a second exclusive settle write.
    with pytest.raises(
        StoreError,
        match=(
            r"portfolio-settle requires a FROZEN|exclusive create rejected|"
            r"already exists|SETTLED"
        ),
    ):
        settle_portfolio_period(
            root=root,
            outcome_path=_outcome(tmp_path / "ds-out2.json", open_at=OPEN_1, period=1, number=2),
        )
    assert (period_directory(root, 1) / SETTLED_NAME).is_file()
    sealed_settled = (period_directory(root, 1) / SETTLED_NAME).read_bytes()
    sealed_outcome = (period_directory(root, 1) / OUTCOME_NAME).read_bytes()
    # Period-root exclusive path also refuses a second settle (once-only journal).
    from xinao.shadow_lifecycle import settle_episode

    with pytest.raises(
        StoreError,
        match=r"exclusive create rejected|already exists|SETTLED|settle requires",
    ):
        settle_episode(
            root=period_directory(root, 1),
            outcome_path=_outcome(tmp_path / "ds-out3.json", open_at=OPEN_1, period=1, number=7),
            _continuity_internal=True,
        )
    assert (period_directory(root, 1) / SETTLED_NAME).read_bytes() == sealed_settled
    assert (period_directory(root, 1) / OUTCOME_NAME).read_bytes() == sealed_outcome


def test_feedback_bind_mismatch_and_rewrite_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-feedback"
    _init(root, suffix="feedback")
    freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(tmp_path / "fb-req.json", open_at=OPEN_1, period=1),
    )
    settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "fb-out.json", open_at=OPEN_1, period=1, number=1),
    )
    period_root = period_directory(root, 1)
    settled = load_settled(period_root)
    outcome = load_outcome(period_root)

    with pytest.raises(ValueError, match=r"period_index|feedback period"):
        seal_account_feedback(
            feedback_ref="feedback.bad-period",
            kind=FeedbackKind.NO_CHANGE_WITH_REASON,
            period_index=2,
            settled=settled,
            outcome=outcome,
            reason_code="BAD",
        )

    with pytest.raises(ValueError, match="reason_code"):
        seal_account_feedback(
            feedback_ref="feedback.no-reason",
            kind=FeedbackKind.NO_CHANGE_WITH_REASON,
            period_index=1,
            settled=settled,
            outcome=outcome,
            reason_code=None,
        )

    good = feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.TYPED_FEEDBACK,
        feedback_ref="feedback.once",
        notes="sealed once",
    )
    assert good["scientific_promotion"] is False
    assert (period_root / FEEDBACK_NAME).is_file()

    with pytest.raises(StoreError, match=r"settled head without feedback|already exists"):
        feedback_portfolio_period(
            root=root,
            kind=FeedbackKind.NO_CHANGE_WITH_REASON,
            feedback_ref="feedback.rewrite",
            reason_code="REWRITE",
        )

    mismatched = seal_account_feedback(
        feedback_ref="feedback.mismatch-bind",
        kind=FeedbackKind.TYPED_FEEDBACK,
        period_index=1,
        settled=settled,
        outcome=outcome,
        notes="should not write over",
    )
    bad = type(mismatched).model_construct(
        **{
            **{name: getattr(mismatched, name) for name in type(mismatched).model_fields},
            "account_pnl_echo": "0.0000",
            "content_hash": None,
        }
    )
    bad = bad.model_copy(update={"content_hash": bad.compute_content_hash()})
    with pytest.raises(StoreError, match=r"FEEDBACK_BIND_MISMATCH|already exists"):
        write_feedback_exclusive(period_root, bad)


def test_foreign_root_and_period_artifact_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-foreign"
    _init(root, suffix="foreign")
    freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(tmp_path / "fr-req.json", open_at=OPEN_1, period=1),
    )
    settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "fr-out.json", open_at=OPEN_1, period=1, number=1),
    )
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="OK",
    )

    foreign_file = period_directory(root, 1) / "evil_payload.bin"
    foreign_file.write_bytes(b"not-allowed")
    with pytest.raises(StoreError, match="FOREIGN_PERIOD_ARTIFACT"):
        inspect_portfolio(root=root)
    foreign_file.unlink()

    period_root, period_index, _prior = prepare_next_period_root(root)
    assert period_index == 2
    foreign_seat = create_seat(
        seat_id="seat.intruder",
        portfolio_ref="portfolio.intruder",
        opening_balance="10000.0000",
    ).model_dump(mode="json")
    seat_path = period_root / "seat.v1.json"
    seat_path.unlink()
    write_new_json(seat_path, foreign_seat)
    with pytest.raises(StoreError, match=r"FOREIGN_PORTFOLIO|period seat"):
        freeze_portfolio_period(
            root=root,
            request_path=_no_action_request(tmp_path / "fr-p2.json", open_at=OPEN_2, period=2),
        )


def test_second_genesis_and_top_up_rejected(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-genesis"
    first = _init(root, suffix="genesis")
    assert first["opening_balance"] == "10000.0000"

    with pytest.raises(StoreError, match="empty root"):
        init_portfolio(
            root=root,
            seat_id="seat.fraud.genesis2",
            portfolio_ref="portfolio.fraud.genesis2",
        )

    with pytest.raises(StoreError, match="empty root"):
        init_portfolio(
            root=root,
            seat_id="seat.fraud.genesis",
            portfolio_ref="portfolio.fraud.genesis",
            opening_balance="50000.0000",
        )

    with pytest.raises(ValueError, match="opening_balance must be positive"):
        create_seat(
            seat_id="seat.zero",
            portfolio_ref="portfolio.zero",
            opening_balance="0.0000",
        )
    with pytest.raises(ValueError, match="opening_balance must be positive"):
        init_portfolio(
            root=tmp_path / "portfolio-zero-open",
            seat_id="seat.zero2",
            portfolio_ref="portfolio.zero2",
            opening_balance="0.0000",
        )


def test_pure_api_period_three_cannot_bind_period_one(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-gen-skip"
    _init(root, suffix="gen-skip")
    _p1_action_hit_and_feedback(tmp_path, root)
    settled_1 = load_settled(period_directory(root, 1))
    seat = load_seat(root)
    cutoff, frozen_at, deadline = _times(OPEN_3)
    science = build_science_decision(
        science_decision_ref="science.p3",
        identity=ScienceDecisionIdentity.POLICY_NO_ACTION,
        knowledge_cutoff=cutoff,
        rationale_ref="gap",
    )
    account = build_account_no_action(
        account_decision_ref="account.p3",
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.special-number.20260731.v1",
    )
    with pytest.raises(ValueError, match="HISTORY_GAP"):
        freeze_shadow_episode(
            episode_ref="episode.p3.invalid",
            seat=seat,
            science_decision=science,
            account_decision=account,
            target_ref="draw.20260803-001",
            target_open_time=OPEN_3,
            freeze_deadline=deadline,
            frozen_at=frozen_at,
            period_index=3,
            prior_settled=settled_1,
            accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
        )


def test_wrong_panel_baseline_rejected_before_freeze(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-baseline"
    _init(root, suffix="baseline")
    request = _ticket_action_request(
        tmp_path / "bad-base.json",
        open_at=OPEN_1,
        period=1,
        panel="B",
        baseline_ref="BO0001",
    )
    with pytest.raises(ValueError, match="ACCOUNT_TICKET_BASELINE_INVALID"):
        freeze_portfolio_period(root=root, request_path=request)
    assert not (period_directory(root, 1) / FROZEN_NAME).exists()
    cutoff, frozen_at, deadline = _times(OPEN_1)
    with pytest.raises(ValueError, match="ACCOUNT_TICKET_BASELINE_INVALID"):
        AccountRiskTicket(
            ticket_ref="t.bad",
            target_ref="draw.20260801-001",
            target_open_time=OPEN_1,
            freeze_deadline=deadline,
            knowledge_cutoff=cutoff,
            frozen_at=frozen_at,
            panel="B",
            selected_number=1,
            stake="1.0000",
            rule_ref="special-number-rule.v1",
            odds_version_ref="odds.special-number.20260731.v1",
            baseline_ref="BO0001",
            risk_policy_ref="shadow-risk.max-one-unit.v1",
            information_set_ref="info.v1",
            information_set_hash="a" * 64,
        )


def test_flat_legacy_verbs_cannot_poison_portfolio_or_period_roots(tmp_path: Path) -> None:
    root = tmp_path / "portfolio-legacy-verb"
    _init(root, suffix="legacy-verb")
    request = _ticket_action_request(tmp_path / "lv.json", open_at=OPEN_1, period=1)

    with pytest.raises(StoreError, match="legacy flat verb"):
        inspect_episode(root=root)
    with pytest.raises(StoreError, match="legacy flat verb"):
        freeze_episode(root=root, request_path=request)
    assert not (root / FROZEN_NAME).exists()

    period_root, period_index, prior = prepare_next_period_root(root)
    assert period_index == 1 and prior is None
    with pytest.raises(StoreError, match="legacy flat verb"):
        freeze_episode(root=period_root, request_path=request)
    assert not (period_root / FROZEN_NAME).exists()


def test_legacy_canonical_hash_omits_null_additive_fields(tmp_path: Path) -> None:
    """0.2.0 hash projection must not be polluted by additive null 0.3.0 fields."""
    root = tmp_path / "portfolio-hash"
    _init(root, suffix="hash")
    freeze_portfolio_period(
        root=root,
        request_path=_no_action_request(tmp_path / "hash-p1.json", open_at=OPEN_1, period=1),
    )
    episode = load_frozen(period_directory(root, 1))
    canonical = episode.canonical_content()
    assert canonical.get("accounting_basis") == AccountingBasis.CARRIED_BALANCE_SNAPSHOT.value
    assert "prior_close_binding" not in canonical
    assert "bound_account_ticket" not in canonical
    account = canonical["account_decision"]
    assert "account_ticket_ref" not in account
    assert "account_ticket_hash" not in account
    assert "period_index" not in canonical
    assert episode.content_hash == episode.compute_content_hash()


def test_zero_opening_zero_balance_and_double_opening_post_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="opening_balance must be positive"):
        create_seat(
            seat_id="seat.neg",
            portfolio_ref="portfolio.neg",
            opening_balance="-1.0000",
        )

    root = tmp_path / "portfolio-carry"
    init_portfolio(
        root=root,
        seat_id="seat.fraud.carry",
        portfolio_ref="portfolio.fraud.carry",
        opening_balance="1.0000",
    )
    freeze_portfolio_period(
        root=root,
        request_path=_ticket_action_request(
            tmp_path / "carry-p1.json",
            open_at=OPEN_1,
            period=1,
            number=1,
            stake="1.0000",
        ),
    )
    settled_miss = settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "carry-miss.json", open_at=OPEN_1, period=1, number=49),
    )
    assert settled_miss["statement_result"] == "MISS"
    assert settled_miss["closing_balance"] == "0.0000"
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="ZERO_CARRY",
    )

    freeze_portfolio_period(
        root=root,
        request_path=_no_action_request(tmp_path / "carry-p2.json", open_at=OPEN_2, period=2),
    )
    episode_2 = load_frozen(period_directory(root, 2))
    assert episode_2.pre_freeze_balance == "0.0000"
    assert episode_2.opening_journal_group is None
    assert episode_2.position_journal_group is None

    settle_portfolio_period(
        root=root,
        outcome_path=_outcome(tmp_path / "carry-p2-out.json", open_at=OPEN_2, period=2, number=7),
    )
    feedback_portfolio_period(
        root=root,
        kind=FeedbackKind.TYPED_FEEDBACK,
        notes="still zero",
    )
    prior_zero = load_settled(period_directory(root, 2))
    seat = load_seat(root)
    cutoff, frozen_at, deadline = _times(OPEN_3)
    science = build_science_decision(
        science_decision_ref="science.zero-action",
        identity=ScienceDecisionIdentity.POLICY_NO_ACTION,
        knowledge_cutoff=cutoff,
        rationale_ref="zero-stake-fail",
    )
    ticket = AccountRiskTicket(
        ticket_ref="ticket.zero-action",
        target_ref="draw.20260803-001",
        target_open_time=OPEN_3,
        freeze_deadline=deadline,
        knowledge_cutoff=cutoff,
        frozen_at=frozen_at,
        panel="B",
        selected_number=1,
        stake="1.0000",
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.special-number.20260731.v1",
        baseline_ref="BO0013",
        risk_policy_ref="shadow-risk.max-one-unit.v1",
        information_set_ref="info.zero",
        information_set_hash="b" * 64,
    ).with_content_hash()
    account = build_account_action_from_ticket(
        account_decision_ref="account.zero-action",
        account_ticket=ticket,
    )
    with pytest.raises(ValueError, match=r"stake exceeds pre-freeze balance"):
        freeze_shadow_episode(
            episode_ref="episode.zero-action",
            seat=seat,
            science_decision=science,
            account_decision=account,
            target_ref=ticket.target_ref,
            target_open_time=OPEN_3,
            freeze_deadline=deadline,
            frozen_at=frozen_at,
            period_index=3,
            prior_settled=prior_zero,
            accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
            bound_account_ticket=ticket,
            position_journal_group_ref="journal.pos.zero",
        )

    # NO_ACTION cannot smuggle journals either (double-post / hollow journals).
    no_action = build_account_no_action(
        account_decision_ref="account.zero-no-action-journals",
        rule_ref="special-number-rule.v1",
        odds_version_ref="odds.special-number.20260731.v1",
    )
    with pytest.raises(ValueError, match=r"creates no position journals|OPENING|journal"):
        freeze_shadow_episode(
            episode_ref="episode.zero-no-action-journals",
            seat=seat,
            science_decision=science,
            account_decision=no_action,
            target_ref="draw.20260803-001",
            target_open_time=OPEN_3,
            freeze_deadline=deadline,
            frozen_at=frozen_at,
            period_index=3,
            prior_settled=prior_zero,
            accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
            opening_journal_group_ref="journal.opening.illegal",
            position_journal_group_ref="journal.pos.illegal",
        )


def test_carried_period_rejects_second_opening_via_consumer_request(tmp_path: Path) -> None:
    """Consumer path: period 2 ACTION must not accept opening_journal_group_ref."""
    root = tmp_path / "portfolio-double-post"
    _init(root, suffix="double-post")
    _p1_action_hit_and_feedback(tmp_path, root)
    request = _ticket_action_request(tmp_path / "p2-open.json", open_at=OPEN_2, period=2)
    body = json.loads(request.read_text(encoding="utf-8"))
    body["opening_journal_group_ref"] = "journal.opening.p2.illegal"
    _write_json(request, body)
    with pytest.raises(ValueError, match=r"OPENING journal|opening_journal"):
        freeze_portfolio_period(root=root, request_path=request)
    assert not (period_directory(root, 2) / FROZEN_NAME).exists()
