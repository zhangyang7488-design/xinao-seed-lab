[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$TemporalAddress = "127.0.0.1:7233",
    [string]$TaskQueue = "xinao-codex-task-default"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$wrapper = Join-Path $RepoRoot "scripts\hardmode\Invoke-CodexS333RunReconciler.ps1"
Assert-True (Test-Path -LiteralPath $wrapper -PathType Leaf) "Missing wrapper: $wrapper"

& $wrapper -RuntimeRoot $RuntimeRoot -RepoRoot $RepoRoot -TemporalAddress $TemporalAddress -TaskQueue $TaskQueue
Assert-True ($LASTEXITCODE -eq 0) "333 run reconciler invocation failed."

$latestPath = Join-Path $RuntimeRoot "state\codex_333_run_reconciler\latest.json"
$currentIndexPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.333_run_reconciler\manifest.json"
$toolRegistryPath = Join-Path $RuntimeRoot "agent_runtime\tools\registry\tool_registry.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\codex_333_run_reconciler.md"

$latest = Read-JsonFile $latestPath
$current = Read-JsonFile $currentIndexPath
$manifest = Read-JsonFile $manifestPath
$toolRegistry = Read-JsonFile $toolRegistryPath

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.333_run_reconciler.v1") "schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_CODEX_S_333_RUN_RECONCILER_READY") "sentinel mismatch."
Assert-True ($latest.validation.passed -eq $true) "validation did not pass."
Assert-True ($latest.no_temporal_write_performed -eq $true) "Temporal write was performed."
Assert-True ($latest.no_signal_sent -eq $true) "Signal was sent."
Assert-True ($latest.no_worker_started_or_stopped -eq $true) "Worker was started/stopped."
Assert-True ($latest.completion_claim_allowed -eq $false) "completion claim is allowed."
Assert-True ($latest.not_execution_controller -eq $true) "not_execution_controller missing."

$selected = $latest.decision.selected -eq $true
$blocker = [string]$latest.decision.named_blocker
Assert-True ($selected -or -not [string]::IsNullOrWhiteSpace($blocker)) "Neither selected nor named-blocked."

Assert-True ([string]$current.reconciler_schema_version -eq "xinao.codex_s.333_run_reconciler.v1") "current index was not written by reconciler."
Assert-True ($current.completion_claim_allowed -eq $false) "current index allows completion."
Assert-True ($current.not_user_completion -eq $true) "current index not_user_completion missing."
Assert-True ($current.not_execution_controller -eq $true) "current index not_execution_controller missing."
Assert-True ($current.reconciliation.no_temporal_write_performed -eq $true) "current index overclaims Temporal write."

if ($selected) {
    Assert-True ([string]$current.status -eq "current_333_run_index_ready") "selected current index not ready."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$current.workflow_id)) "selected workflow_id missing."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$current.workflow_run_id)) "selected workflow_run_id missing."
}
else {
    Assert-True ([string]$current.status -eq "current_333_run_index_blocked") "blocked current index not blocked."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$current.reconciliation.named_blocker)) "current index blocker missing."
}

Assert-True ([string]$manifest.provider_id -eq "codex_s.333_run_reconciler") "manifest provider mismatch."
Assert-True ($manifest.not_execution_controller -eq $true) "manifest not_execution_controller missing."
Assert-True ($manifest.completion_claim_allowed -eq $false) "manifest completion claim allowed."
Assert-True (@($toolRegistry.provider_ids) -contains "codex_s.333_run_reconciler") "ToolRegistry missing codex_s.333_run_reconciler."
Assert-True ($toolRegistry.not_execution_controller -eq $true) "ToolRegistry overclaims execution control."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."

Write-Output "codex_333_run_reconciler_latest=$latestPath"
Write-Output "current_333_run_index_latest=$currentIndexPath"
Write-Output "capability_manifest=$manifestPath"
Write-Output "tool_registry=$toolRegistryPath"
Write-Output "selected=$selected"
Write-Output "named_blocker=$blocker"
Write-Output "validation_result=ok"
