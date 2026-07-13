# Local behavior regression

This is a medium local layer over capabilities already present on the machine. It is not another
agent platform, daemon, scheduler, or approval gate.

## Shape

- `catalog.json` inventories 59 behavior specifications across live and static suites.
- `context_intent_alignment/cases.yaml` is the canonical live behavior dataset. Promptfoo reads it
  directly, so expected behavior is not duplicated in the config.
- `smoke`, `core`, and `deep` profiles make cost proportional to the change. Metadata domains can
  narrow a run further, and a prior result can be supplied to rerun only failures.
- Every run gets an operation-scoped D-drive directory containing raw Promptfoo JSON and a compact
  `summary.json`; `latest.json` is only a pointer.
- Live suites default to Promptfoo concurrency 2 to avoid app-server capacity spikes; callers can
  override `-MaxConcurrency` without changing the suite or adding a retry service.
- Provider ERROR rows get at most one native `--filter-errors-only` rerun at concurrency 1. Assertion
  failures are never retried automatically, and both original and retry JSON remain in the run folder.
- When a retry occurs, `summary.json` points `suites[].result` at a resolved Promptfoo-compatible JSON;
  `initial_result` and `error_retry_results` preserve the raw attempts. Terminal counts come from the
  resolved per-case rows, so downstream candidate intake does not import an already-recovered ERROR.
- Corrections and failures enter the D-drive candidate inbox with provenance. Candidates never
  authorize actions and never rewrite instructions, memory, or evals automatically.
- Promptfoo failures can be imported one way into that same candidate inbox with source trace IDs,
  acceptance criteria, and prohibited side effects. Import never promotes a candidate.
- `context_intent_alignment/decision_model.v1.json` is a cold-path, qualitative intent model distilled
  from user-approved Grok planning behavior. It helps map vague examples to mature capabilities; it is
  not a score, gate, authority source, or replacement for the live user context.

## Commands

```powershell
# Fast representative behavior and capability check
.\scripts\run_behavior_regression.ps1 -Profile smoke

# Normal bank, including deterministic static validation
.\scripts\run_behavior_regression.ps1 -Profile core

# Raise or lower only the native Promptfoo request concurrency when evidence supports it
.\scripts\run_behavior_regression.ps1 -Profile core -MaxConcurrency 2

# One affected domain only
.\scripts\run_behavior_regression.ps1 -Profile core -Domain worker_routing

# One or two descriptions while developing a behavior delta
.\scripts\run_behavior_regression.ps1 -Profile context `
  -CasePattern 'Stopping a user-owned Grok TUI|A nontechnical ambitious idea'

# Rerun only cases that failed in a previous Promptfoo result
.\scripts\run_behavior_regression.ps1 -Profile context -FailedFrom D:\path\context-result.json

# Turn failed Promptfoo rows into sourced candidates, without policy mutation
.\scripts\Import-PromptfooFailuresToBehaviorCandidates.ps1 -ResultPath D:\path\result.json

# Record a sourced candidate without promoting it
.\scripts\New-BehaviorRegressionCandidate.ps1 `
  -Id REG_EXAMPLE_CANDIDATE `
  -SourceType user_correction `
  -SourceRef current-user-2026-07-13 `
  -Domain preference_learning `
  -ObservedOutcome 'The preference was saved as prose only.' `
  -DesiredOutcome 'The smallest existing artifact changes later behavior.' `
  -RestoredContext 'Memory, evals, skills, and config are available.' `
  -UserIncrement 'Make this stable preference reduce later work.'
```

`-FailedFrom` replays prior failed testcase definitions. Use it after an implementation or prompt
fix. When the expected testcase variables themselves change, run that suite normally so Promptfoo
loads the new definitions.

Static incident specifications remain specifications until their real environment supplies runtime
evidence. A green JSON fixture never closes a runtime incident.

## Why the other installed software is not always active

Grok is useful for independent candidate research and review. The task-run ledger is useful for a
material behavior change. Temporal is useful only when an evaluation really needs durable,
multi-wave execution. Prefect stays installed but inactive because adding a second durable
orchestrator would add failure modes without improving this local workflow. Pydantic Evals and
Inspect AI contributed dataset and log patterns, but Promptfoo already provides the needed runner.
