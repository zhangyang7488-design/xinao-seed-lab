"""Read-only task-run recovery plus a one-shot pre-action receipt consumer.

Task-run events remain the sole durable execution truth.  Checkpoints, replay
reports, receipts, and one-shot consumption records are non-authoritative
projections and guards; they never grant permission or parent completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import artifact_json_bytes, canonical_json_bytes

CHECKPOINT_VERSION = "xinao.codex_session_checkpoint.v2"
CHECKPOINT_SENTINEL = "SENTINEL:XINAO_CODEX_SESSION_CHECKPOINT_V2"
REUSE_INDEX_VERSION = "xinao.codex_task_run.fan_in_reuse_index.v1"
TASK_RUN_VERSION = "codex.verified-task-run.v1"
RECEIPT_VERSION = "xinao.action_resume_receipt.v1"
VERIFICATION_VERSION = "xinao.action_resume_verification.v1"
CONSUMPTION_VERSION = "xinao.action_resume_consumption.v1"
DEFAULT_TTL_SECONDS = 3600
MAX_TTL_SECONDS = 86400
MAX_DELTA_EVENTS = 128
MAX_DELTA_BYTES = 131072
_EVENT_REF_RE = re.compile(r"^(?P<path>.+[\\/]events\.jsonl)#event(?P<count>[1-9][0-9]*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTION_KINDS = frozenset({"reconcile", "dispatch", "apply"})
_FROZEN_STATUSES = frozenset({"paused", "stopped", "cancelled"})


class ActionResumeError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ActionResumeError("INPUT_INVALID", f"{field} must be an object")
    return dict(value)


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ActionResumeError("INPUT_INVALID", f"{field} must be a string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ActionResumeError("INPUT_INVALID", f"{field} must be an integer >= {minimum}")
    return value


def _sha256(value: object, field: str) -> str:
    text = _text(value, field)
    if not _SHA256_RE.fullmatch(text):
        raise ActionResumeError("INPUT_INVALID", f"{field} must be a lowercase sha256")
    return text


def _read_json(path: Path, field: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        value = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActionResumeError("UTF8_OR_JSON_INVALID", f"cannot read {field}: {path}") from exc
    if "\ufffd" in text:
        raise ActionResumeError("UTF8_REPLACEMENT_CHARACTER", f"{field} contains U+FFFD")
    return _mapping(value, field), raw


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _parse_time(value: object, field: str) -> datetime:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ActionResumeError("INPUT_INVALID", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _event_ref(checkpoint: Mapping[str, object]) -> tuple[Path, int]:
    refs = checkpoint.get("evidence_refs")
    if not isinstance(refs, list):
        raise ActionResumeError(
            "CHECKPOINT_CURSOR_INVALID", "checkpoint.evidence_refs must be an array"
        )
    matches: list[tuple[Path, int]] = []
    for raw in refs:
        match = _EVENT_REF_RE.fullmatch(str(raw or "").strip())
        if match:
            matches.append((Path(match.group("path")), int(match.group("count"))))
    if len(matches) != 1:
        raise ActionResumeError(
            "CHECKPOINT_CURSOR_INVALID", "checkpoint must bind exactly one events.jsonl#eventN"
        )
    return matches[0]


def _validate_checkpoint(checkpoint: Mapping[str, object]) -> None:
    if checkpoint.get("schema_version") != CHECKPOINT_VERSION:
        raise ActionResumeError("CHECKPOINT_SCHEMA_DRIFT", "unsupported checkpoint schema")
    if checkpoint.get("sentinel") != CHECKPOINT_SENTINEL:
        raise ActionResumeError("CHECKPOINT_SCHEMA_DRIFT", "checkpoint sentinel drifted")
    if checkpoint.get("not_authority") is not True:
        raise ActionResumeError(
            "CHECKPOINT_AUTHORITY_INVALID", "checkpoint must remain non-authoritative"
        )
    _text(checkpoint.get("user_intent_cn"), "checkpoint.user_intent_cn")
    _text(checkpoint.get("resume_brief_cn"), "checkpoint.resume_brief_cn")


def _parse_events(raw: bytes, run_id: str) -> list[dict[str, Any]]:
    if raw and not raw.endswith(b"\n"):
        raise ActionResumeError("EVENT_TAIL_INCOMPLETE", "events.jsonl has an incomplete tail")
    events: list[dict[str, Any]] = []
    for ordinal, line in enumerate(raw.splitlines(), start=1):
        try:
            event = _mapping(json.loads(line.decode("utf-8")), f"event[{ordinal}]")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActionResumeError(
                "EVENT_JSON_INVALID", f"event line {ordinal} is invalid"
            ) from exc
        if event.get("schema_version") != TASK_RUN_VERSION or event.get("run_id") != run_id:
            raise ActionResumeError(
                "TASK_RUN_IDENTITY_DRIFT", f"event line {ordinal} identity drifted"
            )
        event["ordinal"] = ordinal
        events.append(event)
    return events


def _normalized_event(event: Mapping[str, object]) -> dict[str, object]:
    return {
        "ordinal": event["ordinal"],
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "kind": event.get("kind"),
        "phase": event.get("phase"),
        "target": event.get("target"),
        "side_effect_id": event.get("side_effect_id"),
        "exit_code": event.get("exit_code"),
        "retry_class": event.get("retry_class"),
        "summary": event.get("summary"),
        "evidence_refs": list(event.get("evidence_refs") or []),
    }


def _load_chain(run_dir: Path, checkpoint: Mapping[str, object], cursor: int) -> dict[str, Any]:
    task, task_raw = _read_json(run_dir / "task.json", "task")
    state, state_raw = _read_json(run_dir / "state.json", "state")
    run_id = _text(task.get("run_id"), "task.run_id")
    if (
        task.get("schema_version") != TASK_RUN_VERSION
        or state.get("schema_version") != TASK_RUN_VERSION
        or state.get("run_id") != run_id
        or run_dir.name != run_id
    ):
        raise ActionResumeError("TASK_RUN_IDENTITY_DRIFT", "task-run identity disagrees")
    events_path = run_dir / "events.jsonl"
    checkpoint_path, _ = _event_ref(checkpoint)
    if _path_key(checkpoint_path) != _path_key(events_path):
        raise ActionResumeError(
            "CHECKPOINT_CURSOR_INVALID", "checkpoint points at another task-run"
        )
    try:
        events_raw = events_path.read_bytes()
    except OSError as exc:
        raise ActionResumeError("TASK_RUN_MISSING", f"cannot read events: {events_path}") from exc

    reuse_report: dict[str, object] | None = None
    binding_raw = checkpoint.get("reuse_index")
    if binding_raw is not None:
        binding = _mapping(binding_raw, "checkpoint.reuse_index")
        reuse_path = Path(_text(binding.get("path"), "reuse_index.path"))
        expected_reuse_sha = _sha256(binding.get("sha256"), "reuse_index.sha256")
        reuse, reuse_raw = _read_json(reuse_path, "reuse_index")
        if _sha256_bytes(reuse_raw) != expected_reuse_sha:
            raise ActionResumeError("REUSE_INDEX_HASH_DRIFT", "reuse index hash disagrees")
        if (
            reuse.get("schema_version") != REUSE_INDEX_VERSION
            or reuse.get("authority") is not False
            or reuse.get("completion_claim_allowed") is not False
            or reuse.get("parent_run") != run_id
        ):
            raise ActionResumeError("REUSE_INDEX_INVALID", "reuse index contract drifted")
        cut = _mapping(
            _mapping(reuse.get("source_cut"), "source_cut").get("events_jsonl"),
            "source_cut.events_jsonl",
        )
        cut_count = _integer(cut.get("event_count"), "source_cut.event_count")
        byte_length = _integer(cut.get("byte_length"), "source_cut.byte_length")
        prefix_sha = _sha256(cut.get("sha256"), "source_cut.sha256")
        if _path_key(Path(_text(cut.get("path"), "source_cut.path"))) != _path_key(events_path):
            raise ActionResumeError(
                "REUSE_INDEX_INVALID", "reuse index points at another event chain"
            )
        prefix = events_raw[:byte_length]
        if (
            len(prefix) != byte_length
            or prefix.count(b"\n") != cut_count
            or _sha256_bytes(prefix) != prefix_sha
        ):
            raise ActionResumeError("REUSE_EVENT_PREFIX_DRIFT", "immutable event prefix drifted")
        if _integer(binding.get("source_cut_event_count"), "source_cut_event_count") != cut_count:
            raise ActionResumeError(
                "REUSE_INDEX_INVALID", "checkpoint and reuse source cut disagree"
            )
        if (
            _integer(binding.get("tail_replay_from_event"), "tail_replay_from_event", minimum=1)
            != cut_count + 1
        ):
            raise ActionResumeError("REUSE_INDEX_INVALID", "tail replay does not follow source cut")
        reuse_report = {
            "path": str(reuse_path.resolve()),
            "sha256": expected_reuse_sha,
            "source_cut_event_count": cut_count,
            "tail_replay_from_event": cut_count + 1,
        }

    events = _parse_events(events_raw, run_id)
    if state.get("events_count") != len(events):
        raise ActionResumeError("EVENT_HEAD_DRIFT", "state.events_count disagrees with events")
    if cursor > len(events):
        raise ActionResumeError("CHECKPOINT_AHEAD_OF_EVENT_HEAD", "checkpoint cursor is ahead")
    if not events:
        raise ActionResumeError("TASK_RUN_EMPTY", "task-run has no events")
    head = events[-1]
    if state.get("current_phase") != head.get("phase"):
        raise ActionResumeError("EVENT_HEAD_DRIFT", "state.current_phase disagrees with event head")
    event_ids = [str(row.get("event_id") or "") for row in events]
    if not all(event_ids) or len(set(event_ids)) != len(event_ids):
        raise ActionResumeError("EVENT_ID_INVALID", "event IDs are missing or duplicated")
    delta = [_normalized_event(row) for row in events if int(row["ordinal"]) > cursor]
    delta_raw = canonical_json_bytes(delta)
    if len(delta) > MAX_DELTA_EVENTS or len(delta_raw) > MAX_DELTA_BYTES:
        raise ActionResumeError(
            "CHECKPOINT_DELTA_TOO_LARGE", "refresh the existing checkpoint first"
        )
    return {
        "run_id": run_id,
        "task": task,
        "state": state,
        "events": events,
        "head": head,
        "event_count": len(events),
        "events_sha256": _sha256_bytes(events_raw),
        "task_sha256": _sha256_bytes(task_raw),
        "state_sha256": _sha256_bytes(state_raw),
        "delta": delta,
        "delta_sha256": _sha256_bytes(delta_raw),
        "reuse_index": reuse_report,
        "side_effect_ids": {
            str(row.get("side_effect_id"))
            for row in events
            if str(row.get("side_effect_id") or "").strip()
        },
    }


def _world_facts(
    files: Sequence[Path], absent: Sequence[Path], work_pin: str
) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in files:
        path = Path(raw).resolve()
        key = _path_key(path)
        if key in seen or not path.is_file():
            raise ActionResumeError(
                "WORLD_FACT_INVALID", f"observed file is missing or duplicated: {path}"
            )
        seen.add(key)
        facts.append(
            {
                "path": str(path),
                "expectation": "file_sha256",
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    for raw in absent:
        path = Path(raw).resolve()
        key = _path_key(path)
        if key in seen or path.exists():
            raise ActionResumeError(
                "WORLD_FACT_INVALID", f"expected-absent fact is present or duplicated: {path}"
            )
        seen.add(key)
        facts.append({"path": str(path), "expectation": "absent"})
    if work_pin:
        facts.append({"expectation": "work_pin", "value": work_pin})
    return sorted(
        facts,
        key=lambda row: (str(row.get("expectation")), os.path.normcase(str(row.get("path") or ""))),
    )


def _mutation_frozen(chain: Mapping[str, object]) -> bool:
    state = _mapping(chain.get("state"), "state")
    if str(state.get("status") or "").lower() in _FROZEN_STATUSES:
        return True
    events = chain.get("events") or []
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, Mapping):
                continue
            phase = str(event.get("phase") or "").lower()
            kind = str(event.get("kind") or "").lower()
            if kind in {"stop", "pause"} or phase.endswith("_paused") or phase.endswith("_stopped"):
                return True
            if kind in {"action", "result"}:
                break
    return False


def issue_action_resume_receipt(
    *,
    checkpoint_path: Path,
    task_run_dir: Path | None = None,
    action_kind: str = "reconcile",
    work_key: str = "",
    next_action: str = "",
    side_effect_id: str = "",
    observed_files: Sequence[Path] = (),
    expected_absent_paths: Sequence[Path] = (),
    work_pin: str = "",
    expected_world_sha256: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    if action_kind not in _ACTION_KINDS:
        raise ActionResumeError("ACTION_KIND_INVALID", f"unsupported action kind: {action_kind}")
    if not 60 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ActionResumeError("TTL_INVALID", "receipt TTL is outside the bounded range")
    if action_kind == "reconcile":
        if any(str(value).strip() for value in (work_key, next_action, side_effect_id)):
            raise ActionResumeError("ACTION_IDENTITY_INVALID", "reconcile cannot bind an effect")
    else:
        work_key = _text(work_key, "work_key").strip()
        next_action = _text(next_action, "next_action").strip()
        side_effect_id = _text(side_effect_id, "side_effect_id").strip()

    checkpoint_path = Path(checkpoint_path).resolve()
    checkpoint, checkpoint_raw = _read_json(checkpoint_path, "checkpoint")
    _validate_checkpoint(checkpoint)
    events_path, cursor = _event_ref(checkpoint)
    inferred_run = events_path.resolve().parent
    run_dir = Path(task_run_dir).resolve() if task_run_dir else inferred_run
    if _path_key(run_dir) != _path_key(inferred_run):
        raise ActionResumeError(
            "CHECKPOINT_CURSOR_INVALID", "explicit run disagrees with checkpoint"
        )
    chain = _load_chain(run_dir, checkpoint, cursor)
    if action_kind != "reconcile" and _mutation_frozen(chain):
        raise ActionResumeError("RUN_MUTATION_FROZEN", "run is paused or stopped")
    if side_effect_id and side_effect_id in chain["side_effect_ids"]:
        raise ActionResumeError("DUPLICATE_SIDE_EFFECT_BLOCKED", "side_effect_id already exists")
    facts = _world_facts(observed_files, expected_absent_paths, work_pin)
    if action_kind == "apply" and not facts:
        raise ActionResumeError("WORLD_FACT_REQUIRED", "apply must bind a live fact")
    world_sha = _sha256_bytes(canonical_json_bytes(facts))
    if expected_world_sha256 and expected_world_sha256 != world_sha:
        raise ActionResumeError(
            "CHECKPOINT_WORLD_DIVERGED", "current world differs from expected pin"
        )
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stale = cursor < int(chain["event_count"])
    head = _mapping(chain["head"], "event_head")
    body: dict[str, Any] = {
        "schema_version": RECEIPT_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "durable_state_owner": "existing_task_run_events",
        "issued_at": _iso(issued),
        "expires_at": _iso(issued + timedelta(seconds=ttl_seconds)),
        "freshness": {
            "checkpoint_was_stale": stale,
            "reason_code": "CHECKPOINT_STALE_EVENT_TAIL" if stale else "CHECKPOINT_FRESH",
            "reconciled": True,
        },
        "action": {
            "kind": action_kind,
            "work_key": work_key or None,
            "next_action": next_action or None,
            "side_effect_id": side_effect_id or None,
        },
        "task_run": {
            "path": str(run_dir),
            "run_id": chain["run_id"],
            "task_sha256": chain["task_sha256"],
            "state_sha256": chain["state_sha256"],
            "events_sha256": chain["events_sha256"],
        },
        "checkpoint": {
            "path": str(checkpoint_path),
            "sha256": _sha256_bytes(checkpoint_raw),
            "cursor": cursor,
        },
        "reuse_index": chain["reuse_index"],
        "event_head": {
            "event_count": chain["event_count"],
            "event_id": head.get("event_id"),
            "phase": head.get("phase"),
            "target": head.get("target"),
        },
        "event_delta": chain["delta"],
        "event_delta_sha256": chain["delta_sha256"],
        "observed_facts": facts,
        "world_sha256": world_sha,
        "false_green_deny": "Fresh pre-action boundary only; no authority, effect, ledger move, verification, or parent completion is proven.",
    }
    body["receipt_sha256"] = _sha256_bytes(canonical_json_bytes(body))
    return body


def write_action_resume_receipt(path: Path, receipt: Mapping[str, object]) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = artifact_json_bytes(receipt)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256_bytes(raw)


def verify_action_resume_receipt(
    receipt: Mapping[str, object],
    *,
    expected_action_kind: str,
    expected_work_key: str,
    expected_side_effect_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    data = _mapping(receipt, "receipt")
    if data.get("schema_version") != RECEIPT_VERSION:
        raise ActionResumeError("ACTION_RECEIPT_SCHEMA_INVALID", "unsupported receipt")
    if data.get("authority") is not False or data.get("completion_claim_allowed") is not False:
        raise ActionResumeError("ACTION_RECEIPT_AUTHORITY_INVALID", "receipt gained authority")
    seal = _sha256(data.get("receipt_sha256"), "receipt_sha256")
    unsealed = dict(data)
    unsealed.pop("receipt_sha256", None)
    if _sha256_bytes(canonical_json_bytes(unsealed)) != seal:
        raise ActionResumeError("ACTION_RECEIPT_SEAL_MISMATCH", "receipt seal mismatch")
    if (now or datetime.now(timezone.utc)).astimezone(timezone.utc) > _parse_time(
        data.get("expires_at"), "expires_at"
    ):
        raise ActionResumeError("ACTION_RECEIPT_EXPIRED", "receipt expired")
    action = _mapping(data.get("action"), "action")
    if action.get("kind") != expected_action_kind:
        raise ActionResumeError("ACTION_IDENTITY_MISMATCH", "action kind mismatch")
    if action.get("work_key") != expected_work_key:
        raise ActionResumeError("ACTION_IDENTITY_MISMATCH", "work_key mismatch")
    if action.get("side_effect_id") != expected_side_effect_id:
        raise ActionResumeError("ACTION_IDENTITY_MISMATCH", "side_effect_id mismatch")
    if expected_action_kind not in {"dispatch", "apply"}:
        raise ActionResumeError("ACTION_KIND_INVALID", "only dispatch/apply can cross the gate")
    checkpoint_info = _mapping(data.get("checkpoint"), "checkpoint")
    checkpoint_path = Path(_text(checkpoint_info.get("path"), "checkpoint.path"))
    checkpoint, checkpoint_raw = _read_json(checkpoint_path, "checkpoint")
    if _sha256_bytes(checkpoint_raw) != checkpoint_info.get("sha256"):
        raise ActionResumeError("CHECKPOINT_CHANGED", "checkpoint changed after receipt issuance")
    _validate_checkpoint(checkpoint)
    _, cursor = _event_ref(checkpoint)
    task_info = _mapping(data.get("task_run"), "task_run")
    chain = _load_chain(Path(_text(task_info.get("path"), "task_run.path")), checkpoint, cursor)
    head = _mapping(data.get("event_head"), "event_head")
    current_head = _mapping(chain["head"], "current_head")
    for field, current in (
        ("event_count", chain["event_count"]),
        ("event_id", current_head.get("event_id")),
        ("phase", current_head.get("phase")),
    ):
        if head.get(field) != current:
            raise ActionResumeError("ACTION_RECEIPT_STALE", f"event head changed: {field}")
    for field in ("task_sha256", "state_sha256", "events_sha256"):
        if task_info.get(field) != chain[field]:
            raise ActionResumeError("ACTION_RECEIPT_STALE", f"task-run changed: {field}")
    if data.get("reuse_index") != chain["reuse_index"]:
        raise ActionResumeError("ACTION_RECEIPT_STALE", "reuse index binding changed")
    if expected_side_effect_id in chain["side_effect_ids"]:
        raise ActionResumeError("DUPLICATE_SIDE_EFFECT_BLOCKED", "side_effect already recorded")
    if _mutation_frozen(chain):
        raise ActionResumeError("RUN_MUTATION_FROZEN", "run is paused or stopped")
    facts = data.get("observed_facts")
    if not isinstance(facts, list):
        raise ActionResumeError("WORLD_FACT_INVALID", "observed_facts must be an array")
    for index, raw_fact in enumerate(facts):
        fact = _mapping(raw_fact, f"observed_facts[{index}]")
        expectation = fact.get("expectation")
        if expectation == "work_pin":
            continue
        path = Path(_text(fact.get("path"), f"observed_facts[{index}].path"))
        if expectation == "absent":
            if path.exists():
                raise ActionResumeError(
                    "CHECKPOINT_WORLD_DIVERGED", f"expected absent path appeared: {path}"
                )
        elif expectation == "file_sha256":
            if (
                not path.is_file()
                or _sha256_file(path) != fact.get("sha256")
                or path.stat().st_size != fact.get("bytes")
            ):
                raise ActionResumeError("CHECKPOINT_WORLD_DIVERGED", f"file fact drifted: {path}")
        else:
            raise ActionResumeError("WORLD_FACT_INVALID", f"unsupported expectation: {expectation}")
    if _sha256_bytes(canonical_json_bytes(facts)) != data.get("world_sha256"):
        raise ActionResumeError("CHECKPOINT_WORLD_DIVERGED", "world fact seal drifted")
    return {
        "schema_version": VERIFICATION_VERSION,
        "ok": True,
        "reason_code": "ACTION_RECEIPT_FRESH",
        "receipt_sha256": seal,
        "run_id": chain["run_id"],
        "event_count": chain["event_count"],
        "event_id": current_head.get("event_id"),
        "action_kind": expected_action_kind,
        "work_key": expected_work_key,
        "side_effect_id": expected_side_effect_id,
        "authority": False,
        "completion_claim_allowed": False,
    }


def _replace_record(path: Path, value: Mapping[str, object]) -> None:
    raw = artifact_json_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def consume_action_resume_receipt(
    receipt_path: Path,
    *,
    expected_action_kind: str,
    expected_work_key: str,
    expected_side_effect_id: str,
    consumer: Callable[[], object],
    consumption_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically admit a receipt once, then invoke exactly one bounded consumer."""

    receipt_path = Path(receipt_path).resolve()
    receipt, _ = _read_json(receipt_path, "receipt")
    verification = verify_action_resume_receipt(
        receipt,
        expected_action_kind=expected_action_kind,
        expected_work_key=expected_work_key,
        expected_side_effect_id=expected_side_effect_id,
        now=now,
    )
    claim_path = (
        Path(consumption_path).resolve()
        if consumption_path is not None
        else receipt_path.with_name(f"{receipt_path.name}.consumption.json")
    )
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claimed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    claim = {
        "schema_version": CONSUMPTION_VERSION,
        "status": "claimed",
        "claimed_at": _iso(claimed_at),
        "receipt_path": str(receipt_path),
        "receipt_sha256": verification["receipt_sha256"],
        "work_key": expected_work_key,
        "side_effect_id": expected_side_effect_id,
        "authority": False,
        "completion_claim_allowed": False,
    }
    try:
        with claim_path.open("xb") as handle:
            handle.write(artifact_json_bytes(claim))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ActionResumeError(
            "ACTION_RECEIPT_ALREADY_CONSUMED", "one-shot receipt was already claimed"
        ) from exc
    try:
        verification = verify_action_resume_receipt(
            receipt,
            expected_action_kind=expected_action_kind,
            expected_work_key=expected_work_key,
            expected_side_effect_id=expected_side_effect_id,
            now=now,
        )
    except ActionResumeError as exc:
        rejected = {
            **claim,
            "status": "rejected",
            "finished_at": _iso(datetime.now(timezone.utc)),
            "reason_code": exc.reason_code,
        }
        _replace_record(claim_path, rejected)
        raise
    try:
        result = consumer()
    except Exception as exc:
        failed = {
            **claim,
            "status": "failed",
            "finished_at": _iso(datetime.now(timezone.utc)),
            "reason_code": "ACTION_CONSUMER_FAILED",
            "error_type": type(exc).__name__,
        }
        _replace_record(claim_path, failed)
        raise ActionResumeError(
            "ACTION_CONSUMER_FAILED", f"one-shot consumer failed: {type(exc).__name__}"
        ) from exc
    result_digest = (
        _sha256_bytes(canonical_json_bytes(result))
        if isinstance(result, Mapping)
        else _sha256_bytes(str(result).encode("utf-8"))
    )
    consumed = {
        **claim,
        "status": "consumed",
        "finished_at": _iso(datetime.now(timezone.utc)),
        "reason_code": "ACTION_RECEIPT_CONSUMED",
        "result_sha256": result_digest,
    }
    _replace_record(claim_path, consumed)
    return {**consumed, "consumption_path": str(claim_path), "effect_count": 1}


