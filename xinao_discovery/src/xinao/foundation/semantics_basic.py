"""Parameterised F1 semantics for the three basic number families.

The catalog supplies option identity, selection-domain shape, and snapshot quote
identity.  The predicates in this module are versioned research conventions;
they are never inferred from a price.  The module deliberately covers only the
94 baselines in ``special-number``, ``regular-number``, and
``regular-position-special`` and does not claim the 433-line Foundation gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import lru_cache
from math import comb
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xinao.canonical import canonical_sha256

SemanticStatus = Literal["EXPLICIT_PAGE", "RESEARCH_CONVENTION"]
BasicFamily = Literal[
    "special-number",
    "regular-number",
    "regular-position-special",
]
SemanticFamily = Literal[
    "special_exact_number",
    "special_digit_sum_parity",
    "special_parity",
    "special_size",
    "special_tail_size",
    "special_color",
    "regular_exact_number",
    "regular_sum_parity",
    "regular_sum_size",
    "position_exact_number",
    "position_parity",
    "position_digit_sum_parity",
    "position_size",
    "position_color",
]
TerminalOutcome = Literal["HIT", "MISS", "VOID"]
VoidPolicy = Literal["NO_VOID", "DRAW_VALUE_49_REFUND_STAKE"]

NUMBER_SELECTIONS = tuple(f"{number:02d}" for number in range(1, 50))
RED_NUMBERS = frozenset({1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46})
BLUE_NUMBERS = frozenset({3, 4, 9, 10, 14, 15, 20, 25, 26, 31, 36, 37, 41, 42, 47, 48})
GREEN_NUMBERS = frozenset({5, 6, 11, 16, 17, 21, 22, 27, 28, 32, 33, 38, 39, 43, 44, 49})
COLOR_NUMBERS = {
    "红波": RED_NUMBERS,
    "绿波": GREEN_NUMBERS,
    "蓝波": BLUE_NUMBERS,
}

_RANGE_PATTERN = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_POSITION_PLAY_PATTERN = re.compile(r"^正([1-6])特$")
_BASELINE_PATTERN = re.compile(r"^BO\d{4}$")


class EffectiveInterval(BaseModel):
    """Effective identity of the page snapshot and admitted convention."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    effective_from: Literal["2026-05-12T00:00:00Z"] = "2026-05-12T00:00:00Z"
    effective_until: None = None
    source_snapshot_ref: Literal["xinao-target-market-page-snapshot.2026-05-12.v1"] = (
        "xinao-target-market-page-snapshot.2026-05-12.v1"
    )


