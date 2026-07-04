param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$WaveId = "",
    [string]$WorkflowId = "",
    [string]$WorkflowRunId = "",
    [string]$ClosureWaveRef = ""
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON evidence: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Resolve-ClosureWaveRef {
    param([string]$Root, [string]$ExpectedWaveId, [string]$ExplicitRef)
    if (-not [string]::IsNullOrWhiteSpace($ExplicitRef)) {
        Assert-True (Test-Path -LiteralPath $ExplicitRef -PathType Leaf) "ClosureWaveRef not found: $ExplicitRef"
        return $ExplicitRef
    }
    Assert-True (-not [string]::IsNullOrWhiteSpace($ExpectedWaveId)) "WaveId or ClosureWaveRef is required."
    $wavesRoot = Join-Path $Root "state\source_frontier_workerpool_closure\waves"
    Assert-True (Test-Path -LiteralPath $wavesRoot -PathType Container) "Closure waves root not found: $wavesRoot"
    $matches = @()
    foreach ($candidate in Get-ChildItem -LiteralPath $wavesRoot -Directory) {
        $path = Join-Path $candidate.FullName "closure.json"
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $payload = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$payload.wave_id -eq $ExpectedWaveId) {
            $matches += $path
        }
    }
    Assert-True ($matches.Count -eq 1) "Expected exactly one closure wave for $ExpectedWaveId, found $($matches.Count)."
    return [string]$matches[0]
}

function Assert-WaveProduct {
    param($Payload, [string]$Name, $Closure)
    Assert-True ([string]$Payload.wave_id -eq [string]$Closure.wave_id) "$Name wave_id mismatch."
    Assert-True ([string]$Payload.parent_wave_id -eq [string]$Closure.parent_wave_id) "$Name parent_wave_id mismatch."
    Assert-True ([string]$Payload.workflow_id -eq [string]$Closure.workflow_id) "$Name workflow_id mismatch."
    if (-not [string]::IsNullOrWhiteSpace([string]$Closure.workflow_run_id)) {
        Assert-True ([string]$Payload.workflow_run_id -eq [string]$Closure.workflow_run_id) "$Name workflow_run_id mismatch."
    }
    Assert-True ([string]$Payload.evidence_digest_sha256 -eq [string]$Closure.evidence_digest_sha256) "$Name digest mismatch."
    $productSource = @($Payload.source_batch_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    $closureSource = @($Closure.source_batch_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    $productBriefs = @($Payload.worker_brief_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    $closureBriefs = @($Closure.worker_brief_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
    Assert-True (($productSource -join "|") -eq ($closureSource -join "|")) "$Name source_batch_ids mismatch."
    Assert-True (($productBriefs -join "|") -eq ($closureBriefs -join "|")) "$Name worker_brief_ids mismatch."
    Assert-True ($null -ne $Payload.same_wave_output_refs) "$Name same_wave_output_refs missing."
}

$closureWavePath = Resolve-ClosureWaveRef -Root $RuntimeRoot -ExpectedWaveId $WaveId -ExplicitRef $ClosureWaveRef
$closure = Read-JsonFile $closureWavePath

if ([string]::IsNullOrWhiteSpace($WaveId)) { $WaveId = [string]$closure.wave_id }
if ([string]::IsNullOrWhiteSpace($WorkflowId)) { $WorkflowId = [string]$closure.workflow_id }
if ([string]::IsNullOrWhiteSpace($WorkflowRunId)) { $WorkflowRunId = [string]$closure.workflow_run_id }

Assert-True ($closure.schema_version -eq "xinao.codex_s.source_frontier_workerpool_closure.v1") "Closure schema mismatch."
Assert-True ([string]$closure.wave_id -eq $WaveId) "Closure wave_id mismatch."
Assert-True ([string]$closure.workflow_id -eq $WorkflowId) "Closure workflow_id mismatch."
if (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) {
    Assert-True ([string]$closure.workflow_run_id -eq $WorkflowRunId) "Closure workflow_run_id mismatch."
}
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$closure.parent_wave_id)) "Closure parent_wave_id missing."
Assert-True ($closure.latest_alias_is_not_proof -eq $true) "Closure latest boundary missing."
Assert-True ($closure.completion_claim_allowed -eq $false) "Closure completion claim incorrectly allowed."
Assert-True ($closure.not_execution_controller -eq $true) "Closure became execution controller."

$output = $closure.output_paths
$requiredOutputNames = @(
    "allocation_plan_snapshot",
    "provider_scheduler_snapshot",
    "staging",
    "merge",
    "fan_in",
    "aaq",
    "next_frontier",
    "repair_plan",
    "worker_dispatch_ledger_wave",
    "worker_dispatch_ledger_activity",
    "readback_zh"
)
foreach ($name in $requiredOutputNames) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$output.$name)) "Closure output path missing: $name"
    Assert-True (Test-Path -LiteralPath ([string]$output.$name) -PathType Leaf) "Closure output evidence missing: $($output.$name)"
}

