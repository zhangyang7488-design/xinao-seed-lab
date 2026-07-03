[CmdletBinding()]
param(
    [ValidateSet("window_start_first_hop", "after_gate_hook_deny", "before_final_pass_report", "before_new_parallel_wave")]
    [string]$Trigger = "window_start_first_hop",
    [string]$Event = "",
    [string]$RawEventJson = "",
    [string]$CurrentUserObject = "Seed Cortex S current task",
    [string]$LatestUserDelta = "restore runtime facts and choose highest-EV next machine action",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [switch]$Quiet
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

if ($eventObject) {
    if (-not $Event -and $eventObject.hook_event_name) {
        $Event = [string]$eventObject.hook_event_name
    }
    if ($eventObject.user_prompt) {
        $LatestUserDelta = [string]$eventObject.user_prompt
    }
    elseif ($eventObject.last_user_message) {
        $LatestUserDelta = [string]$eventObject.last_user_message
    }
    elseif ($eventObject.last_assistant_message -and $Trigger -eq "before_final_pass_report") {
        $LatestUserDelta = "assistant final/report/PASS surface detected before stop hook"
    }
}

$modulePath = Join-Path $RepoRoot "services\agent_runtime\metaminute_preflight_reflection.py"
$hotpathDir = Join-Path $RuntimeRoot "state\metaminute_hotpath"
$hotpathPath = Join-Path $hotpathDir "$Trigger.json"
New-Item -ItemType Directory -Force -Path $hotpathDir | Out-Null

$status = "metaminute_hotpath_ready"
$errorText = ""
$output = @()
try {
    $output = @(python $modulePath `
        --trigger $Trigger `
        --current-user-object $CurrentUserObject `
        --latest-user-delta $LatestUserDelta `
        --repo-root $RepoRoot `
        --runtime-root $RuntimeRoot 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $status = "metaminute_hotpath_degraded"
        $errorText = ($output -join "`n")
    }
}
catch {
    $status = "metaminute_hotpath_degraded"
    $errorText = $_.Exception.Message
}

$latestPath = Join-Path $RuntimeRoot "state\metaminute_preflight_reflection\latest.json"
$globalSelfPreludeLatest = Join-Path $RuntimeRoot "state\codex_s_global_self_prelude\latest.json"
$globalSelfPreludePrompt = Join-Path $RuntimeRoot "state\codex_s_global_self_prelude\latest.prompt.md"
$payload = [ordered]@{
    schema_version = "xinao.codex_s.metaminute_hotpath.v1"
    status = $status
    trigger = $Trigger
    event = $Event
    generated_at = (Get-Date).ToString("o")
    latest_ref = $latestPath
    global_self_prelude_latest_ref = $globalSelfPreludeLatest
    global_self_prelude_prompt_ref = $globalSelfPreludePrompt
    global_self_prelude_exists = (Test-Path -LiteralPath $globalSelfPreludeLatest -PathType Leaf)
    global_self_prelude_prompt_exists = (Test-Path -LiteralPath $globalSelfPreludePrompt -PathType Leaf)
    output = @($output | ForEach-Object { [string]$_ })
    error = $errorText
    fail_open = $true
    not_completion_gate = $true
    not_stop_condition = $true
    not_execution_controller = $true
    sentinel = "SENTINEL:XINAO_METAMINUTE_HOTPATH_READY"
}

($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine | Set-Content -LiteralPath $hotpathPath -Encoding UTF8

if (-not $Quiet) {
    Write-Output "metaminute_hotpath_trigger=$Trigger"
    Write-Output "metaminute_hotpath_status=$status"
    Write-Output "metaminute_latest=$latestPath"
    Write-Output "global_self_prelude_latest=$globalSelfPreludeLatest"
    Write-Output "global_self_prelude_prompt=$globalSelfPreludePrompt"
    Write-Output "metaminute_hotpath_state=$hotpathPath"
    Write-Output $payload.sentinel
}

exit 0
