#!/usr/bin/env python3
"""CLI for one bounded Luna/Terra native Codex candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.codex_inner_profile_consumer import (  # noqa: E402
    invoke_codex_inner_profile,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-key", required=True)
    parser.add_argument("--profile", required=True, choices=("inner-luna", "inner-terra"))
    parser.add_argument("--task", required=True)
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--outer-decision", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = invoke_codex_inner_profile(
            work_key=args.work_key,
            profile_ref=args.profile,
            task=args.task,
            input_paths=args.input,
            outer_decision_path=args.outer_decision,
            evidence_dir=args.evidence_dir,
            codex_home=args.codex_home,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(json.dumps({"status": "REJECTED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["outcome"] == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
