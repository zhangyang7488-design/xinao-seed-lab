from __future__ import annotations

from datetime import date
from fractions import Fraction
from itertools import islice
from math import comb

import pytest

from xinao.foundation.semantics_linked import (
    DEFAULT_PLAY_CATALOG_PATH,
    TARGET_FAMILY_COUNTS,
    compile_linked_semantics,
    iter_atomic_selections,
    linked_probability_signature,
    linked_ticket_probabilities,
    load_play_catalog,
    parlay_ticket_hit_probability,
    semantic_records_hash,
    settle_linked_ticket,
    settle_parlay_ticket,
)


@pytest.fixture(scope="module")
def compilation():
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    return compile_linked_semantics(load_play_catalog())


def _record(compilation, baseline_id: str):
    return next(
        record
        for record in compilation.rule_semantic_map.records
        if record.baseline_id == baseline_id
    )


def _play_records(compilation, play_id: str):
    return tuple(
        record for record in compilation.rule_semantic_map.records if record.play_id == play_id
    )


def _labels(compilation, play_id: str, *labels: str):
    by_label = {record.component_label: record for record in _play_records(compilation, play_id)}
    return tuple(by_label[label] for label in labels)


def test_catalog_slice_is_exactly_the_required_198_component_rows(compilation) -> None:
    records = compilation.rule_semantic_map.records
    expected = {
        *(f"BO{number:04d}" for number in range(219, 261)),
        *(f"BO{number:04d}" for number in range(267, 423)),
    }
    assert TARGET_FAMILY_COUNTS == {
        "linked-zodiac": 96,
        "linked-tail": 60,
        "parlay": 42,
    }
    assert {record.baseline_id for record in records} == expected
    assert compilation.rule_semantic_map.coverage.mapped_baselines == 198
    assert compilation.rule_semantic_map.coverage.remaining_baselines == 235
    assert compilation.rule_semantic_map.coverage.foundation_complete is False
    assert all(record.content_hash for record in records)


def test_records_keep_page_identity_and_mark_every_non_page_rule_as_convention(
    compilation,
) -> None:
    for record in compilation.rule_semantic_map.records:
        assert record.raw_site_fields["baseline_id"] == record.baseline_id
        assert record.raw_site_fields["baseline_odds_components"] == list(
            record.snapshot_payout_components
        )
        assert record.semantic_evidence_statuses == (
            "EXPLICIT_PAGE",
            "RESEARCH_CONVENTION",
        )
        assert record.assumption_refs
        assert record.predicate_ref
        assert record.settlement_tiers == ("HIT", "MISS")
        assert record.hit_payout_ref == "PAYOUT_EQUALS_Q_INCLUDING_STAKE"
        assert record.miss_payout == "0"
        assert record.principal_refund_on_normal_settlement is False


def test_selection_domain_is_exact_but_remains_lazy(compilation) -> None:
    domain = compilation.expected_selection_domain
    assert domain.baseline_component_count == 198
    assert domain.specification_count == 15
    assert domain.exact_atomic_selection_count == 265_997
    assert domain.materialized_atomic_selection_count == 0
    assert domain.expansion_policy == "LAZY_COMBINATORIAL"

    zodiac = next(spec for spec in domain.specifications if spec.play_id == "play:10:47:none")
    assert zodiac.exact_atomic_selection_count == comb(12, 2) == 66
    expanded_zodiac = iter_atomic_selections(zodiac, compilation.rule_semantic_map.records)
    assert sum(1 for _ in expanded_zodiac) == 66

    parlay = next(spec for spec in domain.specifications if spec.family_id == "parlay")
    assert parlay.exact_atomic_selection_count == 262_101
    first_two = tuple(
        islice(iter_atomic_selections(parlay, compilation.rule_semantic_map.records), 2)
    )
    assert len(first_two) == 2
    assert first_two[0].component_baseline_ids == ("BO0219", "BO0226")
    assert first_two[0].selection_key.endswith("正1-单+正2-单")


