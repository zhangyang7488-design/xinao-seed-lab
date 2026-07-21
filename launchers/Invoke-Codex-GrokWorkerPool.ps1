#Requires -Version 7.0
<#[
.SYNOPSIS
  Public bounded Grok entry with stable selector, dispatch epoch, and package mode.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 32)]
    [int]$N = 1,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [Alias("PackageManifestPath")]
    [string]$DispatchEnvelopePath = "",
    [string]$Cwd = "",
    [string]$SupervisorRoot = "",
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Model,
    [string]$SelectionPath = "",
    [string]$SelectorReleasePointer = "",
    [string]$DispatchEpochId = "",
    [string]$DispatchEpisodeId = "",
    [ValidateRange(60, 86400)]
    [int]$DispatchEpochMaxAgeSec = 1800,
    [string]$InvalidateDispatchEpochReason = "",
    [switch]$ReplicaMode,
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
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
    [string]$TaskRunRoot = "",
    [string]$TaskRunId = "",
    [string]$TaskRunCli = "C:\Users\xx363\.codex\skills\verified-agent-loop\scripts\task_run.py",
    [string]$CheckpointPath = "D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\state\session_checkpoint.json",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Model)) {
    throw "CODEX_GROK_MODEL_REQUIRED"
}

function Get-CodexGrokUtf8Sha256([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally { $algorithm.Dispose() }
}

function Resolve-CodexGrokOrdinaryDispatchEpoch {
    $identityKind = ""
    $identityValue = $null
    if (-not [string]::IsNullOrWhiteSpace($DispatchEpisodeId)) {
        $identityKind = "dispatch_episode_id"
        $identityValue = $DispatchEpisodeId.Trim()
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:XINAO_DISPATCH_EPISODE_ID)) {
        $identityKind = "environment_dispatch_episode_id"
        $identityValue = $env:XINAO_DISPATCH_EPISODE_ID.Trim()
    }
    else {
        $stableContext = [ordered]@{}
        if (-not [string]::IsNullOrWhiteSpace($TaskRunId)) {
            $stableContext.task_run_id = $TaskRunId.Trim()
        }
        if (-not [string]::IsNullOrWhiteSpace($CommonParentOperationId)) {
            $stableContext.parent_operation_id = $CommonParentOperationId.Trim()
        }
        if (-not [string]::IsNullOrWhiteSpace($CommonCorrelationId)) {
            $stableContext.correlation_id = $CommonCorrelationId.Trim()
        }
        if ($stableContext.Count -eq 0) {
            throw "CODEX_GROK_DISPATCH_EPISODE_IDENTITY_REQUIRED: pass DispatchEpisodeId, TaskRunId, CommonParentOperationId, CommonCorrelationId, or XINAO_DISPATCH_EPISODE_ID"
        }
        $identityKind = if ($stableContext.Count -eq 1) {
            [string]@($stableContext.Keys)[0]
        } else { "stable_context_tuple" }
        $identityValue = $stableContext
    }
    $identity = [ordered]@{
        schema_version = "xinao.codex_grok_dispatch_epoch_identity.v1"
        identity_kind = $identityKind
        identity_value = $identityValue
    }
    $canonical = $identity | ConvertTo-Json -Compress
    [pscustomobject]@{
        epoch_id = "grok_epoch_v1_" + (Get-CodexGrokUtf8Sha256 $canonical)
        source = $identityKind
    }
}

function Invoke-CodexGrokQuotaEpochQuery(
    [string]$QuotaEntry,
    [string]$EpochId,
    [string]$Runtime,
    [string]$InvalidateReason
) {
    $queryArguments = @{
        Json = $true
        EpochId = $EpochId
        RuntimeRoot = $Runtime
    }
    if (-not [string]::IsNullOrWhiteSpace($InvalidateReason)) {
        $queryArguments.InvalidateReason = $InvalidateReason
    }
    $quotaLine = @(
        & $QuotaEntry @queryArguments 2>&1 | ForEach-Object { [string]$_ }
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0 -or -not $quotaLine) {
        throw "quota query returned no valid resolution"
    }
    $quotaLine | ConvertFrom-Json -ErrorAction Stop
}

function Get-CodexGrokQuotaSnapshotAgeSec($Resolution) {
    $raw = [string]$Resolution.snapshot.queried_at
    $parsed = [DateTimeOffset]::MinValue
    if (
        [string]::IsNullOrWhiteSpace($raw) -or
        -not [DateTimeOffset]::TryParse(
            $raw,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$parsed
        )
    ) {
        throw "CODEX_GROK_QUOTA_SNAPSHOT_TIME_INVALID"
    }
    [Math]::Max(0.0, ([DateTimeOffset]::UtcNow - $parsed.ToUniversalTime()).TotalSeconds)
}

