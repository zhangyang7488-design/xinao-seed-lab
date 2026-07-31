"""Pure ResearchEpisode candidate-manifest schema, constants, and validator.

Single source of truth for host package consumers (xinao-discovery wheel),
pool adapter, and image-side COPY of these exact bytes. No Docker/CLI deps.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

CANDIDATE_MANIFEST_SCHEMA: Final = "xinao.research_episode_candidate_manifest.v1"
CANDIDATE_MANIFEST_MARKER: Final = "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1"
CANDIDATE_MANIFEST_RELATIVE: Final = "candidate/candidate_manifest.v1.json"
ACCOUNT_RECOMMENDATION_VALUES: Final = frozenset(
    {
        "ACTION_CANDIDATE",
        "NO_ACTION_CANDIDATE",
        "NO_RECOMMENDATION",
    }
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CandidateManifestError(ValueError):
    """Fail-closed candidate manifest rejection (package + native re-export)."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def module_source_path() -> Path:
    """Absolute path of this canonical module (for image seal / byte-identity checks)."""
    return Path(__file__).resolve()


def module_source_sha256() -> str:
    """Seal of these exact source bytes (release/image evidence pin)."""
    return hashlib.sha256(module_source_path().read_bytes()).hexdigest()


def validate_candidate_manifest(
    payload: Mapping[str, Any] | bytes,
    *,
    expected_episode_id: str | None = None,
    expected_attempt_cas_digest: str | None = None,
) -> dict[str, Any]:
    """Validate closed lab-authored candidate manifest schema (candidate-only)."""
    if isinstance(payload, (bytes, bytearray)):
        try:
            obj = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidateManifestError("CANDIDATE_MANIFEST_JSON_INVALID", str(exc)) from exc
    else:
        obj = dict(payload)
    if not isinstance(obj, dict):
        raise CandidateManifestError("CANDIDATE_MANIFEST_JSON_INVALID", "object required")
    if obj.get("schema_version") != CANDIDATE_MANIFEST_SCHEMA:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_SCHEMA_INVALID",
            str(obj.get("schema_version")),
        )
    if obj.get("manifest_marker") != CANDIDATE_MANIFEST_MARKER:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_MARKER_INVALID",
            str(obj.get("manifest_marker")),
        )
    for key in (
        "candidate_id",
        "candidate_version",
        "research_question",
        "research_object",
        "account_recommendation",
    ):
        if not isinstance(obj.get(key), str) or not str(obj.get(key)).strip():
            raise CandidateManifestError("CANDIDATE_MANIFEST_FIELD_INVALID", key)
    if obj.get("account_recommendation") not in ACCOUNT_RECOMMENDATION_VALUES:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_RECOMMENDATION_INVALID",
            str(obj.get("account_recommendation")),
        )
    data_cutoff = obj.get("data_cutoff")
    if not isinstance(data_cutoff, Mapping):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_CUTOFF_INVALID", "data_cutoff object required"
        )
    if not isinstance(data_cutoff.get("as_of"), str) or not str(data_cutoff.get("as_of")).strip():
        raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "as_of required")
    material_refs = data_cutoff.get("material_refs") or []
    if not isinstance(material_refs, list):
        raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "material_refs list")
    for ref in material_refs:
        if not isinstance(ref, Mapping):
            raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "material_ref object")
        digest = ref.get("sha256")
        if not isinstance(digest, str) or _HEX_SHA256.fullmatch(digest) is None:
            raise CandidateManifestError("CANDIDATE_MANIFEST_CUTOFF_INVALID", "material_ref.sha256")
    methods = obj.get("method_refs") or obj.get("methods")
    if methods is None:
        raise CandidateManifestError("CANDIDATE_MANIFEST_METHODS_INVALID", "method_refs required")
    # Wild / overfit / black-box methods are allowed; only type-check structure.
    if not isinstance(methods, (list, Mapping, str)):
        raise CandidateManifestError("CANDIDATE_MANIFEST_METHODS_INVALID", type(methods).__name__)
    falsifiers = obj.get("falsifiers") or obj.get("limitations")
    if falsifiers is None:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_LIMITATIONS_INVALID", "falsifiers/limitations"
        )
    if not isinstance(falsifiers, list):
        raise CandidateManifestError("CANDIDATE_MANIFEST_LIMITATIONS_INVALID", "list required")
    # Candidate-only authority clamps (never Owner disposition / completion).
    if obj.get("owner_adopted") is not False:
        raise CandidateManifestError("CANDIDATE_MANIFEST_OWNER_ADOPTED_FORBIDDEN", "must be false")
    if obj.get("completion") is not False and obj.get("completion_claim_allowed") is not False:
        # Accept either key; both must be false when present. Require at least completion=false.
        if "completion" not in obj and "completion_claim_allowed" not in obj:
            raise CandidateManifestError(
                "CANDIDATE_MANIFEST_COMPLETION_MISSING", "completion=false"
            )
        if obj.get("completion") is True or obj.get("completion_claim_allowed") is True:
            raise CandidateManifestError("CANDIDATE_MANIFEST_COMPLETION_FORBIDDEN", "must be false")
    if obj.get("candidate_only") is not True:
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_CANDIDATE_ONLY_REQUIRED", "candidate_only=true"
        )
    for forbidden, reason in (
        ("account_identity", "ACCOUNT_IDENTITY_FORBIDDEN"),
        ("science_disposition", "SCIENCE_DISPOSITION_FORBIDDEN"),
        ("frozen", "FREEZE_CLAIM_FORBIDDEN"),
        ("parent_complete", "PARENT_COMPLETE_FORBIDDEN"),
        ("science_restored", "SCIENCE_RESTORED_FORBIDDEN"),
    ):
        if obj.get(forbidden) not in {None, False}:
            raise CandidateManifestError(f"CANDIDATE_MANIFEST_{reason}", forbidden)
    if (
        expected_episode_id is not None
        and obj.get("episode_id") not in {None, expected_episode_id}
        and obj.get("episode_id") != expected_episode_id
    ):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_EPISODE_MISMATCH",
            f"{obj.get('episode_id')}!={expected_episode_id}",
        )
    if (
        expected_attempt_cas_digest is not None
        and obj.get("attempt_cas_digest") not in {None, expected_attempt_cas_digest}
        and obj.get("attempt_cas_digest") != expected_attempt_cas_digest
    ):
        raise CandidateManifestError(
            "CANDIDATE_MANIFEST_ATTEMPT_MISMATCH",
            f"{obj.get('attempt_cas_digest')}!={expected_attempt_cas_digest}",
        )
    # proposed numbers/stake only as candidate content (optional).
    proposed = obj.get("proposed") or obj.get("proposed_numbers")
    if proposed is not None and not isinstance(proposed, (Mapping, list)):
        raise CandidateManifestError("CANDIDATE_MANIFEST_PROPOSED_INVALID", type(proposed).__name__)
    return obj


__all__ = [
    "ACCOUNT_RECOMMENDATION_VALUES",
    "CANDIDATE_MANIFEST_MARKER",
    "CANDIDATE_MANIFEST_RELATIVE",
    "CANDIDATE_MANIFEST_SCHEMA",
    "CandidateManifestError",
    "module_source_path",
    "module_source_sha256",
    "validate_candidate_manifest",
]
