param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$WaveId = "source-frontier-workerpool-global-closure-20260704-verify-wave",
    [string]$WorkflowId = "source-frontier-workerpool-global-closure-20260704",
    [string]$WorkflowRunId = ""
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Has-Prop {
    param($Object, [string]$Name)
    return $null -ne $Object -and ($Object.PSObject.Properties.Name -contains $Name)
}

function Assert-WaveEvidence {
    param($Payload, [string]$Name, [string]$ExpectedDigest)
    Assert-True ($Payload.wave_id -eq $WaveId) "$Name wave_id mismatch."
    Assert-True ($Payload.workflow_id -eq $WorkflowId) "$Name workflow_id mismatch."
    if (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) {
        Assert-True ($Payload.workflow_run_id -eq $WorkflowRunId) "$Name workflow_run_id mismatch."
    }
    Assert-True ($Payload.evidence_digest_sha256 -eq $ExpectedDigest) "$Name evidence digest mismatch."
    Assert-True (@($Payload.source_batch_ids).Count -gt 0) "$Name source_batch_ids missing."
    Assert-True (@($Payload.worker_brief_ids).Count -gt 0) "$Name worker_brief_ids missing."
    Assert-True ($null -ne $Payload.same_wave_output_refs) "$Name same_wave_output_refs missing."
}

$bridgeModulePath = Join-Path $RepoRoot "services\agent_runtime\source_frontier_workerbrief_bridge.py"
$bridgeTestPath = Join-Path $RepoRoot "tests\seedcortex\test_source_frontier_workerbrief_bridge.py"
$bridgeSchemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_frontier_workerbrief_bridge.v1.json"
$closureModulePath = Join-Path $RepoRoot "services\agent_runtime\source_frontier_workerpool_closure.py"
$closureTestPath = Join-Path $RepoRoot "tests\seedcortex\test_source_frontier_workerpool_closure.py"
$closureSchemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_source_frontier_workerpool_closure.v1.json"

python -m py_compile $bridgeModulePath $closureModulePath
Assert-True ($LASTEXITCODE -eq 0) "bridge/closure py_compile failed."

python -m pytest -q $bridgeTestPath $closureTestPath
Assert-True ($LASTEXITCODE -eq 0) "bridge/closure pytest failed."

$bridgeOutput = python $bridgeModulePath `
    --runtime-root $RuntimeRoot `
    --repo-root $RepoRoot `
    --wave-id $WaveId `
    --workflow-id $WorkflowId
$bridgeExitCode = $LASTEXITCODE
if ($bridgeExitCode -ne 0) {
    $bridgeOutput | ForEach-Object { Write-Output $_ }
}
Assert-True ($bridgeExitCode -eq 0) "source_frontier_workerbrief_bridge generation failed."
Assert-True (($bridgeOutput -join "`n").Contains("SENTINEL:XINAO_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_V1")) "bridge sentinel missing."

$bridgeWavePath = Join-Path $RuntimeRoot "state\source_frontier_workerbrief_bridge\waves\$WaveId.json"
$queuePath = Join-Path $RuntimeRoot "state\source_frontier_workerbrief_bridge\worker_brief_queue_latest.json"
$mappingPath = Join-Path $RuntimeRoot "state\source_frontier_workerbrief_bridge\mapping_latest.json"
$bridgeReadbackPath = Join-Path $RuntimeRoot "readback\zh\source_frontier_workerbrief_bridge_$WaveId.md"

