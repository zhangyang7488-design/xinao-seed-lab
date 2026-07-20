"""Read-only task-run recovery plus a one-shot pre-action receipt consumer.

Task-run events remain the sole durable execution truth.  Checkpoints, replay
reports, receipts, and one-shot consumption records are non-authoritative
projections and guards; they never grant permission or parent completion.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import artifact_json_bytes, canonical_json_bytes

CHECKPOINT_VERSION = "xinao.codex_session_checkpoint.v2"
CHECKPOINT_SENTINEL = "SENTINEL:XINAO_CODEX_SESSION_CHECKPOINT_V2"
REUSE_INDEX_VERSION = "xinao.codex_task_run.fan_in_reuse_index.v1"
TASK_RUN_VERSION = "codex.verified-task-run.v1"
LEGACY_RECEIPT_VERSION = "xinao.action_resume_receipt.v1"
RECEIPT_VERSION = "xinao.action_resume_receipt.v2"
VERIFICATION_VERSION = "xinao.action_resume_verification.v2"
LEGACY_CONSUMPTION_VERSION = "xinao.action_resume_consumption.v1"
CONSUMPTION_VERSION = "xinao.action_resume_consumption.v3"
CLAIM_CONTEXT_VERSION = "xinao.action_claim_context.v3"
EFFECT_OUTCOME_VERSION = "xinao.action_effect_outcome.v3"
WORK_UNIT_FINALIZER_EVIDENCE_VERSION = "xinao.work_unit_finalizer_evidence.v1"
DEFAULT_TTL_SECONDS = 3600
DEFAULT_CLAIM_LEASE_SECONDS = 300
MAX_CLAIM_LEASE_SECONDS = 3600
MAX_TTL_SECONDS = 86400
MAX_DELTA_EVENTS = 128
MAX_DELTA_BYTES = 131072
_EVENT_REF_RE = re.compile(r"^(?P<path>.+[\\/]events\.jsonl)#event(?P<count>[1-9][0-9]*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTION_KINDS = frozenset({"reconcile", "dispatch", "apply", "land", "retire"})
_MUTATING_ACTION_KINDS = frozenset({"dispatch", "apply", "land", "retire"})
_ACTION_RESULT_PHASES = {
    # Dispatch closes only the mutually-exclusive route claim.  It does not
    # claim worker completion, adoption, authority application, or effect.
    "dispatch": "worker_route_claimed",
    "apply": "work_unit_effect_verified",
    "land": "work_unit_land_verified",
}
_RESULT_PHASE_EVIDENCE_KINDS = {
    "worker_route_claimed": frozenset({"dispatch_route_claim"}),
    "work_unit_effect_verified": frozenset({"runtime_consumer"}),
    "work_unit_land_verified": frozenset({"git_remote_ref", "pull_request"}),
}
_FROZEN_STATUSES = frozenset({"paused", "stopped", "cancelled"})
_SEMANTIC_FACT_KINDS = frozenset(
    {"git_remote_ref", "pull_request", "runtime_consumer", "carrier_inventory"}
)
_TERMINAL_WORK_UNIT_PHASES = frozenset(
    {
        "work_unit_effect_verified",
        "work_unit_effect_not_required",
        "work_unit_blocked",
        "work_unit_failed",
        "work_unit_cancelled",
    }
)


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
    files: Sequence[Path],
    absent: Sequence[Path],
    work_pin: str,
    semantic_facts: Sequence[Mapping[str, object]],
    work_key: str,
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
    for index, raw in enumerate(semantic_facts):
        descriptor = _mapping(raw, f"semantic_facts[{index}]")
        kind = _text(descriptor.get("kind"), f"semantic_facts[{index}].kind").strip()
        subject = _text(descriptor.get("subject"), f"semantic_facts[{index}].subject").strip()
        descriptor_work_key = _text(
            descriptor.get("work_key"), f"semantic_facts[{index}].work_key"
        ).strip()
        observed_value = _text(
            descriptor.get("observed_value"),
            f"semantic_facts[{index}].observed_value",
        ).strip()
        if kind not in _SEMANTIC_FACT_KINDS:
            raise ActionResumeError("WORLD_FACT_INVALID", f"unsupported semantic fact kind: {kind}")
        if descriptor_work_key != work_key:
            raise ActionResumeError(
                "WORLD_FACT_INVALID", "semantic fact work_key does not match the action"
            )
        source = Path(
            _text(descriptor.get("source_path"), f"semantic_facts[{index}].source_path")
        ).resolve()
        key = _path_key(source)
        if key in seen or not source.is_file():
            raise ActionResumeError(
                "WORLD_FACT_INVALID", f"semantic fact source is missing or duplicated: {source}"
            )
        seen.add(key)
        facts.append(
            {
                "path": str(source),
                "expectation": "typed_file_sha256",
                "kind": kind,
                "subject": subject,
                "work_key": descriptor_work_key,
                "observed_value": observed_value,
                "sha256": _sha256_file(source),
                "bytes": source.stat().st_size,
            }
        )
    if work_pin:
        facts.append({"expectation": "work_pin", "value": work_pin})
    return sorted(
        facts,
        key=lambda row: (str(row.get("expectation")), os.path.normcase(str(row.get("path") or ""))),
    )


def _action_digest(action: Mapping[str, object]) -> str:
    identity = {
        key: action.get(key)
        for key in (
            "kind",
            "work_key",
            "next_action",
            "side_effect_id",
            "world_sha256",
            "expected_result_phase",
        )
    }
    return _sha256_bytes(canonical_json_bytes(identity))


def _result_phase_for_action(
    action_kind: str,
    requested: str = "",
    *,
    require_defined: bool = False,
) -> str:
    requested = requested.strip()
    if action_kind == "reconcile":
        if requested:
            raise ActionResumeError(
                "ACTION_RESULT_PHASE_MISMATCH",
                "read-only reconciliation cannot bind a result phase",
            )
        return ""
    expected = _ACTION_RESULT_PHASES.get(action_kind)
    if expected is None:
        if requested:
            raise ActionResumeError(
                "ACTION_RESULT_PHASE_MISMATCH",
                f"{action_kind} has no defined completion-safe result phase",
            )
        if require_defined:
            raise ActionResumeError(
                "ACTION_RESULT_PHASE_UNDEFINED",
                f"no completion-safe result phase is defined for {action_kind}",
            )
        return ""
    if requested and requested != expected:
        raise ActionResumeError(
            "ACTION_RESULT_PHASE_MISMATCH",
            f"{action_kind} requires result phase {expected}",
        )
    return expected


def _hash_bound_event_evidence(event: Mapping[str, object]) -> bool:
    refs = event.get("evidence_refs")
    if not isinstance(refs, list):
        return False
    for raw_ref in refs:
        reference = str(raw_ref or "")
        if "#sha256=" not in reference:
            continue
        path_text, expected = reference.rsplit("#sha256=", 1)
        if not _SHA256_RE.fullmatch(expected):
            continue
        try:
            if _sha256_file(Path(path_text)) == expected:
                return True
        except OSError:
            continue
    return False


def _work_unit_control_state(chain: Mapping[str, object], work_key: str) -> tuple[bool, str]:
    events = chain.get("events") or []
    bound = False
    state = "unbound"
    if not isinstance(events, list):
        return bound, state
    for event in events:
        if not isinstance(event, Mapping) or str(event.get("target") or "") != work_key:
            continue
        phase = str(event.get("phase") or "").lower()
        if not phase.startswith("work_unit_"):
            continue
        kind = str(event.get("kind") or "").lower()
        exit_code = event.get("exit_code")
        if phase in {"work_unit_paused", "work_unit_interrupted"}:
            if kind not in {"pause", "result"} or exit_code not in {None, 0}:
                continue
            bound = True
            state = phase.removeprefix("work_unit_")
        elif phase == "work_unit_resume_reconciled":
            if kind != "result" or exit_code != 0 or not _hash_bound_event_evidence(event):
                continue
            bound = True
            state = "active"
        elif kind == "result" and exit_code == 0:
            bound = True
            state = phase.removeprefix("work_unit_")
    return bound, state


def _mutation_frozen(chain: Mapping[str, object], work_key: str) -> bool:
    state = _mapping(chain.get("state"), "state")
    status = str(state.get("status") or "").lower()
    # The canonical task-run has exactly one mutable state: in_progress.
    # verified/partial/blocked/unverified are terminal outcomes, not synonyms
    # for an active run that may issue another dispatch/apply/land/retire.
    if status != "in_progress" or status in _FROZEN_STATUSES:
        return True
    events = chain.get("events") or []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            phase = str(event.get("phase") or "").lower()
            kind = str(event.get("kind") or "").lower()
            if kind == "stop" or (phase.endswith("_stopped") and not event.get("target")):
                return True
    bound, work_state = _work_unit_control_state(chain, work_key)
    if not bound:
        raise ActionResumeError(
            "WORK_KEY_UNBOUND",
            "mutating actions require an existing typed work_unit event for the same work_key",
        )
    return work_state in {"paused", "interrupted"} or (
        f"work_unit_{work_state}" in _TERMINAL_WORK_UNIT_PHASES
    )


def _claim_path(run_dir: Path, work_key: str, side_effect_id: str) -> Path:
    identity = canonical_json_bytes(
        {"run_id": run_dir.name, "work_key": work_key, "side_effect_id": side_effect_id}
    )
    return run_dir / "action_consumptions" / f"{_sha256_bytes(identity)}.json"


def action_consumption_path(run_dir: Path, work_key: str, side_effect_id: str) -> Path:
    """Return the canonical existing action-resume claim path for one side effect."""

    return _claim_path(
        Path(run_dir).resolve(),
        _text(work_key, "work_key").strip(),
        _text(side_effect_id, "side_effect_id").strip(),
    ).resolve()


def _assert_no_prior_claim(
    run_dir: Path,
    work_key: str,
    side_effect_id: str,
    *,
    allowed_receipt_sha256: str = "",
    allowed_claim_generation: int = 0,
    allowed_fence_token: str = "",
) -> Path:
    claim_path = _claim_path(run_dir, work_key, side_effect_id)
    if not claim_path.exists():
        return claim_path
    try:
        claim, _ = _read_json(claim_path, "consumption_claim")
    except ActionResumeError:
        claim = {}
    if (
        claim.get("schema_version") == CONSUMPTION_VERSION
        and claim.get("status") == "aborted_pre_effect"
        and claim.get("work_key") == work_key
        and claim.get("side_effect_id") == side_effect_id
        and claim.get("safe_retry") is True
    ):
        return claim_path
    if allowed_receipt_sha256:
        if claim:
            if (
                claim.get("status") == "claimed"
                and claim.get("receipt_sha256") == allowed_receipt_sha256
                and claim.get("work_key") == work_key
                and claim.get("side_effect_id") == side_effect_id
                and (
                    not allowed_claim_generation
                    or claim.get("claim_generation") == allowed_claim_generation
                )
                and (not allowed_fence_token or claim.get("fence_token") == allowed_fence_token)
            ):
                return claim_path
    raise ActionResumeError(
        "SIDE_EFFECT_CLAIM_EXISTS",
        "a durable claim already exists; reconcile/read back the effect before any retry",
    )


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
    semantic_facts: Sequence[Mapping[str, object]] = (),
    work_pin: str = "",
    expected_result_phase: str = "",
    expected_world_sha256: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    if action_kind not in _ACTION_KINDS:
        raise ActionResumeError("ACTION_KIND_INVALID", f"unsupported action kind: {action_kind}")
    result_phase = _result_phase_for_action(action_kind, expected_result_phase)
    if not 60 <= ttl_seconds <= MAX_TTL_SECONDS:
        raise ActionResumeError("TTL_INVALID", "receipt TTL is outside the bounded range")
    if action_kind == "reconcile":
        if side_effect_id.strip():
            raise ActionResumeError(
                "ACTION_IDENTITY_INVALID", "read-only reconciliation cannot bind a side effect"
            )
        work_key = work_key.strip()
        next_action = next_action.strip()
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
    if action_kind != "reconcile" and _mutation_frozen(chain, work_key):
        raise ActionResumeError("RUN_MUTATION_FROZEN", "run is not in progress, paused, or stopped")
    if side_effect_id and side_effect_id in chain["side_effect_ids"]:
        raise ActionResumeError("DUPLICATE_SIDE_EFFECT_BLOCKED", "side_effect_id already exists")
    if side_effect_id:
        _assert_no_prior_claim(run_dir, work_key, side_effect_id)
    facts = _world_facts(
        observed_files,
        expected_absent_paths,
        work_pin,
        semantic_facts,
        work_key,
    )
    live_facts = [row for row in facts if row.get("expectation") != "work_pin"]
    if action_kind in {"apply", "land", "retire"} and not live_facts:
        raise ActionResumeError(
            "WORLD_FACT_REQUIRED", f"{action_kind} must bind a re-readable live fact"
        )
    semantic_kinds = {
        str(row.get("kind") or "") for row in facts if row.get("expectation") == "typed_file_sha256"
    }
    if action_kind == "land" and not semantic_kinds.intersection(
        {"git_remote_ref", "pull_request"}
    ):
        raise ActionResumeError(
            "SEMANTIC_FACT_REQUIRED",
            "land requires a work-key-bound git_remote_ref or pull_request readback",
        )
    if action_kind == "retire" and "carrier_inventory" not in semantic_kinds:
        raise ActionResumeError(
            "SEMANTIC_FACT_REQUIRED",
            "retire requires a work-key-bound carrier_inventory readback",
        )
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
            "world_sha256": world_sha,
            "expected_result_phase": result_phase or None,
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
    body["action"]["action_digest"] = _action_digest(body["action"])
    body["work_pin_reverified"] = False
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
    expected_next_action: str = "",
    expected_result_phase: str = "",
    _allowed_claim_receipt_sha256: str = "",
    _allowed_claim_generation: int = 0,
    _allowed_fence_token: str = "",
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
    if not expected_next_action:
        raise ActionResumeError(
            "ACTION_IDENTITY_MISMATCH", "every mutating action requires exact next_action"
        )
    if action.get("next_action") != expected_next_action:
        raise ActionResumeError("ACTION_IDENTITY_MISMATCH", "next_action mismatch")
    if expected_action_kind not in _MUTATING_ACTION_KINDS:
        raise ActionResumeError("ACTION_KIND_INVALID", "only mutating actions can cross the gate")
    result_phase = _result_phase_for_action(expected_action_kind, expected_result_phase)
    if action.get("expected_result_phase") != (result_phase or None):
        raise ActionResumeError(
            "ACTION_RESULT_PHASE_MISMATCH", "receipt result phase does not match the action"
        )
    if action.get("action_digest") != _action_digest(action):
        raise ActionResumeError("ACTION_IDENTITY_MISMATCH", "action digest mismatch")
    checkpoint_info = _mapping(data.get("checkpoint"), "checkpoint")
    checkpoint_path = Path(_text(checkpoint_info.get("path"), "checkpoint.path"))
    checkpoint, checkpoint_raw = _read_json(checkpoint_path, "checkpoint")
    if _sha256_bytes(checkpoint_raw) != checkpoint_info.get("sha256"):
        raise ActionResumeError("CHECKPOINT_CHANGED", "checkpoint changed after receipt issuance")
    _validate_checkpoint(checkpoint)
    _, cursor = _event_ref(checkpoint)
    task_info = _mapping(data.get("task_run"), "task_run")
    run_dir = Path(_text(task_info.get("path"), "task_run.path"))
    chain = _load_chain(run_dir, checkpoint, cursor)
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
    _assert_no_prior_claim(
        run_dir,
        expected_work_key,
        expected_side_effect_id,
        allowed_receipt_sha256=_allowed_claim_receipt_sha256,
        allowed_claim_generation=_allowed_claim_generation,
        allowed_fence_token=_allowed_fence_token,
    )
    if _mutation_frozen(chain, expected_work_key):
        raise ActionResumeError("RUN_MUTATION_FROZEN", "run is not in progress, paused, or stopped")
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
        elif expectation in {"file_sha256", "typed_file_sha256"}:
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
    if action.get("world_sha256") != data.get("world_sha256"):
        raise ActionResumeError("ACTION_IDENTITY_MISMATCH", "action world binding drifted")
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
        "next_action": action.get("next_action"),
        "expected_result_phase": result_phase,
        "action_digest": action.get("action_digest"),
        "authority": False,
        "completion_claim_allowed": False,
    }


def _replace_record(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


@contextmanager
def _claim_lock(claim_path: Path):
    """Serialize v3 claim transitions without introducing another state service."""

    lock_path = claim_path.with_name(f".{claim_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _claim_report(claim_path: Path, claim: Mapping[str, object]) -> dict[str, Any]:
    return {**dict(claim), "consumption_path": str(claim_path)}


def _effect_outcome_error(message: str) -> ActionResumeError:
    return ActionResumeError("ACTION_EFFECT_OUTCOME_UNPROVEN", message)


def _opaque_result_sha256(value: object) -> str:
    try:
        raw = canonical_json_bytes(value) if isinstance(value, Mapping) else str(value).encode()
    except (TypeError, ValueError):
        raw = f"unserializable:{type(value).__module__}.{type(value).__qualname__}".encode()
    return _sha256_bytes(raw)


def _validated_evidence_refs(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _effect_outcome_error("typed readback requires hash-bound evidence_refs")
    references: list[str] = []
    for raw in value:
        reference = str(raw or "")
        if "#sha256=" not in reference:
            raise _effect_outcome_error("effect evidence must use path#sha256=<digest>")
        path_text, expected = reference.rsplit("#sha256=", 1)
        if not _SHA256_RE.fullmatch(expected):
            raise _effect_outcome_error("effect evidence contains an invalid sha256")
        path = Path(path_text)
        try:
            valid = path.is_file() and _sha256_file(path) == expected
        except OSError:
            valid = False
        if not valid:
            raise _effect_outcome_error("effect evidence is missing or its hash drifted")
        references.append(reference)
    return references


def _validated_finalizer_evidence_refs(
    value: object,
    *,
    result_phase: str,
    work_key: str,
) -> list[str]:
    allowed_kinds = _RESULT_PHASE_EVIDENCE_KINDS.get(result_phase)
    if allowed_kinds is None:
        raise _effect_outcome_error(f"unsupported task-run result phase: {result_phase}")
    references = _validated_evidence_refs(value)
    for reference in references:
        path_text, _ = reference.rsplit("#sha256=", 1)
        try:
            evidence, _ = _read_json(Path(path_text), "work_unit_finalizer_evidence")
        except ActionResumeError as exc:
            raise _effect_outcome_error("task-run evidence is not readable typed JSON") from exc
        kind = str(evidence.get("kind") or "")
        if (
            evidence.get("schema_version") != WORK_UNIT_FINALIZER_EVIDENCE_VERSION
            or evidence.get("authority") is not False
            or evidence.get("completion_claim_allowed") is not False
            or evidence.get("work_key") != work_key
            or kind not in allowed_kinds
            or not str(evidence.get("subject") or "").strip()
            or not str(evidence.get("observed_value") or "").strip()
            or evidence.get("readback_verified") is not True
        ):
            raise _effect_outcome_error(
                f"task-run evidence does not satisfy {result_phase} for {work_key}"
            )
    return references


def build_action_effect_outcome(
    context: Mapping[str, object],
    *,
    status: str,
    adapter_kind: str,
    observed_before: str,
    observed_after: str,
    evidence_refs: Sequence[str],
    result_phase: str = "",
    task_run_evidence_refs: Sequence[str] = (),
    cas_applied: bool | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Build the typed result that a CAS/readback adapter must return."""

    claim = _mapping(context, "claim_context")
    if claim.get("schema_version") != CLAIM_CONTEXT_VERSION:
        raise ActionResumeError("CLAIM_CONTEXT_INVALID", "unsupported claim context")
    if status not in {"applied", "already_applied", "cas_conflict", "not_applied", "unknown"}:
        raise ActionResumeError("ACTION_EFFECT_STATUS_INVALID", f"unsupported status: {status}")
    adapter_kind = _text(adapter_kind, "adapter_kind").strip()
    before = _text(observed_before, "observed_before", allow_empty=True)
    after = _text(observed_after, "observed_after", allow_empty=True)
    claim_phase = _text(
        claim.get("expected_result_phase"), "claim_context.expected_result_phase"
    ).strip()
    requested_phase = result_phase.strip() or claim_phase
    if requested_phase != claim_phase:
        raise ActionResumeError(
            "ACTION_RESULT_PHASE_MISMATCH", "adapter result phase drifted from the claim"
        )
    applied = status == "applied" if cas_applied is None else bool(cas_applied)
    return {
        "schema_version": EFFECT_OUTCOME_VERSION,
        "status": status,
        "adapter_kind": adapter_kind,
        "run_id": claim.get("run_id"),
        "action_kind": claim.get("action_kind"),
        "work_key": claim.get("work_key"),
        "side_effect_id": claim.get("side_effect_id"),
        "action_digest": claim.get("action_digest"),
        "claim_generation": claim.get("claim_generation"),
        "fence_token": claim.get("fence_token"),
        "expected_version": claim.get("expected_version"),
        "expected_result_phase": claim_phase,
        "cas": {
            "operation": adapter_kind,
            "expected_version": claim.get("expected_version"),
            "observed_before": before,
            "observed_after": after,
            "applied": applied,
        },
        "readback": {
            "verified": status != "unknown",
            "observed_version": after,
            "evidence_refs": list(evidence_refs),
        },
        "task_run_result": {
            "phase": requested_phase,
            "evidence_refs": list(task_run_evidence_refs),
        },
        "details": dict(details or {}),
        "authority": False,
        "completion_claim_allowed": False,
    }


