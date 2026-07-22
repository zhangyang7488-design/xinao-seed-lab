"""Portable, byte-preserving evidence snapshots with exact local resolution.

The primitives in this module are domain-neutral despite the historical F4
module name.  Source bytes are copied unchanged into logical views and a
content-addressed store.  JSON reference edges are recorded by logical
identity, so snapshot readers can resolve a retained absolute path without
falling back to that live path or hashing a physical output directory.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import ntpath
import os
import posixpath
import re
import shutil
import stat
import urllib.parse
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "xinao.evidence_snapshot.v1"
MANIFEST_NAME = "snapshot_manifest.json"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PATH_KEYS = frozenset({"manifest_path", "pack", "path", "ref", "source_pack", "uri"})
_REFERENCE_REGISTRY_SCHEMA = "xinao.evidence_snapshot.required_reference_registry.v1"
_SOFT_PATH_ALLOWLIST_SCHEMA = "xinao.evidence_snapshot.unresolved_path_allowlist.v1"
_SOFT_PATH_ALLOWLIST_ENV = "XINAO_F4_SNAPSHOT_SOFT_PATH_ALLOWLIST"
_SOFT_PATH_ALLOWLIST_SHA256_ENV = "XINAO_F4_SNAPSHOT_SOFT_PATH_ALLOWLIST_SHA256"
_UNRESOLVED_REASONS = frozenset({"invalid_local_identity", "missing_local_target"})
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class SnapshotError(ValueError):
    """Raised when a snapshot is incomplete, ambiguous, or not portable."""


@dataclass(frozen=True)
class _SoftPathAllowlist:
    entries: list[dict[str, str]]
    keys: set[tuple[str, str, str, str]]
    source_manifest_sha256: str | None
    source_content_sha256: str | None


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
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _soft_path_allowlist_from_environment() -> _SoftPathAllowlist:
    """Load one byte-pinned exact allowlist; broad soft-path switches are unsupported."""

    raw_path = os.environ.get(_SOFT_PATH_ALLOWLIST_ENV, "").strip()
    expected_sha256 = os.environ.get(_SOFT_PATH_ALLOWLIST_SHA256_ENV, "").strip()
    if not raw_path and not expected_sha256:
        return _SoftPathAllowlist([], set(), None, None)
    _require(
        bool(raw_path) and bool(expected_sha256), "soft path allowlist path/hash pair is incomplete"
    )
    _require(
        _SHA256_RE.fullmatch(expected_sha256) is not None,
        "soft path allowlist hash is invalid",
    )
    path = _assert_no_lexical_reparse(Path(raw_path), label="soft path allowlist").resolve()
    _require(path.is_file() and not _is_reparse(path), "soft path allowlist is missing or reparse")
    _require(file_sha256(path) == expected_sha256, "soft path allowlist file hash drifted")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("soft path allowlist is not valid JSON") from exc
    _require(isinstance(payload, dict), "soft path allowlist is not an object")
    _require(
        set(payload)
        == {
            "schema_version",
            "source_snapshot_manifest_sha256",
            "source_snapshot_content_sha256",
            "entries_count",
            "entries_sha256",
            "entries",
            "content_sha256",
        },
        "soft path allowlist key set drifted",
    )
    _require(
        payload.get("schema_version") == _SOFT_PATH_ALLOWLIST_SCHEMA,
        "soft path allowlist schema drifted",
    )
    for label in (
        "source_snapshot_manifest_sha256",
        "source_snapshot_content_sha256",
        "entries_sha256",
        "content_sha256",
    ):
        _require(
            _SHA256_RE.fullmatch(str(payload.get(label) or "")) is not None,
            f"soft path allowlist {label} is invalid",
        )
    core = dict(payload)
    content_sha256 = str(core.pop("content_sha256"))
    _require(
        content_sha256 == canonical_sha256(core), "soft path allowlist content identity drifted"
    )
    raw_entries = payload.get("entries")
    _require(isinstance(raw_entries, list), "soft path allowlist entries are not a list")
    entries: list[dict[str, str]] = []
    keys: set[tuple[str, str, str, str]] = set()
    for raw in raw_entries:
        _require(
            isinstance(raw, dict)
            and set(raw) == {"source_ref", "json_pointer", "recorded_value", "reason"},
            "soft path allowlist entry shape drifted",
        )
        source_ref = _validate_relative(raw.get("source_ref"), label="soft path source_ref")
        pointer = str(raw.get("json_pointer") or "")
        parts = _pointer_parts(pointer)
        recorded_value = str(raw.get("recorded_value") or "")
        reason = str(raw.get("reason") or "")
        _require(parts and parts[-1] in _PATH_KEYS, "soft path allowlist entry is not a PATH_KEY")
        _require(
            reason == "missing_local_target",
            "soft path allowlist reason is not missing_local_target",
        )
        entry = {
            "json_pointer": pointer,
            "reason": reason,
            "recorded_value": recorded_value,
            "source_ref": source_ref,
        }
        key = (source_ref, pointer, recorded_value, reason)
        _require(key not in keys, "soft path allowlist contains a duplicate entry")
        entries.append(entry)
        keys.add(key)
    expected_entries = sorted(
        entries,
        key=lambda item: (
            item["source_ref"],
            item["json_pointer"],
            item["recorded_value"],
            item["reason"],
        ),
    )
    _require(entries == expected_entries, "soft path allowlist entries are not canonically ordered")
    _require(
        _integer(payload.get("entries_count"), label="soft path allowlist entries_count")
        == len(entries),
        "soft path allowlist entry count drifted",
    )
    _require(
        payload.get("entries_sha256") == canonical_sha256(entries),
        "soft path allowlist entries identity drifted",
    )
    return _SoftPathAllowlist(
        entries=entries,
        keys=keys,
        source_manifest_sha256=str(payload["source_snapshot_manifest_sha256"]),
        source_content_sha256=str(payload["source_snapshot_content_sha256"]),
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def _integer(value: object, *, label: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{label} is not an integer")
    return int(value)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path.resolve())))


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SnapshotError(f"cannot inspect path: {path}") from exc
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _assert_no_lexical_reparse(path: Path, *, label: str) -> Path:
    """Reject an existing reparse component before any resolving can hide it."""

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


def _validate_relative(value: object, *, label: str) -> str:
    raw = str(value or "")
    _require(raw == raw.strip() and raw, f"{label} is empty or padded")
    _require("\\" not in raw, f"{label} uses a non-portable separator: {raw}")
    _require(":" not in raw, f"{label} is drive-relative or contains a colon: {raw}")
    path = PurePosixPath(raw)
    _require(not path.is_absolute(), f"{label} is absolute: {raw}")
    _require(
        all(part not in {"", ".", ".."} for part in path.parts),
        f"{label} is not canonical: {raw}",
    )
    _require(path.as_posix() == raw, f"{label} is not canonical: {raw}")
    for part in path.parts:
        _require(not part.endswith((".", " ")), f"{label} has an ambiguous suffix: {raw}")
        base = part.split(".", 1)[0].upper()
        _require(base not in _WINDOWS_RESERVED, f"{label} uses a reserved name: {raw}")
    return raw


def _validate_id(value: object, *, label: str) -> str:
    raw = str(value or "")
    _require(_ID_RE.fullmatch(raw) is not None, f"{label} is invalid: {raw!r}")
    return raw


def _normalize_alias_prefix(value: object) -> str:
    original = str(value or "")
    _require(original == original.strip() and original, f"source alias is empty or padded: {value}")
    raw = original.replace("\\", "/")
    _require(not raw.endswith("/"), f"source alias has an ambiguous suffix: {value}")
    _require(
        not raw.casefold().startswith(("//?/", "//./")),
        f"source alias uses a Windows device path: {value}",
    )
    if re.fullmatch(r"[A-Za-z]:/.*", raw):
        raw = raw[0].upper() + raw[1:]
        suffix = raw[3:]
    elif raw.startswith("/"):
        _require(not raw.startswith("//"), f"source alias uses an unsupported UNC path: {value}")
        suffix = raw[1:]
    else:
        raise SnapshotError(f"source alias is not logical-absolute: {value}")
    _validate_relative(suffix, label="source alias suffix")
    return raw


def _logical_identity(value: object) -> str:
    raw = str(value or "").replace("\\", "/")
    if re.fullmatch(r"[A-Za-z]:/.*", raw):
        normalized = ntpath.normpath(raw).replace("\\", "/")
        return normalized[0].upper() + normalized[1:]
    if raw.startswith("//"):
        return ntpath.normpath(raw).replace("\\", "/")
    if raw.startswith("/"):
        return posixpath.normpath(raw)
    raise SnapshotError(f"logical source identity is not absolute: {value}")


def _identity_key(value: object) -> str:
    normalized = _logical_identity(value)
    if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//"):
        return normalized.casefold()
    return normalized


def _join_identity(base: str, relative: str) -> str:
    normalized = _logical_identity(base)
    if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//"):
        return _logical_identity(ntpath.join(normalized, relative))
    return _logical_identity(posixpath.join(normalized, relative))


def _identity_parent(value: str) -> str:
    normalized = _logical_identity(value)
    if re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//"):
        return _logical_identity(ntpath.dirname(normalized))
    return _logical_identity(posixpath.dirname(normalized))


def _reference_identity_candidates(
    recorded: str,
    *,
    source: Mapping[str, Any],
    roots: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> set[str]:
    normalized = recorded.replace("\\", "/")
    candidates: set[str] = set()
    for prefix, target in aliases.items():
        if normalized.casefold() == prefix.casefold():
            candidates.add(_identity_key(target))
        elif normalized.casefold().startswith(prefix.casefold() + "/"):
            candidates.add(_identity_key(_join_identity(target, normalized[len(prefix) + 1 :])))
    try:
        candidates.add(_identity_key(normalized))
    except SnapshotError:
        root_id = source.get("root_id")
        if isinstance(root_id, str) and root_id in roots:
            candidates.add(
                _identity_key(_join_identity(str(roots[root_id]["source_identity"]), normalized))
            )
        candidates.add(
            _identity_key(
                _join_identity(_identity_parent(str(source["source_identity"])), normalized)
            )
        )
    return candidates


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _iter_regular_files(root: Path) -> Iterable[Path]:
    root = _assert_no_lexical_reparse(root, label="logical root").resolve()
    _require(root.is_dir(), f"logical root is missing: {root}")
    _require(not _is_reparse(root), f"logical root is a reparse point: {root}")
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(names):
            candidate = directory_path / name
            _require(
                not _is_reparse(candidate), f"source directory is a reparse point: {candidate}"
            )
        for name in sorted(files):
            candidate = directory_path / name
            _require(not _is_reparse(candidate), f"source file is a reparse point: {candidate}")
            _require(candidate.is_file(), f"source object is not a regular file: {candidate}")
            yield candidate.resolve()


def _pointer_part(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _pointer_parts(pointer: str) -> list[str]:
    _require(pointer == "" or pointer.startswith("/"), f"invalid JSON pointer: {pointer}")
    if not pointer:
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _value_at_pointer(value: object, pointer: str) -> object:
    current = value
    for part in _pointer_parts(pointer):
        if isinstance(current, dict):
            _require(part in current, f"JSON pointer is absent: {pointer}")
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise SnapshotError(f"JSON pointer is absent: {pointer}") from exc
        else:
            raise SnapshotError(f"JSON pointer crosses a scalar: {pointer}")
    return current


def _replace_at_pointer(value: object, pointer: str, replacement: object) -> object:
    parts = _pointer_parts(pointer)
    _require(parts, "root JSON replacement is not supported")
    current = value
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise SnapshotError(f"JSON pointer crosses a scalar: {pointer}")
    last = parts[-1]
    if isinstance(current, dict):
        current[last] = replacement
    elif isinstance(current, list):
        current[int(last)] = replacement
    else:
        raise SnapshotError(f"JSON pointer crosses a scalar: {pointer}")
    return value


def _reference_values(
    value: object,
    pointer: str = "",
) -> Iterable[tuple[str, str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{_pointer_part(key)}"
            if isinstance(child, str) and (key in _PATH_KEYS or key.endswith("_ref")):
                yield child_pointer, key, child
            yield from _reference_values(child, child_pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _reference_values(child, f"{pointer}/{index}")


def _local_reference_path(raw: str) -> str | None:
    """Return a local-path spelling or None for semantic/non-local references."""

    normalized = raw.replace("\\", "/")
    _require(
        not normalized.casefold().startswith(("//?/", "//./")),
        f"local reference uses a Windows device path: {raw}",
    )
    _require(
        not (
            normalized.startswith("/") and re.search(r"(?:^|/)[A-Za-z]:/", normalized) is not None
        ),
        f"local reference mixes POSIX and Windows roots: {raw}",
    )
    if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith(("\\\\", "//", "/")):
        return raw
    if raw.casefold().startswith("file:"):
        parsed = urllib.parse.urlsplit(raw)
        _require(
            parsed.scheme.casefold() == "file" and not parsed.query and not parsed.fragment,
            f"local file URI is invalid: {raw}",
        )
        decoded = urllib.parse.unquote(parsed.path)
        if parsed.netloc:
            return f"//{parsed.netloc}{decoded}"
        if re.match(r"^/[A-Za-z]:/", decoded):
            return decoded[1:]
        _require(decoded.startswith("/"), f"local file URI is not absolute: {raw}")
        return decoded
    return None


def _reference_registry(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        source = "xinao.foundation.f4_evidence_snapshot"
        version = SCHEMA_VERSION
        raw_rules: object = []
    else:
        _require(
            set(value) == {"source", "version", "rules"},
            "required reference registry key set drifted",
        )
        source = str(value.get("source") or "")
        version = str(value.get("version") or "")
        raw_rules = value.get("rules")
    _require(source == source.strip() and source, "required reference registry source is empty")
    _require(version == version.strip() and version, "required reference registry version is empty")
    _require(isinstance(raw_rules, list), "required reference registry rules are not a list")
    rules: list[dict[str, Any]] = []
    for raw in raw_rules:
        _require(isinstance(raw, dict), "required reference registry rule is not an object")
        _require(
            set(raw)
            == {
                "rule_id",
                "source_ref_glob",
                "json_pointer_glob",
                "expected_match_count",
            },
            "required reference registry rule key set drifted",
        )
        rule_id = _validate_id(raw.get("rule_id"), label="required reference rule_id")
        source_glob = str(raw.get("source_ref_glob") or "")
        pointer_glob = str(raw.get("json_pointer_glob") or "")
        expected_match_count = _integer(
            raw.get("expected_match_count"),
            label=f"required reference expected_match_count: {rule_id}",
        )
        _require(
            source_glob == source_glob.strip() and source_glob,
            "required reference source glob is empty",
        )
        _require(
            pointer_glob == pointer_glob.strip() and pointer_glob.startswith("/"),
            "required reference JSON pointer glob is invalid",
        )
        _require(
            expected_match_count > 0,
            f"required reference rule expects no matches: {rule_id}",
        )
        rules.append(
            {
                "rule_id": rule_id,
                "source_ref_glob": source_glob,
                "json_pointer_glob": pointer_glob,
                "expected_match_count": expected_match_count,
            }
        )
    rules.sort(key=lambda item: item["rule_id"])
    _require(
        len({item["rule_id"].casefold() for item in rules}) == len(rules),
        "required reference registry has duplicate rule ids",
    )
    core = {
        "schema_version": _REFERENCE_REGISTRY_SCHEMA,
        "source": source,
        "version": version,
        "builtin_local_path_keys": sorted(_PATH_KEYS),
        "rules": rules,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def _matching_registry_rule_ids(
    registry: Mapping[str, Any],
    *,
    source_ref: str,
    pointer: str,
) -> tuple[str, ...]:
    return tuple(
        str(rule["rule_id"])
        for rule in registry["rules"]
        if fnmatch.fnmatchcase(source_ref, str(rule["source_ref_glob"]))
        and fnmatch.fnmatchcase(pointer, str(rule["json_pointer_glob"]))
    )


def _registry_rule_requires(
    registry: Mapping[str, Any],
    *,
    source_ref: str,
    pointer: str,
) -> bool:
    return bool(
        _matching_registry_rule_ids(
            registry,
            source_ref=source_ref,
            pointer=pointer,
        )
    )


def _reachable_logical_refs(
    *,
    entry_points: Iterable[str],
    refs: set[str],
    root_refs: Mapping[str, set[str]],
    edges: Iterable[Mapping[str, Any]],
) -> set[str]:
    by_source: dict[str, list[Mapping[str, Any]]] = {}
    for edge in edges:
        by_source.setdefault(str(edge["source_ref"]), []).append(edge)
    reachable: set[str] = set()
    expanded_roots: set[tuple[str, str]] = set()
    queue: deque[tuple[str, str, str]] = deque()
    for entry in sorted(entry_points):
        if entry.startswith("root:"):
            queue.append(("root", entry.split(":", 1)[1], ""))
        else:
            queue.append(("file", entry, ""))
    while queue:
        kind, current, relative_path = queue.popleft()
        if kind == "root":
            root_id = current
            _require(root_id in root_refs, f"unknown root entry point: {root_id}")
            expansion = (root_id, relative_path)
            if expansion not in expanded_roots:
                expanded_roots.add(expansion)
                prefix = f"root/{root_id}/"
                relative_prefix = f"{relative_path}/" if relative_path else ""
                queue.extend(
                    ("file", logical_ref, "")
                    for logical_ref in sorted(root_refs[root_id])
                    if not relative_prefix or logical_ref[len(prefix) :].startswith(relative_prefix)
                )
            continue
        _require(kind == "file", f"unknown reachability token kind: {kind}")
        _require(current in refs, f"unknown file entry point: {current}")
        if current in reachable:
            continue
        reachable.add(current)
        for edge in by_source.get(current, []):
            if edge["target_kind"] == "file":
                queue.append(("file", str(edge["target_ref"]), ""))
            else:
                queue.append(
                    (
                        "root",
                        str(edge["target_root_id"]),
                        str(edge.get("target_relative_path") or ""),
                    )
                )
    return reachable


@dataclass(frozen=True)
class _SourceRecord:
    logical_ref: str
    source: Path
    view_ref: str
    root_id: str | None
    relative_path: str | None
    sha256: str
    size_bytes: int

    def manifest_value(self) -> dict[str, Any]:
        return {
            "logical_ref": self.logical_ref,
            "source_identity": _logical_identity(self.source),
            "root_id": self.root_id,
            "relative_path": self.relative_path,
            "view_ref": self.view_ref,
            "cas_ref": f"cas/sha256/{self.sha256[:2]}/{self.sha256}",
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


class EvidenceSnapshotBuilder:
    """Collect immutable source roots/files and build one portable snapshot."""

    def __init__(
        self,
        output_root: Path,
        *,
        allowed_source_roots: Iterable[Path] = (),
        source_aliases: Mapping[str, Path] | None = None,
        required_reference_registry: Mapping[str, Any] | None = None,
    ) -> None:
        self.output_root = _assert_no_lexical_reparse(
            output_root, label="snapshot output"
        ).resolve()
        self.allowed_source_roots = tuple(
            _assert_no_lexical_reparse(path, label="allowed source root").resolve()
            for path in allowed_source_roots
        )
        aliases: dict[str, Path] = {}
        for key, value in (source_aliases or {}).items():
            normalized = _normalize_alias_prefix(key)
            _require(
                normalized.casefold() not in {item.casefold() for item in aliases},
                f"source alias casefold collision: {key}",
            )
            _require(
                not any(
                    normalized.casefold().startswith(item.casefold() + "/")
                    or item.casefold().startswith(normalized.casefold() + "/")
                    for item in aliases
                ),
                f"source aliases overlap: {key}",
            )
            aliases[normalized] = _assert_no_lexical_reparse(
                value, label="source alias target"
            ).resolve()
        self.source_aliases = aliases
        self.required_reference_registry = _reference_registry(required_reference_registry)
        soft_path_allowlist = _soft_path_allowlist_from_environment()
        self.soft_path_allowlist = soft_path_allowlist.entries
        self._soft_path_allowlist_keys = soft_path_allowlist.keys
        self._roots: dict[str, Path] = {}
        self._records: dict[str, _SourceRecord] = {}
        self._source_to_ref: dict[str, str] = {}
        self._external_roots_by_source: dict[str, str] = {}
        self._view_casefold: dict[str, str] = {}
        self._entry_points: set[str] = set()
        self._unresolved_metadata_refs: list[dict[str, str]] = []
        self._required_reference_matches: list[dict[str, str]] = []

    def add_root(
        self,
        root_id: str,
        source_root: Path,
        *,
        exclude_relative: Iterable[str] = (),
        entry_point: bool = True,
    ) -> None:
        root_id = _validate_id(root_id, label="root_id")
        _require(
            root_id.casefold() not in {key.casefold() for key in self._roots},
            "root_id casefold collision",
        )
        source_root = _assert_no_lexical_reparse(
            source_root, label=f"logical root {root_id}"
        ).resolve()
        for prior_id, prior_root in self._roots.items():
            _require(
                source_root != prior_root
                and not _inside(source_root, prior_root)
                and not _inside(prior_root, source_root),
                f"logical roots overlap: {prior_id} / {root_id}",
            )
        _require(
            not _inside(self.output_root, source_root), "snapshot output is inside a source root"
        )
        excluded = {
            _validate_relative(item, label="excluded relative path") for item in exclude_relative
        }
        files = list(_iter_regular_files(source_root))
        relative_casefold: dict[str, str] = {}
        self._roots[root_id] = source_root
        for source in files:
            relative = source.relative_to(source_root).as_posix()
            if relative in excluded:
                continue
            prior = relative_casefold.get(relative.casefold())
            _require(prior is None, f"source root has a casefold collision: {prior} / {relative}")
            relative_casefold[relative.casefold()] = relative
            self._register(
                logical_ref=f"root/{root_id}/{relative}",
                source=source,
                view_ref=f"roots/{root_id}/{relative}",
                root_id=root_id,
                relative_path=relative,
            )
        _require(
            any(record.root_id == root_id for record in self._records.values()),
            f"logical root is empty: {root_id}",
        )
        if entry_point:
            self._entry_points.add(f"root:{root_id}")

    def add_file(
        self,
        logical_id: str,
        source: Path,
        *,
        entry_point: bool = True,
    ) -> str:
        logical_id = _validate_id(logical_id, label="logical file id")
        logical_ref = f"file/{logical_id}"
        self._register(
            logical_ref=logical_ref,
            source=_assert_no_lexical_reparse(source, label=f"logical file {logical_id}").resolve(),
            view_ref=f"files/{logical_id}",
            root_id=None,
            relative_path=None,
        )
        if entry_point:
            self._entry_points.add(logical_ref)
        return logical_ref

    def _register(
        self,
        *,
        logical_ref: str,
        source: Path,
        view_ref: str,
        root_id: str | None,
        relative_path: str | None,
    ) -> None:
        logical_ref = _validate_relative(logical_ref, label="logical_ref")
        view_ref = _validate_relative(view_ref, label="view_ref")
        _require(logical_ref not in self._records, f"duplicate logical_ref: {logical_ref}")
        _require(
            logical_ref.casefold() not in {key.casefold() for key in self._records},
            "logical_ref casefold collision",
        )
        prior_view = self._view_casefold.get(view_ref.casefold())
        _require(prior_view is None, f"view path casefold collision: {prior_view} / {view_ref}")
        _require(source.is_file(), f"logical source file is missing: {source}")
        _require(not _is_reparse(source), f"logical source is a reparse point: {source}")
        digest = file_sha256(source)
        self._records[logical_ref] = _SourceRecord(
            logical_ref=logical_ref,
            source=source,
            view_ref=view_ref,
            root_id=root_id,
            relative_path=relative_path,
            sha256=digest,
            size_bytes=source.stat().st_size,
        )
        self._view_casefold[view_ref.casefold()] = view_ref
        self._source_to_ref.setdefault(_path_key(source), logical_ref)

    def _allowed(self, path: Path) -> bool:
        roots = (*self._roots.values(), *self.allowed_source_roots)
        return any(_inside(path, root) or path.resolve() == root for root in roots)

    def _source_candidate(self, raw: str, record: _SourceRecord) -> Path | None:
        local_path = _local_reference_path(raw)
        candidate_text = local_path if local_path is not None else raw
        normalized = candidate_text.replace("\\", "/")
        candidates: list[Path] = []
        for prefix, target in self.source_aliases.items():
            if normalized.casefold() == prefix.casefold():
                candidates.append(target)
            elif normalized.casefold().startswith(prefix.casefold() + "/"):
                suffix = _validate_relative(
                    normalized[len(prefix) + 1 :],
                    label="source alias suffix",
                )
                alias_candidate = target / Path(*suffix.split("/"))
                _require(
                    _inside(alias_candidate, target),
                    f"source alias suffix escaped its target: {raw}",
                )
                candidates.append(alias_candidate)
        if not candidates:
            raw_path = Path(candidate_text)
            if raw_path.is_absolute():
                candidates.append(raw_path)
            else:
                if record.root_id is not None:
                    candidates.append(self._roots[record.root_id] / raw_path)
                candidates.append(record.source.parent / raw_path)
        for candidate in candidates:
            try:
                lexical = _assert_no_lexical_reparse(candidate, label="referenced source")
                resolved = lexical.resolve()
            except OSError:
                continue
            if resolved.exists():
                return resolved
        return None

    def _directory_target(self, path: Path) -> tuple[str, str] | None:
        for root_id, source_root in self._roots.items():
            if path == source_root:
                return root_id, ""
            if _inside(path, source_root):
                return root_id, path.relative_to(source_root).as_posix()
        return None

    def _add_external(self, source: Path, *, source_ref: str, pointer: str) -> str:
        source_key = _path_key(source)
        known = self._source_to_ref.get(source_key)
        if known is not None:
            return known
        logical_identity = hashlib.sha256(f"{source_ref}\0{pointer}".encode()).hexdigest()
        logical_ref = f"external/reference/{logical_identity}"
        if logical_ref not in self._records:
            safe_name = source.name.replace("\\", "_").replace("/", "_")
            self._register(
                logical_ref=logical_ref,
                source=source,
                view_ref=(
                    f"external/reference/{logical_identity[:2]}/{logical_identity}/{safe_name}"
                ),
                root_id=None,
                relative_path=None,
            )
        self._source_to_ref[source_key] = logical_ref
        return logical_ref

    def _add_external_root(
        self,
        source: Path,
        *,
        source_ref: str,
        pointer: str,
    ) -> str:
        source_key = _path_key(source)
        known = self._external_roots_by_source.get(source_key)
        if known is not None:
            return known
        identity = hashlib.sha256(f"{source_ref}\0{pointer}\0directory".encode()).hexdigest()
        root_id = f"external-{identity}"
        self.add_root(root_id, source, entry_point=False)
        self._external_roots_by_source[source_key] = root_id
        return root_id

    def _discover_edges(self) -> list[dict[str, Any]]:
        edges: dict[tuple[str, str], dict[str, Any]] = {}
        unresolved: dict[tuple[str, str], dict[str, str]] = {}
        required_matches: dict[tuple[str, str, str], dict[str, str]] = {}
        queue = deque(sorted(self._records))
        scanned: set[str] = set()
        while queue:
            logical_ref = queue.popleft()
            if logical_ref in scanned:
                continue
            scanned.add(logical_ref)
            record = self._records[logical_ref]
            try:
                value = json.loads(record.source.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            for pointer, key_name, raw in _reference_values(value):
                normalized_raw = raw.replace("\\", "/")
                selected_alias = any(
                    normalized_raw.casefold() == prefix.casefold()
                    or normalized_raw.casefold().startswith(prefix.casefold() + "/")
                    for prefix in self.source_aliases
                )
                matching_rule_ids = _matching_registry_rule_ids(
                    self.required_reference_registry,
                    source_ref=logical_ref,
                    pointer=pointer,
                )
                required_by_rule = bool(matching_rule_ids)
                for rule_id in matching_rule_ids:
                    required_matches[(rule_id, logical_ref, pointer)] = {
                        "rule_id": rule_id,
                        "source_ref": logical_ref,
                        "json_pointer": pointer,
                    }
                try:
                    local_path = _local_reference_path(raw)
                except SnapshotError:
                    if selected_alias or key_name in _PATH_KEYS or required_by_rule:
                        raise
                    unresolved[(logical_ref, pointer)] = {
                        "source_ref": logical_ref,
                        "json_pointer": pointer,
                        "recorded_value": raw,
                        "reason": "invalid_local_identity",
                    }
                    continue
                candidate = self._source_candidate(raw, record)
                if candidate is None:
                    soft_entry = {
                        "source_ref": logical_ref,
                        "json_pointer": pointer,
                        "recorded_value": raw,
                        "reason": "missing_local_target",
                    }
                    soft_key = (
                        logical_ref,
                        pointer,
                        raw,
                        "missing_local_target",
                    )
                    if (
                        key_name in _PATH_KEYS
                        and local_path is not None
                        and not required_by_rule
                        and soft_key in self._soft_path_allowlist_keys
                    ):
                        unresolved[(logical_ref, pointer)] = soft_entry
                        continue
                    if key_name in _PATH_KEYS and local_path is not None:
                        _require(
                            soft_key not in self._soft_path_allowlist_keys,
                            "soft path allowlist entry was inconsistently classified",
                        )
                    _require(
                        not required_by_rule
                        and not (key_name in _PATH_KEYS and local_path is not None),
                        (
                            "required local reference is missing: "
                            f"{logical_ref}:{pointer} ({key_name})"
                        ),
                    )
                    if key_name.endswith("_ref") and local_path is not None:
                        unresolved[(logical_ref, pointer)] = {
                            "source_ref": logical_ref,
                            "json_pointer": pointer,
                            "recorded_value": raw,
                            "reason": "missing_local_target",
                        }
                    continue
                _require(
                    self._allowed(candidate),
                    f"referenced source escapes allowed roots: {candidate}",
                )
                if candidate.is_dir():
                    target = self._directory_target(candidate)
                    if target is None:
                        external_root = self._add_external_root(
                            candidate,
                            source_ref=logical_ref,
                            pointer=pointer,
                        )
                        queue.extend(
                            sorted(
                                ref
                                for ref, item in self._records.items()
                                if item.root_id == external_root
                            )
                        )
                        target = (external_root, "")
                    target_root, target_relative = target
                    prefix = f"{target_relative}/" if target_relative else ""
                    _require(
                        any(
                            record.root_id == target_root
                            and (not prefix or str(record.relative_path or "").startswith(prefix))
                            for record in self._records.values()
                        ),
                        f"referenced directory has no archived files: {candidate}",
                    )
                    edge = {
                        "source_ref": logical_ref,
                        "json_pointer": pointer,
                        "recorded_value": raw,
                        "target_kind": "directory",
                        "target_root_id": target_root,
                        "target_relative_path": target_relative,
                    }
                else:
                    target_ref = self._source_to_ref.get(_path_key(candidate))
                    if target_ref is None:
                        target_ref = self._add_external(
                            candidate,
                            source_ref=logical_ref,
                            pointer=pointer,
                        )
                        queue.append(target_ref)
                    edge = {
                        "source_ref": logical_ref,
                        "json_pointer": pointer,
                        "recorded_value": raw,
                        "target_kind": "file",
                        "target_ref": target_ref,
                    }
                key = (logical_ref, pointer)
                _require(key not in edges or edges[key] == edge, f"ambiguous reference edge: {key}")
                edges[key] = edge
        self._unresolved_metadata_refs = [unresolved[key] for key in sorted(unresolved)]
        observed_soft_paths = [
            entry
            for entry in self._unresolved_metadata_refs
            if _pointer_parts(entry["json_pointer"])[-1] in _PATH_KEYS
        ]
        _require(
            observed_soft_paths == self.soft_path_allowlist,
            "soft path allowlist is not the exact observed PATH_KEY inventory",
        )
        self._required_reference_matches = [
            required_matches[key] for key in sorted(required_matches)
        ]
        match_counts: dict[str, int] = {}
        for match in self._required_reference_matches:
            match_counts[match["rule_id"]] = match_counts.get(match["rule_id"], 0) + 1
        for rule in self.required_reference_registry["rules"]:
            _require(
                match_counts.get(str(rule["rule_id"]), 0) == int(rule["expected_match_count"]),
                (
                    "required reference rule match count drifted: "
                    f"{rule['rule_id']} expected={rule['expected_match_count']} "
                    f"actual={match_counts.get(str(rule['rule_id']), 0)}"
                ),
            )
        return [edges[key] for key in sorted(edges)]

    def _reachable(self, edges: Iterable[Mapping[str, Any]]) -> set[str]:
        return _reachable_logical_refs(
            entry_points=self._entry_points,
            refs=set(self._records),
            root_refs={
                root_id: {ref for ref, record in self._records.items() if record.root_id == root_id}
                for root_id in self._roots
            },
            edges=edges,
        )

    def build(self) -> Path:
        _require(
            not self.output_root.exists(), f"snapshot output already exists: {self.output_root}"
        )
        _require(self._records, "snapshot has no logical files")
        edges = self._discover_edges()
        reachable = self._reachable(edges)
        self.output_root.mkdir(parents=True, exist_ok=False)
        try:
            cas_written: set[str] = set()
            for record in sorted(self._records.values(), key=lambda item: item.logical_ref):
                cas_ref = f"cas/sha256/{record.sha256[:2]}/{record.sha256}"
                cas_path = self.output_root / Path(*cas_ref.split("/"))
                if cas_ref not in cas_written:
                    cas_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(record.source, cas_path)
                    cas_written.add(cas_ref)
                view_path = self.output_root / Path(*record.view_ref.split("/"))
                view_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(record.source, view_path)

            logical_values = [
                record.manifest_value()
                for record in sorted(self._records.values(), key=lambda item: item.logical_ref)
            ]
            roots = []
            for root_id in sorted(self._roots):
                refs = sorted(
                    record.logical_ref
                    for record in self._records.values()
                    if record.root_id == root_id
                )
                roots.append(
                    {
                        "root_id": root_id,
                        "source_identity": _logical_identity(self._roots[root_id]),
                        "view_ref": f"roots/{root_id}",
                        "file_count": len(refs),
                        "logical_refs": refs,
                    }
                )
            identities: dict[str, dict[str, Any]] = {}
            for record in self._records.values():
                for relative in (
                    record.view_ref,
                    f"cas/sha256/{record.sha256[:2]}/{record.sha256}",
                ):
                    identities[relative] = {
                        "relative_path": relative,
                        "sha256": record.sha256,
                        "size_bytes": record.size_bytes,
                    }
            inventory = [identities[key] for key in sorted(identities)]
            core: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "logical_alias_count": len(self.source_aliases),
                "logical_aliases": [
                    {
                        "logical_prefix": prefix,
                        "source_identity": _logical_identity(target),
                    }
                    for prefix, target in sorted(self.source_aliases.items())
                ],
                "entry_points": sorted(self._entry_points),
                "logical_root_count": len(roots),
                "logical_roots": roots,
                "logical_ref_count": len(logical_values),
                "logical_refs": logical_values,
                "reference_edge_count": len(edges),
                "reference_edges": edges,
                "required_reference_registry": self.required_reference_registry,
                "required_reference_match_count": len(self._required_reference_matches),
                "required_reference_matches": self._required_reference_matches,
                "unresolved_metadata_ref_count": len(self._unresolved_metadata_refs),
                "unresolved_metadata_refs": self._unresolved_metadata_refs,
                "reachable_logical_ref_count": len(reachable),
                "full_archival_logical_ref_count": len(logical_values),
                "cas_object_count": len(cas_written),
                "inventory_count": len(inventory),
                "inventory": inventory,
                "inventory_sha256": canonical_sha256(inventory),
            }
            manifest = {**core, "content_sha256": canonical_sha256(core)}
            manifest_path = self.output_root / MANIFEST_NAME
            manifest_path.write_bytes(canonical_json_bytes(manifest))
            verify_snapshot_manifest(manifest_path)
            return manifest_path
        except Exception:
            shutil.rmtree(self.output_root, ignore_errors=True)
            raise


def _walk_capsule_files(root: Path, expected_files: set[str]) -> set[str]:
    actual: set[str] = set()
    actual_directories: set[str] = set()
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        if directory_path != root:
            actual_directories.add(directory_path.relative_to(root).as_posix())
        for name in names:
            path = directory_path / name
            _require(not _is_reparse(path), f"snapshot directory is a reparse point: {path}")
        for name in files:
            path = directory_path / name
            _require(not _is_reparse(path), f"snapshot file is a reparse point: {path}")
            _require(path.is_file(), f"snapshot object is not a regular file: {path}")
            relative = path.resolve().relative_to(root).as_posix()
            if relative != MANIFEST_NAME:
                actual.add(relative)
    expected_directories = {
        parent.as_posix()
        for relative in expected_files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    _require(
        actual_directories == expected_directories,
        "snapshot has missing or extra directories",
    )
    return actual


def verify_snapshot_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest_path = _assert_no_lexical_reparse(manifest_path, label="snapshot manifest").resolve()
    _require(manifest_path.name == MANIFEST_NAME, "snapshot manifest name drifted")
    _require(manifest_path.is_file(), f"snapshot manifest is missing: {manifest_path}")
    _require(not _is_reparse(manifest_path), "snapshot manifest is a reparse point")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("snapshot manifest is not valid JSON") from exc
    _require(isinstance(manifest, dict), "snapshot manifest is not an object")
    expected_manifest_keys = {
        "schema_version",
        "logical_alias_count",
        "logical_aliases",
        "entry_points",
        "logical_root_count",
        "logical_roots",
        "logical_ref_count",
        "logical_refs",
        "reference_edge_count",
        "reference_edges",
        "required_reference_registry",
        "required_reference_match_count",
        "required_reference_matches",
        "unresolved_metadata_ref_count",
        "unresolved_metadata_refs",
        "reachable_logical_ref_count",
        "full_archival_logical_ref_count",
        "cas_object_count",
        "inventory_count",
        "inventory",
        "inventory_sha256",
        "content_sha256",
    }
    _require(set(manifest) == expected_manifest_keys, "snapshot manifest key set drifted")
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "snapshot schema drifted")
    core = dict(manifest)
    content_hash = str(core.pop("content_sha256", ""))
    _require(_SHA256_RE.fullmatch(content_hash) is not None, "snapshot content hash is invalid")
    _require(content_hash == canonical_sha256(core), "snapshot content identity drifted")
    root = manifest_path.parent.resolve()
    soft_path_allowlist = _soft_path_allowlist_from_environment()
    if soft_path_allowlist.source_manifest_sha256 is not None:
        _require(
            soft_path_allowlist.source_manifest_sha256 == file_sha256(manifest_path),
            "soft path allowlist source manifest identity drifted",
        )
        _require(
            soft_path_allowlist.source_content_sha256 == content_hash,
            "soft path allowlist source content identity drifted",
        )
    soft_path_allowlist_entries = soft_path_allowlist.entries
    soft_path_allowlist_keys = soft_path_allowlist.keys

    raw_refs = manifest.get("logical_refs")
    _require(isinstance(raw_refs, list) and raw_refs, "snapshot logical refs are empty")
    raw_logical_ref_names = [
        str(item.get("logical_ref") or "") for item in raw_refs if isinstance(item, dict)
    ]
    _require(
        len(raw_logical_ref_names) == len(raw_refs)
        and len({item.casefold() for item in raw_logical_ref_names}) == len(raw_refs),
        "logical_ref casefold collision",
    )
    refs: dict[str, dict[str, Any]] = {}
    view_casefold: dict[str, str] = {}
    for raw in raw_refs:
        _require(isinstance(raw, dict), "snapshot logical ref is not an object")
        _require(
            set(raw)
            == {
                "logical_ref",
                "source_identity",
                "root_id",
                "relative_path",
                "view_ref",
                "cas_ref",
                "sha256",
                "size_bytes",
            },
            "snapshot logical ref key set drifted",
        )
        logical_ref = _validate_relative(raw.get("logical_ref"), label="logical_ref")
        source_identity = _logical_identity(raw.get("source_identity"))
        view_ref = _validate_relative(raw.get("view_ref"), label="view_ref")
        digest = str(raw.get("sha256") or "")
        size = _integer(raw.get("size_bytes"), label=f"logical ref size: {logical_ref}")
        cas_ref = _validate_relative(raw.get("cas_ref"), label="cas_ref")
        _require(
            _SHA256_RE.fullmatch(digest) is not None, f"logical ref hash invalid: {logical_ref}"
        )
        _require(cas_ref == f"cas/sha256/{digest[:2]}/{digest}", f"CAS ref drifted: {logical_ref}")
        _require(size >= 0, f"logical ref size invalid: {logical_ref}")
        _require(logical_ref not in refs, f"duplicate logical_ref: {logical_ref}")
        _require(
            logical_ref.casefold() not in {key.casefold() for key in refs},
            "logical_ref casefold collision",
        )
        prior_view = view_casefold.get(view_ref.casefold())
        _require(prior_view is None, f"view path casefold collision: {prior_view} / {view_ref}")
        view_casefold[view_ref.casefold()] = view_ref
        root_id_value = raw.get("root_id")
        relative_value = raw.get("relative_path")
        if root_id_value is None:
            _require(relative_value is None, f"standalone relative_path drifted: {logical_ref}")
            if logical_ref.startswith("file/"):
                expected_view = f"files/{logical_ref.split('/', 1)[1]}"
            elif logical_ref.startswith("external/reference/"):
                identity = logical_ref.rsplit("/", 1)[1]
                _require(
                    _SHA256_RE.fullmatch(identity) is not None,
                    f"external logical identity is invalid: {logical_ref}",
                )
                expected_view = f"external/reference/{identity[:2]}/{identity}"
                expected_named_view = f"{expected_view}/{source_identity.rsplit('/', 1)[-1]}"
            else:
                raise SnapshotError(f"unknown standalone logical class: {logical_ref}")
            _require(
                view_ref == expected_view
                or (
                    logical_ref.startswith("external/reference/")
                    and view_ref == expected_named_view
                ),
                f"standalone view topology drifted: {logical_ref}",
            )
        else:
            root_id = _validate_id(root_id_value, label=f"logical ref root_id: {logical_ref}")
            relative = _validate_relative(
                relative_value,
                label=f"logical ref relative_path: {logical_ref}",
            )
            _require(
                logical_ref == f"root/{root_id}/{relative}"
                and view_ref == f"roots/{root_id}/{relative}",
                f"rooted logical topology drifted: {logical_ref}",
            )
        _require(
            raw.get("source_identity") == source_identity,
            f"logical source identity is not canonical: {logical_ref}",
        )
        refs[logical_ref] = dict(raw)
    _require(
        raw_refs == [refs[key] for key in sorted(refs)], "logical refs are not canonically ordered"
    )
    _require(
        _integer(manifest.get("logical_ref_count"), label="logical_ref_count") == len(refs),
        "logical_ref_count drifted",
    )

    raw_roots = manifest.get("logical_roots")
    _require(isinstance(raw_roots, list), "logical roots are not a list")
    roots: dict[str, dict[str, Any]] = {}
    for raw in raw_roots:
        _require(isinstance(raw, dict), "logical root is not an object")
        _require(
            set(raw) == {"root_id", "source_identity", "view_ref", "file_count", "logical_refs"},
            "logical root key set drifted",
        )
        root_id = _validate_id(raw.get("root_id"), label="root_id")
        root_source_identity = _logical_identity(raw.get("source_identity"))
        _require(
            raw.get("source_identity") == root_source_identity,
            f"logical root source identity is not canonical: {root_id}",
        )
        _require(
            root_id.casefold() not in {key.casefold() for key in roots},
            "root_id casefold collision",
        )
        root_refs = raw.get("logical_refs")
        _require(isinstance(root_refs, list), f"logical root refs missing: {root_id}")
        _require(
            root_refs == sorted(root_refs) and len(root_refs) == len(set(root_refs)),
            f"logical root refs drifted: {root_id}",
        )
        _require(
            _integer(raw.get("file_count"), label=f"logical root file_count: {root_id}")
            == len(root_refs),
            f"logical root file_count drifted: {root_id}",
        )
        _require(
            raw.get("view_ref") == f"roots/{root_id}", f"logical root view_ref drifted: {root_id}"
        )
        for logical_ref in root_refs:
            _require(
                logical_ref in refs and refs[logical_ref].get("root_id") == root_id,
                f"logical root membership drifted: {logical_ref}",
            )
            relative = str(refs[logical_ref]["relative_path"])
            _require(
                _identity_key(refs[logical_ref]["source_identity"])
                == _identity_key(_join_identity(root_source_identity, relative)),
                f"logical root source topology drifted: {logical_ref}",
            )
        roots[root_id] = dict(raw)
    _require(
        raw_roots == [roots[key] for key in sorted(roots)],
        "logical roots are not canonically ordered",
    )
    _require(
        _integer(manifest.get("logical_root_count"), label="logical_root_count") == len(roots),
        "logical_root_count drifted",
    )
    for logical_ref, raw in refs.items():
        root_id = raw.get("root_id")
        if root_id is not None:
            _require(root_id in roots, f"logical ref names an unknown root: {logical_ref}")
            _require(
                roots[str(root_id)]["logical_refs"].count(logical_ref) == 1,
                f"logical ref root membership is not unique: {logical_ref}",
            )

    raw_aliases = manifest.get("logical_aliases")
    _require(isinstance(raw_aliases, list), "logical aliases are not a list")
    aliases: dict[str, str] = {}
    for raw in raw_aliases:
        _require(isinstance(raw, dict), "logical alias is not an object")
        _require(
            set(raw) == {"logical_prefix", "source_identity"},
            "logical alias key set drifted",
        )
        prefix = _normalize_alias_prefix(raw.get("logical_prefix"))
        identity = _logical_identity(raw.get("source_identity"))
        _require(raw.get("logical_prefix") == prefix, "logical alias prefix is not canonical")
        _require(
            raw.get("source_identity") == identity,
            "logical alias source identity is not canonical",
        )
        _require(
            prefix.casefold() not in {item.casefold() for item in aliases},
            "logical alias casefold collision",
        )
        _require(
            not any(
                prefix.casefold().startswith(item.casefold() + "/")
                or item.casefold().startswith(prefix.casefold() + "/")
                for item in aliases
            ),
            "logical aliases overlap",
        )
        aliases[prefix] = identity
    _require(
        raw_aliases
        == [
            {"logical_prefix": prefix, "source_identity": aliases[prefix]}
            for prefix in sorted(aliases)
        ],
        "logical aliases are not canonically ordered",
    )
    _require(
        _integer(manifest.get("logical_alias_count"), label="logical_alias_count") == len(aliases),
        "logical_alias_count drifted",
    )

    raw_registry = manifest.get("required_reference_registry")
    _require(isinstance(raw_registry, dict), "required reference registry is not an object")
    _require(
        set(raw_registry)
        == {
            "schema_version",
            "source",
            "version",
            "builtin_local_path_keys",
            "rules",
            "content_sha256",
        },
        "required reference registry manifest key set drifted",
    )
    registry = _reference_registry(
        {
            "source": raw_registry.get("source"),
            "version": raw_registry.get("version"),
            "rules": raw_registry.get("rules"),
        }
    )
    _require(raw_registry == registry, "required reference registry identity drifted")

    raw_edges = manifest.get("reference_edges")
    _require(isinstance(raw_edges, list), "reference edges are not a list")
    edge_keys: set[tuple[str, str]] = set()
    for edge in raw_edges:
        _require(isinstance(edge, dict), "reference edge is not an object")
        source_ref = str(edge.get("source_ref") or "")
        pointer = str(edge.get("json_pointer") or "")
        _pointer_parts(pointer)
        _require(source_ref in refs, f"edge source is unknown: {source_ref}")
        _require(
            (source_ref, pointer) not in edge_keys,
            f"duplicate reference edge: {source_ref}:{pointer}",
        )
        edge_keys.add((source_ref, pointer))
        kind = edge.get("target_kind")
        if kind == "file":
            _require(
                set(edge)
                == {
                    "source_ref",
                    "json_pointer",
                    "recorded_value",
                    "target_kind",
                    "target_ref",
                },
                "file reference edge key set drifted",
            )
            _require(
                edge.get("target_ref") in refs, f"edge target is unknown: {edge.get('target_ref')}"
            )
        elif kind == "directory":
            _require(
                set(edge)
                == {
                    "source_ref",
                    "json_pointer",
                    "recorded_value",
                    "target_kind",
                    "target_root_id",
                    "target_relative_path",
                },
                "directory reference edge key set drifted",
            )
            target_root = str(edge.get("target_root_id") or "")
            _require(target_root in roots, f"edge root target is unknown: {target_root}")
            relative = str(edge.get("target_relative_path") or "")
            if relative:
                _validate_relative(relative, label="directory edge relative path")
        else:
            raise SnapshotError(f"reference edge target kind is invalid: {kind}")
        source_path = root / Path(*str(refs[source_ref]["view_ref"]).split("/"))
        try:
            source_value = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"reference edge source is not JSON: {source_ref}") from exc
        recorded = _value_at_pointer(source_value, pointer)
        _require(
            isinstance(recorded, str) and recorded == edge.get("recorded_value"),
            f"reference edge does not identify a string: {source_ref}:{pointer}",
        )
        identity_candidates = _reference_identity_candidates(
            recorded,
            source=refs[source_ref],
            roots=roots,
            aliases=aliases,
        )
        if kind == "file":
            target_identity = str(refs[str(edge["target_ref"])]["source_identity"])
        else:
            target_identity = _join_identity(
                str(roots[str(edge["target_root_id"])]["source_identity"]),
                str(edge.get("target_relative_path") or ""),
            )
        _require(
            _identity_key(target_identity) in identity_candidates,
            f"reference edge retargeted recorded identity: {source_ref}:{pointer}",
        )
    _require(
        raw_edges == sorted(raw_edges, key=lambda item: (item["source_ref"], item["json_pointer"])),
        "reference edges are not canonically ordered",
    )
    _require(
        _integer(manifest.get("reference_edge_count"), label="reference_edge_count")
        == len(raw_edges),
        "reference_edge_count drifted",
    )

    raw_required_matches = manifest.get("required_reference_matches")
    _require(
        isinstance(raw_required_matches, list),
        "required reference matches are not a list",
    )
    registry_rule_ids = {str(rule["rule_id"]) for rule in registry["rules"]}
    required_matches: dict[tuple[str, str, str], dict[str, str]] = {}
    for raw in raw_required_matches:
        _require(isinstance(raw, dict), "required reference match is not an object")
        _require(
            set(raw) == {"rule_id", "source_ref", "json_pointer"},
            "required reference match key set drifted",
        )
        rule_id = str(raw.get("rule_id") or "")
        source_ref = str(raw.get("source_ref") or "")
        pointer = str(raw.get("json_pointer") or "")
        _pointer_parts(pointer)
        _require(rule_id in registry_rule_ids, f"required match rule is unknown: {rule_id}")
        _require(source_ref in refs, f"required match source is unknown: {source_ref}")
        _require(
            rule_id
            in _matching_registry_rule_ids(
                registry,
                source_ref=source_ref,
                pointer=pointer,
            ),
            f"required match does not satisfy its rule: {rule_id}",
        )
        key = (rule_id, source_ref, pointer)
        _require(key not in required_matches, f"duplicate required reference match: {key}")
        required_matches[key] = dict(raw)
    _require(
        raw_required_matches == [required_matches[key] for key in sorted(required_matches)],
        "required reference matches are not canonically ordered",
    )
    _require(
        _integer(
            manifest.get("required_reference_match_count"),
            label="required_reference_match_count",
        )
        == len(required_matches),
        "required reference match count drifted",
    )

    raw_unresolved = manifest.get("unresolved_metadata_refs")
    _require(isinstance(raw_unresolved, list), "unresolved metadata refs are not a list")
    unresolved: dict[tuple[str, str], dict[str, str]] = {}
    for raw in raw_unresolved:
        _require(isinstance(raw, dict), "unresolved metadata ref is not an object")
        _require(
            set(raw) == {"source_ref", "json_pointer", "recorded_value", "reason"},
            "unresolved metadata ref key set drifted",
        )
        source_ref = str(raw.get("source_ref") or "")
        pointer = str(raw.get("json_pointer") or "")
        recorded_value = raw.get("recorded_value")
        reason = str(raw.get("reason") or "")
        _pointer_parts(pointer)
        _require(source_ref in refs, f"unresolved metadata source is unknown: {source_ref}")
        _require(isinstance(recorded_value, str), "unresolved recorded value is not a string")
        _require(reason in _UNRESOLVED_REASONS, "unresolved metadata reason is invalid")
        key = (source_ref, pointer)
        _require(
            key not in unresolved,
            f"duplicate unresolved metadata ref: {source_ref}:{pointer}",
        )
        _require(
            key not in edge_keys,
            f"reference is both resolved and unresolved: {source_ref}:{pointer}",
        )
        source_path = root / Path(*str(refs[source_ref]["view_ref"]).split("/"))
        try:
            source_value = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"unresolved metadata source is not JSON: {source_ref}") from exc
        recorded = _value_at_pointer(source_value, pointer)
        _require(
            recorded == recorded_value,
            f"unresolved metadata identity drifted: {source_ref}:{pointer}",
        )
        key_name = _pointer_parts(pointer)[-1]
        soft_key = (source_ref, pointer, recorded_value, reason)
        _require(
            (key_name.endswith("_ref") and key_name not in _PATH_KEYS)
            or (key_name in _PATH_KEYS and soft_key in soft_path_allowlist_keys),
            f"unresolved metadata is not an optional ref: {source_ref}:{pointer}",
        )
        _require(
            not _registry_rule_requires(registry, source_ref=source_ref, pointer=pointer),
            f"required reference was marked unresolved: {source_ref}:{pointer}",
        )
        if reason == "invalid_local_identity":
            try:
                _local_reference_path(recorded_value)
            except SnapshotError:
                pass
            else:
                raise SnapshotError(
                    f"unresolved invalid-local reason is false: {source_ref}:{pointer}"
                )
        else:
            _require(
                _local_reference_path(recorded_value) is not None,
                f"unresolved missing-local reason is false: {source_ref}:{pointer}",
            )
        unresolved[key] = dict(raw)
    _require(
        raw_unresolved == [unresolved[key] for key in sorted(unresolved)],
        "unresolved metadata refs are not canonically ordered",
    )
    observed_soft_paths = [
        entry
        for entry in raw_unresolved
        if _pointer_parts(str(entry["json_pointer"]))[-1] in _PATH_KEYS
    ]
    _require(
        observed_soft_paths == soft_path_allowlist_entries,
        "manifest PATH_KEY diagnostics do not equal the exact soft path allowlist",
    )
    _require(
        _integer(
            manifest.get("unresolved_metadata_ref_count"),
            label="unresolved_metadata_ref_count",
        )
        == len(unresolved),
        "unresolved metadata ref count drifted",
    )

    observed_required_matches: dict[tuple[str, str, str], dict[str, str]] = {}
    for source_ref, source_raw in refs.items():
        source_path = root / Path(*str(source_raw["view_ref"]).split("/"))
        try:
            source_value = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for pointer, key_name, recorded_value in _reference_values(source_value):
            matching_rule_ids = _matching_registry_rule_ids(
                registry,
                source_ref=source_ref,
                pointer=pointer,
            )
            for rule_id in matching_rule_ids:
                key = (rule_id, source_ref, pointer)
                observed_required_matches[key] = {
                    "rule_id": rule_id,
                    "source_ref": source_ref,
                    "json_pointer": pointer,
                }
            key = (source_ref, pointer)
            if key in edge_keys:
                continue
            required_by_rule = bool(matching_rule_ids)
            try:
                local_path = _local_reference_path(recorded_value)
            except SnapshotError:
                _require(
                    not required_by_rule
                    and key_name not in _PATH_KEYS
                    and key in unresolved
                    and unresolved[key]["reason"] == "invalid_local_identity",
                    f"invalid required local reference is unbound: {source_ref}:{pointer}",
                )
                continue
            _require(
                not required_by_rule,
                f"registry-required reference is unbound: {source_ref}:{pointer}",
            )
            if key_name in _PATH_KEYS and local_path is not None:
                unresolved_entry = unresolved.get(key)
                soft_key = (
                    source_ref,
                    pointer,
                    recorded_value,
                    "missing_local_target",
                )
                if (
                    unresolved_entry is not None
                    and unresolved_entry["reason"] == "missing_local_target"
                    and soft_key in soft_path_allowlist_keys
                ):
                    continue
                raise SnapshotError(
                    f"builtin-required reference is unbound: {source_ref}:{pointer}"
                )
            if key_name.endswith("_ref") and local_path is not None:
                _require(
                    key in unresolved and unresolved[key]["reason"] == "missing_local_target",
                    f"local metadata ref is neither bound nor diagnosed: {source_ref}:{pointer}",
                )
    _require(
        required_matches == observed_required_matches,
        "required reference match inventory drifted",
    )
    observed_match_counts: dict[str, int] = {}
    for rule_id, _, _ in observed_required_matches:
        observed_match_counts[rule_id] = observed_match_counts.get(rule_id, 0) + 1
    for rule in registry["rules"]:
        _require(
            observed_match_counts.get(str(rule["rule_id"]), 0) == int(rule["expected_match_count"]),
            f"required reference rule match count drifted: {rule['rule_id']}",
        )
    entry_points = manifest.get("entry_points")
    _require(
        isinstance(entry_points, list)
        and entry_points
        and entry_points == sorted(entry_points)
        and len(entry_points) == len(set(entry_points))
        and all(isinstance(item, str) and item for item in entry_points),
        "snapshot entry points drifted",
    )
    reachable = _reachable_logical_refs(
        entry_points=entry_points,
        refs=set(refs),
        root_refs={root_id: set(raw["logical_refs"]) for root_id, raw in roots.items()},
        edges=raw_edges,
    )
    _require(
        _integer(
            manifest.get("reachable_logical_ref_count"),
            label="reachable_logical_ref_count",
        )
        == len(reachable),
        "reachable logical ref count drifted",
    )

    raw_inventory = manifest.get("inventory")
    _require(isinstance(raw_inventory, list) and raw_inventory, "snapshot inventory is empty")
    inventory: dict[str, dict[str, Any]] = {}
    inventory_casefold: dict[str, str] = {}
    for raw in raw_inventory:
        _require(isinstance(raw, dict), "snapshot inventory entry is invalid")
        _require(
            set(raw) == {"relative_path", "sha256", "size_bytes"},
            "snapshot inventory entry key set drifted",
        )
        relative = _validate_relative(raw.get("relative_path"), label="inventory path")
        prior = inventory_casefold.get(relative.casefold())
        _require(prior is None, f"inventory casefold collision: {prior} / {relative}")
        inventory_casefold[relative.casefold()] = relative
        _require(relative not in inventory, f"duplicate inventory path: {relative}")
        candidate = root / Path(*relative.split("/"))
        _require(_inside(candidate, root), f"inventory path escaped snapshot: {relative}")
        _require(
            candidate.is_file() and not _is_reparse(candidate),
            f"inventory file missing or reparse: {relative}",
        )
        expected_hash = str(raw.get("sha256") or "")
        expected_size = _integer(raw.get("size_bytes"), label=f"inventory size: {relative}")
        _require(file_sha256(candidate) == expected_hash, f"inventory hash drifted: {relative}")
        _require(candidate.stat().st_size == expected_size, f"inventory size drifted: {relative}")
        inventory[relative] = dict(raw)
    _require(
        raw_inventory == [inventory[key] for key in sorted(inventory)],
        "inventory is not canonically ordered",
    )
    _require(
        _integer(manifest.get("inventory_count"), label="inventory_count") == len(inventory),
        "inventory_count drifted",
    )
    _require(
        manifest.get("inventory_sha256") == canonical_sha256(raw_inventory),
        "inventory identity drifted",
    )
    expected_inventory = {
        str(raw["view_ref"]): (
            str(raw["sha256"]),
            _integer(raw["size_bytes"], label="logical inventory size"),
        )
        for raw in raw_refs
    }
    expected_inventory.update(
        {
            str(raw["cas_ref"]): (
                str(raw["sha256"]),
                _integer(raw["size_bytes"], label="CAS inventory size"),
            )
            for raw in raw_refs
        }
    )
    _require(
        set(inventory) == set(expected_inventory),
        "inventory is not the exact logical-view plus CAS set",
    )
    for relative, identity in expected_inventory.items():
        _require(
            (inventory[relative]["sha256"], inventory[relative]["size_bytes"]) == identity,
            f"inventory identity is inconsistent: {relative}",
        )
    _require(
        _walk_capsule_files(root, set(inventory)) == set(inventory),
        "snapshot has missing or extra files",
    )
    _require(
        _integer(manifest.get("cas_object_count"), label="cas_object_count")
        == len({raw["cas_ref"] for raw in raw_refs}),
        "cas_object_count drifted",
    )
    _require(
        _integer(
            manifest.get("full_archival_logical_ref_count"),
            label="full_archival_logical_ref_count",
        )
        == len(refs),
        "full archival count drifted",
    )
    return manifest


class SnapshotResolver:
    """Resolve only manifest-declared references; live-path fallback is absent."""

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = _assert_no_lexical_reparse(
            manifest_path, label="snapshot resolver manifest"
        ).resolve()
        self.root_path = self.manifest_path.parent
        self.manifest = verify_snapshot_manifest(self.manifest_path)
        self.refs = {str(item["logical_ref"]): dict(item) for item in self.manifest["logical_refs"]}
        self.roots = {str(item["root_id"]): dict(item) for item in self.manifest["logical_roots"]}
        self.edges = {
            (str(item["source_ref"]), str(item["json_pointer"])): dict(item)
            for item in self.manifest["reference_edges"]
        }
        self.view_to_ref = {
            str((self.root_path / Path(*str(item["view_ref"]).split("/"))).resolve()): str(
                item["logical_ref"]
            )
            for item in self.manifest["logical_refs"]
        }
        self._trace: list[dict[str, Any]] = []

    def _record(self, operation: str, **values: object) -> None:
        self._trace.append({"sequence": len(self._trace) + 1, "operation": operation, **values})

    def _root_records(
        self,
        root_id: str,
        relative_path: str,
    ) -> dict[str, dict[str, Any]]:
        prefix = f"{relative_path}/" if relative_path else ""
        return {
            str(raw["relative_path"]): raw
            for raw in self.refs.values()
            if raw.get("root_id") == root_id
            and (not prefix or str(raw.get("relative_path") or "").startswith(prefix))
        }

    def _verify_root_tree(
        self,
        *,
        root_id: str,
        relative_path: str,
        base: Path,
        path: Path,
    ) -> tuple[int, str]:
        declared = self._root_records(root_id, relative_path)
        _require(declared, f"logical root has no declared files: {root_id}/{relative_path}")
        actual_files: set[str] = set()
        actual_directories: set[str] = set()
        for directory, names, files in os.walk(path, followlinks=False):
            directory_path = Path(directory)
            lexical_directory = _assert_no_lexical_reparse(
                directory_path,
                label="logical root directory",
            )
            _require(
                _inside(lexical_directory, base),
                f"logical root directory escaped its view: {directory_path}",
            )
            for name in names:
                candidate = directory_path / name
                _require(
                    not _is_reparse(candidate),
                    f"logical root contains a reparse directory: {candidate}",
                )
                actual_directories.add(candidate.relative_to(base).as_posix())
            for name in files:
                candidate = _assert_no_lexical_reparse(
                    directory_path / name,
                    label="logical root file",
                )
                _require(
                    candidate.is_file() and not _is_reparse(candidate) and _inside(candidate, base),
                    f"logical root file is unavailable: {candidate}",
                )
                relative = candidate.relative_to(base).as_posix()
                actual_files.add(relative)
                expected = declared.get(relative)
                _require(expected is not None, f"logical root has an extra file: {relative}")
                _require(
                    file_sha256(candidate) == expected["sha256"],
                    f"logical root file hash drifted: {relative}",
                )
                _require(
                    candidate.stat().st_size == expected["size_bytes"],
                    f"logical root file size drifted: {relative}",
                )
        _require(
            actual_files == set(declared),
            f"logical root file set drifted: {root_id}/{relative_path}",
        )
        expected_directories = {
            parent.as_posix()
            for relative in declared
            for parent in PurePosixPath(relative).parents
            if parent.as_posix() not in {".", relative_path}
            and (not relative_path or parent.as_posix().startswith(f"{relative_path}/"))
        }
        _require(
            actual_directories == expected_directories,
            f"logical root directory set drifted: {root_id}/{relative_path}",
        )
        content_set = [
            {
                "relative_path": relative,
                "sha256": declared[relative]["sha256"],
                "size_bytes": declared[relative]["size_bytes"],
            }
            for relative in sorted(declared)
        ]
        return len(declared), canonical_sha256(content_set)

    def logical_root(self, root_id: str, relative_path: str = "") -> Path:
        _require(root_id in self.roots, f"unknown logical root: {root_id}")
        base = self.root_path / "roots" / root_id
        path = (
            base
            if not relative_path
            else base
            / Path(*_validate_relative(relative_path, label="root relative path").split("/"))
        )
        lexical_base = _assert_no_lexical_reparse(base, label="logical root base")
        lexical_path = _assert_no_lexical_reparse(path, label="logical root path")
        _require(
            lexical_path.is_dir()
            and not _is_reparse(lexical_path)
            and _inside(lexical_base, self.root_path)
            and _inside(lexical_path, lexical_base),
            f"logical root path is unavailable: {root_id}/{relative_path}",
        )
        verified_file_count, content_set_sha256 = self._verify_root_tree(
            root_id=root_id,
            relative_path=relative_path,
            base=lexical_base,
            path=lexical_path,
        )
        self._record(
            "OPEN_LOGICAL_ROOT",
            root_id=root_id,
            relative_path=relative_path,
            verified_file_count=verified_file_count,
            content_set_sha256=content_set_sha256,
        )
        return lexical_path.resolve()

    def logical_path(self, logical_ref: str) -> Path:
        raw = self.refs.get(logical_ref)
        _require(raw is not None, f"unknown logical_ref: {logical_ref}")
        path = self.root_path / Path(*str(raw["view_ref"]).split("/"))
        lexical = _assert_no_lexical_reparse(path, label="logical file")
        _require(
            lexical.is_file() and not _is_reparse(lexical) and _inside(lexical, self.root_path),
            f"logical file is unavailable: {logical_ref}",
        )
        _require(
            file_sha256(lexical) == raw["sha256"],
            f"logical file hash drifted: {logical_ref}",
        )
        _require(
            lexical.stat().st_size == raw["size_bytes"],
            f"logical file size drifted: {logical_ref}",
        )
        self._record(
            "OPEN_LOGICAL_FILE",
            logical_ref=logical_ref,
            cas_ref=raw["cas_ref"],
            sha256=raw["sha256"],
            size_bytes=raw["size_bytes"],
        )
        return lexical.resolve()

    def logical_ref_for_path(self, path: Path) -> str:
        lexical = _assert_no_lexical_reparse(path, label="logical view lookup")
        logical_ref = self.view_to_ref.get(str(lexical.resolve()))
        _require(logical_ref is not None, f"path is not a declared logical view: {path}")
        return logical_ref

    def resolve_reference(
        self,
        *,
        source_ref: str,
        json_pointer: str,
        recorded_value: object,
    ) -> Path:
        edge = self.edges.get((source_ref, json_pointer))
        _require(
            edge is not None,
            f"snapshot reference has no declared edge: {source_ref}:{json_pointer}",
        )
        source_value = json.loads(self.logical_path(source_ref).read_text(encoding="utf-8"))
        _require(
            _value_at_pointer(source_value, json_pointer)
            == recorded_value
            == edge.get("recorded_value"),
            f"recorded logical identity drifted: {source_ref}:{json_pointer}",
        )
        if edge["target_kind"] == "file":
            result = self.logical_path(str(edge["target_ref"]))
            target_identity = str(edge["target_ref"])
        else:
            result = self.logical_root(
                str(edge["target_root_id"]),
                str(edge.get("target_relative_path") or ""),
            )
            target_identity = (
                f"root:{edge['target_root_id']}/{edge.get('target_relative_path') or ''!s}"
            )
        self._record(
            "RESOLVE_REFERENCE",
            source_ref=source_ref,
            json_pointer=json_pointer,
            target_identity=target_identity,
            fallback_used=False,
        )
        return result

    def recorded_reference(self, *, source_ref: str, json_pointer: str) -> str:
        """Return the retained logical identity for reverse-logicalized output."""

        _require(
            (source_ref, json_pointer) in self.edges,
            f"snapshot reference has no declared edge: {source_ref}:{json_pointer}",
        )
        source_value = self.load_json(source_ref)
        recorded = _value_at_pointer(source_value, json_pointer)
        _require(isinstance(recorded, str), "recorded snapshot reference is not a string")
        return recorded

    def trace_report(self) -> dict[str, Any]:
        core = {
            "schema_version": "xinao.evidence_snapshot_resolution_trace.v1",
            "event_count": len(self._trace),
            "fallback_count": 0,
            "events": list(self._trace),
        }
        return {**core, "content_sha256": canonical_sha256(core)}

    def load_json(self, logical_ref: str) -> dict[str, Any]:
        """Load retained bytes without rewriting their recorded logical paths."""

        try:
            value = json.loads(self.logical_path(logical_ref).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"logical JSON object is invalid: {logical_ref}") from exc
        _require(isinstance(value, dict), f"logical JSON value is not an object: {logical_ref}")
        return value

    def materialized_json(self, logical_ref: str) -> dict[str, Any]:
        """Return a disposable view with declared path fields mapped locally."""

        value = self.load_json(logical_ref)
        for (source_ref, pointer), edge in self.edges.items():
            if source_ref != logical_ref:
                continue
            if edge["target_kind"] == "file":
                replacement = str(self.logical_path(str(edge["target_ref"])))
            else:
                replacement = str(
                    self.logical_root(
                        str(edge["target_root_id"]),
                        str(edge.get("target_relative_path") or ""),
                    )
                )
            _replace_at_pointer(value, pointer, replacement)
        return value


def build_evidence_snapshot(
    output_root: Path,
    *,
    logical_roots: Mapping[str, Path],
    logical_files: Mapping[str, Path] | None = None,
    allowed_source_roots: Iterable[Path] = (),
    source_aliases: Mapping[str, Path] | None = None,
    required_reference_registry: Mapping[str, Any] | None = None,
) -> Path:
    builder = EvidenceSnapshotBuilder(
        output_root,
        allowed_source_roots=allowed_source_roots,
        source_aliases=source_aliases,
        required_reference_registry=required_reference_registry,
    )
    for root_id, path in logical_roots.items():
        builder.add_root(root_id, path)
    for logical_id, path in (logical_files or {}).items():
        builder.add_file(logical_id, path)
    return builder.build()


__all__ = [
    "MANIFEST_NAME",
    "SCHEMA_VERSION",
    "EvidenceSnapshotBuilder",
    "SnapshotError",
    "SnapshotResolver",
    "build_evidence_snapshot",
    "canonical_sha256",
    "file_sha256",
    "verify_snapshot_manifest",
]
