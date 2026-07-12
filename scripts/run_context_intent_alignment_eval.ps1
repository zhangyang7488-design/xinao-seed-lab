[CmdletBinding()]
param(
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(Join-Path $HOME '.codex')
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$promptfooRoot = Join-Path $RuntimeRoot 'tools\promptfoo'
$promptfoo = Join-Path $promptfooRoot 'node_modules\.bin\promptfoo.cmd'
$promptfooPackage = Join-Path $promptfooRoot 'node_modules\promptfoo\package.json'
$config = Join-Path $repoRoot 'evals\context_intent_alignment\promptfooconfig.yaml'
$runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$outputRoot = Join-Path $RuntimeRoot "state\human-capabilities\evals\context-intent-alignment\$runId"
$result = Join-Path $outputRoot 'result.json'
$promptfooState = Join-Path $outputRoot 'promptfoo'
$promptfooLogs = Join-Path $promptfooState 'logs'
$promptfooCache = Join-Path $promptfooState 'cache'
$tempRoot = Join-Path $outputRoot 'tmp'

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

New-Item -ItemType Directory -Path @(
    $outputRoot,
    $promptfooState,
    $promptfooLogs,
    $promptfooCache,
    $tempRoot
) -Force | Out-Null

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
    TEMP = $tempRoot
    TMP = $tempRoot
}
$previous = @{}
foreach ($name in $environment.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    foreach ($name in $environment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $environment[$name], 'Process')
    }
    & $promptfoo eval --config $config --no-cache --output $result
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}

Write-Output $result
