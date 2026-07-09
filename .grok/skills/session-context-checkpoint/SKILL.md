---
name: session-context-checkpoint
description: >
  Save/read Grok session context checkpoint so restarts resume without re-explaining.
  Use on EVERY new session (Read first), after material progress (Save), or when user
  says 续上/保存上下文/重启别重聊/检查点. Slash: /session-checkpoint.
  NOT chat log — structured brief on D drive.
---

# Session Context Checkpoint

**重启不靠慢慢重聊。** 本机 `latest.json` = 当轮续接 brief；Memory.md = 跨项目偏好。

## New session — ALWAYS Read first

```powershell
Set-Location "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
.\Invoke-GrokSessionContextCheckpoint.ps1 -Read
```

- If `status=no_checkpoint_yet` → then L0 + Memory
- If checkpoint exists → **resume directly**; cite `session_resume_brief_cn` in first reply; **do not** re-explain architecture from zero
- Honor `do_not_re_explain_cn` list

## After progress or user asks 保存/续上 — Save

**Prefer `-InputJson`** (UTF-8 draft avoids CLI Chinese/array truncation):

```powershell
# 1) Write D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\save_draft.json (UTF-8)
# 2) Save:
.\Invoke-GrokSessionContextCheckpoint.ps1 -Save `
  -InputJson "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\save_draft.json" `
  -IncludeRegistryScan
```

Draft fields: `user_intent_anchor_cn`, `session_resume_brief_cn`, `last_machine_actions`, `next_machine_actions`, `named_blockers`, `evidence_refs`, `do_not_re_explain_cn`.

## Paths

| What | Where |
|------|-------|
| latest | `D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json` |
| history | `checkpoint_*.json` same dir |
| contract | `grok-admin-bridge/grok_session_context_checkpoint.v1.json` |
| rule | `.grok/rules/24-grok-session-context-checkpoint.md` |

## Must / Must not

- **Must** Save before long session ends or when user stresses 重启别重聊
- **Must not** dump full chat into checkpoint
- **Must not** treat MEMORY.md as session substitute
- SessionStart hook already runs `-Read -Quiet` (fail-open)