$bridgeWavePath = [string]$closure.source_frontier_workerbrief_bridge_wave_ref
if ([string]::IsNullOrWhiteSpace($bridgeWavePath)) {
    $bridgeWavePath = Join-Path $RuntimeRoot "state\source_frontier_workerbrief_bridge\waves\$($closure.parent_wave_id).json"
}
$bridge = Read-JsonFile $bridgeWavePath
Assert-True ([string]$bridge.wave_id -eq [string]$closure.parent_wave_id) "Parent bridge wave_id mismatch."
Assert-True ($bridge.validation.passed -eq $true) "Parent bridge validation did not pass."
Assert-True ($bridge.latest_alias_is_not_proof -eq $true) "Parent bridge latest boundary missing."

$bridgeBriefIds = @($bridge.worker_brief_bindings | ForEach-Object { [string]$_.worker_brief_id } | Sort-Object -Unique)
$bridgeSourceIds = @($bridge.worker_brief_bindings | ForEach-Object { [string]$_.source_batch_id } | Sort-Object -Unique)
$closureBriefIds = @($closure.worker_brief_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
$closureSourceIds = @($closure.source_batch_ids | ForEach-Object { [string]$_ } | Sort-Object -Unique)
Assert-True (($bridgeBriefIds -join "|") -eq ($closureBriefIds -join "|")) "Closure worker_brief_ids do not match parent bridge bindings."
Assert-True (($bridgeSourceIds -join "|") -eq ($closureSourceIds -join "|")) "Closure source_batch_ids do not match parent bridge bindings."
Assert-True ([string]$closure.source_bound_worker_brief_queue_ref -eq $bridgeWavePath) "Closure did not bind source queue to parent bridge wave."
Assert-True ($closure.source_bound_worker_brief_queue_latest_fallback_used -eq $false) "Closure used latest queue fallback."
Assert-True ([string]$closure.source_bound_worker_brief_queue_wave_id -eq [string]$closure.parent_wave_id) "Closure source queue wave mismatch."
Assert-True ($closure.validation.checks.source_bound_queue_parent_wave_bound -eq $true) "Validation did not prove parent wave queue binding."
Assert-True ($closure.validation.checks.source_bound_queue_no_latest_fallback -eq $true) "Validation did not reject latest fallback."
Assert-True ($closure.validation.checks.source_batch_ids_match_parent_bridge_queue -eq $true) "Validation did not prove source batch match."

$staging = Read-JsonFile ([string]$output.staging)
$merge = Read-JsonFile ([string]$output.merge)
$fanIn = Read-JsonFile ([string]$output.fan_in)
$aaq = Read-JsonFile ([string]$output.aaq)
$nextFrontier = Read-JsonFile ([string]$output.next_frontier)
$repairPlan = Read-JsonFile ([string]$output.repair_plan)
$ledger = Read-JsonFile ([string]$output.worker_dispatch_ledger_wave)
$activity = Read-JsonFile ([string]$output.worker_dispatch_ledger_activity)
$readback = Get-Content -LiteralPath ([string]$output.readback_zh) -Raw -Encoding UTF8
$allocationPlanSnapshot = Read-JsonFile ([string]$output.allocation_plan_snapshot)
$providerSchedulerSnapshot = Read-JsonFile ([string]$output.provider_scheduler_snapshot)

foreach ($item in @(
    @{ Name = "Staging"; Payload = $staging },
    @{ Name = "Merge"; Payload = $merge },
    @{ Name = "FanIn"; Payload = $fanIn },
    @{ Name = "AAQ"; Payload = $aaq },
    @{ Name = "NextFrontier"; Payload = $nextFrontier }
)) {
    Assert-WaveProduct $item.Payload $item.Name $closure
}

foreach ($item in @(
    @{ Name = "AllocationPlanSnapshot"; Payload = $allocationPlanSnapshot; Ref = [string]$output.allocation_plan_snapshot },
    @{ Name = "ProviderSchedulerSnapshot"; Payload = $providerSchedulerSnapshot; Ref = [string]$output.provider_scheduler_snapshot }
)) {
    Assert-True ([string]$item.Payload.wave_id -eq [string]$closure.wave_id) "$($item.Name) wave_id mismatch."
    Assert-True ([string]$item.Payload.parent_wave_id -eq [string]$closure.parent_wave_id) "$($item.Name) parent_wave_id mismatch."
    Assert-True ([string]$item.Payload.workflow_id -eq [string]$closure.workflow_id) "$($item.Name) workflow_id mismatch."
    if (-not [string]::IsNullOrWhiteSpace([string]$closure.workflow_run_id)) {
        Assert-True ([string]$item.Payload.workflow_run_id -eq [string]$closure.workflow_run_id) "$($item.Name) workflow_run_id mismatch."
    }
    Assert-True ([string]$item.Payload.evidence_digest_sha256 -eq [string]$closure.evidence_digest_sha256) "$($item.Name) digest mismatch."
    Assert-True ([string]$item.Payload.snapshot_ref -eq [string]$item.Ref) "$($item.Name) snapshot ref mismatch."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$item.Payload.source_ref)) "$($item.Name) source_ref missing."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$item.Payload.source_digest_sha256)) "$($item.Name) source digest missing."
    Assert-True ($item.Payload.latest_alias_is_not_proof -eq $true) "$($item.Name) latest boundary missing."
}

