"""Prepare, canary, and atomically promote a Foundation authority generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xinao.foundation import assertion_verifier_registry as registry
from xinao.foundation.authority_generation import (
    DEFAULT_ARCHIVE_MANIFEST_PATH,
    DEFAULT_GENERATION_ROOT,
    DEFAULT_REVIEW_SUMMARY_PATH,
    DEFAULT_VERIFICATION_REPORT_PATH,
    prepare_authority_generation,
)
from xinao.foundation.authority_promotion import (
    DEFAULT_RECEIPT_ROOT,
    promote_authority_generation,
)

DEFAULT_PROJECTION_PATH = registry.CANONICAL_PROJECTION_PATH


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, default=DEFAULT_PROJECTION_PATH)
    parser.add_argument("--archive-manifest", type=Path, default=DEFAULT_ARCHIVE_MANIFEST_PATH)
    parser.add_argument(
        "--verification-report", type=Path, default=DEFAULT_VERIFICATION_REPORT_PATH
    )
    parser.add_argument("--review-summary", type=Path, default=DEFAULT_REVIEW_SUMMARY_PATH)
    parser.add_argument("--generation-root", type=Path, default=DEFAULT_GENERATION_ROOT)
    parser.add_argument("--receipt-root", type=Path, default=DEFAULT_RECEIPT_ROOT)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--skip-pytest", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generation = prepare_authority_generation(
        projection_path=args.projection,
        owner_id=args.owner_id,
        rationale=args.rationale,
        generation_root=args.generation_root,
        archive_manifest_path=args.archive_manifest,
        verification_report_path=args.verification_report,
        review_summary_path=args.review_summary,
    )
    receipt = promote_authority_generation(
        projection_path=args.projection,
        generation_manifest_path=generation["manifest_path"],
        receipt_root=args.receipt_root,
        run_pytest=not args.skip_pytest,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
