param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$WaveId = "wave-block7-source-family-smoked-candidate-thin-bind",
    [ValidateSet("live", "synthetic")]
    [string]$ProbeMode = "synthetic"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_smoked_candidate_thin_bind.py"
$adapterPath = Join-Path $RepoRoot "src\xinao_seedlab\adapters\source_candidate.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_family_smoked_candidate_thin_bind.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_family_smoked_candidate_thin_bind.v1.json"
$adapterSmokeModulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_adapter_smoke.py"

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$RepoRoot;$RepoRoot\src" + ($(if ($oldPyPath) { ";$oldPyPath" } else { "" }))
    Push-Location $RepoRoot

    python -m py_compile $modulePath $adapterPath
    Assert-True ($LASTEXITCODE -eq 0) "source_family_smoked_candidate_thin_bind py_compile failed."

    python -m pytest -q $testPath
    Assert-True ($LASTEXITCODE -eq 0) "source_family_smoked_candidate_thin_bind pytest failed."

    $parentWaveId = "$WaveId-adapter-smoke-parent"
    $adapterOutput = python $adapterSmokeModulePath `
        --repo-root $RepoRoot `
        --runtime-root $RuntimeRoot `
        --anchor-package-root $AnchorPackageRoot `
        --wave-id $parentWaveId `
        --probe-mode $ProbeMode
    $adapterExitCode = $LASTEXITCODE
    if ($adapterExitCode -ne 0) {
        $adapterOutput | ForEach-Object { Write-Output $_ }
    }
    Assert-True ($adapterExitCode -eq 0) "adapter smoke setup failed."

    $output = python $modulePath `
        --repo-root $RepoRoot `
        --runtime-root $RuntimeRoot `
        --anchor-package-root $AnchorPackageRoot `
        --wave-id $WaveId
    $generationExitCode = $LASTEXITCODE
    if ($generationExitCode -ne 0) {
        $output | ForEach-Object { Write-Output $_ }
    }
    Assert-True ($generationExitCode -eq 0) "source_family_smoked_candidate_thin_bind generation failed."
    Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_READY")) "thin bind sentinel missing."

    $stateRoot = Join-Path $RuntimeRoot "state\source_family_smoked_candidate_thin_bind"
    $latestPath = Join-Path $stateRoot "latest.json"
    $wavePath = Join-Path $stateRoot "waves\$WaveId.json"
    $bindingsPath = Join-Path $stateRoot "bindings\latest.json"
    $bindingsWavePath = Join-Path $stateRoot "bindings\$WaveId.json"
    $manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.source_family_smoked_candidate_thin_bind\manifest.json"
    $nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"
    $readbackPath = Join-Path $RuntimeRoot "readback\zh\source_family_smoked_candidate_thin_bind_20260704.md"

    foreach ($path in @($schemaPath, $latestPath, $wavePath, $bindingsPath, $bindingsWavePath, $manifestPath, $nextFrontierPath, $readbackPath)) {
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing thin bind evidence: $path"
    }

    $payload = Get-Content -LiteralPath $wavePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $latest = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $bindings = Get-Content -LiteralPath $bindingsWavePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

    Assert-True ($payload.schema_version -eq "xinao.codex_s.source_family_smoked_candidate_thin_bind.v1") "Payload schema mismatch."
    Assert-True ($payload.status -eq "source_family_smoked_candidate_thin_bind_ready") "Thin bind not ready."
    Assert-True ($payload.task_id -eq "wave7_source_family_smoked_candidate_thin_bind_20260704") "task_id mismatch."
    Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
    Assert-True ($payload.wave_id -eq $WaveId) "Wave-specific payload mismatch."
    Assert-True ($latest.wave_id -eq $WaveId) "Latest does not point at verifier wave."
    Assert-True ($payload.consumed_next_frontier_action -eq "implement_thin_bind_adapter_for_smoked_candidates") "Thin bind action not consumed."
    Assert-True ([int]$payload.binding_count -ge 1) "Binding count empty."
    Assert-True ([int]$payload.ready_binding_count -eq [int]$payload.binding_count) "Not all bindings are ready."
    Assert-True ($bindings.validation.passed -eq $true) "Bindings validation failed."
    Assert-True ([int]$bindings.binding_count -eq [int]$payload.binding_count) "Bindings count mismatch."
    Assert-True ($manifest.capability_id -eq "codex_s.source_family_smoked_candidate_thin_bind") "Capability id mismatch."
    Assert-True ($manifest.status -eq "ready") "Capability manifest not ready."
    Assert-True ($nextFrontier.should_continue_loop -eq $true) "Next frontier did not continue loop."
    Assert-True ($nextFrontier.stop_allowed -eq $false) "Next frontier allowed stop."
    Assert-True ($nextFrontier.next_frontier[0].action -eq "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway") "Next action mismatch."
    Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
    Assert-True ($payload.validation.passed -eq $true) "Thin bind validation failed."
    Assert-True ($readback.Contains("Source-family smoked candidate thin-bind")) "Readback missing thin bind text."
    Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_READY")) "Readback missing sentinel."

    Write-Output "source_family_smoked_candidate_thin_bind_latest=$latestPath"
    Write-Output "source_family_smoked_candidate_thin_bind_wave=$wavePath"
    Write-Output "bindings_latest=$bindingsPath"
    Write-Output "bindings_wave=$bindingsWavePath"
    Write-Output "thin_bind_manifest=$manifestPath"
    Write-Output "next_frontier_ref=$nextFrontierPath"
    Write-Output "readback_zh=$readbackPath"
    Write-Output "validation_result=PASS"
    Write-Output "SENTINEL:XINAO_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_READY"
}
finally {
    Pop-Location
    $env:PYTHONPATH = $oldPyPath
}
