#Requires -Version 5.1
<#
.SYNOPSIS
  动态收益任务 = 对准用户/P0意图 + 外部成熟路径，拆成当前任务逐步推进。
  成熟形状（照搬，不发明）：Goal → 成熟做法/施工包 invoke → backlog → 逐步 RunNext。
  权威：工具胶水宪法施工包 V2 0-7 + 总稿「动态收益=自举+建设」。
#>
param(
    [string]$Intent = "",
    [int]$MaxTasks = 5,
    [switch]$SeedQueue,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\dynamic_roi"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latestPath = Join-Path $outDir "latest.json"
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"

# --- 意图源：用户句 / 愿景未闭合 / P0 未闭合公理 ---
$goals = [System.Collections.Generic.List[object]]::new()

if ($Intent) {
    [void]$goals.Add([ordered]@{ id = "user_intent"; title_cn = $Intent; source = "user"; priority = 100 })
}

$visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
if (Test-Path $visionPath) {
    $v = Get-Content $visionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($it in @($v.items | Where-Object { $_.status -in @("contracted", "partial", "open", "in_progress") })) {
        [void]$goals.Add([ordered]@{
            id = [string]$it.id; title_cn = [string]$it.title_cn; source = "vision"; priority = 90
            accept_cn = [string]$it.accept_cn
        })
    }
}

# P0 未闭合 = 永远有目标（施工包/宪法）
[void]$goals.Add([ordered]@{
    id = "p0_build_333"; title_cn = "P0建设333：成熟底座真交付（intake→claim→history）"
    source = "p0_axiom"; priority = 95
})
[void]$goals.Add([ordered]@{
    id = "p0_honest_invoke"; title_cn = "P0诚实：now_can_invoke/谁决策/哪层partial"
    source = "p0_axiom"; priority = 88
})

# 差距 named
$gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
if (Test-Path $gapPath) {
    $g = Get-Content $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($ng in @($g.named_gaps | Where-Object { $_ })) {
        [void]$goals.Add([ordered]@{
            id = "gap_$ng"; title_cn = "修差距：$ng"; source = "holographic_gap"; priority = 92
        })
    }
}

# --- 外部成熟映射（照搬施工包 V2 0-7，不手搓新编排）---
# 每个目标 → 成熟步骤串（已是公开/合同内成熟路径）
function Get-MatureStepsForGoal([object]$Goal) {
    $steps = [System.Collections.Generic.List[object]]::new()
    $gid = [string]$Goal.id
    $title = [string]$Goal.title_cn

    # 默认：333 主路成熟链（施工包）
    $default333 = @(
        @{ step = "0_entry"; title = "入口投递"; invoke = "Invoke-GrokTaskEntry.ps1"; intent = $title; mature = "施工包V2步0 薄壳入口" }
        @{ step = "3_claim"; title = "耐久认领"; invoke = "Invoke-GrokTaskEntryClaimDurable.ps1"; intent = ""; mature = "施工包V2步3 Temporal Client/claim" }
        @{ step = "7_continue"; title = "续波看history"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1"; intent = ""; mature = "施工包V2步7 Continue/history" }
        @{ step = "history"; title = "Temporal history摘录"; invoke = "temporal_workflow_list"; intent = ""; mature = "Temporal UI/CLI 成熟观测" }
    )

    if ($gid -match 'p0_honest|honest_invoke') {
        [void]$steps.Add(@{ step = "honest"; title = "P0诚实now_can"; invoke = "Invoke-GrokRoiP0HonestNowCan.ps1"; intent = $title; mature = "证据/readback 成熟口径" })
        return $steps
    }
    if ($gid -match '^V01' -or $gid -match 'vision' -or $gid -match '^V') {
        [void]$steps.Add(@{ step = "vision_test"; title = "愿景真测 $gid"; invoke = "Invoke-GrokVisionMegaPackageTrueTest.ps1"; intent = $title; mature = "愿景大包真测门" })
        foreach ($s in $default333) { [void]$steps.Add($s) }
        return $steps
    }
    if ($gid -match '^gap_') {
        [void]$steps.Add(@{ step = "gap_scan"; title = $title; invoke = "Invoke-GrokFullGapScan.ps1"; intent = ""; mature = "强制全量差距扫描" })
        foreach ($s in $default333) { [void]$steps.Add($s) }
        return $steps
    }
    # p0_build_333 / user_intent / default
    foreach ($s in $default333) {
        $copy = @{ step = $s.step; title = $s.title; invoke = $s.invoke; intent = $(if ($s.intent) { $s.intent } else { $title }); mature = $s.mature }
        if ($s.step -eq "0_entry") { $copy.intent = "动态收益：$title" }
        [void]$steps.Add($copy)
    }
    return $steps
}

# 排序目标，取最高优先，拆步骤
$rankedGoals = @($goals | Sort-Object { - [int]$_.priority })
$tasks = [System.Collections.Generic.List[object]]::new()
$seen = @{}
$n = 0
foreach ($goal in $rankedGoals) {
    if ($n -ge $MaxTasks) { break }
    $steps = Get-MatureStepsForGoal $goal
    foreach ($st in $steps) {
        if ($n -ge $MaxTasks) { break }
        $key = "$($st.invoke)|$($st.step)|$($goal.id)"
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $n++
        [void]$tasks.Add([ordered]@{
            order          = $n
            goal_id        = $goal.id
            goal_title_cn  = $goal.title_cn
            goal_source    = $goal.source
            step           = $st.step
            title_cn       = "[$($goal.id)] $($st.title)"
            invoke         = $st.invoke
            intent         = $st.intent
            mature_source  = $st.mature
            why_roi_cn     = "对准意图「$($goal.title_cn)」；成熟路径=$($st.mature)；逐步推进不空转"
        })
    }
}

$out = [ordered]@{
    schema_version           = "xinao.dynamic_roi_from_intent.v1"
    sentinel                 = "SENTINEL:DYNAMIC_ROI_FROM_INTENT"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    shape_cn                 = "意图/目标 → 外部成熟路径(施工包0-7等) → 当前任务列表 → 逐步 RunNext"
    mature_not_invented_cn   = "不发明新编排；照搬施工包V2与总稿动态收益定义"
    goals_ranked             = @($rankedGoals)
    current_tasks            = @($tasks)
    next_single_task         = if ($tasks.Count -gt 0) { $tasks[0] } else { $null }
    now_can_invoke           = @(
        ".\Invoke-GrokDynamicRoiFromIntent.ps1 -SeedQueue",
        ".\Invoke-GrokSelfRotateLoop.ps1 -Cycles 1",
        ".\Invoke-GrokLongWorkflowRunNext.ps1"
    )
}
$out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8

if ($SeedQueue -and $tasks.Count -gt 0) {
    $wave = 40
    if (Test-Path $queuePath) {
        $q0 = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $mx = @($q0.tasks | ForEach-Object { [int]$_.wave } | Measure-Object -Maximum).Maximum
        if ($mx) { $wave = [int]$mx + 1 }
    }
    $prio = 400
    $newTasks = foreach ($t in $tasks) {
        $suf = "dyn_$($t.order)_$($t.step)" -replace '[^a-zA-Z0-9_]', '_'
        $row = [ordered]@{
            id         = "W${wave}_$suf"
            wave       = $wave
            priority   = $prio
            status     = "pending"
            title_cn   = $t.title_cn
            invoke     = $t.invoke
            intent     = $t.intent
            source     = "dynamic_roi_from_intent"
            why_roi_cn = $t.why_roi_cn
            mature     = $t.mature_source
            goal_id    = $t.goal_id
            handler    = switch -Regex ($t.step) {
                "honest" { "roi_p0_honest" }
                "0_entry|entry" { "roi_333_intake" }
                "3_claim|claim" { "roi_333_claim" }
                "7_continue|continue" { "roi_333_continue" }
                "history" { "roi_temporal_history" }
                "vision" { "roi_vision_true_test" }
                "gap" { "roi_gap" }
                default { "roi_333_intake" }
            }
        }
        $prio++
        [pscustomobject]$row
    }
    if (Test-Path $queuePath) {
        $q = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($q.tasks | Where-Object { $_.status -eq "pending" })
        if ($pending.Count -eq 0) {
            $q.tasks = @($q.tasks) + @($newTasks)
            $q.updated_at = (Get-Date).ToString("o")
            $q.scope_cn = "动态收益·意图→成熟路径·Wave$wave"
            $q | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $queuePath -Encoding UTF8
            $out.seeded = $true
            $out.wave = $wave
        } else {
            $out.seeded = $false
            $out.seed_skip_cn = "已有 pending，不重复种；先 RunNext 消化"
        }
    } else {
        @{
            schema_version = "xinao.grok_long_workflow_task_queue.v1"
            updated_at     = (Get-Date).ToString("o")
            execution_mode = "autonomous_continuous"
            scope_cn       = "动态收益·意图→成熟路径·Wave$wave"
            tasks          = @($newTasks)
        } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $queuePath -Encoding UTF8
        $out.seeded = $true
        $out.wave = $wave
    }
    $out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8
}

if (-not $Quiet) { $out | ConvertTo-Json -Depth 8 }
exit 0
