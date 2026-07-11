#Requires -Version 5.1
<#
.SYNOPSIS
  前台永续驱动：主窗口决策+脚本驱动（非 daemon 替代）。
.DESCRIPTION
  合同：grok_frontend_perpetual_drive.v1.json
  一圈：FullGapScan → Pool Pulse → WaveCycle 单圈 → RunNext×N → checkpoint
  默认后置：写 post_action_required=true，主 Grok 下回合必须再跑本脚本。
.PARAMETER MaxParallel
  波次/补位最大并行（默认 8）。
.PARAMETER SingleCycle
  只跑一圈后退出（仍写 post_action_required，供主会话续跑）。
.PARAMETER Continue
  前台自己 while 续圈，直到 user_stop.flag。
.PARAMETER RunNextPasses
  每圈 RunNext 次数（默认 3）。
#>
param(
    [int]$MaxParallel = 8,
    [switch]$SingleCycle,
    [switch]$Continue,
    [int]$RunNextPasses = 3,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateDir = Join-Path $runtime "state\frontend_perpetual_drive"
$latestPath = Join-Path $stateDir "latest.json"
$stopFlag = Join-Path $runtime "state\grok_perpetual_daemon\user_stop.flag"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Write-Log([string]$Msg) {
    if (-not $Quiet) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] [FRONT] $Msg" }
}

function Test-Stop { return (Test-Path -LiteralPath $stopFlag) }

function Save-DriveState([hashtable]$State) {
    $State.generated_at = (Get-Date).ToString("o")
    $State.schema_version = "xinao.grok_frontend_perpetual_drive_run.v1"
    $State.sentinel = "SENTINEL:GROK_FRONTEND_PERPETUAL_DRIVE"
    $State.completion_claim_allowed = $false
    $State.role_cn = "前台主窗口=决策+脚本驱动；daemon=辅助"
    $State.default_post_action_cn = "GapScan+WaveCycle 完成后自动重复本驱动，直至用户明确停止"
    $State.default_closing_action_cn = "下回合默认再 Invoke-GrokFrontendPerpetualDrive.ps1 -SingleCycle"
    if (-not $State.ContainsKey("post_action_required")) {
        $State.post_action_required = (-not (Test-Stop))
    }
    $State | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8
    $md = Join-Path $runtime "readback\zh\frontend_perpetual_drive_latest.md"
    New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
    @(
        "# 前台永续驱动",
        "",
        "时间：$($State.generated_at)",
        "圈次：**$($State.cycle_index)** · post_action_required：**$($State.post_action_required)**",
        "gap_semantic：**$($State.semantic_gap_count)** · pending：**$($State.queue_pending)**",
        "",
        "下回合主 Grok **必须**再跑：``Invoke-GrokFrontendPerpetualDrive.ps1 -SingleCycle``",
        "喊停：``$stopFlag``",
        "",
        "completion_claim_allowed: **false**"
    ) | Set-Content -LiteralPath $md -Encoding UTF8
}

