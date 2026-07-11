#Requires -Version 5.1
<#
.SYNOPSIS
  收益自转决策：P0 未闭合 ⇒ 永远有任务。从愿景/差距/注册表/Temporal/P0 层拆具体活。
  禁止「地图全绿 = 没事做」。供 RunNext 空队列默认调用。
#>
param(
    [switch]$Quiet,
    [int]$MaxSeed = 4
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\roi_self_loop"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latestPath = Join-Path $outDir "latest.json"

$candidates = [System.Collections.Generic.List[object]]::new()

function Add-Cand {
    param(
        [string]$Id,
        [int]$Score,
        [string]$WhyCn,
        [string]$Kind,
        [string]$Suffix,
        [string]$TitleCn,
        [string]$Invoke = "",
        [string]$Intent = "",
        [string]$Handler = ""
    )
    [void]$candidates.Add([ordered]@{
        id          = $Id
        score       = $Score
        why_roi_cn  = $WhyCn
        kind        = $Kind
        seed_suffix = $Suffix
        title_cn    = $TitleCn
        invoke      = $Invoke
        intent      = $Intent
        handler     = $Handler
    })
}

# --- axiom: P0 incomplete ---
$p0Incomplete = $true
$p0Honesty = "P0完整自洽/自修复/自进化仍建设期；completion_claim_allowed=false"
$p0Path = Join-Path $bridge "grok_p0_autonomous_background_base.v1.json"
if (Test-Path -LiteralPath $p0Path) {
    try {
        $p0 = Get-Content -LiteralPath $p0Path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($p0.p0_complete_definition_cn -and $p0.p0_complete_definition_cn.honesty) {
            $p0Honesty = [string]$p0.p0_complete_definition_cn.honesty
        }
    } catch {}
}

# --- gap ---
$gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
$gap = $null
$gapClear = $false
$namedGaps = @()
if (Test-Path -LiteralPath $gapPath) {
    $gap = Get-Content -LiteralPath $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $namedGaps = @($gap.named_gaps | Where-Object { $_ })
    $hZero = $true
    if ($gap.PSObject.Properties.Name -contains "horizontal_gap_count") {
        $hZero = ([int]$gap.horizontal_gap_count -eq 0)
    }
    $gapClear = ($namedGaps.Count -eq 0) -and $hZero
    if ($gap.PSObject.Properties.Name -contains "completion_claim_allowed" -and $gap.completion_claim_allowed -eq $true) {
        # still treat as incomplete unless explicitly closed - never true for now
        $p0Incomplete = $true
    }
}

# --- temporal ---
$temporalUp = $false
try {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
    $temporalUp = [bool]$tcp.TcpTestSucceeded
} catch { $temporalUp = $false }

# --- vision open ---
$visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
$visionOpen = @()
if (Test-Path -LiteralPath $visionPath) {
    $v = Get-Content -LiteralPath $visionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $visionOpen = @($v.items | Where-Object { $_.status -in @("contracted", "partial", "open", "in_progress") })
}

# --- registry ---
$regPath = Join-Path $runtime "state\local_capability_registry\latest.json"
$regCounts = $null
if (Test-Path -LiteralPath $regPath) {
    try {
        $reg = Get-Content -LiteralPath $regPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $regCounts = $reg.counts
    } catch {}
}

# ========== ALWAYS-ON when P0 incomplete ==========
# 用户原话：P0还没完成，怎么可能没有任务
if ($p0Incomplete) {
    Add-Cand -Id "p0_honest_now_can_invoke" -Score 100 -Kind "p0" `
        -Suffix "roi_p0_honest_now_can" -Handler "roi_p0_honest" `
        -TitleCn "P0未闭合：写诚实 now_can_invoke/谁决策/哪层 partial" `
        -WhyCn $p0Honesty `
        -Invoke "Invoke-GrokRoiP0HonestNowCan.ps1" `
        -Intent "P0五目标未闭合·诚实尺落盘"

    if ($temporalUp) {
        Add-Cand -Id "p0_333_intake_mainline" -Score 98 -Kind "service_333" `
            -Suffix "roi_333_intake" -Handler "roi_333_intake" `
            -TitleCn "P0执行层：333主路真实 task intake" `
            -WhyCn "P0执行层要求队列真推进/服务交付；地图绿≠无intake" `
            -Invoke "Invoke-GrokTaskEntry.ps1" `
            -Intent "P0未闭合·ROI：333主路 intake 一条可续跑任务·completion_claim=false"

        Add-Cand -Id "p0_333_claim_continue" -Score 96 -Kind "service_333" `
            -Suffix "roi_333_claim" -Handler "roi_333_claim" `
            -TitleCn "P0执行层：durable claim" `
            -WhyCn "intake 后必须 claim 才有 Temporal 事务" `
            -Invoke "Invoke-GrokTaskEntryClaimDurable.ps1"

        Add-Cand -Id "p0_333_continue_history" -Score 94 -Kind "service_333" `
            -Suffix "roi_333_continue" -Handler "roi_333_continue" `
            -TitleCn "P0执行层：续波+等 history" `
            -WhyCn "服务交付看 history 推进，不是端口 ping" `
            -Invoke "Invoke-GrokTaskEntryContinueWave.ps1"

        Add-Cand -Id "p0_temporal_history_evidence" -Score 92 -Kind "service_333" `
            -Suffix "roi_temporal_history" -Handler "roi_temporal_history" `
            -TitleCn "P0证据层：Temporal workflow list/history 摘录" `
            -WhyCn "证据层：who/weld/now_can 需要 history 可读" `
            -Invoke "temporal_workflow_list"
    } else {
        Add-Cand -Id "p0_repair_temporal_down" -Score 99 -Kind "repair" `
            -Suffix "roi_repair_temporal" -Handler "roi_repair_compose" `
            -TitleCn "P0前置：Temporal:7233 不通·先修 compose" `
            -WhyCn "没有耐久执行层就没有 P0 执行" `
            -Invoke "Status-XinaoBaseCompose.ps1"
    }
}

