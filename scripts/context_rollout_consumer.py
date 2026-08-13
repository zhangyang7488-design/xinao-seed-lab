"""Shallow, single-writer consumer for S/B Codex root CLI rollouts.

The one-shot consumer is intended to be invoked by a current-user Scheduled
Task.  It discovers only date-bounded rollout files, classifies their first
``session_meta`` record, and delegates all canonical admission and cursor
validation to the public context-fabric importer.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime import context_fabric as fabric  # noqa: E402
from services.agent_runtime.context_fabric import (  # noqa: E402
    DEFAULT_ALLOWED_CODEX_HOMES,
    import_codex_rollout,
)

CONSUMER_SCHEMA_VERSION = "s.context_rollout_consumer.v1"
RECEIPT_SCHEMA_VERSION = "s.context_rollout_consumer.receipt.v1"
CONSUMER_DIR_NAME = "_consumer"
STATE_FILE_NAME = "state.json"
LOCK_FILE_NAME = "consumer.lock"
LAST_RECEIPT_FILE_NAME = "last_receipt.json"
MAX_SESSION_META_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_FILES = 64
MAX_ERROR_CHARS = 512
MAX_IMPORTS_PER_RUN = 64
BOOTSTRAP_LOOKBACK_DAYS = 2
DISCOVERY_OVERLAP = timedelta(minutes=5)
TRACKED_RETENTION = timedelta(days=2)
PRODUCTION_CONTEXT_FABRIC_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric")

_SUBAGENT_ONLY_KEYS = (
    "parent_thread_id",
    "agent_path",
    "agent_role",
    "agent_nickname",
    "multi_agent_version",
    "forked_from_id",
    "subagent_history_start_ordinal",
)
_HELD_LOCKS: set[str] = set()
_HELD_LOCKS_GUARD = threading.Lock()


class ConsumerError(RuntimeError):
    """The consumer cannot safely continue its global one-shot transaction."""


@dataclass(frozen=True)
class RolloutClassification:
    status: str
    timestamp: str = ""
    session_id: str = ""
    reason: str = ""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ConsumerError("consumer clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object, *, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsumerError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ConsumerError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _is_reparse_point(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(stat_result, "st_file_attributes", 0)
    reparse_flag = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _consumer_directory(root: Path) -> Path:
    try:
        resolved_root, database = fabric._validate_store_root(Path(root), create=False)
    except (fabric.ContextFabricError, OSError) as exc:
        raise ConsumerError("context fabric root must be a regular admitted directory") from exc
    if not database.is_file() or _is_reparse_point(database):
        raise ConsumerError("context fabric database is unavailable")
    consumer_dir = resolved_root / CONSUMER_DIR_NAME
    if consumer_dir.exists():
        if not consumer_dir.is_dir() or _is_reparse_point(consumer_dir):
            raise ConsumerError("consumer state directory cannot be a link or non-directory")
    else:
        consumer_dir.mkdir()
    return consumer_dir


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    if path.exists() and (_is_reparse_point(path) or not path.is_file()):
        raise ConsumerError(f"consumer JSON target is unsafe: {path.name}")
    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    if temporary.exists():
        raise ConsumerError("consumer atomic JSON temporary path already exists")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class ConsumerFileLock:
    """Non-blocking process lock, backed by a one-byte Windows file lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None
        self._registry_key = str(path.resolve()).casefold()

    def acquire(self) -> bool:
        if self.path.exists() and (_is_reparse_point(self.path) or not self.path.is_file()):
            raise ConsumerError("consumer lock path is unsafe")
        handle = self.path.open("a+b", buffering=0)
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            os.fsync(handle.fileno())
        handle.seek(0)
        with _HELD_LOCKS_GUARD:
            if self._registry_key in _HELD_LOCKS:
                handle.close()
                return False
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - retained for non-Windows CI portability.
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False
            _HELD_LOCKS.add(self._registry_key)
        self.handle = handle
        return True

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - retained for non-Windows CI portability.
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.discard(self._registry_key)
            self.handle = None

    def __enter__(self) -> ConsumerFileLock:
        if not self.acquire():
            raise ConsumerError("consumer lock is already held")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


