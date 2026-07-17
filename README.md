# Grok 4.5 Island Workspace

This repository carries the isolated Grok 4.5 role contracts and endpoint canaries. It is not a second orchestrator or a resident control plane.

## Current execution boundary

- Codex is the thinking/orchestration brain and the single writer for tightly coupled edits.
- Grok workers, Codex agents, or both are selected by positive net benefit. When benefits are close, prefer Grok; quota is scheduling telemetry, not a dispatch gate.
- The canonical route is Temporal + Docker `houtai-gongren` + worker-internal LangGraph.
- This repository owns the Grok 4.5 endpoint identity and canaries only. The sole bounded Grok WorkerPool implementation lives in the Admin repository and is referenced, not copied, here.
- Visible injection, watchdog, scheduler, daemon, resident loop, and host terminal paths are absent.
- Runtime state and evidence belong under `D:\XINAO_RESEARCH_RUNTIME`; generated state is not committed here.

## Endpoint checks

```powershell
.\grok-admin-bridge\Invoke-GrokAcpxTerminalCapabilityEnforce.ps1 -Action Enforce
.\grok-admin-bridge\Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1 -Action TerminalCapability
```

Role boundaries are indexed by `grok-admin-bridge/grok_island_core_index.v1.json`.
