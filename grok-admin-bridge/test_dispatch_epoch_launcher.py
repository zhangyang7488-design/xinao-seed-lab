from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "launchers" / "Invoke-Codex-GrokWorkerPool.ps1"
PWSH = shutil.which("pwsh")


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(value).lstrip(), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    runtime = tmp_path / "runtime"
    bridge = tmp_path / "bridge"
    capture = tmp_path / "dispatch-capture.jsonl"
    package_capture = tmp_path / "package-capture.jsonl"
    launcher = tmp_path / "Invoke-Codex-GrokWorkerPool.ps1"
    launcher_text = LAUNCHER.read_text(encoding="utf-8-sig").replace(
        '$bridgeRoot = "C:\\Users\\xx363\\Grok_Admin_Isolated\\workspace\\grok-admin-bridge"',
        f'$bridgeRoot = "{str(bridge).replace(chr(92), chr(92) * 2)}"',
    )
    launcher.write_text(launcher_text, encoding="utf-8")

    _write(
        bridge / "Invoke-CodexDispatchGrokWorkerPool.ps1",
        r"""
        param(
            [int]$N, [string]$Prompt, [string]$PromptFile,
            [string]$Cwd, [string]$Model,
            [string]$SelectionPath, [string]$SupervisorRoot,
            [string]$SelectorReleasePointer, [string]$RuntimeRoot,
            [string]$MaxTurns, [int]$TimeoutSec, [string]$GrokHome,
            [int]$MinResultChars, [string[]]$RequiredResultMarkers,
            [string]$DispatchId, [string]$PoolId, [string]$CommonPythonExe,
            [string]$DispatchEpochId, [string]$DispatchEpochSource,
            [int]$DispatchEpochMaxAgeSec,
            [string]$QuotaSnapshotId, [string]$QuotaSnapshotRef,
            [string]$QuotaSnapshotSha256, [string]$QuotaResolutionStatus,
            [string]$QuotaResolutionError,
            [string]$CommonWorkKey, [string]$CommonOperationId,
            [string]$CommonSubjectManifestSha256,
            [string]$CommonFrozenContextSha256,
            [string]$CommonContextManifestPath,
            [string]$CommonRulesFile, [string]$CommonRulesSha256,
            [string]$CommonPhase, [switch]$Quiet
        )
        $row = [ordered]@{
            dispatch_epoch_id = $DispatchEpochId
            dispatch_epoch_source = $DispatchEpochSource
            quota_status = $QuotaResolutionStatus
            quota_snapshot_id = $QuotaSnapshotId
            common_work_key = $CommonWorkKey
            common_phase = $CommonPhase
            common_frozen_context_sha256 = $CommonFrozenContextSha256
            common_rules_file = $CommonRulesFile
        }
        Add-Content -LiteralPath $env:XINAO_EPOCH_CAPTURE -Value ($row | ConvertTo-Json -Compress)
        exit 0
        """,
    )
    _write(
        bridge / "Invoke-CodexGrokPackageBatch.ps1",
        r"""
        param(
            [string]$DispatchEnvelopePath, [string]$Model,
            [string]$RuntimeRoot, [string]$SelectorReleasePointer,
            [int]$TimeoutSec, [string]$TaskRunRoot, [string]$TaskRunId,
            [string]$TaskRunCli, [string]$CheckpointPath, [switch]$Quiet
        )
        $row = [ordered]@{
            dispatch_envelope_path = $DispatchEnvelopePath
            model = $Model
            task_run_root = $TaskRunRoot
            task_run_id = $TaskRunId
            task_run_cli = $TaskRunCli
            checkpoint_path = $CheckpointPath
        }
        Add-Content -LiteralPath $env:XINAO_PACKAGE_CAPTURE -Value ($row | ConvertTo-Json -Compress)
        exit 0
        """,
    )
    _write(
        bridge / "Prepare-CodexGrokTaskLocalCheckpoint.ps1",
        r"""
        param(
            [string]$RuntimeRoot, [string]$SelectorReleasePointer,
            [string]$TaskRunRoot, [string]$TaskRunId, [string]$CheckpointPath,
            [string]$DispatchEnvelopePath, [string]$TaskRunCli
        )
        $taskRoot = [IO.Path]::GetFullPath($TaskRunRoot)
        $taskRun = [IO.Path]::GetFullPath((Join-Path $taskRoot $TaskRunId))
        $canonical = [IO.Path]::GetFullPath((Join-Path $taskRun "task-local-checkpoint.v2.json"))
        if ([string]::IsNullOrWhiteSpace($CheckpointPath)) {
            $CheckpointPath = $canonical
        } else {
            $CheckpointPath = [IO.Path]::GetFullPath($CheckpointPath)
        }
        if (-not [string]::Equals($CheckpointPath, $canonical, [StringComparison]::OrdinalIgnoreCase)) {
            throw "CHECKPOINT_PATH_OUTSIDE_TASK_RUN"
        }
        $quotaCountPath = Join-Path $RuntimeRoot "live-query-count.txt"
        $quotaCount = if (Test-Path -LiteralPath $quotaCountPath) {
            [int](Get-Content -LiteralPath $quotaCountPath -Raw)
        } else { 0 }
        New-Item -ItemType Directory -Force -Path $taskRun | Out-Null
        [IO.File]::WriteAllText($CheckpointPath, "{}")
        $capture = Join-Path $RuntimeRoot "checkpoint-preflight.jsonl"
        $row = [ordered]@{
            checkpoint_path = $CheckpointPath
            task_run_id = $TaskRunId
            quota_query_count = $quotaCount
            dispatch_envelope_path = $DispatchEnvelopePath
            task_run_cli = $TaskRunCli
        }
        Add-Content -LiteralPath $capture -Value ($row | ConvertTo-Json -Compress)
        $packageMode = -not [string]::IsNullOrWhiteSpace($DispatchEnvelopePath)
        [pscustomobject]@{
            schema_version = if ($packageMode) {
                "xinao.worker_package_task_run_preflight.v1"
            } else {
                "xinao.checkpoint_task_run_binding.v1"
            }
            checkpoint_path = $CheckpointPath
            run_id = $TaskRunId
            cursor = 1
            event_count = 1
            package_ids = if ($packageMode) { @("p1") } else { @() }
            work_keys = if ($packageMode) { @("wk-1") } else { @() }
            model_invocation_allowed = $packageMode
            authority = $false
            completion_claim_allowed = $false
        }
        """,
    )
    _write(
        runtime / "state" / "quota_query" / "Get-AIQuota.ps1",
        r"""
        param(
            [switch]$Json, [string]$EpochId, [string]$InvalidateReason,
            [string]$RuntimeRoot
        )
        $ErrorActionPreference = "Stop"
        $epochRoot = Join-Path $RuntimeRoot ("state\quota_dispatch_epochs\" + $EpochId)
        New-Item -ItemType Directory -Force -Path $epochRoot | Out-Null
        $current = Join-Path $epochRoot "current.json"
        $status = "cache_hit"
        if (-not (Test-Path -LiteralPath $current) -or -not [string]::IsNullOrWhiteSpace($InvalidateReason)) {
            $countPath = Join-Path $RuntimeRoot "live-query-count.txt"
            $count = if (Test-Path -LiteralPath $countPath) { [int](Get-Content -LiteralPath $countPath -Raw) } else { 0 }
            $count += 1
            [IO.File]::WriteAllText($countPath, [string]$count)
            $generation = 1
            if (Test-Path -LiteralPath $current) {
                $previous = Get-Content -LiteralPath $current -Raw | ConvertFrom-Json
                $generation = [int]$previous.generation + 1
            }
            $snapshot = [ordered]@{
                epoch_id = $EpochId
                generation = $generation
                snapshot_id = "snapshot-$count"
                queried_at = [DateTimeOffset]::UtcNow.ToString("o")
                snapshot_ref = (Join-Path $epochRoot "snapshot.json")
                snapshot_sha256 = ("{0:x64}" -f $count)
            }
            [IO.File]::WriteAllText($current, ($snapshot | ConvertTo-Json -Compress))
            $status = "refreshed"
        }
        $snapshot = Get-Content -LiteralPath $current -Raw | ConvertFrom-Json
        [ordered]@{
            schema_version = "xinao.quota_dispatch_epoch_resolution.v1"
            status = $status
            snapshot = $snapshot
            dispatch_blocked = $false
        } | ConvertTo-Json -Compress
        exit 0
        """,
    )
    return launcher, runtime, capture, package_capture


