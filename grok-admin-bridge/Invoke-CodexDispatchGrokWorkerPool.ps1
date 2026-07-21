#Requires -Version 5.1
<#
.SYNOPSIS
  Explicit leg-A entry: dispatch bounded Grok headless workers.
.DESCRIPTION
  Use when a bounded direct Grok batch has positive net benefit for parallel
  work, diagnosis, or evidence when selected by task fit or an existing
  leg-A route receipt. This is a normal bounded transport, not a fallback. Thin
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
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Model,
    [string]$SelectionPath = "",
    [string]$SelectionProbeGrokExe = "",
    [string]$SupervisorRoot = "",
    [string]$SelectorReleasePointer = "",
    [string]$DispatchEpochId = "",
    [string]$DispatchEpochSource = "",
    [int]$DispatchEpochMaxAgeSec = 0,
    [string]$QuotaSnapshotId = "",
    [string]$QuotaSnapshotRef = "",
    [string]$QuotaSnapshotSha256 = "",
    [string]$QuotaResolutionStatus = "",
    [string]$QuotaResolutionError = "",
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
    [string]$CommonLogicalContractPath = "",
    [string]$CommonWorkKey = "",
    [string]$CommonOperationId = "",
    [string]$CommonTaskContractRef = "",
    [string]$CommonParentOperationId = "",
    [string]$CommonCorrelationId = "",
    [string]$CommonSubjectManifestSha256 = "",
    [string]$CommonFrozenContextSha256 = "",
    [string]$CommonContextManifestPath = "",
    [string]$CommonRulesFile = "",
    [string]$CommonRulesSha256 = "",
    [string]$CommonCandidateOutputRoot = "",
    [string]$CommonPhase = "",
    [string[]]$CommonWriteDomains = @(),
    [string[]]$CommonDependsOn = @(),
    [string]$CommonPriorAttemptReceiptPath = "",
    [string]$CommonAdapterRoot = "",
    [string]$CommonPythonExe = "python",
    [string]$DispatchId = "",
    [string]$PoolId = "",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
