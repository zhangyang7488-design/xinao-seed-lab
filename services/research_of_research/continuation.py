"""Receipt-driven Stage 0 continuity detection for research-of-research.

This adapter deliberately stops before cognition or compute.  A valid durable
``run_receipt.json`` may become one immutable, non-authoritative
``ContinuationObservation``.  Nothing in this module starts or resumes Main, acquires
capacity, interprets scientific meaning, or writes a shared effect.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from services.xinao_perpetual_world_compute.controller import (
    _release_byte_lock,
    _try_acquire_byte_lock,
    atomic_write_json,
    canonical_json_bytes,
    now_iso,
)

DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\research_of_research")
CONTINUATION_DIRECTORY = "continuation"
RECEIPT_GLOB = "cells/*/runs/*/run_receipt.json"
CONTINUATION_TASK_NAME = r"\XINAO-S-RoR-Continuation-Detect-v0"

LEGACY_RUN_SCHEMA = "xinao.research-of-research.run.v1"
CURRENT_RUN_SCHEMA = "xinao.research-of-research.run.v2"
ACCEPTED_RUN_SCHEMAS = (LEGACY_RUN_SCHEMA, CURRENT_RUN_SCHEMA)

CONTRACT_SCHEMA = "xinao.research-of-research.continuation-contract.v0"
CONTRACT_POINTER_SCHEMA = "xinao.research-of-research.continuation-contract-pointer.v0"
SEEN_SOURCE_SCHEMA = "xinao.research-of-research.continuation-seen-source.v0"
CONTINUATION_OBSERVATION_SCHEMA = "xinao.research-of-research.continuation-observation.v0"
OBSERVATION_STATUS_SCHEMA = "xinao.research-of-research.continuation-observation-status.v0"
INCIDENT_SCHEMA = "xinao.research-of-research.continuation-source-incident.v0"
PROJECTION_SCHEMA = "xinao.research-of-research.continuation-projection.v0"

PROTOCOL_STAGE = "STAGE_0_CONTINUITY_DETECTION_ONLY"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_NO_AUTHORITY = {
    "authority": False,
    "instruction_source": False,
    "continuation_authorized": False,
    "dispatch_allowed": False,
    "reentry_request_derived": False,
    "main_launch_authorized": False,
    "capacity_claim_authorized": False,
    "shared_effect_authorized": False,
    "completion_claim_allowed": False,
}


class ContinuationError(RuntimeError):
    """A Stage 0 source, identity, or durable-state invariant failed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise ContinuationError(reason_code, message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stable_id(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _continuation_root(runtime_root: Path) -> Path:
    return runtime_root.resolve(strict=False) / CONTINUATION_DIRECTORY


def _write_once_json(path: Path, value: object, *, conflict_code: str) -> str:
    # Reuse the already-tested RoR immutable writer.  The deferred import keeps
    # cell.py able to call the best-effort wake helper without an import cycle.
    from services.research_of_research.cell import ResearchCellError, _write_once

    try:
        return _write_once(path, canonical_json_bytes(value), conflict_code=conflict_code)
    except ResearchCellError as exc:
        raise ContinuationError(exc.reason_code, str(exc)) from exc


def _receipt_canonical_bytes(value: object) -> bytes:
    # RoR receipts use cell.py's compact canonicalization, which intentionally
    # differs from controller state JSON formatting.
    from services.research_of_research.cell import _canonical_bytes

    return _canonical_bytes(value)


def _read_json_object(path: Path, *, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationError(reason_code, f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        _fail(reason_code, f"JSON object required: {path}")
    return value


def _require_no_authority(value: Mapping[str, Any], *, reason_code: str) -> None:
    for key, expected in _NO_AUTHORITY.items():
        if value.get(key) is not expected:
            _fail(reason_code, f"Stage 0 authority boundary invalid: {key}")


def _relative_receipt_parts(path: Path, runtime_root: Path) -> tuple[str, str, str]:
    try:
        relative = path.resolve(strict=False).relative_to(runtime_root.resolve(strict=False))
    except ValueError as exc:
        raise ContinuationError(
            "SOURCE_OUTSIDE_RUNTIME", f"source is outside runtime: {path}"
        ) from exc
    parts = relative.parts
    if (
        len(parts) != 5
        or parts[0] != "cells"
        or parts[2] != "runs"
        or parts[4] != "run_receipt.json"
    ):
        _fail("SOURCE_PATH_INVALID", f"receipt path does not match {RECEIPT_GLOB}: {path}")
    return relative.as_posix(), parts[1], parts[3]


def classify_receipt(path: Path, runtime_root: Path) -> dict[str, Any]:
    """Return a verified mechanical receipt identity; do not qualify its meaning."""

    relative_path, path_cell_id, path_run_id = _relative_receipt_parts(path, runtime_root)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContinuationError("SOURCE_READ_FAILED", f"cannot read receipt: {path}") from exc
    raw_sha256 = _sha256(raw)
    try:
        receipt = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationError("SOURCE_JSON_INVALID", f"invalid receipt JSON: {path}") from exc
    if not isinstance(receipt, dict):
        _fail("SOURCE_JSON_OBJECT_REQUIRED", f"receipt must be an object: {path}")

    schema = receipt.get("schema")
    cell_id = receipt.get("cell_id")
    run_id = receipt.get("run_id")
    if schema not in ACCEPTED_RUN_SCHEMAS:
        _fail("SOURCE_SCHEMA_INVALID", f"unsupported receipt schema: {schema!r}")
    if not isinstance(cell_id, str) or not cell_id:
        _fail("SOURCE_CELL_ID_INVALID", f"receipt cell_id is invalid: {path}")
    if not isinstance(run_id, str) or not run_id:
        _fail("SOURCE_RUN_ID_INVALID", f"receipt run_id is invalid: {path}")
    if cell_id != path_cell_id or run_id != path_run_id:
        _fail("SOURCE_PATH_IDENTITY_MISMATCH", f"receipt identity does not match its path: {path}")

    seal = receipt.get("receipt_sha256")
    if schema == CURRENT_RUN_SCHEMA:
        if not isinstance(seal, str) or not _HEX_SHA256.fullmatch(seal.casefold()):
            reason = "SOURCE_SEAL_MISSING" if seal is None else "SOURCE_SEAL_INVALID"
            _fail(reason, f"current receipt has no valid receipt_sha256: {path}")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        observed = _sha256(_receipt_canonical_bytes(unsigned))
        if observed != seal.casefold():
            _fail("SOURCE_SEAL_MISMATCH", f"receipt seal mismatch: {path}")
        receipt_digest = f"receipt_sha256:{seal.casefold()}"
        seal_mode = "VERIFIED_RECEIPT_SHA256"
    else:
        # Legacy v1 receipts predate the inner seal.  Preserve that fact rather
        # than fabricating one: their durable exact bytes are the identity.
        receipt_digest = f"bytes_sha256:{raw_sha256}"
        seal_mode = "LEGACY_EXACT_BYTES"

    logical_identity_value = {
        "cell_id": cell_id,
        "run_id": run_id,
        "source_class": "ror_run_receipt",
    }
    source_fingerprint_value = {
        **logical_identity_value,
        "receipt_digest": receipt_digest,
    }
    source = {
        "source_class": "ror_run_receipt",
        "cell_id": cell_id,
        "run_id": run_id,
        "receipt_schema": schema,
        "receipt_digest": receipt_digest,
        "receipt_file_sha256": raw_sha256,
        "seal_mode": seal_mode,
        "reported_status": receipt.get("status"),
        "relative_path": relative_path,
    }
    return {
        "logical_identity": _stable_id(logical_identity_value),
        "source_fingerprint": _stable_id(source_fingerprint_value),
        "source": source,
    }


def _incident_from_error(path: Path, runtime_root: Path, exc: ContinuationError) -> dict[str, Any]:
    try:
        relative_path = (
            path.resolve(strict=False).relative_to(runtime_root.resolve(strict=False)).as_posix()
        )
    except ValueError:
        relative_path = str(path.resolve(strict=False))
    try:
        raw_sha256: str | None = _sha256(path.read_bytes())
    except OSError:
        raw_sha256 = None
    identity = {
        "reason_code": exc.reason_code,
        "relative_path": relative_path,
        "source_file_sha256": raw_sha256,
    }
    incident_id = _stable_id(identity)
    return {
        "schema": INCIDENT_SCHEMA,
        "incident_id": incident_id,
        **identity,
        "protocol_stage": PROTOCOL_STAGE,
        **_NO_AUTHORITY,
    }


def _write_incident(continuation_root: Path, incident: Mapping[str, Any]) -> str:
    return _write_once_json(
        continuation_root / "incidents" / f"{incident['incident_id']}.json",
        dict(incident),
        conflict_code="CONTINUATION_INCIDENT_CONFLICT",
    )


def _scan_receipts(
    runtime_root: Path, continuation_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    facts: list[dict[str, Any]] = []
    incident_ids: list[str] = []
    for path in sorted(
        runtime_root.glob(RECEIPT_GLOB), key=lambda item: item.as_posix().casefold()
    ):
        try:
            facts.append(classify_receipt(path, runtime_root))
        except ContinuationError as exc:
            incident = _incident_from_error(path, runtime_root, exc)
            _write_incident(continuation_root, incident)
            incident_ids.append(str(incident["incident_id"]))
    return facts, incident_ids


def _load_revision(continuation_root: Path, revision_id: str) -> dict[str, Any]:
    if not _HEX_SHA256.fullmatch(revision_id):
        _fail("CONTRACT_REVISION_ID_INVALID", "current contract revision id is invalid")
    path = continuation_root / "contracts" / "revisions" / f"{revision_id}.json"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContinuationError(
            "CONTRACT_REVISION_MISSING", f"contract revision missing: {path}"
        ) from exc
    if _sha256(raw) != revision_id:
        _fail("CONTRACT_REVISION_HASH_MISMATCH", f"contract revision hash mismatch: {path}")
    try:
        revision = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationError(
            "CONTRACT_REVISION_JSON_INVALID", f"invalid contract revision: {path}"
        ) from exc
    if not isinstance(revision, dict) or revision.get("schema") != CONTRACT_SCHEMA:
        _fail("CONTRACT_REVISION_SCHEMA_INVALID", f"invalid contract revision schema: {path}")
    if revision.get("protocol_stage") != PROTOCOL_STAGE:
        _fail("CONTRACT_REVISION_STAGE_INVALID", f"invalid contract revision stage: {path}")
    source_root = revision.get("source_root")
    if not isinstance(source_root, str) or Path(source_root).resolve(strict=False) != (
        continuation_root.parent.resolve(strict=False)
    ):
        _fail("CONTRACT_REVISION_SOURCE_ROOT_INVALID", f"invalid contract source root: {path}")
    if revision.get("source_glob") != RECEIPT_GLOB:
        _fail("CONTRACT_REVISION_SOURCE_GLOB_INVALID", f"invalid contract source glob: {path}")
    if revision.get("accepted_source_schemas") != list(ACCEPTED_RUN_SCHEMAS):
        _fail("CONTRACT_REVISION_SOURCE_SCHEMAS_INVALID", f"invalid source schemas: {path}")
    _require_no_authority(revision, reason_code="CONTRACT_REVISION_AUTHORITY_INVALID")
    return revision


def _load_current(continuation_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = continuation_root / "contracts" / "current.json"
    current = _read_json_object(path, reason_code="CONTRACT_POINTER_INVALID")
    if current.get("schema") != CONTRACT_POINTER_SCHEMA:
        _fail("CONTRACT_POINTER_SCHEMA_INVALID", f"invalid contract pointer schema: {path}")
    if current.get("status") not in {"LIVE", "STOPPED"}:
        _fail("CONTRACT_POINTER_STATUS_INVALID", f"invalid contract pointer status: {path}")
    if current.get("protocol_stage") != PROTOCOL_STAGE:
        _fail("CONTRACT_POINTER_STAGE_INVALID", f"invalid contract pointer stage: {path}")
    _require_no_authority(current, reason_code="CONTRACT_POINTER_AUTHORITY_INVALID")
    revision_id = current.get("revision_id")
    if not isinstance(revision_id, str):
        _fail("CONTRACT_POINTER_REVISION_INVALID", f"missing revision identity: {path}")
    revision = _load_revision(continuation_root, revision_id)
    return current, revision


def _seen_path(continuation_root: Path, source_fingerprint: str) -> Path:
    return continuation_root / "seen" / f"{source_fingerprint}.json"


def _observation_path(continuation_root: Path, observation_id: str) -> Path:
    return continuation_root / "observations" / observation_id / "observation.json"


def _status_path(continuation_root: Path, observation_id: str) -> Path:
    return continuation_root / "observations" / observation_id / "status.json"


def _write_seen(
    continuation_root: Path,
    fact: Mapping[str, Any],
    *,
    disposition: str,
    revision_id: str,
) -> str:
    value = {
        "schema": SEEN_SOURCE_SCHEMA,
        "source_fingerprint": fact["source_fingerprint"],
        "logical_identity": fact["logical_identity"],
        "source": fact["source"],
        "disposition": disposition,
        "contract_revision_id": revision_id,
        "protocol_stage": PROTOCOL_STAGE,
        **_NO_AUTHORITY,
    }
    return _write_once_json(
        _seen_path(continuation_root, str(fact["source_fingerprint"])),
        value,
        conflict_code="CONTINUATION_SEEN_CONFLICT",
    )


def _acquire_adapter_lock(continuation_root: Path) -> Any | None:
    return _try_acquire_byte_lock(continuation_root / ".adapter.lock")


def _validate_binding(binding: Mapping[str, Any]) -> dict[str, str]:
    path_value = binding.get("path")
    sha_value = binding.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        _fail("CONTRACT_BINDING_PATH_INVALID", "source binding path is required")
    if not isinstance(sha_value, str) or not _HEX_SHA256.fullmatch(sha_value.casefold()):
        _fail("CONTRACT_BINDING_SHA256_INVALID", "source binding sha256 is required")
    try:
        path = Path(path_value).resolve(strict=True)
        observed_sha256 = _sha256(path.read_bytes())
    except OSError as exc:
        raise ContinuationError(
            "CONTRACT_BINDING_SOURCE_UNREADABLE",
            f"source binding cannot be read: {path_value}",
        ) from exc
    if observed_sha256 != sha_value.casefold():
        _fail("CONTRACT_BINDING_HASH_MISMATCH", f"source binding changed: {path}")
    return {"path": str(path), "sha256": sha_value.casefold()}


def initialize_contract(
    runtime_root: Path,
    *,
    contract_name: str,
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Explicitly bind the current source inventory as inert history."""

    runtime_root = runtime_root.resolve(strict=False)
    continuation_root = _continuation_root(runtime_root)
    guard = _acquire_adapter_lock(continuation_root)
    if guard is None:
        return {"outcome": "LOCK_BUSY", "created": False, **_NO_AUTHORITY}
    try:
        current_path = continuation_root / "contracts" / "current.json"
        if current_path.exists():
            _load_current(continuation_root)
            _fail("CONTRACT_ALREADY_BOUND", f"a current contract already exists: {current_path}")

        revisions_root = continuation_root / "contracts" / "revisions"
        revision_paths = sorted(revisions_root.glob("*.json")) if revisions_root.is_dir() else []
        if len(revision_paths) > 1:
            _fail("CONTRACT_UNPUBLISHED_AMBIGUOUS", "multiple unpublished contract revisions exist")

        if revision_paths:
            revision_id = revision_paths[0].stem.casefold()
            revision = _load_revision(continuation_root, revision_id)
            if revision.get("contract_name") != contract_name:
                _fail("CONTRACT_UNPUBLISHED_NAME_MISMATCH", "unpublished contract name differs")
            if revision.get("source_binding") != _validate_binding(source_binding):
                _fail("CONTRACT_UNPUBLISHED_BINDING_MISMATCH", "unpublished binding differs")
        else:
            binding = _validate_binding(source_binding)
            facts, incident_ids = _scan_receipts(runtime_root, continuation_root)
            by_logical: dict[str, str] = {}
            for fact in facts:
                logical = str(fact["logical_identity"])
                fingerprint = str(fact["source_fingerprint"])
                prior = by_logical.setdefault(logical, fingerprint)
                if prior != fingerprint:
                    _fail(
                        "BASELINE_SOURCE_IDENTITY_CONFLICT",
                        "two receipt byte identities claim the same cell_id and run_id",
                    )
            baseline = sorted(
                (
                    {
                        "source_fingerprint": fact["source_fingerprint"],
                        "logical_identity": fact["logical_identity"],
                        "source": fact["source"],
                    }
                    for fact in facts
                ),
                key=lambda row: str(row["source_fingerprint"]),
            )
            revision = {
                "schema": CONTRACT_SCHEMA,
                "contract_name": contract_name,
                "protocol_stage": PROTOCOL_STAGE,
                "source_root": str(runtime_root),
                "source_glob": RECEIPT_GLOB,
                "accepted_source_schemas": list(ACCEPTED_RUN_SCHEMAS),
                "source_binding": binding,
                "baseline": baseline,
                "baseline_incident_ids": sorted(set(incident_ids)),
                "wake_semantics": "UNSEEN_VALID_DURABLE_RECEIPT_ONLY",
                "nonclaims": [
                    "NO_REENTRY_REQUEST",
                    "NO_MAIN_LAUNCH",
                    "NO_COMPUTE_SELECTION",
                    "NO_SCIENTIFIC_MEANING",
                    "NO_SHARED_EFFECT",
                    "NO_PARENT_COMPLETION",
                ],
                **_NO_AUTHORITY,
            }
            revision_raw = canonical_json_bytes(revision)
            revision_id = _sha256(revision_raw)
            _write_once_json(
                revisions_root / f"{revision_id}.json",
                revision,
                conflict_code="CONTRACT_REVISION_CONFLICT",
            )

        baseline_rows = revision.get("baseline")
        if not isinstance(baseline_rows, list):
            _fail("CONTRACT_BASELINE_INVALID", "contract baseline must be a list")
        for row in baseline_rows:
            if not isinstance(row, Mapping):
                _fail("CONTRACT_BASELINE_INVALID", "contract baseline row must be an object")
            _write_seen(
                continuation_root,
                row,
                disposition="BOUND_BASELINE",
                revision_id=revision_id,
            )

        current = {
            "schema": CONTRACT_POINTER_SCHEMA,
            "revision_id": revision_id,
            "status": "LIVE",
            "published_at": now_iso(),
            "protocol_stage": PROTOCOL_STAGE,
            **_NO_AUTHORITY,
        }
        atomic_write_json(current_path, current)
        projection = _rebuild_projection(
            continuation_root,
            current=current,
            revision=revision,
            new_observation_ids=[],
            incident_ids=[],
        )
        return {
            "outcome": "BOUND",
            "created": True,
            "revision_id": revision_id,
            "baseline_count": len(baseline_rows),
            "observation_count": projection["observation_count"],
            **_NO_AUTHORITY,
        }
    finally:
        _release_byte_lock(guard)


def _known_sources(
    continuation_root: Path, revision: Mapping[str, Any]
) -> tuple[dict[str, str], set[str], dict[str, dict[str, Any]]]:
    by_logical: dict[str, str] = {}
    fingerprints: set[str] = set()
    source_by_fingerprint: dict[str, dict[str, Any]] = {}
    baseline = revision.get("baseline")
    if not isinstance(baseline, list):
        _fail("CONTRACT_BASELINE_INVALID", "contract baseline must be a list")
    for row in baseline:
        if not isinstance(row, Mapping):
            _fail("CONTRACT_BASELINE_INVALID", "contract baseline row must be an object")
        logical = row.get("logical_identity")
        fingerprint = row.get("source_fingerprint")
        source = row.get("source")
        if (
            not isinstance(logical, str)
            or not isinstance(fingerprint, str)
            or not isinstance(source, Mapping)
        ):
            _fail("CONTRACT_BASELINE_INVALID", "contract baseline identity is invalid")
        prior = by_logical.setdefault(logical, fingerprint)
        if prior != fingerprint:
            _fail("CONTRACT_BASELINE_CONFLICT", "contract baseline has conflicting identities")
        fingerprints.add(fingerprint)
        source_by_fingerprint[fingerprint] = dict(source)

    observations_root = continuation_root / "observations"
    for path in (
        sorted(observations_root.glob("*/observation.json")) if observations_root.is_dir() else []
    ):
        observation = _read_json_object(path, reason_code="OBSERVATION_RECORD_INVALID")
        if observation.get("schema") != CONTINUATION_OBSERVATION_SCHEMA:
            _fail("OBSERVATION_RECORD_SCHEMA_INVALID", f"invalid observation record: {path}")
        _require_no_authority(
            observation,
            reason_code="OBSERVATION_RECORD_AUTHORITY_INVALID",
        )
        logical = observation.get("logical_identity")
        fingerprint = observation.get("source_fingerprint")
        observation_id = observation.get("observation_id")
        source = observation.get("source")
        if (
            not isinstance(logical, str)
            or not isinstance(fingerprint, str)
            or observation_id != fingerprint
            or path.parent.name != observation_id
            or not isinstance(source, Mapping)
        ):
            _fail("OBSERVATION_RECORD_IDENTITY_INVALID", f"invalid observation identity: {path}")
        prior = by_logical.setdefault(logical, fingerprint)
        if prior != fingerprint:
            _fail(
                "OBSERVATION_LOGICAL_IDENTITY_CONFLICT",
                "observation store has conflicting identities",
            )
        fingerprints.add(fingerprint)
        prior_source = source_by_fingerprint.setdefault(fingerprint, dict(source))
        if prior_source != dict(source):
            _fail(
                "OBSERVATION_SOURCE_IDENTITY_CONFLICT",
                "same fingerprint has different stored source facts",
            )
    return by_logical, fingerprints, source_by_fingerprint


def _validate_seen(
    continuation_root: Path,
    fact: Mapping[str, Any],
    *,
    disposition: str,
) -> None:
    fingerprint = str(fact["source_fingerprint"])
    path = _seen_path(continuation_root, fingerprint)
    seen = _read_json_object(path, reason_code="SEEN_RECORD_INVALID")
    if (
        seen.get("schema") != SEEN_SOURCE_SCHEMA
        or seen.get("source_fingerprint") != fingerprint
        or seen.get("logical_identity") != fact["logical_identity"]
        or seen.get("source") != fact["source"]
        or seen.get("disposition") != disposition
    ):
        _fail("SEEN_RECORD_IDENTITY_INVALID", f"invalid seen record: {path}")
    _require_no_authority(seen, reason_code="SEEN_RECORD_AUTHORITY_INVALID")


def _write_observation(
    continuation_root: Path,
    fact: Mapping[str, Any],
    *,
    revision_id: str,
) -> str:
    observation_id = str(fact["source_fingerprint"])
    value = {
        "schema": CONTINUATION_OBSERVATION_SCHEMA,
        "observation_id": observation_id,
        "source_fingerprint": observation_id,
        "logical_identity": fact["logical_identity"],
        "source": fact["source"],
        "contract_revision_id": revision_id,
        "protocol_stage": PROTOCOL_STAGE,
        "observation_semantics": "DURABLE_FACT_DETECTED_NOT_REENTRY_AUTHORIZATION",
        **_NO_AUTHORITY,
    }
    return _write_once_json(
        _observation_path(continuation_root, observation_id),
        value,
        conflict_code="CONTINUATION_OBSERVATION_CONFLICT",
    )


def _ensure_observation_status(continuation_root: Path, observation_id: str) -> None:
    path = _status_path(continuation_root, observation_id)
    if path.exists():
        status = _read_json_object(path, reason_code="OBSERVATION_STATUS_INVALID")
        if (
            status.get("schema") != OBSERVATION_STATUS_SCHEMA
            or status.get("observation_id") != observation_id
        ):
            _fail("OBSERVATION_STATUS_IDENTITY_INVALID", f"invalid observation status: {path}")
        _require_no_authority(
            status,
            reason_code="OBSERVATION_STATUS_AUTHORITY_INVALID",
        )
        return
    atomic_write_json(
        path,
        {
            "schema": OBSERVATION_STATUS_SCHEMA,
            "observation_id": observation_id,
            "status": "OBSERVED_STAGE0_ONLY",
            "observed_at": now_iso(),
            "protocol_stage": PROTOCOL_STAGE,
            **_NO_AUTHORITY,
        },
    )


def _write_identity_drift_incident(
    continuation_root: Path,
    fact: Mapping[str, Any],
    *,
    expected_fingerprint: str,
) -> str:
    identity = {
        "reason_code": "SOURCE_LOGICAL_IDENTITY_DRIFT",
        "logical_identity": fact["logical_identity"],
        "expected_source_fingerprint": expected_fingerprint,
        "observed_source_fingerprint": fact["source_fingerprint"],
        "relative_path": fact["source"]["relative_path"],
        "source_file_sha256": fact["source"]["receipt_file_sha256"],
    }
    incident_id = _stable_id(identity)
    incident = {
        "schema": INCIDENT_SCHEMA,
        "incident_id": incident_id,
        **identity,
        "protocol_stage": PROTOCOL_STAGE,
        **_NO_AUTHORITY,
    }
    _write_incident(continuation_root, incident)
    return incident_id


def _write_file_bytes_drift_incident(
    continuation_root: Path,
    fact: Mapping[str, Any],
    *,
    expected_source: Mapping[str, Any],
) -> str:
    identity = {
        "reason_code": "SOURCE_FILE_BYTES_DRIFT",
        "logical_identity": fact["logical_identity"],
        "source_fingerprint": fact["source_fingerprint"],
        "relative_path": fact["source"]["relative_path"],
        "expected_source_file_sha256": expected_source.get("receipt_file_sha256"),
        "observed_source_file_sha256": fact["source"]["receipt_file_sha256"],
    }
    incident_id = _stable_id(identity)
    incident = {
        "schema": INCIDENT_SCHEMA,
        "incident_id": incident_id,
        **identity,
        "protocol_stage": PROTOCOL_STAGE,
        **_NO_AUTHORITY,
    }
    _write_incident(continuation_root, incident)
    return incident_id


def _rebuild_projection(
    continuation_root: Path,
    *,
    current: Mapping[str, Any],
    revision: Mapping[str, Any],
    new_observation_ids: Sequence[str],
    incident_ids: Sequence[str],
) -> dict[str, Any]:
    observation_paths = sorted((continuation_root / "observations").glob("*/observation.json"))
    seen_paths = sorted((continuation_root / "seen").glob("*.json"))
    all_incident_paths = sorted((continuation_root / "incidents").glob("*.json"))
    projection = {
        "schema": PROJECTION_SCHEMA,
        "protocol_stage": PROTOCOL_STAGE,
        "contract_revision_id": current["revision_id"],
        "contract_status": current["status"],
        "source_root": revision["source_root"],
        "source_glob": revision["source_glob"],
        "baseline_count": len(revision.get("baseline", [])),
        "seen_count": len(seen_paths),
        "observation_count": len(observation_paths),
        "incident_count": len(all_incident_paths),
        "new_observation_ids": sorted(new_observation_ids),
        "scan_incident_ids": sorted(set(incident_ids)),
        "last_reconciled_at": now_iso(),
        **_NO_AUTHORITY,
    }
    atomic_write_json(continuation_root / "projection" / "current.json", projection)
    return projection


def reconcile(runtime_root: Path = DEFAULT_RUNTIME_ROOT) -> dict[str, Any]:
    """Scan the authoritative receipt surface once and exit."""

    runtime_root = runtime_root.resolve(strict=False)
    continuation_root = _continuation_root(runtime_root)
    guard = _acquire_adapter_lock(continuation_root)
    if guard is None:
        return {"outcome": "LOCK_BUSY", "new_observation_ids": [], **_NO_AUTHORITY}
    try:
        current, revision = _load_current(continuation_root)
        if current["status"] == "STOPPED":
            projection = _rebuild_projection(
                continuation_root,
                current=current,
                revision=revision,
                new_observation_ids=[],
                incident_ids=[],
            )
            return {
                "outcome": "STOPPED",
                "new_observation_ids": [],
                "observation_count": projection["observation_count"],
                **_NO_AUTHORITY,
            }

        facts, incident_ids = _scan_receipts(runtime_root, continuation_root)
        by_logical, fingerprints, source_by_fingerprint = _known_sources(
            continuation_root, revision
        )
        new_observation_ids: list[str] = []
        revision_id = str(current["revision_id"])
        for fact in facts:
            logical = str(fact["logical_identity"])
            fingerprint = str(fact["source_fingerprint"])
            expected = by_logical.get(logical)
            if expected is not None and expected != fingerprint:
                incident_ids.append(
                    _write_identity_drift_incident(
                        continuation_root,
                        fact,
                        expected_fingerprint=expected,
                    )
                )
                continue

            if fingerprint in fingerprints:
                observation_path = _observation_path(continuation_root, fingerprint)
                stored_source = source_by_fingerprint[fingerprint]
                if stored_source.get("receipt_file_sha256") != fact["source"].get(
                    "receipt_file_sha256"
                ):
                    incident_ids.append(
                        _write_file_bytes_drift_incident(
                            continuation_root,
                            fact,
                            expected_source=stored_source,
                        )
                    )
                    continue
                stored_fact = {
                    "source_fingerprint": fingerprint,
                    "logical_identity": logical,
                    "source": stored_source,
                }
                disposition = (
                    "CONTINUATION_OBSERVATION_RECORDED"
                    if observation_path.is_file()
                    else "BOUND_BASELINE"
                )
                seen_path = _seen_path(continuation_root, fingerprint)
                if seen_path.is_file():
                    _validate_seen(
                        continuation_root,
                        stored_fact,
                        disposition=disposition,
                    )
                else:
                    _write_seen(
                        continuation_root,
                        stored_fact,
                        disposition=disposition,
                        revision_id=revision_id,
                    )
                if observation_path.is_file():
                    _ensure_observation_status(continuation_root, fingerprint)
                continue

            # Observation first, then seen.  A crash between them is repaired by
            # the next scan; the inverse order could durably lose the observation.
            _write_observation(continuation_root, fact, revision_id=revision_id)
            _write_seen(
                continuation_root,
                fact,
                disposition="CONTINUATION_OBSERVATION_RECORDED",
                revision_id=revision_id,
            )
            _ensure_observation_status(continuation_root, fingerprint)
            by_logical[logical] = fingerprint
            fingerprints.add(fingerprint)
            source_by_fingerprint[fingerprint] = dict(fact["source"])
            new_observation_ids.append(fingerprint)

        projection = _rebuild_projection(
            continuation_root,
            current=current,
            revision=revision,
            new_observation_ids=new_observation_ids,
            incident_ids=incident_ids,
        )
        return {
            "outcome": "RECONCILED",
            "new_observation_ids": new_observation_ids,
            "observation_count": projection["observation_count"],
            "incident_count": projection["incident_count"],
            **_NO_AUTHORITY,
        }
    finally:
        _release_byte_lock(guard)


def stop_contract(runtime_root: Path, *, expected_revision_id: str) -> dict[str, Any]:
    """Stop future detection without deleting receipts, observations, or evidence."""

    runtime_root = runtime_root.resolve(strict=False)
    continuation_root = _continuation_root(runtime_root)
    guard = _acquire_adapter_lock(continuation_root)
    if guard is None:
        return {"outcome": "LOCK_BUSY", **_NO_AUTHORITY}
    try:
        current, revision = _load_current(continuation_root)
        if current["revision_id"] != expected_revision_id:
            _fail("CONTRACT_EXPECTED_REVISION_MISMATCH", "current contract revision changed")
        if current["status"] == "STOPPED":
            return {
                "outcome": "ALREADY_STOPPED",
                "revision_id": expected_revision_id,
                **_NO_AUTHORITY,
            }
        stopped = {
            **current,
            "status": "STOPPED",
            "stopped_at": now_iso(),
        }
        atomic_write_json(continuation_root / "contracts" / "current.json", stopped)
        _rebuild_projection(
            continuation_root,
            current=stopped,
            revision=revision,
            new_observation_ids=[],
            incident_ids=[],
        )
        return {"outcome": "STOPPED", "revision_id": expected_revision_id, **_NO_AUTHORITY}
    finally:
        _release_byte_lock(guard)


def status(runtime_root: Path = DEFAULT_RUNTIME_ROOT) -> dict[str, Any]:
    """Read and validate the current contract and materialized Stage 0 counts."""

    runtime_root = runtime_root.resolve(strict=False)
    continuation_root = _continuation_root(runtime_root)
    current, revision = _load_current(continuation_root)
    observation_count = len(list((continuation_root / "observations").glob("*/observation.json")))
    incident_count = len(list((continuation_root / "incidents").glob("*.json")))
    seen_count = len(list((continuation_root / "seen").glob("*.json")))
    return {
        "outcome": "READABLE",
        "protocol_stage": PROTOCOL_STAGE,
        "runtime_root": str(runtime_root),
        "revision_id": current["revision_id"],
        "contract_status": current["status"],
        "baseline_count": len(revision.get("baseline", [])),
        "seen_count": seen_count,
        "observation_count": observation_count,
        "incident_count": incident_count,
        **_NO_AUTHORITY,
    }


def request_continuation_reconcile(
    *,
    receipt_path: Path | None,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    runner: Callable[..., object] | None = None,
    system_root: str | None = None,
) -> bool:
    """Ring the optional task after receipt commit; correctness never depends on it."""

    try:
        if receipt_path is None:
            return False
        runtime_root = runtime_root.resolve(strict=False)
        path = receipt_path.resolve(strict=False)
        _relative_receipt_parts(path, runtime_root)
        current, _revision = _load_current(_continuation_root(runtime_root))
        if current.get("status") != "LIVE":
            return False
        windows_root = system_root or os.environ.get("SystemRoot", "")
        if not windows_root:
            return False
        schtasks = Path(windows_root) / "System32" / "schtasks.exe"
        if not schtasks.is_file():
            return False
        invoke = runner or subprocess.Popen
        invoke(
            [str(schtasks), "/Run", "/TN", CONTINUATION_TASK_NAME],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False
