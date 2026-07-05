$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = if ($env:XINAO_RESEARCH_RUNTIME) { $env:XINAO_RESEARCH_RUNTIME } else { "D:\XINAO_RESEARCH_RUNTIME" }
$modulePath = Join-Path $repoRoot "services\agent_runtime\mature_capability_first.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_mature_capability_first.v1.json"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_mature_capability_first.py"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "mature_capability_first py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "mature_capability_first pytest failed."

python -m services.agent_runtime.mature_capability_first `
    --runtime-root $runtimeRoot `
    --repo-root $repoRoot `
    --task-id "mature_capability_first_20260705" `
    --wave-id "mature-capability-first-verify-wave" `
    --mechanism provider_registry `
    --mechanism independent_eval `
    --mechanism checkpoint_interrupt `
    --mechanism policy_guardrail `
    --invoked-by "verify_mature_capability_first"
Assert-True ($LASTEXITCODE -eq 0) "mature_capability_first CLI generation failed."

$latestPath = Join-Path $runtimeRoot "state\mature_capability_first\latest.json"
$fitnessPath = Join-Path $runtimeRoot "state\mature_capability_first\fitness_latest.json"
Assert-True (Test-Path -LiteralPath $latestPath) "mature_capability_first latest missing."
Assert-True (Test-Path -LiteralPath $fitnessPath) "mature_capability_first fitness latest missing."

$payload = Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json
Assert-True ([string]$payload.schema_version -eq "xinao.codex_s.mature_capability_first.v1") "schema mismatch."
Assert-True ([string]$payload.sentinel -eq "SENTINEL:XINAO_MATURE_CAPABILITY_FIRST_V1") "sentinel mismatch."
Assert-True ($payload.validation.passed -eq $true) "validation did not pass."
Assert-True ($payload.policy_as_code_gate.enabled -eq $true) "policy gate missing."
Assert-True ($payload.policy_as_code_gate.blocks_local_default_without_exception -eq $true) "local default gate missing."
Assert-True ($payload.completion_claim_allowed -eq $false) "completion claim must be false."
Assert-True ($payload.not_execution_controller -eq $true) "must not be execution controller."

Write-Output "mature_capability_first_latest=$latestPath"
Write-Output "mature_capability_first_fitness=$fitnessPath"
Write-Output "verify_mature_capability_first PASS"
