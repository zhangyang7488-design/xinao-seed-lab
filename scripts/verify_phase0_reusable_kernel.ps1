param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$SpecPath = "D:\XINAO_RESEARCH_RUNTIME\specs\max_benefit_dynamic_loop_authority_20260702.v1.md",
    [string]$WaveId = "wave-block5-phase0-reusable-kernel"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\phase0_reusable_kernel.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_phase0_reusable_kernel.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_phase0_reusable_kernel.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "phase0_reusable_kernel py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "phase0_reusable_kernel pytest failed."

$output = python $modulePath `
    --repo-root $RepoRoot `
    --runtime-root $RuntimeRoot `
    --anchor-package-root $AnchorPackageRoot `
    --spec-path $SpecPath `
    --wave-id $WaveId
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "phase0_reusable_kernel generation failed."
Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_PHASE0_REUSABLE_KERNEL_READY")) "phase0 sentinel missing."

$latestPath = Join-Path $RuntimeRoot "state\phase0_reusable_kernel\latest.json"
$objectsPath = Join-Path $RuntimeRoot "state\phase0_reusable_kernel\kernel_objects\latest.json"
$swapPath = Join-Path $RuntimeRoot "state\phase0_reusable_kernel\provider_swap_replay\latest.json"
$thinPath = Join-Path $RuntimeRoot "state\phase0_reusable_kernel\new_work_id_thin_bind\latest.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.phase0_reusable_kernel\manifest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\wave_block5_phase0_reusable_kernel_20260704.md"

foreach ($path in @($schemaPath, $latestPath, $objectsPath, $swapPath, $thinPath, $manifestPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing phase0 reusable evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$objects = Get-Content -LiteralPath $objectsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$swap = Get-Content -LiteralPath $swapPath -Raw -Encoding UTF8 | ConvertFrom-Json
$thin = Get-Content -LiteralPath $thinPath -Raw -Encoding UTF8 | ConvertFrom-Json
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ($payload.schema_version -eq "xinao.codex_s.phase0_reusable_kernel.v1") "Payload schema mismatch."
Assert-True ($payload.status -eq "phase0_reusable_kernel_ready") "Phase0 reusable kernel not ready."
Assert-True ($payload.task_id -eq "wave5_phase0_reusable_kernel_20260704") "task_id mismatch."
Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
Assert-True ([int]$objects.object_count -eq 4) "Kernel object count mismatch."
Assert-True ([int]$objects.landed_count -eq 4) "Not all kernel objects landed."
Assert-True ($objects.frontier_four_objects_available -eq $true) "Frontier four objects not available."
Assert-True ($swap.provider_swap_requires_domain_rewrite -eq $false) "Provider swap still requires domain rewrite."
Assert-True ([int]$swap.switchable_ready_provider_count -ge 3) "Provider swap ready count too low."
Assert-True ($thin.bind_without_hand_solder -eq $true) "New work_id thin bind still requires hand solder."
Assert-True ($payload.next_frontier_machine_actions.should_continue_loop -eq $true) "Next frontier did not continue loop."
Assert-True ($payload.next_frontier_machine_actions.stop_allowed -eq $false) "Phase0 reusable kernel allowed root stop."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
Assert-True ($payload.validation.passed -eq $true) "Phase0 reusable validation failed."
Assert-True ($readback.Contains("phase0-reusable-kernel")) "Readback missing invoke answer."
Assert-True ($readback.Contains("SENTINEL:XINAO_PHASE0_REUSABLE_KERNEL_READY")) "Readback missing sentinel."

Write-Output "phase0_reusable_kernel_latest=$latestPath"
Write-Output "kernel_objects_latest=$objectsPath"
Write-Output "provider_swap_replay_latest=$swapPath"
Write-Output "new_work_id_thin_bind_latest=$thinPath"
Write-Output "capability_manifest=$manifestPath"
Write-Output "readback_zh=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_PHASE0_REUSABLE_KERNEL_READY"
