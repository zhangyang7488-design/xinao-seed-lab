from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from xinao.world.builder import DrawRecord, iter_event_rows


@given(st.integers(min_value=1, max_value=49))
@settings(max_examples=49)
def test_each_draw_has_one_hit_per_panel_and_all_49_selections(actual: int) -> None:
    others = [value for value in range(1, 50) if value != actual][:6]
    draw = DrawRecord(
        expect="2024001",
        openTime="2024-01-01 21:32:32",
        openCode=",".join(f"{value:02d}" for value in [*others, actual]),
    )
    rows = list(iter_event_rows([draw]))
    assert len(rows) == 98
    for panel in ("A", "B"):
        panel_rows = [row for row in rows if row.panel == panel]
        assert {row.selected_number for row in panel_rows} == set(range(1, 50))
        assert sum(row.hit for row in panel_rows) == 1
        assert next(row for row in panel_rows if row.hit).selected_number == actual