$packageMode = -not [string]::IsNullOrWhiteSpace($DispatchEnvelopePath)
$dispatchEpochSource = ""
if ($packageMode) {
    if ($N -ne 1 -or $ReplicaMode -or -not [string]::IsNullOrWhiteSpace($Prompt) -or -not [string]::IsNullOrWhiteSpace($PromptFile)) {
        throw "CODEX_GROK_PACKAGE_MODE_PARAMETER_CONFLICT"
    }
    try {
        $dispatchEnvelope = Get-Content -LiteralPath $DispatchEnvelopePath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "CODEX_GROK_DISPATCH_ENVELOPE_INVALID: $DispatchEnvelopePath"
    }
    $manifestEpochId = [string]$dispatchEnvelope.dispatch_epoch.epoch_id
    if ([string]::IsNullOrWhiteSpace($manifestEpochId)) {
        throw "CODEX_GROK_PACKAGE_EPOCH_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($DispatchEpochId)) {
        $DispatchEpochId = $manifestEpochId
    }
    elseif (-not [string]::Equals($DispatchEpochId, $manifestEpochId, [StringComparison]::Ordinal)) {
        throw "CODEX_GROK_PACKAGE_EPOCH_MISMATCH"
    }
    $dispatchEpochSource = "neutral_package_manifest"
    if (-not [string]::IsNullOrWhiteSpace($InvalidateDispatchEpochReason)) {
        throw "CODEX_GROK_PACKAGE_EPOCH_INVALIDATE_RESEAL_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($TaskRunRoot)) {
        throw "CODEX_GROK_PACKAGE_TASK_RUN_ROOT_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($TaskRunId)) {
        throw "CODEX_GROK_PACKAGE_TASK_RUN_ID_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($CheckpointPath)) {
        throw "CODEX_GROK_PACKAGE_CHECKPOINT_REQUIRED"
    }
}
else {
    if ([string]::IsNullOrWhiteSpace($Cwd)) { throw "CODEX_GROK_CWD_REQUIRED" }
    if ([string]::IsNullOrWhiteSpace($Prompt) -eq [string]::IsNullOrWhiteSpace($PromptFile)) {
        throw "CODEX_GROK_EXACTLY_ONE_PROMPT_SOURCE_REQUIRED"
    }
    if ($N -gt 1 -and -not $ReplicaMode) {
        throw "CODEX_GROK_MULTI_LANE_REQUIRES_EXPLICIT_REPLICA_MODE"
    }
    if ([string]::IsNullOrWhiteSpace($DispatchEpochId)) {
        $resolvedEpoch = Resolve-CodexGrokOrdinaryDispatchEpoch
        $DispatchEpochId = [string]$resolvedEpoch.epoch_id
        $dispatchEpochSource = [string]$resolvedEpoch.source
    }
    else {
        $dispatchEpochSource = "explicit_dispatch_epoch_id"
    }
}

$DispatchId = "cdx_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$PoolId = "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))

# One advisory query per epoch. Failure is recorded but never blocks positive-benefit work.
$quotaEntry = Join-Path $RuntimeRoot "state\quota_query\Get-AIQuota.ps1"
$quotaResolution = $null
$quotaError = ""
if (Test-Path -LiteralPath $quotaEntry -PathType Leaf) {
    try {
        $quotaResolution = Invoke-CodexGrokQuotaEpochQuery `
            -QuotaEntry $quotaEntry `
            -EpochId $DispatchEpochId `
            -Runtime $RuntimeRoot `
            -InvalidateReason $InvalidateDispatchEpochReason
    }
    catch { $quotaError = "$_" }
}
else { $quotaError = "quota entry missing: $quotaEntry" }

if ($null -ne $quotaResolution) {
    try {
        $quotaAgeSec = Get-CodexGrokQuotaSnapshotAgeSec $quotaResolution
        if ($quotaAgeSec -ge $DispatchEpochMaxAgeSec) {
            if ($packageMode) {
                throw "CODEX_GROK_PACKAGE_EPOCH_EXPIRED_RESEAL_REQUIRED"
            }
            $quotaResolution = Invoke-CodexGrokQuotaEpochQuery `
                -QuotaEntry $quotaEntry `
                -EpochId $DispatchEpochId `
                -Runtime $RuntimeRoot `
                -InvalidateReason ("dispatch_epoch_expired_after_{0}_seconds" -f [int][Math]::Floor($quotaAgeSec))
        }
    }
    catch {
        if ([string]$_.Exception.Message -match '^CODEX_GROK_PACKAGE_EPOCH_') { throw }
        $quotaError = "$_"
        $quotaResolution = $null
    }
}

