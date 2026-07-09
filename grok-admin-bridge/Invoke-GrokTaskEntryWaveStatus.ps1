#Requires -Version 5.1
<#
.SYNOPSIS
  P0 步 4–7 证据查尺：读 D 盘 integrated_bus / aaq / temporal 真源，不写 orchestrator。
#>
param(
    [string]$TaskId = "",
    [string]$ConfigPath = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8

$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$stateRoot = Join-Path $runtime "state\task_entry"
$waveDir = Join-Path $stateRoot "wave_closure"
New-Item -ItemType Directory -Force -Path $waveDir | Out-Null

$latestPath = Join-Path $stateRoot "latest.json"
if (-not (Test-Path -LiteralPath $latestPath)) { throw "No task_entry latest. Run Invoke-GrokTaskEntry first." }
$intake = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($TaskId) {
    $cand = Join-Path $stateRoot "intake\$TaskId.json"
    if (Test-Path -LiteralPath $cand) { $intake = Get-Content -LiteralPath $cand -Raw -Encoding UTF8 | ConvertFrom-Json }
}
$resolvedTaskId = [string]$intake.task_id
$wfId = [string]$intake.temporal_workflow_id
$runId = [string]$intake.temporal_workflow_run_id

$twLatest = Join-Path $runtime "state\temporal_codex_task_workflow\latest.json"
$tw = $null
if (Test-Path -LiteralPath $twLatest) {
    $tw = Get-Content -LiteralPath $twLatest -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $wfId) { $wfId = [string]$tw.workflow_id }
    if (-not $runId) { $runId = [string]$tw.workflow_run_id }
}

$busJson = Get-ChildItem (Join-Path $runtime "readback") -Filter "integrated_bus_*.json" -File -EA SilentlyContinue |
    Where-Object { $_.Name -notmatch 'worker_daemon|temporal_verify|promotion' } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$bus = $null
if ($busJson) {
    $bus = Get-Content -LiteralPath $busJson.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
}

$aaqLatest = Join-Path $runtime "state\aaq\integrated_bus\latest.json"
$aaq = $null
if (Test-Path -LiteralPath $aaqLatest) {
    $aaq = Get-Content -LiteralPath $aaqLatest -Raw -Encoding UTF8 | ConvertFrom-Json
}

$step4 = $false
$step5 = $false
$step6 = $false
$step7 = $false
$blockers = [System.Collections.Generic.List[string]]::new()

if ($bus -and $bus.integrated_bus_invoke -eq $true) { $step4 = $true }
else { [void]$blockers.Add("LANGGRAPH_NO_LIVE_WAVE") }

if ($bus -and $bus.result) {
    $r = $bus.result
    if ($r.glue_seam_invoke_ok -eq $true -or $r.execution_stdout) { $step5 = $true }
}
if (-not $step5) { [void]$blockers.Add("WAVE_EXECUTION_EVIDENCE_MISSING") }

if ($aaq -and $aaq.fanin_ok -eq $true) { $step6 = $true }
elseif ($bus -and $bus.result -and $bus.result.fanin_ok -eq $true) { $step6 = $true }
else { [void]$blockers.Add("FANIN_NOT_OK") }

if ($tw -and ($tw.workflow_open -eq $true -or $tw.temporal_live_route -eq $true)) { $step7 = $true }
elseif ([string]$intake.claim_state -eq "durable_claimed") { $step7 = $true }
else { [void]$blockers.Add("NO_CONTINUE_EVIDENCE") }

$promotionPassed = $null
$promotionEvidenceRef = ""
if ($bus -and $bus.result) {
    if ($bus.result.PSObject.Properties.Name -contains "promotion_gate_passed") {
        $promotionPassed = $bus.result.promotion_gate_passed
    }
    if ($bus.result.PSObject.Properties.Name -contains "promotion_evidence_ref") {
        $promotionEvidenceRef = [string]$bus.result.promotion_evidence_ref
    }
}
$step8 = $promotionPassed -eq $true
if ($step6 -and $promotionPassed -eq $false) { [void]$blockers.Add("PROMOTION_GATE_FAILED") }

# 同步 AAQ claim 快照：readback 已有 promotion 时勿留 null 冒充未跑
if ($aaq -and ($promotionPassed -eq $true -or $promotionPassed -eq $false)) {
    $aaqSync = [ordered]@{
        schema_version           = "xinao.integrated_bus.aaq_claim.v1"
        run_id                   = [string]$aaq.run_id
        workflow_id              = [string]$aaq.workflow_id
        claim_id                 = [string]$aaq.claim_id
        fanin_ok                 = $aaq.fanin_ok
        promotion_gate_passed    = $promotionPassed
        promotion_evidence_ref   = $promotionEvidenceRef
        synced_from_readback_at  = (Get-Date).ToString("o")
        accepted_for_next_frontier_only = $aaq.accepted_for_next_frontier_only
        completion_claim_allowed = $false
    }
    $aaqSync | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $aaqLatest -Encoding UTF8
}

$nowCanDo = if ($step6) {
    "同一 task 已 durable 认领；波内 integrated_bus 有 fan-in 证据；可查 readback\zh\integrated_bus_*.md"
} elseif ($step4) {
    "波内已启动；待 fan-in 闭合（可 Invoke-GrokTaskEntryContinueWave 等待）"
} elseif ([string]$intake.claim_state -eq "durable_claimed") {
    "已认领；波内产物待落盘"
} else {
    "先跑 Invoke-GrokTaskEntryClaimDurable"
}

$report = [ordered]@{
    schema_version       = "xinao.task_entry.wave_status.v1"
    sentinel             = "SENTINEL:GROK_TASK_ENTRY_WAVE_STATUS"
    generated_at         = (Get-Date).ToString("o")
    task_id              = $resolvedTaskId
    claim_state          = [string]$intake.claim_state
    temporal_workflow_id = $wfId
    temporal_workflow_run_id = $runId
    steps                = [ordered]@{
        step4_langgraph_ok      = $step4
        step5_execution_ok      = $step5
        step6_fanin_ok          = $step6
        step7_continue_ok       = $step7
        step8_promotion_gate_ok = $step8
    }
    named_blockers       = @($blockers)
    evidence_refs        = @(
        $(if ($busJson) { $busJson.FullName } else { "" })
        $(if (Test-Path $aaqLatest) { $aaqLatest } else { "" })
        $(if (Test-Path $twLatest) { $twLatest } else { "" })
    ) | Where-Object { $_ }
    now_can_do_cn        = $nowCanDo
    completion_claim_allowed = $false
    blueprint_ref          = "桌面\P0后台自治系统完整施工图_显影对照本地_20260708.txt"
}

$reportLatest = Join-Path $waveDir "latest.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportLatest -Encoding UTF8

$rbDir = Join-Path $runtime "readback\zh"
New-Item -ItemType Directory -Force -Path $rbDir | Out-Null
$rb = @(
    "# 任务入口波闭合查尺（4–7）",
    "",
    "- task_id: $resolvedTaskId",
    "- claim_state: $($intake.claim_state)",
    "- step4 LG: $step4 | step5 执行: $step5 | step6 fanin: $step6 | step7 续跑: $step7 | step8 promotion: $step8",
    "- blocker: $(if ($blockers.Count) { $blockers -join '; ' } else { '无' })",
    "- now_can_do: $nowCanDo",
    ""
) -join "`n"
$rb | Set-Content -LiteralPath (Join-Path $rbDir "task_entry_wave_latest.md") -Encoding UTF8

if (-not $Quiet) { $report | ConvertTo-Json -Depth 8 }
exit 0