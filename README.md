# Grok Admin Isolated Workspace

This repository is the isolated Admin worker surface. Admin is not a third governance brain and is not Windows elevation.

## Current execution boundary

- Codex is the thinking/orchestration brain and the single writer for tightly coupled edits.
- Grok is the only default model worker. Width is chosen dynamically from the ready frontier, quota, latency, and evidence.
- The canonical route is Temporal + Docker `houtai-gongren` + worker-internal LangGraph.
- The local WorkerPool is an explicit bounded bootstrap/fallback surface only.
- Visible terminal, visible injection, scheduler, watchdog, daemon, and resident-loop paths are absent.
- Runtime state and evidence belong under `D:\XINAO_RESEARCH_RUNTIME`; generated state is not committed here.

## Bridge checks

```powershell
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
```

The project overlay is in `.grok/config.toml`; bridge contracts and bounded verification scripts are in `grok-admin-bridge/`. Shell-capability enforcement is owned by the Grok 4.5 island repository.
