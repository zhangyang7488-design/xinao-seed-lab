from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import (
    build_p5_trusted_anchor,
    run_p5_unresolved_semantics_evidence_catalog,
    verify_p5_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P5 unresolved-semantics evidence catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--input-root", type=Path, required=True)
    run.add_argument("--evidence-root", type=Path, required=True)
    run.add_argument("--run-name", required=True)
    run.add_argument("--p4-evidence-run", type=Path, required=True)
    run.add_argument("--p4-trusted-anchor", type=Path, required=True)
    run.add_argument("--admin-acceptance", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--input-root", type=Path, required=True)
    verify.add_argument("--run-dir", type=Path, required=True)
    verify.add_argument("--p4-evidence-run", type=Path, required=True)
    verify.add_argument("--p4-trusted-anchor", type=Path, required=True)
    verify.add_argument("--admin-acceptance", type=Path, required=True)
    verify.add_argument("--trusted-anchor", type=Path)

    anchor = subparsers.add_parser("build-trusted-anchor")
    anchor.add_argument("--input-root", type=Path, required=True)
    anchor.add_argument("--run-dir", type=Path, required=True)
    anchor.add_argument("--p4-evidence-run", type=Path, required=True)
    anchor.add_argument("--p4-trusted-anchor", type=Path, required=True)
    anchor.add_argument("--admin-acceptance", type=Path, required=True)
    anchor.add_argument("--anchor-path", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    common = {
        "input_root": args.input_root,
        "p4_evidence_run": args.p4_evidence_run,
        "p4_trusted_anchor": args.p4_trusted_anchor,
        "admin_acceptance": args.admin_acceptance,
    }
    if args.command == "run":
        result = run_p5_unresolved_semantics_evidence_catalog(
            evidence_root=args.evidence_root,
            run_name=args.run_name,
            **common,
        )
    elif args.command == "verify":
        result = verify_p5_run(
            run_dir=args.run_dir,
            trusted_anchor=args.trusted_anchor,
            **common,
        )
    else:
        result = build_p5_trusted_anchor(
            run_dir=args.run_dir,
            anchor_path=args.anchor_path,
            **common,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
