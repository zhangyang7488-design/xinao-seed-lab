"""ResearchEpisode sealed export -> wild candidate pool adapter.

Multi-turn OPEN_RESEARCH path. Does not weaken the one-shot
``researcher_result_adapter`` (provider_num_turns==1 remains enforced there).

Ingest mints a not-projected PolicyCandidateVersion and a CandidatePoolEntry
with owner_adopted=false. Owner disposition remains a separate artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.candidate_pool import (
    CandidatePoolError,
    _write_new_bytes,
    _write_new_json,
    load_pool_entry,
    pool_entry_path,
    pool_receipt_path,
    pool_result_bytes_path,
    verify_pool_entry_seal,
)
from xinao.science.portfolio import DecisionSignature, PolicyCandidateVersion, PolicyRole
from xinao.science.research_episode_candidate_manifest import (
    CANDIDATE_MANIFEST_MARKER as PACKAGE_MANIFEST_MARKER,
)
from xinao.science.research_episode_candidate_manifest import (
    CANDIDATE_MANIFEST_SCHEMA as PACKAGE_MANIFEST_SCHEMA,
)
from xinao.science.research_episode_candidate_manifest import (
    CandidateManifestError,
    validate_candidate_manifest,
)

EXPORT_SCHEMA: Final = "xinao.research_episode_candidate_evidence_bundle.v1"
MANIFEST_SCHEMA: Final = PACKAGE_MANIFEST_SCHEMA
MANIFEST_MARKER: Final = PACKAGE_MANIFEST_MARKER
ADAPTER_BINDING_KIND: Final = "XINAO_EPISODE_EXPORT_POOL_ADAPTER_V1"
ADAPTER_MARKER: Final = "XINAO_EPISODE_EXPORT_POOL_CANDIDATE_V1"
INGEST_KIND: Final = "EPISODE_EXPORT_MANIFEST"
ACCOUNT_RECOMMENDATIONS: Final = frozenset(
    {"ACTION_CANDIDATE", "NO_ACTION_CANDIDATE", "NO_RECOMMENDATION"}
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EpisodeExportAdapterError(ValueError):
    """Fail-closed episode export pool rejection."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def raw_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_hex64(value: object, reason: str, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise EpisodeExportAdapterError(reason, f"{label} must be lowercase sha256")
    return value


