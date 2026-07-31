"""Episode network/tool boundary constants for ResearchEpisode profiles.

Profiles (Owner-sealed; researcher cannot change authority):
- INSTRUMENT_CANARY: one-turn, empty tools, no web
- CLOSED_LAB: long/multi-turn lab MCP, web denied
- OPEN_RESEARCH: default genuine path — transport-side web_search/web_fetch
  plus Grok built-in MCP meta-tools search_tool/use_tool

Shared by host create specs, entrypoint self-describe, and image labels.
Does not open network sockets or host tools. Candidate only.
"""

from __future__ import annotations

from typing import Final

# Owner-sealed research profiles (argv/attempt/export).
PROFILE_INSTRUMENT_CANARY: Final = "INSTRUMENT_CANARY"
PROFILE_CLOSED_LAB: Final = "CLOSED_LAB"
PROFILE_OPEN_RESEARCH: Final = "OPEN_RESEARCH"
DEFAULT_RESEARCH_PROFILE: Final = PROFILE_OPEN_RESEARCH

# Legacy episode label (image/entrypoint); maps to OPEN_RESEARCH tool surface.
PROFILE: Final = "GENUINE_SCIENTIST_EPISODE"
CANARY_PROFILE: Final = PROFILE_INSTRUMENT_CANARY

NETWORK_POLICY_DEFAULT: Final = "DENY_ALL_FAIL_CLOSED"
MCP_SERVER_NAME: Final = "episode_lab"

# Grok 0.2.117 built-in MCP meta-tools (discover/call MCP server tools).
MCP_META_TOOLS: Final = ("search_tool", "use_tool")
# Transport-side built-in web tools (OPEN_RESEARCH only).
WEB_BUILTIN_TOOLS: Final = ("web_search", "web_fetch")
# First-class lab ops exposed by the episode_lab MCP server (not meta-tools).
LAB_MCP_OPS: Final = ("ping", "list_dir", "read_file", "write_file", "shell_exec")
PRODUCTIVE_LAB_OPS: Final = frozenset({"write_file", "shell_exec"})

# Default genuine allowlist: meta + web (OPEN_RESEARCH).
OPEN_RESEARCH_TOOLS_ALLOWLIST: Final = MCP_META_TOOLS + WEB_BUILTIN_TOOLS
# CLOSED_LAB allowlist: meta only.
CLOSED_LAB_TOOLS_ALLOWLIST: Final = MCP_META_TOOLS
# Backward-compatible name used by older callers (OPEN_RESEARCH surface).
MCP_TOOLS_ALLOWLIST: Final = OPEN_RESEARCH_TOOLS_ALLOWLIST

GENERIC_FILE_SHELL_TOOLS: Final = False
DUAL_CONTAINER_REQUIRED: Final = True

# Canonical container paths (must physically align with mounts/env).
CANONICAL_GROK_HOME: Final = "/grok-home"
CANONICAL_LAB_CWD: Final = "/episode-lab"
CANONICAL_MCP_EVENTS: Final = "/output/mcp_events.jsonl"
CANONICAL_AGENT_PROFILE: Final = f"{CANONICAL_GROK_HOME}/agents/genuine_scientist_mcp.md"
CANONICAL_CONFIG_TOML: Final = f"{CANONICAL_GROK_HOME}/config.toml"
# Grok 0.2.117 stores auth.json + sessions directly under GROK_HOME (flat).
CANONICAL_AUTH_MOUNT: Final = f"{CANONICAL_GROK_HOME}/auth.json"
CANONICAL_SESSIONS_MOUNT: Final = f"{CANONICAL_GROK_HOME}/sessions"
# Legacy nested path retained only for negative/compat checks (not live mounts).
LEGACY_NESTED_GROK_AUTH_MOUNT: Final = f"{CANONICAL_GROK_HOME}/.grok"
CANONICAL_IPC_SOCKET: Final = "/ipc/tool.sock"
# Lab-authored sealed candidate body (tool path only; not host-forged evidence).
CANDIDATE_MANIFEST_RELATIVE: Final = "candidate/candidate_manifest.v1.json"
CANDIDATE_MANIFEST_SCHEMA: Final = "xinao.research_episode_candidate_manifest.v1"
CANDIDATE_MANIFEST_MARKER: Final = "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1"

# Writable surfaces inside the tool/lab namespace only.
ALLOWED_WRITABLE_SURFACES: Final = (
    "/episode-lab",
    "/tmp",
    "/ipc",
)

# Must never appear as mounts on the tool executor.
FORBIDDEN_TOOL_SURFACES: Final = (
    "docker.sock",
    "auth.json",
    "/ledger",
    "/outcomes",
    "/shadow",
    "/freeze",
    "/settlement",
    "/grok-home",
)

