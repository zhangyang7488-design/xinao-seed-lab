from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.situation_snapshot_lab.probe_runner import (
    ProbeRunConfig,
    run_action_only_pilot,
    run_first_pilot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the cold Situation Snapshot falsification pilot")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--allowed-output-parent", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--codex-executable", type=Path, required=True)
    parser.add_argument("--auth-target", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="max")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mode", choices=("first-pilot", "action-only"), default="first-pilot")
    args = parser.parse_args()
    config = ProbeRunConfig(
            run_id=args.run_id,
            run_root=args.run_root,
            allowed_output_parent=args.allowed_output_parent,
            source_root=args.source_root,
            codex_executable=args.codex_executable,
            auth_target=args.auth_target,
            model=args.model,
            model_reasoning_effort=args.reasoning_effort,
            timeout_seconds=args.timeout_seconds,
        )
    runner = run_action_only_pilot if args.mode == "action-only" else run_first_pilot
    manifest = runner(config)
    print(f"{manifest['status']}: {args.run_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
