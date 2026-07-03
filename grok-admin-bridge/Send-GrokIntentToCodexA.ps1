[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$UserIntentCn,
    [string]$SemanticObject = "",
    [string]$ExpectedState = "",
    [string]$IntentOneLiner = "",
    [string]$MustDoOneLiner = "",
    [string]$ForbiddenOneLiner = "",
    [string]$AcceptanceOneLiner = "",
    [string]$TargetTaskId = "",
    [string]$AnchorTaskId = "",
    [string]$DeliveryRole = "",
    [ValidateSet("", "pass", "fail", "hold", "pass_partial")]
    [string]$GrokVerdict = "",
    [string]$RoutingVerb = "",
    [string]$SegmentId = "",
    [int]$DedupeMinutes = 45,
    [switch]$ForceResend,
    [int]$WaitSec = 60,
    [switch]$NoWake,
    [switch]$ReferenceOnly,
    [switch]$BackendOnly,
    [switch]$SkipVisible,
    [switch]$DualVisible,
    [string]$DesktopPackagePath = "",
    [switch]$SkipDesktopPackageResolve,
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
$bridgeScriptRoot = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
}
if (-not $ConfigPath.Trim()) {
    $ConfigPath = Join-Path $bridgeScriptRoot "bridge.config.json"
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Read-JsonFile {
    param([string]$Path)
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Expand-VisibleShortMessage {
    param(
        [string]$Template,
        [string]$TaskId,
        [string]$IntentOneLiner,
        [string]$ForbiddenOneLiner,
        [string]$MustDoOneLiner,
        [string]$AcceptanceOneLiner
    )
    $text = $Template
    $text = $text.Replace("{task_id}", $TaskId)
    $text = $text.Replace("{intent_one_liner}", $IntentOneLiner)
    $text = $text.Replace("{forbidden_one_liner}", $ForbiddenOneLiner)
    $text = $text.Replace("{must_do_one_liner}", $MustDoOneLiner)
    $text = $text.Replace("{acceptance_one_liner}", $AcceptanceOneLiner)
    return $text
}

function Test-IsExistingFilePath {
    param([string]$Candidate)
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return $false }
    $trimmed = $Candidate.Trim()
    if ($trimmed -match '^[A-Za-z]:\\') {
        return Test-Path -LiteralPath $trimmed -PathType Leaf
    }
    return $false
}

function Resolve-GrokDesktopPackageRefs {
    param(
        $Config,
        [string]$ExplicitDesktopPackagePath,
        [string]$SemanticObjectInput,
        [switch]$SkipResolve
    )
    $policy = $null
    if ($Config -and $Config.desktop_package_priority) {
        $policy = $Config.desktop_package_priority
    }
    $enabled = if ($policy -and $null -ne $policy.enabled_default) { [bool]$policy.enabled_default } else { $true }
    if ($SkipResolve -or -not $enabled) {
        return [ordered]@{
            resolved = $false
            primary_package = ""
            authority_refs = @()
            semantic_object = $SemanticObjectInput
            resolve_mode = "skipped"
        }
    }

    $desktopRoot = if ($policy -and $policy.desktop_root) { [string]$policy.desktop_root } else { "C:\Users\xx363\Desktop" }
    $known = if ($policy -and $policy.known_files) { $policy.known_files } else { $null }

    $primary = ""
    $refs = New-Object System.Collections.Generic.List[string]
    $resolveMode = ""

    if (Test-IsExistingFilePath -Candidate $ExplicitDesktopPackagePath) {
        $primary = $ExplicitDesktopPackagePath.Trim()
        $resolveMode = "explicit_param"
    }
    elseif (Test-IsExistingFilePath -Candidate $SemanticObjectInput) {
        $primary = $SemanticObjectInput.Trim()
        $resolveMode = "semantic_object_is_path"
    }
    else {
        if ($known -and $known.correction_json_glob) {
            $corr = Get-ChildItem -LiteralPath $desktopRoot -Filter ([string]$known.correction_json_glob) -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if ($corr) {
                $primary = $corr.FullName
                $resolveMode = "desktop_correction_json_newest"
            }
        }
        if (-not $primary -and $known -and $known.start_package) {
            $startPath = Join-Path $desktopRoot ([string]$known.start_package)
            if (Test-Path -LiteralPath $startPath -PathType Leaf) {
                $primary = $startPath
                $resolveMode = "desktop_start_package_txt"
            }
        }
    }

    foreach ($key in @("master_ledger", "infra_order", "progress_lens")) {
        if (-not $known -or -not $known.$key) { continue }
        $refPath = Join-Path $desktopRoot ([string]$known.$key)
        if (Test-Path -LiteralPath $refPath -PathType Leaf) {
            if ($refPath -ne $primary) { $refs.Add($refPath) | Out-Null }
        }
    }

    if (-not $primary) {
        return [ordered]@{
            resolved = $false
            primary_package = ""
            authority_refs = @($refs)
            semantic_object = $SemanticObjectInput
            resolve_mode = "no_desktop_package_found"
        }
    }

    $refBlock = if ($refs.Count -gt 0) {
        ($refs | ForEach-Object { "- $_" }) -join "`n"
    } else {
        "- (none beyond primary)"
    }

    $semanticObject = @"
[DESKTOP_AUTHORITY_PACKAGE_PATH_FIRST]
resolve_mode: $resolveMode
primary_package: $primary
authority_refs:
$refBlock

binding:
- CodexA MUST read primary_package + authority_refs from disk (full package, no chat shrink)
- Grok delivery is path-first; do NOT substitute inline JSON summary for file contents
- Phase/smoke PASS != user completion; progress truth lens applies

read_order:
1) primary_package
2) authority_refs (master ledger / infra order / progress lens)
3) D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\ + capabilities\
"@

    return [ordered]@{
        resolved = $true
        primary_package = $primary
        authority_refs = @($refs)
        semantic_object = $semanticObject
        resolve_mode = $resolveMode
    }
}

