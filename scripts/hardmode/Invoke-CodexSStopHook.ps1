[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$SideAuditJsonOverride = ""
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$stdinReader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $stdinReader.ReadToEnd()

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$metaMinuteScript = Join-Path $scriptRoot "Invoke-CodexSMetaMinutePreflight.ps1"
$sideAuditScript = Join-Path $scriptRoot "Invoke-CodexSSideAuditHook.ps1"
$stateRoot = Join-Path $RuntimeRoot "state\codex_s_stop_hook"
$latestPath = Join-Path $stateRoot "latest.json"

function Write-StopHookState {
    param(
        [string]$Status,
        [string]$SelectedOutput,
        [array]$RawOutput,
        [string]$ErrorText,
        [object]$TextTaskReanchor
    )

    New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
    $payload = [ordered]@{
        schema_version = "xinao.codex_s.stop_hook_wrapper.v1"
        status = $Status
        generated_at = (Get-Date).ToString("o")
        repo_root = $RepoRoot
        runtime_root = $RuntimeRoot
        metaminute_script = $metaMinuteScript
        side_audit_script = $sideAuditScript
        selected_hook_output = $SelectedOutput
        post_report_text_task_reanchor = $TextTaskReanchor
        raw_output_tail = @($RawOutput | Select-Object -Last 8 | ForEach-Object { [string]$_ })
        error = $ErrorText
        single_output_wrapper = $true
        invokes_metaminute_before_side_audit = $true
        returns_side_audit_hook_json_only = $true
        stop_hook_dispatches_root_intent_loop_driver = $false
        stop_hook_is_execution_controller = $false
        not_completion_gate = $true
        not_execution_controller = $true
        sentinel = "SENTINEL:XINAO_CODEX_S_STOP_HOOK_WRAPPER_READY"
    }
    [IO.File]::WriteAllText(
        $latestPath,
        (($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
}

function U {
    param([string]$Value)
    return [regex]::Unescape($Value)
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

function Test-PatternGroups {
    param(
        [string]$Text,
        [object[]]$PatternGroups
    )
    foreach ($group in $PatternGroups) {
        if (-not (Test-AnyPattern -Text $Text -Patterns @($group))) {
            return $false
        }
    }
    return $true
}

function Get-ClosureEvidenceBundleStatus {
    param(
        [string]$UserText,
        [string]$AssistantText
    )

    $intentPatterns = @(
        "(?i)\b(closeout|closure|landed|complete closeout|full closeout)\b",
        (U "\u6536\u53e3"),
        (U "\u5b8c\u6574\u6536\u53e3"),
        (U "\u5168\u90e8\u6536\u53e3"),
        (U "\u6536\u53e3\u57fa\u7840"),
        (U "\u9ed8\u8ba4\u4e3b\u8def"),
        (U "\u8fd0\u884c\u6001"),
        (U "\u63d0\u4ea4\u63a8\u9001"),
        (U "\u63d0\u4ea4\u5408\u5e76"),
        (U "\u8bc1\u636e/readback")
    )
    $closureIntent = Test-AnyPattern -Text (($UserText + "`n" + $AssistantText)) -Patterns $intentPatterns
    $requiredFields = @(
        "default_mainline_weld_point",
        "runtime_worker_loaded",
        "verification_passed",
        "evidence_readback_written",
        "git_status_clean",
        "commit_hash",
        "push_target",
        "mainline_state",
        "remaining_state"
    )
    $groups = [ordered]@{
        default_mainline_weld_point = @(
            @("(?i)default mainline", "RootIntentLoop", "S Default Dynamic Loop", "TemporalCodexTaskWorkflow\.run", (U "\u9ed8\u8ba4\u4e3b\u8def"), (U "\u710a"), (U "\u7ed1\u5b9a"))
        )
        runtime_worker_loaded = @(
            @("(?i)\bworker\b", "(?i)\bpid\b", "(?i)\bpolling\b", "(?i)\bpollers\b", (U "\u8fd0\u884c\u6001")),
            @("(?i)\bpolling\b", "(?i)\bpollers\b", "(?i)\bpid\b", "(?i)\bloaded\b", "(?i)\brestarted\b", "(?i)process_alive", (U "\u52a0\u8f7d"), (U "\u91cd\u542f"))
        )
        verification_passed = @(
            @("(?i)\btest\b", "(?i)\bpytest\b", "(?i)\bverifier\b", (U "\u9a8c\u8bc1"), (U "\u6d4b\u8bd5")),
            @("(?i)\bpass(?:ed)?\b", "(?i)\bgreen\b", (U "\u901a\u8fc7"), (U "\u6210\u529f"))
        )
        evidence_readback_written = @(
            @("(?i)\bevidence\b", "(?i)\breadback\b", (U "\u8bc1\u636e"), (U "\u56de\u8bfb"))
        )
        git_status_clean = @(
            @("(?i)git status", "(?i)\bworktree\b", (U "\u5de5\u4f5c\u533a")),
            @("(?i)\bclean\b", "(?i)nothing to commit", (U "\u5e72\u51c0"), (U "\u65e0\u6539\u52a8"))
        )
        commit_hash = @(
            @("(?i)\bcommit\b", (U "\u63d0\u4ea4"), "(?i)\bsha\b", "(?i)\bhash\b"),
            @("(?i)\b[0-9a-f]{7,40}\b")
        )
        push_target = @(
            @("(?i)\bpush(?:ed)?\b", "(?i)origin/", (U "\u8fdc\u7aef"), (U "\u63a8\u9001"), (U "\u5408\u5e76")),
            @("(?i)origin/main", "(?i)\bmain\b", "(?i)\bremote\b", (U "\u8fdc\u7aef"), (U "\u5df2\u63a8\u9001"))
        )
        mainline_state = @(
            @("(?i)\b333\b", "(?i)\bTemporal\b", "RootIntentLoop", "(?i)\bmainline\b", (U "\u4e3b\u7ebf")),
            @("(?i)\bactive\b", "NO_ACTIVE_333_MAINLINE", "(?i)\bpolling\b", "(?i)\bworkflow\b", "(?i)\brun_id\b", "(?i)blocker", (U "\u6ca1\u6709"), (U "\u65e0"), (U "\u72b6\u6001"))
        )
        remaining_state = @(
            @("(?i)remaining_state", "(?i)remaining", "(?i)named_blocker", "(?i)\bblocker\b", "(?i)next_machine_action", (U "\u5269\u4f59"), (U "\u672a\u5b8c\u6210")),
            @("(?i)\bnone\b", "(?i)\bno\b", (U "\u65e0"), (U "\u6ca1\u6709"), "(?i)named_blocker", "BLOCKER", "NO_ACTIVE_333_MAINLINE", "TEMPORAL_")
        )
    }
    $checks = [ordered]@{}
    $missing = @()
    foreach ($field in $requiredFields) {
        $ok = Test-PatternGroups -Text $AssistantText -PatternGroups @($groups[$field])
        $checks[$field] = $ok
        if ($closureIntent -and (-not $ok)) {
            $missing += $field
        }
    }
    return [ordered]@{
        closure_intent = $closureIntent
        complete = ($closureIntent -and ($missing.Count -eq 0))
        required_fields = $requiredFields
        checks = $checks
        missing_fields = $missing
        rule = "Execution closure requires default mainline binding, runtime worker load, verification, evidence/readback, clean git status, commit hash, push target, 333/mainline state, and remaining/named-blocker state."
    }
}

function Get-StopEventText {
    $eventObject = $null
    try {
        if ($raw.Trim()) {
            $eventObject = $raw | ConvertFrom-Json
        }
    }
    catch {
        $eventObject = $null
    }

    $userText = ""
    $assistantText = ""
    if ($null -ne $eventObject) {
        if ($eventObject.user_prompt) {
            $userText = [string]$eventObject.user_prompt
        }
        elseif ($eventObject.last_user_message) {
            $userText = [string]$eventObject.last_user_message
        }
        if ($eventObject.last_assistant_message) {
            $assistantText = [string]$eventObject.last_assistant_message
        }
    }
    return [ordered]@{
        user_text = $userText
        assistant_text = $assistantText
    }
}

function Get-TextTaskReanchorDecision {
    param([object]$SelectedObject)

    $texts = Get-StopEventText
    $userText = [string]$texts.user_text
    $assistantText = [string]$texts.assistant_text

    $explicitStopPatterns = @(
        "(?i)(^|[^\w])stop([^\w]|$)",
        "(?i)(^|[^\w])pause([^\w]|$)",
        (U "\u505c\u6b62"),
        (U "\u505c\u4e0b"),
        (U "\u522b\u7ee7\u7eed"),
        (U "\u4e0d\u8981\u7ee7\u7eed"),
        (U "\u5148\u505c"),
        (U "\u6682\u505c"),
        (U "\u5230\u6b64\u4e3a\u6b62")
    )
    $executionPatterns = @(
        "(?i)\b(run|fix|repair|implement|verify|test|commit|push|merge|wire|bind|dispatch|invoke|search|audit|inspect|generate|update|land)\b",
        (U "\u4fee"),
        (U "\u5f04"),
        (U "\u843d\u5730"),
        (U "\u710a"),
        (U "\u56fa\u5316"),
        (U "\u63a5\u5165"),
        (U "\u63a5\u7ebf"),
        (U "\u68c0\u67e5"),
        (U "\u770b\u4e00\u4e0b"),
        (U "\u641c\u7d22"),
        (U "\u751f\u6210"),
        (U "\u5199\u5165"),
        (U "\u66f4\u65b0"),
        (U "\u63d0\u4ea4"),
        (U "\u63a8\u9001"),
        (U "\u5408\u5e76"),
        (U "\u9a8c\u8bc1"),
        (U "\u8dd1"),
        (U "\u8c03\u5ea6"),
        (U "\u76d8\u70b9"),
        (U "\u6574\u7406"),
        (U "\u6536\u53e3")
    )
    $dialogueOnlyPatterns = @(
        (U "\u8ba8\u8bba"),
        (U "\u89e3\u91ca"),
        (U "\u4e3a\u4ec0\u4e48"),
        (U "\u662f\u4e0d\u662f"),
        (U "\u7406\u89e3\u5417"),
        (U "\u4eba\u8bdd"),
        (U "\u5148\u8bf4"),
        "(?i)\bwhy\b",
        "(?i)\bexplain\b"
    )
    $incompletePatterns = @(
        "(?i)\b(todo|fixme|pending|running|blocked|blocker|failed|failure|not complete|not done|not wired|not hardened|next step)\b",
        (U "\u672a\u5b8c\u6210"),
        (U "\u8fd8\u6ca1"),
        (U "\u8fd8\u7f3a"),
        (U "\u5f85\u63a5\u7ebf"),
        (U "\u672a\u56fa\u5316"),
        (U "\u4e0b\u4e00\u6b65"),
        (U "\u5361\u4f4f"),
        (U "\u6ca1\u6709\u5b8c"),
        (U "\u4e0d\u80fd"),
        (U "\u5931\u8d25")
    )
    $completionEvidencePatterns = @(
        "(?i)\b(passed|tests passed|pushed|origin/main|worktree clean|committed|verified)\b",
        (U "\u5df2\u63d0\u4ea4"),
        (U "\u5df2\u63a8\u9001"),
        (U "\u63a8\u5230\u8fdc\u7aef"),
        (U "\u9a8c\u8bc1\u901a\u8fc7"),
        (U "\u5de5\u4f5c\u533a\u5e72\u51c0"),
        (U "\u5df2\u843d\u5730"),
        (U "\u5df2\u4fee")
    )

    $sideAllowsStop = (
        ($SelectedObject.decision -eq "allow_stop") -or
        (($null -eq $SelectedObject.continue) -and ($null -eq $SelectedObject.decision))
    )
    $explicitStop = Test-AnyPattern -Text $userText -Patterns $explicitStopPatterns
    $executionIntent = Test-AnyPattern -Text $userText -Patterns $executionPatterns
    $dialogueOnly = (Test-AnyPattern -Text $userText -Patterns $dialogueOnlyPatterns) -and (-not $executionIntent)
    $assistantSaysIncomplete = Test-AnyPattern -Text $assistantText -Patterns $incompletePatterns
    $assistantHasCompletionEvidence = Test-AnyPattern -Text $assistantText -Patterns $completionEvidencePatterns
    $closureBundle = Get-ClosureEvidenceBundleStatus -UserText $userText -AssistantText $assistantText
    $closureBundleMissing = ($closureBundle.closure_intent -eq $true) -and ($closureBundle.complete -ne $true)
    $required = (
        $sideAllowsStop -and
        (-not $explicitStop) -and
        (-not $dialogueOnly) -and
        ($assistantSaysIncomplete -or $closureBundleMissing -or ($executionIntent -and (-not $assistantHasCompletionEvidence)))
    )

    return [ordered]@{
        required = $required
        side_allows_stop = $sideAllowsStop
        explicit_user_stop = $explicitStop
        dialogue_only = $dialogueOnly
        execution_intent = $executionIntent
        assistant_says_incomplete = $assistantSaysIncomplete
        assistant_has_completion_evidence = $assistantHasCompletionEvidence
        closure_evidence_bundle = $closureBundle
        named_blocker = if ($closureBundleMissing) { "CLOSURE_EVIDENCE_BUNDLE_MISSING_OR_INCOMPLETE" } else { "" }
        user_text_sha256 = if ($userText) {
            $sha = [System.Security.Cryptography.SHA256]::Create()
            ([System.BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($userText))).Replace("-", "").ToLowerInvariant())
        } else { "" }
        rule = "After report output, if backend is not live but the current text task is still not productively complete, continue and re-anchor to the user's task text."
    }
}

try {
    if (Test-Path -LiteralPath $metaMinuteScript -PathType Leaf) {
        $oldRepoReadbackWrite = $env:XINAO_RUNTIME_REPO_READBACK_WRITE
        $env:XINAO_RUNTIME_REPO_READBACK_WRITE = "0"
        try {
            & $metaMinuteScript `
                -Trigger before_final_pass_report `
                -Event Stop `
                -RawEventJson $raw `
                -CurrentUserObject "Codex S Stop hook final/PASS/report surface" `
                -LatestUserDelta "Stop hook wrapper invoked; run MetaMinute before SideAudit" `
                -RepoRoot $RepoRoot `
                -RuntimeRoot $RuntimeRoot `
                -Quiet | Out-Null
        }
        finally {
            if ($null -eq $oldRepoReadbackWrite) {
                Remove-Item Env:\XINAO_RUNTIME_REPO_READBACK_WRITE -ErrorAction SilentlyContinue
            }
            else {
                $env:XINAO_RUNTIME_REPO_READBACK_WRITE = $oldRepoReadbackWrite
            }
        }
    }

    if (-not (Test-Path -LiteralPath $sideAuditScript -PathType Leaf)) {
        throw "SideAudit script missing: $sideAuditScript"
    }

    if ($SideAuditJsonOverride) {
        $sideOutput = @($SideAuditJsonOverride)
    }
    else {
        $oldRepoReadbackWrite = $env:XINAO_RUNTIME_REPO_READBACK_WRITE
        $env:XINAO_RUNTIME_REPO_READBACK_WRITE = "0"
        try {
            $sideOutput = @($raw | powershell -NoProfile -ExecutionPolicy Bypass -File $sideAuditScript -RuntimeRoot $RuntimeRoot 2>&1)
            $sideExit = $LASTEXITCODE
            if ($sideExit -ne 0) {
                throw "SideAudit exited with code $sideExit; output=$($sideOutput -join "`n")"
            }
        }
        finally {
            if ($null -eq $oldRepoReadbackWrite) {
                Remove-Item Env:\XINAO_RUNTIME_REPO_READBACK_WRITE -ErrorAction SilentlyContinue
            }
            else {
                $env:XINAO_RUNTIME_REPO_READBACK_WRITE = $oldRepoReadbackWrite
            }
        }
    }

    $jsonLine = @($sideOutput | Where-Object { ([string]$_).TrimStart().StartsWith("{") } | Select-Object -Last 1)
    if ($jsonLine.Count -eq 0) {
        throw "SideAudit did not emit hook JSON; output=$($sideOutput -join "`n")"
    }

    $selected = [string]$jsonLine[-1]
    $selectedObject = $selected | ConvertFrom-Json
    if ($selectedObject.continue -eq $true) {
        $selectedObject | Add-Member -Force -NotePropertyName suppressOutput -NotePropertyValue $false
        if (-not $selectedObject.reason) {
            $selectedObject | Add-Member -Force -NotePropertyName reason -NotePropertyValue "Stop hook checked after report output: backend/live-watch evidence still requires foreground mirror watch."
        }
        $selectedObject | Add-Member -Force -NotePropertyName visibleHookCheck -NotePropertyValue "Stop hook checked after report output; continue foreground mirror watch."
        $selected = $selectedObject | ConvertTo-Json -Depth 8 -Compress
    }
    $textTaskReanchor = Get-TextTaskReanchorDecision -SelectedObject $selectedObject
    if ($textTaskReanchor.required -eq $true) {
        $closureBundleMissing = ($textTaskReanchor.closure_evidence_bundle.closure_intent -eq $true) -and ($textTaskReanchor.closure_evidence_bundle.complete -ne $true)
        $selectedObject = [ordered]@{
            continue = $true
            suppressOutput = $false
            reason = if ($closureBundleMissing) { "closure_evidence_bundle_missing_or_incomplete" } else { "post_report_text_task_reanchor_required" }
            visibleHookCheck = if ($closureBundleMissing) {
                "Stop hook checked after report output; closure-shaped wording is missing the required closure evidence bundle. Continue binding/verifying evidence instead of final."
            } else {
                "Stop hook checked after report output; backend is not live, but the current text task is not productively complete. Re-anchor to the user's task text and continue decomposition/execution/verification."
            }
            closureEvidenceBundle = $textTaskReanchor.closure_evidence_bundle
        }
        $selected = $selectedObject | ConvertTo-Json -Depth 8 -Compress
    }
    Write-StopHookState -Status "stop_hook_wrapper_ready" -SelectedOutput $selected -RawOutput $sideOutput -ErrorText "" -TextTaskReanchor $textTaskReanchor
    Write-Output $selected
    exit 0
}
catch {
    $fallback = (@{
        decision = "allow_stop"
        suppressOutput = $true
        reason = "Codex S Stop hook wrapper failed open: $($_.Exception.Message)"
    } | ConvertTo-Json -Compress)
    Write-StopHookState -Status "stop_hook_wrapper_fail_open" -SelectedOutput $fallback -RawOutput @() -ErrorText $_.Exception.Message -TextTaskReanchor $null
    Write-Output $fallback
    exit 0
}
