# PiS recovery map for Codex

Use this map only after the current parent result and active Pi object are bound.

## Durable meaning

- Family contract: `E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island\AGENTS.md`
- Current capability lineage:
  `E:\XINAO_RESEARCH_WORKSPACES\pi-local-cognition-contract-island\cognition\CURRENT_CAPABILITY_LINEAGE.md`
- PiS surface island: `E:\XINAO_RESEARCH_WORKSPACES\prime-s-local-cognition-island`
- PiB surface island: `E:\XINAO_RESEARCH_WORKSPACES\prime-agent-local-cognition-island`

The family contract carries stable Pi-specific intent and lifecycle. A surface island carries that
surface's body lineage, candidate evidence, acceptance, and rollback. Neither creates a task.

## Live products

- PiS profile: `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s`
- PiB profile: `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-b`
- Pi engineering source:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1`
- PiS desktop wrapper: `C:\Users\xx363\CodexLaunchers\Open-Prime-S.ps1`
- PiB desktop wrapper: `C:\Users\xx363\CodexLaunchers\Open-Prime-Agent-Account-B.ps1`

Verify launcher target, active account binding, Pi/Node version, settings, installed packages,
contract projection, overlay manifest, native session identity, process instance, and target
consumer only to the degree they intersect the current action.

PiS's numpad transcript-follow behavior is sourced and installed from:

- `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\helpers\PrimeS-NumPadEnter-Follow.ahk`
- `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\scripts\Set-PiSNumpadEnterFollow.ps1`

It is scoped to the exact `prime S` Windows Terminal title. The profile keybinding adds `F12` only
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

## Communication

- Source operation Skill:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\surface-overlays\prime-s\skills\understand-and-steer-prime\SKILL.md`
- Source client:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\surface-overlays\prime-s\skills\understand-and-steer-prime\scripts\pi-supervisor-command.mjs`
- Default PiS pipe: `\\.\pipe\xinao-pi-supervisor-prime-s-v1`

The client accepts delivery content on stdin or from a file. Always list/read state before a
mutation and bind `profile + instance + session`. After restart, a resumed native session has a new
process instance and stale mutations must fail.

## Body labs and adoption

- Lab root: `D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\body-labs\prime-s`
- Lab creator:
  `E:\XINAO_RESEARCH_WORKSPACES\S\infra\pi_upstream_dual_entry\v1\scripts\New-PiSBodyLab.ps1`

A lab is session-empty and account/profile isolated. Installed candidates remain candidates. Before
active PiS adoption, record the exact source/body version, config without secrets, credential
consumer path, positive and negative evidence, known-good preimage, and rollback procedure. After
adoption, fresh-launch PiS and re-run the real activity that exposed the gap.

PiB is outside the default write cone. Compare or promote to it only when the current parent names a
B-side consumer or rollback check.
