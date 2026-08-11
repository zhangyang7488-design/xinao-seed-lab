# Candidate-only Grok engineering: deterministic Windows RuntimeObservation

Design the thinnest deterministic RuntimeObservation for the current Windows Codex environment. Mechanically observable candidates include actual cwd, CODEX_HOME, process/session identity, repo/worktree/HEAD/status, active AGENTS and hooks, tool surface, sandbox/permission facts, and for a worker: provider/model, workspace, read/write capability, world slice actually consumed, and result identity.

Separate facts that can be measured reliably from facts the harness cannot currently prove. Never let model-authored text become runtime truth. Identify command/API sources, stable normalization, failure states, provenance, freshness, redaction, and tests. Explicitly address the observed WorkerPool mismatch where a prompt said read-only but the receipt reported unbounded_host_legacy/none isolation.

Do not modify files or production runtime. Recommend honest UNKNOWN when proof is unavailable.

Return sections: ## VERDICT, ## OBSERVABLE_FACTS, ## UNPROVABLE_OR_UNKNOWN, ## PROBE_DESIGN, ## TESTS, ## DISCONFIRMERS, ## RECOMMENDATION. End with `completion_claim_allowed=false`.
