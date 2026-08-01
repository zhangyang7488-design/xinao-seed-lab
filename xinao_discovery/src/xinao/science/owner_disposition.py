"""Codex Owner disposition bound to a candidate pool entry.

This library validates immutable path/content evidence a filesystem caller can check:

- disposition bytes are content-addressed
- payload binds a sealed pool entry
- path is under the caller-supplied owner_state_root
- owner_state_root is path-separated from the candidate pool

It does **not** authenticate that the caller process is Codex. Workers can import
this module; that is not Owner authority. Honest flags remain:
``owner_channel_authority=UNPROVEN_BY_LIBRARY`` and
``physical_owner_write_isolation_verified=false``. Physical owner-channel
isolation is mount/write-domain separation outside this module.

Disposition artifacts are raw-SHA256 content-addressed JSON without any
self-referential hash field. ACTION and NO_ACTION are both copied from sealed
researcher decision bytes. The Owner may adopt, reject, or defer that decision;
the Owner never authors or rewrites its branch, selection, or stake.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, Literal

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal
from xinao.science.candidate_pool import (
    CandidatePoolError,
    load_pool_entry,
    pool_entry_path,
    pool_receipt_path,
    pool_result_bytes_path,
    verify_pool_entry_seal,
)
from xinao.science.episode_export_pool_adapter import (
    INGEST_KIND as EPISODE_EXPORT_INGEST_KIND,
)
from xinao.science.episode_export_pool_adapter import (
    EpisodeExportAdapterError,
    load_episode_pool_entry,
)
from xinao.science.prospective_source_thin import (
    ProspectiveSourceError,
    build_source_authority_binding,
    is_live_macaujc2_target,
    load_packet,
    validate_source_authority_binding,
)
from xinao.science.research_episode_candidate_manifest import (
    CandidateManifestError,
    validate_actor_authored_behavior_intent,
)

DISPOSITION_SCHEMA_VERSION: Final = "xinao.codex_owner_disposition.v1"
DISPOSITION_MARKER: Final = "XINAO_CODEX_OWNER_DISPOSITION_V1"

# Draft assembly only — never Owner adoption / never a validator-passable disposition.
DRAFT_STATUS: Final = "DRAFT_NOT_OWNER_ADOPTED"
DRAFT_SOURCE: Final = "tool_generated"
REQUIRED_OWNER_INPUT: Final = "REQUIRED_OWNER_INPUT"

ACCOUNT_ACTION: Final = "ACTION"
ACCOUNT_NO_ACTION: Final = "RESEARCHER_ACCOUNT_NO_ACTION"
_ACCOUNT_IDENTITIES: Final = frozenset({ACCOUNT_ACTION, ACCOUNT_NO_ACTION})

SCIENCE_ADOPT: Final = "ADOPT"
SCIENCE_REJECT: Final = "REJECT"
SCIENCE_DEFER: Final = "DEFER"
SCIENCE_ABSORB_NO_ACTION: Final = "ABSORB_NO_ACTION"
SCIENCE_RETAIN_FOR_SHADOW: Final = "RETAIN_FOR_SHADOW"
_SCIENCE_DISPOSITIONS: Final = frozenset(
    {
        SCIENCE_ADOPT,
        SCIENCE_RETAIN_FOR_SHADOW,
        SCIENCE_REJECT,
        SCIENCE_DEFER,
    }
)

# Historical string still required on the disposition payload so live Codex calls
# remain explicit. It is **not** treated as cryptographic owner proof.
CODEX_OWNER_CHANNEL_SOURCE: Final = "codex_owner_channel"
# Backward-compatible alias used by older call sites / tests.
AUTHENTIC_DISPOSITION_SOURCE: Final = CODEX_OWNER_CHANNEL_SOURCE

OWNER_CHANNEL_AUTHORITY_UNPROVEN: Final = "UNPROVEN_BY_LIBRARY"
RESEARCHER_ACTION_BINDING_SCHEMA: Final = "xinao.researcher_action_binding.v1"
RESEARCHER_NO_ACTION_BINDING_SCHEMA: Final = "xinao.researcher_no_action_binding.v1"

_FORBIDDEN_SOURCES: Final = frozenset(
    {
        "worker",
        "fixture",
        "mock",
        "self",
        "worker_fixture",
        "worker_controlled",
        "harness",
        "synthetic",
        "test",
    }
)

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPECIAL_NUMBER_RULE: Final = "special-number-rule.v1"
_PANEL_BASELINE: Final = {"A": "BO0001", "B": "BO0013"}

# Closed top-level allowlist (no self-hash field, no prose smuggle keys).
_TOP_LEVEL_ALLOWED: Final = frozenset(
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

# Closed portfolio/head identity for portfolio-mode dispositions (not used in flat episode).
_PORTFOLIO_BINDING_ALLOWED: Final = frozenset(
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
_PORTFOLIO_HEAD_PHASES: Final = frozenset(
    {
        "INIT",
        "MISSING",
        "FROZEN",
        "SETTLED",
        "FEEDBACK_SEALED",
        "SETTLEMENT_RECOVERY_REQUIRED",
    }
)

_EXECUTABLE_ALLOWED: Final = frozenset(
    {
        "panel",
        "selected_number",
        "stake",
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "frozen_at",
        "knowledge_cutoff",
        "odds_version_ref",
        "baseline_ref",
        "risk_policy_ref",
        "rule_ref",
        "ticket_ref",
        "information_set_ref",
    }
)

# A researcher authors the execution core before Owner disposition. ``frozen_at``
# is deliberately absent: it is an Owner/host observation added when the
# disposition is sealed and sampled again by the freeze adapter. Ticket and
# information-set references are likewise downstream identities.
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

# Current/future result material forbidden anywhere in the raw disposition tree.
_FORBIDDEN_OUTCOME_KEYS: Final = frozenset(
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


class OwnerDispositionError(ValueError):
    """Fail-closed disposition rejection with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, reason_code: str, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise OwnerDispositionError(reason_code, f"{label} must be lowercase sha256")
    return value


