"""Sealed prospective reveal → one-shot mechanical portfolio settlement adapter.

Owner-triggered product seam: load an already-sealed accepted reveal from the
prospective authority CAS, derive ``OutcomeObservation`` mechanically, and settle
exactly one already-frozen shadow portfolio period via existing
``settle_portfolio_period``.

Does **not** accept caller-supplied outcome number/source/time fields. Does not
capture, reveal, poll, feedback, freeze next period, start research, loop,
schedule, daemonize, or introduce Temporal/leg-B/second Owner. Does not
authenticate Codex; physical Owner authority remains mount/write isolation.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from xinao.science.freeze_adapter import (
    extract_research_binding_hash_from_frozen,
    load_research_binding,
)
from xinao.science.prospective_source_thin import (
    SOURCE_ID,
    ProspectiveSourceError,
    is_live_macaujc2_target,
    load_packet,
    load_reveal,
    load_reveal_index,
    resolve_authority_root,
)
from xinao.settlement.shadow import OutcomeObservation
from xinao.shadow_lifecycle.consumer import settle_portfolio_period
from xinao.shadow_lifecycle.store import (
    PortfolioPeriodPhase,
    StoreError,
    derive_portfolio_head,
    load_frozen,
    load_outcome,
    load_settled,
    period_directory,
    resolve_root,
)

ADAPTER_MARKER: Final = "XINAO_SETTLE_FROM_REVEAL_ADAPTER_V1"
OUTCOME_EVIDENCE_SCHEMA: Final = "xinao.settle_from_reveal_outcome_evidence.v1"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Import-surface guard: this module must not pull Temporal/Goal control planes.
_FORBIDDEN_IMPORT_TOKENS: Final = frozenset(
    {
        "temporalio",
        "temporal",
        "root_intent_loop",
        "GoalWorkflow",
    }
)

# Surface that must never appear as public CLI/library outcome overrides.
_FORBIDDEN_CALLER_OUTCOME_KEYS: Final = frozenset(
    {
        "outcome",
        "actual_special_number",
        "special_number",
        "open_code",
        "openCode",
        "source_ref",
        "observed_at",
        "result_hash",
        "outcome_ref",
        "settlement",
        "settled",
    }
)


class SettleFromRevealError(ValueError):
    """Fail-closed settle-from-reveal rejection with stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise SettleFromRevealError("SETTLE_HASH_INVALID", f"{label} must be lowercase sha256")
    return value


def _raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _honest_flags() -> dict[str, Any]:
    return {
        "completion_claim_allowed": False,
        "parent_complete": False,
        "real_money_authorized": False,
        "scientific_promotion": False,
        "auto_capture": False,
        "auto_reveal": False,
        "auto_freeze": False,
        "auto_settle": False,
        "auto_feedback": False,
        "auto_next_period": False,
        "auto_next_research": False,
        "feedback_written": False,
        "next_period_frozen": False,
        "research_started": False,
        "daemon": False,
        "temporal": False,
        "poll": False,
        "loop": False,
        "schedule": False,
        "trusted_time_proof": False,
        "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
        "physical_owner_write_isolation_verified": False,
        "caller_outcome_override_accepted": False,
    }


def reject_caller_outcome_overrides(kwargs: Mapping[str, Any]) -> None:
    """Hard-reject any attempt to pass outcome identity alongside the adapter."""

    for key in kwargs:
        lowered = str(key).lower()
        if key in _FORBIDDEN_CALLER_OUTCOME_KEYS or lowered in _FORBIDDEN_CALLER_OUTCOME_KEYS:
            raise SettleFromRevealError(
                "CALLER_OUTCOME_OVERRIDE_FORBIDDEN",
                f"settle-from-reveal must not accept {key!r}; "
                "outcome is derived from sealed reveal",
            )


