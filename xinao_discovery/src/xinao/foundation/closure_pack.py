"""Build the canonical F1-F4 closure pack from two independent fresh replays."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_bundle_runner import (
    BUNDLE_SCHEMA_VERSION,
    PROTOCOL_VERSION,
    AssertionBundleRunnerError,
    build_assertion_request_v2,
    run_canonical_bundle_fresh,
)
from xinao.foundation.assertion_verifier_registry import (
    CanonicalVerifierError,
    canonical_projection_path,
    canonical_python_executable,
    canonical_verifier,
    materialize_authority_snapshot,
    validate_authority_snapshot,
)
from xinao.foundation.closure import (
    FOUNDATION_BLOCK_IDS,
    FoundationProfileUnavailable,
    evidence_ref,
    load_foundation_profile,
    write_json_atomic,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_MATERIAL_METADATA_KEYS = frozenset(
    {
        "artifact_identity",
        "artifact_type",
        "created_at",
        "description",
        "content_hash",
        "input_hashes",
        "manual_override_used",
        "name",
        "payload_sha256",
        "producer_id",
        "producer_ids",
        "result",
        "schema_version",
        "status",
        "title",
        "updated_at",
        "verifier_id",
        "version",
    }
)


class ClosurePackError(ValueError):
    """Raised before a pack can be mistaken for verified closure evidence."""


class ClosurePackNotPerformed(ClosurePackError):
    """Raised when the current authority is bound but no runtime profile is admitted."""

    status = "NOT_PERFORMED"

    def __init__(self, resolution: Mapping[str, Any]) -> None:
        self.resolution = dict(resolution)
        blockers = self.resolution.get("blockers")
        self.blockers = list(blockers) if isinstance(blockers, list) else []
        super().__init__(f"NOT_PERFORMED: {', '.join(self.blockers)}")


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ClosurePackError(f"{label} must be an object")
    if not all(isinstance(key, str) and key for key in value):
        raise ClosurePackError(f"{label} keys must be non-empty strings")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ClosurePackError(f"{label} key mismatch: missing={missing}, extra={extra}")


def _identity(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ClosurePackError(f"{label} must be a non-empty identity")
    return value


def _timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ClosurePackError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClosurePackError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ClosurePackError(f"{label} must include a timezone")
    return value


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ClosurePackError(f"{label} must be a lowercase SHA-256 value")
    return value


def _path(value: object, *, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise ClosurePackError(f"{label} must be a path")
    result = Path(value).resolve()
    if not result.is_file():
        raise ClosurePackError(f"{label} does not exist: {result}")
    return result


def _content_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_dumps(left) == canonical_dumps(right)
    except (TypeError, ValueError) as exc:
        raise ClosurePackError("assertion values must be canonical JSON values") from exc


def _has_material_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, Mapping):
        return any(_has_material_value(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_has_material_value(item) for item in value)
    return True


def _material_payload(value: object, *, label: str) -> dict[str, Any]:
    payload = _mapping(value, label=label)
    substantive = {
        key: item for key, item in payload.items() if key not in _MATERIAL_METADATA_KEYS
    }
    if not substantive or not any(_has_material_value(item) for item in substantive.values()):
        raise ClosurePackError(f"{label} is metadata-only")
    result = dict(payload)
    try:
        canonical_dumps(result)
    except (TypeError, ValueError) as exc:
        raise ClosurePackError(f"{label} is not canonical JSON") from exc
    return result


def _safe_filename(identity: str) -> str:
    stem = _SAFE_NAME_RE.sub("_", identity).strip("._") or "item"
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{stem}.{suffix}.json"


def _safe_raw_filename(identity: str, source: Path) -> str:
    stem = _SAFE_NAME_RE.sub("_", identity).strip("._") or "item"
    identity_suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    source_suffix = "".join(source.suffixes)
    if not source_suffix or _SAFE_NAME_RE.search(source_suffix):
        source_suffix = ".bin"
    return f"{stem}.{identity_suffix}{source_suffix}"


def _write_canonical(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(dict(value)))
    return evidence_ref(path)


def _write_envelope(path: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    write_json_atomic(path, envelope)
    return evidence_ref(path)


def _validate_live_authority(manifest_path: Path) -> dict[str, Any]:
    try:
        return validate_authority_snapshot(manifest_path, require_live_match=True)
    except CanonicalVerifierError as exc:
        raise ClosurePackError(str(exc)) from exc


def _run_sealed_bundle_fresh(
    *,
    manifest_path: Path,
    request_path: Path,
    block_id: str,
    output_path: Path,
    timeout: int,
) -> dict[str, Any]:
    _validate_live_authority(manifest_path)
    try:
        return run_canonical_bundle_fresh(
            request_path=request_path,
            block_id=block_id,
            output_path=output_path,
            timeout=timeout,
        )
    finally:
        _validate_live_authority(manifest_path)


def _snapshot_verifier_source(
    *,
    manifest_path: Path,
    authority_manifest: Mapping[str, Any],
    block_id: str,
) -> tuple[Path, str]:
    verifier = canonical_verifier(block_id)
    relative_path = f"xinao_discovery/src/{verifier.relative_source}"
    entries = authority_manifest.get("entries")
    if not isinstance(entries, list):
        raise ClosurePackError("authority snapshot source inventory is invalid")
    matching = [
        entry
        for entry in entries
        if isinstance(entry, Mapping)
        and entry.get("relative_path") == relative_path
    ]
    if len(matching) != 1:
        raise ClosurePackError(
            f"canonical verifier is not uniquely present in authority snapshot: {block_id}"
        )
    entry = matching[0]
    snapshot_path = manifest_path.parent / "sources" / Path(*relative_path.split("/"))
    snapshot_ref = evidence_ref(snapshot_path)
    if (
        snapshot_ref["sha256"] != verifier.source_sha256
        or snapshot_ref["sha256"] != entry.get("sha256")
        or snapshot_ref["size_bytes"] != entry.get("size")
    ):
        raise ClosurePackError(
            f"canonical verifier snapshot identity mismatch: {block_id}"
        )
    return snapshot_path, relative_path


def _fresh_process_verify(
    *, projection_path: Path, report_path: Path, authority_manifest_path: Path
) -> dict[str, Any]:
    _validate_live_authority(authority_manifest_path)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PYTHON")
    }
    python = canonical_python_executable()
    try:
        completed = subprocess.run(
            [
                str(python),
                "-I",
                "-m",
                "xinao.foundation.report_verifier_entrypoint",
                "--projection",
                str(projection_path),
                "--report",
                str(report_path),
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=environment,
            cwd=python.parents[2],
            timeout=300,
        )
    finally:
        _validate_live_authority(authority_manifest_path)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ClosurePackError(
            "fresh-process verification did not return JSON: "
            f"exit={completed.returncode}, stderr={completed.stderr.strip()!r}"
        ) from exc
    if (
        completed.returncode != 0
        or not isinstance(result, dict)
        or result.get("ok") is not True
        or result.get("foundation_execution_ready") is not True
    ):
        raise ClosurePackError(
            "fresh-process verification rejected the closure report: "
            f"exit={completed.returncode}, result={result!r}, "
            f"stderr={completed.stderr.strip()!r}"
        )
    return result


def build_foundation_closure_pack(
    *,
    output_root: Path,
    input_evidence: Mapping[str, Mapping[str, Any]],
    artifact_materials: Mapping[str, Mapping[str, Mapping[str, Any]]],
    report_id: str,
    version: str,
    created_at: str,
) -> dict[str, Any]:
    """Build and fresh-process verify one exact F1-F4 closure evidence pack."""

    try:
        blueprint_path = canonical_projection_path()
    except CanonicalVerifierError as exc:
        raise ClosurePackError(str(exc)) from exc
    try:
        profile = load_foundation_profile(blueprint_path)
    except FoundationProfileUnavailable as exc:
        raise ClosurePackNotPerformed(exc.resolution) from exc
    output_root = Path(output_root).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ClosurePackError(f"output_root must be empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    profile_blocks = _mapping(profile.get("blocks"), label="foundation profile blocks")
    closure_meta = _mapping(profile.get("_closure_meta"), label="foundation closure metadata")
    required_input_keys_raw = closure_meta.get("required_input_hash_keys")
    if not isinstance(required_input_keys_raw, list) or not all(
        isinstance(item, str) and item for item in required_input_keys_raw
    ):
        raise ClosurePackError("implementation profile input hash inventory is invalid")
    required_input_keys = set(required_input_keys_raw)
    if "compiler_code_sha256" not in required_input_keys:
        raise ClosurePackError("implementation profile must require compiler_code_sha256")

    try:
        authority_snapshot = materialize_authority_snapshot(
            output_root / "authority_snapshot"
        )
    except CanonicalVerifierError as exc:
        raise ClosurePackError(str(exc)) from exc
    code_manifest_path = authority_snapshot["manifest_path"]
    authority_manifest = authority_snapshot["manifest"]
    code_manifest_ref = evidence_ref(code_manifest_path)
    code_hash = code_manifest_ref["sha256"]
    _validate_live_authority(code_manifest_path)

    input_specs = _mapping(input_evidence, label="input_evidence")
    caller_input_keys = required_input_keys - {"compiler_code_sha256"}
    _exact_keys(input_specs, caller_input_keys, label="input_evidence")
    input_refs: dict[str, dict[str, Any]] = {}
    input_hashes: dict[str, str] = {}
    occupied_paths: set[Path] = set()
    for key in sorted(caller_input_keys):
        spec = _mapping(input_specs[key], label=f"input_evidence[{key}]")
        _exact_keys(spec, {"path", "sha256"}, label=f"input_evidence[{key}]")
        path = _path(spec["path"], label=f"input_evidence[{key}].path")
        if path in occupied_paths:
            raise ClosurePackError(f"input evidence path is reused: {path}")
        occupied_paths.add(path)
        expected_hash = _sha256(spec["sha256"], label=f"input_evidence[{key}].sha256")
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash != expected_hash:
            raise ClosurePackError(
                f"input evidence hash mismatch for {key}: "
                f"expected={expected_hash}, actual={actual_hash}"
            )
        retained_path = (
            output_root
            / "source_materials"
            / "inputs"
            / _safe_raw_filename(key, path)
        )
        retained_path.parent.mkdir(parents=True, exist_ok=True)
        retained_path.write_bytes(raw)
        input_hashes[key] = actual_hash
        input_refs[key] = evidence_ref(retained_path, input_hash_key=key)
    input_hashes["compiler_code_sha256"] = code_hash
    input_refs["compiler_code_sha256"] = {
        **code_manifest_ref,
        "input_hash_key": "compiler_code_sha256",
    }

    known_input_hashes = _mapping(
        closure_meta.get("known_input_hashes"), label="known current profile input hashes"
    )
    for key, expected in known_input_hashes.items():
        if input_hashes.get(key) != expected:
            raise ClosurePackError(
                f"input evidence does not match current profile for {key}: "
                f"expected={expected}, actual={input_hashes.get(key)}"
            )
    config_hash = _sha256(closure_meta.get("config_hash"), label="compiler config")
    if input_hashes.get("compiler_config_sha256") != config_hash:
        raise ClosurePackError(
            "compiler_config_sha256 evidence is not the current profile closure config"
        )

    artifact_blocks = _mapping(artifact_materials, label="artifact_materials")
    expected_blocks = set(FOUNDATION_BLOCK_IDS)
    _exact_keys(artifact_blocks, expected_blocks, label="artifact_materials")
    report_id = _identity(report_id, label="report_id")
    version = _identity(version, label="version")
    created_at = _timestamp(created_at, label="created_at")

    prepared_materials: dict[str, dict[str, dict[str, Any]]] = {}
    required_assertions_by_block: dict[str, list[str]] = {}
    expected_assertions_by_block: dict[str, dict[str, Any]] = {}
    for block_id in FOUNDATION_BLOCK_IDS:
        profile_block = _mapping(profile_blocks[block_id], label=f"profile[{block_id}]")
        required_artifacts_raw = profile_block.get("required_artifact_types")
        required_assertions_raw = profile_block.get("required_assertion_ids")
        required_expectations = _mapping(
            profile_block.get("required_assertions"),
            label=f"profile[{block_id}].required_assertions",
        )
        if not isinstance(required_artifacts_raw, list) or not all(
            isinstance(item, str) and item for item in required_artifacts_raw
        ):
            raise ClosurePackError(f"profile[{block_id}] artifact inventory is invalid")
        if not isinstance(required_assertions_raw, list) or not all(
            isinstance(item, str) and item for item in required_assertions_raw
        ):
            raise ClosurePackError(f"profile[{block_id}] assertion inventory is invalid")
        required_artifacts = set(required_artifacts_raw)
        required_assertions = set(required_assertions_raw)
        _exact_keys(
            required_expectations,
            required_assertions,
            label=f"profile[{block_id}].required_assertions",
        )
        required_assertions_by_block[block_id] = sorted(required_assertions)
        expected_assertions_by_block[block_id] = dict(required_expectations)
        block_materials = _mapping(
            artifact_blocks[block_id], label=f"artifact_materials[{block_id}]"
        )
        _exact_keys(
            block_materials,
            required_artifacts,
            label=f"artifact_materials[{block_id}]",
        )
        prepared_materials[block_id] = {}
        for artifact_type in sorted(required_artifacts):
            material = _mapping(
                block_materials[artifact_type],
                label=f"artifact_materials[{block_id}][{artifact_type}]",
            )
            _exact_keys(
                material,
                {"version", "path", "sha256"},
                label=f"artifact_materials[{block_id}][{artifact_type}]",
            )
            source_path = _path(
                material["path"],
                label=f"artifact_materials[{block_id}][{artifact_type}].path",
            )
            if source_path in occupied_paths:
                raise ClosurePackError(f"artifact source path is reused: {source_path}")
            occupied_paths.add(source_path)
            expected_hash = _sha256(
                material["sha256"],
                label=f"artifact_materials[{block_id}][{artifact_type}].sha256",
            )
            source_bytes = source_path.read_bytes()
            if hashlib.sha256(source_bytes).hexdigest() != expected_hash:
                raise ClosurePackError(f"artifact source hash mismatch for {artifact_type}")
            try:
                payload = json.loads(source_bytes.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ClosurePackError(
                    f"artifact source is not a UTF-8 JSON object: {source_path}"
                ) from exc
            retained_source_path = (
                output_root
                / "source_materials"
                / "artifacts"
                / block_id
                / _safe_raw_filename(artifact_type, source_path)
            )
            retained_source_path.parent.mkdir(parents=True, exist_ok=True)
            retained_source_path.write_bytes(source_bytes)
            prepared_materials[block_id][artifact_type] = {
                "version": _identity(
                    material["version"],
                    label=f"artifact_materials[{block_id}][{artifact_type}].version",
                ),
                "payload": _material_payload(
                    payload,
                    label=f"artifact_materials[{block_id}][{artifact_type}].source_payload",
                ),
                "source_ref": evidence_ref(
                    retained_source_path, artifact_type=artifact_type
                ),
            }

    closure_source = Path(__file__).resolve().with_name("closure.py")
    closure_hash = hashlib.sha256(closure_source.read_bytes()).hexdigest()
    pack_hash = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    material_source_hashes = {
        block_id: {
            name: item["source_ref"]["sha256"]
            for name, item in sorted(prepared_materials[block_id].items())
        }
        for block_id in FOUNDATION_BLOCK_IDS
    }
    normalized_block_producers = {
        block_id: [
            "xinao.canonical.artifact-producer."
            f"{block_id}."
            f"{canonical_sha256(material_source_hashes[block_id])}"
        ]
        for block_id in FOUNDATION_BLOCK_IDS
    }
    normalized_block_verifiers = {
        block_id: f"xinao.canonical.block-deriver.{block_id}.{closure_hash}"
        for block_id in FOUNDATION_BLOCK_IDS
    }
    normalized_report_producers = [f"xinao.canonical.closure-pack-producer.{pack_hash}"]
    normalized_report_verifier = f"xinao.canonical.report-fresh-verifier.{closure_hash}"

    block_reports: dict[str, dict[str, Any]] = {}
    staged_material_refs: dict[str, dict[str, dict[str, Any]]] = {}
    artifact_evidence_identities: set[tuple[str, str]] = set()
    artifact_content_hashes: set[str] = set()
    for block_id in FOUNDATION_BLOCK_IDS:
        artifact_versions: dict[str, str] = {}
        artifact_hashes: dict[str, str] = {}
        artifact_refs: list[dict[str, Any]] = []
        staged_material_refs[block_id] = {}
        for artifact_type, material in sorted(prepared_materials[block_id].items()):
            envelope = {
                "artifact_type": artifact_type,
                "version": material["version"],
                "input_hashes": input_hashes,
                "code_hash": code_hash,
                "config_hash": config_hash,
                "source_ref": material["source_ref"],
                "payload": material["payload"],
                "payload_sha256": canonical_sha256(material["payload"]),
            }
            envelope_hash = canonical_sha256(envelope)
            if envelope_hash in artifact_content_hashes:
                raise ClosurePackError(f"duplicate artifact envelope content: {artifact_type}")
            artifact_content_hashes.add(envelope_hash)
            path = output_root / "artifacts" / block_id / _safe_filename(artifact_type)
            raw_ref = _write_envelope(path, envelope)
            ref = {**raw_ref, "artifact_type": artifact_type}
            identity = (ref["path"], ref["sha256"])
            if identity in artifact_evidence_identities:
                raise ClosurePackError(f"artifact evidence is reused: {artifact_type}")
            artifact_evidence_identities.add(identity)
            artifact_versions[artifact_type] = material["version"]
            artifact_hashes[artifact_type] = ref["sha256"]
            artifact_refs.append(ref)
            staged_material_refs[block_id][artifact_type] = ref
        block_reports[block_id] = {
            "block_id": block_id,
            "artifact_versions": artifact_versions,
            "artifact_hashes": artifact_hashes,
            "input_hashes": input_hashes,
            "assertion_results": {},
            "evidence_refs": artifact_refs,
            "producer_ids": normalized_block_producers[block_id],
            "verifier_id": normalized_block_verifiers[block_id],
        }

    assertion_evidence_identities: set[tuple[str, str]] = set()
    bundle_receipt_refs: dict[str, dict[str, Any]] = {}
    for block_id in FOUNDATION_BLOCK_IDS:
        verifier = canonical_verifier(block_id)
        request = build_assertion_request_v2(
            block_id=block_id,
            assertion_ids=required_assertions_by_block[block_id],
            input_refs=input_refs,
            input_hashes=input_hashes,
            materials=prepared_materials[block_id],
            compiler_code_sha256=code_hash,
            compiler_config_sha256=config_hash,
        )
        for artifact_type, staged_ref in staged_material_refs[block_id].items():
            staged_payload = json.loads(Path(staged_ref["path"]).read_text(encoding="utf-8"))
            if staged_payload != request["artifacts"][artifact_type]["staged_envelope"]:
                raise ClosurePackError(
                    f"canonical request is not bound to staged artifact: {artifact_type}"
                )
        request_path = output_root / "assertion_requests" / f"{block_id}.json"
        request_ref = _write_canonical(request_path, request)
        first_path = output_root / "assertion_bundles" / f"{block_id}.json"
        second_path = output_root / "fresh_assertion_bundles" / f"{block_id}.json"
        try:
            _run_sealed_bundle_fresh(
                manifest_path=code_manifest_path,
                request_path=request_path,
                block_id=block_id,
                output_path=first_path,
                timeout=600,
            )
            _run_sealed_bundle_fresh(
                manifest_path=code_manifest_path,
                request_path=request_path,
                block_id=block_id,
                output_path=second_path,
                timeout=600,
            )
        except AssertionBundleRunnerError as exc:
            raise ClosurePackError(str(exc)) from exc
        first_bytes = first_path.read_bytes()
        second_bytes = second_path.read_bytes()
        if first_bytes != second_bytes:
            raise ClosurePackError(f"canonical double-fresh bundle mismatch for {block_id}")
        try:
            stored_bundle = json.loads(first_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ClosurePackError(f"canonical assertion bundle is invalid: {block_id}") from exc
        if not isinstance(stored_bundle, dict) or canonical_dumps(stored_bundle) != first_bytes:
            raise ClosurePackError(f"canonical assertion bundle is not canonical: {block_id}")
        bundle_core = {
            key: value
            for key, value in stored_bundle.items()
            if key != "content_sha256"
        }
        if (
            stored_bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION
            or stored_bundle.get("protocol_version") != PROTOCOL_VERSION
            or stored_bundle.get("block_id") != block_id
            or stored_bundle.get("request_sha256") != canonical_sha256(request)
            or stored_bundle.get("entrypoint")
            != {
                "module_name": verifier.module_name,
                "source_path": str(verifier.source_path),
                "source_sha256": verifier.source_sha256,
                "checker_id": verifier.checker_id,
                "checker_version": verifier.checker_version,
            }
            or stored_bundle.get("content_sha256") != canonical_sha256(bundle_core)
        ):
            raise ClosurePackError(f"assertion bundle metadata mismatch for {block_id}")
        actuals = _mapping(
            stored_bundle.get("assertion_actuals"),
            label=f"assertion bundle actuals[{block_id}]",
        )
        actual_hashes = _mapping(
            stored_bundle.get("assertion_actual_content_sha256"),
            label=f"assertion bundle actual hashes[{block_id}]",
        )
        required_assertions = set(required_assertions_by_block[block_id])
        _exact_keys(actuals, required_assertions, label=f"assertion bundle actuals[{block_id}]")
        _exact_keys(
            actual_hashes,
            required_assertions,
            label=f"assertion bundle actual hashes[{block_id}]",
        )
        stored_ref = {**evidence_ref(first_path), "block_id": block_id}
        fresh_ref = {**evidence_ref(second_path), "block_id": block_id}
        snapshot_verifier_path, snapshot_verifier_relative = _snapshot_verifier_source(
            manifest_path=code_manifest_path,
            authority_manifest=authority_manifest,
            block_id=block_id,
        )
        receipt = {
            "schema_version": "xinao.fresh_assertion_bundle_receipt.v3",
            "protocol_version": PROTOCOL_VERSION,
            "block_id": block_id,
            "request_ref": request_ref,
            "first_bundle_ref": stored_ref,
            "second_bundle_ref": fresh_ref,
            "entrypoint_source_ref": {
                **evidence_ref(snapshot_verifier_path),
                "block_id": block_id,
            },
            "canonical_entrypoint": {
                "module_name": verifier.module_name,
                "live_source_path": str(verifier.source_path),
                "authority_relative_path": snapshot_verifier_relative,
                "source_sha256": verifier.source_sha256,
                "checker_id": verifier.checker_id,
                "checker_version": verifier.checker_version,
            },
            "compiler_code_manifest_ref": code_manifest_ref,
            "double_fresh_bytes_equal": True,
        }
        receipt_path = output_root / "fresh_assertion_bundle_receipts" / f"{block_id}.json"
        receipt_ref = _write_canonical(receipt_path, receipt)
        bundle_receipt_refs[block_id] = receipt_ref
        artifact_source_hashes = {
            artifact_type: material["source_ref"]["sha256"]
            for artifact_type, material in prepared_materials[block_id].items()
        }
        assertion_results: dict[str, dict[str, Any]] = {}
        for assertion_id in required_assertions_by_block[block_id]:
            expected = expected_assertions_by_block[block_id][assertion_id]
            actual = actuals[assertion_id]
            actual_content_sha256 = canonical_sha256(
                {"assertion_id": assertion_id, "actual": actual}
            )
            if actual_hashes[assertion_id] != actual_content_sha256:
                raise ClosurePackError(f"assertion content hash mismatch for {assertion_id}")
            if not _content_equal(actual, expected):
                raise ClosurePackError(
                    f"assertion actual mismatch for {assertion_id}: "
                    f"expected={expected!r}, actual={actual!r}"
                )
            assertion_payload = {
                "schema_version": "xinao.closure_assertion_evidence.v3",
                "assertion_id": assertion_id,
                "result": "PASS",
                "checker_id": verifier.checker_id,
                "checker_version": verifier.checker_version,
                "checker_code_hash": verifier.source_sha256,
                "config_hash": config_hash,
                "producer_ids": normalized_block_producers[block_id],
                "verifier_id": normalized_block_verifiers[block_id],
                "input_hashes": input_hashes,
                "artifact_source_hashes": artifact_source_hashes,
                "actual": actual,
                "expected": expected,
                "actual_content_sha256": actual_content_sha256,
                "assertion_bundle_content_sha256": stored_bundle["content_sha256"],
                "assertion_bundle_ref": stored_ref,
                "fresh_assertion_bundle_ref": fresh_ref,
                "fresh_receipt_ref": receipt_ref,
                "compiler_code_manifest_ref": code_manifest_ref,
                "executed_at": created_at,
            }
            assertion_path = (
                output_root
                / "assertions"
                / block_id
                / _safe_filename(assertion_id)
            )
            raw_ref = _write_envelope(assertion_path, assertion_payload)
            ref = {**raw_ref, "assertion_id": assertion_id}
            identity = (ref["path"], ref["sha256"])
            if identity in assertion_evidence_identities:
                raise ClosurePackError(f"assertion evidence is reused: {assertion_id}")
            assertion_evidence_identities.add(identity)
            assertion_results[assertion_id] = {
                key: value
                for key, value in assertion_payload.items()
                if key not in {"schema_version", "actual", "expected"}
                and not key.endswith("_ref")
            } | {"evidence_refs": [ref], "output_hash": ref["sha256"]}
        block_reports[block_id]["assertion_results"] = assertion_results

    report_input = {
        "report_id": report_id,
        "version": version,
        "created_at": created_at,
        "authority_projection_ref": evidence_ref(blueprint_path),
        "input_hashes": input_hashes,
        "code_hash": code_hash,
        "config_hash": config_hash,
        "compiler_code_manifest_ref": code_manifest_ref,
        "authority_snapshot_manifest_ref": code_manifest_ref,
        "block_reports": block_reports,
        "evidence_refs": [input_refs[key] for key in sorted(input_refs)],
        "producer_ids": normalized_report_producers,
        "independent_verifier_id": normalized_report_verifier,
    }
    report_input_path = output_root / "foundation_closure_report_input.json"
    write_json_atomic(report_input_path, report_input)

    from xinao.foundation.closure import derive_foundation_closure_report

    report = derive_foundation_closure_report(report_input, blueprint_path=blueprint_path)
    if (
        report.get("foundation_execution_ready") is not True
        or report.get("status") != "VERIFIED"
    ):
        failures = {
            block_id: block.get("failure_reasons", [])
            for block_id, block in report.get("block_reports", {}).items()
            if isinstance(block, dict) and block.get("failure_reasons")
        }
        raise ClosurePackError(f"derived closure report is not verified: {failures}")
    report_path = output_root / "foundation_closure_report.json"
    write_json_atomic(report_path, report)

    verification = _fresh_process_verify(
        projection_path=blueprint_path,
        report_path=report_path,
        authority_manifest_path=code_manifest_path,
    )
    verification_path = output_root / "foundation_closure_verification.json"
    write_json_atomic(verification_path, verification)

    manifest_body = {
        "schema_version": "xinao.foundation_closure_pack.v4",
        "authority_projection_ref": evidence_ref(blueprint_path),
        "compiler_code_manifest_ref": code_manifest_ref,
        "authority_snapshot_manifest_ref": code_manifest_ref,
        "report_input_ref": evidence_ref(report_input_path),
        "report_ref": evidence_ref(report_path),
        "verification_ref": evidence_ref(verification_path),
        "fresh_assertion_bundle_receipt_refs": {
            block_id: bundle_receipt_refs[block_id] for block_id in FOUNDATION_BLOCK_IDS
        },
        "artifact_count": sum(len(item["artifact_hashes"]) for item in block_reports.values()),
        "assertion_count": sum(
            len(item["assertion_results"]) for item in block_reports.values()
        ),
        "retained_input_material_count": len(input_refs) - 1,
        "retained_artifact_material_count": sum(
            len(item) for item in prepared_materials.values()
        ),
        "source_materials_self_contained": True,
        "foundation_execution_ready": True,
        "foundation_closed": False,
        "fresh_process_verified": True,
        "fresh_assertion_bundle_verified": True,
    }
    manifest = {**manifest_body, "pack_sha256": canonical_sha256(manifest_body)}
    manifest_path = output_root / "foundation_closure_pack.json"
    write_json_atomic(manifest_path, manifest)
    return {
        "report_input_path": report_input_path,
        "report_path": report_path,
        "verification_path": verification_path,
        "manifest_path": manifest_path,
        "authority_snapshot_manifest_path": code_manifest_path,
        "report": report,
        "verification": verification,
        "manifest": manifest,
    }
