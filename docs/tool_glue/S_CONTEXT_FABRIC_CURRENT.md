# S Continuous Context Runtime — Current Production Contract

Status: completion implementation present; hot-consumer adoption remains a separately verified claim, 2026-08-13
Source brief: `C:\Users\xx363\Desktop\持续上下文运行时.txt`
Source SHA256: `D5D42CCECE491CD3937ACA940733B92A72F3F54C08BC3F73138A6E8F006BFC62`

## Contract and feature level

`Context Fabric` is one local, S/B-only, event-sourced evidence store. Its canonical schema remains `s.context_fabric.v1`; its completion feature level is `s.context_runtime.complete.v1`. New initialization creates both levels. A legacy v1 database is intentionally not upgraded by initialization, a hook, or ordinary read: it must be migrated explicitly. This prevents an optional continuity read from silently changing a live store.

The runtime reconstructs a bounded, source-linked historical working view. It is not a subject, task source, route selector, Owner, authorization, Stop decision, completion proof, or continuation command. Current user words, live authority, and mechanical reality remain above all retrieved material.

## Data classes and provenance

| Class | Carrier | Contract |
|---|---|---|
| Canonical occurrence evidence | `events`, `event_terms`, event-parent/artifact bindings | append-only, idempotent source/turn identity, exact admitted UTF-8 or withheld secret placeholder, linear event hash chain |
| Canonical typed tool receipt | `artifacts` and optional content-addressed blobs | ordinary tool surfaces are hash-only; only an explicit allowlisted sanitizer may retain a bounded, non-secret exact blob |
| Derived state | projections, relations, producer runs/metadata, lineage nodes, materializations | append-only and hash-verifiable, source-linked, non-authoritative, rebuildable from canonical evidence plus explicit specs |
| Recovery copy | snapshot database, manifest, exact admitted blobs | pinned prefix copy, independently verified before restore; not a new authority source |

SQLite plus its WAL/SHM are one storage implementation, not separate truths. Canonical rows never update/delete. `verify` checks the event chain. `verify-full` checks the exact current schema/meta and append-only triggers, SQLite/FK integrity, event/index/association identities, projection/relation/producer/lineage/materialization provenance, and the complete admitted CAS inventory. It is tamper-evident validation, not cryptographic immutability or an external rollback anchor.

## Explicit migration

Run migration only with an intentional target and a new/empty non-link backup directory. In production the backup directory must be an ACL-protected sibling outside the live root, and its ACL must be read back before migration. The migration snapshots the v1 preimage first, reopens and strictly verifies that recovery copy, stores its manifest hash, adds completion tables/metadata, backfills only derived metadata, and runs `verify-full` while proving that the canonical event count and hash tip did not change. It is dry-runnable and idempotent; unknown/future feature levels fail closed.

```powershell
uv run python scripts/manage_context_fabric.py migrate --dry-run
uv run python scripts/manage_context_fabric.py migrate `
  --backup-root <new-empty-pre-migration-snapshot-directory>
uv run python scripts/manage_context_fabric.py verify-full
uv run python scripts/manage_context_fabric.py restore-preimage `
  --snapshot-dir <pre-migration-snapshot-directory> `
  --target-dir <absent-or-empty-legacy-restore-directory> `
  --expected-manifest-sha256 <manifest-sha256>
```

This is a schema/evidence transition, not evidence that a fresh carrier has been correctly rehydrated in the installed product.

## Admission and safety

Only the S/B homes mount the shared `s-b-engineering-body`; an unknown home or a clean-room cwd (`E:\CODEX_CLEANROOM`) fails closed. The installed JSON adapter also binds admission to its mechanically observed cwd, not just the event's reported cwd. There is no auto-discovery or history inheritance into CodexA/C, the clean-room body, a Sol, or a research session.

