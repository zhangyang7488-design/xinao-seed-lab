#!/usr/bin/env python3
"""Deterministic stdin caveman-compress shim for L8 thin glue (no LLM required)."""

from __future__ import annotations

import re
import sys

_FILLER = re.compile(
    r"\b(just|really|basically|actually|simply|essentially|generally|certainly|of course)\b",
    re.IGNORECASE,
)
_ARTICLES = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)


def compress_text(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence or "`" in line or line.strip().startswith(("#", "- ", "* ")):
            lines.append(line)
            continue
        shrunk = _FILLER.sub("", line)
        shrunk = _ARTICLES.sub("", shrunk)
        shrunk = re.sub(r"\s+", " ", shrunk).strip(" ,.")
        if shrunk:
            lines.append(shrunk)
    return "\n".join(lines)


def main() -> int:
    out = compress_text(sys.stdin.read())
    sys.stdout.write(out)
    if out and not out.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())