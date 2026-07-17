from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation.f2_compile import (
    OddsSpaceBenchmarkVersion,
    RebateScheduleVersion,
    SettlementCostCompileReport,
    SettlementCostSurfaceVersion,
    SettlementProbabilitySnapshotVersion,
    compile_channel_metadata_diagnostic,
    compile_f2_artifacts,
)
from xinao.foundation.selection_manifest import (
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
)
from xinao.foundation.semantics_registry import (
    DEFAULT_PLAY_CATALOG_PATH,
    compile_default_semantics_registry,
    compile_semantics_registry,
    load_play_catalog,
)


@pytest.fixture(scope="module")
def registry():
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    return compile_default_semantics_registry()


@pytest.fixture(scope="module")
def report(registry) -> SettlementCostCompileReport:
    return compile_f2_artifacts(registry)


def test_probability_artifact_covers_active_416_without_demoting_grouped_domains(report) -> None:
    snapshot = report.probability_snapshot
    assert len(snapshot.bindings) == 416
    assert len({binding.baseline_id for binding in snapshot.bindings}) == 416
    assert snapshot.exact_numeric_component_count == 218
    assert snapshot.symbolic_component_count == 198
    assert len(snapshot.symbolic_formulas) == 15
    assert len(snapshot.atomic_ticket_bindings) == 37
    assert snapshot.source_atomic_ticket_projection_hash

    grouped = [
        binding
        for binding in snapshot.bindings
        if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
    ]
    assert len(grouped) == 198
    assert all(not binding.exact_cases for binding in grouped)
    assert all(
        binding.ticket_identity == "GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET" for binding in grouped
    )
    assert all(binding.symbolic_formula_id for binding in grouped)
    assert all(binding.independent_atomic_ticket_binding_id for binding in grouped)
    assert all(
        formula.component_rows_are_independent_tickets is False
        and formula.materialized_atomic_ticket_count == 0
        for formula in snapshot.symbolic_formulas
    )
    assert (
        sum(formula.exact_atomic_selection_count for formula in snapshot.symbolic_formulas)
        == 265_997
    )
    assert (
        sum(
            formula.surface_proof.evaluated_atomic_ticket_count
            for formula in snapshot.symbolic_formulas
        )
        == 265_997
    )
    assert (
        sum(
            formula.surface_proof.probability_equivalence_class_count
            for formula in snapshot.symbolic_formulas
        )
        == 1_736
    )
    parlay_formula = next(
        formula for formula in snapshot.symbolic_formulas if formula.family_id == "parlay"
    )
    assert parlay_formula.surface_proof.probability_equivalence_class_count == 1_708
    assert parlay_formula.surface_proof.probability_cache_hit_count == 260_393
    assert parlay_formula.surface_proof.materialized_atomic_ticket_count == 0

    ticket_bindings = snapshot.atomic_ticket_bindings
    assert sum(binding.representation == "EXACT_NUMERIC" for binding in ticket_bindings) == 22
    assert (
        sum(binding.representation == "SYMBOLIC_DOMAIN_FORMULA" for binding in ticket_bindings)
        == 15
    )
    combination = next(
        binding
        for binding in ticket_bindings
        if binding.selection_domain_spec_id == "selection-domain:combinations:BO0213"
    )
    assert combination.exact_probability_component_baseline_id == "BO0213"
    assert combination.canonical_ticket_identity_rule == "play_id::selection_id"
    assert combination.materialized_atomic_ticket_count == 0
    assert all(
        formula.independent_atomic_ticket_binding_hash for formula in snapshot.symbolic_formulas
    )


def test_every_exact_probability_case_is_a_reduced_normalized_partition(report) -> None:
    exact = [
        binding
        for binding in report.probability_snapshot.bindings
        if binding.representation == "EXACT_NUMERIC"
    ]
    assert len(exact) == 218
    for binding in exact:
        assert binding.exact_cases
        for case in binding.exact_cases:
            total = sum(
                (tier.probability.as_fraction() for tier in case.tier_probabilities),
                start=Fraction(0),
            )
            assert total == 1
            for tier in case.tier_probabilities:
                dumped = tier.probability.model_dump(mode="json")
                assert set(dumped) == {"numerator", "denominator"}
                assert dumped["denominator"] > 0

    six_zodiac = [binding for binding in exact if binding.family_id == "six-zodiac"]
    assert len(six_zodiac) == 2
    assert all(
        sum(case.atomic_selection_count for case in binding.exact_cases) == 924
        for binding in six_zodiac
    )
    assert all(
        case.tier_probabilities[0].probability.as_fraction() == Fraction(24, 49)
        for binding in six_zodiac
        for case in binding.exact_cases
    )


def test_all_source_quotes_are_preserved_but_channel_b_is_not_an_active_cost_surface(
    report, registry
) -> None:
    cost_by_id = {binding.baseline_id: binding for binding in report.cost_surface.bindings}
    benchmark_by_id = {
        binding.baseline_id: binding for binding in report.odds_space_benchmark.bindings
    }
    semantic_by_id = {record.baseline_id: record for record in registry.rule_semantic_map.records}
    active_semantic_ids = set(semantic_by_id)
    assert len(active_semantic_ids) == 416
    assert set(cost_by_id) == active_semantic_ids
    for baseline_id, binding in cost_by_id.items():
        assert binding.quote_components == semantic_by_id[baseline_id].quote_components
        assert all(
            isinstance(value, str) and Decimal(value) > 0 for value in binding.quote_components
        )

    channel_ids = {
        "BO0013",
        "BO0014",
        "BO0015",
        "BO0016",
        "BO0017",
        "BO0018",
        "BO0019",
        "BO0020",
        "BO0021",
        "BO0022",
        "BO0023",
        "BO0024",
        "BO0030",
        "BO0031",
        "BO0032",
        "BO0033",
        "BO0034",
    }
    assert channel_ids.isdisjoint(cost_by_id)
    assert channel_ids.isdisjoint(benchmark_by_id)
    assert channel_ids.isdisjoint(
        binding.baseline_id for binding in report.probability_snapshot.bindings
    )
    assert channel_ids.isdisjoint(
        binding.baseline_id for binding in report.rebate_schedule.bindings
    )
    assert sum(binding.included_in_active_cost_surface for binding in cost_by_id.values()) == 416
    assert report.cost_surface.active_quote_version_count == 1
    assert report.odds_space_benchmark.active_quote_version_count == 1
    catalog = load_play_catalog()
    raw_by_id = {entry["baseline_id"]: entry for entry in catalog["entries"]}
    diagnostic = compile_channel_metadata_diagnostic(registry, source_catalog=catalog)
    assert set(diagnostic.channel_baseline_ids) == channel_ids
    assert diagnostic.channel_record_hashes == {
        baseline_id: canonical_sha256(raw_by_id[baseline_id]) for baseline_id in sorted(channel_ids)
    }
    assert diagnostic.participates_in_f2_content_hash is False
    assert diagnostic.participates_in_f2_closure_status is False


def test_multi_payout_tiers_keep_their_settlement_semantics(report) -> None:
    cost_by_id = {binding.baseline_id: binding for binding in report.cost_surface.bindings}
    assert cost_by_id["BO0213"].quote_components == ("51.5", "35.5")
    assert cost_by_id["BO0216"].quote_components == ("126", "20.1")
    for baseline_id in ("BO0213", "BO0216"):
        binding = cost_by_id[baseline_id]
        payouts = binding.exact_cases[0].tier_payouts
        quote_payouts = [payout for payout in payouts if payout.payout_source == "QUOTE_COMPONENT"]
        assert tuple(payout.payout_component_index for payout in quote_payouts) == (0, 1)
        assert tuple(payout.unit_payout for payout in quote_payouts) == binding.quote_components


def test_event_payout_and_unit_cost_contract_is_exact(report) -> None:
    exact = [
        binding
        for binding in report.cost_surface.bindings
        if binding.representation == "EXACT_NUMERIC"
    ]
    assert len(exact) == 218
    for binding in exact:
        assert binding.principal_refund_on_normal_settlement is False
        assert binding.payout_contract == "HIT_Q_MISS_0_VOID_1_NO_EXTRA_NORMAL_PRINCIPAL"
        for case in binding.exact_cases:
            assert case.expected_unit_cost.as_fraction() == (
                case.quoted_expected_cost.as_fraction() + case.rebate_rate.as_fraction()
            )
            assert case.structural_unit_margin.as_fraction() == (
                1 - case.expected_unit_cost.as_fraction()
            )
            for payout in case.tier_payouts:
                if payout.terminal_role == "MISS":
                    assert payout.unit_payout == "0"
                elif payout.terminal_role == "VOID":
                    assert payout.unit_payout == "1"
                    assert payout.evidence_status == "RESEARCH_CONVENTION"
                    assert payout.convention_ref == "xinao-research-convention.void-refund-one.v1"
                else:
                    assert payout.payout_source == "QUOTE_COMPONENT"
                    assert payout.unit_payout in binding.quote_components
                    assert payout.evidence_status == "SEMANTIC_DEFINITION"
                    assert payout.convention_ref is None
    assert report.cost_surface.void_payout_scope == "ONLY_SEMANTICS_WITH_EXPLICIT_VOID_TIER"


