[CmdletBinding()]
param(
    [string]$CasePattern,
    [ValidateRange(1, 4)]
    [int]$MaxConcurrency = 1,
    [switch]$PreflightOnly,
    [string]$SourceContractPath,
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' })
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$suiteRelative = 'evals\semantic_implication_regression'
$suiteRoot = Join-Path $repoRoot $suiteRelative
if ($SourceContractPath) {
    $contractPath = [IO.Path]::GetFullPath($SourceContractPath)
}
else {
    $contractPath = Join-Path $suiteRoot 'source_contract.v1.json'
}
$configPath = Join-Path $suiteRoot 'promptfooconfig.yaml'
$casesPath = Join-Path $suiteRoot 'cases.yaml'
$builderPath = Join-Path $suiteRoot 'prepare_case_workspace.py'
$testPath = Join-Path $repoRoot 'tests\test_semantic_implication_regression.py'
$runnerPath = $PSCommandPath

function Get-CausalFileState {
    param(
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Path,
        [switch]$AllowMissing
    )
    $absolutePath = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
        if (-not $AllowMissing) {
            throw "Causal file is missing ($Role): $absolutePath"
        }
        return [ordered]@{ role = $Role; path = $absolutePath; state = 'absent' }
    }
    $resolved = (Resolve-Path -LiteralPath $absolutePath).Path
    $item = Get-Item -LiteralPath $resolved
    return [ordered]@{
        role = $Role
        path = $resolved
        state = 'file'
        size_bytes = [int64]$item.Length
        last_write_time_utc_ticks = [int64]$item.LastWriteTimeUtc.Ticks
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolved).Hash.ToLowerInvariant()
    }
}

