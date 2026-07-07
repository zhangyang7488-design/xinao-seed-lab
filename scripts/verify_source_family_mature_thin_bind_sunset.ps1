param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$WaveId = "wave-block5-source-family-mature-thin-bind-sunset"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_mature_thin_bind_sunset.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_family_mature_thin_bind_sunset.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_family_mature_thin_bind_sunset.v1.json"

$env:XINAO_CODEX_S_REPO_ROOT = $RepoRoot
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $RepoRoot
} elseif (-not (($env:PYTHONPATH -split ';') -contains $RepoRoot)) {
    $env:PYTHONPATH = "$RepoRoot;$env:PYTHONPATH"
}

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "source_family_mature_thin_bind_sunset py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "source_family_mature_thin_bind_sunset pytest failed."

$output = python -m services.agent_runtime.source_family_mature_thin_bind_sunset `
    --repo-root $RepoRoot `
    --runtime-root $RuntimeRoot `
    --anchor-package-root $AnchorPackageRoot `
    --wave-id $WaveId
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "source_family_mature_thin_bind_sunset generation failed."
Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET_READY")) "phase5 sunset sentinel missing."

$latestPath = Join-Path $RuntimeRoot "state\source_family_mature_thin_bind_sunset\latest.json"
$edgesPath = Join-Path $RuntimeRoot "state\source_family_mature_thin_bind_sunset\sunset_edges\latest.json"
$queuePath = Join-Path $RuntimeRoot "state\source_family_mature_thin_bind_sunset\candidate_adapter_smoke_queue\latest.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.source_family_mature_thin_bind_sunset\manifest.json"
$nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\wave_block5_mature_thin_bind_sunset_20260704.md"

foreach ($path in @($schemaPath, $latestPath, $edgesPath, $queuePath, $manifestPath, $nextFrontierPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing phase5 sunset evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$edges = Get-Content -LiteralPath $edgesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$queue = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ($payload.schema_version -eq "xinao.codex_s.source_family_mature_thin_bind_sunset.v1") "Payload schema mismatch."
Assert-True ($payload.status -eq "source_family_mature_thin_bind_sunset_ready") "Phase5 sunset not ready."
Assert-True ($payload.task_id -eq "wave5_source_family_mature_thin_bind_sunset_20260704") "task_id mismatch."
Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
Assert-True ($payload.consumed_next_frontier_action -eq "enter_phase5_mature_thin_bind_sunset") "Phase5 action not consumed."
Assert-True ([int]$payload.source_frontier_remaining_topic_family_count -eq 0) "Source frontier remaining is not zero."
Assert-True ([int]$edges.edge_count -ge 2) "Sunset edges too few."
Assert-True ([int]$queue.candidate_count -ge 1) "Adapter smoke queue empty."
Assert-True ($manifest.capability_id -eq "codex_s.source_family_mature_thin_bind_sunset") "Capability id mismatch."
Assert-True ($manifest.status -eq "ready") "Capability manifest not ready."
Assert-True ($nextFrontier.should_continue_loop -eq $true) "Next frontier did not continue loop."
Assert-True ($nextFrontier.stop_allowed -eq $false) "Next frontier allowed stop."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
Assert-True ($payload.validation.passed -eq $true) "Phase5 sunset validation failed."
Assert-True ($readback.Contains("source-family-mature-thin-bind-sunset")) "Readback missing invoke answer."
Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET_READY")) "Readback missing sentinel."

Write-Output "source_family_mature_thin_bind_sunset_latest=$latestPath"
Write-Output "sunset_edges_latest=$edgesPath"
Write-Output "candidate_adapter_smoke_queue_latest=$queuePath"
Write-Output "phase5_sunset_manifest=$manifestPath"
Write-Output "next_frontier_ref=$nextFrontierPath"
Write-Output "readback_zh=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET_READY"