def _require_text(value: object, reason_code: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise OwnerDispositionError(reason_code, f"{label} must be non-empty text")
    return value


def _parse_aware(value: object, label: str) -> datetime:
    text = _require_text(value, "DISPOSITION_TIME_INVALID", label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OwnerDispositionError("DISPOSITION_TIME_INVALID", f"{label}: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OwnerDispositionError("DISPOSITION_TIME_INVALID", f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_disposition_bytes(payload: Mapping[str, Any]) -> bytes:
    """Canonical disposition file bytes (no self-hash field)."""

    if "owner_artifact_sha256" in payload:
        raise OwnerDispositionError(
            "DISPOSITION_SELF_HASH_FORBIDDEN",
            "disposition body must not embed owner_artifact_sha256",
        )
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def disposition_cas_path(owner_state_root: Path, artifact_sha256: str) -> Path:
    digest = _require_hex64(
        artifact_sha256,
        "DISPOSITION_ARTIFACT_HASH_INVALID",
        "owner_artifact_sha256",
    )
    root = resolve_owner_state_root(owner_state_root)
    return root / "objects" / "sha256" / digest[:2] / f"{digest}.json"


def _object_pairs_hook_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise OwnerDispositionError(
                "DISPOSITION_JSON_DUPLICATE_KEY",
                f"duplicate key {key!r}",
            )
        out[key] = value
    return out


def parse_disposition_json_strict(raw: bytes) -> dict[str, Any]:
    """Strict JSON object parse; rejects duplicate keys and non-objects."""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OwnerDispositionError("DISPOSITION_JSON_INVALID", str(exc)) from exc
    try:
        payload = json.loads(text, object_pairs_hook=_object_pairs_hook_no_duplicates)
    except OwnerDispositionError:
        raise
    except json.JSONDecodeError as exc:
        raise OwnerDispositionError("DISPOSITION_JSON_INVALID", str(exc)) from exc
    if not isinstance(payload, dict):
        raise OwnerDispositionError("DISPOSITION_JSON_INVALID", "object required")
    return payload


def reject_forbidden_outcome_material(node: object, *, path: str = "$") -> None:
    """Recursively reject current/future outcome material on the raw tree."""

    if isinstance(node, Mapping):
        for key, value in node.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_text in _FORBIDDEN_OUTCOME_KEYS or key_lower in _FORBIDDEN_OUTCOME_KEYS:
                raise OwnerDispositionError(
                    "DISPOSITION_OUTCOME_MATERIAL_FORBIDDEN",
                    f"{path}.{key_text}",
                )
            if key_lower.startswith("peeked_") or key_lower.startswith("future_"):
                raise OwnerDispositionError(
                    "DISPOSITION_OUTCOME_MATERIAL_FORBIDDEN",
                    f"{path}.{key_text}",
                )
            reject_forbidden_outcome_material(value, path=f"{path}.{key_text}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            reject_forbidden_outcome_material(item, path=f"{path}[{index}]")


def resolve_owner_state_root(owner_state_root: Path) -> Path:
    return owner_state_root.expanduser().resolve()


def assert_path_under_owner_root(path: Path, owner_state_root: Path) -> Path:
    """Require disposition artifact to be under owner_state_root (not pool root)."""

    root = resolve_owner_state_root(owner_state_root)
    resolved = path.expanduser().resolve()
    if not root.is_dir():
        raise OwnerDispositionError(
            "OWNER_STATE_ROOT_MISSING",
            f"owner_state_root is not a directory: {root}",
        )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OwnerDispositionError(
            "DISPOSITION_NOT_UNDER_OWNER_ROOT",
            f"path={resolved} owner_state_root={root}",
        ) from exc
    if not resolved.is_file():
        raise OwnerDispositionError("DISPOSITION_ARTIFACT_MISSING", str(resolved))
    return resolved


def assert_owner_root_separated_from_pool(
    *,
    owner_state_root: Path,
    pool_root: Path,
) -> None:
    owner = resolve_owner_state_root(owner_state_root)
    pool = pool_root.expanduser().resolve()
    if owner == pool:
        raise OwnerDispositionError(
            "OWNER_ROOT_POOL_NOT_SEPARATED",
            "owner_state_root must be path-separated from candidate pool root",
        )
    # OwnerDispositionError subclasses ValueError — never catch it as "not nested".
    try:
        owner.relative_to(pool)
    except ValueError:
        pass
    else:
        raise OwnerDispositionError(
            "OWNER_ROOT_NESTED_IN_POOL",
            "owner_state_root must not be nested under pool_root",
        )
    try:
        pool.relative_to(owner)
    except ValueError:
        pass
    else:
        raise OwnerDispositionError(
            "POOL_NESTED_IN_OWNER_ROOT",
            "pool_root must not be nested under owner_state_root",
        )


def _reject_unknown_keys(
    raw: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    reason_code: str,
) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise OwnerDispositionError(reason_code, f"unknown={unknown}")


def _validate_accounting_stake(stake: object) -> str:
    """Reuse ledger ACCOUNTING_DECIMAL contract; reject non-canonical money strings."""

    if not isinstance(stake, str) or not stake:
        raise OwnerDispositionError(
            "EXECUTABLE_STAKE_INVALID",
            "stake must be a canonical accounting decimal string",
        )
    # Explicit string rejects before Decimal (exponents / IEEE-ish tokens).
    lowered = stake.strip().lower()
    if any(token in lowered for token in ("nan", "inf", "infinity")):
        raise OwnerDispositionError("EXECUTABLE_STAKE_INVALID", "NaN/Infinity forbidden")
    if "e" in lowered:
        raise OwnerDispositionError(
            "EXECUTABLE_STAKE_INVALID",
            "scientific notation / exponent form forbidden",
        )
    try:
        canonical = format_decimal(stake, ACCOUNTING_DECIMAL)
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise OwnerDispositionError("EXECUTABLE_STAKE_INVALID", str(exc)) from exc
    if stake != canonical:
        raise OwnerDispositionError(
            "EXECUTABLE_STAKE_INVALID",
            f"non-canonical stake {stake!r}; require {canonical!r}",
        )
    amount = Decimal(canonical)
    if amount <= 0:
        raise OwnerDispositionError("EXECUTABLE_STAKE_INVALID", "ACTION stake must be positive")
    return canonical


def _validate_executable_account_decision(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "panel",
        "selected_number",
        "stake",
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "frozen_at",
        "knowledge_cutoff",
        "odds_version_ref",
        "baseline_ref",
        "risk_policy_ref",
        "rule_ref",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise OwnerDispositionError(
            "EXECUTABLE_DECISION_INCOMPLETE",
            f"missing={missing}",
        )
    _reject_unknown_keys(
        raw,
        _EXECUTABLE_ALLOWED,
        reason_code="EXECUTABLE_DECISION_UNKNOWN_FIELDS",
    )

    panel = raw.get("panel")
    if panel not in ("A", "B"):
        raise OwnerDispositionError("EXECUTABLE_PANEL_INVALID", str(panel))
    selected = raw.get("selected_number")
    if type(selected) is not int or not (1 <= selected <= 49):
        raise OwnerDispositionError("EXECUTABLE_NUMBER_INVALID", str(selected))
    stake = _validate_accounting_stake(raw.get("stake"))

    rule_ref = _require_text(raw.get("rule_ref"), "EXECUTABLE_RULE_INVALID", "rule_ref")
    if rule_ref != _SPECIAL_NUMBER_RULE:
        raise OwnerDispositionError(
            "EXECUTABLE_RULE_INVALID",
            f"rule_ref must be {_SPECIAL_NUMBER_RULE}",
        )
    baseline = _require_text(raw.get("baseline_ref"), "EXECUTABLE_BASELINE_INVALID", "baseline_ref")
    expected_baseline = _PANEL_BASELINE[str(panel)]
    if baseline != expected_baseline:
        raise OwnerDispositionError(
            "EXECUTABLE_BASELINE_INVALID",
            f"panel={panel} requires baseline_ref={expected_baseline}",
        )

    target_open = _parse_aware(raw.get("target_open_time"), "target_open_time")
    freeze_deadline = _parse_aware(raw.get("freeze_deadline"), "freeze_deadline")
    frozen_at = _parse_aware(raw.get("frozen_at"), "frozen_at")
    knowledge_cutoff = _parse_aware(raw.get("knowledge_cutoff"), "knowledge_cutoff")
    if not (frozen_at <= freeze_deadline < target_open):
        raise OwnerDispositionError(
            "EXECUTABLE_TEMPORAL_VIOLATION",
            "require frozen_at <= freeze_deadline < target_open_time",
        )
    if knowledge_cutoff > frozen_at:
        raise OwnerDispositionError(
            "EXECUTABLE_TEMPORAL_VIOLATION",
            "knowledge_cutoff must be at or before frozen_at",
        )

    return {
        "panel": panel,
        "selected_number": selected,
        "stake": stake,
        "target_ref": _require_text(
            raw.get("target_ref"),
            "EXECUTABLE_TARGET_INVALID",
            "target_ref",
        ),
        "target_open_time": target_open.isoformat().replace("+00:00", "Z"),
        "freeze_deadline": freeze_deadline.isoformat().replace("+00:00", "Z"),
        "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
        "knowledge_cutoff": knowledge_cutoff.isoformat().replace("+00:00", "Z"),
        "odds_version_ref": _require_text(
            raw.get("odds_version_ref"),
            "EXECUTABLE_ODDS_INVALID",
            "odds_version_ref",
        ),
        "baseline_ref": baseline,
        "risk_policy_ref": _require_text(
            raw.get("risk_policy_ref"),
            "EXECUTABLE_RISK_POLICY_INVALID",
            "risk_policy_ref",
        ),
        "rule_ref": rule_ref,
        "ticket_ref": raw.get("ticket_ref"),
        "information_set_ref": raw.get("information_set_ref"),
    }


def _optional_hex64_or_null(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _require_hex64(value, "PORTFOLIO_BINDING_HASH_INVALID", label)


def validate_portfolio_binding(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate closed portfolio/head identity carried on a disposition."""

    required = {
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
    missing = sorted(required - set(raw))
    if missing:
        raise OwnerDispositionError(
            "PORTFOLIO_BINDING_INCOMPLETE",
            f"missing={missing}",
        )
    _reject_unknown_keys(
        raw,
        _PORTFOLIO_BINDING_ALLOWED,
        reason_code="PORTFOLIO_BINDING_UNKNOWN_FIELDS",
    )
    head_period_index = raw.get("head_period_index")
    if type(head_period_index) is not int or head_period_index < 0:
        raise OwnerDispositionError(
            "PORTFOLIO_BINDING_HEAD_PERIOD_INVALID",
            str(head_period_index),
        )
    intended = raw.get("intended_next_period_index")
    if type(intended) is not int or intended < 1:
        raise OwnerDispositionError(
            "PORTFOLIO_BINDING_INTENDED_PERIOD_INVALID",
            str(intended),
        )
    head_phase = raw.get("head_phase")
    if not isinstance(head_phase, str) or head_phase not in _PORTFOLIO_HEAD_PHASES:
        raise OwnerDispositionError(
            "PORTFOLIO_BINDING_HEAD_PHASE_INVALID",
            str(head_phase),
        )
    portfolio_ref = _require_text(
        raw.get("portfolio_ref"),
        "PORTFOLIO_BINDING_PORTFOLIO_REF_INVALID",
        "portfolio_ref",
    )
    seat_id = _require_text(
        raw.get("seat_id"),
        "PORTFOLIO_BINDING_SEAT_ID_INVALID",
        "seat_id",
    )
    if portfolio_ref == seat_id:
        raise OwnerDispositionError(
            "PORTFOLIO_BINDING_SEAT_PORTFOLIO_COLLISION",
            "seat_id and portfolio_ref must be distinct",
        )
    return {
        "portfolio_ref": portfolio_ref,
        "portfolio_content_hash": _require_hex64(
            raw.get("portfolio_content_hash"),
            "PORTFOLIO_BINDING_HASH_INVALID",
            "portfolio_content_hash",
        ),
        "seat_id": seat_id,
        "seat_content_hash": _require_hex64(
            raw.get("seat_content_hash"),
            "PORTFOLIO_BINDING_HASH_INVALID",
            "seat_content_hash",
        ),
        "head_period_index": head_period_index,
        "head_phase": head_phase,
        # Explicit nulls required when first-period / no prior feedback yet.
        "prior_settled_episode_hash": _optional_hex64_or_null(
            raw.get("prior_settled_episode_hash"),
            "prior_settled_episode_hash",
        ),
        "prior_feedback_hash": _optional_hex64_or_null(
            raw.get("prior_feedback_hash"),
            "prior_feedback_hash",
        ),
        "intended_next_period_index": intended,
    }


def _validate_no_action_times(raw: Mapping[str, Any]) -> dict[str, Any]:
    """NO_ACTION still freezes a period; times/target come from disposition, not prose."""

    required = {
        "target_ref",
        "target_open_time",
        "freeze_deadline",
        "frozen_at",
        "knowledge_cutoff",
        "rule_ref",
        "odds_version_ref",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise OwnerDispositionError(
            "NO_ACTION_BINDING_INCOMPLETE",
            f"missing={missing}",
        )
    _reject_unknown_keys(
        raw,
        _NO_ACTION_BINDING_ALLOWED,
        reason_code="NO_ACTION_BINDING_UNKNOWN_FIELDS",
    )
    target_open = _parse_aware(raw.get("target_open_time"), "target_open_time")
    freeze_deadline = _parse_aware(raw.get("freeze_deadline"), "freeze_deadline")
    frozen_at = _parse_aware(raw.get("frozen_at"), "frozen_at")
    knowledge_cutoff = _parse_aware(raw.get("knowledge_cutoff"), "knowledge_cutoff")
    if not (frozen_at <= freeze_deadline < target_open):
        raise OwnerDispositionError(
            "NO_ACTION_TEMPORAL_VIOLATION",
            "require frozen_at <= freeze_deadline < target_open_time",
        )
    if knowledge_cutoff > frozen_at:
        raise OwnerDispositionError(
            "NO_ACTION_TEMPORAL_VIOLATION",
            "knowledge_cutoff must be at or before frozen_at",
        )
    rule_ref = _require_text(raw.get("rule_ref"), "NO_ACTION_RULE_INVALID", "rule_ref")
    if rule_ref != _SPECIAL_NUMBER_RULE:
        raise OwnerDispositionError("NO_ACTION_RULE_INVALID", rule_ref)
    return {
        "target_ref": _require_text(
            raw.get("target_ref"),
            "NO_ACTION_TARGET_INVALID",
            "target_ref",
        ),
        "target_open_time": target_open.isoformat().replace("+00:00", "Z"),
        "freeze_deadline": freeze_deadline.isoformat().replace("+00:00", "Z"),
        "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
        "knowledge_cutoff": knowledge_cutoff.isoformat().replace("+00:00", "Z"),
        "rule_ref": rule_ref,
        "odds_version_ref": _require_text(
            raw.get("odds_version_ref"),
            "NO_ACTION_ODDS_INVALID",
            "odds_version_ref",
        ),
    }


def validate_disposition_payload(
    payload: Mapping[str, Any],
    *,
    pool_entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate disposition JSON structure against a sealed pool entry."""

    # Closed top-level allowlist + recursive no-peek before any soft defaults.
    _reject_unknown_keys(
        payload,
        _TOP_LEVEL_ALLOWED,
        reason_code="DISPOSITION_UNKNOWN_FIELDS",
    )
    reject_forbidden_outcome_material(payload)

    if payload.get("schema_version") != DISPOSITION_SCHEMA_VERSION:
        raise OwnerDispositionError(
            "DISPOSITION_SCHEMA_DRIFT",
            str(payload.get("schema_version")),
        )
    if payload.get("disposition_marker") != DISPOSITION_MARKER:
        raise OwnerDispositionError(
            "DISPOSITION_MARKER_INVALID",
            str(payload.get("disposition_marker")),
        )

    source = payload.get("disposition_source")
    if not isinstance(source, str) or not source:
        raise OwnerDispositionError("DISPOSITION_SOURCE_MISSING", "disposition_source required")
    source_normalized = source.strip().lower()
    if source_normalized in _FORBIDDEN_SOURCES or "worker" in source_normalized:
        raise OwnerDispositionError(
            "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL",
            f"disposition_source={source!r} is not the codex_owner_channel label",
        )
    if source != CODEX_OWNER_CHANNEL_SOURCE:
        raise OwnerDispositionError(
            "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL",
            f"require {CODEX_OWNER_CHANNEL_SOURCE!r}, got {source!r}",
        )
    if payload.get("worker_controlled") is not False:
        raise OwnerDispositionError(
            "DISPOSITION_WORKER_CONTROLLED",
            "worker_controlled must be explicitly false",
        )
    owner_role = payload.get("owner_role")
    if owner_role != "codex":
        raise OwnerDispositionError("DISPOSITION_OWNER_ROLE_INVALID", str(owner_role))
    if "science_identity" in payload:
        raise OwnerDispositionError(
            "SCIENCE_IDENTITY_CALLER_OVERRIDE_FORBIDDEN",
            "science_identity is derived from the sealed researcher account branch",
        )

    verify_pool_entry_seal(pool_entry)
    result_sha256 = _require_hex64(
        payload.get("result_sha256"),
        "DISPOSITION_RESULT_HASH_INVALID",
        "result_sha256",
    )
    if result_sha256 != pool_entry.get("result_sha256"):
        raise OwnerDispositionError(
            "DISPOSITION_POOL_RESULT_MISMATCH",
            f"disposition={result_sha256} pool={pool_entry.get('result_sha256')}",
        )
    receipt_content_sha256 = _require_hex64(
        payload.get("receipt_content_sha256"),
        "DISPOSITION_RECEIPT_HASH_INVALID",
        "receipt_content_sha256",
    )
    if receipt_content_sha256 != pool_entry.get("receipt_content_sha256"):
        raise OwnerDispositionError(
            "DISPOSITION_POOL_RECEIPT_MISMATCH",
            "receipt_content_sha256 disagrees with pool entry",
        )
    pool_entry_content_hash = _require_hex64(
        payload.get("pool_entry_content_hash"),
        "DISPOSITION_POOL_ENTRY_HASH_INVALID",
        "pool_entry_content_hash",
    )
    if pool_entry_content_hash != pool_entry.get("content_hash"):
        raise OwnerDispositionError(
            "DISPOSITION_POOL_ENTRY_HASH_MISMATCH",
            "pool_entry_content_hash disagrees with sealed entry",
        )

    period_index = payload.get("period_index")
    if type(period_index) is not int or period_index < 1:
        raise OwnerDispositionError("DISPOSITION_PERIOD_INVALID", str(period_index))

    account_identity = payload.get("account_identity")
    if account_identity not in _ACCOUNT_IDENTITIES:
        raise OwnerDispositionError(
            "PERIOD_ACCOUNT_IDENTITY_REQUIRED",
            "account_identity must be ACTION or RESEARCHER_ACCOUNT_NO_ACTION",
        )

    science_disposition = payload.get("science_disposition")
    if science_disposition not in _SCIENCE_DISPOSITIONS:
        raise OwnerDispositionError(
            "SCIENCE_DISPOSITION_INVALID",
            str(science_disposition),
        )
    episode_ref = _require_text(
        payload.get("episode_ref"),
        "DISPOSITION_EPISODE_INVALID",
        "episode_ref",
    )
    knowledge_cutoff = _parse_aware(payload.get("knowledge_cutoff"), "knowledge_cutoff")

    # Optional period/target binding fields on the outer disposition.
    target_ref = payload.get("target_ref")
    if target_ref is not None:
        target_ref = _require_text(target_ref, "DISPOSITION_TARGET_INVALID", "target_ref")

    executable: dict[str, Any] | None = None
    no_action_binding: dict[str, Any] | None = None
    if account_identity == ACCOUNT_ACTION:
        exec_raw = payload.get("executable_account_decision")
        if not isinstance(exec_raw, Mapping):
            raise OwnerDispositionError(
                "ACTION_REQUIRES_EXECUTABLE_DECISION",
                "ACTION must carry structured executable_account_decision; "
                "numbers/stake must not be extracted from research prose",
            )
        executable = _validate_executable_account_decision(exec_raw)
        if target_ref is not None and target_ref != executable["target_ref"]:
            raise OwnerDispositionError(
                "DISPOSITION_TARGET_MISMATCH",
                "outer target_ref disagrees with executable decision",
            )
        target_ref = executable["target_ref"]
        # knowledge_cutoff on disposition must match executable (single source).
        exec_cutoff = _parse_aware(executable["knowledge_cutoff"], "executable.knowledge_cutoff")
        if knowledge_cutoff != exec_cutoff:
            raise OwnerDispositionError(
                "DISPOSITION_KNOWLEDGE_CUTOFF_MISMATCH",
                "outer knowledge_cutoff must equal executable_account_decision.knowledge_cutoff",
            )
    else:
        # NO_ACTION: forbid executable ticket; require period freeze binding.
        if payload.get("executable_account_decision") is not None:
            raise OwnerDispositionError(
                "NO_ACTION_MUST_NOT_CARRY_EXECUTABLE",
                "RESEARCHER_ACCOUNT_NO_ACTION cannot carry executable_account_decision",
            )
        na_raw = payload.get("no_action_period_binding")
        if not isinstance(na_raw, Mapping):
            raise OwnerDispositionError(
                "NO_ACTION_BINDING_REQUIRED",
                "RESEARCHER_ACCOUNT_NO_ACTION requires no_action_period_binding",
            )
        no_action_binding = _validate_no_action_times(na_raw)
        if target_ref is not None and target_ref != no_action_binding["target_ref"]:
            raise OwnerDispositionError(
                "DISPOSITION_TARGET_MISMATCH",
                "outer target_ref disagrees with no_action binding",
            )
        target_ref = no_action_binding["target_ref"]
        na_cutoff = _parse_aware(
            no_action_binding["knowledge_cutoff"],
            "no_action.knowledge_cutoff",
        )
        if knowledge_cutoff != na_cutoff:
            raise OwnerDispositionError(
                "DISPOSITION_KNOWLEDGE_CUTOFF_MISMATCH",
                "outer knowledge_cutoff must equal no_action_period_binding.knowledge_cutoff",
            )

    if not target_ref:
        raise OwnerDispositionError("DISPOSITION_TARGET_REQUIRED", "target_ref required")

    portfolio_binding: dict[str, Any] | None = None
    pb_raw = payload.get("portfolio_binding")
    if pb_raw is not None:
        if not isinstance(pb_raw, Mapping):
            raise OwnerDispositionError(
                "PORTFOLIO_BINDING_INVALID",
                "portfolio_binding must be an object when present",
            )
        portfolio_binding = validate_portfolio_binding(pb_raw)
        if int(portfolio_binding["intended_next_period_index"]) != int(period_index):
            raise OwnerDispositionError(
                "PORTFOLIO_BINDING_PERIOD_MISMATCH",
                "portfolio_binding.intended_next_period_index must equal period_index",
            )

    source_authority_binding: dict[str, Any] | None = None
    sab_raw = payload.get("source_authority_binding")
    live_macaujc2 = is_live_macaujc2_target(str(target_ref))
    if live_macaujc2 and sab_raw is None:
        raise OwnerDispositionError(
            "SOURCE_AUTHORITY_BINDING_REQUIRED",
            "target_ref macaujc2/expect/* requires sealed source_authority_binding",
        )
    if sab_raw is not None:
        if not isinstance(sab_raw, Mapping):
            raise OwnerDispositionError(
                "SOURCE_AUTHORITY_BINDING_INVALID",
                "source_authority_binding must be an object when present",
            )
        try:
            source_authority_binding = validate_source_authority_binding(sab_raw)
        except ProspectiveSourceError as exc:
            raise OwnerDispositionError(exc.reason_code, exc.detail) from exc
        if source_authority_binding["target_ref"] != target_ref:
            raise OwnerDispositionError(
                "SOURCE_AUTHORITY_BINDING_TARGET_MISMATCH",
                "source_authority_binding.target_ref must equal disposition target_ref",
            )
        branch = executable if account_identity == ACCOUNT_ACTION else no_action_binding
        if not isinstance(branch, Mapping):
            raise OwnerDispositionError(
                "SOURCE_AUTHORITY_BINDING_BRANCH_MISSING",
                "cannot bind authority without period branch times",
            )
        if (
            str(branch.get("target_open_time"))
            != source_authority_binding["target_guard_open_time"]
        ):
            raise OwnerDispositionError(
                "SOURCE_AUTHORITY_BINDING_GUARD_MISMATCH",
                "period target_open_time must equal target_guard_open_time",
            )
        if str(branch.get("freeze_deadline")) != source_authority_binding["freeze_deadline"]:
            raise OwnerDispositionError(
                "SOURCE_AUTHORITY_BINDING_DEADLINE_MISMATCH",
                "period freeze_deadline must equal authority freeze_deadline",
            )

    normalized: dict[str, Any] = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_marker": DISPOSITION_MARKER,
        "disposition_source": CODEX_OWNER_CHANNEL_SOURCE,
        "owner_role": "codex",
        "worker_controlled": False,
        "result_sha256": result_sha256,
        "receipt_content_sha256": receipt_content_sha256,
        "pool_entry_content_hash": pool_entry_content_hash,
        "period_index": period_index,
        "episode_ref": episode_ref,
        "target_ref": target_ref,
        "knowledge_cutoff": knowledge_cutoff.isoformat().replace("+00:00", "Z"),
        "science_disposition": science_disposition,
        "account_identity": account_identity,
        "executable_account_decision": executable,
        "no_action_period_binding": no_action_binding,
        "portfolio_binding": portfolio_binding,
        "source_authority_binding": source_authority_binding,
        "rationale_ref": _require_text(
            payload.get("rationale_ref") or "owner-disposition.rationale",
            "DISPOSITION_RATIONALE_INVALID",
            "rationale_ref",
        ),
    }
    # A veto/defer is Owner disposition, never a fabricated researcher
    # NO_ACTION. Preserve the producer branch identity independently of Owner
    # judgment so rejection cannot rewrite what the actor actually chose.
    normalized["science_identity"] = (
        "SCIENCE_CANDIDATE" if account_identity == ACCOUNT_ACTION else "POLICY_NO_ACTION"
    )

    return normalized


def _suggest_episode_ref_from_pool(pool_entry: Mapping[str, Any]) -> str:
    """Mechanical episode_ref hint from sealed pool provenance (not science judgment)."""

    lab = pool_entry.get("lab_provenance")
    if isinstance(lab, Mapping):
        episode_id = lab.get("episode_id")
        if isinstance(episode_id, str) and episode_id and "\x00" not in episode_id:
            return f"episode.{episode_id}.owner-draft"
    run_id = pool_entry.get("run_id")
    if isinstance(run_id, str) and run_id and "\x00" not in run_id:
        return f"episode.pool.{run_id}.owner-draft"
    return REQUIRED_OWNER_INPUT


def draft_owner_disposition(
    *,
    pool_root: Path,
    result_sha256: str,
    authority_root: Path | None = None,
    packet_content_hash: str | None = None,
    portfolio_root: Path | None = None,
    episode_root: Path | None = None,
) -> dict[str, Any]:
    """Assemble a non-authoritative Owner disposition draft from sealed consumers.

    Mechanical fields only (sealed researcher branch, pool hashes, authority
    binding/times, optional portfolio head). ACTION/NO_ACTION, selection, and
    stake come from producer bytes; only science disposition and rationale stay
    for Owner judgment. Never writes owner CAS / freeze / portfolio / authority /
    pool.

    The returned ``payload_draft`` is intentionally **not** a validator-passable
    disposition: judgment fields are ``REQUIRED_OWNER_INPUT`` placeholders.
    Codex must fill them, then call write-owner-disposition.
    """

    pool_entry = load_verified_pool_entry_for_disposition(pool_root, result_sha256)
    verify_pool_entry_seal(pool_entry)
    producer_decision = _load_sealed_researcher_decision(
        pool_root=pool_root,
        pool_entry=pool_entry,
        episode_root=episode_root,
        portfolio_root=portfolio_root,
        authority_root=authority_root,
    )
    producer_identity = str(producer_decision["account_identity"])
    producer_core_raw = producer_decision.get("authored")
    if not isinstance(producer_core_raw, Mapping):
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_SOURCE_ABSENT",
            str(producer_decision.get("source_json_path")),
        )
    producer_deadline = producer_core_raw.get("freeze_deadline")
    if producer_identity == ACCOUNT_ACTION:
        producer_core = _researcher_executable_core(
            producer_core_raw,
            disposition_frozen_at=producer_deadline,
        )
    else:
        producer_core = _researcher_no_action_core(
            producer_core_raw,
            disposition_frozen_at=producer_deadline,
        )
    # Never project research prose / recommendation into science judgment. The
    # period branch itself is not judgment: it is the actor's sealed choice.

    source_authority_binding: dict[str, Any] | None = None
    target_ref: object = producer_core.get("target_ref")
    target_open_time: object = producer_core.get("target_open_time")
    freeze_deadline: object = producer_core.get("freeze_deadline")
    authority_meta: dict[str, Any] | None = None

    has_authority = authority_root is not None or packet_content_hash is not None
    if has_authority:
        if authority_root is None or packet_content_hash is None:
            raise OwnerDispositionError(
                "DRAFT_AUTHORITY_ARGS_INCOMPLETE",
                "authority-root and packet-content-hash must be provided together",
            )
        try:
            packet = load_packet(authority_root, packet_content_hash)
            source_authority_binding = build_source_authority_binding(packet)
            # Re-run the same validator freeze consumers use (packet equality).
            source_authority_binding = validate_source_authority_binding(
                source_authority_binding,
                packet=packet,
            )
        except ProspectiveSourceError as exc:
            raise OwnerDispositionError(exc.reason_code, exc.detail) from exc
        for label, produced, authoritative in (
            ("target_ref", target_ref, source_authority_binding["target_ref"]),
            (
                "target_open_time",
                target_open_time,
                source_authority_binding["target_guard_open_time"],
            ),
            ("freeze_deadline", freeze_deadline, source_authority_binding["freeze_deadline"]),
        ):
            if produced != authoritative:
                raise OwnerDispositionError(
                    "DRAFT_RESEARCHER_AUTHORITY_MISMATCH",
                    f"{label}: producer={produced!r} authority={authoritative!r}",
                )
        authority_meta = {
            "authority_root": str(authority_root.expanduser().resolve()),
            "packet_content_hash": source_authority_binding["packet_content_hash"],
        }

    portfolio_binding: dict[str, Any] | None = None
    period_index: object = REQUIRED_OWNER_INPUT
    portfolio_meta: dict[str, Any] | None = None
    if portfolio_root is not None:
        # Lazy import: freeze_adapter imports this module.
        from xinao.science.freeze_adapter import (
            FreezeAdapterError,
            build_portfolio_binding_from_shadow,
        )

        try:
            portfolio_binding = build_portfolio_binding_from_shadow(portfolio_root)
        except FreezeAdapterError as exc:
            raise OwnerDispositionError(exc.reason_code, exc.detail) from exc
        # Closed binding already validated by live inspect consumer shape; re-check.
        portfolio_binding = validate_portfolio_binding(portfolio_binding)
        period_index = int(portfolio_binding["intended_next_period_index"])
        portfolio_meta = {
            "portfolio_root": str(portfolio_root.expanduser().resolve()),
        }

    knowledge_cutoff = producer_core.get("knowledge_cutoff")

    episode_ref = _suggest_episode_ref_from_pool(pool_entry)

    # Mechanical pool/authority/portfolio fields only. Protocol authority labels
    # and judgment remain REQUIRED_OWNER_INPUT so a raw draft cannot pass
    # write-owner-disposition (no CAS pollution, no forged Owner channel).
    # Outer envelope stays tool_generated / owner_adopted=false.
    payload_draft: dict[str, Any] = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_marker": DISPOSITION_MARKER,
        # Owner must explicitly set codex_owner_channel — tool does not forge it.
        "disposition_source": REQUIRED_OWNER_INPUT,
        "owner_role": REQUIRED_OWNER_INPUT,
        # Owner must explicitly set false; tool never stamps Owner authority.
        "worker_controlled": REQUIRED_OWNER_INPUT,
        "result_sha256": pool_entry["result_sha256"],
        "receipt_content_sha256": pool_entry["receipt_content_sha256"],
        "pool_entry_content_hash": pool_entry["content_hash"],
        "period_index": period_index,
        "episode_ref": episode_ref,
        "target_ref": target_ref,
        "knowledge_cutoff": knowledge_cutoff,
        # Owner judgment — never auto-selected from pool/manifest.
        "science_disposition": REQUIRED_OWNER_INPUT,
        # Actor behavior — copied from exact sealed producer bytes, never Owner input.
        "account_identity": producer_identity,
        "rationale_ref": REQUIRED_OWNER_INPUT,
    }
    if source_authority_binding is not None:
        payload_draft["source_authority_binding"] = dict(source_authority_binding)
    if portfolio_binding is not None:
        payload_draft["portfolio_binding"] = dict(portfolio_binding)

    if producer_identity == ACCOUNT_ACTION:
        produced_branch = {
            "account_identity": ACCOUNT_ACTION,
            "executable_account_decision": {
                **producer_core,
                "frozen_at": REQUIRED_OWNER_INPUT,
            },
            "no_action_period_binding": None,
        }
    else:
        produced_branch = {
            "account_identity": ACCOUNT_NO_ACTION,
            "executable_account_decision": None,
            "no_action_period_binding": {
                **producer_core,
                "frozen_at": REQUIRED_OWNER_INPUT,
            },
        }

    required_owner_inputs = [
        "disposition_source(=codex_owner_channel)",
        "owner_role(=codex)",
        "worker_controlled(=false)",
        "science_disposition(ADOPT|RETAIN_FOR_SHADOW|REJECT|DEFER)",
        "rationale_ref",
        "frozen_at",
    ]
    if period_index == REQUIRED_OWNER_INPUT:
        required_owner_inputs.append("period_index")
    if episode_ref == REQUIRED_OWNER_INPUT:
        required_owner_inputs.append("episode_ref")

    return {
        "ok": True,
        "status": DRAFT_STATUS,
        "draft_marker": DRAFT_STATUS,
        "draft_source": DRAFT_SOURCE,
        "tool_generated": True,
        "owner_adopted": False,
        "owner_channel_authority": OWNER_CHANNEL_AUTHORITY_UNPROVEN,
        "owner_disposition_authentic": False,
        "physical_owner_write_isolation_verified": False,
        "candidate_only": True,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "freeze_written": False,
        "settlement_written": False,
        "auto_freeze": False,
        "auto_settle": False,
        "auto_next_period": False,
        "next_task_created": False,
        "daemon": False,
        "account_identity_selected": False,
        "account_identity_from_sealed_researcher": True,
        "science_disposition_selected": False,
        "selected_number_selected": False,
        "stake_selected": False,
        "manifest_recommendation_projected": False,
        "required_owner_inputs": required_owner_inputs,
        "mechanical_sources": {
            "pool_root": str(pool_root.expanduser().resolve()),
            "result_sha256": pool_entry["result_sha256"],
            "pool_entry_content_hash": pool_entry["content_hash"],
            "pool_action_support": pool_entry.get("action_support", "NOT_PROJECTED"),
            "authority": authority_meta,
            "portfolio": portfolio_meta,
        },
        "payload_draft": payload_draft,
        "sealed_researcher_decision": {
            key: value for key, value in producer_decision.items() if key != "authored"
        },
        # Exactly one producer branch is returned. Owner adds only frozen_at and
        # must copy these bytes unchanged into payload_draft.
        "branch_templates": {producer_identity: produced_branch},
        "owner_fill_instructions": (
            "Codex is the only Owner. Explicitly set disposition_source="
            f"{CODEX_OWNER_CHANNEL_SOURCE!r}, owner_role='codex', "
            "worker_controlled=false, science_disposition, rationale_ref, and "
            "frozen_at. Copy the single sealed researcher branch unchanged; never "
            "change ACTION/NO_ACTION, selection, stake, target, rule, odds, or cutoff. "
            "Never submit this draft envelope to write-owner-disposition; "
            "submit only a completed payload_draft after Owner judgment. "
            f"draft_source={DRAFT_SOURCE}; owner_adopted=false; "
            "worker_controlled is not forged by this tool."
        ),
        "protocol_constants_for_owner": {
            "disposition_source": CODEX_OWNER_CHANNEL_SOURCE,
            "owner_role": "codex",
            "worker_controlled": False,
            "schema_version": DISPOSITION_SCHEMA_VERSION,
            "disposition_marker": DISPOSITION_MARKER,
        },
    }


def write_owner_disposition_artifact(
    *,
    owner_state_root: Path,
    payload: Mapping[str, Any],
    pool_root: Path,
    episode_root: Path | None = None,
    portfolio_root: Path | None = None,
    authority_root: Path | None = None,
) -> dict[str, Any]:
    """Validate against sealed research bytes, then write Owner CAS exclusively.

    No artifact is created until pool/result binding, Owner claim fields, science
    projection, and any ACTION researcher-execution binding have all passed.
    """

    assert_owner_root_separated_from_pool(
        owner_state_root=owner_state_root,
        pool_root=pool_root,
    )
    # Encode once, parse that exact byte snapshot strictly, validate it, and
    # write the same bytes.  A mutable/custom Mapping therefore cannot change
    # between validation and CAS creation.
    raw = encode_disposition_bytes(payload)
    payload_snapshot = parse_disposition_json_strict(raw)
    if "owner_artifact_sha256" in payload_snapshot:
        raise OwnerDispositionError(
            "DISPOSITION_SELF_HASH_FORBIDDEN",
            "do not embed owner_artifact_sha256; path is the content address",
        )
    claimed_result = _require_hex64(
        payload_snapshot.get("result_sha256"),
        "DISPOSITION_RESULT_HASH_INVALID",
        "result_sha256",
    )
    pool_entry = load_verified_pool_entry_for_disposition(pool_root, claimed_result)
    normalized = validate_disposition_payload(payload_snapshot, pool_entry=pool_entry)
    researcher_decision_binding = verify_researcher_authored_decision(
        pool_root=pool_root,
        pool_entry=pool_entry,
        disposition=normalized,
        episode_root=episode_root,
        portfolio_root=portfolio_root,
        authority_root=authority_root,
    )
    researcher_action_binding = (
        researcher_decision_binding
        if researcher_decision_binding["account_identity"] == ACCOUNT_ACTION
        else None
    )

    root = resolve_owner_state_root(owner_state_root)
    root.mkdir(parents=True, exist_ok=True)
    digest = raw_sha256(raw)
    path = disposition_cas_path(root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
    except FileExistsError as exc:
        existing = path.read_bytes()
        if existing != raw:
            raise OwnerDispositionError(
                "DISPOSITION_CAS_CONTENT_CONFLICT",
                f"owner_artifact_sha256={digest} already sealed with different bytes",
            ) from exc
        return {
            "disposition_path": str(path),
            "owner_artifact_sha256": digest,
            "owner_state_root": str(root),
            "bytes_written": False,
            "researcher_decision_binding": researcher_decision_binding,
            "researcher_action_binding": researcher_action_binding,
        }
    return {
        "disposition_path": str(path),
        "owner_artifact_sha256": digest,
        "owner_state_root": str(root),
        "bytes_written": True,
        "researcher_decision_binding": researcher_decision_binding,
        "researcher_action_binding": researcher_action_binding,
    }


def load_verified_pool_entry_for_disposition(
    pool_root: Path,
    result_sha256: str,
) -> dict[str, Any]:
    """Load a sealed pool entry with ingest_kind-aware verifier dispatch.

    - ``EPISODE_EXPORT_MANIFEST`` → ``load_episode_pool_entry`` (episode export CAS)
    - all other / missing kinds → ``load_pool_entry`` (one-shot result/receipt)

    Does not invent a second seal/verification rule set; only chooses the loader
    that already owns each admission shape. Pool remains immutable; this path
    never sets owner_adopted or writes freeze.
    """

    digest = _require_hex64(
        result_sha256,
        "DISPOSITION_RESULT_HASH_INVALID",
        "result_sha256",
    )
    entry_path = pool_entry_path(pool_root, digest)
    if not entry_path.is_file():
        raise OwnerDispositionError("POOL_ENTRY_MISSING", digest)
    try:
        peek = json.loads(entry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OwnerDispositionError("POOL_ENTRY_INVALID", str(exc)) from exc
    if not isinstance(peek, Mapping):
        raise OwnerDispositionError("POOL_ENTRY_INVALID", "JSON object required")

    if peek.get("ingest_kind") == EPISODE_EXPORT_INGEST_KIND:
        try:
            return load_episode_pool_entry(pool_root, digest)
        except EpisodeExportAdapterError as exc:
            raise OwnerDispositionError(exc.reason_code, exc.detail) from exc

    try:
        return load_pool_entry(pool_root, digest)
    except CandidatePoolError as exc:
        raise OwnerDispositionError(exc.reason_code, exc.detail) from exc


def _parse_sealed_json_object(raw: bytes, *, reason_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OwnerDispositionError(reason_code, str(exc)) from exc
    if not isinstance(payload, dict):
        raise OwnerDispositionError(reason_code, "object required")
    return payload


def _load_xinao_runtime_module() -> Any:
    """Load the canonical Skill runtime that owns live attempt verification.

    The discovery wheel deliberately does not duplicate ResearchEpisode CAS,
    current-success pointer, provider-session, active-mount, or effective-prompt
    verification.  Production actor projection therefore calls the existing
    runtime verifier.  A repository checkout is preferred for candidate tests;
    an installed Skill is the packaged fallback.
    """

    candidates: list[Path] = []
    override = os.environ.get("XINAO_RUNTIME_SCRIPT")
    if override:
        candidates.append(Path(override))
    source_parents = Path(__file__).resolve().parents
    if len(source_parents) > 4:
        candidates.append(
            source_parents[4] / "skills/xinao/scripts/xinao_runtime.py"
        )
    candidates.append(Path.home() / ".codex/skills/xinao/scripts/xinao_runtime.py")
    runtime_path = next((path.resolve() for path in candidates if path.is_file()), None)
    if runtime_path is None:
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_RUNTIME_UNAVAILABLE",
            "xinao_runtime.py not found; set XINAO_RUNTIME_SCRIPT or install the XINAO Skill",
        )
    path_hash = hashlib.sha256(str(runtime_path).encode()).hexdigest()[:16]
    module_name = f"xinao_owner_runtime_{path_hash}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, runtime_path)
    if spec is None or spec.loader is None:
        raise OwnerDispositionError("RESEARCH_EPISODE_RUNTIME_UNAVAILABLE", str(runtime_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_RUNTIME_UNAVAILABLE", str(exc)[:2000]
        ) from exc
    return module


def _require_episode_actor_roots(
    *,
    episode_root: Path | None,
    portfolio_root: Path | None,
    authority_root: Path | None,
) -> tuple[Path, Path, Path]:
    if episode_root is None or portfolio_root is None or authority_root is None:
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_ACTOR_REALITY_ROOTS_REQUIRED",
            "episode_root, portfolio_root, and authority_root are required "
            "for production projection",
        )
    return (
        episode_root.expanduser().resolve(),
        portfolio_root.expanduser().resolve(),
        authority_root.expanduser().resolve(),
    )


def _project_episode_actor_intent(
    *,
    pool_entry: Mapping[str, Any],
    actor_intent_raw: Mapping[str, Any],
    episode_root: Path | None,
    portfolio_root: Path | None,
    authority_root: Path | None,
) -> dict[str, Any]:
    """Freshly join exact Episode intent to current live reality, without choices."""

    episode, portfolio, authority = _require_episode_actor_roots(
        episode_root=episode_root,
        portfolio_root=portfolio_root,
        authority_root=authority_root,
    )
    provenance = pool_entry.get("lab_provenance")
    if not isinstance(provenance, Mapping):
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_PROVENANCE_REQUIRED", "pool lab_provenance"
        )
    episode_id = _require_text(
        provenance.get("episode_id"), "RESEARCH_EPISODE_PROVENANCE_INVALID", "episode_id"
    )
    attempt_cas_digest = _require_hex64(
        provenance.get("attempt_cas_digest"),
        "RESEARCH_EPISODE_PROVENANCE_INVALID",
        "attempt_cas_digest",
    )
    attempt_hash = _require_hex64(
        provenance.get("attempt_hash"),
        "RESEARCH_EPISODE_PROVENANCE_INVALID",
        "attempt_hash",
    )
    cas_head_sha256 = _require_hex64(
        provenance.get("cas_head_sha256"),
        "RESEARCH_EPISODE_PROVENANCE_INVALID",
        "cas_head_sha256",
    )
    provider_session_uuid = _require_text(
        provenance.get("provider_session_uuid"),
        "RESEARCH_EPISODE_PROVENANCE_INVALID",
        "provider_session_uuid",
    )
    host_session_id = _require_text(
        provenance.get("host_session_id"),
        "RESEARCH_EPISODE_PROVENANCE_INVALID",
        "host_session_id",
    )
    runtime = _load_xinao_runtime_module()
    try:
        reality = runtime.research_episode_build_actor_reality(
            root=episode,
            portfolio_root=portfolio,
            authority_root=authority,
            attempt_cas_digest=attempt_cas_digest,
            expected_head_sha256=cas_head_sha256,
            expected_provider_session_uuid=provider_session_uuid,
            expected_host_session_id=host_session_id,
            attempt_hash=attempt_hash,
        )
        from xinao.shadow_lifecycle.actor_reality import (
            ActorAuthoredBehaviorIntent,
            build_complete_actor_behavior,
            build_shadow_freeze_input_candidate,
        )

        intent = ActorAuthoredBehaviorIntent.model_validate(dict(actor_intent_raw))
        if intent.content_hash is None:
            intent = intent.with_content_hash()
        behavior = build_complete_actor_behavior(
            reality,
            intent,
            candidate_ref=str(pool_entry["policy_ref"]),
        )
        projection = build_shadow_freeze_input_candidate(
            behavior,
            live_reality=reality,
        )
    except OwnerDispositionError:
        raise
    except Exception as exc:
        reason = getattr(exc, "reason_code", None) or "RESEARCH_EPISODE_ACTOR_PROJECTION_FAILED"
        detail = getattr(exc, "detail", None) or str(exc)
        raise OwnerDispositionError(str(reason), str(detail)[:2000]) from exc

    material_reality = reality.material_reality
    for label, observed, expected in (
        ("episode_id", material_reality.episode_id, episode_id),
        ("attempt_cas_digest", material_reality.attempt_cas_digest, attempt_cas_digest),
        ("attempt_hash", material_reality.attempt_hash, attempt_hash),
        ("cas_head_sha256", material_reality.cas_head_sha256, cas_head_sha256),
        ("provider_session_uuid", material_reality.provider_session_uuid, provider_session_uuid),
        ("host_session_id", material_reality.host_session_id, host_session_id),
    ):
        if observed != expected:
            raise OwnerDispositionError(
                "RESEARCH_EPISODE_ACTOR_PROJECTION_PROVENANCE_MISMATCH", label
            )
    projection_payload = projection.model_dump(mode="json")
    return {
        "projection": projection_payload,
        "actor_intent_content_hash": str(intent.content_hash),
        "actor_behavior_content_hash": str(behavior.content_hash),
        "actor_reality_contract_hash": str(reality.content_hash),
        "research_lineage_ref": str(behavior.research_lineage_ref),
        "episode_id": episode_id,
        "attempt_cas_digest": attempt_cas_digest,
        "attempt_hash": attempt_hash,
        "cas_head_sha256": cas_head_sha256,
        "provider_session_uuid": provider_session_uuid,
        "host_session_id": host_session_id,
    }


def _researcher_executable_core(
    raw: Mapping[str, Any],
    *,
    disposition_frozen_at: object,
) -> dict[str, Any]:
    missing = sorted(_RESEARCHER_EXECUTABLE_CORE - set(raw))
    unknown = sorted(set(raw) - _RESEARCHER_EXECUTABLE_CORE)
    if missing:
        raise OwnerDispositionError(
            "RESEARCHER_EXECUTABLE_DECISION_INCOMPLETE",
            f"missing={missing}",
        )
    if unknown:
        raise OwnerDispositionError(
            "RESEARCHER_EXECUTABLE_DECISION_UNKNOWN_FIELDS",
            f"unknown={unknown}",
        )
    # Reuse the production executable validator. The Owner-controlled seal time
    # participates only in temporal validation; it is not attributed to research.
    normalized = _validate_executable_account_decision(
        {**dict(raw), "frozen_at": disposition_frozen_at}
    )
    return {key: normalized[key] for key in sorted(_RESEARCHER_EXECUTABLE_CORE)}


def _researcher_no_action_core(
    raw: Mapping[str, Any],
    *,
    disposition_frozen_at: object,
) -> dict[str, Any]:
    missing = sorted(_RESEARCHER_NO_ACTION_CORE - set(raw))
    unknown = sorted(set(raw) - _RESEARCHER_NO_ACTION_CORE)
    if missing:
        raise OwnerDispositionError(
            "RESEARCHER_NO_ACTION_INTENT_INCOMPLETE",
            f"missing={missing}",
        )
    if unknown:
        raise OwnerDispositionError(
            "RESEARCHER_NO_ACTION_INTENT_UNKNOWN_FIELDS",
            f"unknown={unknown}",
        )
    normalized = _validate_no_action_times(
        {**dict(raw), "frozen_at": disposition_frozen_at}
    )
    return {key: normalized[key] for key in sorted(_RESEARCHER_NO_ACTION_CORE)}


def _load_sealed_researcher_decision(
    *,
    pool_root: Path,
    pool_entry: Mapping[str, Any],
    episode_root: Path | None = None,
    portfolio_root: Path | None = None,
    authority_root: Path | None = None,
) -> dict[str, Any]:
    """Return one actor branch; Episode intent is freshly joined to live reality."""

    if pool_entry.get("status") != "CANDIDATE_READY":
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_STATUS_NOT_READY",
            str(pool_entry.get("status")),
        )

    result_sha = _require_hex64(
        pool_entry.get("result_sha256"),
        "POOL_RESULT_HASH_INVALID",
        "result_sha256",
    )
    if pool_entry.get("ingest_kind") == EPISODE_EXPORT_INGEST_KIND:
        source_path = pool_receipt_path(pool_root, result_sha)
        source_raw = source_path.read_bytes()
        source_artifact_sha = raw_sha256(source_raw)
        expected_source_sha = _require_hex64(
            pool_entry.get("receipt_content_sha256"),
            "DISPOSITION_RECEIPT_HASH_INVALID",
            "receipt_content_sha256",
        )
        source = _parse_sealed_json_object(
            source_raw,
            reason_code="RESEARCHER_EXECUTABLE_SOURCE_INVALID",
        )
        recommendation = source.get("account_recommendation")
        proposed = source.get("proposed")
        if recommendation == "NO_RECOMMENDATION":
            # Historical/read-only compatibility: an old manifest may contain a
            # full branch despite claiming no recommendation. Draft/audit can
            # still inspect it; formal Episode disposition rejects it later for
            # lacking actor_projection_evidence.
            producer = proposed if isinstance(proposed, Mapping) else None
            actor_projection_evidence = None
        else:
            if recommendation not in {"ACTION_CANDIDATE", "NO_ACTION_CANDIDATE"}:
                raise OwnerDispositionError(
                    "RESEARCHER_DECISION_SOURCE_ABSENT", "$.proposed"
                )
            if not isinstance(proposed, Mapping):
                raise OwnerDispositionError("RESEARCHER_ACTOR_INTENT_REQUIRED", "$.proposed")
            try:
                actor_intent = validate_actor_authored_behavior_intent(proposed)
            except CandidateManifestError as exc:
                raise OwnerDispositionError(
                    "RESEARCHER_ACTOR_INTENT_REQUIRED", str(exc.detail)[:2000]
                ) from exc
            expected_kind = "ACTION" if recommendation == "ACTION_CANDIDATE" else "NO_ACTION"
            if actor_intent.get("decision_kind") != expected_kind:
                raise OwnerDispositionError(
                    "RESEARCHER_ACTOR_INTENT_BRANCH_MISMATCH",
                    f"recommendation={recommendation} intent={actor_intent.get('decision_kind')}",
                )
            actor_projection_evidence = _project_episode_actor_intent(
                pool_entry=pool_entry,
                actor_intent_raw=actor_intent,
                episode_root=episode_root,
                portfolio_root=portfolio_root,
                authority_root=authority_root,
            )
            projection = actor_projection_evidence["projection"]
            if not isinstance(projection, Mapping):
                raise OwnerDispositionError(
                    "RESEARCH_EPISODE_ACTOR_PROJECTION_FAILED", "projection object required"
                )
            producer = projection
        source_kind = "EPISODE_CANDIDATE_MANIFEST"
        source_json_root = "$.proposed"
    else:
        if episode_root is not None:
            raise OwnerDispositionError(
                "PRODUCTION_ACTOR_EPISODE_SOURCE_KIND_REQUIRED",
                "actor Episode reality roots cannot authorize a legacy one-shot producer",
            )
        source_path = pool_result_bytes_path(pool_root, result_sha)
        source_raw = source_path.read_bytes()
        source_artifact_sha = raw_sha256(source_raw)
        expected_source_sha = result_sha
        source = _parse_sealed_json_object(
            source_raw,
            reason_code="RESEARCHER_EXECUTABLE_SOURCE_INVALID",
        )
        candidate = source.get("candidate")
        producer = candidate if isinstance(candidate, Mapping) else None
        actor_projection_evidence = None
        source_kind = "ONESHOT_RESEARCH_RESULT"
        source_json_root = "$.candidate"
    if source_artifact_sha != expected_source_sha:
        raise OwnerDispositionError(
            "RESEARCHER_EXECUTABLE_SOURCE_HASH_MISMATCH",
            f"source={source_artifact_sha} expected={expected_source_sha}",
        )
    if not isinstance(producer, Mapping):
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_SOURCE_ABSENT",
            source_json_root,
        )

    authored_action = producer.get("executable_account_decision")
    authored_no_action = producer.get("no_action_intent")
    has_action = isinstance(authored_action, Mapping)
    has_no_action = isinstance(authored_no_action, Mapping)
    if not has_action and not has_no_action:
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_SOURCE_ABSENT",
            f"{source_json_root}: signal-only candidate has no account decision",
        )
    if has_action and has_no_action:
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_BRANCH_INVALID",
            "sealed producer must carry exactly one "
            "executable_account_decision or no_action_intent",
        )

    account_identity = ACCOUNT_ACTION if has_action else ACCOUNT_NO_ACTION
    declared_identity = producer.get("account_identity")
    if declared_identity is not None and declared_identity != account_identity:
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_IDENTITY_CONFLICT",
            f"declared={declared_identity!r} branch={account_identity!r}",
        )
    source_json_path = (
        source_json_root
        if actor_projection_evidence is not None
        else (
            f"{source_json_root}.executable_account_decision"
            if has_action
            else f"{source_json_root}.no_action_intent"
        )
    )
    result = {
        "account_identity": account_identity,
        "authored": authored_action if has_action else authored_no_action,
        "source_kind": source_kind,
        "source_artifact_sha256": source_artifact_sha,
        "source_json_path": source_json_path,
        "result_sha256": result_sha,
        "pool_entry_content_hash": str(pool_entry["content_hash"]),
    }
    if actor_projection_evidence is not None:
        result["actor_projection_evidence"] = actor_projection_evidence
    return result


