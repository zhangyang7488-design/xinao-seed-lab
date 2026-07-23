from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from xinao.assurance import (
    REQUIRED_DIMENSION_CHECKS,
    build_operational_assurance_dimension_evidence,
    build_operational_assurance_report,
    evidence_ref,
    verify_operational_assurance_file,
    verify_operational_assurance_report,
)
from xinao.canonical import canonical_sha256

SCOPE = "xinao-domain-mainline"
REALM = "DOMAIN_FIXED_AXIOM"
SOURCE_COMMIT = "9" * 40
INPUT_HASHES = {"contract": "a" * 64, "dataset": "b" * 64}
ARTIFACT_HASHES = {"lockfile": "c" * 64, "runtime": "d" * 64}
ISSUED_AT = "2026-07-23T00:00:00Z"
EXPIRES_AT = "2026-07-24T00:00:00Z"


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _proofs(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    proof = tmp_path / "proof.txt"
    rollback = tmp_path / "rollback.txt"
    proof.write_text("independent evidence\n", encoding="utf-8")
    rollback.write_text("bounded rollback\n", encoding="utf-8")
    return evidence_ref(proof), evidence_ref(rollback)


def _check_results(
    dimension: str,
    proof_ref: dict[str, object],
    rollback_ref: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "check_id": check_id,
            "outcome": "PASS",
            "evidence_refs": [proof_ref],
            "rollback_ref": rollback_ref,
        }
        for check_id in REQUIRED_DIMENSION_CHECKS[dimension]
    ]


def _dimension_paths(tmp_path: Path) -> tuple[dict[str, Path], dict[str, object]]:
    proof_ref, rollback_ref = _proofs(tmp_path)
    paths: dict[str, Path] = {}
    for dimension in REQUIRED_DIMENSION_CHECKS:
        payload = build_operational_assurance_dimension_evidence(
            dimension=dimension,
            scope=SCOPE,
            realm=REALM,
            source_commit=SOURCE_COMMIT,
            input_hashes=INPUT_HASHES,
            artifact_hashes=ARTIFACT_HASHES,
            status="VERIFIED",
            producer_identity=f"{dimension}-producer",
            verifier_identity=f"{dimension}-verifier",
            independence_evidence_ref=proof_ref,
            issued_at=ISSUED_AT,
            expires_at=EXPIRES_AT,
            check_results=_check_results(dimension, proof_ref, rollback_ref),
        )
        path = tmp_path / f"{dimension}.json"
        _write(path, payload)
        paths[dimension] = path
    return paths, proof_ref


def _report(tmp_path: Path) -> dict[str, object]:
    paths, proof_ref = _dimension_paths(tmp_path)
    return build_operational_assurance_report(
        report_id="unit-g8-report",
        scope=SCOPE,
        realm=REALM,
        source_commit=SOURCE_COMMIT,
        input_hashes=INPUT_HASHES,
        artifact_hashes=ARTIFACT_HASHES,
        dimension_evidence_paths=paths,
        producer_identity="report-producer",
        verifier_identity="report-verifier",
        independence_evidence_ref=proof_ref,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
    )


def test_exact_six_dimension_report_replays_and_is_ready(tmp_path: Path) -> None:
    report = _report(tmp_path)
    verification = verify_operational_assurance_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert report["decision"] == "READY"
    assert verification["ok"] is True
    assert verification["ready"] is True
    assert verification["reasons"] == []


def test_missing_dimensions_materialize_replayable_deny(tmp_path: Path) -> None:
    proof_ref, _ = _proofs(tmp_path)
    report = build_operational_assurance_report(
        report_id="current-gap",
        scope=SCOPE,
        realm=REALM,
        source_commit=SOURCE_COMMIT,
        input_hashes=INPUT_HASHES,
        artifact_hashes=ARTIFACT_HASHES,
        dimension_evidence_paths={},
        producer_identity="report-producer",
        verifier_identity="report-verifier",
        independence_evidence_ref=proof_ref,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
    )
    verification = verify_operational_assurance_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert report["decision"] == "DENY"
    assert verification["ok"] is True
    assert verification["ready"] is False
    assert verification["reasons"] == ["report_decision_deny"]
    assert all(
        source["failures"] == ["dimension_evidence_missing"]
        for source in report["dimension_sources"].values()
    )


