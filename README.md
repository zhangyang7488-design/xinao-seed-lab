# Grok Admin Isolated Workspace

This repository is the isolated Admin worker surface. Admin is not a third governance brain and is not Windows elevation.

## Current execution boundary

- Codex owns orchestration and is the single writer for tightly coupled edits.
- Grok workers, Codex agents, or both are selected by positive net benefit from the ready frontier, latency, quota telemetry, context advantage, and evidence need. When benefits are close, prefer Grok; do not burn without a real task.
- The canonical route is Temporal + Docker `houtai-gongren` + worker-internal LangGraph.
- The local WorkerPool is a bounded bootstrap/fallback surface, activated when it is the best useful route; it is not the durable default.
- Visible terminal, visible injection, scheduler, watchdog, daemon, and resident-loop paths are absent.
- Runtime state and evidence belong under `D:\XINAO_RESEARCH_RUNTIME`; generated state is not committed here.

## Bridge checks

```powershell
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
```

The project overlay is in `.grok/config.toml`; bridge contracts and bounded verification scripts are in `grok-admin-bridge/`. Shell-capability enforcement is owned by the Grok 4.5 island repository.
