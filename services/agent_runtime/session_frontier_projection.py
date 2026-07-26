"""Bounded live task-run context for native Codex compact SessionStart hooks.

The task run remains authoritative. This module only binds one visible session
to one canonical run and renders a small, deterministic, non-authoritative view
when Codex reports ``SessionStart(source=compact)``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import portalocker

DEFAULT_FRONTIER_ROOT = Path(
    os.environ.get(
        "XINAO_COMPACTION_FRONTIER_ROOT",
        r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\state\compaction_frontiers",
    )
)
DEFAULT_TASK_RUN_ROOT = Path(
    os.environ.get(
        "XINAO_TASK_RUN_ROOT",
        r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs",
    )
)
BINDING_SCHEMA_VERSION = "xinao.session_run_binding.v3"
TASK_RUN_SCHEMA_VERSION = "codex.verified-task-run.v1"
DEFAULT_RENDER_CHAR_BUDGET = 2_600
MIN_RENDER_CHAR_BUDGET = 1_000
MAX_RENDER_CHAR_BUDGET = 8_000
SOURCE_READ_ATTEMPTS = 3
LOCK_TIMEOUT_SECONDS = 10
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|secret|access[_ -]?token|"
    r"refresh[_ -]?token)(\s*[:=]\s*)([^\s,;]+)"
)


class FrontierProjectionError(ValueError):
    """Raised when a binding or live task-run projection cannot be verified."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _session_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not SESSION_ID_RE.fullmatch(normalized) or normalized in {".", ".."}:
        raise FrontierProjectionError("session_id contains unsupported characters")
    return normalized


def _redact(value: object) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text
    )


def _clip(value: object, limit: int) -> str:
    text = _redact(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)].rstrip() + " …[externalized]"


def _binding_path(frontier_root: Path, session_id: str) -> Path:
    root = frontier_root.expanduser().resolve()
    path = (root / "bindings" / f"{_session_id(session_id)}.json").resolve()
    if path.parent != (root / "bindings").resolve():
        raise FrontierProjectionError("session binding escaped frontier root")
    return path


def _binding_lock_path(frontier_root: Path, session_id: str) -> Path:
    return _binding_path(frontier_root, session_id).with_suffix(".lock")


def _validated_run(run_directory: Path, allowed_run_root: Path) -> tuple[Path, str]:
    root = allowed_run_root.expanduser().resolve()
    directory = run_directory.expanduser().resolve()
    if directory.parent != root:
        raise FrontierProjectionError("run directory is outside the canonical task-run root")
    run_id = directory.name
    for name in ("task.json", "state.json", "evidence.json", "events.jsonl"):
        if not (directory / name).is_file():
            raise FrontierProjectionError(f"missing required run file: {name}")
    return directory, run_id


