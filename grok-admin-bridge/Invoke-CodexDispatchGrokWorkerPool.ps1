#Requires -Version 5.1
<#
.SYNOPSIS
  Explicit bootstrap/fallback entry: dispatch bounded Grok headless workers.
.DESCRIPTION
  Use when a bounded direct Grok batch has positive net benefit for parallel
  work, diagnosis, or evidence, including canonical-route fallback. Thin
  wrapper over Invoke-GrokWorkerPool.ps1; never durable truth.
.EXAMPLE
  .\Invoke-CodexDispatchGrokWorkerPool.ps1 -N 4 -Prompt "Implement X; write evidence" -Cwd E:\repo -Model grok-4.5
  .\Invoke-CodexDispatchGrokWorkerPool.ps1 -N 2 -PromptFile .\task.md -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 2,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "",
    [string]$SelectionPath = "",
    [string]$SelectionProbeGrokExe = "",
    [string]$SupervisorRoot = "",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$ExpectedSelectionDecisionSha256 = "",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$DispatchId = "",
    [string]$PoolId = "",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$dispatchId = if ([string]::IsNullOrWhiteSpace($DispatchId)) {
    "cdx_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $DispatchId
}
if ($dispatchId -notmatch '^cdx_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
    throw "CODEX_GROK_DISPATCH_ID_INVALID: $dispatchId"
}
$poolId = if ([string]::IsNullOrWhiteSpace($PoolId)) {
    "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $PoolId
}
if ($poolId -notmatch '^gwp_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
    throw "CODEX_GROK_POOL_ID_INVALID: $poolId"
}
$pool = Join-Path $bridge "Invoke-GrokWorkerPool.ps1"
if (-not (Test-Path -LiteralPath $pool)) {
    throw "MISSING_FALLBACK_PATH: $pool — install/copy Invoke-GrokWorkerPool.ps1"
}
$selectionHelper = Join-Path $bridge "GrokWorkerSelectionReceipt.ps1"
if (-not (Test-Path -LiteralPath $selectionHelper -PathType Leaf)) {
    throw "CODEX_GROK_SELECTION_HELPER_MISSING: $selectionHelper"
}
$selectionResolver = Join-Path $bridge "resolve_grok_worker_selection_receipt.py"
$supervisorCapabilityHelper = Join-Path $bridge "GrokSupervisorRootCapability.ps1"
if (-not (Test-Path -LiteralPath $supervisorCapabilityHelper -PathType Leaf)) {
    throw "CODEX_GROK_SUPERVISOR_CAPABILITY_HELPER_MISSING: $supervisorCapabilityHelper"
}
. $supervisorCapabilityHelper
if ([string]::IsNullOrWhiteSpace($SelectionPath)) {
    if ([string]::IsNullOrWhiteSpace($Model)) {
        throw "CODEX_GROK_MODEL_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($Cwd)) {
        throw "CODEX_GROK_CWD_REQUIRED"
    }
    $requestedModel = $Model.Trim()
    if (-not (Test-Path -LiteralPath $selectionResolver -PathType Leaf)) {
        throw "CODEX_GROK_SELECTION_RESOLVER_MISSING: $selectionResolver"
    }
    $resolvedProbe = ""
    if (-not [string]::IsNullOrWhiteSpace($SelectionProbeGrokExe)) {
        try { $resolvedProbe = [IO.Path]::GetFullPath($SelectionProbeGrokExe) }
        catch { throw "CODEX_GROK_SELECTION_PROBE_INVALID: $SelectionProbeGrokExe" }
    }
    else {
        $resolvedProbe = [string](
            (Get-Command grok.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
        )
        if ([string]::IsNullOrWhiteSpace($resolvedProbe)) {
            $resolvedProbe = "C:\Users\xx363\.grok\bin\grok.exe"
        }
    }
    if (-not (Test-Path -LiteralPath $resolvedProbe -PathType Leaf)) {
        throw "CODEX_GROK_SELECTION_PROBE_MISSING: $resolvedProbe"
    }
    $previousGrokHome = $env:GROK_HOME
    try {
        $env:GROK_HOME = $GrokHome
        $modelsOutput = @(& $resolvedProbe models 2>&1 | ForEach-Object { [string]$_ })
        $modelsExit = $LASTEXITCODE
    }
    finally {
        if ($null -eq $previousGrokHome) {
            Remove-Item Env:\GROK_HOME -ErrorAction SilentlyContinue
        }
        else {
            $env:GROK_HOME = $previousGrokHome
        }
    }
    $modelIds = @(
        [regex]::Matches(
            ($modelsOutput -join "`n"),
            '(?m)^\s*[-*]\s+([A-Za-z0-9_.-]+)(?:\s+\(default\))?\s*$'
        ) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    )
    if ($modelsExit -ne 0 -or $modelIds -notcontains $requestedModel) {
        throw "CODEX_GROK_SELECTED_MODEL_UNHEALTHY: requested=$Model profile=$GrokHome"
    }
    $supervisorCapability = Resolve-GrokSupervisorSelectorRoot `
        -SupervisorRoot $SupervisorRoot `
        -Cwd $Cwd `
        -SelectionResolver $selectionResolver
    $resolvedSupervisorRoot = [string]$supervisorCapability.resolved_root
    $supervisorPython = [string]$supervisorCapability.python_executable
    if (-not (Test-Path -LiteralPath $RuntimeRoot -PathType Container)) {
        throw "CODEX_GROK_RUNTIME_ROOT_MISSING: $RuntimeRoot"
    }
    $selectionDir = Join-Path $RuntimeRoot ("state\grok_worker_selection\" + $dispatchId)
    $SelectionPath = Join-Path $selectionDir "selection.receipt.json"
    $expectedSelectorSha256 = [string]$supervisorCapability.selector_source_sha256
    $resolverOutput = @(
        & $supervisorPython -I -B $selectionResolver `
            --supervisor-root $resolvedSupervisorRoot `
            --runtime-root $RuntimeRoot `
            --model $requestedModel `
            --output $SelectionPath `
            --expected-selector-sha256 $expectedSelectorSha256 2>&1 |
            ForEach-Object { [string]$_ }
    )
    $resolverExit = $LASTEXITCODE
    if ($resolverExit -ne 0 -or -not (Test-Path -LiteralPath $SelectionPath -PathType Leaf)) {
        throw (
            "CODEX_GROK_SELECTION_RESOLUTION_FAILED: " +
            ($resolverOutput -join "`n")
        )
    }
}
. $selectionHelper
$selection = Read-GrokWorkerSelectionReceipt `
    -SelectionPath $SelectionPath `
    -Model $Model `
    -Cwd $Cwd `
    -RequiredPrefix "CODEX_GROK"
