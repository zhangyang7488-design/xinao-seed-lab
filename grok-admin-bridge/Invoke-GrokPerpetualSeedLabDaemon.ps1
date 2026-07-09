#Requires -Version 5.1
<#
.SYNOPSIS
  永续 Seed Lab 守护：GapScan → WaveCycle → Pool Pulse → RunNext → checkpoint → 循环。
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
        "now_can：持续扫差距→波次焊主路→写证据。喊停：``$stopFlag``",
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

    # 1.5 参考 invoke 链（睡觉.txt 热路径；非登记）
    $refChain = @(
        @{ name = "StartXinaoMcpHttp"; script = "Invoke-GrokStartXinaoMcpHttp.ps1"; args = @() },
        @{ name = "ScanStack-PolicyScan"; script = "Invoke-GrokScanStack.ps1"; args = @("-PolicyScan") },
        @{ name = "StateSenseMax"; script = "Invoke-GrokStateSenseMax.ps1"; args = @() },
        @{ name = "GapDrivenProgressor"; script = "Invoke-GrokGapDrivenProgressor.ps1"; args = @("-PushQueue") },
        @{ name = "OpenHandsSmoke"; script = "Invoke-GrokOpenHandsSmokeWhenDocker.ps1"; args = @() },
        @{ name = "ExposedToolsCatalog"; script = "Invoke-GrokExposedToolsCatalog.ps1"; args = @("-RefreshRegistry") }
    )
    foreach ($step in $refChain) {
        if (Test-Stop) { break }
        $sp = Join-Path $bridge $step.script
        if (-not (Test-Path -LiteralPath $sp)) {
            Write-Log "RefChain skip missing: $($step.script)"
            continue
        }
        try {
            if ($step.args -contains "-Quiet") {
                & $sp @($step.args) -Quiet 2>$null | Out-Null
            } else {
                & $sp @($step.args) -Quiet 2>$null | Out-Null
            }
            Write-Log "RefChain ok: $($step.name)"
        } catch {
            Write-Log "RefChain err $($step.name): $($_.Exception.Message)"
        }
    }

    if (Test-Stop) { break }

    # 2 子代理池 pulse（meta 补位指令）
    try {
        & (Join-Path $bridge "Invoke-GrokSubagentPoolOrchestrator.ps1") -Action Pulse -MaxParallel $MaxParallel -Quiet | Out-Null
        Write-Log "Pool pulse ok"
    } catch {
        Write-Log "Pool pulse err: $($_.Exception.Message)"
    }

    if (Test-Stop) { break }

    # 3 波次（continue-as-new 单圈/圈，外 while 永续）
    try {
        & (Join-Path $bridge "Invoke-GrokWaveCycleRun.ps1") -MaxParallel $MaxParallel -SingleCycle -Quiet | Out-Null
        Write-Log "WaveCycle single-cycle ok"
    } catch {
        Write-Log "WaveCycle err: $($_.Exception.Message)"
    }

    if (Test-Stop) { break }

    # 4 长久工作流推进一步
    try {
        & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision -Quiet 2>$null | Out-Null
        Write-Log "RunNext ok"
    } catch {
        Write-Log "RunNext err: $($_.Exception.Message)"
    }

    # 5 checkpoint
    try {
        & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
            -UserIntentAnchorCn "永续守护·GapScan驱动波次焊333" `
            -ResumeBriefCn "daemon loop=$loop gap=$gapCount parallel=$MaxParallel" `
            -LastMachineActions @("PerpetualDaemon", "FullGapScan", "WaveCycle", "RunNext") `
            -NextMachineActions @("续daemon", "按top_fix焊", "最大并行补位") `
            -EvidenceRefs @(
                (Join-Path $runtime "state\full_gap_scan\latest.json"),
                (Join-Path $runtime "state\grok_wave_cycle\latest.json"),
                (Join-Path $runtime "state\subagent_pool\latest.json")
            ) `
            -DoNotReExplain @("禁止停等确认", "假绿禁止", "PASS不能停") `
            -Quiet | Out-Null
    } catch { }

    $cycleStatus = if ($BootstrapOneLoop) { "bootstrap_complete" } else { "running" }
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