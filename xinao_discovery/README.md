# Xinao Discovery

This directory is the engineering root for the new Xinao research system defined by:

- `C:\Users\xx363\Desktop\主线\01_主线入口\新澳完整研究施工与旁路双环进化_施工级终稿_v1.0_2026-07-13.txt`
- `C:\Users\xx363\Desktop\主线\01_主线入口\blueprint.v1_已合并工具与执行纪律.json`

Runtime state, evidence, caches, backups, and isolated probes belong under
`D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery`. Large data and the DVC
remote belong under `E:\XINAO_RESEARCH_DATA\xinao_discovery`. This repository
contains only engineering code, schemas, migrations, tests, and versioned
configuration.

Current verified WBS state:

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
