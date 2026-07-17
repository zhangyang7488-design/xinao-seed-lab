"""Deterministic in-memory F2 probability, rebate, and cost compiler.

The input is the complete :class:`FoundationSemanticsRegistry` produced by F1.
The compiler deliberately keeps catalog component rows distinct from atomic
tickets.  Basic, set, and number-combination rows receive exact tier
probabilities.  Linked-zodiac, linked-tail, and parlay rows remain quote
components of fifteen lazy selection domains and therefore bind symbolic
domain formulae rather than fabricated component-level tickets.

All normal HIT payouts are the displayed quote (already including stake), MISS
pays zero, and VOID refunds exactly one unit.  No normal settlement adds an
extra principal unit.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from itertools import combinations
from math import gcd
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xinao.canonical import canonical_sha256
from xinao.foundation.selection_manifest import (
    AtomicTicketBindingDescriptor,
    AtomicTicketBindingVersion,
    compile_default_atomic_ticket_bindings,
)
from xinao.foundation.semantics_basic import tier_probabilities as basic_probabilities
from xinao.foundation.semantics_combinations import (
    tier_probabilities as combination_probabilities,
)
from xinao.foundation.semantics_registry import (
    CanonicalRuleSemanticRecord,
    CanonicalSelectionDomainSpec,
    FoundationSemanticsRegistry,
    load_play_catalog,
)
from xinao.foundation.semantics_sets import ZODIAC_ORDER
from xinao.foundation.semantics_sets import tier_probabilities as set_probabilities

F2_DRAW_DATE = "2026-07-01"
EXPECTED_ACTIVE_COMPONENT_COUNT = 416
EXPECTED_EXACT_COMPONENT_COUNT = 218
EXPECTED_SYMBOLIC_COMPONENT_COUNT = 198
EXPECTED_SYMBOLIC_FORMULA_COUNT = 15
EXPECTED_ATOMIC_TICKET_BINDING_COUNT = 37

_COMBINATION_FAMILIES = frozenset(
    {
        "linked-number",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "special-regular-hit",
    }
)
_GROUPED_FAMILIES = frozenset({"linked-zodiac", "linked-tail", "parlay"})

Representation = Literal["EXACT_NUMERIC", "SYMBOLIC_DOMAIN_FORMULA"]
CostRepresentation = Representation
TerminalRole = Literal["HIT", "MISS", "VOID"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContentHashedModel(_FrozenModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> _ContentHashedModel:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_sha256(payload) != self.content_hash:
            raise ValueError("content_hash does not bind the canonical payload")
        return self


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    draft = model.model_construct(**dict(payload), content_hash="0" * 64)
    body = draft.model_dump(mode="json", exclude={"content_hash"})
    body["content_hash"] = canonical_sha256(body)
    return model.model_validate(body)


class RationalValue(_FrozenModel):
    """Canonical JSON form for every exact :class:`Fraction` in F2 artifacts."""

    numerator: int
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def require_reduced_form(self) -> RationalValue:
        if gcd(abs(self.numerator), self.denominator) != 1:
            raise ValueError("rational value must be reduced")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction) -> RationalValue:
        if not isinstance(value, Fraction):
            raise TypeError("value must be Fraction")
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class TierProbability(_FrozenModel):
    tier_id: str
    terminal_role: TerminalRole
    probability: RationalValue


class ExactProbabilityCase(_FrozenModel):
    case_id: str
    selection_equivalence_ref: str
    atomic_selection_count: int = Field(gt=0)
    tier_probabilities: tuple[TierProbability, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def require_partition(self) -> ExactProbabilityCase:
        if len({tier.tier_id for tier in self.tier_probabilities}) != len(self.tier_probabilities):
            raise ValueError("probability case contains duplicate tier ids")
        total = sum(
            (tier.probability.as_fraction() for tier in self.tier_probabilities),
            start=Fraction(0),
        )
        if total != 1:
            raise ValueError("exact tier probabilities must sum to one")
        return self


class SymbolicDomainProbabilityFormula(_ContentHashedModel):
    schema_version: Literal["xinao.symbolic_domain_probability_formula.v1"] = (
        "xinao.symbolic_domain_probability_formula.v1"
    )
    formula_id: str
    selection_domain_spec_id: str
    source_domain_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_atomic_ticket_binding_id: str
    independent_atomic_ticket_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_id: Literal["linked-zodiac", "linked-tail", "parlay"]
    play_id: str
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    exact_atomic_selection_count: int = Field(gt=0)
    arity_min: int = Field(ge=2, le=6)
    arity_max: int = Field(ge=2, le=6)
    probability_formula_refs: tuple[str, ...] = Field(min_length=1)
    probability_model_ref: str
    hit_formula: str
    miss_formula: Literal["P_MISS=1-P_HIT"] = "P_MISS=1-P_HIT"
    equivalence_descriptor: str
    equivalence_axes: tuple[str, ...] = Field(min_length=1)
    quote_aggregation_ref: Literal["MIN_SELECTED_COMPONENT", "PRODUCT_NON_VOID_LEGS"]
    component_rows_are_independent_tickets: Literal[False] = False
    materialized_atomic_ticket_count: Literal[0] = 0

    @field_validator("component_baseline_ids")
    @classmethod
    def require_sorted_components(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("formula component ids must be sorted and unique")
        return values


class ProbabilityComponentBinding(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: str
    semantic_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_domain_spec_id: str
    probability_formula_ref: str
    representation: Representation
    ticket_identity: Literal[
        "ATOMIC_SELECTION_EQUIVALENCE_COMPONENT",
        "GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET",
    ]
    exact_cases: tuple[ExactProbabilityCase, ...] = ()
    symbolic_formula_id: str | None = None
    independent_atomic_ticket_binding_id: str | None = None

    @model_validator(mode="after")
    def distinguish_exact_from_grouped(self) -> ProbabilityComponentBinding:
        if self.representation == "EXACT_NUMERIC":
            if not self.exact_cases or self.symbolic_formula_id is not None:
                raise ValueError("exact binding must contain cases and no symbolic formula")
            if self.ticket_identity != "ATOMIC_SELECTION_EQUIVALENCE_COMPONENT":
                raise ValueError("exact binding has the wrong ticket identity")
        else:
            if self.exact_cases or not self.symbolic_formula_id:
                raise ValueError("symbolic binding must contain only a formula reference")
            if self.ticket_identity != "GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET":
                raise ValueError("grouped component cannot be presented as an atomic ticket")
        composite = self.family_id in _COMBINATION_FAMILIES | _GROUPED_FAMILIES
        if composite != (self.independent_atomic_ticket_binding_id is not None):
            raise ValueError("composite component must bind exactly one independent ticket domain")
        return self


class AtomicTicketProbabilityBinding(_FrozenModel):
    """F2 projection of one independently compiled composite ticket identity."""

    binding_id: str
    independent_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_domain_spec_id: str
    family_id: str
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    exact_atomic_ticket_count: int = Field(gt=0)
    canonical_ticket_identity_rule: Literal["play_id::selection_id"] = "play_id::selection_id"
    quote_aggregation_ref: Literal[
        "BOUND_BASELINE_TIER_COMPONENT",
        "MIN_SELECTED_COMPONENT",
        "PRODUCT_NON_VOID_LEGS",
    ]
    representation: Representation
    exact_probability_component_baseline_id: str | None = None
    symbolic_formula_id: str | None = None
    materialized_atomic_ticket_count: Literal[0] = 0

    @model_validator(mode="after")
    def preserve_ticket_identity(self) -> AtomicTicketProbabilityBinding:
        if self.representation == "EXACT_NUMERIC":
            if (
                not self.exact_probability_component_baseline_id
                or self.symbolic_formula_id is not None
                or len(self.component_baseline_ids) != 1
            ):
                raise ValueError("exact composite ticket must retain its one baseline identity")
        elif self.exact_probability_component_baseline_id or not self.symbolic_formula_id:
            raise ValueError("grouped ticket must point to its symbolic domain formula")
        return self


class SettlementProbabilitySnapshotVersion(_ContentHashedModel):
    schema_version: Literal["xinao.settlement_probability_snapshot.v1"] = (
        "xinao.settlement_probability_snapshot.v1"
    )
    snapshot_ref: Literal["xinao-f2-settlement-probability.2026-07-01.v1"] = (
        "xinao-f2-settlement-probability.2026-07-01.v1"
    )
    source_active_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_atomic_ticket_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    draw_date: Literal["2026-07-01"] = F2_DRAW_DATE
    fraction_serialization: Literal["NUMERATOR_DENOMINATOR_REDUCED"] = (
        "NUMERATOR_DENOMINATOR_REDUCED"
    )
    component_binding_count: Literal[416] = 416
    exact_numeric_component_count: Literal[218] = 218
    symbolic_component_count: Literal[198] = 198
    symbolic_formula_count: Literal[15] = 15
    atomic_ticket_binding_count: Literal[37] = 37
    bindings: tuple[ProbabilityComponentBinding, ...]
    symbolic_formulas: tuple[SymbolicDomainProbabilityFormula, ...]
    atomic_ticket_bindings: tuple[AtomicTicketProbabilityBinding, ...]

    @model_validator(mode="after")
    def validate_coverage(self) -> SettlementProbabilitySnapshotVersion:
        ids = [binding.baseline_id for binding in self.bindings]
        if len(ids) != 416 or len(ids) != len(set(ids)) or ids != sorted(ids):
            raise ValueError("probability bindings must cover the sorted unique 416 active rows")
        exact = sum(binding.representation == "EXACT_NUMERIC" for binding in self.bindings)
        symbolic = len(self.bindings) - exact
        if (exact, symbolic) != (218, 198):
            raise ValueError("probability representation counts are incorrect")
        formula_ids = [formula.formula_id for formula in self.symbolic_formulas]
        if len(formula_ids) != 15 or formula_ids != sorted(formula_ids):
            raise ValueError("symbolic formulae must be the sorted fifteen-domain set")
        known = set(formula_ids)
        if any(
            binding.symbolic_formula_id not in known
            for binding in self.bindings
            if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
        ):
            raise ValueError("symbolic component references an unknown formula")
        if len(self.atomic_ticket_bindings) != 37:
            raise ValueError("probability snapshot must bind all 37 composite ticket domains")
        ticket_ids = [binding.binding_id for binding in self.atomic_ticket_bindings]
        if ticket_ids != sorted(ticket_ids) or len(ticket_ids) != len(set(ticket_ids)):
            raise ValueError("atomic ticket bindings must be sorted and unique")
        if (
            sum(
                binding.representation == "EXACT_NUMERIC" for binding in self.atomic_ticket_bindings
            )
            != 22
        ):
            raise ValueError("atomic ticket bindings must retain 22 exact combination tickets")
        if (
            sum(
                binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
                for binding in self.atomic_ticket_bindings
            )
            != 15
        ):
            raise ValueError("atomic ticket bindings must retain 15 grouped domains")
        return self


class RebateAssumptionScope(_FrozenModel):
    scope_id: str
    oral_label: str
    evidence_class: Literal["USER_ORAL_ASSUMPTION"] = "USER_ORAL_ASSUMPTION"
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    candidate_rate: RationalValue
    safe_ceiling: RationalValue
    resolved_rate: RationalValue
    resolution_status: Literal["ACTIVE_UNCAPPED", "ACTIVE_CAPPED"]
    actual_exposure_claimed: Literal[False] = False

    @model_validator(mode="after")
    def enforce_ceiling(self) -> RebateAssumptionScope:
        candidate = self.candidate_rate.as_fraction()
        ceiling = self.safe_ceiling.as_fraction()
        resolved = self.resolved_rate.as_fraction()
        if ceiling < 0 or resolved < 0 or resolved > ceiling or resolved > candidate:
            raise ValueError("resolved oral rebate exceeds its safe ceiling")
        expected = "ACTIVE_CAPPED" if resolved < candidate else "ACTIVE_UNCAPPED"
        if self.resolution_status != expected:
            raise ValueError("rebate scope resolution status is inconsistent")
        return self


class RebateComponentBinding(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    quote_role: Literal["ACTIVE_DEFAULT_QUOTE"] = "ACTIVE_DEFAULT_QUOTE"
    scope_id: str | None
    evidence_status: Literal["USER_ORAL_ASSUMPTION", "UNCONFIRMED_NO_REBATE"]
    candidate_rate: RationalValue | None
    resolved_rate: RationalValue
    actual_exposure_claimed: Literal[False] = False

    @model_validator(mode="after")
    def validate_status(self) -> RebateComponentBinding:
        if self.evidence_status == "USER_ORAL_ASSUMPTION":
            if not self.scope_id or self.candidate_rate is None:
                raise ValueError("oral rebate binding must name its scope and candidate")
        elif (
            self.scope_id is not None
            or self.candidate_rate is not None
            or self.resolved_rate.as_fraction() != 0
        ):
            raise ValueError("unconfirmed rebate bindings must be explicit zero without a scope")
        return self


class RebateScheduleVersion(_ContentHashedModel):
    schema_version: Literal["xinao.rebate_schedule.v1"] = "xinao.rebate_schedule.v1"
    schedule_ref: Literal["xinao-f2-rebate-schedule.2026-07-01.v1"] = (
        "xinao-f2-rebate-schedule.2026-07-01.v1"
    )
    source_active_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    probability_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_binding_count: Literal[416] = 416
    active_quote_version_count: Literal[1] = 1
    active_quote_binding_count: Literal[416] = 416
    oral_assumption_scope_count: Literal[3] = 3
    scopes: tuple[RebateAssumptionScope, ...]
    bindings: tuple[RebateComponentBinding, ...]

    @model_validator(mode="after")
    def validate_schedule(self) -> RebateScheduleVersion:
        if len(self.scopes) != 3 or len({scope.scope_id for scope in self.scopes}) != 3:
            raise ValueError("rebate schedule must contain exactly three oral scopes")
        ids = [binding.baseline_id for binding in self.bindings]
        if len(ids) != 416 or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("rebate schedule must cover sorted unique 416 active rows")
        scope_by_id = {scope.scope_id: scope for scope in self.scopes}
        for binding in self.bindings:
            if binding.scope_id is None:
                continue
            scope = scope_by_id.get(binding.scope_id)
            if scope is None or binding.baseline_id not in scope.component_baseline_ids:
                raise ValueError("rebate binding does not belong to its oral scope")
            if binding.resolved_rate != scope.resolved_rate:
                raise ValueError("rebate binding rate differs from resolved scope rate")
        return self


class TierPayout(_FrozenModel):
    tier_id: str
    terminal_role: TerminalRole
    payout_source: Literal["QUOTE_COMPONENT", "ZERO", "REFUND_STAKE"]
    payout_component_index: int | None = Field(default=None, ge=0)
    unit_payout: str
    evidence_status: Literal["SEMANTIC_DEFINITION", "RESEARCH_CONVENTION"]
    convention_ref: str | None = None

    @field_validator("unit_payout")
    @classmethod
    def validate_decimal_string(cls, value: str) -> str:
        _decimal_fraction(value, positive=False)
        return value

    @model_validator(mode="after")
    def confine_void_convention(self) -> TierPayout:
        void_ref = "xinao-research-convention.void-refund-one.v1"
        if self.terminal_role == "VOID":
            if (
                self.payout_source != "REFUND_STAKE"
                or self.unit_payout != "1"
                or self.evidence_status != "RESEARCH_CONVENTION"
                or self.convention_ref != void_ref
            ):
                raise ValueError("VOID must use the scoped versioned refund-one convention")
        elif self.evidence_status != "SEMANTIC_DEFINITION" or self.convention_ref is not None:
            raise ValueError("normal HIT/MISS tiers cannot inherit the VOID convention")
        return self


class ExactCostCase(_FrozenModel):
    case_id: str
    atomic_selection_count: int = Field(gt=0)
    tier_payouts: tuple[TierPayout, ...] = Field(min_length=2)
    quoted_expected_cost: RationalValue
    rebate_rate: RationalValue
    expected_unit_cost: RationalValue
    structural_unit_margin: RationalValue

    @model_validator(mode="after")
    def validate_cost_identity(self) -> ExactCostCase:
        quoted = self.quoted_expected_cost.as_fraction()
        rebate = self.rebate_rate.as_fraction()
        expected = self.expected_unit_cost.as_fraction()
        margin = self.structural_unit_margin.as_fraction()
        if expected != quoted + rebate or margin != 1 - expected:
            raise ValueError("cost case does not satisfy the unit-cost identities")
        return self


class SettlementCostComponentBinding(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: str
    semantic_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote_components: tuple[str, ...] = Field(min_length=1, max_length=2)
    representation: CostRepresentation
    quote_role: Literal["ACTIVE_DEFAULT_QUOTE"] = "ACTIVE_DEFAULT_QUOTE"
    included_in_active_cost_surface: Literal[True] = True
    payout_contract: Literal["HIT_Q_MISS_0_VOID_1_NO_EXTRA_NORMAL_PRINCIPAL"]
    principal_refund_on_normal_settlement: Literal[False] = False
    exact_cases: tuple[ExactCostCase, ...] = ()
    symbolic_formula_id: str | None = None
    symbolic_cost_formula: str | None = None

    @field_validator("quote_components")
    @classmethod
    def validate_quotes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _decimal_fraction(value, positive=True)
        return values

    @model_validator(mode="after")
    def validate_representation(self) -> SettlementCostComponentBinding:
        if self.representation == "EXACT_NUMERIC":
            if not self.exact_cases or self.symbolic_formula_id or self.symbolic_cost_formula:
                raise ValueError("exact cost binding cannot contain symbolic placeholders")
        elif self.representation == "SYMBOLIC_DOMAIN_FORMULA" and (
            self.exact_cases or not self.symbolic_formula_id or not self.symbolic_cost_formula
        ):
            raise ValueError("symbolic cost binding must not fabricate numeric cases")
        if (
            self.quote_role != "ACTIVE_DEFAULT_QUOTE"
            or not self.included_in_active_cost_surface
            or self.payout_contract != "HIT_Q_MISS_0_VOID_1_NO_EXTRA_NORMAL_PRINCIPAL"
        ):
            raise ValueError("active quote binding is missing its payout contract")
        return self


class SettlementCostSurfaceVersion(_ContentHashedModel):
    schema_version: Literal["xinao.settlement_cost_surface.v1"] = "xinao.settlement_cost_surface.v1"
    surface_ref: Literal["xinao-f2-settlement-cost-surface.2026-07-01.v1"] = (
        "xinao-f2-settlement-cost-surface.2026-07-01.v1"
    )
    source_active_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    probability_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rebate_schedule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_binding_count: Literal[416] = 416
    active_quote_version_count: Literal[1] = 1
    active_quote_component_count: Literal[416] = 416
    exact_numeric_component_count: Literal[218] = 218
    symbolic_component_count: Literal[198] = 198
    void_payout_convention_ref: Literal["xinao-research-convention.void-refund-one.v1"] = (
        "xinao-research-convention.void-refund-one.v1"
    )
    void_payout_convention_status: Literal["RESEARCH_CONVENTION"] = "RESEARCH_CONVENTION"
    void_payout_scope: Literal["ONLY_SEMANTICS_WITH_EXPLICIT_VOID_TIER"] = (
        "ONLY_SEMANTICS_WITH_EXPLICIT_VOID_TIER"
    )
    bindings: tuple[SettlementCostComponentBinding, ...]

    @model_validator(mode="after")
    def validate_surface(self) -> SettlementCostSurfaceVersion:
        ids = [binding.baseline_id for binding in self.bindings]
        if len(ids) != 416 or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("cost surface must cover sorted unique 416 active rows")
        counts = {
            mode: sum(binding.representation == mode for binding in self.bindings)
            for mode in ("EXACT_NUMERIC", "SYMBOLIC_DOMAIN_FORMULA")
        }
        if counts != {
            "EXACT_NUMERIC": 218,
            "SYMBOLIC_DOMAIN_FORMULA": 198,
        }:
            raise ValueError("cost surface representation counts are incorrect")
        if sum(binding.included_in_active_cost_surface for binding in self.bindings) != 416:
            raise ValueError("active cost surface must contain exactly 416 non-B components")
        return self


class ExactOddsBenchmarkCase(_FrozenModel):
    case_id: str
    quoted_expected_cost: RationalValue
    resolved_rebate_rate: RationalValue
    total_safe_rebate_ceiling: RationalValue
    expected_unit_cost: RationalValue
    structural_unit_margin: RationalValue
    price_space_status: Literal["BELOW_BREAK_EVEN", "AT_BREAK_EVEN", "ABOVE_BREAK_EVEN"]


class OddsBenchmarkComponentBinding(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    representation: CostRepresentation
    exact_cases: tuple[ExactOddsBenchmarkCase, ...] = ()
    symbolic_formula_id: str | None = None
    benchmark_claim_scope: Literal[
        "EXACT_BOUND_QUOTE_UNIT_COST",
        "SYMBOLIC_TICKET_REQUIRED_NO_COMPONENT_COST_CLAIM",
    ]


class OddsSpaceBenchmarkVersion(_ContentHashedModel):
    schema_version: Literal["xinao.odds_space_benchmark.v1"] = "xinao.odds_space_benchmark.v1"
    benchmark_ref: Literal["xinao-f2-odds-space-benchmark.2026-07-01.v1"] = (
        "xinao-f2-odds-space-benchmark.2026-07-01.v1"
    )
    source_cost_surface_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_binding_count: Literal[416] = 416
    active_quote_version_count: Literal[1] = 1
    active_quote_component_count: Literal[416] = 416
    exact_numeric_component_count: Literal[218] = 218
    symbolic_component_count: Literal[198] = 198
    bindings: tuple[OddsBenchmarkComponentBinding, ...]

    @model_validator(mode="after")
    def validate_benchmarks(self) -> OddsSpaceBenchmarkVersion:
        ids = [binding.baseline_id for binding in self.bindings]
        if len(ids) != 416 or ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("odds benchmark must cover sorted unique 416 active rows")
        for binding in self.bindings:
            if binding.representation == "EXACT_NUMERIC":
                if not binding.exact_cases or binding.symbolic_formula_id is not None:
                    raise ValueError("exact benchmark binding is incomplete")
            elif binding.representation == "SYMBOLIC_DOMAIN_FORMULA" and (
                binding.exact_cases or not binding.symbolic_formula_id
            ):
                raise ValueError("symbolic benchmark must not claim component cost")
        counts = {
            mode: sum(binding.representation == mode for binding in self.bindings)
            for mode in ("EXACT_NUMERIC", "SYMBOLIC_DOMAIN_FORMULA")
        }
        if counts != {
            "EXACT_NUMERIC": 218,
            "SYMBOLIC_DOMAIN_FORMULA": 198,
        }:
            raise ValueError("odds benchmark representation counts are incorrect")
        return self


class ChannelMetadataDiagnostic(_FrozenModel):
    """Trace the 17 B-channel rows without making them part of F2 closure identity."""

    schema_version: Literal["xinao.f2_channel_metadata_diagnostic.v1"] = (
        "xinao.f2_channel_metadata_diagnostic.v1"
    )
    diagnostic_ref: Literal["xinao-f2-channel-b-diagnostic.2026-07-01.v1"] = (
        "xinao-f2-channel-b-diagnostic.2026-07-01.v1"
    )
    source_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_catalog_component_count: Literal[433] = 433
    channel_component_count: Literal[17] = 17
    channel_baseline_ids: tuple[str, ...]
    channel_record_hashes: dict[str, str]
    channel_metadata_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    participates_in_f2_content_hash: Literal[False] = False
    participates_in_f2_closure_status: Literal[False] = False

    @model_validator(mode="after")
    def validate_diagnostic(self) -> ChannelMetadataDiagnostic:
        if (
            len(self.channel_baseline_ids) != 17
            or self.channel_baseline_ids != tuple(sorted(self.channel_baseline_ids))
            or set(self.channel_baseline_ids) != set(self.channel_record_hashes)
        ):
            raise ValueError("B-channel diagnostic must preserve exactly 17 sorted identities")
        expected = canonical_sha256(
            {
                "channel_baseline_ids": self.channel_baseline_ids,
                "channel_record_hashes": dict(sorted(self.channel_record_hashes.items())),
            }
        )
        if self.channel_metadata_digest != expected:
            raise ValueError("B-channel diagnostic digest does not bind its record references")
        return self


class SettlementCostCompileReport(_ContentHashedModel):
    schema_version: Literal["xinao.settlement_cost_compile_report.v1"] = (
        "xinao.settlement_cost_compile_report.v1"
    )
    report_ref: Literal["xinao-f2-settlement-cost-compile.2026-07-01.v1"] = (
        "xinao-f2-settlement-cost-compile.2026-07-01.v1"
    )
    source_active_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    probability_snapshot: SettlementProbabilitySnapshotVersion
    rebate_schedule: RebateScheduleVersion
    cost_surface: SettlementCostSurfaceVersion
    odds_space_benchmark: OddsSpaceBenchmarkVersion
    artifact_hashes: dict[str, str]
    component_binding_count: Literal[416] = 416
    active_quote_version_count: Literal[1] = 1
    active_quote_component_count: Literal[416] = 416
    exact_numeric_component_count: Literal[218] = 218
    symbolic_formula_component_count: Literal[198] = 198
    symbolic_selection_domain_formula_count: Literal[15] = 15
    independent_atomic_ticket_binding_count: Literal[37] = 37
    oral_assumption_scope_count: Literal[3] = 3
    compile_status: Literal["VERIFIED_IN_MEMORY"] = "VERIFIED_IN_MEMORY"
    global_foundation_complete_claimed: Literal[False] = False
    assertions: dict[str, bool]

    @model_validator(mode="after")
    def validate_report(self) -> SettlementCostCompileReport:
        expected_hashes = {
            "SettlementProbabilitySnapshotVersion": self.probability_snapshot.content_hash,
            "RebateScheduleVersion": self.rebate_schedule.content_hash,
            "SettlementCostSurfaceVersion": self.cost_surface.content_hash,
            "OddsSpaceBenchmarkVersion": self.odds_space_benchmark.content_hash,
        }
        if self.artifact_hashes != expected_hashes:
            raise ValueError("compile report artifact hashes do not bind nested artifacts")
        active_hashes = {
            self.source_active_projection_hash,
            self.probability_snapshot.source_active_projection_hash,
            self.rebate_schedule.source_active_projection_hash,
            self.cost_surface.source_active_projection_hash,
        }
        if len(active_hashes) != 1:
            raise ValueError("F2 artifacts do not share one active quote projection identity")
        if not self.assertions or not all(self.assertions.values()):
            raise ValueError("compile report cannot be verified with a failed assertion")
        return self


def _decimal_fraction(value: str, *, positive: bool) -> Fraction:
    if not isinstance(value, str) or not value:
        raise TypeError("decimal values must be non-empty strings")
    try:
        decimal = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal string") from exc
    if not decimal.is_finite() or (positive and decimal <= 0) or (not positive and decimal < 0):
        raise ValueError("decimal string is outside the accepted range")
    return Fraction(decimal)


def _rational(value: Fraction | int) -> RationalValue:
    return RationalValue.from_fraction(value if isinstance(value, Fraction) else Fraction(value))


def active_registry_projection_hash(registry: FoundationSemanticsRegistry) -> str:
    """Hash only the 416 issuer-active semantic rows used by F2."""

    records = tuple(
        sorted(
            (
                record
                for record in registry.rule_semantic_map.records
                if record.catalog.panel != "B"
            ),
            key=lambda record: record.baseline_id,
        )
    )
    if len(records) != EXPECTED_ACTIVE_COMPONENT_COUNT:
        raise ValueError("active F2 projection must contain exactly 416 non-B rows")
    active_spec_ids = {record.selection_domain_spec_id for record in records}
    specs = tuple(
        sorted(
            (
                spec
                for spec in registry.expected_selection_domain.specifications
                if spec.spec_id in active_spec_ids
            ),
            key=lambda spec: spec.spec_id,
        )
    )
    return canonical_sha256(
        {
            "schema_version": "xinao.f2_active_registry_projection.v1",
            "active_quote_version_count": 1,
            "component_count": len(records),
            "record_hashes": {record.baseline_id: record.content_hash for record in records},
            "selection_domain_hashes": {spec.spec_id: spec.content_hash for spec in specs},
        }
    )


def atomic_ticket_projection_hash(version: AtomicTicketBindingVersion) -> str:
    """Hash the 37 active composite ticket descriptors, not catalog-wide provenance."""

    return canonical_sha256(
        {
            "schema_version": "xinao.f2_atomic_ticket_projection.v1",
            "binding_count": len(version.bindings),
            "binding_hashes": {
                binding.binding_id: binding.content_hash
                for binding in sorted(version.bindings, key=lambda item: item.binding_id)
            },
        }
    )


def compile_channel_metadata_diagnostic(
    registry: FoundationSemanticsRegistry,
    *,
    source_catalog: Mapping[str, Any] | None = None,
) -> ChannelMetadataDiagnostic:
    """Compile optional raw B-row metadata outside all required F2 artifacts.

    The canonical F1 registry contains only the 416 ACTIVE settlement rows.  A
    caller compiling a non-default catalog must therefore pass that raw catalog
    explicitly when it wants the sibling B-row diagnostic.
    """

    if not isinstance(registry, FoundationSemanticsRegistry):
        raise TypeError("registry must be FoundationSemanticsRegistry")
    catalog = load_play_catalog() if source_catalog is None else source_catalog
    entries = catalog.get("entries")
    if not isinstance(entries, list) or len(entries) != 433:
        raise ValueError("B-channel diagnostic requires the complete 433-row source catalog")
    records = tuple(
        sorted(
            (dict(record) for record in entries if record.get("panel") == "B"),
            key=lambda record: str(record.get("baseline_id")),
        )
    )
    if len(records) != 17 or any(
        not isinstance(record.get("baseline_id"), str) for record in records
    ):
        raise ValueError("source catalog must contain exactly 17 identified B-channel rows")
    record_hashes = {str(record["baseline_id"]): canonical_sha256(record) for record in records}
    baseline_ids = tuple(record_hashes)
    digest = canonical_sha256(
        {
            "channel_baseline_ids": baseline_ids,
            "channel_record_hashes": record_hashes,
        }
    )
    return ChannelMetadataDiagnostic(
        source_registry_hash=registry.content_hash,
        channel_baseline_ids=baseline_ids,
        channel_record_hashes=record_hashes,
        channel_metadata_digest=digest,
    )


def _tier_vector(
    record: CanonicalRuleSemanticRecord,
    probabilities: Mapping[str, Fraction],
) -> tuple[TierProbability, ...]:
    expected_ids = {tier.tier_id for tier in record.settlement_tiers}
    if set(probabilities) != expected_ids:
        raise ValueError(
            f"probability tiers do not match settlement tiers for {record.baseline_id}"
        )
    vector = tuple(
        TierProbability(
            tier_id=tier.tier_id,
            terminal_role=tier.terminal_role,
            probability=_rational(probabilities[tier.tier_id]),
        )
        for tier in record.settlement_tiers
    )
    if sum((item.probability.as_fraction() for item in vector), Fraction(0)) != 1:
        raise ValueError(f"probability tiers are not normalized for {record.baseline_id}")
    return vector


def _formula_descriptor(
    spec: Any,
    records: Sequence[Any],
    atomic_binding: AtomicTicketBindingDescriptor,
) -> SymbolicDomainProbabilityFormula:
    ordered_records = tuple(sorted(records, key=lambda item: item.baseline_id))
    first = ordered_records[0]
    if first.family_id == "linked-zodiac":
        probability_model = "DISJOINT_ZODIAC_BLOCK_INCLUSION_EXCLUSION_7_OF_49"
        hit_formula = (
            "P_HIT=SUM_{S_SUBSET_SELECTED}((-1)^|S|*C(49-SUM_{i_IN_S}(b_i),7))/C(49,7) "
            "FOR HIT_ALL; P_HIT=C(49-SUM_i(b_i),7)/C(49,7) FOR MISS_ALL"
        )
        equivalence = (
            "same play polarity and sorted selected zodiac block-size vector under the "
            f"Gregorian {F2_DRAW_DATE} lunar-year table"
        )
        axes = ("POLARITY", "SORTED_ZODIAC_BLOCK_SIZES", "LUNAR_YEAR_TABLE_REF")
    elif first.family_id == "linked-tail":
        probability_model = "DISJOINT_TAIL_BLOCK_INCLUSION_EXCLUSION_7_OF_49"
        hit_formula = (
            "P_HIT=SUM_{S_SUBSET_SELECTED}((-1)^|S|*C(49-SUM_{i_IN_S}(b_i),7))/C(49,7) "
            "FOR HIT_ALL; P_HIT=C(49-SUM_i(b_i),7)/C(49,7) FOR MISS_ALL"
        )
        equivalence = "same play polarity, arity, and whether the selected tails include zero-tail"
        axes = ("POLARITY", "ARITY", "CONTAINS_ZERO_TAIL")
    else:
        probability_model = "ORDERED_WITHOUT_REPLACEMENT_ATTRIBUTE_TYPE_DP"
        hit_formula = (
            "DP(i,c)=SUM_t(ACCEPTS(t,a_i)*c_t*DP(i+1,c-e_t)); P_HIT=DP(0,c_initial)/PERM(49,k)"
        )
        equivalence = (
            "same canonical regular-position attribute-leg vector under property-49 "
            "multiplier-one and color-49-green semantics"
        )
        axes = ("ORDERED_POSITION_ATTRIBUTE_VECTOR", "PROPERTY_49_POLICY", "COLOR_49_POLICY")
    return _with_hash(
        SymbolicDomainProbabilityFormula,
        {
            "formula_id": f"symbolic-probability:{spec.spec_id}",
            "selection_domain_spec_id": spec.spec_id,
            "source_domain_hash": spec.content_hash,
            "independent_atomic_ticket_binding_id": atomic_binding.binding_id,
            "independent_atomic_ticket_binding_hash": atomic_binding.content_hash,
            "family_id": first.family_id,
            "play_id": first.play_id,
            "component_baseline_ids": tuple(
                sorted(record.baseline_id for record in ordered_records)
            ),
            "exact_atomic_selection_count": spec.exact_atomic_selection_count,
            "arity_min": spec.arity_min,
            "arity_max": spec.arity_max,
            "probability_formula_refs": tuple(
                sorted({record.probability_formula_ref for record in ordered_records})
            ),
            "probability_model_ref": probability_model,
            "hit_formula": hit_formula,
            "equivalence_descriptor": equivalence,
            "equivalence_axes": axes,
            "quote_aggregation_ref": spec.quote_aggregation_ref,
            "component_rows_are_independent_tickets": False,
            "materialized_atomic_ticket_count": 0,
        },
    )


def _six_zodiac_cases(
    canonical: CanonicalRuleSemanticRecord,
    source: Any,
    domain_spec: CanonicalSelectionDomainSpec,
) -> tuple[ExactProbabilityCase, ...]:
    grouped: dict[str, tuple[tuple[TierProbability, ...], list[str]]] = {}
    for selected in combinations(ZODIAC_ORDER, 6):
        probabilities = set_probabilities(
            source,
            draw_date=F2_DRAW_DATE,
            selection=selected,
        )
        tiers = _tier_vector(canonical, probabilities)
        signature = canonical_sha256([tier.model_dump(mode="json") for tier in tiers])
        if signature not in grouped:
            grouped[signature] = (tiers, [])
        grouped[signature][1].append("-".join(selected))
    cases = []
    for index, (_signature, (tiers, selection_keys)) in enumerate(sorted(grouped.items()), start=1):
        cases.append(
            ExactProbabilityCase(
                case_id=f"{canonical.baseline_id}:equivalence:{index}",
                selection_equivalence_ref=(
                    "six-zodiac-selection-keys-sha256:"
                    + canonical_sha256(tuple(sorted(selection_keys)))
                ),
                atomic_selection_count=len(selection_keys),
                tier_probabilities=tiers,
            )
        )
    if (
        sum(case.atomic_selection_count for case in cases)
        != domain_spec.exact_atomic_selection_count
    ):
        raise ValueError("six-zodiac equivalence cases do not cover the exact domain")
    return tuple(cases)


def _validated_atomic_ticket_index(
    registry: FoundationSemanticsRegistry,
    version: AtomicTicketBindingVersion,
) -> dict[str, AtomicTicketBindingDescriptor]:
    registry_specs = {
        spec.spec_id: spec
        for spec in registry.expected_selection_domain.specifications
        if spec.family_id in _COMBINATION_FAMILIES | _GROUPED_FAMILIES
    }
    by_spec = {binding.domain_spec_id: binding for binding in version.bindings}
    if len(registry_specs) != 37 or set(by_spec) != set(registry_specs):
        raise ValueError("independent atomic ticket domains do not match the 37 composite specs")
    for spec_id, binding in by_spec.items():
        spec = registry_specs[spec_id]
        if (
            binding.family_id != spec.family_id
            or binding.play_id != spec.play_id
            or binding.component_baseline_ids != spec.component_baseline_ids
            or binding.arity_min != spec.arity_min
            or binding.arity_max != spec.arity_max
            or binding.exact_atomic_ticket_count != spec.exact_atomic_selection_count
        ):
            raise ValueError(f"independent atomic ticket scope drifted at {spec_id}")
    return by_spec


def _compile_probability_snapshot(
    registry: FoundationSemanticsRegistry,
    atomic_ticket_version: AtomicTicketBindingVersion,
) -> SettlementProbabilitySnapshotVersion:
    canonical_records = tuple(
        sorted(
            (
                record
                for record in registry.rule_semantic_map.records
                if record.catalog.panel != "B"
            ),
            key=lambda row: row.baseline_id,
        )
    )
    domains = {spec.spec_id: spec for spec in registry.expected_selection_domain.specifications}
    atomic_ticket_by_spec = _validated_atomic_ticket_index(registry, atomic_ticket_version)
    basic = {record.baseline_id: record for record in registry.source_artifacts.basic_records}
    sets = {
        record.baseline_id: record
        for record in registry.source_artifacts.set_compilation.rule_semantic_map.records
    }
    combo = {record.baseline_id: record for record in registry.source_artifacts.combination_records}
    linked_records = registry.source_artifacts.linked_compilation.rule_semantic_map.records
    linked_by_spec: dict[str, list[Any]] = defaultdict(list)
    for source in linked_records:
        canonical = next(
            record for record in canonical_records if record.baseline_id == source.baseline_id
        )
        linked_by_spec[canonical.selection_domain_spec_id].append(source)
    source_specs = (
        registry.source_artifacts.linked_compilation.expected_selection_domain.specifications
    )
    formulas = tuple(
        sorted(
            (
                _formula_descriptor(
                    spec,
                    linked_by_spec[spec.spec_id],
                    atomic_ticket_by_spec[spec.spec_id],
                )
                for spec in source_specs
            ),
            key=lambda formula: formula.formula_id,
        )
    )
    formula_by_spec = {formula.selection_domain_spec_id: formula.formula_id for formula in formulas}

    bindings: list[ProbabilityComponentBinding] = []
    for record in canonical_records:
        domain = domains[record.selection_domain_spec_id]
        if record.source_module == "linked":
            bindings.append(
                ProbabilityComponentBinding(
                    baseline_id=record.baseline_id,
                    family_id=record.family_id,
                    semantic_record_hash=record.content_hash,
                    selection_domain_spec_id=record.selection_domain_spec_id,
                    probability_formula_ref=record.probability_formula_ref,
                    representation="SYMBOLIC_DOMAIN_FORMULA",
                    ticket_identity="GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET",
                    symbolic_formula_id=formula_by_spec[record.selection_domain_spec_id],
                    independent_atomic_ticket_binding_id=atomic_ticket_by_spec[
                        record.selection_domain_spec_id
                    ].binding_id,
                )
            )
            continue
        if record.source_module == "basic":
            probabilities = basic_probabilities(basic[record.baseline_id])
            cases = (
                ExactProbabilityCase(
                    case_id=f"{record.baseline_id}:all-atomic-selections",
                    selection_equivalence_ref=f"all-selections-in:{domain.spec_id}",
                    atomic_selection_count=domain.exact_atomic_selection_count,
                    tier_probabilities=_tier_vector(record, probabilities),
                ),
            )
        elif record.source_module == "sets":
            source = sets[record.baseline_id]
            if source.semantic_family_ref == "six-zodiac-special-membership.v1":
                cases = _six_zodiac_cases(record, source, domain)
            else:
                probabilities = set_probabilities(source, draw_date=F2_DRAW_DATE)
                cases = (
                    ExactProbabilityCase(
                        case_id=f"{record.baseline_id}:all-atomic-selections",
                        selection_equivalence_ref=f"all-selections-in:{domain.spec_id}",
                        atomic_selection_count=domain.exact_atomic_selection_count,
                        tier_probabilities=_tier_vector(record, probabilities),
                    ),
                )
        else:
            probabilities = combination_probabilities(combo[record.baseline_id])
            cases = (
                ExactProbabilityCase(
                    case_id=f"{record.baseline_id}:all-atomic-selections",
                    selection_equivalence_ref=f"all-selections-in:{domain.spec_id}",
                    atomic_selection_count=domain.exact_atomic_selection_count,
                    tier_probabilities=_tier_vector(record, probabilities),
                ),
            )
        if (
            sum(case.atomic_selection_count for case in cases)
            != domain.exact_atomic_selection_count
        ):
            raise ValueError(f"exact probability cases do not cover {record.baseline_id}")
        bindings.append(
            ProbabilityComponentBinding(
                baseline_id=record.baseline_id,
                family_id=record.family_id,
                semantic_record_hash=record.content_hash,
                selection_domain_spec_id=record.selection_domain_spec_id,
                probability_formula_ref=record.probability_formula_ref,
                representation="EXACT_NUMERIC",
                ticket_identity="ATOMIC_SELECTION_EQUIVALENCE_COMPONENT",
                exact_cases=cases,
                independent_atomic_ticket_binding_id=(
                    atomic_ticket_by_spec[record.selection_domain_spec_id].binding_id
                    if record.family_id in _COMBINATION_FAMILIES
                    else None
                ),
            )
        )
    atomic_probability_bindings = []
    for source in sorted(atomic_ticket_version.bindings, key=lambda item: item.binding_id):
        if source.family_id in _COMBINATION_FAMILIES:
            representation: Representation = "EXACT_NUMERIC"
            exact_baseline = source.component_baseline_ids[0]
            symbolic_formula_id = None
        else:
            representation = "SYMBOLIC_DOMAIN_FORMULA"
            exact_baseline = None
            symbolic_formula_id = formula_by_spec[source.domain_spec_id]
        atomic_probability_bindings.append(
            AtomicTicketProbabilityBinding(
                binding_id=source.binding_id,
                independent_binding_hash=source.content_hash,
                selection_domain_spec_id=source.domain_spec_id,
                family_id=source.family_id,
                component_baseline_ids=source.component_baseline_ids,
                exact_atomic_ticket_count=source.exact_atomic_ticket_count,
                canonical_ticket_identity_rule=source.canonical_ticket_identity_rule,
                quote_aggregation_ref=source.quote_aggregation_ref,
                representation=representation,
                exact_probability_component_baseline_id=exact_baseline,
                symbolic_formula_id=symbolic_formula_id,
                materialized_atomic_ticket_count=0,
            )
        )
    return _with_hash(
        SettlementProbabilitySnapshotVersion,
        {
            "source_active_projection_hash": active_registry_projection_hash(registry),
            "source_atomic_ticket_projection_hash": atomic_ticket_projection_hash(
                atomic_ticket_version
            ),
            "bindings": tuple(bindings),
            "symbolic_formulas": formulas,
            "atomic_ticket_bindings": tuple(atomic_probability_bindings),
        },
    )


def _tier_payouts(record: CanonicalRuleSemanticRecord) -> tuple[TierPayout, ...]:
    payouts = []
    for tier in record.settlement_tiers:
        if tier.payout_kind == "QUOTE_COMPONENT":
            index = tier.payout_component_index
            if index is None or index >= len(record.quote_components):
                raise ValueError(f"invalid quote component binding for {record.baseline_id}")
            source = "QUOTE_COMPONENT"
            unit = record.quote_components[index]
        elif tier.payout_kind == "ZERO":
            index = None
            source = "ZERO"
            unit = "0"
        elif tier.payout_kind == "REFUND_STAKE":
            index = None
            source = "REFUND_STAKE"
            unit = "1"
        else:
            raise ValueError("quote aggregation cannot be costed as an independent component")
        payouts.append(
            TierPayout(
                tier_id=tier.tier_id,
                terminal_role=tier.terminal_role,
                payout_source=source,
                payout_component_index=index,
                unit_payout=unit,
                evidence_status=(
                    "RESEARCH_CONVENTION" if tier.terminal_role == "VOID" else "SEMANTIC_DEFINITION"
                ),
                convention_ref=(
                    "xinao-research-convention.void-refund-one.v1"
                    if tier.terminal_role == "VOID"
                    else None
                ),
            )
        )
    return tuple(payouts)


def _quoted_case_cost(
    case: ExactProbabilityCase,
    payouts: Sequence[TierPayout],
) -> Fraction:
    payout_by_tier = {
        payout.tier_id: _decimal_fraction(payout.unit_payout, positive=False) for payout in payouts
    }
    return sum(
        (
            tier.probability.as_fraction() * payout_by_tier[tier.tier_id]
            for tier in case.tier_probabilities
        ),
        start=Fraction(0),
    )


def _compile_rebate_schedule(
    registry: FoundationSemanticsRegistry,
    probability: SettlementProbabilitySnapshotVersion,
) -> RebateScheduleVersion:
    records = {
        record.baseline_id: record
        for record in registry.rule_semantic_map.records
        if record.catalog.panel != "B"
    }
    probabilities = {binding.baseline_id: binding for binding in probability.bindings}
    scope_inputs = (
        (
            "oral-highest-tier.special-exact-a.v1",
            "特码 47.285 + 3.5水",
            ("BO0001",),
            Fraction(35, 1000),
        ),
        (
            "oral-highest-tier.one-zodiac-unified.v1",
            "一肖 2.1 + 1水",
            tuple(
                sorted(
                    record.baseline_id
                    for record in records.values()
                    if record.catalog.play_name == "一肖"
                )
            ),
            Fraction(1, 100),
        ),
        (
            "oral-highest-tier.three-in-three.v1",
            "三中三/三全中 760 + 15.5水",
            ("BO0215",),
            Fraction(155, 1000),
        ),
    )
    if tuple(len(item[2]) for item in scope_inputs) != (1, 12, 1):
        raise ValueError("oral rebate scope identities drifted from the registry")

    scopes = []
    scope_by_baseline: dict[str, RebateAssumptionScope] = {}
    for scope_id, oral_label, baseline_ids, candidate in scope_inputs:
        ceilings = []
        for baseline_id in baseline_ids:
            binding = probabilities[baseline_id]
            if binding.representation != "EXACT_NUMERIC":
                raise ValueError("oral rebate scope cannot bind a symbolic component")
            payouts = _tier_payouts(records[baseline_id])
            ceilings.extend(1 - _quoted_case_cost(case, payouts) for case in binding.exact_cases)
        ceiling = min(ceilings)
        if ceiling < 0:
            raise ValueError("oral rebate scope has a negative safe ceiling")
        resolved = min(candidate, ceiling)
        scope = RebateAssumptionScope(
            scope_id=scope_id,
            oral_label=oral_label,
            component_baseline_ids=baseline_ids,
            candidate_rate=_rational(candidate),
            safe_ceiling=_rational(ceiling),
            resolved_rate=_rational(resolved),
            resolution_status="ACTIVE_CAPPED" if resolved < candidate else "ACTIVE_UNCAPPED",
        )
        scopes.append(scope)
        for baseline_id in baseline_ids:
            if baseline_id in scope_by_baseline:
                raise ValueError("oral rebate scopes overlap")
            scope_by_baseline[baseline_id] = scope

    bindings = []
    for baseline_id in sorted(records):
        scope = scope_by_baseline.get(baseline_id)
        if scope is None:
            bindings.append(
                RebateComponentBinding(
                    baseline_id=baseline_id,
                    quote_role="ACTIVE_DEFAULT_QUOTE",
                    scope_id=None,
                    evidence_status="UNCONFIRMED_NO_REBATE",
                    candidate_rate=None,
                    resolved_rate=_rational(0),
                )
            )
        else:
            bindings.append(
                RebateComponentBinding(
                    baseline_id=baseline_id,
                    quote_role="ACTIVE_DEFAULT_QUOTE",
                    scope_id=scope.scope_id,
                    evidence_status="USER_ORAL_ASSUMPTION",
                    candidate_rate=scope.candidate_rate,
                    resolved_rate=scope.resolved_rate,
                )
            )
    return _with_hash(
        RebateScheduleVersion,
        {
            "source_active_projection_hash": probability.source_active_projection_hash,
            "probability_snapshot_hash": probability.content_hash,
            "scopes": tuple(sorted(scopes, key=lambda scope: scope.scope_id)),
            "bindings": tuple(bindings),
        },
    )


def _compile_cost_surface(
    registry: FoundationSemanticsRegistry,
    probability: SettlementProbabilitySnapshotVersion,
    rebate: RebateScheduleVersion,
) -> SettlementCostSurfaceVersion:
    records = {record.baseline_id: record for record in registry.rule_semantic_map.records}
    rebates = {binding.baseline_id: binding for binding in rebate.bindings}
    bindings = []
    for probability_binding in probability.bindings:
        record = records[probability_binding.baseline_id]
        if probability_binding.representation == "SYMBOLIC_DOMAIN_FORMULA":
            bindings.append(
                SettlementCostComponentBinding(
                    baseline_id=record.baseline_id,
                    family_id=record.family_id,
                    semantic_record_hash=record.content_hash,
                    quote_components=record.quote_components,
                    representation="SYMBOLIC_DOMAIN_FORMULA",
                    quote_role="ACTIVE_DEFAULT_QUOTE",
                    included_in_active_cost_surface=True,
                    payout_contract="HIT_Q_MISS_0_VOID_1_NO_EXTRA_NORMAL_PRINCIPAL",
                    symbolic_formula_id=probability_binding.symbolic_formula_id,
                    symbolic_cost_formula=(
                        "ticket_cost=SUM_t(P_tier(ticket)*payout_tier(ticket))"
                        "+resolved_rebate(ticket); component row alone is not a ticket"
                    ),
                )
            )
            continue
        rate = rebates[record.baseline_id].resolved_rate.as_fraction()
        payouts = _tier_payouts(record)
        cases = []
        for probability_case in probability_binding.exact_cases:
            quoted = _quoted_case_cost(probability_case, payouts)
            expected = quoted + rate
            cases.append(
                ExactCostCase(
                    case_id=probability_case.case_id,
                    atomic_selection_count=probability_case.atomic_selection_count,
                    tier_payouts=payouts,
                    quoted_expected_cost=_rational(quoted),
                    rebate_rate=_rational(rate),
                    expected_unit_cost=_rational(expected),
                    structural_unit_margin=_rational(1 - expected),
                )
            )
        bindings.append(
            SettlementCostComponentBinding(
                baseline_id=record.baseline_id,
                family_id=record.family_id,
                semantic_record_hash=record.content_hash,
                quote_components=record.quote_components,
                representation="EXACT_NUMERIC",
                quote_role="ACTIVE_DEFAULT_QUOTE",
                included_in_active_cost_surface=True,
                payout_contract="HIT_Q_MISS_0_VOID_1_NO_EXTRA_NORMAL_PRINCIPAL",
                exact_cases=tuple(cases),
            )
        )
    return _with_hash(
        SettlementCostSurfaceVersion,
        {
            "source_active_projection_hash": probability.source_active_projection_hash,
            "probability_snapshot_hash": probability.content_hash,
            "rebate_schedule_hash": rebate.content_hash,
            "bindings": tuple(bindings),
        },
    )


def _compile_odds_benchmark(
    cost_surface: SettlementCostSurfaceVersion,
) -> OddsSpaceBenchmarkVersion:
    bindings = []
    for cost in cost_surface.bindings:
        if cost.representation == "SYMBOLIC_DOMAIN_FORMULA":
            bindings.append(
                OddsBenchmarkComponentBinding(
                    baseline_id=cost.baseline_id,
                    representation="SYMBOLIC_DOMAIN_FORMULA",
                    symbolic_formula_id=cost.symbolic_formula_id,
                    benchmark_claim_scope="SYMBOLIC_TICKET_REQUIRED_NO_COMPONENT_COST_CLAIM",
                )
            )
            continue
        cases = []
        for item in cost.exact_cases:
            quoted = item.quoted_expected_cost.as_fraction()
            expected = item.expected_unit_cost.as_fraction()
            margin = item.structural_unit_margin.as_fraction()
            status: Literal["BELOW_BREAK_EVEN", "AT_BREAK_EVEN", "ABOVE_BREAK_EVEN"]
            if expected < 1:
                status = "BELOW_BREAK_EVEN"
            elif expected == 1:
                status = "AT_BREAK_EVEN"
            else:
                status = "ABOVE_BREAK_EVEN"
            cases.append(
                ExactOddsBenchmarkCase(
                    case_id=item.case_id,
                    quoted_expected_cost=item.quoted_expected_cost,
                    resolved_rebate_rate=item.rebate_rate,
                    total_safe_rebate_ceiling=_rational(1 - quoted),
                    expected_unit_cost=item.expected_unit_cost,
                    structural_unit_margin=_rational(margin),
                    price_space_status=status,
                )
            )
        bindings.append(
            OddsBenchmarkComponentBinding(
                baseline_id=cost.baseline_id,
                representation="EXACT_NUMERIC",
                exact_cases=tuple(cases),
                benchmark_claim_scope="EXACT_BOUND_QUOTE_UNIT_COST",
            )
        )
    return _with_hash(
        OddsSpaceBenchmarkVersion,
        {
            "source_cost_surface_hash": cost_surface.content_hash,
            "bindings": tuple(bindings),
        },
    )


def compile_f2_artifacts(
    registry: FoundationSemanticsRegistry,
    *,
    atomic_ticket_bindings: AtomicTicketBindingVersion | None = None,
) -> SettlementCostCompileReport:
    """Compile five deterministic, content-addressed F2 artifacts in memory."""

    if not isinstance(registry, FoundationSemanticsRegistry):
        raise TypeError("registry must be FoundationSemanticsRegistry")
    active_records = registry.rule_semantic_map.records
    if len(active_records) != EXPECTED_ACTIVE_COMPONENT_COUNT or any(
        record.physical_role != "ACTIVE_SETTLEMENT" or record.catalog.panel == "B"
        for record in active_records
    ):
        raise ValueError("F2 requires the complete 416-row ACTIVE F1 registry projection")
    atomic_version = atomic_ticket_bindings or compile_default_atomic_ticket_bindings()
    if not isinstance(atomic_version, AtomicTicketBindingVersion):
        raise TypeError("atomic_ticket_bindings must be AtomicTicketBindingVersion")
    probability = _compile_probability_snapshot(registry, atomic_version)
    rebate = _compile_rebate_schedule(registry, probability)
    cost_surface = _compile_cost_surface(registry, probability, rebate)
    benchmark = _compile_odds_benchmark(cost_surface)
    artifact_hashes = {
        "SettlementProbabilitySnapshotVersion": probability.content_hash,
        "RebateScheduleVersion": rebate.content_hash,
        "SettlementCostSurfaceVersion": cost_surface.content_hash,
        "OddsSpaceBenchmarkVersion": benchmark.content_hash,
    }
    assertions = {
        "active_component_bindings_cover_416": len(probability.bindings) == 416,
        "exact_and_symbolic_are_distinguished": (
            probability.exact_numeric_component_count == 218
            and probability.symbolic_component_count == 198
        ),
        "grouped_components_are_not_independent_tickets": all(
            binding.ticket_identity == "GROUPED_COMPONENT_NOT_INDEPENDENT_TICKET"
            for binding in probability.bindings
            if binding.representation == "SYMBOLIC_DOMAIN_FORMULA"
        ),
        "symbolic_selection_domains_equal_15": len(probability.symbolic_formulas) == 15,
        "independent_atomic_ticket_bindings_equal_37": (
            len(probability.atomic_ticket_bindings) == 37
        ),
        "combination_tickets_retain_exact_identity": sum(
            binding.representation == "EXACT_NUMERIC"
            for binding in probability.atomic_ticket_bindings
        )
        == 22,
        "all_quotes_are_decimal_strings": all(
            all(isinstance(value, str) for value in binding.quote_components)
            for binding in cost_surface.bindings
        ),
        "active_default_quote_surface_equals_416": sum(
            binding.included_in_active_cost_surface for binding in cost_surface.bindings
        )
        == 416,
        "b_channel_rows_absent_from_active_f2_artifacts": not any(
            record.catalog.panel == "B"
            for record in registry.rule_semantic_map.records
            if record.baseline_id
            in {
                binding.baseline_id
                for artifact in (
                    probability.bindings,
                    rebate.bindings,
                    cost_surface.bindings,
                    benchmark.bindings,
                )
                for binding in artifact
            }
        ),
        "oral_rebates_do_not_exceed_safe_ceiling": all(
            scope.resolved_rate.as_fraction() <= scope.safe_ceiling.as_fraction()
            for scope in rebate.scopes
        ),
        "normal_settlement_never_adds_principal": all(
            not binding.principal_refund_on_normal_settlement for binding in cost_surface.bindings
        ),
        "void_refund_one_is_scoped_research_convention": all(
            payout.evidence_status == "RESEARCH_CONVENTION"
            and payout.convention_ref == "xinao-research-convention.void-refund-one.v1"
            for binding in cost_surface.bindings
            for case in binding.exact_cases
            for payout in case.tier_payouts
            if payout.terminal_role == "VOID"
        ),
    }
    return _with_hash(
        SettlementCostCompileReport,
        {
            "source_active_projection_hash": probability.source_active_projection_hash,
            "probability_snapshot": probability,
            "rebate_schedule": rebate,
            "cost_surface": cost_surface,
            "odds_space_benchmark": benchmark,
            "artifact_hashes": artifact_hashes,
            "assertions": assertions,
        },
    )


compile_f2 = compile_f2_artifacts


__all__ = [
    "F2_DRAW_DATE",
    "ChannelMetadataDiagnostic",
    "ExactCostCase",
    "ExactProbabilityCase",
    "OddsSpaceBenchmarkVersion",
    "ProbabilityComponentBinding",
    "RationalValue",
    "RebateScheduleVersion",
    "SettlementCostCompileReport",
    "SettlementCostSurfaceVersion",
    "SettlementProbabilitySnapshotVersion",
    "SymbolicDomainProbabilityFormula",
    "active_registry_projection_hash",
    "atomic_ticket_projection_hash",
    "compile_channel_metadata_diagnostic",
    "compile_f2",
    "compile_f2_artifacts",
]
