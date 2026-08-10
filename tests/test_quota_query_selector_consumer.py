from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from services.agent_runtime.selector_release import (
    RELEASE_FILES,
    build_selector_release,
    promote_selector_release,
    selector_release_current_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GET_QUOTA = REPO_ROOT / "scripts" / "quota_query" / "Get-AIQuota.ps1"
INSTALLER = REPO_ROOT / "scripts" / "install_dispatch_economics_runtime.ps1"
BINDING_NAME = "selector-validator-root.txt"


def _copy_release_source(destination: Path) -> None:
    selected = {
        *RELEASE_FILES,
        "uv.lock",
        "services/agent_runtime/selector_release.py",
        "scripts/build_selector_release.py",
        "scripts/quota_query/Get-AIQuota.ps1",
    }
    for relative_text in sorted(selected):
        source = REPO_ROOT / relative_text
        target = destination / relative_text
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    epoch = destination / "scripts" / "quota_dispatch_epoch.py"
    epoch.write_text(
        """\
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--runtime-root", required=True)
parser.add_argument("--epoch-id", required=True)
args, _ = parser.parse_known_args()
marker = Path(args.runtime_root) / "validated-epoch-script-ran.txt"
marker.write_text(args.epoch_id, encoding="utf-8")
print(json.dumps({
    "status": "quota_snapshot_resolved",
    "dispatch_blocked": False,
    "snapshot": {
        "epoch_id": args.epoch_id,
        "snapshot_id": "fixture-snapshot",
        "freshness": "fresh",
        "snapshot_ref": str(marker),
    },
}, separators=(",", ":"), sort_keys=True))
""",
        encoding="utf-8",
        newline="\n",
    )


def _git_head(source: Path) -> str:
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "selector-test@example.invalid"], cwd=source, check=True
    )
    subprocess.run(["git", "config", "user.name", "Selector Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "--all"], cwd=source, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=source, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _pwsh() -> str:
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required for the real quota-query consumer")
    return executable


def _retire_fixture_source(path: Path) -> None:
    def clear_readonly(function: object, target: str, error: BaseException) -> None:
        del error
        os.chmod(target, stat.S_IWRITE)
        function(target)  # type: ignore[operator]

    shutil.rmtree(path, onexc=clear_readonly)


def _run_installer(
    source: Path,
    runtime: Path,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(INSTALLER),
            "-SourceRoot",
            str(source),
            "-RuntimeRoot",
            str(runtime),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def _install_consumer(source: Path, runtime: Path) -> tuple[Path, dict[str, object]]:
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True, exist_ok=True)
    (target_directory / "quota-query.mjs").write_text(
        "// installed fixture\n", encoding="utf-8", newline="\n"
    )
    completed = _run_installer(source, runtime)
    assert completed.returncode == 0, completed.stderr
    return target_directory / "Get-AIQuota.ps1", json.loads(completed.stdout)


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    _copy_release_source(source)
    _git_head(source)
    built = build_selector_release(
        source_root=source,
        runtime_root=runtime,
        release_id="consumer-fixture",
        python_executable=Path(sys.executable),
        create_venv=False,
        promote=False,
    )
    promoted = promote_selector_release(
        runtime,
        release_id="consumer-fixture",
        expected_current=selector_release_current_identity(runtime),
    )
    assert promoted["status"] == "release_promoted"
    script, receipt = _install_consumer(source, runtime)
    return runtime, Path(built["release_root"]), script, source, receipt


def _run_consumer(script: Path, runtime: Path, epoch_id: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            "-RuntimeRoot",
            str(runtime),
            "-EpochId",
            epoch_id,
            "-NoLiveCodex",
            "-Json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows hidden-process consumer")
def test_installed_epoch_consumer_survives_source_root_deletion(tmp_path: Path) -> None:
    runtime, _, script, source, _ = _release_fixture(tmp_path)
    _retire_fixture_source(source)

    completed = _run_consumer(script, runtime, "epoch-source-retired")

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["snapshot"]["epoch_id"] == "epoch-source-retired"
    assert (runtime / "validated-epoch-script-ran.txt").read_text(encoding="utf-8") == (
        "epoch-source-retired"
    )
    installed = script.read_text(encoding="utf-8")
    assert "__XINAO_SELECTOR_VALIDATOR_BINDING_SHA256__" not in installed
    assert "selector-validator-root.txt" in installed
    assert '"-I", "-S", "-B"' in installed
    assert "CreateNoWindow = $true" in installed
    assert "UseShellExecute = $false" in installed
    assert "ProcessWindowStyle]::Hidden" in installed


@pytest.mark.skipif(os.name != "nt", reason="Windows hidden-process consumer")
@pytest.mark.parametrize("tamper", ["pointer", "manifest_locator", "release_file"])
def test_epoch_consumer_rejects_selector_tamper_before_execution(
    tmp_path: Path,
    tamper: str,
) -> None:
    runtime, release_root, script, _, _ = _release_fixture(tmp_path)
    pointer = runtime / "state" / "grok_supervisor_selector" / "current.json"
    manifest = release_root / "release_manifest.json"
    epoch = release_root / "scripts" / "quota_dispatch_epoch.py"
    untrusted_marker = tmp_path / "untrusted-selector-python-ran.txt"

    if tamper == "pointer":
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        payload["release_id"] = "tampered-pointer"
        pointer.write_text(json.dumps(payload), encoding="utf-8")
    elif tamper == "manifest_locator":
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["python_executable"] = str(tmp_path / "untrusted-python.exe")
        payload["probe"]["python_executable"] = str(untrusted_marker)
        manifest.write_text(json.dumps(payload), encoding="utf-8")
    else:
        epoch.write_bytes(epoch.read_bytes() + b"\n# tampered release file\n")

    completed = _run_consumer(script, runtime, f"epoch-{tamper}")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_RELEASE_VALIDATION_FAILED" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()
    assert not untrusted_marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows trust-anchor consumer")
def test_binding_to_malicious_root_fails_before_root_python_executes(tmp_path: Path) -> None:
    runtime, _, script, _, _ = _release_fixture(tmp_path)
    binding_path = script.parent / BINDING_NAME
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    marker = tmp_path / "malicious-validator-ran.txt"
    malicious_root = tmp_path / "malicious-validator"
    malicious_cli = malicious_root / "scripts" / "build_selector_release.py"
    malicious_cli.parent.mkdir(parents=True)
    malicious_cli.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    binding["validator_root"] = str(malicious_root.resolve())
    binding["files"][0]["sha256"] = hashlib.sha256(malicious_cli.read_bytes()).hexdigest()
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    completed = _run_consumer(script, runtime, "epoch-malicious-binding")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_VALIDATOR_BINDING_HASH_MISMATCH" in completed.stderr
    assert not marker.exists()
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows trust-anchor consumer")
def test_validator_file_drift_fails_before_epoch_executes(tmp_path: Path) -> None:
    runtime, _, script, _, receipt = _release_fixture(tmp_path)
    validator_root = Path(str(receipt["validator_root"]))
    validator = validator_root / "scripts" / "build_selector_release.py"
    validator.write_bytes(validator.read_bytes() + b"\n# drift\n")

    completed = _run_consumer(script, runtime, "epoch-validator-drift")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_VALIDATOR_CLOSURE_HASH_MISMATCH" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point consumer")
def test_validator_leaf_symlink_is_rejected_even_when_target_bytes_match(
    tmp_path: Path,
) -> None:
    runtime, _, script, _, receipt = _release_fixture(tmp_path)
    validator_root = Path(str(receipt["validator_root"]))
    validator = validator_root / "scripts" / "build_selector_release.py"
    identical_target = tmp_path / "identical-validator.py"
    identical_target.write_bytes(validator.read_bytes())
    validator.unlink()
    try:
        validator.symlink_to(identical_target)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    completed = _run_consumer(script, runtime, "epoch-validator-symlink")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_VALIDATOR_CLOSURE_REPARSE_POINT" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installer consumer")
