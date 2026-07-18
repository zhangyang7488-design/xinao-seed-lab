from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts import verify_f4_current_evidence_pack as subject

SOURCE_LABELS = (
    "live_three_stage_runtime",
    "portfolio_source_and_order",
    "negative_failure_cancel_recovery",
)


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _fresh_verification(
    root: Path,
    manifest: Path,
    *,
    label: str,
    index: int,
) -> subject.FreshVerification:
    target = Path(subject.SOURCE_SPECS[label]["script"])
    assertions = {
        f"assertion-{assertion_index}": {"verification_state": "VERIFIED"}
        for assertion_index in range(index)
    }
    bound_core = {
        "schema_version": subject.SOURCE_SPECS[label]["schema"],
        "status": "VERIFIED",
        "assertion_count": index,
        "assertions": assertions,
    }
    bound = {**bound_core, "content_sha256": subject.canonical_sha256(bound_core)}
    bound_path = _write_json(root / f"{label}.json", bound)
    verifier_sha256 = subject.file_sha256(target)
    return subject.FreshVerification(
        label=label,
        pack=root,
        manifest=manifest,
        bound_path=bound_path,
        bound=bound,
        verifier_script=target,
        verifier_source_sha256=verifier_sha256,
        fresh_file_sha256=subject.file_sha256(bound_path),
        content_sha256=bound["content_sha256"],
        assertion_count=index,
        command=(
            str(subject.DEFAULT_PYTHON),
            "-I",
            str(target),
            "--pack",
            str(root),
            "--output-dir",
            "<ephemeral-output-dir>",
        ),
    )


def _exact_pack(root: Path) -> Path:
    root.mkdir()
    for index in range(11):
        (root / f"artifact-{index:02d}.json").write_text(
            json.dumps({"index": index}),
            encoding="utf-8",
        )
    entries = [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": subject.file_sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.glob("artifact-*.json"))
    ]
    core = {
        "schema_version": "xinao.f4_current_evidence_exact_manifest.v1",
        "pack_ref": str(root.resolve()),
        "artifact_count": len(entries),
        "artifacts": entries,
        "artifact_set_sha256": subject.canonical_sha256(entries),
    }
    _write_json(
        root / "artifact_manifest.json",
        {**core, "content_sha256": subject.canonical_sha256(core)},
    )
    return root


def test_exact_manifest_rejects_byte_tamper(tmp_path: Path) -> None:
    pack = _exact_pack(tmp_path / "pack")
    subject._verify_exact_manifest(pack)

    (pack / "artifact-03.json").write_text("tampered", encoding="utf-8")

    with pytest.raises(subject.VerificationError, match="byte binding drifted"):
        subject._verify_exact_manifest(pack)


def test_materialized_payload_requires_utf8_lf_bytes(tmp_path: Path) -> None:
    payload = {"object_type": "Example", "value": 1}
    path = tmp_path / "payload.json"
    canonical = subject._pretty_json_bytes(payload)
    assert b"\r\n" not in canonical

    path.write_bytes(canonical)
    subject._require_materialized_payload_bytes(path, payload, object_type="Example")

    path.write_bytes(canonical.replace(b"\n", b"\r\n"))
    with pytest.raises(subject.VerificationError, match="byte-for-byte current"):
        subject._require_materialized_payload_bytes(path, payload, object_type="Example")


def test_canary_report_rejects_missing_assertion_before_derivation(tmp_path: Path) -> None:
    incomplete = {
        "object_type": "F4AssertionEvidenceMap",
        "assertion_count": 13,
        "assertion_ids": list(subject.ASSERTION_IDS[:-1]),
        "assertions": {},
    }

    with pytest.raises(subject.VerificationError, match="exact 14-item evidence map"):
        subject.build_canary_report(  # type: ignore[arg-type]
            None,
            incomplete,
            tmp_path / "map.json",
            {},
        )


