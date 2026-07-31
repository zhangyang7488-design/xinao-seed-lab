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
from xinao.science.prospective_cli import add_prospective_parsers, dispatch_prospective
from xinao.world import (
    build_science_episode_world,
    build_world,
    replay_science_episode_world,
    replay_world,
)
from xinao.world.builder import LEGACY_WORLD_ROOT


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("catalog must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xinao")
    groups = parser.add_subparsers(dest="group", required=True)
    add_prospective_parsers(groups)
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
    world_build.add_argument("--out", type=Path)
    world_build.add_argument("--correlation-id")
    world_build.add_argument("--workflow-id", default="xinao-science-world-local")
    world_build.add_argument("--run-id")
    world_build.add_argument("--protocol-pin", type=Path, required=True)
    world_build.add_argument("--protocol-pin-sha256", required=True)
    legacy_build = world_commands.add_parser("build-legacy")
    legacy_build.add_argument("--dataset", required=True)
    legacy_build.add_argument("--baseline", required=True)
    legacy_build.add_argument("--rule", required=True)
    legacy_build.add_argument("--out", type=Path, default=LEGACY_WORLD_ROOT)
    legacy_build.add_argument("--correlation-id")
    legacy_build.add_argument("--workflow-id", default="xinao-build-001-world-local")
    legacy_build.add_argument("--run-id")
    world_replay = world_commands.add_parser("replay")
    world_replay.add_argument("--out", type=Path, required=True)
    world_replay.add_argument("--protocol-pin", type=Path, required=True)
    world_replay.add_argument("--protocol-pin-sha256", required=True)
    world_replay.add_argument("--verify-hash", action="store_true")
    world_replay.add_argument("--report", type=Path)
    legacy_replay = world_commands.add_parser("replay-legacy")
    legacy_replay.add_argument("--out", type=Path, default=LEGACY_WORLD_ROOT)
    legacy_replay.add_argument("--verify-hash", action="store_true")
    legacy_replay.add_argument("--report", type=Path)
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
    shadow = groups.add_parser(
        "shadow",
        help="Leg-A file-backed shadow lifecycle consumer (init/freeze/settle/status/replay)",
    )
    shadow_commands = shadow.add_subparsers(dest="command", required=True)
    shadow_init = shadow_commands.add_parser("init")
    shadow_init.add_argument("--root", type=Path, required=True)
    shadow_init.add_argument("--seat-id", required=True)
    shadow_init.add_argument("--portfolio-ref", required=True)
    shadow_init.add_argument("--opening-balance")
    shadow_inspect = shadow_commands.add_parser("inspect")
    shadow_inspect.add_argument("--root", type=Path, required=True)
    shadow_status = shadow_commands.add_parser("status")
    shadow_status.add_argument("--root", type=Path, required=True)
    shadow_freeze = shadow_commands.add_parser(
        "freeze",
        help=(
            "Legacy flat episode freeze from request path only "
            "(not production portfolio Owner freeze; use prospective freeze-from-disposition)"
        ),
    )
    shadow_freeze.add_argument("--root", type=Path, required=True)
    shadow_freeze.add_argument("--request", type=Path, required=True)
    shadow_settle = shadow_commands.add_parser("settle")
    shadow_settle.add_argument("--root", type=Path, required=True)
    shadow_settle.add_argument("--outcome", type=Path, required=True)
    shadow_settle.add_argument("--settlement-ref")
    shadow_settle.add_argument("--settlement-journal-group-ref")
    shadow_settle.add_argument("--statement-ref")
    shadow_settle.add_argument("--occurred-at")
    shadow_replay = shadow_commands.add_parser("replay")
    shadow_replay.add_argument("--root", type=Path, required=True)
    # Packaged Owner consumer for ResearchEpisode pool / feedback (no monorepo walk).
    research_episode = groups.add_parser(
        "research-episode",
        help=(
            "Candidate-only ResearchEpisode pool ingest and feedback material bind "
            "(installed xinao-discovery package; no Owner adopt/freeze/settle)"
        ),
    )
    re_commands = research_episode.add_subparsers(dest="command", required=True)
    re_pool_ingest = re_commands.add_parser(
        "pool-ingest",
        help="Ingest sealed export + exact candidate manifest into candidate pool",
    )
    re_pool_ingest.add_argument("--pool-root", type=Path, required=True)
    re_pool_ingest.add_argument("--export", type=Path, required=True)
    re_pool_ingest.add_argument("--manifest", type=Path, required=True)
    # Alias matching Skill verb name for discovery parity.
    re_ingest_export = re_commands.add_parser(
        "ingest-export",
        help="Alias of pool-ingest (Skill verb parity)",
    )
    re_ingest_export.add_argument("--pool-root", type=Path, required=True)
    re_ingest_export.add_argument("--export", type=Path, required=True)
    re_ingest_export.add_argument("--manifest", type=Path, required=True)
    re_feedback = re_commands.add_parser(
        "feedback-bind",
        help="Bind sealed feedback pack as later episode material (input-only)",
    )
    re_feedback.add_argument("--portfolio-root", type=Path, required=True)
    re_feedback.add_argument("--feedback-content-hash", required=True)
    re_feedback.add_argument("--prior-candidate-result-sha256")
    re_feedback.add_argument("--prior-candidate-version")
    re_feedback.add_argument("--settled-portfolio-hash")
    re_feedback.add_argument("--target-episode-version")
    re_bind_fb = re_commands.add_parser(
        "bind-feedback-material",
        help="Alias of feedback-bind (Skill verb parity)",
    )
    re_bind_fb.add_argument("--portfolio-root", type=Path, required=True)
    re_bind_fb.add_argument("--feedback-content-hash", required=True)
    re_bind_fb.add_argument("--prior-candidate-result-sha256")
    re_bind_fb.add_argument("--prior-candidate-version")
    re_bind_fb.add_argument("--settled-portfolio-hash")
    re_bind_fb.add_argument("--target-episode-version")
    return parser


