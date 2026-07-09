【Codex→Grok 人类出口路由回执 · 非完成】
task_id: codexa_mature_intent_88afdba4e8634adeb66c6d9328c570d1
generated_at: 2026-06-27T20:50:44+0800
source: manual-state-correction-v2-shortcut-semantics
human_egress_route: grok_report_only
desktop_grok_existing_context_preferred: true
shortcut_allowed_when_no_existing_context: true
desktop_grok_context_gate: new_grok_session_started
pre_existing_grok_tui_found: false
used_existing_grok_tui: false
shortcut_launched: true
context_loss_risk: false
consumer_egress_blocked: false
codex_final_to_user_allowed: false
worker_final_user_visible_allowed: false
worker_final_backend_evidence_only: true
no_pytest_wall_to_user: true
segment_audit_status: 
summon_ref: 
grok_verdict: 
next_worker_task_id: 
worker_jsonl_backend_evidence: 
worker_final_backend_only: 

给 Grok 的处理要求：
- 用中文向用户汇报当前段状态；不要复述 pytest/JSONL 墙。
- Codex worker final 只能当后台证据，不是用户状态源。
- 若需要 verdict，仍按 Grok→A dual_visible_and_backend leg2 回写。
- 这不是用户完成、不是 Stop、不是 completion claim。
