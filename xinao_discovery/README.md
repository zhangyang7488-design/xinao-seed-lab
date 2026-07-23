# Xinao Discovery

This directory is an implementation surface for the Xinao research system. Current domain authority is:

- `C:\Users\xx363\Desktop\主线\01_主线入口\新澳完整研究施工与旁路双环进化_当前有效.txt`
- `C:\Users\xx363\Desktop\主线\02正式合同\新澳整体基础执行与自主研究准入合同_当前有效.txt`
- Machine projection only: `D:\XINAO_RESEARCH_RUNTIME\state\mainline_domain_research_current\blueprint.current_domain_research.json`

Software products, routes, models, versions, disks, and runtime defaults are not defined by this README; they bind only through the current tool-glue constitution and current machine evidence.

The original V1 implementation snapshot placed runtime state and evidence under
`D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery` and large data under
`E:\XINAO_RESEARCH_DATA\xinao_discovery`. Those paths are historical evidence,
not current storage authority. Current placement and runtime bindings come only
from the tool-glue constitution and verified machine facts. This repository
contains engineering code, schemas, migrations, tests, and versioned configuration.

Current G5 preflight code lives in `xinao.capability.g5_statistical_validity`. It keeps
sequential alpha spending and online FDR as procedure-specific protocols, debits every
holdout outcome access, distinguishes public null smoke from a real full-pipeline null run,
and does not treat distinct runtime identities as proof of statistical independence.
`scripts/run_g5_statistical_validity_preflight.py` consumes a content-hashed G4 report plus
an optional candidate bundle and emits a deterministic `READY` or `HOLD` report. The code,
tests, public smoke, or a generated report do not themselves establish current G5 or G6.

Current G8 preflight code lives in `xinao.assurance`. It consumes exactly six
hash-bound evidence dimensions: security-negative, reproducibility, capacity,
real recovery, supply chain, and independent audit. Missing, stale, tampered,
revoked, non-independent, or incomplete evidence produces a replayable `DENY`.
`scripts/run_g8_operational_assurance_preflight.py` materializes the report,
verification, and run manifest under a bounded runtime root. Even a valid G8
`READY` report does not grant live-shadow admission or parent-mainline completion.

Historical P0-P11 evidence projection:

The following bullets describe the original V1 vertical under source hash
`316b5b20dd29f5ebc454faa33eab3a4b92c0e7b5c9a4a68c3be2922ec730aae7`.
They do not prove current G0-G8 admission or autonomous-discovery capability. New canonical
ResearchCampaign executions and formal-ledger registration attempts now fail closed through one
hash-bound `DomainResearchAdmissionReport` verifier; pre-cutover Temporal histories retain their
replay path. Current G4/G5 HOLD evidence cannot produce ALLOW, so G6 and formal domain research
remain closed until matching final reports are independently admitted.

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
