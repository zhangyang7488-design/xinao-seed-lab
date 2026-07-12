#Requires -Version 5.1
<#
.SYNOPSIS
  Dual-brain TUI role environment (thin shell; no second orchestrator).
.DESCRIPTION
  Pins AMQ + coordination identity for the product dialogue pair:
    Grok 4.5.lnk  <->  OPEN CODEX S HARDMODE.lnk
  Admin = worker only (can set role, not dialogue default peer).
  Mature carrier: external AMQ + dual-brain kernel paths from construction package.
.PARAMETER Role
  grok_4_5 | codex | admin
.EXAMPLE
  . .\Set-XinaoDualBrainRoleEnv.ps1 -Role grok_4_5
  . .\Set-XinaoDualBrainRoleEnv.ps1 -Role codex
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("grok_4_5", "codex", "admin")]
    [string]$Role,

    [string]$AmqRoot = "D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq",
    [string]$KernelDb = "D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3",
    [string]$AmqBin = "D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe",
    [string]$CoordRepo = "E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$handleMap = @{
    grok_4_5 = "grok"
    codex    = "codex"
    admin    = "admin"
}
$me = $handleMap[$Role]

# Ensure production AMQ layout exists (idempotent)
if (Test-Path -LiteralPath $AmqBin -PathType Leaf) {
    if (-not (Test-Path -LiteralPath (Join-Path $AmqRoot "agents\$me") -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $AmqRoot | Out-Null
        & $AmqBin init --root $AmqRoot --agents "grok,codex,admin,user" 2>$null | Out-Null
    }
}

$env:XINAO_COORD_ROLE = $Role
$env:AM_ME = $me
$env:AM_ROOT = $AmqRoot
$env:XINAO_AMQ_BIN = $AmqBin
$env:XINAO_DUAL_BRAIN_DB = $KernelDb
$env:XINAO_DUAL_BRAIN_REPO = $CoordRepo
$env:XINAO_RESEARCH_RUNTIME = "D:\XINAO_RESEARCH_RUNTIME"

# Dialogue pair hard nail (for agents reading env / evidence)
$env:XINAO_DUAL_BRAIN_DIALOGUE_LEFT = "Grok 4.5.lnk / grok / grok_4_5"
$env:XINAO_DUAL_BRAIN_DIALOGUE_RIGHT = "OPEN CODEX S HARDMODE.lnk / codex"
$env:XINAO_DUAL_BRAIN_NOT_DIALOGUE_PEER = "Grok Admin Isolated / admin (worker only)"

# Per-turn drain discipline (not a daemon; agent/hook must invoke)
$env:XINAO_DUAL_BRAIN_TURN_DRAIN = "1"
$adapterRoot = Split-Path -Parent $PSScriptRoot
$env:XINAO_DUAL_BRAIN_TURN_DRAIN_PS1 = Join-Path $adapterRoot "amq\Invoke-XinaoAmqInboxBridge.ps1"

if ($Role -eq "admin") {
    $env:XINAO_DUAL_BRAIN_CAN_DISCUSS = "0"
    $env:XINAO_DUAL_BRAIN_CAN_CLAIM_TASK = "1"
} else {
    $env:XINAO_DUAL_BRAIN_CAN_DISCUSS = "1"
    $env:XINAO_DUAL_BRAIN_CAN_CLAIM_TASK = "0"
}

if (-not $Quiet) {
    Write-Host "DUAL_BRAIN_ROLE role=$Role AM_ME=$me AM_ROOT=$AmqRoot" -ForegroundColor Cyan
    if ($Role -eq "admin") {
        Write-Host "NOTE: admin is worker only — not dual-brain dialogue peer" -ForegroundColor Yellow
    } else {
        Write-Host "Dialogue pair: Grok 4.5 <-> Codex S Hardmode (not Admin)" -ForegroundColor DarkGray
        Write-Host "TURN_DRAIN: invoke InboxBridge -Action Drain -Role $Role (canonical amq-ingest -> kernel)" -ForegroundColor DarkCyan
    }
}

# Machine-readable one-liner for launchers / evidence
[pscustomobject]@{
    ok                = $true
    role              = $Role
    am_me             = $me
    am_root           = $AmqRoot
    kernel_db         = $KernelDb
    can_discuss       = ($Role -ne "admin")
    dialogue_peer_cn  = "Grok4.5_and_CodexS_only"
    not_dialogue_peer = "admin"
} | ConvertTo-Json -Compress
