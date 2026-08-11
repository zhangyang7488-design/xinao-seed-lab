# Candidate-only Grok design: B0-B5 causal ablation

Design a concrete B0-B5 experiment that isolates exactly one change per arm: B0 current S cwd/shared AGENTS/zero-beat; B1 neutral cwd only; B2 isolated CODEX_HOME only; B3 tiny L0 only; B4 thin CurrentSituation only; B5 deterministic RuntimeObservation only.

The tested runtime must exclude Grok, multi-agent, Memory, Goals, broad Skills, X/S writes, and production Hook changes. Construction workers are outside the tested runtime. Same model and semantic incidents must be held constant. Specify exact runtime identities, inputs, outputs, contamination checks, transcripts, metrics, failure interpretations, and how to distinguish real continuity from a new reader consuming a better handoff.

Do not modify files or production state. You may conclude sequential ablation is insufficient and propose a better bounded design, but preserve causal interpretability and user correction burden as the real outcome.

Return sections: ## VERDICT, ## ARM_SPEC, ## CONTAMINATION_CONTROLS, ## METRICS, ## DISCONFIRMERS, ## RECOMMENDATION. End with `completion_claim_allowed=false`.
