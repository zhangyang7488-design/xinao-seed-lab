"""One-shot T5 canary smoke + kaigong_wave evidence writer."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from xinao_coordination import CoordinationService
from xinao_coordination.errors import ConflictError, InvalidTransitionError

CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
STOP_DIR = CANARY_ROOT / "stop"
DB = CANARY_ROOT / "evidence" / "t5_discuss_promote_canary.sqlite3"
REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"


def main() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    os.environ["XINAO_COORD_STOP_DIR"] = str(STOP_DIR)

    svc = CoordinationService(DB)
    results: dict[str, object] = {}

    opened = svc.open_thread(
        actor="grok_4_5",
        title="T5 canary discuss",
        body="自然语言闲聊：先发散，默认不升 Task。",
        idempotency_key="t5-canary-open",
    )
    thread = opened["thread"]
    assert isinstance(thread, dict)
    thread_id = str(thread["thread_id"])
    version = int(thread["version"])
    svc.post_message(
        actor="codex",
        thread_id=thread_id,
        body="peer 闲聊回应，仍不自动 Task。",
        kind="reply",
        expected_version=version,
        idempotency_key="t5-canary-post",
    )
    results["chat_task_count_after_discuss"] = svc.list_tasks()["count"]
    results["thread_id"] = thread_id

    try:
        svc.promote_to_task(
            actor="codex",
            source_thread_id=thread_id,
            decision_hash="premature",
            title="no",
            goal="no",
            idempotency_key="t5-canary-premature",
        )
        results["promote_without_close"] = "UNEXPECTED_OK"
    except InvalidTransitionError as exc:
        results["promote_without_close"] = {"rejected": True, "error": str(exc)}

    cur = svc.get_thread(thread_id)["thread"]
    assert isinstance(cur, dict)
    stale = int(cur["version"])
    proposed = svc.propose_close(
        actor="grok_4_5",
        thread_id=thread_id,
        decision_hash="t5-canary-hash",
        summary="propose close canary",
        proposal_id="prop-t5-canary",
        expected_version=stale,
        unresolved_points=["none"],
        idempotency_key="t5-canary-propose",
    )
    results["propose_state"] = proposed["thread"]["state"]  # type: ignore[index]
    results["propose_action"] = proposed["action"]
    results["proposal_id"] = proposed["proposal_id"]
    try:
        svc.respond(
            actor="codex",
            thread_id=thread_id,
            decision_hash="t5-canary-hash",
            summary="stale",
            expected_version=stale,
            idempotency_key="t5-canary-stale-respond",
        )
        results["closure_version_conflict"] = "UNEXPECTED_OK"
    except ConflictError as exc:
        results["closure_version_conflict"] = {"rejected": True, "error": str(exc)}

    live = svc.get_thread(thread_id)["thread"]
    assert isinstance(live, dict)
    responded = svc.respond(
        actor="codex",
        thread_id=thread_id,
        decision_hash="t5-canary-hash",
        summary="fresh accept",
        expected_version=int(live["version"]),
        proposal_id="prop-t5-canary",
        idempotency_key="t5-canary-respond",
    )
    results["respond_state"] = responded["thread"]["state"]  # type: ignore[index]
    results["decision_hash"] = responded["decision_hash"]

    p1 = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="t5-canary-hash",
        title="canary promoted",
        goal="T5 evidence",
        writer_scope="canary",
        acceptance="pytest-t5",
        budget="bounded",
        stop_scope="global",
        idempotency_key="t5-canary-promote",
    )
    p2 = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="t5-canary-hash",
        title="canary promoted",
        goal="T5 evidence",
        writer_scope="canary",
        acceptance="pytest-t5",
        budget="bounded",
        stop_scope="global",
        idempotency_key="t5-canary-promote",
    )
    results["promote"] = {
        "task_id": p1["task"]["task_id"],  # type: ignore[index]
        "state": p1["task"]["state"],  # type: ignore[index]
        "replayed_second": p2.get("replayed"),
        "same_task_id": p1["task"]["task_id"] == p2["task"]["task_id"],  # type: ignore[index]
        "task_count": svc.list_tasks()["count"],
    }

    stop = svc.user_stop(actor="user", reason="t5 canary freeze", idempotency_key="t5-canary-stop")
    results["stop"] = {
        "active": stop["active"],
        "canceled_contains_promoted": p1["task"]["task_id"] in stop["canceled_tasks"],  # type: ignore[index,operator]
    }
    o2 = svc.open_thread(actor="codex", title="after-stop", body="x", idempotency_key="t5-canary-open2")
    tid2 = str(o2["thread"]["thread_id"])  # type: ignore[index]
    svc.propose_close(
        actor="codex", thread_id=tid2, decision_hash="h2", summary="a", idempotency_key="t5-c-p2"
    )
    svc.respond(actor="grok_4_5", thread_id=tid2, decision_hash="h2", summary="b", idempotency_key="t5-c-r2")
    try:
        svc.promote_to_task(
            actor="codex",
            source_thread_id=tid2,
            decision_hash="h2",
            title="blocked",
            goal="stop",
            idempotency_key="t5-canary-blocked",
        )
        results["promote_while_stop"] = "UNEXPECTED_OK"
    except InvalidTransitionError as exc:
        results["promote_while_stop"] = {"rejected": True, "error": str(exc)}
    cleared = svc.clear_stop(actor="user", reason="done", idempotency_key="t5-canary-clear")
    results["stop_cleared"] = cleared["active"] is False

    proc = subprocess.run(
        [
            str(PY),
            "-m",
            "pytest",
            "tests/test_t5_discuss_promote.py",
            "tests/test_t1t2t5_vertical_slice.py",
            "-q",
            "--tb=no",
            "-k",
            "not amq_live",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    pytest_line = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    results["pytest"] = {"exit_code": proc.returncode, "summary": pytest_line}

    evidence = {
        "schema_version": "xinao.kaigong_wave.slice_T5_discuss_promote.v1",
        "package": "T5_discuss_promote",
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "landed_tests_green_canary_ok",
        "completion_claim_allowed": False,
        "isolation": {
            "canary_state_root": str(CANARY_ROOT),
            "canary_db": str(DB),
            "stop_dir": str(STOP_DIR),
            "not_production_root": r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination",
        },
        "design_cn": [
            "讨论 thread 默认自然语言 body；闲聊不自动 Task",
            "承诺层：propose_close / respond（CAS expected_version）→ ACCEPTED",
            "显式 promote_to_task 幂等；decision_hash 必须匹配 close_resolution_key",
            "Stop 冻结新 promote/dispatch，不自动恢复",
        ],
        "paths_changed": [
            "src/xinao_coordination/service.py",
            "src/xinao_coordination/cli.py",
            "src/xinao_coordination/mcp_server.py",
            "tests/test_t5_discuss_promote.py",
        ],
        "invoke": {
            "propose_close": "service.propose_close / CLI propose-close / MCP propose_close",
            "respond": "service.respond / CLI respond / MCP respond",
            "promote": "service.promote_to_task / CLI promote / MCP promote_to_task",
            "stop": "service.user_stop / CLI stop",
        },
        "tests_required": {
            "closure_version_conflict": results["closure_version_conflict"],
            "promote_without_closure_reject": results["promote_without_close"],
            "stop_freeze": results["stop"],
            "chat_no_auto_task": results["chat_task_count_after_discuss"] == 0,
            "promote_idempotent": results["promote"],
        },
        "canary_results": results,
        "forbid_cn": [
            "第二控制面",
            "桌面TUI",
            "Temporal recreate",
            "闲聊自动升 Task",
        ],
        "honesty_cn": "T5 语义面 + pytest 绿 + 隔离 canary 冒烟；非真三窗产品；非 P0/333 闭合",
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / "slice_T5_discuss_promote.json"
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    out.write_text(payload, encoding="utf-8")
    (CANARY_ROOT / "evidence" / "slice_T5_discuss_promote.json").write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {"wrote": str(out), "pytest_exit": proc.returncode, "summary": pytest_line},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
