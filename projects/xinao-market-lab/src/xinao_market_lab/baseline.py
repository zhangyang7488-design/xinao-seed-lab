from __future__ import annotations

from collections import Counter
from decimal import Decimal
from fractions import Fraction
from typing import Any

from scipy.stats import chisquare

from .models import DisplayedOddsQuote, Draw, OddsQuote


def uniform_rtp_baseline(draws: tuple[Draw, ...], quote: OddsQuote) -> dict[str, Any]:
    counts = Counter(draw.special for draw in draws)
    observed = [counts[number] for number in range(1, 50)]
    result = chisquare(observed)
    return {
        "schema_version": 1,
        "draw_count": len(draws),
        "category_count": 49,
        "observed_special_counts": {f"{number:02d}": counts[number] for number in range(1, 50)},
        "expected_count_per_number": len(draws) / 49,
        "pearson_chi_square": float(result.statistic),
        "p_value": float(result.pvalue),
        "uniform_hit_probability": str(Decimal(1) / Decimal(49)),
        "inclusive_return": str(quote.inclusive_return),
        "theoretical_uniform_rtp": str(quote.inclusive_return / Decimal(49)),
        "theoretical_house_edge": str(Decimal(1) - quote.inclusive_return / Decimal(49)),
        "interpretation": (
            "descriptive execution-fixed uniformity/RTP baseline only; not a statistical preregistration; "
            "no correction family, "
            "predictive edge, recommendation, or real-money claim"
        ),
    }


def _fraction_payload(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "fraction": f"{value.numerator}/{value.denominator}",
        "decimal": str(Decimal(value.numerator) / Decimal(value.denominator)),
    }


def regular_set_exact_baseline(draws: tuple[Draw, ...], quote: DisplayedOddsQuote) -> dict[str, Any]:
    inclusion_counts = Counter(number for draw in draws for number in draw.regular_numbers)
    probability = Fraction(6, 49)
    displayed = Fraction(quote.displayed_odds)
    rtp = displayed * probability
    net = rtp - 1
    return {
        "schema_version": 2,
        "draw_count": len(draws),
        "regular_numbers_per_draw": 6,
        "number_pool_size": 49,
        "observed_regular_inclusion_counts": {
            f"{number:02d}": inclusion_counts[number] for number in range(1, 50)
        },
        "uniform_hit_probability": _fraction_payload(probability),
        "displayed_odds": str(quote.displayed_odds),
        "payout_basis_status": quote.payout_basis_status.upper(),
        "payout_assumption_id": "mechanics-assumption-inclusive-return-v1",
        "mechanics_rtp_under_assumption": _fraction_payload(rtp),
        "mechanics_net_expectation_under_assumption": _fraction_payload(net),
        "interpretation": (
            "descriptive mechanics under a spec-pinned regular-set membership rule and an explicit "
            "inclusive-return assumption; operator rule truth, historical availability, ranking, "
            "recommendation, and real-money use remain unverified or prohibited"
        ),
    }
