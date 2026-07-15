[CmdletBinding()]
param(
    [ValidateSet('capability', 'smoke', 'core', 'deep', 'context', 'proactive', 'reuse')]
    [string]$Profile = 'smoke',
    [string]$Domain,
    [string]$CasePattern,
    [string]$FailedFrom,
    [ValidateRange(1, 16)]
    [int]$MaxConcurrency = 2,
    [ValidateRange(0, 2)]
    [int]$MaxErrorRetries = 1,
    [switch]$List,
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(Join-Path $HOME '.codex')
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$catalogPath = Join-Path $repoRoot 'evals\behavior_regression\catalog.json'
$catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
if ($catalog.schema_version -ne 'xinao.behavior_regression_catalog.v1') {
    throw "Behavior regression catalog version drift: $($catalog.schema_version)"
}
if ($List) {
    $catalog | ConvertTo-Json -Depth 10
    return
}
if ($Domain -and $Profile -notin @('context', 'smoke', 'core', 'deep')) {
    throw 'Domain filtering applies to context behavior cases only.'
}
if ($CasePattern -and $Profile -notin @('context', 'proactive')) {
    throw 'CasePattern is suite-specific; use it with -Profile context or proactive.'
}
if ($FailedFrom -and $Profile -notin @('context', 'proactive')) {
    throw 'FailedFrom is suite-specific; use it with -Profile context or proactive.'
}
if ($FailedFrom -and -not (Test-Path -LiteralPath $FailedFrom -PathType Leaf)) {
    throw "Previous Promptfoo result is missing: $FailedFrom"
}
if ($FailedFrom) {
    $failedDocument = Get-Content -LiteralPath $FailedFrom -Raw | ConvertFrom-Json
    $expectedDescription = if ($Profile -eq 'context') {
        'Context-first intent alignment without routine approval friction'
    } else {
        'Proactive mature-first and Grok-default worker regressions'
    }
    if ($failedDocument.config.description -ne $expectedDescription) {
        throw "FailedFrom belongs to a different behavior suite: $($failedDocument.config.description)"
    }
}

$promptfooRoot = Join-Path $RuntimeRoot 'tools\promptfoo'
$promptfoo = Join-Path $promptfooRoot 'node_modules\.bin\promptfoo.cmd'
$promptfooPackage = Join-Path $promptfooRoot 'node_modules\promptfoo\package.json'
if (-not (Test-Path -LiteralPath $promptfoo -PathType Leaf)) {
    throw "Pinned Promptfoo runtime is missing: $promptfoo"
}
if (-not (Test-Path -LiteralPath $promptfooPackage -PathType Leaf)) {
    throw "Promptfoo package manifest is missing: $promptfooPackage"
}
$resolvedPromptfooVersion = (Get-Content -LiteralPath $promptfooPackage -Raw |
    ConvertFrom-Json).version
if ($resolvedPromptfooVersion -ne '0.121.18') {
    throw "Promptfoo version drift: expected 0.121.18, got $resolvedPromptfooVersion"
}
if (-not (Test-Path -LiteralPath $CodexHome -PathType Container)) {
    throw "Canonical CODEX_HOME is missing: $CodexHome"
}

$codexShim = (Get-Command codex -ErrorAction Stop).Source
$codexPackage = Join-Path (Split-Path -Parent $codexShim) 'node_modules\@openai\codex'
$codexBinary = Get-ChildItem -LiteralPath $codexPackage -Filter 'codex.exe' -File -Recurse |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $codexBinary) {
    throw "Native Codex app-server binary is missing below: $codexPackage"
}

$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$resultRoot = Join-Path $RuntimeRoot 'state\human-capabilities\evals\behavior-regression'
$outputRoot = Join-Path $resultRoot $runId
$promptfooState = Join-Path $outputRoot 'promptfoo'
$promptfooLogs = Join-Path $promptfooState 'logs'
$promptfooCache = Join-Path $promptfooState 'cache'
$tempRoot = Join-Path $outputRoot 'tmp'
$summaryPath = Join-Path $outputRoot 'summary.json'
$startedAt = Get-Date
$needsThinWorkspace = $Profile -in @('core', 'deep', 'reuse')
$thinWorkspace = Join-Path $outputRoot 'thin-localization-workspace'

New-Item -ItemType Directory -Path @(
    $outputRoot,
    $promptfooState,
    $promptfooLogs,
    $promptfooCache,
    $tempRoot
) -Force | Out-Null

