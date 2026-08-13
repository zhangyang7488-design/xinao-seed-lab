# Main prime recovery map for Codex

Use this map only after the current parent result and active Pi object are bound.

## Durable meaning

- Family contract: `E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island\AGENTS.md`
- Current capability lineage:
  `E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island\cognition\CURRENT_CAPABILITY_LINEAGE.md`
- Main `prime` surface island: `E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island`
- Isolated PiB cold-snapshot island: `E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`

The family contract carries stable machine binding, isolation, compatibility, and recovery facts.
A surface island carries dated body evidence, acceptance, and rollback. Neither defines Pi or
creates a task.

## Live products

- Main `prime` profile (internal compatibility name): `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s`
- PiB isolated cold-snapshot profile: `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-b`
- Pi engineering source:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1`
- Main `prime` Pi core: `D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`
- PiB cold-snapshot Pi core: `D:\XINAO_RESEARCH_RUNTIME\tools\pi\0.84.1`
- Main-core installer/verifier:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\scripts\Install-PiSMainCore.ps1`
- Main desktop wrapper: `C:\Users\xx363\CodexLaunchers\Open-Prime.ps1`
- PiB cold-backup shortcut: `C:\Users\xx363\PrimeB.lnk`
- Exact visible PiS restart:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\scripts\Start-PrimeSInWindowsTerminal.ps1 -Session <native-session-id>`

Verify launcher target, active account binding, Pi/Node version, settings, installed packages,
contract projection, overlay manifest, native session identity, process instance, and target
consumer only to the degree they intersect the current action.

Do not invoke the PiS desktop wrapper as a fresh `pwsh` process. That produces a separate conhost and
changes the user's visible TUI even when the Pi profile/session is correct. A Codex-driven restart
must settle and stop the exact old ingress target, use the exact visible restart script above, then
prove the new instance retained the same `prime-s` profile and native session. The Windows Terminal
profile is a real consumer because it owns appearance, title, close-on-exit, and numpad-follow scope.
The restart script only admits the newest profile-local session, launches the profile's proven native
commandline unchanged, and treats its launch receipt as non-final until exact ingress readback. Do not
replace the profile commandline through `wt.exe`: a zero launcher exit code does not prove a tab or Pi
process was created.

### Context-window authority and recovery

The active provider model catalog in `prime-s\models-store.json` is authoritative for the selected
model's context window. `Set-PiSBodyConfiguration.ps1` removes only a profile-local
`providers.openai-codex.modelOverrides.gpt-5.6-sol.contextWindow` override while preserving unrelated
custom models and providers. Never copy a remembered numeric window into `models.json`; read the
current catalog and verify that the local override is absent. As of the 2026-08-08 incident the live
catalog reported 272000, but that value is drift-prone evidence, not a permanent contract.

If the provider rejects an already-oversized native session, preserve the session file. Native
compaction is the first bounded recovery only while the branch can still fit a provider request; it
cannot rescue a branch that already exceeds the real window. At that boundary, start a fresh visible
PiS session through the proven Windows Terminal profile and give it a short technical pointer to the
old session and named primary artifacts. Do not paste the old transcript, a complete migration tree,
large logs, or recursive file inventories into the new prompt. Read long sources by purpose, offsets,
search hits, and named receipts; a file pointer is transport, not epistemic authority or a task queue.

PiS's numpad transcript-follow behavior is sourced and installed from:

- `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\helpers\PrimeS-NumPadEnter-Follow.ahk`
- `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\scripts\Set-PiSNumpadEnterFollow.ps1`

It is scoped to the exact `prime` Windows Terminal title. The profile keybinding adds `F12` only
to `tui.altScreen.bottom`; the helper sends F12 only from transcript geometry and sends ordinary
Enter from input or uncertain geometry. Never migrate this as a global Windows Terminal action or
change main Enter.

The same profile is fixed to `closeOnExit=always`. Future failed or stopped PiS launches should
close their own tab instead of leaving a visible exited-process page. Cleanup is exact and
Pi-owned: keep the addressed live `prime-s` instance, never terminate the shared
`WindowsTerminal.exe`, and never close Codex or another profile merely because individual stale
tabs are hard to enumerate.

## Credential source knowledge

- User-provided local credential source root: `C:\Users\xx363\私钥`

When a named Pi consumer needs a credential, resolve the relevant source under this root before
asking the user to repeat its path. Read only the intersecting credential, never echo it, and copy
the value directly into that Pi profile's native `auth.json` or the provider's own native store.
The source file path is recovery knowledge, not a runtime dependency; do not replace native storage
with environment-variable shims, pointer files, sync daemons, or credential control planes.

Current native PiS provider entrypoints are `Set-PiSSerperCredential.ps1` for the profile-local
Serper credential store and `Set-PiSDeepSeekCredential.ps1` for Pi's native `deepseek` provider in
`auth.json`. Re-probe the provider before claiming current availability. OpenAI account migration
owns only the `openai-codex` entry and must preserve independent providers.

The PiS model scope admits `deepseek/deepseek-v4-flash` and `deepseek/deepseek-v4-pro`, and
`pi-subagents` accepts a per-run `model` override. Reuse the existing task-fit Pi child role with
that override; do not create a permanent DeepSeek agent merely to force consumption. A marker child
is a transport/auth probe only. For a real value or billing comparison, keep the task and evidence
ruler fixed enough to compare, and bind the exact provider call to official balance before/after
readback without exposing the credential.

## Communication

- Codex/S-side protocol note:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\operator-tools\pi-native-ingress\README.md`
- Codex/S-side client:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\operator-tools\pi-native-ingress\pi-native-control.mjs`
- Default PiS pipe: `\\.\pipe\xinao-pi-supervisor-prime-s-v1`

The client accepts delivery content on stdin or from a file. Always list/read state before a
mutation and bind `profile + instance + session`. After restart, a resumed native session has a new
process instance and stale mutations must fail. For delivery, require `message_consumed`, not only
`runtime_accepted`; apparently idle sends are deferred past Pi's `agent_settled` unwind race, and an
idle prompt that becomes busy fails instead of becoming a steer. Stop cancels ingress-owned
unconsumed delivery first. Its response proves only that shutdown was requested—confirm the exact
pipe and owned process disappear.

## Body labs and adoption

- Lab root: `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\body-labs\prime-s`
- Lab creator:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\scripts\New-PiSBodyLab.ps1`

