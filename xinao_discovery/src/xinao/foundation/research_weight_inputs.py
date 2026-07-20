"""Bind the current 60-row qualitative draft to the deterministic F3 compiler.

The draft is evidence input, not a measured attention dataset.  This adapter
only normalises its provenance and service-graph vocabulary; the compiler in
``research_weight`` remains the single place that allocates research-resource
shares.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from xinao.canonical import canonical_sha256
from xinao.foundation.f2_compile import (
    SettlementCostCompileReport,
    active_registry_projection_hash,
    compile_f2_artifacts,
)
from xinao.foundation.f4_snapshot_runtime import (
    load_object as load_snapshot_object,
)
from xinao.foundation.f4_snapshot_runtime import readable_path, retained_path
from xinao.foundation.research_weight import compile_research_weight_foundation
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)
from xinao.foundation.semantics_registry import (
    FoundationSemanticsRegistry,
    compile_default_semantics_registry,
)

DEFAULT_F3_EVIDENCE_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence\weight_prior_snapshot_v0"
)
DEFAULT_PRIOR_DRAFT_PATH = (
    DEFAULT_F3_EVIDENCE_ROOT / "contracts_draft" / "settlement_event_class_prior_projection_v0.json"
)
DEFAULT_SERVICE_GRAPH_PATH = (
    DEFAULT_F3_EVIDENCE_ROOT
    / "contracts_draft"
    / "SettlementEventAttentionPrior_service_graph_v0.json"
)
DEFAULT_EXTERNAL_SYNTHESIS_PATH = (
    DEFAULT_F3_EVIDENCE_ROOT
    / "raw_search_runs"
    / "20260714_121327"
    / "web_search"
    / "external_mature_funnel_layering_raw.json"
)

FORMAL_FAMILY_IDS = frozenset(
    {
        "linked-number",
        "linked-tail",
        "linked-zodiac",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "one-zodiac-tail",
        "other-explicit",
        "parlay",
        "regular-number",
        "regular-position-special",
        "six-zodiac",
        "special-number",
        "special-regular-hit",
    }
)


def _load_object(path: Path) -> dict[str, Any]:
    value = load_snapshot_object(path)
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _file_binding(path: Path) -> dict[str, Any]:
    resolved = readable_path(path, expect="file")
    raw = resolved.read_bytes()
    return {
        "path": retained_path(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _external_sources(value: dict[str, Any]) -> list[dict[str, str]]:
    urls = {
        str(url).strip()
        for finding in value.get("key_external_findings", [])
        if isinstance(finding, dict)
        for url in finding.get("urls", [])
        if isinstance(url, str) and url.strip()
    }
    sources: list[dict[str, str]] = []
    for url in sorted(urls):
        hostname = (urlparse(url).hostname or "unknown").casefold()
        sources.append(
            {
                "source_id": f"external-url:{hashlib.sha256(url.encode()).hexdigest()[:16]}",
                "origin_cluster_id": f"origin-domain:{hostname}",
            }
        )
    return sources


def _active_foundation_binding(
    registry: FoundationSemanticsRegistry,
    f2_report: SettlementCostCompileReport,
) -> dict[str, Any]:
    if not isinstance(registry, FoundationSemanticsRegistry):
        raise TypeError("semantics_registry must be FoundationSemanticsRegistry")
    if not isinstance(f2_report, SettlementCostCompileReport):
        raise TypeError("f2_report must be SettlementCostCompileReport")
    records = {record.baseline_id: record for record in registry.rule_semantic_map.records}
    costs = {binding.baseline_id: binding for binding in f2_report.cost_surface.bindings}
    if (
        set(records) != ACTIVE_SETTLEMENT_BASELINE_IDS
        or set(costs) != ACTIVE_SETTLEMENT_BASELINE_IDS
        or len(records) != EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT
    ):
        raise ValueError("F3 requires exact 416-row ACTIVE F1/F2 coverage")
    if set(records) & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
        raise ValueError("FROZEN_AGENT_ROUTE_QUOTE rows cannot enter F3")
    expected_projection = active_registry_projection_hash(registry)
    if (
        f2_report.source_active_projection_hash != expected_projection
        or f2_report.active_quote_version_count != 1
        or f2_report.active_quote_component_count != EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT
    ):
        raise ValueError("F3 requires one F2 ACTIVE_DEFAULT_QUOTE surface bound to F1")

    components: list[dict[str, str]] = []
    for baseline_id in sorted(records):
        record = records[baseline_id]
        cost = costs[baseline_id]
        if (
            record.physical_role != "ACTIVE_SETTLEMENT"
            or record.catalog.panel == "B"
            or cost.quote_role != "ACTIVE_DEFAULT_QUOTE"
            or not cost.included_in_active_cost_surface
            or cost.semantic_record_hash != record.content_hash
        ):
            raise ValueError(f"F3 ACTIVE binding drifted for {baseline_id}")
        components.append(
            {
                "baseline_id": baseline_id,
                "family_id": record.family_id,
                "physical_role": "ACTIVE_SETTLEMENT",
                "quote_role": "ACTIVE_DEFAULT_QUOTE",
                "semantic_record_hash": record.content_hash,
                "cost_binding_hash": canonical_sha256(cost.model_dump(mode="json")),
            }
        )
    if {item["family_id"] for item in components} != FORMAL_FAMILY_IDS:
        raise ValueError("F3 ACTIVE projection does not cover the 13 formal families")
    return {
        "physical_role": "ACTIVE_SETTLEMENT",
        "active_quote_role": "ACTIVE_DEFAULT_QUOTE",
        "active_quote_version_count": 1,
        "f1_active_physical_semantics_hash": registry.active_physical_semantics_hash,
        "f2_active_projection_hash": f2_report.source_active_projection_hash,
        "f2_cost_surface_hash": f2_report.cost_surface.content_hash,
        "components": components,
    }


def _content_graph(
    prior_rows: list[dict[str, Any]],
    service: dict[str, Any],
    active_components: list[dict[str, str]],
) -> dict[str, Any]:
    graph = service.get("attention_service_graph")
    if not isinstance(graph, dict):
        raise ValueError("service draft has no attention_service_graph")
    qualitative_node_ids = {
        str(row.get("event_class") or "").strip()
        for row in prior_rows
        if str(row.get("event_class") or "").strip()
    }
    raw_edges: list[tuple[str, str, str]] = []
    for raw in graph.get("tema_funnel_edges", []):
        if not isinstance(raw, dict):
            raise TypeError("tema_funnel_edges entries must be objects")
        source = str(raw.get("from") or "").strip()
        target = str(raw.get("to") or "").strip()
        relation = str(raw.get("relation") or "").strip().upper()
        if not source or not target or not relation:
            raise ValueError("service edge identity is incomplete")
        if source in qualitative_node_ids and target in qualitative_node_ids:
            raw_edges.append((source, target, relation))
    for raw in graph.get("migration_edge_priors", []):
        if not isinstance(raw, dict):
            raise TypeError("migration_edge_priors entries must be objects")
        source = str(raw.get("from") or "").strip()
        target = str(raw.get("to") or "").strip()
        if not source or not target:
            raise ValueError("migration edge identity is incomplete")
        if source in qualitative_node_ids and target in qualitative_node_ids:
            raw_edges.append((source, target, "QUALITATIVE_MIGRATION_PRIOR"))

    family_by_node = {
        str(row["event_class"]): str(row["family_id"])
        for row in prior_rows
        if row.get("event_class") and row.get("family_id")
    }
    nodes = []
    for node_id in sorted(qualitative_node_ids):
        node: dict[str, str] = {"node_id": node_id, "role": "QUALITATIVE_SERVICE_NODE"}
        if node_id in family_by_node:
            node["family_id"] = family_by_node[node_id]
        nodes.append(node)
    nodes.extend(
        {
            "node_id": f"active-settlement:{component['baseline_id']}",
            "family_id": component["family_id"],
            "role": "ACTIVE_SETTLEMENT_COMPONENT",
        }
        for component in active_components
    )
    return {
        "nodes": nodes,
        "edges": [
            {"from": source, "to": target, "relation": relation}
            for source, target, relation in sorted(set(raw_edges))
        ],
    }


def compile_research_weight_foundation_from_input_paths(
    *,
    prior_path: Path,
    service_graph_path: Path,
    external_synthesis_path: Path,
    exploration_share: str = "0.10",
    semantics_registry: FoundationSemanticsRegistry | None = None,
    f2_report: SettlementCostCompileReport | None = None,
) -> dict[str, Any]:
    """Compile F3 from three explicit, hermetic evidence paths."""

    prior = _load_object(prior_path)
    service = _load_object(service_graph_path)
    external = _load_object(external_synthesis_path)
    raw_rows = prior.get("event_class_table")
    if not isinstance(raw_rows, list) or len(raw_rows) != 60:
        raise ValueError("current qualitative prior must contain exactly 60 event classes")
    registry = semantics_registry or compile_default_semantics_registry()
    report = f2_report or compile_f2_artifacts(registry)
    active_foundation = _active_foundation_binding(registry, report)
    active_components = active_foundation["components"]
    active_family_ids = {component["family_id"] for component in active_components}

    active_prior_rows = [
        raw
        for raw in raw_rows
        if isinstance(raw, dict) and raw.get("family_id") in active_family_ids
    ]
    rows: list[dict[str, Any]] = []
    for raw in active_prior_rows:
        if not isinstance(raw, dict):
            raise TypeError("event_class_table rows must be objects")
        row = {
            "event_class_id": raw.get("event_class"),
            "family_id": raw.get("family_id"),
            "tier": raw.get("tier"),
            "scheduler_seed_coefficient": raw.get("prior_w"),
            "source_ids": ["local-prior-draft"],
        }
        rows.append(row)
    observed_formal = {str(row["family_id"]) for row in rows}
    if observed_formal != active_family_ids or observed_formal != FORMAL_FAMILY_IDS:
        raise ValueError("qualitative prior must cover exactly the 13 ACTIVE families")

    sources = [
        {
            "source_id": "local-prior-draft",
            "origin_cluster_id": "local-study:weight-prior-v0",
        },
        {
            "source_id": "local-service-graph",
            "origin_cluster_id": "local-study:weight-prior-v0",
        },
        {
            "source_id": "f1-active-settlement-semantics",
            "origin_cluster_id": "foundation:F1-active-settlement",
        },
        {
            "source_id": "f2-active-default-cost-surface",
            "origin_cluster_id": "foundation:F2-active-default-quote",
        },
        *_external_sources(external),
    ]
    source_graph = {
        "sources": sources,
        "edges": [
            {
                "from": "local-prior-draft",
                "to": "local-service-graph",
                "relation": "CO_DERIVED_PROJECT_MATERIAL",
            },
            {
                "from": "f1-active-settlement-semantics",
                "to": "f2-active-default-cost-surface",
                "relation": "DERIVES_ACTIVE_DEFAULT_COST_SURFACE",
            },
        ],
    }
    bundle = compile_research_weight_foundation(
        active_foundation_binding=active_foundation,
        source_dependency_graph=source_graph,
        content_service_graph=_content_graph(active_prior_rows, service, active_components),
        research_attention_prior={
            "prior_identity": "QUALITATIVE_SEED",
            "rows": rows,
        },
        research_portfolio_policy={
            "exploration_share": exploration_share,
            "update_signals": [
                "EXPECTED_INFORMATION_GAIN",
                "FALSIFICATION_VALUE",
                "FOUNDATION_GAP",
                "NOVELTY",
            ],
        },
    )
    input_bindings = {
        "prior_draft": _file_binding(prior_path),
        "service_graph": _file_binding(service_graph_path),
        "external_synthesis": _file_binding(external_synthesis_path),
    }
    return {
        **bundle,
        "input_bindings": input_bindings,
        "input_bundle_sha256": canonical_sha256(input_bindings),
        "input_identity": "QUALITATIVE_SEED",
        "measured_attention_claimed": False,
    }


def compile_current_research_weight_foundation(
    *,
    prior_path: Path = DEFAULT_PRIOR_DRAFT_PATH,
    service_graph_path: Path = DEFAULT_SERVICE_GRAPH_PATH,
    external_synthesis_path: Path = DEFAULT_EXTERNAL_SYNTHESIS_PATH,
    exploration_share: str = "0.10",
    semantics_registry: FoundationSemanticsRegistry | None = None,
    f2_report: SettlementCostCompileReport | None = None,
) -> dict[str, Any]:
    """Host convenience wrapper over the required-path hermetic compiler."""

    return compile_research_weight_foundation_from_input_paths(
        prior_path=prior_path,
        service_graph_path=service_graph_path,
        external_synthesis_path=external_synthesis_path,
        exploration_share=exploration_share,
        semantics_registry=semantics_registry,
        f2_report=f2_report,
    )


__all__ = [
    "DEFAULT_EXTERNAL_SYNTHESIS_PATH",
    "DEFAULT_PRIOR_DRAFT_PATH",
    "DEFAULT_SERVICE_GRAPH_PATH",
    "FORMAL_FAMILY_IDS",
    "compile_current_research_weight_foundation",
    "compile_research_weight_foundation_from_input_paths",
]