def _load_receipt(path: Path) -> dict[str, Any]:
    value, _ = _read_json(path, "receipt")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--checkpoint", type=Path, required=True)
    issue.add_argument("--task-run-dir", type=Path)
    issue.add_argument("--action-kind", choices=sorted(_ACTION_KINDS), default="reconcile")
    issue.add_argument("--work-key", default="")
    issue.add_argument("--next-action", default="")
    issue.add_argument("--side-effect-id", default="")
    issue.add_argument("--fact", type=Path, action="append", default=[])
    issue.add_argument("--expect-absent", type=Path, action="append", default=[])
    issue.add_argument("--work-pin", default="")
    issue.add_argument("--expected-world-sha256", default="")
    issue.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    issue.add_argument("--output", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--action-kind", choices=["dispatch", "apply"], required=True)
    verify.add_argument("--work-key", required=True)
    verify.add_argument("--side-effect-id", required=True)
    consume = sub.add_parser("consume-canary")
    consume.add_argument("--receipt", type=Path, required=True)
    consume.add_argument("--action-kind", choices=["dispatch", "apply"], required=True)
    consume.add_argument("--work-key", required=True)
    consume.add_argument("--side-effect-id", required=True)
    consume.add_argument("--canary-output", type=Path, required=True)
    consume.add_argument("--payload", default="consumed")
    consume.add_argument("--consumption-record", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "issue":
            receipt = issue_action_resume_receipt(
                checkpoint_path=args.checkpoint,
                task_run_dir=args.task_run_dir,
                action_kind=args.action_kind,
                work_key=args.work_key,
                next_action=args.next_action,
                side_effect_id=args.side_effect_id,
                observed_files=args.fact,
                expected_absent_paths=args.expect_absent,
                work_pin=args.work_pin,
                expected_world_sha256=args.expected_world_sha256,
                ttl_seconds=args.ttl_seconds,
            )
            if args.output:
                write_action_resume_receipt(args.output, receipt)
            elif args.action_kind != "reconcile":
                raise ActionResumeError(
                    "OUTPUT_REQUIRED", "dispatch/apply receipt requires --output"
                )
            report: Mapping[str, object] = receipt
        elif args.command == "verify":
            report = verify_action_resume_receipt(
                _load_receipt(args.receipt),
                expected_action_kind=args.action_kind,
                expected_work_key=args.work_key,
                expected_side_effect_id=args.side_effect_id,
            )
        else:
            output = Path(args.canary_output).resolve()

            def canary() -> dict[str, object]:
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as handle:
                    raw = str(args.payload).encode("utf-8")
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                return {
                    "path": str(output),
                    "sha256": _sha256_file(output),
                    "bytes": output.stat().st_size,
                }

            report = consume_action_resume_receipt(
                args.receipt,
                expected_action_kind=args.action_kind,
                expected_work_key=args.work_key,
                expected_side_effect_id=args.side_effect_id,
                consumer=canary,
                consumption_path=args.consumption_record,
            )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ActionResumeError as exc:
        print(
            json.dumps(
                {
                    "schema_version": VERIFICATION_VERSION,
                    "ok": False,
                    "reason_code": exc.reason_code,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ActionResumeError",
    "issue_action_resume_receipt",
    "write_action_resume_receipt",
    "verify_action_resume_receipt",
    "consume_action_resume_receipt",
    "main",
]
