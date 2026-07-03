[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$ownerPath = Join-Path $RuntimeRoot "state\current_task_owner\latest.json"
$hotpathPath = Join-Path $RuntimeRoot "state\segment_audit_hotpath\latest.json"
$owner = Read-Json $ownerPath
$hotpath = Read-Json $hotpathPath

$taskId = [string]($owner.task_id)
$pending = @()

function Test-PendingGate($gate, [string]$tid) {
    if (-not $gate) { return $false }
    $ready = ($gate.segment_audit_ready -eq $true)
    $waiting = ($gate.workflow_waiting_grok_segment_audit -eq $true) -or
        ([string]$gate.status -match "WAITING_GROK") -or
        ([string]$gate.segment_audit_status -match "WAITING_GROK")
    $verdict = [string]($gate.grok_verdict)
    if (-not $verdict) { $verdict = [string]($gate.verdict) }
    $hasVerdict = $verdict -in @("pass", "fail", "hold")
    return ($ready -and $waiting -and -not $hasVerdict)
}

if ($taskId -and (Test-Path -LiteralPath (Join-Path $RuntimeRoot "state\grok_l1_l2_segment_gate\tasks\$taskId.json"))) {
    $gate = Read-Json (Join-Path $RuntimeRoot "state\grok_l1_l2_segment_gate\tasks\$taskId.json")
    if (Test-PendingGate $gate $taskId) {
        $pending += [ordered]@{
            task_id = $taskId
            segment_id = [string]($gate.segment_id)
            status = [string]($gate.status)
            segment_audit_status = [string]($gate.segment_audit_status)
            workflow_id = [string]($owner.workflow_id)
            workflow_open = ($owner.workflow_open -eq $true)
            source = "grok_l1_l2_segment_gate.tasks"
            next_human_action_cn = "Codex 已交审；Grok 代理自动审查中（task=$taskId）"
        }
    }
}

if ($hotpath -and $hotpath.task_id -and (Test-PendingGate $hotpath.current_task_owner $hotpath.task_id)) {
    $hid = [string]$hotpath.task_id
    if (-not ($pending | Where-Object { $_.task_id -eq $hid })) {
        $pending += [ordered]@{
            task_id = $hid
            segment_id = "phase0_phase1"
            status = "WAITING_GROK_SEGMENT_AUDIT"
            segment_audit_status = [string]($hotpath.grok_gate.segment_audit_status)
            workflow_id = [string]($hotpath.workflow.workflow_id)
            workflow_open = ($hotpath.workflow.workflow_open -eq $true)
            source = "segment_audit_hotpath"
            panel_blocked_line_cn = [string]($hotpath.panel.panel_lines_cn.blocked_line_cn)
            next_human_action_cn = [string]($hotpath.panel.panel_lines_cn.next_human_action_cn)
        }
    }
}

@{
    schema_version = "xinao.grok_segment_audit_pending.v1"
    generated_at = (Get-Date).ToString("o")
    runtime_root = $RuntimeRoot
    pending_count = $pending.Count
    pending = @($pending)
    owner_task_id = $taskId
    owner_segment_audit_ready = ($owner.segment_audit_ready -eq $true)
    owner_waiting_grok = ($owner.workflow_waiting_grok_segment_audit -eq $true)
    grok_must_announce_on_session = ($pending.Count -gt 0)
    user_switch_phrase_cn = "审查"
    not_user_completion = $true
    not_grok_verdict = $true
} | ConvertTo-Json -Depth 8