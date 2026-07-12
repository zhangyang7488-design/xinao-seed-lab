"""S3 thin SSOT read adapter: kernel sqlite preferred, legacy bus fallback (read-only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

KERNEL_DB = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3"
)
BUS_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_bus")
BUS_THREADS_DIR = BUS_ROOT / "discuss" / "threads"
BUS_MESSAGES_DIR = BUS_ROOT / "discuss" / "messages"
BUS_TASKS_DIR = BUS_ROOT / "tasks"
STOP_STATE = KERNEL_DB.parent / "stop" / "global.json"
READBACK_SOURCES = {
    "temporal": Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave"
        r"\C08_temporal_kernel_convergence_latest.json"
    ),
    "mlflow": Path(r"D:\XINAO_RESEARCH_RUNTIME\state\thin_glue_mlflow\latest.json"),
    "openlineage_marquez": Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\thin_glue_openlineage\latest.json"
    ),
    "xinao_market": Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\L0_one_command_rerun_latest.json"
    ),
}

SourceMode = Literal["kernel", "bus", "auto"]


def _ro_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _file_ref(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "size_bytes": None, "sha256": None}
    raw = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


def build_readback_snapshot() -> dict[str, Any]:
    """Build one fresh, reconstructable, strictly read-only source manifest."""
    with _ro_sqlite(KERNEL_DB) as conn:
        query_only = int(conn.execute("PRAGMA query_only").fetchone()[0]) == 1
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        tables = (
            "threads",
            "tasks",
            "messages",
            "events",
            "artifacts",
            "agent_operations",
            "notification_outbox",
        )
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
        thread_states = dict(
            conn.execute("SELECT state,COUNT(*) FROM threads GROUP BY state").fetchall()
        )
        task_states = dict(
            conn.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state").fetchall()
        )
        last_event = conn.execute(
            "SELECT seq,event_type,occurred_at_ms FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    stop_ref = _file_ref(STOP_STATE)
    stop_value: dict[str, Any] | None = None
    if stop_ref["exists"]:
        loaded = json.loads(STOP_STATE.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            stop_value = loaded
    source_refs = {name: _file_ref(path) for name, path in READBACK_SOURCES.items()}
    return {
        "schema_version": "xinao.s3.readback_snapshot.v1",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "strict_read_only",
        "kernel": {
            "database": _file_ref(KERNEL_DB),
            "sqlite_mode_ro": True,
            "query_only": query_only,
            "quick_check": quick_check,
            "counts": counts,
            "thread_states": thread_states,
            "task_states": task_states,
            "last_event": {
                "seq": int(last_event[0]),
                "event_type": str(last_event[1]),
                "occurred_at_ms": int(last_event[2]),
            }
            if last_event
            else None,
        },
        "stop": {"file": stop_ref, "value": stop_value},
        "sources": source_refs,
        "all_named_sources_visible": all(item["exists"] for item in source_refs.values()),
    }


def _kernel_available() -> bool:
    return KERNEL_DB.is_file()


def _bus_available() -> bool:
    return BUS_ROOT.is_dir()


def _read_kernel_thread(thread_id: str) -> dict[str, Any] | None:
    if not _kernel_available():
        return None
    with _ro_sqlite(KERNEL_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT thread_id, title, state, opened_by, rounds, updated_at_ms, close_reason "
            "FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "source": "kernel_sqlite",
        "thread_id": row["thread_id"],
        "title": row["title"],
        "state": row["state"],
        "opened_by": row["opened_by"],
        "rounds": row["rounds"],
        "updated_at_ms": row["updated_at_ms"],
        "close_reason": row["close_reason"],
    }


def _read_bus_thread(thread_id: str) -> dict[str, Any] | None:
    if not _bus_available():
        return None
    path = BUS_THREADS_DIR / f"{thread_id}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "source": "legacy_json_bus",
        "thread_id": data.get("thread_id", thread_id),
        "title": data.get("title"),
        "state": data.get("state"),
        "opened_by": data.get("opened_by"),
        "rounds": data.get("rounds"),
        "updated_at": data.get("updated_at"),
        "close_reason": data.get("close_reason"),
    }


def _kernel_thread_summary() -> dict[str, Any]:
    if not _kernel_available():
        return {"available": False, "path": str(KERNEL_DB), "threads": [], "count": 0}
    with _ro_sqlite(KERNEL_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT thread_id, title, state, opened_by, rounds, updated_at_ms "
            "FROM threads ORDER BY updated_at_ms DESC"
        ).fetchall()
        by_state: dict[str, int] = {}
        for r in rows:
            by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    threads = [
        {
            "thread_id": r["thread_id"],
            "title": r["title"],
            "state": r["state"],
            "opened_by": r["opened_by"],
            "rounds": r["rounds"],
            "updated_at_ms": r["updated_at_ms"],
        }
        for r in rows
    ]
    return {
        "available": True,
        "path": str(KERNEL_DB),
        "source": "kernel_sqlite",
        "count": len(threads),
        "by_state": by_state,
        "threads": threads,
    }


def _bus_thread_summary() -> dict[str, Any]:
    if not _bus_available() or not BUS_THREADS_DIR.is_dir():
        return {"available": False, "path": str(BUS_ROOT), "threads": [], "count": 0}
    threads: list[dict[str, Any]] = []
    by_state: dict[str, int] = {}
    for path in sorted(BUS_THREADS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        state = str(data.get("state", "UNKNOWN"))
        by_state[state] = by_state.get(state, 0) + 1
        threads.append(
            {
                "thread_id": data.get("thread_id", path.stem),
                "title": data.get("title"),
                "state": state,
                "opened_by": data.get("opened_by"),
                "rounds": data.get("rounds"),
                "updated_at": data.get("updated_at"),
            }
        )
    return {
        "available": True,
        "path": str(BUS_ROOT),
        "source": "legacy_json_bus",
        "count": len(threads),
        "by_state": by_state,
        "threads": threads,
    }


def get_thread_summary(
    *,
    source: SourceMode = "auto",
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Return thread summary or single-thread record from kernel, bus, or auto (kernel first).

    Read-only. No writes. ``auto`` prefers kernel; falls back to bus JSON when kernel
    is unavailable or the requested thread_id is absent from kernel.
    """
    if thread_id:
        if source == "kernel":
            row = _read_kernel_thread(thread_id)
            return {"ok": row is not None, "thread": row, "resolved_source": "kernel_sqlite"}
        if source == "bus":
            row = _read_bus_thread(thread_id)
            return {"ok": row is not None, "thread": row, "resolved_source": "legacy_json_bus"}
        # auto
        row = _read_kernel_thread(thread_id)
        resolved = "kernel_sqlite"
        if row is None:
            row = _read_bus_thread(thread_id)
            resolved = "legacy_json_bus"
        return {"ok": row is not None, "thread": row, "resolved_source": resolved}

    if source == "kernel":
        summary = _kernel_thread_summary()
        return {"ok": summary.get("available", False), "mode": "aggregate", **summary}
    if source == "bus":
        summary = _bus_thread_summary()
        return {"ok": summary.get("available", False), "mode": "aggregate", **summary}

    # auto aggregate: prefer kernel when readable
    kernel = _kernel_thread_summary()
    if kernel.get("available") and kernel.get("count", 0) > 0:
        return {"ok": True, "mode": "aggregate", "resolved_source": "kernel_sqlite", **kernel}
    bus = _bus_thread_summary()
    if bus.get("available") and bus.get("count", 0) > 0:
        return {"ok": True, "mode": "aggregate", "resolved_source": "legacy_json_bus", **bus}
    if kernel.get("available"):
        return {"ok": True, "mode": "aggregate", "resolved_source": "kernel_sqlite", **kernel}
    if bus.get("available"):
        return {"ok": True, "mode": "aggregate", "resolved_source": "legacy_json_bus", **bus}
    return {
        "ok": False,
        "mode": "aggregate",
        "resolved_source": None,
        "count": 0,
        "threads": [],
        "note": "neither kernel nor bus readable",
    }


