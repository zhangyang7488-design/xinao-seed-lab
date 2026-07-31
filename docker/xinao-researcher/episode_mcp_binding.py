"""Attempt-local Grok Build MCP binding for the genuine-scientist episode profile.

Generates an isolated GROK_HOME (config.toml + agent profile) that:
- registers the transport-side episode_lab stdio MCP server;
- allowlists only search_tool/use_tool (MCP discovery/call surface);
- does not modify global host config and does not mount arbitrary host config.

Candidate only. Codex is the sole Owner/adopter.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipc_contract import (
    CONTRACT_ID,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_TIMEOUT_MS,
    authority_clamp_flags,
    canonical_bytes,
    sha256_bytes,
)

MCP_SERVER_NAME = "episode_lab"
# Grok headless --tools allowlist IDs (sealed README Built-in Tools / headless flags).
MCP_DISCOVERY_TOOLS = ("search_tool", "use_tool")
# Built-ins that must never appear on the genuine dual-container profile.
STRIPPED_BUILTIN_TOOLS = (
    "run_terminal_cmd",
    "read_file",
    "search_replace",
    "grep",
    "list_dir",
    "web_search",
    "web_fetch",
    "todo_write",
    "task",
    "kill_task",
    "get_task_output",
    "memory_search",
    "memory_get",
    "lsp",
    "Agent",
)

DEFAULT_MCP_SERVER_PATH = "/opt/xinao-researcher/mcp_episode_lab_server.py"
DEFAULT_SOCKET_PATH = "/ipc/tool.sock"
DEFAULT_PYTHON = "python3"

BINDING_SCHEMA_VERSION = "xinao.episode_mcp_binding.v1"
PROFILE_NAME = "genuine_scientist_mcp"


def mcp_tools_allowlist() -> str:
    return ",".join(MCP_DISCOVERY_TOOLS)


def stripped_builtins_csv() -> str:
    return ",".join(STRIPPED_BUILTIN_TOOLS)


def render_config_toml(
    *,
    server_command: str,
    server_args: Sequence[str],
    env: Mapping[str, str] | None = None,
    startup_timeout_sec: int = 15,
    tool_timeout_sec: int = 30,
    server_name: str = MCP_SERVER_NAME,
) -> str:
    # TOML with inline env table. Values are constrained to non-secret binding env.
    lines = [
        f"[mcp_servers.{server_name}]",
        f'command = "{_toml_escape(server_command)}"',
        "args = [" + ", ".join(f'"{_toml_escape(a)}"' for a in server_args) + "]",
        "enabled = true",
        f"startup_timeout_sec = {int(startup_timeout_sec)}",
        f"tool_timeout_sec = {int(tool_timeout_sec)}",
    ]
    if env:
        env_items = ", ".join(
            f'{_toml_escape(k)} = "{_toml_escape(v)}"' for k, v in sorted(env.items())
        )
        lines.append(f"env = {{ {env_items} }}")
    lines.append("")
    # Explicitly disable features that pull extra tools.
    lines.extend(
        [
            "[features]",
            "lsp_tools = false",
            "",
            "[subagents]",
            "enabled = false",
            "",
            "[memory]",
            "enabled = false",
            "",
        ]
    )
    return "\n".join(lines)


def render_agent_profile_md() -> str:
    """Agent profile frontmatter: only MCP discovery tools; strip builtins."""
    tools_yaml = "\n".join(f"  - {name}" for name in MCP_DISCOVERY_TOOLS)
    denied_yaml = "\n".join(f"  - {name}" for name in STRIPPED_BUILTIN_TOOLS)
    return (
        "---\n"
        f"name: {PROFILE_NAME}\n"
        "description: Genuine-scientist episode profile using dual-container MCP lab tools only.\n"
        "tools:\n"
        f"{tools_yaml}\n"
        "disallowedTools:\n"
        f"{denied_yaml}\n"
        "---\n"
        "\n"
        "You are a genuine-scientist episode agent. Use only MCP tools discovered via\n"
        "search_tool / use_tool against the episode_lab server. Do not claim host paths,\n"
        "credentials, Owner adoption, science restoration, or parent completion.\n"
    )


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def attempt_local_binding_paths(root: Path, *, grok_home: Path | None = None) -> dict[str, Path]:
    """Paths for attempt-local binding.

    When ``grok_home`` is provided (typical transport: /grok-home with auth mount
    under .grok/), config.toml is written there so Grok discovers MCP without
    relocating GROK_HOME away from auth. When omitted, a nested grok-home under
    root is used (unit tests / isolated smoke).
    """
    resolved_home = Path(grok_home) if grok_home is not None else (root / "grok-home")
    return {
        "root": root,
        "grok_home": resolved_home,
        "config_toml": resolved_home / "config.toml",
        "agent_profile": resolved_home / "agents" / f"{PROFILE_NAME}.md",
        "evidence": root / "mcp-evidence.jsonl",
    }


def build_server_argv(
    *,
    server_path: str,
    socket_path: str,
    episode_id: str,
    evidence_path: str,
    timeout_ms: int = 5000,
    python_bin: str = DEFAULT_PYTHON,
    sidecar_identity_expected: str | None = None,
) -> list[str]:
    argv = [
        python_bin,
        "-I",
        server_path,
        "--socket",
        socket_path,
        "--episode-id",
        episode_id,
        "--evidence-path",
        evidence_path,
        "--timeout-ms",
        str(int(timeout_ms)),
    ]
    if sidecar_identity_expected:
        argv.extend(["--sidecar-identity-expected", sidecar_identity_expected])
    return argv


def materialize_attempt_local_binding(
    *,
    root: Path,
    episode_id: str,
    socket_path: str = DEFAULT_SOCKET_PATH,
    server_path: str = DEFAULT_MCP_SERVER_PATH,
    python_bin: str = DEFAULT_PYTHON,
    pythonpath: str = "/opt/xinao-researcher",
    timeout_ms: int = 5000,
    sidecar_identity_expected: str | None = None,
    grok_home: Path | str | None = None,
) -> dict[str, Any]:
    """Write attempt-local GROK_HOME config + agent profile; return binding receipt.

    Does not modify host-global operator config. Container-local GROK_HOME
    (auth mount parent) may receive an attempt config.toml overlay.
    """
    preferred_home: Path | None
    if grok_home is not None:
        preferred_home = Path(grok_home)
    else:
        env_home = os.environ.get("GROK_HOME")
        preferred_home = Path(env_home) if env_home else None
        if preferred_home is not None:
            looks_like_transport_home = (
                preferred_home == Path("/grok-home")
                or preferred_home.name in {"grok-home", "attempt-grok-home"}
                or (preferred_home / ".grok").exists()
            )
            if not looks_like_transport_home:
                # Fall back to nested home under root for isolation.
                preferred_home = None
    paths = attempt_local_binding_paths(root, grok_home=preferred_home)
    paths["grok_home"].mkdir(parents=True, exist_ok=True)
    paths["agent_profile"].parent.mkdir(parents=True, exist_ok=True)
    paths["evidence"].parent.mkdir(parents=True, exist_ok=True)

    server_args = build_server_argv(
        server_path=server_path,
        socket_path=socket_path,
        episode_id=episode_id,
        evidence_path=str(paths["evidence"]),
        timeout_ms=timeout_ms,
        python_bin=python_bin,
        sidecar_identity_expected=sidecar_identity_expected,
    )
    # command is argv[0]; remaining are args for config.toml
    command = server_args[0]
    args = server_args[1:]
    env = {
        "PYTHONPATH": pythonpath,
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        # Intentionally no GROK_*, XAI_*, auth, or HOME override that points at transport auth.
        # MCP child still inherits parent process env (Grok merge); mcp_episode_lab_server
        # scrubs credential keys at startup. Tool execution remains on no-auth sidecar.
        "XINAO_TOOL_IPC_SOCKET": socket_path,
        "XINAO_EPISODE_ID": episode_id,
        "XINAO_MCP_EVIDENCE_PATH": str(paths["evidence"]),
    }
    config_text = render_config_toml(
        server_command=command,
        server_args=args,
        env=env,
        tool_timeout_sec=max(1, min(timeout_ms // 1000, MAX_TIMEOUT_MS // 1000)),
    )
    profile_text = render_agent_profile_md()
    paths["config_toml"].write_text(config_text, encoding="utf-8")
    paths["agent_profile"].write_text(profile_text, encoding="utf-8")

    receipt = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding_id": uuid.uuid4().hex,
        "episode_id": episode_id,
        "mcp_server_name": MCP_SERVER_NAME,
        "tools_allowlist": list(MCP_DISCOVERY_TOOLS),
        "tools_allowlist_csv": mcp_tools_allowlist(),
        "stripped_builtins": list(STRIPPED_BUILTIN_TOOLS),
        "socket_basename": Path(socket_path).name,
        "contract_id": CONTRACT_ID,
        "max_request_bytes": MAX_REQUEST_BYTES,
        "max_response_bytes": MAX_RESPONSE_BYTES,
        "timeout_ms": int(timeout_ms),
        "grok_home": str(paths["grok_home"]),
        "config_toml": str(paths["config_toml"]),
        "agent_profile": str(paths["agent_profile"]),
        "evidence_path": str(paths["evidence"]),
        "config_sha256": sha256_bytes(config_text.encode("utf-8")),
        "agent_profile_sha256": sha256_bytes(profile_text.encode("utf-8")),
        "server_argv": server_args,
        "global_config_modified": False,
        "host_config_mounted": False,
        **authority_clamp_flags(),
    }
    receipt_path = root / "mcp-binding-receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt))
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = sha256_bytes(canonical_bytes(receipt))
    return receipt


def dual_container_socket_available(socket_path: str | None = None) -> bool:
    path = Path(socket_path or os.environ.get("XINAO_TOOL_IPC_SOCKET") or DEFAULT_SOCKET_PATH)
    # Socket may not exist yet at planning time; presence of dual-container env is enough
    # for command assembly. Live call still requires the socket.
    if os.environ.get("XINAO_DUAL_CONTAINER") == "1":
        return True
    try:
        return path.exists()
    except OSError:
        return False


def binding_env_for_grok(receipt: Mapping[str, Any]) -> dict[str, str]:
    """Env for the grok process.

    Sets GROK_HOME only when the receipt home is not already the process GROK_HOME,
    so a transport auth mount under /grok-home is preserved when config was written there.
    """
    env = {
        "XINAO_MCP_BINDING": "1",
        "XINAO_MCP_SERVER": MCP_SERVER_NAME,
        "XINAO_MCP_TOOLS": mcp_tools_allowlist(),
    }
    current = os.environ.get("GROK_HOME")
    target = str(receipt["grok_home"])
    if current != target:
        env["GROK_HOME"] = target
    return env
