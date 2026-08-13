"""Copy-first migration for mixed ``xinao/reality/live`` trees.

The migration is deliberately additive.  It never removes or rewrites a source
file.  Callers must first park every world-compute lineage at a completed-turn
boundary and pass the controller's active-child PID view.  Any positive PID in
that view closes the gate before destination directories are created.

The canonical live tree is separated into durable provenance and runtime surfaces:

* canonical raw captures, durable metadata, Python sources, and derived payloads
  are retained in immutable content-addressed provenance bundles;
* each complete lineage clone contributes delta and deletion evidence plus one
  exhaustive effective code tree, with no fallback to canonical code;
* each lineage gets an exhaustive live seed and a private mutable live root that
  is initialized atomically once and never reseeded during recovery.

Locks and bytecode are inventoried but intentionally excluded.  Every admitted
file carries both its source-byte hash and migrated-payload hash, and manifests
carry deterministic source-tree and payload-tree hashes.  A fresh readback is
performed before the API returns success.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

MIGRATION_SCHEMA = "xinao.reality-live-copy-first-migration.v1"
INVENTORY_SCHEMA = "xinao.reality-live-inventory.v1"
BASE_BUNDLE_SCHEMA = "xinao.legacy-unattributed-base-bundle.v1"
OVERLAY_SCHEMA = "xinao.legacy-unattributed-workspace-overlay.v1"
READBACK_SCHEMA = "xinao.reality-live-migration-readback.v1"
EFFECTIVE_CODE_SCHEMA = "xinao.lineage-effective-code.v1"
EFFECTIVE_LIVE_SEED_SCHEMA = "xinao.lineage-effective-live-seed.v1"
EFFECTIVE_VIEW_SCHEMA = "xinao.lineage-effective-view.v1"
PRIVATE_LIVE_MARKER_SCHEMA = "xinao.lineage-private-live-origin.v1"
PRIVATE_LIVE_RECEIPT_SCHEMA = "xinao.lineage-private-live-materialization.v1"
RUNTIME_BINDING_INPUTS_SCHEMA = "xinao.runtime-binding-migration-inputs.v1"

LIVE_RELATIVE = Path("xinao") / "reality" / "live"
PRIVATE_LIVE_RELATIVE = Path(".xinao-world-runtime") / "live-reality"
LEGACY_PACKAGE = "xinao_legacy_research"

RAW_LIVE_REALITY = "raw_live_reality"
DURABLE_METADATA = "durable_metadata"
DERIVED_RESEARCH = "derived_research"
RESEARCH_SOURCE = "research_source"
SIMULATION_SOURCE = "simulation_source"
EXCLUDED_LOCK = "excluded_lock"
EXCLUDED_BYTECODE = "excluded_bytecode"

_EXCLUDED = {EXCLUDED_LOCK, EXCLUDED_BYTECODE}
_SOURCE_CLASSES = {RESEARCH_SOURCE, SIMULATION_SOURCE}
_LIVE_CLASSES = {RAW_LIVE_REALITY, DURABLE_METADATA}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WORKSPACE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OLD_NAMESPACE_RE = re.compile(r"\bxinao\s*\.\s*reality\s*\.\s*live\b")
_RNG_RE = re.compile(
    r"\b(?:"
    r"random\.Random|random\.(?:seed|shuffle|sample|choices?|randint|random)|"
    r"np\.random|numpy\.random|default_rng|"
    r"rng\.(?:random|randrange|randint|sample|choices?|shuffle|permutation|"
    r"integers|normal|beta|binomial|multinomial|poisson|dirichlet|uniform|"
    r"multivariate_normal)"
    r")\b"
)

_NAMESPACE_INIT_MARKER = b"# XINAO_LEGACY_RESEARCH_NAMESPACE_V1"
_PRIVATE_LIVE_MARKER_NAME = ".xinao-private-live-origin.json"
_NAMESPACE_INIT_SUFFIX = (
    "\n# XINAO_LEGACY_RESEARCH_NAMESPACE_V1\n"
    "from pkgutil import extend_path as _xinao_extend_path\n"
    "__path__ = _xinao_extend_path(__path__, __name__)\n"
    "del _xinao_extend_path\n"
).encode("utf-8")
_PACKAGE_INIT = (
    '"""Content-addressed legacy research compatibility namespace."""\n'
).encode("utf-8") + _NAMESPACE_INIT_SUFFIX


class RealityMigrationError(RuntimeError):
    """Base error for a rejected or unverifiable migration."""


class ActiveChildProcessError(RealityMigrationError):
    """Raised before mutation when a caller reports an active child PID."""


class SourceTreeChangedError(RealityMigrationError):
    """Raised when source bytes change between inventory and final readback."""


class DestinationConflictError(RealityMigrationError):
    """Raised when a content-addressed destination already has different bytes."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _hash_records(records: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(_canonical_json_bytes(dict(record)))
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


def _resolve_existing_directory(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_dir():
        raise RealityMigrationError(f"{label} is not an existing directory: {candidate}")
    _assert_no_reparse_chain(candidate, label=label)
    return candidate.resolve(strict=True)


def _assert_no_reparse_chain(path: Path, *, label: str) -> None:
    absolute = path.absolute()
    anchor = Path(absolute.anchor)
    current = anchor
    for part in absolute.parts[1:]:
        current /= part
        if current.exists() and _is_reparse(current):
            raise RealityMigrationError(f"{label} crosses a reparse point: {current}")


def _resolve_destination(path: Path, *, label: str) -> Path:
    raw_candidate = Path(path).absolute()
    _assert_no_reparse_chain(raw_candidate, label=label)
    candidate = raw_candidate.resolve(strict=False)
    probe = candidate
    while not probe.exists():
        if probe.parent == probe:
            raise RealityMigrationError(f"{label} has no existing filesystem anchor: {candidate}")
        probe = probe.parent
    if not probe.is_dir() or _is_reparse(probe):
        raise RealityMigrationError(f"{label} anchor is not a regular directory: {probe}")
    return candidate


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_disjoint(source_roots: Iterable[Path], destination_roots: Iterable[Path]) -> None:
    sources = list(source_roots)
    destinations = list(destination_roots)
    for source in sources:
        for destination in destinations:
            if _is_relative_to(source, destination) or _is_relative_to(destination, source):
                raise RealityMigrationError(
                    f"source and destination roots overlap: source={source}; destination={destination}"
                )
    for index, left in enumerate(destinations):
        for right in destinations[index + 1 :]:
            if _is_relative_to(left, right) or _is_relative_to(right, left):
                raise RealityMigrationError(
                    f"destination roots overlap: left={left}; right={right}"
                )


def _active_pid_records(
    active_child_pids: Mapping[str, int | None] | Iterable[int | None],
) -> list[dict[str, Any]]:
    if isinstance(active_child_pids, Mapping):
        values = list(active_child_pids.items())
    else:
        values = [(str(index), value) for index, value in enumerate(active_child_pids)]
    active: list[dict[str, Any]] = []
    for identity, raw_pid in values:
        if raw_pid is None or raw_pid == 0:
            continue
        if isinstance(raw_pid, bool) or not isinstance(raw_pid, int) or raw_pid < 0:
            raise RealityMigrationError(f"invalid child PID for {identity!r}: {raw_pid!r}")
        active.append({"identity": str(identity), "pid": raw_pid})
    return sorted(active, key=lambda item: (item["identity"], item["pid"]))


def assert_no_active_child_pids(
    active_child_pids: Mapping[str, int | None] | Iterable[int | None],
) -> None:
    """Fail closed if the controller reports any positive active-child PID."""

    active = _active_pid_records(active_child_pids)
    if active:
        raise ActiveChildProcessError(
            "ACTIVE_CHILD_PIDS_BLOCK_REALITY_MIGRATION: "
            + json.dumps(active, ensure_ascii=False, sort_keys=True)
        )


def _iter_regular_files(root: Path) -> list[Path]:
    files: list[Path] = []

    def visit(directory: Path) -> None:
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda entry: entry.name.casefold())
        for child in children:
            path = Path(child.path)
            if child.is_symlink() or _is_reparse(path):
                raise RealityMigrationError(f"live tree contains a reparse point: {path}")
            if child.is_dir(follow_symlinks=False):
                visit(path)
            elif child.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise RealityMigrationError(f"live tree contains a non-regular object: {path}")

    visit(root)
    return files


def _read_stable(path: Path) -> bytes:
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(raw) != after.st_size
    ):
        raise SourceTreeChangedError(f"source file changed during read: {path}")
    return raw


def _classification(relative_path: str, raw: bytes) -> str:
    relative = Path(relative_path)
    parts = tuple(part.casefold() for part in relative.parts)
    name = relative.name.casefold()
    suffix = relative.suffix.casefold()
    if suffix == ".pyc" or "__pycache__" in parts:
        return EXCLUDED_BYTECODE
    if suffix == ".lock" or name.endswith(".lock"):
        return EXCLUDED_LOCK
    if suffix == ".py":
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RealityMigrationError(f"research source is not UTF-8: {relative_path}") from exc
        return SIMULATION_SOURCE if _RNG_RE.search(source) else RESEARCH_SOURCE
    if suffix == ".bin" and "raw" in parts:
        return RAW_LIVE_REALITY
    if suffix == ".json" and (
        name == "current.json" or any(part in {"captures", "events", "manifests"} for part in parts)
    ):
        return DURABLE_METADATA
    return DERIVED_RESEARCH


def _line_character_offset(lines: list[str], line_number: int, utf8_column: int) -> int:
    line = lines[line_number - 1]
    prefix = line.encode("utf-8")[:utf8_column].decode("utf-8")
    return sum(len(value) for value in lines[: line_number - 1]) + len(prefix)


def _node_character_range(source: str, node: ast.AST) -> tuple[int, int]:
    if not hasattr(node, "lineno") or node.end_lineno is None or node.end_col_offset is None:
        raise RealityMigrationError("Python AST did not expose source offsets")
    lines = source.splitlines(keepends=True)
    start = _line_character_offset(lines, node.lineno, node.col_offset)
    end = _line_character_offset(lines, node.end_lineno, node.end_col_offset)
    return start, end


def _is_path_file_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 1:
        return False
    function = node.func
    is_path = isinstance(function, ast.Name) and function.id == "Path"
    is_path = is_path or (isinstance(function, ast.Attribute) and function.attr == "Path")
    argument = node.args[0]
    return is_path and isinstance(argument, ast.Name) and argument.id == "__file__"


def _is_path_file_resolve(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve"
        and _is_path_file_call(node.func.value)
    )


def _is_implicit_repo_root(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == 3
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and _is_path_file_resolve(node.value.value)
    )


def _repository_root_replacements(source: str) -> list[tuple[int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RealityMigrationError(f"research source cannot be parsed: {exc}") from exc
    # The old ``parents[3]`` resolved to the current lineage clone, not to the
    # shared clean-room baseline.  Preserve that isolation after relocating the
    # source module out of the clone.
    replacement = 'Path(__import__("os").environ["XINAO_WORLD_WORKSPACE"]).resolve()'
    replacements = [
        (*_node_character_range(source, node), replacement)
        for node in ast.walk(tree)
        if _is_implicit_repo_root(node)
    ]
    return sorted(replacements, reverse=True)


def _contains_implicit_repo_root(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RealityMigrationError(f"transformed research source cannot be parsed: {exc}") from exc
    return any(_is_implicit_repo_root(node) for node in ast.walk(tree))


def _namespace_import_replacements(source: str) -> list[tuple[int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RealityMigrationError(f"research source cannot be parsed: {exc}") from exc
    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0:
            continue
        normalized_module = re.sub(r"\s+", "", node.module or "")
        if normalized_module != "xinao.reality":
            continue
        live_aliases = [alias for alias in node.names if alias.name == "live"]
        if not live_aliases:
            continue
        if len(node.names) != 1:
            raise RealityMigrationError(
                "mixed 'from xinao.reality import live, ...' cannot be isolated safely"
            )
        alias = live_aliases[0]
        replacement = f"import {LEGACY_PACKAGE} as {alias.asname or 'live'}"
        start, end = _node_character_range(source, node)
        replacements.append((start, end, replacement))
    return sorted(replacements, reverse=True)


def _assert_no_legacy_namespace_semantics(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RealityMigrationError(f"transformed research source cannot be parsed: {exc}") from exc
    reality_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "xinao.reality":
            if any(alias.name == "live" for alias in node.names):
                raise RealityMigrationError("legacy namespace import survived source transformation")
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "xinao":
            for alias in node.names:
                if alias.name == "reality":
                    reality_aliases.add(alias.asname or "reality")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "xinao.reality":
                    if alias.asname is None:
                        raise RealityMigrationError(
                            "unaliased import xinao.reality cannot be isolated safely"
                        )
                    reality_aliases.add(alias.asname or "xinao")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "live"
            and isinstance(node.value, ast.Name)
            and node.value.id in reality_aliases
        ):
            raise RealityMigrationError(
                "dynamic alias access to xinao.reality.live cannot be isolated safely"
            )


def _apply_replacements(source: str, replacements: Iterable[tuple[int, int, str]]) -> str:
    for start, end, replacement in replacements:
        source = source[:start] + replacement + source[end:]
    return source


def _store_assignment_replacements(source: str) -> list[tuple[int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RealityMigrationError(f"research source cannot be parsed: {exc}") from exc
    replacements: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        target_names: set[str] = set()
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            value = node.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = node.value
            target_names.add(node.target.id)
        if value is None or not target_names.intersection({"HOLDOUT_STORE", "STORE"}):
            continue
        constants = [
            candidate.value
            for candidate in ast.walk(value)
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str)
        ]
        store_names = [candidate for candidate in constants if candidate.startswith("pre203_")]
        if not store_names or (
            not any(_is_path_file_resolve(candidate) for candidate in ast.walk(value))
            and not any(
                isinstance(candidate, ast.Constant)
                and isinstance(candidate.value, str)
                and ("xinao" in candidate.value or "reality" in candidate.value)
                for candidate in ast.walk(value)
            )
        ):
            continue
        start, end = _node_character_range(source, value)
        store_name = store_names[-1]
        replacement = (
            'Path(__import__("os").environ["XINAO_LIVE_REALITY_ROOT"]).resolve()'
            f" / {store_name!r}"
        )
        replacements.append((start, end, replacement))
    return sorted(replacements, reverse=True)


def transform_research_source(raw: bytes) -> bytes:
    """Apply the narrow compatibility rewrite used by base and overlay bundles."""

    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RealityMigrationError("research source is not UTF-8") from exc
    source = _apply_replacements(source, _store_assignment_replacements(source))
    source = _apply_replacements(source, _repository_root_replacements(source))
    source = _apply_replacements(source, _namespace_import_replacements(source))
    source = _OLD_NAMESPACE_RE.sub(LEGACY_PACKAGE, source)
    if _OLD_NAMESPACE_RE.search(source):
        raise RealityMigrationError("legacy dotted namespace survived source transformation")
    if _contains_implicit_repo_root(source):
        raise RealityMigrationError("implicit parents[3] repository root survived transformation")
    _assert_no_legacy_namespace_semantics(source)
    return source.encode("utf-8")


def _extend_package_init(payload: bytes) -> bytes:
    if (
        _NAMESPACE_INIT_MARKER in payload
        and b"__path__ = _xinao_extend_path(__path__, __name__)" in payload
    ):
        return payload
    separator = b"" if payload.endswith(b"\n") else b"\n"
    return payload + separator + _NAMESPACE_INIT_SUFFIX


def _payload_for(
    classification: str, raw: bytes, *, relative_path: str | None = None
) -> bytes | None:
    if classification in _EXCLUDED:
        return None
    if classification in _SOURCE_CLASSES:
        payload = transform_research_source(raw)
        if relative_path is not None and Path(relative_path).name.casefold() == "__init__.py":
            payload = _extend_package_init(payload)
        return payload
    return raw


def _inventory_live_root(live_root: Path, *, required: bool) -> dict[str, Any]:
    if not live_root.exists():
        if required:
            raise RealityMigrationError(f"canonical live tree does not exist: {live_root}")
        empty_hash = _hash_records([])
        return {
            "schema": INVENTORY_SCHEMA,
            "exists": False,
            "live_root": str(live_root.resolve(strict=False)),
            "entries": [],
            "counts": {},
            "source_bytes": 0,
            "payload_bytes": 0,
            "source_tree_sha256": empty_hash,
            "payload_tree_sha256": empty_hash,
        }
    live_root = _resolve_existing_directory(live_root, label="live root")
    entries: list[dict[str, Any]] = []
    casefolded: dict[str, str] = {}
    counts: dict[str, int] = {}
    for path in _iter_regular_files(live_root):
        relative = path.relative_to(live_root).as_posix()
        folded = relative.casefold()
        if folded in casefolded:
            raise RealityMigrationError(
                f"case-insensitive live path collision: {casefolded[folded]} and {relative}"
            )
        casefolded[folded] = relative
        raw = _read_stable(path)
        classification = _classification(relative, raw)
        payload = _payload_for(classification, raw, relative_path=relative)
        entry = {
            "relative_path": relative,
            "classification": classification,
            "source_bytes": len(raw),
            "source_sha256": _sha256(raw),
            "payload_bytes": len(payload) if payload is not None else None,
            "payload_sha256": _sha256(payload) if payload is not None else None,
            "transformed": payload is not None and payload != raw,
        }
        entries.append(entry)
        counts[classification] = counts.get(classification, 0) + 1
    entries.sort(key=lambda item: item["relative_path"].casefold())
    source_records = [
        {
            "relative_path": item["relative_path"],
            "classification": item["classification"],
            "bytes": item["source_bytes"],
            "sha256": item["source_sha256"],
        }
        for item in entries
    ]
    payload_records = [
        {
            "relative_path": item["relative_path"],
            "classification": item["classification"],
            "bytes": item["payload_bytes"],
            "sha256": item["payload_sha256"],
        }
        for item in entries
        if item["classification"] not in _EXCLUDED
    ]
    return {
        "schema": INVENTORY_SCHEMA,
        "exists": True,
        "live_root": str(live_root),
        "entries": entries,
        "counts": dict(sorted(counts.items())),
        "source_bytes": sum(item["source_bytes"] for item in entries),
        "payload_bytes": sum(item["payload_bytes"] or 0 for item in entries),
        "source_tree_sha256": _hash_records(source_records),
        "payload_tree_sha256": _hash_records(payload_records),
    }


def inventory_live_reality(canonical_repo: Path) -> dict[str, Any]:
    """Return a deterministic, exhaustive inventory of the canonical mixed tree."""

    repo = _resolve_existing_directory(canonical_repo, label="canonical repository")
    inventory = _inventory_live_root(repo / LIVE_RELATIVE, required=True)
    return {**inventory, "canonical_repo": str(repo)}


def _read_expected_source(live_root: Path, entry: Mapping[str, Any]) -> bytes:
    source = live_root / str(entry["relative_path"])
    if not source.exists() or _is_reparse(source):
        raise SourceTreeChangedError(f"source file disappeared or became a reparse point: {source}")
    raw = _read_stable(source)
    if len(raw) != entry["source_bytes"] or _sha256(raw) != entry["source_sha256"]:
        raise SourceTreeChangedError(f"source bytes changed after inventory: {source}")
    return raw


def _write_once(path: Path, raw: bytes) -> str:
    if path.exists():
        if not path.is_file() or _is_reparse(path):
            raise DestinationConflictError(f"destination is not a regular file: {path}")
        existing = path.read_bytes()
        if existing != raw:
            raise DestinationConflictError(f"destination bytes conflict with payload: {path}")
        return "verified_existing"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _assert_no_reparse_chain(path.parent, label="destination")
    except RealityMigrationError as exc:
        raise DestinationConflictError(str(exc)) from exc
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != raw:
                raise DestinationConflictError(f"destination raced with different bytes: {path}")
            return "verified_existing_after_race"
        return "created"
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_once(path: Path, value: object) -> tuple[str, str]:
    raw = _canonical_json_bytes(value)
    disposition = _write_once(path, raw)
    return _sha256(raw), disposition


def _copy_record(
    *,
    surface: str,
    live_root: Path,
    entry: Mapping[str, Any],
    destination: Path,
    payload_relative_path: str,
) -> dict[str, Any]:
    source_raw = _read_expected_source(live_root, entry)
    payload = _payload_for(
        str(entry["classification"]),
        source_raw,
        relative_path=str(entry["relative_path"]),
    )
    if payload is None:
        raise RealityMigrationError(f"excluded entry reached copy surface: {entry['relative_path']}")
    if len(payload) != entry["payload_bytes"] or _sha256(payload) != entry["payload_sha256"]:
        raise SourceTreeChangedError(f"transformed payload changed: {entry['relative_path']}")
    _write_once(destination, payload)
    return {
        "surface": surface,
        "classification": entry["classification"],
        "source_path": str(live_root / str(entry["relative_path"])),
        "source_relative_path": entry["relative_path"],
        "source_bytes": entry["source_bytes"],
        "source_sha256": entry["source_sha256"],
        "destination_path": str(destination),
        "payload_relative_path": payload_relative_path,
        "payload_bytes": len(payload),
        "payload_sha256": _sha256(payload),
        "transformed": payload != source_raw,
        "copy_verified": True,
    }


def _logical_base_path(entry: Mapping[str, Any]) -> str:
    relative = str(entry["relative_path"])
    if entry["classification"] in _SOURCE_CLASSES:
        return (Path("code") / LEGACY_PACKAGE / Path(relative)).as_posix()
    return (Path("derived") / Path(relative)).as_posix()


def _is_root_package_init(entry: Mapping[str, Any]) -> bool:
    return (
        entry["classification"] in _SOURCE_CLASSES
        and str(entry["relative_path"]).casefold() == "__init__.py"
    )


def _base_payload_records(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = [
        {
            "relative_path": _logical_base_path(entry),
            "classification": entry["classification"],
            "bytes": entry["payload_bytes"],
            "sha256": entry["payload_sha256"],
        }
        for entry in inventory["entries"]
        if entry["classification"] in _SOURCE_CLASSES | {DERIVED_RESEARCH}
    ]
    has_source = any(entry["classification"] in _SOURCE_CLASSES for entry in inventory["entries"])
    has_root_init = any(_is_root_package_init(entry) for entry in inventory["entries"])
    if has_source and not has_root_init:
        records.append(
            {
                "relative_path": f"code/{LEGACY_PACKAGE}/__init__.py",
                "classification": "generated_package_init",
                "bytes": len(_PACKAGE_INIT),
                "sha256": _sha256(_PACKAGE_INIT),
            }
        )
    return sorted(records, key=lambda item: item["relative_path"].casefold())


def _effective_code_payload_records(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "relative_path": _logical_base_path(entry),
                "classification": entry["classification"],
                "bytes": entry["payload_bytes"],
                "sha256": entry["payload_sha256"],
            }
            for entry in inventory["entries"]
            if entry["classification"] in _SOURCE_CLASSES | {DERIVED_RESEARCH}
        ],
        key=lambda item: str(item["relative_path"]).casefold(),
    )


def _overlay_delta(
    canonical: Mapping[str, Any], workspace: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    canonical_by_path = {
        str(entry["relative_path"]).casefold(): entry for entry in canonical["entries"]
    }
    delta: list[dict[str, Any]] = []
    unchanged = 0
    for entry in workspace["entries"]:
        if entry["classification"] in _EXCLUDED:
            continue
        base = canonical_by_path.get(str(entry["relative_path"]).casefold())
        if base is not None and (
            base["source_sha256"] == entry["source_sha256"]
            and base["classification"] == entry["classification"]
        ):
            unchanged += 1
            continue
        delta.append(entry)
    return delta, unchanged


def _logical_overlay_path(entry: Mapping[str, Any]) -> str:
    relative = str(entry["relative_path"])
    if entry["classification"] in _SOURCE_CLASSES:
        return (Path("code") / LEGACY_PACKAGE / Path(relative)).as_posix()
    return (Path("files") / Path(relative)).as_posix()


def _overlay_payload_records(
    delta: Iterable[Mapping[str, Any]],
    *,
    generated_init_paths: Iterable[str],
) -> list[dict[str, Any]]:
    records = [
        {
            "relative_path": _logical_overlay_path(entry),
            "classification": entry["classification"],
            "bytes": entry["payload_bytes"],
            "sha256": entry["payload_sha256"],
        }
        for entry in delta
    ]
    for init_path in generated_init_paths:
        records.append(
            {
                "relative_path": init_path,
                "classification": "generated_package_init",
                "bytes": len(_PACKAGE_INIT),
                "sha256": _sha256(_PACKAGE_INIT),
            }
        )
    return sorted(records, key=lambda item: item["relative_path"].casefold())


def _generated_overlay_init_paths(
    compute_delta: Iterable[Mapping[str, Any]],
) -> list[str]:
    delta = list(compute_delta)
    source_paths = {
        str(entry["relative_path"]).casefold()
        for entry in delta
        if entry["classification"] in _SOURCE_CLASSES
    }
    package_directories: set[str] = set()
    for entry in delta:
        if entry["classification"] not in _SOURCE_CLASSES:
            continue
        parent = Path(str(entry["relative_path"])).parent
        while parent != Path("."):
            package_directories.add(parent.as_posix())
            parent = parent.parent
    paths = ["__init__.py", *(f"{directory}/__init__.py" for directory in package_directories)]
    return sorted(
        [
            (Path("code") / LEGACY_PACKAGE / Path(path)).as_posix()
            for path in paths
            if path.casefold() not in source_paths
        ],
        key=str.casefold,
    )


def _workspace_live_payload_records(
    delta: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "relative_path": str(entry["relative_path"]),
                "classification": entry["classification"],
                "bytes": entry["payload_bytes"],
                "sha256": entry["payload_sha256"],
            }
            for entry in delta
        ],
        key=lambda item: item["relative_path"].casefold(),
    )


def _safe_workspace_mapping(workspace_roots: Mapping[str, Path] | None) -> dict[str, Path]:
    normalized: dict[str, Path] = {}
    folded: set[str] = set()
    for raw_key, raw_root in (workspace_roots or {}).items():
        key = str(raw_key)
        if not _WORKSPACE_KEY_RE.fullmatch(key):
            raise RealityMigrationError(f"unsafe workspace key: {key!r}")
        if key.casefold() in folded:
            raise RealityMigrationError(f"case-insensitive duplicate workspace key: {key!r}")
        folded.add(key.casefold())
        root = _resolve_existing_directory(Path(raw_root), label=f"workspace {key}")
        if root.name != key:
            raise RealityMigrationError(
                "workspace key must equal its exact lineage_id directory leaf: "
                f"key={key!r}; workspace={root}"
            )
        normalized[key] = root
    return dict(sorted(normalized.items(), key=lambda item: item[0].casefold()))


def _inventory_identity(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "exists": inventory["exists"],
        "source_tree_sha256": inventory["source_tree_sha256"],
        "payload_tree_sha256": inventory["payload_tree_sha256"],
        "counts": inventory["counts"],
        "source_bytes": inventory["source_bytes"],
        "payload_bytes": inventory["payload_bytes"],
    }


def _deletion_records(
    canonical: Mapping[str, Any], workspace: Mapping[str, Any]
) -> list[dict[str, Any]]:
    workspace_paths = {
        str(entry["relative_path"]).casefold() for entry in workspace["entries"]
    }
    records = [
        {
            "relative_path": entry["relative_path"],
            "classification": entry["classification"],
            "base_source_bytes": entry["source_bytes"],
            "base_source_sha256": entry["source_sha256"],
            "base_payload_sha256": entry["payload_sha256"],
        }
        for entry in canonical["entries"]
        if entry["classification"] not in _EXCLUDED
        and str(entry["relative_path"]).casefold() not in workspace_paths
    ]
    return sorted(records, key=lambda item: str(item["relative_path"]).casefold())


def _effective_live_records(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "relative_path": str(entry["relative_path"]),
                "classification": entry["classification"],
                "bytes": entry["payload_bytes"],
                "sha256": entry["payload_sha256"],
            }
            for entry in inventory["entries"]
            if entry["classification"] in _LIVE_CLASSES
        ],
        key=lambda item: str(item["relative_path"]).casefold(),
    )


def _verify_exact_payload_tree(
    root: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    label: str,
    create: bool = False,
) -> None:
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise RealityMigrationError(f"{label} root is missing: {root}")
    _assert_no_reparse_chain(root, label=label)
    expected = {str(record["relative_path"]).casefold(): dict(record) for record in records}
    observed_paths = _iter_regular_files(root)
    observed: dict[str, Path] = {}
    for path in observed_paths:
        relative = path.relative_to(root).as_posix()
        folded = relative.casefold()
        if folded in observed:
            raise RealityMigrationError(f"{label} has a case-insensitive path collision: {relative}")
        observed[folded] = path
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise RealityMigrationError(
            f"{label} is not exhaustive: missing={missing[:5]}; extra={extra[:5]}"
        )
    for folded, record in expected.items():
        raw = _read_stable(observed[folded])
        if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
            raise RealityMigrationError(
                f"{label} payload mismatch: {record['relative_path']}"
            )


def _private_live_identity(
    *, workspace_key: str, workspace_root: Path, live_seed_payload_tree_sha256: str
) -> dict[str, Any]:
    return {
        "schema": PRIVATE_LIVE_MARKER_SCHEMA,
        "lineage_id": workspace_key,
        "workspace_key": workspace_key,
        "workspace_root": str(workspace_root),
        "live_seed_payload_tree_sha256": live_seed_payload_tree_sha256,
        "initialization_mode": "initialize_once_then_preserve_mutable_state",
    }


def _runtime_binding_inputs(
    *,
    lineage_id: str,
    workspace_root: Path,
    base_manifest_path: Path,
    base_manifest_sha256: str,
    effective_code_root: Path,
    effective_code_payload_tree_sha256: str,
    effective_code_manifest_path: Path,
    effective_code_manifest_sha256: str,
    private_live_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only immutable migration-owned inputs for the per-attempt binding."""

    return {
        "schema": RUNTIME_BINDING_INPUTS_SCHEMA,
        "lineage_id": lineage_id,
        "workspace": str(workspace_root),
        "base_manifest_path": str(base_manifest_path),
        "base_manifest_sha256": base_manifest_sha256,
        "effective_code_root": str(effective_code_root),
        "effective_python_path": str(effective_code_root / "code"),
        "effective_code_manifest_path": str(effective_code_manifest_path),
        "effective_code_manifest_sha256": effective_code_manifest_sha256,
        "effective_code_tree_sha256": effective_code_payload_tree_sha256,
        "private_live_root": str(private_live_contract["root"]),
        "live_seed_receipt_path": str(private_live_contract["receipt_path"]),
        "live_seed_receipt_sha256": str(private_live_contract["receipt_sha256"]),
    }


def _validate_private_live(
    private_root: Path,
    receipt_path: Path,
    marker_value: Mapping[str, Any],
) -> str:
    marker_raw = _canonical_json_bytes(dict(marker_value))
    if not private_root.exists():
        if receipt_path.exists():
            raise RealityMigrationError(
                f"private live receipt exists without state root: {receipt_path}"
            )
        return "absent"
    if not private_root.is_dir() or _is_reparse(private_root):
        raise RealityMigrationError(f"private live root is not a regular directory: {private_root}")
    _assert_no_reparse_chain(private_root, label="private live root")
    marker_path = private_root / _PRIVATE_LIVE_MARKER_NAME
    if not marker_path.is_file() or _is_reparse(marker_path):
        raise RealityMigrationError(f"private live initialization marker is missing: {marker_path}")
    if _read_stable(marker_path) != marker_raw:
        raise RealityMigrationError(f"private live initialization identity mismatch: {marker_path}")
    if receipt_path.exists():
        expected_receipt = {
            "schema": PRIVATE_LIVE_RECEIPT_SCHEMA,
            "private_live_root": str(private_root),
            "marker_path": str(marker_path),
            "marker_sha256": _sha256(marker_raw),
            "origin": dict(marker_value),
        }
        if _read_stable(receipt_path) != _canonical_json_bytes(expected_receipt):
            raise RealityMigrationError(f"private live materialization receipt mismatch: {receipt_path}")
    return "preserved_existing_mutable_state"


def _initialize_private_live(
    *,
    private_root: Path,
    receipt_path: Path,
    seed_root: Path,
    seed_records: list[dict[str, Any]],
    marker_value: Mapping[str, Any],
) -> dict[str, Any]:
    disposition = _validate_private_live(private_root, receipt_path, marker_value)
    marker_raw = _canonical_json_bytes(dict(marker_value))
    marker_path = private_root / _PRIVATE_LIVE_MARKER_NAME
    if disposition == "absent":
        private_root.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_reparse_chain(private_root.parent, label="private live parent")
        staging = private_root.parent / (
            f".{private_root.name}.{os.getpid()}.{uuid.uuid4().hex}.staging"
        )
        staging.mkdir()
        try:
            for record in seed_records:
                source = seed_root / str(record["relative_path"])
                raw = _read_stable(source)
                if len(raw) != record["bytes"] or _sha256(raw) != record["sha256"]:
                    raise RealityMigrationError(f"effective live seed changed: {source}")
                _write_once(staging / str(record["relative_path"]), raw)
            _verify_exact_payload_tree(staging, seed_records, label="private live staging")
            _write_once(staging / _PRIVATE_LIVE_MARKER_NAME, marker_raw)
            try:
                os.rename(staging, private_root)
                disposition = "initialized_from_effective_seed"
            except OSError:
                if not private_root.exists():
                    raise
                disposition = _validate_private_live(private_root, receipt_path, marker_value)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    receipt = {
        "schema": PRIVATE_LIVE_RECEIPT_SCHEMA,
        "private_live_root": str(private_root),
        "marker_path": str(marker_path),
        "marker_sha256": _sha256(marker_raw),
        "origin": dict(marker_value),
    }
    receipt_sha256, _ = _write_json_once(receipt_path, receipt)
    _write_once(
        receipt_path.with_suffix(".sha256"),
        f"{receipt_sha256}  {receipt_path.name}\n".encode("ascii"),
    )
    _validate_private_live(private_root, receipt_path, marker_value)
    return {
        "root": str(private_root),
        "marker_path": str(marker_path),
        "marker_sha256": _sha256(marker_raw),
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
        "disposition": disposition,
    }


def migrate_live_reality_copy_first(
    canonical_repo: Path,
    *,
    live_reality_root: Path,
    world_compute_root: Path,
    workspace_roots: Mapping[str, Path] | None = None,
    active_child_pids: Mapping[str, int | None] | Iterable[int | None] = (),
    expected_source_tree_sha256: str | None = None,
) -> dict[str, Any]:
    """Copy and verify a mixed live tree without ever deleting its source.

    Each ``workspace_roots`` key is the exact lineage id and must equal its
    lineage-clone directory leaf. Each value is a complete clone snapshot:
    absence is a deletion, not sparse inheritance. ``live_reality_root`` and
    ``world_compute_root`` are explicit provenance/receipt roots; mutable live
    state is initialized at ``<workspace>/.xinao-world-runtime/live-reality`` and
    never reuses ``xinao/reality/live``. The caller-provided PID view is treated
    as authoritative: any positive PID rejects the migration before a target is
    created.
    """

    assert_no_active_child_pids(active_child_pids)
    repo = _resolve_existing_directory(canonical_repo, label="canonical repository")
    canonical_live = _resolve_existing_directory(
        repo / LIVE_RELATIVE, label="canonical live root"
    )
    workspaces = _safe_workspace_mapping(workspace_roots)
    live_target = _resolve_destination(live_reality_root, label="live reality destination")
    compute_target = _resolve_destination(world_compute_root, label="world compute destination")
    source_roots = [repo, *workspaces.values()]
    _assert_disjoint(source_roots, [live_target, compute_target])

    canonical_inventory = _inventory_live_root(canonical_live, required=True)
    if expected_source_tree_sha256 is not None:
        expected = expected_source_tree_sha256.casefold()
        if not _SHA256_RE.fullmatch(expected):
            raise RealityMigrationError("expected_source_tree_sha256 is not a SHA-256 digest")
        if canonical_inventory["source_tree_sha256"] != expected:
            raise RealityMigrationError(
                "CANONICAL_SOURCE_TREE_MISMATCH: "
                f"expected={expected}; observed={canonical_inventory['source_tree_sha256']}"
            )
    workspace_inventories = {
        key: _inventory_live_root(root / LIVE_RELATIVE, required=False)
        for key, root in workspaces.items()
    }

    base_records = _base_payload_records(canonical_inventory)
    base_payload_tree_sha256 = _hash_records(base_records)
    base_root = compute_target / "legacy-unattributed" / base_payload_tree_sha256 / "base"
    canonical_live_records = _effective_live_records(canonical_inventory)
    canonical_live_payload_tree_sha256 = _hash_records(canonical_live_records)
    canonical_live_seed_root = (
        live_target / "canonical-base" / canonical_live_payload_tree_sha256 / "seed"
    )

    plans: dict[str, dict[str, Any]] = {}
    for key, workspace_root in workspaces.items():
        inventory = workspace_inventories[key]
        delta, unchanged = _overlay_delta(canonical_inventory, inventory)
        compute_delta = [
            entry
            for entry in delta
            if entry["classification"] in _SOURCE_CLASSES | {DERIVED_RESEARCH}
        ]
        live_delta = [entry for entry in delta if entry["classification"] in _LIVE_CLASSES]
        if len(compute_delta) + len(live_delta) != len(delta):
            raise RealityMigrationError(f"workspace delta has no destination surface: {key}")
        generated_init_paths = _generated_overlay_init_paths(compute_delta)
        overlay_records = _overlay_payload_records(
            compute_delta, generated_init_paths=generated_init_paths
        )
        live_delta_records = _workspace_live_payload_records(live_delta)
        overlay_payload_tree_sha256 = _hash_records(overlay_records)
        live_delta_payload_tree_sha256 = _hash_records(live_delta_records)
        deletions = _deletion_records(canonical_inventory, inventory)
        deletion_tree_sha256 = _hash_records(deletions)
        effective_code_records = _effective_code_payload_records(inventory)
        effective_code_payload_tree_sha256 = _hash_records(effective_code_records)
        effective_live_records = _effective_live_records(inventory)
        if any(
            str(record["relative_path"]).casefold() == _PRIVATE_LIVE_MARKER_NAME.casefold()
            for record in effective_live_records
        ):
            raise RealityMigrationError(
                f"workspace uses reserved private-live marker path: {key}"
            )
        effective_live_payload_tree_sha256 = _hash_records(effective_live_records)
        private_live_root = workspace_root / PRIVATE_LIVE_RELATIVE
        private_live_receipt_path = (
            compute_target
            / "private-live-initialization"
            / key
            / "INITIALIZATION_RECEIPT.json"
        )
        private_marker_value = _private_live_identity(
            workspace_key=key,
            workspace_root=workspace_root,
            live_seed_payload_tree_sha256=effective_live_payload_tree_sha256,
        )
        binding_identity = {
            "schema": RUNTIME_BINDING_INPUTS_SCHEMA,
            "lineage_id": key,
            "workspace": str(workspace_root),
            "base_manifest_path": str(base_root / "BASE_MANIFEST.json"),
            "effective_code_payload_tree_sha256": effective_code_payload_tree_sha256,
            "private_live_root": str(private_live_root),
            "live_seed_receipt_path": str(private_live_receipt_path),
            "live_seed_payload_tree_sha256": effective_live_payload_tree_sha256,
        }
        effective_view_id = _hash_records(
            [
                {
                    "workspace_key": key,
                    "workspace_root": str(workspace_root),
                    "workspace_mode": "complete_clone",
                    "workspace_source_exists": inventory["exists"],
                    "workspace_source_tree_sha256": inventory["source_tree_sha256"],
                    "base_payload_tree_sha256": base_payload_tree_sha256,
                    "deletion_tree_sha256": deletion_tree_sha256,
                    "effective_code_payload_tree_sha256": effective_code_payload_tree_sha256,
                    "effective_live_payload_tree_sha256": effective_live_payload_tree_sha256,
                    "runtime_binding_inputs_identity": binding_identity,
                }
            ]
        )
        overlay_identity = _hash_records(
            [
                {
                    "base_payload_tree_sha256": base_payload_tree_sha256,
                    "source_exists": inventory["exists"],
                    "workspace_source_tree_sha256": inventory["source_tree_sha256"],
                    "overlay_payload_tree_sha256": overlay_payload_tree_sha256,
                    "live_delta_payload_tree_sha256": live_delta_payload_tree_sha256,
                    "deletion_tree_sha256": deletion_tree_sha256,
                    "effective_view_id": effective_view_id,
                }
            ]
        )
        effective_code_root = (
            compute_target
            / key
            / "effective-code"
            / effective_code_payload_tree_sha256
            / "view"
        )
        effective_live_seed_root = (
            live_target
            / "effective-seeds"
            / effective_live_payload_tree_sha256
            / "seed"
        )
        _validate_private_live(
            private_live_root,
            private_live_receipt_path,
            private_marker_value,
        )
        plans[key] = {
            "workspace_root": workspace_root,
            "inventory": inventory,
            "delta": delta,
            "unchanged": unchanged,
            "compute_delta": compute_delta,
            "live_delta": live_delta,
            "generated_init_paths": generated_init_paths,
            "overlay_records": overlay_records,
            "live_delta_records": live_delta_records,
            "overlay_payload_tree_sha256": overlay_payload_tree_sha256,
            "live_delta_payload_tree_sha256": live_delta_payload_tree_sha256,
            "overlay_id": overlay_identity,
            "deletions": deletions,
            "deletion_tree_sha256": deletion_tree_sha256,
            "effective_code_records": effective_code_records,
            "effective_code_payload_tree_sha256": effective_code_payload_tree_sha256,
            "effective_code_root": effective_code_root,
            "effective_live_records": effective_live_records,
            "effective_live_payload_tree_sha256": effective_live_payload_tree_sha256,
            "effective_live_seed_root": effective_live_seed_root,
            "effective_view_id": effective_view_id,
            "private_live_root": private_live_root,
            "private_live_receipt_path": private_live_receipt_path,
            "private_marker_value": private_marker_value,
        }

    copies: list[dict[str, Any]] = []
    live_entries = [
        entry for entry in canonical_inventory["entries"] if entry["classification"] in _LIVE_CLASSES
    ]
    for entry in live_entries:
        relative = str(entry["relative_path"])
        copies.append(
            _copy_record(
                surface="canonical_live_reality_provenance",
                live_root=canonical_live,
                entry=entry,
                destination=canonical_live_seed_root / Path(relative),
                payload_relative_path=relative,
            )
        )
    _verify_exact_payload_tree(
        canonical_live_seed_root,
        canonical_live_records,
        label="canonical live provenance seed",
        create=True,
    )
    canonical_live_manifest = {
        "schema": EFFECTIVE_LIVE_SEED_SCHEMA,
        "kind": "canonical_live_provenance_only",
        "runtime_bindable": False,
        "payload_tree_sha256": canonical_live_payload_tree_sha256,
        "entries": canonical_live_records,
    }
    canonical_live_manifest_path = canonical_live_seed_root.parent / "LIVE_MANIFEST.json"
    canonical_live_manifest_sha256, _ = _write_json_once(
        canonical_live_manifest_path, canonical_live_manifest
    )
    _write_once(
        canonical_live_manifest_path.with_suffix(".sha256"),
        f"{canonical_live_manifest_sha256}  {canonical_live_manifest_path.name}\n".encode(
            "ascii"
        ),
    )

    base_entries = [
        entry
        for entry in canonical_inventory["entries"]
        if entry["classification"] in _SOURCE_CLASSES | {DERIVED_RESEARCH}
    ]
    for entry in base_entries:
        logical = _logical_base_path(entry)
        copies.append(
            _copy_record(
                surface="legacy_unattributed_base",
                live_root=canonical_live,
                entry=entry,
                destination=base_root / Path(logical),
                payload_relative_path=logical,
            )
        )
    if any(entry["classification"] in _SOURCE_CLASSES for entry in base_entries) and not any(
        _is_root_package_init(entry) for entry in base_entries
    ):
        init_logical = f"code/{LEGACY_PACKAGE}/__init__.py"
        init_path = base_root / Path(init_logical)
        _write_once(init_path, _PACKAGE_INIT)
        copies.append(
            {
                "surface": "legacy_unattributed_base",
                "classification": "generated_package_init",
                "source_path": None,
                "source_relative_path": None,
                "source_bytes": None,
                "source_sha256": None,
                "destination_path": str(init_path),
                "payload_relative_path": init_logical,
                "payload_bytes": len(_PACKAGE_INIT),
                "payload_sha256": _sha256(_PACKAGE_INIT),
                "transformed": True,
                "copy_verified": True,
            }
        )
    base_manifest = {
        "schema": BASE_BUNDLE_SCHEMA,
        "bundle_id": base_payload_tree_sha256,
        "legacy_namespace": LEGACY_PACKAGE,
        "payload_tree_sha256": base_payload_tree_sha256,
        "entries": base_records,
        "runtime_bindable": False,
        "runtime_environment": {
            "world_workspace": "XINAO_WORLD_WORKSPACE",
            "live_reality_root": "XINAO_LIVE_REALITY_ROOT",
        },
    }
    base_manifest_path = base_root / "BASE_MANIFEST.json"
    base_manifest_sha256, _ = _write_json_once(base_manifest_path, base_manifest)
    _write_once(
        base_root / "BASE_MANIFEST.sha256",
        f"{base_manifest_sha256}  BASE_MANIFEST.json\n".encode("ascii"),
    )

    overlays: list[dict[str, Any]] = []
    private_live_dispositions: dict[str, str] = {}
    for key, plan in plans.items():
        workspace_root = plan["workspace_root"]
        inventory = plan["inventory"]
        delta = plan["delta"]
        unchanged = plan["unchanged"]
        compute_delta = plan["compute_delta"]
        live_delta = plan["live_delta"]
        generated_init_paths = plan["generated_init_paths"]
        overlay_records = plan["overlay_records"]
        live_delta_records = plan["live_delta_records"]
        overlay_payload_tree_sha256 = plan["overlay_payload_tree_sha256"]
        live_delta_payload_tree_sha256 = plan["live_delta_payload_tree_sha256"]
        overlay_identity = plan["overlay_id"]
        overlay_root = (
            compute_target
            / key
            / "legacy-unattributed-overlays"
            / base_payload_tree_sha256
            / overlay_identity
        )
        workspace_live_root = (
            live_target / "provenance-workspace-deltas" / key / overlay_identity
        )
        overlay_copy_count = 0
        live_delta_copy_count = 0
        if inventory["exists"]:
            workspace_live = Path(str(inventory["live_root"]))
            for entry in compute_delta:
                logical = _logical_overlay_path(entry)
                copies.append(
                    _copy_record(
                        surface=f"workspace_overlay:{key}",
                        live_root=workspace_live,
                        entry=entry,
                        destination=overlay_root / Path(logical),
                        payload_relative_path=logical,
                    )
                )
                overlay_copy_count += 1
            for entry in live_delta:
                relative = str(entry["relative_path"])
                copies.append(
                    _copy_record(
                        surface=f"workspace_live_reality:{key}",
                        live_root=workspace_live,
                        entry=entry,
                        destination=workspace_live_root / Path(relative),
                        payload_relative_path=relative,
                    )
                )
                live_delta_copy_count += 1
        for init_logical in generated_init_paths:
            init_path = overlay_root / Path(init_logical)
            _write_once(init_path, _PACKAGE_INIT)
            copies.append(
                {
                    "surface": f"workspace_overlay:{key}",
                    "classification": "generated_package_init",
                    "source_path": None,
                    "source_relative_path": None,
                    "source_bytes": None,
                    "source_sha256": None,
                    "destination_path": str(init_path),
                    "payload_relative_path": init_logical,
                    "payload_bytes": len(_PACKAGE_INIT),
                    "payload_sha256": _sha256(_PACKAGE_INIT),
                    "transformed": True,
                    "copy_verified": True,
                }
            )
        overlay_manifest = {
            "schema": OVERLAY_SCHEMA,
            "runtime_bindable": False,
            "lineage_id": key,
            "workspace_key": key,
            "base_payload_tree_sha256": base_payload_tree_sha256,
            "workspace_source_tree_sha256": inventory["source_tree_sha256"],
            "overlay_id": overlay_identity,
            "overlay_payload_tree_sha256": overlay_payload_tree_sha256,
            "source_exists": inventory["exists"],
            "unchanged_base_entry_count": unchanged,
            "delta_entry_count": len(delta),
            "compute_delta_entry_count": len(compute_delta),
            "deletion_count": len(plan["deletions"]),
            "deletion_tree_sha256": plan["deletion_tree_sha256"],
            "deletions": plan["deletions"],
            "entries": overlay_records,
            "live_reality_delta": {
                "payload_tree_sha256": live_delta_payload_tree_sha256,
                "entry_count": len(live_delta),
                "entries": live_delta_records,
            },
        }
        overlay_manifest_path = overlay_root / "OVERLAY_MANIFEST.json"
        overlay_manifest_sha256, _ = _write_json_once(overlay_manifest_path, overlay_manifest)
        _write_once(
            overlay_root / "OVERLAY_MANIFEST.sha256",
            f"{overlay_manifest_sha256}  OVERLAY_MANIFEST.json\n".encode("ascii"),
        )

        effective_code_root = plan["effective_code_root"]
        effective_code_records = plan["effective_code_records"]
        if inventory["exists"]:
            workspace_live = Path(str(inventory["live_root"]))
            for entry in inventory["entries"]:
                if entry["classification"] not in _SOURCE_CLASSES | {DERIVED_RESEARCH}:
                    continue
                logical = _logical_base_path(entry)
                copies.append(
                    _copy_record(
                        surface=f"lineage_effective_code:{key}",
                        live_root=workspace_live,
                        entry=entry,
                        destination=effective_code_root / Path(logical),
                        payload_relative_path=logical,
                    )
                )
        for record in effective_code_records:
            if record["classification"] == "generated_package_init":
                _write_once(effective_code_root / str(record["relative_path"]), _PACKAGE_INIT)
                copies.append(
                    {
                        "surface": f"lineage_effective_code:{key}",
                        "classification": "generated_package_init",
                        "source_path": None,
                        "source_relative_path": None,
                        "source_bytes": None,
                        "source_sha256": None,
                        "destination_path": str(
                            effective_code_root / str(record["relative_path"])
                        ),
                        "payload_relative_path": record["relative_path"],
                        "payload_bytes": record["bytes"],
                        "payload_sha256": record["sha256"],
                        "transformed": True,
                        "copy_verified": True,
                    }
                )
        _verify_exact_payload_tree(
            effective_code_root,
            effective_code_records,
            label=f"lineage effective code {key}",
            create=True,
        )
        (effective_code_root / "code").mkdir(exist_ok=True)
        effective_code_manifest = {
            "schema": EFFECTIVE_CODE_SCHEMA,
            "payload_tree_sha256": plan["effective_code_payload_tree_sha256"],
            "legacy_namespace": LEGACY_PACKAGE,
            "base_fallback_permitted": False,
            "entries": effective_code_records,
        }
        effective_code_manifest_path = (
            effective_code_root.parent / "EFFECTIVE_CODE_MANIFEST.json"
        )
        effective_code_manifest_sha256, _ = _write_json_once(
            effective_code_manifest_path, effective_code_manifest
        )
        _write_once(
            effective_code_manifest_path.with_suffix(".sha256"),
            f"{effective_code_manifest_sha256}  {effective_code_manifest_path.name}\n".encode(
                "ascii"
            ),
        )

        effective_live_seed_root = plan["effective_live_seed_root"]
        effective_live_records = plan["effective_live_records"]
        if inventory["exists"]:
            workspace_live = Path(str(inventory["live_root"]))
            for entry in inventory["entries"]:
                if entry["classification"] not in _LIVE_CLASSES:
                    continue
                relative = str(entry["relative_path"])
                copies.append(
                    _copy_record(
                        surface=f"lineage_effective_live_seed:{key}",
                        live_root=workspace_live,
                        entry=entry,
                        destination=effective_live_seed_root / Path(relative),
                        payload_relative_path=relative,
                    )
                )
        _verify_exact_payload_tree(
            effective_live_seed_root,
            effective_live_records,
            label=f"lineage effective live seed {key}",
            create=True,
        )
        effective_live_manifest = {
            "schema": EFFECTIVE_LIVE_SEED_SCHEMA,
            "payload_tree_sha256": plan["effective_live_payload_tree_sha256"],
            "entries": effective_live_records,
        }
        effective_live_manifest_path = (
            effective_live_seed_root.parent / "EFFECTIVE_LIVE_SEED_MANIFEST.json"
        )
        effective_live_manifest_sha256, _ = _write_json_once(
            effective_live_manifest_path, effective_live_manifest
        )
        _write_once(
            effective_live_manifest_path.with_suffix(".sha256"),
            f"{effective_live_manifest_sha256}  {effective_live_manifest_path.name}\n".encode(
                "ascii"
            ),
        )

        private_receipt = _initialize_private_live(
            private_root=plan["private_live_root"],
            receipt_path=plan["private_live_receipt_path"],
            seed_root=effective_live_seed_root,
            seed_records=effective_live_records,
            marker_value=plan["private_marker_value"],
        )
        private_live_dispositions[key] = str(private_receipt["disposition"])
        private_live_contract = {
            "root": private_receipt["root"],
            "initialization_mode": "initialize_once_then_preserve_mutable_state",
            "origin": plan["private_marker_value"],
            "marker_path": private_receipt["marker_path"],
            "marker_sha256": private_receipt["marker_sha256"],
            "receipt_path": private_receipt["receipt_path"],
            "receipt_sha256": private_receipt["receipt_sha256"],
        }
        runtime_environment = {
            "XINAO_WORLD_WORKSPACE": str(workspace_root),
            "XINAO_LIVE_REALITY_ROOT": str(plan["private_live_root"]),
            "PYTHONPATH": str(effective_code_root / "code"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        runtime_binding_inputs = _runtime_binding_inputs(
            lineage_id=key,
            workspace_root=workspace_root,
            base_manifest_path=base_manifest_path,
            base_manifest_sha256=base_manifest_sha256,
            effective_code_root=effective_code_root,
            effective_code_payload_tree_sha256=plan[
                "effective_code_payload_tree_sha256"
            ],
            effective_code_manifest_path=effective_code_manifest_path,
            effective_code_manifest_sha256=effective_code_manifest_sha256,
            private_live_contract=private_live_contract,
        )
        effective_view_manifest = {
            "schema": EFFECTIVE_VIEW_SCHEMA,
            "view_id": plan["effective_view_id"],
            "lineage_id": key,
            "workspace_key": key,
            "workspace_root": str(workspace_root),
            "workspace_mode": "complete_clone",
            "workspace_inventory": _inventory_identity(inventory),
            "base_payload_tree_sha256": base_payload_tree_sha256,
            "deletion_tree_sha256": plan["deletion_tree_sha256"],
            "deletions": plan["deletions"],
            "effective_code": {
                "root": str(effective_code_root),
                "effective_python_path": str(effective_code_root / "code"),
                "payload_tree_sha256": plan["effective_code_payload_tree_sha256"],
                "manifest_path": str(effective_code_manifest_path),
                "manifest_sha256": effective_code_manifest_sha256,
                "base_fallback_permitted": False,
            },
            "effective_live_seed": {
                "root": str(effective_live_seed_root),
                "payload_tree_sha256": plan["effective_live_payload_tree_sha256"],
                "manifest_path": str(effective_live_manifest_path),
                "manifest_sha256": effective_live_manifest_sha256,
            },
            "private_effective_live": private_live_contract,
            "runtime_environment": runtime_environment,
            "runtime_binding_inputs": runtime_binding_inputs,
        }
        effective_view_root = (
            compute_target / key / "effective-views" / plan["effective_view_id"]
        )
        effective_view_manifest_path = effective_view_root / "VIEW_MANIFEST.json"
        effective_view_manifest_sha256, _ = _write_json_once(
            effective_view_manifest_path, effective_view_manifest
        )
        _write_once(
            effective_view_manifest_path.with_suffix(".sha256"),
            f"{effective_view_manifest_sha256}  {effective_view_manifest_path.name}\n".encode(
                "ascii"
            ),
        )
        overlays.append(
            {
                "lineage_id": key,
                "workspace_key": key,
                "workspace_root": str(workspace_root),
                "source_live_root": inventory["live_root"],
                "source_inventory": _inventory_identity(inventory),
                "overlay_root": str(overlay_root),
                "overlay_id": overlay_identity,
                "overlay_payload_tree_sha256": overlay_payload_tree_sha256,
                "runtime_view": "lineage_effective_view_only",
                "python_path_order": [str(effective_code_root / "code")],
                "effective_python_path": str(effective_code_root / "code"),
                "effective_code_root": str(effective_code_root),
                "effective_code_payload_tree_sha256": plan[
                    "effective_code_payload_tree_sha256"
                ],
                "effective_code_manifest_path": str(effective_code_manifest_path),
                "effective_code_manifest_sha256": effective_code_manifest_sha256,
                "private_effective_live_root": str(plan["private_live_root"]),
                "effective_live_seed_root": str(effective_live_seed_root),
                "effective_live_seed_payload_tree_sha256": plan[
                    "effective_live_payload_tree_sha256"
                ],
                "effective_live_seed_manifest_path": str(effective_live_manifest_path),
                "effective_live_seed_manifest_sha256": effective_live_manifest_sha256,
                "effective_view_id": plan["effective_view_id"],
                "effective_view_manifest_path": str(effective_view_manifest_path),
                "effective_view_manifest_sha256": effective_view_manifest_sha256,
                "runtime_environment": runtime_environment,
                "runtime_binding_inputs": runtime_binding_inputs,
                "private_live_materialization": private_live_contract,
                "deletion_count": len(plan["deletions"]),
                "deletion_tree_sha256": plan["deletion_tree_sha256"],
                "deletions": plan["deletions"],
                "live_reality_delta_root": str(workspace_live_root),
                "live_reality_delta_payload_tree_sha256": live_delta_payload_tree_sha256,
                "live_reality_delta_entry_count": len(live_delta),
                "live_reality_delta_copied_entry_count": live_delta_copy_count,
                "manifest_path": str(overlay_manifest_path),
                "manifest_sha256": overlay_manifest_sha256,
                "delta_entry_count": len(delta),
                "compute_delta_entry_count": len(compute_delta),
                "copied_entry_count": overlay_copy_count,
                "unchanged_base_entry_count": unchanged,
                "excluded_entries": [
                    entry
                    for entry in inventory["entries"]
                    if entry["classification"] in _EXCLUDED
                ],
            }
        )

    post_canonical = _inventory_live_root(canonical_live, required=True)
    if post_canonical["source_tree_sha256"] != canonical_inventory["source_tree_sha256"]:
        raise SourceTreeChangedError("canonical live tree changed during migration")
    for key, root in workspaces.items():
        observed = _inventory_live_root(root / LIVE_RELATIVE, required=False)
        if (
            observed["exists"] != workspace_inventories[key]["exists"]
            or observed["source_tree_sha256"]
            != workspace_inventories[key]["source_tree_sha256"]
        ):
            raise SourceTreeChangedError(f"workspace live tree changed during migration: {key}")

    migration_identity = _hash_records(
        [
            {
                "canonical_repo": str(repo),
                "canonical_source_tree_sha256": canonical_inventory["source_tree_sha256"],
                "canonical_payload_tree_sha256": canonical_inventory["payload_tree_sha256"],
                "base_payload_tree_sha256": base_payload_tree_sha256,
                "live_reality_root": str(live_target),
                "world_compute_root": str(compute_target),
            },
            *[
                {
                    "workspace_key": overlay["workspace_key"],
                    "workspace_root": overlay["workspace_root"],
                    "workspace_source_tree_sha256": overlay["source_inventory"][
                        "source_tree_sha256"
                    ],
                    "overlay_id": overlay["overlay_id"],
                    "effective_view_id": overlay["effective_view_id"],
                    "deletion_tree_sha256": overlay["deletion_tree_sha256"],
                }
                for overlay in overlays
            ],
        ]
    )
    manifest = {
        "schema": MIGRATION_SCHEMA,
        "migration_id": migration_identity,
        "mode": "copy_first_source_preserving",
        "source_deletion_permitted": False,
        "logical_complete_clone_deletions_preserved": True,
        "lineage_effective_view_required_for_runtime": True,
        "canonical_repo": str(repo),
        "canonical_live_root": str(canonical_live),
        "canonical_inventory": _inventory_identity(canonical_inventory),
        "live_reality_root": str(live_target),
        "live_reality_root_runtime_bindable": False,
        "world_compute_root": str(compute_target),
        "canonical_live_bundle": {
            "root": str(canonical_live_seed_root),
            "manifest_path": str(canonical_live_manifest_path),
            "manifest_sha256": canonical_live_manifest_sha256,
            "payload_tree_sha256": canonical_live_payload_tree_sha256,
            "runtime_bindable": False,
        },
        "base_bundle": {
            "bundle_id": base_payload_tree_sha256,
            "root": str(base_root),
            "python_path": str(base_root / "code"),
            "manifest_path": str(base_manifest_path),
            "manifest_sha256": base_manifest_sha256,
            "payload_tree_sha256": base_payload_tree_sha256,
            "runtime_bindable": False,
        },
        "workspace_overlays": overlays,
        "copies": sorted(
            copies,
            key=lambda item: (str(item["surface"]).casefold(), str(item["destination_path"]).casefold()),
        ),
        "canonical_exclusions": [
            entry
            for entry in canonical_inventory["entries"]
            if entry["classification"] in _EXCLUDED
        ],
    }
    manifest_root = compute_target / "migrations" / migration_identity
    manifest_path = manifest_root / "MANIFEST.json"
    manifest_sha256, manifest_disposition = _write_json_once(manifest_path, manifest)
    manifest_sha_path = manifest_root / "MANIFEST.sha256"
    _write_once(
        manifest_sha_path,
        f"{manifest_sha256}  MANIFEST.json\n".encode("ascii"),
    )
    readback = readback_live_reality_migration(
        manifest_path,
        expected_manifest_sha256=manifest_sha256,
        verify_sources=True,
    )
    return {
        "status": "verified",
        "schema": MIGRATION_SCHEMA,
        "migration_id": migration_identity,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "manifest_sha256_path": str(manifest_sha_path),
        "manifest_disposition": manifest_disposition,
        "base_bundle_root": str(base_root),
        "base_provenance_python_path": str(base_root / "code"),
        "base_payload_tree_sha256": base_payload_tree_sha256,
        "live_reality_container_root": str(live_target),
        "workspace_overlay_count": len(overlays),
        "lineage_effective_views": {
            overlay["workspace_key"]: {
                "lineage_id": overlay["lineage_id"],
                "workspace_key": overlay["workspace_key"],
                "workspace_root": overlay["workspace_root"],
                "effective_view_id": overlay["effective_view_id"],
                "effective_view_manifest_path": overlay["effective_view_manifest_path"],
                "effective_view_manifest_sha256": overlay[
                    "effective_view_manifest_sha256"
                ],
                "effective_code_root": overlay["effective_code_root"],
                "effective_python_path": overlay["effective_python_path"],
                "effective_code_payload_tree_sha256": overlay[
                    "effective_code_payload_tree_sha256"
                ],
                "effective_code_manifest_path": overlay[
                    "effective_code_manifest_path"
                ],
                "effective_code_manifest_sha256": overlay[
                    "effective_code_manifest_sha256"
                ],
                "private_effective_live_root": overlay["private_effective_live_root"],
                "effective_live_seed_root": overlay["effective_live_seed_root"],
                "effective_live_seed_payload_tree_sha256": overlay[
                    "effective_live_seed_payload_tree_sha256"
                ],
                "effective_live_seed_manifest_path": overlay[
                    "effective_live_seed_manifest_path"
                ],
                "effective_live_seed_manifest_sha256": overlay[
                    "effective_live_seed_manifest_sha256"
                ],
                "private_live_materialization": overlay[
                    "private_live_materialization"
                ],
                "deletion_tree_sha256": overlay["deletion_tree_sha256"],
                "deletion_count": overlay["deletion_count"],
                "deletions": overlay["deletions"],
                "runtime_environment": overlay["runtime_environment"],
                "runtime_binding_inputs": overlay["runtime_binding_inputs"],
            }
            for overlay in overlays
        },
        "private_live_dispositions": private_live_dispositions,
        "copy_count": len(copies),
        "source_preserved": True,
        "readback": readback,
    }


def _read_manifest_digest(manifest_path: Path) -> str:
    digest_path = manifest_path.with_suffix(".sha256")
    if not digest_path.exists():
        raise RealityMigrationError(f"manifest digest sidecar is missing: {digest_path}")
    tokens = digest_path.read_text(encoding="ascii").strip().split()
    if len(tokens) != 2 or tokens[1] != manifest_path.name or not _SHA256_RE.fullmatch(tokens[0]):
        raise RealityMigrationError(f"manifest digest sidecar is invalid: {digest_path}")
    return tokens[0]


def readback_live_reality_migration(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str | None = None,
    verify_sources: bool = True,
) -> dict[str, Any]:
    """Verify manifest identity, every destination payload, and source preservation."""

    path = Path(manifest_path).resolve(strict=True)
    raw = path.read_bytes()
    observed_manifest_sha256 = _sha256(raw)
    declared = _read_manifest_digest(path)
    expected = declared
    if expected_manifest_sha256 is not None:
        expected = expected_manifest_sha256.casefold()
        if expected != declared:
            raise RealityMigrationError(
                "MIGRATION_MANIFEST_SIDECAR_MISMATCH: "
                f"expected={expected}; declared={declared}"
            )
    if not _SHA256_RE.fullmatch(expected) or observed_manifest_sha256 != expected:
        raise RealityMigrationError(
            "MIGRATION_MANIFEST_HASH_MISMATCH: "
            f"expected={expected}; observed={observed_manifest_sha256}"
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RealityMigrationError(f"migration manifest is invalid JSON: {path}") from exc
    if manifest.get("schema") != MIGRATION_SCHEMA:
        raise RealityMigrationError(f"migration manifest schema mismatch: {path}")
    if manifest.get("source_deletion_permitted") is not False:
        raise RealityMigrationError("migration manifest does not preserve the no-delete boundary")

    live_root = Path(str(manifest["live_reality_root"])).resolve(strict=False)
    compute_root = Path(str(manifest["world_compute_root"])).resolve(strict=False)
    verified_payloads = 0
    verified_sources = 0
    for copy in manifest.get("copies", []):
        destination = Path(str(copy["destination_path"])).resolve(strict=False)
        if not (_is_relative_to(destination, live_root) or _is_relative_to(destination, compute_root)):
            raise RealityMigrationError(f"manifest destination escaped declared roots: {destination}")
        if not destination.exists() or not destination.is_file() or _is_reparse(destination):
            raise RealityMigrationError(f"migrated payload is absent or non-regular: {destination}")
        payload = destination.read_bytes()
        if len(payload) != copy["payload_bytes"] or _sha256(payload) != copy["payload_sha256"]:
            raise RealityMigrationError(f"migrated payload readback failed: {destination}")
        verified_payloads += 1
        source_value = copy.get("source_path")
        if verify_sources and source_value is not None:
            source = Path(str(source_value)).resolve(strict=False)
            if not source.exists() or not source.is_file() or _is_reparse(source):
                raise SourceTreeChangedError(f"source was removed after copy: {source}")
            source_raw = _read_stable(source)
            if len(source_raw) != copy["source_bytes"] or _sha256(source_raw) != copy["source_sha256"]:
                raise SourceTreeChangedError(f"source changed after copy: {source}")
            verified_sources += 1

    referenced_manifests = [manifest["base_bundle"], *manifest.get("workspace_overlays", [])]
    for reference in referenced_manifests:
        referenced_path = Path(str(reference["manifest_path"])).resolve(strict=False)
        if not _is_relative_to(referenced_path, compute_root):
            raise RealityMigrationError(f"referenced manifest escaped compute root: {referenced_path}")
        if not referenced_path.exists():
            raise RealityMigrationError(f"referenced manifest readback failed: {referenced_path}")
        referenced_sha256 = _sha256(referenced_path.read_bytes())
        if (
            referenced_sha256 != reference["manifest_sha256"]
            or _read_manifest_digest(referenced_path) != referenced_sha256
        ):
            raise RealityMigrationError(f"referenced manifest readback failed: {referenced_path}")

    canonical_live_reference = manifest.get("canonical_live_bundle")
    if canonical_live_reference:
        referenced_path = Path(str(canonical_live_reference["manifest_path"])).resolve(
            strict=False
        )
        if not _is_relative_to(referenced_path, live_root):
            raise RealityMigrationError(
                f"canonical live manifest escaped live container: {referenced_path}"
            )
        if (
            not referenced_path.exists()
            or _sha256(referenced_path.read_bytes())
            != canonical_live_reference["manifest_sha256"]
            or _read_manifest_digest(referenced_path)
            != canonical_live_reference["manifest_sha256"]
        ):
            raise RealityMigrationError(
                f"canonical live manifest readback failed: {referenced_path}"
            )

    verified_effective_views = 0
    for overlay in manifest.get("workspace_overlays", []):
        effective_code_manifest_path = Path(
            str(overlay["effective_code_manifest_path"])
        ).resolve(strict=False)
        effective_live_manifest_path = Path(
            str(overlay["effective_live_seed_manifest_path"])
        ).resolve(strict=False)
        effective_view_manifest_path = Path(
            str(overlay["effective_view_manifest_path"])
        ).resolve(strict=False)
        references = (
            (
                effective_code_manifest_path,
                str(overlay["effective_code_manifest_sha256"]),
                compute_root,
            ),
            (
                effective_live_manifest_path,
                str(overlay["effective_live_seed_manifest_sha256"]),
                live_root,
            ),
            (
                effective_view_manifest_path,
                str(overlay["effective_view_manifest_sha256"]),
                compute_root,
            ),
        )
        for referenced_path, referenced_hash, containing_root in references:
            if not _is_relative_to(referenced_path, containing_root):
                raise RealityMigrationError(
                    f"effective view manifest escaped declared root: {referenced_path}"
                )
            if (
                not referenced_path.is_file()
                or _sha256(referenced_path.read_bytes()) != referenced_hash
                or _read_manifest_digest(referenced_path) != referenced_hash
            ):
                raise RealityMigrationError(
                    f"effective view manifest readback failed: {referenced_path}"
                )
        effective_code_manifest = json.loads(
            effective_code_manifest_path.read_text(encoding="utf-8")
        )
        effective_live_manifest = json.loads(
            effective_live_manifest_path.read_text(encoding="utf-8")
        )
        effective_view_manifest = json.loads(
            effective_view_manifest_path.read_text(encoding="utf-8")
        )
        if (
            effective_code_manifest.get("schema") != EFFECTIVE_CODE_SCHEMA
            or effective_code_manifest.get("base_fallback_permitted") is not False
            or _hash_records(effective_code_manifest.get("entries", []))
            != effective_code_manifest.get("payload_tree_sha256")
            or effective_code_manifest.get("payload_tree_sha256")
            != overlay["effective_code_payload_tree_sha256"]
        ):
            raise RealityMigrationError(
                f"effective code manifest contract mismatch: {effective_code_manifest_path}"
            )
        if (
            effective_live_manifest.get("schema") != EFFECTIVE_LIVE_SEED_SCHEMA
            or _hash_records(effective_live_manifest.get("entries", []))
            != effective_live_manifest.get("payload_tree_sha256")
            or effective_live_manifest.get("payload_tree_sha256")
            != overlay["effective_live_seed_payload_tree_sha256"]
        ):
            raise RealityMigrationError(
                f"effective live manifest contract mismatch: {effective_live_manifest_path}"
            )
        if (
            effective_view_manifest.get("schema") != EFFECTIVE_VIEW_SCHEMA
            or effective_view_manifest.get("view_id") != overlay["effective_view_id"]
            or effective_view_manifest.get("lineage_id") != overlay["workspace_key"]
            or effective_view_manifest.get("workspace_key") != overlay["workspace_key"]
            or effective_view_manifest.get("workspace_mode") != "complete_clone"
            or effective_view_manifest.get("deletion_tree_sha256")
            != overlay["deletion_tree_sha256"]
        ):
            raise RealityMigrationError(
                f"effective view manifest contract mismatch: {effective_view_manifest_path}"
            )
        expected_view_id = _hash_records(
            [
                {
                    "workspace_key": overlay["workspace_key"],
                    "workspace_root": overlay["workspace_root"],
                    "workspace_mode": "complete_clone",
                    "workspace_source_exists": overlay["source_inventory"]["exists"],
                    "workspace_source_tree_sha256": overlay["source_inventory"][
                        "source_tree_sha256"
                    ],
                    "base_payload_tree_sha256": manifest["base_bundle"][
                        "payload_tree_sha256"
                    ],
                    "deletion_tree_sha256": overlay["deletion_tree_sha256"],
                    "effective_code_payload_tree_sha256": overlay[
                        "effective_code_payload_tree_sha256"
                    ],
                    "effective_live_payload_tree_sha256": overlay[
                        "effective_live_seed_payload_tree_sha256"
                    ],
                    "runtime_binding_inputs_identity": {
                        "schema": RUNTIME_BINDING_INPUTS_SCHEMA,
                        "lineage_id": overlay["workspace_key"],
                        "workspace": overlay["workspace_root"],
                        "base_manifest_path": manifest["base_bundle"]["manifest_path"],
                        "effective_code_payload_tree_sha256": overlay[
                            "effective_code_payload_tree_sha256"
                        ],
                        "private_live_root": overlay["private_effective_live_root"],
                        "live_seed_receipt_path": overlay[
                            "private_live_materialization"
                        ]["receipt_path"],
                        "live_seed_payload_tree_sha256": overlay[
                            "effective_live_seed_payload_tree_sha256"
                        ],
                    },
                }
            ]
        )
        if expected_view_id != overlay["effective_view_id"]:
            raise RealityMigrationError(
                f"effective view identity mismatch: {overlay['workspace_key']}"
            )
        effective_code_root = Path(str(overlay["effective_code_root"])).resolve(strict=False)
        effective_live_root = Path(str(overlay["effective_live_seed_root"])).resolve(strict=False)
        if not _is_relative_to(effective_code_root, compute_root) or not _is_relative_to(
            effective_live_root, live_root
        ):
            raise RealityMigrationError("effective view root escaped declared migration roots")
        _verify_exact_payload_tree(
            effective_code_root,
            effective_code_manifest["entries"],
            label=f"lineage effective code {overlay['workspace_key']}",
        )
        _verify_exact_payload_tree(
            effective_live_root,
            effective_live_manifest["entries"],
            label=f"lineage effective live seed {overlay['workspace_key']}",
        )
        deletion_hash = _hash_records(overlay["deletions"])
        if deletion_hash != overlay["deletion_tree_sha256"]:
            raise RealityMigrationError(
                f"lineage deletion identity mismatch: {overlay['workspace_key']}"
            )
        for deletion in overlay["deletions"]:
            relative = str(deletion["relative_path"])
            if deletion["classification"] in _SOURCE_CLASSES | {DERIVED_RESEARCH}:
                destination = effective_code_root / Path(
                    _logical_base_path(deletion)
                )
            else:
                destination = effective_live_root / Path(relative)
            if destination.exists():
                raise RealityMigrationError(
                    f"deleted lineage path survived effective view: {destination}"
                )
        private_contract = overlay["private_live_materialization"]
        private_root = Path(str(private_contract["root"])).resolve(strict=False)
        private_receipt_path = Path(str(private_contract["receipt_path"])).resolve(
            strict=False
        )
        workspace_root = Path(str(overlay["workspace_root"])).resolve(strict=False)
        expected_private_root = workspace_root / PRIVATE_LIVE_RELATIVE
        expected_receipt_path = (
            compute_root
            / "private-live-initialization"
            / str(overlay["workspace_key"])
            / "INITIALIZATION_RECEIPT.json"
        )
        if (
            overlay.get("lineage_id") != overlay["workspace_key"]
            or workspace_root.name != overlay["workspace_key"]
            or private_root != expected_private_root
            or not _is_relative_to(private_root, workspace_root)
            or _is_relative_to(private_root, workspace_root / LIVE_RELATIVE)
        ):
            raise RealityMigrationError(
                "private live contract is not the exact lineage-local non-legacy root: "
                f"{overlay['workspace_key']}"
            )
        if private_receipt_path != expected_receipt_path or not _is_relative_to(
            private_receipt_path, compute_root
        ):
            raise RealityMigrationError(
                f"private live receipt escaped compute root: {overlay['workspace_key']}"
            )
        private_receipt_hash = str(private_contract["receipt_sha256"])
        if (
            not private_receipt_path.is_file()
            or _sha256(private_receipt_path.read_bytes()) != private_receipt_hash
            or _read_manifest_digest(private_receipt_path) != private_receipt_hash
            or private_contract.get("marker_sha256")
            != _sha256(_canonical_json_bytes(private_contract["origin"]))
        ):
            raise RealityMigrationError(
                f"private live receipt contract mismatch: {overlay['workspace_key']}"
            )
        _validate_private_live(
            private_root,
            private_receipt_path,
            private_contract["origin"],
        )
        expected_runtime_binding_inputs = _runtime_binding_inputs(
            lineage_id=str(overlay["workspace_key"]),
            workspace_root=workspace_root,
            base_manifest_path=Path(str(manifest["base_bundle"]["manifest_path"])).resolve(
                strict=False
            ),
            base_manifest_sha256=str(manifest["base_bundle"]["manifest_sha256"]),
            effective_code_root=effective_code_root,
            effective_code_payload_tree_sha256=str(
                overlay["effective_code_payload_tree_sha256"]
            ),
            effective_code_manifest_path=effective_code_manifest_path,
            effective_code_manifest_sha256=str(
                overlay["effective_code_manifest_sha256"]
            ),
            private_live_contract=private_contract,
        )
        if (
            overlay.get("runtime_binding_inputs") != expected_runtime_binding_inputs
            or effective_view_manifest.get("runtime_binding_inputs")
            != expected_runtime_binding_inputs
        ):
            raise RealityMigrationError(
                f"runtime binding inputs mismatch: {overlay['workspace_key']}"
            )
        runtime_environment = overlay["runtime_environment"]
        if (
            runtime_environment.get("XINAO_WORLD_WORKSPACE") != overlay["workspace_root"]
            or runtime_environment.get("XINAO_LIVE_REALITY_ROOT")
            != overlay["private_effective_live_root"]
            or runtime_environment.get("PYTHONPATH") != overlay["effective_python_path"]
            or runtime_environment.get("PYTHONDONTWRITEBYTECODE") != "1"
            or overlay.get("python_path_order") != [overlay["effective_python_path"]]
        ):
            raise RealityMigrationError(
                f"lineage runtime binding mismatch: {overlay['workspace_key']}"
            )
        verified_effective_views += 1

    if verify_sources:
        canonical_live = Path(str(manifest["canonical_live_root"]))
        current = _inventory_live_root(canonical_live, required=True)
        expected_tree = manifest["canonical_inventory"]["source_tree_sha256"]
        if current["source_tree_sha256"] != expected_tree:
            raise SourceTreeChangedError("canonical source tree changed after manifest creation")
        for overlay in manifest.get("workspace_overlays", []):
            source_live = Path(str(overlay["source_live_root"]))
            current_overlay = _inventory_live_root(source_live, required=False)
            expected_overlay = overlay["source_inventory"]["source_tree_sha256"]
            expected_exists = overlay["source_inventory"]["exists"]
            if (
                current_overlay["exists"] != expected_exists
                or current_overlay["source_tree_sha256"] != expected_overlay
            ):
                raise SourceTreeChangedError(
                    f"workspace source tree changed after manifest creation: {overlay['workspace_key']}"
                )

    return {
        "schema": READBACK_SCHEMA,
        "status": "verified",
        "migration_id": manifest["migration_id"],
        "manifest_sha256": observed_manifest_sha256,
        "verified_payload_count": verified_payloads,
        "verified_source_count": verified_sources,
        "verified_effective_view_count": verified_effective_views,
        "source_preserved": verify_sources,
    }


__all__ = [
    "ActiveChildProcessError",
    "DestinationConflictError",
    "RealityMigrationError",
    "SourceTreeChangedError",
    "assert_no_active_child_pids",
    "inventory_live_reality",
    "migrate_live_reality_copy_first",
    "readback_live_reality_migration",
    "transform_research_source",
]
