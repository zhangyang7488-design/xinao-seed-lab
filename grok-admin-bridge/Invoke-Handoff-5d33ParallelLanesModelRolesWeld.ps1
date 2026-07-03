$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_5d33_parallel_lanes_model_roles_weld.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 14 -Compress)
$lanes = ($h.lanes | ConvertTo-Json -Depth 10 -Compress)
$roi = ($h.parallel_dispatch_decision | ConvertTo-Json -Depth 8 -Compress)
$loc = ($h.local_snapshot_cn | ConvertTo-Json -Depth 6 -Compress)
$semFull = "{0}|lanes={1}|parallel_dispatch={2}|local_snapshot={3}|spec_ref={4}|handoff_ref={5}|sentinel={6}" -f `
    $sem, $lanes, $roi, $loc, $h.spec_ref, $hPath, $h.sentinel
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "WP1-B harness then fan-out lanes model_tier JSONL weld" `
    -MustDoOneLiner "WORKER_ASSIGNMENT lanes[]; copy spec; lane_a+lane_c parallel; join_evidence" `
    -ForbiddenOneLiner "no_2nd_A_window; no_mini_coder; no_deepseek_harness; no_B_spark; no_completion" `
    -AcceptanceOneLiner "spec dual-copy; JSONL model_tier; 3 workers no correction_note" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -ForceResend `
    -WaitSec 90