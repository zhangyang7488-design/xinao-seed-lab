from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "scripts" / "Update-CodexContextCatalog.ps1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pwsh() -> str:
    discovered = shutil.which("pwsh")
    if not discovered:
        pytest.skip("pwsh is required")
    return discovered


def _fixture(tmp_path: Path, *, missing_required: bool = False) -> tuple[Path, Path, Path]:
    island = tmp_path / "island"
    contracts = island / "contracts"
    contracts.mkdir(parents=True)
    first = tmp_path / "first.txt"
    first.write_text("first\n", encoding="utf-8")
    second = tmp_path / "missing.txt" if missing_required else tmp_path / "second.txt"
    if not missing_required:
        second.write_text("second\n", encoding="utf-8")
    source_map = contracts / "mainline_maintenance_map.v1.json"
    source_map.write_text(
        json.dumps(
            {
                "schema_version": "xinao.machine_context_source_map.v2",
                "sentinel": "SENTINEL:XINAO_MACHINE_CONTEXT_SOURCE_MAP_V2",
                "authority": False,
                "sources": [
                    {
                        "id": "first",
                        "path": str(first),
                        "role": "fixture_first",
                        "required": True,
                        "load_policy": "startup",
                    },
                    {
                        "id": "second",
                        "path": str(second),
                        "role": "fixture_second",
                        "required": True,
                        "load_policy": "on_demand",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return island, source_map, first


def _run(island: Path, source_map: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATER),
            "-IslandRoot",
            str(island),
            "-MaintenanceMapPath",
            str(source_map),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )


def test_catalog_refreshes_hash_index_without_mutating_sources(tmp_path: Path) -> None:
    island, source_map, first = _fixture(tmp_path)
    before = first.read_bytes()

    completed = _run(island, source_map)

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["status"] == "REFRESHED"
    assert receipt["authority_text_mutated"] is False
    assert receipt["legacy_projection_generated"] is False
    assert first.read_bytes() == before
    catalog = json.loads((island / "context_catalog.json").read_text(encoding="utf-8"))
    core = json.loads((island / "core_index.json").read_text(encoding="utf-8"))
    refreshed_map = json.loads(source_map.read_text(encoding="utf-8"))
    assert catalog["schema_version"] == "xinao.codex_context_catalog.v4"
    assert catalog["legacy_platform_in_active_choice_set"] is False
    assert (
        catalog["architecture"]["desktop_mainline_role"]
        == "user_visible_control_surface_thin_auto_load_only"
    )
    assert (
        catalog["architecture"]["engineering_adjudication"]
        == "current_intent_plus_live_facts_compiled_by_non_authority_skills"
    )
    assert {item["id"] for item in catalog["sources"]} == {"first", "second"}
    assert next(item for item in catalog["sources"] if item["id"] == "first")["sha256"] == _sha256(
        first
    )
    assert core["schema_version"] == "xinao.codex_core_index.v4"
    assert refreshed_map["generated_state"]["source_count"] == 2


def test_missing_required_source_fails_before_any_output_write(tmp_path: Path) -> None:
    island, source_map, _first = _fixture(tmp_path, missing_required=True)
    before = source_map.read_bytes()

    completed = _run(island, source_map)

    assert completed.returncode != 0
    assert "REQUIRED_SOURCE_MISSING:second" in (completed.stdout + completed.stderr)
    assert source_map.read_bytes() == before
    assert not (island / "context_catalog.json").exists()
    assert not (island / "core_index.json").exists()


def test_updater_has_no_legacy_projection_or_foundation_parameters() -> None:
    text = UPDATER.read_text(encoding="utf-8")
    for forbidden in (
        "FoundationImplementationProjectionJson",
        "ExpectedSoftwareFoundationSha256",
        "ExpectedSoftwareFoundationVersion",
        "mainline_domain_research_current",
        "06_当前研究接续",
    ):
        assert forbidden not in text
    assert "authority_text_mutated = $false" in text
    assert "legacy_projection_generated = $false" in text
