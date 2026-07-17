"""Exact probability primitives for the 49-number, six-regular-plus-special draw.

The functions in this module describe the mathematical draw universe only.  They
do not infer a play rule from a label and they do not use historical frequencies
as probability definitions.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb, factorial, perm

NUMBER_COUNT = 49
REGULAR_NUMBER_COUNT = 6
DRAW_NUMBER_COUNT = 7
ORDERED_DRAW_OUTCOME_COUNT = perm(NUMBER_COUNT, DRAW_NUMBER_COUNT)


def _integer(
    name: str,
    value: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _comb_or_zero(total: int, selected: int) -> int:
    if selected < 0 or selected > total:
        return 0
    return comb(total, selected)


def fixed_position_in_set_probability(marked_count: int) -> Fraction:
    """Probability that one named draw position belongs to a marked number set."""

    marked = _integer("marked_count", marked_count, minimum=0, maximum=NUMBER_COUNT)
    return Fraction(marked, NUMBER_COUNT)


def special_in_set_probability(marked_count: int) -> Fraction:
    """Probability that the seventh, special number belongs to a marked set."""

    return fixed_position_in_set_probability(marked_count)


def exact_hits_probability(
    *,
    marked_count: int,
    draw_count: int,
    hits: int,
    population_size: int = NUMBER_COUNT,
) -> Fraction:
    """Hypergeometric probability for an unordered without-replacement draw."""

    population = _integer(
        "population_size",
        population_size,
        minimum=1,
        maximum=NUMBER_COUNT,
    )
    marked = _integer("marked_count", marked_count, minimum=0, maximum=population)
    drawn = _integer("draw_count", draw_count, minimum=0, maximum=population)
    hit_count = _integer("hits", hits, minimum=0, maximum=drawn)
    numerator = _comb_or_zero(marked, hit_count) * _comb_or_zero(
        population - marked,
        drawn - hit_count,
    )
    return Fraction(numerator, comb(population, drawn))


def at_least_one_in_seven_probability(marked_count: int) -> Fraction:
    """Probability that the full seven-number draw intersects a marked set."""

    marked = _integer("marked_count", marked_count, minimum=0, maximum=NUMBER_COUNT)
    return 1 - exact_hits_probability(
        marked_count=marked,
        draw_count=DRAW_NUMBER_COUNT,
        hits=0,
    )


def all_selected_in_regular_probability(selection_count: int) -> Fraction:
    """Probability that all selected numbers occur among the six regular numbers."""

    selected = _integer(
        "selection_count",
        selection_count,
        minimum=0,
        maximum=REGULAR_NUMBER_COUNT,
    )
    return Fraction(comb(REGULAR_NUMBER_COUNT, selected), comb(NUMBER_COUNT, selected))


def special_regular_hits_probability(
    *,
    marked_count: int,
    special_hit: bool,
    regular_hits: int,
) -> Fraction:
    """Count one special-membership state and an exact regular-hit count.

    The numerator is expressed in the canonical ordered universe.  The special
    position is selected first, and the six regular values are then ordered.
    Summing every feasible ``special_hit``/``regular_hits`` cell is exactly one.
    """

    marked = _integer("marked_count", marked_count, minimum=0, maximum=NUMBER_COUNT)
    if not isinstance(special_hit, bool):
        raise TypeError("special_hit must be bool")
    hit_count = _integer(
        "regular_hits",
        regular_hits,
        minimum=0,
        maximum=REGULAR_NUMBER_COUNT,
    )

    if special_hit:
        special_choices = marked
        remaining_marked = marked - 1
        remaining_unmarked = NUMBER_COUNT - marked
    else:
        special_choices = NUMBER_COUNT - marked
        remaining_marked = marked
        remaining_unmarked = NUMBER_COUNT - marked - 1

    if special_choices == 0:
        return Fraction(0)
    unordered_regular_choices = _comb_or_zero(
        remaining_marked,
        hit_count,
    ) * _comb_or_zero(
        remaining_unmarked,
        REGULAR_NUMBER_COUNT - hit_count,
    )
    ordered_event_count = (
        special_choices * unordered_regular_choices * factorial(REGULAR_NUMBER_COUNT)
    )
    return Fraction(ordered_event_count, ORDERED_DRAW_OUTCOME_COUNT)
