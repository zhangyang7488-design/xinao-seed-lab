[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Python = "",
    [string]$WaveId = "",
    [string]$WorkflowId = "",
    [string]$TaskQueue = "xinao-codex-task-default",
    [string[]]$SourceRef = @(),
    [string]$WorkPackageJson = "",
    [switch]$ForceInvoke,
    [switch]$RunLiveTemporal,
    [switch]$SkipLocalDriver,
    [switch]$BindProviderWorkerPool,
    [switch]$DisableSourceFrontierWorkerpoolClosure,
    [int]$Phase1TargetWidth = 24,
    [int]$Phase1MaxParallelWorkers = 12,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Payload
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$stateDir = Join-Path $RuntimeRoot "state\root_intent_loop_driver_hook"
$latestPath = Join-Path $stateDir "latest.json"
$stopAuditPath = Join-Path $RuntimeRoot "state\codex_s_stop_continuation_audit\latest.json"
$stopAudit = Read-JsonFile -Path $stopAuditPath
$packet = $null
if ($null -ne $stopAudit -and $null -ne $stopAudit.next_loop_packet) {
    $packet = $stopAudit.next_loop_packet
}

$packetContinue = $false
foreach ($key in @("should_continue_loop", "restore", "dispatch", "poll", "fan_in", "verify_evidence_readback", "recompute_capacity", "next_wave")) {
    if ($null -ne $packet -and $packet.PSObject.Properties.Name -contains $key -and $packet.$key -eq $true) {
        $packetContinue = $true
    }
}
$auditContinue = (
    ($null -ne $stopAudit -and $stopAudit.should_continue_loop -eq $true) -or
    ($null -ne $stopAudit -and $stopAudit.stop_handoff_available -eq $true) -or
    $packetContinue
)
$explicitUserStopRequested = (
    ($null -ne $stopAudit -and $null -ne $stopAudit.report_stop_surface -and $stopAudit.report_stop_surface.explicit_user_stop_requested -eq $true) -or
    ($null -ne $packet -and $null -ne $packet.front_gate -and [string]$packet.front_gate -eq "explicit_user_stop_override")
)
if ($explicitUserStopRequested) {
    $auditContinue = $false
}
if ($ForceInvoke) {
    $auditContinue = $true
    $explicitUserStopRequested = $false
}

$waveId = if ([string]::IsNullOrWhiteSpace($WaveId)) {
    "codex-s-root-intent-loop-hook-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
} else {
    $WaveId
}
$canonicalMainlineWorkflowId = "codex-s-333-mainline-p0-20260707-r9-task-package-resolver-global-hardened"
$current333RunIndexPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$current333RunIndex = Read-JsonFile -Path $current333RunIndexPath
$workflowIdSource = "explicit_parameter"
$workflowIdSourceStatus = "provided"
if ([string]::IsNullOrWhiteSpace($WorkflowId)) {
    $currentIndexWorkflowId = ""
    if (
        $null -ne $current333RunIndex -and
        [string]$current333RunIndex.status -eq "current_333_run_index_ready" -and
        -not [string]::IsNullOrWhiteSpace([string]$current333RunIndex.workflow_id)
    ) {
        $currentIndexWorkflowId = [string]$current333RunIndex.workflow_id
    }
    if (-not [string]::IsNullOrWhiteSpace($currentIndexWorkflowId)) {
        $workflowIdValue = $currentIndexWorkflowId
        $workflowIdSource = "current_333_run_index"
        $workflowIdSourceStatus = "ready"
    } else {
        $workflowIdValue = $canonicalMainlineWorkflowId
        $workflowIdSource = "canonical_mainline_default"
        $workflowIdSourceStatus = "current_index_missing_or_not_ready"
    }
} else {
    $workflowIdValue = $WorkflowId
}
$record = [ordered]@{
    schema_version = "xinao.codex_s.root_intent_loop_driver_hook.v1"
    status = "transfer_not_invoked"
    generated_at = (Get-Date).ToString("o")
    runtime_root = $RuntimeRoot
    repo_root = $RepoRoot
    stop_audit_ref = $stopAuditPath
    audit_should_continue_loop = [bool]$auditContinue
    force_invoke = [bool]$ForceInvoke
    live_temporal_requested = [bool]$RunLiveTemporal
    skip_local_driver = [bool]$SkipLocalDriver
    explicit_user_stop_requested = [bool]$explicitUserStopRequested
    stop_hook_transfer_only = $true
    stop_hook_controller = $false
    stop_hook_is_controller = $false
    stop_hook_is_completion_gate = $false
    stop_hook_dispatches_main_execution_loop_directly = $false
    stop_hook_writes_worker_dispatch_ledger = $false
    root_intent_loop_driver_is_controller = $false
    root_intent_loop_driver_invoked_by_stop_hook_transfer = $false
    root_intent_loop_driver_runtime_enforced_by_hook = $false
    root_intent_loop_driver_owns_runtime_scope_if_invoked = $true
    wave_id = $waveId
    workflow_id = $workflowIdValue
    workflow_id_source = $workflowIdSource
    workflow_id_source_status = $workflowIdSourceStatus
    workflow_id_conflict_policy = "UseExisting_or_Fail_for_default_mainline"
    current_333_run_index_ref = $current333RunIndexPath
    completion_claim_allowed = $false
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
    not_completion_gate = $true
    fail_open = $true
    runtime_enforced_scope = "Stop hook wrapper is transfer-only: it may invoke the RootIntentLoop driver when stop audit says continue, but it does not become the controller, completion gate, worker ledger writer, or main-loop decision authority."
    sentinel = "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_TRANSFER_ONLY_HOOK"
}

try {
    if (-not $auditContinue) {
        $record.status = "skipped_stop_handoff_not_active"
        Write-JsonFile -Path $latestPath -Payload $record
        if (-not $Quiet) {
            $record | ConvertTo-Json -Depth 20
        }
        return
    }

    if (-not $Python) {
        $repoPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
        if (Test-Path -LiteralPath $repoPython -PathType Leaf) {
            $Python = $repoPython
        } else {
            $Python = "python"
        }
    }

    Push-Location $RepoRoot
    try {
        $oldPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
        $anchorPackageRoot = Join-Path "C:\Users\xx363\Desktop" (
            [string]([char]0x65B0) + [string]([char]0x7CFB) + [string]([char]0x7EDF)
        )
        $pythonArgs = @(
            "-m",
            "xinao_seedlab.cli.__main__",
            "root-intent-loop-driver",
            "--runtime-root",
            $RuntimeRoot,
            "--anchor-package-root",
            $anchorPackageRoot,
            "--wave-id",
            $waveId
        )
        if ($BindProviderWorkerPool) {
            $pythonArgs += @(
                "--bind-provider-worker-pool",
                "--phase1-target-width",
                [string]$Phase1TargetWidth,
                "--phase1-max-parallel-workers",
                [string]$Phase1MaxParallelWorkers,
                "--workflow-id",
                $workflowIdValue
            )
        }
        if ($SkipLocalDriver) {
            $output = @("local RootIntentLoop CLI skipped; live Temporal workflow requested from RootIntentLoop entry wrapper.")
            $exitCode = 0
        } else {
            $output = @(& $Python @pythonArgs 2>&1)
            $exitCode = $LASTEXITCODE
        }
        $temporalOutput = @()
        $temporalExitCode = $null
        if ($RunLiveTemporal) {
            $temporalArgs = @(
                "-m",
                "services.agent_runtime.temporal_codex_task_workflow",
                "--task-id",
                "xinao_seed_cortex_phase0_20260701",
                "--user-goal",
                "333_default_chain_global_repair_20260705 RootIntentLoop / S Default Dynamic Loop",
                "--mode",
                "partial",
                "--runtime-root",
                $RuntimeRoot,
                "--live-temporal",
                "--task-queue",
                $TaskQueue,
                "--workflow-id",
                $workflowIdValue,
                "--anchor-package-root",
                $anchorPackageRoot,
                "--no-promote-current-task-owner-latest"
            )
            if ($BindProviderWorkerPool) {
                $temporalArgs += @(
                    "--bind-provider-worker-pool",
                    "--phase1-target-width",
                    [string]$Phase1TargetWidth,
                    "--phase1-max-parallel-workers",
                    [string]$Phase1MaxParallelWorkers
                )
            }
            if ($DisableSourceFrontierWorkerpoolClosure) {
                $temporalArgs += @("--disable-source-frontier-workerpool-closure")
            }
            if (-not [string]::IsNullOrWhiteSpace($WorkPackageJson)) {
                $temporalArgs += @("--work-package-json", $WorkPackageJson)
            }
            foreach ($ref in @($SourceRef)) {
                if (-not [string]::IsNullOrWhiteSpace($ref)) {
                    $temporalArgs += @("--source-ref", $ref)
                }
            }
            $temporalOutput = @(& $Python @temporalArgs 2>&1)
            $temporalExitCode = $LASTEXITCODE
        }
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
        Pop-Location
    }

    $driverLatestPath = Join-Path $RuntimeRoot "state\root_intent_loop_driver\latest.json"
    $driverLatest = Read-JsonFile -Path $driverLatestPath
    $temporalLatestPath = Join-Path $RuntimeRoot "state\temporal_codex_task_workflow\latest.json"
    $temporalLatest = Read-JsonFile -Path $temporalLatestPath
    $driverValidationPassed = (
        $null -ne $driverLatest -and
        $null -ne $driverLatest.validation -and
        $driverLatest.validation.passed -eq $true
    )
    $driverSentinelVerified = (
        $null -ne $driverLatest -and
        [string]$driverLatest.sentinel -eq "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_DRIVER_RUNTIME_ENFORCED"
    )
    $driverLatestVerified = (
        ($SkipLocalDriver -or $exitCode -eq 0) -and
        (Test-Path -LiteralPath $driverLatestPath -PathType Leaf) -and
        $driverValidationPassed -and
        $driverSentinelVerified
    )
    $liveTemporalVerified = (
        $RunLiveTemporal -and
        $temporalExitCode -eq 0 -and
        $null -ne $temporalLatest -and
        $temporalLatest.server_bound -eq $true -and
        [string]$temporalLatest.workflow_id -eq $workflowIdValue -and
        -not [string]::IsNullOrWhiteSpace([string]$temporalLatest.workflow_run_id)
    )

    $record.status = if ($driverLatestVerified -and (-not $RunLiveTemporal -or $liveTemporalVerified)) {
        "transfer_invoked_driver_verified"
    } elseif ($liveTemporalVerified) {
        "transfer_invoked_live_temporal_verified"
    } else {
        "transfer_invoked_driver_failed_open"
    }
    $record.exit_code = $exitCode
    $record.output_tail = @($output | Select-Object -Last 20)
    $record.live_temporal_exit_code = $temporalExitCode
    $record.live_temporal_output_tail = @($temporalOutput | Select-Object -Last 20)
    $record.temporal_workflow_latest_ref = $temporalLatestPath
    $record.temporal_workflow_id = if ($null -ne $temporalLatest) { [string]$temporalLatest.workflow_id } else { "" }
    $record.temporal_workflow_run_id = if ($null -ne $temporalLatest) { [string]$temporalLatest.workflow_run_id } else { "" }
    $record.temporal_task_queue = if ($null -ne $temporalLatest) { [string]$temporalLatest.task_queue } else { $TaskQueue }
    $record.temporal_server_bound = ($null -ne $temporalLatest -and $temporalLatest.server_bound -eq $true)
    $record.temporal_live_route = ($null -ne $temporalLatest -and $temporalLatest.temporal_live_route -eq $true)
    $record.temporal_local_run_observed = ($null -ne $temporalLatest -and $temporalLatest.local_run_observed -eq $true)
    $record.live_temporal_verified = [bool]$liveTemporalVerified
    $record.driver_latest_ref = $driverLatestPath
    $record.driver_latest_exists = Test-Path -LiteralPath $driverLatestPath -PathType Leaf
    $record.driver_latest_status = if ($null -ne $driverLatest -and $driverLatest.status) { [string]$driverLatest.status } else { "" }
    $record.driver_latest_validation_passed = [bool]$driverValidationPassed
    $record.driver_latest_sentinel_verified = [bool]$driverSentinelVerified
    $record.root_intent_loop_driver_invoked_by_stop_hook_transfer = $true
    $record.root_intent_loop_driver_runtime_enforced_by_hook = $false
    $record.driver_runtime_enforced_scope = "owned_by_root_intent_loop_driver_payload_only_if_driver_latest_verifies; not owned by Stop hook wrapper"
    if (-not $driverLatestVerified) {
        $record.named_blocker = if ($exitCode -ne 0) { "ROOT_INTENT_LOOP_DRIVER_HOOK_INVOCATION_FAILED" } else { "ROOT_INTENT_LOOP_DRIVER_HOOK_INVOCATION_UNVERIFIED" }
    }
    Write-JsonFile -Path $latestPath -Payload $record
}
catch {
    $record.status = "transfer_failed_open"
    $record.named_blocker = "ROOT_INTENT_LOOP_DRIVER_HOOK_FAILED_OPEN"
    $record.error_type = $_.Exception.GetType().FullName
    $record.error = $_.Exception.Message
    Write-JsonFile -Path $latestPath -Payload $record
}

if (-not $Quiet) {
    $record | ConvertTo-Json -Depth 20
}