if ($needsThinWorkspace) {
    $thinTemplate = Join-Path $repoRoot 'evals\thin_localization\fixture_template'
    if (-not (Test-Path -LiteralPath $thinTemplate -PathType Container)) {
        throw "Thin-localization fixture template is missing: $thinTemplate"
    }
    Copy-Item -LiteralPath $thinTemplate -Destination $thinWorkspace -Recurse
    & git -C $thinWorkspace init --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize the thin-localization evidence workspace.' }
    & git -C $thinWorkspace add --all
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage the thin-localization baseline.' }
    & git -C $thinWorkspace -c user.name=xinao-eval -c user.email=xinao-eval@local `
        commit --quiet -m baseline
    if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the thin-localization baseline.' }
}

$environment = @{
    CODEX_HOME = (Resolve-Path -LiteralPath $CodexHome).Path
    CODEX_APP_SERVER_PATH = $codexBinary
    PROMPTFOO_CONFIG_DIR = $promptfooState
    PROMPTFOO_LOG_DIR = $promptfooLogs
    PROMPTFOO_CACHE_PATH = $promptfooCache
    PROMPTFOO_DISABLE_TELEMETRY = '1'
    PROMPTFOO_DISABLE_UPDATE = '1'
    PROMPTFOO_DISABLE_DEBUG_LOG = '1'
    PROMPTFOO_DISABLE_ERROR_LOG = '1'
    TSX_DISABLE_CACHE = '1'
    PYTHONDONTWRITEBYTECODE = '1'
    TEMP = $tempRoot
    TMP = $tempRoot
    PATH = [Environment]::GetEnvironmentVariable('PATH', 'Process')
}
if ($needsThinWorkspace) {
    $environment['XINAO_THIN_LOCALIZATION_WORKSPACE'] = $thinWorkspace
}
$previous = @{}
foreach ($name in $environment.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Get-PromptfooResultSummary {
    param(
        [Parameter(Mandatory)]
        [string]$SuiteId,
        [Parameter(Mandatory)]
        [string]$ResultPath,
        [Parameter(Mandatory)]
        [int]$ExitCode
    )

    if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
        return [ordered]@{
            suite = $SuiteId
            exit_code = $ExitCode
            result = $ResultPath
            successes = 0
            failures = 0
            errors = 1
            case_ids = @()
        }
    }
    $document = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    $stats = $document.results.stats
    $caseIds = @(
        $document.results.results | ForEach-Object {
            if ($_.vars.case_id) { $_.vars.case_id } else { $_.testCase.description }
        }
    )
    if ($caseIds.Count -eq 0) {
        return [ordered]@{
            suite = $SuiteId
            exit_code = 1
            result = $ResultPath
            successes = 0
            failures = 0
            errors = 1
            duration_ms = [int64]$stats.durationMs
            token_usage = $stats.tokenUsage
            case_ids = @()
            empty_selection = $true
        }
    }
    return [ordered]@{
        suite = $SuiteId
        exit_code = $ExitCode
        result = $ResultPath
        successes = [int]$stats.successes
        failures = [int]$stats.failures
        errors = [int]$stats.errors
        duration_ms = [int64]$stats.durationMs
        token_usage = $stats.tokenUsage
        case_ids = $caseIds
    }
}

function Invoke-PromptfooSuite {
    param(
        [Parameter(Mandatory)]
        [string]$SuiteId,
        [Parameter(Mandatory)]
        [string]$ConfigPath,
        [Parameter(Mandatory)]
        [string]$ResultPath,
        [ValidateRange(1, 16)]
        [int]$Concurrency = $MaxConcurrency,
        [string[]]$ExtraArguments = @()
    )

    $arguments = @(
        'eval',
        '--config', $ConfigPath,
        '--max-concurrency', $Concurrency,
        '--no-progress-bar',
        '--no-cache',
        '--output', $ResultPath
    ) + $ExtraArguments
    $consolePath = Join-Path $outputRoot "$SuiteId.console.log"
    $console = & $promptfoo @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $console | Set-Content -LiteralPath $consolePath -Encoding utf8NoBOM
    return Get-PromptfooResultSummary -SuiteId $SuiteId -ResultPath $ResultPath -ExitCode $exitCode
}

function Invoke-PromptfooSuiteWithErrorRetry {
    param(
        [Parameter(Mandatory)]
        [string]$SuiteId,
        [Parameter(Mandatory)]
        [string]$ConfigPath,
        [Parameter(Mandatory)]
        [string]$ResultPath,
        [string[]]$ExtraArguments = @()
    )

    $initial = Invoke-PromptfooSuite -SuiteId $SuiteId -ConfigPath $ConfigPath `
        -ResultPath $ResultPath -ExtraArguments $ExtraArguments
    if ($MaxErrorRetries -eq 0 -or $initial.errors -eq 0) {
        return $initial
    }

    $resolvedSuccesses = [int]$initial.successes
    $resolvedFailures = [int]$initial.failures
    $resolvedErrors = [int]$initial.errors
    $retryRuns = @()
    $previousResult = $ResultPath
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($ResultPath)
    $directory = Split-Path -Parent $ResultPath

    for ($attempt = 1; $attempt -le $MaxErrorRetries -and $resolvedErrors -gt 0; $attempt++) {
        $retryResult = Join-Path $directory "$baseName.error-retry-$attempt.json"
        $retryArguments = @($ExtraArguments) + @('--filter-errors-only', $previousResult)
        $retry = Invoke-PromptfooSuite -SuiteId "$SuiteId.error_retry_$attempt" `
            -ConfigPath $ConfigPath -ResultPath $retryResult -Concurrency 1 `
            -ExtraArguments $retryArguments
        $retryRuns += $retry
        $resolvedSuccesses += [int]$retry.successes
        $resolvedFailures += [int]$retry.failures
        $resolvedErrors = [Math]::Max(
            0,
            $resolvedErrors - [int]$retry.successes - [int]$retry.failures
        )
        $previousResult = $retryResult
    }

    $resolvedDocument = Get-Content -LiteralPath $initial.result -Raw | ConvertFrom-Json
    $resolvedRows = @($resolvedDocument.results.results)
    foreach ($retryRun in $retryRuns) {
        $retryDocument = Get-Content -LiteralPath $retryRun.result -Raw | ConvertFrom-Json
        foreach ($retryRow in @($retryDocument.results.results)) {
            $retryKey = if ($retryRow.vars.case_id) {
                $retryRow.vars.case_id
            } else {
                $retryRow.testCase.description
            }
            $matchingIndex = -1
            for ($index = 0; $index -lt $resolvedRows.Count; $index++) {
                $candidateKey = if ($resolvedRows[$index].vars.case_id) {
                    $resolvedRows[$index].vars.case_id
                } else {
                    $resolvedRows[$index].testCase.description
                }
                if ($candidateKey -eq $retryKey) {
                    $matchingIndex = $index
                    break
                }
            }
            if ($matchingIndex -lt 0) {
                throw "Error retry returned an unexpected case: $retryKey"
            }
            $resolvedRows[$matchingIndex] = $retryRow
        }
    }

    $resolvedSuccesses = @($resolvedRows | Where-Object { $_.success -eq $true }).Count
    $resolvedErrors = @($resolvedRows | Where-Object { $_.failureReason -eq 2 }).Count
    $resolvedFailures = $resolvedRows.Count - $resolvedSuccesses - $resolvedErrors
    $resolvedDocument.results.results = $resolvedRows
    $resolvedDocument.results.stats.successes = $resolvedSuccesses
    $resolvedDocument.results.stats.failures = $resolvedFailures
    $resolvedDocument.results.stats.errors = $resolvedErrors
    $resolvedDocument.results.stats.durationMs = [int64]$initial.duration_ms + [int64](
        ($retryRuns | ForEach-Object { [int64]$_.duration_ms } | Measure-Object -Sum).Sum
    )
    $resolution = [ordered]@{
        schema_version = 'xinao.promptfoo_error_resolution.v1'
        initial_result = $initial.result
        retry_results = @($retryRuns | ForEach-Object { $_.result })
        retry_count = $retryRuns.Count
        terminal_counts_authority = 'resolved_result_rows'
    }
    $resolvedDocument | Add-Member -NotePropertyName xinao_resolution `
        -NotePropertyValue $resolution -Force
    $resolvedPath = Join-Path $directory "$baseName.resolved.json"
    $resolvedDocument | ConvertTo-Json -Depth 100 |
        Set-Content -LiteralPath $resolvedPath -Encoding utf8NoBOM
    $terminalExit = if ($resolvedFailures -eq 0 -and $resolvedErrors -eq 0) { 0 } else { 100 }
    $terminal = Get-PromptfooResultSummary -SuiteId $initial.suite `
        -ResultPath $resolvedPath -ExitCode $terminalExit
    $terminal['initial_result'] = $initial.result
    $terminal['error_retry_count'] = $retryRuns.Count
    $terminal['error_retry_results'] = @($retryRuns | ForEach-Object { $_.result })
    $terminal['error_retry_runs'] = $retryRuns
    $terminal['terminal_counts_authority'] = 'resolved_result_rows'
    return $terminal
}

