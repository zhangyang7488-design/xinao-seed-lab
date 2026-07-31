"""File-backed exclusive store for one prospective shadow episode (leg A).

Uses create-exclusive writes for once-only freeze/settlement artifacts. No daemon,
database, or network side effects. Candidate authority only.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.decision import FrozenDecision
from xinao.settlement import OutcomeObservation
from xinao.shadow_lifecycle.lifecycle import (
    AccountFeedback,
    FrozenShadowEpisode,
    SettledShadowEpisode,
    ShadowPortfolio,
    ShadowSeat,
    replay_settled_episode,
)

SEAT_NAME = "seat.v1.json"
FROZEN_NAME = "frozen_episode.v1.json"
SETTLEMENT_INTENT_NAME = "settlement_intent.v1.json"
OUTCOME_NAME = "outcome.v1.json"
SETTLED_NAME = "settled_episode.v1.json"
RECEIPT_NAME = "consumer_receipt.v1.json"
MANIFEST_NAME = "package_manifest.v1.json"
PORTFOLIO_NAME = "portfolio.v1.json"
FEEDBACK_NAME = "feedback.v1.json"
PERIODS_DIR_NAME = "periods"

SCHEMA_RECEIPT = "xinao.shadow_lifecycle.consumer_receipt.v1"
SCHEMA_MANIFEST = "xinao.shadow_lifecycle.package_manifest.v1"
SCHEMA_SETTLEMENT_INTENT = "xinao.shadow_lifecycle.settlement_intent.v1"


class EpisodePhase(StrEnum):
    MISSING = "MISSING"
    INIT = "INIT"
    FROZEN = "FROZEN"
    # Intent sealed (and optionally outcome) but settled missing. Recoverable only on
    # exact full-intent match; outcome-only match is insufficient.
    SETTLEMENT_RECOVERY_REQUIRED = "SETTLEMENT_RECOVERY_REQUIRED"
    SETTLED = "SETTLED"


class PortfolioPeriodPhase(StrEnum):
    INIT = "INIT"
    MISSING = "MISSING"
    FROZEN = "FROZEN"
    SETTLEMENT_RECOVERY_REQUIRED = "SETTLEMENT_RECOVERY_REQUIRED"
    SETTLED = "SETTLED"
    FEEDBACK_SEALED = "FEEDBACK_SEALED"


@dataclass(frozen=True)
class PortfolioHead:
    period_index: int
    phase: PortfolioPeriodPhase
    period_root: Path | None
    closing_balance: str | None
    settled_episode_hash: str | None
    feedback_hash: str | None


class StoreError(ValueError):
    """Typed store failure for CLI mapping."""


def _write_new_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
    except FileExistsError as exc:
        raise StoreError(f"exclusive create rejected; already exists: {path.name}") from exc


def write_new_json(path: Path, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_new_bytes(path, body.encode("utf-8"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Stdlib-only replace write for receipt/manifest projection (sealed cone).

    Matches catalog.compiler.write_atomic: temp sibling + os.replace. Does not
    import outside the locked shadow-runtime inventory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    if not path.is_file():
        raise StoreError(f"missing artifact: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def model_to_jsonable(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def resolve_root(root: Path) -> Path:
    return root.expanduser().resolve()


def artifact_paths(root: Path) -> dict[str, Path]:
    base = resolve_root(root)
    return {
        "seat": base / SEAT_NAME,
        "frozen": base / FROZEN_NAME,
        "intent": base / SETTLEMENT_INTENT_NAME,
        "outcome": base / OUTCOME_NAME,
        "settled": base / SETTLED_NAME,
        "receipt": base / RECEIPT_NAME,
        "manifest": base / MANIFEST_NAME,
    }


def detect_phase(root: Path) -> EpisodePhase:
    """Map exclusive artifacts to phase; fail closed on corrupt combinations.

    Settlement is a three-step exclusive journal: intent → outcome → settled.
    Intent-only or intent+outcome (no settled) is SETTLEMENT_RECOVERY_REQUIRED so an
    exact full-intent retry may resume once; settled remains required for SETTLED/replay.
    Outcome without a sealed intent is corrupt (settlement identity unbound).
    """
    paths = artifact_paths(root)
    has_settled = paths["settled"].is_file()
    has_outcome = paths["outcome"].is_file()
    has_intent = paths["intent"].is_file()
    has_frozen = paths["frozen"].is_file()
    has_seat = paths["seat"].is_file()

    if has_settled:
        if not has_frozen:
            raise StoreError("corrupt store: settled without frozen episode")
        if not has_outcome:
            raise StoreError("corrupt store: settled without outcome")
        if not has_intent:
            raise StoreError("corrupt store: settled without settlement intent")
        _assert_outcome_matches_intent(root)
        return EpisodePhase.SETTLED
    if has_intent or has_outcome:
        if has_outcome and not has_intent:
            raise StoreError("corrupt store: outcome without settlement intent")
        if not has_frozen:
            raise StoreError("corrupt store: settlement intent without frozen episode")
        if has_outcome:
            _assert_outcome_matches_intent(root)
        return EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED
    if has_frozen:
        return EpisodePhase.FROZEN
    if has_seat:
        return EpisodePhase.INIT
    return EpisodePhase.MISSING


def _sealed_outcome_jsonable(outcome: OutcomeObservation) -> dict[str, Any]:
    outcome.require_valid_result_hash()
    return model_to_jsonable(outcome)


def _sealed_settled_jsonable(settled: SettledShadowEpisode) -> dict[str, Any]:
    if settled.content_hash is None:
        raise StoreError("settled episode must be hash sealed before intent bind")
    if settled.content_hash != settled.compute_content_hash():
        raise StoreError("settled episode content seal invalid")
    return model_to_jsonable(settled)


def build_settlement_intent(
    *,
    outcome: OutcomeObservation,
    settled: SettledShadowEpisode,
) -> dict[str, Any]:
    """Hash-seal complete proposed outcome + settled artifacts before any outcome write."""
    outcome_body = _sealed_outcome_jsonable(outcome)
    settled_body = _sealed_settled_jsonable(settled)
    if settled_body.get("outcome") != outcome_body:
        raise StoreError("settlement intent binds mismatched outcome and settled.outcome")
    body: dict[str, Any] = {
        "schema_version": SCHEMA_SETTLEMENT_INTENT,
        "outcome": outcome_body,
        "settled": settled_body,
        "settled_episode_hash": settled.content_hash,
    }
    body["content_hash"] = canonical_sha256(
        {key: value for key, value in body.items() if key != "content_hash"}
    )
    return body


def _require_valid_intent_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StoreError("settlement intent must be a JSON object")
    if raw.get("schema_version") != SCHEMA_SETTLEMENT_INTENT:
        raise StoreError("settlement intent schema invalid")
    required = ("outcome", "settled", "settled_episode_hash", "content_hash")
    missing = [key for key in required if key not in raw]
    if missing:
        raise StoreError(f"settlement intent missing fields: {', '.join(missing)}")
    body = {key: value for key, value in raw.items() if key != "content_hash"}
    expected = canonical_sha256(body)
    if raw.get("content_hash") != expected:
        raise StoreError("settlement intent content seal invalid")
    settled_body = raw["settled"]
    if not isinstance(settled_body, dict):
        raise StoreError("settlement intent settled payload invalid")
    if settled_body.get("content_hash") != raw.get("settled_episode_hash"):
        raise StoreError("settlement intent settled_episode_hash mismatch")
    if settled_body.get("outcome") != raw.get("outcome"):
        raise StoreError("settlement intent outcome/settled.outcome mismatch")
    return raw


def load_settlement_intent(root: Path) -> dict[str, Any]:
    return _require_valid_intent_payload(read_json(artifact_paths(root)["intent"]))


def settlement_intents_identical(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """True iff sealed full intent matches (outcome + settled artifacts + intent hash)."""
    left = _require_valid_intent_payload(existing)
    right = _require_valid_intent_payload(candidate)
    return left == right


def _assert_outcome_matches_intent(root: Path) -> None:
    intent = load_settlement_intent(root)
    outcome = load_outcome(root)
    if intent["outcome"] != _sealed_outcome_jsonable(outcome):
        raise StoreError("corrupt store: outcome does not match sealed settlement intent")


def outcomes_identical_for_recovery(
    existing: OutcomeObservation, candidate: OutcomeObservation
) -> bool:
    """True iff sealed outcome content matches (byte-stable JSON dump)."""
    return _sealed_outcome_jsonable(existing) == _sealed_outcome_jsonable(candidate)


def _try_write_new_json_or_load(path: Path, payload: Any) -> tuple[bool, Any | None]:
    """Exclusive create; on race-loss re-read existing JSON. Returns (created, existing)."""
    try:
        write_new_json(path, payload)
        return True, None
    except StoreError as exc:
        if "already exists" not in str(exc):
            raise
        if not path.is_file():
            raise
        return False, read_json(path)


def load_seat(root: Path) -> ShadowSeat:
    raw = read_json(artifact_paths(root)["seat"])
    seat = ShadowSeat.model_validate(raw)
    if seat.content_hash is None or seat.content_hash != seat.compute_content_hash():
        raise StoreError("seat content seal invalid")
    return seat


def load_frozen(root: Path) -> FrozenShadowEpisode:
    raw = read_json(artifact_paths(root)["frozen"])
    episode = FrozenShadowEpisode.model_validate(raw)
    if episode.content_hash is None or episode.content_hash != episode.compute_content_hash():
        raise StoreError("frozen episode content seal invalid")
    return episode


def load_outcome(root: Path) -> OutcomeObservation:
    raw = read_json(artifact_paths(root)["outcome"])
    outcome = OutcomeObservation.model_validate(raw)
    outcome.require_valid_result_hash()
    return outcome


def load_settled(root: Path) -> SettledShadowEpisode:
    raw = read_json(artifact_paths(root)["settled"])
    settled = SettledShadowEpisode.model_validate(raw)
    if settled.content_hash is None or settled.content_hash != settled.compute_content_hash():
        raise StoreError("settled episode content seal invalid")
    return settled


def write_seat_exclusive(root: Path, seat: ShadowSeat) -> Path:
    if seat.content_hash is None:
        raise StoreError("seat must be hash sealed before write")
    path = artifact_paths(root)["seat"]
    write_new_json(path, model_to_jsonable(seat))
    return path


def write_frozen_exclusive(root: Path, episode: FrozenShadowEpisode) -> Path:
    if episode.content_hash is None:
        raise StoreError("frozen episode must be hash sealed before write")
    paths = artifact_paths(root)
    if paths["intent"].is_file() or paths["outcome"].is_file() or paths["settled"].is_file():
        raise StoreError("no-peek violation: cannot freeze after outcome or settlement artifacts")
    path = paths["frozen"]
    write_new_json(path, model_to_jsonable(episode))
    return path


def write_outcome_and_settled_exclusive(
    root: Path,
    *,
    outcome: OutcomeObservation,
    settled: SettledShadowEpisode,
) -> tuple[Path, Path, Path]:
    """Exclusive settlement journal: intent → outcome → settled; exact-intent recovery.

    Normal path: exclusive create hash-sealed settlement intent (binds full proposed
    outcome and settled artifacts), then exclusive create outcome, then settled.
    Crash after intent (before outcome) or after outcome (before settled) leaves
    SETTLEMENT_RECOVERY_REQUIRED. Recovery accepts only an exact full-intent match;
    differing settlement_ref/journal refs/statement_ref/occurred_at (or outcome)
    fail closed with no overwrite. Fully settled remains once-only.
    """
    intent = build_settlement_intent(outcome=outcome, settled=settled)
    paths = artifact_paths(root)
    if not paths["frozen"].is_file():
        raise StoreError("settle requires frozen episode")
    intent_path = paths["intent"]
    outcome_path = paths["outcome"]
    settled_path = paths["settled"]
    outcome_body = intent["outcome"]
    settled_body = intent["settled"]

    # Fully sealed ledger: never overwrite settled.
    if settled_path.is_file():
        raise StoreError(f"exclusive create rejected; already exists: {settled_path.name}")

    # Step 1: exclusive settlement intent (complete outcome + settled identity).
    if intent_path.is_file():
        existing_intent = load_settlement_intent(root)
        if not settlement_intents_identical(existing_intent, intent):
            raise StoreError(
                "conflicting settlement recovery rejected: sealed settlement intent "
                "does not match retry (outcome and/or settlement identity differ)"
            )
    else:
        created, existing_raw = _try_write_new_json_or_load(intent_path, intent)
        if not created:
            existing_intent = _require_valid_intent_payload(existing_raw)
            if not settlement_intents_identical(existing_intent, intent):
                raise StoreError(
                    "conflicting settlement recovery rejected: sealed settlement intent "
                    "does not match retry (outcome and/or settlement identity differ)"
                )

    # Step 2: exclusive outcome bound by sealed intent.
    if outcome_path.is_file():
        existing_outcome = load_outcome(root)
        if _sealed_outcome_jsonable(existing_outcome) != outcome_body:
            raise StoreError("corrupt store: outcome does not match sealed settlement intent")
        if not outcomes_identical_for_recovery(existing_outcome, outcome):
            raise StoreError(
                "conflicting settlement recovery rejected: sealed outcome "
                "does not match retry outcome"
            )
    else:
        created, existing_raw = _try_write_new_json_or_load(outcome_path, outcome_body)
        if not created:
            existing_outcome = OutcomeObservation.model_validate(existing_raw)
            existing_outcome.require_valid_result_hash()
            if _sealed_outcome_jsonable(existing_outcome) != outcome_body:
                raise StoreError("corrupt store: outcome does not match sealed settlement intent")
            if not outcomes_identical_for_recovery(existing_outcome, outcome):
                raise StoreError(
                    "conflicting settlement recovery rejected: sealed outcome "
                    "does not match retry outcome"
                )

    # Step 3: exclusive settled; leave intent/outcome in place on failure (no overwrite).
    try:
        write_new_json(settled_path, settled_body)
    except StoreError:
        raise
    return intent_path, outcome_path, settled_path


def write_receipt_exclusive_or_replace(
    root: Path,
    receipt: dict[str, Any],
    *,
    replace: bool,
) -> Path:
    path = artifact_paths(root)["receipt"]
    body = dict(receipt)
    if "content_hash" in body:
        body = {k: v for k, v in body.items() if k != "content_hash"}
    body["content_hash"] = canonical_sha256(body)
    if replace and path.is_file():
        # Status/receipt projection may advance after exclusive domain seals.
        _write_json_atomic(path, body)
    else:
        write_new_json(path, body)
    return path


def write_manifest(root: Path) -> dict[str, Any]:
    import hashlib

    base = resolve_root(root)
    files: dict[str, str] = {}
    for path in sorted(base.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name == MANIFEST_NAME:
            continue
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": SCHEMA_MANIFEST,
        "root": str(base),
        "files": files,
    }
    manifest["content_hash"] = canonical_sha256(manifest)
    path = artifact_paths(root)["manifest"]
    _write_json_atomic(path, manifest)
    return manifest


def load_bound_frozen_decision(payload: dict[str, Any]) -> FrozenDecision:
    decision = FrozenDecision.model_validate(payload)
    if decision.content_hash is None or decision.content_hash != decision.compute_content_hash():
        raise StoreError("bound FrozenDecision content seal invalid")
    return decision


def portfolio_artifact_paths(root: Path) -> dict[str, Path]:
    base = resolve_root(root)
    return {
        "seat": base / SEAT_NAME,
        "portfolio": base / PORTFOLIO_NAME,
        "periods": base / PERIODS_DIR_NAME,
        "receipt": base / RECEIPT_NAME,
        "manifest": base / MANIFEST_NAME,
    }


def period_directory(root: Path, period_index: int) -> Path:
    if period_index < 1:
        raise StoreError("period_index must be positive")
    return portfolio_artifact_paths(root)["periods"] / f"{period_index:06d}"


def period_artifact_paths(root: Path, period_index: int) -> dict[str, Path]:
    paths = artifact_paths(period_directory(root, period_index))
    paths["feedback"] = period_directory(root, period_index) / FEEDBACK_NAME
    return paths


def load_portfolio(root: Path) -> ShadowPortfolio:
    raw = read_json(portfolio_artifact_paths(root)["portfolio"])
    portfolio = ShadowPortfolio.model_validate(raw)
    if portfolio.content_hash is None or portfolio.content_hash != portfolio.compute_content_hash():
        raise StoreError("portfolio content seal invalid")
    return portfolio


def write_portfolio_exclusive(root: Path, portfolio: ShadowPortfolio) -> Path:
    if portfolio.content_hash is None:
        raise StoreError("portfolio must be hash sealed before write")
    path = portfolio_artifact_paths(root)["portfolio"]
    write_new_json(path, model_to_jsonable(portfolio))
    return path


def load_feedback(period_root: Path) -> AccountFeedback:
    raw = read_json(resolve_root(period_root) / FEEDBACK_NAME)
    feedback = AccountFeedback.model_validate(raw)
    if feedback.content_hash is None or feedback.content_hash != feedback.compute_content_hash():
        raise StoreError("feedback content seal invalid")
    return feedback


def write_feedback_exclusive(period_root: Path, feedback: AccountFeedback) -> Path:
    if feedback.content_hash is None:
        raise StoreError("feedback must be hash sealed before write")
    base = resolve_root(period_root)
    if detect_phase(base) != EpisodePhase.SETTLED:
        raise StoreError("feedback requires a fully settled period")
    episode = load_frozen(base)
    outcome = load_outcome(base)
    settled = load_settled(base)
    if (
        feedback.period_index != episode.period_index
        or feedback.period_index != settled.period_index
        or feedback.episode_ref != settled.episode_ref
        or feedback.settled_episode_hash != settled.content_hash
        or feedback.statement_hash != settled.statement.content_hash
        or feedback.outcome_result_hash != outcome.result_hash
        or feedback.account_pnl_echo != settled.statement.pnl
    ):
        raise StoreError("FEEDBACK_BIND_MISMATCH")
    path = base / FEEDBACK_NAME
    write_new_json(path, model_to_jsonable(feedback))
    return path


def _portfolio_identity(root: Path) -> tuple[ShadowSeat, ShadowPortfolio]:
    base = resolve_root(root)
    seat = load_seat(base)
    portfolio = load_portfolio(base)
    if (
        portfolio.seat_id != seat.seat_id
        or portfolio.portfolio_ref != seat.portfolio_ref
        or portfolio.seat_content_hash != seat.content_hash
        or portfolio.genesis_opening_balance != seat.opening_balance
    ):
        raise StoreError("FOREIGN_PORTFOLIO: portfolio identity does not match root seat")
    root_domain = artifact_paths(base)
    if any(root_domain[name].is_file() for name in ("frozen", "intent", "outcome", "settled")):
        raise StoreError("LEGACY_LAYOUT_MIXED: continuity root contains flat episode artifacts")
    return seat, portfolio


def _period_indexes(root: Path) -> tuple[int, ...]:
    periods = portfolio_artifact_paths(root)["periods"]
    if not periods.exists():
        return ()
    if periods.is_symlink() or not periods.is_dir():
        raise StoreError("periods path must be a real directory")
    indexes: list[int] = []
    for child in periods.iterdir():
        if child.is_symlink() or not child.is_dir() or not re.fullmatch(r"[0-9]{6}", child.name):
            raise StoreError(f"FOREIGN_PERIOD_ENTRY: {child.name}")
        index = int(child.name)
        if index < 1:
            raise StoreError("period index 000000 is invalid")
        indexes.append(index)
    indexes.sort()
    if indexes and indexes != list(range(1, indexes[-1] + 1)):
        raise StoreError("HISTORY_GAP: period directories must be contiguous from 000001")
    return tuple(indexes)


def _validate_period_entries(period_root: Path) -> None:
    allowed = {
        SEAT_NAME,
        FROZEN_NAME,
        SETTLEMENT_INTENT_NAME,
        OUTCOME_NAME,
        SETTLED_NAME,
        FEEDBACK_NAME,
        RECEIPT_NAME,
        MANIFEST_NAME,
    }
    for child in period_root.iterdir():
        if child.is_symlink() or not child.is_file() or child.name not in allowed:
            raise StoreError(f"FOREIGN_PERIOD_ARTIFACT: {child.name}")


def derive_portfolio_head(root: Path) -> PortfolioHead:
    """Derive the only live tip by fully validating the contiguous sealed period walk."""

    base = resolve_root(root)
    seat, _portfolio = _portfolio_identity(base)
    indexes = _period_indexes(base)
    if not indexes:
        return PortfolioHead(
            period_index=0,
            phase=PortfolioPeriodPhase.INIT,
            period_root=None,
            closing_balance=None,
            settled_episode_hash=None,
            feedback_hash=None,
        )

    prior_settled: SettledShadowEpisode | None = None
    head: PortfolioHead | None = None
    for offset, index in enumerate(indexes):
        period_root = period_directory(base, index)
        _validate_period_entries(period_root)
        episode_phase = detect_phase(period_root)
        feedback_path = period_root / FEEDBACK_NAME
        is_last = offset == len(indexes) - 1
        if episode_phase == EpisodePhase.MISSING:
            if feedback_path.is_file():
                raise StoreError("corrupt period: feedback without a settled episode")
            phase = PortfolioPeriodPhase.MISSING
            if not is_last:
                raise StoreError("HISTORY_GAP: empty period precedes a later period")
            head = PortfolioHead(index, phase, period_root, None, None, None)
            continue

        period_seat = load_seat(period_root)
        if period_seat != seat:
            raise StoreError("FOREIGN_PORTFOLIO: period seat differs from genesis seat")

        frozen: FrozenShadowEpisode | None = None
        settled: SettledShadowEpisode | None = None
        if episode_phase != EpisodePhase.INIT:
            frozen = load_frozen(period_root)
            if (
                frozen.period_index != index
                or frozen.seat_id != seat.seat_id
                or frozen.portfolio_ref != seat.portfolio_ref
                or frozen.opening_balance != seat.opening_balance
            ):
                raise StoreError("FOREIGN_PORTFOLIO: frozen period identity mismatch")
            if frozen.accounting_basis.value != "CARRIED_BALANCE_SNAPSHOT":
                raise StoreError("continuity period must use CARRIED_BALANCE_SNAPSHOT")
            if index == 1:
                if frozen.prior_close_binding is not None:
                    raise StoreError("period 1 must not carry a prior close binding")
            else:
                if prior_settled is None or frozen.prior_close_binding is None:
                    raise StoreError("HISTORY_GAP: successor lacks prior settled binding")
                binding = frozen.prior_close_binding
                if (
                    binding.prior_period_index != index - 1
                    or binding.prior_episode_ref != prior_settled.episode_ref
                    or binding.prior_settled_episode_hash != prior_settled.content_hash
                    or binding.prior_statement_hash != prior_settled.statement.content_hash
                    or binding.prior_closing_balance != prior_settled.statement.closing_balance
                ):
                    raise StoreError("PRIOR_SETTLED_HASH_MISMATCH: successor binding is stale")

        if episode_phase == EpisodePhase.SETTLED:
            assert frozen is not None
            outcome = load_outcome(period_root)
            settled = load_settled(period_root)
            if settled.period_index != index:
                raise StoreError("FOREIGN_PORTFOLIO: settled period_index mismatch")
            replay_settled_episode(
                episode=frozen,
                outcome=outcome,
                settled=settled,
                seat=seat,
                portfolio_ref=seat.portfolio_ref,
            )

        feedback_hash: str | None = None
        if feedback_path.is_file():
            if episode_phase != EpisodePhase.SETTLED or settled is None:
                raise StoreError("corrupt period: feedback requires a settled episode")
            feedback = load_feedback(period_root)
            if (
                feedback.period_index != index
                or feedback.episode_ref != settled.episode_ref
                or feedback.settled_episode_hash != settled.content_hash
                or feedback.statement_hash != settled.statement.content_hash
                or feedback.outcome_result_hash != settled.outcome.result_hash
                or feedback.account_pnl_echo != settled.statement.pnl
            ):
                raise StoreError("FEEDBACK_BIND_MISMATCH")
            phase = PortfolioPeriodPhase.FEEDBACK_SEALED
            feedback_hash = feedback.content_hash
        else:
            phase = PortfolioPeriodPhase(episode_phase.value)

        if not is_last and phase != PortfolioPeriodPhase.FEEDBACK_SEALED:
            raise StoreError("HISTORY_GAP: later period exists before prior feedback seal")
        prior_settled = settled
        head = PortfolioHead(
            period_index=index,
            phase=phase,
            period_root=period_root,
            closing_balance=settled.statement.closing_balance if settled is not None else None,
            settled_episode_hash=settled.content_hash if settled is not None else None,
            feedback_hash=feedback_hash,
        )

    assert head is not None
    return head


def prepare_next_period_root(
    root: Path,
) -> tuple[Path, int, SettledShadowEpisode | None]:
    """Select the single legal next slot and install an exact genesis-seat copy."""

    base = resolve_root(root)
    seat, _portfolio = _portfolio_identity(base)
    head = derive_portfolio_head(base)
    if head.period_index == 0:
        period_index = 1
    elif head.phase in {PortfolioPeriodPhase.MISSING, PortfolioPeriodPhase.INIT}:
        period_index = head.period_index
    elif head.phase == PortfolioPeriodPhase.FEEDBACK_SEALED:
        period_index = head.period_index + 1
    else:
        raise StoreError(f"portfolio cannot open a new period while head is {head.phase.value}")

    prior_settled = (
        load_settled(period_directory(base, period_index - 1)) if period_index > 1 else None
    )
    periods = portfolio_artifact_paths(base)["periods"]
    periods.mkdir(parents=True, exist_ok=True)
    if periods.is_symlink():
        raise StoreError("periods path must not be a symlink")
    period_root = period_directory(base, period_index)
    period_root.mkdir(exist_ok=True)
    if period_root.is_symlink():
        raise StoreError("period path must not be a symlink")
    seat_path = artifact_paths(period_root)["seat"]
    if seat_path.is_file():
        if load_seat(period_root) != seat:
            raise StoreError("FOREIGN_PORTFOLIO: period seat differs from genesis seat")
    else:
        try:
            write_seat_exclusive(period_root, seat)
        except StoreError as exc:
            if "already exists" not in str(exc) or load_seat(period_root) != seat:
                raise
    return period_root, period_index, prior_settled


def write_portfolio_manifest(root: Path) -> dict[str, Any]:
    import hashlib

    base = resolve_root(root)
    files: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative = path.relative_to(base).as_posix()
        if relative == MANIFEST_NAME:
            continue
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": SCHEMA_MANIFEST,
        "root": str(base),
        "files": files,
    }
    manifest["content_hash"] = canonical_sha256(manifest)
    _write_json_atomic(portfolio_artifact_paths(base)["manifest"], manifest)
    return manifest
