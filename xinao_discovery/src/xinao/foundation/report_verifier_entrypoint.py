"""Fixed fresh-process entrypoint for FoundationClosureReport verification."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xinao.foundation.closure import verify_foundation_closure_report


def _load_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("foundation closure report must be a JSON object")
    return dict(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify_foundation_closure_report(
            _load_report(args.report),
            blueprint_path=args.projection.resolve(),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "xinao.foundation_closure_verification_error.v1",
            "ok": False,
            "foundation_execution_ready": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") is True and result.get("foundation_execution_ready") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
