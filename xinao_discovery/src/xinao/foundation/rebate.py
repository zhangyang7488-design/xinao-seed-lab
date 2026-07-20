"""Deterministic valid-turnover rebate decoding and scope-level capping."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

from .cost_surface import DecimalInput, fraction_decimal


def _candidate_fraction(value: DecimalInput | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        result = value
    else:
        if isinstance(value, (bool, float)):
            raise TypeError("rebate candidate must not use binary float or bool")
        try:
            decimal_value = value if isinstance(value, Decimal) else Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("invalid rebate candidate") from exc
        if not decimal_value.is_finite():
            raise ValueError("rebate candidate must be finite")
        result = Fraction(decimal_value)
    if result < 0:
        raise ValueError("rebate candidate must be non-negative")
    return result


def decode_water_label(label: str) -> Fraction:
    """Decode the local oral convention where one water point is one percent."""

    if not isinstance(label, str):
        raise TypeError("water label must be text")
    normalized = label.strip()
    if not normalized.endswith("水"):
        raise ValueError("water label must end with 水")
    number = normalized[:-1].strip()
    if not number:
        raise ValueError("water label has no numeric value")
    return _candidate_fraction(number) / 100


@dataclass(frozen=True, slots=True)
class ScopeQuote:
    quote_ref: str
    quoted_expected_cost: Fraction

    def __post_init__(self) -> None:
        if not self.quote_ref:
            raise ValueError("quote_ref must be non-empty")
        if not isinstance(self.quoted_expected_cost, Fraction):
            raise TypeError("quoted_expected_cost must be Fraction")


@dataclass(frozen=True, slots=True)
class RebateScopeResolution:
    scope_ref: str
    quote_refs: tuple[str, ...]
    candidate_rate: Fraction | None
    scope_ceiling: Fraction
    resolved_rate: Fraction
    feasible: bool

    def rate_decimal(self, *, scale: int = 10) -> Decimal:
        return fraction_decimal(self.resolved_rate, scale=scale)

    def ceiling_decimal(self, *, scale: int = 10) -> Decimal:
        return fraction_decimal(self.scope_ceiling, scale=scale)


def resolve_rebate_scope(
    *,
    scope_ref: str,
    quotes: tuple[ScopeQuote, ...],
    candidate_rate: DecimalInput | Fraction | None,
) -> RebateScopeResolution:
    """Apply one safe rebate ceiling across every independently selectable quote."""

    if not scope_ref:
        raise ValueError("scope_ref must be non-empty")
    if not quotes:
        raise ValueError("rebate scope must contain at least one quote")
    quote_refs = tuple(quote.quote_ref for quote in quotes)
    if len(set(quote_refs)) != len(quote_refs):
        raise ValueError("quote_ref values must be unique inside a rebate scope")

    scope_ceiling = min(1 - quote.quoted_expected_cost for quote in quotes)
    candidate = None if candidate_rate is None else _candidate_fraction(candidate_rate)
    if scope_ceiling < 0:
        resolved = Fraction(0)
        feasible = False
    else:
        resolved = scope_ceiling if candidate is None else min(candidate, scope_ceiling)
        feasible = True
    return RebateScopeResolution(
        scope_ref=scope_ref,
        quote_refs=quote_refs,
        candidate_rate=candidate,
        scope_ceiling=scope_ceiling,
        resolved_rate=resolved,
        feasible=feasible,
    )


@dataclass(frozen=True, slots=True)
class OralAnchorAssumption:
    anchor_ref: str
    oral_label: str
    evidence_class: Literal["USER_ORAL_ASSUMPTION"]
    assumptions: tuple[str, ...]


SPECIAL_NUMBER_ORAL_ANCHOR = OralAnchorAssumption(
    anchor_ref="oral-anchor.special-number.2026-07-14",
    oral_label="特码 47.285 + 3.5水",
    evidence_class="USER_ORAL_ASSUMPTION",
    assumptions=(
        "the special number is uniformly one of 49 numbers",
        "47.285 is the complete hit payout including principal",
        "3.5水 means a 0.035 valid-turnover rebate rate",
    ),
)

ONE_ZODIAC_ORAL_ANCHOR = OralAnchorAssumption(
    anchor_ref="oral-anchor.one-zodiac.2026-07-14",
    oral_label="一肖 2.1 + 1水",
    evidence_class="USER_ORAL_ASSUMPTION",
    assumptions=(
        "one-zodiac means at least one matching number among all seven drawn numbers",
        "four-code and five-code zodiac options retain separate exact probabilities",
        "one shared rebate scope uses the minimum safe ceiling across selectable options",
    ),
)

THREE_IN_THREE_ORAL_ANCHOR = OralAnchorAssumption(
    anchor_ref="oral-anchor.three-in-three.2026-07-14",
    oral_label="三中三 760 + 15.5水",
    evidence_class="USER_ORAL_ASSUMPTION",
    assumptions=(
        "three distinct selected numbers must all occur among the six regular numbers",
        "760 is the complete oral hit payout including principal",
        "15.5水 means a 0.155 valid-turnover rebate rate",
    ),
)
