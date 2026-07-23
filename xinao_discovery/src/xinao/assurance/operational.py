"""Deterministic, fail-closed materialization for G8 operational assurance.

This module does not implement security, recovery, capacity, or supply-chain
controls. It consumes their exact evidence and emits one replayable G8 report.
Missing, stale, tampered, non-independent, or incomplete evidence produces a
valid DENY report. G8 alone never grants live-shadow or parent completion.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256

DIMENSION_EVIDENCE_SCHEMA_VERSION = "xinao.operational_assurance_dimension_evidence.v1"
OPERATIONAL_ASSURANCE_SCHEMA_VERSION = "xinao.operational_assurance_report.v1"
OPERATIONAL_ASSURANCE_VERIFICATION_SCHEMA_VERSION = "xinao.operational_assurance_verification.v1"

REQUIRED_DIMENSION_CHECKS: dict[str, tuple[str, ...]] = {
    "security_negative": (
        "prompt_or_data_injection_rejected",
        "sandbox_escape_rejected",
        "secret_leak_rejected",
        "unauthorized_agent_write_rejected",
        "evidence_rewrite_rejected",
        "resource_exhaustion_rejected",
    ),
    "reproducibility": (
        "locked_environment_replayed",
        "report_replayed_exactly",
        "subject_inputs_hash_bound",
    ),
    "capacity": (
        "token_call_wall_source_bounds_enforced",
        "queue_and_action_limits_enforced",
        "timeout_and_graceful_degradation_verified",
    ),
    "real_recovery": (
        "isolated_restore_completed",
        "restored_artifact_hashes_verified",
        "temporal_history_replayed",
        "research_and_admission_state_restored",
        "downstream_user_effect_canary_passed",
    ),
    "supply_chain": (
        "lockfile_or_dependency_tamper_rejected",
        "image_or_build_subject_digest_verified",
        "build_provenance_verified",
        "sbom_bound_and_verified",
    ),
    "independent_audit": (
        "producer_verifier_separation_verified",
        "subject_hashes_independently_rechecked",
        "negative_matrix_independently_replayed",
    ),
}
REQUIRED_DIMENSIONS = tuple(REQUIRED_DIMENSION_CHECKS)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIMENSION_FIELDS = {
    "schema_version",
    "dimension",
    "scope",
    "realm",
    "subject",
    "status",
    "producer_identity",
    "verifier_identity",
    "independent",
    "independence_evidence_ref",
    "issued_at",
    "expires_at",
    "revoked_at",
    "revocation_reason",
    "check_results",
    "content_hash",
}
_CHECK_FIELDS = {"check_id", "outcome", "evidence_refs", "rollback_ref"}


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _hash_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        return {}
    normalized = {str(key): str(item).lower() for key, item in value.items()}
    if not all(key and _is_sha256(item) for key, item in normalized.items()):
        return {}
    return dict(sorted(normalized.items()))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def evidence_ref(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    raw = resolved.read_bytes()
    return {
        "path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _resolve_ref(raw_ref: str, evidence_root: Path | None = None) -> Path:
    direct = Path(raw_ref)
    if direct.is_file() or evidence_root is None:
        return direct
    normalized = raw_ref.replace("\\", "/")
    marker = "/XINAO_RESEARCH_RUNTIME/"
    position = normalized.upper().find(marker)
    if position >= 0:
        relative = normalized[position + len(marker) :]
        return evidence_root.joinpath(*relative.split("/"))
    return direct


def _valid_evidence_ref(value: object, *, evidence_root: Path | None = None) -> bool:
    if not isinstance(value, Mapping):
        return False
    raw_path = value.get("path")
    expected_hash = value.get("sha256")
    expected_size = value.get("size_bytes")
    if not isinstance(raw_path, str) or not _is_sha256(expected_hash):
        return False
    path = _resolve_ref(raw_path, evidence_root)
    if not path.is_file():
        return False
    raw = path.read_bytes()
    return (
        hashlib.sha256(raw).hexdigest() == expected_hash
        and isinstance(expected_size, int)
        and expected_size == len(raw)
    )


def _subject(
    *,
    source_commit: str,
    input_hashes: Mapping[str, str],
    artifact_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "source_commit": str(source_commit).lower(),
        "input_hashes": _hash_map(input_hashes),
        "artifact_hashes": _hash_map(artifact_hashes),
    }


def _subject_valid(value: Mapping[str, Any]) -> bool:
    return (
        set(value) == {"source_commit", "input_hashes", "artifact_hashes"}
        and isinstance(value.get("source_commit"), str)
        and _GIT_COMMIT_RE.fullmatch(str(value["source_commit"])) is not None
        and bool(_hash_map(value.get("input_hashes")))
        and bool(_hash_map(value.get("artifact_hashes")))
    )


def build_operational_assurance_dimension_evidence(
    *,
    dimension: str,
    scope: str,
    realm: str,
    source_commit: str,
    input_hashes: Mapping[str, str],
    artifact_hashes: Mapping[str, str],
    status: str,
    producer_identity: str,
    verifier_identity: str,
    independence_evidence_ref: Mapping[str, Any],
    issued_at: str,
    expires_at: str,
    check_results: Sequence[Mapping[str, Any]],
    revoked_at: str | None = None,
    revocation_reason: str | None = None,
) -> dict[str, Any]:
    if dimension not in REQUIRED_DIMENSION_CHECKS:
        raise ValueError(f"unknown operational-assurance dimension: {dimension}")
    evidence: dict[str, Any] = {
        "schema_version": DIMENSION_EVIDENCE_SCHEMA_VERSION,
        "dimension": dimension,
        "scope": scope,
        "realm": realm,
        "subject": _subject(
            source_commit=source_commit,
            input_hashes=input_hashes,
            artifact_hashes=artifact_hashes,
        ),
        "status": status,
        "producer_identity": producer_identity,
        "verifier_identity": verifier_identity,
        "independent": producer_identity != verifier_identity,
        "independence_evidence_ref": dict(independence_evidence_ref),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "revoked_at": revoked_at,
        "revocation_reason": revocation_reason,
        "check_results": [dict(item) for item in check_results],
    }
    evidence["content_hash"] = canonical_sha256(evidence)
    return evidence


def _dimension_binding(
    dimension: str,
    path: Path | None,
    *,
    declared_ref: str | None,
    expected_scope: str,
    expected_realm: str,
    expected_subject: Mapping[str, Any],
    as_of: datetime | None,
    evidence_root: Path | None,
) -> dict[str, Any]:
    if path is None:
        return {
            "dimension": dimension,
            "evidence_ref": "",
            "present": False,
            "ready": False,
            "failures": ["dimension_evidence_missing"],
            "verified_check_ids": [],
        }
    raw_ref = declared_ref or str(path.resolve())
    try:
        resolved = _resolve_ref(str(path), evidence_root).resolve()
        payload = _load_json(resolved)
        raw_hash = _raw_sha256(resolved)
        size_bytes = resolved.stat().st_size
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return {
            "dimension": dimension,
            "evidence_ref": raw_ref,
            "present": False,
            "ready": False,
            "failures": ["dimension_evidence_unreadable"],
            "verified_check_ids": [],
        }

    failures: list[str] = []
    if set(payload) != _DIMENSION_FIELDS:
        failures.append("dimension_evidence_fields_invalid")
    if payload.get("schema_version") != DIMENSION_EVIDENCE_SCHEMA_VERSION:
        failures.append("dimension_evidence_schema_mismatch")
    if payload.get("dimension") != dimension:
        failures.append("dimension_identity_mismatch")
    if payload.get("scope") != expected_scope:
        failures.append("dimension_scope_mismatch")
    if payload.get("realm") != expected_realm:
        failures.append("dimension_realm_mismatch")
    evidence_subject = payload.get("subject")
    if not isinstance(evidence_subject, Mapping) or dict(evidence_subject) != dict(
        expected_subject
    ):
        failures.append("dimension_subject_mismatch")
    recorded_hash = payload.get("content_hash")
    body = dict(payload)
    body.pop("content_hash", None)
    if not _is_sha256(recorded_hash) or canonical_sha256(body) != recorded_hash:
        failures.append("dimension_content_hash_invalid")
    if payload.get("status") != "VERIFIED":
        failures.append("dimension_status_not_verified")
    producer = str(payload.get("producer_identity") or "")
    verifier = str(payload.get("verifier_identity") or "")
    if (
        not producer
        or not verifier
        or producer == verifier
        or payload.get("independent") is not True
        or not _valid_evidence_ref(
            payload.get("independence_evidence_ref"), evidence_root=evidence_root
        )
    ):
        failures.append("dimension_independence_invalid")
    issued = _parse_timestamp(payload.get("issued_at"))
    expires = _parse_timestamp(payload.get("expires_at"))
    if issued is None or expires is None or not issued < expires:
        failures.append("dimension_validity_window_invalid")
    elif as_of is not None and not (issued <= as_of < expires):
        failures.append("dimension_evidence_not_current")
    if payload.get("revoked_at") not in (None, "") or payload.get("revocation_reason") not in (
        None,
        "",
    ):
        failures.append("dimension_evidence_revoked")

    raw_checks = payload.get("check_results")
    check_ids: list[str] = []
    if not isinstance(raw_checks, list):
        failures.append("dimension_check_results_invalid")
        raw_checks = []
    for raw_check in raw_checks:
        if not isinstance(raw_check, Mapping) or set(raw_check) != _CHECK_FIELDS:
            failures.append("dimension_check_fields_invalid")
            continue
        check_id = str(raw_check.get("check_id") or "")
        if not check_id or check_id in check_ids:
            failures.append("dimension_check_identity_invalid")
            continue
        check_ids.append(check_id)
        refs = raw_check.get("evidence_refs")
        if (
            raw_check.get("outcome") != "PASS"
            or not isinstance(refs, list)
            or not refs
            or not all(_valid_evidence_ref(item, evidence_root=evidence_root) for item in refs)
        ):
            failures.append(f"dimension_check_failed:{check_id}")
        if not _valid_evidence_ref(raw_check.get("rollback_ref"), evidence_root=evidence_root):
            failures.append(f"dimension_rollback_invalid:{check_id}")
    if set(check_ids) != set(REQUIRED_DIMENSION_CHECKS[dimension]):
        failures.append("dimension_check_inventory_mismatch")

    return {
        "dimension": dimension,
        "evidence_ref": raw_ref,
        "evidence_file_sha256": raw_hash,
        "evidence_size_bytes": size_bytes,
        "schema_version": str(payload.get("schema_version") or ""),
        "status": str(payload.get("status") or ""),
        "present": True,
        "ready": not failures,
        "failures": sorted(set(failures)),
        "verified_check_ids": sorted(check_ids),
    }


def build_operational_assurance_report(
    *,
    report_id: str,
    scope: str,
    realm: str,
    source_commit: str,
    input_hashes: Mapping[str, str],
    artifact_hashes: Mapping[str, str],
    dimension_evidence_paths: Mapping[str, Path],
    producer_identity: str,
    verifier_identity: str,
    independence_evidence_ref: Mapping[str, Any],
    issued_at: str,
    expires_at: str,
    revoked_at: str | None = None,
    revocation_reason: str | None = None,
    _dimension_evidence_refs: Mapping[str, str] | None = None,
    _evidence_root: Path | None = None,
    _dimension_as_of: datetime | None = None,
) -> dict[str, Any]:
    unknown = set(dimension_evidence_paths) - set(REQUIRED_DIMENSIONS)
    if unknown:
        raise ValueError(f"unknown operational-assurance dimensions: {sorted(unknown)}")
    subject = _subject(
        source_commit=source_commit,
        input_hashes=input_hashes,
        artifact_hashes=artifact_hashes,
    )
    issued = _parse_timestamp(issued_at)
    expires = _parse_timestamp(expires_at)
    bindings = {
        dimension: _dimension_binding(
            dimension,
            dimension_evidence_paths.get(dimension),
            declared_ref=(
                _dimension_evidence_refs.get(dimension)
                if _dimension_evidence_refs is not None
                else None
            ),
            expected_scope=scope,
            expected_realm=realm,
            expected_subject=subject,
            as_of=_dimension_as_of if _dimension_as_of is not None else issued,
            evidence_root=_evidence_root,
        )
        for dimension in REQUIRED_DIMENSIONS
    }
    predicates = {
        "subject_complete": _subject_valid(subject),
        "validity_window_valid": issued is not None and expires is not None and issued < expires,
        "not_revoked_at_materialization": revoked_at in (None, "")
        and revocation_reason in (None, ""),
        "report_independence_attested": bool(producer_identity)
        and bool(verifier_identity)
        and producer_identity != verifier_identity
        and _valid_evidence_ref(independence_evidence_ref, evidence_root=_evidence_root),
        "all_required_dimensions_ready": all(
            binding["ready"] is True for binding in bindings.values()
        ),
    }
    ready = all(predicates.values())
    report: dict[str, Any] = {
        "schema_version": OPERATIONAL_ASSURANCE_SCHEMA_VERSION,
        "report_id": report_id,
        "scope": scope,
        "realm": realm,
        "subject": subject,
        "subject_sha256": canonical_sha256(subject),
        "dimension_sources": bindings,
        "producer_identity": producer_identity,
        "verifier_identity": verifier_identity,
        "independence_evidence_ref": dict(independence_evidence_ref),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "revoked_at": revoked_at,
        "revocation_reason": revocation_reason,
        "predicate_results": [
            {"predicate": name, "passed": passed} for name, passed in predicates.items()
        ],
        "decision": "READY" if ready else "DENY",
        "g8_operational_assurance_ready": ready,
        "g8_completion_claim_allowed": ready,
        "live_shadow_claim_allowed": False,
        "parent_completion_claim_allowed": False,
    }
    report["content_hash"] = canonical_sha256(report)
    return report


def _rebuild_report(
    report: Mapping[str, Any],
    *,
    evidence_root: Path | None = None,
    dimension_as_of: datetime | None = None,
) -> dict[str, Any]:
    subject = report.get("subject")
    if not isinstance(subject, Mapping):
        raise ValueError("subject must be an object")
    raw_sources = report.get("dimension_sources")
    if not isinstance(raw_sources, Mapping):
        raise ValueError("dimension_sources must be an object")
    declared_refs = {
        dimension: str(dict(raw_sources.get(dimension) or {}).get("evidence_ref") or "")
        for dimension in REQUIRED_DIMENSIONS
    }
    paths = {
        dimension: _resolve_ref(reference, evidence_root)
        for dimension, reference in declared_refs.items()
        if reference
    }
    independence = report.get("independence_evidence_ref")
    if not isinstance(independence, Mapping):
        raise ValueError("independence_evidence_ref must be an object")
    return build_operational_assurance_report(
        report_id=str(report.get("report_id") or ""),
        scope=str(report.get("scope") or ""),
        realm=str(report.get("realm") or ""),
        source_commit=str(subject.get("source_commit") or ""),
        input_hashes=dict(subject.get("input_hashes") or {}),
        artifact_hashes=dict(subject.get("artifact_hashes") or {}),
        dimension_evidence_paths=paths,
        producer_identity=str(report.get("producer_identity") or ""),
        verifier_identity=str(report.get("verifier_identity") or ""),
        independence_evidence_ref=dict(independence),
        issued_at=str(report.get("issued_at") or ""),
        expires_at=str(report.get("expires_at") or ""),
        revoked_at=report.get("revoked_at"),
        revocation_reason=report.get("revocation_reason"),
        _dimension_evidence_refs=declared_refs,
        _evidence_root=evidence_root,
        _dimension_as_of=dimension_as_of,
    )


def verify_operational_assurance_report(
    report: Mapping[str, Any],
    *,
    expected_scope: str,
    expected_realm: str,
    expected_source_commit: str,
    as_of: datetime | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    if report.get("schema_version") != OPERATIONAL_ASSURANCE_SCHEMA_VERSION:
        reasons.append("schema_version_mismatch")
    recorded_hash = report.get("content_hash")
    body = dict(report)
    body.pop("content_hash", None)
    if not _is_sha256(recorded_hash) or canonical_sha256(body) != recorded_hash:
        reasons.append("content_hash_invalid")
    try:
        rebuilt = _rebuild_report(report, evidence_root=evidence_root)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        rebuilt = {}
        reasons.append(f"replay_failed:{type(exc).__name__}")
    if rebuilt != dict(report):
        reasons.append("report_does_not_replay_exactly")
    if report.get("decision") == "READY":
        try:
            current_rebuild = _rebuild_report(
                report,
                evidence_root=evidence_root,
                dimension_as_of=now,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            reasons.append(f"dimension_revalidation_failed:{type(exc).__name__}")
        else:
            current_sources = current_rebuild.get("dimension_sources", {})
            for dimension in REQUIRED_DIMENSIONS:
                source = dict(current_sources.get(dimension) or {})
                if source.get("ready") is True:
                    continue
                failures = source.get("failures")
                if not isinstance(failures, list) or not failures:
                    failures = ["unknown_failure"]
                reasons.extend(
                    f"dimension_revalidation_failed:{dimension}:{failure}" for failure in failures
                )
    if report.get("scope") != expected_scope:
        reasons.append("scope_mismatch")
    if report.get("realm") != expected_realm:
        reasons.append("realm_mismatch")
    subject = report.get("subject")
    subject_map = dict(subject) if isinstance(subject, Mapping) else {}
    if (
        not isinstance(subject, Mapping)
        or subject.get("source_commit") != expected_source_commit.lower()
    ):
        reasons.append("source_commit_mismatch")
    issued = _parse_timestamp(report.get("issued_at"))
    expires = _parse_timestamp(report.get("expires_at"))
    if issued is None or expires is None or not (issued <= now < expires):
        reasons.append("operational_assurance_not_current")
    if report.get("revoked_at") not in (None, "") or report.get("revocation_reason") not in (
        None,
        "",
    ):
        reasons.append("operational_assurance_revoked")
    integrity_ok = not reasons
    ready = (
        integrity_ok
        and report.get("decision") == "READY"
        and report.get("g8_operational_assurance_ready") is True
        and report.get("g8_completion_claim_allowed") is True
        and report.get("live_shadow_claim_allowed") is False
        and report.get("parent_completion_claim_allowed") is False
    )
    if integrity_ok and not ready:
        reasons.append("report_decision_deny")
    return {
        "schema_version": OPERATIONAL_ASSURANCE_VERIFICATION_SCHEMA_VERSION,
        "ok": integrity_ok,
        "ready": ready,
        "decision": str(report.get("decision") or "DENY"),
        "report_id": str(report.get("report_id") or ""),
        "scope": str(report.get("scope") or ""),
        "realm": str(report.get("realm") or ""),
        "source_commit": str(subject_map.get("source_commit") or ""),
        "content_hash": str(recorded_hash or ""),
        "expires_at": str(report.get("expires_at") or ""),
        "live_shadow_claim_allowed": False,
        "parent_completion_claim_allowed": False,
        "reasons": sorted(set(reasons)),
    }


def verify_operational_assurance_file(
    report_path: Path,
    *,
    expected_file_sha256: str,
    expected_scope: str,
    expected_realm: str,
    expected_source_commit: str,
    as_of: datetime | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    resolved = report_path.resolve()
    try:
        actual_hash = _raw_sha256(resolved)
        report = _load_json(resolved)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return {
            "schema_version": OPERATIONAL_ASSURANCE_VERIFICATION_SCHEMA_VERSION,
            "ok": False,
            "ready": False,
            "decision": "DENY",
            "report_id": "",
            "scope": "",
            "realm": "",
            "source_commit": "",
            "content_hash": "",
            "expires_at": "",
            "live_shadow_claim_allowed": False,
            "parent_completion_claim_allowed": False,
            "report_ref": str(resolved),
            "report_file_sha256": "",
            "reasons": [f"report_unreadable:{type(exc).__name__}"],
        }
    verification = verify_operational_assurance_report(
        report,
        expected_scope=expected_scope,
        expected_realm=expected_realm,
        expected_source_commit=expected_source_commit,
        as_of=as_of,
        evidence_root=evidence_root,
    )
    reasons = list(verification["reasons"])
    if not _is_sha256(expected_file_sha256) or actual_hash != expected_file_sha256:
        reasons.append("report_file_sha256_mismatch")
    file_ok = "report_file_sha256_mismatch" not in reasons
    return {
        **verification,
        "ok": verification["ok"] and file_ok,
        "ready": verification["ready"] and file_ok,
        "report_ref": str(resolved),
        "report_file_sha256": actual_hash,
        "reasons": sorted(set(reasons)),
    }
