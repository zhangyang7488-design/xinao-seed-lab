"""Bounded pytest verification used by the integrated-bus promotion gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso, write_json

LOOP_TEST_PATHS = [
    "tests/test_integrated_bus_hot_path.py",
    "tests/test_integrated_bus_git_isolation.py",
]
DEFAULT_TEST_PATHS = [
    *LOOP_TEST_PATHS,
    "tests/test_repo_safety.py",
]


def run_l5_pytest_verify(
    *,
    repo: Path,
    runtime: Path,
    run_id: str,
    test_paths: list[str] | None = None,
) -> dict[str, Any]:
    candidates = test_paths or list(DEFAULT_TEST_PATHS)
    selected: list[str] = []
    for spec in candidates:
        file_part = spec.split("::", 1)[0]
        if (repo / file_part).is_file():
            selected.append(spec)
    if not selected:
        return {
            "layer": "L5",
            "skipped": True,
            "passed": False,
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
