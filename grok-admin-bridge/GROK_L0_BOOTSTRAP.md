# Grok L0 bootstrap

The Admin repository is a thin isolated configuration and bounded Grok-lane surface.

- Read the session checkpoint first.
- Use A=`direct-grok-worker-pool` for typical bounded work while the current TUI owner is online. Use B=`Temporal → Docker houtai-gongren → worker-internal LangGraph` only after explicit handoff for post-window durability, cross-restart continuation, or unattended multiwave work.
- Select Grok, Codex agents, or a combination by current positive net benefit; softly prefer Grok when close.
- Preserve an existing route receipt across continuation; `continuous` or `resume` alone does not switch legs. WorkerPool is normal leg A selected by task fit/receipt, not a fallback or unconditional default.
- Do not create visible, resident, scheduled, watchdog, keepalive, or second-orchestrator paths.
