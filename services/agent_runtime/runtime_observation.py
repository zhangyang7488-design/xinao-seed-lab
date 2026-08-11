"""Deterministic observation of the local probe environment.

The collector measures a deliberately small runtime surface.  Caller assertions
remain under ``declared`` and unproved permissions remain ``unknown``; neither is
promoted into ``observed``.  A consumer may render a bounded subset, but this
module never selects a task, route, authority, or completion state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

RUNTIME_OBSERVATION_VERSION = "codex.situation_snapshot.runtime_observation.v1"

OBSERVED_ENVIRONMENT_ALLOWLIST = frozenset({"CODEX_HOME", "CODEX_THREAD_ID"})
DECLARED_INVOCATION_ALLOWLIST = frozenset(
    {
        "account_slot",
        "approval_policy",
        "cwd",
        "executable",
        "filesystem_access",
        "invocation_id",
        "isolation",
        "model",
        "parent_process_id",
        "permission_mode",
        "process_id",
        "profile",
        "provider",
        "read_capability",
        "result_id",
        "result_identity",
        "sandbox_enforcement",
        "sandbox_mode",
        "thread_id",
        "tool_surface",
        "transport",
        "worker_id",
        "workspace",
        "write_capability",
    }
)

_GIT_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
        "XDG_CONFIG_HOME",
    }
)
_SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:bearer\s+|gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"-----BEGIN .*PRIVATE KEY)",
    re.IGNORECASE,
)
_MAX_DECLARED_TEXT_CHARS = 4_096
_MAX_DECLARED_COLLECTION_ITEMS = 128
_MAX_DECLARED_DEPTH = 4
_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_DIRTY_FINGERPRINT_FILES = 256
_MAX_DIRTY_FINGERPRINT_BYTES = 8 * 1024 * 1024
_MAX_DIRTY_PATH_BYTES = 1024 * 1024


class RuntimeObservationError(ValueError):
    """The caller supplied an invalid observation boundary or declared fact."""


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


def _utc_text(value: datetime | str | None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError as exc:
            raise RuntimeObservationError("captured_at must be an ISO-8601 timestamp") from exc
    else:
        raise RuntimeObservationError("captured_at must be a datetime or ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise RuntimeObservationError("captured_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _positive_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeObservationError(f"{field_name} must be a positive integer")
    return value


def _lexical_absolute(raw: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    path = Path(os.fspath(raw))
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return Path(os.path.abspath(os.fspath(path)))


def _resolved_text(path: Path) -> str | None:
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError):
        return None


def _contains_known_secret(value: str, secret_values: Sequence[str]) -> bool:
    return any(secret in value for secret in secret_values)


def _safe_declared_value(
    value: object,
    *,
    secret_values: Sequence[str],
    depth: int = 0,
) -> object:
    if depth > _MAX_DECLARED_DEPTH:
        raise RuntimeObservationError("declared invocation value exceeds the nesting limit")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeObservationError("declared invocation numbers must be finite")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_DECLARED_TEXT_CHARS or any(ord(character) < 32 for character in value):
            raise RuntimeObservationError("declared invocation text is unsafe or too large")
        if _SECRET_VALUE_RE.search(value.strip()) or _contains_known_secret(value, secret_values):
            raise RuntimeObservationError("declared invocation text resembles a secret")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_DECLARED_COLLECTION_ITEMS:
            raise RuntimeObservationError("declared invocation object is too large")
        normalized: dict[str, object] = {}
        for raw_key in sorted(value, key=lambda item: str(item)):
            if not isinstance(raw_key, str) or not raw_key or _SECRET_KEY_RE.search(raw_key):
                raise RuntimeObservationError("declared invocation object contains an unsafe key")
            normalized[raw_key] = _safe_declared_value(
                value[raw_key],
                secret_values=secret_values,
                depth=depth + 1,
            )
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        if len(value) > _MAX_DECLARED_COLLECTION_ITEMS:
            raise RuntimeObservationError("declared invocation array is too large")
        return [
            _safe_declared_value(
                item,
                secret_values=secret_values,
                depth=depth + 1,
            )
            for item in value
        ]
    raise RuntimeObservationError("declared invocation values must be bounded JSON values")


def _declared_invocation(
    raw: Mapping[str, object] | None,
    unknown: list[dict[str, object]],
    *,
    secret_values: Sequence[str],
) -> dict[str, object]:
    declared: dict[str, object] = {}
    omitted = 0
    for key in sorted((raw or {}), key=lambda item: str(item)):
        if not isinstance(key, str) or key not in DECLARED_INVOCATION_ALLOWLIST:
            omitted += 1
            continue
        try:
            declared[key] = _safe_declared_value(
                (raw or {})[key],
                secret_values=secret_values,
            )
        except RuntimeObservationError:
            omitted += 1
    if omitted:
        unknown.append(
            {
                "field": "declared.invocation",
                "reason": "unsafe_or_unallowlisted_fields_omitted",
                "count": omitted,
            }
        )
    return {
        "invocation": declared,
        "provenance": "caller_supplied_unverified",
    }


@dataclass(frozen=True, init=False)
class RuntimeObservation:
    """Immutable result created only by :func:`collect_runtime_observation`.

    ``facts_sha256`` seals only the mechanically observed mapping.  Declared
    assertions and UNKNOWN reasons remain visible but cannot perturb that truth
    digest or gain authority from it.
    """

    captured_at: str
    observed: Mapping[str, object]
    declared: Mapping[str, object]
    unknown: Sequence[Mapping[str, object]]
    schema_version: str = field(default=RUNTIME_OBSERVATION_VERSION, init=False)
    facts_sha256: str = field(init=False)
    authority: bool = field(default=False, init=False)
    completion_claim_allowed: bool = field(default=False, init=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeObservationError("RuntimeObservation must come from the local collector")

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "observed": _thaw(self.observed),
            "declared": _thaw(self.declared),
            "unknown": _thaw(self.unknown),
            "facts_sha256": self.facts_sha256,
            "authority": self.authority,
            "completion_claim_allowed": self.completion_claim_allowed,
        }


def _new_runtime_observation(
    *,
    captured_at: datetime | str,
    observed: Mapping[str, object],
    declared: Mapping[str, object],
    unknown: Sequence[Mapping[str, object]],
) -> RuntimeObservation:
    instance = object.__new__(RuntimeObservation)
    frozen_observed = _freeze(_thaw(observed))
    frozen_declared = _freeze(_thaw(declared))
    unknown_rows = [_thaw(row) for row in unknown]
    unknown_rows.sort(key=lambda row: _canonical_json_bytes(row))
    frozen_unknown = _freeze(unknown_rows)
    facts = {
        "schema_version": RUNTIME_OBSERVATION_VERSION,
        "observed": _thaw(frozen_observed),
    }
    object.__setattr__(instance, "schema_version", RUNTIME_OBSERVATION_VERSION)
    object.__setattr__(instance, "captured_at", _utc_text(captured_at))
    object.__setattr__(instance, "observed", frozen_observed)
    object.__setattr__(instance, "declared", frozen_declared)
    object.__setattr__(instance, "unknown", frozen_unknown)
    object.__setattr__(
        instance,
        "facts_sha256",
        hashlib.sha256(_canonical_json_bytes(facts)).hexdigest(),
    )
    object.__setattr__(instance, "authority", False)
    object.__setattr__(instance, "completion_claim_allowed", False)
    return instance


def _git_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _GIT_ENVIRONMENT_ALLOWLIST
    }
    environment.update(
        {
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _git_bytes(cwd: Path, *arguments: str) -> tuple[int | None, bytes]:
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=",
                "--no-optional-locks",
                "-C",
                str(cwd),
                *arguments,
            ],
            check=False,
            capture_output=True,
            env=_git_environment(),
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, b""
    return completed.returncode, completed.stdout


def _git_text(cwd: Path, *arguments: str) -> tuple[int | None, str | None]:
    return_code, raw = _git_bytes(cwd, *arguments)
    if return_code is None:
        return None, None
    try:
        return return_code, raw.decode("utf-8", errors="strict").rstrip("\r\n")
    except UnicodeDecodeError:
        return return_code, None


def _git_path(cwd: Path, *arguments: str, base: Path | None = None) -> str | None:
    return_code, raw = _git_text(cwd, *arguments)
    if return_code != 0 or raw is None or not raw:
        return None
    return str(_lexical_absolute(raw, base=base or cwd))


def _framed_digest_update(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _bounded_dirty_fingerprint(
    cwd: Path,
    root: Path,
    *,
    dirty: bool | None,
) -> tuple[str | None, str | None]:
    """Hash bounded dirty identities without emitting paths or file content."""

    if dirty is None:
        return None, "dirty_state_unknown"
    commands = (
        ("diff", "--no-ext-diff", "--cached", "--raw", "-z", "--no-renames", "--"),
        (
            "diff",
            "--no-ext-diff",
            "--cached",
            "--name-only",
            "-z",
            "--no-renames",
            "--",
        ),
        ("diff", "--no-ext-diff", "--name-only", "-z", "--no-renames", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    )
    outputs: list[bytes] = []
    for command in commands:
        return_code, raw = _git_bytes(cwd, *command)
        if return_code != 0:
            return None, "git_dirty_fingerprint_probe_failed"
        outputs.append(raw)
    if sum(len(raw) for raw in outputs) > _MAX_DIRTY_PATH_BYTES:
        return None, "git_dirty_fingerprint_path_budget_exceeded"

    path_rows = {
        path_raw
        for raw in outputs[1:]
        for path_raw in raw.split(b"\0")
        if path_raw
    }
    if len(path_rows) > _MAX_DIRTY_FINGERPRINT_FILES:
        return None, "git_dirty_fingerprint_file_budget_exceeded"

    digest = hashlib.sha256()
    _framed_digest_update(digest, outputs[0])
    remaining_bytes = _MAX_DIRTY_FINGERPRINT_BYTES
    root_text = os.path.normcase(str(root))
    for path_raw in sorted(path_rows):
        try:
            relative_text = path_raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, "git_dirty_fingerprint_path_decode_failed"
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            return None, "git_dirty_fingerprint_path_invalid"
        candidate = _lexical_absolute(root / relative)
        try:
            if os.path.commonpath((os.path.normcase(str(candidate)), root_text)) != root_text:
                return None, "git_dirty_fingerprint_path_escape"
        except ValueError:
            return None, "git_dirty_fingerprint_path_escape"
        _framed_digest_update(digest, path_raw)
        try:
            candidate_state = candidate.lstat()
        except (FileNotFoundError, NotADirectoryError):
            _framed_digest_update(digest, b"ABSENT")
            continue
        except OSError:
            return None, "git_dirty_fingerprint_file_probe_failed"
        if stat.S_ISLNK(candidate_state.st_mode):
            try:
                link_value = os.fsencode(os.readlink(candidate))
            except OSError:
                return None, "git_dirty_fingerprint_link_probe_failed"
            _framed_digest_update(digest, b"SYMLINK" + link_value)
            continue
        if not stat.S_ISREG(candidate_state.st_mode):
            return None, "git_dirty_fingerprint_non_regular_file"
        if candidate_state.st_size > remaining_bytes:
            return None, "git_dirty_fingerprint_content_budget_exceeded"
        content_identity = _hash_regular_file(candidate)
        if content_identity is None:
            return None, "git_dirty_fingerprint_file_changed_during_hash"
        remaining_bytes -= content_identity[1]
        _framed_digest_update(
            digest,
            b"FILE" + bytes.fromhex(content_identity[0]),
        )
    return digest.hexdigest(), None


def _git_snapshot(cwd: Path) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    unknown: list[dict[str, object]] = []
    root = _git_path(cwd, "rev-parse", "--show-toplevel")
    if root is None:
        unknown.append({"field": "observed.git.root", "reason": "git_probe_failed"})
        return None, unknown
    root_path = Path(root)
    head_code, head_text = _git_text(cwd, "rev-parse", "--verify", "HEAD")
    head = head_text if head_code == 0 and head_text else None
    if head is None:
        unknown.append({"field": "observed.git.head", "reason": "unborn_or_probe_failed"})

    branch_code, branch_text = _git_text(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    branch = branch_text if branch_code == 0 and branch_text else None
    detached_head = head is not None and branch is None
    if branch is None and not detached_head:
        unknown.append({"field": "observed.git.branch", "reason": "unborn_or_probe_failed"})

    git_dir = _git_path(cwd, "rev-parse", "--absolute-git-dir")
    if git_dir is None:
        unknown.append({"field": "observed.git.git_dir", "reason": "git_probe_failed"})

    common_dir = _git_path(
        cwd,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        base=root_path,
    )
    if common_dir is None:
        common_dir = _git_path(cwd, "rev-parse", "--git-common-dir", base=cwd)
    if common_dir is None:
        unknown.append({"field": "observed.git.common_dir", "reason": "git_probe_failed"})

    status_code, status_raw = _git_bytes(
        cwd,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
    )
    dirty = bool(status_raw) if status_code == 0 else None
    porcelain_status_sha256 = (
        hashlib.sha256(status_raw).hexdigest() if status_code == 0 else None
    )
    porcelain_status_bytes = len(status_raw) if status_code == 0 else None
    if dirty is None:
        unknown.append({"field": "observed.git.dirty", "reason": "git_probe_failed"})
    dirty_fingerprint_sha256, dirty_fingerprint_error = _bounded_dirty_fingerprint(
        cwd,
        root_path,
        dirty=dirty,
    )
    if dirty_fingerprint_error is not None:
        unknown.append(
            {
                "field": "observed.git.dirty_fingerprint_sha256",
                "reason": dirty_fingerprint_error,
            }
        )

    linked_worktree: bool | None = None
    if git_dir is not None and common_dir is not None:
        linked_worktree = os.path.normcase(git_dir) != os.path.normcase(common_dir)
    return {
        "root": root,
        "head": head,
        "branch": branch,
        "worktree": root,
        "git_dir": git_dir,
        "common_dir": common_dir,
        "linked_worktree": linked_worktree,
        "detached_head": detached_head,
        "dirty": dirty,
        # Identity of the porcelain status class, not a worktree content seal.
        "porcelain_status_sha256": porcelain_status_sha256,
        "porcelain_status_bytes": porcelain_status_bytes,
        "dirty_fingerprint_sha256": dirty_fingerprint_sha256,
        "dirty_fingerprint_complete": dirty_fingerprint_error is None,
    }, unknown


def _observe_git(cwd: Path, unknown: list[dict[str, object]]) -> dict[str, object] | None:
    return_code, inside = _git_text(cwd, "rev-parse", "--is-inside-work-tree")
    if return_code is None:
        unknown.append({"field": "observed.git", "reason": "git_probe_unavailable"})
        return None
    if return_code != 0 or inside != "true":
        unknown.append(
            {
                "field": "observed.git",
                "reason": "not_a_git_worktree_or_probe_rejected",
            }
        )
        return None

    first, first_unknown = _git_snapshot(cwd)
    second, second_unknown = _git_snapshot(cwd)
    if first is None or second is None:
        unknown.extend(second_unknown or first_unknown)
        return None
    if _canonical_json_bytes(first) != _canonical_json_bytes(second):
        unknown.append(
            {
                "field": "observed.git",
                "reason": "changed_during_probe",
            }
        )
        return None
    unknown.extend(second_unknown)
    second["snapshot_stable"] = True
    return second


def _stat_fingerprint(value: os.stat_result) -> tuple[object, ...]:
    return (
        value.st_mode,
        value.st_dev,
        value.st_ino,
        value.st_size,
        getattr(value, "st_mtime_ns", None),
    )


def _hash_regular_file(path: Path) -> tuple[str, int, tuple[object, ...]] | None:
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode):
                return None
            digest = hashlib.sha256()
            byte_count = 0
            for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
                byte_count += len(chunk)
            finished = os.fstat(handle.fileno())
    except (OSError, RuntimeError):
        return None
    if (
        not stat.S_ISREG(finished.st_mode)
        or opened.st_size != finished.st_size
        or byte_count != finished.st_size
        or getattr(opened, "st_mtime_ns", None) != getattr(finished, "st_mtime_ns", None)
    ):
        return None
    return digest.hexdigest(), byte_count, _stat_fingerprint(finished)


def _candidate_paths(cwd: Path, codex_home: str | None) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if codex_home:
        home = _lexical_absolute(codex_home, base=cwd)
        for kind, relative in (
            ("agents", "AGENTS.md"),
            ("config", "config.toml"),
            ("hooks", "hooks.json"),
        ):
            candidates.append(
                {
                    "scope": "global",
                    "kind": kind,
                    "candidate_form": relative,
                    "path": str(home / relative),
                }
            )
    ancestors = list(reversed((cwd, *cwd.parents)))
    for ancestor in ancestors:
        for kind, relative in (
            ("agents", Path("AGENTS.md")),
            ("config", Path(".codex") / "config.toml"),
            ("hooks", Path(".codex") / "hooks.json"),
        ):
            candidates.append(
                {
                    "scope": "ancestor",
                    "kind": kind,
                    "candidate_form": relative.as_posix(),
                    "path": str(ancestor / relative),
                }
            )
    return candidates


def _file_identity(
    candidate: Mapping[str, str],
    *,
    index: int,
    unknown: list[dict[str, object]],
) -> dict[str, object]:
    path = Path(candidate["path"])

    def lstat_state() -> tuple[str, os.stat_result | None]:
        try:
            return "present", path.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return "missing", None
        except OSError:
            return "unknown", None

    resolved_before = _resolved_text(path)
    state_before, lexical_before = lstat_state()
    content_identity = _hash_regular_file(path) if state_before == "present" else None
    resolved_after = _resolved_text(path)
    state_after, lexical_after = lstat_state()
    binding_stable = state_before == state_after and resolved_before == resolved_after
    if lexical_before is not None and lexical_after is not None:
        binding_stable = binding_stable and _stat_fingerprint(
            lexical_before
        ) == _stat_fingerprint(lexical_after)
    elif lexical_before is not None or lexical_after is not None:
        binding_stable = False

    target_exists: bool | None = None
    if binding_stable and state_after == "missing":
        target_exists = False
    elif binding_stable and state_after == "present":
        try:
            target_after = path.stat()
        except (FileNotFoundError, NotADirectoryError):
            target_exists = False
        except OSError:
            target_exists = None
            unknown.append(
                {
                    "field": f"observed.file_candidates[{index}].target_exists",
                    "reason": "target_probe_failed",
                }
            )
        else:
            target_exists = True
            if content_identity is not None:
                binding_stable = _stat_fingerprint(target_after) == content_identity[2]
    resolved_final = _resolved_text(path)
    state_final, lexical_final = lstat_state()
    binding_stable = (
        binding_stable
        and state_after == state_final
        and resolved_after == resolved_final
    )
    if lexical_after is not None and lexical_final is not None:
        binding_stable = binding_stable and _stat_fingerprint(
            lexical_after
        ) == _stat_fingerprint(lexical_final)
    elif lexical_after is not None or lexical_final is not None:
        binding_stable = False
    if not binding_stable:
        content_identity = None
        unknown.append(
            {
                "field": f"observed.file_candidates[{index}]",
                "reason": "path_or_target_changed_during_probe",
            }
        )
    if resolved_final is None and binding_stable:
        unknown.append(
            {
                "field": f"observed.file_candidates[{index}].resolved_target",
                "reason": "path_resolution_failed",
            }
        )
    if "unknown" in {state_before, state_after, state_final}:
        binding_stable = False
        unknown.append(
            {
                "field": f"observed.file_candidates[{index}].exists",
                "reason": "path_probe_failed",
            }
        )

    exists: bool | None = state_final == "present" if binding_stable else None
    symlink: bool | None = (
        bool(lexical_final and stat.S_ISLNK(lexical_final.st_mode)) if binding_stable else None
    )
    path_redirected: bool | None = None
    if binding_stable and resolved_final is not None:
        path_redirected = os.path.normcase(str(path)) != os.path.normcase(resolved_final)
    if exists and content_identity is None:
        unknown.append(
            {
                "field": f"observed.file_candidates[{index}].content_identity",
                "reason": "not_regular_unreadable_or_changed_during_hash",
            }
        )
    sha256, byte_count = (
        (content_identity[0], content_identity[1])
        if content_identity is not None
        else (None, None)
    )
    return {
        **dict(candidate),
        "resolved_target": resolved_final if binding_stable else None,
        "symlink": symlink,
        "exists": exists,
        "target_exists": target_exists if binding_stable else None,
        "path_redirected": path_redirected,
        "sha256": sha256,
        "bytes": byte_count,
        "capture_stable": binding_stable,
    }


def _observed_environment(
    environ: Mapping[str, str],
    unknown: list[dict[str, object]],
    *,
    secret_values: Sequence[str],
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name in sorted(OBSERVED_ENVIRONMENT_ALLOWLIST):
        value = environ.get(name)
        if (
            isinstance(value, str)
            and value
            and not _SECRET_VALUE_RE.search(value)
            and not _contains_known_secret(value, secret_values)
        ):
            observed[name] = value
        elif isinstance(value, str) and value:
            unknown.append(
                {
                    "field": f"observed.environment.{name}",
                    "reason": "secret_like_value_redacted",
                }
            )
        else:
            unknown.append(
                {
                    "field": f"observed.environment.{name}",
                    "reason": "not_present",
                }
            )
    return observed


def _known_secret_values(environ: Mapping[str, str]) -> tuple[str, ...]:
    values = {
        value
        for key, value in environ.items()
        if isinstance(key, str)
        and _SECRET_KEY_RE.search(key)
        and isinstance(value, str)
        and len(value) >= 8
    }
    return tuple(sorted(values))


def collect_runtime_observation(
    *,
    declared_invocation: Mapping[str, object] | None = None,
) -> RuntimeObservation:
    """Collect local probe facts without accepting caller text as observed truth.

    ``observer_process`` identifies the Python probe, not the parent Codex or a
    worker invocation.  There is intentionally no caller override for cwd,
    environment, process, or executable.  Invocation assertions, including
    permission assertions, always remain under ``declared``.
    """

    actual_cwd = _lexical_absolute(Path.cwd())
    unknown: list[dict[str, object]] = [
        {
            "field": "observed.permissions.approval_policy",
            "reason": "no_current_process_enforcement_probe",
        },
        {
            "field": "observed.permissions.filesystem_access",
            "reason": "no_current_process_enforcement_probe",
        },
        {
            "field": "observed.permissions.sandbox_mode",
            "reason": "no_current_process_enforcement_probe",
        },
        {
            "field": "observed.tool_surface",
            "reason": "not_measured_by_this_collector",
        },
    ]
    secret_values = _known_secret_values(os.environ)
    environment_facts = _observed_environment(
        os.environ,
        unknown,
        secret_values=secret_values,
    )

    pid = _positive_integer(os.getpid(), "process_id")
    ppid = _positive_integer(os.getppid(), "parent_process_id")
    executable_path = _lexical_absolute(sys.executable, base=actual_cwd)
    executable_resolved = _resolved_text(executable_path)
    if executable_resolved is None:
        unknown.append(
            {
                "field": "observed.observer_process.executable_resolved",
                "reason": "path_resolution_failed",
            }
        )

    git_facts = _observe_git(actual_cwd, unknown)
    candidate_rows = _candidate_paths(actual_cwd, environment_facts.get("CODEX_HOME"))
    file_candidates = [
        _file_identity(row, index=index, unknown=unknown)
        for index, row in enumerate(candidate_rows)
    ]
    observed = {
        "cwd": str(actual_cwd),
        "cwd_resolved": _resolved_text(actual_cwd),
        "observer_process": {
            "pid": pid,
            "parent_pid": ppid,
            "executable": str(executable_path),
            "executable_resolved": executable_resolved,
        },
        "environment": environment_facts,
        "git": git_facts,
        "file_candidates": file_candidates,
    }
    if observed["cwd_resolved"] is None:
        unknown.append({"field": "observed.cwd_resolved", "reason": "path_resolution_failed"})

    return _new_runtime_observation(
        captured_at=_utc_text(None),
        observed=observed,
        declared=_declared_invocation(
            declared_invocation,
            unknown,
            secret_values=secret_values,
        ),
        unknown=unknown,
    )


__all__ = [
    "DECLARED_INVOCATION_ALLOWLIST",
    "OBSERVED_ENVIRONMENT_ALLOWLIST",
    "RUNTIME_OBSERVATION_VERSION",
    "RuntimeObservation",
    "RuntimeObservationError",
    "collect_runtime_observation",
]