def _validate_effect_outcome(value: object, context: Mapping[str, object]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _effect_outcome_error("consumer returned an untyped result")
    outcome = dict(value)
    if outcome.get("schema_version") != EFFECT_OUTCOME_VERSION:
        raise _effect_outcome_error("consumer did not return the v3 typed outcome")
    status = str(outcome.get("status") or "")
    if status not in {"applied", "already_applied", "cas_conflict", "not_applied", "unknown"}:
        raise _effect_outcome_error("typed outcome has an unsupported status")
    for field in (
        "run_id",
        "action_kind",
        "work_key",
        "side_effect_id",
        "action_digest",
        "claim_generation",
        "fence_token",
        "expected_version",
        "expected_result_phase",
    ):
        if outcome.get(field) != context.get(field):
            raise _effect_outcome_error(f"typed outcome drifted from claim field: {field}")
    adapter_kind = outcome.get("adapter_kind")
    if not isinstance(adapter_kind, str) or not adapter_kind.strip():
        raise _effect_outcome_error("typed outcome lacks adapter_kind")
    cas = outcome.get("cas")
    readback = outcome.get("readback")
    task_run_result = outcome.get("task_run_result")
    if (
        not isinstance(cas, Mapping)
        or not isinstance(readback, Mapping)
        or not isinstance(task_run_result, Mapping)
    ):
        raise _effect_outcome_error(
            "typed outcome requires cas, readback, and task_run_result objects"
        )
    result_phase = str(context.get("expected_result_phase") or "")
    if task_run_result.get("phase") != result_phase:
        raise _effect_outcome_error("task-run result phase drifted from the claim")
    if cas.get("operation") != adapter_kind:
        raise _effect_outcome_error("CAS operation does not match adapter_kind")
    if cas.get("expected_version") != context.get("expected_version"):
        raise _effect_outcome_error("CAS expected version is not claim-bound")
    if not isinstance(cas.get("applied"), bool):
        raise _effect_outcome_error("CAS applied flag must be boolean")
    if status == "applied" and cas.get("applied") is not True:
        raise _effect_outcome_error("applied outcome did not prove a successful CAS")
    if (
        status in {"already_applied", "cas_conflict", "not_applied"}
        and cas.get("applied") is not False
    ):
        raise _effect_outcome_error("non-applying outcome claims a CAS mutation")
    if status != "unknown":
        if readback.get("verified") is not True:
            raise _effect_outcome_error("effect status lacks verified readback")
        if readback.get("observed_version") != cas.get("observed_after"):
            raise _effect_outcome_error("readback and CAS post-state disagree")
        normalized_refs = _validated_evidence_refs(readback.get("evidence_refs"))
        outcome["readback"] = {**dict(readback), "evidence_refs": normalized_refs}
    if status in {"applied", "already_applied"}:
        work_key = _text(context.get("work_key"), "claim_context.work_key").strip()
        result_refs = _validated_finalizer_evidence_refs(
            task_run_result.get("evidence_refs"),
            result_phase=result_phase,
            work_key=work_key,
        )
        outcome["task_run_result"] = {
            **dict(task_run_result),
            "evidence_refs": result_refs,
        }
    try:
        canonical_json_bytes(outcome)
    except (TypeError, ValueError) as exc:
        raise _effect_outcome_error("typed outcome is not canonical-JSON serializable") from exc
    return outcome


def _bound_expected_version(receipt: Mapping[str, object], requested: str) -> str:
    action = _mapping(receipt.get("action"), "action")
    candidates = {str(action.get("world_sha256") or "")}
    facts = receipt.get("observed_facts")
    if isinstance(facts, list):
        candidates.update(
            str(fact.get("observed_value") or "")
            for fact in facts
            if isinstance(fact, Mapping) and fact.get("observed_value")
        )
    version = requested.strip() if requested else str(action.get("world_sha256") or "")
    if not version or version not in candidates:
        raise ActionResumeError(
            "EXPECTED_VERSION_UNBOUND",
            "expected version must be bound by the receipt world or a typed semantic fact",
        )
    return version


def _holder_id(value: str, role: str) -> str:
    return value.strip() or f"{role}:pid-{os.getpid()}:{uuid.uuid4().hex}"


def _fence_token(
    *, receipt_sha256: str, action_digest: str, generation: int, holder_id: str
) -> str:
    return _sha256_bytes(
        canonical_json_bytes(
            {
                "receipt_sha256": receipt_sha256,
                "action_digest": action_digest,
                "claim_generation": generation,
                "holder_id": holder_id,
            }
        )
    )


def _attempt_summary(claim: Mapping[str, object]) -> dict[str, object]:
    return {
        key: claim.get(key)
        for key in (
            "claim_generation",
            "fence_token",
            "holder_id",
            "status",
            "reason_code",
            "claimed_at",
            "finished_at",
            "effect_started_at",
        )
        if claim.get(key) is not None
    }


def _create_claim(
    claim_path: Path,
    *,
    receipt_path: Path,
    task_run_path: Path,
    verification: Mapping[str, object],
    action_kind: str,
    expected_version: str,
    holder_id: str,
    lease_seconds: int,
    claimed_at: datetime,
) -> dict[str, Any]:
    if not 1 <= lease_seconds <= MAX_CLAIM_LEASE_SECONDS:
        raise ActionResumeError("CLAIM_LEASE_INVALID", "claim lease is outside the bounded range")
    with _claim_lock(claim_path):
        existing: dict[str, Any] | None = None
        if claim_path.exists():
            existing, _ = _read_json(claim_path, "consumption_claim")
            if not (
                existing.get("schema_version") == CONSUMPTION_VERSION
                and existing.get("status") == "aborted_pre_effect"
                and existing.get("safe_retry") is True
            ):
                raise ActionResumeError(
                    "SIDE_EFFECT_CLAIM_EXISTS",
                    "an unresolved or closed durable claim already owns this side effect",
                )
            if existing.get("action_digest") != verification.get("action_digest"):
                raise ActionResumeError(
                    "ACTION_RETRY_IDENTITY_MISMATCH",
                    "a pre-effect retry cannot change the action identity",
                )
        generation = int(existing.get("claim_generation") or 0) + 1 if existing else 1
        attempts = list(existing.get("attempts") or []) if existing else []
        if existing:
            attempts.append(_attempt_summary(existing))
        fence = _fence_token(
            receipt_sha256=str(verification["receipt_sha256"]),
            action_digest=str(verification["action_digest"]),
            generation=generation,
            holder_id=holder_id,
        )
        claim = {
            "schema_version": CONSUMPTION_VERSION,
            "status": "claimed",
            "reason_code": "ACTION_CLAIM_ACQUIRED",
            "claimed_at": _iso(claimed_at),
            "lease_expires_at": _iso(claimed_at + timedelta(seconds=lease_seconds)),
            "lease_seconds": lease_seconds,
            "holder_id": holder_id,
            "claim_generation": generation,
            "fence_token": fence,
            "previous_fence_token": existing.get("fence_token") if existing else None,
            "attempts": attempts,
            "receipt_path": str(receipt_path),
            "receipt_sha256": verification["receipt_sha256"],
            "run_id": verification["run_id"],
            "task_run_path": str(task_run_path),
            "action_kind": action_kind,
            "work_key": verification["work_key"],
            "side_effect_id": verification["side_effect_id"],
            "idempotency_key": verification["side_effect_id"],
            "next_action": verification["next_action"],
            "expected_result_phase": verification["expected_result_phase"],
            "action_digest": verification["action_digest"],
            "expected_version": expected_version,
            "effect_started": False,
            "safe_retry": False,
            "authority": False,
            "completion_claim_allowed": False,
        }
        _replace_record(claim_path, claim)
        return claim


def _transition_claim(
    claim_path: Path,
    *,
    claim_generation: int,
    fence_token: str,
    updates: Mapping[str, object],
) -> dict[str, Any]:
    with _claim_lock(claim_path):
        current, _ = _read_json(claim_path, "consumption_claim")
        if (
            current.get("schema_version") != CONSUMPTION_VERSION
            or current.get("claim_generation") != claim_generation
            or current.get("fence_token") != fence_token
        ):
            raise ActionResumeError(
                "ACTION_CLAIM_FENCED",
                "claim generation or fence changed before the state transition",
            )
        updated = {**current, **dict(updates)}
        _replace_record(claim_path, updated)
        return updated


def _claim_context(claim: Mapping[str, object]) -> dict[str, Any]:
    return {
        "schema_version": CLAIM_CONTEXT_VERSION,
        "run_id": claim.get("run_id"),
        "action_kind": claim.get("action_kind"),
        "work_key": claim.get("work_key"),
        "side_effect_id": claim.get("side_effect_id"),
        "next_action": claim.get("next_action"),
        "expected_result_phase": claim.get("expected_result_phase"),
        "action_digest": claim.get("action_digest"),
        "expected_version": claim.get("expected_version"),
        "claim_generation": claim.get("claim_generation"),
        "fence_token": claim.get("fence_token"),
        "holder_id": claim.get("holder_id"),
        "lease_expires_at": claim.get("lease_expires_at"),
        "authority": False,
        "completion_claim_allowed": False,
    }


def _invoke_adapter(adapter: Callable[..., object], context: Mapping[str, object]) -> object:
    try:
        parameters = inspect.signature(adapter).parameters.values()
    except (TypeError, ValueError):
        return adapter(context)
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind
        in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if positional or any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters
    ):
        return adapter(context)
    if any(
        parameter.kind == inspect.Parameter.KEYWORD_ONLY and parameter.name == "context"
        for parameter in parameters
    ):
        return adapter(context=context)
    return adapter()


