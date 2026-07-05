param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$WaveId = "wave-block6-source-family-adapter-smoke",
    [ValidateSet("live", "synthetic")]
    [string]$ProbeMode = "synthetic"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_adapter_smoke.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_family_adapter_smoke.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_family_adapter_smoke.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "source_family_adapter_smoke py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "source_family_adapter_smoke pytest failed."

$output = python $modulePath `
    --repo-root $RepoRoot `
    --runtime-root $RuntimeRoot `
    --anchor-package-root $AnchorPackageRoot `
    --wave-id $WaveId `
    --probe-mode $ProbeMode
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "source_family_adapter_smoke generation failed."
Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_SMOKE_READY")) "adapter smoke sentinel missing."

$latestPath = Join-Path $RuntimeRoot "state\source_family_adapter_smoke\latest.json"
$resultsPath = Join-Path $RuntimeRoot "state\source_family_adapter_smoke\candidate_results\latest.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.source_family_adapter_smoke\manifest.json"
$nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\source_family_adapter_smoke_20260704.md"

foreach ($path in @($schemaPath, $latestPath, $resultsPath, $manifestPath, $nextFrontierPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing adapter smoke evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$results = Get-Content -LiteralPath $resultsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ($payload.schema_version -eq "xinao.codex_s.source_family_adapter_smoke.v1") "Payload schema mismatch."
Assert-True ($payload.status -eq "source_family_adapter_smoke_ready") "Adapter smoke not ready."
Assert-True ($payload.task_id -eq "wave6_source_family_adapter_smoke_20260704") "task_id mismatch."
Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
Assert-True ($payload.consumed_next_frontier_action -eq "smoke_mature_carrier_adapter_candidates" -or $payload.consumed_next_frontier_action -eq "implement_thin_bind_adapter_for_smoked_candidates") "Smoke action not consumed."
Assert-True ([int]$payload.candidate_count -ge 1) "Candidate count empty."
Assert-True ([int]$payload.passed_candidate_count -eq [int]$payload.candidate_count) "Not all candidate smokes passed."
Assert-True ($results.validation.passed -eq $true) "Candidate results validation failed."
Assert-True ($manifest.capability_id -eq "codex_s.source_family_adapter_smoke") "Capability id mismatch."
Assert-True ($manifest.status -eq "ready") "Capability manifest not ready."
Assert-True ($nextFrontier.should_continue_loop -eq $true) "Next frontier did not continue loop."
Assert-True ($nextFrontier.stop_allowed -eq $false) "Next frontier allowed stop."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
Assert-True ($payload.validation.passed -eq $true) "Adapter smoke validation failed."
Assert-True ($readback.Contains("Source-family adapter smoke")) "Readback missing adapter smoke text."
Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_SMOKE_READY")) "Readback missing sentinel."

Write-Output "source_family_adapter_smoke_latest=$latestPath"
Write-Output "candidate_results_latest=$resultsPath"
Write-Output "adapter_smoke_manifest=$manifestPath"
Write-Output "next_frontier_ref=$nextFrontierPath"
Write-Output "readback_zh=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_SMOKE_READY"
