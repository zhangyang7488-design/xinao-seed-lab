#!/usr/bin/env python3
"""Build one deterministic F4 foundation-v4 relocation source capsule."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.foundation.foundation_v4_relocation_capsule_builder import (
    F4_BLOCK_ID,
    RelocationCapsuleBuildError,
    build_foundation_v4_relocation_source_capsule,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--block-id", default=F4_BLOCK_ID)
    parser.add_argument("--operation-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_foundation_v4_relocation_source_capsule(
            closure_root=args.closure_root,
            snapshot_root=args.snapshot_root,
            output_root=args.output_root,
            block_id=args.block_id,
            operation_id=args.operation_id,
        )
    except RelocationCapsuleBuildError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "output_root": str(result.output_root),
                "capsule_manifest_path": str(result.capsule_manifest_path),
                "build_receipt_path": str(result.build_receipt_path),
                "capsule_manifest_sha256": result.capsule_manifest_sha256,
                "payload_exact_inventory_sha256": result.payload_exact_inventory_sha256,
                "payload_file_count": result.payload_file_count,
                "payload_total_size_bytes": result.payload_total_size_bytes,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
