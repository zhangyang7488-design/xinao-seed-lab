[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$stdinReader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $stdinReader.ReadToEnd()
$event = $null
try {
    if ($raw.Trim()) {
        $event = $raw | ConvertFrom-Json
    }
} catch {
    $event = $null
}

$eventName = if ($event -and $event.hook_event_name) { [string]$event.hook_event_name } else { "Stop" }
$turnId = if ($event -and $event.turn_id) { [string]$event.turn_id } else { "" }
$message = if ($event -and $event.last_assistant_message) { [string]$event.last_assistant_message } else { "" }
$userMessage = ""
if ($event -and $event.user_prompt) {
    $userMessage = [string]$event.user_prompt
}
elseif ($event -and $event.last_user_message) {
    $userMessage = [string]$event.last_user_message
}
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$metaMinuteScript = Join-Path $PSScriptRoot "Invoke-CodexSMetaMinutePreflight.ps1"
$liveBackendWatchRunner = Join-Path $repoRoot "services\agent_runtime\codex_s_live_backend_watch.py"
$sourceAnchorGapRunner = Join-Path $repoRoot "services\agent_runtime\source_anchor_gap_continuation.py"
$loopRuntimeStatePath = Join-Path $RuntimeRoot "state\loop_runtime_state\latest.json"
$legacyPhase2LoopRuntimeStatePath = Join-Path $RuntimeRoot "state\loop_runtime_state_supervisor_worker_pool_phase2_20260704\latest.json"
$maxBenefitDynamicLoopAuthoritySpec = Join-Path $RuntimeRoot "specs\max_benefit_dynamic_loop_authority_20260702.v1.md"

function Invoke-MetaMinuteCheckpoint {
    param(
        [string]$Trigger,
        [string]$CurrentUserObject,
        [string]$LatestUserDelta
    )

    if (-not (Test-Path -LiteralPath $metaMinuteScript -PathType Leaf)) { return }
    try {
        & $metaMinuteScript `
            -Trigger $Trigger `
            -Event $eventName `
            -RawEventJson $raw `
            -CurrentUserObject $CurrentUserObject `
            -LatestUserDelta $LatestUserDelta `
            -RepoRoot $repoRoot `
            -RuntimeRoot $RuntimeRoot `
            -Quiet | Out-Null
    }
    catch {
        # MetaMinute is a fail-open checkpoint, not a hook denial source.
    }
}

Invoke-MetaMinuteCheckpoint `
    -Trigger "before_final_pass_report" `
    -CurrentUserObject "Codex S Stop hook final/PASS/report surface" `
    -LatestUserDelta "Stop hook invoked; run MetaMinute before any final/PASS/report stop semantics"

function Invoke-StopGuardLayerRunners {
    param(
        [bool]$ExplicitUserStopRequested,
        [bool]$ContinuationModeActive
    )

    $refs = [ordered]@{
        live_backend_watch = [ordered]@{
            runner = ConvertTo-JsonSafePath $liveBackendWatchRunner
            invoked = $false
            exit_code = $null
            latest_ref = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\codex_s_live_backend_watch\latest.json")
            adoption_state_expected = "verifier_ready_but_not_hooked"
            not_execution_controller = $true
        }
        source_anchor_gap_continuation = [ordered]@{
            runner = ConvertTo-JsonSafePath $sourceAnchorGapRunner
            invoked = $false
            exit_code = $null
            latest_ref = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\source_anchor_gap_continuation\latest.json")
            adoption_state_expected = "verifier_ready_but_not_hooked"
            not_execution_controller = $true
        }
        fail_open = $true
        runners_are_decision_controllers = $true
        runners_are_stop_decision_inputs = $true
        standalone_runner_latest_adoption_state = "verifier_ready_but_not_hooked"
        stop_hook_runner_invocation_adoption_state = "runtime_enforced"
        stop_guard_layers_runtime_enforced_scope = "stop_continue_protocol_decision"
        stop_continue_protocol_controller = $true
        main_execution_loop_runtime_enforced_by_stop_hook = $false
        stop_hook_dispatches_main_execution_loop = $false
        stop_hook_writes_worker_dispatch_ledger = $false
        runtime_enforced_scope = "S Stop hook runtime_enforced covers report-then-continue Stop protocol decision using live-backend/source-anchor runners; it does not directly execute main_execution_loop, durable_parallel_wave_packet, worker_dispatch_ledger, or codex_s_main_execution_loop_tick."
    }

    if (Test-Path -LiteralPath $liveBackendWatchRunner -PathType Leaf) {
        $args = @($liveBackendWatchRunner, "--repo-root", $repoRoot, "--runtime-root", $RuntimeRoot)
        if ($ExplicitUserStopRequested) { $args += "--explicit-user-stop" }
        $output = & python @args 2>&1
        $refs.live_backend_watch.invoked = $true
        $refs.live_backend_watch.exit_code = $LASTEXITCODE
        $refs.live_backend_watch.output_tail = (($output | Select-Object -Last 4) -join "`n")
    }

    if (Test-Path -LiteralPath $sourceAnchorGapRunner -PathType Leaf) {
        $args = @($sourceAnchorGapRunner, "--repo-root", $repoRoot, "--runtime-root", $RuntimeRoot)
        if ($ExplicitUserStopRequested) { $args += "--explicit-user-stop" }
        if ($ContinuationModeActive) { $args += "--continuation-mode-active" }
        $output = & python @args 2>&1
        $refs.source_anchor_gap_continuation.invoked = $true
        $refs.source_anchor_gap_continuation.exit_code = $LASTEXITCODE
        $refs.source_anchor_gap_continuation.output_tail = (($output | Select-Object -Last 4) -join "`n")
    }

    return $refs
}

function Test-TruthyValue {
    param([object]$Value)

    if ($null -eq $Value) { return $false }
    if ($Value -is [bool]) { return [bool]$Value }
    if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int] -or $Value -is [int64]) {
        return ([int64]$Value -ne 0)
    }

    $text = ([string]$Value).Trim().ToLowerInvariant()
    return @("true", "1", "yes") -contains $text
}

function Test-ExplicitTruthyProperty {
    param(
        [object]$Node,
        [string]$PropertyName
    )

    if ($null -eq $Node) { return $false }

    if ($Node -is [System.Array]) {
        foreach ($item in $Node) {
            if (Test-ExplicitTruthyProperty -Node $item -PropertyName $PropertyName) { return $true }
        }
        return $false
    }

    if ($Node -is [System.Collections.IDictionary]) {
        foreach ($key in $Node.Keys) {
            if ([string]::Equals([string]$key, $PropertyName, [System.StringComparison]::OrdinalIgnoreCase)) {
                if (Test-TruthyValue -Value $Node[$key]) { return $true }
            }
            if (Test-ExplicitTruthyProperty -Node $Node[$key] -PropertyName $PropertyName) { return $true }
        }
        return $false
    }

    if ($Node -is [pscustomobject]) {
        foreach ($prop in $Node.PSObject.Properties) {
            if ([string]::Equals($prop.Name, $PropertyName, [System.StringComparison]::OrdinalIgnoreCase)) {
                if (Test-TruthyValue -Value $prop.Value) { return $true }
            }
            if (Test-ExplicitTruthyProperty -Node $prop.Value -PropertyName $PropertyName) { return $true }
        }
    }

    return $false
}