def _read_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except FileNotFoundError as exc:
        raise FrontierProjectionError(f"missing required file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FrontierProjectionError(f"invalid JSON in {path.name}") from exc
    if not isinstance(value, dict):
        raise FrontierProjectionError(f"{path.name} must contain a JSON object")
    return value, raw


def load_binding(
    *,
    session_id: str,
    frontier_root: Path = DEFAULT_FRONTIER_ROOT,
    allowed_run_root: Path = DEFAULT_TASK_RUN_ROOT,
) -> dict[str, Any]:
    normalized = _session_id(session_id)
    binding, raw = _read_json_object(_binding_path(frontier_root, normalized))
    if binding.get("schema_version") != BINDING_SCHEMA_VERSION:
        raise FrontierProjectionError("unsupported session binding schema")
    if binding.get("session_id") != normalized:
        raise FrontierProjectionError("session binding identity mismatch")
    expected_root = allowed_run_root.expanduser().resolve()
    if Path(str(binding.get("run_root") or "")).expanduser().resolve() != expected_root:
        raise FrontierProjectionError("session binding task-run root mismatch")
    directory, run_id = _validated_run(Path(str(binding.get("run_directory") or "")), expected_root)
    if binding.get("run_id") != run_id:
        raise FrontierProjectionError("bound run identity mismatch")
    return {
        **binding,
        "run_directory": str(directory),
        "binding_path": str(_binding_path(frontier_root, normalized)),
        "binding_sha256": _sha256(raw),
    }


def bind_session(
    *,
    session_id: str,
    run_directory: Path,
    frontier_root: Path = DEFAULT_FRONTIER_ROOT,
    allowed_run_root: Path = DEFAULT_TASK_RUN_ROOT,
    expected_current_run_id: str | None = None,
) -> dict[str, Any]:
    """Bind a session; rebinding another run requires explicit CAS identity."""

    normalized = _session_id(session_id)
    root = allowed_run_root.expanduser().resolve()
    directory, run_id = _validated_run(run_directory, root)
    path = _binding_path(frontier_root, normalized)
    lock_path = _binding_lock_path(frontier_root, normalized)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(
        str(lock_path),
        mode="a",
        timeout=LOCK_TIMEOUT_SECONDS,
        flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
    ):
        if path.exists():
            current = load_binding(
                session_id=normalized,
                frontier_root=frontier_root,
                allowed_run_root=root,
            )
            current_run_id = str(current["run_id"])
            if current_run_id == run_id:
                return current
            if expected_current_run_id != current_run_id:
                raise FrontierProjectionError(
                    "session is bound to a different run; expected_current_run_id is required"
                )
        binding = {
            "schema_version": BINDING_SCHEMA_VERSION,
            "authority": False,
            "authorization_source": None,
            "completion_claim_allowed": False,
            "session_id": normalized,
            "run_id": run_id,
            "run_root": str(root),
            "run_directory": str(directory),
        }
        payload = _json_bytes(binding)
        _write_bytes(path, payload)
        return {
            **binding,
            "binding_path": str(path),
            "binding_sha256": _sha256(payload),
        }


def _parse_events(raw: bytes, run_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise FrontierProjectionError("events.jsonl is not UTF-8") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FrontierProjectionError(
                f"invalid JSON in events.jsonl line {line_number}"
            ) from exc
        if not isinstance(event, dict) or event.get("run_id") != run_id:
            raise FrontierProjectionError("event identity does not match bound run")
        events.append(event)
    return events


def _validate_snapshot(
    run_id: str,
    task: dict[str, Any],
    state: dict[str, Any],
    evidence: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    for name, value in (("task", task), ("state", state), ("evidence", evidence)):
        if value.get("schema_version") != TASK_RUN_SCHEMA_VERSION:
            raise FrontierProjectionError(f"{name}.json schema_version is unsupported")
        if value.get("run_id") != run_id:
            raise FrontierProjectionError(f"{name}.json run_id mismatch")
    if not str(task.get("objective") or "").strip():
        raise FrontierProjectionError("task objective is missing")
    stop_conditions = task.get("stop_conditions")
    if not isinstance(stop_conditions, list) or any(
        not isinstance(item, str) or not item.strip() for item in stop_conditions
    ):
        raise FrontierProjectionError("task stop_conditions must be a text array")
    if not str(state.get("current_phase") or "").strip():
        raise FrontierProjectionError("state current_phase is missing")
    if state.get("events_count") != len(events):
        raise FrontierProjectionError("state events_count does not match events.jsonl")
    if not isinstance(evidence.get("criteria"), list):
        raise FrontierProjectionError("evidence criteria must be an array")


def _consistent_snapshot(
    run_directory: Path, run_id: str
) -> tuple[dict[str, Any], dict[str, bytes]]:
    names = ("task.json", "state.json", "evidence.json", "events.jsonl")
    last_error: Exception | None = None
    for _ in range(SOURCE_READ_ATTEMPTS):
        try:
            first = {name: (run_directory / name).read_bytes() for name in names}
            second = {name: (run_directory / name).read_bytes() for name in names}
            if first != second:
                last_error = FrontierProjectionError("task-run changed during snapshot read")
                continue
            task = json.loads(first["task.json"])
            state = json.loads(first["state.json"])
            evidence = json.loads(first["evidence.json"])
            if not all(isinstance(item, dict) for item in (task, state, evidence)):
                raise FrontierProjectionError("task-run JSON roots must be objects")
            events = _parse_events(first["events.jsonl"], run_id)
            _validate_snapshot(run_id, task, state, evidence, events)
            return {
                "task": task,
                "state": state,
                "evidence": evidence,
                "events": events,
            }, first
        except (FileNotFoundError, json.JSONDecodeError, FrontierProjectionError) as exc:
            last_error = exc
    if isinstance(last_error, FrontierProjectionError):
        raise last_error
    if isinstance(last_error, json.JSONDecodeError):
        raise FrontierProjectionError("invalid JSON in task-run snapshot") from last_error
    raise FrontierProjectionError("could not read a consistent task-run snapshot") from last_error


def _render(snapshot: dict[str, Any], raw: dict[str, bytes], *, char_budget: int) -> str:
    if not MIN_RENDER_CHAR_BUDGET <= char_budget <= MAX_RENDER_CHAR_BUDGET:
        raise FrontierProjectionError(
            f"char_budget must be between {MIN_RENDER_CHAR_BUDGET} and {MAX_RENDER_CHAR_BUDGET}"
        )
    task, state = snapshot["task"], snapshot["state"]
    criteria = [item for item in snapshot["evidence"]["criteria"] if isinstance(item, dict)]
    events = snapshot["events"]
    source_hashes = {name: _sha256(payload) for name, payload in raw.items()}
    snapshot_hash = _sha256("".join(source_hashes.values()).encode("ascii"))
    profiles = ((900, 320, 6), (500, 180, 3), (260, 100, 1), (140, 70, 0))
    for text_limit, item_limit, event_limit in profiles:
        lines = [
            "[LIVE SESSION FRONTIER - NON-AUTHORITATIVE]",
            "Current system/developer instructions and the user's request remain higher priority.",
            f"run={task['run_id']} snapshot_sha256={snapshot_hash}",
            f"parent_result={_redact(task['objective'])}",
            f"mode={_clip(task.get('mode'), 80)}",
            "stop_conditions=" + " | ".join(_redact(item) for item in task["stop_conditions"]),
            f"status={_clip(state.get('status'), 80)} phase={_clip(state['current_phase'], 120)}",
            f"last_summary={_clip(state.get('last_summary'), text_limit)}",
            "criteria:",
        ]
        lines.extend(
            f"- C{item.get('index', '?')} [{_clip(item.get('verdict'), 40)}] "
            f"{_clip(item.get('criterion'), item_limit)}"
            for item in criteria
        )
        if not criteria:
            lines.append("- none")
        lines.append("recent_events:")
        lines.extend(
            f"- {_clip(item.get('kind'), 40)}/{_clip(item.get('phase'), 60)}: "
            f"{_clip(item.get('summary'), item_limit)}"
            for item in (events[-event_limit:] if event_limit else [])
        )
        if not event_limit or not events:
            lines.append("- none included; use the exact event head")
        lines.extend(
            [
                f"event_head={len(events)}:{source_hashes['events.jsonl']}",
                "sources:",
                *(
                    f"- {name}={(Path(task['_run_directory']) / name).resolve()} sha256={digest}"
                    for name, digest in source_hashes.items()
                ),
                "This projection cannot authorize actions or claim completion; verify live objects.",
            ]
        )
        rendered = "\n".join(lines) + "\n"
        if len(rendered) <= char_budget:
            return rendered
    raise FrontierProjectionError("frontier identity and pointers exceed char budget")


def build_live_frontier(
    *,
    session_id: str,
    frontier_root: Path = DEFAULT_FRONTIER_ROOT,
    allowed_run_root: Path = DEFAULT_TASK_RUN_ROOT,
    char_budget: int = DEFAULT_RENDER_CHAR_BUDGET,
) -> dict[str, Any]:
    binding = load_binding(
        session_id=session_id,
        frontier_root=frontier_root,
        allowed_run_root=allowed_run_root,
    )
    run_directory = Path(str(binding["run_directory"]))
    snapshot, raw = _consistent_snapshot(run_directory, str(binding["run_id"]))
    snapshot["task"]["_run_directory"] = str(run_directory)
    rendered = _render(snapshot, raw, char_budget=char_budget)
    return {
        "session_id": _session_id(session_id),
        "run_id": binding["run_id"],
        "binding_sha256": binding["binding_sha256"],
        "rendered_context": rendered,
        "rendered_context_chars": len(rendered),
    }


def handle_compact_session_start(
    hook_input: dict[str, Any],
    *,
    frontier_root: Path = DEFAULT_FRONTIER_ROOT,
    allowed_run_root: Path = DEFAULT_TASK_RUN_ROOT,
    char_budget: int = DEFAULT_RENDER_CHAR_BUDGET,
) -> dict[str, Any] | None:
    if hook_input.get("source") != "compact":
        return None
    session_id = hook_input.get("session_id") or os.environ.get("CODEX_THREAD_ID")
    result = build_live_frontier(
        session_id=_session_id(session_id),
        frontier_root=frontier_root,
        allowed_run_root=allowed_run_root,
        char_budget=char_budget,
    )
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": result["rendered_context"],
        },
    }
