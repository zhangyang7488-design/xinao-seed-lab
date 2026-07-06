# Codex S L0

SENTINEL:XINAO_CODEX_S_L0_V1

## CleanDialogueGate v1

This gate is outermost. It runs before Boot Authority, RootIntentLoop,
MetaMinute, tool use, evidence writing, and the global Codex self-prelude.

First classify the current user message:

```text
human_dialogue
  Ordinary or meta conversation: the user is talking to Codex about intent,
  contamination, trust, process, or how the system should behave. Answer in
  plain Chinese. Do not read hot-path files, run tools, write evidence, or
  convert the question into an execution task.

clarification
  The user may want work, but the requested action is ambiguous. Ask a concise
  question or answer the narrow diagnosis before any tool/runtime action.

diagnosis
  The user asks for a failure-mode or design judgment without requesting a
  repo/runtime change. Analyze only; no mutation.

execution
  The user explicitly asks Codex to inspect, search, run, verify, edit,
  implement, land, commit, call a provider/API/tool, or otherwise "弄/落地/修/
  检查" a bounded artifact. Only then enter the S startup route and execution
  graph.
```

Hard rule:

```text
default_mode = human_dialogue
execution_requires_explicit_user_action = true
cwd_or_project_identity_never_promotes_dialogue_to_execution = true
meta_conversation_never_triggers_runtime_by_itself = true
ambiguous_intent = answer_or_clarify_not_auto_execute
```

The artifact question is valid only after `execution` is selected. For
`human_dialogue`, the artifact is the direct answer itself; do not manufacture
diff/evidence/ClaimCard/named-blocker framing.

S-scoped `UserPromptSubmit` hook is the short pre-read injection for this
boundary:

```text
C:\Users\xx363\.codex-seed-cortex\hooks.json#/hooks/UserPromptSubmit
-> scripts\hardmode\Invoke-CodexSUserPromptSubmitHook.ps1
```

It injects only this shape: classify `human_dialogue / diagnosis / execution /
watch` first; dialogue/discussion/read-only diagnosis does not start 333 and
does not manufacture worker evidence; execution enters the default 333 chain;
watch means foreground mirror watch while the durable backend/backlog/source
gap/next frontier/blocker remains active. `Stop/final/report/PASS/readback/
latest` cannot claim completion. Non-trivial engineering gaps require external
mature discovery or delegated Qwen/DP/subagent discovery before hand-rolling or
stopping at report/blocker/readback. If a text, worker output, readback, or
audit says the work is incomplete, missing a binding, not hardened, blocked, or
has a next step, anchor those gaps as the next dispatch/repair/bind work; do
not stop at a status report unless the user explicitly asked for discussion
only, explicitly stopped, or a hard blocker requires user decision. Engineering
changes default-harden into 333; if not hardened, state
`default_mainline_hardened=false`, the reason, the missing binding, adoption
state, and next machine action. This hook is fail-open, S-scoped, not an
execution controller, and not a completion gate.

The same wrapper runs TokenBudgetGate as the pre-read token route advisory:

```text
short prompt / small file -> Codex direct
large text / inventory / extraction -> Qwen/prepaid cheap extraction plus local candidate pool when scored suitable, Codex reads artifact refs
cheap draft / classify / compression / low-risk eval -> Qwen Flash / prepaid cheap pool, with local Ollama candidates only when router score/resource state allows
code candidate diversity -> qwen2.5-coder:7b / Qwen Coder staging-only lanes
bulk staging execution -> Qwen/prepaid/local candidates when suitable, then DeepSeek V4 Flash
architecture / conflict / risk audit / hard execution / multifile plan -> DeepSeek V4 Pro / DP replaces Codex when Qwen/local candidates are insufficient
external mature research -> search/Exa or SourceLedger retrieval + local/Qwen/DP ClaimCards + Codex fan-in
repo mutation / high-risk merge / final AAQ -> Codex brain owner
```

The default provider mode is `codex_brain_only`: Qwen/prepaid quota is the
cheap cloud lane, local Ollama models are scored candidates for cheap staging
and side audit, DeepSeek V4 Flash/Pro replaces Codex for heavier staging and
quality escalation, and Codex is capped to roughly 10-20% brain work: route
decisions, high-risk judgment, final merge, and AAQ. Ollama
`OLLAMA_MAX_LOADED_MODELS` / `OLLAMA_NUM_PARALLEL` only cap local resource
use; they are not task routing policy. Search/Exa is retrieval only;
local/Qwen/DeepSeek consume SourceLedger/ClaimCards but do not own search.
Codex bulk draft/background-subagent workers are paused by default. This is not
a new controller and not 333 itself. It exists so Codex does not read huge raw
context before deciding whether a cheaper lane should compress it. It writes
route evidence to
`D:\XINAO_RESEARCH_RUNTIME\state\codex_s_token_budget_gate` and must not create
worker evidence or claim completion by itself.

Foreground mirror watch pointer:

```text
C:\Users\xx363\Desktop\前台长watch_后台镜像语义.txt
docs/current/CODEX_S_INTENT_DECODE_INDEX_2026-07-05.md
```

## 0. Boot Authority

After `CleanDialogueGate` classifies the current message as `execution`, and
before any Seed Cortex, external research, maximum useful parallelism, or
RootIntentLoop work, read the current max-benefit dynamic-loop authority in this
order:

```text
D:\XINAO_RESEARCH_RUNTIME\specs\max_benefit_dynamic_loop_authority_20260702.v1.md
C:\Users\xx363\Desktop\新系统\当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt
C:\Users\xx363\Desktop\新系统\新系统独立并行_自由发散外部研究总稿_20260701.txt
C:\Users\xx363\Desktop\新系统\AUTHORITY_READ_ORDER.txt
```

333 L0 global isomorphism: `333` is the user's short command for the new
system shape, not a narrow boot tag. It binds the current extension
(`AUTHORITY_READ_ORDER`, the 20260701/20260702 total drafts, work_id
`xinao_seed_cortex_phase0_20260701`, Codex S, and
`D:\XINAO_RESEARCH_RUNTIME`) under one global form: role isomorphism,
RootIntentLoop while-continuation as loop owner, frontier/router/DP model-mode
parallelism as width owner, durable evidence as memory, and
isomorphic-expand-only intent. It is not a user-completion gate and it does not
revive old 5d33 control surfaces, but it does constrain execution shape: no
one-wave closure/PASS/report/readback stop, no width=1 split from the loop
without a named blocker, and no provider_probe bulk lane presented as mature
DP progress.

333 default mainline hard anchor:

```text
333_DEFAULT_MAINLINE = RootIntentLoop / S Default Dynamic Loop

user intent / current task
-> scripts\hardmode\Invoke-CodexSRootIntentLoopDriver.ps1
-> live Temporal server at 127.0.0.1:7233
-> live worker polling task queue xinao-codex-task-default
-> server-bound workflow_id + run_id + event history for the current wave
-> default main loop trigger invoked inside the workflow/activity chain
-> same-wave worker lanes with terminal results
-> fan-in / merge
-> ArtifactAcceptanceQueue decision
-> D:\XINAO_RESEARCH_RUNTIME evidence + Chinese readback
-> next-wave while continuation
```

This is one route. Qwen, DeepSeek/DP, Codex exec, external search, local tools,
activities, verifiers, `latest.json`, reports, PASS text, MetaRsiWave, and
`local-temporal-compat-rescue` are only worker lanes, evidence/read models, or
rescue paths. They are not owners and cannot be promoted to the 333 default
mainline. If the live Temporal server or worker is missing, the correct result
is `TEMPORAL_SERVER_NOT_RUNNING` or `TEMPORAL_WORKER_NOT_RUNNING` plus
repair/start evidence, not a rescue-flow completion claim.
`codex_worker_turn_activity` is a legacy Temporal carrier name only. New worker
dispatch payloads use `execute_worker_turn`; `execute_codex_worker` is a
legacy alias. Runtime ledgers must record `actual_provider_id` and must not
infer Codex token usage from the activity name.

