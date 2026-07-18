#!/usr/bin/env python3
"""Build one current F1-F4 closure pack from an explicit material manifest."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xinao.foundation.closure_pack import build_foundation_closure_pack

MANIFEST_SCHEMA_VERSION = "xinao.current_foundation_closure_materials.v1"


def _json_default(value: object) -> str:
    """Serialize only the Path boundary intentionally returned by the pack builder."""

    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported CLI JSON value: {type(value).__name__}")


def load_material_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the exact input/artifact maps without granting the manifest authority."""

    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "input_evidence",
        "artifact_materials",
    }:
        raise ValueError("material manifest must contain the exact v1 fields")
    if value["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError("material manifest schema version is not current")
    inputs = value["input_evidence"]
    artifacts = value["artifact_materials"]
    if not isinstance(inputs, Mapping) or not isinstance(artifacts, Mapping):
        raise ValueError("material manifest maps are invalid")
    return dict(inputs), dict(artifacts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--created-at", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_evidence, artifact_materials = load_material_manifest(args.manifest)
    result = build_foundation_closure_pack(
        output_root=args.output_root,
        input_evidence=input_evidence,
        artifact_materials=artifact_materials,
        report_id=args.report_id,
        version=args.version,
        created_at=args.created_at,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
