#Requires -Version 5.1
<#
.SYNOPSIS
  主动进化 intake（step7 h7_evolution_honest 读盘真源）。
  扫 gap / dual_iso / vision 大包 / 队列，写 state\proactive_evolution_intake\latest.json。
  诚实：有 intake ≠ P0 闭合。
#>
param([switch]$Quiet)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\proactive_evolution_intake"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Read-J([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    return Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
}

$gap = Read-J (Join-Path $runtime "state\holographic_gap\latest.json")
$queue = Read-J (Join-Path $runtime "state\grok_long_workflow\task_queue.json")
$weld = Read-J (Join-Path $runtime "state\isomorphic_capability_weld\latest.json")
$vision = Read-J (Join-Path $runtime "state\vision_mega_package\latest.json")
$mod = Read-J (Join-Path $runtime "state\modular_separation_probe\latest.json")
$ckpt = Read-J (Join-Path $runtime "state\grok_session_context\latest.json")

$pending = @()
if ($queue) { $pending = @($queue.tasks | Where-Object { $_.status -eq "pending" }) }
$doneWaves = @()
if ($queue) {
    $doneWaves = @($queue.tasks | Where-Object { $_.status -eq "done" } | ForEach-Object { $_.wave } | Sort-Object -Unique)
}

$proposals = [System.Collections.Generic.List[object]]::new()
if (-not $vision) {
    [void]$proposals.Add([ordered]@{ id = "land_vision_mega_package"; priority = 0; action_cn = "落盘愿景超级完整大包"; invoke = "Invoke-GrokVisionMegaPackageLand.ps1" })
}
if (-not $mod) {
    [void]$proposals.Add([ordered]@{ id = "probe_m1_m4"; priority = 1; action_cn = "M1-M4 模块化分离探活"; invoke = "Invoke-GrokModularSeparationProbe.ps1" })
}
if ($weld -and $weld.completion_claim_allowed -ne $true) {
    [void]$proposals.Add([ordered]@{ id = "m5_honest"; priority = 2; action_cn = "M5 纪律 skills 已焊；勿重复 ApplyDisciplineSkills"; invoke = "Invoke-GrokIsomorphicCapabilityWeld.ps1 -Status" })
}
if ($gap -and $gap.completion_claim_allowed -eq $false) {
    [void]$proposals.Add([ordered]@{ id = "p0_not_closed"; priority = 3; action_cn = "P0/333 未闭合：按愿景大包逐项真测推进"; invoke = "vision_mega_package items" })
}
if ($pending.Count -eq 0) {
    [void]$proposals.Add([ordered]@{ id = "seed_or_continue"; priority = 4; action_cn = "pending=0 时 RunNext 自动按 vision_mega_package 种子下一波"; invoke = "Invoke-GrokLongWorkflowRunNext" })
} else {
    [void]$proposals.Add([ordered]@{ id = "drain_pending"; priority = 4; action_cn = ("推进 {0} 个 pending" -f $pending.Count); invoke = "Invoke-GrokLongWorkflowRunNext" })
}
[void]$proposals.Add([ordered]@{ id = "pro_review_node_on_mature_plane"; priority = 5; action_cn = "成熟控制面焊通 DeepSeek V4 Pro 验收节点（DP仅缩写）"; invoke = "grok_deepseek_v4_pro_review_node.v1.json + Temporal/LangGraph 黄金路径" })

$report = [ordered]@{
    schema_version           = "xinao.proactive_evolution_intake.v1"
    sentinel                 = "SENTINEL:PROACTIVE_EVOLUTION_INTAKE"
    generated_at             = (Get-Date).ToString("o")
    evolution_honest         = $true
    completion_claim_allowed = $false
    inputs = [ordered]@{
        gap_scanned_at     = $(if ($gap) { $gap.scanned_at } else { $null })
        pending_count      = $pending.Count
        done_waves         = $doneWaves
        m5_weld_present    = [bool]$weld
        vision_present     = [bool]$vision
        modular_probe      = [bool]$mod
        checkpoint_anchor  = $(if ($ckpt) { $ckpt.user_intent_anchor_cn } else { $null })
    }
    proposals              = @($proposals)
    next_default_cn        = "执行 proposals 优先级最低数字；真测写证据；禁止假绿闭合"
    dual_iso_ref           = "grok_dual_isomorphism_modular_separation.v1.json"
    note_cn                = "本文件存在 → gap step7.h7_evolution_honest 可变 green；仍非 P0 闭合"
}
$path = Join-Path $outDir "latest.json"
[System.IO.File]::WriteAllText($path, ($report | ConvertTo-Json -Depth 12), $utf8)
$hist = Join-Path $outDir ("intake_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
[System.IO.File]::WriteAllText($hist, ($report | ConvertTo-Json -Depth 12), $utf8)
if (-not $Quiet) { $report | ConvertTo-Json -Depth 12 }
exit 0
