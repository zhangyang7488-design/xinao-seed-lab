from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from services.agent_runtime.integrated_bus_graph import finalize_node


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_finalize_keeps_dirty_worktree_unchanged_and_writes_proof_to_runtime(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    runtime = tmp_path / "runtime"
    repo.mkdir()
    runtime.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "integrated-bus-test@local")
    _git(repo, "config", "user.name", "integrated-bus-test")
    tracked = repo / "tracked.txt"
    tracked.write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "baseline")

    tracked.write_text("user edit\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("user untracked\n", encoding="utf-8")
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    result = asyncio.run(
        finalize_node(
            {
                "repo_root": str(repo),
                "runtime_root": str(runtime),
                "workflow_id": "git-isolation-canary",
                "validate_ok": True,
            }
        )
    )

    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert not (repo / "integrated_bus_proof.txt").exists()

    proof = Path(result["proof_path"])
    assert proof.is_file()
    assert runtime in proof.parents
    assert result["commit_hash"] == before_head
    assert result["git_commit_adapter"] == "gitpython_readonly"
    assert result["git_snapshot_adapter"] == "gitpython_readonly"
    assert result["gitpython_invoke_ok"] is True

    evidence = json.loads(Path(result["gitpython_evidence_ref"]).read_text(encoding="utf-8"))
    assert evidence["invoke_ok"] is True
    assert evidence["created_new"] is False
    assert evidence["worktree_mutated"] is False
    assert evidence["worktree_dirty"] is True
