"""Single fail-closed consumer for formal autonomous-domain research admission.

The report is a deterministic materialization of Foundation plus G0-G5.  It is
not a mutable flag: verification re-reads every source by exact file hash,
rebuilds all predicates, and then applies the current expiry/revocation window.
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

DOMAIN_ADMISSION_SCHEMA_VERSION = "xinao.domain_research_admission_report.v1"
DOMAIN_ADMISSION_VERIFICATION_SCHEMA_VERSION = "xinao.domain_research_admission_verification.v1"
REQUIRED_SOURCE_IDS = ("FOUNDATION", "G0", "G1", "G2", "G3", "G4", "G5")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _embedded_content_identity(report: Mapping[str, Any]) -> tuple[str, str, bool]:
    for field in ("content_hash", "artifact_hash", "content_sha256"):
        recorded = report.get(field)
        if not _is_sha256(recorded):
            continue
        body = dict(report)
        body.pop(field, None)
        return field, str(recorded), canonical_sha256(body) == recorded
    return "raw_file_sha256", "", True


def _source_ready(source_id: str, report: Mapping[str, Any]) -> tuple[bool, list[str]]:
    schema = report.get("schema_version")
    checks: dict[str, bool]
    if source_id == "FOUNDATION":
        checks = {
            "schema": schema == "xinao.foundation_closure_report.v2",
            "verified": report.get("status") == "VERIFIED",
            "execution_ready": report.get("foundation_execution_ready") is True,
            "not_global_closure": report.get("foundation_closed") is False,
            "formal_still_closed": report.get("formal_research_allowed") is False,
            "legacy_gate_unused": report.get("legacy_a_g_gate_used") is False,
            "manual_override_unused": report.get("manual_override_used") is False,
        }
    elif source_id == "G0":
        checks = {
            "schema": schema == "xinao.foundation.g0.owner_acceptance.v1",
            "authority": report.get("authority") is True,
            "owner_adopted": report.get("owner_adopted") is True,
            "closed": report.get("g0_closed") is True,
            "formula_eligible": report.get("closed_for_admission_formula") is True,
            "formal_still_closed": report.get("formal_open") is False,
        }
    elif source_id == "G1":
        checks = {
            "schema": schema == "xinao.measurement_readiness_report.v1",
            "authority": report.get("authority") is True,
            "closed": report.get("g1_closed") is True,
            "formula_eligible": report.get("closed_for_admission_formula") is True,
            "effect_verified": report.get("effect_verified") is True,
            "decision": report.get("decision") == "G1_MEASUREMENT_READY_VERIFIED",
        }
    elif source_id == "G2":
        checks = {
            "schema": schema == "xinao.g2.v23.current_v3_cas.postcas_owner_acceptance.v1",
            "authority": report.get("authority") is True,
            "authority_applied": report.get("authority_applied") is True,
            "effect_verified": report.get("effect_verified") is True,
            "closure_authorized": report.get("g2_closure_authorized") is True,
            "claim_closed": report.get("claim_status") == "closed",
            "verdict": report.get("verdict") == "ACCEPT",
        }
    elif source_id == "G3":
        checks = {
            "schema": schema == "xinao.foundation.g3.final_pin.owner_acceptance.v1",
            "authority": report.get("authority") is True,
            "owner_adopted": report.get("owner_adopted") is True,
            "effect_verified": report.get("effect_verified") is True,
            "closed": report.get("g3_closed") is True,
            "verdict": report.get("verdict") == "ADOPT",
        }
    elif source_id == "G4":
        checks = {
            "final_schema": schema == "xinao.end_to_end_autonomous_research_capability_report.v1",
            "authority": report.get("authority") is True,
            "full": report.get("g4_full") is True,
            "closed": report.get("g4_closed") is True,
            "completion_claim": report.get("completion_claim_allowed") is True,
            "decision": report.get("decision") == "G4_DISCOVERY_CAPABILITY_PROVED",
        }
    elif source_id == "G5":
        checks = {
            "final_schema": schema == "xinao.statistical_validity_report.v1",
            "authority": report.get("authority") is True,
            "ready": report.get("g5_statistical_validity_ready") is True,
            "closed": report.get("g5_closed") is True,
            "completion_claim": report.get("completion_claim_allowed") is True,
            "decision": report.get("decision") == "G5_STATISTICAL_VALIDITY_READY",
        }
    else:  # pragma: no cover - callers enforce the exact source inventory.
        return False, ["unknown_source_id"]
    failed = [name for name, passed in checks.items() if not passed]
    return not failed, failed


def _source_binding(
    source_id: str,
    path: Path,
    *,
    declared_ref: str | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    resolved = _resolve_ref(str(path), evidence_root).resolve()
    report = _load_json(resolved)
    content_field, content_hash, embedded_hash_valid = _embedded_content_identity(report)
    raw_hash = _raw_sha256(resolved)
    if not content_hash:
        content_hash = raw_hash
    ready, failed = _source_ready(source_id, report)
    return {
        "source_id": source_id,
        "report_ref": declared_ref or str(resolved),
        "report_sha256": raw_hash,
        "report_size_bytes": resolved.stat().st_size,
        "schema_version": str(report.get("schema_version") or ""),
        "scope": str(report.get("scope") or report.get("canonical_scope") or ""),
        "realm": str(report.get("realm") or ""),
        "input_hashes": _hash_map(report.get("input_hashes")),
        "content_hash_field": content_field,
        "report_content_hash": content_hash,
        "embedded_content_hash_valid": embedded_hash_valid,
        "ready_for_admission_formula": ready,
        "readiness_failures": failed,
    }


def _independence_valid(
    identities: Sequence[str],
    attestations: Sequence[Mapping[str, Any]],
    *,
    evidence_root: Path | None = None,
) -> bool:
    unique = {item for item in identities if isinstance(item, str) and item}
    if len(unique) != len(identities) or len(unique) < 2 or not attestations:
        return False
    for attestation in attestations:
        producer = attestation.get("producer_identity")
        verifier = attestation.get("verifier_identity")
        refs = attestation.get("evidence_refs")
        if (
            producer not in unique
            or verifier not in unique
            or producer == verifier
            or attestation.get("independent") is not True
            or not isinstance(refs, list)
            or not refs
            or not all(_valid_evidence_ref(item, evidence_root=evidence_root) for item in refs)
        ):
            return False
    return True


def _materialization_receipt_valid(
    value: Mapping[str, Any],
    *,
    source_bundle_hash: str,
    materialization_subject_hash: str,
    evidence_root: Path | None = None,
) -> bool:
    if not _valid_evidence_ref(value, evidence_root=evidence_root):
        return False
    try:
        receipt = _load_json(_resolve_ref(str(value["path"]), evidence_root))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError):
        return False
    recorded = receipt.get("content_hash")
    body = dict(receipt)
    body.pop("content_hash", None)
    return bool(
        receipt.get("schema_version")
        == "xinao.domain_research_admission_materialization_receipt.v1"
        and _is_sha256(recorded)
        and canonical_sha256(body) == recorded
        and receipt.get("source_bundle_hash") == source_bundle_hash
        and receipt.get("materialization_subject_hash") == materialization_subject_hash
        and isinstance(receipt.get("transaction_id"), str)
        and receipt.get("transaction_id")
        and isinstance(receipt.get("event_id"), str)
        and receipt.get("event_id")
        and isinstance(receipt.get("outbox_id"), str)
        and receipt.get("outbox_id")
        and receipt.get("same_transaction") is True
        and receipt.get("event_persisted") is True
        and receipt.get("outbox_persisted") is True
        and receipt.get("idempotent_replay") is True
        and receipt.get("compensation_status") in {"NOT_REQUIRED", "COMPLETED"}
    )


def _predicate_results(
    *,
    scope: str,
    realm: str,
    sources: Mapping[str, Mapping[str, Any]],
    issued_at: str,
    expires_at: str,
    revoked_at: str | None,
    revocation_reason: str | None,
    identities: Sequence[str],
    attestations: Sequence[Mapping[str, Any]],
    negative_test_refs: Sequence[Mapping[str, Any]],
    replay_ref: Mapping[str, Any],
    materialization_receipt_ref: Mapping[str, Any],
    source_bundle_hash: str,
    materialization_subject_hash: str,
    evidence_root: Path | None = None,
) -> list[dict[str, Any]]:
    issued = _parse_timestamp(issued_at)
    expires = _parse_timestamp(expires_at)
    source_hash_maps = [dict(value.get("input_hashes") or {}) for value in sources.values()]
    common_inputs = (
        bool(source_hash_maps)
        and bool(source_hash_maps[0])
        and all(item == source_hash_maps[0] for item in source_hash_maps[1:])
    )
    values = {
        "source_inventory_exact": set(sources) == set(REQUIRED_SOURCE_IDS),
        "source_file_hashes_bound": all(
            _is_sha256(value.get("report_sha256")) for value in sources.values()
        ),
        "source_embedded_hashes_valid": all(
            value.get("embedded_content_hash_valid") is True for value in sources.values()
        ),
        "source_scopes_exact": bool(scope)
        and all(value.get("scope") == scope for value in sources.values()),
        "source_realms_exact": bool(realm)
        and all(value.get("realm") == realm for value in sources.values()),
        "source_input_hashes_exact": common_inputs,
        "foundation_and_g0_g5_ready": all(
            value.get("ready_for_admission_formula") is True for value in sources.values()
        ),
        "issuance_window_structurally_valid": issued is not None
        and expires is not None
        and issued < expires,
        "not_revoked_at_materialization": revoked_at in (None, "")
        and revocation_reason in (None, ""),
        "independence_attested": _independence_valid(
            identities, attestations, evidence_root=evidence_root
        ),
        "negative_tests_bound": bool(negative_test_refs)
        and all(
            _valid_evidence_ref(item, evidence_root=evidence_root) for item in negative_test_refs
        ),
        "replay_bound": _valid_evidence_ref(replay_ref, evidence_root=evidence_root),
        "transactional_materialization_bound": _materialization_receipt_valid(
            materialization_receipt_ref,
            source_bundle_hash=source_bundle_hash,
            materialization_subject_hash=materialization_subject_hash,
            evidence_root=evidence_root,
        ),
    }
    return [{"predicate": name, "passed": passed} for name, passed in values.items()]


def build_domain_research_admission_report(
    *,
    report_id: str,
    scope: str,
    realm: str,
    source_report_paths: Mapping[str, Path],
    report_model_tool_identities: Sequence[str],
    independence_attestations: Sequence[Mapping[str, Any]],
    issued_at: str,
    expires_at: str,
    negative_test_refs: Sequence[Mapping[str, Any]],
    replay_ref: Mapping[str, Any],
    materialization_receipt_ref: Mapping[str, Any] | None = None,
    revoked_at: str | None = None,
    revocation_reason: str | None = None,
    _source_report_refs: Mapping[str, str] | None = None,
    _evidence_root: Path | None = None,
) -> dict[str, Any]:
    if set(source_report_paths) != set(REQUIRED_SOURCE_IDS):
        raise ValueError("source report inventory must be exact Foundation plus G0-G5")
    sources = {
        source_id: _source_binding(
            source_id,
            source_report_paths[source_id],
            declared_ref=(
                _source_report_refs[source_id] if _source_report_refs is not None else None
            ),
            evidence_root=_evidence_root,
        )
        for source_id in REQUIRED_SOURCE_IDS
    }
    identities = [str(item) for item in report_model_tool_identities]
    attestations = [dict(item) for item in independence_attestations]
    negatives = [dict(item) for item in negative_test_refs]
    replay = dict(replay_ref)
    materialization = dict(materialization_receipt_ref or {})
    source_bundle_hash = canonical_sha256(
        {"scope": scope, "realm": realm, "source_reports": sources}
    )
    materialization_subject_hash = canonical_sha256(
        {
            "report_id": report_id,
            "scope": scope,
            "realm": realm,
            "source_reports": sources,
            "report_model_tool_identities": identities,
            "independence_attestations": attestations,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_at": revoked_at,
            "revocation_reason": revocation_reason,
            "negative_test_refs": negatives,
            "replay_ref": replay,
        }
    )
    predicates = _predicate_results(
        scope=scope,
        realm=realm,
        sources=sources,
        issued_at=issued_at,
        expires_at=expires_at,
        revoked_at=revoked_at,
        revocation_reason=revocation_reason,
        identities=identities,
        attestations=attestations,
        negative_test_refs=negatives,
        replay_ref=replay,
        materialization_receipt_ref=materialization,
        source_bundle_hash=source_bundle_hash,
        materialization_subject_hash=materialization_subject_hash,
        evidence_root=_evidence_root,
    )
    allowed = all(item["passed"] for item in predicates)
    common_inputs = dict(sources["FOUNDATION"]["input_hashes"])
    report: dict[str, Any] = {
        "schema_version": DOMAIN_ADMISSION_SCHEMA_VERSION,
        "report_id": report_id,
        "scope": scope,
        "realm": realm,
        "foundation_report_ref": sources["FOUNDATION"]["report_ref"],
        "foundation_report_hash": sources["FOUNDATION"]["report_sha256"],
        "foundation_input_hashes": common_inputs,
        "g0_ref": sources["G0"]["report_ref"],
        "g0_hash": sources["G0"]["report_sha256"],
        "g1_ref": sources["G1"]["report_ref"],
        "g1_hash": sources["G1"]["report_sha256"],
        "g2_ref": sources["G2"]["report_ref"],
        "g2_hash": sources["G2"]["report_sha256"],
        "g3_ref": sources["G3"]["report_ref"],
        "g3_hash": sources["G3"]["report_sha256"],
        "g4_ref": sources["G4"]["report_ref"],
        "g4_hash": sources["G4"]["report_sha256"],
        "g5_ref": sources["G5"]["report_ref"],
        "g5_hash": sources["G5"]["report_sha256"],
        "source_reports": sources,
        "source_bundle_hash": source_bundle_hash,
        "materialization_subject_hash": materialization_subject_hash,
        "report_model_tool_identities": identities,
        "independence_attestations": attestations,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "revoked_at": revoked_at,
        "revocation_reason": revocation_reason,
        "predicate_results": predicates,
        "negative_test_refs": negatives,
        "replay_ref": replay,
        "materialization_receipt_ref": materialization,
        "decision": "ALLOW" if allowed else "DENY",
        "formal_autonomous_domain_research_allowed": allowed,
    }
    report["content_hash"] = canonical_sha256(report)
    return report


def _rebuild_report(
    report: Mapping[str, Any], *, evidence_root: Path | None = None
) -> dict[str, Any]:
    sources = report.get("source_reports")
    if not isinstance(sources, Mapping):
        raise ValueError("source_reports must be an object")
    source_refs = {
        source_id: str(dict(sources.get(source_id) or {}).get("report_ref") or "")
        for source_id in REQUIRED_SOURCE_IDS
    }
    source_paths = {
        source_id: _resolve_ref(source_refs[source_id], evidence_root)
        for source_id in REQUIRED_SOURCE_IDS
    }
    return build_domain_research_admission_report(
        report_id=str(report.get("report_id") or ""),
        scope=str(report.get("scope") or ""),
        realm=str(report.get("realm") or ""),
        source_report_paths=source_paths,
        report_model_tool_identities=list(report.get("report_model_tool_identities") or []),
        independence_attestations=list(report.get("independence_attestations") or []),
        issued_at=str(report.get("issued_at") or ""),
        expires_at=str(report.get("expires_at") or ""),
        revoked_at=report.get("revoked_at"),
        revocation_reason=report.get("revocation_reason"),
        negative_test_refs=list(report.get("negative_test_refs") or []),
        replay_ref=dict(report.get("replay_ref") or {}),
        materialization_receipt_ref=dict(report.get("materialization_receipt_ref") or {}),
        _source_report_refs=source_refs,
        _evidence_root=evidence_root,
    )


def verify_domain_research_admission_report(
    report: Mapping[str, Any],
    *,
    expected_scope: str,
    expected_realm: str,
    as_of: datetime | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if report.get("schema_version") != DOMAIN_ADMISSION_SCHEMA_VERSION:
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
    if report.get("scope") != expected_scope:
        reasons.append("scope_mismatch")
    if report.get("realm") != expected_realm:
        reasons.append("realm_mismatch")
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    issued = _parse_timestamp(report.get("issued_at"))
    expires = _parse_timestamp(report.get("expires_at"))
    if issued is None or expires is None or not (issued <= now < expires):
        reasons.append("admission_not_current")
    if report.get("revoked_at") not in (None, "") or report.get("revocation_reason") not in (
        None,
        "",
    ):
        reasons.append("admission_revoked")
    integrity_ok = not reasons
    allowed = (
        integrity_ok
        and report.get("decision") == "ALLOW"
        and report.get("formal_autonomous_domain_research_allowed") is True
    )
    if integrity_ok and not allowed:
        reasons.append("report_decision_deny")
    return {
        "schema_version": DOMAIN_ADMISSION_VERIFICATION_SCHEMA_VERSION,
        "ok": integrity_ok,
        "allowed": allowed,
        "decision": str(report.get("decision") or "DENY"),
        "report_id": str(report.get("report_id") or ""),
        "scope": str(report.get("scope") or ""),
        "realm": str(report.get("realm") or ""),
        "content_hash": str(recorded_hash or ""),
        "expires_at": str(report.get("expires_at") or ""),
        "reasons": sorted(set(reasons)),
    }


def verify_domain_research_admission_file(
    report_path: Path,
    *,
    expected_file_sha256: str,
    expected_scope: str,
    expected_realm: str,
    as_of: datetime | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    resolved = report_path.resolve()
    try:
        actual_hash = _raw_sha256(resolved)
        report = _load_json(resolved)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return {
            "schema_version": DOMAIN_ADMISSION_VERIFICATION_SCHEMA_VERSION,
            "ok": False,
            "allowed": False,
            "decision": "DENY",
            "report_id": "",
            "scope": "",
            "realm": "",
            "content_hash": "",
            "expires_at": "",
            "report_ref": str(resolved),
            "report_file_sha256": "",
            "reasons": [f"report_unreadable:{type(exc).__name__}"],
        }
    verification = verify_domain_research_admission_report(
        report,
        expected_scope=expected_scope,
        expected_realm=expected_realm,
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
        "allowed": verification["allowed"] and file_ok,
        "report_ref": str(resolved),
        "report_file_sha256": actual_hash,
        "reasons": sorted(set(reasons)),
    }
