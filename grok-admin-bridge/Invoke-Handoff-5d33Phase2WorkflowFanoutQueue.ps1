$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_5d33_phase2_workflow_fanout_queue_weld.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 8 -Compress)
$roi = ($h.parallel_dispatch_decision | ConvertTo-Json -Depth 6 -Compress)
$p1 = ($h.phase1_evidence_cn | ConvertTo-Json -Compress)
$semFull = "{0}|phase1_evidence={1}|parallel_dispatch={2}|authority=外部完整.txt|handoff_ref={3}|sentinel={4}" -f $sem, $p1, $roi, $hPath, $h.sentinel
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "Phase2: WP1-B + workflow fan-out + pending_handoff queue" `
    -MustDoOneLiner "fix C JSONL path; weld parallel activities; drain handoff queue" `
    -ForbiddenOneLiner "no_kill_workers; no_bypass_default; no_completion; no_spawn" `
    -AcceptanceOneLiner "3 workers no correction_note; dual activity in history; queue file exists" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -ForceResend `
    -WaitSec 90