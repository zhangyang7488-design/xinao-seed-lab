"""Domain decimal profiles used before values enter JCS.

RFC 8785 canonicalizes JSON numbers using the ECMAScript/IEEE-754 model. Xinao
therefore carries high precision domain decimals as canonical JSON strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class DecimalProfile:
    """A fixed-scale decimal string contract."""

    name: str
    scale: int
    rounding: str
    max_precision: int = 38

    def __post_init__(self) -> None:
        if self.scale < 0:
            raise ValueError("decimal scale must be non-negative")
        if self.max_precision < self.scale + 1:
            raise ValueError("max_precision must exceed scale")


PROBABILITY_DECIMAL = DecimalProfile(
    name="probability-12-half-even",
    scale=12,
    rounding=ROUND_HALF_EVEN,
)
ACCOUNTING_DECIMAL = DecimalProfile(
    name="accounting-4-half-up",
    scale=4,
    rounding=ROUND_HALF_UP,
)


def _coerce_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("boolean is not a domain decimal")
    if isinstance(value, float):
        raise TypeError("float is not accepted for domain decimals")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid domain decimal") from exc
    if not result.is_finite():
        raise ValueError("NaN and Infinity are not valid domain decimals")
    return result


def format_decimal(value: Decimal | int | str, profile: DecimalProfile) -> str:
    """Quantize *value* and return its fixed-scale non-scientific string."""

    decimal_value = _coerce_decimal(value)
    quantum = Decimal(1).scaleb(-profile.scale)
    try:
        quantized = decimal_value.quantize(quantum, rounding=profile.rounding)
    except InvalidOperation as exc:
        raise ValueError("decimal exceeds the selected profile") from exc
    if quantized.is_zero():
        quantized = abs(quantized)
    digits = len(quantized.as_tuple().digits)
    if digits > profile.max_precision:
        raise ValueError("decimal exceeds maximum precision")
    return format(quantized, f".{profile.scale}f")


def format_decimal_exact(value: Decimal | int | str) -> str:
    """Return a value-preserving canonical decimal string without exponent notation."""

    decimal_value = _coerce_decimal(value)
    if decimal_value.is_zero():
        return "0"
    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered
