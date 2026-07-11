#Requires -Version 5.1
<#
.SYNOPSIS
  XINAO_Base V2 compose start thin shell.
.DESCRIPTION
  docker compose -f S\docker-compose.yml up -d
  -CoreOnly: shiwu-ku / naijiu-shiwu / shiwu-mianban / houtai-gongren
  Optional -Profile ollama / -Build
  ClaimDurable: -RepoRoot / -RuntimeRoot write state\xinao_base_compose\latest.json
  Never down / never -v.
.EXAMPLE
  .\Start-XinaoBaseCompose.ps1
  .\Start-XinaoBaseCompose.ps1 -CoreOnly
#>
[CmdletBinding()]
param(
    [string]$ComposeFile = "",
    [string]$RepoRoot = "",
    [string]$RuntimeRoot = "",
    [switch]$CoreOnly,
    [switch]$Build,
    [string[]]$Profile = @(),
    [string[]]$Service = @(),
    [switch]$Quiet,
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$script:CoreServices = @("shiwu-ku", "naijiu-shiwu", "shiwu-mianban", "houtai-gongren")

if (-not $RepoRoot) {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
}
if (-not $ComposeFile) {
    $ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
}
if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
    $ComposeFile = "E:\XINAO_RESEARCH_WORKSPACES\S\docker-compose.yml"
    $RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
}
if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
    throw "Compose file missing: $ComposeFile"
}
if (-not $RuntimeRoot) {
    $RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
}

$workDir = Split-Path $ComposeFile -Parent
$report = [ordered]@{
    schema_version           = "xinao.base_compose_start.v2"
    sentinel                 = "SENTINEL:XINAO_BASE_COMPOSE_START"
    generated_at             = (Get-Date).ToString("o")
    golden_path              = "docker compose -f S/docker-compose.yml up -d"
    compose_file             = $ComposeFile
    repo_root                = $RepoRoot
    runtime_root             = $RuntimeRoot
    core_only                = [bool]$CoreOnly
    core_services            = @($script:CoreServices)
    build                    = [bool]$Build
    profiles                 = @($Profile)
    services_targeted        = @()
    status                   = "unknown"
    temporal_ok              = $false
    worker_ok                = $false
    docker_exit_code         = $null
    docker_command           = ""
    named_blocker            = $null
    completion_claim_allowed = $false
}

Push-Location $workDir
try {
    $dargs = @("compose", "-f", $ComposeFile)
    foreach ($p in $Profile) {
        if ($p) { $dargs += @("--profile", $p) }
    }
    $dargs += @("up", "-d")
    if ($Build) { $dargs += "--build" }

    $targets = @()
    if ($Service -and $Service.Count -gt 0) {
        $targets = @($Service | Where-Object { $_ })
    }
    elseif ($CoreOnly) {
        $targets = @($script:CoreServices)
    }
    if ($targets.Count -gt 0) {
        $dargs += $targets
        $report.services_targeted = $targets
    }

    $report.docker_command = ("docker {0}" -f ($dargs -join " "))
    if (-not $Quiet) {
        Write-Host ("[Start-XinaoBaseCompose] {0}" -f $report.docker_command)
    }
    & docker @dargs
    $report.docker_exit_code = $LASTEXITCODE
    $composeFailed = ($LASTEXITCODE -ne 0)

    $names = @(& docker ps --format "{{.Names}}" 2>$null)
    $report.temporal_ok = ($names -contains "naijiu-shiwu")
    $report.worker_ok = ($names -contains "houtai-gongren")
    try {
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { $report.temporal_ok = $true }
    } catch { }

    if ($report.temporal_ok -and $report.worker_ok) {
        $report.status = "running"
        if ($composeFailed) {
            $report.named_blocker = "COMPOSE_UP_NONEZERO_BUT_CORE_RUNNING"
            $report["compose_warn"] = "docker compose exit=$($report.docker_exit_code); core services already up"
        }
    }
    elseif ($report.temporal_ok) {
        $report.status = "partial"
        if ($composeFailed) {
            $report.named_blocker = "DOCKER_COMPOSE_UP_FAILED"
        } else {
            $report.named_blocker = "WORKER_NOT_UP"
        }
    }
    elseif ($composeFailed) {
        $report.status = "failed"
        $report.named_blocker = "DOCKER_COMPOSE_UP_FAILED"
        throw "docker compose up failed exit=$($report.docker_exit_code)"
    }
    else {
        $report.status = "degraded"
        $report.named_blocker = "TEMPORAL_NOT_UP"
    }

    if (-not $Quiet) {
        & docker compose -f $ComposeFile ps
    }
}
catch {
    try {
        $names2 = @(& docker ps --format "{{.Names}}" 2>$null)
        if (($names2 -contains "naijiu-shiwu") -and ($names2 -contains "houtai-gongren")) {
            $report.temporal_ok = $true
            $report.worker_ok = $true
            $report.status = "running"
            $report.named_blocker = "START_EXCEPTION_BUT_CORE_RUNNING"
            $report["error"] = $_.Exception.Message
        } else {
            if ($report.status -eq "unknown") {
                $report.status = "failed"
                $report.named_blocker = "START_EXCEPTION"
            }
            $report["error"] = $_.Exception.Message
            throw
        }
    } catch {
        if ($report.status -eq "unknown" -or $report.status -eq "failed") {
            $report.status = "failed"
            if (-not $report.named_blocker) { $report.named_blocker = "START_EXCEPTION" }
            $report["error"] = $_.Exception.Message
        }
        throw
    }
}
finally {
    Pop-Location
    $evDir = Join-Path $RuntimeRoot "state\xinao_base_compose"
    New-Item -ItemType Directory -Force -Path $evDir | Out-Null
    $json = ($report | ConvertTo-Json -Depth 8)
    [System.IO.File]::WriteAllText((Join-Path $evDir "latest.json"), $json, $utf8)
    $stamp = Join-Path $evDir ("start_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
    [System.IO.File]::WriteAllText($stamp, $json, $utf8)
    if ($AsJson -or $Quiet) {
        Write-Output $json
    }
}

if ($report.status -eq "running" -or $report.status -eq "partial") { exit 0 }
exit 1