def test_source_tamper_scope_expiry_and_file_hash_fail_closed(tmp_path: Path) -> None:
    report = _report(tmp_path)
    report_path = tmp_path / "report.json"
    _write(report_path, report)
    expected_hash = evidence_ref(report_path)["sha256"]

    wrong_scope = verify_operational_assurance_file(
        report_path,
        expected_file_sha256=str(expected_hash),
        expected_scope="another-scope",
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    expired = verify_operational_assurance_file(
        report_path,
        expected_file_sha256=str(expected_hash),
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 25, tzinfo=UTC),
    )
    wrong_file_hash = verify_operational_assurance_file(
        report_path,
        expected_file_sha256="f" * 64,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    dimension_path = Path(
        report["dimension_sources"]["security_negative"]["evidence_ref"]  # type: ignore[index]
    )
    mutated = json.loads(dimension_path.read_text(encoding="utf-8"))
    mutated["status"] = "FAILED"
    _write(dimension_path, mutated)
    tampered_source = verify_operational_assurance_file(
        report_path,
        expected_file_sha256=str(expected_hash),
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert wrong_scope["ready"] is False and "scope_mismatch" in wrong_scope["reasons"]
    assert expired["ready"] is False
    assert "operational_assurance_not_current" in expired["reasons"]
    assert wrong_file_hash["ready"] is False
    assert "report_file_sha256_mismatch" in wrong_file_hash["reasons"]
    assert tampered_source["ready"] is False
    assert "report_does_not_replay_exactly" in tampered_source["reasons"]


def test_dimension_requires_exact_negative_matrix_rollbacks_and_independence(
    tmp_path: Path,
) -> None:
    proof_ref, rollback_ref = _proofs(tmp_path)
    checks = _check_results("security_negative", proof_ref, rollback_ref)
    checks.pop()
    checks[0]["rollback_ref"] = {"path": "missing", "sha256": "0" * 64, "size_bytes": 1}
    payload = build_operational_assurance_dimension_evidence(
        dimension="security_negative",
        scope=SCOPE,
        realm=REALM,
        source_commit=SOURCE_COMMIT,
        input_hashes=INPUT_HASHES,
        artifact_hashes=ARTIFACT_HASHES,
        status="VERIFIED",
        producer_identity="same",
        verifier_identity="same",
        independence_evidence_ref=proof_ref,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        check_results=checks,
    )
    path = tmp_path / "security.json"
    _write(path, payload)
    report = build_operational_assurance_report(
        report_id="negative-matrix-gap",
        scope=SCOPE,
        realm=REALM,
        source_commit=SOURCE_COMMIT,
        input_hashes=INPUT_HASHES,
        artifact_hashes=ARTIFACT_HASHES,
        dimension_evidence_paths={"security_negative": path},
        producer_identity="report-producer",
        verifier_identity="report-verifier",
        independence_evidence_ref=proof_ref,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
    )

    source = report["dimension_sources"]["security_negative"]
    assert report["decision"] == "DENY"
    assert source["ready"] is False
    assert "dimension_check_inventory_mismatch" in source["failures"]
    assert "dimension_independence_invalid" in source["failures"]
    assert any(reason.startswith("dimension_rollback_invalid:") for reason in source["failures"])


def test_g8_never_claims_live_shadow_or_parent_completion(tmp_path: Path) -> None:
    report = _report(tmp_path)
    verification = verify_operational_assurance_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert report["g8_operational_assurance_ready"] is True
    assert report["live_shadow_claim_allowed"] is False
    assert report["parent_completion_claim_allowed"] is False
    assert verification["live_shadow_claim_allowed"] is False
    assert verification["parent_completion_claim_allowed"] is False


def test_report_revocation_invalidates_ready_report(tmp_path: Path) -> None:
    report = _report(tmp_path)
    report["revoked_at"] = "2026-07-23T00:30:00Z"
    report["revocation_reason"] = "independent verifier withdrew the evidence"
    body = dict(report)
    body.pop("content_hash")
    report["content_hash"] = canonical_sha256(body)

    verification = verify_operational_assurance_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )

    assert verification["ok"] is False
    assert verification["ready"] is False
    assert "operational_assurance_revoked" in verification["reasons"]
    assert "report_does_not_replay_exactly" in verification["reasons"]


def test_dimension_expiry_invalidates_still_current_ready_report(tmp_path: Path) -> None:
    paths, proof_ref = _dimension_paths(tmp_path)
    capacity = json.loads(paths["capacity"].read_text(encoding="utf-8"))
    capacity["expires_at"] = "2026-07-23T02:00:00Z"
    capacity_body = dict(capacity)
    capacity_body.pop("content_hash")
    capacity["content_hash"] = canonical_sha256(capacity_body)
    _write(paths["capacity"], capacity)
    report = build_operational_assurance_report(
        report_id="dimension-expires-first",
        scope=SCOPE,
        realm=REALM,
        source_commit=SOURCE_COMMIT,
        input_hashes=INPUT_HASHES,
        artifact_hashes=ARTIFACT_HASHES,
        dimension_evidence_paths=paths,
        producer_identity="report-producer",
        verifier_identity="report-verifier",
        independence_evidence_ref=proof_ref,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
    )

    verification = verify_operational_assurance_report(
        report,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 3, tzinfo=UTC),
    )

    assert report["decision"] == "READY"
    assert verification["ok"] is False
    assert verification["ready"] is False
    assert (
        "dimension_revalidation_failed:capacity:dimension_evidence_not_current"
        in verification["reasons"]
    )


def test_malformed_subject_and_unexpected_dimension_fields_fail_closed(tmp_path: Path) -> None:
    paths, proof_ref = _dimension_paths(tmp_path)
    security = json.loads(paths["security_negative"].read_text(encoding="utf-8"))
    security["free_form_pass"] = True
    security["content_hash"] = ""
    security_body = dict(security)
    security_body.pop("content_hash")
    security["content_hash"] = canonical_sha256(security_body)
    _write(paths["security_negative"], security)
    report = build_operational_assurance_report(
        report_id="unexpected-field",
        scope=SCOPE,
        realm=REALM,
        source_commit=SOURCE_COMMIT,
        input_hashes=INPUT_HASHES,
        artifact_hashes=ARTIFACT_HASHES,
        dimension_evidence_paths=paths,
        producer_identity="report-producer",
        verifier_identity="report-verifier",
        independence_evidence_ref=proof_ref,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
    )
    security_source = report["dimension_sources"]["security_negative"]
    assert report["decision"] == "DENY"
    assert "dimension_evidence_fields_invalid" in security_source["failures"]

    malformed = dict(report)
    malformed["subject"] = ["not", "a", "mapping"]
    verification = verify_operational_assurance_report(
        malformed,
        expected_scope=SCOPE,
        expected_realm=REALM,
        expected_source_commit=SOURCE_COMMIT,
        as_of=datetime(2026, 7, 23, 1, tzinfo=UTC),
    )
    assert verification["ok"] is False
    assert verification["ready"] is False
    assert "source_commit_mismatch" in verification["reasons"]
