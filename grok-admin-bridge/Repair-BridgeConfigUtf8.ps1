# One-shot: ensure bridge.config.json is valid UTF-8 with BOM for Windows PowerShell.
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json")
)

$ErrorActionPreference = "Stop"
$raw = [System.IO.File]::ReadAllText($ConfigPath, [System.Text.UTF8Encoding]::new($false))
$null = $raw | ConvertFrom-Json
$utf8Bom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($ConfigPath, $raw, $utf8Bom)
Write-Output "SENTINEL:BRIDGE_CONFIG_UTF8_BOM_OK"