# Host generic file/shell/task/memory builtins stripped on all research profiles.
# OPEN_RESEARCH does NOT strip web_search/web_fetch; CLOSED_LAB does.
# Include both legacy and live 0.2.117 tool ids (run_terminal_command, spawn_subagent).
HOST_CONTROL_BUILTINS: Final = (
    "run_terminal_cmd",
    "run_terminal_command",
    "read_file",
    "search_replace",
    "grep",
    "list_dir",
    "todo_write",
    "task",
    "kill_task",
    "get_task_output",
    "memory_search",
    "memory_get",
    "lsp",
    "Agent",
    "spawn_subagent",
)


def tools_allowlist_for_profile(profile: str) -> tuple[str, ...]:
    name = str(profile or DEFAULT_RESEARCH_PROFILE).strip().upper()
    if name == PROFILE_INSTRUMENT_CANARY:
        return ()
    if name == PROFILE_CLOSED_LAB:
        return CLOSED_LAB_TOOLS_ALLOWLIST
    if name in {PROFILE_OPEN_RESEARCH, "GENUINE_SCIENTIST_EPISODE", "GENUINE"}:
        return OPEN_RESEARCH_TOOLS_ALLOWLIST
    raise ValueError(f"unknown research profile: {profile!r}")


def stripped_builtins_for_profile(profile: str) -> tuple[str, ...]:
    name = str(profile or DEFAULT_RESEARCH_PROFILE).strip().upper()
    if name == PROFILE_CLOSED_LAB:
        return HOST_CONTROL_BUILTINS + WEB_BUILTIN_TOOLS
    if name in {PROFILE_OPEN_RESEARCH, "GENUINE_SCIENTIST_EPISODE", "GENUINE"}:
        return HOST_CONTROL_BUILTINS
    if name == PROFILE_INSTRUMENT_CANARY:
        return HOST_CONTROL_BUILTINS + WEB_BUILTIN_TOOLS
    raise ValueError(f"unknown research profile: {profile!r}")


def web_enabled_for_profile(profile: str) -> bool:
    name = str(profile or DEFAULT_RESEARCH_PROFILE).strip().upper()
    return name in {PROFILE_OPEN_RESEARCH, "GENUINE_SCIENTIST_EPISODE", "GENUINE"}


def normalize_research_profile(profile: str | None) -> str:
    if not profile:
        return DEFAULT_RESEARCH_PROFILE
    name = str(profile).strip().upper()
    if name in {"GENUINE_SCIENTIST_EPISODE", "GENUINE", "GENUINE_SCIENTIST"}:
        return PROFILE_OPEN_RESEARCH
    if name in {
        PROFILE_OPEN_RESEARCH,
        PROFILE_CLOSED_LAB,
        PROFILE_INSTRUMENT_CANARY,
    }:
        return name
    raise ValueError(f"unknown research profile: {profile!r}")


def boundary_receipt() -> dict[str, object]:
    return {
        "schema_version": "xinao.episode_boundary.v1",
        "profile": PROFILE,
        "default_research_profile": DEFAULT_RESEARCH_PROFILE,
        "research_profiles": [
            PROFILE_INSTRUMENT_CANARY,
            PROFILE_CLOSED_LAB,
            PROFILE_OPEN_RESEARCH,
        ],
        "default_image_entrypoint_profile": CANARY_PROFILE,
        "network_policy": NETWORK_POLICY_DEFAULT,
        "mcp_server": MCP_SERVER_NAME,
        "mcp_lab_ops": list(LAB_MCP_OPS),
        "mcp_meta_tools": list(MCP_META_TOOLS),
        "tools_allowlist": list(OPEN_RESEARCH_TOOLS_ALLOWLIST),
        "generic_file_shell_tools": GENERIC_FILE_SHELL_TOOLS,
        "dual_container_required": DUAL_CONTAINER_REQUIRED,
        "canonical_paths": {
            "GROK_HOME": CANONICAL_GROK_HOME,
            "cwd": CANONICAL_LAB_CWD,
            "mcp_events": CANONICAL_MCP_EVENTS,
            "agent_profile": CANONICAL_AGENT_PROFILE,
            "config_toml": CANONICAL_CONFIG_TOML,
            "auth_mount": CANONICAL_AUTH_MOUNT,
            "ipc_socket": CANONICAL_IPC_SOCKET,
        },
        "allowed_writable_surfaces": list(ALLOWED_WRITABLE_SURFACES),
        "forbidden_tool_surfaces": list(FORBIDDEN_TOOL_SURFACES),
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
