# Prime / Codex behavior-parity test v1

`SENTINEL:PRIME_CODEX_PARITY_TEST_V1`

This is a reversible compatibility branch for the existing Prime conversation. It is not a second Pi identity, a second user-visible conversation, or a copy of the current local-cognition island.

The repository package is not itself a live-acceptance claim. Static/source checks can run while the current Prime tree is busy; runtime projection, fresh behavior regression, exact-session switching and rollback readback are recorded separately under the D-drive validation root and must succeed before the test mode is called live-verified.

## Runtime shape

- The exact existing Prime JSONL remains the only durable conversation.
- The test stops the old worker only after it is fully idle, then explicitly resumes that exact JSONL with runtime `cwd=E:\XINAO_RESEARCH_WORKSPACES\S`.
- Prime's provider, Sol model, max thinking, daemon socket, TUI, RLM and kernel stay Prime-native.
- The account-neutral runtime and mutable Prime overlay live under `D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\parity-test\codex-compatible`.
- `C:\Users\xx363\.codex\AGENTS.md`, the active account's Codex hook scripts and memory summary, the canonical Codex Skill directory and `S\AGENTS.md` remain the sources they already are. The adapter reads them; it does not copy changes back into them.
- Prime-only evolution belongs in the D-drive overlay. Promotion into Codex or S behavior is a candidate patch followed by Owner adoption and cross-consumer regression, never an automatic reverse sync.

## Separable account binding

The durable conversation, shared behavior core and active provider account are separate objects. `bindings\account-b.json` is the initially active, verified slot. `bindings\account-s.json` is delivered inactive until a real Prime-format Account S authentication source exists. Switching a slot while the exact conversation is idle changes only the account profile, account-specific Codex hooks/memory home and provider credentials used on the next exact resume. It never copies behavior, creates a conversation or rewrites the JSONL.

Codex `auth.json` is not treated as Prime authentication. A future Account S activation must either use an already authenticated Prime profile or bind a verified Prime-format `auth.json` without printing its contents. The account pointer contains paths and state only, never secrets.

When Account S is actually needed, `scripts\Initialize-PrimeCodexParityAccount.ps1 -Account account-s` opens a no-session Prime `/login` surface, and `scripts\Set-PrimeCodexParityAccount.ps1 -Account account-s` changes only the idle binding. The initializer rejects an OAuth identity that still resolves to Account B.

## What parity means

Parity means that portable causal behavior is consumed: current-user source decoding, user-side technical ownership, live-fact grounding, parent-result continuity, productivity, Stop, candidate/adoption/effect accounting, completion rulers and the user's repeated-burden constraints.

It does not claim that Prime and Codex have identical proprietary system prompts, tool protocols, plugin runtimes, sandbox implementations, TUI code or session formats. Codex-only plugins and tools are not advertised to Prime when Prime cannot execute them. Prime-native RLM is kept as the shell-specific implementation of recursive labor.

The exact surface-by-surface boundary is recorded in `COMPATIBILITY_MATRIX.md`; incompatible Codex rules, agents and plugins are translated only where their causal behavior has a real Prime consumer, never copied for cosmetic parity.

`BASELINE_COMPATIBILITY_ADOPTION.md` records what survives from the current Prime island and what is intentionally not copied, including removal of the stale product-specific permanent Owner exclusion.

## User-side speaking posture

The target is not a generic consultant that explains an abstract architecture after seeing a noun. It is a technical agent standing in the user's live machine and activity. When current files and processes already decide the question, it reads the smallest sufficient live surface and gives the concrete conclusion. It does not return a generic menu and make the user point out an already-existing repository, launcher or consumer.

That posture does not authorize impersonation or automatic Owner promotion. Capability consumption creates eligibility; a named effect scope still needs one current formal appointment.

## Active and protected objects

The existing objects remain untouched:

- `C:\Users\xx363\Desktop\PrimeB.lnk`
- `C:\Users\xx363\CodexLaunchers\Open-Prime-Agent-Account-B.ps1`
- `D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\profiles\account-b`
- `E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`

The new desktop entry is `C:\Users\xx363\Desktop\prime S.lnk`, a mode switch for the same conversation. It deliberately uses the same icon as the existing S/Prime entry. The old and test behavior surfaces cannot run concurrently against one JSONL. `/reload` can refresh resources inside one runtime, but Prime 0.7.0 fixes `cwd` and `agentDir` when that runtime is created; crossing from the old island to S therefore uses an idle stop plus exact resume, not a fork.

## Recovery

`scripts\Restore-PrimeCurrentMode.ps1` stops the test worker only when idle and resumes the same JSONL with the original island profile and cwd. No session history is rolled back or copied over. The source package and non-secret runtime projection can be rebuilt from this directory; provider authentication stays in account profiles and is excluded from recovery archives.
