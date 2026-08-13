from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, Mapping, Sequence

RUN_SCHEMA = "xinao.cleanroom.perpetual-world-compute-run.v2"
CONTROLLER_SCHEMA = "xinao.cleanroom.perpetual-world-compute-controller-state.v2"
LINEAGE_SCHEMA = "xinao.cleanroom.perpetual-world-compute-lineage-state.v2"
TURN_SCHEMA = "xinao.cleanroom.perpetual-world-compute-turn-receipt.v2"
PACKET_SCHEMA = "xinao.cleanroom.perpetual-world-compute-late-fusion-packet.v2"
STOP_SCHEMA = "xinao.cleanroom.perpetual-world-compute-stop-request.v2"
WAKE_SCHEMA = "xinao.cleanroom.perpetual-world-compute-wake-request.v2"
RECOVERY_SCHEMA = "xinao.cleanroom.world-compute-controller-recovery.v1"
ATTEMPT_RECOVERY_SCHEMA = "xinao.cleanroom.world-compute-attempt-recovery.v1"
DEEP_EVIDENCE_REF_SCHEMA = "xinao.cleanroom.world-compute-deep-evidence-ref.v1"
DEEP_EVIDENCE_TRAJECTORY_INDEX_SCHEMA = "xinao.cleanroom.world-compute-trajectory-index.v1"
DEEP_EVIDENCE_ARTIFACT_MANIFEST_SCHEMA = "xinao.cleanroom.world-compute-artifact-manifest.v1"
BODY_INCIDENT_SCHEMA = "xinao.cleanroom.world-compute-body-incident.v1"
WORLD_ISOLATED_LAUNCHER_SCHEMA = "xinao.cleanroom.world-isolated-launcher.v1"
WORLD_RUNTIME_BINDING_SCHEMA = "xinao.cleanroom.world-runtime-binding.v1"
WORLD_RUNTIME_BINDING_APPLIED_SCHEMA = "xinao.cleanroom.world-runtime-binding-applied.v1"
WORLD_TURN_QUOTA_LEASE_SCHEMA = "xinao.cleanroom.world-turn-quota-lease.v1"
RECOVERY_STATE_COMMIT_SCHEMA = "xinao.cleanroom.world-compute-recovery-state-commit.v1"
WORLD_RUNTIME_BINDING_REF_SCHEMA = "xinao.cleanroom.world-runtime-binding-ref.v1"
REALITY_MIGRATION_PREPARATION_SCHEMA = (
    "xinao.cleanroom.world-compute-reality-migration-preparation.v1"
)

LEGACY_RUN_SCHEMA = "xinao.cleanroom-c.perpetual-run.v1"
LEGACY_CONTROLLER_SCHEMA = "xinao.cleanroom-c.perpetual-controller-state.v1"
LEGACY_LINEAGE_SCHEMA = "xinao.cleanroom-c.perpetual-lineage-state.v1"
LEGACY_TURN_SCHEMA = "xinao.cleanroom-c.perpetual-turn-receipt.v1"
LEGACY_PACKET_SCHEMA = "xinao.cleanroom-c.late-fusion-packet.v1"
LEGACY_STOP_SCHEMA = "xinao.cleanroom-c.stop-request.v1"
LEGACY_WAKE_SCHEMA = "xinao.cleanroom-c.wake-request.v1"

_SCHEMA_FAMILIES = {
    RUN_SCHEMA: {
        "run": RUN_SCHEMA,
        "controller": CONTROLLER_SCHEMA,
        "lineage": LINEAGE_SCHEMA,
        "turn": TURN_SCHEMA,
        "packet": PACKET_SCHEMA,
        "stop": STOP_SCHEMA,
        "wake": WAKE_SCHEMA,
    },
    LEGACY_RUN_SCHEMA: {
        "run": LEGACY_RUN_SCHEMA,
        "controller": LEGACY_CONTROLLER_SCHEMA,
        "lineage": LEGACY_LINEAGE_SCHEMA,
        "turn": LEGACY_TURN_SCHEMA,
        "packet": LEGACY_PACKET_SCHEMA,
        "stop": LEGACY_STOP_SCHEMA,
        "wake": LEGACY_WAKE_SCHEMA,
    },
}

DEFAULT_SOURCE_REPO = Path(r"E:\CODEX_CLEANROOM\workspace")
DEFAULT_LAUNCHER = Path(r"E:\CODEX_CLEANROOM\Open-Codex-Cleanroom.ps1")
DEFAULT_POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_world_compute")
LEGACY_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_c")
DEDICATED_A_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_a")
DEFAULT_CLONE_ROOT = Path(r"E:\CODEX_CLEANROOM\research-lineages")
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "max"
DEFAULT_WIDTH = 4
DEFAULT_WATCHDOG_SECONDS = 6 * 60 * 60
DEFAULT_CONTINUATION_DELAY_SECONDS = 20
DEFAULT_RETRY_DELAYS_SECONDS = (60, 300, 900)
DEFAULT_PARK_POLL_SECONDS = 30
DEFAULT_WORLD_TURN_CONCURRENCY_LIMIT = 4
DEFAULT_WORLD_TURN_QUOTA_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_world_turn_quota")
DEFAULT_XINAO_LIVE_REALITY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\xinao\live-reality")
DEFAULT_XINAO_WORLD_COMPUTE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\xinao\world-compute")
ACCOUNT_SLOTS = ("A", "C")
CONTEXT_CONSUMER_TASK_NAME = r"\XINAO-S-Context-Rollout-Consumer-v1"


