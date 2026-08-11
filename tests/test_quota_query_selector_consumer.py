from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
    validate_selector_release_pointer,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GET_QUOTA = REPO_ROOT / "scripts" / "quota_query" / "Get-AIQuota.ps1"
INSTALLER = REPO_ROOT / "scripts" / "install_dispatch_economics_runtime.ps1"
BINDING_NAME = "selector-validator-root.txt"
_BINDING_SHA_ASSIGNMENT = re.compile(
    r'^\$installedValidatorBindingSha256 = "([0-9a-f]{64})"$', re.MULTILINE
)
_BINDING_BASE64_ASSIGNMENT = re.compile(
    r'^\$installedValidatorBindingBase64 = "([A-Za-z0-9+/=]+)"$', re.MULTILINE
)


def _embedded_binding(script: Path) -> tuple[dict[str, object], bytes]:
    installed = script.read_text(encoding="utf-8")
    sha_match = _BINDING_SHA_ASSIGNMENT.search(installed)
    base64_match = _BINDING_BASE64_ASSIGNMENT.search(installed)
    assert sha_match is not None
    assert base64_match is not None
    raw = base64.b64decode(base64_match.group(1), validate=True)
    assert hashlib.sha256(raw).hexdigest() == sha_match.group(1)
    return json.loads(raw), raw


def _rewrite_embedded_binding(script: Path, binding: dict[str, object]) -> None:
    raw = (json.dumps(binding, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    installed = script.read_text(encoding="utf-8")
    installed, sha_count = _BINDING_SHA_ASSIGNMENT.subn(
        f'$installedValidatorBindingSha256 = "{hashlib.sha256(raw).hexdigest()}"', installed
    )
    installed, base64_count = _BINDING_BASE64_ASSIGNMENT.subn(
        f'$installedValidatorBindingBase64 = "{base64.b64encode(raw).decode("ascii")}"',
        installed,
    )
    assert sha_count == 1
    assert base64_count == 1
    script.write_text(installed, encoding="utf-8", newline="\n")


def _rewrite_release_python_binding(
    runtime: Path,
    release_root: Path,
    python_path: Path,
) -> None:
    manifest_path = release_root / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    python_bytes = python_path.read_bytes()
    manifest["python_executable"] = str(python_path)
    manifest["python_sha256"] = hashlib.sha256(python_bytes).hexdigest()
    manifest["python_size_bytes"] = len(python_bytes)
    manifest["probe"]["python_executable"] = str(python_path)
    content = dict(manifest)
    content.pop("release_content_sha256", None)
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest["release_content_sha256"] = hashlib.sha256(canonical).hexdigest()
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    pointer_path = runtime / "state" / "grok_supervisor_selector" / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["release_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    pointer_path.write_text(
        json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _bind_release_local_python(runtime: Path, release_root: Path) -> Path:
    relative = (
        Path(".venv") / "Scripts" / "python.exe"
        if os.name == "nt"
        else Path(".venv") / "bin" / "python"
    )
    release_python = release_root / relative
    release_python.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(sys.executable), release_python)
    source_venv_config = Path(sys.prefix) / "pyvenv.cfg"
    if source_venv_config.is_file():
        shutil.copy2(source_venv_config, release_root / ".venv" / "pyvenv.cfg")
    _rewrite_release_python_binding(runtime, release_root, release_python)
    return release_python


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
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--runtime-root", required=True)
parser.add_argument("--epoch-id", required=True)
parser.add_argument("--collector-command-json", required=True)
args, _ = parser.parse_known_args()
collector_command = json.loads(args.collector_command_json)
collector = subprocess.run(
    collector_command,
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
json.loads(collector.stdout)
if args.epoch_id == "epoch-hold-release-handles":
    ready = Path(args.runtime_root) / "epoch-process-ready.txt"
    release = Path(args.runtime_root) / "release-epoch-process.txt"
    ready.write_text("ready", encoding="utf-8")
    while not release.exists():
        time.sleep(0.01)
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
    collector_marker = runtime / "real-collector-ran.txt"
    (target_directory / "quota-query.mjs").write_text(
        "import fs from 'node:fs';\n"
        f"fs.writeFileSync({json.dumps(str(collector_marker))}, 'ran', 'utf8');\n"
        "process.stdout.write(JSON.stringify({fixture: true}));\n",
        encoding="utf-8",
        newline="\n",
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
    _bind_release_local_python(runtime, Path(built["release_root"]))
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


def _run_direct_consumer(script: Path, runtime: Path) -> subprocess.CompletedProcess[str]:
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
    runtime, release_root, script, source, _ = _release_fixture(tmp_path)
    manifest = json.loads((release_root / "release_manifest.json").read_text(encoding="utf-8"))
    release_python = Path(manifest["python_executable"])
    assert release_python.resolve(strict=True).is_relative_to(release_root.resolve(strict=True))
    pointer = runtime / "state" / "grok_supervisor_selector" / "current.json"
    execution_binding = validate_selector_release_pointer(pointer)["execution_binding"]
    bound_python = Path(execution_binding["python"]["path"])
    assert bound_python == release_python
    assert bound_python.resolve(strict=True).is_relative_to(release_root.resolve(strict=True))
    _retire_fixture_source(source)

    completed = _run_consumer(script, runtime, "epoch-source-retired")

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["snapshot"]["epoch_id"] == "epoch-source-retired"
    assert (runtime / "validated-epoch-script-ran.txt").read_text(encoding="utf-8") == (
        "epoch-source-retired"
    )
    assert (runtime / "real-collector-ran.txt").read_text(encoding="utf-8") == "ran"
    installed = script.read_text(encoding="utf-8")
    assert "__XINAO_SELECTOR_VALIDATOR_BINDING_SHA256__" not in installed
    assert "__XINAO_SELECTOR_VALIDATOR_BINDING_BASE64__" not in installed
    assert "embedded base64" in installed
    assert '"-I", "-S", "-B"' in installed
    assert "CreateNoWindow = $true" in installed
    assert "UseShellExecute = $false" in installed
    assert "ProcessWindowStyle]::Hidden" in installed


@pytest.mark.skipif(os.name != "nt", reason="Windows installed direct consumer")
def test_installed_direct_consumer_executes_bound_collector_after_source_deletion(
    tmp_path: Path,
) -> None:
    runtime, _, script, source, _ = _release_fixture(tmp_path)
    _retire_fixture_source(source)

    completed = _run_direct_consumer(script, runtime)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["fixture"] is True
    assert (runtime / "real-collector-ran.txt").read_text(encoding="utf-8") == "ran"


@pytest.mark.skipif(os.name != "nt", reason="Windows installed collector binding")
def test_collector_drift_is_rejected_before_epoch_or_collector_effect(tmp_path: Path) -> None:
    runtime, _, script, _, _ = _release_fixture(tmp_path)
    collector = script.parent / "quota-query.mjs"
    collector.write_bytes(collector.read_bytes() + b"\n// drift\n")

    completed = _run_consumer(script, runtime, "epoch-collector-drift")

    assert completed.returncode != 0
    assert "XINAO_QUOTA_COLLECTOR_HASH_MISMATCH" in completed.stderr
    assert not (runtime / "real-collector-ran.txt").exists()
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installed collector binding")
def test_collector_symlink_is_rejected_before_direct_effect(tmp_path: Path) -> None:
    runtime, _, script, _, _ = _release_fixture(tmp_path)
    collector = script.parent / "quota-query.mjs"
    identical_target = tmp_path / "identical-collector.mjs"
    identical_target.write_bytes(collector.read_bytes())
    collector.unlink()
    try:
        collector.symlink_to(identical_target)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    completed = _run_direct_consumer(script, runtime)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_COLLECTOR_REPARSE_POINT" in completed.stderr
    assert not (runtime / "real-collector-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installed Node binding")
def test_node_symlink_is_rejected_before_direct_collector_effect(tmp_path: Path) -> None:
    runtime, _, script, _, _ = _release_fixture(tmp_path)
    binding, _ = _embedded_binding(script)
    original_node = Path(str(binding["node"]["path"]))
    node_link = tmp_path / "node-link.exe"
    try:
        node_link.symlink_to(original_node)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    binding["node"]["path"] = str(node_link)
    _rewrite_embedded_binding(script, binding)

    completed = _run_direct_consumer(script, runtime)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_NODE_REPARSE_POINT" in completed.stderr
    assert not (runtime / "real-collector-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installed binding schema")
def test_installed_consumer_rejects_legacy_v1_embedded_binding(tmp_path: Path) -> None:
    runtime, _, script, _, _ = _release_fixture(tmp_path)
    binding, _ = _embedded_binding(script)
    binding["schema_version"] = "xinao.selector_validator_binding.v1"
    _rewrite_embedded_binding(script, binding)

    completed = _run_direct_consumer(script, runtime)

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_VALIDATOR_BINDING_INVALID: schema mismatch" in completed.stderr
    assert not (runtime / "real-collector-ran.txt").exists()


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
def test_external_binding_file_cannot_redirect_embedded_validator(tmp_path: Path) -> None:
    runtime, _, script, _, _ = _release_fixture(tmp_path)
    binding_path = script.parent / BINDING_NAME
    binding, _ = _embedded_binding(script)
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

    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
    assert (runtime / "validated-epoch-script-ran.txt").read_text(encoding="utf-8") == (
        "epoch-malicious-binding"
    )


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


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point consumer")
def test_validator_python_symlink_is_rejected_before_any_epoch_effect(tmp_path: Path) -> None:
    runtime, _, script, _, receipt = _release_fixture(tmp_path)
    binding, _ = _embedded_binding(script)
    original_python = Path(str(receipt["validator_python_ref"]))
    python_link = tmp_path / "validator-python-link.exe"
    try:
        python_link.symlink_to(original_python)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    binding["python_executable"] = str(python_link)
    _rewrite_embedded_binding(script, binding)

    completed = _run_consumer(script, runtime, "epoch-validator-python-symlink")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_VALIDATOR_PYTHON_REPARSE_POINT" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point consumer")
def test_validator_ancestor_symlink_is_rejected_before_any_epoch_effect(tmp_path: Path) -> None:
    runtime, _, script, _, receipt = _release_fixture(tmp_path)
    binding, _ = _embedded_binding(script)
    validator_root = Path(str(receipt["validator_root"]))
    parent_link = tmp_path / "validator-parent-link"
    try:
        parent_link.symlink_to(validator_root.parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation is unavailable: {exc}")
    binding["validator_root"] = str(parent_link / validator_root.name)
    _rewrite_embedded_binding(script, binding)

    completed = _run_consumer(script, runtime, "epoch-validator-ancestor-symlink")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_VALIDATOR_CLOSURE_REPARSE_POINT" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point consumer")
def test_release_epoch_symlink_is_rejected_after_static_validation(tmp_path: Path) -> None:
    runtime, release_root, script, _, _ = _release_fixture(tmp_path)
    epoch = release_root / "scripts" / "quota_dispatch_epoch.py"
    identical_target = release_root / "scripts" / "unlisted-identical-epoch.py"
    identical_target.write_bytes(epoch.read_bytes())
    epoch.unlink()
    try:
        epoch.symlink_to(identical_target)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    completed = _run_consumer(script, runtime, "epoch-release-symlink")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_RELEASE_EXECUTION_REPARSE_POINT" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point consumer")
def test_release_python_symlink_is_rejected_before_epoch_execution(tmp_path: Path) -> None:
    runtime, release_root, script, _, _ = _release_fixture(tmp_path)
    python_link = tmp_path / "release-python-link.exe"
    try:
        python_link.symlink_to(Path(sys.executable))
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    _rewrite_release_python_binding(runtime, release_root, python_link)

    completed = _run_consumer(script, runtime, "epoch-release-python-symlink")

    assert completed.returncode != 0
    assert "XINAO_SELECTOR_RELEASE_PYTHON_REPARSE_POINT" in completed.stderr
    assert not (runtime / "validated-epoch-script-ran.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows held-handle execution consumer")
def test_release_epoch_object_remains_locked_through_process_exit(tmp_path: Path) -> None:
    runtime, release_root, script, _, _ = _release_fixture(tmp_path)
    epoch = release_root / "scripts" / "quota_dispatch_epoch.py"
    ready = runtime / "epoch-process-ready.txt"
    release = runtime / "release-epoch-process.txt"
    consumer = subprocess.Popen(
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
            "epoch-hold-release-handles",
            "-NoLiveCodex",
            "-Json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), consumer.communicate(timeout=1)
        replacement = tmp_path / "malicious-epoch.py"
        replacement.write_text(
            "from pathlib import Path\nPath('malicious-marker').write_text('ran')\n",
            encoding="utf-8",
        )
        with pytest.raises(OSError):
            os.replace(replacement, epoch)
        release.write_text("release", encoding="utf-8")
        stdout, stderr = consumer.communicate(timeout=15)
        assert consumer.returncode == 0, stderr
        assert json.loads(stdout.splitlines()[-1])["snapshot"]["epoch_id"] == (
            "epoch-hold-release-handles"
        )
    finally:
        release.write_text("release", encoding="utf-8")
        if consumer.poll() is None:
            consumer.kill()
            consumer.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer consumer")
def test_installer_publishes_hash_bound_validator_and_receipt_readback(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    expected_head = _git_head(source)
    runtime = tmp_path / "install-runtime"

    installed, receipt = _install_consumer(source, runtime)

    embedded_binding, binding_bytes = _embedded_binding(installed)
    binding_sha = hashlib.sha256(binding_bytes).hexdigest()
    persisted_path = Path(str(receipt["receipt_ref"]))
    persisted_bytes = persisted_path.read_bytes()
    persisted = json.loads(persisted_bytes)
    assert receipt["source_git_head"] == expected_head
    assert binding_sha in installed.read_text(encoding="utf-8")
    assert receipt["validator_binding_storage"] == "embedded_base64"
    assert receipt["validator_binding_sha256"] == binding_sha
    assert embedded_binding["schema_version"] == "xinao.selector_validator_binding.v2"
    assert embedded_binding["collector"]["sha256"] == receipt["collector_sha256"]
    assert embedded_binding["node"]["sha256"] == receipt["node_sha256"]
    assert embedded_binding["python_candidate"]["path"] == receipt["validator_python_candidate_ref"]
    assert (
        embedded_binding["python_candidate"]["sha256"]
        == receipt["validator_python_candidate_sha256"]
    )
    assert (
        embedded_binding["python_candidate"]["size_bytes"]
        == receipt["validator_python_candidate_size_bytes"]
    )
    assert receipt["target_sha256"] == hashlib.sha256(installed.read_bytes()).hexdigest()
    assert receipt["receipt_sha256"] == hashlib.sha256(persisted_bytes).hexdigest()
    assert persisted["validator_binding_sha256"] == binding_sha
    assert embedded_binding["validator_root"] == persisted["validator_root"]
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


@pytest.mark.skipif(os.name != "nt", reason="Windows installer namespace")
def test_installer_rejects_runtime_root_ancestor_symlink_before_publish(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    runtime = tmp_path / "physical-runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    (target_directory / "quota-query.mjs").write_text(
        "process.stdout.write('{}');\n", encoding="utf-8", newline="\n"
    )
    runtime_link = tmp_path / "runtime-link"
    try:
        runtime_link.symlink_to(runtime, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation is unavailable: {exc}")

    completed = _run_installer(source, runtime_link)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_INSTALL_NAMESPACE_REPARSE_POINT" in completed.stderr
    assert not (target_directory / "Get-AIQuota.ps1").exists()
    assert not (runtime / "state" / "quota_query_releases").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installer namespace")
def test_installer_rejects_lock_leaf_symlink_before_critical_section(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    runtime = tmp_path / "runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    (target_directory / "quota-query.mjs").write_text(
        "process.stdout.write('{}');\n", encoding="utf-8", newline="\n"
    )
    external_lock = tmp_path / "external-lock.txt"
    external_lock.write_text("not a lock", encoding="utf-8")
    try:
        (target_directory / ".install.lock").symlink_to(external_lock)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    completed = _run_installer(source, runtime)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_INSTALL_LOCK_REPARSE_POINT" in completed.stderr
    assert not (target_directory / "Get-AIQuota.ps1").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installer namespace")
def test_installer_rejects_existing_target_leaf_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    runtime = tmp_path / "runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    (target_directory / "quota-query.mjs").write_text(
        "process.stdout.write('{}');\n", encoding="utf-8", newline="\n"
    )
    external_target = tmp_path / "external-target.ps1"
    external_target.write_text("# external\n", encoding="utf-8")
    try:
        (target_directory / "Get-AIQuota.ps1").symlink_to(external_target)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    completed = _run_installer(source, runtime)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_INSTALL_TARGET_REPARSE_POINT" in completed.stderr
    assert external_target.read_text(encoding="utf-8") == "# external\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows installer namespace")
def test_installer_rejects_collector_leaf_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    runtime = tmp_path / "runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    external_collector = tmp_path / "external-collector.mjs"
    external_collector.write_text("process.stdout.write('{}');\n", encoding="utf-8", newline="\n")
    try:
        (target_directory / "quota-query.mjs").symlink_to(external_collector)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")

    completed = _run_installer(source, runtime)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_INSTALL_FILE_REPARSE_POINT" in completed.stderr
    assert not (target_directory / "Get-AIQuota.ps1").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installer Python binding")
def test_installer_rejects_python_candidate_symlink_before_execution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    python_candidate = source / ".venv" / "Scripts" / "python.exe"
    python_candidate.parent.mkdir(parents=True)
    try:
        python_candidate.symlink_to(Path(sys.executable))
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    runtime = tmp_path / "runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    (target_directory / "quota-query.mjs").write_text(
        "process.stdout.write('{}');\n", encoding="utf-8", newline="\n"
    )

    completed = _run_installer(source, runtime)

    assert completed.returncode != 0
    assert "XINAO_QUOTA_INSTALL_FILE_REPARSE_POINT" in completed.stderr
    assert not (target_directory / "Get-AIQuota.ps1").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows installer Python binding")
def test_installer_ignores_marker_writing_python_cmd_without_execution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_release_source(source)
    _git_head(source)
    runtime = tmp_path / "runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    (target_directory / "quota-query.mjs").write_text(
        "process.stdout.write('{}');\n", encoding="utf-8", newline="\n"
    )
    shim = tmp_path / "python-shim"
    shim.mkdir()
    marker = tmp_path / "python-shim-ran.txt"
    (shim / "python.cmd").write_text(
        f'@echo off\r\necho executed>"{marker}"\r\necho {sys.executable}\r\nexit /b 0\r\n',
        encoding="utf-8",
        newline="",
    )
    environment = dict(os.environ)
    environment["PATH"] = str(shim) + os.pathsep + environment.get("PATH", "")

    completed = _run_installer(source, runtime, environment=environment)

    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
    assert (target_directory / "Get-AIQuota.ps1").is_file()


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
                str(runtime).swapcase(),
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
        assert receipt["target_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert binding.read_bytes() == previous_binding
        assert not list(target_directory.glob("*.tmp"))
    finally:
        release.write_text("release", encoding="utf-8")
        if installer is not None and installer.poll() is None:
            installer.kill()
            installer.wait(timeout=5)
        if holder.poll() is None:
            holder.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer serialization")
def test_two_real_installers_linearize_as_complete_embedded_generations(tmp_path: Path) -> None:
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    _copy_release_source(source_a)
    _copy_release_source(source_b)
    _git_head(source_b)
    runtime = tmp_path / "two-installer-runtime"
    target_directory = runtime / "state" / "quota_query"
    target_directory.mkdir(parents=True)
    target = target_directory / "Get-AIQuota.ps1"
    initial = b"# initial consumer\n"
    target.write_bytes(initial)
    (target_directory / "quota-query.mjs").write_text(
        "// installed fixture\n", encoding="utf-8", newline="\n"
    )

    shim = tmp_path / "git-a-shim"
    shim.mkdir()
    counter = tmp_path / "git-a-calls.txt"
    ready = tmp_path / "installer-a-inside-lock.txt"
    release = tmp_path / "release-installer-a.txt"
    fake_head = "a" * 40
    (shim / "git.cmd").write_text(
        "@echo off\r\n"
        f'if not exist "{counter}" (\r\n'
        f'  echo first>"{counter}"\r\n'
        f"  echo {fake_head}\r\n"
        "  exit /b 0\r\n"
        ")\r\n"
        f'echo second>>"{counter}"\r\n'
        f'echo ready>"{ready}"\r\n'
        ":wait\r\n"
        f'if exist "{release}" goto released\r\n'
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto wait\r\n"
        ":released\r\n"
        f"echo {fake_head}\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
        newline="",
    )
    environment_a = dict(os.environ)
    environment_a["PATH"] = str(shim) + os.pathsep + environment_a.get("PATH", "")

    command = lambda source: [  # noqa: E731 - keeps the two process calls identical
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
    ]
    installer_a = subprocess.Popen(
        command(source_a),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment_a,
    )
    installer_b: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), installer_a.communicate(timeout=1)

        installer_b = subprocess.Popen(
            command(source_b),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        time.sleep(0.25)
        assert installer_b.poll() is None
        release.write_text("release", encoding="utf-8")

        stdout_a, stderr_a = installer_a.communicate(timeout=45)
        stdout_b, stderr_b = installer_b.communicate(timeout=45)
        assert installer_a.returncode == 0, stderr_a
        assert installer_b.returncode == 0, stderr_b
        receipt_a = json.loads(stdout_a)
        receipt_b = json.loads(stdout_b)
        assert receipt_a["previous_sha256"] == hashlib.sha256(initial).hexdigest()
        assert receipt_b["previous_sha256"] == receipt_a["target_sha256"]
        assert receipt_a["target_sha256"] != receipt_b["target_sha256"]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == receipt_b["target_sha256"]
        final_binding, _ = _embedded_binding(target)
        assert final_binding["validator_root"] == receipt_b["validator_root"]
        assert Path(str(receipt_a["receipt_ref"])).is_file()
        assert Path(str(receipt_b["receipt_ref"])).is_file()
        assert not list(target_directory.glob("*.tmp"))
    finally:
        release.write_text("release", encoding="utf-8")
        for process in (installer_a, installer_b):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)


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
