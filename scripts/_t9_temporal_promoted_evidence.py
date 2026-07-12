"""T9 Temporal promoted-task thin adapter — isolated canary evidence writer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave")
OUT = EVIDENCE_DIR / "T9_temporal_promoted_canary_latest.json"
CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
CANARY_DB = CANARY_ROOT / "evidence" / "t9_temporal_promoted_canary.sqlite3"

CASES = [
    "tests/test_t9_temporal_promoted_adapter.py",
    "tests/test_t6t7t8_vertical_slice.py::test_t8_mbg_status_defaults",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def run_pytest() -> dict[str, object]:
    cmd = [sys.executable, "-m", "pytest", *CASES, "-q", "--tb=no"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=False)
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout.strip()[-2000:],
        "stderr_tail": proc.stderr.strip()[-1000:],
        "passed": proc.returncode == 0,
    }


def _accepted_thread(svc: object, suffix: str) -> str:
    from xinao_coordination import CoordinationService

    assert isinstance(svc, CoordinationService)
    opened = svc.open_thread(
        actor="grok_4_5",
        title=f"t9 {suffix}",
        body="proposal",
        idempotency_key=f"t9-open-{suffix}",
    )
    thread_id = str(opened["thread"]["thread_id"])
    version = int(opened["thread"]["version"])
    svc.post_message(
        actor="codex",
        thread_id=thread_id,
        body="counter",
        kind="counter",
        expected_version=version,
        idempotency_key=f"t9-post-{suffix}",
    )
    svc.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"resolution-{suffix}",
        summary="accepted",
        idempotency_key=f"t9-close-a-{suffix}",
    )
    svc.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"resolution-{suffix}",
        summary="accepted",
        idempotency_key=f"t9-close-b-{suffix}",
    )
    return thread_id


def run_canary() -> dict[str, object]:
    from xinao_coordination import CoordinationService
    from xinao_coordination.temporal.client import reset_mock_registry

    CANARY_DB.parent.mkdir(parents=True, exist_ok=True)
    if CANARY_DB.exists():
        CANARY_DB.unlink()
    os.environ["XINAO_TEMPORAL_ENABLED"] = "1"
    os.environ["XINAO_TEMPORAL_MOCK"] = "1"
    os.environ["XINAO_TEMPORAL_LIVE"] = "0"
    reset_mock_registry()

    svc = CoordinationService(CANARY_DB)
    thread_id = _accepted_thread(svc, "t9-evidence")
    promoted = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash="resolution-t9-evidence",
        title="T9 canary promoted task",
        goal="temporal thin adapter evidence",
        idempotency_key="t9-ev-promote",
    )
    task_id = str(promoted["task"]["task_id"])
    status = svc.temporal_status()
    started = svc.temporal_start_promoted(
        actor="codex",
        task_id=task_id,
        idempotency_key="t9-ev-start",
    )
    replay = svc.temporal_start_promoted(
        actor="codex",
        task_id=task_id,
        idempotency_key="t9-ev-start",
    )
    return {
        "canary_db": str(CANARY_DB),
        "task_id": task_id,
        "temporal_status": {
            "enabled": status["policy"]["enabled"],
            "mock_mode": status["policy"]["mock_mode"],
            "auto_start_on_promote": status["auto_start_on_promote"],
            "mbg_temporal_owner": status["mbg_temporal_owner"],
            "task_queue": status["promoted_queue"]["task_queue"],
        },
        "first_start": {
            "workflow_id": started["workflow_id"],
            "mode": started["mode"],
            "replayed": started["replayed"],
        },
        "idempotent_replay": replay["replayed"],
    }


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    pytest_result = run_pytest()
    canary = run_canary() if pytest_result["passed"] else {"skipped": "pytest_failed"}

    adapter_paths = [
        REPO / "adapters" / "temporal",
        REPO / "src" / "xinao_coordination" / "temporal",
        REPO / "configs" / "modules" / "temporal.toml",
    ]
    on_disk = {
        str(p.relative_to(REPO)): {"exists": p.exists(), "sha256": _sha256(p) if p.is_file() else None}
        for p in adapter_paths
    }

    payload = {
        "schema_version": "xinao.kaigong_wave.T9_temporal_promoted_canary.v1",
        "phase": "S5/T9",
        "title_cn": "T9 Temporal promoted-task 薄适配 canary（mock，无 live recreate）",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "executor": "composer_admin_night_run",
        "implementation_landed": True,
        "live_workflow_start_attempted": False,
        "live_temporal_recreate": False,
        "completion_claim_allowed": False,
        "product_closed": False,
        "hard_bans": {
            "no_live_temporal_recreate": True,
            "no_docker_compose_up": True,
            "no_chat_to_temporal": True,
            "workflow_start_live": False,
        },
        "pytest": pytest_result,
        "canary_flow": canary,
        "on_disk_probe": on_disk,
        "repo": str(REPO),
        "verdict": (
            "PASS_SCOPED_CANARY"
            if pytest_result["passed"] and canary.get("idempotent_replay") is True
            else "PARTIAL_OR_FAIL"
        ),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(OUT), "verdict": payload["verdict"]}, ensure_ascii=False))
    return 0 if payload["verdict"] == "PASS_SCOPED_CANARY" else 1


if __name__ == "__main__":
    raise SystemExit(main())