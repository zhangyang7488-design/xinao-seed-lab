# closure_test_v1 via Temporal (stage C)
param(
    [string]$InputPath = "",
    [switch]$NoDocker
)

$ErrorActionPreference = "Stop"
$env:LITELLM_MASTER_KEY = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Set-Location $RepoRoot

$cliArgs = @("-m", "xinao_seedlab.cli.__main__", "closure-test-v1", "--temporal")
if ($InputPath) { $cliArgs += @("--input", $InputPath) }
if ($NoDocker) { $cliArgs += "--no-docker" }

& $py @cliArgs
exit $LASTEXITCODE