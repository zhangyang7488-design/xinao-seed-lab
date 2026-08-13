"""Shallow, single-writer consumer for S/B Codex root CLI rollouts.

The one-shot consumer is intended to be invoked by a current-user Scheduled
Task. It keeps a stat-only inventory of the sessions tree, opens only newly
admitted or changed candidates for first-record classification, and delegates
all canonical admission and cursor validation to the public context-fabric
importer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
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
from services.agent_runtime.presentation_delivery import (  # noqa: E402
    read_presentation_outbox,
    read_presentation_state,
)
from services.agent_runtime.presentation_observer import (  # noqa: E402
    STATE_KIND_CONTROLLER,
    RuntimeStateSource,
    make_context_event_sink,
    observe_runtime_states,
)

CONSUMER_SCHEMA_VERSION = "s.context_rollout_consumer.v1"
RECEIPT_SCHEMA_VERSION = "s.context_rollout_consumer.receipt.v1"
CONSUMER_DIR_NAME = "_consumer"
STATE_FILE_NAME = "state.json"
STATE_QUARANTINE_FILE_NAME = "state_quarantine.json"
LOCK_FILE_NAME = "consumer.lock"
LAST_RECEIPT_FILE_NAME = "last_receipt.json"
PRESENTATION_CURSOR_FILE_NAME = "presentation_observer.cursor.json"
PRESENTATION_LAST_RECEIPT_FILE_NAME = "presentation_last_receipt.json"
PRESENTATION_RECEIPT_SCHEMA_VERSION = "s.context_rollout_presentation.receipt.v1"
STATE_QUARANTINE_SCHEMA_VERSION = "s.context_rollout_consumer.state_quarantine.v1"
MAX_SESSION_META_BYTES = 8 * 1024 * 1024
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_FILES = 64
MAX_IMPORTS_PER_RUN = 64
MAX_INTEGRITY_RECHECKS_PER_RUN = 1
BOOTSTRAP_LOOKBACK_DAYS = 2
DISCOVERY_OVERLAP = timedelta(minutes=5)
INTEGRITY_RECHECK_INTERVAL = timedelta(hours=6)
TRACKED_STABLE_PRUNE_AFTER = timedelta(days=2)
IMPORT_RETRY_BASE = timedelta(minutes=5)
IMPORT_RETRY_MAX = timedelta(hours=6)
QUIESCENCE_RETRY_DELAYS_SECONDS = (0.25, 0.75)
ROLLOUT_LOCAL_TIMEZONE = timezone(timedelta(hours=8))
LOCATOR_PAYLOAD_TOLERANCE = timedelta(seconds=5)
FUTURE_CLOCK_TOLERANCE = timedelta(seconds=5)
PRODUCTION_CONTEXT_FABRIC_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric")
PRODUCTION_PRESENTATION_RUNTIME_ROOTS = (
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_world_compute"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_c"),
    Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_a"),
)
_POINTER_TO_CONTROLLER_SCHEMA = {
    "xinao.cleanroom.perpetual-world-compute-run.v2": (
        "xinao.cleanroom.perpetual-world-compute-controller-state.v2"
    ),
    "xinao.cleanroom-c.perpetual-run.v1": ("xinao.cleanroom-c.perpetual-controller-state.v1"),
}
_PRODUCTION_PRESENTATION_ROOT_CONTRACTS = {
    os.path.normcase(str(PRODUCTION_PRESENTATION_RUNTIME_ROOTS[0])): {
        "pointer_schema": "xinao.cleanroom.perpetual-world-compute-run.v2",
        "account_slot": "",
    },
    os.path.normcase(str(PRODUCTION_PRESENTATION_RUNTIME_ROOTS[1])): {
        "pointer_schema": "xinao.cleanroom-c.perpetual-run.v1",
        "account_slot": "C",
    },
    os.path.normcase(str(PRODUCTION_PRESENTATION_RUNTIME_ROOTS[2])): {
        "pointer_schema": "xinao.cleanroom.perpetual-world-compute-run.v2",
        "account_slot": "A",
    },
}
_MAX_PRESENTATION_POINTER_BYTES = 1024 * 1024

_ROLLOUT_NAME_RE = re.compile(
    r"^rollout-(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-"
    r"(?P<session>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_CARRIERS = frozenset({"s-primary", "s-account-b"})

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
    locator_timestamp: str = ""


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


def _locator_sha256(locator: str) -> str:
    normalized = locator.replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _locator_timestamp(path_or_locator: Path | str) -> datetime | None:
    parts = Path(path_or_locator).parts
    if len(parts) < 4:
        return None
    year_text, month_text, day_text, filename = parts[-4:]
    match = _ROLLOUT_NAME_RE.fullmatch(filename)
    if match is None:
        return None
    try:
        directory_day = date(int(year_text), int(month_text), int(day_text))
        local_naive = datetime.strptime(match.group("stamp"), "%Y-%m-%dT%H-%M-%S")
    except ValueError:
        return None
    if local_naive.date() != directory_day:
        return None
    return local_naive.replace(tzinfo=ROLLOUT_LOCAL_TIMEZONE).astimezone(timezone.utc)


def _typed_error(exc: BaseException) -> str:
    if isinstance(exc, fabric.ContextFabricUnavailable):
        return "context_fabric_unavailable"
    if isinstance(exc, fabric.ContextFabricError):
        return "context_fabric_rejected"
    if isinstance(exc, sqlite3.Error):
        return "sqlite_error"
    if isinstance(exc, OSError):
        return "filesystem_error"
    if isinstance(exc, ConsumerError):
        return "consumer_contract_error"
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_value"
    return "unexpected_error"


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
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if fabric._secret_like(serialized, environ=os.environ):
        raise ConsumerError("consumer JSON contains secret-like material")
    encoded = (serialized + "\n").encode("utf-8")
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


def _stable_bounded_json_object(
    path: Path,
    *,
    max_bytes: int,
    object_name: str,
) -> tuple[dict[str, object], str]:
    if not path.is_file() or _is_reparse_point(path):
        raise ConsumerError(f"{object_name} must be a regular file")
    try:
        first_stat = path.stat()
        first = path.read_bytes()
        second = path.read_bytes()
        second_stat = path.stat()
    except OSError as exc:
        raise ConsumerError(f"{object_name} is unreadable") from exc

    def fingerprint(value: os.stat_result) -> tuple[int, int, int, int]:
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)

    if fingerprint(first_stat) != fingerprint(second_stat) or first != second:
        raise ConsumerError(f"{object_name} changed during stable read")
    if not first or len(first) > max_bytes:
        raise ConsumerError(f"{object_name} has an invalid bounded size")
    try:
        value = json.loads(first.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerError(f"{object_name} is not a UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ConsumerError(f"{object_name} must be a JSON object")
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if json.loads(canonical.decode("utf-8")) != value:
        raise ConsumerError(f"{object_name} canonical readback changed")
    return value, hashlib.sha256(first).hexdigest()


def _presentation_source_from_pointer(
    runtime_root: Path,
) -> tuple[RuntimeStateSource, dict[str, str]] | None:
    if runtime_root.exists() and (_is_reparse_point(runtime_root) or not runtime_root.is_dir()):
        raise ConsumerError("presentation runtime root is unsafe")
    pointer_path = runtime_root / "current.json"
    if not pointer_path.exists():
        return None
    pointer, pointer_sha256 = _stable_bounded_json_object(
        pointer_path,
        max_bytes=_MAX_PRESENTATION_POINTER_BYTES,
        object_name="presentation current pointer",
    )
    pointer_schema = str(pointer.get("schema") or "")
    controller_schema = _POINTER_TO_CONTROLLER_SCHEMA.get(pointer_schema)
    run_id = str(pointer.get("run_id") or "")
    run_dir_text = str(pointer.get("run_dir") or "")
    account_slot = str(pointer.get("account_slot") or "").upper()
    if controller_schema is None or not run_id or account_slot not in {"A", "C"}:
        raise ConsumerError("presentation current pointer identity is unsupported")
    runtime_resolved = runtime_root.resolve(strict=True)
    production_contract = _PRODUCTION_PRESENTATION_ROOT_CONTRACTS.get(
        os.path.normcase(str(runtime_resolved))
    )
    if production_contract is not None and (
        pointer_schema != production_contract["pointer_schema"]
        or (
            production_contract["account_slot"]
            and account_slot != production_contract["account_slot"]
        )
    ):
        raise ConsumerError("presentation current pointer violates its runtime-root contract")
    try:
        run_dir = Path(run_dir_text).resolve(strict=True)
        run_dir.relative_to(runtime_resolved)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ConsumerError("presentation run_dir escapes its named runtime root") from exc
    expected_run_dir = runtime_resolved / "runs" / run_id
    if os.path.normcase(str(run_dir)) != os.path.normcase(str(expected_run_dir)):
        raise ConsumerError("presentation run_dir does not match the named run")
    controller_path = run_dir / "controller_state.json"
    if not controller_path.is_file() or _is_reparse_point(controller_path):
        raise ConsumerError("presentation controller state is unavailable")
    config_path = run_dir / "run_config.json"
    config, config_sha256 = _stable_bounded_json_object(
        config_path,
        max_bytes=_MAX_PRESENTATION_POINTER_BYTES,
        object_name="presentation run config",
    )
    config_run_dir = Path(str(config.get("run_dir") or "")).resolve(strict=True)
    if (
        config.get("schema") != pointer_schema
        or config.get("run_id") != run_id
        or str(config.get("account_slot") or "").upper() != account_slot
        or os.path.normcase(str(config_run_dir)) != os.path.normcase(str(run_dir))
    ):
        raise ConsumerError("presentation pointer and run config identities differ")
    runtime_identity = _locator_sha256(str(runtime_resolved))[:16]
    source = RuntimeStateSource(
        path=controller_path,
        state_kind=STATE_KIND_CONTROLLER,
        expected_run_id=run_id,
        expected_schema=controller_schema,
        activity_id=f"xinao-world-compute:{runtime_identity}",
        audience="user",
    )
    return source, {
        "pointer_path": str(pointer_path.resolve(strict=True)),
        "pointer_sha256": pointer_sha256,
        "config_path": str(config_path.resolve(strict=True)),
        "config_sha256": config_sha256,
        "run_id": run_id,
        "account_slot": account_slot,
    }


def _validate_presentation_binding(binding: Mapping[str, str]) -> None:
    for prefix, object_name in (
        ("pointer", "presentation current pointer"),
        ("config", "presentation run config"),
    ):
        path = Path(binding[f"{prefix}_path"])
        _value, observed_sha256 = _stable_bounded_json_object(
            path,
            max_bytes=_MAX_PRESENTATION_POINTER_BYTES,
            object_name=object_name,
        )
        if observed_sha256 != binding[f"{prefix}_sha256"]:
            raise ConsumerError(f"{object_name} changed before transition append")


def run_presentation_step(
    *,
    root: Path = PRODUCTION_CONTEXT_FABRIC_ROOT,
    runtime_roots: Sequence[Path] = PRODUCTION_PRESENTATION_RUNTIME_ROOTS,
    carrier_id: str = "s-primary",
) -> dict[str, object]:
    """Observe controller-only state into Context and read the delivery surface.

    This is a one-shot sidecar phase.  It never opens lineage files and never
    invokes a visible emitter; pending items remain in the canonical outbox.
    """

    started = _utc_now()
    consumer_dir = _consumer_directory(Path(root))
    runs_dir = consumer_dir / "presentation"
    if runs_dir.exists():
        if not runs_dir.is_dir() or _is_reparse_point(runs_dir):
            raise ConsumerError("presentation consumer directory is unsafe")
    else:
        runs_dir.mkdir()
    results: list[dict[str, object]] = []
    totals: Counter[str] = Counter()

    for runtime_root in runtime_roots:
        locator_sha256 = _locator_sha256(str(runtime_root))
        item: dict[str, object] = {
            "runtime_root_sha256": locator_sha256,
            "observer_status": "absent",
            "transition_count": 0,
            "pending_delivery_count": 0,
            "routine_pending_count": 0,
            "visible_pending_count": 0,
            "authority": False,
        }
        try:
            source_binding = _presentation_source_from_pointer(Path(runtime_root))
            if source_binding is None:
                totals["absent"] += 1
                results.append(item)
                continue
            source, binding = source_binding
            cursor_dir = runs_dir / locator_sha256
            cursor_dir.mkdir(exist_ok=True)
            _validate_presentation_binding(binding)
            context_sink = make_context_event_sink(
                root=Path(root),
                carrier_id=carrier_id,
                environ=os.environ,
            )
            observation = observe_runtime_states(
                [source],
                cursor_path=cursor_dir / PRESENTATION_CURSOR_FILE_NAME,
                sink=context_sink,
            )
            try:
                _validate_presentation_binding(binding)
                binding_readback = "stable"
            except ConsumerError:
                # A current-pointer rollover after observation does not erase
                # the exact historical controller bytes already admitted.
                # The stable per-runtime-root scope lets the next run replace
                # this state without wedging the observer pending outbox.
                binding_readback = "changed_after_observe"
            states = read_presentation_state(
                root=Path(root),
                activity_id=source.activity_id,
                audience=source.audience,
            )
            pending = read_presentation_outbox(
                root=Path(root),
                activity_id=source.activity_id,
                audience=source.audience,
            )
            routine_pending = sum(item.category == "routine" for item in pending)
            item.update(
                {
                    "activity_id": source.activity_id,
                    "account_slot": binding["account_slot"],
                    "run_id": binding["run_id"],
                    "pointer_sha256": binding["pointer_sha256"],
                    "run_config_sha256": binding["config_sha256"],
                    "binding_readback": binding_readback,
                    "observer_status": observation.status,
                    "transition_count": len(observation.transitions),
                    "projection_count": len(states),
                    "pending_delivery_count": len(pending),
                    "routine_pending_count": routine_pending,
                    "visible_pending_count": len(pending) - routine_pending,
                }
            )
            if states:
                input_tip = states[0]["projection"]["input_tip"]
                item["controller_record_sha256"] = input_tip["source_record_sha256"]
                item["presentation_event_id"] = input_tip["event_id"]
            totals["observed"] += 1
            totals["transitions"] += len(observation.transitions)
            totals["pending_delivery"] += len(pending)
        except Exception as exc:
            item.update(
                {
                    "observer_status": "error",
                    "error_type": _typed_error(exc),
                }
            )
            totals["error"] += 1
        results.append(item)

    receipt = {
        "schema_version": PRESENTATION_RECEIPT_SCHEMA_VERSION,
        "status": "completed_with_errors" if totals["error"] else "completed",
        "started_at": _utc_text(started),
        "finished_at": _utc_text(_utc_now()),
        "runtime_roots": results,
        "counts": dict(sorted(totals.items())),
        "visible_emitter": "not_configured",
        "ui_interception_claimed": False,
        "authority": False,
    }
    _atomic_json(consumer_dir / PRESENTATION_LAST_RECEIPT_FILE_NAME, receipt)
    return receipt


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


def classify_rollout(path: Path, *, now: datetime | None = None) -> RolloutClassification:
    """Classify a rollout using only its bounded first ``session_meta`` line."""

    observed_at = (now or _utc_now()).astimezone(timezone.utc)
    locator_timestamp = _locator_timestamp(path)
    if locator_timestamp is None:
        return RolloutClassification("quarantined", reason="locator_timestamp_invalid")
    locator_text = _utc_text(locator_timestamp)
    if locator_timestamp > observed_at + FUTURE_CLOCK_TOLERANCE:
        return RolloutClassification(
            "quarantined",
            reason="locator_timestamp_future",
            locator_timestamp=locator_text,
        )
    try:
        with path.open("rb") as handle:
            line = handle.readline(MAX_SESSION_META_BYTES + 2)
    except OSError:
        return RolloutClassification("read_error", reason="filesystem_error")
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
        payload_timestamp = _parse_utc(timestamp, field="rollout session timestamp")
    except ConsumerError:
        return RolloutClassification("invalid", reason="session_meta_timestamp")
    if payload_timestamp > observed_at + FUTURE_CLOCK_TOLERANCE:
        return RolloutClassification(
            "quarantined",
            timestamp=timestamp,
            reason="session_meta_timestamp_future",
            locator_timestamp=locator_text,
        )
    if abs(payload_timestamp - locator_timestamp) > LOCATOR_PAYLOAD_TOLERANCE:
        return RolloutClassification(
            "quarantined",
            timestamp=timestamp,
            reason="session_meta_locator_timestamp_mismatch",
            locator_timestamp=locator_text,
        )
    session_id = str(payload.get("id") or "").strip()
    root_session_id = str(payload.get("session_id") or "").strip()
    if (
        any(key in payload for key in _SUBAGENT_ONLY_KEYS)
        or payload.get("thread_source") == "subagent"
    ):
        return RolloutClassification(
            "excluded_subagent",
            timestamp=timestamp,
            session_id=session_id,
            locator_timestamp=locator_text,
        )
    if payload.get("source") != "cli" or payload.get("thread_source") != "user":
        return RolloutClassification(
            "excluded_non_cli",
            timestamp=timestamp,
            session_id=session_id,
            locator_timestamp=locator_text,
        )
    if not session_id or session_id != root_session_id:
        return RolloutClassification(
            "excluded_non_root",
            timestamp=timestamp,
            session_id=session_id,
            locator_timestamp=locator_text,
        )
    filename_match = _ROLLOUT_NAME_RE.fullmatch(path.name)
    if filename_match is None or filename_match.group("session") != session_id:
        return RolloutClassification(
            "quarantined",
            timestamp=timestamp,
            session_id=session_id,
            reason="session_id_locator_mismatch",
            locator_timestamp=locator_text,
        )
    return RolloutClassification(
        "root_cli",
        timestamp=timestamp,
        session_id=session_id,
        locator_timestamp=locator_text,
    )


def _inventory_rollouts(
    carrier_home: Path,
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    """Stat every rollout without opening historical file contents."""

    sessions = carrier_home / "sessions"
    if not sessions.is_dir() or _is_reparse_point(sessions):
        return {}, {}
    sessions = sessions.resolve(strict=True)
    result: dict[str, dict[str, int]] = {}
    locators: dict[str, str] = {}
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
            locator_hash = _locator_sha256(locator)
            if locator_hash in locators and locators[locator_hash] != locator:
                raise ConsumerError("rollout locator hash collision")
            locators[locator_hash] = locator
            result[locator_hash] = {
                "size": int(stat_result.st_size),
                "mtime_ns": int(stat_result.st_mtime_ns),
            }
    return dict(sorted(result.items())), locators


def _fingerprint_changed(
    previous: object,
    current: Mapping[str, object],
) -> bool:
    if not isinstance(previous, Mapping):
        return True
    return any(int(previous.get(key, -1)) != int(current[key]) for key in ("size", "mtime_ns"))


def _bootstrap_candidate(locator: str, now: datetime) -> bool:
    rollout_timestamp = _locator_timestamp(locator)
    if rollout_timestamp is None or rollout_timestamp > now + FUTURE_CLOCK_TOLERANCE:
        return False
    return (
        now - timedelta(days=BOOTSTRAP_LOOKBACK_DAYS)
        <= rollout_timestamp
        <= now + FUTURE_CLOCK_TOLERANCE
    )


def _load_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    if _is_reparse_point(path) or not path.is_file():
        raise ConsumerError("consumer state path is unsafe")
    if path.stat().st_size > MAX_STATE_BYTES:
        raise ConsumerError("consumer state exceeds its bounded size")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerError("consumer state is unreadable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != CONSUMER_SCHEMA_VERSION:
        raise ConsumerError("consumer state schema is unsupported")
    if not set(value) <= {
        "schema_version",
        "cutoff_at",
        "last_scan_at",
        "last_completed_at",
        "carriers",
        "authority",
    }:
        raise ConsumerError("consumer state contains unknown fields")
    if not isinstance(value.get("carriers"), dict):
        raise ConsumerError("consumer carrier state is invalid")
    if value.get("authority") is not False:
        raise ConsumerError("consumer state authority marker is invalid")
    _parse_utc(value.get("cutoff_at"), field="consumer cutoff_at")
    _parse_utc(value.get("last_scan_at"), field="consumer last_scan_at")
    if "last_completed_at" in value:
        _parse_utc(value["last_completed_at"], field="consumer last_completed_at")
    return value


def _sha256_regular_file(path: Path) -> str:
    if _is_reparse_point(path) or not path.is_file():
        raise ConsumerError("consumer state quarantine source is unsafe")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _load_state_quarantine(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    if _is_reparse_point(path) or not path.is_file() or path.stat().st_size > 16_384:
        raise ConsumerError("consumer state quarantine marker is unsafe")
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerError("consumer state quarantine marker is unreadable") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "corrupt_state_sha256",
            "status",
            "first_seen_at",
            "last_attempt_at",
            "attempts",
            "authority",
        }
        or value.get("schema_version") != STATE_QUARANTINE_SCHEMA_VERSION
        or not _SHA256_RE.fullmatch(str(value.get("corrupt_state_sha256") or ""))
        or value.get("status") not in {"pending_recovery", "recovered"}
        or type(value.get("attempts")) is not int
        or int(value["attempts"]) < 0
        or value.get("authority") is not False
    ):
        raise ConsumerError("consumer state quarantine marker is invalid")
    _parse_utc(value["first_seen_at"], field="state quarantine first_seen_at")
    _parse_utc(value["last_attempt_at"], field="state quarantine last_attempt_at")
    return value


def _failed_state_receipt(
    *,
    started: datetime,
    error_type: str,
    recovery_status: str,
    corrupt_state_sha256: str,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "failed",
        "error_type": error_type,
        "recovery_status": recovery_status,
        "started_at": _utc_text(started),
        "finished_at": _utc_text(_utc_now()),
        "authority": False,
    }
    if corrupt_state_sha256:
        receipt["corrupt_state_sha256"] = corrupt_state_sha256
    return receipt


def _new_state(now: datetime, allowed_homes: Mapping[str, str]) -> dict[str, object]:
    return {
        "schema_version": CONSUMER_SCHEMA_VERSION,
        "cutoff_at": _utc_text(now),
        "last_scan_at": _utc_text(now),
        "carriers": {
            carrier_id: {
                "bootstrap_locator_sha256": "",
                "inventory": {},
                "tracked_roots": {},
            }
            for _home, carrier_id in sorted(allowed_homes.items(), key=lambda item: item[1])
        },
        "authority": False,
    }


def _cursor_time(updated_at_unix_ns: object, *, fallback: datetime) -> datetime:
    try:
        value = int(updated_at_unix_ns)
        if value < 0:
            raise ValueError
        return datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
    except (OverflowError, TypeError, ValueError, OSError):
        return fallback - INTEGRITY_RECHECK_INTERVAL


def _cursor_count(root: Path) -> int:
    database = Path(root).resolve(strict=True) / "context_fabric.sqlite3"
    connection = sqlite3.connect(database, timeout=1.2)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM rollout_cursors").fetchone()[0])
    finally:
        connection.close()


def _rebuild_state_from_cursors(
    *,
    root: Path,
    allowed_homes: Mapping[str, str],
    now: datetime,
) -> dict[str, object]:
    """Rebuild discovery state from canonical cursors without bootstrapping history."""

    rebuilt = _new_state(now, allowed_homes)
    carriers = rebuilt["carriers"]
    assert isinstance(carriers, dict)
    locators_by_carrier: dict[str, dict[str, str]] = {}
    for home_text, carrier_id in sorted(allowed_homes.items(), key=lambda item: item[1]):
        inventory, locators = _inventory_rollouts(Path(home_text))
        carrier = carriers[carrier_id]
        assert isinstance(carrier, dict)
        carrier["inventory"] = inventory
        locators_by_carrier[carrier_id] = locators

    database = Path(root).resolve(strict=True) / "context_fabric.sqlite3"
    connection = sqlite3.connect(database, timeout=1.2)
    connection.row_factory = sqlite3.Row
    try:
        cursor_rows = connection.execute(
            "SELECT carrier_id,relative_locator,next_byte_offset,updated_at_unix_ns "
            "FROM rollout_cursors ORDER BY carrier_id,relative_locator"
        ).fetchall()
    finally:
        connection.close()
    for row in cursor_rows:
        carrier_id = str(row["carrier_id"])
        if carrier_id not in carriers:
            continue
        locator = str(row["relative_locator"])
        locator_hash = _locator_sha256(locator)
        current_locator = locators_by_carrier[carrier_id].get(locator_hash)
        if (
            current_locator is None
            or current_locator.replace("\\", "/").casefold()
            != locator.replace("\\", "/").casefold()
        ):
            continue
        carrier = carriers[carrier_id]
        assert isinstance(carrier, dict)
        inventory = carrier["inventory"]
        tracked = carrier["tracked_roots"]
        assert isinstance(inventory, dict) and isinstance(tracked, dict)
        fingerprint = inventory[locator_hash]
        assert isinstance(fingerprint, dict)
        cursor_offset = int(row["next_byte_offset"])
        current_size = int(fingerprint["size"])
        metadata: dict[str, object] = {
            "last_size": cursor_offset,
            "last_mtime_ns": int(fingerprint["mtime_ns"]),
            "incomplete_tail": current_size > cursor_offset,
            "last_status": "recovered_from_cursor",
            "last_integrity_check_at": _utc_text(
                min(_cursor_time(row["updated_at_unix_ns"], fallback=now), now)
            ),
        }
        if current_size != cursor_offset:
            metadata.update(
                {
                    "pending_size": current_size,
                    "pending_mtime_ns": int(fingerprint["mtime_ns"]),
                    "pending_since_scan": _utc_text(now),
                    "stable_observations": 0,
                    "last_status": "awaiting_stable_observation",
                }
            )
        tracked[locator_hash] = metadata
    return rebuilt


def _validate_carrier_state(
    state: dict[str, object], allowed_homes: Mapping[str, str]
) -> dict[str, dict[str, object]]:
    raw_carriers = state["carriers"]
    assert isinstance(raw_carriers, dict)
    result: dict[str, dict[str, object]] = {}
    allowed_carrier_keys = {"bootstrap_locator_sha256", "inventory", "tracked_roots"}
    allowed_metadata_keys = {
        "pending_size",
        "pending_mtime_ns",
        "pending_since_scan",
        "stable_observations",
        "last_size",
        "last_mtime_ns",
        "incomplete_tail",
        "last_status",
        "last_integrity_check_at",
        "quarantine_size",
        "quarantine_mtime_ns",
        "retry_count",
        "next_retry_at",
        "retry_size",
        "retry_mtime_ns",
    }
    allowed_statuses = {
        "awaiting_stable_observation",
        "unchanged_cursor",
        "unchanged_incomplete_tail",
        "imported",
        "integrity_verified",
        "recovered_from_cursor",
        "error",
    }
    for _home, carrier_id in allowed_homes.items():
        raw = raw_carriers.get(carrier_id)
        if not isinstance(raw, dict) or set(raw) != allowed_carrier_keys:
            raise ConsumerError("consumer state carrier identity changed")
        tracked = raw.get("tracked_roots")
        inventory = raw.get("inventory")
        if not isinstance(tracked, dict) or not isinstance(inventory, dict):
            raise ConsumerError("consumer carrier inventory is invalid")
        bootstrap_hash = raw.get("bootstrap_locator_sha256")
        if bootstrap_hash and not _SHA256_RE.fullmatch(str(bootstrap_hash)):
            raise ConsumerError("consumer bootstrap locator hash is invalid")
        for locator_hash, fingerprint in inventory.items():
            if not _SHA256_RE.fullmatch(str(locator_hash)) or not isinstance(fingerprint, dict):
                raise ConsumerError("consumer inventory entry is invalid")
            if set(fingerprint) != {"size", "mtime_ns"} or any(
                type(fingerprint[key]) is not int or int(fingerprint[key]) < 0
                for key in ("size", "mtime_ns")
            ):
                raise ConsumerError("consumer inventory fingerprint is invalid")
        for locator_hash, metadata in tracked.items():
            if not _SHA256_RE.fullmatch(str(locator_hash)) or not isinstance(metadata, dict):
                raise ConsumerError("consumer tracked entry is invalid")
            if not set(metadata) <= allowed_metadata_keys:
                raise ConsumerError("consumer tracked metadata contains unknown fields")
            status = metadata.get("last_status")
            if status is not None and status not in allowed_statuses:
                raise ConsumerError("consumer tracked status is invalid")
            for key in ("pending_since_scan", "last_integrity_check_at"):
                if key in metadata:
                    _parse_utc(metadata[key], field=f"consumer {key}")
            if "next_retry_at" in metadata:
                _parse_utc(metadata["next_retry_at"], field="consumer next_retry_at")
            for key in (
                "pending_size",
                "pending_mtime_ns",
                "stable_observations",
                "last_size",
                "last_mtime_ns",
                "quarantine_size",
                "quarantine_mtime_ns",
                "retry_count",
                "retry_size",
                "retry_mtime_ns",
            ):
                if key in metadata and (type(metadata[key]) is not int or int(metadata[key]) < 0):
                    raise ConsumerError("consumer tracked numeric metadata is invalid")
            if "incomplete_tail" in metadata and type(metadata["incomplete_tail"]) is not bool:
                raise ConsumerError("consumer incomplete tail marker is invalid")
        result[carrier_id] = raw
    if set(raw_carriers) != set(result):
        raise ConsumerError("consumer state contains an unexpected carrier")
    return result


def _stage_or_recover_invalid_state(
    *,
    state_path: Path,
    consumer_dir: Path,
    root: Path,
    allowed_homes: Mapping[str, str],
    started: datetime,
) -> tuple[dict[str, object] | None, dict[str, object] | None, bool]:
    receipt_path = consumer_dir / LAST_RECEIPT_FILE_NAME
    quarantine_path = consumer_dir / STATE_QUARANTINE_FILE_NAME
    state_exists = state_path.exists()
    corrupt_hash = ""
    if state_exists:
        try:
            corrupt_hash = _sha256_regular_file(state_path)
        except (ConsumerError, OSError):
            receipt = _failed_state_receipt(
                started=started,
                error_type="consumer_state_invalid",
                recovery_status="unavailable_unsafe_state_source",
                corrupt_state_sha256="",
            )
            _atomic_json(receipt_path, receipt)
            return None, receipt, False
    try:
        marker = _load_state_quarantine(quarantine_path)
    except ConsumerError:
        receipt = _failed_state_receipt(
            started=started,
            error_type="state_quarantine_invalid",
            recovery_status="manual_intervention_required",
            corrupt_state_sha256=corrupt_hash,
        )
        _atomic_json(receipt_path, receipt)
        return None, receipt, False

    if not state_exists and marker is not None:
        corrupt_hash = str(marker["corrupt_state_sha256"])
    elif not state_exists:
        receipt = _failed_state_receipt(
            started=started,
            error_type="consumer_state_invalid",
            recovery_status="unavailable_missing_state_and_marker",
            corrupt_state_sha256="",
        )
        _atomic_json(receipt_path, receipt)
        return None, receipt, False

    if state_exists and (
        marker is None
        or marker["corrupt_state_sha256"] != corrupt_hash
        or marker["status"] != "pending_recovery"
    ):
        marker = {
            "schema_version": STATE_QUARANTINE_SCHEMA_VERSION,
            "corrupt_state_sha256": corrupt_hash,
            "status": "pending_recovery",
            "first_seen_at": _utc_text(started),
            "last_attempt_at": _utc_text(started),
            "attempts": 0,
            "authority": False,
        }
        staging_receipt = _failed_state_receipt(
            started=started,
            error_type="consumer_state_invalid",
            recovery_status="staging_hash_only_quarantine",
            corrupt_state_sha256=corrupt_hash,
        )
        _atomic_json(receipt_path, staging_receipt)
        try:
            _atomic_json(quarantine_path, marker)
            try:
                state_path.unlink()
                recovery_status = "pending_next_run"
            except OSError:
                recovery_status = "pending_next_run_state_retained"
        except ConsumerError:
            recovery_status = "unavailable_quarantine_marker"
        receipt = _failed_state_receipt(
            started=started,
            error_type="consumer_state_invalid",
            recovery_status=recovery_status,
            corrupt_state_sha256=corrupt_hash,
        )
        _atomic_json(receipt_path, receipt)
        return None, receipt, False

    if marker is None:
        raise ConsumerError("consumer state recovery marker unexpectedly disappeared")

    marker["attempts"] = int(marker["attempts"]) + 1
    marker["last_attempt_at"] = _utc_text(started)
    try:
        rebuilt = _rebuild_state_from_cursors(
            root=Path(root),
            allowed_homes=allowed_homes,
            now=started,
        )
        _validate_carrier_state(rebuilt, allowed_homes)
        _atomic_json(state_path, rebuilt)
        marker["status"] = "recovered"
        _atomic_json(quarantine_path, marker)
        return rebuilt, None, True
    except Exception:
        marker["status"] = "pending_recovery"
        try:
            _atomic_json(quarantine_path, marker)
        except ConsumerError:
            pass
        receipt = _failed_state_receipt(
            started=started,
            error_type="state_recovery_failed",
            recovery_status="pending_next_run",
            corrupt_state_sha256=corrupt_hash,
        )
        _atomic_json(receipt_path, receipt)
        return None, receipt, False


def _stage_missing_state_recovery(
    *,
    consumer_dir: Path,
    started: datetime,
) -> dict[str, object]:
    quarantine_path = consumer_dir / STATE_QUARANTINE_FILE_NAME
    receipt_path = consumer_dir / LAST_RECEIPT_FILE_NAME
    marker = {
        "schema_version": STATE_QUARANTINE_SCHEMA_VERSION,
        "corrupt_state_sha256": hashlib.sha256(b"").hexdigest(),
        "status": "pending_recovery",
        "first_seen_at": _utc_text(started),
        "last_attempt_at": _utc_text(started),
        "attempts": 0,
        "authority": False,
    }
    staging_receipt = _failed_state_receipt(
        started=started,
        error_type="consumer_state_invalid",
        recovery_status="staging_missing_state_recovery",
        corrupt_state_sha256="",
    )
    _atomic_json(receipt_path, staging_receipt)
    _atomic_json(quarantine_path, marker)
    receipt = _failed_state_receipt(
        started=started,
        error_type="consumer_state_invalid",
        recovery_status="pending_next_run",
        corrupt_state_sha256="",
    )
    _atomic_json(receipt_path, receipt)
    return receipt


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


def _append_receipt_file(
    receipt_files: list[dict[str, object]], item: Mapping[str, object]
) -> None:
    if "locator" in item or "error" in item:
        raise ConsumerError("consumer receipt cannot contain raw locator or error text")
    locator_hash = item.get("locator_sha256")
    if locator_hash is not None and not _SHA256_RE.fullmatch(str(locator_hash)):
        raise ConsumerError("consumer receipt locator hash is invalid")
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


def _integrity_recheck_due(metadata: Mapping[str, object], now: datetime) -> bool:
    value = metadata.get("last_integrity_check_at")
    if value is None:
        return True
    return (
        now - _parse_utc(value, field="consumer last_integrity_check_at")
        >= INTEGRITY_RECHECK_INTERVAL
    )


def _retry_due(metadata: Mapping[str, object], now: datetime, *, size: int, mtime_ns: int) -> bool:
    value = metadata.get("next_retry_at")
    if value is None:
        return True
    if (
        int(metadata.get("retry_size", -1)) != size
        or int(metadata.get("retry_mtime_ns", -1)) != mtime_ns
    ):
        return True
    return now >= _parse_utc(value, field="consumer next_retry_at")


def _record_retry(metadata: dict[str, object], now: datetime, *, size: int, mtime_ns: int) -> None:
    same_fingerprint = (
        int(metadata.get("retry_size", -1)) == size
        and int(metadata.get("retry_mtime_ns", -1)) == mtime_ns
    )
    retry_count = min((int(metadata.get("retry_count", 0)) if same_fingerprint else 0) + 1, 16)
    delay_seconds = min(
        IMPORT_RETRY_BASE.total_seconds() * (2 ** (retry_count - 1)),
        IMPORT_RETRY_MAX.total_seconds(),
    )
    metadata.update(
        {
            "retry_count": retry_count,
            "next_retry_at": _utc_text(now + timedelta(seconds=delay_seconds)),
            "retry_size": size,
            "retry_mtime_ns": mtime_ns,
        }
    )


def _clear_retry(metadata: dict[str, object]) -> None:
    for key in ("retry_count", "next_retry_at", "retry_size", "retry_mtime_ns"):
        metadata.pop(key, None)


def run_consumer(
    *,
    root: Path = PRODUCTION_CONTEXT_FABRIC_ROOT,
    allowed_homes: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run one shallow discovery/import transaction and return a bounded receipt."""

    started = (now or _utc_now()).astimezone(timezone.utc)
    homes = dict(DEFAULT_ALLOWED_CODEX_HOMES if allowed_homes is None else allowed_homes)
    if (
        not homes
        or len(set(homes.values())) != len(homes)
        or not set(homes.values()) <= _ALLOWED_CARRIERS
    ):
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
        receipt_path = consumer_dir / LAST_RECEIPT_FILE_NAME
        quarantine_path = consumer_dir / STATE_QUARANTINE_FILE_NAME
        state_recovered = False
        try:
            state = _load_state(state_path)
            if state is None and quarantine_path.exists():
                state, failed_receipt, state_recovered = _stage_or_recover_invalid_state(
                    state_path=state_path,
                    consumer_dir=consumer_dir,
                    root=Path(root),
                    allowed_homes=homes,
                    started=started,
                )
                if failed_receipt is not None:
                    return failed_receipt
                if state is None:
                    raise ConsumerError("consumer state recovery returned no state")
                bootstrap = False
            elif state is None and (receipt_path.exists() or _cursor_count(Path(root)) > 0):
                return _stage_missing_state_recovery(
                    consumer_dir=consumer_dir,
                    started=started,
                )
            else:
                bootstrap = state is None
                if state is None:
                    state = _new_state(started, homes)
            carrier_states = _validate_carrier_state(state, homes)
        except (ConsumerError, OSError):
            if not state_path.exists():
                raise
            state, failed_receipt, state_recovered = _stage_or_recover_invalid_state(
                state_path=state_path,
                consumer_dir=consumer_dir,
                root=Path(root),
                allowed_homes=homes,
                started=started,
            )
            if failed_receipt is not None:
                return failed_receipt
            if state is None:
                raise ConsumerError("consumer state recovery returned no state")
            bootstrap = False
            carrier_states = _validate_carrier_state(state, homes)
        cutoff = _parse_utc(state["cutoff_at"], field="consumer cutoff_at")
        previous_scan = _parse_utc(state["last_scan_at"], field="consumer last_scan_at")
        if started + DISCOVERY_OVERLAP < previous_scan:
            raise ConsumerError("consumer clock moved behind the committed scan watermark")
        scan_start = (
            started - timedelta(days=BOOTSTRAP_LOOKBACK_DAYS) if bootstrap else previous_scan
        )
        scan_end = started

        counts: Counter[str] = Counter()
        if state_recovered:
            counts["state_recovered"] = 1
        receipt_files: list[dict[str, object]] = []
        receipt_file_total = 0
        classified_roots: dict[str, list[tuple[str, RolloutClassification, int]]] = {
            carrier_id: [] for carrier_id in carrier_states
        }
        current_locators_by_carrier: dict[str, dict[str, str]] = {}

        for home_text, carrier_id in sorted(homes.items(), key=lambda item: item[1]):
            home = Path(home_text)
            carrier_state = carrier_states[carrier_id]
            previous_inventory = carrier_state["inventory"]
            assert isinstance(previous_inventory, dict)
            tracked = carrier_state["tracked_roots"]
            assert isinstance(tracked, dict)
            current_inventory, current_locators = _inventory_rollouts(home)
            current_locators_by_carrier[carrier_id] = current_locators
            changed_locator_hashes: list[str] = []
            for locator_hash, fingerprint in current_inventory.items():
                previous = previous_inventory.get(locator_hash)
                changed = _fingerprint_changed(previous, fingerprint)
                if not changed:
                    continue
                locator = current_locators[locator_hash]
                locator_timestamp = _locator_timestamp(locator)
                if bootstrap:
                    if locator_timestamp is None:
                        counts["quarantined_locator"] += 1
                        receipt_file_total += 1
                        _append_receipt_file(
                            receipt_files,
                            {
                                "carrier_id": carrier_id,
                                "locator_sha256": locator_hash,
                                "status": "quarantined",
                                "error_type": "locator_timestamp_invalid",
                            },
                        )
                        continue
                    if locator_timestamp > started + FUTURE_CLOCK_TOLERANCE:
                        counts["quarantined_locator"] += 1
                        receipt_file_total += 1
                        _append_receipt_file(
                            receipt_files,
                            {
                                "carrier_id": carrier_id,
                                "locator_sha256": locator_hash,
                                "status": "quarantined",
                                "error_type": "locator_timestamp_future",
                            },
                        )
                        continue
                    if not _bootstrap_candidate(locator, started):
                        continue
                    changed_locator_hashes.append(locator_hash)
                    continue
                if locator_hash in tracked:
                    changed_locator_hashes.append(locator_hash)
                    continue
                if previous is None:
                    if locator_timestamp is None:
                        counts["quarantined_locator"] += 1
                        receipt_file_total += 1
                        _append_receipt_file(
                            receipt_files,
                            {
                                "carrier_id": carrier_id,
                                "locator_sha256": locator_hash,
                                "status": "quarantined",
                                "error_type": "locator_timestamp_invalid",
                            },
                        )
                    elif locator_timestamp >= cutoff:
                        changed_locator_hashes.append(locator_hash)
                    else:
                        counts["new_pre_cutoff_ignored"] += 1
                    continue
                if int(fingerprint["size"]) > int(previous["size"]):
                    changed_locator_hashes.append(locator_hash)
                else:
                    counts["unadopted_non_growth_ignored"] += 1
            carrier_state["inventory"] = current_inventory
            counts["inventoried"] += len(current_inventory)
            counts["changed_candidates"] += len(changed_locator_hashes)
            for locator_hash in changed_locator_hashes:
                locator = current_locators[locator_hash]
                fingerprint = current_inventory[locator_hash]
                try:
                    path = _tracked_path(home, locator)
                except (OSError, ValueError, ConsumerError) as exc:
                    counts["classification_error"] += 1
                    receipt_file_total += 1
                    _append_receipt_file(
                        receipt_files,
                        {
                            "carrier_id": carrier_id,
                            "locator_sha256": locator_hash,
                            "status": "classification_error",
                            "error_type": _typed_error(exc),
                        },
                    )
                    continue
                classification = classify_rollout(path, now=started)
                counts[f"classified_{classification.status}"] += 1
                if classification.status != "root_cli":
                    if classification.status in {"invalid", "read_error", "quarantined"}:
                        receipt_file_total += 1
                        _append_receipt_file(
                            receipt_files,
                            {
                                "carrier_id": carrier_id,
                                "locator_sha256": locator_hash,
                                "status": (
                                    "quarantined"
                                    if classification.status == "quarantined"
                                    else "classification_error"
                                ),
                                "error_type": classification.reason,
                            },
                        )
                    continue
                classified_roots[carrier_id].append(
                    (locator_hash, classification, int(fingerprint["mtime_ns"]))
                )

        for carrier_id, roots in classified_roots.items():
            carrier_state = carrier_states[carrier_id]
            tracked = carrier_state["tracked_roots"]
            assert isinstance(tracked, dict)
            if bootstrap and roots:
                latest = max(
                    roots,
                    key=lambda item: (
                        _parse_utc(item[1].locator_timestamp, field="locator timestamp"),
                        item[2],
                        item[0],
                    ),
                )
                carrier_state["bootstrap_locator_sha256"] = latest[0]
            bootstrap_locator_hash = str(carrier_state.get("bootstrap_locator_sha256") or "")
            for locator_hash, _classification, _modified_ns in roots:
                if (bootstrap and locator_hash == bootstrap_locator_hash) or not bootstrap:
                    existing_metadata = tracked.get(locator_hash)
                    if not isinstance(existing_metadata, dict):
                        existing_metadata = {}
                        tracked[locator_hash] = existing_metadata
                    if not bootstrap:
                        fingerprint = carrier_state["inventory"][locator_hash]
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

        import_candidates: list[tuple[str, Path, str, str, dict[str, object], str]] = []
        integrity_budget = MAX_INTEGRITY_RECHECKS_PER_RUN
        for home_text, carrier_id in sorted(homes.items(), key=lambda item: item[1]):
            home = Path(home_text)
            tracked = carrier_states[carrier_id]["tracked_roots"]
            assert isinstance(tracked, dict)
            current_locators = current_locators_by_carrier[carrier_id]
            for locator_hash in sorted(tracked):
                metadata = tracked[locator_hash]
                if not isinstance(metadata, dict):
                    raise ConsumerError("tracked rollout metadata is invalid")
                try:
                    locator = current_locators.get(locator_hash)
                    if locator is None:
                        raise ConsumerError("tracked rollout is absent from inventory")
                    path = _tracked_path(home, locator)
                    stat_result = path.stat()
                    size = stat_result.st_size
                    modified_ns = stat_result.st_mtime_ns
                    cursor = _cursor_offset(Path(root), carrier_id, locator)
                    quarantine_size = metadata.get("quarantine_size")
                    quarantine_mtime_ns = metadata.get("quarantine_mtime_ns")
                    if quarantine_size is not None or quarantine_mtime_ns is not None:
                        if (
                            int(quarantine_size or -1) == size
                            and int(quarantine_mtime_ns or -1) == modified_ns
                        ):
                            counts["persistent_integrity_quarantine"] += 1
                            metadata["last_status"] = "error"
                            receipt_file_total += 1
                            _append_receipt_file(
                                receipt_files,
                                {
                                    "carrier_id": carrier_id,
                                    "locator_sha256": locator_hash,
                                    "status": "quarantined",
                                    "error_type": "context_fabric_rejected",
                                },
                            )
                            continue
                        metadata.pop("quarantine_size", None)
                        metadata.pop("quarantine_mtime_ns", None)
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
                        if _integrity_recheck_due(metadata, started):
                            if integrity_budget > 0:
                                integrity_budget -= 1
                                import_candidates.append(
                                    (
                                        carrier_id,
                                        home,
                                        locator_hash,
                                        locator,
                                        metadata,
                                        "integrity_recheck",
                                    )
                                )
                            else:
                                counts["integrity_recheck_deferred"] += 1
                            continue
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
                    if not _retry_due(metadata, started, size=size, mtime_ns=modified_ns):
                        counts["retry_backoff"] += 1
                        continue
                    import_candidates.append(
                        (carrier_id, home, locator_hash, locator, metadata, "incremental")
                    )
                except (OSError, ValueError, sqlite3.Error, ConsumerError) as exc:
                    counts["file_error"] += 1
                    receipt_file_total += 1
                    _append_receipt_file(
                        receipt_files,
                        {
                            "carrier_id": carrier_id,
                            "locator_sha256": locator_hash,
                            "status": "error",
                            "error_type": _typed_error(exc),
                        },
                    )

        import_candidates.sort(
            key=lambda item: (
                1 if "retry_count" in item[4] else 0,
                _parse_utc(item[4].get("next_retry_at"), field="consumer next_retry_at")
                if item[4].get("next_retry_at") is not None
                else datetime.min.replace(tzinfo=timezone.utc),
                item[2],
            )
        )
        for (
            carrier_id,
            home,
            locator_hash,
            locator,
            metadata,
            import_mode,
        ) in import_candidates[:MAX_IMPORTS_PER_RUN]:
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
                prior_size = int(metadata.get("last_size", -1))
                prior_mtime_ns = int(metadata.get("last_mtime_ns", -1))
                metadata["last_size"] = imported_stat.st_size
                metadata["last_mtime_ns"] = imported_stat.st_mtime_ns
                metadata["incomplete_tail"] = bool(result.get("incomplete_tail", False))
                metadata["last_integrity_check_at"] = _utc_text(started)
                metadata["last_status"] = (
                    "integrity_verified" if import_mode == "integrity_recheck" else "imported"
                )
                metadata.pop("quarantine_size", None)
                metadata.pop("quarantine_mtime_ns", None)
                _clear_retry(metadata)
                counts[
                    "integrity_verified" if import_mode == "integrity_recheck" else "imported"
                ] += 1
                counts["appended"] += int(result.get("appended", 0))
                counts["duplicate"] += int(result.get("duplicate", 0))
                counts["ignored"] += int(result.get("ignored", 0))
                _append_receipt_file(
                    receipt_files,
                    {
                        "carrier_id": carrier_id,
                        "locator_sha256": locator_hash,
                        "status": (
                            "integrity_verified"
                            if import_mode == "integrity_recheck"
                            else "imported"
                        ),
                        "appended": int(result.get("appended", 0)),
                        "duplicate": int(result.get("duplicate", 0)),
                        "ignored": int(result.get("ignored", 0)),
                        "incomplete_tail": bool(result.get("incomplete_tail", False)),
                    },
                )
                quiet_before_ns = int(
                    (started - TRACKED_STABLE_PRUNE_AFTER).timestamp() * 1_000_000_000
                )
                if (
                    import_mode == "integrity_recheck"
                    and not bool(result.get("incomplete_tail", False))
                    and imported_stat.st_size == prior_size
                    and imported_stat.st_mtime_ns == prior_mtime_ns
                    and imported_stat.st_mtime_ns <= quiet_before_ns
                ):
                    tracked = carrier_states[carrier_id]["tracked_roots"]
                    assert isinstance(tracked, dict)
                    if tracked.get(locator_hash) is metadata:
                        del tracked[locator_hash]
                        counts["stable_roots_pruned"] += 1
            except Exception as exc:  # Per-file isolation is intentional at the scheduler edge.
                metadata["last_status"] = "error"
                if import_mode == "integrity_recheck":
                    metadata["last_integrity_check_at"] = _utc_text(started)
                    try:
                        quarantined_stat = path.stat()
                        metadata["quarantine_size"] = quarantined_stat.st_size
                        metadata["quarantine_mtime_ns"] = quarantined_stat.st_mtime_ns
                    except OSError:
                        pass
                elif _typed_error(exc) != "context_fabric_unavailable":
                    try:
                        failed_stat = path.stat()
                        _record_retry(
                            metadata,
                            started,
                            size=failed_stat.st_size,
                            mtime_ns=failed_stat.st_mtime_ns,
                        )
                    except OSError:
                        pass
                counts["file_error"] += 1
                _append_receipt_file(
                    receipt_files,
                    {
                        "carrier_id": carrier_id,
                        "locator_sha256": locator_hash,
                        "status": "error",
                        "error_type": _typed_error(exc),
                    },
                )
        counts["deferred"] += max(0, len(import_candidates) - MAX_IMPORTS_PER_RUN)

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
                "classified_quarantined",
                "quarantined_locator",
                "persistent_integrity_quarantine",
            )
        )
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "completed_with_errors" if has_errors else "completed",
            "started_at": _utc_text(started),
            "finished_at": _utc_text(finished),
            "bootstrap": bootstrap,
            "state_recovered": state_recovered,
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


def _needs_quiescence_retry(receipt: Mapping[str, object]) -> bool:
    if receipt.get("status") not in {"completed", "completed_with_errors"}:
        return False
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping):
        return False
    return int(counts.get("awaiting_stable", 0)) > 0 or int(counts.get("deferred", 0)) > 0


def run_consumer_to_quiescence(
    *,
    root: Path = PRODUCTION_CONTEXT_FABRIC_ROOT,
    allowed_homes: Mapping[str, str] | None = None,
    now: datetime | None = None,
    sleeper: Callable[[float], object] = time.sleep,
) -> dict[str, object]:
    """Drain one event wake through a bounded stable-observation retry.

    The public ``run_consumer`` transaction deliberately requires a later
    stable observation before importing a growing rollout.  Task Scheduler is
    now also woken by real lifecycle events, so the one-shot task performs up
    to two short background retries instead of waiting for the low-frequency
    watchdog to provide that later observation.
    """

    elapsed = 0.0
    receipt = run_consumer(root=root, allowed_homes=allowed_homes, now=now)
    for delay_seconds in QUIESCENCE_RETRY_DELAYS_SECONDS:
        if not _needs_quiescence_retry(receipt):
            break
        sleeper(delay_seconds)
        elapsed += delay_seconds
        retry_now = None if now is None else now + timedelta(seconds=elapsed)
        receipt = run_consumer(
            root=root,
            allowed_homes=allowed_homes,
            now=retry_now,
        )
    return receipt


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Consume new S/B root CLI rollouts into the default context fabric."
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        receipt = run_consumer_to_quiescence()
        presentation_status = "not_run"
        if receipt.get("status") in {"completed", "completed_with_errors"}:
            presentation_receipt = run_presentation_step()
            presentation_status = str(presentation_receipt.get("status") or "failed")
    except Exception as exc:
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "status": "failed",
            "error_type": _typed_error(exc),
            "authority": False,
        }
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return (
        2
        if receipt.get("status") == "failed" or presentation_status == "completed_with_errors"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
