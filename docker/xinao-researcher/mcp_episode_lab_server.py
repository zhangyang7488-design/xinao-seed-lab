#!/usr/bin/env python3
"""Transport-side attempt-local MCP stdio server for dual-container episodes.

Exposes first-class lab ops (ping, list_dir, read_file, write_file, shell_exec).
Grok 0.2.117 built-in meta-tools search_tool / use_tool discover and invoke them
(server-qualified names like episode_lab__write_file). Does NOT re-expose
search_tool/use_tool as MCP tools.

Forwards ops over Unix IPC to the no-auth tool-executor sidecar.
Scrubs inherited transport credentials at startup. Candidate only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from ipc_contract import (
    ALLOWED_OPS,
    CONTRACT_ID,
    MAX_TIMEOUT_MS,
    authority_clamp_flags,
    build_request,
    canonical_bytes,
    sha256_bytes,
)
from transport_broker import BrokerError, UnixSocketBroker

SERVER_NAME = "episode_lab"
# First-class lab ops only. Meta-tools live in Grok, not this server.
LAB_OPS = ("ping", "list_dir", "read_file", "write_file", "shell_exec")
PRODUCTIVE_OPS = frozenset({"write_file", "shell_exec"})
CANONICAL_EVIDENCE_PATH = "/output/mcp_events.jsonl"
EVENT_SCHEMA = "xinao.dual_container_mcp_event.v1"

# Credential / host-control keys that must never remain in the MCP child env.
SCRUB_ENV_EXACT = frozenset(
    {
        "GROK_API_KEY",
        "XAI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DOCKER_HOST",
        "SSH_AUTH_SOCK",
        "KUBECONFIG",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AZURE_CLIENT_SECRET",
    }
)
SCRUB_ENV_PREFIXES = (
    "GROK_",
    "XAI_",
    "OPENAI_",
    "ANTHROPIC_",
)

LAB_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "ping": {
        "description": "Health-check the dual-container lab IPC sidecar.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    "list_dir": {
        "description": "List a directory under the episode lab root only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Lab-relative directory path.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "read_file": {
        "description": "Read a file under the episode lab root only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Lab-relative file path.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "write_file": {
        "description": "Write a file under the episode lab root only (productive lab op).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Lab-relative file path.",
                },
                "content": {
                    "type": "string",
                    "description": "UTF-8 text content to write.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    "shell_exec": {
        "description": (
            "Run a bounded argv under the no-network tool sidecar (productive lab op). "
            "May use a preseeded lab-local venv/wheelhouse path; no live online install."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argv list; no free-form shell interpreters.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional lab-relative working directory.",
                },
            },
            "required": ["argv"],
            "additionalProperties": False,
        },
    },
}


def scrub_inherited_transport_env() -> list[str]:
    """Remove transport credentials and host control env from process environment."""
    removed: list[str] = []
    for key in list(os.environ.keys()):
        upper = key.upper()
        if key in SCRUB_ENV_EXACT or upper in SCRUB_ENV_EXACT:
            os.environ.pop(key, None)
            removed.append(key)
            continue
        if any(upper.startswith(prefix) for prefix in SCRUB_ENV_PREFIXES):
            if upper in {"GROK_HOME"}:
                continue
            if any(
                token in upper for token in ("API", "TOKEN", "SECRET", "PASSWORD", "AUTH", "KEY")
            ):
                os.environ.pop(key, None)
                removed.append(key)
    for key in ("GROK_API_KEY", "XAI_API_KEY", "DOCKER_HOST", "SSH_AUTH_SOCK"):
        if key in os.environ:
            os.environ.pop(key, None)
            if key not in removed:
                removed.append(key)
    return removed


def _normalize_op_name(name: str) -> str:
    """Accept bare op or server-qualified episode_lab__op / episode_lab.op."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    if raw.startswith(f"{SERVER_NAME}__"):
        return raw[len(SERVER_NAME) + 2 :]
    if raw.startswith(f"{SERVER_NAME}."):
        return raw[len(SERVER_NAME) + 1 :]
    # Grok may pass MCPTool(server, tool) style with slash.
    if "/" in raw:
        return raw.rsplit("/", 1)[-1]
    return raw


def _list_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for op in LAB_OPS:
        schema = LAB_TOOL_SCHEMAS[op]
        tools.append(
            {
                "name": op,
                "description": schema["description"],
                "inputSchema": schema["inputSchema"],
            }
        )
    return tools


