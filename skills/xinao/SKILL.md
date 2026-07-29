---
name: xinao
description: Operate the dedicated Xinao research system and its versioned local capabilities. Use whenever the user asks about 新澳/XINAO research, researcher containers, shadow accounts, frozen decisions, settlement, replay, capability correction, or continuation of the Xinao scientific mainline. Keep this path separate from ordinary worker dispatch and absorb all technical operation for the user.
---

# 新澳

Read [meta.md](references/meta.md) before changing or adding a Xinao capability. Read
[capabilities.v1.json](references/capabilities.v1.json) to select only a capability whose
source implementation is present; verify its live runtime status instead of trusting the file.

For the researcher container, run `scripts/xinao.py inspect` first. Invoke it with
`scripts/xinao.py research --question <material research question>`; derive all paths, hashes,
image identity, provider settings, mounts, and evidence locations internally. Return the bounded
receipt and research result in the Codex conversation. Do not require the user to run a command,
edit a file, or supply an internal field.

Do not route Xinao scientific researchers through the ordinary WorkerPool, its task contracts,
state roots, evidence roots, or completion semantics. Reuse low-level libraries only when the
scientific chain retains its own identity and tests prove the chains cannot cross.

Research topics are open. Treat the seven-family prior as advisory information and the current
ACTION-support reference as a separate downstream boundary. Never use either as research
admission. A successful container call proves only that the capability ran.

Capabilities marked `planned` are unavailable. Implement and verify them through the update
procedure in the meta reference before calling them; never emulate them with chat glue.
