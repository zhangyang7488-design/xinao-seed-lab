from __future__ import annotations

import pytest

from xinao.settlement import SPECIAL_NUMBER_FUNCTION, SPECIAL_NUMBER_RULE, settle_special_number


def test_a_and_b_share_hit_logic_but_keep_distinct_price_identity() -> None:
    a = settle_special_number(selected_number=6, actual_special_number=6, panel="A", stake="1")
    b = settle_special_number(selected_number=6, actual_special_number=6, panel="B", stake="1")
    assert a.hit is b.hit is True
    assert a.baseline_ref == SPECIAL_NUMBER_FUNCTION.a_baseline_ref == "BO0001"
    assert b.baseline_ref == SPECIAL_NUMBER_FUNCTION.b_baseline_ref == "BO0013"
    assert a.odds == "47.285"
    assert b.odds == "42.385"
    assert a.gross_return == "47.2850"
    assert b.gross_return == "42.3850"
    assert a.realized_gain == "46.2850"
    assert b.realized_gain == "41.3850"
    assert SPECIAL_NUMBER_RULE.odds_include_principal is True


def test_miss_is_explicit_loss_not_zero_value_ambiguity() -> None:
    result = settle_special_number(selected_number=6, actual_special_number=7, panel="A", stake="1")
    assert result.hit is False
    assert result.status == "SETTLED"
    assert result.gross_return == "0.0000"
    assert result.realized_gain == "0.0000"
    assert result.realized_loss == "1.0000"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"selected_number": 0, "actual_special_number": 1, "panel": "A", "stake": "1"},
        {"selected_number": 1, "actual_special_number": 50, "panel": "A", "stake": "1"},
        {"selected_number": 1, "actual_special_number": 1, "panel": "C", "stake": "1"},
        {"selected_number": 1, "actual_special_number": 1, "panel": "A", "stake": "0"},
        {"selected_number": 1, "actual_special_number": 1, "panel": "A", "stake": 1.0},
    ],
)
def test_invalid_settlement_inputs_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        settle_special_number(**kwargs)  # type: ignore[arg-type]