Assert-True ($closure.validation.passed -eq $true) "Closure validation did not pass."
Assert-True ($repairPlan.repair_required -eq $false) "Closure has a RepairPlan; requeue repair instead of treating this as ready."
Assert-True ($ledger.immutable_wave_evidence -eq $true) "Worker dispatch ledger is not immutable wave evidence."
Assert-True ([string]$ledger.wave_id -eq $WaveId) "Worker dispatch ledger wave mismatch."
Assert-True ([string]$ledger.parent_wave_id -eq [string]$closure.parent_wave_id) "Worker dispatch ledger parent mismatch."
Assert-True ([string]$ledger.evidence_digest_sha256 -eq [string]$closure.evidence_digest_sha256) "Worker dispatch ledger digest mismatch."
Assert-True ([string]$activity.activity -eq "source_frontier_workerpool_closure") "Activity ledger mismatch."
Assert-True ([string]$activity.evidence_digest_sha256 -eq [string]$closure.evidence_digest_sha256) "Activity ledger digest mismatch."

$requiredChainFields = @(
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
    Assert-True ([string]$chain.wave_id -eq $WaveId) "Acceptance chain wave mismatch."
    Assert-True ([string]$chain.parent_wave_id -eq [string]$closure.parent_wave_id) "Acceptance chain parent mismatch."
    Assert-True ([string]$chain.workflow_id -eq $WorkflowId) "Acceptance chain workflow mismatch."
    if (-not [string]::IsNullOrWhiteSpace($WorkflowRunId)) {
        Assert-True ([string]$chain.workflow_run_id -eq $WorkflowRunId) "Acceptance chain workflow run mismatch."
    }
    Assert-True ([string]$chain.evidence_digest_sha256 -eq [string]$closure.evidence_digest_sha256) "Acceptance chain digest mismatch."
    foreach ($field in $requiredChainFields) {
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$chain.$field)) "Acceptance chain missing $field."
    }
    Assert-True ($bridgeBriefIds -contains [string]$chain.worker_brief_id) "Acceptance chain worker_brief_id not in parent bridge."
    Assert-True ($bridgeSourceIds -contains [string]$chain.source_batch_id) "Acceptance chain source_batch_id not in parent bridge."
    Assert-True ([string]$chain.allocation_plan_ref -eq [string]$output.allocation_plan_snapshot) "Acceptance chain allocation_plan_ref is not wave-specific."
    Assert-True ([string]$chain.provider_scheduler_ref -eq [string]$output.provider_scheduler_snapshot) "Acceptance chain provider_scheduler_ref is not wave-specific."
    Assert-True ([string]$chain.staging_ref -eq [string]$output.staging) "Acceptance chain staging_ref is not wave-specific."
    Assert-True ([string]$chain.merge_ref -eq [string]$output.merge) "Acceptance chain merge_ref is not wave-specific."
    Assert-True ([string]$chain.fan_in_ref -eq [string]$output.fan_in) "Acceptance chain fan_in_ref is not wave-specific."
    Assert-True ([string]$chain.aaq_ref -eq [string]$output.aaq) "Acceptance chain aaq_ref is not wave-specific."
    Assert-True ([string]$chain.next_frontier_ref -eq [string]$output.next_frontier) "Acceptance chain next_frontier_ref is not wave-specific."
    Assert-True (Test-Path -LiteralPath ([string]$chain.provider_invocation_ref) -PathType Leaf) "Provider invocation ref missing: $($chain.provider_invocation_ref)"
}

Assert-True ($readback.Contains("source-bound WorkerBrief")) "Closure readback missing source-bound WorkerBrief statement."
Assert-True ($readback.Contains("SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_V1")) "Closure readback missing sentinel."

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
Write-Output "source_frontier_workerpool_closure_wave=$closureWavePath"
Write-Output "worker_dispatch_ledger_wave=$($output.worker_dispatch_ledger_wave)"
Write-Output "worker_dispatch_ledger_activity=$($output.worker_dispatch_ledger_activity)"
Write-Output "readback_zh=$($output.readback_zh)"
Write-Output "closure_validation=READY_CONTINUE"
Write-Output "SENTINEL:XINAO_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_WAVE_VERIFY_V1"