function Get-ActionWriteJobPath {
    param([string]$TaskId, [string]$RuntimeRoot)
    if (-not $TaskId) { return "" }
    return Join-Path $RuntimeRoot ("state\action_write_jobs\{0}.json" -f $TaskId)
}

function Test-GrokSegmentVerdictAlreadyDelivered {
    param(
        [string]$TargetTaskId,
        [string]$SegmentId,
        [string]$Verdict,
        [string]$RuntimeRoot,
        [int]$WithinMinutes
    )
    $jobPath = Get-ActionWriteJobPath -TaskId $TargetTaskId -RuntimeRoot $RuntimeRoot
    if (-not (Test-Path -LiteralPath $jobPath)) { return $false }
    try {
        $job = Read-JsonFile -Path $jobPath
    }
    catch { return $false }
    if (-not $job.ok) { return $false }
    $status = [string]$job.status
    if ($status -notmatch "grok_segment_verdict") { return $false }
    $signal = $job.grok_segment_verdict_signal
    if (-not $signal) { return $false }
    if (-not $signal.signal_sent) { return $false }
    $readback = $job.grok_segment_verdict_readback
    if ($readback -and $readback.verdict) {
        $deliveredVerdict = [string]$readback.verdict
    }
    else {
        $req = $job.request_payload
        $deliveredVerdict = if ($req.verdict) { [string]$req.verdict } else { "" }
    }
    $normalizedWanted = if ($Verdict -eq "pass_partial") { "pass" } else { $Verdict }
    $normalizedDelivered = if ($deliveredVerdict -eq "pass_partial") { "pass" } else { $deliveredVerdict }
    if ($normalizedWanted -and $normalizedDelivered -and $normalizedWanted -ne $normalizedDelivered) {
        return $false
    }
    if ($SegmentId) {
        $reqSeg = ""
        if ($job.request_payload.segment_id) { $reqSeg = [string]$job.request_payload.segment_id }
        if ($reqSeg -and $reqSeg -ne $SegmentId) { return $false }
    }
    $updatedAt = [string]$job.updated_at
    if ($updatedAt -and $WithinMinutes -gt 0) {
        try {
            $ts = [datetimeoffset]::Parse($updatedAt)
            if ((Get-Date) - $ts.LocalDateTime -gt [TimeSpan]::FromMinutes($WithinMinutes)) {
                return $false
            }
        }
        catch {}
    }
    return $true
}

