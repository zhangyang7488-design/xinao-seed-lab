"""Snapshot-only path resolution for isolated F4 verifier processes."""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from xinao.foundation.f4_evidence_snapshot import (
    SnapshotError,
    SnapshotResolver,
    _identity_key,
    _inside,
    _join_identity,
    _logical_identity,
    canonical_json_bytes,
)

SNAPSHOT_MANIFEST_ENV = "XINAO_F4_SNAPSHOT_MANIFEST"
SNAPSHOT_TRACE_DIR_ENV = "XINAO_F4_SNAPSHOT_TRACE_DIR"
SNAPSHOT_OUTPUT_ROOT_ENV = "XINAO_F4_SNAPSHOT_OUTPUT_ROOT"
SNAPSHOT_AUTHORITY_ROOT_ENV = "XINAO_F4_AUTHORITY_ROOT"
SNAPSHOT_AUTHORITY_IDENTITY_ENV = "XINAO_F4_AUTHORITY_IDENTITY"


class SnapshotRuntimeError(RuntimeError):
    """Raised when snapshot mode would otherwise fall back to a live path."""


class SnapshotInputRuntime:
    """Map retained logical identities to verified capsule views only."""

    def __init__(self, manifest_path: Path) -> None:
        self.resolver = SnapshotResolver(manifest_path)
        self.root_path = self.resolver.root_path
        self._files_by_identity = {
            _identity_key(item["source_identity"]): str(item["logical_ref"])
            for item in self.resolver.manifest["logical_refs"]
        }
        self._roots_by_identity = sorted(
            (
                (_identity_key(item["source_identity"]), str(item["root_id"]))
                for item in self.resolver.manifest["logical_roots"]
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        self._aliases = {
            str(item["logical_prefix"]): str(item["source_identity"])
            for item in self.resolver.manifest["logical_aliases"]
        }
        self._trace_path: Path | None = None
        trace_dir = os.environ.get(SNAPSHOT_TRACE_DIR_ENV, "").strip()
        if trace_dir:
            directory = Path(trace_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            self._trace_path = directory / f"snapshot-trace-{os.getpid()}.json"
            atexit.register(self.write_trace)

    def _canonical_identity(self, value: object) -> str:
        try:
            identity = _logical_identity(value)
        except SnapshotError as exc:
            raise SnapshotRuntimeError(
                f"input path has no absolute logical identity: {value}"
            ) from exc
        for prefix, target in self._aliases.items():
            if identity.casefold() == prefix.casefold():
                return _logical_identity(target)
            if identity.casefold().startswith(prefix.casefold() + "/"):
                return _join_identity(target, identity[len(prefix) + 1 :])
        return identity

    def _physical_root_match(self, path: Path) -> tuple[str, str] | None:
        for root_id in self.resolver.roots:
            physical = self.root_path / "roots" / root_id
            try:
                relative = path.resolve().relative_to(physical.resolve()).as_posix()
            except ValueError:
                continue
            return root_id, "" if relative == "." else relative
        return None

    def resolve(self, value: object, *, expect: str = "any") -> Path:
        raw_path = Path(str(value))
        if raw_path.is_absolute() and _inside(raw_path, self.root_path):
            physical_root = self._physical_root_match(raw_path)
            if physical_root is not None:
                root_id, relative = physical_root
                if raw_path.is_dir():
                    result = self.resolver.logical_root(root_id, relative)
                else:
                    result = self.resolver.logical_path(
                        self.resolver.logical_ref_for_path(raw_path)
                    )
            elif raw_path.is_file():
                result = self.resolver.logical_path(self.resolver.logical_ref_for_path(raw_path))
            else:
                raise SnapshotRuntimeError(f"capsule path is not declared: {value}")
        else:
            identity = self._canonical_identity(value)
            identity_key = _identity_key(identity)
            logical_ref = self._files_by_identity.get(identity_key)
            if logical_ref is not None:
                result = self.resolver.logical_path(logical_ref)
            else:
                result = self._resolve_root_identity(identity, identity_key)
        if expect == "file" and not result.is_file():
            raise SnapshotRuntimeError(f"snapshot input is not a file: {value}")
        if expect == "directory" and not result.is_dir():
            raise SnapshotRuntimeError(f"snapshot input is not a directory: {value}")
        return result

    def _resolve_root_identity(self, identity: str, identity_key: str) -> Path:
        for root_identity, root_id in self._roots_by_identity:
            if identity_key == root_identity:
                return self.resolver.logical_root(root_id)
            prefix = root_identity.rstrip("/") + "/"
            if identity_key.startswith(prefix):
                relative = identity[len(root_identity) :].lstrip("/")
                rooted_ref = f"root/{root_id}/{relative}"
                if rooted_ref in self.resolver.refs:
                    return self.resolver.logical_path(rooted_ref)
                return self.resolver.logical_root(root_id, relative)
        raise SnapshotRuntimeError(f"snapshot has no declared input identity: {identity}")

    def retained_identity(self, value: object) -> str:
        path = Path(str(value))
        if path.is_absolute() and _inside(path, self.root_path):
            physical_root = self._physical_root_match(path)
            if physical_root is not None:
                root_id, relative = physical_root
                root_identity = str(self.resolver.roots[root_id]["source_identity"])
                return root_identity if not relative else _join_identity(root_identity, relative)
            logical_ref = self.resolver.logical_ref_for_path(path)
            return str(self.resolver.refs[logical_ref]["source_identity"])
        return self._canonical_identity(value)

    def same_path(self, left: object, right: object) -> bool:
        try:
            return _identity_key(self.retained_identity(left)) == _identity_key(
                self.retained_identity(right)
            )
        except (SnapshotError, SnapshotRuntimeError, OSError):
            return False

    def inside(self, path: object, root: object) -> bool:
        try:
            child = _identity_key(self.retained_identity(path))
            parent = _identity_key(self.retained_identity(root)).rstrip("/")
        except (SnapshotError, SnapshotRuntimeError, OSError):
            return False
        return child == parent or child.startswith(parent + "/")

    def write_trace(self) -> None:
        if self._trace_path is None:
            return
        report = self.resolver.trace_report()
        payload = {
            **report,
            "process_id": os.getpid(),
            "manifest_content_sha256": self.resolver.manifest["content_sha256"],
        }
        self._trace_path.write_bytes(canonical_json_bytes(payload))


_RUNTIME: SnapshotInputRuntime | None | bool = False


def snapshot_runtime() -> SnapshotInputRuntime | None:
    global _RUNTIME
    if _RUNTIME is False:
        raw = os.environ.get(SNAPSHOT_MANIFEST_ENV, "").strip()
        _RUNTIME = SnapshotInputRuntime(Path(raw)) if raw else None
    return _RUNTIME if isinstance(_RUNTIME, SnapshotInputRuntime) else None


def input_path(value: object, *, expect: str = "any") -> Path:
    runtime = snapshot_runtime()
    path = (
        runtime.resolve(value, expect=expect) if runtime is not None else Path(str(value)).resolve()
    )
    if expect == "file" and not path.is_file():
        raise SnapshotRuntimeError(f"input file is missing: {value}")
    if expect == "directory" and not path.is_dir():
        raise SnapshotRuntimeError(f"input directory is missing: {value}")
    return path


def _authorized_output_path(value: object) -> Path | None:
    raw_roots = os.environ.get(SNAPSHOT_OUTPUT_ROOT_ENV, "").strip()
    if not raw_roots:
        return None
    candidate = Path(str(value)).resolve()
    for raw_root in raw_roots.split(os.pathsep):
        if raw_root and _inside(candidate, Path(raw_root).resolve()):
            return candidate
    return None


def _authorized_authority_path(value: object) -> Path | None:
    raw_root = os.environ.get(SNAPSHOT_AUTHORITY_ROOT_ENV, "").strip()
    if not raw_root:
        return None
    candidate = Path(str(value)).resolve()
    root = Path(raw_root).resolve()
    return candidate if _inside(candidate, root) else None


def readable_path(value: object, *, expect: str = "file") -> Path:
    runtime = snapshot_runtime()
    if runtime is None:
        return input_path(value, expect=expect)
    try:
        return runtime.resolve(value, expect=expect)
    except SnapshotRuntimeError as exc:
        allowed = _authorized_output_path(value) or _authorized_authority_path(value)
        if allowed is None:
            raise
        if expect == "file" and not allowed.is_file():
            raise SnapshotRuntimeError(f"authorized output file is missing: {value}") from exc
        if expect == "directory" and not allowed.is_dir():
            raise SnapshotRuntimeError(f"authorized output directory is missing: {value}") from exc
        return allowed


def retained_path(value: object) -> str:
    runtime = snapshot_runtime()
    if runtime is None:
        return str(Path(str(value)).resolve())
    authority = _authorized_authority_path(value)
    if authority is not None:
        root = Path(os.environ[SNAPSHOT_AUTHORITY_ROOT_ENV]).resolve()
        identity = os.environ.get(
            SNAPSHOT_AUTHORITY_IDENTITY_ENV,
            "/opt/xinao-authority",
        ).rstrip("/")
        relative = authority.relative_to(root).as_posix()
        return identity if relative == "." else f"{identity}/{relative}"
    output = _authorized_output_path(value)
    if output is not None:
        return str(output)
    identity = runtime.retained_identity(value)
    if re.match(r"^[A-Za-z]:/", identity):
        return identity.replace("/", "\\")
    return identity


def same_path(left: object, right: object) -> bool:
    runtime = snapshot_runtime()
    if runtime is not None:
        return runtime.same_path(left, right)
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def inside(path: object, root: object) -> bool:
    runtime = snapshot_runtime()
    if runtime is not None:
        if runtime.inside(path, root):
            return True
        try:
            Path(str(path)).resolve().relative_to(Path(str(root)).resolve())
        except ValueError:
            return False
        return _authorized_output_path(path) is not None
    try:
        Path(str(path)).resolve().relative_to(Path(str(root)).resolve())
    except ValueError:
        return False
    return True


def file_sha256(path: object) -> str:
    resolved = readable_path(path, expect="file")
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def load_object(path: object) -> dict[str, Any]:
    resolved = readable_path(path, expect="file")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotRuntimeError(f"snapshot JSON input is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise SnapshotRuntimeError(f"snapshot JSON input is not an object: {path}")
    return value


__all__ = [
    "SNAPSHOT_AUTHORITY_IDENTITY_ENV",
    "SNAPSHOT_AUTHORITY_ROOT_ENV",
    "SNAPSHOT_MANIFEST_ENV",
    "SNAPSHOT_OUTPUT_ROOT_ENV",
    "SNAPSHOT_TRACE_DIR_ENV",
    "SnapshotInputRuntime",
    "SnapshotRuntimeError",
    "file_sha256",
    "input_path",
    "inside",
    "load_object",
    "readable_path",
    "retained_path",
    "same_path",
    "snapshot_runtime",
]
