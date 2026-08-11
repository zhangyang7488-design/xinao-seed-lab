"""Unregistered candidate Codex ``exec`` transport for Situation Snapshot Lab.

This module deliberately stops at one subprocess transport boundary.  It does
not establish runtime isolation, install hooks, register a controller, create
authentication, or promote an agent message into a runtime fact.  Callers must
prepare an ``auth.json`` symlink and name its expected source; the driver only
detects its pre/post identity and cannot prevent an in-flight mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

RECEIPT_SCHEMA_VERSION = "codex.situation_snapshot_lab.exec_receipt.v1"
DRIVER_SCOPE = "unregistered_candidate_transport"

# These disable inherited, non-local behavior surfaces while retaining the
# ordinary shell/edit surface needed by action-fidelity lab cases.  A caller
# may replace this complete tuple for a specific sealed arm.
DEFAULT_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "plugins",
    "recommended_plugins",
    "remote_plugin",
    "skill_mcp_dependency_install",
    "skill_search",
)

_KNOWN_EVENT_TYPES = frozenset(
    {
        "thread.started",
        "turn.started",
        "turn.completed",
        "turn.failed",
        "item.started",
        "item.updated",
        "item.completed",
        "error",
    }
)
_NON_TOOL_ITEM_TYPES = frozenset({"agent_message", "reasoning", "plan", "plan_update"})
_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SANDBOX_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})
_APPROVAL_POLICIES = frozenset({"untrusted", "on-request", "never"})
_MODEL_REASONING_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})
_HASH_CHUNK_BYTES = 1024 * 1024
_CHILD_ENV_REMOVED_KEYS = (
    "CODEX_API_KEY",
    "CODEX_MANAGED_BY_NPM",
    "CODEX_MANAGED_PACKAGE_ROOT",
    "CODEX_THREAD_ID",
    "OPENAI_API_KEY",
)


class CodexExecDriverError(ValueError):
    """A pre-invocation boundary or event stream is invalid."""


class AuthLinkError(CodexExecDriverError):
    """The caller-prepared authentication link is absent or has drifted."""


class LabPathBoundaryError(CodexExecDriverError):
    """A requested runtime path escapes its caller-declared lab root."""


class CodexEventError(CodexExecDriverError):
    """Codex stdout is not the pinned JSONL event shape."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _safe_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        raise CodexExecDriverError(f"{field_name} must be non-empty printable text")
    return value


def _prompt_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CodexExecDriverError("prompt must be non-empty UTF-8 text")
    if "\x00" in value:
        raise CodexExecDriverError("prompt must not contain NUL")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CodexExecDriverError("prompt must be valid UTF-8 text") from exc
    return value


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


