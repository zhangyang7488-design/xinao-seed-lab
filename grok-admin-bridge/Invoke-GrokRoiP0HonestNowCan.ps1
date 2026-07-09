#Requires -Version 5.1
<#
.SYNOPSIS
  P0 未闭合时的诚实 now_can_invoke 落盘（总稿/施工包尺：差距缩小+能 invoke，非宣布闭合）。
#>
param([switch]$Quiet)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\roi_self_loop"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$path = Join-Path $outDir "p0_honest_now_can_latest.json"

$gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
$visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
$roiPath = Join-Path $outDir "latest.json"
$tePath = Join-Path $runtime "state\task_entry\latest.json"
$composePath = Join-Path $runtime "state\xinao_base_compose\latest.json"

$gap = $null; if (Test-Path $gapPath) { $gap = Get-Content $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json }
$vision = $null; if (Test-Path $visionPath) { $vision = Get-Content $visionPath -Raw -Encoding UTF8 | ConvertFrom-Json }
$roi = $null; if (Test-Path $roiPath) { $roi = Get-Content $roiPath -Raw -Encoding UTF8 | ConvertFrom-Json }

$temporalUp = $false
try {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
    $temporalUp = [bool]$tcp.TcpTestSucceeded
} catch {}

$visionOpen = @()
if ($vision -and $vision.items) {
    $visionOpen = @($vision.items | Where-Object { $_.status -ne "landed" } | ForEach-Object { "$($_.id):$($_.status)" })
}

$layers = [ordered]@{
    "语义_五目标钉死"     = "contracted_partial · 合同在；完整自洽/自修复/自进化未闭合"
    "架构_Temporal栈"     = if ($temporalUp) { "partial · 7233 通；worker/history 真交付仍要每轮验证" } else { "red · 7233 不通" }
    "执行_队列真推进"     = "partial · ROI自转已接线；禁止巡检冒充推进"
    "证据_D盘who_weld"    = if ($gap) { "partial · gap 可扫；completion_claim_allowed=false" } else { "missing gap" }
    "采纳_runtime"        = "partial · 不得 claim P0 闭合"
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
    ".\Invoke-GrokHolographicGapScan.ps1   # 图景vs事实；全绿≠P0闭合"
)

$out = [ordered]@{
    schema_version           = "xinao.p0_honest_now_can.v1"
    sentinel                 = "SENTINEL:P0_HONEST_NOW_CAN"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    authority_cn             = @(
        "桌面\工具胶水宪法\XINAO_施工包前置_全息语义_v1_20260709.txt",
        "桌面\工具胶水宪法\XINAO_P0_333_成熟生产级底座完整施工包_V2_20260709.txt",
        "桌面\工具胶水宪法\新系统独立并行_自由发散外部研究总稿_20260701.txt"
    )
    axiom_cn                 = "P0未闭合⇒永远有任务。施工包全绿只是图景-事实红格清空，不是P0完成。"
    p0_honesty_cn            = "P0 完整自治/自修复/自进化仍建设期"
    layers_partial_cn        = $layers
    who_decides_cn           = $whoDecides
    now_can_invoke           = $nowCan
    vision_not_landed        = $visionOpen
    holographic_gap_clear    = if ($gap) { (@($gap.named_gaps).Count -eq 0) } else { $null }
    temporal_7233            = $temporalUp
    roi_seed_task_count      = if ($roi -and $roi.seed_tasks) { @($roi.seed_tasks).Count } else { 0 }
    next_work_cn             = "按施工包0-7：intake→claim→worker/history→readback；用 ROI seed_tasks 自转，禁止9条巡检"
}
$out | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path -Encoding UTF8
# also copy as human brief
$md = Join-Path $runtime "readback\zh\p0_honest_now_can_latest.md"
New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
@(
    "# P0 诚实 now_can_invoke",
    "",
    "生成：$((Get-Date).ToString('o'))",
    "",
    "- completion_claim_allowed: **false**",
    "- 公理：P0未闭合 ⇒ 永远有任务",
    "- Temporal 7233: $temporalUp",
    "- 愿景未 landed: $($visionOpen -join ', ')",
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

if (-not $Quiet) { $out | ConvertTo-Json -Depth 6 }
exit 0
