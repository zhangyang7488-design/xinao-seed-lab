# 主队列薄接缝 — thin-glue-mainline-orch（需 --force 或 XINAO_THIN_GLUE_MAINLINE_SPAWN=1）
param(
    [string]$InputPath = "",
    [switch]$NoDocker,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$env:LITELLM_MASTER_KEY = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Set-Location $RepoRoot

$cliArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue-mainline-orch")
if ($InputPath) { $cliArgs += @("--input", $InputPath) }
if ($NoDocker) { $cliArgs += "--no-docker" }
if ($Force) { $cliArgs += "--force" }

& $py @cliArgs
exit $LASTEXITCODE