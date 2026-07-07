[CmdletBinding()]
param(
    [string]$Event = "UserPromptSubmit",
    [string]$RawEventJson = "",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function U {
    param([string]$Value)
    return [regex]::Unescape($Value)
}

if (-not $RawEventJson) {
    try {
        $stdinReader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
        $RawEventJson = $stdinReader.ReadToEnd()
    }
    catch {
        $RawEventJson = ""
    }
}

$eventObject = $null
if ($RawEventJson.Trim()) {
    try { $eventObject = $RawEventJson | ConvertFrom-Json } catch { $eventObject = $null }
}

$latestUserDelta = "classify user delta before action"
if ($eventObject) {
    if ($eventObject.hook_event_name) {
        $Event = [string]$eventObject.hook_event_name
    }
    if ($eventObject.user_prompt) {
        $latestUserDelta = [string]$eventObject.user_prompt
    }
    elseif ($eventObject.last_user_message) {
        $latestUserDelta = [string]$eventObject.last_user_message
    }
}

$stateDir = Join-Path $RuntimeRoot "state\codex_s_user_prompt_submit_hook"
$latestPath = Join-Path $stateDir "latest.json"
$metaMinuteScript = Join-Path $RepoRoot "scripts\hardmode\Invoke-CodexSMetaMinutePreflight.ps1"
$preludeLatest = Join-Path $RuntimeRoot "state\codex_s_global_self_prelude\latest.json"
$preludePrompt = Join-Path $RuntimeRoot "state\codex_s_global_self_prelude\latest.prompt.md"
$intentDecodeIndex = Join-Path $RuntimeRoot "state\codex_s_intent_decode_index\latest.json"
$tokenGateScript = Join-Path $RepoRoot "services\agent_runtime\codex_s_token_budget_gate.py"
$tokenGateLatest = Join-Path $RuntimeRoot "state\codex_s_token_budget_gate\latest.json"
$watchSourceRef = ""
$watchLegacySourceRef = ""
$watchMeaning = "foreground mirror watch: keep polling/kicking/resuming while backend, backlog, source gap, next frontier, or blocker remains active; do not final on status report."
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$metaminuteStatus = "metaminute_not_invoked"
$metaminuteError = ""
$metaminuteOutput = @()
try {
    $metaminuteOutput = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $metaMinuteScript `
        -Trigger user_prompt_submit `
        -Event $Event `
        -CurrentUserObject "Codex S UserPromptSubmit hook" `
        -LatestUserDelta $latestUserDelta `
        -RepoRoot $RepoRoot `
        -RuntimeRoot $RuntimeRoot 2>&1)
    if ($LASTEXITCODE -eq 0) {
        $metaminuteStatus = "metaminute_ready"
    }
    else {
        $metaminuteStatus = "metaminute_degraded"
        $metaminuteError = ($metaminuteOutput -join "`n")
    }
}
catch {
    $metaminuteStatus = "metaminute_degraded"
    $metaminuteError = $_.Exception.Message
}

$closureContext = " Execution closure/full closeout terms are execution_closure inside execution. Before closure-shaped final wording, provide the closure evidence bundle: default mainline binding, runtime worker load, verification, evidence/readback, git clean status, commit hash, push target, 333/mainline state, and remaining/named-blocker state."
$additionalContext = "Codex S UserPromptSubmit intake: classify human_dialogue / diagnosis / execution / watch first. Dialogue and read-only diagnosis do not start 333 or create worker evidence. Execution enters RootIntentLoop / S Default Dynamic Loop. Watch means foreground mirror watch. Reports may be output, but the post-report Stop hook checks backend/live-watch evidence; if backend/backlog/source gap/next frontier/blocker remains active, foreground continues mirror polling instead of final. If backend is not live but the current text task is not productively complete, re-anchor to the user's task text and continue decomposition/execution/verification. Incomplete text anchors next dispatch/repair/bind, not final report. Non-trivial engineering gaps require mature external discovery or delegated Qwen/DP/subagent discovery. Stop/final/report/PASS/readback/latest cannot claim completion. Engineering changes default-harden into 333 or state why not.$closureContext"

