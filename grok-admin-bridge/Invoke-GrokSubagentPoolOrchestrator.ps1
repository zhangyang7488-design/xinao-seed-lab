#Requires -Version 5.1
<#
.SYNOPSIS
  Meta subagent pool orchestrator - D-drive ledger drives refill (not LLM memory).
.DESCRIPTION
  Contract: grok_forced_default_os_behavior.v1.json + morph_max_subagent_default.v1.json
  - Pulse: refresh frontier, reconcile in_flight, write spawn_directives + refill_required
  - Register: register a running subagent / composer25 worker
  - Complete: end one -> compute refill_count immediately
  - Read / Daemon
.PARAMETER MaxParallel
  Cap parallel slots (default from contract, hard cap 8).
#>
param(
    [ValidateSet("Pulse", "Register", "Complete", "Daemon", "Read")]
    [string]$Action = "Pulse",
    [string]$SubagentId = "",
    [string]$Title = "",
    [ValidateSet("running", "success", "failed", "cancelled")]
    [string]$Status = "running",
    [ValidateSet("task45", "composer25", "other")]
    [string]$Lane = "task45",
    [int]$MaxParallel = 0,
    [int]$PollMs = 3000,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$contractPath = Join-Path $bridge "grok_forced_default_os_behavior.v1.json"
$morphPath = Join-Path $bridge "grok_morph_max_subagent_default.v1.json"
$poolDir = Join-Path $runtime "state\subagent_pool"
$latestPath = Join-Path $poolDir "latest.json"
$stopFlag = Join-Path $runtime "state\grok_wave_cycle\user_stop.flag"
$pinnedFrontierPath = Join-Path $runtime "state\subagent_pool\pinned_frontier.json"
New-Item -ItemType Directory -Force -Path $poolDir | Out-Null

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function To-SafeInt([object]$Value, [int]$Default = 0) {
    if ($null -eq $Value) { return $Default }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) { return [int]$Value }
    $s = [string]$Value
    if ([string]::IsNullOrWhiteSpace($s)) { return $Default }
    $n = 0
    if ([int]::TryParse($s, [ref]$n)) { return $n }
    return $Default
}

function Resolve-MaxParallel {
    if ($MaxParallel -gt 0) { return [math]::Min(8, [math]::Max(2, $MaxParallel)) }
    $m = Read-Json $morphPath
    if ($m -and $m.max_parallel) { return [math]::Min(8, [math]::Max(2, [int]$m.max_parallel)) }
    $wc = Read-Json (Join-Path $bridge "grok_wave_cycle_default_behavior.v1.json")
    $d = 8
    if ($wc -and $wc.per_wave_mandatory_cn -and $wc.per_wave_mandatory_cn.max_subagent_parallel -and $wc.per_wave_mandatory_cn.max_subagent_parallel.machine_default) {
        $d = [int]$wc.per_wave_mandatory_cn.max_subagent_parallel.machine_default
    }
    return [math]::Min(8, [math]::Max(2, $d))
}

function Build-SpawnDirectives([object[]]$Frontier, [int]$Count) {
    $out = [System.Collections.Generic.List[object]]::new()
    $i = 0
    foreach ($f in $Frontier) {
        if ($i -ge $Count) { break }
        $lane = "task45"
        if ($f.PSObject.Properties.Name -contains "lane" -and $f.lane) { $lane = [string]$f.lane }
        [void]$out.Add([ordered]@{
            directive_id = "spawn_$([guid]::NewGuid().ToString('N').Substring(0, 8))"
            source_id    = [string]$f.id
            title_cn     = [string]$f.title_cn
            priority     = (To-SafeInt $f.priority 50)
            lane         = $lane
            action_cn    = "IMMEDIATE spawn: Task45 subagent and/or Composer25 worker (not register-only)"
            prompt_hint_cn = if ($f.PSObject.Properties.Name -contains "prompt_hint_cn") { [string]$f.prompt_hint_cn } else { [string]$f.title_cn }
            implementation_sources = @(
                "D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\",
                "grok_morph_max_subagent_default.v1.json",
                "desktop dynamic rotation shape txt"
            )
        })
        $i++
    }
    return @($out)
}

