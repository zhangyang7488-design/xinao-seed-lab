"""Production portfolio freeze -> source-proved outcome -> exhaustive settlement.

This consumer deliberately targets ``FrozenShadowEpisode`` objects under the
production shadow portfolio store.  It is not the historical multipolicy
``FrozenDecisionSet`` settlement surface.

The source ``verified`` boolean is treated as an assertion only.  Verification
is derived by re-reading the exact raw CAS bytes, parsing the pinned point
endpoint response, and binding that result to the packet, reveal, period and
frozen episode.  The current portfolio model permits one unsettled head; this
consumer nevertheless enumerates the complete store and refuses to write when
an extra or uncovered due period exists.  The existing intent-first period
settlement journal supplies crash recovery for that one formal commit.

Corrections require an explicit, independently re-verifiable reveal chain.
Already-settled accounting is never overwritten: such a correction is rejected
with a typed append-only-adjustment seam until that separate product capability
exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.prospective_source_thin import (
    MAX_HOST_HTTP_SKEW,
    POINT_TEMPLATE,
    SOURCE_ID,
    ProspectiveSourceError,
    load_packet,
    load_reveal,
    load_reveal_index,
    parse_point_payload,
    point_result_row,
    raw_object_path,
    resolve_authority_root,
)
from xinao.science.settle_from_reveal_adapter import _bind_frozen_to_authority
from xinao.settlement.shadow import OutcomeObservation
from xinao.shadow_lifecycle.consumer import settle_portfolio_period
from xinao.shadow_lifecycle.store import (
    EpisodePhase,
    StoreError,
    artifact_paths,
    derive_portfolio_head,
    detect_phase,
    load_frozen,
    load_outcome,
    load_settled,
    period_directory,
    portfolio_artifact_paths,
    resolve_root,
)

OUTCOME_EVENT_SCHEMA: Final = "xinao.production_outcome_event.v1"
SETTLE_ALL_RECEIPT_SCHEMA: Final = "xinao.production_portfolio_settle_all_receipt.v1"
ADAPTER_MARKER: Final = "XINAO_PRODUCTION_PORTFOLIO_SETTLE_ALL_V1"
_NORMAL_REVEAL_SCHEMA: Final = "xinao.prospective_reveal_capture.v1"
_CORRECTION_REVEAL_SCHEMA: Final = "xinao.prospective_reveal_correction.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PortfolioSettleAllError(ValueError):
    """Fail-closed production outcome/settle-all rejection."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PortfolioSettleAllError("OUTCOME_HASH_INVALID", f"{label} must be sha256")
    return value


def _parse_aware(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PortfolioSettleAllError("OUTCOME_TIME_INVALID", f"{label} missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PortfolioSettleAllError("OUTCOME_TIME_INVALID", f"{label}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PortfolioSettleAllError("OUTCOME_TIME_INVALID", f"{label} must be aware")
    return parsed.astimezone(UTC)


def _raw_reveal_proof(
    *,
    authority_root: Path,
    packet: Mapping[str, Any],
    reveal: Mapping[str, Any],
) -> tuple[OutcomeObservation, dict[str, Any]]:
    """Reparse source bytes; never accept reveal.outcome.verified as proof."""

    raw_ref = reveal.get("raw")
    if not isinstance(raw_ref, Mapping):
        raise PortfolioSettleAllError("OUTCOME_RAW_REF_REQUIRED", "reveal.raw object required")
    raw_sha = _require_hash(raw_ref.get("sha256"), "reveal.raw.sha256")
    expected_path = raw_object_path(authority_root, raw_sha)
    if not expected_path.is_file() or expected_path.is_symlink():
        raise PortfolioSettleAllError("OUTCOME_RAW_CAS_MISSING", raw_sha)
    raw_bytes = expected_path.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != raw_sha:
        raise PortfolioSettleAllError("OUTCOME_RAW_CAS_TAMPERED", raw_sha)
    if raw_ref.get("byte_length") != len(raw_bytes):
        raise PortfolioSettleAllError(
            "OUTCOME_RAW_LENGTH_MISMATCH",
            f"ref={raw_ref.get('byte_length')!r} actual={len(raw_bytes)}",
        )
    expect = str(packet.get("target_expect"))
    expected_url = POINT_TEMPLATE.format(expect=expect)
    if raw_ref.get("url") != expected_url or raw_ref.get("http_status") != 200:
        raise PortfolioSettleAllError(
            "OUTCOME_SOURCE_IDENTITY_MISMATCH",
            f"url={raw_ref.get('url')!r} status={raw_ref.get('http_status')!r}",
        )
    try:
        row = point_result_row(parse_point_payload(raw_bytes))
    except ProspectiveSourceError as exc:
        raise PortfolioSettleAllError("OUTCOME_RAW_PARSE_REJECTED", str(exc)) from exc
    if row.expect != expect or row.open_code is None:
        raise PortfolioSettleAllError(
            "OUTCOME_PERIOD_BINDING_MISMATCH",
            f"raw.expect={row.expect!r} packet.expect={expect!r}",
        )
    raw_open_code = tuple(int(value) for value in (reveal.get("open_code") or ()))
    if raw_open_code != row.open_code:
        raise PortfolioSettleAllError("OUTCOME_OPEN_CODE_MISMATCH", "reveal differs from raw CAS")
    special = int(row.open_code[-1])
    if int(reveal.get("actual_special_number", -1)) != special:
        raise PortfolioSettleAllError(
            "OUTCOME_SPECIAL_NUMBER_MISMATCH", "reveal differs from raw CAS"
        )

    outcome_raw = reveal.get("outcome")
    if not isinstance(outcome_raw, Mapping):
        raise PortfolioSettleAllError("OUTCOME_BODY_REQUIRED", "reveal.outcome required")
    try:
        asserted = OutcomeObservation.model_validate(dict(outcome_raw))
        asserted.require_valid_result_hash()
    except (ValueError, TypeError) as exc:
        raise PortfolioSettleAllError("OUTCOME_BODY_INVALID", str(exc)) from exc
    if asserted.source_ref != SOURCE_ID or reveal.get("source_id") != SOURCE_ID:
        raise PortfolioSettleAllError("OUTCOME_SOURCE_IDENTITY_MISMATCH", SOURCE_ID)
    if (
        asserted.target_ref != packet.get("target_ref")
        or reveal.get("target_ref") != asserted.target_ref
    ):
        raise PortfolioSettleAllError("OUTCOME_PERIOD_BINDING_MISMATCH", asserted.target_ref)
    if reveal.get("target_expect") != expect or reveal.get("packet_content_hash") != packet.get(
        "content_hash"
    ):
        raise PortfolioSettleAllError("OUTCOME_PERIOD_BINDING_MISMATCH", expect)
    if asserted.actual_special_number != special:
        raise PortfolioSettleAllError("OUTCOME_SPECIAL_NUMBER_MISMATCH", "outcome differs from raw")
    expected_outcome_ref = f"outcome.macaujc2.expect.{expect}.sha256:{raw_sha[:16]}"
    if asserted.outcome_ref != expected_outcome_ref:
        raise PortfolioSettleAllError(
            "OUTCOME_REF_SOURCE_MISMATCH",
            f"outcome_ref={asserted.outcome_ref!r} expected={expected_outcome_ref!r}",
        )

    observed_at = asserted.observed_at.astimezone(UTC)
    http_date_raw = raw_ref.get("http_date")
    try:
        raw_date_text = str(http_date_raw)
        if re.match(r"^\d{4}-\d{2}-\d{2}T", raw_date_text):
            http_date = _parse_aware(raw_date_text, "reveal.raw.http_date")
        else:
            http_date = parsedate_to_datetime(raw_date_text).astimezone(UTC)
    except (TypeError, ValueError) as exc:
        raise PortfolioSettleAllError("OUTCOME_HTTP_DATE_INVALID", str(http_date_raw)) from exc
    if abs(observed_at - http_date) > MAX_HOST_HTTP_SKEW:
        raise PortfolioSettleAllError(
            "OUTCOME_OBSERVED_AT_UNBOUND",
            f"observed_at={observed_at.isoformat()} http_date={http_date.isoformat()}",
        )
    guard = _parse_aware(packet.get("target_guard_open_time"), "target_guard_open_time")
    if row.open_time.astimezone(UTC) < guard or observed_at < guard:
        raise PortfolioSettleAllError("OUTCOME_BEFORE_TARGET_GUARD", expect)

    # Reconstruct the admitted model from raw proof.  The asserted boolean is not
    # consulted; True is now derived from the checks above.
    derived = OutcomeObservation(
        outcome_ref=asserted.outcome_ref,
        source_ref=SOURCE_ID,
        target_ref=asserted.target_ref,
        actual_special_number=special,
        observed_at=observed_at,
        verified=True,
        supersedes_outcome_ref=asserted.supersedes_outcome_ref,
    ).with_hash()
    if derived.result_hash != asserted.result_hash:
        raise PortfolioSettleAllError("OUTCOME_RESULT_HASH_MISMATCH", asserted.outcome_ref)
    return derived, {
        "source_id": SOURCE_ID,
        "endpoint_url": expected_url,
        "raw_content_hash": raw_sha,
        "raw_byte_length": len(raw_bytes),
        "http_date": http_date.isoformat().replace("+00:00", "Z"),
        "source_raw_reparsed": True,
        "caller_verified_flag_trusted": False,
    }


def _verify_reveal_event(
    *,
    authority_root: Path,
    packet: Mapping[str, Any],
    reveal_hash: str,
    seen: frozenset[str],
) -> dict[str, Any]:
    if reveal_hash in seen:
        raise PortfolioSettleAllError("OUTCOME_SUPERSESSION_CYCLE", reveal_hash)
    try:
        reveal = load_reveal(authority_root, reveal_hash)
    except ProspectiveSourceError as exc:
        raise PortfolioSettleAllError(exc.reason_code, exc.detail) from exc
    schema = reveal.get("schema_version")
    if schema not in {_NORMAL_REVEAL_SCHEMA, _CORRECTION_REVEAL_SCHEMA}:
        raise PortfolioSettleAllError("OUTCOME_REVEAL_SCHEMA_UNSUPPORTED", str(schema))
    outcome, source_identity = _raw_reveal_proof(
        authority_root=authority_root,
        packet=packet,
        reveal=reveal,
    )

    supersedes_hash = reveal.get("supersedes_reveal_content_hash")
    predecessor: dict[str, Any] | None = None
    if schema == _CORRECTION_REVEAL_SCHEMA:
        if not isinstance(supersedes_hash, str) or outcome.supersedes_outcome_ref is None:
            raise PortfolioSettleAllError(
                "OUTCOME_CORRECTION_SUPERSESSION_REQUIRED",
                "correction requires reveal hash and outcome_ref predecessor",
            )
        supersedes_hash = _require_hash(supersedes_hash, "supersedes_reveal_content_hash")
        predecessor = _verify_reveal_event(
            authority_root=authority_root,
            packet=packet,
            reveal_hash=supersedes_hash,
            seen=seen | {reveal_hash},
        )
        previous_outcome = OutcomeObservation.model_validate(predecessor["outcome"])
        if outcome.supersedes_outcome_ref != previous_outcome.outcome_ref:
            raise PortfolioSettleAllError(
                "OUTCOME_SUPERSESSION_REF_MISMATCH", outcome.supersedes_outcome_ref
            )
        if (
            outcome.source_ref != previous_outcome.source_ref
            or outcome.target_ref != previous_outcome.target_ref
        ):
            raise PortfolioSettleAllError("OUTCOME_SUPERSESSION_DOMAIN_MISMATCH", reveal_hash)
        if outcome.observed_at <= previous_outcome.observed_at:
            raise PortfolioSettleAllError("OUTCOME_SUPERSESSION_TIME_INVALID", reveal_hash)
        if outcome.result_hash == previous_outcome.result_hash:
            raise PortfolioSettleAllError("OUTCOME_REDUNDANT_CORRECTION", reveal_hash)
        if reveal.get("admission_status") != "CORRECTION_ACCEPTED":
            raise PortfolioSettleAllError("OUTCOME_CORRECTION_NOT_ACCEPTED", reveal_hash)
        # The current source producer never emits a correction event or durable
        # append-only correction index.  A caller-authored envelope plus raw bytes
        # cannot invent that missing source authority, even when its internal
        # chain is self-consistent.  Keep the verified predecessor checks above so
        # malformed claims receive the narrower rejection, then fail closed here.
        raise PortfolioSettleAllError(
            "OUTCOME_CORRECTION_REQUIRES_REGISTERED_APPEND_ONLY_SOURCE_AND_ACCOUNT_ADJUSTMENT",
            "current macaujc2 reveal producer has no correction verb/index; "
            "formal history is immutable",
        )
    else:
        if supersedes_hash is not None or outcome.supersedes_outcome_ref is not None:
            raise PortfolioSettleAllError(
                "OUTCOME_CORRECTION_SCHEMA_REQUIRED", "supersession on normal reveal"
            )
        if reveal.get("admission_status") not in {"ACCEPTED", "DUPLICATE"}:
            raise PortfolioSettleAllError("OUTCOME_REVEAL_NOT_ACCEPTED", reveal_hash)

    body: dict[str, Any] = {
        "schema_version": OUTCOME_EVENT_SCHEMA,
        "adapter_marker": ADAPTER_MARKER,
        "reveal_content_hash": reveal_hash,
        "source_identity": source_identity,
        "period_binding": {
            "packet_content_hash": packet["content_hash"],
            "target_ref": packet["target_ref"],
            "target_expect": packet["target_expect"],
        },
        "observed_at": outcome.observed_at.isoformat().replace("+00:00", "Z"),
        "outcome": outcome.model_dump(mode="json"),
        "is_correction": schema == _CORRECTION_REVEAL_SCHEMA,
        "correction_supported": False,
        "correction_policy": "registered_append_only_source_and_account_adjustment_required",
        "supersedes_reveal_content_hash": supersedes_hash,
        "supersedes_outcome_event_hash": predecessor.get("content_hash") if predecessor else None,
        "reveal_admission_status": reveal.get("admission_status"),
        "verification_basis": "reparsed_pinned_source_raw_cas",
        "caller_verified_flag_trusted": False,
        "source_raw_reparsed": True,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    return body


def load_verified_outcome_event(
    *,
    authority_root: Path,
    packet_content_hash: str,
    reveal_content_hash: str | None = None,
) -> dict[str, Any]:
    """Load the current reveal and independently verify its raw source bytes."""

    packet_hash = _require_hash(packet_content_hash, "packet_content_hash")
    root = resolve_authority_root(authority_root)
    try:
        packet = load_packet(root, packet_hash)
        index = load_reveal_index(root, str(packet["target_expect"]))
    except ProspectiveSourceError as exc:
        raise PortfolioSettleAllError(exc.reason_code, exc.detail) from exc
    current_hash = str(index["reveal_content_hash"])
    if reveal_content_hash is not None:
        pinned = _require_hash(reveal_content_hash, "reveal_content_hash")
        if pinned != current_hash:
            raise PortfolioSettleAllError(
                "OUTCOME_REVEAL_HEAD_MISMATCH", f"index={current_hash} pin={pinned}"
            )
    event = _verify_reveal_event(
        authority_root=root,
        packet=packet,
        reveal_hash=current_hash,
        seen=frozenset(),
    )
    outcome = event["outcome"]
    if index.get("result_hash") != outcome.get("result_hash"):
        raise PortfolioSettleAllError("OUTCOME_REVEAL_INDEX_MISMATCH", current_hash)
    if index.get("outcome_ref") != outcome.get("outcome_ref"):
        raise PortfolioSettleAllError("OUTCOME_REVEAL_INDEX_MISMATCH", current_hash)
    if index.get("admission_status") != event.get("reveal_admission_status"):
        raise PortfolioSettleAllError("OUTCOME_REVEAL_INDEX_MISMATCH", current_hash)
    return event


def _period_indexes(portfolio_root: Path) -> tuple[int, ...]:
    periods = portfolio_artifact_paths(portfolio_root)["periods"]
    if not periods.is_dir() or periods.is_symlink():
        raise PortfolioSettleAllError("PORTFOLIO_STORE_INVALID", "periods directory invalid")
    indexes: list[int] = []
    for child in periods.iterdir():
        if child.is_symlink() or not child.is_dir() or not re.fullmatch(r"[0-9]{6}", child.name):
            raise PortfolioSettleAllError("PORTFOLIO_STORE_INVALID", f"foreign period {child.name}")
        indexes.append(int(child.name))
    return tuple(sorted(indexes))


def _inventory(portfolio_root: Path, outcome: OutcomeObservation) -> dict[str, Any]:
    try:
        head = derive_portfolio_head(portfolio_root)
        indexes = _period_indexes(portfolio_root)
    except (StoreError, ValueError, OSError) as exc:
        raise PortfolioSettleAllError("PORTFOLIO_STORE_INVALID", str(exc)) from exc
    due: list[dict[str, Any]] = []
    settled: list[dict[str, Any]] = []
    for index in indexes:
        root = period_directory(portfolio_root, index)
        try:
            phase = detect_phase(root)
            frozen = (
                load_frozen(root)
                if phase not in {EpisodePhase.MISSING, EpisodePhase.INIT}
                else None
            )
        except (StoreError, ValueError, OSError) as exc:
            raise PortfolioSettleAllError("PORTFOLIO_STORE_INVALID", str(exc)) from exc
        if frozen is None:
            continue
        item = {
            "period_index": index,
            "period_root": str(root),
            "phase": phase.value,
            "target_ref": frozen.target_ref,
            "frozen_episode_hash": frozen.content_hash,
            "episode_ref": frozen.episode_ref,
            "account_identity": frozen.account_decision.identity.value,
            "account_ticket_hash": (
                frozen.bound_account_ticket.content_hash
                if frozen.bound_account_ticket is not None
                else frozen.account_decision.frozen_decision_hash
            ),
        }
        if phase in {EpisodePhase.FROZEN, EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED}:
            due.append(item)
        elif phase == EpisodePhase.SETTLED:
            period_outcome = load_outcome(root)
            item["outcome_result_hash"] = period_outcome.result_hash
            item["outcome_ref"] = period_outcome.outcome_ref
            item["settled_episode_hash"] = load_settled(root).content_hash
            settled.append(item)
    inventory_body = {
        "portfolio_root": str(portfolio_root),
        "head_period_index": head.period_index,
        "head_phase": head.phase.value,
        "period_count": len(indexes),
        "due": due,
        "settled": settled,
        "outcome_target_ref": outcome.target_ref,
    }
    inventory_body["content_hash"] = canonical_sha256(inventory_body)
    return inventory_body


def _write_event_evidence(
    *,
    portfolio_root: Path,
    event: Mapping[str, Any],
    outcome: OutcomeObservation,
) -> dict[str, str]:
    event_hash = _require_hash(event.get("content_hash"), "outcome_event.content_hash")
    computed = canonical_sha256(
        {key: value for key, value in event.items() if key != "content_hash"}
    )
    if computed != event_hash:
        raise PortfolioSettleAllError("OUTCOME_EVENT_HASH_MISMATCH", event_hash)
    event_bytes = (json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    base = resolve_root(portfolio_root)
    event_path = (
        base
        / "objects"
        / "production_outcome_event"
        / "sha256"
        / event_hash[:2]
        / f"{event_hash}.json"
    )
    event_path.parent.mkdir(parents=True, exist_ok=True)
    if event_path.is_file():
        if event_path.read_bytes() != event_bytes:
            raise PortfolioSettleAllError("OUTCOME_EVENT_CAS_CONFLICT", str(event_path))
    else:
        try:
            with event_path.open("xb") as stream:
                stream.write(event_bytes)
                stream.flush()
        except FileExistsError as exc:
            if event_path.read_bytes() != event_bytes:
                raise PortfolioSettleAllError(
                    "OUTCOME_EVENT_CAS_CONFLICT", str(event_path)
                ) from exc
    outcome_path = base / "generated" / f"production_outcome.{event_hash}.json"
    outcome_bytes = (
        json.dumps(outcome.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    if outcome_path.is_file():
        if outcome_path.read_bytes() != outcome_bytes:
            raise PortfolioSettleAllError("OUTCOME_EVENT_CAS_CONFLICT", str(outcome_path))
    else:
        try:
            with outcome_path.open("xb") as stream:
                stream.write(outcome_bytes)
                stream.flush()
        except FileExistsError as exc:
            if outcome_path.read_bytes() != outcome_bytes:
                raise PortfolioSettleAllError(
                    "OUTCOME_EVENT_CAS_CONFLICT", str(outcome_path)
                ) from exc
    return {"event_path": str(event_path), "outcome_path": str(outcome_path)}


def _write_receipt(
    *,
    portfolio_root: Path,
    event: Mapping[str, Any],
    inventory_hash: str,
    inventory_basis: str,
    recovered_after_formal_commit: bool,
    periods: list[dict[str, Any]],
) -> dict[str, str]:
    body: dict[str, Any] = {
        "schema_version": SETTLE_ALL_RECEIPT_SCHEMA,
        "adapter_marker": ADAPTER_MARKER,
        "portfolio_root": str(portfolio_root),
        "outcome_event_hash": event["content_hash"],
        "inventory_hash": inventory_hash,
        "inventory_basis": inventory_basis,
        "settled_periods": periods,
        "enumerated_due_count": len(periods),
        "settled_count": len(periods),
        "unsettled_due_count": 0,
        "settle_coverage": "1.0000",
        "formal_object_model": "production_FrozenShadowEpisode",
        "source_execution_classification": "UNATTESTED_BY_LIBRARY",
        "prospective_source_attested": False,
        "synthetic": None,
        "recovered_after_formal_commit": recovered_after_formal_commit,
        "completion_claim_allowed": False,
    }
    body["content_hash"] = canonical_sha256(body)
    digest = body["content_hash"]
    path = (
        resolve_root(portfolio_root)
        / "objects"
        / "portfolio_settle_all_receipt"
        / "sha256"
        / digest[:2]
        / f"{digest}.json"
    )
    raw = (json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.read_bytes() != raw:
            raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_CONFLICT", str(path))
    else:
        try:
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
        except FileExistsError as exc:
            if path.read_bytes() != raw:
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_CONFLICT", str(path)) from exc
    return {"receipt_path": str(path), "receipt_content_hash": digest}


def _period_result_from_settled(
    *,
    portfolio_root: Path,
    item: Mapping[str, Any],
    outcome: OutcomeObservation,
) -> dict[str, Any]:
    """Reconstruct receipt material only from the sealed formal post-state."""

    period_root = period_directory(portfolio_root, int(item["period_index"]))
    try:
        frozen = load_frozen(period_root)
        stored_outcome = load_outcome(period_root)
        settled = load_settled(period_root)
    except (StoreError, ValueError, OSError) as exc:
        raise PortfolioSettleAllError("SETTLE_ALL_POST_STATE_INVALID", str(exc)) from exc
    if (
        frozen.content_hash != item.get("frozen_episode_hash")
        or settled.content_hash != item.get("settled_episode_hash")
        or stored_outcome != outcome
        or settled.outcome != outcome
        or settled.frozen_episode_hash != frozen.content_hash
    ):
        raise PortfolioSettleAllError(
            "SETTLE_ALL_POST_STATE_DRIFT", f"period={frozen.period_index}"
        )
    return {
        "period_index": frozen.period_index,
        "episode_ref": frozen.episode_ref,
        "frozen_episode_hash": frozen.content_hash,
        "settled_episode_hash": settled.content_hash,
        "account_identity": frozen.account_decision.identity.value,
        "outcome_result_hash": outcome.result_hash,
        "pnl": settled.statement.pnl,
        "closing_balance": settled.statement.closing_balance,
    }


def _find_existing_receipt(
    *,
    portfolio_root: Path,
    event_hash: str,
    periods: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Return one valid matching CAS receipt, rejecting corrupt or ambiguous evidence."""

    root = resolve_root(portfolio_root) / "objects" / "portfolio_settle_all_receipt" / "sha256"
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_STORE_INVALID", str(root))
    expected_hashes = [str(item["settled_episode_hash"]) for item in periods]
    matches: list[dict[str, str]] = []
    for prefix in sorted(root.iterdir(), key=lambda path: path.name):
        if (
            prefix.is_symlink()
            or not prefix.is_dir()
            or re.fullmatch(r"[0-9a-f]{2}", prefix.name) is None
        ):
            raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_STORE_INVALID", str(prefix))
        for path in sorted(prefix.iterdir(), key=lambda item: item.name):
            if (
                path.is_symlink()
                or not path.is_file()
                or re.fullmatch(r"[0-9a-f]{64}\.json", path.name) is None
            ):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_STORE_INVALID", str(path))
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_INVALID", str(path)) from exc
            if not isinstance(body, dict):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_INVALID", str(path))
            digest = path.stem
            if (
                body.get("schema_version") != SETTLE_ALL_RECEIPT_SCHEMA
                or body.get("content_hash") != digest
                or prefix.name != digest[:2]
                or canonical_sha256(
                    {key: value for key, value in body.items() if key != "content_hash"}
                )
                != digest
            ):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_INVALID", str(path))
            if body.get("portfolio_root") != str(resolve_root(portfolio_root)):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_INVALID", str(path))
            recovered = body.get("recovered_after_formal_commit")
            basis = body.get("inventory_basis")
            if (
                body.get("adapter_marker") != ADAPTER_MARKER
                or body.get("formal_object_model") != "production_FrozenShadowEpisode"
                or body.get("source_execution_classification") != "UNATTESTED_BY_LIBRARY"
                or body.get("prospective_source_attested") is not False
                or body.get("synthetic") is not None
                or body.get("completion_claim_allowed") is not False
                or not isinstance(recovered, bool)
                or basis != ("post_state_recovery" if recovered else "pre_commit_due_inventory")
                or _HEX64.fullmatch(str(body.get("inventory_hash"))) is None
            ):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_INVALID", str(path))
            if body.get("outcome_event_hash") != event_hash:
                continue
            settled_periods = body.get("settled_periods")
            if not isinstance(settled_periods, list):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_INVALID", str(path))
            actual_hashes = [
                str(item.get("settled_episode_hash"))
                for item in settled_periods
                if isinstance(item, dict)
            ]
            if (
                len(actual_hashes) != len(settled_periods)
                or actual_hashes != expected_hashes
                or settled_periods != periods
                or body.get("enumerated_due_count") != len(periods)
                or body.get("settled_count") != len(periods)
                or body.get("unsettled_due_count") != 0
                or body.get("settle_coverage") != "1.0000"
            ):
                raise PortfolioSettleAllError("SETTLE_ALL_RECEIPT_CONFLICT", str(path))
            matches.append({"receipt_path": str(path), "receipt_content_hash": digest})
    if len(matches) > 1:
        raise PortfolioSettleAllError(
            "SETTLE_ALL_RECEIPT_AMBIGUOUS", f"event={event_hash} count={len(matches)}"
        )
    return matches[0] if matches else None


def apply_portfolio_settle_all_from_reveal(
    *,
    authority_root: Path,
    portfolio_root: Path,
    packet_content_hash: str,
    reveal_content_hash: str | None = None,
    **forbidden_kwargs: Any,
) -> dict[str, Any]:
    """Settle the complete due set in one production continuity portfolio.

    The continuity schema permits only one unsettled head.  A second due period
    therefore proves store corruption and is rejected before any formal write.
    This cardinality is what makes the existing per-period intent journal an
    all-or-none formal commit rather than a multi-ledger partial posting.
    """

    if forbidden_kwargs:
        raise PortfolioSettleAllError(
            "SETTLE_ALL_CALLER_OVERRIDE_FORBIDDEN", f"keys={sorted(forbidden_kwargs)}"
        )
    portfolio = resolve_root(portfolio_root)
    event = load_verified_outcome_event(
        authority_root=authority_root,
        packet_content_hash=packet_content_hash,
        reveal_content_hash=reveal_content_hash,
    )
    outcome = OutcomeObservation.model_validate(event["outcome"])
    outcome.require_valid_result_hash()
    inventory = _inventory(portfolio, outcome)
    due = list(inventory["due"])
    settled = list(inventory["settled"])

    if not due:
        matching = [
            item
            for item in settled
            if item["target_ref"] == outcome.target_ref
            and item.get("outcome_result_hash") == outcome.result_hash
        ]
        if matching:
            period_results = [
                _period_result_from_settled(
                    portfolio_root=portfolio,
                    item=item,
                    outcome=outcome,
                )
                for item in matching
            ]
            receipt = _find_existing_receipt(
                portfolio_root=portfolio,
                event_hash=str(event["content_hash"]),
                periods=period_results,
            )
            receipt_recovered = receipt is None
            evidence: dict[str, str] | None = None
            if receipt is None:
                evidence = _write_event_evidence(
                    portfolio_root=portfolio,
                    event=event,
                    outcome=outcome,
                )
                try:
                    receipt = _write_receipt(
                        portfolio_root=portfolio,
                        event=event,
                        inventory_hash=inventory["content_hash"],
                        inventory_basis="post_state_recovery",
                        recovered_after_formal_commit=True,
                        periods=period_results,
                    )
                except (OSError, PortfolioSettleAllError) as exc:
                    raise PortfolioSettleAllError(
                        "SETTLE_ALL_EVIDENCE_RECOVERY_REQUIRED",
                        f"formal settlement sealed; receipt recovery failed: {exc}",
                    ) from exc
            return {
                "ok": True,
                "status": "SETTLE_ALL_IDEMPOTENT",
                "adapter_marker": ADAPTER_MARKER,
                "formal_object_model": "production_FrozenShadowEpisode",
                "portfolio_root": str(portfolio),
                "outcome_event_hash": event["content_hash"],
                "enumerated_due_count": 0,
                "settled_count": 0,
                "already_settled_count": len(matching),
                "unsettled_due_count": 0,
                "settle_coverage": "1.0000",
                "idempotent": True,
                "periods": period_results,
                "receipt_recovered": receipt_recovered,
                "source_raw_reparsed": True,
                "caller_verified_flag_trusted": False,
                "source_execution_classification": "UNATTESTED_BY_LIBRARY",
                "prospective_source_attested": False,
                "synthetic": None,
                "completion_claim_allowed": False,
                "auto_feedback": False,
                "auto_next_period": False,
                "auto_next_research": False,
                "daemon": False,
                **(evidence or {}),
                **receipt,
            }
        if any(item["target_ref"] == outcome.target_ref for item in settled):
            raise PortfolioSettleAllError(
                "SETTLEMENT_OUTCOME_CONFLICT", "formal period already settled differently"
            )
        raise PortfolioSettleAllError("NO_DUE_UNSETTLED_TICKETS", str(portfolio))

    # Full-store coverage before the first formal write.
    uncovered = [item for item in due if item["target_ref"] != outcome.target_ref]
    if uncovered:
        raise PortfolioSettleAllError(
            "SETTLE_ALL_OUTCOME_COVERAGE_INCOMPLETE",
            f"uncovered_periods={[item['period_index'] for item in uncovered]}",
        )
    if len(due) != 1:
        raise PortfolioSettleAllError(
            "PORTFOLIO_STORE_INVALID",
            f"continuity portfolio permits one due head, found {len(due)}",
        )
    due_item = due[0]
    period_root = period_directory(portfolio, int(due_item["period_index"]))
    frozen = load_frozen(period_root)
    if outcome.observed_at < frozen.target_open_time:
        raise PortfolioSettleAllError("OUTCOME_BEFORE_TARGET_OPEN", frozen.target_ref)
    try:
        binding = _bind_frozen_to_authority(
            frozen=frozen,
            packet=load_packet(resolve_authority_root(authority_root), packet_content_hash),
            packet_content_hash=packet_content_hash,
            portfolio_root=portfolio,
            outcome=outcome,
        )
    except (ValueError, StoreError, ProspectiveSourceError) as exc:
        raise PortfolioSettleAllError("FROZEN_AUTHORITY_BINDING_INVALID", str(exc)) from exc

    frozen_path = artifact_paths(period_root)["frozen"]
    frozen_bytes = frozen_path.read_bytes()
    evidence = _write_event_evidence(portfolio_root=portfolio, event=event, outcome=outcome)
    try:
        result = settle_portfolio_period(
            root=portfolio,
            _production_observed_outcome=outcome,
        )
    except (StoreError, ValueError, OSError) as exc:
        raise PortfolioSettleAllError("SETTLE_ALL_FORMAL_COMMIT_REJECTED", str(exc)) from exc
    if frozen_path.read_bytes() != frozen_bytes:
        raise PortfolioSettleAllError("FROZEN_BYTES_MUTATED", str(frozen_path))
    after = _inventory(portfolio, outcome)
    remaining = [item for item in after["due"] if item["target_ref"] == outcome.target_ref]
    if remaining:
        raise PortfolioSettleAllError(
            "SETTLE_ALL_INCOMPLETE_AFTER_COMMIT",
            f"remaining={[item['period_index'] for item in remaining]}",
        )
    settled_outcome = load_outcome(period_root)
    if settled_outcome != outcome:
        raise PortfolioSettleAllError("SETTLED_OUTCOME_DRIFT", frozen.episode_ref)
    settled_episode = load_settled(period_root)
    period_result = _period_result_from_settled(
        portfolio_root=portfolio,
        item={
            "period_index": frozen.period_index,
            "frozen_episode_hash": frozen.content_hash,
            "settled_episode_hash": settled_episode.content_hash,
        },
        outcome=outcome,
    )
    if period_result["pnl"] != result.get("pnl") or period_result["closing_balance"] != result.get(
        "closing_balance"
    ):
        raise PortfolioSettleAllError("SETTLE_ALL_CONSUMER_RESULT_DRIFT", frozen.episode_ref)
    try:
        receipt = _write_receipt(
            portfolio_root=portfolio,
            event=event,
            inventory_hash=inventory["content_hash"],
            inventory_basis="pre_commit_due_inventory",
            recovered_after_formal_commit=False,
            periods=[period_result],
        )
    except (OSError, PortfolioSettleAllError) as exc:
        raise PortfolioSettleAllError(
            "SETTLE_ALL_EVIDENCE_RECOVERY_REQUIRED",
            f"formal settlement sealed; retry same request to recover receipt: {exc}",
        ) from exc
    return {
        "ok": True,
        "status": "SETTLE_ALL_COMMITTED",
        "adapter_marker": ADAPTER_MARKER,
        "formal_object_model": "production_FrozenShadowEpisode",
        "portfolio_root": str(portfolio),
        "inventory_hash": inventory["content_hash"],
        "outcome_event_hash": event["content_hash"],
        "outcome_event_path": evidence["event_path"],
        "outcome_path": evidence["outcome_path"],
        "source_authority_binding": binding["source_authority_binding"],
        "research_binding_sha256": binding["research_binding_sha256"],
        "periods": [period_result],
        "enumerated_due_count": 1,
        "settled_count": 1,
        "already_settled_count": 0,
        "unsettled_due_count": 0,
        "settle_coverage": "1.0000",
        "idempotent": False,
        "receipt_recovered": False,
        "source_raw_reparsed": True,
        "caller_verified_flag_trusted": False,
        "source_execution_classification": "UNATTESTED_BY_LIBRARY",
        "prospective_source_attested": False,
        "synthetic": None,
        "scientific_promotion": False,
        "completion_claim_allowed": False,
        "auto_feedback": False,
        "auto_next_period": False,
        "auto_next_research": False,
        "daemon": False,
        **receipt,
    }


__all__ = [
    "ADAPTER_MARKER",
    "OUTCOME_EVENT_SCHEMA",
    "SETTLE_ALL_RECEIPT_SCHEMA",
    "PortfolioSettleAllError",
    "apply_portfolio_settle_all_from_reveal",
    "load_verified_outcome_event",
]