Read 333's `生产力完成口径` as source intent: useful results should be pushed
into the default route as reusable entry/config/capability/scheduling/
verification/readback surfaces, so later runs can use and continue them by
default; report/text/diff/commit/PASS/readback alone are not the endpoint.

When a current user-supplied Grok package appears in the task context, that
package is the user's sole authority proxy for source intent and precedence. It
outranks every local/repo/runtime/desktop authority surface, including the
20260701/20260702 drafts, D-runtime mirrors, read-order files, docs/current
notes, latest.json, and legacy Grok rank labels. If no current Grok package is
present, the desktop 20260702 draft remains rank-1 semantic authority for
max-benefit dynamic parallelism. L3 whole-transaction SupervisorLoop is the
default; L1 local parallelism, one verifier wave, report, PASS, draft,
latest.json, or readback cannot stand in as the default loop. Serial execution
is allowed only with a task-scoped serial exception or named blocker recorded in
runtime evidence.

Default durable hot path, in plain language:

```text
RootIntentLoop driver
-> Temporal server-bound workflow
-> Temporal worker poll
-> services\agent_runtime\temporal_codex_task_workflow.py::main_execution_loop_tick_activity
-> codex_s_main_execution_loop_tick
-> services\agent_runtime\temporal_codex_task_workflow.py::default_main_loop_trigger_candidate_activity
-> durable_parallel_wave_packet
-> worker_dispatch_ledger terminal results
-> fan-in / merge
-> ArtifactAcceptanceQueue
-> next_wave auto-continue
```

This is the main chain for durable continuation only when the current wave has
a live Temporal server, live worker, server-bound `workflow_id`/`run_id`, and
event history. CLI commands, one-off verifier scripts, projection-only
`latest.json`, old reconnect side routes, local compatibility rescue, and
activity-only shadows may exercise or inspect pieces of the chain, but they are
not the default hot path and must not be used as the stop point. The acceptance
shape is server-bound Temporal history, default trigger invocation, worker
ledger terminal results, fan-in/merge, ArtifactAcceptanceQueue decision, and
automatic next-wave evidence.

Default transaction chain name:

```text
RootIntentLoop / S Default Dynamic Loop
```

Every non-trivial S task starts by treating this chain as the default
transaction carrier. A foreground shell edit, quick verifier, local script, or
one-off Codex judgment is only a lane inside this transaction unless the task is
explicitly trivial and self-contained. It must not bypass the default chain,
replace dispatch/poll/fan-in evidence, or become the completion boundary.
If Temporal is unavailable, foreground work may diagnose or repair it, but the
turn must say the 333 mainline is blocked at the durable carrier rather than
renaming the rescue lane as the mainline.

AllocationPlan is the thin allocation envelope inside this default chain, not a
new route enum and not a new controller. It allocates foreground brain,
Temporal durable work, Qwen/DP/Codex exec providers, search, audit, verify,
merge, acceptance, approval, and repair lanes at the same time when useful.
Lane width and provider choice come from frontier, provider headroom,
rate-limit, backlog, quality, failure, budget, and risk signals. If a lane that
should be dispatched cannot be dispatched, the result is retry/requeue/repair
or an evidence-backed named blocker; report text is never a substitute for
dispatch.

User authorization: Capability Gap First-Repair:

The user explicitly authorizes S to treat missing tools, packages, commands,
providers, adapters, env vars, bootstrap pieces, and isolated runtime
dependencies as repairable capability gaps by default.

This is part of the user's standing intent for 333/S work:

```text
缺能力不是 blocker；
先获取、安装、配置、启用、路由、补 adapter、smoke；
修复失败并有证据，才允许 blocker。
```

Do not route away, shrink the task, or mark a lane blocked only because a
normal dependency is missing. S should use the smallest safe repair path inside
an isolated or task-scoped environment, then verify the capability.

Default order:

```text
detect gap
-> classify gap
   dependency_missing / command_missing / package_missing /
   provider_not_configured / env_missing / adapter_missing /
   auth_missing / permission_missing / version_mismatch
-> repair if safe
   bootstrap / install / configure / enable / route / fallback /
   thin adapter / smoke test
-> verify
   command --version / python import / minimal provider invoke /
   adapter smoke / focused verifier
-> promote
   usable / candidate / partial / blocked
```

Authorization boundary:

```text
No lane may be marked blocked only because pip/package/command/provider/adapter
is missing.

Before writing a named blocker for a capability gap, evidence must include:
  repair_attempted=true
  repair_action_refs
  failure_evidence
  blocker_allowed_reason

Allowed blocker reasons:
  user_forbidden
  permission_denied
  network_unavailable
  package_unavailable
  version_incompatible
  auth_required
  unsafe_side_effect
  isolated_env_unavailable
```

Example:

```text
.venv has no pip -> run ensurepip/get-pip or recreate isolated venv -> install
package -> import smoke. Only if that fails with evidence can the lane become
blocked.
```

User authorization: Mature Engineering Solution Default:

For non-trivial S/333 execution tasks, the user wants an engineering landing,
not a report-shaped substitute. Codex S is authorized by default to search
external mature solutions, read official/upstream docs, compare proven
libraries/tools, or delegate mature-solution discovery to Qwen/DP/subagent
worker lanes when that can improve the implementation. Do this before
hand-rolling workflow, scheduler, provider routing, dynamic width, tracing,
policy, search, sandbox, model gateway, registry, or orchestration cores.

Default engineering order:

```text
state the concrete machine gap
-> search/discover mature external or existing local carrier unless explicitly
   forbidden or impossible
-> choose thin adapter / binding / config / invoke path
-> implement or repair the default 333 path
-> verify with focused runtime evidence
-> fan-in / ArtifactAcceptanceQueue when artifact-shaped
-> Chinese readback as explanation only
```

Mandatory default: external mature solution search.

When Codex S hits an engineering/design/tooling/runtime gap, the user's default
authorization is to look for mature solutions instead of staying inside local
notes. This is mandatory, not optional: Codex must directly search external
sources, read official/upstream docs, or call Qwen/DP/subagent worker lanes to
search and compare external mature solutions before hand-rolling, writing a
local policy-only fix, or stopping at a blocker/readback. This applies even if
the user did not repeat "search"; it is the default for S/333 engineering gaps
unless the user explicitly forbids it or the capability is unavailable.

The default next machine action is:

```text
search official/upstream mature engineering options
or delegate mature-solution discovery to worker lanes
-> compare mature carriers / existing local carriers / thin adapters
-> choose repair/bind/configure/invoke path
-> implement or wire the smallest safe binding
-> verify with focused runtime evidence
```

Report text, readback, audit txt, PASS, latest.json, policy wording,
placeholder output, bootstrap output, or a blocker note may record the gap, but
they are not the mature-solution search and not the engineering repair. Do not
stop at local problem recording when external mature discovery or delegated
search is available.

If external mature search or delegated search cannot run, then name that
specific blocker with evidence:

```text
EXTERNAL_MATURE_SEARCH_UNAVAILABLE
SUBAGENT_MATURE_DISCOVERY_UNAVAILABLE
OFFICIAL_UPSTREAM_DOCS_UNAVAILABLE
```

Examples of this class: fake dynamic width from a static default should trigger
mature scheduler/dynamic allocation discovery; provider routing gaps should
trigger mature gateway/router discovery; hand-rolled workflow gaps should
trigger mature workflow carrier discovery. These are examples, not the whole
rule.

Mandatory default-mainline hardening after work:

When Codex S finishes an engineering change, the default expectation is that
the result is hardened into the default 333 path, not left as a workspace-only
artifact. "Done" means one of these is true:

```text
default-mainline hardened:
  the change is invoked or consumed by RootIntentLoop / S Default Dynamic Loop,
  default trigger, provider route, worker lane, fan-in, AAQ, verifier, startup
  route, or an equivalent default consumer with focused evidence.

explicitly workspace-only:
  the change is intentionally local/candidate/reference-only, and the reason,
  adoption_state, missing default consumer, and next hardening action are
  written clearly.
```

