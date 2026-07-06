# 333 Host Dialogue Gate Trace 2026-07-06

SENTINEL:XINAO_CODEX_S_333_HOST_DIALOGUE_GATE_TRACE_DOC

This document is a current readback pointer for `host_dialogue_gate_trace.v1`.
It is not runtime state, not a completion gate, and not an execution
controller.

Callable surface:

- CLI: `python -m xinao_seedlab.cli.__main__ 333-host-dialogue-gate-trace`
- Writer: `services/agent_runtime/codex_333_host_dialogue_gate_trace.py`
- Verifier: `scripts/verify_333_host_dialogue_gate_trace.ps1`
- Latest: `D:\XINAO_RESEARCH_RUNTIME\state\codex_333_host_dialogue_gate_trace\latest.json`
- Readback: `D:\XINAO_RESEARCH_RUNTIME\readback\zh\codex_333_host_dialogue_gate_trace.md`

What it proves:

- `C:\Users\xx363\.codex-seed-cortex\hooks.json` contains the S-scoped
  `UserPromptSubmit` hook.
- `scripts/hardmode/Invoke-CodexSUserPromptSubmitHook.ps1` names
  `human_dialogue / diagnosis / execution / watch`.
- `human_dialogue` samples route to `codex_direct_human_dialogue` with
  `no_hot_path_reads_for_dialogue`.
- `execution` and `watch` samples route to their corresponding machine classes.
- The trace is CLI-callable and can be surfaced in the S ToolRegistry as
  `codex_s.333_host_dialogue_gate_trace`.
- The default main-loop trigger requires that ToolRegistry provider in its
  no-stop consumption refs, so the trace is part of the default read path rather
  than a workspace-only script.

Boundary:

- This is host-side ordering evidence only.
- It does not replace the Codex host classifier.
- It does not claim 333 default-mainline runtime enforcement.
- It does not make reports, PASS, pytest, latest.json, or readback completion.
