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

function Invoke-WorkerRepoMountPreflight {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("compose", "actual")][string]$Mode,
        [Parameter(Mandatory = $true)][string]$Repo,
        [Parameter(Mandatory = $true)][string]$Compose
    )
    $python = Join-Path $Repo ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $pythonCommand = Get-Command python -ErrorAction Stop
        $python = [string]$pythonCommand.Source
    }
    $arguments = @(
        "-m", "services.agent_runtime.worker_repo_mount_identity",
        "--repo-root", $Repo,
        "--mode", $Mode
    )
    if ($Mode -eq "compose") {
        $arguments += @("--compose-file", $Compose)
    } else {
        $arguments += @("--container", "houtai-gongren")
    }
    $raw = (& $python @arguments 2>&1 | Out-String).Trim()
    $exitCode = $LASTEXITCODE
    try {
        $payload = $raw | ConvertFrom-Json
    } catch {
        $payload = [pscustomobject]@{
            ok                          = $false
            named_blocker               = "WORKER_REPO_MOUNT_MISMATCH"
            provider_invocation_allowed = $false
            issues                      = @(@{ code = "MOUNT_PREFLIGHT_OUTPUT_INVALID"; message = $raw.Substring(0, [Math]::Min(400, $raw.Length)) })
        }
    }
    return [pscustomobject]@{ exit_code = $exitCode; report = $payload }
}

if (-not $RepoRoot) {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
}
if (-not $ComposeFile) {
    $ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
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
    worker_container_state   = ""
    docker_exit_code         = $null
    docker_command           = ""
    named_blocker            = $null
    worker_mount_compose     = $null
    worker_mount_actual      = $null
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

    $workerTargeted = ($targets.Count -eq 0 -or $targets -contains "houtai-gongren")
    if ($workerTargeted) {
        $composeMount = Invoke-WorkerRepoMountPreflight -Mode "compose" -Repo $RepoRoot -Compose $ComposeFile
        $report.worker_mount_compose = $composeMount.report
        if ($composeMount.exit_code -ne 0 -or $composeMount.report.ok -ne $true) {
            $report.status = "failed"
            $report.named_blocker = "WORKER_REPO_MOUNT_MISMATCH"
            throw "worker compose mount preflight rejected provider invocation"
        }
        $dargs += @("--wait", "--wait-timeout", "120")
    }

    $report.docker_command = ("docker {0}" -f ($dargs -join " "))
    if (-not $Quiet) {
        Write-Host ("[Start-XinaoBaseCompose] {0}" -f $report.docker_command)
    }
    & docker @dargs
    $report.docker_exit_code = $LASTEXITCODE
    $composeFailed = ($LASTEXITCODE -ne 0)
    if ($composeFailed) {
        $report.status = "failed"
        $report.named_blocker = "DOCKER_COMPOSE_UP_FAILED"
        throw "docker compose up failed exit=$($report.docker_exit_code)"
    }

    $names = @(& docker ps --format "{{.Names}}" 2>$null)
    $report.temporal_ok = ($names -contains "naijiu-shiwu")
    $workerRunning = ($names -contains "houtai-gongren")
    if ($workerRunning) {
        $actualMount = Invoke-WorkerRepoMountPreflight -Mode "actual" -Repo $RepoRoot -Compose $ComposeFile
        $report.worker_mount_actual = $actualMount.report
        if ($actualMount.exit_code -ne 0 -or $actualMount.report.ok -ne $true) {
            $report.status = "failed"
            $report.named_blocker = "WORKER_REPO_MOUNT_MISMATCH"
            throw "running worker mount identity does not match current repo"
        }
        $workerState = (& docker inspect -f "{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" houtai-gongren 2>$null | Out-String).Trim()
        $report.worker_container_state = $workerState
        if ($workerState -eq "running/healthy") {
            $report.worker_ok = $true
        } else {
            $report.named_blocker = "WORKER_NOT_READY"
        }
    }
    try {
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { $report.temporal_ok = $true }
    } catch { }

    if ($report.temporal_ok -and $report.worker_ok) {
        $report.status = "running"
    }
    elseif ($report.temporal_ok) {
        $report.status = "partial"
        if ($composeFailed) {
            $report.named_blocker = "DOCKER_COMPOSE_UP_FAILED"
        } else {
            $report.named_blocker = if ($workerRunning) { "WORKER_NOT_READY" } else { "WORKER_NOT_UP" }
        }
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
    $report.status = "failed"
    if (-not $report.named_blocker) { $report.named_blocker = "START_EXCEPTION" }
    $report["error"] = $_.Exception.Message
    throw
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

if ($report.status -eq "running") { exit 0 }
exit 1
