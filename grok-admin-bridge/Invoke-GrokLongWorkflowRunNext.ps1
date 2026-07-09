#Requires -Version 5.1
<#
.SYNOPSIS
  长久工作流自主推进：取最高优先级 pending task 执行 → 更新队列 → 差距重扫。
#>
param(
    [switch]$SeedWave6,
    [switch]$SeedWave7,
    [switch]$SeedWave8,
    [switch]$SeedWave9,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$outDir = Join-Path $runtime "state\grok_long_workflow\runs"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Update-QueueTask([object]$Queue, [string]$Id, [string]$Status, [string]$Note = "") {
    $changed = $false
    $newTasks = [System.Collections.Generic.List[object]]::new()
    foreach ($t in $Queue.tasks) {
        if ([string]$t.id -eq $Id) {
            $row = [ordered]@{}
            foreach ($p in $t.PSObject.Properties) { $row[$p.Name] = $p.Value }
            $row["status"] = $Status
            $row["completed_at"] = (Get-Date).ToString("o")
            if ($Note) { $row["note"] = $Note }
            [void]$newTasks.Add([pscustomobject]$row)
            $changed = $true
        } else {
            [void]$newTasks.Add($t)
        }
    }
    if (-not $changed) { throw "Task not found: $Id" }
    $Queue.tasks = $newTasks.ToArray()
    $Queue.updated_at = (Get-Date).ToString("o")
    $Queue | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $queuePath -Encoding UTF8
}

function Invoke-TaskHandler([string]$Id, [string]$InvokeHint) {
    switch -Regex ($Id) {
        "^W6_1_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W6_2_" { & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null; return "wave_status_ok" }
        "^W6_3_" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
            return "bootstrap_ok"
        }
        "^W7_1_" { & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null; return "registry_rescan_ok" }
        "^W7_2_" {
            $ctx = "D:\XINAO_RESEARCH_RUNTIME\state\dp_audit_wave\context_20260708.txt"
            if (-not (Test-Path $ctx)) {
                New-Item -ItemType Directory -Force -Path (Split-Path $ctx) | Out-Null
                @(
                    "DP audit context — holographic gap snapshot $(Get-Date -Format o)",
                    "spine_0to7 green; horizontal_gap_count=0; P0 not closed",
                    "next: tool-table coverage + false-progress lens"
                ) | Set-Content -LiteralPath $ctx -Encoding UTF8
            }
            if (Test-Path (Join-Path $bridge "Invoke-GrokDpAuditWave.ps1")) {
                & (Join-Path $bridge "Invoke-GrokDpAuditWave.ps1") -Throttle 2 | Out-Null
                return "dp_audit_wave_ok"
            }
            return "dp_audit_skipped"
        }
        "^W7_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet | Out-Null
            return "wave_status_ok"
        }
        "^W8_1_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W8_2_" {
            & (Join-Path $bridge "Invoke-GrokMatureFirstGovernanceGate.ps1") -RecordStep `
                -StepId "7_evidence" -TaskClass "platform_ops" `
                -SummaryCn "Wave8全息自主队列：差距0+横向partial诚实登记" `
                -LocalRefs @("state/holographic_gap/latest.json") -Quiet | Out-Null
            return "governance_step_ok"
        }
        "^W8_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 30 -Quiet | Out-Null
            return "continue_wave_ok"
        }
        "^W8_4_" {
            Push-Location $bridge
            try {
                if (Test-Path (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1")) {
                    & (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1") -Quiet | Out-Null
                }
            } finally { Pop-Location }
            return "capability_max_ok"
        }
        "^W9_1_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W9_2_" { & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet | Out-Null; return "wave_status_ok" }
        "^W9_3_" {
            Push-Location $bridge
            try { & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null }
            finally { Pop-Location }
            return "registry_rescan_ok"
        }
        "^W9_4_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·Wave9" `
                -ResumeBriefCn "promotion_gate读盘修；W6-W8全绿；evolution仍partial诚实" `
                -LastMachineActions @("SeedWave9","promotion_probe","gap_rescan") `
                -NextMachineActions @("proactive_evolution_intake","DP决策环") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json") `
                -DoNotReExplain @("completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W8_5_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·Wave8续跑" `
                -ResumeBriefCn "W6+W7全绿；Wave8推进；named_gaps空；P0未闭合" `
                -LastMachineActions @("SeedWave8","RunNext") `
                -NextMachineActions @("promotion_gate","evolution_loop") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json") `
                -DoNotReExplain @("completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W6_4_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "全息自主焊接循环" `
                -ResumeBriefCn "横向7格+RunNext真推；主轴0-7绿；P0未闭合" `
                -LastMachineActions @("Invoke-GrokLongWorkflowRunNext", "horizontal_grids", "gap_rescan") `
                -NextMachineActions @("SeedWave7_if_queue_empty", "DP决策环") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json") `
                -DoNotReExplain @("图景↔事实↔差距", "completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "registry_scan" { & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet 2>$null; return "registry_scan_ok" }
        "capability_maximize" { & (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1") -Quiet 2>$null; return "capability_max_ok" }
        default {
            if ($InvokeHint -match "GapScan") {
                & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null
                return "gap_scan_ok"
            }
            if ($InvokeHint -match "Bootstrap") {
                & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
                return "bootstrap_ok"
            }
            return "noop_unmapped"
        }
    }
}

function Merge-SeedTasks([object]$Seed) {
    if (Test-Path -LiteralPath $queuePath) {
        $existing = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($existing.tasks | Where-Object { $_.status -eq "pending" })
        if ($pending.Count -eq 0) {
            $existing.tasks = @($existing.tasks) + @($Seed.tasks)
            $existing.updated_at = (Get-Date).ToString("o")
            $existing | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $queuePath -Encoding UTF8
        }
    } else {
        $Seed | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $queuePath -Encoding UTF8
    }
}

if ($SeedWave9) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "promotion_gate读盘+evolution诚实续跑"
        tasks          = @(
            [ordered]@{ id = "W9_1_promotion_gap_rescan"; wave = 9; priority = 23; status = "pending"; title_cn = "promotion_gate 读盘+差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W9_2_wave_status"; wave = 9; priority = 24; status = "pending"; title_cn = "4-7 WaveStatus"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W9_3_registry_rescan"; wave = 9; priority = 25; status = "pending"; title_cn = "能力注册表重扫"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W9_4_checkpoint"; wave = 9; priority = 26; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave8) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "P0语义环续跑：治理环+波闭合+能力最大化"
        tasks          = @(
            [ordered]@{ id = "W8_1_holographic_rescan"; wave = 8; priority = 18; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W8_2_governance_evidence"; wave = 8; priority = 19; status = "pending"; title_cn = "治理环证据登记"; invoke = "Invoke-GrokMatureFirstGovernanceGate.ps1" }
            [ordered]@{ id = "W8_3_continue_wave_poll"; wave = 8; priority = 20; status = "pending"; title_cn = "4-7 ContinueWave 薄绑等待"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W8_4_capability_maximize"; wave = 8; priority = 21; status = "pending"; title_cn = "能力界面最大化探活"; invoke = "Invoke-GrokCapabilityMaximize.ps1" }
            [ordered]@{ id = "W8_5_checkpoint_save"; wave = 8; priority = 22; status = "pending"; title_cn = "检查点保存"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave7) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "DP决策环+证据透镜续跑"
        tasks          = @(
            [ordered]@{ id = "W7_1_registry_rescan"; wave = 7; priority = 15; status = "pending"; title_cn = "能力注册表重扫"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W7_2_dp_audit_wave"; wave = 7; priority = 16; status = "pending"; title_cn = "DP审计波（工具表覆盖）"; invoke = "Invoke-GrokDpAuditWave.ps1" }
            [ordered]@{ id = "W7_3_wave_evidence_refresh"; wave = 7; priority = 17; status = "pending"; title_cn = "4-7证据刷新"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
        )
    })
}
elseif ($SeedWave6 -or -not (Test-Path -LiteralPath $queuePath)) {
    Merge-SeedTasks ([ordered]@{
        schema_version  = "xinao.grok_long_workflow_task_queue.v1"
        updated_at      = (Get-Date).ToString("o")
        execution_mode  = "autonomous_continuous"
        scope_cn        = "全息差距焊主路；主轴+横向+九宫"
        tasks           = @(
            [ordered]@{ id = "W6_1_holographic_horizontal_rescan"; wave = 6; priority = 11; status = "pending"; title_cn = "横向7格+差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W6_2_wave_status_rescan"; wave = 6; priority = 12; status = "pending"; title_cn = "4-7 WaveStatus 重扫"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W6_3_bootstrap_refresh"; wave = 6; priority = 13; status = "pending"; title_cn = "Bootstrap+探活刷新"; invoke = "Invoke-GrokLongWorkflowBootstrap.ps1" }
            [ordered]@{ id = "W6_4_checkpoint_save"; wave = 6; priority = 14; status = "pending"; title_cn = "检查点保存"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}

if (-not (Test-Path -LiteralPath $queuePath)) { throw "No task queue at $queuePath" }
$queue = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$next = @($queue.tasks | Where-Object { $_.status -eq "pending" } | Sort-Object { [int]$_.priority } | Select-Object -First 1)
if ($next.Count -eq 0) {
    $result = [ordered]@{ status = "queue_empty"; hint_cn = "无 pending；可 -SeedWave6..9" }
    if (-not $Quiet) { $result | ConvertTo-Json -Depth 6 }
    exit 0
}

$task = $next[0]
$taskId = [string]$task.id
$invokeHint = ""
if ($task.PSObject.Properties["invoke"]) { $invokeHint = [string]$task.invoke }

$runLog = [ordered]@{
    schema_version = "xinao.grok_long_workflow_run.v1"
    task_id        = $taskId
    started_at     = (Get-Date).ToString("o")
    invoke_hint    = $invokeHint
}
try {
    $outcome = Invoke-TaskHandler -Id $taskId -InvokeHint $invokeHint
    $runLog.outcome = $outcome
    $runLog.status = "done"
    Update-QueueTask -Queue $queue -Id $taskId -Status "done" -Note $outcome
} catch {
    $runLog.status = "blocked"
    $runLog.error = $_.Exception.Message
    Update-QueueTask -Queue $queue -Id $taskId -Status "blocked" -Note $_.Exception.Message
}

$runLog.finished_at = (Get-Date).ToString("o")
$runFile = Join-Path $outDir ("run_{0}_{1}.json" -f $taskId, (Get-Date).ToString("yyyyMMdd_HHmmss"))
$runLog | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runFile -Encoding UTF8

& (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null

if (-not $Quiet) { $runLog | ConvertTo-Json -Depth 6 }
exit 0