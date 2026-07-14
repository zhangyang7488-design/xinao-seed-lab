"""Asia/Shanghai business-week boundaries and immutable ledger projections."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import canonical_sha256

from .accounting import JournalGroup, replay_balances

SHANGHAI = ZoneInfo("Asia/Shanghai")


class WeeklyClosePolicyVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: Literal["weekly-close-policy.v0"] = "weekly-close-policy.v0"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    close_weekday: Literal[0] = 0
    close_hour: Literal[15] = 15


DEFAULT_WEEKLY_CLOSE_POLICY = WeeklyClosePolicyVersion()


class AccountingPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period_ref: str = Field(min_length=1)
    policy_ref: str
    period_start: datetime
    period_end: datetime
    status: Literal["OPEN", "CLOSING", "RECONCILED", "CLOSED", "ADJUSTED"]


class LedgerProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_ref: str
    period_ref: str
    period_start: datetime
    period_end: datetime
    journal_group_refs: tuple[str, ...]
    balances: dict[str, str]
    unresolved_decision_refs: tuple[str, ...]
    conflicted_target_refs: tuple[str, ...]
    status: Literal["RECONCILED", "BLOCKED"]
    projection_hash: str | None = None

    def with_hash(self) -> LedgerProjection:
        basis = self.model_dump(mode="json", exclude={"projection_hash"})
        return self.model_copy(update={"projection_hash": canonical_sha256(basis)})


def weekly_period(
    instant: datetime, policy: WeeklyClosePolicyVersion = DEFAULT_WEEKLY_CLOSE_POLICY
) -> AccountingPeriod:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("period instant must be timezone-aware")
    local = instant.astimezone(SHANGHAI)
    days_since_monday = (local.weekday() - policy.close_weekday) % 7
    start_date = local.date() - timedelta(days=days_since_monday)
    start = datetime.combine(start_date, time(policy.close_hour), tzinfo=SHANGHAI)
    if local < start:
        start -= timedelta(days=7)
    end = start + timedelta(days=7)
    return AccountingPeriod(
        period_ref=f"business-week.{start:%Y%m%dT%H%M%z}.{end:%Y%m%dT%H%M%z}",
        policy_ref=policy.policy_ref,
        period_start=start,
        period_end=end,
        status="OPEN",
    )


def close_weekly_period(
    *,
    period: AccountingPeriod,
    groups: tuple[JournalGroup, ...],
    expected_decision_refs: tuple[str, ...],
    settled_decision_refs: tuple[str, ...],
    conflicted_target_refs: tuple[str, ...],
    close_at: datetime,
    projection_ref: str,
) -> tuple[AccountingPeriod, LedgerProjection]:
    if period.status != "OPEN":
        raise ValueError("only an open period can be closed")
    if close_at.tzinfo is None or close_at.utcoffset() is None:
        raise ValueError("close time must be timezone-aware")
    if close_at < period.period_end:
        raise ValueError("period cannot close before its end")
    out_of_period = tuple(
        group.group_ref
        for group in groups
        if not (period.period_start <= group.occurred_at.astimezone(SHANGHAI) < period.period_end)
    )
    if out_of_period:
        raise ValueError("cross-period journal groups require a PeriodAdjustment")
    unresolved = tuple(sorted(set(expected_decision_refs) - set(settled_decision_refs)))
    balances = replay_balances(groups)
    blocked = bool(unresolved or conflicted_target_refs)
    projection = LedgerProjection(
        projection_ref=projection_ref,
        period_ref=period.period_ref,
        period_start=period.period_start,
        period_end=period.period_end,
        journal_group_refs=tuple(group.group_ref for group in groups),
        balances=balances,
        unresolved_decision_refs=unresolved,
        conflicted_target_refs=tuple(sorted(set(conflicted_target_refs))),
        status="BLOCKED" if blocked else "RECONCILED",
    ).with_hash()
    if blocked:
        raise ValueError("period has missing settlements or outcome conflicts")
    return period.model_copy(update={"status": "CLOSED"}), projection


def validate_journal_admission(
    group: JournalGroup,
    *,
    periods: tuple[AccountingPeriod, ...],
    original_groups: tuple[JournalGroup, ...] = (),
) -> JournalGroup:
    """Reject backdated writes and correction forms that would rewrite a closed period."""
    closed = tuple(period for period in periods if period.status in {"CLOSED", "ADJUSTED"})
    occurred_at = group.occurred_at.astimezone(SHANGHAI)
    if any(period.period_start <= occurred_at < period.period_end for period in closed):
        raise ValueError("journal timestamp belongs to a closed accounting period")

    originals = {item.group_ref: item for item in original_groups}
    original = (
        originals.get(group.reversal_of_group_ref)
        if group.reversal_of_group_ref is not None
        else None
    )
    if group.transaction_type in {"REVERSAL", "PERIOD_ADJUSTMENT"} and original is None:
        raise ValueError("correction requires the original journal group")

    original_period = next(
        (
            period
            for period in closed
            if original is not None
            and period.period_start <= original.occurred_at.astimezone(SHANGHAI) < period.period_end
        ),
        None,
    )
    if group.transaction_type == "REVERSAL" and original_period is not None:
        raise ValueError("closed-period correction must use a PeriodAdjustment")
    if group.transaction_type == "PERIOD_ADJUSTMENT":
        adjusted = next(
            (period for period in closed if period.period_ref == group.adjusts_period_ref), None
        )
        if adjusted is None:
            raise ValueError("period adjustment must reference a closed period")
        if original_period is None or original_period.period_ref != adjusted.period_ref:
            raise ValueError("period adjustment target must belong to the referenced closed period")
        if occurred_at < adjusted.period_end:
            raise ValueError("period adjustment must be posted after the referenced period ends")
    return group
