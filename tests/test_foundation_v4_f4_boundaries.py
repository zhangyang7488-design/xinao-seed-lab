from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from xinao.foundation import f4_current_evidence_verifier as verifier
from xinao.foundation import foundation_v4_replay_runtime as replay_runtime
from xinao.foundation.assertion_verifiers import f4_assertion_actuals as actuals
from xinao.foundation.foundation_v4_replay_runtime import FoundationV4ReplayError


def _write_synthetic_outer_start_record(
    *,
    audit: Path,
    block_id: str,
    nonce: str,
    argv: tuple[str, ...],
    runtime_python: Path,
    launcher_process_pid: int,
) -> None:
    executable = {
        "path": str(runtime_python.resolve()),
        "size_bytes": runtime_python.stat().st_size,
        "sha256": hashlib.sha256(runtime_python.read_bytes()).hexdigest(),
    }
    core = {
        "schema_version": replay_runtime.OUTER_START_RECORD_SCHEMA,
        "status": "STARTED",
        "block_id": block_id,
        "nonce": nonce,
        "run_index": 0,
        "interpreter_pid": launcher_process_pid + 1,
        "parent_pid": launcher_process_pid,
        "faulthandler_enabled": True,
        "sys_executable": executable,
        "base_executable": executable,
        "orig_argv_tail_sha256": replay_runtime._canonical_sha256(list(argv[1:])),
    }
    (audit / "outer-process-start.json").write_bytes(
        replay_runtime._canonical_bytes(
            {**core, "content_sha256": replay_runtime._canonical_sha256(core)}
        )
    )


def _synthetic_nested_argv(
    *,
    run_root: Path,
    role: str = "phase",
    phase: str = "final",
    nonce: str = "9" * 64,
    run_index: int = 0,
    runtime_python: Path | None = None,
    entrypoint: Path | None = None,
    entrypoint_manifest: Path | None = None,
) -> tuple[str, ...]:
    resolved_entrypoint = (entrypoint or (run_root.parent / "sealed" / "runtime.py")).resolve()
    context = {
        "role": role,
        "phase": phase,
        "nonce": nonce,
        "run_index": run_index,
        "run_root": str(run_root.resolve()),
        "entrypoint_path": str(resolved_entrypoint),
        "entrypoint_sha256": (
            hashlib.sha256(resolved_entrypoint.read_bytes()).hexdigest()
            if resolved_entrypoint.is_file()
            else "0" * 64
        ),
        "entrypoint_manifest_path": str(
            (
                entrypoint_manifest or (resolved_entrypoint.parent / "entrypoint_manifest.json")
            ).resolve()
        ),
    }
    return (
        str((runtime_python or Path(sys.executable)).resolve()),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        str(resolved_entrypoint),
        "--child-role",
        role,
        "--context-json",
        replay_runtime._canonical_bytes(context).decode("utf-8"),
    )


def test_assertion_bound_file_uses_snapshot_aware_readable_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    physical = tmp_path / "capsule" / "source.json"
    physical.parent.mkdir()
    physical.write_bytes(b'{"sealed":true}\n')
    logical = r"D:\XINAO_RESEARCH_RUNTIME\retained\source.json"
    calls: list[tuple[object, str]] = []

    def fake_readable_path(value: object, *, expect: str = "file") -> Path:
        calls.append((value, expect))
        return physical

    monkeypatch.setattr(verifier, "readable_path", fake_readable_path)

    result = actuals._F4PathBoundary.bound_file(
        {
            "path": logical,
            "sha256": hashlib.sha256(physical.read_bytes()).hexdigest(),
            "size_bytes": physical.stat().st_size,
        },
        "sealed source",
    )

    assert result == physical
    assert calls == [(logical, "file")]


