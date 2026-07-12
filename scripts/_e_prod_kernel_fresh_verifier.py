"""Lane E: non-destructive fresh verification of production coordination kernel (read-only)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
EVIDENCE_OUT = EVIDENCE_DIR / "E_prod_kernel_fresh_verifier_latest.json"

PROD_DB = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3")
CANARY_DB = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\coordination.sqlite3"
)
PROD_AMQ = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq")
CANARY_AMQ = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\amq")
S1_W2_GATE = EVIDENCE_DIR / "S1_W2_gate_latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cli(db: Path, args: list[str]) -> tuple[int, dict]:
    cmd = [str(PY), "-m", "xinao_coordination.cli", "--db", str(db), *args]
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        return proc.returncode, {
            "ok": False,
            "error": "empty_stdout",
            "exit_code": proc.returncode,
            "stderr": stderr,
            "command": " ".join(args),
        }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return proc.returncode, {
            "ok": False,
            "error": "json_decode",
            "exit_code": proc.returncode,
            "stderr": stderr,
            "raw": stdout[:2000],
            "command": " ".join(args),
        }
    return proc.returncode, payload


def _snapshot(db: Path, label: str) -> dict:
    doctor_code, doctor = _cli(db, ["doctor"])
    status_code, status = _cli(db, ["status"])
    health = status.get("health") if isinstance(status.get("health"), dict) else {}
    counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
    return {
        "label": label,
        "db_path": db.as_posix(),
        "db_exists": db.is_file(),
        "doctor": {
            "exit_code": doctor_code,
            "ok": doctor_code == 0 and bool(doctor.get("ok")),
            "health_ok": bool((doctor.get("health") or {}).get("ok")) if isinstance(doctor.get("health"), dict) else bool(doctor.get("ok")),
            "schema_version": (doctor.get("health") or {}).get("schema_version") if isinstance(doctor.get("health"), dict) else None,
            "quick_check": (doctor.get("health") or {}).get("quick_check") if isinstance(doctor.get("health"), dict) else None,
        },
        "status": {
            "exit_code": status_code,
            "ok": status_code == 0 and bool(status.get("ok")),
            "schema_version": health.get("schema_version"),
            "quick_check": health.get("quick_check"),
            "journal_mode": health.get("journal_mode"),
            "threads": counts.get("threads"),
            "tasks": counts.get("tasks"),
            "queued_tasks": counts.get("queued_tasks"),
            "active_leases": counts.get("active_leases"),
            "events": counts.get("events"),
        },
    }


def _read_s1_w2_gate() -> dict:
    if not S1_W2_GATE.is_file():
        return {
            "evidence_exists": False,
            "gate_status": None,
            "hold_ok": True,
            "skipped_reason": "evidence_file_absent",
        }
    try:
        payload = json.loads(S1_W2_GATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "evidence_exists": True,
            "gate_status": None,
            "hold_ok": False,
            "error": str(exc),
        }
    gate = payload.get("gate_decision") if isinstance(payload.get("gate_decision"), dict) else {}
    gate_status = gate.get("status")
    hold_ok = gate_status == "HOLD_PLAN_ONLY"
    return {
        "evidence_exists": True,
        "path": S1_W2_GATE.as_posix(),
        "gate_status": gate_status,
        "hold_ok": hold_ok,
        "wiring_executed": payload.get("wiring_executed"),
        "prod_amq_init": payload.get("prod_amq_init"),
        "next_requires_user_or_explicit_w2": payload.get("next_requires_user_or_explicit_w2"),
    }


def main() -> int:
    utc_now = _utc_now()
    prod_amq_exists = PROD_AMQ.exists()
    prod_amq_missing_ok = not prod_amq_exists

    prod_snap = _snapshot(PROD_DB, "prod")
    canary_snap = _snapshot(CANARY_DB, "canary") if CANARY_DB.is_file() else {
        "label": "canary",
        "db_path": CANARY_DB.as_posix(),
        "db_exists": False,
        "doctor": {"ok": False, "skipped": True},
        "status": {"ok": False, "skipped": True},
    }

    prod_schema = prod_snap["status"].get("schema_version")
    canary_schema = canary_snap["status"].get("schema_version")
    schema_match = (
        prod_schema is not None
        and canary_schema is not None
        and prod_schema == canary_schema
    )

    comparison = {
        "schema_version": {
            "prod": prod_schema,
            "canary": canary_schema,
            "match": schema_match,
        },
        "threads": {
            "prod": prod_snap["status"].get("threads"),
            "canary": canary_snap["status"].get("threads"),
            "delta": (
                (prod_snap["status"].get("threads") or 0) - (canary_snap["status"].get("threads") or 0)
                if prod_snap["status"].get("threads") is not None
                and canary_snap["status"].get("threads") is not None
                else None
            ),
        },
        "tasks": {
            "prod": prod_snap["status"].get("tasks"),
            "canary": canary_snap["status"].get("tasks"),
            "delta": (
                (prod_snap["status"].get("tasks") or 0) - (canary_snap["status"].get("tasks") or 0)
                if prod_snap["status"].get("tasks") is not None
                and canary_snap["status"].get("tasks") is not None
                else None
            ),
        },
    }

    s1_w2 = _read_s1_w2_gate()

    assertions = {
        "prod_db_exists": prod_snap["db_exists"],
        "prod_doctor_ok": bool(prod_snap["doctor"].get("ok")),
        "prod_status_ok": bool(prod_snap["status"].get("ok")),
        "prod_amq_missing_ok": prod_amq_missing_ok,
        "s1_w2_gate_hold": bool(s1_w2.get("hold_ok")),
        "canary_db_exists": canary_snap["db_exists"],
        "schema_version_match": schema_match,
    }

    green: list[str] = []
    red: list[str] = []
    for key, ok in assertions.items():
        (green if ok else red).append(key)

    all_ok = all(assertions.values())
    status = "PASS" if all_ok else "FAIL"

    evidence = {
        "schema_version": "xinao.kaigong_wave.E_prod_kernel_fresh_verifier.v1",
        "package": "E",
        "task": "E_prod_kernel_fresh_verifier",
        "title_cn": "生产 kernel 非破坏性 fresh verifier（doctor/status + 边界闸）",
        "generated_at_utc": utc_now,
        "executor": "lane_e_writer",
        "mode": "non_destructive_read_only",
        "completion_claim_allowed": False,
        "product_closed": False,
        "hard_bans_honored": {
            "no_prod_amq_init": True,
            "no_prod_wiring_execute": True,
            "no_prod_db_write": True,
            "no_s1_w2_gate_mutation": True,
            "no_temporal_recreate": True,
        },
        "paths": {
            "prod_kernel_db": PROD_DB.as_posix(),
            "canary_kernel_db": CANARY_DB.as_posix(),
            "prod_amq_root": PROD_AMQ.as_posix(),
            "canary_amq_root": CANARY_AMQ.as_posix(),
            "s1_w2_gate_evidence": S1_W2_GATE.as_posix(),
            "evidence_out": EVIDENCE_OUT.as_posix(),
        },
        "boundary": {
            "prod_amq_exists": prod_amq_exists,
            "prod_amq_status": "PRESENT_NOT_USED" if prod_amq_exists else "MISSING_OK",
            "canary_amq_exists": CANARY_AMQ.exists(),
            "writes_prod": False,
            "writes_prod_amq": False,
        },
        "prod_kernel": prod_snap,
        "canary_kernel": canary_snap,
        "comparison": comparison,
        "s1_w2_gate": s1_w2,
        "assertions": assertions,
        "traffic_light": {
            "overall": "green" if all_ok else "red",
            "green": green,
            "red": red,
        },
        "verdict": {
            "status": status,
            "all_assertions_ok": all_ok,
            "prod_amq_init_performed": False,
        },
        "did_this_turn": [
            "cli doctor on prod coordination.sqlite3 (read-only)",
            "cli status on prod coordination.sqlite3 (read-only)",
            "assert prod amq path MISSING_OK",
            "read S1_W2_gate_latest.json and assert HOLD_PLAN_ONLY when present",
            "compare prod vs canary schema_version and thread/task counts",
            f"write {EVIDENCE_OUT.name}",
        ],
        "summary_cn": (
            f"E prod kernel fresh verifier {status}；prod doctor/status read-only；"
            f"prod amq={'缺失OK' if prod_amq_missing_ok else '存在(不应)'}；"
            f"S1_W2 gate={'HOLD' if s1_w2.get('hold_ok') else '异常'}。"
        ),
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_OUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"WROTE {EVIDENCE_OUT} status={status}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())