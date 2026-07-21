#Requires -Version 5.1
<#
.SYNOPSIS
  Read or save one short restart-safe Grok checkpoint on D:.
.DESCRIPTION
  This script is deliberately checkpoint-only. It does not dispatch workers,
  pulse pools, run schedulers, start shells, or mutate a control plane.
#>
param(
    [switch]$Read,
    [switch]$Save,
    [switch]$Quiet,
    [string]$StateRoot = "",
    [string]$InputJson = "",
    [string]$UserIntentAnchorCn = "",
    [string]$ResumeBriefCn = "",
    [string[]]$LastMachineActions = @(),
    [string[]]$NextMachineActions = @(),
    [string[]]$NamedBlockers = @(),
    [string[]]$EvidenceRefs = @(),
    [string[]]$DoNotReExplain = @()
)

$ErrorActionPreference = "Stop"
$utf8 = [System.Text.UTF8Encoding]::new($false)
$isGrok45Island = $PSScriptRoot -match 'workspace-grok-4[.]5-island'
if (-not $StateRoot) {
    $StateRoot = if ($isGrok45Island) {
        "D:\XINAO_RESEARCH_RUNTIME\state\grok_4_5\session_context"
    } else {
        "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context"
    }
}
$stateRoot = [IO.Path]::GetFullPath($StateRoot)
$latest = Join-Path $stateRoot "latest.json"

if ($Read -and $Save) {
    throw "Specify exactly one action: -Read or -Save"
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

if ($Read) {
    $checkpoint = Read-JsonFile $latest
    if (-not $checkpoint) {
        $checkpoint = [ordered]@{
            schema_version = "xinao.grok_session_context_checkpoint.v3"
            status = "no_checkpoint_yet"
            checkpoint_path = $latest
        }
    }
    if ($Quiet) {
        $checkpoint | ConvertTo-Json -Depth 8 -Compress
    } else {
        $checkpoint | ConvertTo-Json -Depth 8
    }
    exit 0
}

if (-not $Save) {
    throw "Specify exactly one action: -Read or -Save"
}
if ($InputJson) {
    $draft = Read-JsonFile $InputJson
    if (-not $draft) { throw "InputJson not found or invalid: $InputJson" }
    if ($null -ne $draft.user_intent_anchor_cn) { $UserIntentAnchorCn = [string]$draft.user_intent_anchor_cn }
    if ($null -ne $draft.session_resume_brief_cn) { $ResumeBriefCn = [string]$draft.session_resume_brief_cn }
    if ($null -ne $draft.last_machine_actions) { $LastMachineActions = @($draft.last_machine_actions) }
    if ($null -ne $draft.next_machine_actions) { $NextMachineActions = @($draft.next_machine_actions) }
    if ($null -ne $draft.named_blockers) { $NamedBlockers = @($draft.named_blockers) }
    if ($null -ne $draft.evidence_refs) { $EvidenceRefs = @($draft.evidence_refs) }
    if ($null -ne $draft.do_not_re_explain_cn) { $DoNotReExplain = @($draft.do_not_re_explain_cn) }
}

New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
$checkpoint = [ordered]@{
    schema_version = "xinao.grok_session_context_checkpoint.v3"
    status = "active"
    generated_at = (Get-Date).ToString("o")
    user_intent_anchor_cn = $UserIntentAnchorCn
    session_resume_brief_cn = $ResumeBriefCn
    last_machine_actions = @($LastMachineActions)
    next_machine_actions = @($NextMachineActions)
    named_blockers = @($NamedBlockers)
    evidence_refs = @($EvidenceRefs)
    do_not_re_explain_cn = @($DoNotReExplain)
    route_authority = "bridge.config.json#canonical_route"
    route_selection = "selected_by_task_fit_or_existing_route_receipt"
    route_continuity = "continuous_or_resume_does_not_switch_leg"
    worker_selection = "dynamic_positive_net_benefit"
    available_workers = @("grok", "openai_relay", "codex_agents", "combined")
    soft_preference_when_close = "openai_relay"
    grok_lane_provider = "grok"
    worker_width = "dynamic"
    side_effects = [ordered]@{
        dispatch = $false
        scheduler = $false
        resident_loop = $false
        visible_terminal = $false
    }
}
$json = $checkpoint | ConvertTo-Json -Depth 8
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$history = Join-Path $stateRoot ("checkpoint_" + $stamp + ".json")
[System.IO.File]::WriteAllText($history, $json, $utf8)
[System.IO.File]::WriteAllText($latest, $json, $utf8)

if (-not $Quiet) {
    $checkpoint | ConvertTo-Json -Depth 8
}
