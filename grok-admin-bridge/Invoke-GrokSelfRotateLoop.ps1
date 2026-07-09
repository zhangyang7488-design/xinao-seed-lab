#Requires -Version 5.1
<#
.SYNOPSIS
  Grok 完整自转工作流 — 一键入口。
  用户意图：先把 Grok 搭成完整自转，再拿这套去建设 333。
  一圈：探活(底座) → 决策拆任务 → 种队列 → RunNext执行 → 差距证据 → 检查点 → 可多圈。
  合同：grok_self_rotate_workflow.v1.json
#>
param(
    [int]$Cycles = 1,
    [switch]$SeedOnly,
    [switch]$SkipPoll,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\grok_self_rotate"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latestPath = Join-Path $outDir "latest.json"
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$utf8 = New-Object System.Text.UTF8Encoding $false

function Write-Log([string]$Msg) {
    if (-not $Quiet) { Write-Host $Msg }
}

function Get-NextWaveNumber {
    if (-not (Test-Path -LiteralPath $queuePath)) { return 30 }
    $q = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ws = @($q.tasks | ForEach-Object { [int]$_.wave })
    $max = 29
    if ($ws.Count -gt 0) { $max = [int]($ws | Measure-Object -Maximum).Maximum }
    return [math]::Max(30, $max + 1)
}

function Merge-Tasks([object[]]$NewTasks, [string]$ScopeCn) {
    if (-not (Test-Path -LiteralPath $queuePath)) {
        $seed = [ordered]@{
            schema_version = "xinao.grok_long_workflow_task_queue.v1"
            updated_at     = (Get-Date).ToString("o")
            execution_mode = "autonomous_continuous"
            scope_cn       = $ScopeCn
            tasks          = @($NewTasks)
        }
        ($seed | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $queuePath -Encoding UTF8
        return $true
    }
    $q = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $pending = @($q.tasks | Where-Object { $_.status -eq "pending" })
    if ($pending.Count -gt 0 -and -not $SeedOnly) {
        # 已有 pending：本圈只跑，不重复种
        return $false
    }
    $q.tasks = @($q.tasks) + @($NewTasks)
    $q.updated_at = (Get-Date).ToString("o")
    $q.scope_cn = $ScopeCn
    ($q | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $queuePath -Encoding UTF8
    return $true
}

function Invoke-DecideAndSeed {
    # 成熟形状：意图/目标 → 外部成熟路径(施工包0-7) → 当前任务 → 逐步推进
    $dyn = Join-Path $bridge "Invoke-GrokDynamicRoiFromIntent.ps1"
    if (Test-Path -LiteralPath $dyn) {
        & $dyn -SeedQueue -MaxTasks 5 -Quiet | Out-Null
        $dynPath = Join-Path $runtime "state\dynamic_roi\latest.json"
        $n = 0
        $first = $null
        if (Test-Path $dynPath) {
            $d = Get-Content $dynPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $n = @($d.current_tasks).Count
            if ($d.next_single_task) { $first = [string]$d.next_single_task.title_cn }
        }
        return [ordered]@{
            seeded     = $true
            wave       = "dynamic_roi"
            task_count = $n
            decide_ref = $dynPath
            first      = $first
            shape_cn   = "意图→成熟路径→任务→逐步RunNext"
        }
    }
    # fallback 旧 ROI decide
    $decideScript = Join-Path $bridge "Invoke-GrokRoiSelfLoopDecide.ps1"
    if (Test-Path $decideScript) { & $decideScript -Quiet | Out-Null }
    $roiPath = Join-Path $runtime "state\roi_self_loop\latest.json"
    return [ordered]@{ seeded = $true; decide_ref = $roiPath; shape_cn = "fallback_roi_decide" }
}

function Invoke-OneCycle([int]$Index) {
    $cycle = [ordered]@{
        cycle        = $Index
        started_at   = (Get-Date).ToString("o")
        steps        = [ordered]@{}
    }

    # 0 can_work
    if (-not $SkipPoll) {
        Write-Log "[$Index] 0 can_work (底座探活)"
        & (Join-Path $bridge "Invoke-GrokLongWorkflowKeepalivePoll.ps1") -Quiet | Out-Null
        $cycle.steps["0_can_work"] = "ok"
    } else {
        $cycle.steps["0_can_work"] = "skipped"
    }

    # 1-2 decide+seed
    Write-Log "[$Index] 1-2 decide+seed"
    $seedResult = Invoke-DecideAndSeed
    $cycle.steps["1_2_decide_seed"] = $seedResult

    if ($SeedOnly) {
        $cycle.finished_at = (Get-Date).ToString("o")
        $cycle.status = "seed_only"
        return $cycle
    }

    # 3 do — RunNext once (one real task)
    Write-Log "[$Index] 3 do (RunNext 一条)"
    try {
        & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision -Quiet 2>$null | Out-Null
        # without Quiet may still write; call without forcing Quiet if fails
        $cycle.steps["3_do"] = "run_next_ok"
    } catch {
        try {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1") -NoAutoSeedFromVision | Out-Null
            $cycle.steps["3_do"] = "run_next_ok"
        } catch {
            $cycle.steps["3_do"] = "error:$($_.Exception.Message)"
        }
    }

    # 4 evidence
    Write-Log "[$Index] 4 evidence (gap scan)"
    try {
        & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null
        $cycle.steps["4_evidence"] = "ok"
    } catch {
        $cycle.steps["4_evidence"] = "error:$($_.Exception.Message)"
    }

    # 5 checkpoint
    Write-Log "[$Index] 5 checkpoint"
    try {
        $cp = Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1"
        if (Test-Path $cp) {
            & $cp -Save `
                -UserIntentAnchorCn "Grok完整自转工作流·先自转再建设333" `
                -ResumeBriefCn "SelfRotate cycle=$Index; 非巡检；completion_claim=false" `
                -LastMachineActions @("Invoke-GrokSelfRotateLoop", "decide", "RunNext") `
                -NextMachineActions @("继续SelfRotate", "333主路intake/claim/history") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\grok_self_rotate\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\roi_self_loop\latest.json"
                ) `
                -DoNotReExplain @("自转≠333闭合", "地图绿≠无任务") `
                -Quiet | Out-Null
        }
        $cycle.steps["5_checkpoint"] = "ok"
    } catch {
        $cycle.steps["5_checkpoint"] = "error:$($_.Exception.Message)"
    }

    $cycle.finished_at = (Get-Date).ToString("o")
    $cycle.status = "cycle_done"
    $cycle.completion_claim_allowed = $false
    return $cycle
}

# --- main ---
Write-Log "=== Grok 完整自转工作流 ==="
Write-Log "意图：先搭 Grok 自转，再拿去建设 333"
Write-Log "合同：grok_self_rotate_workflow.v1.json"
Write-Log "圈数：$Cycles"

$cyclesOut = [System.Collections.Generic.List[object]]::new()
for ($i = 1; $i -le [math]::Max(1, $Cycles); $i++) {
    $c = Invoke-OneCycle -Index $i
    [void]$cyclesOut.Add($c)
}

$out = [ordered]@{
    schema_version           = "xinao.grok_self_rotate_run.v1"
    sentinel                 = "SENTINEL:GROK_SELF_ROTATE_RUN"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    user_intent_cn           = "完整自转工作流；先Grok自转，再建设333"
    entry                    = "Invoke-GrokSelfRotateLoop.ps1"
    cycles_requested         = $Cycles
    seed_only                = [bool]$SeedOnly
    cycles                   = @($cyclesOut)
    now_can_invoke           = @(
        "cd $bridge",
        ".\Invoke-GrokSelfRotateLoop.ps1              # 转 1 圈",
        ".\Invoke-GrokSelfRotateLoop.ps1 -Cycles 5    # 连转 5 圈",
        ".\Invoke-GrokSelfRotateLoop.ps1 -SeedOnly    # 只决策+种任务",
        ".\Invoke-GrokLongWorkflowRunNext.ps1         # 只执行下一条"
    )
    not_cn                   = @("9条巡检", "洗总稿当进展", "队列空=333闭合")
}
($out | ConvertTo-Json -Depth 12) | Set-Content -LiteralPath $latestPath -Encoding UTF8

# human readback
$md = Join-Path $runtime "readback\zh\grok_self_rotate_latest.md"
New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
@(
    "# Grok 完整自转工作流",
    "",
    "时间：$((Get-Date).ToString('o'))",
    "",
    "**意图**：先把 Grok 搭成完整自转 → 再用它建设 333。",
    "",
    "入口：``Invoke-GrokSelfRotateLoop.ps1``",
    "证据：``$latestPath``",
    "圈数：$Cycles · seed_only=$SeedOnly",
    "",
    "completion_claim_allowed: **false**",
    "",
    "## 一圈步骤",
    "0 探活(底座) → 1 决策拆任务 → 2 种队列 → 3 RunNext执行 → 4 差距证据 → 5 检查点 → 6 下一圈",
    "",
    "## 本轮结果",
    "见 JSON cycles 数组。"
) | Set-Content -LiteralPath $md -Encoding UTF8

if (-not $Quiet) {
    $out | ConvertTo-Json -Depth 6
}
Write-Log "OK → $latestPath"
exit 0
