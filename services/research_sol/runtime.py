"""Thin mechanical runtime for cross-contact world and byte-tree continuity.

This module deliberately does not define a research ontology.  ``WorldPin`` and
``CognitionObject`` are implementation receipts: exact surfaces delivered at a
contact boundary and exact bytes generated inside one such contact.  Neither
receipt carries instruction, scientific, adoption, or shared-effect authority.

The file is pure stdlib because world-compute freezes it beside each controller
release and imports that exact copy during recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

WORLD_LIVE = "WORLD_LIVE"
FROZEN_AUDIT = "FROZEN_AUDIT"
CONTACT_CLASSES = frozenset({WORLD_LIVE, FROZEN_AUDIT})

CARRIER_ENVELOPE_SCHEMA = "xinao.research-sol.carrier-envelope.v1"
WORLD_PIN_SCHEMA = "xinao.research-sol.world-pin.v1"
COGNITION_TREE_SCHEMA = "xinao.research-sol.exact-tree.v1"
COGNITION_OBJECT_SCHEMA = "xinao.research-sol.cognition-object.v1"
OBJECT_OPEN_SCHEMA = "xinao.research-sol.object-open-receipt.v1"
TERMINAL_RECONCILIATION_SCHEMA = "xinao.research-sol.terminal-reconciliation.v1"

_FALSE_AUTHORITY = {
    "authority": False,
    "instruction_authority": False,
    "cognition_authority": False,
    "shared_effect_authorized": False,
    "completion_claim_allowed": False,
}


class ResearchSolRuntimeError(RuntimeError):
    """Typed fail-closed carrier/runtime error."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise ResearchSolRuntimeError(reason_code, message)


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(value: object) -> str:
    return _sha256(_canonical_json_bytes(value))


