from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from services.agent_runtime.context_slice_manifest import (
    DEFAULT_MAX_CONTENT_BYTES,
    build_context_slice_manifest,
    write_context_slice_manifest,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic bounded context-slice manifest from explicit selectors."
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--max-content-bytes",
        type=int,
        default=DEFAULT_MAX_CONTENT_BYTES,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = build_context_slice_manifest(
        root=args.root,
        spec_path=args.spec,
        max_content_bytes=args.max_content_bytes,
    )
    manifest_sha256 = write_context_slice_manifest(args.output, manifest)
    print(
        json.dumps(
            {
                "ok": True,
                "authority": False,
                "completion_claim_allowed": False,
                "output": str(args.output.resolve()),
                "manifest_sha256": manifest_sha256,
                "context_sha256": manifest["context_sha256"],
                "source_manifest_sha256": manifest["source_manifest_sha256"],
                "total_content_bytes": manifest["total_content_bytes"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
