"""Content-addressed authority generations for the Foundation consumer.

The stable human files remain editable authority surfaces.  A Foundation
consumer binds only an independently reviewed, immutable publication
generation.  The current machine blueprint is the single atomic pointer: it
either references the old complete generation or the new complete generation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256

AUTHORITY_GENERATION_SCHEMA_VERSION = "xinao.foundation_authority_generation.v1"
AUTHORITY_GENERATION_REF_SCHEMA_VERSION = "xinao.foundation_authority_generation_ref.v1"
OWNER_VERDICT_SCHEMA_VERSION = "xinao.foundation_authority_compatibility_verdict.v1"
LEGACY_OWNER_SCOPE = (
    "LEGACY_PARENT_G0_G8 Foundation F1-F4 implementation binding only; "
    "not current science admission"
)
PRE_SWITCH_OWNER_SCOPE = (
    "Foundation F1-F4 implementation binding only; formal research remains closed"
)

DEFAULT_ARCHIVE_MANIFEST_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current"
    r"\archive_relocation_manifest.json"
)
DEFAULT_VERIFICATION_REPORT_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current"
    r"\verification_report.json"
)
DEFAULT_REVIEW_SUMMARY_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current"
    r"\independent_review_summary.json"
)
DEFAULT_GENERATION_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\foundation_authority_generations")

GENERATION_MANIFEST_FILENAME = "generation_manifest.json"
HUMAN_SPEC_FILENAME = "human_spec_snapshot.txt"
FORMAL_CONTRACT_FILENAME = "formal_contract_snapshot.txt"
OWNER_VERDICT_FILENAME = "owner_verdict.json"


class AuthorityGenerationError(ValueError):
    """Raised when a publication or authority generation is not exact."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_ref(path: Path) -> dict[str, Any]:
    path = path.resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": _sha256_bytes(raw), "size": len(raw)}


