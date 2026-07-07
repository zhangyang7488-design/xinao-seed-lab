from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_TASK_PACKAGE_ROOT = Path(
    os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
)
DEFAULT_EXPLICIT_ENTRY_ENV = "XINAO_TASK_ENTRY_PATH"
DEFAULT_MANIFEST_ENV = "XINAO_TASK_PACKAGE_MANIFEST"

TASK_PACKAGE_MANIFEST_NAMES = (
    "TASK_PACKAGE.json",
    "task_package.json",
    "datapackage.json",
)

LEGACY_AUTHORITY_FILES = (
    "AUTHORITY_READ_ORDER.txt",
    "新系统独立并行_自由发散外部研究总稿_20260701.txt",
    "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
)

LEGACY_EXTENDED_AUTHORITY_FILES = (
    "AUTHORITY_READ_ORDER.txt",
    "当前源文本增量_20260704.txt",
    "根意图分工.txt",
    "XINAO_333_固定锚点.txt",
    "新系统独立并行_自由发散外部研究总稿_20260701.txt",
    "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
)

CURRENT_SYSTEM_P0_FILES = (
    "01_总说明_本项目是什么_20260707.txt",
    "02_P0_底座全自动任务落地_20260707.txt",
    "03_P1_任务落地_20260707.txt",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def text_source_ref(path: Path, *, role: str = "task_package_resource") -> dict[str, Any]:
    exists = path.is_file()
    raw = b""
    text = ""
    read_error = ""
    if exists:
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception as exc:
            read_error = f"{type(exc).__name__}:{exc}"
    return {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "role": role,
        "exists": exists,
        "read_full": exists and not read_error,
        "read_in_full": exists and not read_error,
        "size_bytes": len(raw),
        "length": len(raw),
        "line_count": len(text.splitlines()) if text else 0,
        "char_count": len(text) if text else 0,
        "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
        "read_error": read_error,
    }


def manifest_source_ref(path: Path) -> dict[str, Any]:
    ref = text_source_ref(path, role="task_package_manifest")
    payload = read_json(path)
    ref.update(
        {
            "json_valid": bool(payload),
            "payload": payload,
            "parse_error": "" if payload else "manifest_missing_or_invalid_json",
        }
    )
    return ref


def explicit_manifest_path(root: Path, manifest_path: str | Path | None = None) -> Path | None:
    requested = str(manifest_path or os.environ.get(DEFAULT_MANIFEST_ENV, "")).strip()
    if requested:
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate if candidate.is_file() else None
    for name in TASK_PACKAGE_MANIFEST_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def normalize_resource_path(root: Path, raw_path: Any) -> Path | None:
    text = str(raw_path or "").strip()
    if not text or "://" in text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate
    if candidate.drive or text.startswith("/") or text.startswith("../"):
        return None
    if any(part in {"..", ""} for part in candidate.parts):
        return None
    return root / candidate


def manifest_resource_paths(root: Path, manifest: dict[str, Any]) -> list[Path]:
    entries: list[Any] = []
    for key in ("resources", "hot_path_files", "files"):
        value = manifest.get(key)
        if isinstance(value, list):
            entries.extend(value)
    entrypoint = manifest.get("entrypoint")
    if entrypoint and not entries:
        entries.append({"path": entrypoint, "role": "entrypoint"})

    paths: list[Path] = []
    seen: set[str] = set()
    for entry in entries:
        role_read = ""
        if isinstance(entry, str):
            raw_path: Any = entry
        elif isinstance(entry, dict):
            if entry.get("exclude") is True or entry.get("reference_only") is True:
                continue
            role_read = str(entry.get("read") or "").strip().lower()
            if role_read in {"reference_only", "skip", "none"}:
                continue
            raw_path = entry.get("path") or entry.get("href")
        else:
            continue
        path = normalize_resource_path(root, raw_path)
        if path is None:
            continue
        key = str(path.resolve()) if path.exists() else str(path.absolute())
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def explicit_entry_path(root: Path, entry_path: str | Path | None = None) -> Path | None:
    requested = str(entry_path or os.environ.get(DEFAULT_EXPLICIT_ENTRY_ENV, "")).strip()
    if not requested:
        return None
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate


def _resource_role(root: Path, manifest: dict[str, Any], path: Path) -> str:
    for resource in manifest.get("resources", []) if isinstance(manifest.get("resources"), list) else []:
        if not isinstance(resource, dict):
            continue
        candidate = normalize_resource_path(root, resource.get("path") or resource.get("href"))
        if candidate and candidate == path:
            return str(resource.get("role") or "manifest_resource")
    return "manifest_resource"


def resolve_task_package(
    root: str | Path = DEFAULT_TASK_PACKAGE_ROOT,
    *,
    manifest_path: str | Path | None = None,
    entry_path: str | Path | None = None,
    legacy_files: tuple[str, ...] | list[str] = LEGACY_AUTHORITY_FILES,
    include_manifest_ref: bool = True,
    package_role: str = "current_task_package",
) -> dict[str, Any]:
    root_path = Path(root)
    generated_at = now_iso()
    manifest = explicit_manifest_path(root_path, manifest_path)
    explicit_entry = explicit_entry_path(root_path, entry_path)

    if manifest is not None:
        manifest_payload = read_json(manifest)
        resource_paths = manifest_resource_paths(root_path, manifest_payload)
        refs: list[dict[str, Any]] = []
        if include_manifest_ref:
            refs.append(manifest_source_ref(manifest))
        refs.extend(
            text_source_ref(path, role=_resource_role(root_path, manifest_payload, path))
            for path in resource_paths
        )
        mode = str(
            manifest_payload.get("package_mode")
            or manifest_payload.get("profile")
            or "manifest_task_package"
        )
        entrypoint_raw = manifest_payload.get("entrypoint")
        entrypoint = normalize_resource_path(root_path, entrypoint_raw) if entrypoint_raw else (
            resource_paths[0] if resource_paths else manifest
        )
        resolution = "task_package_manifest"
        legacy_fallback = False
        manifest_driven = True
        single_entry_driven = False
        task_package_manifest_ref = manifest_source_ref(manifest)
    elif explicit_entry is not None:
        refs = [text_source_ref(explicit_entry, role="explicit_task_entry")]
        mode = "explicit_single_entry_task_package"
        entrypoint = explicit_entry
        resolution = "explicit_task_entry_path"
        legacy_fallback = False
        manifest_driven = False
        single_entry_driven = True
        task_package_manifest_ref = {}
    elif all((root_path / name).is_file() for name in CURRENT_SYSTEM_P0_FILES):
        refs = [
            text_source_ref(root_path / name, role="implicit_current_p0_resource")
            for name in CURRENT_SYSTEM_P0_FILES
        ]
        mode = "current_system_p0"
        entrypoint = root_path / CURRENT_SYSTEM_P0_FILES[1]
        resolution = "implicit_current_system_p0_compat_fallback"
        legacy_fallback = False
        manifest_driven = False
        single_entry_driven = False
        task_package_manifest_ref = {}
    else:
        refs = [text_source_ref(root_path / name, role="legacy_authority_resource") for name in legacy_files]
        mode = "legacy_authority_package"
        entrypoint = root_path / str(legacy_files[0]) if legacy_files else root_path
        resolution = "legacy_authority_fallback"
        legacy_fallback = True
        manifest_driven = False
        single_entry_driven = False
        task_package_manifest_ref = {}

    digest_basis = [
        {
            "path": ref["path"],
            "exists": ref["exists"],
            "sha256": ref.get("sha256", ""),
            "line_count": ref.get("line_count", 0),
            "role": ref.get("role", ""),
        }
        for ref in refs
    ]
    read_order = [str(ref.get("path") or "") for ref in refs if ref.get("path")]
    all_required = bool(refs) and all(ref.get("read_full") is True for ref in refs)
    return {
        "schema_version": "xinao.codex_s.task_package_resolution.v1",
        "package_role": package_role,
        "root": str(root_path),
        "source_entry_root": str(root_path),
        "mode": mode,
        "package_mode": mode,
        "resolution": resolution,
        "manifest_driven": manifest_driven,
        "single_entry_driven": single_entry_driven,
        "legacy_fallback": legacy_fallback,
        "legacy_fallback_allowed": True,
        "task_package_manifest_ref": task_package_manifest_ref,
        "task_package_manifest": task_package_manifest_ref,
        "task_package_manifest_path": str(manifest or ""),
        "entrypoint_ref": str(entrypoint or ""),
        "read_at": generated_at,
        "generated_at": generated_at,
        "authority_read_order": read_order,
        "read_order": read_order,
        "required_files": [Path(path).name for path in read_order],
        "authority_files": [Path(path).name for path in read_order],
        "frontier_source_files": [Path(path).name for path in read_order],
        "refs": refs,
        "sampled_files": refs,
        "file_count": len(refs),
        "sampled_count": len(refs),
        "read_full_count": sum(1 for ref in refs if ref.get("read_full") is True),
        "all_required_sources_read_full": all_required,
        "source_package_digest_sha256": sha256_json(digest_basis),
        "source_entry_digest_sha256": sha256_json(digest_basis),
        "source_package_back_ref_required": True,
        "current_package_rank0_for_task": True,
        "not_fixed_text_filename_slicer": True,
        "not_old_source_anchor_taskcard_machine": True,
        "sample_policy": (
            "task package manifest resources or explicit task entry path first; "
            "legacy authority files only when no current package anchor exists"
        ),
        "external_mature_basis": [
            "Frictionless Data Package descriptor/resources pattern",
            "RO-Crate root dataset hasPart resource graph pattern",
            "BagIt manifest/integrity payload pattern",
            "OCI descriptor digest/read-order boundary pattern",
        ],
    }


def resolve_current_task_package(**kwargs: Any) -> dict[str, Any]:
    return resolve_task_package(DEFAULT_TASK_PACKAGE_ROOT, **kwargs)


def source_refs_from_package(package: dict[str, Any]) -> list[dict[str, Any]]:
    refs = package.get("refs")
    return refs if isinstance(refs, list) else []