function Invoke-OneFrontendCycle([int]$Index) {
    $started = (Get-Date).ToString("o")
    $steps = [ordered]@{}
    $semanticGap = -1
    $pending = -1

    Write-Log "=== Frontend Drive #$Index ==="
    Save-DriveState @{
        cycle_index = $Index
        cycle_started_at = $started
        status = "cycle_running"
        max_parallel = $MaxParallel
    }

    if (Test-Stop) { return @{ status = "user_stop"; steps = $steps } }

    try {
        & (Join-Path $bridge "Invoke-GrokFullGapScan.ps1") -Quiet | Out-Null
        $gPath = Join-Path $runtime "state\full_gap_scan\latest.json"
        if (Test-Path $gPath) {
            $g = Get-Content $gPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $semanticGap = [int]$g.semantic_gap_count
        }
        $steps["gap_scan"] = "ok"
        Write-Log "GapScan ok semantic_gap=$semanticGap"
    } catch {
        $steps["gap_scan"] = "err:$($_.Exception.Message)"
        Write-Log "GapScan err: $($_.Exception.Message)"
    }

    if (Test-Stop) { return @{ status = "user_stop"; steps = $steps; semantic_gap_count = $semanticGap } }

    try {
        & (Join-Path $bridge "Invoke-GrokSubagentPoolOrchestrator.ps1") -Action Pulse -MaxParallel $MaxParallel -Quiet | Out-Null
        $steps["pool_pulse"] = "ok"
        Write-Log "Pool pulse ok"
    } catch {
        $steps["pool_pulse"] = "err:$($_.Exception.Message)"
        Write-Log "Pool pulse err: $($_.Exception.Message)"
    }

    if (Test-Stop) { return @{ status = "user_stop"; steps = $steps; semantic_gap_count = $semanticGap } }

    try {
        & (Join-Path $bridge "Invoke-GrokWaveCycleRun.ps1") -MaxParallel $MaxParallel -SingleCycle -Quiet | Out-Null
        $steps["wave_cycle"] = "ok"
        Write-Log "WaveCycle single-cycle ok"
    } catch {
        $steps["wave_cycle"] = "err:$($_.Exception.Message)"
        Write-Log "WaveCycle err: $($_.Exception.Message)"
    }

    $rn = 0
    for ($p = 0; $p -lt $RunNextPasses; $p++) {
        if (Test-Stop) { break }
        try {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision -Quiet 2>$null | Out-Null
            $rn++
        } catch { }
    }
    $steps["run_next_passes"] = $rn
    Write-Log "RunNext passes=$rn"

    $qPath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
    if (Test-Path $qPath) {
        $q = Get-Content $qPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($q.tasks | Where-Object { $_.status -eq "pending" }).Count
    }

    try {
        & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
            -UserIntentAnchorCn "前台永续驱动·睡觉模式加强" `
            -ResumeBriefCn "front#$Index gap=$semanticGap pending=$pending parallel=$MaxParallel" `
            -LastMachineActions @("FrontendDrive", "FullGapScan", "PoolPulse", "WaveCycle", "RunNext") `
            -NextMachineActions @("再跑FrontendDrive", "Task补满spawn_directives") `
            -EvidenceRefs @(
                (Join-Path $runtime "state\full_gap_scan\latest.json"),
                (Join-Path $runtime "state\subagent_pool\latest.json"),
                (Join-Path $runtime "state\grok_wave_cycle\latest.json")
            ) `
            -DoNotReExplain @("禁止停等确认", "post_action_required=true", "daemon仅辅助") `
            -Quiet | Out-Null
        $steps["checkpoint"] = "saved"
    } catch {
        $steps["checkpoint"] = "err"
    }

    return @{
        status = "cycle_done"
        steps = $steps
        semantic_gap_count = $semanticGap
        queue_pending = $pending
    }
}

$cycle = 0
if (Test-Path $latestPath) {
    try {
        $prior = Get-Content $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($prior.cycle_index) { $cycle = [int]$prior.cycle_index }
    } catch { }
}

do {
    $cycle++
    $result = Invoke-OneFrontendCycle -Index $cycle
    $postRequired = (-not (Test-Stop)) -and ($result.status -ne "user_stop")
    Save-DriveState @{
        cycle_index = $cycle
        cycle_finished_at = (Get-Date).ToString("o")
        status = $result.status
        steps = $result.steps
        semantic_gap_count = $result.semantic_gap_count
        queue_pending = $result.queue_pending
        max_parallel = $MaxParallel
        post_action_required = $postRequired
        next_invoke = "Invoke-GrokFrontendPerpetualDrive.ps1 -SingleCycle -MaxParallel $MaxParallel"
        spawn_pool_ref = "D:\XINAO_RESEARCH_RUNTIME\state\subagent_pool\latest.json"
    }
    if ($SingleCycle -or $result.status -eq "user_stop") { break }
} while ($Continue -and -not (Test-Stop))

if (-not $Quiet) {
    Get-Content $latestPath -Raw -Encoding UTF8
}
exit 0