class TerminalTier(BaseModel):
    """One mutually exclusive terminal outcome and its unit-payout source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tier_id: TerminalOutcome
    payout_kind: Literal["QUOTE_COMPONENT", "ZERO", "REFUND_STAKE"]
    payout_component_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def bind_quote_index_only_to_hit(self) -> TerminalTier:
        if self.tier_id == "HIT":
            if self.payout_kind != "QUOTE_COMPONENT" or self.payout_component_index != 0:
                raise ValueError("HIT must bind snapshot quote component zero")
        elif self.payout_component_index is not None:
            raise ValueError("MISS and VOID must not bind a quote component")
        if self.tier_id == "MISS" and self.payout_kind != "ZERO":
            raise ValueError("MISS must have zero payout")
        if self.tier_id == "VOID" and self.payout_kind != "REFUND_STAKE":
            raise ValueError("VOID must refund exactly the unit stake")
        return self


class RuleSemanticRecord(BaseModel):
    """Strict, hashable projection from one catalog baseline to one rule family."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["xinao.rule_semantic_record.basic.v1"] = (
        "xinao.rule_semantic_record.basic.v1"
    )
    baseline_id: str = Field(min_length=1)
    family_id: BasicFamily
    play_id: str = Field(min_length=1)
    play_name: str = Field(min_length=1)
    pid: int = Field(gt=0)
    tid: int = Field(gt=0)
    panel: Literal["A", "B"]
    option_name: str = Field(min_length=1)
    option_range: str | None
    semantic_family: SemanticFamily
    rule_version_ref: str = Field(min_length=1)
    predicate_ref: str = Field(min_length=1)
    semantic_status: tuple[SemanticStatus, ...]
    evidence_refs: tuple[str, ...] = Field(min_length=2)
    selection_space: tuple[str, ...] = Field(min_length=1)
    selection_space_source: Literal["PLAY_CATALOG_OPTION_RANGE_OR_OPTION_NAME"] = (
        "PLAY_CATALOG_OPTION_RANGE_OR_OPTION_NAME"
    )
    draw_anchor: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=1, le=6)
    terminal_tiers: tuple[TerminalTier, ...]
    snapshot_payout_components: tuple[str, ...] = Field(min_length=1)
    payout_component_index: Literal[0] = 0
    probability_formula_ref: str = Field(min_length=1)
    rebate_scope_ref: str = Field(min_length=1)
    principal_refund_on_normal_settlement: Literal[False] = False
    void_policy: VoidPolicy
    rounding_policy: Literal["NO_PREDICATE_ROUNDING_QUOTE_DECIMAL_PRESERVED"] = (
        "NO_PREDICATE_ROUNDING_QUOTE_DECIMAL_PRESERVED"
    )
    boundary_policy: str = Field(min_length=1)
    effective: EffectiveInterval

    @field_validator("baseline_id")
    @classmethod
    def validate_baseline_id(cls, value: str) -> str:
        if not _BASELINE_PATTERN.fullmatch(value):
            raise ValueError("baseline_id must use BO plus four digits")
        return value

    @field_validator("semantic_status")
    @classmethod
    def preserve_page_and_convention(
        cls, value: tuple[SemanticStatus, ...]
    ) -> tuple[SemanticStatus, ...]:
        if value != ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"):
            raise ValueError("semantic_status must preserve page fact and research convention")
        return value

    @field_validator("selection_space")
    @classmethod
    def require_unique_selection_space(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not selection for selection in value):
            raise ValueError("selection_space must be non-empty and unique")
        return value

    @field_validator("snapshot_payout_components")
    @classmethod
    def validate_quote_components(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != 1:
            raise ValueError("the basic families require exactly one payout component")
        _validate_quote(value[0])
        return value

    @model_validator(mode="after")
    def validate_bindings(self) -> RuleSemanticRecord:
        expected_selection_space = _expand_domain(self.option_range, self.option_name)
        if self.selection_space != expected_selection_space:
            raise ValueError("selection_space must be independently derived from catalog fields")
        expected_tiers = (
            ("HIT", "MISS", "VOID") if self.void_policy != "NO_VOID" else ("HIT", "MISS")
        )
        if tuple(tier.tier_id for tier in self.terminal_tiers) != expected_tiers:
            raise ValueError("terminal_tiers do not match void_policy")
        if self.family_id == "regular-position-special":
            if self.position is None or self.draw_anchor != f"REGULAR_POSITION_{self.position}":
                raise ValueError("position family must bind one ordered regular position")
        elif self.position is not None:
            raise ValueError("position is only valid for regular-position-special")
        return self


class BasicSettlementResult(BaseModel):
    """Unit-stake terminal result; hit is q, miss is zero, normal hit adds no principal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["xinao.basic_settlement_result.v1"] = "xinao.basic_settlement_result.v1"
    baseline_id: str
    selection: str
    outcome: TerminalOutcome
    terminal_tier: TerminalOutcome
    payout_component_index: int | None
    unit_payout: str
    principal_refund_added: Literal[False] = False
    void_refund_applied: bool


@dataclass(frozen=True, slots=True)
class _SemanticSpec:
    semantic_family: SemanticFamily
    predicate_ref: str
    draw_anchor: str
    position: int | None
    probability_formula_ref: str
    void_policy: VoidPolicy
    boundary_policy: str


def _required_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _required_integer(entry: Mapping[str, Any], key: str) -> int:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _validate_quote(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise TypeError("payout components must be non-empty decimal strings")
    try:
        quote = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid payout component") from exc
    if not quote.is_finite() or quote <= 0:
        raise ValueError("payout component must be positive and finite")


def _payout_components(entry: Mapping[str, Any]) -> tuple[str, ...]:
    raw = entry.get("baseline_odds_components")
    if not isinstance(raw, (list, tuple)) or len(raw) != 1:
        raise ValueError("basic family baseline_odds_components must contain one quote")
    component = raw[0]
    if not isinstance(component, str):
        raise TypeError("payout components must be decimal strings")
    _validate_quote(component)
    return (component,)


def _expand_domain(option_range: str | None, option_name: str) -> tuple[str, ...]:
    if option_range is None:
        if not option_name:
            raise ValueError("option_name must be non-empty when option_range is absent")
        return (option_name,)
    if not isinstance(option_range, str):
        raise TypeError("option_range must be text or null")
    match = _RANGE_PATTERN.fullmatch(option_range.strip())
    if match is None:
        raise ValueError(f"unsupported option_range: {option_range}")
    start_text, end_text = match.groups()
    start, end = int(start_text), int(end_text)
    if start < 1 or end > 49 or start > end:
        raise ValueError("numeric option_range must be an ascending subset of 01-49")
    width = max(2, len(start_text), len(end_text))
    return tuple(f"{number:0{width}d}" for number in range(start, end + 1))


def expand_selection_domain(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Expand only catalog ``option_range``/``option_name`` fields, before semantics."""

    if not isinstance(entry, Mapping):
        raise TypeError("catalog entry must be a mapping")
    option_name = _required_text(entry, "option_name")
    return _expand_domain(entry.get("option_range"), option_name)


def _terminal_tiers(void_policy: VoidPolicy) -> tuple[TerminalTier, ...]:
    tiers = [
        TerminalTier(tier_id="HIT", payout_kind="QUOTE_COMPONENT", payout_component_index=0),
        TerminalTier(tier_id="MISS", payout_kind="ZERO", payout_component_index=None),
    ]
    if void_policy != "NO_VOID":
        tiers.append(
            TerminalTier(tier_id="VOID", payout_kind="REFUND_STAKE", payout_component_index=None)
        )
    return tuple(tiers)


def _special_spec(option_name: str) -> _SemanticSpec:
    if option_name == "号码":
        return _SemanticSpec(
            "special_exact_number",
            "predicate.special.equals-selection.v1",
            "SPECIAL_POSITION_7",
            None,
            "probability.fixed-position-one-over-49.v1",
            "NO_VOID",
            "selection and special number are integers in 1..49",
        )
    if option_name in {"合单", "合双"}:
        family: SemanticFamily = "special_digit_sum_parity"
        predicate = "predicate.special.digit-sum-parity.v1"
        boundary = "digit sum parity on 01..48; 49 is VOID"
    elif option_name in {"特单", "特双"}:
        family = "special_parity"
        predicate = "predicate.special.parity.v1"
        boundary = "odd/even on 01..48; 49 is VOID"
    elif option_name in {"特大", "特小"}:
        family = "special_size"
        predicate = "predicate.special.size-24-25.v1"
        boundary = "small=01..24, big=25..48; 49 is VOID"
    elif option_name in {"特尾大", "特尾小"}:
        family = "special_tail_size"
        predicate = "predicate.special.tail-size-4-5.v1"
        boundary = "tail small=0..4, tail big=5..9 on 01..48; 49 is VOID"
    elif option_name in COLOR_NUMBERS:
        return _SemanticSpec(
            "special_color",
            "predicate.special.fixed-color-map.v1",
            "SPECIAL_POSITION_7",
            None,
            "probability.fixed-position-color-cardinality-over-49.v1",
            "NO_VOID",
            "fixed red/blue/green partition of 01..49; 49 is green",
        )
    else:
        raise ValueError(f"unsupported special-number option: {option_name}")
    return _SemanticSpec(
        family,
        predicate,
        "SPECIAL_POSITION_7",
        None,
        "probability.fixed-position-hit24-void1-miss24-over-49.v1",
        "DRAW_VALUE_49_REFUND_STAKE",
        boundary,
    )


def _regular_spec(option_name: str) -> _SemanticSpec:
    if option_name == "号码":
        return _SemanticSpec(
            "regular_exact_number",
            "predicate.selection-in-first-six-regular-numbers.v1",
            "REGULAR_SET_POSITIONS_1_TO_6",
            None,
            "probability.regular-membership-six-over-49.v1",
            "NO_VOID",
            "first six draw positions only; the special position is excluded",
        )
    if option_name in {"总单", "总双"}:
        return _SemanticSpec(
            "regular_sum_parity",
            "predicate.all-seven-sum-parity.v1",
            "ALL_SEVEN_SUM",
            None,
            "probability.seven-combination-exact-sum-parity-enumeration.v1",
            "NO_VOID",
            "sum all seven numbers; odd/even is exhaustive",
        )
    if option_name in {"总大", "总小"}:
        return _SemanticSpec(
            "regular_sum_size",
            "predicate.all-seven-sum-size-174-175.v1",
            "ALL_SEVEN_SUM",
            None,
            "probability.seven-combination-exact-sum-threshold-enumeration.v1",
            "NO_VOID",
            "sum all seven numbers; small<=174 and big>=175",
        )
    raise ValueError(f"unsupported regular-number option: {option_name}")


def _position_spec(option_name: str, *, play_name: str, tid: int) -> _SemanticSpec:
    match = _POSITION_PLAY_PATTERN.fullmatch(play_name)
    if match is None:
        raise ValueError("regular-position-special play_name must be 正1特 through 正6特")
    position = int(match.group(1))
    if tid != 17 + position:
        raise ValueError("regular-position-special tid does not match its ordered position")
    anchor = f"REGULAR_POSITION_{position}"
    if option_name == "号码":
        return _SemanticSpec(
            "position_exact_number",
            "predicate.ordered-regular-position-equals-selection.v1",
            anchor,
            position,
            "probability.fixed-position-one-over-49.v1",
            "NO_VOID",
            "position follows draw order and is never sorted; exact 49 is a normal hit",
        )
    if option_name in {"单", "双"}:
        family: SemanticFamily = "position_parity"
        predicate = "predicate.ordered-regular-position-parity.v1"
        boundary = "odd/even on 01..48; 49 is VOID"
    elif option_name in {"合单", "合双"}:
        family = "position_digit_sum_parity"
        predicate = "predicate.ordered-regular-position-digit-sum-parity.v1"
        boundary = "digit sum parity on 01..48; 49 is VOID"
    elif option_name in {"大", "小"}:
        family = "position_size"
        predicate = "predicate.ordered-regular-position-size-24-25.v1"
        boundary = "small=01..24, big=25..48; 49 is VOID"
    elif option_name in COLOR_NUMBERS:
        return _SemanticSpec(
            "position_color",
            "predicate.ordered-regular-position-fixed-color-map.v1",
            anchor,
            position,
            "probability.fixed-position-color-cardinality-over-49.v1",
            "NO_VOID",
            "fixed red/blue/green partition of 01..49; 49 is green",
        )
    else:
        raise ValueError(f"unsupported regular-position-special option: {option_name}")
    return _SemanticSpec(
        family,
        predicate,
        anchor,
        position,
        "probability.fixed-position-hit24-void1-miss24-over-49.v1",
        "DRAW_VALUE_49_REFUND_STAKE",
        boundary,
    )


def _semantic_spec(
    family_id: BasicFamily,
    *,
    option_name: str,
    play_name: str,
    tid: int,
) -> _SemanticSpec:
    if family_id == "special-number":
        return _special_spec(option_name)
    if family_id == "regular-number":
        return _regular_spec(option_name)
    return _position_spec(option_name, play_name=play_name, tid=tid)


def _validate_catalog_identity(
    family_id: BasicFamily,
    *,
    pid: int,
    tid: int,
    panel: str,
) -> Literal["A", "B"]:
    if panel not in {"A", "B"}:
        raise ValueError("panel must be A or B")
    if family_id == "special-number":
        if pid != 1 or (panel, tid) not in {("A", 14), ("B", 15)}:
            raise ValueError("special-number identity must be PID 1 and A/14 or B/15")
    elif family_id == "regular-number":
        if pid != 2 or (panel, tid) not in {("A", 16), ("B", 17)}:
            raise ValueError("regular-number identity must be PID 2 and A/16 or B/17")
    elif pid != 3 or panel != "A" or tid not in range(18, 24):
        raise ValueError("regular-position-special identity must be PID 3, panel A, TID 18..23")
    return panel


def compile_basic_semantic(entry: Mapping[str, Any]) -> RuleSemanticRecord:
    """Compile one supported catalog entry without consulting or inferring from its price."""

    if not isinstance(entry, Mapping):
        raise TypeError("catalog entry must be a mapping")
    family_raw = _required_text(entry, "family_id")
    if family_raw not in {"special-number", "regular-number", "regular-position-special"}:
        raise ValueError(f"unsupported basic family: {family_raw}")
    family_id: BasicFamily = family_raw  # type: ignore[assignment]
    baseline_id = _required_text(entry, "baseline_id")
    play_id = _required_text(entry, "play_id")
    play_name = _required_text(entry, "play_name")
    option_name = _required_text(entry, "option_name")
    pid = _required_integer(entry, "pid")
    tid = _required_integer(entry, "tid")
    panel = _validate_catalog_identity(
        family_id,
        pid=pid,
        tid=tid,
        panel=_required_text(entry, "panel"),
    )
    spec = _semantic_spec(
        family_id,
        option_name=option_name,
        play_name=play_name,
        tid=tid,
    )
    option_range = entry.get("option_range")
    if option_range is not None and not isinstance(option_range, str):
        raise TypeError("option_range must be text or null")
    selection_space = _expand_domain(option_range, option_name)
    return RuleSemanticRecord(
        baseline_id=baseline_id,
        family_id=family_id,
        play_id=play_id,
        play_name=play_name,
        pid=pid,
        tid=tid,
        panel=panel,
        option_name=option_name,
        option_range=option_range,
        semantic_family=spec.semantic_family,
        rule_version_ref=f"rule-semantic.basic.{spec.semantic_family}.v1",
        predicate_ref=spec.predicate_ref,
        semantic_status=("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
        evidence_refs=(
            f"play-catalog.v1#{baseline_id}",
            f"research-convention.basic.{spec.semantic_family}.2026-07-14",
        ),
        selection_space=selection_space,
        draw_anchor=spec.draw_anchor,
        position=spec.position,
        terminal_tiers=_terminal_tiers(spec.void_policy),
        snapshot_payout_components=_payout_components(entry),
        probability_formula_ref=spec.probability_formula_ref,
        rebate_scope_ref=f"rebate-scope.{baseline_id}.v1",
        void_policy=spec.void_policy,
        boundary_policy=spec.boundary_policy,
        effective=EffectiveInterval(),
    )


def compile_basic_semantics(
    entries: Iterable[Mapping[str, Any]],
) -> tuple[RuleSemanticRecord, ...]:
    """Compile and baseline-sort a bounded set; duplicate identities fail closed."""

    records = [compile_basic_semantic(entry) for entry in entries]
    baseline_ids = [record.baseline_id for record in records]
    if len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError("duplicate baseline_id in basic semantic records")
    return tuple(sorted(records, key=lambda record: record.baseline_id))


def semantic_records_hash(records: Iterable[RuleSemanticRecord]) -> str:
    """Hash a canonical baseline ordering so source-entry reordering is inert."""

    materialized = tuple(records)
    baseline_ids = [record.baseline_id for record in materialized]
    if len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError("duplicate baseline_id in semantic hash input")
    ordered = sorted(materialized, key=lambda record: record.baseline_id)
    return canonical_sha256(
        {
            "schema_version": "xinao.rule_semantic_map.basic.v1",
            "records": [record.model_dump(mode="json") for record in ordered],
        }
    )


def _validated_draw(draw: Sequence[int]) -> tuple[int, ...]:
    if isinstance(draw, (str, bytes)) or not isinstance(draw, Sequence):
        raise TypeError("draw must be a seven-number sequence")
    if len(draw) != 7:
        raise ValueError("draw must contain six regular numbers and one special number")
    values: list[int] = []
    for value in draw:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("draw values must be integers")
        if not 1 <= value <= 49:
            raise ValueError("draw values must be between 1 and 49")
        values.append(value)
    if len(values) != len(set(values)):
        raise ValueError("draw values must be distinct")
    return tuple(values)


def _canonical_selection(record: RuleSemanticRecord, selection: str | int) -> str:
    if isinstance(selection, bool):
        raise TypeError("selection must be text or an integer number")
    if record.selection_space == NUMBER_SELECTIONS:
        if isinstance(selection, int):
            if not 1 <= selection <= 49:
                raise ValueError("number selection must be between 1 and 49")
            candidate = f"{selection:02d}"
        elif isinstance(selection, str) and selection.isdigit():
            number = int(selection)
            candidate = f"{number:02d}"
        else:
            raise TypeError("number selection must be numeric text or an integer")
    elif isinstance(selection, str):
        candidate = selection
    else:
        raise TypeError("named selection must be text")
    if candidate not in record.selection_space:
        raise ValueError("selection is outside the independently expanded catalog domain")
    return candidate


def _anchor(record: RuleSemanticRecord, draw: tuple[int, ...]) -> int | tuple[int, ...]:
    if record.draw_anchor == "SPECIAL_POSITION_7":
        return draw[6]
    if record.draw_anchor == "REGULAR_SET_POSITIONS_1_TO_6":
        return draw[:6]
    if record.draw_anchor == "ALL_SEVEN_SUM":
        return sum(draw)
    if record.position is not None:
        return draw[record.position - 1]
    raise ValueError("unsupported draw anchor")


def _attribute_hit(record: RuleSemanticRecord, anchor: int) -> bool:
    option = record.option_name
    if record.semantic_family in {"special_parity", "position_parity"}:
        return (anchor % 2 == 1) == (option in {"特单", "单"})
    if record.semantic_family in {"special_digit_sum_parity", "position_digit_sum_parity"}:
        digit_sum = anchor // 10 + anchor % 10
        return (digit_sum % 2 == 1) == (option == "合单")
    if record.semantic_family in {"special_size", "position_size"}:
        return (anchor >= 25) == (option in {"特大", "大"})
    if record.semantic_family == "special_tail_size":
        return (anchor % 10 >= 5) == (option == "特尾大")
    if record.semantic_family in {"special_color", "position_color"}:
        return anchor in COLOR_NUMBERS[option]
    raise ValueError("record does not use a scalar attribute predicate")


def _is_hit(
    record: RuleSemanticRecord,
    *,
    draw: tuple[int, ...],
    selection: str,
) -> bool:
    anchor = _anchor(record, draw)
    if record.semantic_family == "special_exact_number":
        return anchor == int(selection)
    if record.semantic_family == "regular_exact_number":
        if not isinstance(anchor, tuple):
            raise ValueError("regular exact-number anchor must be a tuple")
        return int(selection) in anchor
    if record.semantic_family == "position_exact_number":
        return anchor == int(selection)
    if record.semantic_family == "regular_sum_parity":
        if not isinstance(anchor, int):
            raise ValueError("regular sum anchor must be an integer")
        return (anchor % 2 == 1) == (record.option_name == "总单")
    if record.semantic_family == "regular_sum_size":
        if not isinstance(anchor, int):
            raise ValueError("regular sum anchor must be an integer")
        return (anchor >= 175) == (record.option_name == "总大")
    if not isinstance(anchor, int):
        raise ValueError("attribute anchor must be an integer")
    return _attribute_hit(record, anchor)


def settle_basic_record(
    *,
    record: RuleSemanticRecord,
    draw: Sequence[int],
    selection: str | int,
) -> BasicSettlementResult:
    """Settle a compiled record at unit stake using its snapshot payout component."""

    if not isinstance(record, RuleSemanticRecord):
        raise TypeError("record must be RuleSemanticRecord")
    values = _validated_draw(draw)
    selected = _canonical_selection(record, selection)
    anchor = _anchor(record, values)
    if record.void_policy == "DRAW_VALUE_49_REFUND_STAKE" and anchor == 49:
        outcome: TerminalOutcome = "VOID"
    else:
        outcome = "HIT" if _is_hit(record, draw=values, selection=selected) else "MISS"
    if outcome == "HIT":
        payout = record.snapshot_payout_components[record.payout_component_index]
        payout_component_index: int | None = record.payout_component_index
    elif outcome == "VOID":
        payout = "1"
        payout_component_index = None
    else:
        payout = "0"
        payout_component_index = None
    return BasicSettlementResult(
        baseline_id=record.baseline_id,
        selection=selected,
        outcome=outcome,
        terminal_tier=outcome,
        payout_component_index=payout_component_index,
        unit_payout=payout,
        void_refund_applied=outcome == "VOID",
    )


def settle_basic(
    *,
    entry: Mapping[str, Any],
    draw: Sequence[int],
    selection: str | int,
) -> BasicSettlementResult:
    """Compile one catalog entry and settle it against one ordered seven-number draw."""

    return settle_basic_record(
        record=compile_basic_semantic(entry),
        draw=draw,
        selection=selection,
    )


@lru_cache(maxsize=1)
def _seven_subset_sum_distribution() -> tuple[tuple[int, int], ...]:
    states: list[dict[int, int]] = [dict() for _ in range(8)]
    states[0][0] = 1
    for number in range(1, 50):
        for chosen in range(7, 0, -1):
            for prior_sum, count in tuple(states[chosen - 1].items()):
                total = prior_sum + number
                states[chosen][total] = states[chosen].get(total, 0) + count
    distribution = tuple(sorted(states[7].items()))
    if sum(count for _, count in distribution) != comb(49, 7):
        raise RuntimeError("seven-number sum distribution does not cover C(49,7)")
    return distribution


def tier_probabilities(record: RuleSemanticRecord) -> dict[TerminalOutcome, Fraction]:
    """Return the exact HIT/MISS/VOID partition for one compiled basic record."""

    if not isinstance(record, RuleSemanticRecord):
        raise TypeError("record must be RuleSemanticRecord")
    family = record.semantic_family
    if family in {"special_exact_number", "position_exact_number"}:
        hit = Fraction(1, 49)
        return {"HIT": hit, "MISS": 1 - hit}
    if family == "regular_exact_number":
        hit = Fraction(6, 49)
        return {"HIT": hit, "MISS": 1 - hit}
    if family in {"regular_sum_parity", "regular_sum_size"}:
        distribution = _seven_subset_sum_distribution()
        if family == "regular_sum_parity":
            hit_count = sum(
                count
                for total, count in distribution
                if (total % 2 == 1) == (record.option_name == "总单")
            )
        else:
            hit_count = sum(
                count
                for total, count in distribution
                if (total >= 175) == (record.option_name == "总大")
            )
        hit = Fraction(hit_count, comb(49, 7))
        return {"HIT": hit, "MISS": 1 - hit}

    void_numbers = {49} if record.void_policy == "DRAW_VALUE_49_REFUND_STAKE" else set()
    hit_count = sum(
        _attribute_hit(record, number) for number in range(1, 50) if number not in void_numbers
    )
    hit = Fraction(hit_count, 49)
    miss = Fraction(49 - len(void_numbers) - hit_count, 49)
    result: dict[TerminalOutcome, Fraction] = {"HIT": hit, "MISS": miss}
    if void_numbers:
        result["VOID"] = Fraction(len(void_numbers), 49)
    if set(result) != {tier.tier_id for tier in record.terminal_tiers}:
        raise RuntimeError("basic probability tiers diverge from settlement tiers")
    if sum(result.values(), Fraction(0)) != 1:
        raise RuntimeError("basic probability tiers are not normalized")
    return result


__all__ = [
    "BLUE_NUMBERS",
    "GREEN_NUMBERS",
    "NUMBER_SELECTIONS",
    "RED_NUMBERS",
    "BasicSettlementResult",
    "EffectiveInterval",
    "RuleSemanticRecord",
    "TerminalTier",
    "compile_basic_semantic",
    "compile_basic_semantics",
    "expand_selection_domain",
    "semantic_records_hash",
    "settle_basic",
    "settle_basic_record",
    "tier_probabilities",
]
