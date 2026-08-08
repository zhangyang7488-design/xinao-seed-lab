---
name: understand-and-steer-prime
description: Diagnose and operate the live PiS 0.84.1 subject without confusing model, profile, session, TUI, extensions, workers, or authority. Use when Codex or another local supervisor must inspect the exact PiS TUI, send a prompt, steer an active turn, queue a follow-up, abort work, enforce Stop, poll consumption, or verify the resulting trajectory and real effect.
---

# Understand and steer PiS

Treat PiS as a complete working subject:

`behavior = model + active instructions + Pi runtime + profile body + native session + tools + feedback`

This Skill defines how to operate the communication edge. The transport is the profile-local `supervisor-ingress.ts` extension; the Skill is not a daemon, session owner, router, or second state truth.

## Bind the live target

1. Recover the current human parent result, active object, burden, real consumer, authority and Stop boundary before sending anything.
2. Run `list` or `get_state` and capture the exact `profile`, process `instance_id`, native `session_id`, `cwd`, idle state and last event sequence.
3. Re-read state before every mutating command. Never infer a target from cwd, a shortcut name, the newest session file, or an earlier process instance.
4. Choose one delivery semantic:
   - `prompt`: start an intended user turn; accepted only while idle.
   - `steer`: amend active work at the next Pi boundary; while idle it starts a normal turn.
   - `follow_up`: queue a later user turn; while idle it starts a normal turn.
   - `abort`: cancel the current operation but keep the TUI alive. It does not promise to drain already queued messages.
   - `stop`: fail-closed Stop by shutting down the addressed PiS process, which also removes queued work. The durable native session remains resumable.
5. Poll the same process and session after delivery. A transport ACK or `dispatch_requested` is not `runtime_accepted`; acceptance is not `message_consumed`; consumption is not `agent_settled`; settled is not effect.
6. Verify effect in the native transcript, produced artifact, repository/live consumer, or observed behavior. Then return to the surviving parent activity.

## Use the profile client

The client reads delivery content from stdin or a file so prompts do not leak through the process command line:

```powershell
node .\scripts\pi-supervisor-command.mjs list
node .\scripts\pi-supervisor-command.mjs get_state

$text | node .\scripts\pi-supervisor-command.mjs steer `
  --profile prime-s --instance <instance_id> --session <session_id>

node .\scripts\pi-supervisor-command.mjs get_events --since <last_sequence>
node .\scripts\pi-supervisor-command.mjs wait `
  --profile prime-s --instance <instance_id> --session <session_id> `
  --request-id <request_id> --until message_consumed --since <last_sequence>
```

Use [pi-runtime-and-control.md](references/pi-runtime-and-control.md) for the protocol, evidence grades, restart behavior, negative cases, and communication limits.

## Preserve roles

Codex remains the currently appointed formal Owner for adoption, writes, commitments, final verification and parent completion. PiS may be the real researcher and evolving subject; its response or self-assessment is candidate evidence. Workers remain candidate labor. PiB is not a second target for this capability and receives no PiS extension or Skill projection.

Do not edit session JSONL, simulate keystrokes, attach a second writer, silently create a new session, or equate a green transport test with mature PiS behavior.
