# PiS runtime and native control

## Active seam

The PiS desktop launcher owns one fullscreen Pi 0.84.1 process and one native session. Its profile-local extension opens the profile-specific Windows named pipe and invokes Pi's official in-process `sendUserMessage`, `abort`, and `shutdown` APIs. It does not attach another agent, edit the transcript, or create an RPC-side session.

The pipe protocol is newline-delimited JSON. Requests and responses use `xinao.pi_supervisor.v1`. Read-only calls are `list`, `get_state`, and `get_events`. Mutating calls require all of:

- `profile=prime-s`;
- the fresh process `instance_id`;
- the exact native `session_id`;
- a unique `request_id`.

A process restart changes `instance_id` even when `--continue` resumes the same session. A stale mutating request must therefore fail rather than silently controlling the replacement process.

Delivery requests carry `content` only inside the local pipe. Operational events retain `request_id`, command, timing and `message_sha256`, never the plaintext.

## Evidence ladder

| Evidence | Meaning | Still not proven |
|---|---|---|
| `dispatch_requested` | extension requested Pi delivery | Pi accepted the input |
| `runtime_accepted` | Pi's extension input hook observed it | model began that user message |
| `message_consumed` | the user message reached Pi's agent message stream | useful trajectory or effect |
| `turn_end` / `agent_settled` | addressed run reached a runtime boundary | result is correct or adopted |
| transcript/artifact readback | claimed output exists | external consumer changed |
| consumer/effect readback | intended reality changed | whole parent is complete |

Never collapse the ladder. `get_events` is a bounded in-process ring and resets on restart; the native session transcript remains the durable conversation record.

## Semantics and limits

- `prompt` rejects a busy target so a caller must deliberately choose `steer` or `follow_up`.
- `steer` enters the current run at Pi's next model/tool boundary.
- `follow_up` waits for the current work to finish.
- `abort` invokes Pi's official current-operation abort. Pi 0.84.1's public extension context does not expose queue clearing, so the response reports whether pending messages existed and must not claim a full Stop.
- `stop` invokes the official process shutdown after acknowledging the exact request. Use it for an explicit human Stop or when queued work makes abort insufficient. Confirm the pipe disappears and no owned child process continues.

## Required negative checks

Before calling this edge verified, prove:

- wrong profile, process instance, or session is rejected;
- a stale instance is rejected after restart;
- `prompt` while busy is rejected;
- ACK without later consumption is not reported as effect;
- PiB has no PiS pipe, extension, or Skill projection;
- Stop shuts down the addressed PiS process and leaves its durable session resumable;
- a fresh desktop launch restores the edge without manual file copying.

If the extension cannot expose the exact live target, communication is unavailable. Do not fall back to keyboard injection or transcript edits.
