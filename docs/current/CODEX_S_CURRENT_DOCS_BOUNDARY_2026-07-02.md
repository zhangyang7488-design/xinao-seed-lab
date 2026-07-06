# Codex S Current Docs Boundary 2026-07-02

SENTINEL:XINAO_CODEX_S_CURRENT_DOCS_BOUNDARY_2026_07_02

This file is a current-document boundary for the Seed Cortex / Codex S
workspace. It is not runtime state, not a completion gate, and not a control
plane.

Current hot-path documents for this workspace:

- `CODEX_S_L0.md`
- `SEED_CORTEX_MUST_READ_FIRST.md`
- `D:\XINAO_RESEARCH_RUNTIME\state\current_route\latest.json`
- `D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\xinao_seed_cortex_phase0_20260701.json`
- `contracts/codex-s-workspace-boundary.v1.json`
- `docs/current/CODEX_S_CURRENT_DOCS_BOUNDARY_2026-07-02.md`

Boundary rules:

- `CleanDialogueGate v1` is the outermost conversation boundary. Ordinary
  human/meta dialogue defaults to direct Chinese answer and must not trigger
  hot-path reads, tools, RootIntentLoop, runtime evidence, or S machinery unless
  the user explicitly asks for execution.
- Codex S is a Seed Cortex execution identity, not old A/B/C/D renamed.
- Legacy CLEAN/B/5d33 material is reference-only unless a current task asks
  for compatibility, migration, or incident replay.
- Progress must land as repo diff, registered capability invocation,
  task-scoped evidence, ClaimCard, or named blocker plus Chinese readback.
- Non-trivial S/333 execution is an engineering-solution request, not a report
  request. Codex S must use external mature search, official/upstream docs,
  and/or Qwen/DP/subagent discovery before hand-rolling scheduler, workflow,
  provider routing, dynamic width, model gateway, policy, search, tracing,
  registry, sandbox, or orchestration cores, unless the user explicitly forbids
  it or the search/delegation capability is unavailable with evidence.
- Bootstrap behavior must be labeled as bootstrap, not dynamic. Static defaults
  such as 24/20/50 cannot pass as per-wave dynamic decisions; missing mature or
  dynamic binding means repair/bind/invoke now or name the blocker, not write a
  report/readback as the solution.
- Mandatory default-mainline hardening: after a non-trivial S/333 engineering
  change, default behavior is to harden it into the default route. If it remains
  workspace-only/candidate-only, the output must say why: reason_not_hardened,
  missing_binding, adoption_state, and next_machine_action. Ordinary
  default-route hardening does not require another user reminder.
- Latest aliases are convenient read models only. Task acceptance must cite
  wave/activity evidence when a package asks for immutable evidence.
- 333 has one default mainline: `RootIntentLoop / S Default Dynamic Loop` through
  `scripts/hardmode/Invoke-CodexSRootIntentLoopDriver.ps1`, live Temporal server
  `127.0.0.1:7233`, live worker on `xinao-codex-task-default`, current-wave
  server-bound `workflow_id`/`run_id`/event history, default trigger,
  same-wave worker terminal results, fan-in/merge, ArtifactAcceptanceQueue, and
  D-runtime evidence/readback. Activity refs, verifiers, latest files, reports,
  PASS text, MetaRsiWave, Qwen/DP output, and local Temporal compatibility
  rescue are not this mainline.
- Worker output must enter staging, FanIn, AAQ, and next_frontier before any
  completion-shaped wording.
- `host_dialogue_gate_trace.v1` is documented in
  `docs/current/CODEX_S_333_HOST_DIALOGUE_GATE_TRACE_2026-07-06.md`; it is a
  callable trace for UserPromptSubmit/CleanDialogueGate ordering, not a host
  platform controller or completion gate.
- `control_vs_evidence_boundary_contract.v1` is documented in
  `docs/current/CODEX_S_333_CONTROL_VS_EVIDENCE_BOUNDARY_CONTRACT_2026-07-06.md`;
  it keeps Temporal/workflow commands and events separate from latest/readback/
  PASS/ToolRegistry read models, and is not an execution controller or
  completion gate.

This document intentionally contains no secrets and no provider credentials.
