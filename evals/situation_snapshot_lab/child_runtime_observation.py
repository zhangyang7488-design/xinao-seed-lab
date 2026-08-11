"""Read-only observation of one isolated Codex child rollout.

This candidate-only observer treats the rollout JSONL as the sole fact source.
It does not inspect invocation arguments or model text, and it is not registered
with a launcher, hook, profile, runner, or production runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

CHILD_RUNTIME_OBSERVATION_VERSION = "codex.situation_snapshot.child_runtime.v1"
UNKNOWN = "UNKNOWN"

_MAX_THREAD_ID_CHARS = 256
_MAX_OBSERVED_OBJECT_BYTES = 256 * 1024
_SANDBOX_POLICY_TYPES = frozenset(
    {
        "danger-full-access",
        "read-only",
        "workspace-write",
    }
)
_PERMISSION_PROFILE_TYPES = frozenset({"disabled", "managed"})


class ChildRuntimeObservationError(ValueError):
    """The requested rollout cannot support a reliable observation."""


class ThreadRolloutNotFoundError(ChildRuntimeObservationError):
    """No rollout has a session identity equal to the requested thread."""


class MultipleThreadRolloutsError(ChildRuntimeObservationError):
    """More than one rollout claims the requested thread identity."""


class ThreadIdentityMismatchError(ChildRuntimeObservationError):
    """A target-named rollout records a different mechanical thread identity."""


class InvalidRolloutError(ChildRuntimeObservationError):
    """The selected rollout is not valid, stable JSONL."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class ChildRuntimeObservation:
    """Immutable, non-authoritative projection of one rollout's recorded turns."""

    thread_id: str
    observed: Mapping[str, object]
    turn_contexts: Sequence[Mapping[str, object]]
    rollout: Mapping[str, object]
    unknown: Sequence[Mapping[str, str]]
    schema_version: str = field(default=CHILD_RUNTIME_OBSERVATION_VERSION, init=False)
    candidate_only: bool = field(default=True, init=False)
    authority: bool = field(default=False, init=False)
    completion_claim_allowed: bool = field(default=False, init=False)
    production_registered: bool = field(default=False, init=False)
    model_text_used_as_truth: bool = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON-compatible value."""

        return {
            "schema_version": self.schema_version,
            "thread_id": self.thread_id,
            "observed": _thaw(self.observed),
            "turn_contexts": _thaw(self.turn_contexts),
            "rollout": _thaw(self.rollout),
            "unknown": _thaw(self.unknown),
            "candidate_only": self.candidate_only,
            "authority": self.authority,
            "completion_claim_allowed": self.completion_claim_allowed,
            "production_registered": self.production_registered,
            "model_text_used_as_truth": self.model_text_used_as_truth,
        }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json_line(raw: bytes, *, relative_path: str, line_number: int) -> Mapping[str, object]:
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidRolloutError(
            f"invalid rollout JSON at {relative_path}:{line_number}"
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidRolloutError(
            f"rollout row must be an object at {relative_path}:{line_number}"
        )
    return value


def _validated_home(codex_home: str | os.PathLike[str]) -> tuple[Path, Path]:
    raw_home = Path(os.fspath(codex_home))
    if not raw_home.is_absolute():
        raise ChildRuntimeObservationError("codex_home must be an absolute path")
    home = Path(os.path.abspath(os.fspath(raw_home)))
    if not home.is_dir():
        raise ChildRuntimeObservationError("codex_home must be an existing directory")
    sessions = home / "sessions"
    if not sessions.is_dir() or sessions.is_symlink():
        raise ChildRuntimeObservationError("codex_home/sessions must be a local directory")
    return home, sessions


def _validated_thread_id(thread_id: str) -> str:
    if (
        not isinstance(thread_id, str)
        or not thread_id
        or len(thread_id) > _MAX_THREAD_ID_CHARS
        or thread_id in {".", ".."}
        or any(character in thread_id for character in ("/", "\\", "\x00", "\r", "\n"))
    ):
        raise ChildRuntimeObservationError("thread_id must be a bounded exact identity")
    return thread_id


def _relative_path(path: Path, sessions: Path) -> str:
    return path.relative_to(sessions).as_posix()


def _session_meta_id(path: Path, sessions: Path) -> str:
    relative = _relative_path(path, sessions)
    try:
        with path.open("rb") as stream:
            raw = stream.readline()
    except OSError as exc:
        raise InvalidRolloutError(f"could not read rollout: {relative}") from exc
    if not raw:
        raise InvalidRolloutError(f"empty rollout: {relative}")
    row = _parse_json_line(raw, relative_path=relative, line_number=1)
    payload = row.get("payload")
    if row.get("type") != "session_meta" or not isinstance(payload, Mapping):
        raise InvalidRolloutError(f"first rollout row is not session_meta: {relative}")
    observed_id = payload.get("id")
    if not isinstance(observed_id, str) or not observed_id:
        raise InvalidRolloutError(f"session_meta.id is missing or invalid: {relative}")
    return observed_id


def _locate_rollout(sessions: Path, thread_id: str) -> Path:
    matches: list[Path] = []
    target_named_mismatches: list[tuple[Path, str]] = []
    target_named_invalid: list[InvalidRolloutError] = []
    sessions_resolved = sessions.resolve(strict=True)

    for path in sorted(sessions.rglob("*.jsonl"), key=lambda item: item.as_posix()):
        relative = _relative_path(path, sessions)
        target_named = path.name.endswith(f"-{thread_id}.jsonl")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(sessions_resolved)
        except (OSError, RuntimeError, ValueError):
            if target_named:
                target_named_invalid.append(
                    InvalidRolloutError(f"target-named rollout escapes sessions: {relative}")
                )
            continue
        if path.is_symlink() or not resolved.is_file():
            if target_named:
                target_named_invalid.append(
                    InvalidRolloutError(f"target-named rollout is not a local file: {relative}")
                )
            continue
        try:
            observed_id = _session_meta_id(path, sessions)
        except InvalidRolloutError as exc:
            if target_named:
                target_named_invalid.append(exc)
            continue
        if observed_id == thread_id:
            matches.append(path)
        elif target_named:
            target_named_mismatches.append((path, observed_id))

    if len(matches) > 1:
        paths = ", ".join(_relative_path(path, sessions) for path in matches)
        raise MultipleThreadRolloutsError(
            f"multiple rollouts claim thread {thread_id}: {paths}"
        )
    if len(matches) == 1:
        return matches[0]
    if target_named_invalid:
        raise target_named_invalid[0]
    if target_named_mismatches:
        path, observed_id = target_named_mismatches[0]
        raise ThreadIdentityMismatchError(
            "target-named rollout session_meta.id does not match requested thread: "
            f"{_relative_path(path, sessions)} records {observed_id}"
        )
    raise ThreadRolloutNotFoundError(f"no rollout records exact thread {thread_id}")


def _safe_text(value: object) -> str | None:
    if not isinstance(value, str) or not value or any(ord(character) < 32 for character in value):
        return None
    return value


def _safe_path_text(value: object) -> str | None:
    text = _safe_text(value)
    return text if text is not None and os.path.isabs(text) else None


def _safe_object(value: object, *, allowed_types: frozenset[str]) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    policy_type = value.get("type")
    if not isinstance(policy_type, str) or policy_type not in allowed_types:
        return None
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > _MAX_OBSERVED_OBJECT_BYTES:
            return None
        decoded = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _safe_sandbox_policy(value: object) -> dict[str, object] | None:
    policy = _safe_object(value, allowed_types=_SANDBOX_POLICY_TYPES)
    if policy is None:
        return None
    if policy["type"] != "workspace-write":
        return policy
    writable_roots = policy.get("writable_roots")
    if not isinstance(writable_roots, list) or any(
        _safe_text(root) is None or not os.path.isabs(root)
        for root in writable_roots
    ):
        return None
    for field_name in (
        "network_access",
        "exclude_tmpdir_env_var",
        "exclude_slash_tmp",
    ):
        if not isinstance(policy.get(field_name), bool):
            return None
    return policy


def _safe_permission_profile(value: object) -> dict[str, object] | None:
    profile = _safe_object(value, allowed_types=_PERMISSION_PROFILE_TYPES)
    if profile is None or profile["type"] == "disabled":
        return profile
    file_system = profile.get("file_system")
    network = profile.get("network")
    if (
        not isinstance(file_system, Mapping)
        or file_system.get("type") != "restricted"
        or not isinstance(file_system.get("entries"), list)
        or _safe_text(network) is None
    ):
        return None
    for entry in file_system["entries"]:
        if not isinstance(entry, Mapping) or entry.get("access") not in {"read", "write"}:
            return None
        path = entry.get("path")
        if not isinstance(path, Mapping):
            return None
        if path.get("type") == "path":
            path_text = _safe_text(path.get("path"))
            if path_text is None or not os.path.isabs(path_text):
                return None
        elif path.get("type") == "special":
            value = path.get("value")
            if not isinstance(value, Mapping) or _safe_text(value.get("kind")) is None:
                return None
        else:
            return None
        missing_path_behavior = entry.get("missing_path_behavior")
        if missing_path_behavior is not None and _safe_text(missing_path_behavior) is None:
            return None
    return profile


def _same_path(first: str, second: str) -> bool:
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(second))


def _cross_checked_text(
    field_name: str,
    turn_context: Mapping[str, object] | None,
    turn_key: str,
    thread_settings: Mapping[str, object] | None,
    settings_key: str,
    unknown: list[dict[str, str]],
    *,
    path_value: bool = False,
) -> object:
    validator = _safe_path_text if path_value else _safe_text
    turn_value = validator(turn_context.get(turn_key)) if turn_context is not None else None
    settings_value = (
        validator(thread_settings.get(settings_key)) if thread_settings is not None else None
    )
    if turn_value is None:
        unknown.append({"field": field_name, "reason": "missing_or_invalid_turn_context"})
        return UNKNOWN
    if settings_value is None:
        unknown.append(
            {"field": field_name, "reason": "missing_or_invalid_thread_settings_applied"}
        )
        return UNKNOWN
    equal = _same_path(turn_value, settings_value) if path_value else turn_value == settings_value
    if not equal:
        unknown.append({"field": field_name, "reason": "mechanical_sources_disagree"})
        return UNKNOWN
    return turn_value


def _cross_checked_permission_profile(
    turn_context: Mapping[str, object] | None,
    thread_settings: Mapping[str, object] | None,
    unknown: list[dict[str, str]],
) -> object:
    turn_value = (
        _safe_permission_profile(turn_context.get("permission_profile"))
        if turn_context is not None
        else None
    )
    settings_value = (
        _safe_permission_profile(thread_settings.get("permission_profile"))
        if thread_settings is not None
        else None
    )
    if turn_value is None:
        unknown.append(
            {"field": "permission_profile", "reason": "missing_or_invalid_turn_context"}
        )
        return UNKNOWN
    if settings_value is None:
        unknown.append(
            {
                "field": "permission_profile",
                "reason": "missing_or_invalid_thread_settings_applied",
            }
        )
        return UNKNOWN
    if turn_value != settings_value:
        unknown.append(
            {"field": "permission_profile", "reason": "mechanical_sources_disagree"}
        )
        return UNKNOWN
    return turn_value


def _observed_fields(
    turn_context: Mapping[str, object] | None,
    thread_settings: Mapping[str, object] | None,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    unknown: list[dict[str, str]] = []
    observed: dict[str, object] = {
        "cwd": _cross_checked_text(
            "cwd",
            turn_context,
            "cwd",
            thread_settings,
            "cwd",
            unknown,
            path_value=True,
        ),
        "model": _cross_checked_text(
            "model", turn_context, "model", thread_settings, "model", unknown
        ),
        "effort": _cross_checked_text(
            "effort",
            turn_context,
            "effort",
            thread_settings,
            "reasoning_effort",
            unknown,
        ),
        "approval_policy": _cross_checked_text(
            "approval_policy",
            turn_context,
            "approval_policy",
            thread_settings,
            "approval_policy",
            unknown,
        ),
    }
    sandbox_policy = (
        _safe_sandbox_policy(turn_context.get("sandbox_policy"))
        if turn_context is not None
        else None
    )
    if sandbox_policy is None:
        observed["sandbox_policy"] = UNKNOWN
        unknown.append(
            {"field": "sandbox_policy", "reason": "missing_or_invalid_turn_context"}
        )
    else:
        observed["sandbox_policy"] = sandbox_policy
    observed["permission_profile"] = _cross_checked_permission_profile(
        turn_context,
        thread_settings,
        unknown,
    )
    return observed, unknown


def _single_source_fields(
    turn_context: Mapping[str, object] | None,
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Validate one mechanical turn_context without implying corroboration."""

    unknown: list[dict[str, str]] = []
    observed: dict[str, object] = {}
    for field_name in ("cwd", "model", "effort", "approval_policy"):
        validator = _safe_path_text if field_name == "cwd" else _safe_text
        value = validator(turn_context.get(field_name)) if turn_context is not None else None
        if value is None:
            observed[field_name] = UNKNOWN
            unknown.append(
                {"field": field_name, "reason": "missing_or_invalid_turn_context"}
            )
        else:
            observed[field_name] = value

    sandbox_policy = (
        _safe_sandbox_policy(turn_context.get("sandbox_policy"))
        if turn_context is not None
        else None
    )
    if sandbox_policy is None:
        observed["sandbox_policy"] = UNKNOWN
        unknown.append(
            {"field": "sandbox_policy", "reason": "missing_or_invalid_turn_context"}
        )
    else:
        observed["sandbox_policy"] = sandbox_policy

    permission_profile = (
        _safe_permission_profile(turn_context.get("permission_profile"))
        if turn_context is not None
        else None
    )
    if permission_profile is None:
        observed["permission_profile"] = UNKNOWN
        unknown.append(
            {"field": "permission_profile", "reason": "missing_or_invalid_turn_context"}
        )
    else:
        observed["permission_profile"] = permission_profile
    return observed, unknown