def _atomic_write(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(raw)


def _write_once(path: Path, value: object, *, conflict_code: str) -> str:
    raw = _canonical_json_bytes(value)
    if path.exists():
        if path.read_bytes() != raw:
            _fail(conflict_code, f"write-once identity conflict: {path}")
        return _sha256(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # A hard-link is an atomic create-if-absent publication on the same
            # filesystem.  It avoids two concurrent sealers replacing each other.
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                _fail(conflict_code, f"write-once identity conflict: {path}")
        except OSError:
            # Some filesystems deny hard links.  Never silently weaken write-once
            # semantics: only accept a concurrently published identical object.
            if not path.exists() or path.read_bytes() != raw:
                raise
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(raw)


def _read_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchSolRuntimeError(code, f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        _fail(code, f"JSON value is not an object: {path}")
    return value


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        _fail("OBJECT_PATH_INVALID", "object path must be a non-empty string")
    normalized = value.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or normalized.startswith("/") or "\x00" in normalized:
        _fail("OBJECT_PATH_INVALID", f"object path is not relative: {value!r}")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        _fail("OBJECT_PATH_INVALID", f"object path contains traversal: {value!r}")
    return "/".join(candidate.parts)


def _resolve_contained(root: Path, relative: str) -> Path:
    root = root.resolve(strict=False)
    selected = (root / Path(*relative.split("/"))).resolve(strict=False)
    if selected == root or not selected.is_relative_to(root):
        _fail("OBJECT_PATH_ESCAPE", f"object path escapes destination: {relative}")
    return selected


def build_carrier_envelope(
    contact_class: str,
    *,
    network_access: bool,
    world_surface: str,
    fresh_session: bool,
    output_contract: str,
) -> dict[str, Any]:
    """Build the small sealed body contract that keeps LIVE and AUDIT distinct."""

    if contact_class not in CONTACT_CLASSES:
        _fail("CONTACT_CLASS_INVALID", f"unsupported contact class: {contact_class!r}")
    expected = {
        WORLD_LIVE: {
            "network_access": True,
            "fresh_session": True,
            "world_surface": "LINEAGE_WORLD",
            "output_contract": "MECHANICAL_TERMINAL_AND_ARBITRARY_ARTIFACTS",
        },
        FROZEN_AUDIT: {
            "network_access": False,
            "fresh_session": True,
            "world_surface": "CONTRACT_SELECTED_FROZEN_EVIDENCE",
            "output_contract": "OPAQUE_CANDIDATE_PAYLOAD",
        },
    }[contact_class]
    observed = {
        "network_access": network_access,
        "fresh_session": fresh_session,
        "world_surface": world_surface,
        "output_contract": output_contract,
    }
    if observed != expected:
        _fail(
            "CONTACT_CLASS_ENVELOPE_MISMATCH",
            f"{contact_class} envelope mismatch; expected={expected!r} observed={observed!r}",
        )
    body = {
        "schema": CARRIER_ENVELOPE_SCHEMA,
        "contact_class": contact_class,
        **observed,
        "workspace_write_scope": "CURRENT_LINEAGE_ONLY",
        "candidate_only": True,
        **_FALSE_AUTHORITY,
    }
    return {**body, "envelope_id": _stable_id(body)}


def validate_carrier_envelope(value: Mapping[str, Any], *, expected_class: str) -> dict[str, Any]:
    if value.get("schema") != CARRIER_ENVELOPE_SCHEMA or value.get("contact_class") != expected_class:
        _fail("CARRIER_ENVELOPE_IDENTITY_INVALID", "carrier envelope identity mismatch")
    rebuilt = build_carrier_envelope(
        expected_class,
        network_access=value.get("network_access") is True,
        world_surface=str(value.get("world_surface", "")),
        fresh_session=value.get("fresh_session") is True,
        output_contract=str(value.get("output_contract", "")),
    )
    if dict(value) != rebuilt:
        _fail("CARRIER_ENVELOPE_DRIFT", "carrier envelope bytes/fields drifted")
    return rebuilt


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        _fail("WORLD_PIN_GIT_FAILED", completed.stderr[-2000:])
    return completed.stdout.strip()


def _normalize_surface_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    coverage = {"included": [], "omitted": [], "unknown": []}
    seen: set[str] = set()
    for raw in rows:
        surface_id = str(raw.get("surface_id", "")).strip()
        status = str(raw.get("status", "")).upper()
        if not surface_id or surface_id in seen or status not in {"INCLUDED", "OMITTED", "UNKNOWN"}:
            _fail("WORLD_PIN_COVERAGE_INVALID", f"invalid/duplicate surface row: {raw!r}")
        seen.add(surface_id)
        row = {"surface_id": surface_id}
        if status == "INCLUDED":
            identity = raw.get("identity")
            if not isinstance(identity, Mapping) or not identity:
                _fail("WORLD_PIN_INCLUDED_IDENTITY_MISSING", f"included surface lacks identity: {surface_id}")
            row["identity"] = dict(identity)
            coverage["included"].append(row)
        else:
            reason = str(raw.get("reason", "")).strip()
            if not reason:
                _fail("WORLD_PIN_COVERAGE_REASON_MISSING", f"{status} surface lacks reason: {surface_id}")
            row["reason"] = reason
            coverage[status.lower()].append(row)
    for values in coverage.values():
        values.sort(key=lambda item: item["surface_id"])
    return coverage


def build_world_pin(
    pin_root: Path,
    *,
    activity_id: str,
    contact_id: str,
    source_repo: Path,
    source_head: str,
    workspace: Path,
    overlay_manifest_path: Path,
    required_surface_ids: Sequence[str],
    surface_catalog: Sequence[Mapping[str, Any]],
    runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal an exact, coverage-closed delivery receipt for one LIVE contact."""

    if not activity_id.strip() or not contact_id.strip() or not source_head.strip():
        _fail("WORLD_PIN_IDENTITY_INVALID", "activity/contact/source identity must be non-empty")
    pin_root = pin_root.resolve(strict=False)
    source_repo = source_repo.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    overlay_manifest_path = overlay_manifest_path.resolve(strict=True)
    _git(source_repo, "cat-file", "-e", f"{source_head}^{{commit}}")
    observed_head = _git(workspace, "rev-parse", "HEAD")
    merge_base = _git(workspace, "merge-base", source_head, observed_head)
    if merge_base.casefold() != source_head.casefold():
        _fail("WORLD_PIN_WORKSPACE_LINEAGE_DRIFT", "workspace no longer descends from baseline")
    tree_digest = _git(source_repo, "rev-parse", f"{source_head}^{{tree}}")
    workspace_tree_digest = _git(workspace, "rev-parse", f"{observed_head}^{{tree}}")
    overlay = _read_json(overlay_manifest_path, code="WORLD_PIN_OVERLAY_MANIFEST_INVALID")
    if (
        str(overlay.get("source_head", "")).casefold() != source_head.casefold()
        or Path(str(overlay.get("source_workspace", ""))).resolve(strict=False) != workspace
    ):
        _fail("WORLD_PIN_OVERLAY_IDENTITY_DRIFT", "overlay manifest binds another world")
    if overlay.get("complete") is not True:
        _fail("WORLD_PIN_OVERLAY_INCOMPLETE", "exact-current workspace overlay is incomplete")
    overlay_sha256 = _sha256_file(overlay_manifest_path)
    mandatory_rows: list[Mapping[str, Any]] = [
        {
            "surface_id": "repo",
            "status": "INCLUDED",
            "identity": {
                "source_path": str(source_repo),
                "head": source_head,
                "tree_digest": tree_digest,
            },
        },
        {
            "surface_id": "workspace_overlay",
            "status": "INCLUDED",
            "identity": {
                "workspace": str(workspace),
                "manifest_path": str(overlay_manifest_path),
                "manifest_sha256": overlay_sha256,
                "complete": True,
                "captured_at": overlay.get("captured_at"),
                "workspace_head": observed_head,
                "workspace_tree_digest": workspace_tree_digest,
            },
        },
    ]
    required = [str(value).strip() for value in required_surface_ids]
    required_set = set(required)
    if (
        any(not value for value in required)
        or len(required) != len(required_set)
        or not {"repo", "workspace_overlay"}.issubset(required_set)
    ):
        _fail("WORLD_PIN_SURFACE_UNIVERSE_INVALID", "registered surface universe is invalid")
    supplied = [str(row.get("surface_id", "")).strip() for row in surface_catalog]
    supplied_ids = set(supplied)
    if len(supplied) != len(supplied_ids):
        _fail("WORLD_PIN_COVERAGE_INVALID", "surface catalog repeats a surface")
    if supplied_ids & {"repo", "workspace_overlay"}:
        _fail("WORLD_PIN_COVERAGE_DUPLICATE_MANDATORY", "caller repeated a mandatory surface")
    expected_supplied = required_set - {"repo", "workspace_overlay"}
    if supplied_ids != expected_supplied:
        _fail(
            "WORLD_PIN_COVERAGE_NOT_CLOSED",
            "surface catalog does not exactly cover the registered universe; "
            f"missing={sorted(expected_supplied - supplied_ids)!r} "
            f"unexpected={sorted(supplied_ids - expected_supplied)!r}",
        )
    coverage = _normalize_surface_rows([*mandatory_rows, *surface_catalog])
    normalized_universe = sorted(required_set)
    identity = {
        "schema": WORLD_PIN_SCHEMA,
        "activity_id": activity_id,
        "contact_id": contact_id,
        "repo": mandatory_rows[0]["identity"],
        "workspace": str(workspace),
        "overlay_manifest": mandatory_rows[1]["identity"],
        "surface_universe": {
            "scope": "REGISTERED_CARRIER_SURFACES_AT_CONTACT_CUTOFF",
            "surface_ids": normalized_universe,
            "universe_id": _stable_id(normalized_universe),
        },
        "coverage": coverage,
        "runtime_identity": dict(runtime_identity or {}),
        **_FALSE_AUTHORITY,
    }
    pin_id = _stable_id(identity)
    pin = {**identity, "pin_id": pin_id}
    path = pin_root / "world-pins" / f"{pin_id}.json"
    _write_once(path, pin, conflict_code="WORLD_PIN_IDENTITY_CONFLICT")
    return {**pin, "path": str(path)}


def validate_world_pin(pin_root: Path, *, pin_id: str) -> dict[str, Any]:
    """Recompute the complete stored WorldPin identity before recovery/use."""

    pin_root = pin_root.resolve(strict=True)
    path = pin_root / "world-pins" / f"{pin_id}.json"
    stored = _read_json(path, code="WORLD_PIN_INVALID")
    identity_keys = (
        "schema",
        "activity_id",
        "contact_id",
        "repo",
        "workspace",
        "overlay_manifest",
        "surface_universe",
        "coverage",
        "runtime_identity",
        *_FALSE_AUTHORITY,
    )
    identity = {key: stored.get(key) for key in identity_keys}
    expected = {**identity, "pin_id": pin_id}
    if stored != expected or _stable_id(identity) != pin_id:
        _fail("WORLD_PIN_DIGEST_DRIFT", "stored WorldPin no longer matches its identity")
    return {**stored, "path": str(path)}


def _copy_blob_once(source: Path, destination: Path, expected_sha256: str) -> None:
    if destination.exists():
        if _sha256_file(destination) != expected_sha256:
            _fail("COGNITION_BLOB_COLLISION", f"blob collision: {destination}")
        return
    raw = source.read_bytes()
    if _sha256(raw) != expected_sha256:
        _fail("COGNITION_SOURCE_BLOB_DRIFT", f"source blob digest drift: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            pass
        except OSError:
            if not destination.exists():
                os.replace(temporary, destination)
        if _sha256_file(destination) != expected_sha256:
            _fail("COGNITION_BLOB_COLLISION", f"blob collision after publish: {destination}")
    finally:
        temporary.unlink(missing_ok=True)


def _resolve_source_blob(
    blob_root: Path,
    raw_entry: Mapping[str, Any],
    *,
    digest: str,
    relative_path: str,
) -> Path:
    """Resolve the producer's exact blob path without assuming digest casing.

    The world carrier currently publishes upper-case SHA256 path components,
    while the cognition-object store uses canonical lower-case identities.
    Windows hides that distinction; case-sensitive filesystems do not.  Prefer
    the manifest's exact path, but keep the older root/digest layout readable.
    """

    supplied = raw_entry.get("blob_path")
    if isinstance(supplied, str) and supplied.strip():
        source = Path(supplied).resolve(strict=True)
        if not source.is_relative_to(blob_root):
            _fail(
                "COGNITION_SOURCE_BLOB_PATH_ESCAPE",
                f"source blob escapes its declared store: {relative_path}",
            )
        if (
            source.name.casefold() != digest
            or source.parent.name.casefold() != digest[:2]
        ):
            _fail(
                "COGNITION_SOURCE_BLOB_IDENTITY_DRIFT",
                f"source blob path disagrees with its digest: {relative_path}",
            )
        return source

    candidates = (
        blob_root / digest[:2] / digest,
        blob_root / digest[:2].upper() / digest.upper(),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve(strict=True)
    _fail(
        "COGNITION_SOURCE_BLOB_MISSING",
        f"source blob is absent from its declared store: {relative_path}",
    )


def seal_cognition_object(
    object_root: Path,
    *,
    artifact_manifest_path: Path,
    contact_id: str,
    world_pin_id: str,
    lineage_id: str,
    turn_id: str,
) -> dict[str, Any]:
    """Lift one exact artifact overlay into an activity-scoped byte/tree membrane."""

    if not all(value.strip() for value in (contact_id, world_pin_id, lineage_id, turn_id)):
        _fail("COGNITION_GENERATION_IDENTITY_INVALID", "generation identity must be non-empty")
    object_root = object_root.resolve(strict=False)
    artifact_manifest_path = artifact_manifest_path.resolve(strict=True)
    manifest = _read_json(artifact_manifest_path, code="COGNITION_SOURCE_MANIFEST_INVALID")
    if manifest.get("complete") is not True:
        _fail("COGNITION_SOURCE_MANIFEST_INCOMPLETE", "cannot seal an incomplete artifact tree")
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        _fail("COGNITION_SOURCE_MANIFEST_INVALID", "artifact manifest entries are invalid")
    source_blob_root = Path(str(manifest.get("content_addressed_blob_root", ""))).resolve(strict=True)
    entries: list[dict[str, Any]] = []
    byte_count = 0
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            _fail("COGNITION_SOURCE_MANIFEST_INVALID", "artifact entry is not an object")
        relative = _safe_relative_path(raw.get("relative_path"))
        state_value = str(raw.get("state", ""))
        if state_value == "DELETED":
            entries.append({"path": relative, "state": "DELETED"})
            continue
        if state_value != "PRESENT":
            _fail("COGNITION_SOURCE_MANIFEST_INVALID", f"unsupported artifact state: {state_value}")
        digest = str(raw.get("sha256", "")).casefold()
        size = raw.get("bytes")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            _fail("COGNITION_SOURCE_MANIFEST_INVALID", f"invalid blob digest: {relative}")
        if type(size) is not int or size < 0:
            _fail("COGNITION_SOURCE_MANIFEST_INVALID", f"invalid blob size: {relative}")
        source = _resolve_source_blob(
            source_blob_root,
            raw,
            digest=digest,
            relative_path=relative,
        )
        destination = object_root / "blobs" / "sha256" / digest[:2] / digest
        _copy_blob_once(source, destination, digest)
        if destination.stat().st_size != size:
            _fail("COGNITION_BLOB_SIZE_DRIFT", f"blob size drift: {relative}")
        entries.append({"path": relative, "state": "PRESENT", "sha256": digest, "bytes": size})
        byte_count += size
    entries.sort(key=lambda item: item["path"])
    tree_identity = {"schema": COGNITION_TREE_SCHEMA, "entries": entries}
    root_digest = _stable_id(tree_identity)
    tree = {
        **tree_identity,
        "root_digest": root_digest,
        "file_count": sum(1 for row in entries if row["state"] == "PRESENT"),
        "byte_count": byte_count,
    }
    tree_path = object_root / "trees" / f"{root_digest}.json"
    manifest_digest = _write_once(tree_path, tree, conflict_code="COGNITION_TREE_COLLISION")
    generated_by = {
        "contact_id": contact_id,
        "world_pin_id": world_pin_id,
        "lineage_id": lineage_id,
        "turn_id": turn_id,
    }
    identity = {
        "schema": COGNITION_OBJECT_SCHEMA,
        "root_digest": root_digest,
        "manifest_digest": manifest_digest,
        "file_count": tree["file_count"],
        "byte_count": byte_count,
        "generated_by": generated_by,
        "source_captured_at": manifest.get("captured_at"),
        **_FALSE_AUTHORITY,
    }
    object_id = _stable_id(identity)
    generation = {
        **identity,
        "object_id": object_id,
        "tree_manifest_path": f"trees/{root_digest}.json",
    }
    generation_path = object_root / "generations" / f"{object_id}.json"
    _write_once(generation_path, generation, conflict_code="COGNITION_OBJECT_COLLISION")
    return {**generation, "path": str(generation_path)}


def list_cognition_objects(object_root: Path) -> list[dict[str, Any]]:
    """Return a short navigation map; listing never counts as opening."""

    rows: list[dict[str, Any]] = []
    for path in sorted((object_root.resolve(strict=False) / "generations").glob("*.json")):
        value = _read_json(path, code="COGNITION_OBJECT_INVALID")
        rows.append(
            {
                "object_id": value.get("object_id"),
                "root_digest": value.get("root_digest"),
                "file_count": value.get("file_count"),
                "byte_count": value.get("byte_count"),
                "generated_by": value.get("generated_by"),
            }
        )
    return rows


def open_cognition_object(
    object_root: Path,
    *,
    object_id: str,
    contact_id: str,
    world_pin_id: str,
    requested_paths: Sequence[str],
    destination_root: Path,
) -> dict[str, Any]:
    """Digest-verify and materialize selected bytes, then write the open receipt."""

    if not requested_paths:
        _fail("OBJECT_OPEN_PATHS_EMPTY", "an actual open must request at least one path")
    object_root = object_root.resolve(strict=True)
    destination_root = destination_root.resolve(strict=False)
    generation_path = object_root / "generations" / f"{object_id}.json"
    generation = _read_json(generation_path, code="COGNITION_OBJECT_INVALID")
    if generation.get("object_id") != object_id:
        _fail("COGNITION_OBJECT_IDENTITY_DRIFT", "object generation identity drift")
    immutable_generation = {
        key: generation.get(key)
        for key in (
            "schema",
            "root_digest",
            "manifest_digest",
            "file_count",
            "byte_count",
            "generated_by",
            "source_captured_at",
            *_FALSE_AUTHORITY,
        )
    }
    if _stable_id(immutable_generation) != object_id:
        _fail("COGNITION_OBJECT_DIGEST_DRIFT", "object generation digest verification failed")
    expected_generation = {
        **immutable_generation,
        "object_id": object_id,
        "tree_manifest_path": f"trees/{generation.get('root_digest')}.json",
    }
    if generation != expected_generation:
        _fail("COGNITION_OBJECT_ENVELOPE_DRIFT", "object generation envelope changed")
    tree_relative = _safe_relative_path(generation.get("tree_manifest_path"))
    tree_path = _resolve_contained(object_root, tree_relative)
    if (
        tree_path.parent != object_root / "trees"
        or tree_path.name != f"{generation.get('root_digest')}.json"
    ):
        _fail("COGNITION_TREE_PATH_INVALID", "tree manifest is outside the tree store")
    tree_path = tree_path.resolve(strict=True)
    tree = _read_json(tree_path, code="COGNITION_TREE_INVALID")
    if tree.get("root_digest") != generation.get("root_digest"):
        _fail("COGNITION_TREE_IDENTITY_DRIFT", "tree and generation disagree")
    if _stable_id({"schema": COGNITION_TREE_SCHEMA, "entries": tree.get("entries")}) != tree.get(
        "root_digest"
    ):
        _fail("COGNITION_TREE_DIGEST_DRIFT", "tree digest verification failed")
    if _sha256_file(tree_path) != generation.get("manifest_digest"):
        _fail("COGNITION_TREE_MANIFEST_DIGEST_DRIFT", "tree manifest bytes changed")
    by_path = {
        str(row.get("path")): row
        for row in tree.get("entries", [])
        if isinstance(row, Mapping) and row.get("state") == "PRESENT"
    }
    opened: list[dict[str, Any]] = []
    object_destination = destination_root / object_id
    for supplied in requested_paths:
        relative = _safe_relative_path(supplied)
        row = by_path.get(relative)
        if row is None:
            _fail("OBJECT_OPEN_PATH_NOT_FOUND", f"path is not present in object: {relative}")
        digest = str(row["sha256"])
        source = object_root / "blobs" / "sha256" / digest[:2] / digest
        raw = source.read_bytes()
        if _sha256(raw) != digest or len(raw) != int(row["bytes"]):
            _fail("OBJECT_OPEN_BLOB_DRIFT", f"blob failed verification: {relative}")
        destination = _resolve_contained(object_destination, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != raw:
            _fail("OBJECT_OPEN_DESTINATION_CONFLICT", f"destination already differs: {destination}")
        if not destination.exists():
            _atomic_write(destination, raw)
        opened.append(
            {
                "path": relative,
                "bytes": len(raw),
                "sha256": digest,
                "destination": str(destination),
                "ranges": [[0, len(raw)]],
            }
        )
    identity = {
        "schema": OBJECT_OPEN_SCHEMA,
        "object_id": object_id,
        "contact_id": contact_id,
        "world_pin_id": world_pin_id,
        "verified_root_digest": tree["root_digest"],
        "opened": opened,
        **_FALSE_AUTHORITY,
    }
    receipt_id = _stable_id(identity)
    receipt = {**identity, "receipt_id": receipt_id}
    receipt_path = object_root / "opens" / contact_id / f"{receipt_id}.json"
    receipt["path"] = str(receipt_path)
    _write_once(receipt_path, receipt, conflict_code="OBJECT_OPEN_RECEIPT_COLLISION")
    return receipt


def reconcile_carrier_truth(
    *,
    job_state: str,
    child_liveness: str,
    lease_status: str,
    turn_phase: str,
    stop_requested: bool = False,
) -> dict[str, Any]:
    """Pure restart-equivalent law for Job/process/lease/projection truth."""

    job_state = str(job_state)
    child_liveness = str(child_liveness)
    lease_status = str(lease_status)
    turn_phase = str(turn_phase)
    if job_state not in {"PRESENT_NONEMPTY", "PRESENT_EMPTY", "ABSENT", "UNKNOWN", "UNAVAILABLE"}:
        _fail("CARRIER_TRUTH_INVALID", f"unsupported Job state: {job_state}")
    if child_liveness not in {"ALIVE", "DEAD", "UNKNOWN"}:
        _fail("CARRIER_TRUTH_INVALID", f"unsupported child liveness: {child_liveness}")
    if lease_status not in {"RESERVED", "BOUND", "RELEASED"}:
        _fail("CARRIER_TRUTH_INVALID", f"unsupported lease state: {lease_status}")
    if turn_phase not in {"TURN_RUNNING", "TURN_SEALING", "TERMINAL"}:
        _fail("CARRIER_TRUTH_INVALID", f"unsupported turn phase: {turn_phase}")

    contradictory = job_state in {"PRESENT_EMPTY", "ABSENT"} and child_liveness == "ALIVE"
    unknown = job_state == "UNKNOWN" or (
        job_state in {"PRESENT_EMPTY", "ABSENT", "UNAVAILABLE"}
        and child_liveness == "UNKNOWN"
    )
    carrier_alive = job_state == "PRESENT_NONEMPTY" or (
        job_state == "UNAVAILABLE" and child_liveness == "ALIVE"
    )
    carrier_dead = (
        job_state in {"PRESENT_EMPTY", "ABSENT"} and child_liveness == "DEAD"
    ) or (job_state == "UNAVAILABLE" and child_liveness == "DEAD")
    if contradictory:
        action = "HOLD_CONTRADICTORY"
        next_phase = "RUNNING_UNKNOWN" if turn_phase == "TURN_RUNNING" else turn_phase
        release_allowed = False
        duplicate_launch_allowed = False
        capture_required = False
        ordered_actions: list[str] = []
    elif unknown:
        action = "HOLD_UNKNOWN"
        next_phase = "RUNNING_UNKNOWN" if turn_phase == "TURN_RUNNING" else turn_phase
        release_allowed = False
        duplicate_launch_allowed = False
        capture_required = False
        ordered_actions = []
    elif carrier_alive:
        action = "TERMINATE_EXACT_JOB" if stop_requested else "WAIT_FOR_CARRIER"
        next_phase = "STOPPING" if stop_requested else "TURN_RUNNING"
        release_allowed = False
        duplicate_launch_allowed = False
        capture_required = False
        ordered_actions = ["TERMINATE_EXACT_JOB"] if stop_requested else []
    elif carrier_dead:
        if turn_phase == "TERMINAL" and lease_status == "RELEASED":
            action = "ALREADY_TERMINAL"
            next_phase = "TERMINAL"
            release_allowed = False
            duplicate_launch_allowed = True
            capture_required = False
            ordered_actions = []
        else:
            release_required = lease_status in {"RESERVED", "BOUND"}
            release_allowed = release_required and turn_phase == "TERMINAL"
            action = "SEAL_AND_RELEASE" if release_required else "SEAL_RELEASE_ALREADY_DONE"
            next_phase = "TERMINAL" if turn_phase == "TERMINAL" else "TURN_SEALING"
            duplicate_launch_allowed = False
            capture_required = turn_phase != "TERMINAL"
            ordered_actions = []
            if turn_phase == "TURN_RUNNING":
                ordered_actions.append("ENTER_TURN_SEALING")
            if capture_required:
                ordered_actions.extend(["CAPTURE_TERMINAL_ARTIFACTS", "WRITE_TURN_RECEIPT"])
            if release_required:
                ordered_actions.append("RELEASE_EXACT_LEASE")
            ordered_actions.append("COMMIT_LINEAGE_TRANSITION")
    else:
        _fail("CARRIER_TRUTH_INVALID", "carrier truth does not map to a mechanical state")
    return {
        "schema": TERMINAL_RECONCILIATION_SCHEMA,
        "job_state": job_state,
        "child_liveness": child_liveness,
        "lease_status": lease_status,
        "prior_turn_phase": turn_phase,
        "stop_requested": bool(stop_requested),
        "action": action,
        "next_turn_phase": next_phase,
        "capture_required": capture_required,
        "release_allowed": release_allowed,
        "duplicate_launch_allowed": duplicate_launch_allowed,
        "ordered_actions": ordered_actions,
        **_FALSE_AUTHORITY,
    }


def build_live_contact_prompt(
    *,
    activity_id: str,
    contact_id: str,
    world_pin: Mapping[str, Any],
    object_map_path: Path,
    object_open_command: str | None = None,
) -> str:
    """Build a thin provenance envelope without selecting the research method."""

    lines = [
        "You are the fresh Research Sol for the currently open XINAO research activity.",
        "",
        f"Activity identity: {activity_id}",
        f"Contact identity: {contact_id}",
        f"World pin identity: {world_pin.get('pin_id')}",
        f"World pin path: {world_pin.get('path')}",
        f"Prior cognition-object map: {object_map_path}",
        "",
        "S is only delivering you into the exact world named by that mechanical pin.",
        "The envelope is provenance, not a scientific interpretation or research workflow.",
        "Reconstruct the relevant world from the repository, mounted runtime reality, lineage/artifact indexes, and deep evidence as needed.",
        "You own representation, question formation, research method, and local cognition.",
        "Code, Python, simulation, web/external search, and additional neural computation are limbs when the research warrants them.",
        "Arbitrary research artifacts may be created inside this isolated lineage workspace.",
        "Shared production/effect/adoption and parent-completion authority are not granted.",
    ]
    if object_open_command:
        lines.extend(
            [
                "",
                "The object map is navigation only.  If a prior exact tree matters, open it with the digest-verifying tool:",
                object_open_command,
                "Listing or mentioning an object does not count as opening it.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research Sol exact-tree navigation tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list-objects")
    list_parser.add_argument("--object-root", type=Path, required=True)
    open_parser = subparsers.add_parser("open-object")
    open_parser.add_argument("--object-root", type=Path, required=True)
    open_parser.add_argument("--object-id", required=True)
    open_parser.add_argument("--contact-id", required=True)
    open_parser.add_argument("--world-pin-id", required=True)
    open_parser.add_argument("--destination-root", type=Path, required=True)
    open_parser.add_argument("--path", dest="paths", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "list-objects":
            result: object = list_cognition_objects(args.object_root)
        else:
            result = open_cognition_object(
                args.object_root,
                object_id=args.object_id,
                contact_id=args.contact_id,
                world_pin_id=args.world_pin_id,
                requested_paths=args.paths,
                destination_root=args.destination_root,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ResearchSolRuntimeError as exc:
        print(json.dumps({"outcome": "FAILED", "reason_code": exc.reason_code, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
