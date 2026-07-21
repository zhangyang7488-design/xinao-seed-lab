# Single-host capacity maintenance

This package bounds the verified continuously growing PostgreSQL producer and
prepares native bounds for Docker logs/cache and WSL dumps from the July 2026
C:/D:/E: incident. It also records, but does not mislabel as enforced, the
remaining host-metric and Rust build-cache gaps. It creates no second scheduler
or generic cleanup daemon.
`maintenance-policy.v1.json` is a typed admission policy, not authorization for
arbitrary deletion.

## Enforced now

- The existing Temporal Schedule `xinao-platform-capacity-daily-v1` starts one
  fixed daily pgBackRest full-backup Workflow at 03:30 Asia/Shanghai.
- Overlap is `SKIP`, catch-up is 30 minutes, and a Workflow failure pauses the
  Schedule.
- The existing `mowei-zhixing` remains the sole Docker-socket owner. Its
  original OpenHands queue and the maintenance queue share one process.
- Worker, maintenance module, policy, pgBackRest config, broker image,
  PostgreSQL image/Compose identity, fixed argv and `postgres` OS user are
  hash- or identity-pinned.
- Capacity input drift disables only the maintenance poller. The original
  OpenHands poller remains available; it is not sacrificed to a backup-policy
  mismatch.
- pgBackRest catalog retention replaces the former unbounded raw-WAL copy.
  No generic prune, arbitrary shell/path input or explicit delete command is
  exposed to the Workflow.

Schedule activation must be proven from the live Schedule description, latest
Schedule action, completed Workflow result, receipt, repository, WAL archiver
and both task-queue pollers. Repository expiry may legitimately remove catalog
entries after a successful backup; `explicit_delete_command_count=0` means the
Activity did not issue a separate delete command.

## Native bounds prepared for restart

- Docker BuildKit keeps 20 GB of reusable build cache.
- New containers default to Docker's rotated `local` logs: three 10 MiB files.
- WSL `maxCrashDumpCount=1` limits future WSL crash-dump accumulation.
- Windows Storage Sense is configured but its manual run returned
  `0x80040154` before the pending Windows restart; it must be re-tested after
  reboot.

## Not yet an enforced claim

The policy's `desired_state_unenforced` list is deliberate. There is no active
three-volume growth forecaster, repository soft-limit alert, automatic Docker
VHDX compactor or Windows Storage Sense collector in this bounded change. They
would require host metrics and/or a new persistent Windows service boundary.
There is also no active Cargo target collector, global `CARGO_TARGET_DIR`,
`RUSTC_WRAPPER` or sccache quota. The two classified target trees that consumed
about 95 GiB were deleted, but the 10 GiB warning threshold is currently an
unenforced design threshold. A future Rust build-wrapper integration must be
validated against F4 and input-bridge upgrade scripts before changing the
machine-wide toolchain. Do not describe this package as complete predictive AI
operations for all three partitions; these candidate capabilities remain
explicit for a separately authorized phase.

## Rejected routes

- No `docker system prune -a --volumes`, age-based WAL deletion, unclassified
  path cleanup, cron, Windows Scheduled Task, watchdog or second scheduler.
- No automatic VHDX compaction while Docker/WSL is attached.
- No capacity-policy drift that takes down the original OpenHands lane.
- No `PASS` text, config presence or poller alone may stand in for a real
  backup, restore and isolated-execution canary.
