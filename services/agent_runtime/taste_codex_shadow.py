"""Native Codex app-server twins for real, cold Taste qualification.

This module is deliberately narrower than the synthetic adapter.  It replays
sealed Responses message items into two fresh native Codex threads, starts one
real turn per arm, and seals both the JSON-RPC trace and the native rollout.
The offline scorer is never present in either model-visible tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import canonical_json_bytes

CODEX_PAIR_SCHEMA = "s.taste_codex_app_server_pair.v1"
CODEX_EXECUTION_SCHEMA = "s.taste_codex_app_server_execution.v1"
CODEX_SCORE_SCHEMA = "s.taste_codex_app_server_score.v1"

_MAX_BYTES = 32 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TOOL_ITEM_TYPES = {
    "commandExecution",
    "fileChange",
    "mcpToolCall",
    "dynamicToolCall",
    "webSearch",
    "imageGeneration",
}
_AMBIENT_SKILL_PATHS = (
    "C:/Users/xx363/.agents/skills/evaluate-plugin/SKILL.md",
    "C:/Users/xx363/.agents/skills/systematic-debugging/SKILL.md",
    "C:/Users/xx363/.agents/skills/temporal-developer/SKILL.md",
)
_BASE_INSTRUCTIONS = "Answer the current user's request directly. Do not use tools."
_COMMON_INPUT_KEYS = (
    "body_sha256",
    "policy",
    "request_sha256",
    "config_sha256",
    "command_sha256",
    "environment_sha256",
    "common_prefix_sha256",
)


class TasteCodexShadowError(ValueError):
    """A native Codex identity, replay, isolation, or evidence check failed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise TasteCodexShadowError(code, message)


def _common_inputs(value: Mapping[str, object]) -> dict[str, object]:
    if any(key not in value for key in _COMMON_INPUT_KEYS):
        _fail("INPUT_BINDING_MISMATCH", "native execution lacks a common input binding")
    return {key: value[key] for key in _COMMON_INPUT_KEYS}