def _turn_context_projection(
    *,
    index: int,
    line_number: int,
    turn_context: Mapping[str, object] | None,
    preceding_settings_line: int | None,
    preceding_settings: Mapping[str, object] | None,
) -> dict[str, object]:
    overlap_fields = ("cwd", "model", "effort", "approval_policy", "permission_profile")
    if preceding_settings_line is None:
        observed, unknown = _single_source_fields(turn_context)
        unknown.append(
            {
                "field": "thread_settings_applied",
                "reason": "not_available_before_turn_context",
            }
        )
        cross_check: dict[str, object] = {
            "status": "single_source",
            "thread_settings_applied": "not_available",
            "thread_settings_line_number": None,
            "compared_fields": [],
            "disagreement_fields": [],
        }
    else:
        observed, unknown = _observed_fields(turn_context, preceding_settings)
        disagreement_fields = [
            field_name for field_name in overlap_fields if observed[field_name] == UNKNOWN
        ]
        cross_check = {
            "status": "disagreement" if disagreement_fields else "match",
            "thread_settings_applied": "available",
            "thread_settings_line_number": preceding_settings_line,
            "compared_fields": list(overlap_fields),
            "disagreement_fields": disagreement_fields,
        }
    return {
        "index": index,
        "line_number": line_number,
        "observed": observed,
        "cross_check": cross_check,
        "unknown": unknown,
    }


