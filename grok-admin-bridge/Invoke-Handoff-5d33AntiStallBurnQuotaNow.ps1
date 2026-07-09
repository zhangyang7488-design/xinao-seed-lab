$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_5d33_anti_stall_burn_quota_now.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 10 -Compress)
$roi = ($h.parallel_dispatch_decision | ConvertTo-Json -Depth 8 -Compress)
$ev = ($h.live_evidence_cn | ConvertTo-Json -Compress)
$semFull = "{0}|anti_stall=burn_quota_now|evidence={1}|parallel_dispatch={2}|handoff_ref={3}|sentinel={4}" -f $sem, $ev, $roi, $hPath, $h.sentinel
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "USER STALL: burn A+C exec NOW; no signal-only idle" `
    -MustDoOneLiner "dispatch codex-a exec + codex-c exec parallel within 60s; real diff" `
    -ForbiddenOneLiner "no_readback_only; no_snapshot_only; no_A_chat_without_worker; no_idle_handoff" `
    -AcceptanceOneLiner "new worker JSONL after 07:17; app-server not IDLE; diff lands" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -ForceResend `
    -WaitSec 90