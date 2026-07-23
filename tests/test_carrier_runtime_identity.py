from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_host_defaults_follow_loaded_source_carrier_not_foreign_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XINAO_CODEX_S_REPO_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    from services.agent_runtime import integrated_bus_bus_nodes, thin_glue_stack

    thin_glue_stack = importlib.reload(thin_glue_stack)
    integrated_bus_bus_nodes = importlib.reload(integrated_bus_bus_nodes)

    assert thin_glue_stack.DEFAULT_REPO.resolve() == REPO_ROOT
    assert integrated_bus_bus_nodes.resolve_repo_root(None).resolve() == REPO_ROOT
    assert (thin_glue_stack.DEFAULT_REPO / "materials").is_relative_to(REPO_ROOT)


def test_explicit_existing_repo_override_wins_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "configured"
    explicit = tmp_path / "explicit"
    configured.mkdir()
    explicit.mkdir()
    monkeypatch.setenv("XINAO_CODEX_S_REPO_ROOT", str(configured))

    from services.agent_runtime.carrier_identity import resolve_code_carrier_root

    assert resolve_code_carrier_root(explicit) == explicit.resolve()


@pytest.mark.parametrize(
    "module_name",
    [
        "services.agent_runtime.closure_test_activities",
        "services.agent_runtime.task_entry_claim",
        "services.agent_runtime.temporal_codex_task_workflow",
    ],
)
def test_remaining_host_entrypoints_share_the_loaded_source_carrier(
    module_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XINAO_CODEX_S_REPO_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    module = importlib.import_module(module_name)
    module = importlib.reload(module)

    assert module.DEFAULT_REPO.resolve() == REPO_ROOT
