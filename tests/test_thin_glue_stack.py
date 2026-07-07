from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.thin_glue
def test_thin_glue_intake_scans_materials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_INTAKE", "1")
    from services.agent_runtime.thin_glue_intake import build_thin_glue_intake

    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "sample.md").write_text("# hello thin glue\n", encoding="utf-8")

    payload = build_thin_glue_intake(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path,
        materials_dir=materials,
        write=True,
    )
    assert payload["validation"]["passed"] is True
    assert payload["source_entry_count"] >= 1
    assert payload["thin_glue"] is True
    assert payload["replaces"] == "current_task_source_intake"


@pytest.mark.thin_glue
def test_thin_glue_provider_scheduler_writes_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_PROVIDER", "1")
    from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4

    payload = phase4.run_provider_scheduler(
        runtime_root=tmp_path / "runtime",
        repo_root=REPO_ROOT,
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )
    assert payload["thin_glue"] is True
    assert payload["replaces"] == "codex_native_provider_scheduler_phase4"
    latest = tmp_path / "runtime" / "state" / "thin_glue_provider" / "latest.json"
    assert latest.is_file()
    saved = json.loads(latest.read_text(encoding="utf-8"))
    assert saved["task_id"] == "thin_glue_provider_scheduler"


@pytest.mark.thin_glue
def test_thin_glue_loop_glue_and_closure_together(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_INTAKE", "1")
    monkeypatch.setenv("XINAO_THIN_GLUE_PROVIDER", "1")
    from services.agent_runtime.thin_glue_loop import run_thin_glue_loop

    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    (materials / "thin_bootstrap_input.md").write_text("# loop smoke\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# loop smoke marker\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    payload = run_thin_glue_loop(
        materials / "thin_bootstrap_input.md",
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        prefer_docker=False,
        write=True,
    )
    assert payload["glue_and_closure_together"] is True
    assert payload["layers"]["L0_intake_pool"]["source_entry_count"] >= 1
    l4 = payload["layers"]["L4_search"]
    assert l4["thin_glue"] is True
    assert l4["local_hit_count"] >= 1
    assert payload["layers"]["L9_provider_gateway"]["thin_glue"] is True
    assert payload["layers"]["L8_commit"]["created_new"] is True
    assert payload["validation"]["checks"]["L4_local_rg_search"] is True
    assert list((tmp_path / "runtime" / "readback" / "zh").glob("thin_glue_loop_*.md"))


@pytest.mark.thin_glue
def test_thin_glue_l4_search_local_rg(tmp_path) -> None:
    from services.agent_runtime.thin_glue_l4_search import run_thin_glue_search

    repo = tmp_path / "repo"
    (repo / "services").mkdir(parents=True)
    (repo / "services" / "needle.txt").write_text("thin_glue_l4_search marker\n", encoding="utf-8")

    payload = run_thin_glue_search(
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        run_id="test_l4",
        local_query="thin_glue_l4",
        external_query="searxng",
        write=True,
    )
    assert payload["validation"]["passed"] is True
    assert payload["local_hit_count"] >= 1
    latest = tmp_path / "runtime" / "state" / "thin_glue_search" / "latest.json"
    assert latest.is_file()


def test_thin_glue_mainline_bridge_reads_latest_loop(tmp_path) -> None:
    from services.agent_runtime.thin_glue_mainline_bridge import attach_thin_glue_bridge_evidence

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_20260708_test.json").write_text(
        '{"validation": {"passed": true}}',
        encoding="utf-8",
    )
    bridge = attach_thin_glue_bridge_evidence(runtime)
    assert bridge["latest_thin_glue_loop_passed"] is True
    assert (runtime / "state" / "thin_glue_mainline_bridge" / "latest.json").is_file()