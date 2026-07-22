#!/usr/bin/env python3
"""Write hash-bound audit assessment, Owner adjudication, or repair-gate receipt."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.audit_adjudication import (  # noqa: E402
    build_audit_assessment,
    build_owner_adjudication,
    canonical_sha256,
    require_repair_authorization,
)


def _object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _atomic_json(path: Path, value: object) -> None:
    path = path.resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _prior(paths: list[str]) -> list[dict[str, Any]]:
    return [_object(Path(path), f"prior_adjudications[{index}]") for index, path in enumerate(paths)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    assessment_parser = subparsers.add_parser("assessment")
    assessment_parser.add_argument("--spec", required=True)
    assessment_parser.add_argument("--candidate-output", required=True)
    assessment_parser.add_argument("--out", required=True)

    adjudication_parser = subparsers.add_parser("adjudication")
    adjudication_parser.add_argument("--assessment", required=True)
    adjudication_parser.add_argument("--spec", required=True)
    adjudication_parser.add_argument("--prior", action="append", default=[])
    adjudication_parser.add_argument("--out", required=True)

    validate_parser = subparsers.add_parser("validate-repair")
    validate_parser.add_argument("--assessment", required=True)
    validate_parser.add_argument("--adjudication", required=True)
    validate_parser.add_argument("--work-key", required=True)
    validate_parser.add_argument("--prior", action="append", default=[])
    validate_parser.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    if args.command == "assessment":
        spec = _object(Path(args.spec), "assessment spec")
        if "candidate_output" in spec or "findings" in spec:
            raise ValueError("assessment spec cannot inline model output or findings")
        value = build_audit_assessment(
            candidate_output=_object(Path(args.candidate_output), "candidate output"),
            **spec,
        )
    elif args.command == "adjudication":
        spec = _object(Path(args.spec), "adjudication spec")
        value = build_owner_adjudication(
            assessment=_object(Path(args.assessment), "assessment"),
            prior_adjudications=_prior(args.prior),
            **spec,
        )
    else:
        assessment = _object(Path(args.assessment), "assessment")
        adjudication = _object(Path(args.adjudication), "adjudication")
        validated = require_repair_authorization(
            adjudication,
            assessment=assessment,
            expected_work_key=args.work_key,
            prior_adjudications=_prior(args.prior),
        )
        value = {
            "schema_version": "xinao.audit_repair_gate_receipt.v1",
            "work_key": args.work_key,
            "assessment_sha256": validated["assessment_sha256"],
            "adjudication_sha256": validated["adjudication_sha256"],
            "repair_authorized": True,
            "authority": False,
            "completion_claim_allowed": False,
        }
        value["receipt_sha256"] = canonical_sha256(value)

    _atomic_json(Path(args.out), value)
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
