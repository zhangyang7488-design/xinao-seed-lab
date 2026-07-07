from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.thin_glue
def test_closure_test_pipeline_local(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_PROVIDER", "1")
    from services.agent_runtime.closure_test_activities import run_closure_test_pipeline

    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    (materials / "closure_test_input.md").write_text(
        "# closure_test_v1\nintent: closure_test_proof hello closure_ok\n",
        encoding="utf-8",
    )
    (repo / "services" / "agent_runtime").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    payload = run_closure_test_pipeline(
        materials / "closure_test_input.md",
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        prefer_docker=False,
    )
    assert payload["validation"]["passed"] is True
    assert (repo / "services" / "agent_runtime" / "closure_test_proof.py").is_file()
    manifest = payload["closure_manifest"]
    assert manifest["pytest_passed"] is True
    assert manifest["sunset_modules_not_invoked"]


@pytest.mark.thin_glue
def test_closure_import_graph_no_sunset_modules() -> None:
    import ast

    activities = REPO / "services" / "agent_runtime" / "closure_test_activities.py"
    tree = ast.parse(activities.read_text(encoding="utf-8"))
    imports = {
        node.names[0].name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    forbidden = {"codex_333", "modular_dynamic_worker_pool", "root_intent_loop_driver"}
    for name in imports:
        for bad in forbidden:
            assert bad not in (name or "")