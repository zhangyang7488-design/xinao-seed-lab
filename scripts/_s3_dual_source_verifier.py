"""S3 dual-source runtime verifier (read-only probe; writes evidence JSON only)."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _s3_ssot_read_adapter import (  # noqa: E402
    BUS_MESSAGES_DIR,
    BUS_ROOT,
    BUS_TASKS_DIR,
    BUS_THREADS_DIR,
    KERNEL_DB,
    get_thread_summary,
)

EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
STATUS_PATH = EVIDENCE_DIR / "S3_dual_source_status_latest.json"
OUT_PATH = EVIDENCE_DIR / "S3_dual_source_refresh_latest.json"
PROD_AMQ = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq")

HARD_BANS = {
    "delete_live_bus": True,
    "migrate_apply_production": True,
    "migrate_apply_canary": True,
    "migrate_apply_any": True,
    "prod_amq_init": True,
    "codex_lane_or_handoff": True,
}


def _ro_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _load_prior_status() -> dict | None:
    if not STATUS_PATH.is_file():
        return None
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def _kernel_counts() -> dict[str, object]:
    if not KERNEL_DB.is_file():
        return {"exists": False, "path": str(KERNEL_DB), "readable": False}
    with _ro_sqlite(KERNEL_DB) as conn:
        threads = int(conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
        tasks = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
        events = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        thread_states = {
            row[0]: row[1]
            for row in conn.execute("SELECT state, COUNT(*) FROM threads GROUP BY state ORDER BY state")
        }
        task_states = {
            row[0]: row[1]
            for row in conn.execute("SELECT state, COUNT(*) FROM tasks GROUP BY state ORDER BY state")
        }
        thread_ids = [row[0] for row in conn.execute("SELECT thread_id FROM threads ORDER BY thread_id")]
        task_ids = [row[0] for row in conn.execute("SELECT task_id FROM tasks ORDER BY task_id")]
    return {
        "exists": True,
        "path": str(KERNEL_DB),
        "readable": True,
        "threads": threads,
        "tasks": tasks,
        "events": events,
        "thread_by_state": thread_states,
        "task_by_state": task_states,
        "thread_ids": thread_ids,
        "task_ids": task_ids,
        "id_shape": "th_<32hex> / task_<32hex>",
    }


def _bus_counts() -> dict[str, object]:
    if not BUS_ROOT.is_dir():
        return {"exists": False, "path": str(BUS_ROOT), "readable": False}
    thread_files = list(BUS_THREADS_DIR.glob("*.json")) if BUS_THREADS_DIR.is_dir() else []
    task_files = list(BUS_TASKS_DIR.glob("*.json")) if BUS_TASKS_DIR.is_dir() else []
    message_files = list(BUS_MESSAGES_DIR.glob("*.jsonl")) if BUS_MESSAGES_DIR.is_dir() else []
    total_files = sum(1 for _ in BUS_ROOT.rglob("*") if _.is_file())
    total_bytes = sum(f.stat().st_size for f in BUS_ROOT.rglob("*") if f.is_file())
    thread_by_state: dict[str, int] = {}
    thread_ids: list[str] = []
    for path in thread_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = str(data.get("state", "UNKNOWN"))
        thread_by_state[state] = thread_by_state.get(state, 0) + 1
        thread_ids.append(str(data.get("thread_id", path.stem)))
    task_by_state: dict[str, int] = {}
    task_ids: list[str] = []
    for path in task_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = str(data.get("state", "UNKNOWN"))
        task_by_state[state] = task_by_state.get(state, 0) + 1
        task_ids.append(str(data.get("task_id", path.stem)))
    latest = BUS_ROOT / "latest.json"
    latest_meta: dict[str, object] = {}
    if latest.is_file():
        latest_data = json.loads(latest.read_text(encoding="utf-8"))
        latest_meta = {
            "path": str(latest),
            "updated_at": latest_data.get("updated_at"),
            "last_action": latest_data.get("last_action"),
        }
    return {
        "exists": True,
        "path": str(BUS_ROOT),
        "readable": True,
        "threads": len(thread_files),
        "tasks": len(task_files),
        "message_jsonl": len(message_files),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "thread_by_state": thread_by_state,
        "task_by_state": task_by_state,
        "thread_ids": sorted(thread_ids),
        "task_ids": sorted(task_ids),
        "id_shape": "th_<12hex> / task_<12hex>",
        "still_writable": True,
        "legacy_readonly_gate": False,
        "latest_json": latest_meta,
    }


def _overlap(kernel_ids: list[str], bus_ids: list[str]) -> dict[str, object]:
    k_set = set(kernel_ids)
    b_set = set(bus_ids)
    thread_overlap = sorted(k_set & b_set)
    return {
        "thread_ids_overlap_count": len(thread_overlap),
        "thread_overlap_ids": thread_overlap,
        "note_cn": "zero overlap = parallel dual universes (strategy B)",
    }


def _classify_risk(
    *,
    kernel: dict[str, object],
    bus: dict[str, object],
    overlap: dict[str, object],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    kernel_ok = bool(kernel.get("exists")) and bool(kernel.get("readable"))
    bus_ok = bool(bus.get("exists")) and bool(bus.get("readable"))

    if kernel_ok and not bus_ok:
        reasons.append("single source: kernel only (bus absent)")
        return "low", reasons
    if bus_ok and not kernel_ok:
        reasons.append("single source: bus only (kernel absent)")
        return "medium", reasons
    if not kernel_ok and not bus_ok:
        reasons.append("no readable dual-source paths")
        return "high", reasons

    thread_overlap = int(overlap.get("thread_ids_overlap_count", 0))
    kernel_threads = int(kernel.get("threads", 0))
    bus_threads = int(bus.get("threads", 0))

    if thread_overlap > 0:
        reasons.append(f"thread id overlap detected ({thread_overlap})")
        return "medium", reasons

    if kernel_threads > 0 and bus_threads > 0 and bus.get("still_writable"):
        reasons.append("parallel universes: both sources populated, zero id overlap, bus still writable")
        return "high", reasons

    if kernel_threads > 0 and bus_threads > 0:
        reasons.append("both sources populated without id overlap")
        return "medium", reasons

    reasons.append("residual dual-path layout with low live divergence")
    return "low", reasons


def _delta_vs_prior(
    prior: dict | None,
    kernel: dict[str, object],
    bus: dict[str, object],
) -> dict[str, object]:
    if prior is None:
        return {"prior_status_loaded": False}
    prior_dual = prior.get("dual_source", {})
    prior_sources = {s.get("id"): s for s in prior_dual.get("sources", []) if isinstance(s, dict)}
    pk = prior_sources.get("kernel_sqlite", {})
    pb = prior_sources.get("legacy_json_bus", {})
    return {
        "prior_status_loaded": True,
        "prior_status_path": str(STATUS_PATH),
        "prior_kernel_threads": pk.get("threads"),
        "prior_kernel_tasks": pk.get("tasks"),
        "prior_bus_threads": pb.get("threads"),
        "prior_bus_tasks": pb.get("tasks"),
        "current_kernel_threads": kernel.get("threads"),
        "current_kernel_tasks": kernel.get("tasks"),
        "current_bus_threads": bus.get("threads"),
        "current_bus_tasks": bus.get("tasks"),
        "counts_changed": (
            pk.get("threads") != kernel.get("threads")
            or pk.get("tasks") != kernel.get("tasks")
            or pb.get("threads") != bus.get("threads")
            or pb.get("tasks") != bus.get("tasks")
        ),
    }


def run_verifier() -> dict[str, object]:
    prior = _load_prior_status()
    kernel = _kernel_counts()
    bus = _bus_counts()
    overlap = _overlap(
        list(kernel.get("thread_ids", [])) if kernel.get("thread_ids") else [],
        list(bus.get("thread_ids", [])) if bus.get("thread_ids") else [],
    )
    task_overlap_ids = sorted(
        set(kernel.get("task_ids", [])) & set(bus.get("task_ids", []))
        if kernel.get("task_ids") and bus.get("task_ids")
        else []
    )
    overlap["task_ids_overlap_count"] = len(task_overlap_ids)
    overlap["task_overlap_ids"] = task_overlap_ids

    risk, risk_reasons = _classify_risk(kernel=kernel, bus=bus, overlap=overlap)
    adapter_auto = get_thread_summary(source="auto")

    payload: dict[str, object] = {
        "schema_version": "xinao.kaigong_wave.S3_dual_source_refresh.v1",
        "package": "S3_dual_source_refresh_latest",
        "title_cn": "S3 双源 runtime 只读验证刷新（Lane D scripts；策略 B 零迁移）",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "executor": "composer_lane_d_s3_dual_source_verifier",
        "phase": "S3",
        "mode": "read_only_runtime_probe",
        "engineering_only": True,
        "completion_claim_allowed": False,
        "hard_bans": HARD_BANS,
        "hard_bans_honored_this_turn": [
            "no bus delete",
            "no migrate apply",
            "no prod amq init",
            "evidence write only",
        ],
        "prior_status": {
            "loaded": prior is not None,
            "path": str(STATUS_PATH),
            "prior_risk": (prior or {}).get("dual_source", {}).get("risk"),
            "strategy_B_locked": (prior or {}).get("strategy_B", {}).get("status") == "locked",
        },
        "prod_amq_exists": PROD_AMQ.exists(),
        "dual_source_risk": risk,
        "dual_source_risk_reasons": risk_reasons,
        "preferred_ssot": "kernel_sqlite",
        "ssot_read_adapter_sample": {
            "auto_resolved_source": adapter_auto.get("resolved_source"),
            "auto_thread_count": adapter_auto.get("count"),
        },
        "sources": {
            "kernel_sqlite": kernel,
            "legacy_json_bus": bus,
        },
        "id_overlap": overlap,
        "delta_vs_prior_status": _delta_vs_prior(prior, kernel, bus),
        "verdict": {
            "ok": True,
            "risk": risk,
            "strategy_B_zero_migrate": True,
            "bus_deleted": not bus.get("exists"),
            "migrate_apply_executed": False,
            "honesty_cn": (
                f"本文件=runtime 只读探针刷新；≠双源收敛；≠单 SSOT 产品闭合；dual_source_risk={risk}"
            ),
        },
    }
    return payload


def main() -> int:
    payload = run_verifier()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(OUT_PATH),
                "dual_source_risk": payload["dual_source_risk"],
                "kernel_threads": payload["sources"]["kernel_sqlite"]["threads"],
                "bus_threads": payload["sources"]["legacy_json_bus"]["threads"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
