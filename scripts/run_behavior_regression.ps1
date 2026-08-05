[CmdletBinding()]
param(
    [ValidateSet('capability', 'smoke', 'core', 'deep', 'proactive', 'reuse', 'intent')]
    [string]$Profile = 'smoke',
    [string]$Domain,
    [string]$CasePattern,
    [string]$FailedFrom,
    [ValidateRange(1, 16)]
    [int]$MaxConcurrency = 2,
    [ValidateRange(0, 2)]
    [int]$MaxErrorRetries = 1,
    [switch]$PreflightOnly,
    [switch]$List,
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' })
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
if ($Domain -and $Profile -notin @('proactive', 'core', 'deep')) {
    throw 'Domain filtering applies to proactive behavior cases only.'
}
if ($CasePattern -and $Profile -notin @('proactive', 'intent')) {
    throw 'CasePattern is suite-specific; use it with -Profile proactive or intent.'
}
if ($FailedFrom -and $Profile -ne 'proactive') {
    throw 'FailedFrom is suite-specific; use it with -Profile proactive.'
}
if ($FailedFrom -and $CasePattern) {
    throw 'FailedFrom cannot be combined with CasePattern.'
}
if ($FailedFrom -and -not (Test-Path -LiteralPath $FailedFrom -PathType Leaf)) {
    throw "Previous Promptfoo result is missing: $FailedFrom"
}
$failedSelection = $null

function ConvertTo-PromptfooRegexLiteral {
    param([Parameter(Mandatory)][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '[\r\n]') {
        throw 'FailedFrom case descriptions must be non-empty single lines.'
    }
    return [regex]::Replace(
        $Value,
        '([\\.^$|?*+()\[\]{}])',
        '\$1'
    )
}

function Get-PromptfooRowCaseId {
    param([Parameter(Mandatory)][object]$Row)

    foreach ($candidate in @(
            $Row.vars.case_id,
            $Row.testCase.vars.case_id,
            $Row.testCase.metadata.id,
            $Row.testCase.description,
            $Row.description
        )) {
        if (-not [string]::IsNullOrWhiteSpace([string]$candidate)) {
            return [string]$candidate
        }
    }
    throw 'Promptfoo result row has no stable case identity.'
}

function Get-FailedCaseSelection {
    param(
        [Parameter(Mandatory)][object]$Document,
        [string]$RequiredDomain
    )

    $failedRows = @($Document.results.results | Where-Object { $_.success -ne $true })
    if ($RequiredDomain) {
        $failedRows = @(
            $failedRows | Where-Object {
                $rowDomain = if ($_.vars.domain) {
                    $_.vars.domain
                }
                elseif ($_.testCase.vars.domain) {
                    $_.testCase.vars.domain
                }
                else {
                    $_.testCase.metadata.domain
                }
                $rowDomain -eq $RequiredDomain
            }
        )
    }
    if ($failedRows.Count -eq 0) {
        throw 'FailedFrom contains no failing cases for the requested selection.'
    }

    $entries = @(
        foreach ($row in $failedRows) {
            $description = if ($row.testCase.description) {
                [string]$row.testCase.description
            }
            else {
                [string]$row.description
            }
            [pscustomobject]@{
                case_id = Get-PromptfooRowCaseId -Row $row
                description = $description
                escaped = ConvertTo-PromptfooRegexLiteral -Value $description
            }
        }
    )
    $duplicateIds = @($entries | Group-Object case_id | Where-Object { $_.Count -ne 1 })
    $duplicateDescriptions = @(
        $entries | Group-Object description | Where-Object { $_.Count -ne 1 }
    )
    if ($duplicateIds.Count -gt 0 -or $duplicateDescriptions.Count -gt 0) {
        throw 'FailedFrom case identities and descriptions must be unique.'
    }
    $parts = @($entries | ForEach-Object { $_.escaped })
    return [pscustomobject]@{
        case_ids = @($entries | ForEach-Object { $_.case_id })
        descriptions = @($entries | ForEach-Object { $_.description })
        pattern = '^(?:' + ($parts -join '|') + ')$'
    }
}

function Assert-FailedCaseSelection {
    param(
        [Parameter(Mandatory)][object]$ActualSummary,
        [Parameter(Mandatory)][string[]]$ExpectedCaseIds
    )

    $actual = @($ActualSummary.case_ids | ForEach-Object { [string]$_ } | Sort-Object)
    $expected = @($ExpectedCaseIds | ForEach-Object { [string]$_ } | Sort-Object)
    if (($actual -join "`n") -ne ($expected -join "`n")) {
        throw "Current-case selection mismatch: expected [$($expected -join ', ')], actual [$($actual -join ', ')]"
    }
}

if ($FailedFrom) {
    $failedDocument = Get-Content -LiteralPath $FailedFrom -Raw | ConvertFrom-Json
    $expectedDescription = switch ($Profile) {
        'proactive' { 'Proactive mature-first regressions' }
        default { throw "FailedFrom is not supported for profile: $Profile" }
    }
    if ($failedDocument.config.description -ne $expectedDescription) {
        throw "FailedFrom belongs to a different behavior suite: $($failedDocument.config.description)"
    }
    $failedSelection = Get-FailedCaseSelection -Document $failedDocument -RequiredDomain $Domain
}

$promptfooRoot = Join-Path $RuntimeRoot 'tools\promptfoo'
$promptfooPackageRoot = Join-Path $promptfooRoot 'node_modules\promptfoo'
$promptfooPackage = Join-Path $promptfooPackageRoot 'package.json'
if (-not (Test-Path -LiteralPath $promptfooPackage -PathType Leaf)) {
    throw "Promptfoo package manifest is missing: $promptfooPackage"
}
$promptfooManifest = Get-Content -LiteralPath $promptfooPackage -Raw | ConvertFrom-Json
$resolvedPromptfooVersion = $promptfooManifest.version
if ($resolvedPromptfooVersion -ne '0.121.18') {
    throw "Promptfoo version drift: expected 0.121.18, got $resolvedPromptfooVersion"
}
$promptfooBinRelative = [string]$promptfooManifest.bin.promptfoo
if ([string]::IsNullOrWhiteSpace($promptfooBinRelative)) {
    throw "Promptfoo package manifest does not declare bin.promptfoo: $promptfooPackage"
}
$promptfooEntrypoint = Join-Path $promptfooPackageRoot $promptfooBinRelative
if (-not (Test-Path -LiteralPath $promptfooEntrypoint -PathType Leaf)) {
    throw "Pinned Promptfoo entrypoint is missing: $promptfooEntrypoint"
}
$node = (Get-Command node -ErrorAction Stop).Source
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

$runId = '{0}-{1}-{2}' -f `
    (Get-Date -Format 'yyyyMMdd-HHmmss-fff'), `
    $PID, `
    ([Guid]::NewGuid().ToString('N').Substring(0, 8))
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

New-Item -ItemType Directory -Path $outputRoot -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path @(
    $promptfooState,
    $promptfooLogs,
    $promptfooCache,
    $tempRoot
) -Force | Out-Null

$snapshotBuilder = Join-Path $repoRoot 'scripts\prepare_behavior_regression_snapshot.py'
if (-not (Test-Path -LiteralPath $snapshotBuilder -PathType Leaf)) {
    throw "Behavior snapshot builder is missing: $snapshotBuilder"
}
$snapshotArguments = @(
    'run', 'python', $snapshotBuilder,
    '--repo-root', $repoRoot,
    '--output-root', $outputRoot,
    '--profile', $Profile,
    '--codex-home', $CodexHome
)
if ($Domain) { $snapshotArguments += @('--domain', $Domain) }
if ($CasePattern) { $snapshotArguments += @('--case-pattern', $CasePattern) }
if ($FailedFrom) { $snapshotArguments += @('--failed-from', $FailedFrom) }
$snapshotConsole = & uv @snapshotArguments 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Behavior source snapshot failed: $($snapshotConsole -join [Environment]::NewLine)"
}
$sourceSnapshotPath = [string]($snapshotConsole | Select-Object -Last 1)
if (-not (Test-Path -LiteralPath $sourceSnapshotPath -PathType Leaf)) {
    throw "Behavior source snapshot manifest is missing: $sourceSnapshotPath"
}
$sourceSnapshot = Get-Content -LiteralPath $sourceSnapshotPath -Raw | ConvertFrom-Json
if ($sourceSnapshot.schema_version -ne 'xinao.behavior_regression_source_snapshot.v1') {
    throw "Behavior source snapshot version drift: $($sourceSnapshot.schema_version)"
}
$executionRoot = [string]$sourceSnapshot.effective_root
$rawSnapshotRoot = [string]$sourceSnapshot.raw_root
$catalogPath = Join-Path $executionRoot 'evals\behavior_regression\catalog.json'
$catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json

if ($needsThinWorkspace) {
    $thinTemplate = Join-Path $executionRoot 'evals\thin_localization\fixture_template'
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
            model_outputs_observed = 0
            runtime_pass_claim_eligible = $false
            runtime_claim_denial_reasons = @('missing_result', 'zero_model_output')
        }
    }
    $document = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    $stats = $document.results.stats
    $caseIds = @(
        $document.results.results | ForEach-Object {
            Get-PromptfooRowCaseId -Row $_
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
            model_outputs_observed = 0
            runtime_pass_claim_eligible = $false
            runtime_claim_denial_reasons = @('empty_selection', 'zero_model_output')
        }
    }
    $rows = @($document.results.results)
    $modelOutputsObserved = @(
        $rows | Where-Object {
            $candidate = $_.response.output
            if ($null -eq $candidate) { $false }
            elseif ($candidate -is [string]) { -not [string]::IsNullOrWhiteSpace($candidate) }
            else { $true }
        }
    ).Count
    $runtimeClaimDenials = @()
    if ($ExitCode -ne 0) { $runtimeClaimDenials += "nonzero_exit:$ExitCode" }
    if ([int]$stats.failures -gt 0) { $runtimeClaimDenials += 'failed_rows' }
    if ([int]$stats.errors -gt 0) { $runtimeClaimDenials += 'error_rows' }
    if ([int]$stats.successes -le 0) { $runtimeClaimDenials += 'no_successful_rows' }
    if ($modelOutputsObserved -eq 0) { $runtimeClaimDenials += 'zero_model_output' }
    if ($modelOutputsObserved -lt [int]$stats.successes) {
        $runtimeClaimDenials += 'successful_row_without_model_output'
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
        model_outputs_observed = $modelOutputsObserved
        runtime_pass_claim_eligible = ($runtimeClaimDenials.Count -eq 0)
        runtime_claim_denial_reasons = @($runtimeClaimDenials)
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
    # Invoke the pinned JavaScript entrypoint directly. On Windows, forwarding a regex
    # containing `|` through promptfoo.cmd lets cmd.exe reinterpret it as a shell pipe.
    $console = & $node $promptfooEntrypoint @arguments 2>&1
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
        [string[]]$ExtraArguments = @(),
        [string[]]$ExpectedCaseIds = @()
    )

    $initial = Invoke-PromptfooSuite -SuiteId $SuiteId -ConfigPath $ConfigPath `
        -ResultPath $ResultPath -ExtraArguments $ExtraArguments
    if ($ExpectedCaseIds.Count -gt 0) {
        Assert-FailedCaseSelection -ActualSummary $initial -ExpectedCaseIds $ExpectedCaseIds
    }
    if (
        $MaxErrorRetries -eq 0 -or
        $initial.errors -eq 0 -or
        $initial.empty_selection
    ) {
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
            $retryKey = Get-PromptfooRowCaseId -Row $retryRow
            $matchingIndex = -1
            for ($index = 0; $index -lt $resolvedRows.Count; $index++) {
                $candidateKey = Get-PromptfooRowCaseId -Row $resolvedRows[$index]
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
    if ($ExpectedCaseIds.Count -gt 0) {
        Assert-FailedCaseSelection -ActualSummary $terminal -ExpectedCaseIds $ExpectedCaseIds
    }
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
            $declaredLogicalPath = [string]$inputItem.logical_path
            $logicalPath = if (-not [string]::IsNullOrWhiteSpace($declaredLogicalPath)) {
                $base = $declaredLogicalPath.Replace('\', '/').TrimEnd('/')
                if (Test-Path -LiteralPath $resolved -PathType Container) {
                    $inside = [IO.Path]::GetRelativePath($resolved, $fullPath).Replace('\', '/')
                    "$base/$inside"
                }
                else {
                    $base
                }
            }
            elseif ($fullPath.StartsWith(
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
$runIntent = $Profile -in @('intent', 'smoke', 'core', 'deep')
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
        path = (Join-Path $repoRoot 'scripts\prepare_behavior_regression_snapshot.py')
        role = 'snapshot_builder'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'scripts\select_behavior_regression_incremental.py')
        role = 'incremental_selector'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_behavior_regression_snapshot.py')
        role = 'snapshot_builder_tests'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_behavior_regression_incremental.py')
        role = 'incremental_selector_tests'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\behavior_regression\catalog.json')
        role = 'catalog'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\intent_continuity_baseline\decision_model.v1.json')
        role = 'intent_continuity_baseline'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\intent_continuity_baseline\consumer_coverage.v1.json')
        role = 'intent_action_consumer_coverage'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\intent_continuity_baseline\BASELINE.md')
        role = 'intent_action_baseline_documentation'
    },
    [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_intent_action_consumer_coverage.py')
        role = 'intent_action_coverage_tests'
    }
)
if ($runStatic) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_open_world_reuse_behavior.py')
        role = 'static_assertion_tests'
    }
}
if ($runIntent) {
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'tests\test_parent_frame_admission.py')
        role = 'parent_frame_admission_tests'
    }
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $repoRoot 'evals\parent_frame_admission')
        role = 'parent_frame_admission'
    }
    $sourceInputs += [pscustomobject]@{
        path = (Join-Path $CodexHome 'AGENTS.md')
        logical_path = 'external/global_codex_home/AGENTS.md'
        role = 'global_working_kernel'
    }
}
if ($runProactive) {
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
$liveSourceManifestPath = Join-Path $outputRoot 'live-source-manifest.before.json'
$liveSourceManifestFinalPath = Join-Path $outputRoot 'live-source-manifest.after.json'
$liveSourceManifest = New-BehaviorSourceManifest `
    -Inputs $sourceInputs `
    -OutputPath $liveSourceManifestPath
$runtimeSourceInputs = @(
    foreach ($row in $sourceSnapshot.source_inputs) {
        [pscustomobject]@{
            path = [string]$row.snapshot_path
            role = [string]$row.role
            logical_path = [string]$row.logical_path
        }
    }
)
$sourceManifest = New-BehaviorSourceManifest `
    -Inputs $runtimeSourceInputs `
    -OutputPath $sourceManifestPath
$suiteRuns = @()
$preflightResult = [ordered]@{ ran = $false; exit_code = 0; log = $null; tests = @() }
$staticResult = [ordered]@{ ran = $false; exit_code = 0; log = $null }
$overallExit = 0
$infrastructureError = $null

try {
    foreach ($name in $environment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process')
    }

    $preflightResult.ran = $true
    $preflightResult.log = Join-Path $outputRoot 'preflight-validation.log'
    $preflightTests = @(
        'tests/test_behavior_regression_snapshot.py',
        'tests/test_behavior_regression_incremental.py'
    )
    if ($runProactive) {
        $preflightTests += 'tests/test_repo_safety.py'
    }
    if ($runIntent) {
        $preflightTests += 'tests/test_parent_frame_admission.py'
        $preflightTests += 'tests/test_intent_action_consumer_coverage.py'
    }
    $preflightResult.tests = $preflightTests
    Push-Location $rawSnapshotRoot
    try {
        $preflightConsole = & uv run --project $repoRoot --extra dev --extra workflow `
            pytest @preflightTests -q 2>&1
        $preflightResult.exit_code = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    $preflightConsole | Set-Content -LiteralPath $preflightResult.log -Encoding utf8NoBOM
    if ($preflightResult.exit_code -ne 0) {
        $overallExit = 1
        $infrastructureError = 'Behavior regression deterministic preflight failed; no model call was made.'
    }

    if ($overallExit -eq 0 -and $runStatic -and -not $PreflightOnly) {
        $staticResult.ran = $true
        $staticResult.log = Join-Path $outputRoot 'static-validation.log'
        $staticTests = @('tests/test_open_world_reuse_behavior.py')
        Push-Location $rawSnapshotRoot
        try {
            $staticConsole = & uv run --project $repoRoot --extra dev --extra workflow `
                pytest @staticTests -q 2>&1
            $staticResult.exit_code = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
        $staticConsole | Set-Content -LiteralPath $staticResult.log -Encoding utf8NoBOM
        if ($staticResult.exit_code -ne 0) {
            $overallExit = 1
        }
    }

    if ($overallExit -eq 0 -and $runIntent -and -not $PreflightOnly) {
        $intentConfig = Join-Path $executionRoot `
            'evals\parent_frame_admission\promptfooconfig.yaml'
        $intentResult = Join-Path $outputRoot 'parent-frame-admission.result.json'
        $intentFilters = @()
        if ($Profile -eq 'smoke') {
            $intentFilters += @(
                '--filter-pattern',
                '^Contextual distress remains in the active repair$'
            )
        }
        if ($Profile -eq 'intent' -and $CasePattern) {
            $intentFilters += @('--filter-pattern', $CasePattern)
        }
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry `
            -SuiteId 'parent_frame_admission' `
            -ConfigPath $intentConfig -ResultPath $intentResult `
            -ExtraArguments $intentFilters
    }

    if ($overallExit -eq 0 -and $runCapability -and -not $PreflightOnly) {
        $capabilityConfig = Join-Path $executionRoot 'evals\codex_capability\promptfooconfig.yaml'
        $capabilityResult = Join-Path $outputRoot 'codex-capability.result.json'
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry -SuiteId 'codex_capability' `
            -ConfigPath $capabilityConfig -ResultPath $capabilityResult
    }

    if ($overallExit -eq 0 -and $runProactive -and -not $PreflightOnly) {
        $proactiveConfig = Join-Path $executionRoot 'evals\proactive_mature_first\promptfooconfig.yaml'
        $proactiveResult = Join-Path $outputRoot 'proactive-mature-first.result.json'
        $proactiveFilters = @()
        if ($FailedFrom) {
            $proactiveFilters += @('--filter-pattern', $failedSelection.pattern)
        }
        if ($CasePattern) {
            $proactiveFilters += @('--filter-pattern', $CasePattern)
        }
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry -SuiteId 'proactive_mature_first' `
            -ConfigPath $proactiveConfig -ResultPath $proactiveResult `
            -ExtraArguments $proactiveFilters `
            -ExpectedCaseIds $(if ($FailedFrom) { $failedSelection.case_ids } else { @() })
    }

    if ($overallExit -eq 0 -and $runRecallReplay -and -not $PreflightOnly) {
        $recallReplayConfig = Join-Path $executionRoot `
            'evals\mature_capability_recall\promptfooconfig.yaml'
        $recallReplayResult = Join-Path $outputRoot 'mature-capability-recall-replay.result.json'
        $suiteRuns += Invoke-PromptfooSuiteWithErrorRetry `
            -SuiteId 'mature_capability_recall_replay' `
            -ConfigPath $recallReplayConfig -ResultPath $recallReplayResult
    }

    if ($overallExit -eq 0 -and $runThinLocalization -and -not $PreflightOnly) {
        $thinConfig = Join-Path $executionRoot 'evals\thin_localization\promptfooconfig.yaml'
        $thinResult = Join-Path $outputRoot 'thin-localization-live.result.json'
        # Retrying a mutation trajectory against its already-mutated fixture would invalidate order.
        $suiteRuns += Invoke-PromptfooSuite -SuiteId 'thin_localization_live' `
            -ConfigPath $thinConfig -ResultPath $thinResult -Concurrency 1
    }

    if ($overallExit -eq 0 -and $runRecallLive -and -not $PreflightOnly) {
        $recallLiveConfig = Join-Path $executionRoot `
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
        elseif ($suite.result -and $suite.runtime_pass_claim_eligible -ne $true) {
            $overallExit = 1
            if (-not $infrastructureError) {
                $infrastructureError = "Suite $($suite.suite) has no claim-eligible model trajectory."
            }
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
        -Inputs $runtimeSourceInputs `
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
            $infrastructureError = 'Frozen behavior regression snapshot changed during the run.'
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

$liveSourceManifestFinal = $null
$liveSourceManifestUnchanged = $false
$liveSourceManifestDrift = @()
$liveSourceManifestError = $null
try {
    $liveSourceManifestFinal = New-BehaviorSourceManifest `
        -Inputs $sourceInputs `
        -OutputPath $liveSourceManifestFinalPath
    $liveSourceManifestUnchanged = $liveSourceManifest.sha256 -eq $liveSourceManifestFinal.sha256
    if (-not $liveSourceManifestUnchanged) {
        $before = @{}
        $after = @{}
        foreach ($row in $liveSourceManifest.files) { $before[$row.path] = $row }
        foreach ($row in $liveSourceManifestFinal.files) { $after[$row.path] = $row }
        $allPaths = @($before.Keys) + @($after.Keys) | Sort-Object -Unique
        $liveSourceManifestDrift = @(
            foreach ($path in $allPaths) {
                if (-not $before.ContainsKey($path)) { "added:$path"; continue }
                if (-not $after.ContainsKey($path)) { "removed:$path"; continue }
                if (
                    $before[$path].size_bytes -ne $after[$path].size_bytes -or
                    $before[$path].sha256 -ne $after[$path].sha256
                ) { "changed:$path" }
            }
        )
    }
}
catch {
    $liveSourceManifestError = $_.Exception.Message
}

$totals = [ordered]@{
    successes = [int](($suiteRuns | ForEach-Object { [int]$_.successes } | Measure-Object -Sum).Sum)
    failures = [int](($suiteRuns | ForEach-Object { [int]$_.failures } | Measure-Object -Sum).Sum)
    errors = [int](($suiteRuns | ForEach-Object { [int]$_.errors } | Measure-Object -Sum).Sum)
}
$modelOutputsObserved = [int](
    ($suiteRuns | ForEach-Object { [int]$_.model_outputs_observed } | Measure-Object -Sum).Sum
)
$runtimeClaimDenials = @()
if ($PreflightOnly) { $runtimeClaimDenials += 'preflight_only' }
if ($suiteRuns.Count -eq 0) { $runtimeClaimDenials += 'no_model_suite_ran' }
if ($modelOutputsObserved -eq 0) { $runtimeClaimDenials += 'zero_model_output' }
foreach ($suite in $suiteRuns) {
    if ($suite.runtime_pass_claim_eligible -ne $true) {
        $runtimeClaimDenials += "suite_not_eligible:$($suite.suite)"
    }
}
if ($overallExit -ne 0) { $runtimeClaimDenials += "run_exit:$overallExit" }
$runtimeClaimDenials = @($runtimeClaimDenials | Select-Object -Unique)
$runtimePassClaimEligible = $runtimeClaimDenials.Count -eq 0
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
    preflight_only = [bool]$PreflightOnly
    thin_localization_workspace = $(if ($needsThinWorkspace) { $thinWorkspace } else { $null })
    catalog = $catalogPath
    output_root = $outputRoot
    source_snapshot = $sourceSnapshotPath
    source_snapshot_identity_sha256 = [string]$sourceSnapshot.identity_sha256
    source_snapshot_raw_root = $rawSnapshotRoot
    source_snapshot_effective_root = $executionRoot
    source_manifest = $sourceManifestPath
    source_manifest_sha256 = $sourceManifest.sha256
    source_manifest_final = $sourceManifestFinalPath
    source_manifest_final_sha256 = $sourceManifestFinal.sha256
    source_manifest_unchanged = $sourceManifestUnchanged
    source_manifest_drift = $sourceManifestDrift
    live_source_manifest = $liveSourceManifestPath
    live_source_manifest_final = $liveSourceManifestFinalPath
    live_source_manifest_unchanged = $liveSourceManifestUnchanged
    live_source_manifest_drift_advisory = $liveSourceManifestDrift
    live_source_manifest_error_advisory = $liveSourceManifestError
    deterministic_preflight = $preflightResult
    static_validation = $staticResult
    suites = $suiteRuns
    totals = $totals
    model_outputs_observed = $modelOutputsObserved
    runtime_pass_claim_eligible = $runtimePassClaimEligible
    runtime_claim_denial_reasons = $runtimeClaimDenials
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
