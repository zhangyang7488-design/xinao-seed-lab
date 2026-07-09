$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_5d33_full_mature_weld_marathon.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$semThin = [ordered]@{
    task_id = [string]$h.anchor_task_id
    workflow_id = [string]$h.workflow_id
    routing_verb = [string]$h.routing_verb
    wave = "full_mature_weld_marathon"
    handoff_ref = $hPath
    work_package_count = @($h.work_packages).Count
    C_frozen = $true
    payload_policy = "thin_ref_only_no_embedded_work_package"
}
$semFull = ($semThin | ConvertTo-Json -Depth 6 -Compress)
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "5d33马拉松：读handoff续跑剩余8WP" `
    -MustDoOneLiner "读handoff→全量WA→Pro派工→auto_continue" `
    -ForbiddenOneLiner "spawn/完成/readback-only/GHA/C并行" `
    -AcceptanceOneLiner "Q1-Q7证据；signal用活run_id" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -ForceResend `
    -WaitSec 90
