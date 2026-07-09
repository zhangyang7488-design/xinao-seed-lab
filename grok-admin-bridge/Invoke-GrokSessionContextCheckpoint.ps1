#Requires -Version 5.1
<#
.SYNOPSIS
  Grok session context checkpoint — save/read local resume brief (not chat log).
.PARAMETER Read
  Output latest checkpoint for new session bootstrap.
.PARAMETER Save
  Write checkpoint from parameters.
.PARAMETER InputJson
  UTF-8 JSON file with save fields (avoids CLI encoding loss for Chinese/arrays).
#>
param(
    [switch]$Read,
    [switch]$Save,
    [switch]$Quiet,
    [string]$InputJson = "",
    [string]$UserIntentAnchorCn = "",
    [string]$ResumeBriefCn = "",
    [string[]]$LastMachineActions = @(),
    [string[]]$NextMachineActions = @(),
    [string[]]$NamedBlockers = @(),
    [string[]]$EvidenceRefs = @(),
    [string[]]$DoNotReExplain = @(),
    [switch]$IncludeRegistryScan
)

$ErrorActionPreference = "Stop"
try { chcp 65001 | Out-Null } catch {}
$utf8Out = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8Out
[Console]::OutputEncoding = $utf8Out

$outDir = "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context"
$latest = Join-Path $outDir "latest.json"
$contractPath = Join-Path $PSScriptRoot "grok_session_context_checkpoint.v1.json"

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-SubagentPoolCheckpointHints {
    $runtime = & (Join-Path $PSScriptRoot "Resolve-GrokEvidenceRuntimeRoot.ps1")
    $poolLatest = Join-Path $runtime "state\subagent_pool\latest.json"
    $pool = Read-JsonFile $poolLatest

    $refillRequired = $null
    if ($pool -and $null -ne $pool.refill_required) {
        $refillRequired = [bool]$pool.refill_required
    }

    $hintCn = if ($refillRequired) {
        "subagent_pool refill_required=true → 本回合立即 Task 补满 spawn_directives"
    } elseif ($pool) {
        "读 subagent_pool/latest.json 核对 in_flight 与 spawn_directives"
    } else {
        "尚无 subagent_pool ledger；Save 时会 Pulse 初始化"
    }

    return [ordered]@{
        subagent_pool_ref             = $poolLatest
        subagent_pool_refill_required = $refillRequired
        subagent_pool_in_flight_count = if ($pool) { $pool.in_flight_count } else { $null }
        subagent_pool_max_parallel    = if ($pool) { $pool.max_parallel } else { $null }
        subagent_pool_hint_cn         = $hintCn
    }
}

function Merge-CheckpointReadOutput([object]$Checkpoint) {
    $out = [ordered]@{}
    if ($Checkpoint) {
        if ($Checkpoint -is [System.Collections.IDictionary]) {
            foreach ($key in $Checkpoint.Keys) { $out[$key] = $Checkpoint[$key] }
        } else {
            foreach ($prop in $Checkpoint.PSObject.Properties) { $out[$prop.Name] = $prop.Value }
        }
    }
    foreach ($entry in (Get-SubagentPoolCheckpointHints).GetEnumerator()) {
        $out[$entry.Key] = $entry.Value
    }
    return $out
}

if ($Read) {
    $cp = Read-JsonFile $latest
    if (-not $cp) {
        $empty = [ordered]@{
            schema_version = "xinao.grok_session_context_checkpoint.v1"
            status         = "no_checkpoint_yet"
            hint_cn        = "尚无检查点；本轮结束应 -Save"
            memory_ref     = "C:\Users\xx363\.grok\memory\MEMORY.md"
        }
        $out = Merge-CheckpointReadOutput $empty
        if ($Quiet) { $out | ConvertTo-Json -Compress } else { $out | ConvertTo-Json -Depth 6 }
        exit 0
    }
    $out = Merge-CheckpointReadOutput $cp
    if ($Quiet) { $out | ConvertTo-Json -Depth 8 -Compress } else { $out | ConvertTo-Json -Depth 8 }
    exit 0
}