Admitted user/assistant surfaced text is exact unless secret-like, in which case only a SHA256 and character count are retained and indexed bytes are withheld. New hook metadata stores the normalized cwd only as a digest; legacy v1 rows remain immutable and can still contain the cwd captured by the old hook. The installed hooks continuously admit surfaced dialogue and lifecycle boundaries. `import-rollout` is a separate incremental recovery/backfill consumer: it admits strict surfaced messages and a small recognized set of completed tool item types, pins its committed prefix, and refuses rewrites, gaps, malformed complete records, links, or session escapes. It is not an installed daemon or an app-server subscriber. Tool calls, reasoning, developer wrappers, incomplete tool results, and arbitrary tool bodies are rejected or ignored. Recognized tool surfaces become typed, hash-only artifacts plus an empty tool event with safe metadata. No tool body may reach materialization through this route.

The state is local plaintext protected by the runtime ACL; it is not an encrypted vault and does not protect against the current account, Administrators, SYSTEM, disk compromise, or an authorized export. Store paths, session paths, blobs, snapshot sources, manifest members, and restore targets reject path escapes and links/reparse redirects; restore refuses a non-empty/live target. Current account credentials, tokens, passwords, API keys, cookies, and similar secrets are never admissible context.

## Projection, correction, and temporal semantics

Explicit projections retain their exact source event IDs and source-span hash. Completion adds three deterministic structural producers:

- `s.context_runtime.closed_round@v1` creates a structural envelope only for a closed surfaced user/assistant turn; it does not infer a new fact.
- `s.context_runtime.lineage_segment@v1` creates a bounded structural `activity_compact` only at an observed `PostCompact` or `SessionEnd` boundary; it records event kinds and source refs but does not infer a human activity, parent, goal, or open frontier.
- `s.context_runtime.current_seed@v1` creates a source-tip seed describing the canonical boundary; it is not a task or an understanding.

Producer run ID, version, configuration hash, exact event-tip hash, and output refs are recorded in the same SQLite transaction as every automatic projection. A failed run therefore commits neither its output nor its completed receipt; `verify-full` also checks both directions between automatic projection metadata and run outputs. The installed hook runs only a trigger-scoped bounded producer after a captured `Stop`, `PostCompact`, or `SessionEnd`; it never rescans full history on the 3–5 second hook path. Full replay/backfill remains the explicit `produce` manager operation. Producers do not process an open current prompt before that prompt's retrieval boundary.

`correct --spec-file` records an explicit `corrects` relation and bitemporal metadata: recorded/as-of event boundary plus a declared effective interval (`valid_from`/`valid_to` or event bounds) and temporal basis. Supplied instants require an explicit timezone and are normalized to canonical UTC before identity hashing, comparison, and verification; equivalent offset spellings therefore have the same ordering semantics. Materialization can render current or historical views without rewriting old evidence. A correction suppresses the prior projection/evidence only in the selected effective view; explicit event drill-down and earlier `as_of` views remain available. Every surfaced user correction is preserved as raw evidence by the normal hook, but semantic adoption still requires an explicit source-linked replacement projection plus correction write. The runtime does not guess that relation from words such as “纠正”.

## Session lineage and working views

Each captured `SessionStart` writes a lineage node. A `compact` node becomes `resolved` only when the runtime actually observes an earlier same-carrier, same-session `PostCompact` boundary; its evidence quality is `same_session_ordered`. Codex 0.147 does not expose an exact resume-parent locator to this hook, so `resume` remains `unresolved` and creates no inferred continuation edge. An explicit cross-session branch parent must resolve to an existing node on the same carrier. Session identity cannot be inferred from chronology, cwd, lexical similarity, or a matching UUID on another carrier.

`materialize_context()` renders a bounded view pinned to an event tip, optional `as_of_event_id`, optional effective time, query hash, session/carrier, source refs, and lineage status. The active hook uses its compatibility `render_hook_context()` path, which captures the lifecycle event, records lineage, and renders a non-persistent bounded materialization. The public `rehydrate_context()` API separately makes a persisted, mount-checked materialization and sets `continuation_authorized=false`; it is not itself the installed hook's continuation mechanism.