$SelectionPath = [string]$selection.selection_path
$Model = [string]$selection.model_id
$Cwd = [string]$selection.cwd
if (
    -not [string]::IsNullOrWhiteSpace($ExpectedSelectionDecisionSha256) -and
    -not [string]::Equals(
        $ExpectedSelectionDecisionSha256,
        [string]$selection.decision_sha256,
        [StringComparison]::Ordinal
    )
) {
    throw "CODEX_GROK_SELECTION_DECISION_CHANGED"
}

$metaDir = "D:\XINAO_RESEARCH_RUNTIME\state\codex_dispatch_grok_worker_pool"
New-Item -ItemType Directory -Force -Path $metaDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false
$dispatchMetaPath = Join-Path $metaDir ($dispatchId + ".json")
$poolSummaryPath = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool" (
    $poolId + "\pool_summary.json"
)
if (Test-Path -LiteralPath $dispatchMetaPath) {
    throw "CODEX_GROK_DISPATCH_ID_ALREADY_EXISTS: $dispatchId"
}

$dispatchMeta = [ordered]@{
    schema_version = "xinao.codex_dispatch_grok_worker_pool.v1"
    sentinel = "SENTINEL:CODEX_DISPATCH_GROK_WORKER_POOL"
    generated_at = (Get-Date).ToString("o")
    dispatch_id = $dispatchId
    pool_id = $poolId
    pool_summary_path = $poolSummaryPath
    role_cn = "dynamic positive-benefit bounded Grok headless worker pool"
    canonical_default_cn = "Temporal + Docker houtai-gongren + worker-internal LangGraph + dynamic Grok"
    not_default_cn = @(
        "codex_to_grok visible typeahead inject",
        "Docker integrated_bus Desktop .lnk"
    )
    n = $N
    model = $Model
    selection_path = $SelectionPath
    selection_decision_sha256 = [string]$selection.decision_sha256
    selected_provider_id = [string]$selection.provider_id
    selected_profile_ref = [string]$selection.profile_ref
    selected_transport_id = [string]$selection.transport_id
    supervisor_root = [string]$supervisorCapability.resolved_root
    selector_source = [string]$supervisorCapability.selector_source
    selector_source_sha256 = [string]$supervisorCapability.selector_source_sha256
    selector_imported_module_source = [string]$supervisorCapability.imported_module_source
    selector_root_selected_from = [string]$supervisorCapability.selected_from
    selector_root_fallback_used = $supervisorCapability.fallback_used -eq $true
    selector_probe_reports = @($supervisorCapability.candidate_reports)
    json_schema_path = $JsonSchemaPath
    cwd = $Cwd
    pool_script = $pool
    completion_claim_allowed = $false
}
[System.IO.File]::WriteAllText(
    $dispatchMetaPath,
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)
Copy-Item $dispatchMetaPath (Join-Path $metaDir "latest.json") -Force

