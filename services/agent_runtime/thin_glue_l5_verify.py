"""L5 验收 — pytest-json-report 并进 thin-glue 默认链（替 verify PS1 马拉松）."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso, write_json


def run_l5_pytest_verify(
    *,
    repo: Path,
    runtime: Path,
    run_id: str,
    test_paths: list[str] | None = None,
) -> dict[str, Any]:
    candidates = test_paths or [
        "tests/test_closure_test_proof.py",
        "tests/test_thin_glue_work_proof.py",
        "tests/test_thin_bootstrap_runner.py",
        "tests/test_thin_glue_stack.py",
    ]
    selected = [p for p in candidates if (repo / p).is_file()]
    if not selected:
        return {
            "layer": "L5",
            "skipped": True,
            "passed": True,
            "reason": "no_pytest_targets_in_repo",
        }

    report_path = runtime / "evidence" / run_id / "pytest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *selected,
        "-q",
        "--json-report",
        f"--json-report-file={report_path}",
    ]
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
    payload: dict[str, Any] = {
        "layer": "L5",
        "adapter": "pytest-json-report",
        "test_paths": selected,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-1000:],
        "report_path": str(report_path),
    }
    if report_path.is_file():
        try:
            payload["report"] = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["report"] = {}
    else:
        write_json(report_path, {"exit_code": proc.returncode, "tests": []})
    payload["passed"] = proc.returncode == 0
    payload["pytest_node_count"] = len(payload.get("report", {}).get("tests", []) or [])
    append_jsonl(
        runtime / "evidence" / run_id / "execution.jsonl",
        {"layer": "L5", "activity": "pytest", "passed": payload["passed"], "timestamp": now_iso()},
    )
    return payload