A lab is session-empty and account/profile isolated. Installed candidates remain candidates. Before
active PiS adoption, record the exact source/body version, config without secrets, credential
consumer path, positive and negative evidence, known-good preimage, and rollback procedure. After
adoption, fresh-launch PiS and re-run the real activity that exposed the gap.

Core-runtime candidates need stronger isolation than profile packages. Use
`New-PiSBodyLab.ps1 -LabId <id> -IsolatePiCore` to install a pinned Pi binary under the lab; add
`-ApplyMidTurnCompactionCompatibility` only for the named candidate. The PiB cold-snapshot core at
`D:\XINAO_RESEARCH_RUNTIME\tools\pi\0.84.1` is not the main active core and must not be modified by
main-prime experiments or adoption. After an isolated red/green consumer passes, adopt only into the
main core at `D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`. For the 0.84.1 long-tool-loop incident, run
`Test-PiSMidTurnCompaction.mjs` against both the unpatched and patched roots. Required green evidence
is provider order `tool-call -> compact -> resume-after-tool`, one durable session, a persisted
compaction entry, and final consumption of the completed tool result. Gate-off behavior must retain
the upstream order so PrimeB is not silently changed. Also run `--fault cancel-with-steer`: a
cancelled native compaction with a queued steer must settle after the completed tool result and make
no next provider request. The three runs use separate receipt roots so a gate-off run cannot erase
the green evidence.

