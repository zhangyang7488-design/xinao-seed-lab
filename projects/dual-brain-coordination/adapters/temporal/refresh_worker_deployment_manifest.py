"""Deterministically refresh or verify the promoted Worker Deployment manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("worker_deployment.v1.json")
SOURCE_FILES = (
    "src/xinao_coordination/temporal/workflow.py",
    "src/xinao_coordination/temporal/activities.py",
    "src/xinao_coordination/temporal/grok_parallel.py",
    "adapters/temporal/worker_runtime.py",
    "adapters/temporal/names.py",
)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def source_hashes(project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    return {
        relative: hashlib.sha256((project_root / relative).read_bytes()).hexdigest()
        for relative in SOURCE_FILES
    }


def refreshed_manifest(template: dict[str, Any], project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    hashes = source_hashes(project_root)
    digest = hashlib.sha256(canonical_json_bytes(hashes)).hexdigest()
    return {
        **template,
        "build_id": digest[:32],
        "source_digest_sha256": digest,
        "source_hashes": hashes,
    }


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--print", dest="print_manifest", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = refreshed_manifest(current)
    if args.check:
        if current != expected:
            print("worker deployment manifest drift")
            return 1
        print("worker deployment manifest current")
        return 0
    if args.print_manifest:
        print(json.dumps(expected, ensure_ascii=False, indent=2))
        return 0
    _write_atomic(manifest_path, expected)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
