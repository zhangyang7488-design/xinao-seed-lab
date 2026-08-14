#!/usr/bin/env python3
"""CLI for the Stage 0 research-of-research continuation adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# The Scheduled Task runs with ``pythonw -I`` from a frozen app bundle.  Insert
# that bundle's app root explicitly; no live repository path is required.
APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from services.research_of_research.continuation import (  # noqa: E402
    DEFAULT_RUNTIME_ROOT,
    ContinuationError,
    initialize_contract,
    reconcile,
    status,
    stop_contract,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("initialize", help="bind current receipts as inert history")
    initialize.add_argument("--contract-name", required=True)
    initialize.add_argument("--binding-path", type=Path, required=True)
    initialize.add_argument("--binding-sha256", required=True)

    subparsers.add_parser("reconcile", help="scan receipts once and exit")
    subparsers.add_parser("status", help="read current Stage 0 state")

    stop = subparsers.add_parser("stop", help="stop future observation detection")
    stop.add_argument("--expected-revision-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "initialize":
            binding_path = args.binding_path.resolve(strict=True)
            observed = _sha256_file(binding_path)
            expected = args.binding_sha256.casefold()
            if observed != expected:
                raise ContinuationError(
                    "CONTRACT_BINDING_HASH_MISMATCH",
                    f"binding hash differs: {binding_path}",
                )
            result = initialize_contract(
                args.runtime_root,
                contract_name=args.contract_name,
                source_binding={"path": str(binding_path), "sha256": expected},
            )
        elif args.command == "reconcile":
            result = reconcile(args.runtime_root)
        elif args.command == "status":
            result = status(args.runtime_root)
        else:
            result = stop_contract(
                args.runtime_root,
                expected_revision_id=args.expected_revision_id.casefold(),
            )
    except (ContinuationError, OSError) as exc:
        result = {
            "outcome": "ERROR",
            "reason_code": getattr(exc, "reason_code", type(exc).__name__),
            "message": str(exc),
            "authority": False,
            "completion_claim_allowed": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("outcome") == "LOCK_BUSY":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
