---
name: xinao
description: Operate the dedicated Xinao research system and its versioned local capabilities. Use whenever the user asks about 新澳/XINAO research, researcher containers, shadow accounts, frozen decisions, settlement, replay, capability correction, or continuation of the Xinao scientific mainline. Keep this path separate from ordinary worker dispatch and absorb all technical operation for the user.
---

# 新澳

Read [meta.md](references/meta.md) before changing or adding a Xinao capability. Read
[capabilities.v1.json](references/capabilities.v1.json) to select only a capability whose
source implementation is present; verify its live runtime status instead of trusting the file.

For the researcher container, run `scripts/xinao.py inspect` first. Invoke it with
`scripts/xinao.py research --question <material research question>` and add `--material <local
UTF-8 evidence file>` only for exact files the current bounded call may disclose to the provider;
repeat the option when needed. The launcher freezes ordinary local evidence into its own sealed
bundle. Derive all paths, hashes, bundle identity, provider settings, mounts, and evidence locations
internally. Return the bounded receipt and research result in the Codex conversation. Do not require
the user to run a command, edit a file, construct a manifest, pre-seal a material, or supply an
internal field.

`source_status=available` means only that the implementation exists. Treat the runtime as callable
only when `inspect` returns `RUNTIME_READY`; pointer presence, an old successful receipt, an image
tag, or source tests are not substitutes. A call with materials must freeze them before runtime
probing, mount only the run-local snapshot read-only, bind the effective provider prompt and result
to the bundle hashes, and still return candidate-only research. Never expose generic file tools
while the provider credential is mounted in the same container.

Keep the bounded online research lifecycle separate from the durable background leg. When the
user asks to mature the ordinary research leg, finish its stable one-command install, inspect,
parallel isolated researcher calls, freeze, shadow settlement, replay, and feedback path before
building durable orchestration. A container image may implement that leg's execution boundary; it
does not authorize Temporal, a resident worker, a daemon, or another Owner. Never substitute
platform readiness for a real researcher result.

Before making a migration, proof, or preflight artifact a live admission condition, trace its bytes
to a real consumer in build, execution, recovery, settlement, or the returned evidence. If the
artifact is only read and discarded, keep it as optional audit evidence or retire the gate; do not
turn apparent rigor into an unbounded prerequisite. When a verified newer source capability is the
missing live link, install it transactionally through the stable entry and verify that entry in a
fresh process instead of continuing broader infrastructure work around an uninstalled candidate.

Do not route Xinao scientific researchers through the ordinary WorkerPool, its task contracts,
state roots, evidence roots, or completion semantics. Reuse low-level libraries only when the
scientific chain retains its own identity and tests prove the chains cannot cross.

Research topics are open. Do not inject seven-family grades or another inherited background menu
by default: active-parent background is optional and discardable, not attention allocation.
Resolve an ACTION-support reference only for a later, separately authorized downstream effect;
never use it as research admission or include it in this candidate-only prompt. A successful
container call proves only that the capability ran.

For shadow practice, read [shadow-practice-contract.v1.md](references/shadow-practice-contract.v1.md)
before designing, implementing, reviewing, or claiming an account, freeze, reveal, settlement,
replay, or feedback result. Preserve its concrete human-facing episode chain and its separate
account and knowledge axes; the contract is a downstream completion ruler, not a research menu.

Capabilities marked `planned` are unavailable. Implement and verify them through the update
procedure in the meta reference before calling them; never emulate them with chat glue.
