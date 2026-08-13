"""S-side observation of typed world-compute runtime state.

This module is a shallow bridge, not another controller.  It reads named
``controller_state.json`` or lineage ``state.json`` files only after their
bytes and before/after file identities are stable, compares them with one
atomic cursor, and emits already-typed :class:`RuntimeTransition` values.

Classification is intentionally closed over explicit state/error fields.  No
``last_error`` prose, research text, or model output is interpreted.  The
observer can call an injected idempotent sink, or the explicit Context Runtime
adapter below.  It does not append a hot projection, alter a hook, or emit UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.context_runtime_completion import (
    PRESENTATION_RUNTIME_TRANSITION_EVENT_KIND,
)
from services.agent_runtime.presentation_lock import (
    PresentationLockBusy,
    exclusive_presentation_lock,
)
from services.agent_runtime.presentation_reducer import (
    CATEGORY_BLOCKED,
    CATEGORY_MAJOR_RESULT,
    CATEGORY_MATERIAL,
    CATEGORY_NEEDS_USER,
    CATEGORY_ROUTINE,
    CATEGORY_RUNTIME_INCIDENT,
    CATEGORY_STOP_PAUSE,
    PresentationProjection,
    PresentationSourceRef,
    RuntimeTransition,
    reduce_presentation,
)

OBSERVER_CURSOR_SCHEMA_VERSION = "s.presentation_observer.cursor.v1"
CONTEXT_EVENT_KIND = PRESENTATION_RUNTIME_TRANSITION_EVENT_KIND
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_CURSOR_BYTES = 8 * 1024 * 1024

STATE_KIND_CONTROLLER = "controller"
STATE_KIND_LINEAGE = "lineage"
STATE_KINDS = frozenset({STATE_KIND_CONTROLLER, STATE_KIND_LINEAGE})

_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CONTROLLER_ROUTINE_STATUSES = frozenset(
    {
        "CREATED",
        "STARTING",
        "RUNNING",
        "RECOVERED_STALE_CHILD_STATE",
    }
)
_CONTROLLER_INCIDENT_STATUSES = frozenset(
    {
        "FAILED",
        "STOP_INCOMPLETE_ACTIVE_CHILD",
    }
)
_CONTROLLER_STOP_STATUSES = frozenset({"STOPPING", "STOPPED"})

_LINEAGE_ROUTINE_STATUSES = frozenset(
    {
        "CONTINUE",
        "CREATED",
        "NO_POSITIVE_FRONTIER",
        "PARKED_NO_POSITIVE_FRONTIER",
        "PARKED_WAIT",
        "READY_TO_CONTINUE",
        "RUNNING",
        "TRANSIENT_BACKOFF",
        "TURN_COMPLETED",
        "TURN_STARTED",
        "TURN_RUNNING",
        "WAIT",
        "WAITING_FOR_ACCOUNT_WORLD_TURN_QUOTA",
        "WAITING_FOR_BRANCH_WAVE",
        "WOKEN",
        "WORLD_TURN_QUOTA_ADMITTED",
        "WORLD_TURN_QUOTA_RESERVED",
    }
)
_LINEAGE_BLOCKED_STATUSES = frozenset(
    {
        "BLOCKED",
        "PARKED_BLOCKED",
        "PROVIDER_POLICY_BLOCKED",
        "ROOT_PROVIDER_POLICY_BLOCKED",
    }
)
_LINEAGE_NEEDS_USER_STATUSES = frozenset({"NEEDS_USER", "WAITING_FOR_USER"})
_LINEAGE_STOP_STATUSES = frozenset({"PAUSE", "PARKED_PAUSE", "STOPPED", "STOPPING"})
_LINEAGE_INCIDENT_STATUSES = frozenset(
    {
        "BODY_INCIDENT",
        "CONTROL_BODY_DRIFT_PAUSED",
        "CONTROLLER_THREAD_FAILED",
        "EVIDENCE_INCIDENT",
        "ROOT_BODY_INCIDENT",
        "ROOT_EVIDENCE_INCIDENT",
        "ROOT_RUNTIME_PAUSED",
        "RUNTIME_PAUSED",
        "TURN_FAILED",
    }
)
_LINEAGE_MATERIAL_STATUSES = frozenset(
    {
        "TURN_COMPLETED_RECOVERED",
        "TURN_COMPLETED_RECOVERED_STATE_COMMIT",
    }
)
_NON_INCIDENT_ERROR_CLASSES = frozenset(
    {
        "",
        "STOP_REQUESTED",
        "TRANSIENT_RUNTIME_FAILURE",
        "PROVIDER_POLICY_BLOCKED",
    }
)


class PresentationObserverError(RuntimeError):
    """A state source or cursor violated the observer contract."""


class ObserverReadUnstable(PresentationObserverError):
    """A state file changed while it was being observed; retry later."""


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PresentationObserverError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, *, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PresentationObserverError(f"{field} must be a string or null")
    return value.strip()


def _typed_token(value: object, *, field: str, allow_empty: bool = False) -> str:
    text = _optional_text(value, field=field).upper()
    if not text and allow_empty:
        return ""
    if _TOKEN_RE.fullmatch(text) is None:
        raise PresentationObserverError(f"{field} must be an uppercase typed token")
    return text


def _typed_bool(value: object, *, field: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PresentationObserverError(f"{field} must be a bool")
    return value


def _non_negative_int(value: object, *, field: str, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PresentationObserverError(f"{field} must be a non-negative integer")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _parse_instant(value: object, *, field: str) -> tuple[str, datetime]:
    text = _required_text(value, field=field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PresentationObserverError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise PresentationObserverError(f"{field} must include a timezone")
    normalized = parsed.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z"), normalized


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
    except OSError:
        return True


@dataclass(frozen=True, slots=True)
class RuntimeStateSource:
    """One exact runtime state file and its presentation scope."""

    path: Path
    state_kind: str
    expected_run_id: str
    expected_schema: str
    activity_id: str
    audience: str = "user"
    expected_lineage_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        kind = _required_text(self.state_kind, field="state_kind").lower()
        if kind not in STATE_KINDS:
            raise PresentationObserverError("state_kind must be controller or lineage")
        object.__setattr__(self, "state_kind", kind)
        object.__setattr__(
            self,
            "expected_run_id",
            _required_text(self.expected_run_id, field="expected_run_id"),
        )
        object.__setattr__(
            self,
            "activity_id",
            _required_text(self.activity_id, field="activity_id"),
        )
        object.__setattr__(self, "audience", _required_text(self.audience, field="audience"))
        lineage_id = _optional_text(self.expected_lineage_id, field="expected_lineage_id")
        if kind == STATE_KIND_LINEAGE and not lineage_id:
            raise PresentationObserverError("lineage sources require expected_lineage_id")
        if kind == STATE_KIND_CONTROLLER and lineage_id:
            raise PresentationObserverError("controller sources cannot have expected_lineage_id")
        object.__setattr__(self, "expected_lineage_id", lineage_id)
        object.__setattr__(
            self,
            "expected_schema",
            _required_text(self.expected_schema, field="expected_schema"),
        )

    @property
    def source_kind(self) -> str:
        return f"xinao_{self.state_kind}_state"


@dataclass(frozen=True, slots=True)
class _StableSnapshot:
    source: RuntimeStateSource
    resolved_path: Path
    source_record_sha256: str
    runtime_updated_at: str
    runtime_updated_instant: datetime
    writer_ordinal: int | None
    typed_state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ObservationBatch:
    """One observer transaction after all sinks and the cursor commit."""

    transitions: tuple[RuntimeTransition, ...]
    projections: tuple[PresentationProjection, ...]
    observed_source_count: int
    unchanged_source_count: int
    cursor_updated: bool
    sink_results: tuple[object, ...]

    @property
    def status(self) -> str:
        return "observed" if self.transitions else "unchanged"


def _fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat_result = path.stat()
    if not path.is_file() or _is_link(path):
        raise PresentationObserverError(f"runtime state source must be a regular file: {path}")
    return (
        int(stat_result.st_dev),
        int(stat_result.st_ino),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
    )


def _reject_reparse_path(path: Path, *, field: str) -> None:
    absolute = path.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.exists() and _is_link(candidate):
            raise PresentationObserverError(f"{field} cannot traverse a link or junction")


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _stable_json_bytes(path: Path) -> tuple[Path, bytes]:
    try:
        _reject_reparse_path(path, field="runtime state source")
        if not path.is_file():
            raise PresentationObserverError(f"runtime state source must be a regular file: {path}")
        resolved = path.resolve(strict=True)
        before = _fingerprint(resolved)
        if before[2] > MAX_STATE_BYTES:
            raise PresentationObserverError(f"runtime state source exceeds size limit: {resolved}")
        first = _read_bytes(resolved)
        middle = _fingerprint(resolved)
        second = _read_bytes(resolved)
        after = _fingerprint(resolved)
    except FileNotFoundError as exc:
        raise PresentationObserverError(f"runtime state source is missing: {path}") from exc
    except OSError as exc:
        raise ObserverReadUnstable(
            f"runtime state source could not be read stably: {path}"
        ) from exc
    if before != middle or middle != after or first != second:
        raise ObserverReadUnstable(f"runtime state source changed during read: {resolved}")
    return resolved, first


def _validated_payload(source: RuntimeStateSource, raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PresentationObserverError("runtime state source is not a UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise PresentationObserverError("runtime state source must be a JSON object")
    if value.get("run_id") != source.expected_run_id:
        raise PresentationObserverError("runtime state run_id does not match the named source")
    if value.get("schema") != source.expected_schema:
        raise PresentationObserverError("runtime state schema does not match the named source")
    if source.state_kind == STATE_KIND_LINEAGE:
        if value.get("lineage_id") != source.expected_lineage_id:
            raise PresentationObserverError(
                "runtime lineage_id does not match the named lineage source"
            )
    else:
        if not isinstance(value.get("lineages"), Mapping):
            raise PresentationObserverError("controller state requires a typed lineages object")
        if not isinstance(value.get("thread_errors", {}), Mapping):
            raise PresentationObserverError("controller thread_errors must be an object")
    return value


def _typed_state(source: RuntimeStateSource, payload: Mapping[str, Any]) -> dict[str, Any]:
    status = _typed_token(payload.get("status"), field="runtime status")
    lifecycle = _typed_token(
        payload.get("lifecycle_state"),
        field="runtime lifecycle_state",
        allow_empty=True,
    )
    last_error_class = _typed_token(
        payload.get("last_error_class"),
        field="runtime last_error_class",
        allow_empty=True,
    )
    thread_error_keys: list[str] = []
    lineage_summaries: dict[str, dict[str, Any]] = {}
    if source.state_kind == STATE_KIND_CONTROLLER:
        raw_thread_errors = payload.get("thread_errors", {})
        assert isinstance(raw_thread_errors, Mapping)
        for key in raw_thread_errors:
            thread_error_keys.append(_required_text(key, field="thread error identity"))
        raw_lineages = payload.get("lineages", {})
        assert isinstance(raw_lineages, Mapping)
        for raw_lineage_id, raw_summary in raw_lineages.items():
            lineage_id = _required_text(raw_lineage_id, field="controller lineage identity")
            if not isinstance(raw_summary, Mapping):
                raise PresentationObserverError("controller lineage summary must be an object")
            lineage_summaries[lineage_id] = {
                "status": _typed_token(
                    raw_summary.get("status"),
                    field="controller lineage status",
                ),
                "lifecycle_state": _typed_token(
                    raw_summary.get("lifecycle_state"),
                    field="controller lineage lifecycle_state",
                    allow_empty=True,
                ),
                "last_error_class": _typed_token(
                    raw_summary.get("last_error_class"),
                    field="controller lineage last_error_class",
                    allow_empty=True,
                ),
                "turns_completed": _non_negative_int(
                    raw_summary.get("turns_completed"),
                    field="controller lineage turns_completed",
                ),
            }
    return {
        "run_id": source.expected_run_id,
        "lineage_id": source.expected_lineage_id,
        "state_kind": source.state_kind,
        "status": status,
        "lifecycle_state": lifecycle,
        "last_error_class": last_error_class,
        "stop_requested": _typed_bool(
            payload.get("stop_requested"),
            field="stop_requested",
        ),
        "turns_completed": _non_negative_int(
            payload.get("turns_completed"),
            field="turns_completed",
        ),
        "thread_error_keys": sorted(thread_error_keys),
        "lineages": dict(sorted(lineage_summaries.items())),
    }


def _writer_ordinal(payload: Mapping[str, Any]) -> int | None:
    explicit = payload.get("presentation_ordinal")
    if explicit is None:
        return None
    return _non_negative_int(explicit, field="presentation_ordinal")


def _read_snapshot(source: RuntimeStateSource) -> _StableSnapshot:
    resolved, raw = _stable_json_bytes(source.path)
    payload = _validated_payload(source, raw)
    updated_at_text, updated_at = _parse_instant(
        payload.get("updated_at"),
        field="runtime updated_at",
    )
    return _StableSnapshot(
        source=source,
        resolved_path=resolved,
        source_record_sha256=_sha256_bytes(raw),
        runtime_updated_at=updated_at_text,
        runtime_updated_instant=updated_at,
        writer_ordinal=_writer_ordinal(payload),
        typed_state=_typed_state(source, payload),
    )


def _revalidate_snapshot_set(snapshots: list[_StableSnapshot]) -> None:
    """Re-read the complete source set before any downstream side effect."""

    for snapshot in snapshots:
        current = _read_snapshot(snapshot.source)
        if (
            current.resolved_path != snapshot.resolved_path
            or current.source_record_sha256 != snapshot.source_record_sha256
        ):
            raise ObserverReadUnstable(
                f"runtime state source set changed during batch read: {snapshot.resolved_path}"
            )


def _validate_cross_source_coherence(snapshots: list[_StableSnapshot]) -> None:
    controllers = {
        snapshot.source.expected_run_id: snapshot
        for snapshot in snapshots
        if snapshot.source.state_kind == STATE_KIND_CONTROLLER
    }
    for snapshot in snapshots:
        if snapshot.source.state_kind != STATE_KIND_LINEAGE:
            continue
        controller = controllers.get(snapshot.source.expected_run_id)
        if controller is None:
            continue
        summaries = controller.typed_state["lineages"]
        summary = summaries.get(snapshot.source.expected_lineage_id)
        if not isinstance(summary, Mapping):
            raise ObserverReadUnstable(
                "controller snapshot does not contain the named lineage snapshot"
            )
        lineage = snapshot.typed_state
        comparable = {
            "status": lineage["status"],
            "lifecycle_state": lineage["lifecycle_state"],
            "last_error_class": lineage["last_error_class"],
            "turns_completed": lineage["turns_completed"],
        }
        if dict(summary) != comparable:
            raise ObserverReadUnstable(
                "controller and lineage snapshots do not describe one stable runtime state"
            )


def _classify(snapshot: _StableSnapshot) -> str:
    state = snapshot.typed_state
    status = str(state["status"])
    lifecycle = str(state["lifecycle_state"])
    error_class = str(state["last_error_class"])

    if snapshot.source.state_kind == STATE_KIND_CONTROLLER:
        lineage_states = list(state["lineages"].values())
        if (
            status in _CONTROLLER_INCIDENT_STATUSES
            or state["thread_error_keys"]
            or any(
                str(lineage["status"]) in _LINEAGE_INCIDENT_STATUSES
                or str(lineage["last_error_class"]) not in _NON_INCIDENT_ERROR_CLASSES
                for lineage in lineage_states
            )
        ):
            return CATEGORY_RUNTIME_INCIDENT
        if bool(state["stop_requested"]) or status in _CONTROLLER_STOP_STATUSES:
            return CATEGORY_STOP_PAUSE
        if any(
            str(lineage["status"]) in _LINEAGE_NEEDS_USER_STATUSES for lineage in lineage_states
        ):
            return CATEGORY_NEEDS_USER
        if any(
            str(lineage["status"]) in _LINEAGE_BLOCKED_STATUSES
            or str(lineage["lifecycle_state"]) == "BLOCKED"
            for lineage in lineage_states
        ):
            return CATEGORY_BLOCKED
        if any(
            str(lineage["status"]) in _LINEAGE_STOP_STATUSES
            or str(lineage["lifecycle_state"]) == "PAUSE"
            for lineage in lineage_states
        ):
            return CATEGORY_STOP_PAUSE
        if status == "MAJOR_RESEARCH_RESULT":
            return CATEGORY_MAJOR_RESULT
        if status == "MATERIAL_STATE_CHANGE" or any(
            str(lineage["status"]) in _LINEAGE_MATERIAL_STATUSES for lineage in lineage_states
        ):
            return CATEGORY_MATERIAL
        if status in _CONTROLLER_ROUTINE_STATUSES:
            return CATEGORY_ROUTINE
        raise PresentationObserverError(f"unsupported controller status: {status}")

    if status in _LINEAGE_INCIDENT_STATUSES or error_class not in _NON_INCIDENT_ERROR_CLASSES:
        return CATEGORY_RUNTIME_INCIDENT
    if lifecycle == "PAUSE" or status in _LINEAGE_STOP_STATUSES:
        return CATEGORY_STOP_PAUSE
    if status in _LINEAGE_NEEDS_USER_STATUSES:
        return CATEGORY_NEEDS_USER
    if lifecycle == "BLOCKED" or status in _LINEAGE_BLOCKED_STATUSES:
        return CATEGORY_BLOCKED
    if status == "MAJOR_RESEARCH_RESULT":
        return CATEGORY_MAJOR_RESULT
    if status == "MATERIAL_STATE_CHANGE":
        return CATEGORY_MATERIAL
    if status in _LINEAGE_MATERIAL_STATUSES:
        return CATEGORY_MATERIAL
    if (
        lifecycle in {"WAIT", "NO_POSITIVE_FRONTIER", "CONTINUE", ""}
        and status in _LINEAGE_ROUTINE_STATUSES
    ):
        return CATEGORY_ROUTINE
    raise PresentationObserverError(
        f"unsupported lineage status/lifecycle: {status}/{lifecycle or 'NONE'}"
    )


def _source_identity(source: RuntimeStateSource, resolved_path: Path) -> dict[str, str]:
    return {
        "path": str(resolved_path),
        "state_kind": source.state_kind,
        "run_id": source.expected_run_id,
        "lineage_id": source.expected_lineage_id,
        "activity_id": source.activity_id,
        "audience": source.audience,
        "schema": source.expected_schema,
    }


def _cursor_key(source: RuntimeStateSource, resolved_path: Path) -> str:
    return _sha256_value(_source_identity(source, resolved_path))


def _context_source_key_values(
    *,
    activity_id: str,
    audience: str,
    category: str,
    state_ref: str,
    source_kind: str,
    source_locator: str,
    source_record_sha256: str,
) -> str:
    identity = {
        "schema": OBSERVER_CURSOR_SCHEMA_VERSION,
        "activity_id": activity_id,
        "audience": audience,
        "category": category,
        "state_ref": state_ref,
        "source_kind": source_kind,
        "source_locator": source_locator,
        "source_record_sha256": source_record_sha256,
    }
    return f"presentation-observer:v1:{_sha256_value(identity)}"


def _context_source_key(transition: RuntimeTransition) -> str:
    return _context_source_key_values(
        activity_id=transition.activity_id,
        audience=transition.audience,
        category=transition.category,
        state_ref=transition.state_ref,
        source_kind=transition.source.source_kind,
        source_locator=transition.source.source_locator,
        source_record_sha256=transition.source.source_record_sha256,
    )


def _transition_from_snapshot(
    snapshot: _StableSnapshot,
    *,
    previous_cursor: Mapping[str, Any] | None,
    surface_ordinal: int,
) -> RuntimeTransition:
    category = _classify(snapshot)
    state = snapshot.typed_state
    state_ref = f"state_{_sha256_value(state)}"
    if previous_cursor is not None and previous_cursor.get("last_state_ref") == state_ref:
        # A byte-level change that leaves every typed state fact unchanged is a
        # heartbeat.  Decide this before deriving the canonical event identity.
        category = CATEGORY_ROUTINE
    identity = snapshot.source.expected_run_id
    if snapshot.source.expected_lineage_id:
        identity += f"/{snapshot.source.expected_lineage_id}"
    status_text = f"{identity} status={state['status']}"
    if state["lifecycle_state"]:
        status_text += f" lifecycle={state['lifecycle_state']}"
    recovered = False
    delta_text = "" if category == CATEGORY_ROUTINE else f"{identity} category={category}"
    source_locator = f"{snapshot.resolved_path}#updated_at={snapshot.runtime_updated_at}"
    source_key = _context_source_key_values(
        activity_id=snapshot.source.activity_id,
        audience=snapshot.source.audience,
        category=category,
        state_ref=state_ref,
        source_kind=snapshot.source.source_kind,
        source_locator=source_locator,
        source_record_sha256=snapshot.source_record_sha256,
    )
    event_id = f"evt_{_sha256_bytes(source_key.encode('utf-8'))}"
    return RuntimeTransition(
        activity_id=snapshot.source.activity_id,
        audience=snapshot.source.audience,
        category=category,
        state_ref=state_ref,
        status_text=status_text,
        delta_text=delta_text,
        recovered_to_same_state=recovered,
        source=PresentationSourceRef(
            event_id=event_id,
            event_hash=snapshot.source_record_sha256,
            source_kind=snapshot.source.source_kind,
            source_locator=source_locator,
            source_record_sha256=snapshot.source_record_sha256,
            rollout_ordinal=surface_ordinal,
            phase="runtime_transition",
        ),
    )


def _load_cursor(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": OBSERVER_CURSOR_SCHEMA_VERSION,
            "sources": {},
            "next_surface_ordinal": 0,
            "pending": None,
            "authority": False,
        }
    if not path.is_file() or _is_link(path):
        raise PresentationObserverError("observer cursor must be a regular file")
    try:
        if path.stat().st_size > MAX_CURSOR_BYTES:
            raise PresentationObserverError("observer cursor exceeds its size limit")
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PresentationObserverError("observer cursor is unreadable") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "sources",
            "next_surface_ordinal",
            "pending",
            "authority",
        }
        or value.get("schema_version") != OBSERVER_CURSOR_SCHEMA_VERSION
        or value.get("authority") is not False
        or not isinstance(value.get("sources"), dict)
    ):
        raise PresentationObserverError("observer cursor contract is invalid")
    _non_negative_int(value["next_surface_ordinal"], field="cursor next_surface_ordinal")
    for key, entry in value["sources"].items():
        _validate_cursor_source_entry(key, entry)
    pending = value["pending"]
    if pending is not None:
        if (
            not isinstance(pending, dict)
            or set(pending) != {"transitions", "source_entries", "next_surface_ordinal"}
            or not isinstance(pending["transitions"], list)
            or not pending["transitions"]
            or not isinstance(pending["source_entries"], dict)
        ):
            raise PresentationObserverError("observer pending outbox is invalid")
        transitions = [RuntimeTransition.from_value(item) for item in pending["transitions"]]
        if len({item.source.event_id for item in transitions}) != len(transitions):
            raise PresentationObserverError("observer pending outbox contains duplicate events")
        for key, entry in pending["source_entries"].items():
            _validate_cursor_source_entry(key, entry)
        if len(pending["source_entries"]) != len(transitions):
            raise PresentationObserverError("observer pending outbox source count is inconsistent")
        pending_next = _non_negative_int(
            pending["next_surface_ordinal"],
            field="pending next_surface_ordinal",
        )
        if pending_next <= int(value["next_surface_ordinal"]):
            raise PresentationObserverError("observer pending outbox ordinal did not advance")
    return value


def _validate_cursor_source_entry(key: object, entry: object) -> None:
    if _SHA256_RE.fullmatch(str(key)) is None or not isinstance(entry, dict):
        raise PresentationObserverError("observer cursor source entry is invalid")
    required = {
        "identity",
        "source_record_sha256",
        "runtime_updated_at",
        "surface_ordinal",
        "writer_ordinal",
        "typed_state_sha256",
        "last_state_ref",
        "last_category",
    }
    if set(entry) != required:
        raise PresentationObserverError("observer cursor source entry shape changed")
    if not isinstance(entry["identity"], dict):
        raise PresentationObserverError("observer cursor source identity is invalid")
    for digest_field in ("source_record_sha256", "typed_state_sha256"):
        if _SHA256_RE.fullmatch(str(entry[digest_field])) is None:
            raise PresentationObserverError("observer cursor digest is invalid")
    _parse_instant(entry["runtime_updated_at"], field="cursor runtime_updated_at")
    _non_negative_int(entry["surface_ordinal"], field="cursor surface_ordinal")
    if entry["writer_ordinal"] is not None:
        _non_negative_int(entry["writer_ordinal"], field="cursor writer_ordinal")
    _required_text(entry["last_state_ref"], field="cursor last_state_ref")
    _required_text(entry["last_category"], field="cursor last_category")


def _atomic_write_cursor(path: Path, cursor: Mapping[str, Any]) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_path(parent, field="observer cursor parent")
    if _is_link(parent) or not parent.is_dir():
        raise PresentationObserverError("observer cursor parent must be a regular directory")
    if path.exists() and (not path.is_file() or _is_link(path)):
        raise PresentationObserverError("observer cursor target is unsafe")
    encoded = _canonical_bytes(cursor) + b"\n"
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _cursor_entry(snapshot: _StableSnapshot, transition: RuntimeTransition) -> dict[str, Any]:
    return {
        "identity": _source_identity(snapshot.source, snapshot.resolved_path),
        "source_record_sha256": snapshot.source_record_sha256,
        "runtime_updated_at": snapshot.runtime_updated_at,
        "surface_ordinal": transition.source.rollout_ordinal,
        "writer_ordinal": snapshot.writer_ordinal,
        "typed_state_sha256": _sha256_value(snapshot.typed_state),
        "last_state_ref": transition.state_ref,
        "last_category": transition.category,
    }


def _rebind_sink_result(transition: RuntimeTransition, result: object) -> RuntimeTransition:
    if result is None:
        return transition
    if isinstance(result, Mapping):
        event_id = result.get("event_id")
        event_hash = result.get("event_hash")
        database_seq = result.get("seq")
    else:
        event_id = getattr(result, "event_id", None)
        event_hash = getattr(result, "event_hash", None)
        database_seq = getattr(result, "seq", None)
    if event_id is None and event_hash is None and database_seq is None:
        return transition
    if event_id != transition.source.event_id:
        raise PresentationObserverError("sink rebound the observation to another event identity")
    if not isinstance(event_hash, str) or _SHA256_RE.fullmatch(event_hash) is None:
        raise PresentationObserverError("sink did not return a valid event_hash")
    sequence = _non_negative_int(database_seq, field="sink event seq")
    return replace(
        transition,
        source=replace(
            transition.source,
            event_hash=event_hash,
            database_seq=sequence,
        ),
    )


def append_transition_to_context(
    transition: RuntimeTransition,
    *,
    root: Path,
    carrier_id: str,
    environ: Mapping[str, str] | None = None,
) -> object:
    """Append one observer transition through Context Runtime's public API.

    The event kind is neither a message nor an existing hot projection kind.
    ``projection_kind`` is metadata for a later dedicated presentation
    producer/consumer; this function does not call the hot materializer.
    """

    from services.agent_runtime import context_fabric
    from services.agent_runtime.context_runtime_completion import (
        append_presentation_runtime_transition,
    )

    try:
        return append_presentation_runtime_transition(
            transition,
            root=Path(root),
            carrier_id=_required_text(carrier_id, field="carrier_id"),
            environ=environ,
        )
    except context_fabric.ContextFabricError as exc:
        raise PresentationObserverError(str(exc)) from exc


def make_context_event_sink(
    *,
    root: Path,
    carrier_id: str,
    environ: Mapping[str, str] | None = None,
) -> Callable[[RuntimeTransition], object]:
    """Return an idempotent canonical sink for :func:`observe_runtime_states`."""

    def sink(transition: RuntimeTransition) -> object:
        return append_transition_to_context(
            transition,
            root=root,
            carrier_id=carrier_id,
            environ=environ,
        )

    return sink


def _validate_source_advance(
    snapshot: _StableSnapshot,
    previous: Mapping[str, Any],
) -> None:
    previous_text, previous_instant = _parse_instant(
        previous.get("runtime_updated_at"),
        field="cursor runtime_updated_at",
    )
    if snapshot.runtime_updated_instant < previous_instant:
        raise PresentationObserverError(
            "runtime updated_at moved backwards; refusing stale state replacement"
        )
    previous_writer = previous.get("writer_ordinal")
    if previous_writer is not None:
        previous_writer_value = _non_negative_int(
            previous_writer,
            field="cursor writer_ordinal",
        )
        if snapshot.writer_ordinal is None:
            raise PresentationObserverError("runtime presentation_ordinal disappeared")
        if snapshot.writer_ordinal < previous_writer_value:
            raise PresentationObserverError("runtime presentation_ordinal moved backwards")
        if (
            snapshot.writer_ordinal == previous_writer_value
            and snapshot.source_record_sha256 != previous.get("source_record_sha256")
        ):
            raise PresentationObserverError(
                "runtime presentation_ordinal was reused for different state bytes"
            )
    if (
        snapshot.writer_ordinal is not None
        and previous_writer is None
        and snapshot.runtime_updated_at == previous_text
    ):
        # Adding a writer ordinal at the same timestamp is safe; it becomes the
        # stricter contract for later observations.
        return


def _sink_transitions(
    transitions: tuple[RuntimeTransition, ...],
    sink: Callable[[RuntimeTransition], object],
) -> tuple[list[RuntimeTransition], list[object]]:
    emitted: list[RuntimeTransition] = []
    results: list[object] = []
    for transition in transitions:
        result = sink(transition)
        results.append(result)
        emitted.append(_rebind_sink_result(transition, result))
    return emitted, results


def _declared_source_identities(sources: list[RuntimeStateSource]) -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for source in sources:
        _reject_reparse_path(source.path, field="runtime state source")
        identities.append(_source_identity(source, source.path.resolve(strict=False)))
    return identities


def _replay_pending_outbox(
    cursor: dict[str, Any],
    *,
    sources: list[RuntimeStateSource],
    cursor_path: Path,
    sink: Callable[[RuntimeTransition], object] | None,
) -> ObservationBatch | None:
    pending = cursor["pending"]
    if pending is None:
        return None
    assert isinstance(pending, dict)
    source_entries = pending["source_entries"]
    assert isinstance(source_entries, dict)
    declared = _declared_source_identities(sources)
    for entry in source_entries.values():
        assert isinstance(entry, dict)
        if entry["identity"] not in declared:
            raise PresentationObserverError(
                "pending observer outbox does not match the named source set"
            )
    transitions = tuple(RuntimeTransition.from_value(value) for value in pending["transitions"])
    if sink is None:
        return ObservationBatch(
            transitions=transitions,
            projections=reduce_presentation(transitions),
            observed_source_count=len(sources),
            unchanged_source_count=0,
            cursor_updated=False,
            sink_results=(),
        )

    emitted, results = _sink_transitions(transitions, sink)
    next_sources = dict(cursor["sources"])
    next_sources.update(source_entries)
    committed = {
        "schema_version": OBSERVER_CURSOR_SCHEMA_VERSION,
        "sources": dict(sorted(next_sources.items())),
        "next_surface_ordinal": pending["next_surface_ordinal"],
        "pending": None,
        "authority": False,
    }
    _atomic_write_cursor(cursor_path, committed)
    return ObservationBatch(
        transitions=tuple(emitted),
        projections=reduce_presentation(emitted),
        observed_source_count=len(sources),
        unchanged_source_count=0,
        cursor_updated=True,
        sink_results=tuple(results),
    )


def _observe_runtime_states_locked(
    sources: list[RuntimeStateSource],
    *,
    cursor_path: Path,
    sink: Callable[[RuntimeTransition], object] | None,
) -> ObservationBatch:
    cursor = _load_cursor(cursor_path)
    replayed = _replay_pending_outbox(
        cursor,
        sources=sources,
        cursor_path=cursor_path,
        sink=sink,
    )
    if replayed is not None:
        return replayed
    cursor_sources = cursor["sources"]
    assert isinstance(cursor_sources, dict)

    snapshots = [_read_snapshot(source) for source in sources]
    _revalidate_snapshot_set(snapshots)
    _validate_cross_source_coherence(snapshots)
    keyed: list[tuple[str, _StableSnapshot]] = []
    seen_keys: set[str] = set()
    for snapshot in snapshots:
        key = _cursor_key(snapshot.source, snapshot.resolved_path)
        if key in seen_keys:
            raise PresentationObserverError("runtime state sources must be unique")
        seen_keys.add(key)
        keyed.append((key, snapshot))
    keyed.sort(
        key=lambda item: (
            item[1].runtime_updated_instant,
            item[1].writer_ordinal if item[1].writer_ordinal is not None else -1,
            item[0],
        )
    )

    staged: list[tuple[str, _StableSnapshot, RuntimeTransition]] = []
    unchanged = 0
    next_ordinal = _non_negative_int(
        cursor["next_surface_ordinal"],
        field="cursor next_surface_ordinal",
    )
    for key, snapshot in keyed:
        previous = cursor_sources.get(key)
        if isinstance(previous, Mapping):
            expected_identity = _source_identity(snapshot.source, snapshot.resolved_path)
            if previous.get("identity") != expected_identity:
                raise PresentationObserverError("observer cursor source identity drifted")
            if previous.get("source_record_sha256") == snapshot.source_record_sha256:
                unchanged += 1
                continue
            _validate_source_advance(snapshot, previous)
        transition = _transition_from_snapshot(
            snapshot,
            previous_cursor=previous,
            surface_ordinal=next_ordinal,
        )
        next_ordinal += 1
        staged.append((key, snapshot, transition))

    preflight = tuple(transition for _key, _snapshot, transition in staged)
    reduce_presentation(preflight)

    if not staged:
        return ObservationBatch(
            transitions=(),
            projections=(),
            observed_source_count=len(sources),
            unchanged_source_count=unchanged,
            cursor_updated=False,
            sink_results=(),
        )

    if sink is None:
        emitted = list(preflight)
        sink_results: list[object] = []
    else:
        pending_entries = {
            key: _cursor_entry(snapshot, transition) for key, snapshot, transition in staged
        }
        pending_cursor = {
            "schema_version": OBSERVER_CURSOR_SCHEMA_VERSION,
            "sources": dict(sorted(cursor_sources.items())),
            "next_surface_ordinal": cursor["next_surface_ordinal"],
            "pending": {
                "transitions": [transition.as_dict() for transition in preflight],
                "source_entries": dict(sorted(pending_entries.items())),
                "next_surface_ordinal": next_ordinal,
            },
            "authority": False,
        }
        _atomic_write_cursor(cursor_path, pending_cursor)
        emitted, sink_results = _sink_transitions(preflight, sink)
        committed_sources = dict(cursor_sources)
        committed_sources.update(pending_entries)
        committed_cursor = {
            "schema_version": OBSERVER_CURSOR_SCHEMA_VERSION,
            "sources": dict(sorted(committed_sources.items())),
            "next_surface_ordinal": next_ordinal,
            "pending": None,
            "authority": False,
        }
        _atomic_write_cursor(cursor_path, committed_cursor)

    projections = reduce_presentation(emitted)

    return ObservationBatch(
        transitions=tuple(emitted),
        projections=projections,
        observed_source_count=len(sources),
        unchanged_source_count=unchanged,
        cursor_updated=bool(staged) and sink is not None,
        sink_results=tuple(sink_results),
    )


def observe_runtime_states(
    sources: Iterable[RuntimeStateSource],
    *,
    cursor_path: Path,
    sink: Callable[[RuntimeTransition], object] | None = None,
) -> ObservationBatch:
    """Observe one stable batch, emit changed transitions, then commit cursor.

    Every source set is read twice and preflight-reduced before any sink is called.  A
    changing or invalid source therefore leaves both sinks and cursor untouched.
    A sink must be idempotent by the exact transition source identity: if the
    process dies after sink success but before cursor replacement, the source
    is intentionally replayed on the next run.  The canonical adapter above
    satisfies this using Context Runtime's ``source_key`` contract.

    ``sink=None`` is an explicit dry run: transitions and projections are
    returned but the cursor is not advanced, because an in-memory return is not
    a durable acceptance point.
    """

    normalized = list(sources)
    if not normalized:
        raise PresentationObserverError("at least one named runtime state source is required")
    if not all(isinstance(source, RuntimeStateSource) for source in normalized):
        raise TypeError("sources must contain RuntimeStateSource values")

    cursor_path = Path(cursor_path)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_path(cursor_path.parent, field="observer cursor parent")
    lock_path = cursor_path.with_name(f"{cursor_path.name}.lock")
    _reject_reparse_path(lock_path, field="observer cursor lock")
    try:
        with exclusive_presentation_lock(lock_path):
            return _observe_runtime_states_locked(
                normalized,
                cursor_path=cursor_path,
                sink=sink,
            )
    except PresentationLockBusy as exc:
        raise PresentationObserverError("observer cursor is busy; retry later") from exc


__all__ = [
    "CONTEXT_EVENT_KIND",
    "MAX_CURSOR_BYTES",
    "MAX_STATE_BYTES",
    "OBSERVER_CURSOR_SCHEMA_VERSION",
    "ObservationBatch",
    "ObserverReadUnstable",
    "PresentationObserverError",
    "RuntimeStateSource",
    "STATE_KIND_CONTROLLER",
    "STATE_KIND_LINEAGE",
    "append_transition_to_context",
    "make_context_event_sink",
    "observe_runtime_states",
]