function Get-LoopRuntimeStateSummary {
    $selectedLoopRuntimeStatePath = $loopRuntimeStatePath
    if (-not (Test-Path -LiteralPath $selectedLoopRuntimeStatePath -PathType Leaf) -and (Test-Path -LiteralPath $legacyPhase2LoopRuntimeStatePath -PathType Leaf)) {
        $selectedLoopRuntimeStatePath = $legacyPhase2LoopRuntimeStatePath
    }
    $summary = [ordered]@{
        exists = $false
        latest_ref = ConvertTo-JsonSafePath $selectedLoopRuntimeStatePath
        canonical_ref = ConvertTo-JsonSafePath $loopRuntimeStatePath
        fallback_ref = ConvertTo-JsonSafePath $legacyPhase2LoopRuntimeStatePath
        using_legacy_phase2_fallback = ($selectedLoopRuntimeStatePath -eq $legacyPhase2LoopRuntimeStatePath)
        stop_allowed = $null
        stop_reason = ""
        task_backlog_count = 0
        ready_frontier_count = 0
        draft_staged_count = 0
        draft_unmerged_count = 0
        merge_backlog_count = 0
        fan_in_backlog_count = 0
        evidence_backlog_count = 0
        source_gap_count = 0
        blocker_count = 0
        next_frontier_count = 0
        queue_consumer_main_loop = $false
        event_queue_driven_main_loop = $false
        temporal_activity_main_loop = $false
        sleep_1800_default_allowed = $false
        stop_hook_reads_only = $true
        stop_hook_dispatches_main_loop = $false
        stop_hook_writes_worker_dispatch_ledger = $false
    }
    if (-not (Test-Path -LiteralPath $selectedLoopRuntimeStatePath -PathType Leaf)) {
        return $summary
    }
    try {
        $payload = Get-Content -LiteralPath $selectedLoopRuntimeStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $summary.exists = $true
        $summary.stop_allowed = if ($null -ne $payload.stop.stop_allowed) { [bool]$payload.stop.stop_allowed } else { $null }
        $summary.stop_reason = [string]$payload.stop.stop_reason
        $summary.task_backlog_count = @($payload.task_backlog).Count
        $summary.ready_frontier_count = @($payload.ready_frontier).Count
        $summary.draft_staged_count = [int]($payload.draft_staging.staged_count)
        $summary.draft_unmerged_count = [int]($payload.draft_staging.unmerged_count)
        $summary.merge_backlog_count = @($payload.merge_backlog).Count
        $summary.fan_in_backlog_count = @($payload.fan_in_backlog).Count
        $summary.evidence_backlog_count = @($payload.evidence_backlog).Count
        $summary.source_gap_count = @($payload.source_gaps).Count
        $summary.blocker_count = @($payload.blockers).Count
        $summary.next_frontier_count = @($payload.next_frontier).Count
        $summary.queue_consumer_main_loop = ($payload.background.queue_consumer_main_loop -eq $true)
        $summary.event_queue_driven_main_loop = ($payload.background.event_queue_driven -eq $true)
        $summary.temporal_activity_main_loop = ($payload.background.main_loop -eq "temporal_activity_event_queue_loop")
        $summary.sleep_1800_default_allowed = ($payload.background.sleep_seconds_1800_default_main_loop_allowed -eq $true)
    }
    catch {
        $summary.read_error = $_.Exception.Message
    }
    return $summary
}

function Test-AnyPattern {
    param(
        [string]$Text,
        [string[]]$Patterns
    )
    foreach ($pattern in $Patterns) {
        if ($Text -match $pattern) { return $true }
    }
    return $false
}

function Read-JsonSummary {
    param([string]$Path)

    $summary = [ordered]@{
        path = ConvertTo-JsonSafePath $Path
        exists = $false
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $summary
    }

    $summary.exists = $true
    try {
        $payload = Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json
        $summary.json_valid = $true
        $summary.schema_version = if ($payload.schema_version) { [string]$payload.schema_version } else { "" }
        $summary.status = if ($payload.status) { [string]$payload.status } else { "" }
        $summary.sentinel = if ($payload.sentinel) { [string]$payload.sentinel } else { "" }
        $summary.named_blocker = if ($payload.named_blocker) { [string]$payload.named_blocker } else { "" }
        $summary.completion_claim_allowed = if ($null -ne $payload.completion_claim_allowed) { [bool]$payload.completion_claim_allowed } else { $false }
        $summary.validation_passed = if ($payload.validation -and $null -ne $payload.validation.passed) { [bool]$payload.validation.passed } else { $false }
    }
    catch {
        $summary.json_valid = $false
        $summary.error = $_.Exception.Message
    }
    return $summary
}

function Get-FileAnchor {
    param([string]$Path)

    $anchor = [ordered]@{
        path = ConvertTo-JsonSafePath $Path
        exists = $false
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $anchor
    }
    $item = Get-Item -LiteralPath $Path
    $anchor.exists = $true
    $anchor.length = [int64]$item.Length
    $anchor.last_write_time = $item.LastWriteTime.ToString("o")
    return $anchor
}