foreach ($path in @($bridgeSchemaPath, $bridgeWavePath, $queuePath, $mappingPath, $bridgeReadbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing bridge evidence: $path"
}

$bridge = Get-Content -LiteralPath $bridgeWavePath -Raw -Encoding UTF8 | ConvertFrom-Json
$queue = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$mapping = Get-Content -LiteralPath $mappingPath -Raw -Encoding UTF8 | ConvertFrom-Json

Assert-True ($bridge.schema_version -eq "xinao.codex_s.source_frontier_workerbrief_bridge.v1") "Bridge schema mismatch."
Assert-True ($bridge.status -eq "source_frontier_workerbrief_bridge_ready") "Bridge not ready."
Assert-True ($bridge.source_frontier_to_workerbrief_binding -eq $true) "Bridge binding flag missing."
Assert-True ($bridge.not_new_control_plane -eq $true) "Bridge became a control plane."
Assert-True ([int]$bridge.source_item_count -ge 1) "No source frontier item was bound."
Assert-True ([int]$bridge.worker_brief_binding_count -ge 1) "No WorkerBrief binding was generated."
Assert-True ($bridge.latest_alias_is_not_proof -eq $true) "Bridge latest boundary missing."
Assert-True ($bridge.validation.passed -eq $true) "Bridge validation failed."
Assert-True ($queue.schema_version -eq "xinao.codex_s.worker_brief_queue.source_bound.v1") "Source-bound WorkerBriefQueue schema mismatch."
Assert-True ([int]$queue.brief_count -eq [int]$bridge.worker_brief_binding_count) "Source-bound queue count mismatch."
Assert-True ($mapping.schema_version -eq "xinao.codex_s.source_frontier_workerbrief_bridge.mapping.v1") "Mapping schema mismatch."

$bridgeRequired = @(
    "worker_brief_id",
    "source_batch_id",
    "frontier_batch_id",
    "claim_card_id",
    "claim_card_ref",
    "source_package_ref",
    "mapping_key",
    "objective",
    "expected_artifact",
    "provider_policy",
    "fan_in_target",
    "aaq_target",
    "next_frontier_policy"
)
foreach ($binding in @($bridge.worker_brief_bindings)) {
    foreach ($field in $bridgeRequired) {
        Assert-True (Has-Prop $binding $field) "Bridge WorkerBrief missing field $field."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$binding.$field)) "Bridge WorkerBrief empty field $field."
    }
}

$closureArgs = @(
    $closureModulePath,
    "--runtime-root", $RuntimeRoot,
    "--repo-root", $RepoRoot,
    "--wave-id", $WaveId,
    "--parent-wave-id", $WaveId,
    "--workflow-id", $WorkflowId
)
if (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) {
    $closureArgs += @("--workflow-run-id", $WorkflowRunId)
}
$closureOutput = & python @closureArgs
$closureExitCode = $LASTEXITCODE
$closureOutputText = $closureOutput -join "`n"
Assert-True ($closureOutputText.Contains("SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1")) "closure sentinel missing."

$closureWavePath = Join-Path $RuntimeRoot "state\source_frontier_workerpool_closure\waves\$WaveId\closure.json"
Assert-True (Test-Path -LiteralPath $closureWavePath -PathType Leaf) "Missing closure wave evidence: $closureWavePath"
$closure = Get-Content -LiteralPath $closureWavePath -Raw -Encoding UTF8 | ConvertFrom-Json

$repairPlanPath = [string]$closure.output_paths.repair_plan
if ($closureExitCode -ne 0) {
    Assert-True ($closure.repair_plan.repair_required -eq $true) "Closure failed without RepairPlan."
    Assert-True (Test-Path -LiteralPath $repairPlanPath -PathType Leaf) "RepairPlan missing: $repairPlanPath"
    Assert-True ([int]$closure.repair_plan.fixable_repair_count -gt 0 -or -not [string]::IsNullOrWhiteSpace([string]$closure.repair_plan.named_blocker)) "RepairPlan has neither fixable item nor named blocker."
    Write-Output "closure_result=REPAIR_PLAN_CONTINUE"
    Write-Output "repair_plan=$repairPlanPath"
    Write-Output "named_blocker=$($closure.repair_plan.named_blocker)"
    Write-Output "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1"
    exit $closureExitCode
}

Assert-True ($closure.schema_version -eq "xinao.codex_s.source_frontier_workerpool_closure.v1") "Closure schema mismatch."
Assert-True ($closure.status -eq "source_frontier_workerpool_closure_ready") "Closure not ready."
Assert-True ($closure.wave_id -eq $WaveId) "Closure wave_id mismatch."
Assert-True ($closure.parent_wave_id -eq $WaveId) "Closure parent_wave_id mismatch."
Assert-True ($closure.workflow_id -eq $WorkflowId) "Closure workflow_id mismatch."
if (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) {
    Assert-True ($closure.workflow_run_id -eq $WorkflowRunId) "Closure workflow_run_id mismatch."
}
Assert-True ($closure.source_bound_worker_brief_queue_ref -eq $queuePath) "Closure did not use source-bound WorkerBriefQueue."
Assert-True ([int]$closure.source_bound_worker_brief_count -eq [int]$queue.brief_count) "Closure did not invoke all source-bound WorkerBriefs."
Assert-True ([int]$closure.lane_results.Count -eq [int]$queue.brief_count) "Closure lane result count mismatch."
Assert-True ($closure.repair_plan.repair_required -eq $false) "Closure unexpectedly requires repair."
Assert-True ($closure.latest_alias_is_not_proof -eq $true) "Closure latest boundary missing."
Assert-True ($closure.completion_claim_allowed -eq $false) "Closure allowed completion claim."
Assert-True ($closure.not_execution_controller -eq $true) "Closure became execution controller."
Assert-True ($closure.validation.passed -eq $true) "Closure validation failed."
Assert-True ($closure.validation.checks.same_wave_refs -eq $true) "Closure did not validate same_wave_refs."
Assert-True ($closure.validation.checks.wave_specific_products_bound -eq $true) "Closure did not validate wave_specific_products_bound."