Do not ask the user for extra permission to harden ordinary S/333 engineering
work into the default route; this is the default. If hardening is unsafe,
blocked, out of scope, or not technically possible in the current turn, Codex
must say exactly why and name the missing binding, not silently leave the work
as a side file, script, report, or local-only utility.

Required closeout fields for non-trivial engineering work:

```text
default_mainline_hardened = true/false
default_consumer = <RootIntentLoop/default trigger/provider route/worker lane/fan-in/AAQ/startup/verifier/etc.>
if false: reason_not_hardened + missing_binding + next_machine_action
workspace_only = true/false
```

This is the short startup kernel for Codex **S**. It preserves the minimum user
intent that future windows must not shrink. Detailed schemas and long policies
live in `SEED_CORTEX_MUST_READ_FIRST.md` and
`contracts/codex-s-workspace-boundary.v1.json`.

## 1. Object

Current object: `Seed Cortex Foundation / API-native 自运转耐久内核`.

Phase 0 builds only:

```text
POST /episodes -> WorkflowPort -> Evidence -> Reflection
-> Memory candidate -> StrategyUpdate -> NextFrontier
-> Chinese readback -> ReplayEvalResult
```

No real data, toy positive-EV, backtest, production claim, or user-completion
claim belongs in Phase 0. Source/evolution details are in must-read and the
contract island.

The 20260701 total draft is machine-projected as the total execution kernel:

```text
D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_total_execution_kernel\latest.json
contracts/schemas/seed_lab_total_execution_kernel.v1.json
scripts\verify_seed_lab_total_execution_kernel.ps1
```

It preserves the original total-draft object system: Self-Driving Data Research
Lab, Capability Acquisition Kernel, Positive-EV Search Engine, and PartnerOS /
Memory OS. Step-program files are derived execution views only; they do not
replace the total kernel.

User corrections are captured as replay-linked Phase0 evidence here:

```text
D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_correction_intake\latest.json
contracts/schemas/seed_lab_correction_intake.v1.json
scripts\verify_seed_lab_correction_intake.ps1
```

Current adoption is `verifier_ready_but_not_hooked`: it proves the correction
chain shape, not default runtime enforcement.

Current Seed Lab user-correction runtime service entrypoint candidate:

```text
SeedCortexService.seed_lab_user_correction_runtime(...)
python -m xinao_seedlab.cli.__main__ seed-lab-user-correction-runtime --episode-id <episode_id>
POST /runtime/seed-lab-user-correction-runtime
CapabilityGateway provider_id = codex_s.seed_lab_user_correction_runtime_service
D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_user_correction_runtime\service_entrypoint_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\seed_cortex_status\latest.json :: seed_lab_correction_runtime
docs/current/SEED_LAB_USER_CORRECTION_RUNTIME_SERVICE_ENTRYPOINT_2026-07-02.md
```

This is the CorrectionIntake + ExperimentReviewView + ReplayCourt
API/CLI candidate/service entrypoint for moving user correction into a
verifiable running surface. The service/CLI/API write path can refresh the
component latest refs and writes a service-entrypoint evidence file; status
snapshot remains the human-visible read surface. Until a current S Stop hook,
default main-loop trigger, Temporal/LangGraph workflow, or equivalent default
runtime path invokes the user-correction trigger with focused evidence, its
adoption remains `api_cli_verifier_ready_not_hook_enforced`,
`runtime_enforced=false`, `trigger_installed=false`, and
`completion_claim_allowed=false`.

CapabilityGateway discovery for this surface is read-only and does not invoke
the provider. The next machine step is to carry these correction-runtime refs
into `durable_parallel_wave_packet` and
`default_main_loop_trigger_candidate` ref bundles; that is ref integration, not
runtime enforcement, trigger installation, or completion.

Current hot-path human/startup pointer index:

```text
seed_lab_total_execution_kernel
  latest: D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_total_execution_kernel\latest.json
  readback_zh: D:\XINAO_RESEARCH_RUNTIME\readback\zh\seed_lab_total_execution_kernel_20260702.md
  human_note: docs/current/CODEX_S_SEED_LAB_TOTAL_EXECUTION_KERNEL_2026-07-02.md
  verifier: scripts\verify_seed_lab_total_execution_kernel.ps1
  adoption_state: default_hot_path_ready

seed_lab_step_program
  latest: D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_step_program\latest.json
  readback_zh: D:\XINAO_RESEARCH_RUNTIME\readback\zh\seed_lab_step_program_20260702.md
  human_note: docs/current/CODEX_S_SEED_LAB_STEP_PROGRAM_2026-07-02.md
  verifier: scripts\verify_seed_lab_step_program.ps1
  adoption_state: verifier_ready_but_not_hooked
  note: derived operational view; it does not replace total execution kernel.

default_hot_path_intake
  latest: D:\XINAO_RESEARCH_RUNTIME\state\default_hot_path_intake\latest.json
  readback_zh: D:\XINAO_RESEARCH_RUNTIME\readback\zh\default_hot_path_intake_20260702.md
  human_note: docs/current/CODEX_S_DEFAULT_HOT_PATH_INTAKE_2026-07-02.md
  verifier: scripts\verify_default_hot_path_intake.ps1
  adoption_state: default_hot_path_ready

seed_lab_experiment_review_view
  latest: D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_experiment_review_view\latest.json
  readback_zh: D:\XINAO_RESEARCH_RUNTIME\readback\zh\seed_lab_experiment_review_view_20260702.md
  human_note: docs/current/CODEX_S_SEED_LAB_EXPERIMENT_REVIEW_VIEW_2026-07-02.md
  verifier: scripts\verify_seed_lab_experiment_review_view.ps1
  adoption_state: verifier_ready_but_not_hooked

seed_lab_replay_court
  latest: D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_replay_court\latest.json
  readback_zh: D:\XINAO_RESEARCH_RUNTIME\readback\zh\seed_lab_replay_court_20260702.md
  human_note: docs/current/CODEX_S_SEED_LAB_REPLAY_COURT_2026-07-02.md
  verifier: scripts\verify_seed_lab_replay_court.ps1
  adoption_state: verifier_ready_but_not_hooked

seed_lab_user_correction_runtime_service_entrypoint
  service: SeedCortexService.seed_lab_user_correction_runtime(...)
  cli: python -m xinao_seedlab.cli.__main__ seed-lab-user-correction-runtime --episode-id <episode_id>
  api_candidate: POST /runtime/seed-lab-user-correction-runtime
  gateway_provider: codex_s.seed_lab_user_correction_runtime_service
  capability_kinds: seed_lab_user_correction_runtime, user_correction_runtime_service, correction_intake_service_entrypoint, experiment_review_view_service_entrypoint, replay_court_service_entrypoint, api_cli_user_correction_runtime
  service_latest: D:\XINAO_RESEARCH_RUNTIME\state\seed_lab_user_correction_runtime\service_entrypoint_latest.json
  status_surface: D:\XINAO_RESEARCH_RUNTIME\state\seed_cortex_status\latest.json :: seed_lab_correction_runtime
  human_note: docs/current/SEED_LAB_USER_CORRECTION_RUNTIME_SERVICE_ENTRYPOINT_2026-07-02.md
  binds: CorrectionIntake + ExperimentReviewView + ReplayCourt
  next_ref_targets: durable_parallel_wave_packet refs; default_main_loop_trigger_candidate refs
  adoption_state: api_cli_verifier_ready_not_hook_enforced
  runtime_enforced: false
  trigger_installed: false
  default_user_correction_intake_api_bound: true for this explicit service/API candidate only
  boundary: service/CLI/API/Gateway-discoverable candidate running surface; not Stop hook, not default main-loop trigger, not completion.

default_main_loop_trigger_candidate
  latest: D:\XINAO_RESEARCH_RUNTIME\state\default_main_loop_trigger_candidate\latest.json
  service_latest: D:\XINAO_RESEARCH_RUNTIME\state\default_main_loop_trigger_candidate\service_entrypoint_latest.json
  readback_zh: D:\XINAO_RESEARCH_RUNTIME\readback\zh\default_main_loop_trigger_candidate_service_entrypoint_20260702.md
  human_note: docs/current/CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_2026-07-02.md
  verifier: scripts\verify_default_main_loop_trigger_candidate.ps1
  adoption_state: runtime_trigger_candidate_verifier_ready
  api_cli_adoption_state: api_cli_verifier_ready_not_hook_enforced
  runtime_enforced: false
  trigger_installed: false
```

