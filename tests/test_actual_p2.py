from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from xinao_market_lab.inputs import InputLayout, audit_inputs_p2, build_snapshot_manifest
from xinao_market_lab.runner import run_p1, run_p2_domain_lineage_zhengma

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
EXPECTED_SNAPSHOT = "c2fffdf84483d868e659873928830fa769341e874b520d1f07e8fa2aad905877"
EXPECTED_P1_LEDGER = "9c2a59d6f9c26097ac933681dd84e5d9fa84e8ded19df32632873eae11fc0980"


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_p2_actual_input_provenance_and_lineage_contract() -> None:
    layout = InputLayout.from_root(INPUT_ROOT)
    snapshot = build_snapshot_manifest(layout)
    draws, quote, audit, lineage, catalog = audit_inputs_p2(layout)
    assert snapshot["snapshot_id"] == EXPECTED_SNAPSHOT
    assert len(lineage) == 1_209
    assert len(draws) == 1_204
    assert audit["legacy_p1"]["usable_draws"] == 1_203
    assert audit["lineage_v2"]["source_verify_true"] == 0
    assert audit["lineage_v2"]["strictly_increasing_open_time"] is True
    assert catalog["sources"]["play_structure"]["row_count"] == 136
    assert catalog["sources"]["odds_candidates"]["row_count"] == 4_043
    assert quote.captured_at.isoformat() == "2026-05-12T11:12:34.754000+00:00"
    assert quote.bundle_created_at.isoformat() == "2026-05-12T12:08:41.159999+00:00"
    assert str(quote.displayed_odds) == "7.850"
    assert quote.raw_source_sha256 == "6ef5161cb5271c7f3d772be2c468bd07686a72315204594fee47514b8f444a17"
    assert audit["regular_a_quote"]["page_aliases_identical"] is True
    assert [page["raw_candidate_count"] for page in audit["regular_a_quote"]["pages"]] == [55, 55]
    assert [page["numeric_candidate_count"] for page in audit["regular_a_quote"]["pages"]] == [50, 50]
    rejected = [item for page in audit["regular_a_quote"]["pages"] for item in page["rejected_candidates"]]
    assert sum(item["item"] == "49" and str(item["odds"]) == "132.000" for item in rejected) == 2
    by_expect = {record.source_expect: record for record in lineage}
    assert by_expect["2023004"].canonical_expect == "2024004"
    assert by_expect["2023004"].status == "quarantined"
    assert by_expect["2024004"].status == "canonical"


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_p2_is_read_only_and_semantic_artifacts_are_byte_reproducible() -> None:
    layout = InputLayout.from_root(INPUT_ROOT)
    before = build_snapshot_manifest(layout)
    test_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")
    test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=test_root) as directory:
        evidence = Path(directory)
        first = run_p2_domain_lineage_zhengma(input_root=INPUT_ROOT, evidence_root=evidence, run_name="first")
        second = run_p2_domain_lineage_zhengma(
            input_root=INPUT_ROOT, evidence_root=evidence, run_name="second"
        )
        for name in (
            "rule_catalog.json",
            "lineage_pin.json",
            "trials.jsonl",
            "conformance_events.jsonl",
            "exact_baseline.json",
        ):
            assert (evidence / "first" / name).read_bytes() == (evidence / "second" / name).read_bytes()
        checks = json.loads((evidence / "first" / "checks.json").read_text(encoding="utf-8"))
        baseline = json.loads((evidence / "first" / "exact_baseline.json").read_text(encoding="utf-8"))
        manifest = json.loads((evidence / "first" / "run_manifest.json").read_text(encoding="utf-8"))
    after = build_snapshot_manifest(layout)
    assert before["snapshot_id"] == after["snapshot_id"] == EXPECTED_SNAPSHOT
    assert first["status"] == second["status"] == "verified_rule_catalog_pure_settle_with_lineage_v2"
    assert checks["lineage_v2_usable_draws"] == 1_204
    assert checks["future_suffix_decisions_unchanged"] is True
    assert checks["typed_rule_count"] == 8
    assert checks["play_classification_rows"] == 136
    assert checks["play_implemented_reference_rows"] == 16
    assert checks["play_unresolved_rows"] == 120
    assert checks["conformance_event_count"] == 24
    assert checks["all_rules_have_three_golden_events"] is True
    assert checks["all_exact_number_49_paths_resolvable"] is True
    assert checks["all_label_and_two_sided_49_paths_unresolved"] is True
    assert baseline["uniform_hit_probability"]["fraction"] == "6/49"
    assert baseline["mechanics_rtp_under_assumption"]["fraction"] == "471/490"
    assert baseline["mechanics_net_expectation_under_assumption"]["fraction"] == "-19/490"
    assert all(value is False for value in manifest["claims"].values())


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_p1_ledger_remains_byte_compatible_after_p2() -> None:
    test_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")
    test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=test_root) as directory:
        result = run_p1(input_root=INPUT_ROOT, evidence_root=Path(directory), run_name="p1-regression")
    assert result["ledger_sha256"] == EXPECTED_P1_LEDGER


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical user data is not present on this machine")
def test_p2_canonical_input_rejects_non_d_runtime_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical input evidence"):
        run_p2_domain_lineage_zhengma(
            input_root=INPUT_ROOT,
            evidence_root=tmp_path,
            run_name="forbidden",
        )