# named gaps
foreach ($g in $namedGaps) {
    Add-Cand -Id "gap_$g" -Score 97 -Kind "repair" `
        -Suffix ("roi_gap_" + ($g -replace '[^a-zA-Z0-9_]', '_').Substring(0, [Math]::Min(40, $g.Length))) `
        -Handler "roi_gap_rescan" `
        -TitleCn "差距未清：$g" `
        -WhyCn "named_gaps 仍有红项，优先修" `
        -Invoke "Invoke-GrokHolographicGapScan.ps1"
}

# vision each open item
foreach ($it in $visionOpen) {
    $vid = [string]$it.id
    $sc = 88
    if ($vid -match 'V01') { $sc = 95 }
    Add-Cand -Id "vision_$vid" -Score $sc -Kind "vision" `
        -Suffix ("roi_vision_" + ($vid -replace '[^a-zA-Z0-9_]', '_')) `
        -Handler "roi_vision_true_test" `
        -TitleCn ("愿景真测：" + $it.title_cn) `
        -WhyCn ("status=" + $it.status + "；P0未闭合时 contracted 就是任务源") `
        -Invoke "Invoke-GrokVisionMegaPackageTrueTest.ps1" `
        -Intent ("愿景真测 " + $vid)
}

# registry dormants
if ($regCounts) {
    $dorm = 0; $uncl = 0; $miss = 0
    if ($regCounts.PSObject.Properties['registered_dormant']) { $dorm = [int]$regCounts.registered_dormant }
    if ($regCounts.PSObject.Properties['on_disk_unclaimed']) { $uncl = [int]$regCounts.on_disk_unclaimed }
    if ($regCounts.PSObject.Properties['glue_registry_missing']) { $miss = [int]$regCounts.glue_registry_missing }
    if (($dorm + $uncl + $miss) -gt 0) {
        Add-Cand -Id "registry_lying_capacity" -Score 86 -Kind "capability" `
            -Suffix "roi_registry_claim" -Handler "roi_registry_scan" `
            -TitleCn "能力面：躺尸/未认领/缺胶水再扫并记证据" `
            -WhyCn ("dormant=$dorm unclaimed=$uncl glue_missing=$miss；最大能力界面未闭合") `
            -Invoke "Invoke-GrokLocalCapabilityRegistryScan.ps1"
    }
}

# map green but p0 open — explicit high score reminder task already added
if ($gapClear -and $p0Incomplete) {
    Add-Cand -Id "map_green_not_done" -Score 93 -Kind "p0" `
        -Suffix "roi_map_green_not_p0" -Handler "roi_p0_honest" `
        -TitleCn "纠偏：地图全绿≠P0完成·继续拆真事" `
        -WhyCn "施工包差距表清空只说明红格没了；P0五目标/证据/采纳层仍 partial" `
        -Invoke "Invoke-GrokRoiP0HonestNowCan.ps1"
}

# checkpoint always last among seeds
Add-Cand -Id "checkpoint" -Score 40 -Kind "meta" `
    -Suffix "roi_checkpoint" -Handler "roi_checkpoint" `
    -TitleCn "检查点保存" `
    -WhyCn "实质进展后存档" `
    -Invoke "Invoke-GrokSessionContextCheckpoint.ps1 -Save"

$ranked = @($candidates | Sort-Object { - [int]$_.score }, { $_.id })

# Build seed_tasks: top MaxSeed concrete (exclude pure meta until end)
$work = @($ranked | Where-Object { $_.kind -ne "meta" } | Select-Object -First $MaxSeed)
$meta = @($ranked | Where-Object { $_.kind -eq "meta" } | Select-Object -First 1)
$seedTasks = [System.Collections.Generic.List[object]]::new()
$i = 1
foreach ($c in $work) {
    [void]$seedTasks.Add([ordered]@{
        order       = $i
        id_suffix   = $c.seed_suffix
        title_cn    = $c.title_cn
        score       = $c.score
        kind        = $c.kind
        handler     = $c.handler
        invoke      = $c.invoke
        intent      = $c.intent
        why_roi_cn  = $c.why_roi_cn
        source_cand = $c.id
    })
    $i++
}
if ($meta.Count -gt 0) {
    $c = $meta[0]
    [void]$seedTasks.Add([ordered]@{
        order = $i; id_suffix = $c.seed_suffix; title_cn = $c.title_cn; score = $c.score
        kind = $c.kind; handler = $c.handler; invoke = $c.invoke; intent = $c.intent
        why_roi_cn = $c.why_roi_cn; source_cand = $c.id
    })
}

$chosen = $seedTasks | Select-Object -First 1
$mode = "roi_concrete"
if (-not $temporalUp -and $namedGaps.Count -eq 0 -and $seedTasks.Count -eq 0) {
    $mode = "repair_keepalive"
}
# NEVER recommend empty when p0 incomplete
if ($p0Incomplete -and $seedTasks.Count -eq 0) {
    [void]$seedTasks.Add([ordered]@{
        order = 1; id_suffix = "roi_p0_honest_now_can"; title_cn = "P0未闭合强制：诚实 now_can"
        score = 100; kind = "p0"; handler = "roi_p0_honest"
        invoke = "Invoke-GrokRoiP0HonestNowCan.ps1"; intent = "P0强制任务"
        why_roi_cn = "公理：P0未闭合则必有任务"; source_cand = "axiom_force"
    })
}

$out = [ordered]@{
    schema_version           = "xinao.roi_self_loop_decide.v2"
    sentinel                 = "SENTINEL:ROI_SELF_LOOP_DECIDE"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    axiom_cn                 = "P0未闭合 ⇒ 永远有任务。地图全绿/named_gaps空 ≠ 没事做。禁止无任务空转。"
    p0_incomplete            = $p0Incomplete
    p0_honesty_cn            = $p0Honesty
    teleology_cn             = "从 P0层/愿景/差距/注册表/Temporal 拆具体 seed_tasks；一次最多 MaxSeed 条真事"
    inputs                   = [ordered]@{
        gap_clear         = $gapClear
        named_gaps        = $namedGaps
        temporal_7233     = $temporalUp
        vision_open_count = $visionOpen.Count
        vision_open_ids   = @($visionOpen | ForEach-Object { $_.id })
        registry_counts   = $regCounts
        max_seed          = $MaxSeed
    }
    candidates_all           = @($ranked)
    seed_tasks               = @($seedTasks)
    chosen                   = $chosen
    recommended_seed_mode    = $mode
    never_no_task_when_p0_open = $true
    wiring_cn                = "RunNext空队列→本脚本→Invoke-AutoSeedFromRoiConcrete"
    not_second_orchestrator  = $true
}
$out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 8 }
# Always return path-loadable object for caller
return (Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json)
