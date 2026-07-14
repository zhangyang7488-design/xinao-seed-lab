"""The first deterministic vertical slice: special-number A/B settlement."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import ACCOUNTING_DECIMAL, format_decimal, format_decimal_exact


class SpecialNumberRuleVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_ref: Literal["special-number-settlement.v0"] = "special-number-settlement.v0"
    play_slice: Literal["special-number"] = "special-number"
    valid_numbers_min: Literal[1] = 1
    valid_numbers_max: Literal[49] = 49
    odds_include_principal: Literal[True] = True
    accounting_scale: Literal[4] = 4
    rounding: Literal["ROUND_HALF_UP"] = "ROUND_HALF_UP"
    void_policy: Literal["EXPLICIT_ONLY"] = "EXPLICIT_ONLY"


class SettlementFunctionVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    function_ref: Literal["special-number-settlement.v0"] = "special-number-settlement.v0"
    rule_ref: Literal["special-number-settlement.v0"] = "special-number-settlement.v0"
    algorithm: Literal["selected_number_equals_seventh_open_code"] = (
        "selected_number_equals_seventh_open_code"
    )
    a_baseline_ref: Literal["BO0001"] = "BO0001"
    b_baseline_ref: Literal["BO0013"] = "BO0013"
    a_odds: Literal["47.285"] = "47.285"
    b_odds: Literal["42.385"] = "42.385"


class SettlementResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["SETTLED"] = "SETTLED"
    rule_ref: Literal["special-number-settlement.v0"] = "special-number-settlement.v0"
    panel: Literal["A", "B"]
    baseline_ref: Literal["BO0001", "BO0013"]
    selected_number: int = Field(ge=1, le=49)
    actual_special_number: int = Field(ge=1, le=49)
    hit: bool
    odds: str
    stake: str
    gross_return: str
    realized_gain: str
    realized_loss: str


SPECIAL_NUMBER_RULE = SpecialNumberRuleVersion()
SPECIAL_NUMBER_FUNCTION = SettlementFunctionVersion()


def _positive_stake(value: Decimal | int | str) -> Decimal:
    if isinstance(value, (float, bool)):
        raise TypeError("stake must not use float or bool")
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise ValueError("stake must be a positive finite Decimal")
    return Decimal(format_decimal(decimal_value, ACCOUNTING_DECIMAL))


def settle_special_number(
    *,
    selected_number: int,
    actual_special_number: int,
    panel: Literal["A", "B"],
    stake: Decimal | int | str,
) -> SettlementResult:
    if isinstance(selected_number, bool) or not 1 <= selected_number <= 49:
        raise ValueError("selected_number must be an integer from 1 to 49")
    if isinstance(actual_special_number, bool) or not 1 <= actual_special_number <= 49:
        raise ValueError("actual_special_number must be an integer from 1 to 49")
    if panel == "A":
        baseline_ref = SPECIAL_NUMBER_FUNCTION.a_baseline_ref
        odds = Decimal(SPECIAL_NUMBER_FUNCTION.a_odds)
    elif panel == "B":
        baseline_ref = SPECIAL_NUMBER_FUNCTION.b_baseline_ref
        odds = Decimal(SPECIAL_NUMBER_FUNCTION.b_odds)
    else:
        raise ValueError("panel must be A or B")
    normalized_stake = _positive_stake(stake)
    hit = selected_number == actual_special_number
    zero = format_decimal(Decimal(0), ACCOUNTING_DECIMAL)
    if hit:
        gross = Decimal(format_decimal(normalized_stake * odds, ACCOUNTING_DECIMAL))
        gain = Decimal(format_decimal(gross - normalized_stake, ACCOUNTING_DECIMAL))
        loss = Decimal(0)
    else:
        gross = Decimal(0)
        gain = Decimal(0)
        loss = normalized_stake
    return SettlementResult(
        panel=panel,
        baseline_ref=baseline_ref,
        selected_number=selected_number,
        actual_special_number=actual_special_number,
        hit=hit,
        odds=format_decimal_exact(odds),
        stake=format_decimal(normalized_stake, ACCOUNTING_DECIMAL),
        gross_return=format_decimal(gross, ACCOUNTING_DECIMAL) if hit else zero,
        realized_gain=format_decimal(gain, ACCOUNTING_DECIMAL) if hit else zero,
        realized_loss=format_decimal(loss, ACCOUNTING_DECIMAL) if not hit else zero,
    )
