from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation.f2_assertions import (
    F2_ASSERTION_PROFILE_HASH,
    F2_ASSERTION_PROFILE_REF,
    F2_ASSERTION_PROFILE_SOURCE_REF,
    F2_REQUIRED_ASSERTION_EXPECTATIONS,
    F2_REQUIRED_ASSERTION_IDS,
    F2AssertionReport,
    compile_f2_assertion_report,
)
from xinao.foundation.f2_compile import (
    atomic_ticket_projection_hash,
    compile_channel_metadata_diagnostic,
    compile_f2_artifacts,
)
from xinao.foundation.selection_manifest import (
    compile_atomic_ticket_bindings,
    compile_default_atomic_ticket_bindings,
    compile_independent_selection_manifest,
)
from xinao.foundation.semantics_registry import (
    DEFAULT_PLAY_CATALOG_PATH,
    compile_default_semantics_registry,
    compile_semantics_registry,
    load_play_catalog,
)

F2_FRESH_PROCESS_TIMEOUT_SECONDS = 180


@pytest.fixture(scope="module")
def registry():
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    return compile_default_semantics_registry()


@pytest.fixture(scope="module")
def atomic():
    return compile_default_atomic_ticket_bindings()


@pytest.fixture(scope="module")
def f2(registry, atomic):
    return compile_f2_artifacts(registry, atomic_ticket_bindings=atomic)


@pytest.fixture(scope="module")
def assertions(registry, atomic, f2) -> F2AssertionReport:
    return compile_f2_assertion_report(
        registry,
        f2,
        atomic_ticket_bindings=atomic,
    )


def test_versioned_assertion_profile_is_self_bound_without_an_archived_blueprint() -> None:
    assert F2_ASSERTION_PROFILE_REF == "xinao.f2_assertion_profile.v1"
    assert F2_ASSERTION_PROFILE_SOURCE_REF == (
        "current-formal-foundation-contract#B.IssuerSettlementCostSpaceFoundation"
    )
    assert len(F2_REQUIRED_ASSERTION_IDS) == 18
    assert canonical_sha256(
        {
            "profile_ref": F2_ASSERTION_PROFILE_REF,
            "source_ref": F2_ASSERTION_PROFILE_SOURCE_REF,
            "required_assertions": F2_REQUIRED_ASSERTION_EXPECTATIONS,
        }
    ) == F2_ASSERTION_PROFILE_HASH


def test_all_eighteen_assertions_are_recomputed_and_machine_verifiable(assertions) -> None:
    assert assertions.required_assertion_ids == F2_REQUIRED_ASSERTION_IDS
    assert len(assertions.assertion_results) == 18
    assert assertions.status == "VERIFIED"
    assert assertions.all_required_assertions_pass is True
    assert all(result.status == "PASS" for result in assertions.assertion_results)
    assert assertions.assertion_result_hashes == {
        result.assertion_id: result.content_hash for result in assertions.assertion_results
    }

    by_id = {result.assertion_id: result for result in assertions.assertion_results}
    assert by_id["all_active_settlement_objects_covered"].actual_value == 416
    assert type(by_id["all_active_settlement_objects_covered"].actual_value) is int
    for assertion_id in (
        "normal_principal_refund_eq",
        "actual_exposure_or_realized_profit_claimed",
    ):
        assert by_id[assertion_id].expected_value is False
        assert by_id[assertion_id].actual_value is False
        assert by_id[assertion_id].status == "PASS"


def test_independent_ticket_fixtures_are_bound_without_component_ticket_fabrication(
    assertions, f2, atomic
) -> None:
    assert assertions.source_atomic_ticket_projection_hash == atomic_ticket_projection_hash(atomic)
    assert len(f2.probability_snapshot.atomic_ticket_bindings) == 37
    assert (
        sum(
            binding.representation == "EXACT_NUMERIC"
            for binding in f2.probability_snapshot.atomic_ticket_bindings
        )
        == 22
    )
    assert (
        sum(
            binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
            for binding in f2.probability_snapshot.atomic_ticket_bindings
        )
        == 15
    )

    grouped = [
        binding
        for binding in f2.probability_snapshot.bindings
        if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
    ]
    assert len(grouped) == 198
    assert all(not binding.exact_cases for binding in grouped)
    assert all(
        binding.ticket_identity == "GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET" for binding in grouped
    )
    result = next(
        item
        for item in assertions.assertion_results
        if item.assertion_id == "combinatorial_probability_counts_match_independent_fixtures"
    )
    assert result.actual_value is True
    assert result.metrics["atomic_ticket_binding_count"] == 37
    assert result.metrics["symbolic_ticket_domain_count"] == 15


