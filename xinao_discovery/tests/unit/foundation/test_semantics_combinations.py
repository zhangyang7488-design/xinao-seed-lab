from __future__ import annotations

import json
from fractions import Fraction
from math import comb
from pathlib import Path

import pytest

from xinao.foundation.semantics_combinations import (
    EXPECTED_BASELINE_IDS,
    TARGET_FAMILY_IDS,
    CombinationSemanticRecord,
    combination_records_hash,
    compile_combination_catalog,
    compile_combination_semantic,
    compile_combination_semantics,
    expand_number_pool,
    selection_domain_hash,
    settle_combination,
    tier_probabilities,
)

CATALOG_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_catalog.v1.json"
)

ROW_SHAPES = (
    ("BO0212", "连码", "linked-number", 6, 34, "二全中", "66.2"),
    ("BO0213", "连码", "linked-number", 6, 35, "二中特", "51.5/35.5"),
    ("BO0214", "连码", "linked-number", 6, 36, "特串", "165"),
    ("BO0215", "连码", "linked-number", 6, 37, "三全中", "766"),
    ("BO0216", "连码", "linked-number", 6, 38, "三中二", "126/20.1"),
    ("BO0261", "多选不中", "multi-select-no-hit", 9, 41, "五不中", "2.21"),
    ("BO0262", "多选不中", "multi-select-no-hit", 9, 42, "六不中", "2.581"),
    ("BO0263", "多选不中", "multi-select-no-hit", 9, 43, "七不中", "3.01"),
    ("BO0264", "多选不中", "multi-select-no-hit", 9, 44, "八不中", "3.501"),
    ("BO0265", "多选不中", "multi-select-no-hit", 9, 45, "九不中", "4.45"),
    ("BO0266", "多选不中", "multi-select-no-hit", 9, 46, "十不中", "5.45"),
    ("BO0423", "多选中一", "multi-select-one-hit", 12, 61, "五中一", "2.01"),
    ("BO0424", "多选中一", "multi-select-one-hit", 12, 62, "六中一", "2.05"),
    ("BO0425", "多选中一", "multi-select-one-hit", 12, 63, "七中一", "2.08"),
    ("BO0426", "多选中一", "multi-select-one-hit", 12, 64, "八中一", "2.15"),
    ("BO0427", "多选中一", "multi-select-one-hit", 12, 65, "九中一", "2.25"),
    ("BO0428", "多选中一", "multi-select-one-hit", 12, 66, "十中一", "2.29"),
    ("BO0429", "特平中", "special-regular-hit", 13, 67, "一粒任中", "3.5"),
    ("BO0430", "特平中", "special-regular-hit", 13, 68, "二粒任中", "2.7"),
    ("BO0431", "特平中", "special-regular-hit", 13, 69, "三粒任中", "1.8"),
    ("BO0432", "特平中", "special-regular-hit", 13, 70, "四粒任中", "1.65"),
    ("BO0433", "特平中", "special-regular-hit", 13, 71, "五粒任中", "1.45"),
)


def _entries() -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for baseline_id, group, family, pid, tid, name, quote in ROW_SHAPES:
        rows.append(
            {
                "baseline_id": baseline_id,
                "option_id": f"baseline-option:{baseline_id}",
                "play_id": f"play:{pid}:{tid}:none",
                "play_group": group,
                "family_id": family,
                "play_name": name,
                "pid": pid,
                "tid": tid,
                "panel": None,
                "bet_shape": (
                    "复式/拖头/生肖对碰/尾数对碰/生尾对碰/任意对碰"
                    if family == "linked-number"
                    else "复式/多组"
                ),
                "option_name": "号码",
                "option_range": "01-49",
                "baseline_odds_components": quote.split("/"),
            }
        )
    return tuple(rows)


def _entry(baseline_id: str) -> dict[str, object]:
    return next(row for row in _entries() if row["baseline_id"] == baseline_id)


def test_all_22_catalog_rows_compile_with_exact_family_coverage() -> None:
    records = compile_combination_semantics(_entries())
    counts = {
        family: sum(record.family_id == family for record in records)
        for family in TARGET_FAMILY_IDS
    }

    assert tuple(record.baseline_id for record in records) == EXPECTED_BASELINE_IDS
    assert counts == {
        "linked-number": 5,
        "multi-select-no-hit": 6,
        "multi-select-one-hit": 6,
        "special-regular-hit": 5,
    }
    assert all(isinstance(record, CombinationSemanticRecord) for record in records)
    assert all(record.principal_refund_on_normal_settlement is False for record in records)
    assert all("ORAL" not in "|".join(record.semantic_basis) for record in records)
    assert compile_combination_semantic(_entry("BO0213")).tier_order_basis.endswith("中二/中特")
    assert compile_combination_semantic(_entry("BO0216")).tier_order_basis.endswith("中三/中二")


