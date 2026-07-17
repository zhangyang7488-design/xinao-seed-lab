"""Independent machine-checkable assertions over compiled F2 artifacts.

This verifier does not trust ``SettlementCostCompileReport.assertions``.  It
recomputes the versioned F2 implementation-profile predicates from the nested probability,
rebate, cost, benchmark, registry, and independent atomic-ticket artifacts.
Grouped linked/parlay catalog rows are accepted only as components of complete
symbolic ticket domains; they are never promoted to independently settleable
tickets by this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256
from xinao.foundation.f2_compile import (
    SYMBOLIC_COST_EVALUATOR_CONTRACT,
    OddsSpaceBenchmarkVersion,
    RebateScheduleVersion,
    SettlementCostCompileReport,
    SettlementCostSurfaceVersion,
    SettlementProbabilitySnapshotVersion,
    active_registry_projection_hash,
    atomic_ticket_projection_hash,
    compile_f2_artifacts,
)
from xinao.foundation.selection_manifest import (
    AtomicTicketBindingVersion,
    compile_atomic_ticket_bindings,
    compile_default_atomic_ticket_bindings,
    compile_independent_selection_manifest,
)
from xinao.foundation.semantics_registry import (
    FoundationSemanticsRegistry,
    compile_semantics_registry,
    load_play_catalog,
)

F2_ASSERTION_PROFILE_REF = "xinao.f2_assertion_profile.v1"
F2_ASSERTION_PROFILE_SOURCE_REF = (
    "current-formal-foundation-contract#B.IssuerSettlementCostSpaceFoundation"
)
F2_REQUIRED_ASSERTIONS: tuple[tuple[str, bool | int], ...] = (
    (
        "coverage_key_set_equals_expected_outcome_x_active_settlement_object_x_payout_tier",
        True,
    ),
    ("event_unit_cost_surface_functionally_complete", True),
    ("turnover_rebate_materialized", True),
    ("rebate_schedule_covers_all_active_settlement_objects", True),
    ("rebate_rate_lte_implied_max", True),
    ("expected_unit_cost_recomputed_from_payout_and_rebate", True),
    ("all_active_settlement_objects_covered", 416),
    ("all_intra_quote_payout_tiers_preserved", True),
    ("normal_principal_refund_eq", False),
    ("tier_probabilities_gte_zero", True),
    ("tier_probabilities_lte_one", True),
    ("terminal_outcome_probabilities_sum_to_one", True),
    ("hit_miss_void_partition_complete_and_mutually_exclusive", True),
    ("combinatorial_probability_counts_match_independent_fixtures", True),
    ("historical_replay_not_probability_definition", True),
    ("formula_replay_hash_stable", True),
    ("all_compiler_bindings_nonempty_and_hash_bound", True),
    ("actual_exposure_or_realized_profit_claimed", False),
)
F2_REQUIRED_ASSERTION_IDS = tuple(item[0] for item in F2_REQUIRED_ASSERTIONS)
F2_REQUIRED_ASSERTION_EXPECTATIONS = dict(F2_REQUIRED_ASSERTIONS)
F2_ASSERTION_PROFILE_HASH = canonical_sha256(
    {
        "profile_ref": F2_ASSERTION_PROFILE_REF,
        "source_ref": F2_ASSERTION_PROFILE_SOURCE_REF,
        "required_assertions": dict(F2_REQUIRED_ASSERTIONS),
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContentHashedModel(_FrozenModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> _ContentHashedModel:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_sha256(payload) != self.content_hash:
            raise ValueError("content_hash does not bind canonical assertion content")
        return self


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    draft = model.model_construct(**dict(payload), content_hash="0" * 64)
    body = draft.model_dump(mode="json", exclude={"content_hash"})
    body["content_hash"] = canonical_sha256(body)
    return model.model_validate(body)


class F2AssertionResult(_ContentHashedModel):
    schema_version: Literal["xinao.f2_assertion_result.v1"] = "xinao.f2_assertion_result.v1"
    assertion_id: str
    expected_value: bool | int
    actual_value: bool | int
    status: Literal["PASS", "FAIL"]
    calculation_ref: str
    source_hashes: dict[str, str]
    metrics: dict[str, int]

    @model_validator(mode="after")
    def validate_verdict(self) -> F2AssertionResult:
        same_type = type(self.actual_value) is type(self.expected_value)
        passed = same_type and self.actual_value == self.expected_value
        if self.status != ("PASS" if passed else "FAIL"):
            raise ValueError("assertion status does not match actual and expected values")
        return self


class F2AssertionReport(_ContentHashedModel):
    schema_version: Literal["xinao.f2_assertion_report.v1"] = "xinao.f2_assertion_report.v1"
    report_ref: Literal["xinao.f2_assertion_report.v1"] = "xinao.f2_assertion_report.v1"
    assertion_profile_ref: Literal["xinao.f2_assertion_profile.v1"] = F2_ASSERTION_PROFILE_REF
    assertion_profile_source_ref: Literal[
        "current-formal-foundation-contract#B.IssuerSettlementCostSpaceFoundation"
    ] = F2_ASSERTION_PROFILE_SOURCE_REF
    assertion_profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_active_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_f2_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_atomic_ticket_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_hashes: dict[str, str]
    required_assertion_count: Literal[18] = 18
    required_assertion_ids: tuple[str, ...]
    assertion_results: tuple[F2AssertionResult, ...]
    assertion_result_hashes: dict[str, str]
    fresh_recomputed_f2_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reordered_input_f2_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fresh_recompute_hash_matches: bool
    reordered_input_hash_matches: bool
    all_required_assertions_pass: bool
    status: Literal["VERIFIED", "PARTIAL"]
    global_foundation_complete_claimed: Literal[False] = False

    @model_validator(mode="after")
    def validate_report(self) -> F2AssertionReport:
        if self.assertion_profile_hash != F2_ASSERTION_PROFILE_HASH:
            raise ValueError("F2 assertion profile hash drifted")
        if self.required_assertion_ids != F2_REQUIRED_ASSERTION_IDS:
            raise ValueError("F2 assertion id set or order drifted from the implementation profile")
        if len(self.assertion_results) != 18:
            raise ValueError("F2 assertion report must contain exactly 18 results")
        ids = tuple(result.assertion_id for result in self.assertion_results)
        if ids != self.required_assertion_ids:
            raise ValueError("F2 assertion results do not follow the required id order")
        expected_hashes = {
            result.assertion_id: result.content_hash for result in self.assertion_results
        }
        if self.assertion_result_hashes != expected_hashes:
            raise ValueError("F2 assertion result hash index is inconsistent")
        passed = all(result.status == "PASS" for result in self.assertion_results)
        if self.all_required_assertions_pass != passed:
            raise ValueError("all_required_assertions_pass is inconsistent")
        if self.status != ("VERIFIED" if passed else "PARTIAL"):
            raise ValueError("F2 assertion report status is inconsistent")
        return self


def _result(
    assertion_id: str,
    actual: bool | int,
    *,
    calculation_ref: str,
    source_hashes: Mapping[str, str],
    metrics: Mapping[str, int] | None = None,
) -> F2AssertionResult:
    expected = F2_REQUIRED_ASSERTION_EXPECTATIONS[assertion_id]
    passed = type(actual) is type(expected) and actual == expected
    return _with_hash(
        F2AssertionResult,
        {
            "assertion_id": assertion_id,
            "expected_value": expected,
            "actual_value": actual,
            "status": "PASS" if passed else "FAIL",
            "calculation_ref": calculation_ref,
            "source_hashes": dict(sorted(source_hashes.items())),
            "metrics": dict(sorted((metrics or {}).items())),
        },
    )


def _exact_probability_cases(
    report: SettlementCostCompileReport,
) -> tuple[Any, ...]:
    return tuple(
        case
        for binding in report.probability_snapshot.bindings
        if binding.representation == "EXACT_NUMERIC"
        for case in binding.exact_cases
    )


def _symbolic_probability_contract_complete(
    report: SettlementCostCompileReport,
) -> bool:
    probability = report.probability_snapshot
    formula_by_id = {formula.formula_id: formula for formula in probability.symbolic_formulas}
    ticket_by_id = {ticket.binding_id: ticket for ticket in probability.atomic_ticket_bindings}
    grouped = [
        binding
        for binding in probability.bindings
        if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
    ]
    return (
        len(grouped) == 198
        and len(formula_by_id) == 15
        and all(
            not binding.exact_cases
            and binding.ticket_identity == "GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET"
            and binding.symbolic_formula_id in formula_by_id
            and binding.independent_atomic_ticket_binding_id in ticket_by_id
            for binding in grouped
        )
        and all(
            formula.component_rows_are_independent_tickets is False
            and formula.miss_formula == "P_MISS=1-P_HIT"
            and formula.materialized_atomic_ticket_count == 0
            and formula.surface_proof.evaluator_ref == "xinao-symbolic-ticket-evaluator.v1"
            and formula.surface_proof.evaluated_atomic_ticket_count
            == formula.exact_atomic_selection_count
            and formula.surface_proof.unique_atomic_ticket_count
            == formula.exact_atomic_selection_count
            and formula.surface_proof.probability_vector_count
            == formula.exact_atomic_selection_count
            and formula.surface_proof.invalid_ticket_count == 0
            and formula.surface_proof.probabilities_nonnegative is True
            and formula.surface_proof.probabilities_at_most_one is True
            and formula.surface_proof.hit_miss_partition_complete is True
            and formula.surface_proof.expected_cost_nonnegative is True
            and formula.surface_proof.materialized_atomic_ticket_count == 0
            for formula in formula_by_id.values()
        )
        and sum(
            formula.surface_proof.evaluated_atomic_ticket_count
            for formula in formula_by_id.values()
        )
        == 265_997
        and sum(
            formula.surface_proof.probability_equivalence_class_count
            for formula in formula_by_id.values()
        )
        == 1_736
        and sum(
            ticket.representation == "SYMBOLIC_DOMAIN_FORMULA" for ticket in ticket_by_id.values()
        )
        == 15
    )


def _coverage_check(
    registry: FoundationSemanticsRegistry,
    report: SettlementCostCompileReport,
) -> tuple[bool, dict[str, int]]:
    expected_ids = {
        record.baseline_id
        for record in registry.rule_semantic_map.records
        if record.catalog.panel != "B"
    }
    probability_ids = {item.baseline_id for item in report.probability_snapshot.bindings}
    rebate_ids = {item.baseline_id for item in report.rebate_schedule.bindings}
    cost_ids = {item.baseline_id for item in report.cost_surface.bindings}
    benchmark_ids = {item.baseline_id for item in report.odds_space_benchmark.bindings}
    exact_case_ids = {
        (binding.baseline_id, case.case_id)
        for binding in report.probability_snapshot.bindings
        if binding.representation == "EXACT_NUMERIC"
        for case in binding.exact_cases
    }
    cost_case_ids = {
        (binding.baseline_id, case.case_id)
        for binding in report.cost_surface.bindings
        if binding.representation == "EXACT_NUMERIC"
        for case in binding.exact_cases
    }
    symbolic_probability = {
        (binding.baseline_id, binding.symbolic_formula_id)
        for binding in report.probability_snapshot.bindings
        if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
    }
    symbolic_cost = {
        (binding.baseline_id, binding.symbolic_formula_id)
        for binding in report.cost_surface.bindings
        if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
    }
    covered = (
        len(expected_ids) == 416
        and expected_ids == probability_ids == rebate_ids == cost_ids == benchmark_ids
        and exact_case_ids == cost_case_ids
        and symbolic_probability == symbolic_cost
        and _symbolic_probability_contract_complete(report)
    )
    return covered, {
        "active_baseline_count": len(expected_ids),
        "active_settlement_object_count": len(cost_ids),
        "exact_equivalence_case_count": len(exact_case_ids),
        "symbolic_component_count": len(symbolic_probability),
        "symbolic_ticket_domain_count": len(report.probability_snapshot.symbolic_formulas),
        "symbolic_atomic_ticket_count": sum(
            formula.surface_proof.evaluated_atomic_ticket_count
            for formula in report.probability_snapshot.symbolic_formulas
        ),
        "symbolic_probability_equivalence_class_count": sum(
            formula.surface_proof.probability_equivalence_class_count
            for formula in report.probability_snapshot.symbolic_formulas
        ),
    }


def _event_cost_materialized(report: SettlementCostCompileReport) -> bool:
    probability_by_id = {
        binding.baseline_id: binding for binding in report.probability_snapshot.bindings
    }
    formula_by_id = {
        formula.formula_id: formula for formula in report.probability_snapshot.symbolic_formulas
    }
    for cost in report.cost_surface.bindings:
        probability = probability_by_id[cost.baseline_id]
        if cost.representation == "SYMBOLIC_DOMAIN_FORMULA":
            formula = formula_by_id.get(str(cost.symbolic_formula_id))
            if (
                probability.representation != "SYMBOLIC_DOMAIN_FORMULA"
                or cost.symbolic_formula_id != probability.symbolic_formula_id
                or cost.symbolic_cost_formula != SYMBOLIC_COST_EVALUATOR_CONTRACT
                or formula is None
                or cost.symbolic_surface_proof_hash != formula.surface_proof.content_hash
                or formula.surface_proof.expected_cost_nonnegative is not True
                or cost.exact_cases
            ):
                return False
            continue
        probability_cases = {case.case_id: case for case in probability.exact_cases}
        for case in cost.exact_cases:
            source = probability_cases.get(case.case_id)
            if source is None:
                return False
            probability_tiers = {tier.tier_id for tier in source.tier_probabilities}
            payout_tiers = {tier.tier_id for tier in case.tier_payouts}
            if probability_tiers != payout_tiers:
                return False
            for payout in case.tier_payouts:
                if payout.terminal_role == "MISS" and payout.unit_payout != "0":
                    return False
                if payout.terminal_role == "VOID" and payout.unit_payout != "1":
                    return False
                if payout.terminal_role == "HIT" and payout.payout_source != "QUOTE_COMPONENT":
                    return False
    return True


def _rebates_materialized(report: SettlementCostCompileReport) -> bool:
    rebate_by_id = {item.baseline_id: item for item in report.rebate_schedule.bindings}
    if len(rebate_by_id) != 416:
        return False
    for cost in report.cost_surface.bindings:
        rebate = rebate_by_id.get(cost.baseline_id)
        if rebate is None:
            return False
        if cost.representation == "EXACT_NUMERIC":
            if any(case.rebate_rate != rebate.resolved_rate for case in cost.exact_cases):
                return False
        elif rebate.resolved_rate.as_fraction() != 0:
            return False
    return True


def _rebate_ceiling_holds(report: SettlementCostCompileReport) -> bool:
    if any(
        scope.resolved_rate.as_fraction() > scope.safe_ceiling.as_fraction()
        for scope in report.rebate_schedule.scopes
    ):
        return False
    for binding in report.cost_surface.bindings:
        if binding.representation == "EXACT_NUMERIC":
            for case in binding.exact_cases:
                implied_max = 1 - case.quoted_expected_cost.as_fraction()
                if case.rebate_rate.as_fraction() > implied_max:
                    return False
        else:
            rebate = next(
                item
                for item in report.rebate_schedule.bindings
                if item.baseline_id == binding.baseline_id
            )
            if (
                rebate.resolved_rate.as_fraction() != 0
                or rebate.evidence_status != "UNCONFIRMED_NO_REBATE"
            ):
                return False
    return True


def _cost_identities_hold(report: SettlementCostCompileReport) -> bool:
    formula_by_id = {
        formula.formula_id: formula for formula in report.probability_snapshot.symbolic_formulas
    }
    for binding in report.cost_surface.bindings:
        if binding.representation == "SYMBOLIC_DOMAIN_FORMULA":
            formula = formula_by_id.get(str(binding.symbolic_formula_id))
            if (
                binding.symbolic_cost_formula != SYMBOLIC_COST_EVALUATOR_CONTRACT
                or formula is None
                or binding.symbolic_surface_proof_hash != formula.surface_proof.content_hash
                or formula.surface_proof.expected_cost_nonnegative is not True
            ):
                return False
            continue
        for case in binding.exact_cases:
            quoted = case.quoted_expected_cost.as_fraction()
            rebate = case.rebate_rate.as_fraction()
            expected = case.expected_unit_cost.as_fraction()
            margin = case.structural_unit_margin.as_fraction()
            if expected != quoted + rebate or margin != 1 - expected:
                return False
    return True


def _intra_quote_payout_tiers_preserved(
    report: SettlementCostCompileReport,
) -> tuple[bool, dict[str, int]]:
    exact_bindings = [
        binding
        for binding in report.cost_surface.bindings
        if binding.representation == "EXACT_NUMERIC"
    ]
    payout_count = 0
    multi_quote_count = 0
    for binding in exact_bindings:
        if len(binding.quote_components) > 1:
            multi_quote_count += 1
        expected_indices = set(range(len(binding.quote_components)))
        for case in binding.exact_cases:
            quote_payouts = [
                payout for payout in case.tier_payouts if payout.payout_source == "QUOTE_COMPONENT"
            ]
            payout_count += len(quote_payouts)
            actual_indices = {payout.payout_component_index for payout in quote_payouts}
            if actual_indices != expected_indices or any(
                payout.payout_component_index is None
                or payout.unit_payout != binding.quote_components[payout.payout_component_index]
                for payout in quote_payouts
            ):
                return False, {
                    "intra_quote_multi_payout_component_count": multi_quote_count,
                    "intra_quote_payout_tier_count": payout_count,
                }
    return True, {
        "intra_quote_multi_payout_component_count": multi_quote_count,
        "intra_quote_payout_tier_count": payout_count,
    }


def _probability_checks(report: SettlementCostCompileReport) -> dict[str, bool]:
    cases = _exact_probability_cases(report)
    probabilities = [
        tier.probability.as_fraction() for case in cases for tier in case.tier_probabilities
    ]
    symbolic_complete = _symbolic_probability_contract_complete(report)
    symbolic_proofs = [
        formula.surface_proof for formula in report.probability_snapshot.symbolic_formulas
    ]
    nonnegative = (
        all(value >= 0 for value in probabilities)
        and all(proof.probabilities_nonnegative for proof in symbolic_proofs)
        and symbolic_complete
    )
    at_most_one = (
        all(value <= 1 for value in probabilities)
        and all(proof.probabilities_at_most_one for proof in symbolic_proofs)
        and symbolic_complete
    )
    normalized = (
        all(
            sum(
                (tier.probability.as_fraction() for tier in case.tier_probabilities),
                start=Fraction(0),
            )
            == 1
            for case in cases
        )
        and all(proof.hit_miss_partition_complete for proof in symbolic_proofs)
        and symbolic_complete
    )
    partition = (
        all(
            len({tier.tier_id for tier in case.tier_probabilities}) == len(case.tier_probabilities)
            and {tier.terminal_role for tier in case.tier_probabilities} >= {"HIT", "MISS"}
            for case in cases
        )
        and normalized
    )
    return {
        "nonnegative": nonnegative,
        "at_most_one": at_most_one,
        "normalized": normalized,
        "partition": partition,
        "numeric_tier_count": len(probabilities),
    }


def _independent_fixture_check(
    report: SettlementCostCompileReport,
    independent: AtomicTicketBindingVersion,
) -> bool:
    snapshot = report.probability_snapshot
    if snapshot.source_atomic_ticket_projection_hash != atomic_ticket_projection_hash(independent):
        return False
    expected = {binding.binding_id: binding for binding in independent.bindings}
    observed = {binding.binding_id: binding for binding in snapshot.atomic_ticket_bindings}
    if len(expected) != 37 or set(expected) != set(observed):
        return False
    formula_by_id = {formula.formula_id: formula for formula in snapshot.symbolic_formulas}
    for binding_id, source in expected.items():
        projection = observed[binding_id]
        if (
            projection.independent_binding_hash != source.content_hash
            or projection.selection_domain_spec_id != source.domain_spec_id
            or projection.family_id != source.family_id
            or projection.component_baseline_ids != source.component_baseline_ids
            or projection.exact_atomic_ticket_count != source.exact_atomic_ticket_count
            or projection.quote_aggregation_ref != source.quote_aggregation_ref
        ):
            return False
        if projection.representation == "SYMBOLIC_DOMAIN_FORMULA":
            formula = formula_by_id.get(str(projection.symbolic_formula_id))
            if (
                formula is None
                or formula.independent_atomic_ticket_binding_id != source.binding_id
                or formula.independent_atomic_ticket_binding_hash != source.content_hash
            ):
                return False
    return sum(item.exact_atomic_ticket_count for item in observed.values()) == (
        independent.exact_atomic_ticket_count
    )


def _historical_replay_is_not_probability_definition(
    probability: SettlementProbabilitySnapshotVersion,
) -> bool:
    prohibited = ("historical", "history", "replay", "empirical-frequency")
    refs = [binding.probability_formula_ref for binding in probability.bindings]
    refs.extend(
        ref for formula in probability.symbolic_formulas for ref in formula.probability_formula_refs
    )
    return all(not any(token in ref.lower() for token in prohibited) for ref in refs) and not any(
        token in field.lower()
        for field in probability.__class__.model_fields
        for token in ("history", "dataset", "replay")
    )


def _all_hash_bindings_hold(
    registry: FoundationSemanticsRegistry,
    report: SettlementCostCompileReport,
) -> bool:
    artifacts: tuple[tuple[type[BaseModel], BaseModel], ...] = (
        (SettlementProbabilitySnapshotVersion, report.probability_snapshot),
        (RebateScheduleVersion, report.rebate_schedule),
        (SettlementCostSurfaceVersion, report.cost_surface),
        (OddsSpaceBenchmarkVersion, report.odds_space_benchmark),
        (SettlementCostCompileReport, report),
    )
    try:
        for model, artifact in artifacts:
            model.model_validate(artifact.model_dump(mode="json"))
    except ValueError:
        return False
    expected_hashes = {
        "SettlementProbabilitySnapshotVersion": report.probability_snapshot.content_hash,
        "RebateScheduleVersion": report.rebate_schedule.content_hash,
        "SettlementCostSurfaceVersion": report.cost_surface.content_hash,
        "OddsSpaceBenchmarkVersion": report.odds_space_benchmark.content_hash,
    }
    return (
        report.artifact_hashes == expected_hashes
        and report.source_active_projection_hash == active_registry_projection_hash(registry)
        and report.probability_snapshot.source_active_projection_hash
        == active_registry_projection_hash(registry)
        and report.rebate_schedule.probability_snapshot_hash
        == report.probability_snapshot.content_hash
        and report.cost_surface.probability_snapshot_hash
        == report.probability_snapshot.content_hash
        and report.cost_surface.rebate_schedule_hash == report.rebate_schedule.content_hash
        and report.odds_space_benchmark.source_cost_surface_hash == report.cost_surface.content_hash
    )


def _reordered_f2_report() -> SettlementCostCompileReport:
    catalog = load_play_catalog()
    reordered = dict(catalog)
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise TypeError("play catalog entries must be a list")
    reordered["entries"] = list(reversed(entries))
    registry = compile_semantics_registry(reordered)
    manifest = compile_independent_selection_manifest(reordered)
    atomic = compile_atomic_ticket_bindings(reordered, manifest)
    return compile_f2_artifacts(registry, atomic_ticket_bindings=atomic)


def compile_f2_assertion_report(
    registry: FoundationSemanticsRegistry,
    f2_report: SettlementCostCompileReport | None = None,
    *,
    atomic_ticket_bindings: AtomicTicketBindingVersion | None = None,
) -> F2AssertionReport:
    """Recompute all eighteen versioned F2 implementation-profile assertions."""

    if not isinstance(registry, FoundationSemanticsRegistry):
        raise TypeError("registry must be FoundationSemanticsRegistry")
    independent = atomic_ticket_bindings or compile_default_atomic_ticket_bindings()
    if not isinstance(independent, AtomicTicketBindingVersion):
        raise TypeError("atomic_ticket_bindings must be AtomicTicketBindingVersion")
    source = f2_report or compile_f2_artifacts(
        registry,
        atomic_ticket_bindings=independent,
    )
    if not isinstance(source, SettlementCostCompileReport):
        raise TypeError("f2_report must be SettlementCostCompileReport")
    SettlementCostCompileReport.model_validate(source.model_dump(mode="json"))
    if (
        source.probability_snapshot.source_atomic_ticket_projection_hash
        != atomic_ticket_projection_hash(independent)
    ):
        raise ValueError("F2 report and independent atomic ticket version disagree")

    fresh = compile_f2_artifacts(registry, atomic_ticket_bindings=independent)
    reordered = _reordered_f2_report()
    fresh_matches = fresh.content_hash == source.content_hash
    reordered_matches = reordered.content_hash == source.content_hash

    source_hashes = {
        "active_registry_projection": active_registry_projection_hash(registry),
        "atomic_ticket_projection": atomic_ticket_projection_hash(independent),
        "cost_surface": source.cost_surface.content_hash,
        "f2_report": source.content_hash,
        "probability_snapshot": source.probability_snapshot.content_hash,
        "rebate_schedule": source.rebate_schedule.content_hash,
    }
    coverage, coverage_metrics = _coverage_check(registry, source)
    probability_checks = _probability_checks(source)
    rebate_ids = {binding.baseline_id for binding in source.rebate_schedule.bindings}
    cost_ids = {binding.baseline_id for binding in source.cost_surface.bindings}
    active_cost_ids = {
        binding.baseline_id
        for binding in source.cost_surface.bindings
        if binding.included_in_active_cost_surface
    }
    active_settlement_object_count = len(active_cost_ids)
    principal_refund_actual = any(
        binding.principal_refund_on_normal_settlement for binding in source.cost_surface.bindings
    )
    exposure_claim_actual = any(
        scope.actual_exposure_claimed for scope in source.rebate_schedule.scopes
    ) or any(binding.actual_exposure_claimed for binding in source.rebate_schedule.bindings)
    historical_ok = _historical_replay_is_not_probability_definition(source.probability_snapshot)
    fixture_ok = _independent_fixture_check(source, independent)
    hash_bindings_ok = _all_hash_bindings_hold(registry, source)
    event_cost_ok = _event_cost_materialized(source)
    turnover_ok = _rebates_materialized(source)
    rebate_by_id = {binding.baseline_id: binding for binding in source.rebate_schedule.bindings}
    rebate_coverage = (
        rebate_ids == cost_ids
        and len(rebate_ids) == 416
        and len(active_cost_ids) == 416
        and source.rebate_schedule.active_quote_version_count == 1
        and source.cost_surface.active_quote_version_count == 1
        and source.odds_space_benchmark.active_quote_version_count == 1
        and all(
            rebate_by_id[baseline_id].quote_role == "ACTIVE_DEFAULT_QUOTE"
            for baseline_id in active_cost_ids
        )
    )
    rebate_ceiling = _rebate_ceiling_holds(source)
    cost_identity = _cost_identities_hold(source)
    intra_quote_tiers, intra_quote_metrics = _intra_quote_payout_tiers_preserved(source)
    formula_replay = fresh_matches and reordered_matches

    actuals: dict[str, bool | int] = {
        "coverage_key_set_equals_expected_outcome_x_active_settlement_object_x_payout_tier": (
            coverage
        ),
        "event_unit_cost_surface_functionally_complete": event_cost_ok,
        "turnover_rebate_materialized": turnover_ok,
        "rebate_schedule_covers_all_active_settlement_objects": rebate_coverage,
        "rebate_rate_lte_implied_max": rebate_ceiling,
        "expected_unit_cost_recomputed_from_payout_and_rebate": cost_identity,
        "all_active_settlement_objects_covered": active_settlement_object_count,
        "all_intra_quote_payout_tiers_preserved": intra_quote_tiers,
        "normal_principal_refund_eq": principal_refund_actual,
        "tier_probabilities_gte_zero": probability_checks["nonnegative"],
        "tier_probabilities_lte_one": probability_checks["at_most_one"],
        "terminal_outcome_probabilities_sum_to_one": probability_checks["normalized"],
        "hit_miss_void_partition_complete_and_mutually_exclusive": probability_checks["partition"],
        "combinatorial_probability_counts_match_independent_fixtures": fixture_ok,
        "historical_replay_not_probability_definition": historical_ok,
        "formula_replay_hash_stable": formula_replay,
        "all_compiler_bindings_nonempty_and_hash_bound": hash_bindings_ok,
        "actual_exposure_or_realized_profit_claimed": exposure_claim_actual,
    }
    calculation_refs = {
        "coverage_key_set_equals_expected_outcome_x_active_settlement_object_x_payout_tier": (
            "f2-assertion.active-quote-coverage-equivalence-keys.v1"
        ),
        "event_unit_cost_surface_functionally_complete": (
            "f2-assertion.event-payout-or-symbolic-ticket.v1"
        ),
        "turnover_rebate_materialized": "f2-assertion.rebate-binding-to-cost.v1",
        "rebate_schedule_covers_all_active_settlement_objects": (
            "f2-assertion.rebate-active-quote-keyset.v1"
        ),
        "rebate_rate_lte_implied_max": "f2-assertion.safe-rebate-ceiling.v1",
        "expected_unit_cost_recomputed_from_payout_and_rebate": (
            "f2-assertion.unit-cost-identities.v1"
        ),
        "all_active_settlement_objects_covered": (
            "f2-assertion.active-settlement-object-keyset.v1"
        ),
        "all_intra_quote_payout_tiers_preserved": (
            "f2-assertion.same-active-quote-payout-component-index.v1"
        ),
        "normal_principal_refund_eq": "f2-assertion.normal-principal-any.v1",
        "tier_probabilities_gte_zero": "f2-assertion.exact-bounds-plus-symbolic-contract.v1",
        "tier_probabilities_lte_one": "f2-assertion.exact-bounds-plus-symbolic-contract.v1",
        "terminal_outcome_probabilities_sum_to_one": (
            "f2-assertion.exact-normalization-plus-symbolic-complement.v1"
        ),
        "hit_miss_void_partition_complete_and_mutually_exclusive": (
            "f2-assertion.unique-terminal-tier-partition.v1"
        ),
        "combinatorial_probability_counts_match_independent_fixtures": (
            "f2-assertion.atomic-ticket-binding-version-crosscheck.v1"
        ),
        "historical_replay_not_probability_definition": (
            "f2-assertion.probability-reference-provenance.v1"
        ),
        "formula_replay_hash_stable": "f2-assertion.fresh-and-reordered-recompile.v1",
        "all_compiler_bindings_nonempty_and_hash_bound": (
            "f2-assertion.artifact-lineage-and-self-hash.v1"
        ),
        "actual_exposure_or_realized_profit_claimed": ("f2-assertion.exposure-claim-any.v1"),
    }
    common_metrics = {
        **coverage_metrics,
        **intra_quote_metrics,
        "atomic_ticket_binding_count": len(source.probability_snapshot.atomic_ticket_bindings),
        "active_quote_version_count": source.cost_surface.active_quote_version_count,
        "active_settlement_object_count": active_settlement_object_count,
        "numeric_probability_tier_count": int(probability_checks["numeric_tier_count"]),
        "oral_rebate_scope_count": len(source.rebate_schedule.scopes),
    }
    results = tuple(
        _result(
            assertion_id,
            actuals[assertion_id],
            calculation_ref=calculation_refs[assertion_id],
            source_hashes=source_hashes,
            metrics=common_metrics,
        )
        for assertion_id in F2_REQUIRED_ASSERTION_IDS
    )
    all_pass = all(result.status == "PASS" for result in results)
    return _with_hash(
        F2AssertionReport,
        {
            "assertion_profile_hash": F2_ASSERTION_PROFILE_HASH,
            "source_active_projection_hash": active_registry_projection_hash(registry),
            "source_f2_report_hash": source.content_hash,
            "source_atomic_ticket_projection_hash": atomic_ticket_projection_hash(independent),
            "source_artifact_hashes": dict(sorted(source.artifact_hashes.items())),
            "required_assertion_ids": F2_REQUIRED_ASSERTION_IDS,
            "assertion_results": results,
            "assertion_result_hashes": {
                result.assertion_id: result.content_hash for result in results
            },
            "fresh_recomputed_f2_hash": fresh.content_hash,
            "reordered_input_f2_hash": reordered.content_hash,
            "fresh_recompute_hash_matches": fresh_matches,
            "reordered_input_hash_matches": reordered_matches,
            "all_required_assertions_pass": all_pass,
            "status": "VERIFIED" if all_pass else "PARTIAL",
            "global_foundation_complete_claimed": False,
        },
    )


__all__ = [
    "F2_ASSERTION_PROFILE_HASH",
    "F2_ASSERTION_PROFILE_REF",
    "F2_ASSERTION_PROFILE_SOURCE_REF",
    "F2_REQUIRED_ASSERTION_EXPECTATIONS",
    "F2_REQUIRED_ASSERTION_IDS",
    "F2AssertionReport",
    "F2AssertionResult",
    "compile_f2_assertion_report",
]
