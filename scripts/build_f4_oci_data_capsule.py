#!/usr/bin/env python3
"""Build the exact data-only capsule consumed by the F4 OCI verifier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xinao.foundation.f4_evidence_snapshot import (
    EvidenceSnapshotBuilder,
    verify_snapshot_manifest,
)
from xinao.foundation.foundation_v4_relocation_capsule_builder import (
    F4_BLOCK_ID,
    RelocationCapsuleBuildError,
    admit_f4_closure,
)

RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
PROJECT_ROOT = RUNTIME_ROOT / "projects" / "xinao_discovery"

STATIC_LOGICAL_ROOTS = {
    "live_pack": PROJECT_ROOT / "evidence" / "xinao-f4-live-canary-20260714T144335Z",
    "negative_pack": (
        PROJECT_ROOT / "evidence" / "xinao-f4-negative-reachable-cas-20260715T041819"
    ),
    "portfolio_pack": (
        PROJECT_ROOT / "evidence" / "xinao-f4-portfolio-source-canary-20260714T214427Z"
    ),
}

STATIC_LOGICAL_FILES = {
    "behavior_summary": (
        RUNTIME_ROOT
        / "state"
        / "human-capabilities"
        / "evals"
        / "behavior-regression"
        / "20260715-001105-022"
        / "summary.json"
    ),
    "bound_verification_1": (
        PROJECT_ROOT
        / "evidence"
        / "xinao-f4-portfolio-source-canary-20260714T214427Z-independent-verification"
        / "81b7e57a0850aa427a8d8dd7f6e2699b05fcaecc697afeb3afa9cf2e45f95da6.json"
    ),
    "bound_verification_2": (
        PROJECT_ROOT
        / "evidence"
        / "xinao-f4-negative-reachable-cas-20260715T041819-independent-verification-current"
        / "d4890baf4c01cb7c8b0b9286e2d4df2eff3c8a6ee3bcf03295ad0dbb297a2032.json"
    ),
}


def closure_identity_inputs(
    closure_root: Path,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """Project the canonical closure admission into the OCI snapshot namespaces."""

    closure = admit_f4_closure(closure_root)
    input_root = (closure.root / "source_materials" / "inputs").resolve()
    artifact_root = (closure.root / "source_materials" / "artifacts" / F4_BLOCK_ID).resolve()
    admitted_inputs = {
        item.source_path.resolve()
        for item in closure.bindings
        if item.kind == "input" and item.name != "compiler_code_sha256"
    }
    admitted_artifacts = {
        item.source_path.resolve() for item in closure.bindings if item.kind == "artifact"
    }
    actual_inputs = {path.resolve() for path in input_root.iterdir() if path.is_file()}
    actual_artifacts = {path.resolve() for path in artifact_root.iterdir() if path.is_file()}
    if actual_inputs != admitted_inputs or len(actual_inputs) != 9:
        raise RelocationCapsuleBuildError("F4 closure input root is not the exact six-file set")
    if actual_artifacts != admitted_artifacts or len(actual_artifacts) != 8:
        raise RelocationCapsuleBuildError(
            "F4 closure artifact root is not the exact eight-file set"
        )
    return (
        {
            "closure_inputs": input_root,
            "closure_f4_artifacts": artifact_root,
        },
        {
            "closure_f4_request": closure.request_path,
            "closure_authority_manifest": closure.authority.manifest_path,
        },
    )


def logical_inputs(
    *,
    current_source_root: Path,
    independent_support_root: Path,
    live_verification: Path,
    closure_root: Path,
) -> tuple[dict[str, Path], dict[str, Path]]:
    closure_roots, closure_files = closure_identity_inputs(closure_root)
    roots = {
        "current_source": current_source_root.resolve(),
        "independent_support": independent_support_root.resolve(),
        **STATIC_LOGICAL_ROOTS,
        **closure_roots,
    }
    files = {
        "bound_verification_0": live_verification.resolve(),
        **closure_files,
        **STATIC_LOGICAL_FILES,
    }
    return roots, files


def required_reference_registry() -> dict[str, Any]:
    return {
        "source": "xinao.f4.oci_execution.actual_reads",
        "version": "20260715.3",
        "rules": [
            {
                "rule_id": "bound-behavior-summary",
                "source_ref_glob": "root/current_source/source_bindings.json",
                "json_pointer_glob": "/behavior_regression/summary/path",
                "expected_match_count": 1,
            },
            {
                "rule_id": "bound-independent-verifications",
                "source_ref_glob": "root/current_source/source_bindings.json",
                "json_pointer_glob": "/source_packs/*/independent_verification/path",
                "expected_match_count": 3,
            },
            {
                "rule_id": "bound-pack-manifests",
                "source_ref_glob": "root/current_source/source_bindings.json",
                "json_pointer_glob": "/source_packs/*/pack_manifest/path",
                "expected_match_count": 3,
            },
            {
                "rule_id": "bound-source-packs",
                "source_ref_glob": "root/current_source/source_bindings.json",
                "json_pointer_glob": "/source_packs/*/pack/path",
                "expected_match_count": 3,
            },
            *(
                {
                    "rule_id": f"checker-input-{name.replace('_', '-')}",
                    "source_ref_glob": "file/production_checker_inputs",
                    "json_pointer_glob": f"/{name}_ref",
                    "expected_match_count": 1,
                }
                for name in (
                    "play_catalog",
                    "prior_draft",
                    "service_graph",
                    "external_synthesis",
                )
            ),
        ],
    }


def build(
    *,
    repo_root: Path,
    output_root: Path,
    current_source_root: Path,
    independent_support_root: Path,
    live_verification: Path,
    closure_root: Path,
) -> Path:
    contract_path = repo_root / "docker" / "f4-verifier" / "production_checker_inputs.v1.json"
    builder = EvidenceSnapshotBuilder(
        output_root,
        allowed_source_roots=[RUNTIME_ROOT, repo_root],
        source_aliases={
            r"D:\XINAO_RESEARCH_RUNTIME": RUNTIME_ROOT,
            "/evidence": RUNTIME_ROOT,
        },
        required_reference_registry=required_reference_registry(),
    )
    logical_roots, logical_files = logical_inputs(
        current_source_root=current_source_root,
        independent_support_root=independent_support_root,
        live_verification=live_verification,
        closure_root=closure_root,
    )
    for root_id, path in logical_roots.items():
        builder.add_root(root_id, path)
    for logical_id, path in logical_files.items():
        builder.add_file(logical_id, path)
    builder.add_file("production_checker_inputs", contract_path)
    manifest_path = builder.build()
    verify_snapshot_manifest(manifest_path)
    return manifest_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--current-source-root", type=Path, required=True)
    parser.add_argument("--independent-support-root", type=Path, required=True)
    parser.add_argument("--live-verification", type=Path, required=True)
    parser.add_argument("--closure-root", type=Path, required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    manifest_path = build(
        repo_root=args.repo_root.resolve(),
        output_root=args.output_root,
        current_source_root=args.current_source_root,
        independent_support_root=args.independent_support_root,
        live_verification=args.live_verification,
        closure_root=args.closure_root,
    )
    manifest = verify_snapshot_manifest(manifest_path)
    print(
        json.dumps(
            {
                "manifest_path": str(manifest_path),
                "content_sha256": manifest["content_sha256"],
                "logical_ref_count": manifest["logical_ref_count"],
                "reference_edge_count": manifest["reference_edge_count"],
                "required_reference_match_count": manifest["required_reference_match_count"],
                "inventory_count": manifest["inventory_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
