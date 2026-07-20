from __future__ import annotations

import json
import subprocess

import pytest

from xinao.foundation.assertion_verifier_registry import (
    build_canonical_code_manifest,
    canonical_projection_path,
    canonical_python_executable,
)
from xinao.foundation.closure_pack import REPORT_VERIFY_TIMEOUT_SECONDS, ClosurePackError


def test_report_verifier_entrypoint_is_authority_sealed_and_fails_closed(tmp_path) -> None:
    assert REPORT_VERIFY_TIMEOUT_SECONDS == 900
    relative = "xinao_discovery/src/xinao/foundation/report_verifier_entrypoint.py"
    manifest = build_canonical_code_manifest()
    assert any(entry["relative_path"] == relative for entry in manifest["entries"])

    missing = tmp_path / "missing-report.json"
    completed = subprocess.run(
        [
            str(canonical_python_executable()),
            "-X",
            "faulthandler",
            "-I",
            "-m",
            "xinao.foundation.report_verifier_entrypoint",
            "--projection",
            str(canonical_projection_path()),
            "--report",
            str(missing),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=30,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert result["ok"] is False
    assert result["foundation_execution_ready"] is False
    assert result["error_type"] == "FileNotFoundError"


@pytest.mark.parametrize(
    ("returncode", "expected_error"),
    [
        (3221225477, r"native_access_violation: exit=3221225477 \(0xC0000005\)"),
        (-1073741819, r"native_access_violation: exit=-1073741819 \(0xC0000005\)"),
    ],
)
def test_fresh_process_verifier_classifies_windows_access_violation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    expected_error: str,
) -> None:
    import xinao.foundation.closure_pack as closure_pack

    python = tmp_path / "runtime" / ".venv" / "Scripts" / "python.exe"
    observed: dict[str, object] = {}

    monkeypatch.setattr(closure_pack, "_validate_live_authority", lambda _path: None)
    monkeypatch.setattr(closure_pack, "canonical_python_executable", lambda: python)

    def fake_run(argv, **kwargs):
        observed["argv"] = list(argv)
        observed["kwargs"] = dict(kwargs)
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr="")

    monkeypatch.setattr(closure_pack.subprocess, "run", fake_run)

    with pytest.raises(
        ClosurePackError,
        match=expected_error,
    ):
        closure_pack._fresh_process_verify(
            projection_path=tmp_path / "projection.json",
            report_path=tmp_path / "report.json",
            authority_manifest_path=tmp_path / "authority-manifest.json",
        )

    assert observed["argv"] == [
        str(python),
        "-X",
        "faulthandler",
        "-I",
        "-m",
        "xinao.foundation.report_verifier_entrypoint",
        "--projection",
        str(tmp_path / "projection.json"),
        "--report",
        str(tmp_path / "report.json"),
    ]


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("foundation_closed", True),
        ("recorded_artifact_hash", "0" * 64),
        ("extra_field", True),
    ],
)
def test_fresh_process_verifier_rejects_malformed_success_envelope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    value: object,
) -> None:
    import xinao.foundation.closure_pack as closure_pack

    artifact_hash = "a" * 64
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"artifact_hash": artifact_hash}), encoding="utf-8")
    result = {
        "schema_version": "xinao.foundation_closure_verification.v1",
        "ok": True,
        "checks": {
            "schema_version_matches": True,
            "artifact_hash_replays": True,
            "derived_report_fields_match": True,
            "block_derivations_match": True,
            "exact_top_level_keys": True,
            "report_replays_exactly": True,
            "legacy_a_g_gate_unused": True,
            "manual_override_unused": True,
        },
        "recorded_artifact_hash": artifact_hash,
        "recomputed_artifact_hash": artifact_hash,
        "foundation_execution_ready": True,
        "foundation_closed": False,
    }
    result[mutation] = value

    monkeypatch.setattr(closure_pack, "_validate_live_authority", lambda _path: None)
    monkeypatch.setattr(
        closure_pack,
        "canonical_python_executable",
        lambda: tmp_path / "runtime" / ".venv" / "Scripts" / "python.exe",
    )
    monkeypatch.setattr(
        closure_pack.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(result),
            stderr="",
        ),
    )

    with pytest.raises(ClosurePackError, match="fresh-process verification rejected"):
        closure_pack._fresh_process_verify(
            projection_path=tmp_path / "projection.json",
            report_path=report_path,
            authority_manifest_path=tmp_path / "authority-manifest.json",
        )