def _run(
    launcher: Path,
    runtime: Path,
    capture: Path,
    package_capture: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    env = {
        **os.environ,
        "XINAO_EPOCH_CAPTURE": str(capture),
        "XINAO_PACKAGE_CAPTURE": str(package_capture),
    }
    return subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(launcher),
            "-RuntimeRoot",
            str(runtime),
            "-Model",
            "grok-test",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _run_without_model(
    launcher: Path,
    runtime: Path,
    capture: Path,
    package_capture: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    env = {
        **os.environ,
        "XINAO_EPOCH_CAPTURE": str(capture),
        "XINAO_PACKAGE_CAPTURE": str(package_capture),
    }
    return subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(launcher),
            "-RuntimeRoot",
            str(runtime),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _ordinary_args(tmp_path: Path, episode_id: str) -> tuple[str, ...]:
    return (
        "-Prompt",
        "fixture-only",
        "-Cwd",
        str(tmp_path),
        "-TaskRunId",
        episode_id,
        "-Quiet",
    )


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_same_episode_reuses_quota_snapshot_across_fresh_processes(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)

    first = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        *_ordinary_args(tmp_path, "episode-a"),
    )
    second = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        *_ordinary_args(tmp_path, "episode-a"),
    )

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    rows = [json.loads(line) for line in capture.read_text().splitlines()]
    assert rows[0]["dispatch_epoch_id"] == rows[1]["dispatch_epoch_id"]
    assert rows[0]["dispatch_epoch_source"] == "task_run_id"
    assert [row["quota_status"] for row in rows] == ["refreshed", "cache_hit"]
    assert (runtime / "live-query-count.txt").read_text() == "1"


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_new_episode_expiry_and_explicit_invalidation_refresh_once_each(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    common = _ordinary_args(tmp_path, "episode-a")
    assert _run(launcher, runtime, capture, package_capture, *common).returncode == 0
    assert (
        _run(
            launcher,
            runtime,
            capture,
            package_capture,
            *_ordinary_args(tmp_path, "episode-b"),
        ).returncode
        == 0
    )
    assert (runtime / "live-query-count.txt").read_text() == "2"

    first_epoch = json.loads(capture.read_text().splitlines()[0])["dispatch_epoch_id"]
    current = runtime / "state" / "quota_dispatch_epochs" / first_epoch / "current.json"
    value = json.loads(current.read_text())
    value["queried_at"] = "2000-01-01T00:00:00Z"
    current.write_text(json.dumps(value), encoding="utf-8")
    expired = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        *common,
        "-DispatchEpochMaxAgeSec",
        "60",
    )
    assert expired.returncode == 0, expired.stdout + expired.stderr
    assert (runtime / "live-query-count.txt").read_text() == "3"

    invalidated = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        *common,
        "-InvalidateDispatchEpochReason",
        "provider-identity-changed",
    )
    assert invalidated.returncode == 0, invalidated.stdout + invalidated.stderr
    assert (runtime / "live-query-count.txt").read_text() == "4"


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_unscoped_ordinary_mode_fails_before_quota_or_provider(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    result = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-Prompt",
        "fixture-only",
        "-Cwd",
        str(tmp_path),
        "-Quiet",
    )
    assert result.returncode != 0
    assert (
        "CODEX_GROK_DISPATCH_EPISODE_IDENTITY_REQUIRED" in result.stdout + result.stderr
    )
    assert not capture.exists()
    assert not (runtime / "live-query-count.txt").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_ordinary_mode_still_requires_explicit_model_before_quota_or_provider(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    result = _run_without_model(
        launcher,
        runtime,
        capture,
        package_capture,
        "-Prompt",
        "fixture-only",
        "-Cwd",
        str(tmp_path),
        "-TaskRunId",
        "ordinary-model-required",
        "-Quiet",
    )
    assert result.returncode != 0
    assert "CODEX_GROK_MODEL_REQUIRED" in result.stdout + result.stderr
    assert not capture.exists()
    assert not package_capture.exists()
    assert not (runtime / "live-query-count.txt").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_common_contract_reports_all_caller_errors_before_quota_or_provider(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Inspect the sealed evidence.\n", encoding="utf-8")
    rules = tmp_path / "rules.txt"
    rules.write_text("Candidate-only read-only work.\n", encoding="utf-8")
    rules_sha256 = hashlib.sha256(rules.read_bytes()).hexdigest()

    result = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-PromptFile",
        str(prompt),
        "-Cwd",
        str(tmp_path),
        "-TaskRunId",
        "common-preflight-episode",
        "-CommonWorkKey",
        "work-a",
        "-CommonOperationId",
        "operation-a",
        "-CommonSubjectManifestSha256",
        "a" * 64,
        "-CommonRulesFile",
        str(rules),
        "-CommonRulesSha256",
        rules_sha256,
        "-CommonPhase",
        "AUDIT",
        "-RequiredResultMarkers",
        "MISSING_MARKER",
        "-Quiet",
    )

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode != 0
    assert "CODEX_GROK_COMMON_PREFLIGHT_FAILED" in output
    assert "CommonPhase must be one of EXPLORE" in output
    assert "CONSTRUCT, VERIFY, LAND" in output
    assert "CommonFrozenContextSha256 or" in output
    assert "CommonContextManifestPath is required" in output
    assert "PromptFile must explicitly require result marker: MISSING_MARKER" in output
    assert not capture.exists()
    assert not package_capture.exists()
    assert not (runtime / "live-query-count.txt").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_valid_common_contract_preflight_reaches_dispatch_once(tmp_path: Path) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(
        "Inspect the sealed evidence and return EXPECTED_MARKER.\n", encoding="utf-8"
    )
    rules = tmp_path / "rules.txt"
    rules.write_text("Candidate-only read-only work.\n", encoding="utf-8")
    rules_sha256 = hashlib.sha256(rules.read_bytes()).hexdigest()

    result = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-PromptFile",
        str(prompt),
        "-Cwd",
        str(tmp_path),
        "-TaskRunId",
        "valid-common-preflight-episode",
        "-CommonWorkKey",
        "work-a",
        "-CommonOperationId",
        "operation-a",
        "-CommonSubjectManifestSha256",
        "a" * 64,
        "-CommonFrozenContextSha256",
        "b" * 64,
        "-CommonRulesFile",
        str(rules),
        "-CommonRulesSha256",
        rules_sha256,
        "-CommonPhase",
        "EXPLORE",
        "-RequiredResultMarkers",
        "EXPECTED_MARKER",
        "-Quiet",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (runtime / "live-query-count.txt").read_text() == "1"
    rows = [json.loads(line) for line in capture.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["common_work_key"] == "work-a"
    assert rows[0]["common_phase"] == "EXPLORE"
    assert rows[0]["common_frozen_context_sha256"] == "b" * 64
    assert Path(rows[0]["common_rules_file"]) == rules


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_package_mode_reuses_exact_sealed_epoch_and_rejects_expired_seal(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    quota = runtime / "state" / "quota_query" / "Get-AIQuota.ps1"
    seeded = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(quota),
            "-Json",
            "-EpochId",
            "package-episode",
            "-RuntimeRoot",
            str(runtime),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    resolution = json.loads(seeded.stdout.strip().splitlines()[-1])
    envelope = tmp_path / "dispatch-envelope.json"
    envelope.write_text(
        json.dumps(
            {
                "dispatch_epoch": {
                    "epoch_id": "package-episode",
                    "quota_snapshot_id": resolution["snapshot"]["snapshot_id"],
                    "quota_snapshot_ref": resolution["snapshot"]["snapshot_ref"],
                    "quota_snapshot_sha256": resolution["snapshot"]["snapshot_sha256"],
                },
                "selection": {"model_id": "grok-test"},
            }
        ),
        encoding="utf-8",
    )
    task_run_root = tmp_path / "task-runs"
    task_run_dir = task_run_root / "run-1"
    task_run_dir.mkdir(parents=True)
    checkpoint = task_run_dir / "task-local-checkpoint.v2.json"
    task_run_cli = tmp_path / "task_run.py"
    task_run_cli.write_text("# fixture", encoding="utf-8")
    package_claim_args = (
        "-TaskRunRoot",
        str(task_run_root),
        "-TaskRunId",
        "run-1",
        "-TaskRunCli",
        str(task_run_cli),
    )
    accepted = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-DispatchEnvelopePath",
        str(envelope),
        *package_claim_args,
        "-Quiet",
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert (runtime / "live-query-count.txt").read_text() == "1"
    assert package_capture.exists()
    package_row = json.loads(package_capture.read_text().splitlines()[-1])
    assert package_row["task_run_id"] == "run-1"
    assert Path(package_row["checkpoint_path"]) == checkpoint
    assert Path(package_row["task_run_cli"]) == task_run_cli
    checkpoint_rows = [
        json.loads(line)
        for line in (runtime / "checkpoint-preflight.jsonl").read_text().splitlines()
    ]
    assert checkpoint_rows == [
        {
            "checkpoint_path": str(checkpoint),
            "task_run_id": "run-1",
            "quota_query_count": 1,
            "dispatch_envelope_path": str(envelope),
            "task_run_cli": str(task_run_cli),
        }
    ]

    derived_model = _run_without_model(
        launcher,
        runtime,
        capture,
        package_capture,
        "-DispatchEnvelopePath",
        str(envelope),
        *package_claim_args,
        "-Quiet",
    )
    assert derived_model.returncode == 0, derived_model.stdout + derived_model.stderr
    package_rows = [
        json.loads(line) for line in package_capture.read_text().splitlines()
    ]
    assert package_rows[-1]["model"] == "grok-test"

    mismatch_envelope = tmp_path / "dispatch-envelope-model-mismatch.json"
    mismatch_value = json.loads(envelope.read_text(encoding="utf-8"))
    mismatch_value["selection"]["model_id"] = "different-model"
    mismatch_envelope.write_text(json.dumps(mismatch_value), encoding="utf-8")
    mismatch_fixture_root = tmp_path / "model-mismatch-fixture"
    mismatch_fixture_root.mkdir()
    (
        mismatch_launcher,
        mismatch_runtime,
        mismatch_capture,
        mismatch_package_capture,
    ) = _fixture(mismatch_fixture_root)
    mismatch_task_run_root = tmp_path / "model-mismatch-task-runs"
    mismatch_task_run_cli = tmp_path / "model-mismatch-task-run.py"
    mismatch_task_run_cli.write_text("# fixture", encoding="utf-8")
    mismatched_model = _run(
        mismatch_launcher,
        mismatch_runtime,
        mismatch_capture,
        mismatch_package_capture,
        "-DispatchEnvelopePath",
        str(mismatch_envelope),
        "-TaskRunRoot",
        str(mismatch_task_run_root),
        "-TaskRunId",
        "model-mismatch-run",
        "-TaskRunCli",
        str(mismatch_task_run_cli),
        "-Quiet",
    )
    assert mismatched_model.returncode != 0
    assert "CODEX_GROK_PACKAGE_MODEL_MISMATCH" in (
        mismatched_model.stdout + mismatched_model.stderr
    )
    assert not mismatch_package_capture.exists()
    assert not mismatch_capture.exists()
    assert not (mismatch_runtime / "checkpoint-preflight.jsonl").exists()
    assert not (mismatch_runtime / "live-query-count.txt").exists()
    assert not (mismatch_runtime / "state" / "quota_dispatch_epochs").exists()

    current = (
        runtime / "state" / "quota_dispatch_epochs" / "package-episode" / "current.json"
    )
    value = json.loads(current.read_text())
    value["queried_at"] = "2000-01-01T00:00:00Z"
    current.write_text(json.dumps(value), encoding="utf-8")
    rejected = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-DispatchEnvelopePath",
        str(envelope),
        *package_claim_args,
        "-DispatchEpochMaxAgeSec",
        "60",
        "-Quiet",
    )
    assert rejected.returncode != 0
    assert (
        "CODEX_GROK_PACKAGE_EPOCH_EXPIRED_RESEAL_REQUIRED"
        in rejected.stdout + rejected.stderr
    )
    assert (runtime / "live-query-count.txt").read_text() == "1"


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_package_checkpoint_preflight_rejects_shared_path_before_quota_or_package(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    envelope = tmp_path / "dispatch-envelope.json"
    envelope.write_text(
        json.dumps(
            {
                "dispatch_epoch": {"epoch_id": "package-episode"},
                "selection": {"model_id": "grok-test"},
            }
        ),
        encoding="utf-8",
    )
    task_run_root = tmp_path / "task-runs"
    (task_run_root / "run-1").mkdir(parents=True)
    shared_checkpoint = tmp_path / "session_checkpoint.json"
    shared_checkpoint.write_text("{}", encoding="utf-8")
    task_run_cli = tmp_path / "task_run.py"
    task_run_cli.write_text("# fixture", encoding="utf-8")

    rejected = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-DispatchEnvelopePath",
        str(envelope),
        "-CheckpointPath",
        str(shared_checkpoint),
        "-TaskRunRoot",
        str(task_run_root),
        "-TaskRunId",
        "run-1",
        "-TaskRunCli",
        str(task_run_cli),
        "-Quiet",
    )

    assert rejected.returncode != 0
    assert "CHECKPOINT_PATH_OUTSIDE_TASK_RUN" in rejected.stdout + rejected.stderr
    assert not (runtime / "live-query-count.txt").exists()
    assert not capture.exists()
    assert not package_capture.exists()
    assert not (runtime / "state" / "grok_worker_package_batches").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh is required")
def test_package_missing_task_run_cli_fails_before_checkpoint_quota_or_package(
    tmp_path: Path,
) -> None:
    launcher, runtime, capture, package_capture = _fixture(tmp_path)
    envelope = tmp_path / "dispatch-envelope.json"
    envelope.write_text(
        json.dumps(
            {
                "dispatch_epoch": {"epoch_id": "package-episode"},
                "selection": {"model_id": "grok-test"},
            }
        ),
        encoding="utf-8",
    )
    task_run_root = tmp_path / "task-runs"
    task_run_dir = task_run_root / "run-1"
    task_run_dir.mkdir(parents=True)
    missing_cli = tmp_path / "missing-task-run.py"

    rejected = _run(
        launcher,
        runtime,
        capture,
        package_capture,
        "-DispatchEnvelopePath",
        str(envelope),
        "-TaskRunRoot",
        str(task_run_root),
        "-TaskRunId",
        "run-1",
        "-TaskRunCli",
        str(missing_cli),
        "-Quiet",
    )

    assert rejected.returncode != 0
    assert "CODEX_GROK_TASK_RUN_CLI_MISSING" in rejected.stdout + rejected.stderr
    assert not (task_run_dir / "task-local-checkpoint.v2.json").exists()
    assert not (runtime / "checkpoint-preflight.jsonl").exists()
    assert not (runtime / "live-query-count.txt").exists()
    assert not capture.exists()
    assert not package_capture.exists()
    assert not (runtime / "state" / "grok_worker_package_batches").exists()
