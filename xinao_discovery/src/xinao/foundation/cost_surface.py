"""Pure unit-cost calculations over exact probabilities and decimal quotes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from fractions import Fraction

type DecimalInput = Decimal | int | str
DERIVED_SCALE = 12


def _decimal(value: DecimalInput) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError("binary float and bool are not valid decimal inputs")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal input") from exc
    if not result.is_finite():
        raise ValueError("decimal input must be finite")
    if result.is_zero():
        result = abs(result)
    return result


def _rate_fraction(value: DecimalInput | Fraction) -> Fraction:
    result = value if isinstance(value, Fraction) else Fraction(_decimal(value))
    if result < 0:
        raise ValueError("turnover rebate rate must be non-negative")
    return result


def fraction_decimal(value: Fraction, *, scale: int = DERIVED_SCALE) -> Decimal:
    """Render an exact fraction with one explicit half-even decimal profile."""

    if isinstance(scale, bool) or not isinstance(scale, int):
        raise TypeError("scale must be an integer")
    if scale < 0:
        raise ValueError("scale must be non-negative")
    quantum = Decimal(1).scaleb(-scale)
    with localcontext() as context:
        context.prec = max(50, scale + 20)
        rendered = Decimal(value.numerator) / Decimal(value.denominator)
        return rendered.quantize(quantum, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class QuoteVector:
    """One current single-tier or dual-tier quote without lossy float parsing."""

    components: tuple[Decimal, ...]

    def __post_init__(self) -> None:
        if len(self.components) not in {1, 2}:
            raise ValueError("quote vector must contain one or two tiers")
        normalized = tuple(_decimal(component) for component in self.components)
        if any(component <= 0 for component in normalized):
            raise ValueError("quote components must be positive")
        object.__setattr__(self, "components", normalized)

    @classmethod
    def parse(cls, value: str | tuple[DecimalInput, ...]) -> QuoteVector:
        if isinstance(value, (bool, float)):
            raise TypeError("quote must be decimal text or decimal components")
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("quote text is empty")
            parts: tuple[DecimalInput, ...] = tuple(part.strip() for part in value.split("/"))
        elif isinstance(value, tuple):
            parts = value
        else:
            raise TypeError("quote must be decimal text or a tuple")
        return cls(tuple(_decimal(part) for part in parts))


@dataclass(frozen=True, slots=True)
class UnitCostSummary:
    quoted_expected_cost: Fraction
    rebate_rate: Fraction
    expected_unit_cost: Fraction
    structural_unit_margin: Fraction

    def quoted_expected_cost_decimal(self, *, scale: int = DERIVED_SCALE) -> Decimal:
        return fraction_decimal(self.quoted_expected_cost, scale=scale)

    def rebate_rate_decimal(self, *, scale: int = DERIVED_SCALE) -> Decimal:
        return fraction_decimal(self.rebate_rate, scale=scale)

    def expected_unit_cost_decimal(self, *, scale: int = DERIVED_SCALE) -> Decimal:
        return fraction_decimal(self.expected_unit_cost, scale=scale)

    def structural_unit_margin_decimal(self, *, scale: int = DERIVED_SCALE) -> Decimal:
        return fraction_decimal(self.structural_unit_margin, scale=scale)


def compile_unit_cost(
    *,
    probabilities: tuple[Fraction, ...],
    quote: QuoteVector,
    rebate_rate: DecimalInput | Fraction,
) -> UnitCostSummary:
    """Compute ``sum(p*q)+r`` without rounding intermediate values.

    ``probabilities`` contains the paying tier probabilities.  A miss tier pays
    zero and therefore need not be repeated in this sparse quote vector.
    """

    if len(probabilities) != len(quote.components):
        raise ValueError("probability and quote tier cardinality must match")
    if not probabilities:
        raise ValueError("at least one paying tier is required")
    if any(not isinstance(probability, Fraction) for probability in probabilities):
        raise TypeError("probabilities must be Fraction values")
    if any(probability < 0 or probability > 1 for probability in probabilities):
        raise ValueError("tier probabilities must be between zero and one")
    if sum(probabilities, start=Fraction(0)) > 1:
        raise ValueError("paying tier probabilities cannot sum above one")

    quoted_expected_cost = sum(
        (
            probability * Fraction(component)
            for probability, component in zip(probabilities, quote.components, strict=True)
        ),
        start=Fraction(0),
    )
    rebate = _rate_fraction(rebate_rate)
    expected_unit_cost = quoted_expected_cost + rebate
    return UnitCostSummary(
        quoted_expected_cost=quoted_expected_cost,
        rebate_rate=rebate,
        expected_unit_cost=expected_unit_cost,
        structural_unit_margin=1 - expected_unit_cost,
    )


def event_payout_cost(
    *,
    quote: QuoteVector,
    hit: bool,
    payout_index: int = 0,
) -> Decimal:
    """Return the displayed quote on hit and zero on miss.

    The quote is already the complete normal-settlement payout.  No additional
    principal is added by this function.
    """

    if not isinstance(hit, bool):
        raise TypeError("hit must be bool")
    if isinstance(payout_index, bool) or not isinstance(payout_index, int):
        raise TypeError("payout_index must be an integer")
    if not 0 <= payout_index < len(quote.components):
        raise ValueError("payout_index is outside the quote vector")
    return quote.components[payout_index] if hit else Decimal(0)
