from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xinao.ledger import (
    Account,
    JournalGroup,
    frozen_position_group,
    opening_group,
    period_adjustment_group,
    replay_balances,
    reversal_group,
    settlement_group,
)
from xinao.settlement import settle_special_number

NOW = datetime(2026, 7, 14, 4, tzinfo=UTC)


def test_open_freeze_hit_replays_to_balanced_expected_balances() -> None:
    opening = opening_group(group_ref="journal.opening", portfolio_ref="shadow.v1", occurred_at=NOW)
    freeze = frozen_position_group(
        group_ref="journal.freeze",
        portfolio_ref="shadow.v1",
        decision_ref="decision.1",
        occurred_at=NOW + timedelta(minutes=1),
        stake="1.0000",
    )
    result = settle_special_number(
        selected_number=1, actual_special_number=1, panel="B", stake="1.0000"
    )
    settlement = settlement_group(
        group_ref="journal.settlement",
        portfolio_ref="shadow.v1",
        settlement_ref="settlement.1",
        occurred_at=NOW + timedelta(minutes=2),
        result=result,
    )

    balances = replay_balances((opening, freeze, settlement))

    assert balances[Account.SHADOW_CASH] == "100041.3850"
    assert balances[Account.OPEN_POSITION_ASSET] == "0.0000"
    assert balances[Account.REALIZED_GAIN_REVENUE] == "-41.3850"
    assert sum(sum(1 for line in group.lines) for group in (opening, freeze, settlement)) == 7


def test_miss_and_reversal_are_append_only_and_replay_to_pre_settlement_state() -> None:
    freeze = frozen_position_group(
        group_ref="journal.freeze",
        portfolio_ref="shadow.v1",
        decision_ref="decision.1",
        occurred_at=NOW,
        stake="1.0000",
    )
    miss = settlement_group(
        group_ref="journal.miss",
        portfolio_ref="shadow.v1",
        settlement_ref="settlement.1",
        occurred_at=NOW + timedelta(minutes=1),
        result=settle_special_number(
            selected_number=1, actual_special_number=2, panel="B", stake="1.0000"
        ),
    )
    reversal = reversal_group(
        group_ref="journal.reverse-miss", original=miss, occurred_at=NOW + timedelta(minutes=2)
    )

    assert replay_balances((freeze, miss, reversal)) == replay_balances((freeze,))
    assert reversal.reversal_of_group_ref == miss.group_ref
    assert reversal.group_hash != miss.group_hash


def test_unbalanced_group_and_duplicate_replay_are_rejected() -> None:
    opening = opening_group(group_ref="journal.opening", portfolio_ref="shadow.v1", occurred_at=NOW)
    with pytest.raises(ValueError, match="not balanced"):
        JournalGroup.model_validate(
            {
                **opening.model_dump(mode="json", exclude={"group_hash"}),
                "lines": [
                    {
                        "line_no": 1,
                        "account": "ShadowCash",
                        "side": "DEBIT",
                        "amount": "1.0000",
                        "currency": "normalized_shadow_unit",
                    },
                    {
                        "line_no": 2,
                        "account": "OpeningCapitalEquity",
                        "side": "CREDIT",
                        "amount": "0.9999",
                        "currency": "normalized_shadow_unit",
                    },
                ],
            }
        )
    with pytest.raises(ValueError, match="duplicate"):
        replay_balances((opening, opening))


def test_closed_period_correction_is_explicit_period_adjustment() -> None:
    original = opening_group(
        group_ref="journal.opening", portfolio_ref="shadow.v1", occurred_at=NOW
    )
    adjustment = period_adjustment_group(
        group_ref="journal.period-adjustment",
        original=original,
        closed_period_ref="business-week.closed",
        occurred_at=NOW + timedelta(days=7),
    )

    assert adjustment.transaction_type == "PERIOD_ADJUSTMENT"
    assert adjustment.adjusts_period_ref == "business-week.closed"
    assert adjustment.reversal_of_group_ref == original.group_ref
