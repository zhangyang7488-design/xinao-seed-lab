from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction

import pytest

from xinao.foundation.semantics_basic import (
    RuleSemanticRecord,
    compile_basic_semantic,
    compile_basic_semantics,
    expand_selection_domain,
    semantic_records_hash,
    settle_basic,
    tier_probabilities,
)

SPECIAL_OPTIONS = (
    ("号码", "01-49", "47.285"),
    ("合单", None, "1.945"),
    ("合双", None, "1.945"),
    ("特单", None, "1.945"),
    ("特双", None, "1.945"),
    ("特大", None, "1.945"),
    ("特小", None, "1.945"),
    ("特尾大", None, "1.945"),
    ("特尾小", None, "1.945"),
    ("红波", None, "2.795"),
    ("绿波", None, "2.975"),
    ("蓝波", None, "2.975"),
)
REGULAR_OPTIONS = (
    ("号码", "01-49", "7.85"),
    ("总单", None, "1.945"),
    ("总双", None, "1.945"),
    ("总大", None, "1.945"),
    ("总小", None, "1.945"),
)
POSITION_OPTIONS = (
    ("单", None, "1.945"),
    ("双", None, "1.945"),
    ("号码", "01-49", "42.3"),
    ("合单", None, "1.945"),
    ("合双", None, "1.945"),
    ("大", None, "1.945"),
    ("小", None, "1.945"),
    ("红波", None, "2.795"),
    ("绿波", None, "2.975"),
    ("蓝波", None, "2.975"),
)


def _entry(
    *,
    baseline_id: str,
    family_id: str,
    play_id: str,
    play_name: str,
    pid: int,
    tid: int,
    panel: str,
    option_name: str,
    option_range: str | None,
    quote: str,
) -> dict[str, object]:
    return {
        "baseline_id": baseline_id,
        "family_id": family_id,
        "play_id": play_id,
        "play_name": play_name,
        "pid": pid,
        "tid": tid,
        "panel": panel,
        "option_name": option_name,
        "option_range": option_range,
        "baseline_odds_components": [quote],
    }


def _actual_basic_shape_entries() -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    baseline = 1
    for panel, tid, number_quote in (("A", 14, "47.285"), ("B", 15, "42.385")):
        for option_name, option_range, quote in SPECIAL_OPTIONS:
            entries.append(
                _entry(
                    baseline_id=f"BO{baseline:04d}",
                    family_id="special-number",
                    play_id=f"play:1:{tid}:{panel}",
                    play_name=f"特码{panel}盘",
                    pid=1,
                    tid=tid,
                    panel=panel,
                    option_name=option_name,
                    option_range=option_range,
                    quote=number_quote if option_name == "号码" else quote,
                )
            )
            baseline += 1
    for panel, tid, number_quote in (("A", 16, "7.85"), ("B", 17, "7.21")):
        for option_name, option_range, quote in REGULAR_OPTIONS:
            entries.append(
                _entry(
                    baseline_id=f"BO{baseline:04d}",
                    family_id="regular-number",
                    play_id=f"play:2:{tid}:{panel}",
                    play_name=f"正码{panel}盘",
                    pid=2,
                    tid=tid,
                    panel=panel,
                    option_name=option_name,
                    option_range=option_range,
                    quote=number_quote if option_name == "号码" else quote,
                )
            )
            baseline += 1
    for position in range(1, 7):
        tid = 17 + position
        for option_name, option_range, quote in POSITION_OPTIONS:
            entries.append(
                _entry(
                    baseline_id=f"BO{baseline:04d}",
                    family_id="regular-position-special",
                    play_id=f"play:3:{tid}:A",
                    play_name=f"正{position}特",
                    pid=3,
                    tid=tid,
                    panel="A",
                    option_name=option_name,
                    option_range=option_range,
                    quote=quote,
                )
            )
            baseline += 1
    return tuple(entries)


def _find_entry(family_id: str, play_name: str, option_name: str) -> dict[str, object]:
    return next(
        entry
        for entry in _actual_basic_shape_entries()
        if entry["family_id"] == family_id
        and entry["play_name"] == play_name
        and entry["option_name"] == option_name
    )


def _draw_with_value_at(position: int, value: int) -> tuple[int, ...]:
    others = iter(number for number in range(1, 50) if number != value)
    draw = [next(others) for _ in range(7)]
    draw[position] = value
    return tuple(draw)


def _side_outcomes(
    *,
    play_name: str,
    option_names: tuple[str, str],
    position: int,
    value: int,
) -> tuple[str, str]:
    draw = _draw_with_value_at(position, value)
    return tuple(
        settle_basic(
            entry=_find_entry("regular-position-special", play_name, option_name),
            draw=draw,
            selection=option_name,
        ).outcome
        for option_name in option_names
    )