if (-not $Save) {
    Write-Host "Usage: -Read | -Save [-InputJson draft.json] | -Save -UserIntentAnchorCn '...'"
    exit 1
}

if ($InputJson) {
    if (-not (Test-Path -LiteralPath $InputJson)) {
        Write-Error "InputJson not found: $InputJson"
        exit 1
    }
    $draft = Read-JsonFile $InputJson
    if ($draft.user_intent_anchor_cn) { $UserIntentAnchorCn = $draft.user_intent_anchor_cn }
    if ($draft.session_resume_brief_cn) { $ResumeBriefCn = $draft.session_resume_brief_cn }
    if ($draft.last_machine_actions) { $LastMachineActions = @($draft.last_machine_actions) }
    if ($draft.next_machine_actions) { $NextMachineActions = @($draft.next_machine_actions) }
    if ($draft.named_blockers) { $NamedBlockers = @($draft.named_blockers) }
    if ($draft.evidence_refs) { $EvidenceRefs = @($draft.evidence_refs) }
    if ($draft.do_not_re_explain_cn) { $DoNotReExplain = @($draft.do_not_re_explain_cn) }
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$registryRef = "D:\XINAO_RESEARCH_RUNTIME\state\local_capability_registry\latest.json"
if ($IncludeRegistryScan -or -not (Test-Path -LiteralPath $registryRef)) {
    $scanScript = Join-Path $PSScriptRoot "Invoke-GrokLocalCapabilityRegistryScan.ps1"
    if (Test-Path -LiteralPath $scanScript) {
        & $scanScript -Quiet | Out-Null
    }
}

$registry = Read-JsonFile $registryRef
$activeContracts = @(
    "grok_brain_and_executor.v1.json",
    "grok_rollback_domain_max_auth.v1.json",
    "grok_session_context_checkpoint.v1.json",
    "grok_retired_contracts_registry.v1.json"
)

$checkpoint = [ordered]@{
    schema_version       = "xinao.grok_session_context_checkpoint.v1"
    sentinel             = "SENTINEL:GROK_SESSION_CONTEXT_CHECKPOINT"
    generated_at         = (Get-Date).ToString("o")
    user_intent_anchor_cn = $UserIntentAnchorCn
    session_resume_brief_cn = $ResumeBriefCn
    last_machine_actions = @($LastMachineActions)
    next_machine_actions = @($NextMachineActions)
    named_blockers       = @($NamedBlockers)
    evidence_refs        = @($EvidenceRefs)
    do_not_re_explain_cn = @($DoNotReExplain)
    active_contracts     = $activeContracts
    memory_ref           = "C:\Users\xx363\.grok\memory\MEMORY.md"
    registry_scan_ref    = $registryRef
    registry_counts      = if ($registry -and $registry.counts) { $registry.counts } else { $null }
    grok_role_cn         = "大脑+执行者；外部全局视角保留；段审已删"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$hist = Join-Path $outDir "checkpoint_$stamp.json"
$utf8Bom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($hist, ($checkpoint | ConvertTo-Json -Depth 8), $utf8Bom)
[System.IO.File]::WriteAllText($latest, ($checkpoint | ConvertTo-Json -Depth 8), $utf8Bom)

$poolScript = Join-Path $PSScriptRoot "Invoke-GrokSubagentPoolOrchestrator.ps1"
if (Test-Path -LiteralPath $poolScript) {
    try {
        & $poolScript -Action Pulse -Quiet | Out-Null
    } catch {
        if (-not $Quiet) { Write-Warning "subagent_pool Pulse failed (fail-open): $_" }
    }
}

if (-not $Quiet) {
    Write-Host "checkpoint_saved: $latest"
    $checkpoint | ConvertTo-Json -Depth 6
}