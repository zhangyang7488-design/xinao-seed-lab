#Requires -Version 5.1
<#
.SYNOPSIS
  Pull OpenHands image and smoke when Docker daemon is up. NOT_333_MAINLINE.
#>
param(
    [string]$Image = "ghcr.io/openhands/agent-canvas:1.0.0-rc.11",
    [string]$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\openhands_smoke"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null

$report = [ordered]@{
    schema_version = "xinao.openhands_smoke.v1"
    generated_at   = (Get-Date).ToString("o")
    not_333_mainline = $true
    image          = $Image
    docker_ok      = $false
    pull_ok        = $false
    named_blocker  = $null
}

try {
    $null = & docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        $report.named_blocker = "DOCKER_DAEMON_NOT_RUNNING"
        $report | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $EvidenceRoot "latest.json") -Encoding UTF8
        Write-Host "BLOCKER: DOCKER_DAEMON_NOT_RUNNING — use Windows MCP to start Docker Desktop first"
        exit 0
    }
    $report.docker_ok = $true
    Write-Host "Pulling $Image ..."
    & docker pull $Image 2>&1 | Out-Host
    $report.pull_ok = ($LASTEXITCODE -eq 0)
    if (-not $report.pull_ok) { $report.named_blocker = "DOCKER_PULL_FAILED" }
}
catch {
    $report.named_blocker = $_.Exception.Message
}

$out = Join-Path $EvidenceRoot "latest.json"
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Host "evidence=$out"
$report | ConvertTo-Json -Depth 4