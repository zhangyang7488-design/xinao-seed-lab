#Requires -Version 5.1
<#
.SYNOPSIS
  愿景超级完整大包逐项真测：读盘 invoke/失败态，更新 item status，禁止假绿。
  输出 state\vision_mega_package\true_test_latest.json + 刷新 latest.json counts。
#>
param(
    [string[]]$ItemIds = @(),
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\vision_mega_package"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Read-J([string]$p) {
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    return Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-SkillExists([string]$name) {
    $roots = @(
        (Join-Path (Split-Path $bridge -Parent) ".grok\skills"),
        "C:\Users\xx363\.grok\skills"
    )
    foreach ($r in $roots) {
        $p = Join-Path $r $name
        if (Test-Path -LiteralPath $p) { return $true }
    }
    return $false
}

$pkgPath = Join-Path $outDir "latest.json"
$pkg = Read-J $pkgPath
if (-not $pkg) {
    & (Join-Path $bridge "Invoke-GrokVisionMegaPackageLand.ps1") -Quiet | Out-Null
    $pkg = Read-J $pkgPath
}
if (-not $pkg) { throw "vision_mega_package missing" }

$gap = Read-J (Join-Path $runtime "state\holographic_gap\latest.json")
$queue = Read-J (Join-Path $runtime "state\grok_long_workflow\task_queue.json")
$mod = Read-J (Join-Path $runtime "state\modular_separation_probe\latest.json")
$evo = Read-J (Join-Path $runtime "state\proactive_evolution_intake\latest.json")
$lane = Read-J (Join-Path $runtime "state\codex_s_direct_worker_lane\latest.json")
$grokLane = Read-J (Join-Path $bridge "state\grok_codex_s_direct_worker_lane\latest.json")
$reg = Read-J (Join-Path $runtime "state\local_capability_registry\latest.json")
$durable = Read-J (Join-Path $runtime "state\task_entry\durable_claim\latest.json")
$p0Honest = Read-J (Join-Path $runtime "state\roi_self_loop\p0_honest_now_can_latest.json")
$p0Base = Read-J (Join-Path $bridge "grok_p0_autonomous_background_base.v1.json")
$dualIso = Read-J (Join-Path $bridge "grok_dual_isomorphism_modular_separation.v1.json")
$rollback = Read-J (Join-Path $bridge "grok_rollback_domain_max_auth.v1.json")
$coreIndex = Read-J (Join-Path $bridge "grok_island_core_index.v1.json")

$order = @($pkg.next_land_order)
if ($ItemIds.Count -gt 0) { $order = @($ItemIds) }

$results = [System.Collections.Generic.List[object]]::new()

function Add-Result([string]$Id, [bool]$Ok, [string]$Status, [string]$Detail, [string[]]$Evidence) {
    [void]$results.Add([ordered]@{
        id       = $Id
        ok       = $Ok
        status   = $Status
        detail   = $Detail
        evidence = $Evidence
        tested_at = (Get-Date).ToString("o")
    })
}

foreach ($vid in $order) {
    switch -Regex ($vid) {
        "V17" {
            $ok = ($null -ne $evo) -and ($evo.evolution_honest -eq $true)
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "evolution_intake=$ok" @("state/proactive_evolution_intake")
        }
        "V03" {
            $ok = ($null -ne $mod) -and ([int]$mod.ok_count -ge 5)
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "modular_ok=$($mod.ok_count)/$($mod.total)" @("state/modular_separation_probe")
        }
        "V04" {
            $runNext = Test-Path (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1")
            $done = 0
            if ($queue) { $done = @($queue.tasks | Where-Object { $_.status -eq "done" }).Count }
            $ok = $runNext -and ($done -gt 0)
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "RunNext=$runNext done_tasks=$done" @("Invoke-GrokLongWorkflowRunNext.ps1")
        }
        "V06" {
            $skill = Test-SkillExists "sp-verification-before-completion"
            $honest = ($null -eq $gap) -or ($gap.completion_claim_allowed -eq $false)
            $ok = $skill -and $honest
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "verification_skill=$skill claim_honest=$honest" @("sp-verification-before-completion", "holographic_gap")
        }
        "V09" {
            $preamble = Test-Path (Join-Path $bridge "grok_construction_package_preamble.v1.json")
            $gapOk = ($null -ne $gap) -and ($gap.horizontal_gap_count -eq 0)
            $ok = $preamble -and $gapOk
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "preamble=$preamble gap0=$gapOk" @("grok_construction_package_preamble.v1.json", "state/holographic_gap")
        }
        "V10" {
            $runNext = Test-Path (Join-Path $bridge "Invoke-GrokLongWorkflowRunNext.ps1")
            $qOk = ($null -ne $queue)
            $report = Test-Path (Join-Path $runtime "readback\zh\grok_overnight_report_latest.md")
            $autoRan = $false
            if ($queue) { $autoRan = @($queue.tasks | Where-Object { $_.id -match '^W1[2-9]_' -and $_.status -eq 'done' }).Count -ge 5 }
            $ok = $runNext -and $qOk -and ($report -or $autoRan)
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "RunNext=$runNext queue=$qOk report=$report autoRan=$autoRan" @("grok_long_workflow_runtime.v1.json")
        }
        "V13" {
            $scriptOk = Test-Path (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1")
            $laneOk = ($null -ne $lane) -and ($lane.status -eq "direct_worker_lane_ready")
            $dpRoute = $false
            $dpInvoked = $false
            if ($lane -and $lane.provider_route_context) {
                $dpRoute = [bool]$lane.provider_route_context.gateway_probe.ok
            }
            if ($lane -and $lane.worker_lane_result) {
                $dpInvoked = $lane.worker_lane_result.deepseek_dp_invocation -eq $true -or $lane.worker_lane_result.model_invocation_performed -eq $true
            }
            if ($grokLane -and $grokLane.request -and $grokLane.request.provider -eq "dp") {
                $dpInvoked = $dpInvoked -or $grokLane.provider_invocation_performed -eq $true -or $grokLane.model_invocation_performed -eq $true
            }
            $ok = $scriptOk -and ($laneOk -or $dpRoute)
            $st = if ($dpInvoked) { "landed" } elseif ($ok) { "partial" } else { "open" }
            Add-Result $vid $ok $st "script=$scriptOk lane_ready=$laneOk gateway=$dpRoute dp_invoked=$dpInvoked" @("Invoke-GrokCodexSDirectWorkerLane.ps1", "state/codex_s_direct_worker_lane")
        }
        "V14" {
            $scriptOk = Test-Path (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1")
            $qwenReady = $false
            $qwenInvoked = $false
            if ($lane -and $lane.provider_route_context) {
                $qwenReady = $lane.provider_route_context.qwen_prepaid_cheap_worker_ready -eq $true
            }
            if ($lane -and $lane.worker_lane_result) {
                $qwenInvoked = $lane.worker_lane_result.qwen_prepaid_invocation -eq $true -or $lane.worker_lane_result.model_invocation_performed -eq $true
            }
            if ($grokLane -and $grokLane.request -and $grokLane.request.provider -eq "qwen") {
                $qwenInvoked = $qwenInvoked -or $grokLane.provider_invocation_performed -eq $true -or $grokLane.model_invocation_performed -eq $true
            }
            $ok = $scriptOk -and ($qwenReady -or $qwenInvoked)
            $st = if ($qwenInvoked) { "landed" } elseif ($ok) { "partial" } else { "open" }
            Add-Result $vid $ok $st "script=$scriptOk qwen_ready=$qwenReady qwen_invoked=$qwenInvoked" @("Invoke-GrokCodexSDirectWorkerLane.ps1")
        }
        "V11" {
            $waveOk = Test-Path (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1")
            $claimed = ($null -ne $durable)
            $ok = $waveOk -and $claimed
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "wave_ps1=$waveOk durable=$claimed" @("state/task_entry")
        }
        "V12" {
            $composeUp = ($null -ne $gap) -and ($gap.compose_up -eq $true)
            $workerHc = $false
            if ($gap -and $gap.horizontal_grids -and $gap.horizontal_grids.step2) {
                $workerHc = $gap.horizontal_grids.step2.h2_worker_healthy -eq "green"
            }
            $ok = $composeUp -and $workerHc
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "compose_up=$composeUp worker_hc=$workerHc" @("S/docker-compose.yml", "state/holographic_gap")
        }
        "V15" {
            $hooked = 0
            $unclaimed = 99
            if ($reg -and $reg.counts) {
                $hooked = [int]$reg.counts.registered_and_hooked
                $unclaimed = [int]$reg.counts.on_disk_unclaimed
            }
            $ok = ($null -ne $reg) -and ($unclaimed -le 1) -and ($hooked -ge 2)
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "hooked=$hooked unclaimed=$unclaimed" @("state/local_capability_registry")
        }
        "V01" {
            $fiveGoals = $false
            if ($p0Base -and $p0Base.p0_goals_isomorphic_to_grok_cn -and $p0Base.p0_goals_isomorphic_to_grok_cn.goals) {
                $fiveGoals = @($p0Base.p0_goals_isomorphic_to_grok_cn.goals).Count -ge 5
            }
            $dualRef = ($null -ne $dualIso) -and ($dualIso.isomorphic_capability_shape_cn.five_goals.Count -ge 5)
            $whoDecides = ($null -ne $p0Honest) -and ($null -ne $p0Honest.who_decides_cn) -and (@($p0Honest.now_can_invoke).Count -ge 3)
            $honestPartial = ($null -eq $p0Honest) -or ($p0Honest.completion_claim_allowed -eq $false)
            $ok = $fiveGoals -and $dualRef -and $whoDecides -and $honestPartial
            $st = if ($ok) { "partial" } else { "open" }
            Add-Result $vid $ok $st "five_goals=$fiveGoals dual_ref=$dualRef who_decides=$whoDecides honest_partial=$honestPartial" @("grok_p0_autonomous_background_base.v1.json", "grok_dual_isomorphism_modular_separation.v1.json", "state/roi_self_loop/p0_honest_now_can_latest.json")
        }
        "V19" {
            $forbidden = $false
            if ($dualIso -and $dualIso.capability_weld_policy_cn -and $dualIso.capability_weld_policy_cn.forbidden_default) {
                $forbidden = @($dualIso.capability_weld_policy_cn.forbidden_default | Where-Object { $_ -match "OpenClaw|第三条" }).Count -ge 1
            }
            $oneMainline = Test-Path (Join-Path $bridge "grok_333_one_mature_system_mainline_grok_sideline.v1.json")
            $openClawDefault = $false
            if ($coreIndex -and $coreIndex.tier0) {
                $openClawDefault = @($coreIndex.tier0 | Where-Object { $_ -match "openclaw|OpenClaw" }).Count -gt 0
            }
            $ok = $forbidden -and $oneMainline -and (-not $openClawDefault)
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "forbidden_default=$forbidden one_mainline=$oneMainline openclaw_tier0=$openClawDefault" @("grok_dual_isomorphism_modular_separation.v1.json", "grok_333_one_mature_system_mainline_grok_sideline.v1.json")
        }
        "V20" {
            $rule22 = Test-Path (Join-Path (Split-Path $bridge -Parent) ".grok\rules\22-grok-rollback-domain-max-auth.md")
            $desktopPolicy = $false
            if ($rollback -and $rollback.desktop_delete_policy_cn) {
                $desktopPolicy = $rollback.desktop_delete_policy_cn -match "删桌面|Desktop"
            }
            $denyDesktop = $false
            if ($rollback -and $rollback.deny_list_hard_only) {
                $denyDesktop = @($rollback.deny_list_hard_only | Where-Object { $_ -match "desktop|Desktop" }).Count -ge 1
            }
            if (-not $denyDesktop -and $rollback -and $rollback.grok_must_not) {
                $denyDesktop = @($rollback.grok_must_not | Where-Object { $_ -match "desktop" }).Count -ge 1
            }
            $ok = $rule22 -and $desktopPolicy -and $denyDesktop
            Add-Result $vid $ok $(if ($ok) { "landed" } else { "partial" }) "rule22=$rule22 desktop_policy=$desktopPolicy deny_desktop=$denyDesktop" @(".grok/rules/22-grok-rollback-domain-max-auth.md", "grok_rollback_domain_max_auth.v1.json")
        }
        default {
            Add-Result $vid $false "unchanged" "no_probe_mapped" @()
        }
    }
}

$newItems = [System.Collections.Generic.List[object]]::new()
foreach ($it in $pkg.items) {
    $row = [ordered]@{}
    foreach ($p in $it.PSObject.Properties) { $row[$p.Name] = $p.Value }
    $hit = @($results | Where-Object { $_.id -eq $it.id } | Select-Object -First 1)
    if ($hit.Count -gt 0 -and $hit[0].status -ne "unchanged") {
        $row["status"] = $hit[0].status
        $ev = @()
        if ($row.Contains("evidence") -and $row["evidence"]) { $ev = @($row["evidence"]) }
        $ev += "true_test_latest.json"
        $row["evidence"] = @($ev | Select-Object -Unique)
    }
    [void]$newItems.Add([pscustomobject]$row)
}

$counts = [ordered]@{
    total       = $newItems.Count
    landed      = @($newItems | Where-Object { $_.status -eq "landed" }).Count
    contracted  = @($newItems | Where-Object { $_.status -eq "contracted" }).Count
    partial     = @($newItems | Where-Object { $_.status -eq "partial" }).Count
    in_progress = @($newItems | Where-Object { $_.status -eq "in_progress" }).Count
    open        = @($newItems | Where-Object { $_.status -eq "open" }).Count
}

$remaining = @($newItems | Where-Object { $_.status -in @("partial", "open", "in_progress") } | ForEach-Object { $_.id })

$pkg.generated_at = (Get-Date).ToString("o")
$pkg.counts = $counts
$pkg.items = $newItems.ToArray()
$pkg.next_land_order = @($remaining | Select-Object -First 7)
$pkg.completion_claim_allowed = $false
$pkg.honesty_cn = "大包落盘 ≠ 跑穿；逐项真测后改 status；禁止假绿"

$trueTest = [ordered]@{
    schema_version           = "xinao.vision_mega_package_true_test.v1"
    sentinel                 = "SENTINEL:VISION_MEGA_PACKAGE_TRUE_TEST"
    generated_at             = (Get-Date).ToString("o")
    completion_claim_allowed = $false
    items_tested             = @($results)
    counts_after             = $counts
    remaining_partial_open   = $remaining
    honesty_cn               = "真测=读盘+invoke形状；模型真跑另记 worker_lane 证据"
}
$truePath = Join-Path $outDir "true_test_latest.json"
[System.IO.File]::WriteAllText($truePath, ($trueTest | ConvertTo-Json -Depth 14), $utf8)
[System.IO.File]::WriteAllText($pkgPath, ($pkg | ConvertTo-Json -Depth 14), $utf8)
$hist = Join-Path $outDir ("true_test_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
[System.IO.File]::WriteAllText($hist, ($trueTest | ConvertTo-Json -Depth 14), $utf8)

if (-not $Quiet) { $trueTest | ConvertTo-Json -Depth 10 }
exit 0