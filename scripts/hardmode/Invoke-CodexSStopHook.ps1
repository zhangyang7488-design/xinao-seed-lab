[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
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
        [string]$ErrorText
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

try {
    if (Test-Path -LiteralPath $metaMinuteScript -PathType Leaf) {
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

    if (-not (Test-Path -LiteralPath $sideAuditScript -PathType Leaf)) {
        throw "SideAudit script missing: $sideAuditScript"
    }

    $sideOutput = @($raw | powershell -NoProfile -ExecutionPolicy Bypass -File $sideAuditScript -RuntimeRoot $RuntimeRoot 2>&1)
    $sideExit = $LASTEXITCODE
    if ($sideExit -ne 0) {
        throw "SideAudit exited with code $sideExit; output=$($sideOutput -join "`n")"
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
    Write-StopHookState -Status "stop_hook_wrapper_ready" -SelectedOutput $selected -RawOutput $sideOutput -ErrorText ""
    Write-Output $selected
    exit 0
}
catch {
    $fallback = (@{
        decision = "allow_stop"
        suppressOutput = $true
        reason = "Codex S Stop hook wrapper failed open: $($_.Exception.Message)"
    } | ConvertTo-Json -Compress)
    Write-StopHookState -Status "stop_hook_wrapper_fail_open" -SelectedOutput $fallback -RawOutput @() -ErrorText $_.Exception.Message
    Write-Output $fallback
    exit 0
}