try {
    if (Test-Path -LiteralPath $preludeLatest -PathType Leaf) {
        $prelude = Get-Content -LiteralPath $preludeLatest -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($prelude.user_prompt_submit_additional_context) {
            $additionalContext = [string]$prelude.user_prompt_submit_additional_context
        }
        if ($prelude.foreground_mirror_watch) {
            if ($prelude.foreground_mirror_watch.source_ref) {
                $watchSourceRef = [string]$prelude.foreground_mirror_watch.source_ref
            }
            if ($prelude.foreground_mirror_watch.legacy_source_ref) {
                $watchLegacySourceRef = [string]$prelude.foreground_mirror_watch.legacy_source_ref
            }
            if ($prelude.foreground_mirror_watch.meaning_cn) {
                $watchMeaning = [string]$prelude.foreground_mirror_watch.meaning_cn
            }
        }
    }
}
catch {
    # Fail open: keep the static context.
}
if ($additionalContext -notmatch "closure evidence bundle") {
    $additionalContext = "$additionalContext$closureContext"
}

$tokenGateStatus = "token_gate_not_invoked"
$tokenGateError = ""
$tokenGateOutput = @()
$tokenGateContext = ""
$tokenGateDecision = $null
try {
    if (Test-Path -LiteralPath $tokenGateScript -PathType Leaf) {
        $python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            $python = "python"
        }
        $oldPythonPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
            $tokenGateOutput = @(& $python $tokenGateScript `
                --raw-event-json $RawEventJson `
                --repo-root $RepoRoot `
                --runtime-root $RuntimeRoot 2>&1)
        }
        finally {
            $env:PYTHONPATH = $oldPythonPath
        }
        if ($LASTEXITCODE -eq 0) {
            $tokenGateStatus = "token_gate_ready"
            try {
                $tokenGatePayload = ($tokenGateOutput -join "`n") | ConvertFrom-Json
                if ($tokenGatePayload.hook_additional_context) {
                    $tokenGateContext = [string]$tokenGatePayload.hook_additional_context
                    $additionalContext = "$additionalContext $tokenGateContext"
                }
                if ($tokenGatePayload.decision) {
                    $tokenGateDecision = $tokenGatePayload.decision
                }
            }
            catch {
                $tokenGateStatus = "token_gate_ready_parse_degraded"
                $tokenGateError = $_.Exception.Message
            }
        }
        else {
            $tokenGateStatus = "token_gate_degraded"
            $tokenGateError = ($tokenGateOutput -join "`n")
        }
    }
    else {
        $tokenGateStatus = "token_gate_missing"
        $tokenGateError = "missing script: $tokenGateScript"
    }
}
catch {
    $tokenGateStatus = "token_gate_degraded"
    $tokenGateError = $_.Exception.Message
}

