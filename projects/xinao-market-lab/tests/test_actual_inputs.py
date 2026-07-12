from __future__ import annotations

from pathlib import Path

import pytest

from xinao_market_lab.inputs import InputLayout, audit_inputs, build_snapshot_manifest

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_canonical_input_contract_and_known_anomalies() -> None:
    layout = InputLayout.from_root(INPUT_ROOT)
    snapshot = build_snapshot_manifest(layout)
    draws, quote, audit = audit_inputs(layout)
    assert snapshot["file_count"] >= 30
    assert audit["history"]["jsonl_rows"] == 1209
    assert audit["history"]["tsv_rows"] == 1209
    assert audit["history"]["valid_draws"] == 1209
    assert audit["history"]["usable_mechanics_draws"] == 1203
    assert audit["history"]["verify_true_count"] == 0
    assert audit["history"]["verify_false_count"] == 1209
    assert audit["history"]["expect_year_mismatches"] == ["2023004"]
    assert audit["history"]["tsv_json_mismatch_count"] == 0
    assert audit["history"]["top_level_and_bundle_history_tsv_hash_equal"] is True
    assert audit["market_mapping"]["play_structure_rows"] == 136
    assert audit["market_mapping"]["odds_candidate_rows"] == 4043
    assert audit["market_mapping"]["quote"]["raw_candidate_count"] == 50
    assert audit["market_mapping"]["quote"]["discarded_parser_candidates"] == 1
    assert audit["bundle_manifest_mismatches"] == []
    assert len(audit["history"]["duplicate_outcome_groups"]) == 5
    assert len(audit["history"]["quarantined_duplicate_outcome_repetitions"]) == 5
    assert len(draws) == 1203
    assert quote.inclusive_return.as_tuple().exponent == -3
    assert str(quote.inclusive_return) == "47.285"
