"""F1 semantics for linked-zodiac, linked-tail, and regular-position parlays.

The 198 catalog rows covered here are quote components, not an already
materialised universe of atomic bets.  Linked rows are one zodiac/tail quote
component and parlay rows are one regular-position leg.  The selection-domain
candidate therefore records exact combinatorial counts and exposes a lazy
iterator instead of pretending that the expanded Cartesian product was stored.

Catalog identity and displayed quotes are page facts.  Predicates, linked
quote aggregation, 49 handling, and probability models are explicitly marked
``RESEARCH_CONVENTION``.  A normal hit pays the quoted amount ``q`` (including
the stake), a miss pays zero, and no extra principal is added.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from itertools import combinations, product
from math import comb, prod
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256
from xinao.foundation.f4_snapshot_runtime import load_object as load_snapshot_object
from xinao.foundation.semantics_basic import BLUE_NUMBERS, GREEN_NUMBERS, RED_NUMBERS
from xinao.foundation.semantics_sets import zodiac_number_table

DEFAULT_PLAY_CATALOG_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_catalog.v1.json"
)

TARGET_FAMILY_COUNTS = {
    "linked-zodiac": 96,
    "linked-tail": 60,
    "parlay": 42,
}
TARGET_FAMILY_IDS = frozenset(TARGET_FAMILY_COUNTS)

ZODIAC_ORDER = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
TAIL_ORDER = tuple(f"{tail}尾" for tail in range(10))
PARLAY_ATTRIBUTE_ORDER = ("ODD", "EVEN", "BIG", "SMALL", "RED", "GREEN", "BLUE")

LinkedFamily = Literal["linked-zodiac", "linked-tail"]
TargetFamily = Literal["linked-zodiac", "linked-tail", "parlay"]
Polarity = Literal["HIT_ALL_LABELS", "MISS_ALL_LABELS", "ALL_LEGS_NON_MISS"]
ParlayAttribute = Literal["ODD", "EVEN", "BIG", "SMALL", "RED", "GREEN", "BLUE"]
Outcome = Literal["HIT", "MISS"]

_LINKED_ZODIAC_PATTERN = re.compile(r"^([二三四五])肖连\[(中|不中)\]$")
_LINKED_TAIL_PATTERN = re.compile(r"^([二三四])尾连\[(中|不中)\]$")
_PARLAY_OPTION_PATTERN = re.compile(r"^正([1-6])-(单|双|大|小|红波|绿波|蓝波)$")
_BASELINE_PATTERN = re.compile(r"^BO\d{4}$")
_CHINESE_ARITY = {"二": 2, "三": 3, "四": 4, "五": 5}
_PARLAY_ATTRIBUTE = {
    "单": "ODD",
    "双": "EVEN",
    "大": "BIG",
    "小": "SMALL",
    "红波": "RED",
    "绿波": "GREEN",
    "蓝波": "BLUE",
}
_COLOR_NUMBERS = {
    "RED": RED_NUMBERS,
    "GREEN": GREEN_NUMBERS,
    "BLUE": BLUE_NUMBERS,
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContentHashedModel(_FrozenModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> _ContentHashedModel:
        body = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_sha256(body) != self.content_hash:
            raise ValueError("content_hash does not bind the canonical payload")
        return self


class Coverage(_FrozenModel):
    catalog_total: Literal[433] = 433
    mapped_baselines: Literal[198] = 198
    remaining_baselines: Literal[235] = 235
    family_counts: dict[str, int]
    foundation_complete: Literal[False] = False


class InterpretationRecord(_FrozenModel):
    interpretation_ref: str
    status: Literal["ACTIVE", "ALTERNATE"]
    scope: str
    statement: str
    assumption_class: Literal["RESEARCH_CONVENTION"] = "RESEARCH_CONVENTION"
    source_refs: tuple[str, ...]


class RuleSemanticRecord(_ContentHashedModel):
    """One catalog quote component with deterministic semantic bindings."""

    schema_version: Literal["xinao.rule_semantic_record.linked.v1"] = (
        "xinao.rule_semantic_record.linked.v1"
    )
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: TargetFamily
    play_id: str
    play_name: str
    pid: int
    tid: int
    option_name: str
    option_range: str | None
    catalog_role: Literal["LINKED_LABEL_QUOTE_COMPONENT", "PARLAY_SINGLE_LEG_QUOTE_COMPONENT"]
    semantic_family_ref: Literal[
        "zodiac-link-all-seven.v1",
        "tail-link-all-seven.v1",
        "ordered-regular-position-parlay.v1",
    ]
    rule_version_ref: Literal["linked-and-parlay-rule-semantics.v1"] = (
        "linked-and-parlay-rule-semantics.v1"
    )
    selection_domain_ref: Literal["linked-and-parlay-lazy-selection-domain.v1"] = (
        "linked-and-parlay-lazy-selection-domain.v1"
    )
    predicate_ref: str
    settlement_function_ref: str
    probability_formula_ref: str
    settlement_tiers: tuple[Literal["HIT", "MISS"], ...]
    draw_scope: Literal["ALL_SEVEN_UNORDERED", "ORDERED_REGULAR_POSITIONS_1_TO_6"]
    selection_arity_min: int = Field(ge=2, le=6)
    selection_arity_max: int = Field(ge=2, le=6)
    polarity: Polarity
    component_label: str
    component_position: int | None = Field(default=None, ge=1, le=6)
    component_attribute: ParlayAttribute | None = None
    catalog_number_set_snapshot: tuple[int, ...]
    snapshot_payout_components: tuple[str, ...] = Field(min_length=1, max_length=1)
    quote_aggregation_ref: Literal["MIN_SELECTED_COMPONENT", "PRODUCT_NON_VOID_LEGS"]
    hit_payout_ref: Literal["PAYOUT_EQUALS_Q_INCLUDING_STAKE"] = "PAYOUT_EQUALS_Q_INCLUDING_STAKE"
    miss_payout: Literal["0"] = "0"
    principal_refund_on_normal_settlement: Literal[False] = False
    void_policy: Literal["NO_VOID", "PROPERTY_49_LEG_MULTIPLIER_ONE"]
    interpretation_ref: str
    alternative_interpretation_refs: tuple[str, ...]
    semantic_evidence_statuses: tuple[Literal["EXPLICIT_PAGE", "RESEARCH_CONVENTION"], ...]
    assumption_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    raw_site_fields: dict[str, Any]

    @model_validator(mode="after")
    def validate_family_bindings(self) -> RuleSemanticRecord:
        if self.semantic_evidence_statuses != ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"):
            raise ValueError("page identity and research convention must both be explicit")
        _positive_quote(self.snapshot_payout_components[0])
        if self.family_id == "parlay":
            if self.catalog_role != "PARLAY_SINGLE_LEG_QUOTE_COMPONENT":
                raise ValueError("parlay rows must remain single-leg quote components")
            if self.component_position is None or self.component_attribute is None:
                raise ValueError("parlay rows require a position and attribute")
            if self.catalog_number_set_snapshot:
                raise ValueError("parlay attribute legs do not use catalog number-set snapshots")
            if (self.selection_arity_min, self.selection_arity_max) != (2, 6):
                raise ValueError("parlay expansion must retain the 2-6 position domain")
        else:
            if self.catalog_role != "LINKED_LABEL_QUOTE_COMPONENT":
                raise ValueError("linked rows must remain label quote components")
            if self.component_position is not None or self.component_attribute is not None:
                raise ValueError("linked label components cannot bind a regular position")
            if self.selection_arity_min != self.selection_arity_max:
                raise ValueError("each linked play requires a fixed number of labels")
            if not self.catalog_number_set_snapshot:
                raise ValueError("linked labels must preserve the page number-set snapshot")
        return self


class SelectionDomainSpec(_ContentHashedModel):
    spec_id: str
    family_id: TargetFamily
    play_id: str
    play_name: str
    component_baseline_ids: tuple[str, ...]
    component_label_domain: tuple[str, ...]
    atomic_selection_kind: Literal["DISTINCT_LABEL_COMBINATION", "UNIQUE_POSITION_LEG_PRODUCT"]
    arity_min: int = Field(ge=2, le=6)
    arity_max: int = Field(ge=2, le=6)
    exact_atomic_selection_count: int = Field(gt=0)
    expansion_policy: Literal["LAZY_COMBINATORIAL"] = "LAZY_COMBINATORIAL"
    materialized_atomic_selection_count: Literal[0] = 0
    constraint_ref: str
    probability_cache_signature_ref: str
    quote_aggregation_ref: Literal["MIN_SELECTED_COMPONENT", "PRODUCT_NON_VOID_LEGS"]
    interpretation_ref: str
    alternative_interpretation_refs: tuple[str, ...]


class ExpectedSelectionDomainCandidate(_ContentHashedModel):
    schema_version: Literal["xinao.expected_selection_domain.linked.v1"] = (
        "xinao.expected_selection_domain.linked.v1"
    )
    domain_ref: Literal["linked-and-parlay-lazy-selection-domain.v1"] = (
        "linked-and-parlay-lazy-selection-domain.v1"
    )
    baseline_component_count: Literal[198] = 198
    specification_count: Literal[15] = 15
    exact_atomic_selection_count: int
    materialized_atomic_selection_count: Literal[0] = 0
    expansion_policy: Literal["LAZY_COMBINATORIAL"] = "LAZY_COMBINATORIAL"
    specifications: tuple[SelectionDomainSpec, ...]


class RuleSemanticMapSliceVersion(_ContentHashedModel):
    schema_version: Literal["xinao.rule_semantic_map.linked.v1"] = (
        "xinao.rule_semantic_map.linked.v1"
    )
    map_ref: Literal["linked-and-parlay-rule-semantic-map.v1"] = (
        "linked-and-parlay-rule-semantic-map.v1"
    )
    source_catalog_ref: str
    source_catalog_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage: Coverage
    records: tuple[RuleSemanticRecord, ...]


class LinkedSemanticsCompilation(_ContentHashedModel):
    schema_version: Literal["xinao.linked_semantics_compilation.v1"] = (
        "xinao.linked_semantics_compilation.v1"
    )
    rule_semantic_map: RuleSemanticMapSliceVersion
    expected_selection_domain: ExpectedSelectionDomainCandidate
    interpretations: tuple[InterpretationRecord, ...]


class TicketSettlementResult(_FrozenModel):
    schema_version: Literal["xinao.linked_ticket_settlement.v1"] = (
        "xinao.linked_ticket_settlement.v1"
    )
    family_id: TargetFamily
    play_id: str
    component_baseline_ids: tuple[str, ...]
    selection_labels: tuple[str, ...]
    outcome: Outcome
    unit_payout: str
    payout_includes_stake: Literal[True] = True
    principal_refund_added: Literal[False] = False
    void_leg_positions: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AtomicSelection:
    """One lazily expanded ticket identity; generation does not imply persistence."""

    spec_id: str
    selection_key: str
    component_baseline_ids: tuple[str, ...]


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    body = dict(payload)
    body["content_hash"] = canonical_sha256(body)
    return model.model_validate(body)


def load_play_catalog(path: Path = DEFAULT_PLAY_CATALOG_PATH) -> dict[str, Any]:
    raw = load_snapshot_object(path)
    if not isinstance(raw, dict):
        raise ValueError("play catalog must be a JSON object")
    return raw


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"catalog row is missing {key}")
    return value


def _required_int(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"catalog row {key} must be an integer")
    return value


def _positive_quote(value: str) -> Decimal:
    if not isinstance(value, str) or not value:
        raise TypeError("quote must be a non-empty decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("quote must be a valid decimal string") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("quote must be positive and finite")
    return result


def _quote(row: Mapping[str, Any]) -> tuple[str, ...]:
    raw = row.get("baseline_odds_components")
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], str):
        raise ValueError("target component row must contain exactly one quote")
    _positive_quote(raw[0])
    return (raw[0],)


def _number_set(value: Any, *, baseline_id: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{baseline_id}.option_range must contain a number set")
    try:
        numbers = tuple(int(part) for part in value.split(","))
    except ValueError as exc:
        raise ValueError(f"{baseline_id}.option_range contains a non-number") from exc
    if len(numbers) != len(set(numbers)) or any(not 1 <= number <= 49 for number in numbers):
        raise ValueError(f"{baseline_id}.option_range must contain unique numbers 1..49")
    return numbers


def _raw_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in sorted(row.items())}


def _linked_play(row: Mapping[str, Any], family_id: LinkedFamily) -> tuple[int, Polarity]:
    play_name = _required_text(row, "play_name")
    pattern = _LINKED_ZODIAC_PATTERN if family_id == "linked-zodiac" else _LINKED_TAIL_PATTERN
    match = pattern.fullmatch(play_name)
    if match is None:
        raise ValueError(f"unsupported {family_id} play_name: {play_name}")
    arity = _CHINESE_ARITY[match.group(1)]
    polarity: Polarity = "HIT_ALL_LABELS" if match.group(2) == "中" else "MISS_ALL_LABELS"
    return arity, polarity


def _compile_linked_record(row: Mapping[str, Any], family_id: LinkedFamily) -> RuleSemanticRecord:
    baseline_id = _required_text(row, "baseline_id")
    pid = _required_int(row, "pid")
    tid = _required_int(row, "tid")
    expected_pid = 10 if family_id == "linked-zodiac" else 11
    expected_tids = range(47, 55) if family_id == "linked-zodiac" else range(55, 61)
    if pid != expected_pid or tid not in expected_tids or row.get("panel") is not None:
        raise ValueError(f"{baseline_id} has an invalid {family_id} catalog identity")
    if row.get("bet_shape") != "复式/拖头":
        raise ValueError(f"{baseline_id} must retain the 复式/拖头 component shape")
    arity, polarity = _linked_play(row, family_id)
    first_tid = 47 if family_id == "linked-zodiac" else 55
    side_offset = 4 if family_id == "linked-zodiac" else 3
    expected_tid = first_tid + arity - 2 + (side_offset if polarity == "MISS_ALL_LABELS" else 0)
    if tid != expected_tid:
        raise ValueError(f"{baseline_id} tid does not match its arity and polarity")
    option_name = _required_text(row, "option_name")
    allowed = ZODIAC_ORDER if family_id == "linked-zodiac" else TAIL_ORDER
    if option_name not in allowed:
        raise ValueError(f"{baseline_id} has an unknown linked label")
    snapshot = _number_set(row.get("option_range"), baseline_id=baseline_id)
    if family_id == "linked-zodiac":
        expected = zodiac_number_table(date(2026, 7, 1)).numbers_by_zodiac[option_name]
        if snapshot != expected:
            raise ValueError(f"{baseline_id} does not match the versioned catalog zodiac snapshot")
        semantic_family_ref = "zodiac-link-all-seven.v1"
        probability_ref = "partition-occupancy-inclusion-exclusion-seven.v1"
        map_assumption = "ZODIAC_BY_GREGORIAN_DRAW_DATE_LUNAR_NEW_YEAR_BOUNDARY"
    else:
        expected = tuple(number for number in range(1, 50) if number % 10 == int(option_name[0]))
        if snapshot != expected:
            raise ValueError(f"{baseline_id} does not match the canonical tail partition")
        semantic_family_ref = "tail-link-all-seven.v1"
        probability_ref = "tail-partition-occupancy-inclusion-exclusion-seven.v1"
        map_assumption = "TAIL_ZERO_HAS_FOUR_OTHERS_HAVE_FIVE"
    payload = {
        "schema_version": "xinao.rule_semantic_record.linked.v1",
        "baseline_id": baseline_id,
        "family_id": family_id,
        "play_id": _required_text(row, "play_id"),
        "play_name": _required_text(row, "play_name"),
        "pid": pid,
        "tid": tid,
        "option_name": option_name,
        "option_range": row.get("option_range"),
        "catalog_role": "LINKED_LABEL_QUOTE_COMPONENT",
        "semantic_family_ref": semantic_family_ref,
        "rule_version_ref": "linked-and-parlay-rule-semantics.v1",
        "selection_domain_ref": "linked-and-parlay-lazy-selection-domain.v1",
        "predicate_ref": (
            "predicate.all-selected-labels-present-in-seven.v1"
            if polarity == "HIT_ALL_LABELS"
            else "predicate.all-selected-labels-absent-from-seven.v1"
        ),
        "settlement_function_ref": f"settle-{family_id}-atomic-ticket.v1",
        "probability_formula_ref": probability_ref,
        "settlement_tiers": ("HIT", "MISS"),
        "draw_scope": "ALL_SEVEN_UNORDERED",
        "selection_arity_min": arity,
        "selection_arity_max": arity,
        "polarity": polarity,
        "component_label": option_name,
        "component_position": None,
        "component_attribute": None,
        "catalog_number_set_snapshot": snapshot,
        "snapshot_payout_components": _quote(row),
        "quote_aggregation_ref": "MIN_SELECTED_COMPONENT",
        "hit_payout_ref": "PAYOUT_EQUALS_Q_INCLUDING_STAKE",
        "miss_payout": "0",
        "principal_refund_on_normal_settlement": False,
        "void_policy": "NO_VOID",
        "interpretation_ref": f"{family_id}-all-seven-min-component.v1",
        "alternative_interpretation_refs": (
            "linked-six-regular-only.v1",
            "linked-max-component-quote.v1",
        ),
        "semantic_evidence_statuses": ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
        "assumption_refs": (
            "RESEARCH_CONVENTION:ALL_SELECTED_LABELS_REQUIRED",
            "RESEARCH_CONVENTION:ALL_SEVEN_NUMBERS_INCLUDED",
            "RESEARCH_CONVENTION:MIN_SELECTED_COMPONENT_QUOTE",
            f"RESEARCH_CONVENTION:{map_assumption}",
        ),
        "source_refs": (
            f"play-catalog.v1#{baseline_id}",
            "grok-wave1.f1-linked-parlay#active-semantics",
            "foundation-cost-contract#linked-component-route",
        ),
        "raw_site_fields": _raw_fields(row),
    }
    return _with_hash(RuleSemanticRecord, payload)


def _compile_parlay_record(row: Mapping[str, Any]) -> RuleSemanticRecord:
    baseline_id = _required_text(row, "baseline_id")
    if (
        _required_int(row, "pid") != 8
        or _required_int(row, "tid") != 40
        or row.get("panel") is not None
    ):
        raise ValueError(f"{baseline_id} has an invalid parlay catalog identity")
    if _required_text(row, "play_name") != "过关(2-6串)":
        raise ValueError(f"{baseline_id} has an invalid parlay play_name")
    match = _PARLAY_OPTION_PATTERN.fullmatch(_required_text(row, "option_name"))
    if match is None:
        raise ValueError(f"{baseline_id} has an invalid parlay leg")
    position = int(match.group(1))
    attribute: ParlayAttribute = _PARLAY_ATTRIBUTE[match.group(2)]  # type: ignore[assignment]
    payload = {
        "schema_version": "xinao.rule_semantic_record.linked.v1",
        "baseline_id": baseline_id,
        "family_id": "parlay",
        "play_id": _required_text(row, "play_id"),
        "play_name": _required_text(row, "play_name"),
        "pid": 8,
        "tid": 40,
        "option_name": _required_text(row, "option_name"),
        "option_range": row.get("option_range"),
        "catalog_role": "PARLAY_SINGLE_LEG_QUOTE_COMPONENT",
        "semantic_family_ref": "ordered-regular-position-parlay.v1",
        "rule_version_ref": "linked-and-parlay-rule-semantics.v1",
        "selection_domain_ref": "linked-and-parlay-lazy-selection-domain.v1",
        "predicate_ref": "predicate.all-ordered-regular-position-legs-non-miss.v1",
        "settlement_function_ref": "settle-ordered-regular-position-parlay.v1",
        "probability_formula_ref": "ordered-without-replacement-attribute-type-dp.v1",
        "settlement_tiers": ("HIT", "MISS"),
        "draw_scope": "ORDERED_REGULAR_POSITIONS_1_TO_6",
        "selection_arity_min": 2,
        "selection_arity_max": 6,
        "polarity": "ALL_LEGS_NON_MISS",
        "component_label": _required_text(row, "option_name"),
        "component_position": position,
        "component_attribute": attribute,
        "catalog_number_set_snapshot": (),
        "snapshot_payout_components": _quote(row),
        "quote_aggregation_ref": "PRODUCT_NON_VOID_LEGS",
        "hit_payout_ref": "PAYOUT_EQUALS_Q_INCLUDING_STAKE",
        "miss_payout": "0",
        "principal_refund_on_normal_settlement": False,
        "void_policy": "PROPERTY_49_LEG_MULTIPLIER_ONE",
        "interpretation_ref": "parlay-sequential-without-replacement-leg-49-one.v1",
        "alternative_interpretation_refs": (
            "parlay-independent-leg-probability.v1",
            "parlay-49-cancels-ticket.v1",
            "parlay-49-color-void.v1",
        ),
        "semantic_evidence_statuses": ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
        "assumption_refs": (
            "RESEARCH_CONVENTION:ONE_LEG_PER_REGULAR_POSITION",
            "RESEARCH_CONVENTION:SEQUENTIAL_WITHOUT_REPLACEMENT",
            "RESEARCH_CONVENTION:PROPERTY_49_LEG_MULTIPLIER_ONE",
            "RESEARCH_CONVENTION:49_IS_GREEN",
            "RESEARCH_CONVENTION:TICKET_QUOTE_IS_PRODUCT_OF_NON_VOID_LEGS",
        ),
        "source_refs": (
            f"play-catalog.v1#{baseline_id}",
            "grok-wave1.f1-linked-parlay#active-semantics",
            "foundation-cost-contract#parlay-single-leg-route",
        ),
        "raw_site_fields": _raw_fields(row),
    }
    return _with_hash(RuleSemanticRecord, payload)


def compile_linked_record(row: Mapping[str, Any]) -> RuleSemanticRecord:
    family_id = _required_text(row, "family_id")
    if family_id == "linked-zodiac":
        return _compile_linked_record(row, "linked-zodiac")
    if family_id == "linked-tail":
        return _compile_linked_record(row, "linked-tail")
    if family_id == "parlay":
        return _compile_parlay_record(row)
    raise ValueError(f"unsupported linked/parlay family: {family_id}")


def _interpretations() -> tuple[InterpretationRecord, ...]:
    return (
        InterpretationRecord(
            interpretation_ref="linked-zodiac-all-seven-min-component.v1",
            status="ACTIVE",
            scope="生肖连",
            statement=(
                "All selected zodiacs must each appear (中) or each be absent (不中) across "
                "all seven numbers; the ticket quote is the minimum selected component."
            ),
            source_refs=("play-catalog.v1#BO0267-BO0362", "grok-wave1.f1-linked-parlay"),
        ),
        InterpretationRecord(
            interpretation_ref="linked-tail-all-seven-min-component.v1",
            status="ACTIVE",
            scope="尾数连",
            statement=(
                "All selected tails must each appear (中) or each be absent (不中) across all "
                "seven numbers; the ticket quote is the minimum selected component."
            ),
            source_refs=("play-catalog.v1#BO0363-BO0422", "grok-wave1.f1-linked-parlay"),
        ),
        InterpretationRecord(
            interpretation_ref="parlay-sequential-without-replacement-leg-49-one.v1",
            status="ACTIVE",
            scope="过关",
            statement=(
                "Use 2-6 unique regular positions, exact without-replacement probability, quote "
                "product, property-leg multiplier one on 49, and green color for 49."
            ),
            source_refs=("play-catalog.v1#BO0219-BO0260", "grok-wave1.f1-linked-parlay"),
        ),
        InterpretationRecord(
            interpretation_ref="linked-six-regular-only.v1",
            status="ALTERNATE",
            scope="生肖连/尾数连",
            statement="Exclude the special number from linked-label predicates.",
            source_refs=("grok-wave1.f1-linked-parlay#alternate-a4",),
        ),
        InterpretationRecord(
            interpretation_ref="linked-max-component-quote.v1",
            status="ALTERNATE",
            scope="生肖连/尾数连",
            statement="Aggregate selected component quotes with maximum instead of minimum.",
            source_refs=("grok-wave1.f1-linked-parlay#alternate-a1",),
        ),
        InterpretationRecord(
            interpretation_ref="parlay-independent-leg-probability.v1",
            status="ALTERNATE",
            scope="过关",
            statement="Multiply independent leg marginals instead of using without-replacement DP.",
            source_refs=("grok-wave1.f1-linked-parlay#alternate-a3",),
        ),
        InterpretationRecord(
            interpretation_ref="parlay-49-cancels-ticket.v1",
            status="ALTERNATE",
            scope="过关",
            statement="Cancel or refund the whole ticket when a property leg observes 49.",
            source_refs=("grok-wave1.f1-linked-parlay#alternate-a2",),
        ),
        InterpretationRecord(
            interpretation_ref="parlay-49-color-void.v1",
            status="ALTERNATE",
            scope="过关",
            statement="Treat 49 as void for color legs instead of green.",
            source_refs=("grok-wave1.f1-linked-parlay#alternate-a2",),
        ),
    )


def _spec_payload(records: Sequence[RuleSemanticRecord]) -> dict[str, Any]:
    first = records[0]
    if first.family_id == "linked-zodiac":
        labels = ZODIAC_ORDER
        arity_min = arity_max = first.selection_arity_min
        count = comb(len(labels), arity_min)
        kind = "DISTINCT_LABEL_COMBINATION"
        constraint = "distinct-zodiac-labels-exact-k.v1"
        signature = "zodiac-link-year-map-and-selected-block-size-signature.v1"
    elif first.family_id == "linked-tail":
        labels = TAIL_ORDER
        arity_min = arity_max = first.selection_arity_min
        count = comb(len(labels), arity_min)
        kind = "DISTINCT_LABEL_COMBINATION"
        constraint = "distinct-tail-labels-exact-k.v1"
        signature = "tail-link-k-and-contains-zero-signature.v1"
    else:
        labels = tuple(record.option_name for record in records)
        arity_min, arity_max = 2, 6
        count = sum(comb(6, arity) * 7**arity for arity in range(2, 7))
        kind = "UNIQUE_POSITION_LEG_PRODUCT"
        constraint = "one-leg-per-regular-position-length-2-to-6.v1"
        signature = "parlay-position-and-attribute-type-count-signature.v1"
    return {
        "spec_id": f"selection-domain:{first.family_id}:{first.play_id}",
        "family_id": first.family_id,
        "play_id": first.play_id,
        "play_name": first.play_name,
        "component_baseline_ids": tuple(record.baseline_id for record in records),
        "component_label_domain": labels,
        "atomic_selection_kind": kind,
        "arity_min": arity_min,
        "arity_max": arity_max,
        "exact_atomic_selection_count": count,
        "expansion_policy": "LAZY_COMBINATORIAL",
        "materialized_atomic_selection_count": 0,
        "constraint_ref": constraint,
        "probability_cache_signature_ref": signature,
        "quote_aggregation_ref": first.quote_aggregation_ref,
        "interpretation_ref": first.interpretation_ref,
        "alternative_interpretation_refs": first.alternative_interpretation_refs,
    }


def _selection_domain(records: Sequence[RuleSemanticRecord]) -> ExpectedSelectionDomainCandidate:
    by_play: dict[str, list[RuleSemanticRecord]] = {}
    for record in records:
        by_play.setdefault(record.play_id, []).append(record)
    specs: list[SelectionDomainSpec] = []
    for play_id in sorted(by_play):
        group = sorted(by_play[play_id], key=lambda record: record.baseline_id)
        specs.append(_with_hash(SelectionDomainSpec, _spec_payload(group)))
    if len(specs) != 15:
        raise ValueError("linked/parlay selection domain must contain exactly 15 play specs")
    total = sum(spec.exact_atomic_selection_count for spec in specs)
    return _with_hash(
        ExpectedSelectionDomainCandidate,
        {
            "schema_version": "xinao.expected_selection_domain.linked.v1",
            "domain_ref": "linked-and-parlay-lazy-selection-domain.v1",
            "baseline_component_count": 198,
            "specification_count": 15,
            "exact_atomic_selection_count": total,
            "materialized_atomic_selection_count": 0,
            "expansion_policy": "LAZY_COMBINATORIAL",
            "specifications": tuple(specs),
        },
    )


def compile_linked_semantics(catalog: Mapping[str, Any]) -> LinkedSemanticsCompilation:
    """Compile the exact 198-row catalog slice and a non-materialised selection domain."""

    entries = catalog.get("entries")
    if not isinstance(entries, list) or len(entries) != 433 or catalog.get("entry_count") != 433:
        raise ValueError("formal catalog must contain exactly 433 rows")
    target_rows = [
        row
        for row in entries
        if isinstance(row, dict) and row.get("family_id") in TARGET_FAMILY_IDS
    ]
    family_counts = {
        family: sum(row.get("family_id") == family for row in target_rows)
        for family in sorted(TARGET_FAMILY_IDS)
    }
    baseline_ids = [_required_text(row, "baseline_id") for row in target_rows]
    if family_counts != TARGET_FAMILY_COUNTS or len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError(
            f"target family coverage must be exact: expected {TARGET_FAMILY_COUNTS}, "
            f"observed {family_counts}"
        )
    ordered_rows = sorted(target_rows, key=lambda row: row["baseline_id"])
    records = tuple(compile_linked_record(row) for row in ordered_rows)
    expected_ids = {
        *(f"BO{number:04d}" for number in range(219, 261)),
        *(f"BO{number:04d}" for number in range(267, 423)),
    }
    if {record.baseline_id for record in records} != expected_ids:
        raise ValueError("linked/parlay catalog baseline identity set is not the expected 198 rows")
    _validate_component_partitions(records)
    domain = _selection_domain(records)
    coverage = Coverage(family_counts=family_counts)
    catalog_hash = catalog.get("content_hash")
    if not isinstance(catalog_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", catalog_hash):
        raise ValueError("catalog content_hash is missing or malformed")
    semantic_map = _with_hash(
        RuleSemanticMapSliceVersion,
        {
            "schema_version": "xinao.rule_semantic_map.linked.v1",
            "map_ref": "linked-and-parlay-rule-semantic-map.v1",
            "source_catalog_ref": str(catalog.get("catalog_ref") or "play-catalog.v1"),
            "source_catalog_content_hash": catalog_hash,
            "coverage": coverage,
            "records": records,
        },
    )
    return _with_hash(
        LinkedSemanticsCompilation,
        {
            "schema_version": "xinao.linked_semantics_compilation.v1",
            "rule_semantic_map": semantic_map,
            "expected_selection_domain": domain,
            "interpretations": _interpretations(),
        },
    )


def _validate_component_partitions(records: Sequence[RuleSemanticRecord]) -> None:
    by_play: dict[str, list[RuleSemanticRecord]] = {}
    for record in records:
        by_play.setdefault(record.play_id, []).append(record)
    for group in by_play.values():
        first = group[0]
        if first.family_id == "linked-zodiac":
            expected_labels = ZODIAC_ORDER
        elif first.family_id == "linked-tail":
            expected_labels = TAIL_ORDER
        else:
            expected_labels = tuple(
                f"正{position}-{label}"
                for position in range(1, 7)
                for label in ("单", "双", "大", "小", "红波", "绿波", "蓝波")
            )
        ordered_group = sorted(group, key=lambda record: record.baseline_id)
        observed = tuple(record.option_name for record in ordered_group)
        if len(observed) != len(expected_labels) or set(observed) != set(expected_labels):
            raise ValueError(f"{first.play_id} component label domain is incomplete")


def semantic_records_hash(records: Iterable[RuleSemanticRecord]) -> str:
    materialized = tuple(records)
    ids = [record.baseline_id for record in materialized]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate baseline_id in semantic hash input")
    return canonical_sha256(
        {
            "schema_version": "xinao.rule_semantic_map.linked.records.v1",
            "records": [
                record.model_dump(mode="json")
                for record in sorted(materialized, key=lambda item: item.baseline_id)
            ],
        }
    )


def iter_atomic_selections(
    spec: SelectionDomainSpec,
    records: Sequence[RuleSemanticRecord],
) -> Iterator[AtomicSelection]:
    """Lazily expand one domain spec; callers decide if/where selections are persisted."""

    component_by_id = {record.baseline_id: record for record in records}
    try:
        components = tuple(component_by_id[item] for item in spec.component_baseline_ids)
    except KeyError as exc:
        raise ValueError("selection spec references an unavailable component row") from exc
    if any(record.play_id != spec.play_id for record in components):
        raise ValueError("selection spec components do not belong to the declared play")
    if spec.atomic_selection_kind == "DISTINCT_LABEL_COMBINATION":
        by_label = {record.component_label: record for record in components}
        for labels in combinations(spec.component_label_domain, spec.arity_min):
            selected = tuple(by_label[label].baseline_id for label in labels)
            yield AtomicSelection(
                spec_id=spec.spec_id,
                selection_key=f"{spec.play_id}:{'+'.join(labels)}",
                component_baseline_ids=selected,
            )
        return
    by_position: dict[int, dict[str, RuleSemanticRecord]] = {}
    for record in components:
        if record.component_position is None or record.component_attribute is None:
            raise ValueError("parlay selection component is missing position/attribute")
        by_position.setdefault(record.component_position, {})[record.component_attribute] = record
    for arity in range(spec.arity_min, spec.arity_max + 1):
        for positions in combinations(range(1, 7), arity):
            for attributes in product(PARLAY_ATTRIBUTE_ORDER, repeat=arity):
                selected_records = tuple(
                    by_position[position][attribute]
                    for position, attribute in zip(positions, attributes, strict=True)
                )
                labels = tuple(record.option_name for record in selected_records)
                yield AtomicSelection(
                    spec_id=spec.spec_id,
                    selection_key=f"{spec.play_id}:{'+'.join(labels)}",
                    component_baseline_ids=tuple(record.baseline_id for record in selected_records),
                )


def _validated_draw(draw: Sequence[int]) -> tuple[int, ...]:
    if isinstance(draw, (str, bytes)) or len(draw) != 7:
        raise ValueError("draw must contain six regular numbers and one special number")
    result: list[int] = []
    for value in draw:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("draw values must be integers")
        if not 1 <= value <= 49:
            raise ValueError("draw values must be from 1 to 49")
        result.append(value)
    if len(set(result)) != 7:
        raise ValueError("draw values must be distinct")
    return tuple(result)


def _canonical_components(
    records: Sequence[RuleSemanticRecord], *, family: Literal["LINKED", "PARLAY"]
) -> tuple[RuleSemanticRecord, ...]:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise TypeError("ticket components must be a sequence of semantic records")
    materialized = tuple(records)
    wrong_type = any(not isinstance(record, RuleSemanticRecord) for record in materialized)
    if not materialized or wrong_type:
        raise TypeError("ticket components must be RuleSemanticRecord instances")
    if len({record.baseline_id for record in materialized}) != len(materialized):
        raise ValueError("ticket components must be distinct")
    if len({record.play_id for record in materialized}) != 1:
        raise ValueError("ticket components must belong to one play_id")
    if family == "LINKED":
        if any(record.family_id not in {"linked-zodiac", "linked-tail"} for record in materialized):
            raise ValueError("linked ticket requires zodiac or tail component rows")
        if len({record.family_id for record in materialized}) != 1:
            raise ValueError("linked ticket cannot mix zodiac and tail components")
        expected = materialized[0].selection_arity_min
        if len(materialized) != expected or any(
            record.selection_arity_min != expected for record in materialized
        ):
            raise ValueError(f"linked ticket must contain exactly {expected} labels")
        order = ZODIAC_ORDER if materialized[0].family_id == "linked-zodiac" else TAIL_ORDER
        rank = {label: index for index, label in enumerate(order)}
        return tuple(sorted(materialized, key=lambda record: rank[record.component_label]))
    if any(record.family_id != "parlay" for record in materialized):
        raise ValueError("parlay ticket requires parlay component rows")
    if not 2 <= len(materialized) <= 6:
        raise ValueError("parlay ticket must contain 2-6 legs")
    positions = [record.component_position for record in materialized]
    if any(position is None for position in positions) or len(set(positions)) != len(positions):
        raise ValueError("parlay ticket must use at most one leg per regular position")
    return tuple(sorted(materialized, key=lambda record: int(record.component_position or 0)))


def _linked_number_sets(
    records: Sequence[RuleSemanticRecord], *, draw_date: date | datetime | str
) -> tuple[frozenset[int], ...]:
    if records[0].family_id == "linked-zodiac":
        table = zodiac_number_table(draw_date).numbers_by_zodiac
        return tuple(frozenset(table[record.component_label]) for record in records)
    return tuple(frozenset(record.catalog_number_set_snapshot) for record in records)


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def settle_linked_ticket(
    records: Sequence[RuleSemanticRecord],
    *,
    draw: Sequence[int],
    draw_date: date | datetime | str,
) -> TicketSettlementResult:
    components = _canonical_components(records, family="LINKED")
    numbers = set(_validated_draw(draw))
    label_sets = _linked_number_sets(components, draw_date=draw_date)
    if components[0].polarity == "HIT_ALL_LABELS":
        win = all(not numbers.isdisjoint(label_set) for label_set in label_sets)
    else:
        win = all(numbers.isdisjoint(label_set) for label_set in label_sets)
    quote = min(_positive_quote(record.snapshot_payout_components[0]) for record in components)
    return TicketSettlementResult(
        family_id=components[0].family_id,
        play_id=components[0].play_id,
        component_baseline_ids=tuple(record.baseline_id for record in components),
        selection_labels=tuple(record.component_label for record in components),
        outcome="HIT" if win else "MISS",
        unit_payout=_decimal_text(quote) if win else "0",
    )


def _comb_or_zero(total: int, selected: int) -> int:
    if selected < 0 or selected > total:
        return 0
    return comb(total, selected)


def _all_blocks_present_probability(block_sizes: Sequence[int]) -> Fraction:
    denominator = comb(49, 7)
    numerator = 0
    for omitted_count in range(len(block_sizes) + 1):
        for omitted in combinations(block_sizes, omitted_count):
            available = 49 - sum(omitted)
            numerator += (-1) ** omitted_count * _comb_or_zero(available, 7)
    return Fraction(numerator, denominator)


def linked_ticket_probabilities(
    records: Sequence[RuleSemanticRecord],
    *,
    draw_date: date | datetime | str,
) -> dict[Outcome, Fraction]:
    """Exact unordered seven-ball probability; quotes never enter this calculation."""

    components = _canonical_components(records, family="LINKED")
    block_sizes = tuple(
        len(group) for group in _linked_number_sets(components, draw_date=draw_date)
    )
    if components[0].polarity == "HIT_ALL_LABELS":
        hit = _all_blocks_present_probability(block_sizes)
    else:
        hit = Fraction(_comb_or_zero(49 - sum(block_sizes), 7), comb(49, 7))
    return {"HIT": hit, "MISS": 1 - hit}


def linked_probability_signature(
    records: Sequence[RuleSemanticRecord],
    *,
    draw_date: date | datetime | str,
) -> str:
    components = _canonical_components(records, family="LINKED")
    block_sizes = sorted(
        len(group) for group in _linked_number_sets(components, draw_date=draw_date)
    )
    payload: dict[str, Any] = {
        "family_id": components[0].family_id,
        "play_id": components[0].play_id,
        "polarity": components[0].polarity,
        "block_sizes": block_sizes,
    }
    if components[0].family_id == "linked-zodiac":
        table = zodiac_number_table(draw_date)
        payload["zodiac_table_ref"] = table.table_ref
        payload["lunar_year_started_on"] = table.lunar_year_started_on
        payload["lunar_year_zodiac"] = table.lunar_year_zodiac
    return canonical_sha256(payload)


def _parlay_leg_state(record: RuleSemanticRecord, value: int) -> Literal["HIT", "MISS", "VOID"]:
    attribute = record.component_attribute
    if attribute is None:
        raise ValueError("parlay component has no attribute")
    if value == 49 and attribute in {"ODD", "EVEN", "BIG", "SMALL"}:
        return "VOID"
    if attribute == "ODD":
        hit = value % 2 == 1
    elif attribute == "EVEN":
        hit = value % 2 == 0
    elif attribute == "BIG":
        hit = value >= 25
    elif attribute == "SMALL":
        hit = value <= 24
    else:
        hit = value in _COLOR_NUMBERS[attribute]
    return "HIT" if hit else "MISS"


def settle_parlay_ticket(
    records: Sequence[RuleSemanticRecord], *, draw: Sequence[int]
) -> TicketSettlementResult:
    components = _canonical_components(records, family="PARLAY")
    numbers = _validated_draw(draw)
    quote = Decimal(1)
    void_positions: list[int] = []
    miss = False
    for record in components:
        position = int(record.component_position or 0)
        state = _parlay_leg_state(record, numbers[position - 1])
        if state == "MISS":
            miss = True
        elif state == "VOID":
            void_positions.append(position)
        else:
            quote *= _positive_quote(record.snapshot_payout_components[0])
    return TicketSettlementResult(
        family_id="parlay",
        play_id=components[0].play_id,
        component_baseline_ids=tuple(record.baseline_id for record in components),
        selection_labels=tuple(record.component_label for record in components),
        outcome="MISS" if miss else "HIT",
        unit_payout="0" if miss else _decimal_text(quote),
        void_leg_positions=tuple(void_positions),
    )


def _accepted_parlay_attributes(number: int) -> frozenset[str]:
    if number == 49:
        return frozenset({"ODD", "EVEN", "BIG", "SMALL", "GREEN"})
    attributes = {
        "ODD" if number % 2 else "EVEN",
        "BIG" if number >= 25 else "SMALL",
    }
    for color, numbers in _COLOR_NUMBERS.items():
        if number in numbers:
            attributes.add(color)
            break
    return frozenset(attributes)


_PARLAY_TYPES = tuple(
    sorted(
        Counter(_accepted_parlay_attributes(number) for number in range(1, 50)).items(),
        key=lambda item: tuple(sorted(item[0])),
    )
)

_SPECIAL_49_ACCEPTED_ATTRIBUTES = frozenset({"ODD", "EVEN", "BIG", "SMALL", "GREEN"})


def _parlay_path_totals_from_state(
    index: int,
    counts: tuple[int, ...],
    legs: tuple[tuple[str, Fraction], ...],
    memo: dict[tuple[int, tuple[int, ...]], tuple[int, Fraction]],
) -> tuple[int, Fraction]:
    """Return accepted path count and payout-weighted total for one DP state."""

    key = (index, counts)
    cached = memo.get(key)
    if cached is not None:
        return cached
    if index == len(legs):
        return 1, Fraction(1)

    required, quote = legs[index]
    path_count = 0
    weighted_total = Fraction(0)
    for type_index, ((accepted, _), available) in enumerate(
        zip(_PARLAY_TYPES, counts, strict=True)
    ):
        if available == 0 or required not in accepted:
            continue
        remaining = list(counts)
        remaining[type_index] -= 1
        child_count, child_weight = _parlay_path_totals_from_state(
            index + 1,
            tuple(remaining),
            legs,
            memo,
        )
        is_property_49_void = accepted == _SPECIAL_49_ACCEPTED_ATTRIBUTES and required in {
            "ODD",
            "EVEN",
            "BIG",
            "SMALL",
        }
        multiplier = Fraction(1) if is_property_49_void else quote
        path_count += available * child_count
        weighted_total += available * multiplier * child_weight
    result = (path_count, weighted_total)
    memo[key] = result
    return result


def parlay_ticket_probability_and_expected_payout(
    records: Sequence[RuleSemanticRecord],
) -> tuple[Fraction, Fraction]:
    """Return exact hit probability and expected payout in one bounded DP.

    State lives in a plain per-call dictionary passed to a module-level helper.
    There is no self-referential cache wrapper, so every equivalence class is
    released immediately instead of waiting for cyclic garbage collection.
    """

    components = _canonical_components(records, family="PARLAY")
    legs = tuple(
        (
            str(record.component_attribute),
            Fraction(_positive_quote(record.snapshot_payout_components[0])),
        )
        for record in components
    )
    initial_counts = tuple(item[1] for item in _PARLAY_TYPES)
    favourable, weighted_total = _parlay_path_totals_from_state(
        0,
        initial_counts,
        legs,
        {},
    )
    denominator = prod(range(49 - len(components) + 1, 50))
    return Fraction(favourable, denominator), weighted_total / denominator


def parlay_ticket_hit_probability(records: Sequence[RuleSemanticRecord]) -> Fraction:
    """Exact probability by attribute-type DP over an ordered sample without replacement."""

    return parlay_ticket_probability_and_expected_payout(records)[0]


def parlay_ticket_expected_payout(records: Sequence[RuleSemanticRecord]) -> Fraction:
    """Return the exact expected payout for one parlay ticket.

    The dynamic program walks the same ordered-without-replacement attribute
    types as :func:`parlay_ticket_hit_probability`, but weights each accepted
    path by its actual payout multiplier.  Value 49 is a non-miss VOID for
    ODD/EVEN/BIG/SMALL legs, so that leg contributes multiplier one rather
    than its displayed quote; GREEN remains a normal quoted HIT at 49.
    """

    return parlay_ticket_probability_and_expected_payout(records)[1]


def parlay_probability_signature(records: Sequence[RuleSemanticRecord]) -> str:
    components = _canonical_components(records, family="PARLAY")
    return canonical_sha256(
        {
            "probability_model": "ORDERED_WITHOUT_REPLACEMENT_ATTRIBUTE_TYPE_DP",
            "attribute_multiset": sorted(str(record.component_attribute) for record in components),
            "property_49": "NON_MISS_VOID_LEG",
            "color_49": "GREEN",
        }
    )


__all__ = [
    "DEFAULT_PLAY_CATALOG_PATH",
    "PARLAY_ATTRIBUTE_ORDER",
    "TAIL_ORDER",
    "TARGET_FAMILY_COUNTS",
    "ZODIAC_ORDER",
    "AtomicSelection",
    "ExpectedSelectionDomainCandidate",
    "InterpretationRecord",
    "LinkedSemanticsCompilation",
    "RuleSemanticMapSliceVersion",
    "RuleSemanticRecord",
    "SelectionDomainSpec",
    "TicketSettlementResult",
    "compile_linked_record",
    "compile_linked_semantics",
    "iter_atomic_selections",
    "linked_probability_signature",
    "linked_ticket_probabilities",
    "load_play_catalog",
    "parlay_probability_signature",
    "parlay_ticket_expected_payout",
    "parlay_ticket_hit_probability",
    "parlay_ticket_probability_and_expected_payout",
    "semantic_records_hash",
    "settle_linked_ticket",
    "settle_parlay_ticket",
]
