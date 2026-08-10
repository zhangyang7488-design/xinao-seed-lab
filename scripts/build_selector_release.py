#!/usr/bin/env python3
"""Build, validate, and optionally promote the stable selector release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.selector_release import (  # noqa: E402
    SelectorReleaseError,
    build_selector_release,
    load_current_selector_release,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--release-id")
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--no-venv", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--show-current", action="store_true")
    parser.add_argument(
        "--migrate-current-v1",
        action="store_true",
        help="one-shot CAS migration from the exact current v1 pointer to this new v2 release",
    )
    args = parser.parse_args()
    if args.migrate_current_v1 and not args.promote:
        parser.error("--migrate-current-v1 requires --promote")
    if args.show_current and args.promote:
        parser.error("--show-current cannot be combined with --promote")
    if not args.show_current and not args.release_id:
        parser.error("--release-id is required unless --show-current is used")
    try:
        result = (
            load_current_selector_release(args.runtime_root)
            if args.show_current
            else build_selector_release(
                source_root=args.source_root,
                runtime_root=args.runtime_root,
                release_id=args.release_id,
                python_executable=args.python_executable,
                create_venv=not args.no_venv,
                promote=args.promote,
                migrate_current_v1=args.migrate_current_v1,
            )
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, SelectorReleaseError) as exc:
        print(f"SELECTOR_RELEASE_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
