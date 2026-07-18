from __future__ import annotations

import subprocess
from pathlib import Path

from xinao.foundation.assertion_verifier_registry import (
    canonical_f4_workflow_python_executable,
)


def test_f4_verifiers_use_the_canonical_workflow_runtime() -> None:
    python = canonical_f4_workflow_python_executable()

    assert (
        python
        == (Path(__file__).resolve().parents[4] / ".venv" / "Scripts" / "python.exe").resolve()
    )
    probe = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import mlflow, temporalio; print('F4_RUNTIME_READY')",
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=30,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "F4_RUNTIME_READY"
