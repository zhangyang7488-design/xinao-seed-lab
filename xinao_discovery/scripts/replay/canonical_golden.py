"""Replay P1-XN-010 canonical vectors in process, fresh process, and databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VECTORS = PROJECT_ROOT / "tests" / "fixtures" / "canonical" / "golden_vectors.json"


def load_vectors(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "xinao.canonical_golden.v1":
        raise ValueError("unsupported golden vector schema")
    vectors = payload.get("vectors")
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("golden vector list is empty")
    return vectors


def compute_vectors(path: Path) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for vector in load_vectors(path):
        canonical = canonical_dumps(vector["normalized_json"])
        results.append(
            {
                "name": str(vector["name"]),
                "jcs_utf8": canonical.decode("utf-8"),
                "canonical_hex": canonical.hex(),
                "sha256_hex": hashlib.sha256(canonical).hexdigest(),
            }
        )
    return results


def verify_expected(path: Path, computed: list[dict[str, str]]) -> None:
    by_name = {str(vector["name"]): vector for vector in load_vectors(path)}
    for result in computed:
        expected = by_name[result["name"]]
        if result["jcs_utf8"] != expected["jcs_utf8"]:
            raise AssertionError(f"JCS bytes mismatch for {result['name']}")
        if result["sha256_hex"] != expected["sha256_hex"]:
            raise AssertionError(f"SHA-256 mismatch for {result['name']}")


def verify_fresh_process(path: Path, expected: list[dict[str, str]]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", "--vectors", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"fresh process failed with exit {completed.returncode}")
    observed = json.loads(completed.stdout)
    if observed != expected:
        raise AssertionError("fresh-process canonical result differs")
    return {"ok": True, "executable": sys.executable, "vector_count": len(observed)}


def verify_sqlite(expected: list[dict[str, str]], db_path: Path) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE IF EXISTS canonical_golden")
        connection.execute(
            "CREATE TABLE canonical_golden "
            "(name TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO canonical_golden(name, payload, digest) VALUES (?, ?, ?)",
            [
                (item["name"], bytes.fromhex(item["canonical_hex"]), item["sha256_hex"])
                for item in expected
            ],
        )
        rows = connection.execute(
            "SELECT name, hex(payload), digest FROM canonical_golden ORDER BY name"
        ).fetchall()
    observed = {
        name: {"canonical_hex": canonical_hex.lower(), "sha256_hex": digest}
        for name, canonical_hex, digest in rows
    }
    wanted = {
        item["name"]: {
            "canonical_hex": item["canonical_hex"],
            "sha256_hex": item["sha256_hex"],
        }
        for item in expected
    }
    if observed != wanted:
        raise AssertionError("SQLite BLOB readback differs from canonical bytes")
    return {"ok": True, "database": "sqlite", "path": str(db_path), "row_count": len(rows)}


def verify_postgres(expected: list[dict[str, str]], container: str) -> dict[str, Any]:
    statements = [
        "BEGIN;",
        "CREATE TEMP TABLE canonical_golden "
        "(name text PRIMARY KEY, payload bytea NOT NULL, digest text NOT NULL);",
    ]
    for item in expected:
        name = item["name"].replace("'", "''")
        statements.append(
            "INSERT INTO canonical_golden(name,payload,digest) VALUES "
            f"('{name}',decode('{item['canonical_hex']}','hex'),'{item['sha256_hex']}');"
        )
    statements.extend(
        [
            "SELECT name || '|' || encode(payload,'hex') || '|' || digest "
            "FROM canonical_golden ORDER BY name;",
            "ROLLBACK;",
        ]
    )
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "sh",
        "-c",
        'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At',
    ]
    completed = subprocess.run(
        command,
        input="\n".join(statements),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PostgreSQL readback failed with exit {completed.returncode}")
    observed: dict[str, dict[str, str]] = {}
    for line in completed.stdout.splitlines():
        if line.count("|") != 2:
            continue
        name, canonical_hex, digest = line.split("|", 2)
        observed[name] = {"canonical_hex": canonical_hex, "sha256_hex": digest}
    wanted = {
        item["name"]: {
            "canonical_hex": item["canonical_hex"],
            "sha256_hex": item["sha256_hex"],
        }
        for item in expected
    }
    if observed != wanted:
        raise AssertionError("PostgreSQL BYTEA readback differs from canonical bytes")
    return {
        "ok": True,
        "database": "postgresql-temp-table-rolled-back",
        "container": container,
        "row_count": len(observed),
    }


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--vectors", type=Path, default=DEFAULT_VECTORS)
    parser.add_argument("--sqlite-path", type=Path)
    parser.add_argument("--postgres-container")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    computed = compute_vectors(args.vectors)
    if args.worker:
        print(json.dumps(computed, ensure_ascii=False, sort_keys=True))
        return 0
    if not args.verify:
        raise SystemExit("--verify is required")
    verify_expected(args.vectors, computed)
    if args.sqlite_path is None:
        temporary = Path(tempfile.mkdtemp(prefix="xinao-canonical-"))
        sqlite_path = temporary / "canonical.sqlite3"
    else:
        sqlite_path = args.sqlite_path
    report: dict[str, Any] = {
        "schema_version": "xinao.canonical_replay_report.v1",
        "ok": True,
        "vectors": computed,
        "local_process": {"ok": True, "vector_count": len(computed)},
        "fresh_process": verify_fresh_process(args.vectors, computed),
        "sqlite_readback": verify_sqlite(computed, sqlite_path),
    }
    if args.postgres_container:
        report["postgres_readback"] = verify_postgres(computed, args.postgres_container)
    if args.report is not None:
        write_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