def _read_selected_rollout(
    path: Path,
    sessions: Path,
    thread_id: str,
) -> ChildRuntimeObservation:
    relative = _relative_path(path, sessions)
    digest = hashlib.sha256()
    total_bytes = 0
    session_meta_count = 0
    turn_context_count = 0
    last_turn_context: Mapping[str, object] | None = None
    preceding_settings_line: int | None = None
    preceding_settings: Mapping[str, object] | None = None
    last_context_settings: Mapping[str, object] | None = None
    turn_contexts: list[dict[str, object]] = []

    try:
        before = path.stat()
        with path.open("rb") as stream:
            for line_number, raw in enumerate(stream, start=1):
                digest.update(raw)
                total_bytes += len(raw)
                row = _parse_json_line(raw, relative_path=relative, line_number=line_number)
                row_type = row.get("type")
                payload = row.get("payload")
                if row_type == "session_meta":
                    session_meta_count += 1
                    if not isinstance(payload, Mapping) or payload.get("id") != thread_id:
                        raise ThreadIdentityMismatchError(
                            f"rollout session_meta.id changed or mismatched: {relative}"
                        )
                elif row_type == "turn_context":
                    turn_context_count += 1
                    last_turn_context = payload if isinstance(payload, Mapping) else None
                    last_context_settings = preceding_settings
                    turn_contexts.append(
                        _turn_context_projection(
                            index=turn_context_count,
                            line_number=line_number,
                            turn_context=last_turn_context,
                            preceding_settings_line=preceding_settings_line,
                            preceding_settings=preceding_settings,
                        )
                    )
                elif (
                    row_type == "event_msg"
                    and isinstance(payload, Mapping)
                    and payload.get("type") == "thread_settings_applied"
                ):
                    settings = payload.get("thread_settings")
                    preceding_settings_line = line_number
                    preceding_settings = settings if isinstance(settings, Mapping) else None
        after = path.stat()
    except ChildRuntimeObservationError:
        raise
    except OSError as exc:
        raise InvalidRolloutError(f"could not read selected rollout: {relative}") from exc

    if session_meta_count != 1:
        raise InvalidRolloutError(
            f"selected rollout must contain exactly one session_meta: {relative}"
        )
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or total_bytes != after.st_size
    ):
        raise InvalidRolloutError(f"selected rollout changed while observed: {relative}")

    observed, unknown = _observed_fields(last_turn_context, last_context_settings)
    return ChildRuntimeObservation(
        thread_id=thread_id,
        observed=_freeze(observed),
        turn_contexts=_freeze(turn_contexts),
        rollout=_freeze(
            {
                "relative_path": relative,
                "sha256": digest.hexdigest(),
                "bytes": total_bytes,
                "turn_context_count": turn_context_count,
            }
        ),
        unknown=_freeze(unknown),
    )


def collect_child_runtime_observation(
    *,
    codex_home: str | os.PathLike[str],
    thread_id: str,
) -> ChildRuntimeObservation:
    """Observe one exact child thread from its isolated ``CODEX_HOME``.

    Only ``sessions/**/*.jsonl`` is read.  A unique ``session_meta.payload.id``
    selects the rollout; the last mechanical ``turn_context`` and nested
    ``thread_settings_applied`` records provide the candidate runtime facts.
    """

    _, sessions = _validated_home(codex_home)
    exact_thread_id = _validated_thread_id(thread_id)
    rollout = _locate_rollout(sessions, exact_thread_id)
    return _read_selected_rollout(rollout, sessions, exact_thread_id)
