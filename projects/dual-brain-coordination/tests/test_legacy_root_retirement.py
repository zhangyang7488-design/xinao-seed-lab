from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = "E:" + "\\XINAO_RESEARCH_WORKSPACES\\dual-brain-coordination"
TEXT_SUFFIXES = {".md", ".py", ".ps1", ".json", ".toml", ".txt"}


def test_active_project_surfaces_do_not_reference_retired_independent_root() -> None:
    roots = [
        ROOT / "provisioning",
        ROOT / "adapters",
        ROOT / "scripts",
        ROOT / "src",
        ROOT / "docs",
    ]
    files = [ROOT / "README.md"]
    for scan_root in roots:
        files.extend(
            path for path in scan_root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
        )
    offenders = [
        str(path.relative_to(ROOT))
        for path in files
        if LEGACY_ROOT.lower() in path.read_text(encoding="utf-8", errors="ignore").lower()
    ]
    assert offenders == []


def test_managed_mcp_smoke_can_target_an_isolated_runtime_root() -> None:
    source = (ROOT / "scripts" / "mcp_smoke.py").read_text(encoding="utf-8")
    assert '"--runtime-root"' in source
    assert 'managed_args.extend(["-RuntimeRoot", str(runtime_root)])' in source
