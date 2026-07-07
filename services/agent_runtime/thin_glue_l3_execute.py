"""L3 真执行 — 沙箱内改 S 仓文件（Docker 挂载或本地 subprocess）."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_bootstrap_sandbox import (
    SandboxResult,
    run_local_python_sandbox,
)
from services.agent_runtime.thin_evidence_writer import append_jsonl, now_iso

PROOF_REL = Path("services/agent_runtime/thin_glue_work_proof.py")
TEST_REL = Path("tests/test_thin_glue_work_proof.py")

TEST_TEMPLATE = '''from services.agent_runtime.thin_glue_work_proof import last_run_id


def test_thin_glue_work_proof_has_run_id() -> None:
    assert last_run_id()
'''

CLOSURE_PROOF_REL = Path("services/agent_runtime/closure_test_proof.py")
CLOSURE_TEST_REL = Path("tests/test_closure_test_proof.py")

CLOSURE_TEST_TEMPLATE = '''from services.agent_runtime.closure_test_proof import hello


def test_closure_test_proof_hello() -> None:
    assert hello() == "closure_ok"
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


def _posix_rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def run_l3_sandbox_repo_patch(
    *,
    repo_root: Path,
    runtime_root: Path,
    run_id: str,
    proof_rel: Path,
    patch_code: str,
    verify_substrings: list[str],
    test_rel: Path | None = None,
    test_template: str | None = None,
    prefer_docker: bool = True,
    activity: str = "repo_patch",
) -> dict[str, Any]:
    proof_path = repo_root / proof_rel
    test_path = repo_root / test_rel if test_rel else None
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    if test_path is not None:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        if test_template and not test_path.is_file():
            test_path.write_text(test_template, encoding="utf-8")

    rel_posix = json.dumps(_posix_rel(proof_rel))
    sandbox: SandboxResult | None = None
    if prefer_docker:
        try:
            sandbox = _docker_mounted_sandbox(patch_code, repo_root)
        except Exception:
            sandbox = None
    if sandbox is None or sandbox.exit_code != 0:
        local_code = patch_code.replace(f"Path({rel_posix})", f"Path({json.dumps(str(proof_path))})")
        if test_path is not None and test_rel is not None:
            local_code = local_code.replace(
                f"Path({json.dumps(_posix_rel(test_rel))})",
                f"Path({json.dumps(str(test_path))})",
            )
        sandbox = run_local_python_sandbox(local_code, timeout_s=120)

    proof_text = proof_path.read_text(encoding="utf-8") if proof_path.is_file() else ""
    ok = sandbox.exit_code == 0 and proof_path.is_file() and all(s in proof_text for s in verify_substrings)
    result = {
        "layer": "L3",
        "adapter": sandbox.backend,
        "stdout": sandbox.stdout,
        "stderr": sandbox.stderr,
        "exit_code": sandbox.exit_code,
        "proof_path": str(proof_path),
        "test_path": str(test_path) if test_path else None,
        "ok": ok,
        "real_repo_patch": ok,
    }
    append_jsonl(
        runtime_root / "evidence" / run_id / "execution.jsonl",
        {"layer": "L3", "activity": activity, "result": result, "timestamp": now_iso()},
    )
    return result


def _thin_glue_patch_code(run_id: str, task_preview: str) -> str:
    preview_literal = json.dumps(task_preview[:200], ensure_ascii=False)
    rel = json.dumps(_posix_rel(PROOF_REL))
    return (
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
        f"p = Path({rel})\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text(text, encoding='utf-8')\n"
        "print('l3_patch_ok', run_id, p)\n"
    )


def run_l3_repo_patch(
    *,
    repo_root: Path,
    runtime_root: Path,
    run_id: str,
    task_preview: str = "",
    prefer_docker: bool = True,
) -> dict[str, Any]:
    return run_l3_sandbox_repo_patch(
        repo_root=repo_root,
        runtime_root=runtime_root,
        run_id=run_id,
        proof_rel=PROOF_REL,
        patch_code=_thin_glue_patch_code(run_id, task_preview),
        verify_substrings=[run_id],
        test_rel=TEST_REL,
        test_template=TEST_TEMPLATE,
        prefer_docker=prefer_docker,
    )


def _closure_patch_code(run_id: str, task_preview: str) -> str:
    preview_literal = json.dumps(task_preview[:200], ensure_ascii=False)
    proof_rel = json.dumps(_posix_rel(CLOSURE_PROOF_REL))
    test_rel = json.dumps(_posix_rel(CLOSURE_TEST_REL))
    return (
        "from pathlib import Path\n"
        f"run_id = {json.dumps(run_id)}\n"
        f"preview = {preview_literal}\n"
        "proof = '\\n'.join([\n"
        '    \'"""Auto-generated by closure_test_v1 L3 sandbox."""\',\n'
        "    '',\n"
        "    f'RUN_ID = {run_id!r}',\n"
        "    '',\n"
        "    'def hello() -> str:',\n"
        '    \'    return "closure_ok"\',\n'
        "    ''])\n"
        "test = '\\n'.join([\n"
        "    'from services.agent_runtime.closure_test_proof import hello',\n"
        "    '',\n"
        "    'def test_closure_test_proof_hello() -> None:',\n"
        '    \'    assert hello() == "closure_ok"\',\n'
        "    ''])\n"
        f"pp = Path({proof_rel})\n"
        f"tp = Path({test_rel})\n"
        "pp.parent.mkdir(parents=True, exist_ok=True)\n"
        "tp.parent.mkdir(parents=True, exist_ok=True)\n"
        "pp.write_text(proof, encoding='utf-8')\n"
        "tp.write_text(test, encoding='utf-8')\n"
        "print('closure_l3_patch_ok', run_id, pp, tp)\n"
    )


def run_l3_closure_repo_patch(
    *,
    repo_root: Path,
    runtime_root: Path,
    run_id: str,
    task_preview: str = "",
    prefer_docker: bool = True,
) -> dict[str, Any]:
    return run_l3_sandbox_repo_patch(
        repo_root=repo_root,
        runtime_root=runtime_root,
        run_id=run_id,
        proof_rel=CLOSURE_PROOF_REL,
        patch_code=_closure_patch_code(run_id, task_preview),
        verify_substrings=[run_id, "closure_ok"],
        test_rel=CLOSURE_TEST_REL,
        prefer_docker=prefer_docker,
        activity="closure_repo_patch",
    )