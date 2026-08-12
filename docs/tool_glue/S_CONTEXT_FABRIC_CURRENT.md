# S Continuous Context Runtime — Current Production Contract

Status: first production slice, 2026-08-13
Source brief: `C:\Users\xx363\Desktop\持续上下文运行时.txt`
Source SHA256: `D5D42CCECE491CD3937ACA940733B92A72F3F54C08BC3F73138A6E8F006BFC62`

## Consumer result

A fresh or compacted S/B Codex carrier can reconstruct a bounded working view
from the same persistent human--S interaction world. The user does not have to
turn each correction into a new rule or repeat the causal history behind it.
The runtime preserves exact surfaced conversation events and treats every
compact, identity, correction edge, and hot context as a rebuildable
projection.

This is continuity evidence, not an autonomous subject, task source, authority,
or continuation command. Current user words, current live authority, and
mechanical reality remain outside and above retrieved history.

## Current implementation

| Layer | Current carrier | Property |
|---|---|---|
| Canonical conversation events | `context_fabric.sqlite3/events` | append-only triggers, exact UTF-8, idempotent source key, per-event hash chain |
| Deterministic lexical index | `event_terms` | local Latin tokens plus Chinese character n-grams; no model/network dependency |
| Versioned projections | `projections` + `projection_sources` | exact source event IDs and source-span hash; append a new version, never overwrite |
| Correction/scope graph | `relations` | `corrects`, `supersedes`, `refines`, `continues`, `contradicts`, `scopes`; non-authoritative |
| Working view | `render_materialized_context()` | same-session hot tail first, then same-carrier fallback, query-relevant raw, active projections, and correction/scope edges |
| Existing live state | `CurrentSituation` + `RuntimeObservation` | separately rendered and combined by the hook; neither is promoted to event truth |

Source and consumer entrypoints:

- `services/agent_runtime/context_fabric.py`
- `services/agent_runtime/codex_situation_hook.py`
- `scripts/codex_situation_context_hook.py`
- `scripts/manage_context_fabric.py`

Default state root:

```text
D:\XINAO_RESEARCH_RUNTIME\state\S_Context_Fabric\
    context_fabric.sqlite3
    context_fabric.sqlite3-wal
    context_fabric.sqlite3-shm
```

The installed root has inheritance disabled and grants full control only to
the current Windows user, `SYSTEM`, and local `Administrators`; database and
snapshot children inherit that exact ACL. This is a machine deployment fact,
not a portable guarantee, so recovery/install readback must inspect the target
ACL. Re-enabling parent inheritance is the permission rollback.

SQLite is the canonical event store in this slice. Surfaced user/assistant
messages also have a cross-source turn identity, so a later rollout backfill
does not duplicate an event already captured by the live hook. WAL is a
mechanical part of the same database, not another truth source. `PRAGMA
quick_check`, replay of the hash chain, exact event lookup, and rebuildable
indexes are the recovery readbacks.

## Mount and admission policy

The policy is implemented by `evaluate_mount()` and guarded by negative tests;
it is not a conversational reminder.

Allowed `CODEX_HOME` identities:

```text
C:\Users\xx363\.codex                         -> s-primary
C:\Users\xx363\.codex-s-hardmode-account-b  -> s-account-b
```

Both are carriers of one `s-b-engineering-body` interaction world. Events keep
their carrier identity for provenance while reconstruction may use the shared
world. Unknown homes fail closed. A cwd under `E:\CODEX_CLEANROOM` also fails
closed even if an S/B environment was launched incorrectly.

There is no auto-discovery, auto-mount, or fallback into CodexA/C, the cleanroom
body, a new-repository Sol, or a fresh research branch. Those consumers have no
Context Fabric hook entry. Any future handoff out of S is an explicit export of
selected event IDs/material only; it is not retrieval or mount inheritance.

## Capture contract

The hook records only surfaced messages and lifecycle boundaries:

| Hook | Stored event | Model context effect |
|---|---|---|
| `UserPromptSubmit` | exact user message | current message is excluded; related prior evidence may be returned |
| `Stop` | `last_assistant_message` | none; it never blocks or auto-continues |
| `SessionStart` | carrier boundary | `resume`/`compact` may receive a bounded view; startup does not revive work |
| `PreCompact` / `PostCompact` | compaction boundary | none; immediate compact re-entry remains owned by `SessionStart(source=compact)` |
| `SessionEnd` | carrier boundary | none |

Rollout backfill is an explicit, idempotent CLI operation. The importer consumes
only `event_msg/item_completed` `UserMessage` and `AgentMessage` records from an
allowlisted S/B sessions root. It ignores injected developer/user wrappers,
reasoning, tool calls, tool results, and encrypted product state. The transcript
format is treated as a versioned best-effort import surface, not a stable hook
dependency.