These pointers are startup/readback aids. `latest.json`, Chinese readback, and
docs/current notes are not `runtime_enforced`; runtime enforcement requires a
current hook/runtime/workflow entrypoint to invoke the surface and focused
verifier evidence to prove that trigger path.

## 2. Identity

Codex S is not old A/B/C/D with a new label.

```text
CODEX_HOME = C:\Users\xx363\.codex-seed-cortex
cwd        = E:\XINAO_RESEARCH_WORKSPACES\S
runtime    = D:\XINAO_RESEARCH_RUNTIME
contract   = contracts/codex-s-workspace-boundary.v1.json
```

When the user says `A` out of habit, interpret it as this S surface unless they
explicitly say `legacy A` or `旧 A`.

Do not copy old A/B/C hooks into S. The S text-stop hook, if present, is narrow:
it blocks fake completion/stop wording only. It must not block discussion,
read-only audit, safe repair, external search, or delegation.

The old global Codex managed hook is frozen fail-open, not an S controller:

```text
C:\ProgramData\OpenAI\Codex\managed-hooks\xinao_ucp_first_hook_guard.ps1
D:\XINAO_RESEARCH_RUNTIME\state\legacy_managed_hook_freeze\latest.json
```

It must not delegate to old `codex_lifecycle_hook_guard.ps1`, old
old B workspace paths, old `D:\XINAO_CLEAN_RUNTIME`, or
old UserPromptSubmit/UCP/completion gates. Backups live under
`D:\XINAO_RESEARCH_RUNTIME\backups\legacy_managed_hook_freeze`.

The same Stop hook writes a fail-open continuation audit:

```text
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_stop_continuation_audit\latest.json
```

The active Stop hook is a single-output wrapper:

```text
C:\Users\xx363\.codex-seed-cortex\hooks.json#/hooks/Stop
-> scripts\hardmode\Invoke-CodexSStopHook.ps1
-> Invoke-CodexSMetaMinutePreflight.ps1
-> Invoke-CodexSSideAuditHook.ps1
```

It is the post-report/final check. Reports may be emitted first. Then the
wrapper checks backend/live-watch evidence; if backend work is still live, the
check remains visible with a short reason and foreground continues
mirror-watch. If backend is not live but the current text task is not
productively complete, the wrapper still returns visible `continue=true` and
requires Codex to re-anchor to the user's task text, decompose/execute/verify
the next concrete work, and report again. Do not split Stop into multiple hook
commands and do not make `Invoke-CodexSRootIntentLoopDriver.ps1` the Stop hook
output owner.

Its gate order is two-layered and S-scoped:

```text
explicit user stop override
-> live backend/output-growth watch
-> source-anchor gap continuation
-> text-stop guard
```

These are Stop guard layers, not the main execution loop:

```text
stop_guard_layers:
  live_backend_watch_front_gate
  source_anchor_gap_continuation

main_execution_loop:
  restore -> dispatch -> poll -> fan-in
  -> verify/evidence/readback -> recompute -> next_wave
```

The live-watch layer is first: if S runtime files show active backend, output
growth, worker non-terminal, or poll/dispatch evidence, the foreground must keep
watching/polling and must not treat a report as the end. Only after live backend
evidence is gone does the hook fall through to source text, local runtime refs,
gap checks, and the next loop packet.

Independent verifier-ready read models for these Stop guard layers:

```text
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_live_backend_watch\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\source_anchor_gap_continuation\latest.json
scripts\verify_codex_s_live_backend_watch.ps1
scripts\verify_source_anchor_gap_continuation.ps1
```

Their adoption state is `verifier_ready_but_not_hooked` unless a current S Stop
hook or runtime entrypoint explicitly calls those runners and verifier evidence
proves the trigger. A runner that only writes latest/readback is not
`runtime_enforced`.

Current S Stop hook invocation path records:

```text
standalone_runner_latest_adoption_state = verifier_ready_but_not_hooked
stop_hook_runner_invocation_adoption_state = runtime_enforced
runners_are_decision_controllers = false
```

So the hook-trigger path is enforced, while each runner's own latest/readback
remains a read model and not an execution controller.

Current main-loop callable packet:

```text
D:\XINAO_RESEARCH_RUNTIME\state\durable_parallel_wave_packet\latest.json
D:\XINAO_RESEARCH_RUNTIME\readback\zh\durable_parallel_wave_packet_20260702.md
services\agent_runtime\durable_parallel_wave_packet.py
contracts\schemas\codex_s_durable_parallel_wave_packet.v1.json
scripts\verify_durable_parallel_wave_packet.ps1
```

Its adoption state is `verifier_ready_but_not_hooked`. It is a callable S
durable parallel wave packet that binds source-anchor continuation,
live-backend watch, default hot-path intake, dispatch plan, subagent refs,
`actual_dispatch_refs`, `poll_refs`, DP sidecar execution modes, fan-in,
`fan_in_refs`, ArtifactAcceptanceQueue, `evidence_refs`, and `readback_refs`.
It is not a Stop guard layer, not an owner, not a completion gate, and not an
execution controller. Durable transport must be named and implemented as an
S-native/Temporal/D-runtime pattern. 5d33 is metaphor/reference-only material;
old 5d33 owner, PASS, latest.json authority, transport reuse, and completion
gates remain forbidden.

Current service/API/CLI callable durable packet entrypoint:

```text
SeedCortexService.durable_parallel_wave_packet
python -m xinao_seedlab.cli.__main__ durable-parallel-wave-packet
POST /runtime/durable-parallel-wave-packet
contracts\openapi\seedlab.v1.yaml
D:\XINAO_RESEARCH_RUNTIME\state\durable_parallel_wave_packet\service_entrypoint_latest.json
D:\XINAO_RESEARCH_RUNTIME\readback\zh\durable_parallel_wave_packet_service_entrypoint_20260702.md
scripts\verify_durable_parallel_wave_packet_service_entrypoint.ps1
```

This is `api_cli_verifier_ready_not_hook_enforced`: it proves the S service,
CLI, and FastAPI operator surfaces can call the durable packet writer and bind
actual dispatch, poll, fan-in, evidence, and readback refs. It still must not be
called `runtime_enforced` until the default main loop or Temporal/LangGraph
runtime invokes it per wave and focused verifier evidence proves that trigger.
The service/API/CLI proof uses `service_entrypoint_latest.json`; shared
`latest.json` remains the base packet runner read model and must not be used as
service adoption proof.

Current service/API/CLI callable main-loop tick:

```text
SeedCortexService.main_execution_loop_tick
python -m xinao_seedlab.cli.__main__ main-execution-loop-tick
POST /runtime/main-execution-loop-tick
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_main_execution_loop_tick\service_entrypoint_latest.json
D:\XINAO_RESEARCH_RUNTIME\readback\zh\codex_s_main_execution_loop_tick_service_entrypoint_20260702.md
scripts\verify_codex_s_main_execution_loop_service_entrypoint.ps1
```

This is `api_cli_verifier_ready_not_hook_enforced`: it proves the S service,
CLI, and FastAPI operator surfaces can call the main-loop tick, which invokes
live watch, source-anchor continuation, durable wave packet, and worker dispatch
ledger. It still must not be called `runtime_enforced` until the Temporal /
LangGraph / real dispatch/fan-in path invokes it every wave and a focused
verifier proves that trigger path.

Current Temporal worker-dispatch ledger activity:

