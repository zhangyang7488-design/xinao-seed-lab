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

$observeRoot = Join-Path $RuntimeRoot "state\grok_local_observe"
if (-not (Test-Path -LiteralPath $observeRoot)) {
    [ordered]@{
        schema_version = "xinao.grok_local_observe.status.v1"
        status = "no_observe_yet"
        hint_cn = "先运行 Invoke-GrokParallelGlobalAudit.ps1（默认同步观测）"
    } | ConvertTo-Json -Depth 10
    exit 0
}

$ticketDir = if ($TicketId) {
    Join-Path $observeRoot $TicketId
} else {
    $latest = Read-JsonFile -Path (Join-Path $observeRoot "latest_ticket.json")
    if ($latest -and $latest.ticket_id) {
        Join-Path $observeRoot ([string]$latest.ticket_id)
    } else {
        Get-ChildItem -LiteralPath $observeRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
}

$items = @()
if ($ticketDir -and (Test-Path -LiteralPath $ticketDir)) {
    foreach ($f in Get-ChildItem -LiteralPath $ticketDir -Filter "*.observe.json" -File | Sort-Object Name) {
        $obs = Read-JsonFile -Path $f.FullName
        if ($obs) {
            $items += [ordered]@{
                path = $f.FullName
                auditor_code = $obs.auditor_code
                role = $obs.role
                status = $obs.status
                pid = $obs.pid
                jsonl_line_count = $obs.jsonl_line_count
                last_command = $obs.last_command
                last_agent_excerpt = $obs.last_agent_excerpt
                token_usage = $obs.token_usage
                exit_code = $obs.exit_code
                named_blocker = $obs.named_blocker
                updated_at = $obs.updated_at
            }
        }
    }
}

[ordered]@{
    schema_version = "xinao.grok_local_observe.status.v1"
    generated_at = (Get-Date).ToString("o")
    ticket_id = if ($TicketId) { $TicketId } elseif ($ticketDir) { Split-Path -Leaf $ticketDir } else { "" }
    observe_dir = $ticketDir
    observe_count = $items.Count
    observes = $items
    grok_hint_cn = "Grok 会话内应同步读此文件轮询；jsonl_line_count/token_usage 变化=真在跑"
} | ConvertTo-Json -Depth 10