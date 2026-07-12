---
name: session-context-checkpoint
description: Read or save a short restart-safe Grok checkpoint on D without dispatching work.
---

# Session context checkpoint

Use this capability only for continuity. It is not a worker pool, scheduler, keepalive, or orchestration surface.

## Read

From the repository root:

powershell -NoProfile -ExecutionPolicy Bypass -File .\grok-admin-bridge\Invoke-GrokSessionContextCheckpoint.ps1 -Read

If a checkpoint exists, resume from its short brief. Do not replay the full chat.

## Save

Prepare a UTF-8 JSON draft on D: with these fields:

- user_intent_anchor_cn
- session_resume_brief_cn
- last_machine_actions
- next_machine_actions
- named_blockers
- evidence_refs
- do_not_re_explain_cn

Then run:

powershell -NoProfile -ExecutionPolicy Bypass -File .\grok-admin-bridge\Invoke-GrokSessionContextCheckpoint.ps1 -Save -InputJson D:\path\save_draft.json

The script writes latest.json plus one timestamped history file. It must not dispatch workers, pulse a pool, start a scheduler, create a visible terminal, or run a resident loop.
