from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from services.agent_runtime import cheap_worker_patch_executor


def test_cheap_worker_patch_executor_applies_allowlisted_diff_and_verifies(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required for patch executor apply test")
    repo = tmp_path / "repo"
    runtime = tmp_path / "runtime"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)

    diff_text = """diff --git a/tests/generated_patch_exec.py b/tests/generated_patch_exec.py
new file mode 100644
index 0000000..6a8b55d
--- /dev/null
+++ b/tests/generated_patch_exec.py
@@ -0,0 +1,2 @@
+VALUE = "litellm"
+assert VALUE == "litellm"
"""

    result = cheap_worker_patch_executor.execute_patch_artifact(
        runtime_root=runtime,
        repo_root=repo,
        task_id="unit",
        worker_task_id="worker",
        diff_text=diff_text,
        verification=["python -m py_compile tests/generated_patch_exec.py"],
    )

    assert result["status"] == "applied_verified"
    assert result["repo_mutation_performed"] is True
    assert result["named_blocker"] == ""
    assert (repo / "tests" / "generated_patch_exec.py").is_file()
    assert Path(result["record_path"]).is_file()


def test_cheap_worker_patch_executor_blocks_non_allowlisted_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runtime = tmp_path / "runtime"
    repo.mkdir()
    diff_text = """diff --git a/private_config/secret.txt b/private_config/secret.txt
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/private_config/secret.txt
@@ -0,0 +1 @@
+nope
"""

    result = cheap_worker_patch_executor.execute_patch_artifact(
        runtime_root=runtime,
        repo_root=repo,
        task_id="unit",
        worker_task_id="worker",
        diff_text=diff_text,
        verification=[f"{sys.executable} -m py_compile private_config/secret.txt"],
    )

    assert result["status"] == "blocked"
    assert result["named_blocker"] == "BLOCKER_PATH_VIOLATION"
