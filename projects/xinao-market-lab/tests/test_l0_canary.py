from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xinao_market_lab.inputs import InputLayout, audit_inputs_p2
from xinao_market_lab.l0_canary import (
    MODEL_IDS,
    evaluate_special_models,
    run_l0_next_draw,
    verify_l0_next_draw_run,
    walk_forward_windows,
)
from xinao_market_lab.models import Draw

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")


def _draws(count: int = 300) -> tuple[Draw, ...]:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    rows: list[Draw] = []
    for index in range(count):
        special = index % 49 + 1
        regular = tuple((special + offset - 1) % 49 + 1 for offset in range(1, 7))
        rows.append(
            Draw(
                series_id="synthetic",
                source_expect=f"{2_023_001 + index:07d}",
                open_time=start + timedelta(days=index),
                regular_numbers=regular,
                special=special,
                wave=("red",) * 7,
                zodiac=("test",) * 7,
                source_verified=False,
            )
        )
    return tuple(rows)


def test_walk_forward_is_six_strict_time_ordered_cycles() -> None:
    windows = walk_forward_windows(300, initial_train=180, test_size=20, step=20)
    assert len(windows) == 6
    assert windows[0] == {
        "cycle": 1,
        "train_start": 0,
        "train_end_exclusive": 180,
        "test_start": 180,
        "test_end_exclusive": 200,
    }
    assert windows[-1]["test_end_exclusive"] == 300
    assert all(row["train_end_exclusive"] <= row["test_start"] for row in windows)


def test_three_registered_models_emit_prequential_scores_and_zero_stake() -> None:
    table, predictions, judgment = evaluate_special_models(_draws())
    assert [row["model_id"] for row in table["aggregate"]] == list(MODEL_IDS)
    assert table["walk_forward"]["oos_cycles"] == 6
    assert table["walk_forward"]["oos_trials_per_model"] == 120
    assert len(predictions) == 3 * 120
    assert all(row["information_cutoff_sample_index"] < row["target_sample_index"] for row in predictions)
    assert all(row["mean_log_loss"] > 0 for row in table["aggregate"])
    assert all(
        0 <= row["top5_exact_ci_95"]["low"] <= row["top5_exact_ci_95"]["high"] <= 1
        for row in table["aggregate"]
    )
    assert judgment["action"]["stake_units"] == 0
    assert judgment["action"]["edge_claim"] is False
    assert judgment["action"]["recommendation_claim"] is False


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user input is unavailable")
def test_actual_canonical_l0_uses_1204_rows_and_honest_negative_gate() -> None:
    draws, _quote, _audit, _lineage, _catalog = audit_inputs_p2(InputLayout.from_root(INPUT_ROOT))
    table, predictions, judgment = evaluate_special_models(draws)
    assert len(draws) == 1_204
    assert table["sample"]["canonical_draw_count"] == 1_204
    assert table["sample"]["N"] == 300
    assert table["walk_forward"]["oos_cycles"] == 6
    assert len(predictions) == 360
    assert all(row["top5_exact_ci_95"]["high"] < 1 for row in table["aggregate"])
    assert judgment["action"] == {
        "mode": "observe_only_no_bet",
        "stake_units": 0,
        "recommendation_claim": False,
        "edge_claim": False,
    }
    assert judgment["selected_distribution"] == "uniform_1_over_49"
    assert judgment["ranked_numbers"] == []


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user input is unavailable")
def test_actual_l0_run_is_independently_recomputable_and_tamper_evident() -> None:
    test_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")
    test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=test_root) as directory:
        root = Path(directory)
        result = run_l0_next_draw(
            input_root=INPUT_ROOT,
            evidence_root=root,
            run_name="actual",
        )
        run_dir = Path(result["run_dir"])
        verified = verify_l0_next_draw_run(input_root=INPUT_ROOT, run_dir=run_dir)
        assert verified["verified"] is True
        judgment_path = run_dir / "next_draw_judgment.json"
        judgment = json.loads(judgment_path.read_text(encoding="utf-8"))
        judgment["action"]["stake_units"] = 1
        judgment_path.write_text(json.dumps(judgment), encoding="utf-8")
        failed = verify_l0_next_draw_run(input_root=INPUT_ROOT, run_dir=run_dir)
        assert failed["verified"] is False
        assert failed["content_matches"]["next_draw_judgment.json"] is False


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user input is unavailable")
def test_canonical_l0_rejects_non_d_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical input evidence"):
        run_l0_next_draw(input_root=INPUT_ROOT, evidence_root=tmp_path, run_name="forbidden")
