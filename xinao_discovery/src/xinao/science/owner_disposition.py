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
self-referential hash field. ACTION numbers/stake come only from structured
executable decisions (never research prose).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, Literal

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal
from xinao.science.candidate_pool import CandidatePoolError, load_pool_entry, verify_pool_entry_seal
from xinao.science.prospective_source_thin import (
    ProspectiveSourceError,
    is_live_macaujc2_target,
    validate_source_authority_binding,
)

DISPOSITION_SCHEMA_VERSION: Final = "xinao.codex_owner_disposition.v1"
DISPOSITION_MARKER: Final = "XINAO_CODEX_OWNER_DISPOSITION_V1"

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
        SCIENCE_REJECT,
        SCIENCE_DEFER,
        SCIENCE_ABSORB_NO_ACTION,
        SCIENCE_RETAIN_FOR_SHADOW,
    }
)
# Science grades that forbid placing stake (must not be smuggled into ACTION).
_SCIENCE_FORBIDS_ACTION: Final = frozenset(
    {
        SCIENCE_REJECT,
        SCIENCE_ABSORB_NO_ACTION,
        SCIENCE_DEFER,
    }
)

# Historical string still required on the disposition payload so live Codex calls
# remain explicit. It is **not** treated as cryptographic owner proof.
CODEX_OWNER_CHANNEL_SOURCE: Final = "codex_owner_channel"
# Backward-compatible alias used by older call sites / tests.
AUTHENTIC_DISPOSITION_SOURCE: Final = CODEX_OWNER_CHANNEL_SOURCE

OWNER_CHANNEL_AUTHORITY_UNPROVEN: Final = "UNPROVEN_BY_LIBRARY"

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
    if payload.get("worker_controlled") is True:
        raise OwnerDispositionError(
            "DISPOSITION_WORKER_CONTROLLED",
            "worker_controlled=true rejected",
        )
    # owner_role alone is never sufficient; still record if present.
    owner_role = payload.get("owner_role")
    if owner_role is not None and owner_role != "codex":
        raise OwnerDispositionError("DISPOSITION_OWNER_ROLE_INVALID", str(owner_role))

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
    if science_disposition in _SCIENCE_FORBIDS_ACTION and account_identity == ACCOUNT_ACTION:
        raise OwnerDispositionError(
            "SCIENCE_ACCOUNT_MATRIX_VIOLATION",
            f"{science_disposition} must not carry account_identity=ACTION; "
            f"use {SCIENCE_RETAIN_FOR_SHADOW} for shadow production ACTION without science adopt",
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
    # Optional science identity override for freeze science branch.
    science_identity = payload.get("science_identity")
    if science_identity is not None:
        if science_identity not in ("SCIENCE_CANDIDATE", "POLICY_NO_ACTION"):
            raise OwnerDispositionError("SCIENCE_IDENTITY_INVALID", str(science_identity))
        normalized["science_identity"] = science_identity
    else:
        # ADOPT / RETAIN_FOR_SHADOW keep candidate identity; others → policy no-action.
        if science_disposition in (SCIENCE_ADOPT, SCIENCE_RETAIN_FOR_SHADOW):
            normalized["science_identity"] = "SCIENCE_CANDIDATE"
        else:
            normalized["science_identity"] = "POLICY_NO_ACTION"

    return normalized


def write_owner_disposition_artifact(
    *,
    owner_state_root: Path,
    payload: Mapping[str, Any],
    pool_root: Path | None = None,
) -> dict[str, Any]:
    """Write disposition as raw-SHA256 content-addressed exclusive JSON (no self-hash).

    Returns path + raw artifact hash. Same hash with different bytes fails closed.
    """

    if pool_root is not None:
        assert_owner_root_separated_from_pool(
            owner_state_root=owner_state_root,
            pool_root=pool_root,
        )
    root = resolve_owner_state_root(owner_state_root)
    root.mkdir(parents=True, exist_ok=True)
    if "owner_artifact_sha256" in payload:
        raise OwnerDispositionError(
            "DISPOSITION_SELF_HASH_FORBIDDEN",
            "do not embed owner_artifact_sha256; path is the content address",
        )
    # Structural pre-check only: forbid outcome smuggle, unknown top-level keys,
    # and non-owner-channel source labels before bytes are sealed. Full pool
    # binding still happens on load/verify.
    _reject_unknown_keys(
        payload,
        _TOP_LEVEL_ALLOWED,
        reason_code="DISPOSITION_UNKNOWN_FIELDS",
    )
    reject_forbidden_outcome_material(payload)
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
    if payload.get("worker_controlled") is True:
        raise OwnerDispositionError(
            "DISPOSITION_WORKER_CONTROLLED",
            "worker_controlled=true rejected",
        )
    raw = encode_disposition_bytes(payload)
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
        }
    return {
        "disposition_path": str(path),
        "owner_artifact_sha256": digest,
        "owner_state_root": str(root),
        "bytes_written": True,
    }


def load_and_verify_disposition(
    *,
    disposition_path: Path,
    owner_state_root: Path,
    pool_root: Path,
    result_sha256: str | None = None,
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
    try:
        pool_entry = load_pool_entry(pool_root, digest)
    except CandidatePoolError as exc:
        raise OwnerDispositionError(exc.reason_code, exc.detail) from exc

    normalized = validate_disposition_payload(payload, pool_entry=pool_entry)
    return {
        "disposition_path": str(path),
        "owner_state_root": str(resolve_owner_state_root(owner_state_root)),
        "owner_artifact_sha256": artifact_sha256,
        "pool_entry": pool_entry,
        "disposition": normalized,
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
    "OWNER_CHANNEL_AUTHORITY_UNPROVEN",
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
    "encode_disposition_bytes",
    "load_and_verify_disposition",
    "parse_disposition_json_strict",
    "raw_sha256",
    "reject_forbidden_outcome_material",
    "require_period_account_identity",
    "resolve_owner_state_root",
    "validate_disposition_payload",
    "validate_portfolio_binding",
    "write_owner_disposition_artifact",
]
