$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_pro_pool_c_deepseek_burn_division_weld.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 10 -Compress)
$pools = ($h.three_pool_burn_plan | ConvertTo-Json -Depth 8 -Compress)
$roi = ($h.parallel_dispatch_decision | ConvertTo-Json -Depth 8 -Compress)
$semFull = "{0}|three_pool={1}|parallel_dispatch={2}|spec_ref={3}|handoff_ref={4}|sentinel={5}" -f `
    $sem, $pools, $roi, $h.spec_ref, $hPath, $h.sentinel
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "Pro60-75% + C5h15-25% + DeepSeek5-15% parallel fan-out" `
    -MustDoOneLiner "3-pool WORKER_ASSIGNMENT; router pool_id JSONL; fan-out join weld" `
    -ForbiddenOneLiner "no_spark; no_deepseek_harness; no_serial_C; no_readback_only" `
    -AcceptanceOneLiner "spec dual-copy; 3 pool JSONL overlap; pool_id in JSONL" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -ForceResend `
    -WaitSec 90