def test_selection_domains_are_compact_exact_and_independently_hashable() -> None:
    records = compile_combination_semantics(_entries())
    assert {
        record.baseline_id: record.selection_domain.arity
        for record in records
        if record.baseline_id in {"BO0216", "BO0262", "BO0424", "BO0433"}
    } == {"BO0216": 3, "BO0262": 6, "BO0424": 6, "BO0433": 5}
    assert all(
        record.selection_domain.atomic_selection_count == comb(49, record.selection_domain.arity)
        for record in records
    )
    assert len({selection_domain_hash(record) for record in records}) == 22


def test_bo0216_three_in_two_uses_two_mutually_exclusive_quote_tiers() -> None:
    entry = _entry("BO0216")
    selection = (1, 2, 3)
    hit_three = settle_combination(
        entry=entry,
        draw=(1, 2, 3, 10, 11, 12, 13),
        selection=selection,
    )
    hit_two_with_third_special = settle_combination(
        entry=entry,
        draw=(1, 2, 10, 11, 12, 13, 3),
        selection=selection,
    )
    miss = settle_combination(
        entry=entry,
        draw=(1, 10, 11, 12, 13, 14, 2),
        selection=selection,
    )

    assert (hit_three.tier_id, hit_three.unit_payout) == ("THREE_REGULAR", "126")
    assert (hit_two_with_third_special.tier_id, hit_two_with_third_special.unit_payout) == (
        "TWO_REGULAR",
        "20.1",
    )
    assert (miss.outcome, miss.unit_payout) == ("MISS", "0")


def test_no_hit_exactly_one_and_any_hit_predicates_do_not_collapse() -> None:
    selected_six = (1, 2, 3, 4, 5, 6)
    no_intersection = (7, 8, 9, 10, 11, 12, 13)
    one_intersection = (1, 7, 8, 9, 10, 11, 12)
    two_intersections = (1, 2, 7, 8, 9, 10, 11)

    no_hit = settle_combination(
        entry=_entry("BO0262"),
        draw=no_intersection,
        selection=selected_six,
    )
    no_hit_miss = settle_combination(
        entry=_entry("BO0262"),
        draw=one_intersection,
        selection=selected_six,
    )
    exactly_one = settle_combination(
        entry=_entry("BO0424"),
        draw=one_intersection,
        selection=selected_six,
    )
    zero_is_not_one = settle_combination(
        entry=_entry("BO0424"),
        draw=no_intersection,
        selection=selected_six,
    )
    two_is_not_one = settle_combination(
        entry=_entry("BO0424"),
        draw=two_intersections,
        selection=selected_six,
    )
    any_hit = settle_combination(
        entry=_entry("BO0433"),
        draw=two_intersections,
        selection=(1, 2, 3, 4, 5),
    )
    any_hit_miss = settle_combination(
        entry=_entry("BO0433"),
        draw=(10, 11, 12, 13, 14, 15, 16),
        selection=(1, 2, 3, 4, 5),
    )

    assert (no_hit.outcome, no_hit.unit_payout) == ("HIT", "2.581")
    assert (no_hit_miss.outcome, no_hit_miss.unit_payout) == ("MISS", "0")
    assert (exactly_one.outcome, exactly_one.unit_payout) == ("HIT", "2.05")
    assert zero_is_not_one.outcome == "MISS"
    assert two_is_not_one.outcome == "MISS"
    assert (any_hit.outcome, any_hit.unit_payout) == ("HIT", "1.45")
    assert (any_hit_miss.outcome, any_hit_miss.unit_payout) == ("MISS", "0")
    assert all(
        result.principal_refund_added is False
        for result in (
            no_hit,
            no_hit_miss,
            exactly_one,
            zero_is_not_one,
            two_is_not_one,
            any_hit,
            any_hit_miss,
        )
    )


def test_all_five_linked_number_settlements_distinguish_regular_and_special() -> None:
    two_regular = (1, 2, 10, 11, 12, 13, 14)
    regular_special = (1, 10, 11, 12, 13, 14, 2)
    three_regular = (1, 2, 3, 10, 11, 12, 13)

    assert (
        settle_combination(entry=_entry("BO0212"), draw=two_regular, selection=(1, 2)).unit_payout
        == "66.2"
    )
    assert (
        settle_combination(entry=_entry("BO0212"), draw=regular_special, selection=(1, 2)).outcome
        == "MISS"
    )

    two_regular_tier = settle_combination(
        entry=_entry("BO0213"), draw=two_regular, selection=(1, 2)
    )
    regular_special_tier = settle_combination(
        entry=_entry("BO0213"), draw=regular_special, selection=(1, 2)
    )
    assert (two_regular_tier.tier_id, two_regular_tier.unit_payout) == (
        "TWO_REGULAR",
        "51.5",
    )
    assert (regular_special_tier.tier_id, regular_special_tier.unit_payout) == (
        "REGULAR_AND_SPECIAL",
        "35.5",
    )

    assert (
        settle_combination(
            entry=_entry("BO0214"), draw=regular_special, selection=(1, 2)
        ).unit_payout
        == "165"
    )
    assert (
        settle_combination(entry=_entry("BO0214"), draw=two_regular, selection=(1, 2)).outcome
        == "MISS"
    )
    assert (
        settle_combination(
            entry=_entry("BO0215"), draw=three_regular, selection=(1, 2, 3)
        ).unit_payout
        == "766"
    )


