"""Restore the P10 base backup into an isolated PostgreSQL container and verify PITR."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,80}$")


def _run(command: list[str], *, timeout: int = 600, check: bool = True) -> str:
    completed = subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    return completed.stdout.strip()


def _psql(container: str, database: str, sql: str) -> str:
    return _run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "temporal",
            "-d",
            database,
            "-Atc",
            sql,
        ]
    )


def _hash_rows(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _wait_ready(container: str, *, timeout_seconds: int = 180) -> float:
    started = time.monotonic()
    while time.monotonic() - started <= timeout_seconds:
        completed = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", "temporal"],
            capture_output=True,
            timeout=10,
        )
        if completed.returncode == 0:
            promoted = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "psql",
                    "-U",
                    "temporal",
                    "-d",
                    "postgres",
                    "-Atc",
                    "select not pg_is_in_recovery();",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            if promoted.returncode == 0 and promoted.stdout.strip() == "t":
                return time.monotonic() - started
        time.sleep(1)
    logs = _run(["docker", "logs", "--tail", "80", container], check=False)
    raise TimeoutError(f"isolated restore was not ready: {logs}")


def restore(args: argparse.Namespace) -> dict[str, Any]:
    if not _SAFE_ID.fullmatch(args.restore_id):
        raise ValueError("restore-id must be a safe lowercase identifier")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    postgres = dict(manifest["postgres"])
    marker = dict(postgres["pitr_marker"])
    source = Path(postgres["base_backup_path"]).resolve()
    wal = Path(postgres["wal_archive_path"]).resolve()
    restore_root = args.restore_root.resolve()
    target = (restore_root / args.restore_id).resolve()
    if restore_root != target and restore_root not in target.parents:
        raise ValueError("restore target escaped restore-root")
    if target.exists():
        raise FileExistsError(f"restore target already exists: {target}")
    if not source.is_dir() or not wal.is_dir():
        raise FileNotFoundError("base backup or WAL archive is missing")
    if _run(["docker", "ps", "-a", "--filter", f"name=^{args.container}$", "--format", "{{.ID}}"]):
        raise RuntimeError(f"restore container already exists: {args.container}")

    started_at = datetime.now(UTC)
    started = time.monotonic()
    shutil.copytree(source, target, copy_function=shutil.copy2)
    (target / "recovery.signal").touch()
    copy_seconds = time.monotonic() - started

    source_rows = _psql(
        args.source_container,
        "xinao_discovery_domain_canary_20260714",
        "select event_id::text || '|' || event_hash from domain_event order by aggregate_type, "
        "aggregate_id, aggregate_version;",
    )
    mount_data = f"type=bind,source={target},target=/var/lib/postgresql/data"
    mount_wal = f"type=bind,source={wal},target=/wal-archive,readonly"
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            args.container,
            "--network",
            args.network,
            "--mount",
            mount_data,
            "--mount",
            mount_wal,
            "postgres:16-alpine",
            "-c",
            "restore_command=cp /wal-archive/%f %p",
            "-c",
            f"recovery_target_lsn={marker['target_lsn']}",
            "-c",
            "recovery_target_inclusive=on",
            "-c",
            "recovery_target_action=promote",
            "-c",
            "listen_addresses=",
        ],
        timeout=120,
    )
    ready_seconds = _wait_ready(args.container)
    marker_readback = _psql(
        args.container,
        marker["database"],
        "select marker_id from pitr_marker;",
    )
    restored_rows = _psql(
        args.container,
        "xinao_discovery_domain_canary_20260714",
        "select event_id::text || '|' || event_hash from domain_event order by aggregate_type, "
        "aggregate_id, aggregate_version;",
    )
    recovery_state = _psql(
        args.container,
        "postgres",
        "select pg_is_in_recovery(), pg_current_wal_lsn();",
    ).split("|")
    rto_seconds = time.monotonic() - started
    source_hash = _hash_rows(source_rows)
    restored_hash = _hash_rows(restored_rows)
    checks = {
        "new_restore_directory": target != source and target.is_dir(),
        "isolated_container_not_network_exposed": not _run(
            ["docker", "port", args.container], check=False
        ),
        "pitr_marker_recovered": marker_readback == marker["marker_id"],
        "recovery_promoted": recovery_state[0] == "f",
        "formal_event_hash_matches": restored_hash == source_hash,
        "rto_within_15_minutes": rto_seconds <= 900,
    }
    result: dict[str, Any] = {
        "schema_version": "xinao.p10_isolated_restore.v1",
        "status": "verified" if all(checks.values()) else "partial",
        "restore_id": args.restore_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "source": {
            "backup_manifest": str(args.manifest.resolve()),
            "base_backup_path": str(source),
            "wal_archive_path": str(wal),
            "formal_event_hash": source_hash,
        },
        "restore": {
            "directory": str(target),
            "container": args.container,
            "copy_seconds": round(copy_seconds, 3),
            "ready_seconds": round(ready_seconds, 3),
            "rto_seconds": round(rto_seconds, 3),
            "marker_database": marker["database"],
            "marker_id": marker_readback,
            "replayed_lsn": recovery_state[1],
            "formal_event_hash": restored_hash,
        },
        "cleanup": {"container_removed": False, "source_marker_database_dropped": False},
    }
    if result["status"] == "verified":
        _run(["docker", "rm", "-f", args.container], timeout=120)
        result["cleanup"]["container_removed"] = True
        _psql(
            args.source_container,
            "postgres",
            f"drop database {marker['database']} with (force);",
        )
        result["cleanup"]["source_marker_database_dropped"] = True
    _write_json_atomic(args.output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--restore-id", required=True)
    parser.add_argument("--restore-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", default="xinao-p10-restore-postgres")
    parser.add_argument("--source-container", default="shiwu-ku")
    parser.add_argument("--network", default="xinao_internal")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = restore(args)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
