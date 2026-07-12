# Grok L0 bootstrap

The Grok 4.5 island is a thin endpoint identity and canary surface.

- Read the session checkpoint first.
- Use Temporal + Docker houtai-gongren + worker-internal LangGraph for durable or parallel work.
- Use Grok as the only default model worker with dynamic width.
- Preserve shell-capability deny, hidden stdio, and intent-decode canaries.
- Keep WorkerPool explicit and bounded.
- Do not create visible, resident, scheduled, watchdog, keepalive, or second-orchestrator paths.