function Build-Frontier {
    $queue = [System.Collections.Generic.List[object]]::new()
    $seen = @{}

    function Add-Item([string]$Id, [string]$Src, [string]$Title, [int]$Pri, [string]$Lane = "task45", [string]$Hint = "") {
        if ($seen[$Id]) { return }
        $seen[$Id] = $true
        if (-not $Hint) { $Hint = $Title }
        [void]$queue.Add([pscustomobject]@{
            id = $Id
            source = $Src
            title_cn = $Title
            priority = $Pri
            lane = $Lane
            prompt_hint_cn = $Hint
        })
    }

    # Pinned frontier on disk wins for continuity (external ledger, not LLM memory)
    $pinned = Read-Json $pinnedFrontierPath
    if ($pinned -and $pinned.items) {
        foreach ($p in @($pinned.items)) {
            $lane = if ($p.lane) { [string]$p.lane } else { "task45" }
            $hint = if ($p.prompt_hint_cn) { [string]$p.prompt_hint_cn } else { [string]$p.title_cn }
            Add-Item ([string]$p.id) "pinned_frontier" ([string]$p.title_cn) (To-SafeInt $p.priority 90) $lane $hint
        }
    }

    try {
        & (Join-Path $bridge "Invoke-GrokOrchestratorPulse.ps1") -Quiet 2>$null | Out-Null
    } catch {
        if (-not $Quiet) { Write-Warning "OrchestratorPulse fail-open in Build-Frontier: $_" }
    }

    $pulse = Read-Json (Join-Path $runtime "state\orchestrator_loop\latest.json")
    if ($pulse -and $pulse.next_spawn_recommend) {
        foreach ($n in @($pulse.next_spawn_recommend)) {
            Add-Item ([string]$n.id) "orchestrator_pulse" ([string]$n.title_cn) (To-SafeInt $n.priority 70)
        }
    }

    $weak = Read-Json (Join-Path $runtime "state\weak_strategy_scan\latest.json")
    if ($weak -and $weak.gaps) {
        foreach ($w in @($weak.gaps | Select-Object -First 12)) {
            $id = [string]$w.id
            if (-not $id) { continue }
            $t = if ($w.problem_cn) { [string]$w.problem_cn } else { $id }
            Add-Item $id "weak_strategy" $t 92
        }
    }

    $gap = Read-Json (Join-Path $runtime "state\holographic_gap\latest.json")
    if ($gap -and $gap.named_gaps) {
        foreach ($g in @($gap.named_gaps | Select-Object -First 8)) {
            Add-Item "gap_$g" "holographic_gap" "fix gap $g" 95
        }
    }

    # Always-available construction pressure when frontier thin
    if ($queue.Count -lt 3) {
        Add-Item "s1_prod_amq_wiring" "kaigong" "S1 prod AMQ default wiring gap evidence" 99 "composer25" "Write S1 prod wiring + backup/out-of-order gaps; no Temporal recreate"
        Add-Item "s2_mcp_stop_clear" "kaigong" "S2 MCP stop-clear parity or honest GAP" 98 "task45" "MCP missing stop-clear; either thin-bind or evidence-only GAP"
        Add-Item "s3_dual_source_converge" "kaigong" "S3 dual-source risk plan not migrate" 97 "task45" "board exists; dual_source high; plan only no bus delete"
        Add-Item "s4_route_product_gap" "kaigong" "S4 route productization honesty" 96 "composer25" "advisory-only route + doorbell; no auto_dispatch"
    }

    return @($queue | Sort-Object { - $_.priority })
}

function Write-PoolLedger([hashtable]$Payload) {
    $Payload.generated_at = (Get-Date).ToString("o")
    $Payload.schema_version = "xinao.grok_subagent_pool.v1"
    $Payload.sentinel = "SENTINEL:GROK_SUBAGENT_POOL_ORCHESTRATOR"
    $Payload.completion_claim_allowed = $false
    $Payload.contract_ref = "grok_forced_default_os_behavior.v1.json"
    $Payload.morph_ref = "grok_morph_max_subagent_default.v1.json"
    $Payload.daemon_forbidden = $true
    $Payload.external_ledger_required = $true
    $Payload.not_llm_memory = $true
    $Payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8
    $md = Join-Path $runtime "readback\zh\subagent_pool_latest.md"
    New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
    @(
        "# Subagent pool meta (external ledger)",
        "",
        "time: $($Payload.generated_at)",
        "max_parallel: **$($Payload.max_parallel)** · in_flight: **$($Payload.in_flight_count)** · refill_required: **$($Payload.refill_required)**",
        "",
        "Main session MUST: if refill_required -> immediately Task45 + Composer25 fill spawn_directives",
        "",
        "ledger: ``$latestPath``"
    ) | Set-Content -LiteralPath $md -Encoding UTF8
}

