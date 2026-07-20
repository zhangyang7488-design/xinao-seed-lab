#!/usr/bin/env python3
"""Atomically claim one A/B worker route before either provider model starts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_worker_package_batch import build_path_resolver  # noqa: E402
from services.agent_runtime.dispatch_economics import (  # noqa: E402
    DispatchEconomicsError,
    claim_dispatch_route,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch-envelope", type=Path, required=True)
    parser.add_argument("--dispatch-envelope-ref", default="")
    parser.add_argument("--dispatch-envelope-sha256", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--task-run-dir", type=Path, required=True)
    parser.add_argument("--task-run-cli", type=Path, required=True)
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--holder-id", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    resolver = build_path_resolver(args.path_map)
    envelope_ref_path = args.dispatch_envelope_ref.strip() or str(args.dispatch_envelope)
    try:
        result = claim_dispatch_route(
            dispatch_envelope_ref={
                "path": envelope_ref_path,
                "sha256": args.dispatch_envelope_sha256,
            },
            checkpoint_path=args.checkpoint,
            task_run_dir=args.task_run_dir,
            task_run_cli=args.task_run_cli,
            path_resolver=resolver,
            holder_id=args.holder_id,
        )
    except (DispatchEconomicsError, OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "model_invocation_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 20
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
