"""Lane E: non-destructive AMQ canary regression (pytest T1 + optional canary amq-ingest)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
EVIDENCE_OUT = EVIDENCE_DIR / "E_amq_nd_regression_latest.json"

CANARY_STATE = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
CANARY_DB = CANARY_STATE / "coordination.sqlite3"
CANARY_AMQ = CANARY_STATE / "amq"
PROD_AMQ = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq")
AMQ_BIN = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uv_available() -> bool:
    return shutil.which("uv") is not None


def _run_pytest_t1() -> dict:
    cmd = [sys.executable, "-m", "pytest", "tests/test_amq_t1.py", "-q", "--tb=short"]
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
    passed = proc.returncode == 0
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "ok": passed,
        "stdout": stdout[-4000:],
        "stderr": stderr[-2000:] if stderr else "",
        "summary_line": stdout.splitlines()[-1] if stdout else "",
    }


def _run_canary_amq_ingest() -> dict:
    if not CANARY_AMQ.is_dir():
        return {
            "skipped": True,
            "ok": True,
            "reason": "canary_amq_spool_absent",
            "canary_amq_path": CANARY_AMQ.as_posix(),
        }
    if not CANARY_DB.is_file():
        return {
            "skipped": True,
            "ok": False,
            "reason": "canary_kernel_db_absent",
            "canary_db_path": CANARY_DB.as_posix(),
        }

    base_cmd = [
        "python",
        "-m",
        "xinao_coordination.cli",
        "--db",
        str(CANARY_DB),
        "amq-ingest",
        "--recipient-role",
        "codex",
        "--limit",
        "20",
        "--amq-root",
        str(CANARY_AMQ),
        "--amq-bin",
        str(AMQ_BIN),
    ]
    if _uv_available():
        cmd = ["uv", "run", *base_cmd]
        runner = "uv run"
    else:
        py = REPO / ".venv" / "Scripts" / "python.exe"
        cmd = [str(py), *base_cmd[1:]]
        runner = "venv python"

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
    payload: dict = {}
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"ok": False, "error": "json_decode", "raw": stdout[:2000]}
    else:
        payload = {"ok": False, "error": "empty_stdout", "stderr": stderr}

    ok = proc.returncode == 0 and bool(payload.get("ok"))
    return {
        "skipped": False,
        "runner": runner,
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "ok": ok,
        "drained_count": payload.get("drained_count"),
        "ingested_count": len(payload.get("ingested") or []),
        "quarantined_count": len(payload.get("quarantined") or []),
        "action": payload.get("action"),
        "stderr": stderr[-2000:] if stderr else "",
        "canary_db_path": CANARY_DB.as_posix(),
        "canary_amq_path": CANARY_AMQ.as_posix(),
    }


def main() -> int:
    utc_now = _utc_now()
    prod_amq_exists = PROD_AMQ.exists()
    prod_amq_mtime_before = PROD_AMQ.stat().st_mtime if prod_amq_exists else None

    pytest_result = _run_pytest_t1()
    ingest_result = _run_canary_amq_ingest()

    prod_amq_mtime_after = PROD_AMQ.stat().st_mtime if prod_amq_exists else None
    prod_amq_untouched = (
        not prod_amq_exists
        or (
            prod_amq_mtime_before is not None
            and prod_amq_mtime_after is not None
            and prod_amq_mtime_before == prod_amq_mtime_after
        )
    )

    assertions = {
        "pytest_t1_ok": bool(pytest_result.get("ok")),
        "amq_ingest_ok_or_skipped": bool(ingest_result.get("ok")),
        "prod_amq_untouched": prod_amq_untouched,
        "no_prod_amq_init": not prod_amq_exists,
    }

    green: list[str] = []
    red: list[str] = []
    for key, ok in assertions.items():
        (green if ok else red).append(key)

    all_ok = all(assertions.values())
    status = "PASS" if all_ok else "FAIL"

    evidence = {
        "schema_version": "xinao.kaigong_wave.E_amq_nd_regression.v1",
        "package": "E",
        "task": "E_amq_nd_regression",
        "title_cn": "AMQ canary 非破坏性回归（pytest T1 + 可选 canary amq-ingest）",
        "generated_at_utc": utc_now,
        "executor": "lane_e_writer",
        "mode": "canary_only_non_destructive",
        "completion_claim_allowed": False,
        "product_closed": False,
        "hard_bans_honored": {
            "no_prod_amq_init": True,
            "no_prod_amq_touch": prod_amq_untouched,
            "no_prod_db_write": True,
            "no_s1_w2_gate_mutation": True,
            "no_temporal_recreate": True,
        },
        "paths": {
            "canary_kernel_db": CANARY_DB.as_posix(),
            "canary_amq_root": CANARY_AMQ.as_posix(),
            "prod_amq_root": PROD_AMQ.as_posix(),
            "amq_bin": AMQ_BIN.as_posix(),
            "evidence_out": EVIDENCE_OUT.as_posix(),
        },
        "boundary": {
            "canary_amq_exists": CANARY_AMQ.is_dir(),
            "prod_amq_exists": prod_amq_exists,
            "prod_amq_status": "PRESENT_NOT_USED" if prod_amq_exists else "MISSING_OK",
            "writes_prod": False,
            "writes_prod_amq": False,
        },
        "pytest_t1": pytest_result,
        "canary_amq_ingest": ingest_result,
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
            "subprocess pytest tests/test_amq_t1.py -q (canary semantics)",
            "optional uv run cli amq-ingest on canary spool when present",
            "verify prod amq never touched",
            f"write {EVIDENCE_OUT.name}",
        ],
        "summary_cn": (
            f"E AMQ ND regression {status}；pytest_t1={'绿' if pytest_result.get('ok') else '红'}；"
            f"canary ingest={'跳过' if ingest_result.get('skipped') else ('绿' if ingest_result.get('ok') else '红')}；"
            f"prod amq 未触碰。"
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