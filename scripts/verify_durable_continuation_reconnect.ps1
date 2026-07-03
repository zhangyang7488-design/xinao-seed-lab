[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$TaskId = "durable_continuation_reconnect_20260703",
    [string]$WorkflowId = "durable-continuation-reconnect-verify",
    [string]$WaveId = "durable-continuation-reconnect-wave-01",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$repoRoot = if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    (Get-Location).Path
}
else {
    $RepoRoot
}
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = "$repoRoot\src;$repoRoot"

try {
    Push-Location $repoRoot

    $landingPath = Join-Path $repoRoot "contracts\durable-continuation-reconnect.v1.json"
    Assert-True (Test-Path -LiteralPath $landingPath -PathType Leaf) "durable continuation landing map missing: $landingPath"
    $landing = Get-Content -LiteralPath $landingPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$landing.schema_version -eq "xinao.durable_continuation_reconnect_landing.v1") "landing schema_version mismatch."
    Assert-True ([string]$landing.landed.service -eq "SeedCortexService.durable_continuation_reconnect") "landing service mismatch."
    Assert-True ([string]$landing.landed.cli -like "*durable-continuation-reconnect*") "landing cli mismatch."
    Assert-True ([string]$landing.landed.verifier -eq "scripts/verify_durable_continuation_reconnect.ps1") "landing verifier mismatch."
    Assert-True ($landing.acceptance.default_auto_dispatch_enabled -eq $true) "landing default_auto_dispatch acceptance mismatch."
    Assert-True ($landing.acceptance.live_watch_idle -eq $false) "landing live_watch acceptance mismatch."
    Assert-True ($landing.acceptance.driver_synthetic_succeeded_allowed -eq $false) "landing synthetic succeeded acceptance mismatch."

    $firstOutput = & $Python -m xinao_seedlab.cli.__main__ `
        --runtime-root $RuntimeRoot `
        --repo-root $repoRoot `
        durable-continuation-reconnect `
        --task-id $TaskId `
        --workflow-id $WorkflowId `
        --wave-id $WaveId `
        --intent "durable worker poll auto dispatch reconnect" `
        --worker-result-ref "repo://scripts/verify_durable_continuation_reconnect.ps1#first-worker-result" 2>&1
    $firstExitCode = $LASTEXITCODE
    if ($firstExitCode -ne 0) { $firstOutput | Write-Output }
    Assert-True ($firstExitCode -eq 0) "first durable-continuation-reconnect CLI failed."
    $firstPayload = ($firstOutput -join [Environment]::NewLine) | ConvertFrom-Json

    Assert-True ([string]$firstPayload.schema_version -eq "xinao.durable_continuation_reconnect.v1") "schema_version mismatch."
    Assert-True ([string]$firstPayload.task_id -eq $TaskId) "first task_id mismatch."
    Assert-True ([string]$firstPayload.workflow_id -eq $WorkflowId) "first workflow_id mismatch."
    Assert-True ([string]$firstPayload.wave_id -eq $WaveId) "first wave_id mismatch."
    Assert-True ($firstPayload.validation.passed -eq $true) "first validation failed."
    Assert-True ($firstPayload.workflow_state.checkpoint_persisted -eq $true) "first checkpoint not persisted."
    Assert-True ($firstPayload.worker.worker_enabled -eq $true) "worker not enabled."
    Assert-True ($firstPayload.worker.legacy_5d33_reused -eq $false) "legacy 5d33 was reused."
    Assert-True ($firstPayload.worker.local_runtime_shortcut_used -eq $false) "local runtime shortcut was used."
    Assert-True ([string]$firstPayload.worker_poll.source_kind -eq "worker_dispatch_ledger_poll") "worker poll source mismatch."
    Assert-True ([int]$firstPayload.worker_poll.succeeded_count -ge 1) "first worker ledger succeeded missing."
    Assert-True ([int]$firstPayload.worker_poll.synthetic_succeeded_count -eq 0) "synthetic succeeded detected."
    Assert-True ($firstPayload.worker_poll.driver_synthetic_succeeded_allowed -eq $false) "driver synthetic succeeded allowed."
    Assert-True ($firstPayload.main_chain_reuse.reused -eq $true) "existing main-chain fan-in helper was not reused."
    Assert-True ([string]$firstPayload.main_chain_reuse.source_function -eq "write_lane_results_and_fan_in") "unexpected reused fan-in function."
    Assert-True ($firstPayload.main_chain_reuse.validation_passed -eq $true) "reused fan-in helper validation did not pass."
    Assert-True ($firstPayload.fan_in_acceptance.accepted_edge_count -eq $firstPayload.fan_in_acceptance.ledger_succeeded_count) "fan-in edge count does not match ledger succeeded count."
    Assert-True ([string]$firstPayload.fan_in_acceptance.reused_main_chain_helper -like "*write_lane_results_and_fan_in") "fan-in did not expose reused helper."
    Assert-True ($firstPayload.auto_dispatch.next_wave_dispatched -eq $true) "first next_wave not dispatched."
    Assert-True ([string]$firstPayload.auto_dispatch.dispatch_reason -eq "worker_ledger_succeeded") "first next_wave was not driven by ledger succeeded."
    Assert-True ($firstPayload.default_auto_dispatch.default_enabled -eq $true) "default auto_dispatch not enabled."
    Assert-True ($firstPayload.default_auto_dispatch.main_chain_reused -eq $true) "default auto_dispatch did not reuse main chain."
    Assert-True ($firstPayload.default_auto_dispatch.projection_only -eq $false) "default auto_dispatch is still projection-only."
    Assert-True ($firstPayload.default_auto_dispatch.runtime_enforced -eq $true) "default auto_dispatch is not runtime_enforced."
    Assert-True ($firstPayload.default_auto_dispatch.temporal_ingress_bound -eq $true) "default auto_dispatch is not bound to Temporal ingress."
    Assert-True ($firstPayload.default_auto_dispatch.manual_cli_required -eq $false) "default auto_dispatch still requires manual CLI."
    Assert-True ($firstPayload.default_auto_dispatch.watch_window_required -eq $false) "default auto_dispatch still requires watch window."
    Assert-True ($firstPayload.default_auto_dispatch.replaces_root_intent_loop_controller -eq $false) "default auto_dispatch replaced RootIntentLoop controller."
    Assert-True ($firstPayload.default_auto_dispatch.hardcoded_scheduler_removed -eq $true) "hardcoded scheduler seam still present."
    Assert-True ($firstPayload.default_auto_dispatch.manual_bridge_main_chain -eq $false) "manual Bridge main chain used."
    Assert-True ($firstPayload.live_watch.idle -eq $false) "live_watch is idle."
    Assert-True ([string]$firstPayload.live_watch.state -ne "idle") "live_watch state is idle."
    Assert-True ($firstPayload.live_watch.diagnostic_only -eq $true) "live_watch is not diagnostic-only."
    Assert-True ($firstPayload.live_watch.projection_only -eq $false) "live_watch is still projection-only."
    Assert-True ($firstPayload.live_watch.replaces_live_backend_watch -eq $false) "live_watch replaced backend watch."

    Start-Sleep -Milliseconds 100

    $resumeOutput = & $Python -m xinao_seedlab.cli.__main__ `
        --runtime-root $RuntimeRoot `
        --repo-root $repoRoot `
        durable-continuation-reconnect `
        --task-id $TaskId `
        --resume-from-latest `
        --worker-result-ref "repo://scripts/verify_durable_continuation_reconnect.ps1#resume-worker-result" 2>&1
    $resumeExitCode = $LASTEXITCODE
    if ($resumeExitCode -ne 0) { $resumeOutput | Write-Output }
    Assert-True ($resumeExitCode -eq 0) "resume durable-continuation-reconnect CLI failed."
    $resumePayload = ($resumeOutput -join [Environment]::NewLine) | ConvertFrom-Json

    Assert-True ($resumePayload.validation.passed -eq $true) "resume validation failed."
    Assert-True ($resumePayload.workflow_state.resumed_from_checkpoint -eq $true) "resume did not read checkpoint."
    Assert-True ([string]$resumePayload.workflow_state.previous_checkpoint_wave_id -eq $WaveId) "resume did not keep previous checkpoint wave."
    Assert-True ([int]$resumePayload.worker_poll.succeeded_count -ge 1) "resume worker ledger succeeded missing."
    Assert-True ($resumePayload.main_chain_reuse.reused -eq $true) "resume did not reuse existing main-chain fan-in helper."
    Assert-True ($resumePayload.auto_dispatch.next_wave_dispatched -eq $true) "resume next_wave not dispatched."
    Assert-True ([string]$resumePayload.auto_dispatch.dispatch_reason -eq "worker_ledger_succeeded") "resume next_wave was not driven by ledger succeeded."
    Assert-True ($resumePayload.live_watch.idle -eq $false) "resume live_watch is idle."
    Assert-True ([string]$resumePayload.live_watch.state -ne "idle") "resume live_watch state is idle."
    Assert-True ($resumePayload.live_watch.diagnostic_only -eq $true) "resume live_watch is not diagnostic-only."
    Assert-True ($resumePayload.live_watch.projection_only -eq $false) "resume live_watch is still projection-only."
    Assert-True ($resumePayload.hook_seam.default_auto_dispatch_enabled -eq $true) "hook seam did not expose default auto_dispatch."
    Assert-True ($resumePayload.hook_seam.projection_only -eq $true) "hook seam is not projection-only."
    Assert-True ($resumePayload.hook_seam.replaces_root_intent_loop_controller -eq $false) "hook seam replaced RootIntentLoop controller."

    foreach ($path in @(
        [string]$resumePayload.output_paths.runtime_latest,
        [string]$resumePayload.output_paths.checkpoint_latest,
        [string]$resumePayload.output_paths.worker_dispatch_ledger_latest,
        [string]$resumePayload.output_paths.fan_in_latest,
        [string]$resumePayload.output_paths.next_wave_latest,
        [string]$resumePayload.output_paths.default_auto_dispatch_latest,
        [string]$resumePayload.output_paths.live_watch_latest,
        [string]$resumePayload.output_paths.hook_seam_latest,
        [string]$resumePayload.output_paths.parallel_fan_in_acceptance_latest,
        [string]$resumePayload.output_paths.parallel_lane_results_latest,
        [string]$resumePayload.output_paths.readback_zh
    )) {
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "expected output missing: $path"
    }

    $liveWatch = Get-Content -LiteralPath ([string]$resumePayload.output_paths.live_watch_latest) -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($liveWatch.idle -eq $false) "live_watch_latest is idle."
    Assert-True ([string]$liveWatch.state -ne "idle") "live_watch_latest state is idle."

    $defaultAutoDispatch = Get-Content -LiteralPath ([string]$resumePayload.output_paths.default_auto_dispatch_latest) -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($defaultAutoDispatch.default_enabled -eq $true) "default_auto_dispatch_latest not enabled."
    Assert-True ([string]$defaultAutoDispatch.dispatch_reason -eq "worker_ledger_succeeded") "default_auto_dispatch_latest was not ledger driven."

    $readbackText = Get-Content -LiteralPath ([string]$resumePayload.output_paths.readback_zh) -Raw -Encoding UTF8
    Assert-True ($readbackText.Contains("invoke")) "readback missing invoke section."
    Assert-True ($readbackText.Contains("live_watch.state")) "readback missing live_watch state."

    Write-Output "durable_continuation_latest=$($resumePayload.output_paths.runtime_latest)"
    Write-Output "durable_continuation_checkpoint=$($resumePayload.output_paths.checkpoint_latest)"
    Write-Output "durable_continuation_worker_ledger=$($resumePayload.output_paths.worker_dispatch_ledger_latest)"
    Write-Output "durable_continuation_default_auto_dispatch=$($resumePayload.output_paths.default_auto_dispatch_latest)"
    Write-Output "durable_continuation_live_watch=$($resumePayload.output_paths.live_watch_latest)"
    Write-Output "durable_continuation_hook_seam=$($resumePayload.output_paths.hook_seam_latest)"
    Write-Output "durable_continuation_readback_zh=$($resumePayload.output_paths.readback_zh)"
    Write-Output "durable_continuation_resume_cli=$($resumePayload.can_invoke_now.resume_cli)"
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