def _load_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    path = path.resolve()
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityGenerationError(f"{label} is unavailable or invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuthorityGenerationError(f"{label} must be an object: {path}")
    return value, raw


def _resolved_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AuthorityGenerationError(f"{label} path is missing")
    try:
        return Path(value).resolve()
    except OSError as exc:
        raise AuthorityGenerationError(f"{label} path is invalid: {value}") from exc


def _is_reparse(path: Path) -> bool:
    value = os.lstat(path)
    attributes = int(getattr(value, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse_flag)


def _assert_plain_tree(root: Path) -> None:
    if _is_reparse(root):
        raise AuthorityGenerationError(f"generation root is a reparse point: {root}")
    for path in root.rglob("*"):
        if _is_reparse(path):
            raise AuthorityGenerationError(f"generation contains a reparse point: {path}")


def load_reviewed_publication(
    *,
    archive_manifest_path: Path = DEFAULT_ARCHIVE_MANIFEST_PATH,
    verification_report_path: Path = DEFAULT_VERIFICATION_REPORT_PATH,
    review_summary_path: Path = DEFAULT_REVIEW_SUMMARY_PATH,
) -> dict[str, Any]:
    """Validate the reviewed LEGACY_PARENT_G0_G8 publication only."""

    archive, _ = _load_object(archive_manifest_path, label="archive manifest")
    publication = archive.get("legacy_parent")
    if archive.get("schema_version") != "xinao.archive-relocation-manifest.v1" or not isinstance(
        publication, dict
    ):
        raise AuthorityGenerationError("archive manifest has no legacy G0-G8 publication")
    if (
        publication.get("authority_scope") != "LEGACY_PARENT_G0_G8"
        or publication.get("active_parent_status") != "SUPERSEDED_AS_ACTIVE_PARENT"
    ):
        raise AuthorityGenerationError("legacy publication escaped its authority scope")

    stable_spec = _resolved_path(
        publication.get("stable_archive_path"), label="legacy stable archive"
    )
    spec_snapshot = stable_spec
    formal_contract = _resolved_path(
        publication.get("formal_contract_path"), label="legacy formal contract"
    )
    for path, label in (
        (stable_spec, "stable spec"),
        (spec_snapshot, "versioned spec snapshot"),
        (formal_contract, "formal contract"),
    ):
        if not path.is_file() or _is_reparse(path):
            raise AuthorityGenerationError(f"{label} is unavailable or unsafe: {path}")

    stable_ref = _file_ref(stable_spec)
    snapshot_ref = _file_ref(spec_snapshot)
    contract_ref = _file_ref(formal_contract)
    if (
        stable_ref["sha256"] != snapshot_ref["sha256"]
        or publication.get("stable_archive_sha256") != stable_ref["sha256"]
        or publication.get("formal_contract_sha256") != contract_ref["sha256"]
    ):
        raise AuthorityGenerationError("legacy publication material identity is inconsistent")

    report, _ = _load_object(verification_report_path, label="verification report")
    summary, _ = _load_object(review_summary_path, label="independent review summary")
    frozen = report.get("frozen_active_surface_manifest")
    if (
        report.get("status") != "DOCUMENT_PUBLICATION_VERIFIED"
        or report.get("output_hashes_snapshot_status") != "PROMOTED_CURRENT_SNAPSHOT"
        or not isinstance(frozen, dict)
        or summary.get("status") != "PASS"
        or summary.get("schema_version") != "xinao.document-publication-independent-review.v2"
    ):
        raise AuthorityGenerationError("document publication has not passed durable review")

    frozen_path = _resolved_path(frozen.get("path"), label="frozen publication manifest")
    frozen_ref = _file_ref(frozen_path)
    if frozen.get("sha256", "").lower() != frozen_ref["sha256"]:
        raise AuthorityGenerationError("frozen publication manifest hash drifted")
    if (
        summary.get("frozen_manifest_path") != str(frozen_path)
        or str(summary.get("frozen_manifest_sha256", "")).lower() != frozen_ref["sha256"]
    ):
        raise AuthorityGenerationError("review summary does not bind the promoted manifest")

    output_hashes = report.get("output_hashes")
    if not isinstance(output_hashes, dict):
        raise AuthorityGenerationError("verification report has no promoted output hashes")
    promoted_digests = {str(value).lower() for value in output_hashes.values()}
    for label, digest in (
        ("legacy stable archive", stable_ref["sha256"]),
        ("legacy formal contract", contract_ref["sha256"]),
    ):
        if digest not in promoted_digests:
            raise AuthorityGenerationError(f"reviewed output hash is missing or stale: {label}")

    return {
        "archive_manifest_ref": _file_ref(archive_manifest_path),
        "verification_report_ref": _file_ref(verification_report_path),
        "review_summary_ref": _file_ref(review_summary_path),
        "frozen_manifest_ref": frozen_ref,
        "stable_spec_ref": stable_ref,
        "human_spec_snapshot_ref": snapshot_ref,
        "formal_contract_ref": contract_ref,
        "authority_scope": "LEGACY_PARENT_G0_G8",
        "active_parent_status": "SUPERSEDED_AS_ACTIVE_PARENT",
    }


def build_owner_verdict(
    *,
    publication: Mapping[str, Any],
    expected_projection_sha256: str,
    implementation_model_core_sha256: str,
    owner_id: str,
    rationale: str,
) -> dict[str, Any]:
    """Build the exact owner decision that authorizes mechanical promotion."""

    if len(expected_projection_sha256) != 64 or len(implementation_model_core_sha256) != 64:
        raise AuthorityGenerationError("expected projection or model-core SHA256 is invalid")
    if not owner_id.strip() or not rationale.strip():
        raise AuthorityGenerationError("owner verdict identity and rationale are required")
    core = {
        "schema_version": OWNER_VERDICT_SCHEMA_VERSION,
        "authority": True,
        "decision": "ADOPT_COMPATIBLE_PUBLICATION",
        "owner_id": owner_id.strip(),
        "rationale": rationale.strip(),
        "expected_projection_sha256": expected_projection_sha256.lower(),
        "implementation_model_core_sha256": implementation_model_core_sha256.lower(),
        "publication_manifest_sha256": str(publication["frozen_manifest_ref"]["sha256"]).lower(),
        "human_spec_snapshot_sha256": str(publication["human_spec_snapshot_ref"]["sha256"]).lower(),
        "formal_contract_sha256": str(publication["formal_contract_ref"]["sha256"]).lower(),
        "scope": LEGACY_OWNER_SCOPE,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def _write_new_file(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def prepare_authority_generation(
    *,
    projection_path: Path,
    owner_id: str,
    rationale: str,
    generation_root: Path = DEFAULT_GENERATION_ROOT,
    archive_manifest_path: Path = DEFAULT_ARCHIVE_MANIFEST_PATH,
    verification_report_path: Path = DEFAULT_VERIFICATION_REPORT_PATH,
    review_summary_path: Path = DEFAULT_REVIEW_SUMMARY_PATH,
) -> dict[str, Any]:
    """Create or exactly reuse an immutable, content-addressed generation."""

    projection_ref = _file_ref(projection_path)
    publication = load_reviewed_publication(
        archive_manifest_path=archive_manifest_path,
        verification_report_path=verification_report_path,
        review_summary_path=review_summary_path,
    )
    from xinao.foundation.foundation_implementation_model import (
        implementation_model_core_sha256,
    )

    model_core_sha256 = implementation_model_core_sha256()
    verdict = build_owner_verdict(
        publication=publication,
        expected_projection_sha256=projection_ref["sha256"],
        implementation_model_core_sha256=model_core_sha256,
        owner_id=owner_id,
        rationale=rationale,
    )
    verdict_bytes = canonical_dumps(verdict)
    spec_bytes = Path(publication["human_spec_snapshot_ref"]["path"]).read_bytes()
    contract_bytes = Path(publication["formal_contract_ref"]["path"]).read_bytes()

    core = {
        "schema_version": AUTHORITY_GENERATION_SCHEMA_VERSION,
        "authority": False,
        "promotion_eligible": True,
        "expected_previous_projection_sha256": projection_ref["sha256"],
        "materials": {
            "human_spec_snapshot": {
                "relative_path": HUMAN_SPEC_FILENAME,
                "sha256": _sha256_bytes(spec_bytes),
                "size": len(spec_bytes),
            },
            "formal_contract_snapshot": {
                "relative_path": FORMAL_CONTRACT_FILENAME,
                "sha256": _sha256_bytes(contract_bytes),
                "size": len(contract_bytes),
            },
        },
        "publication_refs": {
            "archive_manifest_sha256": publication["archive_manifest_ref"]["sha256"],
            "verification_report_sha256": publication["verification_report_ref"]["sha256"],
            "review_summary_sha256": publication["review_summary_ref"]["sha256"],
            "frozen_manifest_sha256": publication["frozen_manifest_ref"]["sha256"],
        },
        "owner_verdict_ref": {
            "relative_path": OWNER_VERDICT_FILENAME,
            "sha256": _sha256_bytes(verdict_bytes),
            "size": len(verdict_bytes),
            "content_sha256": verdict["content_sha256"],
        },
        "consumer_scope": "Foundation F1-F4 implementation binding",
        "does_not_imply_formal_research": True,
    }
    manifest = {**core, "content_sha256": canonical_sha256(core)}
    manifest_bytes = canonical_dumps(manifest)
    generation_root = generation_root.resolve()
    generation_root.mkdir(parents=True, exist_ok=True)
    target = generation_root / manifest["content_sha256"]

    if target.exists():
        validated = validate_authority_generation(target / GENERATION_MANIFEST_FILENAME)
        return {
            "generation_root": target,
            "manifest_path": target / GENERATION_MANIFEST_FILENAME,
            "manifest": validated["manifest"],
            "binding": validated["binding"],
            "reused": True,
        }

    temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=generation_root))
    try:
        _write_new_file(temporary / HUMAN_SPEC_FILENAME, spec_bytes)
        _write_new_file(temporary / FORMAL_CONTRACT_FILENAME, contract_bytes)
        _write_new_file(temporary / OWNER_VERDICT_FILENAME, verdict_bytes)
        _write_new_file(temporary / GENERATION_MANIFEST_FILENAME, manifest_bytes)
        validate_authority_generation(
            temporary / GENERATION_MANIFEST_FILENAME,
            require_content_addressed_root=False,
        )
        os.replace(temporary, target)
        validated = validate_authority_generation(target / GENERATION_MANIFEST_FILENAME)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "generation_root": target,
        "manifest_path": target / GENERATION_MANIFEST_FILENAME,
        "manifest": validated["manifest"],
        "binding": validated["binding"],
        "reused": False,
    }


def validate_authority_generation(
    manifest_path: Path,
    *,
    require_content_addressed_root: bool = True,
) -> dict[str, Any]:
    """Validate an immutable generation and return its model binding."""

    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    if manifest_path.name != GENERATION_MANIFEST_FILENAME or not root.is_dir():
        raise AuthorityGenerationError("generation manifest location is invalid")
    _assert_plain_tree(root)
    expected_files = {
        GENERATION_MANIFEST_FILENAME,
        HUMAN_SPEC_FILENAME,
        FORMAL_CONTRACT_FILENAME,
        OWNER_VERDICT_FILENAME,
    }
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual_files != expected_files:
        raise AuthorityGenerationError("generation file inventory is not exact")

    manifest, manifest_bytes = _load_object(manifest_path, label="generation manifest")
    if canonical_dumps(manifest) != manifest_bytes:
        raise AuthorityGenerationError("generation manifest is not canonical JSON")
    core = dict(manifest)
    content_sha256 = core.pop("content_sha256", None)
    if (
        manifest.get("schema_version") != AUTHORITY_GENERATION_SCHEMA_VERSION
        or manifest.get("authority") is not False
        or manifest.get("promotion_eligible") is not True
        or manifest.get("does_not_imply_formal_research") is not True
        or canonical_sha256(core) != content_sha256
        or (require_content_addressed_root and root.name != content_sha256)
    ):
        raise AuthorityGenerationError("generation manifest identity is inconsistent")

    materials = manifest.get("materials")
    verdict_ref = manifest.get("owner_verdict_ref")
    publication_refs = manifest.get("publication_refs")
    if (
        not isinstance(materials, dict)
        or not isinstance(verdict_ref, dict)
        or not isinstance(publication_refs, dict)
    ):
        raise AuthorityGenerationError("generation references are incomplete")
    for key, filename in (
        ("human_spec_snapshot", HUMAN_SPEC_FILENAME),
        ("formal_contract_snapshot", FORMAL_CONTRACT_FILENAME),
    ):
        ref = materials.get(key)
        if not isinstance(ref, dict) or ref.get("relative_path") != filename:
            raise AuthorityGenerationError(f"generation material reference is invalid: {key}")
        raw = (root / filename).read_bytes()
        if ref.get("sha256") != _sha256_bytes(raw) or ref.get("size") != len(raw):
            raise AuthorityGenerationError(f"generation material drifted: {key}")

    verdict_path = root / OWNER_VERDICT_FILENAME
    verdict, verdict_bytes = _load_object(verdict_path, label="owner verdict")
    verdict_core = dict(verdict)
    verdict_content_hash = verdict_core.pop("content_sha256", None)
    if (
        verdict.get("schema_version") != OWNER_VERDICT_SCHEMA_VERSION
        or verdict.get("authority") is not True
        or verdict.get("decision") != "ADOPT_COMPATIBLE_PUBLICATION"
        or verdict.get("scope") not in {LEGACY_OWNER_SCOPE, PRE_SWITCH_OWNER_SCOPE}
        or canonical_sha256(verdict_core) != verdict_content_hash
        or verdict_ref.get("relative_path") != OWNER_VERDICT_FILENAME
        or verdict_ref.get("sha256") != _sha256_bytes(verdict_bytes)
        or verdict_ref.get("size") != len(verdict_bytes)
        or verdict_ref.get("content_sha256") != verdict_content_hash
        or verdict.get("human_spec_snapshot_sha256") != materials["human_spec_snapshot"]["sha256"]
        or verdict.get("formal_contract_sha256") != materials["formal_contract_snapshot"]["sha256"]
        or verdict.get("expected_projection_sha256")
        != manifest.get("expected_previous_projection_sha256")
        or not isinstance(verdict.get("implementation_model_core_sha256"), str)
        or len(verdict["implementation_model_core_sha256"]) != 64
        or verdict.get("publication_manifest_sha256")
        != publication_refs.get("frozen_manifest_sha256")
    ):
        raise AuthorityGenerationError("owner verdict does not bind this generation")

    binding = {
        "generation_manifest_sha256": _sha256_bytes(manifest_bytes),
        "generation_content_sha256": content_sha256,
        "human_spec_snapshot_sha256": materials["human_spec_snapshot"]["sha256"],
        "formal_contract_snapshot_sha256": materials["formal_contract_snapshot"]["sha256"],
        "implementation_model_core_sha256": verdict["implementation_model_core_sha256"],
        "publication_manifest_sha256": publication_refs["frozen_manifest_sha256"],
        "owner_verdict_sha256": verdict_ref["sha256"],
    }
    return {"manifest": manifest, "binding": binding, "root": root}


def generation_reference(manifest_path: Path) -> dict[str, Any]:
    validated = validate_authority_generation(manifest_path)
    raw = manifest_path.resolve().read_bytes()
    return {
        "schema_version": AUTHORITY_GENERATION_REF_SCHEMA_VERSION,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha256_bytes(raw),
        "generation_content_sha256": validated["manifest"]["content_sha256"],
    }


def load_generation_binding_from_projection(
    projection: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    authority = projection.get("authority")
    if not isinstance(authority, Mapping):
        raise AuthorityGenerationError("projection authority is missing")
    reference = authority.get("foundation_generation")
    if not isinstance(reference, Mapping):
        raise AuthorityGenerationError("projection has no Foundation generation")
    expected_keys = {
        "schema_version",
        "manifest_path",
        "manifest_sha256",
        "generation_content_sha256",
    }
    if set(reference) != expected_keys or reference.get("schema_version") != (
        AUTHORITY_GENERATION_REF_SCHEMA_VERSION
    ):
        raise AuthorityGenerationError("Foundation generation reference shape is invalid")
    manifest_path = _resolved_path(reference.get("manifest_path"), label="generation manifest")
    validated = validate_authority_generation(manifest_path)
    manifest_raw = manifest_path.read_bytes()
    if (
        reference.get("manifest_sha256") != _sha256_bytes(manifest_raw)
        or reference.get("generation_content_sha256") != validated["manifest"]["content_sha256"]
    ):
        raise AuthorityGenerationError("Foundation generation reference drifted")
    return dict(validated["binding"]), dict(reference)


__all__ = [
    "AUTHORITY_GENERATION_REF_SCHEMA_VERSION",
    "AUTHORITY_GENERATION_SCHEMA_VERSION",
    "DEFAULT_ARCHIVE_MANIFEST_PATH",
    "DEFAULT_GENERATION_ROOT",
    "DEFAULT_REVIEW_SUMMARY_PATH",
    "DEFAULT_VERIFICATION_REPORT_PATH",
    "GENERATION_MANIFEST_FILENAME",
    "OWNER_VERDICT_SCHEMA_VERSION",
    "AuthorityGenerationError",
    "build_owner_verdict",
    "generation_reference",
    "load_generation_binding_from_projection",
    "load_reviewed_publication",
    "prepare_authority_generation",
    "validate_authority_generation",
]
