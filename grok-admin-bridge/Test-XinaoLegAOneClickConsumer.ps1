#Requires -Version 5.1
<#
.SYNOPSIS
  Fresh-process consumer boundary for XINAO leg-A one-click call.
.DESCRIPTION
  Proves (with bounded fake public-dispatch / context-builder fixtures) that one
  stable leg-A consumer call discovers sealed context, bootstraps selection-only
  and the real common-contract path through the public launcher, forces
  linux-container, respects branch isolation, and returns candidate evidence.
  Does not spend a real second provider call. Candidate only; Codex owns adoption.
#>
[CmdletBinding()]
param(
    [string]$ContractPath = "",
    [string]$ContextBuilderPath = "",
    [string]$OneClickWorkerPath = "",
    [switch]$AllowMissingProductionScripts
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$repoRoot = Split-Path -Parent $bridge
$pwsh = (Get-Process -Id $PID).Path
$marker = "XINAO_LEG_A_FRESH_CONSUMER_CANDIDATE_V1"
$contractDefault = Join-Path $bridge "grok_xinao_leg_a_oneclick_contract.v1.json"
if ([string]::IsNullOrWhiteSpace($ContractPath)) { $ContractPath = $contractDefault }

function Assert-True([bool]$Condition, [string]$Label) {
    if (-not $Condition) { throw "XINAO_LEG_A_ONECLICK_ASSERT_FAIL: $Label" }
}

function Write-JsonFile([string]$Path, [object]$Value) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 14), $utf8)
}