def verify_researcher_authored_decision(
    *,
    pool_root: Path,
    pool_entry: Mapping[str, Any],
    disposition: Mapping[str, Any],
    episode_root: Path | None = None,
    portfolio_root: Path | None = None,
    authority_root: Path | None = None,
) -> dict[str, Any]:
    """Bind the Owner disposition to the exact sealed researcher branch.

    Both ACTION and NO_ACTION must be present in producer bytes. The Owner may
    only dispose that branch; changing its identity, selection, stake, target,
    rule, odds, or cutoff is rejected before Owner CAS creation or freeze.
    """

    producer = _load_sealed_researcher_decision(
        pool_root=pool_root,
        pool_entry=pool_entry,
        episode_root=episode_root,
        portfolio_root=portfolio_root,
        authority_root=authority_root,
    )
    account_identity = disposition.get("account_identity")
    if account_identity != producer["account_identity"]:
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_IDENTITY_MISMATCH",
            f"producer={producer['account_identity']} disposition={account_identity}",
        )
    authored = producer["authored"]
    if not isinstance(authored, Mapping):
        raise OwnerDispositionError(
            "RESEARCHER_DECISION_SOURCE_ABSENT",
            str(producer["source_json_path"]),
        )

    if account_identity == ACCOUNT_ACTION:
        executable = disposition.get("executable_account_decision")
        if not isinstance(executable, Mapping):
            raise OwnerDispositionError(
                "ACTION_REQUIRES_EXECUTABLE_DECISION",
                "normalized ACTION executable missing",
            )
        source_core = _researcher_executable_core(
            authored,
            disposition_frozen_at=executable.get("frozen_at"),
        )
        disposition_core = {
            key: executable[key] for key in sorted(_RESEARCHER_EXECUTABLE_CORE)
        }
        schema_version = RESEARCHER_ACTION_BINDING_SCHEMA
        mismatch_code = "RESEARCHER_EXECUTABLE_DECISION_MISMATCH"
        hash_key = "executable_content_hash"
    else:
        no_action_binding = disposition.get("no_action_period_binding")
        if not isinstance(no_action_binding, Mapping):
            raise OwnerDispositionError(
                "NO_ACTION_BINDING_REQUIRED",
                "normalized NO_ACTION binding missing",
            )
        source_core = _researcher_no_action_core(
            authored,
            disposition_frozen_at=no_action_binding.get("frozen_at"),
        )
        disposition_core = {
            key: no_action_binding[key] for key in sorted(_RESEARCHER_NO_ACTION_CORE)
        }
        schema_version = RESEARCHER_NO_ACTION_BINDING_SCHEMA
        mismatch_code = "RESEARCHER_NO_ACTION_INTENT_MISMATCH"
        hash_key = "no_action_content_hash"

    if source_core != disposition_core:
        diverged = sorted(
            key
            for key in source_core
            if source_core.get(key) != disposition_core.get(key)
        )
        raise OwnerDispositionError(
            mismatch_code,
            f"fields={diverged}",
        )
    decision_hash = canonical_sha256(source_core)
    binding: dict[str, Any] = {
        "schema_version": schema_version,
        "account_identity": account_identity,
        "source_kind": producer["source_kind"],
        "source_artifact_sha256": producer["source_artifact_sha256"],
        "source_json_path": producer["source_json_path"],
        "decision_content_hash": decision_hash,
        hash_key: decision_hash,
        "result_sha256": producer["result_sha256"],
        "pool_entry_content_hash": producer["pool_entry_content_hash"],
    }
    actor_evidence = producer.get("actor_projection_evidence")
    if not isinstance(actor_evidence, Mapping):
        if pool_entry.get("ingest_kind") == EPISODE_EXPORT_INGEST_KIND:
            raise OwnerDispositionError(
                "PRODUCTION_ACTOR_INTENT_REQUIRED",
                "ResearchEpisode production requires exact actor intent plus "
                "live reality projection",
            )
        # Existing one-shot/history consumers remain compatibility-shaped. They
        # are not evidence that the multi-turn ResearchEpisode actor path is
        # projected or complete.
        return binding
    projection = actor_evidence.get("projection")
    if not isinstance(projection, Mapping):
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_ACTOR_PROJECTION_FAILED", "projection evidence missing"
        )
    projection_map = dict(projection)
    if projection_map.get("account_identity") != account_identity:
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_ACTOR_PROJECTION_BRANCH_MISMATCH", str(account_identity)
        )
    for key in (
        "actor_id",
        "research_lineage_ref",
        "actor_reality_contract_hash",
        "actor_behavior_content_hash",
        "actor_authored_intent_hash",
        "episode_id",
        "cas_head_sha256",
        "attempt_cas_digest",
        "attempt_hash",
        "provider_session_uuid",
        "active_material_binding_hash",
        "information_set_ref",
        "information_set_hash",
        "material_packet_sha256",
        "effective_prompt_sha256",
        "prospective_packet_content_hash",
        "source_authority_binding_hash",
        "objective_terms_content_hash",
    ):
        value = projection_map.get(key)
        if not isinstance(value, str) or not value:
            raise OwnerDispositionError(
                "RESEARCH_EPISODE_ACTOR_PROJECTION_INCOMPLETE", key
            )
        binding[key] = value
    if binding["actor_authored_intent_hash"] != actor_evidence.get(
        "actor_intent_content_hash"
    ):
        raise OwnerDispositionError(
            "RESEARCH_EPISODE_ACTOR_INTENT_HASH_MISMATCH", "projection vs manifest intent"
        )
    binding["actor_projection"] = projection_map
    return binding


