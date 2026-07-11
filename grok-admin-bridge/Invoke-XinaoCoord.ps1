#Requires -Version 5.1
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CoordArgs = @()
)

$ErrorActionPreference = 'Stop'
$cli = Join-Path $ProjectRoot '.venv\Scripts\xinao-coord.exe'

if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    throw "XINAO_COORD_CLI_MISSING: $cli; run uv sync in the project explicitly"
}

& $cli @CoordArgs
exit $LASTEXITCODE