def test_selection_domain_is_independently_expanded_from_catalog_fields() -> None:
    number = _find_entry("special-number", "特码A盘", "号码")
    side = _find_entry("special-number", "特码A盘", "特大")

    assert expand_selection_domain(number) == tuple(f"{value:02d}" for value in range(1, 50))
    assert expand_selection_domain(side) == ("特大",)

    unsupported = {**number, "option_range": "任选五肖"}
    with pytest.raises(ValueError, match="option_range"):
        expand_selection_domain(unsupported)


def test_all_actual_basic_family_shapes_compile_without_claiming_full_433_closure() -> None:
    records = compile_basic_semantics(_actual_basic_shape_entries())
    counts = {
        family_id: sum(record.family_id == family_id for record in records)
        for family_id in {record.family_id for record in records}
    }

    assert len(records) == 94
    assert counts == {
        "special-number": 24,
        "regular-number": 10,
        "regular-position-special": 60,
    }
    assert sum(len(record.selection_space) for record in records) == 574
    assert all(isinstance(record, RuleSemanticRecord) for record in records)
    assert all(
        record.semantic_status == ("EXPLICIT_PAGE", "RESEARCH_CONVENTION") for record in records
    )
    assert all(record.payout_component_index == 0 for record in records)
    assert all(record.principal_refund_on_normal_settlement is False for record in records)


def test_special_number_exact_attributes_void_and_color_are_distinct() -> None:
    draw = (39, 36, 28, 12, 24, 40, 49)
    exact = settle_basic(
        entry=_find_entry("special-number", "特码A盘", "号码"),
        draw=draw,
        selection="49",
    )
    side = settle_basic(
        entry=_find_entry("special-number", "特码A盘", "合单"),
        draw=draw,
        selection="合单",
    )
    green = settle_basic(
        entry=_find_entry("special-number", "特码A盘", "绿波"),
        draw=draw,
        selection="绿波",
    )

    assert (exact.outcome, exact.unit_payout) == ("HIT", "47.285")
    assert (side.outcome, side.unit_payout) == ("VOID", "1")
    assert (green.outcome, green.unit_payout) == ("HIT", "2.975")
    assert exact.principal_refund_added is False
    assert green.principal_refund_added is False


def test_regular_number_uses_first_six_but_total_properties_use_all_seven() -> None:
    draw = (39, 36, 28, 49, 12, 24, 40)  # all-seven sum=228
    exact_regular = _find_entry("regular-number", "正码A盘", "号码")
    total_big = _find_entry("regular-number", "正码A盘", "总大")
    total_even = _find_entry("regular-number", "正码A盘", "总双")

    assert settle_basic(entry=exact_regular, draw=draw, selection="28").outcome == "HIT"
    miss = settle_basic(entry=exact_regular, draw=draw, selection="40")
    assert (miss.outcome, miss.unit_payout) == ("MISS", "0")
    assert settle_basic(entry=total_big, draw=draw, selection="总大").outcome == "HIT"
    assert settle_basic(entry=total_even, draw=draw, selection="总双").outcome == "HIT"


def test_regular_position_is_ordered_not_membership_or_sort_order() -> None:
    draw = (39, 36, 28, 49, 12, 24, 40)
    pos1_exact = _find_entry("regular-position-special", "正1特", "号码")
    pos4_exact = _find_entry("regular-position-special", "正4特", "号码")
    pos4_odd = _find_entry("regular-position-special", "正4特", "单")
    pos4_green = _find_entry("regular-position-special", "正4特", "绿波")

    assert settle_basic(entry=pos1_exact, draw=draw, selection="28").outcome == "MISS"
    assert settle_basic(entry=pos4_exact, draw=draw, selection="49").outcome == "HIT"
    assert settle_basic(entry=pos4_odd, draw=draw, selection="单").outcome == "VOID"
    assert settle_basic(entry=pos4_green, draw=draw, selection="绿波").outcome == "HIT"


@pytest.mark.parametrize(
    ("value", "expected_size", "expected_tail", "expected_he"),
    [
        (24, ("MISS", "HIT"), ("MISS", "HIT"), ("MISS", "HIT")),
        (25, ("HIT", "MISS"), ("HIT", "MISS"), ("HIT", "MISS")),
        (48, ("HIT", "MISS"), ("HIT", "MISS"), ("MISS", "HIT")),
        (49, ("VOID", "VOID"), ("VOID", "VOID"), ("VOID", "VOID")),
    ],
)
def test_special_attribute_boundaries(
    value: int,
    expected_size: tuple[str, str],
    expected_tail: tuple[str, str],
    expected_he: tuple[str, str],
) -> None:
    draw = _draw_with_value_at(6, value)

    def outcomes(names: tuple[str, str]) -> tuple[str, str]:
        return tuple(
            settle_basic(
                entry=_find_entry("special-number", "特码A盘", name),
                draw=draw,
                selection=name,
            ).outcome
            for name in names
        )

    assert outcomes(("特大", "特小")) == expected_size
    assert outcomes(("特尾大", "特尾小")) == expected_tail
    assert outcomes(("合单", "合双")) == expected_he


