# Candidate-only Grok evaluation design: real semantic accidents

Design an executable transcript/evaluation set for B0-B5 using real failure families: correction `not X, Y`; quoted AI proposal remains material; mentioning web GPT does not trigger product troubleshooting; pure discussion produces no tool/task/worker; explicit edit does act; topic switch and return; compact/resume/fresh recovery; stale understanding is retracted; runtime facts are not guessed.

The primary outcome is user correction/re-explanation burden and preservation of appropriate action, not keyword recitation or schema validity. Specify exact turn sequences, arm-invariant inputs, observable tool/action traces, scoring, blind review, false positives, and what evidence could distinguish necessary from sufficient conditions.

Do not modify files or production state. Use existing S eval conventions where useful, but do not let them define the phenomenon.

Return sections: ## VERDICT, ## CASES, ## TRAJECTORY_ASSERTIONS, ## METRICS, ## BLIND_REVIEW, ## DISCONFIRMERS, ## RECOMMENDATION. End with `completion_claim_allowed=false`.
