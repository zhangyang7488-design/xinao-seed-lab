#Requires -Version 5.1
<#
.SYNOPSIS
  Grok 岛能力最大化一键建设 — 按用户拍板执行；证据写 D 盘。
.NOT_333_MAINLINE
#>
param(
    [switch]$SkipDocker,
    [switch]$SkipClone,
    [switch]$SkipMem0,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8

$bridge = $PSScriptRoot
$evidenceDir = "D:\XINAO_RESEARCH_RUNTIME\state\grok_capability_maximize"
$latestPath = Join-Path $evidenceDir "latest.json"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$userDecisions = [ordered]@{
    docker_overnight = "yes_full"
    mem0_bind        = "docker_d"
    mcp_expand       = "fs_fetch_memory"
    clone_gaps       = "all_missing"
    ingress_overnight = "skip"
    large_optional   = "skip_all"
}

$steps = [System.Collections.Generic.List[object]]::new()

function Add-Step([string]$Id, [string]$Status, [hashtable]$Extra = @{}) {
    $s = [ordered]@{ id = $Id; status = $Status; at = (Get-Date).ToString("o") }
    foreach ($k in $Extra.Keys) { $s[$k] = $Extra[$k] }
    $steps.Add([pscustomobject]$s) | Out-Null
}

# 1) Bootstrap long workflow
try {
    & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
    Add-Step "long_workflow_bootstrap" "done"
} catch {
    Add-Step "long_workflow_bootstrap" "failed" @{ error = $_.Exception.Message }
}

# 2) Registry scan
try {
    & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
    Add-Step "registry_scan" "done"
} catch {
    Add-Step "registry_scan" "failed" @{ error = $_.Exception.Message }
}

# 3) Docker + thin glue
$dockerOk = $false
if (-not $SkipDocker) {
    try {
        docker info 2>&1 | Out-Null
        $dockerOk = ($LASTEXITCODE -eq 0)
        if (-not $dockerOk) {
            $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
            if (Test-Path $dd) {
                Start-Process -FilePath $dd -ErrorAction SilentlyContinue
                $deadline = (Get-Date).AddMinutes(4)
                do {
                    Start-Sleep -Seconds 8
                    docker info 2>&1 | Out-Null
                    $dockerOk = ($LASTEXITCODE -eq 0)
                } while (-not $dockerOk -and (Get-Date) -lt $deadline)
            }
        }
        if ($dockerOk) {
            $thinStart = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Start-XinaoThinGlueStack.ps1"
            if (Test-Path $thinStart) {
                & $thinStart 2>&1 | Out-Null
                Start-Sleep -Seconds 15
                try {
                    $lk = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }
                    $r = Invoke-WebRequest -Uri "http://127.0.0.1:20128/v1/models" -Headers @{ Authorization = "Bearer $lk" } -UseBasicParsing -TimeoutSec 10
                    Add-Step "thin_glue_litellm" "done" @{ status = $r.StatusCode }
                } catch {
                    Add-Step "thin_glue_litellm" "partial" @{ error = $_.Exception.Message }
                }
            }
        } else {
            Add-Step "docker_start" "blocked" @{ blocker = "DOCKER_DAEMON_NOT_RUNNING" }
        }
    } catch {
        Add-Step "docker_start" "failed" @{ error = $_.Exception.Message }
    }
}

# 4) Mem0 on D hot path
if (-not $SkipMem0 -and $dockerOk) {
    $mem0Dir = "D:\XINAO_RESEARCH_RUNTIME\tools\mem0"
    $compose = Join-Path $mem0Dir "docker-compose.yml"
    if (Test-Path $compose) {
        try {
            Push-Location $mem0Dir
            docker compose up -d 2>&1 | Out-Null
            Add-Step "mem0_compose" $(if ($LASTEXITCODE -eq 0) { "done" } else { "failed" })
            Pop-Location
        } catch {
            Add-Step "mem0_compose" "failed" @{ error = $_.Exception.Message }
        }
    } else {
        Add-Step "mem0_compose" "skipped" @{ reason = "compose_not_found" }
    }
}

# 5) Glue registry gap fill (all missing, skip 接线暂缓 handled by script default)
if (-not $SkipClone) {
    try {
        & (Join-Path $bridge "Invoke-XinaoGlueRegistryGapFill.ps1") 2>&1 | Out-Null
        Add-Step "glue_gap_fill" "done"
    } catch {
        Add-Step "glue_gap_fill" "failed" @{ error = $_.Exception.Message }
    }
}

# 6) Probes snapshot
function Test-Http([string]$Url, [string]$BearerToken = $null) {
    try {
        $params = @{ Uri = $Url; UseBasicParsing = $true; TimeoutSec = 5 }
        if ($BearerToken) { $params.Headers = @{ Authorization = "Bearer $BearerToken" } }
        $r = Invoke-WebRequest @params
        return [ordered]@{ ok = $true; status = $r.StatusCode }
    } catch {
        return [ordered]@{ ok = $false; error = $_.Exception.Message }
    }
}

$litellmKey = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }

$report = [ordered]@{
    schema_version  = "xinao.grok_capability_maximize.v1"
    sentinel        = "SENTINEL:GROK_CAPABILITY_MAXIMIZE"
    generated_at    = (Get-Date).ToString("o")
    user_decisions  = $userDecisions
    steps           = $steps
    probes          = [ordered]@{
        litellm_20128 = Test-Http "http://127.0.0.1:20128/v1/models" $litellmKey
        ollama_11434  = Test-Http "http://127.0.0.1:11434"
        mem0_qdrant   = Test-Http "http://127.0.0.1:6333"
        mem0_mcp      = Test-Http "http://127.0.0.1:8765"
    }
    mcp_config      = (Join-Path $bridge "..\.grok\config.toml")
    not_333_mainline = $true
}

($report | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $latestPath -Encoding UTF8
if (-not $Quiet) { $report | ConvertTo-Json -Depth 6 }
exit 0