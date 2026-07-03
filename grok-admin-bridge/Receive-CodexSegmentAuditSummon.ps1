[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME",
    [string]$BridgeRoot = "",
    [string]$TaskId = "",
    [switch]$SkipAutoAudit
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

if (-not $BridgeRoot) {
    $BridgeRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$summonLatest = Join-Path $RuntimeRoot "state\codex_to_grok_segment_audit_summon\latest.json"
$summon = Read-Json $summonLatest
if ($TaskId) {
    $taskPath = Join-Path $RuntimeRoot "state\codex_to_grok_segment_audit_summon\tasks\$TaskId.json"
    $taskSummon = Read-Json $taskPath
    if ($taskSummon) { $summon = $taskSummon }
}

if (-not $summon) {
    $pending = & (Join-Path $BridgeRoot "Get-GrokSegmentAuditPending.ps1") -RuntimeRoot $RuntimeRoot | ConvertFrom-Json
    if ($pending.pending_count -gt 0) {
        $p0 = $pending.pending[0]
        $summon = [pscustomobject]@{
            schema_version = "xinao.codex_to_grok_segment_audit_summon.fallback_from_pending.v1"
            task_id = $p0.task_id
            segment_audit_ready = $true
            status = "WAITING_GROK_SEGMENT_AUDIT"
            source = "fallback_grok_pending_probe"
            generated_at = (Get-Date).ToString("o")
        }
    }
}

if (-not $summon) {
    @{
        schema_version = "xinao.grok_receive_codex_segment_audit_summon.v1"
        status = "no_summon_pending"
        generated_at = (Get-Date).ToString("o")
        grok_action_cn = "无 Codex 段审召唤；等待 segment_audit_ready + leg1 双投递"
        not_user_completion = $true
    } | ConvertTo-Json -Depth 6
    exit 0
}

$tid = [string]$summon.task_id
$inboxDir = Join-Path $BridgeRoot "inbox"
New-Item -ItemType Directory -Force -Path $inboxDir | Out-Null
$visibleMd = Join-Path $inboxDir "segment_audit_summon_visible.md"
$short = if ($tid.Length -gt 12) { $tid.Substring(0, 12) } else { $tid }
$visibleText = @"
【Codex→Grok 段审召唤 · 双投递可见腿】
task_id: $tid
状态: Codex 已交审，Grok 代理自动审查
下一跳: Grok 采证据出判决 → 先双投递 verdict 回 Codex → 再对用户中文说明
非完成 · 非 Codex 代审
生成: $((Get-Date).ToString("o"))
"@
Set-Content -LiteralPath $visibleMd -Value $visibleText -Encoding UTF8

$receiveOut = Join-Path $BridgeRoot "state\codex_segment_audit_summon_received\latest.json"
$receiveDir = Split-Path $receiveOut -Parent
New-Item -ItemType Directory -Force -Path $receiveDir | Out-Null

$auditEvidenceRef = ""
if (-not $SkipAutoAudit) {
    try {
        $auditScript = Join-Path $BridgeRoot "Invoke-GrokGlobalHumanAudit.ps1"
        if (Test-Path -LiteralPath $auditScript) {
            $auditOut = Join-Path $receiveDir "audit_evidence_$short.json"
            & $auditScript | Out-File -LiteralPath $auditOut -Encoding UTF8
            $auditEvidenceRef = $auditOut
        }
    }
    catch {
        $auditEvidenceRef = "audit_collect_failed: $($_.Exception.Message)"
    }
}

$payload = [ordered]@{
    schema_version = "xinao.grok_receive_codex_segment_audit_summon.v1"
    sentinel = "SENTINEL:GROK_SEGMENT_AUDIT_SUMMON_RECEIVED"
    generated_at = (Get-Date).ToString("o")
    status = "summon_received_start_audit"
    task_id = $tid
    summon_ref = $summonLatest
    visible_inbox = $visibleMd
    audit_evidence_ref = $auditEvidenceRef
    grok_discipline_cn = "收到交审后：Grok 自动采证据出判决 → 先 Send-GrokIntentToCodexA 双投递 verdict 回 Codex → 再对用户用中文说明情况"
    leg2_then_user_explain_order_cn = "先 Codex 双投递 verdict，再对用户中文解释；不可颠倒"
    next_script = "Send-GrokIntentToCodexA.ps1"
    leg2_required = "dual_visible_and_backend"
    not_user_completion = $true
    not_auto_verdict_without_user_proxy = $true
}
$json = $payload | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $receiveOut -Value $json -Encoding UTF8
$json
exit 0