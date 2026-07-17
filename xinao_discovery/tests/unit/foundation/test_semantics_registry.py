from __future__ import annotations

import copy
from collections import Counter

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)
from xinao.foundation.semantics_basic import RuleSemanticRecord as BasicRuleSemanticRecord
from xinao.foundation.semantics_combinations import CombinationSemanticRecord
from xinao.foundation.semantics_linked import LinkedSemanticsCompilation
from xinao.foundation.semantics_registry import (
    DEFAULT_PLAY_CATALOG_PATH,
    EXPECTED_ACTIVE_FAMILY_COUNTS,
    assert_bounded_source_claims,
    compile_semantics_registry,
    load_play_catalog,
)
from xinao.foundation.semantics_sets import SetFamilySemanticsCompilation


@pytest.fixture(scope="module")
def catalog() -> dict[str, object]:
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    return load_play_catalog()


@pytest.fixture(scope="module")
def registry(catalog):
    return compile_semantics_registry(catalog)


def _normalized_rehash(catalog: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(catalog)
    entries = sorted(result["entries"], key=lambda row: row["baseline_id"])
    result["entries"] = entries
    body = {key: value for key, value in result.items() if key != "content_hash"}
    result["content_hash"] = canonical_sha256(body)
    return result


def _rehash_content(payload: dict[str, object]) -> dict[str, object]:
    body = copy.deepcopy(payload)
    body.pop("content_hash", None)
    body["content_hash"] = canonical_sha256(body)
    return body


def test_preserves_four_strict_source_artifacts_and_exact_416_active_partition(
    registry,
) -> None:
    source = registry.source_artifacts
    assert len(source.basic_records) == 77
    assert len(source.set_compilation.rule_semantic_map.records) == 119
    assert len(source.combination_records) == 22
    assert len(source.linked_compilation.rule_semantic_map.records) == 198
    assert all(isinstance(record, BasicRuleSemanticRecord) for record in source.basic_records)
    assert isinstance(source.set_compilation, SetFamilySemanticsCompilation)
    assert all(
        isinstance(record, CombinationSemanticRecord) for record in source.combination_records
    )
    assert isinstance(source.linked_compilation, LinkedSemanticsCompilation)

    records = registry.rule_semantic_map.records
    assert len(records) == 416
    assert {record.baseline_id for record in records} == ACTIVE_SETTLEMENT_BASELINE_IDS
    assert dict(Counter(record.family_id for record in records)) == EXPECTED_ACTIVE_FAMILY_COUNTS
    assert registry.rule_semantic_map.family_counts == EXPECTED_ACTIVE_FAMILY_COUNTS
    assert Counter(record.physical_role for record in records) == {"ACTIVE_SETTLEMENT": 416}
    assert registry.rule_semantic_map.foundation_complete is False


def test_b_rows_remain_catalog_only_classification_and_have_no_a_target(catalog, registry) -> None:
    source_ids = {row["baseline_id"] for row in catalog["entries"]}
    assert len(source_ids) == 433
    assert source_ids >= FROZEN_ROUTE_QUOTE_BASELINE_IDS
    projections = (
        {record.baseline_id for record in registry.rule_semantic_map.records},
        {rule.baseline_id for rule in registry.rule_set.rules},
        {binding.baseline_id for binding in registry.settlement_function_set.bindings},
        {
            baseline_id
            for spec in registry.expected_selection_domain.specifications
            for baseline_id in spec.component_baseline_ids
        },
    )
    assert all(ids == ACTIVE_SETTLEMENT_BASELINE_IDS for ids in projections)
    assert all(ids.isdisjoint(FROZEN_ROUTE_QUOTE_BASELINE_IDS) for ids in projections)
    registry_dump = repr(
        {
            "semantic_map": registry.rule_semantic_map.model_dump(mode="json"),
            "rule_set": registry.rule_set.model_dump(mode="json"),
            "function_set": registry.settlement_function_set.model_dump(mode="json"),
        }
    )
    assert "hit_semantic" not in registry_dump
    assert "frozen_route_quote_map" not in registry_dump


def test_frozen_route_quote_cannot_be_injected_into_active_function_set(registry) -> None:
    function_model = type(registry.settlement_function_set)
    injected = registry.settlement_function_set.model_dump(mode="json")
    injected["bindings"][0]["baseline_id"] = "BO0013"
    injected = _rehash_content(injected)
    with pytest.raises(ValueError, match="frozen route quote"):
        function_model.model_validate(injected)


def test_b_quote_source_change_cannot_propagate_into_active_f1_hashes(catalog, registry) -> None:
    changed = copy.deepcopy(catalog)
    b_row = next(row for row in changed["entries"] if row["baseline_id"] == "BO0013")
    b_row["baseline_odds_components"] = ["41.999"]
    changed = _normalized_rehash(changed)
    assert changed["content_hash"] != catalog["content_hash"]
    second = compile_semantics_registry(changed)

    assert second.content_hash == registry.content_hash
    assert second.rule_semantic_map.content_hash == registry.rule_semantic_map.content_hash
    assert (
        second.expected_selection_domain.content_hash
        == registry.expected_selection_domain.content_hash
    )
    assert second.rule_set.content_hash == registry.rule_set.content_hash
    assert second.active_physical_semantics_hash == registry.active_physical_semantics_hash
    assert (
        second.settlement_function_set.content_hash == registry.settlement_function_set.content_hash
    )


def test_canonical_records_bind_exact_catalog_fields_and_required_semantics(
    catalog, registry
) -> None:
    raw_by_id = {row["baseline_id"]: row for row in catalog["entries"]}
    domain_ids = {spec.spec_id for spec in registry.expected_selection_domain.specifications}
    for record in registry.rule_semantic_map.records:
        assert (
            record.catalog.model_dump(mode="json", exclude={"content_hash"})
            == raw_by_id[record.baseline_id]
        )
        assert record.catalog.content_hash
        assert record.source_record_hash
        assert record.predicate_ref
        assert record.selection_domain_spec_id in domain_ids
        assert record.settlement_tiers
        assert {tier.terminal_role for tier in record.settlement_tiers} >= {"HIT", "MISS"}
        assert record.snapshot_payout_binding
        assert record.quote_components == tuple(
            raw_by_id[record.baseline_id]["baseline_odds_components"]
        )
        assert record.principal_refund_on_normal_settlement is False
        assert record.void_policy
        assert record.rounding_policy
        assert record.boundary_policy
        assert record.effective_interval
        assert record.semantic_evidence_statuses
        assert record.evidence_basis
        assert record.probability_artifact_status == "FORMULA_REF_ONLY_NOT_F2_COMPILED"

    assert registry.settlement_function_set.probability_artifacts_compiled is False
    assert registry.settlement_function_set.foundation_complete is False
    assert registry.rule_set.foundation_complete is False


def test_compact_manifest_separates_component_rows_from_atomic_tickets(registry) -> None:
    manifest = registry.expected_selection_domain
    specs = manifest.specifications
    component_ids = [baseline for spec in specs for baseline in spec.component_baseline_ids]
    assert manifest.component_catalog_row_count == 416
    assert set(component_ids) == ACTIVE_SETTLEMENT_BASELINE_IDS
    assert len(component_ids) == len(set(component_ids)) == 416
    assert manifest.selection_domain_spec_count == 233
    assert manifest.canonical_materialized_atomic_selection_count == 0
    assert all(spec.canonical_manifest_materialized_atomic_selection_count == 0 for spec in specs)

    basic_count = sum(
        spec.exact_atomic_selection_count
        for spec in specs
        if spec.family_id in {"special-number", "regular-number", "regular-position-special"}
    )
    set_count = sum(
        spec.exact_atomic_selection_count
        for spec in specs
        if spec.family_id in {"other-explicit", "one-zodiac-tail", "six-zodiac"}
    )
    combination_count = sum(
        spec.exact_atomic_selection_count
        for spec in specs
        if spec.family_id
        in {
            "linked-number",
            "multi-select-no-hit",
            "multi-select-one-hit",
            "special-regular-hit",
        }
    )
    linked_count = sum(
        spec.exact_atomic_selection_count
        for spec in specs
        if spec.family_id in {"linked-zodiac", "linked-tail", "parlay"}
    )
    assert (basic_count, set_count, combination_count, linked_count) == (
        461,
        1965,
        21_652_273_825,
        265_997,
    )
    assert manifest.exact_atomic_selection_count == 21_652_542_248
    assert manifest.source_materialized_atomic_selection_count == 461 + 1965

    parlay = next(spec for spec in specs if spec.family_id == "parlay")
    assert len(parlay.component_baseline_ids) == 42
    assert parlay.exact_atomic_selection_count == 262_101
    assert parlay.expansion_policy == "LAZY_COMBINATORIAL"
    assert parlay.source_materialized_atomic_selection_count == 0


def test_rule_and_settlement_projections_are_hash_bound_to_all_records(registry) -> None:
    semantic_by_id = {record.baseline_id: record for record in registry.rule_semantic_map.records}
    assert len(registry.rule_set.rules) == 416
    assert len(registry.settlement_function_set.bindings) == 416
    assert registry.settlement_function_set.function_count == 416
    for rule in registry.rule_set.rules:
        source = semantic_by_id[rule.baseline_id]
        assert rule.semantic_record_hash == source.content_hash
        assert rule.predicate_ref == source.predicate_ref
        assert rule.selection_domain_spec_id == source.selection_domain_spec_id
    for binding in registry.settlement_function_set.bindings:
        source = semantic_by_id[binding.baseline_id]
        assert source.physical_role == "ACTIVE_SETTLEMENT"
        assert binding.semantic_record_hash == source.content_hash
        assert binding.settlement_tiers == source.settlement_tiers
        assert binding.quote_components == source.quote_components
        assert binding.principal_refund_on_normal_settlement is False


def test_combination_probability_refs_are_projected_without_claiming_f2(registry) -> None:
    source_by_id = {
        record.baseline_id: record for record in registry.source_artifacts.combination_records
    }
    projected = [
        record
        for record in registry.rule_semantic_map.records
        if record.source_module == "combinations"
    ]
    assert len(projected) == 22
    for record in projected:
        assert (
            record.probability_formula_ref
            == source_by_id[record.baseline_id].probability_formula_ref
        )
        assert record.probability_artifact_status == "FORMULA_REF_ONLY_NOT_F2_COMPILED"
    assert registry.settlement_function_set.probability_artifacts_compiled is False


def test_reordered_catalog_input_has_identical_artifact_hashes(catalog, registry) -> None:
    reordered = copy.deepcopy(catalog)
    reordered["entries"] = list(reversed(reordered["entries"]))
    second = compile_semantics_registry(reordered)
    assert second.content_hash == registry.content_hash
    assert second.rule_semantic_map.content_hash == registry.rule_semantic_map.content_hash
    assert (
        second.expected_selection_domain.content_hash
        == registry.expected_selection_domain.content_hash
    )
    assert second.rule_set.content_hash == registry.rule_set.content_hash
    assert (
        second.settlement_function_set.content_hash == registry.settlement_function_set.content_hash
    )


def test_catalog_quote_change_changes_registry_hash_when_rehashed(catalog, registry) -> None:
    changed = copy.deepcopy(catalog)
    changed["entries"][0]["baseline_odds_components"] = ["47.286"]
    changed = _normalized_rehash(changed)
    second = compile_semantics_registry(changed)
    assert second.content_hash != registry.content_hash
    assert second.rule_semantic_map.records[0].quote_components == ("47.286",)


def test_missing_duplicate_unknown_and_family_drift_fail_closed(catalog) -> None:
    missing = copy.deepcopy(catalog)
    missing["entries"] = missing["entries"][:-1]
    missing["entry_count"] = 432
    with pytest.raises(ValueError, match="exactly 433"):
        compile_semantics_registry(missing)

    duplicate = copy.deepcopy(catalog)
    duplicate["entries"][1]["baseline_id"] = duplicate["entries"][0]["baseline_id"]
    with pytest.raises(ValueError, match="duplicate baseline"):
        compile_semantics_registry(duplicate)

    unknown = copy.deepcopy(catalog)
    unknown["entries"][0]["family_id"] = "invented-family"
    with pytest.raises(ValueError, match="unknown families"):
        compile_semantics_registry(unknown)

    drifted = copy.deepcopy(catalog)
    next(row for row in drifted["entries"] if row["family_id"] == "linked-tail")["family_id"] = (
        "linked-zodiac"
    )
    with pytest.raises(ValueError, match="family coverage drifted"):
        compile_semantics_registry(drifted)


def test_catalog_hash_tampering_fails_before_projection(catalog) -> None:
    tampered = copy.deepcopy(catalog)
    tampered["content_hash"] = "0" * 64
    with pytest.raises(ValueError, match="does not bind"):
        compile_semantics_registry(tampered)


def test_bounded_module_cannot_claim_foundation_complete() -> None:
    assert_bounded_source_claims(
        {"coverage": {"foundation_complete": False}},
        ({"nested": "ok"},),
    )
    with pytest.raises(ValueError, match="cannot claim foundation_complete"):
        assert_bounded_source_claims({"coverage": {"mapped": 94, "foundation_complete": True}})
