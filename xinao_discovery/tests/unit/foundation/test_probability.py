from __future__ import annotations

from fractions import Fraction

import pytest

from xinao.foundation.probability import (
    ORDERED_DRAW_OUTCOME_COUNT,
    all_selected_in_regular_probability,
    at_least_one_in_seven_probability,
    exact_hits_probability,
    fixed_position_in_set_probability,
    special_in_set_probability,
    special_regular_hits_probability,
)


def test_fixed_position_and_special_number_use_the_exact_49_number_universe() -> None:
    assert ORDERED_DRAW_OUTCOME_COUNT == 432_938_943_360
    assert fixed_position_in_set_probability(1) == Fraction(1, 49)
    assert special_in_set_probability(17) == Fraction(17, 49)


def test_special_and_regular_hit_cells_partition_the_full_ordered_draw_universe() -> None:
    cells = (
        special_regular_hits_probability(
            marked_count=5,
            special_hit=special_hit,
            regular_hits=regular_hits,
        )
        for special_hit in (False, True)
        for regular_hits in range(7)
    )
    assert sum(cells, start=Fraction(0)) == Fraction(1)


def test_hypergeometric_primitives_reproduce_the_three_anchor_probabilities() -> None:
    assert at_least_one_in_seven_probability(4) == Fraction(7139, 15134)
    assert at_least_one_in_seven_probability(5) == Fraction(12574, 22701)
    assert all_selected_in_regular_probability(3) == Fraction(5, 4606)
    assert exact_hits_probability(marked_count=4, draw_count=7, hits=0) == Fraction(7995, 15134)


@pytest.mark.parametrize(
    ("function", "argument"),
    [
        (special_in_set_probability, -1),
        (fixed_position_in_set_probability, 50),
        (at_least_one_in_seven_probability, True),
        (all_selected_in_regular_probability, 7),
    ],
)
def test_invalid_probability_inputs_fail_closed(function, argument) -> None:
    with pytest.raises((TypeError, ValueError)):
        function(argument)
