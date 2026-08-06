# Native Codex subagent trajectory capability probe

This is a one-case, on-demand Promptfoo profile. It temporarily enables Codex's
native `multi_agent` feature only on the fresh app-server process created for
the case. It does not change either persistent `CODEX_HOME` configuration and
is intentionally excluded from the ordinary `core` and `deep` profiles.
The prompt names the native collaboration object and completion ruler but does
not grant one-off subagent permission; selection relies on the active standing
delegation rule loaded from `CODEX_HOME`.

The disposable fixture makes the observable roles different:

- the parent Owner must directly read `owner_anchor.txt`;
- one bounded native child thread reads the separable worker input and returns
  a terminal candidate;
- after the explicit completed terminal, the parent adopts its value into
  `adoption.json`;
- the parent invokes `consumer.py` with a live fixture nonce, whose successful
  output is the real consumer readback.

`assert_trajectory.js` rejects a parent that reads the worker inputs itself and
a parent that only relays child messages without the direct anchor read,
post-terminal adoption, nonce-bearing consumer invocation, and final answer.

The scorer requires the parent app-server turn to expose completed
`collabAgentToolCall` notifications in the strict order `spawnAgent`, `wait`
with the same child in `agentsStates` as `completed`, nonce-bearing consumer
command, then final answer. Child-internal command/tool steps are not attached
to the parent provider turn, so this case deliberately does not claim a
child-internal tool trajectory.

The first local probes against Promptfoo 0.121.18 and Codex 0.146.0 exposed a
narrower boundary even with both native feature flags enabled: a
`subAgentActivity(kind=started)` carried the child thread ID, but the completed
`wait` carried empty `receiverThreadIds` and empty `agentsStates`. The child did
not have an observable terminal in the parent trace; the parent later acted as
though it had a candidate and passed the consumer. The scorer intentionally
rejects that shape; it must not turn an inferred terminal into a runtime claim.
That Promptfoo trace predates removal of the one-off authorization sentence and
is retained only as provider-serialization counterevidence, not as evidence
that the active standing rule autonomously selected native delegation.

Two fresh `codex exec --json --ephemeral` probes were thinner still. The first
spawn was rejected because a specialized agent type was combined with a
full-history fork. After the prompt required the default inherited child type,
the second spawn was rejected because the root thread was not found. In both
runs JSONL exposed only an empty `wait` and later parent actions, while the final
answer claimed a completed child. Therefore direct JSONL is not a faithful
positive consumer in Codex 0.146.0 either.

Current status is deliberately **fail-closed**: this profile is a diagnostic
capability regression, not a native multi-agent runtime pass. A positive claim
requires a fresh trace containing the actual spawn identity, a completed child
terminal for that same identity, and the Owner's later nonce-bearing consumer
call. The synthetic complete-lifecycle test checks the scorer contract only; it
does not substitute for such a trace.

Run only this fresh case with:

```powershell
.\scripts\run_behavior_regression.ps1 -Profile subagent -MaxConcurrency 1 -MaxErrorRetries 0
```
