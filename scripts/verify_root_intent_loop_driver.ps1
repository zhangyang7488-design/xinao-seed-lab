[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$WaveId = "codex-s-root-intent-loop-driver-verify-20260703",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Native {
    param([scriptblock]$Command)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $Command 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                [string]$_.Exception.Message
            }
            else {
                [string]$_
            }
        })
        $exitCode = $LASTEXITCODE
        return [pscustomobject]@{
            Output = @($output)
            ExitCode = $exitCode
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "JSON file missing: $Path"
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Get-RefPath {
    param($Ref)
    if ($null -eq $Ref) {
        return ""
    }
    if ($Ref -is [string]) {
        return [string]$Ref
    }
    foreach ($name in @("path", "latest", "poll_latest", "state_ref", "ref", "runtime_latest")) {
        $property = $Ref.PSObject.Properties[$name]
        if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return [string]$property.Value
        }
    }
    return ""
}

function Get-SucceededLedgerEntries {
    param($LedgerPayload)
    $entries = @()
    foreach ($name in @("succeeded_entries", "poll_entries", "dispatch_entries", "ledger_poll_entries")) {
        $property = $LedgerPayload.PSObject.Properties[$name]
        if ($null -ne $property -and $null -ne $property.Value) {
            $entries += @($property.Value)
        }
    }
    return @($entries | Where-Object {
        "$($_.poll_status)" -eq "succeeded" -or
        "$($_.terminal_state)" -eq "succeeded" -or
        "$($_.status)" -eq "succeeded"
    })
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$testPath = Join-Path $repoRoot "tests\seedcortex\test_root_intent_loop_driver.py"
$latestPath = Join-Path $RuntimeRoot "state\root_intent_loop_driver\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\root_intent_loop_driver_20260703.md"
$defaultTriggerEnforcementPath = Join-Path $RuntimeRoot "state\root_intent_loop_driver\default_trigger_enforcement_latest.json"
$defaultTriggerEnforcementReadbackPath = Join-Path $RuntimeRoot "readback\zh\codex_s_333_loop_width_nextwave_20260703.md"
$uniqueAuthorityEntry = "C:\Users\xx363\Desktop\" + [string]([char]0x65B0) + [string]([char]0x7CFB) + [string]([char]0x7EDF)
$sentinel = "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_DRIVER_RUNTIME_ENFORCED"
$defaultTriggerSentinel = "SENTINEL:XINAO_CODEX_S_333_LOOP_WIDTH_TRIGGER_ENFORCED"

Push-Location $repoRoot
try {
    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = "$repoRoot\src;$repoRoot"
    $pytest = Invoke-Native { & $Python -m pytest -q $testPath }
    if ($pytest.ExitCode -ne 0) {
        $pytest.Output | Write-Output
    }
    Assert-True ($pytest.ExitCode -eq 0) "RootIntentLoop driver pytest failed."

    $cli = Invoke-Native { & $Python -m xinao_seedlab.cli.__main__ root-intent-loop-driver `
        --runtime-root $RuntimeRoot `
        --wave-id $WaveId }
    if ($cli.ExitCode -ne 0) {
        $cli.Output | Write-Output
    }
    Assert-True ($cli.ExitCode -eq 0) "RootIntentLoop driver CLI failed."

    $cliText = $cli.Output -join [Environment]::NewLine
    Assert-True ($cliText.Contains($sentinel)) "RootIntentLoop driver sentinel missing from CLI output."

    Assert-True (Test-Path -LiteralPath $latestPath -PathType Leaf) "RootIntentLoop driver latest state missing: $latestPath"
    Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "RootIntentLoop driver readback missing: $readbackPath"
    $latestText = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8
    Assert-True ($latestText.Contains($sentinel)) "RootIntentLoop driver sentinel missing from latest state."
    $readbackText = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
    $lLayerGap = "L " + [string]([char]0x5C42) + [string]([char]0x5DEE) + [string]([char]0x8DDD)
    $l1NoImpersonate = "L1 " + [string]([char]0x4E0D) + [string]([char]0x5F97) + [string]([char]0x5192) + [string]([char]0x5145)
    Assert-True ($readbackText.Contains($lLayerGap)) "RootIntentLoop driver readback missing L-layer gap section."
    Assert-True ($readbackText.Contains($l1NoImpersonate)) "RootIntentLoop driver readback missing L1/L3 boundary."

    $latestPayload = $latestText | ConvertFrom-Json
    Assert-True ([string]$latestPayload.wave_id -eq $WaveId) "RootIntentLoop driver latest state wave_id mismatch."
    Assert-True ($latestPayload.validation.passed -eq $true) "RootIntentLoop validation did not pass."
    Assert-True ($latestPayload.validation.checks.worker_dispatch_ledger_succeeded_present -eq $true) "RootIntentLoop validation passed without worker_dispatch_ledger succeeded evidence."
    Assert-True ($latestPayload.validation.checks.fan_in_from_worker_dispatch_ledger_poll -eq $true) "RootIntentLoop validation passed without fan-in from worker_dispatch_ledger poll."
    Assert-True ($latestPayload.validation.checks.no_driver_synthetic_succeeded_lane_results -eq $true) "RootIntentLoop validation allowed driver synthetic succeeded lane results."

    Assert-True ([string]$latestPayload.worker_dispatch_ledger.source_kind -eq "worker_dispatch_ledger_poll") "RootIntentLoop worker ledger source_kind must be worker_dispatch_ledger_poll."
    Assert-True ([string]$latestPayload.worker_dispatch_ledger.poll_source -eq "worker_dispatch_ledger_poll") "RootIntentLoop worker ledger poll_source must be worker_dispatch_ledger_poll."
    Assert-True ($latestPayload.worker_dispatch_ledger.driver_synthetic_succeeded_allowed -eq $false) "RootIntentLoop allowed driver synthetic succeeded."
    Assert-True ([int]$latestPayload.worker_dispatch_ledger.succeeded_count -ge 1) "RootIntentLoop latest has no worker_dispatch_ledger succeeded count."

    $workerLedgerPath = Get-RefPath $latestPayload.worker_dispatch_ledger.latest
    if ([string]::IsNullOrWhiteSpace($workerLedgerPath)) {
        $workerLedgerPath = Join-Path $RuntimeRoot "state\worker_dispatch_ledger\latest.json"
    }
    $workerLedgerPayload = Read-JsonFile $workerLedgerPath
    $succeededLedgerEntries = @(Get-SucceededLedgerEntries $workerLedgerPayload)
    Assert-True (@($succeededLedgerEntries).Count -ge 1) "worker_dispatch_ledger has no succeeded poll entries."

    Assert-True ($latestPayload.fan_in_acceptance.consumed_scheduler_lane_results -eq $true) "RootIntentLoop fan-in did not consume lane results."
    Assert-True ([string]$latestPayload.fan_in_acceptance.source_kind -eq "worker_dispatch_ledger_poll") "RootIntentLoop fan-in source_kind must be worker_dispatch_ledger_poll."
    Assert-True ([int]$latestPayload.fan_in_acceptance.worker_dispatch_ledger_succeeded_count -ge 1) "RootIntentLoop fan-in has no worker_dispatch_ledger succeeded count."
    Assert-True ($latestPayload.fan_in_acceptance.driver_synthetic_succeeded_allowed -eq $false) "RootIntentLoop fan-in allowed driver synthetic succeeded."
    Assert-True ($latestPayload.fan_in_acceptance.before_artifact_acceptance -eq $true) "RootIntentLoop fan-in did not run before ArtifactAcceptance."
    Assert-True ([int]$latestPayload.fan_in_acceptance.lane_result_count -eq [int]$latestPayload.scheduler_default_runtime.scheduler_spawned_lane_count) "RootIntentLoop fan-in lane count mismatch."
    Assert-True ([int]$latestPayload.fan_in_acceptance.accepted_edge_count -eq [int]$latestPayload.fan_in_acceptance.ledger_succeeded_count) "RootIntentLoop fan-in accepted edge count mismatch."
    Assert-True ($latestPayload.validation.checks.fan_in_accepted_edge_count_matches_ledger_succeeded -eq $true) "RootIntentLoop validation check for accepted edge count mismatch is false."
    Assert-True ($latestPayload.validation.checks.dp_nonprobe_true_invocation_present -eq $true) "RootIntentLoop missing non-provider-probe DP true invoke."
    Assert-True ($latestPayload.validation.checks.provider_probe_not_bulk_progress -eq $true) "RootIntentLoop allowed provider_probe bulk progress."

    Assert-True (Test-Path -LiteralPath $defaultTriggerEnforcementPath -PathType Leaf) "RootIntentLoop default trigger enforcement state missing: $defaultTriggerEnforcementPath"
    Assert-True (Test-Path -LiteralPath $defaultTriggerEnforcementReadbackPath -PathType Leaf) "RootIntentLoop default trigger enforcement readback missing: $defaultTriggerEnforcementReadbackPath"
    Assert-True ([string]$latestPayload.evidence_refs.default_trigger_enforcement_latest -eq $defaultTriggerEnforcementPath) "RootIntentLoop latest does not point at default_trigger_enforcement_latest."
    Assert-True ([string]$latestPayload.readback_refs.default_trigger_enforcement_readback_zh -eq $defaultTriggerEnforcementReadbackPath) "RootIntentLoop latest does not point at default_trigger_enforcement_readback_zh."
    Assert-True ([string]$latestPayload.default_trigger_enforcement.latest -eq $defaultTriggerEnforcementPath) "RootIntentLoop default trigger enforcement latest ref mismatch."
    Assert-True ([string]$latestPayload.default_trigger_enforcement.readback_zh -eq $defaultTriggerEnforcementReadbackPath) "RootIntentLoop default trigger enforcement readback ref mismatch."
    Assert-True ($latestPayload.default_trigger_enforcement.trigger_enforced -eq $true) "RootIntentLoop default trigger enforcement summary is not trigger_enforced=true."
    Assert-True ([string]$latestPayload.default_trigger_enforcement.unique_authority_entry -eq $uniqueAuthorityEntry) "RootIntentLoop default trigger enforcement summary has wrong unique authority entry."

    $defaultTriggerPayload = Read-JsonFile $defaultTriggerEnforcementPath
    Assert-True ([string]$defaultTriggerPayload.sentinel -eq $defaultTriggerSentinel) "Default trigger enforcement sentinel mismatch."
    Assert-True ($defaultTriggerPayload.trigger_enforced -eq $true) "Default trigger enforcement trigger_enforced must be true."
    Assert-True ([string]$defaultTriggerPayload.unique_authority_entry -eq $uniqueAuthorityEntry) "Default trigger enforcement unique_authority_entry must be C:\Users\xx363\Desktop\new-system authority folder."
    Assert-True ([int]$defaultTriggerPayload.nonprobe_true_invocation_count -gt 0) "Default trigger enforcement requires nonprobe_true_invocation_count > 0."
    Assert-True ($defaultTriggerPayload.provider_probe_bulk_progress_allowed -eq $false) "Default trigger enforcement must keep provider_probe_bulk_progress_allowed=false."
    $canInvokeNowProperty = $defaultTriggerPayload.PSObject.Properties["can_invoke_now"]
    Assert-True ($null -ne $canInvokeNowProperty -and $null -ne $canInvokeNowProperty.Value) "Default trigger enforcement missing can_invoke_now."
    Assert-True ($defaultTriggerPayload.validation.passed -eq $true) "Default trigger enforcement validation did not pass."
    Assert-True ($defaultTriggerPayload.validation.checks.dp_nonprobe_true_invocation_present -eq $true) "Default trigger enforcement validation missing non-provider-probe DP true invoke."
    Assert-True ($defaultTriggerPayload.validation.checks.provider_probe_not_bulk_progress -eq $true) "Default trigger enforcement validation allowed provider_probe bulk progress."

    $defaultTriggerReadbackText = Get-Content -LiteralPath $defaultTriggerEnforcementReadbackPath -Raw -Encoding UTF8
    Assert-True ($defaultTriggerReadbackText.Contains($defaultTriggerSentinel)) "Default trigger enforcement readback sentinel missing."
    Assert-True ($defaultTriggerReadbackText.Contains("can_invoke.runtime_chain")) "Default trigger enforcement readback missing can_invoke runtime chain."

    $laneResultsPath = Get-RefPath $latestPayload.fan_in_acceptance.lane_results_latest
    $laneResultsPayload = Read-JsonFile $laneResultsPath
    Assert-True ([string]$laneResultsPayload.source_kind -eq "worker_dispatch_ledger_poll") "RootIntentLoop lane results are not from worker_dispatch_ledger poll."
    Assert-True ([int]$laneResultsPayload.worker_dispatch_ledger_succeeded_count -ge 1) "RootIntentLoop lane results have no worker ledger succeeded count."
    Assert-True ($laneResultsPayload.driver_synthetic_succeeded_allowed -eq $false) "RootIntentLoop lane results allowed driver synthetic succeeded."
    Assert-True ($laneResultsPayload.validation.checks.worker_dispatch_ledger_succeeded_present -eq $true) "RootIntentLoop lane results missing worker ledger succeeded validation."
    Assert-True ($laneResultsPayload.validation.checks.lane_results_source_worker_dispatch_ledger_poll -eq $true) "RootIntentLoop lane results missing worker ledger poll validation."
    Assert-True ($laneResultsPayload.validation.checks.no_driver_synthetic_succeeded_lane_results -eq $true) "RootIntentLoop lane results allowed synthetic succeeded validation."

    foreach ($laneResultRef in @($laneResultsPayload.lane_result_refs)) {
        $laneResultPayload = Read-JsonFile ([string]$laneResultRef)
        if ("$($laneResultPayload.terminal_state)" -eq "succeeded") {
            Assert-True ([string]$laneResultPayload.source_kind -eq "worker_dispatch_ledger_poll") "Succeeded lane result is not sourced from worker_dispatch_ledger poll: $laneResultRef"
            Assert-True ([string]$laneResultPayload.worker_dispatch_ledger_poll_status -eq "succeeded") "Succeeded lane result missing worker_dispatch_ledger poll_status=succeeded: $laneResultRef"
            Assert-True (-not [string]::IsNullOrWhiteSpace([string]$laneResultPayload.worker_dispatch_ledger_entry_ref)) "Succeeded lane result missing worker_dispatch_ledger entry ref: $laneResultRef"
            Assert-True ($laneResultPayload.synthetic_succeeded_by_driver -eq $false) "Succeeded lane result was synthetic driver success: $laneResultRef"
        }
    }

    $fanInPath = Get-RefPath $latestPayload.fan_in_acceptance.fan_in_acceptance_latest
    $fanInPayload = Read-JsonFile $fanInPath
    Assert-True ([string]$fanInPayload.source_kind -eq "worker_dispatch_ledger_poll") "RootIntentLoop fan-in artifact is not sourced from worker_dispatch_ledger poll."
    Assert-True ($fanInPayload.driver_synthetic_succeeded_allowed -eq $false) "RootIntentLoop fan-in artifact allowed driver synthetic succeeded."
    foreach ($edge in @($fanInPayload.accepted_edges)) {
        Assert-True ([string]$edge.source_kind -eq "worker_dispatch_ledger_poll") "Fan-in accepted edge is not sourced from worker_dispatch_ledger poll."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$edge.worker_dispatch_ledger_entry_id)) "Fan-in accepted edge missing worker_dispatch_ledger_entry_id."
    }

    Write-Output "root_intent_loop_driver_pytest=$testPath"
    Write-Output "root_intent_loop_driver_runtime_root=$RuntimeRoot"
    Write-Output "root_intent_loop_driver_wave_id=$WaveId"
    Write-Output "worker_dispatch_ledger_latest=$workerLedgerPath"
    Write-Output "root_intent_loop_driver_latest=$latestPath"
    Write-Output "default_trigger_enforcement_latest=$defaultTriggerEnforcementPath"
    Write-Output "default_trigger_enforcement_readback_zh=$defaultTriggerEnforcementReadbackPath"
    Write-Output "validation_result=PASS"
    Write-Output $sentinel
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
