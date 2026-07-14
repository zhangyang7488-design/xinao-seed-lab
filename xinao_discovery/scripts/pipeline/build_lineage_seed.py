"""Build the small content-addressed seed that proves the P7 DVC pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.catalog.compiler import write_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def build(source: dict[str, Any]) -> dict[str, Any]:
    required = {
        "authority_contract_id",
        "dataset_ref",
        "dataset_hash",
        "baseline_ref",
        "baseline_hash",
        "rule_version",
        "validation_protocol_ref",
        "settlement_service_ref",
    }
    missing = sorted(required - source.keys())
    if missing:
        raise ValueError(f"lineage pipeline inputs are incomplete: {missing}")
    content = {
        "schema_version": "xinao.lineage_seed.v1",
        "inputs": {key: source[key] for key in sorted(required)},
    }
    content["content_hash"] = canonical_sha256(content)
    return content


def main() -> int:
    args = parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise TypeError("lineage pipeline input must be one JSON object")
    write_atomic(args.output, build(source))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
