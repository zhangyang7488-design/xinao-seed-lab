from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from xinao.foundation.cost_surface import (
    QuoteVector,
    compile_unit_cost,
    event_payout_cost,
)


def test_quote_vector_preserves_single_and_dual_tiers_as_decimal_values() -> None:
    assert QuoteVector.parse("47.285").components == (Decimal("47.285"),)
    assert QuoteVector.parse("51.5/35.5").components == (
        Decimal("51.5"),
        Decimal("35.5"),
    )


@pytest.mark.parametrize("value", ["", "1/2/3", "NaN", 47.285, True])
def test_quote_vector_rejects_ambiguous_or_binary_float_values(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        QuoteVector.parse(value)


def test_expected_unit_cost_is_exact_sum_probability_times_quote_plus_rebate() -> None:
    summary = compile_unit_cost(
        probabilities=(Fraction(1, 4), Fraction(1, 8)),
        quote=QuoteVector.parse("2.5/3.25"),
        rebate_rate="0.015",
    )
    expected_quote = Fraction(1, 4) * Fraction(5, 2) + Fraction(1, 8) * Fraction(13, 4)
    assert summary.quoted_expected_cost == expected_quote
    assert summary.rebate_rate == Fraction(3, 200)
    assert summary.expected_unit_cost == expected_quote + Fraction(3, 200)
    assert summary.structural_unit_margin == 1 - summary.expected_unit_cost


def test_event_payout_is_quote_on_hit_and_zero_on_miss_without_added_principal() -> None:
    quote = QuoteVector.parse("47.285")
    assert event_payout_cost(quote=quote, hit=True) == Decimal("47.285")
    assert event_payout_cost(quote=quote, hit=False) == Decimal("0")


def test_probability_and_quote_tier_cardinality_must_match() -> None:
    with pytest.raises(ValueError, match="tier"):
        compile_unit_cost(
            probabilities=(Fraction(1, 2),),
            quote=QuoteVector.parse("2/3"),
            rebate_rate="0",
        )
