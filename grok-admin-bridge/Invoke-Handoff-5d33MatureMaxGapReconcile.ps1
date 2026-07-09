$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-28_5d33_mature_max_gap_reconcile_next_beat.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 14 -Compress)
$loc = ($h.local_snapshot_cn | ConvertTo-Json -Depth 6 -Compress)
$semFull = "{0}|local_snapshot={1}" -f $sem, $loc
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "mature_max gap reconcile + next beat; DAG!=map pass" `
    -MustDoOneLiner "gap_report; reopen_DAG; same_workflow_worker; default_handroll_scan" `
    -ForbiddenOneLiner "no_completion; no_GHA; no_phase7_as_done; no_spawn" `
    -AcceptanceOneLiner "gap_table; next_ready; default_handroll_answer" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -WaitSec 90