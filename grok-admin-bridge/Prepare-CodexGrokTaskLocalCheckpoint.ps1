#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskRunRoot,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskRunId,
    [string]$CheckpointPath = "",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$SelectorReleasePointer = ""
)

$ErrorActionPreference = "Stop"

try { $taskRunRootFull = [IO.Path]::GetFullPath($TaskRunRoot) }
catch { throw "CODEX_GROK_TASK_RUN_ROOT_INVALID: $TaskRunRoot" }
if (-not (Test-Path -LiteralPath $taskRunRootFull -PathType Container)) {
    throw "CODEX_GROK_TASK_RUN_ROOT_MISSING: $taskRunRootFull"
}
if ($TaskRunId -match '[\\/]' -or $TaskRunId -in @('.', '..')) {
    throw "CODEX_GROK_TASK_RUN_ID_INVALID: $TaskRunId"
}
$taskRunDirectory = [IO.Path]::GetFullPath((Join-Path $taskRunRootFull $TaskRunId))
if (-not [string]::Equals(
    [IO.Path]::GetFullPath((Split-Path -Parent $taskRunDirectory)),
    $taskRunRootFull,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "CODEX_GROK_TASK_RUN_ID_ESCAPED_ROOT: $TaskRunId"
}
if (-not (Test-Path -LiteralPath $taskRunDirectory -PathType Container)) {
    throw "CODEX_GROK_TASK_RUN_DIRECTORY_MISSING: $taskRunDirectory"
}
$canonicalCheckpoint = [IO.Path]::GetFullPath(
    (Join-Path $taskRunDirectory "task-local-checkpoint.v2.json")
)
if ([string]::IsNullOrWhiteSpace($CheckpointPath)) {
    $CheckpointPath = $canonicalCheckpoint
}
else {
    try { $CheckpointPath = [IO.Path]::GetFullPath($CheckpointPath) }
    catch { throw "CODEX_GROK_CHECKPOINT_PATH_INVALID: $CheckpointPath" }
}
if (-not [string]::Equals(
    $CheckpointPath,
    $canonicalCheckpoint,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "CODEX_GROK_CHECKPOINT_PATH_OUTSIDE_TASK_RUN: expected=$canonicalCheckpoint actual=$CheckpointPath"
}

$resolver = Join-Path $PSScriptRoot "resolve_grok_worker_selection_receipt.py"
. (Join-Path $PSScriptRoot "GrokSupervisorRootCapability.ps1")
$capability = Resolve-GrokSupervisorSelectorRoot `
    -SelectionResolver $resolver `
    -RuntimeRoot $RuntimeRoot `
    -ReleasePointer $SelectorReleasePointer

$pythonCode = @'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from services.agent_runtime.action_resume_receipt import (  # noqa: E402
    ActionResumeError,
    prepare_task_local_checkpoint,
)

try:
    report = prepare_task_local_checkpoint(
        task_run_dir=Path(sys.argv[2]),
        checkpoint_path=Path(sys.argv[3]),
    )
except ActionResumeError as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "reason_code": exc.reason_code,
                "error": str(exc),
                "details": exc.details,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)
print(json.dumps(report, ensure_ascii=False, sort_keys=True))
'@
$lines = @(
    & ([string]$capability.python_executable) -I -B -c $pythonCode `
        ([string]$capability.resolved_root) $taskRunDirectory $CheckpointPath 2>&1 |
        ForEach-Object { [string]$_ }
)
$exitCode = $LASTEXITCODE
$reportLine = @($lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) |
    Select-Object -Last 1
if ($exitCode -ne 0) {
    throw "CODEX_GROK_CHECKPOINT_PREFLIGHT_FAILED: exit=$exitCode output=$($lines -join [Environment]::NewLine)"
}
try { $report = $reportLine | ConvertFrom-Json -ErrorAction Stop }
catch {
    throw "CODEX_GROK_CHECKPOINT_PREFLIGHT_OUTPUT_INVALID: $($lines -join [Environment]::NewLine)"
}
if (
    [string]$report.schema_version -ne "xinao.checkpoint_task_run_binding.v1" -or
    $report.authority -ne $false -or
    $report.completion_claim_allowed -ne $false -or
    [string]$report.run_id -ne $TaskRunId -or
    [int]$report.cursor -lt 1 -or
    [int]$report.cursor -ne [int]$report.event_count -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath([string]$report.checkpoint_path),
        $canonicalCheckpoint,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "CODEX_GROK_CHECKPOINT_PREFLIGHT_CONTRACT_INVALID: $reportLine"
}

$report
