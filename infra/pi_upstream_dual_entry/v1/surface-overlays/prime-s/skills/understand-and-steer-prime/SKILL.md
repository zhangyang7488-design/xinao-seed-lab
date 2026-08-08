---
name: understand-and-steer-prime
description: Diagnose and operate the live PiS 0.84.1 subject without confusing model, profile, session, TUI, extensions, workers, or authority. Use when Codex or another local supervisor must inspect the exact PiS TUI, send a prompt, steer an active turn, queue a follow-up, compact an overgrown native session, abort work, enforce Stop, poll consumption, or verify the resulting trajectory and real effect.
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
   - `compact`: while idle, invoke Pi's native compaction on the same durable session; optional instructions preserve the parent, live facts, decisions and return point without retaining raw tool noise.
   - `abort`: cancel the current operation but keep the TUI alive. It does not promise to drain already queued messages.
   - `stop`: request fail-closed shutdown of the addressed PiS process, aborting an active run first when necessary. Its ACK is not process-exit proof; require the addressed pipe/process to disappear. The durable native session remains resumable.
5. Poll the same process and session after delivery. A transport ACK or `dispatch_requested` is not `runtime_accepted`; acceptance is not `message_consumed`; consumption is not `agent_settled`; settled is not effect.
6. Verify effect in the native transcript, produced artifact, repository/live consumer, or observed behavior. Then return to the surviving parent activity.

Never type, paste, or stage supervisor text in the visible Pi editor. Native delivery must go through the pipe and an ordinary successful send is not reported until the exact request reaches `message_consumed`. Reusing a request ID is idempotent only for the same command and content hash; a conflicting reuse is rejected.

Pi 0.84.1 restores queued steer/follow-up text into the editor when an operation is aborted. The ingress therefore snapshots the editor, invokes the native abort, and removes only the exact supervisor-owned restored prefix when the complete before/after relation matches. It preserves any pre-existing draft byte-for-byte and leaves a mismatch untouched. `get_state` exposes only editor presence, byte length, and SHA-256, never its text.

## Use the profile client

The client reads delivery content from stdin or a file so prompts do not leak through the process command line. `--content-file` is only a transport input: the client expands the complete file into the Pi message, so it does not reduce Pi context. For long evidence or source material, prefer a short ingress message that names the exact existing read-only path, why it matters, the bounded reading target, and the parent return point; let Pi read the file through its own tools. Create one bounded handoff file only when no suitable source already exists. Keep short corrections as direct `steer`/`follow_up` messages and never turn per-step task files into a second queue or control plane.

```powershell
node .\scripts\pi-supervisor-command.mjs list
node .\scripts\pi-supervisor-command.mjs get_state

$text | node .\scripts\pi-supervisor-command.mjs steer `
  --profile prime-s --instance <instance_id> --session <session_id> `
  --request-id <unique_request_id> --until message_consumed `
  --since <last_sequence> --timeout 120000

node .\scripts\pi-supervisor-command.mjs get_events --since <last_sequence>
node .\scripts\pi-supervisor-command.mjs compact `
  --profile prime-s --instance <instance_id> --session <session_id> `
  --request-id <unique_request_id> --content-file <instructions.txt> `
  --until compact_completed --since <last_sequence> --timeout 120000
node .\scripts\pi-supervisor-command.mjs wait `
  --profile prime-s --instance <instance_id> --session <session_id> `
  --request-id <request_id> --until message_consumed --since <last_sequence>
```

Use [pi-runtime-and-control.md](references/pi-runtime-and-control.md) for the protocol, evidence grades, restart behavior, negative cases, and communication limits.

## Preserve roles

Authority follows the current named effect scope rather than a product identity. In the current XINAO repository scope, PiS is the formally appointed repository Owner and Codex is the broader user proxy and Pi-body supervisor; in another scope, rebind from current words and live contracts. A transport sender never gains adoption or completion authority merely by delivering text. PiB is not a second target for this capability and receives no PiS extension or Skill projection.

Do not edit session JSONL, simulate keystrokes, attach a second writer, silently create a new session, or equate a green transport test with mature PiS behavior.
