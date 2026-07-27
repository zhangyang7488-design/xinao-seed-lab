#!/usr/bin/env python3
"""Seal one neutral package DAG and bind one or more worker-leg envelopes to it."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.dispatch_economics import (  # noqa: E402
    DispatchEconomicsError,
    build_route_choice_identity,
    build_worker_package_identity,
    neutral_output_contract_sha256,
    plan_package_frontier,
    validate_dispatch_envelope,
    validate_package_batch_manifest,
)
from services.agent_runtime.grok_execution_contract_adapter import (  # noqa: E402
    GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
    GROK_DOCKER_ROUTE_TRANSPORT_ID,
    build_grok_docker_route_adapter_binding,
    validate_grok_route_selection_receipt,
)

PathResolver = Callable[[str], str | Path]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _logical_path(value: object, label: str) -> str:
    logical = str(value or "").strip()
    if not logical:
        raise ValueError(f"{label} must be a non-empty logical path")
    return logical


def _resolve_path(
    logical: str,
    *,
    path_resolver: PathResolver | None,
) -> Path:
    resolved = path_resolver(logical) if path_resolver is not None else Path(logical)
    return Path(resolved).resolve(strict=True)


def _path_ref(
    logical: str,
    *,
    path_resolver: PathResolver | None,
) -> dict[str, str]:
    return {"path": logical, "sha256": _sha(_resolve_path(logical, path_resolver=path_resolver))}


def _atomic_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


_SENSITIVE_SNAPSHOT_NAMES = {
    ".env",
    "auth.json",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
_SENSITIVE_SNAPSHOT_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
_SENSITIVE_SNAPSHOT_TOKENS = {
    "credential",
    "credentials",
    "secret",
    "secrets",
    "token",
    "tokens",
}
_EXTERNAL_INPUT_ADMISSION = {
    "status": "owner_reviewed_redacted",
    "scope": "all_package_sources",
    "reviewer_role": "codex_owner",
}


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _snapshot_physical_root(snapshot_root: Path) -> Path:
    """Create one real directory root without traversing a junction/symlink."""

    requested = Path(snapshot_root).absolute()
    for candidate in [requested, *requested.parents]:
        if candidate.exists() and _is_reparse_point(candidate):
            raise ValueError(f"input snapshot root traverses a reparse point: {candidate}")
    requested.mkdir(parents=True, exist_ok=True)
    if not requested.is_dir() or _is_reparse_point(requested):
        raise ValueError(f"input snapshot root must be a real directory: {requested}")
    return requested.resolve(strict=True)


def _require_snapshot_source_allowed(source: Path) -> None:
    lowered = source.name.lower()
    compact_stem = re.sub(r"[^a-z0-9]+", "", source.stem.lower())
    name_tokens = {token for token in re.split(r"[^a-z0-9]+", source.stem.lower()) if token}
    has_sensitive_marker = bool(name_tokens & _SENSITIVE_SNAPSHOT_TOKENS) or (
        "apikey" in compact_stem
    )
    if (
        lowered.startswith(".env")
        or lowered in _SENSITIVE_SNAPSHOT_NAMES
        or source.suffix.lower() in _SENSITIVE_SNAPSHOT_SUFFIXES
        or has_sensitive_marker
    ):
        raise ValueError(
            "sensitive input cannot be snapshotted; provide an owner-reviewed redacted sealed file: "
            f"{source}"
        )


def _require_external_input_admission(spec: Mapping[str, object]) -> dict[str, str]:
    raw = spec.get("external_input_admission")
    if not isinstance(raw, Mapping) or dict(raw) != _EXTERNAL_INPUT_ADMISSION:
        raise ValueError(
            "package spec requires external_input_admission declaring all package sources "
            "owner-reviewed and redacted"
        )
    return dict(_EXTERNAL_INPUT_ADMISSION)


def _safe_snapshot_component(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} must be non-empty")
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)
    if not safe or safe in {".", ".."}:
        raise ValueError(f"{label} cannot form a safe snapshot component")
    # Sanitising and truncating alone is lossy (`a/b`, `a_b`, and long shared
    # prefixes can collide).  Keep a readable prefix but bind the directory to
    # the complete original package identity.
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{safe[:79]}-{digest}"


def _provider_visible_input_logicals(
    raw_package: Mapping[str, object], package_index: int
) -> list[str]:
    """Return the one ordered input set that crosses the provider seam."""

    raw_inputs = raw_package.get("input_paths")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError(f"packages[{package_index}] requires input_paths")
    explicit = [
        _logical_path(
            value,
            f"packages[{package_index}].input_paths[{item_index}]",
        )
        for item_index, value in enumerate(raw_inputs)
    ]
    if len(set(explicit)) != len(explicit):
        raise ValueError(
            f"packages[{package_index}].input_paths collapse to duplicate sealed inputs"
        )

    visible = list(explicit)
    if str(raw_package.get("work_class") or "").strip() == "audit_repair":
        audit_values = [
            _logical_path(
                raw_package.get("audit_assessment_path"),
                f"packages[{package_index}].audit_assessment_path",
            ),
            _logical_path(
                raw_package.get("audit_adjudication_path"),
                f"packages[{package_index}].audit_adjudication_path",
            ),
        ]
        prior_values = raw_package.get("prior_audit_adjudication_paths", [])
        if not isinstance(prior_values, list):
            raise TypeError(
                f"packages[{package_index}].prior_audit_adjudication_paths must be an array"
            )
        audit_values.extend(
            _logical_path(
                value,
                f"packages[{package_index}].prior_audit_adjudication_paths[]",
            )
            for value in prior_values
        )
        for logical in audit_values:
            if logical not in visible:
                visible.append(logical)
    return visible


def _snapshot_bytes(raw: bytes, target: Path, *, expected_sha256: str, root: Path) -> None:
    """Create one content-addressed file exclusively, or verify an identical prior copy."""

    resolved_parent = target.parent.resolve(strict=False)
    if not resolved_parent.is_relative_to(root):
        raise ValueError(f"input snapshot target escapes root: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(target.parent):
        raise ValueError(f"input snapshot target parent is a reparse point: {target.parent}")
    if target.exists():
        if _is_reparse_point(target) or not target.is_file() or _sha(target) != expected_sha256:
            raise FileExistsError(f"input snapshot collision: {target}")
        return

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_BINARY", 0))
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError:
        if _is_reparse_point(target) or not target.is_file() or _sha(target) != expected_sha256:
            raise FileExistsError(f"input snapshot collision: {target}") from None
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if _sha(target) != expected_sha256:
            raise OSError(f"input snapshot writeback drifted: {target}")
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def snapshot_package_spec_inputs(
    spec: Mapping[str, object],
    *,
    snapshot_root: Path,
    snapshot_ref_root: str | None = None,
    path_resolver: PathResolver | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, Path]]:
    """Rewrite mutable package sources to a content-addressed local closure.

    The original paths remain provenance only.  Worker manifests bind the
    copied bytes, so later edits to live Skills, handoffs, prompts, rules, or
    source material cannot invalidate or silently change an already sealed
    batch.  Generated audit/adoption receipts keep their own typed identity
    paths and are intentionally outside this source snapshot operation.
    """

    rewritten = copy.deepcopy(dict(spec))
    external_input_admission = _require_external_input_admission(rewritten)
    raw_packages = rewritten.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ValueError("package spec requires packages")
    physical_base = _snapshot_physical_root(snapshot_root)
    logical_base = str(snapshot_ref_root or physical_base).rstrip("/\\")
    if not logical_base:
        raise ValueError("input snapshot logical root must be non-empty")
    source_cache: dict[tuple[str, str], dict[str, object]] = {}

    def preload(value: object, label: str, role: str, package_id: str) -> None:
        source_logical = _logical_path(value, label)
        key = (package_id, source_logical)
        cached = source_cache.get(key)
        if cached is None:
            source_physical = _resolve_path(source_logical, path_resolver=path_resolver)
            _require_snapshot_source_allowed(source_physical)
            raw = source_physical.read_bytes()
            cached = {
                "source_physical": source_physical,
                "raw": raw,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "roles": set(),
            }
            source_cache[key] = cached
        roles = cached["roles"]
        if isinstance(roles, set):
            roles.add(role)

    for index, raw_package in enumerate(raw_packages):
        if not isinstance(raw_package, dict):
            raise TypeError(f"packages[{index}] must be an object")
        package_id = _logical_path(raw_package.get("package_id"), f"packages[{index}].package_id")
        for field in ("prompt_path", "context_manifest_path", "rules_path"):
            preload(
                raw_package.get(field),
                f"packages[{index}].{field}",
                field,
                package_id,
            )
        for item_index, value in enumerate(_provider_visible_input_logicals(raw_package, index)):
            preload(
                value,
                f"packages[{index}].provider_inputs[{item_index}]",
                "input_path",
                package_id,
            )
        acceptance = raw_package.get("acceptance")
        if isinstance(acceptance, dict) and str(acceptance.get("json_schema_path") or "").strip():
            preload(
                acceptance["json_schema_path"],
                f"packages[{index}].acceptance.json_schema_path",
                "output_schema",
                package_id,
            )

    generation_sources = [
        {
            "package_id": package_id,
            "source_path": source_logical,
            "source_sha256": str(cached["source_sha256"]),
            "roles": sorted(str(role) for role in cached["roles"]),
        }
        for (package_id, source_logical), cached in sorted(source_cache.items())
    ]
    snapshot_generation_sha256 = _canonical_sha(
        {
            "schema_version": "xinao.worker_package_input_generation.v1",
            "external_input_admission": external_input_admission,
            "sources": generation_sources,
        }
    )
    physical_root = _snapshot_physical_root(
        physical_base / "generations" / snapshot_generation_sha256
    )
    logical_root = logical_base + "/generations/" + snapshot_generation_sha256
    exact_bindings: dict[str, Path] = {}
    sources: dict[tuple[str, str], dict[str, object]] = {}
    package_catalogs: list[dict[str, object]] = []

    def snapshot(value: object, label: str, role: str, package_id: str) -> str:
        source_logical = _logical_path(value, label)
        cached = source_cache[(package_id, source_logical)]
        source_physical = Path(str(cached["source_physical"]))
        raw = bytes(cached["raw"])
        source_sha256 = str(cached["source_sha256"])
        safe_name = "".join(
            char if char.isalnum() or char in {".", "-", "_"} else "_"
            for char in source_physical.name
        )[:96]
        if not safe_name:
            safe_name = "input.bin"
        package_component = _safe_snapshot_component(package_id, f"{label}.package_id")
        # Only explicit package input_paths enter the worker-visible mount.
        # Prompt/context/rules/schema copies remain in the same immutable
        # generation but outside that mount.  If one source has both roles,
        # its explicit input_path role makes it a catalogued worker input.
        visibility_root = Path("packages") if "input_path" in cached["roles"] else Path("control")
        relative = (
            visibility_root / package_component / source_sha256[:2] / f"{source_sha256}-{safe_name}"
        )
        target = physical_root / relative
        _snapshot_bytes(raw, target, expected_sha256=source_sha256, root=physical_root)
        target_logical = logical_root + "/" + relative.as_posix()
        exact_bindings[target_logical] = target
        row = sources.setdefault(
            (package_id, source_logical),
            {
                "package_id": package_id,
                "source_path": source_logical,
                "source_physical_path": str(source_physical),
                "source_sha256": source_sha256,
                "snapshot_ref": {
                    "path": target_logical,
                    "sha256": source_sha256,
                },
                "roles": [],
            },
        )
        roles = row["roles"]
        if isinstance(roles, list) and role not in roles:
            roles.append(role)
        return target_logical

    for index, raw_package in enumerate(raw_packages):
        if not isinstance(raw_package, dict):
            raise TypeError(f"packages[{index}] must be an object")
        package_id = _logical_path(raw_package.get("package_id"), f"packages[{index}].package_id")
        for field in ("prompt_path", "context_manifest_path", "rules_path"):
            raw_package[field] = snapshot(
                raw_package.get(field),
                f"packages[{index}].{field}",
                field,
                package_id,
            )
        provider_inputs = _provider_visible_input_logicals(raw_package, index)
        rewritten_inputs = [
            snapshot(
                value,
                f"packages[{index}].provider_inputs[{item_index}]",
                "input_path",
                package_id,
            )
            for item_index, value in enumerate(provider_inputs)
        ]
        if len(set(rewritten_inputs)) != len(rewritten_inputs):
            raise ValueError(f"packages[{index}].input_paths collapse to duplicate sealed inputs")
        raw_package["input_paths"] = rewritten_inputs
        provider_input_map = dict(zip(provider_inputs, rewritten_inputs, strict=True))
        if str(raw_package.get("work_class") or "").strip() == "audit_repair":
            assessment_logical = _logical_path(
                raw_package.get("audit_assessment_path"),
                f"packages[{index}].audit_assessment_path",
            )
            adjudication_logical = _logical_path(
                raw_package.get("audit_adjudication_path"),
                f"packages[{index}].audit_adjudication_path",
            )
            raw_package["audit_assessment_path"] = provider_input_map[assessment_logical]
            raw_package["audit_adjudication_path"] = provider_input_map[adjudication_logical]
            prior_values = raw_package.get("prior_audit_adjudication_paths", [])
            if not isinstance(prior_values, list):
                raise TypeError(
                    f"packages[{index}].prior_audit_adjudication_paths must be an array"
                )
            raw_package["prior_audit_adjudication_paths"] = [
                provider_input_map[
                    _logical_path(
                        value,
                        f"packages[{index}].prior_audit_adjudication_paths[]",
                    )
                ]
                for value in prior_values
            ]
        package_component = _safe_snapshot_component(package_id, f"packages[{index}].package_id")
        package_root = physical_root / "packages" / package_component
        catalog_entries: list[dict[str, object]] = []
        for item_index, logical in enumerate(rewritten_inputs):
            physical = exact_bindings[logical]
            catalog_entries.append(
                {
                    "slot": item_index,
                    "path": "/sealed-inputs/" + physical.relative_to(package_root).as_posix(),
                    "sha256": _sha(physical),
                    "bytes": physical.stat().st_size,
                    "required": True,
                    "read_strategy": "read_file_required_selected_content",
                }
            )
        catalog = {
            "schema_version": "xinao.worker_sealed_input_catalog.v2",
            "package_id": package_id,
            "container_root": "/sealed-inputs",
            "mount_scope": "catalog_and_required_entries_only",
            "external_input_admission": external_input_admission,
            "entries": catalog_entries,
            "authority": False,
            "completion_claim_allowed": False,
        }
        catalog_raw = (
            json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        catalog_sha256 = hashlib.sha256(catalog_raw).hexdigest()
        catalog_target = package_root / "catalog.json"
        _snapshot_bytes(
            catalog_raw,
            catalog_target,
            expected_sha256=catalog_sha256,
            root=physical_root,
        )
        catalog_logical = logical_root + "/packages/" + package_component + "/catalog.json"
        exact_bindings[catalog_logical] = catalog_target
        package_catalogs.append(
            {
                "package_id": package_id,
                "catalog_ref": {
                    "path": catalog_logical,
                    "sha256": catalog_sha256,
                },
                "required_entry_count": len(catalog_entries),
            }
        )
        acceptance = raw_package.get("acceptance")
        if isinstance(acceptance, dict) and str(acceptance.get("json_schema_path") or "").strip():
            acceptance["json_schema_path"] = snapshot(
                acceptance["json_schema_path"],
                f"packages[{index}].acceptance.json_schema_path",
                "output_schema",
                package_id,
            )

    snapshot_manifest: dict[str, object] = {
        "schema_version": "xinao.worker_package_input_snapshot.v1",
        "snapshot_root": str(physical_root),
        "snapshot_ref_root": logical_root,
        "snapshot_generation_sha256": snapshot_generation_sha256,
        "external_input_admission": {
            **external_input_admission,
            "snapshot_generation_sha256": snapshot_generation_sha256,
        },
        "sources": sorted(
            sources.values(), key=lambda row: (str(row["package_id"]), str(row["source_path"]))
        ),
        "package_catalogs": package_catalogs,
        "authority": False,
        "completion_claim_allowed": False,
    }
    snapshot_manifest["snapshot_identity_sha256"] = _canonical_sha(snapshot_manifest)
    return rewritten, snapshot_manifest, exact_bindings


def build_path_resolver(
    bindings: Sequence[str] = (),
    *,
    exact_bindings: Mapping[str, str | Path] | None = None,
) -> PathResolver:
    """Build a read-only logical-to-physical resolver without changing manifest bytes."""

    prefix_bindings: list[tuple[str, Path]] = []
    for index, raw in enumerate(bindings):
        if "=" not in raw:
            raise ValueError(f"path-map[{index}] must be LOGICAL=PHYSICAL")
        logical, physical = raw.split("=", 1)
        logical = logical.strip().replace("\\", "/").rstrip("/")
        physical_path = Path(physical.strip()).resolve(strict=True)
        if not logical:
            raise ValueError(f"path-map[{index}] logical prefix is empty")
        prefix_bindings.append((logical, physical_path))
    prefix_bindings.sort(key=lambda item: len(item[0]), reverse=True)
    exact = {
        str(logical): Path(physical).resolve(strict=False)
        for logical, physical in (exact_bindings or {}).items()
    }

    def resolve(logical: str) -> Path:
        if logical in exact:
            return exact[logical]
        normalized = logical.replace("\\", "/")
        for prefix, physical_root in prefix_bindings:
            if normalized == prefix:
                return physical_root
            if normalized.startswith(prefix + "/"):
                relative = normalized[len(prefix) + 1 :]
                return physical_root / Path(relative)
        return Path(logical)

    return resolve


def build_neutral_manifest(
    spec: Mapping[str, object],
    *,
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Build one logical v3 manifest; physical resolver output never enters identity."""

    if spec.get("schema_version") != "xinao.worker_package_batch_spec.v1":
        raise ValueError("package spec schema mismatch")
    _require_external_input_admission(spec)
    parent_work_key = str(spec.get("parent_work_key") or "").strip()
    if not parent_work_key:
        raise ValueError("package spec requires parent_work_key")
    graph_revision = spec.get("graph_revision", 1)
    if isinstance(graph_revision, bool) or not isinstance(graph_revision, int):
        raise ValueError("graph_revision must be an integer")

    packages: list[dict[str, Any]] = []
    raw_packages = spec.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ValueError("package spec requires packages")
    for index, raw_value in enumerate(raw_packages):
        if not isinstance(raw_value, Mapping):
            raise TypeError(f"packages[{index}] must be an object")
        raw = dict(raw_value)
        work_class = str(raw.get("work_class") or "").strip()
        if "consumer_id" in raw:
            raise ValueError(
                f"packages[{index}] cannot bind a physical consumer_id in the neutral manifest"
            )
        prompt_logical = _logical_path(raw.get("prompt_path"), f"packages[{index}].prompt_path")
        context_logical = _logical_path(
            raw.get("context_manifest_path"),
            f"packages[{index}].context_manifest_path",
        )
        input_values = _provider_visible_input_logicals(raw, index)
        audit_assessment_logical = ""
        audit_adjudication_logical = ""
        prior_audit_adjudication_logicals: list[str] = []
        if work_class == "audit_repair":
            audit_assessment_logical = _logical_path(
                raw.get("audit_assessment_path"),
                f"packages[{index}].audit_assessment_path",
            )
            audit_adjudication_logical = _logical_path(
                raw.get("audit_adjudication_path"),
                f"packages[{index}].audit_adjudication_path",
            )
            prior_values = raw.get("prior_audit_adjudication_paths", [])
            if not isinstance(prior_values, list):
                raise TypeError(
                    f"packages[{index}].prior_audit_adjudication_paths must be an array"
                )
            prior_audit_adjudication_logicals = [
                _logical_path(
                    value,
                    f"packages[{index}].prior_audit_adjudication_paths[]",
                )
                for value in prior_values
            ]
        input_refs = [
            _path_ref(
                _logical_path(value, f"packages[{index}].input_paths[]"),
                path_resolver=path_resolver,
            )
            for value in input_values
        ]
        input_sha = input_refs[0]["sha256"] if len(input_refs) == 1 else _canonical_sha(input_refs)
        context_ref = _path_ref(context_logical, path_resolver=path_resolver)
        prompt_ref = _path_ref(prompt_logical, path_resolver=path_resolver)

        acceptance = copy.deepcopy(dict(raw.get("acceptance") or {}))
        acceptance.setdefault("min_result_chars", 1)
        acceptance.setdefault("required_result_markers", [])
        acceptance.setdefault("require_json_object", False)
        if work_class == "high_value_audit":
            acceptance["require_json_object"] = True
            acceptance.setdefault(
                "json_schema_path",
                str(
                    REPO_ROOT
                    / "services"
                    / "agent_runtime"
                    / "schemas"
                    / "audit_candidate_findings.v1.schema.json"
                ),
            )
        schema_path_value = str(acceptance.pop("json_schema_path", "") or "").strip()
        if schema_path_value:
            acceptance["json_schema_ref"] = _path_ref(
                schema_path_value,
                path_resolver=path_resolver,
            )
        rules_path_value = _logical_path(
            raw.get("rules_path"),
            f"packages[{index}].rules_path",
        )
        rules_ref = _path_ref(rules_path_value, path_resolver=path_resolver)
        declared_rules_sha = str(raw.get("rules_sha256") or "").strip()
        if declared_rules_sha and declared_rules_sha != rules_ref["sha256"]:
            raise ValueError(f"packages[{index}].rules_sha256 does not bind rules_path")
        rules_sha = rules_ref["sha256"]
        output_contract_sha = neutral_output_contract_sha256(acceptance)
        declared_output_contract_sha = str(raw.get("output_contract_sha256") or "").strip()
        if declared_output_contract_sha and declared_output_contract_sha != output_contract_sha:
            raise ValueError(f"packages[{index}].output_contract_sha256 does not bind acceptance")
        candidate_only = raw.get("candidate_only", True)
        if not isinstance(candidate_only, bool):
            raise TypeError(f"packages[{index}].candidate_only must be boolean")
        identity = build_worker_package_identity(
            package_id=str(raw.get("package_id") or ""),
            work_key=str(raw.get("work_key") or ""),
            parent_work_key=parent_work_key,
            work_class=work_class,
            role=str(raw.get("role") or ""),
            phase=str(raw.get("phase") or ""),
            input_sha256=input_sha,
            context_sha256=context_ref["sha256"],
            rules_sha256=rules_sha,
            output_contract_sha256=output_contract_sha,
            write_domains=list(raw.get("write_domains") or []),
            candidate_only=candidate_only,
        )
        package: dict[str, Any] = {
            **identity,
            "prompt_ref": prompt_ref,
            "context_manifest_ref": context_ref,
            "rules_ref": rules_ref,
            "input_refs": input_refs,
            "allowed_output_root": _logical_path(
                raw.get("allowed_output_root"),
                f"packages[{index}].allowed_output_root",
            ),
            "cwd": _logical_path(raw.get("cwd"), f"packages[{index}].cwd"),
            "depends_on": copy.deepcopy(list(raw.get("depends_on") or [])),
            "acceptance": acceptance,
            "timeout_sec": int(raw.get("timeout_sec") or 600),
        }
        if work_class == "high_value_audit":
            audit_role = str(raw.get("audit_role") or "").strip().lower()
            if audit_role not in {"cognitive_review", "independent_validation"}:
                raise ValueError(
                    f"packages[{index}].audit_role must be cognitive_review or independent_validation"
                )
            package["audit_role"] = audit_role
            package["cannot_access_filesystem"] = audit_role == "cognitive_review"
            package["tool_execution_allowed"] = audit_role == "independent_validation"
            package["evaluator_output_authority"] = "candidate_only"
        ref_by_path = {str(item["path"]): item for item in input_refs}
        if work_class == "audit_repair":
            package["audit_assessment_ref"] = ref_by_path[audit_assessment_logical]
            package["audit_adjudication_ref"] = ref_by_path[audit_adjudication_logical]
            package["prior_audit_adjudication_refs"] = [
                ref_by_path[logical] for logical in prior_audit_adjudication_logicals
            ]
        prior = raw.get("prior_attempt_receipt_ref")
        if isinstance(prior, Mapping):
            prior_logical = _logical_path(
                prior.get("path"), f"packages[{index}].prior_attempt_receipt_ref.path"
            )
            package["prior_attempt_receipt_ref"] = _path_ref(
                prior_logical,
                path_resolver=path_resolver,
            )
        prior_contract = raw.get("prior_logical_contract_ref")
        if isinstance(prior_contract, Mapping):
            prior_contract_logical = _logical_path(
                prior_contract.get("path"),
                f"packages[{index}].prior_logical_contract_ref.path",
            )
            package["prior_logical_contract_ref"] = _path_ref(
                prior_contract_logical,
                path_resolver=path_resolver,
            )
        packages.append(package)

    limits = copy.deepcopy(dict(spec.get("limits") or {}))
    limits.setdefault("max_parallel", 1)
    limits.setdefault("fan_in_capacity", 1)
    limits.setdefault("candidate_ingestion_capacity", limits["max_parallel"])
    manifest: dict[str, object] = {
        "schema_version": "xinao.worker_package_batch.v3",
        "authority": False,
        "completion_claim_allowed": False,
        "parent_work_key": parent_work_key,
        "candidate_output_base": _logical_path(
            spec.get("candidate_output_base"),
            "candidate_output_base",
        ),
        "graph_revision": graph_revision,
        "predecessor_manifest_ref": copy.deepcopy(spec.get("predecessor_manifest_ref")),
        "reseal_of": copy.deepcopy(spec.get("reseal_of")),
        "affected_cone": copy.deepcopy(list(spec.get("affected_cone") or [])),
        "limits": limits,
        "packages": packages,
    }
    validate_package_batch_manifest(manifest, path_resolver=path_resolver)
    return manifest