def test_position_side_pairs_partition_every_anchor_value() -> None:
    for value in range(1, 50):
        for pair in (("单", "双"), ("大", "小"), ("合单", "合双")):
            outcomes = _side_outcomes(
                play_name="正3特",
                option_names=pair,
                position=2,
                value=value,
            )
            if value == 49:
                assert outcomes == ("VOID", "VOID")
            else:
                assert sorted(outcomes) == ["HIT", "MISS"]


def test_color_sets_partition_all_49_values_and_keep_49_green() -> None:
    names = ("红波", "绿波", "蓝波")
    for value in range(1, 50):
        draw = _draw_with_value_at(6, value)
        outcomes = tuple(
            settle_basic(
                entry=_find_entry("special-number", "特码A盘", name),
                draw=draw,
                selection=name,
            ).outcome
            for name in names
        )
        assert outcomes.count("HIT") == 1
        assert outcomes.count("VOID") == 0
        if value == 49:
            assert outcomes == ("MISS", "HIT", "MISS")


def test_hit_pays_snapshot_q_and_miss_pays_zero_without_added_principal() -> None:
    entry = _find_entry("regular-position-special", "正2特", "号码")
    hit = settle_basic(entry=entry, draw=(1, 2, 3, 4, 5, 6, 7), selection="02")
    miss = settle_basic(entry=entry, draw=(1, 2, 3, 4, 5, 6, 7), selection="03")

    assert (hit.unit_payout, hit.principal_refund_added) == ("42.3", False)
    assert (miss.unit_payout, miss.principal_refund_added) == ("0", False)


def test_semantic_map_hash_is_stable_under_entry_reordering() -> None:
    records = compile_basic_semantics(_actual_basic_shape_entries())
    assert semantic_records_hash(records) == semantic_records_hash(tuple(reversed(records)))


@pytest.mark.parametrize(
    "draw",
    [
        (1, 2, 3, 4, 5, 6),
        (1, 2, 3, 4, 5, 6, 6),
        (0, 1, 2, 3, 4, 5, 6),
        (True, 1, 2, 3, 4, 5, 6),
    ],
)
def test_invalid_draws_fail_closed(draw: tuple[object, ...]) -> None:
    entry = _find_entry("special-number", "特码A盘", "号码")
    with pytest.raises((TypeError, ValueError)):
        settle_basic(entry=entry, draw=draw, selection="07")


def test_unsupported_basic_option_and_duplicate_baseline_fail_closed() -> None:
    entry = _find_entry("special-number", "特码A盘", "号码")
    with pytest.raises(ValueError, match="unsupported"):
        compile_basic_semantic({**entry, "option_name": "特合大"})
    with pytest.raises(ValueError, match="duplicate baseline_id"):
        compile_basic_semantics((entry, entry))


def test_records_iterator_does_not_need_materialized_input() -> None:
    def entries() -> Iterator[dict[str, object]]:
        yield from _actual_basic_shape_entries()[:3]

    assert len(compile_basic_semantics(entries())) == 3


def test_every_basic_record_has_exact_normalized_terminal_probabilities() -> None:
    records = compile_basic_semantics(_actual_basic_shape_entries())
    for record in records:
        probabilities = tier_probabilities(record)
        assert set(probabilities) == {tier.tier_id for tier in record.terminal_tiers}
        assert sum(probabilities.values(), Fraction(0)) == 1
        assert all(Fraction(0) <= value <= Fraction(1) for value in probabilities.values())

    special_exact = next(
        record
        for record in records
        if record.play_name == "特码A盘" and record.option_name == "号码"
    )
    regular_exact = next(
        record
        for record in records
        if record.play_name == "正码A盘" and record.option_name == "号码"
    )
    special_odd = next(
        record
        for record in records
        if record.play_name == "特码A盘" and record.option_name == "特单"
    )
    assert tier_probabilities(special_exact) == {"HIT": Fraction(1, 49), "MISS": Fraction(48, 49)}
    assert tier_probabilities(regular_exact) == {"HIT": Fraction(6, 49), "MISS": Fraction(43, 49)}
    assert tier_probabilities(special_odd) == {
        "HIT": Fraction(24, 49),
        "MISS": Fraction(24, 49),
        "VOID": Fraction(1, 49),
    }

    total_big = next(
        record
        for record in records
        if record.play_name == "正码A盘" and record.option_name == "总大"
    )
    total_small = next(
        record
        for record in records
        if record.play_name == "正码A盘" and record.option_name == "总小"
    )
    assert tier_probabilities(total_big)["HIT"] + tier_probabilities(total_small)["HIT"] == 1
