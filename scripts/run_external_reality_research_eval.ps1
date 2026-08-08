[CmdletBinding()]
param(
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }),
    [string]$CasePattern
)

$runner = Join-Path $PSScriptRoot 'run_behavior_regression.ps1'
& $runner -Profile external -RuntimeRoot $RuntimeRoot -CodexHome $CodexHome -CasePattern $CasePattern
exit $LASTEXITCODE
