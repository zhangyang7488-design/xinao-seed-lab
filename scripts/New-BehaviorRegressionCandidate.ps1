[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Z][A-Z0-9_]{7,95}$')]
    [string]$Id,
    [Parameter(Mandatory)]
    [ValidateSet('user_correction', 'observed_failure', 'incident', 'capability_gap', 'external_maturity')]
    [string]$SourceType,
    [Parameter(Mandatory)]
    [string]$SourceRef,
    [Parameter(Mandatory)]
    [ValidateSet(
        'productivity',
        'topology',
        'external_effect',
        'continuity',
        'authorization',
        'preference_learning',
        'worker_routing',
        'capability_admission',
        'mature_first',
        'control_plane',
        'incident_lifecycle'
    )]
    [string]$Domain,
    [Parameter(Mandatory)]
    [string]$ObservedOutcome,
    [Parameter(Mandatory)]
    [string]$DesiredOutcome,
    [Parameter(Mandatory)]
    [string]$RestoredContext,
    [Parameter(Mandatory)]
    [string]$UserIncrement,
    [string[]]$AcceptanceCriteria = @(
        'The affected live behavior case passes with a real app-server trace.',
        'The prohibited-side-effect regression set remains green.'
    ),
    [string[]]$ProhibitedSideEffects = @(
        'The candidate does not automatically rewrite instructions, memory, policy, or authorization.'
    ),
    [string[]]$TraceRefs = @(),
    [string]$Scope = 'codex-local-collaboration',
    [ValidateSet('smoke', 'core', 'deep')]
    [string[]]$ProposedProfiles = @('core', 'deep'),
    [string]$OperationId = ([guid]::NewGuid().ToString()),
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' })
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$schema = Join-Path $repoRoot 'evals\behavior_regression\candidate.schema.json'
$candidateRoot = Join-Path $RuntimeRoot 'state\human-capabilities\behavior-regression\candidates'
$candidatePath = Join-Path $candidateRoot "$Id.json"

$candidate = [ordered]@{
    schema_version = 'xinao.behavior_regression_candidate.v1'
    id = $Id
    operation_id = $OperationId
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    source_type = $SourceType
    source_ref = $SourceRef
    domain = $Domain
    scope = $Scope
    observed_outcome = $ObservedOutcome
    desired_outcome = $DesiredOutcome
    restored_context = $RestoredContext
    user_increment = $UserIncrement
    acceptance_criteria = @($AcceptanceCriteria | Select-Object -Unique)
    prohibited_side_effects = @($ProhibitedSideEffects | Select-Object -Unique)
    trace_refs = @($TraceRefs | Where-Object { $_ } | Select-Object -Unique)
    proposed_profiles = @($ProposedProfiles | Select-Object -Unique)
    promotion_status = 'candidate'
    contains_secrets = $false
    not_authority = $true
}
$json = $candidate | ConvertTo-Json -Depth 6
if (-not ($json | Test-Json -SchemaFile $schema)) {
    throw 'Candidate failed the local behavior-regression JSON schema.'
}

New-Item -ItemType Directory -Path $candidateRoot -Force | Out-Null
if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
    $existing = Get-Content -LiteralPath $candidatePath -Raw | ConvertFrom-Json
    if ($existing.operation_id -eq $OperationId) {
        Write-Output $candidatePath
        return
    }
    throw "Candidate ID already exists with a different operation: $candidatePath"
}
$json | Set-Content -LiteralPath $candidatePath -Encoding utf8NoBOM
Write-Output $candidatePath
