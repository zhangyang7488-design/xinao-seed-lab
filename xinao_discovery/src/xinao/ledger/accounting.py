"""Strict double-entry shadow ledger with append-only reversal semantics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal

if TYPE_CHECKING:
    from xinao.settlement.special_number import SettlementResult


class Account(StrEnum):
    SHADOW_CASH = "ShadowCash"
    OPEN_POSITION_ASSET = "OpenPositionAsset"
    OPENING_CAPITAL_EQUITY = "OpeningCapitalEquity"
    REALIZED_GAIN_REVENUE = "RealizedGainRevenue"
    REALIZED_LOSS_EXPENSE = "RealizedLossExpense"
    FEE_EXPENSE = "FeeExpense"
    VOID_ADJUSTMENT = "VoidAdjustment"
    ROUNDING_ADJUSTMENT = "RoundingAdjustment"


class JournalLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    line_no: int = Field(ge=1)
    account: Account
    side: Literal["DEBIT", "CREDIT"]
    amount: str
    currency: Literal["normalized_shadow_unit"] = "normalized_shadow_unit"

    @model_validator(mode="after")
    def validate_amount(self) -> JournalLine:
        amount = Decimal(format_decimal(self.amount, ACCOUNTING_DECIMAL))
        if amount <= 0:
            raise ValueError("journal line amount must be positive")
        if self.amount != format_decimal(amount, ACCOUNTING_DECIMAL):
            raise ValueError("journal line amount must use accounting scale")
        return self


class JournalGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    group_ref: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    transaction_type: Literal[
        "OPENING",
        "POSITION_FROZEN",
        "SETTLEMENT_HIT",
        "SETTLEMENT_MISS",
        "FEE",
        "REVERSAL",
        "PERIOD_ADJUSTMENT",
    ]
    occurred_at: datetime
    lines: tuple[JournalLine, ...] = Field(min_length=2)
    source_ref: str = Field(min_length=1)
    reversal_of_group_ref: str | None = None
    adjusts_period_ref: str | None = None
    group_hash: str | None = None

    @model_validator(mode="after")
    def validate_group(self) -> JournalGroup:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("journal timestamp must be timezone-aware")
        if len({line.line_no for line in self.lines}) != len(self.lines):
            raise ValueError("journal line numbers must be unique")
        debit = sum(
            (Decimal(line.amount) for line in self.lines if line.side == "DEBIT"), Decimal(0)
        )
        credit = sum(
            (Decimal(line.amount) for line in self.lines if line.side == "CREDIT"), Decimal(0)
        )
        if debit != credit:
            raise ValueError("journal group is not balanced")
        if self.transaction_type in {"REVERSAL", "PERIOD_ADJUSTMENT"}:
            if not self.reversal_of_group_ref:
                raise ValueError("reversal and period adjustment must reference the original group")
        elif self.reversal_of_group_ref is not None:
            raise ValueError("ordinary journal group cannot carry a reversal reference")
        if self.transaction_type == "PERIOD_ADJUSTMENT" and not self.adjusts_period_ref:
            raise ValueError("period adjustment must reference the closed period")
        return self

    def with_hash(self) -> JournalGroup:
        basis = self.model_dump(mode="json", exclude={"group_hash"})
        return self.model_copy(update={"group_hash": canonical_sha256(basis)})


def _line(line_no: int, account: Account, side: Literal["DEBIT", "CREDIT"], amount: str):
    return JournalLine(
        line_no=line_no,
        account=account,
        side=side,
        amount=format_decimal(amount, ACCOUNTING_DECIMAL),
    )


def opening_group(
    *, group_ref: str, portfolio_ref: str, occurred_at: datetime, amount: str = "100000.0000"
) -> JournalGroup:
    return JournalGroup(
        group_ref=group_ref,
        portfolio_ref=portfolio_ref,
        transaction_type="OPENING",
        occurred_at=occurred_at,
        source_ref=portfolio_ref,
        lines=(
            _line(1, Account.SHADOW_CASH, "DEBIT", amount),
            _line(2, Account.OPENING_CAPITAL_EQUITY, "CREDIT", amount),
        ),
    ).with_hash()


def frozen_position_group(
    *, group_ref: str, portfolio_ref: str, decision_ref: str, occurred_at: datetime, stake: str
) -> JournalGroup:
    return JournalGroup(
        group_ref=group_ref,
        portfolio_ref=portfolio_ref,
        transaction_type="POSITION_FROZEN",
        occurred_at=occurred_at,
        source_ref=decision_ref,
        lines=(
            _line(1, Account.OPEN_POSITION_ASSET, "DEBIT", stake),
            _line(2, Account.SHADOW_CASH, "CREDIT", stake),
        ),
    ).with_hash()


def settlement_group(
    *,
    group_ref: str,
    portfolio_ref: str,
    settlement_ref: str,
    occurred_at: datetime,
    result: SettlementResult,
) -> JournalGroup:
    if result.hit:
        lines = (
            _line(1, Account.SHADOW_CASH, "DEBIT", result.gross_return),
            _line(2, Account.OPEN_POSITION_ASSET, "CREDIT", result.stake),
            _line(3, Account.REALIZED_GAIN_REVENUE, "CREDIT", result.realized_gain),
        )
        transaction_type: Literal["SETTLEMENT_HIT", "SETTLEMENT_MISS"] = "SETTLEMENT_HIT"
    else:
        lines = (
            _line(1, Account.REALIZED_LOSS_EXPENSE, "DEBIT", result.realized_loss),
            _line(2, Account.OPEN_POSITION_ASSET, "CREDIT", result.stake),
        )
        transaction_type = "SETTLEMENT_MISS"
    return JournalGroup(
        group_ref=group_ref,
        portfolio_ref=portfolio_ref,
        transaction_type=transaction_type,
        occurred_at=occurred_at,
        source_ref=settlement_ref,
        lines=lines,
    ).with_hash()


def reversal_group(
    *, group_ref: str, original: JournalGroup, occurred_at: datetime
) -> JournalGroup:
    lines = tuple(
        JournalLine(
            line_no=line.line_no,
            account=line.account,
            side="CREDIT" if line.side == "DEBIT" else "DEBIT",
            amount=line.amount,
            currency=line.currency,
        )
        for line in original.lines
    )
    return JournalGroup(
        group_ref=group_ref,
        portfolio_ref=original.portfolio_ref,
        transaction_type="REVERSAL",
        occurred_at=occurred_at,
        source_ref=original.source_ref,
        reversal_of_group_ref=original.group_ref,
        lines=lines,
    ).with_hash()


def period_adjustment_group(
    *,
    group_ref: str,
    original: JournalGroup,
    closed_period_ref: str,
    occurred_at: datetime,
) -> JournalGroup:
    reversal = reversal_group(group_ref=group_ref, original=original, occurred_at=occurred_at)
    return reversal.model_copy(
        update={
            "transaction_type": "PERIOD_ADJUSTMENT",
            "adjusts_period_ref": closed_period_ref,
            "group_hash": None,
        }
    ).with_hash()


def replay_balances(groups: tuple[JournalGroup, ...]) -> dict[str, str]:
    seen: set[str] = set()
    balances = {account.value: Decimal("0.0000") for account in Account}
    for group in groups:
        if group.group_ref in seen:
            raise ValueError("duplicate journal group in replay")
        seen.add(group.group_ref)
        if group.group_hash is None or group.with_hash().group_hash != group.group_hash:
            raise ValueError("journal group hash mismatch")
        for line in group.lines:
            direction = Decimal(1) if line.side == "DEBIT" else Decimal(-1)
            balances[line.account.value] += direction * Decimal(line.amount)
    if sum(balances.values(), Decimal(0)) != 0:
        raise AssertionError("double-entry replay is not balanced")
    return {
        account: format_decimal(amount, ACCOUNTING_DECIMAL)
        for account, amount in sorted(balances.items())
    }
