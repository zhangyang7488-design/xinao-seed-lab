#!/usr/bin/env python3
"""Validate contract JSON schemas parse and self-check basic structure."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRS = (
    REPO_ROOT / "contracts" / "schemas",
    REPO_ROOT / "schemas",
)


def main() -> int:
    errors: list[str] = []
    checked = 0

    for schema_dir in SCHEMA_DIRS:
        if not schema_dir.is_dir():
            continue
        for path in sorted(schema_dir.rglob("*.json")):
            checked += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"{path}: invalid JSON ({exc})")
                continue
            if not isinstance(payload, dict):
                errors.append(f"{path}: root must be a JSON object")
                continue
            if "$schema" in payload and not isinstance(payload["$schema"], str):
                errors.append(f"{path}: $schema must be a string when present")

    if errors:
        print("JSON schema validation failed:")
        for item in errors:
            print(f"  - {item}")
        return 1

    print(f"Validated {checked} JSON schema/document files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
