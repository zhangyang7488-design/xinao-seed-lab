# Candidate-only Grok design: CurrentSituation transition semantics

Design a minimal CurrentSituation projection that represents the current human-Codex-reality relation, not a summary, memory, task record, authority source, plan, goal, worker registry, or completion state.

Every new utterance must first be interpreted relative to the current situation before any response/tool/task/worker action. Interpretation may yield NO_MATERIAL_CHANGE or MATERIAL_REVISION; only material revision must be durably persisted. Corrections must replace/retract current understandings rather than append a competing historical note. Model interpretation is fallible and must not become irreversible truth.

Specify the smallest transition contract, allowed fields, forbidden fields, replacement/retraction behavior, stale-write protection if truly needed, and tests. Attack the risk that an explicit per-turn state ritual becomes a controller or blocks normal action.

Do not modify files or production runtime.

Return sections: ## VERDICT, ## MINIMAL_PROJECTION, ## TRANSITION_CONTRACT, ## FORBIDDEN_FIELDS, ## TESTS, ## DISCONFIRMERS, ## RECOMMENDATION. End with `completion_claim_allowed=false`.