def plan_worker_dispatch(
    manifest: Mapping[str, object],
    *,
    path_resolver: PathResolver | None = None,
    pending_candidate_ingestion_count: int = 0,
    pending_owner_authority_count: int = 0,
) -> dict[str, object]:
    """Canonicalize once, plan once, and separate worker from owner admissions."""

    validated = validate_package_batch_manifest(manifest, path_resolver=path_resolver)
    frontier = plan_package_frontier(
        validated,
        pending_candidate_ingestion_count=pending_candidate_ingestion_count,
        pending_owner_authority_count=pending_owner_authority_count,
        path_resolver=path_resolver,
    )
    admitted = list(frontier["admitted"])
    worker_rows = [
        row
        for row in admitted
        if row["candidate_only"] is True and row["execution_seal_ready"] is True
    ]
    owner_rows = [row for row in admitted if row["candidate_only"] is False]
    unresolved_pin_package_ids = [
        str(row["package_id"])
        for row in validated["packages"]
        if any(dependency.get("pin") is None for dependency in row["depends_on"])
    ]
    return {
        "validated_manifest": validated,
        "frontier": frontier,
        "worker_package_ids": [str(row["package_id"]) for row in worker_rows],
        "owner_package_ids": [str(row["package_id"]) for row in owner_rows],
        "unresolved_pin_package_ids": unresolved_pin_package_ids,
        "conditionally_ready_package_ids": list(frontier["conditionally_ready_package_ids"]),
    }


