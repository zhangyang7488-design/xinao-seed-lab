from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from xinao.admission import (
    REQUIRED_SOURCE_IDS,
    build_domain_research_admission_report,
    evidence_ref,
    verify_domain_research_admission_file,
    verify_domain_research_admission_report,
)
from xinao.canonical import canonical_sha256

SCOPE = "xinao-domain-mainline"
REALM = "DOMAIN_FIXED_AXIOM"
INPUT_HASHES = {"authority": "a" * 64, "dataset": "b" * 64}


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _source_payload(source_id: str) -> dict[str, object]:
    common: dict[str, object] = {
        "scope": SCOPE,
        "realm": REALM,
        "input_hashes": INPUT_HASHES,
    }
    payloads: dict[str, dict[str, object]] = {
        "FOUNDATION": {
            "schema_version": "xinao.foundation_closure_report.v2",
            "status": "VERIFIED",
            "foundation_execution_ready": True,
            "foundation_closed": False,
            "formal_research_allowed": False,
            "legacy_a_g_gate_used": False,
            "manual_override_used": False,
        },
        "G0": {
            "schema_version": "xinao.foundation.g0.owner_acceptance.v1",
            "authority": True,
            "owner_adopted": True,
            "g0_closed": True,
            "closed_for_admission_formula": True,
            "formal_open": False,
        },
        "G1": {
            "schema_version": "xinao.measurement_readiness_report.v1",
            "authority": True,
            "g1_closed": True,
            "closed_for_admission_formula": True,
            "effect_verified": True,
            "decision": "G1_MEASUREMENT_READY_VERIFIED",
        },
        "G2": {
            "schema_version": "xinao.g2.v23.current_v3_cas.postcas_owner_acceptance.v1",
            "authority": True,
            "authority_applied": True,
            "effect_verified": True,
            "g2_closure_authorized": True,
            "claim_status": "closed",
            "verdict": "ACCEPT",
        },
        "G3": {
            "schema_version": "xinao.foundation.g3.final_pin.owner_acceptance.v1",
            "authority": True,
            "owner_adopted": True,
            "effect_verified": True,
            "g3_closed": True,
            "verdict": "ADOPT",
        },
        "G4": {
            "schema_version": "xinao.end_to_end_autonomous_research_capability_report.v1",
            "authority": True,
            "g4_full": True,
            "g4_closed": True,
            "completion_claim_allowed": True,
            "decision": "G4_DISCOVERY_CAPABILITY_PROVED",
        },
        "G5": {
            "schema_version": "xinao.statistical_validity_report.v1",
            "authority": True,
            "g5_statistical_validity_ready": True,
            "g5_closed": True,
            "completion_claim_allowed": True,
            "decision": "G5_STATISTICAL_VALIDITY_READY",
        },
    }
    return {**common, **payloads[source_id]}


