from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from services.agent_runtime import integrated_bus_worker_daemon as daemon

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeWorker:
    def __init__(self, *, running: bool = False) -> None:
        self.is_running = running


def _ready_marker() -> dict[str, object]:
    return {
        "schema_version": daemon.SCHEMA_VERSION,
        "sentinel": daemon.SENTINEL,
        "status": "polling",
        "readiness_confirmed": True,
        "container_id": "container-generation",
        "process_id": 1,
        "process_start_ticks": "987654",
        "binding_count": 3,
        "worker_context_count": 3,
        "all_workers_running": True,
        "workflow_roles": {
            "XinaoScienceEpisodeWorkflowV1": "CURRENT_SCIENCE_ENTRY",
            "XinaoResearchCampaignWorkflow": "LEGACY_REPLAY",
        },
    }


def _source_release_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, dict[str, object]]:
    commit = "a" * 40
    runtime_root = tmp_path / "runtime"
    app_root = tmp_path / "app"
    files: dict[str, dict[str, str]] = {}
    for relative in daemon.SOURCE_RELEASE_CRITICAL_FILES:
        path = app_root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
        files[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        "schema_version": daemon.SOURCE_RELEASE_SCHEMA_VERSION,
        "commit": commit,
        "files": files,
    }
    manifest_path = (
        runtime_root / "state" / "s_runtime_releases" / f"{commit}.release-manifest.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("XINAO_S_RUNTIME_RELEASE_COMMIT", commit)
    monkeypatch.setenv(
        "XINAO_S_RUNTIME_RELEASE_MANIFEST_SHA256",
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    expected = daemon.source_release_identity(
        runtime_root=runtime_root,
        app_root=app_root,
    )
    return runtime_root, app_root, expected


def test_readiness_marker_binds_current_container_and_process_generation() -> None:
    marker = _ready_marker()
    assert (
        daemon.readiness_marker_issues(
            marker,
            expected_container_id="container-generation",
            expected_process_id=1,
            expected_process_start_ticks="987654",
        )
        == []
    )

    marker["process_start_ticks"] = "stale-generation"
    assert "process_generation_mismatch" in daemon.readiness_marker_issues(
        marker,
        expected_container_id="container-generation",
        expected_process_id=1,
        expected_process_start_ticks="987654",
    )


def test_source_release_identity_binds_manifest_and_mounted_critical_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root, app_root, expected = _source_release_fixture(tmp_path, monkeypatch)
    assert expected["status"] == "VERIFIED"
    assert expected["commit"] == "a" * 40
    assert len(expected["critical_files"]) == len(daemon.SOURCE_RELEASE_CRITICAL_FILES)

    drifted = app_root / "services" / "agent_runtime" / "integrated_bus_worker_daemon.py"
    drifted.write_text("drift\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="critical file drifted"):
        daemon.source_release_identity(
            runtime_root=runtime_root,
            app_root=app_root,
        )


def test_readiness_marker_rejects_source_release_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, expected = _source_release_fixture(tmp_path, monkeypatch)
    marker = _ready_marker()
    marker["source_release"] = expected
    assert (
        daemon.readiness_marker_issues(
            marker,
            expected_container_id="container-generation",
            expected_process_id=1,
            expected_process_start_ticks="987654",
            expected_source_release=expected,
        )
        == []
    )
    marker["source_release"] = {**expected, "commit": "b" * 40}
    assert "source_release_identity_mismatch" in daemon.readiness_marker_issues(
        marker,
        expected_container_id="container-generation",
        expected_process_id=1,
        expected_process_start_ticks="987654",
        expected_source_release=expected,
    )


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("status", "starting", "status_not_polling"),
        ("readiness_confirmed", False, "readiness_not_confirmed"),
        ("container_id", "prior-container", "container_generation_mismatch"),
        ("worker_context_count", 2, "worker_context_count_mismatch"),
        ("all_workers_running", False, "workers_not_running"),
    ],
)
def test_readiness_marker_rejects_pre_poll_and_stale_state(
    field: str, value: object, issue: str
) -> None:
    marker = _ready_marker()
    marker[field] = value
    assert issue in daemon.readiness_marker_issues(
        marker,
        expected_container_id="container-generation",
        expected_process_id=1,
        expected_process_start_ticks="987654",
    )


def test_polling_gate_waits_for_temporal_worker_state() -> None:
    worker = _FakeWorker()

    async def exercise() -> None:
        async def promote() -> None:
            await asyncio.sleep(0)
            worker.is_running = True

        promote_task = asyncio.create_task(promote())
        await daemon._wait_for_workers_polling([worker], timeout_seconds=0.5)
        await promote_task

    asyncio.run(exercise())


def test_polling_gate_fails_when_no_worker_can_poll() -> None:
    with pytest.raises(RuntimeError, match="no Temporal worker bindings"):
        asyncio.run(daemon._wait_for_workers_polling([], timeout_seconds=0.01))


def test_polling_gate_times_out_before_publishing_false_readiness() -> None:
    with pytest.raises(TimeoutError, match="did not enter polling state"):
        asyncio.run(daemon._wait_for_workers_polling([_FakeWorker()], timeout_seconds=0.001))


def test_compose_healthcheck_invokes_generation_aware_readiness() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["houtai-gongren"]["environment"]
    assert "XINAO_S_RUNTIME_RELEASE_COMMIT" in environment
    assert "XINAO_S_RUNTIME_RELEASE_MANIFEST_SHA256" in environment
    healthcheck = compose["services"]["houtai-gongren"]["healthcheck"]["test"]
    assert healthcheck == [
        "CMD",
        "python",
        "-m",
        "services.agent_runtime.integrated_bus_worker_daemon",
        "--runtime-root",
        "/evidence",
        "--check-readiness",
    ]
    dockerfile = (REPO_ROOT / "docker" / "houtai-gongren" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "--runtime-root /evidence --check-readiness" in dockerfile
    assert "test -f /evidence/state/integrated_bus_worker_daemon/latest.json" not in dockerfile


def test_start_script_returns_nonzero_for_partial_state(tmp_path: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is unavailable")
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    if os.name == "nt":
        docker_shim = shim_dir / "docker.cmd"
        docker_shim.write_text(
            "@echo off\r\n"
            'if "%1"=="ps" (\r\n'
            '  if "%2"=="--format" echo naijiu-shiwu\r\n'
            ")\r\n"
            "exit /b 0\r\n",
            encoding="utf-8",
        )
    else:
        docker_shim = shim_dir / "docker"
        docker_shim.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "ps" ] && [ "$2" = "--format" ]; then\n'
            "  echo naijiu-shiwu\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        docker_shim.chmod(0o755)
    runtime_root = tmp_path / "runtime"
    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    completed = subprocess.run(
        [
            shell,
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(REPO_ROOT / "scripts" / "Start-XinaoBaseCompose.ps1"),
            "-RepoRoot",
            str(REPO_ROOT),
            "-RuntimeRoot",
            str(runtime_root),
            "-Service",
            "shiwu-ku",
            "-Quiet",
            "-AsJson",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert '"status": "partial"' in completed.stdout


def test_start_script_waits_for_worker_health_before_running_claim() -> None:
    script = (REPO_ROOT / "scripts" / "Start-XinaoBaseCompose.ps1").read_text(encoding="utf-8")
    assert '$dargs += @("--wait", "--wait-timeout", "120")' in script
    assert '$workerState -eq "running/healthy"' in script
    assert 'if ($report.status -eq "running") { exit 0 }' in script
    assert "WORKER_NOT_READY" in script