function New-BehaviorSourceManifest {
    param(
        [Parameter(Mandatory)]
        [object[]]$Inputs,
        [Parameter(Mandatory)]
        [string]$OutputPath
    )

    $repoPrefix = $repoRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $byPath = @{}
    foreach ($inputItem in $Inputs) {
        $resolved = (Resolve-Path -LiteralPath $inputItem.path -ErrorAction Stop).Path
        $files = if (Test-Path -LiteralPath $resolved -PathType Container) {
            Get-ChildItem -LiteralPath $resolved -File -Recurse -Force |
                Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' }
        }
        else {
            Get-Item -LiteralPath $resolved -Force
        }
        foreach ($file in $files) {
            $fullPath = $file.FullName
            $logicalPath = if ($fullPath.StartsWith(
                    $repoPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                )) {
                [IO.Path]::GetRelativePath($repoRoot, $fullPath).Replace('\', '/')
            }
            else {
                $fullPath.Replace('\', '/')
            }
            $byPath[$logicalPath] = [ordered]@{
                path = $logicalPath
                role = $inputItem.role
                size_bytes = [int64]$file.Length
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fullPath).Hash.ToLowerInvariant()
            }
        }
    }
    $document = [ordered]@{
        schema_version = 'xinao.behavior_regression_source_manifest.v1'
        profile = $Profile
        files = @($byPath.Values | Sort-Object { $_.path })
    }
    $json = $document | ConvertTo-Json -Depth 6 -Compress
    [IO.File]::WriteAllText($OutputPath, $json, [Text.UTF8Encoding]::new($false))
    return [pscustomobject]@{
        path = $OutputPath
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
        files = $document.files
    }
}

$runCapability = $Profile -in @('capability', 'smoke', 'core', 'deep') -and
    -not $Domain -and -not $CasePattern -and -not $FailedFrom
$runContext = $Profile -in @('context', 'smoke', 'core', 'deep')
$runProactive = $Profile -in @('proactive', 'core', 'deep')
$runRecallReplay = $Profile -in @('core', 'deep', 'reuse')
$runRecallLive = $Profile -in @('deep', 'reuse')
$runThinLocalization = $Profile -in @('core', 'deep', 'reuse')
$runStatic = $Profile -in @('core', 'deep', 'reuse') -and -not $FailedFrom
$sourceInputs = @(
    [pscustomobject]@{ path = (Join-Path $repoRoot 'AGENTS.md'); role = 'working_agreement' },
    [pscustomobject]@{ path = (Join-Path $repoRoot 'pyproject.toml'); role = 'python_runtime_contract' },
    [pscustomobject]@{ path = (Join-Path $repoRoot 'uv.lock'); role = 'python_runtime_lock' },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'scripts\run_behavior_regression.ps1')
        role = 'runner'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\behavior_regression\catalog.json')
        role = 'catalog'
    }
)
if ($runStatic) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_open_world_reuse_behavior.py')
        role = 'static_assertion_tests'
    }
}
if ($runStatic -and $Profile -in @('core', 'deep')) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_repo_safety.py')
        role = 'repository_safety_tests'
    }
}
if ($runCapability) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\codex_capability')
        role = 'capability_eval'
    }
}
if ($runContext) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\context_intent_alignment')
        role = 'context_eval'
    }
}
if ($runProactive) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\proactive_mature_first')
        role = 'proactive_eval'
    }
}
if ($runRecallReplay -or $runRecallLive) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\mature_capability_recall')
        role = 'mature_capability_recall_eval'
    }
}
if ($runRecallLive) {
    $sourceInputs += [pscustomobject]@{
        path = 'E:\XINAO_EXTERNAL_MATURE\codex_20260627\manifests\github_external_mature_all_repos.json'
        role = 'live_discovery_cache'
    }
}
if ($runThinLocalization) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\thin_localization')
        role = 'thin_localization_eval'
    }
}
$sourceManifestPath = Join-Path $outputRoot 'source-manifest.json'
$sourceManifestFinalPath = Join-Path $outputRoot 'source-manifest.final.json'
$sourceManifest = New-BehaviorSourceManifest -Inputs $sourceInputs -OutputPath $sourceManifestPath
$suiteRuns = @()
$staticResult = [ordered]@{ ran = $false; exit_code = 0; log = $null }
$overallExit = 0
$infrastructureError = $null

