#Requires -Version 5.1
<#
.SYNOPSIS
  XINAO_Base V2 compose start thin shell.
.DESCRIPTION
  docker compose -f S\docker-compose.yml up -d
  Bare start and -CoreOnly: shiwu-ku / naijiu-shiwu / shiwu-mianban
  Optional -Profile worker / gateway / search / ollama / -Build
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
$script:CoreServices = @("shiwu-ku", "naijiu-shiwu", "shiwu-mianban")

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

function Test-ComposeEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Directory
    )
    $processValue = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $true
    }
    $envPath = Join-Path $Directory ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        return $false
    }
    foreach ($line in [IO.File]::ReadAllLines($envPath, [Text.UTF8Encoding]::new($false))) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -notmatch '^(?:export\s+)?(?<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.*)$') { continue }
        if ($Matches.name -ine $Name) { continue }
        $value = $Matches.value.Trim()
        if ($value.Length -ge 2) {
            $first = $value[0]
            $last = $value[$value.Length - 1]
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        return -not [string]::IsNullOrWhiteSpace($value)
    }
    return $false
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
    core_ok                  = $false
    status                   = "unknown"
    temporal_ok              = $false
    worker_targeted          = $false
    gateway_targeted         = $false
    litellm_key_required     = $false
    litellm_key_available    = $false
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

    $workerTargeted = (
        $targets -contains "houtai-gongren" -or
        ($targets.Count -eq 0 -and $Profile -contains "worker")
    )
    $report.worker_targeted = [bool]$workerTargeted
    $gatewayTargeted = (
        $targets -contains "moxing-wangguan" -or
        ($targets.Count -eq 0 -and $Profile -contains "gateway")
    )
    $report.gateway_targeted = [bool]$gatewayTargeted
    $litellmKeyRequired = $gatewayTargeted
    $report.litellm_key_required = [bool]$litellmKeyRequired
    if ($litellmKeyRequired) {
        $report.litellm_key_available = [bool](
            Test-ComposeEnvironmentValue -Name "LITELLM_MASTER_KEY" -Directory $workDir
        )
        if (-not $report.litellm_key_available) {
            $report.status = "failed"
            $report.named_blocker = "LITELLM_MASTER_KEY_MISSING"
            throw "gateway profile requires LITELLM_MASTER_KEY in the process environment or .env"
        }
    }
    if ($workerTargeted) {
        $composeMount = Invoke-WorkerRepoMountPreflight -Mode "compose" -Repo $RepoRoot -Compose $ComposeFile
        $report.worker_mount_compose = $composeMount.report
        if ($composeMount.exit_code -ne 0 -or $composeMount.report.ok -ne $true) {
            $report.status = "failed"
            $report.named_blocker = "WORKER_REPO_MOUNT_MISMATCH"
            throw "worker compose mount preflight rejected provider invocation"
        }
    }
    $dargs += @("--wait", "--wait-timeout", "120")

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

    $names = @(& docker ps --format "{{.Names}}" --filter "label=com.docker.compose.project=xinao-base" 2>$null)
    $report.core_ok = [bool](
        @($script:CoreServices | Where-Object { $names -contains $_ }).Count -eq
        $script:CoreServices.Count
    )
    $report.temporal_ok = ($names -contains "naijiu-shiwu")
    $workerRunning = ($names -contains "houtai-gongren")
    if ($workerTargeted -and $workerRunning) {
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

    if ($report.core_ok -and $report.temporal_ok -and (-not $workerTargeted -or $report.worker_ok)) {
        $report.status = "running"
    }
    elseif ($report.temporal_ok -or $report.core_ok) {
        $report.status = "partial"
        if ($composeFailed) {
            $report.named_blocker = "DOCKER_COMPOSE_UP_FAILED"
        } elseif ($workerTargeted -and -not $workerRunning) {
            $report.named_blocker = "WORKER_NOT_UP"
        } elseif ($workerTargeted -and -not $report.worker_ok) {
            $report.named_blocker = "WORKER_NOT_READY"
        } else {
            $report.named_blocker = "CORE_PARTIAL"
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