To roll back this compatibility layer, stop the active PiS process, run
`Restore-PiSMidTurnCompactionCompatibility.ps1 -PiToolRoot D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`, verify the upstream hash, then launch with
`Start-UpstreamPi.ps1 -Profile prime-s -DisableMidTurnCompactionCompatibility`. Do not run the normal
launcher or capability installer during rollback validation because their formal path reapplies the
known compatibility patch. A restarted process is required; restoring bytes cannot change a module
already loaded by a live PiS TUI.

The main core also carries two hash-gated post-0.84.1 upstream fixes: DeepSeek requests use
`max_tokens`, and fullscreen full-width rows avoid unnecessary recomposition. Verify them with
`Install-PiSMainCore.ps1 -VerifyOnly` and `Test-PiSPost0841UpstreamCompatibility.mjs --pi-root
D:\XINAO_RESEARCH_RUNTIME\tools\pi\prime\0.84.1`. Their apply/restore scripts reject the PiB cold
core. Rollback restores exact preimages and requires a fresh visible restart; bytes cannot change the
already loaded process.

The profile shell is Git Bash. Use `/dev/null` for discarded output, never Windows `NUL`: in Git Bash
`2>NUL` creates a real untracked file in the current repository. At a natural boundary, read back the
intersecting worktree and remove only proven tool residue. Do not turn this into desktop-wide or
repository-wide cleanup.

PiB is outside the default write, maintenance, upgrade, test, report, and mention cone after the
currently authorized full-body snapshot has passed fresh root/child verification. Reopen it only
when the user explicitly names it or main-prime recovery demonstrably requires it; never treat the
frozen snapshot as a live synchronization peer.

## Native maturity organs

Read the current capability lineage and installed package source before relying on a versioned
behavior. These organs are available to PiS but remain sparsely activated means, never a required
ritual or an automatic claim of self-evolution:

- `pi-subagents` owns Pi-native child sessions, recursion, async FleetView, steer/stop, and bounded
  project-local child refinement. Its `refine`, `refine.show`, and `refine.rollback` actions build an
  evidence-cited overlay under the current project's `.pi-subagents\refinements`; they do not rewrite
  the base agent, root Pi contract, safety, tools, acceptance, or scientific route. Refine only an
  agent with recent bounded evidence and verify a later fresh child; absence of an overlay means the
  capability is available but has not been consumed.
- `pi-autoresearch` is not in the main `prime` active default package set. An exact third-party
  package copy may remain on disk or in a cold snapshot; leave those bytes untouched. Address it
  only through a separately selected isolated benchmark scope if a future live task requires it.
- Hermes memory/session search is a recovery and learning organ. In policy-only mode it should be
  searched when durable context can change the action; it does not inject a second authoritative
  Pi identity, task queue, or scientific ontology.
- The MCP adapter discovers servers on demand behind a small proxy surface. Installing or updating
  it does not justify adding MCP servers, exposing their schemas to every turn, or treating an empty
  server catalog as a maturity gap.

The useful body loop is always consumer-shaped: real friction -> bounded diagnosis -> isolated
candidate -> positive/negative/fresh evidence -> keep or rollback -> return to the interrupted real
activity. Record who detected the friction first and whether the root actually absorbed the child or
tool result into a changed judgment.

## XINAO repository entry

When the live activity explicitly addresses XINAO research or its local mechanics, enter through:

- Current live world repository: `E:\CODEX_CLEANROOM\workspace`
- Current XINAO instructions: `xinao\AGENTS.md` and `xinao\README.md`
- Current entry map: `semantics\xinao\01_XINAO_ENTRY_MAP_V2.txt`

Verify the repository identity and local instructions live. This is a read-only cross-repository
entry for an explicitly named Pi activity, not an account/body attachment or shared write grant.
The retired `E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research` worktree is cold provenance,
recoverable from `E:\XINAO_COLD_STORAGE\xinao-native-research-retirement-20260813-1855`; it is not
a current CLI or startup input. Address it only for a current, named provenance-recovery task.
`C:\Users\xx363\Desktop\历史备用 不动` remains read-only.
