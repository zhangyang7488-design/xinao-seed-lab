#Requires -Version 5.1
<#
.SYNOPSIS
  XINAO_Base V2 compose status thin shell.
.DESCRIPTION
  docker compose ps + core service table + Temporal health + worker evidence.
  Compatible with ClaimDurable: -RepoRoot / -RuntimeRoot emit JSON (worker_ready).
.EXAMPLE
  .\Status-XinaoBaseCompose.ps1
  .\Status-XinaoBaseCompose.ps1 -AsJson
  .\Status-XinaoBaseCompose.ps1 -RepoRoot E:\XINAO_RESEARCH_WORKSPACES\S -RuntimeRoot D:\XINAO_RESEARCH_RUNTIME
#>
[CmdletBinding()]
param(
    [string]$ComposeFile = "",
    [string]$RepoRoot = "",
    [string]$RuntimeRoot = "",
    [switch]$AsJson,
    [switch]$SkipTemporal,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false

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
if (-not $RuntimeRoot) {
    $RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
}

$emitJson = $AsJson -or ($PSBoundParameters.ContainsKey("RuntimeRoot") -or $PSBoundParameters.ContainsKey("RepoRoot"))

# Core services aligned with Start/Stop -CoreOnly (display_cn loaded from materials when present)
$coreServiceDefs = @(
    @{ service = "shiwu-ku";       container = "shiwu-ku";       display_cn = "shiwu-ku";       role_cn = "Temporal Postgres";     port = $null; required = $true },
    @{ service = "naijiu-shiwu";   container = "naijiu-shiwu";   display_cn = "naijiu-shiwu";   role_cn = "Temporal Server :7233"; port = 7233;  required = $true },
    @{ service = "shiwu-mianban";  container = "shiwu-mianban";  display_cn = "shiwu-mianban";  role_cn = "Temporal UI :8080";     port = 8080;  required = $true },
    @{ service = "houtai-gongren"; container = "houtai-gongren"; display_cn = "houtai-gongren"; role_cn = "Temporal Worker";      port = $null; required = $true }
)

$displayPath = Join-Path $RepoRoot "materials\xinao_compose_display_names.v1.json"
$displayMap = @{}
if (Test-Path -LiteralPath $displayPath -PathType Leaf) {
    try {
        $dn = Get-Content -LiteralPath $displayPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($prop in $dn.services.PSObject.Properties) {
            $displayMap[$prop.Name] = $prop.Value
        }
    } catch { }
}

$result = [ordered]@{
    schema_version           = "xinao.base_compose_status.v2"
    sentinel                 = "SENTINEL:XINAO_BASE_COMPOSE_STATUS"
    generated_at             = (Get-Date).ToString("o")
    compose_file             = $ComposeFile
    repo_root                = $RepoRoot
    runtime_root             = $RuntimeRoot
    compose_file_exists      = (Test-Path -LiteralPath $ComposeFile -PathType Leaf)
    docker_ok                = $false
    ps_exit_code             = $null
    services                 = @()
    core_service_table       = @()
    required_running         = [ordered]@{
        "shiwu-ku"       = $false
        "naijiu-shiwu"   = $false
        "shiwu-mianban"  = $false
        "houtai-gongren" = $false
    }
    core_ok                  = $false
    temporal_address         = "127.0.0.1:7233"
    temporal_tcp_ok          = $false
    temporal_health          = $null
    temporal_health_ok       = $false
    temporal_ok              = $false
    temporal_cli             = $null
    worker_ready             = $false
    worker_daemon_ok         = $false
    worker_container         = "houtai-gongren"
    worker_container_state   = ""
    daemon_status            = ""
    status                   = "unknown"
    ps_text_excerpt          = ""
    error                    = ""
    named_blocker            = $null
    completion_claim_allowed = $false
}

if (-not $result.compose_file_exists) {
    $result.error = "compose_file_missing"
    $result.status = "failed"
    $result.named_blocker = "COMPOSE_FILE_MISSING"
    $json = ($result | ConvertTo-Json -Depth 10)
    if ($emitJson) { Write-Output $json }
    else { Write-Error $result.error }
    exit 2
}

try {
    docker info 2>&1 | Out-Null
    $result.docker_ok = ($LASTEXITCODE -eq 0)
} catch {
    $result.error = "docker_unavailable: $($_.Exception.Message)"
    $result.docker_ok = $false
    $result.named_blocker = "DOCKER_UNAVAILABLE"
}

$workDir = Split-Path $ComposeFile -Parent
Push-Location $workDir
try {
    if ($result.docker_ok) {
        $psText = & docker compose -f $ComposeFile ps 2>&1 | Out-String
        $result.ps_exit_code = $LASTEXITCODE
        if ($psText.Length -gt 4000) {
            $result.ps_text_excerpt = $psText.Substring(0, 4000) + "..."
        } else {
            $result.ps_text_excerpt = $psText.TrimEnd()
        }
        if (-not $Quiet -and -not $emitJson) {
            Write-Output $psText.TrimEnd()
        }

        $namesRunning = @(& docker ps --format "{{.Names}}" 2>$null)
        $namesAll = @(& docker ps -a --format "{{.Names}}" 2>$null)

        $svcList = @()
        foreach ($n in $namesRunning) {
            $inspectFmt = "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.Config.Image}}"
            $raw = (& docker inspect -f $inspectFmt $n 2>$null | Out-String).Trim()
            $parts = $raw -split "\|", 3
            $st = if ($parts.Count -ge 1) { $parts[0] } else { "unknown" }
            $health = if ($parts.Count -ge 2) { $parts[1] } else { "none" }
            $image = if ($parts.Count -ge 3) { $parts[2] } else { "" }
            $svcList += ,[ordered]@{
                name    = $n
                service = $n
                state   = $st
                health  = $health
                status  = $st
                image   = $image
            }
        }
        $result["services"] = @($svcList)

        $coreTable = @()
        foreach ($def in $coreServiceDefs) {
            $svc = [string]$def.service
            $ctr = [string]$def.container
            $display = [string]$def.display_cn
            $role = [string]$def.role_cn
            if ($displayMap.ContainsKey($svc)) {
                if ($displayMap[$svc].display_cn) { $display = [string]$displayMap[$svc].display_cn }
                if ($displayMap[$svc].role_cn) { $role = [string]$displayMap[$svc].role_cn }
            }

            $exists = ($namesAll -contains $ctr)
            $running = ($namesRunning -contains $ctr)
            $state = "absent"
            $health = "none"
            if ($exists) {
                $raw2 = (& docker inspect -f "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $ctr 2>$null | Out-String).Trim()
                $p2 = $raw2 -split "\|", 2
                $state = if ($p2.Count -ge 1 -and $p2[0]) { $p2[0] } else { "unknown" }
                $health = if ($p2.Count -ge 2) { $p2[1] } else { "none" }
            }

            $portOk = $null
            if ($null -ne $def.port) {
                try {
                    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port ([int]$def.port) -WarningAction SilentlyContinue
                    $portOk = [bool]$tcp.TcpTestSucceeded
                } catch { $portOk = $false }
            }

            $rowOk = $false
            if ($running -and $state -eq "running") {
                if ($health -eq "none" -or $health -eq "healthy" -or $health -eq "") {
                    $rowOk = $true
                }
            }

            if ($result.required_running.Contains($svc)) {
                $result.required_running[$svc] = [bool]$running
            }

            $row = [ordered]@{
                service    = $svc
                container  = $ctr
                display_cn = $display
                role_cn    = $role
                required   = [bool]$def.required
                exists     = [bool]$exists
                running    = [bool]$running
                state      = $state
                health     = $health
                port       = $def.port
                port_ok    = $portOk
                ok         = [bool]$rowOk
            }
            $coreTable += ,$row
        }
        $result["core_service_table"] = @($coreTable)

        $result["core_ok"] = [bool](
            $result.required_running["shiwu-ku"] -and
            $result.required_running["naijiu-shiwu"] -and
            $result.required_running["houtai-gongren"]
        )

        $wc = "houtai-gongren"
        if ($namesRunning -contains $wc -or $namesAll -contains $wc) {
            $st = (& docker inspect -f "{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $wc 2>$null | Out-String).Trim()
            $result.worker_container_state = $st
            if ($st -match "running") { $result.worker_ready = $true }
        }

        if (-not $Quiet -and -not $emitJson) {
            Write-Output ""
            Write-Output "=== core_service_table ==="
            Write-Output ("{0,-16} {1,-10} {2,-10} {3,-12} {4,-8} {5}" -f "service", "state", "health", "port_ok", "ok", "display_cn")
            Write-Output ("{0,-16} {1,-10} {2,-10} {3,-12} {4,-8} {5}" -f "-------", "-----", "------", "-------", "--", "----------")
            foreach ($r in $coreTable) {
                if ($null -eq $r.port) {
                    $pStr = "-"
                } elseif ($null -eq $r.port_ok) {
                    $pStr = "n/a"
                } elseif ($r.port_ok) {
                    $pStr = "yes:$($r.port)"
                } else {
                    $pStr = "no:$($r.port)"
                }
                Write-Output ("{0,-16} {1,-10} {2,-10} {3,-12} {4,-8} {5}" -f $r.service, $r.state, $r.health, $pStr, $r.ok, $r.display_cn)
            }
        }
    }

    if (-not $SkipTemporal) {
        try {
            $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue
            $result.temporal_tcp_ok = [bool]$tcp.TcpTestSucceeded
            $result.temporal_ok = $result.temporal_tcp_ok
        } catch {
            $result.temporal_tcp_ok = $false
            $result.temporal_ok = $false
        }

        $temporalCli = $null
        $candidates = @(
            (Join-Path $RuntimeRoot "tools\temporal\bin\temporal.exe"),
            "D:\XINAO_RESEARCH_RUNTIME\tools\temporal\bin\temporal.exe",
            "temporal"
        )
        foreach ($c in $candidates) {
            if ($c -eq "temporal") {
                $cmd = Get-Command temporal -ErrorAction SilentlyContinue
                if ($cmd) { $temporalCli = [string]$cmd.Source; break }
            } elseif (Test-Path -LiteralPath $c -PathType Leaf) {
                $temporalCli = $c
                break
            }
        }
        $result.temporal_cli = $temporalCli
        if ($temporalCli) {
            try {
                $h = & $temporalCli operator cluster health --address 127.0.0.1:7233 2>&1 | Out-String
                $result.temporal_health = $h.Trim()
                $result.temporal_health_ok = ($h -match "SERVING")
                if ($result.temporal_health_ok) { $result.temporal_ok = $true }
                if (-not $Quiet -and -not $emitJson) {
                    Write-Output ""
                    Write-Output ("=== Temporal health ({0}) ===" -f $result.temporal_address)
                    Write-Output ("cli: {0}" -f $temporalCli)
                    Write-Output ("tcp_ok={0} health_ok={1}" -f $result.temporal_tcp_ok, $result.temporal_health_ok)
                    Write-Output $result.temporal_health
                }
            } catch {
                $result.temporal_health = $_.Exception.Message
                $result.temporal_health_ok = $false
            }
        } else {
            $result.temporal_health = "temporal_cli_missing"
            $result.temporal_health_ok = $false
            if ($result.temporal_tcp_ok -and $result.required_running["naijiu-shiwu"]) {
                $result.temporal_ok = $true
            }
            if (-not $Quiet -and -not $emitJson) {
                Write-Output ""
                Write-Output "=== Temporal health ==="
                Write-Output ("temporal_cli_missing; fallback tcp_ok={0}" -f $result.temporal_tcp_ok)
            }
        }
    }

    $daemonPath = Join-Path $RuntimeRoot "state\integrated_bus_worker_daemon\latest.json"
    if (Test-Path -LiteralPath $daemonPath -PathType Leaf) {
        try {
            $dj = Get-Content -LiteralPath $daemonPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $result.daemon_status = [string]$dj.status
            if ($dj.status -eq "polling") {
                $result.worker_daemon_ok = $true
                $result.worker_ready = $true
            }
        } catch { }
    }
}
finally {
    Pop-Location
}

if (-not $result.docker_ok) {
    $result.status = "failed"
    if (-not $result.named_blocker) { $result.named_blocker = "DOCKER_UNAVAILABLE" }
} elseif ($result.core_ok -and $result.temporal_ok) {
    $result.status = "running"
} elseif ($result.temporal_ok -or $result.required_running["naijiu-shiwu"]) {
    $result.status = "partial"
    if (-not $result.named_blocker) {
        if (-not $result.required_running["houtai-gongren"]) {
            $result.named_blocker = "WORKER_NOT_UP"
        } else {
            $result.named_blocker = "CORE_PARTIAL"
        }
    }
} else {
    $result.status = "degraded"
    if (-not $result.named_blocker) { $result.named_blocker = "TEMPORAL_NOT_UP" }
}

try {
    $evDir = Join-Path $RuntimeRoot "state\xinao_base_compose"
    New-Item -ItemType Directory -Force -Path $evDir | Out-Null
    $statusEv = [ordered]@{
        schema_version           = $result.schema_version
        generated_at             = $result.generated_at
        status                   = $result.status
        temporal_ok              = $result.temporal_ok
        temporal_tcp_ok          = $result.temporal_tcp_ok
        temporal_health_ok       = $result.temporal_health_ok
        temporal_health          = $result.temporal_health
        worker_ready             = $result.worker_ready
        worker_daemon_ok         = $result.worker_daemon_ok
        core_ok                  = $result.core_ok
        required_running         = $result.required_running
        core_service_table       = $result.core_service_table
        named_blocker            = $result.named_blocker
        completion_claim_allowed = $false
    }
    [System.IO.File]::WriteAllText((Join-Path $evDir "status_latest.json"), ($statusEv | ConvertTo-Json -Depth 10), $utf8)
} catch { }

$jsonOut = ($result | ConvertTo-Json -Depth 12)
if ($emitJson) {
    Write-Output $jsonOut
} elseif (-not $Quiet) {
    Write-Output ""
    Write-Output ("status={0} core_ok={1} temporal_ok={2} temporal_health_ok={3} worker_ready={4} worker_daemon_ok={5}" -f `
        $result.status, $result.core_ok, $result.temporal_ok, $result.temporal_health_ok, $result.worker_ready, $result.worker_daemon_ok)
    $reqBits = @()
    foreach ($k in $result.required_running.Keys) {
        $reqBits += ("{0}={1}" -f $k, $result.required_running[$k])
    }
    Write-Output ("required: {0}" -f ($reqBits -join ", "))
    Write-Output "completion_claim_allowed=false"
}

if ($result.docker_ok -and $result.core_ok -and $result.temporal_ok) { exit 0 }
if ($result.docker_ok) { exit 1 }
exit 2