def _cli_research_episode_pool_ingest(
    *,
    pool_root: Path,
    export_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    from xinao.science.episode_export_pool_adapter import ingest_verified_episode_export

    if not export_path.is_file():
        raise FileNotFoundError(f"export missing: {export_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest missing: {manifest_path}")
    entry = ingest_verified_episode_export(
        pool_root=pool_root,
        export=export_path.read_bytes(),
        manifest_bytes=manifest_path.read_bytes(),
    )
    return {
        **dict(entry),
        "status": "POOL_ENTRY_READY",
        "owner_adopted": False,
        "candidate_only": True,
        "decision_map_projected": False,
        "freeze_written": False,
        "settlement_written": False,
        "disposition_written": False,
        "next_task_created": False,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }


def _cli_research_episode_feedback_bind(
    *,
    portfolio_root: Path,
    feedback_content_hash: str,
    prior_candidate_result_sha256: str | None = None,
    prior_candidate_version: str | None = None,
    settled_portfolio_hash: str | None = None,
    target_episode_version: str | None = None,
) -> dict[str, object]:
    from xinao.science.research_feedback_material import (
        assert_feedback_cannot_rewrite_priors,
        bind_feedback_pack_as_episode_material,
    )

    binding = bind_feedback_pack_as_episode_material(
        portfolio_root=portfolio_root,
        feedback_content_hash=feedback_content_hash,
        prior_candidate_result_sha256=prior_candidate_result_sha256,
        prior_candidate_version=prior_candidate_version,
        settled_portfolio_hash=settled_portfolio_hash,
        target_episode_version=target_episode_version,
    )
    assert_feedback_cannot_rewrite_priors(binding=binding)
    return {
        **dict(binding),
        "status": "FEEDBACK_MATERIAL_BOUND",
        "auto_start_next_research": False,
        "next_task_created": False,
        "freeze_written": False,
        "settlement_written": False,
        "disposition_written": False,
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # wave46 packaged ResearchEpisode Owner consumers (candidate-only clamp).
    if args.group == "research-episode" and args.command in {
        "pool-ingest",
        "ingest-export",
    }:
        result = _cli_research_episode_pool_ingest(
            pool_root=args.pool_root,
            export_path=args.export,
            manifest_path=args.manifest,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    if args.group == "research-episode" and args.command in {
        "feedback-bind",
        "bind-feedback-material",
    }:
        result = _cli_research_episode_feedback_bind(
            portfolio_root=args.portfolio_root,
            feedback_content_hash=args.feedback_content_hash,
            prior_candidate_result_sha256=getattr(args, "prior_candidate_result_sha256", None),
            prior_candidate_version=getattr(args, "prior_candidate_version", None),
            settled_portfolio_hash=getattr(args, "settled_portfolio_hash", None),
            target_episode_version=getattr(args, "target_episode_version", None),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
        return 0
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
        result = build_science_episode_world(
            dataset=args.dataset,
            baseline=args.baseline,
            rule=args.rule,
            output_root=args.out,
            correlation_id=args.correlation_id,
            workflow_id=args.workflow_id,
            run_id=args.run_id,
            protocol_pin_path=args.protocol_pin,
            protocol_pin_sha256=args.protocol_pin_sha256,
        )
        snapshot = result["event_matrix_snapshot"]
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "matrix_sha256": snapshot["matrix_sha256"],
                    "row_count": snapshot["row_count"],
                    "nnz": snapshot["nnz"],
                    "output": str(result["output_root"]),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.group == "world" and args.command == "build-legacy":
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
                    "authority_scope": "LEGACY_PARENT_G0_G8",
                    "matrix_sha256": snapshot["matrix_sha256"],
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
        result = replay_science_episode_world(
            args.out,
            protocol_pin_path=args.protocol_pin,
            protocol_pin_sha256=args.protocol_pin_sha256,
            report_path=args.report,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.group == "world" and args.command == "replay-legacy":
        if not args.verify_hash:
            raise ValueError("legacy world replay requires --verify-hash")
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
    if args.group == "prospective":
        return dispatch_prospective(args)
    if args.group == "shadow":
        from xinao.shadow_lifecycle.consumer import dispatch
        from xinao.shadow_lifecycle.store import StoreError

        try:
            result = dispatch(args)
        except (StoreError, ValueError, TypeError, KeyError) as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "completion_claim_allowed": False,
                        "first_episode_verified": False,
                        "candidate_only": True,
                        "production_owner_path": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("ok") else 1
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
