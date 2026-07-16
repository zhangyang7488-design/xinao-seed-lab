$ErrorActionPreference = "Stop"

$mandatoryLevel = & whoami.exe /groups | Select-String -Pattern "S-1-16-(12288|16384)"
if (-not $mandatoryLevel) {
    throw "WINDOWS_ELEVATION_REQUIRED: launch with Codex 输入框试验版.lnk"
}

$codexHome = "C:\Users\xx363\.codex"
$workdir = "E:\XINAO_RESEARCH_WORKSPACES\S"
$runtime = "D:\XINAO_RESEARCH_RUNTIME"
$situationIsland = "D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island"
$canaryRoot = "D:\XINAO_RESEARCH_RUNTIME\tools\codex-input-canary\0.144.5-20260716-0e350e52-wt-composer"
$codexBinary = Join-Path $canaryRoot "codex-tui.exe"
$codeModeHost = Join-Path $canaryRoot "codex-code-mode-host.exe"
$expectedCodexSha256 = "0E350E52B191CAE654E4EC7670FC6198984397D65A0C432A22D27EED04D1EF7F"
$expectedHostSha256 = "5D7DB48DEE5E82AE23E98E33C3421F2774DC50C52C53374685D616997844116F"

foreach ($path in @($codexHome, $workdir, $runtime, $situationIsland, $canaryRoot)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "CODEX_INPUT_CANARY_REQUIRED_PATH_MISSING: $path"
    }
}
foreach ($path in @($codexBinary, $codeModeHost)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "CODEX_INPUT_CANARY_BINARY_MISSING: $path"
    }
}

if ((Get-FileHash -Algorithm SHA256 -LiteralPath $codexBinary).Hash -ne $expectedCodexSha256) {
    throw "CODEX_INPUT_CANARY_BINARY_HASH_MISMATCH"
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $codeModeHost).Hash -ne $expectedHostSha256) {
    throw "CODEX_INPUT_CANARY_HOST_HASH_MISMATCH"
}

$configPath = Join-Path $codexHome "config.toml"
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "CODEX_S_CONFIG_MISSING: $configPath"
}

$env:CODEX_HOME = $codexHome
$env:XINAO_REPO = $workdir
$env:XINAO_RUNTIME = $runtime

# Preserve the same Codex peer-brain role as the stable S launcher.
$dualBrainEnv = "E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\adapters\env\Set-XinaoDualBrainRoleEnv.ps1"
if ($env:XINAO_DUAL_BRAIN_TURN_DRAIN -eq "1") {
    Write-Host "DUAL_BRAIN: 每回合开头先收信 — Invoke-XinaoDualBrainTurnDrain.ps1 或 amq drain / MCP amq_ingest" -ForegroundColor DarkCyan
}
if (Test-Path -LiteralPath $dualBrainEnv -PathType Leaf) {
    try {
        & $dualBrainEnv -Role codex -Quiet | Out-Null
        Write-Host "DUAL_BRAIN: XINAO_COORD_ROLE=codex AM_ME=$($env:AM_ME) AM_ROOT=$($env:AM_ROOT)" -ForegroundColor DarkCyan
    } catch {
        Write-Host "DUAL_BRAIN_ENV_WARN: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    $env:XINAO_COORD_ROLE = "codex"
    $env:AM_ME = "codex"
    $env:AM_ROOT = "D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq"
    Write-Host "DUAL_BRAIN_ENV: minimal pin (adapter missing)" -ForegroundColor Yellow
}

foreach ($name in @(
    "XINAO_CANONICAL_REPO",
    "XINAO_BLUEPRINT_REPO",
    "XINAO_LEGACY_BLUEPRINT_REPO",
    "XINAO_COMPAT_RUNTIME",
    "XINAO_COMPAT_RUNTIME_ROOT",
    "XINAO_CODEX_SITUATION_ISLAND",
    "XINAO_CODEX_SITUATION_REF",
    "XINAO_CODEX_MATURE_CAPABILITY_CATALOG_REF",
    "XINAO_INGRESS_BASE_URL",
    "XINAO_ROUTE_PROFILE",
    "XINAO_HARDMODE",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_MODEL",
    "CODEX_MODEL",
    "CODEX_API_BASE_URL",
    "CODEX_MODEL_PROVIDER"
)) {
    Remove-Item -LiteralPath "Env:\$name" -ErrorAction SilentlyContinue
}

$env:XINAO_CODEX_SITUATION_ISLAND = $situationIsland
$env:XINAO_CODEX_SITUATION_REF = Join-Path $situationIsland "state\session_checkpoint.json"
$env:XINAO_CODEX_CAPABILITY_REF = Join-Path $situationIsland "state\capability_snapshot.json"
foreach ($name in @(
    "CODEX_TUI_APP_MOUSE",
    "CODEX_TUI_MOUSE_COMPOSER",
    "CODEX_TUI_MOUSE_COMPOSER_HOST",
    "CODEX_TUI_MOUSE_HOST_HWND",
    "CODEX_TUI_MOUSE_WINDOW_TITLE",
    "CODEX_TUI_MOUSE_EVIDENCE_PATH"
)) {
    Remove-Item -LiteralPath "Env:\$name" -ErrorAction SilentlyContinue
}
$env:CODEX_TUI_MOUSE_COMPOSER_HOST = "1"
$env:CODEX_CODE_MODE_HOST_PATH = $codeModeHost

Set-Location -LiteralPath $workdir

$configuredModel = "default"
$modelLine = Select-String -LiteralPath $configPath -Pattern '^\s*model\s*=' | Select-Object -First 1
if ($modelLine) {
    $configuredModel = ($modelLine.Line -split '=', 2)[1].Trim().Trim('"')
}

Write-Host "CODEX S · direct clean launch" -ForegroundColor Cyan
Write-Host "CODEX_HOME=$codexHome"
Write-Host "WORKDIR=$workdir"
Write-Host "RUNTIME=$runtime"
Write-Host "SITUATION_ISLAND=$situationIsland"
Write-Host "MODEL=$configuredModel"
Write-Host ""

if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) {
    throw "CODEX_S_INTERACTIVE_TERMINAL_REQUIRED"
}

& $codexBinary --cd $workdir --dangerously-bypass-approvals-and-sandbox
$exitCode = $LASTEXITCODE
if ($null -eq $exitCode) {
    $exitCode = 0
}
if ($exitCode -ne 0) {
    throw "CODEX_INPUT_CANARY_LAUNCH_FAILED: codex exited with $exitCode"
}
exit $exitCode