function Test-GrokContinueIntentRecentlyAccepted {
    param(
        [string]$AnchorTaskId,
        [string]$RuntimeRoot,
        [int]$WithinMinutes
    )
    $jobPath = Get-ActionWriteJobPath -TaskId $AnchorTaskId -RuntimeRoot $RuntimeRoot
    if (-not (Test-Path -LiteralPath $jobPath)) { return $false }
    try {
        $job = Read-JsonFile -Path $jobPath
    }
    catch { return $false }
    if (-not $job.ok) { return $false }
    $req = $job.request_payload
    if (-not $req) { return $false }
    if ([string]$req.routing_verb -ne "continue_same_task") { return $false }
    if ([string]$req.delivery_role -eq "grok_segment_verdict") { return $false }
    $panel = $job.panel_readback
    if ($panel -and $panel.partial_continuation_dispatched -eq $true) { return $true }
    if ($panel -and $panel.backend_codex_worker_dispatch -eq $true) { return $true }
    $updatedAt = [string]$job.updated_at
    if ($updatedAt -and $WithinMinutes -gt 0) {
        try {
            $ts = [datetimeoffset]::Parse($updatedAt)
            if ((Get-Date) - $ts.LocalDateTime -gt [TimeSpan]::FromMinutes($WithinMinutes)) {
                return $false
            }
        }
        catch {}
    }
    return $true
}

function Resolve-GrokToCodexAVisibleHotPath {
    param(
        $Config,
        $DualPolicy
    )
    $hot = $null
    if ($Config -and $Config.grok_to_codex_a_visible_hot_path) {
        $hot = $Config.grok_to_codex_a_visible_hot_path
    }
    $scriptPath = if ($hot -and $hot.script) { [string]$hot.script } else { [string]$DualPolicy.visible.script }
    return [ordered]@{
        script = $scriptPath
        typeahead = if ($hot -and $null -ne $hot.typeahead) { [bool]$hot.typeahead } else { [bool]$DualPolicy.visible.typeahead }
        user_launcher = if ($hot -and $hot.user_launcher) { [string]$hot.user_launcher } elseif ($DualPolicy.visible.user_launcher) { [string]$DualPolicy.visible.user_launcher } else { "" }
        hardmode_launcher_script = if ($hot -and $hot.hardmode_launcher_script) { [string]$hot.hardmode_launcher_script } elseif ($DualPolicy.visible.hardmode_launcher_script) { [string]$DualPolicy.visible.hardmode_launcher_script } else { "C:\\Users\\xx363\\CodexLaunchers\\Open-Codex-S-Hardmode.ps1" }
        scheduled_task = if ($hot -and $hot.scheduled_task) { [string]$hot.scheduled_task } elseif ($DualPolicy.visible.scheduled_task) { [string]$DualPolicy.visible.scheduled_task } else { "XINAO_OPEN_CODEX_S_HARDMODE" }
        window_title = if ($hot -and $hot.target_window_title) { [string]$hot.target_window_title } elseif ($DualPolicy.visible.target_window_title) { [string]$DualPolicy.visible.target_window_title } else { "S" }
        managed_home = if ($hot -and $hot.managed_home) { [string]$hot.managed_home } elseif ($DualPolicy.visible.managed_home) { [string]$DualPolicy.visible.managed_home } else { "C:\\Users\\xx363\\.codex-seed-cortex" }
        wait_sec = if ($hot -and $hot.wait_sec) { [int]$hot.wait_sec } elseif ($DualPolicy.visible.wait_sec) { [int]$DualPolicy.visible.wait_sec } else { 75 }
        wake_on_miss = if ($hot -and $null -ne $hot.wake_on_miss) { [bool]$hot.wake_on_miss } else { $true }
        no_wake_default = if ($hot -and $null -ne $hot.no_wake_default) { [bool]$hot.no_wake_default } else { $false }
        sentinel = if ($hot -and $hot.sentinel) { [string]$hot.sentinel } else { "SENTINEL:GROK_TO_CODEX_A_VISIBLE_HOT_PATH_V1" }
    }
}