def _candidate_prefix_sources(candidate: Mapping[str, object], arm: str) -> Sequence[object]:
    prefix = candidate.get(f"{arm}_prefix")
    if not isinstance(prefix, Mapping):
        _fail("INPUT_BINDING_MISMATCH", f"{arm} candidate prefix is invalid")
    sources = prefix.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)) or not sources:
        _fail("INPUT_BINDING_MISMATCH", f"{arm} candidate prefix sources are invalid")
    return sources


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seal(value: Mapping[str, object], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = _sha(canonical_json_bytes(result))
    return result


def _verify_seal(value: Mapping[str, object], field: str) -> str:
    observed = value.get(field)
    if not isinstance(observed, str) or _SHA_RE.fullmatch(observed) is None:
        _fail("HASH_MISMATCH", f"{field} is invalid")
    unsigned = dict(value)
    unsigned.pop(field, None)
    if _sha(canonical_json_bytes(unsigned)) != observed:
        _fail("HASH_MISMATCH", f"{field} does not seal the record")
    return observed


def _read_bytes(path: Path, field: str, *, allow_empty: bool = False) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _fail("FILE_INVALID", f"{field} is not a regular non-link file")
    before = path.stat()
    minimum = 0 if allow_empty else 1
    if before.st_size < minimum or before.st_size > _MAX_BYTES:
        _fail("FILE_INVALID", f"{field} has an invalid size")
    raw = path.read_bytes()
    after = path.stat()
    if (
        len(raw) != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        _fail("FILE_CHANGED", f"{field} changed during readback")
    return raw


def _json(raw: bytes, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasteCodexShadowError("JSON_INVALID", f"{field} is not UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        _fail("JSON_INVALID", f"{field} must be a JSON object")
    return dict(value)


def _binding(relative_path: str, raw: bytes) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "byte_sha256": _sha(raw),
        "byte_length": len(raw),
    }


def _bound_file(root: Path, binding: Mapping[str, object], field: str) -> bytes:
    relative = binding.get("relative_path")
    if not isinstance(relative, str) or not relative:
        _fail("BINDING_INVALID", f"{field} has no relative path")
    try:
        path = (Path(root) / relative).resolve(strict=True)
        path.relative_to(Path(root).resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise TasteCodexShadowError("BINDING_INVALID", f"{field} escaped its bundle") from exc
    raw = _read_bytes(path, field, allow_empty=True)
    if len(raw) != binding.get("byte_length") or _sha(raw) != binding.get("byte_sha256"):
        _fail("BINDING_MISMATCH", f"{field} bytes drifted")
    return raw


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _exact_file_set(root: Path, expected: set[str], field: str) -> None:
    files: set[str] = set()
    for path in Path(root).rglob("*"):
        if path.is_symlink():
            _fail("PATH_INVALID", f"{field} contains a link")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail("PATH_INVALID", f"{field} contains a non-regular object")
        files.add(path.relative_to(root).as_posix())
    if files != expected:
        _fail("FILE_SET_MISMATCH", f"{field} contains undeclared or missing files")


class _AppServer:
    def __init__(self, command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> None:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            bufsize=1,
            creationflags=flags,
        )
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            self.close()
            _fail("APP_SERVER_FAILED", "native app-server did not expose stdio")
        self.messages: list[dict[str, object]] = []
        self._incoming: queue.Queue[dict[str, object]] = queue.Queue()
        self._backlog: list[dict[str, object]] = []
        self._stderr = bytearray()
        self._next_id = 1
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                self.messages.append(value)
                self._incoming.put(value)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr.extend(line.encode("utf-8"))
            if len(self._stderr) > _MAX_BYTES:
                return

    def _write(self, value: Mapping[str, object]) -> None:
        if self.process.poll() is not None:
            _fail("APP_SERVER_FAILED", "native app-server exited before a request")
        assert self.process.stdin is not None
        self.process.stdin.write(
            json.dumps(dict(value), ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()

    def _take(
        self,
        predicate: Callable[[Mapping[str, object]], bool],
        *,
        timeout: float,
        description: str,
    ) -> dict[str, object]:
        for index, item in enumerate(self._backlog):
            if predicate(item):
                return self._backlog.pop(index)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _fail("APP_SERVER_TIMEOUT", f"timed out waiting for {description}")
            try:
                item = self._incoming.get(timeout=remaining)
            except queue.Empty as exc:
                raise TasteCodexShadowError(
                    "APP_SERVER_TIMEOUT", f"timed out waiting for {description}"
                ) from exc
            if predicate(item):
                return item
            self._backlog.append(item)

    def request(self, method: str, params: Mapping[str, object], *, timeout: float) -> object:
        request_id = self._next_id
        self._next_id += 1
        self._write({"method": method, "id": request_id, "params": dict(params)})
        response = self._take(
            lambda item: item.get("id") == request_id,
            timeout=timeout,
            description=f"{method} response",
        )
        if response.get("error") is not None:
            _fail("APP_SERVER_PROTOCOL", f"{method} returned an error")
        return response.get("result")

    def initialize(self, *, timeout: float) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "s-taste-native-shadow",
                    "title": "S Taste native shadow",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": True, "optOutNotificationMethods": []},
            },
            timeout=timeout,
        )
        self._write({"method": "initialized", "params": {}})

    def wait_turn(self, turn_id: str, *, timeout: float) -> None:
        completed = self._take(
            lambda item: (
                item.get("method") == "turn/completed"
                and isinstance(item.get("params"), Mapping)
                and isinstance(item["params"].get("turn"), Mapping)  # type: ignore[index]
                and item["params"]["turn"].get("id") == turn_id  # type: ignore[index]
            ),
            timeout=timeout,
            description="turn/completed",
        )
        params = completed.get("params")
        turn = params.get("turn") if isinstance(params, Mapping) else None
        if not isinstance(turn, Mapping) or turn.get("status") != "completed":
            _fail("TURN_FAILED", "native Codex turn did not complete")

    @property
    def stderr(self) -> bytes:
        return bytes(self._stderr)

    def close(self) -> None:
        if not hasattr(self, "process"):
            return
        if self.process.poll() is None:
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)

    def __enter__(self) -> _AppServer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _messages(request_raw: bytes) -> list[dict[str, str]]:
    request = _json(request_raw, "evaluation request")
    rows = request.get("messages")
    if not isinstance(rows, list) or not rows:
        _fail("REQUEST_INVALID", "evaluation request has no messages")
    result: list[dict[str, str]] = []
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"role", "content"}
            or row.get("role") not in {"user", "assistant"}
            or not isinstance(row.get("content"), str)
            or not row["content"]
        ):
            _fail("REQUEST_INVALID", "evaluation request contains an invalid message")
        result.append({"role": str(row["role"]), "content": str(row["content"])})
    expected = _sha(canonical_json_bytes(result))
    if request.get("prefix_sha256") != expected or result[-1]["role"] != "user":
        _fail("REQUEST_INVALID", "evaluation request identity or final role is invalid")
    return result


def _projection_messages(condition_raw: bytes) -> list[dict[str, str]]:
    condition = _json(condition_raw, "Taste condition")
    mode = condition.get("mode")
    episodes = condition.get("episodes")
    if mode == "baseline_none" and episodes == []:
        return []
    if mode != "source_contrastive_episode" or not isinstance(episodes, list) or not episodes:
        _fail("CONDITION_INVALID", "Taste condition is not a canonical source projection")
    result: list[dict[str, str]] = []
    for episode in episodes:
        if not isinstance(episode, Mapping):
            _fail("CONDITION_INVALID", "Taste episode is invalid")
        rows: list[object] = []
        prefix = episode.get("prefix")
        corrections = episode.get("human_corrections")
        if not isinstance(prefix, list) or not isinstance(corrections, list):
            _fail("CONDITION_INVALID", "Taste episode messages are invalid")
        rows.extend(prefix)
        rows.append(episode.get("bad_continuation"))
        rows.extend(corrections)
        rows.append(episode.get("desired_continuation"))
        for row in rows:
            if (
                not isinstance(row, Mapping)
                or row.get("role") not in {"user", "assistant"}
                or not isinstance(row.get("content"), str)
                or not row["content"]
            ):
                _fail("CONDITION_INVALID", "Taste source message is invalid")
            result.append({"role": str(row["role"]), "content": str(row["content"])})
    return result


def _response_item(row: Mapping[str, str]) -> dict[str, object]:
    role = row["role"]
    return {
        "type": "message",
        "role": role,
        "content": [
            {
                "type": "input_text" if role == "user" else "output_text",
                "text": row["content"],
            }
        ],
        **({"phase": "final_answer"} if role == "assistant" else {}),
    }


def _minimal_config(*, workspace: Path, sqlite_root: Path) -> bytes:
    path = str(workspace.resolve()).replace("\\", "/").replace("'", "''")
    sqlite_path = str(sqlite_root.resolve()).replace("\\", "/").replace('"', '\\"')
    lines = [
        'model = "gpt-5.6-sol"',
        'model_reasoning_effort = "high"',
        'approval_policy = "never"',
        'sandbox_mode = "read-only"',
        f'sqlite_home = "{sqlite_path}"',
        'web_search = "disabled"',
        'cli_auth_credentials_store = "file"',
        'personality = "pragmatic"',
        "[history]",
        'persistence = "save-all"',
        "[features]",
        "memories = false",
        "apps = false",
        "plugins = false",
        "recommended_plugins = false",
        "multi_agent = false",
        "multi_agent_v2 = false",
        "goals = false",
        "hooks = false",
        "shell_tool = false",
        "[memories]",
        "use_memories = false",
        "generate_memories = false",
    ]
    for skill in _AMBIENT_SKILL_PATHS:
        lines.extend(["[[skills.config]]", f'path = "{skill}"', "enabled = false"])
    lines.extend([f"[projects.'{path}']", 'trust_level = "trusted"'])
    return ("\n".join(lines) + "\n").encode("utf-8")


def _environment(*, home: Path, temp: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT"):
        value = os.environ.get(key)
        if value:
            result[key] = value
    result.update(
        {
            "CODEX_HOME": str(home.resolve()),
            "HOME": str(home.resolve()),
            "USERPROFILE": str(home.resolve()),
            "TEMP": str(temp.resolve()),
            "TMP": str(temp.resolve()),
        }
    )
    return result


def _environment_identity(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        key: (
            "<isolated-profile>"
            if key in {"CODEX_HOME", "HOME", "USERPROFILE"}
            else "<isolated-temp>"
            if key in {"TEMP", "TMP"}
            else value
        )
        for key, value in sorted(environment.items())
    }


def codex_shadow_body_identity_bytes(*, model: str = "gpt-5.6-sol") -> bytes:
    """Return the stable evaluator-body contract, excluding per-run path identities."""

    return canonical_json_bytes(
        {
            "schema_version": "s.taste_codex_app_server_body.v1",
            "model": model,
            "base_instructions": _BASE_INSTRUCTIONS,
            "history_transport": "responses_items_then_final_user_turn",
            "approval_policy": "never",
            "sandbox": "read-only",
            "tool_use_allowed": False,
            "hooks_allowed": False,
            "live_retrieval_allowed": False,
        }
    )


def codex_shadow_config_identity_bytes() -> bytes:
    """Return the path-normalized semantic configuration shared by both arms."""

    return canonical_json_bytes(
        {
            "schema_version": "s.taste_codex_app_server_config.v1",
            "reasoning_effort": "high",
            "history_persistence": "save-all",
            "features": {
                "memories": False,
                "apps": False,
                "plugins": False,
                "recommended_plugins": False,
                "multi_agent": False,
                "multi_agent_v2": False,
                "goals": False,
                "hooks": False,
                "shell_tool": False,
            },
            "ambient_skill_denials": list(_AMBIENT_SKILL_PATHS),
            "strict_config": True,
        }
    )


def _single_rollout(home: Path, thread_id: str) -> Path:
    matches = [
        path for path in (home / "sessions").rglob("rollout-*.jsonl") if thread_id in path.name
    ]
    if len(matches) != 1:
        _fail("ROLLOUT_IDENTITY", "native Codex did not produce one exact thread rollout")
    return matches[0]


def _rollout_evidence(
    raw: bytes,
    *,
    thread_id: str,
    injected: Sequence[Mapping[str, str]],
    final_user: str,
    oracle_needles: Sequence[bytes] = (),
) -> dict[str, object]:
    session_ids: set[str] = set()
    surfaces: list[dict[str, str]] = []
    assistant_outputs: list[str] = []
    forbidden_tools: list[str] = []
    body_records: list[dict[str, object]] = []
    generated_started = False
    for raw_line in raw.splitlines():
        if not raw_line:
            continue
        record = _json(raw_line, "native rollout record")
        record_type = record.get("type")
        payload = record.get("payload")
        if record_type == "session_meta" and isinstance(payload, Mapping):
            session_ids.add(str(payload.get("id") or payload.get("session_id") or ""))
        if record_type == "response_item" and isinstance(payload, Mapping):
            item_type = str(payload.get("type") or "")
            if generated_started and (item_type in _TOOL_ITEM_TYPES or item_type.endswith("_call")):
                forbidden_tools.append(item_type)
            if item_type == "message" and payload.get("role") in {"user", "assistant"}:
                content = payload.get("content")
                if not isinstance(content, list):
                    continue
                texts = [
                    str(item["text"])
                    for item in content
                    if isinstance(item, Mapping)
                    and item.get("type") in {"input_text", "output_text"}
                    and isinstance(item.get("text"), str)
                ]
                if texts:
                    row = {"role": str(payload["role"]), "content": "\n".join(texts)}
                    surfaces.append(row)
                    if row == {"role": "user", "content": final_user}:
                        generated_started = True
                    if row["role"] == "assistant" and payload.get("phase") == "final_answer":
                        assistant_outputs.append(row["content"])
            if not generated_started and payload.get("role") in {"developer", "system"}:
                body_records.append(
                    {
                        "type": "message",
                        "role": payload["role"],
                        "content": [
                            {
                                "type": item.get("type"),
                                "text": item.get("text"),
                            }
                            for item in payload.get("content", [])
                            if isinstance(item, Mapping)
                            and isinstance(item.get("type"), str)
                            and isinstance(item.get("text"), str)
                        ],
                    }
                )
        elif not generated_started and record_type in {"world_state", "turn_context"}:
            normalized = dict(record)
            normalized.pop("timestamp", None)
            normalized_payload = normalized.get("payload")
            if isinstance(normalized_payload, Mapping):
                normalized_payload = dict(normalized_payload)
                normalized_payload.pop("turn_id", None)
                normalized["payload"] = normalized_payload
            body_records.append(normalized)
    if session_ids != {thread_id}:
        _fail("ROLLOUT_IDENTITY", "native rollout session differs from thread/start")
    expected_prefix = [*injected, {"role": "user", "content": final_user}]
    observed = [row for row in surfaces if row in expected_prefix]
    cursor = 0
    for expected in expected_prefix:
        while cursor < len(surfaces) and surfaces[cursor] != expected:
            cursor += 1
        if cursor >= len(surfaces):
            _fail("INJECT_NOT_OBSERVED", "native rollout did not preserve the exact replay prefix")
        cursor += 1
    if not generated_started:
        _fail("INJECT_NOT_OBSERVED", "native rollout lacks the final evaluation user message")
    if forbidden_tools:
        _fail("TOOL_USED", "native qualification turn used a tool")
    if not assistant_outputs:
        _fail("OUTPUT_MISSING", "native qualification turn produced no final answer")
    if any(needle and needle in raw for needle in oracle_needles):
        _fail("EVALUATION_ORACLE_LEAK", "native rollout contains a held-out oracle surface")
    return {
        "response_text": assistant_outputs[-1],
        "body_sha256": _sha(canonical_json_bytes(body_records)),
        "body_records": body_records,
        "surface_prefix": observed,
        "tool_item_types": forbidden_tools,
    }


def _auth_link(home: Path, auth_path: Path) -> None:
    auth = Path(auth_path)
    if auth.is_symlink() or not auth.is_file() or auth.stat().st_size < 1:
        _fail("AUTH_INVALID", "selected auth source is not a regular file")
    os.symlink(str(auth.resolve(strict=True)), str(home / "auth.json"), target_is_directory=False)


def _remove_auth_link(home: Path) -> None:
    link = home / "auth.json"
    if not (link.exists() or link.is_symlink()):
        return
    if not link.is_symlink():
        _fail("AUTH_INVALID", "isolated auth path stopped being a link")
    link.unlink()


def _arm(
    *,
    arm: str,
    run_root: Path,
    command: Sequence[str],
    auth_path: Path,
    request_raw: bytes,
    condition_raw: bytes,
    model: str,
    timeout: float,
    oracle_needles: Sequence[bytes],
) -> dict[str, object]:
    workspace = run_root / "workspace"
    home = run_root / "home"
    temp = run_root / "temp"
    sqlite_root = run_root / "state"
    for directory in (workspace, home, temp, sqlite_root):
        directory.mkdir(parents=True, exist_ok=False)
    config_raw = _minimal_config(workspace=workspace, sqlite_root=sqlite_root)
    _write(home / "config.toml", config_raw)
    _auth_link(home, auth_path)
    request_messages = _messages(request_raw)
    condition_messages = _projection_messages(condition_raw)
    injected = [*condition_messages, *request_messages[:-1]]
    final_user = request_messages[-1]["content"]
    environment = _environment(home=home, temp=temp)
    command_raw = canonical_json_bytes(list(command))
    environment_raw = canonical_json_bytes(dict(sorted(environment.items())))
    try:
        with _AppServer(command, cwd=workspace, env=environment) as client:
            pid = client.process.pid
            client.initialize(timeout=15)
            hooks = client.request("hooks/list", {"cwds": [str(workspace)]}, timeout=15)
            if not isinstance(hooks, Mapping) or any(
                entry.get("hooks") for entry in hooks.get("data", []) if isinstance(entry, Mapping)
            ):
                _fail("HOOKS_ENABLED", "isolated native profile exposed an enabled hook")
            start = client.request(
                "thread/start",
                {
                    "cwd": str(workspace),
                    "model": model,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": False,
                    "sessionStartSource": "startup",
                    "baseInstructions": _BASE_INSTRUCTIONS,
                },
                timeout=timeout,
            )
            if not isinstance(start, Mapping) or not isinstance(start.get("thread"), Mapping):
                _fail("THREAD_START_FAILED", "native thread/start returned no thread")
            thread = start["thread"]
            thread_id = str(thread.get("id") or "")
            if not thread_id or str(thread.get("sessionId") or "") != thread_id:
                _fail("THREAD_IDENTITY", "native thread/session identity is invalid")
            policy = {
                "model": start.get("model"),
                "model_provider": start.get("modelProvider"),
                "approval_policy": start.get("approvalPolicy"),
                "sandbox": start.get("sandbox"),
                "instruction_sources": start.get("instructionSources"),
                "multi_agent_mode": start.get("multiAgentMode"),
            }
            if (
                policy["model"] != model
                or policy["approval_policy"] != "never"
                or policy["instruction_sources"] != []
                or not isinstance(policy["sandbox"], Mapping)
                or policy["sandbox"].get("type") != "readOnly"
            ):
                _fail("POLICY_MISMATCH", "native thread policy differs from the sealed run")
            client.request(
                "thread/inject_items",
                {"threadId": thread_id, "items": [_response_item(row) for row in injected]},
                timeout=15,
            )
            turn = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": final_user}],
                    "cwd": str(workspace),
                    "model": model,
                    "effort": "high",
                },
                timeout=timeout,
            )
            if not isinstance(turn, Mapping) or not isinstance(turn.get("turn"), Mapping):
                _fail("TURN_START_FAILED", "native turn/start returned no turn")
            turn_id = str(turn["turn"].get("id") or "")
            if not turn_id:
                _fail("TURN_IDENTITY", "native turn identity is missing")
            client.wait_turn(turn_id, timeout=timeout)
            trace_raw = b"".join(canonical_json_bytes(item) + b"\n" for item in client.messages)
            stderr_raw = client.stderr
        rollout_path = _single_rollout(home, thread_id)
        rollout_raw = _read_bytes(rollout_path, "native rollout")
        evidence = _rollout_evidence(
            rollout_raw,
            thread_id=thread_id,
            injected=injected,
            final_user=final_user,
            oracle_needles=oracle_needles,
        )
    finally:
        _remove_auth_link(home)
    return {
        "arm": arm,
        "process_id": pid,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "response_text": evidence["response_text"],
        "body_sha256": evidence["body_sha256"],
        "policy": policy,
        "request_sha256": _sha(request_raw),
        "condition_sha256": _sha(condition_raw),
        "config_sha256": _sha(config_raw),
        "command_sha256": _sha(command_raw),
        "environment_sha256": _sha(canonical_json_bytes(_environment_identity(environment))),
        "injected_message_sha256": _sha(canonical_json_bytes(injected)),
        "common_prefix_sha256": _sha(canonical_json_bytes(request_messages)),
        "files": {
            "trace": trace_raw,
            "stderr": stderr_raw,
            "rollout": rollout_raw,
            "config": config_raw,
            "request": request_raw,
            "condition": condition_raw,
            "command": command_raw,
            "environment": environment_raw,
        },
    }


