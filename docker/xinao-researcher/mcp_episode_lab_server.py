#!/usr/bin/env python3
"""Transport-side attempt-local MCP stdio server for dual-container episodes.

Discovers only search_tool/use_tool (Grok headless MCP discovery surface).
Forwards lab tool ops over Unix IPC to the no-auth tool-executor sidecar.
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
    CONTRACT_ID,
    authority_clamp_flags,
    build_request,
    canonical_bytes,
    sha256_bytes,
)
from transport_broker import BrokerError, UnixSocketBroker

SERVER_NAME = "episode_lab"
ALLOWED_MCP_TOOLS = ("search_tool", "use_tool")

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


def scrub_inherited_transport_env() -> list[str]:
    """Remove transport credentials and host control env from process environment.

    Returns the list of removed key names. Safe to call multiple times.
    """
    removed: list[str] = []
    for key in list(os.environ.keys()):
        upper = key.upper()
        if key in SCRUB_ENV_EXACT or upper in SCRUB_ENV_EXACT:
            os.environ.pop(key, None)
            removed.append(key)
            continue
        if any(upper.startswith(prefix) for prefix in SCRUB_ENV_PREFIXES):
            # Keep non-secret routing flags if explicitly allowlisted later.
            if upper in {
                "GROK_HOME",  # may be attempt-local; still scrub auth-bearing secrets only
            }:
                continue
            # Scrub API key style and session tokens under provider prefixes.
            if any(
                token in upper for token in ("API", "TOKEN", "SECRET", "PASSWORD", "AUTH", "KEY")
            ):
                os.environ.pop(key, None)
                removed.append(key)
    # Always scrub the exact high-risk set even if empty.
    for key in ("GROK_API_KEY", "XAI_API_KEY", "DOCKER_HOST", "SSH_AUTH_SOCK"):
        if key in os.environ:
            os.environ.pop(key, None)
            if key not in removed:
                removed.append(key)
    return removed


def _append_evidence(path: Path | None, event: Mapping[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def _list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_tool",
            "description": "Discover attempt-local episode_lab tools (allowlist only).",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "use_tool",
            "description": "Invoke a lab op via dual-container IPC (no host auth).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "op": {"type": "string"},
                    "args": {"type": "object"},
                    "timeout_ms": {"type": "integer"},
                },
                "required": ["op"],
                "additionalProperties": False,
            },
        },
    ]


def handle_search_tool(arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
    query = ""
    if isinstance(arguments, Mapping):
        query = str(arguments.get("query") or "").strip().lower()
    tools = _list_tools()
    if query:
        tools = [t for t in tools if query in t["name"] or query in t["description"].lower()]
    return {
        "tools": tools,
        "allowlist": list(ALLOWED_MCP_TOOLS),
        "server": SERVER_NAME,
        **authority_clamp_flags(),
    }


def handle_use_tool(
    *,
    episode_id: str,
    socket_path: str,
    arguments: Mapping[str, Any] | None,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    args = dict(arguments or {})
    op = str(args.get("op") or "ping")
    op_args = args.get("args") if isinstance(args.get("args"), dict) else {}
    if (
        "timeout_ms" in args
        and type(args["timeout_ms"]) is int
        and not isinstance(args["timeout_ms"], bool)
    ):
        timeout_ms = int(args["timeout_ms"])
    request = build_request(
        op=op,
        episode_id=episode_id,
        args=op_args if isinstance(op_args, dict) else {},
        timeout_ms=timeout_ms,
    )
    broker = UnixSocketBroker(socket_path)
    try:
        response = broker.call(request, timeout_s=max(1.0, timeout_ms / 1000.0))
    except BrokerError as exc:
        return {
            "status": "error",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
            "contract_id": CONTRACT_ID,
            **authority_clamp_flags(),
        }
    return response


def _mcp_result_text(payload: Mapping[str, Any]) -> dict[str, Any]:
    text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": payload.get("status") == "error",
    }


def serve_stdio(
    *,
    socket_path: str,
    episode_id: str,
    evidence_path: Path | None,
    timeout_ms: int = 5000,
) -> int:
    scrubbed = scrub_inherited_transport_env()
    _append_evidence(
        evidence_path,
        {
            "event": "mcp_server_start",
            "episode_id": episode_id,
            "server": SERVER_NAME,
            "scrubbed_env": scrubbed,
            "socket": socket_path,
            **authority_clamp_flags(),
        },
    )
    # Minimal JSON-RPC style loop compatible with MCP stdio framing (line-delimited JSON).
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
                "serverInfo": {"name": SERVER_NAME, "version": "1"},
            }
            if method == "notifications/initialized":
                continue
        elif method == "tools/list":
            result = {"tools": _list_tools()}
        elif method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if name not in ALLOWED_MCP_TOOLS:
                result = _mcp_result_text(
                    {
                        "status": "denied",
                        "reason_code": "TOOL_NOT_ALLOWLISTED",
                        "tool": name,
                        **authority_clamp_flags(),
                    }
                )
            elif name == "search_tool":
                payload = handle_search_tool(arguments)
                result = _mcp_result_text(payload)
                _append_evidence(
                    evidence_path,
                    {
                        "event": "mcp_tools_call",
                        "tool": name,
                        "episode_id": episode_id,
                        "payload_sha256": sha256_bytes(canonical_bytes(payload)),
                    },
                )
            else:
                payload = handle_use_tool(
                    episode_id=episode_id,
                    socket_path=socket_path,
                    arguments=arguments,
                    timeout_ms=timeout_ms,
                )
                result = _mcp_result_text(payload)
                _append_evidence(
                    evidence_path,
                    {
                        "event": "mcp_tools_call",
                        "tool": name,
                        "episode_id": episode_id,
                        "op": arguments.get("op"),
                        "status": payload.get("status"),
                        "reason_code": payload.get("reason_code"),
                    },
                )
        elif method == "ping":
            result = {}
        else:
            # Unknown methods: empty result rather than crash the episode.
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
        default=os.environ.get("XINAO_MCP_EVIDENCE_PATH", ""),
    )
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument(
        "--sidecar-identity-expected",
        default=None,
        help="Optional expected sidecar identity token (reserved for host checks).",
    )
    args = parser.parse_args(argv)
    evidence = Path(args.evidence_path) if args.evidence_path else None
    return serve_stdio(
        socket_path=str(args.socket),
        episode_id=str(args.episode_id),
        evidence_path=evidence,
        timeout_ms=int(args.timeout_ms),
    )


if __name__ == "__main__":
    raise SystemExit(main())
