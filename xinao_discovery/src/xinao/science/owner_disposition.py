"""Codex Owner disposition bound to a candidate pool entry.

Physical owner-write isolation is a host/container mount responsibility: this
module requires the disposition artifact to live under a caller-supplied
``owner_state_root`` that is path-separated from the candidate pool, and binds
the disposition to the raw file bytes via content hash.

A lone ``owner_role=codex`` text field is never sufficient. Worker / fixture /
mock / self sources are rejected. No cryptographic identity is forged here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from xinao.canonical import canonical_sha256
from xinao.science.candidate_pool import CandidatePoolError, load_pool_entry, verify_pool_entry_seal

DISPOSITION_SCHEMA_VERSION: Final = "xinao.codex_owner_disposition.v1"
DISPOSITION_MARKER: Final = "XINAO_CODEX_OWNER_DISPOSITION_V1"

ACCOUNT_ACTION: Final = "ACTION"
ACCOUNT_NO_ACTION: Final = "RESEARCHER_ACCOUNT_NO_ACTION"
_ACCOUNT_IDENTITIES: Final = frozenset({ACCOUNT_ACTION, ACCOUNT_NO_ACTION})

SCIENCE_ADOPT: Final = "ADOPT"
SCIENCE_REJECT: Final = "REJECT"
SCIENCE_DEFER: Final = "DEFER"
SCIENCE_ABSORB_NO_ACTION: Final = "ABSORB_NO_ACTION"
_SCIENCE_DISPOSITIONS: Final = frozenset(
    {
        SCIENCE_ADOPT,
        SCIENCE_REJECT,
        SCIENCE_DEFER,
        SCIENCE_ABSORB_NO_ACTION,
    }
)

AUTHENTIC_DISPOSITION_SOURCE: Final = "codex_owner_channel"
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


def _raw_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    try:
        owner.relative_to(pool)
        raise OwnerDispositionError(
            "OWNER_ROOT_NESTED_IN_POOL",
            "owner_state_root must not be nested under pool_root",
        )
    except ValueError:
        pass
    try:
        pool.relative_to(owner)
        raise OwnerDispositionError(
            "POOL_NESTED_IN_OWNER_ROOT",
            "pool_root must not be nested under owner_state_root",
        )
    except ValueError:
        pass


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
    # Reject unknown keys that could smuggle prose-derived defaults.
    allowed = required | {"ticket_ref", "information_set_ref"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise OwnerDispositionError(
            "EXECUTABLE_DECISION_UNKNOWN_FIELDS",
            f"unknown={unknown}",
        )

    panel = raw.get("panel")
    if panel not in ("A", "B"):
        raise OwnerDispositionError("EXECUTABLE_PANEL_INVALID", str(panel))
    selected = raw.get("selected_number")
    if type(selected) is not int or not (1 <= selected <= 49):
        raise OwnerDispositionError("EXECUTABLE_NUMBER_INVALID", str(selected))
    stake = raw.get("stake")
    if not isinstance(stake, str) or not stake:
        raise OwnerDispositionError("EXECUTABLE_STAKE_INVALID", "stake must be decimal string")
    # Positive stake for ACTION; exact scale checked by AccountRiskTicket later.
    try:
        stake_value = float(stake)
    except ValueError as exc:
        raise OwnerDispositionError("EXECUTABLE_STAKE_INVALID", str(stake)) from exc
    if stake_value <= 0:
        raise OwnerDispositionError("EXECUTABLE_STAKE_INVALID", "ACTION stake must be positive")

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
    forbidden_ticket_fields = {
        "panel",
        "selected_number",
        "stake",
        "baseline_ref",
        "risk_policy_ref",
        "ticket_ref",
    }
    present_ticket = sorted(forbidden_ticket_fields & set(raw))
    if present_ticket:
        raise OwnerDispositionError(
            "NO_ACTION_MUST_NOT_CARRY_TICKET",
            f"fields={present_ticket}",
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
            "DISPOSITION_SOURCE_NOT_AUTHENTIC",
            f"disposition_source={source!r} is not owner-authentic",
        )
    if source != AUTHENTIC_DISPOSITION_SOURCE:
        raise OwnerDispositionError(
            "DISPOSITION_SOURCE_NOT_AUTHENTIC",
            f"require {AUTHENTIC_DISPOSITION_SOURCE!r}, got {source!r}",
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

    normalized: dict[str, Any] = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_marker": DISPOSITION_MARKER,
        "disposition_source": AUTHENTIC_DISPOSITION_SOURCE,
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
        # Default: ADOPT/DEFER keep candidate identity; REJECT/ABSORB_NO_ACTION → policy no-action.
        if science_disposition in (SCIENCE_ADOPT, SCIENCE_DEFER):
            normalized["science_identity"] = "SCIENCE_CANDIDATE"
        else:
            normalized["science_identity"] = "POLICY_NO_ACTION"

    return normalized


def load_and_verify_disposition(
    *,
    disposition_path: Path,
    owner_state_root: Path,
    pool_root: Path,
    result_sha256: str | None = None,
) -> dict[str, Any]:
    """Load disposition from owner root, bind bytes hash, verify against pool entry.

    Returns a verified package including raw artifact hash and normalized body.
    """

    assert_owner_root_separated_from_pool(owner_state_root=owner_state_root, pool_root=pool_root)
    path = assert_path_under_owner_root(disposition_path, owner_state_root)
    raw = path.read_bytes()
    if not raw:
        raise OwnerDispositionError("DISPOSITION_ARTIFACT_EMPTY", str(path))
    artifact_sha256 = _raw_sha256(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OwnerDispositionError("DISPOSITION_JSON_INVALID", str(exc)) from exc
    if not isinstance(payload, Mapping):
        raise OwnerDispositionError("DISPOSITION_JSON_INVALID", "object required")

    declared_hash = payload.get("owner_artifact_sha256")
    if declared_hash is not None:
        declared = _require_hex64(
            declared_hash,
            "DISPOSITION_ARTIFACT_HASH_INVALID",
            "owner_artifact_sha256",
        )
        # Hash of payload without the self-hash field, OR raw file hash of the
        # sealed file that includes a precomputed hash of the body. We accept
        # only: declared hash equals raw file bytes hash of a body file that
        # does not embed the hash (caller may supply hash out-of-band), OR the
        # declared field equals sha256 of the JSON body excluding this field.
        body_without_hash = {k: v for k, v in payload.items() if k != "owner_artifact_sha256"}
        body_bytes = (
            json.dumps(body_without_hash, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        body_hash = _raw_sha256(body_bytes)
        if declared not in {artifact_sha256, body_hash}:
            raise OwnerDispositionError(
                "DISPOSITION_ARTIFACT_HASH_MISMATCH",
                "owner_artifact_sha256 does not bind disposition file bytes",
            )
    else:
        # Require the field so live path cannot skip artifact binding.
        raise OwnerDispositionError(
            "DISPOSITION_ARTIFACT_HASH_REQUIRED",
            "owner_artifact_sha256 must bind the disposition artifact",
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
        "declared_owner_artifact_sha256": str(payload.get("owner_artifact_sha256")),
        "pool_entry": pool_entry,
        "disposition": normalized,
        "owner_disposition_authentic": True,
        # Physical write isolation is mount/host enforced; not crypto identity.
        "physical_owner_write_isolation": "host_or_container_mount_boundary",
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
) -> str:
    """Canonical information-set hash for AccountRiskTicket binding."""

    return canonical_sha256(
        {
            "binding": "XINAO_DISPOSITION_INFORMATION_SET_V1",
            "result_sha256": result_sha256,
            "receipt_content_sha256": receipt_content_sha256,
            "target_ref": target_ref,
        }
    )


__all__ = [
    "ACCOUNT_ACTION",
    "ACCOUNT_NO_ACTION",
    "AUTHENTIC_DISPOSITION_SOURCE",
    "DISPOSITION_MARKER",
    "DISPOSITION_SCHEMA_VERSION",
    "OwnerDispositionError",
    "assert_owner_root_separated_from_pool",
    "assert_path_under_owner_root",
    "disposition_information_set_hash",
    "load_and_verify_disposition",
    "require_period_account_identity",
    "resolve_owner_state_root",
    "validate_disposition_payload",
]
