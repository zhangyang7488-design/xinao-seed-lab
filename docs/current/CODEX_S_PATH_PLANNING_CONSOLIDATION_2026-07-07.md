# Codex S Path Planning Consolidation 2026-07-07

SENTINEL:XINAO_CODEX_S_PATH_PLANNING_CONSOLIDATION_20260707

## Scope

This document consolidates two local source folders:

- `C:\Users\xx363\Desktop\新建文件夹`
  - current near-term package
  - one file: `333_当前收口_未处理后续_20260706.txt`
- `C:\Users\xx363\Desktop\新系统`
  - longer-term new-system corpus
  - 15 txt files, including 9 files under `已经完成的历史备用`

The goal is not to execute the desktop txt literally. The goal is to prevent
duplicate hand-rolled work by classifying each item as:

- already implemented
- superseded by a better current carrier
- still needed
- stale or conflicting

This document is a planning artifact, not runtime state, not a completion gate,
and not a substitute for RootIntentLoop / Temporal evidence.

## Evidence Used

Local source inputs:

- `C:\Users\xx363\Desktop\新建文件夹\333_当前收口_未处理后续_20260706.txt`
- `C:\Users\xx363\Desktop\新系统\TASK_PACKAGE.json`
- `C:\Users\xx363\Desktop\新系统\XINAO_333_固定锚点.txt`
- `C:\Users\xx363\Desktop\新系统\当前源文本增量_20260704.txt`

Runtime/model evidence:

- input bundle: `D:\XINAO_RESEARCH_RUNTIME\state\path_planning_consolidation\input_20260707.md`
- Qwen extraction: `D:\XINAO_RESEARCH_RUNTIME\state\modular_dynamic_worker_pool_phase1\qwen_worker_invocation\artifacts\path-planning-consolidation-20260707-qwen-svenv-extract-01.extraction.json`
- DP audit: `D:\XINAO_RESEARCH_RUNTIME\state\dp_sidecar_execution_provider\results\path-planning-consolidation-20260707-dp-audit-01.audit.json`
- direct-worker-lane records:
  - `D:\XINAO_RESEARCH_RUNTIME\state\codex_s_direct_worker_lane\records\path-planning-consolidation-20260707-qwen-svenv-extract-01.json`
  - `D:\XINAO_RESEARCH_RUNTIME\state\codex_s_direct_worker_lane\records\path-planning-consolidation-20260707-dp-audit-01.json`
- reconciler: `D:\XINAO_RESEARCH_RUNTIME\state\codex_333_run_reconciler\latest.json`
- current index: `D:\XINAO_RESEARCH_RUNTIME\state\current_333_run_index\latest.json`
- worker status: `D:\XINAO_RESEARCH_RUNTIME\state\temporal_codex_task_worker\status.json`

Repo evidence from current `main`:

- `2b5e64b Persist Qwen carrier reinvoke evidence`
- `00da180 Harden closure evidence bundle gates`
- `7f71608 Close control-plane liveness into default route`
- `bcb07f3 Harden Temporal default loop rollover`
- `bebd5bb Route structural blockers through repair contract`
- `c417a9d Recognize backend control-plane 333 runs`
- `584961b Fix light research absolute local roots`
- `863e2c2 Add 333 run reconciler`
- `2fbfd7f Add Codex S light research loop`
- `99d4bac Align provider router brain-only default`
- `c648deb Bind Codex max worker evidence to workflow DAG`
- `6dbe6f3 feat: worker-turn provider router - V4 Pro brain, Qwen execution, Codex final only`

Provider note:

- Qwen was successfully invoked through S `.venv`.
- A separate Qwen attempt launched from global Python with a large `--input-file`
  fell back to DP because the current re-exec path does not preserve large
  `--input-file` as a file argument. This is a tooling improvement item, not a
  planning blocker.

## Current Fact Snapshot

The near-term desktop file was last updated before the latest worker/reconciler
checks. Treat its runtime section as stale unless revalidated.

Current runtime facts from the latest local check:

- Temporal server: reachable at `127.0.0.1:7233`
- worker: `polling`
- worker pid: `25744`
- task queue: `xinao-codex-task-default`
- pollers seen by status script: `2`
- running Temporal workflows: 1
- current running workflow:
  `xinao-codex-task-default_temporal_tmptk_k6x0l-20260707_100107`
- reconciler classification for that workflow: `temporary_probe_or_ad_hoc`
- current 333 mainline candidate count: `0`
- named blocker: `NO_ACTIVE_333_MAINLINE`

Interpretation:

- There is a live worker.
- There is a running Temporal workflow.
- There is still no accepted active 333 default mainline, because the running
  workflow is not a stable mainline candidate.
- The old desktop statement "running_workflow_count=1 but mainline_candidate=0"
  remains structurally correct; only the worker pid/poller counts are stale.

## Classification

### Already Implemented Or Strongly Superseded

#### 1. Qwen / DP / Codex cost-quality split

Status: implemented and supersedes older fixed "Codex/DeepSeek does everything"
or "DP20" style notes.

Current carrier:

- `codex_s_token_budget_gate.py`
- ProviderScheduler / worker pool route context
- direct-worker-lane
- Qwen prepaid cheap worker for extraction/draft/eval when suitable
- DP/DeepSeek for audit / fallback / hard review
- Codex remains final patch / merge / AAQ owner

Do not hand-roll:

- fixed DeepSeek share target
- Qwen as global primary brain
- Codex subagent fanout as default worker pool
- DP output as completion authority

Needed only if extending:

- unify provider lane index and actual-provider ledger fields across every
  worker result.

#### 2. Foreground light research loop

Status: implemented. This is the replacement for ad hoc new audit txt files.

Current carrier:

- `codex_s.light_research_loop`
- local root scanning
- SourceLedger / ClaimCards
- local/Qwen/DP staging
- Codex fan-in

Evidence:

- `2fbfd7f Add Codex S light research loop`
- `584961b Fix light research absolute local roots`
- tests for absolute local root scanning

Do not hand-roll:

- another "external mature vs old repo audit" desktop txt as the execution
  mechanism
- a new isolated report-only research path

Use instead:

- light research loop for foreground source comparison
- direct-worker-lane Qwen/DP for model compression/audit
- Codex fan-in for final judgment

#### 3. 333 run reconciler and current index

Status: implemented. This supersedes manual "盯旧 workflow / 盯 latest" checks.

Current carrier:

- `scripts\hardmode\Invoke-CodexS333RunReconciler.ps1`
- `D:\XINAO_RESEARCH_RUNTIME\state\codex_333_run_reconciler\latest.json`
- `D:\XINAO_RESEARCH_RUNTIME\state\current_333_run_index\latest.json`

Current decision:

- `NO_ACTIVE_333_MAINLINE`
- temporary/ad-hoc workflow ignored

Do not hand-roll:

- manually resuming a terminated wave-24 workflow pointer
- treating a running temporary workflow as the 333 mainline
- replacing the reconciler with a desktop status note

#### 4. Temporal history rollover

Status: implemented for the default loop.

Current carrier:

- `TemporalCodexTaskWorkflow.run`
- `default_loop_history_budget_rollover`
- continue-as-new payload compaction

Evidence:

- `bcb07f3 Harden Temporal default loop rollover`

Meaning:

- The old wave-24 history-limit failure is a historical cause, not a reason to
  build another local runner.
- Future long 333 runs should rotate through the default loop rollover path.

#### 5. Control-plane liveness demotion

Status: implemented.

Current carrier:

- control-plane liveness is a read-model only
- no model invocation
- no worker dispatch
- no Temporal write
- no signal

Evidence:

- `7f71608 Close control-plane liveness into default route`

Do not hand-roll:

- a heartbeat that becomes a hidden controller
- liveness text that claims completion
- a supervisor that dispatches based on latest/readback alone

#### 6. Closure/final wording guard

Status: implemented after the desktop follow-up package.

Current carrier:

- `completion_claim_payload_builder.py`
- `Invoke-CodexSStopHook.ps1`
- `Invoke-CodexSUserPromptSubmitHook.ps1`
- `pre_pass_audit_loop.py`

Evidence:

- `00da180 Harden closure evidence bundle gates`
- `2b5e64b Persist Qwen carrier reinvoke evidence`

Meaning:

- "收口完了" is now blocked unless the closure evidence bundle is present:
  default mainline binding, runtime worker load, verification, evidence/readback,
  clean git status, commit hash, push target, 333/mainline state, and
  remaining/named-blocker state.

#### 7. PrePASS / AllocationPlan as support surfaces

Status: already exists as support. Do not rebuild as a new controller.

Current carriers:

- `pre_pass_audit_loop.py`
- `allocation_plan.py`
- Temporal pre-pass activity integration

Boundary:

- PrePASS is not a completion gate.
- AllocationPlan is the lane allocation envelope inside RootIntentLoop, not a
  route enum and not a separate orchestrator.

## Still Needed

### P0. Start or bind a real active 333 default mainline