def request_context_consumer_wake(
    *,
    controller_state_path: Path | None = None,
    allowed_runtime_roots: Sequence[Path] | None = None,
    runner: Callable[..., object] | None = None,
    system_root: str | None = None,
) -> bool:
    """Best-effort notification for the optional S presentation sidecar.

    The frozen world-compute controller remains independent of S Context.  It
    only asks the already-installed current-user task to observe the state that
    was just committed; failure is contained and the scheduled watchdog can
    catch up later.
    """

    try:
        if controller_state_path is None:
            return False
        state_path = controller_state_path.resolve(strict=False)
        runtime_roots = tuple(
            Path(value).resolve(strict=False)
            for value in (
                allowed_runtime_roots
                if allowed_runtime_roots is not None
                else (DEFAULT_RUNTIME_ROOT, LEGACY_RUNTIME_ROOT, DEDICATED_A_RUNTIME_ROOT)
            )
        )
        if state_path.name != "controller_state.json" or not any(
            state_path != root and state_path.is_relative_to(root) for root in runtime_roots
        ):
            return False
        windows_root = system_root or os.environ.get("SystemRoot", "")
        if not windows_root:
            return False
        schtasks = Path(windows_root) / "System32" / "schtasks.exe"
        if not schtasks.is_file():
            return False
        invoke = runner or subprocess.Popen
        invoke(
            [str(schtasks), "/Run", "/TN", CONTEXT_CONSUMER_TASK_NAME],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False

LIFECYCLE_STATES = (
    "CONTINUE",
    "WAIT",
    "BLOCKED",
    "NO_POSITIVE_FRONTIER",
    "PAUSE",
)
PARKED_LIFECYCLE_STATES = tuple(state for state in LIFECYCLE_STATES if state != "CONTINUE")
_LIFECYCLE_RE = re.compile(
    r"(?im)^\s*XINAO_LINEAGE_STATE\s*:\s*"
    r"(CONTINUE|WAIT|BLOCKED|NO_POSITIVE_FRONTIER|PAUSE)\s*$"
)

_TRANSIENT_ERROR_TOKENS = (
    "429",
    "rate limit",
    "too many requests",
    "temporarily unavailable",
    "service unavailable",
    "overloaded",
    "connection reset",
    "connection aborted",
    "connection refused",
    "stream disconnected",
    "timed out",
    "timeout",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
)
_HARD_ERROR_TOKENS = (
    "401",
    "403",
    "authentication",
    "unauthorized",
    "forbidden",
    "login required",
    "invalid api key",
    "insufficient quota",
    "usage limit",
)

_DEEP_EVIDENCE_FORBIDDEN_PARTS = {
    ".git",
    ".sandbox",
    "cache",
    "sessions",
    "thread-writer-locks",
    "tmp",
    "user-home",
}
_DEEP_EVIDENCE_FORBIDDEN_NAMES = {
    "auth.json",
    "cap_sid",
    "cookies",
    "history.jsonl",
    "installation_id",
    "local state",
    "login data",
    "secure preferences",
    "web data",
}
_DEEP_EVIDENCE_CACHE_PARTS = {"__pycache__", ".mypy_cache", ".pytest_cache"}
_DEEP_EVIDENCE_CACHE_PARTS.update(
    {
        ".nox",
        ".ruff_cache",
        ".tox",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)
_DEEP_EVIDENCE_IGNORED_MATERIAL_ROOTS = (("xinao", "reality", "live"),)

_UNSANDBOXED_LAUNCH_LINE = (
    b"& $codexExe --cd $launchWorkdir --dangerously-bypass-approvals-and-sandbox "
    b"@slotSpecificCodexArgs @CodexArgs"
)
_WORLD_SANDBOXED_LAUNCH_LINE = (
    b"& $codexExe --cd $launchWorkdir --sandbox workspace-write "
    b"-c 'approval_policy=\"never\"' "
    b"-c 'sandbox_workspace_write.network_access=true' "
    b"@slotSpecificCodexArgs @CodexArgs"
)
_BODY_BOUNDARY_OS_DENIAL_TOKENS = (
    "access is denied",
    "access denied",
    "permission denied",
    "operation not permitted",
    "unauthorizedaccessexception",
    "write access denied",
    "write access is denied",
)
_WORLD_RUNTIME_BINDING_PARAM_SEAM = b'    [string]$CodexArgsFile = "",\r\n    [switch]$PrepareOnly,'
_WORLD_RUNTIME_BINDING_PARAM_REPLACEMENT = (
    b'    [string]$CodexArgsFile = "",\r\n'
    b'    [string]$WorldRuntimeBindingFile = "",\r\n'
    b'    [string]$ExpectedWorldRuntimeBindingSha256 = "",\r\n'
    b'    [string]$WorldRuntimeAppliedReceiptFile = "",\r\n'
    b'    [string]$WorldRuntimeInvocationNonce = "",\r\n'
    b"    [switch]$PrepareOnly,"
)
_WORLD_RUNTIME_BINDING_INSERT_SEAM = (
    b"if ($visibleBlockedCommands) {\r\n"
    b"    throw \"CLEANROOM_DEFAULT_CAPABILITY_LEAK: $($visibleBlockedCommands -join ',')\"\r\n"
    b"}\r\n"
)
_WORLD_RUNTIME_BINDING_POWERSHELL = rb"""

# A world runtime binding is an exact per-attempt capability projection.  It is
# deliberately applied only after the inherited environment has been scrubbed.
$worldBindingArguments = @(
    $WorldRuntimeBindingFile,
    $ExpectedWorldRuntimeBindingSha256,
    $WorldRuntimeAppliedReceiptFile,
    $WorldRuntimeInvocationNonce
)
$worldRuntimeBindingMandatory = $false
$worldBindingRequested = @($worldBindingArguments | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_)
}).Count -gt 0
$worldBindingApplied = $null
if ($worldBindingRequested) {
    if (@($worldBindingArguments | Where-Object {
        [string]::IsNullOrWhiteSpace([string]$_)
    }).Count -gt 0) {
        throw "WORLD_RUNTIME_BINDING_ARGUMENTS_INCOMPLETE"
    }
    if ($ExpectedWorldRuntimeBindingSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
        throw "WORLD_RUNTIME_BINDING_EXPECTED_SHA256_INVALID"
    }
    if ($WorldRuntimeInvocationNonce -notmatch '^[A-Fa-f0-9]{32,64}$') {
        throw "WORLD_RUNTIME_BINDING_INVOCATION_NONCE_INVALID"
    }

    function Assert-WorldRuntimeRegularPath {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)][string]$Label,
            [switch]$Directory
        )
        $kind = if ($Directory) { 'Container' } else { 'Leaf' }
        if (-not (Test-Path -LiteralPath $Path -PathType $kind)) {
            throw ("WORLD_RUNTIME_{0}_MISSING: {1}" -f $Label, $Path)
        }
        $resolved = Get-NormalizedPath $Path
        $cursor = Get-Item -LiteralPath $resolved -Force
        while ($null -ne $cursor) {
            if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw ("WORLD_RUNTIME_{0}_REPARSE_FORBIDDEN: {1}" -f $Label, $cursor.FullName)
            }
            $cursor = $cursor.Parent
        }
        return $resolved
    }

    function Assert-WorldRuntimeSealedFile {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [Parameter(Mandatory = $true)][string]$ExpectedSha256,
            [Parameter(Mandatory = $true)][string]$Label
        )
        if ($ExpectedSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
            throw ("WORLD_RUNTIME_{0}_SHA256_INVALID" -f $Label)
        }
        $resolved = Assert-WorldRuntimeRegularPath -Path $Path -Label $Label
        $observed = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
        if (-not $observed.Equals($ExpectedSha256.ToLowerInvariant(), [StringComparison]::Ordinal)) {
            throw ("WORLD_RUNTIME_{0}_SHA256_MISMATCH" -f $Label)
        }
        return $resolved
    }

    $bindingPath = Assert-WorldRuntimeSealedFile `
        -Path $WorldRuntimeBindingFile `
        -ExpectedSha256 $ExpectedWorldRuntimeBindingSha256 `
        -Label 'BINDING'
    try {
        $binding = Get-Content -LiteralPath $bindingPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "WORLD_RUNTIME_BINDING_JSON_INVALID"
    }
    if ($binding.schema -ne 'xinao.cleanroom.world-runtime-binding.v1') {
        throw "WORLD_RUNTIME_BINDING_SCHEMA_INVALID"
    }
    if ($binding.invocation_nonce -ne $WorldRuntimeInvocationNonce) {
        throw "WORLD_RUNTIME_BINDING_INVOCATION_NONCE_MISMATCH"
    }
    if ($binding.account_slot -ne $AccountSlot) {
        throw "WORLD_RUNTIME_BINDING_ACCOUNT_SLOT_MISMATCH"
    }
    if (@('independent_world', 'late_fusion_root') -notcontains [string]$binding.role) {
        throw "WORLD_RUNTIME_BINDING_ROLE_INVALID"
    }
    if ([string]::IsNullOrWhiteSpace([string]$binding.lineage_id)) {
        throw "WORLD_RUNTIME_BINDING_LINEAGE_ID_INVALID"
    }
    if (($binding.role -eq 'late_fusion_root') -ne ($binding.lineage_id -eq 'root-main')) {
        throw "WORLD_RUNTIME_BINDING_ROOT_ROLE_MISMATCH"
    }
    $bindingWorkspace = Assert-WorldRuntimeRegularPath `
        -Path ([string]$binding.workspace) -Label 'WORKSPACE' -Directory
    if (-not $bindingWorkspace.Equals($launchWorkdir, [StringComparison]::OrdinalIgnoreCase)) {
        throw "WORLD_RUNTIME_BINDING_WORKSPACE_MISMATCH"
    }
    $bindingRunDir = Assert-WorldRuntimeRegularPath `
        -Path ([string]$binding.run_dir) -Label 'RUN_DIR' -Directory
    $expectedAttemptRoot = Join-Path (
        Join-Path (Join-Path $bindingRunDir 'lineages') ([string]$binding.lineage_id)
    ) ('turns\turn-{0:d6}\attempt-{1:d2}' -f [int]$binding.turn_number, [int]$binding.attempt_number)
    $expectedBindingPath = Get-NormalizedPath (Join-Path $expectedAttemptRoot 'runtime_binding.json')
    $expectedAppliedPath = Get-NormalizedPath (Join-Path $expectedAttemptRoot 'binding-applied.json')
    $expectedCodexArgsPath = Get-NormalizedPath (Join-Path $expectedAttemptRoot 'codex_args.json')
    if (-not $bindingPath.Equals($expectedBindingPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "WORLD_RUNTIME_BINDING_PATH_MISMATCH"
    }
    $appliedPath = Get-NormalizedPath $WorldRuntimeAppliedReceiptFile
    if (-not $appliedPath.Equals($expectedAppliedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "WORLD_RUNTIME_BINDING_APPLIED_PATH_MISMATCH"
    }
    if (Test-Path -LiteralPath $appliedPath) {
        throw "WORLD_RUNTIME_BINDING_APPLIED_RECEIPT_ALREADY_EXISTS"
    }
    $appliedParent = Assert-WorldRuntimeRegularPath `
        -Path (Split-Path -Parent $appliedPath) -Label 'APPLIED_PARENT' -Directory
    if (-not $appliedParent.Equals((Get-NormalizedPath $expectedAttemptRoot), [StringComparison]::OrdinalIgnoreCase)) {
        throw "WORLD_RUNTIME_BINDING_APPLIED_PARENT_MISMATCH"
    }
    $sealedCodexArgsPath = Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.codex_args_path) `
        -ExpectedSha256 ([string]$binding.codex_args_sha256) `
        -Label 'CODEX_ARGS'
    if (-not $sealedCodexArgsPath.Equals($expectedCodexArgsPath, [StringComparison]::OrdinalIgnoreCase) -or
        -not $sealedCodexArgsPath.Equals((Get-NormalizedPath $CodexArgsFile), [StringComparison]::OrdinalIgnoreCase)) {
        throw "WORLD_RUNTIME_BINDING_CODEX_ARGS_PATH_MISMATCH"
    }
    try {
        $sealedCodexArgs = @(Get-Content -LiteralPath $sealedCodexArgsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    catch {
        throw "WORLD_RUNTIME_BINDING_CODEX_ARGS_JSON_INVALID"
    }
    if ($sealedCodexArgs.Count -ne @($CodexArgs).Count) {
        throw "WORLD_RUNTIME_BINDING_CODEX_ARGS_CHANGED_AFTER_PARSE"
    }
    for ($index = 0; $index -lt $sealedCodexArgs.Count; $index++) {
        if (-not ($sealedCodexArgs[$index] -is [string]) -or
            -not [string]::Equals(
                [string]$sealedCodexArgs[$index],
                [string]$CodexArgs[$index],
                [StringComparison]::Ordinal
            )) {
            throw "WORLD_RUNTIME_BINDING_CODEX_ARGS_CHANGED_AFTER_PARSE"
        }
    }
    $forbiddenCodexArgument = @($sealedCodexArgs | Where-Object {
        [string]$_ -eq '--dangerously-bypass-approvals-and-sandbox' -or
        [string]$_ -eq '--sandbox' -or
        [string]$_ -eq '--cd' -or
        [string]$_ -match '(?i)(sandbox_mode|approval_policy|additional_writable|sandbox_workspace_write)'
    })
    if ($forbiddenCodexArgument.Count -gt 0) {
        throw "WORLD_RUNTIME_BINDING_CODEX_ARGS_BOUNDARY_OVERRIDE_FORBIDDEN"
    }

    $launcherPath = Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.frozen_launcher_path) `
        -ExpectedSha256 ([string]$binding.frozen_launcher_sha256) `
        -Label 'FROZEN_LAUNCHER'
    if (-not $launcherPath.Equals((Get-NormalizedPath $PSCommandPath), [StringComparison]::OrdinalIgnoreCase)) {
        throw "WORLD_RUNTIME_BINDING_FROZEN_LAUNCHER_PATH_MISMATCH"
    }
    [void](Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.controller_release_path) `
        -ExpectedSha256 ([string]$binding.controller_release_sha256) `
        -Label 'CONTROLLER_RELEASE')
    [void](Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.migration_manifest_path) `
        -ExpectedSha256 ([string]$binding.migration_manifest_sha256) `
        -Label 'MIGRATION_MANIFEST')
    [void](Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.base_manifest_path) `
        -ExpectedSha256 ([string]$binding.base_manifest_sha256) `
        -Label 'BASE_MANIFEST')
    [void](Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.effective_code_manifest_path) `
        -ExpectedSha256 ([string]$binding.effective_code_manifest_sha256) `
        -Label 'EFFECTIVE_CODE_MANIFEST')
    [void](Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.live_seed_receipt_path) `
        -ExpectedSha256 ([string]$binding.live_seed_receipt_sha256) `
        -Label 'LIVE_SEED_RECEIPT')

    $runtimeBindingValidator = Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.runtime_binding_release_path) `
        -ExpectedSha256 ([string]$binding.runtime_binding_release_sha256) `
        -Label 'RUNTIME_BINDING_VALIDATOR'
    $effectiveCodeRoot = Assert-WorldRuntimeRegularPath `
        -Path ([string]$binding.effective_code_root) -Label 'EFFECTIVE_CODE_ROOT' -Directory
    $effectivePythonPath = Assert-WorldRuntimeRegularPath `
        -Path ([string]$binding.effective_python_path) -Label 'EFFECTIVE_PYTHON_PATH' -Directory
    if (-not $effectivePythonPath.Equals(
        (Get-NormalizedPath (Join-Path $effectiveCodeRoot 'code')),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "WORLD_RUNTIME_BINDING_EFFECTIVE_PYTHON_PATH_MISMATCH"
    }
    $privateLiveRoot = Assert-WorldRuntimeRegularPath `
        -Path ([string]$binding.private_live_root) -Label 'PRIVATE_LIVE_ROOT' -Directory
    if (-not ($privateLiveRoot.Equals($bindingWorkspace, [StringComparison]::OrdinalIgnoreCase) -or
        $privateLiveRoot.StartsWith($bindingWorkspace + '\', [StringComparison]::OrdinalIgnoreCase))) {
        throw "WORLD_RUNTIME_BINDING_PRIVATE_LIVE_ROOT_OUTSIDE_WORKSPACE"
    }
    if ([IO.Path]::GetFileName($privateLiveRoot) -match '^pre203_') {
        throw "WORLD_RUNTIME_BINDING_PRIVATE_LIVE_ROOT_IS_STORE_NOT_PARENT"
    }
    $pythonPaths = @($binding.python_path_order)
    if ($pythonPaths.Count -ne 1 -or
        -not (Get-NormalizedPath ([string]$pythonPaths[0])).Equals(
            $effectivePythonPath, [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "WORLD_RUNTIME_BINDING_PYTHON_PATH_ORDER_INVALID"
    }
    if ($binding.legacy_live_runtime_dependency -ne $false -or
        [int]$binding.cross_lineage_overlay_count -ne 0) {
        throw "WORLD_RUNTIME_BINDING_LEGACY_OR_CROSS_LINEAGE_DEPENDENCY"
    }

    $runtimeBindingPython = Assert-WorldRuntimeSealedFile `
        -Path ([string]$binding.controller_python) `
        -ExpectedSha256 ([string]$binding.controller_python_sha256) `
        -Label 'CONTROLLER_PYTHON'
    & $runtimeBindingPython $runtimeBindingValidator verify-binding `
        --binding $bindingPath `
        --expected-file-sha256 $ExpectedWorldRuntimeBindingSha256
    if ($LASTEXITCODE -ne 0) {
        throw "WORLD_RUNTIME_BINDING_FROZEN_VALIDATOR_REJECTED"
    }

    $env:PYTHONPATH = $effectivePythonPath
    $env:XINAO_WORLD_WORKSPACE = $bindingWorkspace
    $env:XINAO_LIVE_REALITY_ROOT = $privateLiveRoot
    $environmentValues = [ordered]@{
        PYTHONPATH = $env:PYTHONPATH
        XINAO_LIVE_REALITY_ROOT = $env:XINAO_LIVE_REALITY_ROOT
        XINAO_WORLD_WORKSPACE = $env:XINAO_WORLD_WORKSPACE
    }
    if (
        [string]$binding.environment.PYTHONPATH -ne $environmentValues.PYTHONPATH -or
        [string]$binding.environment.XINAO_LIVE_REALITY_ROOT -ne $environmentValues.XINAO_LIVE_REALITY_ROOT -or
        [string]$binding.environment.XINAO_WORLD_WORKSPACE -ne $environmentValues.XINAO_WORLD_WORKSPACE
    ) {
        throw "WORLD_RUNTIME_BINDING_ENVIRONMENT_PROJECTION_MISMATCH"
    }
    $environmentProjection = ($environmentValues | ConvertTo-Json -Compress -Depth 4) + "`n"
    $environmentProjectionBytes = [Text.Encoding]::UTF8.GetBytes($environmentProjection)
    $environmentProjectionHash = ([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash($environmentProjectionBytes)
    ) -replace '-', '').ToLowerInvariant()
    $appliedCore = [ordered]@{
        applied = $true
        applied_receipt_path = $appliedPath
        attempt_number = [int]$binding.attempt_number
        binding_file_sha256 = $ExpectedWorldRuntimeBindingSha256.ToLowerInvariant()
        binding_path = $bindingPath
        binding_schema = 'xinao.cleanroom.world-runtime-binding.v1'
        binding_sha256 = [string]$binding.binding_sha256
        codex_args_path = $sealedCodexArgsPath
        codex_args_sha256 = [string]$binding.codex_args_sha256
        controller_release_path = [string]$binding.controller_release_path
        controller_release_sha256 = [string]$binding.controller_release_sha256
        environment = $environmentValues
        environment_sha256 = $environmentProjectionHash
        frozen_launcher_path = $launcherPath
        frozen_launcher_sha256 = [string]$binding.frozen_launcher_sha256
        invocation_nonce = $WorldRuntimeInvocationNonce
        launcher_pid = [int]$PID
        lineage_id = [string]$binding.lineage_id
        role = [string]$binding.role
        run_id = [string]$binding.run_id
        schema = 'xinao.cleanroom.world-runtime-binding-applied.v1'
        turn_number = [int]$binding.turn_number
    }
    $appliedCoreRaw = ($appliedCore | ConvertTo-Json -Compress -Depth 6) + "`n"
    $appliedCoreBytes = [Text.Encoding]::UTF8.GetBytes($appliedCoreRaw)
    $appliedReceiptHash = ([BitConverter]::ToString(
        [Security.Cryptography.SHA256]::Create().ComputeHash($appliedCoreBytes)
    ) -replace '-', '').ToLowerInvariant()
    $applied = [ordered]@{}
    foreach ($entry in $appliedCore.GetEnumerator()) {
        $applied[$entry.Key] = $entry.Value
    }
    $applied['receipt_sha256'] = $appliedReceiptHash
    $appliedRaw = ($applied | ConvertTo-Json -Depth 6) + "`n"
    $appliedTemp = $appliedPath + '.' + $WorldRuntimeInvocationNonce + '.tmp'
    $stream = [IO.File]::Open($appliedTemp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $raw = [Text.Encoding]::UTF8.GetBytes($appliedRaw)
        $stream.Write($raw, 0, $raw.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
    try {
        [IO.File]::Move($appliedTemp, $appliedPath)
    }
    finally {
        if (Test-Path -LiteralPath $appliedTemp) {
            Remove-Item -LiteralPath $appliedTemp -Force -ErrorAction SilentlyContinue
        }
    }
    $worldBindingApplied = $applied
}
elseif ($worldRuntimeBindingMandatory) {
    throw "WORLD_RUNTIME_BINDING_REQUIRED"
}
""".replace(b"\n", b"\r\n")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])([A-Z]:[\\/][^\r\n\"'<>|]+)")

_DEEP_EVIDENCE_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "PRIVATE_KEY_PEM",
        re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", re.I),
    ),
    ("AUTHORIZATION_VALUE", re.compile(rb"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_=.-]{12,}", re.I)),
    (
        "PROVIDER_TOKEN_PREFIX",
        re.compile(
            rb"\b(?:sk-[A-Za-z0-9_-]{16,}|xai-[A-Za-z0-9_-]{16,}|"
            rb"github_pat_[A-Za-z0-9_]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|"
            rb"AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{12,})"
        ),
    ),
    (
        "JWT",
        re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    ("URL_USERINFO", re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@", re.I)),
    (
        "SENSITIVE_ASSIGNMENT",
        re.compile(
            rb"\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|"
            rb"password|passwd|private[_-]?key|cookie|authorization)\b\s*[=:]\s*"
            rb"[\"']?([A-Za-z0-9+/_=.-]{8,})",
            re.I,
        ),
    ),
)
_SECRET_PLACEHOLDER_TOKENS = (b"example", b"dummy", b"test", b"redacted", b"placeholder")


class PerpetualRuntimeError(RuntimeError):
    """A typed control-tower failure that must not be mistaken for cognition."""


class DeepEvidenceSecretPresent(PerpetualRuntimeError):
    """A high-confidence secret pattern was found without exposing its value."""

    def __init__(self, rule: str) -> None:
        super().__init__(f"DEEP_EVIDENCE_SECRET_PRESENT:{rule}")
        self.rule = rule


def validate_account_slot(value: object) -> str:
    slot = str(value).strip().upper()
    if slot not in ACCOUNT_SLOTS:
        raise PerpetualRuntimeError(f"ACCOUNT_SLOT_MUST_BE_A_OR_C: {value!r}")
    return slot


def validate_recovery_account_slot(config: Mapping[str, Any], *, expected: object | None) -> str:
    frozen = validate_account_slot(config.get("account_slot"))
    if expected is not None and validate_account_slot(expected) != frozen:
        raise PerpetualRuntimeError(
            "RECOVERY_ACCOUNT_SLOT_MISMATCH: "
            f"frozen={frozen} expected={validate_account_slot(expected)}"
        )
    return frozen


def schema_family(run_schema: object) -> dict[str, str]:
    family = _SCHEMA_FAMILIES.get(str(run_schema))
    if family is None:
        raise PerpetualRuntimeError(f"RUN_CONFIG_SCHEMA_MISMATCH: {run_schema!r}")
    return dict(family)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


_DYNAMIC_LINEAGE_PROJECT_RE = re.compile(
    r"(?im)^\[projects\.'(?P<path>[^'\r\n]+)'\]\r?\n"
    r'trust_level\s*=\s*"trusted"\r?\n(?:\r?\n)?(?=^\[|\Z)'
)


def cleanroom_config_identity(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    dynamic_paths: list[str] = []

    def normalize_dynamic_project(match: re.Match[str]) -> str:
        project_path = match.group("path")
        normalized_path = project_path.replace("/", "\\").lower()
        if not normalized_path.startswith("e:\\codex_cleanroom\\research-lineages\\"):
            return match.group(0)
        dynamic_paths.append(project_path)
        return ""

    semantic_text = _DYNAMIC_LINEAGE_PROJECT_RE.sub(normalize_dynamic_project, text)
    return {
        "raw_sha256": sha256_bytes(raw),
        "semantic_sha256": sha256_bytes(semantic_text.encode("utf-8")),
        "dynamic_lineage_project_paths": sorted(dynamic_paths, key=str.lower),
    }


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_bytes(raw)


def atomic_write_text(path: Path, text: str) -> str:
    return atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: object) -> str:
    return atomic_write_bytes(path, canonical_json_bytes(value))


def create_world_isolated_launcher(
    source_launcher: Path,
    destination: Path,
    *,
    require_runtime_binding: bool = False,
) -> dict[str, Any]:
    """Freeze the clean-room launcher with an enforced per-workspace write boundary."""

    source_launcher = resolve_path(source_launcher)
    destination = resolve_path(destination)
    raw = source_launcher.read_bytes()
    if raw.count(_UNSANDBOXED_LAUNCH_LINE) != 1:
        raise PerpetualRuntimeError("CLEANROOM_LAUNCHER_UNSANDBOXED_EXEC_SEAM_MISMATCH")
    isolated = raw.replace(
        _UNSANDBOXED_LAUNCH_LINE,
        _WORLD_SANDBOXED_LAUNCH_LINE,
        1,
    )
    isolated = isolated.replace(
        b'sandbox_mode = "danger-full-access"',
        b'sandbox_mode = "workspace-write"',
        1,
    )
    binding_support = False
    for newline in (b"\r\n", b"\n"):
        param_seam = _WORLD_RUNTIME_BINDING_PARAM_SEAM.replace(b"\r\n", newline)
        insert_seam = _WORLD_RUNTIME_BINDING_INSERT_SEAM.replace(b"\r\n", newline)
        if isolated.count(param_seam) == 1 and isolated.count(insert_seam) == 1:
            param_replacement = _WORLD_RUNTIME_BINDING_PARAM_REPLACEMENT.replace(b"\r\n", newline)
            binding_block = _WORLD_RUNTIME_BINDING_POWERSHELL.replace(b"\r\n", newline)
            if require_runtime_binding:
                mandatory_marker = b"$worldRuntimeBindingMandatory = $false"
                if binding_block.count(mandatory_marker) != 1:
                    raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_MANDATORY_SEAM_MISMATCH")
                binding_block = binding_block.replace(
                    mandatory_marker,
                    b"$worldRuntimeBindingMandatory = $true",
                    1,
                )
            isolated = isolated.replace(param_seam, param_replacement, 1)
            isolated = isolated.replace(insert_seam, insert_seam + binding_block, 1)
            binding_support = True
            break
    if require_runtime_binding and not binding_support:
        raise PerpetualRuntimeError("CLEANROOM_LAUNCHER_RUNTIME_BINDING_SEAM_MISSING")
    sha256 = atomic_write_bytes(destination, isolated)
    return {
        "schema": WORLD_ISOLATED_LAUNCHER_SCHEMA,
        "path": str(destination),
        "sha256": sha256,
        "source_path": str(source_launcher),
        "source_sha256": sha256_bytes(raw),
        "sandbox_mode": "workspace-write",
        "approval_policy": "never",
        "network_access": True,
        "writable_scope": "lineage_workspace_only",
        "additional_writable_roots": [],
        "runtime_binding_supported": binding_support,
        "runtime_binding_schema": WORLD_RUNTIME_BINDING_SCHEMA if binding_support else None,
        "runtime_binding_applied_schema": (
            WORLD_RUNTIME_BINDING_APPLIED_SCHEMA if binding_support else None
        ),
        "runtime_binding_required": bool(require_runtime_binding),
    }


def validate_body_boundary_config(config: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate the frozen launcher/body pair; legacy runs may have no boundary."""

    boundary = config.get("body_boundary")
    if boundary is None:
        return None
    if not isinstance(boundary, Mapping):
        raise PerpetualRuntimeError("WORLD_BODY_BOUNDARY_CONFIG_INVALID")
    expected = {
        "schema": WORLD_ISOLATED_LAUNCHER_SCHEMA,
        "sandbox_mode": "workspace-write",
        "approval_policy": "never",
        "network_access": True,
        "writable_scope": "current_lineage_workspace_only",
        "additional_writable_roots": [],
        "s_repo_writable": False,
        "cleanroom_shared_body_writable": False,
        "account_config_writable": False,
        "body_incident_schema": BODY_INCIDENT_SCHEMA,
    }
    if any(boundary.get(key) != value for key, value in expected.items()):
        raise PerpetualRuntimeError("WORLD_BODY_BOUNDARY_CONFIG_INVALID")
    run_dir = resolve_path(config["run_dir"])
    launcher = resolve_path(config["launcher_path"])
    if launcher != run_dir and not launcher.is_relative_to(run_dir):
        raise PerpetualRuntimeError("WORLD_BODY_LAUNCHER_OUTSIDE_RUN_DIR")
    raw = launcher.read_bytes()
    if (
        b"--dangerously-bypass-approvals-and-sandbox" in raw
        or raw.count(b"--sandbox workspace-write") != 1
        or raw.count(b"sandbox_workspace_write.network_access=true") != 1
    ):
        raise PerpetualRuntimeError("WORLD_BODY_LAUNCHER_SEMANTICS_INVALID")
    if config.get("runtime_binding_required") is True:
        required_markers = (
            b"WORLD_RUNTIME_BINDING_ARGUMENTS_INCOMPLETE",
            WORLD_RUNTIME_BINDING_SCHEMA.encode("ascii"),
            WORLD_RUNTIME_BINDING_APPLIED_SCHEMA.encode("ascii"),
            b"WORLD_RUNTIME_BINDING_ENVIRONMENT_PROJECTION_MISMATCH",
            b"$worldRuntimeBindingMandatory = $true",
        )
        if any(marker not in raw for marker in required_markers):
            raise PerpetualRuntimeError("WORLD_BODY_RUNTIME_BINDING_SEAM_INVALID")
        all_lineage_ids = {
            str(spec["lineage_id"]) for spec in [*config["branch_lineages"], config["root_lineage"]]
        }
        required_from = config.get("runtime_binding_required_from_turn")
        views = config.get("runtime_binding_views")
        if (
            not isinstance(required_from, Mapping)
            or set(required_from) != all_lineage_ids
            or any(int(value) < 1 for value in required_from.values())
            or not isinstance(views, Mapping)
            or set(views) != all_lineage_ids
        ):
            raise PerpetualRuntimeError("WORLD_BODY_RUNTIME_BINDING_CONFIG_INVALID")
        _validated_controller_python(config)
        _load_runtime_binding_module(config)
    if not isinstance(config.get("launcher_source_path"), str) or not isinstance(
        config.get("launcher_source_sha256"), str
    ):
        raise PerpetualRuntimeError("WORLD_BODY_LAUNCHER_SOURCE_IDENTITY_MISSING")
    return dict(boundary)


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise PerpetualRuntimeError(f"JSON_OBJECT_REQUIRED: {path}")
    return value


def _validated_controller_python(config: Mapping[str, Any]) -> Path:
    """Return the exact interpreter body sealed by this run config."""

    raw_path = config.get("controller_python")
    raw_sha256 = config.get("controller_python_sha256")
    if not isinstance(raw_path, str) or not isinstance(raw_sha256, str):
        raise PerpetualRuntimeError("WORLD_BODY_CONTROLLER_PYTHON_IDENTITY_MISSING")
    path = resolve_path(raw_path)
    try:
        regular = path.is_file() and _is_regular_non_reparse_file(path)
    except OSError:
        regular = False
    if not regular or sha256_file(path).casefold() != raw_sha256.casefold():
        raise PerpetualRuntimeError("WORLD_BODY_CONTROLLER_PYTHON_IDENTITY_INVALID")
    return path


def read_startup_state(path: Path) -> dict[str, Any] | None:
    """Read a state projection while another Windows process may atomically replace it."""

    try:
        return read_json_object(path)
    except (FileNotFoundError, PermissionError):
        return None


def resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def is_process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            [
                "C:\\Windows\\System32\\tasklist.exe",
                "/FI",
                f"PID eq {pid}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
            check=False,
        )
        return completed.returncode == 0 and f'"{pid}"' in completed.stdout
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def run_checked(
    command: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(part) for part in command]
    completed = subprocess.run(
        rendered,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise PerpetualRuntimeError(
            "COMMAND_FAILED\n"
            f"command={json.dumps(rendered, ensure_ascii=False)}\n"
            f"exit_code={completed.returncode}\n"
            f"stdout={completed.stdout[-4000:]}\n"
            f"stderr={completed.stderr[-4000:]}"
        )
    return completed


def git_output(repo: Path, *arguments: str, timeout: float = 120) -> str:
    completed = run_checked(["git", "-C", repo, *arguments], timeout=timeout)
    return completed.stdout.strip()


def _git_path_list(repo: Path, *arguments: str, timeout: float = 300) -> list[str]:
    completed = run_checked(["git", "-C", repo, *arguments], timeout=timeout)
    return [value for value in completed.stdout.split("\0") if value]


def _safe_workspace_relative_path(raw: str) -> Path:
    normalized = raw.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise PerpetualRuntimeError(f"DEEP_EVIDENCE_PATH_NOT_RELATIVE: {raw!r}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PerpetualRuntimeError(f"DEEP_EVIDENCE_PATH_TRAVERSAL: {raw!r}")
    return Path(*parts)


def _deep_evidence_exclusion_reason(relative_path: Path) -> str | None:
    lowered_parts = [part.lower() for part in relative_path.parts]
    if ".xinao-world-runtime" in lowered_parts:
        return "PRIVATE_LINEAGE_RUNTIME_STATE_NOT_RESEARCH_ARTIFACT"
    if any(part in _DEEP_EVIDENCE_CACHE_PARTS for part in lowered_parts):
        return "REGENERABLE_CACHE"
    name = lowered_parts[-1]
    if name.endswith(".pyc"):
        return "REGENERABLE_CACHE"
    if any(part in _DEEP_EVIDENCE_FORBIDDEN_PARTS for part in lowered_parts):
        return "FORBIDDEN_SECRET_OR_ACCOUNT_SURFACE"
    if name in _DEEP_EVIDENCE_FORBIDDEN_NAMES or name == "exec_stdout.jsonl":
        return "FORBIDDEN_SECRET_OR_ACCOUNT_SURFACE"
    if name.startswith(".env") or name.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm")):
        return "FORBIDDEN_SECRET_OR_ACCOUNT_SURFACE"
    if name.endswith((".pem", ".p12", ".pfx")) or name in {
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }:
        return "FORBIDDEN_SECRET_OR_ACCOUNT_SURFACE"
    return None


def _ignored_path_is_material(relative_path: Path) -> bool:
    lowered = tuple(part.lower() for part in relative_path.parts)
    return any(lowered[: len(root)] == root for root in _DEEP_EVIDENCE_IGNORED_MATERIAL_ROOTS)


def _deep_evidence_secret_rule(raw: bytes) -> str | None:
    for rule, pattern in _DEEP_EVIDENCE_SECRET_PATTERNS:
        for match in pattern.finditer(raw):
            candidate = match.group(1).lower() if match.lastindex else b""
            if candidate and any(token in candidate for token in _SECRET_PLACEHOLDER_TOKENS):
                continue
            return rule
    return None


def _is_regular_non_reparse_file(path: Path) -> bool:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        return False
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return not (reparse_flag and attributes & reparse_flag)


def _snapshot_file_to_blob(source: Path, blob_root: Path) -> dict[str, Any]:
    blob_root.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        before = source.stat()
        temporary = blob_root / f".{os.getpid()}.{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256()
        copied = 0
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                scan_tail = b""
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    rule = _deep_evidence_secret_rule(scan_tail + chunk)
                    if rule is not None:
                        raise DeepEvidenceSecretPresent(rule)
                    digest.update(chunk)
                    writer.write(chunk)
                    copied += len(chunk)
                    scan_tail = (scan_tail + chunk)[-8192:]
                writer.flush()
                os.fsync(writer.fileno())
            after = source.stat()
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or copied != after.st_size
            ):
                continue
            sha256 = digest.hexdigest().upper()
            destination = blob_root / sha256[:2] / sha256
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.stat().st_size != copied or sha256_file(destination) != sha256:
                    raise PerpetualRuntimeError(
                        f"DEEP_EVIDENCE_BLOB_COLLISION_OR_DRIFT: {destination}"
                    )
            else:
                os.replace(temporary, destination)
            return {
                "bytes": copied,
                "sha256": sha256,
                "blob_path": str(destination),
            }
        except (FileNotFoundError, PermissionError, OSError) as exc:
            last_error = exc
        finally:
            temporary.unlink(missing_ok=True)
    raise PerpetualRuntimeError(
        f"DEEP_EVIDENCE_SOURCE_UNSTABLE: {source}: {type(last_error).__name__ if 'last_error' in locals() else 'CHANGED_DURING_COPY'}"
    )


def build_trajectory_index(stdout_path: Path, index_path: Path) -> dict[str, Any]:
    stdout_path = resolve_path(stdout_path)
    index_path = resolve_path(index_path)
    if index_path.parent != stdout_path.parent:
        raise PerpetualRuntimeError("TRAJECTORY_INDEX_MUST_SHARE_ATTEMPT_DIRECTORY")
    temporary = index_path.with_name(f".{index_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    digest = hashlib.sha256()
    event_count = 0
    offset = 0
    try:
        with stdout_path.open("rb") as reader, temporary.open("xb") as writer:
            for event_count, raw_line in enumerate(reader, 1):
                event = parse_event_line(raw_line)
                item = event.get("item") if isinstance(event, dict) else None
                item = item if isinstance(item, dict) else {}
                row = {
                    "schema": DEEP_EVIDENCE_TRAJECTORY_INDEX_SCHEMA,
                    "sequence": event_count,
                    "byte_offset": offset,
                    "byte_length": len(raw_line),
                    "line_sha256": sha256_bytes(raw_line),
                    "event_type": event.get("type") if isinstance(event, dict) else "UNPARSED",
                    "item_type": item.get("type"),
                    "item_id": item.get("id"),
                    "status": item.get("status"),
                    "exit_code": item.get("exit_code"),
                }
                encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode(
                    "utf-8"
                )
                writer.write(encoded)
                digest.update(encoded)
                offset += len(raw_line)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, index_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": str(index_path),
        "sha256": digest.hexdigest().upper(),
        "event_count": event_count,
        "raw_path": str(stdout_path),
        "raw_sha256": sha256_file(stdout_path),
        "raw_bytes": stdout_path.stat().st_size,
    }


def capture_workspace_artifacts(
    *,
    workspace: Path,
    run_id: str,
    source_head: str,
    run_dir: Path,
    lineage_id: str,
    turn_number: int,
    attempt_number: int,
    manifest_path: Path,
) -> dict[str, Any]:
    workspace = resolve_path(workspace)
    run_dir = resolve_path(run_dir)
    manifest_path = resolve_path(manifest_path)
    classifications: dict[str, tuple[Path, str]] = {}
    commands = (
        (
            "TRACKED_CHANGED",
            ("diff", "--no-renames", "--name-only", "-z", source_head, "--"),
        ),
        ("UNTRACKED", ("ls-files", "--others", "--exclude-standard", "-z")),
        (
            "IGNORED_MATERIAL",
            ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
        ),
    )
    priority = {"IGNORED_MATERIAL": 1, "UNTRACKED": 2, "TRACKED_CHANGED": 3}
    for classification, arguments in commands:
        for raw in _git_path_list(workspace, *arguments):
            relative = _safe_workspace_relative_path(raw)
            key = relative.as_posix().lower()
            current = classifications.get(key)
            if current is None or priority[classification] > priority[current[1]]:
                classifications[key] = (relative, classification)

    blob_root = run_dir / "deep-evidence" / "blobs" / "sha256"
    entries: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    gaps: list[dict[str, str]] = []
    safety_block_count = 0
    for relative, classification in sorted(
        classifications.values(), key=lambda item: str(item[0]).lower()
    ):
        package_path = relative.as_posix()
        exclusion = _deep_evidence_exclusion_reason(relative)
        if classification == "IGNORED_MATERIAL" and not _ignored_path_is_material(relative):
            exclusion = exclusion or "IGNORED_NOT_ADMITTED_AS_RESEARCH_REALITY"
        if exclusion is not None:
            exclusions.append({"relative_path": package_path, "reason": exclusion})
            continue
        source = workspace / relative
        if not source.exists():
            entries.append(
                {
                    "relative_path": package_path,
                    "source_class": classification,
                    "state": "DELETED",
                }
            )
            continue
        try:
            if not _is_regular_non_reparse_file(source):
                exclusions.append(
                    {"relative_path": package_path, "reason": "NON_REGULAR_OR_REPARSE"}
                )
                continue
            snapshot = _snapshot_file_to_blob(source, blob_root)
            entries.append(
                {
                    "relative_path": package_path,
                    "source_class": classification,
                    "state": "PRESENT",
                    **snapshot,
                }
            )
        except DeepEvidenceSecretPresent as exc:
            safety_block_count += 1
            exclusions.append(
                {
                    "relative_path": package_path,
                    "reason": "SECRET_CONTENT_BLOCKED",
                    "rule": exc.rule,
                }
            )
        except (FileNotFoundError, PermissionError, OSError, PerpetualRuntimeError) as exc:
            gaps.append(
                {
                    "relative_path": package_path,
                    "reason": type(exc).__name__,
                }
            )
    manifest = {
        "schema": DEEP_EVIDENCE_ARTIFACT_MANIFEST_SCHEMA,
        "run_id": run_id,
        "lineage_id": lineage_id,
        "turn_number": turn_number,
        "attempt_number": attempt_number,
        "captured_at": now_iso(),
        "capture_boundary": "after_model_process_exit_before_next_lineage_turn",
        "source_workspace": str(workspace),
        "source_head": source_head,
        "candidate_authority": False,
        "content_addressed_blob_root": str(blob_root),
        "complete": not gaps and safety_block_count == 0,
        "safety_block_count": safety_block_count,
        "entries": entries,
        "exclusions": exclusions,
        "gaps": gaps,
    }
    manifest_sha256 = atomic_write_json(manifest_path, manifest)
    return {
        "path": str(manifest_path),
        "sha256": manifest_sha256,
        "entry_count": len(entries),
        "exclusion_count": len(exclusions),
        "gap_count": len(gaps),
        "safety_block_count": safety_block_count,
        "complete": not gaps and safety_block_count == 0,
        "blob_root": str(blob_root),
    }


def _require_contained_path(path: Path, root: Path, error_code: str) -> Path:
    resolved = resolve_path(path)
    resolved_root = resolve_path(root)
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise PerpetualRuntimeError(f"{error_code}: path={resolved} root={resolved_root}")
    return resolved


def build_deep_evidence_reference(
    *,
    run_dir: Path,
    lineage_id: str,
    turn_number: int,
    attempt_dir: Path,
    receipt: Mapping[str, Any],
    workspace: Path,
    source_head: str,
    query_command_prefix: Sequence[str],
) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    attempt_dir = _require_contained_path(
        attempt_dir,
        run_dir / "lineages" / lineage_id / "turns",
        "DEEP_EVIDENCE_ATTEMPT_OUTSIDE_LINEAGE",
    )
    receipt_path = attempt_dir / "receipt.json"
    message_path = attempt_dir / "last_message.txt"
    prompt_path = attempt_dir / "prompt.txt"
    deep = receipt.get("deep_evidence")
    deep = dict(deep) if isinstance(deep, dict) else {}
    availability = str(deep.get("status", "UNAVAILABLE_LEGACY_TURN"))
    reference: dict[str, Any] = {
        "schema": DEEP_EVIDENCE_REF_SCHEMA,
        "run_id": receipt.get("run_id"),
        "lineage_id": lineage_id,
        "turn_number": turn_number,
        "attempt_number": receipt.get("attempt_number"),
        "candidate_authority": False,
        "s_content_adjudication": False,
        "access_scope": "same_run_root_main_on_demand",
        "availability": availability,
        "source_run_dir": str(run_dir),
        "source_attempt_dir": str(attempt_dir),
        "source_workspace": str(resolve_path(workspace)),
        "source_head": source_head,
        "receipt": {
            "path": str(receipt_path),
            "sha256": sha256_file(receipt_path),
        },
        "last_message": {
            "path": str(message_path),
            "sha256": receipt.get("last_message_sha256"),
        },
        "query_command_prefix": list(query_command_prefix),
    }
    if prompt_path.is_file():
        reference["prompt"] = {
            "path": str(prompt_path),
            "sha256": receipt.get("prompt_sha256") or sha256_file(prompt_path),
        }
    if availability in {"AVAILABLE", "PARTIAL"}:
        trajectory = deep.get("trajectory")
        artifacts = deep.get("artifacts")
        if isinstance(trajectory, dict):
            raw_path = _require_contained_path(
                Path(str(trajectory["raw_path"])), attempt_dir, "TRAJECTORY_OUTSIDE_ATTEMPT"
            )
            index_path = _require_contained_path(
                Path(str(trajectory["path"])), attempt_dir, "TRAJECTORY_INDEX_OUTSIDE_ATTEMPT"
            )
            if sha256_file(raw_path) != trajectory.get("raw_sha256"):
                raise PerpetualRuntimeError(f"DEEP_EVIDENCE_TRAJECTORY_HASH_MISMATCH: {raw_path}")
            if sha256_file(index_path) != trajectory.get("sha256"):
                raise PerpetualRuntimeError(f"DEEP_EVIDENCE_INDEX_HASH_MISMATCH: {index_path}")
            reference["trajectory"] = trajectory
        if isinstance(artifacts, dict):
            artifact_manifest_path = _require_contained_path(
                Path(str(artifacts["path"])), attempt_dir, "ARTIFACT_MANIFEST_OUTSIDE_ATTEMPT"
            )
            if sha256_file(artifact_manifest_path) != artifacts.get("sha256"):
                raise PerpetualRuntimeError(
                    f"DEEP_EVIDENCE_ARTIFACT_MANIFEST_HASH_MISMATCH: {artifact_manifest_path}"
                )
            reference["artifacts"] = artifacts
        if "trajectory" not in reference and "artifacts" not in reference:
            raise PerpetualRuntimeError("DEEP_EVIDENCE_RECEIPT_FIELDS_MISSING")
    else:
        reference["unavailable_reason"] = deep.get(
            "error_class", "TURN_PREDATES_DEEP_EVIDENCE_CAPTURE"
        )
    return reference


def _load_packet_deep_evidence_reference(
    packet_dir: Path, candidate_index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    packet_dir = resolve_path(packet_dir)
    manifest_path = packet_dir / "PACKET_MANIFEST.json"
    manifest = read_json_object(manifest_path)
    entries = manifest.get("entries")
    if not isinstance(entries, list) or candidate_index < 1 or candidate_index > len(entries):
        raise PerpetualRuntimeError(f"DEEP_EVIDENCE_CANDIDATE_INDEX_INVALID: {candidate_index}")
    entry = entries[candidate_index - 1]
    if not isinstance(entry, dict) or int(entry.get("anonymous_index", -1)) != candidate_index:
        raise PerpetualRuntimeError("DEEP_EVIDENCE_PACKET_ENTRY_IDENTITY_MISMATCH")
    relative = _safe_workspace_relative_path(str(entry.get("deep_evidence_path", "")))
    reference_path = _require_contained_path(
        packet_dir / relative, packet_dir, "DEEP_EVIDENCE_REFERENCE_OUTSIDE_PACKET"
    )
    if reference_path.parent != packet_dir:
        raise PerpetualRuntimeError("DEEP_EVIDENCE_REFERENCE_MUST_BE_PACKET_LOCAL")
    if sha256_file(reference_path) != entry.get("deep_evidence_sha256"):
        raise PerpetualRuntimeError(f"DEEP_EVIDENCE_REFERENCE_HASH_MISMATCH: {reference_path}")
    reference = read_json_object(reference_path)
    if (
        reference.get("schema") != DEEP_EVIDENCE_REF_SCHEMA
        or reference.get("candidate_authority") is not False
        or reference.get("s_content_adjudication") is not False
        or reference.get("lineage_id") != entry.get("source_lineage_id")
        or int(reference.get("turn_number", -1)) != int(entry.get("source_turn_number", -2))
    ):
        raise PerpetualRuntimeError("DEEP_EVIDENCE_REFERENCE_IDENTITY_MISMATCH")
    return entry, reference


def inspect_deep_evidence(
    *,
    packet_dir: Path,
    candidate_index: int,
    event_sequence: int | None = None,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    entry, reference = _load_packet_deep_evidence_reference(packet_dir, candidate_index)
    if event_sequence is not None and artifact_sha256 is not None:
        raise PerpetualRuntimeError("DEEP_EVIDENCE_QUERY_MUST_SELECT_ONE_OBJECT")
    if event_sequence is None and artifact_sha256 is None:
        return {
            "candidate_index": candidate_index,
            "entry": entry,
            "deep_evidence": reference,
        }
    if reference.get("availability") not in {"AVAILABLE", "PARTIAL"}:
        raise PerpetualRuntimeError(
            f"DEEP_EVIDENCE_UNAVAILABLE: {reference.get('unavailable_reason')}"
        )
    attempt_dir = resolve_path(reference["source_attempt_dir"])
    run_dir = resolve_path(reference["source_run_dir"])
    lineage_id = str(reference["lineage_id"])
    _require_contained_path(
        attempt_dir,
        run_dir / "lineages" / lineage_id / "turns",
        "DEEP_EVIDENCE_ATTEMPT_OUTSIDE_RUN",
    )
    if event_sequence is not None:
        if "trajectory" not in reference:
            raise PerpetualRuntimeError("DEEP_EVIDENCE_TRAJECTORY_UNAVAILABLE")
        trajectory = dict(reference["trajectory"])
        raw_path = _require_contained_path(
            Path(str(trajectory["raw_path"])), attempt_dir, "TRAJECTORY_OUTSIDE_ATTEMPT"
        )
        index_path = _require_contained_path(
            Path(str(trajectory["path"])), attempt_dir, "TRAJECTORY_INDEX_OUTSIDE_ATTEMPT"
        )
        if sha256_file(index_path) != trajectory.get("sha256"):
            raise PerpetualRuntimeError(f"DEEP_EVIDENCE_INDEX_HASH_MISMATCH: {index_path}")
        selected: dict[str, Any] | None = None
        with index_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if isinstance(value, dict) and int(value.get("sequence", -1)) == event_sequence:
                    selected = value
                    break
        if selected is None:
            raise PerpetualRuntimeError(f"DEEP_EVIDENCE_EVENT_NOT_FOUND: {event_sequence}")
        with raw_path.open("rb") as stream:
            stream.seek(int(selected["byte_offset"]))
            raw = stream.read(int(selected["byte_length"]))
        if sha256_bytes(raw) != selected.get("line_sha256"):
            raise PerpetualRuntimeError("DEEP_EVIDENCE_EVENT_HASH_MISMATCH")
        event = parse_event_line(raw)
        return {
            "candidate_index": candidate_index,
            "sequence": event_sequence,
            "index": selected,
            "event": event,
            "raw_text": None if event is not None else raw.decode("utf-8", errors="replace"),
        }

    normalized_sha256 = str(artifact_sha256).strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", normalized_sha256):
        raise PerpetualRuntimeError("DEEP_EVIDENCE_ARTIFACT_SHA256_INVALID")
    if "artifacts" not in reference:
        raise PerpetualRuntimeError("DEEP_EVIDENCE_ARTIFACTS_UNAVAILABLE")
    artifacts = dict(reference["artifacts"])
    manifest_path = _require_contained_path(
        Path(str(artifacts["path"])), attempt_dir, "ARTIFACT_MANIFEST_OUTSIDE_ATTEMPT"
    )
    if sha256_file(manifest_path) != artifacts.get("sha256"):
        raise PerpetualRuntimeError("DEEP_EVIDENCE_ARTIFACT_MANIFEST_HASH_MISMATCH")
    manifest = read_json_object(manifest_path)
    blob_root = _require_contained_path(
        Path(str(manifest["content_addressed_blob_root"])),
        run_dir / "deep-evidence" / "blobs" / "sha256",
        "DEEP_EVIDENCE_BLOB_ROOT_OUTSIDE_RUN",
    )
    matches = [
        value
        for value in manifest.get("entries", [])
        if isinstance(value, dict) and value.get("sha256") == normalized_sha256
    ]
    if not matches:
        raise PerpetualRuntimeError(f"DEEP_EVIDENCE_ARTIFACT_NOT_FOUND: {normalized_sha256}")
    blob_path = _require_contained_path(
        Path(str(matches[0]["blob_path"])), blob_root, "DEEP_EVIDENCE_BLOB_OUTSIDE_STORE"
    )
    if sha256_file(blob_path) != normalized_sha256:
        raise PerpetualRuntimeError(f"DEEP_EVIDENCE_ARTIFACT_HASH_MISMATCH: {blob_path}")
    return {
        "candidate_index": candidate_index,
        "artifact": matches[0],
        "verified_blob_path": str(blob_path),
    }


def validate_source_repo(repo: Path) -> dict[str, str]:
    resolved = resolve_path(repo)
    if not resolved.is_dir():
        raise PerpetualRuntimeError(f"SOURCE_REPO_MISSING: {resolved}")
    top = resolve_path(git_output(resolved, "rev-parse", "--show-toplevel"))
    if top != resolved:
        raise PerpetualRuntimeError(f"SOURCE_REPO_ROOT_MISMATCH: {resolved} != {top}")
    head = git_output(resolved, "rev-parse", "HEAD")
    status = git_output(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise PerpetualRuntimeError(f"SOURCE_REPO_NOT_CLEAN:\n{status}")
    branch = git_output(resolved, "branch", "--show-current")
    return {
        "root": str(resolved),
        "head": head,
        "branch": branch,
        "status_sha256": sha256_bytes((status + "\n").encode("utf-8")),
    }


def validate_pinned_source_commit(repo: Path, source_head: str) -> dict[str, str]:
    """Verify that a frozen source commit remains available without pinning live HEAD."""

    resolved = resolve_path(repo)
    if not resolved.is_dir():
        raise PerpetualRuntimeError(f"SOURCE_REPO_MISSING: {resolved}")
    top = resolve_path(git_output(resolved, "rev-parse", "--show-toplevel"))
    if top != resolved:
        raise PerpetualRuntimeError(f"SOURCE_REPO_ROOT_MISMATCH: {resolved} != {top}")
    git_output(resolved, "cat-file", "-e", f"{source_head}^{{commit}}")
    return {
        "root": str(resolved),
        "current_head": git_output(resolved, "rev-parse", "HEAD"),
        "source_head": source_head,
    }


def validate_lineage_runtime_repo(workspace: Path, source_head: str) -> dict[str, str]:
    """Verify a candidate lineage still descends from its frozen, remote-free baseline."""

    resolved = resolve_path(workspace)
    if not resolved.is_dir():
        raise PerpetualRuntimeError(f"LINEAGE_WORKSPACE_MISSING: {resolved}")
    top = resolve_path(git_output(resolved, "rev-parse", "--show-toplevel"))
    if top != resolved:
        raise PerpetualRuntimeError(f"LINEAGE_REPO_ROOT_MISMATCH: {resolved} != {top}")
    head = git_output(resolved, "rev-parse", "HEAD")
    merge_base = git_output(resolved, "merge-base", source_head, head)
    if merge_base.lower() != source_head.lower():
        raise PerpetualRuntimeError(
            f"LINEAGE_BASELINE_NOT_ANCESTOR: workspace={resolved} baseline={source_head} head={head}"
        )
    remotes = git_output(resolved, "remote")
    if remotes:
        raise PerpetualRuntimeError(f"LINEAGE_REMOTE_MUST_BE_EMPTY: {resolved}")
    return {
        "workspace": str(resolved),
        "source_head": source_head,
        "head": head,
        "status_sha256": sha256_bytes(
            (
                git_output(resolved, "status", "--porcelain=v1", "--untracked-files=all") + "\n"
            ).encode("utf-8")
        ),
    }


def clone_isolated_repo(source: Path, destination: Path, head: str) -> dict[str, str]:
    source = resolve_path(source)
    destination = resolve_path(destination)
    if destination.exists():
        raise PerpetualRuntimeError(f"LINEAGE_CLONE_ALREADY_EXISTS: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            "git",
            "clone",
            "--quiet",
            "--no-local",
            "--no-hardlinks",
            "--no-checkout",
            source,
            destination,
        ],
        timeout=600,
    )
    try:
        run_checked(["git", "-C", destination, "checkout", "--quiet", "--detach", head])
        remotes = git_output(destination, "remote")
        if "origin" in remotes.splitlines():
            run_checked(["git", "-C", destination, "remote", "remove", "origin"])
        observed_head = git_output(destination, "rev-parse", "HEAD")
        status = git_output(destination, "status", "--porcelain=v1", "--untracked-files=all")
        if observed_head != head or status:
            raise PerpetualRuntimeError(
                "LINEAGE_CLONE_IDENTITY_MISMATCH: "
                f"expected={head} observed={observed_head} status={status!r}"
            )
        return {
            "workspace": str(destination),
            "head": observed_head,
            "remote_count": str(len(git_output(destination, "remote").splitlines())),
            "status_sha256": sha256_bytes((status + "\n").encode("utf-8")),
        }
    except BaseException:
        # Preserve failed setup for diagnosis. The caller records the run as failed.
        raise


def lifecycle_contract() -> str:
    return """在当前 turn 已把局部 Reality Return 带回整个 working world 后，最后另起一行写一个生命周期回执：
XINAO_LINEAGE_STATE: CONTINUE
或把 CONTINUE 换成 WAIT / BLOCKED / NO_POSITIVE_FRONTIER / PAUSE。

CONTINUE 只表示：你从自己的整个当前 world 判断，现在确有下一单位正收益认识计算，应由同一 session 立即续接。WAIT 表示等待现实或具名事件；BLOCKED 表示真实 runtime/材料阻塞；NO_POSITIVE_FRONTIER 表示当前合法空间已无正收益前沿；PAUSE 表示你明确要求暂停该 lineage。这个回执只让 S 管理生命周期，不限制你的研究内容，也不能把局部 no-action、ABSTAIN、一次反证或一轮报告冒充整个新澳父对象关闭。"""


def build_branch_initial_prompt(*, lineage_id: str, run_id: str, source_head: str) -> str:
    return f"""你是 clean-room 中一条独立、完整、长期存续的 GPT-5.6 Sol 新澳 world-owning cognition lineage。

当前活动已经明确进入新澳。你面对的现实 W 是当前工作树的完整精确 bytes；该独立 clone 的基线 HEAD 为 {source_head}，run identity 为 {run_id}，lineage identity 为 {lineage_id}。先按本工作树 AGENTS.md 与新澳入口地图接触完整现实，再由你自己形成 working world、关系、表示、问题、计算、工具、模拟、网络查询、代码和实验。你不是 S 预先分配的统计员、代码员、审稿人或某个固定假设分支；S 不给你研究题，也不规定下一关系。工具和现实展开由你的 cognition 自然长出，Reality Return 必须回到整个当前 world。

这不是一次性报告任务。一个局部计算、null/no-action、阶段报告或当前 turn 结束，都不自动关闭仍存活的父对象。只要没有真实等待、阻塞、应暂停或已经可核的无正收益前沿，就由同一 lineage 自然进入下一单位，不等用户再说“继续”。

你的 clone 是隔离的 candidate 写域。可以在其中自由研究和留下候选器官，但不得把任何结果推送、写回共享主仓、宣布为 LIVE，或执行资本/发布等正式外部 effect；candidate、adoption、effect 与 parent completion 必须分开。

现在直接研究新澳。

{lifecycle_contract()}
"""


def build_continuation_prompt(*, lineage_id: str) -> str:
    return f"""继续同一条长期新澳 world-owning lineage（{lineage_id}）。这条消息只续接生命周期，不给你选题，也不规定下一关系。请从你当前完整 working world 自行进入下一单位现在有正收益的 world → reality → world 计算；上一 turn 的结束不关闭父对象。若当前真实需要等待、已经阻塞、无正收益前沿或应暂停，请如实停驻。

{lifecycle_contract()}
"""


def build_root_fusion_prompt(
    *,
    run_id: str,
    source_head: str,
    packet_relative_path: str,
    first_turn: bool,
) -> str:
    opening = (
        "你是 clean-room 中长期存续的新仓 Root/Main GPT-5.6 Sol，是新澳的 world-owning cognition 与 late neural resynthesis 位置。"
        if first_turn
        else "继续同一条长期新仓 Root/Main GPT-5.6 Sol lineage。"
    )
    return f"""{opening}

当前 run identity 为 {run_id}，独立 clone 的基线 HEAD 为 {source_head}。S 只冻结了多条独立 world-owning Sol 的原始候选回执与 provenance；新的 packet 位于你工作树内 `{packet_relative_path}`。这些材料默认只是 candidate/evidence，不是投票、结论、canonical answer 或对你的研究 steering。

`PACKET_MANIFEST.json` 同时给每条 lineage 一个薄的 `DEEP_EVIDENCE_XX.json` 导航面：它指向 completed-turn 的逐事件索引与内容寻址 artifact blobs，并给出本 run 冻结 controller 的 `inspect-evidence` 查询命令前缀。`CANDIDATE_XX.txt` 不是该 lineage 的全部认识；当某个分歧、推导、工具结果、撤回或现实产物会改变你的重综合时，按需打开对应事件或 artifact。不要先把所有 raw trajectory 批量灌进上下文，也不要在输出中复现偶然遇到的账户/秘密材料。

请重新直接接触完整 W 和 packet。不要按多数票或 branch 现成压缩做裁决；由你自己重新计算、质疑、调用现实肢体并形成一个可能不同于任何 branch 的综合 working world。你可以采用、改写、并置或拒绝任何候选。S 不形成领域正解，也不替你选择下一认识单位。

你的 clone 是隔离的 candidate 写域；不得写回共享主仓或执行正式外部 effect。一个 packet、一次综合或当前 turn 结束都不自动关闭新澳父对象。

{lifecycle_contract()}
"""


def parse_lifecycle_state(last_message: str) -> str | None:
    matches = list(_LIFECYCLE_RE.finditer(last_message))
    if not matches:
        return None
    return matches[-1].group(1).upper()


def parse_event_line(raw_line: bytes | str) -> dict[str, Any] | None:
    if isinstance(raw_line, bytes):
        text = raw_line.decode("utf-8", errors="replace")
    else:
        text = raw_line
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def classify_failure(stdout_tail: str, stderr_tail: str) -> str:
    combined = f"{stdout_tail}\n{stderr_tail}".lower()
    if any(token in combined for token in _HARD_ERROR_TOKENS):
        return "HARD_RUNTIME_FAILURE"
    if any(token in combined for token in _TRANSIENT_ERROR_TOKENS):
        return "TRANSIENT_RUNTIME_FAILURE"
    return "UNKNOWN_RUNTIME_FAILURE"


def safe_tail(path: Path, limit: int = 64 * 1024) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - limit))
        return stream.read().decode("utf-8", errors="replace")


def sanitize_command(command: Sequence[str]) -> list[str]:
    # The command contains no credential bytes. Keep an explicit guard anyway.
    blocked = ("token", "secret", "password", "credential", "auth.json")
    result: list[str] = []
    for part in command:
        lower = part.lower()
        result.append("[REDACTED]" if any(word in lower for word in blocked) else part)
    return result


def classify_body_incident_events(stdout_path: Path, *, workspace: Path) -> list[dict[str, Any]]:
    """Return mechanical tool-boundary incidents without copying command/output bodies."""

    incidents: list[dict[str, Any]] = []
    workspace = resolve_path(workspace)
    with stdout_path.open("rb") as stream:
        for sequence, raw_line in enumerate(stream, 1):
            event = parse_event_line(raw_line)
            if not isinstance(event, dict) or event.get("type") != "item.completed":
                continue
            item = event.get("item")
            if not isinstance(item, dict) or item.get("type") != "command_execution":
                continue
            if item.get("status") != "failed" and item.get("exit_code") in {0, None}:
                continue
            output = str(item.get("aggregated_output") or "")
            lowered = output.lower()
            denial = next(
                (token for token in _BODY_BOUNDARY_OS_DENIAL_TOKENS if token in lowered), None
            )
            denied_target: Path | None = None
            if denial is not None:
                for candidate in _WINDOWS_ABSOLUTE_PATH_RE.findall(output):
                    try:
                        resolved = resolve_path(candidate.rstrip(" .,:;)]}"))
                    except (OSError, ValueError):
                        continue
                    if resolved != workspace and not resolved.is_relative_to(workspace):
                        denied_target = resolved
                        break
            if denied_target is None:
                continue
            incidents.append(
                {
                    "event_sequence": sequence,
                    "item_id": item.get("id"),
                    "tool": "command_execution",
                    "failure_class": "WRITE_DOMAIN_DENIED",
                    "exit_code": item.get("exit_code"),
                    "matched_rule": denial,
                    "denied_target_scope": "OUTSIDE_LINEAGE_WORKSPACE",
                    "denied_target_path_sha256": (
                        sha256_bytes(str(denied_target).lower().encode("utf-8"))
                        if denied_target is not None
                        else None
                    ),
                    "event_line_sha256": sha256_bytes(raw_line),
                }
            )
    return incidents


def build_codex_arguments(
    config: Mapping[str, Any],
    *,
    last_message_path: Path,
    session_id: str | None,
) -> list[str]:
    arguments = ["exec"]
    common = [
        "--strict-config",
        "--json",
        "-m",
        str(config["model"]),
        "-c",
        f'model_reasoning_effort="{config["model_reasoning_effort"]}"',
        "-o",
        str(last_message_path),
    ]
    if session_id:
        arguments.extend(["resume", *common, session_id, "-"])
    else:
        arguments.extend([*common, "-"])
    return arguments


def build_codex_command(
    config: Mapping[str, Any],
    *,
    workspace: Path,
    arguments_path: Path,
    runtime_binding_path: Path | None = None,
    runtime_binding_sha256: str | None = None,
    runtime_binding_applied_path: Path | None = None,
    runtime_binding_invocation_nonce: str | None = None,
) -> list[str]:
    command = [
        str(config["powershell_path"]),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(config["launcher_path"]),
        "-AccountSlot",
        validate_account_slot(config["account_slot"]),
        "-WorkDir",
        str(workspace),
        "-CodexArgsFile",
        str(arguments_path),
    ]
    binding_values = (
        runtime_binding_path,
        runtime_binding_sha256,
        runtime_binding_applied_path,
        runtime_binding_invocation_nonce,
    )
    if any(value is not None for value in binding_values):
        if any(value is None for value in binding_values):
            raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_COMMAND_ARGUMENTS_INCOMPLETE")
        command.extend(
            [
                "-WorldRuntimeBindingFile",
                str(runtime_binding_path),
                "-ExpectedWorldRuntimeBindingSha256",
                str(runtime_binding_sha256),
                "-WorldRuntimeAppliedReceiptFile",
                str(runtime_binding_applied_path),
                "-WorldRuntimeInvocationNonce",
                str(runtime_binding_invocation_nonce),
            ]
        )
    return command


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            [
                r"C:\Windows\System32\taskkill.exe",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=60,
            check=False,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
    except OSError as exc:
        handle.close()
        raise PerpetualRuntimeError(f"CONTROLLER_ALREADY_ACTIVE: {path}") from exc
    try:
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _try_acquire_byte_lock(path: Path) -> Any | None:
    """Acquire one crash-released file slot without waiting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        handle.close()
        return None


def _release_byte_lock(handle: Any) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


_RUNTIME_BINDING_MODULE_CACHE: dict[tuple[str, str], ModuleType] = {}


def _load_runtime_binding_module(config: Mapping[str, Any]) -> ModuleType:
    """Load the hash-pinned companion used by a frozen controller release."""

    raw_path = config.get("runtime_binding_release_path")
    raw_sha256 = config.get("runtime_binding_release_sha256")
    if not isinstance(raw_path, str) or not isinstance(raw_sha256, str):
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_RELEASE_IDENTITY_MISSING")
    path = resolve_path(raw_path)
    if not path.is_file():
        raise PerpetualRuntimeError(f"WORLD_RUNTIME_BINDING_RELEASE_MISSING: {path}")
    observed = sha256_file(path)
    if observed.casefold() != raw_sha256.casefold():
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_RELEASE_BYTES_CHANGED")
    cache_key = (str(path), observed)
    cached = _RUNTIME_BINDING_MODULE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(
        f"xinao_frozen_runtime_binding_{observed.lower()}", path
    )
    if spec is None or spec.loader is None:
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_RELEASE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        getattr(module, "WORLD_RUNTIME_BINDING_SCHEMA", None) != WORLD_RUNTIME_BINDING_SCHEMA
        or getattr(module, "WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA", None)
        != WORLD_RUNTIME_BINDING_APPLIED_SCHEMA
    ):
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_RELEASE_SCHEMA_MISMATCH")
    _RUNTIME_BINDING_MODULE_CACHE[cache_key] = module
    return module


def _turn_requires_runtime_binding(
    config: Mapping[str, Any], *, lineage_id: str, turn_number: int
) -> bool:
    if config.get("runtime_binding_required") is not True:
        return False
    required_from = config.get("runtime_binding_required_from_turn")
    lineage_required_from = (
        required_from.get(lineage_id) if isinstance(required_from, Mapping) else None
    )
    return lineage_required_from is None or turn_number >= int(lineage_required_from)


def _runtime_binding_view(config: Mapping[str, Any], *, lineage_id: str) -> dict[str, Any]:
    views = config.get("runtime_binding_views")
    if not isinstance(views, Mapping) or not isinstance(views.get(lineage_id), Mapping):
        raise PerpetualRuntimeError(f"WORLD_RUNTIME_BINDING_VIEW_MISSING: {lineage_id}")
    return dict(views[lineage_id])


def _build_attempt_runtime_binding(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    attempt_dir: Path,
    turn_number: int,
    attempt_number: int,
    codex_args_path: Path,
) -> tuple[dict[str, Any], bytes, str]:
    module = _load_runtime_binding_module(config)
    lineage_id = str(spec["lineage_id"])
    view = _runtime_binding_view(config, lineage_id=lineage_id)
    nonce = uuid.uuid4().hex
    try:
        binding = module.build_world_runtime_binding(
            run_id=str(config["run_id"]),
            run_dir=resolve_path(config["run_dir"]),
            account_slot=validate_account_slot(config["account_slot"]),
            lineage_id=lineage_id,
            role=str(spec["role"]),
            workspace=resolve_path(spec["workspace"]),
            source_head=str(config["source_head"]).lower(),
            turn_number=turn_number,
            attempt_number=attempt_number,
            invocation_nonce=nonce,
            codex_args_path=codex_args_path,
            codex_args_sha256=sha256_file(codex_args_path).lower(),
            frozen_launcher_path=resolve_path(config["launcher_path"]),
            frozen_launcher_sha256=str(config["launcher_sha256"]).lower(),
            controller_release_path=resolve_path(config["controller_release_path"]),
            controller_release_sha256=str(config["controller_release_sha256"]).lower(),
            controller_python=resolve_path(config["controller_python"]),
            controller_python_sha256=str(config["controller_python_sha256"]).lower(),
            runtime_binding_release_path=resolve_path(config["runtime_binding_release_path"]),
            runtime_binding_release_sha256=str(config["runtime_binding_release_sha256"]).lower(),
            migration_manifest_path=resolve_path(config["reality_migration_manifest_path"]),
            migration_manifest_sha256=str(config["reality_migration_manifest_sha256"]).lower(),
            migration_id=str(config["reality_migration_id"]),
            base_manifest_path=resolve_path(view["base_manifest_path"]),
            base_manifest_sha256=str(view["base_manifest_sha256"]).lower(),
            effective_code_root=resolve_path(view["effective_code_root"]),
            effective_python_path=resolve_path(view["effective_python_path"]),
            effective_code_manifest_path=resolve_path(view["effective_code_manifest_path"]),
            effective_code_manifest_sha256=str(view["effective_code_manifest_sha256"]).lower(),
            effective_code_tree_sha256=str(view["effective_code_tree_sha256"]).lower(),
            effective_code_owner_run_id=str(config["run_id"]),
            effective_code_owner_lineage_id=lineage_id,
            private_live_root=resolve_path(view["private_live_root"]),
            live_seed_receipt_path=resolve_path(view["live_seed_receipt_path"]),
            live_seed_receipt_sha256=str(view["live_seed_receipt_sha256"]).lower(),
        )
        raw = module.world_runtime_binding_bytes(binding)
        file_sha256 = module.world_runtime_binding_file_sha256(binding)
    except Exception as exc:
        reason = getattr(exc, "reason_code", type(exc).__name__)
        raise PerpetualRuntimeError(f"WORLD_RUNTIME_BINDING_BUILD_FAILED:{reason}") from exc
    expected_path = attempt_dir / "runtime_binding.json"
    if resolve_path(binding["binding_path"]) != resolve_path(expected_path):
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_ATTEMPT_PATH_MISMATCH")
    atomic_write_bytes(expected_path, raw)
    return binding, raw, str(file_sha256)


def _validate_attempt_runtime_binding(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    attempt_dir: Path,
    turn_number: int,
    attempt_number: int,
    receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    module = _load_runtime_binding_module(config)
    binding_path = attempt_dir / "runtime_binding.json"
    applied_path = attempt_dir / "binding-applied.json"
    if not binding_path.is_file() or not applied_path.is_file():
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_APPLIED_EVIDENCE_MISSING")
    binding_raw = binding_path.read_bytes()
    binding_file_sha256 = hashlib.sha256(binding_raw).hexdigest()
    try:
        binding = module.validate_world_runtime_binding_bytes(
            binding_raw,
            expected_file_sha256=binding_file_sha256,
        )
        applied_raw = applied_path.read_bytes()
        applied = json.loads(applied_raw.decode("utf-8-sig"))
        module.validate_world_runtime_binding_applied_receipt(
            applied,
            binding=binding,
            binding_file_sha256=binding_file_sha256,
        )
    except Exception as exc:
        reason = getattr(exc, "reason_code", type(exc).__name__)
        raise PerpetualRuntimeError(
            f"WORLD_RUNTIME_BINDING_APPLIED_EVIDENCE_INVALID:{reason}"
        ) from exc
    if (
        binding.get("run_id") != config.get("run_id")
        or binding.get("lineage_id") != spec.get("lineage_id")
        or binding.get("role") != spec.get("role")
        or int(binding.get("turn_number", -1)) != turn_number
        or int(binding.get("attempt_number", -1)) != attempt_number
    ):
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_RECEIPT_IDENTITY_MISMATCH")
    reference = {
        "schema": WORLD_RUNTIME_BINDING_REF_SCHEMA,
        "status": "AVAILABLE",
        "binding_path": str(binding_path.resolve(strict=False)),
        "binding_file_sha256": binding_file_sha256,
        "binding_sha256": str(binding["binding_sha256"]),
        "applied_receipt_path": str(applied_path.resolve(strict=False)),
        "applied_receipt_sha256": hashlib.sha256(applied_raw).hexdigest(),
        "invocation_nonce": str(binding["invocation_nonce"]),
    }
    if receipt is not None and receipt.get("runtime_binding") != reference:
        raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_TURN_RECEIPT_DRIFT")
    return reference


class PerpetualController:
    def __init__(self, config_path: Path) -> None:
        self.config_path = resolve_path(config_path)
        self.config = read_json_object(self.config_path)
        self.schemas = schema_family(self.config.get("schema"))
        self.run_dir = resolve_path(self.config["run_dir"])
        self.stop_path = self.run_dir / "STOP.json"
        self.wake_root = self.run_dir / "wake"
        self.controller_state_path = self.run_dir / "controller_state.json"
        self._state_lock = threading.RLock()
        self._active_processes: dict[str, int] = {}
        self._world_turn_leases: dict[str, dict[str, Any]] = {}
        self._thread_errors: dict[str, str] = {}
        self._started_at = now_iso()
        self._shutdown = threading.Event()
        self._lineage_states: dict[str, dict[str, Any]] = {}
        self._load_lineage_states()

    @property
    def branch_specs(self) -> list[dict[str, Any]]:
        return [dict(value) for value in self.config["branch_lineages"]]

    @property
    def root_spec(self) -> dict[str, Any]:
        return dict(self.config["root_lineage"])

    def lineage_dir(self, lineage_id: str) -> Path:
        return self.run_dir / "lineages" / lineage_id

    def lineage_state_path(self, lineage_id: str) -> Path:
        return self.lineage_dir(lineage_id) / "state.json"

    def _default_lineage_state(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema": self.schemas["lineage"],
            "run_id": self.config["run_id"],
            "lineage_id": spec["lineage_id"],
            "role": spec["role"],
            "workspace": spec["workspace"],
            "source_head": self.config["source_head"],
            "session_id": None,
            "turns_completed": 0,
            "attempts_started": 0,
            "status": "CREATED",
            "lifecycle_state": None,
            "active_pid": None,
            "last_turn_dir": None,
            "last_completed_turn_dir": None,
            "last_error_class": None,
            "last_error": None,
            "updated_at": now_iso(),
        }

    def _load_lineage_states(self) -> None:
        specs = [*self.config["branch_lineages"], self.config["root_lineage"]]
        for raw_spec in specs:
            spec = dict(raw_spec)
            state_path = self.lineage_state_path(str(spec["lineage_id"]))
            if state_path.exists():
                state = read_json_object(state_path)
                if state.get("schema") != self.schemas["lineage"]:
                    raise PerpetualRuntimeError(f"LINEAGE_STATE_SCHEMA_MISMATCH: {state_path}")
            else:
                state = self._default_lineage_state(spec)
                atomic_write_json(state_path, state)
            self._lineage_states[str(spec["lineage_id"])] = state

    def stopped(self) -> bool:
        return self.stop_path.exists() or self._shutdown.is_set()

    def publish_controller_state(self, status: str) -> None:
        with self._state_lock:
            lineages = {
                key: {
                    "role": value.get("role"),
                    "status": value.get("status"),
                    "session_id": value.get("session_id"),
                    "turns_completed": value.get("turns_completed"),
                    "active_pid": value.get("active_pid"),
                    "lifecycle_state": value.get("lifecycle_state"),
                    "last_error_class": value.get("last_error_class"),
                }
                for key, value in sorted(self._lineage_states.items())
            }
            payload = {
                "schema": self.schemas["controller"],
                "run_id": self.config["run_id"],
                "pid": os.getpid(),
                "status": status,
                "started_at": self._started_at,
                "updated_at": now_iso(),
                "stop_requested": self.stop_path.exists(),
                "active_processes": dict(sorted(self._active_processes.items())),
                "thread_errors": dict(sorted(self._thread_errors.items())),
                "lineages": lineages,
            }
            atomic_write_json(self.controller_state_path, payload)
        request_context_consumer_wake(controller_state_path=self.controller_state_path)

    def publish_lineage_state(self, lineage_id: str, **changes: Any) -> None:
        with self._state_lock:
            state = self._lineage_states[lineage_id]
            state.update(changes)
            state["updated_at"] = now_iso()
            atomic_write_json(self.lineage_state_path(lineage_id), state)
            self.publish_controller_state("RUNNING" if not self.stopped() else "STOPPING")

    def verify_runtime_identity(self) -> None:
        validate_pinned_source_commit(
            resolve_path(self.config["source_repo"]), str(self.config["source_head"])
        )
        self.verify_control_body()
        release_path = resolve_path(self.config["controller_release_path"])
        release_sha256 = str(self.config["controller_release_sha256"])
        if sha256_file(release_path) != release_sha256:
            raise PerpetualRuntimeError("CONTROLLER_RELEASE_BYTES_CHANGED")
        if sha256_file(Path(__file__).resolve()) != release_sha256:
            raise PerpetualRuntimeError("ACTIVE_CONTROLLER_BYTES_NOT_FROZEN_RELEASE")
        for spec in [*self.branch_specs, self.root_spec]:
            validate_lineage_runtime_repo(
                resolve_path(spec["workspace"]), str(self.config["source_head"])
            )

    def verify_control_body(self) -> None:
        if (
            sha256_file(resolve_path(self.config["launcher_path"]))
            != self.config["launcher_sha256"]
        ):
            raise PerpetualRuntimeError("CLEANROOM_LAUNCHER_BYTES_CHANGED")
        validate_body_boundary_config(self.config)
        identity = cleanroom_config_identity(resolve_path(self.config["shared_config_path"]))
        expected_semantic = self.config.get(
            "shared_config_semantic_sha256", self.config["shared_config_sha256"]
        )
        if identity["semantic_sha256"] != expected_semantic:
            raise PerpetualRuntimeError(
                "CLEANROOM_SHARED_CONFIG_SEMANTICS_CHANGED: "
                f"expected={expected_semantic} observed={identity['semantic_sha256']}"
            )

    def reject_live_orphaned_children(self) -> None:
        live: dict[str, int] = {}
        cleared: list[str] = []
        with self._state_lock:
            for lineage_id, state in self._lineage_states.items():
                raw_pid = state.get("active_pid")
                if not isinstance(raw_pid, int) or raw_pid <= 0:
                    continue
                if is_process_alive(raw_pid):
                    live[lineage_id] = raw_pid
                    continue
                state["active_pid"] = None
                state["updated_at"] = now_iso()
                atomic_write_json(self.lineage_state_path(lineage_id), state)
                cleared.append(lineage_id)
        if live:
            raise PerpetualRuntimeError(
                "ORPHAN_CHILDREN_ALIVE_BEFORE_RECOVERY: "
                + json.dumps(live, ensure_ascii=False, sort_keys=True)
            )
        if cleared:
            self.publish_controller_state("RECOVERED_STALE_CHILD_STATE")

    def _wake_path(self, lineage_id: str) -> Path:
        return self.wake_root / f"{lineage_id}.json"

    def _world_turn_quota_paths(self) -> tuple[Path, list[Path]]:
        limit = int(
            self.config.get(
                "world_turn_concurrency_limit",
                DEFAULT_WORLD_TURN_CONCURRENCY_LIMIT,
            )
        )
        if limit < 1:
            raise PerpetualRuntimeError("WORLD_TURN_CONCURRENCY_LIMIT_MUST_BE_POSITIVE")
        quota_root = resolve_path(
            self.config.get("world_turn_quota_root", DEFAULT_WORLD_TURN_QUOTA_ROOT)
        )
        account_slot = validate_account_slot(self.config["account_slot"])
        account_root = quota_root / account_slot
        return account_root / "admission.lock", [
            account_root / f"world-turn-{index:02d}.json" for index in range(1, limit + 1)
        ]

    @staticmethod
    def _archive_world_turn_quota_record(path: Path, record: Mapping[str, Any]) -> None:
        lease_id = str(record.get("lease_id", "")).strip()
        if not lease_id:
            raise PerpetualRuntimeError(f"WORLD_TURN_QUOTA_RECORD_IDENTITY_INVALID: {path}")
        raw = path.read_bytes()
        history_path = path.parent / "history" / f"{lease_id}.json"
        if history_path.exists():
            if history_path.read_bytes() != raw:
                raise PerpetualRuntimeError(f"WORLD_TURN_QUOTA_HISTORY_COLLISION: {history_path}")
        else:
            atomic_write_bytes(history_path, raw)

    def try_reserve_world_turn_quota(self, spec: Mapping[str, Any]) -> dict[str, Any] | None:
        """Reserve a durable account slot; RESERVED is never auto-reclaimed."""

        if str(spec.get("role")) != "independent_world":
            return {"counted": False, "reason": "LATE_FUSION_ROOT_EXEMPT"}
        guard_path, record_paths = self._world_turn_quota_paths()
        guard = _try_acquire_byte_lock(guard_path)
        if guard is None:
            return None
        try:
            account_slot = validate_account_slot(self.config["account_slot"])
            lineage_id = str(spec["lineage_id"])
            for slot, record_path in enumerate(record_paths, 1):
                if record_path.is_file():
                    record = read_json_object(record_path)
                    if (
                        record.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
                        or record.get("account_slot") != account_slot
                        or int(record.get("slot", -1)) != slot
                    ):
                        raise PerpetualRuntimeError(
                            f"WORLD_TURN_QUOTA_RECORD_INVALID: {record_path}"
                        )
                    status = str(record.get("status", ""))
                    if status == "RESERVED":
                        # A controller may have died after launching but before binding its child.
                        # Only explicit reconciliation may clear this fail-closed reservation.
                        continue
                    if status == "BOUND":
                        child_pid = record.get("child_pid")
                        if not isinstance(child_pid, int) or child_pid <= 0:
                            raise PerpetualRuntimeError(
                                f"WORLD_TURN_QUOTA_BOUND_CHILD_INVALID: {record_path}"
                            )
                        if is_process_alive(child_pid):
                            continue
                    elif status != "RELEASED":
                        raise PerpetualRuntimeError(
                            f"WORLD_TURN_QUOTA_STATUS_INVALID: {record_path}"
                        )
                    self._archive_world_turn_quota_record(record_path, record)
                lease_id = f"quota-{uuid.uuid4().hex}"
                lease = {
                    "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                    "lease_id": lease_id,
                    "counted": True,
                    "status": "RESERVED",
                    "account_slot": account_slot,
                    "slot": slot,
                    "limit": len(record_paths),
                    "run_id": self.config["run_id"],
                    "lineage_id": lineage_id,
                    "workspace": str(resolve_path(spec["workspace"])),
                    "controller_pid": os.getpid(),
                    "child_pid": None,
                    "reserved_at": now_iso(),
                    "bound_at": None,
                    "released_at": None,
                }
                atomic_write_json(record_path, lease)
                lease["path"] = str(record_path)
                self._world_turn_leases[lineage_id] = lease
                return dict(lease)
            return None
        finally:
            _release_byte_lock(guard)

    def bind_world_turn_quota_child(
        self, spec: Mapping[str, Any], *, child_pid: int
    ) -> dict[str, Any] | None:
        """Bind the durable reservation to the actual child before it can be forgotten."""

        if str(spec.get("role")) != "independent_world":
            return None
        lineage_id = str(spec["lineage_id"])
        lease = self._world_turn_leases.get(lineage_id)
        if lease is None:
            if "world_turn_concurrency_limit" in self.config:
                raise PerpetualRuntimeError("WORLD_TURN_QUOTA_LEASE_MISSING")
            return None
        guard_path, _ = self._world_turn_quota_paths()
        deadline = time.monotonic() + 30.0
        while True:
            guard = _try_acquire_byte_lock(guard_path)
            if guard is not None:
                break
            if time.monotonic() >= deadline:
                raise PerpetualRuntimeError("WORLD_TURN_QUOTA_BIND_TIMEOUT")
            time.sleep(0.05)
        try:
            record_path = resolve_path(lease["path"])
            record = read_json_object(record_path)
            if (
                record.get("lease_id") != lease["lease_id"]
                or record.get("status") != "RESERVED"
                or record.get("run_id") != self.config["run_id"]
                or record.get("lineage_id") != lineage_id
            ):
                raise PerpetualRuntimeError("WORLD_TURN_QUOTA_RESERVATION_DRIFT")
            record.update(
                {
                    "status": "BOUND",
                    "child_pid": int(child_pid),
                    "bound_at": now_iso(),
                }
            )
            atomic_write_json(record_path, record)
            record["path"] = str(record_path)
            self._world_turn_leases[lineage_id] = record
            return dict(record)
        finally:
            _release_byte_lock(guard)

    def release_world_turn_quota(self, spec: Mapping[str, Any]) -> bool:
        if str(spec.get("role")) != "independent_world":
            return True
        lineage_id = str(spec["lineage_id"])
        lease = self._world_turn_leases.get(lineage_id)
        if lease is None:
            return True
        guard_path, _ = self._world_turn_quota_paths()
        deadline = time.monotonic() + 30.0
        while True:
            guard = _try_acquire_byte_lock(guard_path)
            if guard is not None:
                break
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        try:
            record_path = resolve_path(lease["path"])
            record = read_json_object(record_path)
            if record.get("lease_id") != lease["lease_id"]:
                raise PerpetualRuntimeError("WORLD_TURN_QUOTA_RELEASE_IDENTITY_DRIFT")
            child_pid = record.get("child_pid")
            if isinstance(child_pid, int) and child_pid > 0 and is_process_alive(child_pid):
                return False
            record.update({"status": "RELEASED", "released_at": now_iso()})
            atomic_write_json(record_path, record)
            self._world_turn_leases.pop(lineage_id, None)
            return True
        finally:
            _release_byte_lock(guard)

    @contextlib.contextmanager
    def world_turn_quota_lease(self, spec: Mapping[str, Any]) -> Iterator[dict[str, Any] | None]:
        """Count only world-owning Sol calls against the shared A/C account cap."""

        if str(spec.get("role")) != "independent_world":
            yield {"counted": False, "reason": "LATE_FUSION_ROOT_EXEMPT"}
            return
        lineage_id = str(spec["lineage_id"])
        waiting_published = False
        lease: dict[str, Any] | None = None
        while not self.stopped():
            lease = self.try_reserve_world_turn_quota(spec)
            if lease is not None:
                self.publish_lineage_state(
                    lineage_id,
                    status="WORLD_TURN_QUOTA_RESERVED",
                    active_pid=None,
                    world_turn_quota=lease,
                )
                break
            if not waiting_published:
                _, record_paths = self._world_turn_quota_paths()
                self.publish_lineage_state(
                    lineage_id,
                    status="WAITING_FOR_ACCOUNT_WORLD_TURN_QUOTA",
                    active_pid=None,
                    world_turn_quota={
                        "counted": True,
                        "account_slot": validate_account_slot(self.config["account_slot"]),
                        "limit": len(record_paths),
                        "slot": None,
                    },
                )
                waiting_published = True
            self._shutdown.wait(1.0)
        try:
            yield lease
        finally:
            if lease is not None:
                self.release_world_turn_quota(spec)
                with self._state_lock:
                    self._lineage_states[lineage_id].pop("world_turn_quota", None)
                    atomic_write_json(
                        self.lineage_state_path(lineage_id),
                        self._lineage_states[lineage_id],
                    )

    def _wait_parked(self, lineage_id: str, status: str) -> bool:
        wake_path = self._wake_path(lineage_id)
        self.publish_lineage_state(lineage_id, status=status, active_pid=None)
        while not self.stopped():
            if wake_path.exists():
                consumed = (
                    self.lineage_dir(lineage_id)
                    / "wake-receipts"
                    / (dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json")
                )
                consumed.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(wake_path, consumed)
                except FileNotFoundError:
                    continue
                self.publish_lineage_state(
                    lineage_id,
                    status="WOKEN",
                    lifecycle_state="CONTINUE",
                    last_error_class=None,
                    last_error=None,
                )
                return True
            self._shutdown.wait(float(self.config["park_poll_seconds"]))
        return False

    def _event_update(
        self,
        lineage_id: str,
        event: Mapping[str, Any],
        observed: dict[str, Any],
    ) -> None:
        event_type = event.get("type")
        if event_type == "thread.started" and event.get("thread_id"):
            thread_id = str(event["thread_id"])
            observed["thread_id"] = thread_id
            if self._lineage_states[lineage_id].get("session_id") != thread_id:
                self.publish_lineage_state(lineage_id, session_id=thread_id)
        if event_type in {"turn.completed", "turn.failed", "turn.cancelled"}:
            observed["turn_status"] = event_type
            observed["usage"] = event.get("usage")
        item = event.get("item")
        if isinstance(item, dict):
            observed["response_item_count"] += 1
            item_type = str(item.get("type", ""))
            if item_type not in {"agent_message", "reasoning"}:
                observed["tool_item_count"] += 1

    def _run_attempt(
        self,
        *,
        spec: Mapping[str, Any],
        state: dict[str, Any],
        turn_number: int,
        attempt_number: int,
        prompt: str,
    ) -> dict[str, Any]:
        lineage_id = str(spec["lineage_id"])
        turn_dir = self.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
        attempt_dir = turn_dir / f"attempt-{attempt_number:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        stdout_path = attempt_dir / "exec_stdout.jsonl"
        stderr_path = attempt_dir / "exec_stderr.txt"
        last_message_path = attempt_dir / "last_message.txt"
        prompt_path = attempt_dir / "prompt.txt"
        arguments_path = attempt_dir / "codex_args.json"
        atomic_write_text(prompt_path, prompt)
        session_id = state.get("session_id")
        codex_arguments = build_codex_arguments(
            self.config,
            last_message_path=last_message_path,
            session_id=str(session_id) if session_id else None,
        )
        binding_required = _turn_requires_runtime_binding(
            self.config,
            lineage_id=lineage_id,
            turn_number=turn_number,
        )
        if binding_required:
            binding_module = _load_runtime_binding_module(self.config)
            atomic_write_bytes(
                arguments_path,
                binding_module.canonical_json_bytes(codex_arguments),
            )
        else:
            atomic_write_json(arguments_path, codex_arguments)
        runtime_binding: dict[str, Any] | None = None
        runtime_binding_file_sha256: str | None = None
        runtime_binding_applied_path: Path | None = None
        if binding_required:
            runtime_binding, _, runtime_binding_file_sha256 = _build_attempt_runtime_binding(
                config=self.config,
                spec=spec,
                attempt_dir=attempt_dir,
                turn_number=turn_number,
                attempt_number=attempt_number,
                codex_args_path=arguments_path,
            )
            runtime_binding_applied_path = resolve_path(runtime_binding["applied_receipt_path"])
        if runtime_binding is None:
            command = build_codex_command(
                self.config,
                workspace=resolve_path(spec["workspace"]),
                arguments_path=arguments_path,
            )
        else:
            command = build_codex_command(
                self.config,
                workspace=resolve_path(spec["workspace"]),
                arguments_path=arguments_path,
                runtime_binding_path=resolve_path(runtime_binding["binding_path"]),
                runtime_binding_sha256=runtime_binding_file_sha256,
                runtime_binding_applied_path=runtime_binding_applied_path,
                runtime_binding_invocation_nonce=str(runtime_binding["invocation_nonce"]),
            )
        atomic_write_json(
            attempt_dir / "command.json",
            {
                "argv": sanitize_command(command),
                "codex_argv": codex_arguments,
                "codex_args_sha256": sha256_file(arguments_path),
                "cwd": str(resolve_path(spec["workspace"])),
                "account_slot": validate_account_slot(self.config["account_slot"]),
                "model": self.config["model"],
                "model_reasoning_effort": self.config["model_reasoning_effort"],
                "resume_session_id": session_id,
                "prompt_sha256": sha256_file(prompt_path),
                "runtime_binding_required": binding_required,
                "runtime_binding_path": (
                    str(runtime_binding["binding_path"]) if runtime_binding is not None else None
                ),
                "runtime_binding_file_sha256": runtime_binding_file_sha256,
                "runtime_binding_applied_path": (
                    str(runtime_binding_applied_path)
                    if runtime_binding_applied_path is not None
                    else None
                ),
                "runtime_binding_invocation_nonce": (
                    str(runtime_binding["invocation_nonce"])
                    if runtime_binding is not None
                    else None
                ),
            },
        )
        observed: dict[str, Any] = {
            "thread_id": session_id,
            "turn_status": None,
            "usage": None,
            "response_item_count": 0,
            "tool_item_count": 0,
        }
        started_at = now_iso()
        started_monotonic = time.monotonic()
        stopped = False
        timed_out = False
        parsed_offset = 0
        pending = b""
        if (
            str(spec.get("role")) == "independent_world"
            and "world_turn_concurrency_limit" in self.config
            and lineage_id not in self._world_turn_leases
        ):
            raise PerpetualRuntimeError("WORLD_TURN_QUOTA_LEASE_MISSING_BEFORE_LAUNCH")
        with (
            stdout_path.open("ab", buffering=0) as stdout_stream,
            stderr_path.open("ab", buffering=0) as stderr_stream,
        ):
            process = subprocess.Popen(
                command,
                cwd=resolve_path(spec["workspace"]),
                stdin=subprocess.PIPE,
                stdout=stdout_stream,
                stderr=stderr_stream,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                bound_quota = self.bind_world_turn_quota_child(
                    spec,
                    child_pid=process.pid,
                )
            except BaseException:
                terminate_process_tree(process)
                raise
            with self._state_lock:
                self._active_processes[lineage_id] = process.pid
            self.publish_lineage_state(
                lineage_id,
                status="TURN_RUNNING",
                active_pid=process.pid,
                attempts_started=int(state.get("attempts_started", 0)) + 1,
                last_turn_dir=str(turn_dir),
                world_turn_quota=bound_quota,
            )
            assert process.stdin is not None
            try:
                process.stdin.write(prompt.encode("utf-8"))
                process.stdin.flush()
            except BrokenPipeError:
                # Preserve the native process failure and its stderr as the diagnosis.
                pass
            finally:
                process.stdin.close()
            while process.poll() is None:
                if stdout_path.exists():
                    with stdout_path.open("rb") as reader:
                        reader.seek(parsed_offset)
                        chunk = reader.read()
                    if chunk:
                        parsed_offset += len(chunk)
                        pending += chunk
                        lines = pending.split(b"\n")
                        pending = lines.pop()
                        for line in lines:
                            event = parse_event_line(line)
                            if event is not None:
                                self._event_update(lineage_id, event, observed)
                if self.stopped():
                    stopped = True
                    terminate_process_tree(process)
                    break
                if time.monotonic() - started_monotonic > float(self.config["watchdog_seconds"]):
                    timed_out = True
                    terminate_process_tree(process)
                    break
                time.sleep(0.5)
            try:
                exit_code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                exit_code = process.wait(timeout=60)
            if stdout_path.exists():
                with stdout_path.open("rb") as reader:
                    reader.seek(parsed_offset)
                    pending += reader.read()
                for line in pending.splitlines():
                    event = parse_event_line(line)
                    if event is not None:
                        self._event_update(lineage_id, event, observed)
        with self._state_lock:
            self._active_processes.pop(lineage_id, None)
        runtime_binding_reference: dict[str, Any] | None = None
        runtime_binding_error: str | None = None
        if binding_required:
            try:
                runtime_binding_reference = _validate_attempt_runtime_binding(
                    config=self.config,
                    spec=spec,
                    attempt_dir=attempt_dir,
                    turn_number=turn_number,
                    attempt_number=attempt_number,
                    receipt=None,
                )
            except PerpetualRuntimeError as exc:
                runtime_binding_error = str(exc).split(":", 1)[0]
                runtime_binding_reference = {
                    "schema": WORLD_RUNTIME_BINDING_REF_SCHEMA,
                    "status": "INVALID",
                    "binding_path": str(attempt_dir / "runtime_binding.json"),
                    "applied_receipt_path": str(attempt_dir / "binding-applied.json"),
                    "error_class": runtime_binding_error,
                }
        last_message = (
            last_message_path.read_text(encoding="utf-8", errors="replace")
            if last_message_path.exists()
            else ""
        )
        body_incidents = (
            classify_body_incident_events(
                stdout_path,
                workspace=resolve_path(spec["workspace"]),
            )
            if stdout_path.exists()
            else []
        )
        body_incident: dict[str, Any] | None = None
        if body_incidents:
            incident_id = (
                f"body-{self.config['run_id']}-{lineage_id}-"
                f"t{turn_number:06d}-a{attempt_number:02d}"
            )
            body_incident = {
                "schema": BODY_INCIDENT_SCHEMA,
                "incident_id": incident_id,
                "run_id": self.config["run_id"],
                "lineage_id": lineage_id,
                "turn_number": turn_number,
                "attempt_number": attempt_number,
                "observed_at": now_iso(),
                "sandbox_mode": self.config.get("body_boundary", {}).get("sandbox_mode", "UNKNOWN"),
                "failure_class": "WRITE_DOMAIN_DENIED",
                "affected_evidence_refs": body_incidents,
                "evidence_adoptable": False,
                "resume_same_lineage_after_body_repair": True,
            }
            atomic_write_json(attempt_dir / "body_incident.json", body_incident)
        lifecycle = parse_lifecycle_state(last_message)
        stdout_tail = safe_tail(stdout_path)
        stderr_tail = safe_tail(stderr_path)
        error_class = None
        if stopped:
            error_class = "STOP_REQUESTED"
        elif timed_out:
            error_class = "WATCHDOG_TIMEOUT"
        elif body_incident is not None:
            error_class = "BODY_INCIDENT"
        elif runtime_binding_error is not None:
            error_class = "EVIDENCE_INCIDENT"
        elif exit_code != 0 or observed["turn_status"] != "turn.completed":
            error_class = classify_failure(stdout_tail, stderr_tail)
        elif lifecycle is None:
            error_class = "MISSING_LIFECYCLE_RECEIPT"
        ended_at = now_iso()
        deep_evidence: dict[str, Any] = {
            "status": "NOT_CAPTURED_FAILED_ATTEMPT",
            "captured_at": ended_at,
        }
        if error_class is None:
            evidence_errors: list[str] = []
            trajectory: dict[str, Any] | None = None
            artifacts: dict[str, Any] | None = None
            try:
                trajectory = build_trajectory_index(
                    stdout_path, attempt_dir / "trajectory_index.jsonl"
                )
            except (FileNotFoundError, PermissionError, OSError, PerpetualRuntimeError) as exc:
                evidence_errors.append(f"TRAJECTORY_INDEX:{type(exc).__name__}")
            try:
                artifacts = capture_workspace_artifacts(
                    workspace=resolve_path(spec["workspace"]),
                    run_id=str(self.config["run_id"]),
                    source_head=str(self.config["source_head"]),
                    run_dir=self.run_dir,
                    lineage_id=lineage_id,
                    turn_number=turn_number,
                    attempt_number=attempt_number,
                    manifest_path=attempt_dir / "artifact_manifest.json",
                )
            except (FileNotFoundError, PermissionError, OSError, PerpetualRuntimeError) as exc:
                evidence_errors.append(f"ARTIFACT_MANIFEST:{type(exc).__name__}")
            if trajectory is not None or artifacts is not None:
                partial = bool(evidence_errors) or not bool(
                    artifacts is not None and artifacts.get("complete") is True
                )
                deep_evidence = {
                    "status": "PARTIAL" if partial else "AVAILABLE",
                    "captured_at": now_iso(),
                    "trajectory": trajectory,
                    "artifacts": artifacts,
                    "errors": evidence_errors,
                }
            else:
                deep_evidence = {
                    "status": "UNAVAILABLE",
                    "captured_at": now_iso(),
                    "error_class": "DEEP_EVIDENCE_CAPTURE_FAILED",
                    "errors": evidence_errors,
                }
            if (
                self.config.get("deep_evidence_required") is True
                and deep_evidence.get("status") != "AVAILABLE"
            ):
                error_class = "EVIDENCE_INCIDENT"
        receipt = {
            "schema": self.schemas["turn"],
            "run_id": self.config["run_id"],
            "lineage_id": lineage_id,
            "role": spec["role"],
            "turn_number": turn_number,
            "attempt_number": attempt_number,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "pid": process.pid,
            "exit_code": exit_code,
            "stopped": stopped,
            "timed_out": timed_out,
            "session_id_before": session_id,
            "session_id_observed": observed["thread_id"],
            "turn_status": observed["turn_status"],
            "usage": observed["usage"],
            "response_item_count": observed["response_item_count"],
            "tool_item_count": observed["tool_item_count"],
            "lifecycle_state": lifecycle,
            "error_class": error_class,
            "prompt_sha256": sha256_file(prompt_path),
            "stdout_sha256": sha256_file(stdout_path),
            "stderr_sha256": sha256_file(stderr_path),
            "last_message_sha256": (
                sha256_file(last_message_path) if last_message_path.exists() else None
            ),
            "body_boundary": self.config.get("body_boundary"),
            "body_incident": body_incident,
            "deep_evidence": deep_evidence,
            "runtime_binding": runtime_binding_reference,
        }
        atomic_write_json(attempt_dir / "receipt.json", receipt)
        if observed["thread_id"]:
            self.publish_lineage_state(lineage_id, session_id=observed["thread_id"])
        return {
            "receipt": receipt,
            "turn_dir": turn_dir,
            "attempt_dir": attempt_dir,
            "last_message_path": last_message_path,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }

    def execute_turn(
        self,
        *,
        spec: Mapping[str, Any],
        prompt: str,
    ) -> dict[str, Any]:
        lineage_id = str(spec["lineage_id"])
        try:
            self.verify_control_body()
        except PerpetualRuntimeError as exc:
            self.publish_lineage_state(
                lineage_id,
                status="CONTROL_BODY_DRIFT_PAUSED",
                active_pid=None,
                last_error_class="CONTROL_BODY_DRIFT",
                last_error=str(exc),
            )
            return {
                "outcome": "FAILED",
                "error_class": "CONTROL_BODY_DRIFT",
            }
        state = self._lineage_states[lineage_id]
        turn_number = int(state.get("turns_completed", 0)) + 1
        turn_dir = self.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
        prior_attempt_count = len(list(turn_dir.glob("attempt-*")))
        retry_delays = [float(value) for value in self.config["retry_delays_seconds"]]
        for local_attempt in range(1, len(retry_delays) + 2):
            attempt_number = prior_attempt_count + local_attempt
            if self.stopped():
                return {"outcome": "STOPPED"}
            try:
                result = self._run_attempt(
                    spec=spec,
                    state=state,
                    turn_number=turn_number,
                    attempt_number=attempt_number,
                    prompt=prompt,
                )
            except PerpetualRuntimeError as exc:
                if not str(exc).startswith("WORLD_RUNTIME_BINDING"):
                    raise
                self.publish_lineage_state(
                    lineage_id,
                    status="EVIDENCE_INCIDENT",
                    active_pid=None,
                    last_error_class="EVIDENCE_INCIDENT",
                    last_error=str(exc).split(":", 1)[0],
                )
                return {
                    "outcome": "FAILED",
                    "error_class": "EVIDENCE_INCIDENT",
                }
            receipt = result["receipt"]
            error_class = receipt["error_class"]
            if error_class is None:
                lifecycle = str(receipt["lifecycle_state"])
                self.publish_lineage_state(
                    lineage_id,
                    status="TURN_COMPLETED",
                    turns_completed=turn_number,
                    lifecycle_state=lifecycle,
                    active_pid=None,
                    last_turn_dir=str(result["turn_dir"]),
                    last_completed_turn_dir=str(result["turn_dir"]),
                    last_error_class=None,
                    last_error=None,
                )
                return {
                    "outcome": "COMPLETED",
                    "lifecycle_state": lifecycle,
                    **result,
                }
            summary = (result["stderr_tail"] or result["stdout_tail"])[-4000:]
            self.publish_lineage_state(
                lineage_id,
                status=(
                    error_class
                    if error_class in {"BODY_INCIDENT", "EVIDENCE_INCIDENT"}
                    else "TURN_FAILED"
                ),
                active_pid=None,
                last_error_class=error_class,
                last_error=(
                    str(receipt.get("body_incident", {}).get("incident_id"))
                    if error_class == "BODY_INCIDENT"
                    else summary
                ),
            )
            if error_class != "TRANSIENT_RUNTIME_FAILURE" or local_attempt > len(retry_delays):
                return {"outcome": "FAILED", "error_class": error_class, **result}
            delay = retry_delays[local_attempt - 1]
            deadline = time.monotonic() + delay
            self.publish_lineage_state(lineage_id, status="TRANSIENT_BACKOFF")
            while not self.stopped() and time.monotonic() < deadline:
                self._shutdown.wait(min(1.0, deadline - time.monotonic()))
            state = self._lineage_states[lineage_id]
        raise AssertionError("retry loop exhausted unexpectedly")

    def branch_loop(self, spec: Mapping[str, Any]) -> None:
        lineage_id = str(spec["lineage_id"])
        try:
            recovered_state = self._lineage_states[lineage_id]
            recovered_lifecycle = recovered_state.get("lifecycle_state")
            if (
                recovered_state.get("session_id")
                and recovered_lifecycle in PARKED_LIFECYCLE_STATES
                and not self._wait_parked(lineage_id, f"PARKED_{recovered_lifecycle}")
            ):
                return
            while not self.stopped():
                state = self._lineage_states[lineage_id]
                if not state.get("session_id"):
                    prompt = (self.lineage_dir(lineage_id) / "initial_prompt.txt").read_text(
                        encoding="utf-8"
                    )
                else:
                    prompt = build_continuation_prompt(lineage_id=lineage_id)
                with self.world_turn_quota_lease(spec) as quota_lease:
                    if quota_lease is None:
                        break
                    result = self.execute_turn(spec=spec, prompt=prompt)
                if result["outcome"] == "STOPPED":
                    break
                if result["outcome"] == "FAILED":
                    error_class = str(result.get("error_class", ""))
                    parked_status = (
                        error_class
                        if error_class in {"BODY_INCIDENT", "EVIDENCE_INCIDENT"}
                        else "RUNTIME_PAUSED"
                    )
                    if not self._wait_parked(lineage_id, parked_status):
                        break
                    continue
                lifecycle = result["lifecycle_state"]
                if lifecycle == "CONTINUE":
                    deadline = time.monotonic() + float(self.config["continuation_delay_seconds"])
                    self.publish_lineage_state(lineage_id, status="READY_TO_CONTINUE")
                    while not self.stopped() and time.monotonic() < deadline:
                        self._shutdown.wait(min(1.0, deadline - time.monotonic()))
                    continue
                if not self._wait_parked(lineage_id, f"PARKED_{lifecycle}"):
                    break
        except BaseException:
            error = traceback.format_exc()
            with self._state_lock:
                self._thread_errors[lineage_id] = error
            self.publish_lineage_state(
                lineage_id,
                status="CONTROLLER_THREAD_FAILED",
                active_pid=None,
                last_error_class="CONTROLLER_THREAD_FAILED",
                last_error=error[-8000:],
            )

    def _packet_state_path(self) -> Path:
        return self.lineage_dir(str(self.root_spec["lineage_id"])) / "fusion_state.json"

    def _load_fusion_state(self) -> dict[str, Any]:
        path = self._packet_state_path()
        if path.exists():
            state = read_json_object(path)
            if (
                state.get("schema") != self.schemas["packet"]
                or state.get("run_id") != self.config["run_id"]
            ):
                raise PerpetualRuntimeError(f"FUSION_STATE_IDENTITY_MISMATCH: {path}")
            state.setdefault("pending_packet", None)
            return state
        state = {
            "schema": self.schemas["packet"],
            "run_id": self.config["run_id"],
            "waves_completed": 0,
            "consumed_turns": {str(spec["lineage_id"]): 0 for spec in self.branch_specs},
            "pending_packet": None,
            "updated_at": now_iso(),
        }
        atomic_write_json(path, state)
        return state

    def _completed_turn_candidate(
        self, lineage_id: str, state: Mapping[str, Any]
    ) -> tuple[int, Path, Path, dict[str, Any], bytes]:
        turn_number = int(state.get("turns_completed", 0))
        if turn_number < 1:
            raise PerpetualRuntimeError(f"FUSION_SOURCE_HAS_NO_COMPLETED_TURN: {lineage_id}")
        turn_dir = self.lineage_dir(lineage_id) / "turns" / f"turn-{turn_number:06d}"
        attempts = sorted(turn_dir.glob("attempt-*"), reverse=True)
        for attempt in attempts:
            receipt_path = attempt / "receipt.json"
            message_path = attempt / "last_message.txt"
            if not receipt_path.is_file() or not message_path.is_file():
                continue
            receipt = read_json_object(receipt_path)
            if (
                receipt.get("schema") != self.schemas["turn"]
                or receipt.get("run_id") != self.config["run_id"]
                or receipt.get("lineage_id") != lineage_id
                or int(receipt.get("turn_number", -1)) != turn_number
                or receipt.get("error_class") is not None
            ):
                continue
            normal_process_success = (
                receipt.get("process_exit_code_observed") is not False
                and receipt.get("exit_code") == 0
            )
            recovered_process_success = (
                receipt.get("recovered_from_incomplete_attempt") is True
                and receipt.get("process_exit_code_observed") is False
                and receipt.get("exit_code") is None
                and receipt.get("inferred_process_success") is True
                and receipt.get("completion_basis")
                == "RECOVERED_TURN_COMPLETED_EVENT_AND_LIFECYCLE"
                and receipt.get("turn_status") == "turn.completed"
            )
            if not normal_process_success and not recovered_process_success:
                continue
            evidence_required = _turn_requires_deep_evidence(
                self.config,
                lineage_id=lineage_id,
                turn_number=turn_number,
            )
            if evidence_required:
                deep_evidence = receipt.get("deep_evidence")
                if (
                    not isinstance(deep_evidence, Mapping)
                    or deep_evidence.get("status") != "AVAILABLE"
                ):
                    continue
            if _turn_requires_runtime_binding(
                self.config,
                lineage_id=lineage_id,
                turn_number=turn_number,
            ):
                source_spec = next(
                    item
                    for item in [*self.branch_specs, self.root_spec]
                    if str(item["lineage_id"]) == lineage_id
                )
                _validate_attempt_runtime_binding(
                    config=self.config,
                    spec=source_spec,
                    attempt_dir=attempt,
                    turn_number=turn_number,
                    attempt_number=int(receipt["attempt_number"]),
                    receipt=receipt,
                )
            raw = message_path.read_bytes()
            if receipt.get("last_message_sha256") != sha256_bytes(raw):
                raise PerpetualRuntimeError(
                    f"FUSION_SOURCE_LAST_MESSAGE_HASH_MISMATCH: {message_path}"
                )
            return turn_number, attempt, message_path, receipt, raw
        raise PerpetualRuntimeError(f"FUSION_SOURCE_SUCCESSFUL_ATTEMPT_MISSING: {turn_dir}")

    def _read_existing_fusion_packet(
        self, packet_dir: Path, wave_number: int
    ) -> tuple[Path, dict[str, Any]]:
        manifest_path = packet_dir / "PACKET_MANIFEST.json"
        if not manifest_path.is_file():
            raise PerpetualRuntimeError(f"FUSION_PACKET_MANIFEST_MISSING: {packet_dir}")
        manifest = read_json_object(manifest_path)
        if (
            manifest.get("schema") != self.schemas["packet"]
            or manifest.get("run_id") != self.config["run_id"]
            or int(manifest.get("wave_number", -1)) != wave_number
            or manifest.get("source_head") != self.config["source_head"]
            or manifest.get("candidate_authority") is not False
            or manifest.get("s_content_adjudication") is not False
        ):
            raise PerpetualRuntimeError(f"FUSION_PACKET_IDENTITY_MISMATCH: {packet_dir}")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or len(entries) != len(self.branch_specs):
            raise PerpetualRuntimeError(f"FUSION_PACKET_ENTRY_COUNT_MISMATCH: {packet_dir}")
        selected_turns: dict[str, int] = {}
        deep_mode = manifest.get("deep_evidence_mode")
        if deep_mode not in {None, "thin_index_on_demand_v1"}:
            raise PerpetualRuntimeError(f"FUSION_PACKET_DEEP_EVIDENCE_MODE_INVALID: {packet_dir}")
        for index, (entry, spec) in enumerate(zip(entries, self.branch_specs, strict=True), 1):
            if not isinstance(entry, dict):
                raise PerpetualRuntimeError(f"FUSION_PACKET_ENTRY_INVALID: {packet_dir}")
            lineage_id = str(spec["lineage_id"])
            expected_name = f"CANDIDATE_{index:02d}.txt"
            if (
                entry.get("source_lineage_id") != lineage_id
                or entry.get("packet_path") != expected_name
            ):
                raise PerpetualRuntimeError(f"FUSION_PACKET_ENTRY_IDENTITY_MISMATCH: {packet_dir}")
            candidate_path = packet_dir / expected_name
            if not candidate_path.is_file():
                raise PerpetualRuntimeError(f"FUSION_PACKET_CANDIDATE_MISSING: {candidate_path}")
            if sha256_file(candidate_path) != entry.get("source_last_message_sha256"):
                raise PerpetualRuntimeError(
                    f"FUSION_PACKET_CANDIDATE_HASH_MISMATCH: {candidate_path}"
                )
            if deep_mode == "thin_index_on_demand_v1":
                expected_deep_name = f"DEEP_EVIDENCE_{index:02d}.json"
                if entry.get("deep_evidence_path") != expected_deep_name:
                    raise PerpetualRuntimeError(
                        f"FUSION_PACKET_DEEP_EVIDENCE_IDENTITY_MISMATCH: {packet_dir}"
                    )
                deep_path = packet_dir / expected_deep_name
                if not deep_path.is_file():
                    raise PerpetualRuntimeError(f"FUSION_PACKET_DEEP_EVIDENCE_MISSING: {deep_path}")
                if sha256_file(deep_path) != entry.get("deep_evidence_sha256"):
                    raise PerpetualRuntimeError(
                        f"FUSION_PACKET_DEEP_EVIDENCE_HASH_MISMATCH: {deep_path}"
                    )
                deep = read_json_object(deep_path)
                if (
                    deep.get("schema") != DEEP_EVIDENCE_REF_SCHEMA
                    or deep.get("lineage_id") != lineage_id
                    or int(deep.get("turn_number", -1)) != int(entry["source_turn_number"])
                    or deep.get("candidate_authority") is not False
                    or deep.get("s_content_adjudication") is not False
                ):
                    raise PerpetualRuntimeError(f"FUSION_PACKET_DEEP_EVIDENCE_INVALID: {deep_path}")
            selected_turns[lineage_id] = int(entry["source_turn_number"])
        manifest["manifest_sha256"] = sha256_file(manifest_path)
        return packet_dir, {"manifest": manifest, "selected_turns": selected_turns}

    def freeze_fusion_packet(self, fusion_state: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        wave_number = int(fusion_state.get("waves_completed", 0)) + 1
        root_workspace = resolve_path(self.root_spec["workspace"])
        packet_dir = root_workspace / "S_CONTROL_INPUTS" / f"wave-{wave_number:06d}"
        if packet_dir.exists():
            return self._read_existing_fusion_packet(packet_dir, wave_number)
        staging_dir = packet_dir.with_name(f".{packet_dir.name}.{uuid.uuid4().hex}.tmp")
        staging_dir.mkdir(parents=True)
        entries: list[dict[str, Any]] = []
        selected_turns: dict[str, int] = {}
        with self._state_lock:
            snapshots = {
                str(spec["lineage_id"]): dict(self._lineage_states[str(spec["lineage_id"])])
                for spec in self.branch_specs
            }
        try:
            for index, spec in enumerate(self.branch_specs, 1):
                lineage_id = str(spec["lineage_id"])
                state = snapshots[lineage_id]
                turn_number, attempt_dir, _, receipt, raw = self._completed_turn_candidate(
                    lineage_id, state
                )
                destination = staging_dir / f"CANDIDATE_{index:02d}.txt"
                atomic_write_bytes(destination, raw)
                deep_destination = staging_dir / f"DEEP_EVIDENCE_{index:02d}.json"
                controller_release = resolve_path(
                    self.config.get("controller_release_path", Path(__file__).resolve())
                )
                controller_python = str(self.config.get("controller_python", sys.executable))
                query_command_prefix = [
                    controller_python,
                    str(controller_release),
                    "inspect-evidence",
                    "--packet",
                    str(packet_dir),
                    "--candidate-index",
                    str(index),
                ]
                deep_reference = build_deep_evidence_reference(
                    run_dir=self.run_dir,
                    lineage_id=lineage_id,
                    turn_number=turn_number,
                    attempt_dir=attempt_dir,
                    receipt=receipt,
                    workspace=resolve_path(spec["workspace"]),
                    source_head=str(self.config["source_head"]),
                    query_command_prefix=query_command_prefix,
                )
                deep_sha256 = atomic_write_json(deep_destination, deep_reference)
                entries.append(
                    {
                        "anonymous_index": index,
                        "source_lineage_id": lineage_id,
                        "source_session_id": receipt.get("session_id_observed"),
                        "source_turn_number": turn_number,
                        "source_last_message_sha256": sha256_bytes(raw),
                        "packet_path": destination.name,
                        "source_workspace": spec["workspace"],
                        "source_workspace_head": git_output(
                            resolve_path(spec["workspace"]), "rev-parse", "HEAD"
                        ),
                        "deep_evidence_path": deep_destination.name,
                        "deep_evidence_sha256": deep_sha256,
                        "deep_evidence_availability": deep_reference["availability"],
                    }
                )
                selected_turns[lineage_id] = turn_number
            manifest = {
                "schema": self.schemas["packet"],
                "run_id": self.config["run_id"],
                "wave_number": wave_number,
                "frozen_at": now_iso(),
                "source_head": self.config["source_head"],
                "selection_rule": "latest successful completed turn snapshot from every branch",
                "candidate_authority": False,
                "s_content_adjudication": False,
                "deep_evidence_mode": "thin_index_on_demand_v1",
                "deep_evidence_read_policy": (
                    "Main receives navigation indices and opens exact turn events or immutable "
                    "artifact blobs only on demand; raw trajectories are not bulk-injected."
                ),
                "entries": entries,
            }
            atomic_write_json(staging_dir / "PACKET_MANIFEST.json", manifest)
            os.replace(staging_dir, packet_dir)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
        return self._read_existing_fusion_packet(packet_dir, wave_number)

    def _load_or_create_pending_packet(
        self, fusion_state: dict[str, Any]
    ) -> tuple[Path, dict[str, Any]]:
        pending = fusion_state.get("pending_packet")
        if isinstance(pending, dict):
            packet_dir = resolve_path(pending["packet_dir"])
            expected_parent = resolve_path(self.root_spec["workspace"]) / "S_CONTROL_INPUTS"
            if packet_dir.parent != expected_parent:
                raise PerpetualRuntimeError(f"PENDING_FUSION_PACKET_OUTSIDE_ROOT: {packet_dir}")
            packet_dir, packet = self._read_existing_fusion_packet(
                packet_dir, int(pending["wave_number"])
            )
            if (
                packet["manifest"]["manifest_sha256"] != pending["manifest_sha256"]
                or packet["selected_turns"] != pending["selected_turns"]
            ):
                raise PerpetualRuntimeError(f"PENDING_FUSION_PACKET_DRIFT: {packet_dir}")
            return packet_dir, packet
        packet_dir, packet = self.freeze_fusion_packet(fusion_state)
        fusion_state["pending_packet"] = {
            "wave_number": int(packet["manifest"]["wave_number"]),
            "packet_dir": str(packet_dir),
            "manifest_sha256": packet["manifest"]["manifest_sha256"],
            "selected_turns": packet["selected_turns"],
        }
        fusion_state["updated_at"] = now_iso()
        atomic_write_json(self._packet_state_path(), fusion_state)
        return packet_dir, packet

    def _execute_root_prompt_with_recovery(self, lineage_id: str, prompt: str) -> dict[str, Any]:
        while not self.stopped():
            result = self.execute_turn(spec=self.root_spec, prompt=prompt)
            if result["outcome"] != "FAILED":
                return result
            error_class = str(result.get("error_class", ""))
            parked_status = (
                f"ROOT_{error_class}"
                if error_class in {"BODY_INCIDENT", "EVIDENCE_INCIDENT"}
                else "ROOT_RUNTIME_PAUSED"
            )
            if not self._wait_parked(lineage_id, parked_status):
                return {"outcome": "STOPPED"}
        return {"outcome": "STOPPED"}

    def _run_root_wave(self, lineage_id: str, packet_dir: Path) -> dict[str, Any]:
        relative_packet = packet_dir.relative_to(
            resolve_path(self.root_spec["workspace"])
        ).as_posix()
        first_turn = not bool(self._lineage_states[lineage_id].get("session_id"))
        prompt = build_root_fusion_prompt(
            run_id=str(self.config["run_id"]),
            source_head=str(self.config["source_head"]),
            packet_relative_path=relative_packet,
            first_turn=first_turn,
        )
        result = self._execute_root_prompt_with_recovery(lineage_id, prompt)
        while result.get("outcome") == "COMPLETED" and result.get("lifecycle_state") == "CONTINUE":
            deadline = time.monotonic() + float(self.config["continuation_delay_seconds"])
            while not self.stopped() and time.monotonic() < deadline:
                self._shutdown.wait(min(1.0, deadline - time.monotonic()))
            if self.stopped():
                return {"outcome": "STOPPED"}
            result = self._execute_root_prompt_with_recovery(
                lineage_id, build_continuation_prompt(lineage_id=lineage_id)
            )
        return result

    def _finalize_fusion_wave(
        self,
        fusion_state: dict[str, Any],
        packet_dir: Path,
        packet: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        if result.get("outcome") != "COMPLETED" or result.get("lifecycle_state") == "CONTINUE":
            raise PerpetualRuntimeError("FUSION_WAVE_CANNOT_COMMIT_NONTERMINAL_RESULT")
        fusion_state["waves_completed"] = int(packet["manifest"]["wave_number"])
        fusion_state["consumed_turns"] = dict(packet["selected_turns"])
        fusion_state["last_packet"] = str(packet_dir)
        fusion_state["last_packet_manifest_sha256"] = packet["manifest"]["manifest_sha256"]
        fusion_state["pending_packet"] = None
        fusion_state["updated_at"] = now_iso()
        atomic_write_json(self._packet_state_path(), fusion_state)

    def fusion_loop(self) -> None:
        lineage_id = str(self.root_spec["lineage_id"])
        try:
            recovered_state = self._lineage_states[lineage_id]
            recovered_lifecycle = recovered_state.get("lifecycle_state")
            if (
                recovered_state.get("session_id")
                and recovered_lifecycle in PARKED_LIFECYCLE_STATES
                and not self._wait_parked(lineage_id, f"PARKED_{recovered_lifecycle}")
            ):
                return
            fusion_state = self._load_fusion_state()
            while not self.stopped():
                if not isinstance(fusion_state.get("pending_packet"), dict):
                    consumed = fusion_state["consumed_turns"]
                    with self._state_lock:
                        completed = {
                            str(spec["lineage_id"]): int(
                                self._lineage_states[str(spec["lineage_id"])]["turns_completed"]
                            )
                            for spec in self.branch_specs
                        }
                    ready = all(
                        completed[lineage_id_] > int(consumed.get(lineage_id_, 0))
                        for lineage_id_ in completed
                    )
                    if not ready:
                        self.publish_lineage_state(lineage_id, status="WAITING_FOR_BRANCH_WAVE")
                        self._shutdown.wait(5)
                        continue
                packet_dir, packet = self._load_or_create_pending_packet(fusion_state)
                result = self._run_root_wave(lineage_id, packet_dir)
                if result.get("outcome") == "STOPPED" or self.stopped():
                    break
                if result.get("outcome") != "COMPLETED":
                    raise PerpetualRuntimeError(
                        f"ROOT_WAVE_UNEXPECTED_OUTCOME: {result.get('outcome')}"
                    )
                self._finalize_fusion_wave(fusion_state, packet_dir, packet, result)
                lifecycle = str(result["lifecycle_state"])
                if lifecycle in PARKED_LIFECYCLE_STATES:
                    if not self._wait_parked(lineage_id, f"PARKED_{lifecycle}"):
                        break
                else:
                    self.publish_lineage_state(lineage_id, status="WAITING_FOR_BRANCH_WAVE")
        except BaseException:
            error = traceback.format_exc()
            with self._state_lock:
                self._thread_errors[lineage_id] = error
            self.publish_lineage_state(
                lineage_id,
                status="CONTROLLER_THREAD_FAILED",
                active_pid=None,
                last_error_class="CONTROLLER_THREAD_FAILED",
                last_error=error[-8000:],
            )

    def run(self) -> int:
        def request_shutdown(*_: object) -> None:
            self._shutdown.set()

        for signal_name in ("SIGINT", "SIGTERM"):
            if hasattr(signal, signal_name):
                signal.signal(getattr(signal, signal_name), request_shutdown)
        with exclusive_lock(self.run_dir / "controller.lock"):
            try:
                self.verify_runtime_identity()
                self.reject_live_orphaned_children()
                self.publish_controller_state("STARTING")
                threads = [
                    threading.Thread(
                        target=self.branch_loop,
                        args=(spec,),
                        name=f"branch-{spec['lineage_id']}",
                        daemon=False,
                    )
                    for spec in self.branch_specs
                ]
                threads.append(
                    threading.Thread(
                        target=self.fusion_loop,
                        name="root-late-fusion",
                        daemon=False,
                    )
                )
                for thread in threads:
                    thread.start()
                self.publish_controller_state("RUNNING")
                while not self.stopped():
                    if any(not thread.is_alive() for thread in threads):
                        dead = [thread.name for thread in threads if not thread.is_alive()]
                        with self._state_lock:
                            self._thread_errors.setdefault(
                                "controller", f"UNEXPECTED_THREAD_EXIT: {dead}"
                            )
                        break
                    self._shutdown.wait(5)
                self._shutdown.set()
                self.publish_controller_state("STOPPING")
                for thread in threads:
                    thread.join(timeout=90)
                active = dict(self._active_processes)
                if active:
                    self.publish_controller_state("STOP_INCOMPLETE_ACTIVE_CHILD")
                    return 3
                terminal = "STOPPED" if self.stop_path.exists() else "FAILED"
                self.publish_controller_state(terminal)
                return 0 if terminal == "STOPPED" else 2
            except BaseException:
                error = traceback.format_exc()
                with self._state_lock:
                    self._thread_errors["controller"] = error
                self.publish_controller_state("FAILED")
                raise


def prepare_cleanroom(launcher: Path, powershell: Path, account_slot: str) -> str:
    account_slot = validate_account_slot(account_slot)
    completed = run_checked(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            launcher,
            "-AccountSlot",
            account_slot,
            "-PrepareOnly",
        ],
        timeout=120,
    )
    if "CODEX_CLEANROOM_SHARED_RUNTIME_PREPARE_OK" not in completed.stdout:
        raise PerpetualRuntimeError("CLEANROOM_PREPARE_RECEIPT_MISSING")
    if f"credential_slot={account_slot}" not in completed.stdout:
        raise PerpetualRuntimeError("CLEANROOM_PREPARE_WRONG_ACCOUNT_SLOT")
    return completed.stdout


def current_pointer(runtime_root: Path) -> Path:
    return resolve_path(runtime_root) / "current.json"


def select_runtime_root(
    supplied: Path | None,
    *,
    require_current: bool,
    default_root: Path = DEFAULT_RUNTIME_ROOT,
    legacy_root: Path = LEGACY_RUNTIME_ROOT,
    dedicated_a_root: Path = DEDICATED_A_RUNTIME_ROOT,
) -> Path:
    if supplied is not None:
        return resolve_path(supplied)
    if not require_current:
        return resolve_path(default_root)
    candidates: list[Path] = []
    for root in (default_root, legacy_root, dedicated_a_root):
        resolved = resolve_path(root)
        if resolved not in candidates and current_pointer(resolved).is_file():
            candidates.append(resolved)
    if len(candidates) > 1:
        raise PerpetualRuntimeError(
            "MULTIPLE_CURRENT_RUNTIME_POINTERS_REQUIRE_EXPLICIT_ROOT: "
            + json.dumps([str(path) for path in candidates], ensure_ascii=False)
        )
    return candidates[0] if candidates else resolve_path(default_root)


def ensure_no_active_controller(runtime_root: Path) -> None:
    pointer = current_pointer(runtime_root)
    if not pointer.exists():
        return
    value = read_json_object(pointer)
    state_path = resolve_path(value.get("run_dir", "")) / "controller_state.json"
    state = read_json_object(state_path) if state_path.is_file() else None
    pid = state.get("pid") if state else value.get("controller_pid")
    if isinstance(pid, int) and is_process_alive(pid):
        raise PerpetualRuntimeError(
            f"ACTIVE_CONTROLLER_ALREADY_EXISTS: run_id={value.get('run_id')} pid={pid}"
        )


def validate_recovery_identity(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an existing run without requiring the caller to be its frozen release."""

    schema_family(config.get("schema"))
    account_slot = validate_recovery_account_slot(config, expected=None)
    run_dir = resolve_path(config["run_dir"])
    release_path = resolve_path(config["controller_release_path"])
    if not release_path.is_file():
        raise PerpetualRuntimeError(f"CONTROLLER_RELEASE_MISSING: {release_path}")
    observed_release_sha = sha256_file(release_path)
    if observed_release_sha != str(config["controller_release_sha256"]):
        raise PerpetualRuntimeError("CONTROLLER_RELEASE_BYTES_CHANGED")
    source = validate_pinned_source_commit(
        resolve_path(config["source_repo"]), str(config["source_head"])
    )
    launcher = resolve_path(config["launcher_path"])
    if not launcher.is_file() or sha256_file(launcher) != str(config["launcher_sha256"]):
        raise PerpetualRuntimeError("CLEANROOM_LAUNCHER_BYTES_CHANGED")
    validate_body_boundary_config(config)
    migration_identity = (
        _validate_existing_runtime_binding_identity(config)
        if config.get("runtime_binding_required") is True
        else None
    )
    shared_config = resolve_path(config["shared_config_path"])
    if not shared_config.is_file():
        raise PerpetualRuntimeError(f"CLEANROOM_SHARED_CONFIG_MISSING: {shared_config}")
    shared_identity = cleanroom_config_identity(shared_config)
    expected_semantic = str(
        config.get("shared_config_semantic_sha256", config["shared_config_sha256"])
    )
    if shared_identity["semantic_sha256"] != expected_semantic:
        raise PerpetualRuntimeError(
            "CLEANROOM_SHARED_CONFIG_SEMANTICS_CHANGED: "
            f"expected={expected_semantic} observed={shared_identity['semantic_sha256']}"
        )
    lineages = [
        validate_lineage_runtime_repo(resolve_path(spec["workspace"]), str(config["source_head"]))
        for spec in [*config["branch_lineages"], config["root_lineage"]]
    ]
    return {
        "run_dir": str(run_dir),
        "frozen_release_path": str(release_path),
        "frozen_release_sha256": observed_release_sha,
        "source": source,
        "shared_config": shared_identity,
        "lineages": lineages,
        "account_slot": account_slot,
        "runtime_binding_migration": migration_identity,
    }


def find_live_runtime_processes(
    pointer: Mapping[str, Any],
    state: Mapping[str, Any] | None,
    config: Mapping[str, Any],
) -> dict[str, int]:
    """Return every recorded controller/child PID that is still alive."""

    candidates: dict[str, int] = {}

    def remember(label: str, raw_pid: object) -> None:
        if isinstance(raw_pid, int) and raw_pid > 0:
            candidates[label] = raw_pid

    remember("pointer.controller", pointer.get("controller_pid"))
    if state:
        remember("state.controller", state.get("pid"))
        for lineage_id, raw_pid in dict(state.get("active_processes", {})).items():
            remember(f"state.child.{lineage_id}", raw_pid)
    run_dir = resolve_path(config["run_dir"])
    for spec in [*config["branch_lineages"], config["root_lineage"]]:
        lineage_id = str(spec["lineage_id"])
        state_path = run_dir / "lineages" / lineage_id / "state.json"
        if state_path.is_file():
            remember(f"lineage.child.{lineage_id}", read_json_object(state_path).get("active_pid"))
    for record in world_turn_quota_records_for_run(config):
        if record.get("status") == "BOUND":
            remember(f"quota.child.{record['lineage_id']}", record.get("child_pid"))
    return {label: pid for label, pid in candidates.items() if is_process_alive(pid)}


def prepare_reality_migration(args: argparse.Namespace) -> dict[str, Any]:
    """Create one copy-first migration for an exact stopped current run.

    This is deliberately an offline preparation surface.  It neither adopts the
    migration nor changes the run config, current pointer, STOP state, lineage
    state, or controller state.  Recovery remains the sole adoption seam.
    """

    runtime_root = select_runtime_root(args.runtime_root, require_current=True)
    pointer_path = current_pointer(runtime_root)
    pointer_before_raw = pointer_path.read_bytes()
    pointer_before_sha256 = sha256_bytes(pointer_before_raw)
    pointer = read_json_object(pointer_path)
    run_dir = resolve_path(pointer["run_dir"])
    config_path = run_dir / "run_config.json"
    if not config_path.is_file():
        raise PerpetualRuntimeError(f"RUN_CONFIG_MISSING: {config_path}")
    live_reality_root = resolve_path(args.live_reality_root)
    world_compute_base = resolve_path(args.world_compute_root)
    preparation_dir = run_dir / "reality-migration-preparation"
    receipt_path = preparation_dir / "receipt.json"

    with exclusive_lock(run_dir / "recovery.lock"):
        with exclusive_lock(run_dir / "controller.lock"):
            pointer, state = load_current(runtime_root)
            pointer_stable_raw = pointer_path.read_bytes()
            if (
                sha256_bytes(pointer_stable_raw) != pointer_before_sha256
                or pointer_stable_raw != pointer_before_raw
            ):
                raise PerpetualRuntimeError(
                    "REALITY_MIGRATION_CURRENT_POINTER_CHANGED_BEFORE_PREPARE"
                )
            config = read_json_object(config_path)
            _validate_recovery_pointer(
                pointer,
                state,
                config,
                run_dir,
                allow_stop_request=True,
            )
            account_slot = validate_recovery_account_slot(
                config, expected=getattr(args, "expected_account_slot", None)
            )
            live = find_live_runtime_processes(pointer, state, config)
            if live:
                raise PerpetualRuntimeError(
                    "REALITY_MIGRATION_REFUSED_LIVE_PROCESSES: "
                    + json.dumps(live, ensure_ascii=False, sort_keys=True)
                )
            unresolved_quota = [
                {
                    "path": record["path"],
                    "lineage_id": record["lineage_id"],
                    "status": record["status"],
                    "child_pid": record.get("child_pid"),
                }
                for record in world_turn_quota_records_for_run(config)
                if record.get("status") in {"RESERVED", "BOUND"}
            ]
            if unresolved_quota:
                raise PerpetualRuntimeError(
                    "REALITY_MIGRATION_REFUSED_UNRESOLVED_WORLD_TURN_QUOTA: "
                    + json.dumps(unresolved_quota, ensure_ascii=False, sort_keys=True)
                )
            source_repo = resolve_path(config["source_repo"])
            source = validate_pinned_source_commit(source_repo, str(config["source_head"]))
            all_specs = [*config["branch_lineages"], config["root_lineage"]]
            workspace_roots: dict[str, Path] = {}
            lineage_receipts: list[dict[str, str]] = []
            clone_root = resolve_path(config["clone_run_root"])
            for raw_spec in all_specs:
                spec = dict(raw_spec)
                lineage_id = str(spec["lineage_id"])
                if lineage_id in workspace_roots:
                    raise PerpetualRuntimeError(
                        f"REALITY_MIGRATION_DUPLICATE_LINEAGE_ID: {lineage_id}"
                    )
                workspace = resolve_path(spec["workspace"])
                if (
                    workspace.parent != clone_root
                    or workspace.name != lineage_id
                    or not workspace.is_relative_to(clone_root)
                ):
                    raise PerpetualRuntimeError(
                        f"REALITY_MIGRATION_LINEAGE_WORKSPACE_IDENTITY_INVALID: {lineage_id}"
                    )
                identity = validate_lineage_runtime_repo(workspace, str(config["source_head"]))
                workspace_roots[lineage_id] = workspace
                lineage_receipts.append({"lineage_id": lineage_id, **identity})
            compute_root = world_compute_base / str(config["run_id"])
            try:
                reality_module_path = Path(__file__).resolve().with_name("reality_migration.py")
                reality_spec = importlib.util.spec_from_file_location(
                    "xinao_prepare_reality_migration_" + sha256_file(reality_module_path).lower(),
                    reality_module_path,
                )
                if reality_spec is None or reality_spec.loader is None:
                    raise PerpetualRuntimeError("REALITY_MIGRATION_VALIDATOR_IMPORT_FAILED")
                reality_module = importlib.util.module_from_spec(reality_spec)
                reality_spec.loader.exec_module(reality_module)
                migration = reality_module.migrate_live_reality_copy_first(
                    source_repo,
                    live_reality_root=live_reality_root,
                    world_compute_root=compute_root,
                    workspace_roots=workspace_roots,
                    active_child_pids=live,
                )
            except Exception as exc:
                raise PerpetualRuntimeError(
                    f"REALITY_MIGRATION_PREPARATION_FAILED:{type(exc).__name__}"
                ) from exc
            pointer_after_raw = pointer_path.read_bytes()
            if pointer_after_raw != pointer_before_raw:
                raise PerpetualRuntimeError(
                    "REALITY_MIGRATION_CURRENT_POINTER_CHANGED_DURING_PREPARE"
                )
            receipt = {
                "schema": REALITY_MIGRATION_PREPARATION_SCHEMA,
                "status": "PREPARED_NOT_ADOPTED",
                "prepared_at": now_iso(),
                "runtime_root": str(runtime_root),
                "run_id": config["run_id"],
                "account_slot": account_slot,
                "pointer_path": str(pointer_path),
                "pointer_sha256": pointer_before_sha256,
                "run_config_path": str(config_path),
                "run_config_sha256": sha256_file(config_path),
                "source": source,
                "lineages": lineage_receipts,
                "live_reality_root": str(live_reality_root),
                "world_compute_root": str(compute_root),
                "migration_manifest_path": migration["manifest_path"],
                "migration_manifest_sha256": migration["manifest_sha256"],
                "migration_id": migration["migration_id"],
                "source_preserved": migration["source_preserved"],
                "run_config_changed": False,
                "current_pointer_changed": False,
                "controller_started": False,
            }
            atomic_write_json(receipt_path, receipt)
            return {**receipt, "preparation_receipt": str(receipt_path)}


def world_turn_quota_records_for_run(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read canonical account-quota records that belong to one exact run."""

    if "world_turn_concurrency_limit" not in config:
        return []
    limit = int(config["world_turn_concurrency_limit"])
    if limit < 1:
        raise PerpetualRuntimeError("WORLD_TURN_CONCURRENCY_LIMIT_MUST_BE_POSITIVE")
    account_slot = validate_account_slot(config["account_slot"])
    quota_root = resolve_path(config.get("world_turn_quota_root", DEFAULT_WORLD_TURN_QUOTA_ROOT))
    records: list[dict[str, Any]] = []
    for slot in range(1, limit + 1):
        path = quota_root / account_slot / f"world-turn-{slot:02d}.json"
        if not path.is_file():
            continue
        record = read_json_object(path)
        if (
            record.get("schema") != WORLD_TURN_QUOTA_LEASE_SCHEMA
            or record.get("account_slot") != account_slot
            or int(record.get("slot", -1)) != slot
        ):
            raise PerpetualRuntimeError(f"WORLD_TURN_QUOTA_RECORD_INVALID: {path}")
        if record.get("run_id") != config["run_id"]:
            continue
        status = str(record.get("status", ""))
        if status not in {"RESERVED", "BOUND", "RELEASED"}:
            raise PerpetualRuntimeError(f"WORLD_TURN_QUOTA_STATUS_INVALID: {path}")
        records.append({**record, "path": str(path)})
    return records


def _next_incomplete_fusion_packet(config: Mapping[str, Any]) -> Path | None:
    run_dir = resolve_path(config["run_dir"])
    root_spec = dict(config["root_lineage"])
    fusion_state_path = run_dir / "lineages" / str(root_spec["lineage_id"]) / "fusion_state.json"
    fusion_state = read_json_object(fusion_state_path) if fusion_state_path.is_file() else {}
    wave_number = int(fusion_state.get("waves_completed", 0)) + 1
    packet_dir = (
        resolve_path(root_spec["workspace"]) / "S_CONTROL_INPUTS" / f"wave-{wave_number:06d}"
    )
    if packet_dir.is_dir() and not (packet_dir / "PACKET_MANIFEST.json").is_file():
        return packet_dir
    return None


def _directory_inventory(root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix().lower()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            inventory.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            inventory.append(
                {
                    "path": relative,
                    "type": "file",
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        elif path.is_dir():
            inventory.append({"path": relative, "type": "directory"})
        else:
            inventory.append({"path": relative, "type": "other"})
    return inventory


def quarantine_incomplete_fusion_packet(
    config: Mapping[str, Any], *, recovery_id: str
) -> dict[str, Any] | None:
    """Move an uncommitted manifest-less packet aside without deleting its evidence."""

    packet_dir = _next_incomplete_fusion_packet(config)
    if packet_dir is None:
        return None
    run_dir = resolve_path(config["run_dir"])
    root_spec = dict(config["root_lineage"])
    fusion_state_path = run_dir / "lineages" / str(root_spec["lineage_id"]) / "fusion_state.json"
    fusion_state = read_json_object(fusion_state_path) if fusion_state_path.is_file() else {}
    pending = fusion_state.get("pending_packet")
    if isinstance(pending, dict) and resolve_path(pending.get("packet_dir", "")) == packet_dir:
        raise PerpetualRuntimeError(f"INCOMPLETE_PACKET_IS_PENDING_TRANSACTION: {packet_dir}")
    if fusion_state.get("last_packet") and resolve_path(fusion_state["last_packet"]) == packet_dir:
        raise PerpetualRuntimeError(
            f"INCOMPLETE_PACKET_ALREADY_RECORDED_AS_COMMITTED: {packet_dir}"
        )
    inventory = _directory_inventory(packet_dir)
    quarantine_root = resolve_path(root_spec["workspace"]) / "S_CONTROL_QUARANTINE"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    quarantine_path = quarantine_root / f"{recovery_id}-{packet_dir.name}-manifest-missing"
    if quarantine_path.exists():
        raise PerpetualRuntimeError(f"RECOVERY_QUARANTINE_ALREADY_EXISTS: {quarantine_path}")
    os.replace(packet_dir, quarantine_path)
    return {
        "reason": "PACKET_MANIFEST_MISSING",
        "source_path": str(packet_dir),
        "quarantine_path": str(quarantine_path),
        "inventory": inventory,
        "moved_at": now_iso(),
    }


def _spawn_detached_controller(
    *,
    controller_python: Path,
    controller_python_sha256: str,
    release_path: Path,
    config_path: Path,
    run_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.Popen[bytes], Path]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("ab", buffering=0)
    stderr_handle = stderr_path.open("ab", buffering=0)
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    )
    controller_python = resolve_path(controller_python)
    try:
        regular = controller_python.is_file() and _is_regular_non_reparse_file(controller_python)
    except OSError:
        regular = False
    if (
        not regular
        or sha256_file(controller_python).casefold() != str(controller_python_sha256).casefold()
    ):
        raise PerpetualRuntimeError("WORLD_BODY_CONTROLLER_PYTHON_CHANGED_BEFORE_SPAWN")
    try:
        process = subprocess.Popen(
            [
                str(controller_python),
                str(release_path),
                "run",
                "--config",
                str(config_path),
            ],
            cwd=run_dir,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            close_fds=True,
            shell=False,
            creationflags=creationflags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    return process, controller_python


def _wait_for_controller_startup(
    *,
    process: subprocess.Popen[bytes],
    run_dir: Path,
    expected_run_id: str,
    startup_wait_seconds: float,
    stderr_path: Path,
) -> dict[str, Any]:
    deadline = time.monotonic() + startup_wait_seconds
    state_path = run_dir / "controller_state.json"
    while time.monotonic() < deadline:
        state = read_startup_state(state_path)
        if state is not None:
            if state.get("run_id") == expected_run_id and state.get("pid") == process.pid:
                if state.get("status") in {"STARTING", "RUNNING"}:
                    return state
                if state.get("status") == "FAILED":
                    raise PerpetualRuntimeError(
                        f"CONTROLLER_FAILED_DURING_RECOVERY: {safe_tail(stderr_path)}"
                    )
        if process.poll() is not None:
            raise PerpetualRuntimeError(
                "CONTROLLER_EXITED_DURING_RECOVERY: "
                f"exit={process.returncode} stderr={safe_tail(stderr_path)}"
            )
        time.sleep(0.25)
    raise PerpetualRuntimeError(
        f"CONTROLLER_RECOVERY_READBACK_TIMEOUT: pid={process.pid} run={expected_run_id}"
    )


def make_run_id(head: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"world-compute-{stamp}-{head[:8]}"


def start_runtime(args: argparse.Namespace) -> dict[str, Any]:
    if os.name != "nt":
        raise PerpetualRuntimeError("WINDOWS_RUNTIME_REQUIRED")
    source_repo = resolve_path(args.source_repo)
    launcher = resolve_path(args.launcher)
    powershell = resolve_path(args.powershell)
    runtime_root = select_runtime_root(args.runtime_root, require_current=False)
    clone_root = resolve_path(args.clone_root)
    account_slot = validate_account_slot(args.account_slot)
    if not launcher.is_file():
        raise PerpetualRuntimeError(f"CLEANROOM_LAUNCHER_MISSING: {launcher}")
    if not powershell.is_file():
        raise PerpetualRuntimeError(f"WINDOWS_POWERSHELL_MISSING: {powershell}")
    shared_config = launcher.parent / "codex-home" / "config.toml"
    if not shared_config.is_file():
        raise PerpetualRuntimeError(f"CLEANROOM_SHARED_CONFIG_MISSING: {shared_config}")
    shared_config_identity = cleanroom_config_identity(shared_config)
    roots_to_check = (
        [runtime_root]
        if args.runtime_root is not None
        else sorted(
            {
                resolve_path(DEFAULT_RUNTIME_ROOT),
                resolve_path(LEGACY_RUNTIME_ROOT),
                resolve_path(DEDICATED_A_RUNTIME_ROOT),
            },
            key=str,
        )
    )
    for candidate_root in roots_to_check:
        ensure_no_active_controller(candidate_root)
    prepare_receipt = prepare_cleanroom(launcher, powershell, account_slot)
    source = validate_source_repo(source_repo)
    run_id = args.run_id or make_run_id(source["head"])
    run_dir = runtime_root / "runs" / run_id
    clone_run_root = clone_root / run_id
    if run_dir.exists() or clone_run_root.exists():
        raise PerpetualRuntimeError(f"RUN_ID_ALREADY_EXISTS: {run_id}")
    run_dir.mkdir(parents=True)
    clone_run_root.mkdir(parents=True)
    atomic_write_text(run_dir / "cleanroom_prepare_receipt.txt", prepare_receipt)
    source_file = Path(__file__).resolve()
    release_path = run_dir / "controller_release.py"
    shutil.copyfile(source_file, release_path)
    world_launcher_path = run_dir / "Open-Codex-World-Isolated.ps1"
    branch_specs: list[dict[str, Any]] = []
    setup_receipts: list[dict[str, Any]] = []
    for index in range(1, int(args.width) + 1):
        lineage_id = f"world-{index:02d}"
        workspace = clone_run_root / lineage_id
        clone_receipt = clone_isolated_repo(source_repo, workspace, source["head"])
        spec = {"lineage_id": lineage_id, "role": "independent_world", **clone_receipt}
        branch_specs.append(spec)
        lineage_dir = run_dir / "lineages" / lineage_id
        lineage_dir.mkdir(parents=True)
        prompt = build_branch_initial_prompt(
            lineage_id=lineage_id, run_id=run_id, source_head=source["head"]
        )
        atomic_write_text(lineage_dir / "initial_prompt.txt", prompt)
        setup_receipts.append(spec)
    root_id = "root-main"
    root_workspace = clone_run_root / root_id
    root_clone_receipt = clone_isolated_repo(source_repo, root_workspace, source["head"])
    root_spec = {"lineage_id": root_id, "role": "late_fusion_root", **root_clone_receipt}
    (run_dir / "lineages" / root_id).mkdir(parents=True)
    setup_receipts.append(root_spec)
    source_after = validate_source_repo(source_repo)
    if source_after != source:
        raise PerpetualRuntimeError(
            f"SOURCE_REPO_CHANGED_DURING_CLONE: before={source} after={source_after}"
        )
    controller_python = Path(str(getattr(sys, "_base_executable", sys.executable))).resolve(
        strict=False
    )
    reality_module_path = source_file.with_name("reality_migration.py")
    runtime_binding_source = source_file.with_name("runtime_binding.py")
    if not reality_module_path.is_file() or not runtime_binding_source.is_file():
        raise PerpetualRuntimeError("XINAO_RUNTIME_MIGRATION_COMPONENT_MISSING")
    reality_spec = importlib.util.spec_from_file_location(
        f"xinao_start_reality_migration_{sha256_file(reality_module_path).lower()}",
        reality_module_path,
    )
    if reality_spec is None or reality_spec.loader is None:
        raise PerpetualRuntimeError("REALITY_MIGRATION_VALIDATOR_IMPORT_FAILED")
    reality_module = importlib.util.module_from_spec(reality_spec)
    reality_spec.loader.exec_module(reality_module)
    live_reality_root = resolve_path(args.live_reality_root)
    world_compute_root = resolve_path(args.world_compute_root) / run_id
    try:
        migration_result = reality_module.migrate_live_reality_copy_first(
            source_repo,
            live_reality_root=live_reality_root,
            world_compute_root=world_compute_root,
            workspace_roots={
                str(spec["lineage_id"]): resolve_path(spec["workspace"])
                for spec in [*branch_specs, root_spec]
            },
            active_child_pids=(),
        )
    except Exception as exc:
        raise PerpetualRuntimeError(
            f"REALITY_MIGRATION_FOR_NEW_RUN_FAILED:{type(exc).__name__}"
        ) from exc
    world_launcher = create_world_isolated_launcher(
        launcher,
        world_launcher_path,
        require_runtime_binding=True,
    )
    runtime_binding_release_path = run_dir / "runtime_binding_release.py"
    runtime_binding_release_sha256 = atomic_write_bytes(
        runtime_binding_release_path,
        runtime_binding_source.read_bytes(),
    )
    config = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "created_at": now_iso(),
        "run_dir": str(run_dir),
        "clone_run_root": str(clone_run_root),
        "source_repo": str(source_repo),
        "source_head": source["head"],
        "source_branch": source["branch"],
        "source_status_sha256": source["status_sha256"],
        "launcher_path": str(world_launcher_path),
        "launcher_sha256": world_launcher["sha256"],
        "launcher_source_path": str(launcher),
        "launcher_source_sha256": world_launcher["source_sha256"],
        "shared_config_path": str(shared_config.resolve(strict=False)),
        "shared_config_sha256": shared_config_identity["raw_sha256"],
        "shared_config_semantic_sha256": shared_config_identity["semantic_sha256"],
        "shared_config_dynamic_lineage_projects": shared_config_identity[
            "dynamic_lineage_project_paths"
        ],
        "powershell_path": str(powershell),
        "controller_python": str(controller_python),
        "controller_python_sha256": sha256_file(controller_python),
        "account_slot": account_slot,
        "model": str(args.model),
        "model_reasoning_effort": str(args.model_reasoning_effort),
        "branch_width": int(args.width),
        "branch_lineages": branch_specs,
        "root_lineage": root_spec,
        "watchdog_seconds": int(args.watchdog_seconds),
        "continuation_delay_seconds": int(args.continuation_delay_seconds),
        "retry_delays_seconds": [int(value) for value in args.retry_delays_seconds],
        "park_poll_seconds": int(args.park_poll_seconds),
        "controller_release_path": str(release_path),
        "controller_release_sha256": sha256_file(release_path),
        "deep_evidence_required": True,
        "deep_evidence_required_from_turn": {
            str(spec["lineage_id"]): 1 for spec in [*branch_specs, root_spec]
        },
        "runtime_binding_required": True,
        "runtime_binding_required_from_turn": {
            str(spec["lineage_id"]): 1 for spec in [*branch_specs, root_spec]
        },
        "runtime_binding_release_path": str(runtime_binding_release_path),
        "runtime_binding_release_sha256": runtime_binding_release_sha256,
        "reality_migration_manifest_path": migration_result["manifest_path"],
        "reality_migration_manifest_sha256": migration_result["manifest_sha256"],
        "reality_migration_id": migration_result["migration_id"],
        "world_turn_concurrency_limit": DEFAULT_WORLD_TURN_CONCURRENCY_LIMIT,
        "world_turn_quota_root": str(DEFAULT_WORLD_TURN_QUOTA_ROOT),
        "body_boundary": {
            "schema": WORLD_ISOLATED_LAUNCHER_SCHEMA,
            "sandbox_mode": "workspace-write",
            "approval_policy": "never",
            "network_access": True,
            "writable_scope": "current_lineage_workspace_only",
            "additional_writable_roots": [],
            "s_repo_writable": False,
            "cleanroom_shared_body_writable": False,
            "account_config_writable": False,
            "body_incident_schema": BODY_INCIDENT_SCHEMA,
        },
        "effect_contract": {
            "branch_workspaces_are_candidate_only": True,
            "shared_repo_writes_allowed": False,
            "external_capital_or_publication_allowed": False,
            "s_content_steering_allowed": False,
            "late_fusion_owner": "root-main",
            "turn_end_closes_parent": False,
        },
    }
    migration_adoption = _compile_runtime_binding_views(
        config=config,
        manifest_path=resolve_path(migration_result["manifest_path"]),
    )
    config["runtime_binding_views"] = migration_adoption["views"]
    config_path = run_dir / "run_config.json"
    atomic_write_json(config_path, config)
    atomic_write_json(run_dir / "clone_setup_receipts.json", setup_receipts)
    controller_python = _validated_controller_python(config)
    process, controller_python = _spawn_detached_controller(
        controller_python=controller_python,
        controller_python_sha256=str(config["controller_python_sha256"]),
        release_path=release_path,
        config_path=config_path,
        run_dir=run_dir,
        stdout_path=run_dir / "controller_stdout.txt",
        stderr_path=run_dir / "controller_stderr.txt",
    )
    pointer_payload = {
        "schema": RUN_SCHEMA,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "clone_run_root": str(clone_run_root),
        "controller_pid": process.pid,
        "controller_python": str(controller_python),
        "source_head": source["head"],
        "account_slot": account_slot,
        "started_at": now_iso(),
    }
    atomic_write_json(current_pointer(runtime_root), pointer_payload)
    deadline = time.monotonic() + float(args.startup_wait_seconds)
    controller_state_path = run_dir / "controller_state.json"
    while time.monotonic() < deadline:
        state = read_startup_state(controller_state_path)
        if state is not None:
            if state.get("status") in {"STARTING", "RUNNING"}:
                observed_pid = state.get("pid")
                if isinstance(observed_pid, int) and observed_pid > 0:
                    pointer_payload["controller_pid"] = observed_pid
                    pointer_payload["launcher_pid"] = process.pid
                    atomic_write_json(current_pointer(runtime_root), pointer_payload)
                return {**pointer_payload, "controller_state": state}
            if state.get("status") == "FAILED":
                raise PerpetualRuntimeError(
                    f"CONTROLLER_FAILED_DURING_START: {safe_tail(run_dir / 'controller_stderr.txt')}"
                )
        if process.poll() is not None:
            raise PerpetualRuntimeError(
                "CONTROLLER_EXITED_DURING_START: "
                f"exit={process.returncode} stderr={safe_tail(run_dir / 'controller_stderr.txt')}"
            )
        time.sleep(0.25)
    raise PerpetualRuntimeError(
        f"CONTROLLER_STARTUP_READBACK_TIMEOUT: pid={process.pid} run={run_id}"
    )


def load_current(runtime_root: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    pointer_path = current_pointer(runtime_root)
    if not pointer_path.exists():
        raise PerpetualRuntimeError(f"NO_CURRENT_RUNTIME: {pointer_path}")
    pointer = read_json_object(pointer_path)
    run_dir = resolve_path(pointer["run_dir"])
    state_path = run_dir / "controller_state.json"
    state = read_json_object(state_path) if state_path.exists() else None
    return pointer, state


def _validate_recovery_pointer(
    pointer: Mapping[str, Any],
    state: Mapping[str, Any] | None,
    config: Mapping[str, Any],
    run_dir: Path,
    *,
    allow_stop_request: bool = False,
) -> None:
    run_id = str(config.get("run_id", ""))
    if not run_id or pointer.get("run_id") != run_id:
        raise PerpetualRuntimeError("RECOVERY_POINTER_RUN_ID_MISMATCH")
    if resolve_path(pointer.get("run_dir", "")) != run_dir:
        raise PerpetualRuntimeError("RECOVERY_POINTER_RUN_DIR_MISMATCH")
    if resolve_path(config.get("run_dir", "")) != run_dir:
        raise PerpetualRuntimeError("RECOVERY_CONFIG_RUN_DIR_MISMATCH")
    frozen_slot = validate_recovery_account_slot(config, expected=None)
    pointer_slot = pointer.get("account_slot")
    if pointer_slot is not None and validate_account_slot(pointer_slot) != frozen_slot:
        raise PerpetualRuntimeError("RECOVERY_POINTER_ACCOUNT_SLOT_MISMATCH")
    if state and state.get("run_id") != run_id:
        raise PerpetualRuntimeError("RECOVERY_CONTROLLER_STATE_RUN_ID_MISMATCH")
    state_slot = state.get("account_slot") if state else None
    if state_slot is not None and validate_account_slot(state_slot) != frozen_slot:
        raise PerpetualRuntimeError("RECOVERY_CONTROLLER_STATE_ACCOUNT_SLOT_MISMATCH")
    if (run_dir / "STOP.json").exists() and not allow_stop_request:
        raise PerpetualRuntimeError("RECOVERY_REFUSED_AFTER_STOP_REQUEST")


def _summarize_attempt_events(stdout_path: Path) -> dict[str, Any]:
    thread_id: str | None = None
    terminal_events: list[str] = []
    usage: object = None
    response_item_count = 0
    tool_item_count = 0
    with stdout_path.open("rb") as stream:
        for raw_line in stream:
            event = parse_event_line(raw_line)
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", ""))
            if event_type == "thread.started" and event.get("thread_id"):
                thread_id = str(event["thread_id"])
            if event_type in {"turn.completed", "turn.failed", "turn.cancelled"}:
                terminal_events.append(event_type)
                usage = event.get("usage")
            item = event.get("item")
            if isinstance(item, dict):
                response_item_count += 1
                if str(item.get("type", "")) in {
                    "command_execution",
                    "file_change",
                    "mcp_tool_call",
                    "web_search",
                }:
                    tool_item_count += 1
    return {
        "thread_id": thread_id,
        "terminal_events": terminal_events,
        "usage": usage,
        "response_item_count": response_item_count,
        "tool_item_count": tool_item_count,
    }


def _turn_requires_deep_evidence(
    config: Mapping[str, Any], *, lineage_id: str, turn_number: int
) -> bool:
    if config.get("deep_evidence_required") is not True:
        return False
    required_from = config.get("deep_evidence_required_from_turn")
    lineage_required_from = (
        required_from.get(lineage_id) if isinstance(required_from, Mapping) else None
    )
    return lineage_required_from is None or turn_number >= int(lineage_required_from)


def _validate_required_deep_evidence(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    attempt_dir: Path,
    turn_number: int,
    attempt_number: int,
    receipt: Mapping[str, Any],
) -> None:
    """Prove that an AVAILABLE receipt still resolves to its exact durable evidence."""

    deep = receipt.get("deep_evidence")
    if not isinstance(deep, Mapping) or deep.get("status") != "AVAILABLE":
        raise PerpetualRuntimeError(
            f"RECOVERY_TURN_RECEIPT_REQUIRED_EVIDENCE_MISSING: {attempt_dir / 'receipt.json'}"
        )
    trajectory = deep.get("trajectory")
    artifacts = deep.get("artifacts")
    if not isinstance(trajectory, Mapping) or not isinstance(artifacts, Mapping):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_EVIDENCE_REFERENCE_MISSING")

    raw_value = trajectory.get("raw_path")
    index_value = trajectory.get("path")
    if not isinstance(raw_value, str) or not isinstance(index_value, str):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_PATH_MISSING")
    raw_path = _require_contained_path(
        Path(raw_value), attempt_dir, "RECOVERY_REQUIRED_TRAJECTORY_OUTSIDE_ATTEMPT"
    )
    index_path = _require_contained_path(
        Path(index_value), attempt_dir, "RECOVERY_REQUIRED_INDEX_OUTSIDE_ATTEMPT"
    )
    if raw_path != resolve_path(attempt_dir / "exec_stdout.jsonl"):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_RAW_IDENTITY_MISMATCH")
    if index_path != resolve_path(attempt_dir / "trajectory_index.jsonl"):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_INDEX_IDENTITY_MISMATCH")
    if not raw_path.is_file() or not index_path.is_file():
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_FILE_MISSING")
    if not _is_regular_non_reparse_file(raw_path) or not _is_regular_non_reparse_file(index_path):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_FILE_INVALID")
    if (
        trajectory.get("raw_sha256") != sha256_file(raw_path)
        or trajectory.get("sha256") != sha256_file(index_path)
        or trajectory.get("raw_bytes") != raw_path.stat().st_size
    ):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_HASH_MISMATCH")

    event_count = 0
    byte_offset = 0
    with raw_path.open("rb") as raw_stream, index_path.open("rb") as index_stream:
        for event_count, raw_line in enumerate(raw_stream, 1):
            index_line = index_stream.readline()
            if not index_line:
                raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_INDEX_TRUNCATED")
            try:
                row = json.loads(index_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_INDEX_INVALID") from exc
            event = parse_event_line(raw_line)
            item = event.get("item") if isinstance(event, dict) else None
            item = item if isinstance(item, dict) else {}
            expected_index_fields = {
                "schema": DEEP_EVIDENCE_TRAJECTORY_INDEX_SCHEMA,
                "sequence": event_count,
                "byte_offset": byte_offset,
                "byte_length": len(raw_line),
                "line_sha256": sha256_bytes(raw_line),
                "event_type": event.get("type") if isinstance(event, dict) else "UNPARSED",
                "item_type": item.get("type"),
                "item_id": item.get("id"),
                "status": item.get("status"),
                "exit_code": item.get("exit_code"),
            }
            if (
                not isinstance(row, dict)
                or any(row.get(key) != value for key, value in expected_index_fields.items())
                or (row.get("schema") != DEEP_EVIDENCE_TRAJECTORY_INDEX_SCHEMA)
            ):
                raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_INDEX_MISMATCH")
            byte_offset += len(raw_line)
        if index_stream.readline():
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_INDEX_HAS_EXTRAS")
    if trajectory.get("event_count") != event_count or byte_offset != raw_path.stat().st_size:
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_TRAJECTORY_COVERAGE_MISMATCH")

    manifest_value = artifacts.get("path")
    if not isinstance(manifest_value, str):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_MANIFEST_PATH_MISSING")
    manifest_path = _require_contained_path(
        Path(manifest_value), attempt_dir, "RECOVERY_REQUIRED_MANIFEST_OUTSIDE_ATTEMPT"
    )
    if manifest_path != resolve_path(attempt_dir / "artifact_manifest.json"):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_MANIFEST_IDENTITY_MISMATCH")
    if not manifest_path.is_file() or not _is_regular_non_reparse_file(manifest_path):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_MANIFEST_MISSING")
    if artifacts.get("sha256") != sha256_file(manifest_path):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_MANIFEST_HASH_MISMATCH")
    manifest = read_json_object(manifest_path)
    expected_identity = {
        "schema": DEEP_EVIDENCE_ARTIFACT_MANIFEST_SCHEMA,
        "run_id": config["run_id"],
        "lineage_id": spec["lineage_id"],
        "turn_number": turn_number,
        "attempt_number": attempt_number,
        "source_workspace": str(resolve_path(spec["workspace"])),
        "source_head": config["source_head"],
        "complete": True,
        "safety_block_count": 0,
    }
    if any(manifest.get(key) != value for key, value in expected_identity.items()):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_MANIFEST_IDENTITY_MISMATCH")
    entries = manifest.get("entries")
    exclusions = manifest.get("exclusions")
    gaps = manifest.get("gaps")
    if not isinstance(entries, list) or not isinstance(exclusions, list) or gaps != []:
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_MANIFEST_INCOMPLETE")
    expected_counts = {
        "entry_count": len(entries),
        "exclusion_count": len(exclusions),
        "gap_count": 0,
        "safety_block_count": 0,
        "complete": True,
    }
    if any(artifacts.get(key) != value for key, value in expected_counts.items()):
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_RECEIPT_MISMATCH")

    blob_root_value = manifest.get("content_addressed_blob_root")
    receipt_blob_root = artifacts.get("blob_root")
    if not isinstance(blob_root_value, str) or receipt_blob_root != blob_root_value:
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_BLOB_ROOT_MISMATCH")
    expected_blob_root = resolve_path(config["run_dir"]) / "deep-evidence" / "blobs" / "sha256"
    blob_root = resolve_path(blob_root_value)
    if blob_root != expected_blob_root:
        raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_BLOB_ROOT_INVALID")
    observed_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("relative_path"), str):
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_ENTRY_INVALID")
        relative = _safe_workspace_relative_path(str(entry["relative_path"]))
        relative_key = relative.as_posix().lower()
        if relative_key in observed_paths:
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_ENTRY_DUPLICATE")
        observed_paths.add(relative_key)
        if entry.get("state") == "DELETED":
            continue
        if entry.get("state") != "PRESENT":
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_ENTRY_STATE_INVALID")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        blob_value = entry.get("blob_path")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9A-F]{64}", digest) is None
            or not isinstance(size, int)
            or size < 0
            or not isinstance(blob_value, str)
        ):
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_ENTRY_IDENTITY_MISSING")
        blob_path = _require_contained_path(
            Path(blob_value), blob_root, "RECOVERY_REQUIRED_ARTIFACT_BLOB_OUTSIDE_STORE"
        )
        if blob_path != blob_root / digest[:2] / digest:
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_BLOB_PATH_MISMATCH")
        if (
            not blob_path.is_file()
            or not _is_regular_non_reparse_file(blob_path)
            or blob_path.stat().st_size != size
            or sha256_file(blob_path) != digest
        ):
            raise PerpetualRuntimeError("RECOVERY_REQUIRED_ARTIFACT_BLOB_DRIFT")


def _attempt_recovery_source_identity(
    attempt_dir: Path,
    *,
    event_summary: Mapping[str, Any],
    lifecycle: str | None,
    body_incidents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for name in ("prompt.txt", "exec_stdout.jsonl", "exec_stderr.txt", "last_message.txt"):
        path = attempt_dir / name
        files[name] = (
            {"bytes": path.stat().st_size, "sha256": sha256_file(path)} if path.is_file() else None
        )
    stdout_path = attempt_dir / "exec_stdout.jsonl"
    stdout_ends_newline = False
    if stdout_path.is_file() and stdout_path.stat().st_size:
        with stdout_path.open("rb") as stream:
            stream.seek(-1, os.SEEK_END)
            stdout_ends_newline = stream.read(1) == b"\n"
    return {
        "files": files,
        "thread_id": event_summary.get("thread_id"),
        "terminal_events": list(event_summary.get("terminal_events", [])),
        "lifecycle_state": lifecycle,
        "stdout_ends_newline": stdout_ends_newline,
        "body_incident_count": len(body_incidents),
        "body_incidents_sha256": sha256_bytes(canonical_json_bytes(list(body_incidents))),
    }


def _normalized_recovery_state_commits(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Return append-only seals, importing the immediately preceding scalar format once."""

    lineage_id = str(spec["lineage_id"])
    raw_commits = state.get("recovery_state_commits", [])
    if not isinstance(raw_commits, list):
        raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_LEDGER_INVALID: {lineage_id}")
    commits = [dict(item) if isinstance(item, Mapping) else item for item in raw_commits]
    scalar_fields = {
        "receipt_path": "recovery_state_commit_receipt_path",
        "receipt_sha256": "recovery_state_commit_receipt_sha256",
        "disposition": "recovery_state_commit_disposition",
        "turn_number": "recovery_state_commit_turn_number",
        "attempt_number": "recovery_state_commit_attempt_number",
    }
    present = {name: key in state for name, key in scalar_fields.items()}
    if any(present.values()):
        if not all(present.values()):
            raise PerpetualRuntimeError(
                f"RECOVERY_STATE_COMMIT_LEGACY_SEAL_INCOMPLETE: {lineage_id}"
            )
        scalar_seal = {
            "schema": RECOVERY_STATE_COMMIT_SCHEMA,
            "run_id": config["run_id"],
            "lineage_id": lineage_id,
            **{name: state[key] for name, key in scalar_fields.items()},
        }
        matches = [item for item in commits if item == scalar_seal]
        if commits and len(matches) != 1:
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_LEGACY_SEAL_DIVERGED: {lineage_id}")
        if not commits:
            commits = [scalar_seal]
            return commits, True
    return commits, False


def _validate_recovered_receipt_sources(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    state_path: Path,
    state: Mapping[str, Any],
) -> None:
    lineage_id = str(spec["lineage_id"])
    sealed_commits, legacy_migration_required = _normalized_recovery_state_commits(
        config=config,
        spec=spec,
        state=state,
    )
    observed_commit_ids: set[tuple[int, int]] = set()
    for sealed in sealed_commits:
        if not isinstance(sealed, Mapping):
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_SEAL_INVALID: {lineage_id}")
        expected_identity = {
            "schema": RECOVERY_STATE_COMMIT_SCHEMA,
            "run_id": config["run_id"],
            "lineage_id": lineage_id,
        }
        if any(sealed.get(key) != value for key, value in expected_identity.items()):
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_IDENTITY_MISMATCH: {lineage_id}")
        try:
            sealed_turn = int(sealed["turn_number"])
            sealed_attempt = int(sealed["attempt_number"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PerpetualRuntimeError(
                f"RECOVERY_STATE_COMMIT_ATTEMPT_IDENTITY_MISSING: {lineage_id}"
            ) from exc
        commit_id = (sealed_turn, sealed_attempt)
        if commit_id in observed_commit_ids:
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_DUPLICATE: {lineage_id}")
        observed_commit_ids.add(commit_id)
        receipt_value = sealed.get("receipt_path")
        if not isinstance(receipt_value, str):
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_RECEIPT_PATH_MISSING: {lineage_id}")
        expected_attempt_dir = (
            resolve_path(config["run_dir"])
            / "lineages"
            / lineage_id
            / "turns"
            / f"turn-{sealed_turn:06d}"
            / f"attempt-{sealed_attempt:02d}"
        )
        receipt_path = _require_contained_path(
            Path(receipt_value),
            expected_attempt_dir,
            "RECOVERY_STATE_COMMIT_RECEIPT_OUTSIDE_ATTEMPT",
        )
        if receipt_path != expected_attempt_dir / "receipt.json" or not receipt_path.is_file():
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_RECEIPT_MISSING: {lineage_id}")
        if sha256_file(receipt_path) != sealed.get("receipt_sha256"):
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_RECEIPT_DRIFT: {lineage_id}")
        _, verified = _validate_attempt_receipt_sources(
            config=config,
            spec=spec,
            state=state,
            attempt_dir=expected_attempt_dir,
            turn_number=sealed_turn,
        )
        if verified["disposition"] != sealed.get("disposition"):
            raise PerpetualRuntimeError(f"RECOVERY_STATE_COMMIT_DISPOSITION_DRIFT: {lineage_id}")

    turn_number = int(state.get("turns_completed", 0))
    if turn_number >= 1:
        turn_dir = (
            resolve_path(config["run_dir"])
            / "lineages"
            / lineage_id
            / "turns"
            / f"turn-{turn_number:06d}"
        )
        for attempt_dir in sorted(turn_dir.glob("attempt-*"), reverse=True):
            receipt_path = attempt_dir / "receipt.json"
            if not receipt_path.is_file():
                continue
            receipt = read_json_object(receipt_path)
            if receipt.get("recovered_from_incomplete_attempt") is not True:
                continue
            expected = {
                "prompt.txt": receipt.get("prompt_sha256"),
                "exec_stdout.jsonl": receipt.get("stdout_sha256"),
                "exec_stderr.txt": receipt.get("stderr_sha256"),
                "last_message.txt": receipt.get("last_message_sha256"),
            }
            for name, expected_sha256 in expected.items():
                path = attempt_dir / name
                if (
                    not isinstance(expected_sha256, str)
                    or not path.is_file()
                    or sha256_file(path) != expected_sha256
                ):
                    raise PerpetualRuntimeError(
                        f"RECOVERED_ATTEMPT_SOURCE_DRIFT: {lineage_id} {turn_number} {name}"
                    )
            break
    if legacy_migration_required:
        if not isinstance(state, dict):
            raise PerpetualRuntimeError(
                f"RECOVERY_STATE_COMMIT_LEGACY_SEAL_NOT_MUTABLE: {lineage_id}"
            )
        state["recovery_state_commits"] = sealed_commits
        atomic_write_json(state_path, state)


def _validate_attempt_receipt_sources(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    state: Mapping[str, Any],
    attempt_dir: Path,
    turn_number: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_path = attempt_dir / "receipt.json"
    receipt = read_json_object(receipt_path)
    attempt_match = re.fullmatch(r"attempt-(\d+)", attempt_dir.name)
    if attempt_match is None:
        raise PerpetualRuntimeError(f"RECOVERY_ATTEMPT_NAME_INVALID: {attempt_dir}")
    attempt_number = int(attempt_match.group(1))
    family = schema_family(config["schema"])
    if (
        receipt.get("schema") != family["turn"]
        or receipt.get("run_id") != config["run_id"]
        or receipt.get("lineage_id") != spec["lineage_id"]
        or int(receipt.get("turn_number", -1)) != turn_number
        or int(receipt.get("attempt_number", -1)) != attempt_number
    ):
        raise PerpetualRuntimeError(f"RECOVERY_TURN_RECEIPT_IDENTITY_MISMATCH: {receipt_path}")
    file_hash_fields = {
        "prompt.txt": "prompt_sha256",
        "exec_stdout.jsonl": "stdout_sha256",
        "exec_stderr.txt": "stderr_sha256",
        "last_message.txt": "last_message_sha256",
    }
    for name, field in file_hash_fields.items():
        path = attempt_dir / name
        expected = receipt.get(field)
        if isinstance(expected, str):
            if not path.is_file() or sha256_file(path) != expected:
                raise PerpetualRuntimeError(f"RECOVERY_TURN_RECEIPT_SOURCE_HASH_MISMATCH: {path}")
        elif expected is not None or (name != "last_message.txt" and not path.is_file()):
            raise PerpetualRuntimeError(f"RECOVERY_TURN_RECEIPT_SOURCE_IDENTITY_MISSING: {path}")
    stdout_path = attempt_dir / "exec_stdout.jsonl"
    event_summary = _summarize_attempt_events(stdout_path)
    if (
        event_summary.get("terminal_events")
        and receipt.get("turn_status") != event_summary["terminal_events"][-1]
    ):
        raise PerpetualRuntimeError(f"RECOVERY_TURN_RECEIPT_TERMINAL_MISMATCH: {receipt_path}")
    message_path = attempt_dir / "last_message.txt"
    lifecycle = (
        parse_lifecycle_state(message_path.read_text(encoding="utf-8", errors="replace"))
        if message_path.is_file()
        else None
    )
    if receipt.get("lifecycle_state") != lifecycle:
        raise PerpetualRuntimeError(f"RECOVERY_TURN_RECEIPT_LIFECYCLE_MISMATCH: {receipt_path}")
    body_incidents = classify_body_incident_events(
        stdout_path,
        workspace=resolve_path(spec["workspace"]),
    )
    receipt_error = receipt.get("error_class")
    if bool(body_incidents) != (receipt_error == "BODY_INCIDENT"):
        raise PerpetualRuntimeError(f"RECOVERY_TURN_RECEIPT_BODY_CLASS_MISMATCH: {receipt_path}")
    normal_success = (
        receipt_error is None
        and receipt.get("turn_status") == "turn.completed"
        and receipt.get("exit_code") == 0
    )
    recovered_success = (
        receipt_error is None
        and receipt.get("recovered_from_incomplete_attempt") is True
        and receipt.get("process_exit_code_observed") is False
        and receipt.get("exit_code") is None
        and receipt.get("inferred_process_success") is True
        and receipt.get("completion_basis") == "RECOVERED_TURN_COMPLETED_EVENT_AND_LIFECYCLE"
        and receipt.get("turn_status") == "turn.completed"
    )
    if normal_success or recovered_success:
        if lifecycle is None:
            raise PerpetualRuntimeError(
                f"RECOVERY_TURN_RECEIPT_SUCCESS_WITHOUT_LIFECYCLE: {receipt_path}"
            )
        if _turn_requires_deep_evidence(
            config,
            lineage_id=str(spec["lineage_id"]),
            turn_number=turn_number,
        ):
            _validate_required_deep_evidence(
                config=config,
                spec=spec,
                attempt_dir=attempt_dir,
                turn_number=turn_number,
                attempt_number=attempt_number,
                receipt=receipt,
            )
        if _turn_requires_runtime_binding(
            config,
            lineage_id=str(spec["lineage_id"]),
            turn_number=turn_number,
        ):
            _validate_attempt_runtime_binding(
                config=config,
                spec=spec,
                attempt_dir=attempt_dir,
                turn_number=turn_number,
                attempt_number=attempt_number,
                receipt=receipt,
            )
        disposition = "COMMIT_COMPLETED_TURN"
    elif receipt_error in {"BODY_INCIDENT", "EVIDENCE_INCIDENT"}:
        disposition = str(receipt_error)
    else:
        disposition = "RUNTIME_PAUSED"
    return receipt, {
        "disposition": disposition,
        "attempt_number": attempt_number,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "event_summary": event_summary,
        "body_incident_count": len(body_incidents),
        "state_turns_before": int(state.get("turns_completed", 0)),
    }


def _commit_receipt_bearing_attempt_to_state(
    *,
    config: Mapping[str, Any],
    spec: Mapping[str, Any],
    state_path: Path,
    state: dict[str, Any],
    attempt_dir: Path,
    turn_number: int,
) -> dict[str, Any]:
    receipt, verified = _validate_attempt_receipt_sources(
        config=config,
        spec=spec,
        state=state,
        attempt_dir=attempt_dir,
        turn_number=turn_number,
    )
    disposition = verified["disposition"]
    turn_dir = attempt_dir.parent
    sealed_commits, legacy_migration_required = _normalized_recovery_state_commits(
        config=config,
        spec=spec,
        state=state,
    )
    if legacy_migration_required:
        raise PerpetualRuntimeError(
            f"RECOVERY_STATE_COMMIT_LEGACY_SEAL_NOT_MIGRATED: {spec['lineage_id']}"
        )
    seal = {
        "schema": RECOVERY_STATE_COMMIT_SCHEMA,
        "run_id": config["run_id"],
        "lineage_id": spec["lineage_id"],
        "turn_number": turn_number,
        "attempt_number": verified["attempt_number"],
        "receipt_path": verified["receipt_path"],
        "receipt_sha256": verified["receipt_sha256"],
        "disposition": disposition,
    }
    matching = [
        item
        for item in sealed_commits
        if isinstance(item, Mapping)
        and item.get("turn_number") == turn_number
        and item.get("attempt_number") == verified["attempt_number"]
    ]
    if matching:
        if len(matching) != 1 or dict(matching[0]) != seal:
            raise PerpetualRuntimeError(
                f"RECOVERY_STATE_COMMIT_SEAL_DRIFT: {spec['lineage_id']} turn={turn_number}"
            )
        return {
            "lineage_id": spec["lineage_id"],
            "turn_number": turn_number,
            "attempt_number": verified["attempt_number"],
            "disposition": disposition,
            "receipt_path": verified["receipt_path"],
            "receipt_sha256": verified["receipt_sha256"],
            "reused": True,
        }
    sealed_commits = [*sealed_commits, seal]
    common = {
        "active_pid": None,
        "last_turn_dir": str(turn_dir),
        "recovery_state_commits": sealed_commits,
        "recovery_state_commit_receipt_path": verified["receipt_path"],
        "recovery_state_commit_receipt_sha256": verified["receipt_sha256"],
        "recovery_state_commit_disposition": disposition,
        "recovery_state_commit_turn_number": turn_number,
        "recovery_state_commit_attempt_number": verified["attempt_number"],
        "updated_at": now_iso(),
    }
    if disposition == "COMMIT_COMPLETED_TURN":
        state.update(
            {
                **common,
                "status": "TURN_COMPLETED_RECOVERED_STATE_COMMIT",
                "turns_completed": turn_number,
                "lifecycle_state": receipt.get("lifecycle_state"),
                "session_id": receipt.get("session_id_observed") or state.get("session_id"),
                "last_completed_turn_dir": str(turn_dir),
                "last_error_class": None,
                "last_error": None,
            }
        )
    elif disposition in {"BODY_INCIDENT", "EVIDENCE_INCIDENT"}:
        state.update(
            {
                **common,
                "status": disposition,
                "last_error_class": disposition,
                "last_error": (
                    str(receipt.get("body_incident", {}).get("incident_id"))
                    if disposition == "BODY_INCIDENT"
                    else "REQUIRED_DEEP_EVIDENCE_UNAVAILABLE"
                ),
            }
        )
    else:
        state.update(
            {
                **common,
                "status": "RUNTIME_PAUSED",
                "last_error_class": receipt.get("error_class") or "TURN_FAILED",
                "last_error": "RECEIPT_COMMITTED_FAILURE_REQUIRES_OPERATOR_WAKE",
            }
        )
    atomic_write_json(state_path, state)
    return {
        "lineage_id": spec["lineage_id"],
        "turn_number": turn_number,
        "attempt_number": verified["attempt_number"],
        "disposition": disposition,
        "receipt_path": verified["receipt_path"],
        "receipt_sha256": verified["receipt_sha256"],
        "reused": False,
    }


def reconcile_incomplete_attempts(
    config: Mapping[str, Any], *, recovery_dir: Path
) -> dict[str, Any]:
    """Finalize only mechanically complete post-process turns; preserve all others in place."""

    run_dir = resolve_path(config["run_dir"])
    family = schema_family(config["schema"])
    completed: list[dict[str, Any]] = []
    receipt_commits: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for spec in [*config["branch_lineages"], config["root_lineage"]]:
        lineage_id = str(spec["lineage_id"])
        lineage_dir = run_dir / "lineages" / lineage_id
        state_path = lineage_dir / "state.json"
        state = read_json_object(state_path)
        _validate_recovered_receipt_sources(
            config=config,
            spec=spec,
            state_path=state_path,
            state=state,
        )
        turn_number = int(state.get("turns_completed", 0)) + 1
        turn_dir = lineage_dir / "turns" / f"turn-{turn_number:06d}"
        attempts = sorted(attempt for attempt in turn_dir.glob("attempt-*") if attempt.is_dir())
        if not attempts:
            if state.get("active_pid") is not None:
                state["active_pid"] = None
                state["updated_at"] = now_iso()
                atomic_write_json(state_path, state)
            continue
        latest_attempt = attempts[-1]
        incomplete = [attempt for attempt in attempts if not (attempt / "receipt.json").is_file()]
        if (latest_attempt / "receipt.json").is_file():
            if incomplete:
                raise PerpetualRuntimeError(
                    f"RECOVERY_RECEIPT_AFTER_INCOMPLETE_ATTEMPT_AMBIGUOUS: {lineage_id}"
                )
            receipt_commits.append(
                _commit_receipt_bearing_attempt_to_state(
                    config=config,
                    spec=spec,
                    state_path=state_path,
                    state=state,
                    attempt_dir=latest_attempt,
                    turn_number=turn_number,
                )
            )
            continue
        if len(incomplete) != 1:
            raise PerpetualRuntimeError(
                f"RECOVERY_INCOMPLETE_ATTEMPT_AMBIGUOUS: {lineage_id} count={len(incomplete)}"
            )
        attempt_dir = incomplete[0]
        stdout_path = attempt_dir / "exec_stdout.jsonl"
        stderr_path = attempt_dir / "exec_stderr.txt"
        prompt_path = attempt_dir / "prompt.txt"
        message_path = attempt_dir / "last_message.txt"
        required = [stdout_path, stderr_path, prompt_path]
        if not all(path.is_file() for path in required):
            event_summary = {"terminal_events": []}
        else:
            event_summary = _summarize_attempt_events(stdout_path)
        lifecycle = (
            parse_lifecycle_state(message_path.read_text(encoding="utf-8", errors="replace"))
            if message_path.is_file()
            else None
        )
        terminal_events = event_summary.get("terminal_events")
        body_incidents = (
            classify_body_incident_events(
                stdout_path,
                workspace=resolve_path(spec["workspace"]),
            )
            if stdout_path.is_file()
            else []
        )
        source_identity = _attempt_recovery_source_identity(
            attempt_dir,
            event_summary=event_summary,
            lifecycle=lifecycle,
            body_incidents=body_incidents,
        )
        mechanically_complete = (
            terminal_events == ["turn.completed"]
            and lifecycle is not None
            and message_path.is_file()
            and all(path.is_file() for path in required)
            and source_identity["stdout_ends_newline"] is True
            and not body_incidents
        )
        attempt_number_match = re.fullmatch(r"attempt-(\d+)", attempt_dir.name)
        if attempt_number_match is None:
            raise PerpetualRuntimeError(f"RECOVERY_ATTEMPT_NAME_INVALID: {attempt_dir}")
        attempt_number = int(attempt_number_match.group(1))
        evidence_required = _turn_requires_deep_evidence(
            config,
            lineage_id=lineage_id,
            turn_number=turn_number,
        )
        runtime_binding_required = _turn_requires_runtime_binding(
            config,
            lineage_id=lineage_id,
            turn_number=turn_number,
        )
        trajectory: dict[str, Any] | None = None
        artifacts: dict[str, Any] | None = None
        runtime_binding_reference: dict[str, Any] | None = None
        evidence_errors: list[str] = []
        if mechanically_complete:
            try:
                trajectory = build_trajectory_index(
                    stdout_path, attempt_dir / "trajectory_index.jsonl"
                )
            except (FileNotFoundError, PermissionError, OSError, PerpetualRuntimeError) as exc:
                evidence_errors.append(f"TRAJECTORY_INDEX:{type(exc).__name__}")
            if evidence_required:
                try:
                    artifacts = capture_workspace_artifacts(
                        workspace=resolve_path(spec["workspace"]),
                        run_id=str(config["run_id"]),
                        source_head=str(config["source_head"]),
                        run_dir=run_dir,
                        lineage_id=lineage_id,
                        turn_number=turn_number,
                        attempt_number=attempt_number,
                        manifest_path=attempt_dir / "artifact_manifest.json",
                    )
                    if artifacts.get("complete") is not True:
                        evidence_errors.append("ARTIFACT_MANIFEST:INCOMPLETE")
                except (
                    FileNotFoundError,
                    PermissionError,
                    OSError,
                    PerpetualRuntimeError,
                ) as exc:
                    evidence_errors.append(f"ARTIFACT_MANIFEST:{type(exc).__name__}")
            if runtime_binding_required:
                try:
                    runtime_binding_reference = _validate_attempt_runtime_binding(
                        config=config,
                        spec=spec,
                        attempt_dir=attempt_dir,
                        turn_number=turn_number,
                        attempt_number=attempt_number,
                        receipt=None,
                    )
                except PerpetualRuntimeError as exc:
                    evidence_errors.append("RUNTIME_BINDING:" + str(exc).split(":", 1)[0])
        evidence_available = (
            trajectory is not None
            and artifacts is not None
            and artifacts.get("complete") is True
            and not evidence_errors
        )
        can_finalize = (
            mechanically_complete
            and trajectory is not None
            and (not evidence_required or evidence_available)
            and (not runtime_binding_required or runtime_binding_reference is not None)
        )
        if can_finalize:
            command = (
                read_json_object(attempt_dir / "command.json")
                if (attempt_dir / "command.json").is_file()
                else {}
            )
            receipt = {
                "schema": family["turn"],
                "run_id": config["run_id"],
                "lineage_id": lineage_id,
                "role": spec["role"],
                "turn_number": turn_number,
                "attempt_number": attempt_number,
                "started_at": dt.datetime.fromtimestamp(
                    prompt_path.stat().st_mtime, dt.timezone.utc
                )
                .astimezone()
                .isoformat(timespec="seconds"),
                "ended_at": dt.datetime.fromtimestamp(message_path.stat().st_mtime, dt.timezone.utc)
                .astimezone()
                .isoformat(timespec="seconds"),
                "duration_seconds": None,
                "pid": state.get("active_pid"),
                "exit_code": None,
                "process_exit_code_observed": False,
                "inferred_process_success": True,
                "completion_basis": "RECOVERED_TURN_COMPLETED_EVENT_AND_LIFECYCLE",
                "stopped": False,
                "timed_out": False,
                "session_id_before": command.get("resume_session_id"),
                "session_id_observed": event_summary.get("thread_id") or state.get("session_id"),
                "turn_status": "turn.completed",
                "usage": event_summary.get("usage"),
                "response_item_count": event_summary.get("response_item_count", 0),
                "tool_item_count": event_summary.get("tool_item_count", 0),
                "lifecycle_state": lifecycle,
                "error_class": None,
                "prompt_sha256": sha256_file(prompt_path),
                "stdout_sha256": sha256_file(stdout_path),
                "stderr_sha256": sha256_file(stderr_path),
                "last_message_sha256": sha256_file(message_path),
                "body_boundary": config.get("body_boundary"),
                "body_incident": None,
                "deep_evidence": {
                    "status": "AVAILABLE" if evidence_available else "PARTIAL",
                    "captured_at": now_iso(),
                    "trajectory": trajectory,
                    "artifacts": artifacts,
                    "errors": (
                        [] if evidence_available else ["ARTIFACT_MANIFEST:LEGACY_TURN_NOT_REQUIRED"]
                    ),
                },
                "runtime_binding": runtime_binding_reference,
                "recovered_from_incomplete_attempt": True,
                "recovery_source_identity": source_identity,
            }
            receipt_sha256 = atomic_write_json(attempt_dir / "receipt.json", receipt)
            state.update(
                {
                    "status": "TURN_COMPLETED_RECOVERED",
                    "turns_completed": turn_number,
                    "lifecycle_state": lifecycle,
                    "session_id": receipt["session_id_observed"],
                    "active_pid": None,
                    "last_turn_dir": str(turn_dir),
                    "last_completed_turn_dir": str(turn_dir),
                    "last_error_class": None,
                    "last_error": None,
                    "updated_at": now_iso(),
                }
            )
            atomic_write_json(state_path, state)
            completed.append(
                {
                    "lineage_id": lineage_id,
                    "turn_number": turn_number,
                    "attempt_number": attempt_number,
                    "receipt_path": str(attempt_dir / "receipt.json"),
                    "receipt_sha256": receipt_sha256,
                    "lifecycle_state": lifecycle,
                }
            )
            continue
        if body_incidents:
            reason = "BODY_INCIDENT_DETECTED_DURING_RECOVERY"
            parked_status = "BODY_INCIDENT"
            last_error_class = "BODY_INCIDENT"
        elif (
            mechanically_complete and runtime_binding_required and runtime_binding_reference is None
        ):
            reason = "REQUIRED_RUNTIME_BINDING_UNAVAILABLE_DURING_RECOVERY"
            parked_status = "EVIDENCE_INCIDENT"
            last_error_class = "EVIDENCE_INCIDENT"
        elif mechanically_complete and evidence_required and not evidence_available:
            reason = "REQUIRED_DEEP_EVIDENCE_UNAVAILABLE_DURING_RECOVERY"
            parked_status = "EVIDENCE_INCIDENT"
            last_error_class = "EVIDENCE_INCIDENT"
        elif mechanically_complete and trajectory is None:
            reason = "RECOVERY_TRAJECTORY_INDEX_UNAVAILABLE"
            parked_status = "EVIDENCE_INCIDENT"
            last_error_class = "EVIDENCE_INCIDENT"
        else:
            reason = "NO_UNAMBIGUOUS_COMPLETED_TURN_EVENT_AND_LIFECYCLE"
            parked_status = "RECOVERY_QUARANTINED_INCOMPLETE_ATTEMPT"
            last_error_class = "INCOMPLETE_ATTEMPT_QUARANTINED"
        disposition = {
            "schema": ATTEMPT_RECOVERY_SCHEMA,
            "run_id": config["run_id"],
            "lineage_id": lineage_id,
            "turn_number": turn_number,
            "attempt_number": attempt_number,
            "status": "QUARANTINED_IN_PLACE",
            "reason": reason,
            "observed_terminal_events": terminal_events,
            "last_message_present": message_path.is_file(),
            "lifecycle_state": lifecycle,
            "source_identity": source_identity,
            "body_incidents": body_incidents,
            "evidence_required": evidence_required,
            "runtime_binding_required": runtime_binding_required,
            "evidence_errors": evidence_errors,
            "observed_at": now_iso(),
        }
        disposition_path = attempt_dir / "recovery_disposition.json"
        reused = False
        if disposition_path.is_file():
            existing_disposition = read_json_object(disposition_path)
            immutable_fields = (
                "schema",
                "run_id",
                "lineage_id",
                "turn_number",
                "attempt_number",
                "status",
                "reason",
                "observed_terminal_events",
                "last_message_present",
                "lifecycle_state",
                "source_identity",
                "body_incidents",
                "evidence_required",
                "runtime_binding_required",
                "evidence_errors",
            )
            if any(
                existing_disposition.get(field) != disposition.get(field)
                for field in immutable_fields
            ):
                raise PerpetualRuntimeError(
                    f"RECOVERY_DISPOSITION_SOURCE_DRIFT: {disposition_path}"
                )
            disposition_sha256 = sha256_file(disposition_path)
            reused = True
        else:
            disposition_sha256 = atomic_write_json(disposition_path, disposition)
        state.update(
            {
                "status": parked_status,
                "active_pid": None,
                "last_error_class": last_error_class,
                "last_error": reason,
                "updated_at": now_iso(),
            }
        )
        atomic_write_json(state_path, state)
        quarantined.append(
            {
                "lineage_id": lineage_id,
                "turn_number": turn_number,
                "attempt_number": attempt_number,
                "attempt_dir": str(attempt_dir),
                "disposition_sha256": disposition_sha256,
                "reused": reused,
                "reason": reason,
            }
        )
    result = {
        "schema": ATTEMPT_RECOVERY_SCHEMA,
        "run_id": config["run_id"],
        "reconciled_at": now_iso(),
        "completed": completed,
        "receipt_state_commits": receipt_commits,
        "quarantined": quarantined,
    }
    atomic_write_json(recovery_dir / "attempt_reconciliation.json", result)
    return result


def _compile_runtime_binding_views(
    *,
    config: Mapping[str, Any],
    manifest_path: Path,
    verify_sources: bool = True,
) -> dict[str, Any]:
    """Read back one copy-first migration and bind every exact run lineage."""

    path = resolve_path(manifest_path)
    if not path.is_file():
        raise PerpetualRuntimeError(f"REALITY_MIGRATION_MANIFEST_MISSING: {path}")
    manifest_sha256 = sha256_file(path)
    module_path = Path(__file__).resolve().with_name("reality_migration.py")
    if not module_path.is_file():
        raise PerpetualRuntimeError("REALITY_MIGRATION_VALIDATOR_MISSING")
    spec = importlib.util.spec_from_file_location(
        f"xinao_reality_migration_{sha256_file(module_path).lower()}", module_path
    )
    if spec is None or spec.loader is None:
        raise PerpetualRuntimeError("REALITY_MIGRATION_VALIDATOR_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.readback_live_reality_migration(
            path,
            expected_manifest_sha256=manifest_sha256.lower(),
            verify_sources=verify_sources,
        )
    except Exception as exc:
        raise PerpetualRuntimeError(
            f"REALITY_MIGRATION_READBACK_FAILED:{type(exc).__name__}"
        ) from exc
    manifest = read_json_object(path)
    if manifest.get("schema") != "xinao.reality-live-copy-first-migration.v1":
        raise PerpetualRuntimeError("REALITY_MIGRATION_SCHEMA_MISMATCH")
    if manifest.get("source_deletion_permitted") is not False:
        raise PerpetualRuntimeError("REALITY_MIGRATION_SOURCE_DELETE_PERMISSION_INVALID")
    if manifest.get("live_reality_root_runtime_bindable") is not False:
        raise PerpetualRuntimeError("REALITY_MIGRATION_SHARED_LIVE_BECAME_RUNNABLE")
    base = manifest.get("base_bundle")
    overlays = manifest.get("workspace_overlays")
    if not isinstance(base, Mapping) or not isinstance(overlays, list):
        raise PerpetualRuntimeError("REALITY_MIGRATION_VIEW_INDEX_INVALID")
    all_specs = [*config["branch_lineages"], config["root_lineage"]]
    views: dict[str, dict[str, Any]] = {}
    for lineage in all_specs:
        lineage_id = str(lineage["lineage_id"])
        workspace = resolve_path(lineage["workspace"])
        matching = [
            item
            for item in overlays
            if isinstance(item, Mapping)
            and item.get("workspace_key") == lineage_id
            and isinstance(item.get("workspace_root"), str)
            and resolve_path(str(item["workspace_root"])) == workspace
        ]
        if len(matching) != 1:
            raise PerpetualRuntimeError(
                f"REALITY_MIGRATION_EXACT_LINEAGE_VIEW_MISSING: {lineage_id}"
            )
        view = dict(matching[0])
        private = view.get("private_live_materialization")
        if not isinstance(private, Mapping):
            raise PerpetualRuntimeError(
                f"REALITY_MIGRATION_PRIVATE_LIVE_CONTRACT_MISSING: {lineage_id}"
            )
        required = (
            "effective_code_root",
            "effective_python_path",
            "effective_code_payload_tree_sha256",
            "effective_code_manifest_path",
            "effective_code_manifest_sha256",
            "private_effective_live_root",
        )
        if any(not isinstance(view.get(key), str) for key in required):
            raise PerpetualRuntimeError(f"REALITY_MIGRATION_LINEAGE_VIEW_INCOMPLETE: {lineage_id}")
        if any(
            not isinstance(private.get(key), str)
            for key in ("root", "receipt_path", "receipt_sha256")
        ):
            raise PerpetualRuntimeError(
                f"REALITY_MIGRATION_PRIVATE_LIVE_CONTRACT_INCOMPLETE: {lineage_id}"
            )
        if resolve_path(str(private["root"])) != resolve_path(
            str(view["private_effective_live_root"])
        ):
            raise PerpetualRuntimeError(
                f"REALITY_MIGRATION_PRIVATE_LIVE_ROOT_MISMATCH: {lineage_id}"
            )
        views[lineage_id] = {
            "workspace": str(workspace),
            "base_manifest_path": str(base["manifest_path"]),
            "base_manifest_sha256": str(base["manifest_sha256"]),
            "effective_code_root": str(view["effective_code_root"]),
            "effective_python_path": str(view["effective_python_path"]),
            "effective_code_manifest_path": str(view["effective_code_manifest_path"]),
            "effective_code_manifest_sha256": str(view["effective_code_manifest_sha256"]),
            "effective_code_tree_sha256": str(view["effective_code_payload_tree_sha256"]),
            "private_live_root": str(view["private_effective_live_root"]),
            "live_seed_receipt_path": str(private["receipt_path"]),
            "live_seed_receipt_sha256": str(private["receipt_sha256"]),
        }
    return {
        "manifest_path": str(path),
        "manifest_sha256": manifest_sha256,
        "migration_id": str(manifest["migration_id"]),
        "views": views,
    }


def _validate_existing_runtime_binding_identity(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-read an adopted migration without allowing recovery to re-pin drift."""

    raw_path = config.get("reality_migration_manifest_path")
    raw_sha256 = config.get("reality_migration_manifest_sha256")
    raw_migration_id = config.get("reality_migration_id")
    raw_views = config.get("runtime_binding_views")
    if (
        not isinstance(raw_path, str)
        or not isinstance(raw_sha256, str)
        or not isinstance(raw_migration_id, str)
        or not isinstance(raw_views, Mapping)
    ):
        raise PerpetualRuntimeError("REALITY_MIGRATION_FROZEN_IDENTITY_MISSING")
    path = resolve_path(raw_path)
    if not path.is_file() or sha256_file(path).casefold() != raw_sha256.casefold():
        raise PerpetualRuntimeError("REALITY_MIGRATION_FROZEN_IDENTITY_DRIFT")
    compiled = _compile_runtime_binding_views(
        config=config,
        manifest_path=path,
        verify_sources=False,
    )
    if (
        resolve_path(compiled["manifest_path"]) != path
        or str(compiled["manifest_sha256"]).casefold() != raw_sha256.casefold()
        or compiled["migration_id"] != raw_migration_id
        or compiled["views"] != dict(raw_views)
    ):
        raise PerpetualRuntimeError("REALITY_MIGRATION_FROZEN_IDENTITY_DRIFT")
    return compiled


def _seal_repaired_controller_release(
    *,
    config_path: Path,
    config: Mapping[str, Any],
    recovery_dir: Path,
    recovery_id: str,
    reason: str,
    reality_migration_manifest_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current_source = Path(__file__).resolve()
    current_raw = current_source.read_bytes()
    current_sha = sha256_bytes(current_raw)
    previous_path = resolve_path(config["controller_release_path"])
    previous_sha = str(config["controller_release_sha256"])
    if not previous_path.is_file() or sha256_file(previous_path) != previous_sha:
        raise PerpetualRuntimeError("CONTROLLER_RELEASE_BYTES_CHANGED")
    generation = int(config.get("recovery_generation", 0)) + 1
    release_dir = resolve_path(config["run_dir"]) / "controller_releases"
    release_path = release_dir / f"recovery-{generation:06d}-{current_sha[:12].lower()}.py"
    if release_path.exists():
        if not release_path.is_file() or sha256_file(release_path) != current_sha:
            raise PerpetualRuntimeError(f"RECOVERY_RELEASE_PATH_COLLISION: {release_path}")
    else:
        atomic_write_bytes(release_path, current_raw)
    atomic_write_bytes(recovery_dir / "run_config.before.json", config_path.read_bytes())
    launcher_source = resolve_path(config.get("launcher_source_path", config["launcher_path"]))
    expected_launcher_source_sha = config.get("launcher_source_sha256")
    if not launcher_source.is_file():
        raise PerpetualRuntimeError(f"CLEANROOM_LAUNCHER_MISSING: {launcher_source}")
    observed_launcher_source_sha = sha256_file(launcher_source)
    if (
        isinstance(expected_launcher_source_sha, str)
        and observed_launcher_source_sha != expected_launcher_source_sha
    ):
        raise PerpetualRuntimeError("CLEANROOM_LAUNCHER_SOURCE_CHANGED")
    migration_adoption: dict[str, Any] | None = None
    if reality_migration_manifest_path is not None:
        migration_adoption = _compile_runtime_binding_views(
            config=config,
            manifest_path=reality_migration_manifest_path,
        )
    elif config.get("runtime_binding_required") is True:
        migration_adoption = _validate_existing_runtime_binding_identity(config)
    runtime_binding_required = migration_adoption is not None
    isolated_launcher_path = release_dir / f"recovery-{generation:06d}-world-isolated.ps1"
    isolated_launcher = create_world_isolated_launcher(
        launcher_source,
        isolated_launcher_path,
        require_runtime_binding=runtime_binding_required,
    )
    runtime_binding_release_path: Path | None = None
    runtime_binding_release_sha256: str | None = None
    if runtime_binding_required:
        runtime_binding_source = current_source.with_name("runtime_binding.py")
        if not runtime_binding_source.is_file():
            raise PerpetualRuntimeError("WORLD_RUNTIME_BINDING_SOURCE_MISSING")
        runtime_binding_raw = runtime_binding_source.read_bytes()
        runtime_binding_release_sha256 = sha256_bytes(runtime_binding_raw)
        runtime_binding_release_path = (
            release_dir / f"recovery-{generation:06d}-runtime-binding-"
            f"{runtime_binding_release_sha256[:12].lower()}.py"
        )
        if runtime_binding_release_path.exists():
            if (
                not runtime_binding_release_path.is_file()
                or sha256_file(runtime_binding_release_path) != runtime_binding_release_sha256
            ):
                raise PerpetualRuntimeError(
                    f"WORLD_RUNTIME_BINDING_RELEASE_PATH_COLLISION: {runtime_binding_release_path}"
                )
        else:
            atomic_write_bytes(runtime_binding_release_path, runtime_binding_raw)
    raw_history = config.get("controller_release_history")
    if raw_history is None:
        history: list[dict[str, Any]] = [
            {
                "generation": int(config.get("recovery_generation", 0)),
                "path": str(previous_path),
                "sha256": previous_sha,
                "activated_at": config.get("created_at"),
                "preserved": True,
            }
        ]
    elif isinstance(raw_history, list) and all(isinstance(item, dict) for item in raw_history):
        history = [dict(item) for item in raw_history]
    else:
        raise PerpetualRuntimeError("CONTROLLER_RELEASE_HISTORY_INVALID")
    history.append(
        {
            "generation": generation,
            "path": str(release_path),
            "sha256": current_sha,
            "activated_at": now_iso(),
            "adoption_reason": reason,
            "adopted_by_recovery_id": recovery_id,
            "source_path": str(current_source),
        }
    )
    updated = dict(config)
    persisted_turns: dict[str, int] = {}
    for spec in [*config["branch_lineages"], config["root_lineage"]]:
        lineage_id = str(spec["lineage_id"])
        state_path = resolve_path(config["run_dir"]) / "lineages" / lineage_id / "state.json"
        state = read_json_object(state_path) if state_path.is_file() else {}
        persisted_turns[lineage_id] = int(state.get("turns_completed", 0))
    prior_required_from = config.get("deep_evidence_required_from_turn")
    prior_required_from = (
        dict(prior_required_from) if isinstance(prior_required_from, Mapping) else {}
    )
    deep_evidence_was_required = config.get("deep_evidence_required") is True
    required_from_after_recovery = {
        lineage_id: (
            int(prior_required_from[lineage_id])
            if lineage_id in prior_required_from
            else (1 if deep_evidence_was_required else turns_completed + 1)
        )
        for lineage_id, turns_completed in sorted(persisted_turns.items())
    }
    prior_runtime_required_from = config.get("runtime_binding_required_from_turn")
    prior_runtime_required_from = (
        dict(prior_runtime_required_from)
        if isinstance(prior_runtime_required_from, Mapping)
        else {}
    )
    runtime_binding_was_required = config.get("runtime_binding_required") is True
    runtime_binding_required_from_after_recovery = {
        lineage_id: (
            int(prior_runtime_required_from[lineage_id])
            if lineage_id in prior_runtime_required_from
            else (1 if runtime_binding_was_required else turns_completed + 1)
        )
        for lineage_id, turns_completed in sorted(persisted_turns.items())
    }
    updated.update(
        {
            "controller_release_path": str(release_path),
            "controller_release_sha256": current_sha,
            "controller_release_history": history,
            "recovery_generation": generation,
            "controller_release_adopted_at": now_iso(),
            "controller_release_adoption_reason": reason,
            "launcher_path": str(isolated_launcher_path),
            "launcher_sha256": isolated_launcher["sha256"],
            "launcher_source_path": str(launcher_source),
            "launcher_source_sha256": observed_launcher_source_sha,
            "controller_python": str(
                Path(str(getattr(sys, "_base_executable", sys.executable))).resolve(strict=False)
            ),
            "controller_python_sha256": sha256_file(
                Path(str(getattr(sys, "_base_executable", sys.executable))).resolve(strict=False)
            ),
            "deep_evidence_required": True,
            "deep_evidence_required_from_turn": required_from_after_recovery,
            "runtime_binding_required": runtime_binding_required,
            "runtime_binding_required_from_turn": (
                runtime_binding_required_from_after_recovery if runtime_binding_required else {}
            ),
            "world_turn_concurrency_limit": DEFAULT_WORLD_TURN_CONCURRENCY_LIMIT,
            "world_turn_quota_root": str(DEFAULT_WORLD_TURN_QUOTA_ROOT),
            "body_boundary": {
                "schema": WORLD_ISOLATED_LAUNCHER_SCHEMA,
                "sandbox_mode": "workspace-write",
                "approval_policy": "never",
                "network_access": True,
                "writable_scope": "current_lineage_workspace_only",
                "additional_writable_roots": [],
                "s_repo_writable": False,
                "cleanroom_shared_body_writable": False,
                "account_config_writable": False,
                "body_incident_schema": BODY_INCIDENT_SCHEMA,
            },
        }
    )
    if migration_adoption is not None:
        updated.update(
            {
                "runtime_binding_release_path": str(runtime_binding_release_path),
                "runtime_binding_release_sha256": runtime_binding_release_sha256,
                "reality_migration_manifest_path": migration_adoption["manifest_path"],
                "reality_migration_manifest_sha256": migration_adoption["manifest_sha256"],
                "reality_migration_id": migration_adoption["migration_id"],
                "runtime_binding_views": migration_adoption["views"],
            }
        )
    validate_body_boundary_config(updated)
    atomic_write_json(config_path, updated)
    return updated, {
        "previous_path": str(previous_path),
        "previous_sha256": previous_sha,
        "adopted_path": str(release_path),
        "adopted_sha256": current_sha,
        "source_path": str(current_source),
        "generation": generation,
        "body_boundary_adopted": True,
        "world_turn_concurrency_limit": DEFAULT_WORLD_TURN_CONCURRENCY_LIMIT,
        "world_turn_quota_root": str(DEFAULT_WORLD_TURN_QUOTA_ROOT),
        "launcher_previous_path": str(resolve_path(config["launcher_path"])),
        "launcher_adopted_path": str(isolated_launcher_path),
        "launcher_adopted_sha256": isolated_launcher["sha256"],
        "launcher_source_path": str(launcher_source),
        "launcher_source_sha256": observed_launcher_source_sha,
        "runtime_binding_adopted": runtime_binding_required,
        "runtime_binding_release_path": (
            str(runtime_binding_release_path) if runtime_binding_release_path is not None else None
        ),
        "runtime_binding_release_sha256": runtime_binding_release_sha256,
        "reality_migration_manifest_path": (
            migration_adoption["manifest_path"] if migration_adoption else None
        ),
        "reality_migration_manifest_sha256": (
            migration_adoption["manifest_sha256"] if migration_adoption else None
        ),
        "reality_migration_id": (
            migration_adoption["migration_id"] if migration_adoption else None
        ),
    }


def recover_runtime(args: argparse.Namespace) -> dict[str, Any]:
    """Recover the exact current run, optionally adopting a repaired controller release."""

    if os.name != "nt":
        raise PerpetualRuntimeError("WINDOWS_RUNTIME_REQUIRED")
    runtime_root = select_runtime_root(args.runtime_root, require_current=True)
    pointer, state = load_current(runtime_root)
    run_dir = resolve_path(pointer["run_dir"])
    config_path = run_dir / "run_config.json"
    if not config_path.is_file():
        raise PerpetualRuntimeError(f"RUN_CONFIG_MISSING: {config_path}")
    recovery_id = (
        "recovery-" + dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "-" + uuid.uuid4().hex[:8]
    )
    recovery_dir = run_dir / "recovery" / recovery_id
    receipt_path = recovery_dir / "receipt.json"
    receipt: dict[str, Any] | None = None
    with exclusive_lock(run_dir / "recovery.lock"):
        try:
            pointer, state = load_current(runtime_root)
            config = read_json_object(config_path)
            _validate_recovery_pointer(pointer, state, config, run_dir)
            validate_recovery_account_slot(
                config,
                expected=getattr(args, "expected_account_slot", None),
            )
            live = find_live_runtime_processes(pointer, state, config)
            if live:
                raise PerpetualRuntimeError(
                    "RECOVERY_REFUSED_LIVE_PROCESSES: "
                    + json.dumps(live, ensure_ascii=False, sort_keys=True)
                )
            reserved_quota = [
                {
                    "path": record["path"],
                    "lineage_id": record["lineage_id"],
                    "lease_id": record["lease_id"],
                }
                for record in world_turn_quota_records_for_run(config)
                if record.get("status") == "RESERVED"
            ]
            if reserved_quota:
                raise PerpetualRuntimeError(
                    "RECOVERY_REFUSED_UNRECONCILED_WORLD_TURN_QUOTA_RESERVATION: "
                    + json.dumps(reserved_quota, ensure_ascii=False, sort_keys=True)
                )
            identity = validate_recovery_identity(config)
            recovery_dir.mkdir(parents=True)
            atomic_write_json(recovery_dir / "pointer.before.json", pointer)
            if state is not None:
                atomic_write_json(recovery_dir / "controller_state.before.json", state)
            adopt_current = bool(getattr(args, "adopt_current_release", False))
            migration_manifest_argument = getattr(args, "reality_migration_manifest", None)
            if migration_manifest_argument is not None and not adopt_current:
                raise PerpetualRuntimeError(
                    "REALITY_MIGRATION_ADOPTION_REQUIRES_CURRENT_RELEASE_ADOPTION"
                )
            receipt = {
                "schema": RECOVERY_SCHEMA,
                "recovery_id": recovery_id,
                "run_id": config["run_id"],
                "status": "PREPARING",
                "prepared_at": now_iso(),
                "reason": str(args.reason),
                "adopt_current_release": adopt_current,
                "reality_migration_manifest_argument": (
                    str(resolve_path(migration_manifest_argument))
                    if migration_manifest_argument is not None
                    else None
                ),
                "runtime_identity": identity,
                "release_adoption": None,
                "attempt_reconciliation": None,
                "quarantined_incomplete_packet": None,
                "pointer_before": pointer,
                "controller_state_before": state,
            }
            atomic_write_json(receipt_path, receipt)
            quarantined: dict[str, Any] | None = None
            release_adoption: dict[str, Any] | None = None
            attempt_reconciliation: dict[str, Any] | None = None
            with exclusive_lock(run_dir / "controller.lock"):
                if adopt_current:
                    quarantined = quarantine_incomplete_fusion_packet(
                        config, recovery_id=recovery_id
                    )
                    receipt["quarantined_incomplete_packet"] = quarantined
                    atomic_write_json(receipt_path, receipt)
                    attempt_reconciliation = reconcile_incomplete_attempts(
                        config,
                        recovery_dir=recovery_dir,
                    )
                    receipt["attempt_reconciliation"] = attempt_reconciliation
                    atomic_write_json(receipt_path, receipt)
                    config, release_adoption = _seal_repaired_controller_release(
                        config_path=config_path,
                        config=config,
                        recovery_dir=recovery_dir,
                        recovery_id=recovery_id,
                        reason=str(args.reason),
                        reality_migration_manifest_path=(
                            resolve_path(migration_manifest_argument)
                            if migration_manifest_argument is not None
                            else None
                        ),
                    )
                    receipt["release_adoption"] = release_adoption
                    atomic_write_json(receipt_path, receipt)
                else:
                    incomplete = _next_incomplete_fusion_packet(config)
                    if incomplete is not None:
                        raise PerpetualRuntimeError(
                            f"INCOMPLETE_FUSION_PACKET_REQUIRES_REPAIRED_RELEASE: {incomplete}"
                        )
            release_path = resolve_path(config["controller_release_path"])
            release_sha = str(config["controller_release_sha256"])
            if sha256_file(release_path) != release_sha:
                raise PerpetualRuntimeError("CONTROLLER_RELEASE_BYTES_CHANGED_AFTER_PREPARE")
            receipt.update(
                {
                    "status": "PREPARED",
                    "release_adoption": release_adoption,
                    "attempt_reconciliation": attempt_reconciliation,
                    "quarantined_incomplete_packet": quarantined,
                }
            )
            atomic_write_json(receipt_path, receipt)
            stdout_path = recovery_dir / "controller_stdout.txt"
            stderr_path = recovery_dir / "controller_stderr.txt"
            controller_python = _validated_controller_python(config)
            process, controller_python = _spawn_detached_controller(
                controller_python=controller_python,
                controller_python_sha256=str(config["controller_python_sha256"]),
                release_path=release_path,
                config_path=config_path,
                run_dir=run_dir,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
            pointer_after = dict(pointer)
            pointer_after.update(
                {
                    "controller_pid": process.pid,
                    "launcher_pid": process.pid,
                    "controller_python": str(controller_python),
                    "controller_release_path": str(release_path),
                    "controller_release_sha256": release_sha,
                    "recovered_at": now_iso(),
                    "recovery_id": recovery_id,
                    "recovery_generation": int(config.get("recovery_generation", 0)),
                }
            )
            atomic_write_json(current_pointer(runtime_root), pointer_after)
            controller_state = _wait_for_controller_startup(
                process=process,
                run_dir=run_dir,
                expected_run_id=str(config["run_id"]),
                startup_wait_seconds=float(args.startup_wait_seconds),
                stderr_path=stderr_path,
            )
            receipt.update(
                {
                    "status": "RECOVERED",
                    "completed_at": now_iso(),
                    "pointer_after": pointer_after,
                    "controller_state_after": controller_state,
                }
            )
            atomic_write_json(receipt_path, receipt)
            return {
                "run_id": config["run_id"],
                "recovery_id": recovery_id,
                "recovery_receipt": str(receipt_path),
                "pointer": pointer_after,
                "controller_state": controller_state,
                "release_adoption": release_adoption,
                "quarantined_incomplete_packet": quarantined,
            }
        except BaseException as exc:
            if receipt is not None:
                receipt.update(
                    {
                        "status": "FAILED",
                        "failed_at": now_iso(),
                        "error_class": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                atomic_write_json(receipt_path, receipt)
            raise


def status_runtime(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = select_runtime_root(args.runtime_root, require_current=True)
    pointer, state = load_current(runtime_root)
    pid = state.get("pid") if state else pointer.get("controller_pid")
    return {
        "pointer": pointer,
        "controller_alive": is_process_alive(pid if isinstance(pid, int) else None),
        "controller_state": state,
    }


def stop_runtime(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = select_runtime_root(args.runtime_root, require_current=True)
    pointer, state = load_current(runtime_root)
    run_dir = resolve_path(pointer["run_dir"])
    config = read_json_object(run_dir / "run_config.json")
    schemas = schema_family(config.get("schema"))
    account_slot = validate_recovery_account_slot(config, expected=None)
    stop_path = run_dir / "STOP.json"
    if not stop_path.exists():
        atomic_write_json(
            stop_path,
            {
                "schema": schemas["stop"],
                "requested_at": now_iso(),
                "reason": str(args.reason),
                "scope": "current perpetual world-compute run",
                "account_slot": account_slot,
            },
        )
    pid = state.get("pid") if state else pointer.get("controller_pid")
    deadline = time.monotonic() + float(args.wait_seconds)
    while isinstance(pid, int) and is_process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    state_path = run_dir / "controller_state.json"
    final_state = read_json_object(state_path) if state_path.is_file() else state
    controller_alive = is_process_alive(pid if isinstance(pid, int) else None)
    active_children = {
        str(lineage_id): int(child_pid)
        for lineage_id, child_pid in dict((final_state or {}).get("active_processes", {})).items()
        if isinstance(child_pid, int) and is_process_alive(child_pid)
    }
    if controller_alive or active_children:
        raise PerpetualRuntimeError(
            "STOP_INCOMPLETE_ACTIVE_PROCESSES: "
            + json.dumps(
                {"controller_pid": pid if controller_alive else None, "children": active_children},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return {
        "run_id": pointer.get("run_id"),
        "stop_request": str(stop_path),
        "controller_alive": False,
        "previous_state": state,
        "final_state": final_state,
    }


def wake_runtime(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = select_runtime_root(args.runtime_root, require_current=True)
    pointer, _ = load_current(runtime_root)
    run_dir = resolve_path(pointer["run_dir"])
    config = read_json_object(run_dir / "run_config.json")
    schemas = schema_family(config.get("schema"))
    account_slot = validate_recovery_account_slot(config, expected=None)
    valid_ids = {
        str(spec["lineage_id"]) for spec in [*config["branch_lineages"], config["root_lineage"]]
    }
    targets = sorted(valid_ids) if args.lineage_id == "all" else [args.lineage_id]
    invalid = [value for value in targets if value not in valid_ids]
    if invalid:
        raise PerpetualRuntimeError(f"UNKNOWN_LINEAGE_ID: {invalid}")
    receipts = []
    for lineage_id in targets:
        path = run_dir / "wake" / f"{lineage_id}.json"
        if path.exists():
            raise PerpetualRuntimeError(f"WAKE_ALREADY_PENDING: {lineage_id}")
        payload = {
            "schema": schemas["wake"],
            "requested_at": now_iso(),
            "lineage_id": lineage_id,
            "reason": args.reason,
            "account_slot": account_slot,
        }
        atomic_write_json(path, payload)
        receipts.append({"lineage_id": lineage_id, "path": str(path)})
    return {"run_id": pointer["run_id"], "wake_requests": receipts}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run durable clean-room world-owning XINAO lineages with a selected account slot."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--account-slot", required=True, choices=ACCOUNT_SLOTS)
    start.add_argument("--source-repo", type=Path, default=DEFAULT_SOURCE_REPO)
    start.add_argument("--launcher", type=Path, default=DEFAULT_LAUNCHER)
    start.add_argument("--powershell", type=Path, default=DEFAULT_POWERSHELL)
    start.add_argument("--runtime-root", type=Path)
    start.add_argument("--clone-root", type=Path, default=DEFAULT_CLONE_ROOT)
    start.add_argument(
        "--live-reality-root",
        type=Path,
        default=DEFAULT_XINAO_LIVE_REALITY_ROOT,
    )
    start.add_argument(
        "--world-compute-root",
        type=Path,
        default=DEFAULT_XINAO_WORLD_COMPUTE_ROOT,
    )
    start.add_argument("--run-id")
    start.add_argument("--width", type=int, default=DEFAULT_WIDTH, choices=range(1, 9))
    start.add_argument("--model", default=DEFAULT_MODEL)
    start.add_argument("--model-reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    start.add_argument("--watchdog-seconds", type=int, default=DEFAULT_WATCHDOG_SECONDS)
    start.add_argument(
        "--continuation-delay-seconds",
        type=int,
        default=DEFAULT_CONTINUATION_DELAY_SECONDS,
    )
    start.add_argument(
        "--retry-delays-seconds",
        type=int,
        nargs="*",
        default=list(DEFAULT_RETRY_DELAYS_SECONDS),
    )
    start.add_argument("--park-poll-seconds", type=int, default=DEFAULT_PARK_POLL_SECONDS)
    start.add_argument("--startup-wait-seconds", type=int, default=30)

    run = subparsers.add_parser("run")
    run.add_argument("--config", type=Path, required=True)

    status = subparsers.add_parser("status")
    status.add_argument("--runtime-root", type=Path)

    prepare_migration = subparsers.add_parser(
        "prepare-reality-migration",
        help=(
            "copy and verify the exact stopped current run into one per-run reality "
            "migration without adopting it or starting a controller"
        ),
    )
    prepare_migration.add_argument("--runtime-root", type=Path, required=True)
    prepare_migration.add_argument("--expected-account-slot", required=True, choices=ACCOUNT_SLOTS)
    prepare_migration.add_argument(
        "--live-reality-root",
        type=Path,
        default=DEFAULT_XINAO_LIVE_REALITY_ROOT,
    )
    prepare_migration.add_argument(
        "--world-compute-root",
        type=Path,
        default=DEFAULT_XINAO_WORLD_COMPUTE_ROOT,
    )

    recover = subparsers.add_parser("recover")
    recover.add_argument("--runtime-root", type=Path)
    recover.add_argument("--expected-account-slot", choices=ACCOUNT_SLOTS)
    recover.add_argument(
        "--reason",
        default="recover the current run after an inspected controller failure",
    )
    recover.add_argument(
        "--adopt-current-release",
        action="store_true",
        help="seal the current repository controller as a new preserved release for this run",
    )
    recover.add_argument(
        "--reality-migration-manifest",
        type=Path,
        help=(
            "adopt one verified copy-first reality migration and require its exact "
            "per-lineage runtime binding for subsequent turns"
        ),
    )
    recover.add_argument("--startup-wait-seconds", type=int, default=30)

    stop = subparsers.add_parser("stop")
    stop.add_argument("--runtime-root", type=Path)
    stop.add_argument("--reason", default="explicit operator stop")
    stop.add_argument("--wait-seconds", type=int, default=120)

    wake = subparsers.add_parser("wake")
    wake.add_argument("--runtime-root", type=Path)
    wake.add_argument("--lineage-id", default="all")
    wake.add_argument("--reason", default="explicitly re-opened condition")

    inspect = subparsers.add_parser(
        "inspect-evidence",
        help="open one hash-bound branch event or artifact through a frozen fusion packet",
    )
    inspect.add_argument("--packet", type=Path, required=True)
    inspect.add_argument("--candidate-index", type=int, required=True)
    selection = inspect.add_mutually_exclusive_group()
    selection.add_argument("--event-sequence", type=int)
    selection.add_argument("--artifact-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_runtime(args)
        elif args.command == "run":
            return PerpetualController(args.config).run()
        elif args.command == "status":
            result = status_runtime(args)
        elif args.command == "prepare-reality-migration":
            result = prepare_reality_migration(args)
        elif args.command == "recover":
            result = recover_runtime(args)
        elif args.command == "stop":
            result = stop_runtime(args)
        elif args.command == "wake":
            result = wake_runtime(args)
        elif args.command == "inspect-evidence":
            result = inspect_deep_evidence(
                packet_dir=args.packet,
                candidate_index=args.candidate_index,
                event_sequence=args.event_sequence,
                artifact_sha256=args.artifact_sha256,
            )
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except PerpetualRuntimeError as exc:
        print(f"XINAO_PERPETUAL_WORLD_COMPUTE_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