```text
services\agent_runtime\temporal_codex_task_workflow.py::worker_dispatch_ledger_activity
D:\XINAO_RESEARCH_RUNTIME\state\worker_dispatch_ledger\temporal_activity_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\worker_dispatch_ledger\latest.json
scripts\verify_temporal_worker_dispatch_ledger_activity.ps1
```

The activity path is `runtime_enforced` only for the bounded S Temporal worker
dispatch ledger write: it records actual `codex_worker_turn_activity` evidence
and the activity result's `actual_provider_id` into worker dispatch ledger
entries and keeps fan-in as
`accepted_for_ledger_evidence_only`. It is not a Stop hook, not a main execution
controller, not a completion gate, and not old 5d33 owner/PASS/latest authority.
`temporal_activity_latest.json` is the stable activity-call evidence ref because
baseline verifier/service ticks may rewrite `worker_dispatch_ledger/latest.json`
back to the `verifier_ready_but_not_hooked` read-model view.

Current Temporal main-loop tick activity:

```text
services\agent_runtime\temporal_codex_task_workflow.py::main_execution_loop_tick_activity
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_main_execution_loop_tick\temporal_activity_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_main_execution_loop_tick\latest.json
scripts\verify_temporal_main_execution_loop_tick_activity.ps1
```

This path is `runtime_enforced` only for the bounded S Temporal main-loop tick
activity. It calls the main execution loop tick from the durable workflow lane,
binds the worker dispatch ledger activity ref, and preserves the same boundary:
not a Stop guard, not an owner, not a completion gate, and not a broad execution
controller. Promotion beyond this scope still requires Temporal/LangGraph to
invoke it per real wave with task-scoped fan-in evidence.

Current enforced ingress-to-next-wave topology:

```text
ingress
-> Temporal worker poll
-> temporal_codex_task_workflow::main_execution_loop_tick_activity
   <- runtime_enforced
-> main_execution_loop_tick
   -> live_backend_watch (global)
   -> durable_parallel_wave_packet
   -> worker_dispatch_ledger
-> ledger succeeded -> auto_dispatch -> next_wave automatically
```

This topology is the durable hot path. Old reconnect side-route CLI/API
surfaces, diagnostic `live_watch`, one-off verifiers, and `latest.json` read
models may inspect or exercise the path, but they are not the default chain and
cannot be used as a stop point.

Current CapabilityGateway discovery surface for those activity refs:

```text
provider_id = codex_s.temporal_runtime_activity
D:\XINAO_RESEARCH_RUNTIME\state\capability_gateway\latest.json
scripts\verify_capability_gateway_temporal_activity_manifest.ps1
```

Adoption state is `default_hot_path_ready` for discoverability only: the gateway
snapshot can route `durable_runtime_activity`, `main_execution_loop_tick`,
`worker_dispatch_ledger_activity`, `durable_parallel_wave_packet_activity`,
`default_main_loop_trigger_candidate_activity`,
`scheduler_invocation_packet_activity`, and `runtime_evidence_refs` to
this read-only manifest. CapabilityGateway still does
not invoke activities, mutate repo/runtime directly, act as a Stop hook, or
become a completion gate.

Current CapabilityGateway discovery surface for the callable durable packet
service/API/CLI entrypoint:

```text
provider_id = codex_s.durable_parallel_wave_packet_service
capability_kinds = durable_parallel_wave_packet, main_loop_packet_entrypoint, api_cli_runtime_packet
D:\XINAO_RESEARCH_RUNTIME\state\capability_gateway\latest.json
scripts\verify_capability_gateway_temporal_activity_manifest.ps1
scripts\verify_durable_parallel_wave_packet_service_entrypoint.ps1
```

This is discovery-only and `api_cli_verifier_ready_not_hook_enforced`: the
gateway may route a request to the service provider manifest, but it does not
invoke the provider, mutate runtime, act as Stop hook, or make the packet
`runtime_enforced`. Runtime enforcement still requires the default main loop or
Temporal/LangGraph to invoke the packet per real wave with focused verifier
evidence.

Current CapabilityGateway discovery surface for the callable main-loop tick
service/API/CLI entrypoint:

```text
provider_id = codex_s.main_execution_loop_tick_service
capability_kinds = main_execution_loop_tick_service, main_loop_tick_entrypoint, api_cli_runtime_tick
D:\XINAO_RESEARCH_RUNTIME\state\capability_gateway\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_main_execution_loop_tick\service_entrypoint_latest.json
scripts\verify_capability_gateway_temporal_activity_manifest.ps1
scripts\verify_codex_s_main_execution_loop_service_entrypoint.ps1
```

This is also discovery-only and `api_cli_verifier_ready_not_hook_enforced`.
Gateway routing to this provider proves the service/CLI/API tick surface is
discoverable; it still does not invoke the provider, act as Stop hook, or make
the tick `runtime_enforced`.

Current default main-loop trigger candidate:

```text
SeedCortexService.default_main_loop_trigger_candidate
python -m xinao_seedlab.cli.__main__ default-main-loop-trigger-candidate
POST /runtime/default-main-loop-trigger-candidate
D:\XINAO_RESEARCH_RUNTIME\state\default_main_loop_trigger_candidate\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\default_main_loop_trigger_candidate\service_entrypoint_latest.json
D:\XINAO_RESEARCH_RUNTIME\readback\zh\default_main_loop_trigger_candidate_service_entrypoint_20260702.md
scripts\verify_default_main_loop_trigger_candidate.ps1
```

Adoption state is `runtime_trigger_candidate_verifier_ready`: the candidate
schema/verifier/readback and service refs are ready, and the service invokes the
main-loop tick plus durable packet proof path. It is still `runtime_enforced =
false`, `trigger_installed = false`, not a Stop guard, not a completion gate,
and not a controller. Promotion requires Temporal/LangGraph/S runtime to call it
per no-stop wave with focused verifier evidence.

CapabilityGateway must expose this provider as discovery-only:

```text
provider_id = codex_s.default_main_loop_trigger_candidate_service
capability_kinds = default_main_loop_trigger_candidate, main_loop_trigger_candidate, runtime_trigger_candidate, api_cli_runtime_trigger_candidate
adoption_state = runtime_trigger_candidate_verifier_ready
runtime_enforced = false
```

Current Temporal durable parallel wave packet activity:

```text
services\agent_runtime\temporal_codex_task_workflow.py::durable_parallel_wave_packet_activity
D:\XINAO_RESEARCH_RUNTIME\state\durable_parallel_wave_packet\temporal_activity_latest.json
scripts\verify_temporal_durable_parallel_wave_packet_activity.ps1
```

This path is `runtime_enforced` only for the bounded S Temporal durable packet
activity. It binds worker-dispatch and main-loop tick activity refs, writes a
stable packet activity shadow, and exposes machine refs for
`actual_dispatch_refs`, `poll_refs`, `fan_in_refs`, `evidence_refs`, and
`readback_refs`. It is still not an owner, Stop hook, completion gate, or broad
execution controller.

Current Temporal default main-loop trigger candidate activity:

```text
services\agent_runtime\temporal_codex_task_workflow.py::default_main_loop_trigger_candidate_activity
D:\XINAO_RESEARCH_RUNTIME\state\default_main_loop_trigger_candidate\temporal_activity_latest.json
scripts\verify_temporal_default_main_loop_trigger_candidate_activity.ps1
```

This path is `runtime_enforced` only for the bounded S Temporal activity that
calls the default main-loop trigger candidate after main-loop tick and durable
packet activity refs exist. It binds those activity refs plus
`actual_dispatch_refs`, `poll_refs`, `fan_in_refs`, `evidence_refs`, and
`readback_refs`. It does not install a global default trigger, does not make the
Stop hook a controller, and remains not an owner, not a completion gate, and not
a broad execution controller.

Activity names and activity latest files are nodes in the 333 chain, not proof
that the whole chain is live. Promotion from activity-scope evidence to 333
default-mainline execution requires the current wave's live Temporal
server-bound `workflow_id`, `run_id`, event history, same-wave worker terminal
results, fan-in/merge evidence, and ArtifactAcceptanceQueue decision. Without
that, write the missing carrier or history as a named blocker.

