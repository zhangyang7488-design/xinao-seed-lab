from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_g8_reproducibility_dimension.py"
SPEC = importlib.util.spec_from_file_location("g8_reproducibility_dimension", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _synthetic_capture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    input_path = capture_root / "task_contract.json"
    artifact_path = capture_root / "uv.lock"
    input_path.write_text('{"work_key":"reproducibility"}\n', encoding="utf-8")
    artifact_path.write_text("version = 1\n", encoding="utf-8")
    source_commit = "9" * 40
    subject_binding = MODULE._subject_binding(
        source_commit=source_commit,
        input_paths={"task_contract": input_path},
        artifact_paths={"uv_lock": artifact_path},
    )
    subject_ref = MODULE._write_json(capture_root / "subject_binding.v1.json", subject_binding)

    lock_receipt = {
        "schema_version": MODULE.LOCK_REPLAY_SCHEMA_VERSION,
        "source_commit_timestamp_command": {
            "argv": ["git", "show", "-s", "--format=%ct", source_commit],
            "returncode": 0,
            "stdout": "1721692800\n",
            "stderr": "",
        },
        "source_date_epoch": "1721692800",
        "environment_overrides": {
            "SOURCE_DATE_EPOCH": "1721692800",
            "UV_PROJECT_ENVIRONMENT": str(capture_root / "removed-environment"),
        },
        "lock_check_command": {
            "argv": MODULE._lock_check_command("uv"),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        },
        "locked_sync_command": {
            "argv": MODULE._locked_sync_command("uv"),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        },
        "working_directory": str(REPO_ROOT),
        "uv_project_environment_was_materialized": True,
        "temporary_environment_removed": True,
        "pyproject_ref": MODULE.evidence_ref(input_path),
        "lockfile_ref": MODULE.evidence_ref(artifact_path),
        "passed": True,
    }
    lock_ref = MODULE._write_json(capture_root / "locked_environment_replay.v1.json", lock_receipt)

    subject = {
        "source_commit": source_commit,
        "input_hashes": subject_binding["input_hashes"],
        "artifact_hashes": subject_binding["artifact_hashes"],
    }
    report_refs = []
    verification_refs = []
    manifest_refs = []
    for ordinal in (1, 2):
        report_path = capture_root / f"report_{ordinal}.json"
        verification_path = capture_root / f"verification_{ordinal}.json"
        manifest_path = capture_root / f"manifest_{ordinal}.json"
        _write(report_path, {"subject": subject, "decision": "DENY"})
        _write(verification_path, {"ok": True, "decision": "DENY"})
        _write(
            manifest_path,
            {
                "g8_closed": False,
                "missing_or_unready_dimensions": list(MODULE.REQUIRED_DIMENSIONS),
            },
        )
        report_refs.append(MODULE.evidence_ref(report_path))
        verification_refs.append(MODULE.evidence_ref(verification_path))
        manifest_refs.append(MODULE.evidence_ref(manifest_path))
    replay_receipt = {
        "schema_version": MODULE.REPORT_REPLAY_SCHEMA_VERSION,
        "process_refs": [],
        "report_refs": report_refs,
        "verification_refs": verification_refs,
        "manifest_refs": manifest_refs,
        "report_files_equal": True,
        "report_content_hashes_equal": True,
        "all_verifications_ok": True,
        "all_decisions_deny": True,
        "all_g8_open": True,
        "all_six_dimensions_missing": True,
        "passed": True,
    }
    replay_ref = MODULE._write_json(capture_root / "report_exact_replay.v1.json", replay_receipt)
    rollback_ref = MODULE._write_json(
        capture_root / "rollback.v1.json",
        {
            "schema_version": MODULE.ROLLBACK_SCHEMA_VERSION,
            "scope": str(capture_root),
            "rollback_action": "remove exact test root",
            "source_or_runtime_mutation_required": False,
            "temporary_locked_environment_removed": True,
        },
    )
    now = datetime.now(UTC)
    issued_at = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    expires_at = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    capture = {
        "schema_version": MODULE.CAPTURE_SCHEMA_VERSION,
        "source_commit": source_commit,
        "scope": "xinao-domain-mainline",
        "realm": "DOMAIN_FIXED_AXIOM",
        "issued_at": issued_at,
        "expires_at": expires_at,
        "subject": subject,
        "subject_binding_ref": subject_ref,
        "check_evidence_refs": {
            "locked_environment_replayed": lock_ref,
            "report_replayed_exactly": replay_ref,
            "subject_inputs_hash_bound": subject_ref,
        },
        "rollback_ref": rollback_ref,
        "capture_ready_for_independent_review": True,
        "g8_closed": False,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
    }
    capture_path = capture_root / "capture_manifest.v1.json"
    _write(capture_path, capture)
    review = {
        "schema_version": MODULE.INDEPENDENT_REVIEW_SCHEMA_VERSION,
        "capture_manifest_ref": MODULE.evidence_ref(capture_path),
        "reviewer_identity": "independent-test-reviewer",
        "verdict": "PASS",
        "verified_check_ids": list(MODULE.REQUIRED_CHECKS),
        "nonclaims": {
            "g8_closed": False,
            "live_shadow_ready": False,
            "parent_complete": False,
        },
    }
    review_path = tmp_path / "independent_review.v1.json"
    _write(review_path, review)
    return capture_path, review_path, issued_at, expires_at


def test_finalization_makes_only_reproducibility_ready(tmp_path: Path) -> None:
    capture_path, review_path, issued_at, expires_at = _synthetic_capture(tmp_path)
    output_root = tmp_path / "final"
    output_root.mkdir()

    result = MODULE.finalize(
        output_root=output_root,
        capture_path=capture_path,
        review_path=review_path,
        producer_identity="test-producer",
        issued_at=issued_at,
        expires_at=expires_at,
    )

    report = json.loads(
        (output_root / "consumer" / "operational_assurance_report.v1.json").read_text()
    )
    sources = report["dimension_sources"]
    assert result["classification"] == "DIMENSION_CLOSURE_CANDIDATE"
    assert result["reproducibility_ready"] is True
    assert sources["reproducibility"]["ready"] is True
    assert all(
        source["ready"] is False
        for dimension, source in sources.items()
        if dimension != "reproducibility"
    )
    assert result["decision"] == "DENY"
    assert result["g8_closed"] is False
    assert result["live_shadow_claim_allowed"] is False
    assert result["parent_complete"] is False


def test_tampered_subject_file_invalidates_capture(tmp_path: Path) -> None:
    capture_path, _, _, _ = _synthetic_capture(tmp_path)
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    subject_binding_path = Path(capture["subject_binding_ref"]["path"])
    subject_binding = json.loads(subject_binding_path.read_text(encoding="utf-8"))
    input_path = Path(subject_binding["input_refs"]["task_contract"]["path"])
    input_path.write_text('{"work_key":"tampered"}\n', encoding="utf-8")

    with pytest.raises(SystemExit, match="subject task_contract evidence ref is invalid"):
        MODULE._verify_capture(capture_path)


def test_review_must_be_separate_complete_and_nonclaiming(tmp_path: Path) -> None:
    capture_path, review_path, _, _ = _synthetic_capture(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviewer_identity"] = "test-producer"
    review["verified_check_ids"] = ["ci_green", "codeql_green"]
    review["nonclaims"]["g8_closed"] = True
    _write(review_path, review)

    with pytest.raises(SystemExit, match="independent review is not admissible"):
        MODULE._verify_independent_review(
            review_path,
            capture_ref=MODULE.evidence_ref(capture_path),
            producer_identity="test-producer",
        )


def test_locked_replay_command_is_fixed_and_frozen() -> None:
    assert MODULE._lock_check_command("uv") == ["uv", "lock", "--check"]
    assert MODULE._locked_sync_command("uv") == [
        "uv",
        "sync",
        "--frozen",
        "--extra",
        "dev",
        "--extra",
        "workflow",
    ]
