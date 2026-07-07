# 薄胶闭环一体 — 胶水替换 + 最小闭环同跑（默认入口）
param(
    [string]$InputPath = "",
    [string]$MaterialsDir = "",
    [switch]$NoDocker,
    [switch]$GatewayChat,
    [switch]$StartStack,
    [switch]$NoWrite
)

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Set-Location $RepoRoot

if ($StartStack) {
    & (Join-Path $RepoRoot "scripts\Start-XinaoThinGlueStack.ps1")
}

$cliArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue")
if ($InputPath) { $cliArgs += @("--input", $InputPath) }
if ($MaterialsDir) { $cliArgs += @("--materials-dir", $MaterialsDir) }
if ($NoDocker) { $cliArgs += "--no-docker" }
if ($GatewayChat) { $cliArgs += "--gateway-chat" }
if ($NoWrite) { $cliArgs += "--no-write" }

& $py @cliArgs
exit $LASTEXITCODE