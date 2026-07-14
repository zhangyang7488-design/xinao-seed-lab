from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from xinao.settlement import settle_special_number


@given(
    selected=st.integers(min_value=1, max_value=49),
    actual=st.integers(min_value=1, max_value=49),
    stake=st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("1000"), places=4),
)
@settings(max_examples=200)
def test_hit_logic_is_panel_independent_and_values_are_four_decimal_strings(
    selected: int, actual: int, stake: Decimal
) -> None:
    a = settle_special_number(
        selected_number=selected, actual_special_number=actual, panel="A", stake=stake
    )
    b = settle_special_number(
        selected_number=selected, actual_special_number=actual, panel="B", stake=stake
    )
    assert a.hit == b.hit == (selected == actual)
    for result in (a, b):
        assert all(
            len(value.rpartition(".")[2]) == 4
            for value in (
                result.stake,
                result.gross_return,
                result.realized_gain,
                result.realized_loss,
            )
        )
    if a.hit:
        assert Decimal(a.gross_return) > Decimal(b.gross_return)
    else:
        assert a.realized_loss == b.realized_loss
