"""Deterministic F3 research-resource seed compiler.

This module deliberately keeps qualitative attention, research scheduling, draw
probability, settlement truth, betting amounts, and bookmaker exposure as
separate axes.  Its output can only allocate research resources.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

SEMANTIC_ROLE = "RESEARCH_RESOURCE_SHARE"
PRIOR_IDENTITY = "QUALITATIVE_SEED"
SCHEMA_VERSION = "xinao.research-weight-foundation-object.v1"

SCHEDULER_SEED_COEFFICIENT_BY_TIER: dict[str, Decimal] = {
    "S": Decimal("1"),
    "A+": Decimal("0.72"),
    "A": Decimal("0.55"),
    "B+": Decimal("0.38"),
    "B": Decimal("0.25"),
    "C": Decimal("0.12"),
    "D": Decimal("0.05"),
    "E": Decimal("0.02"),
}

_SURFACE_BY_TIER = {
    "S": "ACTIVE",
    "A+": "ACTIVE",
    "A": "WATCH",
    "B+": "WATCH",
    "B": "TAIL",
    "C": "TAIL",
    "D": "DORMANT",
    "E": "DORMANT",
}

_DOES_NOT_MODIFY = [
    "BETTING_AMOUNT",
    "BOOKMAKER_EXPOSURE",
    "DRAW_PROBABILITY",
    "SETTLEMENT_TRUTH",
]


class ResearchWeightCompileError(ValueError):
    """Raised when an F3 seed input would cross its semantic boundary."""


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    raise TypeError(f"not canonical-JSON serializable: {type(value).__name__}")


def canonical_sha256(value: object) -> str:
    """Hash canonical JSON; callers sort set-like rows before invoking this."""

    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResearchWeightCompileError("value is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearchWeightCompileError(f"{name} must be a mapping")
    return value


def _rows(value: object, name: str) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ResearchWeightCompileError(f"{name} must be a sequence")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        result.append(_mapping(item, f"{name}[{index}]"))
    return result


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchWeightCompileError(f"{name} must be non-empty text")
    return value.strip()


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ResearchWeightCompileError(f"{name} must be a decimal value")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ResearchWeightCompileError(f"{name} must be a decimal value") from exc
    if not result.is_finite():
        raise ResearchWeightCompileError(f"{name} must be finite")
    return result


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def _sha256_text(value: object, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ResearchWeightCompileError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _normalize_active_foundation(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("physical_role") != "ACTIVE_SETTLEMENT":
        raise ResearchWeightCompileError(
            "active foundation physical_role must be ACTIVE_SETTLEMENT"
        )
    if raw.get("active_quote_role") != "ACTIVE_DEFAULT_QUOTE":
        raise ResearchWeightCompileError(
            "active foundation quote role must be ACTIVE_DEFAULT_QUOTE"
        )
    if raw.get("active_quote_version_count") != 1:
        raise ResearchWeightCompileError(
            "active foundation must bind exactly one ACTIVE_DEFAULT_QUOTE version"
        )

    components: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(_rows(raw.get("components"), "active_foundation.components")):
        baseline_id = _text(row.get("baseline_id"), f"components[{index}].baseline_id")
        if baseline_id in seen_ids:
            raise ResearchWeightCompileError(f"duplicate active baseline_id: {baseline_id}")
        seen_ids.add(baseline_id)
        if row.get("physical_role") != "ACTIVE_SETTLEMENT":
            raise ResearchWeightCompileError(
                f"{baseline_id} must have ACTIVE_SETTLEMENT physical_role"
            )
        if row.get("quote_role") != "ACTIVE_DEFAULT_QUOTE":
            raise ResearchWeightCompileError(
                f"{baseline_id} must use the ACTIVE_DEFAULT_QUOTE surface"
            )
        components.append(
            {
                "baseline_id": baseline_id,
                "family_id": _text(row.get("family_id"), f"{baseline_id}.family_id"),
                "physical_role": "ACTIVE_SETTLEMENT",
                "quote_role": "ACTIVE_DEFAULT_QUOTE",
                "semantic_record_hash": _sha256_text(
                    row.get("semantic_record_hash"), f"{baseline_id}.semantic_record_hash"
                ),
                "cost_binding_hash": _sha256_text(
                    row.get("cost_binding_hash"), f"{baseline_id}.cost_binding_hash"
                ),
            }
        )
    if not components:
        raise ResearchWeightCompileError("active foundation must contain components")
    components.sort(key=lambda item: item["baseline_id"])
    family_counts = dict(sorted(Counter(item["family_id"] for item in components).items()))
    return {
        "schema_version": "xinao.f3-active-foundation-input.v1",
        "physical_role": "ACTIVE_SETTLEMENT",
        "active_quote_role": "ACTIVE_DEFAULT_QUOTE",
        "active_quote_version_count": 1,
        "f1_active_physical_semantics_hash": _sha256_text(
            raw.get("f1_active_physical_semantics_hash"),
            "f1_active_physical_semantics_hash",
        ),
        "f2_active_projection_hash": _sha256_text(
            raw.get("f2_active_projection_hash"), "f2_active_projection_hash"
        ),
        "f2_cost_surface_hash": _sha256_text(
            raw.get("f2_cost_surface_hash"), "f2_cost_surface_hash"
        ),
        "active_component_count": len(components),
        "active_family_count": len(family_counts),
        "active_family_counts": family_counts,
        "components": components,
    }


def _finalize(object_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    core = {
        "object_type": object_type,
        "schema_version": SCHEMA_VERSION,
        "semantic_role": SEMANTIC_ROLE,
        **payload,
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"{object_type}@{digest[:16]}",
        "content_sha256": digest,
    }


def verify_versioned_object(value: Mapping[str, Any]) -> bool:
    """Recompute the content identity of one compiled F3 object."""

    if not isinstance(value, Mapping):
        return False
    core = dict(value)
    digest = core.pop("content_sha256", None)
    version_id = core.pop("version_id", None)
    if not isinstance(digest, str) or not isinstance(version_id, str):
        return False
    return canonical_sha256(core) == digest and version_id == (
        f"{core.get('object_type')}@{digest[:16]}"
    )


def _normalize_source_graph(raw: Mapping[str, Any]) -> dict[str, Any]:
    source_by_id: dict[str, str] = {}
    for row in _rows(raw.get("sources"), "source_dependency_graph.sources"):
        source_id = _text(row.get("source_id"), "source_id")
        cluster_id = _text(row.get("origin_cluster_id"), "origin_cluster_id")
        existing = source_by_id.get(source_id)
        if existing is not None and existing != cluster_id:
            raise ResearchWeightCompileError(
                f"source_id {source_id!r} belongs to conflicting origin clusters"
            )
        source_by_id[source_id] = cluster_id

    edges: set[tuple[str, str, str]] = set()
    for row in _rows(raw.get("edges"), "source_dependency_graph.edges"):
        edge = (
            _text(row.get("from"), "source edge from"),
            _text(row.get("to"), "source edge to"),
            _text(row.get("relation"), "source edge relation"),
        )
        if edge[0] not in source_by_id or edge[1] not in source_by_id:
            raise ResearchWeightCompileError("source edge refers to an unknown source_id")
        edges.add(edge)

    cluster_members: dict[str, list[str]] = defaultdict(list)
    for source_id, cluster_id in source_by_id.items():
        cluster_members[cluster_id].append(source_id)

    sources = [
        {"source_id": source_id, "origin_cluster_id": cluster_id}
        for source_id, cluster_id in sorted(source_by_id.items())
    ]
    clusters = [
        {"origin_cluster_id": cluster_id, "member_source_ids": sorted(member_ids)}
        for cluster_id, member_ids in sorted(cluster_members.items())
    ]
    return {
        "sources": sources,
        "origin_clusters": clusters,
        "edges": [
            {"from": source, "to": target, "relation": relation}
            for source, target, relation in sorted(edges)
        ],
        "summary": {
            "independent_origin_cluster_count": len(clusters),
            "source_count": len(sources),
        },
    }


def _normalize_content_graph(
    raw: Mapping[str, Any],
    *,
    source_dependency_ref: str,
    active_foundation_ref: str,
) -> dict[str, Any]:
    nodes: dict[str, dict[str, str]] = {}
    for row in _rows(raw.get("nodes"), "content_service_graph.nodes"):
        node_id = _text(row.get("node_id"), "content node_id")
        normalized = {"node_id": node_id}
        if row.get("family_id") is not None:
            normalized["family_id"] = _text(row.get("family_id"), "content family_id")
        if row.get("role") is not None:
            normalized["role"] = _text(row.get("role"), "content role")
        existing = nodes.get(node_id)
        if existing is not None and existing != normalized:
            raise ResearchWeightCompileError(f"conflicting content node_id: {node_id}")
        nodes[node_id] = normalized

    edges: set[tuple[str, str, str]] = set()
    for row in _rows(raw.get("edges"), "content_service_graph.edges"):
        edge = (
            _text(row.get("from"), "content edge from"),
            _text(row.get("to"), "content edge to"),
            _text(row.get("relation"), "content edge relation"),
        )
        if edge[0] not in nodes or edge[1] not in nodes:
            raise ResearchWeightCompileError("content edge refers to an unknown node_id")
        edges.add(edge)

    return {
        "source_dependency_ref": source_dependency_ref,
        "active_foundation_ref": active_foundation_ref,
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": [
            {"from": source, "to": target, "relation": relation}
            for source, target, relation in sorted(edges)
        ],
        "summary": {"edge_count": len(edges), "node_count": len(nodes)},
    }


def _prior_identity(raw: Mapping[str, Any]) -> str:
    explicit = raw.get("prior_identity", raw.get("prior_kind", raw.get("identity")))
    if explicit is not None and explicit != PRIOR_IDENTITY:
        raise ResearchWeightCompileError(
            "ResearchAttentionPrior must have QUALITATIVE_SEED identity"
        )
    return PRIOR_IDENTITY


def _normalize_attention_prior(
    raw: Mapping[str, Any],
    *,
    source_by_id: Mapping[str, str],
    source_dependency_ref: str,
    content_service_ref: str,
    active_foundation_ref: str,
    active_family_ids: set[str],
) -> dict[str, Any]:
    identity = _prior_identity(raw)
    raw_rows = raw.get("rows")
    if raw_rows is None:
        raw_rows = raw.get("event_class_table")
    event_rows = _rows(raw_rows, "research_attention_prior.rows")
    if not event_rows:
        raise ResearchWeightCompileError("research_attention_prior.rows must not be empty")

    normalized_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in event_rows:
        event_class_id = _text(
            row.get("event_class_id", row.get("event_class")),
            "event_class_id",
        )
        if event_class_id in seen_ids:
            raise ResearchWeightCompileError(f"duplicate event_class_id: {event_class_id}")
        seen_ids.add(event_class_id)

        family_id = _text(row.get("family_id"), "family_id")
        if family_id not in active_family_ids:
            raise ResearchWeightCompileError(
                f"attention row family is outside the ACTIVE foundation: {family_id}"
            )
        tier = _text(row.get("tier"), "tier")
        if tier not in SCHEDULER_SEED_COEFFICIENT_BY_TIER:
            raise ResearchWeightCompileError(f"unknown qualitative tier: {tier}")
        raw_coefficient = row.get("scheduler_seed_coefficient", row.get("prior_w"))
        coefficient = _decimal(raw_coefficient, "scheduler_seed_coefficient")
        expected = SCHEDULER_SEED_COEFFICIENT_BY_TIER[tier]
        if coefficient != expected:
            raise ResearchWeightCompileError(
                f"tier {tier} requires scheduler_seed_coefficient={_decimal_text(expected)}"
            )

        source_ids = sorted(
            {
                _text(item, "source_id")
                for item in _sequence_values(row.get("source_ids"), "source_ids")
            }
        )
        unknown = [source_id for source_id in source_ids if source_id not in source_by_id]
        if unknown:
            raise ResearchWeightCompileError(
                f"attention row refers to unknown source_ids: {', '.join(unknown)}"
            )
        cluster_ids = sorted({source_by_id[source_id] for source_id in source_ids})
        normalized_rows.append(
            {
                "event_class_id": event_class_id,
                "family_id": family_id,
                "tier": tier,
                "scheduler_seed_coefficient": _decimal_text(expected),
                "independent_origin_cluster_ids": cluster_ids,
            }
        )

    normalized_rows.sort(key=lambda item: item["event_class_id"])
    observed_family_ids = {row["family_id"] for row in normalized_rows}
    if observed_family_ids != active_family_ids:
        raise ResearchWeightCompileError(
            "qualitative prior must cover exactly the ACTIVE foundation families"
        )
    by_tier = dict(sorted(Counter(row["tier"] for row in normalized_rows).items()))
    return {
        "prior_identity": identity,
        "source_dependency_ref": source_dependency_ref,
        "content_service_ref": content_service_ref,
        "active_foundation_ref": active_foundation_ref,
        "rows": normalized_rows,
        # The summary is always derived from rows.  Declared draft summaries are ignored.
        "summary": {"by_tier": by_tier, "event_class_count": len(normalized_rows)},
    }


def _sequence_values(value: object, name: str) -> list[object]:
    if value is None:
        return []
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ResearchWeightCompileError(f"{name} must be a sequence")
    return list(value)


def _normalize_policy_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    role = raw.get("semantic_role")
    if role is not None and role != SEMANTIC_ROLE:
        raise ResearchWeightCompileError(f"semantic_role must be {SEMANTIC_ROLE}")
    exploration = _decimal(raw.get("exploration_share"), "exploration_share")
    if not Decimal("0") < exploration < Decimal("1"):
        raise ResearchWeightCompileError("exploration_share must be greater than 0 and less than 1")
    signals = sorted(
        {
            _text(value, "update signal")
            for value in _sequence_values(raw.get("update_signals"), "update_signals")
        }
    )
    return {
        "exploration_share": _decimal_text(exploration),
        "exploitation_share": _decimal_text(Decimal("1") - exploration),
        "update_signals": signals,
    }


def _allocate_family_shares(
    family_seeds: Mapping[str, Decimal],
    exploitation_share: Decimal,
) -> dict[str, Decimal]:
    if not family_seeds:
        raise ResearchWeightCompileError("at least one research family is required")
    seed_total = sum(family_seeds.values(), Decimal("0"))
    quantum = Decimal("0.000000000001")
    family_ids = sorted(family_seeds)
    allocations: dict[str, Decimal] = {}
    allocated = Decimal("0")
    for family_id in family_ids[:-1]:
        share = (exploitation_share * family_seeds[family_id] / seed_total).quantize(
            quantum,
            rounding=ROUND_DOWN,
        )
        allocations[family_id] = share
        allocated += share
    allocations[family_ids[-1]] = exploitation_share - allocated
    return allocations


def _compile_baseline(
    prior: Mapping[str, Any],
    *,
    policy_config: Mapping[str, Any],
    attention_prior_ref: str,
    active_foundation_ref: str,
    active_components: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in prior["rows"]:
        grouped[row["family_id"]].append(row)

    family_seeds = {
        family_id: max(
            _decimal(row["scheduler_seed_coefficient"], "scheduler_seed_coefficient")
            for row in rows
        )
        for family_id, rows in grouped.items()
    }
    exploitation = _decimal(policy_config["exploitation_share"], "exploitation_share")
    allocations = _allocate_family_shares(family_seeds, exploitation)
    active_by_family: dict[str, list[str]] = defaultdict(list)
    for component in active_components:
        active_by_family[str(component["family_id"])].append(str(component["baseline_id"]))
    if set(active_by_family) != set(grouped):
        raise ResearchWeightCompileError(
            "research weights must cover exactly the ACTIVE foundation families"
        )

    family_rows: list[dict[str, Any]] = []
    for family_id in sorted(grouped):
        members = grouped[family_id]
        seed = family_seeds[family_id]
        seed_tier = next(
            tier
            for tier, coefficient in SCHEDULER_SEED_COEFFICIENT_BY_TIER.items()
            if coefficient == seed
        )
        clusters = sorted(
            {
                cluster_id
                for member in members
                for cluster_id in member["independent_origin_cluster_ids"]
            }
        )
        family_rows.append(
            {
                "family_id": family_id,
                "active_component_count": len(active_by_family[family_id]),
                "active_component_ids": sorted(active_by_family[family_id]),
                "member_event_class_count": len(members),
                "member_event_class_ids": sorted(member["event_class_id"] for member in members),
                # Family-first: class count cannot add mass; the family seed is the max.
                "scheduler_seed_coefficient": _decimal_text(seed),
                "seed_tier": seed_tier,
                "independent_origin_cluster_ids": clusters,
                "research_resource_share": _decimal_text(allocations[family_id]),
            }
        )

    exploration = _decimal(policy_config["exploration_share"], "exploration_share")
    return {
        "attention_prior_ref": attention_prior_ref,
        "active_foundation_ref": active_foundation_ref,
        "policy_config_sha256": canonical_sha256(policy_config),
        "aggregation_rule": "FAMILY_SEED_MAX_NOT_CLASS_SUM",
        "family_rows": family_rows,
        "exploration": {"research_resource_share": _decimal_text(exploration)},
        "summary": {
            "event_class_count": len(prior["rows"]),
            "family_count": len(family_rows),
        },
    }


def _compile_active_surface(
    baseline: Mapping[str, Any],
    *,
    weight_baseline_ref: str,
    active_foundation_ref: str,
) -> dict[str, Any]:
    rows = [
        {
            "family_id": row["family_id"],
            "active_component_count": row["active_component_count"],
            "active_component_ids": row["active_component_ids"],
            "research_resource_share": row["research_resource_share"],
            "surface_state": _SURFACE_BY_TIER[row["seed_tier"]],
        }
        for row in baseline["family_rows"]
    ]
    state_counts = dict(sorted(Counter(row["surface_state"] for row in rows).items()))
    return {
        "weight_baseline_ref": weight_baseline_ref,
        "active_foundation_ref": active_foundation_ref,
        "rows": rows,
        "summary": {"by_surface_state": state_counts, "family_count": len(rows)},
    }


def compile_research_weight_foundation(
    *,
    active_foundation_binding: Mapping[str, Any],
    source_dependency_graph: Mapping[str, Any],
    content_service_graph: Mapping[str, Any],
    research_attention_prior: Mapping[str, Any],
    research_portfolio_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile six in-memory F3 objects without reading or mutating source files."""

    active_foundation = _normalize_active_foundation(
        _mapping(active_foundation_binding, "active_foundation_binding")
    )
    active_foundation_ref = canonical_sha256(active_foundation)
    active_family_ids = set(active_foundation["active_family_counts"])

    source_payload = _normalize_source_graph(
        _mapping(source_dependency_graph, "source_dependency_graph")
    )
    source_payload["active_foundation_ref"] = active_foundation_ref
    source_object = _finalize("SourceDependencyGraphVersion", source_payload)
    source_by_id = {row["source_id"]: row["origin_cluster_id"] for row in source_payload["sources"]}

    content_payload = _normalize_content_graph(
        _mapping(content_service_graph, "content_service_graph"),
        source_dependency_ref=source_object["content_sha256"],
        active_foundation_ref=active_foundation_ref,
    )
    content_object = _finalize("ContentServiceGraphVersion", content_payload)

    prior_payload = _normalize_attention_prior(
        _mapping(research_attention_prior, "research_attention_prior"),
        source_by_id=source_by_id,
        source_dependency_ref=source_object["content_sha256"],
        content_service_ref=content_object["content_sha256"],
        active_foundation_ref=active_foundation_ref,
        active_family_ids=active_family_ids,
    )
    prior_object = _finalize("ResearchAttentionPriorVersion", prior_payload)

    policy_config = _normalize_policy_config(
        _mapping(research_portfolio_policy, "research_portfolio_policy")
    )
    baseline_payload = _compile_baseline(
        prior_payload,
        policy_config=policy_config,
        attention_prior_ref=prior_object["content_sha256"],
        active_foundation_ref=active_foundation_ref,
        active_components=active_foundation["components"],
    )
    baseline_object = _finalize("ResearchWeightBaselineVersion", baseline_payload)

    active_payload = _compile_active_surface(
        baseline_payload,
        weight_baseline_ref=baseline_object["content_sha256"],
        active_foundation_ref=active_foundation_ref,
    )
    active_object = _finalize("ActiveResearchSurfaceVersion", active_payload)

    policy_payload = {
        **policy_config,
        "active_surface_ref": active_object["content_sha256"],
        "active_foundation_ref": active_foundation_ref,
        "allocation_scope": SEMANTIC_ROLE,
    }
    policy_object = _finalize("ResearchPortfolioPolicyVersion", policy_payload)

    objects = {
        "SourceDependencyGraphVersion": source_object,
        "ContentServiceGraphVersion": content_object,
        "ResearchAttentionPriorVersion": prior_object,
        "ResearchWeightBaselineVersion": baseline_object,
        "ActiveResearchSurfaceVersion": active_object,
        "ResearchPortfolioPolicyVersion": policy_object,
    }
    bundle_identity = {
        object_type: value["content_sha256"] for object_type, value in sorted(objects.items())
    }
    return {
        "schema_version": "xinao.research-weight-foundation.v1",
        "semantic_role": SEMANTIC_ROLE,
        "does_not_modify": list(_DOES_NOT_MODIFY),
        "active_foundation_sha256": active_foundation_ref,
        "active_component_count": active_foundation["active_component_count"],
        "active_quote_version_count": active_foundation["active_quote_version_count"],
        "objects": objects,
        "bundle_sha256": canonical_sha256(bundle_identity),
    }
