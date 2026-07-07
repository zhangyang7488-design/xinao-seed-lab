from __future__ import annotations

import json
from pathlib import Path

from services.agent_runtime.thin_bootstrap_runner import run_thin_bootstrap


def test_run_thin_bootstrap_smoke(tmp_path: Path, monkeypatch) -> None:
    material = tmp_path / "input.md"
    material.write_text("# bootstrap\nintent: smoke test\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "bootstrap@test.local"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "bootstrap"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    payload = run_thin_bootstrap(material, runtime_root=runtime, repo_root=repo)
    assert payload["sandbox"]["backend"] == "local_subprocess"
    assert payload["git"]["commit_hash"]
    evidence = runtime / "readback" / f"thin_bootstrap_{payload['run_id']}.json"
    assert evidence.is_file()
    manifest = runtime / "closure" / payload["run_id"] / "closure_manifest.json"
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "bootstrap_smoke_passed"