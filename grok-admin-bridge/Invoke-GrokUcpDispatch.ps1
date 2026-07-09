[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Verb,
    [string]$Source = "grok-admin",
    [string]$PayloadJson = "{}",
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json")
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $config.ucp_python) -or -not (Test-Path -LiteralPath $config.ucp_script)) {
    throw "UCP_RUNTIME_MISSING"
}

& $config.ucp_python $config.ucp_script dispatch --source $Source --target $Target --verb $Verb --payload-json $PayloadJson
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }