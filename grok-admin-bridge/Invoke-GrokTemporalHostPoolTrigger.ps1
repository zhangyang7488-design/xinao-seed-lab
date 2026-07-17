#Requires -Version 5.1
<#
.SYNOPSIS
  Short alias for Invoke-GrokHostWorkerPoolFromTemporal.ps1
.DESCRIPTION
  Same Host-only Grok WorkerPool trigger (Temporal Activity semantics).
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 1,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "",
    [string]$SelectionPath = "",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$WorkflowId = "",
    [string]$RunId = "",
    [string]$ActivityName = "trigger_host_grok_worker_pool",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$target = Join-Path $PSScriptRoot "Invoke-GrokHostWorkerPoolFromTemporal.ps1"
if (-not (Test-Path -LiteralPath $target)) {
    throw "MISSING: $target"
}

$args = @{
    N = $N
    Model = $Model
    SelectionPath = $SelectionPath
    MaxTurns = $MaxTurns
    TimeoutSec = $TimeoutSec
    GrokHome = $GrokHome
    ActivityName = $ActivityName
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
}
if ($RequireJsonObject) { $args.RequireJsonObject = $true }
if ($JsonSchemaPath) { $args.JsonSchemaPath = $JsonSchemaPath }
if ($Prompt) { $args.Prompt = $Prompt }
if ($PromptFile) { $args.PromptFile = $PromptFile }
$args.Cwd = $Cwd
if ($WorkflowId) { $args.WorkflowId = $WorkflowId }
if ($RunId) { $args.RunId = $RunId }
if ($SkipPauseGate) { $args.SkipPauseGate = $true }
if ($Quiet) { $args.Quiet = $true }

& $target @args
exit $LASTEXITCODE
