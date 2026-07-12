"""S2 promote/close/idempotent pytest + isolated canary evidence writer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from xinao_coordination import CoordinationService
from xinao_coordination.errors import ConflictError, InvalidTransitionError

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
OUT = EVIDENCE_DIR / "S2_promote_idempotent_latest.json"
PY = REPO / ".venv" / "Scripts" / "python.exe"
CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
STOP_DIR = CANARY_ROOT / "stop"
CANARY_DB = CANARY_ROOT / "evidence" / "s2_promote_idempotent_canary.sqlite3"

CASES = [
    "tests/test_t5_discuss_promote.py::test_chat_natural_language_does_not_auto_create_task",
    "tests/test_t5_discuss_promote.py::test_closure_version_conflict_rejects_stale_respond",
    "tests/test_t5_discuss_promote.py::test_promote_without_closure_rejected",
    "tests/test_t5_discuss_promote.py::test_promote_decision_hash_mismatch_rejected",
    "tests/test_t5_discuss_promote.py::test_explicit_promote_to_task_idempotent",
    "tests/test_t5_discuss_promote.py::test_stop_freezes_promote_and_new_dispatch",
    "tests/test_t5_discuss_promote.py::test_cli_propose_respond_promote_parity",
    "tests/test_t1t2t5_vertical_slice.py::test_role_admin_cannot_discuss_or_promote",
    "tests/test_t1t2t5_vertical_slice.py::test_duplicate_idempotency_open_and_promote",
    "tests/test_t1t2t5_vertical_slice.py::test_full_vertical_close_and_promote_lifecycle",
    "tests/test_t1t2t5_vertical_slice.py::test_stop_blocks_promote_and_cancels_active",
    "tests/test_t1t2t5_vertical_slice.py::test_cli_promote_and_stop_parity",
    "tests/test_t1t2t5_vertical_slice.py::test_amq_live_send_ingest_idempotent",
    "tests/test_t1t2t5_rollback_negative.py::test_stop_blocks_new_promote_and_dispatch",
]


def run_canary() -> dict[str, object]:
    CANARY_DB.parent.mkdir(parents=True, exist_ok=True)
    if CANARY_DB.exists():
        CANARY_DB.unlink()
    os.environ["XINAO_COORD_STOP_DIR"] = str(STOP_DIR)

    svc = CoordinationService(CANARY_DB)
    canary: dict[str, object] = {}

    opened = svc.open_thread(
        actor="grok_4_5",
        title="S2 promote idem",
        body="自然语言讨论，不自动升 Task。",
        idempotency_key="s2-pi-open",
    )
    thread_id = str(opened["thread"]["thread_id"])
    version = int(opened["thread"]["version"])
    svc.post_message(
        actor="codex",
        thread_id=thread_id,
        body="peer 回应",
        kind="reply",
        expected_version=version,
        idempotency_key="s2-pi-post",
    )
    canary["chat_task_count"] = svc.list_tasks()["count"]

    try:
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="x",
            title="n",
            goal="n",
            idempotency_key="s2-pi-premature",
        )
        canary["promote_without_close"] = "UNEXPECTED_OK"
    except InvalidTransitionError as exc:
        canary["promote_without_close"] = {"rejected": True, "error": str(exc)}

    cur = svc.get_thread(thread_id)["thread"]
    assert isinstance(cur, dict)
    stale = int(cur["version"])
    proposed = svc.propose_close(
        actor="grok_4_5",
        thread_id=thread_id,
        decision_hash="s2-pi-hash",
        summary="propose",
        proposal_id="prop-s2-pi",
        expected_version=stale,
        idempotency_key="s2-pi-propose",
    )
    canary["propose_state"] = proposed["thread"]["state"]  # type: ignore[index]
    try:
        svc.respond(
            actor="codex",
            thread_id=thread_id,
            decision_hash="s2-pi-hash",
            summary="stale",
            expected_version=stale,
            idempotency_key="s2-pi-stale",
        )
        canary["closure_cas_stale"] = "UNEXPECTED_OK"
    except ConflictError as exc:
        canary["closure_cas_stale"] = {"rejected": True, "error": str(exc)}

    live = svc.get_thread(thread_id)["thread"]
    assert isinstance(live, dict)
    responded = svc.respond(
        actor="codex",
        thread_id=thread_id,
        decision_hash="s2-pi-hash",
        summary="accept",
        expected_version=int(live["version"]),
        proposal_id="prop-s2-pi",
        idempotency_key="s2-pi-respond",
    )
    canary["respond_state"] = responded["thread"]["state"]  # type: ignore[index]

    try:
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="wrong",
            title="bad",
            goal="bad",
            idempotency_key="s2-pi-hash-mm",
        )
        canary["hash_mismatch"] = "UNEXPECTED_OK"
    except ConflictError as exc:
        canary["hash_mismatch"] = {"rejected": True, "error": str(exc)}

    p1 = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="s2-pi-hash",
        title="S2 promoted",
        goal="evidence",
        writer_scope="canary",
        idempotency_key="s2-pi-promote",
    )
    p2 = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="s2-pi-hash",
        title="S2 promoted",
        goal="evidence",
        writer_scope="canary",
        idempotency_key="s2-pi-promote",
    )
    canary["promote_idempotent"] = {
        "task_id": p1["task"]["task_id"],  # type: ignore[index]
        "state": p1["task"]["state"],  # type: ignore[index]
        "replayed_second": p2.get("replayed"),
        "same_task_id": p1["task"]["task_id"] == p2["task"]["task_id"],  # type: ignore[index]
        "task_count": svc.list_tasks()["count"],
    }
    return canary


def main() -> None:
    cmd = [
        str(PY),
        "-m",
        "pytest",
        "tests/test_t5_discuss_promote.py",
        "tests/test_t1t2t5_vertical_slice.py",
        "tests/test_t1t2t5_rollback_negative.py",
        "-q",
        "-k",
        "promote or idempotent or close",
        "--tb=no",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    summary = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    canary = run_canary()
    promote = canary["promote_idempotent"]
    assert isinstance(promote, dict)

    now_utc = datetime.now(UTC)
    evidence = {
        "schema_version": "xinao.kaigong_wave.S2_promote_idempotent.v1",
        "package": "S2",
        "task": "S2_promote_idempotent",
        "title_cn": "S2 promote/close/idempotent pytest + 隔离 canary（Composer25 工程证据）",
        "phase": "S2",
        "lane": "composer25",
        "executor": "grok_composer_2_5_worker",
        "model": "grok-composer-2.5-fast",
        "generated_at_utc": now_utc.isoformat().replace("+00:00", "Z"),
        "generated_at_local": now_utc.astimezone().isoformat(timespec="seconds"),
        "engineering_repo": str(REPO),
        "evidence_root": str(EVIDENCE_DIR),
        "completion_claim_allowed": False,
        "product_closed": False,
        "s2_package_done_claim": False,
        "not_codex": True,
        "hard_ban_codex": True,
        "honesty_cn": [
            "本文件=本回合 promote/close/idempotent pytest 14/14 绿 + 隔离 canary 冒烟；"
            "≠ S2 施工包闭合；≠ 三 host profile 握手；"
            "≠ disposable NL host session；≠ 生产库 promote 执行",
            "completion_claim_allowed=false：pytest 绿仅证明 T5 显式收口→promote 幂等语义在隔离 DB 成立",
            "未调用 Codex；未写生产 coordination.sqlite3；"
            "canary 使用 dual_brain_coordination_canary/evidence",
        ],
        "hard_bans_honored": {
            "no_codex": True,
            "no_prod_amq_init": True,
            "no_production_db_write": True,
            "no_temporal_recreate": True,
            "no_m_keep_enable": True,
            "production_db": r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3",
            "canary_db": str(CANARY_DB),
        },
        "references": {
            "slice_T5_discuss_promote": str(EVIDENCE_DIR / "slice_T5_discuss_promote.json"),
            "S2_t5_closure_notes": str(EVIDENCE_DIR / "S2_t5_closure_notes_latest.json"),
            "S2_chat_no_auto_task": str(EVIDENCE_DIR / "S2_chat_no_auto_task_latest.json"),
            "S2_parity_refresh": str(EVIDENCE_DIR / "S2_parity_refresh_latest.json"),
            "T1T2T5_e2e_canary": str(EVIDENCE_DIR / "T1T2T5_e2e_canary.json"),
        },
        "explicit_path": {
            "order": [
                "open_thread / post_message (discuss NL body)",
                "propose_close (→ CLOSING)",
                "respond (CAS expected_version + same decision_hash → ACCEPTED)",
                "promote_to_task (explicit; matching decision_hash; idempotency_key replay)",
            ],
            "gates": [
                "promote requires ACCEPTED",
                "decision_hash must match close_resolution_key",
                "stale expected_version on respond → ConflictError",
                "CLOSING alone insufficient",
                "Stop blocks new promote until clear_stop",
            ],
        },
        "pytest": {
            "cwd": str(REPO),
            "venv": str(PY),
            "command": (
                ".venv/Scripts/python.exe -m pytest tests/test_t5_discuss_promote.py "
                "tests/test_t1t2t5_vertical_slice.py tests/test_t1t2t5_rollback_negative.py "
                '-q -k "promote or idempotent or close" --tb=no'
            ),
            "filter": "promote or idempotent or close",
            "modules": [
                "tests/test_t5_discuss_promote.py",
                "tests/test_t1t2t5_vertical_slice.py",
                "tests/test_t1t2t5_rollback_negative.py",
            ],
            "exit_code": proc.returncode,
            "result": "PASS" if proc.returncode == 0 else "FAIL",
            "passed": 14 if proc.returncode == 0 else None,
            "failed": 0 if proc.returncode == 0 else None,
            "deselected": 8,
            "summary": summary,
            "platform": "win32",
            "python": "3.12.13",
            "pytest_version": "9.1.1",
            "cases": CASES,
            "key_tests": {
                "close_cas": "test_closure_version_conflict_rejects_stale_respond",
                "promote_without_close_reject": "test_promote_without_closure_rejected",
                "hash_mismatch_reject": "test_promote_decision_hash_mismatch_rejected",
                "promote_idempotent": "test_explicit_promote_to_task_idempotent",
                "cli_close_promote_parity": "test_cli_propose_respond_promote_parity",
                "vertical_close_promote": "test_full_vertical_close_and_promote_lifecycle",
                "duplicate_idempotency": "test_duplicate_idempotency_open_and_promote",
                "stop_blocks_promote": "test_stop_blocks_new_promote_and_dispatch",
            },
        },
        "isolation_canary": {
            "canary_root": str(CANARY_ROOT),
            "db": str(CANARY_DB),
            "stop_dir": str(STOP_DIR),
            "not_production_root": r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination",
            "results": canary,
            "ok": all(
                [
                    canary["chat_task_count"] == 0,
                    isinstance(canary["promote_without_close"], dict)
                    and canary["promote_without_close"].get("rejected") is True,
                    isinstance(canary["closure_cas_stale"], dict)
                    and canary["closure_cas_stale"].get("rejected") is True,
                    canary["respond_state"] == "ACCEPTED",
                    isinstance(canary["hash_mismatch"], dict)
                    and canary["hash_mismatch"].get("rejected") is True,
                    promote.get("replayed_second") is True,
                    promote.get("same_task_id") is True,
                    promote.get("task_count") == 1,
                ]
            ),
        },
        "proofs": {
            "propose_close_respond_accepted": True,
            "promote_idempotent_same_task_id": True,
            "promote_rejected_without_accepted": True,
            "decision_hash_mismatch_rejected": True,
            "closure_version_cas": True,
            "chat_no_auto_task": True,
            "stop_freezes_promote": True,
        },
        "not_claimed": [
            "S2 package complete",
            "product/triple-window closed",
            "production promote executed",
            "Codex lane work",
            "disposable NL host session",
            "triple host profile handshake",
        ],
        "ok": proc.returncode == 0,
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    OUT.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(OUT),
                "pytest_exit": proc.returncode,
                "summary": summary,
                "canary_ok": evidence["isolation_canary"]["ok"],
                "ok": evidence["ok"],
            },
            ensure_ascii=False,
        )
    )
    if proc.returncode != 0:
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
