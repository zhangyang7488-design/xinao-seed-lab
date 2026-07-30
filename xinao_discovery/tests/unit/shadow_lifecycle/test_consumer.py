"""Focused positive/negative coverage for the file-backed shadow lifecycle consumer."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.decision import DecisionGateInput, compile_decision_plan, freeze_decision
from xinao.shadow_lifecycle import store as store_mod
from xinao.shadow_lifecycle.consumer import (
    CONSUMER_ID,
    freeze_episode,
    init_episode,
    inspect_episode,
    replay_episode,
    settle_episode,
)
from xinao.shadow_lifecycle.consumer import (
    main as consumer_main,
)
from xinao.shadow_lifecycle.store import (
    OUTCOME_NAME,
    SETTLED_NAME,
    SETTLEMENT_INTENT_NAME,
    EpisodePhase,
    StoreError,
    detect_phase,
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


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _action_request(path: Path, *, frozen: Any | None = None) -> Path:
    bound = frozen if frozen is not None else _frozen_shadow()
    body = {
        "episode_ref": "episode.consumer.action.v1",
        "science_decision": {
            "science_decision_ref": "science.candidate.v1",
            "identity": "SCIENCE_CANDIDATE",
            "knowledge_cutoff": CUTOFF.isoformat().replace("+00:00", "Z"),
            "rationale_ref": "rationale.science.v1",
            "candidate_ref": "candidate.signal.v1",
        },
        "account_decision": {
            "account_decision_ref": "acct.action.v1",
            "identity": "ACTION",
        },
        "bound_frozen_decision": bound.model_dump(mode="json"),
        "target_ref": bound.target_ref,
        "target_open_time": bound.target_open_time.isoformat().replace("+00:00", "Z"),
        "freeze_deadline": bound.freeze_deadline.isoformat().replace("+00:00", "Z"),
        "frozen_at": FREEZE_AT.isoformat().replace("+00:00", "Z"),
        "opening_journal_group_ref": "journal.opening.consumer.action.v1",
        "position_journal_group_ref": "journal.position.consumer.action.v1",
    }
    return _write_json(path, body)


def _no_action_request(path: Path) -> Path:
    body = {
        "episode_ref": "episode.consumer.no-action.v1",
        "science_decision": {
            "science_decision_ref": "science.candidate.v1",
            "identity": "SCIENCE_CANDIDATE",
            "knowledge_cutoff": CUTOFF.isoformat().replace("+00:00", "Z"),
            "rationale_ref": "rationale.science.v1",
            "candidate_ref": "candidate.signal.v1",
        },
        "account_decision": {
            "account_decision_ref": "acct.no-action.v1",
            "identity": "RESEARCHER_ACCOUNT_NO_ACTION",
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.signal.v1",
        },
        "target_ref": "draw.20260720-001",
        "target_open_time": OPEN.isoformat().replace("+00:00", "Z"),
        "freeze_deadline": DEADLINE.isoformat().replace("+00:00", "Z"),
        "frozen_at": FREEZE_AT.isoformat().replace("+00:00", "Z"),
    }
    return _write_json(path, body)


def _outcome_payload(
    path: Path,
    *,
    special_number: int = 1,
    target_ref: str = "draw.20260720-001",
    observed_at: datetime | None = None,
) -> Path:
    observed = observed_at if observed_at is not None else OPEN + timedelta(hours=1)
    body = {
        "outcome_ref": "outcome.consumer.1",
        "source_ref": "macaujc2",
        "target_ref": target_ref,
        "actual_special_number": special_number,
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "verified": True,
    }
    return _write_json(path, body)


def test_positive_action_closed_loop_via_file_store(tmp_path: Path) -> None:
    root = tmp_path / "episode-action"
    init = init_episode(
        root=root,
        seat_id="seat.consumer.alpha",
        portfolio_ref="portfolio.consumer.alpha",
    )
    assert init["ok"] is True
    assert init["phase"] == EpisodePhase.INIT.value
    assert init["completion_claim_allowed"] is False
    assert detect_phase(root) == EpisodePhase.INIT

    freeze = freeze_episode(
        root=root, request_path=_action_request(tmp_path / "freeze_request.json")
    )
    assert freeze["ok"] is True
    assert freeze["phase"] == EpisodePhase.FROZEN.value
    assert freeze["account_identity"] == "ACTION"
    assert freeze["frozen_episode_hash"]

    status = inspect_episode(root=root)
    assert status["phase"] == EpisodePhase.FROZEN.value
    assert status["outcome_present"] is False
    assert status["next_action"] == "settle"

    settled = settle_episode(
        root=root,
        outcome_path=_outcome_payload(tmp_path / "outcome.json", special_number=1),
    )
    assert settled["ok"] is True
    assert settled["phase"] == EpisodePhase.SETTLED.value
    assert settled["statement_result"] == "HIT"
    assert settled["first_episode_verified"] is False
    assert settled["completion_claim_allowed"] is False

    replayed = replay_episode(root=root)
    assert replayed["ok"] is True
    assert replayed["replay_match"] is True
    assert replayed["settled_episode_hash"] == settled["settled_episode_hash"]
    assert replayed["first_episode_verified"] is False

    final = inspect_episode(root=root)
    assert final["phase"] == EpisodePhase.SETTLED.value
    assert final["outcome_present"] is True
    assert final["pnl"] == settled["pnl"]


def test_positive_no_action_freeze_and_zero_risk_settle(tmp_path: Path) -> None:
    root = tmp_path / "episode-no-action"
    init_episode(
        root=root,
        seat_id="seat.consumer.beta",
        portfolio_ref="portfolio.consumer.beta",
    )
    freeze = freeze_episode(
        root=root, request_path=_no_action_request(tmp_path / "no_action_request.json")
    )
    assert freeze["account_identity"] == "RESEARCHER_ACCOUNT_NO_ACTION"
    settled = settle_episode(
        root=root,
        outcome_path=_outcome_payload(tmp_path / "outcome_na.json", special_number=7),
    )
    assert settled["statement_result"] == "NO_EXPOSURE"
    assert settled["pnl"] == "0.0000"
    assert settled["closing_balance"] == "10000.0000"
    assert replay_episode(root=root)["replay_match"] is True


def test_negative_double_settle_rejected(tmp_path: Path) -> None:
    root = tmp_path / "episode-double"
    init_episode(root=root, seat_id="seat.consumer.d1", portfolio_ref="portfolio.consumer.d1")
    freeze_episode(root=root, request_path=_action_request(tmp_path / "req1.json"))
    settle_episode(root=root, outcome_path=_outcome_payload(tmp_path / "out1.json"))
    with pytest.raises(StoreError, match=r"exclusive create rejected|SETTLED|already exists"):
        settle_episode(
            root=root,
            outcome_path=_outcome_payload(tmp_path / "out2.json", special_number=2),
        )


def test_negative_freeze_rejects_outcome_peek(tmp_path: Path) -> None:
    root = tmp_path / "episode-peek"
    init_episode(root=root, seat_id="seat.consumer.p1", portfolio_ref="portfolio.consumer.p1")
    request = _action_request(tmp_path / "peek_req.json")
    body = json.loads(request.read_text(encoding="utf-8"))
    body["outcome"] = {"actual_special_number": 1}
    request.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(StoreError, match="no-peek"):
        freeze_episode(root=root, request_path=request)


def test_negative_double_freeze_rejected(tmp_path: Path) -> None:
    root = tmp_path / "episode-double-freeze"
    init_episode(root=root, seat_id="seat.consumer.f1", portfolio_ref="portfolio.consumer.f1")
    freeze_episode(root=root, request_path=_action_request(tmp_path / "req_a.json"))
    with pytest.raises(StoreError, match=r"INIT|exclusive create rejected|already exists"):
        freeze_episode(root=root, request_path=_action_request(tmp_path / "req_b.json"))


def test_negative_late_freeze_rejected(tmp_path: Path) -> None:
    root = tmp_path / "episode-late"
    init_episode(root=root, seat_id="seat.consumer.late", portfolio_ref="portfolio.consumer.late")
    request = _action_request(tmp_path / "late_req.json")
    body = json.loads(request.read_text(encoding="utf-8"))
    body["frozen_at"] = (DEADLINE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    request.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="late or backdated freeze"):
        freeze_episode(root=root, request_path=request)


def test_negative_pre_open_outcome_rejected(tmp_path: Path) -> None:
    root = tmp_path / "episode-preopen"
    init_episode(root=root, seat_id="seat.consumer.pre", portfolio_ref="portfolio.consumer.pre")
    freeze_episode(root=root, request_path=_action_request(tmp_path / "pre_req.json"))
    with pytest.raises(ValueError, match="pre-open"):
        settle_episode(
            root=root,
            outcome_path=_outcome_payload(
                tmp_path / "pre_out.json",
                observed_at=OPEN - timedelta(minutes=1),
            ),
        )


def test_crash_after_intent_before_outcome_leaves_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure after exclusive intent write (before outcome) must require exact-intent recovery."""
    root = tmp_path / "episode-crash-intent"
    init_episode(
        root=root,
        seat_id="seat.consumer.crash-intent",
        portfolio_ref="portfolio.consumer.crash-intent",
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "crash_intent_req.json"))
    outcome_path = _outcome_payload(tmp_path / "crash_intent_out.json", special_number=1)

    original = store_mod.write_new_json

    def crash_on_outcome(path: Path, payload: object) -> None:
        if path.name == OUTCOME_NAME:
            raise StoreError("injected crash after intent write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_on_outcome)
    with pytest.raises(StoreError, match="injected crash after intent write"):
        settle_episode(
            root=root,
            outcome_path=outcome_path,
            settlement_ref="settlement.intent-crash.v1",
            settlement_journal_group_ref="journal.settlement.intent-crash.v1",
            statement_ref="statement.intent-crash.v1",
            occurred_at=(OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )

    assert (root / SETTLEMENT_INTENT_NAME).is_file()
    assert not (root / OUTCOME_NAME).is_file()
    assert not (root / SETTLED_NAME).is_file()
    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED

    status = inspect_episode(root=root)
    assert status["phase"] == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED.value
    assert status["recovery_required"] is True
    assert status["outcome_present"] is False
    assert status["next_action"] == "settle"
    assert "pnl" not in status
    assert "settled_episode_hash" not in status
    assert "outcome_ref" not in status
    assert status["completion_claim_allowed"] is False

    with pytest.raises(StoreError, match=r"replay requires SETTLED"):
        replay_episode(root=root)


def test_crash_after_outcome_write_leaves_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure after exclusive outcome write must not look like clean FROZEN or SETTLED."""
    root = tmp_path / "episode-crash-outcome"
    init_episode(root=root, seat_id="seat.consumer.crash", portfolio_ref="portfolio.consumer.crash")
    freeze_episode(root=root, request_path=_action_request(tmp_path / "crash_req.json"))
    outcome_path = _outcome_payload(tmp_path / "crash_out.json", special_number=1)

    original = store_mod.write_new_json

    def crash_on_settled(path: Path, payload: object) -> None:
        if path.name == SETTLED_NAME:
            raise StoreError("injected crash after outcome write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_on_settled)
    with pytest.raises(StoreError, match="injected crash after outcome write"):
        settle_episode(root=root, outcome_path=outcome_path)

    assert (root / SETTLEMENT_INTENT_NAME).is_file()
    assert (root / OUTCOME_NAME).is_file()
    assert not (root / SETTLED_NAME).is_file()
    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED

    status = inspect_episode(root=root)
    assert status["phase"] == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED.value
    assert status["recovery_required"] is True
    assert status["outcome_present"] is True
    assert status["next_action"] == "settle"
    # Recovery does not claim settlement.
    assert "pnl" not in status
    assert "settled_episode_hash" not in status
    assert status["completion_claim_allowed"] is False

    with pytest.raises(StoreError, match=r"replay requires SETTLED"):
        replay_episode(root=root)


def test_exact_recovery_after_intent_only_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact full-intent settle retry may resume from intent-only to sealed SETTLED."""
    root = tmp_path / "episode-recover-intent-only"
    init_episode(
        root=root,
        seat_id="seat.consumer.recover-intent",
        portfolio_ref="portfolio.consumer.recover-intent",
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "recover_intent_req.json"))
    outcome_path = _outcome_payload(tmp_path / "recover_intent_out.json", special_number=1)
    settle_kwargs = {
        "root": root,
        "outcome_path": outcome_path,
        "settlement_ref": "settlement.recover-intent.v1",
        "settlement_journal_group_ref": "journal.settlement.recover-intent.v1",
        "statement_ref": "statement.recover-intent.v1",
        "occurred_at": (OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }

    original = store_mod.write_new_json
    fail_once = {"armed": True}

    def crash_outcome_once(path: Path, payload: object) -> None:
        if path.name == OUTCOME_NAME and fail_once["armed"]:
            fail_once["armed"] = False
            raise StoreError("injected crash after intent write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_outcome_once)
    with pytest.raises(StoreError, match="injected crash after intent write"):
        settle_episode(**settle_kwargs)
    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    assert not (root / OUTCOME_NAME).is_file()

    sealed_intent_bytes = (root / SETTLEMENT_INTENT_NAME).read_bytes()
    recovered = settle_episode(**settle_kwargs)
    assert recovered["ok"] is True
    assert recovered["phase"] == EpisodePhase.SETTLED.value
    assert recovered["statement_result"] == "HIT"
    assert detect_phase(root) == EpisodePhase.SETTLED
    assert (root / SETTLEMENT_INTENT_NAME).read_bytes() == sealed_intent_bytes

    replayed = replay_episode(root=root)
    assert replayed["replay_match"] is True
    assert replayed["settled_episode_hash"] == recovered["settled_episode_hash"]

    with pytest.raises(StoreError, match=r"exclusive create rejected|SETTLED|already exists"):
        settle_episode(**settle_kwargs)


def test_exact_recovery_after_outcome_before_settled_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact full-intent settle retry may resume from intent+outcome to sealed SETTLED."""
    root = tmp_path / "episode-recover-identical"
    init_episode(
        root=root, seat_id="seat.consumer.recover", portfolio_ref="portfolio.consumer.recover"
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "recover_req.json"))
    outcome_path = _outcome_payload(tmp_path / "recover_out.json", special_number=1)
    settle_kwargs = {
        "root": root,
        "outcome_path": outcome_path,
        "settlement_ref": "settlement.recover-outcome.v1",
        "settlement_journal_group_ref": "journal.settlement.recover-outcome.v1",
        "statement_ref": "statement.recover-outcome.v1",
        "occurred_at": (OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }

    original = store_mod.write_new_json
    fail_once = {"armed": True}

    def crash_settled_once(path: Path, payload: object) -> None:
        if path.name == SETTLED_NAME and fail_once["armed"]:
            fail_once["armed"] = False
            raise StoreError("injected crash after outcome write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_settled_once)
    with pytest.raises(StoreError, match="injected crash after outcome write"):
        settle_episode(**settle_kwargs)
    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    sealed_intent_bytes = (root / SETTLEMENT_INTENT_NAME).read_bytes()
    sealed_outcome_bytes = (root / OUTCOME_NAME).read_bytes()

    recovered = settle_episode(**settle_kwargs)
    assert recovered["ok"] is True
    assert recovered["phase"] == EpisodePhase.SETTLED.value
    assert recovered["statement_result"] == "HIT"
    assert detect_phase(root) == EpisodePhase.SETTLED
    assert (root / SETTLEMENT_INTENT_NAME).read_bytes() == sealed_intent_bytes
    assert (root / OUTCOME_NAME).read_bytes() == sealed_outcome_bytes

    replayed = replay_episode(root=root)
    assert replayed["replay_match"] is True
    assert replayed["settled_episode_hash"] == recovered["settled_episode_hash"]

    with pytest.raises(StoreError, match=r"exclusive create rejected|SETTLED|already exists"):
        settle_episode(**settle_kwargs)


def test_conflicting_outcome_recovery_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Conflicting outcome on recovery must fail closed and leave partial state intact."""
    root = tmp_path / "episode-recover-conflict"
    init_episode(
        root=root, seat_id="seat.consumer.conflict", portfolio_ref="portfolio.consumer.conflict"
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "conflict_req.json"))
    first_outcome = _outcome_payload(tmp_path / "conflict_out1.json", special_number=1)
    second_outcome = _outcome_payload(tmp_path / "conflict_out2.json", special_number=2)

    original = store_mod.write_new_json

    def crash_on_settled(path: Path, payload: object) -> None:
        if path.name == SETTLED_NAME:
            raise StoreError("injected crash after outcome write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_on_settled)
    with pytest.raises(StoreError, match="injected crash after outcome write"):
        settle_episode(root=root, outcome_path=first_outcome)

    sealed_intent_bytes = (root / SETTLEMENT_INTENT_NAME).read_bytes()
    sealed_outcome_bytes = (root / OUTCOME_NAME).read_bytes()
    with pytest.raises(StoreError, match=r"conflicting settlement recovery rejected"):
        settle_episode(root=root, outcome_path=second_outcome)

    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    assert not (root / SETTLED_NAME).is_file()
    assert (root / SETTLEMENT_INTENT_NAME).read_bytes() == sealed_intent_bytes
    assert (root / OUTCOME_NAME).read_bytes() == sealed_outcome_bytes
    with pytest.raises(StoreError, match=r"replay requires SETTLED"):
        replay_episode(root=root)


def test_differing_settlement_ref_recovery_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same outcome with different settlement_ref must not rewrite sealed settlement identity."""
    root = tmp_path / "episode-recover-settlement-ref"
    init_episode(
        root=root,
        seat_id="seat.consumer.settle-ref",
        portfolio_ref="portfolio.consumer.settle-ref",
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "settle_ref_req.json"))
    outcome_path = _outcome_payload(tmp_path / "settle_ref_out.json", special_number=1)

    original = store_mod.write_new_json

    def crash_on_outcome(path: Path, payload: object) -> None:
        if path.name == OUTCOME_NAME:
            raise StoreError("injected crash after intent write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_on_outcome)
    with pytest.raises(StoreError, match="injected crash after intent write"):
        settle_episode(
            root=root,
            outcome_path=outcome_path,
            settlement_ref="settlement.first.v1",
            settlement_journal_group_ref="journal.settlement.first.v1",
            statement_ref="statement.first.v1",
            occurred_at=(OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )

    sealed_intent_bytes = (root / SETTLEMENT_INTENT_NAME).read_bytes()
    with pytest.raises(StoreError, match=r"conflicting settlement recovery rejected"):
        settle_episode(
            root=root,
            outcome_path=outcome_path,
            settlement_ref="settlement.second.v1",
            settlement_journal_group_ref="journal.settlement.first.v1",
            statement_ref="statement.first.v1",
            occurred_at=(OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )

    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    assert not (root / OUTCOME_NAME).is_file()
    assert not (root / SETTLED_NAME).is_file()
    assert (root / SETTLEMENT_INTENT_NAME).read_bytes() == sealed_intent_bytes


def test_differing_occurred_at_recovery_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same outcome with different occurred_at must fail closed against sealed intent."""
    root = tmp_path / "episode-recover-occurred-at"
    init_episode(
        root=root,
        seat_id="seat.consumer.occurred-at",
        portfolio_ref="portfolio.consumer.occurred-at",
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "occurred_req.json"))
    outcome_path = _outcome_payload(tmp_path / "occurred_out.json", special_number=1)
    first_at = (OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    second_at = (OPEN + timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    original = store_mod.write_new_json

    def crash_on_settled(path: Path, payload: object) -> None:
        if path.name == SETTLED_NAME:
            raise StoreError("injected crash after outcome write")
        original(path, payload)

    monkeypatch.setattr(store_mod, "write_new_json", crash_on_settled)
    with pytest.raises(StoreError, match="injected crash after outcome write"):
        settle_episode(
            root=root,
            outcome_path=outcome_path,
            settlement_ref="settlement.occurred.v1",
            settlement_journal_group_ref="journal.settlement.occurred.v1",
            statement_ref="statement.occurred.v1",
            occurred_at=first_at,
        )

    sealed_intent_bytes = (root / SETTLEMENT_INTENT_NAME).read_bytes()
    sealed_outcome_bytes = (root / OUTCOME_NAME).read_bytes()
    with pytest.raises(StoreError, match=r"conflicting settlement recovery rejected"):
        settle_episode(
            root=root,
            outcome_path=outcome_path,
            settlement_ref="settlement.occurred.v1",
            settlement_journal_group_ref="journal.settlement.occurred.v1",
            statement_ref="statement.occurred.v1",
            occurred_at=second_at,
        )

    assert detect_phase(root) == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    assert not (root / SETTLED_NAME).is_file()
    assert (root / SETTLEMENT_INTENT_NAME).read_bytes() == sealed_intent_bytes
    assert (root / OUTCOME_NAME).read_bytes() == sealed_outcome_bytes


def test_same_intent_concurrent_settle_once_only(tmp_path: Path) -> None:
    """Bounded same-intent race: ledger seals once; concurrent loser fails closed."""
    root = tmp_path / "episode-concurrent-same-intent"
    init_episode(
        root=root,
        seat_id="seat.consumer.concurrent",
        portfolio_ref="portfolio.consumer.concurrent",
    )
    freeze_episode(root=root, request_path=_action_request(tmp_path / "concurrent_req.json"))
    outcome_path = _outcome_payload(tmp_path / "concurrent_out.json", special_number=1)
    settle_kwargs = {
        "root": root,
        "outcome_path": outcome_path,
        "settlement_ref": "settlement.concurrent.v1",
        "settlement_journal_group_ref": "journal.settlement.concurrent.v1",
        "statement_ref": "statement.concurrent.v1",
        "occurred_at": (OPEN + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }

    barrier = threading.Barrier(2)
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=5)
        try:
            result = settle_episode(**settle_kwargs)
            with lock:
                results.append(result)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) + len(errors) == 2
    assert len(results) >= 1
    assert all(
        item["ok"] is True and item["phase"] == EpisodePhase.SETTLED.value for item in results
    )
    if len(results) == 2:
        assert results[0]["settled_episode_hash"] == results[1]["settled_episode_hash"]
    else:
        assert any(
            isinstance(exc, StoreError)
            and (
                "already exists" in str(exc)
                or "exclusive create rejected" in str(exc)
                or "SETTLED" in str(exc)
            )
            for exc in errors
        )

    assert detect_phase(root) == EpisodePhase.SETTLED
    assert (root / SETTLEMENT_INTENT_NAME).is_file()
    assert (root / OUTCOME_NAME).is_file()
    assert (root / SETTLED_NAME).is_file()
    replayed = replay_episode(root=root)
    assert replayed["replay_match"] is True
    assert replayed["settled_episode_hash"] == results[0]["settled_episode_hash"]

    with pytest.raises(StoreError, match=r"exclusive create rejected|SETTLED|already exists"):
        settle_episode(**settle_kwargs)


def test_cli_main_init_inspect_and_capability_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "cli-root"
    code = consumer_main(
        [
            "init",
            "--root",
            str(root),
            "--seat-id",
            "seat.cli",
            "--portfolio-ref",
            "portfolio.cli",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["phase"] == "INIT"

    code = consumer_main(["inspect", "--root", str(root)])
    assert code == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["ok"] is True
    assert inspected["completion_claim_allowed"] is False
    assert CONSUMER_ID == "shadow_lifecycle_file_backed_leg_a"

    # Missing root fails closed without claiming completion.
    code = consumer_main(["inspect", "--root", str(tmp_path / "missing")])
    assert code == 1
    failed = json.loads(capsys.readouterr().out)
    assert failed["ok"] is False
    assert failed["completion_claim_allowed"] is False