function Invoke-GrokVisibleTypeahead {
    param(
        $Config,
        $DualPolicy,
        [string]$Message,
        [int]$WaitSec,
        [bool]$NoWake
    )
    $hotPath = Resolve-GrokToCodexAVisibleHotPath -Config $Config -DualPolicy $DualPolicy
    $scriptPath = [string]$hotPath.script
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        return [ordered]@{
            status = "failed"
            named_blocker = "VISIBLE_TYPEAHEAD_SCRIPT_MISSING"
            script = $scriptPath
            hot_path_sentinel = [string]$hotPath.sentinel
        }
    }
    $visibleWait = [int]$hotPath.wait_sec
    if ($visibleWait -le 0) { $visibleWait = $WaitSec }
    # Direct invoke — Start-Process -ArgumentList array does not quote $Message (spaces/parens break -Message).
    $invokeParams = @{
        Message = $Message
        WaitSec = $visibleWait
        WindowTitle = [string]$hotPath.window_title
        ManagedHome = [string]$hotPath.managed_home
    }
    if ($hotPath.typeahead) { $invokeParams.Typeahead = $true }
    # Hot path: HARDMODE A tab via desktop lnk; never NoWake on typeahead; never Grok-island visible script.
    if ($hotPath.typeahead) {
        $invokeParams.NoWake = $false
    }
    elseif ($NoWake) {
        $invokeParams.NoWake = $true
    }
    if ($hotPath.user_launcher) { $invokeParams.UserLauncher = [string]$hotPath.user_launcher }
    if ($hotPath.hardmode_launcher_script) { $invokeParams.HardmodeLauncherScript = [string]$hotPath.hardmode_launcher_script }
    if ($hotPath.scheduled_task) { $invokeParams.HardmodeScheduledTask = [string]$hotPath.scheduled_task }
    & $scriptPath @invokeParams
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    $completed = [pscustomobject]@{ ExitCode = $exitCode }
    $latest = Join-Path "D:\XINAO_CLEAN_RUNTIME\state\codexa_managed_visible_inject" "latest.json"
    if (Test-Path -LiteralPath $latest) {
        try {
            $payload = Read-JsonFile -Path $latest
            return [ordered]@{
                status = if ($payload.status) { [string]$payload.status } else { "unknown" }
                named_blocker = if ($payload.named_blocker) { [string]$payload.named_blocker } else { "" }
                sentinel = if ($payload.sentinel) { [string]$payload.sentinel } else { "" }
                session_modified_after_send = if ($payload.evidence.session_modified_after_send) { [bool]$payload.evidence.session_modified_after_send } else { $false }
                assistant_seen = if ($payload.evidence.assistant_seen) { [bool]$payload.evidence.assistant_seen } else { $false }
                selected_tab = if ($payload.target_tab_name) { [string]$payload.target_tab_name } else { "" }
                exit_code = $completed.ExitCode
                latest_state_path = $latest
            }
        }
        catch {}
    }
    return [ordered]@{
        status = if ($completed.ExitCode -eq 0) { "managed_visible_typeahead_sent" } else { "failed" }
        exit_code = $completed.ExitCode
        named_blocker = if ($completed.ExitCode -ne 0) { "VISIBLE_TYPEAHEAD_NONZERO_EXIT" } else { "" }
    }
}

$config = Read-JsonFile -Path $ConfigPath
$runtimeRoot = if ($config.runtime_root) { [string]$config.runtime_root } else { "D:\XINAO_CLEAN_RUNTIME" }
$templatePath = Join-Path $PSScriptRoot "grok_to_codexa_intent_delivery.template.json"
$template = Read-JsonFile -Path $templatePath
$dualPolicy = $config.dual_delivery_policy