@dataclass(frozen=True)
class CodexExecConfig:
    """Explicit invocation identity shared by first and resume calls."""

    codex_executable: str
    codex_home: Path
    cwd: Path
    model: str
    auth_target: Path
    allowed_lab_root: Path
    sandbox_mode: str = "read-only"
    approval_policy: str = "never"
    model_reasoning_effort: str = "max"
    disabled_features: tuple[str, ...] = DEFAULT_DISABLED_FEATURES
    ignore_user_config: bool = True
    ignore_rules: bool = True
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        executable = _safe_text(self.codex_executable, field_name="codex_executable")
        if Path(executable).suffix.lower() != ".exe":
            raise CodexExecDriverError(
                "codex_executable must name a direct native .exe, not an npm wrapper"
            )
        model = _safe_text(self.model, field_name="model")
        sandbox_mode = _safe_text(self.sandbox_mode, field_name="sandbox_mode")
        approval_policy = _safe_text(self.approval_policy, field_name="approval_policy")
        model_reasoning_effort = _safe_text(
            self.model_reasoning_effort,
            field_name="model_reasoning_effort",
        )
        home = _absolute_path(self.codex_home)
        cwd = _absolute_path(self.cwd)
        auth_target = _absolute_path(self.auth_target)
        allowed_lab_root = _absolute_path(self.allowed_lab_root)
        features = tuple(self.disabled_features)
        if len(features) != len(set(features)):
            raise CodexExecDriverError("disabled_features must not contain duplicates")
        if any(not isinstance(feature, str) or not _FEATURE_RE.fullmatch(feature) for feature in features):
            raise CodexExecDriverError("disabled_features contains an invalid feature name")
        if sandbox_mode not in _SANDBOX_MODES:
            raise CodexExecDriverError("sandbox_mode is not supported by this lab driver")
        if approval_policy not in _APPROVAL_POLICIES:
            raise CodexExecDriverError("approval_policy is not supported by this lab driver")
        if model_reasoning_effort not in _MODEL_REASONING_EFFORTS:
            raise CodexExecDriverError(
                "model_reasoning_effort is not supported by this lab driver"
            )
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise CodexExecDriverError("timeout_seconds must be a positive number")
        if self.timeout_seconds <= 0:
            raise CodexExecDriverError("timeout_seconds must be a positive number")
        if not isinstance(self.ignore_user_config, bool) or not isinstance(self.ignore_rules, bool):
            raise CodexExecDriverError("ignore flags must be booleans")
        object.__setattr__(self, "codex_executable", executable)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "sandbox_mode", sandbox_mode)
        object.__setattr__(self, "approval_policy", approval_policy)
        object.__setattr__(self, "model_reasoning_effort", model_reasoning_effort)
        object.__setattr__(self, "codex_home", home)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "auth_target", auth_target)
        object.__setattr__(self, "allowed_lab_root", allowed_lab_root)
        object.__setattr__(self, "disabled_features", features)
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))


@dataclass(frozen=True)
class AuthLinkSnapshot:
    link_path: str
    link_target: str
    source_target: str
    source_sha256: str
    source_bytes: int


@dataclass(frozen=True)
class LabPathBoundarySnapshot:
    allowed_root: str
    codex_home_resolved: str
    cwd_resolved: str


@dataclass(frozen=True)
class ParsedCodexEvents:
    """Immutable projections of the exact JSONL stream."""

    thread_id: str
    events: tuple[Mapping[str, object], ...]
    turn_trace: tuple[Mapping[str, object], ...]
    item_trace: tuple[Mapping[str, object], ...]
    tool_trace: tuple[Mapping[str, object], ...]
    event_types: tuple[str, ...]
    final_agent_text: str | None
    terminal_usage: Mapping[str, object] | None
    turn_completed: bool
    turn_failed: bool
    error_seen: bool


@dataclass(frozen=True)
class CodexExecResult:
    """One invocation result; raw bytes stay separate from its safe receipt."""

    receipt: Mapping[str, object]
    raw_jsonl: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    parsed: ParsedCodexEvents | None = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.receipt.get("status") == "completed"

    @property
    def final_agent_text(self) -> str | None:
        return self.parsed.final_agent_text if self.parsed is not None else None

    def receipt_dict(self) -> dict[str, object]:
        """Return a detached JSON-compatible copy of the immutable receipt."""

        return _thaw(self.receipt)


def _hash_regular_file(path: Path) -> tuple[str, int]:
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise AuthLinkError("auth source target must be a regular file")
            digest = hashlib.sha256()
            byte_count = 0
            for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
                byte_count += len(chunk)
            finished = os.fstat(handle.fileno())
    except AuthLinkError:
        raise
    except OSError as exc:
        raise AuthLinkError("auth source target is not stably readable") from exc
    if (
        not stat.S_ISREG(finished.st_mode)
        or byte_count != finished.st_size
        or opened.st_size != finished.st_size
        or getattr(opened, "st_mtime_ns", None) != getattr(finished, "st_mtime_ns", None)
    ):
        raise AuthLinkError("auth source target changed while it was hashed")
    return digest.hexdigest(), byte_count


