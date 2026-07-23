from __future__ import annotations

from pathlib import Path

import pytest

from xinao.foundation.assertion_verifier_registry import canonical_projection_path
from xinao.world.builder import (
    DEFAULT_BLUEPRINT_PATH,
    DEFAULT_DATASET_PATH,
    build_world,
    replay_world,
)


def test_world_builder_uses_current_canonical_projection() -> None:
    assert canonical_projection_path() == DEFAULT_BLUEPRINT_PATH


@pytest.mark.skipif(not DEFAULT_DATASET_PATH.is_file(), reason="formal dataset is not mounted")
def test_913_draw_world_build_and_independent_hash_replay(tmp_path: Path) -> None:
    result = build_world(
        dataset="verified-913",
        baseline="baseline-odds-water.v1",
        rule="special-number-rule.v1",
        output_root=tmp_path,
        correlation_id="0190f9c0-6f4c-7c00-8b22-334455667788",
        workflow_id="fixture-workflow",
        run_id="0190f9c0-6f4c-7c01-8b22-334455667788",
    )
    snapshot = result["event_matrix_snapshot"]
    assert snapshot["draw_count"] == 913
    assert snapshot["row_count"] == 913 * 2 * 49
    assert snapshot["nnz"] == 913 * 2
    assert snapshot["first_draw_id"] == "2024001"
    assert snapshot["last_draw_id"] == "2026182"
    replay_report = tmp_path / "fresh_process_replay.json"
    replay = replay_world(tmp_path, report_path=replay_report)
    assert replay["ok"] is True
    assert replay_report.is_file()
    assert replay["recorded_matrix_sha256"] == replay["recomputed_matrix_sha256"]


def test_wrong_world_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported dataset"):
        build_world(
            dataset="wrong",
            baseline="baseline-odds-water.v1",
            rule="special-number-rule.v1",
            output_root=tmp_path,
        )
