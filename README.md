# XINAO Codex local capability workspace

This repository contains the thin, locally verified capabilities that Codex uses directly. The
retired custom Seed Cortex / 333 / CLEAN controllers are not startup paths. The retained software
main route is the Tool Glue Constitution triplet: Temporal + Docker `houtai-gongren` + LangGraph.

## Current roots

- Workspace entry: `E:\XINAO_RESEARCH_WORKSPACES\S` (a junction to the active Git worktree).
- Human material entry: `C:\Users\xx363\Desktop\主线`.
- Runtime and evidence: `D:\XINAO_RESEARCH_RUNTIME`.
- Situation and cross-window checkpoint:
  `D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island`.
- Local long-term memory: `D:\XINAO_RESEARCH_RUNTIME\state\mem0`.

Files under `Desktop\主线` are human-controlled source material. Six were present at final audit,
including three concurrently restored, explicitly retained long-form files. They are discoverable
on demand; their full contents are not injected into every prompt.

## Retained capability surface

- `services/mcp/xinao_memory_mcp_server.py`: explicit local memory MCP.
- `services/mcp/local_mem0_store.py`: Ollama + embedded Qdrant storage with a cross-process lock
  and explicit close lifecycle.
- `scripts/local_data_profile.py`: local, token-efficient data profiling.
- `scripts/local_human_intake.py`: local document conversion and audio/video transcription.
- `evals/codex_capability`: outcome-based Promptfoo checks for the Codex app-server.
- `evals/context_intent_alignment`: balanced real-agent regressions that keep reversible local work
  fast while preventing assumptions from expanding external authority.
- `evals/proactive_mature_first`: live-agent mature-first + Grok-default worker behavior regressions
  (pinned Promptfoo, D-isolated state, deterministic assertions).
- `evals/suite_registry.v1.json`: the dual-loop registry; domain and behavior share evidence
  semantics but keep separate evaluators and completion claims.
- `evals/control_plane_incident`: continuity-specific control-plane incident admission checks
  (static fixtures are not runtime evidence).
- `evals/incident_response_lifecycle`: generic, evidence-bound incident lifecycle checks
  (runtime evidence required for closure).
- `docs/current/CODEX_INCIDENT_RESPONSE_LIFECYCLE_2026-07-11.md`: the bounded incident-response
  contract supplement and current official engineering comparison.
- `scripts/run_codex_capability_eval.ps1`: pinned local eval entrypoint.
- `scripts/run_context_intent_alignment_eval.ps1`: pinned, operation-scoped behavior-evolution
  eval using the real Codex app-server in read-only mode.
- `scripts/run_proactive_mature_first_eval.ps1`: pinned mature-first live-agent suite.
- `scripts/run_domain_self_evolution.ps1`: thin verify/fresh entry for the existing Market Lab P3
  finite protocol, exact Settlement, and TrialLedger.
- `scripts/run_self_evolution_eval_battery.ps1`: one bounded entry for domain, behavior, or both loops.
- `scripts/Import-PromptfooFailuresToBehaviorCandidates.ps1`: one-way trace/failure intake; it never
  promotes or rewrites policy.
- `docker-compose.yml` and `docker/houtai-gongren/Dockerfile`: reproducible Temporal worker stack.
- `services/agent_runtime/integrated_bus_runner.py`: canonical client entry for the real
  Temporal/LangGraph workflow.
- `services/agent_runtime/task_entry_claim.py`: durable task-entry adapter used by the Grok bridge.

Memory operations use:

```text
inter-process lock -> open Qdrant/history -> one operation -> close both -> release lock
```

This lets independent Codex agents share one D-drive embedded store without a boot service.

## Development

```powershell
uv sync --extra dev --extra human-capabilities --extra workflow
uv lock --check
uv run ruff check services scripts tests
uv run ruff format --check services scripts tests
uv run pytest -q
```

Tests in this repository are bounded and must not run `git add`, `git commit`, start legacy
workflows, or mutate the real worktree outside their temporary directories.

## Consolidated project domains

- `projects/dual-brain-coordination`: the local embedded coordination kernel and its preserved
  project history; it is not a second remote product or second orchestration spine.
- `projects/xinao-market-lab`: the bounded market-research engineering domain and its preserved
  project history; its tests and dependency environment remain explicitly project-scoped.

The Grok Admin and Grok 4.5 identity/isolation workspaces are recovery bundles outside GitHub, not
public subprojects. See `materials/repository_topology/recovery_manifest.v1.json` for exact hashes
and dispositions.

## Software main route

```powershell
docker compose up -d
docker exec houtai-gongren python -m services.agent_runtime.integrated_bus_runner `
  --temporal --address naijiu-shiwu:7233 `
  --input /evidence/state/integrated_bus_intake/default_input.md
```

Acceptance requires a real workflow ID and history, `worker_ownership=docker_daemon`,
`invoke_mode=temporal_langgraph_plugin`, and matching evidence under
`D:\XINAO_RESEARCH_RUNTIME`. Finalization records a read-only GitPython snapshot and writes proof
to `D:\XINAO_RESEARCH_RUNTIME\state\integrated_bus_proof`; it never stages or commits the S
worktree. WorkerPool remains an explicit bootstrap/fallback only.

## Operating model

Codex chooses dialogue, plan-only, bounded execution, or explicitly continuous work from the
current request. Complex work follows observable success criteria, implementation, independent
verification, and a concise evidence-backed reflection when a real failure produced a reusable
lesson. Context and memory are retrieved just in time; recalled text never grants authority.

Observed intent/object mismatches are distilled into balanced behavior cases. One small candidate
change is evaluated at a time, with local productivity cases beside external-effect regressions;
this is an episodic learn-and-promote loop, not a resident approval controller.

No Windows boot task, Startup entry, service, hidden daemon, or old continuation loop is required.
