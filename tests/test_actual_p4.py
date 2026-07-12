from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import xinao_market_lab.runner as runner
from xinao_market_lab.inputs import InputLayout, build_snapshot_manifest
from xinao_market_lab.runner import (
    P4_ARTIFACT_NAMES,
    build_p4_trusted_anchor,
    run_p4_exact_null_contamination_structure,
    verify_p4_run,
)

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
P3_EVIDENCE = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p3-research-protocol-acceptance-a-20260711"
)
TEST_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")
EXPECTED_SNAPSHOT = "c2fffdf84483d868e659873928830fa769341e874b520d1f07e8fa2aad905877"


@pytest.mark.skipif(
    not INPUT_ROOT.is_dir() or not P3_EVIDENCE.is_dir(),
    reason="canonical input or accepted P3 evidence is unavailable",
)
def test_p4_actual_dual_run_full_resimulation_anchor_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    layout = InputLayout.from_root(INPUT_ROOT)
    before = build_snapshot_manifest(layout)
    with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory:
        evidence = Path(directory)
        first = run_p4_exact_null_contamination_structure(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="first",
            p3_evidence_run=P3_EVIDENCE,
        )
        second = run_p4_exact_null_contamination_structure(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="second",
            p3_evidence_run=P3_EVIDENCE,
        )
        for name in (*P4_ARTIFACT_NAMES, "run_manifest.json"):
            assert (evidence / "first" / name).read_bytes() == (evidence / "second" / name).read_bytes()
        monkeypatch.setattr(runner, "_source_fingerprint", lambda: "f" * 64)
        anchor_path = evidence / "p4-trusted-anchor.json"
        anchor = build_p4_trusted_anchor(
            input_root=INPUT_ROOT,
            run_dir=evidence / "first",
            anchor_path=anchor_path,
        )
        verification = verify_p4_run(
            input_root=INPUT_ROOT,
            run_dir=evidence / "second",
            trusted_anchor=anchor_path,
        )
        judge = json.loads((evidence / "first" / "judge_gate_p4.json").read_text(encoding="utf-8"))
        checks = json.loads((evidence / "first" / "checks.json").read_text(encoding="utf-8"))
    after = build_snapshot_manifest(layout)

    assert before == after
    assert before["snapshot_id"] == EXPECTED_SNAPSHOT
    assert first["protocol_hash"] == second["protocol_hash"]
    assert first["null_statistics_sha256"] == second["null_statistics_sha256"]
    assert first["simulation_count"] == second["simulation_count"] == 19_999
    assert first["family_size"] == second["family_size"] == 5
    assert verification["status"] == "verified"
    assert verification["trusted_anchor_verified"] is True
    assert anchor["status"] == "trusted_anchor_created"
    assert judge["economic_claim_status"] == "ECONOMIC_CLAIM_BLOCKED"
    assert all(judge["checks"].values())
    assert checks["raw_collision_pair_counts"] == {
        "ordered_regular_6_plus_special": 5,
        "regular_set_plus_special": 5,
        "unordered_seven": 5,
    }


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user input is unavailable")
def test_p4_canonical_input_rejects_non_d_runtime_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical input evidence"):
        run_p4_exact_null_contamination_structure(
            input_root=INPUT_ROOT,
            evidence_root=tmp_path,
            run_name="forbidden",
            p3_evidence_run=P3_EVIDENCE,
        )