def test_installer_publishes_hash_bound_validator_and_receipt_readback(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    expected_head = _git_head(source)
    runtime = tmp_path / "install-runtime"

    installed, receipt = _install_consumer(source, runtime)

    binding = installed.parent / BINDING_NAME
    binding_sha = hashlib.sha256(binding.read_bytes()).hexdigest()
    persisted_path = Path(str(receipt["receipt_ref"]))
    persisted_bytes = persisted_path.read_bytes()
    persisted = json.loads(persisted_bytes)
    assert receipt["source_git_head"] == expected_head
    assert binding_sha in installed.read_text(encoding="utf-8")
    assert receipt["validator_binding_sha256"] == binding_sha
    assert receipt["target_sha256"] == hashlib.sha256(installed.read_bytes()).hexdigest()
    assert receipt["receipt_sha256"] == hashlib.sha256(persisted_bytes).hexdigest()
    assert persisted["validator_binding_sha256"] == binding_sha
    assert Path(str(persisted["validator_root"])).parent == persisted_path.parent
    assert persisted["validator_files"]
    assert os.path.samefile(
        Path(str(persisted["validator_python_ref"])),
        Path(os.path.realpath(sys._base_executable)),
    )
    for row in persisted["validator_files"]:
        target = Path(str(persisted["validator_root"])) / str(row["path"])
        assert target.is_file()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == row["sha256"]
    assert persisted["completion_claim_allowed"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows installer serialization")
def test_installer_waits_for_shared_lock_then_reads_the_new_previous_pair(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    runtime = tmp_path / "serialized-runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    target = target_directory / "Get-AIQuota.ps1"
    binding = target_directory / BINDING_NAME
    target.write_bytes(b"# initial consumer\n")
    binding.write_bytes(b'{"initial":true}\n')
    (target_directory / "quota-query.mjs").write_text(
        "// installed fixture\n", encoding="utf-8", newline="\n"
    )

    lock_path = target_directory / ".install.lock"
    ready = tmp_path / "lock-ready.txt"
    release = tmp_path / "lock-release.txt"
    holder_code = """
param(
    [string]$LockPath,
    [string]$ReadyPath,
    [string]$ReleasePath
)
$handle = [IO.FileStream]::new(
    $LockPath,
    [IO.FileMode]::OpenOrCreate,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::None
)
try {
    [IO.File]::WriteAllText($ReadyPath, 'ready')
    while (-not (Test-Path -LiteralPath $ReleasePath)) {
        Start-Sleep -Milliseconds 10
    }
}
finally {
    $handle.Dispose()
}
"""
    holder_script = tmp_path / "hold-install-lock.ps1"
    holder_script.write_text(holder_code, encoding="utf-8", newline="\n")
    holder = subprocess.Popen(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(holder_script),
            "-LockPath",
            str(lock_path),
            "-ReadyPath",
            str(ready),
            "-ReleasePath",
            str(release),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    installer: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), holder.communicate(timeout=1)

        installer = subprocess.Popen(
            [
                _pwsh(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(INSTALLER),
                "-SourceRoot",
                str(source),
                "-RuntimeRoot",
                str(runtime),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        time.sleep(0.2)
        assert installer.poll() is None
        assert not list((runtime / "state" / "quota_query_releases").glob("*"))

        previous_target = b"# prior successful installer consumer\n"
        previous_binding = b'{"prior_successful_installer":true}\n'
        target.write_bytes(previous_target)
        binding.write_bytes(previous_binding)
        release.write_text("release", encoding="utf-8")

        stdout, stderr = installer.communicate(timeout=45)
        assert installer.returncode == 0, stderr
        receipt = json.loads(stdout)
        assert receipt["previous_sha256"] == hashlib.sha256(previous_target).hexdigest()
        assert (
            receipt["previous_validator_binding_sha256"]
            == hashlib.sha256(previous_binding).hexdigest()
        )
        assert receipt["target_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert (
            receipt["validator_binding_sha256"] == hashlib.sha256(binding.read_bytes()).hexdigest()
        )
        assert not list(target_directory.glob("*.tmp"))
    finally:
        release.write_text("release", encoding="utf-8")
        if installer is not None and installer.poll() is None:
            installer.kill()
            installer.wait(timeout=5)
        if holder.poll() is None:
            holder.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer transaction")
def test_installer_rolls_back_consumer_and_binding_when_receipt_cannot_close(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    runtime = tmp_path / "rollback-runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    target = target_directory / "Get-AIQuota.ps1"
    binding = target_directory / BINDING_NAME
    old_target = b"# pre-existing consumer\n"
    old_binding = b'{"pre_existing":true}\n'
    target.write_bytes(old_target)
    binding.write_bytes(old_binding)
    (target_directory / "quota-query.mjs").write_text(
        "// installed fixture\n", encoding="utf-8", newline="\n"
    )

    shim = tmp_path / "git-shim"
    shim.mkdir()
    counter = tmp_path / "git-calls.txt"
    fake_head = "1" * 40
    git_cmd = shim / "git.cmd"
    git_cmd.write_text(
        "@echo off\r\n"
        f'if not exist "{counter}" (\r\n'
        f'  echo first>"{counter}"\r\n'
        f"  echo {fake_head}\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        f'echo second>>"{counter}"\r\n'
        "exit /b 1\r\n",
        encoding="utf-8",
        newline="",
    )
    environment = dict(os.environ)
    environment["PATH"] = str(shim) + os.pathsep + environment.get("PATH", "")

    completed = _run_installer(source, runtime, environment=environment)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_INSTALL_SOURCE_GIT_HEAD_CHANGED" in completed.stderr
    assert counter.read_text(encoding="utf-8").splitlines() == ["first", "second"]
    assert target.read_bytes() == old_target
    assert binding.read_bytes() == old_binding
    releases = runtime / "state" / "quota_query_releases"
    assert not list(releases.glob("quota-validator-*"))
    assert not list(target_directory.glob("*.tmp"))
