"""Capture and finalize one real, fail-closed G8 reproducibility dimension.

``capture`` performs a frozen uv environment replay, materializes the same G8
report in two fresh Python processes, and binds every declared subject input to
its current file hash. ``finalize`` requires a separately produced review of
that capture before it emits dimension evidence and runs the existing G8
consumer. A successful finalization still leaves G8 DENY unless all other
operational-assurance dimensions are independently ready.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
PREFLIGHT_SCRIPT = REPO_ROOT / "scripts" / "run_g8_operational_assurance_preflight.py"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.assurance import (  # noqa: E402
    REQUIRED_DIMENSIONS,
    build_operational_assurance_dimension_evidence,
    evidence_ref,
)

CAPTURE_SCHEMA_VERSION = "xinao.g8_reproducibility_capture.v1"
INDEPENDENT_REVIEW_SCHEMA_VERSION = "xinao.g8_reproducibility_independent_review.v1"
FINALIZATION_SCHEMA_VERSION = "xinao.g8_reproducibility_finalization.v1"
SUBJECT_BINDING_SCHEMA_VERSION = "xinao.g8_reproducibility_subject_binding.v1"
LOCK_REPLAY_SCHEMA_VERSION = "xinao.g8_locked_environment_replay.v1"
REPORT_REPLAY_SCHEMA_VERSION = "xinao.g8_report_exact_replay.v1"
ROLLBACK_SCHEMA_VERSION = "xinao.g8_reproducibility_rollback.v1"
REQUIRED_CHECKS = (
    "locked_environment_replayed",
    "report_replayed_exactly",
    "subject_inputs_hash_bound",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return evidence_ref(path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _valid_ref(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    raw_path = value.get("path")
    expected_hash = value.get("sha256")
    expected_size = value.get("size_bytes")
    if (
        not isinstance(raw_path, str)
        or not isinstance(expected_hash, str)
        or _SHA256_RE.fullmatch(expected_hash) is None
        or not isinstance(expected_size, int)
    ):
        return False
    path = Path(raw_path)
    return (
        path.is_file() and path.stat().st_size == expected_size and _sha256(path) == expected_hash
    )


def _new_root(path: Path, runtime_root: Path) -> Path:
    resolved = path.resolve()
    allowed = runtime_root.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise SystemExit(f"output root must remain under runtime root: {allowed}") from exc
    if resolved.exists() and any(resolved.iterdir()):
        raise SystemExit("output root must be new or empty")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _bindings(values: Sequence[str], *, label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        key, separator, path_text = raw.partition("=")
        if not separator or not key or not path_text or key in result:
            raise SystemExit(f"{label} must use unique KEY=PATH entries")
        path = Path(path_text).resolve()
        if not path.is_file():
            raise SystemExit(f"{label} path is not a file: {path}")
        result[key] = path
    if not result:
        raise SystemExit(f"{label} requires at least one KEY=PATH entry")
    return dict(sorted(result.items()))


def _subject_binding(
    *,
    source_commit: str,
    input_paths: Mapping[str, Path],
    artifact_paths: Mapping[str, Path],
) -> dict[str, Any]:
    return {
        "schema_version": SUBJECT_BINDING_SCHEMA_VERSION,
        "source_commit": source_commit,
        "input_refs": {key: evidence_ref(path) for key, path in input_paths.items()},
        "artifact_refs": {key: evidence_ref(path) for key, path in artifact_paths.items()},
        "input_hashes": {key: _sha256(path) for key, path in input_paths.items()},
        "artifact_hashes": {key: _sha256(path) for key, path in artifact_paths.items()},
    }


def _lock_check_command(uv_executable: str) -> list[str]:
    return [uv_executable, "lock", "--check"]


def _locked_sync_command(uv_executable: str) -> list[str]:
    return [
        uv_executable,
        "sync",
        "--frozen",
        "--extra",
        "dev",
        "--extra",
        "workflow",
    ]


def _process_receipt(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "argv": [str(item) for item in completed.args],
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _preflight_command(
    *,
    op_root: Path,
    runtime_root: Path,
    report_id: str,
    scope: str,
    realm: str,
    source_commit: str,
    input_hashes: Mapping[str, str],
    artifact_hashes: Mapping[str, str],
    independence_evidence: Path,
    issued_at: str,
    expires_at: str,
    dimension_evidence: Path | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(PREFLIGHT_SCRIPT),
        "--op-root",
        str(op_root),
        "--runtime-root",
        str(runtime_root),
        "--report-id",
        report_id,
        "--scope",
        scope,
        "--realm",
        realm,
        "--source-commit",
        source_commit,
    ]
    for key, value in sorted(input_hashes.items()):
        command.extend(["--input-hash", f"{key}={value}"])
    for key, value in sorted(artifact_hashes.items()):
        command.extend(["--artifact-hash", f"{key}={value}"])
    if dimension_evidence is not None:
        command.extend(["--dimension-evidence", f"reproducibility={dimension_evidence}"])
    command.extend(
        [
            "--producer-identity",
            "codex-owner-g8-reproducibility-event438",
            "--verifier-identity",
            "g8-operational-assurance-consumer-v1",
            "--independence-evidence",
            str(independence_evidence),
            "--issued-at",
            issued_at,
            "--expires-at",
            expires_at,
        ]
    )
    return command


def capture(
    *,
    output_root: Path,
    source_commit: str,
    scope: str,
    realm: str,
    input_paths: Mapping[str, Path],
    artifact_paths: Mapping[str, Path],
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    subject = _subject_binding(
        source_commit=source_commit,
        input_paths=input_paths,
        artifact_paths=artifact_paths,
    )
    subject_ref = _write_json(output_root / "subject_binding.v1.json", subject)

    uv_executable = shutil.which("uv")
    if not uv_executable:
        raise SystemExit("uv executable is required for locked environment replay")
    source_epoch_process = subprocess.run(
        ["git", "show", "-s", "--format=%ct", source_commit],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    source_date_epoch = source_epoch_process.stdout.strip()
    if (
        source_epoch_process.returncode != 0
        or not source_date_epoch
        or not source_date_epoch.isdecimal()
    ):
        raise SystemExit("source commit timestamp could not be resolved")
    scratch_root = output_root / "_scratch"
    scratch_root.mkdir()
    with tempfile.TemporaryDirectory(prefix="locked-env-", dir=scratch_root) as temporary:
        locked_environment = Path(temporary) / "environment"
        environment = os.environ.copy()
        environment["UV_PROJECT_ENVIRONMENT"] = str(locked_environment)
        environment["SOURCE_DATE_EPOCH"] = source_date_epoch
        lock_check = subprocess.run(
            _lock_check_command(uv_executable),
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        locked_sync = subprocess.run(
            _locked_sync_command(uv_executable),
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        environment_materialized = locked_environment.is_dir()
    scratch_root.rmdir()
    lock_receipt = {
        "schema_version": LOCK_REPLAY_SCHEMA_VERSION,
        "source_commit_timestamp_command": _process_receipt(source_epoch_process),
        "source_date_epoch": source_date_epoch,
        "environment_overrides": {
            "SOURCE_DATE_EPOCH": source_date_epoch,
            "UV_PROJECT_ENVIRONMENT": str(locked_environment),
        },
        "lock_check_command": _process_receipt(lock_check),
        "locked_sync_command": _process_receipt(locked_sync),
        "working_directory": str(REPO_ROOT),
        "uv_project_environment_was_materialized": environment_materialized,
        "temporary_environment_removed": not locked_environment.exists(),
        "pyproject_ref": evidence_ref(REPO_ROOT / "pyproject.toml"),
        "lockfile_ref": evidence_ref(REPO_ROOT / "uv.lock"),
        "passed": lock_check.returncode == 0
        and locked_sync.returncode == 0
        and environment_materialized
        and not locked_environment.exists(),
    }
    lock_ref = _write_json(output_root / "locked_environment_replay.v1.json", lock_receipt)
    if lock_receipt["passed"] is not True:
        raise SystemExit("frozen uv environment replay failed")

    replay_seed = {
        "schema_version": "xinao.g8_report_replay_seed.v1",
        "purpose": "Same fixed input is materialized in two fresh Python processes.",
        "authority": False,
        "completion_claim": False,
    }
    replay_seed_path = output_root / "report_replay_seed.v1.json"
    _write_json(replay_seed_path, replay_seed)
    replay_process_refs: list[dict[str, Any]] = []
    replay_results: list[dict[str, Any]] = []
    replay_roots: list[Path] = []
    for ordinal in (1, 2):
        replay_root = output_root / f"report_replay_{ordinal}"
        command = _preflight_command(
            op_root=replay_root,
            runtime_root=output_root,
            report_id="g8-reproducibility-exact-replay",
            scope=scope,
            realm=realm,
            source_commit=source_commit,
            input_hashes=subject["input_hashes"],
            artifact_hashes=subject["artifact_hashes"],
            independence_evidence=replay_seed_path,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        replay_completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        process_ref = _write_json(
            output_root / f"report_replay_{ordinal}_process.v1.json",
            _process_receipt(replay_completed),
        )
        if replay_completed.returncode != 0:
            raise SystemExit(f"report replay process {ordinal} failed")
        try:
            result = json.loads(replay_completed.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"report replay process {ordinal} returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise SystemExit(f"report replay process {ordinal} returned a non-object")
        replay_process_refs.append(process_ref)
        replay_results.append(result)
        replay_roots.append(replay_root)

    report_paths = [
        replay_root / "operational_assurance_report.v1.json" for replay_root in replay_roots
    ]
    verification_paths = [
        replay_root / "operational_assurance_verification.v1.json" for replay_root in replay_roots
    ]
    manifest_paths = [replay_root / "run_manifest.v1.json" for replay_root in replay_roots]
    reports = [_load_json(path) for path in report_paths]
    verifications = [_load_json(path) for path in verification_paths]
    manifests = [_load_json(path) for path in manifest_paths]
    expected_missing = sorted(REQUIRED_DIMENSIONS)
    report_replay = {
        "schema_version": REPORT_REPLAY_SCHEMA_VERSION,
        "process_refs": replay_process_refs,
        "report_refs": [evidence_ref(path) for path in report_paths],
        "verification_refs": [evidence_ref(path) for path in verification_paths],
        "manifest_refs": [evidence_ref(path) for path in manifest_paths],
        "report_files_equal": report_paths[0].read_bytes() == report_paths[1].read_bytes(),
        "report_content_hashes_equal": reports[0].get("content_hash")
        == reports[1].get("content_hash"),
        "all_verifications_ok": all(item.get("ok") is True for item in verifications),
        "all_decisions_deny": all(item.get("decision") == "DENY" for item in replay_results),
        "all_g8_open": all(item.get("g8_closed") is False for item in replay_results),
        "all_six_dimensions_missing": all(
            sorted(item.get("missing_or_unready_dimensions", [])) == expected_missing
            for item in manifests
        ),
    }
    report_replay["passed"] = all(
        report_replay[key] is True
        for key in (
            "report_files_equal",
            "report_content_hashes_equal",
            "all_verifications_ok",
            "all_decisions_deny",
            "all_g8_open",
            "all_six_dimensions_missing",
        )
    )
    report_replay_ref = _write_json(output_root / "report_exact_replay.v1.json", report_replay)
    if report_replay["passed"] is not True:
        raise SystemExit("two-process report replay did not reproduce exactly")

    rollback = {
        "schema_version": ROLLBACK_SCHEMA_VERSION,
        "scope": str(output_root),
        "rollback_action": "Remove only this newly created capture root after exact-path review.",
        "source_or_runtime_mutation_required": False,
        "temporary_locked_environment_removed": True,
    }
    rollback_ref = _write_json(output_root / "rollback.v1.json", rollback)
    capture_manifest = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "source_commit": source_commit,
        "scope": scope,
        "realm": realm,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "subject": {
            "source_commit": source_commit,
            "input_hashes": subject["input_hashes"],
            "artifact_hashes": subject["artifact_hashes"],
        },
        "subject_binding_ref": subject_ref,
        "check_evidence_refs": {
            "locked_environment_replayed": lock_ref,
            "report_replayed_exactly": report_replay_ref,
            "subject_inputs_hash_bound": subject_ref,
        },
        "rollback_ref": rollback_ref,
        "capture_ready_for_independent_review": True,
        "g8_closed": False,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
    }
    capture_ref = _write_json(output_root / "capture_manifest.v1.json", capture_manifest)
    return {
        "capture_ready_for_independent_review": True,
        "capture_manifest_ref": capture_ref,
        "g8_closed": False,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
    }


def _require_valid_ref(value: object, *, label: str) -> dict[str, Any]:
    if not _valid_ref(value):
        raise SystemExit(f"{label} evidence ref is invalid")
    return dict(value)  # type: ignore[arg-type]


def _verify_capture(capture_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    capture_ref = evidence_ref(capture_path)
    capture = _load_json(capture_path)
    if capture.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise SystemExit("capture schema mismatch")
    if capture.get("capture_ready_for_independent_review") is not True:
        raise SystemExit("capture is not ready for independent review")
    source_commit = str(capture.get("source_commit") or "")
    if _GIT_COMMIT_RE.fullmatch(source_commit) is None:
        raise SystemExit("capture source commit is invalid")
    subject = capture.get("subject")
    if not isinstance(subject, Mapping) or dict(subject).get("source_commit") != source_commit:
        raise SystemExit("capture subject is invalid")

    subject_ref = _require_valid_ref(capture.get("subject_binding_ref"), label="subject binding")
    subject_binding = _load_json(Path(subject_ref["path"]))
    if subject_binding.get("schema_version") != SUBJECT_BINDING_SCHEMA_VERSION:
        raise SystemExit("subject binding schema mismatch")
    for ref_group, hash_group in (
        ("input_refs", "input_hashes"),
        ("artifact_refs", "artifact_hashes"),
    ):
        refs = subject_binding.get(ref_group)
        hashes = subject_binding.get(hash_group)
        if not isinstance(refs, Mapping) or not isinstance(hashes, Mapping) or not refs:
            raise SystemExit(f"subject binding {ref_group} is invalid")
        if set(refs) != set(hashes):
            raise SystemExit(f"subject binding {ref_group} inventory mismatch")
        for key, raw_ref in refs.items():
            checked_ref = _require_valid_ref(raw_ref, label=f"subject {key}")
            if checked_ref["sha256"] != hashes[key]:
                raise SystemExit(f"subject binding hash mismatch: {key}")
    if dict(subject) != {
        "source_commit": source_commit,
        "input_hashes": subject_binding["input_hashes"],
        "artifact_hashes": subject_binding["artifact_hashes"],
    }:
        raise SystemExit("capture subject does not match bound files")

    check_refs = capture.get("check_evidence_refs")
    if not isinstance(check_refs, Mapping) or set(check_refs) != set(REQUIRED_CHECKS):
        raise SystemExit("capture check inventory mismatch")
    checked_refs = {
        check_id: _require_valid_ref(check_refs[check_id], label=check_id)
        for check_id in REQUIRED_CHECKS
    }
    lock_receipt = _load_json(Path(checked_refs["locked_environment_replayed"]["path"]))
    expected_lock_check_tail = ["lock", "--check"]
    expected_sync_tail = ["sync", "--frozen", "--extra", "dev", "--extra", "workflow"]
    source_epoch_command = lock_receipt.get("source_commit_timestamp_command")
    lock_check = lock_receipt.get("lock_check_command")
    locked_sync = lock_receipt.get("locked_sync_command")
    source_epoch_argv = (
        source_epoch_command.get("argv") if isinstance(source_epoch_command, Mapping) else None
    )
    lock_argv = lock_check.get("argv") if isinstance(lock_check, Mapping) else None
    sync_argv = locked_sync.get("argv") if isinstance(locked_sync, Mapping) else None
    source_date_epoch = lock_receipt.get("source_date_epoch")
    environment_overrides = lock_receipt.get("environment_overrides")
    if (
        lock_receipt.get("schema_version") != LOCK_REPLAY_SCHEMA_VERSION
        or lock_receipt.get("passed") is not True
        or not isinstance(source_date_epoch, str)
        or not source_date_epoch.isdecimal()
        or source_epoch_argv != ["git", "show", "-s", "--format=%ct", source_commit]
        or source_epoch_command.get("returncode") != 0
        or str(source_epoch_command.get("stdout") or "").strip() != source_date_epoch
        or not isinstance(environment_overrides, Mapping)
        or environment_overrides.get("SOURCE_DATE_EPOCH") != source_date_epoch
        or not isinstance(lock_argv, list)
        or lock_argv[1:] != expected_lock_check_tail
        or lock_check.get("returncode") != 0
        or not isinstance(sync_argv, list)
        or sync_argv[1:] != expected_sync_tail
        or locked_sync.get("returncode") != 0
        or lock_receipt.get("uv_project_environment_was_materialized") is not True
        or lock_receipt.get("temporary_environment_removed") is not True
        or not _valid_ref(lock_receipt.get("pyproject_ref"))
        or not _valid_ref(lock_receipt.get("lockfile_ref"))
    ):
        raise SystemExit("locked environment replay receipt is invalid")

    replay = _load_json(Path(checked_refs["report_replayed_exactly"]["path"]))
    replay_bools = (
        "passed",
        "report_files_equal",
        "report_content_hashes_equal",
        "all_verifications_ok",
        "all_decisions_deny",
        "all_g8_open",
        "all_six_dimensions_missing",
    )
    if replay.get("schema_version") != REPORT_REPLAY_SCHEMA_VERSION or not all(
        replay.get(key) is True for key in replay_bools
    ):
        raise SystemExit("report replay receipt is invalid")
    report_refs = replay.get("report_refs")
    verification_refs = replay.get("verification_refs")
    manifest_refs = replay.get("manifest_refs")
    if not all(
        isinstance(group, list) and len(group) == 2 and all(_valid_ref(item) for item in group)
        for group in (report_refs, verification_refs, manifest_refs)
    ):
        raise SystemExit("report replay evidence refs are invalid")
    report_paths = [Path(item["path"]) for item in report_refs]
    reports = [_load_json(path) for path in report_paths]
    if report_paths[0].read_bytes() != report_paths[1].read_bytes() or any(
        report.get("subject") != dict(subject) for report in reports
    ):
        raise SystemExit("report replay subject or bytes no longer match")

    rollback_ref = _require_valid_ref(capture.get("rollback_ref"), label="rollback")
    return capture, {
        "capture_ref": capture_ref,
        "check_refs": checked_refs,
        "rollback_ref": rollback_ref,
    }


def _verify_independent_review(
    review_path: Path,
    *,
    capture_ref: Mapping[str, Any],
    producer_identity: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    review_ref = evidence_ref(review_path)
    review = _load_json(review_path)
    declared_capture = review.get("capture_manifest_ref")
    reviewer_identity = str(review.get("reviewer_identity") or "")
    if (
        review.get("schema_version") != INDEPENDENT_REVIEW_SCHEMA_VERSION
        or review.get("verdict") != "PASS"
        or not isinstance(declared_capture, Mapping)
        or dict(declared_capture) != dict(capture_ref)
        or not reviewer_identity
        or reviewer_identity == producer_identity
        or set(review.get("verified_check_ids") or []) != set(REQUIRED_CHECKS)
    ):
        raise SystemExit("independent review is not admissible")
    nonclaims = review.get("nonclaims")
    if not isinstance(nonclaims, Mapping) or any(
        nonclaims.get(key) is not False
        for key in ("g8_closed", "live_shadow_ready", "parent_complete")
    ):
        raise SystemExit("independent review contains an invalid completion claim")
    return review, review_ref


def finalize(
    *,
    output_root: Path,
    capture_path: Path,
    review_path: Path,
    producer_identity: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    capture, verified = _verify_capture(capture_path)
    review, review_ref = _verify_independent_review(
        review_path,
        capture_ref=verified["capture_ref"],
        producer_identity=producer_identity,
    )
    subject = dict(capture["subject"])
    check_results = [
        {
            "check_id": check_id,
            "outcome": "PASS",
            "evidence_refs": [verified["check_refs"][check_id]],
            "rollback_ref": verified["rollback_ref"],
        }
        for check_id in REQUIRED_CHECKS
    ]
    dimension = build_operational_assurance_dimension_evidence(
        dimension="reproducibility",
        scope=str(capture["scope"]),
        realm=str(capture["realm"]),
        source_commit=str(subject["source_commit"]),
        input_hashes=dict(subject["input_hashes"]),
        artifact_hashes=dict(subject["artifact_hashes"]),
        status="VERIFIED",
        producer_identity=producer_identity,
        verifier_identity=str(review["reviewer_identity"]),
        independence_evidence_ref=review_ref,
        issued_at=issued_at,
        expires_at=expires_at,
        check_results=check_results,
    )
    dimension_path = output_root / "reproducibility_dimension_evidence.v1.json"
    dimension_ref = _write_json(dimension_path, dimension)

    consumer_root = output_root / "consumer"
    command = _preflight_command(
        op_root=consumer_root,
        runtime_root=output_root,
        report_id="g8-reproducibility-dimension-consumer",
        scope=str(capture["scope"]),
        realm=str(capture["realm"]),
        source_commit=str(subject["source_commit"]),
        input_hashes=dict(subject["input_hashes"]),
        artifact_hashes=dict(subject["artifact_hashes"]),
        independence_evidence=review_path,
        issued_at=issued_at,
        expires_at=expires_at,
        dimension_evidence=dimension_path,
    )
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    consumer_process_ref = _write_json(
        output_root / "consumer_process.v1.json", _process_receipt(completed)
    )
    if completed.returncode != 0:
        raise SystemExit("G8 consumer rejected the reproducibility evidence")
    try:
        consumer_result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("G8 consumer returned invalid JSON") from exc
    expected_missing = sorted(set(REQUIRED_DIMENSIONS) - {"reproducibility"})
    report_path = consumer_root / "operational_assurance_report.v1.json"
    report = _load_json(report_path)
    sources = report.get("dimension_sources")
    if (
        not isinstance(consumer_result, dict)
        or consumer_result.get("verification_ok") is not True
        or consumer_result.get("decision") != "DENY"
        or consumer_result.get("g8_closed") is not False
        or sorted(consumer_result.get("missing_or_unready_dimensions", [])) != expected_missing
        or not isinstance(sources, Mapping)
        or dict(sources.get("reproducibility") or {}).get("ready") is not True
        or any(
            dict(sources.get(dimension) or {}).get("ready") is not False
            for dimension in expected_missing
        )
    ):
        raise SystemExit("G8 consumer effect does not match the bounded dimension claim")

    finalization = {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "capture_manifest_ref": verified["capture_ref"],
        "independent_review_ref": review_ref,
        "dimension_evidence_ref": dimension_ref,
        "consumer_process_ref": consumer_process_ref,
        "consumer_manifest_ref": evidence_ref(consumer_root / "run_manifest.v1.json"),
        "consumer_report_ref": evidence_ref(report_path),
        "consumer_verification_ref": evidence_ref(
            consumer_root / "operational_assurance_verification.v1.json"
        ),
        "reproducibility_ready": True,
        "missing_or_unready_dimensions": expected_missing,
        "decision": "DENY",
        "g8_closed": False,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
        "classification": "DIMENSION_CLOSURE_CANDIDATE",
    }
    finalization_ref = _write_json(output_root / "finalization_manifest.v1.json", finalization)
    return {
        "classification": "DIMENSION_CLOSURE_CANDIDATE",
        "finalization_manifest_ref": finalization_ref,
        "reproducibility_ready": True,
        "missing_or_unready_dimensions": expected_missing,
        "decision": "DENY",
        "g8_closed": False,
        "live_shadow_claim_allowed": False,
        "parent_complete": False,
    }


def _add_common_subject_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--expires-at", required=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(r"D:\XINAO_RESEARCH_RUNTIME"),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--output-root", type=Path, required=True)
    _add_common_subject_arguments(capture_parser)
    capture_parser.add_argument("--input-file", action="append", default=[])
    capture_parser.add_argument("--artifact-file", action="append", default=[])

    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--output-root", type=Path, required=True)
    finalize_parser.add_argument("--capture-manifest", type=Path, required=True)
    finalize_parser.add_argument("--independent-review", type=Path, required=True)
    finalize_parser.add_argument("--producer-identity", required=True)
    finalize_parser.add_argument("--issued-at", required=True)
    finalize_parser.add_argument("--expires-at", required=True)
    args = parser.parse_args()

    if args.command == "capture":
        source_commit = args.source_commit.lower()
        if _GIT_COMMIT_RE.fullmatch(source_commit) is None:
            raise SystemExit("source commit must be a lowercase 40-character Git commit")
        result = capture(
            output_root=_new_root(args.output_root, args.runtime_root),
            source_commit=source_commit,
            scope=args.scope,
            realm=args.realm,
            input_paths=_bindings(args.input_file, label="input file"),
            artifact_paths=_bindings(args.artifact_file, label="artifact file"),
            issued_at=args.issued_at,
            expires_at=args.expires_at,
        )
    else:
        result = finalize(
            output_root=_new_root(args.output_root, args.runtime_root),
            capture_path=args.capture_manifest.resolve(),
            review_path=args.independent_review.resolve(),
            producer_identity=args.producer_identity,
            issued_at=args.issued_at,
            expires_at=args.expires_at,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
