"""Compile deterministic representative replay evidence for all 13 play families.

This module closes only the F1 representative-replay evidence surface.  It binds
39 asserted cases (positive, negative, and boundary for every family) to the
current semantic registry, functional world, independent selection manifest,
and composite atomic-ticket bindings.  Composite examples are taken lazily from
their canonical generators; the conceptual 21.6 billion tickets are never
materialized.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256, ordered_json_stream_sha256
from xinao.foundation.selection_manifest import (
    AtomicTicketBindingDescriptor,
    AtomicTicketBindingVersion,
    AtomicTicketSelection,
    IndependentExpectedSelectionDomainManifestVersion,
    SelectionManifestComparisonVersion,
    assert_registry_manifest_matches,
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    iter_atomic_ticket_selections,
    load_play_catalog,
)
from xinao.foundation.semantics_combinations import settle_combination
from xinao.foundation.semantics_linked import settle_linked_ticket, settle_parlay_ticket
from xinao.foundation.semantics_registry import (
    EXPECTED_ACTIVE_FAMILY_COUNTS,
    FoundationSemanticsRegistry,
)
from xinao.foundation.semantics_sets import settle_rule
from xinao.foundation.world_compile import (
    DrawReplayInput,
    FamilyReplayCase,
    FamilyReplayResult,
    RepresentativeReplayEvidenceSummary,
    WorldSnapshot,
    replay_family_case,
    summarize_replay_results,
)

FAMILY_ORDER = (
    "special-number",
    "regular-number",
    "regular-position-special",
    "other-explicit",
    "one-zodiac-tail",
    "linked-number",
    "six-zodiac",
    "parlay",
    "multi-select-no-hit",
    "linked-zodiac",
    "linked-tail",
    "multi-select-one-hit",
    "special-regular-hit",
)
CASE_KIND_ORDER = ("POSITIVE", "NEGATIVE", "BOUNDARY")
COMPOSITE_FAMILIES = frozenset(
    {
        "linked-number",
        "parlay",
        "multi-select-no-hit",
        "linked-zodiac",
        "linked-tail",
        "multi-select-one-hit",
        "special-regular-hit",
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
            raise ValueError("content_hash does not bind canonical replay evidence")
        return self


class F1ReplayCaseEvidence(_ContentHashedModel):
    schema_version: Literal["xinao.f1_replay_case_evidence.v1"] = "xinao.f1_replay_case_evidence.v1"
    case: FamilyReplayCase
    result: FamilyReplayResult
    derivation_basis: str
    independent_selection_domain_spec_id: str
    independent_selection_domain_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_selection_domain_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    atomic_ticket_binding_id: str | None = None
    atomic_ticket_binding_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    lazy_ticket_selection: AtomicTicketSelection | None = None
    expanded_atomic_tickets_materialized: Literal[False] = False

    @model_validator(mode="after")
    def validate_case_binding(self) -> F1ReplayCaseEvidence:
        if self.case.case_id != self.result.case_id:
            raise ValueError("case evidence result identity drifted")
        if self.case.case_kind != self.result.case_kind:
            raise ValueError("case evidence kind drifted")
        if self.result.assertion_status != "PASS":
            raise ValueError("F1 evidence may contain only asserted passing replays")
        has_binding = self.atomic_ticket_binding_hash is not None
        if has_binding != (self.lazy_ticket_selection is not None):
            raise ValueError("atomic binding and lazy ticket evidence must appear together")
        if has_binding != (self.atomic_ticket_binding_id is not None):
            raise ValueError("atomic ticket binding identity is incomplete")
        if (
            self.lazy_ticket_selection is not None
            and self.lazy_ticket_selection.binding_id != self.atomic_ticket_binding_id
        ):
            raise ValueError("lazy ticket and atomic binding identities disagree")
        return self


class F1RepresentativeReplayEvidence(_ContentHashedModel):
    schema_version: Literal["xinao.f1_representative_replay_evidence.v1"] = (
        "xinao.f1_representative_replay_evidence.v1"
    )
    evidence_ref: Literal["f1-replay.all-13.positive-negative-boundary.v1"] = (
        "f1-replay.all-13.positive-negative-boundary.v1"
    )
    active_semantics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_event_matrix_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_selection_domain_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_atomic_ticket_binding_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_count: Literal[13] = 13
    case_count: Literal[39] = 39
    family_case_counts: dict[str, int]
    cases: tuple[F1ReplayCaseEvidence, ...] = Field(min_length=39, max_length=39)
    representative_replay_summary: RepresentativeReplayEvidenceSummary
    ordered_case_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_status: Literal["VERIFIED"] = "VERIFIED"
    expanded_atomic_tickets_materialized: Literal[False] = False
    conceptual_atomic_ticket_count: Literal[21652542248] = 21652542248
    foundation_complete: Literal[False] = False
    scope_limitation: str

    @model_validator(mode="after")
    def validate_complete_replay_matrix(self) -> F1RepresentativeReplayEvidence:
        if set(FAMILY_ORDER) != set(EXPECTED_ACTIVE_FAMILY_COUNTS):
            raise ValueError("F1 replay family order is not the canonical 13-family set")
        expected_counts = {family: 3 for family in FAMILY_ORDER}
        if self.family_case_counts != expected_counts:
            raise ValueError("F1 replay evidence must contain three cases per family")
        if tuple(item.result.family_id for item in self.cases[::3]) != FAMILY_ORDER:
            raise ValueError("F1 replay family order drifted")
        case_ids = [item.case.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("F1 replay case ids must be unique")
        by_family: dict[str, set[str]] = {family: set() for family in FAMILY_ORDER}
        for item in self.cases:
            by_family[item.result.family_id].add(item.case.case_kind)
        if any(by_family[family] != set(CASE_KIND_ORDER) for family in FAMILY_ORDER):
            raise ValueError("every family requires positive, negative, and boundary evidence")
        if self.representative_replay_summary.result_status != "VERIFIED":
            raise ValueError("representative replay summary is not verified")
        observed_digest = ordered_json_stream_sha256(item.content_hash for item in self.cases)
        if observed_digest != self.ordered_case_digest:
            raise ValueError("ordered replay case digest drifted")
        return self


@dataclass(frozen=True, slots=True)
class _PlannedCase:
    case: FamilyReplayCase
    derivation_basis: str
    lazy_ticket_selection: AtomicTicketSelection | None = None


@dataclass(frozen=True, slots=True)
class _SelectionOracle:
    independent: IndependentExpectedSelectionDomainManifestVersion
    comparison: SelectionManifestComparisonVersion
    atomic: AtomicTicketBindingVersion
    independent_by_baseline: dict[str, Any]
    registry_by_spec_id: dict[str, Any]
    atomic_by_baseline: dict[str, AtomicTicketBindingDescriptor]


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    projected = model.model_construct(content_hash="0" * 64, **dict(payload))
    materialized = projected.model_dump(mode="json", exclude={"content_hash"})
    materialized["content_hash"] = canonical_sha256(materialized)
    return model.model_validate(materialized)


def _selection_oracle(
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
) -> _SelectionOracle:
    catalog = load_play_catalog()
    independent = compile_independent_selection_manifest(catalog)
    comparison = assert_registry_manifest_matches(independent, registry.expected_selection_domain)
    atomic = compile_atomic_ticket_bindings(catalog, independent)
    active_selection_hash = ordered_json_stream_sha256(
            {
                "spec_id": spec.spec_id,
                "family_id": spec.family_id,
                "play_id": spec.play_id,
                "component_baseline_ids": spec.component_baseline_ids,
                "domain_kind": spec.domain_kind,
                "arity_min": spec.arity_min,
                "arity_max": spec.arity_max,
                "exact_atomic_selection_count": spec.exact_atomic_selection_count,
                "canonical_encoding": spec.canonical_encoding,
                "participating_baseline_ids_rule": spec.participating_baseline_ids_rule,
            }
            for spec in independent.specifications
    )
    active_atomic_hash = ordered_json_stream_sha256(
        binding.content_hash for binding in atomic.bindings
    )
    if world.active_selection_domain_structural_hash != active_selection_hash:
        raise ValueError("world and active selection domain disagree")
    if world.active_atomic_ticket_binding_structural_hash != active_atomic_hash:
        raise ValueError("world and active atomic ticket binding disagree")
    independent_by_baseline: dict[str, Any] = {}
    for spec in independent.specifications:
        for baseline_id in spec.component_baseline_ids:
            independent_by_baseline[baseline_id] = spec
    atomic_by_baseline: dict[str, AtomicTicketBindingDescriptor] = {}
    for binding in atomic.bindings:
        for baseline_id in binding.component_baseline_ids:
            atomic_by_baseline[baseline_id] = binding
    return _SelectionOracle(
        independent=independent,
        comparison=comparison,
        atomic=atomic,
        independent_by_baseline=independent_by_baseline,
        registry_by_spec_id={
            spec.spec_id: spec for spec in registry.expected_selection_domain.specifications
        },
        atomic_by_baseline=atomic_by_baseline,
    )


def _case(
    family_id: str,
    case_kind: Literal["POSITIVE", "NEGATIVE", "BOUNDARY"],
    draw_id: str,
    component_baseline_ids: Sequence[str],
    *,
    selection: Sequence[int | str] = (),
    expected_outcome: Literal["HIT", "MISS", "VOID"],
    derivation_basis: str,
    ticket: AtomicTicketSelection | None = None,
) -> _PlannedCase:
    return _PlannedCase(
        case=FamilyReplayCase(
            case_id=f"f1-replay:{family_id}:{case_kind.lower()}:v1",
            case_kind=case_kind,
            draw_id=draw_id,
            component_baseline_ids=tuple(component_baseline_ids),
            selection=tuple(selection),
            expected_outcome=expected_outcome,
        ),
        derivation_basis=derivation_basis,
        lazy_ticket_selection=ticket,
    )


def _first_draw(
    draws: Sequence[DrawReplayInput],
    predicate: Callable[[DrawReplayInput], bool],
    description: str,
) -> DrawReplayInput:
    draw = next((item for item in draws if predicate(item)), None)
    if draw is None:
        raise ValueError(f"formal world has no deterministic replay draw for {description}")
    return draw


def _first_outcome_draw(
    draws: Sequence[DrawReplayInput],
    outcome: Callable[[DrawReplayInput], str],
    expected: Literal["HIT", "MISS", "VOID"],
    description: str,
) -> DrawReplayInput:
    return _first_draw(draws, lambda draw: outcome(draw) == expected, description)


def _ticket(
    binding: AtomicTicketBindingDescriptor,
    selection_id: str | None = None,
) -> AtomicTicketSelection:
    iterator = iter_atomic_ticket_selections(binding)
    if selection_id is None:
        return next(iterator)
    ticket = next((item for item in iterator if item.selection_id == selection_id), None)
    if ticket is None:
        raise ValueError(f"atomic binding has no canonical ticket {selection_id}")
    return ticket


def _number_selection(ticket: AtomicTicketSelection) -> tuple[int, ...]:
    return tuple(int(value) for value in ticket.selection_id.split(","))


def _source_record_maps(registry: FoundationSemanticsRegistry) -> tuple[dict[str, Any], ...]:
    source = registry.source_artifacts
    return (
        {record.baseline_id: record for record in source.basic_records},
        {record.baseline_id: record for record in source.set_compilation.rule_semantic_map.records},
        {record.baseline_id: record for record in source.combination_records},
        {
            record.baseline_id: record
            for record in source.linked_compilation.rule_semantic_map.records
        },
    )


def _plan_replays(
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
    oracle: _SelectionOracle,
) -> tuple[_PlannedCase, ...]:
    draws = tuple(sorted(world.draw_inputs, key=lambda item: (item.draw_date, item.draw_id)))
    if not draws:
        raise ValueError("world has no draw replay inputs")
    _, set_records, combination_records, linked_records = _source_record_maps(registry)
    first = draws[0]
    special_49 = _first_draw(draws, lambda draw: draw.numbers[-1] == 49, "special 49")
    regular_49 = _first_draw(draws, lambda draw: 49 in draw.numbers[:6], "regular 49")
    position_4_49 = _first_draw(draws, lambda draw: draw.numbers[3] == 49, "position 4 value 49")
    first_two_49 = _first_draw(draws, lambda draw: 49 in draw.numbers[:2], "parlay leg 49")
    zero_tail = _first_draw(
        draws,
        lambda draw: any(number % 10 == 0 for number in draw.numbers),
        "zero-tail boundary",
    )
    plans: list[_PlannedCase] = []

    special_value = first.numbers[-1]
    special_miss = next(number for number in range(1, 50) if number != special_value)
    plans.extend(
        (
            _case(
                "special-number",
                "POSITIVE",
                first.draw_id,
                ("BO0001",),
                selection=(special_value,),
                expected_outcome="HIT",
                derivation_basis="SPECIAL_POSITION_EXACT_VALUE_FROM_WORLD_DRAW",
            ),
            _case(
                "special-number",
                "NEGATIVE",
                first.draw_id,
                ("BO0001",),
                selection=(special_miss,),
                expected_outcome="MISS",
                derivation_basis="LOWEST_NON_SPECIAL_VALUE_IN_1_TO_49",
            ),
            _case(
                "special-number",
                "BOUNDARY",
                special_49.draw_id,
                ("BO0002",),
                selection=("合单",),
                expected_outcome="VOID",
                derivation_basis="SPECIAL_VALUE_49_VOID_BOUNDARY",
            ),
        )
    )

    plans.extend(
        (
            _case(
                "regular-number",
                "POSITIVE",
                first.draw_id,
                ("BO0025",),
                selection=(first.numbers[0],),
                expected_outcome="HIT",
                derivation_basis="FIRST_REGULAR_NUMBER_MEMBERSHIP",
            ),
            _case(
                "regular-number",
                "NEGATIVE",
                first.draw_id,
                ("BO0025",),
                selection=(first.numbers[-1],),
                expected_outcome="MISS",
                derivation_basis="SPECIAL_NUMBER_EXCLUDED_FROM_FIRST_SIX",
            ),
            _case(
                "regular-number",
                "BOUNDARY",
                regular_49.draw_id,
                ("BO0025",),
                selection=(49,),
                expected_outcome="HIT",
                derivation_basis="UPPER_SELECTION_ENDPOINT_49_IN_REGULAR_SET",
            ),
        )
    )

    plans.extend(
        (
            _case(
                "regular-position-special",
                "POSITIVE",
                first.draw_id,
                ("BO0037",),
                selection=(first.numbers[0],),
                expected_outcome="HIT",
                derivation_basis="ORDERED_POSITION_ONE_EXACT_VALUE",
            ),
            _case(
                "regular-position-special",
                "NEGATIVE",
                first.draw_id,
                ("BO0037",),
                selection=(first.numbers[1],),
                expected_outcome="MISS",
                derivation_basis="MEMBERSHIP_ELSEWHERE_DOES_NOT_MATCH_POSITION_ONE",
            ),
            _case(
                "regular-position-special",
                "BOUNDARY",
                position_4_49.draw_id,
                ("BO0065",),
                selection=("单",),
                expected_outcome="VOID",
                derivation_basis="ORDERED_POSITION_FOUR_VALUE_49_VOID_BOUNDARY",
            ),
        )
    )

    other_record = set_records["BO0107"]

    def other_outcome(draw: DrawReplayInput) -> str:
        return settle_rule(other_record, draw=draw.numbers, draw_date=draw.draw_date)

    plans.extend(
        (
            _case(
                "other-explicit",
                "POSITIVE",
                _first_outcome_draw(draws, other_outcome, "HIT", "other-explicit hit").draw_id,
                ("BO0107",),
                expected_outcome="HIT",
                derivation_basis="FIRST_HISTORICAL_HALF_WAVE_HIT",
            ),
            _case(
                "other-explicit",
                "NEGATIVE",
                _first_outcome_draw(draws, other_outcome, "MISS", "other-explicit miss").draw_id,
                ("BO0107",),
                expected_outcome="MISS",
                derivation_basis="FIRST_HISTORICAL_HALF_WAVE_MISS",
            ),
            _case(
                "other-explicit",
                "BOUNDARY",
                special_49.draw_id,
                ("BO0107",),
                expected_outcome="VOID",
                derivation_basis="HALF_WAVE_SPECIAL_49_VOID_BOUNDARY",
            ),
        )
    )

    one_tail_record = set_records["BO0180"]

    def one_tail_outcome(draw: DrawReplayInput) -> str:
        return settle_rule(one_tail_record, draw=draw.numbers, draw_date=draw.draw_date)

    plans.extend(
        (
            _case(
                "one-zodiac-tail",
                "POSITIVE",
                _first_outcome_draw(draws, one_tail_outcome, "HIT", "one-tail hit").draw_id,
                ("BO0180",),
                expected_outcome="HIT",
                derivation_basis="FIRST_HISTORICAL_ZERO_TAIL_AT_LEAST_ONCE_HIT",
            ),
            _case(
                "one-zodiac-tail",
                "NEGATIVE",
                _first_outcome_draw(draws, one_tail_outcome, "MISS", "one-tail miss").draw_id,
                ("BO0180",),
                expected_outcome="MISS",
                derivation_basis="FIRST_HISTORICAL_ZERO_TAIL_ABSENCE",
            ),
            _case(
                "one-zodiac-tail",
                "BOUNDARY",
                zero_tail.draw_id,
                ("BO0180",),
                expected_outcome=one_tail_outcome(zero_tail),
                derivation_basis="ZERO_TAIL_FOUR_MEMBER_CARDINALITY_BOUNDARY",
            ),
        )
    )

    linked_number_binding = oracle.atomic_by_baseline["BO0213"]
    linked_number_ticket = _ticket(linked_number_binding)
    linked_number_selection = _number_selection(linked_number_ticket)
    linked_number_record = combination_records["BO0213"]

    def linked_number_outcome(draw: DrawReplayInput) -> str:
        return settle_combination(
            entry=linked_number_record,
            draw=draw.numbers,
            selection=linked_number_selection,
        ).outcome

    linked_number_boundary_ticket = _ticket(linked_number_binding, "48,49")
    linked_number_boundary_selection = _number_selection(linked_number_boundary_ticket)
    linked_number_boundary_outcome = settle_combination(
        entry=linked_number_record,
        draw=special_49.numbers,
        selection=linked_number_boundary_selection,
    ).outcome
    plans.extend(
        (
            _case(
                "linked-number",
                "POSITIVE",
                _first_outcome_draw(
                    draws, linked_number_outcome, "HIT", "linked-number hit"
                ).draw_id,
                linked_number_ticket.participating_baseline_ids,
                selection=linked_number_selection,
                expected_outcome="HIT",
                derivation_basis="FIRST_LAZY_CANONICAL_TICKET_HISTORICAL_HIT",
                ticket=linked_number_ticket,
            ),
            _case(
                "linked-number",
                "NEGATIVE",
                _first_outcome_draw(
                    draws, linked_number_outcome, "MISS", "linked-number miss"
                ).draw_id,
                linked_number_ticket.participating_baseline_ids,
                selection=linked_number_selection,
                expected_outcome="MISS",
                derivation_basis="FIRST_LAZY_CANONICAL_TICKET_HISTORICAL_MISS",
                ticket=linked_number_ticket,
            ),
            _case(
                "linked-number",
                "BOUNDARY",
                special_49.draw_id,
                linked_number_boundary_ticket.participating_baseline_ids,
                selection=linked_number_boundary_selection,
                expected_outcome=linked_number_boundary_outcome,
                derivation_basis="UPPER_NUMBER_PAIR_48_49_AND_SPECIAL_REGULAR_SPLIT",
                ticket=linked_number_boundary_ticket,
            ),
        )
    )

    six_selection = ("鼠", "牛", "虎", "兔", "龙", "蛇")
    six_record = set_records["BO0218"]

    def six_outcome(draw: DrawReplayInput) -> str:
        return settle_rule(
            six_record,
            draw=draw.numbers,
            draw_date=draw.draw_date,
            selection=six_selection,
        )

    plans.extend(
        (
            _case(
                "six-zodiac",
                "POSITIVE",
                _first_outcome_draw(draws, six_outcome, "HIT", "six-zodiac hit").draw_id,
                ("BO0218",),
                selection=six_selection,
                expected_outcome="HIT",
                derivation_basis="FIXED_SIX_LABEL_SELECTION_SPECIAL_MEMBERSHIP_HIT",
            ),
            _case(
                "six-zodiac",
                "NEGATIVE",
                _first_outcome_draw(draws, six_outcome, "MISS", "six-zodiac miss").draw_id,
                ("BO0218",),
                selection=six_selection,
                expected_outcome="MISS",
                derivation_basis="FIXED_SIX_LABEL_SELECTION_SPECIAL_MEMBERSHIP_MISS",
            ),
            _case(
                "six-zodiac",
                "BOUNDARY",
                special_49.draw_id,
                ("BO0218",),
                selection=six_selection,
                expected_outcome="VOID",
                derivation_basis="SIX_ZODIAC_SPECIAL_49_VOID_BOUNDARY",
            ),
        )
    )

    def add_composite_family(
        family_id: str,
        anchor_baseline: str,
        *,
        boundary_draw: DrawReplayInput,
        boundary_basis: str,
        boundary_ticket_id: str | None = None,
    ) -> None:
        binding = oracle.atomic_by_baseline[anchor_baseline]
        ticket = _ticket(binding)
        boundary_ticket = (
            _ticket(binding, boundary_ticket_id) if boundary_ticket_id is not None else ticket
        )

        def outcome(selected: AtomicTicketSelection, draw: DrawReplayInput) -> str:
            if family_id in {
                "multi-select-no-hit",
                "multi-select-one-hit",
                "special-regular-hit",
            }:
                record = combination_records[selected.participating_baseline_ids[0]]
                return settle_combination(
                    entry=record,
                    draw=draw.numbers,
                    selection=_number_selection(selected),
                ).outcome
            records = tuple(
                linked_records[baseline_id] for baseline_id in selected.participating_baseline_ids
            )
            if family_id == "parlay":
                return settle_parlay_ticket(records, draw=draw.numbers).outcome
            return settle_linked_ticket(
                records, draw=draw.numbers, draw_date=draw.draw_date
            ).outcome

        def selection(selected: AtomicTicketSelection) -> tuple[int | str, ...]:
            if family_id in {
                "multi-select-no-hit",
                "multi-select-one-hit",
                "special-regular-hit",
            }:
                return _number_selection(selected)
            return ()

        hit_draw = _first_outcome_draw(
            draws, lambda draw: outcome(ticket, draw), "HIT", f"{family_id} hit"
        )
        miss_draw = _first_outcome_draw(
            draws, lambda draw: outcome(ticket, draw), "MISS", f"{family_id} miss"
        )
        plans.extend(
            (
                _case(
                    family_id,
                    "POSITIVE",
                    hit_draw.draw_id,
                    ticket.participating_baseline_ids,
                    selection=selection(ticket),
                    expected_outcome="HIT",
                    derivation_basis="FIRST_LAZY_CANONICAL_TICKET_HISTORICAL_HIT",
                    ticket=ticket,
                ),
                _case(
                    family_id,
                    "NEGATIVE",
                    miss_draw.draw_id,
                    ticket.participating_baseline_ids,
                    selection=selection(ticket),
                    expected_outcome="MISS",
                    derivation_basis="FIRST_LAZY_CANONICAL_TICKET_HISTORICAL_MISS",
                    ticket=ticket,
                ),
                _case(
                    family_id,
                    "BOUNDARY",
                    boundary_draw.draw_id,
                    boundary_ticket.participating_baseline_ids,
                    selection=selection(boundary_ticket),
                    expected_outcome=outcome(boundary_ticket, boundary_draw),
                    derivation_basis=boundary_basis,
                    ticket=boundary_ticket,
                ),
            )
        )

    add_composite_family(
        "parlay",
        "BO0219",
        boundary_draw=first_two_49,
        boundary_basis="MINIMUM_ARITY_LAZY_TICKET_WITH_POSITION_VALUE_49_VOID_LEG",
    )
    add_composite_family(
        "multi-select-no-hit",
        "BO0261",
        boundary_draw=special_49,
        boundary_basis="MINIMUM_ARITY_FIRST_CANONICAL_NUMBER_POOL_WITH_SPECIAL_49_DRAW",
    )
    add_composite_family(
        "linked-zodiac",
        "BO0267",
        boundary_draw=special_49,
        boundary_basis="FIRST_CANONICAL_ZODIAC_PAIR_WITH_LUNAR_DATE_AND_NUMBER_49",
    )
    add_composite_family(
        "linked-tail",
        "BO0363",
        boundary_draw=zero_tail,
        boundary_basis="FIRST_CANONICAL_PAIR_INCLUDING_FOUR_MEMBER_ZERO_TAIL",
    )
    add_composite_family(
        "multi-select-one-hit",
        "BO0423",
        boundary_draw=special_49,
        boundary_basis="MINIMUM_ARITY_FIRST_CANONICAL_NUMBER_POOL_WITH_SPECIAL_49_DRAW",
    )
    add_composite_family(
        "special-regular-hit",
        "BO0429",
        boundary_draw=regular_49,
        boundary_basis="UPPER_SINGLE_NUMBER_ENDPOINT_49_IN_SEVEN_DRAW",
        boundary_ticket_id="49",
    )

    if tuple(plan.case.case_kind for plan in plans[::3]) != ("POSITIVE",) * 13:
        raise AssertionError("replay plan lost canonical family triplets")
    if tuple(plan.case.component_baseline_ids for plan in plans) == ():
        raise AssertionError("replay plan is empty")
    observed_order = tuple(plan.case.case_id.split(":")[1] for plan in plans[::3])
    if observed_order != FAMILY_ORDER:
        raise AssertionError("replay plan family order drifted")
    return tuple(plans)


def _case_evidence(
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
    oracle: _SelectionOracle,
    planned: _PlannedCase,
) -> F1ReplayCaseEvidence:
    result = replay_family_case(registry, world, planned.case)
    specs = {
        oracle.independent_by_baseline[baseline_id].spec_id: (
            oracle.independent_by_baseline[baseline_id]
        )
        for baseline_id in planned.case.component_baseline_ids
    }
    if len(specs) != 1:
        raise ValueError("representative replay crosses independent selection domains")
    independent_spec = next(iter(specs.values()))
    registry_spec = oracle.registry_by_spec_id[independent_spec.spec_id]
    atomic_bindings = {
        oracle.atomic_by_baseline.get(baseline_id)
        for baseline_id in planned.case.component_baseline_ids
    }
    if None in atomic_bindings:
        if len(atomic_bindings) != 1 or result.family_id in COMPOSITE_FAMILIES:
            raise ValueError("representative replay has an incomplete atomic binding")
        atomic = None
    else:
        by_hash = {
            binding.content_hash: binding for binding in atomic_bindings if binding is not None
        }
        if len(by_hash) != 1:
            raise ValueError("representative replay mixes atomic ticket bindings")
        atomic = next(iter(by_hash.values()))
    ticket = planned.lazy_ticket_selection
    if atomic is None:
        if ticket is not None or result.atomic_ticket_binding_hash is not None:
            raise ValueError("non-composite replay unexpectedly carries a lazy ticket")
    else:
        if ticket is None or ticket.binding_id != atomic.binding_id:
            raise ValueError("composite replay is not bound to its lazy canonical ticket")
        if result.atomic_ticket_binding_hash != atomic.content_hash:
            raise ValueError("world replay and independent atomic binding disagree")
        if tuple(ticket.participating_baseline_ids) != planned.case.component_baseline_ids:
            raise ValueError("lazy ticket participating components drifted")
        if result.family_id in {
            "linked-number",
            "multi-select-no-hit",
            "multi-select-one-hit",
            "special-regular-hit",
        } and _number_selection(ticket) != tuple(planned.case.selection):
            raise ValueError("numeric lazy ticket selection drifted")
    return _with_hash(
        F1ReplayCaseEvidence,
        {
            "case": planned.case,
            "result": result,
            "derivation_basis": planned.derivation_basis,
            "independent_selection_domain_spec_id": independent_spec.spec_id,
            "independent_selection_domain_spec_hash": independent_spec.content_hash,
            "registry_selection_domain_spec_hash": registry_spec.content_hash,
            "atomic_ticket_binding_id": atomic.binding_id if atomic is not None else None,
            "atomic_ticket_binding_hash": (atomic.content_hash if atomic is not None else None),
            "lazy_ticket_selection": ticket,
            "expanded_atomic_tickets_materialized": False,
        },
    )


def compile_f1_replay_evidence(
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
) -> F1RepresentativeReplayEvidence:
    """Compile the content-addressed 13 x 3 representative replay evidence."""

    if world.active_semantics_hash != registry.active_physical_semantics_hash:
        raise ValueError("world and active semantics identity disagree")
    oracle = _selection_oracle(registry, world)
    planned = _plan_replays(registry, world, oracle)
    cases = tuple(_case_evidence(registry, world, oracle, item) for item in planned)
    results = tuple(item.result for item in cases)
    summary = summarize_replay_results(results)
    if summary.result_status != "VERIFIED":
        raise ValueError("13-family representative replay matrix is not verified")
    family_counts = Counter(result.family_id for result in results)
    return _with_hash(
        F1RepresentativeReplayEvidence,
        {
            "active_semantics_hash": registry.active_physical_semantics_hash,
            "source_world_snapshot_hash": world.content_hash,
            "source_event_matrix_snapshot_hash": world.event_matrix_snapshot_hash,
            "active_selection_domain_structural_hash": (
                world.active_selection_domain_structural_hash
            ),
            "active_atomic_ticket_binding_structural_hash": (
                world.active_atomic_ticket_binding_structural_hash
            ),
            "family_count": 13,
            "case_count": 39,
            "family_case_counts": {family: family_counts[family] for family in FAMILY_ORDER},
            "cases": cases,
            "representative_replay_summary": summary,
            "ordered_case_digest": ordered_json_stream_sha256(item.content_hash for item in cases),
            "result_status": "VERIFIED",
            "expanded_atomic_tickets_materialized": False,
            "conceptual_atomic_ticket_count": oracle.independent.exact_atomic_selection_count,
            "foundation_complete": False,
            "scope_limitation": (
                "VERIFIED closes only F1 ACTIVE representative replay evidence; "
                "catalog-only route quotes are outside this object. This does not claim "
                "F2 or later research is complete."
            ),
        },
    )


__all__ = [
    "CASE_KIND_ORDER",
    "COMPOSITE_FAMILIES",
    "FAMILY_ORDER",
    "F1ReplayCaseEvidence",
    "F1RepresentativeReplayEvidence",
    "compile_f1_replay_evidence",
]