$closureWaveLedgerPath = [string]$closure.output_paths.worker_dispatch_ledger_wave
$closureActivityLedgerPath = [string]$closure.output_paths.worker_dispatch_ledger_activity
$stagingPath = [string]$closure.output_paths.staging
$mergePath = [string]$closure.output_paths.merge
$fanInPath = [string]$closure.output_paths.fan_in
$aaqPath = [string]$closure.output_paths.aaq
$nextFrontierPath = [string]$closure.output_paths.next_frontier
$closureReadbackPath = [string]$closure.output_paths.readback_zh

foreach ($path in @($closureSchemaPath, $closureWaveLedgerPath, $closureActivityLedgerPath, $stagingPath, $mergePath, $fanInPath, $aaqPath, $nextFrontierPath, $closureReadbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing closure wave-specific evidence: $path"
}

$closureLedger = Get-Content -LiteralPath $closureWaveLedgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$closureActivity = Get-Content -LiteralPath $closureActivityLedgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$staging = Get-Content -LiteralPath $stagingPath -Raw -Encoding UTF8 | ConvertFrom-Json
$merge = Get-Content -LiteralPath $mergePath -Raw -Encoding UTF8 | ConvertFrom-Json
$fanIn = Get-Content -LiteralPath $fanInPath -Raw -Encoding UTF8 | ConvertFrom-Json
$aaq = Get-Content -LiteralPath $aaqPath -Raw -Encoding UTF8 | ConvertFrom-Json
$nextFrontier = Get-Content -LiteralPath $nextFrontierPath -Raw -Encoding UTF8 | ConvertFrom-Json
$closureReadback = Get-Content -LiteralPath $closureReadbackPath -Raw -Encoding UTF8

Assert-WaveEvidence $closure "Closure" $closure.evidence_digest_sha256
Assert-WaveEvidence $staging "Staging" $closure.evidence_digest_sha256
Assert-WaveEvidence $merge "Merge" $closure.evidence_digest_sha256
Assert-WaveEvidence $fanIn "FanIn" $closure.evidence_digest_sha256
Assert-WaveEvidence $aaq "AAQ" $closure.evidence_digest_sha256
Assert-WaveEvidence $nextFrontier "NextFrontier" $closure.evidence_digest_sha256

Assert-True ($closureLedger.immutable_wave_evidence -eq $true) "Closure ledger is not immutable evidence."
Assert-True ($closureLedger.wave_id -eq $WaveId) "Closure ledger wave mismatch."
Assert-True ($closureLedger.parent_wave_id -eq $WaveId) "Closure ledger parent wave mismatch."
Assert-True ($closureLedger.workflow_id -eq $WorkflowId) "Closure ledger workflow mismatch."
Assert-True ($closureLedger.evidence_digest_sha256 -eq $closure.evidence_digest_sha256) "Closure ledger digest mismatch."
Assert-True ($closureActivity.activity -eq "source_frontier_workerpool_closure") "Closure activity ledger mismatch."
Assert-True ($closureActivity.evidence_digest_sha256 -eq $closure.evidence_digest_sha256) "Closure activity digest mismatch."
Assert-True ($closureActivity.latest_alias_is_not_proof -eq $true) "Closure activity latest boundary missing."

Assert-True ($staging.wave_id -eq $WaveId) "Staging wave mismatch."
Assert-True ([int]$staging.staged_count -gt 0) "No source-bound output entered staging."
Assert-True ($merge.wave_id -eq $WaveId) "Merge wave mismatch."
Assert-True ($merge.status -eq "source_bound_merge_ready") "Merge not ready."
Assert-True ($fanIn.wave_id -eq $WaveId) "FanIn wave mismatch."
Assert-True ($fanIn.object_type -eq "FanInAcceptanceQueue") "FanIn object mismatch."
Assert-True ($fanIn.validation.passed -eq $true) "FanIn validation failed."
Assert-True ($aaq.wave_id -eq $WaveId) "AAQ wave mismatch."
Assert-True ([int]$aaq.accepted_artifact_count -gt 0) "AAQ accepted no artifacts."
Assert-True ($nextFrontier.wave_id -eq $WaveId) "Next frontier wave mismatch."
Assert-True ($nextFrontier.parent_wave_id -eq $WaveId) "Next frontier parent wave mismatch."
Assert-True ($nextFrontier.stop_allowed -eq $false) "Next frontier allowed stop."
Assert-True ($nextFrontier.validation.passed -eq $true) "Next frontier validation failed."

$preferredRoutes = @($closure.validation.preferred_provider_routes_seen)
Assert-True ($preferredRoutes.Count -ge 2) "ProviderScheduler route did not use a mixed provider policy."
$providersSeen = @($closure.validation.providers_seen)
Assert-True ($providersSeen.Count -ge 1) "No provider execution observed."

$chainRequired = @(
    "wave_id",
    "parent_wave_id",
    "workflow_id",
    "evidence_digest_sha256",
    "source_batch_id",
    "worker_brief_id",
    "allocation_plan_ref",
    "provider_scheduler_ref",
    "provider_invocation_ref",
    "staging_ref",
    "merge_ref",
    "fan_in_ref",
    "aaq_ref",
    "next_frontier_ref"
)
foreach ($chain in @($closure.acceptance_chains)) {
    Assert-True ($chain.status -eq "succeeded") "A source-bound WorkerBrief did not succeed: $($chain.worker_brief_id)"
    foreach ($field in $chainRequired) {
        Assert-True (Has-Prop $chain $field) "Acceptance chain missing field $field."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$chain.$field)) "Acceptance chain empty field $field."
    }
    Assert-True ($chain.wave_id -eq $WaveId) "Acceptance chain wave mismatch."
    Assert-True ($chain.parent_wave_id -eq $WaveId) "Acceptance chain parent wave mismatch."
    Assert-True ($chain.workflow_id -eq $WorkflowId) "Acceptance chain workflow mismatch."
    if (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) {
        Assert-True ($chain.workflow_run_id -eq $WorkflowRunId) "Acceptance chain workflow run mismatch."
    }
    Assert-True ($chain.evidence_digest_sha256 -eq $closure.evidence_digest_sha256) "Acceptance chain digest mismatch."
    Assert-True ($chain.staging_ref -eq $stagingPath) "Chain staging ref is not wave-specific."
    Assert-True ($chain.merge_ref -eq $mergePath) "Chain merge ref is not wave-specific."
    Assert-True ($chain.fan_in_ref -eq $fanInPath) "Chain FanIn ref is not wave-specific."
    Assert-True ($chain.aaq_ref -eq $aaqPath) "Chain AAQ ref is not wave-specific."
    Assert-True ($chain.next_frontier_ref -eq $nextFrontierPath) "Chain next_frontier ref is not wave-specific."
    Assert-True (Test-Path -LiteralPath ([string]$chain.provider_invocation_ref) -PathType Leaf) "Provider invocation ref missing: $($chain.provider_invocation_ref)"
}

