$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-28_5d33_next_whole_beat_stack_pop_phase2_entry.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 14 -Compress)
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $sem `
    -IntentOneLiner "5d33 next whole beat: stack pop + Phase1 narrow + Phase2 entry" `
    -MustDoOneLiner "pop_stack_5d33; WORKER_ASSIGNMENT; mature_worker; same_workflow" `
    -ForbiddenOneLiner "no_spawn; no_completion; no_idle_echo; no_panel_gate" `
    -AcceptanceOneLiner "5d33_current; Phase2_DAG_ready; JSONL_evidence" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -WaitSec 90