def outcome_from_sealed_reveal(reveal: Mapping[str, Any]) -> OutcomeObservation:
    """Derive and re-seal OutcomeObservation strictly from sealed reveal bytes."""

    admission = str(reveal.get("admission_status") or "")
    if admission in {"CONFLICT", "QUARANTINED"}:
        raise SettleFromRevealError(
            "REVEAL_NOT_ACCEPTED",
            f"admission_status={admission}",
        )
    if admission not in {"ACCEPTED", "DUPLICATE"}:
        raise SettleFromRevealError(
            "REVEAL_NOT_ACCEPTED",
            f"admission_status={admission!r}",
        )
    raw_outcome = reveal.get("outcome")
    if not isinstance(raw_outcome, Mapping):
        raise SettleFromRevealError("REVEAL_OUTCOME_MISSING", "reveal.outcome object required")
    try:
        outcome = OutcomeObservation.model_validate(dict(raw_outcome))
    except Exception as exc:  # pydantic ValidationError
        raise SettleFromRevealError("REVEAL_OUTCOME_INVALID", str(exc)) from exc
    if outcome.result_hash is None:
        outcome = outcome.with_hash()
    else:
        try:
            outcome.require_valid_result_hash()
        except ValueError as exc:
            raise SettleFromRevealError("REVEAL_OUTCOME_HASH_MISMATCH", str(exc)) from exc
    if not outcome.verified:
        raise SettleFromRevealError("REVEAL_NOT_ACCEPTED", "outcome.verified is false")
    if outcome.source_ref != SOURCE_ID:
        raise SettleFromRevealError(
            "REVEAL_SOURCE_MISMATCH",
            f"outcome.source_ref={outcome.source_ref!r} expected={SOURCE_ID!r}",
        )
    reveal_source = reveal.get("source_id")
    if reveal_source is not None and str(reveal_source) != SOURCE_ID:
        raise SettleFromRevealError(
            "REVEAL_SOURCE_MISMATCH",
            f"reveal.source_id={reveal_source!r}",
        )
    if str(reveal.get("target_ref")) != outcome.target_ref:
        raise SettleFromRevealError(
            "REVEAL_TARGET_MISMATCH",
            f"reveal.target_ref={reveal.get('target_ref')!r} outcome={outcome.target_ref!r}",
        )
    special = reveal.get("actual_special_number")
    if special is not None and int(special) != int(outcome.actual_special_number):
        raise SettleFromRevealError(
            "REVEAL_OUTCOME_NUMBER_DRIFT",
            f"reveal.actual_special_number={special!r} outcome={outcome.actual_special_number!r}",
        )
    # Reveal body does not always embed top-level result_hash; when present, bind it.
    body_result = reveal.get("result_hash")
    if isinstance(body_result, str) and body_result and body_result != outcome.result_hash:
        raise SettleFromRevealError(
            "REVEAL_RESULT_HASH_MISMATCH",
            f"reveal.result_hash={body_result!r} outcome={outcome.result_hash!r}",
        )
    return outcome


