#Requires -Version 5.1
<#
.SYNOPSIS
  旁路保活轮询一轮：观察·探活·差距·登记；不冒充333闭合。站立授权行为，非固定任务表。
#>
param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateDir = Join-Path $runtime "state\grok_keepalive_poll"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$latestPath = Join-Path $stateDir "latest.json"

$probes = [System.Collections.Generic.List[object]]::new()
$blockers = [System.Collections.Generic.List[string]]::new()
$suggest = [System.Collections.Generic.List[string]]::new()

function Add-Probe([string]$Id, [bool]$Ok, [hashtable]$Extra = @{}) {
    $p = [ordered]@{ id = $Id; ok = $Ok; at = (Get-Date).ToString("o") }
    foreach ($k in $Extra.Keys) { $p[$k] = $Extra[$k] }
    $probes.Add([pscustomobject]$p) | Out-Null
}

# Temporal 7233
try {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
    Add-Probe "temporal_7233" $tcp.TcpTestSucceeded
    if (-not $tcp.TcpTestSucceeded) { [void]$blockers.Add("TEMPORAL_7233_DOWN") }
} catch {
    Add-Probe "temporal_7233" $false @{ error = $_.Exception.Message }
    [void]$blockers.Add("TEMPORAL_7233_PROBE_ERROR")
}

# Compose status (golden path)
$statusScript = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Status-XinaoBaseCompose.ps1"
if (Test-Path -LiteralPath $statusScript) {
    try {
        & $statusScript | Out-Null
        Add-Probe "xinao_base_compose" $true
    } catch {
        Add-Probe "xinao_base_compose" $false @{ error = $_.Exception.Message }
        [void]$blockers.Add("COMPOSE_STATUS_ERROR")
    }
} else {
    Add-Probe "xinao_base_compose" $false @{ missing = $true }
}

# Gap + registry lightweight
try {
    & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null
    Add-Probe "holographic_gap" $true
} catch {
    Add-Probe "holographic_gap" $false @{ error = $_.Exception.Message }
}

try {
    & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
    Add-Probe "registry_scan" $true
} catch {
    Add-Probe "registry_scan" $false @{ error = $_.Exception.Message }
}

$gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
if (Test-Path -LiteralPath $gapPath) {
    $gap = Get-Content -LiteralPath $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($g in @($gap.named_gaps)) {
        if ($g) { [void]$suggest.Add("gap:$g") }
    }
    foreach ($w in @($gap.next_weld_queue)) {
        if ($w.action_cn) { [void]$suggest.Add("weld:$($w.action_cn)") }
    }
}

$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$pendingCount = 0
if (Test-Path -LiteralPath $queuePath) {
    $q = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $pendingCount = @($q.tasks | Where-Object { $_.status -eq "pending" }).Count
}

$out = [ordered]@{
    schema_version           = "xinao.grok_keepalive_poll.v1"
    sentinel                 = "SENTINEL:GROK_KEEPALIVE_POLL"
    generated_at             = (Get-Date).ToString("o")
    standing_auth_cn         = "合同=行为授权；轮询观察保活自修复进化；非固定任务清单"
    not_333_mainline         = $true
    not_closure              = $true
    completion_claim_allowed = $false
    probes                   = @($probes)
    named_blockers           = @($blockers)
    suggest_next_cn          = @($suggest)
    queue_pending_count      = $pendingCount
    poll_ok                  = ($blockers.Count -eq 0)
}
$out | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latestPath -Encoding UTF8

if (-not $Quiet) { $out | ConvertTo-Json -Depth 8 }
exit 0