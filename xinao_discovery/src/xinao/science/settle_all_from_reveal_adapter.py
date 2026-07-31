"""Public multipolicy settle-all product seam (FrozenDecisionSet + sealed reveal).

Settles **every** due ticket in one frozen multipolicy decision set exactly once
after one independently authored, authority-validated reveal. Distinct from the
single-seat shadow ``prospective settle-from-reveal`` / portfolio head path.

Does not invent a second ledger: reuses library ``science.portfolio.settle_all``.
Does not authenticate Codex, claim campaign completion, or promote science grade.
Does not auto-loop, daemonize, or bridge multipolicy objects into single-seat
portfolio verbs.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import (
    FrozenDecisionSet,
    PolicyRole,
    REQUIRED_RESEARCH_ROLES,
    SettleAllResult,
    settle_all,
)
from xinao.science.prospective_source_thin import (
    SOURCE_ID,
    ProspectiveSourceError,
    load_reveal,
    resolve_authority_root,
)
from xinao.science.settle_from_reveal_adapter import (
    outcome_from_sealed_reveal,
    reject_caller_outcome_overrides,
)
from xinao.settlement import OutcomeObservation

ADAPTER_MARKER: Final = "XINAO_SETTLE_ALL_FROM_REVEAL_ADAPTER_V1"
RECEIPT_SCHEMA: Final = "xinao.multipolicy_settle_all_receipt.v1"
INTENT_SCHEMA: Final = "xinao.multipolicy_settle_all_intent.v1"
REVEAL_SCHEMA: Final = "xinao.prospective_reveal_capture.v1"
FIXTURE_REVEAL_SCHEMA: Final = "xinao.multipolicy_isolated_reveal_fixture.v1"
OBJECT_MODEL: Final = "multipolicy_FrozenDecisionSet"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_FORBIDDEN_IMPORT_TOKENS: Final = frozenset(
    {
        "temporalio",
        "temporal",
        "root_intent_loop",
        "GoalWorkflow",
    }
)

# Public surface must never accept these as settlement authority or subset filters.
_FORBIDDEN_SETTLE_ALL_KEYS: Final = frozenset(
    {
        "outcome",
        "actual_special_number",
        "special_number",
        "open_code",
        "opencodes",
        "source_ref",
        "observed_at",
        "result_hash",
        "outcome_ref",
        "verified",
        "ticket_refs",
        "ticket_ref",
        "policy_refs",
        "policy_ref",
        "subset",
        "selected_tickets",
        "only_roles",
        "roles",
        "void_reason_hashes",
        "settlement",
        "settled",
    }
)

_ARTIFACT_SETTLEMENT_SET = "settlement_set.v1.json"
_ARTIFACT_INTENT = "settle_all_intent.v1.json"
_ARTIFACT_RECEIPT = "multipolicy_settle_all_receipt.v1.json"
_ARTIFACT_FREEZE_COPY = "frozen_decision_set.v1.json"
_ARTIFACT_REVEAL_COPY = "sealed_reveal.v1.json"
_ARTIFACT_OUTCOME = "derived_outcome.v1.json"
_ARTIFACT_BUNDLES = "action_settlement_bundles.v1.json"


class SettleAllFromRevealError(ValueError):
    """Fail-closed multipolicy settle-all rejection with stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise SettleAllFromRevealError("SETTLE_ALL_HASH_INVALID", f"{label} must be lowercase sha256")
    return value


def _honest_flags() -> dict[str, Any]:
    return {
        "completion_claim_allowed": False,
        "parent_complete": False,
        "real_money_authorized": False,
        "scientific_promotion": False,
        "campaign_promoted": False,
        "auto_capture": False,
        "auto_reveal": False,
        "auto_freeze": False,
        "auto_settle": False,
        "auto_feedback": False,
        "auto_next_period": False,
        "auto_next_research": False,
        "feedback_written": False,
        "daemon": False,
        "temporal": False,
        "poll": False,
        "loop": False,
        "schedule": False,
        "single_seat_portfolio_mutated": False,
        "caller_outcome_override_accepted": False,
        "caller_ticket_subset_accepted": False,
        "owner_channel_authority": "UNPROVEN_BY_LIBRARY",
        "physical_owner_write_isolation_verified": False,
    }


