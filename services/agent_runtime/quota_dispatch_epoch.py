"""Immutable quota telemetry snapshots scoped to one dispatch epoch.

Quota remains routing telemetry, never an authority or a dispatch gate.  The
first caller in an epoch performs the live query; ordinary refills consume the
same hash-bound snapshot until the epoch changes or an explicit invalidation is
recorded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = "xinao.quota_dispatch_epoch_snapshot.v1"
POINTER_SCHEMA = "xinao.quota_dispatch_epoch_pointer.v1"
USAGE_SCHEMA = "xinao.quota_dispatch_epoch_usage.v1"


class QuotaDispatchEpochError(ValueError):
    """Raised when cached quota telemetry fails its integrity contract."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise QuotaDispatchEpochError(f"{label} must be non-empty")
    return text


def _sha(value: object, label: str) -> str:
    text = _text(value, label).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise QuotaDispatchEpochError(f"{label} must be sha256")
    return text


def _epoch_dir(runtime_root: Path, epoch_id: str) -> Path:
    identifier = _text(epoch_id, "epoch_id")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", identifier).strip("-.")[:48] or "epoch"
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:12]
    return (
        Path(runtime_root).resolve(strict=False)
        / "state"
        / "quota_dispatch_epochs"
        / f"{slug}-{digest}"
    )


def _atomic_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return _sha_bytes(raw)


