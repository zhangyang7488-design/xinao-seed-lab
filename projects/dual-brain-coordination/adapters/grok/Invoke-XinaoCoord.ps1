#Requires -Version 7.2
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '..\..'),

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CoordArgs = @()
)

$ErrorActionPreference = 'Stop'
$launcher = Join-Path $ProjectRoot 'provisioning\Invoke-XinaoCoordManaged.ps1'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "XINAO_COORD_MANAGED_LAUNCHER_MISSING: $launcher"
}

& $launcher -Target cli -TargetArgs $CoordArgs
exit $LASTEXITCODE
