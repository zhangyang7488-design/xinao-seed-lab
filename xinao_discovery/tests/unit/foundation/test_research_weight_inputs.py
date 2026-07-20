from __future__ import annotations

import hashlib
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation.f2_compile import compile_f2_artifacts
from xinao.foundation.research_weight import SEMANTIC_ROLE, verify_versioned_object
from xinao.foundation.research_weight_inputs import (
    DEFAULT_EXTERNAL_SYNTHESIS_PATH,
    DEFAULT_PRIOR_DRAFT_PATH,
    DEFAULT_SERVICE_GRAPH_PATH,
    FORMAL_FAMILY_IDS,
    compile_current_research_weight_foundation,
    compile_research_weight_foundation_from_input_paths,
)
from xinao.foundation.selection_manifest import FROZEN_ROUTE_QUOTE_BASELINE_IDS
from xinao.foundation.semantics_registry import (
    compile_default_semantics_registry,
    compile_semantics_registry,
    load_play_catalog,
)


def test_current_qualitative_draft_compiles_six_recomputable_f3_objects() -> None:
    first = compile_current_research_weight_foundation()
    second = compile_current_research_weight_foundation()

    assert second == first
    assert len(first["objects"]) == 6
    assert all(verify_versioned_object(value) for value in first["objects"].values())
    assert first["input_identity"] == "QUALITATIVE_SEED"
    assert first["measured_attention_claimed"] is False
    assert first["semantic_role"] == SEMANTIC_ROLE
    assert first["active_component_count"] == 416
    assert first["active_quote_version_count"] == 1
    assert len({value["active_foundation_ref"] for value in first["objects"].values()}) == 1
    assert first["does_not_modify"] == [
        "BETTING_AMOUNT",
        "BOOKMAKER_EXPOSURE",
        "DRAW_PROBABILITY",
        "SETTLEMENT_TRUTH",
    ]


def test_hermetic_f3_compiler_requires_and_binds_all_three_explicit_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError):
        compile_research_weight_foundation_from_input_paths()  # type: ignore[call-arg]

    source_paths = {
        "prior_draft": DEFAULT_PRIOR_DRAFT_PATH,
        "service_graph": DEFAULT_SERVICE_GRAPH_PATH,
        "external_synthesis": DEFAULT_EXTERNAL_SYNTHESIS_PATH,
    }
    copied_paths = {}
    for name, source in source_paths.items():
        copied = tmp_path / f"{name}.json"
        copied.write_bytes(source.read_bytes() + b"\n ")
        copied_paths[name] = copied

    registry = compile_default_semantics_registry()
    f2_report = compile_f2_artifacts(registry)
    explicit = compile_research_weight_foundation_from_input_paths(
        prior_path=copied_paths["prior_draft"],
        service_graph_path=copied_paths["service_graph"],
        external_synthesis_path=copied_paths["external_synthesis"],
        semantics_registry=registry,
        f2_report=f2_report,
    )
    default = compile_current_research_weight_foundation(
        semantics_registry=registry,
        f2_report=f2_report,
    )
    assert explicit["objects"] == default["objects"]
    assert set(explicit["input_bindings"]) == {
        "prior_draft",
        "service_graph",
        "external_synthesis",
    }
    assert {name: binding["sha256"] for name, binding in explicit["input_bindings"].items()} == {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in copied_paths.items()
    }


def test_current_prior_contains_all_formal_families_and_positive_exploration() -> None:
    bundle = compile_current_research_weight_foundation()
    prior = bundle["objects"]["ResearchAttentionPriorVersion"]
    baseline = bundle["objects"]["ResearchWeightBaselineVersion"]
    policy = bundle["objects"]["ResearchPortfolioPolicyVersion"]

    assert prior["summary"]["event_class_count"] == 48
    observed = {row["family_id"] for row in prior["rows"]}
    assert observed == FORMAL_FAMILY_IDS
    assert Decimal(policy["exploration_share"]) > 0
    total = sum(Decimal(row["research_resource_share"]) for row in baseline["family_rows"])
    total += Decimal(baseline["exploration"]["research_resource_share"])
    assert total == 1


def test_external_sources_are_clustered_by_origin_domain_not_raw_url_count() -> None:
    bundle = compile_current_research_weight_foundation()
    graph = bundle["objects"]["SourceDependencyGraphVersion"]
    sources = graph["sources"]
    clusters = {row["origin_cluster_id"] for row in sources}

    assert len(sources) > len(clusters)
    assert "local-study:weight-prior-v0" in clusters
    assert all(binding["sha256"] for binding in bundle["input_bindings"].values())


def test_only_416_active_components_generate_service_nodes_and_family_weights() -> None:
    bundle = compile_current_research_weight_foundation()
    objects = bundle["objects"]
    service = objects["ContentServiceGraphVersion"]
    active_nodes = [
        row for row in service["nodes"] if row.get("role") == "ACTIVE_SETTLEMENT_COMPONENT"
    ]
    baseline_ids = {row["node_id"].removeprefix("active-settlement:") for row in active_nodes}
    baseline = objects["ResearchWeightBaselineVersion"]

    assert len(active_nodes) == 416
    assert not baseline_ids & FROZEN_ROUTE_QUOTE_BASELINE_IDS
    assert sum(row["active_component_count"] for row in baseline["family_rows"]) == 416
    assert all(row["active_component_count"] > 0 for row in baseline["family_rows"])


def test_b_route_quote_mutation_does_not_propagate_into_any_required_f3_object() -> None:
    catalog = load_play_catalog()
    mutated = deepcopy(catalog)
    for row in mutated["entries"]:
        if row["baseline_id"] in FROZEN_ROUTE_QUOTE_BASELINE_IDS:
            row["baseline_odds_components"] = ["1.23456789"]
    mutated["content_hash"] = canonical_sha256(
        {key: value for key, value in mutated.items() if key != "content_hash"}
    )

    original_registry = compile_default_semantics_registry()
    mutated_registry = compile_semantics_registry(mutated)
    original_f2 = compile_f2_artifacts(original_registry)
    mutated_f2 = compile_f2_artifacts(mutated_registry)
    original = compile_current_research_weight_foundation(
        semantics_registry=original_registry,
        f2_report=original_f2,
    )
    after_b_mutation = compile_current_research_weight_foundation(
        semantics_registry=mutated_registry,
        f2_report=mutated_f2,
    )

    assert after_b_mutation == original