def test_assertion_d_runtime_boundary_uses_retained_identity_inside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    physical = tmp_path / "capsule" / "source.json"
    calls: list[tuple[object, object]] = []

    def fake_inside(path: object, root: object) -> bool:
        calls.append((path, root))
        return True

    monkeypatch.setattr(verifier, "_inside", fake_inside)

    actuals._F4PathBoundary.require_d_runtime(physical, "sealed source")

    assert calls == [(physical, verifier.D_RUNTIME_ROOT)]


def test_fresh_runs_projection_ignores_only_physical_launcher_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "a" * 64
    authority_script = tmp_path / "authority" / "scripts" / "verify_f4_live_canary_pack.py"

    def record(*, python: str, script: str, pack_argv: str) -> dict[str, object]:
        return {
            "schema_version": verifier.RUNS_SCHEMA,
            "python_executable": python,
            "run_count": 1,
            "runs": [
                {
                    "label": "live_three_stage_runtime",
                    "argv": [
                        python,
                        "-I",
                        script,
                        "--pack",
                        pack_argv,
                        "--output-dir",
                        "<ephemeral-output-dir>",
                    ],
                    "shell": False,
                    "source_pack_ref": r"D:\retained\source",
                    "source_manifest_sha256": "b" * 64,
                    "bound_verification_ref": r"D:\retained\bound.json",
                    "bound_verification_file_sha256": "c" * 64,
                    "fresh_verification_file_sha256": "c" * 64,
                    "content_sha256": "d" * 64,
                    "assertion_count": 9,
                    "verifier_source_sha256": digest,
                }
            ],
            "fresh_exact_content_equals_bound_count": 1,
            "source_report_boolean_trust_count": 0,
            "content_sha256": "e" * 64,
        }

    observed_hash_paths: list[Path] = []

    def authority_hash_only(path: object) -> str:
        observed = Path(path)
        observed_hash_paths.append(observed)
        if observed != authority_script:
            raise OSError(f"historical launcher path is not readable: {observed}")
        return digest

    monkeypatch.setattr(
        verifier,
        "SOURCE_SPECS",
        {
            "live_three_stage_runtime": {
                "script": authority_script,
                "schema": "test.schema.v1",
                "manifest": "manifest.json",
            }
        },
    )
    monkeypatch.setattr(verifier, "_same_path", lambda left, right: True)
    monkeypatch.setattr(verifier, "file_sha256", authority_hash_only)
    monkeypatch.setattr(verifier, "retained_path", lambda value: str(value))
    retained = record(
        python=r"E:\runtime\python.exe",
        script=r"E:\repo\scripts\verify_f4_live_canary_pack.py",
        pack_argv=r"D:\retained\source",
    )
    relocated = record(
        python="/opt/f4-runtime/.venv/bin/python",
        script=str(authority_script),
        pack_argv="/capsule/roots/current_source",
    )
    relocated["runs"][0]["fresh_verification_file_sha256"] = "f" * 64

    assert actuals._F4RunProjection.path_neutral_fresh_runs(
        retained
    ) == actuals._F4RunProjection.path_neutral_fresh_runs(relocated)

    relocated["runs"][0]["assertion_count"] = 8
    assert actuals._F4RunProjection.path_neutral_fresh_runs(
        retained
    ) != actuals._F4RunProjection.path_neutral_fresh_runs(relocated)
    assert observed_hash_paths and set(observed_hash_paths) == {authority_script}


