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
    [string]$DispatchEnvelopePath = "",
    [string]$TaskRunCli = "C:\Users\xx363\.codex\skills\verified-agent-loop\scripts\task_run.py",
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
$packageMode = -not [string]::IsNullOrWhiteSpace($DispatchEnvelopePath)
if ($packageMode) {
    try { $DispatchEnvelopePath = [IO.Path]::GetFullPath($DispatchEnvelopePath) }
    catch { throw "CODEX_GROK_DISPATCH_ENVELOPE_PATH_INVALID: $DispatchEnvelopePath" }
    if (-not (Test-Path -LiteralPath $DispatchEnvelopePath -PathType Leaf)) {
        throw "CODEX_GROK_DISPATCH_ENVELOPE_MISSING: $DispatchEnvelopePath"
    }
    try { $TaskRunCli = [IO.Path]::GetFullPath($TaskRunCli) }
    catch { throw "CODEX_GROK_TASK_RUN_CLI_PATH_INVALID: $TaskRunCli" }
    if (-not (Test-Path -LiteralPath $TaskRunCli -PathType Leaf)) {
        throw "CODEX_GROK_TASK_RUN_CLI_MISSING: $TaskRunCli"
    }
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
from services.agent_runtime.dispatch_economics import (  # noqa: E402
    DispatchEconomicsError,
    prepare_worker_package_task_run,
)

try:
    if sys.argv[4] == "-":
        report = prepare_task_local_checkpoint(
            task_run_dir=Path(sys.argv[2]),
            checkpoint_path=Path(sys.argv[3]),
        )
    else:
        report = prepare_worker_package_task_run(
            dispatch_envelope_path=Path(sys.argv[4]),
            task_run_dir=Path(sys.argv[2]),
            task_run_cli=Path(sys.argv[5]),
            checkpoint_path=Path(sys.argv[3]),
        )
except (ActionResumeError, DispatchEconomicsError) as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "reason_code": getattr(exc, "reason_code", type(exc).__name__),
                "error": str(exc),
                "details": getattr(exc, "details", {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)
print(json.dumps(report, ensure_ascii=False, sort_keys=True))
'@
$envelopeArgument = if ($packageMode) { $DispatchEnvelopePath } else { "-" }
$taskRunCliArgument = if ($packageMode) { $TaskRunCli } else { "-" }
$lines = @(
    & ([string]$capability.python_executable) -I -B -c $pythonCode `
        ([string]$capability.resolved_root) $taskRunDirectory $CheckpointPath `
        $envelopeArgument $taskRunCliArgument 2>&1 |
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
if ($packageMode) {
    $packageIds = @($report.package_ids)
    $workKeys = @($report.work_keys)
    if (
        [string]$report.schema_version -ne "xinao.worker_package_task_run_preflight.v1" -or
        $report.model_invocation_allowed -ne $true -or
        $packageIds.Count -lt 1 -or
        $packageIds.Count -ne $workKeys.Count -or
        @($packageIds | Select-Object -Unique).Count -ne $packageIds.Count -or
        @($workKeys | Select-Object -Unique).Count -ne $workKeys.Count -or
        @($packageIds | Where-Object { [string]::IsNullOrWhiteSpace([string]$_) }).Count -gt 0 -or
        @($workKeys | Where-Object { [string]::IsNullOrWhiteSpace([string]$_) }).Count -gt 0
    ) {
        throw "CODEX_GROK_PACKAGE_TASK_RUN_PREFLIGHT_CONTRACT_INVALID: $reportLine"
    }
}
elseif ([string]$report.schema_version -ne "xinao.checkpoint_task_run_binding.v1") {
    throw "CODEX_GROK_CHECKPOINT_PREFLIGHT_CONTRACT_INVALID: $reportLine"
}

$report
