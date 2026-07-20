#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [Alias("PackageManifestPath")]
    [string]$DispatchEnvelopePath,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Model,
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$SelectorReleasePointer = "",
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CheckpointPath,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskRunRoot,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskRunId,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TaskRunCli = "C:\Users\xx363\.codex\skills\verified-agent-loop\scripts\task_run.py",
    [int]$TimeoutSec = 600,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Model)) {
    throw "CODEX_GROK_MODEL_REQUIRED"
}
try { $DispatchEnvelopePath = [IO.Path]::GetFullPath($DispatchEnvelopePath) }
catch { throw "CODEX_GROK_DISPATCH_ENVELOPE_PATH_INVALID: $DispatchEnvelopePath" }
if (-not (Test-Path -LiteralPath $DispatchEnvelopePath -PathType Leaf)) {
    throw "CODEX_GROK_DISPATCH_ENVELOPE_MISSING: $DispatchEnvelopePath"
}
try { $CheckpointPath = [IO.Path]::GetFullPath($CheckpointPath) }
catch { throw "CODEX_GROK_CHECKPOINT_PATH_INVALID: $CheckpointPath" }
if (-not (Test-Path -LiteralPath $CheckpointPath -PathType Leaf)) {
    throw "CODEX_GROK_CHECKPOINT_MISSING: $CheckpointPath"
}
try { $TaskRunRoot = [IO.Path]::GetFullPath($TaskRunRoot) }
catch { throw "CODEX_GROK_TASK_RUN_ROOT_INVALID: $TaskRunRoot" }
if (-not (Test-Path -LiteralPath $TaskRunRoot -PathType Container)) {
    throw "CODEX_GROK_TASK_RUN_ROOT_MISSING: $TaskRunRoot"
}
$taskRunDirectory = Join-Path $TaskRunRoot $TaskRunId
if (-not (Test-Path -LiteralPath $taskRunDirectory -PathType Container)) {
    throw "CODEX_GROK_TASK_RUN_DIRECTORY_MISSING: $taskRunDirectory"
}
try { $TaskRunCli = [IO.Path]::GetFullPath($TaskRunCli) }
catch { throw "CODEX_GROK_TASK_RUN_CLI_PATH_INVALID: $TaskRunCli" }
if (-not (Test-Path -LiteralPath $TaskRunCli -PathType Leaf)) {
    throw "CODEX_GROK_TASK_RUN_CLI_MISSING: $TaskRunCli"
}
try {
    $dispatchEnvelope = Get-Content -LiteralPath $DispatchEnvelopePath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "CODEX_GROK_DISPATCH_ENVELOPE_INVALID_JSON: $DispatchEnvelopePath"
}
$selectionPath = [string]$dispatchEnvelope.selection.receipt_ref
if ([string]::IsNullOrWhiteSpace($selectionPath)) {
    throw "CODEX_GROK_PACKAGE_SELECTION_RECEIPT_MISSING"
}

$resolver = Join-Path $PSScriptRoot "resolve_grok_worker_selection_receipt.py"
. (Join-Path $PSScriptRoot "GrokSupervisorRootCapability.ps1")
$capability = Resolve-GrokSupervisorSelectorRoot `
    -SelectionResolver $resolver `
    -RuntimeRoot $RuntimeRoot `
    -ReleasePointer $SelectorReleasePointer
$runner = Join-Path $PSScriptRoot "run_grok_package_batch.py"
$dispatch = Join-Path $PSScriptRoot "Invoke-CodexDispatchGrokWorkerPool.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "CODEX_GROK_PACKAGE_RUNNER_MISSING: $runner"
}
if (-not (Test-Path -LiteralPath $dispatch -PathType Leaf)) {
    throw "CODEX_GROK_PACKAGE_DISPATCH_MISSING: $dispatch"
}
$batchId = "gpb_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$batchRoot = Join-Path $RuntimeRoot ("state\grok_worker_package_batches\" + $batchId)
New-Item -ItemType Directory -Path $batchRoot -ErrorAction Stop | Out-Null
$summary = Join-Path $batchRoot "batch-summary.json"
$arguments = @(
    "-I", "-B", $runner,
    "--dispatch-envelope", $DispatchEnvelopePath,
    "--selector-root", ([string]$capability.resolved_root),
    "--selector-python", ([string]$capability.python_executable),
    "--dispatch-script", $dispatch,
    "--pwsh", ([string](Get-Command pwsh -ErrorAction Stop).Source),
    "--runtime-root", $RuntimeRoot,
    "--model", $Model,
    "--selection-path", $selectionPath,
    "--checkpoint-path", $CheckpointPath,
    "--task-run-cli", $TaskRunCli,
    "--task-run-root", $TaskRunRoot,
    "--task-run-id", $TaskRunId,
    "--summary-output", $summary,
    "--timeout-sec", ([string]$TimeoutSec)
)
$lines = @(
    & ([string]$capability.python_executable) @arguments 2>&1 |
        ForEach-Object { [string]$_ }
)
$exitCode = $LASTEXITCODE
if (-not $Quiet) { $lines }
if ($exitCode -ne 0) {
    throw "CODEX_GROK_PACKAGE_BATCH_FAILED: exit=$exitCode summary=$summary output=$($lines -join [Environment]::NewLine)"
}
if (-not (Test-Path -LiteralPath $summary -PathType Leaf)) {
    throw "CODEX_GROK_PACKAGE_BATCH_SUMMARY_MISSING: $summary"
}
exit 0