def classify_rollout(path: Path) -> RolloutClassification:
    """Classify a rollout using only its bounded first ``session_meta`` line."""

    try:
        with path.open("rb") as handle:
            line = handle.readline(MAX_SESSION_META_BYTES + 2)
    except OSError as exc:
        return RolloutClassification("read_error", reason=type(exc).__name__)
    if not line.endswith(b"\n"):
        return RolloutClassification("invalid", reason="incomplete_session_meta")
    if len(line) > MAX_SESSION_META_BYTES + 1:
        return RolloutClassification("invalid", reason="session_meta_too_large")
    try:
        record = json.loads(line[:-1].rstrip(b"\r").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return RolloutClassification("invalid", reason="invalid_session_meta_json")
    if not isinstance(record, Mapping) or record.get("type") != "session_meta":
        return RolloutClassification("invalid", reason="missing_session_meta")
    if type(record.get("ordinal")) is not int or record["ordinal"] != 0:
        return RolloutClassification("invalid", reason="session_meta_ordinal")
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return RolloutClassification("invalid", reason="session_meta_payload")
    timestamp = str(payload.get("timestamp") or record.get("timestamp") or "").strip()
    try:
        _parse_utc(timestamp, field="rollout session timestamp")
    except ConsumerError:
        return RolloutClassification("invalid", reason="session_meta_timestamp")
    session_id = str(payload.get("id") or "").strip()
    root_session_id = str(payload.get("session_id") or "").strip()
    if (
        any(key in payload for key in _SUBAGENT_ONLY_KEYS)
        or payload.get("thread_source") == "subagent"
    ):
        return RolloutClassification(
            "excluded_subagent", timestamp=timestamp, session_id=session_id
        )
    if payload.get("source") != "cli" or payload.get("thread_source") != "user":
        return RolloutClassification("excluded_non_cli", timestamp=timestamp, session_id=session_id)
    if not session_id or session_id != root_session_id:
        return RolloutClassification(
            "excluded_non_root", timestamp=timestamp, session_id=session_id
        )
    return RolloutClassification("root_cli", timestamp=timestamp, session_id=session_id)


def _inventory_rollouts(carrier_home: Path) -> dict[str, dict[str, int]]:
    """Stat every rollout without opening historical file contents."""

    sessions = carrier_home / "sessions"
    if not sessions.is_dir() or _is_reparse_point(sessions):
        return {}
    sessions = sessions.resolve(strict=True)
    result: dict[str, dict[str, int]] = {}
    pending = [sessions]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                entry_path = Path(entry.path)
                if entry.is_symlink() or _is_reparse_point(entry_path):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry_path)
                    continue
                if not entry.name.lower().endswith(".jsonl") or not entry.is_file(
                    follow_symlinks=False
                ):
                    continue
                stat_result = entry.stat(follow_symlinks=False)
                relative = entry_path.relative_to(sessions)
            except (OSError, ValueError):
                continue
            locator = str(Path("sessions") / relative)
            result[locator] = {
                "size": int(stat_result.st_size),
                "mtime_ns": int(stat_result.st_mtime_ns),
            }
    return dict(sorted(result.items(), key=lambda item: item[0].casefold()))


def _fingerprint_changed(
    previous: object,
    current: Mapping[str, object],
) -> bool:
    if not isinstance(previous, Mapping):
        return True
    return any(int(previous.get(key, -1)) != int(current[key]) for key in ("size", "mtime_ns"))