def test_probability_cost_and_rebate_assertions_are_computed(assertions) -> None:
    by_id = {result.assertion_id: result for result in assertions.assertion_results}
    checked = (
        "event_unit_cost_surface_functionally_complete",
        "turnover_rebate_materialized",
        "rebate_schedule_covers_all_active_settlement_objects",
        "rebate_rate_lte_implied_max",
        "expected_unit_cost_recomputed_from_payout_and_rebate",
        "all_intra_quote_payout_tiers_preserved",
        "tier_probabilities_gte_zero",
        "tier_probabilities_lte_one",
        "terminal_outcome_probabilities_sum_to_one",
        "hit_miss_void_partition_complete_and_mutually_exclusive",
    )
    assert all(by_id[assertion_id].actual_value is True for assertion_id in checked)
    assert by_id["turnover_rebate_materialized"].metrics["oral_rebate_scope_count"] == 3
    assert by_id["tier_probabilities_gte_zero"].metrics["numeric_probability_tier_count"] > 0
    metrics = by_id["event_unit_cost_surface_functionally_complete"].metrics
    assert metrics["active_quote_version_count"] == 1
    assert metrics["active_settlement_object_count"] == 416
    assert metrics["intra_quote_multi_payout_component_count"] == 2


def test_channel_b_rows_are_diagnostic_only_and_never_active_f2_bindings(f2, registry) -> None:
    costs = {binding.baseline_id: binding for binding in f2.cost_surface.bindings}
    rebates = {binding.baseline_id: binding for binding in f2.rebate_schedule.bindings}
    benchmarks = {binding.baseline_id: binding for binding in f2.odds_space_benchmark.bindings}
    diagnostic = compile_channel_metadata_diagnostic(
        registry,
        source_catalog=load_play_catalog(),
    )
    channel_ids = set(diagnostic.channel_baseline_ids)
    assert len(channel_ids) == 17
    assert len(costs) == len(rebates) == len(benchmarks) == 416
    assert channel_ids.isdisjoint(costs)
    assert channel_ids.isdisjoint(rebates)
    assert channel_ids.isdisjoint(benchmarks)
    assert diagnostic.participates_in_f2_closure_status is False
    for baseline_id in channel_ids:
        assert baseline_id in diagnostic.channel_record_hashes


def test_fresh_and_reordered_recompiles_match_and_report_hash_reloads(assertions, f2) -> None:
    assert assertions.fresh_recompute_hash_matches is True
    assert assertions.reordered_input_hash_matches is True
    assert assertions.fresh_recomputed_f2_hash == f2.content_hash
    assert assertions.reordered_input_f2_hash == f2.content_hash
    replay = next(
        result
        for result in assertions.assertion_results
        if result.assertion_id == "formula_replay_hash_stable"
    )
    assert replay.actual_value is True
    reloaded = F2AssertionReport.model_validate(assertions.model_dump(mode="json"))
    assert reloaded.content_hash == assertions.content_hash


def test_assertion_report_is_fresh_process_recomputable(assertions) -> None:
    script = (
        "from xinao.foundation.semantics_registry import "
        "compile_default_semantics_registry; "
        "from xinao.foundation.f2_assertions import compile_f2_assertion_report; "
        "print(compile_f2_assertion_report(compile_default_semantics_registry()).content_hash)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        check=True,
        capture_output=True,
        text=True,
        # One full 265,997-ticket symbolic proof is about 100 seconds on the
        # canonical Windows host.  Keep the check bounded without truncating
        # a healthy recomputation before it can emit its content hash.
        timeout=F2_FRESH_PROCESS_TIMEOUT_SECONDS,
    )
    assert completed.stdout.strip() == assertions.content_hash


def test_tampered_assertion_value_cannot_reuse_the_recorded_report_hash(assertions) -> None:
    payload = assertions.model_dump(mode="json")
    payload["assertion_results"][0]["actual_value"] = False
    with pytest.raises(ValueError):
        F2AssertionReport.model_validate(payload)


def test_b_channel_quote_change_cannot_change_f2_assertion_hash_or_status(assertions) -> None:
    catalog = deepcopy(load_play_catalog())
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

    changed = compile_f2_assertion_report(
        changed_registry,
        atomic_ticket_bindings=atomic,
    )

    assert changed.status == "VERIFIED"
    assert changed.content_hash == assertions.content_hash
    assert changed.source_f2_report_hash == assertions.source_f2_report_hash
    assert changed.model_dump_json().encode("utf-8") == assertions.model_dump_json().encode("utf-8")
