#!/usr/bin/env python3
"""Independently close the current F4 evidence pack without model judgments.

The verifier treats the current-source pack as an unadjudicated compiler output.
It validates the exact bytes against the current executable contracts, freshly
reruns every bound independent verifier, runs the exact package-owned F4 checks, and
derives a content-addressed 14-item evidence map.  The resulting canary report
is an index over that map; it is never accepted as its own proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xinao.foundation.f4_production_checker import GROUPS as PRODUCTION_CHECK_GROUPS
from xinao.foundation.f4_production_checker import SCHEMA_VERSION as CHECKER_SCHEMA
from xinao.foundation.f4_snapshot_runtime import (
    SNAPSHOT_OUTPUT_ROOT_ENV,
    input_path,
    readable_path,
    retained_path,
    snapshot_runtime,
)
from xinao.foundation.f4_snapshot_runtime import (
    file_sha256 as snapshot_file_sha256,
)
from xinao.foundation.f4_snapshot_runtime import (
    inside as snapshot_inside,
)
from xinao.foundation.f4_snapshot_runtime import (
    load_object as snapshot_load_object,
)
from xinao.foundation.f4_snapshot_runtime import (
    same_path as snapshot_same_path,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
XINAO_SRC = Path(__file__).resolve().parents[2]
D_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_PYTHON = Path(sys.executable)
XINAO_PYTHON = DEFAULT_PYTHON

MAP_SCHEMA = "xinao.f4_assertion_evidence_map.v1"
ITEM_SCHEMA = "xinao.f4_assertion_evidence_item.v1"
CANARY_SCHEMA = "xinao.research_factory_canary_report.v1"
RUNS_SCHEMA = "xinao.f4_fresh_verifier_runs.v1"
EVIDENCE_AUDIT_SCHEMA = "xinao.f4_evidence_plane_audit.v1"
OUTPUT_MANIFEST_SCHEMA = "xinao.f4_independent_closure_exact_manifest.v1"

REQUIRED_TYPES = (
    "TypedHandoffSchemaVersion",
    "EvidenceSchemaVersion",
    "ValidationCourtInterfaceVersion",
    "ResearchWorkItemSchemaVersion",
    "DynamicCapacityPolicyVersion",
    "DedupPolicyVersion",
    "DeterministicFanInPolicyVersion",
)
SUPPORTING_TYPES = (
    "OpenMethodRegistrationSchemaVersion",
    "ResearchErrorBudgetPolicySchemaVersion",
)
SOURCE_SPECS = {
    "live_three_stage_runtime": {
        "script": REPO_ROOT / "scripts" / "verify_f4_live_canary_pack.py",
        "schema": "xinao.f4_live_pack_independent_verification.v1",
        "manifest": "artifact_manifest.json",
    },
    "portfolio_source_and_order": {
        "script": REPO_ROOT / "scripts" / "verify_f4_portfolio_source_canary_pack.py",
        "schema": "xinao.f4_portfolio_pack_independent_verification.v1",
        "manifest": "evidence_manifest.json",
    },
    "negative_failure_cancel_recovery": {
        "script": REPO_ROOT / "scripts" / "verify_f4_negative_companion_pack.py",
        "schema": "xinao.f4_negative_pack_independent_verification.v1",
        "manifest": "artifact_manifest.json",
    },
}

ASSERTION_IDS = (
    "typed_handoff_and_evidence_schemas_verified",
    "fixed_time_split_and_leakage_rejection_verified",
    "negative_controls_and_error_budget_verified",
    "canonical_work_key_and_source_dependency_dedup_verified",
    "real_temporal_workflow_history_verified",
    "real_model_identity_and_lane_artifacts_verified",
    "d_drive_evidence_binding_verified",
    "research_portfolio_ready_frontier_verified",
    "dynamic_multi_lane_capacity_ladder_verified",
    "independent_critique_verified",
    "deterministic_fan_in_without_majority_vote_verified",
    "backpressure_partial_failure_cancel_and_recovery_verified",
    "codex_single_writer_boundary_verified",
    "open_method_typed_admission_verified",
)


class VerificationError(ValueError):
    """Raised when retained evidence or a fresh check is incomplete or contradictory."""


@dataclass(frozen=True)
class CurrentPack:
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    compiler_report_path: Path
    compiler_report: dict[str, Any]
    source_bindings_path: Path
    source_bindings: dict[str, Any]
    required_paths: dict[str, Path]
    supporting_paths: dict[str, Path]


@dataclass(frozen=True)
class FreshVerification:
    label: str
    pack: Path
    manifest: Path
    bound_path: Path
    bound: dict[str, Any]
    verifier_script: Path
    verifier_source_sha256: str
    fresh_file_sha256: str
    content_sha256: str
    assertion_count: int
    command: tuple[str, ...]


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return snapshot_file_sha256(path)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _same_path(left: object, right: object) -> bool:
    return snapshot_same_path(left, right)


def _inside(path: object, root: object) -> bool:
    return snapshot_inside(path, root)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = snapshot_load_object(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationError(f"invalid JSON object: {path}") from exc
    return value


def _snapshot_enabled() -> bool:
    return snapshot_runtime() is not None


def _active_python(requested: Path) -> Path:
    candidate = Path(sys.executable) if _snapshot_enabled() else requested
    launcher = Path(os.path.abspath(str(candidate)))
    _require(launcher.is_file(), f"Python executable is missing: {launcher}")
    return launcher


def _output_root() -> Path | None:
    raw = os.environ.get(SNAPSHOT_OUTPUT_ROOT_ENV, "").strip()
    return Path(raw).resolve() if _snapshot_enabled() and raw else None


def _inside_output(path: object) -> bool:
    root = _output_root()
    if root is None:
        return False
    try:
        Path(str(path)).resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _identity_stem(path: object) -> str:
    name = retained_path(path).replace("\\", "/").rsplit("/", 1)[-1]
    return Path(name).stem


def _pretty_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Render stable human-readable JSON with UTF-8 and an LF terminator."""

    return (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_pretty_json_bytes(value))
    return path


def _require_materialized_payload_bytes(
    path: Path,
    payload: Mapping[str, Any],
    *,
    object_type: str,
) -> None:
    _require(
        path.read_bytes() == _pretty_json_bytes(payload),
        f"materialized payload is not byte-for-byte current: {object_type}",
    )