## Secret and authority admission

“Lossless” applies to admitted surfaced conversation, not credential material.
A message matching known credential/token/private-key patterns is represented
by its SHA256 and character count; its bytes are not stored or indexed. Tool
output is not imported in this slice. Derived projection text has a write-time
secret gate.

The store remains local plaintext. The narrowed ACL prevents ordinary local
users from reading it, but it does not protect against the current account,
Administrators, SYSTEM, disk compromise, or a deliberately authorized export.

Every returned working view carries:

```json
{
  "authority": false,
  "instruction_source": false,
  "completion_claim_allowed": false,
  "current_prompt_included": false
}
```

Retrieval cannot select a parent, task, owner, route, Stop state, account,
payment, or external effect. A 201-day-old instruction remains historical
evidence. Current authority is not inferred from event recency or lexical score.

## Projection and correction semantics

A projection is appended with a semantic key, version, temporal scope, status,
aliases, exact source events, and a source-span hash. A newer version may name
the older projection it supersedes. The old projection and all raw evidence
remain available. Replaying an identical projection or relation specification
is idempotent; a material semantic change appends a new projection version.

Correction lineage is explicit rather than an in-place memory edit. A typical
shape is:

```text
old assistant/user event
    <- corrects - user correction event
    -> current scoped semantic projection
```

Historical experiment `arm C` and current launcher/account-slot `C` therefore
remain different scoped identities even when both are lexically retrieved.

## Operations

All repository Python commands use the declared `uv run` environment:

```powershell
uv run python scripts/manage_context_fabric.py initialize

uv run python scripts/manage_context_fabric.py import-rollout `
  --codex-home C:\Users\xx363\.codex `
  --rollout <exact-s-rollout.jsonl>

uv run python scripts/manage_context_fabric.py inspect --query "C并发研究" `
  --session-id <current-session-uuid> --carrier-id s-primary
uv run python scripts/manage_context_fabric.py event --event-id <event-id>
uv run python scripts/manage_context_fabric.py inventory
uv run python scripts/manage_context_fabric.py verify
uv run python scripts/manage_context_fabric.py snapshot `
  --output-dir <new-empty-snapshot-directory>

pwsh -NoProfile -NonInteractive -File scripts/Protect-SContextFabricState.ps1
pwsh -NoProfile -NonInteractive -File scripts/Protect-SContextFabricState.ps1 -Apply
```

`project --spec-file` and `relate --spec-file` are explicit engineering
operations. They do not run automatically inside the hook.

The ACL helper is audit-only unless `-Apply` is supplied. It refuses every
target except the exact production root, rejects links/reparse points, and
requires a readback containing only the current Windows user, `SYSTEM`, and
local `Administrators`.

`snapshot` uses SQLite's online backup API, then replays the copied event chain
and writes `snapshot.v1.json` with the database hash, event count, chain tip,
and integrity result. The snapshot contains raw admitted conversation, inherits
the local S runtime directory's filesystem protection, and is not an encrypted
vault. It is deliberately not folded into a generic code-recovery archive or
exported across bodies.

## Failure and recovery

The hook does not initialize schemas, import rollouts, call a model, create an
embedding, or wait on a daemon. Missing/corrupt/busy Context Fabric state is
omitted and the existing human-words-first L0 continues. `Stop` never returns a
blocking decision. A failed optional capture cannot suppress a user turn.

Recovery order:

1. disable capture with `CODEX_CONTEXT_FABRIC_DISABLE=1` if immediate isolation is required;
2. create an online `snapshot` when the live database remains readable;
3. otherwise preserve the database/WAL/SHM exact bytes before repair;
4. run `verify` and SQLite integrity readback on the live store and snapshot;
5. restore from a verified exact snapshot or re-import allowlisted rollout sources;
6. rebuild projections/indexes from canonical events before re-enabling hot use.

Do not “repair” a broken chain by updating or deleting rows. Compensating facts
and projection versions append; canonical history does not mutate.

## Deliberately deferred

The first slice does not claim automatic semantic understanding, perfect
compaction, embedding/vector quality, a graph database, automatic
CurrentSituation writes, legal erasure of append-only backups, or measured
longitudinal reduction of user burden. Multi-level local/activity compacts and
semantic clusters are supported as versioned projection types but remain
explicit until fresh behavior evidence justifies an automatic producer.

The acceptance suite proves engineering predicates only: body admission,
append-only/idempotent capture, secret withholding, importer filtering, Chinese
short-phrase reconstruction, correction edges, bounded non-authority context,
same-session hot-tail isolation, concurrent chain integrity, fail-open hooks,
fresh S/B carrier reconstruction, and cleanroom denial.
