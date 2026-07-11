from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass


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


def run_docker_python_sandbox(
    code: str, *, image: str = "python:3.12-slim", timeout_s: int = 60
) -> SandboxResult:
    import subprocess

    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            image,
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
        backend=f"docker:{image}",
    )


def _docker_daemon_ready() -> bool:
    import subprocess

    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, check=False)
        return proc.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def run_cheapest_sandbox(
    code: str,
    *,
    prefer_e2b: bool = False,
    prefer_docker: bool = False,
    docker_image: str = "python:3.12-slim",
    timeout_s: int = 60,
) -> SandboxResult:
    import os

    if prefer_e2b and os.environ.get("E2B_API_KEY"):
        try:
            return run_e2b_sandbox(code, timeout_s=timeout_s)
        except Exception:
            pass
    if prefer_docker and _docker_daemon_ready():
        try:
            result = run_docker_python_sandbox(code, image=docker_image, timeout_s=timeout_s)
            if result.exit_code == 0:
                return result
        except Exception:
            pass
    elif _docker_daemon_ready() and not prefer_e2b:
        try:
            result = run_docker_python_sandbox(code, image=docker_image, timeout_s=timeout_s)
            if result.exit_code == 0:
                return result
        except Exception:
            pass
    return run_local_python_sandbox(code, timeout_s=timeout_s)