def _required_task_run_event(claim: Mapping[str, object]) -> dict[str, Any]:
    outcome = _mapping(claim.get("effect_outcome"), "effect_outcome")
    task_run_result = _mapping(outcome.get("task_run_result"), "effect_outcome.task_run_result")
    result_phase = _text(claim.get("expected_result_phase"), "claim.expected_result_phase").strip()
    if task_run_result.get("phase") != result_phase:
        raise ActionResumeError(
            "ACTION_RESULT_PHASE_MISMATCH", "persisted outcome result phase drifted"
        )
    work_key = _text(claim.get("work_key"), "claim.work_key").strip()
    result_refs = _validated_finalizer_evidence_refs(
        task_run_result.get("evidence_refs"),
        result_phase=result_phase,
        work_key=work_key,
    )
    return {
        "kind": "result",
        "phase": result_phase,
        "target": work_key,
        "side_effect_id": claim.get("side_effect_id"),
        "exit_code": 0,
        "evidence_refs": result_refs,
        "action_digest": claim.get("action_digest"),
    }


def _matching_task_run_event(claim: Mapping[str, object]) -> dict[str, Any] | None:
    run_dir = Path(_text(claim.get("task_run_path"), "claim.task_run_path"))
    run_id = _text(claim.get("run_id"), "claim.run_id")
    try:
        events = _parse_events((run_dir / "events.jsonl").read_bytes(), run_id)
    except OSError as exc:
        raise ActionResumeError(
            "TASK_RUN_MISSING", f"cannot read task-run events: {run_dir}"
        ) from exc
    required = _required_task_run_event(claim)
    required_refs = list(required["evidence_refs"])
    for event in events:
        event_refs = [str(ref) for ref in event.get("evidence_refs") or []]
        if (
            event.get("kind") == "result"
            and event.get("phase") == required["phase"]
            and event.get("target") == claim.get("work_key")
            and event.get("side_effect_id") == claim.get("side_effect_id")
            and event.get("exit_code") == 0
            and required_refs
            and required_refs == event_refs
            and _hash_bound_event_evidence(event)
        ):
            return _normalized_event(event)
    return None


