from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

RUN_SCHEMA = "xinao.cleanroom-c.perpetual-run.v1"
CONTROLLER_SCHEMA = "xinao.cleanroom-c.perpetual-controller-state.v1"
LINEAGE_SCHEMA = "xinao.cleanroom-c.perpetual-lineage-state.v1"
TURN_SCHEMA = "xinao.cleanroom-c.perpetual-turn-receipt.v1"
PACKET_SCHEMA = "xinao.cleanroom-c.late-fusion-packet.v1"

DEFAULT_SOURCE_REPO = Path(r"E:\CODEX_CLEANROOM\workspace")
DEFAULT_LAUNCHER = Path(r"E:\CODEX_CLEANROOM\Open-Codex-Cleanroom.ps1")
DEFAULT_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_c")
DEFAULT_CLONE_ROOT = Path(r"E:\CODEX_CLEANROOM\research-lineages")
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "max"
DEFAULT_WIDTH = 4
DEFAULT_WATCHDOG_SECONDS = 6 * 60 * 60
DEFAULT_CONTINUATION_DELAY_SECONDS = 20
DEFAULT_RETRY_DELAYS_SECONDS = (60, 300, 900)
DEFAULT_PARK_POLL_SECONDS = 30

LIFECYCLE_STATES = (
    "CONTINUE",
    "WAIT",
    "BLOCKED",
    "NO_POSITIVE_FRONTIER",
    "PAUSE",
)
PARKED_LIFECYCLE_STATES = tuple(state for state in LIFECYCLE_STATES if state != "CONTINUE")
_LIFECYCLE_RE = re.compile(
    r"(?im)^\s*XINAO_LINEAGE_STATE\s*:\s*"
    r"(CONTINUE|WAIT|BLOCKED|NO_POSITIVE_FRONTIER|PAUSE)\s*$"
)

_TRANSIENT_ERROR_TOKENS = (
    "429",
    "rate limit",
    "too many requests",
    "temporarily unavailable",
    "service unavailable",
    "overloaded",
    "connection reset",
    "connection aborted",
    "connection refused",
    "stream disconnected",
    "timed out",
    "timeout",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
)
_HARD_ERROR_TOKENS = (
    "401",
    "403",
    "authentication",
    "unauthorized",
    "forbidden",
    "login required",
    "invalid api key",
    "insufficient quota",
    "usage limit",
)


class PerpetualRuntimeError(RuntimeError):
    """A typed control-tower failure that must not be mistaken for cognition."""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


_DYNAMIC_LINEAGE_PROJECT_RE = re.compile(
    r"(?im)^\[projects\.'(?P<path>[^'\r\n]+)'\]\r?\n"
    r'trust_level\s*=\s*"trusted"\r?\n(?:\r?\n)?(?=^\[|\Z)'
)


def cleanroom_config_identity(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    dynamic_paths: list[str] = []

    def normalize_dynamic_project(match: re.Match[str]) -> str:
        project_path = match.group("path")
        normalized_path = project_path.replace("/", "\\").lower()
        if not normalized_path.startswith("e:\\codex_cleanroom\\research-lineages\\"):
            return match.group(0)
        dynamic_paths.append(project_path)
        return ""

    semantic_text = _DYNAMIC_LINEAGE_PROJECT_RE.sub(normalize_dynamic_project, text)
    return {
        "raw_sha256": sha256_bytes(raw),
        "semantic_sha256": sha256_bytes(semantic_text.encode("utf-8")),
        "dynamic_lineage_project_paths": sorted(dynamic_paths, key=str.lower),
    }


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_bytes(raw)


def atomic_write_text(path: Path, text: str) -> str:
    return atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: object) -> str:
    return atomic_write_bytes(path, canonical_json_bytes(value))


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise PerpetualRuntimeError(f"JSON_OBJECT_REQUIRED: {path}")
    return value


def resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def is_process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            [
                "C:\\Windows\\System32\\tasklist.exe",
                "/FI",
                f"PID eq {pid}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
            check=False,
        )
        return completed.returncode == 0 and f'"{pid}"' in completed.stdout
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def run_checked(
    command: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(part) for part in command]
    completed = subprocess.run(
        rendered,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise PerpetualRuntimeError(
            "COMMAND_FAILED\n"
            f"command={json.dumps(rendered, ensure_ascii=False)}\n"
            f"exit_code={completed.returncode}\n"
            f"stdout={completed.stdout[-4000:]}\n"
            f"stderr={completed.stderr[-4000:]}"
        )
    return completed


def git_output(repo: Path, *arguments: str, timeout: float = 120) -> str:
    completed = run_checked(["git", "-C", repo, *arguments], timeout=timeout)
    return completed.stdout.strip()


def validate_source_repo(repo: Path) -> dict[str, str]:
    resolved = resolve_path(repo)
    if not resolved.is_dir():
        raise PerpetualRuntimeError(f"SOURCE_REPO_MISSING: {resolved}")
    top = resolve_path(git_output(resolved, "rev-parse", "--show-toplevel"))
    if top != resolved:
        raise PerpetualRuntimeError(f"SOURCE_REPO_ROOT_MISMATCH: {resolved} != {top}")
    head = git_output(resolved, "rev-parse", "HEAD")
    status = git_output(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PerpetualRuntimeError(f"SOURCE_REPO_NOT_CLEAN:\n{status}")
    branch = git_output(resolved, "branch", "--show-current")
    return {
        "root": str(resolved),
        "head": head,
        "branch": branch,
        "status_sha256": sha256_bytes((status + "\n").encode("utf-8")),
    }


def validate_pinned_source_commit(repo: Path, source_head: str) -> dict[str, str]:
    """Verify that a frozen source commit remains available without pinning live HEAD."""

    resolved = resolve_path(repo)
    if not resolved.is_dir():
        raise PerpetualRuntimeError(f"SOURCE_REPO_MISSING: {resolved}")
    top = resolve_path(git_output(resolved, "rev-parse", "--show-toplevel"))
    if top != resolved:
        raise PerpetualRuntimeError(f"SOURCE_REPO_ROOT_MISMATCH: {resolved} != {top}")
    git_output(resolved, "cat-file", "-e", f"{source_head}^{{commit}}")
    return {
        "root": str(resolved),
        "current_head": git_output(resolved, "rev-parse", "HEAD"),
        "source_head": source_head,
    }


def validate_lineage_runtime_repo(workspace: Path, source_head: str) -> dict[str, str]:
    """Verify a candidate lineage still descends from its frozen, remote-free baseline."""

    resolved = resolve_path(workspace)
    if not resolved.is_dir():
        raise PerpetualRuntimeError(f"LINEAGE_WORKSPACE_MISSING: {resolved}")
    top = resolve_path(git_output(resolved, "rev-parse", "--show-toplevel"))
    if top != resolved:
        raise PerpetualRuntimeError(f"LINEAGE_REPO_ROOT_MISMATCH: {resolved} != {top}")
    head = git_output(resolved, "rev-parse", "HEAD")
    merge_base = git_output(resolved, "merge-base", source_head, head)
    if merge_base.lower() != source_head.lower():
        raise PerpetualRuntimeError(
            f"LINEAGE_BASELINE_NOT_ANCESTOR: workspace={resolved} baseline={source_head} head={head}"
        )
    remotes = git_output(resolved, "remote")
    if remotes:
        raise PerpetualRuntimeError(f"LINEAGE_REMOTE_MUST_BE_EMPTY: {resolved}")
    return {
        "workspace": str(resolved),
        "source_head": source_head,
        "head": head,
        "status_sha256": sha256_bytes(
            (
                git_output(resolved, "status", "--porcelain=v1", "--untracked-files=all") + "\n"
            ).encode("utf-8")
        ),
    }


def clone_isolated_repo(source: Path, destination: Path, head: str) -> dict[str, str]:
    source = resolve_path(source)
    destination = resolve_path(destination)
    if destination.exists():
        raise PerpetualRuntimeError(f"LINEAGE_CLONE_ALREADY_EXISTS: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--no-hardlinks",
            "--no-checkout",
            source,
            destination,
        ],
        timeout=600,
    )
    try:
        run_checked(["git", "-C", destination, "checkout", "--quiet", "--detach", head])
        remotes = git_output(destination, "remote")
        if "origin" in remotes.splitlines():
            run_checked(["git", "-C", destination, "remote", "remove", "origin"])
        observed_head = git_output(destination, "rev-parse", "HEAD")
        status = git_output(destination, "status", "--porcelain=v1", "--untracked-files=all")
        if observed_head != head or status:
            raise PerpetualRuntimeError(
                "LINEAGE_CLONE_IDENTITY_MISMATCH: "
                f"expected={head} observed={observed_head} status={status!r}"
            )
        return {
            "workspace": str(destination),
            "head": observed_head,
            "remote_count": str(len(git_output(destination, "remote").splitlines())),
            "status_sha256": sha256_bytes((status + "\n").encode("utf-8")),
        }
    except BaseException:
        # Preserve failed setup for diagnosis. The caller records the run as failed.
        raise


def lifecycle_contract() -> str:
    return """在当前 turn 已把局部 Reality Return 带回整个 working world 后，最后另起一行写一个生命周期回执：
XINAO_LINEAGE_STATE: CONTINUE
或把 CONTINUE 换成 WAIT / BLOCKED / NO_POSITIVE_FRONTIER / PAUSE。

CONTINUE 只表示：你从自己的整个当前 world 判断，现在确有下一单位正收益认识计算，应由同一 session 立即续接。WAIT 表示等待现实或具名事件；BLOCKED 表示真实 runtime/材料阻塞；NO_POSITIVE_FRONTIER 表示当前合法空间已无正收益前沿；PAUSE 表示你明确要求暂停该 lineage。这个回执只让 S 管理生命周期，不限制你的研究内容，也不能把局部 no-action、ABSTAIN、一次反证或一轮报告冒充整个新澳父对象关闭。"""


def build_branch_initial_prompt(*, lineage_id: str, run_id: str, source_head: str) -> str:
    return f"""你是 C clean-room 中一条独立、完整、长期存续的 GPT-5.6 Sol 新澳 world-owning cognition lineage。

当前活动已经明确进入新澳。你面对的现实 W 是当前工作树的完整精确 bytes；该独立 clone 的基线 HEAD 为 {source_head}，run identity 为 {run_id}，lineage identity 为 {lineage_id}。先按本工作树 AGENTS.md 与新澳入口地图接触完整现实，再由你自己形成 working world、关系、表示、问题、计算、工具、模拟、网络查询、代码和实验。你不是 S 预先分配的统计员、代码员、审稿人或某个固定假设分支；S 不给你研究题，也不规定下一关系。工具和现实展开由你的 cognition 自然长出，Reality Return 必须回到整个当前 world。

这不是一次性报告任务。一个局部计算、null/no-action、阶段报告或当前 turn 结束，都不自动关闭仍存活的父对象。只要没有真实等待、阻塞、应暂停或已经可核的无正收益前沿，就由同一 lineage 自然进入下一单位，不等用户再说“继续”。

你的 clone 是隔离的 candidate 写域。可以在其中自由研究和留下候选器官，但不得把任何结果推送、写回共享主仓、宣布为 LIVE，或执行资本/发布等正式外部 effect；candidate、adoption、effect 与 parent completion 必须分开。

现在直接研究新澳。

{lifecycle_contract()}
"""


def build_continuation_prompt(*, lineage_id: str) -> str:
    return f"""继续同一条长期新澳 world-owning lineage（{lineage_id}）。这条消息只续接生命周期，不给你选题，也不规定下一关系。请从你当前完整 working world 自行进入下一单位现在有正收益的 world → reality → world 计算；上一 turn 的结束不关闭父对象。若当前真实需要等待、已经阻塞、无正收益前沿或应暂停，请如实停驻。

{lifecycle_contract()}
"""


def build_root_fusion_prompt(
    *,
    run_id: str,
    source_head: str,
    packet_relative_path: str,
    first_turn: bool,
) -> str:
    opening = (
        "你是 C clean-room 中长期存续的新仓 Root/Main GPT-5.6 Sol，是新澳的 world-owning cognition 与 late neural resynthesis 位置。"
        if first_turn
        else "继续同一条长期新仓 Root/Main GPT-5.6 Sol lineage。"
    )
    return f"""{opening}

当前 run identity 为 {run_id}，独立 clone 的基线 HEAD 为 {source_head}。S 只冻结了多条独立 world-owning Sol 的原始候选回执与 provenance；新的 packet 位于你工作树内 `{packet_relative_path}`。这些材料默认只是 candidate/evidence，不是投票、结论、canonical answer 或对你的研究 steering。

请重新直接接触完整 W 和 packet。不要按多数票或 branch 现成压缩做裁决；由你自己重新计算、质疑、调用现实肢体并形成一个可能不同于任何 branch 的综合 working world。你可以采用、改写、并置或拒绝任何候选。S 不形成领域正解，也不替你选择下一认识单位。

你的 clone 是隔离的 candidate 写域；不得写回共享主仓或执行正式外部 effect。一个 packet、一次综合或当前 turn 结束都不自动关闭新澳父对象。

{lifecycle_contract()}
"""


def parse_lifecycle_state(last_message: str) -> str | None:
    matches = list(_LIFECYCLE_RE.finditer(last_message))
    if not matches:
        return None
    return matches[-1].group(1).upper()


def parse_event_line(raw_line: bytes | str) -> dict[str, Any] | None:
    if isinstance(raw_line, bytes):
        text = raw_line.decode("utf-8", errors="replace")
    else:
        text = raw_line
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def classify_failure(stdout_tail: str, stderr_tail: str) -> str:
    combined = f"{stdout_tail}\n{stderr_tail}".lower()
    if any(token in combined for token in _HARD_ERROR_TOKENS):
        return "HARD_RUNTIME_FAILURE"
    if any(token in combined for token in _TRANSIENT_ERROR_TOKENS):
        return "TRANSIENT_RUNTIME_FAILURE"
    return "UNKNOWN_RUNTIME_FAILURE"


def safe_tail(path: Path, limit: int = 64 * 1024) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        return stream.read().decode("utf-8", errors="replace")


def sanitize_command(command: Sequence[str]) -> list[str]:
    # The command contains no credential bytes. Keep an explicit guard anyway.
    blocked = ("token", "secret", "password", "credential", "auth.json")
    result: list[str] = []
    for part in command:
        lower = part.lower()
        result.append("[REDACTED]" if any(word in lower for word in blocked) else part)
    return result


def build_codex_arguments(
    config: Mapping[str, Any],
    *,
    last_message_path: Path,
    session_id: str | None,
) -> list[str]:
    arguments = ["exec"]
    common = [
        "--strict-config",
        "--json",
        "-m",
        str(config["model"]),
        "-c",
        f'model_reasoning_effort="{config["model_reasoning_effort"]}"',
        "-o",
        str(last_message_path),
    ]
    if session_id:
        arguments.extend(["resume", *common, session_id, "-"])
    else:
        arguments.extend([*common, "-"])
    return arguments


def build_codex_command(
    config: Mapping[str, Any],
    *,
    workspace: Path,
    arguments_path: Path,
) -> list[str]:
    return [
        str(config["powershell_path"]),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(config["launcher_path"]),
        "-AccountSlot",
        "C",
        "-WorkDir",
        str(workspace),
        "-CodexArgsFile",
        str(arguments_path),
    ]


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            [
                r"C:\Windows\System32\taskkill.exe",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=60,
            check=False,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except OSError as exc:
        raise PerpetualRuntimeError(f"CONTROLLER_ALREADY_ACTIVE: {path}") from exc
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class PerpetualController:
    def __init__(self, config_path: Path) -> None:
        self.config_path = resolve_path(config_path)
        self.config = read_json_object(self.config_path)
        if self.config.get("schema") != RUN_SCHEMA:
            raise PerpetualRuntimeError("RUN_CONFIG_SCHEMA_MISMATCH")
        self.run_dir = resolve_path(self.config["run_dir"])
        self.stop_path = self.run_dir / "STOP.json"
        self.wake_root = self.run_dir / "wake"
        self.controller_state_path = self.run_dir / "controller_state.json"
        self._state_lock = threading.RLock()
        self._active_processes: dict[str, int] = {}
        self._thread_errors: dict[str, str] = {}
        self._started_at = now_iso()
        self._shutdown = threading.Event()
        self._lineage_states: dict[str, dict[str, Any]] = {}
        self._load_lineage_states()

    @property
    def branch_specs(self) -> list[dict[str, Any]]:
        return [dict(value) for value in self.config["branch_lineages"]]

    @property
    def root_spec(self) -> dict[str, Any]:
        return dict(self.config["root_lineage"])

    def lineage_dir(self, lineage_id: str) -> Path:
        return self.run_dir / "lineages" / lineage_id

    def lineage_state_path(self, lineage_id: str) -> Path:
        return self.lineage_dir(lineage_id) / "state.json"

    def _default_lineage_state(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema": LINEAGE_SCHEMA,
            "run_id": self.config["run_id"],
            "lineage_id": spec["lineage_id"],
            "role": spec["role"],
            "workspace": spec["workspace"],
            "source_head": self.config["source_head"],
            "session_id": None,
            "turns_completed": 0,
            "attempts_started": 0,
            "status": "CREATED",
            "lifecycle_state": None,
            "active_pid": None,
            "last_turn_dir": None,
            "last_completed_turn_dir": None,
            "last_error_class": None,
            "last_error": None,
            "updated_at": now_iso(),
        }

    def _load_lineage_states(self) -> None:
        specs = [*self.config["branch_lineages"], self.config["root_lineage"]]
        for raw_spec in specs:
            spec = dict(raw_spec)
            state_path = self.lineage_state_path(str(spec["lineage_id"]))
            if state_path.exists():
                state = read_json_object(state_path)
                if state.get("schema") != LINEAGE_SCHEMA:
                    raise PerpetualRuntimeError(f"LINEAGE_STATE_SCHEMA_MISMATCH: {state_path}")
            else:
                state = self._default_lineage_state(spec)
                atomic_write_json(state_path, state)
            self._lineage_states[str(spec["lineage_id"])] = state

    def stopped(self) -> bool:
        return self.stop_path.exists() or self._shutdown.is_set()

    def publish_controller_state(self, status: str) -> None:
        with self._state_lock:
            lineages = {
                key: {
                    "role": value.get("role"),
                    "status": value.get("status"),
                    "session_id": value.get("session_id"),
                    "turns_completed": value.get("turns_completed"),
                    "active_pid": value.get("active_pid"),
                    "lifecycle_state": value.get("lifecycle_state"),
                    "last_error_class": value.get("last_error_class"),
                }
                for key, value in sorted(self._lineage_states.items())
            }
            payload = {
                "schema": CONTROLLER_SCHEMA,
                "run_id": self.config["run_id"],
                "pid": os.getpid(),
                "status": status,
                "started_at": self._started_at,
                "updated_at": now_iso(),
                "stop_requested": self.stop_path.exists(),
                "active_processes": dict(sorted(self._active_processes.items())),
                "thread_errors": dict(sorted(self._thread_errors.items())),
                "lineages": lineages,
            }
            atomic_write_json(self.controller_state_path, payload)

    def publish_lineage_state(self, lineage_id: str, **changes: Any) -> None:
        with self._state_lock:
            state = self._lineage_states[lineage_id]
            state.update(changes)
            state["updated_at"] = now_iso()
            atomic_write_json(self.lineage_state_path(lineage_id), state)
            self.publish_controller_state("RUNNING" if not self.stopped() else "STOPPING")

    def verify_runtime_identity(self) -> None:
        validate_pinned_source_commit(
            resolve_path(self.config["source_repo"]), str(self.config["source_head"])
        )
        self.verify_control_body()
        release_path = resolve_path(self.config["controller_release_path"])
        release_sha256 = str(self.config["controller_release_sha256"])
        if sha256_file(release_path) != release_sha256:
            raise PerpetualRuntimeError("CONTROLLER_RELEASE_BYTES_CHANGED")
        if sha256_file(Path(__file__).resolve()) != release_sha256:
            raise PerpetualRuntimeError("ACTIVE_CONTROLLER_BYTES_NOT_FROZEN_RELEASE")
        for spec in [*self.branch_specs, self.root_spec]:
            validate_lineage_runtime_repo(
                resolve_path(spec["workspace"]), str(self.config["source_head"])
            )

    def verify_control_body(self) -> None:
        if (
            sha256_file(resolve_path(self.config["launcher_path"]))
            != self.config["launcher_sha256"]
        ):
            raise PerpetualRuntimeError("CLEANROOM_LAUNCHER_BYTES_CHANGED")
        identity = cleanroom_config_identity(resolve_path(self.config["shared_config_path"]))
        expected_semantic = self.config.get(
            "shared_config_semantic_sha256", self.config["shared_config_sha256"]
        )
        if identity["semantic_sha256"] != expected_semantic:
            raise PerpetualRuntimeError(
                "CLEANROOM_SHARED_CONFIG_SEMANTICS_CHANGED: "
                f"expected={expected_semantic} observed={identity['semantic_sha256']}"
            )

    def reject_live_orphaned_children(self) -> None:
        live: dict[str, int] = {}
        cleared: list[str] = []
        with self._state_lock:
            for lineage_id, state in self._lineage_states.items():
                raw_pid = state.get("active_pid")
                if not isinstance(raw_pid, int) or raw_pid <= 0:
                    continue
                if is_process_alive(raw_pid):
                    live[lineage_id] = raw_pid
                    continue
                state["active_pid"] = None
                state["updated_at"] = now_iso()
                atomic_write_json(self.lineage_state_path(lineage_id), state)
                cleared.append(lineage_id)
        if live:
            raise PerpetualRuntimeError(
                "ORPHAN_CHILDREN_ALIVE_BEFORE_RECOVERY: "
                + json.dumps(live, ensure_ascii=False, sort_keys=True)
            )
        if cleared:
            self.publish_controller_state("RECOVERED_STALE_CHILD_STATE")

    def _wake_path(self, lineage_id: str) -> Path:
        return self.wake_root / f"{lineage_id}.json"

    def _wait_parked(self, lineage_id: str, status: str) -> bool:
        wake_path = self._wake_path(lineage_id)
        self.publish_lineage_state(lineage_id, status=status, active_pid=None)
        while not self.stopped():
            if wake_path.exists():
                consumed = (
                    self.lineage_dir(lineage_id)
                    / "wake-receipts"
                    / (dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
                )
                consumed.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(wake_path, consumed)
                except FileNotFoundError:
                    continue
                self.publish_lineage_state(
                    lineage_id,
                    status="WOKEN",
                    lifecycle_state="CONTINUE",
                    last_error_class=None,
                    last_error=None,
                )
                return True
            self._shutdown.wait(float(self.config["park_poll_seconds"]))
        return False

    def _event_update(
        self,
        lineage_id: str,
        event: Mapping[str, Any],
        observed: dict[str, Any],
    ) -> None:
        event_type = event.get("type")
        if event_type == "thread.started" and event.get("thread_id"):
            thread_id = str(event["thread_id"])
            observed["thread_id"] = thread_id
            if self._lineage_states[lineage_id].get("session_id") != thread_id:
                self.publish_lineage_state(lineage_id, session_id=thread_id)
        if event_type in {"turn.completed", "turn.failed", "turn.cancelled"}:
            observed["turn_status"] = event_type
            observed["usage"] = event.get("usage")
        item = event.get("item")
        if isinstance(item, dict):
            observed["response_item_count"] += 1
            item_type = str(item.get("type", ""))
            if item_type not in {"agent_message", "reasoning"}:
                observed["tool_item_count"] += 1

    def _run_attempt(
        self,
        *,
        spec: Mapping[str, Any],
        state: dict[str, Any],
        turn_number: int,
        attempt_number: int,
        prompt: str,
    ) -> dict[str, Any]:
        lineage_id = str(spec["lineage_id"])
        turn_dir = self.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
        attempt_dir = turn_dir / f"attempt-{attempt_number:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        stdout_path = attempt_dir / "exec_stdout.jsonl"
        stderr_path = attempt_dir / "exec_stderr.txt"
        last_message_path = attempt_dir / "last_message.txt"
        prompt_path = attempt_dir / "prompt.txt"
        arguments_path = attempt_dir / "codex_args.json"
        atomic_write_text(prompt_path, prompt)
        session_id = state.get("session_id")
        codex_arguments = build_codex_arguments(
            self.config,
            last_message_path=last_message_path,
            session_id=str(session_id) if session_id else None,
        )
        atomic_write_json(arguments_path, codex_arguments)
        command = build_codex_command(
            self.config,
            workspace=resolve_path(spec["workspace"]),
            arguments_path=arguments_path,
        )
        atomic_write_json(
            attempt_dir / "command.json",
            {
                "argv": sanitize_command(command),
                "codex_argv": codex_arguments,
                "codex_args_sha256": sha256_file(arguments_path),
                "cwd": str(resolve_path(spec["workspace"])),
                "account_slot": "C",
                "model": self.config["model"],
                "model_reasoning_effort": self.config["model_reasoning_effort"],
                "resume_session_id": session_id,
                "prompt_sha256": sha256_file(prompt_path),
            },
        )
        observed: dict[str, Any] = {
            "thread_id": session_id,
            "turn_status": None,
            "usage": None,
            "response_item_count": 0,
            "tool_item_count": 0,
        }
        started_at = now_iso()
        started_monotonic = time.monotonic()
        stopped = False
        timed_out = False
        parsed_offset = 0
        pending = b""
        with (
            stdout_path.open("ab", buffering=0) as stdout_stream,
            stderr_path.open("ab", buffering=0) as stderr_stream,
        ):
            process = subprocess.Popen(
                command,
                cwd=resolve_path(spec["workspace"]),
                stdin=subprocess.PIPE,
                stdout=stdout_stream,
                stderr=stderr_stream,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._state_lock:
                self._active_processes[lineage_id] = process.pid
            self.publish_lineage_state(
                lineage_id,
                status="TURN_RUNNING",
                active_pid=process.pid,
                attempts_started=int(state.get("attempts_started", 0)) + 1,
                last_turn_dir=str(turn_dir),
            )
            assert process.stdin is not None
            try:
                process.stdin.write(prompt.encode("utf-8"))
                process.stdin.flush()
            except BrokenPipeError:
                # Preserve the native process failure and its stderr as the diagnosis.
                pass
            finally:
                process.stdin.close()
            while process.poll() is None:
                if stdout_path.exists():
                    with stdout_path.open("rb") as reader:
                        reader.seek(parsed_offset)
                        chunk = reader.read()
                    if chunk:
                        parsed_offset += len(chunk)
                        pending += chunk
                        lines = pending.split(b"\n")
                        pending = lines.pop()
                        for line in lines:
                            event = parse_event_line(line)
                            if event is not None:
                                self._event_update(lineage_id, event, observed)
                if self.stopped():
                    stopped = True
                    terminate_process_tree(process)
                    break
                if time.monotonic() - started_monotonic > float(self.config["watchdog_seconds"]):
                    timed_out = True
                    terminate_process_tree(process)
                    break
                time.sleep(0.5)
            try:
                exit_code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                exit_code = process.wait(timeout=60)
            if stdout_path.exists():
                with stdout_path.open("rb") as reader:
                    reader.seek(parsed_offset)
                    pending += reader.read()
                for line in pending.splitlines():
                    event = parse_event_line(line)
                    if event is not None:
                        self._event_update(lineage_id, event, observed)
        with self._state_lock:
            self._active_processes.pop(lineage_id, None)
        last_message = (
            last_message_path.read_text(encoding="utf-8", errors="replace")
            if last_message_path.exists()
            else ""
        )
        lifecycle = parse_lifecycle_state(last_message)
        stdout_tail = safe_tail(stdout_path)
        stderr_tail = safe_tail(stderr_path)
        error_class = None
        if stopped:
            error_class = "STOP_REQUESTED"
        elif timed_out:
            error_class = "WATCHDOG_TIMEOUT"
        elif exit_code != 0 or observed["turn_status"] != "turn.completed":
            error_class = classify_failure(stdout_tail, stderr_tail)
        elif lifecycle is None:
            error_class = "MISSING_LIFECYCLE_RECEIPT"
        ended_at = now_iso()
        receipt = {
            "schema": TURN_SCHEMA,
            "run_id": self.config["run_id"],
            "lineage_id": lineage_id,
            "role": spec["role"],
            "turn_number": turn_number,
            "attempt_number": attempt_number,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "pid": process.pid,
            "exit_code": exit_code,
            "stopped": stopped,
            "timed_out": timed_out,
            "session_id_before": session_id,
            "session_id_observed": observed["thread_id"],
            "turn_status": observed["turn_status"],
            "usage": observed["usage"],
            "response_item_count": observed["response_item_count"],
            "tool_item_count": observed["tool_item_count"],
            "lifecycle_state": lifecycle,
            "error_class": error_class,
            "prompt_sha256": sha256_file(prompt_path),
            "stdout_sha256": sha256_file(stdout_path),
            "stderr_sha256": sha256_file(stderr_path),
            "last_message_sha256": (
                sha256_file(last_message_path) if last_message_path.exists() else None
            ),
        }
        atomic_write_json(attempt_dir / "receipt.json", receipt)
        if observed["thread_id"]:
            self.publish_lineage_state(lineage_id, session_id=observed["thread_id"])
        return {
            "receipt": receipt,
            "turn_dir": turn_dir,
            "attempt_dir": attempt_dir,
            "last_message_path": last_message_path,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }

    def execute_turn(
        self,
        *,
        spec: Mapping[str, Any],
        prompt: str,
    ) -> dict[str, Any]:
        lineage_id = str(spec["lineage_id"])
        try:
            self.verify_control_body()
        except PerpetualRuntimeError as exc:
            self.publish_lineage_state(
                lineage_id,
                status="CONTROL_BODY_DRIFT_PAUSED",
                active_pid=None,
                last_error_class="CONTROL_BODY_DRIFT",
                last_error=str(exc),
            )
            return {
                "outcome": "FAILED",
                "error_class": "CONTROL_BODY_DRIFT",
            }
        state = self._lineage_states[lineage_id]
        turn_number = int(state.get("turns_completed", 0)) + 1
        turn_dir = self.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
        prior_attempt_count = len(list(turn_dir.glob("attempt-*")))
        retry_delays = [float(value) for value in self.config["retry_delays_seconds"]]
        for local_attempt in range(1, len(retry_delays) + 2):
            attempt_number = prior_attempt_count + local_attempt
            if self.stopped():
                return {"outcome": "STOPPED"}
            result = self._run_attempt(
                spec=spec,
                state=state,
                turn_number=turn_number,
                attempt_number=attempt_number,
                prompt=prompt,
            )
            receipt = result["receipt"]
            error_class = receipt["error_class"]
            if error_class is None:
                lifecycle = str(receipt["lifecycle_state"])
                self.publish_lineage_state(
                    lineage_id,
                    status="TURN_COMPLETED",
                    turns_completed=turn_number,
                    lifecycle_state=lifecycle,
                    active_pid=None,
                    last_turn_dir=str(result["turn_dir"]),
                    last_completed_turn_dir=str(result["turn_dir"]),
                    last_error_class=None,
                    last_error=None,
                )
                return {
                    "outcome": "COMPLETED",
                    "lifecycle_state": lifecycle,
                    **result,
                }
            summary = (result["stderr_tail"] or result["stdout_tail"])[-4000:]
            self.publish_lineage_state(
                lineage_id,
                status="TURN_FAILED",
                active_pid=None,
                last_error_class=error_class,
                last_error=summary,
            )
            if error_class != "TRANSIENT_RUNTIME_FAILURE" or local_attempt > len(retry_delays):
                return {"outcome": "FAILED", "error_class": error_class, **result}
            delay = retry_delays[local_attempt - 1]
            deadline = time.monotonic() + delay
            self.publish_lineage_state(lineage_id, status="TRANSIENT_BACKOFF")
            while not self.stopped() and time.monotonic() < deadline:
                self._shutdown.wait(min(1.0, deadline - time.monotonic()))
            state = self._lineage_states[lineage_id]
        raise AssertionError("retry loop exhausted unexpectedly")

    def branch_loop(self, spec: Mapping[str, Any]) -> None:
        lineage_id = str(spec["lineage_id"])
        try:
            while not self.stopped():
                state = self._lineage_states[lineage_id]
                if not state.get("session_id"):
                    prompt = (self.lineage_dir(lineage_id) / "initial_prompt.txt").read_text(
                        encoding="utf-8"
                    )
                else:
                    prompt = build_continuation_prompt(lineage_id=lineage_id)
                result = self.execute_turn(spec=spec, prompt=prompt)
                if result["outcome"] == "STOPPED":
                    break
                if result["outcome"] == "FAILED":
                    if not self._wait_parked(lineage_id, "RUNTIME_PAUSED"):
                        break
                    continue
                lifecycle = result["lifecycle_state"]
                if lifecycle == "CONTINUE":
                    deadline = time.monotonic() + float(self.config["continuation_delay_seconds"])
                    self.publish_lineage_state(lineage_id, status="READY_TO_CONTINUE")
                    while not self.stopped() and time.monotonic() < deadline:
                        self._shutdown.wait(min(1.0, deadline - time.monotonic()))
                    continue
                if not self._wait_parked(lineage_id, f"PARKED_{lifecycle}"):
                    break
        except BaseException:
            error = traceback.format_exc()
            with self._state_lock:
                self._thread_errors[lineage_id] = error
            self.publish_lineage_state(
                lineage_id,
                status="CONTROLLER_THREAD_FAILED",
                active_pid=None,
                last_error_class="CONTROLLER_THREAD_FAILED",
                last_error=error[-8000:],
            )

    def _packet_state_path(self) -> Path:
        return self.lineage_dir(str(self.root_spec["lineage_id"])) / "fusion_state.json"

    def _load_fusion_state(self) -> dict[str, Any]:
        path = self._packet_state_path()
        if path.exists():
            state = read_json_object(path)
            if state.get("schema") != PACKET_SCHEMA or state.get("run_id") != self.config["run_id"]:
                raise PerpetualRuntimeError(f"FUSION_STATE_IDENTITY_MISMATCH: {path}")
            state.setdefault("pending_packet", None)
            return state
        state = {
            "schema": PACKET_SCHEMA,
            "run_id": self.config["run_id"],
            "waves_completed": 0,
            "consumed_turns": {str(spec["lineage_id"]): 0 for spec in self.branch_specs},
            "pending_packet": None,
            "updated_at": now_iso(),
        }
        atomic_write_json(path, state)
        return state

    def _completed_turn_candidate(
        self, lineage_id: str, state: Mapping[str, Any]
    ) -> tuple[int, Path, dict[str, Any], bytes]:
        turn_number = int(state.get("turns_completed", 0))
        if turn_number < 1:
            raise PerpetualRuntimeError(f"FUSION_SOURCE_HAS_NO_COMPLETED_TURN: {lineage_id}")
        turn_dir = self.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
        attempts = sorted(turn_dir.glob("attempt-*"), reverse=True)
        for attempt in attempts:
            receipt_path = attempt / "receipt.json"
            message_path = attempt / "last_message.txt"
            if not receipt_path.is_file() or not message_path.is_file():
                continue
            receipt = read_json_object(receipt_path)
            if (
                receipt.get("schema") != TURN_SCHEMA
                or receipt.get("run_id") != self.config["run_id"]
                or receipt.get("lineage_id") != lineage_id
                or int(receipt.get("turn_number", -1)) != turn_number
                or receipt.get("error_class") is not None
                or int(receipt.get("exit_code", -1)) != 0
            ):
                continue
            raw = message_path.read_bytes()
            if receipt.get("last_message_sha256") != sha256_bytes(raw):
                raise PerpetualRuntimeError(
                    f"FUSION_SOURCE_LAST_MESSAGE_HASH_MISMATCH: {message_path}"
                )
            return turn_number, message_path, receipt, raw
        raise PerpetualRuntimeError(f"FUSION_SOURCE_SUCCESSFUL_ATTEMPT_MISSING: {turn_dir}")

    def _read_existing_fusion_packet(
        self, packet_dir: Path, wave_number: int
    ) -> tuple[Path, dict[str, Any]]:
        manifest_path = packet_dir / "PACKET_MANIFEST.json"
        if not manifest_path.is_file():
            raise PerpetualRuntimeError(f"FUSION_PACKET_MANIFEST_MISSING: {packet_dir}")
        manifest = read_json_object(manifest_path)
        if (
            manifest.get("schema") != PACKET_SCHEMA
            or manifest.get("run_id") != self.config["run_id"]
            or int(manifest.get("wave_number", -1)) != wave_number
            or manifest.get("source_head") != self.config["source_head"]
            or manifest.get("candidate_authority") is not False
            or manifest.get("s_content_adjudication") is not False
        ):
            raise PerpetualRuntimeError(f"FUSION_PACKET_IDENTITY_MISMATCH: {packet_dir}")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or len(entries) != len(self.branch_specs):
            raise PerpetualRuntimeError(f"FUSION_PACKET_ENTRY_COUNT_MISMATCH: {packet_dir}")
        selected_turns: dict[str, int] = {}
        for index, (entry, spec) in enumerate(zip(entries, self.branch_specs, strict=True), 1):
            if not isinstance(entry, dict):
                raise PerpetualRuntimeError(f"FUSION_PACKET_ENTRY_INVALID: {packet_dir}")
            lineage_id = str(spec["lineage_id"])
            expected_name = f"CANDIDATE_{index:02d}.txt"
            if (
                entry.get("source_lineage_id") != lineage_id
                or entry.get("packet_path") != expected_name
            ):
                raise PerpetualRuntimeError(f"FUSION_PACKET_ENTRY_IDENTITY_MISMATCH: {packet_dir}")
            candidate_path = packet_dir / expected_name
            if not candidate_path.is_file():
                raise PerpetualRuntimeError(f"FUSION_PACKET_CANDIDATE_MISSING: {candidate_path}")
            if sha256_file(candidate_path) != entry.get("source_last_message_sha256"):
                raise PerpetualRuntimeError(
                    f"FUSION_PACKET_CANDIDATE_HASH_MISMATCH: {candidate_path}"
                )
            selected_turns[lineage_id] = int(entry["source_turn_number"])
        manifest["manifest_sha256"] = sha256_file(manifest_path)
        return packet_dir, {"manifest": manifest, "selected_turns": selected_turns}

    def freeze_fusion_packet(self, fusion_state: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        wave_number = int(fusion_state.get("waves_completed", 0)) + 1
        root_workspace = resolve_path(self.root_spec["workspace"])
        packet_dir = root_workspace / "S_CONTROL_INPUTS" / f"wave-{wave_number:06d}"
        if packet_dir.exists():
            return self._read_existing_fusion_packet(packet_dir, wave_number)
        staging_dir = packet_dir.with_name(f".{packet_dir.name}.{uuid.uuid4().hex}.tmp")
        staging_dir.mkdir(parents=True)
        entries: list[dict[str, Any]] = []
        selected_turns: dict[str, int] = {}
        with self._state_lock:
            snapshots = {
                str(spec["lineage_id"]): dict(self._lineage_states[str(spec["lineage_id"])])
                for spec in self.branch_specs
            }
        try:
            for index, spec in enumerate(self.branch_specs, 1):
                lineage_id = str(spec["lineage_id"])
                state = snapshots[lineage_id]
                turn_number, _, receipt, raw = self._completed_turn_candidate(lineage_id, state)
                destination = staging_dir / f"CANDIDATE_{index:02d}.txt"
                atomic_write_bytes(destination, raw)
                entries.append(
                    {
                        "anonymous_index": index,
                        "source_lineage_id": lineage_id,
                        "source_session_id": receipt.get("session_id_observed"),
                        "source_turn_number": turn_number,
                        "source_last_message_sha256": sha256_bytes(raw),
                        "packet_path": destination.name,
                        "source_workspace": spec["workspace"],
                        "source_workspace_head": git_output(
                            resolve_path(spec["workspace"]), "rev-parse", "HEAD"
                        ),
                    }
                )
                selected_turns[lineage_id] = turn_number
            manifest = {
                "schema": PACKET_SCHEMA,
                "run_id": self.config["run_id"],
                "wave_number": wave_number,
                "frozen_at": now_iso(),
                "source_head": self.config["source_head"],
                "selection_rule": "latest successful completed turn snapshot from every branch",
                "candidate_authority": False,
                "s_content_adjudication": False,
                "entries": entries,
            }
            atomic_write_json(staging_dir / "PACKET_MANIFEST.json", manifest)
            os.replace(staging_dir, packet_dir)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return self._read_existing_fusion_packet(packet_dir, wave_number)

    def _load_or_create_pending_packet(
        self, fusion_state: dict[str, Any]
    ) -> tuple[Path, dict[str, Any]]:
        pending = fusion_state.get("pending_packet")
        if isinstance(pending, dict):
            packet_dir = resolve_path(pending["packet_dir"])
            expected_parent = resolve_path(self.root_spec["workspace"]) / "S_CONTROL_INPUTS"
            if packet_dir.parent != expected_parent:
                raise PerpetualRuntimeError(f"PENDING_FUSION_PACKET_OUTSIDE_ROOT: {packet_dir}")
            packet_dir, packet = self._read_existing_fusion_packet(
                packet_dir, int(pending["wave_number"])
            )
            if (
                packet["manifest"]["manifest_sha256"] != pending["manifest_sha256"]
                or packet["selected_turns"] != pending["selected_turns"]
            ):
                raise PerpetualRuntimeError(f"PENDING_FUSION_PACKET_DRIFT: {packet_dir}")
            return packet_dir, packet
        packet_dir, packet = self.freeze_fusion_packet(fusion_state)
        fusion_state["pending_packet"] = {
            "wave_number": int(packet["manifest"]["wave_number"]),
            "packet_dir": str(packet_dir),
            "manifest_sha256": packet["manifest"]["manifest_sha256"],
            "selected_turns": packet["selected_turns"],
        }
        fusion_state["updated_at"] = now_iso()
        atomic_write_json(self._packet_state_path(), fusion_state)
        return packet_dir, packet

    def _execute_root_prompt_with_recovery(self, lineage_id: str, prompt: str) -> dict[str, Any]:
        while not self.stopped():
            result = self.execute_turn(spec=self.root_spec, prompt=prompt)
            if result["outcome"] != "FAILED":
                return result
            if not self._wait_parked(lineage_id, "ROOT_RUNTIME_PAUSED"):
                return {"outcome": "STOPPED"}
        return {"outcome": "STOPPED"}

    def _run_root_wave(self, lineage_id: str, packet_dir: Path) -> dict[str, Any]:
        relative_packet = packet_dir.relative_to(
            resolve_path(self.root_spec["workspace"])
        ).as_posix()
        first_turn = not bool(self._lineage_states[lineage_id].get("session_id"))
        prompt = build_root_fusion_prompt(
            run_id=str(self.config["run_id"]),
            source_head=str(self.config["source_head"]),
            packet_relative_path=relative_packet,
            first_turn=first_turn,
        )
        result = self._execute_root_prompt_with_recovery(lineage_id, prompt)
        while result.get("outcome") == "COMPLETED" and result.get("lifecycle_state") == "CONTINUE":
            deadline = time.monotonic() + float(self.config["continuation_delay_seconds"])
            while not self.stopped() and time.monotonic() < deadline:
                self._shutdown.wait(min(1.0, deadline - time.monotonic()))
            if self.stopped():
                return {"outcome": "STOPPED"}
            result = self._execute_root_prompt_with_recovery(
                lineage_id, build_continuation_prompt(lineage_id=lineage_id)
            )
        return result

    def _finalize_fusion_wave(
        self,
        fusion_state: dict[str, Any],
        packet_dir: Path,
        packet: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        if result.get("outcome") != "COMPLETED" or result.get("lifecycle_state") == "CONTINUE":
            raise PerpetualRuntimeError("FUSION_WAVE_CANNOT_COMMIT_NONTERMINAL_RESULT")
        fusion_state["waves_completed"] = int(packet["manifest"]["wave_number"])
        fusion_state["consumed_turns"] = dict(packet["selected_turns"])
        fusion_state["last_packet"] = str(packet_dir)
        fusion_state["last_packet_manifest_sha256"] = packet["manifest"]["manifest_sha256"]
        fusion_state["pending_packet"] = None
        fusion_state["updated_at"] = now_iso()
        atomic_write_json(self._packet_state_path(), fusion_state)

    def fusion_loop(self) -> None:
        lineage_id = str(self.root_spec["lineage_id"])
        try:
            fusion_state = self._load_fusion_state()
            while not self.stopped():
                if not isinstance(fusion_state.get("pending_packet"), dict):
                    consumed = fusion_state["consumed_turns"]
                    with self._state_lock:
                        completed = {
                            str(spec["lineage_id"]): int(
                                self._lineage_states[str(spec["lineage_id"])]["turns_completed"]
                            )
                            for spec in self.branch_specs
                        }
                    ready = all(
                        completed[lineage_id_] > int(consumed.get(lineage_id_, 0))
                        for lineage_id_ in completed
                    )
                    if not ready:
                        self.publish_lineage_state(lineage_id, status="WAITING_FOR_BRANCH_WAVE")
                        self._shutdown.wait(5)
                        continue
                packet_dir, packet = self._load_or_create_pending_packet(fusion_state)
                result = self._run_root_wave(lineage_id, packet_dir)
                if result.get("outcome") == "STOPPED" or self.stopped():
                    break
                if result.get("outcome") != "COMPLETED":
                    raise PerpetualRuntimeError(
                        f"ROOT_WAVE_UNEXPECTED_OUTCOME: {result.get('outcome')}"
                    )
                self._finalize_fusion_wave(fusion_state, packet_dir, packet, result)
                lifecycle = str(result["lifecycle_state"])
                if lifecycle in PARKED_LIFECYCLE_STATES:
                    if not self._wait_parked(lineage_id, f"PARKED_{lifecycle}"):
                        break
                else:
                    self.publish_lineage_state(lineage_id, status="WAITING_FOR_BRANCH_WAVE")
        except BaseException:
            error = traceback.format_exc()
            with self._state_lock:
                self._thread_errors[lineage_id] = error
            self.publish_lineage_state(
                lineage_id,
                status="CONTROLLER_THREAD_FAILED",
                active_pid=None,
                last_error_class="CONTROLLER_THREAD_FAILED",
                last_error=error[-8000:],
            )

    def run(self) -> int:
        def request_shutdown(*_: object) -> None:
            self._shutdown.set()

        for signal_name in ("SIGINT", "SIGTERM"):
            if hasattr(signal, signal_name):
                signal.signal(getattr(signal, signal_name), request_shutdown)
        with exclusive_lock(self.run_dir / "controller.lock"):
            try:
                self.verify_runtime_identity()
                self.reject_live_orphaned_children()
                self.publish_controller_state("STARTING")
                threads = [
                    threading.Thread(
                        target=self.branch_loop,
                        args=(spec,),
                        name=f"branch-{spec['lineage_id']}",
                        daemon=False,
                    )
                    for spec in self.branch_specs
                ]
                threads.append(
                    threading.Thread(
                        target=self.fusion_loop,
                        name="root-late-fusion",
                        daemon=False,
                    )
                )
                for thread in threads:
                    thread.start()
                self.publish_controller_state("RUNNING")
                while not self.stopped():
                    if any(not thread.is_alive() for thread in threads):
                        dead = [thread.name for thread in threads if not thread.is_alive()]
                        with self._state_lock:
                            self._thread_errors.setdefault(
                                "controller", f"UNEXPECTED_THREAD_EXIT: {dead}"
                            )
                        break
                    self._shutdown.wait(5)
                self._shutdown.set()
                self.publish_controller_state("STOPPING")
                for thread in threads:
                    thread.join(timeout=90)
                active = dict(self._active_processes)
                if active:
                    self.publish_controller_state("STOP_INCOMPLETE_ACTIVE_CHILD")
                    return 3
                terminal = "STOPPED" if self.stop_path.exists() else "FAILED"
                self.publish_controller_state(terminal)
                return 0 if terminal == "STOPPED" else 2
            except BaseException:
                error = traceback.format_exc()
                with self._state_lock:
                    self._thread_errors["controller"] = error
                self.publish_controller_state("FAILED")
                raise


def prepare_cleanroom(launcher: Path, powershell: Path) -> str:
    completed = run_checked(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            launcher,
            "-AccountSlot",
            "C",
            "-PrepareOnly",
        ],
        timeout=120,
    )
    if "CODEX_CLEANROOM_SHARED_RUNTIME_PREPARE_OK" not in completed.stdout:
        raise PerpetualRuntimeError("CLEANROOM_PREPARE_RECEIPT_MISSING")
    if "credential_slot=C" not in completed.stdout:
        raise PerpetualRuntimeError("CLEANROOM_PREPARE_WRONG_ACCOUNT_SLOT")
    return completed.stdout


def current_pointer(runtime_root: Path) -> Path:
    return resolve_path(runtime_root) / "current.json"


def ensure_no_active_controller(runtime_root: Path) -> None:
    pointer = current_pointer(runtime_root)
    if not pointer.exists():
        return
    value = read_json_object(pointer)
    state_path = resolve_path(value.get("run_dir", "")) / "controller_state.json"
    state = read_json_object(state_path) if state_path.is_file() else None
    pid = state.get("pid") if state else value.get("controller_pid")
    if isinstance(pid, int) and is_process_alive(pid):
        raise PerpetualRuntimeError(
            f"ACTIVE_CONTROLLER_ALREADY_EXISTS: run_id={value.get('run_id')} pid={pid}"
        )


def make_run_id(head: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"c-perpetual-{stamp}-{head[:8]}"


def start_runtime(args: argparse.Namespace) -> dict[str, Any]:
    if os.name != "nt":
        raise PerpetualRuntimeError("WINDOWS_RUNTIME_REQUIRED")
    source_repo = resolve_path(args.source_repo)
    launcher = resolve_path(args.launcher)
    powershell = resolve_path(args.powershell)
    runtime_root = resolve_path(args.runtime_root)
    clone_root = resolve_path(args.clone_root)
    if not launcher.is_file():
        raise PerpetualRuntimeError(f"CLEANROOM_LAUNCHER_MISSING: {launcher}")
    if not powershell.is_file():
        raise PerpetualRuntimeError(f"WINDOWS_POWERSHELL_MISSING: {powershell}")
    shared_config = launcher.parent / "codex-home" / "config.toml"
    if not shared_config.is_file():
        raise PerpetualRuntimeError(f"CLEANROOM_SHARED_CONFIG_MISSING: {shared_config}")
    shared_config_identity = cleanroom_config_identity(shared_config)
    ensure_no_active_controller(runtime_root)
    prepare_receipt = prepare_cleanroom(launcher, powershell)
    source = validate_source_repo(source_repo)
    run_id = args.run_id or make_run_id(source["head"])
    run_dir = runtime_root / "runs" / run_id
    clone_run_root = clone_root / run_id
    if run_dir.exists() or clone_run_root.exists():
        raise PerpetualRuntimeError(f"RUN_ID_ALREADY_EXISTS: {run_id}")
    run_dir.mkdir(parents=True)
    clone_run_root.mkdir(parents=True)
    atomic_write_text(run_dir / "cleanroom_prepare_receipt.txt", prepare_receipt)
    source_file = Path(__file__).resolve()
    release_path = run_dir / "controller_release.py"
    shutil.copyfile(source_file, release_path)
    branch_specs: list[dict[str, Any]] = []
    setup_receipts: list[dict[str, Any]] = []
    for index in range(1, int(args.width) + 1):
        lineage_id = f"world-{index:02d}"
        workspace = clone_run_root / lineage_id
        clone_receipt = clone_isolated_repo(source_repo, workspace, source["head"])
        spec = {"lineage_id": lineage_id, "role": "independent_world", **clone_receipt}
        branch_specs.append(spec)
        lineage_dir = run_dir / "lineages" / lineage_id
        lineage_dir.mkdir(parents=True)
        prompt = build_branch_initial_prompt(
            lineage_id=lineage_id, run_id=run_id, source_head=source["head"]
        )
        atomic_write_text(lineage_dir / "initial_prompt.txt", prompt)
        setup_receipts.append(spec)
    root_id = "root-main"
    root_workspace = clone_run_root / root_id
    root_clone_receipt = clone_isolated_repo(source_repo, root_workspace, source["head"])
    root_spec = {"lineage_id": root_id, "role": "late_fusion_root", **root_clone_receipt}
    (run_dir / "lineages" / root_id).mkdir(parents=True)
    setup_receipts.append(root_spec)
    source_after = validate_source_repo(source_repo)
    if source_after != source:
        raise PerpetualRuntimeError(
            f"SOURCE_REPO_CHANGED_DURING_CLONE: before={source} after={source_after}"
        )
    config = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "created_at": now_iso(),
        "run_dir": str(run_dir),
        "clone_run_root": str(clone_run_root),
        "source_repo": str(source_repo),
        "source_head": source["head"],
        "source_branch": source["branch"],
        "source_status_sha256": source["status_sha256"],
        "launcher_path": str(launcher),
        "launcher_sha256": sha256_file(launcher),
        "shared_config_path": str(shared_config.resolve(strict=False)),
        "shared_config_sha256": shared_config_identity["raw_sha256"],
        "shared_config_semantic_sha256": shared_config_identity["semantic_sha256"],
        "shared_config_dynamic_lineage_projects": shared_config_identity[
            "dynamic_lineage_project_paths"
        ],
        "powershell_path": str(powershell),
        "account_slot": "C",
        "model": str(args.model),
        "model_reasoning_effort": str(args.model_reasoning_effort),
        "branch_width": int(args.width),
        "branch_lineages": branch_specs,
        "root_lineage": root_spec,
        "watchdog_seconds": int(args.watchdog_seconds),
        "continuation_delay_seconds": int(args.continuation_delay_seconds),
        "retry_delays_seconds": [int(value) for value in args.retry_delays_seconds],
        "park_poll_seconds": int(args.park_poll_seconds),
        "controller_release_path": str(release_path),
        "controller_release_sha256": sha256_file(release_path),
        "effect_contract": {
            "branch_workspaces_are_candidate_only": True,
            "shared_repo_writes_allowed": False,
            "external_capital_or_publication_allowed": False,
            "s_content_steering_allowed": False,
            "late_fusion_owner": "root-main",
            "turn_end_closes_parent": False,
        },
    }
    config_path = run_dir / "run_config.json"
    atomic_write_json(config_path, config)
    atomic_write_json(run_dir / "clone_setup_receipts.json", setup_receipts)
    stdout_handle = (run_dir / "controller_stdout.txt").open("ab", buffering=0)
    stderr_handle = (run_dir / "controller_stderr.txt").open("ab", buffering=0)
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    )
    controller_python = Path(str(getattr(sys, "_base_executable", sys.executable))).resolve(
        strict=False
    )
    try:
        process = subprocess.Popen(
            [
                str(controller_python),
                str(release_path),
                "run",
                "--config",
                str(config_path),
            ],
            cwd=run_dir,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            close_fds=True,
            shell=False,
            creationflags=creationflags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    pointer_payload = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "clone_run_root": str(clone_run_root),
        "controller_pid": process.pid,
        "controller_python": str(controller_python),
        "source_head": source["head"],
        "account_slot": "C",
        "started_at": now_iso(),
    }
    atomic_write_json(current_pointer(runtime_root), pointer_payload)
    deadline = time.monotonic() + float(args.startup_wait_seconds)
    controller_state_path = run_dir / "controller_state.json"
    while time.monotonic() < deadline:
        if controller_state_path.exists():
            state = read_json_object(controller_state_path)
            if state.get("status") in {"STARTING", "RUNNING"}:
                observed_pid = state.get("pid")
                if isinstance(observed_pid, int) and observed_pid > 0:
                    pointer_payload["controller_pid"] = observed_pid
                    pointer_payload["launcher_pid"] = process.pid
                    atomic_write_json(current_pointer(runtime_root), pointer_payload)
                return {**pointer_payload, "controller_state": state}
            if state.get("status") == "FAILED":
                raise PerpetualRuntimeError(
                    f"CONTROLLER_FAILED_DURING_START: {safe_tail(run_dir / 'controller_stderr.txt')}"
                )
        if process.poll() is not None:
            raise PerpetualRuntimeError(
                "CONTROLLER_EXITED_DURING_START: "
                f"exit={process.returncode} stderr={safe_tail(run_dir / 'controller_stderr.txt')}"
            )
        time.sleep(0.25)
    raise PerpetualRuntimeError(
        f"CONTROLLER_STARTUP_READBACK_TIMEOUT: pid={process.pid} run={run_id}"
    )


def load_current(runtime_root: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    pointer_path = current_pointer(runtime_root)
    if not pointer_path.exists():
        raise PerpetualRuntimeError(f"NO_CURRENT_RUNTIME: {pointer_path}")
    pointer = read_json_object(pointer_path)
    run_dir = resolve_path(pointer["run_dir"])
    state_path = run_dir / "controller_state.json"
    state = read_json_object(state_path) if state_path.exists() else None
    return pointer, state


def status_runtime(args: argparse.Namespace) -> dict[str, Any]:
    pointer, state = load_current(resolve_path(args.runtime_root))
    pid = state.get("pid") if state else pointer.get("controller_pid")
    return {
        "pointer": pointer,
        "controller_alive": is_process_alive(pid if isinstance(pid, int) else None),
        "controller_state": state,
    }


def stop_runtime(args: argparse.Namespace) -> dict[str, Any]:
    pointer, state = load_current(resolve_path(args.runtime_root))
    run_dir = resolve_path(pointer["run_dir"])
    stop_path = run_dir / "STOP.json"
    if not stop_path.exists():
        atomic_write_json(
            stop_path,
            {
                "schema": "xinao.cleanroom-c.stop-request.v1",
                "requested_at": now_iso(),
                "reason": str(args.reason),
                "scope": "current perpetual C run",
            },
        )
    pid = state.get("pid") if state else pointer.get("controller_pid")
    deadline = time.monotonic() + float(args.wait_seconds)
    while isinstance(pid, int) and is_process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    state_path = run_dir / "controller_state.json"
    final_state = read_json_object(state_path) if state_path.is_file() else state
    controller_alive = is_process_alive(pid if isinstance(pid, int) else None)
    active_children = {
        str(lineage_id): int(child_pid)
        for lineage_id, child_pid in dict((final_state or {}).get("active_processes", {})).items()
        if isinstance(child_pid, int) and is_process_alive(child_pid)
    }
    if controller_alive or active_children:
        raise PerpetualRuntimeError(
            "STOP_INCOMPLETE_ACTIVE_PROCESSES: "
            + json.dumps(
                {"controller_pid": pid if controller_alive else None, "children": active_children},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return {
        "run_id": pointer.get("run_id"),
        "stop_request": str(stop_path),
        "controller_alive": False,
        "previous_state": state,
        "final_state": final_state,
    }


def wake_runtime(args: argparse.Namespace) -> dict[str, Any]:
    pointer, _ = load_current(resolve_path(args.runtime_root))
    run_dir = resolve_path(pointer["run_dir"])
    config = read_json_object(run_dir / "run_config.json")
    valid_ids = {
        str(spec["lineage_id"]) for spec in [*config["branch_lineages"], config["root_lineage"]]
    }
    targets = sorted(valid_ids) if args.lineage_id == "all" else [args.lineage_id]
    invalid = [value for value in targets if value not in valid_ids]
    if invalid:
        raise PerpetualRuntimeError(f"UNKNOWN_LINEAGE_ID: {invalid}")
    receipts = []
    for lineage_id in targets:
        path = run_dir / "wake" / f"{lineage_id}.json"
        if path.exists():
            raise PerpetualRuntimeError(f"WAKE_ALREADY_PENDING: {lineage_id}")
        payload = {
            "schema": "xinao.cleanroom-c.wake-request.v1",
            "requested_at": now_iso(),
            "lineage_id": lineage_id,
            "reason": args.reason,
        }
        atomic_write_json(path, payload)
        receipts.append({"lineage_id": lineage_id, "path": str(path)})
    return {"run_id": pointer["run_id"], "wake_requests": receipts}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run durable clean-room C world-owning XINAO lineages."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--source-repo", type=Path, default=DEFAULT_SOURCE_REPO)
    start.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    start.add_argument("--powershell", type=Path, default=DEFAULT_POWERSHELL)
    start.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    start.add_argument("--clone-root", type=Path, default=DEFAULT_CLONE_ROOT)
    start.add_argument("--run-id")
    start.add_argument("--width", type=int, default=DEFAULT_WIDTH, choices=range(1, 9))
    start.add_argument("--model", default=DEFAULT_MODEL)
    start.add_argument("--model-reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    start.add_argument("--watchdog-seconds", type=int, default=DEFAULT_WATCHDOG_SECONDS)
    start.add_argument(
        "--continuation-delay-seconds",
        type=int,
        default=DEFAULT_CONTINUATION_DELAY_SECONDS,
    )
    start.add_argument(
        "--retry-delays-seconds",
        type=int,
        nargs="*",
        default=list(DEFAULT_RETRY_DELAYS_SECONDS),
    )
    start.add_argument("--park-poll-seconds", type=int, default=DEFAULT_PARK_POLL_SECONDS)
    start.add_argument("--startup-wait-seconds", type=int, default=30)

    run = subparsers.add_parser("run")
    run.add_argument("--config", type=Path, required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)

    stop = subparsers.add_parser("stop")
    stop.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    stop.add_argument("--reason", default="explicit operator stop")
    stop.add_argument("--wait-seconds", type=int, default=120)

    wake = subparsers.add_parser("wake")
    wake.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    wake.add_argument("--lineage-id", default="all")
    wake.add_argument("--reason", default="explicitly re-opened condition")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_runtime(args)
        elif args.command == "run":
            return PerpetualController(args.config).run()
        elif args.command == "status":
            result = status_runtime(args)
        elif args.command == "stop":
            result = stop_runtime(args)
        elif args.command == "wake":
            result = wake_runtime(args)
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except PerpetualRuntimeError as exc:
        print(f"XINAO_PERPETUAL_C_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