$maxP = Resolve-MaxParallel
$prior = Read-Json $latestPath
$inFlight = [System.Collections.Generic.List[object]]::new()
if ($prior -and $prior.in_flight) {
    foreach ($row in @($prior.in_flight)) {
        if ([string]$row.status -eq "running") { [void]$inFlight.Add($row) }
    }
}

switch ($Action) {
    "Register" {
        if (-not $SubagentId) { $SubagentId = "sa_$([guid]::NewGuid().ToString('N').Substring(0, 10))" }
        $deduped = [System.Collections.Generic.List[object]]::new()
        foreach ($row in @($inFlight)) {
            if ([string]$row.id -ne $SubagentId) { [void]$deduped.Add($row) }
        }
        $inFlight = $deduped
        [void]$inFlight.Add([ordered]@{
            id = $SubagentId
            title = $Title
            status = "running"
            lane = $Lane
            started_at = (Get-Date).ToString("o")
        })
        $frontier = Build-Frontier
        $refill = [math]::Max(0, $maxP - $inFlight.Count)
        $directives = Build-SpawnDirectives $frontier $refill
        Write-PoolLedger @{
            max_parallel = $maxP
            in_flight = @($inFlight)
            in_flight_count = $inFlight.Count
            frontier_depth = $frontier.Count
            refill_required = ($refill -gt 0)
            refill_count = $refill
            spawn_directives = $directives
            last_action = "register"
            registered_id = $SubagentId
        }
        if (-not $Quiet) { @{ ok = $true; id = $SubagentId; in_flight = $inFlight.Count } | ConvertTo-Json }
        exit 0
    }
    "Complete" {
        if (-not $SubagentId) { throw "Complete requires -SubagentId" }
        $newList = [System.Collections.Generic.List[object]]::new()
        foreach ($row in @($inFlight)) {
            if ([string]$row.id -eq $SubagentId) { continue }
            if ([string]$row.status -eq "running") { [void]$newList.Add($row) }
        }
        $inFlight = $newList
        $frontier = Build-Frontier
        $refill = [math]::Max(0, $maxP - $inFlight.Count)
        $directives = Build-SpawnDirectives $frontier $refill
        Write-PoolLedger @{
            max_parallel = $maxP
            in_flight = @($inFlight)
            in_flight_count = $inFlight.Count
            frontier_depth = $frontier.Count
            refill_required = ($refill -gt 0)
            refill_count = $refill
            spawn_directives = $directives
            last_action = "complete"
            completed_id = $SubagentId
            completed_status = $Status
            immediate_refill_cn = "complete -> immediate refill; refill_count=$refill"
        }
        if (-not $Quiet) { @{ ok = $true; refill_count = $refill; refill_required = ($refill -gt 0) } | ConvertTo-Json }
        exit 0
    }
    "Read" {
        if (-not (Test-Path $latestPath)) {
            & $PSCommandPath -Action Pulse -Quiet | Out-Null
        }
        Get-Content $latestPath -Raw -Encoding UTF8
        exit 0
    }
    "Daemon" {
        # Optional only; morph prefers main-session ledger-driven refill, not daemon owner
        while (-not (Test-Path $stopFlag)) {
            & $PSCommandPath -Action Pulse -MaxParallel $maxP -Quiet | Out-Null
            Start-Sleep -Milliseconds $PollMs
        }
        exit 0
    }
    default {
        if (Test-Path $stopFlag) {
            Write-PoolLedger @{
                max_parallel = $maxP
                in_flight = @($inFlight)
                in_flight_count = $inFlight.Count
                refill_required = $false
                stop_reason = "user_stop.flag"
                spawn_directives = @()
            }
            exit 0
        }
        $frontier = Build-Frontier
        $refill = [math]::Max(0, $maxP - $inFlight.Count)
        $directives = Build-SpawnDirectives $frontier $refill
        Write-PoolLedger @{
            max_parallel = $maxP
            in_flight = @($inFlight)
            in_flight_count = $inFlight.Count
            frontier = @($frontier | Select-Object -First 20)
            frontier_depth = $frontier.Count
            refill_required = ($refill -gt 0 -or $inFlight.Count -lt $maxP)
            refill_count = $refill
            spawn_directives = $directives
            last_action = "pulse"
            per_turn_rule_cn = "Read this ledger: if refill_required=true then THIS turn fill Task45+Composer25 to max_parallel"
            standing_until_revoked = $true
            morph_cn = "max-subagent default: parallel 4.5 Task + Composer 2.5 workers; external ledger; complete-then-refill; burn tokens for progress"
        }
        if (-not $Quiet) { Get-Content $latestPath -Raw -Encoding UTF8 }
        exit 0
    }
}
