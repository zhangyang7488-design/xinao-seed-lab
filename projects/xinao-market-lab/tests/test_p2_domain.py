from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from xinao_market_lab.domain import (
    build_regular_semantics,
    build_special_semantics,
    compile_rule_claim,
    p2_decision_trace_bytes,
    p2_rule_claims,
    regular_mechanics_fractions,
    settle_regular_exact,
)
from xinao_market_lab.inputs import build_lineage_v2
from xinao_market_lab.models import (
    CandidateSpec,
    CostModel,
    Decision,
    DisplayedOddsQuote,
    Draw,
    RuleSemantics,
)

UTC = ZoneInfo("UTC")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_draw(
    expect: str,
    numbers: tuple[int, int, int, int, int, int, int],
    *,
    day: int = 1,
    year: int = 2026,
) -> Draw:
    flags = () if expect[:4] == str(year) else ("expect_year_mismatch",)
    return Draw(
        series_id="macaujc2_daily_2132_type8",
        source_expect=expect,
        open_time=datetime(year, 1, day, 21, 32, 32, tzinfo=SHANGHAI),
        regular_numbers=numbers[:6],
        special=numbers[6],
        wave=("red", "blue", "green", "red", "blue", "green", "red"),
        zodiac=("鼠", "牛", "虎", "兔", "龍", "蛇", "馬"),
        source_verified=False,
        flags=flags,
    )


def displayed_quote(value: str = "7.85") -> DisplayedOddsQuote:
    return DisplayedOddsQuote(
        quote_id=f"quote-{value}",
        captured_at=datetime(2026, 5, 12, 11, 12, 34, 754000, tzinfo=UTC),
        bundle_created_at=datetime(2026, 5, 12, 12, 8, 41, tzinfo=UTC),
        page_key="canonical-page",
        alias_page_keys=("alias-page",),
        source_file="source.json",
        raw_source_file="raw/source.json",
        raw_source_sha256="a" * 64,
        accepted_numbers=tuple(range(1, 50)),
        displayed_odds=Decimal(value),
    )


def regular_claim_and_semantics():
    regular = build_regular_semantics()
    claims = p2_rule_claims(
        regular_semantics=regular,
        special_semantics=build_special_semantics(),
    )
    claim = next(item for item in claims if item.subject == "regular_set_membership")
    return claim, regular, claims


def test_semantics_hash_is_independent_of_quote_and_invalid_combinations_fail() -> None:
    first = build_regular_semantics()
    _ = displayed_quote("7.85")
    second = build_regular_semantics()
    _ = displayed_quote("7.80")
    assert first.semantics_hash == second.semantics_hash

    with pytest.raises(ValidationError, match="known contract"):
        RuleSemantics(
            semantics_id="bad",
            semantics_hash="b" * 64,
            play_family="regular_number",
            projection="special",
            winning_condition="decision.selection == draw.special",
        )


def test_unresolved_claims_cannot_compile() -> None:
    _claim, regular, claims = regular_claim_and_semantics()
    for unresolved in (claim for claim in claims if claim.status == "unresolved"):
        with pytest.raises(ValueError, match="not executable"):
            compile_rule_claim(unresolved, regular)


@given(st.lists(st.integers(min_value=1, max_value=49), min_size=7, max_size=7, unique=True))
def test_regular_exact_wins_iff_selection_is_in_regular_six(numbers: list[int]) -> None:
    draw = make_draw("2026001", tuple(numbers))  # type: ignore[arg-type]
    claim, semantics, _claims = regular_claim_and_semantics()
    for selection in range(1, 50):
        result = settle_regular_exact(
            Decision(place_bet=True, selection=selection, information_cutoff_expect=None),
            draw,
            displayed_quote(),
            CostModel(),
            semantics=semantics,
            claim=claim,
            payout_assumption_id="mechanics-assumption-inclusive-return-v1",
        )
        assert (result.outcome == "win") is (selection in draw.regular_numbers)
        assert result.net_return == (Decimal("6.85") if selection in draw.regular_numbers else -1)


def test_exact_regular_fractions_and_no_bet() -> None:
    fractions = regular_mechanics_fractions(displayed_quote())
    assert fractions["uniform_hit_probability"] == Fraction(6, 49)
    assert fractions["mechanics_rtp_under_inclusive_return_assumption"] == Fraction(471, 490)
    assert fractions["mechanics_net_expectation_under_inclusive_return_assumption"] == Fraction(-19, 490)

    claim, semantics, _claims = regular_claim_and_semantics()
    skipped = settle_regular_exact(
        Decision(place_bet=False, selection=None, information_cutoff_expect=None),
        make_draw("2026001", (1, 24, 25, 48, 49, 6, 7)),
        displayed_quote(),
        CostModel(),
        semantics=semantics,
        claim=claim,
        payout_assumption_id="mechanics-assumption-inclusive-return-v1",
    )
    assert skipped.stake == skipped.gross_return == skipped.net_return == Decimal("0")


def test_lineage_v2_prefers_valid_exact_time_alias_then_quarantines_later_outcome() -> None:
    repeated = (39, 36, 28, 49, 12, 24, 40)
    later = (1, 2, 3, 4, 5, 6, 7)
    draws = (
        make_draw("2023004", repeated, day=4, year=2024),
        make_draw("2024004", repeated, day=4, year=2024),
        make_draw("2026001", later, day=5),
        make_draw("2026002", later, day=6),
    )
    usable, lineage = build_lineage_v2(draws)
    assert [draw.source_expect for draw in usable] == ["2024004", "2026001"]
    by_expect = {record.source_expect: record for record in lineage}
    assert by_expect["2023004"].reason_code == "expect_year_mismatch_exact_time_alias"
    assert by_expect["2023004"].canonical_expect == "2024004"
    assert by_expect["2024004"].reason_code == "canonical_validation_ranked_exact_time_alias"
    assert by_expect["2026002"].reason_code == "later_full_outcome_repetition"
    assert by_expect["2026002"].canonical_expect == "2026001"


def test_real_future_suffix_mutation_does_not_change_prior_decisions() -> None:
    draws = (
        make_draw("2026001", (1, 2, 3, 4, 5, 6, 7), day=1),
        make_draw("2026002", (8, 9, 10, 11, 12, 13, 14), day=2),
        make_draw("2026003", (15, 16, 17, 18, 19, 20, 21), day=3),
    )
    changed_future = make_draw("2026003", (22, 23, 24, 25, 26, 27, 28), day=3)
    candidates = (
        CandidateSpec(candidate_id="previous", kind="previous_special"),
        CandidateSpec(candidate_id="rolling", kind="rolling_mode", window=1),
    )
    original_prefix = p2_decision_trace_bytes(draws, candidates, through_index=2)
    changed_prefix = p2_decision_trace_bytes((*draws[:2], changed_future), candidates, through_index=2)
    assert original_prefix == changed_prefix
