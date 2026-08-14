"""Mechanical assessment of a matched archive-query canary.

The assessor consumes frozen evidence for baseline, autonomous, random, and
optionally curated arms.  It can identify an interesting or chain-settled
candidate event, but it never emits a scientific, self-evolution, q_t, or
project-level verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

CANARY_SCHEMA = "xinao.research-of-research.archive-query-canary-assessment.v2"
SETTLEMENT_DESCRIPTOR_SCHEMA = "xinao.research-of-research.archive-query-settlement-descriptor.v1"

INVALID_EVIDENCE = "INVALID_EVIDENCE"
MATCHED_COMPARISON_NOT_ASSESSABLE = "MATCHED_COMPARISON_NOT_ASSESSABLE"
NO_QUERY_OR_OPEN = "NO_QUERY_OR_OPEN"
QUERY_WITHOUT_OPEN = "QUERY_WITHOUT_OPEN"
AUTONOMOUS_SELECTION_INVALID = "AUTONOMOUS_SELECTION_INVALID"
NO_DISTINCT_AUTONOMOUS_SELECTION = "NO_DISTINCT_AUTONOMOUS_SELECTION"
INTERESTING_EVENT_ONLY = "INTERESTING_EVENT_ONLY"
CHAIN_SETTLED_CANDIDATE = "CHAIN_SETTLED_CANDIDATE"

PILOT_NO_FIRE = "NO_FIRE"
PILOT_ORDER_FOLLOWING = "ORDER_FOLLOWING"
PILOT_NONTRIVIAL_SELECTION_CANDIDATE = "NONTRIVIAL_SELECTION_CANDIDATE"
PILOT_BYPASS = "BYPASS"
PILOT_LEDGER_INCOMPLETE = "LEDGER_INCOMPLETE"

REQUIRED_ROLES = ("baseline", "autonomous", "random")
OPTIONAL_ROLES = ("curated",)
EXPECTED_OPEN_COUNT = {"baseline": 0, "autonomous": 3, "curated": 3, "random": 3}


class CanaryAssessmentError(RuntimeError):
    """Frozen evidence is malformed, drifting, or outside the canary contract."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise CanaryAssessmentError(reason_code, message)


def _canonical_bytes(value: object, *, newline: bool = True) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + suffix
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bytes(path: Path, *, reason: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        _fail(reason, f"not a regular non-link file: {path}")
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise CanaryAssessmentError(reason, f"cannot read {path}: {exc}") from exc
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field, None) != getattr(after, field, None) for field in identity):
        _fail(reason, f"file changed while being read: {path}")
    if len(raw) != before.st_size:
        _fail(reason, f"file size changed while being read: {path}")
    return raw


