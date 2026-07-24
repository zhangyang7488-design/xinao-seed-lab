#!/usr/bin/env python3
"""Read-only real consumer for the current Xinao science parent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xinao.science.active_parent import (
    SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    ScienceActiveParentError,
    load_science_active_parent,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--projection",
        type=Path,
        default=SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    )
    args = parser.parse_args()
    try:
        result = load_science_active_parent(args.projection)
    except ScienceActiveParentError as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
