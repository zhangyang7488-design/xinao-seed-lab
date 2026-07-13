[CmdletBinding()]
param(
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(Join-Path $HOME '.codex')
)

$runner = Join-Path $PSScriptRoot 'run_behavior_regression.ps1'
& $runner -Profile capability -RuntimeRoot $RuntimeRoot -CodexHome $CodexHome
exit $LASTEXITCODE