function Get-EffectiveNoWake {
    param(
        [switch]$NoWake,
        $DualPolicy
    )
    if ($PSBoundParameters.ContainsKey('NoWake')) {
        return [bool]$NoWake
    }
    if ($DualPolicy -and $DualPolicy.visible -and $DualPolicy.visible.PSObject.Properties.Name -contains 'no_wake_default') {
        return [bool]$DualPolicy.visible.no_wake_default
    }
    return $true
}

$effectiveNoWake = Get-EffectiveNoWake -NoWake:$NoWake -DualPolicy $dualPolicy

$resolvedDeliveryRole = if ($DeliveryRole.Trim()) {
    $DeliveryRole.Trim()
}
elseif ($GrokVerdict.Trim()) {
    "grok_segment_verdict"
}
else {
    "grok_intent_preservation_entry"
}

$resolvedTargetTaskId = if ($TargetTaskId.Trim()) { $TargetTaskId.Trim() } elseif ($AnchorTaskId.Trim()) { $AnchorTaskId.Trim() } else { "" }
$resolvedAnchorTaskId = if ($AnchorTaskId.Trim()) { $AnchorTaskId.Trim() } else { $resolvedTargetTaskId }
$ingressVerdict = if ($GrokVerdict -eq "pass_partial") { "pass" } else { $GrokVerdict.Trim() }

if (-not $ForceResend -and $resolvedDeliveryRole -eq "grok_segment_verdict" -and $resolvedTargetTaskId) {
    if (Test-GrokSegmentVerdictAlreadyDelivered -TargetTaskId $resolvedTargetTaskId -SegmentId $SegmentId -Verdict $GrokVerdict -RuntimeRoot $runtimeRoot -WithinMinutes $DedupeMinutes) {
        [ordered]@{
            schema_version = "xinao.grok_admin_bridge.inject_result.v2"
            status = "skipped_duplicate"
            delivery_mode = "dedupe_no_resend"
            delivery_role = $resolvedDeliveryRole
            target_task_id = $resolvedTargetTaskId
            segment_id = $SegmentId
            grok_verdict = $GrokVerdict
            reason_cn = "同 anchor+segment 已成功 leg2 signal；勿重复投递 verdict"
            action_write_job = Get-ActionWriteJobPath -TaskId $resolvedTargetTaskId -RuntimeRoot $runtimeRoot
            verify_hint = "用户说没发出去才加 -ForceResend"
        } | ConvertTo-Json -Depth 8
        return
    }
}

if (-not $ForceResend -and $RoutingVerb -eq "continue_same_task" -and $resolvedAnchorTaskId -and $resolvedDeliveryRole -ne "grok_segment_verdict") {
    if (Test-GrokContinueIntentRecentlyAccepted -AnchorTaskId $resolvedAnchorTaskId -RuntimeRoot $runtimeRoot -WithinMinutes 10) {
        [ordered]@{
            schema_version = "xinao.grok_admin_bridge.inject_result.v2"
            status = "skipped_duplicate"
            delivery_mode = "dedupe_no_resend"
            routing_verb = $RoutingVerb
            anchor_task_id = $resolvedAnchorTaskId
            reason_cn = "近期 continue_same_task 已 ACCEPT 且 worker 已派工；勿重复投递"
            action_write_job = Get-ActionWriteJobPath -TaskId $resolvedAnchorTaskId -RuntimeRoot $runtimeRoot
            verify_hint = "A 仍 IDLE 且 partial_continuation_dispatched=false 时用 -ForceResend"
        } | ConvertTo-Json -Depth 8
        return
    }
}

$useDual = $false
if ($dualPolicy -and $dualPolicy.enabled_default -and -not $ReferenceOnly -and -not $BackendOnly -and -not $SkipVisible) {
    if ($PSBoundParameters.ContainsKey('DualVisible')) {
        $useDual = [bool]$DualVisible
    }
    else {
        $useDual = [bool]$dualPolicy.user_at_computer_default
    }
}

$episodeId = "YELLOW_BOOTSTRAP_INTENT_SPINE_MISSING"
if (Test-Path -LiteralPath $config.intent_episode_ref) {
    try {
        $episode = Read-JsonFile -Path $config.intent_episode_ref
        if ($episode.intent_id) { $episodeId = [string]$episode.intent_id }
    }
    catch {}
}
$admittedId = ""
if (Test-Path -LiteralPath $config.intent_state_ref) {
    try {
        $state = Read-JsonFile -Path $config.intent_state_ref
        if ($state.current_intent_id) { $admittedId = [string]$state.current_intent_id }
    }
    catch {}
}
$currentIntentId = if ($admittedId) { $admittedId } else { $episodeId }

$desktopResolve = Resolve-GrokDesktopPackageRefs `
    -Config $config `
    -ExplicitDesktopPackagePath $DesktopPackagePath `
    -SemanticObjectInput $SemanticObject `
    -SkipResolve:$SkipDesktopPackageResolve
if ($desktopResolve.resolved) {
    $SemanticObject = [string]$desktopResolve.semantic_object
}
elseif (-not $SemanticObject.Trim()) {
    $SemanticObject = ($UserIntentCn -split "`n" | Select-Object -First 1).Trim()
    if (-not $SemanticObject) { $SemanticObject = $UserIntentCn.Trim() }
}

if (-not $IntentOneLiner.Trim()) {
    $IntentOneLiner = ($SemanticObject -split "[。；\n]" | Select-Object -First 1).Trim()
    if (-not $IntentOneLiner) { $IntentOneLiner = $SemanticObject.Trim() }
    if ($IntentOneLiner.Length -gt 80) { $IntentOneLiner = $IntentOneLiner.Substring(0, 80) }
}

$defaults = $dualPolicy.visible_short_defaults
if (-not $ForbiddenOneLiner.Trim() -and $defaults.forbidden_one_liner) {
    $ForbiddenOneLiner = [string]$defaults.forbidden_one_liner
}
if (-not $MustDoOneLiner.Trim() -and $defaults.must_do_one_liner) {
    $MustDoOneLiner = [string]$defaults.must_do_one_liner
}
if (-not $AcceptanceOneLiner.Trim() -and $defaults.acceptance_one_liner) {
    $AcceptanceOneLiner = [string]$defaults.acceptance_one_liner
}

$delivery = [ordered]@{
    schema_version = $template.schema_version
    delivery_role = $template.delivery_role
    not_task_owner = $true
    not_completion_decision = $true
    not_execution_controller = $true
    current_intent_id = $currentIntentId
    user_intent_cn = $UserIntentCn
    semantic_object = $SemanticObject
    expected_state = $ExpectedState
    forbidden_reductions = @($template.forbidden_reductions)
    handoff_to = $template.handoff_to
    authority = $template.authority
    intent_event_policy = $template.intent_event_policy
    generated_at = (Get-Date).ToString("o")
}

$message = @"
[GROK_INTENT_PRESERVATION_DELIVERY_NOT_INSTRUCTION]
delivery_role: grok_intent_preservation_entry
current_intent_id: $currentIntentId
not_task_owner: true
handoff_to: CodexA_brain_turn

semantic_object:
$SemanticObject

user_intent_cn:
$UserIntentCn

expected_state:
$ExpectedState

forbidden_reductions:
- do not shrink semantic_object
- do not replace with matrix/report before execution
- do not treat this package as completion evidence

execution_model (binding):
- CodexA = brain only; forbid default hand-roll all roles
- require WORKER_ASSIGNMENT before execution
- parallel official subagent pre-review where applicable
- light work -> CodexB + GPT-5.3-Codex-Spark via SDK/app-server
- heavy work -> DP main model workers
- mature carriers: subagent, SDK, codex exec --json, app-server; shell = rescue only
- Grok = side audit only; not task owner