def _self_test() -> int:
    failures: list[str] = []

    agg_auto = get_thread_summary(source="auto")
    if not agg_auto.get("ok"):
        failures.append("auto aggregate should resolve a source")
    if agg_auto.get("resolved_source") != "kernel_sqlite":
        failures.append(f"expected kernel_sqlite default, got {agg_auto.get('resolved_source')}")

    agg_kernel = get_thread_summary(source="kernel")
    if not agg_kernel.get("available"):
        failures.append("kernel should be available on prod path")
    if agg_kernel.get("count", 0) < 1:
        failures.append("kernel thread count should be >= 1")

    agg_bus = get_thread_summary(source="bus")
    if not agg_bus.get("available"):
        failures.append("bus should be available")
    if agg_bus.get("count", 0) != 8:
        failures.append(f"expected 8 bus threads, got {agg_bus.get('count')}")

    # kernel-only id (32 hex)
    kernel_id = agg_kernel["threads"][0]["thread_id"]
    one_kernel = get_thread_summary(source="auto", thread_id=kernel_id)
    if not one_kernel.get("ok") or one_kernel.get("resolved_source") != "kernel_sqlite":
        failures.append("kernel thread lookup via auto failed")

    # bus-only id (12 hex) — absent from kernel, should fall back
    bus_id = agg_bus["threads"][0]["thread_id"]
    one_bus = get_thread_summary(source="auto", thread_id=bus_id)
    if not one_bus.get("ok"):
        failures.append("bus thread lookup via auto failed")
    if one_bus.get("resolved_source") != "legacy_json_bus":
        failures.append("bus-only id should resolve via legacy_json_bus fallback")

    missing = get_thread_summary(source="auto", thread_id="th_nonexistent_00000000")
    if missing.get("ok"):
        failures.append("nonexistent thread should return ok=False")

    print(
        json.dumps(
            {"self_test": "pass" if not failures else "fail", "failures": failures},
            ensure_ascii=False,
        )
    )
    print(
        json.dumps(
            {
                "sample_auto_aggregate": {
                    "count": agg_auto.get("count"),
                    "resolved_source": agg_auto.get("resolved_source"),
                }
            },
            ensure_ascii=False,
        )
    )
    print(json.dumps({"sample_bus_fallback": one_bus}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    if args.snapshot:
        print(json.dumps(build_readback_snapshot(), ensure_ascii=False))
        raise SystemExit(0)
    raise SystemExit(_self_test())