def inspect_auth_link(config: CodexExecConfig) -> AuthLinkSnapshot:
    """Snapshot, but never create or repair, the caller-prepared auth symlink."""

    auth_link = config.codex_home / "auth.json"
    try:
        lexical = auth_link.lstat()
    except OSError as exc:
        raise AuthLinkError("caller-prepared auth.json link is missing") from exc
    if not stat.S_ISLNK(lexical.st_mode):
        raise AuthLinkError("caller-prepared auth.json must be a symbolic link")
    try:
        raw_link_target = os.readlink(auth_link)
        resolved_target = auth_link.resolve(strict=True)
        expected_target = config.auth_target.resolve(strict=True)
        same_target = os.path.samefile(resolved_target, expected_target)
    except OSError as exc:
        raise AuthLinkError("caller-prepared auth.json link target is invalid") from exc
    if not same_target:
        raise AuthLinkError("caller-prepared auth.json points at an unexpected source")
    source_sha256, source_bytes = _hash_regular_file(expected_target)
    return AuthLinkSnapshot(
        link_path=str(auth_link),
        link_target=os.fspath(raw_link_target),
        source_target=str(expected_target),
        source_sha256=source_sha256,
        source_bytes=source_bytes,
    )


def inspect_lab_path_boundary(config: CodexExecConfig) -> LabPathBoundarySnapshot:
    """Require runtime paths to resolve strictly below a caller-declared root.

    This is a mechanical containment check, not evidence that the root is an
    isolated environment or semantically safe lab.
    """

    try:
        allowed_root = config.allowed_lab_root.resolve(strict=True)
        codex_home = config.codex_home.resolve(strict=True)
        cwd = config.cwd.resolve(strict=True)
    except OSError as exc:
        raise LabPathBoundaryError("lab root, codex_home, and cwd must already exist") from exc
    if not allowed_root.is_dir() or not codex_home.is_dir() or not cwd.is_dir():
        raise LabPathBoundaryError("lab root, codex_home, and cwd must be directories")
    if allowed_root.parent == allowed_root:
        raise LabPathBoundaryError("allowed_lab_root cannot be a filesystem root")
    for field_name, candidate in (("codex_home", codex_home), ("cwd", cwd)):
        try:
            relative = candidate.relative_to(allowed_root)
        except ValueError as exc:
            raise LabPathBoundaryError(
                f"{field_name} escapes caller-declared allowed_lab_root"
            ) from exc
        if not relative.parts:
            raise LabPathBoundaryError(
                f"{field_name} must be strictly below caller-declared allowed_lab_root"
            )
    if codex_home == cwd:
        raise LabPathBoundaryError("codex_home and cwd must be distinct lab paths")
    return LabPathBoundarySnapshot(
        allowed_root=str(allowed_root),
        codex_home_resolved=str(codex_home),
        cwd_resolved=str(cwd),
    )


def _common_argv(config: CodexExecConfig) -> list[str]:
    arguments = [
        "--json",
        "--strict-config",
        "-m",
        config.model,
        "-c",
        f'sandbox_mode="{config.sandbox_mode}"',
        "-c",
        f'approval_policy="{config.approval_policy}"',
        "-c",
        f'model_reasoning_effort="{config.model_reasoning_effort}"',
    ]
    if config.ignore_user_config:
        arguments.append("--ignore-user-config")
    if config.ignore_rules:
        arguments.append("--ignore-rules")
    for feature in config.disabled_features:
        arguments.extend(("--disable", feature))
    return arguments


def build_first_argv(config: CodexExecConfig) -> list[str]:
    """Build a prompt-via-stdin ``codex exec --json`` argument list."""

    return [
        config.codex_executable,
        "exec",
        *_common_argv(config),
        "--sandbox",
        config.sandbox_mode,
        "-C",
        str(config.cwd),
        "-",
    ]


