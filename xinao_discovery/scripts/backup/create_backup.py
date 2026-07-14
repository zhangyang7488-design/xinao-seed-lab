"""Create and verify the native P10 PostgreSQL, MinIO, and DVC backup set."""

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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 600,
) -> bytes:
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_bytes,
        check=True,
        capture_output=True,
        timeout=timeout,
    )
    return completed.stdout


def _text(command: list[str], *, cwd: Path | None = None, timeout: int = 600) -> str:
    return _run(command, cwd=cwd, timeout=timeout).decode("utf-8", errors="strict").strip()


def _docker_text(container: str, *command: str, timeout: int = 600) -> str:
    return _text(["docker", "exec", container, *command], timeout=timeout)


def _psql(container: str, database: str, sql: str) -> str:
    return _docker_text(
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
    )


def _json_lines(value: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line in value.splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                output.append(item)
    return output


def _version_id(value: dict[str, Any]) -> str:
    for key in ("versionID", "versionId", "version_id"):
        if value.get(key):
            return str(value[key])
    for nested in value.values():
        if isinstance(nested, dict):
            found = _version_id(nested)
            if found:
                return found
    return ""


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _wait_for_wal(path: Path, *, timeout_seconds: int = 120) -> float:
    started = time.monotonic()
    while time.monotonic() - started <= timeout_seconds:
        if path.is_file() and path.stat().st_size > 0:
            return time.monotonic() - started
        time.sleep(0.5)
    raise TimeoutError(f"WAL segment was not archived inside {timeout_seconds}s: {path.name}")


def create_backup(args: argparse.Namespace) -> dict[str, Any]:
    if not _SAFE_ID.fullmatch(args.backup_id):
        raise ValueError("backup-id must be a safe lowercase identifier")
    started_at = datetime.now(UTC)
    backup_root = args.backup_root.resolve()
    host_base = backup_root / "postgres" / "base" / args.backup_id
    host_wal = backup_root / "postgres" / "wal"
    if host_base.exists():
        raise FileExistsError(f"backup target already exists: {host_base}")
    host_wal.mkdir(parents=True, exist_ok=True)

    settings = _psql(
        args.postgres_container,
        "postgres",
        "select current_setting('wal_level'), current_setting('archive_mode'), "
        "extract(epoch from current_setting('archive_timeout')::interval)::integer, "
        "current_setting('archive_command');",
    ).split("|")
    if settings[:3] != ["replica", "on", "60"] or "/wal-archive" not in settings[3]:
        raise RuntimeError(f"PostgreSQL archive settings are not admitted: {settings[:3]}")

    container_base = f"/backup/postgres/base/{args.backup_id}"
    _docker_text(
        args.postgres_container,
        "pg_basebackup",
        "-U",
        "temporal",
        "-D",
        container_base,
        "-Fp",
        "-X",
        "stream",
        "--checkpoint=fast",
        f"--label=xinao-p10-{args.backup_id}",
        "--manifest-checksums=SHA256",
        timeout=1200,
    )
    verify_output = _docker_text(
        args.postgres_container,
        "pg_verifybackup",
        container_base,
        timeout=1200,
    )
    backup_manifest_path = host_base / "backup_manifest"
    if not backup_manifest_path.is_file():
        raise FileNotFoundError("pg_basebackup did not emit backup_manifest")

    marker_db = "xinao_p10_pitr_" + re.sub(r"[^a-z0-9]+", "_", args.backup_id)
    existing = _psql(
        args.postgres_container,
        "postgres",
        f"select count(*) from pg_database where datname = '{marker_db}';",
    )
    if existing != "0":
        raise RuntimeError(f"PITR marker database already exists: {marker_db}")
    _psql(args.postgres_container, "postgres", f"create database {marker_db};")
    marker_id = f"marker-{args.backup_id}"
    _psql(
        args.postgres_container,
        marker_db,
        "create table pitr_marker(marker_id text primary key, created_at timestamptz not null);"
        f" insert into pitr_marker values ('{marker_id}', clock_timestamp());",
    )
    target = _psql(
        args.postgres_container,
        "postgres",
        "select pg_current_wal_lsn(), clock_timestamp(), pg_walfile_name(pg_current_wal_lsn());",
    ).split("|")
    _psql(args.postgres_container, "postgres", "select pg_switch_wal();")
    archive_latency = _wait_for_wal(host_wal / target[2])
    archiver = _psql(
        args.postgres_container,
        "postgres",
        "select archived_count, failed_count, coalesce(last_archived_wal, '') "
        "from pg_stat_archiver;",
    ).split("|")

    minio_shell = (
        "mc alias set xinao http://127.0.0.1:9000 "
        '"$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && '
        "mc mb --ignore-existing xinao/xinao-discovery >/dev/null && "
        "mc version enable xinao/xinao-discovery --json"
    )
    versioning = _json_lines(_docker_text(args.minio_container, "sh", "-lc", minio_shell))[-1]
    object_key = f"p10/{args.backup_id}/version-canary.json"
    payloads = [
        json.dumps({"backup_id": args.backup_id, "revision": revision}, sort_keys=True).encode()
        for revision in (1, 2)
    ]
    object_versions: list[dict[str, str]] = []
    for payload in payloads:
        _run(
            [
                "docker",
                "exec",
                "-i",
                args.minio_container,
                "sh",
                "-lc",
                f"mc pipe xinao/xinao-discovery/{object_key} >/dev/null",
            ],
            input_bytes=payload,
        )
        stat = _json_lines(
            _docker_text(
                args.minio_container,
                "sh",
                "-lc",
                f"mc stat --json xinao/xinao-discovery/{object_key}",
            )
        )[-1]
        version_id = _version_id(stat)
        if not version_id:
            raise RuntimeError(f"MinIO stat did not expose a version ID: {stat}")
        readback = _run(
            [
                "docker",
                "exec",
                args.minio_container,
                "sh",
                "-lc",
                f"mc cat --version-id '{version_id}' xinao/xinao-discovery/{object_key}",
            ]
        )
        object_versions.append(
            {
                "version_id": version_id,
                "sha256": _sha256_bytes(payload),
                "readback_sha256": _sha256_bytes(readback),
            }
        )
    if len({item["version_id"] for item in object_versions}) != 2:
        raise AssertionError("MinIO did not retain two distinct object versions")
    if any(item["sha256"] != item["readback_sha256"] for item in object_versions):
        raise AssertionError("MinIO version readback hash mismatch")

    dvc = shutil.which("dvc")
    if not dvc:
        raise RuntimeError("DVC is required for the backup manifest")
    dvc_status = _text([dvc, "status", "-c"], cwd=args.project_root)
    dvc_lock = args.project_root / "dvc.lock"
    remote_root = Path(r"E:\XINAO_RESEARCH_DATA\xinao_discovery\dvc-remote")
    remote_files = [path for path in remote_root.rglob("*") if path.is_file()]
    if not remote_files:
        raise RuntimeError("DVC remote has no versioned objects")

    backup_files = [path for path in host_base.rglob("*") if path.is_file()]
    checks = {
        "archive_mode_enabled": settings[1] == "on",
        "pg_verifybackup_passed": "successfully verified" in verify_output.lower(),
        "forced_wal_archived": (host_wal / target[2]).is_file(),
        "wal_archive_failed_count_zero": int(archiver[1]) == 0,
        "minio_versioning_enabled": "enable" in json.dumps(versioning).lower(),
        "minio_two_versions_read_back": len(object_versions) == 2
        and all(item["sha256"] == item["readback_sha256"] for item in object_versions),
        "dvc_remote_populated": bool(remote_files),
        "dvc_pipeline_clean": any(
            marker in dvc_status.lower() for marker in ("up to date", "in sync")
        ),
    }
    result = {
        "schema_version": "xinao.p10_backup_manifest.v1",
        "status": "verified" if all(checks.values()) else "partial",
        "backup_id": args.backup_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "postgres": {
            "container": args.postgres_container,
            "server_version": _psql(args.postgres_container, "postgres", "show server_version;"),
            "base_backup_path": str(host_base),
            "backup_manifest_sha256": _sha256_file(backup_manifest_path),
            "backup_file_count": len(backup_files),
            "backup_bytes": sum(path.stat().st_size for path in backup_files),
            "pg_verifybackup": verify_output,
            "wal_archive_path": str(host_wal),
            "archived_count": int(archiver[0]),
            "archive_failed_count": int(archiver[1]),
            "last_archived_wal": archiver[2],
            "forced_wal": target[2],
            "forced_archive_latency_seconds": round(archive_latency, 3),
            "pitr_marker": {
                "database": marker_db,
                "marker_id": marker_id,
                "target_lsn": target[0],
                "target_time": target[1],
            },
        },
        "objects": {
            "container": args.minio_container,
            "bucket": "xinao-discovery",
            "object_key": object_key,
            "versions": object_versions,
        },
        "dvc": {
            "lock_path": str(dvc_lock),
            "lock_sha256": _sha256_file(dvc_lock),
            "remote_root": str(remote_root),
            "remote_file_count": len(remote_files),
            "remote_bytes": sum(path.stat().st_size for path in remote_files),
            "status": dvc_status,
        },
        "objectives": {
            "rpo_seconds": 60,
            "observed_forced_wal_archive_seconds": round(archive_latency, 3),
            "rto_seconds": None,
            "rto_pending_isolated_restore": True,
        },
    }
    _write_json_atomic(args.output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--postgres-container", default="shiwu-ku")
    parser.add_argument("--minio-container", default="keguan-cunchu")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = create_backup(args)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
