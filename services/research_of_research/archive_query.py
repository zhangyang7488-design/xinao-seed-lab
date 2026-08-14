"""Deterministic, neutral access to an opaque local archive.

The public catalog deliberately contains no backing-store path, source label,
summary, embedding, or ranking signal.  A separate assessor-side config binds
opaque record ids to regular, non-link files.  Every invocation is recorded as
a STARTED/result pair in a tamper-evident JSONL ledger.

This module is intentionally stdlib-only so it can be copied with its tiny CLI
wrapper into an isolated clean-room workspace.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

CATALOG_SCHEMA = "xinao.research-of-research.neutral-archive-catalog.v1"
CONFIG_SCHEMA = "xinao.research-of-research.neutral-archive-config.v1"
LEDGER_SCHEMA = "xinao.research-of-research.archive-query-ledger-event.v1"
RESULT_SCHEMA = "xinao.research-of-research.archive-query-result.v1"
ERROR_SCHEMA = "xinao.research-of-research.archive-query-error.v1"

_PUBLIC_RECORD_FIELDS = ("record_id", "kind", "created_at", "bytes", "sha256")
_ALLOWED_OPERATIONS = ("catalog", "list", "metadata", "find", "open")
_ORDERING = "record_id_ascending"
_KIND_POLICY = "lowercase_file_extension_v1"
_CREATED_AT_POLICY = "filesystem_mtime_utc_nanoseconds_v1"
_ABSOLUTE_BINDING = "absolute_paths_v1"
_PORTABLE_BINDING = "portable_relative_paths_v1"
_ABSOLUTE_RECORD_IDENTITY = "relative_path_kind_created_at_bytes_sha256_v1"
_PORTABLE_RECORD_IDENTITY = "relative_path_kind_bytes_sha256_v1"


class ArchiveQueryError(RuntimeError):
    """A catalog, backing-store, query, or ledger invariant failed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise ArchiveQueryError(code, message)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp_from_ns(value: int) -> str:
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    prefix = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{prefix}.{nanoseconds:09d}Z"


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return False


def _resolved_existing_directory(path: str | Path, *, code: str) -> Path:
    candidate = Path(path).expanduser()
    if _is_link(candidate):
        _fail(code, "directory must be a real non-link directory")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ArchiveQueryError(code, "directory does not exist") from exc
    if not resolved.is_dir() or _is_link(resolved):
        _fail(code, "directory must be a real non-link directory")
    return resolved


def _resolved_output(path: str | Path, *, code: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.exists() and _is_link(candidate):
        _fail(code, "output must not be a link")
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise ArchiveQueryError(code, "output parent does not exist") from exc
    if not parent.is_dir() or _is_link(parent):
        _fail(code, "output parent must be a real non-link directory")
    return parent / candidate.name


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _require_store_separation(store_root: Path, paths: Sequence[Path]) -> None:
    for output in paths:
        if _is_within(output, store_root) or _is_within(store_root, output):
            _fail(
                "STORE_NOT_SEPARATED",
                "catalog, config, and ledger must be outside the backing store",
            )


def _relative_to_root(path: Path, root: Path, *, code: str) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ArchiveQueryError(code, "path is outside the portable root") from exc
    if not relative.parts:
        _fail(code, "portable member must not be the portable root itself")
    return relative.as_posix()


def _assert_portable_member(root: Path, path: Path, *, code: str) -> str:
    relative_text = _relative_to_root(path, root, code=code)
    relative = _safe_relative_path(relative_text)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_link(current):
            _fail(code, "portable tree contains a link")
    return relative_text


def _portable_root_from_config(config_path: Path, relative_text: str) -> Path:
    relative = _safe_relative_path(relative_text)
    candidate = config_path
    for _ in relative.parts:
        candidate = candidate.parent
    root = _resolved_existing_directory(candidate, code="PORTABLE_ROOT_INVALID")
    expected = root.joinpath(*relative.parts)
    try:
        expected = expected.resolve(strict=True)
    except OSError as exc:
        raise ArchiveQueryError("CONFIG_PATH_MISMATCH", "portable config path is missing") from exc
    if expected != config_path:
        _fail("CONFIG_PATH_MISMATCH", "config path differs from portable binding")
    _assert_portable_member(root, config_path, code="CONFIG_PATH_MISMATCH")
    return root


def _safe_relative_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or ":" in relative.parts[0]
    ):
        _fail("CONFIG_INVALID", "store_relative_path is not a safe relative path")
    return relative


def _target_for_relative(store_root: Path, value: str) -> Path:
    relative = _safe_relative_path(value)
    current = store_root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            _fail("BACKING_STORE_LINK", "backing store contains a link")
    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise ArchiveQueryError("ARCHIVE_DRIFT", "backing record is missing") from exc
    if not _is_within(resolved, store_root):
        _fail("PATH_ESCAPE", "backing record escapes the frozen store")
    if not resolved.is_file() or _is_link(resolved):
        _fail("BACKING_RECORD_INVALID", "backing record is not a regular non-link file")
    return resolved


def _stable_read(path: Path) -> tuple[bytes, os.stat_result]:
    if _is_link(path) or not path.is_file():
        _fail("BACKING_RECORD_INVALID", "backing record is not a regular non-link file")
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ArchiveQueryError("BACKING_READ_FAILED", "backing record could not be read") from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(raw) != before.st_size:
        _fail("BACKING_CHANGED_DURING_READ", "backing record changed during read")
    return raw, before


def _kind_for(relative_path: str) -> str:
    suffix = PurePosixPath(relative_path).suffix.casefold().lstrip(".")
    return f"extension:{suffix}" if suffix else "extension:none"


def _record_id(
    relative_path: str,
    raw: bytes,
    created_at: str,
    kind: str,
    *,
    identity_policy: str,
) -> str:
    identity = {
        "store_relative_path": relative_path,
        "kind": kind,
        "bytes": len(raw),
        "sha256": _sha(raw),
    }
    if identity_policy == _ABSOLUTE_RECORD_IDENTITY:
        identity["created_at"] = created_at
    elif identity_policy != _PORTABLE_RECORD_IDENTITY:
        _fail("RECORD_IDENTITY_POLICY_INVALID", "record identity policy is unsupported")
    return _sha(_canonical_bytes(identity))


def _scan_store(
    store_root: Path, *, identity_policy: str = _ABSOLUTE_RECORD_IDENTITY
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    records: list[dict[str, Any]] = []
    record_paths: dict[str, str] = {}
    for current_text, directory_names, file_names in os.walk(store_root, followlinks=False):
        current = Path(current_text)
        for name in directory_names:
            if _is_link(current / name):
                _fail("BACKING_STORE_LINK", "backing store contains a link")
        directory_names.sort(key=lambda item: item.encode("utf-8"))
        file_names.sort(key=lambda item: item.encode("utf-8"))
        for name in file_names:
            path = current / name
            if _is_link(path):
                _fail("BACKING_STORE_LINK", "backing store contains a link")
            relative = path.relative_to(store_root).as_posix()
            _safe_relative_path(relative)
            raw, identity = _stable_read(path)
            created_at = _timestamp_from_ns(identity.st_mtime_ns)
            kind = _kind_for(relative)
            record_id = _record_id(
                relative,
                raw,
                created_at,
                kind,
                identity_policy=identity_policy,
            )
            if record_id in record_paths:
                _fail("RECORD_ID_COLLISION", "two backing records produced the same opaque id")
            records.append(
                {
                    "record_id": record_id,
                    "kind": kind,
                    "created_at": created_at,
                    "bytes": len(raw),
                    "sha256": _sha(raw),
                }
            )
            record_paths[record_id] = relative
    records.sort(key=lambda row: row["record_id"])
    return records, record_paths


def _public_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in records:
        if set(row) != set(_PUBLIC_RECORD_FIELDS):
            _fail("CATALOG_INVALID", "public record contains unsupported fields")
        record = {field: row[field] for field in _PUBLIC_RECORD_FIELDS}
        if not all(
            isinstance(record[field], str) and record[field] for field in _PUBLIC_RECORD_FIELDS[:3]
        ):
            _fail("CATALOG_INVALID", "public record identity fields must be non-empty strings")
        if not isinstance(record["bytes"], int) or record["bytes"] < 0:
            _fail("CATALOG_INVALID", "public record byte count is invalid")
        if not isinstance(record["sha256"], str) or len(record["sha256"]) != 64:
            _fail("CATALOG_INVALID", "public record sha256 is invalid")
        result.append(record)
    if [row["record_id"] for row in result] != sorted(row["record_id"] for row in result):
        _fail("CATALOG_INVALID", "public records are not in frozen record-id order")
    if len({row["record_id"] for row in result}) != len(result):
        _fail("CATALOG_INVALID", "public record ids are not unique")
    return result


def _allowed_invocation_shapes() -> list[dict[str, Any]]:
    common = [
        "--catalog",
        "<catalog.json>",
        "--config",
        "<config.json>",
        "--ledger",
        "<query_log.jsonl>",
    ]
    return [
        {"operation": "list", "argv": ["list", *common, "[--kind <opaque-kind>]"]},
        {"operation": "metadata", "argv": ["metadata", *common, "[record_id ...]"]},
        {
            "operation": "find",
            "argv": ["find", *common, "<fixed-string>", "[--kind <opaque-kind>]"],
        },
        {"operation": "open", "argv": ["open", *common, "record_id", "[record_id ...]"]},
    ]


def _ledger_id(path: Path, *, portable_root: Path | None = None) -> str:
    if portable_root is None:
        identity = {
            "binding_mode": _ABSOLUTE_BINDING,
            "query_ledger_path": str(path),
        }
    else:
        identity = {
            "binding_mode": _PORTABLE_BINDING,
            "query_ledger_relative_path": _relative_to_root(
                path, portable_root, code="PORTABLE_PATH_OUTSIDE_ROOT"
            ),
        }
    return _sha(_canonical_bytes(identity))


def _build_catalog_and_config(
    *,
    store_root: Path,
    catalog_path: Path,
    config_path: Path,
    ledger_path: Path,
    max_open_count: int,
    portable_root: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding_mode = _PORTABLE_BINDING if portable_root is not None else _ABSOLUTE_BINDING
    record_identity_policy = (
        _PORTABLE_RECORD_IDENTITY if portable_root is not None else _ABSOLUTE_RECORD_IDENTITY
    )
    records, record_paths = _scan_store(store_root, identity_policy=record_identity_policy)
    catalog_identity = {
        "records": records,
        "max_open_count": max_open_count,
        "ordering": _ORDERING,
        "kind_policy": _KIND_POLICY,
        "created_at_policy": _CREATED_AT_POLICY,
        "record_identity_policy": record_identity_policy,
    }
    catalog_id = _sha(_canonical_bytes(catalog_identity))
    if portable_root is None:
        binding = {
            "mode": binding_mode,
            "store_root": str(store_root),
            "catalog_path": str(catalog_path),
            "config_path": str(config_path),
            "query_ledger_path": str(ledger_path),
        }
    else:
        binding = {
            "mode": binding_mode,
            "store_relative_path": _assert_portable_member(
                portable_root, store_root, code="PORTABLE_PATH_OUTSIDE_ROOT"
            ),
            "catalog_relative_path": _assert_portable_member(
                portable_root, catalog_path, code="PORTABLE_PATH_OUTSIDE_ROOT"
            ),
            "config_relative_path": _assert_portable_member(
                portable_root, config_path, code="PORTABLE_PATH_OUTSIDE_ROOT"
            ),
            "query_ledger_relative_path": _assert_portable_member(
                portable_root, ledger_path, code="PORTABLE_PATH_OUTSIDE_ROOT"
            ),
        }
    query_ledger_id = _ledger_id(ledger_path, portable_root=portable_root)
    config_identity = {
        "catalog_id": catalog_id,
        "query_ledger_id": query_ledger_id,
        "max_open_count": max_open_count,
        "ordering": _ORDERING,
        "record_identity_policy": record_identity_policy,
        "binding": binding,
        "record_paths": record_paths,
        "allowed_invocation_shapes": _allowed_invocation_shapes(),
    }
    config_id = _sha(_canonical_bytes(config_identity))
    catalog_created_at = (
        max(row["created_at"] for row in records) if records else "1970-01-01T00:00:00.000000000Z"
    )
    catalog_unsigned = {
        "schema": CATALOG_SCHEMA,
        "catalog_id": catalog_id,
        "config_id": config_id,
        "created_at": catalog_created_at,
        "records": records,
        "max_open_count": max_open_count,
        "ordering": _ORDERING,
        "authority": False,
        "completion_claim_allowed": False,
    }
    catalog = {**catalog_unsigned, "catalog_sha256": _sha(_canonical_bytes(catalog_unsigned))}
    config_unsigned = {
        "schema": CONFIG_SCHEMA,
        "config_id": config_id,
        "catalog_id": catalog_id,
        "catalog_sha256": catalog["catalog_sha256"],
        "query_ledger_id": query_ledger_id,
        "max_open_count": max_open_count,
        "ordering": _ORDERING,
        "kind_policy": _KIND_POLICY,
        "created_at_policy": _CREATED_AT_POLICY,
        "record_identity_policy": record_identity_policy,
        "binding_mode": binding_mode,
        "allowed_invocation_shapes": _allowed_invocation_shapes(),
        "provenance": {
            **{key: value for key, value in binding.items() if key != "mode"},
            "records": [
                {
                    "record_id": row["record_id"],
                    "store_relative_path": record_paths[row["record_id"]],
                }
                for row in records
            ],
        },
        "authority": False,
        "completion_claim_allowed": False,
    }
    config = {**config_unsigned, "config_sha256": _sha(_canonical_bytes(config_unsigned))}
    return catalog, config


def _atomic_write_once(path: Path, value: Mapping[str, Any], *, code: str) -> str:
    raw = _canonical_bytes(value)
    if path.exists():
        if _is_link(path) or not path.is_file():
            _fail(code, "frozen output is not a regular non-link file")
        try:
            prior = path.read_bytes()
        except OSError as exc:
            raise ArchiveQueryError(code, "frozen output could not be read") from exc
        if prior == raw:
            return "reused"
        _fail(code, "frozen output already exists with different bytes")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ArchiveQueryError(code, "frozen output could not be written") from exc
    return "created"


def _read_json_object(path: Path, *, code: str) -> dict[str, Any]:
    if _is_link(path) or not path.is_file():
        _fail(code, "required file is not a regular non-link file")
    try:
        raw, _ = _stable_read(path)
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveQueryError(code, "required JSON object is invalid") from exc
    if not isinstance(value, dict):
        _fail(code, "required JSON root must be an object")
    return value


def _validate_seal(value: Mapping[str, Any], seal_field: str, *, code: str) -> None:
    unsigned = dict(value)
    observed = unsigned.pop(seal_field, None)
    if not isinstance(observed, str) or observed != _sha(_canonical_bytes(unsigned)):
        _fail(code, "sealed JSON object failed validation")


def _validate_catalog_config(
    catalog_path: Path, config_path: Path, ledger_path: Path
) -> tuple[dict[str, Any], dict[str, Any], Path, dict[str, str]]:
    catalog = _read_json_object(catalog_path, code="CATALOG_INVALID")
    config = _read_json_object(config_path, code="CONFIG_INVALID")
    if catalog.get("schema") != CATALOG_SCHEMA or config.get("schema") != CONFIG_SCHEMA:
        _fail("SCHEMA_MISMATCH", "catalog or config schema is unsupported")
    _validate_seal(catalog, "catalog_sha256", code="CATALOG_SEAL_INVALID")
    _validate_seal(config, "config_sha256", code="CONFIG_SEAL_INVALID")
    records = _public_records(catalog.get("records", []))
    if (
        catalog.get("authority") is not False
        or catalog.get("completion_claim_allowed") is not False
    ):
        _fail("CATALOG_INVALID", "catalog authority flags are invalid")
    if config.get("authority") is not False or config.get("completion_claim_allowed") is not False:
        _fail("CONFIG_INVALID", "config authority flags are invalid")
    if (
        catalog.get("catalog_id") != config.get("catalog_id")
        or catalog.get("config_id") != config.get("config_id")
        or catalog.get("catalog_sha256") != config.get("catalog_sha256")
    ):
        _fail("CATALOG_CONFIG_MISMATCH", "catalog and config identities do not match")
    max_open_count = catalog.get("max_open_count")
    if (
        not isinstance(max_open_count, int)
        or isinstance(max_open_count, bool)
        or max_open_count < 0
        or config.get("max_open_count") != max_open_count
    ):
        _fail("CONFIG_INVALID", "frozen max_open_count is invalid")
    if catalog.get("ordering") != _ORDERING or config.get("ordering") != _ORDERING:
        _fail("CONFIG_INVALID", "frozen ordering is invalid")
    provenance = config.get("provenance")
    if not isinstance(provenance, dict):
        _fail("CONFIG_INVALID", "config provenance is missing")
    binding_mode = config.get("binding_mode", _ABSOLUTE_BINDING)
    if binding_mode == _ABSOLUTE_BINDING:
        binding = {
            "mode": binding_mode,
            "store_root": str(provenance.get("store_root", "")),
            "catalog_path": str(provenance.get("catalog_path", "")),
            "config_path": str(provenance.get("config_path", "")),
            "query_ledger_path": str(provenance.get("query_ledger_path", "")),
        }
        expected_paths = {
            "catalog_path": str(catalog_path),
            "config_path": str(config_path),
            "query_ledger_path": str(ledger_path),
        }
        if any(provenance.get(key) != value for key, value in expected_paths.items()):
            _fail("CONFIG_PATH_MISMATCH", "invocation paths differ from frozen config")
        store_root = _resolved_existing_directory(
            binding["store_root"], code="BACKING_STORE_INVALID"
        )
        expected_ledger_id = _ledger_id(ledger_path)
    elif binding_mode == _PORTABLE_BINDING:
        relative_fields = {
            "store_relative_path": provenance.get("store_relative_path"),
            "catalog_relative_path": provenance.get("catalog_relative_path"),
            "config_relative_path": provenance.get("config_relative_path"),
            "query_ledger_relative_path": provenance.get("query_ledger_relative_path"),
        }
        if not all(isinstance(value, str) and value for value in relative_fields.values()):
            _fail("CONFIG_INVALID", "portable binding paths are invalid")
        portable_root = _portable_root_from_config(
            config_path, str(relative_fields["config_relative_path"])
        )
        resolved_members: dict[str, Path] = {}
        for field, relative_text in relative_fields.items():
            relative = _safe_relative_path(str(relative_text))
            candidate = portable_root.joinpath(*relative.parts)
            if field == "store_relative_path":
                resolved = _resolved_existing_directory(candidate, code="BACKING_STORE_INVALID")
            else:
                try:
                    resolved = candidate.resolve(strict=True)
                except OSError as exc:
                    raise ArchiveQueryError(
                        "CONFIG_PATH_MISMATCH", "portable invocation member is missing"
                    ) from exc
                if not resolved.is_file() or _is_link(resolved):
                    _fail(
                        "CONFIG_PATH_MISMATCH",
                        "portable invocation member is not a regular non-link file",
                    )
            _assert_portable_member(portable_root, resolved, code="CONFIG_PATH_MISMATCH")
            resolved_members[field] = resolved
        if (
            resolved_members["catalog_relative_path"] != catalog_path
            or resolved_members["config_relative_path"] != config_path
            or resolved_members["query_ledger_relative_path"] != ledger_path
        ):
            _fail("CONFIG_PATH_MISMATCH", "invocation paths differ from portable binding")
        store_root = resolved_members["store_relative_path"]
        binding = {"mode": binding_mode, **relative_fields}
        expected_ledger_id = _ledger_id(ledger_path, portable_root=portable_root)
    else:
        _fail("CONFIG_INVALID", "config binding mode is unsupported")
    if config.get("query_ledger_id") != expected_ledger_id:
        _fail("LEDGER_BINDING_MISMATCH", "query ledger differs from frozen config")
    _require_store_separation(store_root, [catalog_path, config_path, ledger_path])
    provenance_rows = provenance.get("records")
    if not isinstance(provenance_rows, list):
        _fail("CONFIG_INVALID", "record provenance is invalid")
    record_paths: dict[str, str] = {}
    for row in provenance_rows:
        if not isinstance(row, dict) or set(row) != {"record_id", "store_relative_path"}:
            _fail("CONFIG_INVALID", "record provenance row is invalid")
        record_id = row.get("record_id")
        relative = row.get("store_relative_path")
        if not isinstance(record_id, str) or not isinstance(relative, str):
            _fail("CONFIG_INVALID", "record provenance values are invalid")
        _safe_relative_path(relative)
        if record_id in record_paths:
            _fail("CONFIG_INVALID", "record provenance contains duplicate ids")
        record_paths[record_id] = relative
    if set(record_paths) != {row["record_id"] for row in records}:
        _fail("CONFIG_INVALID", "record provenance does not cover the public catalog")
    catalog_identity = {
        "records": records,
        "max_open_count": max_open_count,
        "ordering": _ORDERING,
        "kind_policy": config.get("kind_policy"),
        "created_at_policy": config.get("created_at_policy"),
        "record_identity_policy": config.get("record_identity_policy"),
    }
    if catalog.get("catalog_id") != _sha(_canonical_bytes(catalog_identity)):
        _fail("CATALOG_ID_INVALID", "catalog identity does not match public records")
    config_identity = {
        "catalog_id": catalog["catalog_id"],
        "query_ledger_id": config["query_ledger_id"],
        "max_open_count": max_open_count,
        "ordering": _ORDERING,
        "record_identity_policy": config.get("record_identity_policy"),
        "binding": binding,
        "record_paths": record_paths,
        "allowed_invocation_shapes": config.get("allowed_invocation_shapes"),
    }
    if config.get("config_id") != _sha(_canonical_bytes(config_identity)):
        _fail("CONFIG_ID_INVALID", "config identity does not match frozen provenance")
    return catalog, config, store_root, record_paths


def _validate_live_store(
    catalog: Mapping[str, Any],
    config: Mapping[str, Any],
    store_root: Path,
    record_paths: Mapping[str, str],
) -> dict[str, bytes]:
    identity_policy = config.get("record_identity_policy")
    records, observed_paths = _scan_store(store_root, identity_policy=str(identity_policy))
    if observed_paths != record_paths:
        _fail("ARCHIVE_DRIFT", "backing store differs from the frozen catalog")
    if identity_policy == _PORTABLE_RECORD_IDENTITY:
        expected_without_time = [
            {key: value for key, value in row.items() if key != "created_at"}
            for row in catalog["records"]
        ]
        observed_without_time = [
            {key: value for key, value in row.items() if key != "created_at"} for row in records
        ]
        if observed_without_time != expected_without_time:
            _fail("ARCHIVE_DRIFT", "backing store differs from the frozen catalog")
    elif records != catalog["records"]:
        _fail("ARCHIVE_DRIFT", "backing store differs from the frozen catalog")
    contents: dict[str, bytes] = {}
    expected_by_id = {row["record_id"]: row for row in catalog["records"]}
    for record_id, relative in record_paths.items():
        path = _target_for_relative(store_root, relative)
        raw, _ = _stable_read(path)
        expected = expected_by_id[record_id]
        if len(raw) != expected["bytes"] or _sha(raw) != expected["sha256"]:
            _fail("ARCHIVE_DRIFT", "backing record differs from the frozen catalog")
        contents[record_id] = raw
    return contents


def _validate_ledger_rows(raw: bytes) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        _fail("LEDGER_INVALID", "query ledger does not end at a complete record")
    rows: list[dict[str, Any]] = []
    previous: str | None = None
    for index, line in enumerate(raw.splitlines(), start=1):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveQueryError("LEDGER_INVALID", "query ledger contains invalid JSON") from exc
        if not isinstance(row, dict) or row.get("schema") != LEDGER_SCHEMA:
            _fail("LEDGER_INVALID", "query ledger contains an invalid event")
        unsigned = dict(row)
        observed = unsigned.pop("entry_sha256", None)
        if observed != _sha(_canonical_bytes(unsigned)):
            _fail("LEDGER_INVALID", "query ledger event seal is invalid")
        if row.get("sequence") != index or row.get("previous_entry_sha256") != previous:
            _fail("LEDGER_INVALID", "query ledger chain is invalid")
        previous = observed
        rows.append(row)
    return rows


@contextmanager
def _ledger_lock(ledger_path: Path) -> Iterator[None]:
    lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
    if lock_path.exists() and _is_link(lock_path):
        _fail("LEDGER_LOCK_INVALID", "ledger lock must not be a link")
    try:
        handle = lock_path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
    except OSError as exc:
        raise ArchiveQueryError("LEDGER_LOCK_FAILED", "ledger lock could not be opened") from exc
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    if _is_link(ledger_path) or not ledger_path.is_file():
        _fail("LEDGER_INVALID", "query ledger must be a regular non-link file")
    try:
        raw = ledger_path.read_bytes()
    except OSError as exc:
        raise ArchiveQueryError("LEDGER_READ_FAILED", "query ledger could not be read") from exc
    return _validate_ledger_rows(raw)


def _append_ledger_event(
    ledger_path: Path, rows: list[dict[str, Any]], event: dict[str, Any]
) -> dict[str, Any]:
    unsigned = {
        **event,
        "schema": LEDGER_SCHEMA,
        "sequence": len(rows) + 1,
        "previous_entry_sha256": rows[-1]["entry_sha256"] if rows else None,
        "authority": False,
        "completion_claim_allowed": False,
    }
    sealed = {**unsigned, "entry_sha256": _sha(_canonical_bytes(unsigned))}
    raw = _canonical_bytes(sealed)
    try:
        descriptor = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            written = os.write(descriptor, raw)
            if written != len(raw):
                _fail("LEDGER_WRITE_FAILED", "query ledger append was incomplete")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ArchiveQueryError("LEDGER_WRITE_FAILED", "query ledger append failed") from exc
    rows.append(sealed)
    return sealed


def _opened_unique_ids(rows: Sequence[Mapping[str, Any]], catalog_id: str) -> set[str]:
    opened: set[str] = set()
    for row in rows:
        if (
            row.get("phase") == "result"
            and row.get("status") == "SUCCESS"
            and row.get("catalog_id") == catalog_id
        ):
            actual = row.get("actual_open", {})
            if isinstance(actual, dict):
                values = actual.get("record_ids", [])
                if isinstance(values, list):
                    opened.update(value for value in values if isinstance(value, str))
    return opened


def _request_event(operation_id: str, operation: str, query: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "phase": "request",
        "status": "STARTED",
        "occurred_at": _now(),
        "catalog_id": None,
        "operation": operation,
        "query": dict(query),
        "candidate_record_ids": [],
        "result_record_ids": [],
        "result_count": 0,
        "ordering": None,
        "actual_open": {"record_ids": [], "records": [], "count": 0},
        "error": None,
        "request_entry_sha256": None,
    }


def _operation_id(
    rows: Sequence[Mapping[str, Any]], operation: str, query: Mapping[str, Any]
) -> str:
    return _sha(
        _canonical_bytes(
            {
                "request_sequence": len(rows) + 1,
                "previous_entry_sha256": rows[-1]["entry_sha256"] if rows else None,
                "operation": operation,
                "query": dict(query),
            }
        )
    )


def _result_event(
    *,
    operation_id: str,
    request_entry_sha256: str,
    operation: str,
    query: Mapping[str, Any],
    catalog_id: str | None,
    candidate_ids: Sequence[str],
    result_ids: Sequence[str],
    result_ordering: str,
    actual_open_records: Sequence[Mapping[str, Any]],
    status: str,
    error: Mapping[str, Any] | None,
) -> dict[str, Any]:
    actual = [dict(row) for row in actual_open_records]
    return {
        "operation_id": operation_id,
        "phase": "result",
        "status": status,
        "occurred_at": _now(),
        "catalog_id": catalog_id,
        "operation": operation,
        "query": dict(query),
        "candidate_record_ids": list(candidate_ids),
        "result_record_ids": list(result_ids),
        "result_count": len(result_ids),
        "ordering": {
            "candidates": _ORDERING,
            "results": result_ordering,
            "actual_open": "request_order",
        },
        "actual_open": {
            "record_ids": [row["record_id"] for row in actual],
            "records": actual,
            "count": len(actual),
        },
        "error": dict(error) if error is not None else None,
        "request_entry_sha256": request_entry_sha256,
    }


def _public_result(
    *, operation_id: str, operation: str, catalog_id: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "operation_id": operation_id,
        "operation": operation,
        "catalog_id": catalog_id,
        "result": dict(result),
        "authority": False,
        "completion_claim_allowed": False,
    }


def catalog_archive(
    *,
    store_root: str | Path,
    catalog_path: str | Path,
    config_path: str | Path,
    ledger_path: str | Path,
    max_open_count: int = 3,
    portable_root: str | Path | None = None,
) -> dict[str, Any]:
    """Freeze a neutral public catalog and private backing-store config."""

    catalog_file = _resolved_output(catalog_path, code="CATALOG_PATH_INVALID")
    config_file = _resolved_output(config_path, code="CONFIG_PATH_INVALID")
    ledger_file = _resolved_output(ledger_path, code="LEDGER_PATH_INVALID")
    if len({catalog_file, config_file, ledger_file}) != 3:
        _fail("OUTPUT_PATH_COLLISION", "catalog, config, and ledger paths must differ")
    if (
        not isinstance(max_open_count, int)
        or isinstance(max_open_count, bool)
        or max_open_count < 0
    ):
        _fail("MAX_OPEN_COUNT_INVALID", "max_open_count must be a non-negative integer")
    query = {
        "max_open_count": max_open_count,
        "binding_mode": (_PORTABLE_BINDING if portable_root is not None else _ABSOLUTE_BINDING),
    }
    with _ledger_lock(ledger_file):
        rows = _read_ledger(ledger_file)
        operation_id = _operation_id(rows, "catalog", query)
        request = _append_ledger_event(
            ledger_file, rows, _request_event(operation_id, "catalog", query)
        )
        catalog_id: str | None = None
        candidate_ids: list[str] = []
        try:
            root = _resolved_existing_directory(store_root, code="BACKING_STORE_INVALID")
            _require_store_separation(root, [catalog_file, config_file, ledger_file])
            portable = (
                _resolved_existing_directory(portable_root, code="PORTABLE_ROOT_INVALID")
                if portable_root is not None
                else None
            )
            if portable is not None:
                _assert_portable_member(portable, root, code="PORTABLE_PATH_OUTSIDE_ROOT")
                for output in (catalog_file, config_file, ledger_file):
                    _assert_portable_member(portable, output, code="PORTABLE_PATH_OUTSIDE_ROOT")
            catalog, config = _build_catalog_and_config(
                store_root=root,
                catalog_path=catalog_file,
                config_path=config_file,
                ledger_path=ledger_file,
                max_open_count=max_open_count,
                portable_root=portable,
            )
            catalog_id = catalog["catalog_id"]
            candidate_ids = [row["record_id"] for row in catalog["records"]]
            config_disposition = _atomic_write_once(
                config_file, config, code="CONFIG_ALREADY_FROZEN"
            )
            catalog_disposition = _atomic_write_once(
                catalog_file, catalog, code="CATALOG_ALREADY_FROZEN"
            )
            event = _result_event(
                operation_id=operation_id,
                request_entry_sha256=request["entry_sha256"],
                operation="catalog",
                query=query,
                catalog_id=catalog_id,
                candidate_ids=candidate_ids,
                result_ids=candidate_ids,
                result_ordering=_ORDERING,
                actual_open_records=[],
                status="SUCCESS",
                error=None,
            )
            _append_ledger_event(ledger_file, rows, event)
            return _public_result(
                operation_id=operation_id,
                operation="catalog",
                catalog_id=catalog_id,
                result={
                    "records": catalog["records"],
                    "record_ids": candidate_ids,
                    "count": len(candidate_ids),
                    "max_open_count": max_open_count,
                    "ordering": _ORDERING,
                    "catalog_disposition": catalog_disposition,
                    "config_disposition": config_disposition,
                },
            )
        except Exception as exc:
            error = _error_from_exception(exc)
            event = _result_event(
                operation_id=operation_id,
                request_entry_sha256=request["entry_sha256"],
                operation="catalog",
                query=query,
                catalog_id=catalog_id,
                candidate_ids=candidate_ids,
                result_ids=[],
                result_ordering=_ORDERING,
                actual_open_records=[],
                status="REJECTED" if isinstance(exc, ArchiveQueryError) else "ERROR",
                error=error,
            )
            _append_ledger_event(ledger_file, rows, event)
            if isinstance(exc, ArchiveQueryError):
                raise
            raise ArchiveQueryError(error["code"], error["message"]) from exc


def _query_operation(
    *,
    operation: str,
    query: Mapping[str, Any],
    catalog_path: str | Path,
    config_path: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    if operation not in {"list", "metadata", "find", "open"}:
        _fail("OPERATION_INVALID", "unsupported archive query operation")
    catalog_file = _resolved_output(catalog_path, code="CATALOG_PATH_INVALID")
    config_file = _resolved_output(config_path, code="CONFIG_PATH_INVALID")
    ledger_file = _resolved_output(ledger_path, code="LEDGER_PATH_INVALID")
    with _ledger_lock(ledger_file):
        rows = _read_ledger(ledger_file)
        operation_id = _operation_id(rows, operation, query)
        request = _append_ledger_event(
            ledger_file, rows, _request_event(operation_id, operation, query)
        )
        catalog_id: str | None = None
        candidate_ids: list[str] = []
        result_ids: list[str] = []
        actual_open_records: list[dict[str, Any]] = []
        result_ordering = _ORDERING
        try:
            catalog, config, store_root, record_paths = _validate_catalog_config(
                catalog_file, config_file, ledger_file
            )
            catalog_id = catalog["catalog_id"]
            records = catalog["records"]
            candidate_ids = [row["record_id"] for row in records]
            by_id = {row["record_id"]: row for row in records}
            contents = _validate_live_store(catalog, config, store_root, record_paths)
            result: dict[str, Any]
            if operation == "list":
                kind = query.get("kind")
                if kind is not None and (not isinstance(kind, str) or not kind):
                    _fail("QUERY_INVALID", "kind must be a non-empty opaque string")
                result_ids = [
                    row["record_id"] for row in records if kind is None or row["kind"] == kind
                ]
                result = {"record_ids": result_ids, "count": len(result_ids)}
            elif operation == "metadata":
                requested = query.get("record_ids", [])
                if not isinstance(requested, list) or not all(
                    isinstance(item, str) for item in requested
                ):
                    _fail("QUERY_INVALID", "record_ids must be a list of opaque strings")
                selected = candidate_ids if not requested else sorted(set(requested))
                missing = [record_id for record_id in selected if record_id not in by_id]
                if missing:
                    _fail("RECORD_NOT_FOUND", "one or more opaque record ids do not exist")
                result_ids = selected
                result = {
                    "records": [
                        {field: by_id[record_id][field] for field in _PUBLIC_RECORD_FIELDS}
                        for record_id in selected
                    ],
                    "record_ids": selected,
                    "count": len(selected),
                }
            elif operation == "find":
                needle = query.get("fixed_string")
                kind = query.get("kind")
                if not isinstance(needle, str) or not needle:
                    _fail("QUERY_INVALID", "fixed_string must be a non-empty string")
                if kind is not None and (not isinstance(kind, str) or not kind):
                    _fail("QUERY_INVALID", "kind must be a non-empty opaque string")
                needle_raw = needle.encode("utf-8")
                eligible = [
                    row["record_id"] for row in records if kind is None or row["kind"] == kind
                ]
                candidate_ids = eligible
                match_counts: list[dict[str, Any]] = []
                for record_id in eligible:
                    count = contents[record_id].count(needle_raw)
                    if count:
                        match_counts.append({"record_id": record_id, "count": count})
                result_ids = [row["record_id"] for row in match_counts]
                result = {
                    "record_ids": result_ids,
                    "count": len(result_ids),
                    "match_counts": match_counts,
                    "fixed_string_bytes": len(needle_raw),
                }
            else:
                requested = query.get("record_ids")
                if (
                    not isinstance(requested, list)
                    or not requested
                    or not all(isinstance(item, str) and item for item in requested)
                ):
                    _fail("QUERY_INVALID", "open requires one or more opaque record ids")
                if len(set(requested)) != len(requested):
                    _fail("QUERY_INVALID", "open record ids must not contain duplicates")
                missing = [record_id for record_id in requested if record_id not in by_id]
                if missing:
                    _fail("RECORD_NOT_FOUND", "one or more opaque record ids do not exist")
                opened_before = _opened_unique_ids(rows, catalog_id)
                requested_unique = set(requested)
                if len(opened_before | requested_unique) > catalog["max_open_count"]:
                    _fail("MAX_OPEN_COUNT_EXCEEDED", "open would exceed the frozen unique-id limit")
                result_ordering = "request_order"
                result_ids = list(requested)
                opened: list[dict[str, Any]] = []
                for record_id in requested:
                    raw = contents[record_id]
                    metadata = {field: by_id[record_id][field] for field in _PUBLIC_RECORD_FIELDS}
                    try:
                        content = raw.decode("utf-8")
                        encoding = "utf-8"
                    except UnicodeDecodeError:
                        content = base64.b64encode(raw).decode("ascii")
                        encoding = "base64"
                    opened.append({**metadata, "content_encoding": encoding, "content": content})
                    actual_open_records.append(
                        {
                            "record_id": record_id,
                            "bytes": len(raw),
                            "sha256": _sha(raw),
                        }
                    )
                result = {
                    "records": opened,
                    "record_ids": result_ids,
                    "count": len(result_ids),
                    "max_open_count": catalog["max_open_count"],
                    "opened_unique_count_after": len(opened_before | requested_unique),
                }
            event = _result_event(
                operation_id=operation_id,
                request_entry_sha256=request["entry_sha256"],
                operation=operation,
                query=query,
                catalog_id=catalog_id,
                candidate_ids=candidate_ids,
                result_ids=result_ids,
                result_ordering=result_ordering,
                actual_open_records=actual_open_records,
                status="SUCCESS",
                error=None,
            )
            _append_ledger_event(ledger_file, rows, event)
            return _public_result(
                operation_id=operation_id,
                operation=operation,
                catalog_id=catalog_id,
                result=result,
            )
        except Exception as exc:
            error = _error_from_exception(exc)
            event = _result_event(
                operation_id=operation_id,
                request_entry_sha256=request["entry_sha256"],
                operation=operation,
                query=query,
                catalog_id=catalog_id,
                candidate_ids=candidate_ids,
                result_ids=[],
                result_ordering=result_ordering,
                actual_open_records=[],
                status="REJECTED" if isinstance(exc, ArchiveQueryError) else "ERROR",
                error=error,
            )
            _append_ledger_event(ledger_file, rows, event)
            if isinstance(exc, ArchiveQueryError):
                raise
            raise ArchiveQueryError(error["code"], error["message"]) from exc


def list_records(
    *,
    catalog_path: str | Path,
    config_path: str | Path,
    ledger_path: str | Path,
    kind: str | None = None,
) -> dict[str, Any]:
    return _query_operation(
        operation="list",
        query={"kind": kind},
        catalog_path=catalog_path,
        config_path=config_path,
        ledger_path=ledger_path,
    )


def record_metadata(
    *,
    catalog_path: str | Path,
    config_path: str | Path,
    ledger_path: str | Path,
    record_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return _query_operation(
        operation="metadata",
        query={"record_ids": list(record_ids)},
        catalog_path=catalog_path,
        config_path=config_path,
        ledger_path=ledger_path,
    )


def find_fixed_string(
    *,
    catalog_path: str | Path,
    config_path: str | Path,
    ledger_path: str | Path,
    fixed_string: str,
    kind: str | None = None,
) -> dict[str, Any]:
    return _query_operation(
        operation="find",
        query={"fixed_string": fixed_string, "kind": kind},
        catalog_path=catalog_path,
        config_path=config_path,
        ledger_path=ledger_path,
    )


def open_records(
    *,
    catalog_path: str | Path,
    config_path: str | Path,
    ledger_path: str | Path,
    record_ids: Sequence[str],
) -> dict[str, Any]:
    return _query_operation(
        operation="open",
        query={"record_ids": list(record_ids)},
        catalog_path=catalog_path,
        config_path=config_path,
        ledger_path=ledger_path,
    )


def _error_from_exception(exc: Exception) -> dict[str, str]:
    if isinstance(exc, ArchiveQueryError):
        return {"code": exc.reason_code, "message": str(exc)}
    return {"code": "ARCHIVE_QUERY_INTERNAL_ERROR", "message": "archive query failed internally"}


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--ledger", required=True)
    return parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = _common_parser()
    catalog = subparsers.add_parser("catalog", parents=[common])
    catalog.add_argument("--store-root", required=True)
    catalog.add_argument("--portable-root")
    catalog.add_argument("--max-open-count", type=int, default=3)
    listing = subparsers.add_parser("list", parents=[common])
    listing.add_argument("--kind")
    metadata = subparsers.add_parser("metadata", parents=[common])
    metadata.add_argument("record_ids", nargs="*")
    finding = subparsers.add_parser("find", parents=[common])
    finding.add_argument("fixed_string")
    finding.add_argument("--kind")
    opening = subparsers.add_parser("open", parents=[common])
    opening.add_argument("record_ids", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        common = {
            "catalog_path": args.catalog,
            "config_path": args.config,
            "ledger_path": args.ledger,
        }
        if args.command == "catalog":
            result = catalog_archive(
                store_root=args.store_root,
                portable_root=args.portable_root,
                max_open_count=args.max_open_count,
                **common,
            )
        elif args.command == "list":
            result = list_records(kind=args.kind, **common)
        elif args.command == "metadata":
            result = record_metadata(record_ids=args.record_ids, **common)
        elif args.command == "find":
            result = find_fixed_string(fixed_string=args.fixed_string, kind=args.kind, **common)
        else:
            result = open_records(record_ids=args.record_ids, **common)
        sys.stdout.buffer.write(_canonical_bytes(result))
        return 0
    except ArchiveQueryError as exc:
        payload = {
            "schema": ERROR_SCHEMA,
            "error": {"code": exc.reason_code, "message": str(exc)},
            "authority": False,
            "completion_claim_allowed": False,
        }
        sys.stdout.buffer.write(_canonical_bytes(payload))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