def test_f1_outer_argv_remains_byte_for_byte_default_compatible(tmp_path: Path) -> None:
    arguments = {
        "runtime_python": tmp_path / "python.exe",
        "sealed_entrypoint_path": tmp_path / "b1_runtime" / "runtime.py",
        "sealed_entrypoint_manifest_path": tmp_path / "b1_runtime" / "manifest.json",
        "pack_root": tmp_path,
        "output_root": tmp_path / "output",
        "nonce": "a" * 64,
        "run_index": 0,
        "dependency_roots": (tmp_path / "dependency",),
        "forbidden_roots": (tmp_path / "forbidden",),
        "injected_live_root": tmp_path / "live",
    }

    default = replay_runtime._outer_argv(**arguments)
    explicit = replay_runtime._outer_argv(
        **arguments,
        block_id="F1_settlement_world",
    )

    def absolute(value: object) -> str:
        return str(Path(os.path.abspath(str(value))))

    expected = (
        absolute(arguments["runtime_python"]),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        absolute(arguments["sealed_entrypoint_path"]),
        "--entrypoint-manifest",
        absolute(arguments["sealed_entrypoint_manifest_path"]),
        "--pack-root",
        absolute(arguments["pack_root"]),
        "--output-root",
        absolute(arguments["output_root"]),
        "--nonce",
        arguments["nonce"],
        "--run-index",
        "0",
        "--dependency-roots-json",
        json.dumps([absolute(arguments["dependency_roots"][0])], separators=(",", ":")),
        "--forbidden-roots-json",
        json.dumps([absolute(arguments["forbidden_roots"][0])], separators=(",", ":")),
        "--injected-live-root",
        absolute(arguments["injected_live_root"]),
    )

    assert default == expected
    assert explicit == default
    assert "--block-id" not in default


def test_clean_outer_environment_cannot_use_ambient_faulthandler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONFAULTHANDLER", "1")
    environment = replay_runtime._clean_child_environment()

    assert "PYTHONFAULTHANDLER" not in environment
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_nested_argv_requests_startup_faulthandler_without_changing_isolation(
    tmp_path: Path,
) -> None:
    entrypoint = tmp_path / "sealed" / "runtime.py"
    argv = replay_runtime._nested_argv(
        entrypoint=entrypoint,
        role="phase",
        context={"phase": "final"},
    )

    assert argv[1:6] == ("-X", "faulthandler", "-I", "-S", "-B")
    assert Path(argv[6]) == entrypoint.resolve()
    assert argv[7:9] == ("--child-role", "phase")


