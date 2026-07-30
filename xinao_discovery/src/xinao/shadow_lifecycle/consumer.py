"""Leg-A one-click file-backed shadow-lifecycle consumer.

Stable CLI: ``python -m xinao.shadow_lifecycle`` or ``xinao shadow ...``.

Flow: init → freeze (pre-outcome) → settle (explicit outcome) → status/replay.
Preserves frozen identity, no-peek, exact journals, once-only settlement, and
candidate-only authority. No Docker, Temporal, database, daemon, or live account.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from xinao.decision import FrozenDecision
from xinao.settlement import OutcomeObservation
from xinao.shadow_lifecycle.lifecycle import (
    AccountBranchDecision,
    AccountDecisionIdentity,
    EvidenceState,
    ScienceDecisionIdentity,
    assess_fixture_evidence,
    build_account_action,
    build_account_no_action,
    build_science_decision,
    create_seat,
    freeze_shadow_episode,
    replay_settled_episode,
    settle_shadow_episode,
)
from xinao.shadow_lifecycle.store import (
    SCHEMA_RECEIPT,
    EpisodePhase,
    StoreError,
    detect_phase,
    load_frozen,
    load_outcome,
    load_seat,
    load_settled,
    read_json,
    resolve_root,
    write_frozen_exclusive,
    write_manifest,
    write_outcome_and_settled_exclusive,
    write_receipt_exclusive_or_replace,
    write_seat_exclusive,
)

CONSUMER_ID = "shadow_lifecycle_file_backed_leg_a"
CONSUMER_VERSION = "0.1.0"


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StoreError("timestamp must be timezone-aware")
    return parsed


def _load_request(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise StoreError("request must be a JSON object")
    return raw


def _receipt_base(*, root: Path, phase: EpisodePhase, **fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": SCHEMA_RECEIPT,
        "consumer_id": CONSUMER_ID,
        "consumer_version": CONSUMER_VERSION,
        "root": str(resolve_root(root)),
        "phase": phase.value,
        "parent_complete": False,
        "scientific_promotion": False,
        "real_money_authorized": False,
        "completion_claim_allowed": False,
        "first_episode_verified": False,
        "evidence_state": EvidenceState.IMPLEMENTATION_READY.value,
        "candidate_only": True,
    }
    body.update(fields)
    return body


def init_episode(
    *,
    root: Path,
    seat_id: str,
    portfolio_ref: str,
    opening_balance: str | None = None,
) -> dict[str, Any]:
    base = resolve_root(root)
    if base.exists() and any(base.iterdir()):
        raise StoreError(f"init requires an empty root directory: {base}")
    base.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"seat_id": seat_id, "portfolio_ref": portfolio_ref}
    if opening_balance is not None:
        kwargs["opening_balance"] = opening_balance
    seat = create_seat(**kwargs)
    write_seat_exclusive(base, seat)
    receipt = _receipt_base(
        root=base,
        phase=EpisodePhase.INIT,
        seat_id=seat.seat_id,
        portfolio_ref=seat.portfolio_ref,
        seat_content_hash=seat.content_hash,
        opening_balance=seat.opening_balance,
        next_action="freeze",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=False)
    write_manifest(base)
    return {
        "ok": True,
        "phase": EpisodePhase.INIT.value,
        "root": str(base),
        "seat_id": seat.seat_id,
        "portfolio_ref": seat.portfolio_ref,
        "seat_content_hash": seat.content_hash,
        "completion_claim_allowed": False,
    }


def inspect_episode(*, root: Path) -> dict[str, Any]:
    base = resolve_root(root)
    phase = detect_phase(base)
    if phase == EpisodePhase.MISSING:
        return {
            "ok": False,
            "phase": phase.value,
            "root": str(base),
            "error": "store missing or uninitialized",
            "completion_claim_allowed": False,
        }

    seat = load_seat(base)
    result: dict[str, Any] = {
        "ok": True,
        "phase": phase.value,
        "root": str(base),
        "seat_id": seat.seat_id,
        "portfolio_ref": seat.portfolio_ref,
        "seat_content_hash": seat.content_hash,
        "opening_balance": seat.opening_balance,
        "completion_claim_allowed": False,
        "first_episode_verified": False,
        "candidate_only": True,
    }

    if phase in {EpisodePhase.FROZEN, EpisodePhase.SETTLED}:
        episode = load_frozen(base)
        result.update(
            {
                "episode_ref": episode.episode_ref,
                "frozen_episode_hash": episode.content_hash,
                "target_ref": episode.target_ref,
                "account_identity": episode.account_decision.identity.value,
                "science_identity": episode.science_decision.identity.value,
                "pre_freeze_balance": episode.pre_freeze_balance,
                "outcome_present": False,
            }
        )
        # no-peek: do not surface outcome fields while only frozen
        if phase == EpisodePhase.FROZEN:
            result["next_action"] = "settle"
            result["evidence_state"] = EvidenceState.IMPLEMENTATION_READY.value

    if phase == EpisodePhase.SETTLED:
        settled = load_settled(base)
        outcome = load_outcome(base)
        result.update(
            {
                "outcome_present": True,
                "outcome_ref": outcome.outcome_ref,
                "settled_episode_hash": settled.content_hash,
                "statement_ref": settled.statement.statement_ref,
                "statement_result": settled.statement.result.value,
                "pnl": settled.statement.pnl,
                "closing_balance": settled.statement.closing_balance,
                "next_action": "replay",
                "evidence_state": assess_fixture_evidence(
                    implementation_ready=True, synthetic_or_historical=True
                ).state.value,
            }
        )
    elif phase == EpisodePhase.INIT:
        result["next_action"] = "freeze"
        result["evidence_state"] = EvidenceState.IMPLEMENTATION_READY.value

    return result


def freeze_episode(*, root: Path, request_path: Path) -> dict[str, Any]:
    base = resolve_root(root)
    phase = detect_phase(base)
    if phase != EpisodePhase.INIT:
        raise StoreError(f"freeze requires INIT phase, found {phase.value}")

    seat = load_seat(base)
    request = _load_request(request_path)

    # Hard no-peek: refuse outcome material on freeze path.
    for forbidden in ("outcome", "actual_special_number", "settlement", "settled"):
        if forbidden in request:
            raise StoreError(f"no-peek violation: freeze request must not include {forbidden!r}")

    episode_ref = str(request["episode_ref"])
    science_raw = request.get("science_decision") or request.get("science")
    if not isinstance(science_raw, dict):
        raise StoreError("freeze requires science_decision object")
    science = build_science_decision(
        science_decision_ref=str(science_raw["science_decision_ref"]),
        identity=ScienceDecisionIdentity(str(science_raw["identity"])),
        knowledge_cutoff=_parse_time(science_raw["knowledge_cutoff"]),
        rationale_ref=str(science_raw["rationale_ref"]),
        candidate_ref=science_raw.get("candidate_ref"),
    )
    # Scientific POLICY_NO_ACTION is not an account ticket; still freeze with explicit account.

    account_raw = request.get("account_decision") or request.get("account")
    bound_raw = request.get("bound_frozen_decision")
    bound: FrozenDecision | None = None
    if bound_raw is not None:
        if not isinstance(bound_raw, dict):
            raise StoreError("bound_frozen_decision must be a JSON object")
        bound = FrozenDecision.model_validate(bound_raw)
        if bound.content_hash is None:
            bound = bound.with_content_hash()
        elif bound.content_hash != bound.compute_content_hash():
            raise StoreError("bound FrozenDecision content seal invalid")

    if account_raw is None:
        if bound is None:
            raise StoreError("freeze requires account_decision or ACTION bound_frozen_decision")
        account = build_account_action(
            account_decision_ref=str(request.get("account_decision_ref") or f"acct.{episode_ref}"),
            frozen_decision=bound,
        )
    else:
        if not isinstance(account_raw, dict):
            raise StoreError("account_decision must be a JSON object")
        identity = AccountDecisionIdentity(str(account_raw["identity"]))
        if identity == AccountDecisionIdentity.ACTION:
            if bound is None:
                raise StoreError("ACTION freeze requires bound_frozen_decision")
            account = build_account_action(
                account_decision_ref=str(account_raw["account_decision_ref"]),
                frozen_decision=bound,
            )
        else:
            account = build_account_no_action(
                account_decision_ref=str(account_raw["account_decision_ref"]),
                rule_ref=str(account_raw["rule_ref"]),
                odds_version_ref=str(account_raw["odds_version_ref"]),
            )

    if isinstance(account, AccountBranchDecision) and account.content_hash is None:
        raise StoreError("account decision seal failed")

    target_ref = str(request["target_ref"])
    target_open_time = _parse_time(request["target_open_time"])
    freeze_deadline = _parse_time(request["freeze_deadline"])
    frozen_at = _parse_time(request["frozen_at"])

    freeze_kwargs: dict[str, Any] = {
        "episode_ref": episode_ref,
        "seat": seat,
        "science_decision": science,
        "account_decision": account,
        "target_ref": target_ref,
        "target_open_time": target_open_time,
        "freeze_deadline": freeze_deadline,
        "frozen_at": frozen_at,
        "outcome_present": False,
    }
    if request.get("pre_freeze_balance") is not None:
        freeze_kwargs["pre_freeze_balance"] = str(request["pre_freeze_balance"])
    if account.identity == AccountDecisionIdentity.ACTION:
        freeze_kwargs["bound_frozen_decision"] = bound
        freeze_kwargs["opening_journal_group_ref"] = str(
            request.get("opening_journal_group_ref") or f"journal.opening.{episode_ref}"
        )
        freeze_kwargs["position_journal_group_ref"] = str(
            request.get("position_journal_group_ref") or f"journal.position.{episode_ref}"
        )

    episode = freeze_shadow_episode(**freeze_kwargs)
    write_frozen_exclusive(base, episode)
    receipt = _receipt_base(
        root=base,
        phase=EpisodePhase.FROZEN,
        seat_id=seat.seat_id,
        portfolio_ref=seat.portfolio_ref,
        episode_ref=episode.episode_ref,
        frozen_episode_hash=episode.content_hash,
        target_ref=episode.target_ref,
        account_identity=episode.account_decision.identity.value,
        science_identity=episode.science_decision.identity.value,
        next_action="settle",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=True)
    write_manifest(base)
    return {
        "ok": True,
        "phase": EpisodePhase.FROZEN.value,
        "root": str(base),
        "episode_ref": episode.episode_ref,
        "frozen_episode_hash": episode.content_hash,
        "account_identity": episode.account_decision.identity.value,
        "completion_claim_allowed": False,
        "next_action": "settle",
    }


def settle_episode(
    *,
    root: Path,
    outcome_path: Path,
    settlement_ref: str | None = None,
    settlement_journal_group_ref: str | None = None,
    statement_ref: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    base = resolve_root(root)
    phase = detect_phase(base)
    if phase != EpisodePhase.FROZEN:
        raise StoreError(f"settle requires FROZEN phase, found {phase.value}")

    episode = load_frozen(base)
    seat = load_seat(base)
    if seat.seat_id != episode.seat_id or seat.portfolio_ref != episode.portfolio_ref:
        raise StoreError("seat/portfolio mismatch between store and frozen episode")

    outcome_raw = _load_request(outcome_path)
    if "outcome" in outcome_raw and isinstance(outcome_raw["outcome"], dict):
        outcome_raw = outcome_raw["outcome"]
    outcome = OutcomeObservation.model_validate(outcome_raw)
    if outcome.result_hash is None:
        outcome = outcome.with_hash()
    else:
        outcome.require_valid_result_hash()

    stmt_ref = statement_ref or f"statement.{episode.episode_ref}"
    settle_kwargs: dict[str, Any] = {
        "episode": episode,
        "outcome": outcome,
        "statement_ref": stmt_ref,
        "existing_settlements": (),  # once-only enforced by exclusive settled file
    }
    if occurred_at is not None:
        settle_kwargs["occurred_at"] = _parse_time(occurred_at)

    if episode.account_decision.identity == AccountDecisionIdentity.ACTION:
        settle_kwargs["settlement_ref"] = settlement_ref or f"settlement.{episode.episode_ref}"
        settle_kwargs["settlement_journal_group_ref"] = (
            settlement_journal_group_ref or f"journal.settlement.{episode.episode_ref}"
        )
    else:
        if settlement_ref is not None or settlement_journal_group_ref is not None:
            raise StoreError("account no-action must not supply settlement journal refs")

    settled = settle_shadow_episode(**settle_kwargs)
    write_outcome_and_settled_exclusive(base, outcome=outcome, settled=settled)

    evidence = assess_fixture_evidence(implementation_ready=True, synthetic_or_historical=True)
    receipt = _receipt_base(
        root=base,
        phase=EpisodePhase.SETTLED,
        seat_id=episode.seat_id,
        portfolio_ref=episode.portfolio_ref,
        episode_ref=episode.episode_ref,
        frozen_episode_hash=episode.content_hash,
        settled_episode_hash=settled.content_hash,
        statement_ref=settled.statement.statement_ref,
        statement_result=settled.statement.result.value,
        pnl=settled.statement.pnl,
        closing_balance=settled.statement.closing_balance,
        evidence_state=evidence.state.value,
        next_action="replay",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=True)
    write_manifest(base)
    return {
        "ok": True,
        "phase": EpisodePhase.SETTLED.value,
        "root": str(base),
        "episode_ref": episode.episode_ref,
        "settled_episode_hash": settled.content_hash,
        "statement_result": settled.statement.result.value,
        "pnl": settled.statement.pnl,
        "closing_balance": settled.statement.closing_balance,
        "evidence_state": evidence.state.value,
        "first_episode_verified": False,
        "completion_claim_allowed": False,
        "next_action": "replay",
    }


def replay_episode(*, root: Path) -> dict[str, Any]:
    base = resolve_root(root)
    phase = detect_phase(base)
    if phase != EpisodePhase.SETTLED:
        raise StoreError(f"replay requires SETTLED phase, found {phase.value}")

    seat = load_seat(base)
    episode = load_frozen(base)
    outcome = load_outcome(base)
    settled = load_settled(base)
    fresh = replay_settled_episode(
        episode=episode,
        outcome=outcome,
        settled=settled,
        seat=seat,
        portfolio_ref=episode.portfolio_ref,
    )
    return {
        "ok": True,
        "phase": EpisodePhase.SETTLED.value,
        "root": str(base),
        "episode_ref": episode.episode_ref,
        "replay_match": True,
        "settled_episode_hash": settled.content_hash,
        "fresh_episode_hash": fresh.content_hash,
        "closing_balance": fresh.statement.closing_balance,
        "first_episode_verified": False,
        "completion_claim_allowed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xinao-shadow-lifecycle",
        description="Leg-A file-backed shadow lifecycle consumer (candidate-only).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_cmd = commands.add_parser("init", help="Create seat store in an empty root")
    init_cmd.add_argument("--root", type=Path, required=True)
    init_cmd.add_argument("--seat-id", required=True)
    init_cmd.add_argument("--portfolio-ref", required=True)
    init_cmd.add_argument("--opening-balance")

    inspect_cmd = commands.add_parser("inspect", help="Inspect store phase and sealed ids")
    inspect_cmd.add_argument("--root", type=Path, required=True)

    status_cmd = commands.add_parser("status", help="Alias of inspect")
    status_cmd.add_argument("--root", type=Path, required=True)

    freeze_cmd = commands.add_parser("freeze", help="Pre-outcome freeze from request JSON")
    freeze_cmd.add_argument("--root", type=Path, required=True)
    freeze_cmd.add_argument("--request", type=Path, required=True)

    settle_cmd = commands.add_parser("settle", help="Once-only settle with explicit outcome JSON")
    settle_cmd.add_argument("--root", type=Path, required=True)
    settle_cmd.add_argument("--outcome", type=Path, required=True)
    settle_cmd.add_argument("--settlement-ref")
    settle_cmd.add_argument("--settlement-journal-group-ref")
    settle_cmd.add_argument("--statement-ref")
    settle_cmd.add_argument("--occurred-at")

    replay_cmd = commands.add_parser("replay", help="Fresh deterministic replay of sealed episode")
    replay_cmd.add_argument("--root", type=Path, required=True)
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "init":
        return init_episode(
            root=args.root,
            seat_id=args.seat_id,
            portfolio_ref=args.portfolio_ref,
            opening_balance=args.opening_balance,
        )
    if args.command in {"inspect", "status"}:
        return inspect_episode(root=args.root)
    if args.command == "freeze":
        return freeze_episode(root=args.root, request_path=args.request)
    if args.command == "settle":
        return settle_episode(
            root=args.root,
            outcome_path=args.outcome,
            settlement_ref=args.settlement_ref,
            settlement_journal_group_ref=args.settlement_journal_group_ref,
            statement_ref=args.statement_ref,
            occurred_at=args.occurred_at,
        )
    if args.command == "replay":
        return replay_episode(root=args.root)
    raise StoreError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
    except (StoreError, ValueError, TypeError, KeyError) as exc:
        err = {
            "ok": False,
            "error": str(exc),
            "completion_claim_allowed": False,
            "first_episode_verified": False,
            "candidate_only": True,
        }
        print(json.dumps(err, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
