param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$AnchorPackageRoot = (Join-Path (Join-Path $env:USERPROFILE "Desktop") (([string]([char]0x65B0)) + ([string]([char]0x7CFB)) + ([string]([char]0x7EDF)))),
    [string]$WaveId = "wave-block8-source-family-adapter-value-eval"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\source_family_adapter_value_eval.py"
$testPath = Join-Path $RepoRoot "tests\seedcortex\test_source_family_adapter_value_eval.py"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_family_adapter_value_eval.v1.json"

$oldPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$RepoRoot;$RepoRoot\src" + ($(if ($oldPyPath) { ";$oldPyPath" } else { "" }))
    Push-Location $RepoRoot

    python -m py_compile $modulePath
    Assert-True ($LASTEXITCODE -eq 0) "source_family_adapter_value_eval py_compile failed."

    python -m pytest -q $testPath
    Assert-True ($LASTEXITCODE -eq 0) "source_family_adapter_value_eval pytest failed."

    $output = python -m xinao_seedlab.cli.__main__ source-family-adapter-value-eval `
        --repo-root $RepoRoot `
        --runtime-root $RuntimeRoot `
        --anchor-package-root $AnchorPackageRoot `
        --wave-id $WaveId
    $generationExitCode = $LASTEXITCODE
    if ($generationExitCode -ne 0) {
        $output | ForEach-Object { Write-Output $_ }
    }
    Assert-True ($generationExitCode -eq 0) "source_family_adapter_value_eval generation failed."
    Assert-True (($output -join "`n").Contains("SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_READY")) "value eval sentinel missing."

    $stateRoot = Join-Path $RuntimeRoot "state\source_family_adapter_value_eval"
    $latestPath = Join-Path $stateRoot "latest.json"
    $wavePath = Join-Path $stateRoot "waves\$WaveId.json"
    $decisionsPath = Join-Path $stateRoot "decisions\latest.json"
    $decisionsWavePath = Join-Path $stateRoot "decisions\$WaveId.json"
    $gatewayCandidatesPath = Join-Path $stateRoot "capability_gateway_candidates\latest.json"
    $gatewayCandidatesWavePath = Join-Path $stateRoot "capability_gateway_candidates\$WaveId.json"
    $manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.source_family_adapter_value_eval\manifest.json"
    $gatewayPath = Join-Path $RuntimeRoot "state\capability_gateway\latest.json"
    $nextFrontierPath = Join-Path $RuntimeRoot "state\next_frontier_machine_actions\latest.json"
    $readbackPath = Join-Path $RuntimeRoot "readback\zh\source_family_adapter_value_eval_20260704.md"

    foreach ($path in @($schemaPath, $latestPath, $wavePath, $decisionsPath, $decisionsWavePath, $gatewayCandidatesPath, $gatewayCandidatesWavePath, $manifestPath, $gatewayPath, $nextFrontierPath, $readbackPath)) {
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing value eval evidence: $path"
    }

    $payload = Get-Content -LiteralPath $wavePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $latest = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $decisions = Get-Content -LiteralPath $decisionsWavePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $gatewayCandidates = Get-Content -LiteralPath $gatewayCandidatesWavePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $gateway = Get-Content -LiteralPath $gatewayPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

    Assert-True ($payload.schema_version -eq "xinao.codex_s.source_family_adapter_value_eval.v1") "Payload schema mismatch."
    Assert-True ($payload.status -eq "source_family_adapter_value_eval_ready") "Value eval not ready."
    Assert-True ($payload.task_id -eq "wave8_source_family_adapter_value_eval_20260704") "task_id mismatch."
    Assert-True ($payload.routing -eq "continue_same_task") "routing mismatch."
    Assert-True ($payload.wave_id -eq $WaveId) "Wave-specific payload mismatch."
    Assert-True ($latest.wave_id -eq $WaveId) "Latest does not point at verifier wave."
    Assert-True ($payload.consumed_next_frontier_action -eq "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway" -or $payload.consumed_next_frontier_action -eq "refresh_capability_gateway_snapshot_with_evaluated_source_candidates") "Value eval action not consumed."
    Assert-True ([int]$payload.decision_count -ge 1) "Decision count empty."
    Assert-True ([int]$payload.gateway_candidate_count -eq [int]$payload.decision_count) "Gateway candidate count mismatch."
    Assert-True ($decisions.validation.passed -eq $true) "Decisions validation failed."
    Assert-True ($gatewayCandidates.validation.passed -eq $true) "Gateway candidates validation failed."
    Assert-True ($gatewayCandidates.provider.default_capability_promotion_allowed -eq $false) "Default promotion was allowed."
    Assert-True ($manifest.capability_id -eq "codex_s.source_family_adapter_value_eval") "Capability id mismatch."
    Assert-True ($manifest.status -eq "ready") "Capability manifest not ready."
    Assert-True ($gateway.provider_ids -contains "codex_s.source_family_smoked_candidate_adapter_candidates") "CapabilityGateway candidate provider missing."
    Assert-True ($nextFrontier.should_continue_loop -eq $true) "Next frontier did not continue loop."
    Assert-True ($nextFrontier.stop_allowed -eq $false) "Next frontier allowed stop."
    Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
    Assert-True ($payload.validation.passed -eq $true) "Value eval validation failed."
    Assert-True ($readback.Contains("Source-family adapter value-eval")) "Readback missing value eval text."
    Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_READY")) "Readback missing sentinel."

    Write-Output "source_family_adapter_value_eval_latest=$latestPath"
    Write-Output "source_family_adapter_value_eval_wave=$wavePath"
    Write-Output "decisions_latest=$decisionsPath"
    Write-Output "gateway_candidates_latest=$gatewayCandidatesPath"
    Write-Output "capability_gateway_latest=$gatewayPath"
    Write-Output "next_frontier_ref=$nextFrontierPath"
    Write-Output "readback_zh=$readbackPath"
    Write-Output "validation_result=PASS"
    Write-Output "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_READY"
}
finally {
    Pop-Location
    $env:PYTHONPATH = $oldPyPath
}