def _require_text(value: object, reason: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpisodeExportAdapterError(reason, f"{label} required")
    return value.strip()


def _parse_aware(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EpisodeExportAdapterError("EPISODE_EXPORT_CUTOFF_INVALID", label)
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EpisodeExportAdapterError("EPISODE_EXPORT_CUTOFF_INVALID", label) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EpisodeExportAdapterError("EPISODE_EXPORT_CUTOFF_INVALID", f"{label} aware required")
    return parsed.astimezone(UTC)


def verify_episode_export_bundle(
    export: Mapping[str, Any] | bytes,
) -> dict[str, Any]:
    """Verify sealed multi-turn episode export bindings (no num_turns==1 assumption)."""
    if isinstance(export, (bytes, bytearray)):
        try:
            obj = json.loads(bytes(export).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EpisodeExportAdapterError("EPISODE_EXPORT_JSON_INVALID", str(exc)) from exc
    else:
        obj = dict(export)
    if not isinstance(obj, Mapping):
        raise EpisodeExportAdapterError("EPISODE_EXPORT_JSON_INVALID", "object required")
    if obj.get("schema_version") != EXPORT_SCHEMA:
        raise EpisodeExportAdapterError(
            "EPISODE_EXPORT_SCHEMA_INVALID",
            str(obj.get("schema_version")),
        )
    for key in (
        "episode_id",
        "attempt_cas_digest",
        "attempt_hash",
        "raw_session_hash",
        "tool_trace_hash",
        "artifact_manifest_hash",
        "candidate_manifest_sha256",
        "pair_receipt_sha256",
        "provider_session_uuid",
        "research_profile",
    ):
        if not obj.get(key):
            raise EpisodeExportAdapterError("EPISODE_EXPORT_FIELD_MISSING", key)
    for key in (
        "attempt_cas_digest",
        "attempt_hash",
        "raw_session_hash",
        "tool_trace_hash",
        "artifact_manifest_hash",
        "candidate_manifest_sha256",
        "pair_receipt_sha256",
    ):
        _require_hex64(obj.get(key), "EPISODE_EXPORT_HASH_INVALID", key)
    # Multi-turn allowed; reject only missing/invalid turns, never force ==1.
    actual_turns = obj.get("actual_turns")
    if actual_turns is not None and (
        type(actual_turns) is not int or isinstance(actual_turns, bool) or actual_turns < 1
    ):
        raise EpisodeExportAdapterError("EPISODE_EXPORT_TURNS_INVALID", str(actual_turns))
    for bad in (
        "owner_adopted",
        "science_restored",
        "parent_complete",
        "completion_claim_allowed",
        "disposition_written",
        "freeze_written",
        "settlement_written",
        "shadow_write",
        "next_task_created",
        "portfolio_updated",
    ):
        if obj.get(bad) is True:
            raise EpisodeExportAdapterError("EPISODE_EXPORT_AUTHORITY_CLAIM", bad)
    if obj.get("candidate_only") is not True:
        raise EpisodeExportAdapterError("EPISODE_EXPORT_CANDIDATE_ONLY_REQUIRED", "candidate_only")
    body = {k: v for k, v in obj.items() if k != "bundle_sha256"}
    # Prefer export's own sealed hash when present.
    claimed = obj.get("bundle_sha256")
    if claimed is not None:
        # Recompute from body using the same canonical style as native export when possible.
        # Accept either content-hash style; if mismatch, fail closed.
        recomputed = hashlib.sha256(
            (
                json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        ).hexdigest()
        alt: str | None = None
        if claimed != recomputed:
            try:
                alt = canonical_sha256(body)
            except (TypeError, ValueError):
                # Native exports bind opaque host provenance (for example
                # Windows st_dev/st_ino/st_mtime_ns) with sorted JSON bytes.
                # Those integers may be outside RFC 8785's float-safe domain;
                # that must not invalidate an already matching native seal.
                alt = None
        if claimed not in {recomputed, alt}:
            raise EpisodeExportAdapterError(
                "EPISODE_EXPORT_BUNDLE_HASH_MISMATCH",
                f"claimed={claimed}",
            )
    return dict(obj)


def load_and_verify_candidate_manifest(
    *,
    export: Mapping[str, Any],
    manifest_bytes: bytes,
) -> dict[str, Any]:
    """Exact sha match of lab manifest bytes against export pin; closed schema.

    Schema/cutoff/method/falsifier/authority rules are the package-owned
    ``research_episode_candidate_manifest.validate_candidate_manifest`` (same
    source bytes as image COPY / native re-export; no monorepo docker walk).
    """
    if not isinstance(manifest_bytes, (bytes, bytearray)) or not manifest_bytes:
        raise EpisodeExportAdapterError("CANDIDATE_MANIFEST_MISSING", "bytes required")
    raw = bytes(manifest_bytes)
    observed = raw_sha256(raw)
    expected = _require_hex64(
        export.get("candidate_manifest_sha256"),
        "EPISODE_EXPORT_HASH_INVALID",
        "candidate_manifest_sha256",
    )
    if observed != expected:
        raise EpisodeExportAdapterError(
            "CANDIDATE_MANIFEST_HASH_MISMATCH",
            f"export={expected} bytes={observed}",
        )
    try:
        obj = validate_candidate_manifest(
            raw,
            expected_episode_id=(
                str(export.get("episode_id")) if export.get("episode_id") else None
            ),
            expected_attempt_cas_digest=(
                str(export.get("attempt_cas_digest")) if export.get("attempt_cas_digest") else None
            ),
        )
    except CandidateManifestError as exc:
        raise EpisodeExportAdapterError(exc.reason_code, str(exc.detail)[:2000]) from exc
    except Exception as exc:
        reason = getattr(exc, "reason_code", None) or "CANDIDATE_MANIFEST_INVALID"
        detail = getattr(exc, "detail", None) or str(exc)
        raise EpisodeExportAdapterError(str(reason), str(detail)[:2000]) from exc
    if not isinstance(obj, Mapping):
        raise EpisodeExportAdapterError("CANDIDATE_MANIFEST_JSON_INVALID", "object required")
    # Keep pool-side marker constants aligned with package seals.
    if obj.get("schema_version") != MANIFEST_SCHEMA:
        raise EpisodeExportAdapterError(
            "CANDIDATE_MANIFEST_SCHEMA_INVALID",
            str(obj.get("schema_version")),
        )
    if obj.get("manifest_marker") != MANIFEST_MARKER:
        raise EpisodeExportAdapterError(
            "CANDIDATE_MANIFEST_MARKER_INVALID",
            str(obj.get("manifest_marker")),
        )
    return dict(obj)


def mint_policy_candidate_from_episode_export(
    *,
    export: Mapping[str, Any],
    manifest: Mapping[str, Any],
    export_bytes_sha256: str,
    manifest_bytes_sha256: str,
) -> PolicyCandidateVersion:
    """Mint not-projected PolicyCandidateVersion without one-shot turn assumptions."""
    export_sha = _require_hex64(export_bytes_sha256, "EPISODE_EXPORT_HASH_INVALID", "export")
    manifest_sha = _require_hex64(
        manifest_bytes_sha256, "CANDIDATE_MANIFEST_HASH_INVALID", "manifest"
    )
    cutoff_obj = (
        manifest.get("data_cutoff") if isinstance(manifest.get("data_cutoff"), Mapping) else {}
    )
    as_of = cutoff_obj.get("as_of") or manifest.get("as_of")
    knowledge_cutoff = _parse_aware(as_of, "data_cutoff.as_of")
    family = _require_text(
        manifest.get("candidate_id") or manifest.get("family_id"),
        "CANDIDATE_MANIFEST_FIELD_INVALID",
        "candidate_id",
    )
    version = _require_text(
        manifest.get("candidate_version") or "v1",
        "CANDIDATE_MANIFEST_FIELD_INVALID",
        "candidate_version",
    )
    decision_map_ref = f"xinao.not_projected.episode_candidate.v1:{export_sha}"
    policy_ref = f"science.research_episode_export.v1.sha256:{export_sha}"
    probe_trace_hash = canonical_sha256(
        [
            ADAPTER_BINDING_KIND,
            export_sha,
            manifest_sha,
            str(export.get("attempt_cas_digest")),
            str(export.get("provider_session_uuid")),
        ]
    )
    semantic_config = {
        "binding_kind": ADAPTER_BINDING_KIND,
        "adapter_marker": ADAPTER_MARKER,
        "ingest_kind": INGEST_KIND,
        "export_schema": EXPORT_SCHEMA,
        "manifest_schema": MANIFEST_SCHEMA,
        "export_sha256": export_sha,
        "manifest_sha256": manifest_sha,
        "episode_id": export.get("episode_id"),
        "attempt_hash": export.get("attempt_hash"),
        "attempt_cas_digest": export.get("attempt_cas_digest"),
        "cas_head_sha256": export.get("cas_head_sha256"),
        "host_session_id": export.get("host_session_id"),
        "provider_session_uuid": export.get("provider_session_uuid"),
        "research_profile": export.get("research_profile"),
        "actual_turns": export.get("actual_turns"),
        "namespace_receipt_sha256": export.get("namespace_receipt_sha256"),
        "release_identity_sha256": export.get("release_identity_sha256"),
        "tool_trace_hash": export.get("tool_trace_hash"),
        "pair_receipt_sha256": export.get("pair_receipt_sha256"),
        "account_recommendation": manifest.get("account_recommendation"),
        "decision_map_projected": False,
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "candidate_version": version,
        "research_question_sha256": canonical_sha256(str(manifest.get("research_question") or "")),
    }
    return PolicyCandidateVersion(
        policy_ref=policy_ref,
        family_id=f"research-episode.v1:{family}",
        role=PolicyRole.SUBSTANTIVE,
        knowledge_cutoff=knowledge_cutoff,
        decision_signature=DecisionSignature(
            mechanism="RESEARCH_EPISODE_EXPORT_BOUND_NOT_PROJECTED",
            feature_visibility=("research_episode_export_identity",),
            time_scale="RESEARCH_ONLY_NOT_PROJECTED",
            update_policy="IMMUTABLE_EPISODE_EXPORT_BINDING",
            abstention_rule="NO_ACTION_MAP_UNTIL_OWNER_DISPOSITION",
            action_support="NOT_PROJECTED",
            decision_map_ref=decision_map_ref,
            probe_target_count=1,
            probe_action_count=1,
            probe_trace_hash=probe_trace_hash,
        ),
        semantic_config=semantic_config,
    ).with_content_hash()


def _build_episode_pool_entry(
    *,
    export: Mapping[str, Any],
    manifest: Mapping[str, Any],
    policy: PolicyCandidateVersion,
    export_sha256: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    if policy.content_hash is None:
        raise EpisodeExportAdapterError("EPISODE_POLICY_UNSEALED", "content_hash required")
    body: dict[str, Any] = {
        "schema_version": "xinao.research_candidate_pool_entry.v1",
        "pool_marker": "XINAO_RESEARCH_CANDIDATE_POOL_V1",
        "ingest_kind": INGEST_KIND,
        "result_sha256": export_sha256,
        "receipt_content_sha256": manifest_sha256,
        "receipt_raw_sha256": manifest_sha256,
        "export_bundle_sha256": export_sha256,
        "candidate_manifest_sha256": manifest_sha256,
        "run_id": str(export.get("attempt_id") or export.get("attempt_cas_digest")),
        "status": "CANDIDATE_READY",
        "knowledge_cutoff": policy.knowledge_cutoff.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "policy_ref": policy.policy_ref,
        "policy_content_hash": policy.content_hash,
        "decision_map_ref": policy.decision_signature.decision_map_ref,
        "decision_map_projected": False,
        "action_support": "NOT_PROJECTED",
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "candidate": {
            "schema_version": MANIFEST_SCHEMA,
            "candidate_id": manifest.get("candidate_id"),
            "candidate_version": manifest.get("candidate_version"),
            "research_question": manifest.get("research_question"),
            "research_object": manifest.get("research_object"),
            "account_recommendation": manifest.get("account_recommendation"),
            "proposed": manifest.get("proposed") or manifest.get("proposed_numbers"),
            "owner_adopted": False,
            "candidate_only": True,
        },
        "lab_provenance": {
            "episode_id": export.get("episode_id"),
            "attempt_hash": export.get("attempt_hash"),
            "attempt_cas_digest": export.get("attempt_cas_digest"),
            "cas_head_sha256": export.get("cas_head_sha256"),
            "host_session_id": export.get("host_session_id"),
            "provider_session_uuid": export.get("provider_session_uuid"),
            "research_profile": export.get("research_profile"),
            "namespace_receipt_sha256": export.get("namespace_receipt_sha256"),
            "release_identity_sha256": export.get("release_identity_sha256"),
            "tool_trace_hash": export.get("tool_trace_hash"),
            "pair_receipt_sha256": export.get("pair_receipt_sha256"),
            "actual_turns": export.get("actual_turns"),
        },
    }
    content_hash = canonical_sha256(body)
    return {**body, "content_hash": content_hash}


def remint_episode_pool_entry_from_raw(
    *,
    export_raw: bytes,
    manifest_raw: bytes,
) -> dict[str, Any]:
    """Shared ingest/load remint: export+manifest raw bytes → expected sealed entry.

    Reuses the same production verify/mint/build path as ingest so load cannot
    drift onto a second identity algorithm. Returns reminted objects plus the
    sealed expected pool entry.
    """

    if not isinstance(export_raw, (bytes, bytearray)) or not export_raw:
        raise EpisodeExportAdapterError("POOL_CAS_PARTIAL_STATE", "export bytes required")
    if not isinstance(manifest_raw, (bytes, bytearray)) or not manifest_raw:
        raise EpisodeExportAdapterError("POOL_CAS_PARTIAL_STATE", "manifest bytes required")
    export_bytes = bytes(export_raw)
    manifest_bytes = bytes(manifest_raw)
    export_sha = raw_sha256(export_bytes)
    export_obj = verify_episode_export_bundle(export_bytes)
    manifest = load_and_verify_candidate_manifest(
        export=export_obj,
        manifest_bytes=manifest_bytes,
    )
    manifest_sha = raw_sha256(manifest_bytes)
    # Export pin already enforced inside load_and_verify; keep explicit triple-bind.
    export_pin = export_obj.get("candidate_manifest_sha256")
    if export_pin != manifest_sha:
        raise EpisodeExportAdapterError(
            "CANDIDATE_MANIFEST_HASH_MISMATCH",
            f"export={export_pin} bytes={manifest_sha}",
        )
    policy = mint_policy_candidate_from_episode_export(
        export=export_obj,
        manifest=manifest,
        export_bytes_sha256=export_sha,
        manifest_bytes_sha256=manifest_sha,
    )
    expected_entry = _build_episode_pool_entry(
        export=export_obj,
        manifest=manifest,
        policy=policy,
        export_sha256=export_sha,
        manifest_sha256=manifest_sha,
    )
    return {
        "export_obj": export_obj,
        "manifest": manifest,
        "export_sha256": export_sha,
        "manifest_sha256": manifest_sha,
        "policy": policy,
        "expected_entry": expected_entry,
    }


def _assert_entry_matches_remint(
    entry: Mapping[str, Any],
    *,
    reminted: Mapping[str, Any],
) -> None:
    """Force actual entry identity to equal remint from CAS raw bytes.

    Seal alone is not enough: an attacker can rewrite candidate / policy_ref /
    policy_content_hash / receipt fields and recompute content_hash. Remint from
    export+manifest CAS is the ground truth.
    """

    manifest_sha = reminted["manifest_sha256"]
    expected = reminted["expected_entry"]
    if not isinstance(expected, Mapping):
        raise EpisodeExportAdapterError("POOL_ENTRY_IDENTITY_MISMATCH", "remint entry invalid")

    for field in (
        "receipt_content_sha256",
        "receipt_raw_sha256",
        "candidate_manifest_sha256",
    ):
        observed = entry.get(field)
        if observed != manifest_sha:
            raise EpisodeExportAdapterError(
                "POOL_ENTRY_RECEIPT_HASH_MISMATCH",
                f"{field} entry={observed} remint={manifest_sha}",
            )

    for field in (
        "policy_ref",
        "policy_content_hash",
        "decision_map_ref",
        "candidate",
        "result_sha256",
        "export_bundle_sha256",
        "content_hash",
    ):
        if entry.get(field) != expected.get(field):
            raise EpisodeExportAdapterError(
                "POOL_ENTRY_IDENTITY_MISMATCH",
                f"{field} entry={entry.get(field)!r} remint={expected.get(field)!r}",
            )

    # Full sealed body must match remint (lab_provenance, cutoff, flags, ...).
    if dict(entry) != dict(expected):
        diverged = sorted(k for k in set(entry) | set(expected) if entry.get(k) != expected.get(k))
        raise EpisodeExportAdapterError(
            "POOL_ENTRY_IDENTITY_MISMATCH",
            f"entry != remint fields={diverged}",
        )


def ingest_verified_episode_export(
    *,
    pool_root: Path,
    export: Mapping[str, Any] | bytes,
    manifest_bytes: bytes,
) -> dict[str, Any]:
    """Verify export+manifest, mint not-projected identity, exclusive-create pool entry."""
    # Normalize export to durable raw bytes first (CAS identity = raw sha256).
    if isinstance(export, (bytes, bytearray)):
        export_raw = bytes(export)
    else:
        # Verify structure before durable re-serialize so invalid mappings fail closed.
        export_obj_preview = verify_episode_export_bundle(export)
        export_raw = (
            json.dumps(dict(export_obj_preview), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
    reminted = remint_episode_pool_entry_from_raw(
        export_raw=export_raw,
        manifest_raw=bytes(manifest_bytes),
    )
    entry = reminted["expected_entry"]
    export_sha = reminted["export_sha256"]
    entry_path = pool_entry_path(pool_root, export_sha)
    result_path = pool_result_bytes_path(pool_root, export_sha)
    receipt_path = pool_receipt_path(pool_root, export_sha)
    result_exists = result_path.is_file()
    receipt_exists = receipt_path.is_file()
    entry_exists = entry_path.is_file()
    if result_exists and result_path.read_bytes() != export_raw:
        raise EpisodeExportAdapterError("POOL_CAS_CONTENT_CONFLICT", "export blob differs")
    if receipt_exists and receipt_path.read_bytes() != bytes(manifest_bytes):
        raise EpisodeExportAdapterError("POOL_CAS_CONTENT_CONFLICT", "manifest blob differs")
    if entry_exists:
        existing = json.loads(entry_path.read_text(encoding="utf-8"))
        if existing != entry:
            raise EpisodeExportAdapterError("POOL_CAS_CONTENT_CONFLICT", "entry seal differs")
        try:
            verify_pool_entry_seal(existing)
        except CandidatePoolError as exc:
            raise EpisodeExportAdapterError(exc.reason_code, exc.detail) from exc
        # Existing sealed entry must still rebind to remint (no stale forge left on disk).
        _assert_entry_matches_remint(existing, reminted=reminted)
        return dict(existing)
    if not result_exists:
        _write_new_bytes(result_path, export_raw)
    if not receipt_exists:
        _write_new_bytes(receipt_path, bytes(manifest_bytes))
    if not entry_exists:
        _write_new_json(entry_path, entry)
    return entry


def load_episode_pool_entry(pool_root: Path, result_sha256: str) -> dict[str, Any]:
    """Load pool entry; remint identity from CAS raw bytes (same path as ingest)."""
    digest = _require_hex64(result_sha256, "POOL_RESULT_HASH_INVALID", "result_sha256")
    entry_path = pool_entry_path(pool_root, digest)
    result_path = pool_result_bytes_path(pool_root, digest)
    receipt_path = pool_receipt_path(pool_root, digest)
    if not entry_path.is_file():
        raise EpisodeExportAdapterError("POOL_ENTRY_MISSING", digest)
    try:
        entry_obj = json.loads(entry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EpisodeExportAdapterError("POOL_ENTRY_INVALID", str(exc)) from exc
    if not isinstance(entry_obj, Mapping):
        raise EpisodeExportAdapterError("POOL_ENTRY_INVALID", "JSON object required")
    entry = dict(entry_obj)
    if entry.get("ingest_kind") != INGEST_KIND:
        # Fall back to one-shot loader for old entries.
        try:
            return load_pool_entry(pool_root, digest)
        except CandidatePoolError as exc:
            raise EpisodeExportAdapterError(exc.reason_code, exc.detail) from exc
    try:
        verify_pool_entry_seal(entry)
    except CandidatePoolError as exc:
        raise EpisodeExportAdapterError(exc.reason_code, exc.detail) from exc
    if entry.get("owner_adopted") is not False:
        raise EpisodeExportAdapterError("POOL_OWNER_ADOPTED_FORBIDDEN", "must false")
    if entry.get("result_sha256") != digest:
        raise EpisodeExportAdapterError(
            "POOL_ENTRY_HASH_MISMATCH",
            f"path={digest} body={entry.get('result_sha256')}",
        )
    # Missing/partial CAS must not surface bare FileNotFoundError/OSError.
    if not result_path.is_file() or not receipt_path.is_file():
        raise EpisodeExportAdapterError("POOL_CAS_PARTIAL_STATE", digest)
    try:
        export_raw = result_path.read_bytes()
        manifest_raw = receipt_path.read_bytes()
    except OSError as exc:
        raise EpisodeExportAdapterError("POOL_CAS_PARTIAL_STATE", f"{digest}: {exc}") from exc
    if raw_sha256(export_raw) != digest:
        raise EpisodeExportAdapterError("POOL_RESULT_BYTES_TAMPERED", digest)

    reminted = remint_episode_pool_entry_from_raw(
        export_raw=export_raw,
        manifest_raw=manifest_raw,
    )
    if reminted["export_sha256"] != digest:
        raise EpisodeExportAdapterError(
            "POOL_RESULT_HASH_DRIFT",
            f"path={digest} remint={reminted['export_sha256']}",
        )
    _assert_entry_matches_remint(entry, reminted=reminted)
    return dict(entry)


__all__ = [
    "ADAPTER_BINDING_KIND",
    "ADAPTER_MARKER",
    "EXPORT_SCHEMA",
    "INGEST_KIND",
    "MANIFEST_MARKER",
    "MANIFEST_SCHEMA",
    "EpisodeExportAdapterError",
    "ingest_verified_episode_export",
    "load_and_verify_candidate_manifest",
    "load_episode_pool_entry",
    "mint_policy_candidate_from_episode_export",
    "raw_sha256",
    "remint_episode_pool_entry_from_raw",
    "verify_episode_export_bundle",
]