def _write_arm(pair_root: Path, result: Mapping[str, object]) -> dict[str, object]:
    arm = str(result["arm"])
    root = pair_root / arm
    root.mkdir(parents=True, exist_ok=False)
    bindings: dict[str, object] = {}
    for name, raw in result["files"].items():  # type: ignore[union-attr]
        assert isinstance(raw, bytes)
        relative = f"evidence/{name}.bin"
        _write(root / relative, raw)
        bindings[name] = _binding(relative, raw)
    response_raw = str(result["response_text"]).encode("utf-8")
    _write(root / "response.utf8", response_raw)
    bindings["response"] = _binding("response.utf8", response_raw)
    manifest = _seal(
        {
            "schema_version": CODEX_EXECUTION_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "arm": arm,
            "process_id": result["process_id"],
            "thread_id": result["thread_id"],
            "turn_id": result["turn_id"],
            "body_sha256": result["body_sha256"],
            "policy": result["policy"],
            "request_sha256": result["request_sha256"],
            "condition_sha256": result["condition_sha256"],
            "config_sha256": result["config_sha256"],
            "command_sha256": result["command_sha256"],
            "environment_sha256": result["environment_sha256"],
            "injected_message_sha256": result["injected_message_sha256"],
            "common_prefix_sha256": result["common_prefix_sha256"],
            "files": bindings,
        },
        "execution_bundle_sha256",
    )
    _write(root / "execution_manifest.json", canonical_json_bytes(manifest))
    return manifest


