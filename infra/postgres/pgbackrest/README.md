# PostgreSQL PITR and WAL retention

`shiwu-ku` uses PostgreSQL 16.14 with pgBackRest 2.58.0. The active repository
is the Windows NTFS host bind
`D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\backups\postgres\pgbackrest-repo1`.
It was admitted only after uid/gid 70 could create, fsync, read and remove a
probe through the container mount. This is a host-bound local recovery path,
not a claim that the Windows repository is a native POSIX filesystem.

The repository owns base backups, WAL, restore metadata and catalog-aware
retention. Seven daily full backups are retained; archive retention follows the
same seven-full recovery boundary. `archive_timeout=60s`, zstd compression,
bundling and `expire-auto=y` preserve the one-minute archive RPO while bounding
growth. The local repository is fast PITR only: C:, D: and E: are partitions of
one NVMe device, so hardware-disaster protection requires a future repository
on another disk, NAS or object store.

## Pinned identity

- Base image: `postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`
- pgBackRest source: release 2.58.0 tarball SHA-256
  `2517ec0a7f66be0f1bc77795c3a19cd41c4b106699321d3ac511bc539dd2bfca`
- Built image ID: `sha256:8e7c7e041a94684f9b3abf23a712a60afa10c8e32c1c19c6450b93f6e76a90ca`
- Image version label: `postgres-16.14_pgbackrest-2.58.0`
- `pgbackrest.conf` SHA-256:
  `076d8d88f3a91a645445ff55d8d806c3286d5f8912a38d4d9d1d56358faa77bb`

The capacity policy also pins the image, Compose identity, config bytes, fixed
argv and OS user. Runtime activation is never inferred from this document:
inspect the live container, Temporal Schedule, latest closed Workflow result
and repository before declaring it active.

## Critical execution rule

Every pgBackRest command in the database container must run as `postgres`
(uid 70). Running `docker exec` as root can rewrite `archive.info` and
`backup.info` as `root:root 0640`; PostgreSQL's archiver then loses access and
WAL accumulates. The automated Activity and its activation receipt therefore
require `exec_os_user=postgres` for exactly:

1. `check`
2. `info --output=json`
3. `backup --type=full`
4. `verify`
5. `info --output=json`

The mounted config hash is checked before those commands. A root-owned
repository entry, config drift, image/Compose drift, a missing/extra/reordered
step, nonzero exit or skipped backup blocks Schedule activation.

## Migration performed on 2026-07-17

The pinned image was built without importing Alpine's PostgreSQL 18 stack. The
existing data volume was kept, the stanza was created, a temporary dual-archive
cutover proved both paths, and then Compose was changed to pgBackRest-only.
Multiple full backups, `check`, `verify`, forced WAL switches and isolated
restore drills passed. The final drill restored backup `20260716-190000F` into
a new named volume with no network or published port, promoted PostgreSQL,
verified an exact marker plus the `temporal` and `temporal_visibility`
databases, and removed the temporary container and volume. RTO was 19.212 s.

The old raw-WAL directory is no longer a live rollback path. Its migration-time
snapshot is the byte-tested cold package under
`E:\XINAO_EXTERNAL_SOURCES\archives\postgres-legacy-pitr\20260717-pre-pgbackrest`.
That package itself has not been restore-drilled.

## Rebuild or upgrade runbook

1. Update only the pinned base digest, pgBackRest version and source checksum;
   build a new image and record its full image ID and version output.
2. Recompute the config and capacity-policy hashes. Keep the config mounted
   read-only into both `shiwu-ku` and the existing combined control worker.
3. Probe the repository bind as uid 70 with create/fsync/read/remove and verify
   every existing repository entry is owned by postgres.
4. Leave the Temporal Schedule paused. Recreate only the affected container,
   then verify image, Compose labels/config hash, mount source/target/read-only
   mode and fresh worker hashes.
5. Use a temporary dual-archive cutover when changing archive implementation;
   force a WAL switch and prove both the old and new path before retiring one.
6. Run `check`, full backup, `verify`, and `info`; force another WAL switch and
   require `archived_count` to rise without increasing `failed_count`.
7. Trigger two sequential Schedule-owned canaries. Bind the activation receipt
   to the latest completed Temporal Workflow and reject any skipped backup.
8. Restore a new marker-bearing full into an isolated volume/container, start
   PostgreSQL with archiving disabled, verify marker and databases, then remove
   only those named temporary objects.
9. Re-run the original OpenHands execution canary because the capacity worker
   shares its process but not its admission fate. Unpause only after both lanes
   and the unique Docker-socket owner are verified.

## Rollback and rejected shortcuts

For current-code rollback, pause the Schedule, restore the previous pinned
image/config/policy hashes, recreate only the named service, and re-run archive
plus restore canaries. For legacy investigation, first recompute the cold 7z
SHA-256 and run `7z t`, then extract into an isolated path. Never overwrite the
active data volume or pgBackRest repository in place.

Do not use `archive_cleanup_command` or age-based file deletion as the primary
retention policy, do not run pgBackRest as root, do not raise
`archive_timeout` merely to hide space growth, and do not treat a green backup
command as recovery proof. Daily execution belongs to the existing Temporal
Schedule and unique Docker control owner; no cron, Windows Scheduled Task,
watchdog or second scheduler is part of this design.
