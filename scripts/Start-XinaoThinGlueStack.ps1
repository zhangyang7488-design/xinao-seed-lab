# Start LiteLLM thin-glue gateway on localhost:20128
param(
    [switch]$Down,
    [switch]$Probe
)

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
Set-Location $RepoRoot

if ($Down) {
    docker compose -f docker-compose.thin-glue.yml down
    exit $LASTEXITCODE
}

docker compose -f docker-compose.thin-glue.yml up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Probe) {
    $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    & $py -m xinao_seedlab.cli.__main__ thin-provider-probe
    exit $LASTEXITCODE
}

Write-Host "Thin glue gateway starting on http://127.0.0.1:20128/v1"
Write-Host "Probe: .\.venv\Scripts\python.exe -m xinao_seedlab.cli.__main__ thin-provider-probe"