def _content_addressed(value: Mapping[str, Any], *, label: str) -> str:
    content_hash = str(value.get("content_sha256") or "").lower()
    core = dict(value)
    core.pop("content_sha256", None)
    _require(
        len(content_hash) == 64 and canonical_sha256(core) == content_hash,
        f"{label} content identity drifted",
    )
    return content_hash


def _file_ref(path: Path) -> dict[str, Any]:
    resolved = readable_path(path, expect="file")
    _require(resolved.is_file(), f"evidence file is missing: {resolved}")
    return {
        "path": retained_path(resolved),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _typed_file_binding(path: Path) -> dict[str, Any]:
    return {"kind": "file", **_file_ref(path)}


def _require_file_binding(binding: object, path: Path, *, label: str) -> None:
    _require(isinstance(binding, dict), f"{label} binding is absent")
    expected = _typed_file_binding(path)
    _require(dict(binding) == expected, f"{label} file binding drifted")


def _repo_source_from_binding(
    binding: Mapping[str, Any],
    *,
    label: str,
) -> tuple[Path, str]:
    raw_path = str(binding.get("path") or "")
    expected_hash = str(binding.get("sha256") or "")
    expected_size = binding.get("size_bytes")

    def _hash_identical_candidates() -> list[tuple[Path, str]]:
        parts = [part for part in raw_path.replace("\\", "/").split("/") if part]
        candidates: list[tuple[Path, str]] = []
        for index in range(len(parts)):
            relative = Path(*parts[index:])
            candidate = (REPO_ROOT / relative).resolve()
            try:
                candidate.relative_to(REPO_ROOT.resolve())
            except ValueError:
                continue
            if (
                candidate.is_file()
                and candidate.stat().st_size == expected_size
                and file_sha256(candidate) == expected_hash
            ):
                candidates.append((candidate, relative.as_posix()))
        return candidates

    if not _snapshot_enabled():
        path = Path(raw_path).resolve()
        if path.is_file() and _inside(path, REPO_ROOT):
            relative = path.relative_to(REPO_ROOT).as_posix()
        else:
            # A retired checkout path is only a diagnostic identity. Resolve it
            # through an exact hash/size match under the current authority root.
            candidates = _hash_identical_candidates()
            _require(
                candidates,
                f"{label} is outside the current repository and has no "
                f"hash-identical current authority source: {raw_path}",
            )
            path, relative = max(candidates, key=lambda item: len(Path(item[1]).parts))
    else:
        candidates = _hash_identical_candidates()
        _require(candidates, f"{label} has no hash-identical authority source: {raw_path}")
        path, relative = max(candidates, key=lambda item: len(Path(item[1]).parts))
    _require(
        binding.get("sha256") == file_sha256(path)
        and binding.get("size_bytes") == path.stat().st_size,
        f"{label} source seal drifted: {raw_path}",
    )
    return path, relative


def _require_repo_source_binding(
    binding: object,
    expected_relative: str,
    *,
    label: str,
) -> None:
    _require(isinstance(binding, dict), f"{label} binding is absent")
    _, relative = _repo_source_from_binding(binding, label=label)
    _require(
        relative.casefold() == expected_relative.casefold(),
        f"{label} repository identity drifted: {relative}",
    )


def _directory_binding(path: Path) -> dict[str, Any]:
    resolved = input_path(path, expect="directory")
    _require(resolved.is_dir(), f"bound directory is missing: {resolved}")
    entries = [
        {
            "relative_path": item.relative_to(resolved).as_posix(),
            "sha256": file_sha256(item),
            "size_bytes": item.stat().st_size,
        }
        for item in sorted(
            (candidate for candidate in resolved.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(resolved).as_posix(),
        )
    ]
    _require(entries, f"bound directory is empty: {resolved}")
    return {
        "kind": "directory_tree",
        "path": retained_path(resolved),
        "file_count": len(entries),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in entries),
        "tree_sha256": canonical_sha256(entries),
    }


def _verify_exact_manifest(pack: Path) -> tuple[Path, dict[str, Any], dict[str, Path]]:
    pack = input_path(pack, expect="directory")
    manifest_path = pack / "artifact_manifest.json"
    manifest = _load_object(manifest_path)
    _require(
        manifest.get("schema_version") == "xinao.f4_current_evidence_exact_manifest.v1",
        "unexpected current-pack manifest schema",
    )
    _require(_same_path(manifest.get("pack_ref"), pack), "manifest pack_ref drifted")
    content_hash = _content_addressed(manifest, label="current-pack manifest")
    _require(manifest_path.name == "artifact_manifest.json", "manifest name drifted")
    entries = manifest.get("artifacts")
    _require(isinstance(entries, list), "manifest artifacts is not a list")
    _require(len(entries) == 11, "current pack must contain exactly 11 manifest entries")
    _require(manifest.get("artifact_count") == 11, "manifest artifact_count is not 11")

    paths: dict[str, Path] = {}
    identities: list[dict[str, Any]] = []
    for raw in entries:
        _require(isinstance(raw, dict), "manifest entry is not an object")
        relative = str(raw.get("relative_path") or "")
        candidate = (pack / relative).resolve()
        _require(_inside(candidate, pack), f"manifest path escaped pack: {relative}")
        _require(candidate.is_file(), f"manifest artifact is missing: {relative}")
        _require(
            candidate.relative_to(pack).as_posix() == relative,
            f"manifest path is not canonical: {relative}",
        )
        _require(relative not in paths, f"duplicate manifest path: {relative}")
        identity = {
            "relative_path": relative,
            "sha256": file_sha256(candidate),
            "size_bytes": candidate.stat().st_size,
        }
        _require(dict(raw) == identity, f"manifest byte binding drifted: {relative}")
        paths[relative] = candidate
        identities.append(identity)

    _require(
        identities == sorted(identities, key=lambda item: str(item["relative_path"])),
        "manifest entries are not in canonical path order",
    )
    actual = {
        item.relative_to(pack).as_posix()
        for item in pack.rglob("*")
        if item.is_file() and item.resolve() != manifest_path.resolve()
    }
    _require(set(paths) == actual, "manifest is not the exact current-pack file set")
    _require(
        manifest.get("artifact_set_sha256") == canonical_sha256(identities),
        "manifest artifact_set_sha256 drifted",
    )
    _require(len(content_hash) == 64, "manifest content identity is missing")
    return manifest_path, manifest, paths


def _compile_current_payloads() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    for source_root in (REPO_ROOT, XINAO_SRC):
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
    try:
        from xinao.foundation.research_factory import (
            F4_REQUIRED_ARTIFACT_TYPES,
            research_factory_schema_payloads,
            research_factory_supporting_payloads,
            verify_research_factory_artifacts,
        )
        from xinao.foundation.research_weight import verify_versioned_object
    except ImportError as exc:
        raise VerificationError("current research-factory compiler is unavailable") from exc

    required = research_factory_schema_payloads()
    supporting = research_factory_supporting_payloads()
    _require(tuple(F4_REQUIRED_ARTIFACT_TYPES) == REQUIRED_TYPES, "required inventory drifted")
    _require(tuple(required) == REQUIRED_TYPES, "compiled required order drifted")
    _require(tuple(supporting) == SUPPORTING_TYPES, "compiled supporting order drifted")
    verification = verify_research_factory_artifacts(required)
    _require(verification.get("ok") is True, "current factory verification did not complete")
    for object_type, payload in {**required, **supporting}.items():
        _require(
            payload.get("object_type") == object_type and verify_versioned_object(payload),
            f"compiled payload is not content-addressed: {object_type}",
        )
    return required, supporting


def _payload_path(
    manifest_paths: Mapping[str, Path],
    *,
    category: str,
    object_type: str,
    content_hash: str,
) -> Path:
    relative = f"{category}/{object_type}.{content_hash}.json"
    _require(relative in manifest_paths, f"compiled payload is absent: {relative}")
    return manifest_paths[relative]


def _verify_compiled_payloads(
    pack: Path,
    manifest_paths: Mapping[str, Path],
) -> tuple[dict[str, Path], dict[str, Path], dict[str, Any], Path, dict[str, Any], Path]:
    required, supporting = _compile_current_payloads()
    required_paths: dict[str, Path] = {}
    supporting_paths: dict[str, Path] = {}
    for category, payloads, paths in (
        ("required", required, required_paths),
        ("supporting", supporting, supporting_paths),
    ):
        for object_type, payload in payloads.items():
            content_hash = str(payload["content_sha256"])
            path = _payload_path(
                manifest_paths,
                category=category,
                object_type=object_type,
                content_hash=content_hash,
            )
            _require_materialized_payload_bytes(
                path,
                payload,
                object_type=object_type,
            )
            _require(_load_object(path) == payload, f"payload value drifted: {object_type}")
            paths[object_type] = path

    report_path = pack / "compiler_report.json"
    source_path = pack / "source_bindings.json"
    _require(
        manifest_paths.get("compiler_report.json") == report_path,
        "compiler report is absent from manifest",
    )
    _require(
        manifest_paths.get("source_bindings.json") == source_path,
        "source bindings are absent from manifest",
    )
    report = _load_object(report_path)
    source = _load_object(source_path)
    _content_addressed(report, label="compiler report")
    _content_addressed(source, label="source bindings")
    _require(
        report.get("schema_version") == "xinao.f4_current_evidence_compiler_report.v1",
        "compiler report schema drifted",
    )
    _require(
        report.get("compilation_state") == "MATERIALIZED_UNADJUDICATED",
        "compiler report is not unadjudicated materialization",
    )
    _require(
        report.get("verdict_emitted") is False
        and report.get("canary_report_emitted") is False
        and report.get("model_invocations") == 0
        and "status" not in report,
        "compiler report attempted to self-adjudicate",
    )
    _require(_same_path(report.get("pack_ref"), pack), "compiler report pack_ref drifted")
    _require_file_binding(report.get("source_bindings"), source_path, label="source bindings")

    def expected_bindings(payloads: Mapping[str, Mapping[str, Any]], paths: Mapping[str, Path]):
        return [
            {
                "object_type": object_type,
                "version_id": payload["version_id"],
                "content_sha256": payload["content_sha256"],
                "file": _typed_file_binding(paths[object_type]),
            }
            for object_type, payload in payloads.items()
        ]

    _require(
        report.get("required_artifact_count") == 7
        and report.get("required_artifacts") == expected_bindings(required, required_paths),
        "compiler required-artifact bindings drifted",
    )
    _require(
        report.get("supporting_payload_count") == 2
        and report.get("supporting_payloads") == expected_bindings(supporting, supporting_paths),
        "compiler supporting-payload bindings drifted",
    )
    compiler_sources = report.get("compiler_sources")
    _require(isinstance(compiler_sources, dict), "compiler source bindings are absent")
    _require_repo_source_binding(
        compiler_sources.get("builder"),
        "xinao_discovery/src/xinao/foundation/f4_current_evidence_builder.py",
        label="builder source",
    )
    _require_repo_source_binding(
        compiler_sources.get("research_factory"),
        "xinao_discovery/src/xinao/foundation/research_factory.py",
        label="research-factory source",
    )
    return required_paths, supporting_paths, report, report_path, source, source_path


def verify_current_pack(pack: Path) -> CurrentPack:
    pack = input_path(pack, expect="directory")
    _require(pack.is_dir(), f"current evidence pack is missing: {pack}")
    manifest_path, manifest, paths = _verify_exact_manifest(pack)
    required, supporting, report, report_path, source, source_path = _verify_compiled_payloads(
        pack, paths
    )
    return CurrentPack(
        root=pack,
        manifest_path=manifest_path,
        manifest=manifest,
        compiler_report_path=report_path,
        compiler_report=report,
        source_bindings_path=source_path,
        source_bindings=source,
        required_paths=required,
        supporting_paths=supporting,
    )


def _parse_last_json_line(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise VerificationError("subprocess did not emit a JSON result object")


def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    _require(isinstance(argv, (list, tuple)) and bool(argv), "argv must be a non-empty list")
    _require(all(isinstance(item, str) and item for item in argv), "argv contains invalid item")
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        shell=False,
        timeout=timeout_seconds,
        check=False,
    )


def _command_failure_detail(
    label: str,
    completed: subprocess.CompletedProcess[str],
) -> str:
    return (
        f"{label} failed with exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout[-2000:]}\n"
        f"stderr:\n{completed.stderr[-2000:]}"
    )


def _clean_subprocess_env(*, inject_package_snapshot: bool = False) -> dict[str, str]:
    allowed = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if (key.upper() in allowed or key.upper().startswith("XINAO_F4_"))
        and key.upper() != "XINAO_F4_SNAPSHOT_SOFT_PATH_KEYS"
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    package_manifest = os.environ.get("XINAO_F4_PACKAGE_SNAPSHOT_MANIFEST", "").strip()
    if inject_package_snapshot and package_manifest:
        environment["XINAO_F4_SNAPSHOT_MANIFEST"] = package_manifest
        for key in (
            "XINAO_F4_SNAPSHOT_OUTPUT_ROOT",
            "XINAO_F4_SNAPSHOT_TRACE_DIR",
            "XINAO_F4_AUTHORITY_ROOT",
            "XINAO_F4_AUTHORITY_IDENTITY",
            "XINAO_F4_SNAPSHOT_SOFT_PATH_ALLOWLIST",
            "XINAO_F4_SNAPSHOT_SOFT_PATH_ALLOWLIST_SHA256",
            "PYTHONPATH",
            "PYTHONNOUSERSITE",
        ):
            value = os.environ.get(key, "").strip()
            if value:
                environment[key] = value
    return environment


def _bound_sources(source_bindings: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    _require(
        source_bindings.get("schema_version") == "xinao.f4_current_evidence_source_bindings.v1",
        "source bindings schema drifted",
    )
    raw = source_bindings.get("source_packs")
    _require(isinstance(raw, list) and len(raw) == 3, "exactly three source packs required")
    by_label: dict[str, dict[str, Any]] = {}
    for item in raw:
        _require(isinstance(item, dict), "source-pack binding is not an object")
        label = str(item.get("label") or "")
        _require(
            label in SOURCE_SPECS and label not in by_label, f"unexpected source label: {label}"
        )
        by_label[label] = item
    _require(set(by_label) == set(SOURCE_SPECS), "source-pack inventory drifted")
    return by_label


def _validate_bound_verification(
    *,
    label: str,
    binding: Mapping[str, Any],
) -> tuple[Path, Path, Path, dict[str, Any]]:
    spec = SOURCE_SPECS[label]
    pack_binding = binding.get("pack")
    manifest_binding = binding.get("pack_manifest")
    verification_binding = binding.get("independent_verification")
    _require(
        isinstance(pack_binding, dict)
        and isinstance(manifest_binding, dict)
        and isinstance(verification_binding, dict),
        f"{label} binding is incomplete",
    )
    pack = input_path(pack_binding.get("path") or "", expect="directory")
    manifest = pack / str(spec["manifest"])
    bound_path = input_path(verification_binding.get("path") or "", expect="file")
    _require(pack_binding == _directory_binding(pack), f"{label} source tree drifted")
    _require_file_binding(manifest_binding, manifest, label=f"{label} manifest")
    expected_verification_binding = {
        **_typed_file_binding(bound_path),
        "schema_version": verification_binding.get("schema_version"),
        "content_sha256": verification_binding.get("content_sha256"),
        "verification_status": verification_binding.get("verification_status"),
    }
    _require(
        dict(verification_binding) == expected_verification_binding,
        f"{label} verification file binding drifted",
    )
    bound = _load_object(bound_path)
    content_hash = _content_addressed(bound, label=f"{label} bound verification")
    _require(_identity_stem(bound_path) == content_hash, f"{label} verification filename drifted")
    _require(
        bound.get("schema_version") == spec["schema"]
        and bound.get("status") == "VERIFIED"
        and verification_binding.get("verification_status") == "VERIFIED"
        and verification_binding.get("content_sha256") == content_hash,
        f"{label} bound verification state drifted",
    )
    source_pack = bound.get("source_pack_ref") or bound.get("source_pack")
    manifest_hash = bound.get("source_pack_manifest_sha256") or bound.get("source_manifest_sha256")
    _require(_same_path(source_pack, pack), f"{label} verification identifies another pack")
    _require(manifest_hash == file_sha256(manifest), f"{label} manifest hash drifted")
    assertions = bound.get("assertions")
    _require(isinstance(assertions, dict) and assertions, f"{label} assertions are absent")
    _require(
        bound.get("assertion_count") == len(assertions),
        f"{label} assertion_count drifted",
    )
    return pack, manifest, bound_path, bound


def rerun_bound_verifiers(
    current: CurrentPack,
    *,
    python_executable: Path,
    timeout_seconds: int = 900,
) -> dict[str, FreshVerification]:
    python_executable = _active_python(python_executable)
    sources = _bound_sources(current.source_bindings)
    results: dict[str, FreshVerification] = {}
    output_root = _output_root()
    package_output = os.environ.get("XINAO_F4_SNAPSHOT_OUTPUT_ROOT", "").strip()
    if output_root is not None:
        temp_parent = output_root / "fresh"
    elif package_output:
        temp_parent = Path(package_output).resolve() / "fresh"
    else:
        temp_parent = current.root.parent
    temp_parent.mkdir(parents=True, exist_ok=True)
    for label, binding in sources.items():
        pack, manifest, bound_path, bound = _validate_bound_verification(
            label=label,
            binding=binding,
        )
        script = readable_path(SOURCE_SPECS[label]["script"], expect="file")
        _require(script.is_file(), f"verifier source is missing: {script}")
        verifier_hash = file_sha256(script)
        recorded_source_hash = bound.get("verifier_source_sha256")
        if recorded_source_hash is not None:
            _require(
                recorded_source_hash == verifier_hash,
                f"{label} bound verifier source no longer matches current code",
            )
        with tempfile.TemporaryDirectory(prefix=f"f4-{label}-", dir=temp_parent) as raw_temp:
            output_dir = Path(raw_temp)
            argv = (
                str(python_executable),
                "-I",
                str(script),
                "--pack",
                str(pack),
                "--output-dir",
                str(output_dir),
            )
            completed = _run_command(
                argv,
                cwd=REPO_ROOT,
                timeout_seconds=timeout_seconds,
                env=_clean_subprocess_env(inject_package_snapshot=True),
            )
            _require(
                completed.returncode == 0,
                _command_failure_detail(f"{label} fresh verifier", completed),
            )
            emitted = _parse_last_json_line(completed.stdout)
            fresh_path = Path(
                str(emitted.get("verification_ref") or emitted.get("output") or "")
            ).resolve()
            _require(_inside(fresh_path, output_dir), f"{label} wrote outside fresh output")
            fresh = _load_object(fresh_path)
            fresh_content_hash = _content_addressed(fresh, label=f"{label} fresh verification")
            _require(
                fresh_content_hash == bound["content_sha256"]
                and fresh == bound
                and emitted.get("content_sha256") == fresh_content_hash,
                f"{label} fresh verification is not exact bound content",
            )
            results[label] = FreshVerification(
                label=label,
                pack=pack,
                manifest=manifest,
                bound_path=bound_path,
                bound=bound,
                verifier_script=script,
                verifier_source_sha256=verifier_hash,
                fresh_file_sha256=file_sha256(fresh_path),
                content_sha256=fresh_content_hash,
                assertion_count=len(fresh["assertions"]),
                command=(*argv[:-1], "<ephemeral-output-dir>"),
            )
    return results


def run_targeted_checker(*, timeout_seconds: int = 900) -> dict[str, Any]:
    python_executable = _active_python(XINAO_PYTHON)
    checker_source = XINAO_SRC / "xinao" / "foundation" / "f4_production_checker.py"
    _require(checker_source.is_file(), f"production checker source is missing: {checker_source}")
    bootstrap = (
        "import sys;"
        f"sys.path.insert(0,{str(XINAO_SRC)!r});"
        "from xinao.foundation.f4_production_checker import main;"
        "raise SystemExit(main())"
    )
    argv = (
        str(python_executable),
        "-X",
        "faulthandler",
        "-I",
        "-c",
        bootstrap,
    )
    completed = _run_command(
        argv,
        cwd=REPO_ROOT,
        timeout_seconds=timeout_seconds,
        env=_clean_subprocess_env(),
    )
    _require(
        completed.returncode == 0,
        "package-owned F4 checker failed:\n" + completed.stdout[-3000:] + completed.stderr[-3000:],
    )
    result = _parse_last_json_line(completed.stdout)
    content_hash = _content_addressed(result, label="package-owned F4 checker")
    expected_ids = tuple(
        check_id for group in PRODUCTION_CHECK_GROUPS.values() for check_id in group
    )
    check_rows = result.get("checks")
    _require(
        result.get("schema_version") == CHECKER_SCHEMA
        and result.get("status") == "VERIFIED"
        and result.get("group_count") == len(PRODUCTION_CHECK_GROUPS)
        and result.get("groups")
        == {key: list(value) for key, value in PRODUCTION_CHECK_GROUPS.items()}
        and result.get("check_count") == len(expected_ids) == 17
        and result.get("verified_check_count") == 17
        and result.get("pytest_loaded") is False
        and result.get("checker_source_sha256") == file_sha256(checker_source)
        and isinstance(check_rows, list)
        and tuple(row.get("check_id") for row in check_rows) == expected_ids
        and all(row.get("status") == "VERIFIED" for row in check_rows)
        and len(content_hash) == 64,
        "package-owned F4 checker result drifted",
    )
    return result


def _runtime_ref(path: Path, *, label: str) -> dict[str, Any]:
    resolved = input_path(path)
    _require(
        _inside(resolved, D_RUNTIME_ROOT), f"runtime/data ref is outside D runtime: {resolved}"
    )
    _require(resolved.exists(), f"runtime/data ref is missing: {resolved}")
    return {
        "label": label,
        "path": retained_path(resolved),
        "kind": "directory" if resolved.is_dir() else "file",
    }


def audit_evidence_plane(
    current: CurrentPack,
    fresh: Mapping[str, FreshVerification],
) -> dict[str, Any]:
    """Classify runtime evidence separately from current repository code sources."""

    runtime_refs: dict[str, dict[str, Any]] = {}
    code_refs: dict[str, dict[str, Any]] = {}

    def add_runtime(path: Path, label: str) -> None:
        ref = _runtime_ref(path, label=label)
        runtime_refs[str(ref["path"])] = ref

    def add_code_ref(raw: Mapping[str, Any], label: str) -> None:
        path, relative = _repo_source_from_binding(raw, label=label)
        code_refs[relative] = {
            "label": label,
            "repo_relative_path": relative,
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        }

    add_runtime(current.root, "current_source_pack")
    add_runtime(current.manifest_path, "current_source_manifest")
    add_runtime(current.compiler_report_path, "current_compiler_report")
    add_runtime(current.source_bindings_path, "current_source_bindings")
    for object_type, path in {**current.required_paths, **current.supporting_paths}.items():
        add_runtime(path, f"current_payload:{object_type}")

    compiler_sources = current.compiler_report["compiler_sources"]
    add_code_ref(compiler_sources["builder"], "current_pack_builder")
    add_code_ref(compiler_sources["research_factory"], "current_research_factory")

    for label, result in fresh.items():
        add_runtime(result.pack, f"{label}:source_pack")
        add_runtime(result.manifest, f"{label}:source_manifest")
        add_runtime(result.bound_path, f"{label}:bound_verification")
        verifier_relative = result.verifier_script.relative_to(REPO_ROOT).as_posix()
        code_refs[verifier_relative] = {
            "label": f"{label}:fresh_verifier",
            "repo_relative_path": verifier_relative,
            "sha256": result.verifier_source_sha256,
            "size_bytes": result.verifier_script.stat().st_size,
        }
        assertions = result.bound.get("assertions")
        _require(isinstance(assertions, dict), f"{label} assertion map missing")
        for assertion_id, assertion in assertions.items():
            _require(isinstance(assertion, dict), f"{label}:{assertion_id} is invalid")
            refs = assertion.get("evidence_refs")
            _require(isinstance(refs, list), f"{label}:{assertion_id} refs missing")
            for index, raw in enumerate(refs):
                _require(isinstance(raw, dict), f"{label}:{assertion_id} ref invalid")
                raw_path = str(raw.get("path") or "")
                if _inside(raw_path, D_RUNTIME_ROOT):
                    path = input_path(raw_path, expect="file")
                    _require(path.is_file(), f"runtime evidence is missing: {path}")
                    _require(
                        raw.get("sha256") == file_sha256(path)
                        and raw.get("size_bytes") == path.stat().st_size,
                        f"runtime evidence seal drifted: {path}",
                    )
                    add_runtime(path, f"{label}:{assertion_id}:{index}")
                else:
                    add_code_ref(raw, f"{label}:{assertion_id}:{index}")

    behavior = current.source_bindings.get("behavior_regression")
    _require(isinstance(behavior, dict), "behavior regression binding is missing")
    summary = behavior.get("summary")
    _require(isinstance(summary, dict), "behavior summary binding is missing")
    summary_path = input_path(summary.get("path") or "", expect="file")
    _require_file_binding(summary, summary_path, label="behavior summary")
    add_runtime(summary_path, "behavior_regression_summary")

    core = {
        "schema_version": EVIDENCE_AUDIT_SCHEMA,
        "classification": {
            "runtime_data_rule": (
                "pack/history/request/payload/result/manifest and /evidence material must be "
                "under D runtime"
            ),
            "code_source_rule": (
                "checker/verifier/test/workflow source must resolve to the sealed current "
                "authority tree with matching repository-relative identity, hash, and size"
            ),
        },
        "runtime_data_ref_count": len(runtime_refs),
        "runtime_data_refs": [runtime_refs[key] for key in sorted(runtime_refs)],
        "code_source_ref_count": len(code_refs),
        "code_source_refs": [code_refs[key] for key in sorted(code_refs)],
        "runtime_data_outside_d_count": 0,
        "unsealed_code_source_count": 0,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def _fresh_runs_record(fresh: Mapping[str, FreshVerification]) -> dict[str, Any]:
    runs = []
    for label in SOURCE_SPECS:
        value = fresh[label]
        runs.append(
            {
                "label": label,
                "argv": list(value.command),
                "shell": False,
                "source_pack_ref": retained_path(value.pack),
                "source_manifest_sha256": file_sha256(value.manifest),
                "bound_verification_ref": retained_path(value.bound_path),
                "bound_verification_file_sha256": file_sha256(value.bound_path),
                "fresh_verification_file_sha256": value.fresh_file_sha256,
                "content_sha256": value.content_sha256,
                "assertion_count": value.assertion_count,
                "verifier_source_sha256": value.verifier_source_sha256,
            }
        )
    core = {
        "schema_version": RUNS_SCHEMA,
        "python_executable": runs[0]["argv"][0],
        "run_count": len(runs),
        "runs": runs,
        "fresh_exact_content_equals_bound_count": len(runs),
        "source_report_boolean_trust_count": 0,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def _observed(result: FreshVerification, assertion_id: str) -> dict[str, Any]:
    assertion = result.bound["assertions"].get(assertion_id)
    _require(isinstance(assertion, dict), f"bound assertion is missing: {assertion_id}")
    observed = assertion.get("observed")
    _require(isinstance(observed, dict), f"bound observation is missing: {assertion_id}")
    return dict(observed)


def _evidence_item(
    assertion_id: str,
    *,
    scope: str,
    observed: Mapping[str, Any],
    evidence_paths: Iterable[Path],
) -> dict[str, Any]:
    refs_by_path = {retained_path(path): _file_ref(path) for path in evidence_paths}
    refs = [refs_by_path[key] for key in sorted(refs_by_path)]
    _require(refs, f"assertion has no evidence refs: {assertion_id}")
    for ref in refs:
        _require(
            _inside(ref["path"], D_RUNTIME_ROOT) or _inside_output(ref["path"]),
            "final assertion evidence ref is not runtime input or authorized output: "
            f"{ref['path']}",
        )
    core = {
        "schema_version": ITEM_SCHEMA,
        "assertion_id": assertion_id,
        "verification_state": "VERIFIED",
        "scope": scope,
        "observed": dict(observed),
        "evidence_refs": refs,
        "evidence_set_sha256": canonical_sha256(refs),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def build_assertion_evidence_map(
    current: CurrentPack,
    fresh: Mapping[str, FreshVerification],
    *,
    runs_path: Path,
    checker_path: Path,
    audit_path: Path,
) -> dict[str, Any]:
    live = fresh["live_three_stage_runtime"]
    portfolio = fresh["portfolio_source_and_order"]
    negative = fresh["negative_failure_cancel_recovery"]

    def p(*items: Path) -> list[Path]:
        return list(items)

    live_histories = _observed(live, "six_external_workflow_histories_replay")
    continuity = _observed(live, "worker_restart_continuity")
    route_models = _observed(live, "all_operations_exact_route_models_read_only")
    operations = _observed(live, "nine_operations_spec_result_manifest_bound")
    identity = _observed(live, "stage_binding_and_identity_separation")
    capacity = _observed(live, "stage_width_capacity_sequence")
    fanin = _observed(live, "deterministic_fanin_without_majority_vote")
    portfolio_surface = _observed(portfolio, "f3_selection_surface_exact_13_family_coverage")
    allocation = _observed(portfolio, "weighted_allocation_rank_independently_recomputed")
    decision = _observed(portfolio, "strict_decision_payload_uses_allocation_prefix")
    portfolio_negatives = _observed(portfolio, "four_negative_controls_actually_rejected")
    write_boundary = _observed(portfolio, "three_worker_write_boundary_mutations_rejected")
    negative_replay = _observed(negative, "three_cases_nine_histories_sdk_replay")
    backpressure = _observed(negative, "available_slots_zero_backpressure")
    partial = _observed(negative, "external_failure_partial_downshift_recovery")
    cancel = _observed(negative, "exact_cancel_and_fresh_recovery")

    items = {
        "typed_handoff_and_evidence_schemas_verified": _evidence_item(
            "typed_handoff_and_evidence_schemas_verified",
            scope="current executable typed handoff, evidence, and work-item schemas",
            observed={
                "required_schema_count": 3,
                "object_types": [
                    "TypedHandoffSchemaVersion",
                    "EvidenceSchemaVersion",
                    "ResearchWorkItemSchemaVersion",
                ],
                "factory_schema_check_ids": list(
                    PRODUCTION_CHECK_GROUPS["factory_schema_current_and_tamper"]
                ),
            },
            evidence_paths=p(
                current.required_paths["TypedHandoffSchemaVersion"],
                current.required_paths["EvidenceSchemaVersion"],
                current.required_paths["ResearchWorkItemSchemaVersion"],
                checker_path,
            ),
        ),
        "fixed_time_split_and_leakage_rejection_verified": _evidence_item(
            "fixed_time_split_and_leakage_rejection_verified",
            scope=(
                "generic fixed split/partition identity, purge horizon, walk-forward ordering, "
                "and future-leak rejection"
            ),
            observed={
                "exact_check_ids": list(PRODUCTION_CHECK_GROUPS["fixed_time_split_and_leakage"]),
                "active_domain_instance_bound": False,
                "future_leak_negative_exercised": True,
                "unpurged_fold_negative_exercised": True,
            },
            evidence_paths=p(
                current.required_paths["ValidationCourtInterfaceVersion"], checker_path
            ),
        ),
        "negative_controls_and_error_budget_verified": _evidence_item(
            "negative_controls_and_error_budget_verified",
            scope="typed research error budget plus exercised negative controls",
            observed={
                "error_budget_check_ids": list(
                    PRODUCTION_CHECK_GROUPS["negative_controls_and_error_budget"]
                ),
                "portfolio_negative_controls": portfolio_negatives,
            },
            evidence_paths=p(
                current.supporting_paths["ResearchErrorBudgetPolicySchemaVersion"],
                portfolio.bound_path,
                checker_path,
            ),
        ),
        "canonical_work_key_and_source_dependency_dedup_verified": _evidence_item(
            "canonical_work_key_and_source_dependency_dedup_verified",
            scope=(
                "canonical work identity, mirror collapse, dependency ordering, and cycle rejection"
            ),
            observed={
                "exact_check_ids": list(
                    PRODUCTION_CHECK_GROUPS["canonical_work_key_and_dependency_dedup"]
                ),
                "check_count": len(
                    PRODUCTION_CHECK_GROUPS["canonical_work_key_and_dependency_dedup"]
                ),
            },
            evidence_paths=p(current.required_paths["DedupPolicyVersion"], checker_path),
        ),
        "real_temporal_workflow_history_verified": _evidence_item(
            "real_temporal_workflow_history_verified",
            scope="retained Temporal histories independently decoded and SDK replayed",
            observed={
                "live": live_histories,
                "restart_continuity": continuity,
                "negative": negative_replay,
            },
            evidence_paths=p(live.bound_path, negative.bound_path, runs_path),
        ),
        "real_model_identity_and_lane_artifacts_verified": _evidence_item(
            "real_model_identity_and_lane_artifacts_verified",
            scope=(
                "nine real Grok read-only operations with exact selected-session and provider-"
                "backend identities plus bound spec/result/manifest bytes"
            ),
            observed={"route_models": route_models, "operations": operations},
            evidence_paths=p(live.bound_path, runs_path),
        ),
        "d_drive_evidence_binding_verified": _evidence_item(
            "d_drive_evidence_binding_verified",
            scope="runtime/data evidence on D; repository code sources separately hash sealed",
            observed={
                "runtime_data_outside_d_count": 0,
                "code_source_policy": "E_REPOSITORY_ALLOWED_ONLY_WITH_CURRENT_HASH_AND_SIZE",
            },
            evidence_paths=p(
                current.manifest_path,
                current.source_bindings_path,
                audit_path,
                live.bound_path,
                portfolio.bound_path,
                negative.bound_path,
            ),
        ),
        "research_portfolio_ready_frontier_verified": _evidence_item(
            "research_portfolio_ready_frontier_verified",
            scope=(
                "current 13-family source surface, weighted ready frontier, and allocation prefix"
            ),
            observed={
                "surface": portfolio_surface,
                "allocation": allocation,
                "decision": decision,
            },
            evidence_paths=p(portfolio.bound_path, runs_path),
        ),
        "dynamic_multi_lane_capacity_ladder_verified": _evidence_item(
            "dynamic_multi_lane_capacity_ladder_verified",
            scope="dynamic 3-to-3-to-3 stage ladder plus bounded capacity/downshift evidence",
            observed={"positive_capacity": capacity, "negative_downshift": partial},
            evidence_paths=p(
                current.required_paths["DynamicCapacityPolicyVersion"],
                live.bound_path,
                negative.bound_path,
            ),
        ),
        "independent_critique_verified": _evidence_item(
            "independent_critique_verified",
            scope="producer, critic, and verifier identities remain stage separated",
            observed=identity,
            evidence_paths=p(live.bound_path),
        ),
        "deterministic_fan_in_without_majority_vote_verified": _evidence_item(
            "deterministic_fan_in_without_majority_vote_verified",
            scope="hash/order deterministic fan-in with no majority-vote authority",
            observed=fanin,
            evidence_paths=p(
                current.required_paths["DeterministicFanInPolicyVersion"],
                live.bound_path,
            ),
        ),
        "backpressure_partial_failure_cancel_and_recovery_verified": _evidence_item(
            "backpressure_partial_failure_cancel_and_recovery_verified",
            scope="zero-slot wait, partial failure downshift, exact cancel, and fresh recovery",
            observed={
                "backpressure": backpressure,
                "partial_failure": partial,
                "cancel_and_recovery": cancel,
                "replay": negative_replay,
            },
            evidence_paths=p(negative.bound_path, runs_path),
        ),
        "codex_single_writer_boundary_verified": _evidence_item(
            "codex_single_writer_boundary_verified",
            scope="read-only worker lanes and three exercised write-boundary rejections",
            observed={
                "live_model_lanes": route_models,
                "portfolio_write_boundary": write_boundary,
            },
            evidence_paths=p(live.bound_path, portfolio.bound_path, runs_path),
        ),
        "open_method_typed_admission_verified": _evidence_item(
            "open_method_typed_admission_verified",
            scope="typed method registration admits new methods without a hard-coded whitelist",
            observed={
                "exact_check_ids": list(PRODUCTION_CHECK_GROUPS["open_method_typed_admission"]),
                "positive_and_negative_admission_exercised": True,
            },
            evidence_paths=p(
                current.supporting_paths["OpenMethodRegistrationSchemaVersion"],
                current.required_paths["ResearchWorkItemSchemaVersion"],
                checker_path,
            ),
        ),
    }
    _require(tuple(items) == ASSERTION_IDS, "14-item assertion inventory/order drifted")
    _require(len(items) == 14, "assertion map does not contain exactly 14 items")
    core = {
        "schema_version": MAP_SCHEMA,
        "object_type": "F4AssertionEvidenceMap",
        "verification_state": "VERIFIED",
        "assertion_count": len(items),
        "assertion_ids": list(items),
        "assertions": items,
        "current_source_pack_ref": retained_path(current.root),
        "current_source_manifest": _file_ref(current.manifest_path),
        "fresh_verifier_runs": _file_ref(runs_path),
        "targeted_checker": _file_ref(checker_path),
        "evidence_plane_audit": _file_ref(audit_path),
        "derivation": (
            "current executable artifacts plus fresh subprocess exact-content equality plus exact "
            "package-owned production checks; no source report boolean is accepted as authority"
        ),
        "model_invocations": 0,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def build_canary_report(
    current: CurrentPack,
    evidence_map: Mapping[str, Any],
    evidence_map_path: Path,
    fresh: Mapping[str, FreshVerification],
) -> dict[str, Any]:
    _require(
        evidence_map.get("object_type") == "F4AssertionEvidenceMap"
        and evidence_map.get("assertion_ids") == list(ASSERTION_IDS)
        and evidence_map.get("assertion_count") == 14,
        "canary report input is not the exact 14-item evidence map",
    )
    assertion_states = {
        assertion_id: evidence_map["assertions"][assertion_id]["verification_state"]
        for assertion_id in ASSERTION_IDS
    }
    _require(set(assertion_states.values()) == {"VERIFIED"}, "assertion map is incomplete")
    core = {
        "schema_version": CANARY_SCHEMA,
        "object_type": "ResearchFactoryCanaryReport",
        "status": "VERIFIED",
        "report_role": "INDEX_ONLY_NOT_PROOF",
        "report_is_evidence_authority": False,
        "source_report_boolean_trust_count": 0,
        "current_source_pack_ref": retained_path(current.root),
        "current_source_manifest": _file_ref(current.manifest_path),
        "f4_assertion_evidence_map": _file_ref(evidence_map_path),
        "f4_assertion_evidence_map_content_sha256": evidence_map["content_sha256"],
        "assertion_count": 14,
        "assertion_ids": list(ASSERTION_IDS),
        "assertion_states": assertion_states,
        "source_verification_content_sha256": {
            label: fresh[label].content_sha256 for label in SOURCE_SPECS
        },
        "current_artifact_content_sha256": {
            object_type: _load_object(path)["content_sha256"]
            for object_type, path in {
                **current.required_paths,
                **current.supporting_paths,
            }.items()
        },
        "model_invocations": 0,
    }
    content_hash = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchFactoryCanaryReport@{content_hash[:16]}",
        "content_sha256": content_hash,
    }


def _output_manifest(output: Path) -> dict[str, Any]:
    manifest_path = output / "artifact_manifest.json"
    entries = [
        {
            "relative_path": path.relative_to(output).as_posix(),
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            (
                candidate
                for candidate in output.rglob("*")
                if candidate.is_file() and candidate.resolve() != manifest_path.resolve()
            ),
            key=lambda candidate: candidate.relative_to(output).as_posix(),
        )
    ]
    core = {
        "schema_version": OUTPUT_MANIFEST_SCHEMA,
        "pack_ref": retained_path(output),
        "artifact_count": len(entries),
        "artifacts": entries,
        "artifact_set_sha256": canonical_sha256(entries),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def verify_f4_current_evidence_pack(
    *,
    pack: Path,
    output_dir: Path,
    python_executable: Path = DEFAULT_PYTHON,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    current = verify_current_pack(pack)
    fresh = rerun_bound_verifiers(
        current,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    checker = run_targeted_checker(timeout_seconds=timeout_seconds)
    evidence_audit = audit_evidence_plane(current, fresh)
    runs = _fresh_runs_record(fresh)

    output = output_dir.resolve()
    _require(not output.exists(), f"output already exists: {output}")
    _require(
        _inside_output(output) if _snapshot_enabled() else _inside(output, D_RUNTIME_ROOT),
        "independent closure output must be under D runtime or the authorized OCI output",
    )
    output.mkdir(parents=True, exist_ok=False)
    runs_path = _write_json(output / "fresh_verifier_runs.json", runs)
    checker_path = _write_json(output / "current_source_specialized_checker.json", checker)
    audit_path = _write_json(output / "evidence_plane_audit.json", evidence_audit)

    evidence_map = build_assertion_evidence_map(
        current,
        fresh,
        runs_path=runs_path,
        checker_path=checker_path,
        audit_path=audit_path,
    )
    map_path = _write_json(
        output / f"F4AssertionEvidenceMap.{evidence_map['content_sha256']}.json",
        evidence_map,
    )
    canary = build_canary_report(current, evidence_map, map_path, fresh)
    canary_path = _write_json(
        output / f"ResearchFactoryCanaryReport.{canary['content_sha256']}.json",
        canary,
    )
    manifest = _output_manifest(output)
    manifest_path = _write_json(output / "artifact_manifest.json", manifest)
    return {
        "ok": True,
        "status": "VERIFIED",
        "source_pack_ref": retained_path(current.root),
        "output_ref": retained_path(output),
        "artifact_manifest_ref": retained_path(manifest_path),
        "artifact_manifest_sha256": file_sha256(manifest_path),
        "f4_assertion_evidence_map_ref": retained_path(map_path),
        "f4_assertion_evidence_map_content_sha256": evidence_map["content_sha256"],
        "research_factory_canary_report_ref": retained_path(canary_path),
        "research_factory_canary_report_content_sha256": canary["content_sha256"],
        "assertion_count": 14,
        "fresh_verifier_count": 3,
        "production_check_count": 17,
        "model_invocations": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output_dir or args.pack.parent / (
        f"{args.pack.name}-independent-closure-verification"
    )
    result = verify_f4_current_evidence_pack(
        pack=args.pack,
        output_dir=output,
        python_executable=args.python,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
