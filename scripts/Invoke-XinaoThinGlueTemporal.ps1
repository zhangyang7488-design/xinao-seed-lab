# thin_glue_loop via Temporal (独立队列 xinao-thin-glue-loop-v1)
param(
    [string]$InputPath = "",
    [string]$MaterialsDir = "",
    [switch]$NoDocker,
    [switch]$GatewayChat
)

$ErrorActionPreference = "Stop"
$env:LITELLM_MASTER_KEY = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Set-Location $RepoRoot

$cliArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue", "--temporal")
if ($InputPath) { $cliArgs += @("--input", $InputPath) }
if ($MaterialsDir) { $cliArgs += @("--materials-dir", $MaterialsDir) }
if ($NoDocker) { $cliArgs += "--no-docker" }
if ($GatewayChat) { $cliArgs += "--gateway-chat" }

& $py @cliArgs
exit $LASTEXITCODE