function Assert-CausalFileStatesUnchanged {
    param([Parameter(Mandatory)][object[]]$Before)
    $after = @()
    foreach ($beforeState in @($Before)) {
        $afterState = Get-CausalFileState `
            -Role ([string]$beforeState.role) `
            -Path ([string]$beforeState.path) `
            -AllowMissing:([string]$beforeState.state -eq 'absent')
        $beforeJson = $beforeState | ConvertTo-Json -Depth 5 -Compress
        $afterJson = $afterState | ConvertTo-Json -Depth 5 -Compress
        if ($beforeJson -cne $afterJson) {
            throw "Causal file drifted during fresh evaluation ($($beforeState.role)): before=$beforeJson after=$afterJson"
        }
        $after += $afterState
    }
    return @($after)
}

function ConvertTo-TomlBasicString {
    param([Parameter(Mandatory)][string]$Value)
    if ($Value -match '[\x00-\x1F\x7F]') {
        throw 'TOML string contains a control character.'
    }
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function Assert-AuthSymbolicLink {
    param(
        [Parameter(Mandatory)][string]$LinkPath,
        [Parameter(Mandatory)][string]$TargetPath
    )
    if (-not (Test-Path -LiteralPath $LinkPath -PathType Leaf)) {
        throw "Evaluation authentication link is missing: $LinkPath"
    }
    $link = Get-Item -LiteralPath $LinkPath -Force
    $targets = @($link.Target)
    if ($link.LinkType -ne 'SymbolicLink' -or $targets.Count -ne 1) {
        throw "Evaluation authentication carrier is not one symbolic link: $LinkPath"
    }
    $reportedTarget = [string]$targets[0]
    if (-not [IO.Path]::IsPathRooted($reportedTarget)) {
        $reportedTarget = Join-Path (Split-Path -Parent $LinkPath) $reportedTarget
    }
    if (
        -not [IO.Path]::GetFullPath($reportedTarget).Equals(
            [IO.Path]::GetFullPath($TargetPath),
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw 'Evaluation authentication link no longer targets the selected live CODEX_HOME.'
    }
    return [ordered]@{
        auth_bytes_copied = $false
    }
}

function Remove-VerifiedAuthSymbolicLink {
    param(
        [Parameter(Mandatory)][string]$LinkPath,
        [Parameter(Mandatory)][string]$TargetPath
    )
    $link = Get-Item -LiteralPath $LinkPath -Force -ErrorAction SilentlyContinue
    if ($null -eq $link) {
        throw "Evaluation authentication link disappeared before cleanup: $LinkPath"
    }
    $targets = @($link.Target)
    if ($link.LinkType -ne 'SymbolicLink' -or $targets.Count -ne 1) {
        throw "Refusing to delete a non-link evaluation authentication carrier: $LinkPath"
    }
    $reportedTarget = [string]$targets[0]
    if (-not [IO.Path]::IsPathRooted($reportedTarget)) {
        $reportedTarget = Join-Path (Split-Path -Parent $LinkPath) $reportedTarget
    }
    $targetMatches = [IO.Path]::GetFullPath($reportedTarget).Equals(
        [IO.Path]::GetFullPath($TargetPath),
        [StringComparison]::OrdinalIgnoreCase
    )
    # The exact path is known to be a symbolic link, so removing the link cannot
    # remove either target.  Clean it even after target drift, then fail closed.
    Remove-Item -LiteralPath $LinkPath -Force
    if ($null -ne (Get-Item -LiteralPath $LinkPath -Force -ErrorAction SilentlyContinue)) {
        throw "Evaluation authentication link still exists after cleanup: $LinkPath"
    }
    if (-not $targetMatches) {
        throw 'Evaluation authentication link target drifted before cleanup.'
    }
}

foreach ($required in @($contractPath, $configPath, $casesPath, $builderPath, $testPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Semantic implication eval input is missing: $required"
    }
}
$bodyWitnessStatesBefore = @(
    Get-CausalFileState -Role 'runner' -Path $runnerPath
    Get-CausalFileState -Role 'static_test' -Path $testPath
    Get-CausalFileState -Role 'source_contract' -Path $contractPath
)

$contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json -Depth 30
if ($contract.schema_version -ne 'xinao.semantic_implication_source_contract.v1') {
    throw "Semantic implication source contract drift: $($contract.schema_version)"
}
if ($contract.runtime_loaded -ne $false -or $contract.automatic_core_inclusion -ne $false) {
    throw 'Semantic implication regression must remain cold and on demand.'
}
$nativeRepo = [string]$contract.canonical_source.repository
$nativeRelativeGit = ([string]$contract.canonical_source.relative_path).Replace('\', '/')
$canonicalSource = [IO.Path]::GetFullPath(
    [IO.Path]::Combine($nativeRepo, $nativeRelativeGit.Replace('/', [IO.Path]::DirectorySeparatorChar))
)
if (-not (Test-Path -LiteralPath $canonicalSource -PathType Leaf)) {
    throw "Canonical cold semantic-accident corpus is missing: $canonicalSource"
}

function Invoke-NativeGitScalar {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = @(& git -C $nativeRepo @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical Git lookup failed (git $($Arguments -join ' ')): $($output -join [Environment]::NewLine)"
    }
    $values = @($output | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ })
    if ($values.Count -ne 1) {
        throw "Canonical Git lookup returned $($values.Count) values (git $($Arguments -join ' '))."
    }
    return $values[0].ToLowerInvariant()
}

$expectedObjectFormat = ([string]$contract.canonical_source.git_object_format).ToLowerInvariant()
$expectedRepositoryCommit = ([string]$contract.canonical_source.repository_commit).ToLowerInvariant()
$expectedRepositoryTree = ([string]$contract.canonical_source.repository_tree).ToLowerInvariant()
$expectedFileBlob = ([string]$contract.canonical_source.file_blob).ToLowerInvariant()
foreach ($identity in @($expectedRepositoryCommit, $expectedRepositoryTree, $expectedFileBlob)) {
    if ($identity -notmatch '^[0-9a-f]{40}$') { throw "Canonical Git identity is invalid: $identity" }
}
$resolvedObjectFormat = Invoke-NativeGitScalar @('rev-parse', '--show-object-format')
$resolvedRepositoryCommit = Invoke-NativeGitScalar @('rev-parse', "$expectedRepositoryCommit`^{commit}")
$resolvedRepositoryTree = Invoke-NativeGitScalar @('rev-parse', "$expectedRepositoryCommit`^{tree}")
$resolvedFileBlob = Invoke-NativeGitScalar @('rev-parse', "${expectedRepositoryCommit}:$nativeRelativeGit")
$worktreeFileBlobBefore = Invoke-NativeGitScalar @('hash-object', '--', $nativeRelativeGit)
if (
    $resolvedObjectFormat -ne $expectedObjectFormat -or
    $resolvedRepositoryCommit -ne $expectedRepositoryCommit -or
    $resolvedRepositoryTree -ne $expectedRepositoryTree -or
    $resolvedFileBlob -ne $expectedFileBlob -or
    $worktreeFileBlobBefore -ne $expectedFileBlob
) {
    throw 'Canonical corpus Git commit/tree/blob identity or worktree bytes drifted from source_contract.v1.json.'
}
$expectedSourceHash = ([string]$contract.canonical_source.file_sha256).ToLowerInvariant()
$sourceHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $canonicalSource).Hash.ToLowerInvariant()
if ($sourceHashBefore -ne $expectedSourceHash) {
    throw "Canonical cold corpus hash drift: expected $expectedSourceHash, got $sourceHashBefore"
}
$canonical = Get-Content -LiteralPath $canonicalSource -Raw | ConvertFrom-Json -Depth 80
if (
    $canonical.schema_version -ne $contract.canonical_source.schema_version -or
    $canonical.corpus_id -ne $contract.canonical_source.corpus_id -or
    $canonical.load_policy -ne $contract.canonical_source.load_policy -or
    $canonical.seal.sha256 -ne $contract.canonical_source.corpus_seal_sha256
) {
    throw 'Canonical cold corpus semantic identity does not match source_contract.v1.json.'
}
foreach ($selected in @($contract.canonical_source.selected_case_ids)) {
    $canonicalCase = @($canonical.cases | Where-Object { $_.case_id -eq [string]$selected })
    if ($canonicalCase.Count -ne 1) { throw "Selected canonical case is absent: $selected" }
    $expectedCaseSeal = [string]$contract.canonical_source.selected_case_seals.$selected
    if ([string]$canonicalCase[0].seal.sha256 -ne $expectedCaseSeal) {
        throw "Selected canonical semantic-accident case seal drift: $selected"
    }
}

$previousBytecodeSetting = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
try {
    [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
    $preflight = & uv run python -B -m pytest -p no:cacheprovider -q $testPath
    if ($LASTEXITCODE -ne 0) {
        throw "Semantic implication static preflight failed: $($preflight -join [Environment]::NewLine)"
    }
}
finally {
    [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousBytecodeSetting, 'Process')
}
if ($PreflightOnly) {
    [pscustomobject]@{
        status = 'preflight_passed'
        suite = 'semantic_implication_regression'
        case_count = 14
        canonical_source = $canonicalSource
        canonical_source_sha256 = $sourceHashBefore
        repository_commit = $resolvedRepositoryCommit
        repository_tree = $resolvedRepositoryTree
        file_blob = $resolvedFileBlob
        runtime_loaded = $false
        model_invoked = $false
    } | ConvertTo-Json -Depth 5
    return
}

$promptfooRoot = Join-Path $RuntimeRoot 'tools\promptfoo'
$promptfooPackageRoot = Join-Path $promptfooRoot 'node_modules\promptfoo'
$promptfooPackagePath = Join-Path $promptfooPackageRoot 'package.json'
if (-not (Test-Path -LiteralPath $promptfooPackagePath -PathType Leaf)) {
    throw "Pinned Promptfoo package is missing: $promptfooPackagePath"
}
$promptfooPackage = Get-Content -LiteralPath $promptfooPackagePath -Raw | ConvertFrom-Json
if ($promptfooPackage.version -ne '0.121.18') {
    throw "Promptfoo version drift: expected 0.121.18, got $($promptfooPackage.version)"
}
$promptfooEntrypoint = Join-Path $promptfooPackageRoot ([string]$promptfooPackage.bin.promptfoo)
$node = (Get-Command node -ErrorAction Stop).Source
$python = (Get-Command python -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $CodexHome -PathType Container)) {
    throw "CODEX_HOME is missing: $CodexHome"
}
$liveCodexHome = (Resolve-Path -LiteralPath $CodexHome).Path
$liveAuthPath = Join-Path $liveCodexHome 'auth.json'
if (-not (Test-Path -LiteralPath $liveAuthPath -PathType Leaf)) {
    throw "Selected live CODEX_HOME authentication is missing: $liveAuthPath"
}
$codexShim = (Get-Command codex -ErrorAction Stop).Source
$codexPackage = Join-Path (Split-Path -Parent $codexShim) 'node_modules\@openai\codex'
$codexBinary = Get-ChildItem -LiteralPath $codexPackage -Filter 'codex.exe' -File -Recurse |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $codexBinary) { throw "Native Codex app-server binary is missing below: $codexPackage" }
$codexVersion = (& $codexBinary --version 2>&1 | Select-Object -Last 1).ToString().Trim()
$codexConfigPath = Join-Path $liveCodexHome 'config.toml'
$windowsHiddenChildrenShim = Join-Path $repoRoot 'scripts\windows_hide_background_children.cjs'
$consumerCausalStatesBefore = @(
    Get-CausalFileState -Role 'codex_auth' -Path $liveAuthPath
    Get-CausalFileState -Role 'codex_config' -Path $codexConfigPath
    Get-CausalFileState -Role 'codex_binary' -Path $codexBinary
    Get-CausalFileState -Role 'promptfoo_package' -Path $promptfooPackagePath
    Get-CausalFileState -Role 'promptfoo_entrypoint' -Path $promptfooEntrypoint
    Get-CausalFileState -Role 'windows_hidden_children_shim' -Path $windowsHiddenChildrenShim
)
$codexConfigText = Get-Content -LiteralPath $codexConfigPath -Raw
$modelMatch = [regex]::Match($codexConfigText, '(?m)^\s*model\s*=\s*"([^"]+)"')
$effortMatch = [regex]::Match($codexConfigText, '(?m)^\s*model_reasoning_effort\s*=\s*"([^"]+)"')
if (-not $modelMatch.Success) { throw 'Active Codex model identity is not declared in config.toml.' }
if (-not $effortMatch.Success) { throw 'Active Codex reasoning effort is not declared in config.toml.' }
Assert-CausalFileStatesUnchanged -Before @(
    $consumerCausalStatesBefore | Where-Object role -eq 'codex_config'
) | Out-Null
$selectedModel = $modelMatch.Groups[1].Value
$selectedModelReasoningEffort = $effortMatch.Groups[1].Value
$consumerIdentity = [ordered]@{
    provider_adapter = 'openai:codex-app-server'
    model = $selectedModel
    model_reasoning_effort = $selectedModelReasoningEffort
    windows_sandbox_implementation = 'unelevated'
    codex_version = $codexVersion
    codex_entry = $codexBinary
    codex_entry_sha256 = [string]($consumerCausalStatesBefore | Where-Object role -eq 'codex_binary').sha256
    configuration_source_home = $liveCodexHome
    live_codex_config_sha256 = [string]($consumerCausalStatesBefore | Where-Object role -eq 'codex_config').sha256
    ephemeral = $true
    reuse_server = $false
}

