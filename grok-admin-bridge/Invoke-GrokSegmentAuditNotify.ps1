[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME",
    [string]$BridgeRoot = "",
    [switch]$Quiet,
    [switch]$DesktopToast
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if (-not $BridgeRoot) {
    $BridgeRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
}

$pendingScript = Join-Path $BridgeRoot "Get-GrokSegmentAuditPending.ps1"
$pendingRaw = & $pendingScript -RuntimeRoot $RuntimeRoot
$pending = $pendingRaw | ConvertFrom-Json

$notifyDir = Join-Path $RuntimeRoot "state\grok_segment_audit_notify"
$bridgeNotifyDir = Join-Path $BridgeRoot "state\grok_segment_audit_notify"
foreach ($dir in @($notifyDir, $bridgeNotifyDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$lines = @()
foreach ($item in @($pending.pending)) {
    $tid = [string]$item.task_id
    $short = if ($tid.Length -gt 12) { $tid.Substring(0, 12) } else { $tid }
    $lines += "段审就绪 task=$short | Codex已交审 | Grok代理自动审查中"
}

$payload = [ordered]@{
    schema_version = "xinao.grok_segment_audit_notify.v1"
    generated_at = (Get-Date).ToString("o")
    sentinel = "SENTINEL:GROK_SEGMENT_AUDIT_NOTIFY_V1"
    status = if ($pending.pending_count -gt 0) { "segment_audit_pending_grok_auto_audit" } else { "no_pending_segment_audit" }
    pending_count = [int]$pending.pending_count
    pending = $pending.pending
    announce_cn = if ($lines.Count -gt 0) { ($lines -join "`n") } else { "" }
    next_human_action_cn = if ($pending.pending_count -gt 0) { "Grok 代理自动审查中" } else { "" }
    grok_session_discipline_cn = "Codex 交审后 Grok 自动 Receive+审查；Grok 是用户唯一段审代理"
    codex_can_push_grok_chat_on_segment_complete = $true
    user_says_review_required = $false
    not_user_completion = $true
    not_grok_verdict = $true
    fail_open = $true
}

$json = $payload | ConvertTo-Json -Depth 8
$runtimeOut = Join-Path $notifyDir "latest.json"
$bridgeOut = Join-Path $bridgeNotifyDir "latest.json"
Set-Content -LiteralPath $runtimeOut -Value $json -Encoding UTF8
Set-Content -LiteralPath $bridgeOut -Value $json -Encoding UTF8

if ($DesktopToast -and $pending.pending_count -gt 0) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            $payload.announce_cn,
            "XINAO 段审就绪 · 请找 Grok 说审查",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    catch {
        $payload["desktop_toast_error"] = $_.Exception.Message
    }
}

if (-not $Quiet) {
    $json
}

exit 0