#Requires -Version 5.1
<#
.SYNOPSIS
  【历史误名 · 已废止为架构定义】见 grok_deepseek_v4_pro_review_node.v1.json
  DP 仅 = DeepSeek V4 Pro @ 工人草稿后验收节点；本脚本不得当作 Pro/DP 决策环本体。
  保留仅作历史证据路径 state\dp_decision_loop\；新工程勿 SeedWave17 依赖本脚本。
#>
param(
    [string]$WaveId = "",
    [switch]$SkipDpInvoke,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\dp_decision_loop"
$ctxDir = Join-Path $outDir "context"
New-Item -ItemType Directory -Force -Path $outDir, $ctxDir | Out-Null

function Read-J([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    return Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
}

if (-not $WaveId) { $WaveId = "dp-decision-{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss") }
$vision = Read-J (Join-Path $runtime "state\vision_mega_package\latest.json")
$gap = Read-J (Join-Path $runtime "state\holographic_gap\latest.json")
$ckpt = Read-J (Join-Path $runtime "state\grok_session_context\latest.json")
$queue = Read-J (Join-Path $runtime "state\grok_long_workflow\task_queue.json")
$lane = Read-J (Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json")

$partial = @()
if ($vision) {
    $partial = @($vision.items | Where-Object { $_.status -in @("partial", "open") } | ForEach-Object { "$($_.id):$($_.title_cn)" })
}

$ctxLines = @(
    "DP Decision Loop Context $(Get-Date -Format o)",
    "window=Grok_Admin_Isolated only; not_333_mainline",
    "completion_claim_allowed=false",
    "vision_partial=$($partial -join ' | ')",
    "gap_horizontal=$($gap.horizontal_gap_count) compose_up=$($gap.compose_up)",
    "checkpoint_anchor=$($ckpt.user_intent_anchor_cn)",
    "next_checkpoint_actions=$($ckpt.next_machine_actions -join '; ')",
    "pending_tasks=$(if ($queue) { @($queue.tasks | Where-Object status -eq 'pending').Count } else { 0 })",
    "",
    "问：作为后台主脑语义位（非仅分配），给出≤5条 next_machine_actions + 谁决策 + 禁止假绿纪律。",
    "输出 JSON 草案字段：who_decides_cn, modes_cn[], next_actions[], blockers[], honesty_cn"
)
$ctxPath = Join-Path $ctxDir ("context_{0}.txt" -f $WaveId)
[System.IO.File]::WriteAllText($ctxPath, ($ctxLines -join "`n"), $utf8)

$dpOk = $false
$dpExit = 0
$dpLaneStatus = ""
$dpModelInvoked = $false
$dpArtifact = ""

if (-not $SkipDpInvoke) {
    try {
        & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") `
            -Mode audit -Provider dp -WaveId $WaveId `
            -LaneId "DP-DECISION-brain-slot" `
            -Objective "P0 DP决策环：vision剩partial项+下一机器动作；非仅分配" `
            -InputFile $ctxPath | Out-Null
        $dpExit = $LASTEXITCODE
        $lane = Read-J (Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json")
        if ($lane) {
            $dpLaneStatus = [string]$lane.status
            if ($lane.worker_lane_result) {
                $dpModelInvoked = $lane.worker_lane_result.model_invocation_performed -eq $true
                $dpOk = $lane.worker_lane_result.status -eq "succeeded" -or $dpLaneStatus -eq "direct_worker_lane_ready"
                if ($lane.worker_lane_result.artifact_ref) { $dpArtifact = [string]$lane.worker_lane_result.artifact_ref }
            }
        }
        $dpOk = $dpOk -or ($dpExit -eq 0)
    } catch {
        $dpOk = $false
        $dpLaneStatus = $_.Exception.Message
    }
}

$modes = @(
    "evidence_driven_schedule",
    "draft_internal_review",
    "weld_default_mainline",
    "staging_submit_only",
    "fan_in_before_fact_promotion"
)

$report = [ordered]@{
    schema_version           = "xinao.grok_dp_decision_loop.v1"
    sentinel                 = "SENTINEL:GROK_DP_DECISION_LOOP"
    generated_at             = (Get-Date).ToString("o")
    wave_id                  = $WaveId
    window_cn                = "Grok Admin Isolated"
    boundary_ref             = "grok_admin_isolated_window_boundary.v1.json"
    p0_ref                   = "grok_p0_autonomous_background_base.v1.json"
    who_decides_cn           = "DeepSeek DP 后台主脑语义位（薄绑 worker lane）；Grok 岛执行+证据；用户喊停"
    modes_cn                 = $modes
    not_only_allocator       = $true
    not_333_mainline         = $true
    completion_claim_allowed = $false
    honesty_cn               = "决策落盘≠333闭合；lane 产出 staging；须 fan-in/AAQ 才晋升事实"
    inputs = [ordered]@{
        context_file    = $ctxPath
        vision_partial  = $partial
        gap_ref         = "state/holographic_gap/latest.json"
        checkpoint_ref  = "state/grok_session_context/latest.json"
    }
    dp_invoke = [ordered]@{
        skipped           = [bool]$SkipDpInvoke
        exit_code         = $dpExit
        ok                = $dpOk
        lane_status       = $dpLaneStatus
        model_invoked     = $dpModelInvoked
        artifact_ref      = $dpArtifact
        invoke_script     = "Invoke-GrokCodexSDirectWorkerLane.ps1 -Provider dp -Mode audit"
    }
    next_machine_actions_default = @(
        "续 vision V13/V14：DP+qwen lane 真 invoke 证据写 staging",
        "DP 决策环多 mode 工程化（非固定分配链）",
        "partial 收敛后评估 contracted 条目是否需真测"
    )
    now_can_invoke = @(
        "Invoke-GrokDpDecisionLoop.ps1",
        "Invoke-GrokCodexSDirectWorkerLane.ps1 -Provider dp -Mode audit",
        "Invoke-GrokVisionMegaPackageTrueTest.ps1"
    )
}

$latest = Join-Path $outDir "latest.json"
[System.IO.File]::WriteAllText($latest, ($report | ConvertTo-Json -Depth 14), $utf8)
[System.IO.File]::WriteAllText((Join-Path $outDir ("decision_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))), ($report | ConvertTo-Json -Depth 14), $utf8)

if (-not $Quiet) { $report | ConvertTo-Json -Depth 10 }
exit $(if ($SkipDpInvoke -or $dpOk) { 0 } else { 1 })