def _rollout_directory_date(locator: str) -> date | None:
    parts = Path(locator).parts
    if len(parts) < 5 or parts[0].casefold() != "sessions":
        return None
    try:
        return date(int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def _bootstrap_candidate(locator: str, now: datetime) -> bool:
    rollout_day = _rollout_directory_date(locator)
    if rollout_day is None:
        return False
    today = now.astimezone().date()
    return today - timedelta(days=BOOTSTRAP_LOOKBACK_DAYS) <= rollout_day <= today


def _load_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    if _is_reparse_point(path) or not path.is_file():
        raise ConsumerError("consumer state path is unsafe")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerError("consumer state is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != CONSUMER_SCHEMA_VERSION:
        raise ConsumerError("consumer state schema is unsupported")
    if not isinstance(value.get("carriers"), dict):
        raise ConsumerError("consumer carrier state is invalid")
    _parse_utc(value.get("cutoff_at"), field="consumer cutoff_at")
    _parse_utc(value.get("last_scan_at"), field="consumer last_scan_at")
    return value


def _new_state(now: datetime, allowed_homes: Mapping[str, str]) -> dict[str, object]:
    return {
        "schema_version": CONSUMER_SCHEMA_VERSION,
        "cutoff_at": _utc_text(now),
        "last_scan_at": _utc_text(now),
        "carriers": {
            carrier_id: {
                "home": str(Path(home)),
                "bootstrap_locator": "",
                "inventory": {},
                "tracked_roots": {},
            }
            for home, carrier_id in sorted(allowed_homes.items(), key=lambda item: item[1])
        },
        "authority": False,
    }


def _validate_carrier_state(
    state: dict[str, object], allowed_homes: Mapping[str, str]
) -> dict[str, dict[str, object]]:
    raw_carriers = state["carriers"]
    assert isinstance(raw_carriers, dict)
    result: dict[str, dict[str, object]] = {}
    for home, carrier_id in allowed_homes.items():
        raw = raw_carriers.get(carrier_id)
        if not isinstance(raw, dict) or str(raw.get("home")) != str(Path(home)):
            raise ConsumerError(f"consumer state carrier identity changed: {carrier_id}")
        tracked = raw.get("tracked_roots")
        inventory = raw.get("inventory")
        if not isinstance(tracked, dict) or not isinstance(inventory, dict):
            raise ConsumerError(f"consumer carrier inventory is invalid: {carrier_id}")
        result[carrier_id] = raw
    if set(raw_carriers) != set(result):
        raise ConsumerError("consumer state contains an unexpected carrier")
    return result


def _cursor_offset(root: Path, carrier_id: str, relative_locator: str) -> int | None:
    database = Path(root).resolve(strict=True) / "context_fabric.sqlite3"
    if not database.is_file():
        raise ConsumerError("context fabric database is unavailable")
    connection = sqlite3.connect(database, timeout=1.2)
    try:
        row = connection.execute(
            "SELECT next_byte_offset FROM rollout_cursors "
            "WHERE carrier_id=? AND relative_locator=?",
            (carrier_id, relative_locator),
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else int(row[0])


def _bounded_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:MAX_ERROR_CHARS]


def _append_receipt_file(
    receipt_files: list[dict[str, object]], item: Mapping[str, object]
) -> None:
    if len(receipt_files) < MAX_RECEIPT_FILES:
        receipt_files.append(dict(item))


def _tracked_path(home: Path, locator: str) -> Path:
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise ConsumerError("tracked rollout locator is not a contained relative path")
    sessions_input = home / "sessions"
    if _is_reparse_point(sessions_input):
        raise ConsumerError("carrier sessions root cannot be a link or junction")
    sessions = sessions_input.resolve(strict=True)
    candidate = home / relative
    current = candidate
    while current != home.parent and current != current.parent:
        if current.exists() and _is_reparse_point(current):
            raise ConsumerError("tracked rollout traverses a link or junction")
        if current == home:
            break
        current = current.parent
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(sessions)
    if _is_reparse_point(resolved) or not resolved.is_file():
        raise ConsumerError("tracked rollout is not a regular contained file")
    return resolved


def run_consumer(
    *,
    root: Path = PRODUCTION_CONTEXT_FABRIC_ROOT,
    allowed_homes: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run one shallow discovery/import transaction and return a bounded receipt."""

    started = (now or _utc_now()).astimezone(timezone.utc)
    homes = dict(DEFAULT_ALLOWED_CODEX_HOMES if allowed_homes is None else allowed_homes)
    if not homes or len(set(homes.values())) != len(homes):
        raise ConsumerError("consumer carrier homes must map one-to-one")
    consumer_dir = _consumer_directory(Path(root))
    lock = ConsumerFileLock(consumer_dir / LOCK_FILE_NAME)
    if not lock.acquire():
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "skipped_overlap",
            "reason": "consumer_lock_busy",
            "started_at": _utc_text(started),
            "authority": False,
        }
    try:
        state_path = consumer_dir / STATE_FILE_NAME
        state = _load_state(state_path)
        bootstrap = state is None
        if state is None:
            state = _new_state(started, homes)
        carrier_states = _validate_carrier_state(state, homes)
        previous_scan = _parse_utc(state["last_scan_at"], field="consumer last_scan_at")
        if started + DISCOVERY_OVERLAP < previous_scan:
            raise ConsumerError("consumer clock moved behind the committed scan watermark")
        scan_start = (
            started - timedelta(days=BOOTSTRAP_LOOKBACK_DAYS) if bootstrap else previous_scan
        )
        scan_end = started

        counts: Counter[str] = Counter()
        receipt_files: list[dict[str, object]] = []
        receipt_file_total = 0
        classified_roots: dict[str, list[tuple[str, RolloutClassification, int]]] = {
            carrier_id: [] for carrier_id in carrier_states
        }

        for home_text, carrier_id in sorted(homes.items(), key=lambda item: item[1]):
            home = Path(home_text)
            carrier_state = carrier_states[carrier_id]
            previous_inventory = carrier_state["inventory"]
            assert isinstance(previous_inventory, dict)
            current_inventory = _inventory_rollouts(home)
            changed_locators = [
                locator
                for locator, fingerprint in current_inventory.items()
                if _fingerprint_changed(previous_inventory.get(locator), fingerprint)
                and (not bootstrap or _bootstrap_candidate(locator, started))
            ]
            carrier_state["inventory"] = current_inventory
            counts["inventoried"] += len(current_inventory)
            counts["changed_candidates"] += len(changed_locators)
            for locator in changed_locators:
                fingerprint = current_inventory[locator]
                try:
                    path = _tracked_path(home, locator)
                except (OSError, ValueError, ConsumerError) as exc:
                    counts["classification_error"] += 1
                    receipt_file_total += 1
                    _append_receipt_file(
                        receipt_files,
                        {
                            "carrier_id": carrier_id,
                            "locator": locator[:512],
                            "status": "classification_error",
                            "error_type": type(exc).__name__,
                        },
                    )
                    continue
                classification = classify_rollout(path)
                counts[f"classified_{classification.status}"] += 1
                if classification.status != "root_cli":
                    if classification.status in {"invalid", "read_error"}:
                        receipt_file_total += 1
                        _append_receipt_file(
                            receipt_files,
                            {
                                "carrier_id": carrier_id,
                                "locator": str(path.name)[:256],
                                "status": "classification_error",
                                "error_type": classification.reason,
                            },
                        )
                    continue
                classified_roots[carrier_id].append(
                    (locator, classification, int(fingerprint["mtime_ns"]))
                )

        for carrier_id, roots in classified_roots.items():
            carrier_state = carrier_states[carrier_id]
            tracked = carrier_state["tracked_roots"]
            assert isinstance(tracked, dict)
            if bootstrap and roots:
                latest = max(
                    roots,
                    key=lambda item: (
                        _parse_utc(item[1].timestamp, field="rollout timestamp"),
                        item[2],
                        item[0],
                    ),
                )
                carrier_state["bootstrap_locator"] = latest[0]
            bootstrap_locator = str(carrier_state.get("bootstrap_locator") or "")
            for locator, classification, _modified_ns in roots:
                if (bootstrap and locator == bootstrap_locator) or not bootstrap:
                    existing_metadata = tracked.get(locator)
                    if not isinstance(existing_metadata, dict):
                        existing_metadata = {}
                        tracked[locator] = existing_metadata
                    existing_metadata.update(
                        {
                            "session_id": classification.session_id,
                            "session_timestamp": classification.timestamp,
                        }
                    )
                    if not bootstrap:
                        fingerprint = carrier_state["inventory"][locator]
                        assert isinstance(fingerprint, Mapping)
                        existing_metadata.update(
                            {
                                "pending_size": int(fingerprint["size"]),
                                "pending_mtime_ns": int(fingerprint["mtime_ns"]),
                                "pending_since_scan": _utc_text(started),
                                "stable_observations": 0,
                                "last_status": "awaiting_stable_observation",
                            }
                        )

        import_candidates: list[tuple[str, Path, str, dict[str, object]]] = []
        for home_text, carrier_id in sorted(homes.items(), key=lambda item: item[1]):
            home = Path(home_text)
            tracked = carrier_states[carrier_id]["tracked_roots"]
            assert isinstance(tracked, dict)
            for locator in sorted(tracked):
                metadata = tracked[locator]
                if not isinstance(metadata, dict):
                    raise ConsumerError("tracked rollout metadata is invalid")
                try:
                    path = _tracked_path(home, locator)
                    stat_result = path.stat()
                    size = stat_result.st_size
                    modified_ns = stat_result.st_mtime_ns
                    cursor = _cursor_offset(Path(root), carrier_id, locator)
                    pending_size = metadata.get("pending_size")
                    pending_mtime_ns = metadata.get("pending_mtime_ns")
                    if pending_size is not None or pending_mtime_ns is not None:
                        if (
                            int(pending_size or -1) != size
                            or int(pending_mtime_ns or -1) != modified_ns
                        ):
                            metadata.update(
                                {
                                    "pending_size": size,
                                    "pending_mtime_ns": modified_ns,
                                    "pending_since_scan": _utc_text(started),
                                    "stable_observations": 0,
                                    "last_status": "awaiting_stable_observation",
                                }
                            )
                            counts["awaiting_stable"] += 1
                            continue
                        if metadata.get("pending_since_scan") == _utc_text(started):
                            counts["awaiting_stable"] += 1
                            continue
                        metadata["stable_observations"] = (
                            int(metadata.get("stable_observations", 0)) + 1
                        )
                        metadata.pop("pending_size", None)
                        metadata.pop("pending_mtime_ns", None)
                        metadata.pop("pending_since_scan", None)
                    if (
                        cursor == size
                        and int(metadata.get("last_size", -1)) == size
                        and int(metadata.get("last_mtime_ns", -1)) == modified_ns
                    ):
                        counts["unchanged_cursor"] += 1
                        metadata["last_size"] = size
                        metadata["incomplete_tail"] = False
                        metadata["last_status"] = "unchanged_cursor"
                        continue
                    if (
                        metadata.get("incomplete_tail") is True
                        and int(metadata.get("last_size", -1)) == size
                        and int(metadata.get("last_mtime_ns", -1)) == modified_ns
                    ):
                        counts["unchanged_incomplete_tail"] += 1
                        metadata["last_status"] = "unchanged_incomplete_tail"
                        continue
                    import_candidates.append((carrier_id, home, locator, metadata))
                except (OSError, ValueError, sqlite3.Error, ConsumerError) as exc:
                    counts["file_error"] += 1
                    receipt_file_total += 1
                    _append_receipt_file(
                        receipt_files,
                        {
                            "carrier_id": carrier_id,
                            "locator": locator[:512],
                            "status": "error",
                            "error_type": type(exc).__name__,
                            "error": _bounded_error(exc),
                        },
                    )

        for carrier_id, home, locator, metadata in import_candidates[:MAX_IMPORTS_PER_RUN]:
            receipt_file_total += 1
            try:
                path = _tracked_path(home, locator)
                result = import_codex_rollout(
                    path,
                    carrier_home=home,
                    root=Path(root),
                    allowed_homes=homes,
                )
                imported_stat = path.stat()
                metadata["last_size"] = imported_stat.st_size
                metadata["last_mtime_ns"] = imported_stat.st_mtime_ns
                metadata["incomplete_tail"] = bool(result.get("incomplete_tail", False))
                metadata["last_status"] = "imported"
                counts["imported"] += 1
                counts["appended"] += int(result.get("appended", 0))
                counts["duplicate"] += int(result.get("duplicate", 0))
                counts["ignored"] += int(result.get("ignored", 0))
                _append_receipt_file(
                    receipt_files,
                    {
                        "carrier_id": carrier_id,
                        "locator": locator[:512],
                        "status": "imported",
                        "appended": int(result.get("appended", 0)),
                        "duplicate": int(result.get("duplicate", 0)),
                        "ignored": int(result.get("ignored", 0)),
                        "incomplete_tail": bool(result.get("incomplete_tail", False)),
                    },
                )
            except Exception as exc:  # Per-file isolation is intentional at the scheduler edge.
                metadata["last_status"] = "error"
                counts["file_error"] += 1
                _append_receipt_file(
                    receipt_files,
                    {
                        "carrier_id": carrier_id,
                        "locator": locator[:512],
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": _bounded_error(exc),
                    },
                )
        counts["deferred"] += max(0, len(import_candidates) - MAX_IMPORTS_PER_RUN)

        stable_before_ns = int((started - TRACKED_RETENTION).timestamp() * 1_000_000_000)
        for home_text, carrier_id in homes.items():
            home = Path(home_text)
            tracked = carrier_states[carrier_id]["tracked_roots"]
            assert isinstance(tracked, dict)
            for locator in list(tracked):
                try:
                    path = _tracked_path(home, locator)
                    stat_result = path.stat()
                    if (
                        stat_result.st_mtime_ns < stable_before_ns
                        and _cursor_offset(Path(root), carrier_id, locator) == stat_result.st_size
                    ):
                        del tracked[locator]
                        counts["pruned_stable"] += 1
                except (OSError, ValueError, sqlite3.Error, ConsumerError):
                    continue

        state["last_scan_at"] = _utc_text(scan_end)
        state["last_completed_at"] = _utc_text(_utc_now())
        _atomic_json(state_path, state)
        finished = _utc_now()
        has_errors = any(
            counts[key]
            for key in (
                "file_error",
                "classification_error",
                "classified_invalid",
                "classified_read_error",
            )
        )
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "completed_with_errors" if has_errors else "completed",
            "started_at": _utc_text(started),
            "finished_at": _utc_text(finished),
            "bootstrap": bootstrap,
            "scan_start": _utc_text(scan_start),
            "scan_end": _utc_text(scan_end),
            "counts": dict(sorted(counts.items())),
            "files": receipt_files,
            "file_receipts_total": receipt_file_total,
            "file_receipts_omitted": max(0, receipt_file_total - len(receipt_files)),
            "authority": False,
        }
        _atomic_json(consumer_dir / LAST_RECEIPT_FILE_NAME, receipt)
        return receipt
    finally:
        lock.release()


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Consume new S/B root CLI rollouts into the default context fabric."
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        receipt = run_consumer()
    except Exception as exc:
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": _bounded_error(exc),
            "authority": False,
        }
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