class _EpochLock:
    def __init__(self, directory: Path, timeout_sec: float = 15.0) -> None:
        self.path = directory / ".refresh.lock"
        self.timeout_sec = timeout_sec
        self.acquired = False

    def __enter__(self) -> "_EpochLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_sec
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(f"pid={os.getpid()} acquired_at={_now()}\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    if age > 120:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise QuotaDispatchEpochError(f"quota epoch refresh lock timeout: {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise QuotaDispatchEpochError(f"{label} missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuotaDispatchEpochError(f"{label} invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QuotaDispatchEpochError(f"{label} must be an object")
    return value


def validate_dispatch_epoch_pointer(
    pointer_path: Path,
    *,
    expected_epoch_id: str | None = None,
    expected_source_identity: str | None = None,
) -> dict[str, Any]:
    """Validate the current pointer and immutable snapshot bytes."""

    pointer_file = Path(pointer_path).resolve(strict=False)
    pointer = _read_object(pointer_file, "quota epoch pointer")
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise QuotaDispatchEpochError("quota epoch pointer schema mismatch")
    epoch_id = _text(pointer.get("epoch_id"), "pointer.epoch_id")
    if expected_epoch_id is not None and epoch_id != expected_epoch_id:
        raise QuotaDispatchEpochError("quota epoch id mismatch")
    snapshot_path = Path(_text(pointer.get("snapshot_ref"), "pointer.snapshot_ref")).resolve(
        strict=False
    )
    expected_sha = _sha(pointer.get("snapshot_sha256"), "pointer.snapshot_sha256")
    if not snapshot_path.is_file():
        raise QuotaDispatchEpochError(f"quota snapshot missing: {snapshot_path}")
    observed_sha = _sha_file(snapshot_path)
    if observed_sha != expected_sha:
        raise QuotaDispatchEpochError(
            f"quota snapshot hash mismatch: expected={expected_sha}; observed={observed_sha}"
        )
    if snapshot_path.parent != pointer_file.parent / "snapshots":
        raise QuotaDispatchEpochError("quota snapshot is outside exact epoch directory")
    snapshot = _read_object(snapshot_path, "quota epoch snapshot")
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA:
        raise QuotaDispatchEpochError("quota snapshot schema mismatch")
    if snapshot.get("epoch_id") != epoch_id:
        raise QuotaDispatchEpochError("quota snapshot epoch mismatch")
    if snapshot.get("snapshot_id") != pointer.get("snapshot_id"):
        raise QuotaDispatchEpochError("quota snapshot id mismatch")
    if (
        expected_source_identity is not None
        and snapshot.get("source_identity") != expected_source_identity
    ):
        raise QuotaDispatchEpochError("quota snapshot source identity changed")
    body = dict(snapshot)
    snapshot_id = _sha(body.pop("snapshot_id", None), "snapshot.snapshot_id")
    if _sha_bytes(_canonical_bytes(body)) != snapshot_id:
        raise QuotaDispatchEpochError("quota snapshot content identity mismatch")
    return {
        **snapshot,
        "snapshot_ref": str(snapshot_path),
        "snapshot_sha256": expected_sha,
        "pointer_path": str(pointer_file),
    }


def _current_generation(pointer_path: Path) -> int:
    try:
        value = validate_dispatch_epoch_pointer(pointer_path)
        generation = value.get("generation")
        return int(generation) if isinstance(generation, int) and generation >= 1 else 0
    except (OSError, QuotaDispatchEpochError):
        return 0


def get_or_refresh_dispatch_epoch(
    *,
    runtime_root: Path,
    epoch_id: str,
    source_identity: str,
    collector: Callable[[], Mapping[str, object]],
    invalidate_reason: str | None = None,
) -> dict[str, object]:
    """Return the one snapshot for an epoch, refreshing only at explicit gates."""

    identifier = _text(epoch_id, "epoch_id")
    source = _text(source_identity, "source_identity")
    directory = _epoch_dir(runtime_root, identifier)
    pointer_path = directory / "current.json"
    with _EpochLock(directory):
        reason = str(invalidate_reason or "").strip()
        if not reason:
            try:
                cached = validate_dispatch_epoch_pointer(
                    pointer_path,
                    expected_epoch_id=identifier,
                    expected_source_identity=source,
                )
                return {
                    "schema_version": "xinao.quota_dispatch_epoch_resolution.v1",
                    "status": "cache_hit",
                    "snapshot": cached,
                    "pointer_path": str(pointer_path),
                    "dispatch_blocked": False,
                }
            except QuotaDispatchEpochError:
                pass

        generation = _current_generation(pointer_path) + 1
        queried_at = _now()
        collector_error: str | None = None
        try:
            report_value = collector()
            if not isinstance(report_value, Mapping):
                raise TypeError("collector result must be an object")
            report: dict[str, object] | None = dict(report_value)
            freshness = "fresh"
        except Exception as exc:  # telemetry must not become a dispatch gate
            report = None
            freshness = "unknown"
            collector_error = f"{type(exc).__name__}: {exc}"[:1000]
        body: dict[str, object] = {
            "schema_version": SNAPSHOT_SCHEMA,
            "epoch_id": identifier,
            "generation": generation,
            "queried_at": queried_at,
            "freshness": freshness,
            "source_identity": source,
            "live_report": report,
            "live_report_sha256": (
                _sha_bytes(_canonical_bytes(report)) if report is not None else None
            ),
            "collector_error": collector_error,
            "invalidation_reason": reason
            or ("source_or_cache_changed" if pointer_path.exists() else "epoch_started"),
            "advisory_only": True,
            "dispatch_blocked": False,
            "authority": False,
            "completion_claim_allowed": False,
        }
        snapshot_id = _sha_bytes(_canonical_bytes(body))
        snapshot = {**body, "snapshot_id": snapshot_id}
        snapshot_path = directory / "snapshots" / f"{generation:04d}-{snapshot_id}.json"
        snapshot_sha = _atomic_json(snapshot_path, snapshot)
        pointer = {
            "schema_version": POINTER_SCHEMA,
            "epoch_id": identifier,
            "generation": generation,
            "snapshot_id": snapshot_id,
            "snapshot_ref": str(snapshot_path.resolve(strict=True)),
            "snapshot_sha256": snapshot_sha,
        }
        _atomic_json(pointer_path, pointer)
        validated = validate_dispatch_epoch_pointer(
            pointer_path,
            expected_epoch_id=identifier,
            expected_source_identity=source,
        )
        return {
            "schema_version": "xinao.quota_dispatch_epoch_resolution.v1",
            "status": "refreshed" if report is not None else "refreshed_unknown",
            "snapshot": validated,
            "pointer_path": str(pointer_path),
            "dispatch_blocked": False,
        }


def record_dispatch_epoch_usage(
    *,
    runtime_root: Path,
    epoch_id: str,
    work_key: str,
    provider_id: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, object]:
    """Append one local usage fact and deterministically project epoch totals."""

    if isinstance(input_tokens, bool) or input_tokens < 0:
        raise QuotaDispatchEpochError("input_tokens must be >= 0")
    if isinstance(output_tokens, bool) or output_tokens < 0:
        raise QuotaDispatchEpochError("output_tokens must be >= 0")
    identifier = _text(epoch_id, "epoch_id")
    directory = _epoch_dir(runtime_root, identifier)
    with _EpochLock(directory):
        validate_dispatch_epoch_pointer(directory / "current.json", expected_epoch_id=identifier)
        event: dict[str, object] = {
            "schema_version": USAGE_SCHEMA,
            "event_id": str(uuid.uuid4()),
            "timestamp": _now(),
            "epoch_id": identifier,
            "work_key": _text(work_key, "work_key"),
            "provider_id": _text(provider_id, "provider_id"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "authority": False,
            "completion_claim_allowed": False,
        }
        event["event_sha256"] = _sha_bytes(_canonical_bytes(event))
        events_path = directory / "usage.events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical_bytes(event) + b"\n"
        with events_path.open("ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        totals = {
            "attempt_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        for line_number, line in enumerate(
            events_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                observed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise QuotaDispatchEpochError(
                    f"invalid usage event line {line_number}: {exc}"
                ) from exc
            if (
                observed.get("schema_version") != USAGE_SCHEMA
                or observed.get("epoch_id") != identifier
            ):
                raise QuotaDispatchEpochError("usage event identity mismatch")
            observed_sha = _sha(observed.get("event_sha256"), "usage.event_sha256")
            observed_body = dict(observed)
            observed_body.pop("event_sha256", None)
            if _sha_bytes(_canonical_bytes(observed_body)) != observed_sha:
                raise QuotaDispatchEpochError("usage event hash mismatch")
            totals["attempt_count"] += 1
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                totals[field] += int(observed[field])
        projection = {
            "schema_version": "xinao.quota_dispatch_epoch_usage_projection.v1",
            "epoch_id": identifier,
            "events_ref": str(events_path.resolve(strict=True)),
            "events_sha256": _sha_file(events_path),
            "totals": totals,
            "authority": False,
            "completion_claim_allowed": False,
        }
        projection_path = directory / "usage.current.json"
        projection_sha = _atomic_json(projection_path, projection)
        return {
            **projection,
            "projection_ref": str(projection_path.resolve(strict=True)),
            "projection_sha256": projection_sha,
        }