Assert-True ($closureReadback.Contains("source frontier workerpool closure readback")) "Closure readback missing title."
Assert-True ($closureReadback.Contains("source-bound WorkerBrief")) "Closure readback missing source-bound WorkerBrief statement."
Assert-True ($closureReadback.Contains("SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1")) "Closure readback missing sentinel."

$firstChain = @($closure.acceptance_chains)[0]
Write-Output "source_batch_id=$($firstChain.source_batch_id)"
Write-Output "worker_brief_id=$($firstChain.worker_brief_id)"
Write-Output "allocation_plan_ref=$($firstChain.allocation_plan_ref)"
Write-Output "provider_scheduler_ref=$($firstChain.provider_scheduler_ref)"
Write-Output "provider_invocation_ref=$($firstChain.provider_invocation_ref)"
Write-Output "staging_ref=$($firstChain.staging_ref)"
Write-Output "merge_ref=$($firstChain.merge_ref)"
Write-Output "fan_in_ref=$($firstChain.fan_in_ref)"
Write-Output "aaq_ref=$($firstChain.aaq_ref)"
Write-Output "next_frontier_ref=$($firstChain.next_frontier_ref)"
Write-Output "source_frontier_workerbrief_bridge_wave=$bridgeWavePath"
Write-Output "source_bound_worker_brief_queue=$queuePath"
Write-Output "source_frontier_workerpool_closure_wave=$closureWavePath"
Write-Output "worker_dispatch_ledger_wave=$closureWaveLedgerPath"
Write-Output "worker_dispatch_ledger_activity=$closureActivityLedgerPath"
Write-Output "readback_zh=$closureReadbackPath"
Write-Output "closure_validation=READY_CONTINUE"
Write-Output "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1"