$bridgeRoot = "C:\Users\xx363\Grok_Admin_Isolated\workspace\grok-admin-bridge"
if ($packageMode) {
    if (
        $null -ne $quotaResolution -and
        (
            [string]$quotaResolution.snapshot.snapshot_id -ne [string]$dispatchEnvelope.dispatch_epoch.quota_snapshot_id -or
            -not [string]::Equals(
                [IO.Path]::GetFullPath([string]$quotaResolution.snapshot.snapshot_ref),
                [IO.Path]::GetFullPath([string]$dispatchEnvelope.dispatch_epoch.quota_snapshot_ref),
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            [string]$quotaResolution.snapshot.snapshot_sha256 -ne [string]$dispatchEnvelope.dispatch_epoch.quota_snapshot_sha256
        )
    ) {
        throw "CODEX_GROK_PACKAGE_QUOTA_SNAPSHOT_MISMATCH"
    }
    $packageEntry = Join-Path $bridgeRoot "Invoke-CodexGrokPackageBatch.ps1"
    if (-not (Test-Path -LiteralPath $packageEntry -PathType Leaf)) {
        throw "CODEX_GROK_PACKAGE_ENTRY_MISSING: $packageEntry"
    }
    $packageArgs = @{
        DispatchEnvelopePath = $DispatchEnvelopePath
        Model = $Model
        RuntimeRoot = $RuntimeRoot
        SelectorReleasePointer = $SelectorReleasePointer
        TimeoutSec = $TimeoutSec
        TaskRunRoot = $TaskRunRoot
        TaskRunId = $TaskRunId
        TaskRunCli = $TaskRunCli
        CheckpointPath = $CheckpointPath
    }
    if ($Quiet) { $packageArgs.Quiet = $true }
    & $packageEntry @packageArgs
    exit $LASTEXITCODE
}

$entry = Join-Path $bridgeRoot "Invoke-CodexDispatchGrokWorkerPool.ps1"
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) {
    throw "CODEX_GROK_WORKER_POOL_ENTRY_MISSING: $entry"
}
$arguments = @{
    N = $N
    Model = $Model
    SelectionPath = $SelectionPath
    SupervisorRoot = $SupervisorRoot
    SelectorReleasePointer = $SelectorReleasePointer
    RuntimeRoot = $RuntimeRoot
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
    DispatchId = $DispatchId
    PoolId = $PoolId
    Cwd = $Cwd
    CommonPythonExe = $CommonPythonExe
    DispatchEpochId = $DispatchEpochId
    DispatchEpochSource = $dispatchEpochSource
    DispatchEpochMaxAgeSec = $DispatchEpochMaxAgeSec
    QuotaResolutionError = $quotaError
}
if ($null -ne $quotaResolution) {
    $arguments.QuotaSnapshotId = [string]$quotaResolution.snapshot.snapshot_id
    $arguments.QuotaSnapshotRef = [string]$quotaResolution.snapshot.snapshot_ref
    $arguments.QuotaSnapshotSha256 = [string]$quotaResolution.snapshot.snapshot_sha256
    $arguments.QuotaResolutionStatus = [string]$quotaResolution.status
}
if ($Prompt) { $arguments.Prompt = $Prompt }
if ($PromptFile) { $arguments.PromptFile = $PromptFile }
if ($RequireJsonObject) { $arguments.RequireJsonObject = $true }
if ($JsonSchemaPath) { $arguments.JsonSchemaPath = $JsonSchemaPath }
if ($CommonWorkKey) { $arguments.CommonWorkKey = $CommonWorkKey }
if ($CommonOperationId) { $arguments.CommonOperationId = $CommonOperationId }
if ($CommonTaskContractRef) { $arguments.CommonTaskContractRef = $CommonTaskContractRef }
if ($CommonParentOperationId) { $arguments.CommonParentOperationId = $CommonParentOperationId }
if ($CommonCorrelationId) { $arguments.CommonCorrelationId = $CommonCorrelationId }
if ($CommonSubjectManifestSha256) { $arguments.CommonSubjectManifestSha256 = $CommonSubjectManifestSha256 }
if ($CommonFrozenContextSha256) { $arguments.CommonFrozenContextSha256 = $CommonFrozenContextSha256 }
if ($CommonContextManifestPath) { $arguments.CommonContextManifestPath = $CommonContextManifestPath }
if ($CommonRulesFile) { $arguments.CommonRulesFile = $CommonRulesFile }
if ($CommonRulesSha256) { $arguments.CommonRulesSha256 = $CommonRulesSha256 }
if ($CommonCandidateOutputRoot) { $arguments.CommonCandidateOutputRoot = $CommonCandidateOutputRoot }
if ($CommonPhase) { $arguments.CommonPhase = $CommonPhase }
if ($CommonPriorAttemptReceiptPath) { $arguments.CommonPriorAttemptReceiptPath = $CommonPriorAttemptReceiptPath }
if ($CommonAdapterRoot) { $arguments.CommonAdapterRoot = $CommonAdapterRoot }
if (@($CommonWriteDomains).Count -gt 0) { $arguments.CommonWriteDomains = @($CommonWriteDomains) }
if (@($CommonDependsOn).Count -gt 0) { $arguments.CommonDependsOn = @($CommonDependsOn) }
if ($SkipPauseGate) { $arguments.SkipPauseGate = $true }
if ($Quiet) { $arguments.Quiet = $true }

& $entry @arguments
exit $LASTEXITCODE