def test_nested_native_failure_capture_preserves_full_raw_streams(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    audit = run_root / "audit"
    audit.mkdir(parents=True)
    guard_log = audit / "forbidden-phase-final.jsonl"
    guard_log.write_bytes(b"guard\n")
    argv = _synthetic_nested_argv(run_root=run_root)

    capture, receipt_sha256 = replay_runtime._persist_nested_failure_capture(
        argv=argv,
        role="phase",
        phase="final",
        returncode=3221225477,
        stdout=b"partial nested stdout",
        stderr=b"Fatal Python error: access violation\nfull nested trace",
        launcher_process_pid=444,
        expected_guard_log_path=guard_log,
    )

    receipt_path = capture / "failure_capture.json"
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == receipt_sha256
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["returncode_hex"] == "0xC0000005"
    assert receipt["failure_class"] == "WINDOWS_ACCESS_VIOLATION"
    assert receipt["faulthandler_requested"] is True
    assert receipt["guard_log_exists"] is True
    assert receipt["retry_count"] == 0
    assert (capture / "stdout.bin").read_bytes() == b"partial nested stdout"
    assert (capture / "stderr.bin").read_bytes().endswith(b"full nested trace")


def test_nested_failure_capture_rejects_zero_exit_before_writing(tmp_path: Path) -> None:
    guard_log = tmp_path / "run-0" / "audit" / "forbidden-phase-final.jsonl"
    guard_log.parent.mkdir(parents=True)
    guard_log.write_bytes(b"guard\n")

    with pytest.raises(FoundationV4ReplayError, match="requires a nonzero exit"):
        replay_runtime._persist_nested_failure_capture(
            argv=(str(tmp_path / "python.exe"), "-X", "faulthandler"),
            role="phase",
            phase="final",
            returncode=0,
            stdout=b"",
            stderr=b"",
            launcher_process_pid=444,
            expected_guard_log_path=guard_log,
        )

    assert not (guard_log.parent / "nested-failure-attempt.json").exists()


def test_nested_failure_validator_rejects_an_unregistered_file(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    guard_log = run_root / "audit" / "forbidden-phase-final.jsonl"
    guard_log.parent.mkdir(parents=True)
    guard_log.write_bytes(b"guard\n")
    capture, _ = replay_runtime._persist_nested_failure_capture(
        argv=_synthetic_nested_argv(run_root=run_root),
        role="phase",
        phase="final",
        returncode=1,
        stdout=b"",
        stderr=b"failure",
        launcher_process_pid=444,
        expected_guard_log_path=guard_log,
    )
    (capture / "unregistered.bin").write_bytes(b"not in receipt")

    with pytest.raises(FoundationV4ReplayError, match="committed artifact set drifted"):
        replay_runtime._validate_copied_nested_failure(run_root)


def test_nested_failure_capture_rejects_a_boolean_pid(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    guard_log = run_root / "audit" / "forbidden-phase-final.jsonl"
    guard_log.parent.mkdir(parents=True)
    guard_log.write_bytes(b"guard\n")

    with pytest.raises(FoundationV4ReplayError, match="launcher PID is invalid"):
        replay_runtime._persist_nested_failure_capture(
            argv=_synthetic_nested_argv(run_root=run_root),
            role="phase",
            phase="final",
            returncode=1,
            stdout=b"",
            stderr=b"failure",
            launcher_process_pid=True,
            expected_guard_log_path=guard_log,
        )


def test_nested_failure_validator_rejects_an_orphan_capture(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    orphan = run_root / "audit" / "nested-failures" / "phase-final"
    orphan.mkdir(parents=True)
    (orphan / "failure_capture.json").write_bytes(b"{}")

    with pytest.raises(FoundationV4ReplayError, match="exists without an attempt"):
        replay_runtime._validate_copied_nested_failure(run_root)


def test_nested_failure_validator_requires_the_copied_guard(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    missing_guard = run_root / "audit" / "forbidden-phase-final.jsonl"
    missing_guard.parent.mkdir(parents=True)
    replay_runtime._persist_nested_failure_capture(
        argv=_synthetic_nested_argv(run_root=run_root),
        role="phase",
        phase="final",
        returncode=1,
        stdout=b"",
        stderr=b"failure",
        launcher_process_pid=444,
        expected_guard_log_path=missing_guard,
    )

    with pytest.raises(FoundationV4ReplayError, match="guard observation drifted"):
        replay_runtime._validate_copied_nested_failure(run_root)


def test_nested_failure_validator_rejects_copied_guard_byte_drift(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    guard_log = run_root / "audit" / "forbidden-phase-final.jsonl"
    guard_log.parent.mkdir(parents=True)
    guard_log.write_bytes(b"guard\n")
    replay_runtime._persist_nested_failure_capture(
        argv=_synthetic_nested_argv(run_root=run_root),
        role="phase",
        phase="final",
        returncode=1,
        stdout=b"",
        stderr=b"failure",
        launcher_process_pid=444,
        expected_guard_log_path=guard_log,
    )
    guard_log.write_bytes(b"changed after capture\n")

    with pytest.raises(FoundationV4ReplayError, match="copied guard drift"):
        replay_runtime._validate_copied_nested_failure(run_root)


def test_nested_failure_validator_binds_the_exact_original_run_root(tmp_path: Path) -> None:
    run_root = tmp_path / "source" / "run-0"
    guard_log = run_root / "audit" / "forbidden-phase-final.jsonl"
    guard_log.parent.mkdir(parents=True)
    guard_log.write_bytes(b"guard\n")
    replay_runtime._persist_nested_failure_capture(
        argv=_synthetic_nested_argv(run_root=run_root),
        role="phase",
        phase="final",
        returncode=1,
        stdout=b"",
        stderr=b"failure",
        launcher_process_pid=444,
        expected_guard_log_path=guard_log,
    )

    with pytest.raises(FoundationV4ReplayError, match="parent invocation binding drifted"):
        replay_runtime._validate_copied_nested_failure(
            run_root,
            expected_nonce="9" * 64,
            expected_run_index=0,
            expected_original_run_root=tmp_path / "other-parent" / "run-0",
        )


def test_nested_failure_invocation_binds_flags_role_and_context(tmp_path: Path) -> None:
    run_root = tmp_path / "run-0"
    argv = list(_synthetic_nested_argv(run_root=run_root))
    argv[8] = "ascii"

    with pytest.raises(FoundationV4ReplayError, match="exact invocation drifted"):
        replay_runtime._validated_nested_failure_invocation(
            argv,
            expected_role="phase",
            expected_phase="final",
        )


def test_nested_failure_survives_verified_outer_durable_copy(tmp_path: Path) -> None:
    output = tmp_path / "ephemeral-output"
    audit = output / "run-0" / "audit"
    audit.mkdir(parents=True)
    guard_log = audit / "forbidden-phase-final.jsonl"
    guard_log.write_bytes(b"guard\n")
    runtime_python = tmp_path / "runtime" / "python.exe"
    runtime_python.parent.mkdir()
    runtime_python.write_bytes(b"runtime")
    entrypoint = tmp_path / "pack" / "runtime.py"
    entrypoint.parent.mkdir()
    entrypoint.write_bytes(b"entrypoint")
    manifest = entrypoint.parent / "manifest.json"
    manifest.write_bytes(b"{}")
    nested_argv = _synthetic_nested_argv(
        run_root=output / "run-0",
        nonce="c" * 64,
        runtime_python=runtime_python,
        entrypoint=entrypoint,
        entrypoint_manifest=manifest,
    )
    _, nested_receipt_sha256 = replay_runtime._persist_nested_failure_capture(
        argv=nested_argv,
        role="phase",
        phase="final",
        returncode=3221225477,
        stdout=b"nested stdout",
        stderr=b"Fatal Python error\ncomplete nested native trace",
        launcher_process_pid=333,
        expected_guard_log_path=guard_log,
    )
    outer_argv = (
        str(runtime_python.resolve()),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        str(entrypoint.resolve()),
    )
    _write_synthetic_outer_start_record(
        audit=audit,
        block_id="F1_settlement_world",
        nonce="c" * 64,
        argv=outer_argv,
        runtime_python=runtime_python,
        launcher_process_pid=222,
    )

    durable, _, preservation_complete = replay_runtime._persist_outer_failure_capture(
        capture_root=tmp_path / "durable",
        block_id="F1_settlement_world",
        nonce="c" * 64,
        run_index=0,
        argv=outer_argv,
        cwd=entrypoint.parent,
        returncode=1,
        stdout=b"",
        stderr=(f"outer traceback names nested final sha256={nested_receipt_sha256}".encode()),
        launcher_process_pid=222,
        runtime_python=runtime_python,
        sealed_entrypoint_path=entrypoint,
        sealed_entrypoint_manifest_path=manifest,
        output_root=output,
    )
    shutil.rmtree(output)

    receipt = json.loads((durable / "failure_capture.json").read_text(encoding="utf-8"))
    assert preservation_complete is True
    assert receipt["nested_failure_capture_required"] is True
    assert receipt["nested_failure_capture_validated"] is True
    assert receipt["nested_failure_capture_count"] == 1
    copied_stderr = (
        durable / "partial_run" / "audit" / "nested-failures" / "phase-final" / "stderr.bin"
    )
    assert copied_stderr.read_bytes().endswith(b"complete nested native trace")


def test_incomplete_nested_capture_keeps_outer_preservation_false(tmp_path: Path) -> None:
    output = tmp_path / "ephemeral-output"
    audit = output / "run-0" / "audit"
    audit.mkdir(parents=True)
    attempt_core = {
        "schema_version": replay_runtime.NESTED_FAILURE_ATTEMPT_SCHEMA,
        "status": "CAPTURE_ATTEMPTED",
        "role": "phase",
        "phase": "final",
        "exact_argv_sha256": "d" * 64,
        "launcher_process_pid": 333,
        "returncode_signed": 3221225477,
        "returncode_uint32": 3221225477,
        "returncode_hex": "0xC0000005",
    }
    (audit / "nested-failure-attempt.json").write_bytes(
        replay_runtime._canonical_bytes(
            {
                **attempt_core,
                "content_sha256": replay_runtime._canonical_sha256(attempt_core),
            }
        )
    )
    runtime_python = tmp_path / "runtime" / "python.exe"
    runtime_python.parent.mkdir()
    runtime_python.write_bytes(b"runtime")
    entrypoint = tmp_path / "pack" / "runtime.py"
    entrypoint.parent.mkdir()
    entrypoint.write_bytes(b"entrypoint")
    manifest = entrypoint.parent / "manifest.json"
    manifest.write_bytes(b"{}")
    outer_argv = (
        str(runtime_python.resolve()),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        str(entrypoint.resolve()),
    )
    _write_synthetic_outer_start_record(
        audit=audit,
        block_id="F1_settlement_world",
        nonce="e" * 64,
        argv=outer_argv,
        runtime_python=runtime_python,
        launcher_process_pid=222,
    )

    durable, _, preservation_complete = replay_runtime._persist_outer_failure_capture(
        capture_root=tmp_path / "durable",
        block_id="F1_settlement_world",
        nonce="e" * 64,
        run_index=0,
        argv=outer_argv,
        cwd=entrypoint.parent,
        returncode=1,
        stdout=b"",
        stderr=b"outer traceback",
        launcher_process_pid=222,
        runtime_python=runtime_python,
        sealed_entrypoint_path=entrypoint,
        sealed_entrypoint_manifest_path=manifest,
        output_root=output,
    )

    receipt = json.loads((durable / "failure_capture.json").read_text(encoding="utf-8"))
    assert preservation_complete is False
    assert receipt["nested_failure_capture_required"] is True
    assert receipt["nested_failure_capture_validated"] is False
    assert receipt["nested_failure_capture_count"] == 0
    assert output.is_dir()


def test_successful_outer_exit_rejects_a_stale_start_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "output"
    stale = output / "run-0" / "audit" / "outer-process-start.json"

    class SuccessfulProcessWithStaleStart:
        returncode = 0
        pid = 4321

        def __init__(self, *args: object, **kwargs: object) -> None:
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"stale")

        def communicate(self) -> tuple[bytes, bytes]:
            return b"{}", b""

    monkeypatch.setattr(replay_runtime.subprocess, "Popen", SuccessfulProcessWithStaleStart)

    with pytest.raises(
        FoundationV4ReplayError,
        match="start record persisted after successful exit",
    ):
        replay_runtime._launch_outer_once(
            runtime_python=tmp_path / "python.exe",
            sealed_entrypoint_path=tmp_path / "pack" / "runtime.py",
            sealed_entrypoint_manifest_path=tmp_path / "pack" / "manifest.json",
            pack_root=tmp_path / "pack",
            output_root=output,
            nonce="f" * 64,
            run_index=0,
            dependency_roots=(),
            forbidden_roots=(),
            injected_live_root=tmp_path / "poison",
            block_id="F1_settlement_world",
        )


def test_outer_process_error_exposes_the_durable_capture_sha256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_python = tmp_path / "runtime" / "python.exe"
    runtime_python.parent.mkdir()
    runtime_python.write_bytes(b"runtime")
    entrypoint = tmp_path / "pack" / "runtime.py"
    entrypoint.parent.mkdir()
    entrypoint.write_bytes(b"entrypoint")
    manifest = entrypoint.parent / "manifest.json"
    manifest.write_bytes(b"{}")
    output = tmp_path / "output"
    audit = output / "run-0" / "audit"
    audit.mkdir(parents=True)
    nonce = "8" * 64
    block_id = "F2_issuer_settlement_cost_space"
    argv = replay_runtime._outer_argv(
        runtime_python=runtime_python,
        sealed_entrypoint_path=entrypoint,
        sealed_entrypoint_manifest_path=manifest,
        pack_root=entrypoint.parent,
        output_root=output,
        nonce=nonce,
        run_index=0,
        dependency_roots=(),
        forbidden_roots=(),
        injected_live_root=tmp_path / "poison",
        block_id=block_id,
    )
    _write_synthetic_outer_start_record(
        audit=audit,
        block_id=block_id,
        nonce=nonce,
        argv=argv,
        runtime_python=runtime_python,
        launcher_process_pid=4321,
    )

    class FailedProcess:
        returncode = 1
        pid = 4321

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"outer failure"

    monkeypatch.setattr(replay_runtime.subprocess, "Popen", FailedProcess)
    with pytest.raises(replay_runtime.OuterReplayProcessError) as caught:
        replay_runtime._launch_outer_once(
            runtime_python=runtime_python,
            sealed_entrypoint_path=entrypoint,
            sealed_entrypoint_manifest_path=manifest,
            pack_root=entrypoint.parent,
            output_root=output,
            nonce=nonce,
            run_index=0,
            dependency_roots=(),
            forbidden_roots=(),
            injected_live_root=tmp_path / "poison",
            block_id=block_id,
            failure_capture_root=tmp_path / "durable",
        )

    error = caught.value
    assert error.preservation_complete is True
    assert error.failure_capture_path is not None
    assert (
        error.failure_capture_sha256
        == hashlib.sha256(
            (error.failure_capture_path / "failure_capture.json").read_bytes()
        ).hexdigest()
    )


def test_failure_capture_rejects_an_ancestor_reparse_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "junction-parent"
    ancestor.mkdir()
    capture = ancestor / "durable"
    real_lstat = replay_runtime.os.lstat

    def fake_lstat(path: object):
        observed = real_lstat(path)
        if Path(path) == ancestor:
            return SimpleNamespace(
                st_mode=observed.st_mode,
                st_file_attributes=0x400,
            )
        return observed

    monkeypatch.setattr(replay_runtime.os, "lstat", fake_lstat)

    with pytest.raises(FoundationV4ReplayError, match="path chain contains"):
        replay_runtime._require_plain_path_chain(
            capture,
            label="test capture root",
        )
    assert not capture.exists()


def test_outer_failure_capture_rejects_ephemeral_destination_before_write(
    tmp_path: Path,
) -> None:
    output = tmp_path / "ephemeral-output"
    capture = output / "durable"

    with pytest.raises(FoundationV4ReplayError, match="inside ephemeral output"):
        replay_runtime._persist_outer_failure_capture(
            capture_root=capture,
            block_id="F2_issuer_settlement_cost_space",
            nonce="a" * 64,
            run_index=0,
            argv=(str(tmp_path / "python.exe"), "-X", "faulthandler"),
            cwd=tmp_path,
            returncode=1,
            stdout=b"",
            stderr=b"failure",
            launcher_process_pid=1,
            runtime_python=tmp_path / "python.exe",
            sealed_entrypoint_path=tmp_path / "runtime.py",
            sealed_entrypoint_manifest_path=tmp_path / "manifest.json",
            output_root=output,
        )

    assert not capture.exists()


@pytest.mark.parametrize(
    ("returncode", "failure_class", "returncode_hex"),
    (
        (3221225477, "WINDOWS_ACCESS_VIOLATION", "0xC0000005"),
        (1, "PROCESS_EXIT_NONZERO", "0x00000001"),
    ),
)
def test_outer_failure_capture_is_exact_atomic_and_failure_only(
    tmp_path: Path,
    returncode: int,
    failure_class: str,
    returncode_hex: str,
) -> None:
    runtime_python = tmp_path / "runtime" / "python.exe"
    runtime_python.parent.mkdir()
    runtime_python.write_bytes(b"runtime-redirector")
    entrypoint = tmp_path / "pack" / "b1_runtime" / "runtime.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_bytes(b"print('sealed')\n")
    entrypoint_manifest = entrypoint.parent / "entrypoint_manifest.json"
    entrypoint_manifest.write_bytes(b"{}")
    output = tmp_path / "ephemeral-output"
    run_root = output / "run-0"
    audit = run_root / "audit"
    audit.mkdir(parents=True)
    (run_root / "partial.txt").write_text("partial", encoding="utf-8")
    nonce = ("a" if returncode == 3221225477 else "b") * 64
    argv = (
        str(runtime_python.resolve()),
        "-X",
        "faulthandler",
        "-I",
        "-S",
        "-B",
        str(entrypoint.resolve()),
    )
    start_core = {
        "schema_version": replay_runtime.OUTER_START_RECORD_SCHEMA,
        "status": "STARTED",
        "block_id": "F2_issuer_settlement_cost_space",
        "nonce": nonce,
        "run_index": 0,
        "interpreter_pid": 222,
        "parent_pid": 111,
        "faulthandler_enabled": True,
        "sys_executable": {
            "path": str(runtime_python.resolve()),
            "size_bytes": runtime_python.stat().st_size,
            "sha256": hashlib.sha256(runtime_python.read_bytes()).hexdigest(),
        },
        "base_executable": {
            "path": str(runtime_python.resolve()),
            "size_bytes": runtime_python.stat().st_size,
            "sha256": hashlib.sha256(runtime_python.read_bytes()).hexdigest(),
        },
        "orig_argv_tail_sha256": replay_runtime._canonical_sha256(list(argv[1:])),
    }
    start_record = {
        **start_core,
        "content_sha256": replay_runtime._canonical_sha256(start_core),
    }
    (audit / "outer-process-start.json").write_bytes(replay_runtime._canonical_bytes(start_record))
    capture_parent = tmp_path / "durable-failures"

    (
        capture,
        receipt_sha256,
        preservation_complete,
    ) = replay_runtime._persist_outer_failure_capture(
        capture_root=capture_parent,
        block_id="F2_issuer_settlement_cost_space",
        nonce=nonce,
        run_index=0,
        argv=argv,
        cwd=entrypoint.parent,
        returncode=returncode,
        stdout=b"partial stdout",
        stderr=b"Fatal Python error: access violation",
        launcher_process_pid=111,
        runtime_python=runtime_python,
        sealed_entrypoint_path=entrypoint,
        sealed_entrypoint_manifest_path=entrypoint_manifest,
        output_root=output,
    )

    assert capture.is_dir()
    assert preservation_complete is True
    assert not tuple(capture_parent.glob("*.staging"))
    receipt_path = capture / "failure_capture.json"
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == receipt_sha256
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["failure_class"] == failure_class
    assert receipt["returncode_hex"] == returncode_hex
    assert receipt["returncode_uint32"] == returncode & 0xFFFFFFFF
    assert receipt["faulthandler_requested"] is True
    assert receipt["faulthandler_start_record_validated"] is True
    assert receipt["faulthandler_observed"] is True
    assert receipt["partial_run_copied"] is True
    assert receipt["preservation_verified"] is True
    assert receipt["retry_count"] == 0
    assert (capture / "stdout.bin").read_bytes() == b"partial stdout"
    assert (capture / "stderr.bin").read_bytes() == (b"Fatal Python error: access violation")
    assert (capture / "partial_run" / "partial.txt").read_text(encoding="utf-8") == ("partial")
    assert run_root.is_dir()
