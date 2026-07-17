"""Independent outcome oracles for F1 generated property evidence.

The functions in this module deliberately do not import or call the production
``settle_*`` functions.  They project the compiled records into plain
arithmetic and set predicates so the generated property suite compares two
different execution paths.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal

Outcome = Literal["HIT", "MISS", "VOID"]

_BASIC_COLOR_NUMBERS = {
    "红波": frozenset({1, 2, 7, 8, 12, 13, 18, 19, 23, 24, 29, 30, 34, 35, 40, 45, 46}),
    "蓝波": frozenset({3, 4, 9, 10, 14, 15, 20, 25, 26, 31, 36, 37, 41, 42, 47, 48}),
    "绿波": frozenset({5, 6, 11, 16, 17, 21, 22, 27, 28, 32, 33, 38, 39, 43, 44, 49}),
}
_PARLAY_COLOR_NUMBERS = {
    "RED": _BASIC_COLOR_NUMBERS["红波"],
    "BLUE": _BASIC_COLOR_NUMBERS["蓝波"],
    "GREEN": _BASIC_COLOR_NUMBERS["绿波"],
}
_ZODIAC_ORDER = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
_LUNAR_YEAR_BOUNDARIES = (
    (date(2023, 1, 22), "兔"),
    (date(2024, 2, 10), "龙"),
    (date(2025, 1, 29), "蛇"),
    (date(2026, 2, 17), "马"),
    (date(2027, 2, 6), "羊"),
)
_SUPPORTED_DRAW_DATE_MIN = date(2024, 1, 1)
_SUPPORTED_DRAW_DATE_MAX = date(2027, 12, 31)


def _independent_draw_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        observed = value.date()
    elif isinstance(value, date):
        observed = value
    elif isinstance(value, str):
        try:
            observed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("draw_date must be an ISO Gregorian date") from exc
    else:
        raise TypeError("draw_date must be a date, datetime, or ISO date string")
    if not _SUPPORTED_DRAW_DATE_MIN <= observed <= _SUPPORTED_DRAW_DATE_MAX:
        raise ValueError("draw_date is outside the independent oracle boundary table")
    return observed


def _independent_zodiac_number_sets(
    draw_date: date | datetime | str,
) -> dict[str, frozenset[int]]:
    """Derive zodiac sets without importing the production lookup helper."""

    observed = _independent_draw_date(draw_date)
    eligible = [item for item in _LUNAR_YEAR_BOUNDARIES if item[0] <= observed]
    if not eligible:
        raise ValueError("draw_date precedes the independent oracle boundary table")
    year_zodiac = eligible[-1][1]
    year_index = _ZODIAC_ORDER.index(year_zodiac)
    grouped: dict[str, set[int]] = {zodiac: set() for zodiac in _ZODIAC_ORDER}
    for number in range(1, 50):
        zodiac = _ZODIAC_ORDER[(year_index - (number - 1)) % len(_ZODIAC_ORDER)]
        grouped[zodiac].add(number)
    return {zodiac: frozenset(grouped[zodiac]) for zodiac in _ZODIAC_ORDER}


def _basic_anchor(record: Any, draw: tuple[int, ...]) -> int | tuple[int, ...]:
    if record.draw_anchor == "SPECIAL_POSITION_7":
        return draw[6]
    if record.draw_anchor == "REGULAR_SET_POSITIONS_1_TO_6":
        return draw[:6]
    if record.draw_anchor == "ALL_SEVEN_SUM":
        return sum(draw)
    if record.position is not None:
        return draw[record.position - 1]
    raise ValueError(f"unsupported independent basic anchor: {record.draw_anchor}")


def basic_outcome(record: Any, draw: Sequence[int], selection: str | int) -> Outcome:
    """Settle one basic record with direct arithmetic instead of its subject."""

    numbers = tuple(int(value) for value in draw)
    anchor = _basic_anchor(record, numbers)
    if record.void_policy == "DRAW_VALUE_49_REFUND_STAKE" and anchor == 49:
        return "VOID"

    family = record.semantic_family
    selected = int(selection) if family.endswith("exact_number") else str(selection)
    if family == "special_exact_number":
        hit = anchor == selected
    elif family == "regular_exact_number":
        hit = selected in anchor
    elif family == "position_exact_number":
        hit = anchor == selected
    elif family == "regular_sum_parity":
        hit = (int(anchor) % 2 == 1) == (record.option_name == "总单")
    elif family == "regular_sum_size":
        hit = (int(anchor) >= 175) == (record.option_name == "总大")
    elif family in {"special_parity", "position_parity"}:
        hit = (int(anchor) % 2 == 1) == (record.option_name in {"特单", "单"})
    elif family in {"special_digit_sum_parity", "position_digit_sum_parity"}:
        digit_sum = int(anchor) // 10 + int(anchor) % 10
        hit = (digit_sum % 2 == 1) == (record.option_name == "合单")
    elif family in {"special_size", "position_size"}:
        hit = (int(anchor) >= 25) == (record.option_name in {"特大", "大"})
    elif family == "special_tail_size":
        hit = (int(anchor) % 10 >= 5) == (record.option_name == "特尾大")
    elif family in {"special_color", "position_color"}:
        hit = int(anchor) in _BASIC_COLOR_NUMBERS[record.option_name]
    else:
        raise ValueError(f"unsupported independent basic family: {family}")
    return "HIT" if hit else "MISS"


def _record_number_set(record: Any, draw_date: date | datetime | str) -> frozenset[int]:
    parameters = record.semantic_parameters
    kind = parameters.get("set_kind")
    selector = str(parameters.get("selector"))
    if kind == "EXPLICIT_NUMBER_SET":
        return frozenset(int(value) for value in parameters["number_set"])
    if kind == "TAIL":
        tail = int(selector.removesuffix("尾"))
        return frozenset(number for number in range(1, 50) if number % 10 == tail)
    if kind == "ZODIAC_BY_DRAW_DATE":
        return _independent_zodiac_number_sets(draw_date)[selector]
    raise ValueError(f"unsupported independent set kind: {kind}")


def _partition_labels(
    draw: tuple[int, ...],
    partition: str,
    draw_date: date | datetime | str,
) -> set[str]:
    if partition == "TAIL":
        return {f"{number % 10}尾" for number in draw}
    if partition == "ZODIAC_BY_DRAW_DATE":
        table = _independent_zodiac_number_sets(draw_date)
        reverse = {number: zodiac for zodiac, values in table.items() for number in values}
        return {reverse[number] for number in draw}
    raise ValueError(f"unsupported independent partition: {partition}")


def set_outcome(
    record: Any,
    draw: Sequence[int],
    draw_date: date | datetime | str,
    selection: Sequence[str] | None,
) -> Outcome:
    """Settle set families without importing the production set dispatcher."""

    numbers = tuple(int(value) for value in draw)
    parameters = record.semantic_parameters
    family = record.semantic_family_ref
    if family == "special-number-in-set.v1":
        special = numbers[-1]
        if special in set(parameters.get("void_numbers", ())):
            return "VOID"
        return "HIT" if special in _record_number_set(record, draw_date) else "MISS"
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
        observed = len(_partition_labels(numbers, parameters["partition"], draw_date))
        return "HIT" if observed == parameters["expected_count"] else "MISS"
    if family in {"seven-number-all-miss-set.v1", "seven-number-at-least-once-set.v1"}:
        intersects = not set(numbers).isdisjoint(_record_number_set(record, draw_date))
        hit = not intersects if family == "seven-number-all-miss-set.v1" else intersects
        return "HIT" if hit else "MISS"
    if family == "six-zodiac-special-membership.v1":
        if selection is None:
            raise ValueError("six-zodiac independent oracle requires a selection")
        special = numbers[-1]
        if special in set(parameters.get("void_numbers", ())):
            return "VOID"
        table = _independent_zodiac_number_sets(draw_date)
        chosen = {number for zodiac in selection for number in table[str(zodiac)]}
        in_set = special in chosen
        hit = in_set if parameters["side"] == "IN" else not in_set
        return "HIT" if hit else "MISS"
    raise ValueError(f"unsupported independent set family: {family}")


def combination_outcome(
    record: Any, draw: Sequence[int], selection: Sequence[int | str]
) -> Outcome:
    """Settle a combination using hit cardinalities only."""

    numbers = tuple(int(value) for value in draw)
    selected = {int(value) for value in selection}
    regular_hits = len(selected & set(numbers[:6]))
    special_hit = numbers[6] in selected
    seven_hits = regular_hits + int(special_hit)
    kind = record.semantic_kind
    hit = (
        (kind == "ALL_SELECTED_REGULAR" and regular_hits == record.selection_domain.arity)
        or (
            kind == "TWO_REGULAR_OR_REGULAR_SPECIAL"
            and (regular_hits == 2 or (regular_hits == 1 and special_hit))
        )
        or (kind == "REGULAR_SPECIAL" and regular_hits == 1 and special_hit)
        or (kind == "THREE_OR_TWO_REGULAR" and regular_hits in {2, 3})
        or (kind == "NO_SELECTED_IN_SEVEN" and seven_hits == 0)
        or (kind == "EXACTLY_ONE_SELECTED_IN_SEVEN" and seven_hits == 1)
        or (kind == "ANY_SELECTED_IN_SEVEN" and seven_hits >= 1)
    )
    return "HIT" if hit else "MISS"


def linked_outcome(
    records: Sequence[Any],
    draw: Sequence[int],
    draw_date: date | datetime | str,
) -> Outcome:
    """Settle linked labels through direct set intersection predicates."""

    numbers = set(int(value) for value in draw)
    first = records[0]
    if first.family_id == "linked-zodiac":
        table = _independent_zodiac_number_sets(draw_date)
        label_sets = [set(table[record.component_label]) for record in records]
    else:
        label_sets = [set(record.catalog_number_set_snapshot) for record in records]
    if first.polarity == "HIT_ALL_LABELS":
        hit = all(not numbers.isdisjoint(label_set) for label_set in label_sets)
    else:
        hit = all(numbers.isdisjoint(label_set) for label_set in label_sets)
    return "HIT" if hit else "MISS"


def parlay_outcome(records: Sequence[Any], draw: Sequence[int]) -> Outcome:
    """Settle parlay legs with an independent per-position attribute predicate."""

    numbers = tuple(int(value) for value in draw)
    for record in records:
        attribute = str(record.component_attribute)
        value = numbers[int(record.component_position) - 1]
        if value == 49 and attribute in {"ODD", "EVEN", "BIG", "SMALL"}:
            continue
        if attribute == "ODD":
            hit = value % 2 == 1
        elif attribute == "EVEN":
            hit = value % 2 == 0
        elif attribute == "BIG":
            hit = value >= 25
        elif attribute == "SMALL":
            hit = value <= 24
        else:
            hit = value in _PARLAY_COLOR_NUMBERS[attribute]
        if not hit:
            return "MISS"
    return "HIT"


__all__ = [
    "Outcome",
    "basic_outcome",
    "combination_outcome",
    "linked_outcome",
    "parlay_outcome",
    "set_outcome",
]