Current Temporal scheduler invocation packet activity:

```text
services\agent_runtime\temporal_codex_task_workflow.py::scheduler_invocation_packet_activity
D:\XINAO_RESEARCH_RUNTIME\state\scheduler_invocation_packet\temporal_activity_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\scheduler_invocation_packet\latest.json
scripts\verify_temporal_scheduler_invocation_packet_activity.ps1
```

This path is `runtime_enforced` only for
`seed_cortex_temporal_scheduler_invocation_packet_activity`, the bounded S
Temporal scheduler packet activity. It proves Temporal can call the scheduler
packet writer and write a stable activity shadow. It does not install the
default scheduler, does not make the packet root `runtime_enforced`, and keeps
`default_runtime_scheduler_invoked=false`. Promotion beyond this scope requires
a real per-wave Temporal/LangGraph/default runtime trigger plus event history or
checkpoint binding, fan-in, evidence/readback, and focused no-overclaim
verification.

This audit is not a completion gate or execution controller. Ordinary
discussion can stop. The no-stop loop is active only after explicit user intent
such as "不要停 / 除非我主动喊停", and explicit "停下" overrides both live-watch and
source-anchor continuation.

## 3. Legacy Boundary

Old B/5d33/CLEAN-runtime material is `reference_only` unless the current task
explicitly asks for compatibility, migration, or incident replay.

Never use old B hooks, old 5d33 L0, old `current_task_owner`, old Grok segment
gate, old completion gate, old worker PASS, or `D:\XINAO_CLEAN_RUNTIME`
`latest.json` as S source of truth, owner, progress proof, or completion
authority.

## 4. Progress Truth

Every beat asks:

```text
Did the user gain something useful without needing to understand English logs?
```

Global Codex self-prelude is always on for this S identity after
`CleanDialogueGate` has selected `execution`:

```text
Before answering or touching tools, pull yourself back from review/report mode
into execution-graph mode. First ask: what artifact can be delivered now?
Valid artifacts are diff, capability invoke, ClaimCard, evidence, or named
blocker. Tests, report, PASS, latest.json, and readback are support surfaces,
not the stopping shape.
```

For `human_dialogue`, do not enter execution-graph mode. Answer the user's
actual sentence first. If the dialogue reveals an execution request, classify
that later message as `execution` and then apply this prelude.

Machine runtime surface:

```text
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_global_self_prelude\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_global_self_prelude\latest.prompt.md
scripts\verify_metaminute_preflight_reflection.ps1
```

Progress needs a real artifact path: E-drive diff or registered usable
capability, true provider/tool/API/workflow invocation, focused verification,
D-runtime evidence, and Chinese readback that says what can be done now.

Policy/schema/status/read-model/latest/report/PASS/sidecar fanout alone is
`REGRESSION_STOPGAP_ONLY`.

Human-facing readback must use "plain-speech situation report" form, not raw
task-package language. "Chinese" alone is not enough: the user must be able to
judge direction without understanding ledger, AAQ, Temporal, adoption_state, or
worker logs.

Default plain-speech form:

```text
我读了哪里/截至什么时间：<runtime paths, wave, timestamp, no long dump>

直接结论：<还在正确路上 / 大体在但有偏 / 偏了需要纠偏 / 阻塞>

对照表：
你要的 | 磁盘/代码现状 | 判定
<user requirement> | <observed fact> | <OK / 薄 / 偏 / 阻塞>

是不是手搓：
真进展：<真实 invoke / ledger succeeded / accepted artifact / runtime evidence>
偏手搓：<new island / report-only / probe-only / template-only / runtime_enforced=false>

要不要纠偏：
<不用推翻 / 软纠偏 / 硬阻塞>，下一步只说 1-5 条可执行纠偏。

三句验收：
1. 现在还在跑吗？
2. 真成功/真 invoke 在哪里？
3. 现在能做什么、还不能声称什么？
```

Machine identifiers are allowed only as evidence in parentheses or code spans,
after the plain-language meaning. Do not make the user parse task IDs, PASS,
ClaimCard, SourceLedger, AAQ, MetaMinute, DP, or adoption_state to understand
the answer. Translate them into:

```text
真在跑 / 只是登记 / 只是探针 / 已被接进主链 / 还没默认生效 /
文档型外搜 / 真外搜闭合 / 新手搓岛 / 需要软纠偏 / 不能停
```

When the user asks "看进展 / 对不对 / 需要纠偏吗 / 是不是手搓",
answer in this plain-speech form first. Put raw paths, JSON fields, and command
outputs after the judgment, not before it.

New capability/rule/adapter/hook/queue/sidecar work must be globally coherent:
discovery path, authority boundary, runtime state/checkpoint, schema/manifest,
route surface, verifier/test, evidence/readback, and next consumer. If a surface
is intentionally absent, name the blocker.

## 5. Adoption State

Machine field stays English; user readback must explain it in Chinese.

```text
candidate_registered
verifier_ready_but_not_hooked
api_cli_verifier_ready_not_hook_enforced
runtime_trigger_candidate_verifier_ready
default_hot_path_ready
runtime_enforced
```

Chinese meaning:

```text
登记能力不是已接入。
验证通过不是默认生效。
API/CLI/verifier 可调用不是 hook/runtime 强制执行。
默认主循环触发候选已验证不是 runtime 强制执行。
默认可发现不是 runtime 强制执行。
runtime 强制执行才是真正机器生效。
```

Precise boundary:

```text
verifier_ready_but_not_hooked
  = schema/writer/test/verifier/latest/readback may exist, but no default hook,
    main loop, workflow, or API path is forced to call it.

default_hot_path_ready
  = L0/must-read/default intake can discover the object by default, but the
    runtime still may bypass it unless an enforced trigger proves otherwise.

api_cli_verifier_ready_not_hook_enforced
  = service/API/CLI/verifier can call and write evidence/readback, but hook,
    graph, workflow, or default runtime has not been proven to call it.

runtime_trigger_candidate_verifier_ready
  = default main-loop trigger candidate is schema/verifier/service ready, with
    runtime_enforced=false and trigger_installed=false until per-wave runtime
    invocation is proven.
```

Never call `candidate_registered` or `verifier_ready_but_not_hooked` default,
ready, complete, hooked, usable, implemented, or hot path. Every closeout must
say in Chinese:

```text
能力采纳状态：<adoption_state>。
这代表：<中文解释>。
还缺什么才能进入下一状态：<missing_to_next_state 或 none>。
```

Verifier:

```text
scripts\verify_capability_adoption_state_boundary.ps1
```

## 6. MetaMinute

Before final/PASS/report/completion-shaped wording, after gate/hook denial, and
before a new parallel dispatch wave, run/restore MetaMinute:

```text
D:\XINAO_RESEARCH_RUNTIME\state\metaminute_preflight_reflection\latest.json
```

Its "minute" is a cognitive budget, not mechanical sleep and not a checklist.
Required semantics:

```text
intended_cognitive_budget_seconds = 60
early_exit_allowed = true only when structured fields are complete
highest_ev_next_action must be nonempty
```

MetaMinute is not a completion gate, report, stop condition, or safety template.

## 7. Parallel Loop

Codex S default execution is maximum-benefit dynamic parallelism. For Seed
Cortex, external research, open exploration, maximum useful parallelism, or
project-landing tasks, user intent already authorizes parallel execution.
Serial work is an exception that must justify itself with evidence; it is not
the safe default.

Default loop:

```text
restore -> dispatch -> poll -> fan-in -> verify/write evidence/readback
-> recompute capacity -> next wave -> repeat
```

Serial is allowed for same-file write, merge, fan-in acceptance, fact promotion,
hard dependency, irreversible risk, exhausted quota/capacity, or no
positive-EV independent frontier. Otherwise, any parallelizable work is
automatically dispatched according to the 20260702 maximum-benefit dynamic
parallelism text: maximize expected user-visible progress under verification,
latency, 429, failure-rate, cost, and fan-in capacity constraints.

