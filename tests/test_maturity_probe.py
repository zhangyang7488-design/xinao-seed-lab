from __future__ import annotations

import ast
import importlib.util
import os
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO / "scripts" / "probe_xinao_maturity.py"
LAUNCHER_PATH = Path(
    os.environ.get(
        "XINAO_MATURITY_PROBE_LAUNCHER",
        r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\scripts"
        r"\Invoke-XinaoMaturityProbe.ps1",
    )
)
EXPECTED_TOOLS = {
    "grep",
    "list_dir",
    "read_file",
    "search_tool",
    "use_tool",
    "web_fetch",
    "web_search",
}


def _probe_module():
    spec = importlib.util.spec_from_file_location("xinao_maturity_probe_test", PROBE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_uses_exact_fixed_grok_surface(tmp_path: Path, monkeypatch) -> None:
    dual_root = tmp_path / "dual-brain-coordination"
    grok_parallel = dual_root / "src" / "xinao_coordination" / "temporal" / "grok_parallel.py"
    grok_parallel.parent.mkdir(parents=True)
    grok_parallel.write_text(
        "BACKGROUND_ALLOWED_TOOLS = frozenset(" + repr(EXPECTED_TOOLS) + ")\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XINAO_DUAL_ROOT", str(dual_root))
    probe = _probe_module()
    assert probe.GROK_PARALLEL == grok_parallel
    assert probe.EXPECTED_TOOLS == EXPECTED_TOOLS
    assert set(probe._background_allowed_tools(probe.GROK_PARALLEL)) == EXPECTED_TOOLS


def test_poller_freshness_uses_real_access_timestamp() -> None:
    probe = _probe_module()
    now = time.time()
    summary = probe._poller_summary(
        {
            "pollers": [
                {
                    "last_access_time": {"seconds": int(now - 5), "nanos": 0},
                    "identity": "worker",
                    "deployment_options": {
                        "deployment_name": "deployment",
                        "build_id": "build",
                    },
                }
            ]
        },
        now_epoch=now,
    )
    assert summary["poller_count"] == 1
    assert summary["all_fresh_within_60_seconds"] is True
    assert 4 <= summary["pollers"][0]["age_seconds"] <= 6


def test_probe_source_has_no_runtime_mutation_calls() -> None:
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "start_workflow" not in called_attributes
    assert "remove" not in called_attributes
    assert "kill" not in called_attributes
    assert "connect" not in called_attributes


def test_island_launcher_is_one_shot_without_persistence() -> None:
    if not LAUNCHER_PATH.is_file():
        pytest.skip("live situation-island launcher is not mounted on this runner")
    text = LAUNCHER_PATH.read_text(encoding="utf-8")
    assert "probe_xinao_maturity.py" in text
    assert "Start-Process" not in text
    assert "Register-ScheduledTask" not in text
    assert "while (" not in text


def test_worker_image_uses_pinned_official_uv_and_cache_layer() -> None:
    text = (REPO / "docker/houtai-gongren/Dockerfile").read_text(encoding="utf-8")
    assert "ghcr.io/astral-sh/uv@sha256:0f36cb9361a334" in text
    assert "--mount=type=cache,target=/root/.cache/uv" in text
    assert "pip install --no-cache-dir uv" not in text
