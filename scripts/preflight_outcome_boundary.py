#!/usr/bin/env python3
"""Inspect or conditionally emit one text artifact under a literal period cutoff."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.outcome_boundary_preflight import (  # noqa: E402
    DEFAULT_MAX_BYTES,
    OutcomeBoundaryPreflightError,
    emit_if_outcome_boundary_allows,
    inspect_outcome_boundary,
)

EXIT_ERROR = 2
EXIT_DENIED = 3


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight one exact text byte snapshot before semantic rendering. "
            "Denied content is never printed."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("scan", "emit"):
        child = subparsers.add_parser(command)
        child.add_argument("--path", required=True, type=Path)
        child.add_argument("--cutoff-period", required=True, type=int)
        child.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    return parser.parse_args(argv)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _error_report(path: Path, error: Exception) -> dict[str, object]:
    return {
        "schema_version": "xinao.outcome_boundary_preflight_error.v1",
        "authority": False,
        "completion_claim_allowed": False,
        "source_path": str(path.resolve(strict=False)),
        "disposition": "ERROR_NO_SEMANTIC_READ",
        "semantic_read_allowed": False,
        "reason_codes": ["PREFLIGHT_ERROR"],
        "error_type": type(error).__name__,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "scan":
            report = inspect_outcome_boundary(
                args.path,
                cutoff_period=args.cutoff_period,
                max_bytes=args.max_bytes,
            )
            sys.stdout.buffer.write(_json_bytes(report))
        else:
            report = emit_if_outcome_boundary_allows(
                args.path,
                cutoff_period=args.cutoff_period,
                max_bytes=args.max_bytes,
                stream=sys.stdout.buffer,
            )
            if report["semantic_read_allowed"] is not True:
                sys.stderr.buffer.write(_json_bytes(report))
    except (OSError, OutcomeBoundaryPreflightError, ValueError) as exc:
        sys.stderr.buffer.write(_json_bytes(_error_report(args.path, exc)))
        return EXIT_ERROR
    return 0 if report["semantic_read_allowed"] is True else EXIT_DENIED


if __name__ == "__main__":
    raise SystemExit(main())
