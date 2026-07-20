"""Minimal native CLI for the current Xinao construction vertical."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xinao.catalog import compile_catalog, coverage_report, family_registry
from xinao.catalog.compiler import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_COVERAGE_PATH,
    DEFAULT_FAMILY_REGISTRY_PATH,
)
from xinao.foundation import (
    assess_foundation,
    derive_foundation_closure_report,
    verify_foundation_closure_report,
    write_json_atomic,
)
from xinao.projection import (
    build_workflow_projection,
    describe_temporal_workflow,
    render_tui,
    verify_evidence_report,
)
from xinao.world import build_world, replay_world
from xinao.world.builder import DEFAULT_WORLD_ROOT


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("catalog must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xinao")
    groups = parser.add_subparsers(dest="group", required=True)
    catalog = groups.add_parser("catalog")
    commands = catalog.add_subparsers(dest="command", required=True)
    compile_command = commands.add_parser("compile")
    compile_command.add_argument("--baseline", required=True)
    compile_command.add_argument("--input", type=Path)
    compile_command.add_argument("--out", type=Path, default=DEFAULT_CATALOG_PATH)
    coverage_command = commands.add_parser("coverage")
    coverage_command.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    coverage_command.add_argument("--out", type=Path, default=DEFAULT_COVERAGE_PATH)
    coverage_command.add_argument("--fail-on-unclassified", action="store_true")
    families_command = commands.add_parser("families")
    families_command.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    families_command.add_argument("--out", type=Path, default=DEFAULT_FAMILY_REGISTRY_PATH)
    world = groups.add_parser("world")
    world_commands = world.add_subparsers(dest="command", required=True)
    world_build = world_commands.add_parser("build")
    world_build.add_argument("--dataset", required=True)
    world_build.add_argument("--baseline", required=True)
    world_build.add_argument("--rule", required=True)
    world_build.add_argument("--out", type=Path, default=DEFAULT_WORLD_ROOT)
    world_build.add_argument("--correlation-id")
    world_build.add_argument("--workflow-id", default="xinao-build-001-world-local")
    world_build.add_argument("--run-id")
    world_replay = world_commands.add_parser("replay")
    world_replay.add_argument("--out", type=Path, default=DEFAULT_WORLD_ROOT)
    world_replay.add_argument("--verify-hash", action="store_true")
    world_replay.add_argument("--report", type=Path)
    workflow = groups.add_parser("workflow")
    workflow_commands = workflow.add_subparsers(dest="command", required=True)
    workflow_status = workflow_commands.add_parser("status")
    workflow_status.add_argument("--workflow-id", required=True)
    workflow_status.add_argument("--run-id", default="")
    workflow_status.add_argument("--report", type=Path, required=True)
    workflow_status.add_argument("--runtime-root", type=Path, required=True)
    workflow_status.add_argument("--address", default="127.0.0.1:7233")
    workflow_status.add_argument("--namespace", default="default")
    workflow_status.add_argument("--format", choices=("json", "tui"), default="tui")
    evidence = groups.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(dest="command", required=True)
    evidence_verify = evidence_commands.add_parser("verify")
    evidence_verify.add_argument("--report", type=Path, required=True)
    evidence_verify.add_argument("--runtime-root", type=Path, required=True)
    foundation = groups.add_parser("foundation")
    foundation_commands = foundation.add_subparsers(dest="command", required=True)
    foundation_legacy = foundation_commands.add_parser("legacy-gap")
    foundation_legacy.add_argument("--evidence-root", type=Path, required=True)
    foundation_legacy.add_argument("--catalog", type=Path, required=True)
    foundation_legacy.add_argument("--route-result", type=Path, required=True)
    foundation_legacy.add_argument("--operation-id", required=True)
    foundation_legacy.add_argument("--out", type=Path, required=True)
    foundation_derive = foundation_commands.add_parser("derive-report")
    foundation_derive.add_argument("--blueprint", type=Path, required=True)
    foundation_derive.add_argument("--input", type=Path, required=True)
    foundation_derive.add_argument("--out", type=Path, required=True)
    foundation_verify = foundation_commands.add_parser("verify-report")
    foundation_verify.add_argument("--blueprint", type=Path, required=True)
    foundation_verify.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.group == "catalog" and args.command == "compile":
        kwargs = {"baseline_ref": args.baseline, "output_path": args.out}
        if args.input is not None:
            kwargs["input_path"] = args.input
        catalog = compile_catalog(**kwargs)
        print(
            json.dumps(
                {
                    "ok": True,
                    "catalog_ref": catalog["catalog_ref"],
                    "entry_count": catalog["entry_count"],
                    "content_hash": catalog["content_hash"],
                    "output": str(args.out),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.group == "catalog" and args.command == "coverage":
        report = coverage_report(_load_json(args.catalog), output_path=args.out)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if args.fail_on_unclassified and report["unclassified_count"]:
            return 1
        return 0 if report["ok"] else 1
    if args.group == "catalog" and args.command == "families":
        registry = family_registry(_load_json(args.catalog), output_path=args.out)
        print(
            json.dumps(
                {
                    "identity_complete": registry["identity_complete"],
                    "foundation_compilation_complete": registry["foundation_compilation_complete"],
                    "family_count": registry["family_count"],
                    "content_hash": registry["content_hash"],
                    "output": str(args.out),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if registry["identity_complete"] else 1
    if args.group == "world" and args.command == "build":
        result = build_world(
            dataset=args.dataset,
            baseline=args.baseline,
            rule=args.rule,
            output_root=args.out,
            correlation_id=args.correlation_id,
            workflow_id=args.workflow_id,
            run_id=args.run_id,
        )
        snapshot = result["event_matrix_snapshot"]
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "matrix_sha256": snapshot["matrix_sha256"],
                    "row_count": snapshot["row_count"],
                    "nnz": snapshot["nnz"],
                    "output": str(args.out),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.group == "world" and args.command == "replay":
        if not args.verify_hash:
            raise ValueError("world replay requires --verify-hash")
        result = replay_world(args.out, report_path=args.report)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.group == "workflow" and args.command == "status":
        description = describe_temporal_workflow(
            workflow_id=args.workflow_id,
            run_id=args.run_id,
            address=args.address,
            namespace=args.namespace,
        )
        projection = build_workflow_projection(
            args.report,
            temporal_description=description,
            runtime_root=args.runtime_root,
        )
        if args.format == "json":
            print(json.dumps(projection, ensure_ascii=False, sort_keys=True))
        else:
            print(render_tui(projection))
        return 0 if projection["evidence"]["ok"] else 1
    if args.group == "evidence" and args.command == "verify":
        result = verify_evidence_report(args.report, runtime_root=args.runtime_root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.group == "foundation" and args.command == "legacy-gap":
        result = assess_foundation(
            evidence_root=args.evidence_root,
            catalog_path=args.catalog,
            route_result_path=args.route_result,
            operation_id=args.operation_id,
            output_path=args.out,
        )
        print(
            json.dumps(
                {
                    "legacy_diagnostic_only": result["legacy_diagnostic_only"],
                    "legacy_all_gates_verified": result["legacy_all_gates_verified"],
                    "foundation_closed": False,
                    "gates": {name: gate["status"] for name, gate in result["gates"].items()},
                    "content_hash": result["content_hash"],
                    "output": str(args.out),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.group == "foundation" and args.command == "derive-report":
        result = derive_foundation_closure_report(
            _load_json(args.input), blueprint_path=args.blueprint
        )
        write_json_atomic(args.out, result)
        print(
            json.dumps(
                {
                    "foundation_closed": result["foundation_closed"],
                    "formal_research_gate": result["formal_research_gate"],
                    "status": result["status"],
                    "artifact_hash": result["artifact_hash"],
                    "output": str(args.out),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result["foundation_closed"] else 2
    if args.group == "foundation" and args.command == "verify-report":
        result = verify_foundation_closure_report(
            _load_json(args.report), blueprint_path=args.blueprint
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