def test_canary_report_is_content_addressed_index_over_exact_map(tmp_path: Path) -> None:
    manifest_path = _write_json(tmp_path / "artifact_manifest.json", {"manifest": True})
    payload = {
        "object_type": "TypedHandoffSchemaVersion",
        "content_sha256": "a" * 64,
    }
    payload_path = _write_json(tmp_path / "typed.json", payload)
    evidence_map = {
        "object_type": "F4AssertionEvidenceMap",
        "assertion_count": 14,
        "assertion_ids": list(subject.ASSERTION_IDS),
        "assertions": {
            assertion_id: {"verification_state": "VERIFIED"}
            for assertion_id in subject.ASSERTION_IDS
        },
        "content_sha256": "b" * 64,
    }
    map_path = _write_json(tmp_path / "map.json", evidence_map)
    current = subject.CurrentPack(
        root=tmp_path,
        manifest_path=manifest_path,
        manifest={},
        compiler_report_path=tmp_path / "compiler.json",
        compiler_report={},
        source_bindings_path=tmp_path / "sources.json",
        source_bindings={},
        required_paths={"TypedHandoffSchemaVersion": payload_path},
        supporting_paths={},
    )
    fresh = {
        label: _fresh_verification(
            tmp_path,
            manifest_path,
            label=label,
            index=index,
        )
        for index, label in enumerate(subject.SOURCE_SPECS, start=1)
    }

    report = subject.build_canary_report(current, evidence_map, map_path, fresh)
    core = dict(report)
    content_hash = core.pop("content_sha256")
    version_id = core.pop("version_id")

    assert report["status"] == "VERIFIED"
    assert report["report_role"] == "INDEX_ONLY_NOT_PROOF"
    assert report["report_is_evidence_authority"] is False
    assert report["assertion_count"] == 14
    assert report["source_report_boolean_trust_count"] == 0
    assert content_hash == subject.canonical_sha256(core)
    assert version_id == f"ResearchFactoryCanaryReport@{content_hash[:16]}"


def test_fresh_runs_v1_is_exact_three_bound_rerun_index(tmp_path: Path) -> None:
    manifest_path = _write_json(tmp_path / "manifest.json", {"manifest": True})
    fresh = {
        label: _fresh_verification(
            tmp_path,
            manifest_path,
            label=label,
            index=index,
        )
        for index, label in enumerate(SOURCE_LABELS, start=1)
    }

    runs = subject._fresh_runs_record(fresh)

    assert set(runs) == {
        "schema_version",
        "python_executable",
        "run_count",
        "runs",
        "fresh_exact_content_equals_bound_count",
        "source_report_boolean_trust_count",
        "content_sha256",
    }
    assert runs["schema_version"] == "xinao.f4_fresh_verifier_runs.v1"
    assert runs["python_executable"] == str(subject.DEFAULT_PYTHON)
    assert runs["run_count"] == 3
    assert [row["label"] for row in runs["runs"]] == list(SOURCE_LABELS)
    assert all(
        set(row)
        == {
            "label",
            "argv",
            "shell",
            "source_pack_ref",
            "source_manifest_sha256",
            "bound_verification_ref",
            "bound_verification_file_sha256",
            "fresh_verification_file_sha256",
            "content_sha256",
            "assertion_count",
            "verifier_source_sha256",
        }
        for row in runs["runs"]
    )
    assert all(row["shell"] is False for row in runs["runs"])
    assert runs["fresh_exact_content_equals_bound_count"] == 3
    assert runs["source_report_boolean_trust_count"] == 0
    core = dict(runs)
    content_hash = core.pop("content_sha256")
    assert content_hash == subject.canonical_sha256(core)


def test_clean_subprocess_env_preserves_snapshot_bindings_and_drops_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XINAO_F4_SNAPSHOT_MANIFEST", "/capsule/snapshot_manifest.json")
    monkeypatch.setenv("XINAO_F4_AUTHORITY_ROOT", "/opt/xinao-authority")
    monkeypatch.setenv("UNRELATED_HOST_SECRET", "must-not-cross")

    environment = subject._clean_subprocess_env()

    assert environment["XINAO_F4_SNAPSHOT_MANIFEST"] == "/capsule/snapshot_manifest.json"
    assert environment["XINAO_F4_AUTHORITY_ROOT"] == "/opt/xinao-authority"
    assert "UNRELATED_HOST_SECRET" not in environment


def test_snapshot_python_selection_uses_current_container_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = tmp_path / "venv" / "bin" / "python"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"launcher")
    monkeypatch.setattr(subject._implementation, "_snapshot_enabled", lambda: True)
    monkeypatch.setattr(subject._implementation.sys, "executable", str(launcher))
    assert subject._active_python(subject.DEFAULT_PYTHON) == launcher


def test_default_fresh_verifier_uses_repository_workflow_environment() -> None:
    expected = subject.REPO_ROOT / ".venv" / "Scripts" / "python.exe"

    assert subject.DEFAULT_PYTHON == expected
    completed = subprocess.run(
        [
            str(expected),
            "-I",
            "-c",
            "import mlflow, temporalio; print('ready')",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ready"


def test_fresh_verifier_failure_preserves_stdout_error() -> None:
    completed = subprocess.CompletedProcess(
        args=["python", "verifier.py"],
        returncode=1,
        stdout='{"status":"FAILED","error":"portable path drift"}\n',
        stderr="",
    )

    detail = subject._command_failure_detail("live verifier", completed)

    assert "exit code 1" in detail
    assert "portable path drift" in detail
    assert "stdout:" in detail
