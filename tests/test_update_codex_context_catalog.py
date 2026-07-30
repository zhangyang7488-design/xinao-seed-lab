"""Focused fixture tests for the catalog/selector software_foundation version one-home."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# Checkout alias is same-byte with the package-canonical resource (enforced in
# test_tool_glue_operational_projection). Fixture tests may use either path.
UPDATER = (
    REPO_ROOT
    / "xinao_discovery"
    / "src"
    / "xinao"
    / "tool_glue"
    / "resources"
    / "Update-CodexContextCatalog.ps1"
)
MODULE_SCHEMA_SRC = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\contracts"
    r"\module_operational_note.v1.schema.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _require_pwsh() -> str:
    discovered = shutil.which("pwsh")
    if not discovered:
        pytest.skip("pwsh is required for catalog updater fixture tests")
    return discovered


def _materialize_fixture_island(root: Path, *, glue_version: str) -> dict[str, Path]:
    island = root / "island"
    contracts = island / "contracts"
    notes = island / "state" / "module_operational_notes"
    cards = notes / "cards"
    cards.mkdir(parents=True, exist_ok=True)
    contracts.mkdir(parents=True, exist_ok=True)

    if MODULE_SCHEMA_SRC.is_file():
        shutil.copyfile(MODULE_SCHEMA_SRC, contracts / "module_operational_note.v1.schema.json")
    else:
        _write_json(
            contracts / "module_operational_note.v1.schema.json",
            {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
        )
    _write_json(
        notes / "index.v1.json",
        {
            "schema_version": "xinao.module_operational_notes_index.v1",
            "sentinel": "SENTINEL:XINAO_MODULE_OPERATIONAL_NOTES_INDEX_V1",
            "generated_at": "2026-01-01T00:00:00Z",
            "cards_root": str(cards),
            "card_count": 0,
            "cards_tree_sha256": "0" * 64,
            "cards": [],
            "authority": False,
            "completion_claim_allowed": False,
        },
    )

    science_spec = _write(root / "science_spec.txt", "science-spec-bytes\n")
    legacy_domain = _write(root / "legacy_domain.txt", "legacy-domain-bytes\n")
    admission = _write(root / "admission.txt", "admission-bytes\n")
    background = _write(root / "background.txt", "background-bytes\n")
    stable_entry = _write(root / "stable_entry.txt", "stable router text\n")
    tool_glue = _write(
        root / "tool_glue.txt",
        "软件工具胶水宪法｜当前有效\n"
        f"版本：{glue_version}\n"
        "SENTINEL:XINAO_SOFTWARE_TOOL_GLUE_CONSTITUTION_V2\n",
    )
    science_projection = _write_json(
        root / "active_parent.current.json",
        {
            "schema_version": "xinao.science_active_parent_projection.v1",
            "sentinel": "SENTINEL:XINAO_SCIENCE_ACTIVE_PARENT_PROJECTION_V1",
            "authority": False,
            "completion_claim_allowed": False,
            "generated_at": "2026-01-01T00:00:00Z",
            "active_parent": {
                "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
                "status": "CURRENT_ACTIVE_PARENT",
                "path": str(science_spec),
                "sha256": "0" * 64,
            },
            "stable_entry": {"path": str(stable_entry), "sha256": "0" * 64},
            "software_foundation": {
                "path": str(tool_glue),
                "sha256": "0" * 64,
                "relationship": "REUSABLE_INSTRUMENT_FOUNDATION_NOT_PARENT_GATE",
            },
            "background_contract": {"path": str(background), "sha256": "0" * 64},
            "legacy_parent": {
                "path": str(legacy_domain),
                "sha256": "0" * 64,
                "status": "SUPERSEDED_AS_ACTIVE_PARENT",
                "authority_scope": "LEGACY_PARENT_G0_G8",
            },
            "legacy_admission_contract": {
                "path": str(admission),
                "sha256": "0" * 64,
                "authority_scope": "LEGACY_PARENT_G0_G8",
            },
        },
    )
    blueprint_dir = root / "blueprint_home"
    blueprint = _write_json(
        blueprint_dir / "blueprint.json",
        {
            "schema_version": "xinao.current-domain-research-blueprint.v1",
            "authority": {
                "human_spec": str(legacy_domain),
                "human_spec_sha256": "0" * 64,
                "formal_admission_contract": str(admission),
                "formal_admission_contract_sha256": "0" * 64,
                "projection_is_not_authority": True,
            },
            "gates": {"normative_contract_sha256": "0" * 64},
        },
    )
    _write_json(
        blueprint_dir / "source_manifest.json",
        {
            "schema_version": "xinao.text_governance.source_manifest.current.v1",
            "superseded_auxiliary_contract": {
                "replacement_path": str(admission),
                "replacement_sha256": "0" * 64,
            },
        },
    )
    archive = _write_json(
        root / "archive_relocation_manifest.json",
        {
            "schema_version": "xinao.archive-relocation-manifest.v1",
            "status": "ARCHIVE_RELOCATION_VERIFIED",
            "current_publication": {
                "stable_spec_path": str(science_spec),
                "stable_spec_sha256": _sha256(science_spec),
                "versioned_snapshot_path": str(science_spec),
                "versioned_snapshot_sha256": _sha256(science_spec),
                "background_contract_path": str(background),
                "background_contract_sha256": _sha256(background),
            },
        },
    )
    source_ids = {
        "current_science_spec": science_spec,
        "legacy_domain_spec": legacy_domain,
        "legacy_foundation_admission_contract": admission,
        "background_model_contract": background,
        "current_science_projection": science_projection,
        "legacy_machine_projection": blueprint,
        "archive_relocation_manifest": archive,
        "tool_glue_constitution": tool_glue,
        "stable_mainline_entry": stable_entry,
    }
    maintenance_map = _write_json(
        island / "contracts" / "mainline_maintenance_map.v1.json",
        {
            "schema_version": "xinao.mainline_maintenance_map.v1",
            "sentinel": "SENTINEL:XINAO_MAINLINE_MAINTENANCE_MAP_V1",
            "authority": False,
            "sources": [
                {
                    "id": source_id,
                    "path": str(path),
                    "required": True,
                    "hash_policy": "sha256",
                }
                for source_id, path in source_ids.items()
            ],
            "collections": [],
            "generated_state": {
                "updated_at": "2026-01-01T00:00:00Z",
                "source_count": len(source_ids),
                "collection_count": 0,
            },
        },
    )
    catalog = _write_json(
        island / "context_catalog.json",
        {
            "schema_version": "xinao.codex_context_catalog.v3",
            "sentinel": "SENTINEL:XINAO_CODEX_CONTEXT_CATALOG_V3",
            "authority": False,
            "completion_claim_allowed": False,
            "updated_at": "2026-01-01T00:00:00Z",
            "router_source": {"path": str(stable_entry), "sha256": "0" * 64},
            "entries": [
                {
                    "module_id": "stable-router",
                    "source_id": "stable_mainline_entry",
                    "content_type": "stable_mainline_router",
                    "source_path": str(stable_entry),
                    "keywords": ["router"],
                    "read_policy": "read_for_routing",
                },
                {
                    "module_id": "maintenance-map",
                    "source_id": "maintenance_map_self",
                    "content_type": "maintenance_map",
                    "source_path": str(island / "contracts" / "mainline_maintenance_map.v1.json"),
                    "keywords": ["maintenance"],
                    "read_policy": "read_for_maintenance",
                },
            ],
        },
    )
    return {
        "island": island,
        "catalog": catalog,
        "maintenance_map": maintenance_map,
        "science_projection": science_projection,
        "tool_glue": tool_glue,
    }


def _run_updater(
    *,
    island: Path,
    catalog: Path,
    maintenance_map: Path,
    expected_sha256: str = "",
    expected_version: str = "",
) -> dict[str, object]:
    pwsh = _require_pwsh()
    command = [
        pwsh,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(UPDATER),
        "-IslandRoot",
        str(island),
        "-CatalogPath",
        str(catalog),
        "-MaintenanceMapPath",
        str(maintenance_map),
    ]
    if expected_sha256:
        command.extend(["-ExpectedSoftwareFoundationSha256", expected_sha256])
    if expected_version:
        command.extend(["-ExpectedSoftwareFoundationVersion", expected_version])
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"updater failed:\nstdout={completed.stdout[-4000:]}\nstderr={completed.stderr[-4000:]}"
        )
    return json.loads(completed.stdout)


def test_catalog_updater_writes_software_foundation_version_from_authority(
    tmp_path: Path,
) -> None:
    fixture = _materialize_fixture_island(tmp_path, glue_version="v3.4")
    glue_sha = _sha256(fixture["tool_glue"])

    receipt = _run_updater(
        island=fixture["island"],
        catalog=fixture["catalog"],
        maintenance_map=fixture["maintenance_map"],
        expected_sha256=glue_sha,
        expected_version="v3.4",
    )

    projection = json.loads(fixture["science_projection"].read_text(encoding="utf-8"))
    software = projection["software_foundation"]
    assert software["version"] == "v3.4"
    assert software["sha256"] == glue_sha
    assert Path(software["path"]).resolve() == fixture["tool_glue"].resolve()
    bindings = receipt["projection_bindings"]
    assert bindings["software_foundation_version"] == "v3.4"
    assert bindings["software_foundation_sha256"] == glue_sha
    assert receipt["authority_text_mutated"] is False


def test_catalog_updater_rejects_version_pin_mismatch(tmp_path: Path) -> None:
    fixture = _materialize_fixture_island(tmp_path, glue_version="v3.4")
    pwsh = _require_pwsh()
    completed = subprocess.run(
        [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATER),
            "-IslandRoot",
            str(fixture["island"]),
            "-CatalogPath",
            str(fixture["catalog"]),
            "-MaintenanceMapPath",
            str(fixture["maintenance_map"]),
            "-ExpectedSoftwareFoundationVersion",
            "v9.9",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    assert completed.returncode != 0
    assert "TOOL_GLUE_CONSTITUTION_VERSION_PIN_MISMATCH" in (completed.stderr + completed.stdout)
    projection = json.loads(fixture["science_projection"].read_text(encoding="utf-8"))
    assert "version" not in projection["software_foundation"]


def test_catalog_updater_is_idempotent_when_version_already_bound(tmp_path: Path) -> None:
    fixture = _materialize_fixture_island(tmp_path, glue_version="v3.4")
    first = _run_updater(
        island=fixture["island"],
        catalog=fixture["catalog"],
        maintenance_map=fixture["maintenance_map"],
    )
    assert first["projection_bindings"]["current_science_projection_changed"] is True
    second = _run_updater(
        island=fixture["island"],
        catalog=fixture["catalog"],
        maintenance_map=fixture["maintenance_map"],
    )
    assert second["projection_bindings"]["current_science_projection_changed"] is False
    projection = json.loads(fixture["science_projection"].read_text(encoding="utf-8"))
    assert projection["software_foundation"]["version"] == "v3.4"
