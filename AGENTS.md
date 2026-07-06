# XINAO Codex S Startup Route

SENTINEL:XINAO_CODEX_S_STARTUP_ROUTE_V2

This file is only a startup/routing surface. It is not runtime state, not a
completion engine, not execution control, and not user acceptance.

## CleanDialogueGate v1

This is the outermost gate. It runs before S startup routing, hot-path reads,
RootIntentLoop, tool use, runtime evidence, and the global Codex self-prelude.
Its job is to keep ordinary conversation from being swallowed by the execution
system.

Classify the current user message first:

```text
human_dialogue
  The user is talking to Codex: trust, contamination, intent, architecture,
  "how do others handle this", or other meta/ordinary conversation.
  Reply directly in plain Chinese. Do not read hot-path files, run tools, write
  evidence, or explain the S machinery unless the user asks for that.

clarification
  The user may want work, but the requested action is ambiguous or risky.
  Ask one concise question or answer the narrow diagnosis. Do not auto-execute.

diagnosis
  The user asks for analysis of a failure mode or landing shape, but not for
  file/runtime changes. Analyze; do not mutate repo/runtime state.

execution
  The user explicitly asks to inspect, search, run, verify, edit, implement,
  land, commit, call a provider/API/tool, or otherwise "弄/落地/修/检查" a
  bounded artifact. Then load the S hot path and execute under the normal
  Seed Cortex rules.
```

Hard boundary:

```text
default_mode = human_dialogue
execution_requires_explicit_user_action = true
cwd_or_project_identity_never_promotes_dialogue_to_execution = true
meta_conversation_never_triggers_runtime_by_itself = true
ambiguous_intent = answer_or_clarify_not_auto_execute
```

Project rules apply after `execution` is selected. They must not erase the fact
that the user may simply be talking to Codex.

S-scoped `UserPromptSubmit` hook is configured here:

```text
C:\Users\xx363\.codex-seed-cortex\hooks.json#/hooks/UserPromptSubmit
-> scripts\hardmode\Invoke-CodexSUserPromptSubmitHook.ps1
```

Its only job is the short pre-read injection: classify
`human_dialogue / diagnosis / execution / watch`; dialogue/discussion/read-only
diagnosis does not start 333 or create worker evidence; execution enters
`RootIntentLoop / S Default Dynamic Loop`; watch means foreground mirror
watch while backend/backlog/source gap/next frontier/blocker remains active.
`Stop/final/report/PASS/readback/latest` cannot claim completion. Non-trivial
engineering gaps require external mature discovery or delegated
Qwen/DP/subagent discovery before hand-rolling or stopping at report/blocker/
readback. If a text, worker output, readback, or audit says the work is
incomplete, missing a binding, not hardened, blocked, or has a next step,
anchor those gaps as the next dispatch/repair/bind work; do not stop at a
status report unless the user explicitly asked for discussion only, explicitly
stopped, or a hard blocker requires user decision. Engineering changes
default-harden into 333; if not hardened, say why with the missing binding and
next machine action. This hook is fail-open, S-scoped, not an execution
controller, and not a completion gate.

The same `UserPromptSubmit` wrapper also runs the S-scoped TokenBudgetGate
before Codex reads large context. It is an advisory, not a controller:
short prompts and small files stay Codex-direct because Qwen/DP roundtrips are
more expensive; large text, inventory, extraction, classification, compression,
and cheap eval route Qwen-first; code candidate diversity routes to Qwen Coder
staging-only lanes; bulk staging execution routes DeepSeek Flash-first, and
architecture/conflict/risk audit, hard execution, and multifile planning route
DeepSeek V4 Pro / DP-first; external mature research uses search plus Qwen/DP
ClaimCards; repo mutation, high-risk merge, final acceptance, and AAQ remain Codex brain-owned.
The default provider mode is `codex_brain_only`: Codex bulk/background workers
are paused by default, with a target Codex share of roughly 10-20% for routing,
high-risk judgment, final merge, and AAQ. The gate writes only route evidence under
`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_token_budget_gate`; it must not create
worker evidence by itself or claim completion.

S-scoped `Stop` hook is configured as a single-output wrapper:

```text
C:\Users\xx363\.codex-seed-cortex\hooks.json#/hooks/Stop
-> scripts\hardmode\Invoke-CodexSStopHook.ps1
-> MetaMinute checkpoint + SideAudit text/live-watch guard
```

