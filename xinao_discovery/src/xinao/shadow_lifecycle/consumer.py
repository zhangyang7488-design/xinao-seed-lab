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
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.cli_json import print_cli_json
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
CONSUMER_VERSION = "0.3.1"

# Production portfolio freeze requires a disposition-bound owner authority envelope.
# Labels / private underscores are not security boundaries — this is a structural gate.
OWNER_FREEZE_AUTHORITY_SCHEMA: Final = "xinao.owner_freeze_authority.v1"
OWNER_FREEZE_AUTHORITY_MARKER: Final = "XINAO_OWNER_FREEZE_AUTHORITY_V1"
_OWNER_FREEZE_AUTHORITY_FIELDS: Final = frozenset(
    {
        "schema_version",
        "authority_marker",
        "owner_state_root",
        "research_pool_root",
        "owner_disposition_sha256",
        "research_binding_sha256",
        "request_content_hash",
    }
)
_OWNER_FREEZE_ACTOR_AUTHORITY_FIELDS: Final = _OWNER_FREEZE_AUTHORITY_FIELDS | frozenset(
    {"research_episode_root", "source_authority_root"}
)
_RESEARCH_BINDING_SCHEMA: Final = "xinao.research_freeze_binding.v1"
_RESEARCH_BINDING_MARKER: Final = "XINAO_RESEARCH_FREEZE_BINDING_V1"
_DISPOSITION_SCHEMA: Final = "xinao.codex_owner_disposition.v1"
_DISPOSITION_MARKER: Final = "XINAO_CODEX_OWNER_DISPOSITION_V1"
_POOL_ENTRY_SCHEMA: Final = "xinao.research_candidate_pool_entry.v1"
_POOL_ENTRY_MARKER: Final = "XINAO_RESEARCH_CANDIDATE_POOL_V1"
_EPISODE_EXPORT_INGEST_KIND: Final = "EPISODE_EXPORT_MANIFEST"
_EPISODE_MANIFEST_SCHEMA: Final = "xinao.research_episode_candidate_manifest.v1"
_EPISODE_MANIFEST_MARKER: Final = "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1"
_RESEARCHER_ACTION_BINDING_SCHEMA: Final = "xinao.researcher_action_binding.v1"
_RESEARCHER_NO_ACTION_BINDING_SCHEMA: Final = "xinao.researcher_no_action_binding.v1"
_SCIENCE_DISPOSITIONS: Final = frozenset(
    {"ADOPT", "RETAIN_FOR_SHADOW", "REJECT", "DEFER"}
)
_FREEZE_AUTHORIZING_DISPOSITIONS: Final = frozenset({"ADOPT", "RETAIN_FOR_SHADOW"})
_DISPOSITION_ALLOWED_FIELDS: Final = frozenset(
    {
        "schema_version",
        "disposition_marker",
        "disposition_source",
        "owner_role",
        "worker_controlled",
        "result_sha256",
        "receipt_content_sha256",
        "pool_entry_content_hash",
        "period_index",
        "episode_ref",
        "target_ref",
        "knowledge_cutoff",
        "science_disposition",
        "account_identity",
        "executable_account_decision",
        "no_action_period_binding",
        "portfolio_binding",
        "source_authority_binding",
        "rationale_ref",
        "science_identity",
    }
)
_FORBIDDEN_OUTCOME_FIELDS: Final = frozenset(
    {
        "outcome",
        "settlement",
        "settled",
        "actual_special_number",
        "future_outcome",
        "future_settlement",
        "next_period_outcome",
        "unrevealed_outcome",
        "peeked_outcome",
        "peeked_settlement",
        "peeked_result",
        "peeked_special_number",
        "public_outcome",
        "settled_episode",
        "account_pnl",
        "realized_pnl",
    }
)
_RESEARCHER_EXECUTABLE_CORE: Final = frozenset(
    {
        "panel",
        "selected_number",
        "stake",
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "knowledge_cutoff",
        "odds_version_ref",
        "baseline_ref",
        "risk_policy_ref",
        "rule_ref",
    }
)
_RESEARCHER_NO_ACTION_CORE: Final = frozenset(
    {
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "knowledge_cutoff",
        "rule_ref",
        "odds_version_ref",
    }
)
_OWNER_EXECUTABLE_ALLOWED: Final = frozenset(
    {
        *_RESEARCHER_EXECUTABLE_CORE,
        "frozen_at",
        "ticket_ref",
        "information_set_ref",
    }
)
_NO_ACTION_BINDING_ALLOWED: Final = frozenset(
    {
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "frozen_at",
        "knowledge_cutoff",
        "rule_ref",
        "odds_version_ref",
    }
)
_PORTFOLIO_BINDING_FIELDS: Final = frozenset(
    {
        "portfolio_ref",
        "portfolio_content_hash",
        "seat_id",
        "seat_content_hash",
        "head_period_index",
        "head_phase",
        "prior_settled_episode_hash",
        "prior_feedback_hash",
        "intended_next_period_index",
    }
)
_SOURCE_AUTHORITY_BINDING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "packet_content_hash",
        "source_id",
        "contract_sha256",
        "target_ref",
        "target_expect",
        "target_guard_open_time",
        "freeze_deadline",
        "latest_completed_expect",
        "capture_sha256",
    }
)
_RESEARCH_BINDING_FIELDS: Final = frozenset(
    {
        "schema_version",
        "binding_marker",
        "result_sha256",
        "receipt_content_sha256",
        "pool_entry_content_hash",
        "policy_ref",
        "owner_artifact_sha256",
        "period_index",
        "episode_ref",
        "target_ref",
        "science_disposition",
        "account_identity",
        "science_identity",
        "knowledge_cutoff",
        "executable_account_intent",
        "researcher_action_binding",
        "portfolio_binding",
        "source_authority_binding",
        "scientific_promotion",
        "owner_adopted",
    }
)
RESEARCH_BINDING_REF_PREFIX: Final = "research-binding.sha256:"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPECT_RE = re.compile(r"^\d{7}$")
_LIVE_TARGET_RE = re.compile(r"^macaujc2/expect/(\d{7})$")
_BINDING_REF_RE = re.compile(rf"{re.escape(RESEARCH_BINDING_REF_PREFIX)}([0-9a-f]{{64}})")
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


