from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from xinao.foundation.cost_surface import QuoteVector, compile_unit_cost
from xinao.foundation.rebate import (
    ONE_ZODIAC_ORAL_ANCHOR,
    SPECIAL_NUMBER_ORAL_ANCHOR,
    THREE_IN_THREE_ORAL_ANCHOR,
    ScopeQuote,
    decode_water_label,
    resolve_rebate_scope,
)


def test_water_labels_decode_to_valid_turnover_rates() -> None:
    assert decode_water_label("3.5水") == Fraction(7, 200)
    assert decode_water_label("1水") == Fraction(1, 100)
    assert decode_water_label("15.5水") == Fraction(31, 200)


def test_special_number_oral_anchor_reaches_the_explicit_unit_cost_assumption() -> None:
    quoted = compile_unit_cost(
        probabilities=(Fraction(1, 49),),
        quote=QuoteVector.parse("47.285"),
        rebate_rate="0",
    )
    resolution = resolve_rebate_scope(
        scope_ref="special-number-A",
        quotes=(ScopeQuote("BO0001", quoted.quoted_expected_cost),),
        candidate_rate=decode_water_label("3.5水"),
    )
    final = compile_unit_cost(
        probabilities=(Fraction(1, 49),),
        quote=QuoteVector.parse("47.285"),
        rebate_rate=resolution.resolved_rate,
    )
    assert resolution.resolved_rate == Fraction(7, 200)
    assert final.expected_unit_cost == 1
    assert final.structural_unit_margin == 0


def test_one_zodiac_unified_scope_caps_the_oral_one_water_candidate() -> None:
    four_code = compile_unit_cost(
        probabilities=(Fraction(7139, 15134),),
        quote=QuoteVector.parse("2.103"),
        rebate_rate="0",
    )
    five_code = compile_unit_cost(
        probabilities=(Fraction(12574, 22701),),
        quote=QuoteVector.parse("1.779"),
        rebate_rate="0",
    )
    resolution = resolve_rebate_scope(
        scope_ref="one-zodiac-unified",
        quotes=(
            ScopeQuote("four-code", four_code.quoted_expected_cost),
            ScopeQuote("five-code", five_code.quoted_expected_cost),
        ),
        candidate_rate=decode_water_label("1水"),
    )
    expected_cap = min(
        1 - four_code.quoted_expected_cost,
        1 - five_code.quoted_expected_cost,
    )
    assert resolution.feasible is True
    assert resolution.scope_ceiling == expected_cap
    assert resolution.resolved_rate == expected_cap
    assert resolution.resolved_rate < Fraction(1, 100)
    assert resolution.rate_decimal() == Decimal("0.0079742963")


def test_three_in_three_oral_anchor_remains_below_one_at_760_plus_15_5_water() -> None:
    summary = compile_unit_cost(
        probabilities=(Fraction(5, 4606),),
        quote=QuoteVector.parse("760"),
        rebate_rate=decode_water_label("15.5水"),
    )
    assert summary.expected_unit_cost_decimal() == Decimal("0.980010855406")
    assert summary.structural_unit_margin_decimal() == Decimal("0.019989144594")


def test_negative_implied_ceiling_never_becomes_a_negative_turnover_rebate() -> None:
    resolution = resolve_rebate_scope(
        scope_ref="anomalous",
        quotes=(ScopeQuote("overfull", Fraction(101, 100)),),
        candidate_rate=None,
    )
    assert resolution.feasible is False
    assert resolution.scope_ceiling == Fraction(-1, 100)
    assert resolution.resolved_rate == 0


def test_all_three_anchor_constants_are_explicit_assumptions_not_verification_claims() -> None:
    anchors = (
        SPECIAL_NUMBER_ORAL_ANCHOR,
        ONE_ZODIAC_ORAL_ANCHOR,
        THREE_IN_THREE_ORAL_ANCHOR,
    )
    assert {anchor.anchor_ref for anchor in anchors} == {
        "oral-anchor.special-number.2026-07-14",
        "oral-anchor.one-zodiac.2026-07-14",
        "oral-anchor.three-in-three.2026-07-14",
    }
    assert all(anchor.evidence_class == "USER_ORAL_ASSUMPTION" for anchor in anchors)
    assert all(anchor.assumptions for anchor in anchors)