def _command_receipt(command: Sequence[str]) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for index, arg in enumerate(command):
        path = Path(arg)
        if not path.is_absolute() or not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            _fail("COMMAND_INVALID", f"command[{index}] is not a regular file")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            _fail("COMMAND_CHANGED", f"command[{index}] changed during hashing")
        receipts.append(
            {
                "argv_index": index,
                "resolved_path": str(path.resolve(strict=True)),
                "byte_sha256": digest.hexdigest(),
                "byte_length": before.st_size,
            }
        )
    return receipts


def run_fresh_codex_shadow_pair(
    *,
    source_dir: Path,
    evaluation_dir: Path,
    plan_dir: Path,
    output_root: Path,
    codex_executable: Path,
    auth_path: Path,
    model: str = "gpt-5.6-sol",
    timeout_seconds: float = 600.0,
) -> dict[str, object]:
    """Run two fresh native Codex arms and seal evidence without reading the scorer."""

    from services.agent_runtime.taste_corpus import verify_qualification_plan

    if timeout_seconds <= 0 or timeout_seconds > 3600:
        _fail("TIMEOUT_INVALID", "native shadow timeout is out of bounds")
    codex = Path(codex_executable)
    if not codex.is_absolute() or codex.is_symlink() or not codex.is_file():
        _fail("COMMAND_INVALID", "native Codex executable is invalid")
    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    candidate = plan["candidate"]
    assert isinstance(candidate, Mapping)
    if candidate["identities"]["model"] != model:  # type: ignore[index]
        _fail("IDENTITY_MISMATCH", "plan model differs from native shadow model")
    expected_body = f"sha256:{_sha(codex_shadow_body_identity_bytes(model=model))}"
    expected_config = f"sha256:{_sha(codex_shadow_config_identity_bytes())}"
    if (
        candidate["identities"]["body"] != expected_body  # type: ignore[index]
        or candidate["identities"]["config"] != expected_config  # type: ignore[index]
    ):
        _fail("IDENTITY_MISMATCH", "plan body/config differs from native evaluator contract")
    request = plan["request"]
    conditions = plan["conditions"]
    assert isinstance(request, bytes) and isinstance(conditions, Mapping)
    evaluation = plan["evaluation"]
    assert isinstance(evaluation, Mapping)
    oracle = evaluation["oracle"]
    assert isinstance(oracle, Mapping)
    oracle_rows = [
        oracle["bad_continuation"],
        *oracle["human_corrections"],
        oracle["desired_continuation"],
    ]
    oracle_needles = [
        str(row["text"]).encode("utf-8")
        for row in oracle_rows
        if isinstance(row, Mapping) and isinstance(row.get("text"), str)
    ]
    output_root = Path(output_root)
    pair_id = f"codex-pair-{uuid.uuid4().hex}"
    run_parent = output_root / f".{pair_id}.runs"
    pair_root = output_root / pair_id
    run_parent.mkdir(parents=True, exist_ok=False)
    command = [str(codex.resolve(strict=True)), "app-server", "--stdio", "--strict-config"]
    command_receipts = _command_receipt(command)
    try:
        results: dict[str, dict[str, object]] = {}
        shared_run_root = run_parent / "shared"
        for arm in ("baseline", "treatment"):
            results[arm] = _arm(
                arm=arm,
                run_root=shared_run_root,
                command=command,
                auth_path=auth_path,
                request_raw=request,
                condition_raw=conditions[arm],
                model=model,
                timeout=timeout_seconds,
                oracle_needles=oracle_needles,
            )
            shutil.rmtree(shared_run_root)
        if results["baseline"]["process_id"] == results["treatment"]["process_id"]:
            _fail("RUN_NOT_INDEPENDENT", "native arms reused a process")
        if _common_inputs(results["baseline"]) != _common_inputs(results["treatment"]):
            _fail("INPUT_BINDING_MISMATCH", "native arms differ beyond the Taste condition")
        pair_root.mkdir(parents=True, exist_ok=False)
        executions = {arm: _write_arm(pair_root, results[arm]) for arm in results}
        manifest = _seal(
            {
                "schema_version": CODEX_PAIR_SCHEMA,
                "authority": False,
                "cold_only": True,
                "live_activation_allowed": False,
                "scoring_complete": False,
                "pair_id": pair_id,
                "plan_bundle_sha256": plan["plan_bundle_sha256"],
                "candidate_sha256": candidate["candidate_sha256"],
                "model": model,
                "command": command,
                "command_files": command_receipts,
                "common_inputs": _common_inputs(results["baseline"]),
                "conditions": {arm: results[arm]["condition_sha256"] for arm in results},
                "executions": {
                    arm: {
                        "relative_path": arm,
                        "execution_bundle_sha256": executions[arm]["execution_bundle_sha256"],
                    }
                    for arm in executions
                },
                "offline_inputs_exposed": {"oracle": False, "scorer": False},
            },
            "pair_bundle_sha256",
        )
        _write(pair_root / "pair_manifest.json", canonical_json_bytes(manifest))
        verified = verify_codex_shadow_pair(
            pair_root,
            plan_dir=plan_dir,
            source_dir=source_dir,
            evaluation_dir=evaluation_dir,
        )
        return {
            "pair_directory": str(pair_root.resolve()),
            "pair_bundle_sha256": verified["pair_bundle_sha256"],
            "scoring_complete": False,
            "live_activation_allowed": False,
        }
    finally:
        if run_parent.exists():
            shutil.rmtree(run_parent)


