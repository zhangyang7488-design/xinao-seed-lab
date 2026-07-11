#Requires -Version 5.1
<#
.SYNOPSIS
  开工包专用动态轮回：frontier 来自施工阶段缺口 + 证据盘，写 subagent_pool ledger 补位指令。
.DESCRIPTION
  外部成熟：concurrent fan-out + complete-as-done refill。
  frontier 钉死五项：S0_compose_on_disk, S0_merged, S1_amq_attribution, S2_surface, S3_legacy_bus。
  禁 daemon。
.PARAMETER Action
  Pulse | Read | SeedWave3
#>
param(
    [ValidateSet("Pulse", "Read", "SeedWave3")]
    [string]$Action = "Pulse",
    [int]$MaxParallel = 5,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$poolDir = Join-Path $runtime "state\subagent_pool"
$latestPath = Join-Path $poolDir "latest.json"
$waveDir = Join-Path $runtime "state\kaigong_wave"
$stopFlag = Join-Path $runtime "state\grok_wave_cycle\user_stop.flag"
New-Item -ItemType Directory -Force -Path $poolDir, $waveDir | Out-Null

function Test-Ev([string]$Name) {
    Test-Path -LiteralPath (Join-Path $waveDir $Name)
}

function Build-KaigongFrontier {
    $q = [System.Collections.Generic.List[object]]::new()
    function AddF([string]$Id, [string]$Title, [int]$Pri, [string]$PromptHint) {
        [void]$q.Add([pscustomobject]@{
            id = $Id
            title_cn = $Title
            priority = $Pri
            prompt_hint_cn = $PromptHint
            source = "kaigong_infra_frontier_pinned"
        })
    }

    $sComposePath = "E:\XINAO_RESEARCH_WORKSPACES\S\docker-compose.yml"
    $sComposeOnDisk = (Test-Path -LiteralPath $sComposePath) -or (Test-Ev "S0_compose_on_disk.json")

    if (-not $sComposeOnDisk) {
        AddF "S0_compose_on_disk" "S0: compose to S authority path" 100 "Target E:\XINAO_RESEARCH_WORKSPACES\S\docker-compose.yml or honest gap. Reuse S0_baseline. No live recreate/daemon. Evidence: kaigong_wave\S0_compose_on_disk.json"
    }
    if (-not (Test-Ev "S0_merged.json")) {
        AddF "S0_merged" "S0: merge backup+parity+draft to single authority" 99 "Merge backup_search/parity_notes/baseline into S0_merged. Single source + named_gaps. No compose up live/daemon. Evidence: kaigong_wave\S0_merged.json"
    }
    if (-not (Test-Ev "S1_amq_attribution.json")) {
        AddF "S1_amq_attribution" "S1: AMQ exact release/hash attribution" 98 "Pin version/source/license/hash/offline path. Reuse dl_amq+baseline+mailbox. Not re-download as done. No daemon/Temporal recreate. Evidence: kaigong_wave\S1_amq_attribution.json"
    }
    if (-not (Test-Ev "S2_surface.json")) {
        AddF "S2_surface" "S2: capability surface claim refresh" 97 "Refresh grok_capability_surface_claim; list now_can_invoke; real invoke evidence. No daemon/live Temporal. Evidence: kaigong_wave\S2_surface.json"
    }
    if (-not (Test-Ev "S3_legacy_bus.json")) {
        AddF "S3_legacy_bus" "S3: legacy bus/panel thin bind doorbell" 96 "dual_brain_bus/LivePanel doorbell thin-bind Mailbox. See T3_bus_thin_bind. No daemon/while+sleep owner. Evidence: kaigong_wave\S3_legacy_bus.json"
    }

    return @($q | Sort-Object { - $_.priority })
}

function Write-Ledger([hashtable]$H) {
    $H.generated_at = (Get-Date).ToString("o")
    $H.schema_version = "xinao.grok_subagent_pool.v1"
    $H.sentinel = "SENTINEL:GROK_SUBAGENT_POOL_ORCHESTRATOR"
    $H.completion_claim_allowed = $false
    $H.contract_ref = "grok_dynamic_subagent_rotation.v1.json"
    $H.kaigong_rotation = $true
    $H.daemon_forbidden = $true
    $H.wave_tag = "infra_pinned_s0_s1_s2_s3_five"
    $H.standing_until_revoked = $false
    $H.external_mature_cn = "Azure concurrent orchestration + complete-then-refill; Warp parent observes child"
    $H.tui_loop_honest_cn = "No platform auto-infinite-turn; ledger+spawn_directives; main session must Task-refill when refill_required"
    $H.disk_rules_cn = "D=tools/state/evidence; E=repos/mature; avoid C tool roots"
    if (-not $H.notes_cn) {
        $H.notes_cn = @(
            "frontier pinned five: S0_compose_on_disk / S0_merged / S1_amq_attribution / S2_surface / S3_legacy_bus",
            "max_parallel=8 cap; daemon forbidden; no live Temporal recreate"
        )
    }
    $H | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $latestPath -Encoding UTF8
    $md = Join-Path $runtime "readback\zh\subagent_pool_latest.md"
    New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
    @(
        "# kaigong subagent pool",
        "",
        "in_flight=$($H.in_flight_count) / max=$($H.max_parallel) refill_required=$($H.refill_required) refill=$($H.refill_count)",
        "",
        "If refill_required: Task-fill spawn_directives this turn",
        "",
        "ledger: ``$latestPath``"
    ) | Set-Content -LiteralPath $md -Encoding UTF8
}

if (Test-Path $stopFlag) {
    Write-Ledger @{
        max_parallel = $MaxParallel
        in_flight = @()
        in_flight_count = 0
        refill_required = $false
        spawn_directives = @()
        stop_reason = "user_stop.flag"
    }
    if (-not $Quiet) { Get-Content $latestPath -Raw -Encoding UTF8 }
    exit 0
}

$prior = $null
if (Test-Path $latestPath) {
    $prior = Get-Content $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
$inFlight = [System.Collections.Generic.List[object]]::new()
if ($prior -and $prior.in_flight) {
    foreach ($row in @($prior.in_flight)) {
        if ([string]$row.status -eq "running") { [void]$inFlight.Add($row) }
    }
}

$frontier = Build-KaigongFrontier
$maxP = [math]::Min(8, [math]::Max(2, $MaxParallel))
$refill = [math]::Max(0, $maxP - $inFlight.Count)
$directives = [System.Collections.Generic.List[object]]::new()
$i = 0
foreach ($f in $frontier) {
    if ($i -ge $refill) { break }
    $busy = $false
    foreach ($r in $inFlight) {
        if ([string]$r.source_id -eq [string]$f.id) { $busy = $true; break }
    }
    if ($busy) { continue }
    [void]$directives.Add([ordered]@{
        directive_id = "spawn_$([guid]::NewGuid().ToString('N').Substring(0,8))"
        source_id = [string]$f.id
        title_cn = [string]$f.title_cn
        priority = [int]$f.priority
        prompt_hint_cn = [string]$f.prompt_hint_cn
        action_cn = "Task/spawn_subagent implement now (not register-only)"
        implementation_sources = @(
            "D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\",
            "Invoke-GrokKaigongRotation.ps1 pinned frontier"
        )
    })
    $i++
}

Write-Ledger @{
    max_parallel = $maxP
    in_flight = @($inFlight)
    in_flight_count = $inFlight.Count
    frontier = @($frontier | Select-Object -First 20)
    frontier_depth = $frontier.Count
    refill_required = ($directives.Count -gt 0)
    refill_count = $directives.Count
    spawn_directives = @($directives)
    last_action = $Action
    per_turn_rule_cn = "refill_required=true -> fill parallel subagents this turn; Complete then Pulse; no daemon"
}

if ($Action -eq "Read" -or -not $Quiet) {
    Get-Content $latestPath -Raw -Encoding UTF8
}
exit 0