def test_linked_zodiac_hit_uses_all_seven_and_minimum_component_quote(compilation) -> None:
    components = _labels(compilation, "play:10:47:none", "马", "兔")
    result = settle_linked_ticket(
        components,
        draw=(1, 2, 3, 5, 6, 7, 4),
        draw_date=date(2026, 7, 1),
    )
    assert result.outcome == "HIT"
    assert result.unit_payout == "4.01"
    assert result.principal_refund_added is False

    missing_rabbit = settle_linked_ticket(
        components,
        draw=(1, 2, 3, 5, 6, 7, 8),
        draw_date="2026-07-01",
    )
    assert missing_rabbit.outcome == "MISS"
    assert missing_rabbit.unit_payout == "0"


def test_linked_miss_side_requires_every_selected_label_to_be_absent(compilation) -> None:
    components = _labels(compilation, "play:10:51:none", "鼠", "龙")
    from xinao.foundation.semantics_sets import zodiac_number_table

    table = zodiac_number_table("2026-07-01").numbers_by_zodiac
    excluded = set(table["鼠"]) | set(table["龙"])
    complement = tuple(number for number in range(1, 50) if number not in excluded)
    hit = settle_linked_ticket(
        components,
        draw=complement[:7],
        draw_date="2026-07-01",
    )
    assert hit.outcome == "HIT"
    contaminated = (table["鼠"][0], *complement[:6])
    miss = settle_linked_ticket(
        components,
        draw=contaminated,
        draw_date="2026-07-01",
    )
    assert miss.outcome == "MISS"


def test_tail_link_zero_tail_is_four_numbers_and_changes_quote_tier(compilation) -> None:
    components = _labels(compilation, "play:11:57:none", "0尾", "1尾", "2尾", "3尾")
    hit = settle_linked_ticket(
        components,
        draw=(10, 1, 2, 4, 5, 6, 3),
        draw_date="2026-07-01",
    )
    assert hit.outcome == "HIT"
    assert hit.unit_payout == "16.1"
    assert len(components[0].catalog_number_set_snapshot) == 4
    assert all(len(record.catalog_number_set_snapshot) == 5 for record in components[1:])


def test_linked_probability_is_exact_seven_ball_combinatorics_not_quote_math(
    compilation,
) -> None:
    hit_components = _labels(compilation, "play:10:47:none", "兔", "牛")
    probabilities = linked_ticket_probabilities(hit_components, draw_date="2026-07-01")
    denominator = comb(49, 7)
    expected = Fraction(
        denominator - 2 * comb(45, 7) + comb(41, 7),
        denominator,
    )
    assert probabilities == {"HIT": expected, "MISS": 1 - expected}

    miss_components = _labels(compilation, "play:10:51:none", "兔", "牛")
    miss_probabilities = linked_ticket_probabilities(
        miss_components,
        draw_date="2026-07-01",
    )
    assert miss_probabilities["HIT"] == Fraction(comb(41, 7), denominator)
    assert sum(miss_probabilities.values()) == 1


def test_zodiac_probability_signature_switches_at_lunar_new_year(compilation) -> None:
    components = _labels(compilation, "play:10:47:none", "马", "兔")
    before = linked_probability_signature(components, draw_date="2026-02-16")
    after = linked_probability_signature(components, draw_date="2026-02-17")
    assert before != after
    assert linked_ticket_probabilities(
        components, draw_date="2026-02-16"
    ) != linked_ticket_probabilities(components, draw_date="2026-02-17")


def test_parlay_quote_is_product_and_any_miss_loses_the_ticket(compilation) -> None:
    odd_even = (_record(compilation, "BO0219"), _record(compilation, "BO0227"))
    hit = settle_parlay_ticket(odd_even, draw=(11, 2, 3, 4, 5, 6, 7))
    assert hit.outcome == "HIT"
    assert hit.unit_payout == "3.690241"
    miss = settle_parlay_ticket(odd_even, draw=(11, 3, 2, 4, 5, 6, 7))
    assert miss.outcome == "MISS"
    assert miss.unit_payout == "0"