def build_dispatch_envelope(
    *,
    leg: str,
    manifest_ref: Mapping[str, object],
    package_ids: Sequence[str],
    epoch_id: str,
    snapshot: Mapping[str, object],
    snapshot_ref: Mapping[str, object],
    selection: Mapping[str, object],
    selection_ref: Mapping[str, object],
) -> dict[str, object]:
    """Compatibility name for the route-bound envelope constructor."""

    return build_route_bound_dispatch_envelope(
        leg=leg,
        manifest_ref=manifest_ref,
        package_ids=package_ids,
        epoch_id=epoch_id,
        snapshot=snapshot,
        snapshot_ref=snapshot_ref,
        selection=selection,
        selection_ref=selection_ref,
    )


def build_route_bound_dispatch_envelope(
    *,
    leg: str,
    manifest_ref: Mapping[str, object],
    package_ids: Sequence[str],
    epoch_id: str,
    snapshot: Mapping[str, object],
    snapshot_ref: Mapping[str, object],
    selection: Mapping[str, object],
    selection_ref: Mapping[str, object],
) -> dict[str, object]:
    """Bind one package batch to exactly one selector route and consumer leg."""

    normalized_leg = str(leg or "").strip().upper()
    route_transport_by_leg = {
        "A": GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
        "B": GROK_DOCKER_ROUTE_TRANSPORT_ID,
    }
    expected_route_transport = route_transport_by_leg.get(normalized_leg)
    if expected_route_transport is None:
        raise ValueError("dispatch envelope leg must be A or B")
    route = validate_grok_route_selection_receipt(
        selection,
        expected_route_transport_id=expected_route_transport,
    )
    if not package_ids:
        raise ValueError("worker dispatch envelope requires an admitted candidate package")
    route_identity = dict(route["route_identity"])
    envelope: dict[str, object] = {
        "schema_version": "xinao.worker_dispatch_envelope.v2",
        "authority": False,
        "completion_claim_allowed": False,
        "leg": normalized_leg,
        "package_manifest_ref": copy.deepcopy(dict(manifest_ref)),
        "package_ids": [str(value) for value in package_ids],
        "dispatch_epoch": {
            "epoch_id": str(epoch_id),
            "quota_snapshot_id": snapshot["snapshot_id"],
            "quota_snapshot_ref": snapshot_ref["path"],
            "quota_snapshot_sha256": snapshot_ref["sha256"],
        },
        "selection": {
            **route_identity,
            "receipt_ref": selection_ref["path"],
            "receipt_sha256": selection_ref["sha256"],
            "decision_sha256": route["decision_sha256"],
            "route_identity_sha256": route["route_identity_sha256"],
            "route_decision_binding_sha256": route["route_decision_binding_sha256"],
        },
    }
    if normalized_leg == "B":
        envelope["execution_adapter"] = build_grok_docker_route_adapter_binding(selection)
    envelope["route_choice"] = build_route_choice_identity(
        package_manifest_sha256=str(manifest_ref["sha256"]),
        package_ids=[str(value) for value in package_ids],
        epoch_id=str(epoch_id),
        leg=normalized_leg,
        selection_decision_sha256=str(route["decision_sha256"]),
        route_decision_binding_sha256=str(route["route_decision_binding_sha256"]),
    )
    return envelope


