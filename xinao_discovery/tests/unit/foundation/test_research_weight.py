from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from xinao.foundation.research_weight import (
    ResearchWeightCompileError,
    compile_research_weight_foundation,
    verify_versioned_object,
)

TIER_COEFFICIENTS = {
    "S": "1",
    "A+": "0.72",
    "A": "0.55",
    "B+": "0.38",
    "B": "0.25",
    "C": "0.12",
    "D": "0.05",
    "E": "0.02",
}


def _source_graph() -> dict[str, object]:
    return {
        "sources": [
            {"source_id": "mirror-b", "origin_cluster_id": "cluster-one"},
            {"source_id": "independent", "origin_cluster_id": "cluster-two"},
            {"source_id": "mirror-a", "origin_cluster_id": "cluster-one"},
        ],
        "edges": [
            {"from": "mirror-b", "to": "mirror-a", "relation": "REPRINT"},
        ],
    }


def _content_graph() -> dict[str, object]:
    return {
        "nodes": [
            {"node_id": "terminal-special", "family_id": "special-number"},
            {"node_id": "filter-tail", "family_id": "special-number"},
            {"node_id": "linked", "family_id": "linked-zodiac"},
        ],
        "edges": [
            {
                "from": "filter-tail",
                "to": "terminal-special",
                "relation": "FILTER_SUPPORT",
            }
        ],
    }


def _prior_rows() -> list[dict[str, object]]:
    return [
        {
            "event_class": "special-direct",
            "family_id": "special-number",
            "tier": "S",
            "scheduler_seed_coefficient": "1",
            "source_ids": ["mirror-a", "mirror-b"],
        },
        {
            "event_class": "special-tail",
            "family_id": "special-number",
            "tier": "C",
            "scheduler_seed_coefficient": "0.12",
            "source_ids": ["independent"],
        },
        {
            "event_class": "linked-two",
            "family_id": "linked-zodiac",
            "tier": "A+",
            "scheduler_seed_coefficient": "0.72",
            "source_ids": ["independent"],
        },
    ]


def _active_foundation(rows: list[dict[str, object]]) -> dict[str, object]:
    family_ids = sorted({str(row["family_id"]) for row in rows})
    return {
        "physical_role": "ACTIVE_SETTLEMENT",
        "active_quote_role": "ACTIVE_DEFAULT_QUOTE",
        "active_quote_version_count": 1,
        "f1_active_physical_semantics_hash": "1" * 64,
        "f2_active_projection_hash": "2" * 64,
        "f2_cost_surface_hash": "3" * 64,
        "components": [
            {
                "baseline_id": f"BO{index + 1:04d}",
                "family_id": family_id,
                "physical_role": "ACTIVE_SETTLEMENT",
                "quote_role": "ACTIVE_DEFAULT_QUOTE",
                "semantic_record_hash": f"{index + 4:064x}",
                "cost_binding_hash": f"{index + 100:064x}",
            }
            for index, family_id in enumerate(family_ids)
        ],
    }


def _compile(
    *,
    rows: list[dict[str, object]] | None = None,
    exploration_share: str = "0.10",
) -> dict[str, object]:
    selected_rows = _prior_rows() if rows is None else rows
    return compile_research_weight_foundation(
        active_foundation_binding=_active_foundation(selected_rows),
        source_dependency_graph=_source_graph(),
        content_service_graph=_content_graph(),
        research_attention_prior={
            "prior_identity": "QUALITATIVE_SEED",
            "rows": selected_rows,
            "summary": {"event_class_count": 58},
        },
        research_portfolio_policy={
            "exploration_share": exploration_share,
            "update_signals": ["INFORMATION_GAIN", "FALSIFICATION_VALUE"],
        },
    )


