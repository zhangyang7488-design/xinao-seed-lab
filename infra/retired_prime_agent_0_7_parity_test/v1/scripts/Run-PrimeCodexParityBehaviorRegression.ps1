#Requires -Version 5.1
[CmdletBinding()]
param([string]$FilterPattern)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PrimeParity.Common.ps1')

$null = Get-PrimeParityActiveAccount
$null = Get-PrimeParityConversationBinding
$promptfooPackage = 'D:\XINAO_RESEARCH_RUNTIME\tools\promptfoo\node_modules\promptfoo\package.json'
$manifest = Read-PrimeParityJson -Path $promptfooPackage
$entry = Join-Path (Split-Path -Parent $promptfooPackage) ([string]$manifest.bin.promptfoo)
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw "PRIME_PARITY_PROMPTFOO_ENTRY_MISSING: $entry" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runRoot = Join-Path $script:PrimeParityRuntimeRoot "behavior-runs\$stamp"
$artifactRoot = Join-Path $runRoot 'trajectories'
$promptfooState = Join-Path $runRoot 'promptfoo-state'
foreach ($path in @($runRoot,$artifactRoot,$promptfooState,(Join-Path $promptfooState 'logs'))) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}
$resultPath = Join-Path $runRoot 'promptfoo-results.json'
$consolePath = Join-Path $runRoot 'promptfoo-console.txt'
$config = Join-Path $script:PrimeParitySourceRoot 'evals\promptfooconfig.yaml'
$env:PRIME_PARITY_EVAL_RUN_ROOT = $artifactRoot
$env:PROMPTFOO_CONFIG_DIR = $promptfooState
$env:PROMPTFOO_LOG_DIR = Join-Path $promptfooState 'logs'
$env:PROMPTFOO_CACHE_PATH = Join-Path $promptfooState 'cache'
$env:PROMPTFOO_DISABLE_TELEMETRY = '1'
$env:PROMPTFOO_DISABLE_UPDATE = '1'
$env:PROMPTFOO_DISABLE_DEBUG_LOG = '1'
$env:PROMPTFOO_DISABLE_ERROR_LOG = '1'
$env:TSX_DISABLE_CACHE = '1'

$arguments = @($entry,'eval','--config',$config,'--output',$resultPath,'--max-concurrency','1','--no-cache','--no-table','--no-progress-bar','--no-share')
if (-not [string]::IsNullOrWhiteSpace($FilterPattern)) { $arguments += @('--filter-pattern',$FilterPattern) }
$started = Get-Date
$console = @(& $script:PrimeParityNode @arguments 2>&1)
$exitCode = $LASTEXITCODE
$console | Set-Content -LiteralPath $consolePath -Encoding UTF8
if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
    throw "PRIME_PARITY_PROMPTFOO_RESULT_MISSING: exit=$exitCode console=$consolePath"
}
$result = Read-PrimeParityJson -Path $resultPath
$stats = $result.results.stats
$verified = ($exitCode -eq 0 -and [int]$stats.failures -eq 0 -and [int]$stats.errors -eq 0 -and [int]$stats.successes -gt 0)
$acceptance = [ordered]@{
    schema = 'xinao.prime_codex_parity.behavior_acceptance.v1'
    status = if ($verified) { 'verified' } else { 'failed' }
    promptfoo_version = [string]$manifest.version
    filter_pattern = $FilterPattern
    successes = [int]$stats.successes
    failures = [int]$stats.failures
    errors = [int]$stats.errors
    token_usage = $stats.tokenUsage
    duration_ms = [int]((Get-Date) - $started).TotalMilliseconds
    result = $resultPath
    console = $consolePath
    trajectories = $artifactRoot
    durable_session_used = $false
    provider_auth_copied = $false
    automatic_approval_reviewer_used = $false
    observed_at = (Get-Date).ToString('o')
}
Write-PrimeParityJsonAtomic -Path (Join-Path $runRoot 'acceptance.json') -Value $acceptance
if ([string]::IsNullOrWhiteSpace($FilterPattern)) {
    Write-PrimeParityJsonAtomic -Path (Join-Path $script:PrimeParityRuntimeRoot 'validation\behavior-latest.json') -Value $acceptance
}
$acceptance | ConvertTo-Json -Depth 12
if (-not $verified) { exit 1 }
exit 0
