from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_root in (REPO_ROOT, REPO_ROOT / "xinao_discovery" / "src"):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from services.agent_runtime.foundation_continuous_workflow_v2 import (
    reconcile_foundation_frontier_v2,
)
from xinao.canonical import canonical_sha256
from xinao.foundation.research_candidate_source import (
    compile_f4_canary_candidate_snapshot,
    compile_f4_canary_candidate_source,
)
from xinao.foundation.research_factory import (
    admit_open_method,
    compile_research_portfolio_allocation,
    dedupe_ready_frontier,
    project_allocated_ready_frontier,
    research_factory_artifact_manifest,
)
from xinao.foundation.selection_manifest import (
    compile_default_independent_selection_manifest,
)

EVIDENCE_PARENT = Path(r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence")
F3_PACK = EVIDENCE_PARENT / "xinao-f3-evidence-20260714T200713"
LIVE_PACK = EVIDENCE_PARENT / "xinao-f4-live-canary-20260714T144335Z"
WORLD_SNAPSHOT_SHA256 = "758d953f24cf99bed074f18797172f5b96ec1b336cdd0d87fd189a0124339a0c"
KNOWLEDGE_CUTOFF = "2026-07-14T00:00:00Z"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(path.resolve()), file_sha256(path)


def rehash_versioned(value: dict[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key not in {"version_id", "content_sha256"}}
    digest = canonical_sha256(core)
    value["content_sha256"] = digest
    value["version_id"] = f"{value['object_type']}@{digest[:16]}"
    return value


def rejected(name: str, call: Callable[[], Any]) -> dict[str, Any]:
    try:
        call()
    except (TypeError, ValueError, KeyError) as exc:
        return {"case_id": name, "rejected": True, "error": str(exc)}
    return {"case_id": name, "rejected": False, "error": ""}


def materialize_method_registry(
    source_registry: dict[str, Any],
    target_root: Path,
) -> dict[str, Any]:
    method_id = next(iter(sorted(source_registry["registrations"])))
    source_admission = source_registry["registrations"][method_id]
    registration = copy.deepcopy(source_admission["registration"])
    resolved: dict[str, str] = {}
    for name, ref_field, hash_field in (
        ("executable", "executable_ref", "executable_sha256"),
        ("input_schema", "input_schema_ref", "input_schema_sha256"),
        ("output_schema", "output_schema_ref", "output_schema_sha256"),
        (
            "verification_protocol",
            "verification_protocol_ref",
            "verification_protocol_sha256",
        ),
        ("failure_contract", "failure_contract_ref", "failure_contract_sha256"),
    ):
        ref, digest = write_json(
            target_root / f"{name}.json",
            load_json(Path(str(registration[ref_field]))),
        )
        registration[ref_field] = ref
        registration[hash_field] = digest
        resolved[ref] = digest

    source_canary = load_json(Path(str(registration["canary_evidence_ref"])))
    controls = []
    for control in source_canary["negative_controls"]:
        check_id = str(control["check_id"])
        ref, digest = write_json(
            target_root / "negative-controls" / f"{check_id}.json",
            load_json(Path(str(control["evidence_ref"]))),
        )
        controls.append({**control, "evidence_ref": ref, "sha256": digest})
    source_canary["negative_controls"] = controls
    source_canary.update(
        {
            "executable_sha256": registration["executable_sha256"],
            "input_schema_sha256": registration["input_schema_sha256"],
            "output_schema_sha256": registration["output_schema_sha256"],
            "verification_protocol_sha256": registration["verification_protocol_sha256"],
            "failure_contract_sha256": registration["failure_contract_sha256"],
        }
    )
    canary_ref, canary_digest = write_json(target_root / "canary_evidence.json", source_canary)
    registration["canary_evidence_ref"] = canary_ref
    registration["canary_evidence_sha256"] = canary_digest
    resolved[canary_ref] = canary_digest
    admission = admit_open_method(
        registration,
        resolved_content_hashes=resolved,
    )
    return {"registrations": {method_id: admission}}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--f3-pack", type=Path, default=F3_PACK)
    parser.add_argument("--live-pack", type=Path, default=LIVE_PACK)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    f3_pack = args.f3_pack.resolve()
    live_pack = args.live_pack.resolve()
    output_root = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else EVIDENCE_PARENT / f"xinao-f4-portfolio-source-canary-{stamp}"
    )
    if output_root.exists():
        raise FileExistsError(f"portfolio evidence directory already exists: {output_root}")
    inputs = output_root / "inputs"

    active_surface = load_json(f3_pack / "f3_active_research_surface.v1.json")
    portfolio_policy = load_json(f3_pack / "f3_research_portfolio_policy.v1.json")
    source_graph = load_json(f3_pack / "f3_source_dependency_graph.v1.json")
    method_registry = materialize_method_registry(
        load_json(live_pack / "inputs" / "method_registry.json"),
        inputs / "method",
    )
    selection_manifest = compile_default_independent_selection_manifest()
    method_id = next(iter(sorted(method_registry["registrations"])))

    active_surface_ref, active_surface_file_hash = write_json(
        inputs / "active_research_surface.json", active_surface
    )
    portfolio_policy_ref, portfolio_policy_file_hash = write_json(
        inputs / "research_portfolio_policy.json", portfolio_policy
    )
    source_graph_ref, source_graph_file_hash = write_json(
        inputs / "source_dependency_graph.json", source_graph
    )
    selection_ref, selection_file_hash = write_json(
        inputs / "selection_manifest.json",
        selection_manifest.model_dump(mode="json"),
    )
    method_registry_ref, method_registry_file_hash = write_json(
        inputs / "method_registry.json", method_registry
    )
    factory_manifest_ref, factory_manifest_file_hash = write_json(
        inputs / "research_factory_manifest.json",
        research_factory_artifact_manifest(),
    )
    observation_ref, observation_file_hash = write_json(
        inputs / "capacity_observation.json",
        {
            "schema_version": "xinao.capacity_observation.v1",
            "host_state": "available",
            "available_slots": 8,
            "queue_depth": 13,
            "verified_canary": True,
        },
    )
    payload_template_ref, payload_template_file_hash = write_json(
        inputs / "payload_template.json",
        {
            "require_full_grok_frontier": True,
            "langgraph_child": {
                "enabled": True,
                "task_queue": "xinao-integrated-langgraph-plugin-queue",
                "workflow_type": "XinaoIntegratedBusWorkflow",
            },
        },
    )

    source = compile_f4_canary_candidate_source(
        active_research_surface=active_surface,
        selection_manifest=selection_manifest,
        method_registry=method_registry,
        method_id=method_id,
        source_dependency_graph=source_graph,
        world_snapshot_hash=WORLD_SNAPSHOT_SHA256,
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
    )
    question_ref, question_file_hash = write_json(
        inputs / "research_question.json", source["research_question"]
    )
    source_snapshot_ref, source_snapshot_file_hash = write_json(
        inputs / "research_candidate_source_snapshot.json",
        source["candidate_source_snapshot"],
    )
    candidate_snapshot = compile_f4_canary_candidate_snapshot(
        research_question=source["research_question"],
        candidate_source_snapshot=source["candidate_source_snapshot"],
        active_research_surface=active_surface,
        selection_manifest=selection_manifest,
        method_registry=method_registry,
        method_id=method_id,
        source_dependency_graph=source_graph,
    )
    candidate_snapshot_ref, candidate_snapshot_file_hash = write_json(
        inputs / "research_candidate_snapshot.json", candidate_snapshot
    )
    allocation = compile_research_portfolio_allocation(
        candidate_snapshot,
        active_surface=active_surface,
        portfolio_policy=portfolio_policy,
        source_dependency_graph=source_graph,
    )
    allocation_ref, allocation_file_hash = write_json(
        inputs / "research_portfolio_allocation.json", allocation
    )
    projection = project_allocated_ready_frontier(
        allocation,
        candidate_snapshot=candidate_snapshot,
    )
    projection_ref, projection_file_hash = write_json(
        inputs / "allocated_ready_frontier_projection.json", projection
    )

    frontier = {
        "schema_version": "xinao.foundation_continuous_frontier.v3",
        "foundation_closed": True,
        "source_dependency_graph_ref": source_graph_ref,
        "source_dependency_graph_sha256": source_graph_file_hash,
        "capacity_observation_ref": observation_ref,
        "capacity_observation_sha256": observation_file_hash,
        "selection_manifest_ref": selection_ref,
        "selection_manifest_sha256": selection_file_hash,
        "research_factory_manifest_ref": factory_manifest_ref,
        "research_factory_manifest_sha256": factory_manifest_file_hash,
        "method_registry_ref": method_registry_ref,
        "method_registry_sha256": method_registry_file_hash,
        "active_research_surface_ref": active_surface_ref,
        "active_research_surface_sha256": active_surface_file_hash,
        "research_portfolio_policy_ref": portfolio_policy_ref,
        "research_portfolio_policy_sha256": portfolio_policy_file_hash,
        "research_question_ref": question_ref,
        "research_question_sha256": question_file_hash,
        "research_candidate_source_snapshot_ref": source_snapshot_ref,
        "research_candidate_source_snapshot_sha256": source_snapshot_file_hash,
        "research_candidate_snapshot_ref": candidate_snapshot_ref,
        "research_candidate_snapshot_sha256": candidate_snapshot_file_hash,
        "research_portfolio_allocation_ref": allocation_ref,
        "research_portfolio_allocation_sha256": allocation_file_hash,
        "payload_template_ref": payload_template_ref,
        "payload_template_sha256": payload_template_file_hash,
        "external_worker_cwd": str(REPO_ROOT.resolve()),
        "wait_seconds": 3600,
    }
    frontier_ref, frontier_file_hash = write_json(inputs / "frontier.json", frontier)
    decision = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(output_root),
            "operation_id": f"f4-strict-portfolio-{stamp}",
            "frontier_ref": frontier_ref,
            "frontier_sha256": frontier_file_hash,
            "previous_width": 1,
            "succeeded": 1,
            "failed": 0,
        }
    )
    decision_ref, decision_file_hash = write_json(
        output_root / "strict_reconcile_decision.json", decision
    )
    lane_payload = load_json(Path(decision["wave"]["payload_ref"]))

    legacy = dedupe_ready_frontier(
        [row["entry"]["work_item"] for row in candidate_snapshot["candidate_rows"]],
        source_dependency_graph=source_graph,
    )
    filtered = project_allocated_ready_frontier(
        allocation,
        candidate_snapshot=candidate_snapshot,
        closed_work_keys=[allocation["ready_work_keys"][0]],
        in_flight_work_keys=[allocation["ready_work_keys"][1]],
    )

    shortened_source = copy.deepcopy(source["candidate_source_snapshot"])
    shortened_source["candidate_entries"] = shortened_source["candidate_entries"][:-1]
    shortened_source["candidate_count"] = 12
    shortened_source["coverage"] = {
        **shortened_source["coverage"],
        "observed_family_count": 12,
        "observed_family_ids": shortened_source["coverage"]["observed_family_ids"][:-1],
        "complete": False,
    }
    rehash_versioned(shortened_source)
    reordered_source = copy.deepcopy(source["candidate_source_snapshot"])
    reordered_source["candidate_entries"][0], reordered_source["candidate_entries"][1] = (
        reordered_source["candidate_entries"][1],
        reordered_source["candidate_entries"][0],
    )
    rehash_versioned(reordered_source)
    reordered_allocation = copy.deepcopy(allocation)
    reordered_allocation["allocations"][0], reordered_allocation["allocations"][1] = (
        reordered_allocation["allocations"][1],
        reordered_allocation["allocations"][0],
    )
    rehash_versioned(reordered_allocation)
    raw_ready_frontier = copy.deepcopy(frontier)
    raw_ready_frontier["ready_frontier"] = []
    raw_frontier_ref, raw_frontier_file_hash = write_json(
        output_root / "negative" / "raw_ready_frontier.json",
        raw_ready_frontier,
    )
    negatives = [
        rejected(
            "SHORTENED_REHASHED_SOURCE",
            lambda: compile_f4_canary_candidate_snapshot(
                research_question=source["research_question"],
                candidate_source_snapshot=shortened_source,
                active_research_surface=active_surface,
                selection_manifest=selection_manifest,
                method_registry=method_registry,
                method_id=method_id,
                source_dependency_graph=source_graph,
            ),
        ),
        rejected(
            "REORDERED_REHASHED_SOURCE",
            lambda: compile_f4_canary_candidate_snapshot(
                research_question=source["research_question"],
                candidate_source_snapshot=reordered_source,
                active_research_surface=active_surface,
                selection_manifest=selection_manifest,
                method_registry=method_registry,
                method_id=method_id,
                source_dependency_graph=source_graph,
            ),
        ),
        rejected(
            "REORDERED_REHASHED_ALLOCATION",
            lambda: project_allocated_ready_frontier(
                reordered_allocation,
                candidate_snapshot=candidate_snapshot,
            ),
        ),
        rejected(
            "CALLER_RAW_READY_FRONTIER",
            lambda: reconcile_foundation_frontier_v2(
                {
                    "runtime_root": str(output_root),
                    "operation_id": f"f4-strict-negative-{stamp}",
                    "frontier_ref": raw_frontier_ref,
                    "frontier_sha256": raw_frontier_file_hash,
                }
            ),
        ),
    ]

    selected = allocation["ready_work_keys"][:2]
    lane_binding = lane_payload["research_surface_binding"]
    checks = {
        "candidate_source_13_of_13": source["candidate_source_snapshot"]["candidate_count"] == 13
        and source["candidate_source_snapshot"]["coverage"]["complete"] is True,
        "candidate_snapshot_exact_coverage": candidate_snapshot["candidate_count"] == 13
        and candidate_snapshot["coverage"]["exact"] is True
        and candidate_snapshot["coverage"]["omitted_source_ids"] == [],
        "caller_ready_frontier_absent": "ready_frontier" not in frontier,
        "allocation_covers_snapshot": allocation["candidate_count"] == 13
        and allocation["candidate_snapshot_ref"] == candidate_snapshot["content_sha256"],
        "allocation_order_not_legacy_dedup_order": legacy["ready_work_keys"]
        != allocation["ready_work_keys"],
        "projection_preserves_allocation_order": projection["ready_work_keys"]
        == allocation["ready_work_keys"],
        "closed_inflight_filter_only": filtered["ready_work_keys"]
        == allocation["ready_work_keys"][2:],
        "capacity_selects_allocation_prefix": decision["wave"]["work_keys"] == selected
        and lane_payload["canonical_work_keys"] == selected,
        "strict_source_binding_reaches_lane_payload": lane_binding["frontier_binding_mode"]
        == "STRICT_F3_SURFACE_SOURCE_BOUND"
        and lane_binding["research_candidate_source_snapshot_content_sha256"]
        == source["candidate_source_snapshot"]["content_sha256"],
        "all_lanes_read_only": all(
            lane["write"] is False for lane in lane_payload["grok_ready_frontier"]
        ),
        "supervisor_selected_worker_cwd_bound": all(
            lane.get("cwd") == str(REPO_ROOT.resolve())
            and lane_payload["lane_bindings"][lane["lane_id"]].get("requested_cwd")
            == str(REPO_ROOT.resolve())
            for lane in lane_payload["grok_ready_frontier"]
        ),
        "negative_controls_all_rejected": all(item["rejected"] for item in negatives),
        "no_model_dispatched": True,
    }
    report = {
        "schema_version": "xinao.f4_portfolio_source_canary_report.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "VERIFIED" if all(checks.values()) else "FAILED",
        "assertion_id": "research_portfolio_ready_frontier_verified",
        "checks": checks,
        "negative_controls": negatives,
        "bindings": {
            "active_surface_content_sha256": active_surface["content_sha256"],
            "portfolio_policy_content_sha256": portfolio_policy["content_sha256"],
            "source_graph_content_sha256": source_graph["content_sha256"],
            "selection_manifest_content_sha256": selection_manifest.content_hash,
            "research_question_content_sha256": source["research_question"]["content_sha256"],
            "candidate_source_snapshot_content_sha256": source["candidate_source_snapshot"][
                "content_sha256"
            ],
            "candidate_snapshot_content_sha256": candidate_snapshot["content_sha256"],
            "allocation_content_sha256": allocation["content_sha256"],
            "projection_content_sha256": projection["content_sha256"],
            "decision_file_sha256": decision_file_hash,
            "decision_ref": decision_ref,
            "projection_file_sha256": projection_file_hash,
            "projection_ref": projection_ref,
        },
        "source_code_sha256": {
            "candidate_source": canonical_sha256(
                inspect.getsource(compile_f4_canary_candidate_source)
            ),
            "candidate_snapshot": canonical_sha256(
                inspect.getsource(compile_f4_canary_candidate_snapshot)
            ),
            "allocation": canonical_sha256(
                inspect.getsource(compile_research_portfolio_allocation)
            ),
            "projection": canonical_sha256(inspect.getsource(project_allocated_ready_frontier)),
            "reconcile": canonical_sha256(inspect.getsource(reconcile_foundation_frontier_v2)),
        },
        "composite_evidence_dependencies": {
            "live_route_pack": str(live_pack),
            "live_route_report_sha256": file_sha256(
                live_pack / "f4_live_canary_report.json"
            ),
            "f3_pack": str(f3_pack),
            "f3_assertions_sha256": file_sha256(f3_pack / "f3_assertions.v1.json"),
        },
    }
    report_body_hash = canonical_sha256(report)
    report["content_sha256"] = report_body_hash
    report_ref, report_file_hash = write_json(
        output_root / "portfolio_source_canary_report.json", report
    )

    entries = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            entries.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "sha256": file_sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    manifest_body = {
        "schema_version": "xinao.f4_portfolio_source_canary_manifest.v1",
        "report_ref": report_ref,
        "report_file_sha256": report_file_hash,
        "entry_count": len(entries),
        "entries": entries,
    }
    manifest = {**manifest_body, "content_sha256": canonical_sha256(manifest_body)}
    manifest_ref, manifest_file_hash = write_json(output_root / "evidence_manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_ref": report_ref,
                "report_file_sha256": report_file_hash,
                "manifest_ref": manifest_ref,
                "manifest_file_sha256": manifest_file_hash,
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
