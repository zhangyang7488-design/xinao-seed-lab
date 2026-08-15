[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Case
)

$ErrorActionPreference = 'Stop'
if ($Case -ne 'parent_frontier') {
    throw "unsupported PowerShell fixture case: $Case"
}

$statePath = Join-Path $PSScriptRoot 'parent_frontier\state.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not [bool]$state.source_restored) {
    Write-Output 'ACTION_PARENT_STATE_INVALID case=parent_frontier'
    exit 2
}
if (-not [bool]$state.consumer_verified) {
    Write-Output 'ACTION_PARENT_FRONTIER_OPEN case=parent_frontier settled=source_restore next=consumer_verification remaining=2'
    exit 2
}
if (-not [bool]$state.consumer_migrated) {
    Write-Output 'ACTION_PARENT_FRONTIER_OPEN case=parent_frontier settled=consumer_verification next=consumer_migration remaining=1'
    exit 2
}

Write-Output 'ACTION_CONSUMER_OK case=parent_frontier decision=repair settled=source_restore,consumer_verification,consumer_migration remaining=0'
exit 0
