from __future__ import annotations

from types import SimpleNamespace

import pytest

from xinao.foundation import semantics_linked, semantics_sets
from xinao.foundation.f1_property_oracles import linked_outcome, set_outcome


def _fail_production_zodiac_lookup(_draw_date: object) -> object:
    raise RuntimeError("production zodiac lookup was called")


def test_set_oracle_does_not_reuse_the_production_zodiac_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        semantic_family_ref="special-number-in-set.v1",
        semantic_parameters={"set_kind": "ZODIAC_BY_DRAW_DATE", "selector": "龙"},
    )
    draw = (10, 11, 12, 13, 14, 15, 3)
    assert set_outcome(record, draw, "2026-07-17", None) == "HIT"
    assert (
        semantics_sets.settle_rule(
            record,
            draw=draw,
            draw_date="2026-07-17",
        )
        == "HIT"
    )

    monkeypatch.setattr(semantics_sets, "zodiac_number_table", _fail_production_zodiac_lookup)
    assert set_outcome(record, draw, "2026-07-17", None) == "HIT"
    with pytest.raises(RuntimeError, match="production zodiac lookup"):
        semantics_sets.settle_rule(record, draw=draw, draw_date="2026-07-17")


def test_linked_oracle_does_not_reuse_the_production_zodiac_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (
        SimpleNamespace(
            family_id="linked-zodiac",
            component_label="马",
            polarity="HIT_ALL_LABELS",
        ),
        SimpleNamespace(
            family_id="linked-zodiac",
            component_label="蛇",
            polarity="HIT_ALL_LABELS",
        ),
    )
    draw = (1, 2, 10, 11, 12, 13, 14)
    assert linked_outcome(records, draw, "2026-07-17") == "HIT"

    monkeypatch.setattr(semantics_linked, "zodiac_number_table", _fail_production_zodiac_lookup)
    assert linked_outcome(records, draw, "2026-07-17") == "HIT"
    with pytest.raises(RuntimeError, match="production zodiac lookup"):
        semantics_linked._linked_number_sets(records, draw_date="2026-07-17")
