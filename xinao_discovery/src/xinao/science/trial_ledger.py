"""Transactional append journal for a pin-bound science TrialLedger anchor.

The ProtocolPin binds the immutable JSON anchor. Post-pin entries live in a
deterministically derived SQLite journal so appends do not rewrite the frozen
protocol or its anchor hash.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from xinao.canonical.hashing import canonical_sha256

SCIENCE_TRIAL_JOURNAL_SCHEMA_VERSION = "xinao.science_trial_journal.sqlite.v1"
EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256 = canonical_sha256([])

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {
    "REGISTERED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "TIMEOUT",
    "COMPILE_FAILED",
    "CANCELLED",
    "DISCARDED",
    "NO_ACTION",
}
_TERMINAL_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "TIMEOUT",
    "COMPILE_FAILED",
    "CANCELLED",
    "DISCARDED",
    "NO_ACTION",
}
_BASE_ENTRY_FIELDS = {
    "seq",
    "work_key",
    "status",
    "family_id",
    "equivalence_cluster_id",
    "path_kind",
    "failure_reason",
    "payload_hash",
    "meta",
    "immutable",
}


class ScienceTrialLedgerError(ValueError):
    """Raised when the science TrialLedger journal cannot append or replay safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScienceTrialLedgerError(f"{label} must be non-empty text")
    return value.strip()


def _nullable_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ScienceTrialLedgerError(f"{label} must be exact lowercase sha256")
    return value


