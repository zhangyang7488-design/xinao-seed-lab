#Requires -Version 5.1
[CmdletBinding()]
param([switch]$PrepareOnly)

$ErrorActionPreference = "Stop"
$sharedLauncher = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Open-Codex-S-SharedRuntime.ps1"
if (-not (Test-Path -LiteralPath $sharedLauncher -PathType Leaf)) {
    throw "CODEX_SHARED_RUNTIME_LAUNCHER_MISSING: $sharedLauncher"
}

& $sharedLauncher -AccountSlot A -PrepareOnly:$PrepareOnly
if ($LASTEXITCODE) { exit $LASTEXITCODE }
