"""A thin, replaceable projection of the current human--Codex situation.

This module is deliberately not a task, plan, authority, or completion store.  It
keeps only what is current, applies one explicitly dispositioned revision at a
time, and writes the displaced preimage to a separate cold evidence directory.
The projection is always provisional and non-authoritative.  Production
consumers may use it only as a bounded checkpoint at an explicit session
boundary; it never selects a task, owner, action, or completion state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

CURRENT_SITUATION_VERSION = "codex.current_situation.v1"
TRANSITION_VERSION = "codex.current_situation_transition.v1"
REVISION_RECEIPT_VERSION = "codex.current_situation_revision_receipt.v1"

MATERIALITIES = frozenset({"NO_MATERIAL_CHANGE", "MATERIAL_REVISION"})
EVENT_RELATIONS = frozenset(
    {
        "clarification",
        "correction",
        "discussion",
        "enrichment",
        "explicit_action",
        "reality_update",
        "recovery",
        "topic_return",
        "topic_shift",
    }
)
ACTIVITY_MODES = frozenset({"construction", "discussion", "investigation", "mixed", "waiting"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CURRENT_COLLECTIONS = ("open_relations", "retracted", "understandings")
_CURRENT_FIELDS = ("activity", "human_relation", "object")
_MAX_TEXT_CHARS = 8_192
_MAX_CURRENT_ITEMS = 32
MAX_SNAPSHOT_BYTES = 262_144
LOCK_TIMEOUT_SECONDS = 10.0


class CurrentSituationError(ValueError):
    """The current projection or proposed transition is unsafe or inconsistent."""


class CurrentSituationConflict(CurrentSituationError):
    """The transition was formed against a different current projection."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the sole stable hash representation for this bounded store."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def artifact_json_bytes(value: object) -> bytes:
    """Return stable human-readable bytes for a checkpoint or cold receipt."""

    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


@contextmanager
def _exclusive_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire one stdlib file lock without requiring the repository venv."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise CurrentSituationConflict(
                        "current situation store is busy; retry the explicit checkpoint"
                    ) from exc
                time.sleep(0.05)
        yield
    finally:
        try:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CurrentSituationError(f"{field} must be an object")
    return dict(value)


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CurrentSituationError(f"{field} keys mismatch: missing={missing}, extra={extra}")


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CurrentSituationError(f"{field} must be text")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise CurrentSituationError(f"{field} must not be empty")
    if len(normalized) > _MAX_TEXT_CHARS:
        raise CurrentSituationError(f"{field} exceeds {_MAX_TEXT_CHARS} characters")
    return normalized


def _identifier(value: object, field: str) -> str:
    identifier = _text(value, field)
    if not _ID_RE.fullmatch(identifier):
        raise CurrentSituationError(f"{field} is not a bounded identifier")
    return identifier


def _digest(value: object, field: str) -> str:
    digest = _text(value, field)
    if not _SHA256_RE.fullmatch(digest):
        raise CurrentSituationError(f"{field} must be a lowercase sha256")
    return digest


def _event_ref(value: object, field: str = "event_ref") -> dict[str, str]:
    event = _mapping(value, field)
    _exact_keys(event, {"event_id", "event_sha256", "relation"}, field)
    relation = _text(event["relation"], f"{field}.relation")
    if relation not in EVENT_RELATIONS:
        raise CurrentSituationError(f"unsupported {field}.relation: {relation}")
    return {
        "event_id": _identifier(event["event_id"], f"{field}.event_id"),
        "event_sha256": _digest(event["event_sha256"], f"{field}.event_sha256"),
        "relation": relation,
    }


def _activity(value: object) -> dict[str, str]:
    activity = _mapping(value, "current.activity")
    _exact_keys(activity, {"description", "mode"}, "current.activity")
    mode = _text(activity["mode"], "current.activity.mode")
    if mode not in ACTIVITY_MODES:
        raise CurrentSituationError(f"unsupported current.activity.mode: {mode}")
    return {
        "description": _text(activity["description"], "current.activity.description"),
        "mode": mode,
    }


