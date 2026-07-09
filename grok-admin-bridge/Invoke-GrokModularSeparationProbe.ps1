#Requires -Version 5.1
<#
.SYNOPSIS
  M1-M4 模块化分离探活（真测形状，非假绿）。
  M5 纪律 skills 另见 isomorphic_capability_weld；本脚本不重复 ApplyDisciplineSkills。
#>
param([switch]$Quiet)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\modular_separation_probe"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Probe([string]$Id, [string]$Name, [scriptblock]$Body) {
    $row = [ordered]@{ id = $Id; name_cn = $Name; ok = $false; detail = ""; invoke = "" }
    try {
        $r = & $Body
        if ($r -is [hashtable] -or $r -is [System.Collections.IDictionary]) {
            foreach ($k in $r.Keys) { $row[$k] = $r[$k] }
        } elseif ($r -is [pscustomobject]) {
            foreach ($p in $r.PSObject.Properties) { $row[$p.Name] = $p.Value }
        } else {
            $row.detail = [string]$r
            $row.ok = $true
        }
    } catch {
        $row.ok = $false
        $row.detail = $_.Exception.Message
    }
    return [pscustomobject]$row
}

$m1 = Probe "M1_intent_ingress" "意图入口投递壳" {
    $ps1 = Join-Path $bridge "Invoke-GrokTaskEntry.ps1"
    $mod = Join-Path $bridge "grok_task_entry_module.v1.json"
    $intake = Join-Path $runtime "state\task_entry"
    $ok = (Test-Path $ps1) -and (Test-Path $mod)
    return @{
        ok     = $ok
        invoke = "Invoke-GrokTaskEntry.ps1"
        detail = "script=$ok module=$(Test-Path $mod) state_dir=$(Test-Path $intake)"
        role   = "delivery_shell_only"
    }
}

$m2 = Probe "M2_claim_orchestrate" "认领与编排" {
    $claim = Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1"
    $runNext = Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1"
    $q = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
    $durable = Join-Path $runtime "state\task_entry\durable_claim\latest.json"
    $pending = 0
    if (Test-Path $q) {
        $qj = Get-Content $q -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($qj.tasks | Where-Object { $_.status -eq "pending" }).Count
    }
    return @{
        ok     = (Test-Path $claim) -and (Test-Path $runNext)
        invoke = "ClaimDurable / RunNext"
        detail = "claim_ps1=$(Test-Path $claim) queue=$(Test-Path $q) pending=$pending durable=$(Test-Path $durable)"
        note   = "Grok queue 与 333 Temporal 载体分离、形状同构"
    }
}

$m3 = Probe "M3_workers" "工人面" {
    $lane = Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1"
    $ev = Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json"
    $laneEv = $false
    if (Test-Path $ev) { $laneEv = $true }
    # 轻探：脚本存在即 partial ok；不强制烧额度
    return @{
        ok     = (Test-Path $lane)
        invoke = "Invoke-GrokCodexSDirectWorkerLane.ps1 -Lane dp|qwen"
        detail = "script=$(Test-Path $lane) evidence=$laneEv"
        honesty = "存在脚本≠本轮真跑通模型；额度/网关另记"
    }
}

$m4 = Probe "M4_evidence_lens" "证据与透镜" {
    $gap = Join-Path $runtime "state\holographic_gap\latest.json"
    $lens = Join-Path $bridge "grok_meta_cognition_lens.v1.json"
    $gapOk = Test-Path $gap
    $claim = $true
    if ($gapOk) {
        $g = Get-Content $gap -Raw -Encoding UTF8 | ConvertFrom-Json
        $claim = ($g.completion_claim_allowed -eq $false)
    }
    return @{
        ok     = $gapOk -and (Test-Path $lens) -and $claim
        invoke = "Invoke-GrokHolographicGapScan.ps1"
        detail = "gap=$gapOk lens=$(Test-Path $lens) claim_false_honest=$claim"
    }
}

$m5 = Probe "M5_capability_weld" "能力焊装（只读状态）" {
    $st = Join-Path $runtime "state\isomorphic_capability_weld\latest.json"
    $skills = Join-Path (Split-Path $bridge -Parent) ".grok\skills"
    $sp = @(Get-ChildItem $skills -Filter "sp-*" -ErrorAction SilentlyContinue)
    return @{
        ok     = (Test-Path $st) -and ($sp.Count -ge 5)
        invoke = "Invoke-GrokIsomorphicCapabilityWeld.ps1 -Status"
        detail = "weld_json=$(Test-Path $st) sp_skills=$($sp.Count) skip_reapply=true"
    }
}

$modules = @($m1, $m2, $m3, $m4, $m5)
$okN = @($modules | Where-Object { $_.ok }).Count

$report = [ordered]@{
    schema_version           = "xinao.modular_separation_probe.v1"
    sentinel                 = "SENTINEL:MODULAR_SEPARATION_PROBE"
    generated_at             = (Get-Date).ToString("o")
    dual_iso_ref             = "grok_dual_isomorphism_modular_separation.v1.json"
    modules                  = $modules
    ok_count                 = $okN
    total                    = $modules.Count
    completion_claim_allowed = $false
    honesty_cn               = "模块探活绿=可 invoke 形状；≠愿景大包跑穿、≠333 自洽闭合"
    now_can_invoke           = @(
        "Invoke-GrokTaskEntry.ps1",
        "Invoke-GrokLongWorkflowRunNext.ps1",
        "Invoke-GrokHolographicGapScan.ps1",
        "Invoke-GrokIsomorphicCapabilityWeld.ps1 -Status",
        "Invoke-GrokVisionMegaPackageLand.ps1",
        "Invoke-GrokProactiveEvolutionIntake.ps1"
    )
}
$path = Join-Path $outDir "latest.json"
[System.IO.File]::WriteAllText($path, ($report | ConvertTo-Json -Depth 12), $utf8)
if (-not $Quiet) { $report | ConvertTo-Json -Depth 12 }
exit 0
