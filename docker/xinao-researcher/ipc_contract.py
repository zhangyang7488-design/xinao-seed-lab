"""Bounded Unix-socket IPC contract for dual-container tool execution.

Transport (authful) and tool-executor (no-auth) share this schema only.
No second ledger, daemon, or Owner-authority channel lives here.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import uuid
from typing import Any, Mapping

CONTRACT_ID = "xinao.dual_container_ipc.v1"
REQUEST_SCHEMA = "xinao.dual_container_ipc_request.v1"
RESPONSE_SCHEMA = "xinao.dual_container_ipc_response.v1"

EPISODE_LAB_ROOT = "/episode-lab"
PRIVATE_TMP_ROOT = "/tmp"

MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 262_144
MAX_STDOUT_BYTES = 65_536
MAX_TIMEOUT_MS = 30_000
MIN_TIMEOUT_MS = 50

ALLOWED_OPS = frozenset({"ping", "list_dir", "read_file", "write_file", "shell_exec"})

_REL_PATH_OK = re.compile(r"^(?!\.)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")


class IpcContractError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = str(detail)[:2000]


def authority_clamp_flags() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def parse_json_object(raw: bytes, *, reason_code: str = "JSON_INVALID") -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IpcContractError(reason_code, str(exc)) from exc
    if not isinstance(value, dict):
        raise IpcContractError(reason_code, "object required")
    return value


def normalize_lab_relative_path(relative: str) -> str:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise IpcContractError("PATH_INVALID", "empty or null path")
    cleaned = relative.replace("\\", "/").strip()
    if cleaned.startswith("/") or cleaned.startswith("~"):
        raise IpcContractError("PATH_ABSOLUTE_FORBIDDEN", cleaned[:80])
    if ".." in cleaned.split("/"):
        raise IpcContractError("PATH_TRAVERSAL", cleaned[:80])
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned or cleaned == ".":
        raise IpcContractError("PATH_INVALID", "cwd-only path")
    if not _REL_PATH_OK.match(cleaned):
        # Allow empty segments denial already handled; still accept simple names.
        parts = cleaned.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise IpcContractError("PATH_INVALID", cleaned[:80])
        for part in parts:
            if not re.fullmatch(r"[A-Za-z0-9._-]+", part):
                raise IpcContractError("PATH_INVALID", cleaned[:80])
    return cleaned


def encode_frame(message: Mapping[str, Any]) -> bytes:
    body = canonical_bytes(dict(message))
    if len(body) > MAX_RESPONSE_BYTES and len(body) > MAX_REQUEST_BYTES:
        # Caller may still send; size checks live at decode / handlers.
        pass
    return struct.pack("!Q", len(body)) + body


def decode_frame(buffer: bytes, *, maximum: int = MAX_REQUEST_BYTES) -> tuple[dict[str, Any], bytes]:
    if len(buffer) < 8:
        raise IpcContractError("FRAME_INCOMPLETE", str(len(buffer)))
    (length,) = struct.unpack("!Q", buffer[:8])
    if length > maximum:
        raise IpcContractError("REQUEST_TOO_LARGE", str(length))
    if len(buffer) < 8 + length:
        raise IpcContractError("FRAME_INCOMPLETE", str(len(buffer)))
    raw = buffer[8 : 8 + length]
    remaining = buffer[8 + length :]
    message = parse_json_object(raw, reason_code="REQUEST_JSON_INVALID")
    return message, remaining


def build_request(
    *,
    op: str,
    episode_id: str,
    args: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    timeout_ms: int = 5_000,
) -> dict[str, Any]:
    if not isinstance(op, str) or op not in ALLOWED_OPS:
        raise IpcContractError("OP_UNKNOWN", str(op))
    if not isinstance(episode_id, str) or not episode_id.strip():
        raise IpcContractError("EPISODE_ID_INVALID", "required")
    if type(timeout_ms) is not int or isinstance(timeout_ms, bool):
        raise IpcContractError("TIMEOUT_INVALID", str(timeout_ms))
    if timeout_ms < MIN_TIMEOUT_MS or timeout_ms > MAX_TIMEOUT_MS:
        raise IpcContractError("TIMEOUT_OUT_OF_RANGE", str(timeout_ms))
    rid = request_id if request_id is not None else uuid.uuid4().hex
    if not isinstance(rid, str) or not rid or len(rid) > 128:
        raise IpcContractError("REQUEST_ID_INVALID", str(rid)[:80])
    payload_args = dict(args or {})
    if not isinstance(payload_args, dict):
        raise IpcContractError("ARGS_INVALID", "object required")
    request = {
        "schema_version": REQUEST_SCHEMA,
        "contract_id": CONTRACT_ID,
        "request_id": rid,
        "episode_id": episode_id.strip(),
        "op": op,
        "args": payload_args,
        "timeout_ms": int(timeout_ms),
        **authority_clamp_flags(),
    }
    raw = canonical_bytes(request)
    if len(raw) > MAX_REQUEST_BYTES:
        raise IpcContractError("REQUEST_TOO_LARGE", str(len(raw)))
    return request


def validate_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IpcContractError("REQUEST_JSON_INVALID", "object required")
    if payload.get("schema_version") not in {REQUEST_SCHEMA, None}:
        # Accept missing schema for older synthetic callers; require contract if present.
        if payload.get("schema_version") is not None:
            raise IpcContractError("REQUEST_SCHEMA_INVALID", str(payload.get("schema_version")))
    if payload.get("contract_id") not in {CONTRACT_ID, None}:
        if payload.get("contract_id") is not None:
            raise IpcContractError("CONTRACT_ID_MISMATCH", str(payload.get("contract_id")))
    op = payload.get("op")
    if not isinstance(op, str) or op not in ALLOWED_OPS:
        raise IpcContractError("OP_UNKNOWN", str(op))
    episode_id = payload.get("episode_id")
    if not isinstance(episode_id, str) or not episode_id.strip():
        raise IpcContractError("EPISODE_ID_INVALID", "required")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise IpcContractError("REQUEST_ID_INVALID", str(request_id)[:80])
    timeout_ms = payload.get("timeout_ms", 5_000)
    if type(timeout_ms) is not int or isinstance(timeout_ms, bool):
        raise IpcContractError("TIMEOUT_INVALID", str(timeout_ms))
    if timeout_ms < MIN_TIMEOUT_MS or timeout_ms > MAX_TIMEOUT_MS:
        raise IpcContractError("TIMEOUT_OUT_OF_RANGE", str(timeout_ms))
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        raise IpcContractError("ARGS_INVALID", "object required")
    # Op-specific light validation.
    if op == "list_dir":
        if "path_relative" not in args:
            raise IpcContractError("ARGS_INVALID", "path_relative required")
        normalize_lab_relative_path(str(args["path_relative"]))
    elif op == "read_file":
        if "path_relative" not in args:
            raise IpcContractError("ARGS_INVALID", "path_relative required")
        normalize_lab_relative_path(str(args["path_relative"]))
        max_bytes = args.get("max_bytes", 65536)
        if type(max_bytes) is not int or isinstance(max_bytes, bool):
            raise IpcContractError("ARGS_INVALID", "max_bytes must be int")
        if max_bytes < 1 or max_bytes > MAX_STDOUT_BYTES:
            raise IpcContractError("ARGS_INVALID", "max_bytes out of range")
        args = {**args, "max_bytes": max_bytes}
    elif op == "write_file":
        if "path_relative" not in args or "content_utf8" not in args:
            raise IpcContractError("ARGS_INVALID", "path_relative+content_utf8 required")
        normalize_lab_relative_path(str(args["path_relative"]))
        if not isinstance(args.get("content_utf8"), str):
            raise IpcContractError("ARGS_INVALID", "content_utf8 must be string")
    elif op == "shell_exec":
        argv = args.get("argv")
        cwd_relative = args.get("cwd_relative")
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
            raise IpcContractError("ARGS_INVALID", "argv required")
        if not isinstance(cwd_relative, str):
            raise IpcContractError("ARGS_INVALID", "cwd_relative required")
        normalize_lab_relative_path(cwd_relative)
    return {
        "schema_version": REQUEST_SCHEMA,
        "contract_id": CONTRACT_ID,
        "request_id": request_id,
        "episode_id": episode_id.strip(),
        "op": op,
        "args": dict(args),
        "timeout_ms": int(timeout_ms),
        **authority_clamp_flags(),
    }


def make_response(
    *,
    request: Mapping[str, Any],
    status: str,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    reason_code: str | None = None,
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise IpcContractError("REQUEST_JSON_INVALID", "request mapping required")
    request_id = str(request.get("request_id") or "invalid")[:128]
    episode_id = str(request.get("episode_id") or "invalid")[:256]
    op = str(request.get("op") or "ping")[:64]
    if not isinstance(stdout, str):
        stdout = str(stdout)
    if not isinstance(stderr, str):
        stderr = str(stderr)
    # Bound model-visible streams.
    stdout_b = stdout.encode("utf-8", errors="replace")
    stderr_b = stderr.encode("utf-8", errors="replace")
    if len(stdout_b) > MAX_STDOUT_BYTES:
        stdout = stdout_b[:MAX_STDOUT_BYTES].decode("utf-8", errors="replace")
    if len(stderr_b) > MAX_STDOUT_BYTES:
        stderr = stderr_b[:MAX_STDOUT_BYTES].decode("utf-8", errors="replace")
    core = {
        "status": status,
        "reason_code": reason_code,
        "stderr": stderr,
    }
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "contract_id": CONTRACT_ID,
        "request_id": request_id,
        "episode_id": episode_id,
        "op": op,
        "status": status,
        "exit_code": int(exit_code),
        "stdout": stdout,
        "stderr": stderr,
        "reason_code": reason_code,
        "event_hash": sha256_bytes(canonical_bytes(core)),
        **authority_clamp_flags(),
    }
    raw = canonical_bytes(response)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise IpcContractError("RESPONSE_TOO_LARGE", str(len(raw)))
    return response
