#!/usr/bin/env python3
"""Additive GENUINE_SCIENTIST_EPISODE transport entrypoint.

Selected only via host ``docker create --entrypoint`` for dual-container seats.
Default image ENTRYPOINT remains INSTRUMENT_CANARY ``entrypoint.py`` (unchanged).

This module does not open generic host file/shell tools. Model tools reach the
no-auth sidecar only through attempt-local native MCP (episode_lab).

Idle-hold contract (``--hold``):
  - Write AWAITING_HOST_GROK_ATTACH receipt, then block until SIGTERM/SIGINT.
  - No research, no next-task scheduling, no freeze/settle, no provider calls.
  - No busy loop; docker stop (SIGTERM) must exit the process.
  - restart policy remains ``no`` (host-side); this process never restarts itself.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Callable

PROFILE = "GENUINE_SCIENTIST_EPISODE"
CANARY_PROFILE = "INSTRUMENT_CANARY"
ENTRYPOINT_SCHEMA = "xinao.genuine_scientist_episode_entrypoint.v1"

# Tests may inject a wait callable; production path uses signals only.
_HOLD_WAIT_HOOK: Callable[[], None] | None = None


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
        "research_profile_default": "OPEN_RESEARCH",
        "tools_allowlist": [
            "search_tool",
            "use_tool",
            "web_search",
            "web_fetch",
        ],
        "mcp_lab_ops": ["ping", "list_dir", "read_file", "write_file", "shell_exec"],
        "generic_file_shell_tools": False,
        "dual_container_required": True,
        "idle_hold_mode": True,
        "network_policy": os.environ.get("XINAO_EPISODE_NETWORK_POLICY", "DENY_ALL_FAIL_CLOSED"),
        "ipc_socket": os.environ.get("XINAO_TOOL_IPC_SOCKET", "/ipc/tool.sock"),
        **_authority_clamp(),
    }


def _receipt_path() -> Path:
    return Path(
        os.environ.get("XINAO_EPISODE_RECEIPT_PATH", "/output/episode_entrypoint_receipt.json")
    )


def _write_awaiting_receipt(args: list[str], *, hold: bool) -> None:
    out = _receipt_path()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        receipt = {
            "schema_version": ENTRYPOINT_SCHEMA,
            "status": "AWAITING_HOST_GROK_ATTACH",
            "profile": PROFILE,
            "hold": hold,
            "note": (
                "episode_entrypoint is host-selected only; Owner attaches Grok with "
                "OPEN_RESEARCH (search_tool,use_tool,web_search,web_fetch) against "
                "episode_lab lab ops. Not INSTRUMENT_CANARY."
                + (
                    " Idle-hold active: no research/schedule/freeze/settle until host "
                    "docker exec attach; exits on SIGTERM."
                    if hold
                    else ""
                )
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


def _emit_idle_status(*, hold: bool) -> None:
    payload = {
        "status": "EPISODE_ENTRYPOINT_IDLE_HOLD" if hold else "EPISODE_ENTRYPOINT_IDLE",
        "profile": PROFILE,
        "completion_claim_allowed": False,
        "hold": hold,
    }
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def idle_hold_until_signal() -> int:
    """Block until SIGTERM/SIGINT without busy-loop, provider, or work dispatch.

    Return 0 after a clean signal-driven stop so docker stop does not leave
    a stuck PID 1. Does not claim research completion.
    """
    if _HOLD_WAIT_HOOK is not None:
        _HOLD_WAIT_HOOK()
        return 0

    done = threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        done.set()

    previous: dict[int, object] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[sig] = signal.signal(sig, _stop)
        except (ValueError, OSError):
            # Non-main thread or unsupported signal — continue with remaining.
            pass
    try:
        # Event.wait with no timeout blocks the thread without spinning.
        # Wake periodically only so a missed signal install can still be killed
        # by the outer docker stop → SIGKILL path (no self-restart).
        while not done.is_set():
            done.wait(timeout=3600.0)
    finally:
        for sig, prev in previous.items():
            try:
                signal.signal(sig, prev)  # type: ignore[arg-type]
            except (ValueError, OSError):
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-describe" in args or os.environ.get("XINAO_EPISODE_SELF_DESCRIBE") == "1":
        sys.stdout.write(
            json.dumps(self_describe(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        return 0

    hold = "--hold" in args or os.environ.get("XINAO_EPISODE_HOLD") == "1"
    # Host dual-container orchestration attaches Grok with attempt-local MCP config.
    # With --hold: stay running so docker exec / require_live_pair_ready can attach.
    # Without --hold: fail-closed receipt + immediate exit (not canary success).
    _write_awaiting_receipt(args, hold=hold)
    _emit_idle_status(hold=hold)
    if hold:
        return idle_hold_until_signal()
    # Non-hold bare invoke: exit 0 after receipt so accidental default ENTRYPOINT
    # swap cannot green canary research semantics (no model call, no claim).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
