from __future__ import annotations

import argparse
import json
from pathlib import Path

from .l0_canary import run_l0_next_draw, verify_l0_next_draw_run
from .public_sources import (
    build_p6_trusted_anchor,
    capture_p6_official_sources,
    run_p6_public_source_role_ruleclaim,
    verify_p6_capture_bundle,
    verify_p6_run,
)
from .runner import (
    build_p4_trusted_anchor,
    build_p5_trusted_anchor,
    compare_ledgers,
    run_p1,
    run_p2_domain_lineage_zhengma,
    run_p3_research_protocol_judge,
    run_p4_exact_null_contamination_structure,
    run_p5_unresolved_semantics_evidence_catalog,
    verify_p3_run,
    verify_p4_run,
    verify_p5_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Xinao P1 mechanics lab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    p1 = subparsers.add_parser("p1", help="run the P1 vertical slice into a new evidence directory")
    p1.add_argument("--input-root", type=Path, required=True)
    p1.add_argument("--evidence-root", type=Path, required=True)
    p1.add_argument("--run-name", required=True)
    p2 = subparsers.add_parser(
        "p2-domain-lineage-zhengma",
        help="run the P2 lineage-v2 and spec-pinned regular-set mechanics vertical",
    )
    p2.add_argument("--input-root", type=Path, required=True)
    p2.add_argument("--evidence-root", type=Path, required=True)
    p2.add_argument("--run-name", required=True)
    p2_catalog = subparsers.add_parser(
        "p2-rule-catalog-pure-settle",
        help="run the accepted P2 eight-rule catalog, pure settlement, hash-chain, and lineage vertical",
    )
    p2_catalog.add_argument("--input-root", type=Path, required=True)
    p2_catalog.add_argument("--evidence-root", type=Path, required=True)
    p2_catalog.add_argument("--run-name", required=True)
    p3 = subparsers.add_parser(
        "p3-research-protocol-judge",
        help="run the frozen finite research protocol and evidence-bounded Judge gate",
    )
    p3.add_argument("--input-root", type=Path, required=True)
    p3.add_argument("--evidence-root", type=Path, required=True)
    p3.add_argument("--run-name", required=True)
    p3.add_argument("--p2-evidence-run", type=Path, required=True)
    p3_verify = subparsers.add_parser(
        "p3-verify",
        help="read-only semantic replay and claim-gate verification of a P3 run",
    )
    p3_verify.add_argument("--input-root", type=Path, required=True)
    p3_verify.add_argument("--run-dir", type=Path, required=True)
    p4 = subparsers.add_parser(
        "p4-exact-null-contamination-structure",
        help="run the frozen five-test joint null and deterministic contamination gate",
    )
    p4.add_argument("--input-root", type=Path, required=True)
    p4.add_argument("--evidence-root", type=Path, required=True)
    p4.add_argument("--run-name", required=True)
    p4.add_argument("--p3-evidence-run", type=Path, required=True)
    p4_verify = subparsers.add_parser(
        "p4-verify",
        help="fully resimulate and semantically verify a P4 run",
    )
    p4_verify.add_argument("--input-root", type=Path, required=True)
    p4_verify.add_argument("--run-dir", type=Path, required=True)
    p4_verify.add_argument("--trusted-anchor", type=Path)
    p4_anchor = subparsers.add_parser(
        "p4-build-trusted-anchor",
        help="verify P4 then create an immutable acceptance anchor outside the run",
    )
    p4_anchor.add_argument("--input-root", type=Path, required=True)
    p4_anchor.add_argument("--run-dir", type=Path, required=True)
    p4_anchor.add_argument("--anchor-path", type=Path, required=True)
    p5 = subparsers.add_parser(
        "p5-unresolved-semantics-evidence-catalog",
        help="build the frozen 33-file evidence catalog without resolving economic semantics",
    )
    p5.add_argument("--input-root", type=Path, required=True)
    p5.add_argument("--evidence-root", type=Path, required=True)
    p5.add_argument("--run-name", required=True)
    p5.add_argument("--p4-evidence-run", type=Path, required=True)
    p5.add_argument("--p4-trusted-anchor", type=Path, required=True)
    p5.add_argument("--admin-acceptance", type=Path, required=True)
    p5_verify = subparsers.add_parser(
        "p5-verify",
        help="independently rebuild the P5 scan, selectors, claims, classification, and Judge",
    )
    p5_verify.add_argument("--input-root", type=Path, required=True)
    p5_verify.add_argument("--run-dir", type=Path, required=True)
    p5_verify.add_argument("--p4-evidence-run", type=Path, required=True)
    p5_verify.add_argument("--p4-trusted-anchor", type=Path, required=True)
    p5_verify.add_argument("--admin-acceptance", type=Path, required=True)
    p5_verify.add_argument("--trusted-anchor", type=Path)
    p5_anchor = subparsers.add_parser(
        "p5-build-trusted-anchor",
        help="verify P5 then create an acceptance anchor outside the run",
    )
    p5_anchor.add_argument("--input-root", type=Path, required=True)
    p5_anchor.add_argument("--run-dir", type=Path, required=True)
    p5_anchor.add_argument("--p4-evidence-run", type=Path, required=True)
    p5_anchor.add_argument("--p4-trusted-anchor", type=Path, required=True)
    p5_anchor.add_argument("--admin-acceptance", type=Path, required=True)
    p5_anchor.add_argument("--anchor-path", type=Path, required=True)
    p6_capture = subparsers.add_parser(
        "p6-capture-official-sources",
        help="perform one exact allowlisted official-source GET capture into an immutable WARC",
    )
    p6_capture.add_argument("--capture-root", type=Path, required=True)
    p6_capture.add_argument("--capture-name", required=True)
    p6_capture.add_argument("--capture-anchor-path", type=Path, required=True)
    p6_capture.add_argument("--p5-evidence-run", type=Path, required=True)
    p6_capture.add_argument("--p5-trusted-anchor", type=Path, required=True)
    p6_capture.add_argument("--p5-admin-acceptance", type=Path, required=True)
    p6_capture.add_argument("--p5-independent-report", type=Path, required=True)
    p6_capture_verify = subparsers.add_parser(
        "p6-verify-capture",
        help="offline verification of the immutable P6 capture bundle and external anchor",
    )
    p6_capture_verify.add_argument("--capture-dir", type=Path, required=True)
    p6_capture_verify.add_argument("--capture-anchor-path", type=Path, required=True)
    p6_capture_verify.add_argument("--p5-evidence-run", type=Path, required=True)
    p6_capture_verify.add_argument("--p5-trusted-anchor", type=Path, required=True)
    p6_capture_verify.add_argument("--p5-admin-acceptance", type=Path, required=True)
    p6_capture_verify.add_argument("--p5-independent-report", type=Path, required=True)
    p6 = subparsers.add_parser(
        "p6-public-source-role-ruleclaim",
        help="build the P6 public-source role and unresolved RuleClaim evidence vertical offline",
    )
    p6.add_argument("--evidence-root", type=Path, required=True)
    p6.add_argument("--run-name", required=True)
    p6.add_argument("--capture-dir", type=Path, required=True)
    p6.add_argument("--capture-anchor-path", type=Path, required=True)
    p6.add_argument("--p5-evidence-run", type=Path, required=True)
    p6.add_argument("--p5-trusted-anchor", type=Path, required=True)
    p6.add_argument("--p5-admin-acceptance", type=Path, required=True)
    p6.add_argument("--p5-independent-report", type=Path, required=True)
    p6_verify = subparsers.add_parser(
        "p6-verify",
        help="offline semantic replay of a P6 formal run",
    )
    p6_verify.add_argument("--run-dir", type=Path, required=True)
    p6_verify.add_argument("--capture-dir", type=Path, required=True)
    p6_verify.add_argument("--capture-anchor-path", type=Path, required=True)
    p6_verify.add_argument("--p5-evidence-run", type=Path, required=True)
    p6_verify.add_argument("--p5-trusted-anchor", type=Path, required=True)
    p6_verify.add_argument("--p5-admin-acceptance", type=Path, required=True)
    p6_verify.add_argument("--p5-independent-report", type=Path, required=True)
    p6_verify.add_argument("--trusted-anchor", type=Path)
    p6_anchor = subparsers.add_parser(
        "p6-build-trusted-anchor",
        help="verify P6 then create an immutable formal acceptance anchor outside the run",
    )
    p6_anchor.add_argument("--run-dir", type=Path, required=True)
    p6_anchor.add_argument("--capture-dir", type=Path, required=True)
    p6_anchor.add_argument("--capture-anchor-path", type=Path, required=True)
    p6_anchor.add_argument("--p5-evidence-run", type=Path, required=True)
    p6_anchor.add_argument("--p5-trusted-anchor", type=Path, required=True)
    p6_anchor.add_argument("--p5-admin-acceptance", type=Path, required=True)
    p6_anchor.add_argument("--p5-independent-report", type=Path, required=True)
    p6_anchor.add_argument("--anchor-path", type=Path, required=True)
    l0 = subparsers.add_parser(
        "l0-next-draw",
        help="run the canonical 1204-row business-L0 next-draw categorical canary",
    )
    l0.add_argument("--input-root", type=Path, required=True)
    l0.add_argument("--evidence-root", type=Path, required=True)
    l0.add_argument("--run-name", required=True)
    l0_verify = subparsers.add_parser(
        "l0-next-draw-verify",
        help="independently recompute and verify a business-L0 next-draw run",
    )
    l0_verify.add_argument("--input-root", type=Path, required=True)
    l0_verify.add_argument("--run-dir", type=Path, required=True)
    compare = subparsers.add_parser("compare-ledgers", help="compare two P1 trial ledgers byte-for-byte")
    compare.add_argument("first_run", type=Path)
    compare.add_argument("second_run", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "p1":
        result = run_p1(input_root=args.input_root, evidence_root=args.evidence_root, run_name=args.run_name)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command in {"p2-domain-lineage-zhengma", "p2-rule-catalog-pure-settle"}:
        result = run_p2_domain_lineage_zhengma(
            input_root=args.input_root,
            evidence_root=args.evidence_root,
            run_name=args.run_name,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p3-research-protocol-judge":
        result = run_p3_research_protocol_judge(
            input_root=args.input_root,
            evidence_root=args.evidence_root,
            run_name=args.run_name,
            p2_evidence_run=args.p2_evidence_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p3-verify":
        result = verify_p3_run(input_root=args.input_root, run_dir=args.run_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p4-exact-null-contamination-structure":
        result = run_p4_exact_null_contamination_structure(
            input_root=args.input_root,
            evidence_root=args.evidence_root,
            run_name=args.run_name,
            p3_evidence_run=args.p3_evidence_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p4-verify":
        result = verify_p4_run(
            input_root=args.input_root,
            run_dir=args.run_dir,
            trusted_anchor=args.trusted_anchor,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p4-build-trusted-anchor":
        result = build_p4_trusted_anchor(
            input_root=args.input_root,
            run_dir=args.run_dir,
            anchor_path=args.anchor_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p5-unresolved-semantics-evidence-catalog":
        result = run_p5_unresolved_semantics_evidence_catalog(
            input_root=args.input_root,
            evidence_root=args.evidence_root,
            run_name=args.run_name,
            p4_evidence_run=args.p4_evidence_run,
            p4_trusted_anchor=args.p4_trusted_anchor,
            admin_acceptance=args.admin_acceptance,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p5-verify":
        result = verify_p5_run(
            input_root=args.input_root,
            run_dir=args.run_dir,
            p4_evidence_run=args.p4_evidence_run,
            p4_trusted_anchor=args.p4_trusted_anchor,
            admin_acceptance=args.admin_acceptance,
            trusted_anchor=args.trusted_anchor,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p5-build-trusted-anchor":
        result = build_p5_trusted_anchor(
            input_root=args.input_root,
            run_dir=args.run_dir,
            p4_evidence_run=args.p4_evidence_run,
            p4_trusted_anchor=args.p4_trusted_anchor,
            admin_acceptance=args.admin_acceptance,
            anchor_path=args.anchor_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p6-capture-official-sources":
        result = capture_p6_official_sources(
            capture_root=args.capture_root,
            capture_name=args.capture_name,
            capture_anchor_path=args.capture_anchor_path,
            p5_run_dir=args.p5_evidence_run,
            p5_trusted_anchor=args.p5_trusted_anchor,
            p5_admin_acceptance=args.p5_admin_acceptance,
            p5_independent_report=args.p5_independent_report,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p6-verify-capture":
        result = verify_p6_capture_bundle(
            capture_dir=args.capture_dir,
            capture_anchor_path=args.capture_anchor_path,
            p5_run_dir=args.p5_evidence_run,
            p5_trusted_anchor=args.p5_trusted_anchor,
            p5_admin_acceptance=args.p5_admin_acceptance,
            p5_independent_report=args.p5_independent_report,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p6-public-source-role-ruleclaim":
        result = run_p6_public_source_role_ruleclaim(
            evidence_root=args.evidence_root,
            run_name=args.run_name,
            capture_dir=args.capture_dir,
            capture_anchor_path=args.capture_anchor_path,
            p5_run_dir=args.p5_evidence_run,
            p5_trusted_anchor=args.p5_trusted_anchor,
            p5_admin_acceptance=args.p5_admin_acceptance,
            p5_independent_report=args.p5_independent_report,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p6-verify":
        result = verify_p6_run(
            run_dir=args.run_dir,
            capture_dir=args.capture_dir,
            capture_anchor_path=args.capture_anchor_path,
            p5_run_dir=args.p5_evidence_run,
            p5_trusted_anchor=args.p5_trusted_anchor,
            p5_admin_acceptance=args.p5_admin_acceptance,
            p5_independent_report=args.p5_independent_report,
            trusted_anchor=args.trusted_anchor,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "p6-build-trusted-anchor":
        result = build_p6_trusted_anchor(
            run_dir=args.run_dir,
            capture_dir=args.capture_dir,
            capture_anchor_path=args.capture_anchor_path,
            p5_run_dir=args.p5_evidence_run,
            p5_trusted_anchor=args.p5_trusted_anchor,
            p5_admin_acceptance=args.p5_admin_acceptance,
            p5_independent_report=args.p5_independent_report,
            anchor_path=args.anchor_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "l0-next-draw":
        result = run_l0_next_draw(
            input_root=args.input_root,
            evidence_root=args.evidence_root,
            run_name=args.run_name,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "l0-next-draw-verify":
        result = verify_l0_next_draw_run(input_root=args.input_root, run_dir=args.run_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["verified"] else 1
    result = compare_ledgers(args.first_run, args.second_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