$runId = '{0}-{1}-{2}' -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'), $PID, ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$outputRoot = Join-Path $RuntimeRoot "state\human-capabilities\evals\semantic-implication-regression\$runId"
$snapshotRoot = Join-Path $outputRoot 'source-snapshot'
$snapshotSuite = Join-Path $snapshotRoot $suiteRelative
$workspaceRoot = Join-Path $outputRoot 'case-workspaces'
$manifestRoot = Join-Path $outputRoot 'case-manifests'
$promptfooState = Join-Path $outputRoot 'promptfoo'
$promptfooLogs = Join-Path $promptfooState 'logs'
$promptfooCache = Join-Path $promptfooState 'cache'
$tempRoot = Join-Path $outputRoot 'tmp'
$receiptPath = Join-Path $outputRoot 'semantic-implication-regression.verification.json'
$summaryPath = Join-Path $outputRoot 'summary.json'
New-Item -ItemType Directory -Path @(
    $snapshotSuite, $workspaceRoot, $manifestRoot, $promptfooState,
    $promptfooLogs, $promptfooCache, $tempRoot
) -Force | Out-Null
foreach ($sourceFile in Get-ChildItem -LiteralPath $suiteRoot -File -Recurse) {
    $relative = [IO.Path]::GetRelativePath($suiteRoot, $sourceFile.FullName)
    $parts = @($relative -split '[\\/]')
    if ('__pycache__' -in $parts -or $sourceFile.Extension -eq '.pyc') { continue }
    $target = Join-Path $snapshotSuite $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $sourceFile.FullName -Destination $target -Force
}
$snapshotSuiteStatesBefore = @(
    Get-ChildItem -LiteralPath $snapshotSuite -File -Recurse | ForEach-Object {
        Get-CausalFileState `
            -Role ('snapshot_suite:' + [IO.Path]::GetRelativePath($snapshotSuite, $_.FullName).Replace('\', '/')) `
            -Path $_.FullName
    }
)
$snapshotCases = Join-Path $snapshotSuite 'cases.yaml'
$snapshotBuilder = Join-Path $snapshotSuite 'prepare_case_workspace.py'
$caseConsole = & $python -B $snapshotBuilder list --cases $snapshotCases 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Could not enumerate semantic cases: $($caseConsole -join [Environment]::NewLine)"
}
$selectedCases = @($caseConsole | Select-Object -Last 1 | ConvertFrom-Json)
if ($CasePattern) {
    $selectedCases = @($selectedCases | Where-Object {
        [regex]::IsMatch([string]$_.description, $CasePattern) -or
        [regex]::IsMatch([string]$_.case_id, $CasePattern)
    })
}
if ($selectedCases.Count -eq 0) { throw 'CasePattern selected no semantic implication cases.' }
foreach ($case in $selectedCases) {
    if ([string]$case.case_id -notmatch '^[A-Z0-9_]+$') {
        throw "Unsafe semantic case id: $($case.case_id)"
    }
}

