from __future__ import annotations

from datetime import date
from fractions import Fraction
from itertools import combinations

import pytest

from xinao.foundation.semantics_sets import (
    DEFAULT_PLAY_CATALOG_PATH,
    TARGET_FAMILY_COUNTS,
    compile_set_family_semantics,
    load_play_catalog,
    number_attribute_table,
    settle_rule,
    tier_probabilities,
    zodiac_number_table,
)


@pytest.fixture(scope="module")
def compilation():
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    return compile_set_family_semantics(load_play_catalog())


def _rule(compilation, baseline_id: str):
    return next(
        record
        for record in compilation.rule_semantic_map.records
        if record.baseline_id == baseline_id
    )


def test_catalog_slice_is_exactly_119_rows_without_claiming_full_433(compilation) -> None:
    coverage = compilation.rule_semantic_map.coverage
    assert TARGET_FAMILY_COUNTS == {
        "other-explicit": 95,
        "one-zodiac-tail": 22,
        "six-zodiac": 2,
    }
    assert coverage.catalog_total == 433
    assert coverage.mapped_baselines == 119
    assert coverage.remaining_baselines == 314
    assert coverage.family_counts == TARGET_FAMILY_COUNTS
    assert coverage.foundation_complete is False
    assert len({record.baseline_id for record in compilation.rule_semantic_map.records}) == 119


def test_all_rows_bind_rule_domain_settlement_and_probability_refs(compilation) -> None:
    for record in compilation.rule_semantic_map.records:
        assert record.rule_version_ref
        assert record.selection_domain_ref == compilation.expected_selection_domain.domain_ref
        assert record.settlement_function_ref
        assert record.probability_formula_ref
        assert record.interpretation_status == "ACTIVE"
        assert record.raw_site_fields["baseline_id"] == record.baseline_id
        assert "baseline_odds_components" in record.raw_site_fields
        assert "baseline_odds_components" not in record.semantic_parameters


def test_expected_selection_domain_is_independent_and_expands_six_zodiac(compilation) -> None:
    domain = compilation.expected_selection_domain
    assert domain.baseline_count == 119
    assert domain.expanded_selection_count == 95 + 22 + 2 * 924
    assert len(domain.entries) == domain.expanded_selection_count
    assert len({entry.selection_key for entry in domain.entries}) == len(domain.entries)
    six = [entry for entry in domain.entries if entry.family_id == "six-zodiac"]
    assert len(six) == 2 * len(tuple(combinations(range(12), 6)))
    assert all(len(entry.selected_values) == 6 for entry in six)


def test_ambiguous_market_readings_are_explicit_not_silently_blended(compilation) -> None:
    interpretations = {item.interpretation_ref: item for item in compilation.interpretations}
    assert interpretations["half-wave-49-void.v1"].status == "ACTIVE"
    assert interpretations["half-wave-49-miss.v1"].status == "ALTERNATE"
    assert interpretations["six-zodiac-select-six.v1"].status == "ACTIVE"
    alternate = interpretations["six-zodiac-select-five-from-raw-label.v1"]
    assert alternate.status == "ALTERNATE"
    assert "任选五肖" in alternate.basis
    assert interpretations["six-zodiac-49-normal-zodiac.v1"].status == "ALTERNATE"
    six_rule = _rule(compilation, "BO0218")
    assert six_rule.interpretation_ref == "six-zodiac-select-six.v1"
    assert six_rule.alternative_interpretation_refs == (
        "six-zodiac-select-five-from-raw-label.v1",
        "six-zodiac-49-normal-zodiac.v1",
    )


def test_attribute_tables_are_versioned_and_partition_1_to_49() -> None:
    table = number_attribute_table()
    assert table.table_ref == "xinao-number-attributes.v1"
    assert set().union(*table.color_wave.values()) == set(range(1, 50))
    assert sum(map(len, table.color_wave.values())) == 49
    assert set().union(*table.five_elements.values()) == set(range(1, 50))
    assert sum(map(len, table.five_elements.values())) == 49
    assert table.tail["0尾"] == (10, 20, 30, 40)
    assert all(len(table.tail[f"{tail}尾"]) == 5 for tail in range(1, 10))
    assert set(table.home_wild) == {"家禽", "野兽"}
    assert table.content_hash


def test_zodiac_uses_draw_date_and_switches_on_lunar_new_year() -> None:
    before = zodiac_number_table(date(2026, 2, 16))
    after = zodiac_number_table(date(2026, 2, 17))
    assert before.lunar_year_zodiac == "蛇"
    assert after.lunar_year_zodiac == "马"
    assert before.numbers_by_zodiac["马"] == (12, 24, 36, 48)
    assert after.numbers_by_zodiac["马"] == (1, 13, 25, 37, 49)
    assert sum(len(numbers) for numbers in after.numbers_by_zodiac.values()) == 49
    assert after.content_hash != before.content_hash


def test_special_zodiac_uses_only_special_but_one_zodiac_uses_all_seven(compilation) -> None:
    special_rabbit = _rule(compilation, "BO0095")
    one_rabbit = _rule(compilation, "BO0168")
    draw = (4, 1, 2, 3, 5, 6, 7)
    assert settle_rule(special_rabbit, draw=draw, draw_date=date(2026, 7, 1)) == "MISS"
    assert settle_rule(one_rabbit, draw=draw, draw_date=date(2026, 7, 1)) == "HIT"


