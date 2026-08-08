# Codex-to-Prime compatibility matrix

`SENTINEL:PRIME_CODEX_PARITY_COMPATIBILITY_MATRIX_V1`

The target is behavioral consumption, not a false claim that two products share one proprietary shell.

| Codex surface | Prime test consumer | Status and boundary |
|---|---|---|
| Canonical `AGENTS.md` | `before_agent_start` live read into effective system prompt | live per turn |
| Account `UserPromptSubmit` hook | exact current hook script invoked with a Prime event adapter | live per turn; returned zero-beat context is injected |
| Account `SessionStart` hook | exact current hook script invoked on Prime session start/reload | live, fail-open on timeout |
| Codex Stop/finalization hook | L0 and overlay Stop/completion semantics | semantic parity only; Prime has no identical blocking hook protocol |
| Canonical Skills | `resources_discover` adds the canonical Skill root | live catalog; a Skill cannot conjure a Codex-only tool in Prime |
| Active account memory summary | live read into effective prompt | advisory, account-switchable, current words/live facts win |
| S `AGENTS.md` | Prime native cwd context discovery with runtime `cwd=S` | live |
| Approval posture | selected non-secret config values projected into prompt | `approval_policy=never`; no automatic review agent added |
| Codex `agents/*.toml` | Prime-native RLM and compatibility Skill | not copied; worker runtime and authority semantics differ |
| Codex `rules/default.rules` | Prime native tool execution plus explicit protected-source guard | not copied; these are Codex command approvals, not portable behavior law |
| Codex plugins/MCP/browser UI | Prime-native tools and explicitly configured MCP | no identity claim; unavailable Codex-only capabilities are not advertised |
| Codex session format | existing Prime JSONL | never converted or copied |

Account binding is orthogonal to this matrix. It selects Prime provider authentication plus the account-specific Codex hooks/memory home; it does not select or duplicate the behavior core.