required_next_steps_for_A:
$(
    $steps = @($template.required_next_steps_for_A)
    if (-not $steps -or $steps.Count -eq 0) {
        $steps = @(
            "Re-anchor semantic_object from this package (not from chat memory)"
            "Generate WORKER_ASSIGNMENT"
            "Dispatch mature carriers; local shell is rescue only"
        )
    }
    for ($i = 0; $i -lt $steps.Count; $i++) { "{0}. {1}" -f ($i + 1), $steps[$i] } -join "`n"
)
[/GROK_INTENT_PRESERVATION_DELIVERY_NOT_INSTRUCTION]
"@

$body = [ordered]@{
    message = $message
    source_kind = if ($ReferenceOnly) { $config.delivery_policy.reference_only_source_kind } else { $config.delivery_policy.default_source_kind }
    target_policy = if ($ReferenceOnly) { "single_codexa_managed_visible_conversation" } else { "mature_intent_entry_temporal_owner_app_server" }
    execute_policy = if ($ReferenceOnly) { "reference_only" } else { $config.delivery_policy.default_execute_policy }
    wait_sec = $WaitSec
    no_wake = [bool]$effectiveNoWake
    grok_delivery = $delivery
    delivery_role = $resolvedDeliveryRole
    desktop_package_resolve = $desktopResolve
}

if ($resolvedTargetTaskId) { $body.target_task_id = $resolvedTargetTaskId }
if ($resolvedAnchorTaskId) { $body.anchor_task_id = $resolvedAnchorTaskId }
if ($RoutingVerb.Trim()) { $body.routing_verb = $RoutingVerb.Trim() }
if ($SegmentId.Trim()) { $body.segment_id = $SegmentId.Trim() }

if ($resolvedDeliveryRole -eq "grok_segment_verdict" -and $ingressVerdict) {
    $body.verdict = $ingressVerdict
    $body.grok_verdict = $ingressVerdict
    $body.verdict_delivery_mode = "dual_visible_and_backend"
    $body.delivery_mode = "dual_visible_and_backend"
    if ($SegmentId.Trim()) { $body.segment_audit_ready = $true }
    $body.grok_segment_verdict = [ordered]@{
        verdict = $ingressVerdict
        grok_verdict = $ingressVerdict
        target_task_id = $resolvedTargetTaskId
        delivery_role = "grok_segment_verdict"
        verdict_delivery_mode = "dual_visible_and_backend"
    }
    if ($SegmentId.Trim()) {
        $body.grok_segment_verdict.segment_id = $SegmentId.Trim()
        $body.grok_segment_verdict.segment_audit_ready = $true
    }
}

