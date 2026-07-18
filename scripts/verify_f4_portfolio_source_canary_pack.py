"""Independently verify an F4 portfolio-source canary evidence pack.

The verifier does not accept the canary report's booleans as proof.  It reads
the retained bytes, recomputes the F3/selection coverage and every persisted
content identity, rebuilds the candidate/allocation/projection relationships,
and checks the strict reconcile decision and payload.  Production functions
are used only for a supplemental exact replay and for exercising the retained
negative controls.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
for source_root in (REPO_ROOT, XINAO_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from xinao.canonical import canonical_sha256
from xinao.foundation.f4_snapshot_runtime import (
    file_sha256 as snapshot_file_sha256,
)
from xinao.foundation.f4_snapshot_runtime import (
    input_path,
    inside,
    load_object,
    readable_path,
    retained_path,
    same_path,
)

DEFAULT_PACK = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f4-portfolio-source-canary-20260714T160804Z"
)
SCHEMA_VERSION = "xinao.f4_portfolio_pack_independent_verification.v1"
ASSERTION_SCHEMA_VERSION = "xinao.content_addressed_assertion.v1"
EXPECTED_FAMILY_COUNT = 13
EXPECTED_COMPONENT_COUNT = 416
EXPECTED_SPEC_COUNT = 233
EXPECTED_NEGATIVE_CASES = {
    "CALLER_RAW_READY_FRONTIER",
    "REORDERED_REHASHED_ALLOCATION",
    "REORDERED_REHASHED_SOURCE",
    "SHORTENED_REHASHED_SOURCE",
}
EXPECTED_WRITE_BOUNDARY_CASES = {
    "WORKER_ASSUMES_CODEX_SINGLE_WRITER",
    "WORKER_LANE_REQUESTS_WRITE",
    "WORKER_LANE_REQUESTS_WRITE_TOOL",
}
BOUND_INPUTS = {
    "source_dependency_graph": "source_dependency_graph.json",
    "capacity_observation": "capacity_observation.json",
    "selection_manifest": "selection_manifest.json",
    "research_factory_manifest": "research_factory_manifest.json",
    "method_registry": "method_registry.json",
    "active_research_surface": "active_research_surface.json",
    "research_portfolio_policy": "research_portfolio_policy.json",
    "research_question": "research_question.json",
    "research_candidate_source_snapshot": "research_candidate_source_snapshot.json",
    "research_candidate_snapshot": "research_candidate_snapshot.json",
    "research_portfolio_allocation": "research_portfolio_allocation.json",
    "payload_template": "payload_template.json",
}


class VerificationError(ValueError):
    """Raised when retained evidence is incomplete, mutable, or contradictory."""


@dataclass
class Audit:
    """Count independently evaluated predicates while failing closed."""

    check_count: int = 0

    def require(self, condition: bool, message: str) -> None:
        self.check_count += 1
        if not condition:
            raise VerificationError(message)


def file_sha256(path: Path) -> str:
    return snapshot_file_sha256(path)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = load_object(path)
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"JSON evidence is not an object: {path}")
    return value


def _inside(path: Path, root: Path, *, label: str) -> Path:
    resolved = readable_path(path)
    if not inside(path, root):
        raise VerificationError(f"{label} escaped source pack: {path}")
    return resolved


def _same_path(left: object, right: object) -> bool:
    return same_path(left, right)


def _snapshot_files(pack: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(pack).as_posix(): (path.stat().st_size, file_sha256(path))
        for path in pack.rglob("*")
        if path.is_file()
    }


def _evidence_ref(path: Path) -> dict[str, Any]:
    resolved = readable_path(path, expect="file")
    return {
        "path": retained_path(path),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _assertion(
    assertion_id: str,
    evidence_paths: Iterable[Path],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    refs_by_path = {retained_path(path): _evidence_ref(path) for path in evidence_paths}
    refs = [refs_by_path[key] for key in sorted(refs_by_path)]
    body = {
        "schema_version": ASSERTION_SCHEMA_VERSION,
        "assertion_id": assertion_id,
        "status": "PASS",
        "evidence_refs": refs,
        "evidence_set_sha256": canonical_sha256(refs),
        "observed": dict(observed),
    }
    return {**body, "assertion_sha256": canonical_sha256(body)}


def _verify_manifest(
    pack: Path,
    audit: Audit,
) -> tuple[dict[str, Any], Path, dict[str, dict[str, Any]]]:
    manifest_path = pack / "evidence_manifest.json"
    manifest = _load_object(manifest_path)
    audit.require(
        manifest.get("schema_version") == "xinao.f4_portfolio_source_canary_manifest.v1",
        "unexpected portfolio canary manifest schema",
    )
    core = dict(manifest)
    recorded_content = str(core.pop("content_sha256", ""))
    audit.require(
        recorded_content == canonical_sha256(core),
        "manifest content identity drifted",
    )
    raw_entries = manifest.get("entries")
    audit.require(isinstance(raw_entries, list), "manifest entries are not a list")
    entries: dict[str, dict[str, Any]] = {}
    for raw in raw_entries:
        audit.require(isinstance(raw, dict), "manifest entry is not an object")
        relative = str(raw.get("path") or "")
        audit.require(relative and "\\" not in relative, "manifest path is not canonical")
        candidate = _inside(pack / relative, pack, label="manifest entry")
        audit.require(candidate.is_file(), f"manifest entry is missing: {relative}")
        audit.require(relative not in entries, "manifest contains a duplicate path")
        actual_hash = file_sha256(candidate)
        audit.require(
            actual_hash == str(raw.get("sha256") or ""),
            f"manifest byte hash drifted: {relative}",
        )
        audit.require(
            candidate.stat().st_size == int(raw.get("size_bytes") or -1),
            f"manifest byte size drifted: {relative}",
        )
        entries[relative] = dict(raw)
    actual_files = {
        path.relative_to(pack).as_posix()
        for path in pack.rglob("*")
        if path.is_file() and path != manifest_path
    }
    audit.require(
        set(entries) == actual_files,
        "manifest entries do not equal the exact source-pack file set",
    )
    audit.require(
        int(manifest.get("entry_count") or -1) == len(entries),
        "manifest entry count drifted",
    )
    report_path = pack / "portfolio_source_canary_report.json"
    audit.require(
        _same_path(manifest.get("report_ref"), report_path),
        "manifest report ref does not identify the retained report",
    )
    audit.require(
        manifest.get("report_file_sha256") == file_sha256(report_path),
        "manifest report byte hash drifted",
    )
    return manifest, manifest_path, entries


def _verify_versioned(
    value: Mapping[str, Any],
    audit: Audit,
    *,
    object_type: str | None = None,
) -> str:
    core = dict(value)
    recorded = str(core.pop("content_sha256", ""))
    version_id = str(core.pop("version_id", ""))
    audit.require(len(recorded) == 64, "versioned object lacks a SHA-256 identity")
    audit.require(
        canonical_sha256(core) == recorded,
        f"{object_type or 'versioned object'} content identity drifted",
    )
    actual_type = str(core.get("object_type") or "")
    if object_type is not None:
        audit.require(actual_type == object_type, f"expected {object_type}")
    audit.require(
        version_id == f"{actual_type}@{recorded[:16]}",
        f"{actual_type} version identity drifted",
    )
    return recorded


def _verify_content_hash(value: Mapping[str, Any], audit: Audit, *, label: str) -> str:
    core = dict(value)
    recorded = str(core.pop("content_hash", ""))
    audit.require(
        len(recorded) == 64 and canonical_sha256(core) == recorded,
        f"{label} content hash drifted",
    )
    return recorded


def _load_inputs(
    pack: Path,
    frontier: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
    audit: Audit,
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    values: dict[str, dict[str, Any]] = {}
    paths: list[Path] = []
    for name, filename in BOUND_INPUTS.items():
        relative = f"inputs/{filename}"
        path = pack / relative
        audit.require(relative in entries, f"bound input is absent from manifest: {name}")
        ref_field = f"{name}_ref"
        hash_field = f"{name}_sha256"
        audit.require(
            _same_path(frontier.get(ref_field), path),
            f"frontier {name} ref drifted",
        )
        audit.require(
            frontier.get(hash_field) == file_sha256(path),
            f"frontier {name} byte hash drifted",
        )
        values[name] = _load_object(path)
        paths.append(path)
    return values, paths


def _verify_selection_and_surface(
    selection: Mapping[str, Any],
    surface: Mapping[str, Any],
    policy: Mapping[str, Any],
    audit: Audit,
) -> tuple[dict[str, list[str]], dict[str, Decimal]]:
    surface_hash = _verify_versioned(
        surface,
        audit,
        object_type="ActiveResearchSurfaceVersion",
    )
    policy_hash = _verify_versioned(
        policy,
        audit,
        object_type="ResearchPortfolioPolicyVersion",
    )
    audit.require(
        policy.get("active_surface_ref") == surface_hash,
        "portfolio policy is not bound to the active surface",
    )
    specs = selection.get("specifications")
    audit.require(
        isinstance(specs, list) and len(specs) == EXPECTED_SPEC_COUNT,
        "selection manifest does not contain 233 specifications",
    )
    component_family: dict[str, str] = {}
    derived_counts: dict[str, int] = {}
    for raw in specs:
        audit.require(isinstance(raw, dict), "selection specification is not an object")
        _verify_content_hash(raw, audit, label="selection specification")
        family_id = str(raw.get("family_id") or "")
        components = raw.get("component_baseline_ids")
        audit.require(
            family_id and isinstance(components, list) and components,
            "selection specification lacks its family or component set",
        )
        audit.require(
            components == sorted(components) and len(components) == len(set(components)),
            "selection specification component set is not canonical",
        )
        for component in components:
            component_id = str(component)
            audit.require(
                component_id not in component_family,
                "selection manifest component partition overlaps",
            )
            component_family[component_id] = family_id
        derived_counts[family_id] = derived_counts.get(family_id, 0) + len(components)
    audit.require(
        len(component_family) == EXPECTED_COMPONENT_COUNT,
        "selection manifest does not partition 416 ACTIVE components",
    )
    audit.require(
        selection.get("family_counts") == derived_counts,
        "selection manifest family counts do not match the component partition",
    )
    _verify_content_hash(selection, audit, label="selection manifest")

    rows = surface.get("rows")
    audit.require(
        isinstance(rows, list) and len(rows) == EXPECTED_FAMILY_COUNT,
        "active research surface does not contain 13 families",
    )
    surface_components: dict[str, list[str]] = {}
    family_shares: dict[str, Decimal] = {}
    observed_components: set[str] = set()
    for raw in rows:
        audit.require(isinstance(raw, dict), "active surface row is not an object")
        family_id = str(raw.get("family_id") or "")
        components = raw.get("active_component_ids")
        audit.require(
            family_id not in surface_components and isinstance(components, list),
            "active surface family identity is invalid",
        )
        canonical_components = [str(item) for item in components]
        audit.require(
            canonical_components == sorted(canonical_components)
            and len(canonical_components) == len(set(canonical_components))
            and raw.get("active_component_count") == len(canonical_components),
            "active surface component inventory is not canonical",
        )
        audit.require(
            all(component_family.get(item) == family_id for item in canonical_components),
            "active surface component escaped its selection-manifest family",
        )
        audit.require(
            observed_components.isdisjoint(canonical_components),
            "active surface component partition overlaps",
        )
        observed_components.update(canonical_components)
        surface_components[family_id] = canonical_components
        share = Decimal(str(raw.get("research_resource_share")))
        audit.require(share > 0, "active surface family share is not positive")
        family_shares[family_id] = share
    audit.require(
        observed_components == set(component_family),
        "active surface is not the exact selection-manifest ACTIVE component universe",
    )
    exploitation = Decimal(str(policy.get("exploitation_share")))
    exploration = Decimal(str(policy.get("exploration_share")))
    audit.require(
        exploitation + exploration == Decimal("1"),
        "portfolio policy shares do not sum to one",
    )
    audit.require(
        sum(family_shares.values(), Decimal("0")) == exploitation,
        "active family shares do not equal the exploitation share",
    )
    audit.require(bool(surface_hash and policy_hash), "surface/policy identities are empty")
    return surface_components, family_shares


def _method_registry_hash(method_registry: Mapping[str, Any], audit: Audit) -> str:
    registrations = method_registry.get("registrations")
    audit.require(
        isinstance(registrations, dict) and bool(registrations),
        "method registry is empty",
    )
    canonical = {
        "registrations": {
            method_id: dict(registrations[method_id]) for method_id in sorted(registrations)
        }
    }
    return canonical_sha256(canonical)


def _verify_candidate_chain(
    *,
    question: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    candidate_snapshot: Mapping[str, Any],
    surface: Mapping[str, Any],
    selection: Mapping[str, Any],
    method_registry: Mapping[str, Any],
    source_graph: Mapping[str, Any],
    surface_components: Mapping[str, Sequence[str]],
    audit: Audit,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    surface_hash = str(surface.get("content_sha256") or "")
    selection_hash = str(selection.get("content_hash") or "")
    source_graph_hash = _verify_versioned(
        source_graph,
        audit,
        object_type="SourceDependencyGraphVersion",
    )
    method_hash = _method_registry_hash(method_registry, audit)
    question_hash = _verify_versioned(question, audit, object_type="ResearchQuestion")
    source_hash = _verify_versioned(
        source_snapshot,
        audit,
        object_type="ResearchCandidateSourceSnapshot",
    )
    candidate_hash = _verify_versioned(
        candidate_snapshot,
        audit,
        object_type="ResearchCandidateSnapshot",
    )
    expected_families = sorted(surface_components)
    audit.require(
        len(expected_families) == EXPECTED_FAMILY_COUNT,
        "candidate source foundation does not expose 13 families",
    )
    input_hashes = source_snapshot.get("input_hashes")
    audit.require(isinstance(input_hashes, dict), "candidate source input hashes are missing")
    expected_input_hashes = {
        "active_research_surface_sha256": surface_hash,
        "selection_manifest_sha256": selection_hash,
        "method_registry_sha256": method_hash,
        "source_dependency_graph_sha256": source_graph_hash,
    }
    audit.require(
        all(input_hashes.get(key) == value for key, value in expected_input_hashes.items()),
        "candidate source foundation hash binding drifted",
    )
    audit.require(
        question.get("input_hashes") == input_hashes
        and question.get("expected_family_ids") == expected_families
        and question.get("expected_candidate_count") == EXPECTED_FAMILY_COUNT,
        "research question does not bind the exact source universe",
    )
    audit.require(
        source_snapshot.get("research_question_ref") == question_hash
        and source_snapshot.get("candidate_generator_source_sha256")
        == question.get("candidate_generator_source_sha256"),
        "candidate source does not bind its research question/compiler",
    )
    coverage = source_snapshot.get("coverage")
    entries = source_snapshot.get("candidate_entries")
    audit.require(
        isinstance(coverage, dict)
        and coverage.get("expected_family_ids") == expected_families
        and coverage.get("observed_family_ids") == expected_families
        and coverage.get("expected_family_count") == EXPECTED_FAMILY_COUNT
        and coverage.get("observed_family_count") == EXPECTED_FAMILY_COUNT
        and coverage.get("complete") is True,
        "candidate source does not prove exact 13-family coverage",
    )
    audit.require(
        isinstance(entries, list)
        and len(entries) == EXPECTED_FAMILY_COUNT
        and source_snapshot.get("candidate_count") == len(entries),
        "candidate source inventory is incomplete",
    )
    graph_sources = {
        str(row.get("source_id")): str(row.get("origin_cluster_id"))
        for row in source_graph.get("sources") or []
        if isinstance(row, dict)
    }
    source_by_candidate: dict[str, dict[str, Any]] = {}
    source_work_keys: set[str] = set()
    source_lane_ids: set[str] = set()
    for family_id, raw in zip(expected_families, entries, strict=True):
        audit.require(isinstance(raw, dict), "candidate source entry is not an object")
        entry_core = dict(raw)
        entry_hash = str(entry_core.pop("entry_sha256", ""))
        audit.require(
            entry_hash == canonical_sha256(entry_core),
            "candidate source entry hash drifted",
        )
        selected = min(surface_components[family_id])
        candidate_id = f"f4-canary:{family_id}:{selected}"
        audit.require(
            raw.get("family_id") == family_id
            and raw.get("selected_component_id") == selected
            and raw.get("candidate_id") == candidate_id,
            "candidate source entry was not derived from the F3 family minimum",
        )
        source_ref = str(raw.get("source_ref") or "")
        audit.require(
            graph_sources.get(source_ref) == raw.get("source_origin_cluster_id"),
            "candidate source origin binding drifted",
        )
        work_item = raw.get("work_item")
        lanes = raw.get("lane_templates")
        audit.require(
            isinstance(work_item, dict) and isinstance(lanes, dict),
            "candidate source runtime materials are missing",
        )
        audit.require(
            raw.get("work_item_sha256") == canonical_sha256(work_item)
            and raw.get("lane_templates_sha256") == canonical_sha256(lanes),
            "candidate source work item or lane-template hash drifted",
        )
        audit.require(
            set(lanes) == {"PRODUCER", "CRITIQUE", "VERIFIER"},
            "candidate source lacks a complete three-stage lane set",
        )
        for stage, lane in lanes.items():
            audit.require(isinstance(lane, dict), "candidate lane template is invalid")
            lane_id = str(lane.get("lane_id") or "")
            audit.require(
                lane.get("write") is False
                and lane.get("allowed_tools") == ["read_file"]
                and lane_id
                and lane_id not in source_lane_ids,
                f"candidate {stage} lane is not unique and read-only",
            )
            source_lane_ids.add(lane_id)
        work_key = str(raw.get("work_key") or "")
        audit.require(
            len(work_key) == 64 and work_key not in source_work_keys,
            "candidate source work identity is invalid or duplicated",
        )
        source_work_keys.add(work_key)
        audit.require(
            work_item.get("kind") == "F4_CANARY_ACTIVE_FAMILY"
            and work_item.get("physical_role") == "ACTIVE_SETTLEMENT"
            and work_item.get("active_settlement_refs") == [selected]
            and work_item.get("selection_manifest_hash") == selection_hash
            and work_item.get("source_ref") == source_ref
            and work_item.get("source_dependency_refs") == []
            and work_item.get("upstream_work_keys") == []
            and work_item.get("write_boundary") == "READ_ONLY_WORKER"
            and set(work_item.get("authority_scope") or [])
            == {"read:bound-evidence", "read:bound-sources"},
            "candidate source work item escaped its exact read-only binding",
        )
        audit.require(
            work_item.get("input_snapshot_hashes")
            == sorted(str(value) for value in input_hashes.values()),
            "candidate work item input-snapshot set drifted",
        )
        source_by_candidate[candidate_id] = dict(raw)

    rows = candidate_snapshot.get("candidate_rows")
    audit.require(
        isinstance(rows, list)
        and len(rows) == EXPECTED_FAMILY_COUNT
        and candidate_snapshot.get("candidate_count") == len(rows),
        "compiled candidate snapshot inventory is incomplete",
    )
    audit.require(
        candidate_snapshot.get("candidate_source_snapshot_ref") == source_hash
        and candidate_snapshot.get("research_question_ref") == question_hash
        and candidate_snapshot.get("active_surface_ref") == surface_hash
        and candidate_snapshot.get("selection_manifest_ref") == selection_hash
        and candidate_snapshot.get("method_registry_sha256") == method_hash
        and candidate_snapshot.get("source_dependency_graph_ref") == source_graph_hash,
        "compiled candidate snapshot foundation binding drifted",
    )
    expected_ids = list(source_by_candidate)
    candidate_coverage = candidate_snapshot.get("coverage")
    audit.require(
        isinstance(candidate_coverage, dict)
        and candidate_coverage.get("expected_source_ids") == expected_ids
        and candidate_coverage.get("compiled_source_ids") == expected_ids
        and candidate_coverage.get("omitted_source_ids") == []
        and candidate_coverage.get("exact") is True,
        "compiled candidate snapshot does not cover its exact source universe",
    )
    rebuilt_rows: list[dict[str, Any]] = []
    for raw in rows:
        audit.require(isinstance(raw, dict), "compiled candidate row is not an object")
        candidate_id = str(raw.get("candidate_id") or "")
        source = source_by_candidate.get(candidate_id)
        audit.require(source is not None, "compiled candidate has no source record")
        runtime_entry = {
            "work_item": source["work_item"],
            "lane_templates": source["lane_templates"],
            "work_key": source["work_key"],
            "portfolio_lane": "EXPLOITATION",
        }
        expected = {
            "candidate_id": candidate_id,
            "source_record_sha256": source["entry_sha256"],
            "entry": runtime_entry,
            "entry_sha256": canonical_sha256(runtime_entry),
            "work_key": source["work_key"],
            "family_id": source["family_id"],
            "portfolio_lane": "EXPLOITATION",
            "active_settlement_refs": [source["selected_component_id"]],
        }
        audit.require(raw == expected, "compiled candidate row differs from its source")
        rebuilt_rows.append(expected)
    audit.require(
        candidate_snapshot.get("candidate_universe_sha256") == canonical_sha256(rebuilt_rows),
        "candidate-universe hash drifted",
    )
    audit.require(bool(candidate_hash), "candidate snapshot identity is empty")
    return rebuilt_rows, source_by_candidate


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _expected_allocation_order(
    rows: Sequence[Mapping[str, Any]],
    family_shares: Mapping[str, Decimal],
) -> list[tuple[Fraction, str, Mapping[str, Any]]]:
    by_bucket: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        bucket = f"{row['portfolio_lane']}:{row['family_id']}"
        by_bucket.setdefault(bucket, []).append(row)
    scheduled: list[tuple[Fraction, str, Mapping[str, Any]]] = []
    for bucket, candidates in sorted(by_bucket.items()):
        family_id = str(candidates[0]["family_id"])
        weight = Fraction(family_shares[family_id])
        for ordinal, candidate in enumerate(
            sorted(candidates, key=lambda item: (item["candidate_id"], item["work_key"])),
            start=1,
        ):
            scheduled.append((Fraction(ordinal, 1) / weight, bucket, candidate))
    scheduled.sort(
        key=lambda item: (item[0], item[1], item[2]["candidate_id"], item[2]["work_key"])
    )
    return scheduled


def _verify_allocation_and_projection(
    *,
    allocation: Mapping[str, Any],
    projection: Mapping[str, Any],
    candidate_snapshot: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]],
    surface: Mapping[str, Any],
    policy: Mapping[str, Any],
    source_graph: Mapping[str, Any],
    family_shares: Mapping[str, Decimal],
    audit: Audit,
) -> list[str]:
    allocation_hash = _verify_versioned(
        allocation,
        audit,
        object_type="ResearchPortfolioAllocation",
    )
    projection_hash = _verify_versioned(
        projection,
        audit,
        object_type="AllocatedReadyFrontierProjection",
    )
    audit.require(
        allocation.get("candidate_snapshot_ref") == candidate_snapshot.get("content_sha256")
        and allocation.get("candidate_universe_sha256")
        == candidate_snapshot.get("candidate_universe_sha256")
        and allocation.get("active_surface_ref") == surface.get("content_sha256")
        and allocation.get("policy_ref") == policy.get("content_sha256")
        and allocation.get("source_dependency_graph_ref") == source_graph.get("content_sha256"),
        "portfolio allocation foundation binding drifted",
    )
    scheduled = _expected_allocation_order(candidate_rows, family_shares)
    raw_allocations = allocation.get("allocations")
    audit.require(
        isinstance(raw_allocations, list)
        and len(raw_allocations) == EXPECTED_FAMILY_COUNT
        and allocation.get("candidate_count") == len(raw_allocations),
        "portfolio allocation inventory is incomplete",
    )
    expected_keys: list[str] = []
    expected_entry_hashes: list[str] = []
    expected_entries: list[Mapping[str, Any]] = []
    expected_ready: list[dict[str, Any]] = []
    for rank, ((virtual_finish, bucket, candidate), raw) in enumerate(
        zip(scheduled, raw_allocations, strict=True),
        start=1,
    ):
        audit.require(isinstance(raw, dict), "portfolio allocation row is invalid")
        weight = Fraction(family_shares[str(candidate["family_id"])])
        expected = {
            "rank": rank,
            "candidate_id": candidate["candidate_id"],
            "work_key": candidate["work_key"],
            "entry_sha256": candidate["entry_sha256"],
            "portfolio_lane": candidate["portfolio_lane"],
            "bucket_id": bucket,
            "family_id": candidate["family_id"],
            "active_settlement_refs": candidate["active_settlement_refs"],
            "bucket_weight_fraction": _fraction_text(weight),
            "virtual_finish_fraction": _fraction_text(virtual_finish),
        }
        audit.require(raw == expected, "portfolio allocation rank or weight drifted")
        expected_keys.append(str(candidate["work_key"]))
        expected_entry_hashes.append(str(candidate["entry_sha256"]))
        expected_entries.append(candidate["entry"])
        expected_ready.append(
            {
                "rank": rank,
                "candidate_id": candidate["candidate_id"],
                "work_key": candidate["work_key"],
                "item": candidate["entry"]["work_item"],
                "entry_sha256": candidate["entry_sha256"],
            }
        )
    audit.require(
        allocation.get("ready_work_keys") == expected_keys
        and allocation.get("ordered_entry_sha256s") == expected_entry_hashes
        and allocation.get("ready_frontier_sha256") == canonical_sha256(expected_entries),
        "portfolio allocation ordered frontier identity drifted",
    )
    audit.require(
        projection.get("allocation_ref") == allocation_hash
        and projection.get("candidate_snapshot_ref") == candidate_snapshot.get("content_sha256")
        and projection.get("closed_work_keys") == []
        and projection.get("in_flight_work_keys") == []
        and projection.get("deferred") == []
        and projection.get("duplicates") == [],
        "positive ready projection is not an empty-state allocation filter",
    )
    audit.require(
        projection.get("execution_state_sha256")
        == canonical_sha256({"closed_work_keys": [], "in_flight_work_keys": []})
        and projection.get("ready") == expected_ready
        and projection.get("ready_work_keys") == expected_keys
        and projection.get("ready_frontier_sha256") == canonical_sha256(expected_ready)
        and projection.get("order_policy") == "FILTER_FROZEN_ALLOCATION_RANK_WITHOUT_REORDER",
        "ready projection did not preserve the frozen allocation order",
    )
    audit.require(bool(projection_hash), "ready projection identity is empty")
    return expected_keys


def _verify_capacity(
    capacity: Mapping[str, Any],
    observation: Mapping[str, Any],
    observation_path: Path,
    audit: Audit,
) -> int:
    core = dict(capacity)
    recorded = str(core.pop("content_sha256", ""))
    core.pop("observation_ref", None)
    core.pop("observation_sha256", None)
    audit.require(
        len(recorded) == 64 and canonical_sha256(core) == recorded,
        "dynamic capacity decision content identity drifted",
    )
    observed = capacity.get("observation")
    audit.require(isinstance(observed, dict), "dynamic capacity observation is missing")
    expected_observation = {
        **dict(observation),
        "ready_count": EXPECTED_FAMILY_COUNT,
        "queue_depth": max(
            int(observation.get("queue_depth") or 0),
            EXPECTED_FAMILY_COUNT,
        ),
        "previous_width": 1,
        "succeeded": 1,
        "failed": 0,
        "partial": False,
    }
    audit.require(
        observed == expected_observation
        and _same_path(capacity.get("observation_ref"), observation_path)
        and capacity.get("observation_sha256") == file_sha256(observation_path),
        "dynamic capacity decision observation binding drifted",
    )
    width = int(capacity.get("dispatch_width") or 0)
    audit.require(width > 0, "strict reconcile selected no dispatch capacity")
    return width


def _verify_strict_decision_and_payload(
    *,
    pack: Path,
    frontier_path: Path,
    frontier: Mapping[str, Any],
    inputs: Mapping[str, Mapping[str, Any]],
    projection: Mapping[str, Any],
    expected_keys: Sequence[str],
    source_by_candidate: Mapping[str, Mapping[str, Any]],
    audit: Audit,
) -> tuple[dict[str, Any], dict[str, Any], Path, list[str]]:
    decision_path = pack / "strict_reconcile_decision.json"
    decision = _load_object(decision_path)
    audit.require(
        decision.get("action") == "DISPATCH_EXTERNAL"
        and decision.get("reason") == "three_stage_pipeline_producer"
        and _same_path(decision.get("frontier_ref"), frontier_path)
        and decision.get("frontier_sha256") == file_sha256(frontier_path),
        "strict reconcile decision identity/action drifted",
    )
    audit.require(
        decision.get("dedup") == projection,
        "strict reconcile decision did not persist the verified projection",
    )
    capacity = decision.get("capacity_decision")
    audit.require(isinstance(capacity, dict), "strict reconcile capacity is missing")
    observation_path = pack / "inputs" / "capacity_observation.json"
    width = _verify_capacity(
        capacity,
        inputs["capacity_observation"],
        observation_path,
        audit,
    )
    selected = list(expected_keys[:width])
    wave = decision.get("wave")
    audit.require(isinstance(wave, dict), "strict reconcile wave is missing")
    audit.require(
        wave.get("stage") == "PRODUCER"
        and wave.get("work_keys") == selected
        and wave.get("capacity_decision") == capacity,
        "strict reconcile wave is not the allocation prefix",
    )
    payload_path = _inside(Path(str(wave.get("payload_ref") or "")), pack, label="payload")
    audit.require(payload_path.is_file(), "strict reconcile payload is missing")
    audit.require(
        wave.get("payload_sha256") == file_sha256(payload_path),
        "strict reconcile payload byte hash drifted",
    )
    payload = _load_object(payload_path)
    audit.require(
        payload.get("canonical_work_keys") == selected
        and payload.get("dynamic_capacity_decision") == capacity
        and payload.get("research_stage") == "PRODUCER"
        and _same_path(payload.get("frontier_ref"), frontier_path)
        and payload.get("frontier_sha256") == file_sha256(frontier_path),
        "strict payload does not preserve decision identity and rank prefix",
    )
    surface_binding = payload.get("research_surface_binding")
    audit.require(isinstance(surface_binding, dict), "strict surface binding is missing")
    expected_binding_content = {
        "active_research_surface": "active_research_surface",
        "research_portfolio_policy": "research_portfolio_policy",
        "research_question": "research_question",
        "research_candidate_source_snapshot": "research_candidate_source_snapshot",
        "research_candidate_snapshot": "research_candidate_snapshot",
        "research_portfolio_allocation": "research_portfolio_allocation",
    }
    for prefix, input_name in expected_binding_content.items():
        expected_path = pack / "inputs" / BOUND_INPUTS[input_name]
        audit.require(
            _same_path(surface_binding.get(f"{prefix}_ref"), expected_path)
            and surface_binding.get(f"{prefix}_sha256") == file_sha256(expected_path)
            and surface_binding.get(f"{prefix}_content_sha256")
            == inputs[input_name].get("content_sha256"),
            f"strict payload {prefix} binding drifted",
        )
    audit.require(
        surface_binding.get("frontier_binding_mode") == "STRICT_F3_SURFACE_SOURCE_BOUND"
        and surface_binding.get("ready_frontier_sha256")
        == inputs["research_portfolio_allocation"].get("ready_frontier_sha256"),
        "strict payload does not carry the frozen allocation binding",
    )
    source_by_work_key = {str(raw["work_key"]): raw for raw in source_by_candidate.values()}
    lanes = payload.get("grok_ready_frontier")
    lane_bindings = payload.get("lane_bindings")
    audit.require(
        isinstance(lanes, list)
        and len(lanes) == width
        and isinstance(lane_bindings, dict)
        and len(lane_bindings) == width,
        "strict payload lane cardinality differs from selected capacity",
    )
    observed_lane_ids: list[str] = []
    for work_key, lane in zip(selected, lanes, strict=True):
        audit.require(isinstance(lane, dict), "strict payload lane is invalid")
        source = source_by_work_key.get(work_key)
        audit.require(source is not None, "strict payload lane lacks a candidate source")
        template = source["lane_templates"]["PRODUCER"]
        lane_id = str(lane.get("lane_id") or "")
        observed_lane_ids.append(lane_id)
        audit.require(
            lane_id == template.get("lane_id")
            and lane.get("write") is False
            and lane.get("allowed_tools") == ["read_file"]
            and lane.get("contract_id") == "xinao.foundation.f4.readonly_lane.v1"
            and lane.get("permission_mode") == "approve-reads"
            and lane.get("model") == "grok-4.5",
            "strict payload lane is not the selected read-only producer",
        )
        prompt = str(lane.get("prompt") or "")
        audit.require(
            lane.get("prompt_sha256") == hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "strict payload prompt hash drifted",
        )
        method_input = lane.get("method_input")
        audit.require(
            isinstance(method_input, dict)
            and method_input.get("work_key") == work_key
            and method_input.get("stage") == "PRODUCER"
            and method_input.get("actor_id") == lane_id
            and lane.get("method_input_sha256") == canonical_sha256(method_input),
            "strict payload method input is not bound to lane/work/stage",
        )
        binding = lane_bindings.get(lane_id)
        audit.require(
            isinstance(binding, dict)
            and binding.get("work_key") == work_key
            and binding.get("stage") == "PRODUCER"
            and binding.get("actor_id") == lane_id
            and binding.get("write") is False
            and binding.get("allowed_tools") == ["read_file"]
            and binding.get("method_input") == method_input
            and binding.get("method_input_sha256") == lane.get("method_input_sha256"),
            "strict payload lane binding drifted",
        )
    audit.require(
        wave.get("lane_ids") == observed_lane_ids
        and set(wave.get("lane_bindings") or {}) == set(observed_lane_ids),
        "strict decision lane identity differs from its payload",
    )
    audit.require(
        "ready_frontier" not in frontier,
        "strict positive frontier contains caller-provided ready work",
    )
    return decision, payload, payload_path, selected


def _rehash_versioned(value: dict[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key not in {"version_id", "content_sha256"}}
    digest = canonical_sha256(core)
    value["content_sha256"] = digest
    value["version_id"] = f"{value['object_type']}@{digest[:16]}"
    return value


def _expect_rejected(
    case_id: str,
    call: Callable[[], Any],
    audit: Audit,
) -> dict[str, str]:
    try:
        call()
    except (TypeError, ValueError, KeyError) as exc:
        audit.require(bool(str(exc)), f"{case_id} rejection has no diagnostic")
        return {"case_id": case_id, "exception": type(exc).__name__, "error": str(exc)}
    raise VerificationError(f"negative control was accepted: {case_id}")


def _exercise_current_source(
    *,
    pack: Path,
    frontier_path: Path,
    frontier: Mapping[str, Any],
    inputs: Mapping[str, Mapping[str, Any]],
    decision: Mapping[str, Any],
    report: Mapping[str, Any],
    audit: Audit,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    from services.agent_runtime.foundation_continuous_workflow_v2 import (
        reconcile_foundation_frontier_v2,
    )
    from xinao.foundation.research_candidate_source import (
        compile_f4_canary_candidate_snapshot,
        compile_f4_canary_candidate_source,
    )
    from xinao.foundation.research_factory import (
        compile_research_portfolio_allocation,
        project_allocated_ready_frontier,
    )

    recorded_source_hashes = report.get("source_code_sha256")
    audit.require(isinstance(recorded_source_hashes, dict), "report source hashes are missing")
    current_source_hashes = {
        "candidate_source": canonical_sha256(inspect.getsource(compile_f4_canary_candidate_source)),
        "candidate_snapshot": canonical_sha256(
            inspect.getsource(compile_f4_canary_candidate_snapshot)
        ),
        "allocation": canonical_sha256(inspect.getsource(compile_research_portfolio_allocation)),
        "projection": canonical_sha256(inspect.getsource(project_allocated_ready_frontier)),
        "reconcile": canonical_sha256(inspect.getsource(reconcile_foundation_frontier_v2)),
    }
    audit.require(
        recorded_source_hashes == current_source_hashes,
        "retained pack is not current-source evidence",
    )
    signature_parameters = set(inspect.signature(compile_f4_canary_candidate_source).parameters)
    audit.require(
        signature_parameters.isdisjoint({"candidate_specs", "candidate_entries", "ready_frontier"}),
        "candidate source API accepts a caller-provided candidate universe",
    )

    files_before = _snapshot_files(pack)
    payload = _load_object(Path(str(decision["wave"]["payload_ref"])))
    replay = reconcile_foundation_frontier_v2(
        {
            "runtime_root": str(pack),
            "operation_id": payload["parent_operation_id"],
            "frontier_ref": str(frontier_path),
            "frontier_sha256": file_sha256(frontier_path),
            "previous_width": 1,
            "succeeded": 1,
            "failed": 0,
        }
    )
    audit.require(replay == decision, "current-source strict reconcile replay drifted")

    question = inputs["research_question"]
    source_snapshot = inputs["research_candidate_source_snapshot"]
    candidate_snapshot = inputs["research_candidate_snapshot"]
    allocation = inputs["research_portfolio_allocation"]
    method_id = str(question.get("method_id") or "")
    common = {
        "research_question": question,
        "active_research_surface": inputs["active_research_surface"],
        "selection_manifest": inputs["selection_manifest"],
        "method_registry": inputs["method_registry"],
        "method_id": method_id,
        "source_dependency_graph": inputs["source_dependency_graph"],
    }
    shortened = copy.deepcopy(source_snapshot)
    shortened["candidate_entries"] = shortened["candidate_entries"][:-1]
    shortened["candidate_count"] = len(shortened["candidate_entries"])
    shortened["coverage"] = {
        **shortened["coverage"],
        "observed_family_count": len(shortened["candidate_entries"]),
        "observed_family_ids": shortened["coverage"]["observed_family_ids"][:-1],
        "complete": False,
    }
    _rehash_versioned(shortened)
    reordered_source = copy.deepcopy(source_snapshot)
    reordered_source["candidate_entries"][0], reordered_source["candidate_entries"][1] = (
        reordered_source["candidate_entries"][1],
        reordered_source["candidate_entries"][0],
    )
    _rehash_versioned(reordered_source)
    reordered_allocation = copy.deepcopy(allocation)
    reordered_allocation["allocations"][0], reordered_allocation["allocations"][1] = (
        reordered_allocation["allocations"][1],
        reordered_allocation["allocations"][0],
    )
    _rehash_versioned(reordered_allocation)

    def mutated_worker_source(case_id: str) -> dict[str, Any]:
        mutated = copy.deepcopy(source_snapshot)
        entry = mutated["candidate_entries"][0]
        if case_id == "WORKER_ASSUMES_CODEX_SINGLE_WRITER":
            entry["work_item"]["write_boundary"] = "CODEX_SINGLE_WRITER"
            entry["work_item_sha256"] = canonical_sha256(entry["work_item"])
        elif case_id == "WORKER_LANE_REQUESTS_WRITE":
            entry["lane_templates"]["PRODUCER"]["write"] = True
            entry["lane_templates_sha256"] = canonical_sha256(entry["lane_templates"])
        elif case_id == "WORKER_LANE_REQUESTS_WRITE_TOOL":
            entry["lane_templates"]["PRODUCER"]["allowed_tools"] = [
                "read_file",
                "write_file",
            ]
            entry["lane_templates_sha256"] = canonical_sha256(entry["lane_templates"])
        else:  # pragma: no cover - bounded internal caller
            raise AssertionError(case_id)
        entry_core = dict(entry)
        entry_core.pop("entry_sha256", None)
        entry["entry_sha256"] = canonical_sha256(entry_core)
        return _rehash_versioned(mutated)

    worker_write_boundary_negatives = [
        _expect_rejected(
            case_id,
            lambda case_id=case_id: compile_f4_canary_candidate_snapshot(
                candidate_source_snapshot=mutated_worker_source(case_id),
                **common,
            ),
            audit,
        )
        for case_id in sorted(EXPECTED_WRITE_BOUNDARY_CASES)
    ]
    raw_frontier_path = pack / "negative" / "raw_ready_frontier.json"
    raw_frontier = _load_object(raw_frontier_path)
    audit.require(
        raw_frontier.get("schema_version") == "xinao.foundation_continuous_frontier.v3"
        and "ready_frontier" in raw_frontier,
        "retained caller-ready negative frontier is not the requested mutation",
    )
    negatives = [
        _expect_rejected(
            "SHORTENED_REHASHED_SOURCE",
            lambda: compile_f4_canary_candidate_snapshot(
                candidate_source_snapshot=shortened,
                **common,
            ),
            audit,
        ),
        _expect_rejected(
            "REORDERED_REHASHED_SOURCE",
            lambda: compile_f4_canary_candidate_snapshot(
                candidate_source_snapshot=reordered_source,
                **common,
            ),
            audit,
        ),
        _expect_rejected(
            "REORDERED_REHASHED_ALLOCATION",
            lambda: project_allocated_ready_frontier(
                reordered_allocation,
                candidate_snapshot=candidate_snapshot,
            ),
            audit,
        ),
        _expect_rejected(
            "CALLER_RAW_READY_FRONTIER",
            lambda: reconcile_foundation_frontier_v2(
                {
                    "runtime_root": str(pack),
                    "operation_id": "f4-independent-negative-caller-ready",
                    "frontier_ref": str(raw_frontier_path),
                    "frontier_sha256": file_sha256(raw_frontier_path),
                }
            ),
            audit,
        ),
    ]
    observed = {item["case_id"]: item["error"] for item in negatives}
    audit.require(
        set(observed) == EXPECTED_NEGATIVE_CASES,
        "independent negative-control set is incomplete",
    )
    recorded_cases = {
        str(item.get("case_id"))
        for item in report.get("negative_controls") or []
        if isinstance(item, dict)
    }
    audit.require(
        recorded_cases == EXPECTED_NEGATIVE_CASES,
        "canary report did not retain the same negative-control identities",
    )
    write_boundary_observed = {
        item["case_id"]: item["error"] for item in worker_write_boundary_negatives
    }
    audit.require(
        set(write_boundary_observed) == EXPECTED_WRITE_BOUNDARY_CASES,
        "worker write-boundary negative-control set is incomplete",
    )
    audit.require(
        _snapshot_files(pack) == files_before,
        "current-source replay or negative controls mutated the source pack",
    )
    return current_source_hashes, observed, write_boundary_observed


def verify_portfolio_pack(pack: Path) -> dict[str, Any]:
    pack = input_path(pack, expect="directory")
    audit = Audit()
    audit.require(pack.is_dir(), f"portfolio canary pack is missing: {pack}")
    manifest, manifest_path, manifest_entries = _verify_manifest(pack, audit)
    report_path = pack / "portfolio_source_canary_report.json"
    report = _load_object(report_path)
    report_core = dict(report)
    report_content = str(report_core.pop("content_sha256", ""))
    audit.require(
        report_content == canonical_sha256(report_core),
        "portfolio canary report content identity drifted",
    )
    audit.require(
        report.get("schema_version") == "xinao.f4_portfolio_source_canary_report.v1"
        and report.get("assertion_id") == "research_portfolio_ready_frontier_verified"
        and report.get("status") == "VERIFIED",
        "portfolio canary report identity/status drifted",
    )
    frontier_path = pack / "inputs" / "frontier.json"
    frontier = _load_object(frontier_path)
    audit.require(
        frontier.get("schema_version") == "xinao.foundation_continuous_frontier.v3"
        and frontier.get("foundation_closed") is True,
        "portfolio canary is not a strict F3-closed frontier",
    )
    inputs, input_paths = _load_inputs(
        pack,
        frontier,
        manifest_entries,
        audit,
    )
    projection_path = pack / "inputs" / "allocated_ready_frontier_projection.json"
    projection = _load_object(projection_path)

    surface_components, family_shares = _verify_selection_and_surface(
        inputs["selection_manifest"],
        inputs["active_research_surface"],
        inputs["research_portfolio_policy"],
        audit,
    )
    candidate_rows, source_by_candidate = _verify_candidate_chain(
        question=inputs["research_question"],
        source_snapshot=inputs["research_candidate_source_snapshot"],
        candidate_snapshot=inputs["research_candidate_snapshot"],
        surface=inputs["active_research_surface"],
        selection=inputs["selection_manifest"],
        method_registry=inputs["method_registry"],
        source_graph=inputs["source_dependency_graph"],
        surface_components=surface_components,
        audit=audit,
    )
    expected_keys = _verify_allocation_and_projection(
        allocation=inputs["research_portfolio_allocation"],
        projection=projection,
        candidate_snapshot=inputs["research_candidate_snapshot"],
        candidate_rows=candidate_rows,
        surface=inputs["active_research_surface"],
        policy=inputs["research_portfolio_policy"],
        source_graph=inputs["source_dependency_graph"],
        family_shares=family_shares,
        audit=audit,
    )
    decision, payload, payload_path, selected = _verify_strict_decision_and_payload(
        pack=pack,
        frontier_path=frontier_path,
        frontier=frontier,
        inputs=inputs,
        projection=projection,
        expected_keys=expected_keys,
        source_by_candidate=source_by_candidate,
        audit=audit,
    )
    current_source_hashes, negative_errors, write_boundary_errors = _exercise_current_source(
        pack=pack,
        frontier_path=frontier_path,
        frontier=frontier,
        inputs=inputs,
        decision=decision,
        report=report,
        audit=audit,
    )

    assertions: dict[str, dict[str, Any]] = {}
    assertions["manifest_exact_byte_set"] = _assertion(
        "manifest_exact_byte_set",
        [manifest_path],
        {
            "entry_count": int(manifest["entry_count"]),
            "manifest_content_sha256": manifest["content_sha256"],
        },
    )
    assertions["f3_selection_surface_exact_13_family_coverage"] = _assertion(
        "f3_selection_surface_exact_13_family_coverage",
        [
            pack / "inputs" / "selection_manifest.json",
            pack / "inputs" / "active_research_surface.json",
            pack / "inputs" / "research_portfolio_policy.json",
        ],
        {
            "active_component_count": sum(map(len, surface_components.values())),
            "family_count": len(surface_components),
            "family_ids": sorted(surface_components),
            "selection_spec_count": len(inputs["selection_manifest"]["specifications"]),
        },
    )
    assertions["generated_source_to_candidate_snapshot_exact"] = _assertion(
        "generated_source_to_candidate_snapshot_exact",
        [
            pack / "inputs" / "research_question.json",
            pack / "inputs" / "research_candidate_source_snapshot.json",
            pack / "inputs" / "research_candidate_snapshot.json",
        ],
        {
            "candidate_count": len(candidate_rows),
            "candidate_source_sha256": inputs["research_candidate_source_snapshot"][
                "content_sha256"
            ],
            "candidate_snapshot_sha256": inputs["research_candidate_snapshot"]["content_sha256"],
        },
    )
    assertions["weighted_allocation_rank_independently_recomputed"] = _assertion(
        "weighted_allocation_rank_independently_recomputed",
        [
            pack / "inputs" / "research_portfolio_allocation.json",
            pack / "inputs" / "allocated_ready_frontier_projection.json",
        ],
        {
            "ranked_work_keys": expected_keys,
            "ready_count": len(expected_keys),
        },
    )
    assertions["strict_decision_payload_uses_allocation_prefix"] = _assertion(
        "strict_decision_payload_uses_allocation_prefix",
        [pack / "strict_reconcile_decision.json", payload_path],
        {
            "dispatch_width": len(selected),
            "payload_sha256": file_sha256(payload_path),
            "selected_work_keys": selected,
        },
    )
    assertions["all_source_and_actual_lanes_read_only"] = _assertion(
        "all_source_and_actual_lanes_read_only",
        [
            pack / "inputs" / "research_candidate_source_snapshot.json",
            payload_path,
        ],
        {
            "actual_lane_count": len(payload["grok_ready_frontier"]),
            "allowed_tools": ["read_file"],
            "caller_ready_frontier_absent": True,
            "write": False,
        },
    )
    assertions["current_source_strict_replay_exact"] = _assertion(
        "current_source_strict_replay_exact",
        [pack / "strict_reconcile_decision.json", report_path],
        {"source_code_sha256": current_source_hashes},
    )
    assertions["four_negative_controls_actually_rejected"] = _assertion(
        "four_negative_controls_actually_rejected",
        [
            pack / "negative" / "raw_ready_frontier.json",
            pack / "inputs" / "research_candidate_source_snapshot.json",
            pack / "inputs" / "research_portfolio_allocation.json",
        ],
        {"case_count": len(negative_errors), "rejections": negative_errors},
    )
    assertions["three_worker_write_boundary_mutations_rejected"] = _assertion(
        "three_worker_write_boundary_mutations_rejected",
        [
            pack / "inputs" / "research_candidate_source_snapshot.json",
            payload_path,
        ],
        {
            "case_count": len(write_boundary_errors),
            "rejections": write_boundary_errors,
            "scope": "F4_MODEL_WORKERS_REMAIN_READ_ONLY",
        },
    )
    core = {
        "schema_version": SCHEMA_VERSION,
        "status": "VERIFIED",
        "verification_mode": "READ_ONLY_INDEPENDENT_RECOMPUTE_PLUS_CURRENT_SOURCE_REPLAY",
        "source_pack": retained_path(pack),
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_report_sha256": file_sha256(report_path),
        "verifier_source_sha256": file_sha256(Path(__file__)),
        "primitive_check_count": audit.check_count,
        "assertion_count": len(assertions),
        "assertions": assertions,
        "unclosed_items": [],
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def write_verification(report: Mapping[str, Any], output_dir: Path) -> Path:
    digest = str(report.get("content_sha256") or "")
    if len(digest) != 64:
        raise VerificationError("independent report is not content addressed")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{digest}.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise VerificationError("independent report content-address collision")
        return path
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir or args.pack.parent / (
        f"{args.pack.name}-independent-verification"
    )
    try:
        report = verify_portfolio_pack(args.pack)
        output = write_verification(report, output_dir)
    except VerificationError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "content_sha256": report["content_sha256"],
                "assertion_count": report["assertion_count"],
                "primitive_check_count": report["primitive_check_count"],
                "output": str(output),
                "unclosed_items": report["unclosed_items"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
