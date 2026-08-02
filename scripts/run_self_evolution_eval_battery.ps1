[CmdletBinding()]
param(
    [ValidateSet('behavior')]
    [string]$Loop = 'behavior',
    [ValidateSet('smoke', 'core', 'deep')]
    [string]$Profile = 'smoke',
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(Join-Path $HOME '.codex')
)

$ErrorActionPreference = 'Stop'
$batteryId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$batteryRoot = Join-Path $RuntimeRoot "state\human-capabilities\evals\behavior-battery\$batteryId"
New-Item -ItemType Directory -Path $batteryRoot -Force | Out-Null
$consolePath = Join-Path $batteryRoot 'behavior.console.log'
$console = & (Join-Path $PSScriptRoot 'run_behavior_regression.ps1') `
    -Profile $Profile -RuntimeRoot $RuntimeRoot -CodexHome $CodexHome 2>&1
$code = $LASTEXITCODE
$console | Set-Content -LiteralPath $consolePath -Encoding utf8NoBOM

$summary = [ordered]@{
    schema_version = 'xinao.behavior_evolution_battery.v2'
    battery_id = $batteryId
    loop_filter = $Loop
    profile = $Profile
    generated_at = (Get-Date).ToString('o')
    repository_git_sha = (& git -C (Split-Path -Parent $PSScriptRoot) rev-parse HEAD 2>$null).Trim()
    repository_git_dirty = (@(& git -C (Split-Path -Parent $PSScriptRoot) status --porcelain=v1 2>$null).Count -gt 0)
    scope_note = 'domain research belongs to xinao-native-research'
    admission_fixture_only = @('thin_localization_contract')
    domain_completion_claim_allowed = $false
    results = @([ordered]@{
        loop = 'behavior'
        runner = 'run_behavior_regression.ps1'
        exit_code = $code
        ok = ($code -eq 0)
        evidence = if ($console) { [string](@($console)[-1]) } else { $null }
        console = $consolePath
    })
    ok = ($code -eq 0)
}
$summaryPath = Join-Path $batteryRoot 'summary.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8NoBOM
$latestRoot = Join-Path $RuntimeRoot 'state\human-capabilities\evals\behavior-battery'
New-Item -ItemType Directory -Path $latestRoot -Force | Out-Null
Copy-Item -LiteralPath $summaryPath -Destination (Join-Path $latestRoot 'latest.json') -Force
Write-Output $summaryPath
if ($code -ne 0) { exit $code }