$evalCodexHome = [IO.Path]::GetFullPath((Join-Path $tempRoot 'codex-home'))
New-Item -ItemType Directory -Path $evalCodexHome | Out-Null
$evalConfigPath = Join-Path $evalCodexHome 'config.toml'
$evalAuthPath = Join-Path $evalCodexHome 'auth.json'
$evalConfigLines = @(
    'model = ' + (ConvertTo-TomlBasicString -Value $selectedModel)
    'model_reasoning_effort = ' + (ConvertTo-TomlBasicString -Value $selectedModelReasoningEffort)
    ''
    '[features]'
    'hooks = false'
    ''
    '[windows]'
    'sandbox = "unelevated"'
)
foreach ($case in $selectedCases) {
    $workspace = [IO.Path]::GetFullPath((Join-Path $workspaceRoot ([string]$case.case_id)))
    $evalConfigLines += @(
        ''
        '[projects.' + (ConvertTo-TomlBasicString -Value $workspace) + ']'
        'trust_level = "trusted"'
    )
}
[IO.File]::WriteAllLines(
    $evalConfigPath,
    [string[]]$evalConfigLines,
    [Text.UTF8Encoding]::new($false)
)
$authLinkCreated = $false
try {
New-Item -ItemType SymbolicLink -Path $evalAuthPath -Target $liveAuthPath | Out-Null
$authLinkCreated = $true
$authLinkWitness = Assert-AuthSymbolicLink -LinkPath $evalAuthPath -TargetPath $liveAuthPath
$consumerCausalStatesBefore = @($consumerCausalStatesBefore) + @(
    Get-CausalFileState -Role 'eval_codex_config' -Path $evalConfigPath
)
$consumerIdentity['codex_home'] = $evalCodexHome
$consumerIdentity['eval_codex_config_sha256'] = [string](
    $consumerCausalStatesBefore | Where-Object role -eq 'eval_codex_config'
).sha256
$consumerIdentity['authentication'] = $authLinkWitness
$sourceHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $canonicalSource).Hash.ToLowerInvariant()
$worktreeFileBlobAfter = Invoke-NativeGitScalar @('hash-object', '--', $nativeRelativeGit)
if ($sourceHashAfter -ne $expectedSourceHash -or $worktreeFileBlobAfter -ne $expectedFileBlob) {
    throw 'Canonical cold corpus changed while the evaluation source was being frozen.'
}
$sourceManifest = [ordered]@{
    schema_version = 'xinao.semantic_implication_source_snapshot.v2'
    suite = 'semantic_implication_regression'
    runtime_loaded = $false
    canonical_source = [ordered]@{
        locator = $canonicalSource
        sha256 = $sourceHashAfter
        git_object_format = $resolvedObjectFormat
        repository_commit = $resolvedRepositoryCommit
        repository_tree = $resolvedRepositoryTree
        file_blob = $resolvedFileBlob
        corpus_seal_sha256 = [string]$canonical.seal.sha256
        selected_case_seals = $contract.canonical_source.selected_case_seals
    }
    consumer_identity = $consumerIdentity
    body_witness = [ordered]@{
        runner = $bodyWitnessStatesBefore | Where-Object role -eq 'runner'
        static_test = $bodyWitnessStatesBefore | Where-Object role -eq 'static_test'
        consumer_causal_files = @($consumerCausalStatesBefore)
        frozen_suite_files = @($snapshotSuiteStatesBefore)
    }
}
$sourceManifestPath = Join-Path $snapshotRoot 'source-snapshot.v2.json'
[IO.File]::WriteAllText($sourceManifestPath, ($sourceManifest | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))

