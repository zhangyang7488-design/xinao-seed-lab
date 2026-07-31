"""Episode network/tool boundary constants for GENUINE_SCIENTIST_EPISODE.

Shared by host create specs, entrypoint self-describe, and image labels.
Does not open network sockets or host tools. Candidate only.
"""

from __future__ import annotations

from typing import Final

PROFILE: Final = "GENUINE_SCIENTIST_EPISODE"
CANARY_PROFILE: Final = "INSTRUMENT_CANARY"
NETWORK_POLICY_DEFAULT: Final = "DENY_ALL_FAIL_CLOSED"
MCP_SERVER_NAME: Final = "episode_lab"
MCP_TOOLS_ALLOWLIST: Final = ("search_tool", "use_tool")
GENERIC_FILE_SHELL_TOOLS: Final = False
DUAL_CONTAINER_REQUIRED: Final = True

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


def boundary_receipt() -> dict[str, object]:
    return {
        "schema_version": "xinao.episode_boundary.v1",
        "profile": PROFILE,
        "default_image_entrypoint_profile": CANARY_PROFILE,
        "network_policy": NETWORK_POLICY_DEFAULT,
        "mcp_server": MCP_SERVER_NAME,
        "tools_allowlist": list(MCP_TOOLS_ALLOWLIST),
        "generic_file_shell_tools": GENERIC_FILE_SHELL_TOOLS,
        "dual_container_required": DUAL_CONTAINER_REQUIRED,
        "allowed_writable_surfaces": list(ALLOWED_WRITABLE_SURFACES),
        "forbidden_tool_surfaces": list(FORBIDDEN_TOOL_SURFACES),
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
