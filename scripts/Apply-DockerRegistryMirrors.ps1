# Apply durable Docker Hub registry mirrors for Docker Desktop (Windows).
# Config: user Docker state (C thin entry). Does not change compose topology.

[CmdletBinding()]
param(
    [string[]]$Mirrors = @(
        'https://docker.m.daocloud.io',
        'https://docker.1ms.run'
    ),
    [switch]$RestartDesktop,
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
$daemonPath = Join-Path $env:USERPROFILE '.docker\daemon.json'
$backupDir = 'D:\XINAO_RESEARCH_RUNTIME\state\docker_registry_mirrors'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $daemonPath) | Out-Null

$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$cfg = @{
    builder = @{
        gc = @{
            defaultKeepStorage = '20GB'
            enabled = $true
        }
    }
    experimental = $false
    'registry-mirrors' = @($Mirrors)
}

if (Test-Path $daemonPath) {
    $bak = Join-Path $backupDir ("daemon.json.bak." + $ts)
    Copy-Item -LiteralPath $daemonPath -Destination $bak -Force
    try {
        $existing = Get-Content -LiteralPath $daemonPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($existing.builder) {
            $cfg.builder = $existing.builder
        }
        if ($null -ne $existing.experimental) {
            $cfg.experimental = [bool]$existing.experimental
        }
        foreach ($prop in $existing.PSObject.Properties) {
            if ($prop.Name -notin @('builder', 'experimental', 'registry-mirrors')) {
                $cfg[$prop.Name] = $prop.Value
            }
        }
    } catch {
        Write-Warning ("Could not merge existing daemon.json; writing mirrors with defaults. " + $_)
    }
}

$json = $cfg | ConvertTo-Json -Depth 8
Write-Host ("Target: " + $daemonPath)
Write-Host $json
if ($WhatIf) {
    Write-Host 'WhatIf: not writing.'
    return
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($daemonPath, $json + "`n", $utf8NoBom)
$appliedPath = Join-Path $backupDir ("daemon.json.applied." + $ts)
[System.IO.File]::WriteAllText($appliedPath, $json + "`n", $utf8NoBom)

$evidence = @{
    schema_version = 'xinao.docker_registry_mirrors.v1'
    applied_at = (Get-Date).ToString('o')
    daemon_path = $daemonPath
    mirrors = $Mirrors
    restart_requested = [bool]$RestartDesktop
    note_cn = 'Docker Desktop must reload daemon for mirrors; compose defaults unchanged.'
}
$latestPath = Join-Path $backupDir 'latest.json'
$evidence | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $latestPath -Encoding utf8

if ($RestartDesktop) {
    Write-Host 'Restarting Docker Desktop...'
    Get-Process -Name 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 4
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Docker\Docker\Docker Desktop.exe')
    )
    $dd = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $dd) {
        throw 'Docker Desktop.exe not found'
    }
    Start-Process -FilePath $dd
    Write-Host 'Docker Desktop start issued; wait for engine healthy then check mirrors.'
}

Write-Host ("Backup/evidence: " + $backupDir)
Write-Host 'Verify: docker info  (look for Registry Mirrors)'