def test_parlay_49_property_leg_is_multiplier_one_but_color_49_is_green(
    compilation,
) -> None:
    property_ticket = (
        _record(compilation, "BO0219"),
        _record(compilation, "BO0230"),
        _record(compilation, "BO0234"),
    )
    result = settle_parlay_ticket(property_ticket, draw=(11, 1, 49, 2, 3, 4, 5))
    assert result.outcome == "HIT"
    assert result.void_leg_positions == (3,)
    assert result.unit_payout == "5.369195"

    green_ticket = (_record(compilation, "BO0219"), _record(compilation, "BO0238"))
    green = settle_parlay_ticket(green_ticket, draw=(11, 2, 49, 3, 4, 5, 6))
    assert green.outcome == "HIT"
    assert green.void_leg_positions == ()
    assert green.unit_payout == "5.714975"

    red_ticket = (_record(compilation, "BO0219"), _record(compilation, "BO0237"))
    assert settle_parlay_ticket(red_ticket, draw=(11, 2, 49, 3, 4, 5, 6)).outcome == "MISS"


def test_parlay_probability_is_exact_without_replacement(compilation) -> None:
    two_big = (_record(compilation, "BO0221"), _record(compilation, "BO0228"))
    exact = parlay_ticket_hit_probability(two_big)
    assert exact == Fraction(25 * 24, 49 * 48)
    assert exact != Fraction(25, 49) ** 2


def test_alternate_readings_are_retained_but_not_activated(compilation) -> None:
    interpretations = {item.interpretation_ref: item for item in compilation.interpretations}
    assert interpretations["parlay-sequential-without-replacement-leg-49-one.v1"].status == "ACTIVE"
    assert interpretations["linked-six-regular-only.v1"].status == "ALTERNATE"
    assert interpretations["linked-max-component-quote.v1"].status == "ALTERNATE"
    assert interpretations["parlay-independent-leg-probability.v1"].status == "ALTERNATE"
    assert interpretations["parlay-49-cancels-ticket.v1"].status == "ALTERNATE"


def test_hash_is_invariant_to_catalog_and_record_order() -> None:
    if not DEFAULT_PLAY_CATALOG_PATH.is_file():
        pytest.skip("formal play catalog is not mounted")
    catalog = load_play_catalog()
    first = compile_linked_semantics(catalog)
    reordered = {**catalog, "entries": list(reversed(catalog["entries"]))}
    second = compile_linked_semantics(reordered)
    assert first.content_hash == second.content_hash
    assert semantic_records_hash(first.rule_semantic_map.records) == semantic_records_hash(
        tuple(reversed(first.rule_semantic_map.records))
    )


def test_invalid_draw_ticket_shape_and_missing_catalog_row_fail_closed(compilation) -> None:
    with pytest.raises(ValueError, match="one play_id"):
        settle_linked_ticket(
            (
                _record(compilation, "BO0267"),
                _record(compilation, "BO0373"),
            ),
            draw=(1, 2, 3, 4, 5, 6, 7),
            draw_date="2026-07-01",
        )
    with pytest.raises(ValueError, match="one leg per regular position"):
        settle_parlay_ticket(
            (_record(compilation, "BO0219"), _record(compilation, "BO0220")),
            draw=(1, 2, 3, 4, 5, 6, 7),
        )
    with pytest.raises(ValueError, match="distinct"):
        settle_parlay_ticket(
            (_record(compilation, "BO0219"), _record(compilation, "BO0227")),
            draw=(1, 1, 2, 3, 4, 5, 6),
        )

    catalog = load_play_catalog()
    broken = {
        **catalog,
        "entries": [row for row in catalog["entries"] if row["baseline_id"] != "BO0363"],
    }
    with pytest.raises(ValueError, match="433 rows"):
        compile_linked_semantics(broken)