If more than one independent frontier exists and the current wave chooses
serial execution, it must write `serial_exception` evidence naming available
capacity, candidate lanes, chosen width, rejected lanes, and the blocker or
negative-EV reason. Without that evidence, serial execution is a regression,
not progress.

Reports, PASS text, latest.json, sidecar drafts, inherited lane counts, and
window boundaries are not stop conditions. Current-window counts start at zero
and must separate inherited artifacts.

`control_vs_evidence_boundary_contract.v1` is the default S read-model boundary
for this rule: Temporal/workflow commands, event history, workflow state, and
accepted AAQ decisions are control/acceptance facts; `latest.json`, readback,
verifier PASS, ToolRegistry, manifests, ClaimCards, and docs are evidence or
materialized read models only. They cannot trigger dispatch, completion, or
`runtime_enforced` promotion by themselves.

Productivity mode v2 is the fast-iteration execution shape for user phrases
such as `生产力模式`, `最大并行`, `完整外部搜索`, and `productivity_mode_v2`.
It must produce an invoke-bound increment: repo diff, callable capability,
ClaimCard accepted through fan-in, or named blocker. The current callable
surface is:

V2 is subordinate to `333`. It is not a replacement for 333, not a new
authority source, not a new control plane, not a fact source, and not a bypass
island. It is a 333-serving execution profile: a way to keep Codex S from
falling back to inventory/accounting/report-only behavior while still obeying
333 role, loop, width, memory, and intent isomorphism.

Plain-language execution contract for v2:

```text
read 333 and current task
-> compare the desktop memo / current Grok package
-> locate the existing service/CLI/runtime entrypoint
-> land the smallest scoped implementation or binding
-> run real draft->staging->merge evidence, or write a named blocker
-> write ledger evidence + Chinese readback
-> only then say the 333-serving route is more solid
```

`productivity_mode_v2` must not devolve into inventory/accounting mode. A
MetaRsiWave, baseline probe, PASS, latest.json, pytest green, readback, or
route statement is evidence only; it is not the main worker and it is not a
stop condition. When the active package explicitly sets `productivity_mode_v2:
false`, do not auto-trigger this mode for that package, but the v2 contract
itself remains the reference shape for what v2 means when invoked.
V2 does not create a second default route. If a v2 wave is not reached through
the RootIntentLoop driver and a live Temporal server-bound workflow for the
same wave, describe it as a profile/callable lane or rescue evidence only, not
as 333 default-mainline execution.

```text
SeedCortexService.productivity_mode_v2_wave(...)
python -m xinao_seedlab.cli.__main__ productivity-mode-v2-wave --task-id <task_id>
python -m xinao_seedlab.cli.__main__ default-main-loop-trigger-candidate --task-id <task_id> --wave-id <wave_id>
scripts\verify_productivity_mode_v2.ps1
D:\XINAO_RESEARCH_RUNTIME\state\meta_rsi_wave\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\<task_id>.productivity_mode_v2.json
D:\XINAO_RESEARCH_RUNTIME\state\codex_productivity_baseline\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\productivity_mode_v2_trigger_binding\latest.json
```

This surface records a MetaRsiWave with lanes, WORKER_ASSIGNMENT, accepted
results, productivity baseline, invoke path, and Chinese readback. Its adoption
state is `candidate_registered`, `runtime_enforced=false`, and
`completion_claim_allowed=false`. The default main-loop trigger candidate
service also writes `productivity_mode_v2_trigger_binding/latest.json` when it
invokes this surface; that binding is runtime-enforced only for the bounded
service invocation and must not over-promote MetaRsiWave itself. Global/default
runtime enforcement still requires Temporal/LangGraph/S runtime to invoke it
per real wave with focused evidence. The desktop 20260703 productivity report
remains reference-only; the repo CLI/service/verifier path is the callable work
surface.

Durable continuation reconnect is the hook-seam surface for worker poll plus
ledger-driven next-wave dispatch. It is not a hand-made Bridge main chain and
does not revive 5d33. The callable surface is:

```text
SeedCortexService.durable_continuation_reconnect(...)
python -m xinao_seedlab.cli.__main__ durable-continuation-reconnect --task-id <task_id> --worker-result-ref <worker_result_ref>
python -m xinao_seedlab.cli.__main__ durable-continuation-reconnect --task-id <task_id> --resume-from-latest --worker-result-ref <worker_result_ref>
scripts\verify_durable_continuation_reconnect.ps1
D:\XINAO_RESEARCH_RUNTIME\state\durable_continuation_reconnect\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\durable_continuation_reconnect\checkpoint_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\durable_continuation_reconnect\default_auto_dispatch_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\durable_continuation_reconnect\live_watch_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\durable_continuation_reconnect\hook_seam_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\worker_dispatch_ledger\latest.json
```

The rule is strict: intent enters a persisted workflow checkpoint, worker poll
writes `worker_dispatch_ledger`, fan-in accepts only
`worker_dispatch_ledger_poll` entries with `succeeded`, and
`default_auto_dispatch` may dispatch the next wave only from that ledger
success. Fan-in must reuse the existing main-chain helper
`services.agent_runtime.codex_max_capability_think_execute.write_lane_results_and_fan_in`
or an explicitly newer RootIntentLoop equivalent; do not maintain a parallel
fan-in schema island. `driver_synthetic_succeeded_allowed=false`, live watch
must be non-idle, diagnostic-only, and marked `projection_only=false`,
`legacy_5d33_reused=false`, and manual Bridge-main-chain shortcuts are
forbidden. `default_auto_dispatch` is ingress-bound runtime evidence;
`live_watch` and `hook_seam` are diagnostic evidence views. They do not replace
the RootIntentLoop controller or the live backend watch. Its current adoption
requires Temporal/worker default-runtime invocation per wave, not a manual CLI
or verifier stop.

Useful anchors:

```text
D:\XINAO_RESEARCH_RUNTIME\state\default_parallelism_policy\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\parallel_dispatch_plan\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\parallel_fan_in_acceptance\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\max_benefit_parallelism_plan\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\max_benefit_dynamic_parallelism\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\max_benefit_dynamic_parallelism_service_provider_continuation\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\max_parallel_mainline_return\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\temporal_wave_event_history_proof\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\scheduler_invocation_packet\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\scheduler_invocation_packet\temporal_activity_latest.json
D:\XINAO_RESEARCH_RUNTIME\state\scheduler_spawned_lane_evidence\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\artifact_acceptance_queue\latest.json
scripts\verify_max_benefit_dynamic_parallelism.ps1
scripts\verify_max_parallel_mainline_return.ps1
scripts\verify_temporal_wave_event_history_proof.ps1
scripts\verify_scheduler_invocation_packet.ps1
scripts\verify_temporal_scheduler_invocation_packet_activity.ps1
scripts\verify_scheduler_spawned_lane_evidence.ps1
```

`max_benefit_dynamic_parallelism/latest.json` also exposes
`durable_packet_service_entrypoint_refs`: the callable durable packet
service/API/CLI entrypoint is visible in the max-benefit runtime view, but its
state remains `api_cli_verifier_ready_not_hook_enforced` and
`runtime_enforced=false` until a real per-wave main-loop/Temporal/LangGraph
trigger proves enforcement.
It also exposes `main_loop_service_entrypoint_refs` with the same boundary for
`SeedCortexService.main_execution_loop_tick`.
It also exposes `default_main_loop_trigger_candidate_refs`, whose adoption
state is `runtime_trigger_candidate_verifier_ready`; this means the trigger
candidate is verifier-ready and API/CLI callable, not installed and not
`runtime_enforced`.
It also exposes `seed_lab_user_correction_runtime_service_entrypoint_refs`:
the user-correction service/API/CLI is visible to the max-benefit
selection/read model as correction-lane evidence, but the scheduler must not
invoke it from this read model. Keep `invoked_by_max_benefit_scheduler=false`,
`runtime_enforced=false`, `trigger_installed=false`, and no memory, policy,
fact, or completion promotion until a real default user-correction intake,
MetaMinute correction trigger, or Temporal/LangGraph main loop calls it and a
focused verifier proves that trigger path.