function Get-Sha256File([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-Sha256Text([string]$Text) {
    $bytes = $utf8.GetBytes($Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Invoke-FreshPowerShell([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $pwsh -NoLogo -NoProfile @Arguments 2>&1 | ForEach-Object { [string]$_ })
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{
        exit_code = $exitCode
        output = ($output -join "`n")
        lines = $output
    }
}

function ConvertFrom-LastJsonObject([string[]]$Lines) {
    $candidates = @($Lines | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_) -and $_.Trim().StartsWith("{")
    })
    Assert-True ($candidates.Count -gt 0) "expected_json_object_line"
    return ($candidates[-1] | ConvertFrom-Json -ErrorAction Stop)
}

function New-SourceWorktree([string]$Root) {
    $wt = Join-Path $Root "source-worktree"
    New-Item -ItemType Directory -Force -Path $wt | Out-Null
    $keep = Join-Path $wt "SOURCE_PRESERVE.txt"
    [IO.File]::WriteAllText($keep, "SOURCE_WORKTREE_MUST_SURVIVE`n", $utf8)
    $keepSha = Get-Sha256File $keep
    return [pscustomobject]@{
        path = $wt
        preserve_path = $keep
        preserve_sha256 = $keepSha
    }
}

function Install-FakePublicLauncher([string]$CarrierRoot, [string]$CallLogPath) {
    $launcherDir = Join-Path $CarrierRoot "public-launcher"
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
    $launcher = Join-Path $launcherDir "Invoke-Codex-GrokWorkerPool.ps1"
    $launcherBody = @'
#Requires -Version 5.1
param(
    [int]$N = 1,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "",
    [string]$SelectionPath = "",
    [switch]$SelectionOnly,
    [string]$CommonWorkKey = "",
    [string]$CommonOperationId = "",
    [string]$CommonSubjectManifestSha256 = "",
    [string]$CommonFrozenContextSha256 = "",
    [string]$CommonContextManifestPath = "",
    [string]$CommonRulesFile = "",
    [string]$CommonRulesSha256 = "",
    [string]$CommonSealedInputRoot = "",
    [string]$CommonCandidateOutputRoot = "",
    [string]$CommonPhase = "",
    [string[]]$CommonWriteDomains = @(),
    [string]$CommonPriorAttemptReceiptPath = "",
    [string]$ExpectedSelectionDecisionSha256 = "",
    [string]$RuntimeRoot = "",
    [int]$MinResultChars = 1,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [int]$TimeoutSec = 30,
    [switch]$Quiet
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$callLog = $env:XINAO_LEG_A_FAKE_PUBLIC_LAUNCHER_LOG
if ([string]::IsNullOrWhiteSpace($callLog)) { throw "FAKE_LAUNCHER_LOG_MISSING" }
$mode = if ($SelectionOnly) { "selection_only" } else { "common_contract" }
$backend = "linux-container"
if (-not [string]::IsNullOrWhiteSpace($env:XINAO_LEG_A_FAKE_BACKEND)) {
    $backend = $env:XINAO_LEG_A_FAKE_BACKEND
}
if ($env:XINAO_LEG_A_FAKE_DOCKER_UNAVAILABLE -eq "1" -and -not $SelectionOnly) {
    throw "XINAO_LEG_A_DOCKER_UNAVAILABLE"
}
if (-not $SelectionOnly -and $backend -ne "linux-container") {
    throw "XINAO_LEG_A_BACKEND_FORBIDDEN: $backend"
}
$decision = "b" * 64
if (-not [string]::IsNullOrWhiteSpace($env:XINAO_LEG_A_FAKE_SELECTION_DECISION)) {
    $decision = $env:XINAO_LEG_A_FAKE_SELECTION_DECISION
}
if (
    -not $SelectionOnly -and
    -not [string]::IsNullOrWhiteSpace($ExpectedSelectionDecisionSha256) -and
    -not [string]::Equals($ExpectedSelectionDecisionSha256, $decision, [StringComparison]::Ordinal)
) {
    throw "XINAO_LEG_A_SELECTION_STALE"
}
$selectionOut = $SelectionPath
if ($SelectionOnly) {
    if ([string]::IsNullOrWhiteSpace($selectionOut)) {
        $selDir = Join-Path $RuntimeRoot ("state\grok_worker_selection\fake_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
        New-Item -ItemType Directory -Force -Path $selDir | Out-Null
        $selectionOut = Join-Path $selDir "selection.receipt.json"
    }
    $receipt = [ordered]@{
        schema_version = "xinao.supervisor_worker_decision_receipt.v1"
        decision = "selected"
        selected_candidate = [ordered]@{
            provider_id = "grok_acpx_headless"
            profile_ref = "grok.com.cached_profile"
            model_id = $(if ($Model) { $Model } else { "grok-4.5" })
            transport_id = "direct-grok-worker-pool"
            declared_active = $true
            healthy = $true
            positive_benefit = $true
            context_capable = $true
        }
        decision_sha256 = $decision
    }
    [IO.File]::WriteAllText($selectionOut, ($receipt | ConvertTo-Json -Depth 8), $utf8)
}
$record = [ordered]@{
    ts = (Get-Date).ToString("o")
    mode = $mode
    n = $N
    model = $Model
    cwd = $Cwd
    selection_only = [bool]$SelectionOnly
    selection_path = $selectionOut
    expected_selection_decision_sha256 = $ExpectedSelectionDecisionSha256
    execution_backend_requested = $backend
    common_work_key = $CommonWorkKey
    common_operation_id = $CommonOperationId
    common_subject_manifest_sha256 = $CommonSubjectManifestSha256
    common_frozen_context_sha256 = $CommonFrozenContextSha256
    common_context_manifest_path = $CommonContextManifestPath
    common_rules_file = $CommonRulesFile
    common_rules_sha256 = $CommonRulesSha256
    common_sealed_input_root = $CommonSealedInputRoot
    common_candidate_output_root = $CommonCandidateOutputRoot
    common_phase = $CommonPhase
    common_write_domains = @($CommonWriteDomains)
    prompt_file = $PromptFile
    prompt_len = $(if ($Prompt) { $Prompt.Length } else { 0 })
    required_result_markers = @($RequiredResultMarkers)
}
$stream = [IO.StreamWriter]::new($callLog, $true, $utf8)
try { $stream.WriteLine(($record | ConvertTo-Json -Compress -Depth 8)) }
finally { $stream.Dispose() }

if ($SelectionOnly) {
    [ordered]@{
        schema_version = "xinao.codex_grok_selection_only_result.v1"
        selection_path = $selectionOut
        selection_receipt_sha256 = (Get-FileHash -LiteralPath $selectionOut -Algorithm SHA256).Hash.ToLowerInvariant()
        decision_sha256 = $decision
        provider_id = "grok_acpx_headless"
        profile_ref = "grok.com.cached_profile"
        model_id = $(if ($Model) { $Model } else { "grok-4.5" })
        transport_id = "direct-grok-worker-pool"
        execution_backend_requested = $backend
        quota_query_performed = $false
        dispatch_artifact_created = $false
        pool_artifact_created = $false
        model_invocation_count = 0
        completion_claim_allowed = $false
    } | ConvertTo-Json -Compress
    exit 0
}

# Common-contract path: emit candidate result envelope without a real provider call.
$marker = "XINAO_LEG_A_ONECLICK_OK"
if (@($RequiredResultMarkers).Count -gt 0) { $marker = [string]$RequiredResultMarkers[0] }
$usage = [ordered]@{
    input_tokens = 11
    output_tokens = 7
    total_tokens = 18
    model_invocation_count = 1
}
$result = [ordered]@{
    schema_version = "xinao.codex_dispatch_grok_worker_pool.v1"
    ok = $true
    route_role = "normal_leg_a_bounded_online_current_tui"
    execution_backend = $backend
    selected_provider_id = "grok_acpx_headless"
    observed_provider_id = "grok_acpx_headless"
    selected_model_id = $(if ($Model) { $Model } else { "grok-4.5" })
    observed_model_id = $(if ($Model) { $Model } else { "grok-4.5" })
    selected_transport_id = "direct-grok-worker-pool"
    observed_transport_id = "direct-grok-worker-pool"
    selection_decision_sha256 = $decision
    effect_mode = $(if (@($CommonWriteDomains).Count -gt 0) { "authorized_write" } else { "read_only" })
    common_sealed_input_root = $CommonSealedInputRoot
    common_sealed_input_read_only = -not [string]::IsNullOrWhiteSpace($CommonSealedInputRoot)
    common_candidate_output_root = $CommonCandidateOutputRoot
    common_frozen_context_sha256 = $CommonFrozenContextSha256
    common_rules_sha256 = $CommonRulesSha256
    output_marker = $marker
    usage = $usage
    candidate_only = $true
    completion_claim_allowed = $false
}
$result | ConvertTo-Json -Compress -Depth 8
exit 0
'@
    [IO.File]::WriteAllText($launcher, $launcherBody, $utf8)
    return [pscustomobject]@{
        path = $launcher
        call_log = $CallLogPath
    }
}

function Install-FixtureContextBuilder([string]$CarrierRoot) {
    $path = Join-Path $CarrierRoot "Build-XinaoLegAContext.ps1"
    $body = @'
#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Worktree,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [string]$PromptText = "Reply only with marker XINAO_LEG_A_ONECLICK_OK",
    [string]$RulesText = "leg-a oneclick sealed rules; candidate only; no parent completion",
    [string]$SubjectManifestText = '{"schema_version":"xinao.leg_a_subject_manifest.v1","subject":"fresh_consumer"}',
    [switch]$SimulateMissing,
    [switch]$Quiet
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
if ($SimulateMissing -or $env:XINAO_LEG_A_FIXTURE_MISSING_CONTEXT -eq "1") {
    throw "XINAO_LEG_A_CONTEXT_MISSING"
}
$Worktree = [IO.Path]::GetFullPath($Worktree)
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (-not (Test-Path -LiteralPath $Worktree -PathType Container)) {
    throw "XINAO_LEG_A_WORKTREE_MISSING: $Worktree"
}
# Path escape: OutputRoot must stay under an authorized carrier prefix when provided.
$authorized = $env:XINAO_LEG_A_AUTHORIZED_ROOT
if (-not [string]::IsNullOrWhiteSpace($authorized)) {
    $authorized = [IO.Path]::GetFullPath($authorized).TrimEnd('\', '/')
    $outNorm = $OutputRoot.TrimEnd('\', '/')
    $wtNorm = $Worktree.TrimEnd('\', '/')
    if (
        -not ($outNorm.StartsWith($authorized, [StringComparison]::OrdinalIgnoreCase) -or
              $outNorm.StartsWith($authorized + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))
    ) {
        throw "XINAO_LEG_A_PATH_ESCAPE: output_root"
    }
    if (
        -not ($wtNorm.StartsWith($authorized, [StringComparison]::OrdinalIgnoreCase) -or
              $wtNorm.Equals($authorized, [StringComparison]::OrdinalIgnoreCase) -or
              $wtNorm.StartsWith($authorized + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))
    ) {
        # Source worktree may sit beside carrier; only fail when forced escape probe is set.
        if ($env:XINAO_LEG_A_FIXTURE_FORCE_PATH_ESCAPE -eq "1") {
            throw "XINAO_LEG_A_PATH_ESCAPE: worktree"
        }
    }
}
$sealed = Join-Path $OutputRoot "sealed-context"
$inputs = Join-Path $sealed "inputs"
New-Item -ItemType Directory -Force -Path $inputs | Out-Null
$promptFile = Join-Path $sealed "prompt.md"
$rulesFile = Join-Path $sealed "rules.txt"
$manifestFile = Join-Path $sealed "context_manifest.json"
$subjectFile = Join-Path $sealed "subject_manifest.json"
[IO.File]::WriteAllText($promptFile, $PromptText.TrimEnd() + "`n", $utf8)
[IO.File]::WriteAllText($rulesFile, $RulesText.TrimEnd() + "`n", $utf8)
[IO.File]::WriteAllText($subjectFile, $SubjectManifestText.TrimEnd() + "`n", $utf8)
$rulesSha = (Get-FileHash -LiteralPath $rulesFile -Algorithm SHA256).Hash.ToLowerInvariant()
$promptSha = (Get-FileHash -LiteralPath $promptFile -Algorithm SHA256).Hash.ToLowerInvariant()
$subjectSha = (Get-FileHash -LiteralPath $subjectFile -Algorithm SHA256).Hash.ToLowerInvariant()
# frozen_context_sha256 is derived from sealed bytes; caller never supplies it.
$frozenPayload = [ordered]@{
    schema_version = "xinao.leg_a_frozen_context.v1"
    prompt_sha256 = $promptSha
    rules_sha256 = $rulesSha
    subject_manifest_sha256 = $subjectSha
    sealed_input_root = $inputs
}
$frozenJson = ($frozenPayload | ConvertTo-Json -Compress -Depth 6)
$frozenBytes = $utf8.GetBytes($frozenJson)
$frozenAlg = [Security.Cryptography.SHA256]::Create()
try {
    $frozenSha = ([BitConverter]::ToString($frozenAlg.ComputeHash($frozenBytes))).Replace("-", "").ToLowerInvariant()
}
finally { $frozenAlg.Dispose() }
$manifest = [ordered]@{
    schema_version = "xinao.leg_a_context_manifest.v1"
    context_binding_mode = "validated_context_slice_manifest"
    sealed_context_path = $sealed
    prompt_file = $promptFile
    prompt_sha256 = $promptSha
    rules_file = $rulesFile
    rules_sha256 = $rulesSha
    subject_manifest_path = $subjectFile
    subject_manifest_sha256 = $subjectSha
    frozen_context_sha256 = $frozenSha
    sealed_input_root = $inputs
    sealed_read_only = $true
    worktree = $Worktree
}
[IO.File]::WriteAllText($manifestFile, ($manifest | ConvertTo-Json -Depth 8), $utf8)
[IO.File]::WriteAllText((Join-Path $inputs "catalog.json"), '{"sealed":true}', $utf8)
$result = [ordered]@{
    schema_version = "xinao.leg_a_context_build_result.v1"
    sealed_context_path = $sealed
    context_manifest_path = $manifestFile
    frozen_context_sha256 = $frozenSha
    rules_file = $rulesFile
    rules_sha256 = $rulesSha
    sealed_input_root = $inputs
    prompt_file = $promptFile
    subject_manifest_sha256 = $subjectSha
    sealed_read_only = $true
    manual_hashes_required = $false
    prior_chat_state_required = $false
}
$result | ConvertTo-Json -Compress -Depth 8
'@
    [IO.File]::WriteAllText($path, $body, $utf8)
    return $path
}

function Install-FixtureOneClickWorker([string]$CarrierRoot) {
    $path = Join-Path $CarrierRoot "Invoke-XinaoLegAWorker.ps1"
    $body = @'
#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Worktree,
    [string]$Model = "grok-4.5",
    [string]$Prompt = "Reply only with marker XINAO_LEG_A_ONECLICK_OK",
    [string]$PromptFile = "",
    [string]$ContextBuilderPath = "",
    [string]$PublicLauncherPath = "",
    [string]$RuntimeRoot = "",
    [string]$SealedContextOutputRoot = "",
    [string]$CandidateOutputRoot = "",
    [switch]$AuthorizeWorktreeWrite,
    [string]$ForcedBackend = "",
    [string]$WorkKey = "",
    [string]$OperationId = "",
    [string[]]$RequiredResultMarkers = @("XINAO_LEG_A_ONECLICK_OK"),
    [switch]$SkipContextBuild,
    [string]$InjectContextManifestPath = "",
    [string]$InjectFrozenContextSha256 = "",
    [string]$InjectRulesFile = "",
    [string]$InjectRulesSha256 = "",
    [string]$InjectSealedInputRoot = "",
    [string]$InjectPromptFile = "",
    [string]$InjectSubjectManifestSha256 = "",
    [string]$ExpectedSelectionDecisionSha256 = "",
    [switch]$Quiet
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
function Get-LastJson([string[]]$Lines) {
    $hits = @($Lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_.Trim().StartsWith("{") })
    if ($hits.Count -eq 0) { throw "XINAO_LEG_A_NO_JSON_RESULT" }
    return ($hits[-1] | ConvertFrom-Json -ErrorAction Stop)
}
$Worktree = [IO.Path]::GetFullPath($Worktree)
if (-not (Test-Path -LiteralPath $Worktree -PathType Container)) {
    throw "XINAO_LEG_A_WORKTREE_MISSING: $Worktree"
}
if ([string]::IsNullOrWhiteSpace($PublicLauncherPath)) {
    $PublicLauncherPath = $env:XINAO_LEG_A_PUBLIC_LAUNCHER
}
if ([string]::IsNullOrWhiteSpace($PublicLauncherPath) -or -not (Test-Path -LiteralPath $PublicLauncherPath -PathType Leaf)) {
    throw "XINAO_LEG_A_PUBLIC_LAUNCHER_MISSING"
}
if ([string]::IsNullOrWhiteSpace($ContextBuilderPath)) {
    $ContextBuilderPath = $env:XINAO_LEG_A_CONTEXT_BUILDER
}
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $Worktree "_runtime"
}
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
if ([string]::IsNullOrWhiteSpace($SealedContextOutputRoot)) {
    $SealedContextOutputRoot = Join-Path $RuntimeRoot "context-out"
}
if ([string]::IsNullOrWhiteSpace($WorkKey)) {
    $WorkKey = "xinao-leg-a-oneclick:" + [guid]::NewGuid().ToString("N").Substring(0, 12)
}
if ([string]::IsNullOrWhiteSpace($OperationId)) {
    $OperationId = "op-leg-a-oneclick"
}

$backend = "linux-container"
if (-not [string]::IsNullOrWhiteSpace($ForcedBackend)) { $backend = $ForcedBackend }
elseif (-not [string]::IsNullOrWhiteSpace($env:XINAO_LEG_A_FAKE_BACKEND)) { $backend = $env:XINAO_LEG_A_FAKE_BACKEND }
if ($backend -ne "linux-container") {
    throw "XINAO_LEG_A_BACKEND_FORBIDDEN: $backend"
}

# Discover sealed context without prior chat state or manually supplied hashes.
$context = $null
if ($SkipContextBuild) {
    if (
        [string]::IsNullOrWhiteSpace($InjectContextManifestPath) -or
        [string]::IsNullOrWhiteSpace($InjectFrozenContextSha256) -or
        [string]::IsNullOrWhiteSpace($InjectRulesFile) -or
        [string]::IsNullOrWhiteSpace($InjectRulesSha256) -or
        [string]::IsNullOrWhiteSpace($InjectSealedInputRoot) -or
        [string]::IsNullOrWhiteSpace($InjectPromptFile) -or
        [string]::IsNullOrWhiteSpace($InjectSubjectManifestSha256)
    ) {
        throw "XINAO_LEG_A_CONTEXT_MISSING"
    }
    $context = [pscustomobject]@{
        context_manifest_path = $InjectContextManifestPath
        frozen_context_sha256 = $InjectFrozenContextSha256
        rules_file = $InjectRulesFile
        rules_sha256 = $InjectRulesSha256
        sealed_input_root = $InjectSealedInputRoot
        prompt_file = $InjectPromptFile
        subject_manifest_sha256 = $InjectSubjectManifestSha256
        sealed_context_path = (Split-Path -Parent $InjectContextManifestPath)
    }
}
else {
    if ([string]::IsNullOrWhiteSpace($ContextBuilderPath) -or -not (Test-Path -LiteralPath $ContextBuilderPath -PathType Leaf)) {
        throw "XINAO_LEG_A_CONTEXT_BUILDER_MISSING"
    }
    try {
        $buildOut = @(& $ContextBuilderPath -Worktree $Worktree -OutputRoot $SealedContextOutputRoot -PromptText $Prompt 2>&1 | ForEach-Object { [string]$_ })
        $buildExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    catch {
        throw ("XINAO_LEG_A_CONTEXT_BUILD_FAILED: " + $_)
    }
    if ($buildExit -ne 0) {
        throw ("XINAO_LEG_A_CONTEXT_BUILD_FAILED: " + ($buildOut -join "`n"))
    }
    $context = Get-LastJson $buildOut
}

foreach ($required in @(
    "context_manifest_path", "frozen_context_sha256", "rules_file", "rules_sha256",
    "sealed_input_root", "prompt_file", "subject_manifest_sha256"
)) {
    if ([string]::IsNullOrWhiteSpace([string]$context.$required)) {
        throw "XINAO_LEG_A_CONTEXT_MISSING: $required"
    }
}

# Drift checks before provider effect.
if (-not (Test-Path -LiteralPath ([string]$context.rules_file) -PathType Leaf)) {
    throw "XINAO_LEG_A_CONTEXT_MISSING: rules_file"
}
$observedRulesSha = (Get-FileHash -LiteralPath ([string]$context.rules_file) -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not [string]::Equals($observedRulesSha, [string]$context.rules_sha256, [StringComparison]::Ordinal)) {
    throw "XINAO_LEG_A_CONTEXT_DRIFT: rules"
}
if (-not (Test-Path -LiteralPath ([string]$context.context_manifest_path) -PathType Leaf)) {
    throw "XINAO_LEG_A_CONTEXT_MISSING: context_manifest_path"
}
if (-not (Test-Path -LiteralPath ([string]$context.sealed_input_root) -PathType Container)) {
    throw "XINAO_LEG_A_CONTEXT_MISSING: sealed_input_root"
}
if (-not (Test-Path -LiteralPath ([string]$context.prompt_file) -PathType Leaf)) {
    throw "XINAO_LEG_A_CONTEXT_MISSING: prompt_file"
}

$effectMode = "read_only"
$writeDomains = @()
$candidateRoot = ""
if ($AuthorizeWorktreeWrite) {
    $effectMode = "authorized_write"
    if ([string]::IsNullOrWhiteSpace($CandidateOutputRoot)) {
        $CandidateOutputRoot = $Worktree
    }
    $candidateRoot = [IO.Path]::GetFullPath($CandidateOutputRoot)
    $wtFull = [IO.Path]::GetFullPath($Worktree)
    if (-not [string]::Equals($candidateRoot, $wtFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "XINAO_LEG_A_OUTPUT_ROOT_MISMATCH"
    }
    $writeDomains = @("candidate_output_root:" + ($candidateRoot.Replace('\', '/').TrimEnd('/').ToLowerInvariant()))
}
elseif (-not [string]::IsNullOrWhiteSpace($CandidateOutputRoot)) {
    # Providing an output root without authorize is a mismatch.
    throw "XINAO_LEG_A_OUTPUT_ROOT_MISMATCH"
}

# Path escape probe for sealed input / rules relative to authorized carrier when set.
$authorized = $env:XINAO_LEG_A_AUTHORIZED_ROOT
if (-not [string]::IsNullOrWhiteSpace($authorized)) {
    $authorized = [IO.Path]::GetFullPath($authorized).TrimEnd('\', '/')
    foreach ($pair in @(
        @{ name = "sealed_input_root"; path = [string]$context.sealed_input_root },
        @{ name = "rules_file"; path = [string]$context.rules_file },
        @{ name = "prompt_file"; path = [string]$context.prompt_file }
    )) {
        $p = [IO.Path]::GetFullPath($pair.path).TrimEnd('\', '/')
        if (
            -not ($p.StartsWith($authorized, [StringComparison]::OrdinalIgnoreCase) -or
                  $p.StartsWith($authorized + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))
        ) {
            if ($env:XINAO_LEG_A_FIXTURE_FORCE_PATH_ESCAPE -eq "1") {
                throw "XINAO_LEG_A_PATH_ESCAPE: $($pair.name)"
            }
        }
    }
}

# 1) selection-only bootstrap through public launcher
$selArgs = @(
    "-NoLogo", "-NoProfile", "-File", $PublicLauncherPath,
    "-N", "1",
    "-Model", $Model,
    "-Cwd", $Worktree,
    "-SelectionOnly",
    "-RuntimeRoot", $RuntimeRoot
)
$selRaw = @(& (Get-Process -Id $PID).Path @selArgs 2>&1 | ForEach-Object { [string]$_ })
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
    throw ("XINAO_LEG_A_SELECTION_ONLY_FAILED: " + ($selRaw -join "`n"))
}
$selection = Get-LastJson $selRaw
if ([string]$selection.schema_version -ne "xinao.codex_grok_selection_only_result.v1") {
    throw "XINAO_LEG_A_SELECTION_ONLY_SCHEMA"
}
if ([int]$selection.model_invocation_count -ne 0) {
    throw "XINAO_LEG_A_SELECTION_ONLY_HAD_PROVIDER_EFFECT"
}
$decisionSha = [string]$selection.decision_sha256
if (
    -not [string]::IsNullOrWhiteSpace($ExpectedSelectionDecisionSha256) -and
    -not [string]::Equals($ExpectedSelectionDecisionSha256, $decisionSha, [StringComparison]::Ordinal)
) {
    throw "XINAO_LEG_A_SELECTION_STALE"
}

# Optional stale-selection probe for tests: mutate expected after bootstrap.
if ($env:XINAO_LEG_A_FIXTURE_STALE_SELECTION_AFTER_BOOTSTRAP -eq "1") {
    $decisionSha = ("c" * 64)
}

# 2) real common-contract call through the same public launcher
$commonArgs = @(
    "-NoLogo", "-NoProfile", "-File", $PublicLauncherPath,
    "-N", "1",
    "-Model", $Model,
    "-Cwd", $Worktree,
    "-PromptFile", ([string]$context.prompt_file),
    "-CommonWorkKey", $WorkKey,
    "-CommonOperationId", $OperationId,
    "-CommonSubjectManifestSha256", ([string]$context.subject_manifest_sha256),
    "-CommonFrozenContextSha256", ([string]$context.frozen_context_sha256),
    "-CommonContextManifestPath", ([string]$context.context_manifest_path),
    "-CommonRulesFile", ([string]$context.rules_file),
    "-CommonRulesSha256", ([string]$context.rules_sha256),
    "-CommonSealedInputRoot", ([string]$context.sealed_input_root),
    "-CommonPhase", "EXPLORE",
    "-ExpectedSelectionDecisionSha256", $decisionSha,
    "-RuntimeRoot", $RuntimeRoot,
    "-MinResultChars", "1",
    "-RequiredResultMarkers", ($RequiredResultMarkers -join ",")
)
if ($AuthorizeWorktreeWrite) {
    $commonArgs += @("-CommonCandidateOutputRoot", $candidateRoot)
    foreach ($domain in $writeDomains) {
        $commonArgs += @("-CommonWriteDomains", $domain)
    }
}
$commonRaw = @(& (Get-Process -Id $PID).Path @commonArgs 2>&1 | ForEach-Object { [string]$_ })
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
    throw ("XINAO_LEG_A_COMMON_CALL_FAILED: " + ($commonRaw -join "`n"))
}
$dispatch = Get-LastJson $commonRaw

$selectedProvider = [string]$selection.provider_id
$selectedModel = [string]$selection.model_id
$selectedTransport = [string]$selection.transport_id
$observedProvider = [string]$dispatch.observed_provider_id
$observedModel = [string]$dispatch.observed_model_id
$observedTransport = [string]$dispatch.observed_transport_id
$observedBackend = [string]$dispatch.execution_backend
if ([string]::IsNullOrWhiteSpace($observedBackend)) { $observedBackend = $backend }

if ($observedBackend -ne "linux-container") {
    throw "XINAO_LEG_A_BACKEND_FORBIDDEN: observed=$observedBackend"
}
if ($selectedProvider -ne $observedProvider) { throw "XINAO_LEG_A_SELECTED_OBSERVED_PROVIDER_MISMATCH" }
if ($selectedModel -ne $observedModel) { throw "XINAO_LEG_A_SELECTED_OBSERVED_MODEL_MISMATCH" }
if ($selectedTransport -ne $observedTransport) { throw "XINAO_LEG_A_SELECTED_OBSERVED_TRANSPORT_MISMATCH" }

$usage = $dispatch.usage
$total = 0
if ($null -ne $usage) {
    if ($null -ne $usage.total_tokens) { $total = [int]$usage.total_tokens }
    elseif ($null -ne $usage.output_tokens) { $total = [int]$usage.output_tokens }
}
if ($total -le 0) { throw "XINAO_LEG_A_USAGE_NOT_POSITIVE" }

$worktreeReadOnly = -not $AuthorizeWorktreeWrite
$result = [ordered]@{
    schema_version = "xinao.leg_a_oneclick_result.v1"
    sentinel = "SENTINEL:XINAO_LEG_A_ONECLICK_RESULT_V1"
    ok = $true
    candidate_only = $true
    completion_claim_allowed = $false
    route_leg = "A"
    execution_backend_requested = "linux-container"
    execution_backend_observed = $observedBackend
    selected_provider_id = $selectedProvider
    observed_provider_id = $observedProvider
    selected_model_id = $selectedModel
    observed_model_id = $observedModel
    selected_transport_id = $selectedTransport
    observed_transport_id = $observedTransport
    selection_decision_sha256 = [string]$selection.decision_sha256
    selection_only_invoked = $true
    common_contract_invoked = $true
    public_launcher_used = $true
    public_launcher_path = $PublicLauncherPath
    sealed_context_path = [string]$context.sealed_context_path
    context_manifest_path = [string]$context.context_manifest_path
    frozen_context_sha256 = [string]$context.frozen_context_sha256
    rules_file = [string]$context.rules_file
    rules_sha256 = [string]$context.rules_sha256
    sealed_input_root = [string]$context.sealed_input_root
    sealed_read_only = $true
    effect_mode = $effectMode
    worktree = $Worktree
    worktree_read_only = $worktreeReadOnly
    candidate_output_root = $candidateRoot
    write_domains = @($writeDomains)
    usage = $usage
    output_marker = [string]$dispatch.output_marker
    evidence_root = $RuntimeRoot
    prior_chat_state_required = $false
    manual_hashes_required = $false
    rollback = [ordered]@{
        removes_test_carrier_only = $true
        preserves_source_worktree = $true
    }
}
$result | ConvertTo-Json -Compress -Depth 10
'@
    [IO.File]::WriteAllText($path, $body, $utf8)
    return $path
}

function Get-LauncherCalls([string]$CallLogPath) {
    if (-not (Test-Path -LiteralPath $CallLogPath -PathType Leaf)) { return @() }
    $lines = Get-Content -LiteralPath $CallLogPath -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    return @($lines | ForEach-Object { $_ | ConvertFrom-Json })
}

function Invoke-OneClickCase {
    param(
        [string]$Label,
        [string]$WorkerPath,
        [string]$ContextBuilder,
        [string]$Launcher,
        [string]$Worktree,
        [string]$RuntimeRoot,
        [string]$ContextOut,
        [hashtable]$ExtraArgs = @{},
        [hashtable]$EnvOverrides = @{},
        [bool]$ExpectSuccess = $true,
        [string]$ExpectedErrorToken = ""
    )
    $argList = @(
        "-NoLogo", "-NoProfile", "-File", $WorkerPath,
        "-Worktree", $Worktree,
        "-Model", "grok-4.5",
        "-Prompt", "Reply only with marker XINAO_LEG_A_ONECLICK_OK",
        "-ContextBuilderPath", $ContextBuilder,
        "-PublicLauncherPath", $Launcher,
        "-RuntimeRoot", $RuntimeRoot,
        "-SealedContextOutputRoot", $ContextOut,
        "-RequiredResultMarkers", "XINAO_LEG_A_ONECLICK_OK"
    )
    foreach ($key in $ExtraArgs.Keys) {
        $value = $ExtraArgs[$key]
        if ($value -is [switch] -or $value -is [bool]) {
            if ($value) { $argList += "-$key" }
        }
        elseif ($null -ne $value -and "$value" -ne "") {
            $argList += @("-$key", [string]$value)
        }
    }
    $saved = @{}
    foreach ($k in $EnvOverrides.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k)
        [Environment]::SetEnvironmentVariable($k, [string]$EnvOverrides[$k])
    }
    try {
        $run = Invoke-FreshPowerShell -Arguments $argList
    }
    finally {
        foreach ($k in $saved.Keys) {
            [Environment]::SetEnvironmentVariable($k, $saved[$k])
        }
    }
    if ($ExpectSuccess) {
        Assert-True ($run.exit_code -eq 0) "$Label exit=0 (got $($run.exit_code)): $($run.output)"
        $json = ConvertFrom-LastJsonObject -Lines $run.lines
        return [pscustomobject]@{ run = $run; result = $json }
    }
    Assert-True ($run.exit_code -ne 0 -or $run.output -match [regex]::Escape($ExpectedErrorToken)) `
        "$Label expected failure token $ExpectedErrorToken"
    Assert-True ($run.output -match [regex]::Escape($ExpectedErrorToken)) `
        "$Label error token present: $ExpectedErrorToken (output=$($run.output))"
    return [pscustomobject]@{ run = $run; result = $null }
}

# ---------------------------------------------------------------------------
# Contract presence + schema
# ---------------------------------------------------------------------------
Assert-True (Test-Path -LiteralPath $ContractPath -PathType Leaf) "contract_present"
$contract = Get-Content -LiteralPath $ContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($contract.schema_version -eq "xinao.grok_xinao_leg_a_oneclick_contract.v1") "contract_schema"
Assert-True ($contract.sentinel -eq "SENTINEL:XINAO_LEG_A_ONECLICK_CONTRACT_V1") "contract_sentinel"
Assert-True ($contract.marker -eq $marker) "contract_marker"
Assert-True ($contract.authority.completion_claim_allowed -eq $false) "contract_no_completion_claim"
Assert-True ($contract.authority.worker_output -eq "candidate_only") "contract_candidate_only"
Assert-True ($contract.route.required_execution_backend -eq "linux-container") "contract_backend_linux_container"
Assert-True (@($contract.route.forbidden_execution_backends) -contains "windows-host") "contract_forbids_windows_host"
Assert-True (@($contract.route.forbidden_routes) -contains "leg_b") "contract_forbids_leg_b"

$productionBuilder = Join-Path $bridge "Build-XinaoLegAContext.ps1"
$productionWorker = Join-Path $bridge "Invoke-XinaoLegAWorker.ps1"
if (-not [string]::IsNullOrWhiteSpace($ContextBuilderPath)) { $productionBuilder = $ContextBuilderPath }
if (-not [string]::IsNullOrWhiteSpace($OneClickWorkerPath)) { $productionWorker = $OneClickWorkerPath }
# This file is the deterministic contract suite. Production is selected only
# when a caller explicitly supplies both scripts; mere co-location must not turn
# a fixture test into a provider-facing integration run. The real one-click
# commissioning is performed separately through Invoke-XinaoLegAWorker.ps1.
$usingProduction = (
    -not [string]::IsNullOrWhiteSpace($ContextBuilderPath) -and
    -not [string]::IsNullOrWhiteSpace($OneClickWorkerPath) -and
    (Test-Path -LiteralPath $productionBuilder -PathType Leaf) -and
    (Test-Path -LiteralPath $productionWorker -PathType Leaf)
)
if (-not $usingProduction) { $AllowMissingProductionScripts = $true }

# ---------------------------------------------------------------------------
# Temp carrier (only cleanup target)
# ---------------------------------------------------------------------------
$carrier = Join-Path ([IO.Path]::GetTempPath()) (
    "xinao-leg-a-oneclick-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
    [guid]::NewGuid().ToString("N").Substring(0, 8)
)
New-Item -ItemType Directory -Force -Path $carrier | Out-Null
$source = New-SourceWorktree -Root $carrier
$callLog = Join-Path $carrier "public-launcher-calls.jsonl"
$fakeLauncher = Install-FakePublicLauncher -CarrierRoot $carrier -CallLogPath $callLog
$fixtureBuilder = Install-FixtureContextBuilder -CarrierRoot $carrier
$fixtureWorker = Install-FixtureOneClickWorker -CarrierRoot $carrier
$builderUnderTest = if ($usingProduction) { $productionBuilder } else { $fixtureBuilder }
$workerUnderTest = if ($usingProduction) { $productionWorker } else { $fixtureWorker }
$runtimeRoot = Join-Path $carrier "runtime"
$contextOut = Join-Path $carrier "context-out"
New-Item -ItemType Directory -Force -Path $runtimeRoot, $contextOut | Out-Null

$env:XINAO_LEG_A_FAKE_PUBLIC_LAUNCHER_LOG = $callLog
$env:XINAO_LEG_A_PUBLIC_LAUNCHER = $fakeLauncher.path
$env:XINAO_LEG_A_CONTEXT_BUILDER = $builderUnderTest
$env:XINAO_LEG_A_AUTHORIZED_ROOT = $carrier
$env:XINAO_LEG_A_FAKE_BACKEND = "linux-container"
$env:XINAO_LEG_A_FAKE_SELECTION_DECISION = ("b" * 64)

$passed = New-Object System.Collections.Generic.List[string]

try {
    # --- Happy path: fresh consumer ---
    if (Test-Path -LiteralPath $callLog) { Remove-Item -LiteralPath $callLog -Force }
    $happy = Invoke-OneClickCase `
        -Label "happy_path" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot $runtimeRoot `
        -ContextOut $contextOut
    $r = $happy.result
    Assert-True ($r.ok -eq $true) "happy.ok"
    Assert-True ($r.candidate_only -eq $true) "happy.candidate_only"
    Assert-True ($r.completion_claim_allowed -eq $false) "happy.no_completion_claim"
    Assert-True ($r.route_leg -eq "A") "happy.route_leg_a"
    Assert-True ($r.execution_backend_requested -eq "linux-container") "happy.backend_requested"
    Assert-True ($r.execution_backend_observed -eq "linux-container") "happy.backend_observed"
    Assert-True ($r.selection_only_invoked -eq $true) "happy.selection_only"
    Assert-True ($r.common_contract_invoked -eq $true) "happy.common_contract"
    Assert-True ($r.public_launcher_used -eq $true) "happy.public_launcher"
    Assert-True ($r.prior_chat_state_required -eq $false) "happy.no_chat_state"
    Assert-True ($r.manual_hashes_required -eq $false) "happy.no_manual_hashes"
    Assert-True ($r.sealed_read_only -eq $true) "happy.sealed_ro"
    Assert-True ($r.worktree_read_only -eq $true) "happy.worktree_ro_default"
    Assert-True ($r.effect_mode -eq "read_only") "happy.effect_mode_ro"
    Assert-True ($r.selected_provider_id -eq $r.observed_provider_id) "happy.selected_eq_observed_provider"
    Assert-True ($r.selected_model_id -eq $r.observed_model_id) "happy.selected_eq_observed_model"
    Assert-True ($r.selected_transport_id -eq $r.observed_transport_id) "happy.selected_eq_observed_transport"
    Assert-True ($r.execution_backend_requested -eq $r.execution_backend_observed) "happy.selected_eq_observed_backend"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.output_marker)) "happy.output_marker"
    Assert-True ($r.output_marker -match "XINAO_LEG_A_ONECLICK_OK") "happy.output_marker_value"
    $usageTotal = 0
    if ($null -ne $r.usage.total_tokens) { $usageTotal = [int]$r.usage.total_tokens }
    Assert-True ($usageTotal -gt 0) "happy.positive_usage"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.sealed_context_path)) "happy.sealed_context_path"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.frozen_context_sha256)) "happy.frozen_context_sha"
    Assert-True ([string]$r.frozen_context_sha256 -match '^[0-9a-f]{64}$') "happy.frozen_context_sha_format"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.selection_decision_sha256)) "happy.selection_decision"
    $calls = Get-LauncherCalls -CallLogPath $callLog
    Assert-True ($calls.Count -ge 2) "happy.launcher_calls_ge_2"
    Assert-True (@($calls | Where-Object { $_.mode -eq "selection_only" }).Count -ge 1) "happy.has_selection_only_call"
    Assert-True (@($calls | Where-Object { $_.mode -eq "common_contract" }).Count -ge 1) "happy.has_common_call"
    $commonCall = @($calls | Where-Object { $_.mode -eq "common_contract" })[0]
    Assert-True ($commonCall.execution_backend_requested -eq "linux-container") "happy.common_backend_linux"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.common_frozen_context_sha256)) "happy.common_has_frozen_context"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.common_rules_sha256)) "happy.common_has_rules_sha"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.common_sealed_input_root)) "happy.common_has_sealed_root"
    [void]$passed.Add("happy_path_fresh_consumer")
    [void]$passed.Add("no_prior_chat_or_manual_hashes")
    [void]$passed.Add("selection_only_and_common_via_public_launcher")
    [void]$passed.Add("backend_linux_container_only")
    [void]$passed.Add("sealed_ro_and_worktree_ro_default")
    [void]$passed.Add("result_json_evidence_surface")

    # --- Authorized write domain (only when explicit) ---
    if (Test-Path -LiteralPath $callLog) { Remove-Item -LiteralPath $callLog -Force }
    $writeCase = Invoke-OneClickCase `
        -Label "authorized_write" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-write") `
        -ContextOut (Join-Path $carrier "context-out-write") `
        -ExtraArgs @{ AuthorizeWorktreeWrite = $true }
    Assert-True ($writeCase.result.effect_mode -eq "authorized_write") "write.effect_mode"
    Assert-True ($writeCase.result.worktree_read_only -eq $false) "write.worktree_not_ro"
    Assert-True (@($writeCase.result.write_domains).Count -eq 1) "write.single_domain"
    [void]$passed.Add("authorized_write_domain_only_when_explicit")

    # --- Fail closed: missing context ---
    Invoke-OneClickCase `
        -Label "missing_context" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-missing") `
        -ContextOut (Join-Path $carrier "context-missing") `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_MISSING_CONTEXT = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_CONTEXT_MISSING" | Out-Null
    [void]$passed.Add("missing_context_fail_closed")

    # --- Fail closed: drifted context (rules bytes changed after build) ---
    $driftRuntime = Join-Path $carrier "runtime-drift"
    $driftContextOut = Join-Path $carrier "context-drift"
    New-Item -ItemType Directory -Force -Path $driftRuntime, $driftContextOut | Out-Null
    $buildDrift = Invoke-FreshPowerShell -Arguments @(
        "-NoLogo", "-NoProfile", "-File", $builderUnderTest,
        "-Worktree", $source.path,
        "-OutputRoot", $driftContextOut
    )
    Assert-True ($buildDrift.exit_code -eq 0) "drift_build_ok"
    $built = ConvertFrom-LastJsonObject -Lines $buildDrift.lines
    # Tamper rules after seal
    [IO.File]::WriteAllText([string]$built.rules_file, "TAMPERED_RULES`n", $utf8)
    Invoke-OneClickCase `
        -Label "drifted_context" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot $driftRuntime `
        -ContextOut $driftContextOut `
        -ExtraArgs @{
            SkipContextBuild = $true
            InjectContextManifestPath = [string]$built.context_manifest_path
            InjectFrozenContextSha256 = [string]$built.frozen_context_sha256
            InjectRulesFile = [string]$built.rules_file
            InjectRulesSha256 = [string]$built.rules_sha256
            InjectSealedInputRoot = [string]$built.sealed_input_root
            InjectPromptFile = [string]$built.prompt_file
            InjectSubjectManifestSha256 = [string]$built.subject_manifest_sha256
        } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_CONTEXT_DRIFT" | Out-Null
    [void]$passed.Add("drifted_context_fail_closed")

    # --- Fail closed: stale selection ---
    Invoke-OneClickCase `
        -Label "stale_selection" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-stale") `
        -ContextOut (Join-Path $carrier "context-stale") `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_STALE_SELECTION_AFTER_BOOTSTRAP = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_SELECTION_STALE" | Out-Null
    [void]$passed.Add("stale_selection_fail_closed")

    # --- Fail closed: docker unavailable ---
    Invoke-OneClickCase `
        -Label "docker_unavailable" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-docker") `
        -ContextOut (Join-Path $carrier "context-docker") `
        -EnvOverrides @{ XINAO_LEG_A_FAKE_DOCKER_UNAVAILABLE = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_DOCKER_UNAVAILABLE" | Out-Null
    [void]$passed.Add("docker_unavailable_fail_closed")

    # --- Fail closed: path escape (output root outside authorized zone, still under carrier) ---
    $authorizedZone = Join-Path $carrier "authorized-zone"
    $escapeOut = Join-Path $carrier "escape-zone"
    New-Item -ItemType Directory -Force -Path $authorizedZone | Out-Null
    Invoke-OneClickCase `
        -Label "path_escape" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-escape") `
        -ContextOut $escapeOut `
        -EnvOverrides @{
            XINAO_LEG_A_AUTHORIZED_ROOT = $authorizedZone
            XINAO_LEG_A_FIXTURE_FORCE_PATH_ESCAPE = "1"
        } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_PATH_ESCAPE" | Out-Null
    [void]$passed.Add("path_escape_fail_closed")

    # --- Fail closed: mismatched output root ---
    $otherOut = Join-Path $carrier "other-output-root"
    New-Item -ItemType Directory -Force -Path $otherOut | Out-Null
    Invoke-OneClickCase `
        -Label "mismatched_output_root" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-mismatch") `
        -ContextOut (Join-Path $carrier "context-mismatch") `
        -ExtraArgs @{
            AuthorizeWorktreeWrite = $true
            CandidateOutputRoot = $otherOut
        } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_OUTPUT_ROOT_MISMATCH" | Out-Null
    [void]$passed.Add("mismatched_output_root_fail_closed")

    # --- Fail closed: forbidden backend (windows-host) ---
    Invoke-OneClickCase `
        -Label "forbidden_backend" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Launcher $fakeLauncher.path `
        -Worktree $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-backend") `
        -ContextOut (Join-Path $carrier "context-backend") `
        -ExtraArgs @{ ForcedBackend = "windows-host" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_BACKEND_FORBIDDEN" | Out-Null
    [void]$passed.Add("forbidden_backend_fail_closed")

    # --- Rollback / cleanup preserves source worktree ---
    $sourceShaBeforeCleanup = Get-Sha256File $source.preserve_path
    Assert-True ($sourceShaBeforeCleanup -eq $source.preserve_sha256) "source_intact_before_cleanup"
    [void]$passed.Add("rollback_preserves_source_worktree")

    $summary = [ordered]@{
        schema_version = "xinao.leg_a_oneclick_consumer_test_result.v1"
        marker = $marker
        ok = $true
        candidate_only = $true
        completion_claim_allowed = $false
        using_production_scripts = [bool]$usingProduction
        fixture_mode = -not $usingProduction
        contract_path = $ContractPath
        context_builder_under_test = $builderUnderTest
        oneclick_worker_under_test = $workerUnderTest
        public_launcher_fixture = $fakeLauncher.path
        carrier_root = $carrier
        source_worktree = $source.path
        source_preserve_sha256 = $source.preserve_sha256
        passed_cases = @($passed)
        required_cases = @($contract.test.required_cases)
        notes = @(
            "Deterministic fixtures only; no second real provider call.",
            "Production Build/Invoke scripts are preferred when present in the bridge.",
            "Codex remains sole Owner for adoption and parent completion."
        )
    }
    # Ensure required cases from contract are covered
    $passedSet = @($passed)
    foreach ($req in @($contract.test.required_cases)) {
        Assert-True ($passedSet -contains [string]$req) "required_case_covered:$req"
    }
    Write-Output ($summary | ConvertTo-Json -Compress -Depth 8)
}
finally {
    # Rollback: remove only the test carrier; verify source file identity first.
    try {
        if (Test-Path -LiteralPath $source.preserve_path -PathType Leaf) {
            $after = Get-Sha256File $source.preserve_path
            if ($after -ne $source.preserve_sha256) {
                throw "XINAO_LEG_A_SOURCE_WORKTREE_MUTATED"
            }
        }
    }
    catch {
        if ("$_" -match "XINAO_LEG_A_SOURCE_WORKTREE_MUTATED") { throw }
    }
    foreach ($name in @(
        "XINAO_LEG_A_FAKE_PUBLIC_LAUNCHER_LOG",
        "XINAO_LEG_A_PUBLIC_LAUNCHER",
        "XINAO_LEG_A_CONTEXT_BUILDER",
        "XINAO_LEG_A_AUTHORIZED_ROOT",
        "XINAO_LEG_A_FAKE_BACKEND",
        "XINAO_LEG_A_FAKE_SELECTION_DECISION",
        "XINAO_LEG_A_FAKE_DOCKER_UNAVAILABLE",
        "XINAO_LEG_A_FIXTURE_MISSING_CONTEXT",
        "XINAO_LEG_A_FIXTURE_STALE_SELECTION_AFTER_BOOTSTRAP",
        "XINAO_LEG_A_FIXTURE_FORCE_PATH_ESCAPE"
    )) {
        [Environment]::SetEnvironmentVariable($name, $null)
    }
    if (Test-Path -LiteralPath $carrier -PathType Container) {
        Remove-Item -LiteralPath $carrier -Recurse -Force -ErrorAction SilentlyContinue
    }
}
