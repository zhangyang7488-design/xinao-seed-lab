#Requires -Version 5.1
<#
.SYNOPSIS
  Loop Guardian：检测推进停滞 → 强制 Gap-Driven Progressor + 可选 RunNext。
.EXAMPLE
  .\Invoke-GrokLoopGuardian.ps1
  .\Invoke-GrokLoopGuardian.ps1 -ForceProgressor -RunNext
#>
param(
    [int]$StaleMinutes = 30,
    [switch]$ForceProgressor,
    [switch]$RunNext,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\loop_guardian"
$latestPath = Join-Path $outDir "latest.json"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 14), $utf8)
}
function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}
function Get-AgeMin([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 99999 }
    return [math]::Round(((Get-Date) - (Get-Item -LiteralPath $Path).LastWriteTime).TotalMinutes, 1)
}

$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$gdpPath = Join-Path $runtime "state\gap_driven_progressor\latest.json"
$sessionPath = Join-Path $runtime "state\grok_session_context\latest.json"
$sensePath = Join-Path $runtime "state\local_state_sense\latest.json"

$q = Read-JsonSafe $queuePath
$pending = 0
if ($q -and $q.tasks) { $pending = @($q.tasks | Where-Object { $_.status -eq "pending" }).Count }

$stall_reasons = [System.Collections.Generic.List[string]]::new()
if ($pending -lt 2) { [void]$stall_reasons.Add("QUEUE_PENDING_LT_2") }
if ((Get-AgeMin $gdpPath) -gt $StaleMinutes) { [void]$stall_reasons.Add("GDP_STALE") }
if ((Get-AgeMin $sessionPath) -gt ($StaleMinutes * 3)) { [void]$stall_reasons.Add("SESSION_CHECKPOINT_STALE") }
if ((Get-AgeMin $sensePath) -gt $StaleMinutes) { [void]$stall_reasons.Add("STATE_SENSE_STALE") }

$stalled = ($stall_reasons.Count -gt 0) -or $ForceProgressor
$actions = [System.Collections.Generic.List[string]]::new()

if ($stalled) {
    [void]$actions.Add("Invoke-GrokGapDrivenProgressor")
    try {
        & (Join-Path $bridge "Invoke-GrokGapDrivenProgressor.ps1") -PushQueue -Quiet | Out-Null
        [void]$actions.Add("GDP_OK")
    } catch {
        [void]$actions.Add("GDP_FAIL:$_")
    }
    if ($RunNext) {
        try {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -Quiet | Out-Null
            [void]$actions.Add("RunNext_OK")
        } catch {
            [void]$actions.Add("RunNext_FAIL:$_")
        }
    }
} else {
    [void]$actions.Add("NO_STALL_IDLE_WATCH")
}

$result = [ordered]@{
    schema_version = "xinao.loop_guardian.v1"
    sentinel       = "SENTINEL:LOOP_GUARDIAN"
    generated_at   = (Get-Date).ToString("o")
    stalled        = $stalled
    stall_reasons  = @($stall_reasons)
    pending_tasks  = $pending
    stale_minutes_threshold = $StaleMinutes
    ages_min       = [ordered]@{
        gdp = (Get-AgeMin $gdpPath)
        session = (Get-AgeMin $sessionPath)
        sense = (Get-AgeMin $sensePath)
        queue = (Get-AgeMin $queuePath)
    }
    actions        = @($actions)
    now_can_do_cn  = @(
        "Invoke-GrokLoopGuardian.ps1 -ForceProgressor -RunNext",
        "Invoke-GrokGapDrivenProgressor.ps1 -DeepSense",
        "读 readback/zh/gap_driven_interject_latest.md"
    )
    completion_claim_allowed = $false
    note_cn = "Guardian 不写长报告当推进；只触发 GDP/RunNext"
}

Write-JsonFile $latestPath $result
if (-not $Quiet) {
    Write-Host "LoopGuardian stalled=$stalled reasons=$($stall_reasons -join ',') actions=$($actions -join ' | ')"
    Write-Host "evidence: $latestPath"
}
$result
