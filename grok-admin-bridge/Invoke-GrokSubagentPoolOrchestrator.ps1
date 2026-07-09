#Requires -Version 5.1
<#
.SYNOPSIS
  Meta 层子代理池编排器 — D 盘 ledger 监控 in_flight，计算补位，不依赖 LLM 记忆。
.DESCRIPTION
  合同：grok_forced_default_os_behavior.v1.json
  - -Pulse：刷新 frontier、对账 in_flight、写 spawn_directives 与 refill_required
  - -RegisterSubagent：登记 Cursor Task 子代理（id/title/status）
  - -CompleteSubagent：结束一项 → 立刻算 refill_count
  - -Daemon：后台轮询（可选，fail-open）
.PARAMETER MaxParallel
  最大并发（默认读合同，上限 8）。
#>
param(
    [ValidateSet("Pulse", "Register", "Complete", "Daemon", "Read")]
    [string]$Action = "Pulse",
    [string]$SubagentId = "",
    [string]$Title = "",
    [ValidateSet("running", "success", "failed", "cancelled")]
    [string]$Status = "running",
    [int]$MaxParallel = 0,
    [int]$PollMs = 3000,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$contractPath = Join-Path $bridge "grok_forced_default_os_behavior.v1.json"
$poolDir = Join-Path $runtime "state\subagent_pool"
$latestPath = Join-Path $poolDir "latest.json"
$stopFlag = Join-Path $runtime "state\grok_wave_cycle\user_stop.flag"
New-Item -ItemType Directory -Force -Path $poolDir | Out-Null

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Resolve-MaxParallel {
    if ($MaxParallel -gt 0) { return [math]::Min(8, [math]::Max(2, $MaxParallel)) }
    $c = Read-Json $contractPath
    $d = 5
    if ($c -and $c.parallel_policy_cn) { }
    $wc = Read-Json (Join-Path $bridge "grok_wave_cycle_default_behavior.v1.json")
    if ($wc -and $wc.per_wave_mandatory_cn.max_subagent_parallel.machine_default) {
        $d = [int]$wc.per_wave_mandatory_cn.max_subagent_parallel.machine_default
    }
    return [math]::Min(8, [math]::Max(2, $d))
}

function Build-SpawnDirectives([object[]]$Frontier, [int]$Count) {
    $out = [System.Collections.Generic.List[object]]::new()
    $i = 0
    foreach ($f in $Frontier) {
        if ($i -ge $Count) { break }
        [void]$out.Add([ordered]@{
            directive_id = "spawn_$([guid]::NewGuid().ToString('N').Substring(0,8))"
            source_id    = [string]$f.id
            title_cn     = [string]$f.title_cn
            priority     = [int]$f.priority
            action_cn    = "立即 Task subagent 实现（非登记）"
            implementation_sources = @(
                "桌面三txt + gap/weak_strategy 对应项"
            )
        })
        $i++
    }
    return @($out)
}

function Build-Frontier {
    $queue = [System.Collections.Generic.List[object]]::new()
    $seen = @{}

    function Add([string]$Id, [string]$Src, [string]$Title, [int]$Pri) {
        if ($seen[$Id]) { return }
        $seen[$Id] = $true
        [void]$queue.Add([pscustomobject]@{ id = $Id; source = $Src; title_cn = $Title; priority = $Pri })
    }

    & (Join-Path $bridge "Invoke-GrokOrchestratorPulse.ps1") -Quiet 2>$null | Out-Null
    $pulse = Read-Json (Join-Path $runtime "state\orchestrator_loop\latest.json")
    if ($pulse -and $pulse.next_spawn_recommend) {
        foreach ($n in @($pulse.next_spawn_recommend)) {
            Add ([string]$n.id) "orchestrator_pulse" ([string]$n.title_cn) ([int]$n.priority)
        }
    }

    $weak = Read-Json (Join-Path $runtime "state\weak_strategy_scan\latest.json")
    if ($weak -and $weak.gaps) {
        foreach ($w in @($weak.gaps | Select-Object -First 12)) {
            $id = [string]$w.id
            if (-not $id) { continue }
            $t = if ($w.problem_cn) { [string]$w.problem_cn } else { $id }
            Add $id "weak_strategy" $t 92
        }
    }

    $gap = Read-Json (Join-Path $runtime "state\holographic_gap\latest.json")
    if ($gap -and $gap.named_gaps) {
        foreach ($g in @($gap.named_gaps | Select-Object -First 8)) {
            Add "gap_$g" "holographic_gap" "修差距 $g" 95
        }
    }

    $bus = Read-Json (Join-Path $runtime "state\integrated_bus_v2\latest.json")
    if ($bus -and $bus.validation -and $bus.validation.passed -ne $true) {
        Add "bus_regreen" "integrated_bus" "integrated_bus validation 再绿" 94
    }

    Add "implement_desktop_specs" "forced_os" "桌面三txt 热路径实施（非登记）" 99
    Add "wave_cycle_continue" "forced_os" "Invoke-GrokWaveCycleRun 续波" 98

    return @($queue | Sort-Object { - $_.priority })
}

function Write-PoolLedger([hashtable]$Payload) {
    $Payload.generated_at = (Get-Date).ToString("o")
    $Payload.schema_version = "xinao.grok_subagent_pool.v1"
    $Payload.sentinel = "SENTINEL:GROK_SUBAGENT_POOL_ORCHESTRATOR"
    $Payload.completion_claim_allowed = $false
    $Payload.contract_ref = "grok_forced_default_os_behavior.v1.json"
    $Payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8
    $md = Join-Path $runtime "readback\zh\subagent_pool_latest.md"
    New-Item -ItemType Directory -Force -Path (Split-Path $md) | Out-Null
    @(
        "# 子代理池 meta 编排",
        "",
        "时间：$($Payload.generated_at)",
        "max_parallel：**$($Payload.max_parallel)** · in_flight：**$($Payload.in_flight_count)** · refill_required：**$($Payload.refill_required)**",
        "",
        "Grok 本回合必须：若 refill_required → 立刻 Task 补满 spawn_directives",
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
        if (-not $SubagentId) { $SubagentId = "sa_$([guid]::NewGuid().ToString('N').Substring(0,10))" }
        $deduped = [System.Collections.Generic.List[object]]::new()
        foreach ($row in @($inFlight)) {
            if ([string]$row.id -ne $SubagentId) { [void]$deduped.Add($row) }
        }
        $inFlight = $deduped
        [void]$inFlight.Add([ordered]@{
            id = $SubagentId; title = $Title; status = "running"; started_at = (Get-Date).ToString("o")
        })
        $frontier = Build-Frontier
        $refill = [math]::Max(0, $maxP - $inFlight.Count)
        $directives = Build-SpawnDirectives $frontier $refill
        Write-PoolLedger @{
            max_parallel = $maxP; in_flight = @($inFlight); in_flight_count = $inFlight.Count
            frontier_depth = $frontier.Count; refill_required = ($refill -gt 0); refill_count = $refill
            spawn_directives = $directives; last_action = "register"; registered_id = $SubagentId
        }
        if (-not $Quiet) { @{ ok = $true; id = $SubagentId; in_flight = $inFlight.Count } | ConvertTo-Json }
        exit 0
    }
    "Complete" {
        if (-not $SubagentId) { throw "Complete requires -SubagentId" }
        $newList = [System.Collections.Generic.List[object]]::new()
        foreach ($row in @($inFlight)) {
            if ([string]$row.id -eq $SubagentId) {
                # JSON-deserialized rows are not mutable; completed agents leave in_flight
                continue
            }
            if ([string]$row.status -eq "running") {
                [void]$newList.Add($row)
            }
        }
        $inFlight = $newList
        $frontier = Build-Frontier
        $refill = [math]::Max(0, $maxP - $inFlight.Count)
        $directives = Build-SpawnDirectives $frontier $refill
        Write-PoolLedger @{
            max_parallel = $maxP; in_flight = @($inFlight); in_flight_count = $inFlight.Count
            frontier_depth = $frontier.Count; refill_required = ($refill -gt 0); refill_count = $refill
            spawn_directives = $directives; last_action = "complete"; completed_id = $SubagentId; completed_status = $Status
            immediate_refill_cn = "子代理结束→下一瞬间补位；本拍 refill_count=$refill"
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
        while (-not (Test-Path $stopFlag)) {
            & $PSCommandPath -Action Pulse -MaxParallel $maxP -Quiet | Out-Null
            Start-Sleep -Milliseconds $PollMs
        }
        exit 0
    }
    default {
        # Pulse
        if (Test-Path $stopFlag) {
            Write-PoolLedger @{
                max_parallel = $maxP; in_flight = @($inFlight); in_flight_count = $inFlight.Count
                refill_required = $false; stop_reason = "user_stop.flag"; spawn_directives = @()
            }
            exit 0
        }
        $frontier = Build-Frontier
        $refill = [math]::Max(0, $maxP - $inFlight.Count)
        $directives = Build-SpawnDirectives $frontier $refill
        Write-PoolLedger @{
            max_parallel = $maxP; in_flight = @($inFlight); in_flight_count = $inFlight.Count
            frontier = @($frontier | Select-Object -First 20)
            frontier_depth = $frontier.Count
            refill_required = ($refill -gt 0 -or $inFlight.Count -lt $maxP)
            refill_count = $refill
            spawn_directives = $directives
            last_action = "pulse"
            per_turn_rule_cn = "Grok 读本文件：refill_required=true → 本回合立即 Task 补满 spawn_directives"
            standing_until_revoked = $true
        }
        if (-not $Quiet) { Get-Content $latestPath -Raw -Encoding UTF8 }
        exit 0
    }
}