def _object(value: object) -> dict[str, str]:
    current_object = _mapping(value, "current.object")
    _exact_keys(current_object, {"description"}, "current.object")
    return {"description": _text(current_object["description"], "current.object.description")}


def _human_relation(value: object) -> dict[str, str]:
    relation = _mapping(value, "current.human_relation")
    _exact_keys(
        relation,
        {"description", "user_need_not_repeat"},
        "current.human_relation",
    )
    return {
        "description": _text(relation["description"], "current.human_relation.description"),
        "user_need_not_repeat": _text(
            relation["user_need_not_repeat"],
            "current.human_relation.user_need_not_repeat",
        ),
    }


def _items(value: object, collection: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise CurrentSituationError(f"current.{collection} must be an array")
    if len(value) > _MAX_CURRENT_ITEMS:
        raise CurrentSituationError(f"current.{collection} exceeds {_MAX_CURRENT_ITEMS} items")
    normalized: list[dict[str, str]] = []
    previous_id = ""
    for index, raw in enumerate(value):
        item = _mapping(raw, f"current.{collection}[{index}]")
        _exact_keys(
            item,
            {"id", "source_event_id", "statement"},
            f"current.{collection}[{index}]",
        )
        item_id = _identifier(item["id"], f"current.{collection}[{index}].id")
        if item_id <= previous_id:
            raise CurrentSituationError(f"current.{collection} must be unique and sorted by id")
        previous_id = item_id
        normalized.append(
            {
                "id": item_id,
                "source_event_id": _identifier(
                    item["source_event_id"],
                    f"current.{collection}[{index}].source_event_id",
                ),
                "statement": _text(item["statement"], f"current.{collection}[{index}].statement"),
            }
        )
    return normalized


def validate_current(value: object) -> dict[str, Any]:
    """Validate the sole hot projection body using a strict allowlist."""

    current = _mapping(value, "current")
    _exact_keys(
        current,
        {"activity", "human_relation", "object", "open_relations", "retracted", "understandings"},
        "current",
    )
    return {
        "activity": _activity(current["activity"]),
        "human_relation": _human_relation(current["human_relation"]),
        "object": _object(current["object"]),
        "open_relations": _items(current["open_relations"], "open_relations"),
        "retracted": _items(current["retracted"], "retracted"),
        "understandings": _items(current["understandings"], "understandings"),
    }


def _projection_identity(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": snapshot["schema_version"],
        "lineage_id": snapshot["lineage_id"],
        "generation": snapshot["generation"],
        "provisional": snapshot["provisional"],
        "last_event_ref": snapshot["last_event_ref"],
        "current": snapshot["current"],
    }


def build_snapshot(
    *,
    lineage_id: str,
    generation: int,
    last_event_ref: Mapping[str, object],
    current: Mapping[str, object],
) -> dict[str, Any]:
    """Build one self-hashed current projection."""

    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise CurrentSituationError("generation must be a non-negative integer")
    snapshot: dict[str, Any] = {
        "schema_version": CURRENT_SITUATION_VERSION,
        "lineage_id": _identifier(lineage_id, "lineage_id"),
        "generation": generation,
        "provisional": True,
        "last_event_ref": _event_ref(last_event_ref, "last_event_ref"),
        "current": validate_current(current),
    }
    snapshot["projection_sha256"] = _sha256(_projection_identity(snapshot))
    return snapshot


def validate_snapshot(value: object) -> dict[str, Any]:
    snapshot = _mapping(value, "current_situation")
    _exact_keys(
        snapshot,
        {
            "current",
            "generation",
            "last_event_ref",
            "lineage_id",
            "projection_sha256",
            "provisional",
            "schema_version",
        },
        "current_situation",
    )
    if snapshot["schema_version"] != CURRENT_SITUATION_VERSION:
        raise CurrentSituationError("unsupported current situation schema_version")
    if snapshot["provisional"] is not True:
        raise CurrentSituationError("model-authored current situation must remain provisional")
    normalized = build_snapshot(
        lineage_id=str(snapshot["lineage_id"]),
        generation=snapshot["generation"],
        last_event_ref=_mapping(snapshot["last_event_ref"], "last_event_ref"),
        current=_mapping(snapshot["current"], "current"),
    )
    supplied_hash = _digest(snapshot["projection_sha256"], "projection_sha256")
    if supplied_hash != normalized["projection_sha256"]:
        raise CurrentSituationError("projection_sha256 mismatch")
    return normalized


def _item_map(current: Mapping[str, object]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for collection in _CURRENT_COLLECTIONS:
        for item in current[collection]:  # type: ignore[index]
            row = dict(item)
            result[f"{collection}:{row['id']}"] = row
    return result


def _field_dispositions(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        raise CurrentSituationError("field_dispositions must be an array")
    result: dict[str, str] = {}
    for index, raw in enumerate(value):
        row = _mapping(raw, f"field_dispositions[{index}]")
        _exact_keys(row, {"disposition", "field"}, f"field_dispositions[{index}]")
        field = _text(row["field"], f"field_dispositions[{index}].field")
        disposition = _text(row["disposition"], f"field_dispositions[{index}].disposition")
        if field not in _CURRENT_FIELDS or field in result:
            raise CurrentSituationError(f"invalid or duplicate field disposition: {field}")
        if disposition not in {"preserve", "replace"}:
            raise CurrentSituationError(f"unsupported field disposition: {disposition}")
        result[field] = disposition
    if set(result) != set(_CURRENT_FIELDS):
        raise CurrentSituationError("every prior current field requires one disposition")
    return result


def _item_dispositions(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, list):
        raise CurrentSituationError("item_dispositions must be an array")
    result: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(value):
        row = _mapping(raw, f"item_dispositions[{index}]")
        expected = {"disposition", "item_ref"}
        if row.get("disposition") == "replace":
            expected.add("replacement_ref")
        _exact_keys(row, expected, f"item_dispositions[{index}]")
        item_ref = _text(row["item_ref"], f"item_dispositions[{index}].item_ref")
        disposition = _text(row["disposition"], f"item_dispositions[{index}].disposition")
        if item_ref in result or disposition not in {"preserve", "replace", "retract"}:
            raise CurrentSituationError(f"invalid or duplicate item disposition: {item_ref}")
        normalized = {"item_ref": item_ref, "disposition": disposition}
        if disposition == "replace":
            normalized["replacement_ref"] = _text(
                row["replacement_ref"], f"item_dispositions[{index}].replacement_ref"
            )
        result[item_ref] = normalized
    return result


def validate_transition(value: object, *, current_snapshot: Mapping[str, object]) -> dict[str, Any]:
    """Validate one event interpretation against the exact current preimage."""

    current_snapshot = validate_snapshot(current_snapshot)
    transition = _mapping(value, "transition")
    expected_keys = {
        "event_ref",
        "expected_generation",
        "expected_projection_sha256",
        "field_dispositions",
        "item_dispositions",
        "materiality",
        "schema_version",
    }
    materiality = transition.get("materiality")
    if materiality == "MATERIAL_REVISION":
        expected_keys.add("next_current")
    _exact_keys(transition, expected_keys, "transition")
    if transition["schema_version"] != TRANSITION_VERSION:
        raise CurrentSituationError("unsupported transition schema_version")
    if materiality not in MATERIALITIES:
        raise CurrentSituationError(f"unsupported transition materiality: {materiality}")
    if transition["expected_generation"] != current_snapshot["generation"]:
        raise CurrentSituationConflict("transition expected_generation is stale")
    expected_hash = _digest(transition["expected_projection_sha256"], "expected_projection_sha256")
    if expected_hash != current_snapshot["projection_sha256"]:
        raise CurrentSituationConflict("transition expected_projection_sha256 is stale")
    event_ref = _event_ref(transition["event_ref"])

    if materiality == "NO_MATERIAL_CHANGE":
        if transition["field_dispositions"] or transition["item_dispositions"]:
            raise CurrentSituationError("NO_MATERIAL_CHANGE cannot carry dispositions")
        return {
            "schema_version": TRANSITION_VERSION,
            "materiality": materiality,
            "expected_generation": current_snapshot["generation"],
            "expected_projection_sha256": expected_hash,
            "event_ref": event_ref,
            "field_dispositions": [],
            "item_dispositions": [],
        }

    next_current = validate_current(transition["next_current"])
    field_dispositions = _field_dispositions(transition["field_dispositions"])
    old_current = current_snapshot["current"]
    changed = False
    for field, disposition in field_dispositions.items():
        equal = old_current[field] == next_current[field]
        if disposition == "preserve" and not equal:
            raise CurrentSituationError(f"preserved field changed: {field}")
        if disposition == "replace" and equal:
            raise CurrentSituationError(f"replaced field did not change: {field}")
        changed = changed or not equal

    old_items = _item_map(old_current)
    next_items = _item_map(next_current)
    item_dispositions = _item_dispositions(transition["item_dispositions"])
    if set(item_dispositions) != set(old_items):
        missing = sorted(set(old_items) - set(item_dispositions))
        extra = sorted(set(item_dispositions) - set(old_items))
        raise CurrentSituationError(
            f"every prior current item requires one disposition: missing={missing}, extra={extra}"
        )
    for item_ref, disposition in item_dispositions.items():
        mode = disposition["disposition"]
        if mode == "preserve":
            if next_items.get(item_ref) != old_items[item_ref]:
                raise CurrentSituationError(f"preserved item changed or disappeared: {item_ref}")
            continue
        changed = True
        if item_ref in next_items:
            raise CurrentSituationError(f"retracted/replaced item remains current: {item_ref}")
        if mode == "replace":
            replacement_ref = disposition["replacement_ref"]
            if replacement_ref == item_ref or replacement_ref not in next_items:
                raise CurrentSituationError(f"invalid replacement_ref for {item_ref}")

    for item_ref, item in next_items.items():
        if item_ref not in old_items and item["source_event_id"] != event_ref["event_id"]:
            raise CurrentSituationError(
                f"new current item is not sourced to this event: {item_ref}"
            )
    if not changed and old_current == next_current:
        raise CurrentSituationError("MATERIAL_REVISION did not change the current projection")

    return {
        "schema_version": TRANSITION_VERSION,
        "materiality": materiality,
        "expected_generation": current_snapshot["generation"],
        "expected_projection_sha256": expected_hash,
        "event_ref": event_ref,
        "field_dispositions": [
            {"field": field, "disposition": field_dispositions[field]}
            for field in sorted(field_dispositions)
        ],
        "item_dispositions": [item_dispositions[key] for key in sorted(item_dispositions)],
        "next_current": next_current,
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def initialize_store(store_root: Path, snapshot: Mapping[str, object]) -> Path:
    """Create the first current projection for one explicitly selected store."""

    root = Path(store_root)
    current_path = root / "current.json"
    normalized = validate_snapshot(snapshot)
    root.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(root / ".current.lock"):
        if current_path.exists():
            raise CurrentSituationConflict(f"current projection already exists: {current_path}")
        _atomic_write(current_path, artifact_json_bytes(normalized))
        retired_path = root / "retired.json"
        if retired_path.exists():
            retired_path.unlink()
    return current_path


def load_current(store_root: Path) -> dict[str, Any]:
    root = Path(store_root)
    if (root / "retired.json").exists():
        raise CurrentSituationError(f"current projection is retired: {root}")
    path = root / "current.json"
    try:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise CurrentSituationError(f"current projection cannot be a link: {path}")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SNAPSHOT_BYTES:
            raise CurrentSituationError(f"current projection is not a bounded regular file: {path}")
        payload = path.read_bytes()
        after = path.lstat()
        stable_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if not stable_identity or len(payload) > MAX_SNAPSHOT_BYTES:
            raise CurrentSituationError(f"current projection changed during capture: {path}")
        raw = json.loads(payload.decode("utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentSituationError(f"cannot load current projection: {path}") from exc
    return validate_snapshot(raw)


def retire_store(store_root: Path, *, reason: str) -> dict[str, Any]:
    """Tombstone one explicit checkpoint without deleting its recovery preimage."""

    root = Path(store_root)
    normalized_reason = _text(reason, "retirement.reason")
    root.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(root / ".current.lock"):
        before = load_current(root)
        retired_at_ns = time.time_ns()
        receipt = {
            "schema_version": "codex.current_situation_retirement_receipt.v1",
            "retired_at_unix_ns": retired_at_ns,
            "reason": normalized_reason,
            "before_projection": before,
            "authority": False,
            "completion_claim_allowed": False,
        }
        receipt["receipt_sha256"] = _sha256(receipt)
        receipt_path = (
            root / "cold_retirements" / f"{before['generation']:08d}-{retired_at_ns}.json"
        )
        _atomic_write(receipt_path, artifact_json_bytes(receipt))
        _atomic_write(
            root / "retired.json",
            artifact_json_bytes(
                {
                    "schema_version": "codex.current_situation_tombstone.v1",
                    "retired_at_unix_ns": retired_at_ns,
                    "receipt_sha256": receipt["receipt_sha256"],
                    "authority": False,
                }
            ),
        )
        (root / "current.json").unlink()
        return {
            "status": "retired",
            "persisted": True,
            "generation": before["generation"],
            "projection_sha256": before["projection_sha256"],
            "cold_retirement_receipt": str(receipt_path),
        }


def apply_transition(store_root: Path, transition: Mapping[str, object]) -> dict[str, Any]:
    """Apply one CAS revision; cold evidence is never read by the hot renderer."""

    root = Path(store_root)
    current_path = root / "current.json"
    root.mkdir(parents=True, exist_ok=True)
    # A semantic no-op is genuinely persistence-free.  Read and validate it
    # before opening the exclusive writer lock, whose lock carrier is itself a
    # filesystem effect on some Windows filesystems.
    observed = load_current(root)
    observed_transition = validate_transition(transition, current_snapshot=observed)
    if observed_transition["materiality"] == "NO_MATERIAL_CHANGE":
        return {
            "materiality": "NO_MATERIAL_CHANGE",
            "persisted": False,
            "projection_sha256": observed["projection_sha256"],
            "generation": observed["generation"],
        }

    with _exclusive_lock(root / ".current.lock"):
        current = load_current(root)
        normalized_transition = validate_transition(transition, current_snapshot=current)
        next_snapshot = build_snapshot(
            lineage_id=current["lineage_id"],
            generation=current["generation"] + 1,
            last_event_ref=normalized_transition["event_ref"],
            current=normalized_transition["next_current"],
        )
        receipt = {
            "schema_version": REVISION_RECEIPT_VERSION,
            "application_rule": "applied_iff_current_projection_sha256_equals_after_projection_sha256",
            "before_projection": current,
            "after_projection": next_snapshot,
            "transition": normalized_transition,
        }
        receipt["receipt_sha256"] = _sha256(receipt)
        event_id = normalized_transition["event_ref"]["event_id"]
        receipt_path = (
            root / "cold_revisions" / f"{next_snapshot['generation']:08d}-{event_id}.json"
        )
        _atomic_write(receipt_path, artifact_json_bytes(receipt))
        _atomic_write(current_path, artifact_json_bytes(next_snapshot))
        return {
            "materiality": "MATERIAL_REVISION",
            "persisted": True,
            "projection_sha256": next_snapshot["projection_sha256"],
            "generation": next_snapshot["generation"],
            "cold_revision_receipt": str(receipt_path),
        }


def render_hot_context(snapshot: Mapping[str, object]) -> str:
    """Render only the current projection; no history, task state, or cold locator."""

    normalized = validate_snapshot(snapshot)
    payload = {
        "schema_version": normalized["schema_version"],
        "lineage_id": normalized["lineage_id"],
        "generation": normalized["generation"],
        "provisional": normalized["provisional"],
        "projection_sha256": normalized["projection_sha256"],
        "last_event_ref": normalized["last_event_ref"],
        "current": normalized["current"],
    }
    return artifact_json_bytes(payload).decode("utf-8")