def reject_settle_all_forbidden_kwargs(kwargs: Mapping[str, Any]) -> None:
    """Reject outcome overrides, free-form verified, and ticket-subset selection."""

    try:
        reject_caller_outcome_overrides(kwargs)
    except Exception as exc:
        reason = getattr(exc, "reason_code", None)
        detail = getattr(exc, "detail", str(exc))
        if isinstance(reason, str) and reason:
            raise SettleAllFromRevealError(reason, detail) from exc
        raise
    for key in kwargs:
        lowered = str(key).lower()
        if key in _FORBIDDEN_SETTLE_ALL_KEYS or lowered in _FORBIDDEN_SETTLE_ALL_KEYS:
            raise SettleAllFromRevealError(
                "CALLER_SETTLE_ALL_OVERRIDE_FORBIDDEN",
                f"settle-all-from-reveal must not accept {key!r}",
            )


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_exclusive_bytes(path: Path, payload: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
        return True
    except FileExistsError:
        existing = path.read_bytes()
        if existing != payload:
            raise SettleAllFromRevealError(
                "SETTLEMENT_CAS_CONFLICT",
                f"path={path} already sealed with different bytes",
            )
        return False


def _write_exclusive_json(path: Path, payload: Any) -> bool:
    return _write_exclusive_bytes(path, _json_bytes(payload))


def _atomic_replace_json(path: Path, payload: Any) -> None:
    """Replace an existing artifact under a verified recovery transaction only."""

    path.parent.mkdir(parents=True, exist_ok=True)
    body = _json_bytes(payload)
    tmp = path.with_name(path.name + ".heal_tmp")
    try:
        with tmp.open("wb") as stream:
            stream.write(body)
            stream.flush()
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _bundles_digest(bundles_payload: list[Any]) -> str:
    """Canonical digest of durable action settlement bundles payload."""

    return canonical_sha256(bundles_payload)


# Invocation-local fields must never enter sealed receipt identity / content_hash.
_RECEIPT_RESPONSE_ONLY_KEYS: Final = frozenset(
    {
        "idempotent_replay",
        "settlement_written",
    }
)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SettleAllFromRevealError("TIMESTAMP_NOT_AWARE", "timestamp must be timezone-aware")
    return value.isoformat()


def load_sealed_freeze_set(
    *,
    freeze_set_path: Path,
    expected_freeze_set_hash: str,
) -> FrozenDecisionSet:
    """Load and pin-verify a sealed FrozenDecisionSet (fail closed on hash drift)."""

    path = Path(freeze_set_path)
    if not path.is_file() or path.is_symlink():
        raise SettleAllFromRevealError("FREEZE_SET_MISSING", str(path))
    expected = _require_hex64(expected_freeze_set_hash, "expected_freeze_set_hash")
    try:
        freeze_set = FrozenDecisionSet.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SettleAllFromRevealError("FREEZE_SET_INVALID", str(exc)) from exc
    if freeze_set.content_hash is None:
        raise SettleAllFromRevealError("FREEZE_SET_UNSEALED", "FrozenDecisionSet lacks content_hash")
    recomputed = freeze_set.compute_content_hash()
    if freeze_set.content_hash != recomputed:
        raise SettleAllFromRevealError(
            "FREEZE_SET_HASH_ALTERED",
            f"embedded={freeze_set.content_hash} recomputed={recomputed}",
        )
    if freeze_set.content_hash != expected:
        raise SettleAllFromRevealError(
            "FREEZE_SET_HASH_MISMATCH",
            f"embedded={freeze_set.content_hash} expected={expected}",
        )
    return freeze_set


def enumerate_expected_tickets(freeze_set: FrozenDecisionSet) -> dict[str, Any]:
    """Enumerate exact expected tickets; fail closed on structural defects."""

    tickets = freeze_set.tickets
    if freeze_set.eligible_frozen_count != len(tickets):
        raise SettleAllFromRevealError(
            "TICKET_COUNT_MISMATCH",
            f"eligible_frozen_count={freeze_set.eligible_frozen_count} tickets={len(tickets)}",
        )
    policy_refs = [ticket.policy_ref for ticket in tickets]
    if len(set(policy_refs)) != len(policy_refs):
        raise SettleAllFromRevealError("DUPLICATE_POLICY_TICKETS", str(policy_refs))
    decision_refs = [ticket.frozen_decision.decision_ref for ticket in tickets]
    if len(set(decision_refs)) != len(decision_refs):
        raise SettleAllFromRevealError("DUPLICATE_DECISION_REFS", str(decision_refs))
    roles = {ticket.role for ticket in tickets}
    if PolicyRole.NO_ACTION not in roles or not REQUIRED_RESEARCH_ROLES.issubset(roles):
        raise SettleAllFromRevealError(
            "ROLE_COVERAGE_INCOMPLETE",
            f"roles={sorted(role.value for role in roles)}",
        )
    targets = {ticket.frozen_decision.target_ref for ticket in tickets}
    if targets != {freeze_set.target_ref}:
        raise SettleAllFromRevealError(
            "WRONG_TARGET_TICKET",
            f"set={freeze_set.target_ref!r} tickets={sorted(targets)}",
        )
    protocols = {
        (ticket.frozen_decision.protocol_pin_ref, ticket.frozen_decision.protocol_pin_sha256)
        for ticket in tickets
    }
    if len(protocols) != 1:
        raise SettleAllFromRevealError(
            "WRONG_PROTOCOL_DRIFT",
            f"protocol pins disagree across tickets: {sorted(protocols)}",
        )
    protocol_ref, protocol_sha = next(iter(protocols))
    ordered_refs = tuple(sorted(decision_refs))
    return {
        "ticket_count": len(tickets),
        "policy_refs": tuple(sorted(policy_refs)),
        "decision_refs": ordered_refs,
        "roles": tuple(sorted(role.value for role in roles)),
        "protocol_pin_ref": protocol_ref,
        "protocol_pin_sha256": protocol_sha,
        "target_ref": freeze_set.target_ref,
        "eligible_frozen_count": freeze_set.eligible_frozen_count,
    }


def _reveal_is_fixture(reveal: Mapping[str, Any]) -> bool:
    schema = str(reveal.get("schema_version") or "")
    if schema == FIXTURE_REVEAL_SCHEMA:
        return True
    if reveal.get("fixture_isolated_mechanics") is True:
        return True
    if reveal.get("evidence_class") == "ISOLATED_REVEAL_FIXTURE_MECHANICS":
        return True
    return False


def load_reveal_artifact(path: Path) -> dict[str, Any]:
    """Load an independently authored sealed reveal JSON (authority or isolated fixture)."""

    p = Path(path)
    if not p.is_file() or p.is_symlink():
        raise SettleAllFromRevealError("REVEAL_ARTIFACT_MISSING", str(p))
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SettleAllFromRevealError("REVEAL_ARTIFACT_JSON_INVALID", str(exc)) from exc
    if not isinstance(raw, dict):
        raise SettleAllFromRevealError("REVEAL_ARTIFACT_JSON_INVALID", "object required")
    embedded = raw.get("content_hash")
    if isinstance(embedded, str) and embedded:
        body = {k: v for k, v in raw.items() if k != "content_hash"}
        recomputed = canonical_sha256(body)
        if embedded != recomputed:
            raise SettleAllFromRevealError(
                "REVEAL_ARTIFACT_HASH_ALTERED",
                f"embedded={embedded} recomputed={recomputed}",
            )
    return raw


def load_authority_reveal(
    *,
    authority_root: Path,
    reveal_content_hash: str,
) -> tuple[dict[str, Any], str]:
    digest = _require_hex64(reveal_content_hash, "reveal_content_hash")
    try:
        reveal = load_reveal(resolve_authority_root(authority_root), digest)
    except ProspectiveSourceError as exc:
        raise SettleAllFromRevealError(exc.reason_code, exc.detail) from exc
    return reveal, digest


def derive_outcome_from_multipolicy_reveal(
    reveal: Mapping[str, Any],
    *,
    freeze_set: FrozenDecisionSet,
) -> tuple[OutcomeObservation, dict[str, Any]]:
    """Derive outcome only from sealed reveal envelope; bind to freeze target."""

    is_fixture = _reveal_is_fixture(reveal)
    schema = str(reveal.get("schema_version") or "")
    if schema not in {REVEAL_SCHEMA, FIXTURE_REVEAL_SCHEMA, ""} and not is_fixture:
        # Allow empty schema only for exact prospective reveal bodies already hash-sealed.
        raise SettleAllFromRevealError(
            "REVEAL_SCHEMA_UNSUPPORTED",
            f"schema_version={schema!r}",
        )

    # Free-form OutcomeObservation alone is not authority (must be reveal envelope).
    if "outcome" not in reveal and "admission_status" not in reveal:
        raise SettleAllFromRevealError(
            "REVEAL_ENVELOPE_REQUIRED",
            "free-form outcome/verified is not multipolicy settle-all authority",
        )

    try:
        if is_fixture:
            outcome = _outcome_from_fixture_reveal(reveal)
        else:
            outcome = outcome_from_sealed_reveal(reveal)
    except Exception as exc:
        # Map settle-from-reveal codes when present.
        reason = getattr(exc, "reason_code", None)
        detail = getattr(exc, "detail", str(exc))
        if isinstance(reason, str) and reason:
            raise SettleAllFromRevealError(reason, detail) from exc
        raise SettleAllFromRevealError("REVEAL_OUTCOME_INVALID", str(exc)) from exc

    if outcome.target_ref != freeze_set.target_ref:
        raise SettleAllFromRevealError(
            "REVEAL_TARGET_MISMATCH",
            f"reveal/outcome={outcome.target_ref!r} freeze_set={freeze_set.target_ref!r}",
        )
    if outcome.observed_at < freeze_set.target_open_time:
        raise SettleAllFromRevealError(
            "REVEAL_PRE_OPEN",
            f"observed_at={_iso(outcome.observed_at)} open={_iso(freeze_set.target_open_time)}",
        )
    if not outcome.verified:
        raise SettleAllFromRevealError("REVEAL_NOT_VERIFIED", "outcome.verified is false")
    meta = {
        "fixture_isolated_mechanics": is_fixture,
        "evidence_class": (
            "ISOLATED_REVEAL_FIXTURE_MECHANICS" if is_fixture else "AUTHORITY_REVEAL"
        ),
        "reveal_source_id": reveal.get("source_id") or outcome.source_ref,
        "admission_status": reveal.get("admission_status"),
        "formal_object_settled": False if is_fixture else None,
    }
    return outcome, meta


def _outcome_from_fixture_reveal(reveal: Mapping[str, Any]) -> OutcomeObservation:
    """Fixture path still requires sealed outcome + admission; never free-form verified."""

    admission = str(reveal.get("admission_status") or "")
    if admission not in {"ACCEPTED", "DUPLICATE"}:
        raise SettleAllFromRevealError(
            "REVEAL_NOT_ACCEPTED",
            f"fixture admission_status={admission!r}",
        )
    if reveal.get("fixture_isolated_mechanics") is not True and str(
        reveal.get("schema_version")
    ) != FIXTURE_REVEAL_SCHEMA:
        raise SettleAllFromRevealError(
            "FIXTURE_MARKER_REQUIRED",
            "isolated fixture reveal must set fixture_isolated_mechanics=true "
            f"or schema_version={FIXTURE_REVEAL_SCHEMA}",
        )
    raw_outcome = reveal.get("outcome")
    if not isinstance(raw_outcome, Mapping):
        raise SettleAllFromRevealError("REVEAL_OUTCOME_MISSING", "reveal.outcome object required")
    # Reject caller stuffing verified without outcome identity seal.
    if "actual_special_number" in reveal and "outcome" in reveal:
        special = reveal.get("actual_special_number")
        try:
            if int(special) != int(raw_outcome.get("actual_special_number")):  # type: ignore[arg-type]
                raise SettleAllFromRevealError(
                    "REVEAL_OUTCOME_NUMBER_DRIFT",
                    f"reveal.actual_special_number={special!r}",
                )
        except (TypeError, ValueError) as exc:
            raise SettleAllFromRevealError("REVEAL_OUTCOME_NUMBER_DRIFT", str(exc)) from exc
    try:
        outcome = OutcomeObservation.model_validate(dict(raw_outcome))
    except Exception as exc:
        raise SettleAllFromRevealError("REVEAL_OUTCOME_INVALID", str(exc)) from exc
    if outcome.result_hash is None:
        outcome = outcome.with_hash()
    else:
        try:
            outcome.require_valid_result_hash()
        except ValueError as exc:
            raise SettleAllFromRevealError("REVEAL_OUTCOME_HASH_MISMATCH", str(exc)) from exc
    if not outcome.verified:
        raise SettleAllFromRevealError("REVEAL_NOT_ACCEPTED", "fixture outcome.verified is false")
    return outcome


def _intent_payload(
    *,
    freeze_set: FrozenDecisionSet,
    ticket_enum: Mapping[str, Any],
    reveal_content_hash: str,
    outcome: OutcomeObservation,
    settlement_set_ref: str,
    portfolio_ref: str,
) -> dict[str, Any]:
    return {
        "schema_version": INTENT_SCHEMA,
        "adapter_marker": ADAPTER_MARKER,
        "object_model": OBJECT_MODEL,
        "freeze_set_ref": freeze_set.freeze_set_ref,
        "freeze_set_hash": freeze_set.content_hash,
        "target_ref": freeze_set.target_ref,
        "eligible_frozen_count": freeze_set.eligible_frozen_count,
        "decision_refs": list(ticket_enum["decision_refs"]),
        "policy_refs": list(ticket_enum["policy_refs"]),
        "protocol_pin_ref": ticket_enum["protocol_pin_ref"],
        "protocol_pin_sha256": ticket_enum["protocol_pin_sha256"],
        "reveal_content_hash": reveal_content_hash,
        "outcome_ref": outcome.outcome_ref,
        "outcome_result_hash": outcome.result_hash,
        "outcome_source_ref": outcome.source_ref,
        "actual_special_number": outcome.actual_special_number,
        "settlement_set_ref": settlement_set_ref,
        "portfolio_ref": portfolio_ref,
    }


def _build_sealed_receipt(
    *,
    settlement_root: Path,
    freeze_set: FrozenDecisionSet,
    ticket_enum: Mapping[str, Any],
    reveal_content_hash: str,
    outcome: OutcomeObservation,
    result: SettleAllResult,
    reveal_meta: Mapping[str, Any],
    action_bundles_digest: str,
) -> dict[str, Any]:
    """Build durable sealed receipt bound to settlement-set and action-bundles digests.

    Invocation-local flags (``settlement_written``, ``idempotent_replay``) are
    intentionally excluded from the sealed body / content_hash so concurrent
    same-identity callers produce byte-stable artifacts.
    """

    settlement = result.settlement_set
    conservation_ok = (
        settlement.missing_or_duplicate_count == 0
        and settlement.eligible_frozen_count == freeze_set.eligible_frozen_count
        and settlement.settled_exactly_once_count + settlement.void_with_reason_count
        == settlement.eligible_frozen_count
        and settlement.closed is True
        and len(settlement.score_rows) == freeze_set.eligible_frozen_count
    )
    if not conservation_ok:
        raise SettleAllFromRevealError(
            "CONSERVATION_FAILED",
            "settlement set does not conserve every frozen ticket exactly once",
        )
    action_settled = sum(1 for row in settlement.score_rows if row.disposition == "SETTLED")
    no_action_settled = sum(
        1 for row in settlement.score_rows if row.disposition == "NO_ACTION_SETTLED"
    )
    next_consumer = (
        "Owner ClaimGrade recompute / research-feedback material binding "
        "(manual; not auto-started by this consumer)"
    )
    formal_settled = reveal_meta.get("formal_object_settled")
    if reveal_meta.get("fixture_isolated_mechanics"):
        formal_settled = False
        next_consumer = (
            "ISOLATED FIXTURE ONLY — real formal FrozenDecisionSet remains "
            "FROZEN_AWAITING_VERIFIED_OUTCOME until Owner applies an authoritative "
            "non-fixture reveal; do not claim formal 2026209 settled"
        )
    bundle_count = len(result.action_bundles)
    digest = _require_hex64(action_bundles_digest, "action_bundles_digest")
    receipt: dict[str, Any] = {
        "ok": True,
        "schema_version": RECEIPT_SCHEMA,
        "adapter_marker": ADAPTER_MARKER,
        "command": "prospective settle-all-from-reveal",
        "object_model": OBJECT_MODEL,
        "not_single_seat_shadow_portfolio": True,
        "settlement_root": str(settlement_root),
        "freeze_set_ref": freeze_set.freeze_set_ref,
        "freeze_set_hash": freeze_set.content_hash,
        "target_ref": freeze_set.target_ref,
        "target_open_time": _iso(freeze_set.target_open_time),
        "eligible_frozen_count": freeze_set.eligible_frozen_count,
        "ticket_decision_refs": list(ticket_enum["decision_refs"]),
        "ticket_policy_refs": list(ticket_enum["policy_refs"]),
        "roles": list(ticket_enum["roles"]),
        "protocol_pin_ref": ticket_enum["protocol_pin_ref"],
        "protocol_pin_sha256": ticket_enum["protocol_pin_sha256"],
        "reveal_content_hash": reveal_content_hash,
        "outcome_ref": outcome.outcome_ref,
        "outcome_result_hash": outcome.result_hash,
        "outcome_source_ref": outcome.source_ref,
        "actual_special_number": outcome.actual_special_number,
        "observed_at": _iso(outcome.observed_at),
        "settlement_set_ref": settlement.settlement_set_ref,
        "settlement_set_hash": settlement.content_hash,
        "settled_exactly_once_count": settlement.settled_exactly_once_count,
        "void_with_reason_count": settlement.void_with_reason_count,
        "missing_or_duplicate_count": settlement.missing_or_duplicate_count,
        "action_settled_count": action_settled,
        "no_action_settled_count": no_action_settled,
        "action_bundle_count": bundle_count,
        "action_bundles_digest": digest,
        "conservation_ok": True,
        "equality_evidence": {
            "score_rows": len(settlement.score_rows),
            "eligible_frozen_count": settlement.eligible_frozen_count,
            "settled_plus_void": settlement.settled_exactly_once_count
            + settlement.void_with_reason_count,
            "missing_or_duplicate_count": settlement.missing_or_duplicate_count,
            "closed": settlement.closed,
            "freeze_set_hash_bound": settlement.freeze_set_hash == freeze_set.content_hash,
            "outcome_hash_bound": settlement.outcome_hash == outcome.result_hash,
            "action_bundles_digest_bound": digest,
            "action_bundle_count_bound": bundle_count,
        },
        "role_coverage": [
            {
                "role": item.role.value,
                "frozen_count": item.frozen_count,
                "settled_or_void_count": item.settled_or_void_count,
            }
            for item in settlement.role_coverage
        ],
        "evidence_class": reveal_meta.get("evidence_class"),
        "fixture_isolated_mechanics": bool(reveal_meta.get("fixture_isolated_mechanics")),
        "formal_object_settled": formal_settled,
        "next_true_consumer": next_consumer,
        **_honest_flags(),
    }
    receipt["content_hash"] = canonical_sha256(
        {k: v for k, v in receipt.items() if k != "content_hash"}
    )
    return receipt


def _with_response_fields(
    sealed_receipt: Mapping[str, Any],
    *,
    idempotent_replay: bool,
    settlement_written: bool,
) -> dict[str, Any]:
    """Attach invocation-local fields outside sealed content_hash identity."""

    response = dict(sealed_receipt)
    response["idempotent_replay"] = bool(idempotent_replay)
    response["settlement_written"] = bool(settlement_written)
    return response


def _receipt_binding_ok(
    receipt: Mapping[str, Any],
    *,
    settlement_set_hash: str,
    action_bundles_digest: str,
    action_bundle_count: int,
) -> bool:
    """True only when receipt binds settlement-set identity and bundles digest/count."""

    if receipt.get("settlement_set_hash") != settlement_set_hash:
        return False
    if receipt.get("action_bundles_digest") != action_bundles_digest:
        return False
    try:
        if int(receipt.get("action_bundle_count")) != int(action_bundle_count):
            return False
    except (TypeError, ValueError):
        return False
    embedded = receipt.get("content_hash")
    if not isinstance(embedded, str) or not embedded:
        return False
    body = {
        k: v
        for k, v in receipt.items()
        if k != "content_hash" and k not in _RECEIPT_RESPONSE_ONLY_KEYS
    }
    return embedded == canonical_sha256(body)


def _load_existing_settlement(
    settlement_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, Any | None]:
    intent_path = settlement_root / _ARTIFACT_INTENT
    settlement_path = settlement_root / _ARTIFACT_SETTLEMENT_SET
    receipt_path = settlement_root / _ARTIFACT_RECEIPT
    bundles_path = settlement_root / _ARTIFACT_BUNDLES
    intent = _read_json(intent_path) if intent_path.is_file() else None
    settlement = _read_json(settlement_path) if settlement_path.is_file() else None
    receipt = _read_json(receipt_path) if receipt_path.is_file() else None
    bundles = _read_json(bundles_path) if bundles_path.is_file() else None
    return intent, settlement, receipt, bundles


def _assert_durable_commit_set_present(settlement_root: Path) -> None:
    """Fail closed if the durable commit triad is incomplete."""

    missing = [
        name
        for name in (_ARTIFACT_SETTLEMENT_SET, _ARTIFACT_BUNDLES, _ARTIFACT_RECEIPT)
        if not (settlement_root / name).is_file()
    ]
    if missing:
        raise SettleAllFromRevealError(
            "PARTIAL_DURABLE_STATE",
            f"durable commit set incomplete; missing={missing}",
        )


def _heal_or_verify_bundles(
    *,
    settlement_root: Path,
    expected_bundles: list[Any],
    existing_bundles: Any | None,
) -> str:
    """Ensure action bundles match recompute; exclusive-heal if missing only."""

    expected_digest = _bundles_digest(expected_bundles)
    bundles_path = settlement_root / _ARTIFACT_BUNDLES
    if existing_bundles is None:
        _write_exclusive_json(bundles_path, expected_bundles)
        # Re-read path after exclusive write (another concurrent healer may have won).
        on_disk = _read_json(bundles_path)
        if on_disk != expected_bundles:
            raise SettleAllFromRevealError(
                "BUNDLES_RECOVERY_DIVERGENT",
                "healed/existing action bundles differ from deterministic recompute",
            )
        return expected_digest
    if not isinstance(existing_bundles, list):
        raise SettleAllFromRevealError(
            "BUNDLES_PAYLOAD_INVALID",
            "action_settlement_bundles.v1.json must be a JSON array",
        )
    if existing_bundles != expected_bundles:
        raise SettleAllFromRevealError(
            "BUNDLES_RECOVERY_DIVERGENT",
            "existing action bundles differ from deterministic recompute",
        )
    # Byte-level seal check when file already present.
    if bundles_path.is_file() and bundles_path.read_bytes() != _json_bytes(expected_bundles):
        raise SettleAllFromRevealError(
            "BUNDLES_RECOVERY_DIVERGENT",
            "existing action bundles bytes differ from deterministic recompute",
        )
    return expected_digest


def _heal_or_verify_receipt(
    *,
    settlement_root: Path,
    expected_receipt: Mapping[str, Any],
    existing_receipt: Mapping[str, Any] | None,
    settlement_set_hash: str,
    action_bundles_digest: str,
    action_bundle_count: int,
) -> dict[str, Any]:
    """Ensure sealed receipt exists and binds settlement + bundles; heal/replace safely."""

    receipt_path = settlement_root / _ARTIFACT_RECEIPT
    expected = dict(expected_receipt)

    if existing_receipt is None:
        _write_exclusive_json(receipt_path, expected)
        on_disk = _read_json(receipt_path)
        # Concurrent writer may have sealed first; accept only if sealed identity matches.
        if not _receipt_binding_ok(
            on_disk,
            settlement_set_hash=settlement_set_hash,
            action_bundles_digest=action_bundles_digest,
            action_bundle_count=action_bundle_count,
        ):
            raise SettleAllFromRevealError(
                "RECEIPT_BINDING_MISMATCH",
                "on-disk receipt after heal does not bind settlement_set + action_bundles",
            )
        if on_disk.get("content_hash") != expected.get("content_hash"):
            # Same binding but different sealed body is not an identical recovery transaction.
            raise SettleAllFromRevealError(
                "SETTLEMENT_CAS_CONFLICT",
                f"path={receipt_path} already sealed with different bytes",
            )
        return dict(on_disk)

    if _receipt_binding_ok(
        existing_receipt,
        settlement_set_hash=settlement_set_hash,
        action_bundles_digest=action_bundles_digest,
        action_bundle_count=action_bundle_count,
    ):
        # Bound receipt: sealed body must match expected deterministic recovery payload.
        if existing_receipt.get("content_hash") == expected.get("content_hash"):
            return dict(existing_receipt)
        # Bound to same digests but different sealed fields → fail closed (not silent rewrite).
        raise SettleAllFromRevealError(
            "SETTLEMENT_CAS_CONFLICT",
            f"path={receipt_path} already sealed with different bytes",
        )

    # Forged / unbound / pre-binding-era receipt: replace only under proven recovery identity.
    if expected.get("settlement_set_hash") != settlement_set_hash:
        raise SettleAllFromRevealError(
            "RECEIPT_RECOVERY_INCONSISTENT",
            "expected receipt settlement_set_hash does not match sealed settlement",
        )
    if expected.get("action_bundles_digest") != action_bundles_digest:
        raise SettleAllFromRevealError(
            "RECEIPT_RECOVERY_INCONSISTENT",
            "expected receipt action_bundles_digest does not match sealed bundles",
        )
    _atomic_replace_json(receipt_path, expected)
    on_disk = _read_json(receipt_path)
    if not _receipt_binding_ok(
        on_disk,
        settlement_set_hash=settlement_set_hash,
        action_bundles_digest=action_bundles_digest,
        action_bundle_count=action_bundle_count,
    ):
        raise SettleAllFromRevealError(
            "RECEIPT_BINDING_MISMATCH",
            "replaced receipt still fails settlement_set + action_bundles binding",
        )
    return dict(on_disk)


def _recover_existing_settlement(
    *,
    settlement_root: Path,
    freeze_set: FrozenDecisionSet,
    ticket_enum: Mapping[str, Any],
    reveal_hash: str,
    outcome: OutcomeObservation,
    reveal_meta: Mapping[str, Any],
    existing_settlement: Mapping[str, Any],
    existing_bundles: Any | None,
    existing_receipt: Mapping[str, Any] | None,
    set_ref: str,
    port_ref: str,
    occurred_at: datetime | None,
) -> dict[str, Any]:
    """Deterministic heal/verify of durable commit set after settlement_set exists."""

    if existing_settlement.get("freeze_set_hash") != freeze_set.content_hash:
        raise SettleAllFromRevealError(
            "FREEZE_CHANGED_AFTER_PARTIAL",
            f"settled freeze={existing_settlement.get('freeze_set_hash')!r}",
        )
    if existing_settlement.get("outcome_hash") != outcome.result_hash:
        raise SettleAllFromRevealError(
            "REVEAL_CHANGED_AFTER_PARTIAL",
            f"settled outcome={existing_settlement.get('outcome_hash')!r}",
        )
    if int(existing_settlement.get("missing_or_duplicate_count", 1)) != 0:
        raise SettleAllFromRevealError(
            "EXISTING_SETTLEMENT_NOT_CONSERVED",
            "prior settlement_set fails conservation",
        )

    from xinao.science.portfolio import SettlementSet

    sealed = SettlementSet.model_validate(dict(existing_settlement))
    recompute = settle_all(
        freeze_set=freeze_set,
        outcome=outcome,
        settlement_set_ref=str(existing_settlement.get("settlement_set_ref") or set_ref),
        portfolio_ref=port_ref,
        occurred_at=occurred_at or outcome.observed_at,
    )
    if recompute.settlement_set.content_hash != sealed.content_hash:
        raise SettleAllFromRevealError(
            "SETTLEMENT_REPLAY_DRIFT",
            f"disk={sealed.content_hash} recompute={recompute.settlement_set.content_hash}",
        )

    expected_bundles = [bundle.model_dump(mode="json") for bundle in recompute.action_bundles]
    action_bundles_digest = _heal_or_verify_bundles(
        settlement_root=settlement_root,
        expected_bundles=expected_bundles,
        existing_bundles=existing_bundles,
    )
    sealed_receipt = _build_sealed_receipt(
        settlement_root=settlement_root,
        freeze_set=freeze_set,
        ticket_enum=ticket_enum,
        reveal_content_hash=reveal_hash,
        outcome=outcome,
        result=recompute,
        reveal_meta=reveal_meta,
        action_bundles_digest=action_bundles_digest,
    )
    durable_receipt = _heal_or_verify_receipt(
        settlement_root=settlement_root,
        expected_receipt=sealed_receipt,
        existing_receipt=existing_receipt,
        settlement_set_hash=str(sealed.content_hash),
        action_bundles_digest=action_bundles_digest,
        action_bundle_count=len(recompute.action_bundles),
    )
    _assert_durable_commit_set_present(settlement_root)
    return _with_response_fields(
        durable_receipt,
        idempotent_replay=True,
        settlement_written=False,
    )


def apply_settle_all_from_reveal(
    *,
    settlement_root: Path,
    freeze_set_path: Path,
    expected_freeze_set_hash: str,
    reveal_artifact: Path | None = None,
    authority_root: Path | None = None,
    reveal_content_hash: str | None = None,
    settlement_set_ref: str | None = None,
    portfolio_ref: str | None = None,
    occurred_at: datetime | None = None,
    **forbidden_kwargs: Any,
) -> dict[str, Any]:
    """Settle every FrozenDecisionSet ticket exactly once from one sealed reveal.

    Inputs:
      - sealed freeze set path + expected content hash pin
      - independently authored reveal (authority CAS pin **or** sealed reveal artifact)

    Fail-closed on missing/extra/duplicate tickets, wrong target/protocol, altered
    freeze hash, partial/subset settlement attempts, caller outcome override, and
    reveal/freeze identity change after partial progress. Durable commit set is
    ``{settlement_set, action_settlement_bundles, multipolicy_settle_all_receipt}``;
    crash retry after ``settlement_set`` reconstructs/verifies/heals missing
    siblings or fails closed — never returns ``ok`` for an incomplete durable set.
    Deterministic replay of the same identity does not double-post.
    """

    reject_settle_all_forbidden_kwargs(forbidden_kwargs)
    if forbidden_kwargs:
        raise SettleAllFromRevealError(
            "UNKNOWN_SETTLE_ALL_KWARG",
            f"unknown={sorted(forbidden_kwargs)}",
        )

    if (reveal_artifact is None) == (authority_root is None and reveal_content_hash is None):
        # Exactly one reveal channel: artifact XOR authority pin.
        if reveal_artifact is None and authority_root is None:
            raise SettleAllFromRevealError(
                "REVEAL_SOURCE_REQUIRED",
                "provide --reveal-artifact or (--authority-root and --reveal-content-hash)",
            )
    if reveal_artifact is not None and (
        authority_root is not None or reveal_content_hash is not None
    ):
        raise SettleAllFromRevealError(
            "REVEAL_SOURCE_AMBIGUOUS",
            "use either reveal-artifact or authority-root+reveal-content-hash, not both",
        )
    if authority_root is not None and reveal_content_hash is None:
        raise SettleAllFromRevealError(
            "REVEAL_HASH_REQUIRED",
            "authority-root settle-all requires reveal-content-hash pin",
        )
    if authority_root is None and reveal_content_hash is not None:
        raise SettleAllFromRevealError(
            "AUTHORITY_ROOT_REQUIRED",
            "reveal-content-hash requires authority-root",
        )

    root = Path(settlement_root)
    root.mkdir(parents=True, exist_ok=True)

    freeze_set = load_sealed_freeze_set(
        freeze_set_path=freeze_set_path,
        expected_freeze_set_hash=expected_freeze_set_hash,
    )
    ticket_enum = enumerate_expected_tickets(freeze_set)

    if reveal_artifact is not None:
        reveal = load_reveal_artifact(reveal_artifact)
        body = {k: v for k, v in reveal.items() if k != "content_hash"}
        reveal_hash = str(reveal.get("content_hash") or canonical_sha256(body))
        if reveal.get("content_hash") and str(reveal["content_hash"]) != reveal_hash:
            raise SettleAllFromRevealError("REVEAL_ARTIFACT_HASH_ALTERED", reveal_hash)
    else:
        assert authority_root is not None and reveal_content_hash is not None
        reveal, reveal_hash = load_authority_reveal(
            authority_root=authority_root,
            reveal_content_hash=reveal_content_hash,
        )

    outcome, reveal_meta = derive_outcome_from_multipolicy_reveal(reveal, freeze_set=freeze_set)
    assert outcome.result_hash is not None

    set_ref = settlement_set_ref or (
        f"settlement-set/settle-all/{freeze_set.freeze_set_ref}/{outcome.result_hash[:16]}"
    )
    port_ref = portfolio_ref or f"shadow-portfolio/multipolicy/{freeze_set.freeze_set_ref}"

    intent = _intent_payload(
        freeze_set=freeze_set,
        ticket_enum=ticket_enum,
        reveal_content_hash=reveal_hash,
        outcome=outcome,
        settlement_set_ref=set_ref,
        portfolio_ref=port_ref,
    )

    existing_intent, existing_settlement, existing_receipt, existing_bundles = (
        _load_existing_settlement(root)
    )

    if existing_intent is not None:
        for key in (
            "freeze_set_hash",
            "reveal_content_hash",
            "outcome_result_hash",
            "decision_refs",
        ):
            if existing_intent.get(key) != intent.get(key):
                code = {
                    "freeze_set_hash": "FREEZE_CHANGED_AFTER_PARTIAL",
                    "reveal_content_hash": "REVEAL_CHANGED_AFTER_PARTIAL",
                    "outcome_result_hash": "REVEAL_CHANGED_AFTER_PARTIAL",
                    "decision_refs": "TICKET_SET_CHANGED_AFTER_PARTIAL",
                }[key]
                raise SettleAllFromRevealError(
                    code,
                    f"intent.{key}={existing_intent.get(key)!r} current={intent.get(key)!r}",
                )

    if existing_settlement is not None:
        return _recover_existing_settlement(
            settlement_root=root,
            freeze_set=freeze_set,
            ticket_enum=ticket_enum,
            reveal_hash=reveal_hash,
            outcome=outcome,
            reveal_meta=reveal_meta,
            existing_settlement=existing_settlement,
            existing_bundles=existing_bundles,
            existing_receipt=existing_receipt,
            set_ref=set_ref,
            port_ref=port_ref,
            occurred_at=occurred_at,
        )

    # Fresh settlement path: seal intent first (partial-progress identity).
    _write_exclusive_json(root / _ARTIFACT_INTENT, intent)
    _write_exclusive_json(
        root / _ARTIFACT_FREEZE_COPY,
        freeze_set.model_dump(mode="json"),
    )
    _write_exclusive_json(root / _ARTIFACT_REVEAL_COPY, dict(reveal))
    _write_exclusive_json(
        root / _ARTIFACT_OUTCOME,
        outcome.model_dump(mode="json"),
    )

    when = occurred_at or outcome.observed_at
    if when.tzinfo is None or when.utcoffset() is None:
        raise SettleAllFromRevealError("TIMESTAMP_NOT_AWARE", "occurred_at must be timezone-aware")
    if when < outcome.observed_at:
        raise SettleAllFromRevealError(
            "SETTLEMENT_BEFORE_OUTCOME",
            "occurred_at precedes outcome.observed_at",
        )

    try:
        result = settle_all(
            freeze_set=freeze_set,
            outcome=outcome,
            settlement_set_ref=set_ref,
            portfolio_ref=port_ref,
            occurred_at=when,
        )
    except ValueError as exc:
        raise SettleAllFromRevealError("SETTLE_ALL_REJECTED", str(exc)) from exc

    # Conservation / exact ticket set equality before durable commit.
    settled_refs = tuple(sorted(row.ticket_ref for row in result.settlement_set.score_rows))
    if settled_refs != tuple(ticket_enum["decision_refs"]):
        raise SettleAllFromRevealError(
            "TICKET_SET_NOT_EXACT",
            f"expected={ticket_enum['decision_refs']} settled={settled_refs}",
        )
    if result.settlement_set.missing_or_duplicate_count != 0:
        raise SettleAllFromRevealError("MISSING_OR_DUPLICATE_TICKETS", "library conservation failed")
    if result.settlement_set.eligible_frozen_count != freeze_set.eligible_frozen_count:
        raise SettleAllFromRevealError("PARTIAL_SET_SETTLEMENT", "row count != eligible frozen")

    settlement_payload = result.settlement_set.model_dump(mode="json")
    bundles_payload = [bundle.model_dump(mode="json") for bundle in result.action_bundles]
    action_bundles_digest = _bundles_digest(bundles_payload)

    # Ordered durable commit: settlement_set → bundles → receipt (receipt last).
    # Crash after settlement_set is healed by the recovery path above.
    written_settlement = _write_exclusive_json(root / _ARTIFACT_SETTLEMENT_SET, settlement_payload)

    # If another concurrent caller already sealed settlement and raced ahead into
    # recovery, fall through to load+recover so sealed artifacts stay identical.
    if not written_settlement:
        _, sealed_settlement, sealed_receipt, sealed_bundles = _load_existing_settlement(root)
        if sealed_settlement is not None:
            return _recover_existing_settlement(
                settlement_root=root,
                freeze_set=freeze_set,
                ticket_enum=ticket_enum,
                reveal_hash=reveal_hash,
                outcome=outcome,
                reveal_meta=reveal_meta,
                existing_settlement=sealed_settlement,
                existing_bundles=sealed_bundles,
                existing_receipt=sealed_receipt,
                set_ref=set_ref,
                port_ref=port_ref,
                occurred_at=occurred_at,
            )

    _write_exclusive_json(root / _ARTIFACT_BUNDLES, bundles_payload)

    sealed_receipt = _build_sealed_receipt(
        settlement_root=root,
        freeze_set=freeze_set,
        ticket_enum=ticket_enum,
        reveal_content_hash=reveal_hash,
        outcome=outcome,
        result=result,
        reveal_meta=reveal_meta,
        action_bundles_digest=action_bundles_digest,
    )
    _write_exclusive_json(root / _ARTIFACT_RECEIPT, sealed_receipt)
    _assert_durable_commit_set_present(root)
    return _with_response_fields(
        sealed_receipt,
        idempotent_replay=False,
        settlement_written=written_settlement,
    )


def build_isolated_reveal_fixture(
    *,
    target_ref: str,
    actual_special_number: int,
    observed_at: datetime,
    source_ref: str = "isolated-reveal-fixture.multipolicy.v1",
    outcome_ref: str | None = None,
) -> dict[str, Any]:
    """Build an explicitly isolated reveal envelope for mechanics tests only.

    Labeled so consumers cannot confuse fixture success with formal settlement.
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise SettleAllFromRevealError("TIMESTAMP_NOT_AWARE", "observed_at must be timezone-aware")
    if not (1 <= int(actual_special_number) <= 49):
        raise SettleAllFromRevealError("FIXTURE_NUMBER_INVALID", str(actual_special_number))
    oref = outcome_ref or f"outcome.fixture/{target_ref}"
    outcome = OutcomeObservation(
        outcome_ref=oref,
        source_ref=source_ref,
        target_ref=target_ref,
        actual_special_number=int(actual_special_number),
        observed_at=observed_at,
        verified=True,
    ).with_hash()
    body: dict[str, Any] = {
        "schema_version": FIXTURE_REVEAL_SCHEMA,
        "fixture_isolated_mechanics": True,
        "evidence_class": "ISOLATED_REVEAL_FIXTURE_MECHANICS",
        "formal_object_settled": False,
        "target_ref": target_ref,
        "source_id": source_ref,
        "actual_special_number": int(actual_special_number),
        "admission_status": "ACCEPTED",
        "outcome": outcome.model_dump(mode="json"),
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "settlement_written": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def assert_no_control_plane_imports() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
    hits = sorted(imported & {t.lower() for t in _FORBIDDEN_IMPORT_TOKENS})
    if hits:
        raise SettleAllFromRevealError("CONTROL_PLANE_IMPORT_FORBIDDEN", f"imports={hits}")


__all__ = [
    "ADAPTER_MARKER",
    "FIXTURE_REVEAL_SCHEMA",
    "OBJECT_MODEL",
    "RECEIPT_SCHEMA",
    "SettleAllFromRevealError",
    "apply_settle_all_from_reveal",
    "assert_no_control_plane_imports",
    "build_isolated_reveal_fixture",
    "enumerate_expected_tickets",
    "load_sealed_freeze_set",
    "reject_settle_all_forbidden_kwargs",
]
