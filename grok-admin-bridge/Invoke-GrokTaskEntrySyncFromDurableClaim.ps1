#Requires -Version 5.1
<#
.SYNOPSIS
  P0-S3 漂移修复：以 durable_claim 权威记录同步 task_entry/latest.json（workflow/run/claim_state）。
  不宣布 P0 闭合；仅消除 latest ↔ durable_claim 同构遗留。
#>
param(
    [string]$ConfigPath = "",
    [string]$TaskId = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false

$bridge = $PSScriptRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $bridge "bridge.config.json" }
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $ConfigPath
$stateRoot = Join-Path $runtime "state\task_entry"
$claimDir = Join-Path $stateRoot "durable_claim"
$latestPath = Join-Path $stateRoot "latest.json"
$claimLatest = Join-Path $claimDir "latest.json"

if (-not (Test-Path -LiteralPath $claimLatest)) {
    throw "No durable_claim/latest.json; run Invoke-GrokTaskEntryClaimDurable first."
}

$claimMeta = Get-Content -LiteralPath $claimLatest -Raw -Encoding UTF8 | ConvertFrom-Json
$resolvedTaskId = if ($TaskId) { $TaskId } else { [string]$claimMeta.intake_task_id }
if (-not $resolvedTaskId) { throw "durable_claim missing intake_task_id" }

$claimRecordPath = Join-Path $claimDir "claim_$resolvedTaskId.json"
$sourcePath = $claimRecordPath
if (-not (Test-Path -LiteralPath $sourcePath)) {
    $intakePath = Join-Path $stateRoot "intake\$resolvedTaskId.json"
    if (Test-Path -LiteralPath $intakePath) { $sourcePath = $intakePath }
    else { throw "No claim record or intake for task_id=$resolvedTaskId" }
}

$record = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8 | ConvertFrom-Json
$recordHash = [ordered]@{}
foreach ($p in $record.PSObject.Properties) { $recordHash[$p.Name] = $p.Value }

# Merge authoritative durable fields from claim meta (container paths may differ)
$recordHash["claim_state"] = [string]$claimMeta.claim_state
if ($claimMeta.durable_evidence_ref) { $recordHash["durable_evidence_ref"] = [string]$claimMeta.durable_evidence_ref }
if ($claimMeta.temporal_workflow_id) { $recordHash["temporal_workflow_id"] = [string]$claimMeta.temporal_workflow_id }
if ($claimMeta.temporal_workflow_run_id) { $recordHash["temporal_workflow_run_id"] = [string]$claimMeta.temporal_workflow_run_id }
if ($claimMeta.work_package_ref) { $recordHash["work_package_ref"] = [string]$claimMeta.work_package_ref }
if ($claimMeta.generated_at) { $recordHash["durable_claim_at"] = [string]$claimMeta.generated_at }

# Refresh temporal probe for honest readback
$temporalOk = $false
try {
    $temporalOk = (Test-NetConnection -ComputerName 127.0.0.1 -Port 7233 -WarningAction SilentlyContinue).TcpTestSucceeded
} catch { }
$recordHash["temporal_7233_ok"] = $temporalOk
if ($temporalOk -and $recordHash["named_blockers"]) {
    $blockers = @($recordHash["named_blockers"] | Where-Object { $_ -and $_ -ne "TEMPORAL_7233_DOWN" })
    $recordHash["named_blockers"] = $blockers
}

$recordHash["readback_three_cn"] = @(
    "①入口读到：$($recordHash.entry_kind) / $($recordHash.intent_one_liner)",
    "②durable认领证据：$(if ($recordHash.durable_evidence_ref) { $recordHash.durable_evidence_ref } else { '无（' + $recordHash.claim_state + '）' })",
    "③blocker：$(if ($recordHash.named_blockers -and @($recordHash.named_blockers).Count) { ($recordHash.named_blockers -join '；') } else { '无' })"
)
$recordHash["completion_claim_allowed"] = $false
$recordHash["not_user_completion"] = $true
$recordHash["not_frontend_plan"] = $true
$recordHash["synced_from_durable_claim_at"] = (Get-Date).ToString("o")

$json = ($recordHash | ConvertTo-Json -Depth 12)
[System.IO.File]::WriteAllText($latestPath, $json, $utf8)

$readbackZh = Join-Path $runtime "readback\zh\task_entry_latest.md"
$three = ($recordHash.readback_three_cn | ForEach-Object { "- $_" }) -join "`n"
$md = @(
    "# task_entry readback (synced from durable_claim)",
    "",
    "task_id: **$resolvedTaskId**",
    "claim_state: **$($recordHash.claim_state)**",
    "workflow_id: **$($recordHash.temporal_workflow_id)**",
    "run_id: **$($recordHash.temporal_workflow_run_id)**",
    "",
    "## three_lines",
    $three,
    "",
    "## honest",
    "- synced from durable_claim; SelfRotate intake_staged does not replace claimed latest",
    ("- Temporal:7233=" + $(if ($temporalOk) { "up" } else { "down" }))
) -join "`n"
[System.IO.File]::WriteAllText($readbackZh, $md, $utf8)

$result = [ordered]@{
    schema_version = "xinao.task_entry.sync_from_durable_claim.v1"
    generated_at   = (Get-Date).ToString("o")
    task_id        = $resolvedTaskId
    claim_state    = $recordHash.claim_state
    temporal_workflow_id = $recordHash.temporal_workflow_id
    temporal_workflow_run_id = $recordHash.temporal_workflow_run_id
    source_path    = $sourcePath
    latest_path    = $latestPath
    completion_claim_allowed = $false
}
$syncDir = Join-Path $stateRoot "sync_from_durable_claim"
New-Item -ItemType Directory -Force -Path $syncDir | Out-Null
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $syncDir "latest.json") -Encoding UTF8

if (-not $Quiet) { $result | ConvertTo-Json -Depth 6 }