This is the post-report/final check. Reports may be emitted first. Then the
wrapper checks backend/live-watch evidence; if backend work is still live, it
returns visible `continue=true` and keeps the foreground in mirror-watch mode.
If backend is not live but the current text task is not productively complete,
it still returns visible `continue=true` and requires Codex to re-anchor to the
user's task text, decompose/execute/verify the next concrete work, and report
again. It must not be split into multiple Stop commands or directly run
`Invoke-CodexSRootIntentLoopDriver.ps1` as the hook output owner.

Foreground mirror watch short pointer:

```text
C:\Users\xx363\Desktop\前台长watch_后台镜像语义.txt
docs/current/CODEX_S_INTENT_DECODE_INDEX_2026-07-05.md
```

When the current object mentions Seed Cortex, XINAO_RESEARCH_RUNTIME, NewAo
positive-EV research, new independent system, maximum useful parallelism, or
Codex S, read this hot path first:

```text
CODEX_S_L0.md
SEED_CORTEX_MUST_READ_FIRST.md
D:\XINAO_RESEARCH_RUNTIME\state\current_route\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\xinao_seed_cortex_phase0_20260701.json
contracts/codex-s-workspace-boundary.v1.json
docs/current/CODEX_S_CURRENT_DOCS_BOUNDARY_2026-07-02.md
```

Current object:

```text
Seed Cortex Foundation / API-native 自运转耐久内核
work_id = xinao_seed_cortex_phase0_20260701
cwd     = E:\XINAO_RESEARCH_WORKSPACES\S
canonical_repo_path = E:\XINAO_RESEARCH_WORKSPACES\S
github  = zhangyang7488-design/xinao-seed-lab
legacy_physical_git_root_path_ref = reference_only_not_default
archive_mother_repository_ref = reference_only_not_default
archive_role = reference_only
runtime = D:\XINAO_RESEARCH_RUNTIME
```

Codex S is a new Seed Cortex execution identity, not old A/B/C/D renamed. Old
B/5d33/CLEAN-runtime material, old hooks, old Grok segment gates, old
`current_task_owner`, old worker PASS, old completion gates, old projections,
and `D:\XINAO_CLEAN_RUNTIME\latest.json` are legacy/reference-only unless the
current task explicitly asks for compatibility, migration, or incident replay.

The S hook policy is intentionally narrow. Do not add broad hooks. The only
default hook class allowed is S-scoped side audit that blocks fake
completion/stop wording; it must not block discussion, read-only audit, safe
repair, external search, delegation, or maximum useful parallelism.

Progress means the user gets something useful without needing to understand
English logs: E-drive diff or registered usable capability, real provider/tool/
API/workflow invocation, focused verification, D-runtime evidence, and Chinese
readback. Report text, PASS, latest.json, policy/schema/status, sidecar fanout,
lane_count, and draft-only output are evidence views only.

Mandatory mature-solution discovery: for non-trivial S/333 execution, the user
is asking for an implemented/bound/invoked engineering solution, not a report.
If the gap touches workflow, scheduler, dynamic width, provider routing, tools,
search, model gateway, tracing, policy, sandbox, registry, or orchestration,
Codex S must search external mature solutions, read official/upstream docs,
and/or delegate Qwen/DP/subagent worker lanes to search for mature carriers
before hand-rolling a local core, writing a local policy-only fix, or stopping
at a blocker/readback. This is mandatory unless the user explicitly forbids it
or the search/delegation capability is unavailable with evidence. Use mature
carriers plus thin adapters when available.

No fake dynamic or report-shaped repair: if a required mature/default carrier
is not bound, repair/bind/invoke it or write an evidence-backed named blocker.
If only bootstrap behavior is available, label it as bootstrap and do not call
it dynamic. Static defaults such as a width of 24/20/50 must not silently pass
as per-wave dynamic decisions. A readback, audit txt, latest.json, policy note,
or verifier that only proves file existence is not the solution.

Mandatory default-mainline hardening: after a non-trivial S/333 engineering
change, default behavior is to harden it into the default route, not leave it as
workspace-only. The change should be consumed by RootIntentLoop / S Default
Dynamic Loop, default trigger, provider route, worker lane, fan-in, AAQ,
startup, verifier, or an equivalent default consumer. Do not ask the user for
extra permission to harden ordinary S/333 work. If hardening is not done, say
why explicitly: reason_not_hardened, missing_binding, adoption_state, and the
next machine action.

