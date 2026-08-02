# S engineering workspace

S is the general engineering body and mature-capability carrier. It is not the
default XINAO research object, a science parent, or a second control plane.

## Active machine architecture

- Thin hot entry: `C:\Users\xx363\Desktop\主线`
- Default XINAO native research: `E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research`
- General engineering and WorkerPool tooling: `E:\XINAO_RESEARCH_WORKSPACES\S`
- Live runtime, recent evidence, and recovery state: `D:\XINAO_RESEARCH_RUNTIME`
- Cold archaeology: `E:\XINAO_COLD_STORAGE\archives\LEGACY_XINAO_PLATFORM`

Without an explicit different task, a new Codex window continues native XINAO
research. S is entered only for an explicit engineering task or a concrete
engineering gap exposed by live research. Finishing that bounded child returns
to the native-research parent.

Ordinary bounded worker labor uses the installed supervisor/dispatch Skills.
Grok is normally preferred when its independent quota and the task fit produce
positive net benefit. Terra, Luna, Sol, and Codex collaboration share the Codex
quota pool; built-in collaboration subagents require exceptional net benefit.

## Retained engineering surface

- ordinary Grok/Terra/Luna WorkerPool launchers and dispatch adapters;
- generic Temporal/LangGraph durable execution for explicitly durable work;
- behavior regressions and Promptfoo evaluation;
- local memory and human-material intake;
- the thin Situation Island catalog updater in `scripts/`;
- the reusable dual-brain coordination kernel.

The removed legacy XINAO platform and its tests are absent from the active tree.
Git history is the code recovery boundary; the E-drive archive holds unique
historical documents and evidence. Neither is loaded by default.

## Development

```powershell
uv sync --extra dev --extra workflow
uv lock --check
uv run python scripts/run_ci_hygiene.py --all
uv run pytest -q
```

`--all` is the local full remote hygiene parity check for the retained root and
dual-brain project cones. Root hygiene covers `services`, `scripts`, and `tests`.

Tests and engineering reports do not claim scientific progress or replace the
native-research consumer.