def _read_json(path: Path, *, reason: str) -> dict[str, Any]:
    raw = _read_bytes(path, reason=reason)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssessmentError(reason, f"invalid JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(reason, f"JSON value is not an object: {path}")
    return value


def _resolve(value: object, *, anchor: Path, reason: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        _fail(reason, "path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = anchor / path
    return path.resolve()


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _self_seal_valid(value: Mapping[str, Any], field: str) -> bool:
    declared = value.get(field)
    if not isinstance(declared, str) or len(declared) != 64:
        return False
    unsigned = dict(value)
    unsigned.pop(field, None)
    expected = {
        _sha(_canonical_bytes(unsigned)),
        _sha(_canonical_bytes(unsigned, newline=False)),
    }
    return declared.casefold() in expected


def _tree_manifest(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        _fail("WORKSPACE_SNAPSHOT_INVALID", f"not a frozen directory: {root}")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            _fail("WORKSPACE_SNAPSHOT_INVALID", f"snapshot contains a link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail("WORKSPACE_SNAPSHOT_INVALID", f"snapshot contains a non-file: {path}")
        raw = path.read_bytes()
        rows.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": len(raw),
                "sha256": _sha(raw),
            }
        )
    return {"root": str(root), "files": rows, "tree_sha256": _sha(_canonical_bytes(rows))}


def _workspace_root(job: Mapping[str, Any], *, receipt_dir: Path) -> tuple[Path, str]:
    snapshot = job.get("workspace_after_snapshot")
    if isinstance(snapshot, Mapping):
        root = _resolve(
            snapshot.get("root"), anchor=receipt_dir, reason="WORKSPACE_AFTER_SNAPSHOT_INVALID"
        )
        observed = _tree_manifest(root)
        declared = snapshot.get("tree_sha256")
        if not isinstance(declared, str) or observed["tree_sha256"] != declared.casefold():
            _fail("WORKSPACE_AFTER_SNAPSHOT_DRIFT", f"snapshot drift: {root}")
        workspace_after = job.get("workspace_after")
        if isinstance(workspace_after, Mapping) and workspace_after.get("tree_sha256") != declared:
            _fail("WORKSPACE_AFTER_SNAPSHOT_DRIFT", "snapshot is not the recorded after-tree")
        return root, "workspace_after_snapshot"
    if isinstance(snapshot, (str, os.PathLike)):
        root = _resolve(snapshot, anchor=receipt_dir, reason="WORKSPACE_AFTER_SNAPSHOT_INVALID")
        _tree_manifest(root)
        return root, "workspace_after_snapshot"
    root = _resolve(job.get("workspace"), anchor=receipt_dir, reason="WORKSPACE_AFTER_MISSING")
    observed = _tree_manifest(root)
    workspace_after = job.get("workspace_after")
    if isinstance(workspace_after, Mapping):
        declared = workspace_after.get("tree_sha256")
        if isinstance(declared, str) and observed["tree_sha256"] != declared.casefold():
            _fail("WORKSPACE_AFTER_DRIFT", f"legacy workspace drift: {root}")
    return root, "workspace"


def _record_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail("CATALOG_INVALID", "catalog records must be a list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            _fail("CATALOG_INVALID", f"catalog record {index} is not an object")
        record_id = raw.get("record_id", raw.get("id"))
        kind = raw.get("kind")
        size = raw.get("bytes")
        digest = raw.get("sha256")
        if not isinstance(record_id, str) or not record_id or record_id in seen:
            _fail("CATALOG_INVALID", f"invalid or duplicate record id at index {index}")
        if not isinstance(kind, str) or not kind:
            _fail("CATALOG_INVALID", f"record kind is missing: {record_id}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            _fail("CATALOG_INVALID", f"record bytes is invalid: {record_id}")
        if not isinstance(digest, str) or len(digest) != 64:
            _fail("CATALOG_INVALID", f"record sha256 is invalid: {record_id}")
        seen.add(record_id)
        rows.append(
            {
                "record_id": record_id,
                "kind": kind,
                "created_at": raw.get("created_at"),
                "bytes": size,
                "sha256": digest.casefold(),
            }
        )
    if [row["record_id"] for row in rows] != sorted(seen):
        _fail("CATALOG_ORDER_INVALID", "neutral catalog must be ordered by opaque record id")
    return rows


def _catalog_record_path(
    workspace: Path,
    catalog_path: Path,
    record_id: str,
    record_paths: Mapping[str, object],
    *,
    store_relative_path: str,
) -> Path:
    declared = record_paths.get(record_id)
    candidates: list[Path] = []
    if isinstance(declared, str) and declared:
        relative = Path(declared)
        if relative.is_absolute() or ".." in relative.parts:
            _fail("CATALOG_RECORD_PATH_INVALID", f"unsafe record path: {record_id}")
        store_root = (workspace / store_relative_path).resolve()
        candidates.extend(
            (store_root / relative, workspace / relative, catalog_path.parent / relative)
        )
    candidates.append((workspace / store_relative_path / f"{record_id}.bin").resolve())
    resolved = [path.resolve() for path in candidates]
    existing = [
        path
        for path in resolved
        if _contained(path, workspace) and path.is_file() and not path.is_symlink()
    ]
    unique = list(dict.fromkeys(existing))
    if not unique:
        _fail("CATALOG_RECORD_MISSING", f"frozen record is missing: {record_id}")
    return unique[0]


def _validate_private_config(
    workspace: Path,
    *,
    descriptor: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    config_relative = descriptor.get(
        "config_relative_path",
        descriptor.get("private_config_path", "archive/config.json"),
    )
    if not isinstance(config_relative, str) or not config_relative:
        _fail("DESCRIPTOR_CONFIG_INVALID", "config_relative_path is invalid")
    config_path = _resolve(config_relative, anchor=workspace, reason="ARCHIVE_CONFIG_MISSING")
    if not _contained(config_path, workspace):
        _fail("ARCHIVE_CONFIG_PATH_INVALID", "archive config escapes frozen workspace")
    raw = _read_bytes(config_path, reason="ARCHIVE_CONFIG_MISSING")
    expected = descriptor.get("expected_config_sha256")
    if not isinstance(expected, str) or _sha(raw) != expected.casefold():
        _fail("ARCHIVE_CONFIG_DRIFT", "private archive config differs from descriptor")
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssessmentError("ARCHIVE_CONFIG_INVALID", "invalid private config") from exc
    if not isinstance(config, dict) or not _self_seal_valid(config, "config_sha256"):
        _fail("ARCHIVE_CONFIG_SEAL_INVALID", "private archive config seal is invalid")
    if config.get("authority") is not False or config.get("completion_claim_allowed") is not False:
        _fail("ARCHIVE_CONFIG_BOUNDARY_INVALID", "private config boundary fields are invalid")
    if (
        config.get("catalog_id") != catalog.get("catalog_id")
        or config.get("catalog_sha256") != catalog.get("catalog_sha256")
        or config.get("config_id") != catalog.get("config_id")
        or config.get("max_open_count") != catalog.get("max_open_count")
        or config.get("ordering") != catalog.get("ordering")
    ):
        _fail("ARCHIVE_CONFIG_CATALOG_MISMATCH", "private config is not bound to catalog")
    provenance = config.get("provenance")
    if not isinstance(provenance, Mapping) or not isinstance(provenance.get("records"), list):
        _fail("ARCHIVE_CONFIG_INVALID", "private config record provenance is missing")
    record_paths: dict[str, str] = {}
    for row in provenance["records"]:
        if not isinstance(row, Mapping) or set(row) != {"record_id", "store_relative_path"}:
            _fail("ARCHIVE_CONFIG_INVALID", "private config record row is invalid")
        record_id = row.get("record_id")
        relative = row.get("store_relative_path")
        if (
            not isinstance(record_id, str)
            or record_id in record_paths
            or not isinstance(relative, str)
            or not relative
        ):
            _fail("ARCHIVE_CONFIG_INVALID", "private config record identity is invalid")
        record_paths[record_id] = relative
    if set(record_paths) != {row["record_id"] for row in catalog["records"]}:
        _fail("ARCHIVE_CONFIG_INVALID", "private config does not cover catalog records")
    catalog_identity = {
        "records": catalog["records"],
        "max_open_count": catalog["max_open_count"],
        "ordering": catalog["ordering"],
        "kind_policy": config.get("kind_policy"),
        "created_at_policy": config.get("created_at_policy"),
        "record_identity_policy": config.get("record_identity_policy"),
    }
    if catalog.get("catalog_id") != _sha(_canonical_bytes(catalog_identity)):
        _fail("CATALOG_ID_INVALID", "catalog identity does not match frozen records")
    binding_mode = config.get("binding_mode", "absolute_paths_v1")
    if binding_mode == "portable_relative_paths_v1":
        field_names = (
            "store_relative_path",
            "catalog_relative_path",
            "config_relative_path",
            "query_ledger_relative_path",
        )
        if any(
            not isinstance(provenance.get(field), str) or not provenance.get(field)
            for field in field_names
        ):
            _fail("ARCHIVE_CONFIG_INVALID", "portable binding paths are missing")
        binding = {"mode": binding_mode, **{field: provenance[field] for field in field_names}}
        ledger_identity = {
            "binding_mode": binding_mode,
            "query_ledger_relative_path": provenance["query_ledger_relative_path"],
        }
        query_ledger_path = provenance["query_ledger_relative_path"]
    elif binding_mode == "absolute_paths_v1":
        field_names = ("store_root", "catalog_path", "config_path", "query_ledger_path")
        if any(
            not isinstance(provenance.get(field), str) or not provenance.get(field)
            for field in field_names
        ):
            _fail("ARCHIVE_CONFIG_INVALID", "absolute binding paths are missing")
        binding = {"mode": binding_mode, **{field: provenance[field] for field in field_names}}
        ledger_identity = {
            "binding_mode": binding_mode,
            "query_ledger_path": provenance["query_ledger_path"],
        }
        query_ledger_path = provenance["query_ledger_path"]
    else:
        _fail("ARCHIVE_CONFIG_INVALID", "private config binding mode is unsupported")
    ledger_id = _sha(_canonical_bytes(ledger_identity))
    if config.get("query_ledger_id") != ledger_id:
        _fail("ARCHIVE_CONFIG_ID_INVALID", "query ledger identity is invalid")
    config_identity = {
        "catalog_id": config["catalog_id"],
        "query_ledger_id": config["query_ledger_id"],
        "max_open_count": config["max_open_count"],
        "ordering": config["ordering"],
        "record_identity_policy": config.get("record_identity_policy"),
        "binding": binding,
        "record_paths": record_paths,
        "allowed_invocation_shapes": config.get("allowed_invocation_shapes"),
    }
    if config.get("config_id") != _sha(_canonical_bytes(config_identity)):
        _fail("ARCHIVE_CONFIG_ID_INVALID", "private config identity is invalid")
    return {
        "path": str(config_path),
        "sha256": _sha(raw),
        "record_paths": record_paths,
        "query_ledger_path": query_ledger_path,
        "allowed_invocation_shapes": config.get("allowed_invocation_shapes"),
    }


def _validate_catalog(workspace: Path, *, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    path = (workspace / "archive" / "catalog.json").resolve()
    if not _contained(path, workspace):
        _fail("CATALOG_PATH_INVALID", "catalog escapes the frozen workspace")
    raw = _read_bytes(path, reason="CATALOG_MISSING")
    digest = _sha(raw)
    expected_sha256 = descriptor.get("expected_catalog_sha256", descriptor.get("catalog_sha256"))
    if not isinstance(expected_sha256, str) or digest != expected_sha256.casefold():
        _fail("CATALOG_DRIFT", f"catalog differs from settlement descriptor: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssessmentError("CATALOG_INVALID", f"invalid catalog: {path}") from exc
    expected_max_open_count = 0 if descriptor.get("arm_role") == "baseline" else 3
    if isinstance(value, list):
        rows = _record_rows(value)
        catalog_id = f"sha256:{_sha(_canonical_bytes(value))}"
        config: Mapping[str, Any] = {
            "max_open_count": expected_max_open_count,
            "ordering": "record_id_ascending",
        }
        private_config: dict[str, Any] | None = None
        record_paths: Mapping[str, object] = {}
        query_ledger_path: object = None
    elif isinstance(value, Mapping):
        if value.get("authority") not in (None, False):
            _fail("CATALOG_BOUNDARY_INVALID", "catalog cannot claim authority")
        if not _self_seal_valid(value, "catalog_sha256"):
            _fail("CATALOG_SEAL_INVALID", "catalog self-seal is invalid")
        rows = _record_rows(value.get("records"))
        catalog_id = value.get("catalog_id")
        config = {
            "max_open_count": value.get("max_open_count"),
            "ordering": value.get("ordering"),
        }
        if not isinstance(catalog_id, str) or not catalog_id:
            _fail("CATALOG_ID_INVALID", "catalog_id is missing")
        if (
            config.get("max_open_count") != expected_max_open_count
            or config.get("ordering") != "record_id_ascending"
        ):
            _fail(
                "CATALOG_CONFIG_INVALID",
                "catalog query bounds differ from the arm's frozen query contract",
            )
        private_config = _validate_private_config(workspace, descriptor=descriptor, catalog=value)
        record_paths = private_config["record_paths"]
        query_ledger_path = private_config["query_ledger_path"]
    else:
        _fail("CATALOG_INVALID", "catalog must be an object or a legacy neutral list")
    store_relative_path = _descriptor_value(descriptor, "store_relative_path", "trajectory")
    if store_relative_path is None:
        store_relative_path = descriptor.get("backing_store_relative_path")
    if not isinstance(store_relative_path, str) or not store_relative_path:
        _fail("DESCRIPTOR_TRAJECTORY_INVALID", "store_relative_path is missing")
    resolved_paths: dict[str, str] = {}
    blob_names: list[str] = []
    for row in rows:
        record_path = _catalog_record_path(
            workspace,
            path,
            row["record_id"],
            record_paths,
            store_relative_path=store_relative_path,
        )
        record_raw = _read_bytes(record_path, reason="CATALOG_RECORD_MISSING")
        if len(record_raw) != row["bytes"] or _sha(record_raw) != row["sha256"]:
            _fail("CATALOG_RECORD_DRIFT", f"record bytes drift: {row['record_id']}")
        resolved_paths[row["record_id"]] = str(record_path)
        blob_names.append(record_path.name)
    return {
        "path": str(path),
        "sha256": digest,
        "catalog_id": catalog_id,
        "records": rows,
        "record_ids": [row["record_id"] for row in rows],
        "record_paths": resolved_paths,
        "record_blob_names": sorted(blob_names),
        "query_ledger_path": query_ledger_path,
        "config": dict(config),
        "private_config": private_config,
    }


def _query_ledger_path(workspace: Path, catalog: Mapping[str, Any]) -> Path:
    declared = catalog.get("query_ledger_path")
    candidates: list[Path] = []
    if isinstance(declared, str) and declared:
        candidate = Path(declared)
        if not candidate.is_absolute():
            candidates.extend((workspace / candidate, workspace / "archive" / candidate))
    candidates.extend(
        (
            workspace / "archive" / "query-ledger.jsonl",
            workspace / "query_log.jsonl",
        )
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if _contained(resolved, workspace) and resolved.exists():
            return resolved
    return (workspace / "archive" / "query-ledger.jsonl").resolve()


def _validate_query_ledger(workspace: Path, catalog: Mapping[str, Any]) -> dict[str, Any]:
    path = _query_ledger_path(workspace, catalog)
    if not path.exists():
        _fail("QUERY_LEDGER_INCOMPLETE", f"query ledger is missing: {path}")
    raw = _read_bytes(path, reason="QUERY_LEDGER_INVALID")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanaryAssessmentError("QUERY_LEDGER_INVALID", "query ledger is not UTF-8") from exc
    events: list[dict[str, Any]] = []
    opened: list[str] = []
    known = set(catalog["record_ids"])
    metadata = {row["record_id"]: row for row in catalog["records"]}
    previous: str | None = None
    pending: dict[str, str] = {}
    completed_operation_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            _fail("QUERY_LEDGER_INVALID", f"blank ledger line: {line_number}")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CanaryAssessmentError(
                "QUERY_LEDGER_INVALID", f"invalid ledger line {line_number}"
            ) from exc
        if not isinstance(event, dict):
            _fail("QUERY_LEDGER_INVALID", f"ledger line is not an object: {line_number}")
        if event.get("sequence") != line_number:
            _fail("QUERY_LEDGER_SEQUENCE_INVALID", f"sequence mismatch at line {line_number}")
        if event.get("schema") != "xinao.research-of-research.archive-query-ledger-event.v1":
            _fail("QUERY_LEDGER_SCHEMA_INVALID", f"schema mismatch at line {line_number}")
        if (
            event.get("authority") is not False
            or event.get("completion_claim_allowed") is not False
        ):
            _fail("QUERY_LEDGER_BOUNDARY_INVALID", f"boundary mismatch at line {line_number}")
        if event.get("previous_entry_sha256") != previous:
            _fail("QUERY_LEDGER_CHAIN_INVALID", f"chain mismatch at line {line_number}")
        if not _self_seal_valid(event, "entry_sha256"):
            _fail("QUERY_LEDGER_SEAL_INVALID", f"entry seal mismatch at line {line_number}")
        previous = str(event["entry_sha256"]).casefold()
        operation = event.get("operation")
        if operation not in {"catalog", "list", "metadata", "find", "open"}:
            _fail("QUERY_LEDGER_OPERATION_INVALID", f"operation mismatch at line {line_number}")
        operation_id = event.get("operation_id")
        phase = event.get("phase")
        if not isinstance(operation_id, str) or not operation_id:
            _fail("QUERY_LEDGER_ID_INVALID", f"operation_id mismatch at line {line_number}")
        if phase == "request":
            if (
                operation_id in pending
                or operation_id in completed_operation_ids
                or event.get("status") != "STARTED"
                or event.get("catalog_id") is not None
                or event.get("request_entry_sha256") is not None
            ):
                _fail("QUERY_LEDGER_REQUEST_INVALID", f"request mismatch at line {line_number}")
            pending[operation_id] = str(event["entry_sha256"])
        elif phase == "result":
            request_sha = pending.pop(operation_id, None)
            if request_sha is None or event.get("request_entry_sha256") != request_sha:
                _fail("QUERY_LEDGER_PAIR_INVALID", f"result pair mismatch at line {line_number}")
            if event.get("status") not in {"SUCCESS", "REJECTED", "ERROR"}:
                _fail(
                    "QUERY_LEDGER_RESULT_INVALID", f"result status mismatch at line {line_number}"
                )
            if (
                event.get("status") == "SUCCESS"
                and event.get("catalog_id") != catalog["catalog_id"]
            ):
                _fail("QUERY_LEDGER_CATALOG_DRIFT", f"catalog mismatch at line {line_number}")
            completed_operation_ids.add(operation_id)
        else:
            _fail("QUERY_LEDGER_PHASE_INVALID", f"phase mismatch at line {line_number}")
        actual_open = event.get("actual_open")
        if not isinstance(actual_open, Mapping):
            _fail("QUERY_LEDGER_OPEN_INVALID", f"actual_open missing at line {line_number}")
        record_ids = actual_open.get("record_ids")
        opened_records = actual_open.get("records")
        count = actual_open.get("count")
        if not isinstance(record_ids, list) or any(
            not isinstance(record_id, str) or record_id not in known for record_id in record_ids
        ):
            _fail("QUERY_LEDGER_OPEN_INVALID", f"unknown open id at line {line_number}")
        if (
            not isinstance(opened_records, list)
            or count != len(record_ids)
            or count != len(opened_records)
        ):
            _fail("QUERY_LEDGER_OPEN_INVALID", f"open count mismatch at line {line_number}")
        for record_id, opened_record in zip(record_ids, opened_records, strict=True):
            if (
                not isinstance(opened_record, Mapping)
                or opened_record.get("record_id") != record_id
                or opened_record.get("bytes") != metadata[record_id]["bytes"]
                or opened_record.get("sha256") != metadata[record_id]["sha256"]
            ):
                _fail("QUERY_LEDGER_OPEN_INVALID", f"opened record mismatch at line {line_number}")
        result_ids = event.get("result_record_ids")
        if result_ids is not None and (
            not isinstance(result_ids, list)
            or any(
                not isinstance(record_id, str) or record_id not in known for record_id in result_ids
            )
        ):
            _fail("QUERY_LEDGER_RESULT_INVALID", f"result ids mismatch at line {line_number}")
        if event.get("result_count") is not None and event.get("result_count") != len(
            result_ids or []
        ):
            _fail("QUERY_LEDGER_RESULT_INVALID", f"result count mismatch at line {line_number}")
        if (
            operation != "open" or phase != "result" or event.get("status") != "SUCCESS"
        ) and record_ids:
            _fail(
                "QUERY_LEDGER_OPEN_INVALID", f"non-open event opened records at line {line_number}"
            )
        opened.extend(record_ids)
        if len(set(opened)) > 3:
            _fail("QUERY_LEDGER_OPEN_LIMIT_EXCEEDED", "query ledger exceeds three unique opens")
        events.append(event)
    if pending:
        _fail("QUERY_LEDGER_INCOMPLETE", "query ledger ends with an unmatched STARTED event")
    return {
        "path": str(path),
        "sha256": _sha(raw),
        "events": events,
        "open_order": opened,
        "model_query_event_count": sum(
            1
            for event in events
            if event.get("phase") == "request" and event.get("operation") != "catalog"
        ),
    }


def _trajectory(job: Mapping[str, Any], *, receipt_dir: Path) -> tuple[Path, bytes, str]:
    index = job.get("trajectory_index")
    if not isinstance(index, Mapping):
        _fail("TRAJECTORY_INDEX_INVALID", "trajectory_index is missing")
    path = _resolve(index.get("raw_path"), anchor=receipt_dir, reason="TRAJECTORY_MISSING")
    raw = _read_bytes(path, reason="TRAJECTORY_MISSING")
    digest = _sha(raw)
    declared = index.get("raw_sha256")
    if not isinstance(declared, str) or digest != declared.casefold():
        _fail("TRAJECTORY_DRIFT", f"raw trajectory drift: {path}")
    return path, raw, digest


def _command_strings(value: object) -> list[str]:
    commands: list[str] = []
    if isinstance(value, Mapping):
        type_value = str(value.get("type", "")).casefold()
        name_value = str(value.get("name", value.get("tool", ""))).casefold()
        is_call = any(
            token in type_value
            for token in ("function_call", "custom_tool_call", "tool_call", "command_execution")
        ) or name_value in {"exec_command", "shell", "powershell", "command_execution"}
        if is_call:
            if "mcp_tool_call" in type_value:
                server_value = str(value.get("server", "")).casefold()
                tool_value = str(value.get("tool", value.get("name", ""))).casefold()
                if server_value and tool_value:
                    commands.append(f"mcp__{server_value}__{tool_value}")
            if name_value:
                commands.append(name_value)
            for key in ("arguments", "input", "command", "cmd"):
                raw = value.get(key)
                if isinstance(raw, str):
                    commands.append(raw)
                    try:
                        decoded = json.loads(raw)
                    except json.JSONDecodeError:
                        decoded = None
                    if decoded is not None:
                        commands.extend(_all_strings(decoded))
                elif raw is not None:
                    commands.extend(_all_strings(raw))
        for child in value.values():
            commands.extend(_command_strings(child))
    elif isinstance(value, list):
        for child in value:
            commands.extend(_command_strings(child))
    return commands


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for child in value.values() for text in _all_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _all_strings(child)]
    return []


def _normalize_command(value: str) -> str:
    normalized = value.casefold().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return " ".join(normalized.split())


def _audit_trajectory(
    raw: bytes,
    *,
    allowed_invocation_prefix: Sequence[str],
    store_relative_path: str,
    record_blob_names: Sequence[str],
    query_event_count: int,
    bypass_is_error: bool = True,
) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanaryAssessmentError("TRAJECTORY_INVALID", "trajectory is not UTF-8") from exc
    commands: list[str] = []
    parsed_event_count = 0
    preamble_line_count = 0
    json_stream_started = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if not json_stream_started and not line.lstrip().startswith(("{", "[")):
                preamble_line_count += 1
                continue
            raise CanaryAssessmentError(
                "TRAJECTORY_INVALID", f"invalid JSONL line {line_number}"
            ) from exc
        json_stream_started = True
        parsed_event_count += 1
        commands.extend(_command_strings(event))
    if parsed_event_count == 0:
        _fail("TRAJECTORY_INVALID", "trajectory contains no JSON events")
    normalized_commands = [_normalize_command(command) for command in commands]
    allowed_phrase = _normalize_command(" ".join(allowed_invocation_prefix))
    allowed_seen = any(
        allowed_phrase and allowed_phrase in command for command in normalized_commands
    )
    store_token = _normalize_command(store_relative_path).rstrip("/")
    blob_tokens = {name.casefold() for name in record_blob_names if name}
    bypass_commands = []
    for command in normalized_commands:
        store_hit = bool(store_token and store_token in command)
        blob_hit = any(f"/{blob}" in command or f" {blob}" in command for blob in blob_tokens)
        if store_hit or blob_hit:
            bypass_commands.append(command)
    if bypass_commands and bypass_is_error:
        _fail("DIRECT_ARCHIVE_BYPASS", "trajectory directly addressed the archive backing store")
    if query_event_count and not allowed_seen:
        _fail(
            "QUERY_LEDGER_WITHOUT_ALLOWED_INVOCATION",
            "query ledger has events but no allowed archive invocation is visible",
        )
    return {
        "command_count": len(normalized_commands),
        "parsed_event_count": parsed_event_count,
        "preamble_line_count": preamble_line_count,
        "allowed_invocation_seen": allowed_seen,
        "direct_archive_bypass": bool(bypass_commands),
    }


def _descriptor_location(
    job: Mapping[str, Any], *, explicit: Path | None, receipt_dir: Path
) -> tuple[Path, str | None]:
    if explicit is not None:
        return explicit.expanduser().resolve(), None
    descriptor = job.get("settlement_descriptor")
    if isinstance(descriptor, Mapping):
        return (
            _resolve(descriptor.get("path"), anchor=receipt_dir, reason="DESCRIPTOR_MISSING"),
            descriptor.get("sha256") if isinstance(descriptor.get("sha256"), str) else None,
        )
    return (
        _resolve(
            job.get("settlement_descriptor_path"),
            anchor=receipt_dir,
            reason="DESCRIPTOR_MISSING",
        ),
        (
            job.get("settlement_descriptor_sha256")
            if isinstance(job.get("settlement_descriptor_sha256"), str)
            else None
        ),
    )


def _load_descriptor(
    path: Path,
    *,
    expected_file_sha256: str | None,
    role: str,
    variant_id: str,
    replicate: int,
    run_id: object,
) -> dict[str, Any]:
    raw = _read_bytes(path, reason="DESCRIPTOR_MISSING")
    digest = _sha(raw)
    if expected_file_sha256 is not None and digest != expected_file_sha256.casefold():
        _fail("DESCRIPTOR_DRIFT", f"settlement descriptor drift: {path}")
    try:
        descriptor = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssessmentError("DESCRIPTOR_INVALID", f"invalid descriptor: {path}") from exc
    if not isinstance(descriptor, dict):
        _fail("DESCRIPTOR_INVALID", "settlement descriptor must be an object")
    if descriptor.get("schema") != SETTLEMENT_DESCRIPTOR_SCHEMA:
        _fail("DESCRIPTOR_SCHEMA_INVALID", f"unsupported descriptor schema: {path}")
    if (
        descriptor.get("authority") is not False
        or descriptor.get("completion_claim_allowed") is not False
    ):
        _fail("DESCRIPTOR_BOUNDARY_INVALID", f"invalid descriptor boundaries: {path}")
    if not _self_seal_valid(descriptor, "descriptor_sha256"):
        _fail("DESCRIPTOR_SEAL_INVALID", f"invalid descriptor seal: {path}")
    identity = {
        "arm_role": role,
        "variant_id": variant_id,
        "replicate": replicate,
        "run_id": run_id,
    }
    for key, expected in identity.items():
        if descriptor.get(key) != expected:
            _fail("DESCRIPTOR_IDENTITY_INVALID", f"descriptor {key} mismatch: {path}")
    descriptor["path"] = str(path)
    descriptor["file_sha256"] = digest
    return descriptor


def _find_cell_directory(receipt_path: Path) -> Path:
    for parent in receipt_path.parents:
        if all(
            (parent / name).is_file()
            for name in ("cell.json", "preregistration.json", "source_map.json")
        ):
            return parent
    _fail("CELL_DIRECTORY_MISSING", "run receipt is not beneath a frozen cell directory")


def _write_once(path: Path, raw: bytes) -> str:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.is_symlink():
            _fail("DESCRIPTOR_OUTPUT_CONFLICT", "descriptor output is not a regular file")
        if path.read_bytes() == raw:
            return "reused"
        _fail("DESCRIPTOR_OUTPUT_CONFLICT", "descriptor output already binds different bytes")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return "created"


def prepare_instrument_pilot_descriptor(
    run_receipt_path: Path,
    output_path: Path,
    *,
    autonomous_variant: str = "autonomous",
) -> dict[str, Any]:
    """Bind one sealed pilot run to its frozen cell without adding a scientific verdict."""

    receipt_path = Path(run_receipt_path).expanduser().resolve()
    receipt = _read_json(receipt_path, reason="RUN_RECEIPT_INVALID")
    if receipt.get("status") != "SEALED" or not _self_seal_valid(receipt, "receipt_sha256"):
        _fail("RUN_NOT_SEALED", "pilot descriptor preparation requires one sealed run")
    if (
        receipt.get("authority") is not False
        or receipt.get("completion_claim_allowed") is not False
    ):
        _fail("RUN_BOUNDARY_INVALID", "run receipt boundary fields are invalid")
    jobs = receipt.get("jobs")
    if not isinstance(jobs, list):
        _fail("PILOT_JOB_SET_INVALID", "pilot run jobs must be a list")
    selected = [
        row
        for row in jobs
        if isinstance(row, Mapping) and row.get("variant_id") == autonomous_variant
    ]
    if len(selected) != 1 or selected[0].get("exit_code") not in (None, 0):
        _fail("PILOT_JOB_SET_INVALID", "pilot requires one successful autonomous job")
    job = selected[0]
    replicate = job.get("replicate")
    if not isinstance(replicate, int) or isinstance(replicate, bool) or replicate < 1:
        _fail("RUN_JOB_IDENTITY_INVALID", "pilot replicate is invalid")

    cell_dir = _find_cell_directory(receipt_path)
    from services.research_of_research.cell import verify_cell

    frozen = verify_cell(cell_dir, include_runs=False)
    if not frozen.get("ok"):
        _fail("CELL_DRIFT", "frozen cell inputs failed verification")
    cell = _read_json(cell_dir / "cell.json", reason="CELL_INVALID")
    spec = _read_json(cell_dir / "preregistration.json", reason="CELL_INVALID")
    source_map = _read_json(cell_dir / "source_map.json", reason="CELL_INVALID")
    if receipt.get("cell_id") != cell.get("cell_id") or receipt.get("cell_sha256") != cell.get(
        "cell_sha256"
    ):
        _fail("RUN_CELL_IDENTITY_DRIFT", "run receipt differs from its frozen cell")
    observables = spec.get("observables")
    canary_contract = (
        observables.get("archive_query_canary") if isinstance(observables, Mapping) else None
    )
    if (
        not isinstance(canary_contract, Mapping)
        or canary_contract.get("stage") != "instrument-pilot"
    ):
        _fail("PILOT_CONTRACT_MISSING", "frozen cell has no instrument-pilot contract")
    source_variants = source_map.get("variants")
    if not isinstance(source_variants, list):
        _fail("CELL_INVALID", "frozen source map has no variants")
    frozen_variants = [
        row
        for row in source_variants
        if isinstance(row, Mapping) and row.get("id") == autonomous_variant
    ]
    if len(frozen_variants) != 1:
        _fail("PILOT_CONTRACT_MISSING", "autonomous variant is not uniquely frozen")
    frozen_variant = frozen_variants[0]
    frozen_seed = frozen_variant.get("workspace_seed")
    workspace_before = job.get("workspace_before")
    if (
        not isinstance(frozen_seed, Mapping)
        or not isinstance(workspace_before, Mapping)
        or job.get("workspace_seed_tree_sha256") != frozen_seed.get("tree_sha256")
        or workspace_before.get("tree_sha256") != frozen_seed.get("tree_sha256")
    ):
        _fail("RUN_WORKSPACE_SEED_DRIFT", "pilot job did not start from its frozen arm seed")

    workspace, _workspace_source = _workspace_root(job, receipt_dir=receipt_path.parent)
    catalog_relative = str(canary_contract.get("catalog_path", "archive/catalog.json"))
    config_relative = str(canary_contract.get("private_config_path", "archive/private/config.json"))
    store_relative = str(canary_contract.get("backing_store_relative_path", "archive/store"))
    catalog_path = _resolve(catalog_relative, anchor=workspace, reason="CATALOG_MISSING")
    config_path = _resolve(config_relative, anchor=workspace, reason="ARCHIVE_CONFIG_MISSING")
    if not _contained(catalog_path, workspace) or not _contained(config_path, workspace):
        _fail("PILOT_CONTRACT_INVALID", "pilot archive paths escape the workspace")
    seed_root = _resolve(frozen_seed.get("root"), anchor=cell_dir, reason="WORKSPACE_SEED_MISSING")
    for relative, observed in (
        (catalog_relative, catalog_path),
        (config_relative, config_path),
    ):
        frozen_path = _resolve(relative, anchor=seed_root, reason="WORKSPACE_SEED_MISSING")
        if _read_bytes(frozen_path, reason="WORKSPACE_SEED_MISSING") != _read_bytes(
            observed, reason="PILOT_ARCHIVE_MISSING"
        ):
            _fail("PILOT_ARCHIVE_DRIFT", f"pilot archive input changed after freeze: {relative}")

    catalog_raw = _read_bytes(catalog_path, reason="CATALOG_MISSING")
    config_raw = _read_bytes(config_path, reason="ARCHIVE_CONFIG_MISSING")
    try:
        catalog_value = json.loads(catalog_raw.decode("utf-8"))
        config_value = json.loads(config_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssessmentError(
            "PILOT_ARCHIVE_INVALID", "pilot archive JSON is invalid"
        ) from exc
    if not isinstance(catalog_value, Mapping) or not isinstance(config_value, Mapping):
        _fail("PILOT_ARCHIVE_INVALID", "pilot catalog and config must be objects")
    catalog_rows = _record_rows(catalog_value.get("records"))
    full_pool = canary_contract.get("full_pool_record_identities")
    expected_pool = _pool_identity_map(full_pool)
    observed_pool = {row["record_id"]: (row["bytes"], row["sha256"]) for row in catalog_rows}
    if observed_pool != expected_pool:
        _fail("PILOT_CATALOG_NOT_FULL_POOL", "pilot catalog differs from frozen full pool")
    full_pool_id = canary_contract.get("full_pool_id")
    if full_pool_id != f"sha256:{catalog_value.get('catalog_id')}":
        _fail("PILOT_CATALOG_NOT_FULL_POOL", "pilot full-pool identity is invalid")
    provenance = config_value.get("provenance")
    provenance_rows = provenance.get("records") if isinstance(provenance, Mapping) else None
    if not isinstance(provenance_rows, list):
        _fail("PILOT_ARCHIVE_INVALID", "pilot private config lacks record provenance")
    blob_names = sorted(
        Path(str(row.get("store_relative_path"))).name
        for row in provenance_rows
        if isinstance(row, Mapping)
    )
    if len(blob_names) != len(catalog_rows):
        _fail("PILOT_ARCHIVE_INVALID", "pilot private config record coverage is incomplete")
    trajectory_path, _trajectory_raw, trajectory_sha = _trajectory(
        job, receipt_dir=receipt_path.parent
    )
    allowed_prefix = canary_contract.get("allowed_query_tool_invocation_prefix")
    if not isinstance(allowed_prefix, list) or any(
        not isinstance(item, str) or not item for item in allowed_prefix
    ):
        _fail("PILOT_CONTRACT_INVALID", "pilot query invocation prefix is invalid")
    draft: dict[str, Any] = {
        "schema": SETTLEMENT_DESCRIPTOR_SCHEMA,
        "authority": False,
        "completion_claim_allowed": False,
        "stage": "instrument-pilot",
        "arm_role": "autonomous",
        "variant_id": autonomous_variant,
        "replicate": replicate,
        "run_id": receipt.get("run_id"),
        "full_pool_id": full_pool_id,
        "full_pool_record_identities": full_pool,
        "expected_catalog_sha256": _sha(catalog_raw),
        "expected_config_sha256": _sha(config_raw),
        "config_relative_path": config_relative,
        "visible_history_ids": [row["record_id"] for row in catalog_rows],
        "required_open_count": 0,
        "selection": {"method": "full_opaque_catalog"},
        "trajectory": {
            "path": str(trajectory_path),
            "sha256": trajectory_sha,
            "allowed_invocation_prefix": list(allowed_prefix),
            "store_relative_path": store_relative,
            "record_blob_names": blob_names,
        },
        "last_message_claims": {},
        "held_out": {"status": "PENDING"},
    }
    # Reuse the assessor's strict catalog/config/store validation before sealing
    # the mechanically prepared descriptor.
    _validate_catalog(workspace, descriptor=draft)
    descriptor = {**draft, "descriptor_sha256": _sha(_canonical_bytes(draft))}
    disposition = _write_once(Path(output_path), _canonical_bytes(descriptor))
    return {
        **descriptor,
        "output_path": str(Path(output_path).expanduser().resolve()),
        "disposition": disposition,
    }


def _last_message(job: Mapping[str, Any], *, receipt_dir: Path) -> tuple[Path, bytes, str]:
    path = _resolve(job.get("last_message_path"), anchor=receipt_dir, reason="LAST_MESSAGE_MISSING")
    raw = _read_bytes(path, reason="LAST_MESSAGE_MISSING")
    digest = _sha(raw)
    declared = job.get("last_message_sha256")
    if not isinstance(declared, str) or digest != declared.casefold():
        _fail("LAST_MESSAGE_DRIFT", f"last message drift: {path}")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanaryAssessmentError("LAST_MESSAGE_INVALID", "last message is not UTF-8") from exc
    return path, raw, digest


def _span_annotation(
    value: object,
    *,
    output_path: Path,
    output_raw: bytes,
    output_sha256: str,
    claim_name: str,
) -> dict[str, Any]:
    if value is None:
        return {"status": "ABSENT", "claim_name": claim_name}
    if not isinstance(value, Mapping):
        _fail("CLAIM_ANNOTATION_INVALID", f"{claim_name} annotation must be an object")
    if value.get("present") is not True:
        return {"status": "ABSENT", "claim_name": claim_name}
    if value.get("authority") is not False:
        _fail("CLAIM_ANNOTATION_INVALID", f"{claim_name} annotation cannot claim authority")
    annotated_path = _resolve(
        value.get("output_path"), anchor=output_path.parent, reason="CLAIM_ANNOTATION_INVALID"
    )
    if annotated_path != output_path or value.get("output_sha256") != output_sha256:
        _fail("CLAIM_OUTPUT_IDENTITY_INVALID", f"{claim_name} output identity mismatch")
    start = value.get("byte_start")
    end = value.get("byte_end")
    line_start = value.get("line_start")
    line_end = value.get("line_end")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not 0 <= start < end <= len(output_raw)
        or not isinstance(line_start, int)
        or not isinstance(line_end, int)
    ):
        _fail("CLAIM_SPAN_INVALID", f"{claim_name} has an invalid byte/line span")
    span = output_raw[start:end]
    try:
        span.decode("utf-8")
        output_raw[:start].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanaryAssessmentError(
            "CLAIM_SPAN_INVALID", f"{claim_name} span is not on UTF-8 boundaries"
        ) from exc
    observed_start_line = output_raw[:start].count(b"\n") + 1
    observed_end_line = output_raw[: end - 1].count(b"\n") + 1
    if (line_start, line_end) != (observed_start_line, observed_end_line):
        _fail("CLAIM_SPAN_INVALID", f"{claim_name} line span does not match byte span")
    span_sha256 = _sha(span)
    if value.get("span_sha256") != span_sha256:
        _fail("CLAIM_SPAN_INVALID", f"{claim_name} span hash mismatch")
    return {
        "status": "ANNOTATED_CANDIDATE",
        "claim_name": claim_name,
        "output_path": str(output_path),
        "output_sha256": output_sha256,
        "byte_start": start,
        "byte_end": end,
        "line_start": line_start,
        "line_end": line_end,
        "span_sha256": span_sha256,
        "prediction_id": value.get("prediction_id"),
        "semantic_verification": None,
    }


def _file_identity(value: Mapping[str, Any], prefix: str, *, anchor: Path) -> tuple[Path, bytes]:
    path = _resolve(value.get(f"{prefix}_path"), anchor=anchor, reason="HELD_OUT_EVIDENCE_INVALID")
    raw = _read_bytes(path, reason="HELD_OUT_EVIDENCE_INVALID")
    declared = value.get(f"{prefix}_sha256")
    if not isinstance(declared, str) or _sha(raw) != declared.casefold():
        _fail("HELD_OUT_EVIDENCE_DRIFT", f"held-out {prefix} drift: {path}")
    return path, raw


def _held_out_settlement(
    value: object,
    *,
    descriptor_path: Path,
    current_run_id: object,
    prediction: Mapping[str, Any],
) -> dict[str, Any]:
    if value is None:
        return {"status": "PENDING", "machine_verified": False}
    if not isinstance(value, Mapping):
        _fail("HELD_OUT_DESCRIPTOR_INVALID", "held_out must be an object")
    status = value.get("status")
    if status == "PENDING":
        return {"status": "PENDING", "machine_verified": False}
    if status != "SATISFIED":
        _fail("HELD_OUT_DESCRIPTOR_INVALID", "held_out status must be PENDING or SATISFIED")
    if prediction.get("status") != "ANNOTATED_CANDIDATE" or not isinstance(
        prediction.get("prediction_id"), str
    ):
        _fail("HELD_OUT_PREDICTION_UNBOUND", "satisfied held-out lacks a bound prediction")
    anchor = descriptor_path.parent
    prereg_path, prereg_raw = _file_identity(value, "preregistration", anchor=anchor)
    receipt_path, receipt_raw = _file_identity(value, "run_receipt", anchor=anchor)
    trajectory_path, trajectory_raw = _file_identity(value, "trajectory", anchor=anchor)
    try:
        prereg = json.loads(prereg_raw.decode("utf-8"))
        receipt = json.loads(receipt_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryAssessmentError("HELD_OUT_EVIDENCE_INVALID", "invalid held-out JSON") from exc
    if not isinstance(prereg, Mapping) or not isinstance(receipt, Mapping):
        _fail("HELD_OUT_EVIDENCE_INVALID", "held-out JSON evidence must be objects")
    if (
        prereg.get("authority") is not False
        or prereg.get("fresh_session_required") is not True
        or prereg.get("source_run_id") != current_run_id
        or prereg.get("status") not in {"FROZEN", "SEALED"}
    ):
        _fail("HELD_OUT_PREREGISTRATION_INVALID", "held-out twin is not preregistered fresh")
    if (
        receipt.get("status") != "SEALED"
        or receipt.get("authority") is not False
        or receipt.get("completion_claim_allowed") is not False
    ):
        _fail("HELD_OUT_RUN_NOT_SEALED", "held-out run receipt is not sealed")
    if receipt.get("run_id") == current_run_id:
        _fail("HELD_OUT_TWIN_NOT_FRESH", "held-out twin reuses the source run")
    if not _self_seal_valid(receipt, "receipt_sha256"):
        _fail("HELD_OUT_RUN_RECEIPT_SEAL_INVALID", "held-out run receipt seal is invalid")
    trajectory_digest = _sha(trajectory_raw)
    trajectory_bound = any(
        isinstance(job, Mapping)
        and isinstance(job.get("trajectory_index"), Mapping)
        and (
            (
                Path(str(job["trajectory_index"].get("raw_path", ""))).expanduser()
                if Path(str(job["trajectory_index"].get("raw_path", ""))).expanduser().is_absolute()
                else receipt_path.parent
                / Path(str(job["trajectory_index"].get("raw_path", ""))).expanduser()
            ).resolve()
            == trajectory_path
        )
        and job["trajectory_index"].get("raw_sha256") == trajectory_digest
        for job in receipt.get("jobs", [])
        if isinstance(receipt.get("jobs"), list)
    )
    if not trajectory_bound:
        _fail("HELD_OUT_TRAJECTORY_UNBOUND", "trajectory is not bound by held-out receipt")
    predictions = prereg.get("predictions")
    prediction_id = prediction["prediction_id"]
    if not isinstance(predictions, list):
        _fail("HELD_OUT_PREREGISTRATION_INVALID", "preregistered predictions are missing")
    registered = next(
        (
            row
            for row in predictions
            if isinstance(row, Mapping) and row.get("prediction_id") == prediction_id
        ),
        None,
    )
    if registered is None:
        _fail("HELD_OUT_PREDICTION_UNBOUND", "prediction id was not preregistered")
    matched = value.get("matched_prediction")
    if not isinstance(matched, Mapping) or matched.get("prediction_id") != prediction_id:
        _fail("HELD_OUT_MATCH_INVALID", "matched_prediction is missing or unbound")
    if matched.get("method") != "exact_utf8_span_sha256_v1" or matched.get("matched") is not True:
        _fail("HELD_OUT_MATCH_INVALID", "held-out matcher is not mechanically supported")
    observed_path = _resolve(
        matched.get("observed_path"), anchor=anchor, reason="HELD_OUT_MATCH_INVALID"
    )
    observed_raw = _read_bytes(observed_path, reason="HELD_OUT_MATCH_INVALID")
    if matched.get("observed_sha256") != _sha(observed_raw):
        _fail("HELD_OUT_MATCH_INVALID", "held-out observed file drift")
    start = matched.get("byte_start")
    end = matched.get("byte_end")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not 0 <= start < end <= len(observed_raw)
    ):
        _fail("HELD_OUT_MATCH_INVALID", "held-out observed span is invalid")
    span = observed_raw[start:end]
    try:
        span.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanaryAssessmentError("HELD_OUT_MATCH_INVALID", "held-out span is not UTF-8") from exc
    expected = registered.get("expected_observation_sha256")
    if (
        not isinstance(expected, str)
        or _sha(span) != expected
        or matched.get("span_sha256") != expected
    ):
        _fail("HELD_OUT_MATCH_INVALID", "held-out observation does not match preregistration")
    return {
        "status": "SATISFIED",
        "machine_verified": True,
        "prediction_id": prediction_id,
        "preregistration_path": str(prereg_path),
        "held_out_run_receipt_path": str(receipt_path),
        "held_out_trajectory_path": str(trajectory_path),
        "matched_observation_sha256": expected,
    }


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _descriptor_value(descriptor: Mapping[str, Any], key: str, section: str) -> object:
    nested = descriptor.get(section)
    if isinstance(nested, Mapping) and key in nested:
        return nested[key]
    return descriptor.get(key)


def _selection_contract(descriptor: Mapping[str, Any], role: str) -> dict[str, Any]:
    nested = descriptor.get("selection")
    result = dict(nested) if isinstance(nested, Mapping) else {}
    defaults = {
        "baseline": "empty",
        "autonomous": "subject_self_selected",
        "curated": "frozen_external_set",
        "random": "sha256_seed_rank_v1",
    }
    result.setdefault("method", descriptor.get("selection_method", defaults[role]))
    if "seed" not in result:
        if "seed" in descriptor:
            result["seed"] = descriptor["seed"]
        elif "random_seed" in descriptor:
            result["seed"] = descriptor["random_seed"]
    for key in ("expected_selected_ids", "externally_selected_ids"):
        if key not in result and key in descriptor:
            result[key] = descriptor[key]
    return result


def _inspect_arm(
    job: Mapping[str, Any],
    *,
    role: str,
    variant_id: str,
    replicate: int,
    run_id: object,
    receipt_dir: Path,
    explicit_descriptor: Path | None,
) -> dict[str, Any]:
    workspace, workspace_source = _workspace_root(job, receipt_dir=receipt_dir)
    descriptor_path, descriptor_outer_sha = _descriptor_location(
        job, explicit=explicit_descriptor, receipt_dir=receipt_dir
    )
    descriptor = _load_descriptor(
        descriptor_path,
        expected_file_sha256=descriptor_outer_sha,
        role=role,
        variant_id=variant_id,
        replicate=replicate,
        run_id=run_id,
    )
    expected_catalog_sha = descriptor.get(
        "expected_catalog_sha256", descriptor.get("catalog_sha256")
    )
    if not isinstance(expected_catalog_sha, str) or len(expected_catalog_sha) != 64:
        _fail("DESCRIPTOR_CATALOG_INVALID", "expected_catalog_sha256 is missing")
    catalog = _validate_catalog(workspace, descriptor=descriptor)
    visible_ids = descriptor.get("visible_history_ids", descriptor.get("record_ids"))
    if visible_ids != catalog["record_ids"]:
        _fail("VISIBLE_HISTORY_IDENTITY_INVALID", f"visible history mismatch for {role}")
    required_open_count = descriptor.get("required_open_count")
    if required_open_count != EXPECTED_OPEN_COUNT[role]:
        _fail("OPEN_COUNT_CONTRACT_INVALID", f"required open count mismatch for {role}")
    ledger = _validate_query_ledger(workspace, catalog)
    trajectory_path, trajectory_raw, trajectory_sha = _trajectory(job, receipt_dir=receipt_dir)
    trajectory_contract = descriptor.get("trajectory")
    trajectory_contract = trajectory_contract if isinstance(trajectory_contract, Mapping) else {}
    declared_trajectory_path = _resolve(
        trajectory_contract.get("path", descriptor.get("trajectory_path")),
        anchor=descriptor_path.parent,
        reason="DESCRIPTOR_TRAJECTORY_INVALID",
    )
    declared_trajectory_sha = trajectory_contract.get("sha256", descriptor.get("trajectory_sha256"))
    if declared_trajectory_path != trajectory_path or declared_trajectory_sha != trajectory_sha:
        _fail("DESCRIPTOR_TRAJECTORY_INVALID", f"trajectory identity mismatch for {role}")
    allowed_prefix = trajectory_contract.get(
        "allowed_invocation_prefix",
        descriptor.get(
            "allowed_invocation_prefix",
            descriptor.get("allowed_query_tool_invocation_prefix"),
        ),
    )
    store_relative_path = trajectory_contract.get(
        "store_relative_path",
        descriptor.get("store_relative_path", descriptor.get("backing_store_relative_path")),
    )
    blob_names = trajectory_contract.get("record_blob_names", descriptor.get("record_blob_names"))
    if (
        not isinstance(allowed_prefix, list)
        or any(not isinstance(item, str) or not item for item in allowed_prefix)
        or not isinstance(store_relative_path, str)
        or not store_relative_path
        or not isinstance(blob_names, list)
        or any(not isinstance(item, str) or not item for item in blob_names)
    ):
        _fail("DESCRIPTOR_TRAJECTORY_INVALID", f"trajectory audit contract invalid for {role}")
    if sorted(blob_names) != catalog["record_blob_names"]:
        _fail("DESCRIPTOR_TRAJECTORY_INVALID", f"record blob identity mismatch for {role}")
    trajectory_audit = _audit_trajectory(
        trajectory_raw,
        allowed_invocation_prefix=allowed_prefix,
        store_relative_path=store_relative_path,
        record_blob_names=blob_names,
        query_event_count=ledger["model_query_event_count"],
        bypass_is_error=False,
    )
    last_path, last_raw, last_sha = _last_message(job, receipt_dir=receipt_dir)
    claims = descriptor.get("last_message_claims", {})
    if not isinstance(claims, Mapping):
        _fail("CLAIM_ANNOTATION_INVALID", "last_message_claims must be an object")
    abstraction = _span_annotation(
        claims.get("previously_unnamed_abstraction"),
        output_path=last_path,
        output_raw=last_raw,
        output_sha256=last_sha,
        claim_name="previously_unnamed_abstraction",
    )
    prediction = _span_annotation(
        claims.get("counterfactual_prediction"),
        output_path=last_path,
        output_raw=last_raw,
        output_sha256=last_sha,
        claim_name="counterfactual_prediction",
    )
    held_out = _held_out_settlement(
        descriptor.get("held_out"),
        descriptor_path=descriptor_path,
        current_run_id=run_id,
        prediction=prediction,
    )
    opened = ledger["open_order"]
    unique_opened = _unique(opened)
    if not ledger["model_query_event_count"]:
        query_state = "NO_QUERY"
    elif not opened:
        query_state = "QUERY_WITHOUT_OPEN"
    else:
        query_state = "OPENED"
    return {
        "role": role,
        "variant_id": variant_id,
        "replicate": replicate,
        "lineage_id": job.get("lineage_id"),
        "workspace_root": str(workspace),
        "workspace_source": workspace_source,
        "descriptor_path": str(descriptor_path),
        "descriptor_sha256": descriptor["file_sha256"],
        "full_pool_id": descriptor.get("full_pool_id"),
        "full_pool_record_identities": descriptor.get("full_pool_record_identities"),
        "selection": _selection_contract(descriptor, role),
        "catalog": catalog,
        "query_ledger": {
            "path": ledger["path"],
            "sha256": ledger["sha256"],
            "event_count": len(ledger["events"]),
            "model_query_event_count": ledger["model_query_event_count"],
        },
        "query_state": query_state,
        "open_order": opened,
        "unique_open_order": unique_opened,
        "required_open_count": required_open_count,
        "open_count_valid": len(unique_opened) == required_open_count,
        "trajectory": {
            "path": str(trajectory_path),
            "sha256": trajectory_sha,
            **trajectory_audit,
        },
        "last_message": {"path": str(last_path), "sha256": last_sha},
        "previously_unnamed_abstraction": abstraction,
        "counterfactual_prediction": prediction,
        "held_out_trajectory_settlement": held_out,
    }


def _inspect_pilot_arm(
    job: Mapping[str, Any],
    *,
    variant_id: str,
    run_id: object,
    receipt_dir: Path,
    explicit_descriptor: Path | None,
) -> dict[str, Any]:
    replicate = job.get("replicate")
    if not isinstance(replicate, int) or isinstance(replicate, bool) or replicate < 1:
        _fail("RUN_JOB_IDENTITY_INVALID", "pilot replicate is invalid")
    workspace, workspace_source = _workspace_root(job, receipt_dir=receipt_dir)
    descriptor_path, outer_sha = _descriptor_location(
        job, explicit=explicit_descriptor, receipt_dir=receipt_dir
    )
    descriptor = _load_descriptor(
        descriptor_path,
        expected_file_sha256=outer_sha,
        role="autonomous",
        variant_id=variant_id,
        replicate=replicate,
        run_id=run_id,
    )
    if descriptor.get("stage") != "instrument-pilot":
        _fail("PILOT_DESCRIPTOR_INVALID", "pilot descriptor stage is not instrument-pilot")
    catalog = _validate_catalog(workspace, descriptor=descriptor)
    if descriptor.get("visible_history_ids", descriptor.get("record_ids")) != catalog["record_ids"]:
        _fail("VISIBLE_HISTORY_IDENTITY_INVALID", "pilot visible history differs from catalog")
    pool = _pool_identity_map(descriptor.get("full_pool_record_identities"))
    if set(catalog["record_ids"]) != set(pool):
        _fail("PILOT_CATALOG_NOT_FULL_POOL", "pilot autonomous catalog is not the full pool")
    for row in catalog["records"]:
        if pool[row["record_id"]] != (row["bytes"], row["sha256"]):
            _fail("PILOT_CATALOG_NOT_FULL_POOL", "pilot catalog record identity drift")
    selection = _selection_contract(descriptor, "autonomous")
    if selection.get("method") not in {
        "subject_self_selected",
        "full_opaque_catalog",
    }:
        _fail("PILOT_DESCRIPTOR_INVALID", "pilot selection is not autonomous")
    ledger = _validate_query_ledger(workspace, catalog)
    trajectory_path, trajectory_raw, trajectory_sha = _trajectory(job, receipt_dir=receipt_dir)
    contract = descriptor.get("trajectory")
    contract = contract if isinstance(contract, Mapping) else {}
    bound_path = _resolve(
        contract.get("path", descriptor.get("trajectory_path")),
        anchor=descriptor_path.parent,
        reason="DESCRIPTOR_TRAJECTORY_INVALID",
    )
    bound_sha = contract.get("sha256", descriptor.get("trajectory_sha256"))
    if bound_path != trajectory_path or bound_sha != trajectory_sha:
        _fail("DESCRIPTOR_TRAJECTORY_INVALID", "pilot trajectory identity mismatch")
    allowed = contract.get(
        "allowed_invocation_prefix",
        descriptor.get(
            "allowed_invocation_prefix",
            descriptor.get("allowed_query_tool_invocation_prefix"),
        ),
    )
    store_relative = contract.get(
        "store_relative_path",
        descriptor.get("store_relative_path", descriptor.get("backing_store_relative_path")),
    )
    blob_names = contract.get("record_blob_names", descriptor.get("record_blob_names"))
    if (
        not isinstance(allowed, list)
        or any(not isinstance(item, str) or not item for item in allowed)
        or not isinstance(store_relative, str)
        or not store_relative
        or not isinstance(blob_names, list)
        or sorted(blob_names) != catalog["record_blob_names"]
    ):
        _fail("DESCRIPTOR_TRAJECTORY_INVALID", "pilot trajectory audit contract invalid")
    audit = _audit_trajectory(
        trajectory_raw,
        allowed_invocation_prefix=allowed,
        store_relative_path=store_relative,
        record_blob_names=blob_names,
        query_event_count=ledger["model_query_event_count"],
        bypass_is_error=False,
    )
    opened = _unique(ledger["open_order"])
    max_open_count = catalog["config"].get("max_open_count")
    if not isinstance(max_open_count, int) or len(opened) > max_open_count:
        _fail("PILOT_OPEN_LIMIT_INVALID", "pilot exceeds its frozen maximum open count")
    return {
        "variant_id": variant_id,
        "replicate": replicate,
        "workspace_root": str(workspace),
        "workspace_source": workspace_source,
        "descriptor_path": str(descriptor_path),
        "catalog_id": catalog["catalog_id"],
        "catalog_order": catalog["record_ids"],
        "query_ledger_path": ledger["path"],
        "query_ledger_sha256": ledger["sha256"],
        "query_event_count": ledger["model_query_event_count"],
        "open_order": ledger["open_order"],
        "unique_open_order": opened,
        "maximum_open_count": max_open_count,
        "trajectory": {"path": str(trajectory_path), "sha256": trajectory_sha, **audit},
    }


def _pool_identity_map(value: object) -> dict[str, tuple[int, str]]:
    if not isinstance(value, list) or not value:
        _fail("FULL_POOL_IDENTITY_INVALID", "full_pool_record_identities must be non-empty")
    result: dict[str, tuple[int, str]] = {}
    for row in value:
        if not isinstance(row, Mapping):
            _fail("FULL_POOL_IDENTITY_INVALID", "full-pool identity row is invalid")
        record_id = row.get("id", row.get("record_id"))
        size = row.get("bytes")
        digest = row.get("sha256")
        if (
            not isinstance(record_id, str)
            or record_id in result
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            _fail("FULL_POOL_IDENTITY_INVALID", "full-pool record identity is invalid")
        result[record_id] = (size, digest.casefold())
    return result


def _selection_ids(arm: Mapping[str, Any], key: str) -> list[str] | None:
    selection = arm.get("selection")
    if not isinstance(selection, Mapping):
        return None
    value = selection.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return list(value)


def _random_expected(seed: object, ids: Iterable[str]) -> list[str]:
    if isinstance(seed, bool) or not isinstance(seed, (str, int)) or seed == "":
        _fail("RANDOM_CONTROL_INVALID", "random seed is not frozen")
    seed_bytes = _canonical_bytes({"seed": seed})
    return sorted(
        ids,
        key=lambda record_id: _sha(seed_bytes + b"\0" + record_id.encode("utf-8")),
    )[:3]


def _validate_matched_arms(arms: Mapping[str, Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    full_pool_ids = {arm.get("full_pool_id") for arm in arms.values()}
    if len(full_pool_ids) != 1 or None in full_pool_ids:
        _fail("FULL_POOL_IDENTITY_MISMATCH", "arms are not bound to one full history pool")
    pool_maps = [
        _pool_identity_map(arm.get("full_pool_record_identities")) for arm in arms.values()
    ]
    if any(pool != pool_maps[0] for pool in pool_maps[1:]):
        _fail("FULL_POOL_IDENTITY_MISMATCH", "full history identities differ by arm")
    pool = pool_maps[0]
    baseline = arms["baseline"]
    autonomous = arms["autonomous"]
    random_arm = arms["random"]
    expected_pool_id = autonomous["catalog"]["catalog_id"]
    if next(iter(full_pool_ids)) not in {expected_pool_id, f"sha256:{expected_pool_id}"}:
        _fail("FULL_POOL_IDENTITY_MISMATCH", "full_pool_id is not bound to the full catalog")
    if baseline["catalog"]["record_ids"]:
        _fail("BASELINE_CATALOG_NOT_EMPTY", "baseline must have an empty catalog")
    if set(autonomous["catalog"]["record_ids"]) != set(pool):
        _fail("AUTONOMOUS_CATALOG_NOT_FULL_POOL", "autonomous arm lacks the full neutral pool")
    for role, arm in arms.items():
        for row in arm["catalog"]["records"]:
            expected = pool.get(row["record_id"])
            if expected != (row["bytes"], row["sha256"]):
                _fail("ARM_CATALOG_NOT_FROM_FULL_POOL", f"{role} record is not from full pool")
    autonomous_selection = autonomous.get("selection")
    if not isinstance(autonomous_selection, Mapping) or autonomous_selection.get("method") not in {
        "subject_self_selected",
        "full_opaque_catalog",
    }:
        _fail("AUTONOMOUS_SELECTION_CONTRACT_INVALID", "autonomous method is not subject-selected")
    if any(
        key in autonomous_selection
        for key in ("expected_selected_ids", "externally_selected_ids", "selected_ids")
    ):
        _fail("AUTONOMOUS_SELECTION_PREASSIGNED", "autonomous selection was preassigned")
    random_selection = random_arm.get("selection")
    if not isinstance(random_selection, Mapping):
        _fail("RANDOM_CONTROL_INVALID", "random selection descriptor is missing")
    if random_selection.get("method") not in {"sha256_seed_rank_v1", "sha256-order-v1"}:
        _fail("RANDOM_CONTROL_INVALID", "random selection method is unsupported")
    frozen_random = _selection_ids(random_arm, "expected_selected_ids")
    expected_random = _random_expected(random_selection.get("seed"), pool)
    if frozen_random is not None and frozen_random != expected_random:
        _fail("RANDOM_CONTROL_INVALID", "random selected ids do not match the frozen seed")
    if set(random_arm["catalog"]["record_ids"]) != set(expected_random):
        _fail("RANDOM_CONTROL_INVALID", "random catalog does not match the frozen selection")
    if set(random_arm["unique_open_order"]) != set(expected_random):
        reasons.append("RANDOM_CONTROL_DID_NOT_OPEN_FROZEN_SET")
    curated = arms.get("curated")
    if curated is not None:
        curated_selection = curated.get("selection")
        curated_ids = _selection_ids(curated, "externally_selected_ids")
        if (
            not isinstance(curated_selection, Mapping)
            or curated_selection.get("method") not in {"frozen_external_set", "externally_curated"}
            or curated_ids is None
            or len(curated_ids) != 3
            or set(curated["catalog"]["record_ids"]) != set(curated_ids)
        ):
            _fail("CURATED_CONTROL_INVALID", "curated selection is not frozen at three ids")
        if set(curated["unique_open_order"]) != set(curated_ids):
            reasons.append("CURATED_CONTROL_DID_NOT_OPEN_FROZEN_SET")
    return reasons


def _overlap(left: Sequence[str], right: Sequence[str]) -> dict[str, Any]:
    left_set = set(left)
    right_set = set(right)
    intersection = sorted(left_set & right_set)
    union = left_set | right_set
    return {
        "ids": intersection,
        "count": len(intersection),
        "jaccard": len(intersection) / len(union) if union else 1.0,
        "identical": left == right,
        "same_set": left_set == right_set,
    }


def _classify_replicate(arms: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    validation_reasons = _validate_matched_arms(arms)
    autonomous = arms["autonomous"]
    random_arm = arms["random"]
    overlaps = {
        "autonomous_vs_random": _overlap(
            autonomous["unique_open_order"], random_arm["unique_open_order"]
        )
    }
    if "curated" in arms:
        overlaps["autonomous_vs_curated"] = _overlap(
            autonomous["unique_open_order"], arms["curated"]["unique_open_order"]
        )
        overlaps["curated_vs_random"] = _overlap(
            arms["curated"]["unique_open_order"], random_arm["unique_open_order"]
        )
    equal_exposure = all(
        arm["open_count_valid"]
        for role, arm in arms.items()
        if role in {"baseline", "autonomous", "random", "curated"}
    )
    control_bypass = any(
        arm["trajectory"]["direct_archive_bypass"]
        for role, arm in arms.items()
        if role != "autonomous"
    )
    if autonomous["trajectory"]["direct_archive_bypass"]:
        classification = AUTONOMOUS_SELECTION_INVALID
        reasons = ["DIRECT_ARCHIVE_BYPASS"]
        assessable = False
    elif control_bypass:
        classification = MATCHED_COMPARISON_NOT_ASSESSABLE
        reasons = ["CONTROL_DIRECT_ARCHIVE_BYPASS"]
        assessable = False
    elif autonomous["query_state"] == "NO_QUERY":
        classification = NO_QUERY_OR_OPEN
        reasons = ["AUTONOMOUS_NO_QUERY"]
        assessable = False
    elif autonomous["query_state"] == "QUERY_WITHOUT_OPEN":
        classification = QUERY_WITHOUT_OPEN
        reasons = ["AUTONOMOUS_QUERY_WITHOUT_OPEN"]
        assessable = False
    elif not autonomous["open_count_valid"]:
        classification = AUTONOMOUS_SELECTION_INVALID
        reasons = ["AUTONOMOUS_REQUIRES_EXACTLY_THREE_DISTINCT_OPENS"]
        assessable = False
    elif not equal_exposure or validation_reasons:
        classification = MATCHED_COMPARISON_NOT_ASSESSABLE
        reasons = ["NON_AUTONOMOUS_CONTROL_EXPOSURE_INVALID", *validation_reasons]
        assessable = False
    else:
        assessable = True
        reasons = []
        random_same = overlaps["autonomous_vs_random"]["same_set"]
        curated_same = (
            overlaps.get("autonomous_vs_curated", {}).get("same_set", False)
            if "curated" in arms
            else False
        )
        distinct_from_random = not random_same
        abstraction = autonomous["previously_unnamed_abstraction"]["status"]
        prediction = autonomous["counterfactual_prediction"]["status"]
        held_out = autonomous["held_out_trajectory_settlement"]["status"]
        if random_same and ("curated" not in arms or curated_same):
            classification = NO_DISTINCT_AUTONOMOUS_SELECTION
            reasons.append("AUTONOMOUS_SELECTION_EQUALS_NON_AUTONOMOUS_CONTROL")
        elif (
            distinct_from_random
            and abstraction == "ANNOTATED_CANDIDATE"
            and prediction == "ANNOTATED_CANDIDATE"
            and held_out == "SATISFIED"
        ):
            classification = CHAIN_SETTLED_CANDIDATE
            reasons.append("FRESH_HELD_OUT_CHAIN_MACHINE_SETTLED")
        else:
            classification = INTERESTING_EVENT_ONLY
            reasons.append("NO_SELF_EVOLUTION_EVIDENCE")
            if held_out == "PENDING":
                reasons.append("HELD_OUT_TRAJECTORY_PENDING")
    return {
        "replicate": autonomous["replicate"],
        "classification": classification,
        "reason_codes": _unique(reasons),
        "autonomous_contrast_assessable": assessable,
        "equal_history_open_count_exposure": equal_exposure,
        "selection_overlap": overlaps,
        "previously_unnamed_abstraction": autonomous["previously_unnamed_abstraction"]["status"],
        "counterfactual_prediction_presence": autonomous["counterfactual_prediction"]["status"],
        "held_out_trajectory_settlement": autonomous["held_out_trajectory_settlement"],
        "arms": dict(arms),
    }


def _base_report(
    receipt_path: Path,
    *,
    variants: Mapping[str, str | None],
) -> dict[str, Any]:
    return {
        "schema": CANARY_SCHEMA,
        "stage": "formal",
        "formal_canary": True,
        "authority": False,
        "completion_claim_allowed": False,
        "scientific_verdict": None,
        "research_verdict": None,
        "q_t_verdict": None,
        "self_evolution_claim_allowed": False,
        "project_completion_claim_allowed": False,
        "run_receipt_path": str(receipt_path),
        "run_id": None,
        "variants": dict(variants),
        "classification": INVALID_EVIDENCE,
        "reason_codes": [],
        "replicates": [],
    }


def assess_instrument_pilot(
    run_receipt_path: Path,
    *,
    autonomous_variant: str = "autonomous",
    descriptor_path: Path | None = None,
) -> dict[str, Any]:
    """Classify one free-k autonomous contact as an instrument pilot, never a canary."""

    receipt_path = Path(run_receipt_path).expanduser().resolve()
    report: dict[str, Any] = {
        "schema": CANARY_SCHEMA,
        "stage": "instrument-pilot",
        "formal_canary": False,
        "authority": False,
        "completion_claim_allowed": False,
        "scientific_verdict": None,
        "research_verdict": None,
        "q_t_verdict": None,
        "self_evolution_claim_allowed": False,
        "project_completion_claim_allowed": False,
        "run_receipt_path": str(receipt_path),
        "run_id": None,
        "variant_id": autonomous_variant,
        "classification": PILOT_LEDGER_INCOMPLETE,
        "reason_codes": [],
        "pilot": None,
    }
    try:
        receipt = _read_json(receipt_path, reason="RUN_RECEIPT_INVALID")
        report["run_id"] = receipt.get("run_id")
        if receipt.get("status") != "SEALED":
            _fail("RUN_NOT_SEALED", "pilot assessment requires a SEALED run")
        if (
            receipt.get("authority") is not False
            or receipt.get("completion_claim_allowed") is not False
        ):
            _fail("RUN_BOUNDARY_INVALID", "run receipt boundary fields are invalid")
        if not _self_seal_valid(receipt, "receipt_sha256"):
            _fail("RUN_RECEIPT_SEAL_INVALID", "run receipt seal is invalid")
        jobs = receipt.get("jobs")
        if not isinstance(jobs, list):
            _fail("PILOT_JOB_SET_INVALID", "pilot run jobs must be a list")
        selected = [
            job
            for job in jobs
            if isinstance(job, Mapping) and job.get("variant_id") == autonomous_variant
        ]
        if len(selected) != 1:
            _fail("PILOT_JOB_SET_INVALID", "pilot requires exactly one autonomous job")
        pilot = _inspect_pilot_arm(
            selected[0],
            variant_id=autonomous_variant,
            run_id=receipt.get("run_id"),
            receipt_dir=receipt_path.parent,
            explicit_descriptor=descriptor_path,
        )
        report["pilot"] = pilot
        if pilot["trajectory"]["direct_archive_bypass"]:
            report["classification"] = PILOT_BYPASS
            report["reason_codes"] = ["DIRECT_ARCHIVE_BYPASS"]
        elif pilot["query_event_count"] == 0 and pilot["trajectory"]["allowed_invocation_seen"]:
            report["classification"] = PILOT_LEDGER_INCOMPLETE
            report["reason_codes"] = ["QUERY_ATTEMPT_WITHOUT_LEDGER"]
        elif not pilot["unique_open_order"]:
            report["classification"] = PILOT_NO_FIRE
            report["reason_codes"] = ["ZERO_OPEN_IS_LEGAL_IN_PILOT"]
        elif (
            pilot["unique_open_order"] == pilot["catalog_order"][: len(pilot["unique_open_order"])]
        ):
            report["classification"] = PILOT_ORDER_FOLLOWING
            report["reason_codes"] = ["SELECTION_FOLLOWS_NEUTRAL_CATALOG_ORDER"]
        else:
            report["classification"] = PILOT_NONTRIVIAL_SELECTION_CANDIDATE
            report["reason_codes"] = ["MECHANICAL_SELECTION_EVENT_ONLY"]
        return report
    except CanaryAssessmentError as exc:
        report["classification"] = PILOT_LEDGER_INCOMPLETE
        report["reason_codes"] = [exc.reason_code]
        report["error"] = str(exc)
        return report


def assess_run_receipt(
    run_receipt_path: Path,
    *,
    baseline_variant: str = "baseline",
    autonomous_variant: str = "autonomous",
    random_variant: str = "random",
    curated_variant: str | None = None,
    descriptor_paths: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Return a conservative mechanical classification for one completed run."""

    receipt_path = Path(run_receipt_path).expanduser().resolve()
    variants = {
        "baseline": baseline_variant,
        "autonomous": autonomous_variant,
        "random": random_variant,
        "curated": curated_variant,
    }
    report = _base_report(receipt_path, variants=variants)
    try:
        chosen = [value for value in variants.values() if value is not None]
        if any(not isinstance(value, str) or not value for value in chosen) or len(
            set(chosen)
        ) != len(chosen):
            _fail("VARIANT_SELECTION_INVALID", "arm variants must be non-empty and unique")
        receipt = _read_json(receipt_path, reason="RUN_RECEIPT_INVALID")
        report["run_id"] = receipt.get("run_id")
        if receipt.get("status") != "SEALED":
            _fail("RUN_NOT_SEALED", "assessment requires a completed SEALED run")
        if (
            receipt.get("authority") is not False
            or receipt.get("completion_claim_allowed") is not False
        ):
            _fail("RUN_BOUNDARY_INVALID", "run receipt boundary fields are invalid")
        if not _self_seal_valid(receipt, "receipt_sha256"):
            _fail("RUN_RECEIPT_SEAL_INVALID", "run receipt seal is invalid")
        jobs = receipt.get("jobs")
        if not isinstance(jobs, list):
            _fail("RUN_JOB_SET_INVALID", "run jobs must be a list")
        by_key: dict[tuple[str, int], Mapping[str, Any]] = {}
        for job in jobs:
            if not isinstance(job, Mapping):
                _fail("RUN_JOB_SET_INVALID", "run contains a non-object job")
            variant = job.get("variant_id")
            if variant not in chosen:
                continue
            replicate = job.get("replicate")
            if not isinstance(replicate, int) or isinstance(replicate, bool) or replicate < 1:
                _fail("RUN_JOB_IDENTITY_INVALID", "selected job replicate is invalid")
            key = (str(variant), replicate)
            if key in by_key:
                _fail("RUN_JOB_IDENTITY_INVALID", f"duplicate selected job: {key}")
            if job.get("exit_code") not in (None, 0):
                _fail("RUN_JOB_FAILED", f"selected job failed: {key}")
            by_key[key] = job
        replicate_ids = sorted(
            {
                replicate
                for (variant, replicate) in by_key
                if variant in {baseline_variant, autonomous_variant, random_variant}
            }
        )
        if not replicate_ids:
            report["classification"] = MATCHED_COMPARISON_NOT_ASSESSABLE
            report["reason_codes"] = ["REQUIRED_ARMS_MISSING"]
            return report
        explicit_descriptors = descriptor_paths or {}
        for replicate in replicate_ids:
            missing = [
                role for role in REQUIRED_ROLES if (str(variants[role]), replicate) not in by_key
            ]
            if missing:
                report["replicates"].append(
                    {
                        "replicate": replicate,
                        "classification": MATCHED_COMPARISON_NOT_ASSESSABLE,
                        "reason_codes": ["REQUIRED_ARMS_MISSING"],
                        "missing_roles": missing,
                        "autonomous_contrast_assessable": False,
                    }
                )
                continue
            arm_rows: dict[str, Mapping[str, Any]] = {}
            for role in REQUIRED_ROLES:
                variant_id = str(variants[role])
                arm_rows[role] = _inspect_arm(
                    by_key[(variant_id, replicate)],
                    role=role,
                    variant_id=variant_id,
                    replicate=replicate,
                    run_id=receipt.get("run_id"),
                    receipt_dir=receipt_path.parent,
                    explicit_descriptor=explicit_descriptors.get(role),
                )
            if curated_variant is not None and (curated_variant, replicate) in by_key:
                arm_rows["curated"] = _inspect_arm(
                    by_key[(curated_variant, replicate)],
                    role="curated",
                    variant_id=curated_variant,
                    replicate=replicate,
                    run_id=receipt.get("run_id"),
                    receipt_dir=receipt_path.parent,
                    explicit_descriptor=explicit_descriptors.get("curated"),
                )
            report["replicates"].append(_classify_replicate(arm_rows))
        classes = [row["classification"] for row in report["replicates"]]
        if any(value == MATCHED_COMPARISON_NOT_ASSESSABLE for value in classes):
            report["classification"] = MATCHED_COMPARISON_NOT_ASSESSABLE
        elif any(value == AUTONOMOUS_SELECTION_INVALID for value in classes):
            report["classification"] = AUTONOMOUS_SELECTION_INVALID
        elif any(value == QUERY_WITHOUT_OPEN for value in classes):
            report["classification"] = QUERY_WITHOUT_OPEN
        elif any(value == NO_QUERY_OR_OPEN for value in classes):
            report["classification"] = NO_QUERY_OR_OPEN
        elif all(value == CHAIN_SETTLED_CANDIDATE for value in classes):
            report["classification"] = CHAIN_SETTLED_CANDIDATE
        elif any(value == INTERESTING_EVENT_ONLY for value in classes):
            report["classification"] = INTERESTING_EVENT_ONLY
        else:
            report["classification"] = NO_DISTINCT_AUTONOMOUS_SELECTION
        report["reason_codes"] = _unique(
            reason for row in report["replicates"] for reason in row.get("reason_codes", [])
        )
        if len(set(classes)) > 1:
            report["reason_codes"].append("MIXED_REPLICATE_CLASSIFICATIONS")
        return report
    except CanaryAssessmentError as exc:
        report["classification"] = INVALID_EVIDENCE
        report["reason_codes"] = [exc.reason_code]
        report["error"] = str(exc)
        return report


assess_archive_query_canary = assess_run_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_receipt", type=Path)
    parser.add_argument("--stage", choices=("formal", "instrument-pilot"), default="formal")
    parser.add_argument("--baseline-variant", default="baseline")
    parser.add_argument("--autonomous-variant", default="autonomous")
    parser.add_argument("--random-variant", default="random")
    parser.add_argument("--curated-variant")
    for role in (*REQUIRED_ROLES, *OPTIONAL_ROLES):
        parser.add_argument(f"--{role}-descriptor", type=Path)
    parser.add_argument(
        "--prepare-pilot-descriptor",
        type=Path,
        help="mechanically prepare a write-once pilot descriptor, then assess it",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    descriptor_paths = {
        role: path
        for role in (*REQUIRED_ROLES, *OPTIONAL_ROLES)
        if (path := getattr(args, f"{role}_descriptor")) is not None
    }
    if args.stage == "instrument-pilot":
        if args.prepare_pilot_descriptor is not None:
            if "autonomous" in descriptor_paths:
                raise SystemExit(
                    "--prepare-pilot-descriptor and --autonomous-descriptor are mutually exclusive"
                )
            prepare_instrument_pilot_descriptor(
                args.run_receipt,
                args.prepare_pilot_descriptor,
                autonomous_variant=args.autonomous_variant,
            )
            descriptor_paths["autonomous"] = args.prepare_pilot_descriptor
        report = assess_instrument_pilot(
            args.run_receipt,
            autonomous_variant=args.autonomous_variant,
            descriptor_path=descriptor_paths.get("autonomous"),
        )
    else:
        report = assess_run_receipt(
            args.run_receipt,
            baseline_variant=args.baseline_variant,
            autonomous_variant=args.autonomous_variant,
            random_variant=args.random_variant,
            curated_variant=args.curated_variant,
            descriptor_paths=descriptor_paths,
        )
    raw = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(raw, end="")
    else:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
        temporary.write_text(raw, encoding="utf-8")
        os.replace(temporary, output)
    return 2 if report["classification"] in {INVALID_EVIDENCE, PILOT_LEDGER_INCOMPLETE} else 0


if __name__ == "__main__":
    raise SystemExit(main())