def verify_researcher_authored_action(
    *,
    pool_root: Path,
    pool_entry: Mapping[str, Any],
    disposition: Mapping[str, Any],
    episode_root: Path | None = None,
    portfolio_root: Path | None = None,
    authority_root: Path | None = None,
) -> dict[str, Any] | None:
    """Backward-compatible ACTION-only view over the symmetric verifier."""

    binding = verify_researcher_authored_decision(
        pool_root=pool_root,
        pool_entry=pool_entry,
        disposition=disposition,
        episode_root=episode_root,
        portfolio_root=portfolio_root,
        authority_root=authority_root,
    )
    return binding if binding["account_identity"] == ACCOUNT_ACTION else None


def load_and_verify_disposition(
    *,
    disposition_path: Path,
    owner_state_root: Path,
    pool_root: Path,
    result_sha256: str | None = None,
    episode_root: Path | None = None,
    portfolio_root: Path | None = None,
    authority_root: Path | None = None,
) -> dict[str, Any]:
    """Load disposition under owner root, bind raw bytes hash, verify pool entry.

    Library authority claims are intentionally non-authenticating: path separation
    and content addressing only.
    """

    assert_owner_root_separated_from_pool(owner_state_root=owner_state_root, pool_root=pool_root)
    path = assert_path_under_owner_root(disposition_path, owner_state_root)
    raw = path.read_bytes()
    if not raw:
        raise OwnerDispositionError("DISPOSITION_ARTIFACT_EMPTY", str(path))
    artifact_sha256 = raw_sha256(raw)
    # Path digest must equal raw bytes hash (single content-address mode).
    if path.name != f"{artifact_sha256}.json" or path.parent.name != artifact_sha256[:2]:
        raise OwnerDispositionError(
            "DISPOSITION_CAS_PATH_MISMATCH",
            f"path digest must equal raw sha256; path={path.name} raw={artifact_sha256}",
        )
    expected_path = disposition_cas_path(owner_state_root, artifact_sha256)
    if path.resolve() != expected_path.resolve():
        raise OwnerDispositionError(
            "DISPOSITION_CAS_PATH_MISMATCH",
            f"require {expected_path}, got {path}",
        )

    payload = parse_disposition_json_strict(raw)
    if "owner_artifact_sha256" in payload:
        raise OwnerDispositionError(
            "DISPOSITION_SELF_HASH_FORBIDDEN",
            "self-referential owner_artifact_sha256 is not allowed",
        )

    claimed_result = payload.get("result_sha256")
    if result_sha256 is not None and claimed_result != result_sha256:
        raise OwnerDispositionError(
            "DISPOSITION_RESULT_HASH_MISMATCH",
            f"caller={result_sha256} disposition={claimed_result}",
        )
    digest = _require_hex64(claimed_result, "DISPOSITION_RESULT_HASH_INVALID", "result_sha256")
    pool_entry = load_verified_pool_entry_for_disposition(pool_root, digest)

    normalized = validate_disposition_payload(payload, pool_entry=pool_entry)
    researcher_decision_binding = verify_researcher_authored_decision(
        pool_root=pool_root,
        pool_entry=pool_entry,
        disposition=normalized,
        episode_root=episode_root,
        portfolio_root=portfolio_root,
        authority_root=authority_root,
    )
    researcher_action_binding = (
        researcher_decision_binding
        if researcher_decision_binding["account_identity"] == ACCOUNT_ACTION
        else None
    )
    return {
        "disposition_path": str(path),
        "owner_state_root": str(resolve_owner_state_root(owner_state_root)),
        "owner_artifact_sha256": artifact_sha256,
        "pool_entry": pool_entry,
        "disposition": normalized,
        "researcher_decision_binding": researcher_decision_binding,
        "researcher_action_binding": researcher_action_binding,
        # Honest library surface: never self-certify Codex identity.
        "owner_channel_authority": OWNER_CHANNEL_AUTHORITY_UNPROVEN,
        "path_separated_from_pool": True,
        "physical_owner_write_isolation_verified": False,
        "owner_disposition_authentic": False,
        "cryptographic_identity_forged": False,
    }


