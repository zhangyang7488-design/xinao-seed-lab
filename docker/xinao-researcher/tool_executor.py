#!/usr/bin/env python3
"""Tool-executor process for dual-container fallback (candidate only).

Holds no Grok auth/config/provider session. Accepts only bounded IPC requests
over a Unix socket or stdio. May access one episode lab and private /tmp.
Network must be denied by container create specs (this process does not open
outbound sockets for tool ops).

Does not write Owner/science/account authority fields.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipc_contract import (
    EPISODE_LAB_ROOT,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PRIVATE_TMP_ROOT,
    IpcContractError,
    authority_clamp_flags,
    canonical_bytes,
    decode_frame,
    encode_frame,
    make_response,
    normalize_lab_relative_path,
    parse_json_object,
    sha256_bytes,
    validate_request,
)

# Hard denials: tool executor must not see transport secrets.
FORBIDDEN_ENV_PREFIXES = (
    "GROK_",
    "XAI_",
    "OPENAI_",
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
)
FORBIDDEN_ENV_KEYS = frozenset(
    {
        "HOME",
        "GROK_HOME",
        "DOCKER_HOST",
        "SSH_AUTH_SOCK",
        "KUBECONFIG",
    }
)

# Absolute binaries permitted for shell_exec (lab-relative args only otherwise).
# Interactive shells are NOT allowed: free-form -c smuggling reaches host paths.
ALLOWED_BIN_PREFIXES = (
    "/usr/bin/",
    "/bin/",
    "/usr/local/bin/",
)
ALLOWED_BIN_EXACT = frozenset(
    {
        "/usr/bin/env",
        "/usr/bin/python",
        "/usr/bin/python3",
        "/usr/local/bin/python",
        "/usr/local/bin/python3",
    }
)
DENIED_SHELL_BINARIES = frozenset(
    {
        "sh",
        "bash",
        "dash",
        "zsh",
        "csh",
        "tcsh",
        "ksh",
        "/bin/sh",
        "/bin/bash",
        "/bin/dash",
        "/bin/zsh",
        "/usr/bin/sh",
        "/usr/bin/bash",
        "/usr/bin/dash",
        "/usr/bin/zsh",
        "/usr/bin/rbash",
    }
)
# Substrings banned in any argv element (transport, proc, sockets, ledgers).
SHELL_DENIED_SUBSTRINGS = (
    "/grok-home",
    "auth.json",
    "docker.sock",
    "podman.sock",
    "/etc/shadow",
    "shadow_ledger",
    "/proc",
    "/sys/",
    "/dev/",
    "/var/run",
    "/run/docker",
    "/root/",
    "provider_session",
    "GROK_API",
)

# shell_exec outer confinement (defense in depth beyond argv filters).
# auto: use bwrap when binary exists; 1/require: deny shell_exec if missing; 0: argv-only.
BWRAP_MODE_ENV = "XINAO_TOOL_EXEC_BWRAP"
BWRAP_BIN_ENV = "XINAO_TOOL_BWRAP_BIN"
# Unix peer uid allowlist (comma-separated). Empty + require=0 → no SO_PEERCRED gate.
IPC_PEER_UID_ENV = "XINAO_IPC_PEER_UIDS"
# Genuine dual-container profile: require=1 fail-closes when allowlist empty or peer mismatch.
IPC_PEER_REQUIRE_ENV = "XINAO_IPC_PEER_REQUIRE"
# Durable (episode-scoped) replay markers live under IPC mount, never under lab RW.
REPLAY_STATE_DIR_ENV = "XINAO_REPLAY_STATE_DIR"
DEFAULT_REPLAY_STATE_BASENAME = ".xinao-replay"


class ToolExecutorError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def _safe_replay_token(value: str, *, maximum: int = 128) -> str:
    """Filesystem-safe token for durable replay markers (no path separators)."""
    cleaned = []
    for ch in str(value)[:maximum]:
        if ch.isalnum() or ch in {"-", "_", "."}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    token = "".join(cleaned).strip("._") or "empty"
    return token[:maximum]


class RequestReplayGuard:
    """Reject duplicate (episode_id, request_id) for one episode.

    Process-local set always applies. When ``state_dir`` is set (genuine dual-
    container: under the IPC volume, outside lab RW), markers survive tool-
    executor restart so the same request_id cannot be replayed for the episode.
    Markers are never stored under the episode lab (model-writable).
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._state_dir = Path(state_dir) if state_dir is not None else None
        if self._state_dir is not None:
            try:
                self._state_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                # Fall back to process-local only if durable dir unusable.
                self._state_dir = None

    @property
    def durable(self) -> bool:
        return self._state_dir is not None

    def _marker_path(self, episode_id: str, request_id: str) -> Path:
        assert self._state_dir is not None
        return (
            self._state_dir
            / _safe_replay_token(episode_id, maximum=256)
            / f"{_safe_replay_token(request_id, maximum=128)}.seen"
        )

    def check_and_record(self, episode_id: str, request_id: str) -> None:
        key = (episode_id, request_id)
        if key in self._seen:
            raise ToolExecutorError(
                "REQUEST_REPLAY",
                f"duplicate request_id for episode: {request_id}",
            )
        if self._state_dir is not None:
            marker = self._marker_path(episode_id, request_id)
            try:
                if marker.is_file():
                    raise ToolExecutorError(
                        "REQUEST_REPLAY",
                        f"duplicate request_id for episode (durable): {request_id}",
                    )
                marker.parent.mkdir(parents=True, exist_ok=True)
                # O_EXCL: concurrent acceptors cannot both claim the same id.
                fd = os.open(
                    str(marker),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                try:
                    os.write(fd, b"1\n")
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except FileExistsError as exc:
                raise ToolExecutorError(
                    "REQUEST_REPLAY",
                    f"duplicate request_id for episode (durable): {request_id}",
                ) from exc
            except ToolExecutorError:
                raise
            except OSError as exc:
                raise ToolExecutorError("REPLAY_STATE_FAILED", str(exc)) from exc
        self._seen.add(key)


def scrub_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a minimal env with no provider/auth/session material."""
    del env  # never forward host env into tool executions
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": PRIVATE_TMP_ROOT,
        "TMPDIR": PRIVATE_TMP_ROOT,
        "TMP": PRIVATE_TMP_ROOT,
        "TEMP": PRIVATE_TMP_ROOT,
    }


def assert_no_auth_artifacts() -> list[str]:
    """Probe common auth/config paths; return list of violations if present."""
    violations: list[str] = []
    candidates = [
        Path("/grok-home/.grok/auth.json"),
        Path("/grok-home/.grok/config.json"),
        Path.home() / ".grok" / "auth.json",
        Path("/root/.grok/auth.json"),
        Path("/var/run/docker.sock"),
        Path("/run/docker.sock"),
        Path("/var/run/podman/podman.sock"),
    ]
    for path in candidates:
        try:
            if path.exists() or path.is_symlink():
                violations.append(f"present:{path}")
        except OSError:
            continue
    for key, value in os.environ.items():
        upper = key.upper()
        if not value:
            continue
        if upper in FORBIDDEN_ENV_KEYS or any(upper.startswith(p) for p in FORBIDDEN_ENV_PREFIXES):
            # HOME is always set; only flag provider-ish HOME when it points at grok home.
            if upper == "HOME" and "grok" not in value.lower():
                continue
            if upper == "HOME":
                violations.append(f"env:{key}")
                continue
            if upper in {"GROK_HOME"} or any(upper.startswith(p) for p in FORBIDDEN_ENV_PREFIXES):
                violations.append(f"env:{key}")
            elif upper in {"DOCKER_HOST", "SSH_AUTH_SOCK", "KUBECONFIG"}:
                violations.append(f"env:{key}")
    return violations


def _denial_response(
    *,
    reason_code: str,
    detail: str,
    request_id: str = "invalid",
    episode_id: str = "invalid",
    op: str = "ping",
) -> dict[str, Any]:
    core = {
        "status": "denied",
        "reason_code": reason_code,
        "stderr": detail,
    }
    return {
        "schema_version": "xinao.dual_container_ipc_response.v1",
        "request_id": request_id,
        "episode_id": episode_id,
        "op": op,
        "status": "denied",
        "exit_code": 125,
        "stdout": "",
        "stderr": detail,
        "reason_code": reason_code,
        "event_hash": sha256_bytes(canonical_bytes(core)),
        **authority_clamp_flags(),
    }


def _resolve_under_lab(relative: str, *, lab_root: Path) -> Path:
    rel = normalize_lab_relative_path(relative)
    # Do not follow symlinks for the final component: refuse escape before resolve.
    candidate = lab_root / rel
    lab_resolved = lab_root.resolve()
    try:
        # Ensure every parent stays inside the lab without following the leaf symlink.
        parent = candidate.parent.resolve()
        parent.relative_to(lab_resolved)
    except ValueError as exc:
        raise ToolExecutorError("PATH_ESCAPE", str(candidate)) from exc
    if candidate.is_symlink():
        raise ToolExecutorError("SYMLINK_REFUSED", str(candidate))
    # Refuse hardlinks: shared inode can alias planted ledger/outcome bytes outside lab.
    try:
        if candidate.exists() and not candidate.is_dir():
            st = candidate.lstat()
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                raise ToolExecutorError("HARDLINK_REFUSED", str(candidate))
    except OSError as exc:
        raise ToolExecutorError("PATH_STAT_FAILED", str(candidate)) from exc
    target = candidate.resolve()
    try:
        target.relative_to(lab_resolved)
    except ValueError as exc:
        raise ToolExecutorError("PATH_ESCAPE", str(target)) from exc
    return target


_EMBEDDED_ABS_PATH = re.compile(r"(?<![A-Za-z0-9_])(/(?:[A-Za-z0-9._-]+/?)+)")


def _is_allowed_bin_path(item: str) -> bool:
    if item == sys.executable or item in ALLOWED_BIN_EXACT:
        return True
    base = Path(item).name
    if base in DENIED_SHELL_BINARIES or item in DENIED_SHELL_BINARIES:
        return False
    return any(item.startswith(prefix) for prefix in ALLOWED_BIN_PREFIXES)


def _path_under_lab(token: str, *, lab_resolved: Path) -> bool:
    try:
        Path(token).resolve().relative_to(lab_resolved)
        return True
    except (OSError, ValueError):
        return False


def bwrap_mode() -> str:
    """Return normalized bwrap mode: auto | require | off."""
    raw = (os.environ.get(BWRAP_MODE_ENV) or "auto").strip().lower()
    if raw in {"0", "off", "false", "no", "disable", "disabled"}:
        return "off"
    if raw in {"1", "on", "true", "yes", "require", "required", "must"}:
        return "require"
    return "auto"


def resolve_bwrap_bin() -> str | None:
    explicit = (os.environ.get(BWRAP_BIN_ENV) or "").strip()
    if explicit:
        return explicit if os.path.isfile(explicit) and os.access(explicit, os.X_OK) else None
    return shutil.which("bwrap")


def _interpreter_ro_bind_targets() -> list[Path]:
    """Paths that must be visible for allowlisted interpreters (incl. venv).

    Never includes host root, /ipc, auth homes, docker sockets, or ledgers.
    """
    targets: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        # Keep both the path-as-given (venv symlink path) and the resolved target.
        # resolve()-only drops intermediate symlink paths that argv still uses.
        candidates: list[Path] = []
        try:
            if path.is_absolute():
                candidates.append(path)
        except OSError:
            pass
        try:
            candidates.append(path.resolve())
        except OSError:
            return
        for candidate in candidates:
            try:
                key = str(candidate)
            except OSError:
                continue
            if key in seen or key == "/":
                continue
            # Refuse to bind obvious credential/socket roots even if sys points there.
            lowered = key.lower()
            denied_hit = False
            for denied in (
                "docker.sock",
                "podman.sock",
                "/.grok",
                "auth.json",
                "/ledger",
                "/shadow",
                "/outcomes",
                "/freeze",
                "/settlement",
            ):
                if denied in lowered:
                    denied_hit = True
                    break
            if denied_hit:
                continue
            try:
                if not candidate.exists():
                    continue
            except OSError:
                continue
            seen.add(key)
            targets.append(candidate)

    _add(Path(sys.executable))
    # If argv0 is a venv shim, bind the whole prefix tree (site-packages, pyvenv.cfg).
    for raw in (
        getattr(sys, "executable", None),
        getattr(sys, "prefix", None),
        getattr(sys, "base_prefix", None),
        getattr(sys, "exec_prefix", None),
        getattr(sys, "base_exec_prefix", None),
    ):
        if raw:
            _add(Path(str(raw)))
    # Realpath of the interpreter binary (venv bin/python -> CPython install).
    try:
        _add(Path(os.path.realpath(sys.executable)))
    except OSError:
        pass
    # Parent of executable (venv bin/) when argv0 is a non-resolved symlink path.
    try:
        _add(Path(sys.executable).parent)
    except OSError:
        pass
    return targets


def build_bwrap_command(
    argv: Sequence[str],
    *,
    lab_root: Path,
    cwd: Path,
) -> list[str]:
    """Build bubblewrap argv that confines shell_exec to lab + system libs.

    Does not bind /ipc, /grok-home, docker sockets, ledger/outcome mounts, or host root.
    Uses a private /tmp tmpfs and network namespace (unshare-net).
    """
    bwrap = resolve_bwrap_bin()
    if not bwrap:
        raise ToolExecutorError("BWRAP_UNAVAILABLE", "bwrap binary not found")
    lab_resolved = lab_root.resolve()
    cwd_resolved = cwd.resolve()
    try:
        cwd_resolved.relative_to(lab_resolved)
    except ValueError as exc:
        raise ToolExecutorError("CWD_ESCAPE", str(cwd_resolved)) from exc

    # Preserve real lab path so relative and absolute-under-lab argv still work.
    lab_s = str(lab_resolved)
    cwd_s = str(cwd_resolved)
    cmd: list[str] = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--unshare-pid",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind-try",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--ro-bind-try",
        "/sbin",
        "/sbin",
        "--ro-bind-try",
        "/usr/local",
        "/usr/local",
        "--ro-bind-try",
        "/etc/ld.so.cache",
        "/etc/ld.so.cache",
        "--ro-bind-try",
        "/etc/ld.so.conf",
        "/etc/ld.so.conf",
        "--ro-bind-try",
        "/etc/ld.so.conf.d",
        "/etc/ld.so.conf.d",
        "--ro-bind-try",
        "/etc/alternatives",
        "/etc/alternatives",
        "--ro-bind-try",
        "/etc/ssl",
        "/etc/ssl",
        # Private volatile mounts first. Interpreter binds under /tmp must come AFTER
        # so uv/venv paths like /tmp/.cache/... are not masked by tmpfs /tmp.
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/var",
        "--tmpfs",
        "/run",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    # Bind venv / interpreter trees that live outside /usr (e.g. /workspace/.venv,
    # /tmp/.cache/uv/... ephemeral envs). Applied after tmpfs so /tmp trees remain visible.
    lab_key = str(lab_resolved)
    for target in _interpreter_ro_bind_targets():
        key = str(target)
        # Lab is already rw-bound; skip nested duplicates.
        if key == lab_key or key.startswith(lab_key + os.sep):
            continue
        cmd.extend(["--ro-bind-try", key, key])
    cmd.extend(
        [
            # Intentionally no --bind of /ipc, /grok-home, host root, or docker.sock.
            "--bind",
            lab_s,
            lab_s,
            "--chdir",
            cwd_s,
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/local/bin:/usr/bin:/bin",
            "--setenv",
            "HOME",
            PRIVATE_TMP_ROOT,
            "--setenv",
            "TMPDIR",
            PRIVATE_TMP_ROOT,
            "--setenv",
            "TMP",
            PRIVATE_TMP_ROOT,
            "--setenv",
            "TEMP",
            PRIVATE_TMP_ROOT,
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--setenv",
            "LC_ALL",
            "C.UTF-8",
            "--setenv",
            "PYTHONNOUSERSITE",
            "1",
            "--setenv",
            "PYTHONDONTWRITEBYTECODE",
            "1",
            "--",
        ]
    )
    cmd.extend(list(argv))
    return cmd


def wrap_shell_argv(argv: list[str], *, lab_root: Path, cwd: Path) -> list[str]:
    """Apply bwrap confinement according to XINAO_TOOL_EXEC_BWRAP policy."""
    mode = bwrap_mode()
    if mode == "off":
        return list(argv)
    bwrap = resolve_bwrap_bin()
    if bwrap is None:
        if mode == "require":
            raise ToolExecutorError(
                "BWRAP_REQUIRED",
                f"{BWRAP_MODE_ENV}=require but bwrap is unavailable",
            )
        return list(argv)
    return build_bwrap_command(argv, lab_root=lab_root, cwd=cwd)


def _validate_shell_argv(argv: list[str], *, lab_root: Path) -> None:
    """Fail closed on argv that reaches transport roots, /proc, sockets, or host paths."""
    lab_resolved = lab_root.resolve()
    if not argv:
        raise ToolExecutorError("ARGV_INVALID", "empty argv")
    # Reject shell interpreters (free-form -c / pipeline smuggling).
    head = argv[0]
    head_base = Path(head).name
    if head in DENIED_SHELL_BINARIES or head_base in DENIED_SHELL_BINARIES:
        raise ToolExecutorError("ARGV_DENIED", f"shell interpreter denied: {head[:80]}")
    for index, item in enumerate(argv):
        if not isinstance(item, str) or "\x00" in item:
            raise ToolExecutorError("ARGV_INVALID", "argv item")
        lowered = item.lower()
        for denied in SHELL_DENIED_SUBSTRINGS:
            if denied.lower() in lowered:
                raise ToolExecutorError("ARGV_DENIED", f"argv denied substring: {denied}")
        if ".." in item.replace("\\", "/").split("/"):
            raise ToolExecutorError("ARGV_DENIED", "argv path traversal")
        if item.startswith("/") or item.startswith("~"):
            if index == 0:
                # Allow system interpreters OR preseeded lab-local venv binaries
                # under /episode-lab (no live online installer).
                if _is_allowed_bin_path(item) or _path_under_lab(
                    item, lab_resolved=lab_resolved
                ):
                    continue
                raise ToolExecutorError("ARGV_DENIED", f"absolute binary denied: {item[:80]}")
            # Non-binary absolute args must resolve inside the episode lab only.
            if not _path_under_lab(item, lab_resolved=lab_resolved):
                raise ToolExecutorError("ARGV_DENIED", f"absolute path outside lab: {item[:80]}")
            continue
        # Relative binary name at argv[0] must not be a shell either.
        if index == 0 and (
            item in DENIED_SHELL_BINARIES or Path(item).name in DENIED_SHELL_BINARIES
        ):
            raise ToolExecutorError("ARGV_DENIED", f"shell interpreter denied: {item[:80]}")
        # Free-form args (python -c '...', shell snippets): reject embedded host paths.
        for match in _EMBEDDED_ABS_PATH.finditer(item):
            token = match.group(1).rstrip("/")
            if not token or token == "/":
                continue
            if _is_allowed_bin_path(token) or _is_allowed_bin_path(token + "/"):
                continue
            # Allow bare interpreter roots that appear in sys.executable dirname chains.
            if token in {"/usr", "/usr/local", "/usr/bin", "/bin", "/usr/local/bin"}:
                continue
            if _path_under_lab(token, lab_resolved=lab_resolved):
                continue
            raise ToolExecutorError(
                "ARGV_DENIED", f"embedded absolute path outside lab: {token[:80]}"
            )


def peer_require_enabled() -> bool:
    raw = (os.environ.get(IPC_PEER_REQUIRE_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on", "require", "required", "must"}


def _peer_uids_allowed() -> set[int] | None:
    """Return allowlist, empty set, or None.

    None means gate disabled (require off and no allowlist).
    Empty set with require on means fail-closed (no peer can connect until configured).
    """
    raw = (os.environ.get(IPC_PEER_UID_ENV) or "").strip()
    if not raw:
        if peer_require_enabled():
            return set()
        return None
    allowed: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError as exc:
            raise ToolExecutorError("IPC_PEER_UID_CONFIG", part) from exc
    if not allowed and peer_require_enabled():
        return set()
    if not allowed:
        return None
    return allowed


def assert_unix_peer_allowed(conn: socket.socket) -> None:
    """SO_PEERCRED gate. Fail-closed when XINAO_IPC_PEER_REQUIRE=1 (genuine profile)."""
    allowed = _peer_uids_allowed()
    if allowed is None:
        return
    if not allowed:
        raise ToolExecutorError(
            "IPC_PEER_CONFIG_REQUIRED",
            f"{IPC_PEER_UID_ENV} required when {IPC_PEER_REQUIRE_ENV}=1",
        )
    # Linux SO_PEERCRED: struct ucred { pid_t pid; uid_t uid; gid_t gid; }
    try:
        SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)
        creds = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
    except OSError as exc:
        raise ToolExecutorError("IPC_PEER_CRED_UNAVAILABLE", str(exc)) from exc
    if uid not in allowed:
        raise ToolExecutorError("IPC_PEER_UID_DENIED", f"uid={uid}")


def resolve_replay_state_dir(
    *, socket_path: Path | None = None, explicit: str | None = None
) -> Path | None:
    """Durable replay dir: env override, else sibling of Unix socket under /ipc."""
    raw = explicit if explicit is not None else (os.environ.get(REPLAY_STATE_DIR_ENV) or "")
    raw = raw.strip()
    if raw:
        return Path(raw)
    if socket_path is not None:
        # Keep markers next to the socket on the IPC volume (outside lab RW / bwrap).
        return Path(socket_path).parent / DEFAULT_REPLAY_STATE_BASENAME
    return None


def execute_op(
    request: Mapping[str, Any],
    *,
    lab_root: Path,
    replay_guard: RequestReplayGuard | None = None,
) -> dict[str, Any]:
    op = request["op"]
    args = request["args"]
    timeout_s = max(request["timeout_ms"] / 1000.0, 0.05)

    try:
        if replay_guard is not None:
            replay_guard.check_and_record(str(request["episode_id"]), str(request["request_id"]))

        if op == "ping":
            return make_response(
                request=request,
                status="ok",
                exit_code=0,
                stdout="pong",
                stderr="",
                reason_code=None,
            )

        if op == "list_dir":
            target = _resolve_under_lab(args["path_relative"], lab_root=lab_root)
            if not target.is_dir():
                return make_response(
                    request=request,
                    status="error",
                    exit_code=1,
                    stderr="not a directory",
                    reason_code="NOT_A_DIRECTORY",
                )
            names = sorted(p.name for p in target.iterdir())
            return make_response(
                request=request,
                status="ok",
                exit_code=0,
                stdout="\n".join(names),
                reason_code=None,
            )

        if op == "read_file":
            target = _resolve_under_lab(args["path_relative"], lab_root=lab_root)
            max_bytes = int(args["max_bytes"])
            if not target.is_file():
                return make_response(
                    request=request,
                    status="error",
                    exit_code=1,
                    stderr="file not found",
                    reason_code="FILE_NOT_FOUND",
                )
            data = target.read_bytes()
            truncated = len(data) > max_bytes
            if truncated:
                data = data[:max_bytes]
            return make_response(
                request=request,
                status="ok",
                exit_code=0,
                stdout=data.decode("utf-8", errors="replace"),
                stderr="truncated" if truncated else "",
                reason_code="TRUNCATED" if truncated else None,
            )

        if op == "write_file":
            target = _resolve_under_lab(args["path_relative"], lab_root=lab_root)
            # Refuse writing through an existing hardlink name before replace.
            if target.exists() and target.is_file():
                st = target.lstat()
                if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                    raise ToolExecutorError("HARDLINK_REFUSED", str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            content = args["content_utf8"].encode("utf-8")
            fd, tmp_name = tempfile.mkstemp(prefix=".xinao-tool-", dir=str(target.parent))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                os.replace(tmp_name, target)
            finally:
                if os.path.exists(tmp_name):
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
            return make_response(
                request=request,
                status="ok",
                exit_code=0,
                stdout=f"wrote:{len(content)}",
                reason_code=None,
            )

        if op == "shell_exec":
            cwd = _resolve_under_lab(args["cwd_relative"], lab_root=lab_root)
            if not cwd.is_dir():
                return make_response(
                    request=request,
                    status="error",
                    exit_code=1,
                    stderr="cwd not a directory",
                    reason_code="CWD_INVALID",
                )
            argv = list(args["argv"])
            _validate_shell_argv(argv, lab_root=lab_root)
            # Outer namespace confinement: private net + lab-only writable bind.
            # Argv filters alone are insufficient against interpreter path construction.
            run_argv = wrap_shell_argv(argv, lab_root=lab_root, cwd=cwd)
            env = scrub_environment()
            try:
                completed = subprocess.run(
                    run_argv,
                    # When bwrap wraps, it sets --chdir; keep cwd for argv-only fallback.
                    cwd=str(cwd) if run_argv == argv else None,
                    env=env if run_argv == argv else scrub_environment(),
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else "timeout"
                # Strip NULs that break response validation.
                stdout = stdout.replace("\x00", "")
                stderr = stderr.replace("\x00", "")
                return make_response(
                    request=request,
                    status="timeout",
                    exit_code=124,
                    stdout=stdout,
                    stderr=stderr,
                    reason_code="TIMEOUT",
                )
            except OSError as exc:
                return make_response(
                    request=request,
                    status="error",
                    exit_code=1,
                    stderr=str(exc),
                    reason_code="EXEC_FAILED",
                )
            stdout = (completed.stdout or "").replace("\x00", "")
            stderr = (completed.stderr or "").replace("\x00", "")
            return make_response(
                request=request,
                status="ok" if completed.returncode == 0 else "error",
                exit_code=int(completed.returncode),
                stdout=stdout,
                stderr=stderr,
                reason_code=None if completed.returncode == 0 else "NONZERO_EXIT",
            )

        return make_response(
            request=request,
            status="denied",
            exit_code=125,
            stderr="unknown op",
            reason_code="OP_UNKNOWN",
        )
    except IpcContractError as exc:
        return make_response(
            request=request,
            status="denied",
            exit_code=125,
            stderr=exc.detail,
            reason_code=exc.reason_code,
        )
    except ToolExecutorError as exc:
        return make_response(
            request=request,
            status="denied",
            exit_code=125,
            stderr=exc.detail,
            reason_code=exc.reason_code,
        )


def handle_raw_request(
    raw: bytes,
    *,
    lab_root: Path,
    replay_guard: RequestReplayGuard | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] | None = None
    try:
        if len(raw) > MAX_REQUEST_BYTES:
            raise IpcContractError("REQUEST_TOO_LARGE", str(len(raw)))
        payload = parse_json_object(raw, reason_code="REQUEST_JSON_INVALID")
        request = validate_request(payload)
    except IpcContractError as exc:
        # Preserve ids/args so transport broker can bind response to the caller's request
        # and recompute event_hash. Completely unparseable bodies stay synthetic.
        if isinstance(payload, dict):
            fake_req = {
                "request_id": (
                    payload["request_id"][:128]
                    if isinstance(payload.get("request_id"), str) and payload["request_id"]
                    else "invalid"
                ),
                "episode_id": (
                    payload["episode_id"][:256]
                    if isinstance(payload.get("episode_id"), str) and payload["episode_id"]
                    else "invalid"
                ),
                "op": (
                    payload["op"][:64]
                    if isinstance(payload.get("op"), str) and payload["op"]
                    else "ping"
                ),
                "args": payload["args"] if isinstance(payload.get("args"), dict) else {},
            }
            try:
                return make_response(
                    request=fake_req,
                    status="denied",
                    exit_code=125,
                    stderr=exc.detail,
                    reason_code=exc.reason_code,
                )
            except IpcContractError:
                pass
        return _denial_response(reason_code=exc.reason_code, detail=exc.detail)
    return execute_op(request, lab_root=lab_root, replay_guard=replay_guard)


def _send_response_frame(write_fn: Any, response: Mapping[str, Any]) -> None:
    body = encode_frame(dict(response))
    if len(body) - 8 > MAX_RESPONSE_BYTES:
        response = _denial_response(
            reason_code="RESPONSE_TOO_LARGE",
            detail="frame exceeds max",
            request_id=str(response.get("request_id", "invalid")),
            episode_id=str(response.get("episode_id", "invalid")),
            op=str(response.get("op", "ping")),
        )
        body = encode_frame(response)
    write_fn(body)


def serve_stdio(*, lab_root: Path, replay_state_dir: Path | None = None) -> int:
    """Multi-frame stdio broker (length-prefixed frames)."""
    buffer = b""
    state = replay_state_dir or resolve_replay_state_dir()
    replay_guard = RequestReplayGuard(state_dir=state)
    while True:
        chunk = sys.stdin.buffer.read(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            try:
                message, buffer = decode_frame(buffer, maximum=MAX_REQUEST_BYTES)
            except IpcContractError as exc:
                if exc.reason_code == "FRAME_INCOMPLETE":
                    break
                _send_response_frame(
                    sys.stdout.buffer.write,
                    _denial_response(reason_code=exc.reason_code, detail=exc.detail),
                )
                sys.stdout.buffer.flush()
                buffer = b""
                break
            response = handle_raw_request(
                canonical_bytes(message),
                lab_root=lab_root,
                replay_guard=replay_guard,
            )
            _send_response_frame(sys.stdout.buffer.write, response)
            sys.stdout.buffer.flush()
    return 0


def serve_unix(
    *,
    socket_path: Path,
    lab_root: Path,
    oneshot: bool = False,
    replay_state_dir: Path | None = None,
) -> int:
    if socket_path.exists():
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # Bind then listen immediately so sock.path existence implies acceptors are ready.
    server.bind(str(socket_path))
    server.listen(8)
    try:
        os.chmod(socket_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    server.settimeout(60.0)
    state = replay_state_dir or resolve_replay_state_dir(socket_path=socket_path)
    replay_guard = RequestReplayGuard(state_dir=state)
    try:
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                if oneshot:
                    return 0
                continue
            with conn:
                try:
                    assert_unix_peer_allowed(conn)
                except ToolExecutorError as exc:
                    _send_response_frame(
                        conn.sendall,
                        _denial_response(reason_code=exc.reason_code, detail=exc.detail),
                    )
                    if oneshot:
                        return 0
                    continue
                buffer = b""
                conn.settimeout(30.0)
                while True:
                    try:
                        chunk = conn.recv(4096)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buffer += chunk
                    while True:
                        try:
                            message, buffer = decode_frame(buffer, maximum=MAX_REQUEST_BYTES)
                        except IpcContractError as exc:
                            if exc.reason_code == "FRAME_INCOMPLETE":
                                break
                            _send_response_frame(
                                conn.sendall,
                                _denial_response(reason_code=exc.reason_code, detail=exc.detail),
                            )
                            buffer = b""
                            break
                        response = handle_raw_request(
                            canonical_bytes(message),
                            lab_root=lab_root,
                            replay_guard=replay_guard,
                        )
                        _send_response_frame(conn.sendall, response)
            if oneshot:
                return 0
    finally:
        server.close()
        if socket_path.exists():
            try:
                socket_path.unlink()
            except OSError:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XINAO dual-container tool executor")
    parser.add_argument(
        "--lab-root",
        default=EPISODE_LAB_ROOT,
        help="Episode lab root (default /episode-lab)",
    )
    parser.add_argument(
        "--socket",
        default="",
        help="Unix socket path; empty means stdio frames",
    )
    parser.add_argument(
        "--oneshot",
        action="store_true",
        help="Exit after one connection (socket mode)",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Print auth-artifact probe and exit",
    )
    parser.add_argument(
        "--replay-state-dir",
        default="",
        help="Durable REQUEST_REPLAY marker dir (default: <socket-parent>/.xinao-replay)",
    )
    args = parser.parse_args(argv)
    lab_root = Path(args.lab_root)
    if args.self_check:
        violations = assert_no_auth_artifacts()
        report = {
            "schema_version": "xinao.tool_executor_self_check.v1",
            "lab_root": str(lab_root),
            "violations": violations,
            "ok": not violations,
            "bwrap_mode": bwrap_mode(),
            "bwrap_bin": resolve_bwrap_bin(),
            "peer_require": peer_require_enabled(),
            **authority_clamp_flags(),
        }
        sys.stdout.buffer.write(canonical_bytes(report))
        return 0 if not violations else 2
    if not lab_root.is_dir():
        print(f"lab root missing: {lab_root}", file=sys.stderr)
        return 10
    replay_dir = Path(args.replay_state_dir) if args.replay_state_dir else None
    if args.socket:
        return serve_unix(
            socket_path=Path(args.socket),
            lab_root=lab_root,
            oneshot=args.oneshot,
            replay_state_dir=replay_dir,
        )
    return serve_stdio(lab_root=lab_root, replay_state_dir=replay_dir)


if __name__ == "__main__":
    sys.exit(main())