def _close_or_mark_event_pending(
    claim_path: Path,
    claim: Mapping[str, object],
    *,
    at: datetime,
) -> dict[str, Any]:
    event = _matching_task_run_event(claim)
    if event is None:
        updates: dict[str, object] = {
            "status": "event_pending",
            "reason_code": "ACTION_EFFECT_EVENT_PENDING",
            "required_task_run_event": _required_task_run_event(claim),
            "task_run_result_required": True,
            "completion_claim_allowed": False,
        }
    else:
        updates = {
            "status": "closed",
            "reason_code": "ACTION_EFFECT_EVENT_CLOSED",
            "finished_at": _iso(at),
            "task_run_event": event,
            "task_run_result_required": False,
            "completion_claim_allowed": False,
        }
    return _transition_claim(
        claim_path,
        claim_generation=int(claim["claim_generation"]),
        fence_token=str(claim["fence_token"]),
        updates=updates,
    )


def _finalize_effect_outcome(
    claim_path: Path,
    claim: Mapping[str, object],
    outcome: Mapping[str, object],
    *,
    at: datetime,
) -> dict[str, Any]:
    status = str(outcome.get("status"))
    base_updates: dict[str, object] = {
        "effect_outcome": dict(outcome),
        "result_sha256": _sha256_bytes(canonical_json_bytes(outcome)),
        "readback_at": _iso(at),
    }
    if status in {"cas_conflict", "not_applied"}:
        aborted = _transition_claim(
            claim_path,
            claim_generation=int(claim["claim_generation"]),
            fence_token=str(claim["fence_token"]),
            updates={
                **base_updates,
                "status": "aborted_pre_effect",
                "reason_code": (
                    "ACTION_CAS_CONFLICT_NO_EFFECT"
                    if status == "cas_conflict"
                    else "ACTION_READBACK_PROVED_NO_EFFECT"
                ),
                "finished_at": _iso(at),
                "safe_retry": True,
            },
        )
        return aborted
    if status == "unknown":
        _transition_claim(
            claim_path,
            claim_generation=int(claim["claim_generation"]),
            fence_token=str(claim["fence_token"]),
            updates={
                **base_updates,
                "status": "effect_unknown",
                "reason_code": "ACTION_EFFECT_READBACK_UNKNOWN",
                "safe_retry": False,
            },
        )
        raise ActionResumeError(
            "ACTION_EFFECT_READBACK_UNKNOWN",
            f"effect remains uncertain; reconcile claim at {claim_path}",
        )
    verified = _transition_claim(
        claim_path,
        claim_generation=int(claim["claim_generation"]),
        fence_token=str(claim["fence_token"]),
        updates={
            **base_updates,
            "status": "readback_verified",
            "reason_code": "ACTION_EFFECT_READBACK_VERIFIED",
            "effect_readback_required_before_retry": False,
            "safe_retry": False,
        },
    )
    return _close_or_mark_event_pending(claim_path, verified, at=at)


