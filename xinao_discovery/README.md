# Xinao Discovery

This directory is the reusable software/instrument surface for the Xinao
research system. The current science authority is:

- `C:\Users\xx363\Desktop\主线\01_主线入口\《新澳严格数学科学研究模式——独立融合稿》.txt`
- Non-authoritative selector:
  `D:\XINAO_RESEARCH_RUNTIME\state\mainline_science_current\active_parent.current.json`

The former mixed G0-G8 parent, its admission contract, G4/G5/G6 gates and
`mainline_domain_research_current` projection are preserved under
`LEGACY_PARENT_G0_G8`. They remain valid for historical replay, regression and
reusable statistical/software instruments, but they cannot admit or block a
current science episode. The current Temporal entry is
`XinaoScienceEpisodeWorkflowV1`; `XinaoResearchCampaignWorkflow` and the
Foundation continuous workflows are legacy replay types.

Software products, routes, models, versions, disks, and runtime defaults are not defined by this README; they bind only through the current tool-glue constitution and current machine evidence.

The original V1 implementation snapshot placed runtime state and evidence under
`D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery` and large data under
`E:\XINAO_RESEARCH_DATA\xinao_discovery`. Those paths are historical evidence,
not current storage authority. Current placement and runtime bindings come only
from the tool-glue constitution and verified machine facts. This repository
contains engineering code, schemas, migrations, tests, and versioned configuration.

Legacy G5 statistical-instrument code lives in
`xinao.capability.g5_statistical_validity`. It keeps
sequential alpha spending and online FDR as procedure-specific protocols, debits every
holdout outcome access, distinguishes public null smoke from a real full-pipeline null run,
and does not treat distinct runtime identities as proof of statistical independence.
`scripts/run_g5_statistical_validity_preflight.py` consumes a content-hashed G4 report plus
an optional candidate bundle and emits a deterministic `READY` or `HOLD` report. The code,
tests, public smoke, or a generated report do not establish a current science
episode or scientific conclusion.

The reusable/legacy G8 operational-assurance code lives in `xinao.assurance`. It consumes exactly six
hash-bound evidence dimensions: security-negative, reproducibility, capacity,
real recovery, supply chain, and independent audit. Missing, stale, tampered,
revoked, non-independent, or incomplete evidence produces a replayable `DENY`.
`scripts/run_g8_operational_assurance_preflight.py` materializes the report,
verification, and run manifest under a bounded runtime root. Even a valid G8
`READY` report does not grant live-shadow admission or parent-mainline completion.
`scripts/run_g8_reproducibility_dimension.py` builds only the reproducibility
dimension in two phases: `capture` checks lock/metadata agreement, replays a
frozen isolated environment, compares two fresh-process report materializations,
and binds subject files; `finalize` requires a separate review bound to that
exact capture before invoking the existing G8 consumer. Reproducibility alone
keeps the report at `DENY` with the other five dimensions unready.

Historical P0-P11 evidence projection:

The following bullets describe the original V1 vertical under source hash
`316b5b20dd29f5ebc454faa33eab3a4b92c0e7b5c9a4a68c3be2922ec730aae7`.
They do not prove current science admission or scientific conclusions. Explicit
legacy ResearchCampaign executions and formal-ledger registration attempts
still fail closed through the hash-bound `DomainResearchAdmissionReport`
verifier; pre-cutover Temporal histories retain their replay path. No old
G4/G5/G6 outcome is equivalent to `XINAO_SCIENCE_EPISODE_ALLOWED`.

- P0 capability/input admission, dedicated branch, locked dependency BOM, licenses, and SBOM.
- P1 canonical profile, 37-object registry, and 16-kind typed handoff contract.
- P2 separate domain-ledger and confirmation-vault migrations, roles, immutable gates,
  canonical-byte hash verification, finite aggregate query API, and live PostgreSQL probes.
- The first P3/P4 vertical slice registers the 913-draw dataset and 433-row baseline,
  compiles the special-number catalog, and replays an 89,474-row EventMatrix.
- P5 fixes the four time partitions, walk-forward/leakage/statistical court, deterministic
  NO_ACTION candidate, limited confirmation binding, and resumable Optuna RDB smoke.
- P6 compiles ACTION/NO_ACTION mechanically, freezes decisions before the target, and
  records outcomes, strict double-entry shadow journals, deterministic settlements,
  Monday-15:00 Asia/Shanghai business weeks, replayed projections, and append-only
  period adjustments. The live formal database is migrated but remains free of canary rows.
- P7 keeps versioned pipeline inputs in DVC with a D-drive cache and E-drive remote, tracks
  run evidence in MLflow, emits OpenLineage to Marquez with exact COMPLETED readback, and
  preserves 32-hex OpenTelemetry trace identity through a resumable outbox delivery.
- P8 runs the durable mainline and ResearchCampaign workflows on the existing Temporal,
  Docker `houtai-gongren`, and worker-internal LangGraph route. The same workflow/run
  survives a bounded worker restart, replays its history, deduplicates Signals, keeps Query
  read-only, validates Updates before acceptance, and audits STOP/CANCEL/TERMINATE.
- P9 adds a credential-scrubbed read-only workflow/evidence CLI and terminal projection.
  Its pinned Promptfoo suite admits the legal Grok 4.5 read-only control and rejects model
  impersonation, worker writes, missing sources, bypass flags, and blanket authorization.
- P10 enables native PostgreSQL WAL archiving, verified `pg_basebackup`, MinIO object
  versioning, and DVC remote inventory. An isolated new-directory PITR drill recovered the
  post-backup marker and identical formal-event hash in 25.109 seconds.
- P11 closes the first end-to-end evidence pack with positive, deterministic NO_ACTION,
  unauthorized-write, leakage, duplicate, conflict, worker-restart recovery, PITR,
  reverse-lookup, and content-addressed artifact checks. A real Grok 4.5 verifier reached it
  through Temporal and LangGraph and returned VERIFIED.

P12 remains sidelined and is not activated by this verified P0-P11 vertical.