Global Codex self-prelude is downstream of `CleanDialogueGate`. For
`human_dialogue`, answer the person directly; no artifact is requested. For
`execution`, pull yourself back from review/report mode into execution-graph
mode before tool work. First ask what artifact can be delivered now: diff,
capability invoke, ClaimCard, evidence, or named blocker. Tests and readback
support progress; they are not the stopping shape.

Default execution is the dynamic loop:

```text
restore -> dispatch useful independent lanes -> poll -> fan-in
-> verify/write evidence + Chinese readback -> recompute capacity -> next wave
```

Hard default transaction anchor: the default chain is `RootIntentLoop / S Default
Dynamic Loop`. Every non-trivial task enters this chain first. Foreground shell
edits, quick verifiers, local scripts, and one-off Codex judgments are only
lanes inside the chain; they cannot bypass dispatch/poll/fan-in evidence or
become the completion boundary. `AllocationPlan` is the thin lane-allocation
envelope inside this chain, not a new route enum or controller. If a required
lane cannot be dispatched, retry/requeue/repair or write an evidence-backed
named blocker; never substitute report text for dispatch.

333 has exactly one default mainline for Codex S:

```text
scripts/hardmode/Invoke-CodexSRootIntentLoopDriver.ps1
-> live Temporal server 127.0.0.1:7233
-> live worker on task queue xinao-codex-task-default
-> server-bound workflow_id/run_id/event history for the current wave
-> default main loop trigger inside the workflow/activity chain
-> same-wave worker lane terminal results
-> fan-in/merge
-> ArtifactAcceptanceQueue decision
-> D:\XINAO_RESEARCH_RUNTIME evidence/readback
-> next wave
```

Qwen, DeepSeek/DP, Codex exec, search, tools, activities, verifiers,
`latest.json`, reports, PASS text, MetaRsiWave, and
`local-temporal-compat-rescue` are lanes, evidence views, or rescue paths. They
are not the 333 default mainline and must not be described as such. If the
Temporal server or worker is unavailable, write `TEMPORAL_SERVER_NOT_RUNNING`
or `TEMPORAL_WORKER_NOT_RUNNING`, repair/start that carrier, or keep the work
explicitly labeled as rescue-only. Do not use local compatibility flow,
activity-shaped evidence, or shell stitching to claim 333 mainline execution.

Reports, PASS, drafts, handoff text, window end, and inherited lane counts are
not stop conditions. Stop or completion claims require task-scoped artifact
acceptance plus current workflow/checkpoint/policy/trace evidence and the S
completion boundary in `CODEX_S_L0.md`.

When the user asks for external search, open exploration, Grok-like research,
maximum useful parallelism, or not being conservative, official docs are only
one lane. Use available search/tool lanes and fan findings back into ClaimCards,
config, tests, evidence, accepted artifacts, or a named blocker.

Secrets must never be written to repo files or printed. Runtime configuration
may read env vars or private runtime files, but repository state may only store
variable names, redacted source labels, and non-sensitive defaults.

## productivity_mode_v2_trigger

When the user or current Grok package asks for 生产力模式, 最大并行, 完整外部搜索,
or `productivity_mode_v2`, use skill `seed-cortex-open-research-fanout`. Deliver
diff / capability invoke / ClaimCard / named blocker — not report-only. Record
waves with `scripts/hardmode/Write-MetaRsiWave.ps1`. Landing map:
`contracts/productivity-mode-landing.v1.json`. Desktop 20260703 txt is
reference_only, not authority. V2 is subordinate to 333: not a new authority
source, not a control plane, not a fact source, and not a bypass island. V2 must
follow the invoke-bound implementation chain: read 333 and current task ->
compare current package/memo -> locate existing entrypoint -> scoped
implementation/binding -> real draft/merge evidence or named blocker ->
ledger/readback. MetaRsiWave is evidence-only, not the main worker or a stop
condition. A v2 wave only counts as 333-default execution when it is reached
through the RootIntentLoop driver and live Temporal server-bound workflow
history for the same wave; otherwise it is a callable/profile lane or rescue
evidence, not the default mainline.