def build_resume_argv(config: CodexExecConfig, thread_id: str) -> list[str]:
    """Build a 0.147 ``codex exec resume --json`` argument list.

    Codex 0.147's resume parser has no ``-C`` option.  ``invoke_resume`` still
    binds the same explicit cwd at the subprocess boundary.
    """

    identity = _safe_text(thread_id, field_name="thread_id")
    if identity == "-":
        raise CodexExecDriverError("thread_id cannot be the stdin sentinel")
    return [
        config.codex_executable,
        "exec",
        "resume",
        *_common_argv(config),
        identity,
        "-",
    ]


def _event_projection(event: Mapping[str, object], names: Sequence[str]) -> dict[str, object]:
    return {name: event[name] for name in names if name in event}


def _item_projection(event_type: str, item: Mapping[str, object]) -> dict[str, object]:
    projection: dict[str, object] = {
        "event_type": event_type,
        "item_id": item["id"],
        "item_type": item["type"],
    }
    for key in ("status", "name", "tool_name", "server"):
        if key in item:
            projection[key] = item[key]
    return projection


def parse_codex_jsonl(
    raw_jsonl: bytes | str,
    *,
    require_final_agent_text: bool = True,
) -> ParsedCodexEvents:
    """Parse the pinned 0.147 event surface without interpreting agent claims."""

    if isinstance(raw_jsonl, bytes):
        try:
            text = raw_jsonl.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise CodexEventError("Codex JSONL must be UTF-8") from exc
    elif isinstance(raw_jsonl, str):
        text = raw_jsonl
    else:
        raise TypeError("raw_jsonl must be bytes or str")

    events: list[Mapping[str, object]] = []
    turn_trace: list[Mapping[str, object]] = []
    item_trace: list[Mapping[str, object]] = []
    tool_trace: list[Mapping[str, object]] = []
    event_types: list[str] = []
    thread_id: str | None = None
    turn_started = False
    terminal_turn: str | None = None
    started_items: dict[str, str] = {}
    completed_items: set[str] = set()
    final_agent_text: str | None = None
    terminal_usage: Mapping[str, object] | None = None
    turn_completed = False
    turn_failed = False
    error_seen = False

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexEventError(f"line {line_number} is not valid JSON") from exc
        if not isinstance(event, dict):
            raise CodexEventError(f"line {line_number} event must be an object")
        event_type = event.get("type")
        if not isinstance(event_type, str) or event_type not in _KNOWN_EVENT_TYPES:
            raise CodexEventError(f"line {line_number} has an unsupported event type")
        if event_type == "thread.started":
            if events or thread_id is not None:
                raise CodexEventError("thread.started must be the unique first event")
            observed_thread_id = event.get("thread_id")
            if not isinstance(observed_thread_id, str) or not observed_thread_id:
                raise CodexEventError("thread.started requires a thread_id")
            thread_id = observed_thread_id
            event_types.append(event_type)
            events.append(_freeze(event))
            continue

        if thread_id is None:
            raise CodexEventError("thread.started must be the first event")

        if event_type.startswith("turn."):
            if event_type == "turn.started":
                if turn_started or terminal_turn is not None:
                    raise CodexEventError("turn.started must occur exactly once before items")
                turn_started = True
            else:
                if not turn_started:
                    raise CodexEventError("terminal turn requires turn.started")
                if terminal_turn is not None:
                    raise CodexEventError("Codex JSONL must contain exactly one terminal turn")
                incomplete_items = set(started_items) - completed_items
                if incomplete_items:
                    raise CodexEventError("terminal turn has incomplete item lifecycles")
                terminal_turn = event_type
            projection = _event_projection(event, ("type", "turn_id", "status", "usage"))
            turn_trace.append(_freeze(projection))
            if event_type == "turn.completed":
                turn_completed = True
                usage = event.get("usage")
                if usage is not None and not isinstance(usage, dict):
                    raise CodexEventError("turn.completed usage must be an object")
                terminal_usage = _freeze(usage) if isinstance(usage, dict) else None
            elif event_type == "turn.failed":
                turn_failed = True
            event_types.append(event_type)
            events.append(_freeze(event))
            continue

        if event_type.startswith("item."):
            if not turn_started:
                raise CodexEventError("item event requires turn.started")
            if terminal_turn is not None:
                raise CodexEventError("item event cannot occur after terminal turn")
            item = event.get("item")
            if not isinstance(item, dict):
                raise CodexEventError(f"{event_type} requires an item object")
            if not isinstance(item.get("id"), str) or not item["id"]:
                raise CodexEventError(f"{event_type} item requires an id")
            item_type = item.get("type")
            if not isinstance(item_type, str) or not item_type:
                raise CodexEventError(f"{event_type} item requires a type")
            item_id = item["id"]
            if event_type == "item.started":
                if item_id in started_items:
                    raise CodexEventError("item.started cannot repeat an item id")
                started_items[item_id] = item_type
            else:
                if item_id not in started_items:
                    if event_type != "item.completed":
                        raise CodexEventError(f"{event_type} requires a paired item.started")
                    # Codex 0.147 emits completion-only items for agent messages.
                    started_items[item_id] = item_type
                if started_items[item_id] != item_type:
                    raise CodexEventError("item type changed within one item lifecycle")
                if item_id in completed_items:
                    raise CodexEventError("item event cannot follow item.completed")
                if event_type == "item.completed":
                    completed_items.add(item_id)
            projection = _item_projection(event_type, item)
            item_trace.append(_freeze(projection))
            if item_type not in _NON_TOOL_ITEM_TYPES:
                tool_trace.append(_freeze(projection))
            if event_type == "item.completed" and item_type == "agent_message":
                candidate_text = item.get("text")
                if not isinstance(candidate_text, str):
                    raise CodexEventError("completed agent_message requires text")
                final_agent_text = candidate_text
            event_types.append(event_type)
            events.append(_freeze(event))
            continue

        error_seen = True
        event_types.append(event_type)
        events.append(_freeze(event))

    if thread_id is None:
        raise CodexEventError("Codex JSONL did not emit thread.started")
    if not turn_started:
        raise CodexEventError("Codex JSONL did not emit turn.started")
    if terminal_turn is None:
        raise CodexEventError("Codex JSONL did not emit exactly one terminal turn")
    if require_final_agent_text and final_agent_text is None:
        raise CodexEventError("Codex JSONL did not emit a final agent message")
    return ParsedCodexEvents(
        thread_id=thread_id,
        events=tuple(events),
        turn_trace=tuple(turn_trace),
        item_trace=tuple(item_trace),
        tool_trace=tuple(tool_trace),
        event_types=tuple(event_types),
        final_agent_text=final_agent_text,
        terminal_usage=terminal_usage,
        turn_completed=turn_completed,
        turn_failed=turn_failed,
        error_seen=error_seen,
    )


