#!/usr/bin/env python3
"""Byte-compile Python sources to catch syntax errors early in CI."""

from __future__ import annotations

import compileall
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    REPO_ROOT / "src",
    REPO_ROOT / "services",
    REPO_ROOT / "tests",
    REPO_ROOT / "scripts",
)


def main() -> int:
    ok = True
    for target in TARGETS:
        if not target.exists():
            continue
        if not compileall.compile_dir(
            str(target),
            quiet=1,
            force=True,
            legacy=False,
        ):
            ok = False
            print(f"compile failed: {target}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())