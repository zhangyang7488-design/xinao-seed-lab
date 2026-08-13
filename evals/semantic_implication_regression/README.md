# Semantic implication regression

Formal suite identity: `semantic_implication_regression`.

This is the only live semantic-accident behavior suite in S. It is cold, on demand, and owned by
the dedicated runner `scripts/run_semantic_implication_regression_eval.ps1`; it is not loaded by
the ordinary behavior-regression profiles.

The live clean-room repository preserves the retired native corpus at
`xinao/archive/legacy-research/T0-X-4328f8c45497/semantic_accidents/cases.v1.json`.
`source_contract.v1.json` binds its exact Git commit, tree,
blob, worktree bytes, corpus seal, and selected case seal. Local held-out fixtures are synthetic
case facts, not incident authority.

The fourteen cases cover:

- evidence de-duplication and downstream functional retention under AB/BA turn order;
- a held-out generic evidence/function transfer pair;
- an attractive carrier-ontology lure;
- real return of a local result into its continuing consumer;
- quoted candidate material versus an explicitly adopted bounded effect;
- formation of an unlisted working relation;
- one offline shift-recovery property without a recurrent controller;
- a normal exact bounded read and an explicit Stop zero-tool control.

Every case receives a separate ephemeral thread, turn, and physical workspace. The model-visible
workspace contains only that case's raw facts and causal executables. The case facts explicitly
separate complete source-witness identities, their deterministic representations, functional
consumer dimensions, and relation-reference observations; the oracle does not hide a second
witness ontology. The answer oracle, exact normalized command and exit sequences, stdout
observation contract, and initial/final inventory contract remain outside the workspace. A pass
requires exact command identity, exact exit status, either raw stdout identity or the explicitly
allowlisted JSON projection produced by app-server redaction, exact case-local state delta, effect
or local-result readback where applicable, and stable causal body bytes. A redaction marker at any
other path, any non-redacted value change, or any structural change fails. Cases contain no
`expected_*`, `allowed_*`, or `forbidden_*` answer fields, and model output does not self-report
parent, idle, next-question, source-adoption, or effect-receipt status.

Model output is never an effect receipt. A passing run remains scoped to the frozen source,
consumer identity, provider adapter, and observed trajectories. It cannot prove hidden-state
uptake, permanent future behavior, domain truth, parent completion, or authority to rewrite hot
behavior.

Static source/runner preflight:

```powershell
.\scripts\run_semantic_implication_regression_eval.ps1 -PreflightOnly
```

Full fresh run after the canonical source contract is pinned to the final adopted X revision:

```powershell
.\scripts\run_semantic_implication_regression_eval.ps1 -MaxConcurrency 1
```

Run artifacts are written below
`D:\XINAO_RESEARCH_RUNTIME\state\human-capabilities\evals\semantic-implication-regression`.
