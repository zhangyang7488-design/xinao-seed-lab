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

$additionalContext = "Codex S UserPromptSubmit intake: classify human_dialogue / diagnosis / execution / watch first. Dialogue and read-only diagnosis do not start 333 or create worker evidence. Execution enters RootIntentLoop / S Default Dynamic Loop. Watch means foreground mirror watch. Reports may be output, but the post-report Stop hook checks backend/live-watch evidence; if backend/backlog/source gap/next frontier/blocker remains active, foreground continues mirror polling instead of final. Incomplete text anchors next dispatch/repair/bind, not final report. Non-trivial engineering gaps require mature external discovery or delegated Qwen/DP/subagent discovery. Stop/final/report/PASS/readback/latest cannot claim completion. Engineering changes default-harden into 333 or state why not."

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
    human_dialogue_or_diagnosis_rule = "answer/analyze directly; do not start 333 and do not manufacture worker evidence"
    execution_rule = "non-trivial execution enters RootIntentLoop / S Default Dynamic Loop"
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