def _source_paths(tmp_path: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for source_id in REQUIRED_SOURCE_IDS:
        path = tmp_path / f"{source_id.lower()}.json"
        _write(path, _source_payload(source_id))
        paths[source_id] = path
    return paths


def _materialization_receipt(
    path: Path,
    source_bundle_hash: str,
    materialization_subject_hash: str,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "xinao.domain_research_admission_materialization_receipt.v1",
        "source_bundle_hash": source_bundle_hash,
        "materialization_subject_hash": materialization_subject_hash,
        "transaction_id": "unit-transaction",
        "event_id": "unit-event",
        "outbox_id": "unit-outbox",
        "same_transaction": True,
        "event_persisted": True,
        "outbox_persisted": True,
        "idempotent_replay": True,
        "compensation_status": "NOT_REQUIRED",
    }
    receipt["content_hash"] = canonical_sha256(receipt)
    _write(path, receipt)
    return evidence_ref(path)


def _report(tmp_path: Path, paths: dict[str, Path]) -> dict[str, object]:
    proof = tmp_path / "independent-proof.txt"
    proof.write_text("unit-only independent proof\n", encoding="utf-8")
    reference = evidence_ref(proof)
    arguments = {
        "report_id": "unit-only-domain-admission",
        "scope": SCOPE,
        "realm": REALM,
        "source_report_paths": paths,
        "report_model_tool_identities": ["unit-producer", "unit-verifier"],
        "independence_attestations": [
            {
                "producer_identity": "unit-producer",
                "verifier_identity": "unit-verifier",
                "independent": True,
                "evidence_refs": [reference],
            }
        ],
        "issued_at": "2026-07-23T00:00:00Z",
        "expires_at": "2026-07-24T00:00:00Z",
        "negative_test_refs": [reference],
        "replay_ref": reference,
    }
    preimage = build_domain_research_admission_report(**arguments)
    materialization = _materialization_receipt(
        tmp_path / "materialization.json",
        str(preimage["source_bundle_hash"]),
        str(preimage["materialization_subject_hash"]),
    )
    return build_domain_research_admission_report(
        **arguments,
        materialization_receipt_ref=materialization,
    )


def test_exact_complete_report_replays_and_allows() -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as raw:
        tmp_path = Path(raw)
        report = _report(tmp_path, _source_paths(tmp_path))
        verification = verify_domain_research_admission_report(
            report,
            expected_scope=SCOPE,
            expected_realm=REALM,
            as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
        )

    assert report["decision"] == "ALLOW"
    assert verification["ok"] is True
    assert verification["allowed"] is True
    assert verification["reasons"] == []


def test_materialization_receipt_cannot_be_reused_for_another_report(tmp_path: Path) -> None:
    paths = _source_paths(tmp_path)
    report = _report(tmp_path, paths)
    reused_receipt = dict(report["materialization_receipt_ref"])
    proof = tmp_path / "independent-proof.txt"
    reference = evidence_ref(proof)

    replayed = build_domain_research_admission_report(
        report_id="different-report-id",
        scope=SCOPE,
        realm=REALM,
        source_report_paths=paths,
        report_model_tool_identities=["unit-producer", "unit-verifier"],
        independence_attestations=[
            {
                "producer_identity": "unit-producer",
                "verifier_identity": "unit-verifier",
                "independent": True,
                "evidence_refs": [reference],
            }
        ],
        issued_at="2026-07-23T00:00:00Z",
        expires_at="2026-07-24T00:00:00Z",
        negative_test_refs=[reference],
        replay_ref=reference,
        materialization_receipt_ref=reused_receipt,
    )

    predicates = {item["predicate"]: item["passed"] for item in replayed["predicate_results"]}
    assert replayed["decision"] == "DENY"
    assert predicates["transactional_materialization_bound"] is False


def test_current_route_advisory_materializes_deny_but_replays_exactly(
    tmp_path: Path,
) -> None:
    paths = _source_paths(tmp_path)
    g4 = _source_payload("G4")
    g4.update(
        {
            "schema_version": "xinao.g4.bounded_family_route_advisory.v2",
            "authority": False,
            "g4_full": False,
            "g4_closed": False,
            "completion_claim_allowed": False,
            "terminal": "G4_BOUNDED_FAMILY_ROUTE_READY_NO_OUTCOME_ACCESS",
        }
    )
    _write(paths["G4"], g4)
    g5 = _source_payload("G5")
    g5.update(
        {
            "schema_version": "xinao.g5.statistical_validity_adjudication.v1",
            "authority": False,
            "g5_statistical_validity_ready": False,
            "g5_closed": False,
            "completion_claim_allowed": False,
            "terminal": "G5_STATISTICAL_VALIDITY_HOLD",
        }
    )
    _write(paths["G5"], g5)
    report = _report(tmp_path, paths)
    verification = verify_domain_research_admission_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert report["decision"] == "DENY"
    assert verification["ok"] is True
    assert verification["allowed"] is False
    assert verification["reasons"] == ["report_decision_deny"]
    by_name = {item["predicate"]: item["passed"] for item in report["predicate_results"]}
    assert by_name["foundation_and_g0_g5_ready"] is False


def test_source_tamper_scope_expiry_and_file_hash_fail_closed(tmp_path: Path) -> None:
    paths = _source_paths(tmp_path)
    report = _report(tmp_path, paths)
    report_path = tmp_path / "admission.json"
    _write(report_path, report)
    expected_hash = evidence_ref(report_path)["sha256"]

    wrong_scope = verify_domain_research_admission_file(
        report_path,
        expected_file_sha256=expected_hash,
        expected_scope="another-scope",
        expected_realm=REALM,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    expired = verify_domain_research_admission_file(
        report_path,
        expected_file_sha256=expected_hash,
        expected_scope=SCOPE,
        expected_realm=REALM,
        as_of=datetime(2026, 7, 25, tzinfo=UTC),
    )
    wrong_file_hash = verify_domain_research_admission_file(
        report_path,
        expected_file_sha256="f" * 64,
        expected_scope=SCOPE,
        expected_realm=REALM,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    mutated = json.loads(paths["G3"].read_text(encoding="utf-8"))
    mutated["g3_closed"] = False
    _write(paths["G3"], mutated)
    source_tamper = verify_domain_research_admission_file(
        report_path,
        expected_file_sha256=expected_hash,
        expected_scope=SCOPE,
        expected_realm=REALM,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert wrong_scope["allowed"] is False and "scope_mismatch" in wrong_scope["reasons"]
    assert expired["allowed"] is False and "admission_not_current" in expired["reasons"]
    assert wrong_file_hash["allowed"] is False
    assert "report_file_sha256_mismatch" in wrong_file_hash["reasons"]
    assert source_tamper["allowed"] is False
    assert "report_does_not_replay_exactly" in source_tamper["reasons"]


def test_revocation_and_non_independent_identity_cannot_allow(tmp_path: Path) -> None:
    paths = _source_paths(tmp_path)
    proof = tmp_path / "proof.txt"
    proof.write_text("proof\n", encoding="utf-8")
    reference = evidence_ref(proof)
    revoked = build_domain_research_admission_report(
        report_id="revoked",
        scope=SCOPE,
        realm=REALM,
        source_report_paths=paths,
        report_model_tool_identities=["same", "same"],
        independence_attestations=[
            {
                "producer_identity": "same",
                "verifier_identity": "same",
                "independent": True,
                "evidence_refs": [reference],
            }
        ],
        issued_at="2026-07-23T00:00:00Z",
        expires_at="2026-07-24T00:00:00Z",
        revoked_at="2026-07-23T00:30:00Z",
        revocation_reason="negative test",
        negative_test_refs=[reference],
        replay_ref=reference,
    )

    assert revoked["decision"] == "DENY"
    predicates = {item["predicate"]: item["passed"] for item in revoked["predicate_results"]}
    assert predicates["not_revoked_at_materialization"] is False
    assert predicates["independence_attested"] is False


def test_windows_runtime_refs_replay_through_container_evidence_mount(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    fixture_root = evidence_root / "fixtures"
    fixture_root.mkdir(parents=True)
    paths = _source_paths(fixture_root)
    declared_refs = {
        source_id: rf"D:\XINAO_RESEARCH_RUNTIME\fixtures\{source_id.lower()}.json"
        for source_id in REQUIRED_SOURCE_IDS
    }
    proof = fixture_root / "proof.txt"
    proof.write_text("portable proof\n", encoding="utf-8")
    reference = evidence_ref(proof)
    reference["path"] = r"D:\XINAO_RESEARCH_RUNTIME\fixtures\proof.txt"
    report = build_domain_research_admission_report(
        report_id="portable-admission",
        scope=SCOPE,
        realm=REALM,
        source_report_paths=paths,
        report_model_tool_identities=["producer", "verifier"],
        independence_attestations=[
            {
                "producer_identity": "producer",
                "verifier_identity": "verifier",
                "independent": True,
                "evidence_refs": [reference],
            }
        ],
        issued_at="2026-07-23T00:00:00Z",
        expires_at="2026-07-24T00:00:00Z",
        negative_test_refs=[reference],
        replay_ref=reference,
        _source_report_refs=declared_refs,
        _evidence_root=evidence_root,
    )
    materialization = _materialization_receipt(
        fixture_root / "materialization.json",
        str(report["source_bundle_hash"]),
        str(report["materialization_subject_hash"]),
    )
    materialization["path"] = r"D:\XINAO_RESEARCH_RUNTIME\fixtures\materialization.json"
    report = build_domain_research_admission_report(
        report_id="portable-admission",
        scope=SCOPE,
        realm=REALM,
        source_report_paths=paths,
        report_model_tool_identities=["producer", "verifier"],
        independence_attestations=[
            {
                "producer_identity": "producer",
                "verifier_identity": "verifier",
                "independent": True,
                "evidence_refs": [reference],
            }
        ],
        issued_at="2026-07-23T00:00:00Z",
        expires_at="2026-07-24T00:00:00Z",
        negative_test_refs=[reference],
        replay_ref=reference,
        materialization_receipt_ref=materialization,
        _source_report_refs=declared_refs,
        _evidence_root=evidence_root,
    )

    verification = verify_domain_research_admission_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
        evidence_root=evidence_root,
    )

    assert report["source_reports"]["G5"]["report_ref"].startswith("D:\\")
    assert verification["ok"] is True
    assert verification["allowed"] is True
