from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from xinao_market_lab.inputs import InputLayout, build_snapshot_manifest
from xinao_market_lab.runner import (
    run_p1,
    run_p2_domain_lineage_zhengma,
    run_p3_research_protocol_judge,
    verify_p3_run,
)

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
P2_EVIDENCE = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p2-rule-catalog-acceptance-a-20260711"
)
TEST_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")
EXPECTED_SNAPSHOT = "c2fffdf84483d868e659873928830fa769341e874b520d1f07e8fa2aad905877"
EXPECTED_P1_LEDGER = "9c2a59d6f9c26097ac933681dd84e5d9fa84e8ded19df32632873eae11fc0980"
EXPECTED_P2_LEDGER = "8e98407bd07812768c401be9d8f5f34fa5b77c8f80e86c6eb60a8376ba794d01"


@pytest.mark.skipif(
    not INPUT_ROOT.is_dir() or not P2_EVIDENCE.is_dir(),
    reason="canonical input or accepted P2 evidence is unavailable",
)
def test_p3_actual_dual_run_is_byte_reproducible_and_read_only() -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    layout = InputLayout.from_root(INPUT_ROOT)
    before = build_snapshot_manifest(layout)
    with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory:
        evidence = Path(directory)
        first = run_p3_research_protocol_judge(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="first",
            p2_evidence_run=P2_EVIDENCE,
        )
        second = run_p3_research_protocol_judge(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="second",
            p2_evidence_run=P2_EVIDENCE,
        )
        semantic_artifacts = (
            "input_snapshot.json",
            "source_audit.json",
            "rule_surface_pin.json",
            "p2_acceptance_pin.json",
            "research_protocol.json",
            "trials.jsonl",
            "cell_summary.json",
            "tombstones.jsonl",
            "judge_gate.json",
            "checks.json",
        )
        for name in semantic_artifacts:
            assert (evidence / "first" / name).read_bytes() == (evidence / "second" / name).read_bytes()
        verification = verify_p3_run(input_root=INPUT_ROOT, run_dir=evidence / "first")
        judge = json.loads((evidence / "first" / "judge_gate.json").read_text(encoding="utf-8"))
        protocol = json.loads((evidence / "first" / "research_protocol.json").read_text(encoding="utf-8"))
    after = build_snapshot_manifest(layout)

    assert before == after
    assert before["snapshot_id"] == EXPECTED_SNAPSHOT
    assert (
        first["status"]
        == second["status"]
        == ("verified_research_protocol_mechanics_economic_claims_blocked")
    )
    assert first["protocol_hash"] == second["protocol_hash"]
    assert first["trial_ledger_sha256"] == second["trial_ledger_sha256"]
    assert first["trial_rows"] == second["trial_rows"] == 38_528
    assert first["cell_count"] == second["cell_count"] == 32
    assert verification["status"] == "verified"
    assert judge["mechanics_status"] == "MECHANICS_ACCEPTED"
    assert judge["economic_claim_status"] == "ECONOMIC_CLAIM_BLOCKED"
    assert all(judge["checks"].values())
    assert protocol["spec"]["declared_cell_budget"] == 32
    assert protocol["spec"]["declared_trial_row_budget"] == 38_528
    assert [fold["end_index_exclusive"] - fold["start_index"] for fold in protocol["spec"]["folds"]] == [
        301,
        301,
        301,
        301,
    ]


@pytest.mark.skipif(
    not INPUT_ROOT.is_dir() or not P2_EVIDENCE.is_dir(),
    reason="canonical input or accepted P2 evidence is unavailable",
)
def test_p3_preserves_p1_and_p2_ledger_contracts() -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory:
        evidence = Path(directory)
        p1 = run_p1(input_root=INPUT_ROOT, evidence_root=evidence, run_name="p1")
        p2 = run_p2_domain_lineage_zhengma(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="p2",
        )
    assert p1["ledger_sha256"] == EXPECTED_P1_LEDGER
    assert p2["ledger_sha256"] == EXPECTED_P2_LEDGER
    assert p2["conformance_ledger_sha256"] == (
        "d1dd5444d5c47c75c15187f9e3bfa8c76672c6f5f4c07728338f19e3efda0a6f"
    )


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user input is unavailable")
def test_p3_canonical_input_rejects_non_d_runtime_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical input evidence"):
        run_p3_research_protocol_judge(
            input_root=INPUT_ROOT,
            evidence_root=tmp_path,
            run_name="forbidden",
            p2_evidence_run=P2_EVIDENCE,
        )
