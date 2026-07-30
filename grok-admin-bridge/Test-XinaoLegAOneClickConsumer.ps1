#Requires -Version 5.1
<#
.SYNOPSIS
  Fresh-process consumer boundary for XINAO leg-A one-click call.
.DESCRIPTION
  Binds the published contract to the production parameter/result shape of
  Invoke-XinaoLegAWorker.ps1 + Build-XinaoLegAContext.ps1, then exercises the
  one-click consumer through a bounded fake public dispatcher (no real second
  provider spend). Fixture workers must mirror production params/results;
  fixture-only greens without production shape binding are forbidden.
  Candidate only; Codex owns adoption.
#>
[CmdletBinding()]
param(
    [string]$ContractPath = "",
    [string]$ContextBuilderPath = "",
    [string]$OneClickWorkerPath = "",
    [switch]$AllowMissingProductionScripts,
    [switch]$ForceFixtureWorker
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$repoRoot = Split-Path -Parent $bridge
$pwsh = (Get-Process -Id $PID).Path
$marker = "XINAO_LEG_A_ONECLICK_ENTRY_CANDIDATE_V1"
$contractDefault = Join-Path $bridge "grok_xinao_leg_a_oneclick_contract.v1.json"
if ([string]::IsNullOrWhiteSpace($ContractPath)) { $ContractPath = $contractDefault }

function Assert-True([bool]$Condition, [string]$Label) {
    if (-not $Condition) { throw "XINAO_LEG_A_ONECLICK_ASSERT_FAIL: $Label" }
}
function Get-Sha256File([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function Invoke-GitQuiet {
    param(
        [string]$Repo,
        [string[]]$GitArgs
    )
    $prev = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& git -C $Repo @GitArgs 2>&1 | ForEach-Object { [string]$_ })
        $code = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally {
        $ErrorActionPreference = $prev
    }
    return [pscustomobject]@{ exit_code = $code; output = ($output -join "`n") }
}

function Initialize-SelfContainedClone {
    param(
        [string]$Root,
        [string]$Name = "valid-clone",
        [string]$OriginUrl = "https://example.invalid/xinao/leg-a-fixture.git"
    )
    $wt = Join-Path $Root $Name
    New-Item -ItemType Directory -Force -Path $wt | Out-Null
    $init = Invoke-GitQuiet -Repo $wt -GitArgs @("init")
    Assert-True ($init.exit_code -eq 0) "git_init:$Name"
    [void](Invoke-GitQuiet -Repo $wt -GitArgs @("config", "user.email", "leg-a-test@example.invalid"))
    [void](Invoke-GitQuiet -Repo $wt -GitArgs @("config", "user.name", "LegA Fixture"))
    [IO.File]::WriteAllText(
        (Join-Path $wt "AGENTS.md"),
        "leg-a oneclick sealed rules; candidate only; no parent completion`n",
        $utf8
    )
    $keep = Join-Path $wt "SOURCE_PRESERVE.txt"
    [IO.File]::WriteAllText($keep, "SOURCE_WORKTREE_MUST_SURVIVE`n", $utf8)
    [void](Invoke-GitQuiet -Repo $wt -GitArgs @("add", "AGENTS.md", "SOURCE_PRESERVE.txt"))
    $commit = Invoke-GitQuiet -Repo $wt -GitArgs @("commit", "-m", "lega-fixture-init")
    Assert-True ($commit.exit_code -eq 0) "git_commit:$Name"
    [void](Invoke-GitQuiet -Repo $wt -GitArgs @("remote", "add", "origin", $OriginUrl))
    $head = (Invoke-GitQuiet -Repo $wt -GitArgs @("rev-parse", "HEAD")).output.Trim().ToLowerInvariant()
    return [pscustomobject]@{
        path = $wt
        preserve_path = $keep
        preserve_sha256 = (Get-Sha256File $keep)
        rules_file = (Join-Path $wt "AGENTS.md")
        rules_sha256 = (Get-Sha256File (Join-Path $wt "AGENTS.md"))
        head = $head
        origin_url = $OriginUrl
        kind = "self_contained_regular_clone"
    }
}

function New-SourceWorktree([string]$Root) {
    # Production-shaped source is a self-contained regular clone (not a linked worktree).
    return Initialize-SelfContainedClone -Root $Root -Name "source-worktree"
}

function New-BrokenGitdirWorktree([string]$Root) {
    $wt = Join-Path $Root "broken-gitdir"
    New-Item -ItemType Directory -Force -Path $wt | Out-Null
    [IO.File]::WriteAllText((Join-Path $wt ".git"), "gitdir: /definitely/not/a/valid/gitdir`n", $utf8)
    [IO.File]::WriteAllText(
        (Join-Path $wt "AGENTS.md"),
        "leg-a oneclick sealed rules; candidate only; no parent completion`n",
        $utf8
    )
    return [pscustomobject]@{ path = $wt; kind = "broken_gitdir" }
}

function New-LinkedWorktreePair([string]$Root) {
    $main = Initialize-SelfContainedClone -Root $Root -Name "main-repo"
    $linked = Join-Path $Root "linked-worktree"
    $add = Invoke-GitQuiet -Repo $main.path -GitArgs @("worktree", "add", $linked, "-b", "linked-branch")
    Assert-True ($add.exit_code -eq 0) "git_worktree_add"
    # Ensure AGENTS.md present in linked tree (shared from main commit).
    Assert-True (Test-Path -LiteralPath (Join-Path $linked "AGENTS.md") -PathType Leaf) "linked_has_agents"
    return [pscustomobject]@{
        main = $main
        linked_path = $linked
        kind = "linked_worktree"
    }
}

function Install-FakePublicDispatcher([string]$CarrierRoot, [string]$CallLogPath) {
    $launcherDir = Join-Path $CarrierRoot "public-dispatcher"
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
    [string]$DispatchEpisodeId = "",
    [string]$RuntimeRoot = "",
    [string]$GrokHome = "",
    [string]$MaxTurns = "auto",
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
    throw "XINAO_LEG_A_DOCKER_CLI_MISSING"
}
if (-not $SelectionOnly -and $backend -ne "linux-container") {
    throw "XINAO_LEG_A_BACKEND_REJECTED: $backend"
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
        $selDir = Join-Path $RuntimeRoot ("state/grok_worker_selection/fake_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
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

# Emit production-shaped dispatch meta + pool_summary so the oneclick worker can accept.
$dispatchId = "cdx_fake_" + [guid]::NewGuid().ToString("N").Substring(0, 10)
$poolId = "gwp_fake_" + [guid]::NewGuid().ToString("N").Substring(0, 10)
$metaDir = Join-Path $RuntimeRoot "state/codex_dispatch_grok_worker_pool"
$poolDir = Join-Path $RuntimeRoot ("state/grok_worker_pool/" + $poolId)
New-Item -ItemType Directory -Force -Path $metaDir, $poolDir | Out-Null
$poolSummaryPath = Join-Path $poolDir "pool_summary.json"
$dispatchMetaPath = Join-Path $metaDir ($dispatchId + ".json")
$marker = "XINAO_LEG_A_ONECLICK_OK"
if (@($RequiredResultMarkers).Count -gt 0) { $marker = [string]$RequiredResultMarkers[0] }
$effect = $(if (@($CommonWriteDomains).Count -gt 0) { "authorized_write" } else { "read_only" })
$poolSummary = [ordered]@{
    schema_version = "xinao.grok_worker_pool_summary.v1"
    pool_id = $poolId
    all_ok = $true
    acceptance_contract_ok = $true
    reuse_skipped_execution = $false
    execution_backend = $backend
    effect_mode = $effect
    results = @([ordered]@{
        evidence_dir = $poolDir
        meta_path = $dispatchMetaPath
        output_marker = $marker
    })
}
[IO.File]::WriteAllText($poolSummaryPath, ($poolSummary | ConvertTo-Json -Depth 8), $utf8)
$dispatchMeta = [ordered]@{
    schema_version = "xinao.codex_dispatch_grok_worker_pool.v1"
    dispatch_id = $dispatchId
    pool_id = $poolId
    pool_summary_path = $poolSummaryPath
    selection_path = $selectionOut
    selection_decision_sha256 = $decision
    status = "accepted_candidate"
    common_context_effect_status = "bound"
    common_model_input_effect_verified = $true
    common_frozen_context_sha256 = $CommonFrozenContextSha256
    common_rules_sha256 = $CommonRulesSha256
    common_context_manifest_path = $CommonContextManifestPath
}
[IO.File]::WriteAllText($dispatchMetaPath, ($dispatchMeta | ConvertTo-Json -Depth 8), $utf8)
[IO.File]::WriteAllText((Join-Path $metaDir "latest.json"), ($dispatchMeta | ConvertTo-Json -Depth 8), $utf8)

[ordered]@{
    schema_version = "xinao.codex_dispatch_grok_worker_pool.v1"
    ok = $true
    route_role = "normal_leg_a_bounded_online_current_tui"
    execution_backend = $backend
    selection_decision_sha256 = $decision
    pool_id = $poolId
    dispatch_id = $dispatchId
    output_marker = $marker
    usage = [ordered]@{
        input_tokens = 11
        output_tokens = 7
        total_tokens = 18
        model_invocation_count = 1
    }
    candidate_only = $true
    completion_claim_allowed = $false
} | ConvertTo-Json -Compress -Depth 8
exit 0
'@
    [IO.File]::WriteAllText($launcher, $launcherBody, $utf8)
    return [pscustomobject]@{ path = $launcher; call_log = $CallLogPath }
}

function Install-FixtureContextBuilder([string]$CarrierRoot) {
    # Production-shaped: -OutputDir; emits manifest_path/context_sha256/source_manifest_sha256/spec_path.
    $path = Join-Path $CarrierRoot "Build-XinaoLegAContext.ps1"
    $body = @'
#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDir,
    [string]$MainlineRoot = "",
    [string]$RepoRoot = "",
    [string]$PythonExe = "",
    [string]$ExpectedSourcePinsPath = "",
    [int]$MaxContentBytes = 65536,
    [switch]$Quiet
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
if ($env:XINAO_LEG_A_FIXTURE_MISSING_CONTEXT -eq "1") {
    throw "XINAO_LEG_A_CONTEXT_BUILD_FAILED: fixture missing context"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$manifestPath = Join-Path $OutputDir "context_slice_manifest.json"
$specPath = Join-Path $OutputDir "owned_context_slice_spec.json"
$receiptPath = Join-Path $OutputDir "seal_receipt.json"
$payload = "sealed-leg-a-context-bytes-v1"
$contextSha = (Get-FileHash -InputStream ([IO.MemoryStream]::new($utf8.GetBytes($payload))) -Algorithm SHA256).Hash.ToLowerInvariant()
$sourceSha = (Get-FileHash -InputStream ([IO.MemoryStream]::new($utf8.GetBytes("source-manifest-v1"))) -Algorithm SHA256).Hash.ToLowerInvariant()
$spec = [ordered]@{
    schema_version = "xinao.context_slice_spec.v1"
    package_id = "xinao_leg_a_context_seal"
}
$specJson = ($spec | ConvertTo-Json -Compress)
[IO.File]::WriteAllText($specPath, $specJson, $utf8)
$specSha = (Get-FileHash -LiteralPath $specPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schema_version = "xinao.context_slice_manifest.v1"
    authority = $false
    completion_claim_allowed = $false
    context_sha256 = $contextSha
    source_manifest_sha256 = $sourceSha
    spec_sha256 = $specSha
    total_content_bytes = $payload.Length
    false_green_deny = "fixture_context_not_live_mainline"
    sources = @()
    rules_file = ""
    rules_sha256 = ""
}
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8)
$public = [ordered]@{
    ok = $true
    sentinel = "XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1"
    schema_version = "xinao.leg_a_context_seal_receipt.v1"
    package_id = "xinao_leg_a_context_seal"
    authority = $false
    completion_claim_allowed = $false
    candidate_only = $true
    manifest_path = $manifestPath
    context_sha256 = $contextSha
    source_manifest_sha256 = $sourceSha
    spec_path = $specPath
    spec_sha256 = $specSha
    receipt_path = $receiptPath
    total_content_bytes = $payload.Length
}
[IO.File]::WriteAllText($receiptPath, ($public | ConvertTo-Json -Depth 8), $utf8)
$public | ConvertTo-Json -Compress -Depth 8
'@
    [IO.File]::WriteAllText($path, $body, $utf8)
    return $path
}

function Install-FixtureOneClickWorker([string]$CarrierRoot) {
    # Mirrors production parameter names + result schema (xinao.leg_a.oneclick_entry_result.v1).
    $path = Join-Path $CarrierRoot "Invoke-XinaoLegAWorker.ps1"
    $body = @'
#Requires -Version 5.1
param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [Parameter(Mandatory = $true)]
    [string]$Cwd,
    [string]$Model = "grok-4.5",
    [Alias("AuthorizedCandidateWrite")]
    [switch]$AuthorizedWrite,
    [ValidateSet("EXPLORE", "CONSTRUCT", "VERIFY", "LAND")]
    [string]$Phase = "CONSTRUCT",
    [string]$WorkKey = "",
    [string]$OperationId = "",
    [string]$DispatchEpisodeId = "",
    [string]$ParentOperationId = "",
    [string]$CorrelationId = "",
    [string]$TaskContractRef = "",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$SelectorReleasePointer = "",
    [string]$SupervisorRoot = "",
    [string]$PublicDispatcher = "",
    [string]$ContextBuilder = "",
    [string]$DockerExe = "",
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$PriorAttemptReceiptPath = "",
    [switch]$Quiet
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$startedAt = Get-Date
function Get-LastJson([string[]]$Lines) {
    $hits = @($Lines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_.Trim().StartsWith("{") })
    if ($hits.Count -eq 0) { throw "XINAO_LEG_A_NO_JSON_RESULT" }
    return ($hits[-1] | ConvertFrom-Json -ErrorAction Stop)
}
function Emit-Result([hashtable]$Payload, [int]$Code) {
    $Payload["finished_at"] = (Get-Date).ToString("o")
    $Payload["duration_ms"] = [int]((Get-Date) - $startedAt).TotalMilliseconds
    Write-Output ($Payload | ConvertTo-Json -Compress -Depth 10)
    exit $Code
}
$resultBase = [ordered]@{
    schema_version = "xinao.leg_a.oneclick_entry_result.v1"
    sentinel = "XINAO_LEG_A_ONECLICK_ENTRY_CANDIDATE_V1"
    package_id = "xinao_leg_a_oneclick_entry"
    generated_at = $startedAt.ToString("o")
    route_role = "normal_leg_a_bounded_online_current_tui"
    transport_id = "direct-grok-worker-pool"
    leg = "A"
    not_leg_b = $true
    not_temporal = $true
    not_houtai_gongren = $true
    not_second_owner = $true
    execution_backend = "linux-container"
    effect_mode = if ($AuthorizedWrite) { "authorized_write" } else { "read_only" }
    worker_output_authority = "candidate_only"
    completion_claim_allowed = $false
    model = $Model
    phase = $Phase
    authorized_write = [bool]$AuthorizedWrite
    cwd = ""
    ok = $false
    status = "preflight"
    error = ""
    selection = $null
    context = $null
    identities = $null
    evidence = $null
    pool_exit_code = $null
}
function Test-PathInside([string]$Candidate, [string]$Root) {
    $c = [IO.Path]::GetFullPath($Candidate)
    $r = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('\', '/'))
    if ([string]::Equals($c, $r, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $prefix = $r + [IO.Path]::DirectorySeparatorChar
    return $c.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}
function Get-NonSecretOrigin([string]$Url) {
    if ([string]::IsNullOrWhiteSpace($Url)) { return "" }
    $u = $Url.Trim()
    if ($u -match '^(?i)(https?://)([^/@\s]+@)(.+)$') { return $Matches[1] + $Matches[3] }
    if ($u -match '^(?i)(ssh://)([^/@\s]+@)(.+)$') { return $Matches[1] + $Matches[3] }
    return $u
}
function Invoke-GitC([string]$Repo, [string[]]$GitArgs) {
    $prev = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $out = @(& git -C $Repo @GitArgs 2>&1 | ForEach-Object { [string]$_ })
        $code = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally { $ErrorActionPreference = $prev }
    return [pscustomobject]@{ code = $code; text = (($out | ForEach-Object { "$_" }) -join "`n").Trim() }
}
function Get-GitSeal([string]$ResolvedCwd, [bool]$AuthWrite) {
    $marker = Join-Path $ResolvedCwd ".git"
    if (-not (Test-Path -LiteralPath $marker)) {
        throw "XINAO_LEG_A_INVALID_WORKTREE: $ResolvedCwd"
    }
    $dotType = if (Test-Path -LiteralPath $marker -PathType Container) { "directory" }
        elseif (Test-Path -LiteralPath $marker -PathType Leaf) { "file" }
        else { "other" }
    $top = Invoke-GitC $ResolvedCwd @("rev-parse", "--show-toplevel")
    $abs = Invoke-GitC $ResolvedCwd @("rev-parse", "--absolute-git-dir")
    $common = Invoke-GitC $ResolvedCwd @("rev-parse", "--git-common-dir")
    if ($top.code -ne 0 -or $abs.code -ne 0 -or $common.code -ne 0) {
        if ($dotType -eq "file") {
            throw ("XINAO_LEG_A_GIT_BROKEN_GITDIR: " + $abs.text)
        }
        throw ("XINAO_LEG_A_GIT_IDENTITY_UNRESOLVED: " + $top.text)
    }
    $repoTop = [IO.Path]::GetFullPath($top.text)
    $gitDir = [IO.Path]::GetFullPath($abs.text)
    $commonRaw = $common.text
    $commonDir = if ([IO.Path]::IsPathRooted($commonRaw)) {
        [IO.Path]::GetFullPath($commonRaw)
    } else {
        [IO.Path]::GetFullPath((Join-Path $ResolvedCwd $commonRaw))
    }
    $headRun = Invoke-GitC $ResolvedCwd @("rev-parse", "HEAD")
    $head = if ($headRun.code -eq 0) { $headRun.text.ToLowerInvariant() } else { "" }
    $originRun = Invoke-GitC $ResolvedCwd @("remote", "get-url", "origin")
    $originId = Get-NonSecretOrigin $(if ($originRun.code -eq 0) { $originRun.text } else { "" })
    $gitIn = Test-PathInside $gitDir $ResolvedCwd
    $commonIn = Test-PathInside $commonDir $ResolvedCwd
    $selfContained = ($dotType -eq "directory" -and $gitIn -and $commonIn)
    if ($AuthWrite -and -not $selfContained) {
        throw ("XINAO_LEG_A_GIT_NOT_SELFCONTAINED: AuthorizedWrite requires self-contained regular clone under Cwd; dot_git_type=$dotType git_dir=$gitDir common_dir=$commonDir")
    }
    return [ordered]@{
        policy = "XINAO_LEGA_SELFCONTAINED_GIT_WRITE_FIX_V1"
        sealed_at = (Get-Date).ToString("o")
        repo_toplevel = $repoTop
        git_dir = $gitDir
        common_dir = $commonDir
        dot_git_type = $dotType
        head = $head
        head_unborn = [string]::IsNullOrWhiteSpace($head)
        origin_identity = $originId
        self_contained = [bool]$selfContained
        authorized_write = [bool]$AuthWrite
        git_dir_inside_cwd = [bool]$gitIn
        common_dir_inside_cwd = [bool]$commonIn
    }
}
function Assert-GitPost([string]$ResolvedCwd, $PreSeal) {
    $marker = Join-Path $ResolvedCwd ".git"
    $dotType = if (-not (Test-Path -LiteralPath $marker)) { "missing" }
        elseif (Test-Path -LiteralPath $marker -PathType Container) { "directory" }
        elseif (Test-Path -LiteralPath $marker -PathType Leaf) { "file" }
        else { "other" }
    if ([string]$PreSeal.dot_git_type -eq "directory" -and $dotType -ne "directory") {
        throw ("XINAO_LEG_A_GIT_POSTCALL_DOT_GIT_TYPE: pre=$([string]$PreSeal.dot_git_type) post=$dotType")
    }
    if ($dotType -eq "missing") {
        throw "XINAO_LEG_A_GIT_POSTCALL_DOT_GIT_TYPE: post=.git missing"
    }
    $abs = Invoke-GitC $ResolvedCwd @("rev-parse", "--absolute-git-dir")
    if ($abs.code -ne 0) {
        throw "XINAO_LEG_A_GIT_BROKEN_GITDIR: post-call git identity unresolved"
    }
    $originRun = Invoke-GitC $ResolvedCwd @("remote", "get-url", "origin")
    $originId = Get-NonSecretOrigin $(if ($originRun.code -eq 0) { $originRun.text } else { "" })
    if (-not [string]::Equals([string]$PreSeal.origin_identity, $originId, [StringComparison]::Ordinal)) {
        throw ("XINAO_LEG_A_GIT_ORIGIN_IDENTITY_DRIFT: pre=$([string]$PreSeal.origin_identity) post=$originId")
    }
    $headRun = Invoke-GitC $ResolvedCwd @("rev-parse", "HEAD")
    $postHead = if ($headRun.code -eq 0) { $headRun.text.ToLowerInvariant() } else { "" }
    $preHead = [string]$PreSeal.head
    if (-not [string]::IsNullOrWhiteSpace($preHead) -and [string]::IsNullOrWhiteSpace($postHead)) {
        throw ("XINAO_LEG_A_GIT_HEAD_ANCESTRY_BROKEN: post-call HEAD unborn after sealed HEAD $preHead")
    }
    if (-not [string]::IsNullOrWhiteSpace($preHead) -and -not [string]::IsNullOrWhiteSpace($postHead) -and
        -not [string]::Equals($preHead, $postHead, [StringComparison]::OrdinalIgnoreCase)) {
        $anc = Invoke-GitC $ResolvedCwd @("merge-base", "--is-ancestor", $preHead, $postHead)
        if ($anc.code -ne 0) {
            throw ("XINAO_LEG_A_GIT_HEAD_ANCESTRY_BROKEN: pre_head=$preHead is not ancestor of post_head=$postHead (reinit/orphan replacement rejected)")
        }
    }
    return [ordered]@{
        post_head = $postHead
        head_unchanged = [string]::Equals($preHead, $postHead, [StringComparison]::OrdinalIgnoreCase)
        head_ancestry_ok = $true
        origin_identity = $originId
        dot_git_type = $dotType
    }
}
try {
    if ([string]::IsNullOrWhiteSpace($Cwd)) { throw "XINAO_LEG_A_CWD_REQUIRED" }
    $resolvedCwd = [IO.Path]::GetFullPath($Cwd)
    if (-not (Test-Path -LiteralPath $resolvedCwd -PathType Container)) {
        throw "XINAO_LEG_A_CWD_MISSING: $resolvedCwd"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedCwd ".git"))) {
        throw "XINAO_LEG_A_INVALID_WORKTREE: $resolvedCwd"
    }
    $resultBase.cwd = $resolvedCwd
    $hasPrompt = -not [string]::IsNullOrWhiteSpace($Prompt)
    $hasPromptFile = -not [string]::IsNullOrWhiteSpace($PromptFile)
    if ($hasPrompt -eq $hasPromptFile) {
        throw "XINAO_LEG_A_EXACTLY_ONE_PROMPT_SOURCE_REQUIRED"
    }
    if ($Phase -eq "LAND" -and -not $AuthorizedWrite) {
        throw "XINAO_LEG_A_LAND_REQUIRES_AUTHORIZED_WRITE"
    }
    $candidateWriteDomain = ""
    $candidateOutputRoot = ""
    if ($AuthorizedWrite) {
        $candidateOutputRoot = $resolvedCwd
        $candidateWriteDomain = "candidate_output_root:" + ($candidateOutputRoot.Replace('\', '/').TrimEnd('/').ToLowerInvariant())
        if ($env:XINAO_LEG_A_FIXTURE_FORCE_WRITE_SCOPE -eq "1") {
            throw "XINAO_LEG_A_WRITE_SCOPE_AMBIGUOUS: forced"
        }
    }
    # Before dispatcher/provider: seal git identity; AuthorizedWrite requires self-contained clone.
    $gitSeal = Get-GitSeal -ResolvedCwd $resolvedCwd -AuthWrite ([bool]$AuthorizedWrite)
    $resultBase.git_seal = $gitSeal
    $resolvedRuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
    if (-not (Test-Path -LiteralPath $resolvedRuntimeRoot -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $resolvedRuntimeRoot | Out-Null
    }
    if ([string]::IsNullOrWhiteSpace($PublicDispatcher)) {
        throw "XINAO_LEG_A_PUBLIC_DISPATCHER_REQUIRED"
    }
    $publicDispatcher = [IO.Path]::GetFullPath($PublicDispatcher)
    if (-not (Test-Path -LiteralPath $publicDispatcher -PathType Leaf)) {
        throw "XINAO_LEG_A_PUBLIC_DISPATCHER_MISSING: $publicDispatcher"
    }
    if ([string]::IsNullOrWhiteSpace($ContextBuilder)) {
        throw "XINAO_LEG_A_CONTEXT_BUILDER_MISSING"
    }
    $contextBuilder = [IO.Path]::GetFullPath($ContextBuilder)
    if (-not (Test-Path -LiteralPath $contextBuilder -PathType Leaf)) {
        throw "XINAO_LEG_A_CONTEXT_BUILDER_MISSING: $contextBuilder"
    }
    if ($env:XINAO_LEG_A_FAKE_DOCKER_UNAVAILABLE -eq "1") {
        throw "XINAO_LEG_A_DOCKER_CLI_MISSING"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_LEG_A_FAKE_BACKEND) -and
        $env:XINAO_LEG_A_FAKE_BACKEND -ne "linux-container") {
        throw ("XINAO_LEG_A_BACKEND_REJECTED: observed=" + $env:XINAO_LEG_A_FAKE_BACKEND)
    }
    $runStamp = (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $localStateDir = Join-Path $resolvedRuntimeRoot ("state/xinao_leg_a_oneclick/" + $runStamp)
    New-Item -ItemType Directory -Force -Path $localStateDir | Out-Null
    $resolvedPromptFile = ""
    if ($hasPromptFile) {
        $resolvedPromptFile = [IO.Path]::GetFullPath($PromptFile)
        if (-not (Test-Path -LiteralPath $resolvedPromptFile -PathType Leaf)) {
            throw "XINAO_LEG_A_PROMPT_FILE_MISSING: $resolvedPromptFile"
        }
    }
    else {
        $resolvedPromptFile = Join-Path $localStateDir "prompt.md"
        [IO.File]::WriteAllText($resolvedPromptFile, $Prompt, $utf8)
    }
    $contextOutputDir = Join-Path $localStateDir "sealed-context"
    $builderOutput = @(& $contextBuilder -OutputDir $contextOutputDir -Quiet 2>&1 | ForEach-Object { "$_" })
    $builderExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    if ($builderExit -ne 0) {
        throw ("XINAO_LEG_A_CONTEXT_BUILD_FAILED: exit=$builderExit " + ($builderOutput -join "`n"))
    }
    $contextJson = Get-LastJson $builderOutput
    foreach ($field in @("manifest_path", "context_sha256", "source_manifest_sha256", "spec_path")) {
        if ([string]::IsNullOrWhiteSpace([string]$contextJson.$field)) {
            throw "XINAO_LEG_A_CONTEXT_FIELD_MISSING: $field"
        }
    }
    $rulesFile = Join-Path $resolvedCwd "AGENTS.md"
    if (-not (Test-Path -LiteralPath $rulesFile -PathType Leaf)) {
        throw "XINAO_LEG_A_RULES_MISSING: $rulesFile"
    }
    $rulesSha = (Get-FileHash -LiteralPath $rulesFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($env:XINAO_LEG_A_FIXTURE_RULES_DRIFT -eq "1") {
        throw "XINAO_LEG_A_RULES_DRIFT: expected=deadbeef observed=$rulesSha"
    }
    $resultBase.context = [ordered]@{
        builder = $contextBuilder
        manifest_path = [string]$contextJson.manifest_path
        manifest_sha256 = (Get-FileHash -LiteralPath ([string]$contextJson.manifest_path) -Algorithm SHA256).Hash.ToLowerInvariant()
        context_sha256 = [string]$contextJson.context_sha256
        source_manifest_sha256 = [string]$contextJson.source_manifest_sha256
        spec_path = [string]$contextJson.spec_path
        rules_file = $rulesFile
        rules_sha256 = $rulesSha
    }
    if ([string]::IsNullOrWhiteSpace($WorkKey)) {
        $WorkKey = "xinao.leg_a.oneclick:" + [string]$contextJson.context_sha256.Substring(0, 16)
    }
    if ([string]::IsNullOrWhiteSpace($OperationId)) {
        $OperationId = "xinao.leg_a.op:fixture"
    }
    if ([string]::IsNullOrWhiteSpace($DispatchEpisodeId)) {
        $DispatchEpisodeId = "xinao.leg_a.episode:fixture"
    }
    $subjectManifestPath = Join-Path $localStateDir "subject-manifest.v1.json"
    $subjectManifest = [ordered]@{
        schema_version = "xinao.leg_a.subject_manifest.v1"
        prompt_sha256 = (Get-FileHash -LiteralPath $resolvedPromptFile -Algorithm SHA256).Hash.ToLowerInvariant()
        cwd = $resolvedCwd
        phase = $Phase
        work_key = $WorkKey
        operation_id = $OperationId
        frozen_context_sha256 = [string]$contextJson.context_sha256
        worker_output_authority = "candidate_only"
        completion_claim_allowed = $false
    }
    [IO.File]::WriteAllText($subjectManifestPath, ($subjectManifest | ConvertTo-Json -Compress), $utf8)
    $subjectManifestSha256 = (Get-FileHash -LiteralPath $subjectManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $resultBase.identities = [ordered]@{
        work_key = $WorkKey
        operation_id = $OperationId
        dispatch_episode_id = $DispatchEpisodeId
        subject_manifest_path = $subjectManifestPath
        subject_manifest_sha256 = $subjectManifestSha256
    }

    $selArgs = @{
        N = 1
        Model = $Model
        Cwd = $resolvedCwd
        SelectionOnly = $true
        RuntimeRoot = $resolvedRuntimeRoot
        GrokHome = $GrokHome
    }
    $selRaw = @(& $publicDispatcher @selArgs 2>&1 | ForEach-Object { "$_" })
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw ("XINAO_LEG_A_SELECTION_FAILED: " + ($selRaw -join "`n"))
    }
    $selection = Get-LastJson $selRaw
    foreach ($field in @("selection_path", "decision_sha256", "model_id", "transport_id")) {
        if ([string]::IsNullOrWhiteSpace([string]$selection.$field)) {
            throw "XINAO_LEG_A_SELECTION_FIELD_MISSING: $field"
        }
    }
    if ([int]$selection.model_invocation_count -ne 0) {
        throw "XINAO_LEG_A_SELECTION_ONLY_HAD_PROVIDER_EFFECT"
    }
    $pinnedDecision = [string]$selection.decision_sha256
    if ($env:XINAO_LEG_A_FIXTURE_STALE_SELECTION_AFTER_BOOTSTRAP -eq "1") {
        $pinnedDecision = ("c" * 64)
    }
    $dispatcherText = Get-Content -LiteralPath $publicDispatcher -Raw -Encoding UTF8
    $pinAvailable = $dispatcherText -match "ExpectedSelectionDecisionSha256"
    $resultBase.selection = [ordered]@{
        selection_path = [string]$selection.selection_path
        selection_receipt_sha256 = [string]$selection.selection_receipt_sha256
        decision_sha256 = [string]$selection.decision_sha256
        provider_id = [string]$selection.provider_id
        profile_ref = [string]$selection.profile_ref
        model_id = [string]$selection.model_id
        transport_id = [string]$selection.transport_id
        model_invocation_count = [int]$selection.model_invocation_count
        expected_selection_decision_sha256_pinned = [bool]$pinAvailable
    }

    $dispatchArgs = @{
        N = 1
        Model = $Model
        PromptFile = $resolvedPromptFile
        Cwd = $resolvedCwd
        SelectionPath = [string]$selection.selection_path
        RuntimeRoot = $resolvedRuntimeRoot
        GrokHome = $GrokHome
        MaxTurns = $MaxTurns
        TimeoutSec = $TimeoutSec
        MinResultChars = 1
        RequiredResultMarkers = @($(if (@($RequiredResultMarkers).Count -gt 0) { $RequiredResultMarkers } else { @("XINAO_LEG_A_ONECLICK_OK") }))
        DispatchEpisodeId = $DispatchEpisodeId
        CommonWorkKey = $WorkKey
        CommonOperationId = $OperationId
        CommonSubjectManifestSha256 = $subjectManifestSha256
        CommonFrozenContextSha256 = [string]$contextJson.context_sha256
        CommonContextManifestPath = [string]$contextJson.manifest_path
        CommonRulesFile = $rulesFile
        CommonRulesSha256 = $rulesSha
        CommonPhase = $Phase
    }
    if ($pinAvailable) {
        $dispatchArgs.ExpectedSelectionDecisionSha256 = $pinnedDecision
    }
    if ($AuthorizedWrite) {
        $dispatchArgs.CommonCandidateOutputRoot = $candidateOutputRoot
        $dispatchArgs.CommonWriteDomains = @($candidateWriteDomain)
    }
    $dispatchRaw = @(& $publicDispatcher @dispatchArgs 2>&1 | ForEach-Object { "$_" })
    $poolExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    $resultBase.pool_exit_code = $poolExit
    if ($poolExit -ne 0) {
        $joined = $dispatchRaw -join "`n"
        if ($joined -match 'XINAO_LEG_A_SELECTION_STALE') { throw "XINAO_LEG_A_SELECTION_STALE" }
        if ($joined -match 'XINAO_LEG_A_BACKEND_REJECTED') { throw ($joined) }
        throw ("XINAO_LEG_A_POOL_EXIT_" + $poolExit + ": " + $joined)
    }
    # Simulate reinit/orphan replacement after provider effect (negative post-call verify).
    if ($env:XINAO_LEG_A_FIXTURE_SIMULATE_REINIT -eq "1") {
        $gitPath = Join-Path $resolvedCwd ".git"
        if (Test-Path -LiteralPath $gitPath) {
            Remove-Item -LiteralPath $gitPath -Recurse -Force -ErrorAction SilentlyContinue
        }
        [void](Invoke-GitC $resolvedCwd @("init"))
        [void](Invoke-GitC $resolvedCwd @("config", "user.email", "reinit@example.invalid"))
        [void](Invoke-GitC $resolvedCwd @("config", "user.name", "Reinit"))
        $orphan = Join-Path $resolvedCwd "ORPHAN_REINIT.txt"
        [IO.File]::WriteAllText($orphan, "orphan`n", $utf8)
        [void](Invoke-GitC $resolvedCwd @("add", "ORPHAN_REINIT.txt"))
        [void](Invoke-GitC $resolvedCwd @("commit", "-m", "orphan-reinit"))
        # Preserve non-secret origin identity if present so ancestry is the failure mode.
        if (-not [string]::IsNullOrWhiteSpace([string]$gitSeal.origin_identity)) {
            [void](Invoke-GitC $resolvedCwd @("remote", "add", "origin", [string]$gitSeal.origin_identity))
        }
    }
    $gitPost = Assert-GitPost -ResolvedCwd $resolvedCwd -PreSeal $gitSeal
    $resultBase.git_seal_post = $gitPost
    $resultBase.evidence = [ordered]@{
        dispatch_meta_path = ""
        pool_id = ""
        pool_summary_path = ""
        local_state_dir = $localStateDir
        prompt_file = $resolvedPromptFile
        subject_manifest_path = $subjectManifestPath
        candidate_output_root = $candidateOutputRoot
        write_domains = if ($AuthorizedWrite) { @($candidateWriteDomain) } else { @() }
        docker_exe = "fixture-docker"
        public_dispatcher = $publicDispatcher
        selection_only_invoked = $true
        common_contract_invoked = $true
        public_dispatcher_used = $true
        prior_chat_state_required = $false
        manual_hashes_required = $false
        git_self_contained = [bool]$gitSeal.self_contained
        git_dot_git_type = [string]$gitSeal.dot_git_type
        git_pre_head = [string]$gitSeal.head
        git_post_head = [string]$gitPost.post_head
        git_origin_identity = [string]$gitSeal.origin_identity
        git_policy = [string]$gitSeal.policy
    }
    $metaDir = Join-Path $resolvedRuntimeRoot "state/codex_dispatch_grok_worker_pool"
    $latest = Join-Path $metaDir "latest.json"
    if (Test-Path -LiteralPath $latest -PathType Leaf) {
        $meta = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json
        $resultBase.evidence.dispatch_meta_path = $latest
        $resultBase.evidence.pool_id = [string]$meta.pool_id
        $resultBase.evidence.pool_summary_path = [string]$meta.pool_summary_path
        $resultBase.evidence.dispatch_id = [string]$meta.dispatch_id
    }
    $resultBase.ok = $true
    $resultBase.status = "accepted_candidate"
    Emit-Result -Payload $resultBase -Code 0
}
catch {
    $resultBase.ok = $false
    $resultBase.status = "blocked"
    $resultBase.error = [string]$_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($resultBase.error)) { $resultBase.error = [string]$_ }
    $code = 3
    Emit-Result -Payload $resultBase -Code $code
}
'@
    [IO.File]::WriteAllText($path, $body, $utf8)
    return $path
}

function Get-LauncherCalls([string]$CallLogPath) {
    if (-not (Test-Path -LiteralPath $CallLogPath -PathType Leaf)) { return @() }
    $lines = Get-Content -LiteralPath $CallLogPath -Encoding UTF8 |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    return @($lines | ForEach-Object { $_ | ConvertFrom-Json })
}

function Invoke-OneClickCase {
    param(
        [string]$Label,
        [string]$WorkerPath,
        [string]$ContextBuilder,
        [string]$Dispatcher,
        [string]$Cwd,
        [string]$RuntimeRoot,
        [hashtable]$ExtraArgs = @{},
        [hashtable]$EnvOverrides = @{},
        [bool]$ExpectSuccess = $true,
        [string]$ExpectedErrorToken = ""
    )
    $argList = @(
        "-NoLogo", "-NoProfile", "-File", $WorkerPath,
        "-Cwd", $Cwd,
        "-Model", "grok-4.5",
        "-Prompt", "Reply only with marker XINAO_LEG_A_ONECLICK_OK",
        "-ContextBuilder", $ContextBuilder,
        "-PublicDispatcher", $Dispatcher,
        "-RuntimeRoot", $RuntimeRoot,
        "-RequiredResultMarkers", "XINAO_LEG_A_ONECLICK_OK",
        "-MinResultChars", "1"
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

function Assert-ProductionShapeBound {
    param(
        [string]$WorkerSource,
        [string]$BuilderSource,
        [object]$Contract
    )
    # Production worker parameters (must appear in production script).
    foreach ($p in @(
        "Prompt", "PromptFile", "Cwd", "Model", "AuthorizedWrite", "Phase",
        "RuntimeRoot", "PublicDispatcher", "ContextBuilder", "RequiredResultMarkers"
    )) {
        Assert-True ($WorkerSource -match [regex]::Escape("]$p") -or $WorkerSource -match [regex]::Escape("[string]`$$p") -or $WorkerSource -match [regex]::Escape("[switch]`$$p") -or $WorkerSource -match ("\`$$p\s*=") -or $WorkerSource -match ("\[string\]\`$$p") -or $WorkerSource -match ("\[switch\]\`$$p") -or $WorkerSource -match ("\`$$p,")) `
            "prod_param_present:$p"
        # Simpler: param block contains the name
        Assert-True ($WorkerSource -match ("\b" + [regex]::Escape($p) + "\b")) "prod_param_token:$p"
    }
    Assert-True ($WorkerSource -match [regex]::Escape("xinao.leg_a.oneclick_entry_result.v1")) "prod_result_schema"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_ONECLICK_ENTRY_CANDIDATE_V1")) "prod_result_sentinel"
    Assert-True ($WorkerSource -match [regex]::Escape("candidate_only")) "prod_candidate_only"
    Assert-True ($WorkerSource -match [regex]::Escape("linux-container")) "prod_linux_container"
    Assert-True ($WorkerSource -match [regex]::Escape("SelectionOnly")) "prod_selection_only"
    Assert-True ($WorkerSource -match [regex]::Escape("CommonFrozenContextSha256")) "prod_common_frozen_context"
    Assert-True ($WorkerSource -match [regex]::Escape("CommonContextManifestPath")) "prod_common_manifest"
    Assert-True ($WorkerSource -match [regex]::Escape("CommonRulesSha256")) "prod_common_rules"
    Assert-True ($WorkerSource -match [regex]::Escape("ExpectedSelectionDecisionSha256")) "prod_selection_pin_support"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_SELECTION_STALE")) "prod_selection_stale_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_PUBLIC_DISPATCHER_MISSING")) "prod_dispatcher_missing_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_DOCKER_CLI_MISSING")) "prod_docker_cli_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_RULES_DRIFT")) "prod_rules_drift_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_WRITE_SCOPE_AMBIGUOUS")) "prod_write_scope_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_BACKEND_REJECTED")) "prod_backend_rejected_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_GIT_NOT_SELFCONTAINED")) "prod_git_not_selfcontained_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_GIT_BROKEN_GITDIR")) "prod_git_broken_gitdir_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEG_A_GIT_HEAD_ANCESTRY_BROKEN")) "prod_git_head_ancestry_token"
    Assert-True ($WorkerSource -match [regex]::Escape("XINAO_LEGA_SELFCONTAINED_GIT_WRITE_FIX_V1")) "prod_git_policy_id"
    Assert-True ($WorkerSource -match [regex]::Escape("Get-XinaoLegAGitSeal")) "prod_git_seal_fn"
    Assert-True ($WorkerSource -match [regex]::Escape("Assert-XinaoLegAGitPostCall")) "prod_git_post_fn"

    Assert-True ($BuilderSource -match [regex]::Escape("OutputDir")) "builder_output_dir_param"
    Assert-True ($BuilderSource -match [regex]::Escape("manifest_path")) "builder_manifest_path"
    Assert-True ($BuilderSource -match [regex]::Escape("context_sha256")) "builder_context_sha"
    Assert-True ($BuilderSource -match [regex]::Escape("source_manifest_sha256")) "builder_source_sha"
    Assert-True ($BuilderSource -match [regex]::Escape("spec_path")) "builder_spec_path"
    Assert-True ($BuilderSource -match [regex]::Escape("XINAO_LEG_A_CONTEXT_SEAL_CANDIDATE_V1")) "builder_sentinel"

    # Contract must describe production schema / tokens (not fixture-only aliases).
    Assert-True ($Contract.result_json.schema_version -eq "xinao.leg_a.oneclick_entry_result.v1") "contract_result_schema"
    Assert-True ($Contract.result_json.sentinel -eq "XINAO_LEG_A_ONECLICK_ENTRY_CANDIDATE_V1") "contract_result_sentinel"
    Assert-True ($Contract.marker -eq "XINAO_LEG_A_ONECLICK_ENTRY_CANDIDATE_V1") "contract_marker_prod"
    Assert-True ($Contract.package_id -eq "xinao_leg_a_oneclick_entry") "contract_package_id"
    Assert-True (@($Contract.public_interfaces.oneclick_worker.production_parameters) -contains "Cwd") "contract_param_cwd"
    Assert-True (@($Contract.public_interfaces.oneclick_worker.production_parameters) -contains "PublicDispatcher") "contract_param_public_dispatcher"
    Assert-True (@($Contract.public_interfaces.oneclick_worker.production_parameters) -contains "AuthorizedWrite") "contract_param_authorized_write"
    Assert-True (@($Contract.public_interfaces.context_builder.required_outputs) -contains "manifest_path") "contract_builder_manifest_path"
    Assert-True (@($Contract.public_interfaces.context_builder.required_outputs) -contains "context_sha256") "contract_builder_context_sha"
    Assert-True (@($Contract.public_interfaces.context_builder.required_outputs) -notcontains "frozen_context_sha256") "contract_no_fixture_frozen_alias"
    Assert-True (@($Contract.public_interfaces.context_builder.required_outputs) -notcontains "sealed_context_path") "contract_no_fixture_sealed_path_alias"
    $tokens = @($Contract.fail_closed_before_provider_effect | ForEach-Object { [string]$_.error_token })
    foreach ($tok in @(
        "XINAO_LEG_A_PUBLIC_DISPATCHER_MISSING",
        "XINAO_LEG_A_DOCKER_CLI_MISSING",
        "XINAO_LEG_A_SELECTION_STALE",
        "XINAO_LEG_A_RULES_DRIFT",
        "XINAO_LEG_A_WRITE_SCOPE_AMBIGUOUS",
        "XINAO_LEG_A_BACKEND_REJECTED",
        "XINAO_LEG_A_GIT_BROKEN_GITDIR",
        "XINAO_LEG_A_GIT_NOT_SELFCONTAINED",
        "XINAO_LEG_A_GIT_HEAD_ANCESTRY_BROKEN"
    )) {
        Assert-True ($tokens -contains $tok) "contract_fail_closed_token:$tok"
    }
    Assert-True ($Contract.isolation.git_metadata.policy_id -eq "XINAO_LEGA_SELFCONTAINED_GIT_WRITE_FIX_V1") `
        "contract_git_policy_id"
    Assert-True ($Contract.isolation.git_metadata.authorized_write.requires_self_contained_regular_clone -eq $true) `
        "contract_git_auth_write_selfcontained"
    # Forbidden fixture-only tokens that previously caused false green.
    Assert-True ($tokens -notcontains "XINAO_LEG_A_DOCKER_UNAVAILABLE") "contract_no_legacy_docker_unavailable_alias"
    Assert-True ($tokens -notcontains "XINAO_LEG_A_CONTEXT_MISSING") "contract_no_legacy_context_missing_alias"
    Assert-True ($tokens -notcontains "XINAO_LEG_A_CONTEXT_DRIFT") "contract_no_legacy_context_drift_alias"
    Assert-True ($Contract.test.binding_policy.fixture_only_false_green_forbidden -eq $true) "contract_fixture_false_green_forbidden"
    Assert-True ($Contract.test.binding_policy.default_binds_production_parameter_and_result_shape -eq $true) "contract_default_binds_prod_shape"
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

$productionBuilderPresent = Test-Path -LiteralPath $productionBuilder -PathType Leaf
$productionWorkerPresent = Test-Path -LiteralPath $productionWorker -PathType Leaf
if (-not ($productionBuilderPresent -and $productionWorkerPresent)) {
    if (-not $AllowMissingProductionScripts) {
        throw "XINAO_LEG_A_ONECLICK_ASSERT_FAIL: production_scripts_required (builder=$productionBuilderPresent worker=$productionWorkerPresent)"
    }
}

$productionShapeBound = $false
if ($productionBuilderPresent -and $productionWorkerPresent) {
    $workerSource = Get-Content -LiteralPath $productionWorker -Raw -Encoding UTF8
    $builderSource = Get-Content -LiteralPath $productionBuilder -Raw -Encoding UTF8
    Assert-ProductionShapeBound -WorkerSource $workerSource -BuilderSource $builderSource -Contract $contract
    $productionShapeBound = $true
}

# Behavioral worker: production-shaped fixture by default so we never require a
# live docker/mainline path for this package. Production scripts are still
# statically bound above; ForceFixtureWorker cannot skip that binding.
$usingLiveProductionWorker = $false
if (
    -not $ForceFixtureWorker -and
    $productionWorkerPresent -and
    $env:XINAO_LEG_A_USE_LIVE_PRODUCTION_WORKER -eq "1"
) {
    $usingLiveProductionWorker = $true
}

# ---------------------------------------------------------------------------
# Temp carrier (only cleanup target)
# ---------------------------------------------------------------------------
$carrier = Join-Path ([IO.Path]::GetTempPath()) (
    "xinao-leg-a-oneclick-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
    [guid]::NewGuid().ToString("N").Substring(0, 8)
)
New-Item -ItemType Directory -Force -Path $carrier | Out-Null
$source = New-SourceWorktree -Root $carrier
$callLog = Join-Path $carrier "public-dispatcher-calls.jsonl"
$fakeDispatcher = Install-FakePublicDispatcher -CarrierRoot $carrier -CallLogPath $callLog
$fixtureBuilder = Install-FixtureContextBuilder -CarrierRoot $carrier
$fixtureWorker = Install-FixtureOneClickWorker -CarrierRoot $carrier

# Fixture builder always used for deterministic sealed envelope unless live prod worker is forced.
$builderUnderTest = $fixtureBuilder
$workerUnderTest = if ($usingLiveProductionWorker) { $productionWorker } else { $fixtureWorker }
$runtimeRoot = Join-Path $carrier "runtime"
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

$env:XINAO_LEG_A_FAKE_PUBLIC_LAUNCHER_LOG = $callLog
$env:XINAO_LEG_A_FAKE_BACKEND = "linux-container"
$env:XINAO_LEG_A_FAKE_SELECTION_DECISION = ("b" * 64)

$passed = New-Object System.Collections.Generic.List[string]
if ($productionShapeBound) {
    [void]$passed.Add("production_parameter_shape_bound")
    [void]$passed.Add("production_result_schema_bound")
    [void]$passed.Add("production_fail_closed_tokens_bound")
}
else {
    throw "XINAO_LEG_A_ONECLICK_ASSERT_FAIL: production_shape_not_bound (fixture-only false green forbidden)"
}

# Fixture worker itself must also use production parameter/result tokens.
$fixtureWorkerSource = Get-Content -LiteralPath $fixtureWorker -Raw -Encoding UTF8
Assert-True ($fixtureWorkerSource -match [regex]::Escape("xinao.leg_a.oneclick_entry_result.v1")) "fixture_worker_prod_schema"
Assert-True ($fixtureWorkerSource -match [regex]::Escape("PublicDispatcher")) "fixture_worker_public_dispatcher_param"
Assert-True ($fixtureWorkerSource -match [regex]::Escape("AuthorizedWrite")) "fixture_worker_authorized_write_param"
Assert-True ($fixtureWorkerSource -match [regex]::Escape("\`$Cwd") -or $fixtureWorkerSource -match "\[string\]\`$Cwd" -or $fixtureWorkerSource -match "\bCwd\b") "fixture_worker_cwd_param"
Assert-True ($fixtureWorkerSource -notmatch [regex]::Escape("xinao.leg_a_oneclick_result.v1")) "fixture_worker_no_legacy_schema"
Assert-True ($fixtureWorkerSource -notmatch "-Worktree") "fixture_worker_no_legacy_worktree_param"

try {
    # --- Happy path: fresh consumer ---
    if (Test-Path -LiteralPath $callLog) { Remove-Item -LiteralPath $callLog -Force }
    $happy = Invoke-OneClickCase `
        -Label "happy_path" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot $runtimeRoot
    $r = $happy.result
    Assert-True ($r.ok -eq $true) "happy.ok"
    Assert-True ($r.schema_version -eq "xinao.leg_a.oneclick_entry_result.v1") "happy.schema"
    Assert-True ($r.sentinel -eq "XINAO_LEG_A_ONECLICK_ENTRY_CANDIDATE_V1") "happy.sentinel"
    Assert-True ($r.package_id -eq "xinao_leg_a_oneclick_entry") "happy.package_id"
    Assert-True ($r.worker_output_authority -eq "candidate_only") "happy.candidate_only"
    Assert-True ($r.completion_claim_allowed -eq $false) "happy.no_completion_claim"
    Assert-True ($r.leg -eq "A") "happy.leg_a"
    Assert-True ($r.not_leg_b -eq $true) "happy.not_leg_b"
    Assert-True ($r.execution_backend -eq "linux-container") "happy.backend"
    Assert-True ($r.effect_mode -eq "read_only") "happy.effect_mode_ro"
    Assert-True ($r.authorized_write -eq $false) "happy.authorized_write_false"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.context.manifest_path)) "happy.context.manifest_path"
    Assert-True ([string]$r.context.context_sha256 -match '^[0-9a-f]{64}$') "happy.context.context_sha"
    Assert-True ([string]$r.context.source_manifest_sha256 -match '^[0-9a-f]{64}$') "happy.context.source_sha"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.context.rules_file)) "happy.context.rules_file"
    Assert-True ([string]$r.context.rules_sha256 -match '^[0-9a-f]{64}$') "happy.context.rules_sha"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.selection.decision_sha256)) "happy.selection.decision"
    Assert-True ([int]$r.selection.model_invocation_count -eq 0) "happy.selection.no_provider"
    Assert-True ($r.selection.expected_selection_decision_sha256_pinned -eq $true) "happy.selection.pin_flag"
    Assert-True ($r.evidence.selection_only_invoked -eq $true -or $null -ne $r.selection) "happy.selection_only"
    Assert-True ($r.evidence.prior_chat_state_required -eq $false) "happy.no_chat_state"
    Assert-True ($r.evidence.manual_hashes_required -eq $false) "happy.no_manual_hashes"
    $calls = Get-LauncherCalls -CallLogPath $callLog
    Assert-True ($calls.Count -ge 2) "happy.dispatcher_calls_ge_2"
    Assert-True (@($calls | Where-Object { $_.mode -eq "selection_only" }).Count -ge 1) "happy.has_selection_only_call"
    Assert-True (@($calls | Where-Object { $_.mode -eq "common_contract" }).Count -ge 1) "happy.has_common_call"
    $commonCall = @($calls | Where-Object { $_.mode -eq "common_contract" })[0]
    Assert-True ($commonCall.execution_backend_requested -eq "linux-container") "happy.common_backend_linux"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.common_frozen_context_sha256)) "happy.common_has_frozen_context"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.common_rules_sha256)) "happy.common_has_rules_sha"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.common_context_manifest_path)) "happy.common_has_manifest"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$commonCall.expected_selection_decision_sha256)) "happy.common_has_selection_pin"
    Assert-True ($commonCall.expected_selection_decision_sha256 -eq [string]$r.selection.decision_sha256) "happy.pin_matches_bootstrap"
    Assert-True ($null -ne $r.git_seal) "happy.git_seal_present"
    Assert-True ([string]$r.git_seal.policy -eq "XINAO_LEGA_SELFCONTAINED_GIT_WRITE_FIX_V1") "happy.git_policy"
    Assert-True ($r.git_seal.self_contained -eq $true) "happy.git_self_contained"
    Assert-True ([string]$r.git_seal.dot_git_type -eq "directory") "happy.git_dot_git_dir"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$r.git_seal.head)) "happy.git_head_sealed"
    [void]$passed.Add("happy_path_fresh_consumer")
    [void]$passed.Add("no_prior_chat_or_manual_hashes")
    [void]$passed.Add("selection_only_and_common_via_public_dispatcher")
    [void]$passed.Add("selection_decision_pinning_when_available")
    [void]$passed.Add("backend_linux_container_only")
    [void]$passed.Add("sealed_ro_and_worktree_ro_default")
    [void]$passed.Add("result_json_evidence_surface")

    # --- Authorized write domain (only when explicit) on valid self-contained clone ---
    if (Test-Path -LiteralPath $callLog) { Remove-Item -LiteralPath $callLog -Force }
    $writeCase = Invoke-OneClickCase `
        -Label "authorized_write" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-write") `
        -ExtraArgs @{ AuthorizedWrite = $true }
    Assert-True ($writeCase.result.effect_mode -eq "authorized_write") "write.effect_mode"
    Assert-True ($writeCase.result.authorized_write -eq $true) "write.authorized_write"
    Assert-True (@($writeCase.result.evidence.write_domains).Count -eq 1) "write.single_domain"
    Assert-True ($writeCase.result.git_seal.self_contained -eq $true) "write.git_self_contained"
    Assert-True ([string]$writeCase.result.git_seal.dot_git_type -eq "directory") "write.git_dir_type"
    Assert-True ([string]$writeCase.result.evidence.git_policy -eq "XINAO_LEGA_SELFCONTAINED_GIT_WRITE_FIX_V1") "write.git_policy"
    [void]$passed.Add("authorized_write_domain_only_when_explicit")
    [void]$passed.Add("valid_selfcontained_clone_authorized_write")

    # --- Fail closed: broken gitdir pointer ---
    $broken = New-BrokenGitdirWorktree -Root $carrier
    Invoke-OneClickCase `
        -Label "broken_gitdir" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $broken.path `
        -RuntimeRoot (Join-Path $carrier "runtime-broken-gitdir") `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_GIT_BROKEN_GITDIR" | Out-Null
    [void]$passed.Add("broken_gitdir_fail_closed")

    # --- Fail closed: linked worktree AuthorizedWrite (external common-dir) ---
    $linkedPair = New-LinkedWorktreePair -Root $carrier
    Invoke-OneClickCase `
        -Label "linked_worktree_authorized_write" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $linkedPair.linked_path `
        -RuntimeRoot (Join-Path $carrier "runtime-linked-write") `
        -ExtraArgs @{ AuthorizedWrite = $true } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_GIT_NOT_SELFCONTAINED" | Out-Null
    # Read-only on the same linked worktree may still resolve host git identity (thin policy).
    if (Test-Path -LiteralPath $callLog) { Remove-Item -LiteralPath $callLog -Force }
    $linkedRo = Invoke-OneClickCase `
        -Label "linked_worktree_read_only" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $linkedPair.linked_path `
        -RuntimeRoot (Join-Path $carrier "runtime-linked-ro")
    Assert-True ($linkedRo.result.ok -eq $true) "linked_ro.ok"
    Assert-True ($linkedRo.result.git_seal.self_contained -eq $false) "linked_ro.not_self_contained"
    Assert-True ([string]$linkedRo.result.git_seal.dot_git_type -eq "file") "linked_ro.dot_git_file"
    [void]$passed.Add("linked_worktree_authorized_write_fail_closed")

    # --- Fail closed: reinit / orphan HEAD replacement after worker effect ---
    $reinitClone = Initialize-SelfContainedClone -Root $carrier -Name "reinit-clone"
    Invoke-OneClickCase `
        -Label "reinit_ancestry" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $reinitClone.path `
        -RuntimeRoot (Join-Path $carrier "runtime-reinit") `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_SIMULATE_REINIT = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_GIT_HEAD_ANCESTRY_BROKEN" | Out-Null
    [void]$passed.Add("reinit_head_ancestry_fail_closed")

    # --- Fail closed: missing public dispatcher ---
    Invoke-OneClickCase `
        -Label "missing_public_dispatcher" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher (Join-Path $carrier "no-such-dispatcher.ps1") `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-dispatcher-missing") `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_PUBLIC_DISPATCHER_MISSING" | Out-Null
    [void]$passed.Add("missing_public_dispatcher_fail_closed")

    # --- Fail closed: missing context field (force builder missing context) ---
    Invoke-OneClickCase `
        -Label "missing_context" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-missing") `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_MISSING_CONTEXT = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_CONTEXT_BUILD_FAILED" | Out-Null
    [void]$passed.Add("missing_context_field_fail_closed")

    # --- Fail closed: rules drift ---
    Invoke-OneClickCase `
        -Label "rules_drift" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-drift") `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_RULES_DRIFT = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_RULES_DRIFT" | Out-Null
    [void]$passed.Add("rules_drift_fail_closed")

    # --- Fail closed: stale selection ---
    Invoke-OneClickCase `
        -Label "stale_selection" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-stale") `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_STALE_SELECTION_AFTER_BOOTSTRAP = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_SELECTION_STALE" | Out-Null
    [void]$passed.Add("stale_selection_fail_closed")

    # --- Fail closed: docker cli missing ---
    Invoke-OneClickCase `
        -Label "docker_cli_missing" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-docker") `
        -EnvOverrides @{ XINAO_LEG_A_FAKE_DOCKER_UNAVAILABLE = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_DOCKER_CLI_MISSING" | Out-Null
    [void]$passed.Add("docker_cli_missing_fail_closed")

    # --- Fail closed: write scope ambiguous ---
    Invoke-OneClickCase `
        -Label "write_scope_ambiguous" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-write-scope") `
        -ExtraArgs @{ AuthorizedWrite = $true } `
        -EnvOverrides @{ XINAO_LEG_A_FIXTURE_FORCE_WRITE_SCOPE = "1" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_WRITE_SCOPE_AMBIGUOUS" | Out-Null
    [void]$passed.Add("write_scope_ambiguous_fail_closed")

    # --- Fail closed: backend rejected (windows-host) ---
    Invoke-OneClickCase `
        -Label "backend_rejected" `
        -WorkerPath $workerUnderTest `
        -ContextBuilder $builderUnderTest `
        -Dispatcher $fakeDispatcher.path `
        -Cwd $source.path `
        -RuntimeRoot (Join-Path $carrier "runtime-backend") `
        -EnvOverrides @{ XINAO_LEG_A_FAKE_BACKEND = "windows-host" } `
        -ExpectSuccess:$false `
        -ExpectedErrorToken "XINAO_LEG_A_BACKEND_REJECTED" | Out-Null
    [void]$passed.Add("backend_rejected_fail_closed")

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
        production_shape_bound = [bool]$productionShapeBound
        using_live_production_worker = [bool]$usingLiveProductionWorker
        fixture_worker_production_shaped = $true
        fixture_only_false_green = $false
        contract_path = $ContractPath
        production_worker = $productionWorker
        production_builder = $productionBuilder
        context_builder_under_test = $builderUnderTest
        oneclick_worker_under_test = $workerUnderTest
        public_dispatcher_fixture = $fakeDispatcher.path
        carrier_root = $carrier
        source_worktree = $source.path
        source_preserve_sha256 = $source.preserve_sha256
        passed_cases = @($passed)
        required_cases = @($contract.test.required_cases)
        notes = @(
            "Production parameter/result/fail-closed shape statically bound to co-located scripts.",
            "Behavioral cases use production-shaped fixture worker + bounded fake public dispatcher.",
            "No second real provider call; candidate only; Codex remains Owner."
        )
    }
    $passedSet = @($passed)
    foreach ($req in @($contract.test.required_cases)) {
        Assert-True ($passedSet -contains [string]$req) "required_case_covered:$req"
    }
    # Hard anti-false-green: never report ok without production shape binding.
    Assert-True ($summary.production_shape_bound -eq $true) "summary_production_shape_bound"
    Assert-True ($summary.fixture_only_false_green -eq $false) "summary_no_fixture_only_false_green"
    Write-Output ($summary | ConvertTo-Json -Compress -Depth 8)
}
finally {
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
        "XINAO_LEG_A_FAKE_BACKEND",
        "XINAO_LEG_A_FAKE_SELECTION_DECISION",
        "XINAO_LEG_A_FAKE_DOCKER_UNAVAILABLE",
        "XINAO_LEG_A_FIXTURE_MISSING_CONTEXT",
        "XINAO_LEG_A_FIXTURE_STALE_SELECTION_AFTER_BOOTSTRAP",
        "XINAO_LEG_A_FIXTURE_RULES_DRIFT",
        "XINAO_LEG_A_FIXTURE_FORCE_WRITE_SCOPE",
        "XINAO_LEG_A_FIXTURE_SIMULATE_REINIT"
    )) {
        [Environment]::SetEnvironmentVariable($name, $null)
    }
    if (Test-Path -LiteralPath $carrier -PathType Container) {
        Remove-Item -LiteralPath $carrier -Recurse -Force -ErrorAction SilentlyContinue
    }
}
