# Grok L0 bootstrap

The Admin repository is a thin isolated configuration and explicit-fallback surface.

- Read the session checkpoint first.
- Use Temporal + Docker houtai-gongren + worker-internal LangGraph for durable or parallel work.
- Use Grok as the only default model worker with dynamic width.
- Keep WorkerPool explicit and bounded.
- Do not create visible, resident, scheduled, watchdog, keepalive, or second-orchestrator paths.
