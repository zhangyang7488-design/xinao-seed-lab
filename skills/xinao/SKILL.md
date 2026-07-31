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

The additive host-side `research-state` carrier may bind successive calls of that same one-shot
instrument when a bounded continuity canary is useful:

- `scripts/xinao.py research-state genesis --root <D-or-E-series> --question <question>`
- `scripts/xinao.py research-state advance --root <series> --expected-head <sha256> --question <question>`
- `scripts/xinao.py research-state inspect --root <series>`
- `scripts/xinao.py research-state recover-partial --root <series>`

`advance` copies the exact prior state, candidate, result, and sealed receipt into the next
one-shot material bundle and commits only after sealed provider/material evidence validates. The
expected head is a compare-and-swap boundary. `recover-partial` only removes a validated,
uncommitted `series.json` left before the first head publish and preserves orphan CAS bytes; it is
not research resumption. Every result keeps `research_progress_claim_allowed`, `science_restored`,
`parent_complete`, and `completion_claim_allowed` false. This carrier proves neither multi-round
inquiry nor researcher role fitness and must remain distinguishable from a real long-running
ResearchEpisode.

## ResearchEpisode (multi-turn lab; candidate-only; Owner disposition separate)

Use `research-episode` for a real long multi-turn tool/web research episode that produces a
lab-authored immutable candidate. Supported Grok CLI pin: **0.2.117** (fail closed on mismatch).
Codex alone adopts/disposes/freezes. Feedback may inform a later version but never rewrites prior
history. **No** auto-freeze, auto-settle, next-task, daemon, Temporal/leg-B, or second Owner.

### Packaged Owner consumers (preferred; sealed `xinao-discovery` install)

Pool admission, Owner disposition write, feedback pack emit, and feedback bind require the
installed `xinao-discovery` package (console entry `xinao`), not a monorepo path walk. Fresh
isolated wheel/venv is sufficient. Compose one-shot only:

`pool-ingest | pool-ingest-result → write-owner-disposition → freeze-from-disposition → (settle) → emit-research-feedback-pack → feedback-bind`

- `xinao research-episode pool-ingest --pool-root <pool> --export <export.json> --manifest <candidate_manifest.v1.json>` — ResearchEpisode sealed export + candidate manifest only
- `xinao research-episode pool-ingest-result --pool-root <pool> --result <result.json> --receipt <receipt.json>` — **one-shot** researcher result+receipt public admission (historical `xrr_*` shape); alias `pool-ingest-oneshot`; never pretends episode-export provenance; forces `owner_adopted=false`
- `xinao prospective write-owner-disposition --owner-state-root <owner> --pool-root <pool> --payload <disposition.json>` — seals Owner disposition CAS; validates pool binding/hashes/role; never freezes/settles/adopts or starts next Episode
- `xinao research-episode emit-research-feedback-pack --portfolio-root <portfolio> [--period-index N]` — emits sealed research feedback pack from settled state only; never auto-starts next research
- `xinao research-episode feedback-bind --portfolio-root <portfolio> --feedback-content-hash <sha256>`

Skill aliases (`ingest-export`, `bind-feedback-material`) resolve to the same package functions
when the Skill runtime can import installed `xinao.science.*` first. Disposition write and
feedback emit remain package CLI one-shots (Codex invokes; worker/container candidate-only).

### Host Skill dual-container verbs (live attach; sealed images + tool-namespace receipt)

Long ResearchEpisode public vertical (Owner one-shots only; no daemon / no self-schedule):

1. `scripts/xinao.py research-episode start --root <D-episode> --question <question>`
2. `scripts/xinao.py research-episode ensure-pair --root <episode> --expected-head <sha256> [--research-profile OPEN_RESEARCH]`
3. `scripts/xinao.py research-episode attach-run --root <episode> --prompt <prompt> [--max-turns 16]`
4. `scripts/xinao.py research-episode checkpoint --root <episode> --expected-head <sha256> [--lab-relative path --progress-note ...]`
5. `scripts/xinao.py research-episode resume-live --root <episode> --expected-provider-session <uuid> --expected-head <sha256>`
6. `scripts/xinao.py research-episode export-candidate-evidence --root <episode> --attempt-cas-digest <sha256> --expected-head <sha256>`
7. `scripts/xinao.py research-episode cancel --root <episode>` (also best-effort `retire-pair`)
8. `scripts/xinao.py research-episode retire-pair --root <episode>`

Also available:

- `scripts/xinao.py research-episode status|resume --root <episode> ...`
- `scripts/xinao.py research-episode ingest-export --pool-root <pool> --export <export.json> --manifest <candidate_manifest.v1.json>`
- `scripts/xinao.py research-episode bind-feedback-material --portfolio-root <portfolio> --feedback-content-hash <sha256>`

`ensure-pair` is the production consumer that materializes disposable transport+tool containers
under the durable CAS head. Without it, `attach-run` has no live lease. Pair retirement never
creates a successor episode. Intermediate lab experiments/failures remain under the episode root.

Auth handle path order (path/mount only; never secret bytes): `XINAO_AUTH_HOST_PATH` →
`GROK_HOME/auth.json` → `~/.grok/auth.json` → fail closed. Transport uses sealed
`xinao_researcher_internal` by default; tool remains `network=none`. Host modules
(`docker_create_specs`, `native_grok_session`, MCP binding) ship inside the skill-bundle under
`scripts/host_modules/` — never monorepo/`~/.codex/docker` walks at installed runtime.

Boundaries:

- **Candidate-only:** export and pool ingest force `owner_adopted=false`, never freeze/settle.
- **Owner-only disposition:** adoption/freeze/settlement remain separate Codex Owner artifacts.
- **No self-scheduling / no leg-B:** ensure-pair, attach-run, cancel, and retire-pair never create
  the next episode, Temporal workflow, or daemon continuation.
- **Sealed inputs / outcome isolation:** dual-pair mounts forbid shadow ledger, freeze, outcome,
  settlement, and auth-on-tool; lab writes stay under episode lab/outbox.
- **`absorb` is deprecated placeholder** for a local outbox review file — **not** candidate-pool
  admission. Prefer package `pool-ingest` (episode export), `pool-ingest-result` (one-shot
  result+receipt), or Skill `export-candidate-evidence` + `ingest-export`.
- Productive lab evidence requires **successful** tool-executor sealed event hashes (`status=ok`
  only; denied/error/timeout never count even with a real sidecar hash or planted lab file).

For shadow lifecycle, require `inspect` to report `shadow.runtime_status=AVAILABLE` (source
registration, live image shadow labels, and `installed_projection.status=ALIGNED`). Then use the
installed Skill only:

Legacy flat (first-period / single-episode) consumer verbs:

- `scripts/xinao.py shadow init --root <episode> --seat-id <id> --portfolio-ref <ref>`
- `scripts/xinao.py shadow inspect|status --root <episode>`
- `scripts/xinao.py shadow freeze --root <episode> --request <freeze.json>` — **always** `FLAT_FREEZE_NOT_PRODUCTION`; never accepts caller-authored `frozen_at` as production freeze. Not the Owner path.
- `scripts/xinao.py shadow settle --root <episode> --outcome <outcome.json>` — settle already sealed historical/fixture freezes only
- `scripts/xinao.py shadow replay --root <episode>` — replay already sealed historical/fixture episodes

Same-seat portfolio continuity verbs (multi-period consumer surface; not scientific promotion):

- `scripts/xinao.py shadow portfolio-init --root <portfolio> --seat-id <id> --portfolio-ref <ref>`
- `scripts/xinao.py shadow portfolio-inspect --root <portfolio>`
- `scripts/xinao.py shadow portfolio-freeze --root <portfolio> --request <freeze.json>` — **always** `PORTFOLIO_FREEZE_CLI_NOT_PRODUCTION`; never calls production freeze. Not the Owner path.
- `scripts/xinao.py shadow portfolio-settle --root <portfolio> --outcome <outcome.json>`
- `scripts/xinao.py shadow portfolio-feedback --root <portfolio> --kind <FeedbackKind> [--feedback-ref <ref>] [--reason-code <code>] [--notes <text>]`
- `scripts/xinao.py shadow portfolio-replay --root <portfolio> --period-index <n>`

**Single production freeze path (packaged discovery CLI, not a daemon):**

- `xinao prospective capture --authority-root <Owner auth root> --contract <AuthorityContract> --expected-contract-sha256 <hex>`
- `xinao prospective reveal --authority-root <Owner auth root> --packet-content-hash <hex>`
- `xinao prospective write-owner-disposition --owner-state-root <owner> --pool-root <pool> --payload <disposition.json>` — exclusive CAS write under Owner-selected root; honest `owner_channel_authority=UNPROVEN_BY_LIBRARY`; never auto-continues
- `xinao prospective freeze-from-disposition --pool-root <pool> --owner-state-root <owner> --disposition <path> --portfolio-root <portfolio> --authority-root <auth>` — **only** production freeze: binds candidate pool + sealed Owner disposition + samples **host UTC at freeze** as authoritative freeze-action time (must be ≤ sealed packet/disposition deadline); no public `--owner-freeze-time` override
- `xinao research-episode emit-research-feedback-pack --portfolio-root <portfolio> [--period-index N] [--output <path>]` — post-settlement research material only
- `xinao prospective canary --contract <…> --expected-contract-sha256 <hex> --i-accept-network-canary` (opt-in live shape probe only; no campaign state)

