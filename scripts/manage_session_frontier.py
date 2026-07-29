#!/usr/bin/env python3
"""Bind a Codex session or render its live frontier after native compaction."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.session_frontier_projection import (  # noqa: E402
    DEFAULT_FRONTIER_ROOT,
    DEFAULT_RENDER_CHAR_BUDGET,
    DEFAULT_TASK_RUN_ROOTS,
    FrontierProjectionError,
    bind_session,
    build_live_frontier,
    handle_compact_session_start,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontier-root", type=Path, default=DEFAULT_FRONTIER_ROOT)
    parser.add_argument("--allowed-run-root", type=Path, action="append", dest="allowed_run_roots")
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind")
    bind.add_argument("--session-id")
    bind.add_argument("--run-directory", type=Path, required=True)
    bind.add_argument("--expected-current-run-id")
    verify = commands.add_parser("verify-binding")
    verify.add_argument("--session-id")
    verify.add_argument("--char-budget", type=int, default=DEFAULT_RENDER_CHAR_BUDGET)
    compact = commands.add_parser("hook-session-start")
    compact.add_argument("--char-budget", type=int, default=DEFAULT_RENDER_CHAR_BUDGET)
    return parser


def _hook_input() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise FrontierProjectionError("hook stdin is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FrontierProjectionError("hook stdin must be a JSON object")
    return value


def main() -> int:
    args = _parser().parse_args()
    allowed_run_roots = tuple(args.allowed_run_roots or DEFAULT_TASK_RUN_ROOTS)
    try:
        if args.command == "bind":
            session_id = args.session_id or os.environ.get("CODEX_THREAD_ID")
            result = bind_session(
                session_id=str(session_id or ""),
                run_directory=args.run_directory,
                frontier_root=args.frontier_root,
                allowed_run_root=allowed_run_roots,
                expected_current_run_id=args.expected_current_run_id,
            )
            print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
            return 0
        if args.command == "verify-binding":
            session_id = args.session_id or os.environ.get("CODEX_THREAD_ID")
            result = build_live_frontier(
                session_id=str(session_id or ""),
                frontier_root=args.frontier_root,
                allowed_run_root=allowed_run_roots,
                char_budget=args.char_budget,
            )
            receipt = {
                "binding_sha256": result["binding_sha256"],
                "compact_recovery_verified": True,
                "completion_claim_allowed": False,
                "rendered_context_chars": result["rendered_context_chars"],
                "run_id": result["run_id"],
                "session_id": result["session_id"],
            }
            print(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True))
            return 0
        hook_input = _hook_input()
        output = handle_compact_session_start(
            hook_input,
            frontier_root=args.frontier_root,
            allowed_run_root=allowed_run_roots,
            char_budget=args.char_budget,
        )
        if output is not None:
            print(json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True))
            sys.stdout.flush()
        return 0
    except FrontierProjectionError as exc:
        if args.command == "hook-session-start":
            return 0
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
