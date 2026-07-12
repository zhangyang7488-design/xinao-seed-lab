from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

import xinao_market_lab.runner as runner
from xinao_market_lab.inputs import InputLayout, build_snapshot_manifest, canonical_json_bytes
from xinao_market_lab.runner import (
    P5_ARTIFACT_NAMES,
    build_p5_trusted_anchor,
    run_p5_unresolved_semantics_evidence_catalog,
    verify_p5_run,
)

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
P4_RUN = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-exact-null-contamination-structure-acceptance-a-20260711"
)
P4_ANCHOR = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-exact-null-contamination-structure-trusted-anchor-20260711.json"
)
ADMIN_ACCEPTANCE = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-admin-acceptance-20260711\admin_acceptance.json"
)
TEST_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\test-runs")


@pytest.mark.skipif(
    not all(path.exists() for path in (INPUT_ROOT, P4_RUN, P4_ANCHOR, ADMIN_ACCEPTANCE)),
    reason="canonical P4/P5 inputs are unavailable",
)
def test_p5_actual_dual_run_anchor_semantic_replay_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    before = build_snapshot_manifest(InputLayout.from_root(INPUT_ROOT))
    with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory:
        evidence = Path(directory)
        first = run_p5_unresolved_semantics_evidence_catalog(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="first",
            p4_evidence_run=P4_RUN,
            p4_trusted_anchor=P4_ANCHOR,
            admin_acceptance=ADMIN_ACCEPTANCE,
        )
        second = run_p5_unresolved_semantics_evidence_catalog(
            input_root=INPUT_ROOT,
            evidence_root=evidence,
            run_name="second",
            p4_evidence_run=P4_RUN,
            p4_trusted_anchor=P4_ANCHOR,
            admin_acceptance=ADMIN_ACCEPTANCE,
        )
        for name in (*P5_ARTIFACT_NAMES, "run_manifest.json"):
            assert (evidence / "first" / name).read_bytes() == (evidence / "second" / name).read_bytes()
        anchor_path = evidence / "p5-trusted-anchor.json"
        anchor = build_p5_trusted_anchor(
            input_root=INPUT_ROOT,
            run_dir=evidence / "first",
            p4_evidence_run=P4_RUN,
            p4_trusted_anchor=P4_ANCHOR,
            admin_acceptance=ADMIN_ACCEPTANCE,
            anchor_path=anchor_path,
        )
        verified = verify_p5_run(
            input_root=INPUT_ROOT,
            run_dir=evidence / "second",
            p4_evidence_run=P4_RUN,
            p4_trusted_anchor=P4_ANCHOR,
            admin_acceptance=ADMIN_ACCEPTANCE,
            trusted_anchor=anchor_path,
        )
        original_source_statement = runner._p5_source_statement
        with monkeypatch.context() as source_drift:

            def drifted_source_statement():
                statement = original_source_statement()
                statement["subject"][0]["digest"]["sha256"] = "f" * 64
                return statement

            source_drift.setattr(runner, "_p5_source_statement", drifted_source_statement)
            with pytest.raises(ValueError, match="producer_source_statement"):
                verify_p5_run(
                    input_root=INPUT_ROOT,
                    run_dir=evidence / "second",
                    p4_evidence_run=P4_RUN,
                    p4_trusted_anchor=P4_ANCHOR,
                    admin_acceptance=ADMIN_ACCEPTANCE,
                )
        with pytest.raises(FileExistsError, match="immutable"):
            build_p5_trusted_anchor(
                input_root=INPUT_ROOT,
                run_dir=evidence / "first",
                p4_evidence_run=P4_RUN,
                p4_trusted_anchor=P4_ANCHOR,
                admin_acceptance=ADMIN_ACCEPTANCE,
                anchor_path=anchor_path,
            )

        coherent = evidence / "coherent-rewrite"
        shutil.copytree(evidence / "second", coherent)
        claim_path = coherent / "unresolved_claim_register.json"
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        claim["rule_claims"][0]["p5_evidence_status"] = "CONFLICT"
        claim_path.write_bytes(canonical_json_bytes(claim))
        judge_path = coherent / "judge_gate_p5.json"
        judge = json.loads(judge_path.read_text(encoding="utf-8"))
        judge["semantics_status"] = "SEMANTICS_CONFLICT_RECORDED"
        judge["rule_claim_statuses"]["payout_basis"] = "CONFLICT"
        judge_path.write_bytes(canonical_json_bytes(judge))
        checks_path = coherent / "checks.json"
        coherent_checks = json.loads(checks_path.read_text(encoding="utf-8"))
        coherent_checks["semantics_status"] = "SEMANTICS_CONFLICT_RECORDED"
        checks_path.write_bytes(canonical_json_bytes(coherent_checks))
        coherent_manifest_path = coherent / "run_manifest.json"
        coherent_manifest = json.loads(coherent_manifest_path.read_text(encoding="utf-8"))
        for name in (
            "unresolved_claim_register.json",
            "judge_gate_p5.json",
            "checks.json",
        ):
            path = coherent / name
            row = next(item for item in coherent_manifest["artifacts"] if item["relative_path"] == name)
            row["size_bytes"] = path.stat().st_size
            row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        coherent_manifest_path.write_bytes(canonical_json_bytes(coherent_manifest))
        with pytest.raises(ValueError, match="semantic artifact mismatch"):
            verify_p5_run(
                input_root=INPUT_ROOT,
                run_dir=coherent,
                p4_evidence_run=P4_RUN,
                p4_trusted_anchor=P4_ANCHOR,
                admin_acceptance=ADMIN_ACCEPTANCE,
            )

        tampered = evidence / "second" / "unresolved_claim_register.json"
        value = json.loads(tampered.read_text(encoding="utf-8"))
        value["rule_claims"][0]["p5_evidence_status"] = "RESOLVED"
        tampered.write_bytes(canonical_json_bytes(value))
        manifest_path = evidence / "second" / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        row = next(
            item
            for item in manifest["artifacts"]
            if item["relative_path"] == "unresolved_claim_register.json"
        )
        row["size_bytes"] = tampered.stat().st_size
        row["sha256"] = hashlib.sha256(tampered.read_bytes()).hexdigest()
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        with pytest.raises(ValueError, match="semantic artifact mismatch"):
            verify_p5_run(
                input_root=INPUT_ROOT,
                run_dir=evidence / "second",
                p4_evidence_run=P4_RUN,
                p4_trusted_anchor=P4_ANCHOR,
                admin_acceptance=ADMIN_ACCEPTANCE,
                trusted_anchor=anchor_path,
            )
    after = build_snapshot_manifest(InputLayout.from_root(INPUT_ROOT))

    assert before == after
    assert first["protocol_hash"] == second["protocol_hash"]
    assert first["evidence_ledger_sha256"] == second["evidence_ledger_sha256"]
    assert first["evidence_record_count"] == second["evidence_record_count"] == 20
    assert first["semantics_status"] == "SEMANTICS_STILL_UNRESOLVED"
    assert first["economic_claim_status"] == "ECONOMIC_CLAIM_BLOCKED"
    assert verified["status"] == "verified"
    assert verified["historical_artifact_integrity"] == "HISTORICAL_ARTIFACT_INTEGRITY_VERIFIED"
    assert verified["current_source_replay"] == "CURRENT_SOURCE_REPLAY_VERIFIED"
    assert verified["trusted_anchor_verified"] is True
    assert anchor["status"] == "trusted_anchor_created"


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical input is unavailable")
def test_p5_canonical_input_rejects_non_d_runtime_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical input evidence"):
        run_p5_unresolved_semantics_evidence_catalog(
            input_root=INPUT_ROOT,
            evidence_root=tmp_path,
            run_name="forbidden",
            p4_evidence_run=P4_RUN,
            p4_trusted_anchor=P4_ANCHOR,
            admin_acceptance=ADMIN_ACCEPTANCE,
        )