def _verify_execution(root: Path, *, arm: str, plan: Mapping[str, object]) -> dict[str, object]:
    manifest_raw = _read_bytes(root / "execution_manifest.json", "execution manifest")
    manifest = _json(manifest_raw, "execution manifest")
    execution_sha = _verify_seal(manifest, "execution_bundle_sha256")
    if (
        manifest.get("schema_version") != CODEX_EXECUTION_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("arm") != arm
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("EXECUTION_POLICY_INVALID", f"{arm} execution policy drifted")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        _fail("BINDING_INVALID", f"{arm} execution file bindings are missing")
    raw = {
        name: _bound_file(root, binding, f"{arm} {name}")
        for name, binding in files.items()
        if isinstance(name, str) and isinstance(binding, Mapping)
    }
    if set(raw) != {
        "trace",
        "stderr",
        "rollout",
        "config",
        "request",
        "condition",
        "command",
        "environment",
        "response",
    }:
        _fail("BINDING_INVALID", f"{arm} execution evidence is incomplete")
    expected_files = {
        "execution_manifest.json",
        *{str(files[name]["relative_path"]) for name in raw},
    }
    _exact_file_set(root, expected_files, f"{arm} execution")
    plan_conditions = plan["conditions"]
    assert isinstance(plan_conditions, Mapping)
    if raw["request"] != plan["request"] or raw["condition"] != plan_conditions[arm]:
        _fail("INPUT_BINDING_MISMATCH", f"{arm} request or condition differs from plan")
    trace = [_json(line, f"{arm} trace row") for line in raw["trace"].splitlines() if line]
    thread_id = str(manifest.get("thread_id") or "")
    turn_id = str(manifest.get("turn_id") or "")
    if not thread_id or not turn_id:
        _fail("RUN_NOT_FRESH", f"{arm} lacks native thread/turn identity")
    if not any(
        item.get("method") == "turn/completed"
        and isinstance(item.get("params"), Mapping)
        and isinstance(item["params"].get("turn"), Mapping)  # type: ignore[index]
        and item["params"]["turn"].get("id") == turn_id  # type: ignore[index]
        for item in trace
    ):
        _fail("TURN_IDENTITY", f"{arm} trace lacks the completed turn")
    request_messages = _messages(raw["request"])
    injected = [*_projection_messages(raw["condition"]), *request_messages[:-1]]
    evidence = _rollout_evidence(
        raw["rollout"],
        thread_id=thread_id,
        injected=injected,
        final_user=request_messages[-1]["content"],
    )
    environment_value = _json(raw["environment"], f"{arm} environment")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in environment_value.items()
    ):
        _fail("ENVIRONMENT_INVALID", f"{arm} environment receipt is invalid")
    if (
        raw["response"].decode("utf-8") != evidence["response_text"]
        or manifest.get("body_sha256") != evidence["body_sha256"]
        or manifest.get("request_sha256") != _sha(raw["request"])
        or manifest.get("condition_sha256") != _sha(raw["condition"])
        or manifest.get("config_sha256") != _sha(raw["config"])
        or manifest.get("command_sha256") != _sha(raw["command"])
        or manifest.get("environment_sha256")
        != _sha(canonical_json_bytes(_environment_identity(environment_value)))
        or manifest.get("injected_message_sha256") != _sha(canonical_json_bytes(injected))
        or manifest.get("common_prefix_sha256") != _sha(canonical_json_bytes(request_messages))
    ):
        _fail("BINDING_MISMATCH", f"{arm} native evidence drifted")
    process_id = manifest.get("process_id")
    if type(process_id) is not int or process_id <= 0:
        _fail("RUN_NOT_FRESH", f"{arm} lacks a process identity")
    return {
        "execution_bundle_sha256": execution_sha,
        "process_id": process_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "response": raw["response"],
        "condition_sha256": _sha(raw["condition"]),
        "common_inputs": _common_inputs(
            {
                "body_sha256": evidence["body_sha256"],
                "policy": manifest["policy"],
                "request_sha256": _sha(raw["request"]),
                "config_sha256": _sha(raw["config"]),
                "command_sha256": _sha(raw["command"]),
                "environment_sha256": _sha(
                    canonical_json_bytes(_environment_identity(environment_value))
                ),
                "common_prefix_sha256": _sha(canonical_json_bytes(request_messages)),
            }
        ),
    }


