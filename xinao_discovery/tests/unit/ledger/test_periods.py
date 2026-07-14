from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xinao.ledger import (
    close_weekly_period,
    opening_group,
    period_adjustment_group,
    reversal_group,
    validate_journal_admission,
    weekly_period,
)


def test_weekly_period_is_monday_1500_shanghai_half_open() -> None:
    before = weekly_period(datetime(2026, 7, 13, 6, 59, tzinfo=UTC))
    boundary = weekly_period(datetime(2026, 7, 13, 7, 0, tzinfo=UTC))

    assert before.period_start.isoformat() == "2026-07-06T15:00:00+08:00"
    assert before.period_end.isoformat() == "2026-07-13T15:00:00+08:00"
    assert boundary.period_start == before.period_end


def test_close_replays_and_blocks_missing_conflict_or_cross_period() -> None:
    period = weekly_period(datetime(2026, 7, 14, 4, tzinfo=UTC))
    opening = opening_group(
        group_ref="journal.opening",
        portfolio_ref="shadow.v1",
        occurred_at=period.period_start + timedelta(minutes=1),
    )
    closed, projection = close_weekly_period(
        period=period,
        groups=(opening,),
        expected_decision_refs=("decision.1",),
        settled_decision_refs=("decision.1",),
        conflicted_target_refs=(),
        close_at=period.period_end,
        projection_ref="ledger-projection.week1",
    )

    assert closed.status == "CLOSED"
    assert projection.status == "RECONCILED"
    assert projection.projection_hash is not None

    with pytest.raises(ValueError, match="missing"):
        close_weekly_period(
            period=period,
            groups=(opening,),
            expected_decision_refs=("decision.1",),
            settled_decision_refs=(),
            conflicted_target_refs=(),
            close_at=period.period_end,
            projection_ref="ledger-projection.blocked",
        )
    with pytest.raises(ValueError, match="cross-period"):
        close_weekly_period(
            period=period,
            groups=(
                opening_group(
                    group_ref="journal.next",
                    portfolio_ref="shadow.v1",
                    occurred_at=period.period_end,
                ),
            ),
            expected_decision_refs=(),
            settled_decision_refs=(),
            conflicted_target_refs=(),
            close_at=period.period_end,
            projection_ref="ledger-projection.cross-period",
        )


def test_closed_period_rejects_backdating_and_requires_period_adjustment() -> None:
    period = weekly_period(datetime(2026, 7, 14, 4, tzinfo=UTC))
    original = opening_group(
        group_ref="journal.closed",
        portfolio_ref="shadow.v1",
        occurred_at=period.period_start + timedelta(minutes=1),
    )
    closed = period.model_copy(update={"status": "CLOSED"})
    backdated = opening_group(
        group_ref="journal.backdated",
        portfolio_ref="shadow.v1",
        occurred_at=period.period_end - timedelta(seconds=1),
    )
    reversal = reversal_group(
        group_ref="journal.reversal",
        original=original,
        occurred_at=period.period_end + timedelta(minutes=1),
    )
    adjustment = period_adjustment_group(
        group_ref="journal.adjustment",
        original=original,
        closed_period_ref=period.period_ref,
        occurred_at=period.period_end + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="timestamp belongs"):
        validate_journal_admission(backdated, periods=(closed,))
    with pytest.raises(ValueError, match="must use a PeriodAdjustment"):
        validate_journal_admission(reversal, periods=(closed,), original_groups=(original,))
    assert (
        validate_journal_admission(adjustment, periods=(closed,), original_groups=(original,))
        == adjustment
    )
