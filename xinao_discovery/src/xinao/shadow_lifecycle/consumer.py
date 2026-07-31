"""Leg-A one-click file-backed shadow-lifecycle consumer.

Stable CLI: ``python -m xinao.shadow_lifecycle`` or ``xinao shadow ...``.

Flow: init → freeze (pre-outcome) → settle (explicit outcome) → status/replay.
Preserves frozen identity, no-peek, exact journals, once-only settlement, and
candidate-only authority. No Docker, Temporal, database, daemon, or live account.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.decision import FrozenDecision
from xinao.settlement import OutcomeObservation
from xinao.shadow_lifecycle.lifecycle import (
    AccountBranchDecision,
    AccountDecisionIdentity,
    AccountFeedback,
    AccountingBasis,
    AccountRiskTicket,
    EvidenceState,
    FeedbackKind,
    ScienceDecisionIdentity,
    SettledShadowEpisode,
    assess_fixture_evidence,
    build_account_action,
    build_account_action_from_ticket,
    build_account_no_action,
    build_science_decision,
    create_portfolio,
    create_seat,
    freeze_shadow_episode,
    replay_settled_episode,
    seal_account_feedback,
    settle_shadow_episode,
)
from xinao.shadow_lifecycle.store import (
    SCHEMA_RECEIPT,
    EpisodePhase,
    PortfolioPeriodPhase,
    StoreError,
    artifact_paths,
    derive_portfolio_head,
    detect_phase,
    load_feedback,
    load_frozen,
    load_outcome,
    load_portfolio,
    load_seat,
    load_settled,
    period_directory,
    portfolio_artifact_paths,
    prepare_next_period_root,
    read_json,
    resolve_root,
    write_feedback_exclusive,
    write_frozen_exclusive,
    write_manifest,
    write_outcome_and_settled_exclusive,
    write_portfolio_exclusive,
    write_portfolio_manifest,
    write_receipt_exclusive_or_replace,
    write_seat_exclusive,
)

CONSUMER_ID = "shadow_lifecycle_file_backed_leg_a"
CONSUMER_VERSION = "0.3.0"

# Production portfolio freeze requires a disposition-bound owner authority envelope.
# Labels / private underscores are not security boundaries — this is a structural gate.
OWNER_FREEZE_AUTHORITY_SCHEMA: Final = "xinao.owner_freeze_authority.v1"
OWNER_FREEZE_AUTHORITY_MARKER: Final = "XINAO_OWNER_FREEZE_AUTHORITY_V1"
RESEARCH_BINDING_REF_PREFIX: Final = "research-binding.sha256:"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING_REF_RE = re.compile(rf"{re.escape(RESEARCH_BINDING_REF_PREFIX)}([0-9a-f]{{64}})")
_CODEX_OWNER_CHANNEL_SOURCE: Final = "codex_owner_channel"
_ACCOUNT_ACTION: Final = "ACTION"
_ACCOUNT_NO_ACTION: Final = "RESEARCHER_ACCOUNT_NO_ACTION"


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


def _resolve_freeze_request(
    *,
    request_path: Path | None,
    request: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Accept exactly one authority input: path or closed in-memory mapping.

    In-memory requests are deep-copied so later mutation of the caller object
    (or of a display-only request artifact on disk) cannot change freeze input.
    """

    if (request_path is None) == (request is None):
        raise StoreError("freeze requires exactly one of request_path or request")
    if request is not None:
        if not isinstance(request, Mapping):
            raise StoreError("request must be a JSON object")
        return copy.deepcopy(dict(request))
    assert request_path is not None
    return _load_request(request_path)


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise StoreError(f"FREEZE_AUTHORITY_HASH_INVALID: {label} must be lowercase sha256")
    return value