Capture/reveal/disposition-write/feedback-emit are one-shot; freeze is an explicit Codex Owner
action via sealed disposition. Host freeze-action time is written onto FrozenEpisode/Ticket
(disposition seal time kept as `disposition_frozen_at` on the research binding). These do **not**
authenticate Codex (physical root isolation remains outside the library). Do **not** use shadow
`freeze` or `portfolio-freeze` as production freeze advertising; both fail closed.

These shadow verbs run an ephemeral leg-A container from the active researcher image by exact image ID
with read-only rootfs, dropped capabilities, no-new-privileges, and network none; only the episode
or portfolio state mount is writable. Host Skill passes consumer arguments honestly and does not
reinterpret account P&L as scientific grade. Do not substitute Temporal, a daemon, or ordinary
worker routes for Owner freeze. Shadow results stay candidate-only and never claim parent completion.
Portfolio continuity does not invent long-research availability.

`source_status=available` means only that the implementation exists. Treat the runtime as callable
only when `inspect` returns `RUNTIME_READY`; pointer presence, an old successful receipt, an image
tag, or source tests are not substitutes. A call with materials must freeze them before runtime
probing, mount only the run-local snapshot read-only, bind the effective provider prompt and result
to the bundle hashes, and still return candidate-only research. Never expose generic file tools
while the provider credential is mounted in the same container.

If a verified source update must replace a legacy installed bootstrap, run the source entry's
`scripts/xinao.py bootstrap-migrate` with no release, hash, path, or generation arguments. The same
journaled transaction must install the version-independent entry, switch the versioned pointer,
retain rollback, and canary through the newly installed entry. Then run the installed entry's
`inspect` in a fresh process. Do not copy the Skill before legacy capture or patch it after pointer
activation as a separate unjournaled step. This is a legacy-replacement command, not a fresh-install
fallback; if no installed root or pointer exists, require a separately implemented and verified
fresh-install capability instead of inventing one during the call.

Ordinary `activate` switches only the versioned current pointer; it deliberately does not rewrite the
installed Skill tree. After a later activate, fresh `inspect` must report
`installed_projection.status=DRIFTED` until you run the installed entry's
`scripts/xinao.py sync-projection` (no release/hash/path arguments). That journaled transaction
projects only `current.active`'s sealed skill-bundle onto the installed Skill root with D-disk
receipt, previous-installed snapshot, recovery cone, foreign-entry rejection, and atomic replace;
it never changes the current pointer. On success, `installed_projection.status=ALIGNED` and
`shadow.runtime_status` may become `AVAILABLE` only when image labels also pass. Treat projection
drift as fail-closed: do not treat researcher runtime as ready while the installed projection is
drifted.

Keep the bounded online research lifecycle separate from the durable background leg. When the
user asks to mature the ordinary research leg, finish one stable entry with one-command lifecycle
verbs for install, inspect, parallel isolated researcher calls, freeze, shadow settlement, replay,
and feedback before building durable orchestration. A container image may implement that leg's
execution boundary; it
does not authorize Temporal, a resident worker, a daemon, or another Owner. Never substitute
platform readiness for a real researcher result.

Before making a migration, proof, or preflight artifact a live admission condition, trace its bytes
to a real consumer in build, execution, recovery, settlement, or the returned evidence. If the
artifact is only read and discarded, keep it as optional audit evidence or retire the gate; do not
turn apparent rigor into an unbounded prerequisite. When a verified newer source capability is the
missing live link, invoke its declared transactional install verb; for legacy replacement, use the
source `bootstrap-migrate` entry above. Verify the resulting installed entry in a fresh process
instead of continuing broader infrastructure work around an uninstalled candidate.

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
Shadow account/freeze/settlement/replay and portfolio-* continuity verbs are available only as
verbs of `shadow-lifecycle-leg-a` through the installed Skill container path above, and only when
inspect proves live image capability. Account settlement never promotes scientific grade.
