$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_5d33_parallel_lane_c_harness_implementation.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 14 -Compress)
$lanes = (@{ lane_a = $h.lane_a_mainline; lane_c = $h.lane_c_parallel } | ConvertTo-Json -Depth 8 -Compress)
$loc = ($h.local_snapshot_cn | ConvertTo-Json -Depth 6 -Compress)
$semFull = "{0}|parallel_lanes={1}|local_snapshot={2}|handoff_ref={3}|sentinel={4}" -f $sem, $lanes, $loc, $hPath, $h.sentinel
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "parallel Lane-C bind B repo burn C quota" `
    -MustDoOneLiner "WORKER_ASSIGNMENT lane_a+lane_c; C exec B/nianhua now parallel" `
    -ForbiddenOneLiner "no_C_fork_repo; no_B_spark; no_readonly_audit_as_impl; no_completion" `
    -AcceptanceOneLiner "C JSONL on B repo; real test/spec diff; overlaps Lane-A time" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -ForceResend `
    -WaitSec 90