$environment = @{
    CODEX_HOME = $evalCodexHome
    CODEX_APP_SERVER_PATH = $codexBinary
    SEMANTIC_IMPLICATION_CANONICAL_SHA256 = $sourceHashAfter
    SEMANTIC_IMPLICATION_MODEL = $selectedModel
    SEMANTIC_IMPLICATION_MODEL_REASONING_EFFORT = $selectedModelReasoningEffort
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
    NODE_OPTIONS = (@(
        [Environment]::GetEnvironmentVariable('NODE_OPTIONS', 'Process'),
        "--require=`"$($windowsHiddenChildrenShim.Replace('\', '/'))`""
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ' '
}
$previous = @{}
foreach ($name in $environment.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, [string]$environment[$name], 'Process')
}

try {
    $resultPaths = @()
    $manifestPaths = @()
    $workspaceVerifications = @()
    foreach ($case in $selectedCases) {
        $caseId = [string]$case.case_id
        if ($caseId -notmatch '^[A-Z0-9_]+$') { throw "Unsafe semantic case id: $caseId" }
        $workspace = [IO.Path]::GetFullPath((Join-Path $workspaceRoot $caseId))
        $manifest = Join-Path $manifestRoot "$caseId.json"
        $prepareConsole = & $python -B $snapshotBuilder prepare `
            --suite-root $snapshotSuite --cases $snapshotCases --canonical $canonicalSource `
            --case-id $caseId --workspace $workspace --manifest $manifest 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Case workspace preparation failed ($caseId): $($prepareConsole -join [Environment]::NewLine)" }
        $initialConsole = & $python -B $snapshotBuilder verify --manifest $manifest --phase initial 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Initial workspace verification failed ($caseId): $($initialConsole -join [Environment]::NewLine)" }
        [Environment]::SetEnvironmentVariable('SEMANTIC_IMPLICATION_WORKSPACE', $workspace, 'Process')
        [Environment]::SetEnvironmentVariable('SEMANTIC_IMPLICATION_CASE_MANIFEST', $manifest, 'Process')
        $resultPath = Join-Path $outputRoot "$caseId.result.json"
        $arguments = @(
            'eval', '--config', (Join-Path $snapshotSuite 'promptfooconfig.yaml'),
            '--max-concurrency', ([Math]::Min($MaxConcurrency, 1)), '--no-progress-bar',
            '--no-cache', '--filter-pattern', ('^' + [regex]::Escape([string]$case.description) + '$'),
            '--output', $resultPath
        )
        $console = & $node $promptfooEntrypoint @arguments 2>&1
        $exitCode = $LASTEXITCODE
        [IO.File]::WriteAllLines(
            (Join-Path $outputRoot "$caseId.promptfoo.console.log"),
            [string[]]$console,
            [Text.UTF8Encoding]::new($false)
        )
        Assert-CausalFileStatesUnchanged -Before $bodyWitnessStatesBefore | Out-Null
        Assert-CausalFileStatesUnchanged -Before $consumerCausalStatesBefore | Out-Null
        Assert-CausalFileStatesUnchanged -Before $snapshotSuiteStatesBefore | Out-Null
        Assert-AuthSymbolicLink -LinkPath $evalAuthPath -TargetPath $liveAuthPath | Out-Null
        if ($exitCode -ne 0) { throw "Fresh semantic implication case failed ($caseId) with exit code $exitCode." }
        $finalConsole = & $python -B $snapshotBuilder verify --manifest $manifest --phase final 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Final workspace verification failed ($caseId): $($finalConsole -join [Environment]::NewLine)" }
        $workspaceVerifications += @($finalConsole | Select-Object -Last 1 | ConvertFrom-Json)
        $resultPaths += $resultPath
        $manifestPaths += $manifest
    }

    $verifyArguments = @('-B', (Join-Path $snapshotSuite 'verify_result.py'))
    foreach ($resultPath in $resultPaths) { $verifyArguments += @('--result', $resultPath) }
    foreach ($manifest in $manifestPaths) { $verifyArguments += @('--manifest', $manifest) }
    $verifyArguments += @('--receipt', $receiptPath, '--canonical-source-sha256', $sourceHashAfter)
    if (-not $CasePattern) { $verifyArguments += @('--required-case-count', '14') }
    $verifyConsole = & $python @verifyArguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Semantic implication verification failed: $($verifyConsole -join [Environment]::NewLine)" }
    $bodyWitnessStatesAfter = @(Assert-CausalFileStatesUnchanged -Before $bodyWitnessStatesBefore)
    $consumerCausalStatesAfter = @(Assert-CausalFileStatesUnchanged -Before $consumerCausalStatesBefore)
    $snapshotSuiteStatesAfter = @(Assert-CausalFileStatesUnchanged -Before $snapshotSuiteStatesBefore)
    Assert-AuthSymbolicLink -LinkPath $evalAuthPath -TargetPath $liveAuthPath | Out-Null
    $verification = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $summary = [ordered]@{
        schema_version = 'xinao.semantic_implication_run_summary.v2'
        status = 'verified'
        suite = 'semantic_implication_regression'
        provider_adapter = 'openai:codex-app-server'
        consumer_identity = $consumerIdentity
        source_snapshot = $sourceManifestPath
        source_snapshot_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceManifestPath).Hash.ToLowerInvariant()
        runner_sha256 = [string]($bodyWitnessStatesAfter | Where-Object role -eq 'runner').sha256
        static_test_sha256 = [string]($bodyWitnessStatesAfter | Where-Object role -eq 'static_test').sha256
        consumer_causal_files = @($consumerCausalStatesAfter)
        frozen_suite_files = @($snapshotSuiteStatesAfter)
        causal_file_stability_verified = $true
        canonical_source_sha256 = $sourceHashAfter
        result_files = @($resultPaths)
        case_manifests = @($manifestPaths)
        workspace_verifications = @($workspaceVerifications)
        verification = $receiptPath
        selected_case_count = [int]$verification.selected_case_count
        fresh_thread_count = [int]$verification.fresh_thread_count
        fresh_turn_count = [int]$verification.fresh_turn_count
        fresh_workspace_count = [int]$verification.fresh_workspace_count
        checked_metamorphic_pairs = @($verification.checked_metamorphic_pairs)
        hidden_state_claim_allowed = $false
        permanent_uptake_claim_allowed = $false
        automatic_core_rewrite_allowed = $false
    }
    [IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
    $summaryPath
}
finally {
    [Environment]::SetEnvironmentVariable('SEMANTIC_IMPLICATION_WORKSPACE', $null, 'Process')
    [Environment]::SetEnvironmentVariable('SEMANTIC_IMPLICATION_CASE_MANIFEST', $null, 'Process')
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
}
finally {
    if ($authLinkCreated) {
        Remove-VerifiedAuthSymbolicLink -LinkPath $evalAuthPath -TargetPath $liveAuthPath
    }
}
