#Requires -Version 5.1
<#
.SYNOPSIS
  编排脉搏：验收并行结果、刷新差距、种 333 下一波、写 ledger。
  主脑在 Grok 会话里 spawn 子代理；本脚本做机器侧「收口+下一步种子+证据」。
  合同：grok_orchestrator_subagent_loop.v1.json
#>
param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\orchestrator_loop"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$latest = Join-Path $outDir "latest.json"

# 0 keepalive
& (Join-Path $bridge "Invoke-GrokLongWorkflowKeepalivePoll.ps1") -Quiet | Out-Null

# 1 collect lane evidence
$lanes = [System.Collections.Generic.List[object]]::new()
function Add-Lane([string]$Id, [string]$Path, [string]$AcceptCn) {
    $ok = Test-Path -LiteralPath $Path
    $mtime = if ($ok) { (Get-Item -LiteralPath $Path).LastWriteTime.ToString("o") } else { $null }
    [void]$lanes.Add([ordered]@{
        id = $Id; path = $Path; present = $ok; mtime = $mtime; accept_cn = $AcceptCn
        verdict = if ($ok) { "pass_evidence" } else { "missing" }
    })
}
Add-Lane "H-02_git" "D:\XINAO_RESEARCH_RUNTIME\state\git_weld_evidence\latest.json" "有 commit 或 clean + hash"
Add-Lane "P0-01_honest" "D:\XINAO_RESEARCH_RUNTIME\state\roi_self_loop\p0_honest_now_can_latest.json" "now_can + who decides"
Add-Lane "P0_claim" "D:\XINAO_RESEARCH_RUNTIME\state\task_entry\durable_claim\latest.json" "workflow_id 或 blocker"
Add-Lane "P0_task_entry" "D:\XINAO_RESEARCH_RUNTIME\state\task_entry\latest.json" "intake 证据"
Add-Lane "temporal_probe" "D:\XINAO_RESEARCH_RUNTIME\state\temporal_mainline_probe\latest.json" "history 摘录"
Add-Lane "V19_audit" "D:\XINAO_RESEARCH_RUNTIME\state\vision_boundary_audit\latest.json" "第三条链审计"
Add-Lane "mature_observe" "D:\XINAO_RESEARCH_RUNTIME\readback\zh\mature_observe_vs_local_20260709.md" "成熟对照"

# 2 gap rescan
& (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null
$gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
$gaps = @()
if (Test-Path $gapPath) {
    $g = Get-Content $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $gaps = @($g.named_gaps | Where-Object { $_ })
}

# 3 seed next 333 concrete tasks via dynamic roi
& (Join-Path $bridge "Invoke-GrokDynamicRoiFromIntent.ps1") -Intent "编排验收后继续推进333主路" -SeedQueue -MaxTasks 6 -Quiet | Out-Null

# 4 next wave recommendations for human/main agent spawn
$nextSpawn = [System.Collections.Generic.List[object]]::new()
$claimPath = "D:\XINAO_RESEARCH_RUNTIME\state\task_entry\durable_claim\latest.json"
$hasWf = $false
if (Test-Path $claimPath) {
    $c = Get-Content $claimPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $blob = ($c | ConvertTo-Json -Depth 6 -Compress)
    if ($blob -match 'workflow') { $hasWf = $true }
}
if (-not $hasWf) {
    [void]$nextSpawn.Add([ordered]@{ id = "N1"; title_cn = "333 claim 仍无 workflow_id：修 claim/worker/7233"; priority = 100 })
} else {
    [void]$nextSpawn.Add([ordered]@{ id = "N1"; title_cn = "333 history 加深：continue + UI 对照"; priority = 90 })
}
if ($gaps -contains "GROK_ISLAND_UNCOMMITTED_WELDS") {
    [void]$nextSpawn.Add([ordered]@{ id = "N2"; title_cn = "gap 仍报未提交：再扫或补 commit"; priority = 80 })
}
[void]$nextSpawn.Add([ordered]@{ id = "N3"; title_cn = "worker/LangGraph 波内痕迹验收"; priority = 70 })
[void]$nextSpawn.Add([ordered]@{ id = "N4"; title_cn = "V01 五目标诚实材料（不假 landed）"; priority = 60 })

$passed = @($lanes | Where-Object { $_.verdict -eq "pass_evidence" }).Count
$total = $lanes.Count

$out = [ordered]@{
    schema_version           = "xinao.orchestrator_pulse.v1"
    sentinel                 = "SENTINEL:ORCHESTRATOR_PULSE"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    mode_cn                  = "主脑验收脉搏；子代理由会话 spawn；本脚本收口+种下一波"
    lanes_accepted           = $lanes
    score                    = "$passed/$total evidence present"
    named_gaps               = $gaps
    next_spawn_recommend     = @($nextSpawn)
    now_can_invoke           = @(
        "主会话：再 spawn 2~5 路 subagent（按 next_spawn_recommend）",
        "cd $bridge; .\Invoke-GrokOrchestratorPulse.ps1",
        "cd $bridge; .\Invoke-GrokLongWorkflowRunNext.ps1",
        "cd $bridge; .\Invoke-GrokSelfRotateLoop.ps1 -Cycles 3"
    )
    teleology_cn             = "一直活着=循环 pulse+spawn；推进333=claim/history/worker 加深"
}
$out | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latest -Encoding UTF8

# human
$md = Join-Path $runtime "readback\zh\orchestrator_pulse_latest.md"
@(
    "# 编排脉搏",
    "",
    "时间：$((Get-Date).ToString('o'))",
    "验收：$passed/$total 路有证据",
    "gaps：$($gaps -join ', ')",
    "",
    "## 下一波建议 spawn",
    ($nextSpawn | ForEach-Object { "- **$($_.id)** $($_.title_cn)" }),
    "",
    "JSON: $latest"
) | Set-Content -LiteralPath $md -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 6 }
exit 0
