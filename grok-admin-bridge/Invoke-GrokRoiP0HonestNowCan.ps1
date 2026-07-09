#Requires -Version 5.1
<#
.SYNOPSIS
  P0 未闭合时的诚实 now_can_invoke 落盘（总稿/施工包尺：差距缩小+能 invoke，非宣布闭合）。
  wave11+：五目标各一条可验证 partial 证据或诚实 blocker。
#>
param([switch]$Quiet)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\roi_self_loop"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$path = Join-Path $outDir "p0_honest_now_can_latest.json"

function Read-JsonSafe([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    try { return Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

$gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
$visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
$roiPath = Join-Path $outDir "latest.json"
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$regPath = Join-Path $runtime "state\local_capability_registry\latest.json"
$fullGapPath = Join-Path $runtime "state\full_gap_scan\latest.json"
$sessionPath = Join-Path $runtime "state\grok_session_context\latest.json"
$exposedPath = Join-Path $runtime "state\exposed_tools_catalog\latest.json"
$composePath = Join-Path $runtime "state\xinao_base_compose\latest.json"

$gap = Read-JsonSafe $gapPath
$vision = Read-JsonSafe $visionPath
$roi = Read-JsonSafe $roiPath
$queue = Read-JsonSafe $queuePath
$reg = Read-JsonSafe $regPath
$fullGap = Read-JsonSafe $fullGapPath
$session = Read-JsonSafe $sessionPath
$exposed = Read-JsonSafe $exposedPath
$compose = Read-JsonSafe $composePath

$temporalUp = $false
try {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
    $temporalUp = [bool]$tcp.TcpTestSucceeded
} catch {}

$queuePending = 0
$queueBlocked = 0
$queueMode = $null
if ($queue -and $queue.tasks) {
    $queuePending = @($queue.tasks | Where-Object { $_.status -eq "pending" }).Count
    $queueBlocked = @($queue.tasks | Where-Object { $_.status -eq "blocked" }).Count
    $queueMode = [string]$queue.execution_mode
}

$hooked = 0; $unclaimed = 0; $dormant = 0; $glueMissing = 0
if ($reg -and $reg.counts) {
    $hooked = [int]$reg.counts.registered_and_hooked
    $unclaimed = [int]$reg.counts.on_disk_unclaimed
    if ($reg.counts.registered_dormant) { $dormant = [int]$reg.counts.registered_dormant }
    if ($reg.counts.glue_registry_missing) { $glueMissing = [int]$reg.counts.glue_registry_missing }
}

$exposedCount = 0
if ($exposed -and $exposed.tools) { $exposedCount = @($exposed.tools).Count }

$semanticGapCount = $null
$semanticGapId = "P0_NOT_CLOSED_HONEST"
if ($fullGap) {
    if ($null -ne $fullGap.semantic_gap_count) { $semanticGapCount = [int]$fullGap.semantic_gap_count }
    if ($fullGap.gaps_ranked -and @($fullGap.gaps_ranked).Count -gt 0) {
        $semanticGapId = [string]$fullGap.gaps_ranked[0].id
    }
}

$holographicGapClear = if ($gap) { (@($gap.named_gaps).Count -eq 0) } else { $null }
$roiSeedCount = if ($roi -and $roi.seed_tasks) { @($roi.seed_tasks).Count } else { 0 }
$sessionExists = $null -ne $session
$composeStatus = if ($compose -and $compose.status) { [string]$compose.status } else { "unknown" }

$runNextExists = Test-Path -LiteralPath (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1")
$gapScanExists = Test-Path -LiteralPath (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1")
$gdpExists = Test-Path -LiteralPath (Join-Path $bridge "Invoke-GrokGapDrivenProgressor.ps1")
$checkpointExists = Test-Path -LiteralPath (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1")

$visionOpen = @()
if ($vision -and $vision.items) {
    $visionOpen = @($vision.items | Where-Object { $_.status -ne "landed" } | ForEach-Object { "$($_.id):$($_.status)" })
}

$fiveGoalsPartial = [ordered]@{
    "自治" = [ordered]@{
        status         = "partial"
        evidence_probe = "queue_pending=$queuePending; queue_blocked=$queueBlocked; execution_mode=$queueMode; runnext_exists=$runNextExists; temporal_7233=$temporalUp"
        evidence_paths = @(
            "state/grok_long_workflow/task_queue.json",
            "grok-admin-bridge/Invoke-GrokLongWorkflowRunNext.ps1"
        )
        blocker_cn     = "非一句话→无手搓默认主路全程自治闭合；队列仍有 pending/blocked，compose=$composeStatus"
    }
    "自修复" = [ordered]@{
        status         = "partial"
        evidence_probe = "holographic_gap_clear=$holographicGapClear; gap_scan_script=$gapScanExists; gdp_script=$gdpExists; full_gap_scan_exists=$($null -ne $fullGap)"
        evidence_paths = @(
            "state/holographic_gap/latest.json",
            "state/full_gap_scan/latest.json",
            "grok-admin-bridge/Invoke-GrokGapDrivenProgressor.ps1"
        )
        blocker_cn     = "地图全绿后无统一自愈运行时闭环；blocker 仍靠轮次脚本/GDP 续跑，非 runtime_enforced 自修复"
    }
    "自进化" = [ordered]@{
        status         = "partial"
        evidence_probe = "session_context=$sessionExists; roi_seed_tasks=$roiSeedCount; checkpoint_script=$checkpointExists; queue_mode=$queueMode"
        evidence_paths = @(
            "state/grok_session_context/latest.json",
            "state/roi_self_loop/latest.json",
            "grok-admin-bridge/Invoke-GrokSessionContextCheckpoint.ps1"
        )
        blocker_cn     = "ROI 续种/检查点是薄面；非自进化主循环真交付（EVERY_WINDOW_REARCH 风险仍在）"
    }
    "全局自洽" = [ordered]@{
        status         = "partial"
        evidence_probe = "semantic_gap_count=$semanticGapCount; gap_id=$semanticGapId; completion_claim_allowed=false; holographic_map_all_green=$($fullGap.holographic_map_all_green)"
        evidence_paths = @(
            "state/full_gap_scan/latest.json",
            "state/roi_self_loop/p0_honest_now_can_latest.json",
            "grok_p0_autonomous_background_base.v1.json",
            "grok_dual_isomorphism_modular_separation.v1.json"
        )
        blocker_cn     = "holographic_gap_clear=true 只说明图景扫过；多源未 runtime 一体自洽；$semanticGapId 仍开"
    }
    "最大能力界面" = [ordered]@{
        status         = "partial"
        evidence_probe = "hooked=$hooked; unclaimed=$unclaimed; dormant=$dormant; glue_missing=$glueMissing; exposed_tools=$exposedCount"
        evidence_paths = @(
            "state/local_capability_registry/latest.json",
            "state/exposed_tools_catalog/latest.json"
        )
        blocker_cn     = "dormant=$dormant · unclaimed=$unclaimed · glue_missing=$glueMissing 仍在；未全展开可委托面"
    }
}

$layers = [ordered]@{
    "语义_五目标钉死"     = "contracted_partial · 合同在；五目标各 partial（见 five_goals_partial_cn）"
    "架构_Temporal栈"     = if ($temporalUp) { "partial · 7233 通；compose=$composeStatus；worker/history 真交付仍要每轮验证" } else { "red · 7233 不通" }
    "执行_队列真推进"     = "partial · pending=$queuePending blocked=$queueBlocked；ROI自转已接线；禁止巡检冒充推进"
    "证据_D盘who_weld"    = if ($gap) { "partial · gap 可扫；semantic_gap=$semanticGapId；completion_claim_allowed=false" } else { "missing gap" }
    "采纳_runtime"        = "partial · 不得 claim P0 闭合；$semanticGapId 仍登记"
}

$whoDecides = [ordered]@{
    "333主路事务"   = "Temporal 成熟栈（含 LangGraphPlugin 波内）；非 Grok 聊天"
    "岛旁路选种"     = "Invoke-GrokRoiSelfLoopDecide → seed_tasks；非第二 orchestrator"
    "用户对话窗"     = "Grok 4.5 dialogue；不默认队列 owner"
}

$nowCan = @(
    "cd $bridge; .\Invoke-GrokLongWorkflowRunNext.ps1   # 空队列→ROI拆真事→种 seed_tasks",
    "cd $bridge; .\Invoke-GrokRoiSelfLoopDecide.ps1",
    "cd $bridge; .\Invoke-GrokTaskEntry.ps1 -Intent '...'",
    "cd $bridge; .\Invoke-GrokTaskEntryClaimDurable.ps1",
    "浏览器 http://127.0.0.1:8080 看 Temporal history",
    ".\Invoke-GrokHolographicGapScan.ps1   # 图景vs事实；全绿≠P0闭合",
    ".\Invoke-GrokFullGapScan.ps1   # A11 诚实门；P0_NOT_CLOSED_HONEST 仍开"
)

$out = [ordered]@{
    schema_version           = "xinao.p0_honest_now_can.v1"
    sentinel                 = "SENTINEL:P0_HONEST_NOW_CAN"
    generated_at             = (Get-Date).ToString("o")
    wave_cn                  = "wave11"
    completion_claim_allowed = $false
    semantic_gap_id          = $semanticGapId
    semantic_gap_count       = $semanticGapCount
    authority_cn             = @(
        "桌面\工具胶水宪法\XINAO_施工包前置_全息语义_v1_20260709.txt",
        "桌面\工具胶水宪法\XINAO_P0_333_成熟生产级底座完整施工包_V2_20260709.txt",
        "桌面\工具胶水宪法\新系统独立并行_自由发散外部研究总稿_20260701.txt"
    )
    axiom_cn                 = "P0未闭合⇒永远有任务。施工包全绿只是图景-事实红格清空，不是P0完成。"
    p0_honesty_cn            = "P0 完整自治/自修复/自进化仍建设期"
    five_goals_partial_cn    = $fiveGoalsPartial
    layers_partial_cn        = $layers
    who_decides_cn           = $whoDecides
    now_can_invoke           = $nowCan
    vision_not_landed        = $visionOpen
    holographic_gap_clear    = $holographicGapClear
    temporal_7233            = $temporalUp
    queue_pending            = $queuePending
    queue_blocked            = $queueBlocked
    roi_seed_task_count      = $roiSeedCount
    registry_hooked          = $hooked
    registry_unclaimed       = $unclaimed
    exposed_tools_count      = $exposedCount
    next_work_cn             = "按施工包0-7：intake→claim→worker/history→readback；用 ROI seed_tasks 自转，禁止9条巡检；P0_NOT_CLOSED_HONEST 不得消号"
}
$out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $path -Encoding UTF8

$md = Join-Path $runtime "readback\zh\p0_honest_now_can_latest.md"
New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
$fiveGoalLines = $fiveGoalsPartial.GetEnumerator() | ForEach-Object {
    $g = $_.Value
    "- **$($_.Key)**（$($g.status)）：``$($g.evidence_probe)`` · blocker：$($g.blocker_cn)"
}
@(
    "# P0 诚实 now_can_invoke",
    "",
    "生成：$((Get-Date).ToString('o'))",
    "",
    "- completion_claim_allowed: **false**",
    "- 公理：P0未闭合 ⇒ 永远有任务",
    "- 唯一语义缺口：**$semanticGapId**（semantic_gap_count=$semanticGapCount）",
    "- Temporal 7233: $temporalUp",
    "- 队列 pending=$queuePending blocked=$queueBlocked",
    "- 愿景未 landed: $($visionOpen -join ', ')",
    "",
    "## 五目标 partial（可验证 · 不得闭合）",
    $fiveGoalLines,
    "",
    "## 谁决策",
    ($whoDecides.GetEnumerator() | ForEach-Object { "- **$($_.Key)**：$($_.Value)" }),
    "",
    "## 哪层 partial",
    ($layers.GetEnumerator() | ForEach-Object { "- **$($_.Key)**：$($_.Value)" }),
    "",
    "## now_can_invoke",
    ($nowCan | ForEach-Object { "- ``$_``" }),
    "",
    "证据 JSON: $path"
) | Set-Content -LiteralPath $md -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 8 }
exit 0