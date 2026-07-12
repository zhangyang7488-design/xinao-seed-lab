from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_c01_c15.py"
    spec = importlib.util.spec_from_file_location("verify_c01_c15_for_c10", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture_tree(tmp_path: Path, *, execution_closed: bool) -> tuple[Path, Path]:
    kaigong = tmp_path / "state"
    sat = tmp_path / "sat"
    _write(
        kaigong / "S8_interface_inventory_latest.json",
        {"budget_universe_built": True, "inventory_only": False},
    )
    g18 = sat / "G18_c10_budget"
    cells = [{"cell_id": f"cell_{idx:03d}", "executed": True} for idx in range(1, 25)]
    universe = {
        "budget_universe_built": True,
        "budget_expansion_executed": True,
        "n_seeds": 3,
        "n_split_schemes": 2,
        "candidates": [{"id": str(idx)} for idx in range(4)],
        "cartesian": {"n_cells_total": 24},
        "cells": cells,
        "min_required_met": True,
        "multiple_testing_plan": {"procedure": "Benjamini-Hochberg"},
        "l1_closed": False,
        "l1_budget_execution_closed": execution_closed,
        "exact_cell_id_coverage": True,
    }
    _write(g18 / "budget_universe.json", universe)
    _write(g18 / "RESULT.json", {"budget_universe_built": True})
    _write(
        sat / "G22_budget_execute" / "RESULT.json",
        {
            "n_cells_executed": 24,
            "control_mechanics_ok": True,
            "multiple_testing_actual": {"all_six_retained": True},
            "l1_budget_execution_closed": execution_closed,
            "edge_claim": False,
        },
    )
    return kaigong, sat


def test_c10_passes_completed_budget_even_when_statistical_l1_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    kaigong, sat = _fixture_tree(tmp_path, execution_closed=True)
    monkeypatch.setattr(module, "KAIGONG", kaigong)
    monkeypatch.setattr(module, "SAT", sat)

    result = module.check_c10()

    assert result["ok"] is True
    assert result["verdict"] == "PASS"
    assert result["checks"]["g18_c10_budget"]["l1_closed"] is False
    assert result["checks"]["g18_c10_budget"]["l1_budget_execution_closed"] is True


def test_c10_rejects_plan_only_or_unclosed_execution(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    kaigong, sat = _fixture_tree(tmp_path, execution_closed=False)
    monkeypatch.setattr(module, "KAIGONG", kaigong)
    monkeypatch.setattr(module, "SAT", sat)

    result = module.check_c10()

    assert result["ok"] is False
    assert result["verdict"] == "PARTIAL"
