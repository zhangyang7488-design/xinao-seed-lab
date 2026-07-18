from __future__ import annotations

from pathlib import Path

import pytest

from xinao.foundation import f4_authority_source_pack as authority


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "localpkg").mkdir()
    (repo / "scripts" / "entry.py").write_text(
        "def load():\n    from localpkg import helper\n    return helper.VALUE\n",
        encoding="utf-8",
    )
    (repo / "localpkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "localpkg" / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repo


def _build(repo: Path, output_parent: Path) -> Path:
    return authority.build_authority_source_pack(
        repo_root=repo,
        output_parent=output_parent,
        entry_paths=["scripts/entry.py"],
    )


def test_function_local_import_is_in_authority_closure(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    sources, external = authority.discover_python_closure(
        repo,
        entry_paths=["scripts/entry.py"],
    )

    assert [path.relative_to(repo).as_posix() for path in sources] == [
        "localpkg/__init__.py",
        "localpkg/helper.py",
        "scripts/entry.py",
    ]
    assert external == []


def test_default_authority_closure_covers_current_evidence_code_sources() -> None:
    repo = Path(__file__).resolve().parents[4]

    sources, _ = authority.discover_python_closure(repo)
    relative_sources = {path.relative_to(repo).as_posix() for path in sources}

    assert {
        "scripts/verify_f4_live_canary_pack.py",
        "scripts/verify_f4_negative_companion_pack.py",
        "scripts/verify_f4_portfolio_source_canary_pack.py",
        "services/agent_runtime/grok_build_docker_worker.py",
        "xinao_discovery/src/xinao/foundation/f4_current_evidence_builder.py",
        "xinao_discovery/src/xinao/foundation/research_factory.py",
    } <= relative_sources


def test_built_authority_pack_has_exact_verified_inventory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest_path = _build(repo, tmp_path / "output")

    manifest = authority.verify_authority_source_pack(manifest_path)

    assert manifest["python_source_count"] == 3
    assert manifest["artifact_count"] == 3
    assert manifest["entry_paths"] == ["scripts/entry.py"]


@pytest.mark.parametrize("mutation", ["extra", "hash"])
def test_authority_pack_rejects_artifact_drift(tmp_path: Path, mutation: str) -> None:
    repo = _repo(tmp_path)
    manifest_path = _build(repo, tmp_path / "output")
    if mutation == "extra":
        (manifest_path.parent / "extra.txt").write_text("unexpected\n", encoding="utf-8")
    else:
        (manifest_path.parent / "scripts" / "entry.py").write_text(
            "VALUE = 2\n",
            encoding="utf-8",
        )

    with pytest.raises(authority.AuthorityPackError, match="inventory drifted"):
        authority.verify_authority_source_pack(manifest_path)


def test_existing_identity_is_not_reused_when_directory_drifted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "output"
    manifest_path = _build(repo, output)
    (manifest_path.parent / "extra.txt").write_text("unexpected\n", encoding="utf-8")

    with pytest.raises(authority.AuthorityPackError, match="inventory drifted"):
        _build(repo, output)


def test_source_drift_during_build_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    original = authority._stable_copy
    changed = False

    def drifting_copy(source: Path, destination: Path) -> dict[str, object]:
        nonlocal changed
        result = original(source, destination)
        if not changed and source.name == "entry.py":
            source.write_text(source.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
            changed = True
        return result

    monkeypatch.setattr(authority, "_stable_copy", drifting_copy)

    with pytest.raises(authority.AuthorityPackError, match="source changed after"):
        _build(repo, tmp_path / "output")


def test_authority_pack_rejects_reparse_objects_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    manifest_path = _build(repo, tmp_path / "output")
    original = authority._is_reparse

    def report_reparse(path: Path) -> bool:
        return path.name == "entry.py" or original(path)

    monkeypatch.setattr(authority, "_is_reparse", report_reparse)

    with pytest.raises(authority.AuthorityPackError, match="reparse point"):
        authority.verify_authority_source_pack(manifest_path)
