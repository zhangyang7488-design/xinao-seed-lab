#Requires -Version 5.1
<#
.SYNOPSIS
  轮回循环默认波行为 — 可执行政策入口（continue-as-new 风格，非单轮）。
.DESCRIPTION
  读 checkpoint → 从 gap/weak_strategy 建 frontier → 最大并行在飞、完成即补开
  → 滚动验收 → 保存 checkpoint → 循环直到 hard blocker 或用户 stop。
  合同：grok_wave_cycle_default_behavior.v1.json
  实施源（不登记=已成）：桌面三份 txt（合同指针/后台搜索/动态轮回形状）
.PARAMETER MaxParallel
  子代理/工作项最大并行宽度（默认 5）。
.PARAMETER MaxCycles
  外圈 continue-as-new 次数；0=直到 frontier 空或 stop。
.PARAMETER SingleCycle
  只跑一圈（调试）。
.PARAMETER MaxItemsPerCycle
  每圈最多处理工作项数（continue-as-new 有界；默认 MaxParallel*2）。
.PARAMETER UserStopFile
  存在即停（用户喊停）。
#>
param(
    [int]$MaxParallel = 5,
    [int]$MaxCycles = 0,
    [int]$MaxItemsPerCycle = 0,
    [switch]$SingleCycle,
    [switch]$SkipPoll,
    [switch]$Quiet,
    [string]$UserStopFile = ""
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$contractPath = Join-Path $bridge "grok_wave_cycle_default_behavior.v1.json"
$contract = $null
if (Test-Path -LiteralPath $contractPath) {
    $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
if ($contract -and $contract.per_wave_mandatory_cn.max_subagent_parallel.machine_default) {
    if ($MaxParallel -eq 5) {
        $MaxParallel = [int]$contract.per_wave_mandatory_cn.max_subagent_parallel.machine_default
    }
}
$maxCap = 8
if ($contract) { $maxCap = [int]$contract.per_wave_mandatory_cn.max_subagent_parallel.max }
$MaxParallel = [math]::Max(2, [math]::Min($maxCap, $MaxParallel))
if ($MaxItemsPerCycle -le 0) { $MaxItemsPerCycle = $MaxParallel * 2 }

$stateDir = Join-Path $runtime "state\grok_wave_cycle"
$runsDir = Join-Path $stateDir "runs"
$latestPath = Join-Path $stateDir "latest.json"
if (-not $UserStopFile) {
    $UserStopFile = Join-Path $stateDir "user_stop.flag"
}
New-Item -ItemType Directory -Force -Path $stateDir, $runsDir | Out-Null

function Write-Log([string]$Msg) {
    if (-not $Quiet) { Write-Host $Msg }
}

function Test-UserStop {
    return (Test-Path -LiteralPath $UserStopFile)
}

function Read-JsonSafe([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-CheckpointBrief {
    $cp = Read-JsonSafe (Join-Path $runtime "state\grok_session_context\latest.json")
    if (-not $cp) { return "无 prior checkpoint" }
    $brief = ""
    if ($cp.session_resume_brief_cn) { $brief = [string]$cp.session_resume_brief_cn }
    elseif ($cp.resume_brief_cn) { $brief = [string]$cp.resume_brief_cn }
    return $brief
}

function Invoke-WorkItem([object]$Item) {
    $invoke = [string]$Item.invoke
    $id = [string]$Item.id
    $started = (Get-Date).ToString("o")
    $result = [ordered]@{
        id         = $id
        source     = [string]$Item.source
        title_cn   = [string]$Item.title_cn
        invoke     = $invoke
        started_at = $started
        status     = "unknown"
    }
    try {
        if ($invoke -match 'Invoke-Grok') {
            $scriptName = ($invoke -split '\s')[0]
            $scriptPath = Join-Path $bridge $scriptName
            if (-not (Test-Path -LiteralPath $scriptPath)) { throw "Script missing: $scriptName" }
            if ($invoke -match '-Quiet') {
                & $scriptPath -Quiet 2>$null | Out-Null
            } else {
                & $scriptPath -Quiet | Out-Null
            }
            $result.status = "done"
            $result.outcome = "invoke_ok"
        }
        elseif ($invoke -match 'temporal') {
            $evDir = Join-Path $runtime "state\temporal_mainline_probe"
            New-Item -ItemType Directory -Force -Path $evDir | Out-Null
            $wfOut = ""
            try { $wfOut = (temporal workflow list --address 127.0.0.1:7233 2>&1 | Out-String).Trim() } catch { $wfOut = $_.Exception.Message }
            @{ schema_version = "xinao.temporal_mainline_probe.v1"; generated_at = (Get-Date).ToString("o"); workflow_list_excerpt = $wfOut.Substring(0, [Math]::Min(2000, [Math]::Max(0, $wfOut.Length))); via = "wave_cycle" } |
                ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evDir "latest.json") -Encoding UTF8
            $result.status = "done"
            $result.outcome = "temporal_probe_ok"
        }
        elseif ($id -match 'gap_|WEAK_STRATEGY') {
            & (Join-Path $bridge "Invoke-GrokFullGapScan.ps1") -Quiet | Out-Null
            $result.status = "done"
            $result.outcome = "gap_rescan_ok"
        }
        else {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision -Quiet 2>$null | Out-Null
            $result.status = "done"
            $result.outcome = "run_next_ok"
        }
    } catch {
        $result.status = "blocked"
        $result.outcome = "error"
        $result.error = $_.Exception.Message
    }
    $result.finished_at = (Get-Date).ToString("o")
    $result.verdict = if ($result.status -eq "done") { "accept_evidence_pending" } else { "reject_blocker" }
    return [pscustomobject]$result
}

function Build-FrontierQueue {
    # refresh sources
    if (-not $SkipPoll) {
        & (Join-Path $bridge "Invoke-GrokWeakStrategyScan.ps1") -Quiet 2>$null | Out-Null
        & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet 2>$null | Out-Null
        $dyn = Join-Path $bridge "Invoke-GrokDynamicRoiFromIntent.ps1"
        if (Test-Path $dyn) { & $dyn -MaxTasks 8 -Quiet | Out-Null }
    }

    $queue = [System.Collections.Generic.List[object]]::new()
    $seen = @{}

    function Enqueue([string]$Id, [string]$Source, [string]$Title, [string]$Invoke, [int]$Pri) {
        if ($seen.ContainsKey($Id)) { return }
        $seen[$Id] = $true
        [void]$queue.Add([pscustomobject]@{
            id = $Id; source = $Source; title_cn = $Title; invoke = $Invoke; priority = $Pri
        })
    }

    $gap = Read-JsonSafe (Join-Path $runtime "state\holographic_gap\latest.json")
    if ($gap -and $gap.named_gaps) {
        foreach ($ng in @($gap.named_gaps | Where-Object { $_ })) {
            Enqueue "gap_$ng" "holographic_gap" "修差距：$ng" "Invoke-GrokFullGapScan.ps1" 95
        }
    }

    $weak = Read-JsonSafe (Join-Path $runtime "state\weak_strategy_scan\latest.json")
    if ($weak -and $weak.gaps) {
        foreach ($w in @($weak.gaps)) {
            $wid = [string]$w.id
            if (-not $wid) { continue }
            $title = if ($w.problem_cn) { [string]$w.problem_cn } else { $wid }
            $action = if ($w.next_action_cn) { [string]$w.next_action_cn } else { "弱策略修" }
            Enqueue $wid "weak_strategy" "$title → $action" "Invoke-GrokWeakStrategyScan.ps1" 92
        }
    }

    $roi = Read-JsonSafe (Join-Path $runtime "state\dynamic_roi\latest.json")
    if ($roi -and $roi.current_tasks) {
        foreach ($t in @($roi.current_tasks)) {
            $tid = "roi_$($t.order)_$($t.goal_id)"
            Enqueue $tid "dynamic_roi" [string]$t.title_cn [string]$t.invoke 88
        }
    }

    $vision = Read-JsonSafe (Join-Path $runtime "state\vision_mega_package\latest.json")
    if ($vision -and $vision.items) {
        foreach ($it in @($vision.items | Where-Object { $_.status -in @("contracted", "partial", "open", "in_progress") })) {
            Enqueue "vision_$($it.id)" "vision" [string]$it.title_cn "Invoke-GrokVisionMegaPackageTrueTest.ps1" 85
        }
    }

    # 公理兜底：P0 未闭合永远有活（波内用快 handler，长等待续波由 RunNext/主脑 spawn）
    Enqueue "axiom_p0_honest" "p0_axiom" "P0诚实 now_can" "Invoke-GrokRoiP0HonestNowCan.ps1" 99
    Enqueue "axiom_333_intake" "p0_axiom" "333 intake 续跑" "Invoke-GrokTaskEntry.ps1" 98
    Enqueue "axiom_333_claim" "p0_axiom" "333 durable claim" "Invoke-GrokTaskEntryClaimDurable.ps1" 97
    Enqueue "axiom_333_wave_status" "p0_axiom" "333 WaveStatus 读回" "Invoke-GrokTaskEntryWaveStatus.ps1" 96

    return @($queue | Sort-Object { - $_.priority })
}

function Invoke-ParallelPool([object[]]$Frontier, [int]$Width, [int]$ItemCap) {
    $pending = [System.Collections.Generic.Queue[object]]::new()
    $enqueued = 0
    foreach ($f in $Frontier) {
        if ($enqueued -ge $ItemCap) { break }
        $pending.Enqueue($f)
        $enqueued++
    }
    $inFlight = @{}
    $completed = [System.Collections.Generic.List[object]]::new()
    $jobScript = {
        param($Bridge, $ItemJson)
        $item = $ItemJson | ConvertFrom-Json
        $invoke = [string]$item.invoke
        $id = [string]$item.id
        $row = [ordered]@{ id = $id; source = [string]$item.source; title_cn = [string]$item.title_cn; invoke = $invoke; started_at = (Get-Date).ToString("o") }
        try {
            if ($invoke -match '^Invoke-Grok') {
                $scriptName = ($invoke -split '\s')[0]
                $scriptPath = Join-Path $Bridge $scriptName
                if ($scriptName -match 'TaskEntry\.ps1$') {
                    & $scriptPath -Intent "WaveCycle 333续跑·completion_claim=false" -Quiet 2>$null | Out-Null
                } else {
                    & $scriptPath -Quiet 2>$null | Out-Null
                }
                $row.status = "done"; $row.outcome = "invoke_ok"
            } elseif ($invoke -match 'temporal') {
                $row.status = "done"; $row.outcome = "temporal_stub_ok"
            } else {
                & (Join-Path $Bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision -Quiet 2>$null | Out-Null
                $row.status = "done"; $row.outcome = "run_next_ok"
            }
        } catch {
            $row.status = "blocked"; $row.error = $_.Exception.Message; $row.outcome = "error"
        }
        $row.finished_at = (Get-Date).ToString("o")
        $row.verdict = if ($row.status -eq "done") { "accept_evidence_pending" } else { "reject_blocker" }
        return [pscustomobject]$row
    }

    while ($pending.Count -gt 0 -or $inFlight.Count -gt 0) {
        if (Test-UserStop) { break }
        while ($inFlight.Count -lt $Width -and $pending.Count -gt 0) {
            $next = $pending.Dequeue()
            $job = Start-Job -ScriptBlock $jobScript -ArgumentList $bridge, ($next | ConvertTo-Json -Compress -Depth 4)
            $inFlight[$job.Id] = @{ job = $job; item = $next }
        }
        if ($inFlight.Count -eq 0) { break }
        $done = Wait-Job -Job @($inFlight.Values.job) -Any
        foreach ($kv in @($inFlight.GetEnumerator())) {
            $j = $kv.Value.job
            if ($j.State -eq "Completed" -or $j.State -eq "Failed") {
                $res = $null
                try { $res = Receive-Job $j } catch { $res = [pscustomobject]@{ id = $kv.Value.item.id; status = "blocked"; error = $_.Exception.Message } }
                [void]$completed.Add($res)
                Remove-Job $j -Force -ErrorAction SilentlyContinue
                [void]$inFlight.Remove($kv.Key)
            }
        }
        # 工作守恒：完成即补开已在 while 顶部处理
    }
    return @($completed)
}

function Save-CycleCheckpoint([int]$CycleIndex, [object]$CycleResult) {
    $cpScript = Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1"
    if (-not (Test-Path $cpScript)) { return }
    $inFlightN = if ($CycleResult.in_flight_peak) { $CycleResult.in_flight_peak } else { 0 }
    $doneN = @($CycleResult.completed_items).Count
    & $cpScript -Save `
        -UserIntentAnchorCn "轮回循环默认波·最大并行+完成即补开" `
        -ResumeBriefCn "WaveCycle cycle=$CycleIndex; 在飞峰值=$inFlightN; 完成=$doneN; completion_claim=false" `
        -LastMachineActions @("Invoke-GrokWaveCycleRun", "parallel_pool", "frontier_gap_weak") `
        -NextMachineActions @("续 WaveCycle", "333 claim/history", "弱策略收敛") `
        -EvidenceRefs @(
            $latestPath,
            "D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json",
            "D:\XINAO_RESEARCH_RUNTIME\state\weak_strategy_scan\latest.json"
        ) `
        -DoNotReExplain @("实现不登记=桌面三txt为源", "PASS不能停", "旁路≠333闭合") `
        -Quiet | Out-Null
}

function Invoke-OneCycle([int]$Index, [object]$PriorState) {
    Write-Log "=== WaveCycle #$Index ==="
    $cycle = [ordered]@{
        cycle_index              = $Index
        started_at               = (Get-Date).ToString("o")
        parallel_width           = $MaxParallel
        checkpoint_brief_before  = (Get-CheckpointBrief)
        steps                    = [ordered]@{}
        completion_claim_allowed = $false
    }

    if (Test-UserStop) {
        $cycle.status = "user_stop"
        $cycle.stop_reason = "user_stop.flag"
        $cycle.finished_at = (Get-Date).ToString("o")
        return $cycle
    }

    if (-not $SkipPoll) {
        Write-Log "[$Index] 0 keepalive poll (底座)"
        & (Join-Path $bridge "Invoke-GrokLongWorkflowKeepalivePoll.ps1") -Quiet | Out-Null
        $cycle.steps["0_keepalive"] = "ok"
    }

    Write-Log "[$Index] 1-2 frontier from gap + weak_strategy"
    $frontier = Build-FrontierQueue
    $cycle.steps["1_frontier_count"] = $frontier.Count
    $cycle.frontier_sample = @($frontier | Select-Object -First 6 | ForEach-Object { $_.id })

    if ($frontier.Count -eq 0) {
        $cycle.status = "frontier_empty"
        $cycle.finished_at = (Get-Date).ToString("o")
        return $cycle
    }

    $batch = @($frontier | Select-Object -First $MaxItemsPerCycle)
    Write-Log "[$Index] 3 parallel pool width=$MaxParallel items=$($batch.Count)/$($frontier.Count) (完成即补开)"
    $completed = Invoke-ParallelPool -Frontier $batch -Width $MaxParallel -ItemCap $MaxItemsPerCycle
    $cycle.completed_items = @($completed)
    $cycle.in_flight_peak = [math]::Min($MaxParallel, $batch.Count)
    $cycle.items_per_cycle_cap = $MaxItemsPerCycle
    $cycle.frontier_remaining = [math]::Max(0, $frontier.Count - $batch.Count)
    $blocked = @($completed | Where-Object { $_.status -eq "blocked" })
    $cycle.steps["3_parallel"] = [ordered]@{
        done    = @($completed | Where-Object { $_.status -eq "done" }).Count
        blocked = $blocked.Count
        total   = $completed.Count
    }

    if ($blocked.Count -gt 0 -and @($completed | Where-Object { $_.status -eq "done" }).Count -eq 0) {
        $cycle.status = "hard_blocker"
        $cycle.named_blocker = $blocked[0].error
    } else {
        $cycle.status = "cycle_done"
    }

    $cycle.finished_at = (Get-Date).ToString("o")
    Save-CycleCheckpoint -CycleIndex $Index -CycleResult $cycle
    $cycle.steps["6_checkpoint"] = "saved"
    return $cycle
}

# --- main continue-as-new loop ---
Write-Log "Grok WaveCycle Run — 合同 grok_wave_cycle_default_behavior.v1.json"
Write-Log "实施源：桌面三 txt（实现不登记）；parallel=$MaxParallel"

$prior = Read-JsonSafe $latestPath
$startCycle = 1
if ($prior -and $prior.last_cycle_index) { $startCycle = [int]$prior.last_cycle_index + 1 }

$cyclesOut = [System.Collections.Generic.List[object]]::new()
$limit = if ($SingleCycle) { 1 } elseif ($MaxCycles -gt 0) { $MaxCycles } else { 9999 }
$ran = 0
$stopReason = $null

for ($i = $startCycle; $ran -lt $limit; $i++) {
    if (Test-UserStop) { $stopReason = "user_stop"; break }
    $c = Invoke-OneCycle -Index $i -PriorState $prior
    [void]$cyclesOut.Add($c)
    $ran++
    if ($c.status -in @("user_stop", "hard_blocker")) {
        $stopReason = $c.status
        break
    }
    if ($c.status -eq "frontier_empty") { break }
    if ($SingleCycle) { break }
    if (-not $c.frontier_remaining -or [int]$c.frontier_remaining -le 0) { break }
}

$out = [ordered]@{
    schema_version           = "xinao.grok_wave_cycle_run.v1"
    sentinel                 = "SENTINEL:GROK_WAVE_CYCLE_RUN"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    contract_ref             = "grok-admin-bridge/grok_wave_cycle_default_behavior.v1.json"
    implementation_sources   = @(
        "C:\Users\xx363\Desktop\合同_默认加动态升级_指针_20260710.txt",
        "C:\Users\xx363\Desktop\后台免费本地搜索_成熟选型与集成_20260710.txt",
        "C:\Users\xx363\Desktop\外部成熟_动态轮回与智能派模_完整形状_20260710.txt"
    )
    implementation_not_registered_cn = "桌面三txt=实施源；本 JSON+脚本=政策入口，不等于形状已焊完"
    parallel_width           = $MaxParallel
    continue_as_new          = $true
    cycles_ran               = $ran
    last_cycle_index         = if ($cyclesOut.Count -gt 0) { $cyclesOut[-1].cycle_index } else { 0 }
    stop_reason              = $stopReason
    cycles                   = @($cyclesOut)
    now_can_invoke           = @(
        "cd $bridge",
        ".\Invoke-GrokWaveCycleRun.ps1",
        ".\Invoke-GrokWaveCycleRun.ps1 -MaxParallel 5 -MaxCycles 3",
        ".\Invoke-GrokWaveCycleRun.ps1 -SingleCycle",
        "New-Item -ItemType File -Path '$UserStopFile'  # 用户喊停"
    )
}
$out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8
$runFile = Join-Path $runsDir ("run_{0}.json" -f (Get-Date).ToString("yyyyMMdd_HHmmss"))
$out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $runFile -Encoding UTF8

$md = Join-Path $runtime "readback\zh\grok_wave_cycle_latest.md"
New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
$last = if ($cyclesOut.Count -gt 0) { $cyclesOut[-1] } else { $null }
@(
    "# 轮回循环默认波",
    "",
    "时间：$((Get-Date).ToString('o'))",
    "并行宽度：**$MaxParallel** · continue-as-new：**是**",
    "圈数：$ran · 停因：$(if ($stopReason) { $stopReason } else { 'frontier_done_or_limit' })",
    "",
    "**实现不登记**：形状实施源=桌面三 txt；本跑=政策执行入口。",
    "",
    "证据：``$latestPath``",
    "",
    "completion_claim_allowed: **false**"
) | Set-Content -LiteralPath $md -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 6 }
Write-Log "OK → $latestPath"
exit 0