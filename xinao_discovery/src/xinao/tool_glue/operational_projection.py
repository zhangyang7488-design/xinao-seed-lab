"""CAS install/promote/recover/rollback for SI operational script projections.

Canonical source is the package resource.  The Situation Island script path is
only an operational projection.  Promotion is journaled, same-byte, and
recoverable; callers never need a manual copy step.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from xinao.tool_glue.canonical_paths import (
    DEFAULT_ISLAND_ROOT,
    DEFAULT_OPERATIONAL_STATE_ROOT,
    discover_canonical_updater_path,
    operational_updater_path,
)
from xinao.tool_glue.publication import (
    APPLYING,
    PREPARED,
    ROLLED_BACK_VERIFIED,
    ROLLING_BACK,
    VERIFIED,
    PublicationError,
    _assert_current_hash,
    _atomic_replace_bytes,
    _capture_file_metadata,
    _journal_path,
    _marker_path,
    _normalized_sha256,
    _persist_journal_and_marker,
    _read_object,
    _remove_marker,
    _seal_archive_bytes,
    _write_json_atomic,
    sha256_bytes,
    sha256_file,
)

JOURNAL_SCHEMA = "xinao.tool_glue_operational_projection_transaction.v1"
MARKER_SCHEMA = "xinao.tool_glue_operational_projection_marker.v1"
RESULT_SCHEMA = "xinao.tool_glue_operational_projection_result.v1"
ARTIFACT_KIND = "operational_updater"

AUTHORITY_APPLIED = "OPERATIONAL_APPLIED"


def _transaction_id(value: str | None) -> str:
    return value or f"op-proj-{uuid.uuid4().hex}"


def _marker_payload(operational_path: Path, journal_path: Path, journal: dict[str, Any]) -> dict:
    return {
        "schema_version": MARKER_SCHEMA,
        "operational_path": str(operational_path),
        "journal_path": str(journal_path),
        "transaction_id": journal.get("transaction_id"),
        "status": journal.get("status"),
        "completion_claim_allowed": False,
    }


def _result(
    journal: dict[str, Any], *, journal_path: Path, operational_path: Path
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "status": journal.get("status"),
        "transaction_id": journal.get("transaction_id"),
        "journal_path": str(journal_path),
        "operational_path": str(operational_path),
        "canonical_path": journal.get("canonical_path"),
        "expected_new_sha256": journal.get("expected_new_sha256"),
        "expected_old_sha256": journal.get("expected_old_sha256"),
        "completion_claim_allowed": False,
    }


def _load_canonical_bytes() -> tuple[Path, bytes, str]:
    canonical = discover_canonical_updater_path()
    raw = canonical.read_bytes()
    digest = sha256_bytes(raw)
    if sha256_file(canonical) != digest:
        raise PublicationError("CANONICAL_UPDATER_DRIFT", "canonical updater changed while reading")
    return canonical, raw, digest


def install_operational_updater(
    *,
    island_root: Path = DEFAULT_ISLAND_ROOT,
    state_root: Path = DEFAULT_OPERATIONAL_STATE_ROOT,
    expected_old_sha256: str | None = None,
    transaction_id: str | None = None,
    allow_create: bool = True,
) -> dict[str, Any]:
    """CAS-promote package-canonical updater bytes onto the SI operational path."""

    island_root = island_root.resolve()
    state_root = state_root.resolve()
    operational = operational_updater_path(island_root=island_root)
    operational.parent.mkdir(parents=True, exist_ok=True)
    canonical, candidate_bytes, new_digest = _load_canonical_bytes()

    recovered = recover_operational_updater(
        island_root=island_root,
        state_root=state_root,
    )
    if recovered["status"] != "NO_INTERRUPTED_TRANSACTION":
        raise PublicationError(
            "RECOVERED_TRANSACTION_RETRY_REQUIRED",
            "an interrupted operational projection transaction was recovered; retry install",
            receipt={"recovery": recovered},
        )

    if operational.is_file():
        old_digest = sha256_file(operational)
        if expected_old_sha256 is not None:
            wanted = _normalized_sha256(expected_old_sha256, "expected_old_sha256")
            if old_digest != wanted:
                raise PublicationError(
                    "EXPECTED_OLD_MISMATCH",
                    f"operational updater hash mismatch: expected={wanted} observed={old_digest}",
                )
        if old_digest == new_digest:
            return {
                "schema_version": RESULT_SCHEMA,
                "status": VERIFIED,
                "transaction_id": None,
                "journal_path": None,
                "operational_path": str(operational),
                "canonical_path": str(canonical),
                "expected_new_sha256": new_digest,
                "expected_old_sha256": old_digest,
                "already_same_byte": True,
                "completion_claim_allowed": False,
            }
        preimage_bytes = operational.read_bytes()
        authority_metadata = _capture_file_metadata(operational)
    else:
        if not allow_create:
            raise PublicationError(
                "OPERATIONAL_UPDATER_MISSING",
                f"operational updater is missing and create is disabled: {operational}",
            )
        if expected_old_sha256 is not None:
            raise PublicationError(
                "EXPECTED_OLD_MISMATCH",
                "expected_old_sha256 was provided but operational updater does not exist",
            )
        old_digest = None
        preimage_bytes = None
        authority_metadata = None

    candidate_archive = _seal_archive_bytes(state_root, "candidates", candidate_bytes, new_digest)
    preimage_archive = None
    if preimage_bytes is not None and old_digest is not None:
        preimage_archive = _seal_archive_bytes(state_root, "preimages", preimage_bytes, old_digest)

    txid = _transaction_id(transaction_id)
    journal_path = _journal_path(state_root, txid).resolve()
    if journal_path.exists():
        raise PublicationError("TRANSACTION_EXISTS", f"transaction already exists: {txid}")
    marker_path = _marker_path(state_root).resolve()
    journal: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA,
        "transaction_id": txid,
        "status": PREPARED,
        "artifact_kind": ARTIFACT_KIND,
        "island_root": str(island_root),
        "operational_path": str(operational),
        "canonical_path": str(canonical),
        "expected_old_sha256": old_digest,
        "expected_new_sha256": new_digest,
        "candidate_archive_path": str(candidate_archive),
        "preimage_archive_path": str(preimage_archive) if preimage_archive else None,
        "authority_metadata": authority_metadata,
        "completion_claim_allowed": False,
    }
    try:
        _persist_journal_and_marker(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            authority_path=operational,
        )
        journal["status"] = APPLYING
        _persist_journal_and_marker(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            authority_path=operational,
        )
        if old_digest is not None:
            _assert_current_hash(operational, old_digest, "EXPECTED_OLD_MISMATCH_BEFORE_REPLACE")
        if sha256_file(candidate_archive) != new_digest:
            raise PublicationError("ARCHIVE_BINDING_DRIFT", "candidate archive drifted")
        _atomic_replace_bytes(
            operational,
            candidate_archive.read_bytes(),
            metadata=authority_metadata,
        )
        _assert_current_hash(operational, new_digest, "OPERATIONAL_REPLACE_FAILED")
        journal["status"] = AUTHORITY_APPLIED
        _persist_journal_and_marker(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            authority_path=operational,
        )
        # Fresh-process same-byte readback closes install without trusting the write handle.
        if sha256_file(operational) != new_digest:
            raise PublicationError(
                "OPERATIONAL_READBACK_MISMATCH",
                "fresh-process operational readback does not match canonical digest",
            )
        if sha256_file(discover_canonical_updater_path()) != new_digest:
            raise PublicationError(
                "CANONICAL_READBACK_MISMATCH",
                "canonical resource drifted after operational promote",
            )
        journal["status"] = VERIFIED
        _persist_journal_and_marker(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            authority_path=operational,
        )
        receipt = _result(journal, journal_path=journal_path, operational_path=operational)
        _remove_marker(marker_path)
        return receipt
    except Exception as primary:
        failure = (
            primary
            if isinstance(primary, PublicationError)
            else PublicationError("OPERATIONAL_INSTALL_FAILED", str(primary))
        )
        if marker_path.is_file() or journal_path.is_file():
            try:
                recovery = recover_operational_updater(
                    island_root=island_root,
                    state_root=state_root,
                )
            except Exception as recovery_error:
                raise PublicationError(
                    failure.code,
                    str(failure),
                    receipt={
                        **failure.receipt,
                        "recovery_status": "FAILED",
                        "recovery_error": str(recovery_error),
                        "transaction_journal": str(journal_path),
                        "completion_claim_allowed": False,
                    },
                ) from primary
            if recovery.get("status") == VERIFIED:
                return {**recovery, "recovered_from_error_code": failure.code}
            raise PublicationError(
                failure.code,
                str(failure),
                receipt={
                    **failure.receipt,
                    "recovery": recovery,
                    "transaction_journal": str(journal_path),
                    "completion_claim_allowed": False,
                },
            ) from primary
        raise failure from primary


def _rollback_locked(
    *,
    journal: dict[str, Any],
    journal_path: Path,
    marker_path: Path,
    operational: Path,
) -> dict[str, Any]:
    preimage_path = journal.get("preimage_archive_path")
    old_digest = journal.get("expected_old_sha256")
    if not preimage_path or not old_digest:
        raise PublicationError(
            "ROLLBACK_PREIMAGE_MISSING",
            "cannot roll back an install that created the operational file without preimage",
        )
    preimage = Path(str(preimage_path))
    if sha256_file(preimage) != old_digest:
        raise PublicationError("ARCHIVE_BINDING_DRIFT", "preimage archive drifted")
    journal["status"] = ROLLING_BACK
    _persist_journal_and_marker(
        journal=journal,
        journal_path=journal_path,
        marker_path=marker_path,
        authority_path=operational,
    )
    metadata = journal.get("authority_metadata")
    _atomic_replace_bytes(
        operational,
        preimage.read_bytes(),
        metadata=metadata if isinstance(metadata, dict) else None,
    )
    _assert_current_hash(operational, str(old_digest), "ROLLBACK_REPLACE_FAILED")
    journal["status"] = ROLLED_BACK_VERIFIED
    _persist_journal_and_marker(
        journal=journal,
        journal_path=journal_path,
        marker_path=marker_path,
        authority_path=operational,
    )
    receipt = _result(journal, journal_path=journal_path, operational_path=operational)
    _remove_marker(marker_path)
    return receipt


def recover_operational_updater(
    *,
    island_root: Path = DEFAULT_ISLAND_ROOT,
    state_root: Path = DEFAULT_OPERATIONAL_STATE_ROOT,
) -> dict[str, Any]:
    """Recover one interrupted operational projection transaction."""

    island_root = island_root.resolve()
    state_root = state_root.resolve()
    operational = operational_updater_path(island_root=island_root)
    marker_path = _marker_path(state_root).resolve()
    if not marker_path.is_file():
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "NO_INTERRUPTED_TRANSACTION",
            "operational_path": str(operational),
            "completion_claim_allowed": False,
        }
    marker = _read_object(marker_path)
    journal_path = Path(str(marker["journal_path"])).resolve()
    journal = _read_object(journal_path)
    status = str(journal.get("status"))
    if status in {PREPARED, APPLYING}:
        # No confirmed mutation — drop marker and leave operational bytes alone.
        if journal.get("expected_old_sha256") and operational.is_file():
            current = sha256_file(operational)
            if current != journal.get("expected_old_sha256") and current != journal.get(
                "expected_new_sha256"
            ):
                raise PublicationError(
                    "FOREIGN_BYTE_BLOCK",
                    "operational path holds foreign bytes during recover; refuse mutation",
                )
        _remove_marker(marker_path)
        journal["status"] = ROLLED_BACK_VERIFIED
        journal["recovery_note"] = "cleared_pre_mutation_marker"
        _write_json_atomic(journal_path, journal)
        return _result(journal, journal_path=journal_path, operational_path=operational)
    if status == AUTHORITY_APPLIED:
        new_digest = str(journal.get("expected_new_sha256"))
        if operational.is_file() and sha256_file(operational) == new_digest:
            journal["status"] = VERIFIED
            _write_json_atomic(journal_path, journal)
            receipt = _result(journal, journal_path=journal_path, operational_path=operational)
            _remove_marker(marker_path)
            return receipt
        return _rollback_locked(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            operational=operational,
        )
    if status == ROLLING_BACK:
        return _rollback_locked(
            journal=journal,
            journal_path=journal_path,
            marker_path=marker_path,
            operational=operational,
        )
    if status in {VERIFIED, ROLLED_BACK_VERIFIED}:
        _remove_marker(marker_path)
        return _result(journal, journal_path=journal_path, operational_path=operational)
    raise PublicationError("JOURNAL_STATE_INVALID", f"cannot recover operational status: {status}")


def rollback_operational_updater(
    *,
    journal_path: Path,
    island_root: Path = DEFAULT_ISLAND_ROOT,
    state_root: Path = DEFAULT_OPERATIONAL_STATE_ROOT,
) -> dict[str, Any]:
    """Explicitly roll back one VERIFIED operational promotion from its preimage."""

    island_root = island_root.resolve()
    state_root = state_root.resolve()
    operational = operational_updater_path(island_root=island_root)
    journal_path = journal_path.resolve()
    marker_path = _marker_path(state_root).resolve()
    if marker_path.exists():
        raise PublicationError(
            "ACTIVE_TRANSACTION_EXISTS",
            "recover the active operational transaction before explicit rollback",
        )
    journal = _read_object(journal_path)
    if journal.get("status") != VERIFIED:
        raise PublicationError(
            "ROLLBACK_STATE_INVALID",
            "explicit rollback requires a VERIFIED operational journal",
        )
    _assert_current_hash(
        operational,
        str(journal["expected_new_sha256"]),
        "ROLLBACK_TARGET_NOT_NEW",
    )
    _write_json_atomic(
        marker_path,
        _marker_payload(operational, journal_path, journal),
    )
    return _rollback_locked(
        journal=journal,
        journal_path=journal_path,
        marker_path=marker_path,
        operational=operational,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--island-root",
        type=Path,
        default=DEFAULT_ISLAND_ROOT,
        help="Situation Island root whose scripts/ holds the operational projection",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=DEFAULT_OPERATIONAL_STATE_ROOT,
        help="journal and CAS archive root for operational projection transactions",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install", help="CAS-promote canonical updater to SI operational")
    install.add_argument("--expected-old-sha256")
    install.add_argument("--transaction-id")
    install.add_argument(
        "--disallow-create",
        action="store_true",
        help="fail if the operational path does not already exist",
    )

    commands.add_parser("recover", help="recover an interrupted operational projection transaction")

    rollback = commands.add_parser("rollback", help="roll back one VERIFIED operational journal")
    rollback.add_argument("--journal", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            result = install_operational_updater(
                island_root=args.island_root,
                state_root=args.state_root,
                expected_old_sha256=args.expected_old_sha256,
                transaction_id=args.transaction_id,
                allow_create=not args.disallow_create,
            )
        elif args.command == "recover":
            result = recover_operational_updater(
                island_root=args.island_root,
                state_root=args.state_root,
            )
        else:
            result = rollback_operational_updater(
                journal_path=args.journal,
                island_root=args.island_root,
                state_root=args.state_root,
            )
    except PublicationError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    except Exception as exc:
        failure = {
            "schema_version": RESULT_SCHEMA,
            "status": "FAILED",
            "error_code": "UNEXPECTED_FAILURE",
            "error": str(exc),
            "completion_claim_allowed": False,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KIND",
    "AUTHORITY_APPLIED",
    "JOURNAL_SCHEMA",
    "MARKER_SCHEMA",
    "RESULT_SCHEMA",
    "install_operational_updater",
    "main",
    "recover_operational_updater",
    "rollback_operational_updater",
]