def _legacy_draft_anomaly() -> dict[str, object]:
    counts = {"S": 5, "A+": 4, "A": 6, "B+": 10, "B": 9, "C": 15, "D": 7, "E": 4}
    rows: list[dict[str, object]] = []
    for tier, count in counts.items():
        for index in range(count):
            rows.append(
                {
                    "event_class": f"{tier}-{index}",
                    "family_id": f"family-{index % 13}",
                    "tier": tier,
                    # The D: draft uses this legacy name.  It is input-only.
                    "prior_w": float(TIER_COEFFICIENTS[tier]),
                }
            )
    return {
        "status": "QUALITATIVE_SEED",
        "event_class_table": rows,
        # This intentionally reproduces the draft's stale 58-row declaration.
        "summary_stats": {"n_event_classes": 58},
    }


def _all_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value] + [
            nested_key for item in value.values() for nested_key in _all_keys(item)
        ]
    if isinstance(value, list | tuple):
        return [nested_key for item in value for nested_key in _all_keys(item)]
    return []


def test_recomputes_actual_draft_rows_and_renames_all_eight_seed_values() -> None:
    draft = _legacy_draft_anomaly()
    bundle = compile_research_weight_foundation(
        active_foundation_binding=_active_foundation(draft["event_class_table"]),
        source_dependency_graph={"sources": [], "edges": []},
        content_service_graph={"nodes": [], "edges": []},
        research_attention_prior=draft,
        research_portfolio_policy={"exploration_share": "0.10"},
    )
    prior = bundle["objects"]["ResearchAttentionPriorVersion"]

    assert prior["summary"]["event_class_count"] == 60
    assert prior["summary"]["by_tier"] == {
        "A": 6,
        "A+": 4,
        "B": 9,
        "B+": 10,
        "C": 15,
        "D": 7,
        "E": 4,
        "S": 5,
    }
    assert {row["scheduler_seed_coefficient"] for row in prior["rows"]} == set(
        TIER_COEFFICIENTS.values()
    )
    assert "prior_w" not in _all_keys(bundle)


def test_family_first_seed_uses_max_and_ignores_class_count_inflation() -> None:
    one_class = _compile(rows=[_prior_rows()[0], _prior_rows()[2]])
    inflated_rows = [_prior_rows()[2]] + [
        {
            "event_class": f"special-{index}",
            "family_id": "special-number",
            "tier": "S" if index == 0 else "E",
            "scheduler_seed_coefficient": "1" if index == 0 else "0.02",
        }
        for index in range(49)
    ]
    inflated = _compile(rows=inflated_rows)

    one_rows = one_class["objects"]["ResearchWeightBaselineVersion"]["family_rows"]
    inflated_rows_out = inflated["objects"]["ResearchWeightBaselineVersion"]["family_rows"]
    one_special = next(row for row in one_rows if row["family_id"] == "special-number")
    inflated_special = next(
        row for row in inflated_rows_out if row["family_id"] == "special-number"
    )

    assert one_special["scheduler_seed_coefficient"] == "1"
    assert inflated_special["scheduler_seed_coefficient"] == "1"
    assert inflated_special["research_resource_share"] == one_special["research_resource_share"]
    assert inflated_special["member_event_class_count"] == 49


def test_same_origin_sources_count_once_in_rows_and_families() -> None:
    bundle = _compile()
    prior_rows = bundle["objects"]["ResearchAttentionPriorVersion"]["rows"]
    baseline_rows = bundle["objects"]["ResearchWeightBaselineVersion"]["family_rows"]
    special_direct = next(row for row in prior_rows if row["event_class_id"] == "special-direct")
    special_family = next(row for row in baseline_rows if row["family_id"] == "special-number")

    assert special_direct["independent_origin_cluster_ids"] == ["cluster-one"]
    assert special_family["independent_origin_cluster_ids"] == [
        "cluster-one",
        "cluster-two",
    ]
    source_graph = bundle["objects"]["SourceDependencyGraphVersion"]
    assert source_graph["summary"] == {
        "independent_origin_cluster_count": 2,
        "source_count": 3,
    }