try {
    foreach ($name in $environment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process')
    }

    if ($runStatic) {
        $staticResult.ran = $true
        $staticResult.log = Join-Path $outputRoot 'static-validation.log'
        $staticTests = @('tests/test_open_world_reuse_behavior.py')
        if ($Profile -in @('core', 'deep')) {
            $staticTests = @('tests/test_repo_safety.py') + $staticTests
        }
        $staticConsole = & uv run pytest @staticTests -q 2>&1
        $staticResult.exit_code = $LASTEXITCODE
        $staticConsole | Set-Content -LiteralPath $staticResult.log -Encoding utf8NoBOM
        if ($staticResult.exit_code -ne 0) {
            $overallExit = 1
        }
    }

    if ($overallExit -eq 0 -and $runCapability) {
        $capabilityConfig = Join-Path $repoRoot 'evals\codex_capability\promptfooconfig.yaml'
        $capabilityResult = Join-Path $outputRoot 'codex-capability.result.json'
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry -SuiteId 'codex_capability' `
            -ConfigPath $capabilityConfig -ResultPath $capabilityResult
    }

    if ($overallExit -eq 0 -and $runContext) {
        $contextConfig = Join-Path $repoRoot 'evals\context_intent_alignment\promptfooconfig.yaml'
        $contextResult = Join-Path $outputRoot 'context-intent-alignment.result.json'
        $filters = @()
        if ($Profile -in @('smoke', 'core', 'deep')) {
            $filters += @('--filter-metadata', "profiles=$Profile")
        }
        if ($Domain) {
            $filters += @('--filter-metadata', "domain=$Domain")
        }
        if ($CasePattern) {
            $filters += @('--filter-pattern', $CasePattern)
        }
        if ($FailedFrom) {
            $filters += @('--filter-failing', (Resolve-Path -LiteralPath $FailedFrom).Path)
        }
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry -SuiteId 'context_intent_alignment' `
            -ConfigPath $contextConfig -ResultPath $contextResult -ExtraArguments $filters
    }

    if ($overallExit -eq 0 -and $runProactive) {
        $proactiveConfig = Join-Path $repoRoot 'evals\proactive_mature_first\promptfooconfig.yaml'
        $proactiveResult = Join-Path $outputRoot 'proactive-mature-first.result.json'
        $proactiveFilters = @()
        if ($FailedFrom) {
            $proactiveFilters += @('--filter-failing', (Resolve-Path -LiteralPath $FailedFrom).Path)
        }
        if ($CasePattern) {
            $proactiveFilters += @('--filter-pattern', $CasePattern)
        }
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry -SuiteId 'proactive_mature_first' `
            -ConfigPath $proactiveConfig -ResultPath $proactiveResult -ExtraArguments $proactiveFilters
    }

    if ($overallExit -eq 0 -and $runRecallReplay) {
        $recallReplayConfig = Join-Path $repoRoot `
            'evals\mature_capability_recall\promptfooconfig.yaml'
        $recallReplayResult = Join-Path $outputRoot 'mature-capability-recall-replay.result.json'
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry `
            -SuiteId 'mature_capability_recall_replay' `
            -ConfigPath $recallReplayConfig -ResultPath $recallReplayResult
    }

    if ($overallExit -eq 0 -and $runThinLocalization) {
        $thinConfig = Join-Path $repoRoot 'evals\thin_localization\promptfooconfig.yaml'
        $thinResult = Join-Path $outputRoot 'thin-localization-live.result.json'
        # Retrying a mutation trajectory against its already-mutated fixture would invalidate order.
        $suiteRuns += Invoke-PromptfooSuite -SuiteId 'thin_localization_live' `
            -ConfigPath $thinConfig -ResultPath $thinResult -Concurrency 1
    }

    if ($overallExit -eq 0 -and $runRecallLive) {
        $recallLiveConfig = Join-Path $repoRoot `
            'evals\mature_capability_recall\promptfooconfig.live.yaml'
        $recallLiveResult = Join-Path $outputRoot 'mature-capability-recall-live.result.json'
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry `
            -SuiteId 'mature_capability_recall_live' `
            -ConfigPath $recallLiveConfig -ResultPath $recallLiveResult
    }

    foreach ($suite in $suiteRuns) {
        if ($suite.exit_code -eq 100 -and $overallExit -eq 0) {
            $overallExit = 100
        }
        elseif ($suite.exit_code -ne 0 -and $suite.exit_code -ne 100) {
            $overallExit = 1
        }
    }
}
catch {
    $infrastructureError = $_.Exception.Message
    $overallExit = 1
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}

$sourceManifestFinal = $null
$sourceManifestUnchanged = $false
$sourceManifestDrift = @()
try {
    $sourceManifestFinal = New-BehaviorSourceManifest `
        -Inputs $sourceInputs `
        -OutputPath $sourceManifestFinalPath
    $sourceManifestUnchanged = $sourceManifest.sha256 -eq $sourceManifestFinal.sha256
    if (-not $sourceManifestUnchanged) {
        $before = @{}
        $after = @{}
        foreach ($row in $sourceManifest.files) { $before[$row.path] = $row }
        foreach ($row in $sourceManifestFinal.files) { $after[$row.path] = $row }
        $allPaths = @($before.Keys) + @($after.Keys) | Sort-Object -Unique
        $sourceManifestDrift = @(
            foreach ($path in $allPaths) {
                if (-not $before.ContainsKey($path)) { "added:$path"; continue }
                if (-not $after.ContainsKey($path)) { "removed:$path"; continue }
                if (
                    $before[$path].size_bytes -ne $after[$path].size_bytes -or
                    $before[$path].sha256 -ne $after[$path].sha256
                ) { "changed:$path" }
            }
        )
        $overallExit = 1
        if (-not $infrastructureError) {
            $infrastructureError = 'Behavior regression sources changed during the run.'
        }
    }
}
catch {
    $overallExit = 1
    $sourceManifestDrift = @("manifest_error:$($_.Exception.Message)")
    if (-not $infrastructureError) {
        $infrastructureError = 'Could not verify behavior regression source stability.'
    }
}