def test_half_wave_49_void_and_seven_count_boundaries(compilation) -> None:
    red_odd = _rule(compilation, "BO0107")
    odd_four = _rule(compilation, "BO0123")
    assert settle_rule(red_odd, draw=(1, 2, 3, 4, 5, 6, 49), draw_date="2026-07-01") == "VOID"
    draw = (1, 3, 24, 25, 26, 28, 49)
    assert settle_rule(odd_four, draw=draw, draw_date="2026-07-01") == "HIT"


def test_at_least_once_and_all_miss_are_complements(compilation) -> None:
    one_zero_tail = _rule(compilation, "BO0180")
    no_zero_tail = _rule(compilation, "BO0202")
    hit_draw = (1, 2, 3, 4, 5, 6, 10)
    miss_draw = (1, 2, 3, 4, 5, 6, 7)
    assert settle_rule(one_zero_tail, draw=hit_draw, draw_date="2026-07-01") == "HIT"
    assert settle_rule(no_zero_tail, draw=hit_draw, draw_date="2026-07-01") == "MISS"
    assert settle_rule(one_zero_tail, draw=miss_draw, draw_date="2026-07-01") == "MISS"
    assert settle_rule(no_zero_tail, draw=miss_draw, draw_date="2026-07-01") == "HIT"


def test_probability_formulas_preserve_four_and_five_number_tiers(compilation) -> None:
    zero_tail = _rule(compilation, "BO0180")
    one_tail = _rule(compilation, "BO0181")
    four = tier_probabilities(zero_tail, draw_date="2026-07-01")
    five = tier_probabilities(one_tail, draw_date="2026-07-01")
    assert four["HIT"] == Fraction(7139, 15134)
    assert five["HIT"] == Fraction(12574, 22701)
    assert sum(four.values()) == sum(five.values()) == 1


def test_every_mapped_record_has_a_normalized_exact_probability(compilation) -> None:
    selected = ("鼠", "牛", "虎", "兔", "龙", "蛇")
    for record in compilation.rule_semantic_map.records:
        probabilities = tier_probabilities(
            record,
            draw_date="2026-07-01",
            selection=selected if record.family_id == "six-zodiac" else None,
        )
        assert set(probabilities) == set(record.settlement_tiers)
        assert sum(probabilities.values()) == 1
        assert all(
            Fraction(0) <= probability <= Fraction(1) for probability in probabilities.values()
        )


def test_six_zodiac_validates_selection_and_partitions_non_void_sides(compilation) -> None:
    hit_rule = _rule(compilation, "BO0218")
    miss_rule = _rule(compilation, "BO0217")
    chosen = ("鼠", "牛", "虎", "兔", "龙", "蛇")
    draw = (2, 3, 4, 5, 6, 7, 19)
    assert settle_rule(hit_rule, draw=draw, draw_date="2026-07-01", selection=chosen) == "HIT"
    assert settle_rule(miss_rule, draw=draw, draw_date="2026-07-01", selection=chosen) == "MISS"
    hit_probability = tier_probabilities(
        hit_rule,
        draw_date="2026-07-01",
        selection=chosen,
    )
    miss_probability = tier_probabilities(
        miss_rule,
        draw_date="2026-07-01",
        selection=chosen,
    )
    assert hit_probability["HIT"] + miss_probability["HIT"] == Fraction(48, 49)
    assert hit_probability["VOID"] == miss_probability["VOID"] == Fraction(1, 49)
    assert (
        settle_rule(
            hit_rule,
            draw=(2, 3, 4, 5, 6, 7, 49),
            draw_date="2026-07-01",
            selection=chosen,
        )
        == "VOID"
    )
    with pytest.raises(ValueError, match="exactly 6"):
        settle_rule(
            hit_rule,
            draw=draw,
            draw_date="2026-07-01",
            selection=chosen[:5],
        )
    with pytest.raises(ValueError, match="exactly 6"):
        settle_rule(
            hit_rule,
            draw=(2, 3, 4, 5, 6, 7, 49),
            draw_date="2026-07-01",
            selection=chosen[:1],
        )


@pytest.mark.parametrize(
    "draw",
    [
        (1, 2, 3, 4, 5, 6),
        (1, 2, 3, 4, 5, 6, 6),
        (0, 1, 2, 3, 4, 5, 6),
        (1, 2, 3, 4, 5, 6, 50),
    ],
)
def test_invalid_draws_fail_closed(compilation, draw) -> None:
    rule = _rule(compilation, "BO0168")
    with pytest.raises((TypeError, ValueError)):
        settle_rule(rule, draw=draw, draw_date="2026-07-01")


def test_catalog_entry_reordering_does_not_change_hash() -> None:
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    catalog = load_play_catalog()
    reordered = {**catalog, "entries": list(reversed(catalog["entries"]))}
    first = compile_set_family_semantics(catalog)
    second = compile_set_family_semantics(reordered)
    assert first.content_hash == second.content_hash
    assert first.rule_semantic_map.content_hash == second.rule_semantic_map.content_hash
    assert (
        first.expected_selection_domain.content_hash
        == second.expected_selection_domain.content_hash
    )


def test_missing_target_row_is_rejected_instead_of_silently_reducing_coverage() -> None:
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    catalog = load_play_catalog()
    broken_entries = [dict(entry) for entry in catalog["entries"]]
    next(entry for entry in broken_entries if entry["baseline_id"] == "BO0218")["family_id"] = (
        "special-number"
    )
    broken = {**catalog, "entries": broken_entries}
    with pytest.raises(ValueError, match="family coverage"):
        compile_set_family_semantics(broken)