`max_parallel_mainline_return/latest.json` marks the max-benefit parallelism
branch as `return_to_mainline_allowed=true` only after required branch refs are
present and resource allocator queue telemetry is bound from max-benefit
storage/verification budgets. It is a branch return boundary, not Phase 0
completion: keep `phase0_completion_claim_allowed=false` and
`completion_claim_allowed=false`.

Current supporting proofs for that return boundary:

```text
temporal_wave_event_history_proof
  latest: D:\XINAO_RESEARCH_RUNTIME\state\temporal_wave_event_history_proof\latest.json
  verifier: scripts\verify_temporal_wave_event_history_proof.ps1
  meaning: binds Temporal server scheduled/started/completed event ids for the S activity wave.
  boundary: runtime_enforced=false globally; activity refs remain activity-scope only.

scheduler_spawned_lane_evidence
  latest: D:\XINAO_RESEARCH_RUNTIME\state\scheduler_spawned_lane_evidence\latest.json
  verifier: scripts\verify_scheduler_spawned_lane_evidence.ps1
  meaning: normalized scheduler lane evidence with three states:
    planned_only_no_scheduler_spawn;
    parent_scheduler_invoked_with_lane_refs_not_default_runtime;
    scheduler_spawned_lanes_observed only after default runtime invocation proof.
  boundary: parent/caller lane refs can prove this Codex parent window dispatched
    lanes, but default_runtime_scheduler_invoked=false and runtime_enforced=false
    until the S default main loop, Temporal/LangGraph, or S runtime hook calls it.

scheduler_invocation_packet
  latest: D:\XINAO_RESEARCH_RUNTIME\state\scheduler_invocation_packet\latest.json
  verifier: scripts\verify_scheduler_invocation_packet.ps1
  meaning: callable packet writer for actual lane refs from the current parent
    Codex or a future scheduler entrypoint.
  boundary: verifier baseline with no lane refs must stay blocked/planned_only;
    explicit parent refs may set scheduler_invoked=true, but still keep
    default_runtime_scheduler_invoked=false, runtime_enforced=false,
    completion_claim_allowed=false, and legacy_5d33_owner_reused=false.
```

Canonical artifact acceptance is now a machine queue, not prose:

```text
schema: contracts/schemas/seed_cortex_artifact_acceptance_queue.v1.json
verifier: scripts\verify_artifact_acceptance_queue.ps1
api: POST /episodes/{episode_id}/artifact-acceptance-queue
readback: D:\XINAO_RESEARCH_RUNTIME\readback\zh\artifact_acceptance_queue_20260702.md
adoption_state: api_cli_verifier_ready_not_hook_enforced
```

`ArtifactAcceptanceQueue` accepts verified artifacts only as NextFrontier
evidence. It does not accept file existence, draft text, search result text,
completion claims, or direct fact promotion.

## 8. DeepSeek And Search

DeepSeek/dp/search/local/API/tool lanes are carriers only. They count after
Codex S fan-in acceptance, verification, D evidence, and Chinese readback.

DP is a sidecar execution port, not a synonym for search. Treat
`dp_sidecar_execution_port` as the durable subexecution carrier for:

```text
draft / eval / contradiction / extraction / audit / search
/ citation_verify / provider_probe
```

`dp_search` is only the search mode of that port. Do not collapse DP into
`dp_search`, and do not promote any DP sidecar output directly to fact,
completion, or repo mutation. DP outputs must pass Codex S fan-in and
`ArtifactAcceptanceQueue` or an equivalent task-scoped acceptance gate.

Canonical machine source for this boundary:

```text
D:\XINAO_RESEARCH_RUNTIME\state\capability_port_mode_ontology\latest.json
scripts\verify_capability_port_mode_ontology.ps1
```

Current Temporal activity binding for the DP execution port:

```text
runner: D:\XINAO_RESEARCH_RUNTIME\state\dp_sidecar_execution_port\latest.json
provider: D:\XINAO_RESEARCH_RUNTIME\state\dp_sidecar_execution_provider\latest.json
manifest: D:\XINAO_RESEARCH_RUNTIME\capabilities\legacy.deepseek_dp_sidecar.dp_sidecar_execution_port\manifest.json
activity: services\agent_runtime\temporal_codex_task_workflow.py::durable_parallel_wave_packet_activity
verifier: scripts\verify_temporal_codex_task_workflow.ps1
scope: runtime_enforced_for_temporal_durable_parallel_wave_packet_activity_only
```

This is actual DP port ref binding for the activity-scoped durable packet. It is
not global default runtime enforcement and not a completion gate.

DeepSeek default for high-intelligence dp work is `deepseek-v4-pro`,
`reasoning_effort=max`, `thinking=enabled`, unless task-scoped env override is
explicit.

dp search provider priority:

```text
1. Exa API when configured
2. Serper API when configured
3. free local search: local cache / SourceLedger / SearXNG / DDGS
```

Absent a current user-supplied Grok package, live Grok invocation is high-value
escalation only, never default. A current Grok package is not an escalation
lane; it is the user's authority proxy for the task. Secrets may be loaded from
`C:\Users\xx363\私钥` or `D:\XINAO_RESEARCH_RUNTIME\private\search.env`; never
print raw values.

## 9. Open Intent

When the user asks for outside search, open exploration, free divergence,
Grok-like research, maximum useful parallelism, or not being conservative,
actually use available search/tool lanes. Official docs are one lane, not the
whole search.

External findings enter fan-in as ClaimCards or equivalent evidence, not loose
prose. Community/social claims stay `candidate_pattern` or `reference_only`
until cross-checked.

Detect and repair:

```text
official_docs_only
report_only
single_lane_when_parallel_requested
safety_template_shrink
promised_tool_not_executed
```

## 10. Completion Boundary

Completion or Stop claims require task-scoped artifact acceptance plus
workflow/checkpoint/policy/trace/worker evidence and completion claim. Missing
completion evidence blocks completion wording only; it must not block safe
repair work.

Reflection, side audit text, report text, worker PASS, pytest PASS, or
`latest.json` are evidence views only. The executor must not be the sole auditor
of its own completion-like claim.

## 11. Read Order

For Seed Cortex / S work:

```text
CODEX_S_L0.md
SEED_CORTEX_MUST_READ_FIRST.md
D:\XINAO_RESEARCH_RUNTIME\state\current_route\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\xinao_seed_cortex_phase0_20260701.json
contracts/codex-s-workspace-boundary.v1.json
docs/current/CODEX_S_CURRENT_DOCS_BOUNDARY_2026-07-02.md
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_situation_bridge\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_window_context_contract\latest.json
D:\XINAO_RESEARCH_RUNTIME\state\codex_s_meta_object_router\latest.json
C:\Users\xx363\Desktop\Codex_Admin_Isolated\workspace\agent-tools\codex_s_operator_preference_recall.json
C:\Users\xx363\Desktop\Codex_Admin_Isolated\workspace\agent-tools\codex_s_intent_functional_objects.json
```

Old `D:\XINAO_CLEAN_RUNTIME\resources\startup\codex_l0_bootstrap.md`, project
projection files, B workspace manuals, old hooks, and historical desktop
reports are cold-path legacy/reference inputs only.

`docs/current` is also cold by default. Read only the boundary index above at
startup; other docs/current files require an explicit task, runtime evidence
pointer, audit/replay/migration need, or fan-in citation.

The same boundary applies to repo surfaces: schemas, `services/agent_runtime`
modules, `scripts/verify_*.ps1`, and tests are not hot runtime adoption by file
existence. They need entrypoint use, focused evidence, Chinese readback, and the
right `adoption_state`.

Verifier/service entrypoints are tiered. Use task-scoped focused verifiers by
default. Broad suites such as `scripts\verify_seedcortex_day1.ps1` and
`scripts\verify_seedcortex_runtime_readonly.ps1` are full-suite/cold audit
tools, not startup defaults and not the next step after every small change.
