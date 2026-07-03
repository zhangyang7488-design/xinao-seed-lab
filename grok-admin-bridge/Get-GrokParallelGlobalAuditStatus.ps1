[CmdletBinding()]
param(
    [string]$TicketId = "",
    [string]$RuntimeRoot = "D:\XINAO_CLEAN_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Read-JsonFile {
    param([string]$Path, $Default = $null)
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    try {
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $raw = [System.IO.File]::ReadAllText($Path, $utf8)
        return ($raw | ConvertFrom-Json)
    }
    catch { return $Default }
}

$stateDir = Join-Path $RuntimeRoot "state\grok_parallel_global_audit"
$manifestPath = if ($TicketId) {
    Join-Path $stateDir "$TicketId.json"
} else {
    Join-Path $stateDir "latest.json"
}

$manifest = Read-JsonFile -Path $manifestPath
if (-not $manifest) {
    [ordered]@{
        schema_version = "xinao.grok_parallel_global_audit.status.v1"
        status = "no_dispatch_yet"
        hint_cn = "先运行 Invoke-GrokParallelGlobalAudit.ps1 喊 B/C/DP"
    } | ConvertTo-Json -Depth 8
    exit 0
}

$artifactDir = [string]$manifest.artifact_dir
$reports = [System.Collections.Generic.List[object]]::new()
$jobs = @()

foreach ($d in @($manifest.dispatches)) {
    $item = [ordered]@{
        auditor_code = $d.auditor_code
        role = $d.role
        label_cn = $d.label_cn
        dispatch_status = $d.status
    }

    if ($d.observe_state_path) {
        $obs = Read-JsonFile -Path ([string]$d.observe_state_path)
        if ($obs) {
            $item.observe_status = [string]$obs.status
            $item.observe_jsonl_line_count = $obs.jsonl_line_count
            $item.observe_pid = $obs.pid
            $item.observe_token_usage = $obs.token_usage
            $item.observe_updated_at = [string]$obs.updated_at
            $item.observe_last_command = [string]$obs.last_command
        }
    }
    if ($d.process_id) {
        $proc = Get-Process -Id ([int]$d.process_id) -ErrorAction SilentlyContinue
        $item.process_alive = [bool]$proc
    }
    if ($d.job_id) {
        $job = Get-Job -Id $d.job_id -ErrorAction SilentlyContinue
        if ($job) {
            $item.job_state = $job.State
            if ($job.State -in @("Completed", "Failed")) {
                $jobs += $job
            }
        }
    }

    $expected = if ($d.report_path) { [string]$d.report_path } else { [string]$d.report_path_expected }
    if ($expected -and (Test-Path -LiteralPath $expected)) {
        $report = Read-JsonFile -Path $expected
        $item.report_path = $expected
        $item.report_decision = if ($report.decision) { $report.decision } else { "unknown" }
        $item.report_summary = if ($report.summary) { $report.summary.Substring(0, [Math]::Min(400, $report.summary.Length)) } else { "" }
        $item.report_ready = $true
    }
    else {
        $role = [string]$d.role
        $fallback = Join-Path $artifactDir "$role.report.json"
        if (Test-Path -LiteralPath $fallback) {
            $report = Read-JsonFile -Path $fallback
            $item.report_path = $fallback
            $item.report_decision = if ($report.decision) { $report.decision } else { "unknown" }
            $item.report_summary = if ($report.summary) { $report.summary.Substring(0, [Math]::Min(400, $report.summary.Length)) } else { "" }
            $item.report_ready = $true
        }
        else {
            $item.report_ready = $false
        }
    }

    $reports.Add([pscustomobject]$item)
}

if ($jobs.Count -gt 0) {
    Receive-Job -Job $jobs -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $jobs -Force -ErrorAction SilentlyContinue
}

$readyCount = @($reports | Where-Object { $_.report_ready }).Count
$total = $reports.Count

$status = [ordered]@{
    schema_version = "xinao.grok_parallel_global_audit.status.v1"
    generated_at = (Get-Date).ToString("o")
    ticket_id = $manifest.ticket_id
    manifest_path = $manifestPath
    artifact_dir = $artifactDir
    observe_root = [string]$manifest.observe_root
    local_observe_hint = "Get-GrokLocalObserve.ps1 -TicketId $($manifest.ticket_id)"
    does_not_block_codex_a = $true
    dispatch_status = $manifest.status
    reports_ready = "$readyCount/$total"
    reports = @($reports)
    grok_translate_hint_cn = "把 report_summary 和 dispatch_status 翻成中文人话四段式；不得把 JSON 直接倒给用户"
    named_blockers = @($manifest.named_blockers)
}

$status | ConvertTo-Json -Depth 10