def require_period_account_identity(
    disposition: Mapping[str, Any],
) -> Literal[
    "ACTION",
    "RESEARCHER_ACCOUNT_NO_ACTION",
]:
    identity = disposition.get("account_identity")
    if identity not in _ACCOUNT_IDENTITIES:
        raise OwnerDispositionError(
            "PERIOD_ACCOUNT_IDENTITY_REQUIRED",
            "each period must explicitly choose ACTION or RESEARCHER_ACCOUNT_NO_ACTION",
        )
    return identity  # type: ignore[return-value]


def disposition_information_set_hash(
    *,
    result_sha256: str,
    receipt_content_sha256: str,
    target_ref: str,
    research_binding_sha256: str,
) -> str:
    """Canonical information-set hash for AccountRiskTicket binding."""

    return canonical_sha256(
        {
            "binding": "XINAO_DISPOSITION_INFORMATION_SET_V1",
            "result_sha256": result_sha256,
            "receipt_content_sha256": receipt_content_sha256,
            "target_ref": target_ref,
            "research_binding_sha256": research_binding_sha256,
        }
    )


__all__ = [
    "ACCOUNT_ACTION",
    "ACCOUNT_NO_ACTION",
    "AUTHENTIC_DISPOSITION_SOURCE",
    "CODEX_OWNER_CHANNEL_SOURCE",
    "DISPOSITION_MARKER",
    "DISPOSITION_SCHEMA_VERSION",
    "DRAFT_SOURCE",
    "DRAFT_STATUS",
    "OWNER_CHANNEL_AUTHORITY_UNPROVEN",
    "REQUIRED_OWNER_INPUT",
    "RESEARCHER_ACTION_BINDING_SCHEMA",
    "RESEARCHER_NO_ACTION_BINDING_SCHEMA",
    "SCIENCE_ABSORB_NO_ACTION",
    "SCIENCE_ADOPT",
    "SCIENCE_DEFER",
    "SCIENCE_REJECT",
    "SCIENCE_RETAIN_FOR_SHADOW",
    "OwnerDispositionError",
    "assert_owner_root_separated_from_pool",
    "assert_path_under_owner_root",
    "disposition_cas_path",
    "disposition_information_set_hash",
    "draft_owner_disposition",
    "encode_disposition_bytes",
    "load_and_verify_disposition",
    "load_verified_pool_entry_for_disposition",
    "parse_disposition_json_strict",
    "raw_sha256",
    "reject_forbidden_outcome_material",
    "require_period_account_identity",
    "resolve_owner_state_root",
    "validate_disposition_payload",
    "validate_portfolio_binding",
    "verify_researcher_authored_decision",
    "write_owner_disposition_artifact",
]