def _append_evidence(path: Path | None, event: Mapping[str, Any]) -> str | None:
    """Append a canonically hashable event line; return event_hash."""
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in dict(event).items() if k != "event_hash"}
    body.setdefault("schema_version", EVENT_SCHEMA)
    body.setdefault("server", SERVER_NAME)
    event_hash = sha256_bytes(canonical_bytes(body))
    line_obj = {**body, "event_hash": event_hash}
    line = json.dumps(line_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    return event_hash


def remap_mcp_args_to_ipc(op: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map published MCP schema args onto IPC contract field names.

    MCP advertises path/content/cwd; IPC requires path_relative/content_utf8/cwd_relative.
    Accept either shape so schema-native model calls succeed without host-forged aliases.
    Never invent host absolute paths; never default cwd_relative to \".\".
    """
    raw = dict(arguments or {})
    args = dict(raw)
    # Prefer explicit IPC names when both are present.
    if "path_relative" not in args and "path" in args:
        args["path_relative"] = args.pop("path")
    elif "path" in args and "path_relative" in args:
        args.pop("path", None)
    if "content_utf8" not in args and "content" in args:
        args["content_utf8"] = args.pop("content")
    elif "content" in args and "content_utf8" in args:
        args.pop("content", None)
    if op == "shell_exec":
        if "cwd_relative" not in args:
            if "cwd" in args and str(args.get("cwd") or "").strip() not in {"", "."}:
                args["cwd_relative"] = args.pop("cwd")
            else:
                # Lab root token for shell ops when model omits cwd (never ".").
                args["cwd_relative"] = "work"
                args.pop("cwd", None)
        else:
            args.pop("cwd", None)
        if str(args.get("cwd_relative") or "").strip() in {"", "."}:
            args["cwd_relative"] = "work"
    else:
        args.pop("cwd", None)
    return args


def handle_lab_op(
    *,
    op: str,
    episode_id: str,
    socket_path: str,
    arguments: Mapping[str, Any] | None,
    timeout_ms: int,
) -> dict[str, Any]:
    if op not in ALLOWED_OPS:
        return {
            "status": "denied",
            "reason_code": "OP_UNKNOWN",
            "op": op,
            "contract_id": CONTRACT_ID,
            **authority_clamp_flags(),
        }
    args = remap_mcp_args_to_ipc(op, arguments)
    # Do not allow callers to smuggle authority or host paths via args keys.
    for forbidden in (
        "completion_claim_allowed",
        "owner_adopted",
        "science_restored",
        "parent_complete",
        "shadow",
        "ledger",
        "freeze",
        "settlement",
    ):
        args.pop(forbidden, None)
    call_timeout = timeout_ms
    if (
        "timeout_ms" in args
        and type(args["timeout_ms"]) is int
        and not isinstance(args["timeout_ms"], bool)
    ):
        call_timeout = int(args.pop("timeout_ms"))
    if call_timeout < 50 or call_timeout > MAX_TIMEOUT_MS:
        return {
            "status": "error",
            "reason_code": "TIMEOUT_OUT_OF_RANGE",
            "detail": str(call_timeout),
            "contract_id": CONTRACT_ID,
            **authority_clamp_flags(),
        }
    try:
        request = build_request(
            op=op,
            episode_id=episode_id,
            args=args,
            timeout_ms=call_timeout,
        )
    except Exception as exc:  # IpcContractError
        return {
            "status": "error",
            "reason_code": getattr(exc, "reason_code", "REQUEST_INVALID"),
            "detail": str(exc)[:500],
            "contract_id": CONTRACT_ID,
            **authority_clamp_flags(),
        }
    broker = UnixSocketBroker(socket_path)
    try:
        response = broker.call(request, timeout_s=max(1.0, call_timeout / 1000.0))
    except BrokerError as exc:
        return {
            "status": "error",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
            "contract_id": CONTRACT_ID,
            "op": op,
            **authority_clamp_flags(),
        }
    if isinstance(response, dict):
        response = dict(response)
        response.setdefault("op", op)
        response.setdefault("productive", op in PRODUCTIVE_OPS)
    return response


def _mcp_result_text(payload: Mapping[str, Any]) -> dict[str, Any]:
    text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": payload.get("status") in {"error", "denied"},
    }


def serve_stdio(
    *,
    socket_path: str,
    episode_id: str,
    evidence_path: Path | None,
    timeout_ms: int = 60_000,
) -> int:
    scrubbed = scrub_inherited_transport_env()
    _append_evidence(
        evidence_path,
        {
            "event": "mcp_server_start",
            "episode_id": episode_id,
            "server": SERVER_NAME,
            "lab_ops": list(LAB_OPS),
            "scrubbed_env": scrubbed,
            "socket": socket_path,
            "productive": False,
            **authority_clamp_flags(),
        },
    )
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        req_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        result: dict[str, Any]
        if method in {"initialize", "notifications/initialized"}:
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "2"},
            }
            if method == "notifications/initialized":
                continue
        elif method == "tools/list":
            result = {"tools": _list_tools()}
            _append_evidence(
                evidence_path,
                {
                    "event": "mcp_tools_list",
                    "episode_id": episode_id,
                    "tool_names": list(LAB_OPS),
                    "productive": False,
                    **authority_clamp_flags(),
                },
            )
        elif method == "tools/call":
            raw_name = str(params.get("name") or "")
            op = _normalize_op_name(raw_name)
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            # Deny meta-tools and unknown ops exposed as MCP tools.
            if op in {"search_tool", "use_tool"}:
                payload = {
                    "status": "denied",
                    "reason_code": "META_TOOL_NOT_MCP_SURFACE",
                    "tool": raw_name,
                    "detail": (
                        "search_tool/use_tool are Grok built-in meta-tools; "
                        "call lab ops via use_tool against episode_lab tools."
                    ),
                    **authority_clamp_flags(),
                }
                result = _mcp_result_text(payload)
                _append_evidence(
                    evidence_path,
                    {
                        "event": "mcp_tools_call",
                        "tool": raw_name,
                        "op": op,
                        "episode_id": episode_id,
                        "status": "denied",
                        "reason_code": "META_TOOL_NOT_MCP_SURFACE",
                        "productive": False,
                        **authority_clamp_flags(),
                    },
                )
            elif op not in LAB_OPS:
                payload = {
                    "status": "denied",
                    "reason_code": "TOOL_NOT_ALLOWLISTED",
                    "tool": raw_name,
                    "op": op,
                    **authority_clamp_flags(),
                }
                result = _mcp_result_text(payload)
                _append_evidence(
                    evidence_path,
                    {
                        "event": "mcp_tools_call",
                        "tool": raw_name,
                        "op": op,
                        "episode_id": episode_id,
                        "status": "denied",
                        "reason_code": "TOOL_NOT_ALLOWLISTED",
                        "productive": False,
                        **authority_clamp_flags(),
                    },
                )
            else:
                remapped = remap_mcp_args_to_ipc(op, arguments)
                payload = handle_lab_op(
                    op=op,
                    episode_id=episode_id,
                    socket_path=socket_path,
                    arguments=arguments,
                    timeout_ms=timeout_ms,
                )
                result = _mcp_result_text(payload)
                sidecar_event = payload.get("event_hash") if isinstance(payload, dict) else None
                path_rel = remapped.get("path_relative")
                if path_rel is None and op == "shell_exec":
                    path_rel = remapped.get("cwd_relative")
                _append_evidence(
                    evidence_path,
                    {
                        "event": "mcp_tools_call",
                        "tool": raw_name,
                        "op": op,
                        "episode_id": episode_id,
                        "status": payload.get("status") if isinstance(payload, dict) else None,
                        "reason_code": (
                            payload.get("reason_code") if isinstance(payload, dict) else None
                        ),
                        "sidecar_event_hash": sidecar_event,
                        "path_relative": path_rel,
                        "productive": op in PRODUCTIVE_OPS,
                        **authority_clamp_flags(),
                    },
                )
        elif method == "ping":
            result = {}
        else:
            result = {"status": "ignored", "method": method}
        if req_id is None:
            continue
        response = {"jsonrpc": "2.0", "id": req_id, "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XINAO episode_lab MCP stdio server")
    parser.add_argument(
        "--socket", default=os.environ.get("XINAO_TOOL_IPC_SOCKET", "/ipc/tool.sock")
    )
    parser.add_argument("--episode-id", default=os.environ.get("XINAO_EPISODE_ID", "episode-local"))
    parser.add_argument(
        "--evidence-path",
        default=os.environ.get("XINAO_MCP_EVIDENCE_PATH")
        or os.environ.get("XINAO_MCP_EVENT_LOG")
        or CANONICAL_EVIDENCE_PATH,
    )
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument(
        "--sidecar-identity-expected",
        default=None,
        help="Optional expected sidecar identity token (reserved for host checks).",
    )
    args = parser.parse_args(argv)
    evidence = Path(args.evidence_path) if args.evidence_path else None
    # Fail closed on non-canonical evidence path when under container contract.
    if evidence is not None:
        evidence_s = str(evidence).replace("\\", "/")
        if evidence_s not in {CANONICAL_EVIDENCE_PATH, str(Path(CANONICAL_EVIDENCE_PATH))}:
            # Allow host unit-test absolute paths outside container; only reject
            # known fragmented container aliases.
            if evidence_s in {
                "/output/mcp-evidence.jsonl",
                "/attempt/mcp-evidence.jsonl",
                "output/mcp_events.jsonl",
            }:
                raise SystemExit(f"NON_CANONICAL_EVIDENCE_PATH:{evidence_s}")
    return serve_stdio(
        socket_path=str(args.socket),
        episode_id=str(args.episode_id),
        evidence_path=evidence,
        timeout_ms=int(args.timeout_ms),
    )


if __name__ == "__main__":
    raise SystemExit(main())
