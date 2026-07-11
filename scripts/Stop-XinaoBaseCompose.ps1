#Requires -Version 5.1
<#
.SYNOPSIS
  XINAO_Base V2 compose stop thin shell.
.DESCRIPTION
  Default SAFE: docker compose stop (keeps containers + volumes).
  -CoreOnly: stop only core services.
  -Down: docker compose down (volumes still kept by default).
  -RemoveVolumes: only with -Down adds -v (dangerous).
  Never default down -v.
.EXAMPLE
  .\Stop-XinaoBaseCompose.ps1
  .\Stop-XinaoBaseCompose.ps1 -CoreOnly
  .\Stop-XinaoBaseCompose.ps1 -Down
  .\Stop-XinaoBaseCompose.ps1 -Down -RemoveVolumes
#>
[CmdletBinding()]
param(
    [string]$ComposeFile = "",
    [string]$RepoRoot = "",
    [string]$RuntimeRoot = "",
    [switch]$CoreOnly,
    [switch]$Down,
    [switch]$RemoveVolumes,
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

if ($RemoveVolumes -and -not $Down) {
    throw "Refuse: -RemoveVolumes requires -Down. Default stop never removes volumes."
}

$mode = if ($Down) { "down" } else { "stop" }
$report = [ordered]@{
    schema_version           = "xinao.base_compose_stop.v2"
    sentinel                 = "SENTINEL:XINAO_BASE_COMPOSE_STOP"
    generated_at             = (Get-Date).ToString("o")
    compose_file             = $ComposeFile
    repo_root                = $RepoRoot
    runtime_root             = $RuntimeRoot
    mode                     = $mode
    core_only                = [bool]$CoreOnly
    core_services            = @($script:CoreServices)
    down                     = [bool]$Down
    remove_volumes           = [bool]$RemoveVolumes
    services_targeted        = @()
    status                   = "unknown"
    docker_exit_code         = $null
    docker_command           = ""
    named_blocker            = $null
    completion_claim_allowed = $false
    safety_note              = "default=compose stop; down requires -Down; -v requires -Down -RemoveVolumes"
}

$workDir = Split-Path $ComposeFile -Parent
Push-Location $workDir
try {
    $dargs = @("compose", "-f", $ComposeFile)
    foreach ($p in $Profile) {
        if ($p) { $dargs += @("--profile", $p) }
    }

    $targets = @()
    if ($Service -and $Service.Count -gt 0) {
        $targets = @($Service | Where-Object { $_ })
    }
    elseif ($CoreOnly) {
        $targets = @($script:CoreServices)
    }

    if ($Down) {
        if ($CoreOnly -or ($Service -and $Service.Count -gt 0)) {
            # compose down is project-wide; scoped request falls back to stop targets
            $report["down_scope_note"] = "compose down is project-wide; CoreOnly/Service + Down fell back to stop targets (no project down, no -v)"
            $dargs = @("compose", "-f", $ComposeFile)
            foreach ($p in $Profile) {
                if ($p) { $dargs += @("--profile", $p) }
            }
            $dargs += @("stop") + $targets
            $report.mode = "stop_fallback_from_down_scoped"
            $report.remove_volumes = $false
            $report.services_targeted = $targets
        } else {
            $dargs += "down"
            if ($RemoveVolumes) {
                $dargs += "-v"
                $report.safety_note = "explicit -Down -RemoveVolumes: volumes will be deleted"
            }
        }
    }
    else {
        $dargs += "stop"
        if ($targets.Count -gt 0) {
            $dargs += $targets
            $report.services_targeted = $targets
        }
    }

    $report.docker_command = ("docker {0}" -f ($dargs -join " "))
    if (-not $Quiet) {
        Write-Host ("[Stop-XinaoBaseCompose] {0}" -f $report.docker_command)
        if ($RemoveVolumes -and $Down -and $report.mode -eq "down") {
            Write-Warning "RemoveVolumes=true: volumes will be deleted"
        }
    }
    & docker @dargs
    $report.docker_exit_code = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) {
        $report.status = "failed"
        if ($Down -and $report.mode -eq "down") {
            $report.named_blocker = "DOCKER_COMPOSE_DOWN_FAILED"
        } else {
            $report.named_blocker = "DOCKER_COMPOSE_STOP_FAILED"
        }
        throw "docker compose $($report.mode) failed exit=$LASTEXITCODE"
    }
    if ($report.mode -eq "down") {
        $report.status = "down"
    } else {
        $report.status = "stopped"
    }
}
catch {
    if ($report.status -eq "unknown") {
        $report.status = "failed"
        $report.named_blocker = "STOP_EXCEPTION"
    }
    $report["error"] = $_.Exception.Message
    throw
}
finally {
    Pop-Location
    $evDir = Join-Path $RuntimeRoot "state\xinao_base_compose"
    New-Item -ItemType Directory -Force -Path $evDir | Out-Null
    $json = ($report | ConvertTo-Json -Depth 6)
    [System.IO.File]::WriteAllText((Join-Path $evDir "stop_latest.json"), $json, $utf8)
    if ($AsJson) { Write-Output $json }
    elseif (-not $Quiet) {
        Write-Output ("status={0} mode={1} remove_volumes={2} completion_claim_allowed=false" -f `
            $report.status, $report.mode, $report.remove_volumes)
    }
}

exit 0