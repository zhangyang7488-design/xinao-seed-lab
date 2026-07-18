"""Build the minimal content-addressed Python authority tree for F4 replay."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import stat
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.f4_authority_source_pack.v2"
DEFAULT_ENTRY_PATHS = (
    "scripts/verify_f4_live_canary_pack.py",
    "scripts/verify_f4_negative_companion_pack.py",
    "scripts/verify_f4_portfolio_source_canary_pack.py",
    "services/agent_runtime/grok_build_docker_worker.py",
    "xinao_discovery/src/xinao/foundation/f4_current_evidence_builder.py",
    "xinao_discovery/src/xinao/foundation/f4_current_evidence_verifier.py",
    "xinao_discovery/src/xinao/foundation/f4_evidence_snapshot.py",
    "xinao_discovery/src/xinao/foundation/f4_production_checker.py",
    "xinao_discovery/src/xinao/foundation/f4_snapshot_runtime.py",
    "xinao_discovery/src/xinao/foundation/assertion_verifiers/f4_assertion_actuals.py",
)


class AuthorityPackError(ValueError):
    """Raised when local Python authority cannot be closed exactly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorityPackError(message)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _assert_plain_path(path: Path, *, label: str) -> Path:
    lexical = Path(os.path.abspath(str(path)))
    current = lexical
    while True:
        if current.exists() or current.is_symlink():
            _require(not _is_reparse(current), f"{label} contains a reparse point: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent
    return lexical


def _stable_copy(source: Path, destination: Path) -> dict[str, Any]:
    source = _assert_plain_path(source, label="authority source")
    _require(source.is_file(), f"authority source is missing: {source}")
    before = {"sha256": _file_sha256(source), "size_bytes": source.stat().st_size}
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    after = {"sha256": _file_sha256(source), "size_bytes": source.stat().st_size}
    copied = {"sha256": _file_sha256(destination), "size_bytes": destination.stat().st_size}
    _require(before == after == copied, f"authority source changed during copy: {source}")
    return before


def _module_name(path: Path, roots: tuple[Path, ...]) -> tuple[str, Path] | None:
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts), root
    return None


def _module_file(module: str, roots: tuple[Path, ...]) -> Path | None:
    if not module:
        return None
    relative = Path(*module.split("."))
    for root in roots:
        module_path = root / relative.with_suffix(".py")
        package_path = root / relative / "__init__.py"
        if module_path.is_file():
            return module_path.resolve()
        if package_path.is_file():
            return package_path.resolve()
    return None


def _parent_initializers(path: Path, roots: tuple[Path, ...]) -> Iterable[Path]:
    identified = _module_name(path, roots)
    if identified is None:
        return ()
    _, root = identified
    current = path.parent
    initializers: list[Path] = []
    while current != root:
        initializer = current / "__init__.py"
        if initializer.is_file():
            initializers.append(initializer.resolve())
        current = current.parent
    return initializers


