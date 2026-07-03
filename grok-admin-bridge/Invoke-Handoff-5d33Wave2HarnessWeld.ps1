$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-29_5d33_wave2_harness_auto_continue_weld.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 14 -Compress)
$loc = ($h.local_snapshot_cn | ConvertTo-Json -Depth 6 -Compress)
$semFull = "{0}|local_snapshot={1}|handoff_ref={2}" -f $sem, $loc, $hPath
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "wave2 harness weld: sunset A 180s babysitter" `
    -MustDoOneLiner "PR1 closeout; PR2 auto_continue dedup; PR2b dag next_ready; PR5 spec" `
    -ForbiddenOneLiner "no_completion; no_spawn; no_GHA; no_phase10_11_scope; no_idle_handoff_mainline" `
    -AcceptanceOneLiner "3 workers no correction_note; partial_dispatched<=30s; spec on disk" `
    -TargetTaskId $h.anchor_task_id `
    -AnchorTaskId $h.anchor_task_id `
    -RoutingVerb $h.routing_verb `
    -WaitSec 90