def test_generic_pool_expansion_is_canonical_but_complex_generators_are_not_faked() -> None:
    assert expand_number_pool((4, 1, 3, 2), arity=3) == (
        (1, 2, 3),
        (1, 2, 4),
        (1, 3, 4),
        (2, 3, 4),
    )
    linked = compile_combination_semantic(_entry("BO0216"))
    assert linked.upstream_generator_modes == (
        "拖头",
        "生肖对碰",
        "尾数对碰",
        "生尾对碰",
        "任意对碰",
    )
    assert "C(m,3)" in linked.atomic_expansion_rule


def test_semantic_hash_is_stable_under_input_reordering_and_binds_quote() -> None:
    records = compile_combination_semantics(_entries())
    assert combination_records_hash(records) == combination_records_hash(reversed(records))

    changed = {**_entry("BO0433"), "baseline_odds_components": ["1.46"]}
    assert (
        compile_combination_semantic(changed).source_row_hash
        != compile_combination_semantic(_entry("BO0433")).source_row_hash
    )


def test_exact_probability_tiers_match_settlement_predicates() -> None:
    three_in_two = tier_probabilities(compile_combination_semantic(_entry("BO0216")))
    assert three_in_two["THREE_REGULAR"] == Fraction(comb(46, 3), comb(49, 6))
    assert three_in_two["TWO_REGULAR"] == Fraction(3 * comb(46, 4), comb(49, 6))

    two_special = tier_probabilities(compile_combination_semantic(_entry("BO0213")))
    assert two_special["REGULAR_AND_SPECIAL"] == Fraction(1, 196)

    no_hit = tier_probabilities(compile_combination_semantic(_entry("BO0262")))
    exactly_one = tier_probabilities(compile_combination_semantic(_entry("BO0424")))
    any_hit = tier_probabilities(compile_combination_semantic(_entry("BO0433")))
    assert no_hit["NO_HIT"] == Fraction(comb(43, 7), comb(49, 7))
    assert exactly_one["EXACTLY_ONE"] == Fraction(6 * comb(43, 6), comb(49, 7))
    assert any_hit["ANY_HIT"] == 1 - Fraction(comb(44, 7), comb(49, 7))

    for record in compile_combination_semantics(_entries()):
        probabilities = tier_probabilities(record)
        assert sum(probabilities.values(), Fraction(0)) == 1
        assert all(Fraction(0) <= value <= Fraction(1) for value in probabilities.values())
        assert record.probability_formula_ref


@pytest.mark.parametrize(
    ("draw", "selection"),
    [
        ((1, 2, 3, 4, 5, 6), (1, 2, 3)),
        ((1, 2, 3, 4, 5, 6, 6), (1, 2, 3)),
        ((0, 1, 2, 3, 4, 5, 6), (1, 2, 3)),
        ((1, 2, 3, 4, 5, 6, 7), (1, 1, 2)),
        ((1, 2, 3, 4, 5, 6, 7), (1, 2)),
    ],
)
def test_invalid_draw_or_atomic_selection_fails_closed(draw, selection) -> None:
    with pytest.raises((TypeError, ValueError)):
        settle_combination(entry=_entry("BO0216"), draw=draw, selection=selection)


def test_unknown_duplicate_incomplete_and_drifted_catalog_rows_fail_closed() -> None:
    entry = _entry("BO0216")
    with pytest.raises(ValueError, match="unsupported"):
        compile_combination_semantic({**entry, "baseline_id": "BO9999"})
    with pytest.raises(ValueError, match="identity mismatch"):
        compile_combination_semantic({**entry, "play_name": "三中三"})
    with pytest.raises(ValueError, match="duplicate baseline_id"):
        compile_combination_semantics((entry, entry), require_complete=False)
    with pytest.raises(ValueError, match="incomplete"):
        compile_combination_semantics((entry,))


@pytest.mark.skipif(not CATALOG_PATH.is_file(), reason="canonical D-drive catalog is not mounted")
def test_current_d_drive_catalog_matches_the_candidate_row_identity() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    records = compile_combination_catalog(catalog)
    assert tuple(record.baseline_id for record in records) == EXPECTED_BASELINE_IDS
    assert len({record.source_row_hash for record in records}) == 22
    assert len(catalog["content_hash"]) == 64