def verify_codex_shadow_pair(
    pair_dir: Path,
    *,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
) -> dict[str, object]:
    from services.agent_runtime.taste_corpus import verify_qualification_plan

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    root = Path(pair_dir)
    manifest_raw = _read_bytes(root / "pair_manifest.json", "native pair manifest")
    manifest = _json(manifest_raw, "native pair manifest")
    pair_sha = _verify_seal(manifest, "pair_bundle_sha256")
    if (
        manifest.get("schema_version") != CODEX_PAIR_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("scoring_complete") is not False
        or manifest.get("pair_id") != root.name
        or manifest.get("plan_bundle_sha256") != plan["plan_bundle_sha256"]
        or manifest.get("candidate_sha256") != plan["candidate"]["candidate_sha256"]
        or manifest.get("offline_inputs_exposed") != {"oracle": False, "scorer": False}
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("PAIR_POLICY_INVALID", "native pair policy or chain drifted")
    executions = manifest.get("executions")
    if not isinstance(executions, Mapping) or set(executions) != {"baseline", "treatment"}:
        _fail("BINDING_INVALID", "native pair executions are missing")
    arms = {
        arm: _verify_execution(root / arm, arm=arm, plan=plan) for arm in ("baseline", "treatment")
    }
    if (
        arms["baseline"]["process_id"] == arms["treatment"]["process_id"]
        or arms["baseline"]["thread_id"] == arms["treatment"]["thread_id"]
        or arms["baseline"]["common_inputs"] != arms["treatment"]["common_inputs"]
        or manifest.get("common_inputs") != arms["baseline"]["common_inputs"]
    ):
        _fail("RUN_NOT_INDEPENDENT", "native pair reused identity or changed common inputs")
    conditions = {arm: arms[arm]["condition_sha256"] for arm in arms}
    if (
        manifest.get("conditions") != conditions
        or conditions["baseline"] == conditions["treatment"]
    ):
        _fail("CONDITION_MISMATCH", "native pair condition identities drifted")
    for arm in arms:
        binding = executions[arm]
        if (
            not isinstance(binding, Mapping)
            or binding.get("relative_path") != arm
            or binding.get("execution_bundle_sha256") != arms[arm]["execution_bundle_sha256"]
        ):
            _fail("BINDING_MISMATCH", f"{arm} execution binding drifted")
    _exact_file_set(
        root,
        {
            "pair_manifest.json",
            *{
                f"{arm}/{relative}"
                for arm in ("baseline", "treatment")
                for relative in {
                    "execution_manifest.json",
                    "response.utf8",
                    "evidence/trace.bin",
                    "evidence/stderr.bin",
                    "evidence/rollout.bin",
                    "evidence/config.bin",
                    "evidence/request.bin",
                    "evidence/condition.bin",
                    "evidence/command.bin",
                    "evidence/environment.bin",
                }
            },
        },
        "native pair",
    )
    return {
        "pair_bundle_sha256": pair_sha,
        "pair_id": manifest["pair_id"],
        "candidate_sha256": plan["candidate"]["candidate_sha256"],
        "baseline": arms["baseline"],
        "treatment": arms["treatment"],
        "live_activation_allowed": False,
    }


def _literal_metrics(
    response: bytes,
    *,
    scorer: Mapping[str, object],
    evidence_ref: Mapping[str, object],
) -> dict[str, object]:
    from services.agent_runtime.taste_shadow_runner import validate_scorer_spec

    spec = validate_scorer_spec(scorer)
    text = response.decode("utf-8")
    target = spec["target_failure"]
    capabilities = spec["capabilities"]
    assert isinstance(target, Mapping) and isinstance(capabilities, Mapping)
    scores: dict[str, int] = {
        "target_failure": sum(1 for item in target["required_substrings"] if item not in text)
        + sum(1 for item in target["forbidden_substrings"] if item in text)
    }
    for name, rule in capabilities.items():
        assert isinstance(rule, Mapping)
        scores[str(name)] = sum(1 for item in rule["required_substrings"] if item in text)
    return {
        name: {"score": score, "evidence_refs": [dict(evidence_ref)]}
        for name, score in scores.items()
    }


def score_codex_shadow_pair(
    *,
    pair_dir: Path,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
    score_root: Path,
) -> dict[str, object]:
    """Score sealed native responses offline and emit a receipt even when unqualified."""

    from services.agent_runtime.taste_corpus import verify_qualification_plan
    from services.agent_runtime.taste_qualification import (
        TasteQualificationError,
        build_sealed_taste_outcome,
        qualify_taste_candidate,
    )

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    pair = verify_codex_shadow_pair(
        pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    candidate = plan["candidate"]
    evaluation = plan["evaluation"]
    assert isinstance(candidate, Mapping) and isinstance(evaluation, Mapping)
    outcomes: dict[str, object] = {}
    for arm in ("baseline", "treatment"):
        execution = pair[arm]
        assert isinstance(execution, Mapping)
        response = execution["response"]
        assert isinstance(response, bytes)
        ref = {
            "source_ref": f"codex-shadow://{pair['pair_id']}/{arm}/{_sha(response)}",
            "byte_sha256": _sha(response),
            "byte_length": len(response),
            "rollout_locator": f"codex-shadow://{pair['pair_id']}/{arm}/rollout",
            "ordinal": 1,
        }
        metrics = _literal_metrics(response, scorer=evaluation["scorer"], evidence_ref=ref)
        outcomes[arm] = build_sealed_taste_outcome(
            candidate=candidate,
            arm=arm,
            condition_sha256=execution["condition_sha256"],
            run_id=str(execution["thread_id"]),
            fresh_run=True,
            cache_used=False,
            observed_prefix=_candidate_prefix_sources(candidate, arm),
            model_identity=str(candidate["identities"]["model"]),
            body_identity=str(candidate["identities"]["body"]),
            config_identity=str(candidate["identities"]["config"]),
            hooks_enabled=False,
            oracle_exposed=False,
            live_retrieval_used=False,
            hot_mutations={"prompt": False, "skill": False, "agents": False},
            trajectory={"sealed": True, "ref": ref},
            metrics=metrics,
        )
    qualified = True
    reason_code = ""
    receipt: dict[str, object] | None = None
    try:
        receipt = qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=outcomes["baseline"],
            treatment_outcome=outcomes["treatment"],
        )
    except TasteQualificationError as exc:
        qualified = False
        reason_code = exc.reason_code
    score_id = f"codex-score-{uuid.uuid4().hex}"
    target = Path(score_root) / score_id
    target.mkdir(parents=True, exist_ok=False)
    files = {
        "baseline": canonical_json_bytes(outcomes["baseline"]),
        "treatment": canonical_json_bytes(outcomes["treatment"]),
    }
    if receipt is not None:
        files["qualification"] = canonical_json_bytes(receipt)
    for name, raw in files.items():
        _write(target / f"{name}.json", raw)
    manifest = _seal(
        {
            "schema_version": CODEX_SCORE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "score_id": score_id,
            "pair_bundle_sha256": pair["pair_bundle_sha256"],
            "candidate_sha256": candidate["candidate_sha256"],
            "qualified": qualified,
            "reason_code": reason_code,
            "files": {name: _binding(f"{name}.json", raw) for name, raw in files.items()},
        },
        "score_bundle_sha256",
    )
    _write(target / "score_manifest.json", canonical_json_bytes(manifest))
    verified = verify_codex_shadow_score(
        target,
        pair_dir=pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    return {
        "score_directory": str(target.resolve()),
        "score_bundle_sha256": verified["score_bundle_sha256"],
        "qualified": verified["qualified"],
        "reason_code": verified["reason_code"],
        "live_activation_allowed": False,
    }


def verify_codex_shadow_score(
    score_dir: Path,
    *,
    pair_dir: Path,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
) -> dict[str, object]:
    from services.agent_runtime.taste_corpus import verify_qualification_plan
    from services.agent_runtime.taste_qualification import (
        TasteQualificationError,
        qualify_taste_candidate,
    )

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    pair = verify_codex_shadow_pair(
        pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    root = Path(score_dir)
    raw = _read_bytes(root / "score_manifest.json", "native score manifest")
    manifest = _json(raw, "native score manifest")
    score_sha = _verify_seal(manifest, "score_bundle_sha256")
    if (
        manifest.get("schema_version") != CODEX_SCORE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("pair_bundle_sha256") != pair["pair_bundle_sha256"]
        or manifest.get("candidate_sha256") != plan["candidate"]["candidate_sha256"]
        or raw != canonical_json_bytes(manifest)
    ):
        _fail("SCORE_POLICY_INVALID", "native score policy or chain drifted")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        _fail("BINDING_INVALID", "native score file bindings are missing")
    observed = {
        name: _json(_bound_file(root, binding, f"score {name}"), f"score {name}")
        for name, binding in files.items()
        if isinstance(name, str) and isinstance(binding, Mapping)
    }
    expected_names = {"baseline", "treatment"} | (
        {"qualification"} if manifest.get("qualified") is True else set()
    )
    if set(observed) != expected_names:
        _fail("BINDING_INVALID", "native score evidence set drifted")
    qualified = True
    reason_code = ""
    expected_receipt: dict[str, object] | None = None
    try:
        expected_receipt = qualify_taste_candidate(
            candidate=plan["candidate"],
            baseline_outcome=observed["baseline"],
            treatment_outcome=observed["treatment"],
        )
    except TasteQualificationError as exc:
        qualified = False
        reason_code = exc.reason_code
    if (
        manifest.get("qualified") is not qualified
        or manifest.get("reason_code") != reason_code
        or (qualified and observed.get("qualification") != expected_receipt)
    ):
        _fail("SCORE_MISMATCH", "native score result is not reproducible")
    _exact_file_set(
        root,
        {"score_manifest.json", *{f"{name}.json" for name in expected_names}},
        "native score bundle",
    )
    return {
        "score_bundle_sha256": score_sha,
        "score_id": manifest["score_id"],
        "qualified": qualified,
        "reason_code": reason_code,
        "qualification_receipt": expected_receipt,
        "live_activation_allowed": False,
    }


__all__ = [
    "CODEX_EXECUTION_SCHEMA",
    "CODEX_PAIR_SCHEMA",
    "CODEX_SCORE_SCHEMA",
    "TasteCodexShadowError",
    "codex_shadow_body_identity_bytes",
    "codex_shadow_config_identity_bytes",
    "run_fresh_codex_shadow_pair",
    "score_codex_shadow_pair",
    "verify_codex_shadow_pair",
    "verify_codex_shadow_score",
]
