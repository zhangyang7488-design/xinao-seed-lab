"""Immutable wild research candidate pool (content-addressed by result_sha256).

Ingest means "admitted as a wild candidate identity", not Owner adoption.
Reuses ``researcher_result_adapter`` verification and PolicyCandidateVersion mint;
does not invent a second loose validator.

CAS layout (exclusive create; fail-closed on content conflict)::

    <pool_root>/
      objects/sha256/<ab>/<result_sha256>.json   # sealed CandidatePoolEntry
      objects/result/<ab>/<result_sha256>.bin    # raw result.json bytes
      objects/receipt/<ab>/<result_sha256>.json  # raw receipt object

Same hash with different bytes, receipt mismatch, or overwrite attempts fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import PolicyCandidateVersion
from xinao.science.researcher_result_adapter import (
    ResearcherResultAdapterError,
    mint_policy_candidate_from_verified_binding,
    raw_sha256,
    verify_researcher_result_against_receipt,
)

POOL_SCHEMA_VERSION: Final = "xinao.research_candidate_pool_entry.v1"
POOL_MARKER: Final = "XINAO_RESEARCH_CANDIDATE_POOL_V1"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CandidatePoolError(ValueError):
    """Fail-closed candidate pool rejection with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, reason_code: str, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise CandidatePoolError(reason_code, f"{label} must be lowercase sha256")
    return value


def _resolve_pool_root(pool_root: Path) -> Path:
    return pool_root.expanduser().resolve()


def pool_entry_path(pool_root: Path, result_sha256: str) -> Path:
    digest = _require_hex64(result_sha256, "POOL_RESULT_HASH_INVALID", "result_sha256")
    base = _resolve_pool_root(pool_root)
    return base / "objects" / "sha256" / digest[:2] / f"{digest}.json"


def pool_result_bytes_path(pool_root: Path, result_sha256: str) -> Path:
    digest = _require_hex64(result_sha256, "POOL_RESULT_HASH_INVALID", "result_sha256")
    base = _resolve_pool_root(pool_root)
    return base / "objects" / "result" / digest[:2] / f"{digest}.bin"


def pool_receipt_path(pool_root: Path, result_sha256: str) -> Path:
    digest = _require_hex64(result_sha256, "POOL_RESULT_HASH_INVALID", "result_sha256")
    base = _resolve_pool_root(pool_root)
    return base / "objects" / "receipt" / digest[:2] / f"{digest}.json"


