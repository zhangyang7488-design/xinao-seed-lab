#Requires -Version 7.0
<#
.SYNOPSIS
  One stable XINAO leg-A entry: seal base context, select, run common-contract Grok.
.DESCRIPTION
  Thin composition only. A fresh caller supplies Prompt/PromptFile and an explicit
  candidate worktree Cwd. This entry seals the current XINAO base context via
  Build-XinaoLegAContext.ps1, bootstraps selection through the public
  Invoke-Codex-GrokWorkerPool -SelectionOnly surface, then runs N=1 common-contract
  mode in the existing linux-container backend.

  Normal leg A only. Never Temporal, houtai-gongren, a daemon, a second owner,
  silent windows-host fallback, secret copy, or broad D/C mounts.
  Output is always candidate-only; Codex remains Owner/integrator.
.EXAMPLE
  .\Invoke-XinaoLegAWorker.ps1 -Prompt "Reply only: LEGA_OK" -Cwd D:\worktrees\candidate -RequiredResultMarkers LEGA_OK
  .\Invoke-XinaoLegAWorker.ps1 -PromptFile .\task.md -Cwd D:\worktrees\candidate -AuthorizedWrite
#>
[CmdletBinding()]
param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
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
    [string]$PublicDispatcher = "C:\Users\xx363\CodexLaunchers\Invoke-Codex-GrokWorkerPool.ps1",
    [string]$ContextBuilder = "",
    [string]$DockerExe = "",
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [string]$MaxTurns = "auto",
    [ValidateRange(60, 86400)]
    [int]$TimeoutSec = 600,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$PriorAttemptReceiptPath = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridgeRoot = $PSScriptRoot
$startedAt = Get-Date