def _raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso_z(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    text = str(value)
    return text.replace("+00:00", "Z") if text.endswith("+00:00") else text


def _research_binding_path(shadow_root: Path, binding_sha256: str) -> Path:
    digest = _require_hex64(binding_sha256, "research_binding_sha256")
    base = resolve_root(shadow_root)
    return base / "objects" / "research_binding" / "sha256" / digest[:2] / f"{digest}.json"


def _disposition_cas_path(owner_state_root: Path, artifact_sha256: str) -> Path:
    digest = _require_hex64(artifact_sha256, "owner_disposition_sha256")
    root = owner_state_root.expanduser().resolve()
    return root / "objects" / "sha256" / digest[:2] / f"{digest}.json"


def _binding_shadow_root_for_episode(base: Path) -> Path:
    """Research bindings live on portfolio root (or flat episode root)."""

    context = _continuity_context(base)
    if context == "portfolio-period":
        return base.parent.parent
    return base


def _extract_binding_hash_from_request(request: Mapping[str, Any]) -> str | None:
    claimed = request.get("bound_research_binding_sha256")
    sci = request.get("science_decision") or {}
    acc = request.get("account_decision") or {}
    sci_ref = str(sci.get("science_decision_ref") or "") if isinstance(sci, Mapping) else ""
    acc_ref = str(acc.get("account_decision_ref") or "") if isinstance(acc, Mapping) else ""
    sci_m = _BINDING_REF_RE.search(sci_ref)
    acc_m = _BINDING_REF_RE.search(acc_ref)
    if claimed is not None:
        digest = _require_hex64(claimed, "bound_research_binding_sha256")
        if sci_m is not None and sci_m.group(1) != digest:
            raise StoreError(
                "FREEZE_AUTHORITY_BINDING_REF_MISMATCH: "
                "science_decision_ref disagrees with bound_research_binding_sha256"
            )
        if acc_m is not None and acc_m.group(1) != digest:
            raise StoreError(
                "FREEZE_AUTHORITY_BINDING_REF_MISMATCH: "
                "account_decision_ref disagrees with bound_research_binding_sha256"
            )
        return digest
    if sci_m is None and acc_m is None:
        return None
    if sci_m is None or acc_m is None or sci_m.group(1) != acc_m.group(1):
        raise StoreError(
            "FREEZE_AUTHORITY_BINDING_REF_MISMATCH: "
            "science/account decision refs disagree on research binding hash"
        )
    return sci_m.group(1)


def _load_research_binding(shadow_root: Path, binding_sha256: str) -> dict[str, Any]:
    digest = _require_hex64(binding_sha256, "research_binding_sha256")
    path = _research_binding_path(shadow_root, digest)
    if not path.is_file():
        raise StoreError(f"FREEZE_AUTHORITY_BINDING_MISSING: {digest}")
    raw = path.read_bytes()
    if _raw_sha256(raw) != digest:
        raise StoreError(f"FREEZE_AUTHORITY_BINDING_BYTES_TAMPERED: {digest}")
    if path.name != f"{digest}.json" or path.parent.name != digest[:2]:
        raise StoreError(f"FREEZE_AUTHORITY_BINDING_PATH_MISMATCH: {path}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreError(f"FREEZE_AUTHORITY_BINDING_JSON_INVALID: {exc}") from exc
    if not isinstance(payload, dict):
        raise StoreError("FREEZE_AUTHORITY_BINDING_JSON_INVALID: object required")
    return payload


def _request_content_hash(request: Mapping[str, Any]) -> str:
    body = {k: v for k, v in request.items() if k != "request_content_hash"}
    return canonical_sha256(body)


def _assert_request_content_hash(request: Mapping[str, Any]) -> str:
    recomputed = _request_content_hash(request)
    claimed = request.get("request_content_hash")
    if claimed is not None:
        claimed_hex = _require_hex64(claimed, "request_content_hash")
        if claimed_hex != recomputed:
            raise StoreError(
                "FREEZE_AUTHORITY_REQUEST_HASH_MISMATCH: "
                f"claimed={claimed_hex} recomputed={recomputed}"
            )
    return recomputed


def _assert_episode_matches_binding_intent(
    *,
    episode: Any,
    binding: Mapping[str, Any],
) -> None:
    """Compare the pre-write episode object to sealed research-binding intent."""

    intent = binding.get("executable_account_intent")
    if not isinstance(intent, Mapping):
        raise StoreError(
            "FREEZE_AUTHORITY_BINDING_EXECUTABLE_MISSING: "
            "research binding lacks executable_account_intent"
        )
    account_identity = str(binding.get("account_identity") or "")
    if str(episode.account_decision.identity.value) != account_identity:
        raise StoreError(
            "FREEZE_AUTHORITY_ACCOUNT_IDENTITY_MISMATCH: "
            f"episode={episode.account_decision.identity.value} binding={account_identity}"
        )
    if str(episode.target_ref) != str(intent.get("target_ref")):
        raise StoreError(
            f"FREEZE_AUTHORITY_TARGET_MISMATCH: episode={episode.target_ref} "
            f"intent={intent.get('target_ref')}"
        )
    if _iso_z(episode.target_open_time) != str(intent.get("target_open_time")):
        raise StoreError("FREEZE_AUTHORITY_TARGET_OPEN_MISMATCH")
    if _iso_z(episode.freeze_deadline) != str(intent.get("freeze_deadline")):
        raise StoreError("FREEZE_AUTHORITY_DEADLINE_MISMATCH")
    if _iso_z(episode.frozen_at) != str(intent.get("frozen_at")):
        raise StoreError("FREEZE_AUTHORITY_FROZEN_AT_MISMATCH")
    if str(episode.rule_ref) != str(intent.get("rule_ref")):
        raise StoreError("FREEZE_AUTHORITY_RULE_MISMATCH")
    if str(episode.odds_version_ref) != str(intent.get("odds_version_ref")):
        raise StoreError("FREEZE_AUTHORITY_ODDS_MISMATCH")
    if int(episode.period_index) != int(binding.get("period_index", -1)):
        raise StoreError(
            "FREEZE_AUTHORITY_PERIOD_MISMATCH: "
            f"episode={episode.period_index} binding={binding.get('period_index')}"
        )

    if account_identity == _ACCOUNT_ACTION:
        ticket = episode.bound_account_ticket
        if ticket is None:
            raise StoreError("FREEZE_AUTHORITY_TICKET_MISSING: ACTION requires bound ticket")
        for field in (
            "selected_number",
            "stake",
            "panel",
            "rule_ref",
            "odds_version_ref",
            "baseline_ref",
            "risk_policy_ref",
            "target_ref",
        ):
            ticket_val = getattr(ticket, field)
            intent_val = intent.get(field)
            if ticket_val != intent_val and str(ticket_val) != str(intent_val):
                raise StoreError(
                    "FREEZE_AUTHORITY_TICKET_MISMATCH: "
                    f"{field}: ticket={ticket_val!r} intent={intent_val!r}"
                )
        if str(episode.account_decision.stake) != str(intent.get("stake")):
            raise StoreError(
                f"FREEZE_AUTHORITY_ACCOUNT_STAKE_MISMATCH: {episode.account_decision.stake}"
            )
    elif account_identity == _ACCOUNT_NO_ACTION:
        if episode.bound_account_ticket is not None:
            raise StoreError("FREEZE_AUTHORITY_NO_ACTION_HAS_TICKET")
        if str(episode.account_decision.stake) != "0.0000":
            raise StoreError(
                f"FREEZE_AUTHORITY_NO_ACTION_STAKE_MISMATCH: {episode.account_decision.stake}"
            )
    else:
        raise StoreError(f"FREEZE_AUTHORITY_ACCOUNT_IDENTITY_INVALID: {account_identity}")


def _assert_pre_write_research_binding_authority(
    *,
    root: Path,
    request: Mapping[str, Any],
    episode: Any,
) -> None:
    """Authority comparison BEFORE irreversible freeze write when binding is present.

    A failed check must leave no frozen ticket on the ledger.
    """

    binding_hash = _extract_binding_hash_from_request(request)
    if binding_hash is None:
        return
    shadow_root = _binding_shadow_root_for_episode(resolve_root(root))
    binding = _load_research_binding(shadow_root, binding_hash)
    # Decision refs on the sealed episode must embed the same binding hash.
    try:
        sci_ref = str(episode.science_decision.science_decision_ref)
        acc_ref = str(episode.account_decision.account_decision_ref)
    except Exception as exc:  # pragma: no cover - defensive
        raise StoreError(f"FREEZE_AUTHORITY_DECISION_REF_UNREADABLE: {exc}") from exc
    sci_m = _BINDING_REF_RE.search(sci_ref)
    acc_m = _BINDING_REF_RE.search(acc_ref)
    if (
        sci_m is None
        or acc_m is None
        or sci_m.group(1) != binding_hash
        or acc_m.group(1) != binding_hash
    ):
        raise StoreError(
            "FREEZE_AUTHORITY_EPISODE_BINDING_REF_MISMATCH: "
            "frozen decision refs must embed the sealed research binding hash"
        )
    _assert_episode_matches_binding_intent(episode=episode, binding=binding)


def _live_portfolio_binding(portfolio_root: Path) -> dict[str, Any]:
    """Derive closed portfolio/head identity for authority envelope checks."""

    base = resolve_root(portfolio_root)
    seat = load_seat(base)
    portfolio = load_portfolio(base)
    head = derive_portfolio_head(base)
    if head.period_index == 0:
        intended = 1
        prior_settled: str | None = None
        prior_feedback: str | None = None
    elif head.phase in {PortfolioPeriodPhase.MISSING, PortfolioPeriodPhase.INIT}:
        intended = head.period_index
        if intended == 1:
            prior_settled = None
            prior_feedback = None
        else:
            prior_root = period_directory(base, intended - 1)
            prior_settled = load_settled(prior_root).content_hash
            prior_feedback = load_feedback(prior_root).content_hash
    elif head.phase == PortfolioPeriodPhase.FEEDBACK_SEALED:
        intended = head.period_index + 1
        prior_settled = head.settled_episode_hash
        prior_feedback = head.feedback_hash
    else:
        raise StoreError(
            "FREEZE_PORTFOLIO_HEAD_NOT_READY: "
            f"portfolio cannot freeze while head is {head.phase.value}"
        )
    return {
        "portfolio_ref": portfolio.portfolio_ref,
        "portfolio_content_hash": portfolio.content_hash,
        "seat_id": seat.seat_id,
        "seat_content_hash": seat.content_hash,
        "head_period_index": head.period_index,
        "head_phase": head.phase.value,
        "prior_settled_episode_hash": prior_settled,
        "prior_feedback_hash": prior_feedback,
        "intended_next_period_index": intended,
    }


def _assert_disposition_intent_matches_request(
    *,
    disposition: Mapping[str, Any],
    request: Mapping[str, Any],
) -> None:
    account_identity = str(disposition.get("account_identity") or "")
    req_account = request.get("account_decision") or {}
    if not isinstance(req_account, Mapping):
        raise StoreError("FREEZE_AUTHORITY_REQUEST_ACCOUNT_MISSING")
    if str(req_account.get("identity")) != account_identity:
        raise StoreError(
            "FREEZE_AUTHORITY_DISPOSITION_ACCOUNT_MISMATCH: "
            f"request={req_account.get('identity')} disposition={account_identity}"
        )
    if account_identity == _ACCOUNT_ACTION:
        executable = disposition.get("executable_account_decision")
        ticket = request.get("bound_account_ticket")
        if not isinstance(executable, Mapping) or not isinstance(ticket, Mapping):
            raise StoreError("FREEZE_AUTHORITY_ACTION_EXECUTABLE_REQUIRED")
        for field in (
            "selected_number",
            "stake",
            "panel",
            "rule_ref",
            "odds_version_ref",
            "baseline_ref",
            "risk_policy_ref",
            "target_ref",
        ):
            t_val = ticket.get(field)
            e_val = executable.get(field)
            if t_val != e_val and str(t_val) != str(e_val):
                raise StoreError(
                    "FREEZE_AUTHORITY_DISPOSITION_TICKET_MISMATCH: "
                    f"{field}: ticket={t_val!r} disposition={e_val!r}"
                )
        for time_field in ("target_open_time", "freeze_deadline", "frozen_at", "knowledge_cutoff"):
            if str(ticket.get(time_field)) != str(executable.get(time_field)):
                raise StoreError(f"FREEZE_AUTHORITY_DISPOSITION_TICKET_MISMATCH: {time_field}")
    elif account_identity == _ACCOUNT_NO_ACTION:
        if (
            request.get("bound_account_ticket") is not None
            or request.get("bound_frozen_decision") is not None
        ):
            raise StoreError("FREEZE_AUTHORITY_NO_ACTION_MUST_NOT_BIND_TICKET")
        binding = disposition.get("no_action_period_binding")
        if not isinstance(binding, Mapping):
            raise StoreError("FREEZE_AUTHORITY_NO_ACTION_BINDING_REQUIRED")
        if str(req_account.get("rule_ref")) != str(binding.get("rule_ref")):
            raise StoreError("FREEZE_AUTHORITY_NO_ACTION_RULE_MISMATCH")
        if str(req_account.get("odds_version_ref")) != str(binding.get("odds_version_ref")):
            raise StoreError("FREEZE_AUTHORITY_NO_ACTION_ODDS_MISMATCH")
    else:
        raise StoreError(f"FREEZE_AUTHORITY_DISPOSITION_ACCOUNT_INVALID: {account_identity}")


def _require_and_verify_owner_freeze_authority(
    *,
    portfolio_root: Path,
    request: Mapping[str, Any],
    owner_authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Production portfolio freeze: require disposition-bound Owner authority envelope/CAS.

    Workers with package import + shadow write access cannot mint production ACTION
    without owner-root disposition evidence bound to the live portfolio head.
    """

    if owner_authority is None:
        raise StoreError(
            "PRODUCTION_FREEZE_REQUIRES_OWNER_AUTHORITY: "
            "freeze_portfolio_period requires disposition-bound owner_authority "
            "envelope/CAS (use allow_fixture_construction=True only for explicit fixtures)"
        )
    if not isinstance(owner_authority, Mapping):
        raise StoreError("PRODUCTION_FREEZE_AUTHORITY_INVALID: owner_authority must be an object")

    if owner_authority.get("schema_version") != OWNER_FREEZE_AUTHORITY_SCHEMA:
        raise StoreError(
            f"PRODUCTION_FREEZE_AUTHORITY_SCHEMA_DRIFT: {owner_authority.get('schema_version')}"
        )
    if owner_authority.get("authority_marker") != OWNER_FREEZE_AUTHORITY_MARKER:
        raise StoreError(
            f"PRODUCTION_FREEZE_AUTHORITY_MARKER_INVALID: {owner_authority.get('authority_marker')}"
        )

    owner_state_root = Path(str(owner_authority["owner_state_root"])).expanduser().resolve()
    disposition_sha = _require_hex64(
        owner_authority.get("owner_disposition_sha256"),
        "owner_disposition_sha256",
    )
    binding_sha = _require_hex64(
        owner_authority.get("research_binding_sha256"),
        "research_binding_sha256",
    )
    envelope_request_hash = _require_hex64(
        owner_authority.get("request_content_hash"),
        "request_content_hash",
    )

    # Bind exactly the closed request that will be written.
    recomputed = _assert_request_content_hash(request)
    if recomputed != envelope_request_hash:
        raise StoreError(
            "PRODUCTION_FREEZE_REQUEST_ENVELOPE_MISMATCH: "
            f"envelope={envelope_request_hash} request={recomputed}"
        )

    request_binding = _extract_binding_hash_from_request(request)
    if request_binding is None:
        raise StoreError(
            "PRODUCTION_FREEZE_REQUIRES_RESEARCH_BINDING: "
            "production freeze request must embed research-binding authority"
        )
    if request_binding != binding_sha:
        raise StoreError(
            "PRODUCTION_FREEZE_BINDING_ENVELOPE_MISMATCH: "
            f"envelope={binding_sha} request={request_binding}"
        )

    # Disposition CAS under owner root (path + bytes).
    if not owner_state_root.is_dir():
        raise StoreError(f"OWNER_STATE_ROOT_MISSING: {owner_state_root}")
    disp_path = _disposition_cas_path(owner_state_root, disposition_sha)
    if not disp_path.is_file():
        raise StoreError(f"OWNER_DISPOSITION_CAS_MISSING: {disp_path}")
    raw = disp_path.read_bytes()
    if _raw_sha256(raw) != disposition_sha:
        raise StoreError(f"OWNER_DISPOSITION_BYTES_TAMPERED: {disposition_sha}")
    if disp_path.name != f"{disposition_sha}.json" or disp_path.parent.name != disposition_sha[:2]:
        raise StoreError(f"OWNER_DISPOSITION_CAS_PATH_MISMATCH: {disp_path}")
    try:
        disposition = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StoreError(f"OWNER_DISPOSITION_JSON_INVALID: {exc}") from exc
    if not isinstance(disposition, dict):
        raise StoreError("OWNER_DISPOSITION_JSON_INVALID: object required")
    if disposition.get("disposition_source") != _CODEX_OWNER_CHANNEL_SOURCE:
        raise StoreError(
            f"OWNER_DISPOSITION_SOURCE_NOT_OWNER_CHANNEL: {disposition.get('disposition_source')}"
        )
    if disposition.get("worker_controlled") is True:
        raise StoreError("OWNER_DISPOSITION_WORKER_CONTROLLED")

    # Portfolio head exact binding before any freeze write.
    claimed_pb = disposition.get("portfolio_binding")
    if not isinstance(claimed_pb, Mapping):
        raise StoreError(
            "PRODUCTION_FREEZE_PORTFOLIO_BINDING_REQUIRED: "
            "owner disposition must carry closed portfolio_binding"
        )
    live_pb = _live_portfolio_binding(portfolio_root)
    for key in (
        "portfolio_ref",
        "portfolio_content_hash",
        "seat_id",
        "seat_content_hash",
        "head_period_index",
        "head_phase",
        "prior_settled_episode_hash",
        "prior_feedback_hash",
        "intended_next_period_index",
    ):
        if claimed_pb.get(key) != live_pb.get(key):
            raise StoreError(
                "PRODUCTION_FREEZE_PORTFOLIO_HEAD_MISMATCH: "
                f"{key}: disposition={claimed_pb.get(key)!r} live={live_pb.get(key)!r}"
            )
    if int(claimed_pb["intended_next_period_index"]) != int(disposition["period_index"]):
        raise StoreError("PRODUCTION_FREEZE_PORTFOLIO_PERIOD_MISMATCH")

    # Disposition executable intent must match the freeze request ticket/branch.
    _assert_disposition_intent_matches_request(disposition=disposition, request=request)

    # Research binding CAS under portfolio root must exist and agree with disposition.
    binding = _load_research_binding(resolve_root(portfolio_root), binding_sha)
    if int(binding.get("period_index", -1)) != int(disposition["period_index"]):
        raise StoreError("PRODUCTION_FREEZE_BINDING_PERIOD_MISMATCH")
    if str(binding.get("account_identity")) != str(disposition.get("account_identity")):
        raise StoreError("PRODUCTION_FREEZE_BINDING_ACCOUNT_MISMATCH")
    if str(binding.get("owner_artifact_sha256")) != disposition_sha:
        raise StoreError(
            "PRODUCTION_FREEZE_BINDING_OWNER_MISMATCH: "
            "research binding must seal the same owner disposition hash"
        )
    intent = binding.get("executable_account_intent")
    if not isinstance(intent, Mapping):
        raise StoreError("PRODUCTION_FREEZE_BINDING_EXECUTABLE_MISSING")
    if str(disposition.get("account_identity")) == _ACCOUNT_ACTION:
        executable = disposition.get("executable_account_decision")
        if not isinstance(executable, Mapping):
            raise StoreError("PRODUCTION_FREEZE_ACTION_EXECUTABLE_REQUIRED")
        if int(intent.get("selected_number")) != int(executable["selected_number"]):
            raise StoreError("PRODUCTION_FREEZE_BINDING_NUMBER_MISMATCH")
        if str(intent.get("stake")) != str(executable["stake"]):
            raise StoreError("PRODUCTION_FREEZE_BINDING_STAKE_MISMATCH")

    # Bound owner artifact on request must match disposition CAS.
    bound_owner = request.get("bound_owner_artifact_sha256")
    if bound_owner is not None and str(bound_owner) != disposition_sha:
        raise StoreError(
            "PRODUCTION_FREEZE_REQUEST_OWNER_MISMATCH: "
            f"request={bound_owner} disposition={disposition_sha}"
        )

    return {
        "owner_state_root": str(owner_state_root),
        "owner_disposition_sha256": disposition_sha,
        "research_binding_sha256": binding_sha,
        "request_content_hash": envelope_request_hash,
        "disposition": disposition,
        "portfolio_binding": live_pb,
    }


def _continuity_context(root: Path) -> str | None:
    base = resolve_root(root)
    if portfolio_artifact_paths(base)["portfolio"].is_file():
        return "portfolio-root"
    if (
        base.parent.name == "periods"
        and portfolio_artifact_paths(base.parent.parent)["portfolio"].is_file()
    ):
        return "portfolio-period"
    return None


def _reject_flat_operation_on_continuity_context(
    root: Path,
    *,
    verb: str,
    allow_internal_period: bool = False,
) -> None:
    context = _continuity_context(root)
    if context is None or (context == "portfolio-period" and allow_internal_period):
        return
    raise StoreError(
        f"{verb} is a legacy flat verb and cannot target a {context}; use portfolio-{verb}"
    )


def _receipt_base(
    *, root: Path, phase: EpisodePhase | PortfolioPeriodPhase | str, **fields: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": SCHEMA_RECEIPT,
        "consumer_id": CONSUMER_ID,
        "consumer_version": CONSUMER_VERSION,
        "root": str(resolve_root(root)),
        "phase": phase.value if isinstance(phase, StrEnum) else str(phase),
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
    _reject_flat_operation_on_continuity_context(base, verb="init")
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
    _reject_flat_operation_on_continuity_context(base, verb="inspect")
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

    if phase in {
        EpisodePhase.FROZEN,
        EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED,
        EpisodePhase.SETTLED,
    }:
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
                "recovery_required": False,
            }
        )
        # no-peek: do not surface outcome fields while only frozen (pre-outcome)
        if phase == EpisodePhase.FROZEN:
            result["next_action"] = "settle"
            result["evidence_state"] = EvidenceState.IMPLEMENTATION_READY.value

    if phase == EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED:
        # Intent sealed (outcome may be absent): recovery without settlement claims.
        paths = artifact_paths(base)
        outcome_present = paths["outcome"].is_file()
        result.update(
            {
                "outcome_present": outcome_present,
                "recovery_required": True,
                "next_action": "settle",
                "evidence_state": EvidenceState.IMPLEMENTATION_READY.value,
            }
        )
        if outcome_present:
            outcome = load_outcome(base)
            result["outcome_ref"] = outcome.outcome_ref
    elif phase == EpisodePhase.SETTLED:
        settled = load_settled(base)
        outcome = load_outcome(base)
        result.update(
            {
                "outcome_present": True,
                "recovery_required": False,
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


def freeze_episode(
    *,
    root: Path,
    request_path: Path | None = None,
    request: Mapping[str, Any] | None = None,
    period_index: int = 1,
    prior_settled: SettledShadowEpisode | None = None,
    accounting_basis: AccountingBasis = AccountingBasis.LEGACY_OPENING_JOURNAL,
    _continuity_internal: bool = False,
) -> dict[str, Any]:
    base = resolve_root(root)
    _reject_flat_operation_on_continuity_context(
        base,
        verb="freeze",
        allow_internal_period=_continuity_internal,
    )
    if _continuity_internal and accounting_basis != AccountingBasis.CARRIED_BALANCE_SNAPSHOT:
        raise StoreError("continuity period freeze requires CARRIED_BALANCE_SNAPSHOT accounting")
    phase = detect_phase(base)
    if phase != EpisodePhase.INIT:
        raise StoreError(f"freeze requires INIT phase, found {phase.value}")

    seat = load_seat(base)
    request = _resolve_freeze_request(request_path=request_path, request=request)

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
    ticket_raw = request.get("bound_account_ticket")
    bound: FrozenDecision | None = None
    ticket: AccountRiskTicket | None = None
    if bound_raw is not None and ticket_raw is not None:
        raise StoreError("ACTION freeze must not bind both scientific and account tickets")
    if bound_raw is not None:
        if not isinstance(bound_raw, dict):
            raise StoreError("bound_frozen_decision must be a JSON object")
        bound = FrozenDecision.model_validate(bound_raw)
        if bound.content_hash is None:
            bound = bound.with_content_hash()
        elif bound.content_hash != bound.compute_content_hash():
            raise StoreError("bound FrozenDecision content seal invalid")
    if ticket_raw is not None:
        if not isinstance(ticket_raw, dict):
            raise StoreError("bound_account_ticket must be a JSON object")
        ticket = AccountRiskTicket.model_validate(ticket_raw)
        if ticket.content_hash is None:
            ticket = ticket.with_content_hash()
        elif ticket.content_hash != ticket.compute_content_hash():
            raise StoreError("bound AccountRiskTicket content seal invalid")

    if account_raw is None:
        if (bound is None) == (ticket is None):
            raise StoreError("freeze requires account_decision or exactly one ACTION ticket")
        decision_ref = str(request.get("account_decision_ref") or f"acct.{episode_ref}")
        account = (
            build_account_action(
                account_decision_ref=decision_ref,
                frozen_decision=bound,
            )
            if bound is not None
            else build_account_action_from_ticket(
                account_decision_ref=decision_ref,
                account_ticket=ticket,
            )
        )
    else:
        if not isinstance(account_raw, dict):
            raise StoreError("account_decision must be a JSON object")
        identity = AccountDecisionIdentity(str(account_raw["identity"]))
        if identity == AccountDecisionIdentity.ACTION:
            if (bound is None) == (ticket is None):
                raise StoreError("ACTION freeze requires exactly one bound action ticket")
            account = (
                build_account_action(
                    account_decision_ref=str(account_raw["account_decision_ref"]),
                    frozen_decision=bound,
                )
                if bound is not None
                else build_account_action_from_ticket(
                    account_decision_ref=str(account_raw["account_decision_ref"]),
                    account_ticket=ticket,
                )
            )
        else:
            if bound is not None or ticket is not None:
                raise StoreError("account no-action must not bind an ACTION ticket")
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
        "period_index": period_index,
        "prior_settled": prior_settled,
        "accounting_basis": accounting_basis,
        "outcome_present": False,
    }
    if request.get("pre_freeze_balance") is not None:
        freeze_kwargs["pre_freeze_balance"] = str(request["pre_freeze_balance"])
    if account.identity == AccountDecisionIdentity.ACTION:
        if bound is not None:
            freeze_kwargs["bound_frozen_decision"] = bound
        else:
            freeze_kwargs["bound_account_ticket"] = ticket
        if accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
            freeze_kwargs["opening_journal_group_ref"] = str(
                request.get("opening_journal_group_ref") or f"journal.opening.{episode_ref}"
            )
        elif request.get("opening_journal_group_ref") is not None:
            freeze_kwargs["opening_journal_group_ref"] = str(request["opening_journal_group_ref"])
        freeze_kwargs["position_journal_group_ref"] = str(
            request.get("position_journal_group_ref") or f"journal.position.{episode_ref}"
        )

    episode = freeze_shadow_episode(**freeze_kwargs)
    # Authority comparison BEFORE irreversible exclusive freeze write.
    # Mutated in-memory tickets cannot leave a poisoned FROZEN ledger.
    _assert_pre_write_research_binding_authority(
        root=base,
        request=request,
        episode=episode,
    )
    write_frozen_exclusive(base, episode)
    # Additive optional research-binding fields (absent on legacy freeze requests).
    binding_fields: dict[str, Any] = {}
    for key in (
        "bound_result_sha256",
        "bound_receipt_content_sha256",
        "bound_pool_entry_content_hash",
        "bound_owner_artifact_sha256",
        "bound_policy_ref",
        "bound_research_binding_sha256",
        "trusted_time_proof",
    ):
        if key in request:
            binding_fields[key] = request[key]
    # File-backed leg-A never proves wall-clock; if caller omitted the flag, leave absent.
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
        **binding_fields,
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=True)
    write_manifest(base)
    result: dict[str, Any] = {
        "ok": True,
        "phase": EpisodePhase.FROZEN.value,
        "root": str(base),
        "episode_ref": episode.episode_ref,
        "frozen_episode_hash": episode.content_hash,
        "period_index": episode.period_index,
        "account_identity": episode.account_decision.identity.value,
        "completion_claim_allowed": False,
        "next_action": "settle",
    }
    result.update(binding_fields)
    return result


def settle_episode(
    *,
    root: Path,
    outcome_path: Path,
    settlement_ref: str | None = None,
    settlement_journal_group_ref: str | None = None,
    statement_ref: str | None = None,
    occurred_at: str | None = None,
    _continuity_internal: bool = False,
) -> dict[str, Any]:
    base = resolve_root(root)
    _reject_flat_operation_on_continuity_context(
        base,
        verb="settle",
        allow_internal_period=_continuity_internal,
    )
    phase = detect_phase(base)
    if phase not in {
        EpisodePhase.FROZEN,
        EpisodePhase.SETTLEMENT_RECOVERY_REQUIRED,
    }:
        raise StoreError(
            f"settle requires FROZEN or SETTLEMENT_RECOVERY_REQUIRED phase, found {phase.value}"
        )

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
    # Intent-first journal: exact full-intent resumes remaining seals; any identity drift rejects.
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


def replay_episode(*, root: Path, _continuity_internal: bool = False) -> dict[str, Any]:
    base = resolve_root(root)
    _reject_flat_operation_on_continuity_context(
        base,
        verb="replay",
        allow_internal_period=_continuity_internal,
    )
    phase = detect_phase(base)
    # Replay requires fully sealed settled; outcome-only recovery is not replayable.
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


def init_portfolio(
    *,
    root: Path,
    seat_id: str,
    portfolio_ref: str,
    opening_balance: str | None = None,
) -> dict[str, Any]:
    """Create an immutable continuity root without opening or funding a second seat."""

    base = resolve_root(root)
    if base.exists() and any(base.iterdir()):
        raise StoreError(f"portfolio-init requires an empty root directory: {base}")
    base.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"seat_id": seat_id, "portfolio_ref": portfolio_ref}
    if opening_balance is not None:
        kwargs["opening_balance"] = opening_balance
    seat = create_seat(**kwargs)
    portfolio = create_portfolio(seat=seat)
    write_seat_exclusive(base, seat)
    write_portfolio_exclusive(base, portfolio)
    portfolio_artifact_paths(base)["periods"].mkdir(exist_ok=True)
    receipt = _receipt_base(
        root=base,
        phase=PortfolioPeriodPhase.INIT,
        seat_id=seat.seat_id,
        portfolio_ref=seat.portfolio_ref,
        seat_content_hash=seat.content_hash,
        portfolio_content_hash=portfolio.content_hash,
        opening_balance=seat.opening_balance,
        head_period_index=0,
        next_action="portfolio-freeze",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=False)
    write_portfolio_manifest(base)
    return {
        "ok": True,
        "phase": PortfolioPeriodPhase.INIT.value,
        "root": str(base),
        "seat_id": seat.seat_id,
        "portfolio_ref": seat.portfolio_ref,
        "seat_content_hash": seat.content_hash,
        "portfolio_content_hash": portfolio.content_hash,
        "head_period_index": 0,
        "opening_balance": seat.opening_balance,
        "completion_claim_allowed": False,
        "next_action": "portfolio-freeze",
    }


def inspect_portfolio(*, root: Path) -> dict[str, Any]:
    base = resolve_root(root)
    seat = load_seat(base)
    portfolio = load_portfolio(base)
    head = derive_portfolio_head(base)
    if head.phase in {
        PortfolioPeriodPhase.INIT,
        PortfolioPeriodPhase.MISSING,
        PortfolioPeriodPhase.FEEDBACK_SEALED,
    }:
        next_action = "portfolio-freeze"
    elif head.phase in {
        PortfolioPeriodPhase.FROZEN,
        PortfolioPeriodPhase.SETTLEMENT_RECOVERY_REQUIRED,
    }:
        next_action = "portfolio-settle"
    else:
        next_action = "portfolio-feedback"
    return {
        "ok": True,
        "phase": head.phase.value,
        "root": str(base),
        "seat_id": seat.seat_id,
        "portfolio_ref": portfolio.portfolio_ref,
        "seat_content_hash": seat.content_hash,
        "portfolio_content_hash": portfolio.content_hash,
        "head_period_index": head.period_index,
        "head_period_root": str(head.period_root) if head.period_root is not None else None,
        "closing_balance": head.closing_balance,
        "settled_episode_hash": head.settled_episode_hash,
        "feedback_hash": head.feedback_hash,
        "candidate_only": True,
        "first_episode_verified": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "next_action": next_action,
    }


def freeze_portfolio_period(
    *,
    root: Path,
    request_path: Path | None = None,
    request: Mapping[str, Any] | None = None,
    owner_authority: Mapping[str, Any] | None = None,
    allow_fixture_construction: bool = False,
) -> dict[str, Any]:
    """Freeze the next portfolio period.

    Production path requires a disposition-bound Owner authority envelope/CAS.
    Fixture/unit construction must set ``allow_fixture_construction=True``
    explicitly — module privacy is not a security boundary.
    """

    # Capture authority input before any period-root preparation side effects.
    closed_request = _resolve_freeze_request(request_path=request_path, request=request)
    base = resolve_root(root)
    if allow_fixture_construction:
        if owner_authority is not None:
            raise StoreError(
                "FIXTURE_FREEZE_MUST_NOT_MIX_OWNER_AUTHORITY: "
                "use either production owner_authority or allow_fixture_construction"
            )
    else:
        # Structural production gate: no disposition-bound envelope => no freeze write.
        _require_and_verify_owner_freeze_authority(
            portfolio_root=base,
            request=closed_request,
            owner_authority=owner_authority,
        )
    period_root, period_index, prior_settled = prepare_next_period_root(base)
    result = freeze_episode(
        root=period_root,
        request=closed_request,
        period_index=period_index,
        prior_settled=prior_settled,
        accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
        _continuity_internal=True,
    )
    receipt = _receipt_base(
        root=base,
        phase=PortfolioPeriodPhase.FROZEN,
        head_period_index=period_index,
        period_root=str(period_root),
        episode_ref=result["episode_ref"],
        frozen_episode_hash=result["frozen_episode_hash"],
        account_identity=result["account_identity"],
        next_action="portfolio-settle",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=True)
    write_portfolio_manifest(base)
    return {
        **result,
        "phase": PortfolioPeriodPhase.FROZEN.value,
        "root": str(base),
        "period_root": str(period_root),
        "period_index": period_index,
        "next_action": "portfolio-settle",
    }


def settle_portfolio_period(
    *,
    root: Path,
    outcome_path: Path,
    settlement_ref: str | None = None,
    settlement_journal_group_ref: str | None = None,
    statement_ref: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    base = resolve_root(root)
    head = derive_portfolio_head(base)
    if head.period_root is None or head.phase not in {
        PortfolioPeriodPhase.FROZEN,
        PortfolioPeriodPhase.SETTLEMENT_RECOVERY_REQUIRED,
    }:
        raise StoreError("portfolio-settle requires a FROZEN or SETTLEMENT_RECOVERY_REQUIRED head")
    result = settle_episode(
        root=head.period_root,
        outcome_path=outcome_path,
        settlement_ref=settlement_ref,
        settlement_journal_group_ref=settlement_journal_group_ref,
        statement_ref=statement_ref,
        occurred_at=occurred_at,
        _continuity_internal=True,
    )
    receipt = _receipt_base(
        root=base,
        phase=PortfolioPeriodPhase.SETTLED,
        head_period_index=head.period_index,
        period_root=str(head.period_root),
        episode_ref=result["episode_ref"],
        settled_episode_hash=result["settled_episode_hash"],
        statement_result=result["statement_result"],
        pnl=result["pnl"],
        closing_balance=result["closing_balance"],
        next_action="portfolio-feedback",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=True)
    write_portfolio_manifest(base)
    return {
        **result,
        "phase": PortfolioPeriodPhase.SETTLED.value,
        "root": str(base),
        "period_root": str(head.period_root),
        "period_index": head.period_index,
        "scientific_promotion": False,
        "next_action": "portfolio-feedback",
    }


def feedback_portfolio_period(
    *,
    root: Path,
    kind: FeedbackKind,
    feedback_ref: str | None = None,
    reason_code: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    base = resolve_root(root)
    head = derive_portfolio_head(base)
    if head.period_root is None or head.phase != PortfolioPeriodPhase.SETTLED:
        raise StoreError("portfolio-feedback requires a settled head without feedback")
    settled = load_settled(head.period_root)
    outcome = load_outcome(head.period_root)
    feedback: AccountFeedback = seal_account_feedback(
        feedback_ref=feedback_ref or f"feedback.{settled.episode_ref}",
        kind=kind,
        period_index=head.period_index,
        settled=settled,
        outcome=outcome,
        reason_code=reason_code,
        notes=notes,
    )
    write_feedback_exclusive(head.period_root, feedback)
    period_receipt = _receipt_base(
        root=head.period_root,
        phase=PortfolioPeriodPhase.FEEDBACK_SEALED,
        period_index=head.period_index,
        episode_ref=settled.episode_ref,
        feedback_hash=feedback.content_hash,
        closing_balance=settled.statement.closing_balance,
        next_action="portfolio-freeze",
    )
    write_receipt_exclusive_or_replace(head.period_root, period_receipt, replace=True)
    write_manifest(head.period_root)
    root_receipt = _receipt_base(
        root=base,
        phase=PortfolioPeriodPhase.FEEDBACK_SEALED,
        head_period_index=head.period_index,
        period_root=str(head.period_root),
        episode_ref=settled.episode_ref,
        feedback_hash=feedback.content_hash,
        closing_balance=settled.statement.closing_balance,
        next_action="portfolio-freeze",
    )
    write_receipt_exclusive_or_replace(base, root_receipt, replace=True)
    write_portfolio_manifest(base)
    return {
        "ok": True,
        "phase": PortfolioPeriodPhase.FEEDBACK_SEALED.value,
        "root": str(base),
        "period_root": str(head.period_root),
        "period_index": head.period_index,
        "episode_ref": settled.episode_ref,
        "feedback_hash": feedback.content_hash,
        "closing_balance": settled.statement.closing_balance,
        "scientific_promotion": False,
        "claim_grade_delta": None,
        "first_episode_verified": False,
        "completion_claim_allowed": False,
        "next_action": "portfolio-freeze",
    }


def replay_portfolio_period(*, root: Path, period_index: int) -> dict[str, Any]:
    base = resolve_root(root)
    head = derive_portfolio_head(base)
    if period_index < 1 or period_index > head.period_index:
        raise StoreError("portfolio-replay period_index is outside the sealed history")
    period_root = period_directory(base, period_index)
    if detect_phase(period_root) != EpisodePhase.SETTLED:
        raise StoreError("portfolio-replay requires a settled period")
    result = replay_episode(root=period_root, _continuity_internal=True)
    return {
        **result,
        "root": str(base),
        "period_root": str(period_root),
        "period_index": period_index,
        "scientific_promotion": False,
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

    portfolio_init_cmd = commands.add_parser(
        "portfolio-init", help="Create an immutable same-seat continuity root"
    )
    portfolio_init_cmd.add_argument("--root", type=Path, required=True)
    portfolio_init_cmd.add_argument("--seat-id", required=True)
    portfolio_init_cmd.add_argument("--portfolio-ref", required=True)
    portfolio_init_cmd.add_argument("--opening-balance")

    portfolio_inspect_cmd = commands.add_parser(
        "portfolio-inspect", help="Validate the full contiguous history and derive its head"
    )
    portfolio_inspect_cmd.add_argument("--root", type=Path, required=True)

    portfolio_freeze_cmd = commands.add_parser(
        "portfolio-freeze", help="Freeze the only legal next prospective period"
    )
    portfolio_freeze_cmd.add_argument("--root", type=Path, required=True)
    portfolio_freeze_cmd.add_argument("--request", type=Path, required=True)

    portfolio_settle_cmd = commands.add_parser(
        "portfolio-settle", help="Settle the current period with an explicit outcome"
    )
    portfolio_settle_cmd.add_argument("--root", type=Path, required=True)
    portfolio_settle_cmd.add_argument("--outcome", type=Path, required=True)
    portfolio_settle_cmd.add_argument("--settlement-ref")
    portfolio_settle_cmd.add_argument("--settlement-journal-group-ref")
    portfolio_settle_cmd.add_argument("--statement-ref")
    portfolio_settle_cmd.add_argument("--occurred-at")

    portfolio_feedback_cmd = commands.add_parser(
        "portfolio-feedback", help="Seal typed feedback before the next period"
    )
    portfolio_feedback_cmd.add_argument("--root", type=Path, required=True)
    portfolio_feedback_cmd.add_argument(
        "--kind",
        type=FeedbackKind,
        choices=list(FeedbackKind),
        required=True,
    )
    portfolio_feedback_cmd.add_argument("--feedback-ref")
    portfolio_feedback_cmd.add_argument("--reason-code")
    portfolio_feedback_cmd.add_argument("--notes", default="")

    portfolio_replay_cmd = commands.add_parser(
        "portfolio-replay", help="Replay one settled period after validating the full chain"
    )
    portfolio_replay_cmd.add_argument("--root", type=Path, required=True)
    portfolio_replay_cmd.add_argument("--period-index", type=int, required=True)
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
    if args.command == "portfolio-init":
        return init_portfolio(
            root=args.root,
            seat_id=args.seat_id,
            portfolio_ref=args.portfolio_ref,
            opening_balance=args.opening_balance,
        )
    if args.command == "portfolio-inspect":
        return inspect_portfolio(root=args.root)
    if args.command == "portfolio-freeze":
        return freeze_portfolio_period(root=args.root, request_path=args.request)
    if args.command == "portfolio-settle":
        return settle_portfolio_period(
            root=args.root,
            outcome_path=args.outcome,
            settlement_ref=args.settlement_ref,
            settlement_journal_group_ref=args.settlement_journal_group_ref,
            statement_ref=args.statement_ref,
            occurred_at=args.occurred_at,
        )
    if args.command == "portfolio-feedback":
        return feedback_portfolio_period(
            root=args.root,
            kind=args.kind,
            feedback_ref=args.feedback_ref,
            reason_code=args.reason_code,
            notes=args.notes,
        )
    if args.command == "portfolio-replay":
        return replay_portfolio_period(root=args.root, period_index=args.period_index)
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