def _write_new_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
    except FileExistsError as exc:
        raise CandidatePoolError(
            "POOL_CAS_EXCLUSIVE_CREATE_REJECTED",
            f"already exists: {path.name}",
        ) from exc


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    body = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_new_bytes(path, body.encode("utf-8"))


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise CandidatePoolError("POOL_ENTRY_MISSING", str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CandidatePoolError("POOL_KNOWLEDGE_CUTOFF_INVALID", "timezone-aware required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_candidate_pool_entry(
    *,
    binding: Mapping[str, Any],
    policy_candidate: PolicyCandidateVersion,
    result_bytes_sha256: str,
    receipt_raw_sha256: str,
) -> dict[str, Any]:
    """Build a sealed pool entry body. owner_adopted is always false."""

    result_sha256 = _require_hex64(
        binding.get("result_sha256"),
        "POOL_RESULT_HASH_INVALID",
        "result_sha256",
    )
    if result_sha256 != result_bytes_sha256:
        raise CandidatePoolError(
            "POOL_RESULT_HASH_DRIFT",
            f"binding={result_sha256} bytes={result_bytes_sha256}",
        )
    receipt_content_sha256 = _require_hex64(
        binding.get("receipt_content_sha256"),
        "POOL_RECEIPT_HASH_INVALID",
        "receipt_content_sha256",
    )
    if policy_candidate.content_hash is None:
        raise CandidatePoolError("POOL_POLICY_CANDIDATE_UNSEALED", "content_hash required")
    knowledge_cutoff = binding.get("knowledge_cutoff")
    if not isinstance(knowledge_cutoff, datetime):
        raise CandidatePoolError("POOL_KNOWLEDGE_CUTOFF_INVALID", "datetime required")

    body: dict[str, Any] = {
        "schema_version": POOL_SCHEMA_VERSION,
        "pool_marker": POOL_MARKER,
        "result_sha256": result_sha256,
        "receipt_content_sha256": receipt_content_sha256,
        "receipt_raw_sha256": _require_hex64(
            receipt_raw_sha256,
            "POOL_RECEIPT_RAW_HASH_INVALID",
            "receipt_raw_sha256",
        ),
        "run_id": str(binding["run_id"]),
        "status": str(binding["status"]),
        "knowledge_cutoff": _iso_utc(knowledge_cutoff),
        "policy_ref": policy_candidate.policy_ref,
        "policy_content_hash": policy_candidate.content_hash,
        "decision_map_ref": policy_candidate.decision_signature.decision_map_ref,
        "decision_map_projected": False,
        "action_support": "NOT_PROJECTED",
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "candidate": dict(binding["candidate"]),
    }
    content_hash = canonical_sha256(body)
    sealed = {**body, "content_hash": content_hash}
    return sealed


def entry_content_without_hash(entry: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(entry)
    body.pop("content_hash", None)
    return body


def verify_pool_entry_seal(entry: Mapping[str, Any]) -> str:
    if entry.get("schema_version") != POOL_SCHEMA_VERSION:
        raise CandidatePoolError("POOL_ENTRY_SCHEMA_DRIFT", str(entry.get("schema_version")))
    if entry.get("owner_adopted") is not False:
        raise CandidatePoolError("POOL_OWNER_ADOPTED_FORBIDDEN", "ingest cannot claim adoption")
    if entry.get("completion_claim_allowed") is not False:
        raise CandidatePoolError("POOL_COMPLETION_CLAIM_FORBIDDEN", "must be false")
    if entry.get("scientific_promotion") is not False:
        raise CandidatePoolError("POOL_SCIENTIFIC_PROMOTION_FORBIDDEN", "must be false")
    if entry.get("decision_map_projected") is not False:
        raise CandidatePoolError("POOL_DECISION_MAP_PROJECTED_FORBIDDEN", "must be false")
    observed = entry.get("content_hash")
    expected = canonical_sha256(entry_content_without_hash(entry))
    if not isinstance(observed, str) or observed != expected:
        raise CandidatePoolError(
            "POOL_ENTRY_SEAL_INVALID",
            f"observed={observed} expected={expected}",
        )
    return expected


def ingest_verified_research_result(
    *,
    pool_root: Path,
    result_bytes: bytes,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify result+receipt, mint not-projected identity, exclusive-create pool entry.

    Wild / overfit / black-box candidates are allowed. Ingest never sets owner_adopted.
    """

    if not isinstance(result_bytes, (bytes, bytearray)) or not result_bytes:
        raise CandidatePoolError("POOL_RESULT_BYTES_INVALID", "non-empty bytes required")
    raw_result = bytes(result_bytes)
    try:
        binding = verify_researcher_result_against_receipt(raw_result, receipt)
        policy = mint_policy_candidate_from_verified_binding(binding)
    except ResearcherResultAdapterError as exc:
        raise CandidatePoolError(exc.reason_code, exc.detail) from exc

    result_sha256 = str(binding["result_sha256"])
    if raw_sha256(raw_result) != result_sha256:
        raise CandidatePoolError("POOL_RESULT_HASH_DRIFT", "raw bytes hash drift")

    # Canonicalize receipt for durable storage identity (stable field order).
    receipt_obj = dict(receipt)
    receipt_bytes = (
        json.dumps(receipt_obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    receipt_raw_sha256 = hashlib.sha256(receipt_bytes).hexdigest()

    entry = build_candidate_pool_entry(
        binding=binding,
        policy_candidate=policy,
        result_bytes_sha256=result_sha256,
        receipt_raw_sha256=receipt_raw_sha256,
    )
    entry_path = pool_entry_path(pool_root, result_sha256)
    result_path = pool_result_bytes_path(pool_root, result_sha256)
    receipt_path = pool_receipt_path(pool_root, result_sha256)

    if entry_path.is_file() or result_path.is_file() or receipt_path.is_file():
        # Same-hash idempotent success only when all artifacts match exactly.
        if not (entry_path.is_file() and result_path.is_file() and receipt_path.is_file()):
            raise CandidatePoolError(
                "POOL_CAS_PARTIAL_STATE",
                "incomplete prior CAS objects for this result_sha256",
            )
        existing_entry = _read_json(entry_path)
        existing_result = result_path.read_bytes()
        existing_receipt_bytes = receipt_path.read_bytes()
        if (
            existing_result != raw_result
            or existing_receipt_bytes != receipt_bytes
            or existing_entry != entry
        ):
            raise CandidatePoolError(
                "POOL_CAS_CONTENT_CONFLICT",
                f"result_sha256={result_sha256} already sealed with different content",
            )
        verify_pool_entry_seal(existing_entry)
        return dict(existing_entry)

    # Exclusive create in order: result bytes → receipt → sealed entry.
    _write_new_bytes(result_path, raw_result)
    try:
        _write_new_bytes(receipt_path, receipt_bytes)
    except CandidatePoolError:
        # Best-effort: leave result blob; loaders require all three.
        raise
    try:
        _write_new_json(entry_path, entry)
    except CandidatePoolError as exc:
        if exc.reason_code == "POOL_CAS_EXCLUSIVE_CREATE_REJECTED":
            # Race: another writer sealed; require exact match.
            existing = _read_json(entry_path)
            if existing != entry:
                raise CandidatePoolError(
                    "POOL_CAS_CONTENT_CONFLICT",
                    f"result_sha256={result_sha256} race conflict",
                ) from exc
            return dict(existing)
        raise
    return entry


def load_pool_entry(pool_root: Path, result_sha256: str) -> dict[str, Any]:
    """Load and re-verify a sealed pool entry plus CAS byte bindings."""

    digest = _require_hex64(result_sha256, "POOL_RESULT_HASH_INVALID", "result_sha256")
    entry_path = pool_entry_path(pool_root, digest)
    result_path = pool_result_bytes_path(pool_root, digest)
    receipt_path = pool_receipt_path(pool_root, digest)
    if not entry_path.is_file():
        raise CandidatePoolError("POOL_ENTRY_MISSING", digest)
    if not result_path.is_file() or not receipt_path.is_file():
        raise CandidatePoolError("POOL_CAS_PARTIAL_STATE", digest)

    entry = _read_json(entry_path)
    if not isinstance(entry, Mapping):
        raise CandidatePoolError("POOL_ENTRY_INVALID", "JSON object required")
    entry_dict = dict(entry)
    verify_pool_entry_seal(entry_dict)
    if entry_dict.get("result_sha256") != digest:
        raise CandidatePoolError(
            "POOL_ENTRY_HASH_MISMATCH",
            f"path={digest} body={entry_dict.get('result_sha256')}",
        )

    raw_result = result_path.read_bytes()
    if raw_sha256(raw_result) != digest:
        raise CandidatePoolError("POOL_RESULT_BYTES_TAMPERED", digest)
    receipt_raw = receipt_path.read_bytes()
    if hashlib.sha256(receipt_raw).hexdigest() != entry_dict.get("receipt_raw_sha256"):
        raise CandidatePoolError("POOL_RECEIPT_BYTES_TAMPERED", digest)

    # Re-bind through the strict adapter (fail closed on any drift).
    receipt_obj = json.loads(receipt_raw.decode("utf-8"))
    try:
        binding = verify_researcher_result_against_receipt(raw_result, receipt_obj)
    except ResearcherResultAdapterError as exc:
        raise CandidatePoolError(exc.reason_code, exc.detail) from exc
    if binding["result_sha256"] != digest:
        raise CandidatePoolError("POOL_RESULT_HASH_DRIFT", "re-verify drift")
    if binding["receipt_content_sha256"] != entry_dict.get("receipt_content_sha256"):
        raise CandidatePoolError("POOL_RECEIPT_CONTENT_HASH_DRIFT", "re-verify drift")
    return entry_dict


def load_pool_result_bytes(pool_root: Path, result_sha256: str) -> bytes:
    entry = load_pool_entry(pool_root, result_sha256)
    path = pool_result_bytes_path(pool_root, str(entry["result_sha256"]))
    return path.read_bytes()


__all__ = [
    "POOL_MARKER",
    "POOL_SCHEMA_VERSION",
    "CandidatePoolError",
    "build_candidate_pool_entry",
    "ingest_verified_research_result",
    "load_pool_entry",
    "load_pool_result_bytes",
    "pool_entry_path",
    "pool_receipt_path",
    "pool_result_bytes_path",
    "verify_pool_entry_seal",
]
