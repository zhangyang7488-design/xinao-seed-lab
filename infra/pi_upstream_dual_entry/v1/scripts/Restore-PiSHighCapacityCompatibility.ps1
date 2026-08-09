#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AgentDir,
    [Parameter(Mandatory)][string]$PiToolRoot,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
$applyScript = Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1'
if (-not (Test-Path -LiteralPath $applyScript -PathType Leaf)) {
    throw "PI_S_HIGH_CAPACITY_RESTORE_APPLY_SCRIPT_MISSING: $applyScript"
}
& $applyScript -AgentDir $AgentDir -PiToolRoot $PiToolRoot -VerifyOnly:$VerifyOnly -InternalRestore
