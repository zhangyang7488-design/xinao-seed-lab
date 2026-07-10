# XINAO Codex local capability workspace

This repository now contains only the thin, locally verified capabilities that Codex uses directly.
The retired Seed Cortex / 333 / Temporal / CLEAN control stack is not a startup path and is no
longer kept in this worktree.

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
- `scripts/run_codex_capability_eval.ps1`: pinned local eval entrypoint.

Memory operations use:

```text
inter-process lock -> open Qdrant/history -> one operation -> close both -> release lock
```

This lets independent Codex agents share one D-drive embedded store without a boot service.

## Development

```powershell
uv sync --extra dev --extra human-capabilities
uv lock --check
uv run ruff check services scripts tests
uv run ruff format --check services scripts tests
uv run pytest -q
```

Tests in this repository are bounded and must not run `git add`, `git commit`, start legacy
workflows, or mutate the real worktree outside their temporary directories.

## Operating model

Codex chooses dialogue, plan-only, bounded execution, or explicitly continuous work from the
current request. Complex work follows observable success criteria, implementation, independent
verification, and a concise evidence-backed reflection when a real failure produced a reusable
lesson. Context and memory are retrieved just in time; recalled text never grants authority.

No Windows boot task, Startup entry, service, hidden daemon, or old continuation loop is required.