Current blocker:

- `NO_ACTIVE_333_MAINLINE`

Why this is still needed:

- Worker polling is live.
- Temporal has a running workflow.
- The reconciler rejects it as `temporary_probe_or_ad_hoc`.
- Therefore the system lacks a stable current 333 mainline with accepted
  `workflow_id` / `run_id`.

Minimal landing carrier:

- `scripts\hardmode\Invoke-CodexSRootIntentLoopDriver.ps1`
- live Temporal server `127.0.0.1:7233`
- task queue `xinao-codex-task-default`
- stable workflow id policy:
  - use existing only if it is a valid stable mainline
  - otherwise create a clean mainline workflow id
  - do not adopt temporary/probe/ad-hoc workflow ids

Required evidence:

- server-bound Temporal event history
- selected `workflow_id`
- selected `run_id`
- same-wave worker terminal results
- fan-in / merge
- AAQ decision
- Chinese readback
- updated current 333 run index

Do not do:

- continue the old terminated wave-24 run
- claim the temporary running workflow is the mainline
- use local compatibility flow as the mainline

### P0. Make source frontier -> WorkerBrief -> ProviderScheduler -> worker pool -> FanIn/AAQ a default per-wave path

Why this is still needed:

- The new-system corpus says this is the core missing chain.
- Some components exist, but the default every-wave path must prove that source
  frontier naturally becomes worker briefs, provider selection, staged worker
  outputs, fan-in, AAQ, and next frontier.

Minimal landing carrier:

- RootIntentLoop driver entry
- Temporal workflow activity chain
- ProviderScheduler route
- modular dynamic worker pool
- staging / merge
- FanInAcceptanceQueue
- ArtifactAcceptanceQueue
- next_frontier

Required evidence:

- one wave where the chain runs end-to-end
- worker lane terminal result count
- staged count
- merged count
- accepted / rejected AAQ decision
- next_frontier update

Do not do:

- write ClaimCards only and call that the worker pool
- count planned lanes as completed lanes
- call Qwen/DP output accepted without Codex fan-in / AAQ

### P1. Result wait / bounded readback protocol

Why this is still needed:

- Current readbacks and status files exist.
- The user-facing waiting boundary is not yet a complete protocol.

Required states:

- `ACCEPTED`
- `RUNNING`
- `TERMINAL_SUCCESS`
- `TERMINAL_FAILURE`
- `NAMED_BLOCKER`
- `TIMEOUT`
- `STALE_READBACK`

Minimal landing carrier:

- a result-wait surface that reads current index, worker status, fan-in/AAQ, and
  readback freshness
- no model invocation
- no worker dispatch
- no completion claim

Acceptance:

- foreground can tell the user exactly whether to wait, resume/kick, or report a
  named blocker
- Stop/final cannot use stale readback as completion

### P1. Provider lane index and ledger disambiguation

Why this is still needed:

- Legacy activity names such as `codex_worker_turn_activity` can be mistaken for
  actual Codex spend or provider choice.
- Qwen/DP/Codex lanes need unified fields.

Required fields for every worker terminal result:

- `actual_provider_id`
- `selected_carrier_provider_id`
- `selected_model`
- `provider_tier`
- `qwen_prepaid_first_required`
- `qwen_prepaid_first_attempted`
- `qwen_prepaid_first_succeeded`
- `fallback_from_provider_id`
- `fallback_reason`
- token usage
- cost source
- artifact ref
- completion blocked flags

Do not do:

- infer provider usage from activity name
- let Qwen/DP artifacts bypass staging/fan-in/AAQ

### P1. Controller / Supervisor event layering

Why this is still needed:

- Reconciler is read-only and should stay read-only.
- A controller/supervisor response is still needed when state changes, conflicts
  appear, AAQ blocks, or mainline admission fails.

Landing shape:

- Do not build a new generic controller from scratch.
- Use existing Temporal workflow state, current index, reconciler, ProviderScheduler,
  and AAQ.
- Add narrow event triggers only:
  - `NO_ACTIVE_333_MAINLINE`
  - provider route conflict
  - source gap open
  - fan-in rejected
  - AAQ rejected or blocked
  - stale readback / timeout
  - history rollover required

Supervisor role:

- Qwen/DP/DeepSeek can draft or audit.
- Codex S remains final fan-in and repo mutation owner.

### P1. P1 global hardening backlog

Still real:

- executor/sandbox hardening
- provider lane index unification
- source/intent lineage full chain
- health signal denoise
- old CLEAN / D-runtime reference scan and cleanup

Landing rule:

- Handle these as focused P1 packages.
- Do not bundle them into the P0 mainline admission fix.
- Each package needs its own default consumer, verifier, evidence, and readback.

### P2. Tooling improvement: direct-worker-lane large input re-exec

Observed during this consolidation:

- Running Qwen direct-worker-lane from global Python with a large `--input-file`
  attempted the Qwen route but fell back to DP with
  `QWEN_WORKER_POOL_WRONG_PYTHON_CARRIER`.
- Running the same lane from S `.venv` succeeded with
  `qwen_prepaid_cheap_worker`.

Probable cause:

- The re-exec path reads `--input-file` into text and forwards it as
  `--input-text`, which is fragile for large Windows command lines.

Landing:

- Preserve `--input-file` when re-executing into S `.venv`.
- Add a regression test for `provider=qwen`, `mode=extraction`, global Python
  entry, and large `--input-file`.

Priority:

- P2 unless Qwen lanes are invoked frequently from global Python with large
  files.

## Do Not Do

Do not execute the near-term desktop file literally as a new hand-written plan.

Do not:

- create another audit/readback txt as the main output
- rebuild a new Controller/Supervisor island from scratch
- continue wave 24 as if it were a live workflow
- treat a temporary/probe Temporal workflow as the active 333 mainline
- use `latest.json`, report, PASS, readback, or ClaimCard count as completion
- claim 20/50/DP20 width without configured/requested/dispatched/completed/staged/merged/blocker fields
- make Qwen the final engineering owner
- make DP/DeepSeek a second brain or completion gate
- resurrect old 5d33/CLEAN runtime hot path as authority
- use 30-minute runners or black-window loops as the default mainline

## Execution Order

### Step 1: Freeze the desktop inputs as source material

Action:

- Treat `新建文件夹\333_当前收口_未处理后续_20260706.txt` as a source package,
  not current runtime truth.
- Treat `新系统\TASK_PACKAGE.json` as the current task package manifest for the
  desktop corpus; legacy read-order files are fallback/reference only.

Acceptance:

- Future tasks cite this consolidation doc and the runtime evidence refs above,
  not the older worker pid / wave-24 status lines.

### Step 2: Confirm current mainline blocker before any new 333 work

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hardmode\Invoke-CodexS333RunReconciler.ps1 -RepoRoot E:\XINAO_RESEARCH_WORKSPACES\S -RuntimeRoot D:\XINAO_RESEARCH_RUNTIME
```

Expected:

- either a selected stable mainline workflow
- or `NO_ACTIVE_333_MAINLINE`

If the result remains `NO_ACTIVE_333_MAINLINE`, the next task is mainline
admission, not another audit.

### Step 3: Start/bind the real mainline

Entry:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hardmode\Invoke-CodexSRootIntentLoopDriver.ps1 -RepoRoot E:\XINAO_RESEARCH_WORKSPACES\S -RuntimeRoot D:\XINAO_RESEARCH_RUNTIME
```

Acceptance evidence:

- stable workflow id
- run id
- Temporal event history
- worker terminal results
- fan-in/merge
- AAQ
- readback
- current index updated

### Step 4: Run one end-to-end default chain wave

The wave must prove:

```text
source frontier
-> WorkerBrief
-> ProviderScheduler
-> Qwen/DP/Codex worker pool
-> staging
-> merge
-> FanIn/AAQ
-> next_frontier
```

Acceptance evidence:

- observed dispatched width
- observed completed width
- staged count
- merged count
- accepted/rejected AAQ decision
- named blocker if incomplete

### Step 5: Add bounded result_wait/readback

Only after the mainline is real enough to wait on.

Acceptance:

- foreground can report `ACCEPTED/RUNNING/TERMINAL/NAMED_BLOCKER/TIMEOUT`
- stale readback is detected
- Stop/final cannot convert timeout or stale readback into completion

### Step 6: P1 packages

Handle separately:

- provider lane index
- executor/sandbox
- source/intent lineage
- health denoise
- old reference cleanup
- direct-worker-lane large `--input-file` re-exec fix

Each P1 package needs:

- scoped diff
- default consumer
- verifier
- runtime evidence
- Chinese readback

## One-Line Decision

The near-term desktop package is not useless, but it is not the execution plan.
It is a stale follow-up source package. Most control-plane P0 work in it is
already implemented or superseded. The remaining real P0 is: bind/start a stable
active 333 mainline, then prove one default wave runs source frontier through
WorkerBrief, ProviderScheduler, worker pool, FanIn/AAQ, and next_frontier.
