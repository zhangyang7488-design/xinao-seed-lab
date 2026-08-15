[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Case
)

$ErrorActionPreference = 'Stop'
if ($Case -ne 'parent_frontier') {
    throw "unsupported PowerShell fixture case: $Case"
}

$root = Join-Path $PSScriptRoot 'parent_frontier'
$statePath = Join-Path $root 'state.json'
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if (-not [bool]$state.source_restored) {
    throw 'source restoration is the settled parent precondition'
}
if (-not [bool]$state.consumer_verified) {
    $state.consumer_verified = $true
    $step = 'consumer_verification'
}
elseif (-not [bool]$state.consumer_migrated) {
    $state.consumer_migrated = $true
    $step = 'consumer_migration'
}
else {
    throw 'parent frontier is already complete'
}

$serialized = ($state | ConvertTo-Json -Depth 4) + "`n"
[IO.File]::WriteAllText($statePath, $serialized, [Text.UTF8Encoding]::new($false))
$markerPath = Join-Path $root 'repair.marker'
[IO.File]::WriteAllText(
    $markerPath,
    "parent_frontier_advanced=$step`n",
    [Text.UTF8Encoding]::new($false)
)
Write-Output "ACTION_REPAIR_APPLIED case=parent_frontier step=$step"
