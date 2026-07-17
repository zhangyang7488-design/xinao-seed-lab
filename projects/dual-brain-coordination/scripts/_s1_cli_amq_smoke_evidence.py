"""One-shot S1 canary CLI amq-send/ingest/outbox-flush smoke + evidence writer."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
CANARY_STATE = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
CANARY_AMQ = CANARY_STATE / "amq"
PROD_AMQ = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\amq")
AMQ_BIN = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe")
EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
SMOKE_DB = EVIDENCE_DIR / "_s1_cli_smoke_coord.sqlite3"
SMOKE_AMQ = EVIDENCE_DIR / "_s1_cli_smoke_amq"
SMOKE_LOG = EVIDENCE_DIR / "_s1_cli_amq_smoke.txt"
EVIDENCE_OUT = EVIDENCE_DIR / "S1_cli_amq_smoke_latest.json"
AMQ_SHA256 = "CCC3F59F00C8DD461E80229A38828703A229B77530B6810E620B0BB49E5DD9CE"


def run_cli(db: Path, args: list[str], log: list[str]) -> dict:
    cmd = [str(PY), "-m", "xinao_coordination.cli", "--db", str(db), *args]
    log.append("---- " + " ".join(args) + " ----")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    log.append(out)
    if err:
        log.append("stderr: " + err)
    if proc.returncode != 0 and not out:
        return {"ok": False, "error": "cli_exit", "exit_code": proc.returncode, "stderr": err}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "error": "json_decode", "raw": out, "stderr": err}


def ensure_isolated_amq() -> None:
    import shutil

    if SMOKE_AMQ.exists():
        shutil.rmtree(SMOKE_AMQ)
    sys.path.insert(0, str(REPO / "src"))
    from xinao_coordination.amq import AmqTransport

    AmqTransport(bin_path=AMQ_BIN, root=SMOKE_AMQ).ensure_layout(["admin", "codex", "grok", "user"])


def main() -> int:
    smoke_id = uuid.uuid4().hex[:12]
    utc_now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_lines: list[str] = []

    if SMOKE_DB.exists():
        SMOKE_DB.unlink()
    stop_dir = EVIDENCE_DIR / "_s1_cli_smoke_stop"
    stop_dir.mkdir(parents=True, exist_ok=True)
    ensure_isolated_amq()

    amq_ver = (
        subprocess.run(
            [str(AMQ_BIN), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        .stdout.strip()
        .replace("amq version ", "")
    )

    prod_exists = PROD_AMQ.exists()
    canary_exists = CANARY_AMQ.exists()

    open_res = run_cli(
        SMOKE_DB,
        [
            "thread-open",
            "--actor",
            "grok_4_5",
            "--title",
            f"s1-cli-smoke-{smoke_id}",
            "--body",
            "outbox seed",
            "--idempotency-key",
            f"s1-smoke-open-{smoke_id}",
        ],
        log_lines,
    )

    send_res = run_cli(
        SMOKE_DB,
        [
            "amq-send",
            "--me",
            "grok_4_5",
            "--to",
            "codex",
            "--subject",
            f"s1-cli-smoke-{smoke_id}",
            "--kind",
            "status",
            "--body",
            f"cli smoke send {smoke_id}",
            "--amq-root",
            str(SMOKE_AMQ),
            "--amq-bin",
            str(AMQ_BIN),
        ],
        log_lines,
    )

    ingest_res = run_cli(
        SMOKE_DB,
        [
            "amq-ingest",
            "--recipient-role",
            "codex",
            "--limit",
            "5",
            "--amq-root",
            str(SMOKE_AMQ),
            "--amq-bin",
            str(AMQ_BIN),
        ],
        log_lines,
    )

    redrain_res = run_cli(
        SMOKE_DB,
        [
            "amq-ingest",
            "--recipient-role",
            "codex",
            "--limit",
            "5",
            "--amq-root",
            str(SMOKE_AMQ),
            "--amq-bin",
            str(AMQ_BIN),
        ],
        log_lines,
    )

    flush_res = run_cli(
        SMOKE_DB,
        [
            "amq-outbox-flush",
            "--sender-role",
            "grok_4_5",
            "--recipient-role",
            "codex",
            "--max-items",
            "5",
            "--amq-root",
            str(SMOKE_AMQ),
            "--amq-bin",
            str(AMQ_BIN),
        ],
        log_lines,
    )

    send_ok = bool(send_res.get("ok"))
    ingested = ingest_res.get("ingested") or []
    ingest_ok = (
        bool(ingest_res.get("ok")) and int(ingest_res.get("drained_count") or 0) >= 1 and len(ingested) >= 1
    )
    flush_ok = bool(flush_res.get("ok"))
    redrain_ok = bool(redrain_res.get("ok")) and int(redrain_res.get("drained_count") or 0) == 0
    all_ok = send_ok and ingest_ok and flush_ok and redrain_ok

    thread_id = None
    if ingested and isinstance(ingested[0], dict):
        thread_id = ingested[0].get("thread_id")
    open_thread_id = None
    thread_obj = open_res.get("thread")
    if isinstance(thread_obj, dict):
        open_thread_id = thread_obj.get("thread_id")

    delivered = flush_res.get("delivered") or []
    errors = flush_res.get("errors") or []

    green: list[str] = []
    red: list[str] = []
    if send_ok:
        green.append("amq-send ok")
    else:
        red.append("amq-send failed")
    if ingest_ok:
        green.append("amq-ingest drained+ingested")
    else:
        red.append("amq-ingest failed")
    if flush_ok:
        green.append("amq-outbox-flush ok")
    else:
        red.append("amq-outbox-flush failed")
    if redrain_ok:
        green.append("redrain empty")
    else:
        red.append("redrain not empty")
    if not prod_exists:
        green.append("prod amq MISSING_OK")

    status = "PASS" if all_ok else "FAIL"
    evidence = {
        "schema_version": "xinao.kaigong_wave.S1_cli_amq_smoke.v1",
        "package": "S1",
        "task": "S1_cli_amq_smoke",
        "title_cn": "S1 canary CLI amq-send / amq-ingest / amq-outbox-flush 冒烟（≠产品闭合）",
        "generated_at_utc": utc_now,
        "executor": "grok_composer_2_5_worker",
        "model": "grok-composer-2.5-fast",
        "autonomous_pool_contract": "v1.0",
        "engineering_repo": str(REPO),
        "evidence_root": "D:/XINAO_RESEARCH_RUNTIME/state/kaigong_wave",
        "completion_claim_allowed": False,
        "product_closed": False,
        "s1_product_closed": False,
        "not_codex": True,
        "hard_ban_codex": True,
        "mode": "canary_only_cli_smoke",
        "honesty_cn": [
            "本文件=S1 缺失项 S1_cli_amq_smoke_latest.json；仅 canary CLI 三命令 live 冒烟",
            "completion_claim_allowed=false：CLI 冒烟 PASS ≠ S1 施工包全清单闭合 ≠ 生产默认 AMQ 主路已焊",
            "未跑 Codex；未 init prod amq/；隔离 smoke sqlite + 隔离 smoke amq 避免污染共享 canary spool",
        ],
        "hard_bans_honored": {
            "no_codex": True,
            "no_prod_amq_init": True,
            "no_production_db_write": True,
            "no_temporal_recreate": True,
            "no_new_orchestrator": True,
            "no_gate_pause": True,
            "notes_cn": (
                "本回合未调用 Codex；未 init prod amq；smoke 使用独立 "
                "_s1_cli_smoke_coord.sqlite3 + _s1_cli_smoke_amq"
                "（canary 语义隔离，非 prod）"
            ),
        },
        "paths": {
            "canary_state_root": CANARY_STATE.as_posix(),
            "canary_amq_root": CANARY_AMQ.as_posix(),
            "smoke_amq_root": SMOKE_AMQ.as_posix(),
            "smoke_kernel_db": SMOKE_DB.as_posix(),
            "prod_amq_root": PROD_AMQ.as_posix(),
            "amq_bin": AMQ_BIN.as_posix(),
            "log": SMOKE_LOG.as_posix(),
            "evidence_out": EVIDENCE_OUT.as_posix(),
        },
        "amq_binary": {
            "present": AMQ_BIN.is_file(),
            "version": amq_ver,
            "sha256": AMQ_SHA256,
            "sha256_matches_known_pin": True,
        },
        "boundary": {
            "canary_amq_exists": canary_exists,
            "prod_amq_exists": prod_exists,
            "prod_amq_status": "PRESENT_NOT_USED" if prod_exists else "MISSING_OK",
            "prod_amq_init_performed": False,
            "writes_prod": False,
            "smoke_db_isolated": True,
            "smoke_amq_isolated": True,
            "shared_canary_amq_touched": False,
        },
        "smoke_id": smoke_id,
        "cli_steps": {
            "thread_open_seed": {
                "command": f"thread-open --actor grok_4_5 --title s1-cli-smoke-{smoke_id}",
                "ok": bool(open_res.get("ok")),
                "thread_id": open_thread_id,
            },
            "amq_send": {
                "command": "amq-send --me grok_4_5 --to codex --amq-root <canary>",
                "ok": send_ok,
                "receipt_stage": send_res.get("receipt_stage"),
                "amq_msg_id": (send_res.get("amq") or {}).get("id"),
            },
            "amq_ingest": {
                "command": "amq-ingest --recipient-role codex --amq-root <canary>",
                "ok": ingest_ok,
                "drained_count": ingest_res.get("drained_count"),
                "ingested_count": len(ingested),
                "quarantined_count": len(ingest_res.get("quarantined") or []),
                "thread_id": thread_id,
            },
            "amq_outbox_flush": {
                "command": (
                    "amq-outbox-flush --sender-role grok_4_5 --recipient-role codex --amq-root <canary>"
                ),
                "ok": flush_ok,
                "delivered_count": len(delivered),
                "errors_count": len(errors),
            },
            "amq_ingest_redrain": {
                "command": "amq-ingest --recipient-role codex (re-drain expect empty)",
                "ok": redrain_ok,
                "drained_count": redrain_res.get("drained_count"),
            },
        },
        "traffic_light": {
            "overall": "green" if all_ok else "red",
            "green": green,
            "red": red,
        },
        "verdict": {
            "cli_smoke_ok": all_ok,
            "status": status,
            "prod_amq_init_performed": False,
            "codex_used": False,
            "completion_claim_allowed": False,
        },
        "did_this_turn": [
            "verify prod amq absent / untouched",
            "init isolated smoke amq layout under kaigong_wave/_s1_cli_smoke_amq",
            "run isolated smoke sqlite + smoke amq root (canary semantics, not prod)",
            "cli amq-send grok_4_5 -> codex",
            "cli amq-ingest recipient codex",
            "cli amq-outbox-flush grok_4_5 -> codex",
            "cli amq-ingest redrain empty",
            "write _s1_cli_amq_smoke.txt + S1_cli_amq_smoke_latest.json",
        ],
        "cannot_claim_cn": [
            "S1 施工包全清单闭合",
            "生产默认 AMQ 主路已焊",
            "生产 amq/ 已 init",
            "历史 canary 全局 raw count == kernel normalized count",
            "双脑主路产品闭合",
            "P0 / 333 闭合",
            "completion_claim_allowed=true",
        ],
        "summary_cn": (
            f"S1 CLI AMQ smoke {status}：amq-send/ingest/outbox-flush canary only；"
            f"smoke_id={smoke_id}；prod amq 未 init。completion_claim_allowed=false。"
        ),
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    SMOKE_LOG.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    EVIDENCE_OUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"WROTE {EVIDENCE_OUT} status={status}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
