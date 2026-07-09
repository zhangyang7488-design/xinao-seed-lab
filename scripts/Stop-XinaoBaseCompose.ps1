param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $RepoRoot "docker-compose.yml"
Set-Location $RepoRoot
& docker compose -f $composeFile down
$evidencePath = Join-Path $RuntimeRoot "state\xinao_base_compose\latest.json"
[ordered]@{
    schema_version = "xinao.base_compose.v1"
    status         = "stopped"
    generated_at   = (Get-Date).ToString("o")
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $evidencePath -Encoding UTF8