# DEPRECATED thin-glue-only launcher — gateway merged into docker-compose.yml (XINAO_Base V2)
param(
    [switch]$Down,
    [switch]$Probe
)

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$composeFile = Join-Path $RepoRoot "docker-compose.yml"
Set-Location $RepoRoot

if ($Down) {
    docker compose -f $composeFile stop litellm qdrant
    exit $LASTEXITCODE
}

docker compose -f $composeFile up -d moxing-wangguan xiangliang-ku naijiu-shiwu shiwu-mianban houtai-gongren
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Probe) {
    $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    & $py -m xinao_seedlab.cli.__main__ thin-provider-probe
    exit $LASTEXITCODE
}

Write-Host "XINAO_Base V2: litellm :20128 + qdrant :6333 (unified compose)"
Write-Host "Full stack: scripts/Start-XinaoBaseCompose.ps1 -Build"