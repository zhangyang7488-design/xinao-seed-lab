"""L3 真执行 — 沙箱内改 S 仓文件（Docker 挂载或本地 subprocess）."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_bootstrap_sandbox import (
    SandboxResult,
    run_cheapest_sandbox,
    run_local_python_sandbox,
)
from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso

PROOF_REL = Path("services/agent_runtime/thin_glue_work_proof.py")
TEST_REL = Path("tests/test_thin_glue_work_proof.py")

TEST_TEMPLATE = '''from services.agent_runtime.thin_glue_work_proof import last_run_id


def test_thin_glue_work_proof_has_run_id() -> None:
    assert last_run_id()
'''


def _docker_mounted_sandbox(code: str, repo_root: Path, *, timeout_s: int = 120) -> SandboxResult:
    mount = str(repo_root.resolve())
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{mount}:/work",
            "-w",
            "/work",
            "python:3.12-slim",
            "python",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return SandboxResult(
        stdout=(proc.stdout or "").strip(),
        stderr=(proc.stderr or "").strip(),
        exit_code=int(proc.returncode),
        backend="docker:mounted:python:3.12-slim",
    )


def run_l3_repo_patch(
    *,
    repo_root: Path,
    runtime_root: Path,
    run_id: str,
    task_preview: str = "",
    prefer_docker: bool = True,
) -> dict[str, Any]:
    proof_path = repo_root / PROOF_REL
    test_path = repo_root / TEST_REL
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.parent.mkdir(parents=True, exist_ok=True)
    if not test_path.is_file():
        test_path.write_text(TEST_TEMPLATE, encoding="utf-8")

    preview_literal = json.dumps(task_preview[:200], ensure_ascii=False)
    patch_code = (
        "from pathlib import Path\n"
        "from datetime import datetime\n"
        f"run_id = {json.dumps(run_id)}\n"
        f"preview = {preview_literal}\n"
        "text = '\\n'.join([\n"
        '    \'"""Patched by L3 sandbox — external glue execute."""\',\n'
        "    '',\n"
        "    f'LAST_RUN_ID = {run_id!r}',\n"
        "    '',\n"
        "    'def last_run_id() -> str:',\n"
        "    '    return LAST_RUN_ID',\n"
        "    '',\n"
        "    f'PREVIEW = {preview!r}',\n"
        "    f'PATCHED_AT = {datetime.now().isoformat()!r}',\n"
        "    ''])\n"
        f"p = Path({json.dumps(str(PROOF_REL).replace(chr(92), '/'))})\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text(text, encoding='utf-8')\n"
        "print('l3_patch_ok', run_id, p)\n"
    )

    sandbox: SandboxResult | None = None
    if prefer_docker:
        try:
            sandbox = _docker_mounted_sandbox(patch_code, repo_root)
        except Exception:
            sandbox = None
    if sandbox is None or sandbox.exit_code != 0:
        local_code = patch_code.replace(
            f"Path({json.dumps(str(PROOF_REL).replace(chr(92), '/'))})",
            f"Path({json.dumps(str(proof_path))})",
        )
        sandbox = run_local_python_sandbox(local_code, timeout_s=120)

    ok = sandbox.exit_code == 0 and proof_path.is_file() and run_id in proof_path.read_text(encoding="utf-8")
    result = {
        "layer": "L3",
        "adapter": sandbox.backend,
        "stdout": sandbox.stdout,
        "stderr": sandbox.stderr,
        "exit_code": sandbox.exit_code,
        "proof_path": str(proof_path),
        "test_path": str(test_path),
        "ok": ok,
        "real_repo_patch": ok,
    }
    append_jsonl(
        runtime_root / "evidence" / run_id / "execution.jsonl",
        {"layer": "L3", "activity": "repo_patch", "result": result, "timestamp": now_iso()},
    )
    return result