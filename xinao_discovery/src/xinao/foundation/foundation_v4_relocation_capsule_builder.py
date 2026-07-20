"""Build one deterministic source-only relocation capsule for F4.

The builder consumes a sealed foundation closure and a separately sealed F4
evidence snapshot.  It does not execute assertion actuals, probe a Python
runtime, rebuild authority/snapshot state, or consult a historical capsule.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_bundle_runner import PROTOCOL_VERSION, REQUEST_SCHEMA_VERSION
from xinao.foundation.assertion_verifier_registry import (
    AUTHORITY_MANIFEST_FILENAME,
    AUTHORITY_MANIFEST_SCHEMA_VERSION,
    AUTHORITY_SEAL_POLICY_ID,
    RUNTIME_BUILDINFO_FILENAME,
    RUNTIME_BUILDINFO_SCHEMA_VERSION,
    validate_authority_snapshot,
)
from xinao.foundation.f4_evidence_snapshot import (
    MANIFEST_NAME as SNAPSHOT_MANIFEST_NAME,
)
from xinao.foundation.f4_evidence_snapshot import (
    SCHEMA_VERSION as SNAPSHOT_SCHEMA_VERSION,
)
from xinao.foundation.f4_evidence_snapshot import (
    verify_snapshot_manifest,
)

F4_BLOCK_ID = "F4_research_factory"
CAPSULE_SCHEMA_VERSION = "xinao.foundation_v4_relocation_source_capsule.v1"
BUILD_RECEIPT_SCHEMA_VERSION = "xinao.foundation_v4_relocation_capsule_build_receipt.v1"

F4_INPUT_NAMES = (
    "active_quote_projection_sha256",
    "baseline_sha256",
    "compiler_code_sha256",
    "compiler_config_sha256",
    "dataset_sha256",
    "f3_external_synthesis_sha256",
    "f3_prior_draft_sha256",
    "f3_service_graph_sha256",
    "play_catalog_sha256",
    "rule_semantic_map_sha256",
)
F4_ARTIFACT_NAMES = (
    "DedupPolicyVersion",
    "DeterministicFanInPolicyVersion",
    "DynamicCapacityPolicyVersion",
    "EvidenceSchemaVersion",
    "ResearchFactoryCanaryReport",
    "ResearchWorkItemSchemaVersion",
    "TypedHandoffSchemaVersion",
    "ValidationCourtInterfaceVersion",
)
F4_ASSERTION_IDS = (
    "backpressure_partial_failure_cancel_and_recovery_verified",
    "canonical_work_key_and_source_dependency_dedup_verified",
    "codex_single_writer_boundary_verified",
    "d_drive_evidence_binding_verified",
    "deterministic_fan_in_without_majority_vote_verified",
    "dynamic_multi_lane_capacity_ladder_verified",
    "fixed_time_split_and_leakage_rejection_verified",
    "independent_critique_verified",
    "negative_controls_and_error_budget_verified",
    "open_method_typed_admission_verified",
    "real_model_identity_and_lane_artifacts_verified",
    "real_temporal_workflow_history_verified",
    "research_portfolio_ready_frontier_verified",
    "typed_handoff_and_evidence_schemas_verified",
)

_F4_RUNTIME_PROFILES = frozenset({"f4_dual_brain_runtime", "xinao_assertion_runtime"})
_F4_SNAPSHOT_ROOTS = frozenset(
    {
        "closure_f4_artifacts",
        "closure_inputs",
        "current_source",
        "independent_support",
        "live_pack",
        "negative_pack",
        "portfolio_pack",
    }
)
_F4_SNAPSHOT_FILES = frozenset({"file/closure_authority_manifest", "file/closure_f4_request"})
_F4_UNRESOLVED = frozenset(
    {
        ("/last_decision/frontier_ref", "invalid_local_identity"),
        ("/last_state_ref", "missing_local_target"),
    }
)
_LEGACY_OUTPUT_NAMES = frozenset(
    {
        "assertion_bundles",
        "fresh_assertion_bundles",
        "fresh_assertion_bundle_receipts",
        "assertions",
        "artifacts",
        "foundation_closure_report.json",
        "foundation_closure_report_input.json",
        "foundation_closure_verification.json",
        "foundation_closure_pack.json",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OPERATION_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")


class RelocationCapsuleBuildError(ValueError):
    """Raised when an input cannot produce one exact F4 source capsule."""


@dataclass(frozen=True, slots=True)
class CapsuleBuildResult:
    output_root: Path
    foundation_root: Path
    capsule_manifest_path: Path
    build_receipt_path: Path
    capsule_manifest_sha256: str
    payload_exact_inventory_sha256: str
    payload_file_count: int
    payload_total_size_bytes: int


@dataclass(frozen=True, slots=True)
class BoundSource:
    kind: str
    name: str
    recorded_path: str
    source_path: Path
    destination: PurePosixPath
    sha256: str
    size_bytes: int
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PayloadRow:
    relative_path: str
    sha256: str
    size_bytes: int
    roles: tuple[str, ...]
    source_path: str


@dataclass(frozen=True, slots=True)
class AuthorityAdmission:
    root: Path
    manifest_path: Path
    manifest: Mapping[str, Any]
    manifest_raw: bytes
    runtime_buildinfo: Mapping[str, Any]
    runtime_buildinfo_path: Path
    actuals: Mapping[str, Any]
    copy_items: tuple[BoundSource, ...]


@dataclass(frozen=True, slots=True)
class AdmittedClosure:
    root: Path
    created_at: str
    pack: Mapping[str, Any]
    pack_path: Path
    pack_raw: bytes
    report_input: Mapping[str, Any]
    request: Mapping[str, Any]
    request_path: Path
    request_raw: bytes
    request_item: BoundSource
    authority: AuthorityAdmission
    blueprint: BoundSource
    bindings: tuple[BoundSource, ...]


@dataclass(frozen=True, slots=True)
class AdmittedSnapshot:
    root: Path
    manifest: Mapping[str, Any]
    manifest_path: Path
    manifest_raw: bytes
    copy_items: tuple[BoundSource, ...]


def _require(condition: object, message: str) -> None:
    if not condition:
        raise RelocationCapsuleBuildError(message)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _paths_overlap(left: Path, right: Path) -> bool:
    left_key = _absolute(left)
    right_key = _absolute(right)
    try:
        left_key.relative_to(right_key)
    except ValueError:
        pass
    else:
        return True
    try:
        right_key.relative_to(left_key)
    except ValueError:
        return False
    return True


def _is_reparse(path: Path) -> bool:
    info = os.lstat(path)
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _assert_no_lexical_reparse(
    path: Path,
    *,
    label: str,
    allow_missing_leaf: bool = False,
) -> Path:
    candidate = _absolute(path)
    parts = candidate.parts
    _require(bool(parts), f"{label} path is empty")
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current /= part
        try:
            exists = current.exists() or current.is_symlink()
        except OSError as exc:
            raise RelocationCapsuleBuildError(
                f"{label} path cannot be inspected: {current}"
            ) from exc
        if not exists:
            if allow_missing_leaf and index == len(parts) - 1:
                return candidate
            raise RelocationCapsuleBuildError(f"{label} path is missing: {current}")
        try:
            if _is_reparse(current):
                raise RelocationCapsuleBuildError(
                    f"{label} path contains a reparse component: {current}"
                )
        except OSError as exc:
            raise RelocationCapsuleBuildError(
                f"{label} path cannot be inspected: {current}"
            ) from exc
    return candidate


def _existing_directory(path: Path, *, label: str) -> Path:
    candidate = _assert_no_lexical_reparse(path, label=label)
    _require(candidate.is_dir(), f"{label} is not a directory: {candidate}")
    return candidate


def _existing_file(path: Path, *, label: str) -> Path:
    candidate = _assert_no_lexical_reparse(path, label=label)
    _require(candidate.is_file(), f"{label} is not a regular file: {candidate}")
    return candidate


def _safe_relative(value: object, *, label: str) -> PurePosixPath:
    _require(isinstance(value, str) and bool(value) and "\\" not in value, f"{label} is invalid")
    path = PurePosixPath(str(value))
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} and ":" not in part for part in path.parts),
        f"{label} escapes its root: {value}",
    )
    return path


def _validate_destination(path: PurePosixPath) -> None:
    relative = _safe_relative(path.as_posix(), label="capsule destination")
    first = relative.parts[0]
    _require(first not in _LEGACY_OUTPUT_NAMES, f"reserved legacy destination: {relative}")
    _require(relative.as_posix() != "capsule_manifest.json", "payload cannot replace manifest")
    _require(
        all(part.casefold() != "__pycache__" for part in relative.parts),
        f"capsule destination contains a cache directory: {relative}",
    )
    _require(
        relative.suffix.casefold() not in {".pyc", ".pyo"},
        f"capsule destination contains bytecode: {relative}",
    )


def _inside(path: Path, root: Path) -> PurePosixPath:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RelocationCapsuleBuildError(f"path escaped expected root: {path} / {root}") from exc
    _require(relative.parts, f"path identifies a directory rather than a retained file: {path}")
    return _safe_relative(relative.as_posix(), label="retained source relative path")


def _load_json_object(
    path: Path,
    *,
    label: str,
    require_canonical: bool = False,
) -> tuple[dict[str, Any], bytes]:
    source = _existing_file(path, label=label)
    try:
        raw = source.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RelocationCapsuleBuildError(f"{label} is not valid UTF-8 JSON: {source}") from exc
    _require(isinstance(value, dict), f"{label} is not a JSON object")
    if require_canonical:
        _require(canonical_dumps(value) == raw, f"{label} is not canonical JSON")
    return value, raw


def _sha256_value(value: object, *, label: str) -> str:
    _require(isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None, f"{label} invalid")
    return str(value)


def _size_value(value: object, *, label: str, positive: bool = False) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= (1 if positive else 0),
        f"{label} invalid",
    )
    return int(value)


def _verify_file_identity(
    path: Path,
    *,
    expected_sha256: object,
    expected_size: object,
    label: str,
) -> tuple[Path, str, int]:
    source = _existing_file(path, label=label)
    digest = _sha256_value(expected_sha256, label=f"{label} sha256")
    size = _size_value(expected_size, label=f"{label} size")
    raw = source.read_bytes()
    _require(len(raw) == size and _sha256_bytes(raw) == digest, f"{label} identity drifted")
    return source, digest, size


def _recorded_ref(
    raw: object,
    *,
    label: str,
    exact_keys: set[str],
) -> tuple[str, Path, str, int, Mapping[str, Any]]:
    _require(
        isinstance(raw, Mapping) and set(raw) == exact_keys, f"{label} reference shape drifted"
    )
    recorded = raw.get("path")
    _require(isinstance(recorded, str) and bool(recorded), f"{label} recorded path invalid")
    source_path = Path(recorded)
    _require(source_path.is_absolute(), f"{label} recorded path is not absolute")
    source, digest, size = _verify_file_identity(
        source_path,
        expected_sha256=raw.get("sha256"),
        expected_size=raw.get("size_bytes"),
        label=label,
    )
    return recorded, source, digest, size, raw


def _admit_runtime_buildinfo(
    *,
    authority_root: Path,
    authority_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], Path]:
    runtime_ref = authority_manifest.get("runtime_buildinfo_ref")
    _require(
        isinstance(runtime_ref, Mapping)
        and set(runtime_ref) == {"relative_path", "sha256", "size"}
        and runtime_ref.get("relative_path") == RUNTIME_BUILDINFO_FILENAME,
        "authority runtime buildinfo binding drifted",
    )
    runtime_path, _, _ = _verify_file_identity(
        authority_root / RUNTIME_BUILDINFO_FILENAME,
        expected_sha256=runtime_ref.get("sha256"),
        expected_size=runtime_ref.get("size"),
        label="authority runtime buildinfo",
    )
    runtime, runtime_raw = _load_json_object(
        runtime_path,
        label="authority runtime buildinfo",
        require_canonical=True,
    )
    _require(
        set(runtime) == {"schema_version", "runtimes", "content_sha256"}
        and runtime.get("schema_version") == RUNTIME_BUILDINFO_SCHEMA_VERSION,
        "runtime buildinfo shape drifted",
    )
    runtime_core = dict(runtime)
    content_hash = runtime_core.pop("content_sha256", None)
    _require(
        _sha256_value(content_hash, label="runtime buildinfo content sha256")
        == canonical_sha256(runtime_core),
        "runtime buildinfo content drifted",
    )
    _require(_sha256_bytes(runtime_raw) == runtime_ref["sha256"], "runtime buildinfo file drifted")
    profiles = runtime.get("runtimes")
    _require(
        isinstance(profiles, Mapping) and set(profiles) == _F4_RUNTIME_PROFILES,
        "runtime profile inventory drifted",
    )
    projection_hashes: dict[str, str] = {}
    for profile_name in sorted(_F4_RUNTIME_PROFILES):
        profile = profiles[profile_name]
        _require(
            isinstance(profile, Mapping)
            and set(profile) == {"interpreter", "distribution_projection"},
            f"runtime profile shape drifted: {profile_name}",
        )
        interpreter = profile["interpreter"]
        _require(
            isinstance(interpreter, Mapping)
            and set(interpreter)
            == {
                "executable_path",
                "executable_sha256",
                "executable_size",
                "implementation",
                "version",
                "cache_tag",
            },
            f"runtime interpreter shape drifted: {profile_name}",
        )
        executable_path = interpreter.get("executable_path")
        _require(
            isinstance(executable_path, str)
            and bool(executable_path)
            and Path(executable_path).is_absolute(),
            f"runtime interpreter path invalid: {profile_name}",
        )
        _sha256_value(interpreter.get("executable_sha256"), label="runtime executable sha256")
        _size_value(
            interpreter.get("executable_size"), label="runtime executable size", positive=True
        )
        _require(
            all(
                isinstance(interpreter.get(key), str) and bool(interpreter.get(key))
                for key in ("implementation", "version", "cache_tag")
            ),
            f"runtime interpreter semantics invalid: {profile_name}",
        )
        projection = profile["distribution_projection"]
        _require(
            isinstance(projection, Mapping)
            and set(projection)
            == {"roots", "resolver_distribution", "distributions", "projection_sha256"},
            f"runtime dependency projection shape drifted: {profile_name}",
        )
        roots = projection.get("roots")
        distributions = projection.get("distributions")
        _require(
            isinstance(roots, list)
            and bool(roots)
            and all(isinstance(item, str) and bool(item) for item in roots)
            and len(roots) == len(set(roots))
            and isinstance(projection.get("resolver_distribution"), Mapping)
            and isinstance(distributions, list)
            and bool(distributions),
            f"runtime dependency projection invalid: {profile_name}",
        )
        projection_core = dict(projection)
        projection_hash = projection_core.pop("projection_sha256", None)
        _require(
            _sha256_value(projection_hash, label="runtime dependency projection sha256")
            == canonical_sha256(projection_core),
            f"runtime dependency projection drifted: {profile_name}",
        )
        projection_hashes[profile_name] = str(projection_hash)
    _require(
        len(set(projection_hashes.values())) == len(projection_hashes),
        "runtime dependency profiles collapsed",
    )
    return runtime, runtime_path


def _admit_authority(authority_manifest_path: Path) -> AuthorityAdmission:
    manifest_path = _existing_file(authority_manifest_path, label="authority manifest")
    try:
        validated = validate_authority_snapshot(manifest_path, require_live_match=False)
    except Exception as exc:
        raise RelocationCapsuleBuildError(f"authority validation failed: {exc}") from exc
    _require(isinstance(validated, Mapping), "authority validator returned no manifest")
    manifest, manifest_raw = _load_json_object(
        manifest_path,
        label="authority manifest",
        require_canonical=True,
    )
    _require(manifest == validated, "authority validator result drifted from manifest")
    _require(
        set(manifest)
        == {
            "schema_version",
            "policy_id",
            "registry",
            "entries",
            "source_tree_sha256",
            "runtime_buildinfo_ref",
            "authority_tree_sha256",
            "content_sha256",
        }
        and manifest.get("schema_version") == AUTHORITY_MANIFEST_SCHEMA_VERSION
        and manifest.get("policy_id") == AUTHORITY_SEAL_POLICY_ID,
        "authority manifest shape drifted",
    )
    authority_root = manifest_path.parent
    runtime, runtime_path = _admit_runtime_buildinfo(
        authority_root=authority_root,
        authority_manifest=manifest,
    )
    registry = manifest.get("registry")
    _require(isinstance(registry, Mapping), "authority registry is absent")
    f4_registry = registry.get(F4_BLOCK_ID)
    _require(
        isinstance(f4_registry, Mapping)
        and set(f4_registry)
        == {
            "module_name",
            "relative_source",
            "checker_version",
            "source_sha256",
            "checker_id",
        },
        "authority F4 registry binding drifted",
    )
    expected_relative_source = "xinao/foundation/assertion_verifiers/f4_assertion_actuals.py"
    source_sha256 = _sha256_value(
        f4_registry.get("source_sha256"),
        label="authority F4 source sha256",
    )
    _require(
        f4_registry.get("relative_source") == expected_relative_source
        and f4_registry.get("module_name")
        == "xinao.foundation.assertion_verifiers.f4_assertion_actuals"
        and f4_registry.get("checker_version") == "xinao.foundation.assertion_actuals.f4.v1"
        and f4_registry.get("checker_id") == f"xinao.canonical.{F4_BLOCK_ID}.{source_sha256}",
        "authority F4 registry identity drifted",
    )
    expected_entry_path = f"xinao_discovery/src/{expected_relative_source}"
    entries = manifest.get("entries")
    _require(isinstance(entries, list) and bool(entries), "authority entries are absent")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("relative_path") == expected_entry_path
    ]
    _require(len(matches) == 1, "authority F4 source entry is not unique")
    f4_entry = matches[0]
    _require(
        set(f4_entry) == {"role", "relative_path", "sha256", "size"}
        and f4_entry.get("sha256") == source_sha256,
        "authority F4 source entry drifted",
    )
    actuals_path, _, actuals_size = _verify_file_identity(
        authority_root / "sources" / Path(*PurePosixPath(expected_entry_path).parts),
        expected_sha256=source_sha256,
        expected_size=f4_entry.get("size"),
        label="authority F4 actuals source",
    )

    copy_items: list[BoundSource] = [
        BoundSource(
            kind="authority",
            name=AUTHORITY_MANIFEST_FILENAME,
            recorded_path=str(manifest_path),
            source_path=manifest_path,
            destination=PurePosixPath("authority_snapshot") / AUTHORITY_MANIFEST_FILENAME,
            sha256=_sha256_bytes(manifest_raw),
            size_bytes=len(manifest_raw),
            roles=("authority_snapshot_file",),
        ),
        BoundSource(
            kind="authority",
            name=RUNTIME_BUILDINFO_FILENAME,
            recorded_path=str(runtime_path),
            source_path=runtime_path,
            destination=PurePosixPath("authority_snapshot") / RUNTIME_BUILDINFO_FILENAME,
            sha256=_sha256_file(runtime_path),
            size_bytes=runtime_path.stat().st_size,
            roles=("authority_snapshot_file",),
        ),
    ]
    for entry in entries:
        _require(
            isinstance(entry, Mapping)
            and set(entry) == {"role", "relative_path", "sha256", "size"},
            "authority source entry shape drifted",
        )
        relative = _safe_relative(entry.get("relative_path"), label="authority source path")
        source, digest, size = _verify_file_identity(
            authority_root / "sources" / Path(*relative.parts),
            expected_sha256=entry.get("sha256"),
            expected_size=entry.get("size"),
            label=f"authority source {relative}",
        )
        copy_items.append(
            BoundSource(
                kind="authority",
                name=relative.as_posix(),
                recorded_path=str(source),
                source_path=source,
                destination=PurePosixPath("authority_snapshot/sources") / relative,
                sha256=digest,
                size_bytes=size,
                roles=("authority_snapshot_file",),
            )
        )
    actuals = {
        "module_relative_path": expected_entry_path,
        "module_sha256": source_sha256,
        "checker_id": f4_registry["checker_id"],
        "checker_version": f4_registry["checker_version"],
        "expected_actual_id_count": len(F4_ASSERTION_IDS),
        "expected_actual_ids": list(F4_ASSERTION_IDS),
        "module_size_bytes": actuals_size,
        "copied_source_path": str(actuals_path),
    }
    return AuthorityAdmission(
        root=authority_root,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_raw=manifest_raw,
        runtime_buildinfo=runtime,
        runtime_buildinfo_path=runtime_path,
        actuals=actuals,
        copy_items=tuple(copy_items),
    )


def _admit_request(
    request_path: Path,
    *,
    closure_root: Path,
    authority: AuthorityAdmission,
) -> tuple[dict[str, Any], bytes, BoundSource, tuple[BoundSource, ...]]:
    request, request_raw = _load_json_object(
        request_path,
        label="F4 assertion request",
        require_canonical=True,
    )
    _require(
        set(request)
        == {
            "schema_version",
            "protocol_version",
            "block_id",
            "assertion_ids",
            "input_evidence",
            "input_hashes",
            "artifacts",
            "compiler_code_sha256",
            "compiler_config_sha256",
        }
        and request.get("schema_version") == REQUEST_SCHEMA_VERSION
        and request.get("protocol_version") == PROTOCOL_VERSION
        and request.get("block_id") == F4_BLOCK_ID,
        "F4 assertion request shape drifted",
    )
    assertion_ids = request.get("assertion_ids")
    _require(
        isinstance(assertion_ids, list) and tuple(assertion_ids) == F4_ASSERTION_IDS,
        "F4 assertion inventory drifted",
    )
    input_evidence = request.get("input_evidence")
    input_hashes = request.get("input_hashes")
    artifacts = request.get("artifacts")
    _require(
        isinstance(input_evidence, Mapping)
        and tuple(sorted(input_evidence)) == F4_INPUT_NAMES
        and isinstance(input_hashes, Mapping)
        and tuple(sorted(input_hashes)) == F4_INPUT_NAMES
        and isinstance(artifacts, Mapping)
        and tuple(sorted(artifacts)) == F4_ARTIFACT_NAMES,
        "F4 request transport inventory drifted",
    )
    input_root = _existing_directory(
        closure_root / "source_materials" / "inputs",
        label="closure input namespace",
    )
    artifact_root = _existing_directory(
        closure_root / "source_materials" / "artifacts" / F4_BLOCK_ID,
        label="closure artifact namespace",
    )
    bindings: list[BoundSource] = []
    for name in F4_INPUT_NAMES:
        recorded, source, digest, size, row = _recorded_ref(
            input_evidence[name],
            label=f"F4 input {name}",
            exact_keys={"input_hash_key", "path", "sha256", "size_bytes"},
        )
        _require(
            row.get("input_hash_key") == name and input_hashes.get(name) == digest,
            f"F4 input hash binding drifted: {name}",
        )
        if name == "compiler_code_sha256":
            _require(
                _path_key(source) == _path_key(authority.manifest_path),
                "compiler code input does not identify closure authority",
            )
            destination = PurePosixPath("authority_snapshot") / AUTHORITY_MANIFEST_FILENAME
        else:
            try:
                relative = _inside(source, input_root)
            except RelocationCapsuleBuildError as exc:
                raise RelocationCapsuleBuildError(
                    f"F4 input escaped closure input namespace: {name}"
                ) from exc
            destination = PurePosixPath("source_materials/inputs") / relative
        bindings.append(
            BoundSource(
                kind="input",
                name=name,
                recorded_path=recorded,
                source_path=source,
                destination=destination,
                sha256=digest,
                size_bytes=size,
                roles=(f"request_input:{name}",),
            )
        )
    _require(
        request.get("compiler_code_sha256") == input_hashes["compiler_code_sha256"]
        and request.get("compiler_config_sha256") == input_hashes["compiler_config_sha256"],
        "F4 request compiler hash binding drifted",
    )
    for artifact_type in F4_ARTIFACT_NAMES:
        wrapper = artifacts[artifact_type]
        _require(
            isinstance(wrapper, Mapping)
            and set(wrapper) == {"staged_envelope", "staged_envelope_content_sha256"},
            f"F4 artifact wrapper drifted: {artifact_type}",
        )
        envelope = wrapper["staged_envelope"]
        _require(
            isinstance(envelope, Mapping)
            and set(envelope)
            == {
                "artifact_type",
                "version",
                "input_hashes",
                "code_hash",
                "config_hash",
                "source_ref",
                "payload",
                "payload_sha256",
            },
            f"F4 artifact envelope drifted: {artifact_type}",
        )
        _require(
            envelope.get("artifact_type") == artifact_type
            and isinstance(envelope.get("version"), str)
            and bool(envelope.get("version"))
            and envelope.get("input_hashes") == input_hashes
            and envelope.get("code_hash") == request["compiler_code_sha256"]
            and envelope.get("config_hash") == request["compiler_config_sha256"]
            and envelope.get("payload_sha256") == canonical_sha256(envelope.get("payload"))
            and wrapper.get("staged_envelope_content_sha256") == canonical_sha256(envelope),
            f"F4 artifact content binding drifted: {artifact_type}",
        )
        recorded, source, digest, size, source_ref = _recorded_ref(
            envelope.get("source_ref"),
            label=f"F4 artifact source {artifact_type}",
            exact_keys={"artifact_type", "path", "sha256", "size_bytes"},
        )
        _require(
            source_ref.get("artifact_type") == artifact_type,
            f"F4 artifact source type drifted: {artifact_type}",
        )
        try:
            relative = _inside(source, artifact_root)
        except RelocationCapsuleBuildError as exc:
            raise RelocationCapsuleBuildError(
                f"F4 artifact escaped closure artifact namespace: {artifact_type}"
            ) from exc
        bindings.append(
            BoundSource(
                kind="artifact",
                name=artifact_type,
                recorded_path=recorded,
                source_path=source,
                destination=PurePosixPath(f"source_materials/artifacts/{F4_BLOCK_ID}") / relative,
                sha256=digest,
                size_bytes=size,
                roles=(f"request_artifact:{artifact_type}",),
            )
        )
    request_item = BoundSource(
        kind="request",
        name=F4_BLOCK_ID,
        recorded_path=str(request_path),
        source_path=request_path,
        destination=PurePosixPath(f"assertion_requests/{F4_BLOCK_ID}.json"),
        sha256=_sha256_bytes(request_raw),
        size_bytes=len(request_raw),
        roles=("assertion_request",),
    )
    return request, request_raw, request_item, tuple(bindings)


def _admit_closure(closure_root: Path, *, block_id: str) -> AdmittedClosure:
    _require(block_id == F4_BLOCK_ID, f"unsupported foundation block: {block_id}")
    root = _existing_directory(closure_root, label="closure root")
    pack_path = root / "foundation_closure_pack.json"
    pack, pack_raw = _load_json_object(pack_path, label="foundation closure pack")
    _require(
        pack.get("schema_version") == "xinao.foundation_closure_pack.v4", "closure schema drifted"
    )
    pack_core = dict(pack)
    pack_hash = pack_core.pop("pack_sha256", None)
    _require(
        _sha256_value(pack_hash, label="closure pack sha256") == canonical_sha256(pack_core),
        "closure pack content drifted",
    )
    _require(
        pack.get("foundation_closed") is True
        and pack.get("source_materials_self_contained") is True,
        "closure is not a self-contained closed foundation",
    )
    report_input, _ = _load_json_object(
        root / "foundation_closure_report_input.json",
        label="foundation closure report input",
    )
    created_at = report_input.get("created_at")
    _require(isinstance(created_at, str) and bool(created_at), "closure created_at is absent")
    authority_path = root / "authority_snapshot" / AUTHORITY_MANIFEST_FILENAME
    authority = _admit_authority(authority_path)
    for field in ("authority_snapshot_manifest_ref", "compiler_code_manifest_ref"):
        _, source, digest, size, _ = _recorded_ref(
            pack.get(field),
            label=f"closure {field}",
            exact_keys={"path", "sha256", "size_bytes"},
        )
        _require(
            _path_key(source) == _path_key(authority.manifest_path)
            and digest == _sha256_bytes(authority.manifest_raw)
            and size == len(authority.manifest_raw),
            f"closure {field} does not bind its authority",
        )
    request_path = root / "assertion_requests" / f"{F4_BLOCK_ID}.json"
    request, request_raw, request_item, request_bindings = _admit_request(
        request_path,
        closure_root=root,
        authority=authority,
    )
    _require(
        report_input.get("input_hashes") == request.get("input_hashes")
        and report_input.get("code_hash") == request.get("compiler_code_sha256")
        and report_input.get("config_hash") == request.get("compiler_config_sha256"),
        "closure report input drifted from F4 request",
    )
    blueprint_ref = pack.get("blueprint_ref")
    _require(blueprint_ref == report_input.get("blueprint_ref"), "closure blueprint refs disagree")
    recorded, blueprint_path, blueprint_hash, blueprint_size, _ = _recorded_ref(
        blueprint_ref,
        label="closure blueprint",
        exact_keys={"path", "sha256", "size_bytes"},
    )
    blueprint = BoundSource(
        kind="blueprint",
        name="canonical_blueprint",
        recorded_path=recorded,
        source_path=blueprint_path,
        destination=PurePosixPath("blueprint/blueprint.json"),
        sha256=blueprint_hash,
        size_bytes=blueprint_size,
        roles=("canonical_blueprint",),
    )
    return AdmittedClosure(
        root=root,
        created_at=created_at,
        pack=pack,
        pack_path=pack_path,
        pack_raw=pack_raw,
        report_input=report_input,
        request=request,
        request_path=request_path,
        request_raw=request_raw,
        request_item=request_item,
        authority=authority,
        blueprint=blueprint,
        bindings=(*request_bindings, blueprint),
    )


def admit_f4_closure(closure_root: Path) -> AdmittedClosure:
    """Validate one self-contained F4 closure for downstream carriers."""

    return _admit_closure(closure_root, block_id=F4_BLOCK_ID)


def _admit_snapshot(snapshot_root: Path) -> AdmittedSnapshot:
    root = _existing_directory(snapshot_root, label="snapshot root")
    manifest_path = root / SNAPSHOT_MANIFEST_NAME
    try:
        validated = verify_snapshot_manifest(manifest_path)
    except Exception as exc:
        raise RelocationCapsuleBuildError(f"snapshot validation failed: {exc}") from exc
    _require(isinstance(validated, Mapping), "snapshot validator returned no manifest")
    manifest, manifest_raw = _load_json_object(manifest_path, label="snapshot manifest")
    _require(manifest == validated, "snapshot validator result drifted from manifest")
    _require(manifest.get("schema_version") == SNAPSHOT_SCHEMA_VERSION, "snapshot schema drifted")
    _require(
        manifest.get("required_reference_match_count") == 14,
        "F4 snapshot required reference match count drifted",
    )
    logical_ref_count = manifest.get("logical_ref_count")
    _require(
        isinstance(logical_ref_count, int)
        and manifest.get("reachable_logical_ref_count") == logical_ref_count
        and manifest.get("full_archival_logical_ref_count") == logical_ref_count,
        "F4 snapshot reachability projection drifted",
    )
    roots = manifest.get("logical_roots")
    _require(isinstance(roots, list), "F4 snapshot logical roots are absent")
    root_ids = {
        row.get("root_id")
        for row in roots
        if isinstance(row, Mapping) and isinstance(row.get("root_id"), str)
    }
    _require(_F4_SNAPSHOT_ROOTS.issubset(root_ids), "F4 snapshot required roots drifted")
    logical_refs = manifest.get("logical_refs")
    _require(isinstance(logical_refs, list), "F4 snapshot logical refs are absent")
    logical_ref_ids = {
        row.get("logical_ref")
        for row in logical_refs
        if isinstance(row, Mapping) and isinstance(row.get("logical_ref"), str)
    }
    _require(
        _F4_SNAPSHOT_FILES.issubset(logical_ref_ids),
        "F4 snapshot closure identity files drifted",
    )
    unresolved = manifest.get("unresolved_metadata_refs")
    _require(isinstance(unresolved, list), "F4 snapshot unresolved metadata is absent")
    unresolved_projection = {
        (row.get("json_pointer"), row.get("reason"))
        for row in unresolved
        if isinstance(row, Mapping)
    }
    _require(
        manifest.get("unresolved_metadata_ref_count") == len(unresolved)
        and len(unresolved) == len(_F4_UNRESOLVED)
        and unresolved_projection == _F4_UNRESOLVED,
        "F4 snapshot unresolved metadata allowlist drifted",
    )
    inventory = manifest.get("inventory")
    _require(isinstance(inventory, list) and bool(inventory), "snapshot inventory is absent")
    _require(manifest.get("inventory_count") == len(inventory), "snapshot inventory count drifted")
    copy_items: list[BoundSource] = [
        BoundSource(
            kind="snapshot",
            name=SNAPSHOT_MANIFEST_NAME,
            recorded_path=str(manifest_path),
            source_path=manifest_path,
            destination=PurePosixPath("f4_snapshot") / SNAPSHOT_MANIFEST_NAME,
            sha256=_sha256_bytes(manifest_raw),
            size_bytes=len(manifest_raw),
            roles=("f4_transitive_evidence_snapshot",),
        )
    ]
    for row in inventory:
        _require(
            isinstance(row, Mapping) and set(row) == {"relative_path", "sha256", "size_bytes"},
            "snapshot inventory row drifted",
        )
        relative = _safe_relative(row.get("relative_path"), label="snapshot inventory path")
        destination = PurePosixPath("f4_snapshot") / relative
        _validate_destination(destination)
        source, digest, size = _verify_file_identity(
            root / Path(*relative.parts),
            expected_sha256=row.get("sha256"),
            expected_size=row.get("size_bytes"),
            label=f"snapshot object {relative}",
        )
        copy_items.append(
            BoundSource(
                kind="snapshot",
                name=relative.as_posix(),
                recorded_path=str(source),
                source_path=source,
                destination=destination,
                sha256=digest,
                size_bytes=size,
                roles=("f4_transitive_evidence_snapshot",),
            )
        )
    return AdmittedSnapshot(
        root=root,
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_raw=manifest_raw,
        copy_items=tuple(copy_items),
    )


def _bind_snapshot_closure_identity(
    *,
    closure: AdmittedClosure,
    snapshot: AdmittedSnapshot,
) -> None:
    raw_refs = snapshot.manifest.get("logical_refs")
    _require(isinstance(raw_refs, list), "F4 snapshot logical refs are absent")
    refs = {
        row.get("logical_ref"): row
        for row in raw_refs
        if isinstance(row, Mapping) and isinstance(row.get("logical_ref"), str)
    }
    expected = {
        "file/closure_f4_request": closure.request_raw,
        "file/closure_authority_manifest": closure.authority.manifest_raw,
    }
    for logical_ref, raw in expected.items():
        row = refs.get(logical_ref)
        _require(
            isinstance(row, Mapping)
            and row.get("sha256") == _sha256_bytes(raw)
            and row.get("size_bytes") == len(raw),
            f"F4 snapshot differs from admitted closure identity: {logical_ref}",
        )


def _derive_copy_plan(
    *,
    closure: AdmittedClosure,
    snapshot: AdmittedSnapshot,
) -> tuple[BoundSource, ...]:
    raw_items = (
        closure.request_item,
        *closure.authority.copy_items,
        *closure.bindings,
        *snapshot.copy_items,
    )
    by_destination: dict[str, BoundSource] = {}
    folded_destinations: dict[str, str] = {}
    source_destinations: dict[str, str] = {}
    for item in raw_items:
        _validate_destination(item.destination)
        relative = item.destination.as_posix()
        folded = relative.casefold()
        prior_folded = folded_destinations.get(folded)
        _require(
            prior_folded is None or prior_folded == relative,
            f"capsule destination casefold collision: {prior_folded} / {relative}",
        )
        folded_destinations[folded] = relative
        source_key = _path_key(item.source_path)
        prior_source_destination = source_destinations.get(source_key)
        _require(
            prior_source_destination is None or prior_source_destination == relative,
            f"one source was assigned to multiple capsule destinations: {item.source_path}",
        )
        source_destinations[source_key] = relative
        prior = by_destination.get(relative)
        if prior is None:
            by_destination[relative] = item
            continue
        _require(
            _path_key(prior.source_path) == source_key
            and prior.sha256 == item.sha256
            and prior.size_bytes == item.size_bytes,
            f"capsule destination has conflicting source identities: {relative}",
        )
        by_destination[relative] = replace(
            prior,
            roles=tuple(sorted(set(prior.roles) | set(item.roles))),
        )
    return tuple(by_destination[key] for key in sorted(by_destination))


def _copy_plan_to_staging(
    *,
    plan: Sequence[BoundSource],
    foundation_root: Path,
) -> tuple[PayloadRow, ...]:
    rows: list[PayloadRow] = []
    for item in plan:
        source_raw_before = item.source_path.read_bytes()
        _require(
            len(source_raw_before) == item.size_bytes
            and _sha256_bytes(source_raw_before) == item.sha256,
            f"source drifted before copy: {item.source_path}",
        )
        destination = foundation_root.joinpath(*item.destination.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.source_path, destination)
        source_raw_after = item.source_path.read_bytes()
        destination_raw = destination.read_bytes()
        _require(
            source_raw_after == source_raw_before,
            f"source drifted during copy: {item.source_path}",
        )
        _require(
            destination_raw == source_raw_before,
            f"capsule destination drifted during copy: {item.destination}",
        )
        _require(
            not _is_reparse(destination),
            f"copied destination became a reparse point: {item.destination}",
        )
        rows.append(
            PayloadRow(
                relative_path=item.destination.as_posix(),
                sha256=_sha256_bytes(destination_raw),
                size_bytes=len(destination_raw),
                roles=tuple(sorted(set(item.roles))),
                source_path=str(item.source_path),
            )
        )
    _require(
        [row.relative_path for row in rows] == sorted(row.relative_path for row in rows),
        "payload rows are not canonically ordered",
    )
    return tuple(rows)


def _build_reference_bindings(
    *,
    copied_rows: Sequence[PayloadRow],
    closure: AdmittedClosure,
) -> list[dict[str, Any]]:
    rows = {row.relative_path: row for row in copied_rows}
    ordered = [
        *(
            item
            for name in F4_INPUT_NAMES
            for item in closure.bindings
            if item.kind == "input" and item.name == name
        ),
        *(
            item
            for name in F4_ARTIFACT_NAMES
            for item in closure.bindings
            if item.kind == "artifact" and item.name == name
        ),
        closure.blueprint,
    ]
    _require(len(ordered) == 16, "F4 reference binding count drifted")
    bindings: list[dict[str, Any]] = []
    for item in ordered:
        copied = rows.get(item.destination.as_posix())
        _require(
            copied is not None
            and copied.sha256 == item.sha256
            and copied.size_bytes == item.size_bytes,
            f"F4 reference binding was not copied exactly: {item.kind}:{item.name}",
        )
        bindings.append(
            {
                "kind": item.kind,
                "name": item.name,
                "recorded_path": item.recorded_path,
                "capsule_relative_path": item.destination.as_posix(),
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
        )
    return bindings


def _payload_manifest(rows: Sequence[PayloadRow]) -> dict[str, Any]:
    values = [
        {
            "relative_path": row.relative_path,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
            "roles": list(row.roles),
            "source_path": row.source_path,
        }
        for row in rows
    ]
    inventory_raw = "\n".join(
        f"{row.relative_path}\t{row.size_bytes}\t{row.sha256}" for row in rows
    ).encode("utf-8")
    return {
        "total_size_bytes": sum(row.size_bytes for row in rows),
        "exact_inventory_sha256": _sha256_bytes(inventory_raw),
        "inventory_algorithm": "sha256(relative_path<TAB>size_bytes<TAB>sha256 joined by LF)",
        "files": values,
    }


def _build_capsule_manifest(
    *,
    closure: AdmittedClosure,
    snapshot: AdmittedSnapshot,
    payload_rows: Sequence[PayloadRow],
    reference_bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = _payload_manifest(payload_rows)
    request_sha256 = _sha256_bytes(closure.request_raw)
    snapshot_content_sha256 = _sha256_value(
        snapshot.manifest.get("content_sha256"),
        label="snapshot content sha256",
    )
    actuals = dict(closure.authority.actuals)
    actuals.pop("module_size_bytes", None)
    actuals.pop("copied_source_path", None)
    counts = {
        "authority_snapshot_file_count": len(closure.authority.copy_items),
        "additional_input_file_count": len(F4_INPUT_NAMES) - 1,
        "artifact_source_file_count": len(F4_ARTIFACT_NAMES),
        "blueprint_file_count": 1,
        "f4_snapshot_file_count": len(snapshot.copy_items),
        "payload_file_count": len(payload_rows),
        "legacy_file_count": 0,
        "pyc_or_pycache_file_count": 0,
    }
    snapshot_summary = {
        "included": True,
        "manifest_relative_path": f"f4_snapshot/{SNAPSHOT_MANIFEST_NAME}",
        "manifest_sha256": _sha256_bytes(snapshot.manifest_raw),
        "manifest_size_bytes": len(snapshot.manifest_raw),
        "schema_version": snapshot.manifest["schema_version"],
        "content_sha256": snapshot_content_sha256,
        "inventory_count": snapshot.manifest["inventory_count"],
        "inventory_sha256": snapshot.manifest["inventory_sha256"],
        "logical_root_count": snapshot.manifest["logical_root_count"],
        "logical_ref_count": snapshot.manifest["logical_ref_count"],
        "reference_edge_count": snapshot.manifest["reference_edge_count"],
        "required_reference_match_count": snapshot.manifest["required_reference_match_count"],
        "reachable_logical_ref_count": snapshot.manifest["reachable_logical_ref_count"],
        "full_archival_logical_ref_count": snapshot.manifest["full_archival_logical_ref_count"],
        "cas_object_count": snapshot.manifest["cas_object_count"],
        "unresolved_metadata_ref_count": snapshot.manifest["unresolved_metadata_ref_count"],
        "unresolved_metadata_refs": snapshot.manifest["unresolved_metadata_refs"],
    }
    source = {
        "closure_pack_manifest_sha256": _sha256_bytes(closure.pack_raw),
        "closure_pack_sha256": closure.pack["pack_sha256"],
        "request_sha256": request_sha256,
        "authority_manifest_sha256": _sha256_bytes(closure.authority.manifest_raw),
        "runtime_buildinfo_sha256": _sha256_file(closure.authority.runtime_buildinfo_path),
        "snapshot_manifest_sha256": _sha256_bytes(snapshot.manifest_raw),
        "snapshot_content_sha256": snapshot_content_sha256,
        "old_capsule_manifest_read_count": 0,
    }
    return {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "capsule_id": (
            f"{F4_BLOCK_ID}-source-capsule-{request_sha256[:12]}-{snapshot_content_sha256[:12]}"
        ),
        "created_at": closure.created_at,
        "block_id": F4_BLOCK_ID,
        "scope": {
            "capsule_class": "SOURCE_ONLY_SAME_HOST_RELOCATION",
            "claims": [
                "SOURCE_CAPSULE_INPUT_COMPLETE",
                "SNAPSHOT_BYTES_PRESERVED",
                "AUTHORITY_BYTES_PRESERVED",
            ],
            "excluded_claims": [
                "REPLAY_VERIFIED",
                "OCI_RUNTIME_PORTABLE",
                "CROSS_MACHINE_EXECUTION",
                "FOUNDATION_GLOBALLY_CLOSED",
            ],
        },
        "source": source,
        "request": {
            "relative_path": closure.request_item.destination.as_posix(),
            "sha256": request_sha256,
            "size_bytes": len(closure.request_raw),
            "assertion_ids": list(F4_ASSERTION_IDS),
            "assertion_count": len(F4_ASSERTION_IDS),
            "input_reference_count": len(F4_INPUT_NAMES),
            "artifact_reference_count": len(F4_ARTIFACT_NAMES),
        },
        "actuals": actuals,
        "counts": counts,
        "payload": payload,
        "reference_bindings": list(reference_bindings),
        "f4_snapshot": snapshot_summary,
        "static_runtime_audit": {
            "authority_verified": True,
            "runtime_profiles_structurally_verified": True,
            "snapshot_verified": True,
            "replay_executed": False,
            "old_capsule_manifest_read_count": 0,
        },
        "excluded_prefixes_and_files": sorted(_LEGACY_OUTPUT_NAMES),
    }


def _scan_foundation(root: Path) -> set[str]:
    files: set[str] = set()
    folded: set[str] = set()
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        _require(
            not _is_reparse(directory_path), f"foundation contains reparse directory: {directory}"
        )
        for name in names:
            child = directory_path / name
            _require(not _is_reparse(child), f"foundation contains reparse directory: {child}")
            _require(
                name.casefold() != "__pycache__", f"foundation contains cache directory: {child}"
            )
        for name in filenames:
            child = directory_path / name
            _require(
                not _is_reparse(child) and child.is_file(), f"foundation contains non-file: {child}"
            )
            relative = child.relative_to(root).as_posix()
            _require(
                relative.casefold() not in folded, f"foundation path casefold collision: {relative}"
            )
            folded.add(relative.casefold())
            _require(
                Path(name).suffix.casefold() not in {".pyc", ".pyo"},
                f"foundation contains bytecode: {relative}",
            )
            files.add(relative)
    return files


def _run_common_preflight(*, pack_root: Path, block_id: str) -> dict[str, Any]:
    from xinao.foundation.foundation_v4_replay_runtime import (
        preflight_relocated_foundation_v4,
    )

    return preflight_relocated_foundation_v4(pack_root=pack_root, block_id=block_id)


def _verify_staged_pack(*, staging_root: Path, block_id: str) -> dict[str, Any]:
    foundation = staging_root / "foundation"
    manifest_path = foundation / "capsule_manifest.json"
    manifest, manifest_raw = _load_json_object(
        manifest_path,
        label="capsule manifest",
        require_canonical=True,
    )
    payload = manifest.get("payload")
    payload_files = payload.get("files") if isinstance(payload, Mapping) else None
    _require(isinstance(payload_files, list), "capsule payload inventory is absent")
    declared = {
        row.get("relative_path")
        for row in payload_files
        if isinstance(row, Mapping) and isinstance(row.get("relative_path"), str)
    }
    _require(len(declared) == len(payload_files), "capsule payload inventory is duplicated")
    _require(
        _scan_foundation(foundation) == {*declared, "capsule_manifest.json"},
        "capsule foundation tree is not exact",
    )
    preflight = _run_common_preflight(pack_root=staging_root, block_id=block_id)
    _require(preflight.get("status") == "VERIFIED", "common relocation preflight did not verify")
    authority = _admit_authority(foundation / "authority_snapshot" / AUTHORITY_MANIFEST_FILENAME)
    snapshot = _admit_snapshot(foundation / "f4_snapshot")
    return {
        "capsule_manifest_sha256": _sha256_bytes(manifest_raw),
        "preflight": preflight,
        "authority_manifest_sha256": _sha256_bytes(authority.manifest_raw),
        "snapshot_manifest_sha256": _sha256_bytes(snapshot.manifest_raw),
        "snapshot_content_sha256": snapshot.manifest["content_sha256"],
    }


def _write_canonical(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(dict(value)))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _build_receipt(
    *,
    operation_id: str,
    closure: AdmittedClosure,
    snapshot: AdmittedSnapshot,
    output_root: Path,
    capsule_manifest: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    builder_source = Path(__file__)
    core = {
        "schema_version": BUILD_RECEIPT_SCHEMA_VERSION,
        "operation_id": operation_id,
        "built_at": _utc_now(),
        "block_id": F4_BLOCK_ID,
        "builder_source_ref": {
            "path": str(builder_source),
            "sha256": _sha256_file(builder_source),
            "size_bytes": builder_source.stat().st_size,
        },
        "closure_root_observation": str(closure.root),
        "snapshot_root_observation": str(snapshot.root),
        "output_root_observation": str(output_root),
        "closure_pack_manifest_ref": {
            "path": str(closure.pack_path),
            "sha256": _sha256_bytes(closure.pack_raw),
            "size_bytes": len(closure.pack_raw),
        },
        "request_ref": {
            "path": str(closure.request_path),
            "sha256": _sha256_bytes(closure.request_raw),
            "size_bytes": len(closure.request_raw),
        },
        "authority_manifest_ref": {
            "path": str(closure.authority.manifest_path),
            "sha256": _sha256_bytes(closure.authority.manifest_raw),
            "size_bytes": len(closure.authority.manifest_raw),
        },
        "runtime_buildinfo_ref": {
            "path": str(closure.authority.runtime_buildinfo_path),
            "sha256": _sha256_file(closure.authority.runtime_buildinfo_path),
            "size_bytes": closure.authority.runtime_buildinfo_path.stat().st_size,
        },
        "snapshot_manifest_ref": {
            "path": str(snapshot.manifest_path),
            "sha256": _sha256_bytes(snapshot.manifest_raw),
            "size_bytes": len(snapshot.manifest_raw),
            "content_sha256": snapshot.manifest["content_sha256"],
        },
        "capsule_manifest_ref": {
            "relative_path": "foundation/capsule_manifest.json",
            "sha256": validation["capsule_manifest_sha256"],
        },
        "payload_file_count": capsule_manifest["counts"]["payload_file_count"],
        "payload_total_size_bytes": capsule_manifest["payload"]["total_size_bytes"],
        "payload_exact_inventory_sha256": capsule_manifest["payload"]["exact_inventory_sha256"],
        "reference_binding_count": len(capsule_manifest["reference_bindings"]),
        "preflight_receipt": validation["preflight"],
        "authority_validation": {
            "status": "VERIFIED",
            "manifest_sha256": validation["authority_manifest_sha256"],
        },
        "snapshot_validation": {
            "status": "VERIFIED",
            "manifest_sha256": validation["snapshot_manifest_sha256"],
            "content_sha256": validation["snapshot_content_sha256"],
        },
        "old_capsule_manifest_read_count": 0,
        "atomic_publish": {
            "method": "same-parent-os.replace",
            "same_volume": True,
            "published": True,
        },
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def _operation_identity(value: str | None) -> str:
    operation = value or uuid.uuid4().hex
    _require(_OPERATION_RE.fullmatch(operation) is not None, "operation_id is invalid")
    return operation


def build_foundation_v4_relocation_source_capsule(
    *,
    closure_root: Path,
    snapshot_root: Path,
    output_root: Path,
    block_id: str = F4_BLOCK_ID,
    operation_id: str | None = None,
) -> CapsuleBuildResult:
    """Build and atomically publish one exact F4 source capsule."""

    operation = _operation_identity(operation_id)
    _require(block_id == F4_BLOCK_ID, f"unsupported foundation block: {block_id}")
    output = _absolute(output_root)
    output_parent = _existing_directory(output.parent, label="output parent")
    _assert_no_lexical_reparse(output, label="output root", allow_missing_leaf=True)
    _require(not output.exists(), f"output root already exists: {output}")
    staging = output_parent / f".{output.name}.{operation}.staging"
    _require(not staging.exists(), f"operation staging root already exists: {staging}")

    closure = _admit_closure(closure_root, block_id=block_id)
    snapshot = _admit_snapshot(snapshot_root)
    _bind_snapshot_closure_identity(closure=closure, snapshot=snapshot)
    _require(
        not _paths_overlap(output, closure.root) and not _paths_overlap(output, snapshot.root),
        "output root overlaps a sealed input root",
    )
    _require(
        not _paths_overlap(staging, closure.root) and not _paths_overlap(staging, snapshot.root),
        "operation staging root overlaps a sealed input root",
    )
    plan = _derive_copy_plan(closure=closure, snapshot=snapshot)
    staging.mkdir(parents=False, exist_ok=False)
    published = False
    try:
        foundation = staging / "foundation"
        foundation.mkdir()
        payload_rows = _copy_plan_to_staging(plan=plan, foundation_root=foundation)
        bindings = _build_reference_bindings(copied_rows=payload_rows, closure=closure)
        capsule_manifest = _build_capsule_manifest(
            closure=closure,
            snapshot=snapshot,
            payload_rows=payload_rows,
            reference_bindings=bindings,
        )
        manifest_path = foundation / "capsule_manifest.json"
        _write_canonical(manifest_path, capsule_manifest)
        validation = _verify_staged_pack(staging_root=staging, block_id=block_id)
        receipt = _build_receipt(
            operation_id=operation,
            closure=closure,
            snapshot=snapshot,
            output_root=output,
            capsule_manifest=capsule_manifest,
            validation=validation,
        )
        _write_canonical(staging / "build_receipt.v1.json", receipt)
        os.replace(staging, output)
        published = True
        final_validation = _verify_staged_pack(staging_root=output, block_id=block_id)
        stable_validation_fields = (
            "capsule_manifest_sha256",
            "authority_manifest_sha256",
            "snapshot_manifest_sha256",
            "snapshot_content_sha256",
        )
        _require(
            all(final_validation[field] == validation[field] for field in stable_validation_fields)
            and final_validation["preflight"].get("status") == "VERIFIED",
            "published capsule validation drifted",
        )
        final_manifest = output / "foundation" / "capsule_manifest.json"
        final_receipt = output / "build_receipt.v1.json"
        _require(final_receipt.is_file(), "published build receipt is absent")
        return CapsuleBuildResult(
            output_root=output,
            foundation_root=output / "foundation",
            capsule_manifest_path=final_manifest,
            build_receipt_path=final_receipt,
            capsule_manifest_sha256=_sha256_file(final_manifest),
            payload_exact_inventory_sha256=str(
                capsule_manifest["payload"]["exact_inventory_sha256"]
            ),
            payload_file_count=int(capsule_manifest["counts"]["payload_file_count"]),
            payload_total_size_bytes=int(capsule_manifest["payload"]["total_size_bytes"]),
        )
    except Exception as exc:
        if published and output.exists():
            shutil.rmtree(output, ignore_errors=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, RelocationCapsuleBuildError):
            raise
        raise RelocationCapsuleBuildError(str(exc)) from exc


__all__ = [
    "BUILD_RECEIPT_SCHEMA_VERSION",
    "CAPSULE_SCHEMA_VERSION",
    "F4_ARTIFACT_NAMES",
    "F4_ASSERTION_IDS",
    "F4_BLOCK_ID",
    "F4_INPUT_NAMES",
    "CapsuleBuildResult",
    "RelocationCapsuleBuildError",
    "admit_f4_closure",
    "build_foundation_v4_relocation_source_capsule",
]
