# Shared UTF-8 bridge.config.json reader for Grok Admin Bridge scripts.
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "GROK_BRIDGE_CONFIG_MISSING: $ConfigPath"
}

Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json