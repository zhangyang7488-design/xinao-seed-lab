from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE_ROOTS = (
    REPO_ROOT / "services",
    REPO_ROOT / "scripts",
    REPO_ROOT / ".github",
)
TEXT_SUFFIXES = {".py", ".ps1", ".js", ".json", ".toml", ".yaml", ".yml"}


def _executable_text() -> str:
    chunks: list[str] = []
    for root in EXECUTABLE_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_retired_control_stack_directories_are_absent() -> None:
    for relative in (
        "apps",
        "contracts",
        "docker",
        "materials",
        "policies",
        "src",
        "services/agent_runtime",
        "services/codex_activator",
        "scripts/hardmode",
    ):
        assert not (REPO_ROOT / relative).exists(), relative


def test_retained_executable_sources_cannot_commit_the_worktree() -> None:
    text = _executable_text().lower()
    assert "git add -a" not in text
    assert "git commit" not in text


def test_retained_executable_sources_have_no_dead_desktop_or_runtime_entry() -> None:
    text = _executable_text().lower()
    for forbidden in (
        r"desktop\新系统".lower(),
        r"desktop\codex_admin_isolated".lower(),
        r"desktop\grok_admin_isolated".lower(),
        "rootintentloop",
        "xinao_clean_runtime",
    ):
        assert forbidden not in text, forbidden


def test_memory_server_is_isolated_from_retired_or_hosted_backends() -> None:
    text = (REPO_ROOT / "services/mcp/xinao_memory_mcp_server.py").read_text(encoding="utf-8")
    assert "local_mem0_store" in text
    for forbidden in (
        "services.agent_runtime",
        "materials/",
        "MemoryClient",
        "MEM0_API_KEY",
        "chromadb",
    ):
        assert forbidden not in text


def test_project_agreement_keeps_capabilities_available_but_activation_adaptive() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "availability as the hard default and activation as adaptive" in text
    assert "Do not impose a fixed score, lane count, or mandatory sequence" in text
    assert "decode “收口” as bounded review" in text