def _strict_json_object(raw: bytes, *, reason: str) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"duplicate key {key!r}")
            obj[key] = value
        return obj

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StoreError(f"{reason}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise StoreError(f"{reason}: object required")
    return parsed


def _reject_disposition_outcome_material(node: object, *, path: str = "$") -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            field = str(key).lower()
            if (
                field in _FORBIDDEN_OUTCOME_FIELDS
                or field.startswith("peeked_")
                or field.startswith("future_")
            ):
                raise StoreError(f"OWNER_DISPOSITION_OUTCOME_MATERIAL_FORBIDDEN: {path}.{key}")
            _reject_disposition_outcome_material(value, path=f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_disposition_outcome_material(value, path=f"{path}[{index}]")


def _pool_object_path(pool_root: Path, kind: str, digest: str, suffix: str) -> Path:
    result_sha = _require_hex64(digest, "result_sha256")
    return pool_root / "objects" / kind / result_sha[:2] / f"{result_sha}.{suffix}"


def _normalized_researcher_core(raw: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if set(raw) != _RESEARCHER_EXECUTABLE_CORE:
        missing = sorted(_RESEARCHER_EXECUTABLE_CORE - set(raw))
        unknown = sorted(set(raw) - _RESEARCHER_EXECUTABLE_CORE)
        raise StoreError(
            "PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: "
            f"{label}; missing={missing}; unknown={unknown}"
        )
    core = dict(raw)
    number = core.get("selected_number")
    if type(number) is not int or not 1 <= number <= 49:
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: selected_number")
    panel = core.get("panel")
    if panel not in {"A", "B"}:
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: panel")
    if core.get("baseline_ref") != ("BO0001" if panel == "A" else "BO0013"):
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: baseline_ref")
    stake = core.get("stake")
    if not isinstance(stake, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{4}", stake) is None:
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: stake")
    try:
        if Decimal(stake) <= 0:
            raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: stake")
    except InvalidOperation as exc:
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: stake") from exc
    for key in (
        "target_ref",
        "odds_version_ref",
        "risk_policy_ref",
        "rule_ref",
    ):
        if not isinstance(core.get(key), str) or not str(core[key]).strip():
            raise StoreError(f"PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: {key}")
    if core.get("rule_ref") != "special-number-rule.v1":
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: rule_ref")
    for key in ("target_open_time", "freeze_deadline", "knowledge_cutoff"):
        try:
            core[key] = _iso_z(_parse_time(core[key]))
        except (TypeError, ValueError, StoreError) as exc:
            raise StoreError(
                f"PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: {key}: {exc}"
            ) from exc
    if not (
        _parse_time(core["knowledge_cutoff"])
        <= _parse_time(core["freeze_deadline"])
        < _parse_time(core["target_open_time"])
    ):
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_INVALID: temporal_order")
    return {key: core[key] for key in sorted(_RESEARCHER_EXECUTABLE_CORE)}


def _validate_owner_executable(raw: Mapping[str, Any]) -> dict[str, Any]:
    missing = sorted(({*_RESEARCHER_EXECUTABLE_CORE, "frozen_at"}) - set(raw))
    unknown = sorted(set(raw) - _OWNER_EXECUTABLE_ALLOWED)
    if missing or unknown:
        raise StoreError(
            f"OWNER_DISPOSITION_EXECUTABLE_INVALID: missing={missing}; unknown={unknown}"
        )
    core = _normalized_researcher_core(
        {key: raw[key] for key in _RESEARCHER_EXECUTABLE_CORE},
        label="owner disposition executable_account_decision",
    )
    try:
        frozen_at = _parse_time(raw["frozen_at"])
    except (TypeError, ValueError, StoreError) as exc:
        raise StoreError(f"OWNER_DISPOSITION_EXECUTABLE_INVALID: frozen_at: {exc}") from exc
    cutoff = _parse_time(core["knowledge_cutoff"])
    deadline = _parse_time(core["freeze_deadline"])
    target_open = _parse_time(core["target_open_time"])
    if not (cutoff <= frozen_at <= deadline < target_open):
        raise StoreError("OWNER_DISPOSITION_EXECUTABLE_TEMPORAL_VIOLATION")
    normalized = {
        **core,
        "frozen_at": _iso_z(frozen_at),
        "ticket_ref": raw.get("ticket_ref"),
        "information_set_ref": raw.get("information_set_ref"),
    }
    return normalized


def _validate_no_action_binding(raw: Mapping[str, Any]) -> dict[str, Any]:
    missing = sorted(_NO_ACTION_BINDING_ALLOWED - set(raw))
    unknown = sorted(set(raw) - _NO_ACTION_BINDING_ALLOWED)
    if missing or unknown:
        raise StoreError(
            f"OWNER_DISPOSITION_NO_ACTION_BINDING_INVALID: missing={missing}; unknown={unknown}"
        )
    for key in ("target_ref", "rule_ref", "odds_version_ref"):
        if not isinstance(raw.get(key), str) or not str(raw[key]).strip():
            raise StoreError(f"OWNER_DISPOSITION_NO_ACTION_BINDING_INVALID: {key}")
    if raw.get("rule_ref") != "special-number-rule.v1":
        raise StoreError("OWNER_DISPOSITION_NO_ACTION_BINDING_INVALID: rule_ref")
    try:
        cutoff = _parse_time(raw["knowledge_cutoff"])
        frozen_at = _parse_time(raw["frozen_at"])
        deadline = _parse_time(raw["freeze_deadline"])
        target_open = _parse_time(raw["target_open_time"])
    except (TypeError, ValueError, StoreError) as exc:
        raise StoreError(f"OWNER_DISPOSITION_NO_ACTION_BINDING_INVALID: time: {exc}") from exc
    if not (cutoff <= frozen_at <= deadline < target_open):
        raise StoreError("OWNER_DISPOSITION_NO_ACTION_TEMPORAL_VIOLATION")
    return {
        "target_ref": str(raw["target_ref"]),
        "target_open_time": _iso_z(target_open),
        "freeze_deadline": _iso_z(deadline),
        "frozen_at": _iso_z(frozen_at),
        "knowledge_cutoff": _iso_z(cutoff),
        "rule_ref": str(raw["rule_ref"]),
        "odds_version_ref": str(raw["odds_version_ref"]),
    }


def _normalized_researcher_no_action_core(
    raw: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    """Validate the researcher-authored NO_ACTION core before host frozen_at."""

    if set(raw) != _RESEARCHER_NO_ACTION_CORE:
        missing = sorted(_RESEARCHER_NO_ACTION_CORE - set(raw))
        unknown = sorted(set(raw) - _RESEARCHER_NO_ACTION_CORE)
        raise StoreError(
            "PRODUCTION_FREEZE_RESEARCHER_NO_ACTION_INVALID: "
            f"{label}; missing={missing}; unknown={unknown}"
        )
    normalized = _validate_no_action_binding({**dict(raw), "frozen_at": raw["freeze_deadline"]})
    return {key: normalized[key] for key in sorted(_RESEARCHER_NO_ACTION_CORE)}


def _validate_source_authority_binding_local(raw: Mapping[str, Any]) -> dict[str, Any]:
    missing = sorted(_SOURCE_AUTHORITY_BINDING_FIELDS - set(raw))
    unknown = sorted(set(raw) - _SOURCE_AUTHORITY_BINDING_FIELDS)
    if missing or unknown:
        raise StoreError(f"SOURCE_AUTHORITY_BINDING_INVALID: missing={missing}; unknown={unknown}")
    if raw.get("schema_version") != "xinao.source_authority_binding.v1":
        raise StoreError("SOURCE_AUTHORITY_BINDING_SCHEMA_DRIFT")
    if raw.get("source_id") != "macaujc2":
        raise StoreError("SOURCE_AUTHORITY_BINDING_SOURCE_MISMATCH")
    for key in ("packet_content_hash", "contract_sha256", "capture_sha256"):
        _require_hex64(raw.get(key), key)
    target_ref = raw.get("target_ref")
    target_expect = raw.get("target_expect")
    latest = raw.get("latest_completed_expect")
    if (
        not isinstance(target_ref, str)
        or not isinstance(target_expect, str)
        or _EXPECT_RE.fullmatch(target_expect) is None
        or target_ref != f"macaujc2/expect/{target_expect}"
    ):
        raise StoreError("SOURCE_AUTHORITY_BINDING_TARGET_MISMATCH")
    if not isinstance(latest, str) or _EXPECT_RE.fullmatch(latest) is None:
        raise StoreError("SOURCE_AUTHORITY_BINDING_LATEST_INVALID")
    guard = _parse_time(raw.get("target_guard_open_time"))
    deadline = _parse_time(raw.get("freeze_deadline"))
    if deadline >= guard:
        raise StoreError("SOURCE_AUTHORITY_BINDING_TEMPORAL_VIOLATION")
    return {
        "schema_version": "xinao.source_authority_binding.v1",
        "packet_content_hash": str(raw["packet_content_hash"]),
        "source_id": "macaujc2",
        "contract_sha256": str(raw["contract_sha256"]),
        "target_ref": target_ref,
        "target_expect": target_expect,
        "target_guard_open_time": _iso_z(guard),
        "freeze_deadline": _iso_z(deadline),
        "latest_completed_expect": latest,
        "capture_sha256": str(raw["capture_sha256"]),
    }


def _load_pool_and_research_source(
    *,
    research_pool_root: Path,
    result_sha256: str,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, str]]:
    """Independently read pool CAS and the producer bytes needed by freeze.

    This intentionally lives in the import-closed shadow runtime cone. It does
    not mint candidates or adopt science; it only verifies the already-sealed
    bytes required to reject a caller-constructed ACTION chain.
    """

    digest = _require_hex64(result_sha256, "result_sha256")
    pool_root = research_pool_root.expanduser().resolve()
    entry_path = _pool_object_path(pool_root, "sha256", digest, "json")
    result_path = _pool_object_path(pool_root, "result", digest, "bin")
    receipt_path = _pool_object_path(pool_root, "receipt", digest, "json")
    for path, label in (
        (entry_path, "POOL_ENTRY_MISSING"),
        (result_path, "POOL_RESULT_MISSING"),
        (receipt_path, "POOL_RECEIPT_MISSING"),
    ):
        if not path.is_file():
            raise StoreError(f"PRODUCTION_FREEZE_{label}: {path}")

    entry_raw = entry_path.read_bytes()
    entry = _strict_json_object(entry_raw, reason="PRODUCTION_FREEZE_POOL_ENTRY_INVALID")
    if entry.get("schema_version") != _POOL_ENTRY_SCHEMA:
        raise StoreError("PRODUCTION_FREEZE_POOL_ENTRY_SCHEMA_DRIFT")
    if entry.get("pool_marker") != _POOL_ENTRY_MARKER:
        raise StoreError("PRODUCTION_FREEZE_POOL_ENTRY_MARKER_INVALID")
    if entry.get("result_sha256") != digest:
        raise StoreError("PRODUCTION_FREEZE_POOL_ENTRY_RESULT_MISMATCH")
    for field in (
        "owner_adopted",
        "completion_claim_allowed",
        "scientific_promotion",
        "decision_map_projected",
    ):
        if entry.get(field) is not False:
            raise StoreError(f"PRODUCTION_FREEZE_POOL_ENTRY_FLAG_INVALID: {field}")
    claimed_entry_hash = _require_hex64(entry.get("content_hash"), "pool_entry_content_hash")
    entry_body = dict(entry)
    entry_body.pop("content_hash", None)
    if canonical_sha256(entry_body) != claimed_entry_hash:
        raise StoreError("PRODUCTION_FREEZE_POOL_ENTRY_SEAL_INVALID")

    result_raw = result_path.read_bytes()
    if _raw_sha256(result_raw) != digest:
        raise StoreError("PRODUCTION_FREEZE_POOL_RESULT_BYTES_TAMPERED")
    receipt_raw = receipt_path.read_bytes()
    receipt_raw_hash = _raw_sha256(receipt_raw)
    if receipt_raw_hash != entry.get("receipt_raw_sha256"):
        raise StoreError("PRODUCTION_FREEZE_POOL_RECEIPT_BYTES_TAMPERED")

    if entry.get("ingest_kind") == _EPISODE_EXPORT_INGEST_KIND:
        export = _strict_json_object(
            result_raw,
            reason="PRODUCTION_FREEZE_EPISODE_EXPORT_INVALID",
        )
        manifest = _strict_json_object(
            receipt_raw,
            reason="PRODUCTION_FREEZE_EPISODE_MANIFEST_INVALID",
        )
        manifest_hash = receipt_raw_hash
        if (
            manifest.get("schema_version") != _EPISODE_MANIFEST_SCHEMA
            or manifest.get("manifest_marker") != _EPISODE_MANIFEST_MARKER
        ):
            raise StoreError("PRODUCTION_FREEZE_EPISODE_MANIFEST_IDENTITY_INVALID")
        for field in (
            "receipt_content_sha256",
            "receipt_raw_sha256",
            "candidate_manifest_sha256",
        ):
            if entry.get(field) != manifest_hash:
                raise StoreError(f"PRODUCTION_FREEZE_EPISODE_MANIFEST_HASH_MISMATCH: {field}")
        if export.get("candidate_manifest_sha256") != manifest_hash:
            raise StoreError("PRODUCTION_FREEZE_EPISODE_EXPORT_MANIFEST_MISMATCH")
        recommendation = manifest.get("account_recommendation")
        if recommendation == "NO_RECOMMENDATION":
            raise StoreError(
                "PRODUCTION_FREEZE_RESEARCHER_DECISION_SOURCE_ABSENT: signal-only candidate"
            )
        if recommendation in {"ACTION_CANDIDATE", "NO_ACTION_CANDIDATE"}:
            raise StoreError(
                "PRODUCTION_FREEZE_ACTOR_REALITY_ROOTS_REQUIRED: "
                "ResearchEpisode proposed is actor-only intent and must be "
                "projected from live reality"
            )
        raise StoreError(
            "PRODUCTION_FREEZE_EPISODE_RECOMMENDATION_INVALID: "
            f"{recommendation!r}"
        )
    else:
        result = _strict_json_object(
            result_raw,
            reason="PRODUCTION_FREEZE_RESEARCH_RESULT_INVALID",
        )
        receipt = _strict_json_object(
            receipt_raw,
            reason="PRODUCTION_FREEZE_RESEARCH_RECEIPT_INVALID",
        )
        if receipt.get("result_sha256") != digest:
            raise StoreError("PRODUCTION_FREEZE_RESULT_RECEIPT_HASH_MISMATCH")
        candidate = result.get("candidate")
        receipt_candidate = receipt.get("candidate")
        if not isinstance(candidate, Mapping) or not isinstance(receipt_candidate, Mapping):
            raise StoreError("PRODUCTION_FREEZE_RESEARCH_CANDIDATE_MISSING")
        if canonical_sha256(candidate) != canonical_sha256(receipt_candidate):
            raise StoreError("PRODUCTION_FREEZE_RESULT_RECEIPT_CANDIDATE_MISMATCH")
        if canonical_sha256(candidate) != canonical_sha256(entry.get("candidate")):
            raise StoreError("PRODUCTION_FREEZE_POOL_CANDIDATE_MISMATCH")
        if result.get("status") != entry.get("status"):
            raise StoreError("PRODUCTION_FREEZE_POOL_STATUS_MISMATCH")
        producer = candidate
        source = {
            "source_kind": "ONESHOT_RESEARCH_RESULT",
            "source_artifact_sha256": digest,
        }

    if not isinstance(producer, Mapping):
        raise StoreError("PRODUCTION_FREEZE_RESEARCHER_DECISION_SOURCE_ABSENT")
    authored_action = producer.get("executable_account_decision")
    authored_no_action = producer.get("no_action_intent")
    has_action = isinstance(authored_action, Mapping)
    has_no_action = isinstance(authored_no_action, Mapping)
    if not has_action and not has_no_action:
        raise StoreError(
            "PRODUCTION_FREEZE_RESEARCHER_DECISION_SOURCE_ABSENT: signal-only candidate"
        )
    if has_action and has_no_action:
        raise StoreError(
            "PRODUCTION_FREEZE_RESEARCHER_DECISION_BRANCH_INVALID: "
            "exactly one executable_account_decision or no_action_intent required"
        )
    account_identity = _ACCOUNT_ACTION if has_action else _ACCOUNT_NO_ACTION
    declared_identity = producer.get("account_identity")
    if declared_identity is not None and declared_identity != account_identity:
        raise StoreError(
            "PRODUCTION_FREEZE_RESEARCHER_DECISION_IDENTITY_CONFLICT: "
            f"declared={declared_identity!r} branch={account_identity!r}"
        )
    if has_action:
        source["source_json_path"] = "$.proposed.executable_account_decision" if entry.get(
            "ingest_kind"
        ) == _EPISODE_EXPORT_INGEST_KIND else "$.candidate.executable_account_decision"
        assert isinstance(authored_action, Mapping)
        authored_core = _normalized_researcher_core(
            authored_action, label=source["source_json_path"]
        )
    else:
        source["source_json_path"] = "$.proposed.no_action_intent" if entry.get(
            "ingest_kind"
        ) == _EPISODE_EXPORT_INGEST_KIND else "$.candidate.no_action_intent"
        assert isinstance(authored_no_action, Mapping)
        authored_core = _normalized_researcher_no_action_core(
            authored_no_action, label=source["source_json_path"]
        )
    return entry, account_identity, authored_core, source


def _load_verified_disposition_for_freeze(
    *,
    disposition_path: Path,
    owner_state_root: Path,
    research_pool_root: Path,
    disposition_sha256: str,
    research_episode_root: Path | None = None,
    portfolio_root: Path | None = None,
    source_authority_root: Path | None = None,
) -> dict[str, Any]:
    digest = _require_hex64(disposition_sha256, "owner_disposition_sha256")
    owner_root = owner_state_root.expanduser().resolve()
    pool_root = research_pool_root.expanduser().resolve()
    if (
        owner_root == pool_root
        or owner_root.is_relative_to(pool_root)
        or pool_root.is_relative_to(owner_root)
    ):
        raise StoreError("PRODUCTION_FREEZE_OWNER_POOL_ROOTS_NOT_SEPARATED")
    # ``portfolio_root`` is always supplied by the portfolio consumer, including
    # the historical one-shot path.  Only the two explicit Episode-reality roots
    # select the fresh actor-projection verifier.
    actor_roots_supplied = any(
        value is not None for value in (research_episode_root, source_authority_root)
    )
    if actor_roots_supplied:
        if (
            research_episode_root is None
            or portfolio_root is None
            or source_authority_root is None
        ):
            raise StoreError("PRODUCTION_ACTOR_REALITY_ROOTS_INCOMPLETE")
        # Reuse the Owner verifier, but invoke it again inside the final consumer
        # so current attempt/material/portfolio/authority are freshly re-read at
        # the actual freeze boundary.
        try:
            from xinao.science.owner_disposition import (
                OwnerDispositionError,
                load_and_verify_disposition,
            )

            verified = load_and_verify_disposition(
                disposition_path=disposition_path,
                owner_state_root=owner_root,
                pool_root=pool_root,
                result_sha256=None,
                episode_root=research_episode_root,
                portfolio_root=portfolio_root,
                authority_root=source_authority_root,
            )
        except (OwnerDispositionError, OSError, ValueError) as exc:
            raise StoreError(f"PRODUCTION_FREEZE_ACTOR_PROJECTION_REJECTED: {exc}") from exc
        disposition = verified["disposition"]
        if disposition.get("science_disposition") not in _FREEZE_AUTHORIZING_DISPOSITIONS:
            raise StoreError("OWNER_DISPOSITION_NOT_ADOPTED")
        return {
            "disposition": disposition,
            "pool_entry": verified["pool_entry"],
            "researcher_decision_binding": verified["researcher_decision_binding"],
        }
    expected_path = _disposition_cas_path(owner_root, digest)
    path = disposition_path.expanduser().resolve()
    if path != expected_path or not path.is_file():
        raise StoreError(f"OWNER_DISPOSITION_CAS_MISSING_OR_MISPLACED: {path}")
    raw = path.read_bytes()
    if _raw_sha256(raw) != digest:
        raise StoreError(f"OWNER_DISPOSITION_BYTES_TAMPERED: {digest}")
    disposition = _strict_json_object(raw, reason="OWNER_DISPOSITION_JSON_INVALID")
    unknown = sorted(set(disposition) - _DISPOSITION_ALLOWED_FIELDS)
    if unknown:
        raise StoreError(f"OWNER_DISPOSITION_UNKNOWN_FIELDS: {unknown}")
    _reject_disposition_outcome_material(disposition)
    if disposition.get("schema_version") != _DISPOSITION_SCHEMA:
        raise StoreError("OWNER_DISPOSITION_SCHEMA_DRIFT")
    if disposition.get("disposition_marker") != _DISPOSITION_MARKER:
        raise StoreError("OWNER_DISPOSITION_MARKER_INVALID")
    if disposition.get("disposition_source") != "codex_owner_channel":
        raise StoreError("OWNER_DISPOSITION_SOURCE_NOT_OWNER_CHANNEL")
    if disposition.get("owner_role") != "codex":
        raise StoreError("OWNER_DISPOSITION_OWNER_ROLE_INVALID")
    if disposition.get("worker_controlled") is not False:
        raise StoreError("OWNER_DISPOSITION_WORKER_CONTROLLED")
    if "science_identity" in disposition:
        raise StoreError("SCIENCE_IDENTITY_CALLER_OVERRIDE_FORBIDDEN")

    result_sha = _require_hex64(disposition.get("result_sha256"), "result_sha256")
    pool_entry, researcher_identity, authored_core, source = _load_pool_and_research_source(
        research_pool_root=pool_root,
        result_sha256=result_sha,
    )
    for field, entry_field in (
        ("result_sha256", "result_sha256"),
        ("receipt_content_sha256", "receipt_content_sha256"),
        ("pool_entry_content_hash", "content_hash"),
    ):
        if disposition.get(field) != pool_entry.get(entry_field):
            raise StoreError(f"OWNER_DISPOSITION_POOL_BINDING_MISMATCH: {field}")

    science_disposition = disposition.get("science_disposition")
    if science_disposition not in _SCIENCE_DISPOSITIONS:
        raise StoreError("OWNER_DISPOSITION_SCIENCE_DISPOSITION_INVALID")
    if science_disposition not in _FREEZE_AUTHORIZING_DISPOSITIONS:
        raise StoreError("OWNER_DISPOSITION_NOT_ADOPTED")
    account_identity = disposition.get("account_identity")
    if account_identity not in {_ACCOUNT_ACTION, _ACCOUNT_NO_ACTION}:
        raise StoreError("OWNER_DISPOSITION_ACCOUNT_IDENTITY_INVALID")
    if account_identity != researcher_identity:
        raise StoreError(
            "RESEARCHER_DECISION_IDENTITY_MISMATCH: "
            f"producer={researcher_identity} disposition={account_identity}"
        )
    period_index = disposition.get("period_index")
    if type(period_index) is not int or period_index < 1:
        raise StoreError("OWNER_DISPOSITION_PERIOD_INVALID")
    episode_ref = disposition.get("episode_ref")
    if not isinstance(episode_ref, str) or not episode_ref.strip():
        raise StoreError("OWNER_DISPOSITION_EPISODE_INVALID")
    try:
        outer_cutoff = _parse_time(disposition.get("knowledge_cutoff"))
    except (TypeError, ValueError, StoreError) as exc:
        raise StoreError(f"OWNER_DISPOSITION_KNOWLEDGE_CUTOFF_INVALID: {exc}") from exc
    outer_target = disposition.get("target_ref")
    if outer_target is not None and (not isinstance(outer_target, str) or not outer_target.strip()):
        raise StoreError("OWNER_DISPOSITION_TARGET_INVALID")
    normalized = copy.deepcopy(disposition)
    normalized["period_index"] = period_index
    normalized["episode_ref"] = episode_ref
    normalized["knowledge_cutoff"] = _iso_z(outer_cutoff)
    normalized["science_identity"] = (
        "SCIENCE_CANDIDATE" if account_identity == _ACCOUNT_ACTION else "POLICY_NO_ACTION"
    )

    if account_identity == _ACCOUNT_ACTION:
        if pool_entry.get("status") != "CANDIDATE_READY":
            raise StoreError("PRODUCTION_FREEZE_RESEARCHER_EXECUTABLE_STATUS_NOT_READY")
        executable = disposition.get("executable_account_decision")
        if not isinstance(executable, Mapping):
            raise StoreError("PRODUCTION_FREEZE_ACTION_EXECUTABLE_REQUIRED")
        normalized_executable = _validate_owner_executable(executable)
        disposition_core = {
            key: normalized_executable[key] for key in sorted(_RESEARCHER_EXECUTABLE_CORE)
        }
        if outer_target is not None and outer_target != normalized_executable["target_ref"]:
            raise StoreError("OWNER_DISPOSITION_TARGET_MISMATCH")
        if _iso_z(outer_cutoff) != normalized_executable["knowledge_cutoff"]:
            raise StoreError("OWNER_DISPOSITION_KNOWLEDGE_CUTOFF_MISMATCH")
        normalized["target_ref"] = normalized_executable["target_ref"]
        normalized["executable_account_decision"] = normalized_executable
        normalized["no_action_period_binding"] = None
        if authored_core != disposition_core:
            diverged = sorted(
                key
                for key in _RESEARCHER_EXECUTABLE_CORE
                if authored_core.get(key) != disposition_core.get(key)
            )
            raise StoreError(f"RESEARCHER_EXECUTABLE_DECISION_MISMATCH: fields={diverged}")
    else:
        if disposition.get("executable_account_decision") is not None:
            raise StoreError("OWNER_DISPOSITION_NO_ACTION_HAS_EXECUTABLE")
        no_action_raw = disposition.get("no_action_period_binding")
        if not isinstance(no_action_raw, Mapping):
            raise StoreError("OWNER_DISPOSITION_NO_ACTION_BINDING_REQUIRED")
        no_action = _validate_no_action_binding(no_action_raw)
        if outer_target is not None and outer_target != no_action["target_ref"]:
            raise StoreError("OWNER_DISPOSITION_TARGET_MISMATCH")
        if _iso_z(outer_cutoff) != no_action["knowledge_cutoff"]:
            raise StoreError("OWNER_DISPOSITION_KNOWLEDGE_CUTOFF_MISMATCH")
        normalized["target_ref"] = no_action["target_ref"]
        normalized["executable_account_decision"] = None
        normalized["no_action_period_binding"] = no_action
        disposition_core = {
            key: no_action[key] for key in sorted(_RESEARCHER_NO_ACTION_CORE)
        }
        if authored_core != disposition_core:
            diverged = sorted(
                key
                for key in _RESEARCHER_NO_ACTION_CORE
                if authored_core.get(key) != disposition_core.get(key)
            )
            raise StoreError(f"RESEARCHER_NO_ACTION_INTENT_MISMATCH: fields={diverged}")

    decision_hash = canonical_sha256(authored_core)
    if account_identity == _ACCOUNT_ACTION:
        decision_schema = _RESEARCHER_ACTION_BINDING_SCHEMA
        decision_hash_key = "executable_content_hash"
    else:
        decision_schema = _RESEARCHER_NO_ACTION_BINDING_SCHEMA
        decision_hash_key = "no_action_content_hash"
    verified_researcher_decision = {
        "schema_version": decision_schema,
        "account_identity": account_identity,
        **source,
        "decision_content_hash": decision_hash,
        decision_hash_key: decision_hash,
        "result_sha256": result_sha,
        "pool_entry_content_hash": str(pool_entry["content_hash"]),
    }

    portfolio_binding = disposition.get("portfolio_binding")
    if portfolio_binding is not None:
        if not isinstance(portfolio_binding, Mapping):
            raise StoreError("OWNER_DISPOSITION_PORTFOLIO_BINDING_INVALID")
        if set(portfolio_binding) != _PORTFOLIO_BINDING_FIELDS:
            raise StoreError("OWNER_DISPOSITION_PORTFOLIO_BINDING_FIELDS_INVALID")
        if portfolio_binding.get("intended_next_period_index") != period_index:
            raise StoreError("OWNER_DISPOSITION_PORTFOLIO_PERIOD_MISMATCH")
        for key in ("portfolio_content_hash", "seat_content_hash"):
            _require_hex64(portfolio_binding.get(key), key)
        for key in ("prior_settled_episode_hash", "prior_feedback_hash"):
            value = portfolio_binding.get(key)
            if value is not None:
                _require_hex64(value, key)
        normalized["portfolio_binding"] = copy.deepcopy(dict(portfolio_binding))

    source_authority = disposition.get("source_authority_binding")
    target_ref = str(normalized["target_ref"])
    live_target = _LIVE_TARGET_RE.fullmatch(target_ref) is not None
    if live_target and source_authority is None:
        raise StoreError("SOURCE_AUTHORITY_BINDING_REQUIRED")
    if source_authority is not None:
        if not isinstance(source_authority, Mapping):
            raise StoreError("SOURCE_AUTHORITY_BINDING_INVALID")
        normalized_source = _validate_source_authority_binding_local(source_authority)
        if normalized_source["target_ref"] != target_ref:
            raise StoreError("SOURCE_AUTHORITY_BINDING_TARGET_MISMATCH")
        branch = (
            normalized["executable_account_decision"]
            if account_identity == _ACCOUNT_ACTION
            else normalized["no_action_period_binding"]
        )
        if (
            branch["target_open_time"] != normalized_source["target_guard_open_time"]
            or branch["freeze_deadline"] != normalized_source["freeze_deadline"]
        ):
            raise StoreError("SOURCE_AUTHORITY_BINDING_PERIOD_MISMATCH")
        normalized["source_authority_binding"] = normalized_source
    else:
        normalized["source_authority_binding"] = None

    rationale_ref = disposition.get("rationale_ref") or "owner-disposition.rationale"
    if not isinstance(rationale_ref, str) or not rationale_ref.strip():
        raise StoreError("OWNER_DISPOSITION_RATIONALE_INVALID")
    normalized["rationale_ref"] = rationale_ref

    return {
        "disposition": normalized,
        "pool_entry": pool_entry,
        "researcher_decision_binding": verified_researcher_decision,
        "researcher_action_binding": (
            verified_researcher_decision if account_identity == _ACCOUNT_ACTION else None
        ),
    }


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
    payload = _strict_json_object(raw, reason="FREEZE_AUTHORITY_BINDING_JSON_INVALID")
    if set(payload) != _RESEARCH_BINDING_FIELDS:
        missing = sorted(_RESEARCH_BINDING_FIELDS - set(payload))
        unknown = sorted(set(payload) - _RESEARCH_BINDING_FIELDS)
        raise StoreError(
            f"FREEZE_AUTHORITY_BINDING_FIELDS_INVALID: missing={missing}; unknown={unknown}"
        )
    _reject_disposition_outcome_material(payload)
    if payload.get("schema_version") != _RESEARCH_BINDING_SCHEMA:
        raise StoreError(f"FREEZE_AUTHORITY_BINDING_SCHEMA_DRIFT: {payload.get('schema_version')}")
    if payload.get("binding_marker") != _RESEARCH_BINDING_MARKER:
        raise StoreError(
            f"FREEZE_AUTHORITY_BINDING_MARKER_INVALID: {payload.get('binding_marker')}"
        )
    if payload.get("scientific_promotion") is not False:
        raise StoreError("FREEZE_AUTHORITY_BINDING_SCIENTIFIC_PROMOTION_FORBIDDEN")
    if payload.get("owner_adopted") is not False:
        raise StoreError("FREEZE_AUTHORITY_BINDING_OWNER_ADOPTED_FORBIDDEN")
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
    science_identity = str(binding.get("science_identity") or "")
    if str(episode.science_decision.identity.value) != science_identity:
        raise StoreError(
            "FREEZE_AUTHORITY_SCIENCE_IDENTITY_MISMATCH: "
            f"episode={episode.science_decision.identity.value} binding={science_identity}"
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
    req_science = request.get("science_decision") or {}
    if not isinstance(req_science, Mapping):
        raise StoreError("FREEZE_AUTHORITY_REQUEST_SCIENCE_MISSING")
    for field, request_key in (
        ("science_identity", "identity"),
        ("knowledge_cutoff", "knowledge_cutoff"),
        ("rationale_ref", "rationale_ref"),
    ):
        if str(req_science.get(request_key)) != str(disposition.get(field)):
            raise StoreError(
                "FREEZE_AUTHORITY_DISPOSITION_SCIENCE_MISMATCH: "
                f"{request_key}: request={req_science.get(request_key)!r} "
                f"disposition={disposition.get(field)!r}"
            )
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
        # Period bind: open/deadline/cutoff must match sealed disposition.
        # frozen_at on the ticket is host freeze-action time (authoritative), not
        # the disposition seal label — do not accept backdated equality as proof.
        for time_field in ("target_open_time", "freeze_deadline", "knowledge_cutoff"):
            if str(ticket.get(time_field)) != str(executable.get(time_field)):
                raise StoreError(f"FREEZE_AUTHORITY_DISPOSITION_TICKET_MISMATCH: {time_field}")
        try:
            ticket_frozen = _parse_time(ticket.get("frozen_at"))
            disp_frozen = _parse_time(executable.get("frozen_at"))
            deadline = _parse_time(executable.get("freeze_deadline"))
        except (TypeError, ValueError) as exc:
            raise StoreError(
                f"FREEZE_AUTHORITY_DISPOSITION_TICKET_MISMATCH: frozen_at parse: {exc}"
            ) from exc
        if ticket_frozen > deadline:
            raise StoreError(
                "FREEZE_AUTHORITY_HOST_FREEZE_AFTER_DEADLINE: "
                f"ticket_frozen_at={ticket.get('frozen_at')} "
                f"deadline={executable.get('freeze_deadline')}"
            )
        if ticket_frozen < disp_frozen:
            raise StoreError(
                "FREEZE_AUTHORITY_HOST_FREEZE_BEFORE_DISPOSITION: "
                f"ticket_frozen_at={ticket.get('frozen_at')} "
                f"disposition_frozen_at={executable.get('frozen_at')}"
            )
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


def _expected_binding_intent(
    *,
    disposition: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild the exact freeze-binding intent from verified disposition + request."""

    account_identity = str(disposition["account_identity"])
    if account_identity == _ACCOUNT_ACTION:
        executable = disposition.get("executable_account_decision")
        ticket = request.get("bound_account_ticket")
        if not isinstance(executable, Mapping) or not isinstance(ticket, Mapping):
            raise StoreError("PRODUCTION_FREEZE_ACTION_EXECUTABLE_REQUIRED")
        intent: dict[str, Any] = {
            "account_identity": _ACCOUNT_ACTION,
            "panel": executable["panel"],
            "selected_number": executable["selected_number"],
            "stake": str(executable["stake"]),
            "rule_ref": str(executable["rule_ref"]),
            "odds_version_ref": str(executable["odds_version_ref"]),
            "baseline_ref": str(executable["baseline_ref"]),
            "risk_policy_ref": str(executable["risk_policy_ref"]),
            "target_ref": str(executable["target_ref"]),
            "target_open_time": str(executable["target_open_time"]),
            "freeze_deadline": str(executable["freeze_deadline"]),
            "frozen_at": _iso_z(_parse_time(ticket["frozen_at"])),
            "disposition_frozen_at": str(executable["frozen_at"]),
            "knowledge_cutoff": str(executable["knowledge_cutoff"]),
        }
        if executable.get("ticket_ref") is not None:
            intent["ticket_ref"] = str(executable["ticket_ref"])
        if executable.get("information_set_ref") is not None:
            intent["information_set_ref"] = str(executable["information_set_ref"])
        return intent

    binding = disposition.get("no_action_period_binding")
    if not isinstance(binding, Mapping):
        raise StoreError("PRODUCTION_FREEZE_NO_ACTION_BINDING_REQUIRED")
    return {
        "account_identity": _ACCOUNT_NO_ACTION,
        "selected_number": None,
        "stake": "0.0000",
        "rule_ref": str(binding["rule_ref"]),
        "odds_version_ref": str(binding["odds_version_ref"]),
        "target_ref": str(binding["target_ref"]),
        "target_open_time": str(binding["target_open_time"]),
        "freeze_deadline": str(binding["freeze_deadline"]),
        "frozen_at": _iso_z(_parse_time(request["frozen_at"])),
        "disposition_frozen_at": str(binding["frozen_at"]),
        "knowledge_cutoff": str(binding["knowledge_cutoff"]),
    }


def _require_and_verify_owner_freeze_authority(
    *,
    portfolio_root: Path,
    request: Mapping[str, Any],
    owner_authority: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate sealed Owner disposition/research-binding evidence for portfolio freeze.

    This is evidence validation against disposition CAS + live portfolio head, not
    cryptographic authentication of the Codex process. Physical Owner authority is
    host/container write-domain separation of ``owner_state_root`` (and absence of
    that root from researcher mounts). Import of this module alone is not an Owner
    channel.
    """

    if owner_authority is None:
        raise StoreError(
            "PRODUCTION_FREEZE_REQUIRES_OWNER_AUTHORITY: "
            "freeze_portfolio_period requires a sealed disposition-bound "
            "owner_authority envelope that reloads Owner disposition CAS "
            "and research-binding evidence"
        )
    if not isinstance(owner_authority, Mapping):
        raise StoreError("PRODUCTION_FREEZE_AUTHORITY_INVALID: owner_authority must be an object")
    authority = copy.deepcopy(dict(owner_authority))
    authority_fields = set(authority)
    if (
        authority_fields != _OWNER_FREEZE_AUTHORITY_FIELDS
        and authority_fields != _OWNER_FREEZE_ACTOR_AUTHORITY_FIELDS
    ):
        expected = (
            _OWNER_FREEZE_ACTOR_AUTHORITY_FIELDS
            if authority_fields & {"research_episode_root", "source_authority_root"}
            else _OWNER_FREEZE_AUTHORITY_FIELDS
        )
        missing = sorted(expected - authority_fields)
        unknown = sorted(authority_fields - expected)
        raise StoreError(
            f"PRODUCTION_FREEZE_AUTHORITY_FIELDS_INVALID: missing={missing}; unknown={unknown}"
        )

    if authority.get("schema_version") != OWNER_FREEZE_AUTHORITY_SCHEMA:
        raise StoreError(
            f"PRODUCTION_FREEZE_AUTHORITY_SCHEMA_DRIFT: {authority.get('schema_version')}"
        )
    if authority.get("authority_marker") != OWNER_FREEZE_AUTHORITY_MARKER:
        raise StoreError(
            f"PRODUCTION_FREEZE_AUTHORITY_MARKER_INVALID: {authority.get('authority_marker')}"
        )

    owner_state_root = Path(str(authority["owner_state_root"])).expanduser().resolve()
    research_pool_root = Path(str(authority["research_pool_root"])).expanduser().resolve()
    actor_authority = authority_fields == _OWNER_FREEZE_ACTOR_AUTHORITY_FIELDS
    research_episode_root = (
        Path(str(authority["research_episode_root"])).expanduser().resolve()
        if actor_authority
        else None
    )
    source_authority_root = (
        Path(str(authority["source_authority_root"])).expanduser().resolve()
        if actor_authority
        else None
    )
    disposition_sha = _require_hex64(
        authority.get("owner_disposition_sha256"),
        "owner_disposition_sha256",
    )
    binding_sha = _require_hex64(
        authority.get("research_binding_sha256"),
        "research_binding_sha256",
    )
    envelope_request_hash = _require_hex64(
        authority.get("request_content_hash"),
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

    # Independently re-open disposition + pool + producer bytes inside the
    # import-closed shadow runtime cone. A self-consistent caller-made
    # disposition and binding is therefore insufficient.
    if not owner_state_root.is_dir():
        raise StoreError(f"OWNER_STATE_ROOT_MISSING: {owner_state_root}")
    disp_path = _disposition_cas_path(owner_state_root, disposition_sha)
    try:
        verified_disposition = _load_verified_disposition_for_freeze(
            disposition_path=disp_path,
            owner_state_root=owner_state_root,
            research_pool_root=research_pool_root,
            disposition_sha256=disposition_sha,
            research_episode_root=research_episode_root,
            portfolio_root=portfolio_root,
            source_authority_root=source_authority_root,
        )
    except (StoreError, OSError, ValueError) as exc:
        raise StoreError(f"PRODUCTION_FREEZE_DISPOSITION_REJECTED: {exc}") from exc
    disposition = verified_disposition["disposition"]
    pool_entry = verified_disposition["pool_entry"]
    verified_researcher_decision = verified_disposition["researcher_decision_binding"]

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
    expected_binding = {
        "schema_version": _RESEARCH_BINDING_SCHEMA,
        "binding_marker": _RESEARCH_BINDING_MARKER,
        "result_sha256": str(pool_entry["result_sha256"]),
        "receipt_content_sha256": str(pool_entry["receipt_content_sha256"]),
        "pool_entry_content_hash": str(pool_entry["content_hash"]),
        "policy_ref": str(pool_entry["policy_ref"]),
        "owner_artifact_sha256": disposition_sha,
        "period_index": int(disposition["period_index"]),
        "episode_ref": str(disposition["episode_ref"]),
        "target_ref": str(disposition["target_ref"]),
        "science_disposition": str(disposition["science_disposition"]),
        "account_identity": str(disposition["account_identity"]),
        "science_identity": str(disposition["science_identity"]),
        "knowledge_cutoff": str(disposition["knowledge_cutoff"]),
        "executable_account_intent": _expected_binding_intent(
            disposition=disposition,
            request=request,
        ),
        # Transitional field name in the sealed binding; its value is symmetric
        # producer evidence for either ACTION or NO_ACTION.
        "researcher_action_binding": verified_researcher_decision,
        "portfolio_binding": live_pb,
        "source_authority_binding": disposition.get("source_authority_binding"),
        "scientific_promotion": False,
        "owner_adopted": False,
    }
    if binding != expected_binding:
        diverged = sorted(
            key for key in _RESEARCH_BINDING_FIELDS if binding.get(key) != expected_binding.get(key)
        )
        raise StoreError(f"PRODUCTION_FREEZE_BINDING_EVIDENCE_MISMATCH: fields={diverged}")

    # Bound owner artifact on request must match disposition CAS.
    bound_owner = request.get("bound_owner_artifact_sha256")
    if bound_owner is not None and str(bound_owner) != disposition_sha:
        raise StoreError(
            "PRODUCTION_FREEZE_REQUEST_OWNER_MISMATCH: "
            f"request={bound_owner} disposition={disposition_sha}"
        )

    return {
        "owner_state_root": str(owner_state_root),
        "research_pool_root": str(research_pool_root),
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
) -> dict[str, Any]:
    """Freeze the next portfolio period from sealed Owner disposition evidence.

    Always requires a disposition-bound ``owner_authority`` envelope that reloads
    Owner disposition CAS and research-binding under the live portfolio head.
    There is no caller-selectable production fixture bypass on this API.

    Validates immutable evidence; does not authenticate that the caller process is
    Codex. Physical Owner write isolation is a mount/FS concern outside this library.
    Unit/fixture construction must use a test-only helper under ``tests/`` or build
    a real sealed disposition envelope.
    """

    # Capture authority input before any period-root preparation side effects.
    closed_request = _resolve_freeze_request(request_path=request_path, request=request)
    base = resolve_root(root)
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

    _flat_freeze_help = (
        "NON-PRODUCTION CLI surface: always returns FLAT_FREEZE_NOT_PRODUCTION "
        "and never calls freeze_episode. Production Owner freeze: "
        "xinao prospective freeze-from-disposition (host UTC + sealed disposition). "
        "Inspect/settle/replay of already sealed historical episodes remain available. "
        "Fixture construction stays under tests-only helpers."
    )
    freeze_cmd = commands.add_parser(
        "freeze",
        help=_flat_freeze_help,
        description=_flat_freeze_help,
    )
    freeze_cmd.add_argument("--root", type=Path, required=True)
    freeze_cmd.add_argument(
        "--request",
        type=Path,
        required=True,
        help="Ignored: this CLI never performs production or fixture freeze",
    )

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
        "portfolio-freeze",
        help=(
            "NON-PRODUCTION CLI surface: always returns PORTFOLIO_FREEZE_CLI_NOT_PRODUCTION "
            "and never calls freeze_portfolio_period. Production Owner freeze: "
            "xinao prospective freeze-from-disposition (apply_freeze_from_disposition). "
            "Fixture construction stays under tests-only helpers."
        ),
    )
    portfolio_freeze_cmd.add_argument("--root", type=Path, required=True)
    portfolio_freeze_cmd.add_argument(
        "--request",
        type=Path,
        required=True,
        help="Ignored: this CLI never performs production or fixture freeze",
    )

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
        # Ordinary shadow freeze CLI is never a production freeze path and must not
        # accept caller-authored frozen_at without Owner disposition authority.
        # Production: prospective freeze-from-disposition (host UTC + sealed disposition).
        # Library freeze_episode remains for tests-only fixtures and internal period writes.
        raise StoreError(
            "FLAT_FREEZE_NOT_PRODUCTION: "
            "shadow freeze never accepts caller-authored frozen_at as production freeze. "
            "Production path: xinao prospective freeze-from-disposition "
            "(candidate pool + sealed Owner disposition + host UTC). "
            "Historical inspect/settle/replay of sealed episodes remain available. "
            "Fixture construction: tests-only helper under tests/."
        )
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
        # Ordinary shadow portfolio-freeze CLI is never a production freeze path and
        # must not call freeze_portfolio_period. Production: prospective freeze-from-disposition.
        raise StoreError(
            "PORTFOLIO_FREEZE_CLI_NOT_PRODUCTION: "
            "shadow portfolio-freeze never calls freeze_portfolio_period. "
            "Production path: xinao prospective freeze-from-disposition "
            "(authority-root + owner-state-root + disposition + portfolio-root). "
            "Fixture construction: tests-only helper under tests/."
        )
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
        print_cli_json(err)
        return 1
    print_cli_json(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