if ($ReferenceOnly) {
    $body.wrap_as_reference = $true
    $uri = ($config.ingress_base_url.TrimEnd('/') + $config.delivery_policy.reference_only_endpoint)
} else {
    $uri = ($config.ingress_base_url.TrimEnd('/') + $config.delivery_policy.default_endpoint)
}
$json = $body | ConvertTo-Json -Depth 10
try {
    $resp = Invoke-WebRequest -Uri $uri -Method POST -Body $json -ContentType "application/json; charset=utf-8" -UseBasicParsing -TimeoutSec ([Math]::Min(180, $WaitSec + 60))
    $result = $resp.Content | ConvertFrom-Json
    $deliveryRoute = if ($ReferenceOnly) { "visible-inject-reference-only" } else { "codex-a-intent-main-chain" }
    $taskId = if ($result.task_id) { [string]$result.task_id } elseif ($result.inject_id) { [string]$result.inject_id } else { "" }

    $ingressOk = $false
    if ($result.ok -eq $true) { $ingressOk = $true }
    if ([string]$result.status -match "^(ACCEPTED|grok_segment_verdict)") { $ingressOk = $true }
    if ($resolvedTargetTaskId -and $taskId -and $taskId -ne $resolvedTargetTaskId -and $resolvedDeliveryRole -eq "grok_segment_verdict") {
        [ordered]@{
            schema_version = "xinao.grok_admin_bridge.inject_result.v2"
            status = "blocked_wrong_task_id"
            http_status = $resp.StatusCode
            delivery_role = $resolvedDeliveryRole
            target_task_id = $resolvedTargetTaskId
            ingress_task_id = $taskId
            ingress_result = $result
            named_blocker = "GROK_SEGMENT_VERDICT_TARGET_TASK_ID_MISMATCH"
            reason_cn = "ingress 未绑定 anchor；勿当成功；检查顶层 target_task_id"
        } | ConvertTo-Json -Depth 10
        exit 1
    }
    if (-not $ingressOk -and [string]$result.named_blocker) {
        [ordered]@{
            schema_version = "xinao.grok_admin_bridge.inject_result.v2"
            status = "blocked"
            http_status = $resp.StatusCode
            delivery_role = $resolvedDeliveryRole
            target_task_id = $resolvedTargetTaskId
            ingress_task_id = $taskId
            named_blocker = [string]$result.named_blocker
            ingress_result = $result
        } | ConvertTo-Json -Depth 10
        exit 1
    }

    $visibleResult = $null
    if ($useDual -and $taskId -and $dualPolicy.visible_short_template_cn) {
        $visibleMessage = Expand-VisibleShortMessage `
            -Template ([string]$dualPolicy.visible_short_template_cn) `
            -TaskId $taskId `
            -IntentOneLiner $IntentOneLiner `
            -ForbiddenOneLiner $ForbiddenOneLiner `
            -MustDoOneLiner $MustDoOneLiner `
            -AcceptanceOneLiner $AcceptanceOneLiner
        $visibleResult = Invoke-GrokVisibleTypeahead -Config $config -DualPolicy $dualPolicy -Message $visibleMessage -WaitSec $WaitSec -NoWake:$effectiveNoWake
    }

    [ordered]@{
        schema_version = "xinao.grok_admin_bridge.inject_result.v2"
        status = if ($ingressOk) { "accepted" } else { "accepted_verify_ingress" }
        http_status = $resp.StatusCode
        delivery_mode = if ($useDual) { "dual_visible_and_backend" } else { $deliveryRoute }
        delivery_route = $deliveryRoute
        delivery_role = $resolvedDeliveryRole
        target_task_id = $resolvedTargetTaskId
        anchor_task_id = $resolvedAnchorTaskId
        routing_verb = $RoutingVerb
        segment_id = $SegmentId
        grok_verdict = $GrokVerdict
        endpoint = $uri
        source_kind = $body.source_kind
        execute_policy = $body.execute_policy
        current_intent_id = $currentIntentId
        semantic_object = $SemanticObject
        desktop_package_resolve = $desktopResolve
        task_id = $taskId
        ingress_ok = $ingressOk
        ingress_result = $result
        visible_delivery = $visibleResult
        visible_blocker = if ($visibleResult -and $visibleResult.named_blocker) { [string]$visibleResult.named_blocker } else { "" }
        visible_ok = if ($visibleResult -and $visibleResult.status -match "sent|readback_seen") { $true } elseif (-not $useDual) { $null } else { $false }
        verify_hint = if ($visibleResult -and $visibleResult.named_blocker) {
            "可见通道阻断: $($visibleResult.named_blocker)；后台 task_id=$taskId 可能已接活。请确认 A 标签窗口；或重试 typeahead。"
        } else {
            "GET $($config.ingress_base_url)/result/wait?id=$taskId&wait_sec=45 and GET $($config.ingress_base_url)/codex-a/panel-readback"
        }
    } | ConvertTo-Json -Depth 12
}
catch {
    $detail = $_.Exception.Message
    if ($_.Exception.Response) {
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $detail = $reader.ReadToEnd()
        }
        catch {}
    }
    [ordered]@{
        schema_version = "xinao.grok_admin_bridge.inject_result.v2"
        status = "failed"
        current_intent_id = $currentIntentId
        semantic_object = $SemanticObject
        error = $detail
    } | ConvertTo-Json -Depth 6
    exit 1
}