def consume_action_resume_receipt(
    receipt_path: Path,
    *,
    expected_action_kind: str,
    expected_work_key: str,
    expected_side_effect_id: str,
    expected_next_action: str = "",
    expected_result_phase: str = "",
    consumer: Callable[..., object],
    consumption_path: Path | None = None,
    expected_version: str = "",
    holder_id: str = "",
    lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Claim an action, invoke one typed CAS adapter, and wait for its task-run event."""

    _result_phase_for_action(
        expected_action_kind,
        expected_result_phase,
        require_defined=True,
    )
    receipt_path = Path(receipt_path).resolve()
    receipt, _ = _read_json(receipt_path, "receipt")
    verification = verify_action_resume_receipt(
        receipt,
        expected_action_kind=expected_action_kind,
        expected_work_key=expected_work_key,
        expected_side_effect_id=expected_side_effect_id,
        expected_next_action=expected_next_action,
        expected_result_phase=expected_result_phase,
        now=now,
    )
    task_info = _mapping(receipt.get("task_run"), "task_run")
    run_dir = Path(_text(task_info.get("path"), "task_run.path")).resolve()
    claim_path = _claim_path(run_dir, expected_work_key, expected_side_effect_id).resolve()
    if consumption_path is not None and _path_key(Path(consumption_path)) != _path_key(claim_path):
        raise ActionResumeError(
            "CONSUMPTION_PATH_NOT_CANONICAL",
            "the claim path is derived from run_id, work_key, and side_effect_id",
        )
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claimed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    bound_version = _bound_expected_version(receipt, expected_version)
    claim = _create_claim(
        claim_path,
        receipt_path=receipt_path,
        task_run_path=run_dir,
        verification=verification,
        action_kind=expected_action_kind,
        expected_version=bound_version,
        holder_id=_holder_id(holder_id, "consumer"),
        lease_seconds=lease_seconds,
        claimed_at=claimed_at,
    )
    try:
        verification = verify_action_resume_receipt(
            receipt,
            expected_action_kind=expected_action_kind,
            expected_work_key=expected_work_key,
            expected_side_effect_id=expected_side_effect_id,
            expected_next_action=expected_next_action,
            expected_result_phase=expected_result_phase,
            _allowed_claim_receipt_sha256=verification["receipt_sha256"],
            _allowed_claim_generation=int(claim["claim_generation"]),
            _allowed_fence_token=str(claim["fence_token"]),
            now=now,
        )
    except ActionResumeError as exc:
        _transition_claim(
            claim_path,
            claim_generation=int(claim["claim_generation"]),
            fence_token=str(claim["fence_token"]),
            updates={
                "status": "aborted_pre_effect",
                "finished_at": _iso(claimed_at),
                "reason_code": exc.reason_code,
                "safe_retry": True,
            },
        )
        raise
    claim = _transition_claim(
        claim_path,
        claim_generation=int(claim["claim_generation"]),
        fence_token=str(claim["fence_token"]),
        updates={
            "status": "effect_in_progress",
            "reason_code": "ACTION_EFFECT_STARTED",
            "effect_started": True,
            "effect_started_at": _iso(claimed_at),
        },
    )
    context = _claim_context(claim)
    try:
        result = _invoke_adapter(consumer, context)
    except Exception as exc:
        _transition_claim(
            claim_path,
            claim_generation=int(claim["claim_generation"]),
            fence_token=str(claim["fence_token"]),
            updates={
                "status": "effect_unknown",
                "reason_code": "ACTION_EFFECT_EXECUTION_UNCERTAIN",
                "error_type": type(exc).__name__,
                "safe_retry": False,
            },
        )
        raise ActionResumeError(
            "ACTION_EFFECT_EXECUTION_UNCERTAIN",
            f"adapter failed after effect start: {type(exc).__name__}",
        ) from exc
    try:
        outcome = _validate_effect_outcome(result, context)
    except ActionResumeError as exc:
        _transition_claim(
            claim_path,
            claim_generation=int(claim["claim_generation"]),
            fence_token=str(claim["fence_token"]),
            updates={
                "status": "effect_unknown",
                "reason_code": exc.reason_code,
                "result_sha256": _opaque_result_sha256(result),
                "safe_retry": False,
            },
        )
        raise
    finalized = _finalize_effect_outcome(claim_path, claim, outcome, at=claimed_at)
    return _claim_report(claim_path, finalized)


def reconcile_action_resume_claim(
    consumption_path: Path,
    *,
    readback: Callable[..., object] | None = None,
    holder_id: str = "",
    lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile a crashed/uncertain claim or close a verified effect after event append."""

    claim_path = Path(consumption_path).resolve()
    claim, _ = _read_json(claim_path, "consumption_claim")
    if claim.get("schema_version") == LEGACY_CONSUMPTION_VERSION:
        return {
            "schema_version": CONSUMPTION_VERSION,
            "status": "effect_unknown",
            "reason_code": "LEGACY_CONSUMPTION_UNPROVEN",
            "legacy_status": claim.get("status"),
            "legacy_record_sha256": _sha256_file(claim_path),
            "consumption_path": str(claim_path),
            "safe_retry": False,
            "completion_claim_allowed": False,
        }
    if claim.get("schema_version") != CONSUMPTION_VERSION:
        raise ActionResumeError("ACTION_CLAIM_SCHEMA_INVALID", "unsupported claim schema")
    status = str(claim.get("status") or "")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if status == "closed" or status == "aborted_pre_effect":
        return _claim_report(claim_path, claim)
    if status in {"readback_verified", "event_pending"}:
        reconciled = _close_or_mark_event_pending(claim_path, claim, at=current)
        return _claim_report(claim_path, reconciled)
    if status not in {"claimed", "effect_in_progress", "effect_unknown", "reconciling"}:
        raise ActionResumeError("ACTION_CLAIM_STATE_INVALID", f"cannot reconcile status: {status}")
    if readback is None:
        raise ActionResumeError(
            "ACTION_READBACK_REQUIRED", "an uncertain claim requires a typed readback adapter"
        )
    if not 1 <= lease_seconds <= MAX_CLAIM_LEASE_SECONDS:
        raise ActionResumeError("CLAIM_LEASE_INVALID", "claim lease is outside the bounded range")
    if current < _parse_time(claim.get("lease_expires_at"), "claim.lease_expires_at"):
        raise ActionResumeError(
            "ACTION_CLAIM_LEASE_ACTIVE", "the current holder lease has not expired"
        )
    reconciler = _holder_id(holder_id, "reconciler")
    with _claim_lock(claim_path):
        latest, _ = _read_json(claim_path, "consumption_claim")
        if latest.get("schema_version") != CONSUMPTION_VERSION:
            raise ActionResumeError("ACTION_CLAIM_SCHEMA_INVALID", "unsupported claim schema")
        if current < _parse_time(latest.get("lease_expires_at"), "claim.lease_expires_at"):
            raise ActionResumeError(
                "ACTION_CLAIM_LEASE_ACTIVE", "another holder renewed the claim lease"
            )
        generation = int(latest.get("claim_generation") or 0) + 1
        previous_fence = str(latest.get("fence_token") or "")
        fence = _fence_token(
            receipt_sha256=str(latest.get("receipt_sha256") or ""),
            action_digest=str(latest.get("action_digest") or ""),
            generation=generation,
            holder_id=reconciler,
        )
        takeover = {
            **latest,
            "status": "reconciling",
            "reason_code": "ACTION_CLAIM_RECONCILING",
            "claim_generation": generation,
            "previous_fence_token": previous_fence,
            "fence_token": fence,
            "holder_id": reconciler,
            "claimed_at": _iso(current),
            "lease_seconds": lease_seconds,
            "lease_expires_at": _iso(current + timedelta(seconds=lease_seconds)),
            "reconciliation_history": [
                *list(latest.get("reconciliation_history") or []),
                _attempt_summary(latest),
            ],
        }
        _replace_record(claim_path, takeover)
    context = _claim_context(takeover)
    try:
        result = _invoke_adapter(readback, context)
    except Exception as exc:
        _transition_claim(
            claim_path,
            claim_generation=generation,
            fence_token=fence,
            updates={
                "status": "effect_unknown",
                "reason_code": "ACTION_READBACK_FAILED",
                "error_type": type(exc).__name__,
                "safe_retry": False,
            },
        )
        raise ActionResumeError(
            "ACTION_READBACK_FAILED", f"readback adapter failed: {type(exc).__name__}"
        ) from exc
    try:
        outcome = _validate_effect_outcome(result, context)
    except ActionResumeError as exc:
        _transition_claim(
            claim_path,
            claim_generation=generation,
            fence_token=fence,
            updates={
                "status": "effect_unknown",
                "reason_code": exc.reason_code,
                "safe_retry": False,
            },
        )
        raise
    finalized = _finalize_effect_outcome(claim_path, takeover, outcome, at=current)
    return _claim_report(claim_path, finalized)


def _stable_task_run_event_id(claim: Mapping[str, object]) -> str:
    required = _required_task_run_event(claim)
    identity = {
        "schema_version": "xinao.action_resume_task_run_event_id.v1",
        "run_id": claim.get("run_id"),
        "work_key": claim.get("work_key"),
        "side_effect_id": claim.get("side_effect_id"),
        "action_digest": claim.get("action_digest"),
        "required_task_run_event": required,
    }
    return f"action-resume:{_sha256_bytes(canonical_json_bytes(identity))}"


def append_pending_action_event_and_reconcile(
    consumption_path: Path,
    *,
    task_run_cli: Path,
    actor: str = "action-resume-owner",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one stable canonical result event, then reconcile its pending claim."""

    claim_path = Path(consumption_path).resolve()
    claim, _ = _read_json(claim_path, "consumption_claim")
    if claim.get("schema_version") != CONSUMPTION_VERSION:
        raise ActionResumeError("ACTION_CLAIM_SCHEMA_INVALID", "unsupported claim schema")
    status = str(claim.get("status") or "")
    if status == "closed":
        return _claim_report(claim_path, claim)
    if status != "event_pending":
        raise ActionResumeError(
            "ACTION_CLAIM_STATE_INVALID",
            f"owner event append requires event_pending, got: {status}",
        )
    required = _required_task_run_event(claim)
    cli_path = Path(task_run_cli).resolve()
    if not cli_path.is_file():
        raise ActionResumeError("TASK_RUN_CLI_MISSING", f"task-run CLI is missing: {cli_path}")
    run_dir = Path(_text(claim.get("task_run_path"), "claim.task_run_path")).resolve()
    run_id = _text(claim.get("run_id"), "claim.run_id").strip()
    if run_dir.name != run_id:
        raise ActionResumeError("TASK_RUN_IDENTITY_DRIFT", "claim run path and run_id disagree")
    event_id = _stable_task_run_event_id(claim)
    summary = (
        f"Action resume {claim.get('action_kind')} result verified for {claim.get('work_key')}"
    )
    command = [
        sys.executable,
        str(cli_path),
        "--root",
        str(run_dir.parent),
        "event",
        "--run-id",
        run_id,
        "--event-id",
        event_id,
        "--actor",
        _text(actor, "actor").strip(),
        "--kind",
        str(required["kind"]),
        "--phase",
        str(required["phase"]),
        "--summary",
        summary,
        "--target",
        str(required["target"]),
        "--exit-code",
        str(required["exit_code"]),
        "--retry-class",
        "none",
        "--side-effect-id",
        _text(required.get("side_effect_id"), "required_task_run_event.side_effect_id"),
    ]
    for reference in required["evidence_refs"]:
        command.extend(["--evidence-ref", str(reference)])
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except OSError as exc:
        raise ActionResumeError(
            "TASK_RUN_EVENT_APPEND_FAILED", "cannot launch the canonical task-run CLI"
        ) from exc
    if completed.returncode != 0:
        raise ActionResumeError(
            "TASK_RUN_EVENT_APPEND_FAILED",
            f"canonical task-run CLI rejected the stable event (exit={completed.returncode})",
        )
    try:
        writer_report = _mapping(json.loads(completed.stdout), "task_run_cli_result")
    except (json.JSONDecodeError, ActionResumeError) as exc:
        raise ActionResumeError(
            "TASK_RUN_EVENT_APPEND_FAILED", "canonical task-run CLI returned invalid JSON"
        ) from exc
    if writer_report.get("ok") is not True or writer_report.get("event_id") != event_id:
        raise ActionResumeError(
            "TASK_RUN_EVENT_APPEND_FAILED", "canonical task-run CLI did not confirm event identity"
        )
    reconciled = reconcile_action_resume_claim(claim_path, now=now)
    if reconciled.get("status") != "closed":
        raise ActionResumeError(
            "TASK_RUN_EVENT_NOT_VISIBLE", "canonical event append did not close the pending claim"
        )
    return {
        **reconciled,
        "owner_event_id": event_id,
        "owner_event_replayed": writer_report.get("replayed") is True,
    }


def git_update_ref_cas_adapter(
    *,
    repo_path: Path,
    ref_name: str,
    new_oid: str,
    expected_old_oid: str,
    evidence_path: Path,
    remote: str = "",
    remote_ref_name: str = "",
    runner: Callable[[list[str]], subprocess.CompletedProcess[bytes]] | None = None,
) -> Callable[[Mapping[str, object]], dict[str, Any]]:
    """CAS a local ref and prove land only through an exact remote readback.

    Without ``remote`` this is deliberately local-only: it records the native
    ``update-ref <new> <old>`` result, but returns an unknown land outcome and
    never creates a ``git_remote_ref`` finalizer.  A remote land performs a
    force-with-lease update and then requires an exact ``git ls-remote`` match.
    """

    repo = Path(repo_path).resolve()
    reference = ref_name.strip()
    new_value = new_oid.strip().lower()
    old_value = expected_old_oid.strip().lower()
    remote_name = remote.strip()
    remote_reference = remote_ref_name.strip()
    oid_re = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    if not repo.is_dir() or not reference.startswith("refs/"):
        raise ActionResumeError("GIT_CAS_INPUT_INVALID", "repo/ref input is invalid")
    if not oid_re.fullmatch(new_value) or not oid_re.fullmatch(old_value):
        raise ActionResumeError("GIT_CAS_INPUT_INVALID", "Git OIDs must be full SHA-1/SHA-256")
    if bool(remote_name) != bool(remote_reference) or (
        remote_reference and not remote_reference.startswith("refs/")
    ):
        raise ActionResumeError(
            "GIT_CAS_INPUT_INVALID",
            "remote and a full remote refs/... name must be provided together",
        )
    if any(character in remote_name + remote_reference for character in ("\0", "\r", "\n")):
        raise ActionResumeError("GIT_CAS_INPUT_INVALID", "remote input contains control bytes")
    if runner is not None and not callable(runner):
        raise ActionResumeError("GIT_CAS_INPUT_INVALID", "runner must be callable")
    evidence_base = Path(evidence_path).resolve()

    def run_git(*arguments: str) -> tuple[int, bytes, bytes]:
        command = ["git", "-C", str(repo), *arguments]
        try:
            completed = (
                runner(command)
                if runner is not None
                else subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            )
        except OSError as exc:
            return 127, b"", f"{type(exc).__name__}:{exc}".encode("utf-8", errors="replace")
        stdout = completed.stdout
        stderr = completed.stderr
        stdout_bytes = stdout if isinstance(stdout, bytes) else str(stdout or "").encode("utf-8")
        stderr_bytes = stderr if isinstance(stderr, bytes) else str(stderr or "").encode("utf-8")
        return int(completed.returncode), stdout_bytes, stderr_bytes

    def git_read_ref() -> tuple[str, int, bytes]:
        return_code, stdout, stderr = run_git("rev-parse", "--verify", reference)
        observed = stdout.decode("ascii", errors="replace").strip().lower()
        if return_code != 0 or not oid_re.fullmatch(observed):
            observed = "absent"
        return observed, return_code, stderr

    def git_read_remote_ref() -> tuple[str, bool, int, bytes, bytes]:
        return_code, stdout, stderr = run_git("ls-remote", "--refs", remote_name, remote_reference)
        if return_code != 0:
            return "unreachable", False, return_code, stdout, stderr
        rows = [row for row in stdout.decode("ascii", errors="replace").splitlines() if row]
        if not rows:
            return "absent", True, return_code, stdout, stderr
        if len(rows) != 1:
            return "ambiguous", False, return_code, stdout, stderr
        parts = rows[0].split("\t", 1)
        if len(parts) != 2 or parts[1] != remote_reference:
            return "wrong_ref", False, return_code, stdout, stderr
        observed = parts[0].strip().lower()
        if not oid_re.fullmatch(observed):
            return "invalid_oid", False, return_code, stdout, stderr
        return observed, True, return_code, stdout, stderr

    def update_local_ref() -> tuple[str, str, str, int, bytes]:
        before, _, _ = git_read_ref()
        if before == new_value:
            update_return_code = 0
            update_stderr = b""
            local_status = "already_applied"
        elif before != old_value:
            update_return_code = 1
            update_stderr = b"local expected-old mismatch"
            local_status = "cas_conflict"
        else:
            update_return_code, _, update_stderr = run_git(
                "update-ref", reference, new_value, old_value
            )
            local_status = "applied" if update_return_code == 0 else "cas_conflict"
        after, _, _ = git_read_ref()
        if after == new_value and local_status == "cas_conflict":
            local_status = "already_applied"
        elif local_status == "applied" and after != new_value:
            local_status = "unknown"
        return local_status, before, after, update_return_code, update_stderr

    def adapter(context: Mapping[str, object]) -> dict[str, Any]:
        if context.get("expected_result_phase") != "work_unit_land_verified":
            raise ActionResumeError(
                "ACTION_RESULT_PHASE_MISMATCH",
                "Git ref land adapter can only serve work_unit_land_verified",
            )
        if context.get("expected_version") != old_value:
            raise ActionResumeError(
                "EXPECTED_VERSION_MISMATCH", "Git expected-old is not bound to the claim"
            )
        remote_before = "not_configured"
        remote_after = "not_configured"
        remote_before_verified = False
        remote_after_verified = False
        remote_before_return_code: int | None = None
        remote_after_return_code: int | None = None
        remote_before_stdout = b""
        remote_before_stderr = b""
        remote_after_stdout = b""
        remote_after_stderr = b""
        push_return_code: int | None = None
        push_stdout = b""
        push_stderr = b""
        local_status = "not_attempted"
        local_before, _, _ = git_read_ref()
        local_after = local_before
        local_return_code: int | None = None
        local_stderr = b""

        if not remote_name:
            (
                local_status,
                local_before,
                local_after,
                local_return_code,
                local_stderr,
            ) = update_local_ref()
            status = "cas_conflict" if local_status == "cas_conflict" else "unknown"
        else:
            (
                remote_before,
                remote_before_verified,
                remote_before_return_code,
                remote_before_stdout,
                remote_before_stderr,
            ) = git_read_remote_ref()
            remote_after = remote_before
            remote_after_verified = remote_before_verified
            remote_after_return_code = remote_before_return_code
            remote_after_stdout = remote_before_stdout
            remote_after_stderr = remote_before_stderr
            if not remote_before_verified:
                status = "not_applied"
            elif remote_before not in {old_value, new_value}:
                status = "cas_conflict"
            else:
                (
                    local_status,
                    local_before,
                    local_after,
                    local_return_code,
                    local_stderr,
                ) = update_local_ref()
                if local_status in {"cas_conflict", "unknown"} and remote_before != new_value:
                    status = "cas_conflict" if local_status == "cas_conflict" else "unknown"
                elif remote_before == new_value:
                    status = "already_applied"
                else:
                    push_return_code, push_stdout, push_stderr = run_git(
                        "push",
                        "--porcelain",
                        f"--force-with-lease={remote_reference}:{old_value}",
                        remote_name,
                        f"{new_value}:{remote_reference}",
                    )
                    (
                        remote_after,
                        remote_after_verified,
                        remote_after_return_code,
                        remote_after_stdout,
                        remote_after_stderr,
                    ) = git_read_remote_ref()
                    if not remote_after_verified:
                        status = "unknown"
                    elif remote_after == new_value:
                        status = "applied" if push_return_code == 0 else "already_applied"
                    elif remote_after == old_value and push_return_code != 0:
                        status = "not_applied"
                    elif remote_after not in {old_value, new_value} and push_return_code != 0:
                        status = "cas_conflict"
                    else:
                        status = "unknown"

        generation = int(context.get("claim_generation") or 0)
        suffix = evidence_base.suffix or ".json"
        actual_evidence = evidence_base.with_name(f"{evidence_base.stem}.g{generation}{suffix}")
        evidence = {
            "schema_version": "xinao.git_ref_land_cas_readback.v2",
            "repo_path": str(repo),
            "local_ref_name": reference,
            "remote": remote_name or None,
            "remote_ref_name": remote_reference or None,
            "expected_old_oid": old_value,
            "new_oid": new_value,
            "local": {
                "status": local_status,
                "observed_before": local_before,
                "observed_after": local_after,
                "return_code": local_return_code,
                "stderr_sha256": _sha256_bytes(local_stderr),
            },
            "remote_readback": {
                "observed_before": remote_before,
                "before_verified": remote_before_verified,
                "before_return_code": remote_before_return_code,
                "before_stdout_sha256": _sha256_bytes(remote_before_stdout),
                "before_stderr_sha256": _sha256_bytes(remote_before_stderr),
                "push_return_code": push_return_code,
                "push_stdout_sha256": _sha256_bytes(push_stdout),
                "push_stderr_sha256": _sha256_bytes(push_stderr),
                "observed_after": remote_after,
                "after_verified": remote_after_verified,
                "after_return_code": remote_after_return_code,
                "after_stdout_sha256": _sha256_bytes(remote_after_stdout),
                "after_stderr_sha256": _sha256_bytes(remote_after_stderr),
            },
            "status": status,
            "claim_generation": generation,
            "fence_token": context.get("fence_token"),
            "authority": False,
            "completion_claim_allowed": False,
        }
        _replace_record(actual_evidence, evidence)
        evidence_sha = _sha256_file(actual_evidence)
        physical_ref = f"{actual_evidence}#sha256={evidence_sha}"
        readback_refs = [physical_ref]
        task_run_refs: list[str] = []
        local_finalizer_ref = ""
        if local_after == new_value and local_status in {"applied", "already_applied"}:
            local_finalizer_path = actual_evidence.with_name(
                f"{actual_evidence.stem}.local-finalizer.json"
            )
            local_finalizer = {
                "schema_version": WORK_UNIT_FINALIZER_EVIDENCE_VERSION,
                "kind": "git_local_ref",
                "work_key": context.get("work_key"),
                "subject": f"{repo}#{reference}",
                "observed_value": local_after,
                "readback_verified": True,
                "evidence_refs": [physical_ref],
                "authority": False,
                "completion_claim_allowed": False,
            }
            _replace_record(local_finalizer_path, local_finalizer)
            local_finalizer_ref = (
                f"{local_finalizer_path}#sha256={_sha256_file(local_finalizer_path)}"
            )
            readback_refs.append(local_finalizer_ref)
        if (
            remote_name
            and status in {"applied", "already_applied"}
            and remote_after_verified
            and remote_after == new_value
        ):
            remote_finalizer_path = actual_evidence.with_name(
                f"{actual_evidence.stem}.remote-finalizer.json"
            )
            remote_finalizer = {
                "schema_version": WORK_UNIT_FINALIZER_EVIDENCE_VERSION,
                "kind": "git_remote_ref",
                "work_key": context.get("work_key"),
                "subject": f"{remote_name}#{remote_reference}",
                "observed_value": remote_after,
                "readback_verified": True,
                "evidence_refs": [
                    physical_ref,
                    *([local_finalizer_ref] if local_finalizer_ref else []),
                ],
                "authority": False,
                "completion_claim_allowed": False,
            }
            _replace_record(remote_finalizer_path, remote_finalizer)
            task_run_refs.append(
                f"{remote_finalizer_path}#sha256={_sha256_file(remote_finalizer_path)}"
            )
        observed_before = remote_before if remote_name else local_before
        observed_after = remote_after if remote_name else local_after
        return build_action_effect_outcome(
            context,
            status=status,
            adapter_kind=(
                "git.remote-ref.force-with-lease.v1"
                if remote_name
                else "git.local-update-ref.expected-old.v1"
            ),
            observed_before=observed_before,
            observed_after=observed_after,
            evidence_refs=readback_refs,
            result_phase="work_unit_land_verified",
            task_run_evidence_refs=task_run_refs,
            cas_applied=(status == "applied" if remote_name else local_status == "applied"),
            details={
                "local_ref_name": reference,
                "local_status": local_status,
                "remote": remote_name or None,
                "remote_ref_name": remote_reference or None,
                "remote_readback_verified": remote_after_verified,
            },
        )

    return adapter


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
    issue.add_argument(
        "--semantic-fact",
        type=Path,
        action="append",
        default=[],
        help="JSON descriptor with kind, subject, work_key, observed_value, source_path",
    )
    issue.add_argument("--work-pin", default="")
    issue.add_argument("--expected-result-phase", default="")
    issue.add_argument("--expected-world-sha256", default="")
    issue.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    issue.add_argument("--output", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--action-kind", choices=sorted(_MUTATING_ACTION_KINDS), required=True)
    verify.add_argument("--work-key", required=True)
    verify.add_argument("--side-effect-id", required=True)
    verify.add_argument("--next-action", default="")
    verify.add_argument("--expected-result-phase", default="")
    consume = sub.add_parser("consume-canary")
    consume.add_argument("--receipt", type=Path, required=True)
    consume.add_argument("--action-kind", choices=sorted(_MUTATING_ACTION_KINDS), required=True)
    consume.add_argument("--work-key", required=True)
    consume.add_argument("--side-effect-id", required=True)
    consume.add_argument("--next-action", default="")
    consume.add_argument("--expected-result-phase", default="")
    consume.add_argument("--canary-output", type=Path, required=True)
    consume.add_argument("--payload", default="consumed")
    consume.add_argument("--consumption-record", type=Path)
    consume.add_argument("--expected-version", default="")
    consume.add_argument("--holder-id", default="")
    consume.add_argument("--lease-seconds", type=int, default=DEFAULT_CLAIM_LEASE_SECONDS)
    reconcile = sub.add_parser("reconcile-claim")
    reconcile.add_argument("--consumption-record", type=Path, required=True)
    close_pending = sub.add_parser("close-pending")
    close_pending.add_argument("--consumption-record", type=Path, required=True)
    close_pending.add_argument("--task-run-cli", type=Path, required=True)
    close_pending.add_argument("--actor", default="action-resume-owner")
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
                semantic_facts=[
                    _read_json(path, f"semantic_fact:{path}")[0] for path in args.semantic_fact
                ],
                work_pin=args.work_pin,
                expected_result_phase=args.expected_result_phase,
                expected_world_sha256=args.expected_world_sha256,
                ttl_seconds=args.ttl_seconds,
            )
            if args.output:
                write_action_resume_receipt(args.output, receipt)
            elif args.action_kind != "reconcile":
                raise ActionResumeError(
                    "OUTPUT_REQUIRED", "mutating action receipt requires --output"
                )
            report: Mapping[str, object] = receipt
        elif args.command == "verify":
            report = verify_action_resume_receipt(
                _load_receipt(args.receipt),
                expected_action_kind=args.action_kind,
                expected_work_key=args.work_key,
                expected_side_effect_id=args.side_effect_id,
                expected_next_action=args.next_action,
                expected_result_phase=args.expected_result_phase,
            )
        elif args.command == "consume-canary":
            output = Path(args.canary_output).resolve()

            def canary(context: Mapping[str, object]) -> dict[str, object]:
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as handle:
                    raw = str(args.payload).encode("utf-8")
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                digest = _sha256_file(output)
                physical_ref = f"{output}#sha256={digest}"
                finalizer_path = output.with_name(f"{output.name}.finalizer.json")
                _replace_record(
                    finalizer_path,
                    {
                        "schema_version": WORK_UNIT_FINALIZER_EVIDENCE_VERSION,
                        "kind": "runtime_consumer",
                        "work_key": context.get("work_key"),
                        "subject": str(output),
                        "observed_value": digest,
                        "readback_verified": True,
                        "evidence_refs": [physical_ref],
                        "authority": False,
                        "completion_claim_allowed": False,
                    },
                )
                finalizer_ref = f"{finalizer_path}#sha256={_sha256_file(finalizer_path)}"
                return build_action_effect_outcome(
                    context,
                    status="applied",
                    adapter_kind="file.create-if-absent.v1",
                    observed_before="absent",
                    observed_after=digest,
                    evidence_refs=[physical_ref],
                    result_phase="work_unit_effect_verified",
                    task_run_evidence_refs=[finalizer_ref],
                    details={"bytes": output.stat().st_size},
                )

            report = consume_action_resume_receipt(
                args.receipt,
                expected_action_kind=args.action_kind,
                expected_work_key=args.work_key,
                expected_side_effect_id=args.side_effect_id,
                expected_next_action=args.next_action,
                expected_result_phase=args.expected_result_phase,
                consumer=canary,
                consumption_path=args.consumption_record,
                expected_version=args.expected_version,
                holder_id=args.holder_id,
                lease_seconds=args.lease_seconds,
            )
        elif args.command == "reconcile-claim":
            report = reconcile_action_resume_claim(args.consumption_record)
        else:
            report = append_pending_action_event_and_reconcile(
                args.consumption_record,
                task_run_cli=args.task_run_cli,
                actor=args.actor,
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
    "build_action_effect_outcome",
    "consume_action_resume_receipt",
    "reconcile_action_resume_claim",
    "append_pending_action_event_and_reconcile",
    "git_update_ref_cas_adapter",
    "main",
]