$payload = [ordered]@{
    schema_version = "xinao.codex_s.user_prompt_submit_hook.v1"
    sentinel = "SENTINEL:XINAO_CODEX_S_USER_PROMPT_SUBMIT_HOOK_READY"
    status = "user_prompt_submit_hook_ready"
    event = $Event
    generated_at = (Get-Date).ToString("o")
    scope = "S-scoped UserPromptSubmit hook"
    codex_home_hooks_ref = "C:\Users\xx363\.codex-seed-cortex\hooks.json#/hooks/UserPromptSubmit"
    repo_root = $RepoRoot
    runtime_root = $RuntimeRoot
    latest_user_delta_sha256 = if ($latestUserDelta) {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($latestUserDelta)
        ([System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes))).Replace("-", "")
    } else { "" }
    classification_classes = @("human_dialogue", "diagnosis", "execution", "watch")
    execution_subclasses = @("execution_closure")
    execution_closure_keywords = @(
        (U "\u5b8c\u6574\u6536\u53e3"),
        (U "\u5168\u90e8\u6536\u53e3"),
        (U "\u6536\u53e3\u57fa\u7840\u6807\u51c6"),
        (U "\u9ed8\u8ba4\u4e3b\u8def\u7ed1\u5b9a"),
        (U "\u8fd0\u884c\u6001\u52a0\u8f7d"),
        (U "\u8bc1\u636e/readback"),
        (U "\u63d0\u4ea4\u63a8\u9001\u5408\u5e76")
    )
    closure_evidence_bundle_required_fields = @(
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
    human_dialogue_or_diagnosis_rule = "answer/analyze directly; do not start 333 and do not manufacture worker evidence"
    execution_rule = "non-trivial execution enters RootIntentLoop / S Default Dynamic Loop"
    execution_closure_rule = "closure-shaped final wording is blocked until the closure evidence bundle is present; otherwise continue bind/verify/evidence/readback/commit/push work"
    watch_rule = "foreground mirror watch: poll/kick/resume while 333 backend/backlog/source gap/next frontier/blocker remains active"
    stop_final_report_pass_readback_latest_cannot_complete = $true
    mandatory_external_mature_search = $true
    mandatory_default_mainline_hardening = $true
    incomplete_text_anchors_next_dispatch = $true
    incomplete_text_rule = "text/worker/readback says unfinished/missing/next step => continue dispatch/repair/bind unless user asked discussion-only, explicit stop, or hard blocker requiring user decision"
    default_hardening_requires_no_extra_user_reminder = $true
    if_not_hardened_required_fields = @(
        "default_mainline_hardened=false",
        "reason_not_hardened",
        "missing_binding",
        "adoption_state",
        "next_machine_action"
    )
    foreground_mirror_watch = [ordered]@{
        source_ref = $watchSourceRef
        source_ref_exists = (Test-Path -LiteralPath $watchSourceRef -PathType Leaf)
        legacy_source_ref = $watchLegacySourceRef
        legacy_source_ref_exists = (Test-Path -LiteralPath $watchLegacySourceRef -PathType Leaf)
        meaning_cn = $watchMeaning
        not_execution_controller = $true
        not_completion_gate = $true
    }
    metaminute = [ordered]@{
        status = $metaminuteStatus
        error = $metaminuteError
        output_tail = @($metaminuteOutput | Select-Object -Last 8 | ForEach-Object { [string]$_ })
        latest_ref = (Join-Path $RuntimeRoot "state\metaminute_preflight_reflection\latest.json")
    }
    token_budget_gate = [ordered]@{
        status = $tokenGateStatus
        error = $tokenGateError
        latest_ref = $tokenGateLatest
        route_id = if ($tokenGateDecision) { [string]$tokenGateDecision.route_id } else { "" }
        action = if ($tokenGateDecision) { [string]$tokenGateDecision.action } else { "" }
        codex_read_policy = if ($tokenGateDecision) { [string]$tokenGateDecision.codex_read_policy } else { "" }
        context = $tokenGateContext
        output_tail = @($tokenGateOutput | Select-Object -Last 8 | ForEach-Object { [string]$_ })
        not_execution_controller = $true
        not_completion_gate = $true
    }
    global_self_prelude_latest_ref = $preludeLatest
    global_self_prelude_prompt_ref = $preludePrompt
    intent_decode_index_ref = $intentDecodeIndex
    additional_context = $additionalContext
    hook_specific_output_emitted = $true
    fail_open = $true
    not_completion_gate = $true
    not_stop_condition = $true
    not_execution_controller = $true
    adoption_state = "hook_configured_in_codex_s_codex_home"
}

($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine | Set-Content -LiteralPath $latestPath -Encoding UTF8

$hookOutput = [ordered]@{
    hookSpecificOutput = [ordered]@{
        hookEventName = "UserPromptSubmit"
        additionalContext = $additionalContext
    }
}
Write-Output (($hookOutput | ConvertTo-Json -Depth 8 -Compress))
exit 0