def test_exploration_is_positive_and_all_outputs_have_only_resource_share_semantics() -> None:
    bundle = _compile(exploration_share="0.125")
    objects = bundle["objects"]
    policy = objects["ResearchPortfolioPolicyVersion"]
    baseline = objects["ResearchWeightBaselineVersion"]

    assert policy["exploration_share"] == "0.125"
    assert Decimal(policy["exploration_share"]) > 0
    assert all(item["semantic_role"] == "RESEARCH_RESOURCE_SHARE" for item in objects.values())
    family_total = sum(Decimal(row["research_resource_share"]) for row in baseline["family_rows"])
    assert family_total + Decimal(baseline["exploration"]["research_resource_share"]) == 1
    assert bundle["does_not_modify"] == [
        "BETTING_AMOUNT",
        "BOOKMAKER_EXPOSURE",
        "DRAW_PROBABILITY",
        "SETTLEMENT_TRUTH",
    ]

    with pytest.raises(ResearchWeightCompileError, match="exploration_share"):
        _compile(exploration_share="0")


def test_qualitative_seed_identity_is_mandatory() -> None:
    with pytest.raises(ResearchWeightCompileError, match="QUALITATIVE_SEED"):
        compile_research_weight_foundation(
            active_foundation_binding=_active_foundation(_prior_rows()),
            source_dependency_graph=_source_graph(),
            content_service_graph=_content_graph(),
            research_attention_prior={
                "prior_identity": "MEASURED_ATTENTION_PRIOR",
                "rows": _prior_rows(),
            },
            research_portfolio_policy={"exploration_share": "0.10"},
        )


def test_compilation_and_hashes_are_stable_under_input_reordering() -> None:
    first = _compile()
    source_graph = _source_graph()
    source_graph["sources"] = list(reversed(source_graph["sources"]))
    content_graph = _content_graph()
    content_graph["nodes"] = list(reversed(content_graph["nodes"]))
    prior = {
        "prior_identity": "QUALITATIVE_SEED",
        "rows": list(reversed(deepcopy(_prior_rows()))),
        "summary": {"event_class_count": 999},
    }
    second = compile_research_weight_foundation(
        active_foundation_binding=_active_foundation(_prior_rows()),
        source_dependency_graph=source_graph,
        content_service_graph=content_graph,
        research_attention_prior=prior,
        research_portfolio_policy={
            "update_signals": ["FALSIFICATION_VALUE", "INFORMATION_GAIN"],
            "exploration_share": "0.10",
        },
    )

    assert second == first
    assert all(verify_versioned_object(item) for item in first["objects"].values())


def test_all_six_objects_bind_the_same_active_foundation_and_reject_frozen_rows() -> None:
    bundle = _compile()
    refs = {item["active_foundation_ref"] for item in bundle["objects"].values()}

    assert refs == {bundle["active_foundation_sha256"]}
    assert bundle["active_component_count"] == 2
    assert bundle["active_quote_version_count"] == 1

    frozen = _active_foundation(_prior_rows())
    frozen["components"][0]["physical_role"] = "FROZEN_AGENT_ROUTE_QUOTE"
    with pytest.raises(ResearchWeightCompileError, match="ACTIVE_SETTLEMENT"):
        compile_research_weight_foundation(
            active_foundation_binding=frozen,
            source_dependency_graph=_source_graph(),
            content_service_graph=_content_graph(),
            research_attention_prior={"rows": _prior_rows()},
            research_portfolio_policy={"exploration_share": "0.10"},
        )


def test_duplicate_event_class_ids_are_rejected_instead_of_inflating_a_family() -> None:
    duplicate = [*_prior_rows(), deepcopy(_prior_rows()[0])]
    with pytest.raises(ResearchWeightCompileError, match="duplicate event_class_id"):
        _compile(rows=duplicate)
