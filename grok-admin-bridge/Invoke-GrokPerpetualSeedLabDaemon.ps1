#Requires -Version 5.1
<#
.SYNOPSIS
  后台辅助守护：长时间 GapScan + 守护 pending 任务（不替代前台 WaveCycle）。
  前台主责：Invoke-GrokFrontendPerpetualDrive.ps1
  合同：grok_perpetual_sleep_daemon.v1.json
.PARAMETER GapScanIntervalSec
  全量差距扫描间隔秒（默认 900）。
.PARAMETER MaxParallel
  波次最大并行（默认 8）。
.PARAMETER BootstrapOneLoop
  仅跑一圈（GapScan→Pulse→Wave→RunNext→checkpoint→写 latest.json）后退出，不 sleep。
#>
param(
    [int]$GapScanIntervalSec = 900,
    [int]$MaxParallel = 8,
    [switch]$Quiet,
    [switch]$BootstrapOneLoop
)

$ErrorActionPreference = "Continue"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateDir = Join-Path $runtime "state\grok_perpetual_daemon"
$latestPath = Join-Path $stateDir "latest.json"
$stopFlag = Join-Path $stateDir "user_stop.flag"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Write-Log([string]$Msg) {
    if (-not $Quiet) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Msg" }
}

function Test-Stop { return (Test-Path -LiteralPath $stopFlag) }

function Save-DaemonState([hashtable]$State) {
    $State.generated_at = (Get-Date).ToString("o")
    $State.schema_version = "xinao.grok_perpetual_daemon_run.v1"
    $State.sentinel = "SENTINEL:GROK_PERPETUAL_SEEDLAB_DAEMON"
    $State.completion_claim_allowed = $false
    $State | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $latestPath -Encoding UTF8
    $md = Join-Path $runtime "readback\zh\grok_perpetual_daemon_latest.md"
    New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
    @(
        "# 永续守护 Seed Lab",
        "",
        "时间：$($State.generated_at)",
        "圈次：**$($State.loop_index)**",
        "最近 GapScan：$($State.last_gap_scan_at)",
        "gap_count：**$($State.last_gap_count)**",
        "",
        "角色：**后台辅助**（GapScan+pending守护）。前台波次：``Invoke-GrokFrontendPerpetualDrive.ps1``",
        "喊停：``$stopFlag``",
        "",
        "completion_claim_allowed: **false**"
    ) | Set-Content -LiteralPath $md -Encoding UTF8
}

$loop = 0
$prior = $null
if (Test-Path $latestPath) {
    try { $prior = Get-Content $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    if ($prior -and $prior.loop_index) { $loop = [int]$prior.loop_index }
}

if ($BootstrapOneLoop) {
    Write-Log "Grok Perpetual SeedLab Daemon BOOTSTRAP ONE LOOP (parallel=$MaxParallel)"
} else {
    Write-Log "Grok Perpetual SeedLab Daemon START (parallel=$MaxParallel interval=${GapScanIntervalSec}s)"
}
Write-Log "Stop: New-Item '$stopFlag'"

$gapCount = -1
while (-not (Test-Stop)) {
    $loop++
    $cycleStarted = (Get-Date).ToString("o")
    Write-Log "=== Loop #$loop ==="

    # 首圈/每圈先写 latest.json，避免长 GapScan+波次期间与 sleep 前无证据
    $priorGapCount = -1
    if ($prior -and $null -ne $prior.last_gap_count) { $priorGapCount = [int]$prior.last_gap_count }
    Save-DaemonState @{
        loop_index = $loop
        cycle_started_at = $cycleStarted
        last_gap_count = $priorGapCount
        max_parallel = $MaxParallel
        gap_scan_interval_sec = $GapScanIntervalSec
        stop_flag = $stopFlag
        bootstrap_one_loop = [bool]$BootstrapOneLoop
        status = if ($BootstrapOneLoop) { "bootstrap_one_loop" } else { "cycle_running" }
    }

    # 1 GapScan（发动机）
    $gapOk = $false
    $gapCount = -1
    try {
        & (Join-Path $bridge "Invoke-GrokFullGapScan.ps1") -Quiet | Out-Null
        $gapOk = $true
        $gapPath = Join-Path $runtime "state\full_gap_scan\latest.json"
        if (Test-Path $gapPath) {
            $g = Get-Content $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($g.gaps) { $gapCount = @($g.gaps).Count }
            elseif ($g.gap_count) { $gapCount = [int]$g.gap_count }
            else { $gapCount = 0 }
        }
        Write-Log "GapScan ok gap_count=$gapCount"
    } catch {
        Write-Log "GapScan err: $($_.Exception.Message)"
    }

    if (Test-Stop) { break }

    # 2 辅助：GDP 推队列 + pending 守护（WaveCycle 归前台 Invoke-GrokFrontendPerpetualDrive）
    try {
        & (Join-Path $bridge "Invoke-GrokGapDrivenProgressor.ps1") -PushQueue -Quiet 2>$null | Out-Null
        Write-Log "GDP PushQueue ok (aux)"
    } catch {
        Write-Log "GDP err: $($_.Exception.Message)"
    }

    if (Test-Stop) { break }

    $pending = 0
    $qPath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
    if (Test-Path $qPath) {
        $q = Get-Content $qPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($q.tasks | Where-Object { $_.status -eq "pending" }).Count
    }
    if ($pending -gt 0) {
        try {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision -Quiet 2>$null | Out-Null
            Write-Log "RunNext ok pending_was=$pending (aux guard)"
        } catch {
            Write-Log "RunNext err: $($_.Exception.Message)"
        }
    } else {
        Write-Log "RunNext skip pending=0"
    }

    $cycleStatus = if ($BootstrapOneLoop) { "bootstrap_complete" } else { "aux_running" }
    Save-DaemonState @{
        loop_index = $loop
        cycle_started_at = $cycleStarted
        cycle_finished_at = (Get-Date).ToString("o")
        last_gap_scan_at = (Get-Date).ToString("o")
        last_gap_scan_ok = $gapOk
        last_gap_count = $gapCount
        max_parallel = $MaxParallel
        gap_scan_interval_sec = $GapScanIntervalSec
        stop_flag = $stopFlag
        bootstrap_one_loop = [bool]$BootstrapOneLoop
        status = $cycleStatus
    }

    if ($BootstrapOneLoop) {
        Write-Log "BootstrapOneLoop DONE (loop=$loop gap=$gapCount)"
        break
    }

    if (Test-Stop) { break }
    Write-Log "Sleep ${GapScanIntervalSec}s ..."
    Start-Sleep -Seconds $GapScanIntervalSec
}

if (Test-Stop) {
    Save-DaemonState @{
        loop_index = $loop
        last_gap_count = $gapCount
        max_parallel = $MaxParallel
        bootstrap_one_loop = [bool]$BootstrapOneLoop
        status = "user_stop"
        stop_reason = "user_stop.flag"
    }
    Write-Log "Daemon STOPPED"
} elseif (-not $BootstrapOneLoop) {
    Save-DaemonState @{
        loop_index = $loop
        last_gap_count = $gapCount
        max_parallel = $MaxParallel
        status = "user_stop"
        stop_reason = "loop_exit"
    }
    Write-Log "Daemon STOPPED"
}
exit 0