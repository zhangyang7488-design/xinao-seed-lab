from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    backend: str


def run_local_python_sandbox(code: str, *, timeout_s: int = 60) -> SandboxResult:
    """Cheap local sandbox: isolated subprocess, no cloud API."""
    with tempfile.TemporaryDirectory(prefix="xinao_sandbox_") as tmp:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=tmp,
            check=False,
        )
    return SandboxResult(
        stdout=(proc.stdout or "").strip(),
        stderr=(proc.stderr or "").strip(),
        exit_code=int(proc.returncode),
        backend="local_subprocess",
    )


def run_e2b_sandbox(code: str, *, timeout_s: int = 60) -> SandboxResult:
    try:
        from e2b_code_interpreter import Sandbox  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("e2b_code_interpreter not installed") from exc

    with Sandbox.create() as sandbox:
        execution = sandbox.run_code(code, timeout=timeout_s)
    text = getattr(execution, "text", None) or str(execution)
    return SandboxResult(stdout=text.strip(), stderr="", exit_code=0, backend="e2b")


def run_cheapest_sandbox(code: str, *, prefer_e2b: bool = False, timeout_s: int = 60) -> SandboxResult:
    import os

    if prefer_e2b and os.environ.get("E2B_API_KEY"):
        try:
            return run_e2b_sandbox(code, timeout_s=timeout_s)
        except Exception:
            pass
    return run_local_python_sandbox(code, timeout_s=timeout_s)