$args = @{
    N = $N
    Model = $Model
    SelectionPath = $SelectionPath
    ExpectedSelectionDecisionSha256 = [string]$selection.decision_sha256
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
    PoolId = $poolId
}
if ($RequireJsonObject) { $args.RequireJsonObject = $true }
if ($JsonSchemaPath) { $args.JsonSchemaPath = $JsonSchemaPath }
if ($Prompt) { $args.Prompt = $Prompt }
if ($PromptFile) { $args.PromptFile = $PromptFile }
$args.Cwd = $Cwd
if ($SkipPauseGate) { $args.SkipPauseGate = $true }
if ($Quiet) { $args.Quiet = $true }

& $pool @args
$code = $LASTEXITCODE

$dispatchMeta.finished_at = (Get-Date).ToString("o")
$dispatchMeta.pool_exit_code = $code
$dispatchMeta.pool_summary_path = $poolSummaryPath
$dispatchMeta.pool_summary_exists = Test-Path -LiteralPath $poolSummaryPath -PathType Leaf
if ($dispatchMeta.pool_summary_exists) {
    try {
        $poolSummary = Get-Content -LiteralPath $poolSummaryPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
        if ([string]$poolSummary.pool_id -ne $poolId) {
            throw "CODEX_GROK_POOL_SUMMARY_ID_MISMATCH"
        }
        if (
            -not [string]::Equals(
                [string]$poolSummary.selection_decision_sha256,
                [string]$selection.decision_sha256,
                [StringComparison]::Ordinal
            ) -or
            -not [string]::Equals([string]$poolSummary.model, $Model, [StringComparison]::Ordinal) -or
            [IO.Path]::GetFullPath([string]$poolSummary.cwd) -ne $Cwd -or
            -not [string]::Equals(
                [string]$poolSummary.selected_provider_id,
                [string]$selection.provider_id,
                [StringComparison]::Ordinal
            ) -or
            -not [string]::Equals(
                [string]$poolSummary.selected_profile_ref,
                [string]$selection.profile_ref,
                [StringComparison]::Ordinal
            ) -or
            -not [string]::Equals(
                [string]$poolSummary.selected_transport_id,
                [string]$selection.transport_id,
                [StringComparison]::Ordinal
            )
        ) {
            throw "CODEX_GROK_POOL_SELECTION_RECEIPT_MISMATCH"
        }
        $dispatchMeta.pool_summary_sha256 = (
            Get-FileHash -LiteralPath $poolSummaryPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $dispatchMeta.pool_all_ok = $poolSummary.all_ok -eq $true
        $dispatchMeta.pool_acceptance_contract_ok = $poolSummary.acceptance_contract_ok -eq $true
    }
    catch {
        if ($code -eq 0) { $code = 4 }
        $dispatchMeta.pool_exit_code = $code
        $dispatchMeta.pool_summary_error = [string]$_.Exception.Message
    }
}
elseif ($code -eq 0) {
    $code = 4
    $dispatchMeta.pool_exit_code = $code
    $dispatchMeta.pool_summary_error = "CODEX_GROK_POOL_SUMMARY_MISSING"
}
$dispatchMeta.status = if (
    $code -eq 0 -and
    $dispatchMeta.pool_all_ok -eq $true -and
    $dispatchMeta.pool_acceptance_contract_ok -eq $true
) { "accepted" } else { "rejected" }
[System.IO.File]::WriteAllText(
    $dispatchMetaPath,
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)
Copy-Item $dispatchMetaPath (Join-Path $metaDir "latest.json") -Force

exit $code
