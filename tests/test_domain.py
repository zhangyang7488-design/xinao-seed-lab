from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

from xinao_market_lab.domain import (
    build_rule,
    build_trial_records,
    decide,
    default_candidates,
    ledger_bytes,
    settle,
)
from xinao_market_lab.models import CandidateSpec, CostModel, Decision, Draw, OddsQuote


def make_draw(expect: str, numbers: tuple[int, int, int, int, int, int, int]) -> Draw:
    return Draw(
        series_id="macaujc2_daily_2132_type8",
        source_expect=expect,
        open_time=datetime(2026, 1, 1, 21, 32, 32, tzinfo=ZoneInfo("Asia/Shanghai")),
        regular_numbers=numbers[:6],
        special=numbers[6],
        wave=("red", "blue", "green", "red", "blue", "green", "red"),
        zodiac=("鼠", "牛", "虎", "兔", "龍", "蛇", "馬"),
        source_verified=False,
    )


def quote() -> OddsQuote:
    return OddsQuote(
        quote_id="quote-test",
        observed_at=datetime(2026, 5, 12, tzinfo=ZoneInfo("UTC")),
        page_key="page",
        source_file="source.json",
        inclusive_return=Decimal("47.285"),
    )


def test_inclusive_return_settlement_and_no_bet() -> None:
    draw = make_draw("2026001", (1, 2, 3, 4, 5, 6, 7))
    cost = CostModel()
    won = settle(
        Decision(place_bet=True, selection=7, information_cutoff_expect="2026000"), draw, quote(), cost
    )
    lost = settle(
        Decision(place_bet=True, selection=8, information_cutoff_expect="2026000"), draw, quote(), cost
    )
    skipped = settle(
        Decision(place_bet=False, selection=None, information_cutoff_expect=None), draw, quote(), cost
    )
    assert won.outcome == "win"
    assert won.gross_return == Decimal("47.285")
    assert won.net_return == Decimal("46.285")
    assert lost.net_return == Decimal("-1")
    assert skipped.net_return == Decimal("0")
    assert skipped.stake == Decimal("0")


def test_candidates_only_use_past_draws() -> None:
    draws = (
        make_draw("2026001", (1, 2, 3, 4, 5, 6, 7)),
        make_draw("2026002", (8, 9, 10, 11, 12, 13, 14)),
    )
    candidate = CandidateSpec(candidate_id="previous", kind="previous_special")
    first = decide(candidate, draws[:1])
    future_changed = make_draw("2026002", (8, 9, 10, 11, 12, 13, 49))
    second = decide(candidate, (draws[0],))
    assert future_changed.special != draws[1].special
    assert first == second
    assert first.selection == 7
    assert first.information_cutoff_expect == "2026001"

    rolling = CandidateSpec(candidate_id="rolling", kind="rolling_mode", window=1)
    rolling_before = decide(rolling, (draws[0],))
    rolling_after_future_change = decide(rolling, (draws[0],))
    assert rolling_before == rolling_after_future_change
    assert rolling_before.selection == 7


def test_ledger_is_byte_deterministic() -> None:
    draws = (
        make_draw("2026001", (1, 2, 3, 4, 5, 6, 7)),
        make_draw("2026002", (8, 9, 10, 11, 12, 13, 14)),
    )
    selected_quote = quote()
    rule = build_rule(selected_quote)
    arguments = {
        "draws": draws,
        "candidates": default_candidates(),
        "quote": selected_quote,
        "rule": rule,
        "cost": CostModel(),
        "snapshot_id": "snapshot",
    }
    first_key, first_records = build_trial_records(**arguments)
    second_key, second_records = build_trial_records(**arguments)
    assert first_key == second_key
    assert ledger_bytes(first_records) == ledger_bytes(second_records)


def test_more_than_four_candidates_is_rejected() -> None:
    draw = make_draw("2026001", (1, 2, 3, 4, 5, 6, 7))
    selected_quote = quote()
    candidates = tuple(
        CandidateSpec(candidate_id=f"fixed_{number}", kind="fixed_number", fixed_number=number)
        for number in range(1, 6)
    )
    try:
        build_trial_records(
            draws=(draw,),
            candidates=candidates,
            quote=selected_quote,
            rule=build_rule(selected_quote),
            cost=CostModel(),
            snapshot_id="snapshot",
        )
    except ValueError as error:
        assert "at most four" in str(error)
    else:
        raise AssertionError("five candidates should have been rejected")


@given(st.lists(st.integers(min_value=1, max_value=49), min_size=7, max_size=7, unique=True))
def test_exact_number_win_iff_selection_equals_special(numbers: list[int]) -> None:
    draw = make_draw("2026001", tuple(numbers))  # type: ignore[arg-type]
    cost = CostModel()
    for selection in range(1, 50):
        result = settle(
            Decision(place_bet=True, selection=selection, information_cutoff_expect=None),
            draw,
            quote(),
            cost,
        )
        assert (result.outcome == "win") is (selection == draw.special)
