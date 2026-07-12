from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from xinao_market_lab.catalog import (
    build_conformance_events,
    conformance_ledger_bytes,
    load_rule_bundle,
    resolve_exact_rule,
    rule_semantic_hash,
    rule_semantic_material,
    settle_catalog_exact,
    verify_conformance_events,
)
from xinao_market_lab.models import CompiledExactRule, CostModel, Decision, Draw

RULE_BUNDLE = Path(__file__).parents[1] / "rules" / "p2_rule_bundle_v1.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_draw(
    expect: str,
    numbers: tuple[int, int, int, int, int, int, int],
    *,
    day: int,
) -> Draw:
    return Draw(
        series_id="macaujc2_daily_2132_type8",
        source_expect=expect,
        open_time=datetime(2026, 1, day, 21, 32, 32, tzinfo=SHANGHAI),
        regular_numbers=numbers[:6],
        special=numbers[6],
        wave=("red", "blue", "green", "red", "blue", "green", "red"),
        zodiac=("鼠", "牛", "虎", "兔", "龍", "蛇", "馬"),
        source_verified=False,
    )


def compiled_rules() -> tuple[CompiledExactRule, ...]:
    bundle = load_rule_bundle(RULE_BUNDLE)
    return tuple(
        CompiledExactRule(
            definition=definition,
            rule_hash=rule_semantic_hash(definition),
            quote_evidence={},
        )
        for definition in bundle.rules
    )


def test_rule_bundle_is_strict_eight_rule_surface_and_hash_excludes_quote() -> None:
    bundle = load_rule_bundle(RULE_BUNDLE)
    assert len(bundle.rules) == len({rule.rule_key for rule in bundle.rules}) == 8
    assert {rule.pid for rule in bundle.rules} == {"1", "2", "3"}
    assert [rule.tid for rule in bundle.rules] == ["14", "16", "18", "19", "20", "21", "22", "23"]
    for rule in bundle.rules:
        material = rule_semantic_material(rule)
        assert "expected_modal_odds" not in material
        assert "price_status" not in material
        assert len(rule_semantic_hash(rule)) == 64


def test_resolver_is_unresolved_by_default_for_unsupported_or_ambiguous_paths() -> None:
    rules = compiled_rules()
    resolved = resolve_exact_rule(rules, pid="3", tid="22", pan="A", selection=49)
    assert resolved.status == "IMPLEMENTED"
    assert resolved.rule_key == "regular-position-5-a"

    for query in (
        {"pid": "3", "tid": "22", "pan": "", "selection": 49},
        {"pid": "1", "tid": "14", "pan": "A", "selection": 49, "requested_mode": "two_sided"},
        {"pid": "9", "tid": "41", "pan": "", "selection": 1},
        {"pid": "2", "tid": "16", "pan": "A", "selection": None},
    ):
        unresolved = resolve_exact_rule(rules, **query)  # type: ignore[arg-type]
        assert unresolved.status == "UNRESOLVED"
        assert unresolved.rule_key is None
        assert unresolved.rule_hash is None


@given(st.lists(st.integers(min_value=1, max_value=49), min_size=7, max_size=7, unique=True))
def test_all_typed_rules_are_pure_exact_projections(numbers: list[int]) -> None:
    draw = make_draw("2026001", tuple(numbers), day=1)  # type: ignore[arg-type]
    cost = CostModel()
    for rule in compiled_rules():
        for selection in range(1, 50):
            settlement = settle_catalog_exact(
                Decision(place_bet=True, selection=selection, information_cutoff_expect=None),
                draw,
                rule,
                cost,
            )
            definition = rule.definition
            if definition.projection == "special":
                expected = selection == draw.special
            elif definition.projection == "regular_set":
                expected = selection in draw.regular_numbers
            else:
                assert definition.position is not None
                expected = selection == draw.regular_numbers[definition.position - 1]
            assert (settlement.outcome == "win") is expected
            if expected:
                assert settlement.gross_return == Decimal(definition.expected_modal_odds)
            else:
                assert settlement.net_return == Decimal("-1")


def test_hash_chain_has_three_cases_per_rule_and_detects_tampering() -> None:
    draws = (
        make_draw("2026001", (1, 2, 3, 4, 5, 6, 7), day=1),
        make_draw("2026002", (8, 9, 10, 11, 12, 13, 14), day=2),
        make_draw("2026003", (15, 16, 17, 18, 19, 20, 21), day=3),
    )
    events = build_conformance_events(draws, compiled_rules(), CostModel())
    assert len(events) == 24
    assert events[0].previous_hash == "0" * 64
    assert all(events[index].previous_hash == events[index - 1].event_hash for index in range(1, 24))
    assert len(conformance_ledger_bytes(events)) > 0

    tampered = (events[0].model_copy(update={"output_hash": "f" * 64}), *events[1:])
    with pytest.raises(ValueError, match="output hash mismatch"):
        verify_conformance_events(tampered)