def _output_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _child_environment(config: CodexExecConfig) -> dict[str, str]:
    environment = os.environ.copy()
    for key in _CHILD_ENV_REMOVED_KEYS:
        environment.pop(key, None)
    environment["CODEX_HOME"] = str(config.codex_home)
    environment["NO_COLOR"] = "1"
    return environment


def _post_auth_state(
    config: CodexExecConfig,
    before: AuthLinkSnapshot,
) -> tuple[AuthLinkSnapshot | None, bool, str | None]:
    try:
        after = inspect_auth_link(config)
    except AuthLinkError:
        return None, False, "auth_link_invalid_after_invocation"
    unchanged = (
        after.link_target == before.link_target
        and after.source_target == before.source_target
        and after.source_sha256 == before.source_sha256
        and after.source_bytes == before.source_bytes
    )
    return after, unchanged, None if unchanged else "auth_source_changed"


def _receipt(
    *,
    config: CodexExecConfig,
    mode: str,
    requested_thread_id: str | None,
    argv: Sequence[str],
    prompt: str,
    returncode: int | None,
    execution_error: str | None,
    raw_jsonl: bytes,
    stderr: bytes,
    parsed: ParsedCodexEvents | None,
    parse_error: str | None,
    path_boundary: LabPathBoundarySnapshot,
    auth_before: AuthLinkSnapshot,
    auth_after: AuthLinkSnapshot | None,
    auth_unchanged: bool,
    auth_error: str | None,
) -> Mapping[str, object]:
    if not auth_unchanged:
        status = "auth_integrity_failed"
    elif execution_error is not None:
        status = execution_error
    elif returncode != 0:
        status = "process_failed"
    elif parse_error is not None:
        status = "invalid_jsonl"
    elif parsed is None:
        status = "invalid_jsonl"
    elif mode == "resume" and parsed.thread_id != requested_thread_id:
        status = "thread_identity_mismatch"
    elif parsed.turn_failed or parsed.error_seen:
        status = "turn_failed"
    elif not parsed.turn_completed:
        status = "incomplete_turn"
    elif parsed.final_agent_text is None:
        status = "missing_final_agent_text"
    else:
        status = "completed"

    candidate_text = parsed.final_agent_text if parsed is not None else None
    candidate_bytes = candidate_text.encode("utf-8") if candidate_text is not None else b""
    tool_item_ids = (
        {str(row["item_id"]) for row in parsed.tool_trace}
        if parsed is not None
        else set()
    )
    payload: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "driver_scope": DRIVER_SCOPE,
        "status": status,
        "invoked": True,
        "authority": False,
        "production_registered": False,
        "controller_installed": False,
        "completion_claim_allowed": False,
        "model_output_is_runtime_truth": False,
        "declared_invocation": {
            "mode": mode,
            "codex_executable": config.codex_executable,
            "codex_entrypoint_contract": {
                "kind": "direct_native_executable",
                "npm_wrapper_accepted": False,
                "identity_assurance": "caller_supplied_path_contract_only",
            },
            "codex_home": str(config.codex_home),
            "cwd": str(config.cwd),
            "allowed_lab_root": str(config.allowed_lab_root),
            "allowed_lab_root_source": "caller_supplied",
            "requested_model": config.model,
            "sandbox_mode": config.sandbox_mode,
            "approval_policy": config.approval_policy,
            "model_reasoning_effort": config.model_reasoning_effort,
            "requested_thread_id": requested_thread_id,
            "argv": list(argv),
            "disabled_features": list(config.disabled_features),
            "ignore_user_config": config.ignore_user_config,
            "ignore_rules": config.ignore_rules,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_bytes": len(prompt.encode("utf-8")),
            "child_environment_contract": {
                "removed_inherited_keys": list(_CHILD_ENV_REMOVED_KEYS),
                "codex_home_overridden": True,
            },
        },
        "process_observation": {
            "returncode": returncode,
            "execution_error": execution_error,
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "stderr_bytes": len(stderr),
        },
        "raw_jsonl_sha256": hashlib.sha256(raw_jsonl).hexdigest(),
        "raw_jsonl_bytes": len(raw_jsonl),
        "path_boundary_detection": {
            "assurance": "resolved_path_containment_only",
            "isolation_established": False,
            "allowed_root": path_boundary.allowed_root,
            "codex_home_resolved": path_boundary.codex_home_resolved,
            "cwd_resolved": path_boundary.cwd_resolved,
            "contained": True,
        },
        "auth_pre_post_detection": {
            "assurance": "pre_post_detection_only",
            "credential_model": "shared_live_credential_link",
            "continuous_monitoring": False,
            "mutation_prevention": False,
            "link_path": auth_before.link_path,
            "source_target": auth_before.source_target,
            "source_sha256_before": auth_before.source_sha256,
            "source_bytes_before": auth_before.source_bytes,
            "source_sha256_after": (
                auth_after.source_sha256 if auth_after is not None else None
            ),
            "source_bytes_after": auth_after.source_bytes if auth_after is not None else None,
            "link_verified_before": True,
            "link_verified_after": auth_after is not None,
            "unchanged": auth_unchanged,
            "error": auth_error,
        },
        "trajectory_observation": {
            "parse_error": parse_error,
            "thread_id": parsed.thread_id if parsed is not None else None,
            "thread_identity_matches_request": (
                None
                if mode != "resume" or parsed is None
                else parsed.thread_id == requested_thread_id
            ),
            "event_types": list(parsed.event_types) if parsed is not None else [],
            "event_count": len(parsed.events) if parsed is not None else 0,
            "turn_event_count": len(parsed.turn_trace) if parsed is not None else 0,
            "item_event_count": len(parsed.item_trace) if parsed is not None else 0,
            "tool_event_count": len(parsed.tool_trace) if parsed is not None else 0,
            "tool_item_count": len(tool_item_ids),
            "turn_completed": parsed.turn_completed if parsed is not None else False,
            "turn_failed": parsed.turn_failed if parsed is not None else False,
        },
        "candidate_model_output": {
            "classification": "candidate_only_not_runtime_truth",
            "present": candidate_text is not None,
            "sha256": hashlib.sha256(candidate_bytes).hexdigest() if candidate_text is not None else None,
            "bytes": len(candidate_bytes),
        },
    }
    payload["receipt_sha256"] = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return _freeze(payload)