def _import_candidates(path: Path, roots: tuple[Path, ...]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise AuthorityPackError(f"cannot parse authority source: {path}") from exc
    identified = _module_name(path, roots)
    current_module = identified[0] if identified is not None else ""
    current_package = (
        current_module if path.name == "__init__.py" else current_module.rpartition(".")[0]
    )
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package_parts = current_package.split(".") if current_package else []
                keep = len(package_parts) - node.level + 1
                _require(keep >= 0, f"relative import escapes package: {path}:{node.lineno}")
                prefix = ".".join(package_parts[:keep])
                base = ".".join(item for item in (prefix, base) if item)
            if base:
                imports.add(base)
            for alias in node.names:
                if alias.name != "*":
                    imports.add(".".join(item for item in (base, alias.name) if item))
    return imports


def discover_python_closure(
    repo_root: Path,
    *,
    entry_paths: Iterable[str] = DEFAULT_ENTRY_PATHS,
) -> tuple[list[Path], list[str]]:
    repo_root = repo_root.resolve()
    roots = (
        repo_root / "xinao_discovery" / "src",
        repo_root / "projects" / "dual-brain-coordination" / "src",
        repo_root,
    )
    queue: deque[Path] = deque()
    for relative in entry_paths:
        source = (repo_root / relative).resolve()
        _require(source.is_file(), f"authority entry source is missing: {relative}")
        _require(source.suffix == ".py", f"authority entry is not Python: {relative}")
        queue.append(source)
    discovered: set[Path] = set()
    external_modules: set[str] = set()
    while queue:
        source = queue.popleft()
        if source in discovered:
            continue
        discovered.add(source)
        queue.extend(_parent_initializers(source, roots))
        for module in sorted(_import_candidates(source, roots)):
            candidate = _module_file(module, roots)
            if candidate is None:
                parts = module.split(".")
                has_local_prefix = any(
                    _module_file(".".join(parts[:index]), roots) is not None
                    for index in range(len(parts) - 1, 0, -1)
                )
                if not has_local_prefix:
                    external_modules.add(parts[0])
                continue
            queue.append(candidate)
    return sorted(discovered), sorted(external_modules)


def _inventory(root: Path) -> list[dict[str, Any]]:
    root = _assert_plain_path(root, label="authority pack root")
    rows: list[dict[str, Any]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        _assert_plain_path(directory_path, label="authority pack directory")
        for name in names:
            candidate = directory_path / name
            _require(
                not _is_reparse(candidate),
                f"authority pack directory is a reparse point: {candidate}",
            )
        for name in files:
            path = directory_path / name
            _require(not _is_reparse(path), f"authority pack file is a reparse point: {path}")
            _require(path.is_file(), f"authority pack object is not a file: {path}")
            if path.name == "authority_source_manifest.json":
                continue
            rows.append(
                {
                    "relative_path": path.relative_to(root).as_posix(),
                    "sha256": _file_sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    rows.sort(key=lambda item: item["relative_path"])
    return rows


def verify_authority_source_pack(manifest_path: Path) -> dict[str, Any]:
    manifest_path = _assert_plain_path(manifest_path, label="authority manifest")
    _require(
        manifest_path.name == "authority_source_manifest.json" and manifest_path.is_file(),
        f"authority manifest is missing: {manifest_path}",
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityPackError("authority manifest is invalid") from exc
    _require(isinstance(manifest, dict), "authority manifest is not an object")
    expected_keys = {
        "schema_version",
        "entry_paths",
        "python_source_count",
        "python_sources",
        "source_set_sha256",
        "external_module_roots",
        "artifact_count",
        "artifacts",
        "artifact_set_sha256",
        "content_sha256",
    }
    _require(set(manifest) == expected_keys, "authority manifest key set drifted")
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "authority schema drifted")
    core = dict(manifest)
    content_hash = str(core.pop("content_sha256", ""))
    _require(content_hash == _canonical_sha256(core), "authority content identity drifted")
    artifacts = _inventory(manifest_path.parent)
    _require(manifest.get("artifacts") == artifacts, "authority artifact inventory drifted")
    _require(manifest.get("artifact_count") == len(artifacts), "authority artifact count drifted")
    _require(
        manifest.get("artifact_set_sha256") == _canonical_sha256(artifacts),
        "authority artifact set identity drifted",
    )
    python_sources = manifest.get("python_sources")
    _require(isinstance(python_sources, list), "authority Python sources are not a list")
    _require(
        manifest.get("python_source_count") == len(python_sources),
        "authority Python source count drifted",
    )
    artifact_by_path = {str(item["relative_path"]): item for item in artifacts}
    _require(
        all(
            artifact_by_path.get(str(item.get("relative_path"))) == item for item in python_sources
        ),
        "authority Python sources are not an exact artifact subset",
    )
    _require(
        manifest.get("source_set_sha256") == _canonical_sha256(python_sources),
        "authority Python source set identity drifted",
    )
    entry_paths = manifest.get("entry_paths")
    _require(
        isinstance(entry_paths, list)
        and entry_paths == sorted(entry_paths)
        and all(path in artifact_by_path for path in entry_paths),
        "authority entry path inventory drifted",
    )
    return manifest


def build_authority_source_pack(
    *,
    repo_root: Path,
    output_parent: Path,
    entry_paths: Iterable[str] = DEFAULT_ENTRY_PATHS,
) -> Path:
    repo_root = repo_root.resolve()
    output_parent = output_parent.resolve()
    sources, external_modules = discover_python_closure(
        repo_root,
        entry_paths=entry_paths,
    )
    source_bindings = {
        source.relative_to(repo_root).as_posix(): {
            "sha256": _file_sha256(source),
            "size_bytes": source.stat().st_size,
        }
        for source in sources
    }
    staging = output_parent / f".xinao-f4-authority-source.{os.getpid()}.tmp"
    _require(not staging.exists(), f"authority staging path exists: {staging}")
    staging.mkdir(parents=True)
    try:
        for source in sources:
            relative = source.relative_to(repo_root)
            destination = staging / relative
            copied = _stable_copy(source, destination)
            _require(
                copied == source_bindings[relative.as_posix()],
                f"authority discovery bytes changed before copy: {relative}",
            )
        after_sources, after_external_modules = discover_python_closure(
            repo_root,
            entry_paths=entry_paths,
        )
        _require(after_sources == sources, "authority source closure changed during build")
        _require(
            after_external_modules == external_modules,
            "authority external module closure changed during build",
        )
        for source in after_sources:
            relative = source.relative_to(repo_root).as_posix()
            _require(
                source_bindings[relative]
                == {"sha256": _file_sha256(source), "size_bytes": source.stat().st_size},
                f"authority source changed after closure discovery: {relative}",
            )
        artifacts = _inventory(staging)
        python_sources = [item for item in artifacts if item["relative_path"].endswith(".py")]
        core = {
            "schema_version": SCHEMA_VERSION,
            "entry_paths": sorted(entry_paths),
            "python_source_count": len(python_sources),
            "python_sources": python_sources,
            "source_set_sha256": _canonical_sha256(python_sources),
            "external_module_roots": external_modules,
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "artifact_set_sha256": _canonical_sha256(artifacts),
        }
        manifest = {**core, "content_sha256": _canonical_sha256(core)}
        staging_manifest = staging / "authority_source_manifest.json"
        staging_manifest.write_bytes(_canonical_bytes(manifest))
        verify_authority_source_pack(staging_manifest)
        final = output_parent / f"xinao-f4-authority-source-{manifest['content_sha256'][:16]}"
        if final.exists():
            existing = final / "authority_source_manifest.json"
            _require(
                existing.is_file()
                and verify_authority_source_pack(existing) == manifest
                and existing.read_bytes() == _canonical_bytes(manifest),
                f"authority pack identity conflict: {final}",
            )
            shutil.rmtree(staging)
            return existing
        staging.rename(final)
        final_manifest = final / "authority_source_manifest.json"
        verify_authority_source_pack(final_manifest)
        return final_manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


__all__ = [
    "DEFAULT_ENTRY_PATHS",
    "SCHEMA_VERSION",
    "AuthorityPackError",
    "build_authority_source_pack",
    "discover_python_closure",
    "verify_authority_source_pack",
]
