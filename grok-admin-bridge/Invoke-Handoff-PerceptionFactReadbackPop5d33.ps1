$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$hPath = Join-Path $PSScriptRoot "handoffs\2026-06-28_perception_vs_fact_readback_pop5d33_convergence.v1.json"
$h = Get-Content -LiteralPath $hPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sem = ($h.semantic_object | ConvertTo-Json -Depth 12 -Compress)
$rt = ($h.runtime_context_cn | ConvertTo-Json -Depth 8 -Compress)
$semFull = "{0}|runtime_context={1}" -f $sem, $rt
& (Join-Path $PSScriptRoot "Send-GrokIntentToCodexA.ps1") `
    -UserIntentCn $h.intent_one_liner_cn `
    -SemanticObject $semFull `
    -IntentOneLiner "readonly reconcile perception vs fact; cd3d closeout; pop 5d33 stack converge" `
    -MustDoOneLiner "reconcile_readback; cd3d_phase_exit_gate; stack_pop_plan; WP1_evidence" `
    -ForbiddenOneLiner "no_completion_claim; no_kill_safe_worker; no_spawn_new_owner" `
    -AcceptanceOneLiner "zh_reconcile_sheet; cd3d_tri_state; 5d33_pop_plan; depth13_converge" `
    -TargetTaskId $h.task_binding.current_task_id `
    -AnchorTaskId $h.task_binding.anchor_root_task_id `
    -WaitSec 75