def test_only_three_oral_scopes_apply_and_each_is_safely_capped(report) -> None:
    schedule = report.rebate_schedule
    assert len(schedule.scopes) == 3
    scopes = {scope.scope_id: scope for scope in schedule.scopes}
    special = scopes["oral-highest-tier.special-exact-a.v1"]
    one_zodiac = scopes["oral-highest-tier.one-zodiac-unified.v1"]
    three_in_three = scopes["oral-highest-tier.three-in-three.v1"]

    assert special.component_baseline_ids == ("BO0001",)
    assert special.candidate_rate.as_fraction() == Fraction(7, 200)
    assert special.safe_ceiling.as_fraction() == Fraction(7, 200)
    assert special.resolved_rate.as_fraction() == Fraction(7, 200)

    assert len(one_zodiac.component_baseline_ids) == 12
    assert one_zodiac.candidate_rate.as_fraction() == Fraction(1, 100)
    assert one_zodiac.safe_ceiling.as_fraction() == Fraction(120_683, 15_134_000)
    assert one_zodiac.resolved_rate.as_fraction() == one_zodiac.safe_ceiling.as_fraction()
    assert one_zodiac.resolution_status == "ACTIVE_CAPPED"

    assert three_in_three.component_baseline_ids == ("BO0215",)
    assert three_in_three.candidate_rate.as_fraction() == Fraction(31, 200)
    assert three_in_three.resolved_rate.as_fraction() == Fraction(31, 200)
    assert all(
        scope.resolved_rate.as_fraction() <= scope.safe_ceiling.as_fraction()
        for scope in schedule.scopes
    )

    bindings = {binding.baseline_id: binding for binding in schedule.bindings}
    assert bindings["BO0001"].evidence_status == "USER_ORAL_ASSUMPTION"
    assert bindings["BO0001"].quote_role == "ACTIVE_DEFAULT_QUOTE"
    assert "BO0013" not in bindings
    assert all(binding.actual_exposure_claimed is False for binding in bindings.values())


def test_formula_order_and_all_artifact_hashes_are_fresh_recompute_stable(report, registry) -> None:
    formula_ids = [formula.formula_id for formula in report.probability_snapshot.symbolic_formulas]
    assert formula_ids == sorted(formula_ids)
    second = compile_f2_artifacts(registry)
    assert second.content_hash == report.content_hash
    assert second.artifact_hashes == report.artifact_hashes
    assert [formula.content_hash for formula in second.probability_snapshot.symbolic_formulas] == [
        formula.content_hash for formula in report.probability_snapshot.symbolic_formulas
    ]

    artifacts = (
        (SettlementProbabilitySnapshotVersion, report.probability_snapshot),
        (RebateScheduleVersion, report.rebate_schedule),
        (SettlementCostSurfaceVersion, report.cost_surface),
        (OddsSpaceBenchmarkVersion, report.odds_space_benchmark),
        (SettlementCostCompileReport, report),
    )
    for model, artifact in artifacts:
        reloaded = model.model_validate(artifact.model_dump(mode="json"))
        assert reloaded.content_hash == artifact.content_hash


def test_report_is_honest_about_exact_numeric_and_symbolic_formulae(report) -> None:
    assert report.component_binding_count == 416
    assert report.active_quote_version_count == 1
    assert report.active_quote_component_count == 416
    assert report.exact_numeric_component_count == 218
    assert report.symbolic_formula_component_count == 198
    assert report.symbolic_selection_domain_formula_count == 15
    assert report.independent_atomic_ticket_binding_count == 37
    assert report.oral_assumption_scope_count == 3
    assert report.compile_status == "VERIFIED_IN_MEMORY"
    assert report.global_foundation_complete_claimed is False
    assert all(report.assertions.values())


def test_b_channel_quote_changes_only_the_non_gating_diagnostic(report) -> None:
    source_registry = compile_default_semantics_registry()
    catalog = deepcopy(load_play_catalog())
    source_diagnostic = compile_channel_metadata_diagnostic(
        source_registry,
        source_catalog=catalog,
    )
    for entry in catalog["entries"]:
        if entry["baseline_id"] == "BO0013":
            entry["baseline_odds_components"] = ["41.111"]
            break
    normalized = {key: value for key, value in catalog.items() if key != "content_hash"}
    normalized["entries"] = sorted(normalized["entries"], key=lambda row: row["baseline_id"])
    catalog["content_hash"] = canonical_sha256(normalized)

    changed_registry = compile_semantics_registry(catalog)
    manifest = compile_independent_selection_manifest(catalog)
    atomic = compile_atomic_ticket_bindings(catalog, manifest)
    changed = compile_f2_artifacts(changed_registry, atomic_ticket_bindings=atomic)
    changed_diagnostic = compile_channel_metadata_diagnostic(
        changed_registry,
        source_catalog=catalog,
    )

    assert changed.content_hash == report.content_hash
    assert changed.artifact_hashes == report.artifact_hashes
    assert changed.source_active_projection_hash == report.source_active_projection_hash
    assert changed.model_dump_json().encode("utf-8") == report.model_dump_json().encode("utf-8")
    assert canonical_sha256(changed.model_dump(mode="json")) == canonical_sha256(
        report.model_dump(mode="json")
    )
    assert changed_diagnostic.channel_metadata_digest != source_diagnostic.channel_metadata_digest
    assert changed_diagnostic.source_registry_hash == source_diagnostic.source_registry_hash