def _invoke(
    *,
    config: CodexExecConfig,
    prompt: str,
    thread_id: str | None,
) -> CodexExecResult:
    prompt_text = _prompt_text(prompt)
    path_boundary = inspect_lab_path_boundary(config)
    auth_before = inspect_auth_link(config)
    mode = "resume" if thread_id is not None else "first"
    argv = build_resume_argv(config, thread_id) if thread_id is not None else build_first_argv(config)

    raw_jsonl = b""
    stderr = b""
    returncode: int | None = None
    execution_error: str | None = None
    try:
        completed = subprocess.run(
            list(argv),
            input=prompt_text.encode("utf-8"),
            cwd=str(config.cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_environment(config),
            timeout=config.timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        raw_jsonl = _output_bytes(completed.stdout)
        stderr = _output_bytes(completed.stderr)
    except subprocess.TimeoutExpired as exc:
        execution_error = "timeout"
        raw_jsonl = _output_bytes(exc.stdout)
        stderr = _output_bytes(exc.stderr)
    except OSError:
        execution_error = "spawn_failed"

    parsed: ParsedCodexEvents | None = None
    parse_error: str | None = None
    try:
        parsed = parse_codex_jsonl(raw_jsonl, require_final_agent_text=False)
    except (CodexEventError, TypeError):
        parse_error = "invalid_codex_event_stream"

    auth_after, auth_unchanged, auth_error = _post_auth_state(config, auth_before)
    receipt = _receipt(
        config=config,
        mode=mode,
        requested_thread_id=thread_id,
        argv=argv,
        prompt=prompt_text,
        returncode=returncode,
        execution_error=execution_error,
        raw_jsonl=raw_jsonl,
        stderr=stderr,
        parsed=parsed,
        parse_error=parse_error,
        path_boundary=path_boundary,
        auth_before=auth_before,
        auth_after=auth_after,
        auth_unchanged=auth_unchanged,
        auth_error=auth_error,
    )
    return CodexExecResult(
        receipt=receipt,
        raw_jsonl=raw_jsonl,
        stderr=stderr,
        parsed=parsed,
    )


def invoke_first(
    *,
    config: CodexExecConfig,
    prompt: str,
) -> CodexExecResult:
    """Invoke one fresh, non-production ``codex exec --json`` turn."""

    return _invoke(config=config, prompt=prompt, thread_id=None)


def invoke_resume(
    *,
    config: CodexExecConfig,
    thread_id: str,
    prompt: str,
) -> CodexExecResult:
    """Invoke one explicit-thread ``codex exec resume --json`` turn."""

    return _invoke(config=config, prompt=prompt, thread_id=thread_id)