def _meta(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScienceTrialLedgerError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def science_trial_journal_path(anchor_path: Path) -> Path:
    """Return the only journal path derived from one immutable ledger anchor."""

    anchor = Path(anchor_path)
    return anchor.with_name(f"{anchor.stem}.journal.sqlite3")


def _payload_basis(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "work_key": entry["work_key"],
        "status": entry["status"],
        "family_id": entry["family_id"],
        "equivalence_cluster_id": entry["equivalence_cluster_id"],
        "path_kind": entry["path_kind"],
        "failure_reason": entry["failure_reason"],
        "meta": entry["meta"],
    }


def _validate_entry(
    raw: Mapping[str, Any],
    *,
    expected_seq: int,
    require_payload_integrity: bool,
) -> dict[str, Any]:
    entry = dict(raw)
    expected_fields = set(_BASE_ENTRY_FIELDS)
    if "event" in entry:
        expected_fields.add("event")
    if set(entry) != expected_fields:
        raise ScienceTrialLedgerError(
            f"science TrialLedger entry {expected_seq} fields do not match the exact contract"
        )
    if (
        not isinstance(entry.get("seq"), int)
        or isinstance(entry.get("seq"), bool)
        or entry["seq"] != expected_seq
    ):
        raise ScienceTrialLedgerError("science TrialLedger sequence must be contiguous")
    entry["work_key"] = _text(entry.get("work_key"), "work_key")
    entry["status"] = _text(entry.get("status"), "status").upper()
    if entry["status"] not in _STATUSES:
        raise ScienceTrialLedgerError(f"unsupported science trial status {entry['status']!r}")
    entry["family_id"] = _nullable_text(entry.get("family_id"), "family_id")
    entry["equivalence_cluster_id"] = _nullable_text(
        entry.get("equivalence_cluster_id"),
        "equivalence_cluster_id",
    )
    entry["path_kind"] = _text(entry.get("path_kind"), "path_kind")
    entry["failure_reason"] = _nullable_text(entry.get("failure_reason"), "failure_reason")
    entry["meta"] = _meta(entry.get("meta"), "meta")
    entry["payload_hash"] = _hash(entry.get("payload_hash"), "payload_hash")
    if entry.get("immutable") is not True:
        raise ScienceTrialLedgerError("science TrialLedger entries must be immutable")
    terminal = entry["status"] in _TERMINAL_STATUSES
    if "event" in entry and entry["event"] != "TERMINAL":
        raise ScienceTrialLedgerError("science TrialLedger event must be TERMINAL")
    if require_payload_integrity:
        if terminal != ("event" in entry):
            raise ScienceTrialLedgerError(
                "journal terminal status and TERMINAL event marker do not agree"
            )
        observed_hash = canonical_sha256(_payload_basis(entry))
        if entry["payload_hash"] != observed_hash:
            raise ScienceTrialLedgerError("science TrialLedger journal payload hash mismatch")
        event_id = _text(entry["meta"].get("event_id"), "meta.event_id")
        entry["meta"]["event_id"] = event_id
    return entry


def _validate_transitions(entries: Sequence[Mapping[str, Any]]) -> None:
    last_status: dict[str, str] = {}
    for entry in entries:
        work_key = str(entry["work_key"])
        status = str(entry["status"])
        previous = last_status.get(work_key)
        if status == "REGISTERED":
            if previous is not None:
                raise ScienceTrialLedgerError(
                    f"trial {work_key!r} was registered more than once"
                )
        elif previous is None:
            raise ScienceTrialLedgerError(
                f"trial {work_key!r} has a silent unregistered transition"
            )
        elif previous in _TERMINAL_STATUSES:
            raise ScienceTrialLedgerError(
                f"trial {work_key!r} changed after a terminal status"
            )
        elif status == "RUNNING" and previous != "REGISTERED":
            raise ScienceTrialLedgerError(
                f"trial {work_key!r} has an invalid RUNNING transition"
            )
        elif status in _TERMINAL_STATUSES and previous not in {"REGISTERED", "RUNNING"}:
            raise ScienceTrialLedgerError(
                f"trial {work_key!r} has an invalid terminal transition"
            )
        last_status[work_key] = status


def _anchor(
    anchor_path: Path,
    *,
    expected_anchor_sha256: str,
    episode_id: str,
) -> tuple[dict[str, Any], str]:
    path = Path(anchor_path)
    if not path.is_file():
        raise ScienceTrialLedgerError(f"science TrialLedger anchor is missing: {path}")
    expected_hash = _hash(expected_anchor_sha256, "expected_anchor_sha256")
    observed_hash = _sha256(path)
    if observed_hash != expected_hash:
        raise ScienceTrialLedgerError("science TrialLedger anchor hash mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScienceTrialLedgerError("science TrialLedger anchor is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ScienceTrialLedgerError("science TrialLedger anchor must be an object")
    if set(payload) != {"schema_version", "episode_id", "append_only", "entries"}:
        raise ScienceTrialLedgerError(
            "science TrialLedger anchor fields do not match the exact contract"
        )
    if payload.get("schema_version") != "xinao.science_trial_ledger.v1":
        raise ScienceTrialLedgerError("unsupported science TrialLedger anchor schema")
    if payload.get("episode_id") != episode_id or payload.get("append_only") is not True:
        raise ScienceTrialLedgerError(
            "science TrialLedger anchor is not append-only or bound to this episode"
        )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ScienceTrialLedgerError("science TrialLedger anchor entries must be a list")
    validated = [
        _validate_entry(item, expected_seq=index, require_payload_integrity=False)
        for index, item in enumerate(entries, start=1)
        if isinstance(item, Mapping)
    ]
    if len(validated) != len(entries):
        raise ScienceTrialLedgerError("science TrialLedger anchor entry must be an object")
    _validate_transitions(validated)
    payload["entries"] = validated
    return payload, observed_hash


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_identity (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            schema_version TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            anchor_sha256 TEXT NOT NULL,
            anchor_entry_count INTEGER NOT NULL,
            anchor_entries_sha256 TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS trial_entries (
            seq INTEGER PRIMARY KEY CHECK (seq > 0),
            event_id TEXT NOT NULL UNIQUE,
            work_key TEXT NOT NULL,
            status TEXT NOT NULL,
            family_id TEXT,
            equivalence_cluster_id TEXT,
            path_kind TEXT NOT NULL,
            failure_reason TEXT,
            payload_hash TEXT NOT NULL,
            meta_json TEXT NOT NULL,
            immutable INTEGER NOT NULL CHECK (immutable = 1),
            terminal_event TEXT CHECK (
                terminal_event IS NULL OR terminal_event = 'TERMINAL'
            )
        )
        """
    )
    connection.execute("PRAGMA user_version = 1")


def _bind_identity(
    connection: sqlite3.Connection,
    *,
    episode_id: str,
    anchor_sha256: str,
    anchor_entries: Sequence[Mapping[str, Any]],
) -> None:
    anchor_entries_sha256 = canonical_sha256(list(anchor_entries))
    expected = (
        SCIENCE_TRIAL_JOURNAL_SCHEMA_VERSION,
        episode_id,
        anchor_sha256,
        len(anchor_entries),
        anchor_entries_sha256,
    )
    observed = connection.execute(
        """
        SELECT schema_version, episode_id, anchor_sha256,
               anchor_entry_count, anchor_entries_sha256
        FROM ledger_identity
        WHERE singleton = 1
        """
    ).fetchone()
    if observed is None:
        connection.execute(
            """
            INSERT INTO ledger_identity (
                singleton, schema_version, episode_id, anchor_sha256,
                anchor_entry_count, anchor_entries_sha256
            ) VALUES (1, ?, ?, ?, ?, ?)
            """,
            expected,
        )
        return
    if tuple(observed) != expected:
        raise ScienceTrialLedgerError(
            "science TrialLedger journal identity does not match its pinned anchor"
        )


def _journal_entries(connection: sqlite3.Connection, *, start_seq: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT seq, event_id, work_key, status, family_id,
               equivalence_cluster_id, path_kind, failure_reason,
               payload_hash, meta_json, immutable, terminal_event
        FROM trial_entries
        ORDER BY seq
        """
    ).fetchall()
    entries: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        (
            seq,
            event_id,
            work_key,
            status,
            family_id,
            equivalence_cluster_id,
            path_kind,
            failure_reason,
            payload_hash,
            meta_json,
            immutable,
            terminal_event,
        ) = row
        try:
            meta = json.loads(meta_json)
        except json.JSONDecodeError as exc:
            raise ScienceTrialLedgerError("journal meta_json is not valid JSON") from exc
        if not isinstance(meta, dict) or meta.get("event_id") != event_id:
            raise ScienceTrialLedgerError("journal event identity does not match entry meta")
        entry: dict[str, Any] = {
            "seq": seq,
            "work_key": work_key,
            "status": status,
            "family_id": family_id,
            "equivalence_cluster_id": equivalence_cluster_id,
            "path_kind": path_kind,
            "failure_reason": failure_reason,
            "payload_hash": payload_hash,
            "meta": meta,
            "immutable": immutable == 1,
        }
        if terminal_event is not None:
            entry["event"] = terminal_event
        entries.append(
            _validate_entry(
                entry,
                expected_seq=start_seq + offset,
                require_payload_integrity=True,
            )
        )
    return entries


def load_science_trial_journal(
    anchor_path: Path,
    *,
    expected_anchor_sha256: str,
    episode_id: str,
) -> dict[str, Any]:
    """Replay the immutable anchor plus its optional transactional journal."""

    anchor_payload, anchor_sha256 = _anchor(
        anchor_path,
        expected_anchor_sha256=expected_anchor_sha256,
        episode_id=episode_id,
    )
    anchor_entries = list(anchor_payload["entries"])
    journal_path = science_trial_journal_path(anchor_path)
    journal_entries: list[dict[str, Any]] = []
    if journal_path.exists():
        uri = f"{journal_path.resolve().as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=5.0) as connection:
                connection.execute("PRAGMA query_only = ON")
                _bind_identity(
                    connection,
                    episode_id=episode_id,
                    anchor_sha256=anchor_sha256,
                    anchor_entries=anchor_entries,
                )
                journal_entries = _journal_entries(
                    connection,
                    start_seq=len(anchor_entries) + 1,
                )
        except sqlite3.Error as exc:
            raise ScienceTrialLedgerError(
                f"science TrialLedger journal cannot be replayed: {exc}"
            ) from exc
    entries = [*anchor_entries, *journal_entries]
    _validate_transitions(entries)
    return {
        "schema_version": SCIENCE_TRIAL_JOURNAL_SCHEMA_VERSION,
        "anchor_ref": str(Path(anchor_path)),
        "anchor_sha256": anchor_sha256,
        "anchor_entry_count": len(anchor_entries),
        "journal_ref": str(journal_path),
        "journal_exists": journal_path.exists(),
        "journal_file_sha256": _sha256(journal_path) if journal_path.exists() else None,
        "entry_count": len(entries),
        "entries_sha256": canonical_sha256(entries),
        "entries": entries,
    }


def append_science_trial_entry(
    anchor_path: Path,
    *,
    expected_anchor_sha256: str,
    episode_id: str,
    event_id: str,
    work_key: str,
    status: str,
    family_id: str | None,
    equivalence_cluster_id: str | None,
    path_kind: str,
    failure_reason: str | None,
    meta: Mapping[str, Any],
    expected_entry_count: int,
    expected_entries_sha256: str,
    terminal: bool,
) -> dict[str, Any]:
    """Append one idempotent entry under an immediate SQLite write transaction."""

    anchor_payload, anchor_sha256 = _anchor(
        anchor_path,
        expected_anchor_sha256=expected_anchor_sha256,
        episode_id=episode_id,
    )
    anchor_entries = list(anchor_payload["entries"])
    event_id = _text(event_id, "event_id")
    work_key = _text(work_key, "work_key")
    status = _text(status, "status").upper()
    if status not in _STATUSES:
        raise ScienceTrialLedgerError(f"unsupported science trial status {status!r}")
    if terminal != (status in _TERMINAL_STATUSES):
        raise ScienceTrialLedgerError("terminal flag does not match science trial status")
    normalized_meta = _meta(meta, "meta")
    observed_event_id = normalized_meta.get("event_id")
    if observed_event_id not in (None, event_id):
        raise ScienceTrialLedgerError("meta.event_id conflicts with event_id")
    normalized_meta["event_id"] = event_id
    requested: dict[str, Any] = {
        "work_key": work_key,
        "status": status,
        "family_id": _nullable_text(family_id, "family_id"),
        "equivalence_cluster_id": _nullable_text(
            equivalence_cluster_id,
            "equivalence_cluster_id",
        ),
        "path_kind": _text(path_kind, "path_kind"),
        "failure_reason": _nullable_text(failure_reason, "failure_reason"),
        "meta": normalized_meta,
    }
    requested_hash = canonical_sha256(requested)
    expected_entries_sha256 = _hash(
        expected_entries_sha256,
        "expected_entries_sha256",
    )
    if (
        not isinstance(expected_entry_count, int)
        or isinstance(expected_entry_count, bool)
        or expected_entry_count < 0
    ):
        raise ScienceTrialLedgerError("expected_entry_count must be a non-negative integer")

    journal_path = science_trial_journal_path(anchor_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(journal_path, timeout=5.0, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("BEGIN IMMEDIATE")
        _create_schema(connection)
        _bind_identity(
            connection,
            episode_id=episode_id,
            anchor_sha256=anchor_sha256,
            anchor_entries=anchor_entries,
        )
        journal_entries = _journal_entries(
            connection,
            start_seq=len(anchor_entries) + 1,
        )
        entries = [*anchor_entries, *journal_entries]
        _validate_transitions(entries)

        existing = next(
            (
                item
                for item in journal_entries
                if item["meta"].get("event_id") == event_id
            ),
            None,
        )
        if existing is not None:
            same_request = (
                existing["payload_hash"] == requested_hash
                and existing.get("event") == ("TERMINAL" if terminal else None)
            )
            if not same_request:
                raise ScienceTrialLedgerError(
                    "duplicate event_id has a different science trial payload"
                )
            connection.commit()
            return {
                "schema_version": SCIENCE_TRIAL_JOURNAL_SCHEMA_VERSION,
                "entry": existing,
                "entry_count": len(entries),
                "entries_sha256": canonical_sha256(entries),
                "anchor_sha256": anchor_sha256,
                "journal_ref": str(journal_path),
                "journal_file_sha256": _sha256(journal_path),
                "replayed": True,
            }

        if len(entries) != expected_entry_count:
            raise ScienceTrialLedgerError("science TrialLedger entry count changed")
        if canonical_sha256(entries) != expected_entries_sha256:
            raise ScienceTrialLedgerError("science TrialLedger entry head changed")

        seq = len(entries) + 1
        entry: dict[str, Any] = {
            "seq": seq,
            **requested,
            "payload_hash": requested_hash,
            "immutable": True,
        }
        if terminal:
            entry["event"] = "TERMINAL"
        candidate_entries = [*entries, entry]
        _validate_entry(
            entry,
            expected_seq=seq,
            require_payload_integrity=True,
        )
        _validate_transitions(candidate_entries)
        connection.execute(
            """
            INSERT INTO trial_entries (
                seq, event_id, work_key, status, family_id,
                equivalence_cluster_id, path_kind, failure_reason,
                payload_hash, meta_json, immutable, terminal_event
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                seq,
                event_id,
                work_key,
                status,
                entry["family_id"],
                entry["equivalence_cluster_id"],
                entry["path_kind"],
                entry["failure_reason"],
                requested_hash,
                json.dumps(
                    normalized_meta,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                entry.get("event"),
            ),
        )
        connection.commit()
    except (ScienceTrialLedgerError, sqlite3.Error):
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()

    replay = load_science_trial_journal(
        anchor_path,
        expected_anchor_sha256=anchor_sha256,
        episode_id=episode_id,
    )
    return {
        "schema_version": SCIENCE_TRIAL_JOURNAL_SCHEMA_VERSION,
        "entry": replay["entries"][-1],
        "entry_count": replay["entry_count"],
        "entries_sha256": replay["entries_sha256"],
        "anchor_sha256": anchor_sha256,
        "journal_ref": replay["journal_ref"],
        "journal_file_sha256": replay["journal_file_sha256"],
        "replayed": False,
    }


__all__ = [
    "EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256",
    "SCIENCE_TRIAL_JOURNAL_SCHEMA_VERSION",
    "ScienceTrialLedgerError",
    "append_science_trial_entry",
    "load_science_trial_journal",
    "science_trial_journal_path",
]
