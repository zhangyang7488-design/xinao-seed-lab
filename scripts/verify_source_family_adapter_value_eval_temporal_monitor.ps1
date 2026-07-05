param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$WaveId = "wave-block8-source-family-adapter-value-eval-temporal-monitor"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_adapter_value_eval.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_family_adapter_value_eval.py"

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$RepoRoot;$RepoRoot\src" + ($(if ($oldPyPath) { ";$oldPyPath" } else { "" }))
    Push-Location $RepoRoot

    python -m py_compile $modulePath
    Assert-True ($LASTEXITCODE -eq 0) "source_family_adapter_value_eval py_compile failed."

    python -m pytest -q $testPath
    Assert-True ($LASTEXITCODE -eq 0) "source_family_adapter_value_eval pytest failed."

    $output = python -m xinao_seedlab.cli.__main__ source-family-adapter-value-eval-temporal-monitor `
        --repo-root $RepoRoot `
        --runtime-root $RuntimeRoot `
        --wave-id $WaveId
    $generationExitCode = $LASTEXITCODE
    if ($generationExitCode -ne 0) {
        $output | ForEach-Object { Write-Output $_ }
    }
    Assert-True ($generationExitCode -eq 0) "source_family_adapter_value_eval_temporal_monitor generation failed."
    Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_TEMPORAL_MONITOR_READY")) "temporal monitor sentinel missing."

    $stateRoot = Join-Path $RuntimeRoot "state\source_family_adapter_value_eval\temporal_monitor"
    $latestPath = Join-Path $stateRoot "latest.json"
    $wavePath = Join-Path $stateRoot "waves\$WaveId.json"
    $nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"

    foreach ($path in @($latestPath, $wavePath, $nextFrontierPath)) {
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing temporal monitor evidence: $path"
    }

    $payload = Get-Content -LiteralPath $wavePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $latest = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json

    Assert-True ($payload.schema_version -eq "xinao.codex_s.source_family_adapter_value_eval.temporal_monitor.v1") "Monitor schema mismatch."
    Assert-True ($payload.status -eq "source_family_adapter_value_eval_temporal_monitor_ready") "Monitor not ready."
    Assert-True ($payload.wave_id -eq $WaveId) "Wave-specific monitor mismatch."
    Assert-True ($latest.wave_id -eq $WaveId) "Monitor latest does not point at verifier wave."
    Assert-True ($payload.consumed_next_frontier_action -eq "monitor_temporal_source_family_adapter_value_eval_activity") "Monitor action not consumed."
    Assert-True ($payload.input_refs.temporal_activity_wave.exists -eq $true) "Temporal activity wave ref missing."
    Assert-True ($payload.input_refs.gateway_refresh_wave.exists -eq $true) "Gateway refresh wave ref missing."
    Assert-True ($payload.validation.passed -eq $true) "Monitor validation failed."
    Assert-True ($nextFrontier.next_frontier[0].action -eq "continue_default_temporal_chain_after_source_family_adapter_value_eval_monitor") "Monitor next frontier did not advance."
    Assert-True ($nextFrontier.stop_allowed -eq $false) "Monitor next frontier allowed stop."
    Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."

    Write-Output "source_family_adapter_value_eval_temporal_monitor_latest=$latestPath"
    Write-Output "source_family_adapter_value_eval_temporal_monitor_wave=$wavePath"
    Write-Output "temporal_activity_wave_ref=$($payload.input_refs.temporal_activity_wave.path)"
    Write-Output "gateway_refresh_wave_ref=$($payload.input_refs.gateway_refresh_wave.path)"
    Write-Output "next_frontier_ref=$nextFrontierPath"
    Write-Output "validation_result=READY_CONTINUE"
    Write-Output "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_TEMPORAL_MONITOR_READY"
}
finally {
    Pop-Location
    $env:PYTHONPATH = $oldPyPath
}
