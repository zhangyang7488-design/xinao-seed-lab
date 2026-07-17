"""Deterministic semantics for the three set/attribute catalog families.

This module is deliberately a bounded RuleSemanticMap slice.  It maps the 119
``other-explicit``, ``one-zodiac-tail``, and ``six-zodiac`` baseline rows; it
does not claim that the complete 433-row settlement world is compiled.

Displayed odds are retained as raw catalog evidence but never participate in
choosing a play meaning.  Ambiguous market readings are represented as an
ACTIVE interpretation plus explicit ALTERNATE records.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from fractions import Fraction
from itertools import combinations
from math import comb
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import canonical_sha256
from xinao.foundation.f4_snapshot_runtime import load_object as load_snapshot_object
from xinao.foundation.probability import at_least_one_in_seven_probability

DEFAULT_PLAY_CATALOG_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_catalog.v1.json"
)

TARGET_FAMILY_COUNTS = {
    "other-explicit": 95,
    "one-zodiac-tail": 22,
    "six-zodiac": 2,
}
TARGET_FAMILY_IDS = frozenset(TARGET_FAMILY_COUNTS)

ZODIAC_ORDER = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
ZODIAC_SET = frozenset(ZODIAC_ORDER)

# The research world currently spans 2024-2026.  The adjacent boundary years
# are retained so a draw immediately before the first/after the last New Year
# can still be mapped without treating Gregorian 1 January as a zodiac change.
LUNAR_YEAR_BOUNDARIES = (
    (date(2023, 1, 22), "兔"),
    (date(2024, 2, 10), "龙"),
    (date(2025, 1, 29), "蛇"),
    (date(2026, 2, 17), "马"),
    (date(2027, 2, 6), "羊"),
)
SUPPORTED_DRAW_DATE_MIN = date(2024, 1, 1)
SUPPORTED_DRAW_DATE_MAX = date(2027, 12, 31)

_COLOR_WAVE = {
    "红": (1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46),
    "蓝": (3, 4, 9, 10, 14, 15, 20, 25, 26, 31, 36, 37, 41, 42, 47, 48),
    "绿": (5, 6, 11, 16, 17, 21, 22, 27, 28, 32, 33, 38, 39, 43, 44, 49),
}
_FIVE_ELEMENTS = {
    "土": (5, 10, 15, 20, 25, 30, 35, 40, 45),
    "木": (2, 7, 12, 17, 22, 27, 32, 37, 42, 47),
    "水": (3, 8, 13, 18, 23, 28, 33, 38, 43, 48),
    "火": (4, 9, 14, 19, 24, 29, 34, 39, 44, 49),
    "金": (1, 6, 11, 16, 21, 26, 31, 36, 41, 46),
}
_HOME_WILD = {
    "家禽": ("牛", "马", "羊", "鸡", "狗", "猪"),
    "野兽": ("鼠", "虎", "兔", "龙", "蛇", "猴"),
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Coverage(_FrozenModel):
    catalog_total: int
    mapped_baselines: int
    remaining_baselines: int
    family_counts: dict[str, int]
    foundation_complete: Literal[False] = False


class InterpretationRecord(_FrozenModel):
    interpretation_ref: str
    status: Literal["ACTIVE", "ALTERNATE"]
    scope: str
    statement: str
    basis: str
    source_refs: tuple[str, ...]


class NumberAttributeTableVersion(_FrozenModel):
    table_ref: Literal["xinao-number-attributes.v1"] = "xinao-number-attributes.v1"
    number_domain: tuple[int, ...]
    color_wave: dict[str, tuple[int, ...]]
    tail: dict[str, tuple[int, ...]]
    five_elements: dict[str, tuple[int, ...]]
    home_wild: dict[str, tuple[str, ...]]
    source_refs: tuple[str, ...]
    content_hash: str


class ZodiacNumberTableVersion(_FrozenModel):
    table_ref: Literal["xinao-zodiac-by-draw-date.v1"] = "xinao-zodiac-by-draw-date.v1"
    draw_date: str
    lunar_year_started_on: str
    lunar_year_zodiac: str
    numbers_by_zodiac: dict[str, tuple[int, ...]]
    source_refs: tuple[str, ...]
    content_hash: str


class RuleSemanticRecord(_FrozenModel):
    schema_version: Literal["xinao.rule_semantic_record.sets.v1"] = (
        "xinao.rule_semantic_record.sets.v1"
    )
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: Literal["other-explicit", "one-zodiac-tail", "six-zodiac"]
    play_name: str
    option_name: str
    rule_version_ref: Literal["set-attribute-rule-semantics.v1"] = "set-attribute-rule-semantics.v1"
    semantic_family_ref: str
    selection_domain_ref: Literal["set-attribute-expected-selection-domain.v1"] = (
        "set-attribute-expected-selection-domain.v1"
    )
    settlement_function_ref: str
    probability_formula_ref: str
    settlement_tiers: tuple[Literal["HIT", "MISS", "VOID"], ...]
    interpretation_status: Literal["ACTIVE"] = "ACTIVE"
    interpretation_ref: str
    alternative_interpretation_refs: tuple[str, ...]
    semantic_parameters: dict[str, Any]
    semantic_evidence_statuses: tuple[Literal["EXPLICIT_PAGE", "RESEARCH_CONVENTION"], ...]
    source_refs: tuple[str, ...]
    raw_site_fields: dict[str, Any]
    content_hash: str


class SelectionDomainEntry(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: Literal["other-explicit", "one-zodiac-tail", "six-zodiac"]
    selection_key: str
    selected_values: tuple[str, ...]
    interpretation_ref: str


class ExpectedSelectionDomainManifest(_FrozenModel):
    schema_version: Literal["xinao.expected_selection_domain.sets.v1"] = (
        "xinao.expected_selection_domain.sets.v1"
    )
    domain_ref: Literal["set-attribute-expected-selection-domain.v1"] = (
        "set-attribute-expected-selection-domain.v1"
    )
    baseline_count: int
    expanded_selection_count: int
    entries: tuple[SelectionDomainEntry, ...]
    content_hash: str


class RuleSemanticMapSliceVersion(_FrozenModel):
    schema_version: Literal["xinao.rule_semantic_map.sets.v1"] = "xinao.rule_semantic_map.sets.v1"
    map_ref: Literal["set-attribute-rule-semantic-map.v1"] = "set-attribute-rule-semantic-map.v1"
    source_catalog_ref: str
    source_catalog_content_hash: str
    attribute_table_ref: Literal["xinao-number-attributes.v1"] = "xinao-number-attributes.v1"
    zodiac_table_ref: Literal["xinao-zodiac-by-draw-date.v1"] = "xinao-zodiac-by-draw-date.v1"
    coverage: Coverage
    records: tuple[RuleSemanticRecord, ...]
    content_hash: str


class SetFamilySemanticsCompilation(_FrozenModel):
    schema_version: Literal["xinao.set_family_semantics_compilation.v1"] = (
        "xinao.set_family_semantics_compilation.v1"
    )
    rule_semantic_map: RuleSemanticMapSliceVersion
    expected_selection_domain: ExpectedSelectionDomainManifest
    attribute_table: NumberAttributeTableVersion
    interpretations: tuple[InterpretationRecord, ...]
    content_hash: str


def _model_with_hash(model: type[_FrozenModel], payload: dict[str, Any]) -> Any:
    body = dict(payload)
    body["content_hash"] = canonical_sha256(body)
    return model.model_validate(body)


def load_play_catalog(path: Path = DEFAULT_PLAY_CATALOG_PATH) -> dict[str, Any]:
    """Load the formal catalog without mutating or recompiling it."""

    raw = load_snapshot_object(path)
    if not isinstance(raw, dict):
        raise ValueError("play catalog must be a JSON object")
    return raw


def number_attribute_table() -> NumberAttributeTableVersion:
    """Return the versioned static color/tail/five-element/home-wild tables."""

    tails = {
        f"{tail}尾": tuple(number for number in range(1, 50) if number % 10 == tail)
        for tail in range(10)
    }
    payload = {
        "table_ref": "xinao-number-attributes.v1",
        "number_domain": tuple(range(1, 50)),
        "color_wave": _COLOR_WAVE,
        "tail": tails,
        "five_elements": _FIVE_ELEMENTS,
        "home_wild": _HOME_WILD,
        "source_refs": (
            "play-catalog.v1#BO0107-BO0118,BO0151-BO0155,BO0180-BO0189",
            "new-macau-result-api.wave-and-zodiac-fields",
            "set-attribute-research-convention.2026-07-14",
        ),
    }
    table = _model_with_hash(NumberAttributeTableVersion, payload)
    _require_partition(table.color_wave, label="color wave")
    _require_partition(table.tail, label="tail")
    _require_partition(table.five_elements, label="five elements")
    return table


def _parse_draw_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        result = value.date()
    elif isinstance(value, date):
        result = value
    elif isinstance(value, str):
        try:
            result = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("draw_date must be an ISO Gregorian date") from exc
    else:
        raise TypeError("draw_date must be a date, datetime, or ISO date string")
    if not SUPPORTED_DRAW_DATE_MIN <= result <= SUPPORTED_DRAW_DATE_MAX:
        raise ValueError("draw_date is outside the versioned lunar-year boundary table")
    return result


def zodiac_number_table(draw_date: date | datetime | str) -> ZodiacNumberTableVersion:
    """Map numbers to zodiac using the Gregorian draw date and Lunar New Year boundary."""

    observed = _parse_draw_date(draw_date)
    eligible = [item for item in LUNAR_YEAR_BOUNDARIES if item[0] <= observed]
    if not eligible:
        raise ValueError("draw_date precedes the first versioned lunar-year boundary")
    boundary, year_zodiac = eligible[-1]
    year_index = ZODIAC_ORDER.index(year_zodiac)
    grouped: dict[str, list[int]] = {zodiac: [] for zodiac in ZODIAC_ORDER}
    for number in range(1, 50):
        zodiac = ZODIAC_ORDER[(year_index - (number - 1)) % len(ZODIAC_ORDER)]
        grouped[zodiac].append(number)
    payload = {
        "table_ref": "xinao-zodiac-by-draw-date.v1",
        "draw_date": observed.isoformat(),
        "lunar_year_started_on": boundary.isoformat(),
        "lunar_year_zodiac": year_zodiac,
        "numbers_by_zodiac": {zodiac: tuple(grouped[zodiac]) for zodiac in ZODIAC_ORDER},
        "source_refs": (
            "macaujc2-source-contract#openTime-gregorian-zodiac-lunar-new-year",
            "set-attribute-research-convention.2026-07-14",
        ),
    }
    return _model_with_hash(ZodiacNumberTableVersion, payload)


def _require_partition(groups: Mapping[str, Sequence[int]], *, label: str) -> None:
    flattened = [number for numbers in groups.values() for number in numbers]
    if len(flattened) != 49 or set(flattened) != set(range(1, 50)):
        raise ValueError(f"{label} table must partition numbers 1-49 exactly once")


def _interpretations() -> tuple[InterpretationRecord, ...]:
    return (
        InterpretationRecord(
            interpretation_ref="half-wave-49-void.v1",
            status="ACTIVE",
            scope="半波",
            statement="Special number 49 settles as VOID for every half-wave option.",
            basis="Independent market-rule consensus; all 12 explicit page sets omit 49.",
            source_refs=(
                "play-catalog.v1#BO0107-BO0118",
                "grok-wave1.f1-attribute-set-families#half-wave-49",
            ),
        ),
        InterpretationRecord(
            interpretation_ref="half-wave-49-miss.v1",
            status="ALTERNATE",
            scope="半波",
            statement="Treat omitted special number 49 as MISS instead of VOID.",
            basis="Literal set-membership fallback retained for sensitivity only.",
            source_refs=("play-catalog.v1#BO0107-BO0118",),
        ),
        InterpretationRecord(
            interpretation_ref="six-zodiac-select-six.v1",
            status="ACTIVE",
            scope="六肖",
            statement=(
                "Select exactly six distinct zodiacs and settle the special zodiac in/out; "
                "special number 49 settles as VOID before zodiac membership is evaluated."
            ),
            basis=(
                "Play identity and independent rule consensus agree on six selections and "
                "the 49 VOID boundary; no price was used to select the interpretation."
            ),
            source_refs=(
                "foundation-cost-contract#six-zodiac-route",
                "grok-wave1.f1-attribute-set-families#six-zodiac",
                "https://www.24628.com/News/197315.html",
                "https://www.xinyupan.com/index/index/essay_details.html?id=110",
            ),
        ),
        InterpretationRecord(
            interpretation_ref="six-zodiac-select-five-from-raw-label.v1",
            status="ALTERNATE",
            scope="六肖",
            statement="Select exactly five distinct zodiacs and settle the special zodiac in/out.",
            basis="Raw option_range says 任选五肖; retained as a non-active source conflict.",
            source_refs=("play-catalog.v1#BO0217-BO0218.option_range",),
        ),
        InterpretationRecord(
            interpretation_ref="six-zodiac-49-normal-zodiac.v1",
            status="ALTERNATE",
            scope="六肖",
            statement=(
                "Retain number 49's date-derived zodiac and evaluate the selected zodiac union."
            ),
            basis=(
                "Pure set-membership sensitivity retained as an alternate to the independent "
                "market-rule consensus."
            ),
            source_refs=("macaujc2-source-contract#zodiac-number-table",),
        ),
    )


def _parse_number_set(value: Any, *, field: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain an explicit comma-separated number set")
    try:
        numbers = tuple(sorted(int(part.strip()) for part in value.split(",")))
    except ValueError as exc:
        raise ValueError(f"{field} contains a non-integer number") from exc
    if len(numbers) != len(set(numbers)) or any(not 1 <= number <= 49 for number in numbers):
        raise ValueError(f"{field} must be unique numbers from 1 to 49")
    return numbers


def _record_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    baseline_id = _required_text(row, "baseline_id")
    family_id = _required_text(row, "family_id")
    play_name = _required_text(row, "play_name")
    option_name = _required_text(row, "option_name")
    raw_fields = {str(key): value for key, value in sorted(row.items())}
    base = {
        "schema_version": "xinao.rule_semantic_record.sets.v1",
        "baseline_id": baseline_id,
        "family_id": family_id,
        "play_name": play_name,
        "option_name": option_name,
        "rule_version_ref": "set-attribute-rule-semantics.v1",
        "selection_domain_ref": "set-attribute-expected-selection-domain.v1",
        "interpretation_status": "ACTIVE",
        "semantic_evidence_statuses": ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
        "source_refs": (
            f"play-catalog.v1#{baseline_id}",
            "foundation-cost-contract#13-family-computation-route",
            "grok-wave1.f1-attribute-set-families",
        ),
        "raw_site_fields": raw_fields,
    }

    if play_name == "特肖":
        return {
            **base,
            "semantic_family_ref": "special-number-in-set.v1",
            "settlement_function_ref": "settle-special-zodiac.v1",
            "probability_formula_ref": "special-in-dynamic-zodiac-set.v1",
            "settlement_tiers": ("HIT", "MISS"),
            "interpretation_ref": "special-zodiac-by-draw-date.v1",
            "alternative_interpretation_refs": (),
            "semantic_parameters": {
                "draw_scope": "SPECIAL_ONLY",
                "set_kind": "ZODIAC_BY_DRAW_DATE",
                "selector": option_name,
                "table_ref": "xinao-zodiac-by-draw-date.v1",
            },
        }
    if play_name == "半波":
        return {
            **base,
            "semantic_family_ref": "special-number-in-set.v1",
            "settlement_function_ref": "settle-special-half-wave.v1",
            "probability_formula_ref": "special-in-explicit-set-with-void.v1",
            "settlement_tiers": ("HIT", "MISS", "VOID"),
            "interpretation_ref": "half-wave-49-void.v1",
            "alternative_interpretation_refs": ("half-wave-49-miss.v1",),
            "semantic_parameters": {
                "draw_scope": "SPECIAL_ONLY",
                "set_kind": "EXPLICIT_NUMBER_SET",
                "selector": option_name,
                "number_set": _parse_number_set(
                    row.get("option_range"), field=f"{baseline_id}.option_range"
                ),
                "void_numbers": (49,),
                "table_ref": "xinao-number-attributes.v1",
            },
        }
    if play_name == "五行":
        return {
            **base,
            "semantic_family_ref": "special-number-in-set.v1",
            "settlement_function_ref": "settle-special-five-element.v1",
            "probability_formula_ref": "special-in-explicit-set.v1",
            "settlement_tiers": ("HIT", "MISS"),
            "interpretation_ref": "five-elements-target-page-table.v1",
            "alternative_interpretation_refs": (),
            "semantic_parameters": {
                "draw_scope": "SPECIAL_ONLY",
                "set_kind": "EXPLICIT_NUMBER_SET",
                "selector": option_name,
                "number_set": _parse_number_set(
                    row.get("option_range"), field=f"{baseline_id}.option_range"
                ),
                "table_ref": "xinao-number-attributes.v1",
            },
        }
    if play_name == "七码":
        attribute = {"单": "ODD", "双": "EVEN", "大": "BIG", "小": "SMALL"}.get(option_name[:1])
        if attribute is None or not option_name[1:].isdigit():
            raise ValueError(f"unsupported seven-count option: {option_name}")
        expected_count = int(option_name[1:])
        if not 0 <= expected_count <= 7:
            raise ValueError("seven-count option must be from 0 to 7")
        return {
            **base,
            "semantic_family_ref": "seven-number-attribute-count.v1",
            "settlement_function_ref": "settle-seven-attribute-count.v1",
            "probability_formula_ref": "hypergeometric-seven-attribute-count.v1",
            "settlement_tiers": ("HIT", "MISS"),
            "interpretation_ref": "seven-count-all-seven-numbers.v1",
            "alternative_interpretation_refs": (),
            "semantic_parameters": {
                "draw_scope": "ALL_SEVEN",
                "attribute": attribute,
                "expected_count": expected_count,
                "big_small_boundary": "SMALL_1_24_BIG_25_49",
            },
        }
    if play_name in {"一肖量", "尾数量"}:
        prefix = "肖" if play_name == "一肖量" else "尾"
        if not option_name.startswith(prefix) or not option_name[1:].isdigit():
            raise ValueError(f"unsupported distinct-count option: {option_name}")
        expected_count = int(option_name[1:])
        if not 2 <= expected_count <= 7:
            raise ValueError("distinct-count option must be from 2 to 7")
        partition = "ZODIAC_BY_DRAW_DATE" if play_name == "一肖量" else "TAIL"
        return {
            **base,
            "semantic_family_ref": "seven-number-distinct-partition-count.v1",
            "settlement_function_ref": "settle-seven-distinct-partition-count.v1",
            "probability_formula_ref": "partition-occupancy-dp-seven.v1",
            "settlement_tiers": ("HIT", "MISS"),
            "interpretation_ref": "distinct-count-all-seven-numbers.v1",
            "alternative_interpretation_refs": (),
            "semantic_parameters": {
                "draw_scope": "ALL_SEVEN",
                "partition": partition,
                "expected_count": expected_count,
            },
        }
    if play_name in {"一肖不中", "尾数不中", "一肖", "尾数"}:
        is_zodiac = play_name in {"一肖不中", "一肖"}
        all_miss = play_name in {"一肖不中", "尾数不中"}
        if is_zodiac and option_name not in ZODIAC_SET:
            raise ValueError(f"unknown zodiac selector: {option_name}")
        if not is_zodiac and option_name not in {f"{tail}尾" for tail in range(10)}:
            raise ValueError(f"unknown tail selector: {option_name}")
        return {
            **base,
            "semantic_family_ref": (
                "seven-number-all-miss-set.v1" if all_miss else "seven-number-at-least-once-set.v1"
            ),
            "settlement_function_ref": (
                "settle-seven-all-miss.v1" if all_miss else "settle-seven-at-least-once.v1"
            ),
            "probability_formula_ref": (
                "complement-at-least-once-in-seven.v1" if all_miss else "at-least-once-in-seven.v1"
            ),
            "settlement_tiers": ("HIT", "MISS"),
            "interpretation_ref": "all-seven-set-membership.v1",
            "alternative_interpretation_refs": (),
            "semantic_parameters": {
                "draw_scope": "ALL_SEVEN",
                "set_kind": "ZODIAC_BY_DRAW_DATE" if is_zodiac else "TAIL",
                "selector": option_name,
                "predicate": "ALL_MISS" if all_miss else "AT_LEAST_ONCE",
                "table_ref": (
                    "xinao-zodiac-by-draw-date.v1" if is_zodiac else "xinao-number-attributes.v1"
                ),
            },
        }
    if play_name == "六肖":
        if option_name not in {"中", "不中"}:
            raise ValueError(f"unsupported six-zodiac side: {option_name}")
        return {
            **base,
            "semantic_family_ref": "six-zodiac-special-membership.v1",
            "settlement_function_ref": "settle-six-zodiac-special-membership.v1",
            "probability_formula_ref": "special-in-zodiac-union.v1",
            "settlement_tiers": ("HIT", "MISS", "VOID"),
            "interpretation_ref": "six-zodiac-select-six.v1",
            "alternative_interpretation_refs": (
                "six-zodiac-select-five-from-raw-label.v1",
                "six-zodiac-49-normal-zodiac.v1",
            ),
            "semantic_parameters": {
                "draw_scope": "SPECIAL_ONLY",
                "selection_kind": "ZODIAC_COMBINATION",
                "selection_count": 6,
                "side": "IN" if option_name == "中" else "OUT",
                "void_numbers": (49,),
                "table_ref": "xinao-zodiac-by-draw-date.v1",
            },
        }
    raise ValueError(f"unsupported play_name in target families: {play_name}")


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"catalog row is missing {field}")
    return value


def _compile_record(row: Mapping[str, Any]) -> RuleSemanticRecord:
    payload = _record_payload(row)
    return _model_with_hash(RuleSemanticRecord, payload)


def _domain_entries(records: Sequence[RuleSemanticRecord]) -> tuple[SelectionDomainEntry, ...]:
    entries: list[SelectionDomainEntry] = []
    for record in records:
        if record.family_id != "six-zodiac":
            entries.append(
                SelectionDomainEntry(
                    baseline_id=record.baseline_id,
                    family_id=record.family_id,
                    selection_key=f"{record.baseline_id}:{record.option_name}",
                    selected_values=(record.option_name,),
                    interpretation_ref=record.interpretation_ref,
                )
            )
            continue
        for selected in combinations(ZODIAC_ORDER, 6):
            entries.append(
                SelectionDomainEntry(
                    baseline_id=record.baseline_id,
                    family_id=record.family_id,
                    selection_key=f"{record.baseline_id}:{'-'.join(selected)}",
                    selected_values=selected,
                    interpretation_ref=record.interpretation_ref,
                )
            )
    return tuple(sorted(entries, key=lambda entry: entry.selection_key))


def _validate_raw_attribute_bindings(records: Sequence[RuleSemanticRecord]) -> None:
    """Bind explicit page sets to the versioned tables without using prices."""

    table = number_attribute_table()
    zodiac_snapshots: dict[str, dict[str, tuple[int, ...]]] = {}
    for record in records:
        raw_range = record.raw_site_fields.get("option_range")
        if record.play_name in {"特肖", "一肖", "一肖不中"}:
            zodiac_snapshots.setdefault(record.play_name, {})[record.option_name] = (
                _parse_number_set(raw_range, field=f"{record.baseline_id}.option_range")
            )
        if record.play_name in {"尾数", "尾数不中"}:
            observed = _parse_number_set(raw_range, field=f"{record.baseline_id}.option_range")
            if observed != table.tail[record.option_name]:
                raise ValueError(f"{record.baseline_id} does not match versioned tail table")
        if record.play_name == "五行":
            observed = _parse_number_set(raw_range, field=f"{record.baseline_id}.option_range")
            if observed != table.five_elements[record.option_name]:
                raise ValueError(
                    f"{record.baseline_id} does not match versioned five-element table"
                )
        if record.play_name == "半波":
            color, attribute = record.option_name[0], record.option_name[1:]
            predicates = {
                "单": lambda number: number % 2 == 1,
                "双": lambda number: number % 2 == 0,
                "大": lambda number: number >= 25,
                "小": lambda number: number <= 24,
            }
            if color not in table.color_wave or attribute not in predicates:
                raise ValueError(f"unsupported half-wave option: {record.option_name}")
            expected = tuple(
                number
                for number in table.color_wave[color]
                if number != 49 and predicates[attribute](number)
            )
            observed = _parse_number_set(raw_range, field=f"{record.baseline_id}.option_range")
            if observed != expected:
                raise ValueError(f"{record.baseline_id} does not match versioned half-wave table")

    if set(zodiac_snapshots) != {"特肖", "一肖", "一肖不中"}:
        raise ValueError("raw zodiac snapshots are incomplete")
    canonical_snapshot = zodiac_snapshots["特肖"]
    if set(canonical_snapshot) != ZODIAC_SET:
        raise ValueError("raw zodiac snapshot must contain exactly 12 zodiacs")
    _require_partition(canonical_snapshot, label="raw zodiac snapshot")
    if any(snapshot != canonical_snapshot for snapshot in zodiac_snapshots.values()):
        raise ValueError("raw zodiac snapshot sets disagree across target play names")


def compile_set_family_semantics(
    catalog: Mapping[str, Any],
) -> SetFamilySemanticsCompilation:
    """Compile the exact 119-row target slice and its ACTIVE selection domain."""

    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise ValueError("catalog entries are missing")
    total = catalog.get("entry_count")
    if total != 433 or len(entries) != 433:
        raise ValueError("formal catalog must contain exactly 433 rows")
    target_rows = [
        row
        for row in entries
        if isinstance(row, dict) and row.get("family_id") in TARGET_FAMILY_IDS
    ]
    ids = [_required_text(row, "baseline_id") for row in target_rows]
    family_counts = {
        family: sum(row.get("family_id") == family for row in target_rows)
        for family in sorted(TARGET_FAMILY_IDS)
    }
    if family_counts != TARGET_FAMILY_COUNTS or len(ids) != len(set(ids)):
        raise ValueError(
            f"target family coverage must be exact: expected {TARGET_FAMILY_COUNTS}, "
            f"observed {family_counts}"
        )
    records = tuple(
        _compile_record(row) for row in sorted(target_rows, key=lambda row: row["baseline_id"])
    )
    if len(records) != 119:
        raise ValueError("target family coverage must compile exactly 119 records")
    _validate_raw_attribute_bindings(records)

    domain_entries = _domain_entries(records)
    domain = _model_with_hash(
        ExpectedSelectionDomainManifest,
        {
            "schema_version": "xinao.expected_selection_domain.sets.v1",
            "domain_ref": "set-attribute-expected-selection-domain.v1",
            "baseline_count": len(records),
            "expanded_selection_count": len(domain_entries),
            "entries": domain_entries,
        },
    )
    coverage = Coverage(
        catalog_total=433,
        mapped_baselines=len(records),
        remaining_baselines=433 - len(records),
        family_counts=family_counts,
        foundation_complete=False,
    )
    map_version = _model_with_hash(
        RuleSemanticMapSliceVersion,
        {
            "schema_version": "xinao.rule_semantic_map.sets.v1",
            "map_ref": "set-attribute-rule-semantic-map.v1",
            "source_catalog_ref": str(catalog.get("catalog_ref") or "play-catalog.v1"),
            "source_catalog_content_hash": _required_catalog_hash(catalog),
            "attribute_table_ref": "xinao-number-attributes.v1",
            "zodiac_table_ref": "xinao-zodiac-by-draw-date.v1",
            "coverage": coverage,
            "records": records,
        },
    )
    attribute_table = number_attribute_table()
    interpretations = _interpretations()
    return _model_with_hash(
        SetFamilySemanticsCompilation,
        {
            "schema_version": "xinao.set_family_semantics_compilation.v1",
            "rule_semantic_map": map_version,
            "expected_selection_domain": domain,
            "attribute_table": attribute_table,
            "interpretations": interpretations,
        },
    )


def _required_catalog_hash(catalog: Mapping[str, Any]) -> str:
    value = catalog.get("content_hash")
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("catalog content_hash is missing or malformed")
    return value


def _validated_draw(draw: Sequence[int]) -> tuple[int, ...]:
    if isinstance(draw, (str, bytes)) or len(draw) != 7:
        raise ValueError("draw must contain exactly six regular numbers plus one special number")
    result: list[int] = []
    for number in draw:
        if isinstance(number, bool) or not isinstance(number, int):
            raise TypeError("draw numbers must be integers")
        if not 1 <= number <= 49:
            raise ValueError("draw numbers must be from 1 to 49")
        result.append(number)
    if len(set(result)) != 7:
        raise ValueError("draw numbers must be distinct")
    return tuple(result)


def _validated_selection(selection: Sequence[str] | None) -> tuple[str, ...]:
    if selection is None or isinstance(selection, (str, bytes)):
        raise ValueError("six-zodiac selection must contain exactly 6 distinct zodiacs")
    selected = tuple(selection)
    if (
        len(selected) != 6
        or len(set(selected)) != 6
        or any(item not in ZODIAC_SET for item in selected)
    ):
        raise ValueError("six-zodiac selection must contain exactly 6 distinct zodiacs")
    return tuple(zodiac for zodiac in ZODIAC_ORDER if zodiac in selected)


def _number_set(
    record: RuleSemanticRecord,
    *,
    draw_date: date | datetime | str,
) -> frozenset[int]:
    parameters = record.semantic_parameters
    kind = parameters.get("set_kind")
    selector = parameters.get("selector")
    if kind == "EXPLICIT_NUMBER_SET":
        return frozenset(parameters["number_set"])
    if kind == "TAIL":
        return frozenset(number_attribute_table().tail[str(selector)])
    if kind == "ZODIAC_BY_DRAW_DATE":
        return frozenset(zodiac_number_table(draw_date).numbers_by_zodiac[str(selector)])
    raise ValueError(f"unsupported set kind: {kind}")


def _partition_labels(
    *, draw: Sequence[int], partition: str, draw_date: date | datetime | str
) -> set[str]:
    if partition == "TAIL":
        return {f"{number % 10}尾" for number in draw}
    if partition == "ZODIAC_BY_DRAW_DATE":
        table = zodiac_number_table(draw_date).numbers_by_zodiac
        reverse = {number: zodiac for zodiac, numbers in table.items() for number in numbers}
        return {reverse[number] for number in draw}
    raise ValueError(f"unsupported partition: {partition}")


def settle_rule(
    record: RuleSemanticRecord,
    *,
    draw: Sequence[int],
    draw_date: date | datetime | str,
    selection: Sequence[str] | None = None,
) -> Literal["HIT", "MISS", "VOID"]:
    """Settle one ACTIVE semantic record against one ordered seven-number draw."""

    numbers = _validated_draw(draw)
    family = record.semantic_family_ref
    parameters = record.semantic_parameters
    if family == "special-number-in-set.v1":
        special = numbers[-1]
        if special in set(parameters.get("void_numbers", ())):
            return "VOID"
        return "HIT" if special in _number_set(record, draw_date=draw_date) else "MISS"
    if family == "seven-number-attribute-count.v1":
        attribute = parameters["attribute"]
        predicates = {
            "ODD": lambda number: number % 2 == 1,
            "EVEN": lambda number: number % 2 == 0,
            "BIG": lambda number: number >= 25,
            "SMALL": lambda number: number <= 24,
        }
        observed = sum(predicates[attribute](number) for number in numbers)
        return "HIT" if observed == parameters["expected_count"] else "MISS"
    if family == "seven-number-distinct-partition-count.v1":
        observed = len(
            _partition_labels(
                draw=numbers,
                partition=parameters["partition"],
                draw_date=draw_date,
            )
        )
        return "HIT" if observed == parameters["expected_count"] else "MISS"
    if family in {"seven-number-all-miss-set.v1", "seven-number-at-least-once-set.v1"}:
        intersects = not set(numbers).isdisjoint(_number_set(record, draw_date=draw_date))
        hit = not intersects if family == "seven-number-all-miss-set.v1" else intersects
        return "HIT" if hit else "MISS"
    if family == "six-zodiac-special-membership.v1":
        selected = _validated_selection(selection)
        if numbers[-1] in set(parameters.get("void_numbers", ())):
            return "VOID"
        table = zodiac_number_table(draw_date).numbers_by_zodiac
        chosen_numbers = {number for zodiac in selected for number in table[zodiac]}
        in_set = numbers[-1] in chosen_numbers
        hit = in_set if parameters["side"] == "IN" else not in_set
        return "HIT" if hit else "MISS"
    raise ValueError(f"unsupported semantic family: {family}")


def _attribute_count_probability(attribute: str, expected_count: int) -> Fraction:
    marked = 25 if attribute in {"ODD", "BIG"} else 24
    numerator = _comb_or_zero(marked, expected_count) * _comb_or_zero(
        49 - marked, 7 - expected_count
    )
    return Fraction(numerator, comb(49, 7))


def _comb_or_zero(total: int, selected: int) -> int:
    if selected < 0 or selected > total:
        return 0
    return comb(total, selected)


def _partition_count_probability(block_sizes: Sequence[int], occupied: int) -> Fraction:
    # DP state: (numbers chosen, non-empty blocks used) -> unordered subsets.
    states: dict[tuple[int, int], int] = {(0, 0): 1}
    for size in block_sizes:
        next_states: dict[tuple[int, int], int] = {}
        for (chosen, used), count in states.items():
            for take in range(0, min(size, 7 - chosen) + 1):
                key = (chosen + take, used + int(take > 0))
                next_states[key] = next_states.get(key, 0) + count * comb(size, take)
        states = next_states
    return Fraction(states.get((7, occupied), 0), comb(49, 7))


def tier_probabilities(
    record: RuleSemanticRecord,
    *,
    draw_date: date | datetime | str,
    selection: Sequence[str] | None = None,
) -> dict[Literal["HIT", "MISS", "VOID"], Fraction]:
    """Return exact theoretical tier probabilities for one ACTIVE rule record."""

    family = record.semantic_family_ref
    parameters = record.semantic_parameters
    if family == "special-number-in-set.v1":
        marked = len(_number_set(record, draw_date=draw_date))
        void_count = len(set(parameters.get("void_numbers", ())))
        result: dict[Literal["HIT", "MISS", "VOID"], Fraction] = {
            "HIT": Fraction(marked, 49),
            "MISS": Fraction(49 - marked - void_count, 49),
        }
        if void_count:
            result["VOID"] = Fraction(void_count, 49)
        return result
    if family == "seven-number-attribute-count.v1":
        hit = _attribute_count_probability(parameters["attribute"], parameters["expected_count"])
        return {"HIT": hit, "MISS": 1 - hit}
    if family == "seven-number-distinct-partition-count.v1":
        block_sizes = [4] + [5] * 9 if parameters["partition"] == "TAIL" else [5] + [4] * 11
        hit = _partition_count_probability(block_sizes, parameters["expected_count"])
        return {"HIT": hit, "MISS": 1 - hit}
    if family in {"seven-number-all-miss-set.v1", "seven-number-at-least-once-set.v1"}:
        marked = len(_number_set(record, draw_date=draw_date))
        at_least_once = at_least_one_in_seven_probability(marked)
        hit = 1 - at_least_once if family == "seven-number-all-miss-set.v1" else at_least_once
        return {"HIT": hit, "MISS": 1 - hit}
    if family == "six-zodiac-special-membership.v1":
        selected = _validated_selection(selection)
        table = zodiac_number_table(draw_date).numbers_by_zodiac
        void_numbers = set(parameters.get("void_numbers", ()))
        marked = len(
            {
                number
                for zodiac in selected
                for number in table[zodiac]
                if number not in void_numbers
            }
        )
        non_void = 49 - len(void_numbers)
        hit_count = marked if parameters["side"] == "IN" else non_void - marked
        hit = Fraction(hit_count, 49)
        miss = Fraction(non_void - hit_count, 49)
        result = {"HIT": hit, "MISS": miss}
        if void_numbers:
            result["VOID"] = Fraction(len(void_numbers), 49)
        return result
    raise ValueError(f"unsupported semantic family: {family}")


__all__ = [
    "DEFAULT_PLAY_CATALOG_PATH",
    "TARGET_FAMILY_COUNTS",
    "ExpectedSelectionDomainManifest",
    "InterpretationRecord",
    "NumberAttributeTableVersion",
    "RuleSemanticMapSliceVersion",
    "RuleSemanticRecord",
    "SetFamilySemanticsCompilation",
    "ZodiacNumberTableVersion",
    "compile_set_family_semantics",
    "load_play_catalog",
    "number_attribute_table",
    "settle_rule",
    "tier_probabilities",
    "zodiac_number_table",
]
