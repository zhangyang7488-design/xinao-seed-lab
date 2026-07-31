#!/usr/bin/env python3
"""Additive GENUINE_SCIENTIST_EPISODE transport entrypoint.

Selected only via host ``docker create --entrypoint`` for dual-container seats.
Default image ENTRYPOINT remains INSTRUMENT_CANARY ``entrypoint.py`` (unchanged).

This module does not open generic host file/shell tools. Model tools reach the
no-auth sidecar only through attempt-local native MCP (episode_lab).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROFILE = "GENUINE_SCIENTIST_EPISODE"
CANARY_PROFILE = "INSTRUMENT_CANARY"
ENTRYPOINT_SCHEMA = "xinao.genuine_scientist_episode_entrypoint.v1"


def _authority_clamp() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }


def self_describe() -> dict[str, object]:
    return {
        "schema_version": ENTRYPOINT_SCHEMA,
        "profile": PROFILE,
        "default_image_entrypoint_profile": CANARY_PROFILE,
        "mcp_server": "episode_lab",
        "tools_allowlist": ["search_tool", "use_tool"],
        "generic_file_shell_tools": False,
        "dual_container_required": True,
        "network_policy": os.environ.get("XINAO_EPISODE_NETWORK_POLICY", "DENY_ALL_FAIL_CLOSED"),
        "ipc_socket": os.environ.get("XINAO_TOOL_IPC_SOCKET", "/ipc/tool.sock"),
        **_authority_clamp(),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-describe" in args or os.environ.get("XINAO_EPISODE_SELF_DESCRIBE") == "1":
        sys.stdout.write(
            json.dumps(self_describe(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        return 0
    # Host dual-container orchestration attaches Grok with attempt-local MCP config.
    # When invoked bare (no host attach), emit a fail-closed receipt rather than
    # pretending canary research completed.
    out = Path(
        os.environ.get("XINAO_EPISODE_RECEIPT_PATH", "/output/episode_entrypoint_receipt.json")
    )
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        receipt = {
            "schema_version": ENTRYPOINT_SCHEMA,
            "status": "AWAITING_HOST_GROK_ATTACH",
            "profile": PROFILE,
            "note": (
                "episode_entrypoint is host-selected only; Owner attaches Grok with "
                "search_tool,use_tool MCP binding. Not INSTRUMENT_CANARY."
            ),
            "argv": args[:32],
            **_authority_clamp(),
        }
        out.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    # Non-zero so accidental default ENTRYPOINT swap cannot green canary semantics.
    print(
        json.dumps(
            {
                "status": "EPISODE_ENTRYPOINT_IDLE",
                "profile": PROFILE,
                "completion_claim_allowed": False,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