def write_derived_outcome_evidence(
    *,
    portfolio_root: Path,
    outcome: OutcomeObservation,
    reveal_content_hash: str,
    packet_content_hash: str,
) -> dict[str, Any]:
    """Exclusive content-addressed evidence of mechanically derived outcome (not hand-authored)."""

    outcome.require_valid_result_hash()
    body = {
        "schema_version": OUTCOME_EVIDENCE_SCHEMA,
        "adapter_marker": ADAPTER_MARKER,
        "derivation": "sealed_prospective_reveal",
        "packet_content_hash": packet_content_hash,
        "reveal_content_hash": reveal_content_hash,
        "outcome": outcome.model_dump(mode="json"),
        "caller_outcome_override_accepted": False,
    }
    raw = (json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = _raw_sha256(raw)
    base = resolve_root(portfolio_root)
    path = (
        base
        / "objects"
        / "settle_from_reveal_outcome"
        / "sha256"
        / digest[:2]
        / f"{digest}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
        written = True
    except FileExistsError:
        existing = path.read_bytes()
        if existing != raw:
            raise SettleFromRevealError(
                "OUTCOME_EVIDENCE_CAS_CONFLICT",
                f"path={path} already sealed with different bytes",
            )
        written = False
    # Consumer-facing outcome path is the pure OutcomeObservation JSON (existing schema).
    consumer_path = (
        base
        / "generated"
        / f"settle_from_reveal.outcome.{outcome.result_hash[:16]}.v1.json"
    )
    consumer_body = (
        json.dumps(outcome.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    consumer_path.parent.mkdir(parents=True, exist_ok=True)
    if consumer_path.is_file():
        if consumer_path.read_bytes() != consumer_body:
            raise SettleFromRevealError(
                "OUTCOME_EVIDENCE_CAS_CONFLICT",
                f"consumer path {consumer_path} differs from derived outcome",
            )
    else:
        consumer_path.write_bytes(consumer_body)
    return {
        "evidence_sha256": digest,
        "evidence_path": str(path),
        "outcome_path": str(consumer_path),
        "bytes_written": written,
        "outcome_result_hash": outcome.result_hash,
    }


def _bind_reveal_to_packet(
    *,
    packet: Mapping[str, Any],
    reveal: Mapping[str, Any],
    packet_content_hash: str,
) -> None:
    if str(reveal.get("packet_content_hash")) != packet_content_hash:
        raise SettleFromRevealError(
            "REVEAL_PACKET_MISMATCH",
            f"reveal.packet={reveal.get('packet_content_hash')!r} "
            f"expected={packet_content_hash!r}",
        )
    if str(reveal.get("target_ref")) != str(packet.get("target_ref")):
        raise SettleFromRevealError(
            "REVEAL_TARGET_MISMATCH",
            f"reveal={reveal.get('target_ref')!r} packet={packet.get('target_ref')!r}",
        )
    if str(reveal.get("target_expect")) != str(packet.get("target_expect")):
        raise SettleFromRevealError(
            "REVEAL_TARGET_MISMATCH",
            f"reveal.expect={reveal.get('target_expect')!r} "
            f"packet.expect={packet.get('target_expect')!r}",
        )
    if str(packet.get("contract", {}).get("contract_sha256")) != str(
        reveal.get("contract_sha256")
    ):
        raise SettleFromRevealError(
            "REVEAL_CONTRACT_MISMATCH",
            f"reveal.contract={reveal.get('contract_sha256')!r}",
        )


def _bind_frozen_to_authority(
    *,
    frozen: Any,
    packet: Mapping[str, Any],
    packet_content_hash: str,
    portfolio_root: Path,
    outcome: OutcomeObservation,
) -> dict[str, Any]:
    if str(frozen.target_ref) != str(packet.get("target_ref")):
        raise SettleFromRevealError(
            "FROZEN_TARGET_MISMATCH",
            f"frozen={frozen.target_ref!r} packet={packet.get('target_ref')!r}",
        )
    if outcome.target_ref != str(frozen.target_ref):
        raise SettleFromRevealError(
            "OUTCOME_TARGET_MISMATCH",
            f"outcome={outcome.target_ref!r} frozen={frozen.target_ref!r}",
        )
    if not is_live_macaujc2_target(str(frozen.target_ref)):
        raise SettleFromRevealError(
            "TARGET_NOT_PROSPECTIVE_LIVE",
            f"settle-from-reveal requires macaujc2/expect/*; got {frozen.target_ref!r}",
        )
    try:
        binding_hash = extract_research_binding_hash_from_frozen(frozen)
        binding = load_research_binding(portfolio_root, binding_hash)
    except Exception as exc:
        raise SettleFromRevealError(
            "RESEARCH_BINDING_REQUIRED",
            f"frozen episode must embed loadable research binding: {exc}",
        ) from exc
    sab = binding.get("source_authority_binding")
    if not isinstance(sab, Mapping):
        raise SettleFromRevealError(
            "SOURCE_AUTHORITY_BINDING_REQUIRED",
            "research binding must seal source_authority_binding for settle-from-reveal",
        )
    if str(sab.get("packet_content_hash")) != packet_content_hash:
        raise SettleFromRevealError(
            "AUTHORITY_HEAD_MISMATCH",
            f"binding.packet={sab.get('packet_content_hash')!r} "
            f"cli.packet={packet_content_hash!r}",
        )
    if str(sab.get("target_ref")) != str(frozen.target_ref):
        raise SettleFromRevealError(
            "SOURCE_AUTHORITY_TARGET_MISMATCH",
            f"binding.target={sab.get('target_ref')!r} frozen={frozen.target_ref!r}",
        )
    if str(binding.get("target_ref")) != str(frozen.target_ref):
        raise SettleFromRevealError(
            "RESEARCH_BINDING_TARGET_MISMATCH",
            f"binding={binding.get('target_ref')!r} frozen={frozen.target_ref!r}",
        )
    return {
        "research_binding_sha256": binding_hash,
        "research_binding": binding,
        "source_authority_binding": dict(sab),
    }


def apply_settle_from_reveal(
    *,
    authority_root: Path,
    portfolio_root: Path,
    packet_content_hash: str,
    reveal_content_hash: str | None = None,
    expected_frozen_episode_hash: str | None = None,
    period_index: int | None = None,
    **forbidden_kwargs: Any,
) -> dict[str, Any]:
    """Settle one frozen portfolio period from a sealed accepted prospective reveal.

    Outcome number/source/time are taken only from the sealed reveal CAS object.
    Reuses ``settle_portfolio_period``; never invents odds (uses frozen ticket/lifecycle
    contract). Stops after this period's settlement — no feedback/next freeze/research.
    """

    reject_caller_outcome_overrides(forbidden_kwargs)
    if forbidden_kwargs:
        # Any unexpected kwargs are fail-closed (no silent ignore of future override attempts).
        raise SettleFromRevealError(
            "UNKNOWN_SETTLE_FROM_REVEAL_KWARG",
            f"unknown={sorted(forbidden_kwargs)}",
        )

    packet_hash = _require_hex64(packet_content_hash, "packet_content_hash")
    if reveal_content_hash is not None:
        reveal_pin = _require_hex64(reveal_content_hash, "reveal_content_hash")
    else:
        reveal_pin = None
    if expected_frozen_episode_hash is not None:
        expected_frozen = _require_hex64(
            expected_frozen_episode_hash, "expected_frozen_episode_hash"
        )
    else:
        expected_frozen = None

    auth = resolve_authority_root(authority_root)
    try:
        packet = load_packet(auth, packet_hash)
    except ProspectiveSourceError as exc:
        raise SettleFromRevealError(exc.reason_code, exc.detail) from exc

    try:
        idx = load_reveal_index(auth, str(packet["target_expect"]))
    except ProspectiveSourceError as exc:
        raise SettleFromRevealError(exc.reason_code, exc.detail) from exc

    if reveal_pin is not None and idx["reveal_content_hash"] != reveal_pin:
        raise SettleFromRevealError(
            "REVEAL_HASH_MISMATCH",
            f"index={idx['reveal_content_hash']!r} pin={reveal_pin!r}",
        )
    reveal_hash = reveal_pin or str(idx["reveal_content_hash"])

    try:
        reveal = load_reveal(auth, reveal_hash)
    except ProspectiveSourceError as exc:
        raise SettleFromRevealError(exc.reason_code, exc.detail) from exc

    _bind_reveal_to_packet(packet=packet, reveal=reveal, packet_content_hash=packet_hash)

    if idx.get("result_hash") is not None and reveal.get("outcome"):
        try:
            sealed_outcome_preview = OutcomeObservation.model_validate(reveal["outcome"])
            if sealed_outcome_preview.result_hash is None:
                sealed_outcome_preview = sealed_outcome_preview.with_hash()
            if str(idx["result_hash"]) != sealed_outcome_preview.result_hash:
                raise SettleFromRevealError(
                    "REVEAL_INDEX_RESULT_MISMATCH",
                    f"index.result_hash={idx['result_hash']!r} "
                    f"outcome={sealed_outcome_preview.result_hash!r}",
                )
        except SettleFromRevealError:
            raise
        except Exception as exc:
            raise SettleFromRevealError("REVEAL_OUTCOME_INVALID", str(exc)) from exc

    # Explicit allowlist (not denylist-only): only ACCEPTED/DUPLICATE may settle.
    index_admission = str(idx.get("admission_status") or "")
    if index_admission not in {"ACCEPTED", "DUPLICATE"}:
        raise SettleFromRevealError(
            "REVEAL_NOT_ACCEPTED",
            f"index.admission_status={idx.get('admission_status')!r}",
        )

    outcome = outcome_from_sealed_reveal(reveal)

    portfolio = resolve_root(portfolio_root)
    head = derive_portfolio_head(portfolio)
    if head.period_root is None or head.phase not in {
        PortfolioPeriodPhase.FROZEN,
        PortfolioPeriodPhase.SETTLEMENT_RECOVERY_REQUIRED,
    }:
        raise SettleFromRevealError(
            "PORTFOLIO_HEAD_NOT_FROZEN",
            f"phase={head.phase.value} period_index={head.period_index}",
        )
    if period_index is not None and int(period_index) != int(head.period_index):
        raise SettleFromRevealError(
            "PERIOD_INDEX_MISMATCH",
            f"cli={period_index} head={head.period_index}",
        )

    period_root = period_directory(portfolio, head.period_index)
    frozen = load_frozen(period_root)
    if expected_frozen is not None and str(frozen.content_hash) != expected_frozen:
        raise SettleFromRevealError(
            "FROZEN_HEAD_MISMATCH",
            f"frozen={frozen.content_hash!r} expected={expected_frozen!r}",
        )
    frozen_bytes_path = period_root / "frozen_episode.v1.json"
    frozen_bytes_before = frozen_bytes_path.read_bytes() if frozen_bytes_path.is_file() else b""

    binding_info = _bind_frozen_to_authority(
        frozen=frozen,
        packet=packet,
        packet_content_hash=packet_hash,
        portfolio_root=portfolio,
        outcome=outcome,
    )

    evidence = write_derived_outcome_evidence(
        portfolio_root=portfolio,
        outcome=outcome,
        reveal_content_hash=reveal_hash,
        packet_content_hash=packet_hash,
    )

    try:
        settle_result = settle_portfolio_period(
            root=portfolio,
            outcome_path=Path(evidence["outcome_path"]),
        )
    except StoreError as exc:
        msg = str(exc)
        if "already exists" in msg or "exclusive create rejected" in msg:
            raise SettleFromRevealError("ALREADY_SETTLED", msg) from exc
        if "conflicting settlement" in msg:
            raise SettleFromRevealError("SETTLEMENT_CONFLICT", msg) from exc
        if "pre-open" in msg:
            raise SettleFromRevealError("PRE_OPEN_OBSERVATION", msg) from exc
        raise SettleFromRevealError("SETTLE_CONSUMER_REJECTED", msg) from exc
    except ValueError as exc:
        msg = str(exc)
        if "pre-open" in msg:
            raise SettleFromRevealError("PRE_OPEN_OBSERVATION", msg) from exc
        if "outcome-before-freeze" in msg:
            raise SettleFromRevealError("OUTCOME_BEFORE_FREEZE", msg) from exc
        if "not admitted" in msg or "QUARANTINED" in msg or "CONFLICT" in msg:
            raise SettleFromRevealError("OUTCOME_NOT_ADMITTED", msg) from exc
        raise SettleFromRevealError("SETTLE_CONSUMER_REJECTED", msg) from exc

    # Prove settlement used the sealed reveal number/result (no caller override).
    settled_outcome = load_outcome(period_root)
    if settled_outcome.result_hash != outcome.result_hash:
        raise SettleFromRevealError(
            "SETTLED_OUTCOME_DRIFT",
            f"settled={settled_outcome.result_hash!r} reveal={outcome.result_hash!r}",
        )
    if int(settled_outcome.actual_special_number) != int(outcome.actual_special_number):
        raise SettleFromRevealError(
            "SETTLED_NUMBER_DRIFT",
            f"settled={settled_outcome.actual_special_number} "
            f"reveal={outcome.actual_special_number}",
        )
    if settled_outcome.target_ref != outcome.target_ref:
        raise SettleFromRevealError(
            "SETTLED_TARGET_DRIFT",
            f"settled={settled_outcome.target_ref!r} reveal={outcome.target_ref!r}",
        )
    if settled_outcome.source_ref != SOURCE_ID:
        raise SettleFromRevealError(
            "SETTLED_SOURCE_DRIFT",
            f"settled.source_ref={settled_outcome.source_ref!r}",
        )

    # Frozen bytes must remain unchanged by settlement.
    if frozen_bytes_path.is_file() and frozen_bytes_path.read_bytes() != frozen_bytes_before:
        raise SettleFromRevealError(
            "FROZEN_BYTES_MUTATED",
            "settlement must not rewrite frozen_episode.v1.json",
        )

    settled = load_settled(period_root)
    account_identity = str(frozen.account_decision.identity.value)

    return {
        "ok": bool(settle_result.get("ok", True)),
        "adapter_marker": ADAPTER_MARKER,
        "command": "prospective settle-from-reveal",
        "phase": settle_result.get("phase"),
        "root": str(portfolio),
        "period_root": str(period_root),
        "period_index": head.period_index,
        "episode_ref": settle_result.get("episode_ref") or frozen.episode_ref,
        "frozen_episode_hash": frozen.content_hash,
        "settled_episode_hash": settle_result.get("settled_episode_hash") or settled.content_hash,
        "account_identity": account_identity,
        "target_ref": str(frozen.target_ref),
        "packet_content_hash": packet_hash,
        "reveal_content_hash": reveal_hash,
        "outcome_ref": outcome.outcome_ref,
        "outcome_result_hash": outcome.result_hash,
        "actual_special_number": outcome.actual_special_number,
        "source_ref": outcome.source_ref,
        "statement_result": settle_result.get("statement_result"),
        "pnl": settle_result.get("pnl"),
        "closing_balance": settle_result.get("closing_balance"),
        "derived_outcome_evidence_sha256": evidence["evidence_sha256"],
        "derived_outcome_path": evidence["outcome_path"],
        "research_binding_sha256": binding_info["research_binding_sha256"],
        "source_authority_binding": binding_info["source_authority_binding"],
        "settlement_written": True,
        "odds_invented_after_reveal": False,
        "odds_source": "frozen_ticket_or_lifecycle_contract",
        "consumer_result": settle_result,
        "next_action": settle_result.get("next_action"),
        **_honest_flags(),
    }


def assert_no_control_plane_imports() -> None:
    """Self-check: module must not import Temporal/Goal control-plane packages."""

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
    forbidden_hits = sorted(imported & {t.lower() for t in _FORBIDDEN_IMPORT_TOKENS})
    if forbidden_hits:
        raise SettleFromRevealError(
            "CONTROL_PLANE_IMPORT_FORBIDDEN",
            f"imports={forbidden_hits}",
        )


__all__ = [
    "ADAPTER_MARKER",
    "OUTCOME_EVIDENCE_SCHEMA",
    "SettleFromRevealError",
    "apply_settle_from_reveal",
    "assert_no_control_plane_imports",
    "outcome_from_sealed_reveal",
    "reject_caller_outcome_overrides",
    "write_derived_outcome_evidence",
]