function Get-XinaoLegAUtf8Sha256([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $algorithm.Dispose()
    }
}
function Get-XinaoLegAFileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function ConvertTo-XinaoLegACandidateWriteDomain([string]$ResolvedRoot) {
    return "candidate_output_root:" + ($ResolvedRoot.Replace('\', '/').TrimEnd('/').ToLowerInvariant())
}

function Write-XinaoLegAResult {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Payload,
        [int]$ExitCode = 0
    )
    $Payload["finished_at"] = (Get-Date).ToString("o")
    if ($null -eq $Payload["duration_ms"]) {
        $Payload["duration_ms"] = [int]((Get-Date) - $startedAt).TotalMilliseconds
    }
    $json = $Payload | ConvertTo-Json -Depth 10 -Compress
    Write-Output $json
    exit $ExitCode
}

function Throw-XinaoLegAPreflight([string]$Code, [string]$Detail = "") {
    $message = if ([string]::IsNullOrWhiteSpace($Detail)) { $Code } else { "$Code`: $Detail" }
    throw $message
}

function Get-XinaoLegALastJsonObject([object[]]$Lines) {
    $textLines = @(
        $Lines | ForEach-Object { [string]$_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($textLines.Count -lt 1) {
        return $null
    }
    for ($i = $textLines.Count - 1; $i -ge 0; $i--) {
        $candidate = $textLines[$i].Trim()
        if (-not ($candidate.StartsWith("{") -and $candidate.EndsWith("}"))) {
            continue
        }
        try {
            return ($candidate | ConvertFrom-Json -ErrorAction Stop)
        }
        catch {
            continue
        }
    }
    $joined = ($textLines -join [Environment]::NewLine).Trim()
    if ($joined.StartsWith("{") -and $joined.EndsWith("}")) {
        try {
            return ($joined | ConvertFrom-Json -ErrorAction Stop)
        }
        catch {
            return $null
        }
    }
    return $null
}

function Assert-XinaoLegAWorktree([string]$ResolvedCwd) {
    if (-not (Test-Path -LiteralPath $ResolvedCwd -PathType Container)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CWD_MISSING" $ResolvedCwd
    }
    $gitMarker = Join-Path $ResolvedCwd ".git"
    if (-not (Test-Path -LiteralPath $gitMarker)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_INVALID_WORKTREE" "cwd is not a git worktree: $ResolvedCwd"
    }
    # Reject ambiguous reparse / empty worktree shells without object identity.
    try {
        $item = Get-Item -LiteralPath $ResolvedCwd -Force
        if ($null -eq $item) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_INVALID_WORKTREE" "cwd unreadable: $ResolvedCwd"
        }
    }
    catch {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_INVALID_WORKTREE" "$_"
    }
}

function Assert-XinaoLegALinuxDockerCapability([string]$ResolvedCwd, [ref]$DockerPathOut) {
    $docker = $DockerExe
    if ([string]::IsNullOrWhiteSpace($docker)) {
        $docker = [string](
            Get-Command docker.exe -ErrorAction SilentlyContinue |
                Select-Object -First 1 -ExpandProperty Source
        )
    }
    if ([string]::IsNullOrWhiteSpace($docker)) {
        $docker = [string](
            Get-Command docker -ErrorAction SilentlyContinue |
                Select-Object -First 1 -ExpandProperty Source
        )
    }
    if ([string]::IsNullOrWhiteSpace($docker) -or -not (Test-Path -LiteralPath $docker -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_DOCKER_CLI_MISSING" "linux-container capability unavailable"
    }
    $docker = [IO.Path]::GetFullPath($docker)
    $DockerPathOut.Value = $docker

    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $docker
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.WorkingDirectory = $ResolvedCwd
    if ($null -ne $psi.PSObject.Properties['ArgumentList']) {
        [void]$psi.ArgumentList.Add("info")
        [void]$psi.ArgumentList.Add("--format")
        [void]$psi.ArgumentList.Add("{{json .OSType}}")
    }
    else {
        $psi.Arguments = 'info --format "{{json .OSType}}"'
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit(60000) | Out-Null
    if (-not $process.HasExited) {
        try { $process.Kill($true) } catch { try { $process.Kill() } catch {} }
        Throw-XinaoLegAPreflight "XINAO_LEG_A_DOCKER_INFO_TIMEOUT"
    }
    if ($process.ExitCode -ne 0) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_DOCKER_INFO_FAILED" ("exit=" + $process.ExitCode + " err=" + $stderr)
    }
    try {
        $osType = [string]($stdout | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_DOCKER_INFO_INVALID" $stdout
    }
    if (-not [string]::Equals($osType, "linux", [StringComparison]::OrdinalIgnoreCase)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_LINUX_ENGINE_REQUIRED" "observed=$osType"
    }
}

function Resolve-XinaoLegAContextObject([object]$Context) {
    if ($null -eq $Context) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_JSON_MISSING"
    }
    $required = @("manifest_path", "context_sha256", "source_manifest_sha256", "spec_path")
    foreach ($field in $required) {
        $value = [string]$Context.$field
        if ([string]::IsNullOrWhiteSpace($value)) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_FIELD_MISSING" $field
        }
    }
    $contextSha = ([string]$Context.context_sha256).ToLowerInvariant()
    $sourceSha = ([string]$Context.source_manifest_sha256).ToLowerInvariant()
    if ($contextSha -notmatch '^[0-9a-f]{64}$') {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_SHA256_INVALID" $contextSha
    }
    if ($sourceSha -notmatch '^[0-9a-f]{64}$') {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SOURCE_MANIFEST_SHA256_INVALID" $sourceSha
    }

    try { $manifestPath = [IO.Path]::GetFullPath([string]$Context.manifest_path) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_MANIFEST_PATH_INVALID" ([string]$Context.manifest_path) }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_MANIFEST_MISSING" $manifestPath
    }
    $observedManifestSha = Get-XinaoLegAFileSha256 $manifestPath
    # Prefer explicit context-manifest content hash when builder supplies it; otherwise
    # only enforce that the manifest bytes exist. Drift against context_sha256 is checked
    # when builder emits matching fields.
    if (
        $null -ne $Context.PSObject.Properties["manifest_sha256"] -and
        -not [string]::IsNullOrWhiteSpace([string]$Context.manifest_sha256)
    ) {
        $expectedManifestSha = ([string]$Context.manifest_sha256).ToLowerInvariant()
        if ($expectedManifestSha -notmatch '^[0-9a-f]{64}$' -or $expectedManifestSha -ne $observedManifestSha) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_MANIFEST_DRIFT" "expected=$expectedManifestSha observed=$observedManifestSha"
        }
    }

    try { $specPath = [IO.Path]::GetFullPath([string]$Context.spec_path) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_SPEC_PATH_INVALID" ([string]$Context.spec_path) }
    if (-not (Test-Path -LiteralPath $specPath -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SPEC_MISSING" $specPath
    }

    $rulesPath = ""
    foreach ($name in @("rules_file", "rules_path", "common_rules_file")) {
        if (
            $null -ne $Context.PSObject.Properties[$name] -and
            -not [string]::IsNullOrWhiteSpace([string]$Context.$name)
        ) {
            $rulesPath = [string]$Context.$name
            break
        }
    }
    # Fall back to rules identity sealed inside the context manifest (current rules).
    if ([string]::IsNullOrWhiteSpace($rulesPath)) {
        try {
            $manifestObject = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
                ConvertFrom-Json -ErrorAction Stop
            foreach ($name in @("rules_file", "rules_path", "common_rules_file")) {
                if (
                    $null -ne $manifestObject.PSObject.Properties[$name] -and
                    -not [string]::IsNullOrWhiteSpace([string]$manifestObject.$name)
                ) {
                    $rulesPath = [string]$manifestObject.$name
                    break
                }
            }
            if (
                [string]::IsNullOrWhiteSpace($rulesPath) -and
                $null -ne $manifestObject.PSObject.Properties["rules"] -and
                $null -ne $manifestObject.rules
            ) {
                foreach ($name in @("path", "file", "rules_file")) {
                    if (
                        $null -ne $manifestObject.rules.PSObject.Properties[$name] -and
                        -not [string]::IsNullOrWhiteSpace([string]$manifestObject.rules.$name)
                    ) {
                        $rulesPath = [string]$manifestObject.rules.$name
                        break
                    }
                }
            }
        }
        catch {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_MANIFEST_JSON_INVALID" $manifestPath
        }
    }
    if ([string]::IsNullOrWhiteSpace($rulesPath)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_RULES_MISSING" "builder/manifest must identify current rules_file"
    }
    try { $rulesPath = [IO.Path]::GetFullPath($rulesPath) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_RULES_PATH_INVALID" $rulesPath }
    if (-not (Test-Path -LiteralPath $rulesPath -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_RULES_MISSING" $rulesPath
    }
    $observedRulesSha = Get-XinaoLegAFileSha256 $rulesPath
    $rulesSha = $observedRulesSha
    $expectedRulesSha = ""
    if (
        $null -ne $Context.PSObject.Properties["rules_sha256"] -and
        -not [string]::IsNullOrWhiteSpace([string]$Context.rules_sha256)
    ) {
        $expectedRulesSha = ([string]$Context.rules_sha256).ToLowerInvariant()
    }
    elseif (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        try {
            $manifestForRules = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
                ConvertFrom-Json -ErrorAction Stop
            if (
                $null -ne $manifestForRules.PSObject.Properties["rules_sha256"] -and
                -not [string]::IsNullOrWhiteSpace([string]$manifestForRules.rules_sha256)
            ) {
                $expectedRulesSha = ([string]$manifestForRules.rules_sha256).ToLowerInvariant()
            }
            elseif (
                $null -ne $manifestForRules.PSObject.Properties["rules"] -and
                $null -ne $manifestForRules.rules -and
                $null -ne $manifestForRules.rules.PSObject.Properties["sha256"] -and
                -not [string]::IsNullOrWhiteSpace([string]$manifestForRules.rules.sha256)
            ) {
                $expectedRulesSha = ([string]$manifestForRules.rules.sha256).ToLowerInvariant()
            }
        }
        catch {
            # rules path already resolved; hash drift check is best-effort from sealed bytes.
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($expectedRulesSha)) {
        if ($expectedRulesSha -notmatch '^[0-9a-f]{64}$' -or $expectedRulesSha -ne $observedRulesSha) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_RULES_DRIFT" "expected=$expectedRulesSha observed=$observedRulesSha"
        }
        $rulesSha = $expectedRulesSha
    }

    return [ordered]@{
        manifest_path = $manifestPath
        manifest_sha256 = $observedManifestSha
        context_sha256 = $contextSha
        source_manifest_sha256 = $sourceSha
        spec_path = $specPath
        rules_file = $rulesPath
        rules_sha256 = $rulesSha
        raw = $Context
    }
}

function Find-XinaoLegADispatchEvidence {
    param(
        [string]$Runtime,
        [string]$SelectionDecisionSha256,
        [string]$SelectionPath,
        [datetime]$NotBeforeUtc
    )

    $metaDir = Join-Path $Runtime "state\codex_dispatch_grok_worker_pool"
    $candidates = @()
    if (Test-Path -LiteralPath $metaDir -PathType Container) {
        $candidates = @(
            Get-ChildItem -LiteralPath $metaDir -Filter "cdx_*.json" -File -ErrorAction SilentlyContinue |
                Where-Object { $_.LastWriteTimeUtc -ge $NotBeforeUtc.AddMinutes(-1) } |
                Sort-Object LastWriteTimeUtc -Descending
        )
    }
    foreach ($file in $candidates) {
        try {
            $meta = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            continue
        }
        $decisionOk = [string]::Equals(
            [string]$meta.selection_decision_sha256,
            $SelectionDecisionSha256,
            [StringComparison]::Ordinal
        )
        $pathOk = (
            [string]::IsNullOrWhiteSpace($SelectionPath) -or
            [string]::Equals(
                [IO.Path]::GetFullPath([string]$meta.selection_path),
                [IO.Path]::GetFullPath($SelectionPath),
                [StringComparison]::OrdinalIgnoreCase
            )
        )
        if ($decisionOk -and $pathOk) {
            return [ordered]@{
                dispatch_meta_path = $file.FullName
                dispatch_meta = $meta
                pool_id = [string]$meta.pool_id
                dispatch_id = [string]$meta.dispatch_id
                pool_summary_path = [string]$meta.pool_summary_path
            }
        }
    }

    $latest = Join-Path $metaDir "latest.json"
    if (Test-Path -LiteralPath $latest -PathType Leaf) {
        try {
            $meta = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
            if ([string]::Equals(
                [string]$meta.selection_decision_sha256,
                $SelectionDecisionSha256,
                [StringComparison]::Ordinal
            )) {
                return [ordered]@{
                    dispatch_meta_path = $latest
                    dispatch_meta = $meta
                    pool_id = [string]$meta.pool_id
                    dispatch_id = [string]$meta.dispatch_id
                    pool_summary_path = [string]$meta.pool_summary_path
                }
            }
        }
        catch {}
    }
    return $null
}

# --- fail-closed preflight (before any provider / selection / pool use) ---
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

try {
    if ([string]::IsNullOrWhiteSpace($Model)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_MODEL_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($Cwd)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CWD_REQUIRED"
    }
    try { $resolvedCwd = [IO.Path]::GetFullPath($Cwd) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_CWD_INVALID" $Cwd }
    Assert-XinaoLegAWorktree -ResolvedCwd $resolvedCwd
    $resultBase.cwd = $resolvedCwd

    $hasPrompt = -not [string]::IsNullOrWhiteSpace($Prompt)
    $hasPromptFile = -not [string]::IsNullOrWhiteSpace($PromptFile)
    if ($hasPrompt -eq $hasPromptFile) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_EXACTLY_ONE_PROMPT_SOURCE_REQUIRED"
    }

    if ($Phase -eq "LAND" -and -not $AuthorizedWrite) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_LAND_REQUIRES_AUTHORIZED_WRITE"
    }

    try { $resolvedRuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_RUNTIME_ROOT_INVALID" $RuntimeRoot }
    if (-not (Test-Path -LiteralPath $resolvedRuntimeRoot -PathType Container)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_RUNTIME_ROOT_MISSING" $resolvedRuntimeRoot
    }

    if ([string]::IsNullOrWhiteSpace($PublicDispatcher)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_PUBLIC_DISPATCHER_REQUIRED"
    }
    try { $publicDispatcher = [IO.Path]::GetFullPath($PublicDispatcher) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_PUBLIC_DISPATCHER_INVALID" $PublicDispatcher }
    if (-not (Test-Path -LiteralPath $publicDispatcher -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_PUBLIC_DISPATCHER_MISSING" $publicDispatcher
    }

    if ([string]::IsNullOrWhiteSpace($ContextBuilder)) {
        $ContextBuilder = Join-Path $bridgeRoot "Build-XinaoLegAContext.ps1"
    }
    try { $contextBuilder = [IO.Path]::GetFullPath($ContextBuilder) }
    catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_BUILDER_INVALID" $ContextBuilder }
    if (-not (Test-Path -LiteralPath $contextBuilder -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_BUILDER_MISSING" $contextBuilder
    }

    $candidateWriteDomain = ""
    $candidateOutputRoot = ""
    if ($AuthorizedWrite) {
        $candidateOutputRoot = $resolvedCwd
        $candidateWriteDomain = ConvertTo-XinaoLegACandidateWriteDomain $candidateOutputRoot
        # Ambiguous write scope: more than one domain or root != cwd is forbidden by design.
        if ([string]::IsNullOrWhiteSpace($candidateWriteDomain)) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_WRITE_SCOPE_AMBIGUOUS" "empty write domain"
        }
        if (-not [string]::Equals($candidateOutputRoot, $resolvedCwd, [StringComparison]::OrdinalIgnoreCase)) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_WRITE_SCOPE_AMBIGUOUS" "candidate output root must equal Cwd"
        }
    }

    $resolvedDocker = ""
    Assert-XinaoLegALinuxDockerCapability -ResolvedCwd $resolvedCwd -DockerPathOut ([ref]$resolvedDocker)

    $runStamp = (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $localStateDir = Join-Path $resolvedRuntimeRoot ("state\xinao_leg_a_oneclick\" + $runStamp)
    New-Item -ItemType Directory -Force -Path $localStateDir | Out-Null

    $resolvedPromptFile = ""
    if ($hasPromptFile) {
        try { $resolvedPromptFile = [IO.Path]::GetFullPath($PromptFile) }
        catch { Throw-XinaoLegAPreflight "XINAO_LEG_A_PROMPT_FILE_INVALID" $PromptFile }
        if (-not (Test-Path -LiteralPath $resolvedPromptFile -PathType Leaf)) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_PROMPT_FILE_MISSING" $resolvedPromptFile
        }
        try {
            $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
            [void][IO.File]::ReadAllText($resolvedPromptFile, $strictUtf8)
        }
        catch {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_PROMPT_FILE_NOT_UTF8" $resolvedPromptFile
        }
    }
    else {
        $resolvedPromptFile = Join-Path $localStateDir "prompt.md"
        [IO.File]::WriteAllText(
            $resolvedPromptFile,
            $Prompt,
            [Text.UTF8Encoding]::new($false)
        )
    }

    # Seal current XINAO base context (no caller-supplied hashes). Keep generated
    # bytes outside the candidate worktree so read-only calls do not dirty it.
    $contextOutputDir = Join-Path $localStateDir "sealed-context"
    $builderOutput = @(
        & $contextBuilder -OutputDir $contextOutputDir -Quiet 2>&1
    )
    $builderExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    if ($builderExit -ne 0) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_CONTEXT_BUILD_FAILED" (
            "exit=$builderExit output=" + (($builderOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine)
        )
    }
    $contextJson = Get-XinaoLegALastJsonObject -Lines $builderOutput
    $rulesFile = Join-Path $resolvedCwd "AGENTS.md"
    if (-not (Test-Path -LiteralPath $rulesFile -PathType Leaf)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_RULES_MISSING" $rulesFile
    }
    $contextJson | Add-Member -NotePropertyName rules_file -NotePropertyValue $rulesFile -Force
    $contextJson | Add-Member `
        -NotePropertyName rules_sha256 `
        -NotePropertyValue (Get-XinaoLegAFileSha256 $rulesFile) `
        -Force
    $context = Resolve-XinaoLegAContextObject -Context $contextJson
    $resultBase.context = [ordered]@{
        builder = $contextBuilder
        manifest_path = [string]$context.manifest_path
        manifest_sha256 = [string]$context.manifest_sha256
        context_sha256 = [string]$context.context_sha256
        source_manifest_sha256 = [string]$context.source_manifest_sha256
        spec_path = [string]$context.spec_path
        rules_file = [string]$context.rules_file
        rules_sha256 = [string]$context.rules_sha256
    }

    # Stable episode / work / operation identities (derived when caller omits them).
    if ([string]::IsNullOrWhiteSpace($WorkKey)) {
        $WorkKey = "xinao.leg_a.oneclick:" + [string]$context.context_sha256.Substring(0, 16)
    }
    if ([string]::IsNullOrWhiteSpace($OperationId)) {
        $OperationId = "xinao.leg_a.op:" + (
            Get-XinaoLegAUtf8Sha256 (
                [string]$context.context_sha256 + "|" +
                $WorkKey + "|" +
                $Phase + "|" +
                [string]$context.source_manifest_sha256
            )
        ).Substring(0, 24)
    }
    if ([string]::IsNullOrWhiteSpace($DispatchEpisodeId)) {
        $DispatchEpisodeId = "xinao.leg_a.episode:" + [string]$context.context_sha256.Substring(0, 24)
    }
    $subjectManifestPath = Join-Path $localStateDir "subject-manifest.v1.json"
    $subjectManifest = [ordered]@{
        schema_version = "xinao.leg_a.subject_manifest.v1"
        prompt_sha256 = Get-XinaoLegAFileSha256 $resolvedPromptFile
        cwd = $resolvedCwd
        phase = $Phase
        work_key = $WorkKey
        operation_id = $OperationId
        frozen_context_sha256 = [string]$context.context_sha256
        worker_output_authority = "candidate_only"
        completion_claim_allowed = $false
    }
    [IO.File]::WriteAllText(
        $subjectManifestPath,
        ($subjectManifest | ConvertTo-Json -Compress -Depth 6),
        [Text.UTF8Encoding]::new($false)
    )
    $subjectManifestSha256 = Get-XinaoLegAFileSha256 $subjectManifestPath
    $resultBase.identities = [ordered]@{
        work_key = $WorkKey
        operation_id = $OperationId
        dispatch_episode_id = $DispatchEpisodeId
        parent_operation_id = $ParentOperationId
        correlation_id = $CorrelationId
        task_contract_ref = $TaskContractRef
        subject_manifest_path = $subjectManifestPath
        subject_manifest_sha256 = $subjectManifestSha256
    }

    # Public selection bootstrap (SelectionOnly). No common-contract fields allowed here.
    $selectionArgs = @{
        N = 1
        Model = $Model
        Cwd = $resolvedCwd
        SelectionOnly = $true
        RuntimeRoot = $resolvedRuntimeRoot
        GrokHome = $GrokHome
    }
    if (-not [string]::IsNullOrWhiteSpace($SupervisorRoot)) {
        $selectionArgs.SupervisorRoot = $SupervisorRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($SelectorReleasePointer)) {
        $selectionArgs.SelectorReleasePointer = $SelectorReleasePointer
    }
    $selectionOutput = @(& $publicDispatcher @selectionArgs 2>&1)
    $selectionExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    if ($selectionExit -ne 0) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_FAILED" (
            "exit=$selectionExit output=" + (($selectionOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine)
        )
    }
    $selection = Get-XinaoLegALastJsonObject -Lines $selectionOutput
    if ($null -eq $selection) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_JSON_MISSING"
    }
    foreach ($field in @("selection_path", "decision_sha256", "model_id", "transport_id")) {
        if ([string]::IsNullOrWhiteSpace([string]$selection.$field)) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_FIELD_MISSING" $field
        }
    }
    if (-not [string]::Equals([string]$selection.model_id, $Model, [StringComparison]::Ordinal)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_MODEL_MISMATCH" (
            "requested=$Model selected=$([string]$selection.model_id)"
        )
    }
    if (-not [string]::Equals(
        [string]$selection.transport_id,
        "direct-grok-worker-pool",
        [StringComparison]::Ordinal
    )) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_TRANSPORT_REJECTED" ([string]$selection.transport_id)
    }
    $pinnedSelectionDecisionSha256 = [string]$selection.decision_sha256
    if ($pinnedSelectionDecisionSha256 -notmatch '^[0-9a-f]{64}$') {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_FIELD_MISSING" "decision_sha256"
    }
    $resultBase.selection = [ordered]@{
        selection_path = [string]$selection.selection_path
        selection_receipt_sha256 = [string]$selection.selection_receipt_sha256
        decision_sha256 = $pinnedSelectionDecisionSha256
        provider_id = [string]$selection.provider_id
        profile_ref = [string]$selection.profile_ref
        model_id = [string]$selection.model_id
        transport_id = [string]$selection.transport_id
        selector_source_sha256 = [string]$selection.selector_source_sha256
        selector_release_binding = $selection.selector_release_binding
        quota_query_performed = $selection.quota_query_performed -eq $true
        model_invocation_count = [int]$selection.model_invocation_count
        expected_selection_decision_sha256_pinned = $false
    }

    # Fail closed if selection receipt bytes drift before common-contract call.
    $selectionPathForPin = [string]$selection.selection_path
    if (Test-Path -LiteralPath $selectionPathForPin -PathType Leaf) {
        try {
            $selectionReceiptReplay = Get-Content -LiteralPath $selectionPathForPin -Raw -Encoding UTF8 |
                ConvertFrom-Json -ErrorAction Stop
            $replayDecision = [string]$selectionReceiptReplay.decision_sha256
            if ([string]::IsNullOrWhiteSpace($replayDecision) -and
                $null -ne $selectionReceiptReplay.PSObject.Properties["decision"] -and
                $null -ne $selectionReceiptReplay.decision) {
                $replayDecision = [string]$selectionReceiptReplay.decision.decision_sha256
            }
            if (
                -not [string]::IsNullOrWhiteSpace($replayDecision) -and
                -not [string]::Equals(
                    $replayDecision,
                    $pinnedSelectionDecisionSha256,
                    [StringComparison]::Ordinal
                )
            ) {
                Throw-XinaoLegAPreflight "XINAO_LEG_A_SELECTION_STALE" (
                    "bootstrap=$pinnedSelectionDecisionSha256 receipt=$replayDecision"
                )
            }
        }
        catch {
            if ("$_" -match 'XINAO_LEG_A_SELECTION_STALE') { throw }
            # Receipt shape may vary; SelectionPath pin below remains authoritative.
        }
    }

    # Common-contract bounded dispatch via public launcher. Hashes come only from
    # sealed context / local rehash — never from caller-supplied hidden digests.
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
        MinResultChars = $MinResultChars
        RequiredResultMarkers = @($RequiredResultMarkers)
        DispatchEpisodeId = $DispatchEpisodeId
        CommonWorkKey = $WorkKey
        CommonOperationId = $OperationId
        CommonSubjectManifestSha256 = $subjectManifestSha256
        CommonFrozenContextSha256 = [string]$context.context_sha256
        CommonContextManifestPath = [string]$context.manifest_path
        CommonRulesFile = [string]$context.rules_file
        CommonRulesSha256 = [string]$context.rules_sha256
        CommonPhase = $Phase
    }
    # Pin selection decision when the host public dispatcher declares the parameter.
    $dispatcherDeclaresSelectionPin = $false
    try {
        $dispatcherSource = Get-Content -LiteralPath $publicDispatcher -Raw -Encoding UTF8 -ErrorAction Stop
        $dispatcherDeclaresSelectionPin = $dispatcherSource -match 'ExpectedSelectionDecisionSha256'
    }
    catch {
        $dispatcherDeclaresSelectionPin = $false
    }
    if ($dispatcherDeclaresSelectionPin) {
        $dispatchArgs.ExpectedSelectionDecisionSha256 = $pinnedSelectionDecisionSha256
        $resultBase.selection.expected_selection_decision_sha256_pinned = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($SupervisorRoot)) {
        $dispatchArgs.SupervisorRoot = $SupervisorRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($SelectorReleasePointer)) {
        $dispatchArgs.SelectorReleasePointer = $SelectorReleasePointer
    }
    if (-not [string]::IsNullOrWhiteSpace($ParentOperationId)) {
        $dispatchArgs.CommonParentOperationId = $ParentOperationId
    }
    if (-not [string]::IsNullOrWhiteSpace($CorrelationId)) {
        $dispatchArgs.CommonCorrelationId = $CorrelationId
    }
    if (-not [string]::IsNullOrWhiteSpace($TaskContractRef)) {
        $dispatchArgs.CommonTaskContractRef = $TaskContractRef
    }
    if (-not [string]::IsNullOrWhiteSpace($PriorAttemptReceiptPath)) {
        $dispatchArgs.CommonPriorAttemptReceiptPath = $PriorAttemptReceiptPath
    }
    if ($RequireJsonObject) {
        $dispatchArgs.RequireJsonObject = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($JsonSchemaPath)) {
        $dispatchArgs.JsonSchemaPath = $JsonSchemaPath
    }
    if ($AuthorizedWrite) {
        $dispatchArgs.CommonCandidateOutputRoot = $candidateOutputRoot
        $dispatchArgs.CommonWriteDomains = @($candidateWriteDomain)
    }
    if ($Quiet) {
        $dispatchArgs.Quiet = $true
    }

    $dispatchStartedUtc = [DateTime]::UtcNow
    $dispatchOutput = @(& $publicDispatcher @dispatchArgs 2>&1)
    $poolExit = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    $resultBase.pool_exit_code = $poolExit
    $resultBase.dispatch_output_excerpt = (
        ($dispatchOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine
    )
    if ($resultBase.dispatch_output_excerpt.Length -gt 4000) {
        $resultBase.dispatch_output_excerpt = $resultBase.dispatch_output_excerpt.Substring(0, 4000)
    }

    $evidence = Find-XinaoLegADispatchEvidence `
        -Runtime $resolvedRuntimeRoot `
        -SelectionDecisionSha256 ([string]$selection.decision_sha256) `
        -SelectionPath ([string]$selection.selection_path) `
        -NotBeforeUtc $dispatchStartedUtc

    $poolSummary = $null
    $poolSummaryPath = ""
    $attemptPaths = New-Object System.Collections.Generic.List[string]
    $observedBackend = "linux-container"
    $observedEffect = if ($AuthorizedWrite) { "authorized_write" } else { "read_only" }
    $poolAccepted = $false

    if ($null -ne $evidence) {
        $poolSummaryPath = [string]$evidence.pool_summary_path
        if (
            [string]::IsNullOrWhiteSpace($poolSummaryPath) -and
            -not [string]::IsNullOrWhiteSpace([string]$evidence.pool_id)
        ) {
            $poolSummaryPath = Join-Path $resolvedRuntimeRoot (
                "state\grok_worker_pool\" + [string]$evidence.pool_id + "\pool_summary.json"
            )
        }
        if (-not [string]::IsNullOrWhiteSpace($poolSummaryPath) -and (Test-Path -LiteralPath $poolSummaryPath -PathType Leaf)) {
            try {
                $poolSummary = Get-Content -LiteralPath $poolSummaryPath -Raw -Encoding UTF8 |
                    ConvertFrom-Json -ErrorAction Stop
            }
            catch {
                $poolSummary = $null
            }
        }
        if ($null -ne $poolSummary) {
            if (-not [string]::IsNullOrWhiteSpace([string]$poolSummary.execution_backend)) {
                $observedBackend = [string]$poolSummary.execution_backend
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$poolSummary.effect_mode)) {
                $observedEffect = [string]$poolSummary.effect_mode
            }
            $poolAccepted = (
                $poolExit -eq 0 -and
                (
                    $poolSummary.all_ok -eq $true -or
                    $poolSummary.reuse_skipped_execution -eq $true
                ) -and
                $poolSummary.acceptance_contract_ok -eq $true
            )
            foreach ($item in @($poolSummary.results)) {
                $evDir = [string]$item.evidence_dir
                if (-not [string]::IsNullOrWhiteSpace($evDir)) {
                    $attemptPaths.Add($evDir)
                }
                $metaPath = [string]$item.meta_path
                if (-not [string]::IsNullOrWhiteSpace($metaPath)) {
                    $attemptPaths.Add($metaPath)
                }
            }
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$evidence.dispatch_meta_path)) {
            $attemptPaths.Add([string]$evidence.dispatch_meta_path)
        }
        if (-not [string]::IsNullOrWhiteSpace($poolSummaryPath)) {
            $attemptPaths.Add($poolSummaryPath)
        }
    }

    # Hard reject non-container or leg-B bleed even if pool returned ok.
    if (-not [string]::Equals($observedBackend, "linux-container", [StringComparison]::Ordinal)) {
        Throw-XinaoLegAPreflight "XINAO_LEG_A_BACKEND_REJECTED" "observed=$observedBackend (windows-host fallback forbidden)"
    }
    $expectedEffect = if ($AuthorizedWrite) { "authorized_write" } else { "read_only" }
    if (-not [string]::Equals($observedEffect, $expectedEffect, [StringComparison]::Ordinal)) {
        # If pool summary is missing after hard failure, keep expected mode in report.
        if ($null -ne $poolSummary) {
            Throw-XinaoLegAPreflight "XINAO_LEG_A_EFFECT_MODE_MISMATCH" "expected=$expectedEffect observed=$observedEffect"
        }
    }

    $resultBase.execution_backend = $observedBackend
    $resultBase.effect_mode = $expectedEffect
    $resultBase.evidence = [ordered]@{
        dispatch_meta_path = if ($null -ne $evidence) { [string]$evidence.dispatch_meta_path } else { "" }
        dispatch_id = if ($null -ne $evidence) { [string]$evidence.dispatch_id } else { "" }
        pool_id = if ($null -ne $evidence) { [string]$evidence.pool_id } else { "" }
        pool_summary_path = $poolSummaryPath
        attempt_evidence_paths = @($attemptPaths | Select-Object -Unique)
        local_state_dir = $localStateDir
        prompt_file = $resolvedPromptFile
        subject_manifest_path = $subjectManifestPath
        candidate_output_root = $candidateOutputRoot
        write_domains = if ($AuthorizedWrite) { @($candidateWriteDomain) } else { @() }
        docker_exe = $resolvedDocker
    }
    if ($null -ne $evidence -and $null -ne $evidence.dispatch_meta) {
        $resultBase.evidence.dispatch_status = [string]$evidence.dispatch_meta.status
        $resultBase.evidence.common_context_effect_status = [string]$evidence.dispatch_meta.common_context_effect_status
        $resultBase.evidence.common_model_input_effect_verified =
            $evidence.dispatch_meta.common_model_input_effect_verified -eq $true
    }
    if ($null -ne $poolSummary) {
        $resultBase.evidence.pool_all_ok = $poolSummary.all_ok -eq $true
        $resultBase.evidence.pool_acceptance_contract_ok = $poolSummary.acceptance_contract_ok -eq $true
        $resultBase.evidence.pool_reuse_skipped_execution = $poolSummary.reuse_skipped_execution -eq $true
        $resultBase.evidence.observed_execution_backend = $observedBackend
        $resultBase.evidence.observed_effect_mode = $observedEffect
    }

    $resultBase.ok = [bool]$poolAccepted
    $resultBase.status = if ($poolAccepted) { "accepted_candidate" } else { "rejected" }
    if (-not $poolAccepted -and [string]::IsNullOrWhiteSpace([string]$resultBase.error)) {
        $resultBase.error = if ($poolExit -ne 0) {
            "XINAO_LEG_A_POOL_EXIT_$poolExit"
        } else {
            "XINAO_LEG_A_POOL_NOT_ACCEPTED"
        }
    }

    Write-XinaoLegAResult -Payload $resultBase -ExitCode $(if ($poolAccepted) { 0 } else { 1 })
}
catch {
    $resultBase.ok = $false
    $resultBase.status = "blocked"
    $resultBase.error = [string]$_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($resultBase.error)) {
        $resultBase.error = [string]$_
    }
    $exitCode = 2
    if ($resultBase.error -match 'XINAO_LEG_A_(DOCKER|LINUX_ENGINE|CONTEXT|INVALID_WORKTREE|WRITE_SCOPE|CWD|PROMPT|RULES|MANIFEST|SPEC|PUBLIC_DISPATCHER|SELECTION|BACKEND|EFFECT)') {
        $exitCode = 3
    }
    Write-XinaoLegAResult -Payload $resultBase -ExitCode $exitCode
}