function ConvertFrom-Base64Utf8 {
    param([string]$Value)
    return [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}

function ConvertTo-JsonSafePath {
    param([string]$Value)
    return ($Value -replace "\\", "/")
}

function Read-JsonObject {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        return (Get-Content -Raw -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

function Emit-StopContinueProtocol {
    param([string]$Reason)

    [ordered]@{
        continue = $true
        suppressOutput = $true
        reason = $Reason
    } | ConvertTo-Json -Depth 4 -Compress
    exit 0
}

function New-ReportThenContinueGate {
    param(
        [string]$Status,
        [string[]]$Flags,
        [bool]$ExplicitUserStopRequested,
        [bool]$ContinuationModeActive,
        [object]$ContinuationIntentState,
        [object]$StopGuardLayerRunnerRefs,
        [string]$ContinuationAuditPath,
        [string]$ContinuationAuditError
    )

    $livePath = Join-Path $RuntimeRoot "state\codex_s_live_backend_watch\latest.json"
    $sourcePath = Join-Path $RuntimeRoot "state\source_anchor_gap_continuation\latest.json"
    $gateRoot = Join-Path $RuntimeRoot "state\report_then_continue_gate"
    $gatePath = Join-Path $gateRoot "latest.json"
    New-Item -ItemType Directory -Force -Path $gateRoot | Out-Null

    $livePayload = Read-JsonObject -Path $livePath
    $sourcePayload = Read-JsonObject -Path $sourcePath
    $liveForeground = ($null -ne $livePayload -and $livePayload.foreground_poll_required -eq $true)
    $sourcePayloadMissing = ($null -eq $sourcePayload)
    $sourceContinueExpected = ($null -ne $sourcePayload -and $sourcePayload.continue_dispatch_expected -eq $true)
    $sourceDebtOpen = (
        $null -ne $sourcePayload -and (
            $sourcePayload.source_text_debt_open -eq $true -or
            ($sourcePayload.source_anchor_coverage -and $sourcePayload.source_anchor_coverage.source_text_debt_open -eq $true)
        )
    )
    $sourceCoverageComplete = (
        $null -ne $sourcePayload -and (
            $sourcePayload.source_anchor_coverage_complete -eq $true -or
            ($sourcePayload.source_anchor_coverage -and $sourcePayload.source_anchor_coverage.coverage_complete -eq $true)
        )
    )
    $sourceTaskSlicingFrozen = (
        $null -ne $sourcePayload -and (
            $sourcePayload.source_anchor_task_slicing_frozen -eq $true -or
            ($sourcePayload.source_anchor_coverage -and $sourcePayload.source_anchor_coverage.frozen_by_user -eq $true)
        )
    )
    $coverageGateContinuation = (
        $null -ne $sourcePayload -and
        $sourcePayload.coverage_gate_decision -and
        $sourcePayload.coverage_gate_decision.continuation_required -eq $true
    )
    $coverageGateStopAllowed = (
        $null -ne $sourcePayload -and
        $sourcePayload.coverage_gate_decision -and
        $sourcePayload.coverage_gate_decision.stop_allowed -eq $true
    )
    $sourceNamedBlocker = ""
    if ($null -ne $sourcePayload -and $sourcePayload.next_loop_packet -and $sourcePayload.next_loop_packet.named_blocker) {
        $sourceNamedBlocker = [string]$sourcePayload.next_loop_packet.named_blocker
    }

    $reasonCategories = @()
    if ($ExplicitUserStopRequested) { $reasonCategories += "explicit_user_stop_override" }
    if ($liveForeground) { $reasonCategories += "live_backend_foreground_poll_required" }
    if ($sourceDebtOpen) { $reasonCategories += "source_text_debt_open" }
    if ($coverageGateContinuation) { $reasonCategories += "source_anchor_coverage_gate_continue" }
    if ($sourcePayloadMissing -and $ContinuationModeActive) { $reasonCategories += "source_anchor_runner_missing_in_continuation_mode" }
    if (-not [string]::IsNullOrWhiteSpace($sourceNamedBlocker)) { $reasonCategories += $sourceNamedBlocker }

    $continuationRequired = (
        -not $ExplicitUserStopRequested -and (
            $liveForeground -or
            $coverageGateContinuation -or
            ($ContinuationModeActive -and ($sourceContinueExpected -or $sourceDebtOpen -or $sourcePayloadMissing -or (-not $coverageGateStopAllowed)))
        )
    )
    $turnStopAllowed = (
        $ExplicitUserStopRequested -or
        (($Flags.Count -eq 0) -and (-not $continuationRequired))
    )
    $continueProtocolRequired = (($Flags.Count -eq 0) -and $continuationRequired)
    $statusOut = if ($continueProtocolRequired) {
        "report_then_continue_required"
    } elseif ($ExplicitUserStopRequested) {
        "explicit_user_stop_allowed"
    } elseif ($Flags.Count -gt 0) {
        "fake_stop_blocked_by_text_guard"
    } else {
        "stop_allowed"
    }

    $payload = [ordered]@{
        schema_version = "xinao.codex_s.report_then_continue_gate.v1"
        status = $statusOut
        generated_at = (Get-Date).ToString("o")
        event = $eventName
        turn_id = $turnId
        side_audit_status = $Status
        report_allowed = $true
        turn_stop_allowed = $turnStopAllowed
        continuation_required = $continuationRequired
        continue_protocol_required = $continueProtocolRequired
        continue_protocol_shape = [ordered]@{
            continue = $true
            suppressOutput = $true
        }
        explicit_user_stop_requested = $ExplicitUserStopRequested
        continuation_mode_active = $ContinuationModeActive
        continuation_intent_state = $ContinuationIntentState
        reason_categories = @($reasonCategories | Select-Object -Unique)
        source_text_debt_open = $sourceDebtOpen
        source_anchor_task_slicing_frozen = $sourceTaskSlicingFrozen
        source_anchor_coverage_complete = $sourceCoverageComplete
        source_anchor_runner_missing = $sourcePayloadMissing
        live_backend_foreground_poll_required = $liveForeground
        coverage_gate_stop_allowed = $coverageGateStopAllowed
        source_named_blocker = $sourceNamedBlocker
        next_machine_action = if ($sourceDebtOpen) {
            "slice_source_text_to_taskcards_and_dispatch_next_assignment"
        } elseif ($liveForeground) {
            "foreground_poll_live_backend"
        } elseif ($ContinuationModeActive) {
            "restore_dynamic_loop_next_wave_or_named_blocker"
        } else {
            "ordinary_stop_allowed"
        }
        refs = [ordered]@{
            live_backend_watch = ConvertTo-JsonSafePath $livePath
            source_anchor_gap_continuation = ConvertTo-JsonSafePath $sourcePath
            source_anchor_coverage = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\source_anchor_coverage\latest.json")
            source_anchor_task_slices = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\source_anchor_task_slices\latest.json")
            source_anchor_next_task_card = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\task_card\source_anchor_coverage_next_ready.json")
            continuation_audit = ConvertTo-JsonSafePath $ContinuationAuditPath
            side_audit = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\codex_s_side_audit\latest.json")
        }
        stop_guard_layer_runner_refs = $StopGuardLayerRunnerRefs
        continuation_audit_error = $ContinuationAuditError
        policy = "report_allowed_but_report_is_not_stop; source-anchor auto task slicing is frozen by user, so this gate must not dispatch source-anchor TaskCards."
        sentinel = "SENTINEL:XINAO_CODEX_S_REPORT_THEN_CONTINUE_GATE_READY"
    }

    [IO.File]::WriteAllText(
        $gatePath,
        (($payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
    return [pscustomobject]$payload
}

function Get-ContinuationIntentState {
    $intentPath = Join-Path $RuntimeRoot "state\codex_s_continuation_intent\latest.json"
    if (-not (Test-Path -LiteralPath $intentPath -PathType Leaf)) {
        return [ordered]@{
            active = $false
            path = ConvertTo-JsonSafePath $intentPath
            source = "missing_default_inactive"
        }
    }
    try {
        $payload = Get-Content -Raw -LiteralPath $intentPath -Encoding UTF8 | ConvertFrom-Json
        return [ordered]@{
            active = ($payload.active -eq $true)
            path = ConvertTo-JsonSafePath $intentPath
            source = "runtime_state"
            updated_at = if ($payload.updated_at) { [string]$payload.updated_at } else { "" }
            reason = if ($payload.reason) { [string]$payload.reason } else { "" }
        }
    }
    catch {
        return [ordered]@{
            active = $false
            path = ConvertTo-JsonSafePath $intentPath
            source = "invalid_runtime_state_default_inactive"
            error = $_.Exception.Message
        }
    }
}

function Set-ContinuationIntentState {
    param(
        [bool]$Active,
        [string]$Reason,
        [string]$SourceText
    )

    $intentRoot = Join-Path $RuntimeRoot "state\codex_s_continuation_intent"
    $intentPath = Join-Path $intentRoot "latest.json"
    New-Item -ItemType Directory -Force -Path $intentRoot | Out-Null
    $payload = [ordered]@{
        schema_version = "xinao.codex_s.continuation_intent.v1"
        active = $Active
        reason = $Reason
        source_text = $SourceText
        updated_at = (Get-Date).ToString("o")
        default_policy = "inactive_for_ordinary_discussion; active_only_after_explicit_no_stop_intent; inactive_after_explicit_user_stop"
        not_source_of_truth = $true
        not_completion_decision = $true
        sentinel = "SENTINEL:XINAO_CODEX_S_CONTINUATION_INTENT_STATE"
    }
    [IO.File]::WriteAllText(
        $intentPath,
        (($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
    return Get-ContinuationIntentState
}

function Test-LiveBackendMarker {
    param([string]$Text)

    $markers = @()
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return @()
    }

    $markerPatterns = [ordered]@{
        worker_running = '"worker_running"\s*:\s*true'
        temporal_pending_activity = '"(?:temporal_)?pending_activity"\s*:\s*true'
        assignment_next_ready = '"next_ready"\s*:\s*true'
        assignment_auto_continue = '"auto_continue(?:_expected)?"\s*:\s*true'
        non_terminal_worker_evidence = '"worker_jsonl_evidence_present"\s*:\s*true'
        should_continue = '"should_continue(?:_loop)?"\s*:\s*true'
        queue_nonterminal = '"(?:active_lane_count|nonterminal_lane_count|running_count|pending_count)"\s*:\s*[1-9][0-9]*'
        idle_handoff_required = '"idle_handoff_required"\s*:\s*true'
        live_status = '"(?:status|state|lifecycle_state|run_state|terminal_state)"\s*:\s*"(?:running|in_progress|dispatching|polling|queued|accepted|non_terminal|continue_required|pending|started)"'
    }

    foreach ($entry in $markerPatterns.GetEnumerator()) {
        if ($Text -match $entry.Value) {
            $markers += [string]$entry.Key
        }
    }

    return @($markers)
}

function ConvertTo-LiveBackendCategories {
    param([string[]]$Markers)

    $categories = @()
    foreach ($marker in @($Markers)) {
        switch ($marker) {
            "temporal_pending_activity" { $categories += "temporal_pending_activity" }
            "worker_running" { $categories += "worker_running" }
            "non_terminal_worker_evidence" { $categories += "worker_jsonl_non_terminal" }
            "assignment_next_ready" { $categories += "assignment_next_ready" }
            "assignment_auto_continue" { $categories += "assignment_auto_continue_expected" }
            "should_continue" { $categories += "explicit_continue_required" }
            "queue_nonterminal" { $categories += "queue_or_lane_non_terminal" }
            "idle_handoff_required" { $categories += "idle_handoff_required" }
            "live_status" { $categories += "non_terminal_status" }
        }
    }
    return @($categories | Select-Object -Unique)
}

function Get-LiveBackendWatch {
    param([bool]$ExplicitUserStopRequested)

    $watchRoot = Join-Path $RuntimeRoot "state\codex_s_live_backend_watch"
    $watchPath = Join-Path $watchRoot "latest.json"
    $watchSetVersion = "codex_s_live_backend_watch.s_runtime_worker_files.v2"
    New-Item -ItemType Directory -Force -Path $watchRoot | Out-Null

    $previousByPath = @{}
    $previousWatchSetMatches = $false
    if (Test-Path -LiteralPath $watchPath -PathType Leaf) {
        try {
            $previous = Get-Content -Raw -LiteralPath $watchPath -Encoding UTF8 | ConvertFrom-Json
            $previousWatchSetMatches = ([string]$previous.watch_set_version -eq $watchSetVersion)
            if ($previousWatchSetMatches) {
                foreach ($file in @($previous.watched_files)) {
                    $key = [string]$file.path
                    if (-not [string]::IsNullOrWhiteSpace($key)) {
                        $previousByPath[$key] = $file
                    }
                }
            }
        }
        catch {
            $previousByPath = @{}
        }
    }

    $relativeWatchPaths = @(
        "state\live_parallel_pool\latest.json",
        "state\worker_assignment_dynamic_fanout\latest.json",
        "state\parallel_lane_results\latest.json",
        "state\parallel_dispatch_plan\latest.json",
        "state\parallel_fan_in_acceptance\latest.json",
        "state\parallel_capacity\latest.json",
        "state\deepseek_sidecar\xinao_seed_cortex_phase0_20260701\latest.json",
        "state\deepseek_search_sidecar\latest.json",
        "state\deepseek_draft_staging_queue\latest.json",
        "state\deepseek_fan_in_acceptance_queue\latest.json",
        "state\deepseek_search_fan_in_acceptance\latest.json",
        "state\artifact_acceptance_queue\latest.json",
        "state\max_parallel_mainline_return\latest.json",
        "state\durable_workflow_evidence\latest.json"
    )

    $watchedFiles = @()
    foreach ($relative in $relativeWatchPaths) {
        $path = Join-Path $RuntimeRoot $relative
        $safePath = ConvertTo-JsonSafePath $path
        $entry = [ordered]@{
            path = $safePath
            exists = $false
            length = 0
            last_write_time = ""
            changed_since_previous_watch = $false
            live_status_detected = $false
            live_markers = @()
            live_categories = @()
        }

        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $item = Get-Item -LiteralPath $path
            $entry.exists = $true
            $entry.length = [int64]$item.Length
            $entry.last_write_time = $item.LastWriteTime.ToString("o")

            $previousFile = $previousByPath[$safePath]
            if ($null -ne $previousFile) {
                $previousLength = [int64]0
                [void][int64]::TryParse([string]$previousFile.length, [ref]$previousLength)
                $previousLastWrite = [string]$previousFile.last_write_time
                $entry.changed_since_previous_watch = (
                    $previousLength -ne [int64]$entry.length -or
                    $previousLastWrite -ne [string]$entry.last_write_time
                )
            }

            try {
                $text = Get-Content -Raw -LiteralPath $path -Encoding UTF8
                if ($text.Length -gt 200000) {
                    $text = $text.Substring(0, 200000)
                }
                $markers = @(Test-LiveBackendMarker -Text $text)
                $entry.live_markers = $markers
                $entry.live_categories = @(ConvertTo-LiveBackendCategories -Markers $markers)
                $entry.live_status_detected = ($markers.Count -gt 0)
            }
            catch {
                $entry.read_error = $_.Exception.Message
            }
        }

        $watchedFiles += $entry
    }

    $liveFiles = @($watchedFiles | Where-Object { $_.exists -and $_.live_status_detected })
    $growthFiles = @($watchedFiles | Where-Object { $_.exists -and $_.changed_since_previous_watch })
    $foregroundPollRequired = (-not $ExplicitUserStopRequested) -and (($liveFiles.Count -gt 0) -or ($growthFiles.Count -gt 0))
    $decisionCategories = @()
    foreach ($file in $liveFiles) {
        $decisionCategories += @($file.live_categories)
    }
    if ($growthFiles.Count -gt 0) {
        $decisionCategories += "output_growth_detected"
    }
    if ($ExplicitUserStopRequested) {
        $decisionCategories += "explicit_user_stop_override"
    }
    $decisionCategories = @($decisionCategories | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } | Select-Object -Unique)
    $existingCandidateCount = @($watchedFiles | Where-Object { $_.exists }).Count

    $payload = [ordered]@{
        schema_version = "xinao.codex_s.live_backend_watch.v1"
        watch_set_version = $watchSetVersion
        previous_watch_set_matches = $previousWatchSetMatches
        status = if ($foregroundPollRequired) { "live_backend_watch_poll_required" } elseif ($ExplicitUserStopRequested) { "live_backend_watch_user_stop_override" } elseif ($existingCandidateCount -eq 0) { "live_backend_watch_no_candidate_state" } else { "live_backend_watch_idle_or_unavailable" }
        generated_at = (Get-Date).ToString("o")
        foreground_poll_required = $foregroundPollRequired
        explicit_user_stop_overrides_live_watch = $ExplicitUserStopRequested
        old_backend_mirror_semantics_reused = $true
        old_backend_endpoint_used = $false
        old_semantic_categories = [ordered]@{
            continue_required_categories = @(
                "temporal_pending_activity",
                "worker_running",
                "worker_jsonl_non_terminal",
                "assignment_next_ready",
                "assignment_auto_continue_expected",
                "queue_or_lane_non_terminal",
                "explicit_continue_required",
                "non_terminal_status",
                "output_growth_detected"
            )
            fallback_or_handoff_categories = @(
                "idle_handoff_required"
            )
            fail_open_categories = @(
                "no_candidate_state",
                "state_read_unavailable",
                "invalid_json_or_decode_error"
            )
            not_live_by_itself = @(
                "current_route status active",
                "static worker_assignment status active",
                "temporal dev server process running",
                "plan/read_model/status ready without worker, queue, non-terminal, or growth evidence"
            )
        }
        decision_categories = $decisionCategories
        live_status_file_count = $liveFiles.Count
        output_growth_file_count = $growthFiles.Count
        live_status_paths = @($liveFiles | ForEach-Object { $_.path })
        output_growth_paths = @($growthFiles | ForEach-Object { $_.path })
        watched_files = $watchedFiles
        source_policy = "S runtime state files only; old A/CLEAN backend mirror hook semantics reused, old endpoint not used by default"
        compat_endpoint_used = $false
        hook_action_cn = if ($foregroundPollRequired) {
            [regex]::Unescape("\u540e\u53f0\u4ecd\u6709\u6d3b\u4f53\u72b6\u6001\u6216\u8f93\u51fa\u589e\u957f\uff1b\u524d\u53f0\u5e94\u7ee7\u7eed\u8f6e\u8be2\u89c2\u5bdf\uff0c\u4e0d\u80fd\u628a\u62a5\u544a\u5f53\u7ed3\u675f\u3002")
        } elseif ($ExplicitUserStopRequested) {
            [regex]::Unescape("\u7528\u6237\u663e\u5f0f\u558a\u505c\uff1b\u6d3b\u4f53\u89c2\u5bdf\u53ea\u8bb0\u5f55\uff0c\u4e0d\u963b\u6b62\u505c\u6b62\u3002")
        } else {
            [regex]::Unescape("\u672a\u53d1\u73b0 S \u8fd0\u884c\u6001\u6d3b\u4f53\u6216\u8f93\u51fa\u589e\u957f\uff1b\u5141\u8bb8\u8fdb\u5165\u6e90\u6587\u672c\u951a\u5b9a\u7eed\u8dd1\u68c0\u67e5\u6216\u666e\u901a\u505c\u6b62\u3002")
        }
        not_source_of_truth = $true
        not_user_completion = $true
        not_completion_decision = $true
        not_execution_controller = $true
        sentinel = "SENTINEL:XINAO_CODEX_S_LIVE_BACKEND_WATCH_READY"
    }

    [IO.File]::WriteAllText(
        $watchPath,
        (($payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )

    return $payload
}

function New-StopContinuationAudit {
    param(
        [string]$Status,
        [string[]]$Flags,
        [string[]]$RawFlags,
        [bool]$ExplicitUserStopRequested,
        [bool]$ExplicitNoStopIntentDetected,
        [bool]$ContinuationModeActive,
        [object]$ContinuationIntentState,
        [bool]$HasNonBlockingKeywordMention
    )

    $sourceAnchorRoot = Join-Path (Join-Path $env:USERPROFILE "Desktop") (ConvertFrom-Base64Utf8 "5paw57O757uf")
    $sourceAnchorSpecs = @(
        [ordered]@{
            key = "source_anchor_entry_root"
            path = $sourceAnchorRoot
            required = $true
        }
    )
    $sourceAnchors = @($sourceAnchorSpecs | ForEach-Object {
        $anchor = Get-FileAnchor -Path $_.path
        $anchor["key"] = [string]$_.key
        $anchor["required"] = [bool]$_.required
        $anchor
    })

    $runtimeRefs = [ordered]@{
        current_route = Read-JsonSummary (Join-Path $RuntimeRoot "state\current_route\latest.json")
        worker_assignment = Read-JsonSummary (Join-Path $RuntimeRoot "state\worker_assignment\xinao_seed_cortex_phase0_20260701.json")
        metaminute = Read-JsonSummary (Join-Path $RuntimeRoot "state\metaminute_preflight_reflection\latest.json")
        default_parallelism_policy = Read-JsonSummary (Join-Path $RuntimeRoot "state\default_parallelism_policy\latest.json")
        parallel_dispatch_plan = Read-JsonSummary (Join-Path $RuntimeRoot "state\parallel_dispatch_plan\latest.json")
        parallel_fan_in_acceptance = Read-JsonSummary (Join-Path $RuntimeRoot "state\parallel_fan_in_acceptance\latest.json")
        max_benefit_parallelism_plan = Read-JsonSummary (Join-Path $RuntimeRoot "state\max_benefit_parallelism_plan\latest.json")
        artifact_acceptance_queue = Read-JsonSummary (Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json")
        durable_parallel_wave_packet = Read-JsonSummary (Join-Path $RuntimeRoot "state\durable_parallel_wave_packet\latest.json")
        durable_parallel_wave_packet_service_entrypoint = Read-JsonSummary (Join-Path $RuntimeRoot "state\durable_parallel_wave_packet\service_entrypoint_latest.json")
        worker_dispatch_ledger = Read-JsonSummary (Join-Path $RuntimeRoot "state\worker_dispatch_ledger\latest.json")
        temporal_worker_dispatch_ledger_activity = Read-JsonSummary (Join-Path $RuntimeRoot "state\worker_dispatch_ledger\temporal_activity_latest.json")
        codex_s_main_execution_loop_tick = Read-JsonSummary (Join-Path $RuntimeRoot "state\codex_s_main_execution_loop_tick\latest.json")
        codex_s_main_execution_loop_tick_service_entrypoint = Read-JsonSummary (Join-Path $RuntimeRoot "state\codex_s_main_execution_loop_tick\service_entrypoint_latest.json")
        temporal_main_execution_loop_tick_activity = Read-JsonSummary (Join-Path $RuntimeRoot "state\codex_s_main_execution_loop_tick\temporal_activity_latest.json")
        temporal_durable_parallel_wave_packet_activity = Read-JsonSummary (Join-Path $RuntimeRoot "state\durable_parallel_wave_packet\temporal_activity_latest.json")
        capability_adoption_state_boundary = Read-JsonSummary (Join-Path $RuntimeRoot "state\capability_adoption_state_boundary\latest.json")
    }

    $missingSources = @($sourceAnchors | Where-Object { -not $_.exists } | ForEach-Object { $_.path })
    $missingRequiredSources = @($sourceAnchors | Where-Object { $_.required -and -not $_.exists } | ForEach-Object { $_.path })
    $missingOptionalSources = @($sourceAnchors | Where-Object { -not $_.required -and -not $_.exists } | ForEach-Object { $_.path })
    $missingRuntimeRefs = @()
    foreach ($prop in $runtimeRefs.GetEnumerator()) {
        if (-not $prop.Value.exists) { $missingRuntimeRefs += $prop.Name }
    }
    $sourceGapPath = Join-Path $RuntimeRoot "state\source_anchor_gap_continuation\latest.json"
    $sourceCoveragePath = Join-Path $RuntimeRoot "state\source_anchor_coverage\latest.json"
    $sourceTaskSlicesPath = Join-Path $RuntimeRoot "state\source_anchor_task_slices\latest.json"
    $sourceNextTaskCardPath = Join-Path $RuntimeRoot "state\task_card\source_anchor_coverage_next_ready.json"
    $sourceGapPayload = Read-JsonObject -Path $sourceGapPath
    $sourceCoveragePayload = Read-JsonObject -Path $sourceCoveragePath
    $sourceTextDebtOpen = (
        $null -ne $sourceGapPayload -and (
            $sourceGapPayload.source_text_debt_open -eq $true -or
            ($sourceGapPayload.source_anchor_coverage -and $sourceGapPayload.source_anchor_coverage.source_text_debt_open -eq $true)
        )
    )
    $sourceCoverageComplete = (
        $null -ne $sourceGapPayload -and (
            $sourceGapPayload.source_anchor_coverage_complete -eq $true -or
            ($sourceGapPayload.source_anchor_coverage -and $sourceGapPayload.source_anchor_coverage.coverage_complete -eq $true)
        )
    )
    $sourceTaskSlicingFrozen = (
        $null -ne $sourceGapPayload -and (
            $sourceGapPayload.source_anchor_task_slicing_frozen -eq $true -or
            ($sourceGapPayload.source_anchor_coverage -and $sourceGapPayload.source_anchor_coverage.frozen_by_user -eq $true)
        )
    )
    $sourceTaskSliceCount = 0
    if ($null -ne $sourceGapPayload -and $sourceGapPayload.source_anchor_coverage -and $null -ne $sourceGapPayload.source_anchor_coverage.sampled_obligation_count) {
        [void][int]::TryParse([string]$sourceGapPayload.source_anchor_coverage.sampled_obligation_count, [ref]$sourceTaskSliceCount)
    }

    $liveBackendWatch = Get-LiveBackendWatch -ExplicitUserStopRequested $ExplicitUserStopRequested
    $loopRuntimeStateSummary = Get-LoopRuntimeStateSummary
    $loopRuntimeBlocksStop = (
        $loopRuntimeStateSummary.exists -eq $true -and
        $loopRuntimeStateSummary.stop_allowed -eq $false -and
        -not $ExplicitUserStopRequested
    )
    $frontGateContinue = ([bool]$liveBackendWatch.foreground_poll_required) -or $loopRuntimeBlocksStop

    $continuationAction = if ($ExplicitUserStopRequested) {
        "explicit user stop requested; do not continue until the user resumes"
    } elseif ($frontGateContinue) {
        "foreground live-watch -> poll active backend/output growth until terminal or no-growth -> then source-anchor gap check -> dispatch next useful wave if needed"
    } elseif ($ContinuationModeActive -and $sourceTaskSlicingFrozen) {
        "source-anchor auto task slicing is frozen; do not create or consume source-anchor TaskCard; main brain reads entry root directly"
    } elseif ($ContinuationModeActive -and $sourceTextDebtOpen) {
        "source text debt open -> slice source obligations -> TaskCard -> existing lane -> ClaimCard or named blocker"
    } elseif ($ContinuationModeActive) {
        "restore -> source-anchor gap check -> recompute max-benefit frontier -> dispatch useful independent lanes -> poll -> fan-in -> verify/write evidence + Chinese readback -> next wave"
    } else {
        "ordinary single-turn checkpoint; stop is allowed unless explicit no-stop continuation intent is active"
    }
    $shouldContinueLoop = ($frontGateContinue -or ($ContinuationModeActive -and -not $ExplicitUserStopRequested))
    $namedBlocker = ""
    if ($ExplicitUserStopRequested) {
        $namedBlocker = ""
    }
    elseif ($ContinuationModeActive -and $missingRequiredSources.Count -gt 0) {
        $namedBlocker = "CODEX_S_STOP_AUDIT_SOURCE_ANCHOR_MISSING"
    }
    elseif ($ContinuationModeActive -and $missingRuntimeRefs.Count -gt 0) {
        $namedBlocker = "CODEX_S_STOP_AUDIT_RUNTIME_REF_MISSING"
    }

    $auditRoot = Join-Path $RuntimeRoot "state\codex_s_stop_continuation_audit"
    $auditPath = Join-Path $auditRoot "latest.json"
    New-Item -ItemType Directory -Force -Path $auditRoot | Out-Null

    $payload = [ordered]@{
        schema_version = "xinao.codex_s.stop_continuation_audit.v1"
        status = "stop_continuation_audit_ready"
        generated_at = (Get-Date).ToString("o")
        event = $eventName
        turn_id = $turnId
        gate_order = @(
            "explicit_user_stop_override",
            "loop_runtime_state_stop_allowed_gate",
            "live_backend_watch_front_gate",
            "source_anchor_gap_continuation",
            "text_stop_guard_last_gate"
        )
        loop_runtime_state_gate = [ordered]@{
            gate = "loop_runtime_state_stop_allowed_gate"
            latest_ref = $loopRuntimeStateSummary.latest_ref
            exists = $loopRuntimeStateSummary.exists
            stop_allowed = $loopRuntimeStateSummary.stop_allowed
            stop_reason = $loopRuntimeStateSummary.stop_reason
            task_backlog_count = $loopRuntimeStateSummary.task_backlog_count
            ready_frontier_count = $loopRuntimeStateSummary.ready_frontier_count
            draft_staged_count = $loopRuntimeStateSummary.draft_staged_count
            draft_unmerged_count = $loopRuntimeStateSummary.draft_unmerged_count
            merge_backlog_count = $loopRuntimeStateSummary.merge_backlog_count
            fan_in_backlog_count = $loopRuntimeStateSummary.fan_in_backlog_count
            evidence_backlog_count = $loopRuntimeStateSummary.evidence_backlog_count
            source_gap_count = $loopRuntimeStateSummary.source_gap_count
            blocker_count = $loopRuntimeStateSummary.blocker_count
            next_frontier_count = $loopRuntimeStateSummary.next_frontier_count
            queue_consumer_main_loop = $loopRuntimeStateSummary.queue_consumer_main_loop
            blocks_fake_stop = $loopRuntimeBlocksStop
            stop_hook_reads_only = $true
            stop_hook_dispatches_main_loop = $false
            stop_hook_writes_worker_dispatch_ledger = $false
        }
        front_gate_decision = [ordered]@{
            gate = "live_backend_watch_front_gate"
            foreground_poll_required = $frontGateContinue
            live_backend_watch_status = [string]$liveBackendWatch.status
            explicit_user_stop_overrides = $ExplicitUserStopRequested
        }
        live_backend_watch = $liveBackendWatch
        source_anchor_check = [ordered]@{
            source_anchor_root = ConvertTo-JsonSafePath $sourceAnchorRoot
            source_anchor_policy = "entry_root_only_no_text_file_binding"
            source_text_auto_slicing_permanently_frozen = $true
            source_anchors = $sourceAnchors
            missing_sources = $missingSources
            missing_required_sources = $missingRequiredSources
            missing_optional_sources = $missingOptionalSources
            source_anchor_complete = ($missingRequiredSources.Count -eq 0)
            source_text_debt_open = $sourceTextDebtOpen
            source_anchor_task_slicing_frozen = $sourceTaskSlicingFrozen
            source_anchor_coverage_complete = $sourceCoverageComplete
            source_task_slice_count = $sourceTaskSliceCount
            source_anchor_gap_continuation = Read-JsonSummary $sourceGapPath
            source_anchor_coverage = Read-JsonSummary $sourceCoveragePath
            source_anchor_task_slices = Read-JsonSummary $sourceTaskSlicesPath
            source_anchor_next_task_card = Read-JsonSummary $sourceNextTaskCardPath
            source_text_debt_policy = "source-anchor auto task slicing is permanently frozen by user; this layer checks only the entry root and must not create or dispatch source-anchor TaskCards."
        }
        local_runtime_gap_check = [ordered]@{
            runtime_refs = $runtimeRefs
            missing_runtime_refs = $missingRuntimeRefs
            runtime_ref_complete = ($missingRuntimeRefs.Count -eq 0)
        }
        report_stop_surface = [ordered]@{
            side_audit_status = $Status
            flags = $Flags
            raw_flags = $RawFlags
            explicit_stop_or_completion_claim_detected = ($RawFlags.Count -gt 0)
            explicit_user_stop_requested = $ExplicitUserStopRequested
            explicit_no_stop_intent_detected = $ExplicitNoStopIntentDetected
            continuation_mode_active = $ContinuationModeActive
            continuation_intent_state = $ContinuationIntentState
            user_stop_overrides_loop_continuation = $ExplicitUserStopRequested
            user_stop_overrides_live_backend_watch = $ExplicitUserStopRequested
            non_blocking_keyword_mention = $HasNonBlockingKeywordMention
            report_pass_draft_window_end_are_not_stop_conditions = $true
        }
        conversation_flow_policy = [ordered]@{
            ordinary_single_turn_discussion_can_stop = $true
            checkpoint_not_stop_only_when_continuation_mode_active = $true
            ordinary_reply_is_checkpoint_not_stop = $ContinuationModeActive
            user_question_can_interrupt_without_cancelling_mainline = $true
            after_answer_return_to_interrupted_question_or_mainline = $shouldContinueLoop
            return_target_order = @(
                "current explicit user interruption",
                "previous unresolved inserted question",
                "active Seed Cortex mainline frontier",
                "next highest-EV machine action from runtime refs"
            )
            do_not_convert_answer_to_final_stop = $true
        }
        next_loop_packet = [ordered]@{
            should_continue_loop = $shouldContinueLoop
            front_gate = if ($frontGateContinue) { "live_backend_watch_front_gate" } elseif ($ContinuationModeActive -and -not $ExplicitUserStopRequested) { "source_anchor_gap_continuation" } elseif ($ExplicitUserStopRequested) { "explicit_user_stop_override" } else { "ordinary_checkpoint_stop_allowed" }
            live_backend_watch_status = [string]$liveBackendWatch.status
            source_text_debt_open = $sourceTextDebtOpen
            source_anchor_task_slicing_frozen = $sourceTaskSlicingFrozen
            source_anchor_coverage_complete = $sourceCoverageComplete
            source_task_slice_count = $sourceTaskSliceCount
            source_anchor_next_task_card = ConvertTo-JsonSafePath $sourceNextTaskCardPath
            action = $continuationAction
            return_policy = if ($ExplicitUserStopRequested) {
                "user explicitly asked to stop; do not restore prior question/mainline until user resumes"
            } elseif ($frontGateContinue) {
                "continue foreground polling while backend/output is live, then fall through to source-anchor gap continuation"
            } elseif ($ContinuationModeActive) {
                "answer current interruption if needed, then restore prior question/mainline and continue the dynamic loop"
            } else {
                "ordinary reply may stop here; do not continue unless explicit no-stop intent is active"
            }
            dispatch_policy = "max-benefit useful parallelism bounded by fan-in and verification capacity"
            fan_in_required = $true
            evidence_required = $true
            chinese_readback_required = $true
            evidence_refs = [ordered]@{
                read_only = $true
                loop_runtime_state = $loopRuntimeStateSummary.latest_ref
                durable_parallel_wave_packet = $runtimeRefs.durable_parallel_wave_packet
                durable_parallel_wave_packet_service_entrypoint = $runtimeRefs.durable_parallel_wave_packet_service_entrypoint
                worker_dispatch_ledger = $runtimeRefs.worker_dispatch_ledger
                temporal_worker_dispatch_ledger_activity = $runtimeRefs.temporal_worker_dispatch_ledger_activity
                codex_s_main_execution_loop_tick = $runtimeRefs.codex_s_main_execution_loop_tick
                codex_s_main_execution_loop_tick_service_entrypoint = $runtimeRefs.codex_s_main_execution_loop_tick_service_entrypoint
                temporal_main_execution_loop_tick_activity = $runtimeRefs.temporal_main_execution_loop_tick_activity
                temporal_durable_parallel_wave_packet_activity = $runtimeRefs.temporal_durable_parallel_wave_packet_activity
                activity_evidence_refs_observed_read_only = $true
                activity_evidence_refs_runtime_enforced_scope = "read_only_observed_evidence_refs_only"
                stop_hook_dispatches_main_execution_loop = $false
                stop_hook_calls_main_execution_loop_tick_activity = $false
                stop_hook_writes_worker_dispatch_ledger = $false
                stop_hook_writes_activity_evidence_refs = $false
                stop_hook_is_execution_controller = $false
            }
            adoption_boundary = [ordered]@{
                stop_guard_layers_runtime_enforced_scope = "stop_continue_protocol_decision"
                stop_guard_layers_runtime_enforced_covers_main_execution_loop = $false
                main_execution_loop_runtime_enforced_by_stop_hook = $false
                main_execution_loop_controller_runtime_enforced_by_stop_hook = $false
                runners_are_decision_controllers = $true
                runners_are_stop_decision_inputs = $true
                stop_continue_protocol_controller = $true
                durable_parallel_wave_packet_adoption_state = "verifier_ready_but_not_hooked"
                durable_parallel_wave_packet_service_api_cli_adoption_state = "api_cli_verifier_ready_not_hook_enforced"
                codex_s_main_execution_loop_tick_runtime_enforced_by_stop_hook = $false
                codex_s_main_execution_loop_tick_service_api_cli_adoption_state = "api_cli_verifier_ready_not_hook_enforced"
                temporal_worker_dispatch_ledger_activity_observed_read_only = $true
                temporal_main_execution_loop_tick_activity_observed_read_only = $true
                temporal_durable_parallel_wave_packet_activity_observed_read_only = $true
                main_execution_loop_tick_activity_called_by_stop_hook = $false
                worker_dispatch_ledger_write_by_stop_hook = $false
                worker_dispatch_ledger_activity_write_by_stop_hook = $false
            }
            named_blocker = $namedBlocker
            stop_reason = if ($ExplicitUserStopRequested) { "explicit_user_stop" } elseif (-not $ContinuationModeActive) { "ordinary_checkpoint_stop_allowed" } else { "" }
        }
        authority_boundary = [ordered]@{
            not_source_of_truth = $true
            not_user_completion = $true
            not_completion_decision = $true
            not_execution_controller = $true
            runners_are_decision_controllers = $true
            runners_are_stop_decision_inputs = $true
            stop_continue_protocol_controller = $true
            stop_hook_dispatches_main_execution_loop = $false
            stop_hook_writes_worker_dispatch_ledger = $false
            stop_hook_calls_main_execution_loop_tick_activity = $false
            stop_hook_writes_activity_evidence_refs = $false
            runtime_enforced_scope = "Stop hook runtime_enforced covers report-then-continue Stop protocol decision plus read-only observed Temporal activity evidence refs; it does not directly execute main_execution_loop, main loop controller, worker dispatch ledger writes, or activity invocation."
            hook_scope = "Stop-time live-backend/source-gap/continuation read model plus fake-stop text guard"
        }
        sentinel = "SENTINEL:XINAO_CODEX_S_STOP_CONTINUATION_AUDIT_READY"
    }

    [IO.File]::WriteAllText(
        $auditPath,
        (($payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
    return $auditPath
}

function U {
    param([string]$Value)
    return [regex]::Unescape($Value)
}

$completeAllowedClaimPatterns = @(
    "(?i)(^|[^\w])decision\.status\s*[:=]\s*complete_allowed([^\w]|$)",
    "(?i)(^|[^\w])status\s*[:=]\s*complete_allowed([^\w]|$)",
    "(?i)(^|[^\w])complete_allowed\s*[:=]\s*(true|1|yes)([^\w]|$)",
    "(?i)(^|[^\w])complete_allowed\s*\+\s*stop_allowed\s*[:=]\s*true([^\w]|$)"
)
$stopAllowedClaimPatterns = @(
    "(?i)(^|[^\w])stop_allowed\s*[:=]\s*(true|1|yes)([^\w]|$)"
)
$doneAsCompletionPatterns = @(
    "(?i)\bdone\s+as\s+(?:a\s+)?completion\b",
    "(?i)\bcompletion\s+claim\s*[:=]\s*done\b",
    "(?i)\bdone\s*[:=]\s*(true|1|yes)\b",
    "(?i)\bclaim(?:ed|ing)?\s+(?:this|task|work|object|request|change|fix|repair|hook)?\s*(?:as\s+)?done\b",
    "(?i)\bdeclare(?:d|s|ing)?\s+(?:this|task|work|object|request|change|fix|repair|hook)?\s*(?:as\s+)?done\b"
)
$nonBlockingKeywordPatterns = @(
    (U "\u5b8c\u6210"), "final", "\bPASS\b", (U "\u5b89\u5168"),
    "fanout", "fan-out"
)
$explicitUserStopPatterns = @(
    "(?i)(^|[^\w])stop([^\w]|$)",
    "(?i)(^|[^\w])pause([^\w]|$)",
    (U "\u505c\u6b62"),
    (U "\u505c\u4e0b"),
    (U "\u522b\u7ee7\u7eed"),
    (U "\u522b\u518d\u7ee7\u7eed"),
    (U "\u4e0d\u8981\u7ee7\u7eed"),
    (U "\u4e0d\u8981\u518d\u7ee7\u7eed"),
    (U "\u5148\u505c"),
    (U "\u6682\u505c"),
    (U "\u5230\u6b64\u4e3a\u6b62")
)
$explicitNoStopIntentPatterns = @(
    "(?i)do\s+not\s+stop",
    "(?i)don't\s+stop",
    "(?i)keep\s+going",
    "(?i)continue\s+until\s+i\s+(say\s+)?stop",
    "(?i)unless\s+i\s+(say\s+)?stop",
    (U "\u4e0d\u8981\u505c"),
    (U "\u522b\u505c"),
    (U "\u4e0d\u8bb8\u505c"),
    (U "\u9ed8\u8ba4\u4e0d\u505c"),
    (U "\u9664\u975e\u6211\u558a\u505c"),
    (U "\u9664\u975e\u6211\u4e3b\u52a8\u558a\u505c"),
    (U "\u9664\u975e\u7528\u6237\u558a\u505c"),
    (U "\u52a8\u6001\u8f6e\u56de"),
    (U "\u5faa\u73af"),
    (U "\u4e0d\u505c\u8f6e\u8be2"),
    (U "\u7ee7\u7eed\u8f6e\u8be2"),
    (U "\u7ee7\u7eed\u5faa\u73af")
)

$hasCompletionClaimIntent = Test-ExplicitTruthyProperty -Node $event -PropertyName "completion_claim_intent"
$hasStopClaimIntent = Test-ExplicitTruthyProperty -Node $event -PropertyName "stop_claim_intent"
$declaresCompleteAllowed = Test-AnyPattern $message $completeAllowedClaimPatterns
$declaresStopAllowed = Test-AnyPattern $message $stopAllowedClaimPatterns
$declaresDoneAsCompletion = Test-AnyPattern $message $doneAsCompletionPatterns
$hasNonBlockingKeywordMention = Test-AnyPattern $message $nonBlockingKeywordPatterns
$explicitNoStopIntentDetected = Test-AnyPattern $userMessage $explicitNoStopIntentPatterns
$explicitUserStopRequested = (Test-AnyPattern $userMessage $explicitUserStopPatterns) -and (-not $explicitNoStopIntentDetected)

if ($explicitUserStopRequested) {
    $continuationIntentState = Set-ContinuationIntentState -Active $false -Reason "explicit_user_stop" -SourceText $userMessage
}
elseif ($explicitNoStopIntentDetected) {
    $continuationIntentState = Set-ContinuationIntentState -Active $true -Reason "explicit_no_stop_until_user_stop_intent" -SourceText $userMessage
}
else {
    $continuationIntentState = Get-ContinuationIntentState
}
$continuationModeActive = [bool]$continuationIntentState.active

$rawFlags = @()
if ($hasCompletionClaimIntent) { $rawFlags += "EXPLICIT_COMPLETION_CLAIM_INTENT" }
if ($hasStopClaimIntent) { $rawFlags += "EXPLICIT_STOP_CLAIM_INTENT" }
if ($declaresCompleteAllowed) { $rawFlags += "TEXT_DECLARED_COMPLETE_ALLOWED" }
if ($declaresStopAllowed) { $rawFlags += "TEXT_DECLARED_STOP_ALLOWED" }
if ($declaresDoneAsCompletion) { $rawFlags += "TEXT_DECLARED_DONE_AS_COMPLETION" }

$flags = if ($explicitUserStopRequested) { @() } else { $rawFlags }
$status = if ($rawFlags.Count -gt 0 -and -not $explicitUserStopRequested) { "text_stop_guard_blocked_fake_stop" } elseif ($explicitUserStopRequested) { "text_stop_guard_user_stop_requested" } else { "text_stop_guard_pass" }
$stateRoot = Join-Path $RuntimeRoot "state\codex_s_side_audit"
$latestPath = Join-Path $stateRoot "latest.json"
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
$continuationAuditPath = ""
$continuationAuditError = ""
$stopGuardLayerRunnerRefs = [ordered]@{
    live_backend_watch = [ordered]@{ invoked = $false }
    source_anchor_gap_continuation = [ordered]@{ invoked = $false }
    fail_open = $true
    runners_are_decision_controllers = $true
    runners_are_stop_decision_inputs = $true
    stop_guard_layers_runtime_enforced_scope = "stop_continue_protocol_decision"
    stop_continue_protocol_controller = $true
    main_execution_loop_runtime_enforced_by_stop_hook = $false
    stop_hook_dispatches_main_execution_loop = $false
    stop_hook_writes_worker_dispatch_ledger = $false
}
try {
    $stopGuardLayerRunnerRefs = Invoke-StopGuardLayerRunners -ExplicitUserStopRequested $explicitUserStopRequested -ContinuationModeActive $continuationModeActive
    $continuationAuditPath = New-StopContinuationAudit -Status $status -Flags $flags -RawFlags $rawFlags -ExplicitUserStopRequested $explicitUserStopRequested -ExplicitNoStopIntentDetected $explicitNoStopIntentDetected -ContinuationModeActive $continuationModeActive -ContinuationIntentState $continuationIntentState -HasNonBlockingKeywordMention $hasNonBlockingKeywordMention
}
catch {
    $continuationAuditError = $_.Exception.Message
}

$reportThenContinueGate = New-ReportThenContinueGate `
    -Status $status `
    -Flags $flags `
    -ExplicitUserStopRequested $explicitUserStopRequested `
    -ContinuationModeActive $continuationModeActive `
    -ContinuationIntentState $continuationIntentState `
    -StopGuardLayerRunnerRefs $stopGuardLayerRunnerRefs `
    -ContinuationAuditPath $continuationAuditPath `
    -ContinuationAuditError $continuationAuditError

$audit = [ordered]@{
    schema_version = "xinao.codex_s_side_audit.v1"
    status = $status
    guard_kind = "CODEX_S_TEXT_STOP_GUARD"
    event = $eventName
    turn_id = $turnId
    generated_at = (Get-Date).ToString("o")
    flags = $flags
    blocking_scope = "explicit_completion_or_stop_claim_intent_or_clear_text_claim_only"
    checks = [ordered]@{
        has_completion_claim_intent = $hasCompletionClaimIntent
        has_stop_claim_intent = $hasStopClaimIntent
        declares_complete_allowed = $declaresCompleteAllowed
        declares_stop_allowed = $declaresStopAllowed
        declares_done_as_completion = $declaresDoneAsCompletion
        has_non_blocking_keyword_mention = $hasNonBlockingKeywordMention
        keyword_mentions_are_non_blocking = $true
        explicit_user_stop_requested = $explicitUserStopRequested
        explicit_user_stop_overrides_fake_stop_guard = $true
    }
    continuation_audit_ref = $continuationAuditPath
    continuation_audit_error = $continuationAuditError
    stop_guard_layer_runner_refs = $stopGuardLayerRunnerRefs
    report_then_continue_gate_ref = ConvertTo-JsonSafePath (Join-Path $RuntimeRoot "state\report_then_continue_gate\latest.json")
    report_then_continue_gate = $reportThenContinueGate
    continuation_rule = "Before report/final/PASS/Stop semantics, anchor to source text, compare runtime/local gap, and emit a Stop continue protocol when report is allowed but source/backend debt remains."
    rule = "Block only explicit completion/stop claim intent or clear complete_allowed/stop_allowed/done-as-completion text unless the user explicitly asked to stop. Do not block discussion, read-only audit, repair, delegation, safety discussion, PASS/final wording, fanout mentions, or explicit user stop."
    named_blocker = if ($flags.Count -gt 0) { "CODEX_S_SIDE_AUDIT_BLOCKED_FAKE_STOP" } else { "" }
}
$auditJson = ($audit | ConvertTo-Json -Depth 8)
[IO.File]::WriteAllText($latestPath, $auditJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

if ($flags.Count -gt 0) {
    Invoke-MetaMinuteCheckpoint `
        -Trigger "after_gate_hook_deny" `
        -CurrentUserObject "Codex S side-audit hook deny branch" `
        -LatestUserDelta "SideAudit blocked fake completion/stop wording; classify possible gate/hook deny and continue safe next machine action"
    [ordered]@{
        decision = "block"
        reason = "Codex S side audit detected explicit completion/stop claim surface: $($flags -join ', '). Continue with repair, verification, delegation, or a named blocker unless this is an accepted task-scoped claim."
        suppressOutput = $false
    } | ConvertTo-Json -Depth 4 -Compress
    exit 0
}

if ($reportThenContinueGate.continue_protocol_required -eq $true) {
    $reason = if ($reportThenContinueGate.reason_categories) {
        (($reportThenContinueGate.reason_categories | ForEach-Object { [string]$_ }) -join ",")
    } else {
        "report_then_continue_required"
    }
    Emit-StopContinueProtocol -Reason $reason
}

[ordered]@{
    suppressOutput = $true
    decision = "allow_stop"
} | ConvertTo-Json -Depth 4 -Compress
