[CmdletBinding()]
param(
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(Join-Path $HOME '.codex')
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$promptfoo = Join-Path $RuntimeRoot 'tools\promptfoo\node_modules\.bin\promptfoo.cmd'
$config = Join-Path $repoRoot 'evals\codex_capability\promptfooconfig.yaml'
$outputRoot = Join-Path $RuntimeRoot 'state\human-capabilities\evals\codex-app-server'
$result = Join-Path $outputRoot 'latest.json'
$promptfooState = Join-Path $outputRoot 'promptfoo'
$promptfooLogs = Join-Path $promptfooState 'logs'

if (-not (Test-Path -LiteralPath $promptfoo -PathType Leaf)) {
    throw "Pinned Promptfoo runtime is missing: $promptfoo"
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

New-Item -ItemType Directory -Path $outputRoot, $promptfooState, $promptfooLogs -Force | Out-Null
$previousCodexHome = $env:CODEX_HOME
$previousCodexAppServerPath = $env:CODEX_APP_SERVER_PATH
$previousPromptfooConfigDir = $env:PROMPTFOO_CONFIG_DIR
$previousPromptfooLogDir = $env:PROMPTFOO_LOG_DIR
$previousPromptfooDisableTelemetry = $env:PROMPTFOO_DISABLE_TELEMETRY
try {
    $env:CODEX_HOME = (Resolve-Path -LiteralPath $CodexHome).Path
    $env:CODEX_APP_SERVER_PATH = $codexBinary
    $env:PROMPTFOO_CONFIG_DIR = $promptfooState
    $env:PROMPTFOO_LOG_DIR = $promptfooLogs
    $env:PROMPTFOO_DISABLE_TELEMETRY = '1'
    & $promptfoo eval --config $config --no-cache --output $result
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    $env:CODEX_HOME = $previousCodexHome
    $env:CODEX_APP_SERVER_PATH = $previousCodexAppServerPath
    $env:PROMPTFOO_CONFIG_DIR = $previousPromptfooConfigDir
    $env:PROMPTFOO_LOG_DIR = $previousPromptfooLogDir
    $env:PROMPTFOO_DISABLE_TELEMETRY = $previousPromptfooDisableTelemetry
}

Write-Output $result