$totals = [ordered]@{
    successes = [int](($suiteRuns | ForEach-Object { [int]$_.successes } | Measure-Object -Sum).Sum)
    failures = [int](($suiteRuns | ForEach-Object { [int]$_.failures } | Measure-Object -Sum).Sum)
    errors = [int](($suiteRuns | ForEach-Object { [int]$_.errors } | Measure-Object -Sum).Sum)
}
$gitSha = (& git -C $repoRoot rev-parse HEAD 2>$null).Trim()
$gitStatus = @(& git -C $repoRoot status --porcelain=v1 2>$null)
$summary = [ordered]@{
    schema_version = 'xinao.behavior_regression_run.v1'
    run_id = $runId
    profile = $Profile
    domain = $Domain
    case_pattern = $CasePattern
    failed_from = $FailedFrom
    started_at = $startedAt.ToString('o')
    finished_at = (Get-Date).ToString('o')
    git_sha = $gitSha
    git_dirty = ($gitStatus.Count -gt 0)
    uncommitted_files_count = $gitStatus.Count
    promptfoo_version = $resolvedPromptfooVersion
    max_concurrency = $MaxConcurrency
    max_error_retries = $MaxErrorRetries
    thin_localization_workspace = $(if ($needsThinWorkspace) { $thinWorkspace } else { $null })
    catalog = $catalogPath
    output_root = $outputRoot
    source_manifest = $sourceManifestPath
    source_manifest_sha256 = $sourceManifest.sha256
    source_manifest_final = $sourceManifestFinalPath
    source_manifest_final_sha256 = $sourceManifestFinal.sha256
    source_manifest_unchanged = $sourceManifestUnchanged
    source_manifest_drift = $sourceManifestDrift
    static_validation = $staticResult
    suites = $suiteRuns
    totals = $totals
    exit_code = $overallExit
    infrastructure_error = $infrastructureError
    not_authority = $true
}
$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding utf8NoBOM
$latest = [ordered]@{
    schema_version = 'xinao.behavior_regression_latest.v1'
    run_id = $runId
    summary = $summaryPath
    profile = $Profile
    exit_code = $overallExit
    finished_at = $summary.finished_at
}
New-Item -ItemType Directory -Path $resultRoot -Force | Out-Null
$latest | ConvertTo-Json -Depth 4 |
    Set-Content -LiteralPath (Join-Path $resultRoot 'latest.json') -Encoding utf8NoBOM

Write-Output $summaryPath
exit $overallExit