. (Join-Path $bridge "GrokWindowsPathIdentity.ps1")
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
if ([string]::IsNullOrWhiteSpace($Model)) {
    throw "CODEX_GROK_MODEL_REQUIRED"
}
if ([string]::IsNullOrWhiteSpace($SelectionPath)) {
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
        -SelectionResolver $selectionResolver `
        -RuntimeRoot $RuntimeRoot `
        -ReleasePointer $SelectorReleasePointer
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
$commonPrepareReceipt = $null
$commonRequested = (
    -not [string]::IsNullOrWhiteSpace($CommonLogicalContractPath) -or
    -not [string]::IsNullOrWhiteSpace($CommonWorkKey) -or
    -not [string]::IsNullOrWhiteSpace($CommonOperationId) -or
    -not [string]::IsNullOrWhiteSpace($CommonSubjectManifestSha256) -or
    -not [string]::IsNullOrWhiteSpace($CommonFrozenContextSha256) -or
    -not [string]::IsNullOrWhiteSpace($CommonContextManifestPath) -or
    -not [string]::IsNullOrWhiteSpace($CommonRulesFile) -or
    -not [string]::IsNullOrWhiteSpace($CommonRulesSha256) -or
    -not [string]::IsNullOrWhiteSpace($CommonCandidateOutputRoot) -or
    -not [string]::IsNullOrWhiteSpace($CommonPhase) -or
    -not [string]::IsNullOrWhiteSpace($CommonPriorAttemptReceiptPath)
)
if ($commonRequested) {
    if ($N -ne 1) { throw "CODEX_GROK_COMMON_REQUIRES_SINGLE_LANE" }
    if ([string]::IsNullOrWhiteSpace($CommonRulesFile)) {
        throw "CODEX_GROK_COMMON_REQUIRED: rules_file"
    }
    if ($CommonRulesSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "CODEX_GROK_COMMON_RULES_SHA256_INVALID"
    }
    try { $CommonRulesFile = [IO.Path]::GetFullPath($CommonRulesFile) }
    catch { throw "CODEX_GROK_COMMON_RULES_FILE_INVALID: $CommonRulesFile" }
    if (-not (Test-Path -LiteralPath $CommonRulesFile -PathType Leaf)) {
        throw "CODEX_GROK_COMMON_RULES_FILE_MISSING: $CommonRulesFile"
    }
    $observedRulesSha256 = (Get-FileHash -LiteralPath $CommonRulesFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not [string]::Equals($observedRulesSha256, $CommonRulesSha256, [StringComparison]::Ordinal)) {
        throw "CODEX_GROK_COMMON_RULES_FILE_HASH_MISMATCH"
    }
    if (-not [string]::IsNullOrWhiteSpace($CommonCandidateOutputRoot)) {
        try { $CommonCandidateOutputRoot = [IO.Path]::GetFullPath($CommonCandidateOutputRoot) }
        catch { throw "CODEX_GROK_COMMON_CANDIDATE_OUTPUT_ROOT_INVALID: $CommonCandidateOutputRoot" }
        if (-not (Test-Path -LiteralPath $CommonCandidateOutputRoot -PathType Container)) {
            throw "CODEX_GROK_COMMON_CANDIDATE_OUTPUT_ROOT_MISSING: $CommonCandidateOutputRoot"
        }
        $resolvedCwd = [IO.Path]::GetFullPath($Cwd)
        if (-not [string]::Equals($CommonCandidateOutputRoot, $resolvedCwd, [StringComparison]::OrdinalIgnoreCase)) {
            throw "CODEX_GROK_COMMON_CANDIDATE_OUTPUT_ROOT_CWD_MISMATCH"
        }
        $expectedCandidateWriteDomain = "candidate_output_root:" + ($CommonCandidateOutputRoot.Replace('\', '/').TrimEnd('/').ToLowerInvariant())
        if (
            @($CommonWriteDomains).Count -ne 1 -or
            -not [string]::Equals([string]$CommonWriteDomains[0], $expectedCandidateWriteDomain, [StringComparison]::Ordinal)
        ) {
            throw "CODEX_GROK_COMMON_CANDIDATE_WRITE_DOMAIN_MISMATCH"
        }
    }
    if (
        -not [string]::IsNullOrWhiteSpace($CommonLogicalContractPath) -and
        -not [string]::IsNullOrWhiteSpace($CommonContextManifestPath)
    ) {
        throw "CODEX_GROK_COMMON_CONTEXT_MANIFEST_REQUIRES_PREPARATION"
    }
    if ($null -eq $supervisorCapability) {
        $supervisorCapability = Resolve-GrokSupervisorSelectorRoot `
            -SupervisorRoot $SupervisorRoot `
            -Cwd $Cwd `
            -SelectionResolver $selectionResolver `
            -RuntimeRoot $RuntimeRoot `
            -ReleasePointer $SelectorReleasePointer
    }
    if ([string]::IsNullOrWhiteSpace($CommonAdapterRoot)) {
        $CommonAdapterRoot = [string]$supervisorCapability.resolved_root
    }
    $CommonAdapterRoot = [IO.Path]::GetFullPath($CommonAdapterRoot)
    if (-not (Test-Path -LiteralPath $CommonAdapterRoot -PathType Container)) {
        throw "CODEX_GROK_COMMON_ADAPTER_ROOT_MISSING: $CommonAdapterRoot"
    }
    if ([string]::IsNullOrWhiteSpace($CommonLogicalContractPath)) {
        foreach ($entry in ([ordered]@{
            work_key = $CommonWorkKey
            operation_id = $CommonOperationId
            subject_manifest_sha256 = $CommonSubjectManifestSha256
            phase = $CommonPhase
            prompt_file = $PromptFile
        }).GetEnumerator()) {
            if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) {
                throw "CODEX_GROK_COMMON_REQUIRED: $($entry.Key)"
            }
        }
        if (
            [string]::IsNullOrWhiteSpace($CommonFrozenContextSha256) -and
            [string]::IsNullOrWhiteSpace($CommonContextManifestPath)
        ) {
            throw "CODEX_GROK_COMMON_REQUIRED: frozen_context_sha256_or_context_manifest_path"
        }
        if (-not [string]::IsNullOrWhiteSpace($CommonContextManifestPath)) {
            try { $CommonContextManifestPath = [IO.Path]::GetFullPath($CommonContextManifestPath) }
            catch { throw "CODEX_GROK_COMMON_CONTEXT_MANIFEST_INVALID: $CommonContextManifestPath" }
            if (-not (Test-Path -LiteralPath $CommonContextManifestPath -PathType Leaf)) {
                throw "CODEX_GROK_COMMON_CONTEXT_MANIFEST_MISSING: $CommonContextManifestPath"
            }
        }
        $prepareScript = Join-Path $CommonAdapterRoot "scripts\prepare_direct_worker_pool_common_contract.py"
        if (-not (Test-Path -LiteralPath $prepareScript -PathType Leaf)) {
            throw "CODEX_GROK_COMMON_PREPARER_MISSING: $prepareScript"
        }
        if (-not (Get-Command $CommonPythonExe -ErrorAction SilentlyContinue)) {
            throw "CODEX_GROK_COMMON_PYTHON_MISSING: $CommonPythonExe"
        }
        $commonContractDir = Join-Path $RuntimeRoot (
            "state\codex_dispatch_grok_worker_pool\common_contracts\" + $dispatchId
        )
        New-Item -ItemType Directory -Force -Path $commonContractDir | Out-Null
        $CommonLogicalContractPath = Join-Path $commonContractDir "logical_contract.json"
        $prepareArgs = @(
            $prepareScript,
            "--prompt-file", ([IO.Path]::GetFullPath($PromptFile)),
            "--selection-receipt", $SelectionPath,
            "--subject-manifest-sha256", $CommonSubjectManifestSha256,
            "--work-key", $CommonWorkKey,
            "--operation-id", $CommonOperationId,
            "--task-contract-ref", $CommonTaskContractRef,
            "--parent-operation-id", $CommonParentOperationId,
            "--correlation-id", $CommonCorrelationId,
            "--rules-file", $CommonRulesFile,
            "--min-result-chars", ([string]$MinResultChars),
            "--deadline-seconds", ([string]$TimeoutSec),
            "--output", $CommonLogicalContractPath
        )
        if (-not [string]::IsNullOrWhiteSpace($CommonFrozenContextSha256)) {
            $prepareArgs += @("--frozen-context-sha256", $CommonFrozenContextSha256)
        }
        if (-not [string]::IsNullOrWhiteSpace($CommonContextManifestPath)) {
            $prepareArgs += @("--context-manifest-file", $CommonContextManifestPath)
        }
        foreach ($marker in @($RequiredResultMarkers)) {
            $prepareArgs += @("--required-result-marker", [string]$marker)
        }
        if ($RequireJsonObject) { $prepareArgs += "--require-json-object" }
        if ($JsonSchemaPath) {
            $prepareArgs += @("--json-schema-file", ([IO.Path]::GetFullPath($JsonSchemaPath)))
        }
        if (@($CommonWriteDomains).Count -gt 0) { $prepareArgs += "--write" }
        $prepareOutput = @(& $CommonPythonExe @prepareArgs 2>&1)
        $prepareExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
        if ($prepareExit -ne 0 -or -not (Test-Path -LiteralPath $CommonLogicalContractPath -PathType Leaf)) {
            throw (
                "CODEX_GROK_COMMON_PREPARE_FAILED: exit=$prepareExit output=" +
                (($prepareOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine)
            )
        }
        $prepareReceiptPath = Join-Path $commonContractDir "contract_prepare_receipt.json"
        if (-not (Test-Path -LiteralPath $prepareReceiptPath -PathType Leaf)) {
            throw "CODEX_GROK_COMMON_PREPARE_RECEIPT_MISSING: $prepareReceiptPath"
        }
        try {
            $commonPrepareReceipt = Get-Content -LiteralPath $prepareReceiptPath -Raw -Encoding UTF8 |
                ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            throw "CODEX_GROK_COMMON_PREPARE_RECEIPT_INVALID: $prepareReceiptPath"
        }
        $preparedContextSha256 = [string]$commonPrepareReceipt.frozen_context_sha256
        if ($preparedContextSha256 -notmatch '^[0-9a-f]{64}$') {
            throw "CODEX_GROK_COMMON_PREPARE_CONTEXT_INVALID"
        }
        if (
            -not [string]::IsNullOrWhiteSpace($CommonContextManifestPath) -and
            [string]$commonPrepareReceipt.context_binding_mode -ne "validated_context_slice_manifest"
        ) {
            throw "CODEX_GROK_COMMON_CONTEXT_MANIFEST_NOT_BOUND"
        }
        if (
            -not [string]::Equals([string]$commonPrepareReceipt.rules_sha256, $CommonRulesSha256, [StringComparison]::Ordinal) -or
            -not [string]::Equals(
                [IO.Path]::GetFullPath([string]$commonPrepareReceipt.rules_file),
                $CommonRulesFile,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            throw "CODEX_GROK_COMMON_RULES_NOT_BOUND"
        }
        $CommonFrozenContextSha256 = $preparedContextSha256
    }
}
$dispatchCwdLease = Open-GrokDirectoryIdentityLease -Path $Cwd
try {
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
    route_role = "normal_leg_a_bounded_online_current_tui"
    route_selection = "selected_by_task_fit_or_existing_route_receipt"
    route_continuity = "continuous_or_resume_does_not_switch_leg"
    is_unconditional_default = $false
    leg_b_cn = "explicit durable handoff -> Temporal + Docker houtai-gongren + worker-internal LangGraph"
    prohibited_cn = @(
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
    selector_task_cwd_used = $supervisorCapability.task_cwd_used_for_selector -eq $true
    selector_release_binding = $supervisorCapability.release_binding
    dispatch_epoch_id = $DispatchEpochId
    dispatch_epoch_source = $DispatchEpochSource
    dispatch_epoch_max_age_sec = $DispatchEpochMaxAgeSec
    quota_snapshot_id = $QuotaSnapshotId
    quota_snapshot_ref = $QuotaSnapshotRef
    quota_snapshot_sha256 = $QuotaSnapshotSha256
    quota_resolution_status = $QuotaResolutionStatus
    quota_resolution_error = $QuotaResolutionError
    selector_probe_reports = @($supervisorCapability.candidate_reports)
    json_schema_path = $JsonSchemaPath
    common_contract_path = $CommonLogicalContractPath
    common_context_manifest_path = $CommonContextManifestPath
    common_rules_file = $CommonRulesFile
    common_rules_sha256 = $CommonRulesSha256
    common_candidate_output_root = $CommonCandidateOutputRoot
    common_context_binding_mode = if ($null -ne $commonPrepareReceipt) {
        [string]$commonPrepareReceipt.context_binding_mode
    } else { "" }
    common_context_manifest_sha256 = if ($null -ne $commonPrepareReceipt) {
        [string]$commonPrepareReceipt.context_manifest_sha256
    } else { "" }
    common_phase = $CommonPhase
    common_adapter_root = $CommonAdapterRoot
    cwd = $Cwd
    cwd_final_path = [string]$dispatchCwdLease.final_path
    cwd_object_id = [string]$dispatchCwdLease.object_id
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
if ($CommonLogicalContractPath) {
    $args.CommonLogicalContractPath = $CommonLogicalContractPath
    $args.CommonSubjectManifestSha256 = $CommonSubjectManifestSha256
    $args.CommonFrozenContextSha256 = $CommonFrozenContextSha256
    $args.CommonRulesFile = $CommonRulesFile
    $args.CommonRulesSha256 = $CommonRulesSha256
    $args.CommonCandidateOutputRoot = $CommonCandidateOutputRoot
    $args.CommonPhase = $CommonPhase
    $args.CommonWriteDomains = @($CommonWriteDomains)
    $args.CommonDependsOn = @($CommonDependsOn)
    $args.CommonAdapterRoot = $CommonAdapterRoot
    $args.CommonPythonExe = $CommonPythonExe
}
if ($CommonPriorAttemptReceiptPath) {
    $args.CommonPriorAttemptReceiptPath = $CommonPriorAttemptReceiptPath
}
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
        $poolCwdLease = Open-GrokDirectoryIdentityLease -Path ([string]$poolSummary.cwd)
        try {
        if (
            -not [string]::Equals(
                [string]$poolSummary.selection_decision_sha256,
                [string]$selection.decision_sha256,
                [StringComparison]::Ordinal
            ) -or
            -not [string]::Equals([string]$poolSummary.model, $Model, [StringComparison]::Ordinal) -or
            -not (Test-GrokDirectoryObjectIdentityEqual -Left $poolCwdLease -Right $dispatchCwdLease) -or
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
        [void](Assert-GrokDirectoryIdentityLeaseStable -Lease $poolCwdLease)
        [void](Assert-GrokDirectoryIdentityLeaseStable -Lease $dispatchCwdLease)
        }
        finally {
            Close-GrokDirectoryIdentityLease -Lease $poolCwdLease
        }
        $dispatchMeta.pool_summary_sha256 = (
            Get-FileHash -LiteralPath $poolSummaryPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $dispatchMeta.pool_all_ok = $poolSummary.all_ok -eq $true
        $dispatchMeta.pool_reuse_skipped_execution =
            $poolSummary.reuse_skipped_execution -eq $true
        $dispatchMeta.pool_effective_ok = (
            $dispatchMeta.pool_all_ok -eq $true -or
            $dispatchMeta.pool_reuse_skipped_execution -eq $true
        )
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
    $dispatchMeta.pool_effective_ok -eq $true -and
    $dispatchMeta.pool_acceptance_contract_ok -eq $true
) { "accepted" } else { "rejected" }
[System.IO.File]::WriteAllText(
    $dispatchMetaPath,
    ($dispatchMeta | ConvertTo-Json -Depth 6),
    $utf8
)
Copy-Item $dispatchMetaPath (Join-Path $metaDir "latest.json") -Force

}
finally {
    Close-GrokDirectoryIdentityLease -Lease $dispatchCwdLease
}

exit $code
