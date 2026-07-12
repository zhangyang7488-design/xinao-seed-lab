from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from xinao_market_lab.inputs import InputLayout, build_snapshot_manifest
from xinao_market_lab.runner import compare_ledgers, run_p1

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_real_p1_is_read_only_and_reproducible() -> None:
    layout = InputLayout.from_root(INPUT_ROOT)
    before = build_snapshot_manifest(layout)
    test_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")
    test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=test_root) as directory:
        evidence = Path(directory)
        first = run_p1(input_root=INPUT_ROOT, evidence_root=evidence, run_name="first")
        second = run_p1(input_root=INPUT_ROOT, evidence_root=evidence, run_name="second")
        comparison = compare_ledgers(evidence / "first", evidence / "second")
        checks = json.loads((evidence / "first" / "checks.json").read_text(encoding="utf-8"))
        baseline = json.loads((evidence / "first" / "uniform_rtp_baseline.json").read_text(encoding="utf-8"))
    after = build_snapshot_manifest(layout)
    assert before["snapshot_id"] == after["snapshot_id"]
    assert first["status"] == second["status"] == "verified_mechanics_only"
    assert comparison["equal"] is True
    assert checks["always_no_bet_net_zero"] is True
    assert baseline["theoretical_uniform_rtp"] == str(47.285 / 49) or baseline[
        "theoretical_uniform_rtp"
    ].startswith("0.965")


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_canonical_input_rejects_non_d_runtime_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical input evidence"):
        run_p1(input_root=INPUT_ROOT, evidence_root=tmp_path, run_name="forbidden")
