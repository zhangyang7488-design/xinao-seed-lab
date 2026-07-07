from pathlib import Path

from services.agent_runtime import ucp_tool_surface_resolver as resolver


def test_resolver_falls_back_to_clean_when_research_has_no_tools(
    tmp_path: Path, monkeypatch
) -> None:
    research = tmp_path / "research"
    clean = tmp_path / "clean"
    research.mkdir()
    clean.mkdir()
    python = clean / "tools" / "codex-sdk-python" / ".venv" / "Scripts" / "python.exe"
    ucp = clean / "tools" / "universal_control_plane_v0" / "universal_control_plane_v0.py"
    python.parent.mkdir(parents=True)
    ucp.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    ucp.write_text("print('ucp')\n", encoding="utf-8")

    monkeypatch.setattr(resolver, "DEFAULT_UCP_TOOLS_RUNTIME", clean)
    monkeypatch.delenv("XINAO_UCP_TOOLS_RUNTIME_ROOT", raising=False)

    payload = resolver.resolve_ucp_tool_surface(
        evidence_runtime_root=research, repo_root=tmp_path / "repo"
    )

    assert payload["ready"] is True
    assert payload["tool_root_source"] == "default_ucp_tools_runtime"
    assert payload["python_exists"] is True
    assert payload["ucp_exists"] is True
    assert payload["named_blocker"] == ""


def test_resolver_prefers_evidence_runtime_when_tools_present(tmp_path: Path) -> None:
    research = tmp_path / "research"
    research.mkdir()
    python = research / "tools" / "codex-sdk-python" / ".venv" / "Scripts" / "python.exe"
    ucp = research / "tools" / "universal_control_plane_v0" / "universal_control_plane_v0.py"
    python.parent.mkdir(parents=True)
    ucp.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    ucp.write_text("print('ucp')\n", encoding="utf-8")

    payload = resolver.resolve_ucp_tool_surface(evidence_runtime_root=research)

    assert payload["ready"] is True
    assert payload["tool_root_source"] == "evidence_runtime_root"


def test_resolver_blocks_when_no_candidate_has_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resolver, "DEFAULT_UCP_TOOLS_RUNTIME", tmp_path / "missing")
    monkeypatch.delenv("XINAO_UCP_TOOLS_RUNTIME_ROOT", raising=False)
    payload = resolver.resolve_ucp_tool_surface(evidence_runtime_root=tmp_path / "research")
    assert payload["ready"] is False
    assert payload["named_blocker"] == "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING"