def _dispatch_targets(
    args: argparse.Namespace, spec: Mapping[str, object]
) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    if args.dispatch_output is not None:
        targets.append((str(spec.get("leg") or "A").upper(), args.dispatch_output))
    if args.dispatch_output_a is not None:
        targets.append(("A", args.dispatch_output_a))
    if args.dispatch_output_b is not None:
        targets.append(("B", args.dispatch_output_b))
    if not targets:
        raise ValueError(
            "one of --dispatch-output/--dispatch-output-a/--dispatch-output-b is required"
        )
    legs = [leg for leg, _ in targets]
    paths = [path.resolve(strict=False) for _, path in targets]
    if len(legs) != len(set(legs)):
        raise ValueError("dispatch envelope legs must be unique")
    if len(paths) != len(set(paths)):
        raise ValueError("dispatch envelope output paths must be unique")
    if any(leg not in {"A", "B"} for leg in legs):
        raise ValueError("dispatch envelope leg must be A or B")
    if len(targets) > 1:
        raise ValueError(
            "A/B are mutually exclusive route alternatives; "
            "one package batch cannot dispatch the same frontier to both legs"
        )
    return targets


def _selection_input_for_leg(
    args: argparse.Namespace,
    leg: str,
) -> tuple[Path, str]:
    specific_path = args.selection_receipt_a if leg == "A" else args.selection_receipt_b
    specific_ref = args.selection_receipt_ref_a if leg == "A" else args.selection_receipt_ref_b
    if specific_path is not None and args.selection_receipt is not None:
        raise ValueError(f"leg-{leg} selection receipt is ambiguous")
    selected_path = specific_path or args.selection_receipt
    if selected_path is None:
        raise ValueError(f"leg-{leg} requires its own stable-selector route receipt")
    selected_ref = str(specific_ref or args.selection_receipt_ref or selected_path)
    return selected_path.resolve(strict=True), selected_ref


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--quota-resolution", type=Path, required=True)
    parser.add_argument("--selection-receipt", type=Path)
    parser.add_argument("--selection-receipt-ref")
    parser.add_argument("--selection-receipt-a", type=Path)
    parser.add_argument("--selection-receipt-ref-a")
    parser.add_argument("--selection-receipt-b", type=Path)
    parser.add_argument("--selection-receipt-ref-b")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-ref")
    parser.add_argument("--dispatch-output", type=Path)
    parser.add_argument("--dispatch-output-a", type=Path)
    parser.add_argument("--dispatch-output-b", type=Path)
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--input-snapshot-root", type=Path)
    parser.add_argument("--input-snapshot-ref-root")
    parser.add_argument(
        "--no-input-snapshot",
        action="store_true",
        help="disabled fail-closed compatibility flag; provider dispatch always requires the sealed copy",
    )
    args = parser.parse_args()
    try:
        if args.no_input_snapshot:
            raise ValueError(
                "--no-input-snapshot is disabled for provider dispatch; use the canonical "
                "owner-reviewed sealed-copy path"
            )
        spec = _object(args.spec.resolve(strict=True), "package spec")
        parent_work_key = str(spec.get("parent_work_key") or "").strip()
        epoch_id = str(spec.get("epoch_id") or "").strip()
        if not parent_work_key or not epoch_id:
            raise ValueError("package spec requires parent_work_key and epoch_id")
        targets = _dispatch_targets(args, spec)
        target_leg = targets[0][0]
        selection_path, selection_logical = _selection_input_for_leg(args, target_leg)
        output_path = args.output.resolve(strict=False)
        snapshot_manifest_path = output_path.with_name(output_path.name + ".input-snapshot.v1.json")
        output_targets = [output_path, *(path.resolve(strict=False) for _, path in targets)]
        if not args.no_input_snapshot:
            output_targets.append(snapshot_manifest_path)
        for target in output_targets:
            if target.exists():
                raise FileExistsError(f"output already exists: {target}")

        resolution = _object(args.quota_resolution.resolve(strict=True), "quota resolution")
        snapshot = resolution.get("snapshot")
        if not isinstance(snapshot, Mapping) or snapshot.get("epoch_id") != epoch_id:
            raise ValueError("quota resolution epoch mismatch")
        selection = _object(selection_path, "selection receipt")
        snapshot_logical = _logical_path(snapshot.get("snapshot_ref"), "snapshot.snapshot_ref")
        manifest_logical = str(args.manifest_ref or args.output)
        source_resolver = build_path_resolver(
            args.path_map,
            exact_bindings={selection_logical: selection_path},
        )
        snapshot_manifest: dict[str, object] | None = None
        snapshot_exact_bindings: dict[str, Path] = {}
        if not args.no_input_snapshot:
            if args.input_snapshot_ref_root is not None:
                raise ValueError(
                    "--input-snapshot-ref-root is not supported by the current dispatch "
                    "consumers; sealed manifest refs must be physical paths"
                )
            snapshot_root = (
                args.input_snapshot_root.resolve(strict=False)
                if args.input_snapshot_root is not None
                else output_path.parent / "sealed-inputs"
            )
            spec, snapshot_manifest, snapshot_exact_bindings = snapshot_package_spec_inputs(
                spec,
                snapshot_root=snapshot_root,
                snapshot_ref_root=args.input_snapshot_ref_root,
                path_resolver=source_resolver,
            )
        base_resolver = build_path_resolver(
            args.path_map,
            exact_bindings={
                selection_logical: selection_path,
                **snapshot_exact_bindings,
            },
        )
        manifest = build_neutral_manifest(spec, path_resolver=base_resolver)
        plan = plan_worker_dispatch(manifest, path_resolver=base_resolver)
        manifest_sha = _atomic_json(output_path, manifest)
        manifest_ref = {"path": manifest_logical, "sha256": manifest_sha}
        snapshot_manifest_ref: dict[str, str] | None = None
        if snapshot_manifest is not None:
            snapshot_manifest_sha = _atomic_json(snapshot_manifest_path, snapshot_manifest)
            snapshot_manifest_ref = {
                "path": str(snapshot_manifest_path),
                "sha256": snapshot_manifest_sha,
            }
        runtime_resolver = build_path_resolver(
            args.path_map,
            exact_bindings={
                selection_logical: selection_path,
                manifest_logical: output_path,
            },
        )
        snapshot_path = _resolve_path(snapshot_logical, path_resolver=runtime_resolver)
        snapshot_ref = {"path": snapshot_logical, "sha256": _sha(snapshot_path)}
        selection_ref = {"path": selection_logical, "sha256": _sha(selection_path)}

        dispatch_results: dict[str, dict[str, str]] = {}
        package_ids = list(plan["worker_package_ids"])
        if package_ids:
            for leg, target in targets:
                envelope = build_dispatch_envelope(
                    leg=leg,
                    manifest_ref=manifest_ref,
                    package_ids=package_ids,
                    epoch_id=epoch_id,
                    snapshot=snapshot,
                    snapshot_ref=snapshot_ref,
                    selection=selection,
                    selection_ref=selection_ref,
                )
                validate_dispatch_envelope(envelope, path_resolver=runtime_resolver)
                envelope_path = target.resolve(strict=False)
                envelope_sha = _atomic_json(envelope_path, envelope)
                dispatch_results[leg] = {
                    "path": str(envelope_path),
                    "sha256": envelope_sha,
                }

        result: dict[str, object] = {
            "manifest_ref": manifest_logical,
            "manifest_sha256": manifest_sha,
            "package_count": len(manifest["packages"]),
            "worker_package_ids": package_ids,
            "owner_package_ids": list(plan["owner_package_ids"]),
            "conditionally_ready_package_ids": list(plan["conditionally_ready_package_ids"]),
            "unresolved_pin_package_ids": list(plan["unresolved_pin_package_ids"]),
            "dispatch_envelopes": dispatch_results,
            "dispatch_deferred": not bool(package_ids),
            "epoch_id": epoch_id,
            "selection_decision_sha256": selection["decision_sha256"],
            "selected_leg": target_leg,
            "input_snapshot_status": (
                "sealed_copy" if snapshot_manifest_ref is not None else "disabled"
            ),
            "input_snapshot_manifest_ref": snapshot_manifest_ref,
        }
        if len(dispatch_results) == 1:
            only = next(iter(dispatch_results.values()))
            result["dispatch_envelope_ref"] = only["path"]
            result["dispatch_envelope_sha256"] = only["sha256"]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        DispatchEconomicsError,
    ) as exc:
        print(f"WORKER_PACKAGE_BATCH_BUILD_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