The current prompt is excluded from its own retrieval boundary, including from a producer run made after capture. An unresolved fresh session does not receive a parallel TUI tail merely because it shares a carrier; cross-session material requires query-relevant evidence. These are implementation/test predicates, not proof that a real fresh/compact/resume product flow has been accepted.

Every rendered view carries `authority=false`, `instruction_source=false`, `completion_claim_allowed=false`, and `current_prompt_included=false`.

## Snapshot and restore

`snapshot` creates a new/empty, non-link directory containing a SQLite backup, only the exact blobs named by that database, and `snapshot.v2.json`. The manifest pins feature level, database SHA256, canonical event count/tip, and artifact inventory. It is a consistent prefix: later source appends do not change it.

`restore` first rejects occupied/live targets, then checks source-root and manifest-member containment, database/blob hashes, and the full source database. It copies into a same-parent hidden staging directory, verifies the staged store and canonical count/tip, writes `restore.complete.v1.json` last, and only then atomically renames the staging directory to the absent/empty target. It never overwrites a live target. A successful restore proves only its current local readbacks, not hook re-enablement, task selection, or consumer recovery.

## CLI

All repository commands use `uv run`:

```powershell
uv run python scripts/manage_context_fabric.py initialize
uv run python scripts/manage_context_fabric.py migrate --dry-run
uv run python scripts/manage_context_fabric.py import-rollout `
  --codex-home C:\Users\xx363\.codex --rollout <exact-s-rollout.jsonl>
uv run python scripts/manage_context_fabric.py project --spec-file <projection.json>
uv run python scripts/manage_context_fabric.py relate --spec-file <relation.json>
uv run python scripts/manage_context_fabric.py correct --spec-file <correction.json>
uv run python scripts/manage_context_fabric.py produce --through-seq <event-seq>
uv run python scripts/manage_context_fabric.py inspect --query "C并发研究" `
  --session-id <canonical-session-uuid> --carrier-id s-primary
uv run python scripts/manage_context_fabric.py lineage --session-id <canonical-session-uuid>
uv run python scripts/manage_context_fabric.py verify-full
uv run python scripts/manage_context_fabric.py snapshot --output-dir <new-empty-snapshot-dir>
uv run python scripts/manage_context_fabric.py restore `
  --snapshot-dir <snapshot-dir> --target-dir <absent-or-empty-staging-dir> `
  --expected-manifest-sha256 <manifest-sha256>
```

`project`, `relate`, and `correct` are explicit engineering writes. The normal hook does not infer their semantic content. The ACL helper remains audit-only without `-Apply` and must be read back against its exact target.

## CurrentSituation compatibility and unproven claims

`CurrentSituation` remains a separate, exact-session, provisional checkpoint with its own explicit `initialize`/CAS `apply`/`retire` lifecycle. It is not canonical Context Fabric evidence and is not automatically written from events or projections. During migration/availability fallback, `SessionStart(source=resume|compact)` may use its bounded checkpoint only when Fabric produced no materialization; the hook does not inject two competing current views. Neither surface creates a task or authority.

The completion implementation and local tests establish explicit migration, full current-schema verification, bounded materialization, lineage classification, contained staged restore, and negative-security predicates including extended-path clean-room denial, DB-busy fail-open, cursor corruption, concurrent deduplication, trigger/meta/derived tamper, snapshot-root links, and manifest path escape. This still does **not** establish cryptographic immutability, detection of a separately valid older snapshot without an external tip anchor, installed live S/B-hook acceptance across actual fresh/compact/resume windows, automatic CurrentSituation revision, autonomous world revision, a persistent subject, or measured long-term reduction in user repetition/correction burden. Those require live consumer and longitudinal behavioral evidence.
